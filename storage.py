import json
import sqlite3
import time
from typing import Iterable, Optional

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS posts (
    id TEXT PRIMARY KEY,
    subreddit TEXT NOT NULL,
    title TEXT NOT NULL,
    flair TEXT,
    body TEXT,
    url TEXT,
    author TEXT,
    budget TEXT,
    created_utc REAL NOT NULL,
    first_seen REAL NOT NULL,
    last_seen REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'new',
    filter_reason TEXT
);
CREATE INDEX IF NOT EXISTS idx_posts_status ON posts(status);
CREATE INDEX IF NOT EXISTS idx_posts_created ON posts(created_utc DESC);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

DEFAULT_SETTINGS = {
    "interval_sec": str(config.DEFAULT_INTERVAL_SEC),
    "max_age_days": str(config.DEFAULT_MAX_AGE_DAYS),
    "fetch_limit": str(config.DEFAULT_FETCH_LIMIT),
    "keywords": config.DEFAULT_KEYWORDS,
    "subreddits": ",".join(config.DEFAULT_SUBREDDITS),
    # AI filtre
    "ai_profile": "",
    "ai_base_url": config.LLM_BASE_URL,
    "ai_model": config.LLM_MODEL,
    "ai_api_key": config.GOOGLE_API_KEY,
    "ai_threshold": str(config.AI_THRESHOLD),
}

_AI_COLUMNS = {
    "ai_score": "REAL",
    "ai_reason": "TEXT",
    "ai_checked": "REAL",
}


def connect(db_path=None) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path or config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    _migrate(conn)
    _seed_settings(conn)
    conn.commit()
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    """Mevcut posts tablosuna eksik AI kolonlarini ekler."""
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(posts)")}
    for name, col_type in _AI_COLUMNS.items():
        if name not in cols:
            conn.execute(f"ALTER TABLE posts ADD COLUMN {name} {col_type}")


def _seed_settings(conn: sqlite3.Connection) -> None:
    for key, value in DEFAULT_SETTINGS.items():
        conn.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
            (key, value),
        )


def get_setting(conn: sqlite3.Connection, key: str) -> str:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    if row is None:
        return DEFAULT_SETTINGS.get(key, "")
    return row["value"]


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    conn.commit()


def get_settings(conn: sqlite3.Connection) -> dict:
    return {k: get_setting(conn, k) for k in DEFAULT_SETTINGS}


def get_setting_int(conn: sqlite3.Connection, key: str) -> int:
    raw = get_setting(conn, key)
    try:
        return int(raw)
    except (TypeError, ValueError):
        return int(DEFAULT_SETTINGS.get(key, "0"))


def parse_list(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def upsert_posts(conn: sqlite3.Connection, posts: Iterable[dict]) -> int:
    now = time.time()
    count = 0
    for post in posts:
        conn.execute(
            """
            INSERT INTO posts (
                id, subreddit, title, flair, body, url, author, budget,
                created_utc, first_seen, last_seen, status, filter_reason
            ) VALUES (
                :id, :subreddit, :title, :flair, :body, :url, :author, :budget,
                :created_utc, :first_seen, :last_seen, :status, :filter_reason
            )
            ON CONFLICT(id) DO UPDATE SET
                flair = excluded.flair,
                title = excluded.title,
                body = excluded.body,
                last_seen = excluded.last_seen
            """,
            {
                "id": post["id"],
                "subreddit": post["subreddit"],
                "title": post["title"],
                "flair": post.get("flair"),
                "body": post.get("body") or "",
                "url": post["url"],
                "author": post.get("author") or "",
                "budget": post.get("budget"),
                "created_utc": post["created_utc"],
                "first_seen": post.get("first_seen", now),
                "last_seen": now,
                "status": post.get("status", "new"),
                "filter_reason": post.get("filter_reason"),
            },
        )
        count += 1
    conn.commit()
    return count


def set_post_status(
    conn: sqlite3.Connection, post_id: str, status: str, reason: Optional[str]
) -> None:
    conn.execute(
        "UPDATE posts SET status = ?, filter_reason = ? WHERE id = ?",
        (status, reason, post_id),
    )


def set_budget(conn: sqlite3.Connection, post_id: str, budget: str) -> None:
    conn.execute("UPDATE posts SET budget = ? WHERE id = ?", (budget, post_id))


def set_ai_result(conn: sqlite3.Connection, post_id: str, score, reason: str) -> None:
    conn.execute(
        "UPDATE posts SET ai_score = ?, ai_reason = ?, ai_checked = ? WHERE id = ?",
        (score, reason, time.time(), post_id),
    )


def ai_kept_posts(conn: sqlite3.Connection, threshold: int) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT * FROM posts
        WHERE status = 'kept' AND ai_score IS NOT NULL AND ai_score >= ?
        ORDER BY ai_score DESC, created_utc DESC
        """,
        (threshold,),
    ).fetchall()


def pending_ai_posts(conn: sqlite3.Connection, limit: int) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT * FROM posts
        WHERE status = 'kept'
        ORDER BY created_utc DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()


def pending_posts(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM posts WHERE status IN ('new', 'kept') ORDER BY created_utc DESC"
    ).fetchall()


def list_posts(
    conn: sqlite3.Connection, status: Optional[str] = None, limit: int = 200
) -> list[sqlite3.Row]:
    if status:
        rows = conn.execute(
            "SELECT * FROM posts WHERE status = ? ORDER BY created_utc DESC LIMIT ?",
            (status, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM posts ORDER BY created_utc DESC LIMIT ?", (limit,)
        ).fetchall()
    return rows


def count_by_status(conn: sqlite3.Connection) -> dict[str, int]:
    rows = conn.execute(
        "SELECT status, COUNT(*) AS n FROM posts GROUP BY status"
    ).fetchall()
    return {row["status"]: row["n"] for row in rows}


def export_posts(conn: sqlite3.Connection) -> str:
    rows = list_posts(conn, limit=10000)
    return json.dumps([dict(row) for row in rows], indent=2, ensure_ascii=False)
