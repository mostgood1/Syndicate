"""Live-execution checks, email alerts and the daily digest for the local fleet (lane `execution-alerts`).

    python3 scripts/execution_watchdog.py                 # one check, human summary (no state saved, no email)
    python3 scripts/execution_watchdog.py --json
    python3 scripts/execution_watchdog.py --digest-now    # print the digest that would be emailed

Normally NOT run by hand: `scripts/local_watchdog.py` calls `run()` every 5 minutes (the Windows task
`SyndicateFleetWatchdog`), adds these findings to the fleet's, and hands email to `scripts/alert_mailer.py`.

WHY. Live money has run on this machine since 2026-10-19 16:04Z and nothing told anyone when it stopped
working: the 2026-10-19 audit found no alerting in the worker at all. Every check below reads what the
live-odds-worker ALREADY writes; this file adds no writer to the money path.

WHAT IS CHECKED (key -> severity). Every `exec:` finding is emailed.
  exec:heartbeat              execution_state.json (`record_execution_state`, every execution tick)
                              older than HEARTBEAT_MAX_MINUTES, or never written            fail
  exec:kill_switch            the stamped kill switch is engaged (env / flag / read_failed) fail
  exec:unreconciled           a LIVE `submitted` row the venue has not confirmed for
                              UNRECONCILED_MINUTES (it blocks every live run)              fail
  exec:balance_stale          venue_balances.json older than BALANCE_STALE_MINUTES          fail
  exec:balance_status:<v>     a venue's balance read is not `ok` (auth_error, ...)          fail
  exec:balance_low:<v>        spendable dollars below the venue's threshold                 fail
  exec:pending_deposit        Polymarket reports a pending deposit (it is counted in
                              buyingPower but cannot be spent yet)                          warn
  exec:unknown_submits        a LIVE order failed with no venue answer and no venue id --
                              it may or may not be a position                               fail
  exec:log_errors:<group>     >= LOG_ERRORS_PER_CHECK failure lines from the order adapters
                              / execution tick in one check; held LOG_HOLD_MINUTES          fail
  exec:monitor                this monitor could not read the store (fails LOUD, not quiet) fail

Process death is the fleet watchdog's (`role:live-odds-worker`, `heartbeat:live-odds-worker`,
`crashloop:*`); those FAIL findings are emailed too (`email_messages`).

THRESHOLDS are overridable in `<home>/alerts.env` (the same file as the SMTP settings):
  SYNDICATE_ALERT_HEARTBEAT_MAX_MINUTES (25)   SYNDICATE_ALERT_UNRECONCILED_MINUTES (20)
  SYNDICATE_ALERT_BALANCE_STALE_MINUTES (30)   SYNDICATE_ALERT_MIN_BALANCE_KALSHI (50)
  SYNDICATE_ALERT_MIN_BALANCE_POLYMARKET (25)  SYNDICATE_ALERT_LOG_ERRORS_PER_CHECK (3)
  SYNDICATE_ALERT_DIGEST_HOUR_CT (8)

STATE lives inside the fleet watchdog's state file under `execution` (log cursor, digest accumulator,
log-burst holds), so one file says what the watchdog knows.
"""

from __future__ import annotations

import argparse
import ast
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import local_production as lp  # noqa: E402

try:
    from zoneinfo import ZoneInfo

    CENTRAL = ZoneInfo("America/Chicago")
except Exception:  # pragma: no cover - tzdata missing
    CENTRAL = dt.timezone(dt.timedelta(hours=-5), "CDT")

FAIL, WARN = "fail", "warn"
EXEC_PREFIX = "exec:"
WORKER_ROLE = "live-odds-worker"
LIVE = "live"

DEFAULTS = {
    "heartbeat_max_minutes": 25.0,
    "unreconciled_minutes": 20.0,
    "balance_stale_minutes": 30.0,
    "min_balance_kalshi": 50.0,
    "min_balance_polymarket": 25.0,
    "log_errors_per_check": 3.0,
    "digest_hour_ct": 8.0,
}
_THRESHOLD_ENV = {
    "heartbeat_max_minutes": "SYNDICATE_ALERT_HEARTBEAT_MAX_MINUTES",
    "unreconciled_minutes": "SYNDICATE_ALERT_UNRECONCILED_MINUTES",
    "balance_stale_minutes": "SYNDICATE_ALERT_BALANCE_STALE_MINUTES",
    "min_balance_kalshi": "SYNDICATE_ALERT_MIN_BALANCE_KALSHI",
    "min_balance_polymarket": "SYNDICATE_ALERT_MIN_BALANCE_POLYMARKET",
    "log_errors_per_check": "SYNDICATE_ALERT_LOG_ERRORS_PER_CHECK",
    "digest_hour_ct": "SYNDICATE_ALERT_DIGEST_HOUR_CT",
}
LOG_HOLD_MINUTES = 30
MAX_SCAN_BYTES = 64 * 1024 * 1024
SAMPLE_LINES = 3
DIGEST_DAYS_KEPT = 8

