"""Build `feature_generation_payload` for NCAAF from the season snapshots.

--------------------------------------------------------------------------
WHAT THIS IS FOR, AND WHY IT IS DEFAULT-OFF
--------------------------------------------------------------------------

`#457`: `drive_priors.py` reads 9 blocks / 65 keys out of
`feature_generation_payload`, and all three production entrypoints construct
`SmartSim2SimulationInput` WITHOUT it. Every NFL and NCAAF game in production
runs on four rating scalars plus a hardcoded `pace_seconds_per_play=24.0`, with
`returning_production_index=0.5`, `coach_continuity_index=0.5`,
`player_usage_index=0.25` and `market_prior_index=0.5` carried identically by
every game.

This module fills four of those blocks from the snapshots built 2026-08-27 --
returning production (136 teams), coach continuity (138), transfers (3,305),
roster (15,496).

**IT IS WIRED BEHIND A FLAG AND DEFAULTS OFF, DELIBERATELY.**
`state.md` is explicit: *"DO NOT JUST WIRE IT. Both calibration profiles were
fit against a payload the engine cannot read, so this is a mechanism added to a
calibrated engine and owes a re-fit"* -- and the same pattern was measured
elsewhere as a **negative interaction in 4 of 4 markets**. The published deltas
(margin -1.125, total -1.685, home win% -6.50pts) are the DISTURBANCE, not the
improvement.

So the flag exists to make the mechanism MEASURABLE, not to turn it on. The
go/no-go is a re-fit evaluated against the market, not this file.

--------------------------------------------------------------------------
THREE BLOCKS ARE DELIBERATELY NOT FILLED
--------------------------------------------------------------------------

`state.md` names them and each needs a different remedy, so filling them from
here would paper over three distinct defects:

  defensive_metrics  MISROUTED -- all 7 keys sit in `team_metrics` at 100%.
                     A routing fix, not a data one.
  pace               NULL AT SOURCE -- all 4 keys are `None` on 272 games.
                     A data-pipeline job.
  player_usage       WRONG GRAIN -- 19,400 player rows exist but
                     `FootballGameFeatures` has no game-level block, and
                     `adapters._team_player_usage` already aggregates
                     correctly with nothing consuming its output.

Emitting a neutral default for any of them would make an unfed block
indistinguishable from a working one -- the exact failure
`model_engine_standard.md` was written for.
"""
from __future__ import annotations

import csv
import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Any

_SPACE_RE = re.compile(r"\s+")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9 ]+")


