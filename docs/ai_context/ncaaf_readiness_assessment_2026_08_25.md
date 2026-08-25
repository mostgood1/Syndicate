# NCAAF end-to-end readiness — measured 2026-08-25, four days before kickoff

> Scope: UI (compact + main game cards, MLB as reference), sim engine, this
> weekend's schedule and the sims against it, props pipeline, Layer 1 and
> Layer 2 board population, model backtesting.
>
> **Nothing in this document changed production.** It is an assessment.
>
> Evidence discipline: every number below is tagged `[prod]` (Render logs or
> deploy metadata), `[local]` (this checkout, which is a lossy mirror), or
> `[git]`. Where the two disagree, that is called out rather than reconciled.

---

## 0. The headline

**The board is real and the model runs. The market is not connected to it.**

51 games render with SmartSim 2.0 projections on every one, in production and
locally. Every downstream surface that needs a *price* — edges, candidates,
picks, props, Layer 1, Layer 2 — is at exactly zero, because the cards board's
market block is null on all 51 games.

Two independent causes, and they need separating because one is self-clearing
and the other is not:

1. **The odds sweep does not own NCAAF yet.** Correct behaviour, expires
   Fri 08-28. See §6.
2. **The cards board's market file has no producer on any service.** Does not
   expire. See §7. This is the one that will still be true on Saturday.

---

## 1. This weekend's schedule, and the sims against it

`load_games_season(2026)` → 888 games. Week 1 = 99 rows. `[local]`

| window | games | FBS-vs-FBS | projected |
|---|---|---|---|
| **2026-08-28 → 08-30 (this weekend)** | **8** | **8** | **8 of 8** |
| week 1 as the board serves it | 99 | 51 | 51 of 51 |

**All eight of this weekend's games are simmed.** Kickoffs 08-29 07:00–08-30
02:00 UTC. First is North Carolina @ TCU, 16:00Z, Aviva Stadium, Dublin.

Two coverage facts that the board does not show a reader:

- **"Week 1" spans ten days, 08-29 → 09-07.** Only 8 of the 51 are this
  weekend; **43 are 09-03 → 09-07** (30 on 09-05 alone). Every one of the 51
  carries the identical badge `WEEK 1` and no date, so on Saturday the board
  cannot distinguish today's 8 games from next weekend's 43. `[local]`
- **The FBS-only filter drops 48 of 99 week-1 games (48.5%)** — every
  FBS-vs-FCS matchup (`_smartsim2_standalone_rows`, cards.py:293). Defensible
  (no FCS ratings exist) but it costs nothing this weekend and half the slate
  from 09-05 onward.

### The artifact web is actually serving

`data/ncaaf_source/data/smartsim2_projections_2026_wk1.csv`, 51 rows,
`generated_at 2026-08-19T22:11:51Z`, committed `46ca8445` on 08-24, present in
web's live SHA `0e0017d7`. `[git]`

The refresh-worker regenerates it daily — `SEASON_PROJECTION_LAUNCHING
sport=ncaaf season=2026 week=1 reason=artifact_stale age_seconds=86552` at
2026-08-24T20:43:54Z `[prod]` — **into a file the web service never reads.**
`smartsim2_projections_*.csv` matches **0 of the 155 `HOT_ARTIFACT_PATTERNS`**
(fnmatch, both directions) and the git→bootstrap path is seed-only since
`32148cac`. So web serves the 08-19 vintage until someone commits and deploys.

The age arithmetic is also the good news: `age_seconds` sitting at one interval
rather than growing unbounded means the generator **is succeeding** on the
worker, i.e. `CFBD_API_KEY` is present there as a service env var (it is in no
`render.yaml`). `#458` looks resolved on the worker.

**Only week 1 exists.** No `smartsim2_projections_2026_wk2.csv` anywhere in git
or on disk. A new week is a new path, so bootstrap will carry it — but only
after someone commits it and deploys web.

---

## 2. The UI, against MLB

Both boards were rendered headless from this checkout at 1500×1100
(`/ncaaf/cards?week=1`, `/mlb/cards?date=2026-06-25`, both HTTP 200).

