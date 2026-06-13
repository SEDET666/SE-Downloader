import os
import json
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QFileDialog, QFrame
from PySide6.QtCore import Qt, Signal
from qfluentwidgets import (
    CheckBox,
    ColorPickerButton,
    ScrollArea, TitleLabel, BodyLabel, CaptionLabel, SubtitleLabel,
    SettingCard,
    PushSettingCard, SwitchSettingCard,
    PrimaryPushButton, PushButton,
    LineEdit, SpinBox, ComboBox, TextEdit,
    SwitchButton, FluentIcon,
    InfoBar, InfoBarPosition
)
from core.settings import AppSettings
from core.i18n import t, set_language, SUPPORTED_LANGUAGES, get_language
from ui.collapsible_group import CollapsibleSettingGroup


# ── Reusable card helpers ─────────────────────────────────────────────────────

class LineSettingCard(SettingCard):
    """SettingCard with an embedded LineEdit."""
    def __init__(self, icon, title, content, placeholder="", parent=None):
        super().__init__(icon, title, content, parent)
        self.line = LineEdit(self)
        self.line.setPlaceholderText(placeholder)
        self.line.setMinimumWidth(260)
        self.hBoxLayout.addWidget(self.line)
        self.hBoxLayout.addSpacing(16)

    def value(self) -> str:  return self.line.text()
    def setValue(self, v):   self.line.setText(str(v))


class SpinSettingCard(SettingCard):
    """SettingCard with an embedded SpinBox."""
    def __init__(self, icon, title, content, lo=0, hi=9999, parent=None):
        super().__init__(icon, title, content, parent)
        self.spin = SpinBox(self)
        self.spin.setRange(lo, hi)
        self.spin.setFixedWidth(120)
        self.hBoxLayout.addWidget(self.spin)
        self.hBoxLayout.addSpacing(16)

    def value(self) -> int: return self.spin.value()
    def setValue(self, v):  self.spin.setValue(int(v))


class SwitchSettingCardCustom(SettingCard):
    """SettingCard with an embedded SwitchButton."""
    toggled = Signal(bool)

    def __init__(self, icon, title, content, parent=None):
        super().__init__(icon, title, content, parent)
        self._sw = SwitchButton(self)
        self._sw.checkedChanged.connect(self.toggled)
        self.hBoxLayout.addWidget(self._sw)
        self.hBoxLayout.addSpacing(16)

    def isChecked(self) -> bool: return self._sw.isChecked()
    def setChecked(self, v):     self._sw.setChecked(bool(v))



class _TextAreaCard(SettingCard):
    """SettingCard with a TextEdit below the title row."""
    def __init__(self, icon, title, desc, placeholder="", parent=None):
        super().__init__(icon, title, desc, parent)
        self.edit = TextEdit(self)
        self.edit.setPlaceholderText(placeholder)
        self.edit.setFixedHeight(72)
        # SettingCard uses hBoxLayout; we need to insert a sub-VBox
        vl = QVBoxLayout()
        vl.setContentsMargins(0, 4, 16, 8)
        vl.setSpacing(0)
        vl.addWidget(self.edit)
        self.hBoxLayout.addLayout(vl)

    def value(self): return self.edit.toPlainText()
    def setValue(self, v): self.edit.setPlainText(str(v) if v else "")


# ── Page ─────────────────────────────────────────────────────────────────────

