"""Measured skill for markets whose PRODUCER attaches no `model_skill` note.

WHY THIS EXISTS. `projection_skill.attach_projection_skill` stamps
`status: "unmeasured"` ("model never backtested -- projection is unvalidated")
on every projection whose producer attached no note. That is the honest answer
when nothing was measured. It was also the answer on markets that HAD been
measured. Census of the served Layer 2 shortlist, 2026-09-14, lane
`accuracy-assessment-0914`: 605 of 1,394 rows carried the label (mlb 268,
soccer 268, nfl 69). They included MLB full-game moneyline and totals
(482 finals, `state_mlb.md [mlb-sim-edge-is-anti-predictive]`) and soccer 1X2
(the 1,112-match backtest, `state.md` user decision 7). The measurement
existed; the row said it did not.

WHY A TABLE HERE AND NOT IN EACH PRODUCER. `projection_skill`'s docstring
prefers a producer attaching its own note, and producers that do
(`nfl_preseason_calibration`, `ncaaf.game_projections`, `mlb_prop_calibration`)
keep precedence: this table is consulted ONLY where no note exists. The game
producers it covers are reached through `board_enrichment`'s per-sport return
sites. One lookup behind the choke point every caller already shares covers all
of them; per-producer wiring is `#334`'s failure (three of four paths patched).

WHAT AN ENTRY IS. A measurement on the full projection population against the
de-vigged market -- or against the closing LINE, for spreads and totals --
with its window, its sample and its sign. It is NOT a claim that the model is
good. Most entries say it loses to the market, and a reader is entitled to that
number either way. An entry that cannot cite where it was measured does not
belong here: `source` is required.

PHASE IS PART OF THE KEY. A pregame measurement says nothing about a live
re-sim's number (`projection["live_aware"]`, set by `live_projection_join`).
MLB's live model has its own, different record, and a pregame note on a live
row would be the inherited-number failure `live_gameline_join` names.

ADMISSION. `layer2_board._row_rests_on_unmeasured_model` withholds ONE-SIDED
(`book_margin_model`) rows whose model is not `measured`, so relabelling a
market can re-admit rows. On the 2026-09-14 shortlist every row in the markets
this table covers was priced `consensus` (two-sided) and none changed admission.
`TWO_SIDED_GAME_MARKETS` pins that: an entry outside it whose verdict is not
`beats_market` needs `admission_checked` naming the reading that cleared it.

PAYLOAD DISCIPLINE, same as `projection_skill`: the per-row note is six short
keys. The numbers behind a verdict live in the entry, not on the row.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

PHASE_PREGAME = "pregame"
PHASE_LIVE = "live"

VERDICT_BEATS = "beats_market"
VERDICT_PARITY = "parity"
VERDICT_LOSES = "loses_to_market"
VERDICT_CLASSES = frozenset({VERDICT_BEATS, VERDICT_PARITY, VERDICT_LOSES})

TWO_SIDED_GAME_MARKETS = frozenset({"h2h", "spreads", "totals", "btts", "team_totals"})

NOTE_BASIS = "measured_market_skill"

REQUIRED_ENTRY_KEYS = ("sample_games", "seasons", "verdict", "verdict_class", "source")

_MLB_LIVE_SOURCE = (
    "lane accuracy-assessment-0914: production live_gameline_ledger (web copy) vs "
    "StatsAPI finals, fresh quotes <=120s, paired rows, bootstrap over games"
)
_MLB_PREGAME_SOURCE = (
    "lane accuracy-assessment-0914: production daily_summary game probabilities "
    "(post-first-pitch re-sims, so parity is an upper bound) vs the single-book "
    "pregame freeze, de-vigged, vs StatsAPI finals, bootstrap over games"
)
_MLB_PROPS_SOURCE = (
    "lane accuracy-assessment-0914: production daily_summary prop projections "
    "(re-simulated after the games, so parity is an upper bound) vs de-vigged book "
    "prices vs StatsAPI box scores, bootstrap over games"
)
_FOOTBALL_SOURCE = (
    "lane accuracy-assessment-0914: production NCAAF/NFL projection CSVs (inputs "
    "verified pregame) vs OddsAPI closes vs ESPN finals, bootstrap over games"
)
_SOCCER_SOURCE = (
    "lane accuracy-assessment-0914: production odds_history closes (per book, "
    "proportional de-vig, averaged) vs soccer projection artifacts vs ESPN finals, "
    "draws counted, bootstrap over matches"
)

# (sport, market, segment, phase) -> entry.
MEASURED_MARKET_SKILL: dict[tuple[str, str, str, str], dict[str, Any]] = {
    # ---- MLB, LIVE ------------------------------------------------------------
    # Full-game h2h is the market MLB live publication was switched off for
    # (lane `mlb-stop-publishing-edges`). This window re-confirms the loss.
    # Since the 09-08 changes it reads parity (+0.00356 [-0.00966, +0.01610],
    # 69 games) -- under-powered, so the pooled window is what the row carries.
    ("mlb", "h2h", "full", PHASE_LIVE): {
        "sample_games": 176,
        "seasons": "2026-08-31..09-13 live",
        "brier_model": 0.16949,
        "brier_market": 0.15931,
        "diff": 0.01019,
        "ci95": (0.00089, 0.02045),
        "verdict": "live: loses to the market, Brier +0.010 [+0.001, +0.020] over 176 games; worst where it disagrees most",
        "verdict_class": VERDICT_LOSES,
        "source": _MLB_LIVE_SOURCE,
    },
    ("mlb", "h2h", "first5", PHASE_LIVE): {
        "sample_games": 67,
        "seasons": "2026-09-08..09-13 live",
        "brier_model": 0.16821,
        "brier_market": 0.15916,
        "diff": 0.00905,
        "ci95": (-0.00869, 0.02806),
        "verdict": "live first-5: parity with the market, Brier +0.009 [-0.009, +0.028] over 67 games",
        "verdict_class": VERDICT_PARITY,
        "source": _MLB_LIVE_SOURCE + "; first5 observation rows, ties dropped, no quote age",
    },
    ("mlb", "totals", "full", PHASE_LIVE): {
        "sample_games": 159,
        "seasons": "2026-08-31..09-13 live (no 09-09)",
        "brier_model": 0.24824,
        "brier_market": 0.24342,
        "diff": 0.00482,
        "ci95": (-0.00847, 0.01889),
        "verdict": "live: parity with the market, Brier +0.005 [-0.008, +0.019] over 159 games; runs high early",
        "verdict_class": VERDICT_PARITY,
        "source": _MLB_LIVE_SOURCE,
    },
    ("mlb", "spreads", "full", PHASE_LIVE): {
        "sample_games": 159,
        "seasons": "2026-08-31..09-13 live (no 09-09)",
        "brier_model": 0.22852,
        "brier_market": 0.22849,
        "diff": 0.00002,
        "ci95": (-0.0139, 0.01468),
        "verdict": "live: parity with the market, Brier +0.000 [-0.014, +0.015] over 159 games",
        "verdict_class": VERDICT_PARITY,
        "source": _MLB_LIVE_SOURCE,
    },
    # ---- SOCCER, PREGAME --------------------------------------------------------
    # Every projection artifact in the window was REBUILT after its match, so the
    # scored number is not the one published before kickoff. A leak can only
    # flatter the model: "loses" is robust, "parity" is an upper bound on skill.
    ("soccer", "h2h", "full", PHASE_PREGAME): {
        "sample_games": 121,
        "seasons": "2026-09-07..09-13 pregame, current model version",
        "brier_model": 0.6474,
        "brier_market": 0.6028,
        "diff": 0.0446,
        "ci95": (0.0148, 0.0742),
        "verdict": "loses to the de-vigged close: 1X2 Brier +0.045 [+0.015, +0.074] over 121 matches; under-prices favourites",
        "verdict_class": VERDICT_LOSES,
        "source": _SOCCER_SOURCE,
    },
    ("soccer", "totals", "full", PHASE_PREGAME): {
        "sample_games": 194,
        "seasons": "2026-08-31..09-13 pregame, main line",
        "brier_model": 0.2603,
        "brier_market": 0.2505,
        "diff": 0.0099,
        "ci95": (-0.0037, 0.0237),
        "verdict": "parity with the de-vigged close: main-line Brier +0.010 [-0.004, +0.024] over 194 matches",
        "verdict_class": VERDICT_PARITY,
        "source": _SOCCER_SOURCE,
    },
    ("soccer", "spreads", "full", PHASE_PREGAME): {
        "sample_games": 100,
        "seasons": "2026-09-07..09-13 pregame, main Asian handicap line",
        "brier_model": 0.2698,
        "brier_market": 0.2433,
        "diff": 0.0265,
        "ci95": (0.0001, 0.0542),
        "verdict": "loses to the close, borderline: Asian handicap Brier +0.027 [+0.000, +0.054] over 100 matches",
        "verdict_class": VERDICT_LOSES,
        "source": _SOCCER_SOURCE,
    },
    # ---- SOCCER, LIVE -----------------------------------------------------------
    ("soccer", "h2h", "full", PHASE_LIVE): {
        "sample_games": 118,
        "seasons": "2026-08-31..09-13 live, fresh quotes",
        "brier_model": 0.1490,
        "brier_market": 0.1340,
        "diff": 0.0150,
        "ci95": (-0.0032, 0.0319),
        "verdict": "live: parity with the market, Brier +0.015 [-0.003, +0.032] over 118 matches; worse when it disagrees 10pp+",
        "verdict_class": VERDICT_PARITY,
        "source": _SOCCER_SOURCE + "; live_gameline_ledger, quotes <=120s, 80 sims",
    },
    ("soccer", "totals", "full", PHASE_LIVE): {
        "sample_games": 44,
        "seasons": "2026-08-31..09-13 live, fresh quotes",
        "verdict": "live: parity, model-mean lean hit 52.7% [44.2%, 61.3%] over 44 matches",
        "verdict_class": VERDICT_PARITY,
        "source": _SOCCER_SOURCE + "; live_gameline_ledger point forecast, quotes <=120s",
    },
    # ---- MLB GAME MARKETS, PREGAME --------------------------------------------------
    # Scored against the single-book pregame freeze (the best-price `closing_lines`
    # file was >2h stale on 49% of full-game totals), 188 games / 14 dates, the whole
    # slate. The served `daily_summary` is a re-sim written after first pitch, and the
    # sim changed three times inside the window (e3bdbc8b 09-01, ead7c6c5 09-05,
    # 72499c2a 09-08): every verdict below is parity at best, and on moneyline, run
    # line and first5 run line ADDING the sim to the market made out-of-sample Brier
    # worse. "Parity" here is not "useful".
    ("mlb", "h2h", "full", PHASE_PREGAME): {
        "sample_games": 188,
        "seasons": "2026-08-31..09-13 pregame",
        "brier_model": 0.24715, "brier_market": 0.23805, "diff": 0.0091, "ci95": (-0.0046, 0.0236),
        "verdict": "parity with the close, point worse: Brier +0.009 [-0.005, +0.024] over 188 games; adding it to the market hurts",
        "verdict_class": VERDICT_PARITY,
        "source": _MLB_PREGAME_SOURCE,
    },
    ("mlb", "spreads", "full", PHASE_PREGAME): {
        "sample_games": 188,
        "seasons": "2026-08-31..09-13 pregame",
        "brier_model": 0.24526, "brier_market": 0.23752, "diff": 0.0077, "ci95": (-0.0055, 0.0207),
        "verdict": "parity with the close, point worse: run line Brier +0.008 [-0.006, +0.021] over 188 games; adding it hurts",
        "verdict_class": VERDICT_PARITY,
        "source": _MLB_PREGAME_SOURCE,
    },
    ("mlb", "totals", "full", PHASE_PREGAME): {
        "sample_games": 177,
        "seasons": "2026-08-31..09-13 pregame",
        "brier_model": 0.25424, "brier_market": 0.25033, "diff": 0.0039, "ci95": (-0.0166, 0.0246),
        "verdict": "parity with the close over 177 games, but only because scoring ran high: the sim sits ~2 runs above the line since 09-05",
        "verdict_class": VERDICT_PARITY,
        "source": _MLB_PREGAME_SOURCE,
    },
    ("mlb", "h2h", "first5", PHASE_PREGAME): {
        "sample_games": 148,
        "seasons": "2026-08-31..09-13 pregame",
        "brier_model": 0.24983, "brier_market": 0.24094, "diff": 0.0089, "ci95": (-0.0094, 0.0272),
        "verdict": "first 5: parity with the close, point worse: Brier +0.009 [-0.009, +0.027] over 148 games",
        "verdict_class": VERDICT_PARITY,
        "source": _MLB_PREGAME_SOURCE,
    },
    ("mlb", "spreads", "first5", PHASE_PREGAME): {
        "sample_games": 168,
        "seasons": "2026-08-31..09-13 pregame",
        "brier_model": 0.25688, "brier_market": 0.24992, "diff": 0.0070, "ci95": (-0.0084, 0.0227),
        "verdict": "first 5: parity with the close: run line Brier +0.007 [-0.008, +0.023] over 168 games; adding it hurts",
        "verdict_class": VERDICT_PARITY,
        "source": _MLB_PREGAME_SOURCE,
    },
    ("mlb", "totals", "first5", PHASE_PREGAME): {
        "sample_games": 168,
        "seasons": "2026-08-31..09-13 pregame",
        "brier_model": 0.24937, "brier_market": 0.25120, "diff": -0.0018, "ci95": (-0.0190, 0.0157),
        "verdict": "first 5: parity with the close: totals Brier -0.002 [-0.019, +0.016] over 168 games",
        "verdict_class": VERDICT_PARITY,
        "source": _MLB_PREGAME_SOURCE,
    },
    ("mlb", "h2h", "first3", PHASE_PREGAME): {
        "sample_games": 124,
        "seasons": "2026-08-31..09-13 pregame",
        "brier_model": 0.23951, "brier_market": 0.24617, "diff": -0.0067, "ci95": (-0.0244, 0.0120),
        "verdict": "first 3: parity with the close: Brier -0.007 [-0.024, +0.012] over 124 games",
        "verdict_class": VERDICT_PARITY,
        "source": _MLB_PREGAME_SOURCE,
    },
    ("mlb", "spreads", "first3", PHASE_PREGAME): {
        "sample_games": 168,
        "seasons": "2026-08-31..09-13 pregame",
        "brier_model": 0.24341, "brier_market": 0.24360, "diff": -0.0002, "ci95": (-0.0123, 0.0122),
        "verdict": "first 3: parity with the close: run line Brier -0.000 [-0.012, +0.012] over 168 games",
        "verdict_class": VERDICT_PARITY,
        "source": _MLB_PREGAME_SOURCE,
    },
    ("mlb", "totals", "first3", PHASE_PREGAME): {
        "sample_games": 163,
        "seasons": "2026-08-31..09-13 pregame",
        "brier_model": 0.23789, "brier_market": 0.25052, "diff": -0.0126, "ci95": (-0.0267, 0.0022),
        "verdict": "first 3: parity with the close: totals Brier -0.013 [-0.027, +0.002] over 163 games; not confirmed out of sample",
        "verdict_class": VERDICT_PARITY,
        "source": _MLB_PREGAME_SOURCE,
    },
    ("mlb", "totals", "first1", PHASE_PREGAME): {
        "sample_games": 168,
        "seasons": "2026-08-31..09-13 pregame",
        "brier_model": 0.25228, "brier_market": 0.25331, "diff": -0.0010, "ci95": (-0.0116, 0.0098),
        "verdict": "first inning: parity with the close: over/under 0.5 Brier -0.001 [-0.012, +0.010] over 168 games",
        "verdict_class": VERDICT_PARITY,
        "source": _MLB_PREGAME_SOURCE,
    },
    # ---- MLB PROPS the hitter calibration does not cover, PREGAME ----------------------
    # `mlb_prop_calibration.skill_note` returns None for these, so the row fell to
    # "never backtested". Every projection in the window was RE-SIMULATED after the
    # games (`daily_summary` rebuilds nightly), with player stats carrying no date
    # cutoff: "loses" is robust, "parity" is an upper bound. `sample_games` counts
    # starts / player-games; the CI resamples games.
    ("mlb", "outs", "full", PHASE_PREGAME): {
        "sample_games": 196,
        "seasons": "2026-09-06..09-13 pregame, post 09-04 refit",
        "brier_model": 0.2801, "brier_market": 0.2437, "diff": 0.036, "ci95": (0.006, 0.068),
        "verdict": "loses to the de-vigged market: Brier +0.036 [+0.006, +0.068] over 196 starts; starters projected ~7% too long",
        "verdict_class": VERDICT_LOSES,
        "source": _MLB_PROPS_SOURCE,
        "admission_checked": "2026-09-14 served shortlist: all 33 outs rows fair_method=consensus",
    },
    ("mlb", "earned_runs", "full", PHASE_PREGAME): {
        "sample_games": 200,
        "seasons": "2026-09-06..09-13 pregame, post 09-04 refit",
        "brier_model": 0.2597, "brier_market": 0.2430, "diff": 0.017, "ci95": (0.001, 0.033),
        "verdict": "loses to the de-vigged market: Brier +0.017 [+0.001, +0.033] over 200 starts; biased high ~13%",
        "verdict_class": VERDICT_LOSES,
        "source": _MLB_PROPS_SOURCE,
        "admission_checked": "2026-09-14 served shortlist: all 19 earned_runs rows fair_method=consensus",
    },
    ("mlb", "strikeouts", "full", PHASE_PREGAME): {
        "sample_games": 193,
        "seasons": "2026-09-06..09-13 pregame, post 09-04 refit",
        "brier_model": 0.2621, "brier_market": 0.2452, "diff": 0.017, "ci95": (-0.009, 0.042),
        "verdict": "parity with the market: Brier +0.017 [-0.009, +0.042] over 193 starts; biased high ~13%",
        "verdict_class": VERDICT_PARITY,
        "source": _MLB_PROPS_SOURCE,
        "admission_checked": "2026-09-14 served shortlist: all 39 strikeouts rows fair_method=consensus",
    },
    ("mlb", "hits_allowed", "full", PHASE_PREGAME): {
        "sample_games": 192,
        "seasons": "2026-09-06..09-13 pregame, post 09-04 refit",
        "brier_model": 0.2599, "brier_market": 0.2496, "diff": 0.010, "ci95": (-0.014, 0.035),
        "verdict": "parity with the market: Brier +0.010 [-0.014, +0.035] over 192 starts; biased high ~11%",
        "verdict_class": VERDICT_PARITY,
        "source": _MLB_PROPS_SOURCE,
        "admission_checked": "2026-09-14 served shortlist: all 30 hits_allowed rows fair_method=consensus",
    },
    ("mlb", "walks_allowed", "full", PHASE_PREGAME): {
        "sample_games": 186,
        "seasons": "2026-09-06..09-13 pregame, post 09-04 refit",
        "brier_model": 0.2358, "brier_market": 0.2390, "diff": -0.003, "ci95": (-0.015, 0.010),
        "verdict": "parity with the market: Brier -0.003 [-0.015, +0.010] over 186 starts",
        "verdict_class": VERDICT_PARITY,
        "source": _MLB_PROPS_SOURCE,
        "admission_checked": "2026-09-14 served shortlist: all 7 walks_allowed rows fair_method=consensus",
    },
    ("mlb", "batter_hits_runs_rbis", "full", PHASE_PREGAME): {
        "sample_games": 1266,
        "seasons": "2026-09-06..09-13 pregame, post 09-04 refit",
        "brier_model": 0.2456, "brier_market": 0.2487, "diff": -0.003, "ci95": (-0.009, 0.003),
        "verdict": "parity with the market: Brier -0.003 [-0.009, +0.003] over 1,266 player-games; biased high ~15%",
        "verdict_class": VERDICT_PARITY,
        "source": _MLB_PROPS_SOURCE,
        "admission_checked": "2026-09-14 served shortlist: all 103 batter_hits_runs_rbis rows fair_method=consensus",
    },
    # ---- NCAAF, LIVE --------------------------------------------------------------
    # NCAAF PREGAME is not here on purpose: `ncaaf.game_projections` attaches its own
    # note, and a producer's note outranks this table.
    ("ncaaf", "totals", "full", PHASE_LIVE): {
        "sample_games": 75,
        "seasons": "2026 weeks 1-2 live",
        "mae_model": 10.28,
        "mae_market": 8.40,
        "diff": 1.88,
        "ci95": (0.79, 3.04),
        "verdict": "live: loses to the live line, total MAE +1.9 [+0.8, +3.0] pts over 75 games, in every game phase",
        "verdict_class": VERDICT_LOSES,
        "source": _FOOTBALL_SOURCE + "; live_gameline_ledger",
    },
    ("ncaaf", "spreads", "full", PHASE_LIVE): {
        "sample_games": 75,
        "seasons": "2026 weeks 1-2 live",
        "mae_model": 9.44,
        "mae_market": 8.93,
        "diff": 0.51,
        "ci95": (-0.40, 1.40),
        "verdict": "live: parity with the live line, margin MAE +0.5 [-0.4, +1.4] pts over 75 games",
        "verdict_class": VERDICT_PARITY,
        "source": _FOOTBALL_SOURCE + "; live_gameline_ledger",
    },
    ("ncaaf", "h2h", "full", PHASE_LIVE): {
        "sample_games": 76,
        "seasons": "2026 weeks 1-2 live",
        "brier_model": 0.078,
        "brier_market": 0.092,
        "diff": -0.014,
        "ci95": (-0.031, 0.002),
        "verdict": "live: parity with the market, Brier -0.014 [-0.031, +0.002] over 76 games",
        "verdict_class": VERDICT_PARITY,
        "source": _FOOTBALL_SOURCE + "; live_gameline_ledger",
    },
    # ---- NFL, PREGAME (regular season) ----------------------------------------------
    # `nfl_preseason_calibration` answers for the PRESEASON profile only; regular-season
    # game rows carried no note. Week 1 is 15 games -- the verdict says so on the row.
    ("nfl", "spreads", "full", PHASE_PREGAME): {
        "sample_games": 15,
        "seasons": "2026 week 1, after the rating-units fix",
        "mae_model": 12.59,
        "mae_market": 10.80,
        "diff": 1.79,
        "ci95": (0.09, 3.49),
        "verdict": "week 1 only: loses to the close, margin MAE +1.8 [+0.1, +3.5] pts over 15 games; underpowered",
        "verdict_class": VERDICT_LOSES,
        "source": _FOOTBALL_SOURCE,
    },
    ("nfl", "totals", "full", PHASE_PREGAME): {
        "sample_games": 15,
        "seasons": "2026 week 1, after the rating-units fix",
        "mae_model": 14.94,
        "mae_market": 12.37,
        "diff": 2.57,
        "ci95": (0.35, 4.67),
        "verdict": "week 1 only: loses to the close, total MAE +2.6 [+0.4, +4.7] pts over 15 games; underpowered",
        "verdict_class": VERDICT_LOSES,
        "source": _FOOTBALL_SOURCE,
    },
    ("nfl", "h2h", "full", PHASE_PREGAME): {
        "sample_games": 15,
        "seasons": "2026 week 1, after the rating-units fix",
        "brier_model": 0.260,
        "brier_market": 0.214,
        "diff": 0.046,
        "ci95": (-0.012, 0.101),
        "verdict": "week 1 only: parity with the close, Brier +0.046 [-0.012, +0.101] over 15 games; underpowered",
        "verdict_class": VERDICT_PARITY,
        "source": _FOOTBALL_SOURCE,
    },
}


def _norm(value: Any) -> str:
    return str(value or "").strip().lower()


# ---- SCORING: how far a measured loss moves a row's Layer 2 score ------------------
#
# `[2026-09-14, user decisions: "Category now, buckets next", "Scale by measured loss",
# "Switch directly"]`. The multiplier folds into the score's RELIABILITY, so it moves
# ranking, caps and which rows get staked, and never admission (`value_pct`) or stake
# size (the sizer does not read the score).
#
# ONLY AN ESTABLISHED LOSS MOVES A SCORE. `established_loss_rel` is the CI's LOWER
# bound divided by the market's own error (Brier or MAE), so Brier and point markets
# share one unit-free scale. Parity has a lower bound below zero and moves nothing; a
# borderline loss barely moves; a clear one moves more.
#
# GAIN AND FLOOR ARE A TUNING CHOICE, NOT A MEASUREMENT: a 10% established loss halves
# the score, and no category is discounted below half. The strongest measured loss at
# the time of writing (NCAAF pregame totals, 9.7%) lands near the floor.
SKILL_GAIN = 5.0
SKILL_FLOOR = 0.5


def established_loss_rel(entry: Mapping[str, Any]) -> float | None:
    """The relative loss the CI's lower bound establishes, or None if unscoreable."""
    ci = entry.get("ci95")
    market = entry.get("brier_market")
    if market is None:
        market = entry.get("mae_market")
    try:
        lower = float(ci[0])  # type: ignore[index]
        market_value = float(market)  # type: ignore[arg-type]
    except (TypeError, ValueError, IndexError, KeyError):
        return None
    if not math.isfinite(lower) or not math.isfinite(market_value) or market_value <= 0:
        return None
    return round(max(0.0, lower) / market_value, 5)


