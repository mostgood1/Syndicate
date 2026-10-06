"""Is an existing SmartSim file still valid for TODAY's exclusions? (lane smart-sim-reuse-stale-exclusions)

WHY. ``basketball_props_smart_sim._smart_sim_run_date_local`` reuses any existing sim file that has players (plus,
for NBA, a matching calibration stamp). The only thing that rebuilt a sim after an injury change was the
live-odds-worker scoped trigger, and it misses four ways (measured 2026-10-06, lane wnba-props-out-player-leak):
(a) it watches today only, so a D+1 sim is never re-checked; (b) on a new date the stored fingerprint is another
day's, so the first look becomes the baseline and a change since the build is never seen; (c) it hashes
injuries.csv + league_status only, not injuries_excluded_<D>.csv or the recency exclusions the sim reads; (d) it
saves the new fingerprint before the launch gates (mutex, cooldown, off-hours, lane_busy), so a refused launch
consumes the change. Each path leaves a sim simulating a player who is now OUT, or dropping one who is back.

THE CHECK. Every sim stamps the exclusion set it was built with in ``context.excluded_players`` (the vendored
``simulate_smart_game`` writes ``{team: sorted(keys)}`` from the ``excluded_player_keys_by_team`` it was given,
omitting teams with no keys). The reuse branch rebuilds that set exactly as the worker would pass it -- same map,
same ``_excluded_keys_for_source_filter``, same sim module -- and a per-team difference means the file is stale.
Measured on the fleet 2026-10-06 for both 10-07 WNBA sims: stamp == current set on all four teams, so an unchanged
feed does not churn rebuilds.

Kill switch: ``SYNDICATE_SMART_SIM_REUSE_EXCLUSION_CHECK=0`` (absent = ON).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Iterable

_SWITCH_ENV = "SYNDICATE_SMART_SIM_REUSE_EXCLUSION_CHECK"


def check_enabled() -> bool:
    raw = str(os.environ.get(_SWITCH_ENV, "") or "").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _key_set(values: Iterable[Any] | None) -> set[str]:
    return {str(value or "").strip().upper() for value in (values or ()) if str(value or "").strip()}


def stamped_exclusions(path: Path) -> dict[str, set[str]] | None:
    """``context.excluded_players`` of a sim file as ``{TEAM: {KEYS}}``; ``{}`` when the stamp is absent (the
    vendored writer omits it when nothing was excluded); ``None`` when the file cannot be read."""
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    context = payload.get("context") if isinstance(payload.get("context"), dict) else {}
    stamp = context.get("excluded_players")
    if not isinstance(stamp, dict):
        return {}
    return {str(team).strip().upper(): _key_set(keys) for team, keys in stamp.items()}


def exclusion_drift(stamped: dict[str, set[str]], expected: dict[str, Iterable[Any]], teams: Iterable[str]) -> dict[str, dict[str, list[str]]]:
    """Per team, the keys the current run would exclude that the file did not (``added``) and the reverse
    (``removed``). Empty dict = the file was built with today's exclusions."""
    drift: dict[str, dict[str, list[str]]] = {}
    for team in teams:
        team_key = str(team or "").strip().upper()
        now = _key_set(expected.get(team) if team in expected else expected.get(team_key))
        then = stamped.get(team_key, set())
        if now != then:
            drift[team_key] = {"added": sorted(now - then), "removed": sorted(then - now)}
    return drift


def reuse_verdict(path: Path, *, expected: dict[str, Iterable[Any]], teams: Iterable[str], date_str: str, league: str) -> bool:
    """True = the file's exclusions match the current run's (reuse it). Prints one line per decision.

    An unreadable file is not a match (the caller's own has-players check already rejects it). Never raises: a
    failure in the comparison keeps the pre-existing behaviour (reuse) and says so.
    """
    teams = [str(team or "").strip().upper() for team in teams]
    name = Path(path).name
    if not check_enabled():
        print(f"[smart_sim_reuse] SMART_SIM_REUSE_EXCLUSIONS league={league} date={date_str} file={name} check=off reuse=True", flush=True)
        return True
    try:
        stamped = stamped_exclusions(path)
        if stamped is None:
            print(f"[smart_sim_reuse] SMART_SIM_REUSE_EXCLUSIONS league={league} date={date_str} file={name} stale=1 reason=unreadable", flush=True)
            return False
        drift = exclusion_drift(stamped, expected, teams)
    except Exception as exc:
        print(f"[smart_sim_reuse] SMART_SIM_REUSE_EXCLUSION_CHECK_FAILED league={league} date={date_str} file={name} {type(exc).__name__}: {exc} reuse=True", flush=True)
        return True
    if not drift:
        print(f"[smart_sim_reuse] SMART_SIM_REUSE_EXCLUSIONS league={league} date={date_str} file={name} stale=0 reuse=True", flush=True)
        return True
    detail = ";".join(
        f"{team}:+{','.join(item['added']) or '-'}/-{','.join(item['removed']) or '-'}" for team, item in sorted(drift.items())
    )
    print(
        f"[smart_sim_reuse] SMART_SIM_REUSE_STALE_EXCLUSIONS league={league} date={date_str} file={name} stale=1 "
        f"teams={len(drift)} drift={detail} reuse=False",
        flush=True,
    )
    return False
