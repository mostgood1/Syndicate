# What player ALTERNATE-line props would cost on OddsAPI — 2026-10-16

User 2026-10-16: "fetch alt lines, but we need to understand cost implications of this". READ-ONLY study: **no
OddsAPI call was made and nothing was turned on.** Runs/day are from the fleet's odds-refresh run reports (prop-fetch
steps, averaged 10-09..10-15 Central); events/run from the NFL/NCAAF raw files ~2:35 PM CT 10-16; floors from the
book-quote logs (they write only CHANGED prices, so they undercount what was billed).

**Billing used:** an event-odds call costs markets x regions, a `bookmakers` list of <= 10 books = 1 region; the repo
records billing per market RETURNED (`fetch_ncaaf_oddsapi_props_local.py:264,799`; vendor `odds_api.py:535-538`), so
every option-(a)/(b) figure below is an upper bound.

**Budget context:** 809,746 credits used on 10-06 and 2,250,566 on 10-16 (`log/2026-10-16.md:427`) -> ~144K/day
including a one-off ~159K backfill on 10-14 -> **~3.8-4.3M per 30 days, 75-86% of the 5M cap, before NBA's regular
season** (from 10-20; ledger projection up to ~20K/night, not measured). Cycle reset inferred ~10-01 (UNVERIFIED).

| sport | prop markets/event now | runs/day | events/run | prop credits/day now | alt keys | +(a) every run | +(b) once/event/day | +(c) sheet games, once |
|---|---|---|---|---|---|---|---|---|
| NFL | 9 (`fetch_nfl_oddsapi_props_local.py:38-48`) | 96 (44-61 off-days, 256 Sun) | 13-15 | 5.7K floor - 11.7K | 8 | 5.0-10.4K | 110 | 17 |
| NCAAF | 9 (~6 returned) | 93 (due events only) | Sat ~14, weekdays 2-4 | 2.3K floor - ~3.6K | <= 6 | 2.3-3.6K | 290 | 60 |
| MLB (postseason) | 12 in 2 calls | 65-77 | 1-2 | 0.8-1.4K | <= 9 | 0.65-1.1K | 18 | 9-18 |
| NHL | 5 (`local_nhl_odds.py:646`) | 109 (57-159) | ~13-15 | 1.4K floor - 8.2K | 4-5 | 1.4-8.2K | 75 | 38 |
| NBA | 13 | 116 | 1-3 now, ~7.5 in season | ~0 (preseason) | 11 | ~9.6K from 10-20 | 83 | 83 |
| Soccer | 8 + 2 game keys | ~440 league steps | — | ~18K (ledger 10-05) | 0 | 0 | 0 | 0 |

- **(a) every run: +19-33K/day = 0.57-0.99M per 30 days (11-20% of the cap)** — roughly doubles each sport's prop
  spend, and with NBA starting reaches or passes the cap. **Do not add alternate keys to the main market lists**;
  that IS option (a).
- **(b) once per event per day: ~+575/day, ~17K per 30 days, 0.35% of the cap.**
- **(c) cheat-sheet games only, once, late pregame (~60-90 min before start): ~+210/day, ~6.3K per 30 days, 0.13%
  of the cap.** Recommended: a separate call per game asking ONLY the alternate keys with the same 10-book list.
  NFL/NCAAF parsing already keeps each line separately (`is_ladder`); NHL already maps `*_alternate`
  (`local_nhl_odds.py:650-658`). Validate every key first — one invalid key 422s the whole combined call.

**Ladders that are already free** (several lines under the main key): soccer shots 98% of player/book pairs (up to
8 lines), shots on target 47%; NHL ~17% (SOG, points); MLB 17-25% (batter markets); NFL/NCAAF 0% — must be bought.

**Budget flag, not verified:** the NBA live tick (`nba/live_tick/tick.py:914-928`, live-odds-worker, ~40/h, no
switch) asks for every player market a game lists, alternates included, and keeps only one median line. Once NBA
props appear (10-20) it could spend ~15-20K/day by itself. Check before 10-20.

**UNVERIFIED:** the NFL/NCAAF/MLB alternate key names (nothing in the repo references them — from memory of the
public list) and whether NCAAF books post alternates at all; the "now" NFL/NHL figures are a runs x events x markets
model (quote-log floors are 2x / 5x lower; the quota by-sport counter was not read); NBA in-season figures are
projections; the cost of a `/markets` key check (believed 1 credit).

## Checks run 2026-10-16 afternoon (user: "proceed with option c and check all the items that need to be checked")

Total spent on the checks: **18 credits** (5 `/markets` + 13 on two real alt calls). `/events` costs 0.

- **`/markets` costs 1 credit** -- measured (`x-requests-last` = 1 on each of 5 calls).
- **Alternate key names VERIFIED** per sport on one upcoming event each (books posting, of our 10-book list):
  - NFL (HOU @ JAX 10-18): pass_yds / pass_tds / reception_yds / rush_yds alternates at 9 books, receptions 8,
    rush_attempts 6, pass_completions 5, pass_attempts 4, pass_interceptions 3 (+ minor keys at 1-2 books).
  - MLB (TB @ CLE 10-16): batter_hits and pitcher_strikeouts alternates at 10 books; rbis / runs_scored 9;
    total_bases / home_runs 8; hits_runs_rbis / doubles / stolen_bases 5; strikeouts 2.
  - NHL (PIT @ COL 10-16): goals 7, points 6, assists / shots_on_goal 5, total_saves 3.
  - NBA (BOS @ DET 10-20 -- opening night is ALREADY posted): points / rebounds / assists 5, PRA / threes / RA 4,
    PR / PA 3, steals / blocks 2.
  - **NCAAF: NO player alternates at any book** (FAU @ Army 10-17: two team-total alternates at FanDuel only) --
    NCAAF is out of option (c).
- **Billing = markets returned, confirmed on two real calls** through `scripts/fetch_alt_ladders.py`:
  NHL PIT @ COL 5 credits for 5 markets (1,299 rungs, 39 players, 9 books); NFL HOU @ JAX 8 credits for 8 markets
  (2,203 rungs, 17 players, 9 books, median 6 rungs per player x side x book). (All requested markets were returned
  on both, so "requested" vs "returned" is not separated by these two calls.)
- **NBA live tick** (read-only check, a separate agent): the props stream runs on live-odds-worker only, one fetch per
  in-progress game per lens cycle (median 78 s overall, 100 s evenings; a 6-game preseason slate 266-313 s). A
  preseason registry shows 13 market keys on every fetch (a floor). Estimate **~4.5-8K credits per 7-8 game night,
  ~125-225K per 30 days (2.5-4.5% of the cap), stretch ~400K (8%)** -- billing per call assumed, not read. A second
  stream, `_live_oddsapi_period_totals_for_game` (`tick.py:340`, called `:8826`), makes an UNCACHED `/markets` call
  plus up to 13 period markets: ~10-14 credits per game-cycle, ~100K per 30 days (estimate). **Neither stream calls
  `record_oddsapi_quota`**, so quota `by_sport` never sees them. Not forced before 10-20; stage
  `LIVE_PLAYER_PROPS_ALL_MARKETS=0` (saves 23-48% per fetch) ready for the opener and measure G1 (10-17) / the
  opener by sampling `latest.used` vs the `by_sport` sum. Files belong to lane `nba-live-tick-native`.