### Compact cards (the scoreboard strip)

NCAAF falls to `_scoreboard_strip_generic.html`. `_scoreboard_strip.html`
dispatches on `card_variant`, and only `mlb_main` and `soccer_main` have their
own — so this is inheritance, not a design.

| | MLB strip | NCAAF strip |
|---|---|---|
| status | `FINAL` + first pitch `11:10 AM` | `WEEK 1` — **no date, no kickoff time**, identical on all 51 |
| score | R/H/E linescore, both teams | none |
| logos | `<img>` per team | abbreviation text only — `logo_url` **is in the payload and unused** |
| market | `TOTAL · ML` chips | none |
| freshness | `Odds updated 6/25, 1:24 PM` | none |
| body | live line + sim lens | 3 model metrics + summary + panel title, and the summary's last sentence is **repeated verbatim** in the panel below it |

Two of the ~4 text blocks on every NCAAF compact card are spent saying a legacy
engine has no prediction. **The `PROJECTED TOTAL` tile is clipped at the card
edge** — its value renders half-cut on every card in the strip.

### Header band

- MLB: `9 games | 7 upcoming / 2 live` and `ML 9 | Tot 9 | Spr 9 | Odds 6/25,
  1:24 PM | Pitcher props 15 | Hitter props 158`, plus All/Official/Props/
  Live/Final filter pills.
- NCAAF: `Games 51 | Candidates 51 | Weeks 1 | Source SmartSim 2.0`. No market
  coverage counts, no odds timestamp, no filter pills.

`Candidates 51` is worth flagging on its own: production generated **0**
candidates from this board (§5). The header's "Candidates" is counting games,
not candidates — a field named for a quantity it does not hold, which is the
2026-08-21 `learnings.md` rule verbatim.

### Main cards

