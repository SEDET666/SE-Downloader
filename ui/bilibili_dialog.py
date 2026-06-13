"""
Bilibili video download dialog.

Shows resolved video URL and audio URL separately.
On confirm, calls manager.add_bili_task() which downloads both and merges with FFmpeg.
"""

import re
import json
import threading
import urllib.request

from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QFrame
from PySide6.QtCore import Qt, Signal, QObject
from qfluentwidgets import (
    MessageBoxBase, SubtitleLabel, BodyLabel, CaptionLabel,
    LineEdit, ComboBox, PrimaryPushButton, PushButton,
    FluentIcon, InfoBar, InfoBarPosition,
    IndeterminateProgressBar, CardWidget, TextEdit,
)

# ── API ───────────────────────────────────────────────────────────────────────

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36")

QUALITY_LABELS = {
    127:"8K 超高清", 126:"杜比视界", 125:"HDR 真彩",
    120:"4K 超清",   116:"1080P 60fps", 112:"1080P 高码率",
    80:"1080P 高清", 74:"720P 60fps",   64:"720P 高清",
    32:"480P 清晰",  16:"360P 流畅",
}


def _make_opener(cookies_str: str = ""):
    """Build an opener with Cookie header and correct UA."""
    import urllib.request
    hdrs = [
        ("User-Agent", UA),
        ("Referer", "https://www.bilibili.com"),
        ("Origin", "https://www.bilibili.com"),
    ]
    if cookies_str:
        hdrs.append(("Cookie", cookies_str))
    opener = urllib.request.build_opener()
    opener.addheaders = hdrs
    return opener


def _req(url, referer="https://www.bilibili.com", cookies_str=""):
    opener = _make_opener(cookies_str)
    req = urllib.request.Request(url)
    req.add_header("Referer", referer)
    with opener.open(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


def _extract_bvid(text):
    text = text.strip()
    m = re.search(r"BV[a-zA-Z0-9]{10,}", text)
    return m.group(0) if m else ""


def _get_streams(bvid, cookies_str=""):
    """
    Fetch available streams.
    Pass SESSDATA cookie for HD qualities (720P+).
    Without login, B站 API only returns up to 480P.
    """
    info = _req(
        f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}",
        cookies_str=cookies_str
    )
    if info.get("code") != 0:
        raise ValueError(f"API {info.get('code')}: {info.get('message')}")
    d     = info["data"]
    title = d["title"]
    cid   = d["cid"]
    aid   = d["aid"]

    # fnval=4048: request DASH + HDR + 4K + AV1
    # qn=127: request highest quality (server caps based on login status)
    play = _req(
        f"https://api.bilibili.com/x/player/wbi/playurl"
        f"?avid={aid}&cid={cid}&qn=127&fnver=0&fnval=4048&fourk=1&platform=pc",
        referer=f"https://www.bilibili.com/video/{bvid}",
        cookies_str=cookies_str,
    )
    if play.get("code") != 0:
        raise ValueError(f"Playurl {play.get('message')}")

    pdata = play["data"]
    streams = []

    dash = pdata.get("dash")
    if dash:
        # Best audio track (highest bitrate)
        best_audio = ""
        for a in sorted(dash.get("audio", []), key=lambda x: x.get("id", 0), reverse=True):
            best_audio = a.get("baseUrl") or a.get("base_url") or ""
            if best_audio: break

        # Deduplicate by quality id, keep first (highest codec quality)
        seen_qn = set()
        for v in dash.get("video", []):
            qn  = v.get("id", 0)
            if qn in seen_qn: continue
            seen_qn.add(qn)
            url = v.get("baseUrl") or v.get("base_url") or ""
            if not url: continue
            streams.append({
                "quality":    qn,
                "label":      QUALITY_LABELS.get(qn, f"{qn}P"),
                "video_url":  url,
                "audio_url":  best_audio,
                "format":     "dash",
            })
    else:
        for u in pdata.get("durl", []):
            qn = pdata.get("quality", 0)
            streams.append({
                "quality":   qn,
                "label":     QUALITY_LABELS.get(qn, f"{qn}P"),
                "video_url": u.get("url",""),
                "audio_url": "",
                "format":    "flv",
            })

    streams.sort(key=lambda x: x["quality"], reverse=True)
    return {"bvid": bvid, "title": title, "streams": streams}


