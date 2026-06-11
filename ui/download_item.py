import os
from PySide6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QLabel
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from qfluentwidgets import (
    CardWidget, BodyLabel, CaptionLabel,
    TransparentToolButton, FluentIcon, ToolTipFilter,
)
from core.downloader import DownloadTask, DownloadStatus
from core.i18n import t
from ui.segmented_progress_bar import SegmentedProgressBar
from ui.file_icon import get_file_icon, ext_from_filename


def _fmt_size(n):
    if n <= 0: return "?"
    for u in ["B","KB","MB","GB","TB"]:
        if n < 1024: return f"{n:.1f} {u}"
        n /= 1024
    return f"{n:.1f} PB"

def _fmt_speed(bps): return _fmt_size(int(bps)) + "/s"

def _fmt_eta(s):
    """Format ETA — units come from i18n so they switch with language."""
    if s <= 0: return "--"
    s = int(s)
    if s < 60:   return f"{s}s"
    if s < 3600: return f"{s//60}m{s%60:02d}s"
    return f"{s//3600}h{(s%3600)//60}m"


# STATUS_LABELS must NOT be a module-level constant built with t() at import time,
# because the language may not be set yet. Use a function instead.
def _status_label(status: DownloadStatus):
    return {
        DownloadStatus.PENDING:     (t("status_pending"),     "#888888"),
        DownloadStatus.DOWNLOADING: (t("status_downloading"), "#0078D4"),
        DownloadStatus.PAUSED:      (t("status_paused"),      "#FF8C00"),
        DownloadStatus.COMPLETED:   (t("status_completed"),   "#107C10"),
        DownloadStatus.FAILED:      (t("status_failed"),      "#D13438"),
        DownloadStatus.CANCELLED:   (t("status_cancelled"),   "#888888"),
    }.get(status, (t("status_pending"), "#888888"))


