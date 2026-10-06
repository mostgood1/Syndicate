# DESIGN — Phase-aware NBA models: preseason / regular season / play-in / playoffs

**Lane** `nba-prop-calibration` (design only; implementation lanes proposed below). **Session** e0a3e383.
**Date** 2026-10-05. **Status:** design, nothing built beyond what is already live (§0).
**Asked by:** the user ("design the phase-aware NBA models"), following the user's preseason direction relayed by the
NCAAF session. **Audit this rests on:** findings_2026-10-02_nba_lines_props_backtest.md §"NBA season phase"
(b0b35e3c). Every file:line below comes from that audit.

---

## 0. What is already true (do not re-design)

- **Game lines serve the market in preseason.** Layer 2 serves NBA game lines through a per-line logit blend toward
  the de-vigged fair (`nba_game_projections._project_row`; `nba_prop_calibration.served_game_probability`). The
  weights are keyed on season phase from the cached ESPN scoreboard; preseason w = 0. Serving since 2026-10-05
  23:46:45Z; reading MET in deploys.md.
- **Props serve ~the book in every phase.** `nba_prop_book_blend.json` weights are mostly 0, as measured on the
  2025-26 regular season plus playoffs. That blend has **no phase key yet** (§3.1).
- **Elo and team rolling features are regular-season-only already.** `scrape_nba_api.py:96,183` keeps only `002`
  game ids. `player_logs.csv` is regular-season-only (`vendor/player_logs.py:234`), unless its fallback fires (§2.2).

**The principle.** The served PROBABILITY is already protected in every phase, because it leans on the market when
the model has no measured information. What the phase work fixes is (a) the **means and projections** the board
shows (minutes, points, margins), which are regular-season-shaped in preseason; and (b) **contamination**: preseason
data leaking into regular-season fits and windows, worst on opening night (2026-10-20). Both matter because a
measured model edge, if one ever appears, can only come from inputs that are right for the phase.

## 1. Season phase as a first-class field

### 1.1 One resolver, one vocabulary
`syndicate/features/shared/nba_season_phase.py` (NEW), with
`phase_for(event_id=None, commence_time=None, date=None) -> "preseason" | "regular" | "play_in" | "postseason" | None`.

Precedence:
1. ESPN `events[].season.type` from the sim's cached scoreboard (`_espn_cache/nba/scoreboard_<ymd>.json`). Today's
   resolver handles this per date.
2. The ESPN season-types date table for the season, cached once per season:
   `sports.core.api.espn.com/v2/sports/basketball/leagues/nba/seasons/<yr>/types`. Measured 2026-10-05: 2027 =
   Preseason 09-30..10-20 06:59Z, Regular 10-20 07:00Z..04-12, Play-In 04-12..04-17, Postseason 04-17..06-26.
   This works for future dates with no scoreboard cached yet.
3. OddsAPI sport key: `basketball_nba_preseason` means preseason. It is fetched today and DROPPED from rows
   (`vendor/odds_api.py:133-145`; `scripts/fetch_basketball_oddsapi_props_local.py:170-183,390-410`).
4. Otherwise `None`. **Unknown is never "regular".** Every consumer treats unknown as its most conservative branch.

ESPN codes: 1 = preseason, 2 = regular, **5 = play_in**, 3 = postseason. **Fix owed:** the shipped
`season_phase_for_date` maps only 1/2/3, so play-in reads as unknown today. The conservative weight still applies,
but the stamp is wrong.

### 1.2 Stamp it where rows are born
- `game_odds_<D>.csv`, `oddsapi_player_props_<D>.csv` and book_quotes: add `season_phase` (+ `sport_key`).
- `smart_sim_<D>_*.json`, `cards_sim_detail_<D>.json`, `props_predictions_<D>.csv`, `predictions_<D>.csv`:
  `season_phase` at the top level and per row.
- `boxscores_history.csv`, `rotation_stints_history`, `recon_*`: `season_phase` per game. The writers are date-based
  ESPN (`shared/basketball_boxscores_history.py:297-395`; `vendor/rotations_espn.py:512`); the ESPN event already
  carries the type.
- Layer 2 and market-board rows: `season_phase` (already on blended game rows).

A history file **without** the column is read as phase-unknown. Every phase-filtered reader treats unknown as
"exclude from regular-season fits". That is the contamination-safe default; old rows can be re-labelled from the
ESPN date table.

## 2. The partition rule (no cross-contamination)

