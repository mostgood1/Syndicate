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

ADMISSION IS NOT THIS TABLE'S BUSINESS ANY MORE `[2026-10-05, user directive, lane
stop-market-withholding]`: "All lines are judged individually - models are tested
for accuracy but each bet is at the line level". A verdict here RANKS a row
(`skill_reliability` -> `layer2_board._apply_skill_reliability`); it never removes
one. The `admission_checked` strings on some entries record readings taken while
`layer2_board._row_rests_on_unmeasured_model` was still a gate (2026-09-11..10-05)
and are history, not a requirement.

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

_SOCCER_PROPS_PRICE_SOURCE = (
    "lane soccer-lines-props-backtest (2026-10-02), .syndicate/findings_2026-10-02_soccer_lines_props_backtest.md "
    "'Vs the book': production PRE-KICKOFF soccer recommendation builds vs captured OddsAPI prop prices "
    "(props/<date>.csv, 8 US books) vs ESPN box scores; appeared players only; flat 1u at the best price "
    "when model p > raw implied; match-bootstrap CI; scripts/soccer_season_audit/audit_props.py --asof"
)
_SOCCER_SCORER_RACE_SOURCE = (
    "lane soccer-scorer-race-grade (2026-10-05), .syndicate/findings_2026-10-05_soccer_scorer_race_grade.md: "
    "production scorer_race on PRE-KICKOFF builds vs OddsAPI first/last scorer prices from run dates before "
    "kickoff vs ESPN keyEvents goal order; flat 1u at the best price when model p > raw implied; match-bootstrap "
    "CI; scripts/soccer_season_audit/grade_scorer_race.py"
)

_NHL_SAVES_PRICE_SOURCE = (
    "lane nhl-saves-skill-registry (2026-10-05): scripts/nhl_saves_vs_book.py -- production-form SAVES proj_lambda "
    "(props harness arm prior_dfo: current engine incl. c29e1271 + de074a80, Daily Faceoff confirmed-starter overlay, "
    "as-of inputs) priced by production's Poisson at the line, vs OddsAPI HISTORICAL player_total_saves closes "
    "(3 min pre-start, us books, proportional two-sided de-vig, mean over books) vs boxscore saves; population = what "
    "production prices (the sim's starter, who played); game-clustered bootstrap"
)

# (sport, market, segment, phase) -> entry.
MEASURED_MARKET_SKILL: dict[tuple[str, str, str, str], dict[str, Any]] = {

    # ---- NHL GOALIE SAVES vs the PRICE `[2026-10-05]` ----------------------------
    #
    # LOSES, clearly. The mean probability matches the market (model 0.505, market 0.503,
    # realised over rate 0.529) and the loss is in the SPREAD: Brier 0.277 is worse than a
    # coin flip, i.e. the probabilities are overconfident. Production prices SAVES by Poisson
    # from the sim mean, which is narrower than real saves. A pricing-shape defect, not a
    # mean defect, so it is a lead for the props model, not something this table fixes.
    # Board key: the grid writes the CODE "SAVES", which normalises to "saves".
    ("nhl", "saves", "full", PHASE_PREGAME): {
        "sample_games": 435,
        "seasons": "2025-26 regular season, 56 harness dates (every 2nd date 10-08..01-31); 881 player-game-lines in 435 games; 139 lines on a goalie production would not price (not the sim's starter), 5 on goalies who did not play and 10 name-unmatched were excluded; CI is game-clustered",
        "brier_model": 0.2772,
        "brier_market": 0.24978,
        "diff": 0.02742,
        "ci95": (0.01616, 0.03883),
        "verdict": "loses to the de-vigged market, Brier +0.0274 [+0.0162, +0.0388], 881 lines / 435 games; Poisson spread overconfident",
        "verdict_class": VERDICT_LOSES,
        "source": _NHL_SAVES_PRICE_SOURCE,
    },

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
        "sample_games": 360,
        "seasons": "re-measured 2026-10-03 on PRODUCTION's estimator (player_rate, zero-game imputation ON) and PRODUCTION's probability (_nfl_prop_model_probability); holdout 2025 wk3-wk18 (16 weeks; wk10-18 recovered from the already-purchased book_quotes log, not re-bought); 360 observations (one per player-game-line), 360 player-game clusters; CI is cluster-robust",
        "brier_model": 0.24942,
        "brier_market": 0.24765,
        "diff": 0.00177,
        "ci95": (-0.00355, 0.00708),
        "verdict": "parity with the de-vigged market, Brier +0.0018 [-0.0036, +0.0071] over 360 player-game observations",
        "verdict_class": VERDICT_PARITY,
        "source": _NFL_PROPS_PRICE_SOURCE,
        "admission_checked": "2026-10-03 re-verified on the served 19:36:52Z and 20:54:39Z NFL artifacts: all interceptions rows carry fair_method=consensus, so layer2_board._row_rests_on_unmeasured_model (which requires book_margin_model) cannot fire for this market and no verdict change here can alter admission",
    },
    ("nfl", "passing_attempts", "full", PHASE_PREGAME): {
        "sample_games": 720,
        "seasons": "re-measured 2026-10-03 on PRODUCTION's estimator (player_rate, zero-game imputation ON) and PRODUCTION's probability (_nfl_prop_model_probability); holdout 2025 wk3-wk18 (16 weeks; wk10-18 recovered from the already-purchased book_quotes log, not re-bought); 720 observations (one per player-game-line), 358 player-game clusters; CI is cluster-robust",
        "brier_model": 0.28295,
        "brier_market": 0.2496,
        "diff": 0.03335,
        "ci95": (0.01664, 0.05375),
        "verdict": "loses to the de-vigged market, Brier +0.0333 [+0.0166, +0.0537] over 720 obs in 358 player-game clusters",
        "verdict_class": VERDICT_LOSES,
        "source": _NFL_PROPS_PRICE_SOURCE,
        "admission_checked": "2026-10-03 re-verified on the served 19:36:52Z and 20:54:39Z NFL artifacts: all passing_attempts rows carry fair_method=consensus, so layer2_board._row_rests_on_unmeasured_model (which requires book_margin_model) cannot fire for this market and no verdict change here can alter admission",
    },
    ("nfl", "passing_tds", "full", PHASE_PREGAME): {
        "sample_games": 393,
        "seasons": "re-measured 2026-10-03 on PRODUCTION's estimator (player_rate, zero-game imputation ON) and PRODUCTION's probability (_nfl_prop_model_probability); holdout 2025 wk3-wk18 (16 weeks; wk10-18 recovered from the already-purchased book_quotes log, not re-bought); 393 observations (one per player-game-line), 360 player-game clusters; CI is cluster-robust",
        "brier_model": 0.25725,
        "brier_market": 0.24498,
        "diff": 0.01227,
        "ci95": (0.00327, 0.02234),
        "verdict": "loses to the de-vigged market, Brier +0.0123 [+0.0033, +0.0223] over 393 obs in 360 player-game clusters",
        "verdict_class": VERDICT_LOSES,
        "source": _NFL_PROPS_PRICE_SOURCE,
        "admission_checked": "2026-10-03 re-verified on the served 19:36:52Z and 20:54:39Z NFL artifacts: all passing_tds rows carry fair_method=consensus, so layer2_board._row_rests_on_unmeasured_model (which requires book_margin_model) cannot fire for this market and no verdict change here can alter admission",
    },
    ("nfl", "passing_yards", "full", PHASE_PREGAME): {
        "sample_games": 1833,
        "seasons": "re-measured 2026-10-03 on PRODUCTION's estimator (player_rate, zero-game imputation ON) and PRODUCTION's probability (_nfl_prop_model_probability); holdout 2025 wk3-wk18 (16 weeks; wk10-18 recovered from the already-purchased book_quotes log, not re-bought); 1833 observations (one per player-game-line), 359 player-game clusters; CI is cluster-robust",
        "brier_model": 0.30281,
        "brier_market": 0.24944,
        "diff": 0.05337,
        "ci95": (0.0323, 0.07182),
        "verdict": "loses to the de-vigged market, Brier +0.0534 [+0.0323, +0.0718] over 1833 obs in 359 player-game clusters",
        "verdict_class": VERDICT_LOSES,
        "source": _NFL_PROPS_PRICE_SOURCE,
        "admission_checked": "2026-10-03 re-verified on the served 19:36:52Z and 20:54:39Z NFL artifacts: all passing_yards rows carry fair_method=consensus, so layer2_board._row_rests_on_unmeasured_model (which requires book_margin_model) cannot fire for this market and no verdict change here can alter admission",
    },
    ("nfl", "receiving_yards", "full", PHASE_PREGAME): {
        "sample_games": 6570,
        "seasons": "re-measured 2026-10-03 on PRODUCTION's estimator (player_rate, zero-game imputation ON) and PRODUCTION's probability (_nfl_prop_model_probability); holdout 2025 wk3-wk18 (16 weeks; wk10-18 recovered from the already-purchased book_quotes log, not re-bought); 6570 observations (one per player-game-line), 2039 player-game clusters; CI is cluster-robust",
        "brier_model": 0.28483,
        "brier_market": 0.24956,
        "diff": 0.03527,
        "ci95": (0.02524, 0.04122),
        "verdict": "loses to the de-vigged market, Brier +0.0353 [+0.0252, +0.0412] over 6570 obs in 2039 player-game clusters",
        "verdict_class": VERDICT_LOSES,
        "source": _NFL_PROPS_PRICE_SOURCE,
        "admission_checked": "2026-10-03 re-verified on the served 19:36:52Z and 20:54:39Z NFL artifacts: all receiving_yards rows carry fair_method=consensus, so layer2_board._row_rests_on_unmeasured_model (which requires book_margin_model) cannot fire for this market and no verdict change here can alter admission",
    },
    ("nfl", "receptions", "full", PHASE_PREGAME): {
        "sample_games": 2542,
        "seasons": "re-measured 2026-10-03 on PRODUCTION's estimator (player_rate, zero-game imputation ON) and PRODUCTION's probability (_nfl_prop_model_probability); holdout 2025 wk3-wk18 (16 weeks; wk10-18 recovered from the already-purchased book_quotes log, not re-bought); 2542 observations (one per player-game-line), 1980 player-game clusters; CI is cluster-robust",
        "brier_model": 0.26393,
        "brier_market": 0.23969,
        "diff": 0.02423,
        "ci95": (0.01887, 0.03356),
        "verdict": "loses to the de-vigged market, Brier +0.0242 [+0.0189, +0.0336] over 2542 obs in 1980 player-game clusters",
        "verdict_class": VERDICT_LOSES,
        "source": _NFL_PROPS_PRICE_SOURCE,
        "admission_checked": "2026-10-03 re-verified on the served 19:36:52Z and 20:54:39Z NFL artifacts: all receptions rows carry fair_method=consensus, so layer2_board._row_rests_on_unmeasured_model (which requires book_margin_model) cannot fire for this market and no verdict change here can alter admission",
    },
    ("nfl", "rushing_attempts", "full", PHASE_PREGAME): {
        "sample_games": 1177,
        "seasons": "re-measured 2026-10-03 on PRODUCTION's estimator (player_rate, zero-game imputation ON) and PRODUCTION's probability (_nfl_prop_model_probability); holdout 2025 wk3-wk18 (16 weeks; wk10-18 recovered from the already-purchased book_quotes log, not re-bought); 1177 observations (one per player-game-line), 845 player-game clusters; CI is cluster-robust",
        "brier_model": 0.27012,
        "brier_market": 0.24737,
        "diff": 0.02275,
        "ci95": (0.01088, 0.03561),
        "verdict": "loses to the de-vigged market, Brier +0.0227 [+0.0109, +0.0356] over 1177 obs in 845 player-game clusters",
        "verdict_class": VERDICT_LOSES,
        "source": _NFL_PROPS_PRICE_SOURCE,
        "admission_checked": "2026-10-03 re-verified on the served 19:36:52Z and 20:54:39Z NFL artifacts: all rushing_attempts rows carry fair_method=consensus, so layer2_board._row_rests_on_unmeasured_model (which requires book_margin_model) cannot fire for this market and no verdict change here can alter admission",
    },
    ("nfl", "rushing_yards", "full", PHASE_PREGAME): {
        "sample_games": 3102,
        "seasons": "re-measured 2026-10-03 on PRODUCTION's estimator (player_rate, zero-game imputation ON) and PRODUCTION's probability (_nfl_prop_model_probability); holdout 2025 wk3-wk18 (16 weeks; wk10-18 recovered from the already-purchased book_quotes log, not re-bought); 3102 observations (one per player-game-line), 978 player-game clusters; CI is cluster-robust",
        "brier_model": 0.28113,
        "brier_market": 0.24962,
        "diff": 0.03151,
        "ci95": (0.02798, 0.0525),
        "verdict": "loses to the de-vigged market, Brier +0.0315 [+0.0280, +0.0525] over 3102 obs in 978 player-game clusters",
        "verdict_class": VERDICT_LOSES,
        "source": _NFL_PROPS_PRICE_SOURCE,
        "admission_checked": "2026-10-03 re-verified on the served 19:36:52Z and 20:54:39Z NFL artifacts: all rushing_yards rows carry fair_method=consensus, so layer2_board._row_rests_on_unmeasured_model (which requires book_margin_model) cannot fire for this market and no verdict change here can alter admission",
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
    # ---- SOCCER PLAYER PROPS, PREGAME, vs the PRICE ---------------------------------
    # `[2026-10-05, lane layer2-unmeasured-per-line; user: "take over all three"]`. Until
    # 2026-10-05 these rows never reached the board (the removed unmeasured-model withhold
    # dropped 3,111 soccer prop rows on one build), so they read "never backtested" while a
    # reading existed. One-sided markets: 50 of 168,846 captured prices carry an UNDER, so
    # there is NO de-vigged market and no Brier comparison. The reading is FLAT ROI, 1u at the
    # best price, on the model's EV>0 side against the raw implied probability WITH vig, on
    # pre-kickoff builds only -- the bet the board would actually be showing.
    #
    # BOTH READ PARITY UNDER THIS TABLE'S RULE, and that is deliberate, not lenient. Only an
    # ESTABLISHED loss moves a score (`established_loss_rel`): for ROI that is the CI's
    # UPPER bound below zero. Anytime's point estimate is -29.5% but its CI reaches +0.8%;
    # SOT's reaches +31.1%. A weight taken from a point estimate would be the invented
    # midpoint `skill_reliability` refuses. Shots (-22.4% [-40.6, -1.7]) and assists DO
    # have readings but are NOT registered: no board row carries `player_shots` or
    # `player_assists` (an entry no row can reach is the failure the key-shape block
    # below describes).
    #
    # FIRST / LAST SCORER `[2026-10-05, graded by lane soccer-scorer-race-grade, bc51b24c]`:
    # the board's `scorer_race` probability, same at-the-price method, outcome = ESPN goal
    # order (own goals and shootouts excluded, DNP void), prices only from run dates BEFORE
    # kickoff. LAST scorer is the first soccer prop with an ESTABLISHED loss (CI wholly below
    # zero): it ranks at the floor. The finding attributes it to the race's time-reversal
    # assumption (late goals favour substitutes), which a fix should target.
    ("soccer", "player_goal_scorer_anytime", "full", PHASE_PREGAME): {
        "sample_games": 144,
        "seasons": "2026-27 pre-kickoff builds 07-22..09-30, all versions; 487 EV>0 bets over 144 matches; OVER-only prices, no de-vig possible",
        "roi_model": -0.295,
        "roi_ci95": (-0.537, 0.008),
        "bets": 487,
        "verdict": "at the price: no established loss, ROI on model EV>0 -29.5% [-53.7%, +0.8%] over 487 bets, 144 matches",
        "verdict_class": VERDICT_PARITY,
        "source": _SOCCER_PROPS_PRICE_SOURCE,
    },
    ("soccer", "player_shots_on_target", "full", PHASE_PREGAME): {
        "sample_games": 143,
        "seasons": "2026-27 pre-kickoff builds 07-22..09-30, all versions; 210 EV>0 bets over 143 matches; OVER-only prices, no de-vig possible",
        "roi_model": -0.071,
        "roi_ci95": (-0.413, 0.311),
        "bets": 210,
        "verdict": "at the price: no established loss, ROI on model EV>0 -7.1% [-41.3%, +31.1%] over 210 bets, 143 matches",
        "verdict_class": VERDICT_PARITY,
        "source": _SOCCER_PROPS_PRICE_SOURCE,
    },
    ("soccer", "player_first_goal_scorer", "full", PHASE_PREGAME): {
        "sample_games": 200,
        "seasons": "2026-27 pre-kickoff builds, 22 dates 07-22..09-30; 305 EV>0 bets over 116 of 200 graded matches; yes-only prices, no de-vig possible",
        "roi_model": -0.348,
        "roi_ci95": (-0.699, 0.126),
        "bets": 305,
        "verdict": "at the price: no established loss, ROI on model EV>0 -34.8% [-69.9%, +12.6%] over 305 bets, 200 matches",
        "verdict_class": VERDICT_PARITY,
        "source": _SOCCER_SCORER_RACE_SOURCE,
    },
    ("soccer", "player_last_goal_scorer", "full", PHASE_PREGAME): {
        "sample_games": 177,
        "seasons": "2026-27 pre-kickoff builds, 22 dates 07-22..09-30; 264 EV>0 bets over 105 of 177 graded matches; yes-only prices, no de-vig possible",
        "roi_model": -0.668,
        "roi_ci95": (-0.924, -0.315),
        "bets": 264,
        "verdict": "at the price: LOSES, ROI on model EV>0 -66.8% [-92.4%, -31.5%] over 264 bets, 177 matches",
        "verdict_class": VERDICT_LOSES,
        "source": _SOCCER_SCORER_RACE_SOURCE,
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
# point). (The admission note below dates from when unmeasured/losing one-sided rows were withheld;
# since 2026-10-05 nothing is withheld by verdict -- see the module docstring.)
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


# THE BOARD AND THIS TABLE SPELL THE SAME MARKET TWO WAYS, and `_norm` -- which is
# only `strip().lower()` -- never bridged them. The Layer 2 board names player props
# in display case (`'Receiving Yards'`); every key here is snake_case
# (`receiving_yards`). Measured 2026-10-03 on the fleet, production's own `skill_note`
# against the board's own strings at segment `'full'`, phase pregame:
#
#     'Receiving Yards' -> None      'receiving_yards' -> MATCH 3116
#     'Rushing Yards'   -> None      'passing_yards'   -> MATCH 834
#     'Passing Yards'   -> None
#
# That is 1,910 of 2,622 NFL rows on `layer2_shortlist_2026_10_01__nfl.json` matching
# nothing -- 850 prop rows stamped `unmeasured` while a measurement for them existed,
# and six entries no board row could reach. It survived because SINGLE-WORD board names
# (`Interceptions`, `Receptions`) normalise straight onto the key and DO match, so two
# of the eight NFL prop markets looked like the table was working.
#
# This is a key-SHAPE problem, not an alias problem, so it is fixed here at the one
# place that builds the key rather than per market. The soccer block above is the other
# kind: `totals_alt` -> `totals` maps DIFFERENT markets onto one measurement, which is a
# judgement call needing its own admission check. Spaces to underscores is not a
# judgement -- it is the same market, spelled for a human.
#
# ORDER MATTERS AND IS ADDITIVE: the exact normalised form is tried FIRST, so no lookup
# that resolved before can resolve differently now, and the fallback can only ever turn
# a MISS into a hit. A sport whose board already uses snake_case never reaches it.
def _market_key_candidates(market: Any) -> tuple[str, ...]:
    """The market spellings to try, exact form first. Never raises."""
    exact = _norm(market)
    bridged = exact.replace(" ", "_")
    if bridged == exact:
        return (exact,)
    return (exact, bridged)


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
    """The relative loss the CI's lower bound establishes, or None if unscoreable.

    An entry measured as REALISED ROI at the price (`roi_ci95`, one-sided markets with no
    de-vig) is already a relative loss per unit staked, so the established loss is how far
    the CI's UPPER bound sits below zero -- the same "only what the CI establishes" rule,
    with the sign flipped because a better model has a higher ROI and a lower Brier.
    """
    roi_ci = entry.get("roi_ci95")
    if roi_ci is not None and entry.get("brier_market") is None and entry.get("mae_market") is None:
        try:
            upper = float(roi_ci[1])  # type: ignore[index]
        except (TypeError, ValueError, IndexError, KeyError):
            return None
        if not math.isfinite(upper):
            return None
        return round(max(0.0, -upper), 5)
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
    sport_k = _norm(sport)
    segment_k = _norm(segment) or "full"
    phase_k = _norm(phase)
    entry = None
    for market_k in _market_key_candidates(market):
        entry = MEASURED_MARKET_SKILL.get((sport_k, market_k, segment_k, phase_k))
        if entry:
            break
    if not entry:
        return None
    # A SUPERSEDED entry is NOT a measurement, so it must not become a note. Its own
    # text says to treat the numbers as unmeasured, and returning them would let
    # `skill_reliability` discount a row by a figure the finding that wrote it calls
    # stale. This is not hypothetical: measured 2026-10-03, `Interceptions` is a single
    # word, so it already resolved under the old exact lookup and was discounting ~47
    # NFL board rows by a reading taken through an estimator production does not serve
    # and before five model re-fits. `None` here is the same honest answer the docstring
    # above describes -- the caller stamps `unmeasured`.
    if entry.get("superseded"):
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
