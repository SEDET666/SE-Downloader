#!/usr/bin/env python3
"""
seget.py — SE Downloader 命令行下载工具

用法:
  python seget.py <URL> [选项]

选项:
  -o, --output <文件名>       指定保存文件名（默认从服务器响应解析）
  -d, --dir <目录>            保存目录（默认当前目录）
  -t, --threads <数量>        下载线程数（默认 16）
  -r, --retries <次数>        失败重试次数（默认 3）
  --timeout <秒>              请求超时（默认 30 秒）
  --speed-limit <KB/s>        限速，0=不限（默认 0）
  --proxy <地址>              代理，如 http://127.0.0.1:7890
  --cookie <字符串>           Cookie，格式 key=val;key2=val2
  --referer <URL>             Referer 请求头
  --ua <字符串>               User-Agent（默认 Chrome）
  --no-ssl-verify             不验证 SSL 证书
  -q, --quiet                 静默模式，不显示进度
  -h, --help                  显示此帮助

示例:
  python seget.py https://example.com/file.zip
  python seget.py https://example.com/file.zip -d ~/Downloads -t 32
  python seget.py https://example.com/file.zip --proxy http://127.0.0.1:7890
  python seget.py https://example.com/video.mp4 --speed-limit 1024
"""

import sys, os, uuid, time, argparse, threading, signal, shutil

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core.downloader import DownloadTask, DownloadStatus, SegmentedDownloader


def fmt_size(n):
    if n <= 0: return "0 B"
    for u in ["B","KB","MB","GB","TB"]:
        if n < 1024: return f"{n:.1f} {u}"
        n /= 1024
    return f"{n:.1f} PB"

def fmt_speed(bps): return fmt_size(int(bps)) + "/s"

def fmt_eta(s):
    if s <= 0: return "--"
    s = int(s)
    if s < 60:   return f"{s}s"
    if s < 3600: return f"{s//60}m{s%60:02d}s"
    return f"{s//3600}h{(s%3600)//60}m"


def _enable_win_ansi():
    """Enable ANSI escape processing on Windows."""
    if sys.platform != "win32": return
    try:
        import ctypes
        h = ctypes.windll.kernel32.GetStdHandle(-11)
        m = ctypes.c_ulong()
        ctypes.windll.kernel32.GetConsoleMode(h, ctypes.byref(m))
        ctypes.windll.kernel32.SetConsoleMode(h, m.value | 4)
    except Exception:
        pass

_enable_win_ansi()


def render_progress(task: DownloadTask) -> str:
    """
    Build a single progress line that fits within terminal width.
    Always ends without newline; caller writes with \\r prefix.
    """
    cols = shutil.get_terminal_size((80, 24)).columns

    pct  = task.progress
    size = (f"{fmt_size(task.downloaded)}/{fmt_size(task.file_size)}"
            if task.file_size > 0 else fmt_size(task.downloaded))
    spd  = fmt_speed(task.speed)
    eta  = fmt_eta(task.eta)

    # Segment mini-indicators, as many as fit
    seg_parts = []
    if task.segments:
        for s in task.segments:
            seg_parts.append(f"{s.index+1}:{s.progress_pct:.0f}%")

    # Core info (always shown)
    core = f" {pct:5.1f}% {size} {spd} ETA:{eta}"

    # Bar fills remaining space
    bar_width = max(4, cols - len(core) - 2)
    filled    = max(0, min(int(bar_width * pct / 100), bar_width))
    bar       = "█" * filled + "░" * (bar_width - filled)

    line = f"[{bar}]{core}"

    # Append segment indicators only if they fit
    if seg_parts:
        segs_str = " [" + " ".join(seg_parts) + "]"
        if len(line) + len(segs_str) <= cols - 1:
            line += segs_str
        else:
            # Fit as many as possible
            available = cols - 1 - len(line) - 2  # " [" and "]"
            fitted = []
            used = 0
            for p in seg_parts:
                need = len(p) + (1 if fitted else 0)
                if used + need <= available:
                    fitted.append(p)
                    used += need
                else:
                    break
            if fitted:
                line += " [" + " ".join(fitted) + "]"

    # Truncate hard if still too long
    return line[:cols - 1]


