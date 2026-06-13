"""Persist download task list across sessions."""
import json, os, time, logging
from pathlib import Path
from typing import List
from core.downloader import DownloadTask, DownloadStatus

log = logging.getLogger(__name__)
STORE_PATH = Path.home() / ".config" / "se_downloader" / "tasks.json"

_KEEP_STATUSES = {
    DownloadStatus.PENDING, DownloadStatus.DOWNLOADING,
    DownloadStatus.PAUSED, DownloadStatus.COMPLETED, DownloadStatus.FAILED
}

def save_tasks(tasks: List[DownloadTask]):
    try:
        STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
        data = []
        for t in tasks:
            if t.status not in _KEEP_STATUSES: continue
            data.append({
                "task_id": t.task_id, "url": t.url, "final_url": t.final_url,
                "save_path": t.save_path, "filename": t.filename,
                "threads": t.threads, "file_size": t.file_size,
                "downloaded": t.downloaded,
                "status": t.status.value, "progress": t.progress,
                "error_msg": t.error_msg, "created_at": t.created_at,
                "started_at": t.started_at, "finished_at": t.finished_at,
                "headers": t.headers, "cookies": t.cookies,
                "speed_limit": t.speed_limit, "proxy": t.proxy,
                "retries": t.retries, "timeout": t.timeout,
                "verify_ssl": t.verify_ssl, "referer": t.referer,
                "single_thread_reason": t.single_thread_reason,
                "bili_audio_url":   t.bili_audio_url,
                "bili_audio_file":  t.bili_audio_file,
                "bili_merge_status": t.bili_merge_status,
            })
        with open(STORE_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception:
        log.exception("save_tasks")

def load_tasks() -> List[DownloadTask]:
    tasks = []
    if not STORE_PATH.exists(): return tasks
    try:
        with open(STORE_PATH, encoding="utf-8") as f:
            data = json.load(f)
        for d in data:
            status_val = d.get("status", "pending")
            # Downloading/Pending tasks become Paused on reload
            if status_val in ("downloading", "pending"):
                status_val = "paused"
            try:
                status = DownloadStatus(status_val)
            except ValueError:
                status = DownloadStatus.PAUSED
            t = DownloadTask(
                task_id=d["task_id"], url=d["url"],
                final_url=d.get("final_url",""), save_path=d["save_path"],
                filename=d.get("filename",""), threads=d.get("threads",16),
                file_size=d.get("file_size",0), downloaded=d.get("downloaded",0),
                status=status, progress=d.get("progress",0.0),
                error_msg=d.get("error_msg",""), created_at=d.get("created_at",time.time()),
                started_at=d.get("started_at",0.0), finished_at=d.get("finished_at",0.0),
                headers=d.get("headers",{}), cookies=d.get("cookies",{}),
                speed_limit=d.get("speed_limit",0), proxy=d.get("proxy",""),
                retries=d.get("retries",3), timeout=d.get("timeout",30),
                verify_ssl=d.get("verify_ssl",True), referer=d.get("referer",""),
                single_thread_reason=d.get("single_thread_reason",""),
                bili_audio_url=d.get("bili_audio_url",""),
                bili_audio_file=d.get("bili_audio_file",""),
                bili_merge_status=d.get("bili_merge_status",""),
            )
            tasks.append(t)
    except Exception:
        log.exception("load_tasks")
    return tasks