# ── Bridge ────────────────────────────────────────────────────────────────────

class _Bridge(QObject):
    done  = Signal(dict)
    error = Signal(str)


# ── Confirmation dialog ───────────────────────────────────────────────────────

class BiliConfirmDialog(MessageBoxBase):
    """
    Shows video URL and audio URL for confirmation before downloading.
    """
    confirmed = Signal(dict)   # stream dict

    def __init__(self, info: dict, stream: dict, save_path: str, parent=None):
        super().__init__(parent)
        self._info    = info
        self._stream  = stream
        self._save_path = save_path
        self._setup_ui()

    def _setup_ui(self):
        self.titleLabel = SubtitleLabel("确认 B站 下载任务", self)
        self.viewLayout.addWidget(self.titleLabel)

        # Title
        title_lbl = BodyLabel(f"📺  {self._info['title']}")
        title_lbl.setWordWrap(True)
        self.viewLayout.addWidget(title_lbl)

        # Quality
        self.viewLayout.addWidget(
            CaptionLabel(f"画质：{self._stream['label']}  ({self._stream['format'].upper()})")
        )

        # Divider
        line = QFrame(); line.setFrameShape(QFrame.Shape.HLine)
        self.viewLayout.addWidget(line)

        # Video URL
        self.viewLayout.addWidget(BodyLabel("🎬 视频流 URL"))
        self.video_edit = TextEdit()
        self.video_edit.setPlainText(self._stream["video_url"])
        self.video_edit.setFixedHeight(72)
        self.video_edit.setReadOnly(False)  # allow copy
        self.viewLayout.addWidget(self.video_edit)

        # Audio URL
        audio_url = self._stream.get("audio_url", "")
        if audio_url:
            self.viewLayout.addWidget(BodyLabel("🎵 音频流 URL"))
            self.audio_edit = TextEdit()
            self.audio_edit.setPlainText(audio_url)
            self.audio_edit.setFixedHeight(72)
            self.audio_edit.setReadOnly(False)
            self.viewLayout.addWidget(self.audio_edit)

            from core.bili_downloader import ffmpeg_available
            if ffmpeg_available():
                note = CaptionLabel("✅ 检测到 FFmpeg，下载完成后将自动合并为 MP4")
                note.setStyleSheet("color: #107C10;")
                self.viewLayout.addWidget(note)
            else:
                note = CaptionLabel(
                    "⚠ 未检测到 FFmpeg。视频和音频将分开下载，需手动合并。"
                )
                note.setStyleSheet("color: #FF8C00;")
                self.viewLayout.addWidget(note)
                # Auto-install button
                install_row = QHBoxLayout()
                self._install_btn = PushButton("🔧 自动安装 FFmpeg")
                self._install_btn.setFixedWidth(180)
                self._install_btn.clicked.connect(self._install_ffmpeg)
                self._ffmpeg_status = CaptionLabel("")
                install_row.addWidget(self._install_btn)
                install_row.addWidget(self._ffmpeg_status)
                install_row.addStretch()
                w = QWidget(); w.setLayout(install_row)
                self.viewLayout.addWidget(w)
        else:
            self.audio_edit = None

        # Save path
        self.viewLayout.addWidget(BodyLabel("💾 保存目录"))
        self.path_edit = LineEdit()
        self.path_edit.setText(self._save_path)
        self.viewLayout.addWidget(self.path_edit)

        self.yesButton.setText("开始下载")
        self.cancelButton.setText("取消")

    def _install_ffmpeg(self):
        """
        Install FFmpeg:
        1. Fetch latest release zip URL from gyan.dev/ffmpeg API
        2. If user IP is in China, prepend mirror prefix
        3. Download zip, extract ffmpeg.exe to ~/.ffmpeg/bin, add to PATH
        4. Fallback: winget install ffmpeg
        """
        import threading
        self._install_btn.setEnabled(False)
        self._ffmpeg_status.setText("获取下载地址...")

        def _update(msg, color="#888888"):
            from PySide6.QtCore import QMetaObject, Qt, Q_ARG
            QMetaObject.invokeMethod(
                self, "_set_install_status",
                Qt.ConnectionType.QueuedConnection,
                Q_ARG(str, msg), Q_ARG(str, color)
            )

        def _done(ok, msg):
            from PySide6.QtCore import QMetaObject, Qt, Q_ARG
            QMetaObject.invokeMethod(
                self, "_on_install_done",
                Qt.ConnectionType.QueuedConnection,
                Q_ARG(bool, ok), Q_ARG(str, msg)
            )

        def _is_china_ip():
            """Quick check: try to reach a CN-only endpoint."""
            try:
                import urllib.request
                r = urllib.request.urlopen(
                    "https://ipapi.co/country/", timeout=5
                )
                country = r.read().decode().strip()
                return country == "CN"
            except Exception:
                # Fallback: check if github is slow (heuristic)
                try:
                    import urllib.request, time
                    t0 = time.monotonic()
                    urllib.request.urlopen(
                        "https://github.com", timeout=4
                    )
                    return (time.monotonic() - t0) > 3.0
                except Exception:
                    return True  # assume CN if github unreachable

        def _get_download_url():
            """
            Fetch latest ffmpeg release info from gyan.dev API.
            Returns the URL to ffmpeg-release-essentials.zip
            """
            import urllib.request, json
            api = "https://www.gyan.dev/ffmpeg/builds/release-version"
            try:
                with urllib.request.urlopen(api, timeout=10) as r:
                    version = r.read().decode().strip()
            except Exception:
                version = "release"
            # Direct zip download URL from gyan.dev
            zip_url = (
                f"https://github.com/GyanD/codexffmpeg/releases/download/"
                f"{version}/ffmpeg-{version}-essentials_build.zip"
            )
            return zip_url, version

        def _run():
            import sys, os, shutil, zipfile, tempfile, urllib.request, subprocess

            if sys.platform != "win32":
                _done(False, "请使用系统包管理器安装 ffmpeg")
                return

            # ── Step 1: get download URL ──────────────────────────────────────
            _update("获取最新版本信息...")
            try:
                zip_url, version = _get_download_url()
            except Exception as e:
                _done(False, f"获取版本信息失败: {e}")
                return

            # ── Step 2: China mirror ──────────────────────────────────────────
            _update("检测网络环境...")
            china = _is_china_ip()
            if china:
                MIRROR = "https://github.cnxiaobai.com/"
                # Replace https://github.com/ with mirror
                zip_url = zip_url.replace("https://github.com/", MIRROR)
                _update(f"使用国内镜像下载 (v{version})...")
            else:
                _update(f"下载 FFmpeg v{version}...")

            # ── Step 3: download zip ──────────────────────────────────────────
            install_dir = os.path.join(os.path.expanduser("~"), ".ffmpeg", "bin")
            os.makedirs(install_dir, exist_ok=True)

            try:
                tmp_zip = os.path.join(tempfile.gettempdir(), "ffmpeg_install.zip")

                # Download with progress
                def _reporthook(block, block_size, total):
                    if total > 0:
                        pct = min(block * block_size / total * 100, 100)
                        _update(f"下载中 {pct:.0f}%...")

                req = urllib.request.Request(
                    zip_url,
                    headers={"User-Agent": "SE-Downloader/1.0"}
                )
                with urllib.request.urlopen(req, timeout=120) as resp,                      open(tmp_zip, "wb") as f:
                    total = int(resp.headers.get("Content-Length", 0))
                    downloaded = 0
                    while True:
                        chunk = resp.read(65536)
                        if not chunk: break
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total > 0:
                            pct = min(downloaded / total * 100, 100)
                            _update(f"下载中 {pct:.0f}%...")

            except Exception as e:
                # Download failed — try winget fallback
                _update("直接下载失败，尝试 winget...")
                _try_winget(_done, _update)
                return

            # ── Step 4: extract ffmpeg.exe ────────────────────────────────────
            _update("解压中...")
            try:
                with zipfile.ZipFile(tmp_zip, "r") as zf:
                    # Find ffmpeg.exe inside the zip
                    ffmpeg_entry = next(
                        (n for n in zf.namelist()
                         if n.endswith("bin/ffmpeg.exe")), None
                    )
                    if not ffmpeg_entry:
                        raise FileNotFoundError("ffmpeg.exe not found in zip")
                    # Extract just ffmpeg.exe
                    with zf.open(ffmpeg_entry) as src,                          open(os.path.join(install_dir, "ffmpeg.exe"), "wb") as dst:
                        dst.write(src.read())
                os.remove(tmp_zip)
            except Exception as e:
                _update("解压失败，尝试 winget...")
                _try_winget(_done, _update)
                return

            # ── Step 5: add to PATH (user-level) ─────────────────────────────
            _update("配置 PATH...")
            try:
                import winreg
                key = winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    r"Environment", 0,
                    winreg.KEY_READ | winreg.KEY_WRITE
                )
                try:
                    cur_path, _ = winreg.QueryValueEx(key, "PATH")
                except FileNotFoundError:
                    cur_path = ""
                if install_dir.lower() not in cur_path.lower():
                    new_path = cur_path.rstrip(";") + ";" + install_dir if cur_path else install_dir
                    winreg.SetValueEx(key, "PATH", 0, winreg.REG_EXPAND_SZ, new_path)
                winreg.CloseKey(key)
                # Also update current process PATH so shutil.which works immediately
                os.environ["PATH"] = os.environ.get("PATH","") + os.pathsep + install_dir
                # Broadcast WM_SETTINGCHANGE so Explorer picks up new PATH
                import ctypes
                ctypes.windll.user32.SendMessageTimeoutW(
                    0xFFFF, 0x001A, 0,
                    "Environment", 0x0002, 1000, None
                )
            except Exception as e:
                # PATH update failed but exe is there — still works with full path
                pass

            if shutil.which("ffmpeg"):
                _done(True, "✅ FFmpeg 安装成功！")
            else:
                # Exe exists but PATH not refreshed yet
                _done(True, f"✅ FFmpeg 已安装到 {install_dir}，重启程序后生效")

        def _try_winget(done_cb, update_cb):
            import subprocess, shutil
            try:
                update_cb("运行 winget install ffmpeg...")
                r = subprocess.run(
                    ["winget", "install", "ffmpeg",
                     "--accept-package-agreements",
                     "--accept-source-agreements"],
                    capture_output=True, timeout=300
                )
                if r.returncode == 0 and shutil.which("ffmpeg"):
                    done_cb(True, "✅ FFmpeg 安装成功（via winget）！")
                else:
                    done_cb(False,
                        "⚠ 自动安装失败。请手动下载：\n"
                        "https://www.gyan.dev/ffmpeg/builds/")
            except Exception as e:
                done_cb(False, f"winget 失败: {e}")

        threading.Thread(target=_run, daemon=True).start()

    def _set_install_status(self, msg: str, color: str):
        self._ffmpeg_status.setText(msg)
        self._ffmpeg_status.setStyleSheet(f"color: {color};")

    def _on_install_done(self, ok: bool, msg: str):
        self._ffmpeg_status.setText(msg)
        color = "#107C10" if ok else "#FF8C00"
        self._ffmpeg_status.setStyleSheet(f"color: {color};")
        if not ok:
            self._install_btn.setEnabled(True)
            self._install_btn.setText("🔧 重试安装")

    def accept(self):
        # Update URLs from edits (user may have corrected them)
        self._stream["video_url"] = self.video_edit.toPlainText().strip()
        if self.audio_edit:
            self._stream["audio_url"] = self.audio_edit.toPlainText().strip()
        self._stream["save_path"] = self.path_edit.text().strip()
        self.confirmed.emit(self._stream)
        super().accept()