def _norm(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.strip().lower().replace("&", " and ")
    text = _NON_ALNUM_RE.sub(" ", text)
    return _SPACE_RE.sub(" ", text).strip()


def _processed(*parts: str) -> Path:
    return (
        Path(__file__).resolve().parents[3]
        / "data" / "ncaaf_source" / "source_artifacts" / "data" / "processed" / Path(*parts)
    )


def _read(*parts: str) -> list[dict[str, str]]:
    from syndicate.features.ncaaf.sources import ncaaf_source_artifacts_data_path

    for path in (ncaaf_source_artifacts_data_path("processed", *parts), _processed(*parts)):
        try:
            if path.exists():
                with path.open("r", encoding="utf-8", newline="") as handle:
                    rows = [dict(r) for r in csv.DictReader(handle)]
                if rows:
                    return rows
        except Exception:
            continue
    return []


def _f(value: Any) -> float | None:
    try:
        text = str(value or "").strip()
        return float(text) if text else None
    except (TypeError, ValueError):
        return None


@lru_cache(maxsize=4)
def _index(season: int) -> dict[str, Any]:
    """team_id -> the four blocks, for one season."""
    registry = _read("team_registry", "ncaaf_team_registry_snapshot.csv") or _read(
        "team_registry", "ncaaf_team_registry.csv"
    )
    id_by_name: dict[str, str] = {}
    for row in registry:
        team_id = str(row.get("team_id") or "").strip()
        if not team_id:
            continue
        school = _norm(row.get("school_name"))
        mascot = _norm(row.get("mascot_name"))
        for form in {school, _norm(row.get("canonical_team_name")), _norm(row.get("display_name")),
                     _norm(row.get("abbreviation")), f"{school} {mascot}".strip()}:
            if form:
                id_by_name.setdefault(form, team_id)

    season_text = str(int(season))
    returning: dict[str, dict[str, Any]] = {}
    for row in _read("returning_production", "ncaaf_returning_production_snapshot.csv"):
        if str(row.get("season") or "") != season_text:
            continue
        returning[str(row.get("team_id") or "").strip()] = {
            "percent_ppa": _f(row.get("percent_ppa")),
            "usage": _f(row.get("usage")),
            "total_ppa": _f(row.get("total_ppa")),
        }

    coach: dict[str, dict[str, Any]] = {}
    for row in _read("coach_continuity", "ncaaf_coach_continuity_snapshot.csv"):
        if str(row.get("season") or "") != season_text:
            continue
        coach[str(row.get("team_id") or "").strip()] = {
            "continuity_score": _f(row.get("continuity_score")),
            "tenure_years": _f(row.get("coach_tenure_years")),
        }

    transfers_in: dict[str, int] = {}
    transfers_out: dict[str, int] = {}
    for row in _read("transfers", "ncaaf_transfer_portal_snapshot.csv"):
        if str(row.get("season") or "") != season_text:
            continue
        dest = str(row.get("destination_team_id") or "").strip()
        orig = str(row.get("origin_team_id") or "").strip()
        if dest:
            transfers_in[dest] = transfers_in.get(dest, 0) + 1
        if orig:
            transfers_out[orig] = transfers_out.get(orig, 0) + 1

    roster: dict[str, int] = {}
    for row in _read("roster", "ncaaf_roster_snapshot.csv"):
        if str(row.get("season") or "") != season_text:
            continue
        tid = str(row.get("team_id") or "").strip()
        if tid:
            roster[tid] = roster.get(tid, 0) + 1

    return {
        "id_by_name": id_by_name,
        "returning": returning,
        "coach": coach,
        "transfers_in": transfers_in,
        "transfers_out": transfers_out,
        "roster": roster,
    }


def team_id_for(name: str, season: int) -> str | None:
    return _index(int(season))["id_by_name"].get(_norm(name))


def build_payload(*, home_team: str, away_team: str, season: int) -> dict[str, Any]:
    """The payload for one game, or `{}` when nothing resolves.

    `{}` rather than a skeleton of neutral defaults: `build_drive_priors`
    already falls back to the rating scalars for an absent block, and a
    hand-built skeleton of 0.5s would be indistinguishable from real data at
    every level except the source file.

    Keyed on the HOME team for the blocks `drive_priors` reads as scalars --
    it derives one offense-strength index per game, and feeding it the away
    side's continuity would be an answer to a different question. The away
    values ride along under `away_*` so a future two-sided consumer has them
    without another pass.
    """
    idx = _index(int(season))
    home_id = idx["id_by_name"].get(_norm(home_team))
    away_id = idx["id_by_name"].get(_norm(away_team))
    if not home_id:
        return {}

    payload: dict[str, Any] = {}

    ret = idx["returning"].get(home_id) or {}
    if ret.get("percent_ppa") is not None:
        payload["returning_production"] = {
            "percent_ppa": ret["percent_ppa"],
            "usage": ret.get("usage"),
            "away_percent_ppa": (idx["returning"].get(away_id) or {}).get("percent_ppa"),
        }

    coach = idx["coach"].get(home_id) or {}
    if coach.get("continuity_score") is not None:
        payload["coach_continuity"] = {
            "continuity_score": coach["continuity_score"],
            "tenure_years": coach.get("tenure_years"),
            "away_continuity_score": (idx["coach"].get(away_id) or {}).get("continuity_score"),
        }

    tin = idx["transfers_in"].get(home_id)
    tout = idx["transfers_out"].get(home_id)
    if tin is not None or tout is not None:
        payload["transfer_impact"] = {
            "incoming": tin or 0,
            "outgoing": tout or 0,
            "net": (tin or 0) - (tout or 0),
            "away_net": (idx["transfers_in"].get(away_id) or 0) - (idx["transfers_out"].get(away_id) or 0),
        }

    roster_n = idx["roster"].get(home_id)
    if roster_n:
        payload["roster_depth"] = {
            "active_count": roster_n,
            "away_active_count": idx["roster"].get(away_id) or 0,
        }

    if payload:
        payload["adapter_metadata"] = {
            "source": f"ncaaf_snapshots_{int(season)}",
            "home_team_id": home_id,
            "away_team_id": away_id,
            "blocks": sorted(k for k in payload if k != "adapter_metadata"),
            # NAMED, so a reader can see what is NOT here without diffing
            # against `drive_priors`. See this module's docstring.
            "blocks_deliberately_absent": ["defensive_metrics", "pace", "player_usage"],
        }
    return payload


def reset_caches() -> None:
    _index.cache_clear()
