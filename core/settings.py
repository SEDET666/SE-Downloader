import json
import os
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Dict


DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)

CONFIG_DIR = Path.home() / ".config" / "se_downloader"
CONFIG_FILE = CONFIG_DIR / "settings.json"


@dataclass
class AppSettings:
    # General
    default_save_path: str = field(
        default_factory=lambda: str(Path.home() / "Downloads")
    )
    default_threads: int = 16
    max_concurrent_downloads: int = 3
    theme: str = "auto"  # auto, light, dark
    theme_color: str = "#0078D4"  # accent color
    language: str = "en_US"  # en_US, zh_CN, ru_RU
    window_geometry: str = ""   # hex-encoded QByteArray, saved on close
    bilibili_cookie: str = ""   # SESSDATA=xxx; bili_jct=xxx; DedeUserID=xxx
    show_tray_icon: bool = True
    minimize_to_tray: bool = True
    start_on_boot: bool = False
    close_to_tray: bool = True

    # Network
    user_agent: str = field(default_factory=lambda: DEFAULT_UA)
    cookies_str: str = ""
    use_proxy: bool = False
    proxy: str = ""  # e.g. http://127.0.0.1:7890
    default_retries: int = 3
    default_timeout: int = 30
    verify_ssl: bool = True

    # Speed limit
    enable_speed_limit: bool = False
    global_speed_limit: int = 0  # bytes/sec

    # Extra request headers (stored as JSON string)
    extra_headers_json: str = "{}"

    # Browser integration
    browser_listen_port: int = 26339
    browser_integration_enabled: bool = True
    intercept_extensions: str = "zip,rar,7z,tar,gz,exe,msi,dmg,pkg,iso,mp4,mp3,mkv,avi,mov,flac,pdf"

    # Notifications
    notify_on_complete: bool = True
    notify_on_error: bool = True

    # File handling
    auto_rename_conflict: bool = True
    create_subfolders: bool = False

    @property
    def extra_headers(self) -> Dict[str, str]:
        try:
            return json.loads(self.extra_headers_json)
        except Exception:
            return {}

    @extra_headers.setter
    def extra_headers(self, val: Dict[str, str]):
        self.extra_headers_json = json.dumps(val, ensure_ascii=False)

    def save(self):
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(asdict(self), f, indent=2, ensure_ascii=False)

    @classmethod
    def load(cls) -> "AppSettings":
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                inst = cls()
                for k, v in data.items():
                    if hasattr(inst, k):
                        setattr(inst, k, v)
                return inst
            except Exception:
                pass
        return cls()
