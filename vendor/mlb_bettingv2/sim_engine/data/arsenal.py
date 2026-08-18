"""Apply per-pitch-type matchup multipliers from the ARSENAL artifact. `#440`.

Fills FIVE fields the sim consumes as `.get(pitch_type, 1.0)` and which were
therefore silent no-ops -- a slider and a fastball were interchangeable:

    pitcher.pitch_type_whiff_mult    pitcher.pitch_type_inplay_mult
    pitcher.pitch_type_hr_mult       batter.vs_pitch_type
    batter.vs_pitch_type_hr

SUPERSEDES `statcast_pitch_splits`, which needed 309 per-pitcher network calls
(~80 min) to fill TWO of these for 305 pitchers. The arsenal artifact is two
leaderboard calls and covers 466 pitchers and 384 batters, both sides of the
matchup. **This module is applied AFTER the pitch-splits applier so it wins where
both have data**, and the older path remains as a fallback rather than being
deleted -- it still covers pitchers the leaderboard drops for having a single
pitch type.

THE MULTIPLIERS ARE LEVEL-NEUTRAL. They are normalised in the builder against
each player's OWN usage-weighted mean, so they average ~1.0 across an arsenal and
say only "this pitch is better or worse than this player's average pitch". The
overall level already lives in `k_rate` / `hr_rate`; encoding it again here would
double-count, which is the calibration-absorption failure measured 2026-08-17
(two mechanisms, interaction -0.00331, negative in 4 of 4).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

_CACHE: Dict[int, Optional[dict]] = {}
_REL = "mlb_source/source_artifacts/data/arsenal"


def _root() -> Path:
    override = str(os.environ.get("SYNDICATE_DATA_ROOT") or "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return Path(__file__).resolve().parents[4] / "data"


def load_arsenal(season: int) -> Optional[dict]:
    """Whole-season arsenal artifact, memoised. None when absent."""
    if season in _CACHE:
        return _CACHE[season]
    out = None
    try:
        p = _root() / _REL / f"arsenal_{int(season)}.json"
        if p.is_file():
            payload = json.loads(p.read_text(encoding="utf-8"))
            if payload.get("pitchers") or payload.get("batters"):
                out = payload
    except Exception:
        out = None
    _CACHE[season] = out
    return out


def _pt(code: str):
    """Canonical PitchType, or None when the code is unknown to the engine."""
    from ..models import PitchType
    try:
        return PitchType(str(code).strip().upper())
    except Exception:
        return None


def _entry_for(prof: Any, season: int, side: str) -> Optional[dict]:
    art = load_arsenal(season)
    if not art:
        return None
    pid = int(getattr(getattr(prof, "player", None), "mlbam_id", 0) or 0)
    if pid <= 0:
        return None
    entry = (art.get(side) or {}).get(str(pid))
    return entry if isinstance(entry, dict) and entry else None


def apply_arsenal_to_pitcher(prof: Any, *, season: int) -> bool:
    """Set this pitcher's per-pitch-type whiff / in-play / HR multipliers."""
    entry = _entry_for(prof, season, "pitchers")
    if entry is None:
        return False
    whiff, inplay, hr = {}, {}, {}
    for code, vals in entry.items():
        pt = _pt(code)
        if pt is None or not isinstance(vals, dict):
            continue
        if isinstance(vals.get("whiff_mult"), (int, float)):
            whiff[pt] = float(vals["whiff_mult"])
        if isinstance(vals.get("inplay_mult"), (int, float)):
            inplay[pt] = float(vals["inplay_mult"])
        if isinstance(vals.get("hr_mult"), (int, float)):
            hr[pt] = float(vals["hr_mult"])
    if not (whiff or inplay or hr):
        return False
    try:
        if whiff:
            prof.pitch_type_whiff_mult = whiff
        if inplay:
            prof.pitch_type_inplay_mult = inplay
        if hr:
            prof.pitch_type_hr_mult = hr
        setattr(prof, "arsenal_source", "statcast_arsenal_leaderboard")
        return True
    except Exception:
        return False


def apply_arsenal_to_batter(prof: Any, *, season: int) -> bool:
    """Set this batter's performance BY PITCH TYPE.

    `vs_pitch_type` takes the in-play (contact-quality) multiplier and
    `vs_pitch_type_hr` the power multiplier, matching how `simulate.py:1067-1068`
    reads them -- a general term and an HR-specific one.
    """
    entry = _entry_for(prof, season, "batters")
    if entry is None:
        return False
    contact, power = {}, {}
    for code, vals in entry.items():
        pt = _pt(code)
        if pt is None or not isinstance(vals, dict):
            continue
        if isinstance(vals.get("inplay_mult"), (int, float)):
            contact[pt] = float(vals["inplay_mult"])
        if isinstance(vals.get("hr_mult"), (int, float)):
            power[pt] = float(vals["hr_mult"])
    if not (contact or power):
        return False
    try:
        if contact:
            prof.vs_pitch_type = contact
        if power:
            prof.vs_pitch_type_hr = power
        return True
    except Exception:
        return False


__all__ = ["apply_arsenal_to_pitcher", "apply_arsenal_to_batter", "load_arsenal"]
