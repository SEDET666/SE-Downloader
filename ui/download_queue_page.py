"""
Download queue page — bridge callbacks from background threads to Qt main thread.
"""

import os, sys, subprocess
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QFrame
from PySide6.QtCore    import Qt, Signal, QObject, Slot, QTimer
from qfluentwidgets import (
    TitleLabel, BodyLabel,
    PrimaryPushButton, PushButton,
    FluentIcon, ScrollArea, SegmentedWidget,
    InfoBar, InfoBarPosition,
)
from core.downloader import DownloadTask, DownloadStatus
from core.i18n import t
from core.manager    import DownloadManager
from ui.download_item import DownloadItemWidget
from ui.new_download_dialog import NewDownloadDialog
from ui.bilibili_dialog import BilibiliDialog, BiliConfirmDialog
from ui.bili_item import BiliItemWidget


class _Bridge(QObject):
    task_added   = Signal(object)
    task_updated = Signal(object)
    task_removed = Signal(object)



def _three_button_dialog(parent, title: str, content: str,
                         btn_yes: str = "确认",
                         btn_no: str = None,
                         btn_cancel: str = t("misclick")) -> "bool | None":
    """
    Three-button dialog using FluentWidgets.
    Returns:
      True  → user clicked btn_yes
      False → user clicked btn_no
      None  → user clicked btn_cancel (abort / go back)
    """
    from PySide6.QtWidgets import QHBoxLayout
    from qfluentwidgets import MessageBoxBase, SubtitleLabel, BodyLabel
    from qfluentwidgets import PrimaryPushButton, PushButton, TransparentPushButton

    class _Dlg(MessageBoxBase):
        def __init__(self, par):
            super().__init__(par)
            self._result = None
            self.titleLabel = SubtitleLabel(title, self)
            self.viewLayout.addWidget(self.titleLabel)
            self.viewLayout.addWidget(BodyLabel(content, self))

            # Replace default button row
            self.yesButton.hide()
            self.cancelButton.hide()
            btn_row = QHBoxLayout()
            btn_row.setSpacing(8)

            # t("misclick") always on left as transparent/subtle button
            back_btn = TransparentPushButton(btn_cancel, self)
            back_btn.clicked.connect(lambda: (setattr(self, "_result", None), self.reject()))
            btn_row.addWidget(back_btn)
            btn_row.addStretch()

            if btn_no is not None:
                no_btn = PushButton(btn_no, self)
                no_btn.clicked.connect(lambda: (setattr(self, "_result", False), self.accept()))
                btn_row.addWidget(no_btn)

            yes_btn = PrimaryPushButton(btn_yes, self)
            yes_btn.clicked.connect(lambda: (setattr(self, "_result", True), self.accept()))
            btn_row.addWidget(yes_btn)

            self.viewLayout.addLayout(btn_row)

        def result(self):
            return self._result

    dlg = _Dlg(parent)
    dlg.exec()
    return dlg.result()


