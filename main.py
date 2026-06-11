import sys
import os
import logging
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from ui.main_window import MainWindow
from core.i18n import set_language


# ── logging ───────────────────────────────────────────────────────────────────
log_path = os.path.join(os.path.expanduser("~"), ".config", "se_downloader", "debug.log")
os.makedirs(os.path.dirname(log_path), exist_ok=True)

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(log_path, encoding="utf-8", mode="w"),
    ]
)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("requests").setLevel(logging.WARNING)

log = logging.getLogger("main")


def read_win_accent_color() -> str:
    """
    Read Windows accent color from the registry.

    Tries multiple sources in priority order:
    1. HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\Accent\AccentColorMenu
       (most accurate — matches taskbar/start menu color)
    2. HKCU\Software\Microsoft\Windows\DWM\AccentColor

    Registry DWORD format: 0xAABBGGRR (little-endian, bytes are R,G,B,A)
    So: R = val & 0xFF, G = (val>>8)&0xFF, B = (val>>16)&0xFF
    """
    if sys.platform != "win32":
        return ""
    try:
        import winreg

        def _read(hive, subkey, value_name):
            try:
                key = winreg.OpenKey(hive, subkey)
                val, _ = winreg.QueryValueEx(key, value_name)
                winreg.CloseKey(key)
                v = val & 0xFFFFFFFF
                r = (v      ) & 0xFF
                g = (v >>  8) & 0xFF
                b = (v >> 16) & 0xFF
                return f"#{r:02X}{g:02X}{b:02X}"
            except Exception:
                return None

        # Source 1: Explorer Accent (most accurate for UI color)
        color = _read(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\Accent",
            "AccentColorMenu"
        )
        if color:
            log.info("Accent color (AccentColorMenu): %s", color)
            return color

        # Source 2: DWM AccentColor
        color = _read(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\DWM",
            "AccentColor"
        )
        if color:
            log.info("Accent color (DWM AccentColor): %s", color)
            return color

    except Exception as e:
        log.debug("Could not read accent color: %s", e)

    return ""


# Init language before any UI is created
from core.settings import AppSettings as _AS
_early = _AS.load()
set_language(_early.language)

log.info("SE Downloader starting, log=%s, lang=%s", log_path, _early.language)

if __name__ == "__main__":
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setApplicationName("SE Downloader")
    app.setApplicationVersion("1.0.0")
    app.setOrganizationName("SEDownloader")

    from qfluentwidgets import setTheme, Theme, setThemeColor
    st = _AS.load()

    # Apply theme (light / dark / auto)
    _theme_map = {"auto": Theme.AUTO, "light": Theme.LIGHT, "dark": Theme.DARK}
    setTheme(_theme_map.get(st.theme, Theme.AUTO))

    if st.theme_color:
        # User picked a custom color — use it
        setThemeColor(st.theme_color)
        log.info("Using custom theme color: %s", st.theme_color)
    else:
        # Follow system: read Windows accent color from registry
        accent = read_win_accent_color()
        if accent:
            setThemeColor(accent)
            log.info("Using system accent color: %s", accent)
        else:
            log.info("No accent color found, using qfluentwidgets default")

    window = MainWindow()
    window.show()
    log.info("Window shown, port=%d", window.settings.browser_listen_port)
    sys.exit(app.exec())
