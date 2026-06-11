<div align="center">

<img src="browser_extension/icons/icon128.png" width="96" alt="SE Downloader Logo"/>

# SE Downloader

**High-speed, multi-threaded segmented download manager**

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![PySide6](https://img.shields.io/badge/PySide6-6.6%2B-41CD52?logo=qt&logoColor=white)](https://doc.qt.io/qtforpython/)
[![QFluentWidgets](https://img.shields.io/badge/QFluentWidgets-1.6%2B-0078D4)](https://qfluentwidgets.com/)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey?logo=windows&logoColor=white)](https://github.com/)
[![Manifest](https://img.shields.io/badge/Extension-Manifest%20V3-4285F4?logo=googlechrome&logoColor=white)](https://developer.chrome.com/docs/extensions/mv3/)
[![i18n](https://img.shields.io/badge/Languages-EN%20%7C%20ZH%20%7C%20RU-orange)](https://github.com/)

English | [中文](#中文说明) | [Русский](#русское-описание)

---

![SE Downloader Screenshot](https://raw.githubusercontent.com/SEDET666/SE-Downloader/main/SE_Downloader_Screenshot.png)

</div>

## ✨ Features

- 🚀 **Multi-threaded segmented download** — up to 64 concurrent threads per task, splits files into segments for maximum speed
- 🔄 **Resume support** — pause and resume downloads at any time; `.seresume` files track per-segment progress
- 🌐 **Browser extension (MV3)** — intercepts downloads in Chrome & Edge using Content-Disposition / Content-Type heuristics, inspired by NeatDownloadManager
- 🗂️ **Download queue** — configurable concurrent task limit; tasks persist across restarts
- 🎨 **Fluent Design UI** — built with QFluentWidgets; light/dark/system theme; custom accent color or system accent (reads from Windows registry)
- 🌍 **Multi-language** — English, 中文 (Simplified Chinese), Русский; auto-restarts to apply
- 🔒 **Cookie & Proxy support** — per-task or global cookies; HTTP/SOCKS5 proxy; optional SSL bypass
- ⚡ **Global speed limit** — token-bucket algorithm enforces the total rate across all threads
- 📁 **System file icons** — shows the OS icon for each file type using `SHGetFileInfo` (Windows)
- 🖥️ **`seget` CLI** — scriptable command-line downloader with the same engine

## 📦 Installation

### Prerequisites

- Python 3.10 or later
- pip

### Steps

```bash
# 1. Clone the repository
git clone https://github.com/SEDET666/SE-Downloader.git
cd se-downloader/se_downloader

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run
python main.py
```

### Browser Extension

1. Open `chrome://extensions` (Chrome) or `edge://extensions` (Edge)
2. Enable **Developer mode** (top-right toggle)
3. Click **Load unpacked**
4. Select the `browser_extension/` folder

The extension requires SE Downloader to be running and listening on the configured port (default **26339**).

## 🖥️ CLI Tool — `seget`

`seget.py` is a standalone command-line downloader using the same segmented engine.

```
Usage: python seget.py <URL> [OPTIONS]

Options:
  -o, --output <name>      Save filename (auto-detected if omitted)
  -d, --dir <path>         Save directory (default: current dir)
  -t, --threads <n>        Thread count (default: 16)
  -r, --retries <n>        Retry count on failure (default: 3)
  --timeout <sec>          Request timeout in seconds (default: 30)
  --speed-limit <KB/s>     Speed cap; 0 = unlimited (default: 0)
  --proxy <url>            Proxy, e.g. http://127.0.0.1:7890
  --cookie <string>        Cookies: key=val; key2=val2
  --referer <url>          Referer header
  --ua <string>            Custom User-Agent
  --no-ssl-verify          Disable SSL certificate verification
  --chs                    Use Chinese interface / 使用中文界面
  -q, --quiet              Suppress progress output
  -h, --help               Show help
```

**Examples:**

```bash
# Basic download
python seget.py https://example.com/file.zip

# Save to ~/Downloads with 32 threads
python seget.py https://example.com/file.zip -d ~/Downloads -t 32

# Speed-limited with proxy
python seget.py https://example.com/video.mp4 --speed-limit 2048 --proxy http://127.0.0.1:7890

# With cookies (e.g. for authenticated content)
python seget.py https://example.com/file.zip --cookie "session=abc123; token=xyz"

# Chinese interface
python seget.py https://example.com/file.zip --chs
```

## 🏗️ Project Structure

```
se_downloader/
├── main.py                      # Entry point — logging, theme, language init
├── seget.py                     # CLI download tool
├── requirements.txt
│
├── core/
│   ├── downloader.py            # SegmentedDownloader engine + DownloadTask model
│   ├── manager.py               # DownloadManager — queue, scheduler, persistence
│   ├── settings.py              # AppSettings dataclass (JSON, ~/.config/se_downloader/)
│   ├── task_store.py            # Task list persistence across restarts
│   ├── browser_server.py        # Local HTTP server for browser extension
│   └── i18n.py                  # Translations: en_US (default), zh_CN, ru_RU
│
├── ui/
│   ├── main_window.py           # FluentWindow, navigation, browser signal bridge
│   ├── download_queue_page.py   # Download list page with filter tabs
│   ├── download_item.py         # Per-task card widget
│   ├── segmented_progress_bar.py# Custom multi-thread progress bar
│   ├── file_icon.py             # System file type icon provider
│   ├── settings_page.py         # Full settings with color picker, language switcher
│   ├── about_page.py            # About page
│   └── new_download_dialog.py   # New download dialog
│
└── browser_extension/           # MV3 Chrome/Edge extension
    ├── manifest.json            # Manifest V3
    ├── background.js            # Service worker — interception engine
    ├── popup.html / popup.js    # Extension popup UI
    ├── options.html / options.js# Extension settings page
    └── icons/                   # Extension icons (16/48/128 px)
```

## ⚙️ Configuration

Settings are stored in:
- **Windows:** `%USERPROFILE%\.config\se_downloader\settings.json`
- **macOS/Linux:** `~/.config/se_downloader/settings.json`

Debug log: `~/.config/se_downloader/debug.log` (overwritten on each launch)

Key settings:

| Setting | Default | Description |
|---------|---------|-------------|
| `default_save_path` | `~/Downloads` | Default directory for new downloads |
| `default_threads` | `16` | Concurrent threads per task |
| `max_concurrent_downloads` | `3` | Max simultaneous tasks |
| `theme` | `auto` | `auto` / `light` / `dark` |
| `theme_color` | `""` | Hex color; empty = follow system accent |
| `language` | `en_US` | `en_US` / `zh_CN` / `ru_RU` |
| `browser_listen_port` | `26339` | Port for browser extension |
| `browser_integration_enabled` | `true` | Enable browser integration server |
| `global_speed_limit` | `0` | KB/s; 0 = unlimited |

## 🔧 How It Works

### Download Engine

1. **Probe** — sends `HEAD` first (fast, no body), falls back to `GET Range: bytes=0-0` to get file size and check range support
2. **Segmented** — if server supports `Accept-Ranges`, pre-allocates the file and spawns N threads each downloading a non-overlapping byte range
3. **Resume** — progress is saved to `<filename>.seresume` every 3 seconds; on restart, each segment continues from its last written offset
4. **Speed limit** — token-bucket algorithm shared across all threads; total throughput never exceeds the configured cap

### Browser Interception (MV3)

The extension uses a four-layer pipeline:

```
onBeforeRequest    → record requestId, URL
onBeforeSendHeaders → record Referer header
onBeforeRedirect   → track redirect chain, update final URL
onHeadersReceived  → judge by Content-Disposition + Content-Type + extension + file size
                     → mark URL in interceptQueue
downloads.onCreated → cancel() the download, send URL to app via fetch (no-cors)
```

Interception logic is inspired by [NeatDownloadManager](https://www.neatdownloadmanager.com/).

## 🌍 Internationalization

To add a new language:

1. Open `core/i18n.py`
2. Add a new entry to `_STRINGS` with your language code (e.g. `"de_DE"`)
3. Add the code and display name to `SUPPORTED_LANGUAGES`
4. Restart the app — it will appear in Settings → Language

## 📋 Requirements

| Package | Version | Purpose |
|---------|---------|---------|
| `PySide6` | ≥ 6.6.0 | Qt bindings for Python |
| `PySide6-Fluent-Widgets[full]` | ≥ 1.6.0 | Fluent Design UI components |
| `requests` | ≥ 2.31.0 | HTTP download engine |

## 🤝 Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/your-feature`)
3. Commit your changes (`git commit -m 'Add your feature'`)
4. Push to the branch (`git push origin feature/your-feature`)
5. Open a Pull Request

Please make sure new UI strings are added to all three languages in `core/i18n.py`.

## 📄 License

This project is licensed under the **GNU General Public License v3.0**.

See [LICENSE](LICENSE) for the full license text.

---

<div align="center">

## 中文说明

</div>

SE Downloader 是一款高速多线程分段下载管理器，基于 PySide6 + QFluentWidgets 构建，支持 Windows / macOS / Linux。

### 主要功能

- 🚀 最多 64 线程分段下载，充分利用带宽
- 🔄 断点续传，随时暂停/继续
- 🌐 浏览器扩展（MV3），自动接管 Chrome/Edge 下载
- 🎨 Fluent Design 界面，支持深色/浅色/系统主题及自定义主题色
- 🌍 支持英语、简体中文、俄语
- ⚡ 令牌桶限速，精准控制总带宽占用
- 🖥️ `seget` 命令行下载工具（加 `--chs` 使用中文界面）

### 安装

```bash
git clone https://github.com/SEDET666/SE-Downloader.git
cd se-downloader/se_downloader
pip install -r requirements.txt
python main.py
```

### 浏览器扩展安装

1. 打开 `chrome://extensions`（Chrome）或 `edge://extensions`（Edge）
2. 开启右上角「开发者模式」
3. 点击「加载已解压的扩展程序」
4. 选择 `browser_extension` 文件夹

---

<div align="center">

## Русское описание

</div>

SE Downloader — высокоскоростной многопоточный менеджер загрузок, построенный на PySide6 + QFluentWidgets. Работает на Windows, macOS и Linux.

### Основные возможности

- 🚀 До 64 потоков на задачу, сегментная загрузка для максимальной скорости
- 🔄 Возобновление загрузки — пауза и продолжение в любой момент
- 🌐 Расширение для браузера (MV3) — перехват загрузок в Chrome и Edge
- 🎨 Интерфейс в стиле Fluent Design с поддержкой тёмной/светлой/системной темы
- 🌍 Поддержка английского, китайского и русского языков
- ⚡ Алгоритм токен-бакет для точного ограничения скорости по всем потокам

### Установка

```bash
git clone https://github.com/SEDET666/SE-Downloader.git
cd se-downloader/se_downloader
pip install -r requirements.txt
python main.py
```

---

<div align="center">

Made with ❤️ using [PySide6](https://doc.qt.io/qtforpython/) and [QFluentWidgets](https://qfluentwidgets.com/)

</div>
