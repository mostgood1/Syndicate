"""Blend batted-ball quality into a batter's rate ESTIMATES. `#440`.

NOT A MECHANISM. The 2x2 factorial showed that adding mechanisms (substitution,
pitch-type splits) to this engine produces a NEGATIVE interaction, because the
fitted `hr_rate` / `inplay_hit_rate` already absorb their average effect and
re-adding them double-counts.

This does something different: it estimates THE SAME PARAMETERS better. Measured
leak-free (all predictors first-half only, n=218):

    predictor                vs future HR/PA   vs future TB/AB
    hr_rate (current input)        0.312             0.126
    barrel%                        0.387             0.178
    hard-hit% (EV>=95)             0.363             0.235

Replacing part of a noisy outcome rate with a better-predicting process rate
does not double-count a mechanism, so it is NOT expected to interfere the way
the mechanisms did. **That is an expectation, not a result — the factorial is
how it gets checked.**

THE BLEND is deliberately rank-preserving and unit-free:

    multiplier = 1 + weight * (player_metric / league_metric - 1)
    rate_new   = rate_observed * clamp(multiplier)

so it shifts a batter toward what his CONTACT QUALITY implies without needing a
barrel%-to-HR/PA unit conversion, and a league-average batter is unchanged. The
clamp exists because a 3x barrel outlier must not produce a 3x home-run rate.

DARK-LAUNCHED: the caller must pass a non-zero weight. Absent artifact, absent
player, or weight 0 leaves the profile untouched.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

_ARTIFACT_CACHE: Dict[int, Optional[dict]] = {}
_REL = "mlb_source/source_artifacts/data/batted_ball"

# Guard rails on the multiplier. Contact quality is informative, not decisive:
# the observed rate still carries most of the weight, and an extreme leaderboard
# value must not swing a rate by more than this.
_MULT_MIN, _MULT_MAX = 0.70, 1.40


def _root() -> Path:
    override = str(os.environ.get("SYNDICATE_DATA_ROOT") or "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return Path(__file__).resolve().parents[4] / "data"


def load_batted_ball(season: int) -> Optional[dict]:
    """Whole-season batted-ball artifact, memoised. None when absent."""
    if season in _ARTIFACT_CACHE:
        return _ARTIFACT_CACHE[season]
    out = None
    try:
        p = _root() / _REL / f"batted_ball_{int(season)}.json"
        if p.is_file():
            payload = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(payload.get("players"), dict) and payload["players"]:
                out = payload
    except Exception:
        out = None
    _ARTIFACT_CACHE[season] = out
    return out


def _league_mean(players: dict, key: str) -> Optional[float]:
    vals = []
    for e in players.values():
        v = (e or {}).get(key)
        if isinstance(v, (int, float)) and v == v and v > 0:
            vals.append(float(v))
    return (sum(vals) / len(vals)) if len(vals) >= 20 else None


def _mult(player_val: Any, league_val: Optional[float], weight: float) -> Optional[float]:
    if league_val is None or not isinstance(player_val, (int, float)):
        return None
    if player_val != player_val or player_val <= 0 or league_val <= 0:
        return None
    raw = 1.0 + weight * ((float(player_val) / league_val) - 1.0)
    return max(_MULT_MIN, min(_MULT_MAX, raw))


def apply_batted_ball_to_batter(prof: Any, *, season: int, weight: float = 0.35) -> bool:
    """Shift this batter's hr_rate / inplay_hit_rate toward his contact quality.

    `weight` is the pull toward the batted-ball signal. 0.35 is a starting value
    chosen to be conservative relative to the measured predictive edge (barrel
    0.387 vs hr_rate 0.312), NOT a fitted optimum — it is a knob for the refit
    to set, and it is recorded here as unfitted so nobody reads it as tuned.

    Returns True when the profile was modified.
    """
    if weight <= 0.0:
        return False
    art = load_batted_ball(season)
    if not art:
        return False
    players = art["players"]
    pid = int(getattr(getattr(prof, "player", None), "mlbam_id", 0) or 0)
    entry = players.get(str(pid))
    if not isinstance(entry, dict):
        return False

    changed = False
    # barrels drive HOME RUNS; hard contact drives EXTRA BASES / BABIP.
    # Pairing each metric with the rate it actually predicts is the whole point
    # of the measurement -- using one metric for both would discard that.
    hr_mult = _mult(entry.get("barrel_pct"), _league_mean(players, "barrel_pct"), weight)
    if hr_mult is not None:
        try:
            prof.hr_rate = float(prof.hr_rate) * hr_mult
            changed = True
        except Exception:
            pass

    ip_mult = _mult(entry.get("hard_hit_pct"), _league_mean(players, "hard_hit_pct"), weight)
    if ip_mult is not None:
        try:
            prof.inplay_hit_rate = float(prof.inplay_hit_rate) * ip_mult
            changed = True
        except Exception:
            pass

    # NATIVE batted-ball rates -- the fields `simulate.py:1120-1123` actually
    # reads. THIS IS THE POINT OF THE WHOLE ARTIFACT, and the first version of
    # this module missed it entirely: it scaled `hr_rate`/`inplay_hit_rate` (a
    # proxy) while `bb_gb_rate` and friends stayed at their league defaults, so
    # every hitter kept an identical batted-ball profile. Measured after a
    # simulated rebuild: 26 unfed fields -> 20, with all five `bb_*` still
    # failing, which is what exposed it.
    #
    # The leaderboard gives a 2-way split (`gb` vs `fbld`); the sim wants 4. The
    # player's REAL ground-ball share is the large, player-specific signal and is
    # used directly; the air-ball remainder is divided using the league
    # proportions the engine already defaults to (fb .25 / ld .20 / pu .11,
    # renormalised within non-GB). Stated plainly: the GB/air split is measured
    # per player, the split WITHIN air balls is not.
    gb_share = entry.get("gb_share")
    if isinstance(gb_share, (int, float)) and 0.0 < float(gb_share) < 1.0:
        try:
            gb = float(gb_share)
            rest = 1.0 - gb
            total_air = 0.25 + 0.20 + 0.11
            prof.bb_gb_rate = gb
            prof.bb_fb_rate = rest * (0.25 / total_air)
            prof.bb_ld_rate = rest * (0.20 / total_air)
            prof.bb_pu_rate = rest * (0.11 / total_air)
            bbe = entry.get("bbe")
            if isinstance(bbe, (int, float)) and bbe > 0:
                prof.bb_inplay_n = int(bbe)
            changed = True
        except Exception:
            pass

    if changed:
        try:
            setattr(prof, "batted_ball_source", "statcast_leaderboard")
            setattr(prof, "batted_ball_bbe", int(entry.get("bbe") or 0))
            setattr(prof, "batted_ball_weight", float(weight))
        except Exception:
            pass
    return changed


__all__ = ["apply_batted_ball_to_batter", "load_batted_ball"]
