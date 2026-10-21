"""A basketball SmartSim is frozen at tip (lane freeze-nba-pregame-sims, 2026-10-21).

WHY. ``basketball_props_smart_sim._smart_sim_run_date_local`` runs on every full props refresh, including refreshes
after a game has started, and nothing in it read the tip time. Any reuse check that went stale (the exclusion drift
check in ``smart_sim_reuse``, the roster pool check, the NBA calibration stamp) or the WNBA targeted trigger
re-simulated a game in progress. That rewrote the pregame ``smart_sim_<D>_<H>_<A>.json`` and
``engine_inputs/<D>/<H>_<A>.pkl``. The NBA live re-sim (``syndicate/features/nba/live_resim.py``) reloads that pkl
on every tick, so its inputs changed mid-game.

Measured on the fleet's props logs for 10-03..10-21 (``scripts/basketball_posttip_rebuilds.py``):
- NBA: 10 of 145 builds ran after the scheduled tip, on 7 of 74 games. 6 of them came after engine-input persistence
  began (10-10), and they included all three 10-20 games. Triggers: 8 exclusion drift, 2 calibration stamp.
- The changes after tip were churn. The 11:07 PM CT rebuild on 10-20 reversed every player change the 6:54 PM CT
  rebuild had made.
- WNBA: 1 of 60.
User decision 2026-10-21: freeze at tip, on by default.

THE RULE. In the per-game loop, before the force-unlink and the reuse checks, an existing sim with players is KEPT
when its rebuild would finish at or after the game's tip. "Would finish" means now + (jobs already queued ahead of it
+ 1) x ``PER_JOB_SECONDS``. Jobs run in queue order after the loop, and the queue is in home-team alphabetical
order, not in tip order. On 10-21 the earliest tip (WAS) was queued last of 11.

NOT frozen:
- ``overwrite=True``. Research and backfill tools use it, and it deletes the whole date before the loop, by design.
- A missing or player-less sim. There is nothing to protect, so it is built and logged ``built_after_tip=1``.
- A game whose tip is unknown. It is rebuilt as before and logged ``tip=unknown``.

Tip sources, first hit wins: the predictions row's ``commence_time``; the ``game_odds_<D>.csv`` row for the same
teams; the ``schedule_*.csv`` row (``date_est`` + tricodes -> ``datetime_utc``). The predictions column is empty for
any game whose UTC date is the next day (measured 10-21: 6 of 11), which is why the other two sources exist.

Switch ``SYNDICATE_SMART_SIM_TIP_FREEZE``:
- absent or ``on``: freeze.
- ``shadow``: log ``would_freeze=1`` and rebuild as before.
- ``off`` / ``0`` / ``false`` / ``no``: no check and no line.
"""

from __future__ import annotations

import csv
import math
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

SWITCH_ENV = "SYNDICATE_SMART_SIM_TIP_FREEZE"

# One sim job, decision to written file. Measured on the fleet's NBA props logs (n_sims=100, 24 batches): median 47 s,
# p90 70 s. The 500-draw runs: median 51 s.
PER_JOB_SECONDS = 90.0


def mode() -> str:
    raw = str(os.environ.get(SWITCH_ENV, "") or "").strip().lower()
    if raw in {"0", "off", "false", "no"}:
        return "off"
    if raw == "shadow":
        return "shadow"
    return "on"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def parse_tip(value: Any) -> datetime | None:
    """A UTC datetime from an ISO string (``Z`` or offset), else None (NaN, blank, unparseable)."""
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    text = str(value).strip()
    if not text or text.lower() in {"nan", "nat", "none"}:
        return None
    try:
        when = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when.astimezone(timezone.utc)


def schedule_tips(processed_root: Path, date_str: str) -> dict[tuple[str, str], datetime]:
    """(home, away) -> tip for the games whose ``date_est`` is ``date_str``, from every ``schedule_*.csv``."""
    out: dict[tuple[str, str], datetime] = {}
    day = str(date_str)[:10]
    for path in sorted(Path(processed_root).glob("schedule_*.csv")):
        try:
            with path.open(newline="", encoding="utf-8") as handle:
                for row in csv.DictReader(handle):
                    if str(row.get("date_est") or "")[:10] != day:
                        continue
                    when = parse_tip(row.get("datetime_utc"))
                    home = str(row.get("home_tricode") or "").strip().upper()
                    away = str(row.get("away_tricode") or "").strip().upper()
                    if when is not None and home and away:
                        out.setdefault((home, away), when)
        except Exception:
            continue
    return out


def tip_time(row: Mapping[str, Any] | Any, *, odds_df: Any, schedule: Mapping[tuple[str, str], datetime],
             home: str, away: str) -> datetime | None:
    """The game's tip: predictions row, then the ``game_odds`` row for the same teams, then the schedule."""
    try:
        when = parse_tip(row.get("commence_time"))
    except Exception:
        when = None
    if when is not None:
        return when
    try:
        if odds_df is not None and not odds_df.empty and "commence_time" in odds_df.columns:
            match = odds_df[(odds_df["home_tri"] == home) & (odds_df["away_tri"] == away)]
            for value in match["commence_time"].tolist():
                when = parse_tip(value)
                if when is not None:
                    return when
    except Exception:
        pass
    return schedule.get((str(home).upper(), str(away).upper()))


def keep_existing(out_path: Path, *, has_players: bool, tip: datetime | None, queued: int, date_str: str,
                  league: str, now: Callable[[], datetime] | None = None) -> bool:
    """True = the existing sim is kept and this game is not rebuilt. One line for every freeze, would-freeze,
    after-tip first build and unknown tip; nothing for a pre-tip game. Never raises (a failure keeps today's
    behaviour, the rebuild, and says so)."""
    current = mode()
    if current == "off":
        return False
    name = Path(out_path).name
    prefix = f"[smart_sim_tip_freeze] SMART_SIM_TIP_FREEZE league={league} date={date_str} file={name} mode={current}"
    try:
        if tip is None:
            print(f"{prefix} tip=unknown frozen=0", flush=True)
            return False
        at = (now or _now)()
        finish = at + timedelta(seconds=PER_JOB_SECONDS * (int(queued) + 1))
        if finish < tip:
            return False
        detail = (f"tip={tip.strftime('%Y-%m-%dT%H:%M:%SZ')} now={at.strftime('%Y-%m-%dT%H:%M:%SZ')} "
                  f"finish_by={finish.strftime('%Y-%m-%dT%H:%M:%SZ')} queued={int(queued)}")
        if not has_players:
            print(f"{prefix} {detail} frozen=0 built_after_tip=1 reason=no_existing_sim", flush=True)
            return False
        if current == "shadow":
            print(f"{prefix} {detail} would_freeze=1 frozen=0 reuse=False", flush=True)
            return False
        print(f"{prefix} {detail} frozen=1 reuse=True", flush=True)
        return True
    except Exception as exc:  # noqa: BLE001 -- the freeze must never take the sim down
        print(f"{prefix} CHECK_FAILED {type(exc).__name__}: {str(exc)[:160]} frozen=0", flush=True)
        return False
