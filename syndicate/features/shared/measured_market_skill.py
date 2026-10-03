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
_NFL_PROPS_PRICE_SOURCE = (
    "scripts/backtest_nfl_props.py rate model vs the DE-VIGGED book price, scored on "
    "2024 (the only complete recent season -- 2025 wk10-21 props were never captured, "
    "on production either), with 2025 wk1-9 + 2026 as a second holdout. Both sides are "
    "priced on ~100% of rows in these eight markets, so this is a real de-vig and not "
    "an assumed hold. 2026-09-29."
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

_SOCCER_SOURCE_2026_10 = (
    "lane soccer-lines-props-backtest (2026-10-02): production soccer recommendation artifacts vs "
    "football-data.co.uk 2026-27 CLOSING average (Pinnacle close for MLS 1X2), proportional de-vig, "
    "vs ESPN finals, bootstrap over matches; scripts/soccer_season_audit/audit_games.py"
)

# (sport, market, segment, phase) -> entry.
MEASURED_MARKET_SKILL: dict[tuple[str, str, str, str], dict[str, Any]] = {

    # ---- NFL PLAYER PROPS vs the PRICE `[2026-09-29]` ----------------------------
    #
    # THE COMPARISON THE BACKTEST WAS NAMED FOR AND NEVER MADE. Its
    # `section_3_real_market_hit_rate` never reads `over_price`/`under_price`; it
    # scores the model's side CALL against the line, so its headline
    # `anytime_td hit_rate 0.774` is the MAJORITY-CLASS NULL (base rate 0.2209 ->
    # always-say-no = 0.7791). Nothing in it established that any of these models
    # beats a price, so every one of these markets read "never measured" while the
    # 2026-09-11 "Withhold, all sports" decision withheld their one-sided rows.
    #
    # ALL EIGHT LOSE, on every arm, with every CI clear of zero. De-biasing the
    # model (bias fitted on 2023, applied to 2024) narrows the gap -- passing_yards
    # +0.0395 -> +0.0302 -- and closes none of them. The 2025/2026 holdout is WORSE
    # across the board, so this is not a one-season artefact.
    #
    # ANYTIME TD IS ABSENT AND THAT IS STRUCTURAL, not an omission: 0 of 8,946 2024
    # rows carry an under price, so the market's fair probability cannot be recovered
    # at any sample size and a Brier comparison is impossible for it. It needs a
    # realised-ROI arm instead.
    ("nfl", "interceptions", "full", PHASE_PREGAME): {
        "superseded": "SUPERSEDED 2026-10-03 and NOT re-measured: the stored numbers below were taken through backtest_nfl_props.collect_raw, which omits production's zero-game imputation, AND before five model re-fits. On re-measurement this market had only 168 two-sided holdout rows, under the 200-row floor set before the data was seen, so no replacement reading exists. It also moved to a POISSON family in c3874b91, so the stored figures are doubly stale. Treat the numbers as unmeasured; the verdict CLASS is the only part still carried. See .syndicate/findings_2026-10-03_nfl_props_vs_price_recheck.md",
        "sample_games": 374,
        "seasons": "scored 2024, 374 quoted rows; holdout under-powered",
        "brier_model": 0.24966,
        "brier_market": 0.24204,
        "diff": 0.00763,
        "ci95": (0.00232, 0.01293),
        "verdict": "loses to the de-vigged market, Brier +0.0076 [+0.0023, +0.0129] over 374 quoted rows",
        "verdict_class": VERDICT_LOSES,
        "source": _NFL_PROPS_PRICE_SOURCE,
        "admission_checked": "2026-10-02 local-fleet served book grids 10-01..10-05: all 32 interceptions rows fair_method=consensus (layer2_board._resolve_fair, refresh-worker env)",
    },
    ("nfl", "passing_attempts", "full", PHASE_PREGAME): {
        "sample_games": 343,
        "seasons": "re-measured 2026-10-03 on PRODUCTION's estimator (player_rate, zero-game imputation ON) and PRODUCTION's probability (_nfl_prop_model_probability), scored on the 2025+2026 holdout; 343 two-sided rows",
        "brier_model": 0.2909,
        "brier_market": 0.25012,
        "diff": 0.04078,
        "ci95": (0.02143, 0.06012),
        "verdict": "loses to the de-vigged market, Brier +0.0408 [+0.0214, +0.0601] over 343 holdout rows (2025+2026)",
        "verdict_class": VERDICT_LOSES,
        "source": _NFL_PROPS_PRICE_SOURCE,
        "admission_checked": "2026-10-02 local-fleet served book grids 10-01..10-05: all 44 passing_attempts rows fair_method=consensus (layer2_board._resolve_fair, refresh-worker env)",
    },
    ("nfl", "passing_tds", "full", PHASE_PREGAME): {
        "superseded": "SUPERSEDED 2026-10-03 and NOT re-measured: the stored numbers below were taken through backtest_nfl_props.collect_raw, which omits production's zero-game imputation, AND before five model re-fits. On re-measurement this market had only 184 two-sided holdout rows, under the 200-row floor set before the data was seen, so no replacement reading exists. It also moved to a POISSON family in c3874b91, so the stored figures are doubly stale. Treat the numbers as unmeasured; the verdict CLASS is the only part still carried. See .syndicate/findings_2026-10-03_nfl_props_vs_price_recheck.md",
        "sample_games": 835,
        "seasons": "scored 2024, 835 quoted rows; holdout under-powered",
        "brier_model": 0.21705,
        "brier_market": 0.21004,
        "diff": 0.00701,
        "ci95": (0.00188, 0.01214),
        "verdict": "loses to the de-vigged market, Brier +0.0070 [+0.0019, +0.0121] over 835 quoted rows",
        "verdict_class": VERDICT_LOSES,
        "source": _NFL_PROPS_PRICE_SOURCE,
        "admission_checked": "2026-10-02 local-fleet served book grids 10-01..10-05: all 33 passing_tds rows fair_method=consensus (layer2_board._resolve_fair, refresh-worker env)",
    },
    ("nfl", "passing_yards", "full", PHASE_PREGAME): {
        "sample_games": 834,
        "seasons": "re-measured 2026-10-03 on PRODUCTION's estimator (player_rate, zero-game imputation ON) and PRODUCTION's probability (_nfl_prop_model_probability), scored on the 2025+2026 holdout; 834 two-sided rows",
        "brier_model": 0.30669,
        "brier_market": 0.24992,
        "diff": 0.05677,
        "ci95": (0.043, 0.07055),
        "verdict": "loses to the de-vigged market, Brier +0.0568 [+0.0430, +0.0706] over 834 holdout rows (2025+2026)",
        "verdict_class": VERDICT_LOSES,
        "source": _NFL_PROPS_PRICE_SOURCE,
        "admission_checked": "2026-10-02 local-fleet served book grids 10-01..10-05: all 142 passing_yards rows fair_method=consensus (layer2_board._resolve_fair, refresh-worker env)",
    },
    ("nfl", "receiving_yards", "full", PHASE_PREGAME): {
        "sample_games": 3116,
        "seasons": "re-measured 2026-10-03 on PRODUCTION's estimator (player_rate, zero-game imputation ON) and PRODUCTION's probability (_nfl_prop_model_probability), scored on the 2025+2026 holdout; 3116 two-sided rows",
        "brier_model": 0.28997,
        "brier_market": 0.24941,
        "diff": 0.04056,
        "ci95": (0.03327, 0.04785),
        "verdict": "loses to the de-vigged market, Brier +0.0406 [+0.0333, +0.0478] over 3116 holdout rows (2025+2026)",
        "verdict_class": VERDICT_LOSES,
        "source": _NFL_PROPS_PRICE_SOURCE,
        "admission_checked": "2026-10-02 local-fleet served book grids 10-01..10-05: all 462 receiving_yards rows fair_method=consensus (layer2_board._resolve_fair, refresh-worker env)",
    },
    ("nfl", "receptions", "full", PHASE_PREGAME): {
        "sample_games": 1179,
        "seasons": "re-measured 2026-10-03 on PRODUCTION's estimator (player_rate, zero-game imputation ON) and PRODUCTION's probability (_nfl_prop_model_probability), scored on the 2025+2026 holdout; 1179 two-sided rows",
        "brier_model": 0.26931,
        "brier_market": 0.24184,
        "diff": 0.02747,
        "ci95": (0.01753, 0.03741),
        "verdict": "loses to the de-vigged market, Brier +0.0275 [+0.0175, +0.0374] over 1179 holdout rows (2025+2026)",
        "verdict_class": VERDICT_LOSES,
        "source": _NFL_PROPS_PRICE_SOURCE,
        "admission_checked": "2026-10-02 local-fleet served book grids 10-01..10-05: 202 of 204 receptions rows fair_method=consensus; the 2 book_margin_model rows (single-book Over-only) are withheld by layer2_board._row_rests_on_unmeasured_model under this loses_to_market verdict",
    },
    ("nfl", "rushing_attempts", "full", PHASE_PREGAME): {
        "sample_games": 562,
        "seasons": "re-measured 2026-10-03 on PRODUCTION's estimator (player_rate, zero-game imputation ON) and PRODUCTION's probability (_nfl_prop_model_probability), scored on the 2025+2026 holdout; 562 two-sided rows",
        "brier_model": 0.27316,
        "brier_market": 0.24878,
        "diff": 0.02438,
        "ci95": (0.00909, 0.03967),
        "verdict": "loses to the de-vigged market, Brier +0.0244 [+0.0091, +0.0397] over 562 holdout rows (2025+2026)",
        "verdict_class": VERDICT_LOSES,
        "source": _NFL_PROPS_PRICE_SOURCE,
        "admission_checked": "2026-10-02 local-fleet served book grids 10-01..10-05: all 70 rushing_attempts rows fair_method=consensus (layer2_board._resolve_fair, refresh-worker env)",
    },
    ("nfl", "rushing_yards", "full", PHASE_PREGAME): {
        "sample_games": 1463,
        "seasons": "re-measured 2026-10-03 on PRODUCTION's estimator (player_rate, zero-game imputation ON) and PRODUCTION's probability (_nfl_prop_model_probability), scored on the 2025+2026 holdout; 1463 two-sided rows",
        "brier_model": 0.27934,
        "brier_market": 0.24993,
        "diff": 0.02941,
        "ci95": (0.01969, 0.03913),
        "verdict": "loses to the de-vigged market, Brier +0.0294 [+0.0197, +0.0391] over 1463 holdout rows (2025+2026)",
        "verdict_class": VERDICT_LOSES,
        "source": _NFL_PROPS_PRICE_SOURCE,
        "admission_checked": "2026-10-02 local-fleet served book grids 10-01..10-05: all 235 rushing_yards rows fair_method=consensus (layer2_board._resolve_fair, refresh-worker env)",
    },
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
    # RE-MEASURED 2026-10-03 (lane `soccer-skill-registry-line-weighting`, readings from lane
    # `soccer-lines-props-backtest`, `.syndicate/findings_2026-10-02_soccer_lines_props_backtest.md`):
    # 07-22..09-20 (MLS to 09-30), 4-6x the 09-13 samples. The totals entry FLIPPED: it read parity
    # on 194 matches (+0.010 [-0.004, +0.024]) and loses on 492. Final artifacts were rebuilt after
    # kickoff; on 165 matches with a genuine pre-kickoff build the 1X2 Brier moved 0.6243 -> 0.6230,
    # so the verdicts are not a rebuild artefact. A leak can only flatter the model.
    ("soccer", "h2h", "full", PHASE_PREGAME): {
        "sample_games": 671,
        "seasons": "2026-07-22..09-20 pregame (MLS to 09-30), 10 leagues",
        "brier_model": 0.6207,
        "brier_market": 0.5921,
        "diff": 0.0285,
        "ci95": (0.0169, 0.0411),
        "verdict": "loses to the de-vigged close: 1X2 Brier +0.029 [+0.017, +0.041] over 671 matches; under-prices favourites",
        "verdict_class": VERDICT_LOSES,
        "source": _SOCCER_SOURCE_2026_10,
    },
    ("soccer", "totals", "full", PHASE_PREGAME): {
        "sample_games": 492,
        "seasons": "2026-07-22..09-20 pregame, Europe (no MLS O/U close), O/U 2.5",
        "brier_model": 0.2387,
        "brier_market": 0.2293,
        "diff": 0.0095,
        "ci95": (0.0032, 0.0157),
        "verdict": "loses to the de-vigged close: O/U 2.5 Brier +0.010 [+0.003, +0.016] over 492 matches; trails this season's scoring",
        "verdict_class": VERDICT_LOSES,
        "source": _SOCCER_SOURCE_2026_10,
    },
    ("soccer", "spreads", "full", PHASE_PREGAME): {
        "sample_games": 458,
        "seasons": "2026-07-22..09-20 pregame, closing main Asian handicap line",
        "brier_model": 0.2696,
        "brier_market": 0.2487,
        "diff": 0.0208,
        "ci95": (0.0082, 0.0340),
        "verdict": "loses to the close: Asian handicap Brier +0.021 [+0.008, +0.034] over 458 matches",
        "verdict_class": VERDICT_LOSES,
        "source": _SOCCER_SOURCE_2026_10,
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

# ALIASES `[2026-10-03, user decision, lane soccer-skill-registry-line-weighting]`. The board names the
# same soccer market three ways: the alternate-line keys (`totals_alt`, `spreads_alt`) and `h2h_3_way`
# read "unmeasured" because the lookup is an exact key. They are the same model and the same
# measurement (taken at the main line; an alternate line is the same distribution read at another
# point). ADMISSION CANNOT CHANGE: `layer2_board._row_rests_on_unmeasured_model` withholds a one-sided
# row whose note is unmeasured OR `loses_to_market` alike, so moving these keys from unmeasured to a
# LOSES verdict re-admits nothing.
_SOCCER_ALIAS_ADMISSION = (
    "2026-10-03: aliased verdict is loses_to_market; layer2_board._row_rests_on_unmeasured_model treats "
    "loses_to_market exactly as unmeasured for one-sided rows, so no row's admission can change"
)
for _alias, _base in (("totals_alt", "totals"), ("spreads_alt", "spreads"), ("h2h_3_way", "h2h")):
    _entry = dict(MEASURED_MARKET_SKILL[("soccer", _base, "full", PHASE_PREGAME)])
    _entry["seasons"] = _entry["seasons"] + f"; measured as '{_base}', applied to '{_alias}'"
    _entry["admission_checked"] = _SOCCER_ALIAS_ADMISSION
    MEASURED_MARKET_SKILL[("soccer", _alias, "full", PHASE_PREGAME)] = _entry
del _alias, _base, _entry


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
