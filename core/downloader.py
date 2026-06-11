"""
Segmented downloader — correctness-first.

seresume lifecycle (STRICT):
  Created  : _segmented() start, only if NOT all segments already done
  Updated  : every 3s in monitor loop, guarded by _completed
  Deleted  : _clear_resume() called once at the very end of _run()
              _clear_resume() sets _completed=True FIRST (atomic under GIL)
              so NO subsequent _save_resume() can ever fire

pause() guard:
  - Only operates if task is DOWNLOADING
  - Does NOT touch status if _completed is True
  - Does NOT call _save_resume if _completed is True

_single() resume_from fix:
  - Updated from file size after each failed attempt (not fixed at start)
"""

import os, re, json, time, shutil, logging, threading, traceback, urllib.parse
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Callable, Dict

import requests
from requests.adapters import HTTPAdapter

log = logging.getLogger(__name__)


# ── filename helpers ──────────────────────────────────────────────────────────

def _cd_filename(h: str) -> str:
    if not h: return ""
    m = re.search(r"filename\*\s*=\s*([^'\s;]+)''([^\s;]+)", h, re.I)
    if m:
        try: return urllib.parse.unquote(m.group(2), encoding=m.group(1))
        except: pass
    m = re.search(r'filename\s*=\s*"([^"]+)"', h, re.I)
    if m: return m.group(1).strip()
    m = re.search(r"filename\s*=\s*([^\s;\"']+)", h, re.I)
    if m: return m.group(1).strip().strip("'\"")
    return ""

def _url_filename(url: str) -> str:
    try:
        p = urllib.parse.urlparse(url)
        qs = urllib.parse.parse_qs(p.query)
        for k in ("filename","fn","name","file"):
            v = qs.get(k) or qs.get(k.upper())
            if v:
                s = urllib.parse.unquote_plus(v[0]).strip()
                if s: return s
        return urllib.parse.unquote(p.path.rstrip("/").split("/")[-1]).strip()
    except: return ""

def _safe(name: str) -> str:
    name = re.sub(r'[\\/:*?"<>|]', "_", name).strip(". ")
    return (name[:200] if name else "") or "download"

def _unique(folder: str, name: str) -> str:
    if not os.path.exists(os.path.join(folder, name)): return name
    base, ext = os.path.splitext(name)
    for i in range(1, 10000):
        c = f"{base} ({i}){ext}"
        if not os.path.exists(os.path.join(folder, c)): return c
    return name


# ── data model ────────────────────────────────────────────────────────────────

class DownloadStatus(Enum):
    PENDING     = "pending"
    DOWNLOADING = "downloading"
    PAUSED      = "paused"
    COMPLETED   = "completed"
    FAILED      = "failed"
    CANCELLED   = "cancelled"


@dataclass
class SegmentInfo:
    index:   int
    start:   int
    end:     int
    written: int = 0
    status:  str = "pending"

    @property
    def resume_offset(self) -> int: return self.start + self.written
    @property
    def is_done(self) -> bool: return self.written >= (self.end - self.start + 1)
    @property
    def progress_pct(self) -> float:
        total = self.end - self.start + 1
        return min(self.written / total * 100.0, 100.0) if total > 0 else 0.0


@dataclass
class DownloadTask:
    task_id:     str
    url:         str
    save_path:   str
    filename:    str
    threads:     int   = 16
    status:      DownloadStatus = DownloadStatus.PENDING
    file_size:   int   = 0
    downloaded:  int   = 0
    speed:       float = 0.0
    eta:         float = 0.0
    progress:    float = 0.0
    error_msg:   str   = ""
    final_url:   str   = ""
    single_thread_reason: str = ""
    segments:    list  = field(default_factory=list)
    created_at:  float = field(default_factory=time.time)
    started_at:  float = 0.0
    finished_at: float = 0.0
    headers:     Dict[str,str] = field(default_factory=dict)
    cookies:     Dict[str,str] = field(default_factory=dict)
    speed_limit: int   = 0
    proxy:       str   = ""
    retries:     int   = 3
    timeout:     int   = 30
    verify_ssl:  bool  = True
    referer:     str   = ""

    @property
    def full_path(self) -> str: return os.path.join(self.save_path, self.filename)
    @property
    def resume_path(self) -> str: return self.full_path + ".seresume"
    @property
    def display_url(self) -> str: return self.final_url or self.url


