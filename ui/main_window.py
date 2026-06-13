import sys
import logging
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QObject, Signal, Qt, QProcess
from qfluentwidgets import (
    FluentWindow, NavigationItemPosition, FluentIcon,
    InfoBar, InfoBarPosition, setTheme, Theme, MessageBox
)
from core.settings import AppSettings
from core.i18n import t, get_language, set_language
from core.manager import DownloadManager
from core.browser_server import BrowserIntegrationServer
from ui.download_queue_page import DownloadQueuePage
from ui.settings_page import SettingsPage
from ui.about_page import AboutPage

log = logging.getLogger("main_window")


class _Bridge(QObject):
    """Lives on the main thread. Any thread can emit; slot always runs on main thread."""
    download_received = Signal(str, str, str)   # url, referer, cookies


class MainWindow(FluentWindow):
    def __init__(self):
        # Hide window during construction to prevent flash
        super().__init__()
        self.setAttribute(Qt.WA_DontShowOnScreen, True)
        # Set title and minimum size immediately
        self.setWindowTitle("SE Downloader")
        self.setMinimumSize(960, 640)

        self.settings = AppSettings.load()
        self.manager  = DownloadManager(self.settings)
        self.browser_server = None

        # Create bridge on main thread and connect slot
        self._bridge = _Bridge(self)
        self._bridge.download_received.connect(
            self._handle_browser_download,
            Qt.ConnectionType.QueuedConnection
        )

        self._init_navigation()
        self._apply_theme(self.settings.theme)
        self._init_browser_server()

        # Resize and center AFTER navigation is fully built
        self.resize(1200, 780)
        self._center_on_screen()
        # Re-enable normal display
        self.setAttribute(Qt.WA_DontShowOnScreen, False)

    def _center_on_screen(self):
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(
            screen.x() + (screen.width()  - self.width())  // 2,
            screen.y() + (screen.height() - self.height()) // 2,
        )

    def _apply_theme(self, theme_str: str):
        mapping = {"auto": Theme.AUTO, "light": Theme.LIGHT, "dark": Theme.DARK}
        setTheme(mapping.get(theme_str, Theme.AUTO))

    def _init_navigation(self):
        self.queue_page = DownloadQueuePage(self.manager, self.settings, self)
        self.queue_page.setObjectName("downloadQueuePage")
        self.addSubInterface(self.queue_page, FluentIcon.DOWNLOAD, t("download_queue"),
                             position=NavigationItemPosition.TOP)

        self.settings_page = SettingsPage(self.settings, self)
        self.settings_page.setObjectName("settingsPage")
        self.settings_page.settings_changed.connect(self._on_settings_changed)
        self.addSubInterface(self.settings_page, FluentIcon.SETTING, t("settings"),
                             position=NavigationItemPosition.BOTTOM)

        self.about_page = AboutPage(self)
        self.about_page.setObjectName("aboutPage")
        self.addSubInterface(self.about_page, FluentIcon.INFO, t("about"),
                             position=NavigationItemPosition.BOTTOM)

        self.navigationInterface.setExpandWidth(220)

    def _init_browser_server(self):
        if self.settings.browser_integration_enabled:
            self._start_browser_server()

    def _start_browser_server(self):
        port = self.settings.browser_listen_port
        log.info("Starting browser server on port %d", port)
        self.browser_server = BrowserIntegrationServer(
            port=port,
            on_download_request=self._on_browser_download,
        )
        ok = self.browser_server.start()
        log.info("Browser server started: %s", ok)
        if not ok:
            InfoBar.warning(t("browser_start_failed"),
                t("browser_port_used", port=port),
                parent=self, position=InfoBarPosition.TOP_RIGHT, duration=4000)

    # ── browser integration ───────────────────────────────────────────────────

    def _on_browser_download(self, data: dict):
        """Called from HTTP server thread. Emit signal → main thread."""
        url     = data.get("url", "")
        referer = data.get("referer", "")
        cookies = data.get("cookies", "")
        log.info("_on_browser_download: url=%s", url[:80])
        if not url:
            log.warning("Empty URL, ignoring")
            return
        # Signal emit is thread-safe; QueuedConnection delivers to main thread
        self._bridge.download_received.emit(url, referer, cookies)
        log.info("Signal emitted")

    def _handle_browser_download(self, url: str, referer: str, cookies: str):
        """Slot — always runs on main thread (QueuedConnection)."""
        log.info("_handle_browser_download: url=%s", url[:80])
        self._force_foreground()
        try:
            self.switchTo(self.queue_page)
        except Exception as e:
            log.debug("switchTo: %s", e)
        self.queue_page.add_external_task(url, referer=referer, cookies_str=cookies)

    def _force_foreground(self):
        """Show and forcefully bring window to front."""
        import sys

        if self.isMinimized():
            self.showNormal()
        else:
            self.show()

        if sys.platform == "win32":
            try:
                import ctypes
                user32 = ctypes.windll.user32
                hwnd = int(self.winId())

                HWND_TOPMOST    = -1
                HWND_NOTOPMOST  = -2
                SWP_NOMOVE      = 0x0002
                SWP_NOSIZE      = 0x0001
                SWP_SHOWWINDOW  = 0x0040
                flags = SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW

                # 1. Restore if minimized
                user32.ShowWindow(hwnd, 9)  # SW_RESTORE

                # 2. Set always-on-top temporarily → forces Windows to bring to front
                user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, flags)

                # 3. Remove always-on-top immediately
                user32.SetWindowPos(hwnd, HWND_NOTOPMOST, 0, 0, 0, 0, flags)

                # 4. Final foreground/activate calls
                user32.SetForegroundWindow(hwnd)
                user32.BringWindowToTop(hwnd)
            except Exception as e:
                log.debug("_force_foreground win32 error: %s", e)

        self.raise_()
        self.activateWindow()

    # ── settings ──────────────────────────────────────────────────────────────

    def _on_settings_changed(self):
        self._apply_theme(self.settings.theme)
        if self.browser_server:
            self.browser_server.stop()
        if self.settings.browser_integration_enabled:
            self._start_browser_server()
        # If language changed, restart application to rebuild all UI strings
        from core.i18n import get_language
        if self.settings.language != get_language():
            set_language(self.settings.language)
            self._restart_app()

    def _restart_app(self):
        """Save state and restart the process to apply language change."""
        import sys
        from qfluentwidgets import MessageBox
        self.manager.save()
        if self.browser_server:
            self.browser_server.stop()
        QProcess.startDetached(sys.executable, sys.argv)
        QApplication.quit()

    # ── close ─────────────────────────────────────────────────────────────────

    def showEvent(self, event):
        """Restore saved window geometry on first show."""
        super().showEvent(event)
        geo = self.settings.window_geometry if hasattr(self.settings, "window_geometry") else None
        if geo:
            try:
                from PySide6.QtCore import QByteArray
                self.restoreGeometry(QByteArray.fromHex(geo.encode()))
            except Exception:
                pass

    def closeEvent(self, event):
        # Save window geometry before closing
        try:
            geo_hex = bytes(self.saveGeometry().toHex()).decode()
            self.settings.window_geometry = geo_hex
            self.settings.save()
        except Exception:
            pass
        from core.downloader import DownloadStatus
        from ui.download_queue_page import _three_button_dialog
        active = [t for t in self.manager.get_all_tasks()
                  if t.status == DownloadStatus.DOWNLOADING]

        if active:
            result = _three_button_dialog(
                self,
                t("close_title"),
                t("close_msg", n=len(active)),
                btn_yes=t("pause_exit"),
                btn_no=t("force_exit"),
                btn_cancel=t("misclick"),
            )
            if result is None:      # 我点错了 — 取消关闭
                event.ignore()
                return
            if result:              # 暂停并退出
                self.manager.pause_all()
            # result is False → 直接退出，不暂停

        self.manager.save()
        if self.browser_server:
            self.browser_server.stop()
        event.accept()
        QApplication.quit()