**Rule:** a read of history for a game in phase P uses only rows of the phases its policy allows, explicitly. A
reader that cannot tell a row's phase excludes it.

| reader | file:line | policy for REGULAR | PRESEASON | PLAY-IN / POSTSEASON |
|---|---|---|---|---|
| rotation-history minutes (28-day lookback) | basketball_props_smart_sim.py:2324,2380; vendor rotations_espn.py:512 | regular only (this season), else prior-season regular | preseason only (this preseason) + prior-season regular as the role prior | postseason + regular, recency-weighted |
| sim minutes priors (21-day) | basketball_props_smart_sim.py:3403 -> vendor smart_sim.py:1600 | regular (player_logs) — already | same + preseason caps (§3.2) | regular + this postseason |
| prop calibration own_rates | nba_prop_calibration.py:82-85,236-239 | regular only; `season_start` from the ESPN table, not Aug 1 | not used (served ≈ book; §3.2) | postseason first, regular as prior |
| prop calibration prior | nba_prop_calibration.py:242-246 | prior-season regular — already | same | same |
| props bias calibration 7/30 days | refresh_nba_oddsapi_props.py:2998-2999; vendor props_calibration.py:50,187; shared/basketball_props_calibration.py:80-85,181-195 | regular dates only (window counts regular DAYS, not calendar days) | none (no calibration in preseason) | postseason dates; fall back to the last regular window |
| totals / game calibration | vendor cli.py:11017-11060 | regular only | none | postseason, fallback regular |
| availability K rule | wnba_sim_availability.py:85-114 | regular team games only (a preseason DNP is not evidence) | not applied (rest is the norm) | postseason + last regular games |
| team advanced stats | vendor advanced_stats_boxscores.py:150-162,344 | regular only | prior-season regular | postseason + regular |
| Elo / team rolling | vendor cli.py:12302-12372; features.py | regular — already; **add season-start regression** (elo.py has none) | prior-season end + regression, labelled | regular — already |
| player_logs fallback | vendor player_logs.py:293-298 | must NOT rewrite player_logs from all-phase boxscores_history; fail loud instead | — | — |

**Opening-night hazard (2026-10-20, time-bound):** on the opener the 28-day rotation lookback is 100% preseason. From
~10-08 own_rates switches to preseason-only data after 3 games. For the first 7 days the props bias windows hold
only preseason. These three are the **first** deliverable (§5, step 1). They must land and be verified before
10-20.

## 3. The four phase variants

### 3.1 Served probability (all phases): per-phase blend weights
- Game lines: already phase-keyed. Preseason 0; regular = measured (total 0.05); play-in and postseason = the
  regular weights until measured (§4).
- Props: add the same `phase` block to `nba_prop_book_blend.json`. Preseason all 0, so the book is served (books post
  almost no preseason props; 0 player markets on 10-04..06). Regular = the current refit. Postseason = regular until
  measured.
- **Refit regular weights on regular-season lines only.** Today's 336,418 lines include the playoffs.

### 3.2 PRESEASON: explicit adjustments, not a fitted model
Data: **71 preseason games on 16 dates in 2025** (ESPN, counted 2026-10-05), plus 2026's so far. That is enough to
fit SHAPES (minutes by role), not a prop or line model, and books post almost no preseason props to grade against.
- **Minutes model.** Fit on 2025 preseason box scores, as-of: minutes by role tier. Role is last season's
  regular-season minutes rank within the team (starter / rotation / fringe / new). Expected preseason minutes =
  tier mean (predicted: starters ~20-24, rotation ~18-22, fringe ~10-16). Add P(DNP) per tier, which models stars
  sitting entire games, and a deeper pool: max_keep 15-17 instead of 13 (`basketball_props_smart_sim.py:1799`).
- **Rates.** Last regular season's per-minute rates, shrunk toward league average (preseason effort and lineups
  differ). Means = adjusted minutes × rates.
- **Game sim.** Margins compressed toward 0 (talent gaps shrink when starters sit), with totals from the preseason
  minutes mix. Measured target (§4, H-P2). Served p stays at the market (w 0).
- **Never fed back:** preseason outputs, recon and calibration never enter regular-season windows (§2).

### 3.3 REGULAR SEASON: today's models with clean inputs
- Inputs per §2 (regular-only windows, ESPN-table season start, Elo season-start regression).
- Prop calibration (rate shrink, season blend, width): **refit on regular-season rows only**. Today's constants were
  fit on regular season + playoffs (`backtest_nba_lines_props.py:460`). The availability rule (K=2) only if the
  running paired re-run shows a gain.
