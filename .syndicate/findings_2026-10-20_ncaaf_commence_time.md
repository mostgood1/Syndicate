# 2026-10-20 — NCAAF commence_time vs venue ticker dates (lane `ncaaf-commence-time-wrong`, session 07f26684)

Substrate: **fleet** (WSL `~/syndicate-prod`, read-only) + public read-only GETs
(Kalshi `/trade-api/v2`, ESPN scoreboard). Readings 2026-10-20 21:46–22:30Z.

## 1. The trigger: the board was RIGHT, Kalshi's ticker date is stale

`REFUSED_TICKER_DATE_MISMATCH ticker='KXNCAAFGAME-26OCT23OREILL-ORE' commence_time='2026-10-24T19:00:00Z'`
(fleet `live-odds-worker.log` 21:34:31Z).

| source | kickoff for Oregon @ Illinois |
|---|---|
| OddsAPI event `0f773ec5…` (`oddsapi_player_props_2026_wk8_raw.json`, `book_grid_2026-10-24`) | 2026-10-24T19:00Z |
| CFBD `historical_truth/games_2026.json.gz` id 401858495 | 2026-10-24T19:00Z, `startTimeTBD: False` |
| ESPN scoreboard id 401858495 | 2026-10-24T19:00Z, `timeValid: True`, "Sat, October 24th at 3:00 PM EDT" |
| Kalshi `KXNCAAFGAME-26OCT23OREILL` | ticker date 10-23; `occurrence_datetime` 2026-10-24T03:00Z; rules: "game **originally scheduled for** Oct 23, 2026" |

The brief's premise ("the game is Friday 10-23, our time is wrong by a day") is
**falsified**. Three independent schedule sources agree with the board.

**Kalshi-side population.** Of all open `KXNCAAFGAME` events, 36 FBS week-8 games
carry `26OCT23` with the SAME placeholder `occurrence_datetime 2026-10-24T03:00Z`
(Oregon–Illinois, Texas Tech–Cincinnati, USC–Wisconsin, VT–Clemson, …). Kalshi
listed them before TV kickoff times existed and never re-dated them; the real
Friday games (Duke–UVA, UMass–UConn, Yale–Penn, NCCU–DSU at 00:00–02:00Z) are
mixed into the same date. Every other KXNCAAFGAME date checked (Oct 22, 24, 31)
has real per-game times.

## 2. Board commence_time vs the venue's own date (fleet book_grid 10-20..10-26)

Join: each board game → open Kalshi `*GAME` events (1,431 across 305 series) by
team names on the market `yes_sub_title`; ticker date via
`kalshi_catalogue.game_date_from_ticker`; board kickoff converted to US/Eastern.

| sport | board games | matched to a Kalshi event | ticker date == Eastern date | disagree |
|---|---|---|---|---|
| ncaaf | 56 | 41 | 14 | **27** |
| nfl | 29 | 24 | 23 | 1 (matcher false positive: "Los Angeles" hit NHL/esports) |
| nhl | 11 | 9 | 9 | 0 |
| nba | 3 | 2 | 2 | 0 |
| soccer | 197 | 78 | 78 | 0 |

The 27 NCAAF disagreements are the 26OCT23-placeholder population above (plus
`KXNCAAFBOWLGAME-26` season futures, which match on team names only). **And the
board side is right:** board vs ESPN, 50 NCAAF games matched, **49 agree to the
minute**. The one that does not is §3.

Consequence (NOT changed here — the guard is correct as is): every live Kalshi
order on one of those ~36 Saturday games is refused `REFUSED_TICKER_DATE_MISMATCH`,
and the board fan-in refuses their Kalshi quotes (`CROSS_DATE_REJECTED_GRID
sport=ncaaf count=209 sides_seen=2604` at 21:36:29Z). Conservative and correct —
but it is a FALSE refusal of the right contract, and it will recur every week
Kalshi lists FBS games before kickoff times are set. Whether to accept a ticker
dated the day before when Kalshi's own `occurrence_datetime` is the placeholder
is a USER decision (todo `#710`).

