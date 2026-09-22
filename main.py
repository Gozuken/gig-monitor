"""CLI giris noktasi.

    python main.py scrape   -> tek cekim + temizleme
    python main.py run      -> arka plan dongusu (interval ayari DB'den)
    python main.py serve    -> Flask kontrol paneli + ayar yapili scheduler
"""

import argparse
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def cmd_scrape(args):
    import storage

    conn = storage.connect()
    try:
        import scheduler

        scheduler.scrape_and_clean(conn)
        print("Cekim + temizleme tamam.")
        print("Kontrol paneli icin:                 python main.py serve")
    finally:
        conn.close()


def cmd_run(args):
    import storage

    if args.interval is not None:
        interval = args.interval
    else:
        conn = storage.connect()
        interval = storage.get_setting_int(conn, "interval_sec")
        conn.close()
    if interval <= 0:
        print("interval_sec=0 (scheduler kapali). Once serve ile panelden ac:")
        print("    python main.py serve   (veya --interval <sn> ver)")
        return
    import scheduler

    sched = scheduler.Scheduler(scheduler.make_job())
    sched.start(interval)
    try:
        import time

        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        sched.stop()
        print("durdu")


def cmd_serve(args):
    import ui

    ui.run(debug=args.debug)


def app():
    parser = argparse.ArgumentParser(prog="reddit-job-tracker")
    sub = parser.add_subparsers(dest="command", required=True)

    p_scrape = sub.add_parser("scrape", help="tek cekim + temizleme kosusu")
    p_scrape.add_argument("-n", "--interval", action="store_true",
                          help="(uyumsuz) scheduler intervalini kullan")

    p_run = sub.add_parser("run", help="arka plan dongusu (DB'deki interval ile)")
    p_run.add_argument("--interval", type=int, default=None,
                       help="interval saniye (0=kapali); DB ayari ezer")

    p_serve = sub.add_parser("serve", help="kontrol panelini baslat")
    p_serve.add_argument("--debug", action="store_true", help="Flask debug modu")

    args = parser.parse_args()
    try:
        if args.command == "scrape":
            cmd_scrape(args)
        elif args.command == "run":
            cmd_run(args)
        elif args.command == "serve":
            cmd_serve(args)
    except RuntimeError as exc:
        print(f"[hata] {exc}")


if __name__ == "__main__":
    app()