- Served p: the per-phase blend (§3.1).

### 3.4 PLAY-IN and POSTSEASON: shorter rotations, heavier starters
Data: 2026 postseason box scores (`boxscores_history.csv` 2026-04-20..06-13, 2,052 rows) + play-in 04-14..17; the
calibration test set already includes playoff rows.
- **Minutes.** Pool max_keep 9-10; starters' minutes from the last 10 postseason/regular games, recency-weighted.
  Fit the postseason minutes uplift per role tier on 2026.
- **Calibration.** Postseason-specific width (`sd_scale`) and blend, fit on playoff rows, if the CI separates from
  the regular constants. Otherwise the regular constants (one model, labelled).
- Play-in = postseason minutes rules (elimination games), regular-season rates.

## 4. Measurement, per phase (pre-registered; nothing ships without it)

| id | hypothesis | substrate | refuted if |
|---|---|---|---|
| H-P1 | Preseason starter minutes (tier 1) average <= 24 and P(DNP) >= 0.15 in 2025 preseason; the current sim projects >= 28 | 71 games 2025 (ESPN box) vs the as-of sim (re-run harness, preseason dates) | starters avg > 26 or the sim already within 2 min |
| H-P2 | Preseason sim margin |error| exceeds the market's by >= 3 pts and the sim total is biased >= +5 | 2025 preseason game lines (OddsAPI historical, ~600 credits est.) + finals; + 2026 games as they finish | gap < 1.5 pts and bias < 2 |
| H-P3 | The phase-aware preseason minutes model cuts preseason minutes MAE by >= 25% vs the current sim | same as H-P1, held out by date | < 10% |
| H-R1 | Regular-only refit of the prop calibration differs from the regular+playoff constants by more than its CI, OR it doesn't (then keep one set) | the existing harness, regular rows | — (a choice, recorded either way) |
| H-R2 | Excluding preseason from own_rates / bias windows improves the first 3 regular-season weeks' prop MAE | 2025-26 as-of: windows with vs without 2025 preseason, Oct 21..Nov 10 2025 | no difference within CI |
| H-O1 | Postseason starter minutes exceed the regular-season sim projection by >= 3 min; a postseason minutes rule cuts minutes MAE | 2026 playoffs, as-of re-run (playoff dates) | uplift < 1.5 min |
| H-B1 | The OOS book-blend weight is 0 in preseason and postseason too (no information beyond the book) | backfill lines by phase | w > 0 with a CI excluding 0 |

Grading and registry stay **per phase**:
- `measured_market_skill.py:117` and `daily_optimizer.py:14` key on `phase` = pregame/live today. Add
  `season_phase` as a key dimension (`nba|market|segment|pregame|preseason`), so a preseason result can never
  certify a regular-season cell.
- The backtest's `phase_of` already splits regular vs playoff; add preseason.

## 5. Delivery order (each step: claim, pre-register, test reachability off != on, measure, then ship)

1. **Before 2026-10-20 (opening night), contamination guards:**
   - the phase resolver + stamps (§1);
   - regular-only filters for the rotation lookback, own_rates (+ ESPN-table season start) and the 7/30-day bias
     windows;
   - the player_logs fallback failing loud.
   Verify on the 10-20 sims: 0 preseason games in any regular-season window.
2. **Preseason minutes and means** (H-P1/H-P3), so the board's projected minutes and points are right for preseason.
   Useful for the rest of THIS preseason (through 10-19) and every one after. Served p unchanged (market).
3. **Prop blend phase block + regular-only refit** (§3.1, H-B1).
4. **Postseason rotation/minutes rules** (H-O1), before 2027-04-12.
5. **Registry keyed on season phase** (§4).
6. **Elo season-start regression** (game lines; measured on 2025-26 opening weeks).

**Ownership.** Steps 1-2 touch:
- basketball_props_smart_sim.py, rotations / boxscores_history writers, refresh_nba_oddsapi_props.py and
  props_calibration (several unclaimed);
- nba_prop_calibration.py (this lane).

Proposed: one new lane `nba-season-phase` (steps 1-3), opened when the user says go. Step 5 touches the shared
registry, so it gets its own lane.

## 6. What this design deliberately does NOT do

- **No market-wide withhold in any phase.** Every line stays on the board with its own probability; preseason leans
  on the market per line.
- **No preseason prop or line model fit:** 71 games and almost no preseason props.
- **No change to served probabilities beyond §3.1:** they are already at the market wherever the model has no
  measured information.
