# NCAAB live tier (P4) — what exists, what it rests on, what is owed

Phase P4 of `docs/ai_context/basketball_live_native_plan.md`. Lane
`ncaab-native-live-tier`. Written 2026-10-09.

**Status: the prerequisite-free half is built. The live lens itself is BLOCKED
on P1 (native resumable engine) and P2 (native `LiveGameState` incl. NCAAB),
neither of which had a lane when this was written.** Nothing here runs in
production yet: no module below is imported by a route, a loop or a job.

## What exists

| piece | file | what it is |
|---|---|---|
| league rules | `syndicate/features/shared/basketball_league_rules.py` | `LeagueRules` for nba / wnba / ncaab: periods, clock, shot clock, foul-out, team-foul bonus (college 1-and-1 at 7, double bonus at 10, per HALF with OT continuing the count), `regulation_elapsed_fraction`, and league-parametric rotation windows. |
| team model | `syndicate/features/ncaab/live_team_model.py` | the pregame prior the engine resumes from: possessions, ppp per side, points, total, margin, from the dated `team_ratings_<season>_asof_*.csv` tables. |
| input checklist | `scripts/ncaab_live_input_checklist.py` | engine standard section 1 for the team model; exits 1 on a consumed+unfed field or D-I coverage < 95%, 2 with no table. |
| pbp corpus | `scripts/build_ncaab_pbp_corpus.py` | one compact record per finished D-I game: every play (incl. directed subs, fouls, timeouts, wallclock, ESPN win prob), pregame open/close lines, team box rows. |
| corpus analysis | `scripts/ncaab_corpus_baseline.py` | coverage, walk-forward team-model grade, the in-game baseline to beat, and NCAAB's scoring shape. |

### For P1: what the NCAAB rules require of the engine

The vendored engine (`vendor/nba_betting_repo/src/nba_betting/sim/events.py`)
hardcodes four quarters. Each spot and its replacement:

- `for q in range(1, 5)` (:2059), `base_poss = 2*poss/4.0` (:1610) ->
  `rules.periods`, `rules.period_share(period)`.
- `_rotation_windows` (:179) -> `rules.rotation_window_flags(period, remaining, margin)`.
  For nba/wnba it reproduces the vendored function EXACTLY (full-grid test,
  `tests/test_basketball_league_rules.py`). NCAAB windows are PRIORS
  (`rotation_windows_fitted=False`), keyed to the under-16 / under-12 media
  timeouts; the corpus measures starter on-floor share by minute (below) and
  P2's `rotation_stints_history` should replace them.
- blowout gates `q >= 3` / `q >= 4` (:2104) -> `rules.regulation_elapsed_fraction() >= 0.5 / 0.75`.
  In NCAAB 0.75 is 10:00 left in the second half, which is not a period
  boundary. Testing the period number would never enter the late-blowout state.
- The vendored engine has NO team-foul counter, NO bonus and NO foul-out.
  `rules.bonus_free_throws()` / `expected_free_throw_points()` (a 1-and-1 is
  p + p^2, not 2p) / `rules.fouled_out()` are what P3's foul mechanisms use.

### Team model: rules it keeps

- **No leakage**: the table for a game is the newest with `as_of` STRICTLY
  before the game date.
- **Refusal by name**: an unrated team returns `NcaabPriorRefusal("team_unrated", ...)`;
  no table returns `no_ratings_table`. Never a league-average default.
- **Season convention**: tables use ESPN's year (season ENDS in it: 2025-26 is
  2026). `ncaab/sources.season_for_date` uses the START year. Do not mix them.
