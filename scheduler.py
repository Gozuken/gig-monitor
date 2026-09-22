"""Arka planda belirlenen intervallerde cekim + temizleme dongusu."""

import logging
import threading
import time
import traceback
from typing import Callable

log = logging.getLogger(__name__)


class Scheduler:
    def __init__(self, job: Callable[[], None]):
        self.job = job
        self.interval_sec = 0.0
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.last_duration = 0.0

    @property
    def running(self) -> bool:
        return self.thread is not None and self.thread.is_alive()

    def start(self, interval_sec: float) -> bool:
        if self.running:
            return False
        self.interval_sec = max(0.0, interval_sec)
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._loop, name="scheduler", daemon=True)
        self.thread.start()
        return True

    def stop(self) -> bool:
        if not self.running:
            return True
        self.stop_event.set()
        self.thread.join(timeout=15)
        self.thread = None
        return True

    def _loop(self):
        log.info("scheduler basladi (interval=%ss)", self.interval_sec)
        while not self.stop_event.is_set():
            started = time.time()
            try:
                self.job()
            except Exception:
                log.error("dondurme hatasi:\n%s", traceback.format_exc())
            self.last_duration = time.time() - started
            if self.interval_sec <= 0:
                break
            self.stop_event.wait(self.interval_sec)
        self.thread = None
        log.info("scheduler durdu")


def scrape_and_clean(conn) -> int:
    """Bir tam cekim + temizleme kosusu. Yeni kept ilan sayisini dondurur."""
    import cleaner
    import scraper
    import storage

    settings = storage.get_settings(conn)
    subreddits = storage.parse_list(settings["subreddits"])
    limit = storage.get_setting_int(conn, "fetch_limit")

    if not subreddits:
        log.info("subreddit listesi bos, cekim atlandi")
        return 0

    fetched = scraper.sync(conn, subreddits, limit)
    counts = cleaner.run_pipeline(
        conn,
        max_age_days=storage.get_setting_int(conn, "max_age_days"),
        keywords=storage.parse_list(settings["keywords"]),
    )
    log.info(
        "kosu tamam: %d cekildi, %d kept, %d filtered",
        fetched, counts["kept"], counts["filtered"],
    )
    return counts["kept"]


def make_job() -> Callable[[], None]:
    import storage

    def job():
        conn = storage.connect()
        try:
            scrape_and_clean(conn)
        finally:
            conn.close()

    return job


def run_foreground(interval_sec: float):
    """interval=0 ise tek kosu; degilse arka planda calismaya devam et."""
    log.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    sched = Scheduler(make_job())
    if interval_sec > 0:
        sched.start(interval_sec)
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            sched.stop()
    else:
        sched.job()