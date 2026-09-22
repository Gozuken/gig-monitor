import calendar
import html
import logging
import re
import socket
import time
from html.parser import HTMLParser

import feedparser

import config

socket.setdefaulttimeout(25)

log = logging.getLogger(__name__)

TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")
_RETRY_STATUS = (429, 500, 502, 503, 504)
_MAX_ATTEMPTS = 4


def _fetch(url: str, timeout: int = 20):
    last_err: Exception | None = None
    for attempt in range(_MAX_ATTEMPTS):
        feed = feedparser.parse(url, request_headers={"User-Agent": config.RSS_USER_AGENT})
        if feed.entries:
            return feed
        status = getattr(feed, "status", None)
        if status in _RETRY_STATUS and attempt < _MAX_ATTEMPTS - 1:
            delay = 2 ** attempt
            log.warning("RSS %s: status=%s, %ss sonra tekrar deniyor", url, status, delay)
            time.sleep(delay)
            continue
        msg = getattr(feed, "bozo_exception", None) or "bos feed"
        last_err = RuntimeError(f"status={status} {msg}")
        break
    raise last_err or RuntimeError("feed okunamadi")


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data):
        self.parts.append(data)


def strip_html(raw: str) -> str:
    if not raw:
        return ""
    parser = _TextExtractor()
    parser.feed(raw)
    text = " ".join(parser.parts)
    text = html.unescape(text)
    text = TAG_RE.sub(" ", text)
    text = SPACE_RE.sub(" ", text)
    return text.strip()


def _post_id(entry_id: str) -> str:
    value = (entry_id or "").strip()
    m = re.search(r"t3_([A-Za-z0-9]+)", value)
    if m:
        return m.group(1)
    m = re.search(r"/comments/([A-Za-z0-9]+)/", value)
    if m:
        return m.group(1)
    return value


def _created_utc(entry) -> float:
    for key in ("published_parsed", "updated_parsed"):
        parsed = getattr(entry, key, None)
        if parsed:
            return float(calendar.timegm(parsed))
    return 0.0


def parse_subreddit(subreddit: str, limit: int) -> list[dict]:
    """RSS feed'ini okur, normalize edilmis post dict'leri dondurur."""
    limit = max(1, min(limit, config.RSS_LIMIT_MAX))
    url = f"https://www.reddit.com/r/{subreddit}/new/.rss?limit={limit}"
    feed = _fetch(url)

    posts: list[dict] = []
    for entry in feed.entries:
        content = ""
        if getattr(entry, "content", None):
            content = entry.content[0].get("value", "")
        elif getattr(entry, "summary", None):
            content = entry.summary

        title = html.unescape(entry.get("title", ""))
        author = entry.get("author", "").replace("/u/", "").strip()

        posts.append(
            {
                "id": _post_id(entry.get("id", entry.get("link", ""))),
                "subreddit": subreddit,
                "title": title,
                "flair": None,  # RSS'te flair yok; title on eklerine guveniyoruz
                "body": strip_html(content),
                "url": entry.get("link", ""),
                "author": author,
                "budget": None,
                "created_utc": _created_utc(entry),
            }
        )
    return posts


def sync(conn, subreddits: list[str], limit: int) -> int:
    import storage

    total = 0
    for i, name in enumerate(subreddits):
        try:
            posts = parse_subreddit(name, limit)
            total += storage.upsert_posts(conn, posts)
            log.info("%s: %d post kaydedildi/guncellendi", name, len(posts))
        except (RuntimeError, OSError) as exc:
            log.warning("%s", exc)
        if i < len(subreddits) - 1:
            time.sleep(2)  # Reddit rate-limit'i (429) onlemek icin
    return total