- **Preseason**: before this season's first table, last season's newest table
  regressed 30% to the mean (the producer's `PRIOR_REGRESSION`), flagged
  `prior_season_fallback`.
- `HOME_POINTS = 2.9` is the producer's walk-forward fit; it moves the margin,
  not the total. A test pins both constants to the producer.

## Pipeline trace (planned; file:line filled in when P1/P2 land)

```
live_lens_loop._LIVE_LENS_SPORTS += "ncaab"            (syndicate/features/shared/live_lens_loop.py:254)
  -> _LIVE_LENS_BUILDERS["ncaab"]                       (NEW, P4 after P1/P2)
    -> P2 native LiveGameState (ESPN summary/pbp)       (P2)
    -> live_team_model.prior_for_game(date, home, away) (syndicate/features/ncaab/live_team_model.py)
         reads <SYNDICATE_DATA_ROOT>/ncaab_source/data/processed/team_ratings_<season>_asof_<YYYYMMDD>.csv
         written by scripts/build_ncaab_team_ratings.py (local_production SCHEDULED_JOBS "ncaab-team-ratings" 10:45Z)
    -> native engine resume(rules=NCAAB, state, prior)  (P1)
  -> write_json_file(snapshot)  keyvalue, 8 MB cap      (refresh_state_store.py:594)
  -> live_gameline_join / board_enrichment._LIVE_GAMELINE_SPORTS += "ncaab"
```

Today `syndicate/features/ncaab/live_lens.py` (164 lines) only displays mirrored
`live_state_*.json` / `live_lines_*.json`; NCAAB is not in `_LIVE_LENS_SPORTS`.

**Props**: there is NO NCAAB player model in Syndicate (no player priors, no
prop pipeline for ncaab). The live tier is game lines only until one exists.

## Keyvalue budget — size it before opening week

The cap is 8 MiB (`SYNDICATE_KEYVALUE_MAX_BYTES`, `refresh_state_store.py:594`);
a write at or over it is refused with the line prefix
`[refresh_state_store] KEYVALUE_WRITE_REJECTED key=` — count rejections on that
prefix. The NBA lens was refused for 9 h on 2026-10-08 at 9.59 MB with 6 games
and fixed to 243 KB (`ac48cdcd`), i.e. ~40 KB per game.

NCAAB's 2025-26 opening day had **169** D-I events on the scoreboard
(2025-11-03, measured 2026-10-09). At NBA's post-fix density that is ~6.8 MB:
under the cap, with no headroom, before any growth. **Budget for the NCAAB
snapshot: <= 20 KB per game at 200 games (4 MB, half the cap)**, which means:
no per-player rows, no pbp history, no sim distributions in the snapshot —
summary numbers per game, full blocks only for games in progress, and a
size test over a synthetic 200-game slate before the builder is registered.

## Corpus and results

**Substrate:** a LOCAL corpus built 2026-10-09 by `build_ncaab_pbp_corpus.py`
from ESPN, at `C:	mp\syndicate-data
caab_source\data\pbp_corpus\pbp_corpus_2026.jsonl.gz`
(45 MB, 6,275 games; the full report is `C:	mp\syndicate-data
caab_corpus_baseline_2026.json`).
It is not on the fleet. These numbers describe ESPN's 2025-26 record, not
anything production computed. Re-run with
`py -3 scripts/ncaab_corpus_baseline.py --season 2026 --json-out <path>`.

### Coverage (2025-26, every finished D-I scoreboard event)

| phase | games | dates | pbp final == official | close total | ESPN WP | directed subs | OT |
|---|---|---|---|---|---|---|---|
| regular | 5,871 | 123 (11-03..03-08) | 5,865 | 5,332 | 5,871 | 5,871 | 300 |
| conf tournament | 299 | 14 | 299 | 299 | 299 | 299 | 19 |
| NCAA tournament | 67 | 12 | 67 | 67 | 67 | 67 | 2 |
| other postseason (NIT, Crown) | 38 | 10 | 38 | 38 | 38 | 38 | 5 |

25 events had no pbp and were skipped. Lines: the summary's pickcenter (DK) is empty early in the season;
ESPN BET from the core odds API fills those games.

### Pregame team model, walk-forward (both teams >= 5 prior games)

Ratings for each date are rebuilt with `compute_ratings` from the corpus's box rows strictly before it.
There is no 2024-25 prior table, so early-season ratings are thinner than the producer's.
Refusals (all phases): 711 `team_unrated` (almost all non-D-I opponents), 162 `no_ratings_table` (opening day), 765 under 5 games.

| phase | n | total bias | total RMSE (close) | margin RMSE (close) | final on model's side when model vs close >= 3 |
|---|---|---|---|---|---|
| regular | 4,239 | +1.13 | 17.54 (16.89) | 11.56 (11.17) | 49.8% of 2,111 |
| conf tournament | 294 | **+4.31** | 17.09 (15.97) | 10.29 (10.33) | 41.0% of 173 |
| NCAA tournament | 66 | +3.20 | 14.66 (13.92) | 11.91 (11.37) | 54.5% of 44 |

The close beats the team model on every phase's total. The model sides with the final at coin-flip
rates, so **there is no pregame totals edge here**. Conference tournaments total about 4 points under
the model; the season-phase rule applies.

### In-game baseline to beat: "resume at the prior's rate" (graded vs the FINAL)

Projected = current score + prior x (remaining / 2400). ML is a normal on the projected margin, with
sigma = 11.56 x sqrt(remaining share) (the regular season's pregame margin RMSE, in-sample).
ESPN's own win probability at the same play is the comparator. **The live close is not available**:
ESPN keeps pregame lines only.

| regular season (n = 4,239) | total bias | total MAE | margin MAE | Brier baseline | Brier ESPN |
|---|---|---|---|---|---|
| H1 10:00 | -2.80 | 12.16 | 8.17 | 0.1678 | 0.1654 |
| halftime | -4.18 | 10.27 | 7.08 | 0.1446 | 0.1424 |
| H2 10:00 | -4.86 | 8.23 | 5.43 | 0.1141 | 0.1128 |
| H2 5:00 | -4.58 | 6.83 | 4.03 | 0.0885 | 0.0872 |
| H2 2:00 | -4.38 | 5.73 | 2.86 | 0.0693 | 0.0687 |
| H2 1:00 | -3.96 | 4.98 | 2.23 | 0.0544 | 0.0561 |

Tournament phases are in the JSON. The populations are small: n = 294 conf, 66 NCAA, 38 other per checkpoint.
The P4 engine must beat this row by row, regular season and tournament separately.
The -4 to -5 total bias is the half split below. A flat rate cannot represent it.

### NCAAB scoring shape (regular season, n = 4,239; tournament in the JSON)

- **Second halves score +8.03 points more than first halves** (77.83 vs 69.80, SE 0.22;
  conf tournament +8.96, NCAA +5.05 +/- 1.87). The engine must produce this from bonus free throws and
  end-game fouling (`bonus_free_throws`, 1-and-1 at 7 per half), not from a flat pace.
- **Score-effect reversion**: H2 margin residual on H1 margin residual, slope **-0.187**
  (95% CI -0.214..-0.159). NBA real is -0.174; the NBA sim is -0.001. NCAAB has the same reversion
  the sim lacks.
- **Second-half scoring rate by margin state**, relative to the prior's per-minute rate:
  1.010 (margin 0-5), 1.059 (6-10), 1.052 (11-19), 1.047 (20+).
- **End-game fouling** (fouls per team-minute, trailing vs leading, last 2:00 of H2):
  margin 1-3: 0.99 vs 0.69; 4-6: **1.46 vs 0.63**; 7-10: **1.64 vs 0.61**; 11+: 0.60 vs 0.50.
  From 4:00 to 2:00 there is no asymmetry (all 0.41-0.48). Intentional fouling is a last-2:00 mechanism
  for trailing teams down 4-10.
- **Starter on-floor share by minute** (of the 10 starters, H1 minute 0..19 | H2 20..39):
  1.00 .99 .97 .89 .75 .63 .54 **.50** .53 .58 .63 .65 .67 .68 .67 .65 .65 .66 .66 .65 |
  .96 .94 .89 .80 .69 .62 .58 **.57** .59 .62 .65 .66 .67 .69 .69 .69 .69 .67 .64 .60.
  The bench wave bottoms at minute 7 of each half (elapsed ~420 s), later than the prior's
  `bench_stint` 240-480 s. Starters never return above ~0.69. The last two minutes FALL (blowouts
  empty benches). `rotation_windows_fitted` stays False until this is fitted against P2's stints.

## What is owed, in order

1. P1 + P2 land (their lanes). Then the NCAAB builder: resume the native engine
   under `NCAAB` from P2's state with `live_team_model.prior_for_game`; refuse
   by name when either is missing; register in `_LIVE_LENS_SPORTS` and
   `_LIVE_GAMELINE_SPORTS`.
2. The P4 backtest proper: the engine at the checkpoints above, against this
   corpus, beating the baseline below at each checkpoint, n per checkpoint,
   regular season separate from the tournament.
3. **The live close.** ESPN keeps pregame lines only (core odds provider 59
   keeps a single untimestamped last in-play quote, no movement history —
   probed 2026-10-09). Grading against the live close needs OddsAPI historical
   in-play snapshots at the checkpoint wallclocks (each play carries `wall`).
   That spends OddsAPI quota: a user decision.
4. Fit the NCAAB rotation windows from P2's stints (or this corpus's
   starter-share curve) and flip `rotation_windows_fitted`.
5. The live reading at opening week (early November 2026) on the local fleet:
   the served lens reads `live_resim`, edges are published, and 0
   `KEYVALUE_WRITE_REJECTED` lines over the slate.
6. Copy the corpus to the fleet's data root. It was built locally (see Corpus and results).