class DownloadQueuePage(QWidget):

    def __init__(self, manager: DownloadManager, settings, parent=None):
        super().__init__(parent)
        self.setAutoFillBackground(False)
        self.manager  = manager
        self.settings = settings
        self._widgets: dict = {}
        self._bili_widgets: dict = {}  # video_task_id → BiliItemWidget
        self._bili_widgets: dict = {}  # video_task_id → BiliItemWidget
        self._filter  = "all"

        self._bridge = _Bridge(self)
        self._bridge.task_added.connect(self._on_added)
        self._bridge.task_updated.connect(self._on_updated)
        self._bridge.task_removed.connect(self._on_removed)

        self.manager.on_task_added   = self._bridge.task_added.emit
        self.manager.on_task_updated = self._bridge.task_updated.emit
        self.manager.on_task_removed = self._bridge.task_removed.emit

        self._setup_ui()

        # Replay already-loaded tasks to UI (tasks loaded before UI was ready)
        self.manager.replay_to_ui()

    # ── build UI ──────────────────────────────────────────────────────────────

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(16)

        # ── header row ────────────────────────────────────────────────────────
        hdr = QHBoxLayout()
        hdr.addWidget(TitleLabel(t("download_queue")))
        hdr.addStretch()

        self.new_btn = PrimaryPushButton(FluentIcon.DOWNLOAD, t("new_download"))
        self.new_btn.clicked.connect(self._do_new)
        hdr.addWidget(self.new_btn)

        self.bili_btn = PushButton("📺 B站")
        self.bili_btn.setFixedWidth(80)
        self.bili_btn.setToolTip("解析 B站视频")
        self.bili_btn.clicked.connect(self._on_bilibili)
        hdr.addWidget(self.bili_btn)

        self.pause_all_btn = PushButton(FluentIcon.PAUSE, t("pause_all"))
        self.pause_all_btn.clicked.connect(self.manager.pause_all)
        hdr.addWidget(self.pause_all_btn)

        self.resume_all_btn = PushButton(FluentIcon.PLAY, t("resume_all"))
        self.resume_all_btn.clicked.connect(self.manager.resume_all)
        hdr.addWidget(self.resume_all_btn)

        self.clear_btn = PushButton(FluentIcon.DELETE, t("clear_completed"))
        self.clear_btn.clicked.connect(self._do_clear)
        hdr.addWidget(self.clear_btn)

        root.addLayout(hdr)

        # ── filter + stat row (only shown when tasks exist) ───────────────────
        self._filter_row_w = QWidget()
        self._filter_row_w.setAutoFillBackground(False)
        fr = QHBoxLayout(self._filter_row_w)
        fr.setContentsMargins(0, 0, 0, 0)

        self.seg = SegmentedWidget()
        for key, lbl in [("all",t("all")),("downloading",t("downloading")),
                          ("completed",t("completed")),("failed",t("failed"))]:
            self.seg.addItem(key, lbl)
        self.seg.setCurrentItem("all")
        self.seg.currentItemChanged.connect(self._on_filter)
        fr.addWidget(self.seg)
        fr.addStretch()
        self.stat_lbl = BodyLabel("共 0 个任务")
        fr.addWidget(self.stat_lbl)

        root.addWidget(self._filter_row_w)

        # ── scroll area for task cards (only shown when tasks exist) ──────────
        self.scroll = ScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setStyleSheet(
            "QScrollArea, QScrollArea > QWidget, QScrollArea > QWidget > QWidget"
            "{ background: transparent; border: none; }"
        )

        self._queue_w = QWidget()
        self._queue_w.setAutoFillBackground(False)
        self._queue_l = QVBoxLayout(self._queue_w)
        self._queue_l.setContentsMargins(0, 0, 0, 0)
        self._queue_l.setSpacing(8)
        self._queue_l.addStretch()
        self.scroll.setWidget(self._queue_w)

        root.addWidget(self.scroll)

        # ── empty-state label (shown when no tasks) ───────────────────────────
        self.empty_lbl = BodyLabel(t("no_tasks"))
        self.empty_lbl.setAlignment(Qt.AlignCenter)
        root.addWidget(self.empty_lbl)

        self._sync_visibility()

    # ── bridge slots ──────────────────────────────────────────────────────────

    @Slot(object)
    def _on_added(self, task: DownloadTask):
        # Bili audio tasks: attach to existing bili card, don't create new card
        if task.is_bili:
            # This is the VIDEO task — create bili card
            self._add_bili_card(task)
        elif self._is_bili_audio(task.task_id):
            # This is the AUDIO task of a bili pair — skip, bili card handles it
            pass
        else:
            self._add_card(task)
        self._sync_stats()

    @Slot(object)
    def _on_updated(self, task: DownloadTask):
        # Check if this is a bili video task
        bw = self._bili_widgets.get(task.task_id)
        if bw:
            # Update bili card with both tasks
            audio_task = self._get_bili_audio(task.task_id)
            if audio_task:
                bw.update_tasks(task, audio_task)
            self._sync_stats()
            return
        # Check if this is a bili audio task — update parent card
        vid_id = self._find_bili_video_for_audio(task.task_id)
        if vid_id:
            bw = self._bili_widgets.get(vid_id)
            vid_task = self.manager.get_task(vid_id)
            if bw and vid_task:
                bw.update_tasks(vid_task, task)
            return
        w = self._widgets.get(task.task_id)
        if w:
            w.update_from_task(task)
            self._apply_filter(w)
        self._sync_stats()

    @Slot(object)
    def _on_removed(self, task: DownloadTask):
        bw = self._bili_widgets.pop(task.task_id, None)
        if bw:
            self._queue_l.removeWidget(bw)
            bw.deleteLater()
        w = self._widgets.pop(task.task_id, None)
        if w:
            self._queue_l.removeWidget(w)
            w.deleteLater()
        self._sync_stats()

    # ── card management ───────────────────────────────────────────────────────

    def _is_bili_audio(self, task_id: str) -> bool:
        """Check if task_id is an audio task in any bili pair."""
        pairs = getattr(self.manager, "_bili_pairs", {})
        return task_id in pairs.values()

    def _find_bili_video_for_audio(self, audio_id: str):
        """Return video task_id for the given audio task_id."""
        pairs = getattr(self.manager, "_bili_pairs", {})
        for vid, aud in pairs.items():
            if aud == audio_id:
                return vid
        return None

    def _get_bili_audio(self, video_id: str):
        """Return audio DownloadTask for a bili video task."""
        pairs = getattr(self.manager, "_bili_pairs", {})
        audio_id = pairs.get(video_id)
        if audio_id:
            return self.manager.get_task(audio_id)
        return None

    def _add_bili_card(self, video_task: DownloadTask):
        audio_task = self._get_bili_audio(video_task.task_id)
        if not audio_task:
            # Fallback: treat as normal task if audio not found
            self._add_card(video_task)
            return
        w = BiliItemWidget(video_task, audio_task, self._queue_w)
        w.cancel_requested.connect(self._on_cancel_bili)
        w.remove_requested.connect(self._on_remove_bili)
        w.open_folder_requested.connect(self._open_folder)
        self._bili_widgets[video_task.task_id] = w
        # Also register in _widgets so stats/filter work
        self._widgets[video_task.task_id] = w
        self._queue_l.insertWidget(self._queue_l.count() - 1, w)
        self._sync_visibility()

    def _on_cancel_bili(self, video_task_id: str):
        pairs = getattr(self.manager, "_bili_pairs", {})
        audio_id = pairs.get(video_task_id)
        self.manager.cancel_task(video_task_id)
        if audio_id:
            self.manager.cancel_task(audio_id)

    def _on_remove_bili(self, video_task_id: str):
        from core.downloader import DownloadStatus
        video_task = self.manager.get_task(video_task_id)
        pairs = getattr(self.manager, "_bili_pairs", {})
        audio_id = pairs.get(video_task_id)
        audio_task = self.manager.get_task(audio_id) if audio_id else None

        # If merged (fully complete) — just remove, no file deletion dialog
        merged = (video_task and video_task.bili_merge_status == "merged")
        both_done = (
            video_task and video_task.status == DownloadStatus.COMPLETED and
            (not audio_task or audio_task.status == DownloadStatus.COMPLETED)
        )

        if merged or both_done:
            delete = False
        else:
            result = _three_button_dialog(
                self, "移除B站任务",
                "是否同时删除已下载的视频/音频临时文件？",
                btn_yes="删除文件",
                btn_no="仅移除",
                btn_cancel=t("misclick"),
            )
            if result is None:
                return
            delete = result

        self.manager.remove_task(video_task_id, delete_files=delete)
        if audio_id:
            self.manager.remove_task(audio_id, delete_files=delete)
        self._bili_widgets.pop(video_task_id, None)
        self._widgets.pop(video_task_id, None)

    def _add_card(self, task: DownloadTask):
        w = DownloadItemWidget(task, self._queue_w)
        w.pause_requested.connect(self.manager.pause_task)
        w.resume_requested.connect(self.manager.resume_task)
        w.cancel_requested.connect(self._on_cancel_task)
        w.remove_requested.connect(self._on_remove_task)
        w.open_folder_requested.connect(self._open_folder)
        self._widgets[task.task_id] = w
        self._queue_l.insertWidget(self._queue_l.count() - 1, w)
        self._apply_filter(w)
        self._sync_visibility()

    def _apply_filter(self, w):
        s = self._get_task(w).status
        f = self._filter
        vis = (
            True if f == "all" else
            s in (DownloadStatus.DOWNLOADING, DownloadStatus.PENDING, DownloadStatus.PAUSED)
            if f == "downloading" else
            s == DownloadStatus.COMPLETED if f == "completed" else
            s in (DownloadStatus.FAILED, DownloadStatus.CANCELLED)
        )
        w.setVisible(vis)

    def _get_task(self, w):
        """Get the primary task from any widget type."""
        if hasattr(w, "video_task"):  # BiliItemWidget
            return w.video_task
        return w.task

    def _sync_stats(self):
        total  = len(self._widgets)
        active = sum(1 for w in self._widgets.values()
                     if self._get_task(w).status == DownloadStatus.DOWNLOADING)
        self.stat_lbl.setText(t("tasks_count", total=total, active=active))
        self._sync_visibility()

    def _sync_visibility(self):
        """Show scroll+filter only when tasks exist; show empty label otherwise."""
        has = bool(self._widgets)
        self._filter_row_w.setVisible(has)
        self.scroll.setVisible(has)
        self.empty_lbl.setVisible(not has)

    # ── actions ───────────────────────────────────────────────────────────────

    def _on_filter(self, key: str):
        self._filter = key
        for w in self._widgets.values():
            self._apply_filter(w)

    def _on_bilibili(self):
        dlg = BilibiliDialog(self.settings, self)
        dlg.download_ready.connect(self._on_bilibili_ready)
        dlg.exec()

    def _on_bilibili_ready(self, info: dict, stream: dict, save_path: str):
        """Show confirmation dialog with video URL + audio URL."""
        dlg = BiliConfirmDialog(info, stream, save_path, self)
        dlg.confirmed.connect(self._on_bilibili_confirmed)
        dlg.exec()

    def _on_bilibili_confirmed(self, stream: dict):
        """User confirmed — add bili task pair to manager."""
        import os
        save_path = stream.get("save_path", self.settings.default_save_path)
        os.makedirs(save_path, exist_ok=True)
        self.manager.add_bili_task(
            video_url   = stream["video_url"],
            audio_url   = stream.get("audio_url", ""),
            save_path   = save_path,
            title       = stream.get("_title", "bilibili_video"),
            bvid        = stream.get("_bvid", ""),
            cookies_str = stream.get("_cookies", ""),
        )

    def _do_new(self):
        dlg = NewDownloadDialog(parent=self, settings=self.settings)
        if dlg.exec():
            cfg = dlg.get_task_config()
            extra: dict = {}
            for pair in (cfg.get("cookies_str") or "").split(";"):
                pair = pair.strip()
                if "=" in pair:
                    k, v = pair.split("=", 1)
                    extra[k.strip()] = v.strip()
            self.manager.add_task(
                url=cfg["url"], save_path=cfg["save_path"],
                filename=cfg.get("filename",""),
                threads=cfg.get("threads", self.settings.default_threads),
                cookies=extra or None, referer=cfg.get("referer",""),
            )

    def _on_cancel_task(self, task_id: str):
        from core.downloader import DownloadStatus
        task = self.manager.get_task(task_id)
        if task and task.status in (DownloadStatus.DOWNLOADING, DownloadStatus.PAUSED):
            result = _three_button_dialog(
                self, t("cancel_download"),
                "取消此下载任务，请选择如何处理临时文件：",
                btn_yes=t("delete_files"),
                btn_no=t("cancel_only"),
                btn_cancel=t("misclick"),
            )
            if result is None:   # 我点错了
                return
            delete = result      # True=删除, False=仅取消
        else:
            delete = False
        self.manager.cancel_task(task_id, delete_files=delete)


    def _on_remove_task(self, task_id: str):
        from core.downloader import DownloadStatus
        task = self.manager.get_task(task_id)
        if task and task.status not in (DownloadStatus.COMPLETED, DownloadStatus.CANCELLED):
            result = _three_button_dialog(
                self, t("remove_task"),
                "移除此下载任务，请选择如何处理临时文件：",
                btn_yes=t("delete_files"),
                btn_no=t("remove_only"),
                btn_cancel=t("misclick"),
            )
            if result is None:
                return
            delete = result
        else:
            result = _three_button_dialog(
                self, t("remove_task"),
                t("remove_done_msg"),
                btn_yes=t("confirm_remove"),
                btn_no=None,
                btn_cancel=t("misclick"),
            )
            if result is None:
                return
            delete = False
        self.manager.remove_task(task_id, delete_files=delete)


    def _do_clear(self):
        self.manager.clear_completed()
        InfoBar.success(t("clear_completed"), "",
                        parent=self, position=InfoBarPosition.TOP, duration=2000)

    def _open_folder(self, task_id: str):
        task = self.manager.get_task(task_id)
        if not task or not os.path.exists(task.save_path):
            return
        if sys.platform == "win32":
            os.startfile(task.save_path)
        elif sys.platform == "darwin":
            subprocess.run(["open", task.save_path])
        else:
            subprocess.run(["xdg-open", task.save_path])

    def add_external_task(self, url: str, referer: str = "", cookies_str: str = ""):
        dlg = NewDownloadDialog(url=url, parent=self, settings=self.settings)
        # Pre-fill referer if provided by browser extension
        if referer and not dlg.referer_edit.text():
            dlg.referer_edit.setText(referer)
        # Pre-fill cookies from browser extension
        if cookies_str and not dlg.cookie_edit.text():
            dlg.cookie_edit.setText(cookies_str)
        if dlg.exec():
            cfg = dlg.get_task_config()
            if cfg.get("url"):
                self.manager.add_task(**cfg)
