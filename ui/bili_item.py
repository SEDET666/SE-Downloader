"""
BiliItemWidget — download card for Bilibili video+audio tasks.
Shows video task, audio task status, and merge status separately.
"""

from PySide6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QLabel
from PySide6.QtCore import Qt, Signal
from qfluentwidgets import (
    CardWidget, BodyLabel, CaptionLabel,
    TransparentToolButton, FluentIcon, ToolTipFilter,
    ProgressBar,
)
from core.downloader import DownloadTask, DownloadStatus
from core.i18n import t


def _fmt_size(n):
    if n <= 0: return "?"
    for u in ["B","KB","MB","GB","TB"]:
        if n < 1024: return f"{n:.1f} {u}"
        n /= 1024
    return f"{n:.1f} PB"

def _fmt_speed(bps): return _fmt_size(int(bps)) + "/s"

def _fmt_eta(s):
    if s <= 0: return "--"
    s = int(s)
    if s < 60: return f"{s}s"
    if s < 3600: return f"{s//60}m{s%60:02d}s"
    return f"{s//3600}h{(s%3600)//60}m"


class BiliItemWidget(CardWidget):
    """
    Card for a Bilibili DASH download pair.
    video_task is the primary task (carries bili_audio_url).
    audio_task is tracked separately.
    """
    cancel_requested      = Signal(str)   # video task_id
    remove_requested      = Signal(str)
    open_folder_requested = Signal(str)

    def __init__(self, video_task: DownloadTask, audio_task: DownloadTask, parent=None):
        super().__init__(parent)
        self.video_task = video_task
        self.audio_task = audio_task
        self._setup_ui()
        self.update_tasks(video_task, audio_task)

    def _setup_ui(self):
        self.setMinimumHeight(130)
        main = QHBoxLayout(self)
        main.setContentsMargins(16, 10, 12, 10)
        main.setSpacing(12)

        # B站 badge
        badge = CaptionLabel("📺 B站")
        badge.setStyleSheet(
            "color: white; background: #00a1d6; border-radius: 3px; padding: 1px 5px;"
        )
        badge.setFixedSize(46, 18)

        info = QVBoxLayout(); info.setSpacing(4)

        # Row 1: badge + title
        r1 = QHBoxLayout(); r1.setSpacing(8)
        r1.addWidget(badge)
        self.title_lbl = BodyLabel("title")
        self.title_lbl.setMaximumWidth(420)
        r1.addWidget(self.title_lbl)
        self.status_lbl = CaptionLabel("")
        r1.addWidget(self.status_lbl)
        r1.addStretch()
        info.addLayout(r1)

        # Row 2: video progress
        r2 = QHBoxLayout(); r2.setSpacing(6)
        r2.addWidget(CaptionLabel("🎬"))
        self.v_bar = ProgressBar(); self.v_bar.setRange(0,1000); self.v_bar.setValue(0)
        self.v_bar.setFixedHeight(5)
        r2.addWidget(self.v_bar, 1)
        self.v_pct = CaptionLabel("0%"); self.v_pct.setFixedWidth(38)
        r2.addWidget(self.v_pct)
        info.addLayout(r2)

        # Row 3: audio progress
        r3 = QHBoxLayout(); r3.setSpacing(6)
        r3.addWidget(CaptionLabel("🎵"))
        self.a_bar = ProgressBar(); self.a_bar.setRange(0,1000); self.a_bar.setValue(0)
        self.a_bar.setFixedHeight(5)
        r3.addWidget(self.a_bar, 1)
        self.a_pct = CaptionLabel("0%"); self.a_pct.setFixedWidth(38)
        r3.addWidget(self.a_pct)
        info.addLayout(r3)

        # Row 4: stats
        r4 = QHBoxLayout(); r4.setSpacing(14)
        self.speed_lbl = CaptionLabel("--")
        self.size_lbl  = CaptionLabel("")
        self.eta_lbl   = CaptionLabel("")
        self.merge_lbl = CaptionLabel("")
        for w in (self.speed_lbl, self.size_lbl, self.eta_lbl, self.merge_lbl):
            r4.addWidget(w)
        r4.addStretch()
        info.addLayout(r4)

        main.addLayout(info, 1)

        # Buttons
        btn = QVBoxLayout(); btn.setAlignment(Qt.AlignCenter); btn.setSpacing(2)
        self.cancel_btn = TransparentToolButton(FluentIcon.CLOSE)
        self.folder_btn = TransparentToolButton(FluentIcon.FOLDER)
        self.remove_btn = TransparentToolButton(FluentIcon.DELETE)
        for b, tip in [(self.cancel_btn,"取消"), (self.folder_btn,"打开文件夹"),
                       (self.remove_btn,"移除")]:
            b.setToolTip(tip); b.installEventFilter(ToolTipFilter(b))
            btn.addWidget(b)
        self.cancel_btn.clicked.connect(
            lambda: self.cancel_requested.emit(self.video_task.task_id))
        self.folder_btn.clicked.connect(
            lambda: self.open_folder_requested.emit(self.video_task.task_id))
        self.remove_btn.clicked.connect(
            lambda: self.remove_requested.emit(self.video_task.task_id))
        main.addLayout(btn)

    def update_tasks(self, video_task: DownloadTask, audio_task: DownloadTask):
        self.video_task = video_task
        self.audio_task = audio_task

        # Title from filename
        title = video_task.filename.replace(".video.m4v","") or "B站视频"
        if len(title) > 55: title = title[:52] + "..."
        self.title_lbl.setText(title)

        # Overall status
        ms = video_task.bili_merge_status
        v_done = video_task.status == DownloadStatus.COMPLETED
        a_done = audio_task.status == DownloadStatus.COMPLETED

        if ms == "merged":
            self.status_lbl.setText("✅ 已完成并合并")
            self.status_lbl.setStyleSheet("color: #107C10;")
        elif ms == "merging":
            self.status_lbl.setText("⚙ 合并中...")
            self.status_lbl.setStyleSheet("color: #0078D4;")
        elif ms == "merge_failed":
            self.status_lbl.setText("❌ 合并失败")
            self.status_lbl.setStyleSheet("color: #D13438;")
            self.setToolTip(video_task.error_msg[:200])
        elif v_done and a_done:
            self.status_lbl.setText("⏳ 等待合并")
            self.status_lbl.setStyleSheet("color: #FF8C00;")
        elif (video_task.status == DownloadStatus.DOWNLOADING or
              audio_task.status == DownloadStatus.DOWNLOADING):
            self.status_lbl.setText("下载中")
            self.status_lbl.setStyleSheet("color: #0078D4;")
        elif (video_task.status == DownloadStatus.FAILED or
              audio_task.status == DownloadStatus.FAILED):
            self.status_lbl.setText("❌ 下载失败")
            self.status_lbl.setStyleSheet("color: #D13438;")
        else:
            self.status_lbl.setText(video_task.status.value)
            self.status_lbl.setStyleSheet("color: #888;")

        # Video progress
        vp = video_task.progress
        self.v_bar.setValue(int(vp * 10))
        self.v_pct.setText(f"{vp:.0f}%")

        # Audio progress
        ap = audio_task.progress
        self.a_bar.setValue(int(ap * 10))
        self.a_pct.setText(f"{ap:.0f}%")

        # Speed/size/eta (show whichever is downloading)
        active = None
        if video_task.status == DownloadStatus.DOWNLOADING:
            active = video_task
        elif audio_task.status == DownloadStatus.DOWNLOADING:
            active = audio_task

        if active:
            self.speed_lbl.setText(_fmt_speed(active.speed))
            total = (video_task.file_size or 0) + (audio_task.file_size or 0)
            done  = (video_task.downloaded or 0) + (audio_task.downloaded or 0)
            self.size_lbl.setText(f"{_fmt_size(done)} / {_fmt_size(total)}" if total else _fmt_size(done))
            self.eta_lbl.setText(f"ETA {_fmt_eta(active.eta)}")
        else:
            self.speed_lbl.setText("--")
            self.size_lbl.setText("")
            self.eta_lbl.setText("")

        # Merge notice
        if ms == "merge_failed":
            self.merge_lbl.setText("⚠ 请手动合并")
            self.merge_lbl.setStyleSheet("color: #FF8C00;")
        else:
            self.merge_lbl.setText("")

        # Buttons
        done_all = ms in ("merged", "merge_failed")
        self.cancel_btn.setEnabled(not done_all)
