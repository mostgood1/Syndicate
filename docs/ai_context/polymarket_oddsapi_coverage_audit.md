# Polymarket US vs. OddsAPI — what the venue lists, what we resolve, what the board carries

**Every number and every slug on this page was read out of a production log
line, and the UTC timestamp of that reading is printed next to it.** Nothing
here is inferred from the local `data/` tree (a lossy mirror — see
`CLAUDE.md`) and no slug was constructed. Direct HTTP to the live service is
blocked from this sandbox (`curl https://syndicate-an21.onrender.com/healthz`
→ `CONNECT tunnel failed, response 403`, 2026-08-25T20:35Z), so production was
read through `mcp__Render__list_logs` on `refresh-worker`
(`srv-d91dpertqb8s73co8ls0`) and `live-odds-worker`
(`srv-d91dpertqb8s73co8lt0`).

Sibling document: `docs/ai_context/kalshi_oddsapi_coverage_audit.md` (same
question, other venue, other session — not edited here). Background:
`docs/ai_context/exchange_capture_deep_dive.md`, whose §2.4 conclusion
("the slate is not being truncated") **this audit supersedes** — see §2.

**The distinction this document keeps everywhere:** *"Polymarket does not list
this"* and *"we cannot see whether Polymarket lists this"* are different
findings with different fixes. Rows of the second kind are in
[§9, SUSPECTED / UNCONFIRMED](#9-suspected-unconfirmed), never in the tables.

---

## 1. The one-paragraph answer

Polymarket lists **five** game-market types and we have a mapping for
**four** of them. Not one of the eight sports' coverage gaps is a gap in what
the venue offers — every one is ours, and they have **five distinct causes**:
(a) a sport-scope filter that drops **57% of the catalogue we already fetch**
before it is even recorded; (b) two market families (`PROP`, segment
lines) refused deliberately; (c) a **league-vocabulary miss** that makes
soccer and NCAAF structurally unreachable regardless of coverage; (d) one
missing fact — *which team a spread's sign belongs to* — that costs the entire
spreads family on every sport at once; and (e) a **club-vocabulary miss**, found
by this audit, where the join cannot resolve four of Polymarket's own
tri-codes for clubs it names in full one layer away (§5.5). The venue's own absences (NBA, NHL,
NCAAB) are **not established**, because the catalogue read is running
**against its page ceiling with `truncated=True`**, which makes every zero on
this page an upper bound rather than a fact.

---

## 2. The funnel, measured

| stage | count | source line | read at |
|---|---:|---|---|
| rows returned by the catalogue read | **15,000** | `POLYMARKET_US_GAMES rows=15000 pages=30 truncated=True` | 19:28:40Z |
| …of which game markets | **13,255** | same line, `games=13255` | 19:28:40Z |
| …of which season futures | 1,613 | same line, `futures=1613` | 19:28:40Z |
| markets handed to the daily-book recorder | 13,233 | `POLYMARKET_BOARD_JOIN markets=13233` | 20:34:22Z |
| **dropped by `in_scope_sports()` before capture** | **7,545 (57%)** | `POLYMARKET_DAILY_BOOK skipped=7545` | 20:29:03Z |
| recorded to a daily file | 5,688 | `POLYMARKET_DAILY_BOOK listed=5688` | 20:29:03Z |
| …parsed to a board market name | 2,664 | `parsed=2664` | 20:29:03Z |
| …stored unparsed (`market=null`) | 3,024 | `unparsed={'SPORTS_MARKET_TYPE_PROP': 3024}` | 20:29:03Z |
| indexed as joinable game lines | 5,736 | `POLYMARKET_BOARD_JOIN indexed=5736` | 20:34:22Z |
| joined to a board row | **73** | `matched=73` of `board_rows=1290` | 20:34:22Z |
| quotes offered to the re-pricer | **2,218** | `VENUE_REPRICE` per-sport `quotes` (194+112+1376+536) | 20:31:36Z |
| re-price selections won by Polymarket | **786 of 892** | `selected_by_source={'polymarket_us': 786, 'oddsapi': 106}` | 20:31:36Z |

`5,688 + 7,545 = 13,233` exactly, and the refusal counters reconcile to the
unit (§3.1), so these are complete counts, not samples.

### 2.1 THE READ IS TRUNCATED, AND THAT CHANGES HOW EVERY ZERO READS

```
POLYMARKET_US_GAMES status=ok start_offset=12142 boundary_probes=16 monotonic=True
  games=13255 futures=1613 rows=15000 pages=30 duplicate_ids=0 truncated=True
  orderable=14868
  game_types=['SPORTS_MARKET_TYPE_DRAWABLE_OUTCOME','SPORTS_MARKET_TYPE_MONEYLINE',
              'SPORTS_MARKET_TYPE_PROP','SPORTS_MARKET_TYPE_SPREAD','SPORTS_MARKET_TYPE_TOTAL']
  window=2026-08-21T19:00:00Z..2026-09-20T03:15:00Z
                                          -- live-odds-worker, 2026-08-25T19:28:40Z
```

`rows = 15,000 = max_pages(30) × limit(500)`, and the venue's own
`truncated=True` says so. `exchange_capture_deep_dive.md` §2.4 recorded 12,897
rows against the same 15,000 budget and concluded the slate was *not* being
truncated. **That is no longer true**: the book has grown into the ceiling.
Every "Polymarket does not list X" on this page is therefore bounded by
"…within the first 15,000 rows of the `closed=false` ordering, spanning game
starts 2026-08-21 → 2026-09-20".

**NBA (season opens late October), NHL and NCAAB fall outside that
30-day window entirely.** Their absence from this audit is a window fact, not
a venue fact.

### 2.2 The catalogue read failed outright at 20:21:29Z

```
POLYMARKET_US_GAMES status=error start_offset=None boundary_probes=None games=None
  ... reason=no_game_offset: ok                    -- live-odds-worker, 2026-08-25T20:21:29Z
```