## 3. The real board defect: a moved kickoff leaves a ghost row in the old date's grid

NCAAF Iowa @ Minnesota, OddsAPI event `6dab7d3b…`:

| shard (Central kickoff date) | commence_time | rows | last look |
|---|---|---|---|
| `book_quotes/2026-10-23.jsonl` | 2026-10-24T04:00Z (OddsAPI placeholder) | 1,072 | **2026-10-17 18:32Z** |
| `book_quotes/2026-10-24.jsonl` | 16:00Z, then 19:30Z | 384 + 1,740 | 2026-10-20 21:55Z |

The quote log is sharded by Central kickoff date
(`odds_book_quotes.kickoff_shard_date`, `syndicate/features/shared/odds_book_quotes.py:193`),
so the move left the old quotes behind. `build_book_grid_artifact`
(`book_grid_artifact.py`) pivoted the 10-23 shard into a row with the
superseded 04:00Z kickoff and FanDuel −182 from 10-15, `market_basis.servable:
True`, "+8.21 pts better than the 3-book consensus" — while the 10-24 grid had
the game at −240 / +2.37 from 21 fresh books.

Who is exposed: `layer1_board.merge_grid_rows_across_dates` (`layer1_board.py:338`)
already keeps the fresher copy on the Layer-1 board; the shortlist pivots all
window shards together (`pipeline/layer2_shortlist.py:1140`) so freshest-per-book
absorbs it. But `ncaaf/picks.py:437` keeps the LARGEST edge per bet across the
week's grids (the ghost wins), and `pipeline/venue_odds_loop.py:198` reads one
date's grid at a time.

**Fix (producer, every reader at once):** `drop_events_moved_to_another_date`
in `book_grid_artifact.py`, run right after the pivot. An event is dropped only
when ALL FOUR hold: its newest look in this shard is >6h old, its kickoff is
still ahead, that kickoff falls on THIS shard's Central date, and another date's
shard (±7 days, `last_seen` sidecars, read only when a candidate exists) has
looked at it MORE RECENTLY. Absence elsewhere never drops. Counted and printed
unconditionally (`MOVED_KICKOFF_ROWS_DROPPED`), served as `moved_kickoff` on the
artifact. Switch `SYNDICATE_BOOK_GRID_DROP_MOVED_KICKOFF`, default on; `off`
keeps the rows and still counts.

**Offline replay on the fleet's own grids + sidecars** (worktree code, 27 grids
10-18..10-27, 32,977 rows, 7 sports): **1 event / 7 rows dropped — Iowa @
Minnesota from the 10-23 grid — and nothing else.** The first version (without
the shard-date condition) also dropped 28 NFL and 154 soccer forward games from
the PAST 10-18/10-19 grids, which are capture-dated copies, not moves; the
fourth condition removed exactly those.

Tests: `tests/test_book_grid_moved_kickoff.py` (10), including off != on
through the real `build_book_grid_artifact`.

## 4. Live ticker-guard refusals since the guard went live (19:33Z)

Timestamped `[execute_portfolio] REFUSED_TICKER_DATE_` lines, fleet logs, through 21:46Z:

| reason | count | tickers |
|---|---|---|
| `REFUSED_TICKER_DATE_MISMATCH` | 2 | `KXNCAAFGAME-26OCT23OREILL-ORE` ×2 (21:34:31Z, 21:42:00Z) |
| `REFUSED_TICKER_DATE_UNVERIFIABLE` | 0 | — |

All in `live-odds-worker.log`. The one `refresh-worker.log` hit was an
`ALL_PROCESS_MEMORY` line quoting a grep cmdline (`learnings.md` 2026-10-20) and
is excluded.

## Not done

- No change to the ticker-date guard (brief) and no Kalshi-placeholder handling (user decision, `#710`).
- Not landed, not deployed: the fix is committed on branch `claude/priceless-mcnulty-03480a`; the fleet runs it only after a land + refresh-worker restart, on the user's yes.