# ── Main parse dialog ─────────────────────────────────────────────────────────

class BilibiliDialog(MessageBoxBase):
    download_ready = Signal(dict, dict, str)  # info, stream, save_path

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self._settings = settings
        self._info = None
        self._bridge = _Bridge(self)
        self._bridge.done.connect(self._on_parsed)
        self._bridge.error.connect(self._on_error)
        self._setup_ui()

    def _setup_ui(self):
        self.titleLabel = SubtitleLabel("解析 B站 视频", self)
        self.viewLayout.addWidget(self.titleLabel)

        self.viewLayout.addWidget(BodyLabel("BV 号 / 视频链接"))
        row = QHBoxLayout()
        self.url_edit = LineEdit()
        self.url_edit.setPlaceholderText("BV1xxxxxxxxxx 或 https://www.bilibili.com/video/BV...")
        self.url_edit.setMinimumWidth(380)
        self.url_edit.returnPressed.connect(self._parse)
        self.parse_btn = PrimaryPushButton("解析")
        self.parse_btn.setFixedWidth(72)
        self.parse_btn.clicked.connect(self._parse)
        row.addWidget(self.url_edit, 1)
        row.addWidget(self.parse_btn)
        self.viewLayout.addLayout(row)

        self.progress = IndeterminateProgressBar(self)
        self.progress.setVisible(False)
        self.viewLayout.addWidget(self.progress)

        self.info_lbl = CaptionLabel("")
        self.info_lbl.setVisible(False)
        self.viewLayout.addWidget(self.info_lbl)

        # Quality selector
        qw = QWidget(); ql = QHBoxLayout(qw)
        ql.setContentsMargins(0, 0, 0, 0)
        ql.addWidget(BodyLabel("画质"))
        self.quality_combo = ComboBox()
        self.quality_combo.setMinimumWidth(220)
        ql.addWidget(self.quality_combo)
        ql.addStretch()
        qw.setVisible(False)
        self.quality_w = qw
        self.viewLayout.addWidget(qw)

        # Show cookie status from global settings
        self._cookie_from_settings = self._settings.bilibili_cookie or ""
        if self._cookie_from_settings:
            note = CaptionLabel("🍪 已从设置读取 B站 Cookie，可解锁高清画质 ✅")
            note.setStyleSheet("color: #107C10;")
        else:
            note = CaptionLabel(
                "⚠ 未设置 B站 Cookie，最高 480P。\n   请在「设置 → B站」中填写 Cookie 后重新解析。"
            )
            note.setStyleSheet("color: #FF8C00;")
        self.viewLayout.addWidget(note)

        self.yesButton.setText("下一步")
        self.cancelButton.setText("取消")
        self.yesButton.setEnabled(False)

    def _parse(self):
        text = self.url_edit.text().strip()
        if not text: return
        bvid = _extract_bvid(text)
        if not bvid:
            InfoBar.error("无效输入", "请输入有效的 BV 号或 B站 视频链接",
                parent=self, position=InfoBarPosition.TOP, duration=3000)
            return

        self.parse_btn.setEnabled(False)
        self.progress.setVisible(True)
        self.quality_w.setVisible(False)
        self.info_lbl.setVisible(False)
        self.yesButton.setEnabled(False)

        bridge = self._bridge
        def _worker():
            try:
                bridge.done.emit(_get_streams(bvid,
                    cookies_str=self._cookie_from_settings))
            except Exception as e:
                bridge.error.emit(str(e))
        threading.Thread(target=_worker, daemon=True).start()

    def _on_parsed(self, info: dict):
        self._info = info
        self.progress.setVisible(False)
        self.parse_btn.setEnabled(True)
        streams = info.get("streams", [])
        if not streams:
            InfoBar.error("解析失败", "未找到可用视频流", parent=self,
                position=InfoBarPosition.TOP, duration=3000)
            return
        self.info_lbl.setText(f"📺  {info['title']}")
        self.info_lbl.setVisible(True)
        self.quality_combo.clear()
        for s in streams:
            label = s["label"]
            if s["format"] == "dash":
                label += "  [DASH - 视频+音频分离]" if s.get("audio_url") else "  [DASH]"
            self.quality_combo.addItem(label, userData=s)
        self.quality_w.setVisible(True)
        self.yesButton.setEnabled(True)

    def _on_error(self, msg: str):
        self.progress.setVisible(False)
        self.parse_btn.setEnabled(True)
        InfoBar.error("解析失败", msg[:150], parent=self,
            position=InfoBarPosition.TOP, duration=5000)

    def validate(self) -> bool:
        return bool(self._info and self.quality_combo.count())

    def accept(self):
        if not self.validate(): return
        stream = self.quality_combo.currentData()
        if not stream: return
        stream = dict(stream)
        stream["_title"]   = self._info.get("title", "")
        stream["_bvid"]    = self._info.get("bvid", "")
        stream["_cookies"] = self._cookie_from_settings
        self.download_ready.emit(self._info, stream, self._settings.default_save_path)
        super().accept()