# ── downloader ────────────────────────────────────────────────────────────────

class SegmentedDownloader:

    def __init__(self, task: DownloadTask,
                 on_progress: Optional[Callable] = None,
                 on_status_change: Optional[Callable] = None):
        self.task             = task
        self.on_progress      = on_progress
        self.on_status_change = on_status_change
        self._stop  = threading.Event()
        self._pause = threading.Event()
        self._lock  = threading.Lock()
        self._speed_win: deque = deque()
        self._last_tick: float = 0.0
        # _completed: set to True BEFORE deleting seresume.
        # Blocks ALL future _save_resume() calls regardless of caller.
        self._completed = False

    # ── public API ────────────────────────────────────────────────────────────

    def start(self):
        threading.Thread(target=self._safe_run, daemon=True,
                         name=f"dl-{self.task.task_id[:8]}").start()

    def pause(self):
        if self.task.status in (DownloadStatus.COMPLETED,
                                DownloadStatus.CANCELLED,
                                DownloadStatus.FAILED):
            return
        if self.task.status != DownloadStatus.DOWNLOADING:
            return
        self._pause.set()
        time.sleep(0.35)
        # Re-check after sleep: download may have completed during the wait
        if self.task.status in (DownloadStatus.COMPLETED,
                                DownloadStatus.CANCELLED,
                                DownloadStatus.FAILED):
            self._pause.clear()
            return
        self._save_resume()
        self.task.status = DownloadStatus.PAUSED
        self._emit_status()

    def resume(self):
        if self.task.status == DownloadStatus.COMPLETED:
            return
        self._pause.clear()
        self.task.status = DownloadStatus.DOWNLOADING
        with self._lock: self._speed_win.clear()
        self._last_tick = 0.0
        self._emit_status()

    def cancel(self):
        self._stop.set()
        self._pause.clear()
        self.task.status = DownloadStatus.CANCELLED
        self._emit_status()

    # ── internal callbacks ────────────────────────────────────────────────────

    def _emit_status(self):
        try:
            if self.on_status_change: self.on_status_change(self.task)
        except: log.exception("on_status_change")

    def _emit_progress(self):
        try:
            if self.on_progress: self.on_progress(self.task)
        except: log.exception("on_progress")

    # ── session factory ───────────────────────────────────────────────────────

    def _make_session(self) -> requests.Session:
        s = requests.Session()
        a = HTTPAdapter(pool_connections=max(4, self.task.threads),
                        pool_maxsize=max(4, self.task.threads) + 4)
        s.mount("http://", a); s.mount("https://", a)
        h = dict(self.task.headers)
        if "User-Agent" not in h:
            h["User-Agent"] = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                               "AppleWebKit/537.36 (KHTML, like Gecko) "
                               "Chrome/125.0.0.0 Safari/537.36")
        if self.task.referer: h["Referer"] = self.task.referer
        s.headers.update(h)
        if self.task.cookies: s.cookies.update(self.task.cookies)
        if self.task.proxy: s.proxies = {"http": self.task.proxy, "https": self.task.proxy}
        s.verify = self.task.verify_ssl
        return s

    # ── resume file ───────────────────────────────────────────────────────────

    def _save_resume(self):
        if self.task.status in (DownloadStatus.COMPLETED,
                                DownloadStatus.CANCELLED):
            return
        try:
            d = {
                "url": self.task.url, "final_url": self.task.final_url,
                "filename": self.task.filename, "file_size": self.task.file_size,
                "downloaded": self.task.downloaded,
                "segments": [{"index": s.index, "start": s.start, "end": s.end,
                               "written": s.written, "status": s.status}
                              for s in self.task.segments],
            }
            with open(self.task.resume_path, "w", encoding="utf-8") as f:
                json.dump(d, f)
        except: log.exception("_save_resume")

    def _load_resume(self) -> bool:
        try:
            if not (os.path.exists(self.task.resume_path) and
                    os.path.exists(self.task.full_path)):
                return False
            with open(self.task.resume_path, encoding="utf-8") as f:
                d = json.load(f)
            if d.get("url") != self.task.url: return False
            if d.get("file_size", 0) != self.task.file_size: return False
            segs, total = [], 0
            for sd in d["segments"]:
                seg = SegmentInfo(sd["index"], sd["start"], sd["end"],
                                  sd["written"], sd["status"])
                segs.append(seg); total += sd["written"]
            self.task.segments   = segs
            self.task.downloaded = total
            self.task.filename   = d.get("filename", self.task.filename)
            self.task.final_url  = d.get("final_url", self.task.final_url)
            with self._lock: self._speed_win.clear()
            return True
        except: log.exception("_load_resume"); return False

    def _clear_resume(self):
        """
        Mark completed (blocks _save_resume forever) then delete the file.
        This is the ONLY place _completed is set to True.
        Must be called exactly once, at the end of a successful _run().
        """
        self._completed = True      # FIRST — GIL makes this atomic
        path = self.task.resume_path
        for _ in range(10):
            try:
                if os.path.exists(path):
                    os.remove(path)
                return
            except OSError:
                time.sleep(0.2)
        log.warning("Could not delete resume file: %s", path)

    # ── entry point ───────────────────────────────────────────────────────────

    def _safe_run(self):
        try:
            self._run()
        except Exception:
            tb = traceback.format_exc(limit=6)
            log.error("FAILED %s\n%s", self.task.url, tb)
            if not self._stop.is_set():
                self.task.status    = DownloadStatus.FAILED
                self.task.error_msg = tb
                self._emit_status()

    def _run(self):
        self.task.status     = DownloadStatus.DOWNLOADING
        self.task.started_at = time.time()
        self._emit_status()

        # Remember if user explicitly set a filename — don't overwrite it
        self._user_specified_filename = bool(
            self.task.filename and self.task.filename not in ("", "download")
        )

        # Probe session — closed in finally
        probe_sess = self._make_session()
        try:
            self._probe(probe_sess)
        finally:
            probe_sess.close()

        os.makedirs(self.task.save_path, exist_ok=True)

        # Collision avoidance only if file doesn't already exist
        if not os.path.exists(self.task.full_path):
            self.task.filename = _unique(self.task.save_path, self.task.filename)

        # Disk space check
        if self.task.file_size > 0:
            try:
                free = shutil.disk_usage(self.task.save_path).free
                if free < self.task.file_size:
                    raise OSError(
                        f"磁盘空间不足：需要 {self.task.file_size/1048576:.1f} MB，"
                        f"剩余 {free/1048576:.1f} MB")
            except OSError: raise
            except: pass

        self._emit_status()

        # Download session — closed in finally
        dl_sess = self._make_session()
        try:
            if (self.task.file_size > 0 and
                    self.task.threads > 1 and
                    self._accept_range):
                self.task.single_thread_reason = ""
                self._segmented(dl_sess)
            else:
                if self.task.threads > 1:
                    self.task.single_thread_reason = (
                        "single_thread_no_range"
                        if not self._accept_range else
                        "single_thread_no_size")
                self._emit_status()
                self._single(dl_sess)
        finally:
            dl_sess.close()

        if self._stop.is_set():
            return

        # Integrity check
        if self.task.file_size > 0:
            actual = os.path.getsize(self.task.full_path)
            if actual != self.task.file_size:
                raise RuntimeError(
                    f"文件大小不一致：期望 {self.task.file_size} B，实际 {actual} B")

        # Complete: _clear_resume sets _completed=True FIRST, then deletes file.
        # After this point, pause() / _save_resume() are all no-ops.
        self._clear_resume()
        self.task.status      = DownloadStatus.COMPLETED
        self.task.finished_at = time.time()
        self.task.progress    = 100.0
        self.task.speed       = 0.0
        self.task.eta         = 0.0
        self._emit_status()
        self._emit_progress()

    # ── probe ─────────────────────────────────────────────────────────────────

    def _probe(self, sess: requests.Session):
        """
        Fast probe: try HEAD first (low overhead), fall back to Range:bytes=0-0.
        Both have a short timeout (5s) so the user never waits long before
        bytes start flowing. On total failure we just start downloading and
        collect info from the real GET response headers.
        """
        self._accept_range = False
        PROBE_TO = (min(3, self.task.timeout), min(5, self.task.timeout))  # (connect, read)
        filename  = self.task.filename or ""
        final_url = self.task.url
        file_size = 0

        def _parse_resp(r):
            nonlocal final_url, file_size, filename
            final_url = r.url or self.task.url

            # Range support from HEAD/206
            if r.status_code == 206:
                self._accept_range = True
            elif r.headers.get("Accept-Ranges", "").lower() == "bytes":
                self._accept_range = True

            # File size
            cr = r.headers.get("Content-Range", "")
            if cr:
                m = re.search(r"/(\d+)$", cr.strip())
                if m: file_size = int(m.group(1))
            if file_size == 0:
                cl = r.headers.get("Content-Length", "")
                if cl.isdigit(): file_size = int(cl)

            # Filename from Content-Disposition
            cd = r.headers.get("Content-Disposition", "")
            if cd:
                name = _cd_filename(cd)
                if name: filename = name

        # ── Strategy 1: HEAD (fastest, no body) ──────────────────────────────
        try:
            r = sess.head(self.task.url, timeout=PROBE_TO,
                          allow_redirects=True)
            if r.status_code < 400:
                _parse_resp(r)
                r.close()
                log.debug("Probe via HEAD OK, range=%s size=%d",
                          self._accept_range, file_size)
                # HEAD succeeded — if we got range support and size, done.
                # If not, try Range:bytes=0-0 to confirm range support.
                if not self._accept_range and file_size > 0:
                    # Server might still support ranges even without saying so in HEAD
                    pass  # fall through to Range probe
                elif file_size > 0:
                    # Have everything we need
                    self.task.final_url = final_url
                    self.task.file_size = file_size
                    self.task.filename  = _safe(filename or
                        _url_filename(final_url) or
                        _url_filename(self.task.url) or "download")
                    return
        except Exception as e:
            log.debug("HEAD failed (%s), trying Range probe", e)

        # ── Strategy 2: GET Range:bytes=0-0 ──────────────────────────────────
        try:
            r = sess.get(self.task.url, headers={"Range": "bytes=0-0"},
                         stream=True, timeout=PROBE_TO, allow_redirects=True)
            r.raise_for_status()
            _parse_resp(r)
            try: r.content    # drain 1-byte body
            except: pass
            r.close()
            log.debug("Probe via Range OK, range=%s size=%d",
                      self._accept_range, file_size)
        except Exception as e:
            log.warning("Range probe failed (%s) — info from GET response", e)
            # Will get info from the real download response

        # Only auto-detect filename if user didn't specify one
        user_specified = bool(self.task.filename and
                              self.task.filename not in ("", "download"))
        if not user_specified:
            if not filename or filename in ("", "download"):
                filename = (_url_filename(final_url) or
                            _url_filename(self.task.url) or "download")
            self.task.filename = _safe(filename)
        # Always update these
        self.task.final_url = final_url
        self.task.file_size = file_size

    # ── segmented download ────────────────────────────────────────────────────

    def _segmented(self, sess: requests.Session):
        size   = self.task.file_size
        target = self.task.final_url or self.task.url

        resumed = self._load_resume()
        if not resumed:
            n = self.task.threads
            chunk = size // n
            self.task.segments = [
                SegmentInfo(i, i * chunk,
                            (i * chunk + chunk - 1) if i < n - 1 else size - 1)
                for i in range(n)
            ]
            self.task.downloaded = 0
            with self._lock: self._speed_win.clear()

            try:
                with open(self.task.full_path, "wb") as fh:
                    fh.seek(size - 1); fh.write(b"\x00")
            except OSError as e:
                raise OSError(f"无法创建文件：{e}") from e
        else:
            # Resumed: if all segments already done, skip re-downloading
            if all(s.is_done for s in self.task.segments):
                log.info("All segments complete — skipping download")
                return  # _run() will integrity-check and _clear_resume()

        # Write initial resume file ONLY for a real (partial) download
        self._save_resume()
        self._emit_progress()

        errors: dict = {}
        err_lock = threading.Lock()

        def worker(seg: SegmentInfo):
            try: self._seg_dl(target, seg)
            except Exception as exc:
                with err_lock: errors[seg.index] = exc

        pending = [s for s in self.task.segments if not s.is_done]
        threads = [threading.Thread(target=worker, args=(s,), daemon=True)
                   for s in pending]
        for t in threads: t.start()

        last_save = time.monotonic()
        while any(t.is_alive() for t in threads):
            if self._stop.is_set(): break
            if not self._pause.is_set(): self._tick_speed()
            now = time.monotonic()
            if now - last_save > 3.0:
                self._save_resume()   # guarded by _completed inside
                last_save = now
            time.sleep(0.3)

        for t in threads: t.join(timeout=60)

        if self._stop.is_set():
            self._save_resume()
            return
        if errors:
            self._save_resume()
            raise RuntimeError(f"{len(errors)} 段失败：" +
                               "; ".join(str(v) for v in list(errors.values())[:2]))
        # SUCCESS: return without _save_resume — _run() calls _clear_resume()

    # ── segment worker ────────────────────────────────────────────────────────

    def _seg_dl(self, url: str, seg: SegmentInfo):
        if seg.is_done: return
        seg.status = "downloading"
        attempt = 0

        while True:
            if self._stop.is_set(): return
            while self._pause.is_set():
                if self._stop.is_set(): return
                time.sleep(0.05)

            byte_start = seg.resume_offset
            byte_end   = seg.end
            if byte_start > byte_end:
                seg.status = "done"; return

            seg_sess = self._make_session()
            resp = None; fh = None; paused_mid = False

            try:
                resp = seg_sess.get(url,
                    headers={"Range": f"bytes={byte_start}-{byte_end}"},
                    stream=True, timeout=self.task.timeout)

                if resp.status_code not in (206, 200):
                    raise IOError(f"HTTP {resp.status_code}")
                if resp.status_code == 200 and byte_start > 0:
                    raise IOError("Server ignores Range header")

                fh = open(self.task.full_path, "r+b")
                fh.seek(byte_start)

                for chunk in resp.iter_content(chunk_size=131072):
                    if self._stop.is_set(): break
                    if self._pause.is_set(): paused_mid = True; break
                    if not chunk: continue

                    capacity = seg.end - fh.tell() + 1
                    if capacity <= 0: break
                    if len(chunk) > capacity: chunk = chunk[:capacity]

                    fh.write(chunk)
                    n = len(chunk); seg.written += n
                    with self._lock:
                        self.task.downloaded += n
                        self._speed_win.append((time.monotonic(), n))
                    if self.task.speed_limit > 0: self._throttle(n)

            except Exception as e:
                log.warning("Seg %d attempt %d: %s", seg.index, attempt + 1, e)
                attempt += 1
                if attempt > self.task.retries:
                    seg.status = "failed"; raise
                paused_mid = False
            finally:
                if fh is not None:
                    try: fh.close()
                    except: pass
                if resp is not None:
                    try: resp.close()
                    except: pass
                try: seg_sess.close()
                except: pass

            if self._stop.is_set(): return

            if paused_mid:
                while self._pause.is_set():
                    if self._stop.is_set(): return
                    time.sleep(0.05)
                continue  # reconnect, attempt unchanged

            if seg.is_done:
                seg.status = "done"; return

            if attempt > self.task.retries:
                seg.status = "failed"
                raise RuntimeError(f"Seg {seg.index} exhausted retries")
            time.sleep(min(2 ** (attempt - 1), 16))

    # ── single-thread download ────────────────────────────────────────────────

    def _single(self, sess: requests.Session):
        target = self.task.final_url or self.task.url

        # Initial resume offset from existing file
        def _get_resume_from() -> int:
            if os.path.exists(self.task.full_path) and self.task.file_size > 0:
                ex = os.path.getsize(self.task.full_path)
                if 0 < ex < self.task.file_size:
                    return ex
            return 0

        resume_from = _get_resume_from()
        if resume_from > 0:
            with self._lock:
                self.task.downloaded = resume_from
                self._speed_win.clear()

        attempt = 0
        while attempt <= self.task.retries:
            if self._stop.is_set(): return
            counted = 0; resp = None; fh = None

            try:
                hdrs = {}
                if resume_from > 0:
                    hdrs["Range"] = f"bytes={resume_from}-"

                resp = sess.get(target, headers=hdrs, stream=True,
                                timeout=self.task.timeout)
                resp.raise_for_status()

                if resp.url and resp.url != self.task.final_url:
                    self.task.final_url = resp.url
                cd = resp.headers.get("Content-Disposition", "")
                if cd and not getattr(self, "_user_specified_filename", False):
                    name = _safe(_cd_filename(cd))
                    if name and name != self.task.filename:
                        self.task.filename = _unique(self.task.save_path, name)
                        self._emit_status()
                if self.task.file_size == 0:
                    cl = resp.headers.get("Content-Length", "")
                    if cl.isdigit(): self.task.file_size = int(cl)

                mode = "ab" if resume_from > 0 and resp.status_code == 206 else "wb"
                if mode == "wb" and resume_from > 0:
                    # Server didn't honour Range — restart from scratch
                    with self._lock:
                        self.task.downloaded = 0
                        self._speed_win.clear()
                    resume_from = 0

                fh = open(self.task.full_path, mode)
                for chunk in resp.iter_content(chunk_size=131072):
                    if self._stop.is_set(): break
                    while self._pause.is_set():
                        if self._stop.is_set(): break
                        time.sleep(0.05)
                    if self._stop.is_set(): break
                    if not chunk: continue
                    fh.write(chunk)
                    n = len(chunk); counted += n
                    with self._lock:
                        self.task.downloaded += n
                        self._speed_win.append((time.monotonic(), n))
                    self._tick_speed()
                    if self.task.speed_limit > 0: self._throttle(n)

                return  # success

            except OSError as e:
                raise OSError(f"写入失败：{e}") from e
            except Exception as e:
                log.warning("Single attempt %d: %s", attempt + 1, e)
                with self._lock:
                    self.task.downloaded -= counted
                    self._speed_win.clear()
                counted = 0
                attempt += 1
                if attempt > self.task.retries: raise
                # Re-read resume_from: file may have grown before the error
                new_rf = _get_resume_from()
                if new_rf != resume_from:
                    resume_from = new_rf
                    with self._lock:
                        self.task.downloaded = resume_from
                time.sleep(min(2 ** (attempt - 1), 16))
            finally:
                if fh is not None:
                    try: fh.close()
                    except: pass
                if resp is not None:
                    try: resp.close()
                    except: pass

    # ── speed (4-second sliding window) ──────────────────────────────────────

    def _tick_speed(self):
        now = time.monotonic()
        if now - self._last_tick < 0.4: return
        self._last_tick = now
        with self._lock:
            cutoff = now - 4.0
            while self._speed_win and self._speed_win[0][0] < cutoff:
                self._speed_win.popleft()
            downloaded = self.task.downloaded
            win = list(self._speed_win)
        if len(win) >= 2:
            span = win[-1][0] - win[0][0]
            speed = sum(b for _, b in win) / span if span > 0.001 else 0.0
        elif len(win) == 1:
            speed = self.task.speed   # keep last known
        else:
            speed = 0.0
        self.task.speed = speed
        if self.task.file_size > 0:
            self.task.progress = min(downloaded / self.task.file_size * 100.0, 99.9)
            self.task.eta = ((self.task.file_size - downloaded) / speed
                             if speed > 0 else 0.0)
        else:
            self.task.progress = 0.0
            self.task.eta      = 0.0
        self._emit_progress()

    # ── token-bucket throttle (global across all segment threads) ────────────
    #
    # All threads share _thr_lock and _thr_tokens.
    # Tokens accumulate at `speed_limit` bytes/sec.
    # Each thread consumes tokens before writing; if not enough tokens,
    # it sleeps until enough accumulate. This enforces the TOTAL rate.

    _thr_lock:   object = None   # threading.Lock, created lazily
    _thr_tokens: float  = 0.0
    _thr_last:   float  = 0.0

    def _throttle(self, n: int):
        lim = self.task.speed_limit
        if lim <= 0:
            return
        # Lazy init of lock (dataclass __init__ doesn't run for class-level attrs)
        if self._thr_lock is None:
            import threading as _th
            object.__setattr__(self, "_thr_lock",   _th.Lock())
            object.__setattr__(self, "_thr_tokens", float(lim))  # start full
            object.__setattr__(self, "_thr_last",   time.monotonic())

        while True:
            with self._thr_lock:
                now = time.monotonic()
                # Refill tokens based on elapsed time
                elapsed = now - self._thr_last
                self._thr_last = now
                self._thr_tokens = min(
                    lim,                                  # cap at 1 second of tokens
                    self._thr_tokens + elapsed * lim      # add new tokens
                )
                if self._thr_tokens >= n:
                    self._thr_tokens -= n
                    return                                 # got tokens, proceed
                # Not enough tokens — calculate sleep outside lock
                deficit = n - self._thr_tokens

            # Sleep proportional to deficit, then retry
            time.sleep(deficit / lim)