NCAAF has its own `_game_card_ncaaf.html` (352 lines vs MLB's 493), and it is
decent: kickoff **is** shown here (`SAT AUG 29, 11:00 AM CDT`), venue, week
badge, a Game Identity section, returning-production/portal blocks.

What it does not have, against MLB:

- MLB's `GAME TOTAL` / `MONEYLINE` tiles carry line, price and
  `Model | Market | Edge`. NCAAF's four market tiles are placeholders —
  `Source / Tier / Status / Priority` — because there is no price to put in them.
- No GAME / BOX SCORE / PROPS tabs. `shared_prop_rows` is empty on all 51.
- **Section 2 is titled `Enhanced Totals Engine` and contains SmartSim 2.0's
  numbers**, while the panel beside it says the Enhanced Totals Engine has no
  prediction for this game. Same failure mode as the header's `Candidates`.

### Sub-navigation parity

MLB carries 16 sub-tabs including 10 props/ladder surfaces (Pitcher/Hitter Top
Props, Top Props, HR/K/RFI Targets, Pitcher/Hitter Ladders, Market Accuracy,
Season Review). NCAAF carries 6 and **zero** props surfaces.

---

## 3. Sim engine

`scripts/football_sim_input_checklist.py` — **FAIL, 9 alarms.** `[local]`

- **9 feature blocks / 65 keys consumed; 0 of 3 production entrypoints pass a
  payload.** `generate_smartsim2_ncaaf_projections.py` constructs
  `SmartSim2SimulationInput` without `feature_generation_payload`, so every key
  `drive_priors.py` reads falls to a neutral default on every game. Each NCAAF
  game runs on **four rating scalars** plus a hardcoded
  `pace_seconds_per_play=24.0`.
- NCAAF Level-2 population is **UNMEASURED, not zero** — the checklist's
  feature loader returns 0 games from this checkout. The board builder returns
  51 from the same checkout, so these are different loaders and the checklist's
  NCAAF arm is measuring something the board does not use. Worth a look.
- Unfed on NFL (the measurable control): `advanced_metrics`,
  `defensive_metrics`, `offensive_metrics`, `pace`, `player_usage` all 0.0% of
  16 games. `defensive_metrics` is misrouted into `team_metrics`; `pace` is
  null at source.

**Do not read this as "wire the payload".** `state.md`'s domination result
(b=+0.990, w=−0.028 on 751 clean OOS games) says the payload path cannot supply
what is missing, and §10 of the strategy doc measured the payload at 4.1% of
margin SD against the ratings path's 17.2%. The checklist failing is a *truth*
about the engine, correctly reported; it is not a work order.

Calibration state, unchanged and worth restating because it bears on what the
board shows: **margins are calibrated** (SD 15.37 vs market 14.46, ratio 1.06);
**totals are not** (SD 5.77 vs 3.46, ratio **1.67**). Over-dispersed totals
manufacture edges — an inflated spread of projected totals crosses more lines by
further, and reads as conviction. That is exactly what would happen the moment a
total line is joined to these projections.

---

## 4. Props pipeline

**Zero rows, by design, and the design's own deadline has passed.**

`[prod] [intelligence] SPORT_PROPS_DONE sport=ncaaf pregame=0 live=0`

- `scripts/fetch_ncaaf_oddsapi_props_local.py` exists and is a faithful mirror
  of the NFL fetcher. Its docstring states plainly that it is **"NOT WIRED to
  any props page or board yet — this is intentional"**, and that the join
  should be built "once real market coverage is confirmed closer to the season
  (~2026-08-23 to 2026-08-30)". **That window opened two days ago.** Nobody has
  built the join.
- No caller anywhere: not in `refresh_odds_sources.py`, not in either worker,
  not in any `.ps1`. Only tests reference it.
- No `oddsapi_player_props_*.csv` exists locally.
- The planned join was to be built on season-to-date player rates from
  `syndicate/features/ncaaf/player_stats.py`. Its source snapshot,
  `player_game_stats`, has **never produced a file** — correctly, since no 2026
  games have been played. So even with odds in hand, **week 1 has no rate basis
  for a props ladder.** Props are realistically a week-3+ surface, not an
  opening-weekend one.

---

## 5. Layer 1 and Layer 2

### Layer 2 — zero candidates `[prod, 2026-08-25T14:21:27Z]`

```
[INTEL_TRACE] overview_counts   sport=ncaaf dashboard_games_count=51
                                data_health=partial live_count=0 pregame_count=0
[INTEL_TRACE] game_candidate_inputs blocks={betting:0, gameLens:0, gameMarkets:0,
                                game_market_recommendations:0, markets:5,
                                shared_prop_rows:0, shared_top_play_rows:6}
[intelligence] GAME_CANDIDATES_EXIT sport=ncaaf rows=0 elapsed_s=0.0
[INTEL_TRACE] candidate_generation generated=0 markets={} duration_ms=1.016
[INTEL_TRACE] odds_history_input  entry_count=0 present=false shard_key=2026_wk1
```

`markets: 5` is the key count, not a value count. Measured on the same board
`[local]`: **markets non-null 0 of 51, predictions non-null 0 of 51.** The
`markets` dict is `{moneyline:{home:null,away:null}, spread:{...null},
total:{line:null}, prices:{...null}, probabilities:{...null}}` on every game.

`predictions` being null on all 51 is separately notable: the NCAAF-specific
`metrics` / `panels` / `shared_top_play_rows` carry the SmartSim numbers fine,
but the **shared board contract's own `predictions` block is empty**. Any
cross-sport consumer reading the contract rather than the NCAAF card sees a
sport with no model. Same for `shared_game_state.startTime` — **0 of 51
populated**, while the card's panel prints the kickoff correctly.

### Layer 1 — no artifact

`/ncaaf/market-board` renders `0 games  0 markets  0 with a projection` and
`No games on this board. Reason: no_precomputed_grid_artifact`. `[local]`

The chain is empty at its first stage, and production says so:

```
[prod] [artifact_publisher] STREAM_PULL_ABSENT   path=ncaaf_source/tracking/book_quotes/2026-08-25.jsonl
[prod] [artifact_publisher] PULL_REPAIR_MISSING  path=ncaaf_source/tracking/book_quotes/2026-08-25.jsonl ok=False written=0
```

`build_ncaaf_market_board(1)` does return 51 games — with **0 odds rows in
total** across all of them. `[local]`

Second, independent Layer 1 problem: **the board is date-scoped and NCAAF is
week-scoped.** The picker sits on today's date with `← 2026-08-24` /
`2026-08-26 →` neighbours; there is no navigation that reaches 08-29.

---

## 6. Why the market is empty today — and why that part is self-clearing

```
[prod] 2026-08-25T14:23:45.771Z
[live_refresh_loop] SWEEP_OWNERSHIP_EXCLUDED date=2026-08-25
  kept=mlb,wnba,soccer
  dropped=nfl:not_in_SYNDICATE_ACTIVE_SPORTS ncaaf:not_in_SYNDICATE_ACTIVE_SPORTS
```

`SYNDICATE_ACTIVE_SPORTS` is **not in `render.yaml`** (0 matches) — it is a
service-level env var, so changing it would not fire `blueprint_sync`.

But it should not need changing. `#520` added a weekly carve-out:
`_weekly_sport_claimed_by_fast_tick(sport, date)` →
`sport_has_games_within(sport, date, horizon_days=1)` keeps nfl/ncaaf/ncaab on
the fast tick **on game days regardless of `SYNDICATE_ACTIVE_SPORTS`**.
Horizon is **1 = today and tomorrow**.

- 08-25: no NCAAF game within 08-25..08-26 → dropped. **Correct.**
- 08-28: 7 games on 08-29, inside the horizon → should be claimed.

**Verified that this mechanism actually fires in production**, rather than
assumed — the identical code path, same file, same live SHA, on NFL:

```
[prod] 2026-08-24T03:55:01Z .. 04:56:14Z  (repeating)
[live_refresh_loop] SWEEP_OWNERSHIP_WEEKLY_CLAIM sport=nfl kept=true
                    reason=claimed_by_fast_tick_despite_SYNDICATE_ACTIVE_SPORTS
```

live-odds-worker is on `620734fb`, whose `live_refresh_loop.py` is byte-identical
to this checkout's. So **NCAAF's exclusion today is the gate working, not a
defect, and it should self-arm on Fri 08-28.**

Two caveats worth having in hand rather than discovering on Saturday:

- **Horizon 1 means no line history before Friday.** No opening-line capture,
  no CLV baseline built across the week. The function's own docstring argues a
  day-of window "would start capturing too late to be worth much" — horizon 1
  is one day better than that, on a market that has been trading for months.
- The claim must be **read on 08-28**, not predicted. The token to grep is
  `SWEEP_OWNERSHIP_WEEKLY_CLAIM sport=ncaaf`.

---

## 7. The part that does *not* self-clear

**The cards board's market lines come from a file no service produces.**

`_smartsim2_standalone_market_lines` (cards.py:237) reads exactly one path:

```
data/ncaaf_source/data/cfbd_lines_{season}_wk{week}.json
```

- Written only by `scripts/fetch_ncaaf_market_lines.py` and
  `scripts/fetch_cfbd_lines.py`.
- **Both have zero callers.** Not in `refresh_odds_sources.py`, not in
  `run_refresh_worker.py`, not in `run_live_odds_refresh_worker.py`, not in any
  `.ps1`. Manual scripts only.
- **Zero `cfbd_lines_*.json` files exist in git**, at any SHA, and none on this
  checkout.
- **Not allowlisted** — so even if a worker produced one, it could not cross to
  web (0 NCAAF patterns in 155).

What the odds sweep *does* run for NCAAF is `refresh_ncaaf_oddsapi.py`, which
writes `recommendations_summary/` off the legacy predicted-totals CSVs — a 2025
artifact family that production already reports as absent for 2026:

```
[prod] [INTEL_TRACE] artifact_status sport=ncaaf data_health=missing artifact_exists=false
       artifact_paths=[.../recommendations_summary/week_1.json, .../index.json]
```

So the expected state on Saturday, if nothing changes: the sweep arms,
`book_quotes`/`book_grid` start filling, **Layer 1 may populate** — and the
**game cards' `markets` block stays null**, because it reads a different file on
a path with no producer. Layer 2 candidates are built from the cards board's
market block, so they would stay at zero too.

That is a prediction, and it is the single highest-value thing to check on
08-28/08-29 rather than believe.

---

## 8. Backtesting

The *design* here is the strongest work in the module. `grade_football_playability.py`
grades ATS against the **52.4% breakeven** rather than 50%, prints **every**
threshold rather than the best (it names its own multiplicity: 7 thresholds × 2
sports = 14 tests, ~0.7 false positives expected), uses **Wilson** intervals,
and reports the **underdog share** so an under-dispersed model biasing to one
side cannot read as skill. `/ncaaf/picks` renders the conclusion honestly, with
a pre-specified four-part re-open condition.

**But it cannot be reproduced from this repository.**

```
scripts/grade_football_playability.py:42   REPO = Path(r"C:\Users\tempadmin\OneDrive\Coding\Syndicate")
scripts/grade_football_model_weight.py:36  REPO = Path(r"C:\Users\tempadmin\OneDrive\Coding\Syndicate")
```

Run here, with `PYTHONPATH` set so the import still resolves:

```
NCAAF 2024 -- clean out-of-sample (2023 SP+ on 2024 games)  --  0 gradable games
NFL PRESEASON 2023+2024 -- leak-free by construction        --  0 gradable games
```

**Exit 0. No error. No warning.** The proximate cause is that the pick-ledger
CSVs the graders read (`{sport}_source/data/pick_ledger/pick_ledger_*.csv`) are
**untracked and absent** — `git ls-files | grep pick_ledger` returns only the
builder, the module and its test. The hardcoded path is a second, independent
barrier for anyone whose `sys.path` is not already set.

The consequence is not that the conclusions are wrong — they are stated with
n and CIs and are almost certainly right. It is that **the entire evidence base
for suppressing NCAAF picks lives on one laptop**, and re-running it anywhere
else produces a clean, plausible-looking zero rather than a failure. That is the
`model_engine_standard.md` unfed-input signature applied to the evidence layer
instead of the input layer.

---

## 9. Readiness, by surface

| surface | state | ready Saturday? |
|---|---|---|
| Schedule (this weekend) | 8 of 8 games present | **yes** |
| Sims against it | 8 of 8 projected, margins calibrated | **yes** |
| Main game cards | render, kickoff + venue + model | **yes**, with mislabels |
| Compact cards | generic strip, no time/score/logo/market, clipped tile | **degraded** |
| Sim engine inputs | 4 scalars; checklist FAILs, 9 alarms | **as designed** |
| Market on cards | 0 of 51 — no producer for `cfbd_lines_*` | **no** |
| Layer 1 | `no_precomputed_grid_artifact`; date-vs-week scoping | **no** |
| Layer 2 | `generated=0`, `rows=0` | **no** |
| Props | `pregame=0 live=0`; join never built; no rate basis | **no** |
| Picks | suppressed, correctly and legibly | **by design** |
| Backtests | not reproducible off one machine | **no** |
| Odds sweep ownership | gated off today, mechanism verified working | **expected 08-28** |

**Bottom line.** As a *projection* board for this weekend, NCAAF is ready: all
eight games, all simmed, margins calibrated. As a *betting* board it is not,
and the blocker is narrower than it looks — one artifact family
(`cfbd_lines_{season}_wk{week}.json`) with no producer on any service and no
allowlist entry, sitting between a working model and every priced surface
downstream.

---

## 10. What to check on 08-28 / 08-29 (reading list, not a work order)

1. `SWEEP_OWNERSHIP_WEEKLY_CLAIM sport=ncaaf` — did the carve-out fire?
2. `ncaaf_source/tracking/book_quotes/2026-08-29.jsonl` — is it being written?
3. `/ncaaf/api/cards?week=1` → `games[].markets.total.line` — still null?
4. `GAME_CANDIDATES_EXIT sport=ncaaf rows=` — still 0?
5. `/ncaaf/market-board?date=2026-08-29` — still `no_precomputed_grid_artifact`?

Items 3 and 4 are the ones §7 predicts will stay empty.
