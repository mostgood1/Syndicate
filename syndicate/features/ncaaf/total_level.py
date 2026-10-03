"""NCAAF total-level shrink -- ONE value for the pregame generator AND the live re-sim.

WHAT IT IS. NCAAF's version of NFL's `NFL_TOTAL_LEVEL_SHRINK`
(`[nfl-total-level-gain]`): scale the two teams' COMMON rating level by
lambda and leave every DIFFERENCE between them exactly intact. The margin reads
the difference and the total reads the level; one gain (`SP_RATING_SCALE`,
calibrated on margins) served both, and the level was over-applied.

THE DEFECT, measured as-of over 626 of 2025's 644 graded FBS games
(`scripts/backtest_ncaaf_lines_props.py`, arm L25): pregame total MAE 14.32 vs
the CFBD close 12.15 (+2.16 [+1.49, +2.82]) and worse than naive team scoring
averages (+1.93); model total SD 12.83 against the close's 6.30;
actual-on-model slope 0.30. Correlated, over-amplified: a gain defect.

THE VALUE is set from the lambda fit recorded in
`.syndicate/findings_2026-10-02_ncaaf_lines_props_backtest.md` (re-simulated
through the engine on 2025, validated on 2026 wk3-4). 1.0 is the unshrunk
engine, exactly.

WHERE IT APPLIES, AND ONE PLACE EACH:
  * pregame -- `scripts/generate_smartsim2_ncaaf_projections.build_projection`,
    after both rating paths (SP+ and the PPA fallback);
  * live -- `ncaaf/live_resim.resim_live_game`, on the ratings it is handed, so
    the cutoff-replay grade (`scripts/backtest_ncaaf_live_totals.py`, which
    calls that shipped function) measures exactly what production runs. The
    caller exempts FBS-vs-FCS games whose unrated side is MARKET-IMPLIED: that
    rating is solved so the engine reproduces the market's own total, and
    shrinking it would pull a market-anchored total back toward the league.

THE LIVE PATH WAS ALREADY CALIBRATED WITHOUT IT. Graded 2026-09-27 with fresh
ratings (546 Saturday cutoff rows / 182 games): live total bias +0.171 [-1.176,
+1.538], worst bucket 0.0556 against `#499`'s 0.150 bar, both live calibrators
set to identity. A lambda < 1 on the live path is therefore UNMEASURED there:
re-run that grade at the shipped lambda before a fleet update carries it, and
`SYNDICATE_NCAAF_LIVE_TOTAL_LEVEL_SHRINK=1` turns it off for live alone.

OVERRIDES. `SYNDICATE_NCAAF_TOTAL_LEVEL_SHRINK` sets both paths;
`SYNDICATE_NCAAF_LIVE_TOTAL_LEVEL_SHRINK` overrides the live path only. Absent
means the constant; unparseable falls back to it (never to "off"); negatives
clamp to 0; `1` is the exact kill switch.
"""
from __future__ import annotations

import os

NCAAF_TOTAL_LEVEL_SHRINK = 1.0

PREGAME_ENV = "SYNDICATE_NCAAF_TOTAL_LEVEL_SHRINK"
LIVE_ENV = "SYNDICATE_NCAAF_LIVE_TOTAL_LEVEL_SHRINK"


def _parse(raw: str, default: float) -> float:
    try:
        value = float(raw) if raw else default
    except ValueError:
        value = default
    return max(0.0, value)


def total_level_shrink() -> float:
    """The pregame lambda (and the live one unless `LIVE_ENV` says otherwise)."""
    return _parse(str(os.environ.get(PREGAME_ENV) or "").strip(), NCAAF_TOTAL_LEVEL_SHRINK)


def live_total_level_shrink() -> float:
    """The live lambda: `LIVE_ENV` if set, else exactly the pregame lambda."""
    raw = str(os.environ.get(LIVE_ENV) or "").strip()
    return _parse(raw, total_level_shrink()) if raw else total_level_shrink()


def shrink_rating_level(
    home_off: float, home_def: float, away_off: float, away_def: float, shrink: float,
) -> tuple[float, float, float, float]:
    """Scale the two teams' COMMON level by `shrink`, leaving every DIFFERENCE
    between them exactly intact (NFL's arithmetic). Ratings are centred on the
    league, so shrinking toward 0 shrinks toward the league-average total. Exact
    in the ratings, statistical in the output: the sim is non-linear, so the
    margin moves within seed noise."""
    if shrink == 1.0:
        return home_off, home_def, away_off, away_def
    out = []
    for home, away in ((home_off, away_off), (home_def, away_def)):
        level, half = (home + away) / 2.0, (home - away) / 2.0
        out.append((shrink * level + half, shrink * level - half))
    (new_home_off, new_away_off), (new_home_def, new_away_def) = out
    return new_home_off, new_home_def, new_away_off, new_away_def