def main():
    parser = argparse.ArgumentParser(prog="seget",
        description="SE Downloader CLI — 多线程分段下载",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("url")
    parser.add_argument("-o","--output",   default="")
    parser.add_argument("-d","--dir",      default=".")
    parser.add_argument("-t","--threads",  type=int, default=16)
    parser.add_argument("-r","--retries",  type=int, default=3)
    parser.add_argument("--timeout",       type=int, default=30)
    parser.add_argument("--speed-limit",   type=int, default=0, metavar="KB/s")
    parser.add_argument("--proxy",         default="")
    parser.add_argument("--cookie",        default="")
    parser.add_argument("--referer",       default="")
    parser.add_argument("--ua",            default="")
    parser.add_argument("--no-ssl-verify", action="store_true")
    parser.add_argument("-q","--quiet",    action="store_true", help="Quiet mode")
    parser.add_argument("--chs",           action="store_true", help="Use Chinese interface / 使用中文界面")
    args = parser.parse_args()

    # Language selection
    if args.chs:
        import sys as _sys
        _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from core.i18n import set_language
        set_language("zh_CN")

    cookies = {}
    for pair in args.cookie.split(";"):
        pair = pair.strip()
        if "=" in pair:
            k, v = pair.split("=", 1)
            cookies[k.strip()] = v.strip()

    headers = {}
    if args.ua:
        headers["User-Agent"] = args.ua

    save_dir = os.path.expanduser(args.dir)
    os.makedirs(save_dir, exist_ok=True)

    task = DownloadTask(
        task_id     = str(uuid.uuid4()),
        url         = args.url,
        save_path   = save_dir,
        filename    = args.output,
        threads     = args.threads,
        retries     = args.retries,
        timeout     = args.timeout,
        speed_limit = args.speed_limit * 1024,
        proxy       = args.proxy,
        cookies     = cookies,
        headers     = headers,
        referer     = args.referer,
        verify_ssl  = not args.no_ssl_verify,
    )

    done  = threading.Event()
    _lock = threading.Lock()
    _started = [False]   # first byte received

    def _write(line: str):
        cols = shutil.get_terminal_size((80, 24)).columns
        sys.stdout.write("\r" + line[:cols - 1] + " " * max(0, cols - 1 - len(line)))
        sys.stdout.flush()

    def on_progress(t):
        if args.quiet: return
        try:
            _started[0] = True
            with _lock:
                _write(render_progress(t))
        except Exception:
            pass

    # Track status text separately so progress thread can also update it
    _status_msg = [""]

    def _refresh_status():
        """Called periodically to animate the connecting dots."""
        pass  # handled in on_status

    def on_status(t):
        if not args.quiet:
            try:
                with _lock:
                    if t.status == DownloadStatus.DOWNLOADING and not _started[0]:
                        fname = t.filename if t.filename and t.filename not in ("", "download") else ""
                        if fname:
                            _write(f"⏳ 正在建立 {t.threads} 个连接... [{fname}]")
                        else:
                            _write("⏳ 探测服务器中...")
                    elif t.status == DownloadStatus.PAUSED:
                        _write("⏸ 已暂停")
            except Exception:
                pass
        if t.status in (DownloadStatus.COMPLETED,
                        DownloadStatus.FAILED,
                        DownloadStatus.CANCELLED):
            done.set()

    dl = SegmentedDownloader(task, on_progress=on_progress, on_status_change=on_status)

    if not args.quiet:
        if args.chs:
            print(f"URL    : {args.url}")
            print(f"保存到 : {save_dir}")
            sl = f"  限速: {args.speed_limit} KB/s" if args.speed_limit > 0 else ""
            print(f"线程数 : {args.threads}{sl}")
        else:
            print(f"URL     : {args.url}")
            print(f"Save to : {save_dir}")
            sl = f"  limit: {args.speed_limit} KB/s" if args.speed_limit > 0 else ""
            print(f"Threads : {args.threads}{sl}")

    def _sigint(sig, frame):
        sys.stdout.write("\n")
        print("⚠ 中断，正在取消...")
        dl.cancel()
        done.set()
    signal.signal(signal.SIGINT, _sigint)

    # Spinner thread: animates "connecting..." while waiting for first byte
    _spinner_stop = threading.Event()
    def _spinner():
        frames = ["⠋","⠙","⠹","⠸","⠼","⠴","⠦","⠧","⠇","⠏"]
        i = 0
        while not _spinner_stop.wait(0.12):
            if _started[0] or done.is_set():
                break
            try:
                with _lock:
                    fname = task.filename or ""
                    chs_s = getattr(args, "chs", False)
                    if fname and fname not in ("", "download"):
                        msg = (f"{frames[i % len(frames)]} 建立 {args.threads} 个连接中... [{fname}]" if chs_s
                               else f"{frames[i % len(frames)]} Connecting {args.threads} threads... [{fname}]")
                    elif task.file_size > 0:
                        msg = (f"{frames[i % len(frames)]} 建立 {args.threads} 个连接中... ({fmt_size(task.file_size)})" if chs_s
                               else f"{frames[i % len(frames)]} Connecting {args.threads} threads... ({fmt_size(task.file_size)})")
                    else:
                        msg = (f"{frames[i % len(frames)]} 连接服务器中..." if chs_s
                               else f"{frames[i % len(frames)]} Connecting to server...")
                    _write(msg)
                i += 1
            except Exception:
                pass
    if not args.quiet:
        _spin_t = threading.Thread(target=_spinner, daemon=True)
        _spin_t.start()

    dl.start()
    done.wait()
    _spinner_stop.set()

    # Clear progress line
    if not args.quiet:
        cols = shutil.get_terminal_size((80, 24)).columns
        sys.stdout.write("\r" + " " * (cols - 1) + "\r")
        sys.stdout.flush()

    t = task
    chs = getattr(args, "chs", False)
    if t.status == DownloadStatus.COMPLETED:
        elapsed   = t.finished_at - t.started_at if t.finished_at > 0 else 0
        avg_speed = t.file_size / elapsed if elapsed > 0 and t.file_size > 0 else 0
        if not args.quiet:
            if chs:
                print(f"✅ 完成: {t.filename}")
                print(f"   {fmt_size(t.file_size)}  {elapsed:.1f}s  均速 {fmt_speed(avg_speed)}")
            else:
                print(f"✅ Done: {t.filename}")
                print(f"   {fmt_size(t.file_size)}  {elapsed:.1f}s  avg {fmt_speed(avg_speed)}")
        sys.exit(0)
    elif t.status == DownloadStatus.CANCELLED:
        print("⚠ Cancelled" if not chs else "⚠ 已取消")
        sys.exit(130)
    else:
        print("❌ Download failed" if not chs else "❌ 下载失败")
        if t.error_msg:
            for line in t.error_msg.strip().split("\n")[-4:]:
                print(f"   {line}")
        sys.exit(1)


if __name__ == "__main__":
    main()