def skill_reliability(note: Any) -> float:
    """The score multiplier a row's `model_skill` note earns: 1.0 unless a loss is established.

    1.0 for an unmeasured note, a note without `established_loss_rel` (a comparison
    against something other than the market, e.g. NFL preseason correlation or the MLB
    hitter notes' constant baseline), and any malformed value. Unknown must not be
    punished with an invented midpoint any more than it may be rewarded with one.
    """
    if not isinstance(note, Mapping):
        return 1.0
    if _norm(note.get("status")) != "measured":
        return 1.0
    try:
        loss = float(note.get("established_loss_rel"))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 1.0
    if not math.isfinite(loss) or loss <= 0:
        return 1.0
    return max(SKILL_FLOOR, 1.0 - SKILL_GAIN * loss)


def projection_phase(projection: Mapping[str, Any]) -> str:
    """`live` only when the projection itself knows the game state."""
    return PHASE_LIVE if projection.get("live_aware") else PHASE_PREGAME


def skill_note(
    *, sport: Any, market: Any, segment: Any = "full", phase: str = PHASE_PREGAME
) -> dict[str, Any] | None:
    """The compact per-row note for a measured market, or None.

    None is load-bearing, as in `mlb_prop_calibration.skill_note`: the caller
    then stamps `unmeasured`, which is the honest answer, instead of this
    module inventing one. No `status` key -- `projection_skill` adds it, so
    there is one place that decides what `measured` means.
    """
    key = (_norm(sport), _norm(market), _norm(segment) or "full", _norm(phase))
    entry = MEASURED_MARKET_SKILL.get(key)
    if not entry:
        return None
    return {
        "correlation": entry.get("correlation"),
        "sample_games": entry["sample_games"],
        "seasons": entry["seasons"],
        "verdict": entry["verdict"],
        "verdict_class": entry["verdict_class"],
        "basis": NOTE_BASIS,
        # The one number Layer 2 scoring reads (`skill_reliability`). None when the
        # entry has no CI against the market, which scores as 1.0.
        "established_loss_rel": established_loss_rel(entry),
    }
