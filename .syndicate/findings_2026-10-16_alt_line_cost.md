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
