"""Synthetic-trigger drill for the execution alerts (lane `execution-alerts`). Sends REAL emails, marked DRILL.

    python3 scripts/execution_alert_drill.py --alerts-env ~/syndicate-prod/alerts.env [--no-email]

Proves every alert end to end through the code the 5-minute watchdog runs (`local_watchdog.main` ->
`execution_watchdog` -> `alert_mailer`), against SYNTHETIC state, with nothing of production touched:

  * its own redis-server on a spare port (default 6391), deleted afterwards;
  * a temp fleet home (pidfile, logs, alerts.env copied in so the drill mails the real inbox);
  * a dummy "live-odds-worker" process whose environment points at that redis and temp reports root --
    the watchdog reads the store env from the worker's /proc environ exactly as it does in production;
  * web /healthz is the real fleet's (read-only GET), so the fleet half of the watchdog stays green.

Steps (each prints what it saw):
  1 baseline   healthy synthetic book                      -> no alert email
  2 triggers   heartbeat 40 min old, kill switch, unreconciled 60 min, balance stamp 45 min old,
               kalshi auth_error, polymarket below threshold + pending deposit, an unknown submit,
               3 kalshi + 3 polymarket adapter failure lines -> ONE email listing every NEW finding
  3 repeat     same state                                   -> no email (deduped)
  4 healthy    restored                                     -> ONE "cleared" email
  5 worker     the dummy worker is killed                   -> email: role:live-odds-worker (+ heartbeat)
  6 digest     the daily digest for the synthetic day       -> ONE digest email
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import alert_mailer as mailer  # noqa: E402
from scripts import execution_watchdog as xw  # noqa: E402
from scripts import local_production as lp  # noqa: E402
from scripts import local_watchdog as wd  # noqa: E402


def _z(minutes_ago: float) -> str:
    return (dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=minutes_ago)).isoformat().replace("+00:00", "Z")


def healthy_store() -> dict[str, dict]:
    return {
        "execution_state.json": {"recorded_by": "live-odds-worker", "recorded_at": _z(2), "execution_mode": "live",
                                 "live_armed": True, "execution_enabled": True, "venue": "kalshi,polymarket",
                                 "kill_switch": {"engaged": False, "source": "clear"}},
        "venue_balances.json": {"recorded_by": "live-odds-worker", "recorded_at": _z(2), "venues": {
            "kalshi": {"status": "ok", "dollars": 485.48, "portfolio_value_dollars": 4.5},
            "polymarket": {"status": "ok", "dollars": 86.05, "buying_power_dollars": 86.05,
                           "detail": {"numbers": {"depositReservation": 0.0, "displayedAvailableSoon": 0.0}}}}},
        "execution_ledger.json": {"orders": [
            {"idempotency_key": "drill0filled", "mode": "live", "venue": "kalshi", "venue_ticker": "KXDRILL-1",
             "status": "filled", "submitted_at": _z(600), "reconciled_at": _z(2), "fill_stake_dollars": 4.53,
             "fees_dollars": 0.03, "outcome": "won", "pnl_dollars": 0.47, "graded_at": _z(30), "sport": "drill"}]},
    }


def triggered_store() -> dict[str, dict]:
    store = healthy_store()
    store["execution_state.json"].update(recorded_at=_z(40), kill_switch={"engaged": True, "source": "flag",
                                                                           "detail": "DRILL synthetic", "set_at": _z(1)})
    store["venue_balances.json"]["recorded_at"] = _z(45)
    store["venue_balances.json"]["venues"]["kalshi"] = {"status": "auth_error", "detail": "DRILL http_401"}
    store["venue_balances.json"]["venues"]["polymarket"].update(
        buying_power_dollars=12.0, dollars=12.0, detail={"numbers": {"depositReservation": 100.0}})
    store["execution_ledger.json"]["orders"] += [
        {"idempotency_key": "drill1stuck", "mode": "live", "venue": "kalshi", "venue_ticker": "KXDRILL-2",
         "status": "submitted", "submitted_at": _z(60), "requested_stake_dollars": 5.0, "sport": "drill"},
        {"idempotency_key": "drill2unknown", "mode": "live", "venue": "polymarket", "venue_ticker": "drill-slug",
         "status": "failed", "error": 'DRILL http_503 {"code":14}', "submitted_at": _z(30),
         "requested_stake_dollars": 1.84, "sport": "drill"},
    ]
    return store


FAILURE_LINES = (
    ["[kalshi_orders] SUBMIT_FAILED_MARKET ticker=KXDRILL-3 DRILL"] * 3
    + ["[polymarket_us_orders] ORDERS_READ_ALL_FAILED n=1 errors=['DRILL http_503']"] * 3
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--alerts-env", required=True, help="the real alerts.env (SMTP settings) to mail with")
    parser.add_argument("--redis-port", type=int, default=6391)
    parser.add_argument("--web-port", type=int, default=10000, help="a /healthz that answers (the fleet's web)")
    parser.add_argument("--no-email", action="store_true", help="run every step, queue but do not send")
    args = parser.parse_args(argv)

    root = Path(tempfile.mkdtemp(prefix="execdrill-"))
    home = root / "home"
    settings = lp.Settings(home=home, port=args.web_port)
    for d in (settings.run_dir, settings.logs_dir, settings.data_root / "reports" / "intelligence"):
        d.mkdir(parents=True, exist_ok=True)
    if not args.no_email:
        shutil.copy(Path(args.alerts_env).expanduser(), home / "alerts.env")
        os.chmod(home / "alerts.env", 0o600)
    mailer.SUBJECT_PREFIX = "[Syndicate DRILL]"
    mailer.MAX_SENDS_PER_HOUR = 20

    redis = subprocess.Popen(["redis-server", "--port", str(args.redis_port), "--bind", "127.0.0.1", "--save", "",
                              "--appendonly", "no", "--dir", str(root)], stdout=subprocess.DEVNULL)
    store_env = {"SYNDICATE_REFRESH_STATE_BACKEND": "keyvalue",
                 "SYNDICATE_REFRESH_STATE_URL": f"redis://127.0.0.1:{args.redis_port}/0",
                 "SYNDICATE_REFRESH_STATE_NAMESPACE": "execdrill",
                 "SYNDICATE_REPORTS_ROOT": str(settings.data_root / "reports")}
    worker = subprocess.Popen(["sleep", "3600"], env={**os.environ, **store_env})
    time.sleep(0.5)
    os.environ.update(store_env)
    from syndicate.features.shared import refresh_state_store as rss

    intelligence = rss.reports_root() / "intelligence"

    def write_store(store: dict[str, dict]) -> None:
        for name, payload in store.items():
            rss.write_json_file(intelligence / name, payload)

    def write_pidfile(alive: bool) -> None:
        me = os.getpid()
        roles = {"web": me, "refresh-worker": me, "live-odds-worker": worker.pid if alive else 999999}
        (settings.run_dir / lp.PIDFILE_NAME).write_text(json.dumps(
            {"supervisor_pid": me, "roles": roles, "restarts": {k: 0 for k in roles}, "port": args.web_port}))
        for role in roles:  # fresh role logs so the fleet heartbeat check is green
            with (settings.logs_dir / f"{role}.log").open("a", encoding="utf-8") as handle:
                handle.write(f"{_z(0)} drill tick\n")

    def step(name: str) -> dict:
        print(f"\n=== {name}", flush=True)
        result = {}
        # local_watchdog.main prints its JSON; capture by calling the same functions it does.
        import contextlib
        import io

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            wd.main(["--home", str(home), "--port", str(args.web_port), "--json"])
        result = json.loads(buf.getvalue().strip().splitlines()[-1])
        print(f"status={result['status']} email={result.get('email')}")
        for f in result.get("findings") or []:
            if f["key"] == "backup":
                continue  # no backup dir in a temp home; a warn, never emailed
            print(f"  [{f['severity']}] {f['key']}: {f['message'][:160]}")
        return result

    if args.no_email:
        os.environ["SYNDICATE_DRILL_NO_EMAIL"] = "1"
        mailer.smtp_send = lambda config, subject, body: print(f"  (not sent) {subject}")
        (home / "alerts.env").write_text("SYNDICATE_ALERT_SMTP_USER=drill@example.com\n"
                                         "SYNDICATE_ALERT_SMTP_PASSWORD=x\n", encoding="utf-8")
    today = dt.datetime.now(dt.timezone.utc).date().isoformat()
    (settings.run_dir / "scheduled_jobs.json").write_text(json.dumps(
        {job.name: {"last_run_date": today, "last_rc": 0} for job in lp.SCHEDULED_JOBS}))
    # The digest is step 6's; without this, step 1 would send yesterday's (it is due once a day after 8 AM CT).
    (settings.run_dir / wd.STATE_NAME).write_text(json.dumps(
        {"execution": {"last_digest_day": (xw.central(dt.datetime.now(dt.timezone.utc)).date()
                                           - dt.timedelta(days=1)).isoformat()}}))
    try:
        write_pidfile(True)
        write_store(healthy_store())
        step("1 baseline (healthy; also sets the log cursor)")
        write_store(triggered_store())
        with (settings.logs_dir / "live-odds-worker.log").open("a", encoding="utf-8") as handle:
            for line in FAILURE_LINES:
                handle.write(f"{_z(0)} {line}\n")
        write_pidfile(True)
        step("2 every trigger at once -> one email")
        write_pidfile(True)
        step("3 same state -> deduped, no email")
        write_store(healthy_store())
        state_path = settings.run_dir / wd.STATE_NAME
        state = json.loads(state_path.read_text())
        state.setdefault("execution", {})["log_holds"] = {}  # end the log-burst hold now rather than in 30 min
        state_path.write_text(json.dumps(state))
        write_pidfile(True)
        step("4 healthy again -> one cleared email")
        worker.kill()
        worker.wait()
        rss._get_keyvalue_client.cache_clear()  # noqa: SLF001 -- the fallback env names another redis
        write_pidfile(False)
        step("5 live-odds-worker gone -> email")
        print("\n=== 6 daily digest")
        now = dt.datetime.now(dt.timezone.utc)
        exec_state = json.loads(state_path.read_text()).get("execution") or {}
        os.environ.update(store_env)
        rss._get_keyvalue_client.cache_clear()  # noqa: SLF001
        readings = xw.read_store_state(store_env)
        message = xw.digest_message(settings, now, exec_state, readings, {}, force_day=xw.central(now).date())
        message["subject"] = "digest drill: " + message["subject"]
        summary = mailer.deliver(settings, [message], now)
        print(f"digest: {summary.get('sent') or summary.get('failed') or summary}")
        print("\nmailer log:")
        print((settings.logs_dir / mailer.LOG_NAME).read_text())
    finally:
        if worker.poll() is None:
            worker.kill()
        redis.send_signal(signal.SIGTERM)
        redis.wait(timeout=10)
        shutil.rmtree(root, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