# The store env the WORKER runs with. Read from its /proc environ so this reads exactly the keys it writes;
# only these names are copied -- the worker's environ also holds venue private keys, which never leave it.
STATE_ENV_KEYS = (
    "SYNDICATE_REFRESH_STATE_BACKEND", "SYNDICATE_REFRESH_STATE_URL", "SYNDICATE_REFRESH_STATE_NAMESPACE",
    "REDIS_URL", "SYNDICATE_REPORTS_ROOT", "SYNDICATE_STATE_ROOT", "SYNDICATE_DATA_ROOT",
    "SYNDICATE_REQUIRE_HOSTED_STORAGE", "SYNDICATE_LOCAL_PRODUCTION",
)

# FAILURE LINES. The adapters RAISE rather than print, so most failures surface one layer out
# (execute_portfolio / live_odds_worker / execution_ledger); the adapter-level tokens are the ones that
# only print on failure. Group = which alert key a line counts toward.
LOG_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("kalshi", re.compile(r"\[kalshi_orders\] \S*(?:FAIL|ERROR)")),
    ("polymarket", re.compile(r"\[polymarket_us_orders\] \S*(?:FAIL|ERROR|IMPLAUSIBLE|ABOVE_LIMIT|OUT_OF_RANGE)")),
    ("orders", re.compile(r"\[execute_portfolio\] (?:LIVE_ORDER status=failed|RECONCILE_FAILED)")),
    ("orders", re.compile(r"\[execution_ledger\] (?:RECONCILE_READ_FAILED|RECONCILE_SINGLE_READ_FAILED|MERGE_READ_FAILED)")),
    ("tick", re.compile(r"\[live_odds_worker\] (?:EXECUTION_ERROR|VENUE_SETTLEMENT_FAILED|ORDER_PATH_FAILED|"
                        r"LEDGER_RECONCILE_FAILED|EXECUTION_STATE_STAMP_FAILED|VENUE_BALANCES_STAMP_FAILED|SELF_HEAL_FAILED)")),
)
_EXECUTION_LINE = re.compile(r"\[live_odds_worker\] EXECUTION status=(\S+) reason=(\S+) mode=(\S+) venue=(\S+)"
                             r".*? refused=(\{.*?\}) spent=")
_SELF_HEALED = re.compile(r"\[execution_self_heal\] UNKNOWN_SUBMIT_AUTO_RESOLVED .*?finding=(\S+)")
_VENUE_IN_LINE = re.compile(r"\bvenue=(kalshi|polymarket)")


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------


def _parse_time(value: Any) -> dt.datetime | None:
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)


def _age_minutes(value: Any, now: dt.datetime) -> float | None:
    parsed = _parse_time(value)
    return None if parsed is None else (now - parsed).total_seconds() / 60.0