class SettingsPage(QWidget):
    settings_changed = Signal()

    def __init__(self, settings: AppSettings, parent=None):
        super().__init__(parent)
        self.setAutoFillBackground(False)
        self.settings = settings
        self._setup_ui()
        self._restore_group_states()
        self._connect_group_signals()
        self._load()

    def _setup_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = ScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet(
            "QScrollArea, QScrollArea > QWidget, QScrollArea > QWidget > QWidget"
            "{ background: transparent; border: none; }"
        )
        outer.addWidget(scroll)

        box = QWidget()
        box.setAutoFillBackground(False)
        scroll.setWidget(box)
        L = QVBoxLayout(box)
        L.setContentsMargins(24, 20, 24, 40)
        L.setSpacing(16)
        L.setAlignment(Qt.AlignTop)
        L.addWidget(TitleLabel(t("settings_title")))

        # ── 常规 ────────────────────────────────────────────
        self.g_general = CollapsibleSettingGroup(FluentIcon.SETTING, t("general"), box, expanded=True)
        g = self.g_general

        self.save_path_card = PushSettingCard(
            t("browse"), FluentIcon.FOLDER, t("default_save_path"),
            t("default_save_path_desc")
        )
        self.save_path_card.clicked.connect(self._browse_save)
        g.addSettingCard(self.save_path_card)

        self.threads_card = SpinSettingCard(
            FluentIcon.SPEED_HIGH, t("default_threads"),
            t("default_threads_desc"), 1, 64
        )
        g.addSettingCard(self.threads_card)

        self.concurrent_card = SpinSettingCard(
            FluentIcon.SYNC, t("max_concurrent"),
            t("max_concurrent_desc"), 1, 20
        )
        g.addSettingCard(self.concurrent_card)

        self.theme_card = SettingCard(
            FluentIcon.BRUSH, t("theme"), t("theme_desc")
        )
        self.theme_combo = ComboBox(self.theme_card)
        self.theme_combo.addItems([t("theme_auto"), t("theme_light"), t("theme_dark")])
        self.theme_combo.setFixedWidth(120)
        self.theme_card.hBoxLayout.addWidget(self.theme_combo)
        self.theme_card.hBoxLayout.addSpacing(16)
        g.addSettingCard(self.theme_card)

        # Theme color picker + "follow system" checkbox
        self.color_card = SettingCard(
            FluentIcon.PALETTE, t("theme_color"), t("theme_color_desc")
        )
        self.color_follow_sys = CheckBox(t("theme_auto"), self.color_card)
        self.color_follow_sys.setChecked(True)
        self.color_btn = ColorPickerButton(
            "#0078D4", t("theme_color"), self.color_card, enableAlpha=False
        )
        self.color_btn.setEnabled(False)   # disabled by default (follow system)
        self.color_card.hBoxLayout.addWidget(self.color_follow_sys)
        self.color_card.hBoxLayout.addSpacing(8)
        self.color_card.hBoxLayout.addWidget(self.color_btn)
        self.color_card.hBoxLayout.addSpacing(16)
        self.color_follow_sys.stateChanged.connect(self._on_color_follow_changed)
        g.addSettingCard(self.color_card)

        # Language
        self.lang_card = SettingCard(
            FluentIcon.LANGUAGE, t("language"), t("language_desc")
        )
        self.lang_combo = ComboBox(self.lang_card)
        for code, name in SUPPORTED_LANGUAGES.items():
            self.lang_combo.addItem(name, userData=code)
        self.lang_combo.setFixedWidth(160)
        self.lang_card.hBoxLayout.addWidget(self.lang_combo)
        self.lang_card.hBoxLayout.addSpacing(16)
        g.addSettingCard(self.lang_card)

        L.addWidget(g)

        # ── 网络 ────────────────────────────────────────────
        self.g_network = CollapsibleSettingGroup(FluentIcon.WIFI, t("network"), box, expanded=False)
        g = self.g_network

        self.ua_card = LineSettingCard(
            FluentIcon.GLOBE, "User-Agent",
            t("user_agent_desc"),
            "Mozilla/5.0 ..."
        )
        g.addSettingCard(self.ua_card)

        self.retries_card = SpinSettingCard(
            FluentIcon.ROTATE, t("retries"),
            t("retries_desc"), 0, 20
        )
        g.addSettingCard(self.retries_card)

        self.timeout_card = SpinSettingCard(
            FluentIcon.HISTORY, t("timeout"),
            t("timeout_desc"), 5, 300
        )
        g.addSettingCard(self.timeout_card)

        self.ssl_card = SwitchSettingCardCustom(
            FluentIcon.CERTIFICATE, t("verify_ssl"),
            t("verify_ssl_desc")
        )
        g.addSettingCard(self.ssl_card)

        L.addWidget(g)

        # ── Cookie & 请求头 ──────────────────────────────────
        self.g_cookies = CollapsibleSettingGroup(FluentIcon.FINGERPRINT, t("cookies_headers"), box, expanded=False)
        g = self.g_cookies

        # Cookie card: title row + TextEdit below
        cookie_card = _TextAreaCard(
            FluentIcon.FINGERPRINT, t("global_cookie"), t("global_cookie_desc"),
            "key=value; key2=value2; ..."
        )
        self.cookie_edit = cookie_card.edit
        g.addSettingCard(cookie_card)

        # Headers card: title row + TextEdit below
        hdr_card = _TextAreaCard(
            FluentIcon.CODE, t("custom_headers"), t("custom_headers_desc"),
            '{"X-Custom-Header": "value"}'
        )
        self.headers_edit = hdr_card.edit
        g.addSettingCard(hdr_card)

        L.addWidget(g)

        # ── 代理 ────────────────────────────────────────────
        self.g_proxy = CollapsibleSettingGroup(FluentIcon.VPN, t("proxy"), box, expanded=False)
        g = self.g_proxy

        self.proxy_sw = SwitchSettingCardCustom(
            FluentIcon.VPN, t("enable_proxy"),
            t("enable_proxy_desc")
        )
        g.addSettingCard(self.proxy_sw)

        self.proxy_url = LineSettingCard(
            FluentIcon.LINK, t("proxy_url"),
            t("proxy_url_desc"),
            "http://127.0.0.1:7890"
        )
        g.addSettingCard(self.proxy_url)

        L.addWidget(g)

        # ── 限速 ────────────────────────────────────────────
        self.g_speed = CollapsibleSettingGroup(FluentIcon.SPEED_OFF, t("speed_limit"), box, expanded=False)
        g = self.g_speed

        self.speed_sw = SwitchSettingCardCustom(
            FluentIcon.SPEED_HIGH, t("enable_speed_limit"),
            t("enable_speed_limit_desc")
        )
        g.addSettingCard(self.speed_sw)

        self.speed_card = SpinSettingCard(
            FluentIcon.SPEED_OFF, t("speed_limit_val"),
            t("speed_limit_val_desc"), 0, 1048576
        )
        g.addSettingCard(self.speed_card)

        L.addWidget(g)

        # ── 浏览器接管 ───────────────────────────────────────
        self.g_browser = CollapsibleSettingGroup(FluentIcon.GLOBE, t("browser_integration"), box, expanded=False)
        g = self.g_browser

        self.browser_sw = SwitchSettingCardCustom(
            FluentIcon.GLOBE, t("enable_browser"),
            t("enable_browser_desc")
        )
        g.addSettingCard(self.browser_sw)

        self.browser_port = SpinSettingCard(
            FluentIcon.IOT, t("browser_port"),
            t("browser_port_desc"),
            1024, 65535
        )
        g.addSettingCard(self.browser_port)

        self.intercept_ext = LineSettingCard(
            FluentIcon.FILTER, t("intercept_ext"),
            t("intercept_ext_desc"),
            "zip,rar,7z,exe,mp4,mp3,..."
        )
        g.addSettingCard(self.intercept_ext)

        L.addWidget(g)

        # ── B站设置 ──────────────────────────────────────────
        self.g_bili = CollapsibleSettingGroup(FluentIcon.VIDEO, "B站 (Bilibili)", box, expanded=False)
        g = self.g_bili

        self.bili_cookie_card = _TextAreaCard(
            FluentIcon.FINGERPRINT, "B站 Cookie",
            "SESSDATA=xxx; bili_jct=xxx; DedeUserID=xxx  (用于解锁高清画质)",
            "SESSDATA=xxxxxx; bili_jct=xxxxxx; DedeUserID=xxxxxx"
        )
        self.bili_cookie_card.edit.setFixedHeight(56)
        g.addSettingCard(self.bili_cookie_card)

        bili_note = SettingCard(
            FluentIcon.INFO, "如何获取 Cookie",
            "浏览器登录B站 → F12 → Application → Cookies → bilibili.com"
        )
        g.addSettingCard(bili_note)

        L.addWidget(g)

        # ── 通知 ────────────────────────────────────────────
        self.g_notif = CollapsibleSettingGroup(FluentIcon.RINGER, t("notifications"), box, expanded=False)
        g = self.g_notif

        self.notify_done = SwitchSettingCardCustom(
            FluentIcon.COMPLETED, t("notify_complete"),
            t("notify_complete_desc")
        )
        g.addSettingCard(self.notify_done)

        self.notify_err = SwitchSettingCardCustom(
            FluentIcon.INFO, t("notify_error"),
            t("notify_error_desc")
        )
        g.addSettingCard(self.notify_err)

        L.addWidget(g)

        # ── 文件处理 ─────────────────────────────────────────
        self.g_files = CollapsibleSettingGroup(FluentIcon.FOLDER, t("file_handling"), box, expanded=False)
        g = self.g_files

        self.auto_rename = SwitchSettingCardCustom(
            FluentIcon.EDIT, t("auto_rename"),
            t("auto_rename_desc")
        )
        g.addSettingCard(self.auto_rename)

        L.addWidget(g)

        # ── 保存按钮 ─────────────────────────────────────────
        row = QHBoxLayout()
        row.addStretch()
        save_btn = PrimaryPushButton(FluentIcon.SAVE, t("save_settings"))
        save_btn.setFixedWidth(140)
        save_btn.clicked.connect(self._save)
        row.addWidget(save_btn)
        L.addLayout(row)

    # ── Load / Save ───────────────────────────────────────────
    # ── Group state persistence ──────────────────────────────────────────────

    _GROUP_ATTRS = ["g_general","g_network","g_cookies","g_proxy",
                    "g_speed","g_browser","g_bili","g_notif","g_files"]

    def _restore_group_states(self):
        """Restore expand/collapse state from QSettings."""
        from PySide6.QtCore import QSettings
        qs = QSettings("SEDownloader", "SE Downloader")
        for key in self._GROUP_ATTRS:
            group = getattr(self, key, None)
            if group is None:
                continue
            saved = qs.value(f"settings_group/{key}")
            if saved is None:
                continue
            expanded = str(saved).lower() in ("true", "1")
            if expanded != group._expanded:
                group._expanded = expanded
                group._content_wrap.setVisible(expanded)
                group._divider.setVisible(expanded)
                group._arrow.set_angle(90.0 if expanded else 0.0)

    def _connect_group_signals(self):
        """Connect expand/collapse signals to save state."""
        for key in self._GROUP_ATTRS:
            group = getattr(self, key, None)
            if group:
                # Capture key in closure
                group.expanded_changed.connect(
                    lambda expanded, k=key: self._save_group_state(k, expanded)
                )

    def _save_group_state(self, key: str, expanded: bool):
        from PySide6.QtCore import QSettings
        qs = QSettings("SEDownloader", "SE Downloader")
        qs.setValue(f"settings_group/{key}", expanded)

    def _on_color_follow_changed(self, state):
        follow = bool(state)
        self.color_btn.setEnabled(not follow)
        if follow:
            from qfluentwidgets import setThemeColor
            try:
                from main import read_win_accent_color
                accent = read_win_accent_color()
                if accent:
                    setThemeColor(accent)
            except Exception:
                pass

    def _load(self):
        s = self.settings
        self.save_path_card.setContent(s.default_save_path)
        self.threads_card.setValue(s.default_threads)
        self.concurrent_card.setValue(s.max_concurrent_downloads)
        self.theme_combo.setCurrentIndex({"auto": 0, "light": 1, "dark": 2}.get(s.theme, 0))
        self.ua_card.setValue(s.user_agent)
        self.retries_card.setValue(s.default_retries)
        self.timeout_card.setValue(s.default_timeout)
        self.ssl_card.setChecked(s.verify_ssl)
        self.cookie_edit.setPlainText(s.cookies_str)
        self.headers_edit.setPlainText(s.extra_headers_json)
        self.proxy_sw.setChecked(s.use_proxy)
        self.proxy_url.setValue(s.proxy)
        self.speed_sw.setChecked(s.enable_speed_limit)
        self.speed_card.setValue(s.global_speed_limit // 1024)
        self.browser_sw.setChecked(s.browser_integration_enabled)
        self.browser_port.setValue(s.browser_listen_port)
        self.intercept_ext.setValue(s.intercept_extensions)
        self.notify_done.setChecked(s.notify_on_complete)
        self.notify_err.setChecked(s.notify_on_error)
        self.auto_rename.setChecked(s.auto_rename_conflict)
        self.bili_cookie_card.setValue(s.bilibili_cookie or "")
        # Color — "follow system" means theme_color is empty
        follow_sys = not s.theme_color
        self.color_follow_sys.setChecked(follow_sys)
        self.color_btn.setEnabled(not follow_sys)
        try:
            from PySide6.QtGui import QColor
            self.color_btn.setColor(QColor(s.theme_color or "#0078D4"))
        except Exception:
            pass
        # Language
        for i in range(self.lang_combo.count()):
            if self.lang_combo.itemData(i) == s.language:
                self.lang_combo.setCurrentIndex(i)
                break

    def _browse_save(self):
        folder = QFileDialog.getExistingDirectory(
            self, t("default_save_path"), self.settings.default_save_path
        )
        if folder:
            self.settings.default_save_path = folder
            self.save_path_card.setContent(folder)

    def _save(self):
        s = self.settings
        _prev_lang = s.language
        s.default_threads          = self.threads_card.value()
        s.max_concurrent_downloads = self.concurrent_card.value()
        s.theme = {0: "auto", 1: "light", 2: "dark"}.get(self.theme_combo.currentIndex(), "auto")
        s.user_agent               = self.ua_card.value()
        s.default_retries          = self.retries_card.value()
        s.default_timeout          = self.timeout_card.value()
        s.verify_ssl               = self.ssl_card.isChecked()
        s.cookies_str              = self.cookie_edit.toPlainText().strip()
        raw_hdr = self.headers_edit.toPlainText().strip()
        s.extra_headers_json       = raw_hdr if raw_hdr else "{}"
        s.use_proxy                = self.proxy_sw.isChecked()
        s.proxy                    = self.proxy_url.value()
        s.enable_speed_limit       = self.speed_sw.isChecked()
        s.global_speed_limit       = self.speed_card.value() * 1024
        s.browser_integration_enabled = self.browser_sw.isChecked()
        s.browser_listen_port      = self.browser_port.value()
        s.intercept_extensions     = self.intercept_ext.value()
        s.notify_on_complete       = self.notify_done.isChecked()
        s.notify_on_error          = self.notify_err.isChecked()
        s.auto_rename_conflict     = self.auto_rename.isChecked()
        s.bilibili_cookie          = self.bili_cookie_card.value().strip()
        try:
            if self.color_follow_sys.isChecked():
                s.theme_color = ""   # empty = follow system accent color
            else:
                s.theme_color = self.color_btn.color.name()
        except Exception:
            pass
        lang_idx = self.lang_combo.currentIndex()
        if lang_idx >= 0:
            s.language = self.lang_combo.itemData(lang_idx) or "zh_CN"
        s.save()

        from qfluentwidgets import setTheme, Theme, setThemeColor
        setTheme({"auto": Theme.AUTO, "light": Theme.LIGHT, "dark": Theme.DARK}.get(s.theme, Theme.AUTO))
        if s.theme_color:   # only override if user picked a custom color
            try:
                setThemeColor(s.theme_color)
            except Exception:
                pass
        set_language(s.language)
        self.settings_changed.emit()
        InfoBar.success(
            t("settings_saved"), t("settings_saved_desc"),
            parent=self, position=InfoBarPosition.TOP, duration=2000
        )
        # If language changed, prompt restart
        if s.language != _prev_lang:
            InfoBar.warning(
                "Language Changed" if s.language == "en_US" else
                "Язык изменён" if s.language == "ru_RU" else t("settings_saved"),
                t("language_desc"),
                parent=self, position=InfoBarPosition.TOP, duration=5000
            )
