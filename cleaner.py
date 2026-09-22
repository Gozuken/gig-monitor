import logging
import re
import time

import config

log = logging.getLogger(__name__)

MONEY_RE = re.compile(r"\$\s?(\d+(?:[kKmM])?)", re.IGNORECASE)


def extract_budget(text: str) -> str | None:
    match = MONEY_RE.search(text or "")
    return match.group(1) if match else None


def _flair_tags(flair: str | None) -> str:
    return (flair or "").lower().strip()


def _is_hired(flair: str | None) -> bool:
    f = _flair_tags(flair)
    return any(tag in f for tag in config.HIRED_FLAIRS)


def _verdict(flair: str | None, title: str) -> bool | None:
    """True = is veren ilani, False = degil, None = kararsiz."""
    f = _flair_tags(flair)
    if f:
        if any(tag in f for tag in config.HIRING_FLAIRS):
            return True
        if any(tag in f for tag in config.FOR_HIRE_FLAIRS):
            return False
    t = title.lower()
    if any(m in t for m in config.TITLE_HIRING_MARKERS):
        return True
    if any(m in t for m in config.TITLE_FOR_HIRE_MARKERS):
        return False
    return None


def matches_keywords(title: str, body: str, keywords: list[str]) -> bool:
    if not keywords:
        return True
    haystack = f"{title} {body}".lower()
    return any(k.lower() in haystack for k in keywords)


def evaluate(post: dict, now: float, max_age_days: int, keywords: list[str]) -> tuple[str, str | None]:
    """Hard-rule degerlendirmesi. (status, reason) dondurur."""
    if _is_hired(post["flair"]):
        return "filtered", "hired"

    if not _verdict(post["flair"], post["title"]):
        # False => kendi isini pazarlayan ilan (rakip), None => hizmet mi is mi
        # belli degil (spam riski yuksek). Ikisi de ele.
        return "filtered", "not_hiring"

    age_days = (now - post["created_utc"]) / 86400.0
    if age_days > max_age_days:
        return "filtered", "stale"

    if post.get("budget") is None:
        budget = extract_budget(f"{post.get('title') or ''} {post.get('body') or ''}")
        post["budget"] = budget

    if not matches_keywords(post["title"], post["body"], keywords):
        return "filtered", "keyword_miss"

    return "kept", None


def update_budget(conn, post_id: str, budget: str | None) -> None:
    import storage

    storage.set_budget(conn, post_id, budget)


def run_pipeline(conn, max_age_days: int, keywords: list[str]) -> dict[str, int]:
    """Kayitli new/kept post'lari yeniden degerlendirir, istatistik dondurur."""
    now = time.time()
    counts = {"scanned": 0, "kept": 0, "filtered": 0, "changed": 0}
    for row in pending_posts(conn):
        post = dict(row)
        status, reason = evaluate(post, now, max_age_days, keywords)
        counts["scanned"] += 1
        if status == "kept":
            counts["kept"] += 1
        else:
            counts["filtered"] += 1
        if post["status"] != status or post["filter_reason"] != reason:
            set_post_status(conn, post["id"], status, reason)
            counts["changed"] += 1
        if status == "kept" and post.get("budget"):
            update_budget(conn, post["id"], post["budget"])
    log.info(
        "temizleme: %d tarandi, %d kept, %d filtered, %d degisti",
        counts["scanned"], counts["kept"], counts["filtered"], counts["changed"],
    )
    return counts


def pending_posts(conn):
    import storage

    return storage.pending_posts(conn)


def set_post_status(conn, post_id, status, reason):
    import storage

    storage.set_post_status(conn, post_id, status, reason)