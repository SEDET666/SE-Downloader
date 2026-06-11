import os
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QFileDialog
from PySide6.QtCore import Qt, Signal
from qfluentwidgets import (
    MessageBoxBase, SubtitleLabel, BodyLabel, CaptionLabel,
    LineEdit, SpinBox, TransparentToolButton, FluentIcon,
    InfoBar, InfoBarPosition
)
from core.settings import AppSettings
from core.i18n import t


class NewDownloadDialog(MessageBoxBase):
    download_confirmed = Signal(dict)

    def __init__(self, url: str = "", parent=None, settings: AppSettings = None):
        super().__init__(parent)
        self.settings = settings or AppSettings()
        self._setup_ui(url)

    def _setup_ui(self, url: str):
        self.titleLabel = SubtitleLabel(t("new_task_title"), self)
        self.viewLayout.addWidget(self.titleLabel)

        self.viewLayout.addWidget(BodyLabel(t("url_label")))
        self.url_edit = LineEdit()
        self.url_edit.setPlaceholderText(t("url_placeholder"))
        self.url_edit.setText(url)
        self.url_edit.setMinimumWidth(480)
        self.viewLayout.addWidget(self.url_edit)

        self.viewLayout.addWidget(BodyLabel(t("filename_label")))
        self.filename_edit = LineEdit()
        self.filename_edit.setPlaceholderText(t("filename_placeholder"))
        self.viewLayout.addWidget(self.filename_edit)

        self.viewLayout.addWidget(BodyLabel(t("save_path_label")))
        path_layout = QHBoxLayout()
        self.save_path_edit = LineEdit()
        self.save_path_edit.setText(self.settings.default_save_path)
        self.save_path_edit.setPlaceholderText(t("save_path_placeholder"))
        browse_btn = TransparentToolButton(FluentIcon.FOLDER)
        browse_btn.clicked.connect(self._browse_folder)
        path_layout.addWidget(self.save_path_edit)
        path_layout.addWidget(browse_btn)
        self.viewLayout.addLayout(path_layout)

        self.viewLayout.addWidget(BodyLabel(t("threads_label")))
        self.threads_spin = SpinBox()
        self.threads_spin.setRange(1, 64)
        self.threads_spin.setValue(self.settings.default_threads)
        self.viewLayout.addWidget(self.threads_spin)

        self.viewLayout.addWidget(BodyLabel(t("referer_label")))
        self.referer_edit = LineEdit()
        self.referer_edit.setPlaceholderText(t("referer_placeholder"))
        self.viewLayout.addWidget(self.referer_edit)

        self.viewLayout.addWidget(BodyLabel(t("cookie_label")))
        self.cookie_edit = LineEdit()
        self.cookie_edit.setPlaceholderText(t("cookie_placeholder"))
        self.viewLayout.addWidget(self.cookie_edit)

        self.yesButton.setText(t("start_download"))
        self.cancelButton.setText(t("cancel_btn"))

    def _browse_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self, t("browse"), self.save_path_edit.text()
        )
        if folder:
            self.save_path_edit.setText(folder)

    def validate(self) -> bool:
        if not self.url_edit.text().strip():
            InfoBar.error("URL", t("url_placeholder"),
                parent=self, position=InfoBarPosition.TOP, duration=2000)
            return False
        if not self.save_path_edit.text().strip():
            InfoBar.error(t("save_path_label"), "",
                parent=self, position=InfoBarPosition.TOP, duration=2000)
            return False
        return True

    def get_task_config(self) -> dict:
        return {
            "url": self.url_edit.text().strip(),
            "filename": self.filename_edit.text().strip(),
            "save_path": self.save_path_edit.text().strip(),
            "threads": self.threads_spin.value(),
            "referer": self.referer_edit.text().strip(),
            "cookies_str": self.cookie_edit.text().strip(),
        }