`find_first_game_offset` returned `status=ok` with `first_game_offset=None` —
the binary search ran to its `ceiling=40000` and found no game block. The
preceding successful reads had `start_offset` climbing 11,554 → 11,557 →
11,676 → 11,686 → **12,142** over three hours. This is the failure mode that
module's docstring predicts for a *hardcoded* boundary, arriving instead as an
intermittent whole-slate outage. Not chased here (it is another lane's file);
recorded because a cycle that returns nothing is indistinguishable, downstream,
from a venue that lists nothing.

### 2.3 The daily book has not recorded a single price point

Every `POLYMARKET_DAILY_BOOK` line today reads `opened=0 appended=0`, and the
lines at 20:09:29Z, 20:13:14Z, 20:16:58Z, 20:21:34Z, 20:25:27Z and 20:29:03Z
are **byte-identical** (`listed=5688 parsed=2664` on all six). Kalshi's
equivalent on the same cycles is `appended=663 … 1245`. So the Polymarket
venue-native movement history that the capture-first design exists to produce
is, as of today, **an empty shell**: markets are being filed, prices are not.

---

## 3. Per-sport, per-market-family

Column meanings, per the four questions:

1. **Lists it?** — the `sportsMarketTypeV2` value and a verbatim observed slug.
2. **We resolve it?** — and if not, *which* refusal, by name.
3. **Board carries the key?** — does a board row ask for this market at all.
4. **OddsAPI supplies it?** — at the re-price layer, measured today.

The board's active sports today are **`['mlb', 'nfl', 'soccer', 'wnba']`**
(`VENUE_REPRICE sports=[...]`, 20:31:36Z). NBA, NHL, NCAAF and NCAAB have no
board rows on 2026-08-25.

### 3.1 The refusal ledger reconciles exactly

```
POLYMARKET_BOARD_JOIN markets=13233 indexed=5736 board_rows=1290 matched=73 slate_age_s=2081.9
  refusals={'market_type_not_a_game_line': 6234, 'segment_market_not_full_game': 1063,
            'board_market_not_a_game_line': 765,
            'no_polymarket_market_for_league_date_market': 305,
            'outcomes_count_mismatch': 200, 'no_matching_polymarket_market': 115,
            'side_not_an_outcome_of_this_market': 32}
                                              -- refresh-worker, 2026-08-25T20:34:22Z
```

`POLYMARKET_OUT_OF_SCOPE` (same tick) itemises those two big buckets
completely — its `PROP` entries sum to **6,234** and its `SEGMENT` entries to
**1,063**, matching the refusal counters to the unit. So the table below is
built on complete counts.

### 3.2 MLB — Polymarket league token `mlb`

| family | 1. Lists it? | 2. We resolve it? | 3. Board key? | 4. OddsAPI? |
|---|---|---|---|---|
| moneyline | **YES** `SPORTS_MARKET_TYPE_MONEYLINE` — `aec-mlb-pit-sd-2026-08-24` | **YES** — 194 quotes offered mlb | yes (`h2h`) | **0 quotes**, `no_side_in_key:3449` |
| totals (full game) | **YES** `SPORTS_MARKET_TYPE_TOTAL` — `tsc-mlb-tb-det-2026-08-25-7pt5` | **YES** | yes (`totals`) | 0 quotes |
| totals ladder | **YES**, every rung a separate slug — offered `chc-az@…`, `kc-tor@7.5`, `kc-tor@8.5`, `tb-det@6.5/7.5/8.5` | **YES** — all rungs indexed; only rungs a board row names survive to a match | partial | 0 quotes |
| spreads (run line) | **YES** `SPORTS_MARKET_TYPE_SPREAD` — ladder `chc-az@-2.5, -1.5, +1.5, +2.5` | **NO** — `spreads_refused:237` at the re-pricer; `side_not_an_outcome_of_this_market` at the join. See §5 | yes (`spreads`) | 0 quotes |
| segment (F5 / 1H) totals | **YES** — 74 rows | **NO** — `segment_market_not_full_game`, by design | no | n/a |
| segment spreads | **YES** — 29 rows | **NO** — same | no | no |
| player props | **YES** — **2,592 rows**, `astatc-mlb-pit-sd-2026-08-24-hits-jakman-gte2` | **NO** — `market_type_not_a_game_line`, by design (player-name resolution unbuilt) | **yes** — `mlb\|batter_home_runs\|over\|0.5` and `…\|over\|1.5` are in `board_wanted` | yes — OddsAPI is what *creates* those rows |

### 3.3 NFL — Polymarket league token `nfl`

| family | 1. Lists it? | 2. We resolve it? | 3. Board key? | 4. OddsAPI? |
|---|---|---|---|---|
| moneyline | **YES** — `aec-nfl-lac-ten-2025-11-02` | **YES** — part of 1,376 quotes | yes | **0 quotes**, `no_odds_history_shard_for_this_sport_and_date` |
| totals + ladder | **YES** — offered `nfl\|totals\|over\|24.5`, `…\|26.5` | **YES** | yes | 0 quotes |
| spreads + ladder | **YES** — `asc-nfl-nyg-nyj-2026-08-28-pos-1pt5` | **NO** — `spreads_refused:992` (the largest single spread loss of any sport) | yes | 0 quotes |
| segment spreads (1H/1Q) | **YES** — **480 rows**, `asc-nfl-pit-buf-2026-08-27-1h-neg-4pt5`, outcomes `["-4.50","+4.50"]` | **NO** — `segment_market_not_full_game` | no | no |
| segment totals (1H/1Q) | **YES** — **480 rows**, `tsc-nfl-pit-buf-2026-08-27-1h-16pt5` | **NO** — same | no | no |
| segment *moneyline* | **YES**, and it is typed `PROP`, not MONEYLINE — `atc-nfl-was-bal-2026-08-28-winner-1h-was`, outcomes `["Yes","No"]` | **NO** — `market_type_not_a_game_line` | no | no |
| player props | **YES** — 432 rows | **NO** — by design | yes (NFL props exist on the board) | yes |

**Note the fourth slug prefix.** `atc` is a prefix not in the grammar this
repo has recorded (`aec`, `tsc`, `asc`, `astatc`). `atc-nfl-was-bal-…-winner-1h-was`
names the winning team *in the slug's trailing modifier* and prices it Yes/No —
a shape none of the current parsers expect.

### 3.4 WNBA — Polymarket league token `wnba`

| family | 1. Lists it? | 2. We resolve it? | 3. Board key? | 4. OddsAPI? |
|---|---|---|---|---|
| moneyline | **YES** — offered `wnba\|h2h\|chicago sky`, `…\|connecticut sun`, `…\|portland fire`, `…\|dallas wings` | **YES** — 112 quotes | yes | **0 quotes**, `no_side_in_key:99` |
| totals + ladder | **YES** — offered `chi-conn@156.5, 159.5, 162.5, 165.5, 168.5` | **YES** | yes | 0 quotes |
| spreads + ladder | **YES** — offered `chi-conn@-11.5, -8.5, -5.5, -2.5, +3.5` | **NO** — `spreads_refused:40` | yes | 0 quotes |
| segment lines | **not observed** — no `SEGMENT\|wnba` entry in a complete counter | n/a | no | n/a |
| player props | **not observed** — no `PROP\|wnba` entry in a complete counter | n/a | yes (WNBA props exist on the board) | yes |

The two "not observed" rows sit in a counter that is **complete for the rows we
read**, so they are the strongest negative evidence on this page — but they are
still bounded by §2.1's truncation. They are listed again in §9.

### 3.5 Soccer — Polymarket lists **by competition**, never by "soccer"

| family | 1. Lists it? | 2. We resolve it? | 3. Board key? | 4. OddsAPI? |
|---|---|---|---|---|
| 3-way moneyline | **YES** `SPORTS_MARKET_TYPE_DRAWABLE_OUTCOME` | **PARTLY** — mapped to `h2h` 2026-08-25; reaches the index only when *both* clubs resolve via `team_aliases` (`_effective_league`), never via the league token | yes | **YES** — the only sport where OddsAPI produced quotes today: `44`, offering `soccer\|h2h\|draw`, `…\|real betis`, `…\|valencia`, `soccer\|spreads\|real betis` |
| totals + ladder | **YES** — offered `soccer\|totals\|over\|0.5`, `…\|1.5`; venue side `sou-whu@3.5`, `stk-hul@2.5/3.5`, `nfo-lee@0.5/1.5`, `new-wba@0.5/1.5/2.5/3.5`, `pne-eve@0.5` | **PARTLY** — same club-alias route | yes | OddsAPI offers `soccer\|spreads\|…` but no totals key in the sample |
| spreads (Asian handicap) | **YES** — `asc-eflc-car-nor-2026-08-25-neg-1pt5` etc. | **NO** — `spreads_refused:250` | yes | **YES** — `soccer\|spreads\|real betis` |
| BTTS | **YES**, typed `PROP` — `astatc-epl-cry-mnc-2026-08-28-btts`, outcomes `["No","Yes"]` | **NO** — `market_type_not_a_game_line` | (soccer BTTS exists in the props pipeline) | yes |
| everything else | **YES**, ~1,900 `PROP` rows across six competitions | **NO** | — | — |

Two additional soccer facts, both from `VENUE_REPRICE` at 20:31:36Z:

* `polymarket_us … reason="spreads_refused:250 clubs_unresolved:198:['No', 'Yes']"`
  — **198 soccer rows reached the club resolver with the outcome names `Yes`
  and `No`.** A row whose outcomes are Yes/No is being routed down the
  moneyline path, where `canonical_team(sport, "Yes")` correctly returns
  nothing. That is 198 rows/cycle counted as an alias-map gap when it is a
  market-shape gap. Characterising it needs the `question` field — which the
  artifact drops (§4.3).
* `GRID_REPRICE sport=soccer sides_seen=12858 repriced=236 … benchmark_skipped={'not_two_sided': 10229, …}`
  (20:31:31Z) — 10,229 soccer sides are one-sided and cannot be benchmarked at
  all. Consistent with the parallel lane's 88% one-sided reading.

### 3.6 NCAAF — listed as `cfb`, fetched, and structurally unreachable

| family | 1. Lists it? | 2. We resolve it? | 3. Board key? | 4. OddsAPI? |
|---|---|---|---|---|
| game lines (h2h / spreads / totals) | **YES — 246 markets on 2026-08-25**, `POLYMARKET_DAILY_BOOK skipped_by_sport={… 'cfb': 246 …}` | **NO** — dropped by `in_scope_sports()`, whose set contains `ncaaf`, not `cfb`. The rows that *do* reach the join are indexed under league `cfb`, which no board row can request | **no rows today** (NCAAF opens 2026-08-27) | Kalshi's book carries 346/212/965 NCAAF markets for 08-27/08-28/08-29, so the slate is real and imminent |
| props | **not observed** — no `PROP\|cfb` entry | n/a | no | n/a |

**This is the same defect as soccer's, in a sport nobody has looked for it in.**
`cfb` is not a soccer token, so `_effective_league`'s club-alias rescue never
fires for it. NCAAF is 100% lost, by name.

### 3.7 NBA / NHL / NCAAB — no finding either way

No `nba`, `nhl` or `ncaab` league token appears in any Polymarket log line
today, in counters that are complete for the rows read. But the fetched block
spans game starts **2026-08-21 → 2026-09-20** and the read is truncated at its
page ceiling, so all three seasons begin outside the window this instrument can
see. **"Polymarket does not list NBA/NHL/NCAAB" is NOT established** — see §9.

### 3.8 Non-Syndicate sports we fetch and pay to drop

Complete for the top 20 of `skipped_by_sport`, 20:29:03Z: `atp` 721, `ufc` 382,
`cs2` 473, `lol` 199, `itfme` 214, `itfwo` 124, `wta` 54, `valorant` 59,
`setkameua` 50, `dota2` (in the join's counter), plus `arg2` 57, `uslc` 36.
Correctly out of scope — recorded so the denominator is honest.

---

## 4. GAP TABLE — what to hand back a link for

Ranked by markets lost per cycle. **The slugs are verbatim from production
logs.** The public web-URL form for a Polymarket US market has **not been
observed** by this audit and is deliberately not constructed here; the only
address this repo has ever read is the signed API route
`https://api.polymarket.us/v1/markets?limit=<n>&offset=<n>&closed=false`
(`polymarket_us_auth.BASE_URL`, code-read). **Confirming the browsable URL for
one of these slugs is the single most useful thing to send back.**

| # | gap | markets/cycle | which of the four bugs | verbatim slug to check |
|---|---|---:|---|---|
| G1 | **Sport scope drops 57% of the book before capture** | **7,545** | we fetch it and refuse it (at `in_scope_sports`) | n/a — see §6 for the league codes |
| G2 | **Player props, every sport** | 6,234 | we fetch it and refuse it, by design | `astatc-mlb-pit-sd-2026-08-24-hits-jakman-gte2` |
| G3 | **Spreads, every sport** — the family that dies one step from working | 1,519 quotes refused (mlb 237, wnba 40, nfl 992, soccer 250) | we resolve it and the join misses (§5) | `asc-nfl-nyg-nyj-2026-08-28-pos-1pt5` · `asc-eflc-car-nor-2026-08-25-neg-1pt5` |
| G4 | **Segment lines (1H / 1Q / F5)** | 1,063 | we fetch it and refuse it, by design | `asc-nfl-pit-buf-2026-08-27-1h-neg-4pt5` · `tsc-nfl-pit-buf-2026-08-27-1h-16pt5` |
| G5 | **Soccer, by league token** | ~3,600 in named competitions + tail | we fetch it and refuse it (league vocabulary) | `astatc-epl-cry-mnc-2026-08-28-btts` · `tsc-eflc-car-nor-2026-08-25-1pt5` |
| G6 | **NCAAF as `cfb`** | 246 | we fetch it and refuse it (league vocabulary) | *observed only as the counter `'cfb': 246`; no `cfb` slug has been sampled — **§9-C** |
| G7 | **Soccer BTTS** | ~1,900 (subset of G2) | we fetch it and refuse it | `astatc-lg1-lil-psg-2026-08-28-btts` |
| G8 | **NFL 1H moneyline under a 4th prefix** | ≥1 (unbounded — `atc` is uncounted as a family) | we fetch it and cannot parse the family | `atc-nfl-was-bal-2026-08-28-winner-1h-was` |
| G9 | **One-sided quotes** — two outcomes, one price | 200 | venue-side shape; we refuse rather than guess | `tsc-eflc-car-nor-2026-08-25-1pt5` outcomes `["Under","Over"]` prices `["0.01"]` |
| G10 | **Soccer Yes/No rows on the moneyline path** | 198 | unreadable outcome shape | *slug not sampled — **§9-D** |
| G13 | **The join's team resolver fails on Polymarket's own tri-codes** — `chc`, `az`, `stl` (MLB), `phx` (WNBA) | drives part of `no_match` 115/cycle | we resolve it and the join misses (§5.5) | no full slug sampled; observed as the join's own candidate labels `chc-az@-2.5, -1.5, +1.5, +2.5` and `wsh-phx@None` |
| G11 | **NBA / NHL / NCAAB** | unknown | **we cannot see** (window + truncation) | none — **§9-A** |
| G12 | **WNBA props / segments** | unknown | **we cannot see** (truncation) | none — **§9-B** |

---

## 5. THE SPREAD FINDING — half the mapping is now verified, and the half that is missing is one bit

Spreads are refused in two places for the same reason: nothing in a Polymarket
spread row names a **team**. Outcomes are signed numbers.

```
execute_portfolio.py:1042   refusal = "spread_side_needs_verified_team_mapping"
venue_quote_adapters        if market == "spreads": return None   # refused by name
```

### 5.1 CONFIRMED — the slug's `pos`/`neg` token labels `outcomes[0]`, 5 rows of 5

Every spread row this audit observed, verbatim from `POLYMARKET_BOARD_JOIN
shapes` and `POLYMARKET_OUT_OF_SCOPE samples`, 19:55:58Z–20:34:22Z:

| slug | `outcomes` | token | `outcomes[0]` sign | agrees |
|---|---|---|---|---|
| `asc-eflc-car-nor-2026-08-25-neg-2pt5` | `["-2.50","+2.50"]` | neg | − | ✅ |
| `asc-eflc-car-nor-2026-08-25-neg-1pt5` | `["-1.50","+1.50"]` | neg | − | ✅ |
| `asc-eflc-car-nor-2026-08-25-pos-1pt5` | `["+1.50","-1.50"]` | pos | + | ✅ |
| `asc-eflc-car-nor-2026-08-25-pos-2pt5` | `["+2.50","-2.50"]` | pos | + | ✅ |
| `asc-nfl-pit-buf-2026-08-27-1h-neg-4pt5` | `["-4.50","+4.50"]` | neg | − | ✅ |

**5 of 5.** And the control is in the same log line: the *totals* rows for the
identical fixture are `["Under","Over"]` at 1.5 and `["Over","Under"]` at 2.5
and 3.5 — so **array position is genuinely unstable, and the spread sign token
is genuinely stable.** `venue_quote_adapters`' docstring records an earlier
sample where "1 of 5 rows would have been priced on the opposite handicap";
that measurement is not reproduced by these five and the two should be
reconciled before anything ships.

### 5.2 CONFIRMED — the ladder is symmetric about zero, so the sign is relative to one fixed club per game

`POLYMARKET_UNMATCHED` `offered`, 20:16:08Z:

```
mlb  chc-az    @ -2.5, -1.5, +1.5, +2.5          (complete, 4 rungs)
wnba chi-conn  @ -11.5, -8.5, -5.5, -2.5, +3.5   (first 5 of more)
```

Both signs exist at the same |line|. So `pos`/`neg` cannot mean "the favourite"
— it is a handicap applied to **one reference club that is constant within a
game**, with the opponent's mirror as the second outcome.

### 5.3 NOT CONFIRMED — whether that reference club is the slug's `<home>` or its `<away>`

This is the **one remaining bit**, and it cannot be read from any log line
production currently emits: the counters that carry spread slugs do not carry
the board's home/away for the same fixture, and the line that does
(`POLYMARKET_ARTIFACT_PRICE`) never fires for spreads because they are refused
upstream. **No inference is offered here.** Guessing it is the error that
already bought the wrong team once (2026-08-25T16:08:10Z).

### 5.4 The test that settles it, offline, with zero order risk

Both inputs already exist on the worker:

* Polymarket's spread ladder per fixture — `polymarket_us_games.json`.
* The board's own signed home spread per fixture, from OddsAPI.

For every fixture present in both, compare `sign(slug pos/neg)` against
`sign(board home spread)`. Over a full slate the answer is bimodal and
unambiguous: **≈100% agreement ⇒ the reference club is `<home>`; ≈0% ⇒ it is
`<away>`.** Anything in between falsifies §5.2 and means the reference is
per-market, in which case spreads must stay refused. `scripts/audit_polymarket_coverage.py`
in this branch implements exactly this and prints the agreement rate with its
sample size; it reads artifacts, places nothing, and is wired into no loop.

**Why this is the highest-value item in this audit:** it is one bit, it is
falsifiable, it needs no venue call, and it unblocks 1,519 refused quotes per
cycle across all four active sports simultaneously.

---

## 5.5 A FIFTH BUG CLASS — the join cannot resolve Polymarket's own tri-codes, on clubs it names in full one line away

`join_polymarket_to_board._teams_match` pairs a slug's `<away>`/`<home>`
tri-codes against the board's club names through `team_aliases.teams_match`.
**Code-read at `a41f8e2d`, and re-verified unchanged after rebasing onto
`407c602d1`** (2026-08-25T20:5xZ — production may still run a different SHA,
and `team_aliases.py` was edited by another lane the same day):

```
teams_match("mlb",  "chc", "Chicago Cubs")           -> False
teams_match("mlb",  "az",  "Arizona Diamondbacks")   -> False
teams_match("mlb",  "stl", "St. Louis Cardinals")    -> False
teams_match("wnba", "phx", "Phoenix Mercury")        -> False
teams_match("mlb",  "ari", "Arizona Diamondbacks")   -> True     # the map has `ari`, not `az`
teams_match("mlb",  "sd",  "San Diego Padres")       -> True
```

17 of 20 sampled MLB codes, 6 of 7 WNBA, **15 of 15 NFL** resolve. The failures
are not random: they are the codes where Polymarket's spelling differs from the
one the alias map happens to hold.

**Why this is separate from every other gap on this page, and why it is
invisible.** Production offered `chc-az` as a spreads *and* totals candidate at
20:16:08Z — the venue is listing the fixture, the slug parses, the line parses,
the rung is indexed — and the board row still reported `no_match`. At the *same
tick*, the re-price adapter offered `mlb|h2h|chicago cubs` and
`mlb|h2h|arizona diamondbacks`, because `_polymarket_sides` resolves the
**outcome name** ("Chicago Cubs") rather than the **slug code** (`chc`). So:

> the same club is simultaneously resolvable and unresolvable, depending on
> which of the two Polymarket spellings a given layer happens to read.

That is why MLB h2h re-pricing looks healthy (194 quotes) while the board join
matches 73 of 1,290. It is also the same shape as the `min`/`ath` collision
already recorded in `_effective_league`'s comment: **a tri-code gap presents as
intermittent coverage, because it only bites the fixtures whose codes differ.**

**The caveat this finding needs.** The code→club assignments above are read off
the fixture context in the same production log line (`chc-az` appearing at the
tick that offered "chicago cubs" and "arizona diamondbacks"); the `teams_match`
results are a pure code fact independent of Polymarket. Both halves should be
re-checked against the deployed SHA before anything is changed — this audit
changed nothing.

---

## 6. THE SOCCER LEAGUE MAPPING — read from data, as the docstring asked

`venue_daily_odds.in_scope_sports()` says the mapping "has never been read" and
counts out-of-scope rows by league so the codes become addable from data.
Those counters have now been read.

```
POLYMARKET_DAILY_BOOK … skipped=7545
  skipped_by_sport={'lal': 960, 'epl': 790, 'atp': 721, 'lg1': 711, 'cs2': 473,
                    'sea': 448, 'bun': 393, 'ufc': 382, 'lgscup': 320, 'cfb': 246,
                    'itfme': 214, 'lol': 199, 'eflc': 198, 'itfwo': 124, 'uecl': 72,
                    'valorant': 59, 'arg2': 57, 'wta': 54, 'setkameua': 50, 'uslc': 36}
                                        -- live-odds-worker, 2026-08-25T20:29:03Z
```

**Each mapping below is confirmed by the CLUBS in a verbatim slug, not by the
token's resemblance to a league name.**

| Polymarket token | markets | Syndicate league | evidence — verbatim slug |
|---|---:|---|---|
| `lal` | 960 | **`la_liga`** | `astatc-lal-ala-vil-2026-08-28-btts` — Alavés v Villarreal |
| `epl` | 790 | **`epl`** | `astatc-epl-cry-mnc-2026-08-28-btts` — Crystal Palace v Man City |
| `lg1` | 711 | **`ligue_1`** | `astatc-lg1-lil-psg-2026-08-28-btts` — Lille v PSG |
| `sea` | 448 | **`serie_a`** | `astatc-sea-mil-ven-2026-08-28-btts` — Milan v Venezia |
| `bun` | 393 | **`bundesliga`** | `astatc-bun-fcb-stu-2026-08-28-btts` — Bayern v Stuttgart |
| `eflc` | 198 | **`championship`** | `astatc-eflc-car-nor-2026-08-25-btts`, `tsc-eflc-car-nor-2026-08-25-1pt5` — Cardiff v Norwich |
| `lgscup` | 320 | *none of the ten* — Leagues Cup | `astatc-lgscup-mon-chi-2026-08-25-btts` — CF Montréal v Chicago Fire (MLS clubs, cup competition) |
| `uecl` | 72 | *none of the ten* — UEFA Conference League | token only |
| `ucl` | 1 | *none of the ten* — UEFA Champions League | token only (join counter) |
| `arg2` | 57 | *none* — Argentine second tier | token only |
| `uslc` | 36 | *none* — USL Championship | token only |

**Six of Syndicate's ten leagues are now mapped from data.** Adding those six
tokens to `SYNDICATE_VENUE_ODDS_SPORTS` — which `in_scope_sports()` documents
as changeable *without a deploy* — would bring **3,500 soccer markets/cycle**
into capture. That is a production change and is **not taken here**; this
audit only supplies the codes.

### 6.1 The four leagues still missing, and why they are missing from the READING, not from the venue

`mls`, `eredivisie`, `primeira_liga` and `belgian_pro_league` do not appear
above. **That is a reporting artefact, not an absence.** `record_venue_book`
truncates `skipped_by_sport` to `[:20]`; the twenty printed sum to **6,507**
against `skipped_total=7,545`, so **1,038 markets sit in leagues whose codes
are never printed.** The four missing leagues are the obvious occupants.
Removing the `[:20]` cap (a one-token read-only change to a diagnostic) names
them on the next cycle. See §9-E.

### 6.2 The rescue path that is masking how bad this is

Soccer is not at zero (536 quotes) because `_effective_league` reclassifies a
row as `"soccer"` when *both* clubs resolve through `team_aliases`. So soccer
coverage today is a function of the **club alias map**, not of the league
mapping, and it will keep looking partially healthy while the league key stays
broken. NCAAF has no such rescue (§3.6) and sits at exactly zero — which is
what the soccer number would be without the alias coincidence.

---

## 7. ALT LINES AND LADDERS — explicitly

**Capture: every rung.** Polymarket lists each rung as its own slug
(`-8pt5`, `pos-1pt5`, `neg-2pt5`), all rungs are inside the same catalogue
page range, and `_line_from_modifiers` parses each. Observed complete ladders:
`chc-az @ ±1.5, ±2.5` (MLB run line), `tb-det @ 6.5/7.5/8.5` and
`kc-tor @ 7.5/8.5` (MLB totals), `chi-conn @ 156.5–168.5` in 3-point steps
(WNBA totals), `nfo-lee / new-wba @ 0.5/1.5/2.5/3.5` (soccer totals),
`nfl totals @ 24.5, 26.5`.

**Re-price layer: every rung survives.** `_polymarket_sides` emits a `Quote`
per side per row keyed `sport|market|side|line`, so all rungs reach
`apply_venue_quotes`. NFL's 1,376 quotes against a much smaller board row
count is the ladder being carried.

**Join layer: only the rungs the board already names.** `join_polymarket_to_board`
indexes every rung, then requires `abs(candidate.line − board.line) < 1e-9`.
A rung the board does not carry is fetched, parsed, indexed — and dropped
without a counter of its own. **We do not lose ladder rungs at capture; we
lose them at the board.** Widening alt-line coverage is therefore a board-row
question, not a Polymarket question.

**One exception, and it is total:** every rung of every **spread** ladder is
refused (§5). Alt spreads are 100% lost on all four active sports.

---

## 8. THE REVERSE DIRECTION — what OddsAPI is being paid for that Polymarket already covers

`VENUE_REPRICE`, refresh-worker, 2026-08-25T20:31:36Z:

| sport | polymarket_us | age | oddsapi | age | Polymarket age advantage |
|---|---:|---:|---:|---:|---|
| mlb | **194 quotes**, `status=ok` | 1,915 s | **0 quotes**, `no_side_in_key:3449` | 3,479 s | 1.8× fresher, and the only source with quotes |
| wnba | **112 quotes**, `ok` | 1,915 s | **0 quotes**, `no_side_in_key:99` | **15,825 s (4.4 h)** | 8.3× fresher |
| nfl | **1,376 quotes**, `ok` | 1,916 s | **0 quotes**, `no_odds_history_shard_for_this_sport_and_date` | — | no OddsAPI shard at all |
| soccer | **536 quotes**, `ok` | 1,916 s | 44 quotes, `ok` | 128 s | OddsAPI fresher here |

`selected_by_source={'polymarket_us': 786, 'oddsapi': 106}`.

**The defensible reading — and its limit.** At the **re-price** layer, MLB, WNBA
and NFL game lines are *already* 100% Polymarket-sourced today: OddsAPI
contributed **zero** usable quotes for all three. Soccer is the only sport
where OddsAPI is doing re-price work (44 quotes, 106 selections), and it is the
sport where it is genuinely fresher.

**What this does NOT license.** OddsAPI is what *creates* board rows —
`board_wanted=['mlb|batter_home_runs|over|0.5', …]` exists because OddsAPI
supplied it. Polymarket re-prices rows; it does not yet generate them, and it
carries no player-prop resolution at all (§4-G2). So the honest statement is:

> **The OddsAPI *game-line price refresh* for mlb / wnba / nfl is already
> contributing nothing measurable and Polymarket is covering it for free at a
> 900 s cadence.** Cutting OddsAPI *game-line* pulls for those three sports is
> supportable on today's reading. Cutting OddsAPI **props** or **row
> generation** is not — nothing else produces them.

Two caveats worth stating before anyone acts: OddsAPI's zero on mlb/wnba is a
**reader** defect (`no_side_in_key` — the shard has 3,449 entries whose keys
carry no side), not proof the feed is empty; and this is **one tick**. A
before/after over a full day is the reading that would justify a spend change.

### 8.1 ADDENDUM — Kalshi entered the contest 17 minutes after this reading, and took nothing from OddsAPI

The `kalshi: markets_key_absent` in the table above was fixed and deployed at
~20:48Z (`.syndicate/deploys.md`, commit `407c602d1`, "verified 0 -> 1852
selections"). The before/after recorded there:

```
before   selected_by_source={'polymarket_us': 788, 'oddsapi': 106}
after    selected_by_source={'kalshi': 1852, 'polymarket_us': 769, 'oddsapi': 106}
```

**This strengthens §8 rather than dating it.** A third free venue arriving with
1,852 selections cost Polymarket 19 and cost OddsAPI **zero** — OddsAPI's 106
are all soccer, the one sport where it is genuinely fresher (128 s vs 1,916 s),
and nothing else it supplies was contested by either exchange. The conclusion
is unchanged and now has a control: the OddsAPI *game-line price refresh* for
mlb / wnba / nfl is contributing nothing that either free venue is not already
covering, while OddsAPI's soccer quotes and its **row generation and player
props** remain unreplaced by anything.

The `by_source` table in §8 stays as measured at 20:31:36Z and is not rewritten
— it is the reading that was taken, and the addendum is what happened next.

---

## 9. SUSPECTED, UNCONFIRMED

Each row names what would confirm it. These are the items worth sending a live
Polymarket link for.

**A. NBA, NHL and NCAAB.** No league token observed in complete counters, but
the fetched block spans 2026-08-21 → 2026-09-20 and the read is truncated at
its page ceiling (§2.1). All three seasons start after that window.
*Confirms it:* a Polymarket link to any NBA, NHL or NCAAB market — or raising
`max_pages` past 30 and re-reading `POLYMARKET_US_GAMES game_types` / the
skipped-league counter.

**B. WNBA player props and WNBA segment lines.** Absent from a counter that is
complete for the rows read, on a day with four WNBA fixtures.
*Confirms it:* a link to any WNBA player-prop market, or the same
untruncated re-read.

**C. A verbatim `cfb` slug.** NCAAF is confirmed present *as a count* (246
markets) but no `cfb` slug has been sampled, so the NCAAF slug grammar is
unverified. *Confirms it:* one `POLYMARKET_OUT_OF_SCOPE` sample keyed on `cfb`
(it will appear the moment a `cfb` row is refused for a reason that samples),
or a link to a college-football market.

**D. The 198 soccer Yes/No rows.** `clubs_unresolved:198:['No','Yes']` names
the outcome values but no slug. *Confirms it:* the `question` field — which
`_SLATE_STORAGE_FIELDS` drops before persistence, so the diagnostic designed
to characterise these rows (`out_of_scope_samples`, whose own comment says
"the question is what names the bet") is **structurally blind**: every sample
observed today carries `'question': ''`. Adding `question` to the persisted
row is the fix.

**E. `mls`, `eredivisie`, `primeira_liga`, `belgian_pro_league`.** 1,038
skipped markets sit below the `[:20]` print cap (§6.1). *Confirms it:* raise
or remove the cap in `record_venue_book`'s return.

**F. The browsable Polymarket US market URL.** Every slug on this page is
verbatim; the web address that renders one is not observed anywhere in this
repo or in production. *Confirms it:* one link from the user.

**G. `atc` as a market family.** One slug observed
(`atc-nfl-was-bal-2026-08-28-winner-1h-was`). Whether `atc` is a family or a
one-off is unknown, because prefixes are not counted anywhere.
*Confirms it:* a per-prefix counter, or a link.

**§5.5 IS CLOSED, and by someone else.** `teams_match` now resolves all ten
MLB tri-codes checked (`cle laa chc az min ath phi sea cin sf`) against
`7b8f67b04`; the four failures recorded at `a41f8e2d` were fixed by another
session the same evening. The gap was real when measured and is real no longer.

**§5.3 HAS NOW BEEN RUN THREE TIMES IN PRODUCTION AND IS STILL UNANSWERED**
(2026-08-25 21:47Z, 22:01Z, 22:17Z; full working in `.syndicate/deploys.md`).
The current blocker is not the instrument: with segment markets correctly
excluded, our slate carries **no full-game MLB spread** for any of the 18 board
fixtures — only first-five-innings. NFL wk1 (2026-08-27) is the next slate that
should carry full-game spreads. **Whether the missing full-game MLB spreads are
absent at the venue or dropped by our own `_slate_within_budget` trim
(13,233 → 7,936 markets) is UNMEASURED**, and is exactly this document's
central distinction applied to itself.

**H. The `venue_quote_adapters` "1 of 5 spread rows" measurement.** It
contradicts §5.1's 5-of-5. Its five rows are not reproduced in any log line
this audit could find. *Confirms it:* the ladder-vs-board comparison in §5.4,
run over a whole slate.

---

## 10. Evidence appendix — the lines, verbatim

All UTC, 2026-08-25. `POLYMARKET_*` on `refresh-worker` come from
`portfolio_commit`; those on `live-odds-worker` from `run_live_odds_refresh_worker`.

**19:28:40Z · live-odds-worker**
```
[live_odds_worker] POLYMARKET_US_GAMES status=ok start_offset=12142 boundary_probes=16
 monotonic=True games=13255 futures=1613 rows=15000 pages=30 duplicate_ids=0
 truncated=True orderable=14868 game_types=['SPORTS_MARKET_TYPE_DRAWABLE_OUTCOME',
 'SPORTS_MARKET_TYPE_MONEYLINE','SPORTS_MARKET_TYPE_PROP','SPORTS_MARKET_TYPE_SPREAD',
 'SPORTS_MARKET_TYPE_TOTAL'] window=2026-08-21T19:00:00Z..2026-09-20T03:15:00Z reason=None
```

**20:21:29Z · live-odds-worker**
```
[live_odds_worker] POLYMARKET_US_GAMES status=error start_offset=None boundary_probes=None
 monotonic=None games=None futures=None rows=None pages=None duplicate_ids=None
 truncated=None orderable=None game_types=None window=None..None reason=no_game_offset: ok
```

**20:21:32Z · live-odds-worker**
```
[live_odds_worker] POLYMARKET_US_SLATE status=skipped
 reason=sports_routes_404_on_this_host_measured_2026-08-24T20:18:37Z
 (set SYNDICATE_POLYMARKET_US_SPORTS_PROBE=1 to re-check)
```
— the per-league events route is unavailable on this host; `/v1/markets` is the
only working discovery path.

**20:29:03Z · live-odds-worker** (identical at 20:09:29, 20:13:14, 20:16:58, 20:21:34, 20:25:27)
```
[live_odds_worker] POLYMARKET_DAILY_BOOK status=ok files=11 errors=0 listed=5688
 parsed=2664 opened=0 appended=0 undated=0 skipped=7545
 skipped_by_sport={'lal': 960, 'epl': 790, 'atp': 721, 'lg1': 711, 'cs2': 473,
  'sea': 448, 'bun': 393, 'ufc': 382, 'lgscup': 320, 'cfb': 246, 'itfme': 214,
  'lol': 199, 'eflc': 198, 'itfwo': 124, 'uecl': 72, 'valorant': 59, 'arg2': 57,
  'wta': 54, 'setkameua': 50, 'uslc': 36}
 unparsed={'SPORTS_MARKET_TYPE_PROP': 3024}
 detail=[{'sport':'mlb','date':'2026-08-25','markets':2637,'appended':0}, …
         {'sport':'nfl','date':'2026-08-28','markets':1690,'appended':0}, …
         {'sport':'wnba','date':'2026-08-25','markets':54,'appended':0}, …]
```

**20:34:22Z · refresh-worker**
```
[portfolio_commit] POLYMARKET_BOARD_JOIN markets=13233 indexed=5736 board_rows=1290
 matched=73 slate_age_s=2081.9 refusals={'market_type_not_a_game_line': 6234,
 'outcomes_count_mismatch': 200, 'segment_market_not_full_game': 1063,
 'no_matching_polymarket_market': 115, 'board_market_not_a_game_line': 765,
 'side_not_an_outcome_of_this_market': 32,
 'no_polymarket_market_for_league_date_market': 305}
 shapes=[{'slug':'tsc-eflc-car-nor-2026-08-25-1pt5','type':'SPORTS_MARKET_TYPE_TOTAL',
   'reason':'outcomes_count_mismatch','outcomes':'["Under","Over"]','prices':'["0.01"]'},
  {'slug':'tsc-eflc-car-nor-2026-08-25-2pt5', … 'outcomes':'["Over","Under"]','prices':'["0.01"]'},
  {'slug':'tsc-eflc-car-nor-2026-08-25-3pt5', … 'outcomes':'["Over","Under"]','prices':'["0.0100"]'},
  {'slug':'asc-eflc-car-nor-2026-08-25-neg-2pt5','type':'SPORTS_MARKET_TYPE_SPREAD',
   … 'outcomes':'["-2.50","+2.50"]','prices':'["0.0100"]'},
  {'slug':'asc-eflc-car-nor-2026-08-25-neg-1pt5', … 'outcomes':'["-1.50","+1.50"]','prices':'["0.0100"]'},
  {'slug':'asc-eflc-car-nor-2026-08-25-pos-1pt5', … 'outcomes':'["+1.50","-1.50"]','prices':'["0.01"]'}]
```
(the `pos-2pt5` rung `'outcomes':'["+2.50","-2.50"]'` appears in the same field
at 19:55:58Z)

**20:34:22Z · refresh-worker** — complete, reconciles to 6,234 + 1,063
```
[portfolio_commit] POLYMARKET_OUT_OF_SCOPE counts={'SPORTS_MARKET_TYPE_PROP|mlb': 2592,
 'SPORTS_MARKET_TYPE_PROP|lal': 632, 'SPORTS_MARKET_TYPE_PROP|epl': 500,
 'SPORTS_MARKET_TYPE_SPREAD|SEGMENT|nfl': 480, 'SPORTS_MARKET_TYPE_TOTAL|SEGMENT|nfl': 480,
 'SPORTS_MARKET_TYPE_PROP|lg1': 450, 'SPORTS_MARKET_TYPE_PROP|nfl': 432,
 'SPORTS_MARKET_TYPE_PROP|ufc': 359, 'SPORTS_MARKET_TYPE_PROP|sea': 338,
 'SPORTS_MARKET_TYPE_PROP|bun': 308, 'SPORTS_MARKET_TYPE_PROP|lgscup': 200,
 'SPORTS_MARKET_TYPE_PROP|atp': 132, 'SPORTS_MARKET_TYPE_PROP|cs2': 129,
 'SPORTS_MARKET_TYPE_PROP|lol': 127, 'SPORTS_MARKET_TYPE_TOTAL|SEGMENT|mlb': 74,
 'SPORTS_MARKET_TYPE_SPREAD|SEGMENT|mlb': 29, 'SPORTS_MARKET_TYPE_PROP|eflc': 18,
 'SPORTS_MARKET_TYPE_PROP|valorant': 12, 'SPORTS_MARKET_TYPE_PROP|dota2': 4,
 'SPORTS_MARKET_TYPE_PROP|ucl': 1}
 samples=[{'key':'SPORTS_MARKET_TYPE_PROP|lg1','slug':'astatc-lg1-lil-psg-2026-08-28-btts','question':'','outcomes':'["Yes","No"]'},
  {'key':'SPORTS_MARKET_TYPE_PROP|epl','slug':'astatc-epl-cry-mnc-2026-08-28-btts','question':'','outcomes':'["No","Yes"]'},
  {'key':'SPORTS_MARKET_TYPE_PROP|sea','slug':'astatc-sea-mil-ven-2026-08-28-btts','question':'','outcomes':'["Yes","No"]'},
  {'key':'SPORTS_MARKET_TYPE_PROP|bun','slug':'astatc-bun-fcb-stu-2026-08-28-btts','question':'','outcomes':'["Yes","No"]'},
  {'key':'SPORTS_MARKET_TYPE_PROP|lal','slug':'astatc-lal-ala-vil-2026-08-28-btts','question':'','outcomes':'["Yes","No"]'},
  {'key':'SPORTS_MARKET_TYPE_PROP|nfl','slug':'atc-nfl-was-bal-2026-08-28-winner-1h-was','question':'','outcomes':'["Yes","No"]'},
  {'key':'SPORTS_MARKET_TYPE_PROP|ufc','slug':'astatc-ufc-josvan-alepan-2026-09-19-mov-f1-ko','question':'','outcomes':'["Yes","No"]'},
  {'key':'SPORTS_MARKET_TYPE_PROP|eflc','slug':'astatc-eflc-car-nor-2026-08-25-btts','question':'','outcomes':'["Yes","No"]'},
  {'key':'SPORTS_MARKET_TYPE_PROP|lgscup','slug':'astatc-lgscup-mon-chi-2026-08-25-btts','question':'','outcomes':'["Yes","No"]'},
  {'key':'SPORTS_MARKET_TYPE_PROP|cs2','slug':'astatc-cs2-pcy-mm-2026-08-25-map1','question':'','outcomes':'["Yes","No"]'},
  {'key':'SPORTS_MARKET_TYPE_SPREAD|SEGMENT|nfl','slug':'asc-nfl-pit-buf-2026-08-27-1h-neg-4pt5','question':'','outcomes':'["-4.50","+4.50"]'},
  {'key':'SPORTS_MARKET_TYPE_TOTAL|SEGMENT|nfl','slug':'tsc-nfl-pit-buf-2026-08-27-1h-16pt5','question':'','outcomes':'["Over","Under"]'},
  {'key':'SPORTS_MARKET_TYPE_PROP|lol','slug':'astatc-lol-doc-fsk-2026-08-25-game2','question':'','outcomes':'["Yes","No"]'},
  {'key':'SPORTS_MARKET_TYPE_PROP|atp','slug':'astatc-atp-miokec-fabmar-2026-08-25-es-2-0','question':'','outcomes':'["Yes","No"]'}]
```
**Every `question` is empty** — see §9-D.

**20:16:08Z · refresh-worker**
```
[portfolio_commit] POLYMARKET_UNMATCHED counts={'no_candidates|soccer|h2h': 215,
 'no_candidates|nfl|totals': 68, 'no_match|soccer|totals': 49, 'no_match|mlb|totals': 21,
 'no_candidates|nfl|h2h': 21, 'no_match|mlb|spreads': 20, 'no_match|wnba|totals': 14,
 'no_match|wnba|h2h': 7, 'no_match|wnba|spreads': 3, 'no_candidates|nfl|spreads': 1}
 samples=[{'kind':'no_match','board':'Minnesota Twins @ Athletics','want':'totals|under|10.0',
   'date':'2026-08-25','offered':['tb-det@6.5','tb-det@7.5','tb-det@8.5','kc-tor@7.5','kc-tor@8.5']},
  {'kind':'no_candidates','board':'Real Betis @ Valencia','want':'h2h|away|None','date':'2026-08-25','offered':[]},
  {'kind':'no_match','board':'Kansas City Royals @ Toronto Blue Jays','want':'spreads|away|1.0',
   'date':'2026-08-25','offered':['chc-az@-2.5','chc-az@-1.5','chc-az@1.5','chc-az@2.5','hou-nyy@-2.5']},
  {'kind':'no_match','board':'CF Montreal @ Inter Miami CF','want':'totals|under|3.5','date':'2026-08-25',
   'offered':['sou-whu@3.5','stk-hul@2.5','stk-hul@3.5','nfo-lee@0.5','nfo-lee@1.5']},
  {'kind':'no_match','board':'Washington Mystics @ Phoenix Mercury','want':'spreads|away|-1.5',
   'date':'2026-08-25','offered':['chi-conn@-11.5','chi-conn@-8.5','chi-conn@-5.5','chi-conn@-2.5','chi-conn@3.5']},
  {'kind':'no_candidates','board':'Washington Commanders @ Baltimore Ravens','want':'h2h|home|None','date':'2026-08-25','offered':[]},
  {'kind':'no_match','board':'Washington Mystics @ Phoenix Mercury','want':'totals|over|40.5','date':'2026-08-25',
   'offered':['chi-conn@156.5','chi-conn@159.5','chi-conn@162.5','chi-conn@165.5','chi-conn@168.5']}, …]
```

**20:31:36Z · refresh-worker**
```
[layer2_shortlist] VENUE_REPRICE rows_in=18064 stamped=892 unstamped=17172
 sports=['mlb','nfl','soccer','wnba'] ceiling_s={'mlb':21600,'wnba':21600,'nfl':21600,'soccer':86400}
 by_source={'mlb': {'kalshi': {'status':'error','reason':'markets_key_absent','quotes':0},
   'polymarket_us': {'status':'ok','reason':'spreads_refused:237','quotes':194,'age_seconds':1914.5},
   'novig': {'status':'disabled','reason':'switched_off','quotes':0},
   'oddsapi': {'status':'no_rows','reason':'no_side_in_key:3449','quotes':0,'age_seconds':3479.2}},
  'wnba': { … 'polymarket_us': {'status':'ok','reason':'spreads_refused:40','quotes':112,'age_seconds':1915.3},
   'oddsapi': {'status':'no_rows','reason':'no_side_in_key:99','quotes':0,'age_seconds':15824.7}},
  'nfl': { … 'polymarket_us': {'status':'ok','reason':'spreads_refused:992','quotes':1376,'age_seconds':1915.8},
   'oddsapi': {'status':'no_rows','reason':'no_odds_history_shard_for_this_sport_and_date','quotes':0}},
  'soccer': { … 'polymarket_us': {'status':'ok','reason':"spreads_refused:250 clubs_unresolved:198:['No', 'Yes']",
     'quotes':536,'age_seconds':1916.3},
   'oddsapi': {'status':'ok','reason':'no_side_in_key:8','quotes':44,'age_seconds':127.7}}}
 selected_by_source={'polymarket_us': 786, 'oddsapi': 106}

[layer2_shortlist] VENUE_REPRICE_KEYS unmatched_by_sport={'mlb':4204,'wnba':1501,'nfl':2132,'soccer':9335}
 board_wanted=['mlb|batter_home_runs|over|0.5', … 'mlb|batter_home_runs|over|1.5', …]
 sources_offered={'mlb': {'polymarket_us': ['mlb|h2h|chicago cubs','mlb|h2h|arizona diamondbacks',
    'mlb|h2h|houston astros','mlb|h2h|new york yankees']},
  'wnba': {'polymarket_us': ['wnba|h2h|chicago sky','wnba|h2h|connecticut sun','wnba|h2h|portland fire','wnba|h2h|dallas wings']},
  'nfl': {'polymarket_us': ['nfl|totals|over|24.5','nfl|totals|under|24.5','nfl|totals|under|26.5','nfl|totals|over|26.5']},
  'soccer': {'polymarket_us': ['soccer|totals|over|0.5','soccer|totals|under|0.5','soccer|totals|over|1.5','soccer|totals|under|1.5'],
   'oddsapi': ['soccer|h2h|draw','soccer|h2h|real betis','soccer|h2h|valencia','soccer|spreads|real betis']}}
```

**20:30:29Z–20:31:31Z · refresh-worker**
```
[layer2_shortlist] GRID_REPRICE sport=mlb    sides_seen=4347  repriced=38  by_source={'polymarket_us': 38}
[layer2_shortlist] GRID_REPRICE sport=wnba   sides_seen=1676  repriced=4   by_source={'polymarket_us': 4}
[layer2_shortlist] GRID_REPRICE sport=nfl    sides_seen=2682  repriced=450 by_source={'polymarket_us': 450}
[layer2_shortlist] GRID_REPRICE sport=soccer sides_seen=12858 repriced=236 by_source={'polymarket_us': 236}
  benchmark_skipped={'not_live':1244,'venue_did_not_price_every_side':15,'not_two_sided':10229,…}
```

**19:52:21Z · live-odds-worker** — the slate artifact's size
```
[refresh_state_store] KEYVALUE_WRITE_LARGE
 key=…/reports/intelligence/polymarket_us_games.json size_bytes=3711595
 warn_bytes=1048576 max_bytes=8388608 caller=polymarket_us_markets.py:1288
```

---

## 11. Code facts used above (code-read, NOT production measurements)

Labelled separately because a read of the tree is not a reading of production.
Read at `a41f8e2d` and **re-verified unchanged against `407c602d1`** after this
branch was rebased — including the `venue_quote_adapters.py` edit main landed
in between, which did not touch any fact below.

* `MARKET_TYPE_TO_BOARD` (`polymarket_board_join.py`) maps MONEYLINE→`h2h`,
  SPREAD→`spreads`, TOTAL→`totals`, DRAWABLE_OUTCOME→`h2h`. **PROP is the only
  one of the five observed game types with no mapping.** No other
  `sportsMarketTypeV2` value is unmapped the way DRAWABLE_OUTCOME was.
* `_SLATE_STORAGE_FIELDS` (`polymarket_us_markets.py`) is `slug`,
  `sportsMarketTypeV2`, `outcomes`, `outcomePrices`, `line`, `gameStartTime`,
  `orderPriceMinTickSize`, `minimumTradeQty`, `orderable` — **`question` is
  dropped**, which is why §9-D cannot be answered.
* `in_scope_sports()` returns `SUPPORTED_SPORT_SLUGS | {"soccer"}` and is
  overridable by `SYNDICATE_VENUE_ODDS_SPORTS` **without a deploy**.
* `record_venue_book` truncates `skipped_by_sport` to `[:20]` (§6.1).
* `_NON_SOCCER_LEAGUE_TOKENS` = `{mlb, nba, wnba, nfl, nhl, ncaaf, ncaab,
  ncaabb}` — `cfb` is not in it, and neither is any soccer competition token,
  which is why soccer gets the club-alias rescue and NCAAF does not.
* `polymarket_us_auth.BASE_URL = "https://api.polymarket.us"`; the discovery
  route in use is `/v1/markets?limit=&offset=&closed=false`.
* Nothing in this audit changed any of the above.
