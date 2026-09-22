"""Flask kontrol paneli + ayar yapilabilir scheduler."""

import logging
import threading
import time

from flask import Flask, jsonify, redirect, render_template, request, url_for

import config
import scheduler
import storage

log = logging.getLogger(__name__)

app = Flask(__name__)
sched = scheduler.Scheduler(scheduler.make_job())
_lock = threading.Lock()


def _conn():
    return storage.connect()


def _format_age(created_utc: float) -> str:
    age_h = (time.time() - created_utc) / 3600.0
    if age_h < 1:
        return f"{int(age_h * 60)}dk"
    if age_h < 48:
        return f"{int(age_h)}s"
    return f"{age_h / 24:.1f}g"


def _sched_state() -> dict:
    return {
        "running": sched.running,
        "interval_sec": sched.interval_sec if sched.running else 0,
        "last_duration": round(sched.last_duration, 1),
    }


@app.context_processor
def inject_globals():
    return {
        "sched": _sched_state(),
        "now": time.time(),
        "format_age": _format_age,
    }


@app.route("/")
def index():
    conn = _conn()
    try:
        view = request.args.get("view", "kept")
        kept = storage.list_posts(conn, status="kept")
        new = storage.list_posts(conn, status="new")
        ai = []
        ai_threshold = config.AI_THRESHOLD
        if view == "ai":
            ai_threshold = storage.get_setting_int(conn, "ai_threshold")
            ai = storage.ai_kept_posts(conn, ai_threshold)
        filtered = storage.list_posts(conn, status="filtered")
        counts = storage.count_by_status(conn)
        settings = storage.get_settings(conn)
        return render_template(
            "index.html",
            kept=kept,
            new=new,
            ai=ai,
            ai_threshold=ai_threshold,
            filtered=filtered,
            counts=counts,
            settings=settings,
            view=view,
        )
    finally:
        conn.close()


@app.route("/settings", methods=["GET", "POST"])
def settings_page():
    conn = _conn()
    try:
        if request.method == "POST":
            error = apply_settings(conn)
            if error:
                return render_template("settings.html", error=error,
                                       settings=storage.get_settings(conn))
            return redirect(url_for("settings_page"))
        return render_template("settings.html", settings=storage.get_settings(conn), error=None)
    finally:
        conn.close()


def apply_settings(conn):
    form = request.form
    interval = form.get("interval_sec", "0").strip()
    try:
        interval_i = int(interval)
    except ValueError:
        return f"interval_sec gecerli bir sayi olmali: '{interval}'"
    max_age = form.get("max_age_days", "5").strip()
    try:
        max_age_i = int(max_age)
    except ValueError:
        return f"max_age_days gecerli bir sayi olmali: '{max_age}'"

    loud = {"interval_sec": str(interval_i), "max_age_days": str(max_age_i)}
    silent = {
        "keywords": form.get("keywords", ""),
        "subreddits": form.get("subreddits", ""),
        "fetch_limit": form.get("fetch_limit", "100"),
        "ai_profile": form.get("ai_profile", ""),
        "ai_base_url": form.get("ai_base_url", ""),
        "ai_model": form.get("ai_model", ""),
        "ai_api_key": form.get("ai_api_key", ""),
        "ai_threshold": form.get("ai_threshold", "50"),
    }
    for k, v in loud.items():
        storage.set_setting(conn, k, v)
    for k, v in silent.items():
        storage.set_setting(conn, k, v)

    if "action" in form and form["action"] == "apply":
        # yeni interval scheduler'a aninda islemek icin
        if sched.running:
            sched.set_interval(interval_i)
    return None


@app.route("/api/start", methods=["POST"])
def api_start():
    conn = _conn()
    try:
        interval = storage.get_setting_int(conn, "interval_sec")
    finally:
        conn.close()
    if interval <= 0:
        return jsonify({"ok": False, "error": "once interval_sec > 0 ayarlayin"}), 400
    with _lock:
        sched.start(interval)
    return jsonify({"ok": True, "running": sched.running})


@app.route("/api/stop", methods=["POST"])
def api_stop():
    with _lock:
        sched.stop()
    return jsonify({"ok": True, "running": sched.running})


@app.route("/api/scrape", methods=["POST"])
def api_scrape():
    conn = _conn()
    try:
        with _lock:
            if sched.running:
                return jsonify({"ok": False, "error": "scheduler calisiyor"}), 409
            kept = scheduler.scrape_and_clean(conn)
        return jsonify({"ok": True, "kept": kept})
    finally:
        conn.close()


@app.route("/api/ai_filter", methods=["POST"])
def api_ai_filter():
    import ai

    conn = _conn()
    try:
        settings = storage.get_settings(conn)
        profile = (settings.get("ai_profile") or "").strip()
        if not profile:
            return jsonify({"ok": False, "error": "once Ayarlar'dan profil metni (CV) gir"}), 400
        base = (settings.get("ai_base_url") or "").strip()
        model = (settings.get("ai_model") or "").strip()
        apikey = (settings.get("ai_api_key") or "").strip()
        if not base or not model:
            return jsonify({"ok": False, "error": "ai_base_url / ai_model ayari eksik (Ayarlar)"}), 400

        posts = storage.pending_ai_posts(conn, limit=50)
        if not posts:
            return jsonify({"ok": False, "error": "henuz uygun (kept) ilan yok"}), 404

        with _lock:
            results = ai.score_posts([dict(p) for p in posts], profile, base, apikey, model)

        threshold = storage.get_setting_int(conn, "ai_threshold")
        above = below = failed = 0
        for post_id, info in results.items():
            storage.set_ai_result(conn, post_id, info["score"], info["reason"])
            if info["score"] is None:
                failed += 1
            elif info["score"] >= threshold:
                above += 1
            else:
                below += 1

        scored = len(results) - failed
        return jsonify({
            "ok": True,
            "scanned": len(results),
            "scored": scored,
            "above_threshold": above,
            "below_threshold": below,
            "failed": failed,
        })
    finally:
        conn.close()


@app.route("/api/settings", methods=["GET"])
def api_settings():
    conn = _conn()
    try:
        return jsonify({"settings": storage.get_settings(conn), "sched": _sched_state()})
    finally:
        conn.close()


def run(debug=False):
    log.info("panel: http://%s:%d", config.FLASK_HOST, config.FLASK_PORT)
    app.run(host=config.FLASK_HOST, port=config.FLASK_PORT, debug=debug, use_reloader=False)