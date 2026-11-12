"""The fleet watchdog's college team-name check (called from `scripts/local_watchdog.py` main()).

WHY. User 2026-11-12, after CSU Bakersfield's two games drew chip-less cards on the Games rail: "run the audit before
each slate automatically". The same report had been fixed by hand on 11-03, 11-07 and 11-12, each time after the user
spotted the card. An odds-feed team name that does not resolve to an ESPN school (`team_aliases.chip_join_key` -> None)
leaves that game's board rows without team keys. So the rail card has no chip, the slate's odds join misses the game,
and its live re-sim refuses `no_margin_anchor` at tip. The odds feed lists a college game days before it tips, so
catching the name when it first appears in the quote log is "before the slate".

WHAT IS CHECKED (keys carry the `exec:` prefix, so they are EMAILED as well as toasted -- the same choice as
`min_ev_tuner_watch`'s decision cue):
  exec:team_names:<league>   an ncaab / wncaab odds-feed team name in a quote shard dated yesterday (UTC) or later
                             that does not resolve; the message names it, its events and dates, and ESPN's spelling
                             where the opponent pins the game                                                   warn
  exec:team_names:watch_error  the check itself crashed                                                          warn

CADENCE. The watchdog runs every 5 min; the audit (`scripts/college_team_name_audit.py`) runs at most once per
AUDIT_EVERY_SECONDS, and the findings in between come from the cached result in the watchdog state. So an unresolved
name does not flap between checks. Measured on the fleet 2026-11-12: 0.45 s over the 11-12 + 11-13 shards (20 MB).

NO SHARD IS NO FINDING. In the offseason a league has no quote shard from yesterday on, and that is not a fault this
check can name. The row records `shards_read` per league, so the absence stays readable. Odds capture stopping
mid-season is a capture fault, and other checks own it.

Off switch: SYNDICATE_WATCHDOG_TEAM_NAMES=0. The fix for a finding is a derivation rule or an `_ODDS_FEED_ALIASES`
entry in `syndicate/features/shared/ncaab_team_registry.py`, with the ESPN spelling as its evidence.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any, Callable, Mapping

FAIL, WARN = "fail", "warn"
PREFIX = "exec:team_names:"
STATE_KEY = "team_names"
AUDIT_EVERY_SECONDS = 3600
MAX_NAMES_IN_MESSAGE = 5


def _parse(value: Any) -> dt.datetime | None:
    try:
        parsed = dt.datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)


def audit_due(row: Mapping[str, Any], now: dt.datetime) -> bool:
    last = _parse(row.get("audited_at"))
    return last is None or (now - last).total_seconds() >= AUDIT_EVERY_SECONDS


def run_audit(data_root: Path, now: dt.datetime, audit: Callable[..., dict[str, Any]] | None = None) -> dict[str, Any]:
    """The audit over shards dated yesterday (UTC) or later, summarised into the watchdog state row."""
    if audit is None:
        from scripts.college_team_name_audit import audit
    since = (now.date() - dt.timedelta(days=1)).isoformat()
    report = audit(Path(data_root), since=since)
    leagues = {}
    for league, v in (report.get("leagues") or {}).items():
        leagues[league] = {
            "shards_read": int(v.get("shards_read") or 0),
            "events": int(v.get("events") or 0),
            "events_with_an_unresolved_team": int(v.get("events_with_an_unresolved_team") or 0),
            "unresolved": dict(v.get("unresolved") or {}),
        }
    return {"audited_at": now.isoformat(), "since": since, "leagues": leagues}


def _describe(name: str, info: Mapping[str, Any]) -> str:
    dates = list(info.get("dates") or [])
    span = (dates[0] if len(dates) == 1 else f"{dates[0]}..{dates[-1]}") if dates else "?"
    espn = info.get("espn_spelling") or {}
    best = max(espn.items(), key=lambda kv: kv[1])[0] if espn else None
    tail = f"; ESPN calls it {best!r}" if best else "; ESPN spelling unknown (its opponent does not resolve either)"
    return f"{name!r} ({info.get('events', 0)} event(s), {span}{tail})"


def evaluate(row: Mapping[str, Any]) -> list[tuple[str, str, str]]:
    findings = []
    if row.get("error"):
        # Kept on the row until the next audit, so the finding holds between checks instead of flapping.
        findings.append((PREFIX + "watch_error", WARN, f"college team-name check crashed: {row['error']}"[:300]))
    for league, v in sorted((row.get("leagues") or {}).items()):
        unresolved = v.get("unresolved") or {}
        if not unresolved:
            continue
        names = sorted(unresolved.items(), key=lambda kv: (-int(kv[1].get("events") or 0), kv[0]))
        shown = "; ".join(_describe(name, info) for name, info in names[:MAX_NAMES_IN_MESSAGE])
        more = f"; +{len(names) - MAX_NAMES_IN_MESSAGE} more" if len(names) > MAX_NAMES_IN_MESSAGE else ""
        findings.append((
            PREFIX + league, WARN,
            f"{league.upper()} odds-feed team name(s) that match no ESPN school: their games lose their rail chip, odds "
            f"join and live re-sim anchor. {shown}{more}. {v.get('events_with_an_unresolved_team', 0)} of "
            f"{v.get('events', 0)} events since {row.get('since')}. Fix: a rule or alias in "
            f"syndicate/features/shared/ncaab_team_registry.py (scripts/college_team_name_audit.py has the details).",
        ))
    return findings


def run(data_root: Path, state: Mapping[str, Any], now: dt.datetime,
        audit: Callable[..., dict[str, Any]] | None = None) -> tuple[list[tuple[str, str, str]], dict[str, Any]]:
    """(findings, new row for state["team_names"]). Never raises.

    A crashed audit keeps the previous result's names (still true until an audit says otherwise) and records the
    error, so both are reported until the next hourly audit."""
    row = dict(state.get(STATE_KEY) or {})
    if audit_due(row, now):
        try:
            row = run_audit(data_root, now, audit)
        except Exception as exc:  # noqa: BLE001 -- a broken check must not stop the fleet checks
            row = {**row, "audited_at": now.isoformat(), "error": f"{type(exc).__name__}: {exc}"[:240]}
    try:
        return evaluate(row), row
    except Exception as exc:  # noqa: BLE001
        return [(PREFIX + "watch_error", WARN, f"college team-name check crashed: {type(exc).__name__}: {exc}"[:300])], row
