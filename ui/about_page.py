from PySide6.QtWidgets import QWidget, QVBoxLayout, QFrame
from PySide6.QtCore import Qt
from qfluentwidgets import (
    ScrollArea, TitleLabel, SubtitleLabel, BodyLabel, CaptionLabel,
    CardWidget, PrimaryPushButton, SettingCard, SettingCardGroup,
    FluentIcon, InfoBar, InfoBarPosition
)
from core.i18n import t


class AboutPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAutoFillBackground(False)
        self._setup_ui()

    def _setup_ui(self):
        scroll = ScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet(
            "QScrollArea, QScrollArea > QWidget, QScrollArea > QWidget > QWidget"
            "{ background: transparent; border: none; }"
        )

        box = QWidget()
        box.setAutoFillBackground(False)
        L = QVBoxLayout(box)
        L.setContentsMargins(24, 20, 24, 40)
        L.setSpacing(20)
        L.setAlignment(Qt.AlignTop)
        scroll.setWidget(box)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        L.addWidget(TitleLabel(t("about_title")))

        # App card
        card = CardWidget()
        cl = QVBoxLayout(card)
        cl.setContentsMargins(24, 20, 24, 20)
        cl.setSpacing(6)
        cl.addWidget(SubtitleLabel("SE Downloader"))
        cl.addWidget(BodyLabel(t("about_desc")))
        cl.addWidget(CaptionLabel(f"{t('version')} 1.1.0"))
        cl.addWidget(CaptionLabel(t("built_with")))
        L.addWidget(card)

        # Features — all strings from i18n
        g = SettingCardGroup(t("features"), box)
        feats = [
            (FluentIcon.SPEED_HIGH, "feat_threads_title", "feat_threads_desc"),
            (FluentIcon.SYNC,       "feat_queue_title",   "feat_queue_desc"),
            (FluentIcon.GLOBE,      "feat_browser_title", "feat_browser_desc"),
            (FluentIcon.VPN,        "feat_proxy_title",   "feat_proxy_desc"),
            (FluentIcon.FINGERPRINT,"feat_cookie_title",  "feat_cookie_desc"),
            (FluentIcon.SPEED_OFF,  "feat_speed_title",   "feat_speed_desc"),
            (FluentIcon.BRUSH,      "feat_theme_title",   "feat_theme_desc"),
        ]
        for icon, title_key, desc_key in feats:
            g.addSettingCard(SettingCard(icon, t(title_key), t(desc_key)))
        L.addWidget(g)

        # Browser extension install
        g2 = SettingCardGroup(t("ext_install"), box)
        ext_card = SettingCard(
            FluentIcon.GLOBE, "Chrome / Edge",
            t("ext_install_desc")
        )
        btn = PrimaryPushButton(t("ext_install_btn"), ext_card)
        btn.clicked.connect(self._show_guide)
        ext_card.hBoxLayout.addWidget(btn)
        ext_card.hBoxLayout.addSpacing(16)
        g2.addSettingCard(ext_card)
        L.addWidget(g2)

    def _show_guide(self):
        InfoBar.info(
            t("ext_install"),
            t("ext_install_guide"),
            parent=self, position=InfoBarPosition.TOP, duration=8000,
        )