class DownloadItemWidget(CardWidget):
    pause_requested       = Signal(str)
    resume_requested      = Signal(str)
    cancel_requested      = Signal(str)
    remove_requested      = Signal(str)
    open_folder_requested = Signal(str)

    def __init__(self, task: DownloadTask, parent=None):
        super().__init__(parent)
        self.task = task
        self._current_ext = ""
        self._setup_ui()
        self.update_from_task(task)

    def _setup_ui(self):
        self.setMinimumHeight(110)
        main = QHBoxLayout(self)
        main.setContentsMargins(16, 10, 12, 10)
        main.setSpacing(12)

        # ── Info column ───────────────────────────────────────────────────────
        info = QVBoxLayout(); info.setSpacing(3)

        # Row 1: icon + filename + status badge
        r1 = QHBoxLayout(); r1.setSpacing(6)
        self.icon_lbl = QLabel()
        self.icon_lbl.setAlignment(Qt.AlignVCenter | Qt.AlignHCenter)
        self.icon_lbl.setScaledContents(False)
        self.icon_lbl.setFixedSize(20, 20)
        r1.addWidget(self.icon_lbl)
        self.filename_lbl = BodyLabel("filename")
        self.filename_lbl.setMaximumWidth(400)
        r1.addWidget(self.filename_lbl)
        self.status_lbl = CaptionLabel("")
        r1.addWidget(self.status_lbl)
        r1.addStretch()
        info.addLayout(r1)

        # Row 2: URL
        self.url_lbl = CaptionLabel("url")
        self.url_lbl.setMaximumWidth(520)
        info.addWidget(self.url_lbl)

        # Row 3: segmented progress bar
        self.prog_bar = SegmentedProgressBar()
        info.addWidget(self.prog_bar)

        # Row 4: stats
        r4 = QHBoxLayout(); r4.setSpacing(14)
        self.speed_lbl = CaptionLabel("--")
        self.eta_lbl   = CaptionLabel("")
        self.size_lbl  = CaptionLabel("")
        self.pct_lbl   = CaptionLabel("0%")
        for w in (self.speed_lbl, self.eta_lbl, self.size_lbl, self.pct_lbl):
            r4.addWidget(w)
        r4.addStretch()
        info.addLayout(r4)

        # Row 5: single-thread notice
        self.notice_lbl = CaptionLabel("")
        self.notice_lbl.setStyleSheet("color: #FF8C00;")
        self.notice_lbl.setVisible(False)
        info.addWidget(self.notice_lbl)

        main.addLayout(info, stretch=1)

        # ── Action buttons ────────────────────────────────────────────────────
        btn = QVBoxLayout(); btn.setAlignment(Qt.AlignCenter); btn.setSpacing(2)
        self.pause_btn  = TransparentToolButton(FluentIcon.PAUSE)
        self.cancel_btn = TransparentToolButton(FluentIcon.CLOSE)
        self.folder_btn = TransparentToolButton(FluentIcon.FOLDER)
        self.remove_btn = TransparentToolButton(FluentIcon.DELETE)
        for b in (self.pause_btn, self.cancel_btn, self.folder_btn, self.remove_btn):
            btn.addWidget(b)
        self.pause_btn.clicked.connect(self._on_pause_resume)
        self.cancel_btn.clicked.connect(lambda: self.cancel_requested.emit(self.task.task_id))
        self.folder_btn.clicked.connect(lambda: self.open_folder_requested.emit(self.task.task_id))
        self.remove_btn.clicked.connect(lambda: self.remove_requested.emit(self.task.task_id))
        main.addLayout(btn)

    def _on_pause_resume(self):
        if self.task.status == DownloadStatus.DOWNLOADING:
            self.pause_requested.emit(self.task.task_id)
        elif self.task.status == DownloadStatus.PAUSED:
            self.resume_requested.emit(self.task.task_id)

    def _update_icon(self, filename: str):
        ext = ext_from_filename(filename) if filename else ""
        if ext == self._current_ext:
            return
        self._current_ext = ext
        try:
            px = get_file_icon(ext, 32)
            if px and not px.isNull():
                self.icon_lbl.setPixmap(
                    px.scaled(20, 20, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                return
        except Exception:
            pass
        self.icon_lbl.clear()

    def update_from_task(self, task: DownloadTask):
        self.task = task

        # Filename + icon
        fname = task.filename or task.url.split("/")[-1] or "?"
        if len(fname) > 52: fname = fname[:49] + "..."
        self.filename_lbl.setText(fname)
        self._update_icon(task.filename or "")

        # URL
        url_text = task.display_url
        if len(url_text) > 74: url_text = url_text[:71] + "..."
        self.url_lbl.setText(url_text)
        self.url_lbl.setToolTip(task.display_url)

        # Status — call _status_label() every time so language is always current
        txt, color = _status_label(task.status)
        self.status_lbl.setText(txt)
        self.status_lbl.setStyleSheet(f"color: {color};")

        # Progress
        self.prog_bar.set_segments(task.segments, task.progress)
        self.pct_lbl.setText(f"{task.progress:.1f}%")

        # Size
        if task.file_size > 0:
            self.size_lbl.setText(
                f"{_fmt_size(task.downloaded)} / {_fmt_size(task.file_size)}")
        else:
            self.size_lbl.setText(_fmt_size(task.downloaded))

        # Speed / ETA
        if task.status == DownloadStatus.DOWNLOADING:
            self.speed_lbl.setText(_fmt_speed(task.speed))
            self.eta_lbl.setText(f"ETA {_fmt_eta(task.eta)}")
        else:
            self.speed_lbl.setText("--")
            self.eta_lbl.setText("")

        # Button tooltips — re-set every update so language switch takes effect
        self.pause_btn.setToolTip(t("pause"))
        self.cancel_btn.setToolTip(t("cancel"))
        self.folder_btn.setToolTip(t("open_folder"))
        self.remove_btn.setToolTip(t("remove"))

        # Single-thread notice
        reason = getattr(task, "single_thread_reason", "")
        if reason:
            display = t(reason) if reason.startswith("single_thread") else reason
            self.notice_lbl.setText(f"⚠ {display}")
            self.notice_lbl.setVisible(True)
            self.setMinimumHeight(126)
        else:
            self.notice_lbl.setVisible(False)
            self.setMinimumHeight(110)

        # Button states
        active = task.status == DownloadStatus.DOWNLOADING
        paused = task.status == DownloadStatus.PAUSED
        done   = task.status in (DownloadStatus.COMPLETED, DownloadStatus.CANCELLED)
        self.pause_btn.setIcon(FluentIcon.PAUSE if active else FluentIcon.PLAY)
        self.pause_btn.setToolTip(t("pause") if active else t("resume"))
        self.pause_btn.setEnabled(active or paused)
        self.cancel_btn.setEnabled(not done)
        if task.error_msg:
            self.setToolTip(task.error_msg[:200])
