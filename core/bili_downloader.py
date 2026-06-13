"""
Bilibili DASH downloader.

Downloads video and audio streams separately, then merges with FFmpeg.
Falls back to a "merge manually" notice if FFmpeg is not available.
"""

import os
import sys
import shutil
import logging
import threading
import subprocess
import uuid
import time

from core.downloader import (
    DownloadTask, DownloadStatus, SegmentedDownloader
)
from core.settings import AppSettings

log = logging.getLogger(__name__)

BILI_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def make_bili_tasks(
    video_url: str,
    audio_url: str,
    save_path: str,
    title: str,
    bvid: str,
    settings: AppSettings,
    cookies_str: str = "",
) -> tuple:
    """
    Create (video_task, audio_task) for a Bilibili DASH download.
    The video_task carries bili_audio_url so the manager knows to merge after both finish.
    """
    safe_title = title[:80] if title else bvid
    video_filename = safe_title + ".video.m4v"
    audio_filename = safe_title + ".audio.m4a"
    referer = f"https://www.bilibili.com/video/{bvid}"

    # B站CDN需要完整的浏览器请求头，缺一不可
    # Cookie必须放在headers里以字符串形式发送，不能用requests的cookies dict
    # （CDN只认header里的Cookie字符串，不认Set-Cookie机制）
    cookie_header = cookies_str.strip() if cookies_str else ""

    headers = {
        "User-Agent":      BILI_UA,
        "Referer":         referer,
        "Origin":          "https://www.bilibili.com",
        "Accept":          "*/*",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Accept-Encoding": "identity",   # 不压缩，避免解压问题
        "Connection":      "keep-alive",
    }
    if cookie_header:
        headers["Cookie"] = cookie_header

    # B站CDN对分段下载有连接数限制，用较少线程避免触发限速/封锁
    # 同时设置更长超时，B站CDN响应较慢
    bili_threads = min(settings.default_threads, 8)

    video_task = DownloadTask(
        task_id          = str(uuid.uuid4()),
        url              = video_url,
        save_path        = save_path,
        filename         = video_filename,
        threads          = bili_threads,
        headers          = headers,
        cookies          = {},    # Cookie已在headers["Cookie"]里，不重复放
        referer          = referer,
        retries          = max(settings.default_retries, 5),
        timeout          = max(settings.default_timeout, 60),
        verify_ssl       = settings.verify_ssl,
        bili_audio_url   = audio_url,
        bili_audio_file  = audio_filename,
        bili_merge_status= "",
    )

    audio_task = DownloadTask(
        task_id    = str(uuid.uuid4()),
        url        = audio_url,
        save_path  = save_path,
        filename   = audio_filename,
        threads    = bili_threads,
        headers    = headers,
        cookies    = {},
        referer    = referer,
        retries    = max(settings.default_retries, 5),
        timeout    = max(settings.default_timeout, 60),
        verify_ssl = settings.verify_ssl,
    )

    return video_task, audio_task


def merge_bili(video_task: DownloadTask,
               on_status_change=None):
    """
    Called when both video and audio streams are downloaded.
    Runs FFmpeg in a background thread.
    """
    def _run():
        video_path = video_task.full_path
        audio_path = os.path.join(video_task.save_path, video_task.bili_audio_file)
        title = video_task.filename.replace(".video.m4v", "")
        out_path = os.path.join(video_task.save_path, title + ".mp4")

        # Avoid overwriting existing file
        if os.path.exists(out_path):
            base, ext = os.path.splitext(out_path)
            for i in range(1, 10000):
                candidate = f"{base} ({i}){ext}"
                if not os.path.exists(candidate):
                    out_path = candidate
                    break

        video_task.bili_merge_status = "merging"
        if on_status_change:
            on_status_change(video_task)

        try:
            if not ffmpeg_available():
                raise RuntimeError(
                    "FFmpeg not found. Install FFmpeg and add it to PATH, "
                    "then manually merge:\n"
                    f'ffmpeg -i "{video_path}" -i "{audio_path}" -c copy "{out_path}"'
                )

            cmd = [
                "ffmpeg", "-y",
                "-i", video_path,
                "-i", audio_path,
                "-c:v", "copy",
                "-c:a", "copy",
                out_path,
            ]
            log.info("FFmpeg merge: %s", " ".join(cmd))
            result = subprocess.run(
                cmd, capture_output=True, timeout=300
            )
            if result.returncode != 0:
                err = result.stderr.decode("utf-8", errors="replace")[-500:]
                raise RuntimeError(f"FFmpeg exit {result.returncode}: {err}")

            # Clean up temp files
            for p in (video_path, audio_path):
                try:
                    if os.path.exists(p):
                        os.remove(p)
                except OSError:
                    pass

            video_task.bili_merge_status = "merged"
            video_task.filename = os.path.basename(out_path)
            log.info("Merged: %s", out_path)

        except Exception as e:
            log.error("Merge failed: %s", e)
            video_task.bili_merge_status = "merge_failed"
            video_task.error_msg = str(e)

        if on_status_change:
            on_status_change(video_task)

    threading.Thread(target=_run, daemon=True, name="bili-merge").start()
