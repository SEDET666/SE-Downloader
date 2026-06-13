import uuid, logging, threading, time, os
from core.bili_downloader import merge_bili
from typing import Dict, List, Optional, Callable
from collections import deque
from core.downloader import DownloadTask, DownloadStatus, SegmentedDownloader
from core.settings import AppSettings
from core import task_store

log = logging.getLogger(__name__)


class DownloadManager:
    def __init__(self, settings: AppSettings):
        self.settings = settings
        self._tasks:       Dict[str, DownloadTask]        = {}
        self._downloaders: Dict[str, SegmentedDownloader] = {}
        self._queue: deque = deque()
        self._lock  = threading.Lock()
        # bili: video_task_id → audio_task_id
        self._bili_pairs: Dict[str, str] = {}
        self.on_task_added:   Optional[Callable] = None
        self.on_task_updated: Optional[Callable] = None
        self.on_task_removed: Optional[Callable] = None
        self._scheduler = threading.Thread(target=self._sched_loop,
                                           daemon=True, name="dl-sched")
        self._scheduler.start()
        self._load_saved_tasks()

    def _load_saved_tasks(self):
        """Load persisted tasks silently. Call replay_to_ui() after UI callbacks are set."""
        for task in task_store.load_tasks():
            with self._lock:
                self._tasks[task.task_id] = task
                # PAUSED tasks go back in queue so they can be resumed
                # DOWNLOADING tasks were interrupted — treat as PAUSED
                if task.status in (DownloadStatus.PAUSED, DownloadStatus.DOWNLOADING):
                    task.status = DownloadStatus.PAUSED
                    self._queue.append(task.task_id)
            # Do NOT call on_task_added here — UI isn't connected yet

    def replay_to_ui(self):
        """
        Called by UI after it has set on_task_added.
        Fires on_task_added for every already-loaded task so the UI can render them.
        """
        with self._lock:
            tasks = list(self._tasks.values())
        for task in tasks:
            self._safe_cb(self.on_task_added, task)

    def save(self):
        task_store.save_tasks(list(self._tasks.values()))

    def add_task(self, url, save_path, filename="", threads=0, headers=None,
                 cookies=None, speed_limit=0, proxy="", referer="",
                 retries=-1, timeout=-1, verify_ssl=None) -> str:
        s = self.settings
        if not filename:
            filename = url.split("/")[-1].split("?")[0].strip() or ""
        merged_h: dict = {}
        if s.user_agent: merged_h["User-Agent"] = s.user_agent
        try: merged_h.update(s.extra_headers)
        except: pass
        if headers: merged_h.update(headers)
        merged_c: dict = {}
        for pair in (s.cookies_str or "").split(";"):
            pair = pair.strip()
            if "=" in pair:
                k, v = pair.split("=", 1); merged_c[k.strip()] = v.strip()
        if cookies: merged_c.update(cookies)
        task = DownloadTask(
            task_id=str(uuid.uuid4()), url=url, save_path=save_path,
            filename=filename,
            threads=threads if threads > 0 else s.default_threads,
            headers=merged_h, cookies=merged_c,
            speed_limit=speed_limit if speed_limit > 0 else (
                s.global_speed_limit if s.enable_speed_limit else 0),
            proxy=proxy or (s.proxy if s.use_proxy else ""),
            referer=referer,
            retries=retries if retries >= 0 else s.default_retries,
            timeout=timeout if timeout > 0 else s.default_timeout,
            verify_ssl=verify_ssl if verify_ssl is not None else s.verify_ssl,
        )
        with self._lock:
            self._tasks[task.task_id] = task
            self._queue.append(task.task_id)
        self._safe_cb(self.on_task_added, task)
        self.save()
        return task.task_id

    def add_bili_task(self, video_url: str, audio_url: str,
                       save_path: str, title: str, bvid: str,
                       cookies_str: str = "") -> str:
        """Add a Bilibili video+audio task pair. Returns video task_id."""
        from core.bili_downloader import make_bili_tasks
        import os
        os.makedirs(save_path, exist_ok=True)
        video_task, audio_task = make_bili_tasks(
            video_url, audio_url, save_path, title, bvid, self.settings,
            cookies_str=cookies_str,
        )
        with self._lock:
            self._tasks[video_task.task_id] = video_task
            self._tasks[audio_task.task_id] = audio_task
            self._queue.append(video_task.task_id)
            self._queue.append(audio_task.task_id)
            self._bili_pairs[video_task.task_id] = audio_task.task_id
        self._safe_cb(self.on_task_added, video_task)
        self._safe_cb(self.on_task_added, audio_task)
        self.save()
        return video_task.task_id

    def pause_task(self, task_id):
        with self._lock: dl = self._downloaders.get(task_id)
        if dl: dl.pause()

    def resume_task(self, task_id):
        with self._lock: task = self._tasks.get(task_id)
        if task and task.status == DownloadStatus.PAUSED:
            task.status = DownloadStatus.PENDING
            with self._lock:
                if task_id not in self._queue:
                    self._queue.append(task_id)
            self._safe_cb(self.on_task_updated, task)

    def cancel_task(self, task_id: str, delete_files: bool = False):
        """Cancel a task and optionally delete its partial file + resume file."""
        with self._lock:
            dl   = self._downloaders.get(task_id)
            task = self._tasks.get(task_id)

        if dl:
            dl.cancel()
        elif task and task.status in (DownloadStatus.PENDING, DownloadStatus.PAUSED):
            task.status = DownloadStatus.CANCELLED
            self._safe_cb(self.on_task_updated, task)

        if delete_files and task:
            self._delete_task_files(task)

    def _delete_task_files(self, task: DownloadTask):
        """Delete partial download file and .seresume file."""
        for path in (task.resume_path, task.full_path):
            if not path:
                continue
            for attempt in range(5):
                try:
                    if os.path.exists(path):
                        os.remove(path)
                    break
                except OSError:
                    time.sleep(0.15)

    def remove_task(self, task_id: str, delete_files: bool = False):
        """Remove task from list. If delete_files=True, also delete partial file."""
        # Cancel first (stops download threads)
        self.cancel_task(task_id, delete_files=False)
        time.sleep(0.08)

        with self._lock:
            task = self._tasks.pop(task_id, None)
            self._downloaders.pop(task_id, None)
            self._queue = deque(t for t in self._queue if t != task_id)

        if task and delete_files:
            self._delete_task_files(task)

        if task:
            self._safe_cb(self.on_task_removed, task)
        self.save()

    def get_task(self, task_id) -> Optional[DownloadTask]:
        return self._tasks.get(task_id)

    def get_all_tasks(self) -> List[DownloadTask]:
        with self._lock: return list(self._tasks.values())

    def pause_all(self):
        for tid in list(self._tasks.keys()): self.pause_task(tid)

    def resume_all(self):
        for tid in list(self._tasks.keys()):
            t = self._tasks.get(tid)
            if t and t.status == DownloadStatus.PAUSED:
                self.resume_task(tid)

    def clear_completed(self):
        tids = [tid for tid, t in list(self._tasks.items())
                if t.status in (DownloadStatus.COMPLETED, DownloadStatus.CANCELLED,
                                DownloadStatus.FAILED)]
        for tid in tids: self.remove_task(tid)

    # ── scheduler ─────────────────────────────────────────────────────────────

    def _sched_loop(self):
        while True:
            try: self._tick()
            except: log.exception("sched tick")
            time.sleep(0.3)

    def _tick(self):
        max_c = self.settings.max_concurrent_downloads
        with self._lock:
            active = sum(1 for t in self._tasks.values()
                         if t.status == DownloadStatus.DOWNLOADING)
            slots = max_c - active
            to_start = []
            new_queue = deque()
            while self._queue:
                tid  = self._queue.popleft()
                task = self._tasks.get(tid)
                if task is None: continue
                if task.status == DownloadStatus.PENDING and slots > 0:
                    task.status = DownloadStatus.DOWNLOADING
                    to_start.append(tid); slots -= 1
                elif task.status == DownloadStatus.PENDING:
                    new_queue.append(tid)
                # Any other status (COMPLETED, PAUSED, etc.) — drop from queue
            self._queue = new_queue
        for tid in to_start: self._start_task(tid)

    def _start_task(self, task_id):
        task = self._tasks.get(task_id)
        if not task: return
        dl = SegmentedDownloader(task, on_progress=self._on_progress,
                                 on_status_change=self._on_status_change)
        with self._lock: self._downloaders[task_id] = dl
        dl.start()

    def _on_progress(self, task):
        self._safe_cb(self.on_task_updated, task)

    def _on_status_change(self, task):
        if task.status in (DownloadStatus.COMPLETED, DownloadStatus.FAILED,
                           DownloadStatus.CANCELLED):
            with self._lock: self._downloaders.pop(task.task_id, None)
        self._safe_cb(self.on_task_updated, task)
        self.save()

        # Bili: check if both video and audio are done → merge
        if task.status == DownloadStatus.COMPLETED and task.is_bili:
            self._check_bili_merge(task)
        # Bili: check if this is an audio task whose video is done
        if task.status == DownloadStatus.COMPLETED:
            self._check_bili_merge_as_audio(task)

    def _check_bili_merge(self, video_task):
        """Called when video task completes — check if audio is also done."""
        audio_id = self._bili_pairs.get(video_task.task_id)
        if not audio_id:
            return
        audio_task = self._tasks.get(audio_id)
        if audio_task and audio_task.status == DownloadStatus.COMPLETED:
            log.info("Both bili streams done, merging: %s", video_task.filename)
            merge_bili(video_task, on_status_change=self._safe_status_notify)

    def _check_bili_merge_as_audio(self, audio_task):
        """Called when any task completes — check if it's an audio whose video is done."""
        for vid_id, aud_id in list(self._bili_pairs.items()):
            if aud_id == audio_task.task_id:
                video_task = self._tasks.get(vid_id)
                if video_task and video_task.status == DownloadStatus.COMPLETED:
                    log.info("Both bili streams done (audio finished last), merging")
                    merge_bili(video_task, on_status_change=self._safe_status_notify)
                break

    def _safe_status_notify(self, task):
        self._safe_cb(self.on_task_updated, task)
        self.save()

    @staticmethod
    def _safe_cb(cb, *args):
        if cb is None: return
        try: cb(*args)
        except: log.exception("manager cb")