def _num(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out == out else None


def _money(value: Any) -> str:
    n = _num(value)
    return "?" if n is None else f"${n:,.2f}"


def thresholds(home: Path) -> dict[str, float]:
    raw = lp.parse_env_file(home / "alerts.env") if (home / "alerts.env").is_file() else {}
    out = dict(DEFAULTS)
    for name, env in _THRESHOLD_ENV.items():
        value = _num(raw.get(env))
        if value is not None and value >= 0:
            out[name] = value
    return out


def central(now: dt.datetime) -> dt.datetime:
    return now.astimezone(CENTRAL)


def fmt_ct(value: Any) -> str:
    parsed = value if isinstance(value, dt.datetime) else _parse_time(value)
    return "?" if parsed is None else central(parsed).strftime("%a %m-%d %I:%M %p CT")


# --------------------------------------------------------------------------
# readings (all I/O lives here)
# --------------------------------------------------------------------------


def worker_state_env(settings: lp.Settings, pid: Any) -> dict[str, str]:
    """The store env of the running worker, falling back to what `local_production.py up` derives."""
    env = {
        "SYNDICATE_REFRESH_STATE_BACKEND": "keyvalue",
        "SYNDICATE_REFRESH_STATE_URL": settings.redis_url,
        "SYNDICATE_REPORTS_ROOT": str(settings.data_root / "reports"),
        "SYNDICATE_DATA_ROOT": str(settings.data_root),
    }
    try:
        blob = Path(f"/proc/{int(pid)}/environ").read_bytes()
    except (OSError, TypeError, ValueError):
        return env
    for item in blob.split(b"\0"):
        key, _, value = item.partition(b"=")
        name = key.decode("utf-8", "replace")
        if name in STATE_ENV_KEYS:
            env[name] = value.decode("utf-8", "replace")
    return env


def _read_store(path: Path) -> tuple[dict[str, Any] | None, bool]:
    from syndicate.features.shared.refresh_state_store import read_json_file_result

    return read_json_file_result(path)


def _lean(order: Mapping[str, Any]) -> dict[str, Any]:
    keep = ("idempotency_key", "mode", "venue", "sport", "market", "side", "line", "venue_ticker", "status",
            "outcome", "pnl_dollars", "graded_at", "submitted_at", "venue_resolved_at", "reconciled_at",
            "venue_order_id", "operator_resolution", "error", "requested_stake_dollars", "fill_stake_dollars",
            "fill_price", "fees_dollars", "selected_date", "player")
    return {k: order.get(k) for k in keep if k in order}


def read_store_state(env: Mapping[str, str]) -> dict[str, Any]:
    """execution_state, venue_balances, the kill-switch flag and the ledger's rows, via the modules' own readers."""
    os.environ.update(env)
    from syndicate.features.shared.refresh_state_store import reports_root

    intelligence = reports_root() / "intelligence"
    out: dict[str, Any] = {"store_errors": []}
    for name, filename in (("execution_state", "execution_state.json"), ("venue_balances", "venue_balances.json"),
                           ("kill_flag", "execution_kill_switch.json")):
        payload, ok = _read_store(intelligence / filename)
        out[name] = payload
        if not ok:
            out["store_errors"].append(filename)
    ledger, ok = _read_store(intelligence / "execution_ledger.json")
    if not ok:
        out["store_errors"].append("execution_ledger.json")
    out["ledger_ok"] = ok and isinstance(ledger, dict)
    out["orders"] = [_lean(o) for o in ((ledger or {}).get("orders") or []) if isinstance(o, Mapping)]
    return out


def balance_evidence(orders: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """`venue_settlement`'s own read-only arithmetic, for the alert text. Never fatal."""
    try:
        from syndicate.features.shared.venue_settlement import balance_evidence_for_unknown_submits

        return balance_evidence_for_unknown_submits(orders)
    except Exception as exc:  # noqa: BLE001
        return {"_error": {"verdict": "unknown", "reason": f"{type(exc).__name__}: {exc}"[:120]}}


def scan_log(path: Path, cursor: Mapping[str, Any] | None) -> tuple[list[str], dict[str, Any]]:
    """New lines since `cursor` ({inode, offset}); follows one rotation to `<path>.1`. A first run starts at EOF."""
    lines: list[str] = []
    try:
        st = path.stat()
    except OSError:
        return lines, dict(cursor or {})
    cursor = dict(cursor or {})
    if not cursor:
        return lines, {"inode": st.st_ino, "offset": st.st_size}

    def _read(p: Path, start: int, budget: int) -> tuple[list[str], int]:
        with p.open("rb") as handle:
            handle.seek(start)
            blob = handle.read(budget)
        cut = blob.rfind(b"\n") + 1  # never split a line; the remainder is read next time
        return blob[:cut].decode("utf-8", "replace").splitlines(), start + cut

    budget = MAX_SCAN_BYTES
    offset = int(cursor.get("offset") or 0)
    if cursor.get("inode") != st.st_ino:
        rotated = path.with_name(path.name + ".1")
        try:
            if rotated.stat().st_ino == cursor.get("inode"):
                got, _ = _read(rotated, offset, budget)
                lines += got
                budget -= sum(len(x) + 1 for x in got)
        except OSError:
            pass
        offset = 0
    elif offset > st.st_size:  # truncated in place
        offset = 0
    if st.st_size - offset > budget:  # fell too far behind: skip ahead and say so
        lines.append(f"[execution_watchdog] LOG_SCAN_SKIPPED bytes={st.st_size - offset - budget}")
        offset = st.st_size - budget
    got, offset = _read(path, offset, max(budget, 0))
    return lines + got, {"inode": st.st_ino, "offset": offset}


def collect(settings: lp.Settings, now: dt.datetime, state: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """(readings, new execution-state). Never raises: a failure is a reading (`monitor_error`)."""
    exec_state = dict(state.get("execution") or {})
    pidfile = {}
    try:
        pidfile = json.loads((settings.run_dir / lp.PIDFILE_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    pid = (pidfile.get("roles") or {}).get(WORKER_ROLE)
    readings: dict[str, Any] = {"worker_pid": pid}
    try:
        readings.update(read_store_state(worker_state_env(settings, pid)))
    except Exception as exc:  # noqa: BLE001
        readings["monitor_error"] = f"{type(exc).__name__}: {exc}"[:200]
    unknown = unknown_submits(readings.get("orders") or [])
    readings["unknown_submits"] = unknown
    if unknown:
        readings["balance_evidence"] = balance_evidence(readings.get("orders") or [])
    lines, cursor = scan_log(settings.logs_dir / f"{WORKER_ROLE}.log", exec_state.get("log_cursor"))
    readings["log_lines"] = lines
    exec_state["log_cursor"] = cursor
    return readings, exec_state


# --------------------------------------------------------------------------
# evaluation (pure)
# --------------------------------------------------------------------------


def is_non_position(order: Mapping[str, Any]) -> bool:
    try:
        from syndicate.features.shared.execution_guard import is_non_position as guard

        return bool(guard(order))
    except Exception:  # noqa: BLE001 -- same rule, restated, if the import breaks
        status = str(order.get("status") or "")
        return status == "rejected" or (status == "failed" and bool(re.search(r"http_4\d\d", str(order.get("error") or ""), re.I)))


def unknown_submits(orders: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """`intelligence._is_unknown_submit`, over live rows: failed, no outcome, no venue id, no resolution, not a 4xx."""
    out = []
    for o in orders:
        if (str(o.get("mode") or "") == LIVE and str(o.get("status") or "") == "failed" and not o.get("outcome")
                and not str(o.get("venue_order_id") or "").strip() and not o.get("operator_resolution")
                and not is_non_position(o)):
            out.append(dict(o))
    return out


def stuck_unreconciled(orders: Iterable[Mapping[str, Any]], now: dt.datetime, minutes: float) -> list[dict[str, Any]]:
    """LIVE `submitted` rows with no venue confirmation for `minutes` (reconciled_at, else submitted_at)."""
    out = []
    for o in orders:
        if str(o.get("mode") or "") != LIVE or str(o.get("status") or "") != "submitted" or o.get("outcome"):
            continue
        age = _age_minutes(o.get("reconciled_at") or o.get("submitted_at"), now)
        if age is None or age >= minutes:
            out.append({**o, "_age_minutes": age})
    return out


def _order_label(o: Mapping[str, Any]) -> str:
    what = " ".join(str(o.get(k)) for k in ("sport", "market", "player", "side", "line") if o.get(k) not in (None, ""))
    return (f"{o.get('venue')} {o.get('venue_ticker') or ''} {what} stake {_money(o.get('requested_stake_dollars'))} "
            f"key {o.get('idempotency_key')}").replace("  ", " ")


def venue_money(balances: Mapping[str, Any] | None) -> dict[str, dict[str, Any]]:
    """Per venue {status, spendable, positions, pending_deposit}, straight from the venue_balances stamp.

    Read here rather than through `venue_capital`, whose Polymarket rule is changing (lane caps-revamp): the
    user decided 2026-10-19 that "the $500 pending on polymarket CAN be used", so spendable Polymarket money is
    `buyingPower` and the pending deposit is reported beside it, not subtracted. Kalshi spendable = cash
    (`dollars`, summed over shards); `portfolio_value_dollars` is open positions only.
    """
    rows = (balances or {}).get("venues") if isinstance((balances or {}).get("venues"), Mapping) else {}
    out: dict[str, dict[str, Any]] = {}
    for venue in ("kalshi", "polymarket"):
        row = rows.get(venue) if isinstance(rows.get(venue), Mapping) else {}
        status = str(row.get("status") or "absent")
        entry: dict[str, Any] = {"status": status, "detail": row.get("detail")}
        if status == "ok":
            if venue == "kalshi":
                entry["spendable"] = _num(row.get("dollars"))
                entry["positions"] = _num(row.get("portfolio_value_dollars"))
            else:
                entry["spendable"] = _num(row.get("buying_power_dollars"))
                if entry["spendable"] is None:
                    entry["spendable"] = _num(row.get("dollars"))
                numbers = (row.get("detail") or {}).get("numbers") if isinstance(row.get("detail"), Mapping) else None
                pending = [_num((numbers or {}).get(k)) for k in ("depositReservation", "displayedAvailableSoon")]
                pending = [p for p in pending if p is not None]
                entry["pending_deposit"] = max(pending) if pending else None
        out[venue] = entry
    return out


def configured_venues(exec_state: Mapping[str, Any] | None) -> list[str]:
    raw = str((exec_state or {}).get("venue") or "kalshi,polymarket")
    return [v for v in ("kalshi", "polymarket") if v in raw.lower()] or ["kalshi", "polymarket"]


def log_hits(lines: Iterable[str]) -> dict[str, list[str]]:
    hits: dict[str, list[str]] = {}
    for line in lines:
        for group, pattern in LOG_PATTERNS:
            if pattern.search(line):
                match = _VENUE_IN_LINE.search(line)
                key = group if group in ("kalshi", "polymarket") or not match else f"{group}:{match.group(1)}"
                hits.setdefault(key, []).append(line.strip()[:300])
                break
    return hits


def evaluate(readings: Mapping[str, Any], now: dt.datetime, limits: Mapping[str, float],
             exec_state: Mapping[str, Any]) -> tuple[list[Any], dict[str, Any]]:
    """(findings, execution-state updates). Findings use local_watchdog.Finding."""
    from scripts.local_watchdog import Finding

    findings: list[Finding] = []
    updates: dict[str, Any] = {}

    def add(key: str, severity: str, message: str) -> None:
        findings.append(Finding(EXEC_PREFIX + key, severity, message))

    if readings.get("monitor_error"):
        add("monitor", FAIL, f"execution monitor could not read the state store: {readings['monitor_error']} -- "
                             "every other execution check is blind until this clears")
    if readings.get("store_errors"):
        add("monitor", FAIL, f"state store read FAILED for {', '.join(readings['store_errors'])} (not absent: unreadable)")

    state = readings.get("execution_state")
    if not readings.get("monitor_error") and "execution_state.json" not in (readings.get("store_errors") or []):
        if not isinstance(state, Mapping):
            add("heartbeat", FAIL, "execution tick has NEVER stamped execution_state.json -- live-odds-worker is not "
                                   "running execution (disabled, crashed in the tick, or a fresh store)")
        else:
            age = _age_minutes(state.get("recorded_at"), now)
            if age is None or age > limits["heartbeat_max_minutes"]:
                shown = "unreadable" if age is None else f"{age:.0f} min"
                add("heartbeat", FAIL, f"execution tick heartbeat is {shown} old (limit {limits['heartbeat_max_minutes']:.0f}); "
                                       f"last stamp {fmt_ct(state.get('recorded_at'))} by {state.get('recorded_by')} -- no "
                                       "orders, settlement or balance reads are happening")
            switch = state.get("kill_switch") if isinstance(state.get("kill_switch"), Mapping) else {}
            if switch.get("engaged"):
                add("kill_switch", FAIL, f"KILL SWITCH ENGAGED (source={switch.get('source')}"
                                         f"{', ' + str(switch.get('detail')) if switch.get('detail') else ''}"
                                         f"{', set ' + fmt_ct(switch.get('set_at')) if switch.get('set_at') else ''}) -- "
                                         "no live order will be placed")
        flag = readings.get("kill_flag")
        if isinstance(flag, Mapping) and flag.get("engaged") and not any(f.key == EXEC_PREFIX + "kill_switch" for f in findings):
            add("kill_switch", FAIL, f"KILL SWITCH flag set ({flag.get('reason') or 'no reason'}, {fmt_ct(flag.get('set_at'))}); "
                                     "the worker has not stamped it yet")

    orders = readings.get("orders") or []
    if readings.get("ledger_ok"):
        stuck = stuck_unreconciled(orders, now, limits["unreconciled_minutes"])
        if stuck:
            rows = "; ".join(f"{_order_label(o)} ({'?' if o['_age_minutes'] is None else int(o['_age_minutes'])} min)"
                             for o in stuck[:5])
            add("unreconciled", FAIL, f"{len(stuck)} live order(s) unconfirmed by the venue for >= "
                                      f"{limits['unreconciled_minutes']:.0f} min -- this BLOCKS every live run "
                                      f"(BLOCKED_ON_UNRECONCILED): {rows}")
        unknown = readings.get("unknown_submits") or []
        if unknown:
            evidence = readings.get("balance_evidence") or {}
            rows = []
            for o in unknown[:5]:
                ev = evidence.get(str(o.get("idempotency_key") or "")) or {}
                rows.append(f"{_order_label(o)} error={str(o.get('error') or '')[:80]!r} balance-evidence="
                            f"{ev.get('verdict', 'n/a')}/{ev.get('reason') or '-'}")
            dollars = sum(_num(o.get("requested_stake_dollars")) or 0.0 for o in unknown)
            add("unknown_submits", FAIL, f"{len(unknown)} live submit(s) with NO venue answer (${dollars:,.2f}) -- each may "
                                         "or may not be a position. A Kalshi one is resolved automatically once Kalshi lists it "
                                         "under our key (execution_self_heal); anything else waits for /portfolio/live: " + "; ".join(rows))

    balances = readings.get("venue_balances")
    if not readings.get("monitor_error") and isinstance(state, Mapping):
        venues = configured_venues(state)
        if not isinstance(balances, Mapping) or not balances.get("recorded_at"):
            add("balance_stale", FAIL, "venue balances have never been stamped (venue_balances.json absent)")
        else:
            age = _age_minutes(balances.get("recorded_at"), now)
            if age is None or age > limits["balance_stale_minutes"]:
                add("balance_stale", FAIL, f"venue balance stamp is {'?' if age is None else f'{age:.0f} min'} old "
                                           f"(limit {limits['balance_stale_minutes']:.0f}; compounding sizing treats > 60 min "
                                           f"as unknown capital); last {fmt_ct(balances.get('recorded_at'))}")
            money = venue_money(balances)
            for venue in venues:
                status = money[venue]["status"]
                if status != "ok":
                    add(f"balance_status:{venue}", FAIL, f"{venue} balance read is `{status}` -- "
                                                         f"{str(money[venue].get('detail') or '')[:120]}")
                    continue
                cash = money[venue].get("spendable")
                floor = limits[f"min_balance_{venue}"]
                if cash is not None and cash < floor:
                    add(f"balance_low:{venue}", FAIL, f"{venue} spendable balance {_money(cash)} is below the "
                                                      f"{_money(floor)} alert threshold")
            pm = money["polymarket"]
            pending = pm.get("pending_deposit")
            if "polymarket" in venues and pm["status"] == "ok" and pending and pending > 0:
                add("pending_deposit", WARN, f"Polymarket has a PENDING DEPOSIT of {_money(pending)} (inside buyingPower "
                                             f"{_money(pm.get('spendable'))}; counted as usable per the 2026-10-19 decision) "
                                             "-- if it bounces, buyingPower falls by that much")

    # LOG BURSTS, held LOG_HOLD_MINUTES after the last burst so one incident is one alert, not NEW/CLEARED every 5 min.
    holds = dict(exec_state.get("log_holds") or {})
    for group, lines in log_hits(readings.get("log_lines") or []).items():
        if len(lines) >= limits["log_errors_per_check"]:
            holds[group] = {"at": now.isoformat(), "count": len(lines), "sample": lines[-SAMPLE_LINES:]}
    for group, held in list(holds.items()):
        at = _parse_time(held.get("at"))
        if at is None or (now - at).total_seconds() > LOG_HOLD_MINUTES * 60:
            holds.pop(group)
            continue
        add(f"log_errors:{group}", FAIL, f"{held['count']} failure lines from {group} in one 5-min check "
                                         f"(last burst {fmt_ct(at)}): " + " || ".join(held.get("sample") or []))
    updates["log_holds"] = holds
    return findings, updates


# --------------------------------------------------------------------------
# daily digest
# --------------------------------------------------------------------------


def accumulate(lines: Iterable[str], acc: dict[str, Any], now: dt.datetime) -> dict[str, Any]:
    """Fold EXECUTION and failure lines into per-Central-day counters. Refusals are counted per TICK: the same
    position is refused again every tick, so a sum would count one bet dozens of times."""
    acc = {k: v for k, v in (acc or {}).items()
           if k >= (central(now).date() - dt.timedelta(days=DIGEST_DAYS_KEPT)).isoformat()}
    for line in lines:
        stamp = _parse_time(line[:24].rstrip()) if line[:4].isdigit() else None
        day = central(stamp or now).date().isoformat()
        bucket = acc.setdefault(day, {"ticks": {}, "refusals": {}, "errors": {}})
        m = _EXECUTION_LINE.search(line)
        if m:
            status, _reason, mode, venue, refused = m.groups()
            tick = bucket["ticks"].setdefault(f"{mode}:{venue}", {})
            tick[status] = int(tick.get(status) or 0) + 1
            try:
                parsed = ast.literal_eval(refused)
            except (ValueError, SyntaxError):
                parsed = {}
            for reason, count in (parsed or {}).items():
                row = bucket["refusals"].setdefault(f"{venue}:{reason}", {"ticks": 0, "max": 0})
                row["ticks"] += 1
                row["max"] = max(row["max"], int(count or 0))
            continue
        healed = _SELF_HEALED.search(line)
        if healed:
            bucket.setdefault("self_healed", {})
            bucket["self_healed"][healed.group(1)] = int(bucket["self_healed"].get(healed.group(1)) or 0) + 1
            continue
        for group, pattern in LOG_PATTERNS:
            if pattern.search(line):
                bucket["errors"][group] = int(bucket["errors"].get(group) or 0) + 1
                break
    return acc


def _window(day: dt.date) -> tuple[dt.datetime, dt.datetime]:
    start = dt.datetime.combine(day, dt.time(0, 0), tzinfo=CENTRAL)
    return start.astimezone(dt.timezone.utc), (start + dt.timedelta(days=1)).astimezone(dt.timezone.utc)


def _in(value: Any, lo: dt.datetime, hi: dt.datetime) -> bool:
    parsed = _parse_time(value)
    return parsed is not None and lo <= parsed < hi


def build_digest(day: dt.date, orders: list[Mapping[str, Any]], readings: Mapping[str, Any], acc_day: Mapping[str, Any],
                 active: Mapping[str, Any], now: dt.datetime, previous_balances: Mapping[str, Any] | None) -> tuple[str, str, dict]:
    """(subject, body, balances snapshot) for Central day `day`."""
    lo, hi = _window(day)
    lines: list[str] = []
    state = readings.get("execution_state") if isinstance(readings.get("execution_state"), Mapping) else {}
    switch = (state or {}).get("kill_switch") or {}
    lines.append(f"Syndicate daily digest for {day.strftime('%a %b %d')} (Central), sent {fmt_ct(now)}")
    lines.append("")
    lines.append(f"NOW: mode={state.get('execution_mode')} armed={state.get('live_armed')} enabled={state.get('execution_enabled')} "
                 f"kill_switch={'ENGAGED (' + str(switch.get('source')) + ')' if switch.get('engaged') else 'clear'} "
                 f"heartbeat={fmt_ct(state.get('recorded_at'))}")

    snapshot: dict[str, Any] = {}
    money = venue_money(readings.get("venue_balances"))
    lines.append("")
    lines.append(f"BALANCES (stamp {fmt_ct((readings.get('venue_balances') or {}).get('recorded_at'))})")
    for venue, cap in money.items():
        cash = cap.get("spendable")
        snapshot[venue] = cash
        before = _num((previous_balances or {}).get(venue))
        delta = f" ({'+' if cash - before >= 0 else '-'}{_money(abs(cash - before))} since last digest)" \
            if cash is not None and before is not None else ""
        extra = ""
        if venue == "kalshi" and cap.get("positions") is not None:
            extra = f", open positions {_money(cap.get('positions'))}"
        if venue == "polymarket" and (cap.get("pending_deposit") or 0) > 0:
            extra = f", of which pending deposit {_money(cap.get('pending_deposit'))}"
        lines.append(f"  {venue}: spendable {_money(cash)}{extra}{delta}" if cap["status"] == "ok"
                     else f"  {venue}: unreadable ({cap['status']})")

    def section(title: str, rows: list[Mapping[str, Any]]) -> None:
        placed = [o for o in rows if _in(o.get("submitted_at"), lo, hi)]
        settled = [o for o in rows if _in(o.get("graded_at"), lo, hi) and o.get("outcome")]
        lines.append("")
        lines.append(title)
        if not placed and not settled:
            lines.append("  no orders placed or settled")
            return
        for venue in sorted({str(o.get("venue") or "?") for o in placed + settled}):
            vp = [o for o in placed if str(o.get("venue") or "?") == venue]
            vs = [o for o in settled if str(o.get("venue") or "?") == venue]
            by_status: dict[str, int] = {}
            for o in vp:
                by_status[str(o.get("status"))] = by_status.get(str(o.get("status")), 0) + 1
            filled = [o for o in vp if str(o.get("status")) == "filled"]
            staked = sum(_num(o.get("fill_stake_dollars")) or _num(o.get("requested_stake_dollars")) or 0.0 for o in filled)
            fees = sum(_num(o.get("fees_dollars")) or 0.0 for o in filled)
            w = sum(1 for o in vs if o.get("outcome") == "won")
            lo_ = sum(1 for o in vs if o.get("outcome") == "lost")
            p = sum(1 for o in vs if o.get("outcome") == "push")
            pnl = sum(_num(o.get("pnl_dollars")) or 0.0 for o in vs)
            settled_stake = sum(_num(o.get("fill_stake_dollars")) or _num(o.get("requested_stake_dollars")) or 0.0 for o in vs)
            roi = f", ROI {pnl / settled_stake * 100:+.1f}%" if settled_stake else ""
            lines.append(f"  {venue}: orders {len(vp)} {dict(sorted(by_status.items()))}, fills {len(filled)} "
                         f"staked {_money(staked)} fees {_money(fees)}")
            lines.append(f"  {venue}: settled {len(vs)} (W{w}-L{lo_}-P{p}) P&L {'+' if pnl >= 0 else '-'}{_money(abs(pnl))}{roi}")

    live = [o for o in orders if str(o.get("mode") or "") == LIVE]
    paper = [o for o in orders if str(o.get("mode") or "").startswith("paper")]
    section("LIVE", live)
    section("PAPER", paper)

    lines.append("")
    lines.append("EXECUTION TICKS + REFUSALS (refusals counted per tick; the same bet is refused again each tick)")
    ticks = (acc_day or {}).get("ticks") or {}
    if not ticks:
        lines.append("  no EXECUTION lines were scanned for this day (the digest started mid-day, or the worker was down)")
    for name, counts in sorted(ticks.items()):
        lines.append(f"  {name}: {dict(sorted(counts.items()))}")
    for name, row in sorted(((acc_day or {}).get("refusals") or {}).items(), key=lambda kv: -kv[1]["ticks"]):
        lines.append(f"  refused {name}: {row['ticks']} ticks, up to {row['max']} per tick")
    errors = (acc_day or {}).get("errors") or {}
    if errors:
        lines.append(f"  failure lines: {dict(sorted(errors.items()))}")
    if (acc_day or {}).get("self_healed"):
        lines.append(f"  unknown submits auto-resolved from Kalshi's order list: {acc_day['self_healed']}")

    unknown = readings.get("unknown_submits") or []
    stuck = [o for o in live if str(o.get("status")) == "submitted" and not o.get("outcome")]
    lines.append("")
    lines.append(f"OPEN QUESTIONS: unknown submits {len(unknown)}, live orders awaiting the venue {len(stuck)}")
    lines.append("")
    lines.append("ACTIVE WATCHDOG FINDINGS" if active else "ACTIVE WATCHDOG FINDINGS: none")
    for key, held in sorted((active or {}).items()):
        lines.append(f"  [{held.get('severity')}] {key} since {fmt_ct(held.get('since'))}: {held.get('message')}")
    live_pnl = sum(_num(o.get("pnl_dollars")) or 0.0 for o in live if _in(o.get("graded_at"), lo, hi))
    subject = f"daily digest {day.strftime('%m-%d')}: live P&L {'+' if live_pnl >= 0 else '-'}{_money(abs(live_pnl))}"
    return subject, "\n".join(lines), snapshot


def digest_due(now: dt.datetime, exec_state: Mapping[str, Any], hour_ct: float) -> dt.date | None:
    """The Central day to digest, or None. Once a day, at/after `hour_ct` Central, for YESTERDAY."""
    local = central(now)
    if local.hour + local.minute / 60.0 < hour_ct:
        return None
    day = local.date() - dt.timedelta(days=1)
    return None if exec_state.get("last_digest_day") == day.isoformat() else day


def digest_orders(readings: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """Archive + live rows (the ledger trims to 3,000 and archives the rest); the live rows if that fails."""
    try:
        from syndicate.features.shared.execution_ledger import full_history_orders

        return [_lean(o) for o in full_history_orders() if isinstance(o, Mapping)]
    except Exception:  # noqa: BLE001
        return list(readings.get("orders") or [])


# --------------------------------------------------------------------------
# what gets emailed
# --------------------------------------------------------------------------


def emailable(key: str, severity: str) -> bool:
    """Every execution finding, and every fleet FAIL (role down, crash loop, heartbeat, healthz, supervisor).
    Fleet WARNs (a nightly job's rc, backup age, disk) stay toast + digest: they are not money."""
    return key.startswith(EXEC_PREFIX) or severity == FAIL


# The subject line names the most urgent finding: money stopped > money at risk > money mis-read > noise.
_PRIORITY = ("exec:kill_switch", "role:live-odds-worker", "crashloop:live-odds-worker", "exec:heartbeat",
             "supervisor", "exec:unknown_submits", "exec:unreconciled", "exec:monitor", "exec:log_errors",
             "exec:balance_status", "exec:balance_stale", "exec:balance_low", "heartbeat:live-odds-worker")


def _priority(key: str) -> int:
    for i, prefix in enumerate(_PRIORITY):
        if key.startswith(prefix):
            return i
    return len(_PRIORITY)


def email_messages(findings: list[Any], previous_active: Mapping[str, Any], new_active: Mapping[str, Any],
                   result: Mapping[str, Any], now: dt.datetime) -> list[dict[str, str]]:
    """One alert email for this check's NEW / STILL / CLEARED emailable findings (decide() already deduped)."""
    current = {f.key: f for f in findings}
    new_keys = {f["key"] for f in result.get("new") or []}
    repeat_keys = {f["key"] for f in result.get("repeat") or []}
    cleared = {k: v for k, v in (previous_active or {}).items() if k not in current}
    rows = []
    for key in sorted(new_keys):
        f = current[key]
        if emailable(key, f.severity):
            rows.append(("NEW", f.severity, key, f.message))
    for key in sorted(repeat_keys):
        f = current[key]
        if emailable(key, f.severity):
            rows.append(("STILL", f.severity, key, f.message))
    for key, held in sorted(cleared.items()):
        if emailable(key, str(held.get("severity"))):
            rows.append(("CLEARED", str(held.get("severity")), key, str(held.get("message"))))
    if not rows:
        return []
    rows.sort(key=lambda r: (r[0] == "CLEARED", _priority(r[2]), r[2]))
    fails = sum(1 for r in rows if r[0] != "CLEARED" and r[1] == FAIL)
    head = rows[0]
    if fails:
        subject = f"ALERT {head[2]}" + (f" (+{len(rows) - 1} more)" if len(rows) > 1 else "")
    elif all(r[0] == "CLEARED" for r in rows):
        subject = f"cleared: {', '.join(r[2] for r in rows[:3])}"
    else:
        subject = f"warning {head[2]}" + (f" (+{len(rows) - 1} more)" if len(rows) > 1 else "")
    body = [f"Checked {fmt_ct(now)}. Fleet status: {result.get('status')}.", ""]
    for kind, severity, key, message in rows:
        body.append(f"{kind} [{severity}] {key}\n  {message}\n")
    still_open = [k for k in new_active if emailable(k, str((new_active.get(k) or {}).get("severity")))]
    body.append(f"Open emailable findings after this check: {', '.join(sorted(still_open)) or 'none'}")
    body.append("Repeats: a failing finding re-alerts every 6 h while it persists; you get one CLEARED when it ends.")
    return [{"kind": "alert", "subject": subject, "body": "\n".join(body)}]


# --------------------------------------------------------------------------
# entry points
# --------------------------------------------------------------------------


def run(settings: lp.Settings, now: dt.datetime, state: Mapping[str, Any]) -> tuple[list[Any], dict[str, Any], dict[str, Any]]:
    """(findings, new execution-state, readings). Called by local_watchdog.main; never raises."""
    from scripts.local_watchdog import Finding

    try:
        limits = thresholds(settings.home)
        readings, exec_state = collect(settings, now, state)
        findings, updates = evaluate(readings, now, limits, exec_state)
        exec_state.update(updates)
        exec_state["digest_acc"] = accumulate(readings.get("log_lines") or [], exec_state.get("digest_acc") or {}, now)
        readings.pop("log_lines", None)
        exec_state["limits"] = limits
        return findings, exec_state, readings
    except Exception as exc:  # noqa: BLE001 -- the fleet checks must still run
        return ([Finding(EXEC_PREFIX + "monitor", FAIL, f"execution monitor crashed: {type(exc).__name__}: {exc}"[:300])],
                dict(state.get("execution") or {}), {})


def digest_message(settings: lp.Settings, now: dt.datetime, exec_state: dict[str, Any], readings: Mapping[str, Any],
                   active: Mapping[str, Any], *, force_day: dt.date | None = None) -> dict[str, str] | None:
    """The digest email if one is due (marks it sent in `exec_state`), else None."""
    limits = exec_state.get("limits") or thresholds(settings.home)
    day = force_day or digest_due(now, exec_state, float(limits.get("digest_hour_ct", DEFAULTS["digest_hour_ct"])))
    if day is None:
        return None
    subject, body, snapshot = build_digest(day, digest_orders(readings), readings,
                                           (exec_state.get("digest_acc") or {}).get(day.isoformat()) or {},
                                           active, now, exec_state.get("digest_balances"))
    if force_day is None:
        exec_state["last_digest_day"] = day.isoformat()
        exec_state["digest_balances"] = snapshot
    return {"kind": "digest", "subject": subject, "body": body}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--home", help="local production home (default: as local_production.py)")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--digest-now", action="store_true", help="print yesterday's digest (nothing sent or saved)")
    args = parser.parse_args(argv)
    home = Path(args.home).expanduser().resolve() if args.home else lp.default_home()
    settings = lp.Settings(home=home)
    now = dt.datetime.now(dt.timezone.utc)
    try:
        state = json.loads((settings.run_dir / "watchdog_state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {}
    # A dry look: start the log scan 2 MB back so a hand run sees recent lines, and save nothing.
    probe_state = dict(state)
    probe_exec = dict(state.get("execution") or {})
    log_path = settings.logs_dir / f"{WORKER_ROLE}.log"
    if log_path.is_file():
        st = log_path.stat()
        probe_exec["log_cursor"] = {"inode": st.st_ino, "offset": max(0, st.st_size - 2 * 1024 * 1024)}
    probe_state["execution"] = probe_exec
    findings, exec_state, readings = run(settings, now, probe_state)
    if args.digest_now:
        message = digest_message(settings, now, exec_state, readings, state.get("active") or {},
                                 force_day=central(now).date() - dt.timedelta(days=1))
        print(message["subject"] if message else "no digest")
        print(message["body"] if message else "")
        return 0
    if args.json:
        print(json.dumps({"findings": [f.__dict__ for f in findings], "unknown_submits": len(readings.get("unknown_submits") or []),
                          "orders": len(readings.get("orders") or [])}, default=str))
    else:
        print(f"{len(findings)} execution finding(s); ledger rows read: {len(readings.get('orders') or [])}")
        for f in findings:
            print(f"  [{f.severity}] {f.key}: {f.message}")
    return 0 if not findings else 1


if __name__ == "__main__":
    raise SystemExit(main())
