# The betting contract lifecycle — eight sports, eight stages

Written 2026-08-09. **Read-only trace. No code was changed to produce it.**

## What this document is for

`plan_layer2_north_star.md` §3 says every board is a projection or a filter over
one canonical `market_row`, never a second pipeline. This document tests that
claim against production, stage by stage and sport by sport, and names every
place a field survives to one surface and dies before the next.

**The book grid (L1-A) is the reference contract.** It is the widest surface —
every market, every book, every line, no quality filter — so anything it can
render is something the contract must carry. Everything downstream is a
narrowing of that same row. **A field that survives to the book grid and dies
before settlement is a contract break.**

### How to read the tables

Three verdicts, and they must never be collapsed:

| verdict | meaning | cost of confusing it |
|---|---|---|
| **NO PRODUCER** | nothing computes this value for this sport | you go looking for a broken join that does not exist |
| **NOT JOINED** | a producer exists and its output does not reach the consumer | you build a producer that is already there |
| **MEANINGLESS** | the value cannot exist for this sport/market/state | you file a defect against correct behaviour |

The single most repeated defect in this codebase is rendering all three
identically. Where a surface already distinguishes them, this document says so;
where it does not, that is itself the finding.

### Provenance rules used here

Every number below carries **which service, which disk, which instant**. Two
services in this system report different values for the same field name at the
same moment, and the repo has lost hours to that. Where a figure is inherited
from another lane rather than measured here, it is attributed inline.

Three provenance classes appear:

- **`[web]`** — served by `syndicate-an21` (web service), commit `b6ef6512`,
  reading web's own disk `syndicate-data-web`.
- **`[worker/kv]`** — refresh-worker's own view, reaching web through the
  keyvalue-backed `refresh_state_store`. The endpoint runs on web; **the numbers
  describe refresh-worker.**
- **`[code]`** — established by reading source and `render.yaml`, not by
  observing production. Flagged explicitly because it is a weaker claim.

**Local `data/**` was not used for any figure in this document.** It was tried
first and is empty: `graded_rows_for_date` returns **0 rows for all eight
sports** across 2026-07-19..2026-08-08 on this checkout, and
`build_market_accuracy_payload('date=2026-08-05')` returns `days: []`. That is
CLAUDE.md's lossy-mirror trap and nothing here rests on it.

### Measurement window

All `[web]` and `[worker/kv]` figures were taken **2026-08-09 03:37Z–03:57Z**,
date shard **2026-08-08**. That instant matters and is stated wherever it
changes the answer: at 03:37Z the 08-08 MLB slate is 14/15 complete, the WNBA
and soccer slates are finished, and NFL is five days out. **Several zeros below
are correct for that hour and would be defects at 18:00Z.** Where that is true
it is marked `[HOUR]`.

---

## 0. The identity chain — the most important table in this document

A bet must stay joinable from the moment a book quotes it to the moment it is
graded. It does not. The chain uses **at least six different identity
vocabularies**, and the breaks are at the seams between them.

| # | stage | identity key | vocabulary | source |
|---|---|---|---|---|
| 1 | CAPTURE | `event_id` + bookmaker + market + selection + line + `snapshot_ts` | OddsAPI event hash | `odds_book_quotes.py` |
| 2 | ROW BUILD | `(sport, event_id, market, segment, line, player_name)` → one market_instance, sides merged | same hash | `book_grid.py` |
| 3 | ENRICH · game state | **team display name** | English names | `board_enrichment.attach_game_state` |
| 4 | ENRICH · projections | **player name** / match | English names | `prop_projections`, `wnba_projections`, `soccer_projections` |
| 5 | SELECTION | `_IDENTITY_FIELDS` = sport, event_id, kind, market, segment, line, player_name, home_team, away_team, commence_time, + `side` | same hash | `layer2_board.py:60` |
| 6a | BET LOG · slip | `prediction_id` (uuid4) + `recommendation_id` | opaque ids | `POST /api/portfolio/bets` |
| 6b | BET LOG · event | normalized **values** of {market, selection/pick/name, event_id, game_id, player, player_name, team, name, home, away} | mixed | `_evaluation_record_keys` |
| 7 | SETTLEMENT · graded | normalized **values** of {selection, player, team, home, away, title} | English names only | `_graded_row_keys` |
| 8 | MATCH | **set intersection of normalized values**, then market compatibility, then line equality | — | `match_graded_row` |
| 9 | BRIDGE B→A | `recommendation_id` | opaque id | `ledger_bridge.py` |
| — | MLB source truth | `game_pk` (e.g. `823106`) | MLBAM namespace | `market_accuracy` |
| — | NCAAF source truth | CFBD numeric `id` | CFBD namespace | `graded_outcomes.py:547` |

### The three breaks

**BREAK 1 — `event_id` is carried on both sides of the settlement join and is
dead weight.** `_graded_row_keys` (`evaluation_settlement.py:337`) emits
`selection / player / team / home / away / title` and **no `event_id` and no
`market`**. The matcher intersects normalized *values*, so an id present on the
record side that no graded row ever emits can never contribute an overlap. Every
settlement match therefore falls back to matching English names. An L2-A game
row's key set is `{event_id, market}`, which can never intersect any graded row:
**84 of 200 rows measured tonight would log successfully and never settle.**
Filed as `#299` by the settlement lane; documented here, not re-derived.

Corroborated independently on production `[worker/kv]`: `missing_event_identity`
is **0 across every sport and every stage** of `opportunity_contract_metrics_v1`
(table in §2). Event identity is universally present on the recommendation side
and universally absent on the graded side. **The chain breaks at exactly one
hop, and it is the last one.**

**BREAK 2 — prop rows join on a single string.** With `event_id` inert and the
market token never emitted, a prop record's only viable key is the player name.
It works because names happen to be unique and to agree between the two sources.
Nothing enforces that.

**BREAK 3 — a real joinable id exists at the source and is discarded by the
adapter.** `_ncaaf_graded_rows_for_date` reads CFBD's numeric game id into
`game_id`, uses it for its own dedup (`seen_game_ids`), and **does not place it
on the emitted row**. MLB's `game_pk` reaches the ledger record side (visible in
the live diagnostic below) and never the graded side. This is not "no id
exists"; it is an id thrown away one line before it would have been useful.

Live evidence of Break 1 and Break 3 together, from the settlement diagnostic
`[worker/kv]`, autorun epoch **2026-08-06T11:03:17Z**:

```
record_keys      ["823106", "det", "drew anderson", "over drew anderson", "pitcher outs"]
                   ^^^^^^ MLB game_pk, on the record side
graded_rows_available   1        graded_row_market_families_sample ["moneyline"]
reason           "no_key_match"
```

### The identity fields each grader actually emits

`[code]`, from `graded_outcomes.py`. `GRADED_OUTCOME_FIELDS` documents a
superset; this is what each grader populates in practice.

| sport | grader | `event_id` | `title` | `home`/`away` | `team` | `player` | `selection` | `odds` |
|---|---|---|---|---|---|---|---|---|
| mlb | `_mlb_graded_rows_for_date` | **never** | yes | **no** | yes | yes | yes | yes |
| wnba | `_local_market_accuracy_...` | **never** | **no** | games only | props only | props only | yes | yes |
| nba | `_local_market_accuracy_...` | **never** | **no** | games only | props only | props only | yes | yes |
| nhl | `_local_market_accuracy_...` | **never** | **no** | games only | props only | props only | yes | yes |
| nfl | `_nfl_graded_rows_for_date` | **never** | yes | yes | **no** | n/a | yes | yes |
| ncaaf | `_ncaaf_graded_rows_for_date` | **discarded** | yes | yes | **no** | n/a | yes | yes |
| ncaab | `_ncaab_graded_rows_for_date` | **never** | yes | yes | **no** | n/a | yes | **no** |
| soccer | `syndicate/features/soccer/actuals` | not inspected | — | — | — | — | — | — |

Two consequences the aggregate hides:

- **MLB emits `team` and `title` but never `home`/`away`; NFL/NCAAF/NCAAB emit
  `home`/`away`/`title` but never `team`.** A record normalized to carry one
  vocabulary will match one group of sports and not the other. `#297`'s
  `normalize_portfolio_event_identity` fills `home`, `away` **and** `team`,
  which is why it works across both — that is load-bearing, not belt-and-braces.
- **NCAAB emits no `odds` at all.** Its rows carry `result` but no price, so
  `_pnl_for_settlement` has nothing to compute a return from. NCAAB can be
  graded and cannot be priced. Out of season now; it will matter in November.

---

## 1. CAPTURE

**Which books, which regions, what cadence, sharded by which date.**

### Books and regions — S0b is no longer dark

`[web]`, 03:37Z, `book_grid.summary.books`:

| sport | distinct books | max on one row | evidence of the extra regions |
|---|---|---|---|
| **mlb** | **44** | 43 | `pinnacle`, `betfair_ex_eu`, `matchbook`, `kalshi`, `polymarket`, `novig`, `prophetx`, `espnbet`, `hardrockbet`, `fliff`, `rebet` all present |
| **wnba** | 18 | 18 | `us` + `us2` only (`ballybet`, `betparx`, `espnbet`, `fliff`, `hardrockbet`, `rebet`) |
| **soccer** | 11 | 11 | `us` only |
| **nfl** | 11 | 11 | `us` only |
| nba / nhl / ncaaf / ncaab | 0 | 0 | no shard `[HOUR]`, see §1.3 |

The North Star §5 records S0b as *"ships DARK until two env vars are set"*. It
is now lit: MLB's 44 books is `us,us2` plus `eu,us_ex` on the game lines, which
is the scoped configuration §4d prices at 4.13M/month.

**Unverified and it matters:** I did not read the live values of
`SYNDICATE_LIVE_ODDS_REFRESH_REGIONS` / `SYNDICATE_LIVE_ODDS_GAME_LINE_REGIONS`
off the three services. So I cannot say whether `us2` leaked onto the prop calls
— **the exact ~1M/month mistake S0b's 9 tests exist to catch.** The check is
`/v1/services/<id>/env-vars` on all three, paginated (`limit` > 100 → HTTP 400).

**Why only MLB gets the wide grid is not established here.** WNBA has `us2` and
not `eu`/`us_ex`; soccer and NFL have neither. Whether that is a deliberate
per-sport scope, a fetch path that does not thread the extras list, or simply
which sports were fetched during the window, is unanswered.

### Cost — the burn is at 155% of cap

`[web]` `GET /api/ops/oddsapi/quota`, read **03:54:31Z**. The 30-day projection
is the endpoint's own field, not a derivation of mine.

```
aggregate since 2026-07-28T02:36Z (12.05 d)   902,524 cr    74,870/day   2.25M/30d    45% of 5M
recent window (27.6 h, ends 03:54Z)           296,697 cr   257,916/day   7.74M/30d   155% of 5M
projected_30d_credits (reported)                                         7,737,455   155% of 5M
```

S0 measured **62,076/day = 1.86M/month = 37.2%** on 2026-08-07 and concluded
"more headroom than planned". The recent window is **4.15×** that. At
257,916/day the 5,000,000 contracted cap is exhausted in **19.4 days**.

The header still reports `remaining: 14,187,817`. Per the standing note, that
figure is not real; every percentage above is against 5M.

Cost structure, and S0's shape holds:

| family | credits | share | | sport | credits | share | credits/call |
|---|---|---|---|---|---|---|---|
| props | 417,572 | 46.3% | | **mlb** | 859,100 | **95.2%** | 7.2 |
| segment | 302,593 | 33.5% | | soccer | 36,571 | 4.1% | 1.3 |
| alternate | 151,327 | 16.8% | | wnba | 6,292 | 0.7% | 6.1 |
| full_game | 29,952 | 3.3% | | nfl | 561 | 0.1% | 0.4 |
| event_list / other | 1,080 | 0.1% | | | | | |
| **per-event-billed** | | **96.6%** | | | | | |

S0 measured per-event-billed at 95.5% and MLB at 92.8%. Both confirmed and
slightly more concentrated. Soccer makes 27,547 calls for less credit than
WNBA's 1,035 — the "cheap lever hiding in a sport nobody has looked at"
hypothesis stays falsified.

**No §4d lever gets 155% under 100% alone.** L1+L2 together were priced at ~47%
off, which takes 7.74M to ~4.1M — the entire savings plan spent to return to
where S0b's projection started.

`by_hour_utc` (aggregate window, not the recent one) peaks at 22:00Z = 154,942
credits against a 04:00Z trough of 5,965 — a **26× diurnal swing**. §4d's L4
off-hours gate is the lever with the clearest measured shape and the smallest
headline.

### Cadence and date-sharding

| sport | cadence evidence | shard key | verdict |
|---|---|---|---|
| mlb game lines | `h2h_lay` `observed_at` 03:39:57Z, read 03:44Z → **4 min** | local date | fresh |
| mlb props | `batter_total_bases` best-cell ages on one event span **0.09 h – 14.95 h** | local date | **per-event billing means per-event starvation** |
| mlb, first capture of a date | **~06:43Z**, per `#296`'s measurement in `layer2_shortlist.py:75-85` | local date | ~6 h nightly with no shard at all |
| soccer | not measured here | **fixture date** (`#239`) | a today-only puller 404s and logs "absent" |
| wnba / nfl | not measured here | local date | — |

The prop-vs-game-line cadence split is not a defect, it is §4c's cost structure
working as designed: props bill per event, so they cannot be polled at game-line
rates. **It becomes a defect only downstream, where a 21-hour prop price is
admitted to a ranked recommendation surface without being labelled stale.** See
§4.

**Two capture paths with different region scope.** The orchestrator run captured
at 03:39:56Z `[web]` shows `--sports mlb,wnba --phase live --regions us`, while
the MLB grid carries 44 books. So the `refresh_odds_sources.py` path and the
live-refresh loop are not configured alike. Not diagnosed; flagged because a
reader comparing the two will see contradictory region sets and neither is wrong.

---

## 2. ROW BUILD — the canonical `market_row`

`build_book_grid` emits the reference row. Measured `[web]` 03:37–03:56Z, first
400 rows of each sport's grid (the slice is stated because coverage figures are
per-slice, not per-slate).

| field | mlb | wnba | soccer | nfl | nba/nhl/ncaaf/ncaab |
|---|---|---|---|---|---|
| rows in slate | **6,641** | 715 | 727 | 1,351 | **0** `[HOUR]` |
| `event_id` | 400/400 | 400/400 | 400/400 | 400/400 | — |
| `market` / `segment` | 400/400 | 400/400 | 400/400 | 400/400 | — |
| `line` | 370/400 | 373/400 | 172/400 | 170/400 | — |
| `player_name` | 148/400 | 350/400 | 336/400 | **0/400** | — |
| `home_team`/`away_team` | 400/400 | 400/400 | 400/400 | 400/400 | — |
| `commence_time` | 400/400 | 400/400 | 400/400 | 400/400 | — |
| `cells` (all books) | yes | yes | yes | yes | — |
| `best` / `consensus` | yes | yes | yes | yes | — |
| `gaps` (why a row is thin) | 18/400 populated | — | — | — | — |
| segments present | `full` only in slice | `full` | `full` | `full` | — |

**Verdict: ROW BUILD is the healthiest stage in the system.** Identity is
complete on every sport that has a shard. `player_name 0/400` on NFL is
**MEANINGLESS**, not a gap — NFL's grid is 400/400 `kind: game`; there are no
prop rows to name a player on.

### Grid width and two-sidedness

| sport | rows | 3+ books | two-sided | single-book | best flagged stale |
|---|---|---|---|---|---|
| mlb | 6,641 | 64.1% | 83.9% | 1,623 | 472 (`rows_with_suspect_best`) |
| wnba | 715 | 41.5% | 94.0% | 266 | 34 |
| soccer | 727 | **13.2%** | **10.3%** | 557 | 1 |
| nfl | 1,351 | 16.2% | 100.0% | 614 | 0 |

Soccer at 13.2% three-book and 10.3% two-sided is the thinnest grid on the
platform. The margin model covers it (§3), but no-vig from a real two-sided
consensus is unavailable on ~90% of soccer rows.

### The one measured row-build identity break

`[worker/kv]` `opportunity_contract_metrics_v1`, `service_role
refresh-worker-4tx2`, generated **2026-08-09T03:55:54Z**:

| sport | date key | stage | rows | complete | with_quote | miss_event | **miss_market_key** | miss_entity |
|---|---|---|---|---|---|---|---|---|
| mlb | 2026-08-08 | game_candidate | 38 | 38 | 38 | 0 | 0 | 9 |
| mlb | 2026-08-08 | intelligence_game | 91 | 91 | 38 | 0 | 0 | 13 |
| mlb | 2026-08-08 | intelligence_prop | 30 | 30 | 26 | 0 | 0 | 0 |
| mlb | 2026-08-08 | prop_source_in | 46 | 46 | 0 | 0 | 0 | 0 |
| mlb | 2026-08-09 | game_candidate | 53 | 53 | **0** | 0 | 0 | 4 |
| **soccer** | 2026-08-08 | **prop_source_in** | **162** | **0** | 0 | 0 | **162** | 0 |
| soccer | 2026-08-08 | intelligence_game/prop | 0 | 0 | 0 | 0 | 0 | 0 |
| wnba | 2026-08-08 | intelligence_prop | 11 | 11 | 11 | 0 | 0 | 0 |
| wnba | 2026-08-08 | intelligence_game | 4 | 4 | 0 | 0 | 0 | 4 |
| wnba | 2026-08-09 | game_candidate | 4 | 4 | 0 | 0 | 0 | 4 |
| nfl | *(empty)* | game_candidate | 32 | 32 | 0 | 0 | 0 | 32 |
| nfl | 2026-08-08 | intelligence_game | 16 | 16 | 0 | 0 | 0 | 16 |
| nba / nhl / ncaab / ncaaf | 2026-08-08 | all | 0 | 0 | 0 | 0 | 0 | 0 |

- **Soccer `prop_source_in`: 162 rows, 162 missing `market_key`, 0 complete.**
  Every soccer prop source row fails the contract at the market-key check. This
  is a **NOT JOINED** at the source, and it is 100%, not a tail.
- `missing_entity_name` on game candidates (nfl 32/32, wnba 4/4, mlb 9/38) is
  **MEANINGLESS** — a game line has no entity.
- `missing_event_identity` is **0 everywhere**. Stated again because it is the
  fact that makes Break 1 a pure waste: the id is there, all the way through.
- **Date keys are context labels, not dates.** `nfl` appears under an *empty*
  key and under `"2026 Prese"`; `ncaaf` under `"2025 Week "` — a stale season
  year with the week number missing, still present after `#289` flagged it. A
  metrics store keyed on a truncated display string cannot be joined to a date.

---

## 3. ENRICHMENT — sim projection, game state, margin model

### 3a. Projections — and this is where "a zero must be attributable" is won and lost

`[web]` 03:37Z, from each grid's own `projections` block plus row-level counts
over the 400-row slice.

| sport | `supported` | rows considered | with projection | **with edge** | blank rows carrying a reason | verdict |
|---|---|---|---|---|---|---|
| **mlb** | true | 6,641 (grid) / 3,604 (shortlist ingest) | 1,308 = **19.7%** (grid); 18.6% (ingest); 117/400 slice | **0** | **117 of 117 projected rows** say *"game is final: a pregame projection cannot be priced against a live market"*. **283 of 400 rows carry no projection and no reason.** | mixed — see below |
| **soccer** | true | 727 (grid) / 720 (ingest) | 222 = **30.5%** (grid); 220 = 30.6% (ingest); 96/400 slice | 2 | 37 *"one-sided market: no two-sided fair to price against"*, 4 *"3-way market: two-leg de-vig would drop the draw"*, **55 unattributed** | best attribution on the platform |
| **wnba** | true | 563 (grid) / 494 (ingest) | 71 = **12.6%** (grid); 7.7% (ingest); 35/400 slice | **0** | **0 of 35.** Summary says `probability_fields: "null by design -- means only, no distribution"` — the reason exists **only at the summary level and is not carried onto the row** | **MEANINGLESS, rendered as silent** |
| **nfl** | **false** | — | 0 | 0 | summary says `reason: "no projection source wired for nfl"` | **NO PRODUCER**, correctly labelled |
| nba / nhl / ncaaf / ncaab | **false** | — | 0 | 0 | `"no projection source wired for <sport>"` | **NO PRODUCER**, correctly labelled |

**Two denominators, and they are not the same.** The serve-time grid and the
persisted shortlist run the *same* `attach_projections` over the *same* shard
and report different `rows_considered`: mlb 6,641 vs 3,604, wnba 563 vs 494,
soccer 727 vs 720. `build_layer2_shortlist` passes `max_grid_rows_per_sport`,
which the endpoint does not — so the two percentages are over different row
sets. **Quote whichever you like, but say which**: the same sport is 19.7%
projected on one surface and 18.6% on the other, and neither is wrong. This is
the shape `#275` named — *put the n in the number*.

**Three different zeros in one column, and only two of them are stated on the
row.** WNBA's blank `Edge` is correct behaviour — its source is a per-player
mean block with no distribution, so no probability-space edge exists to compute
(`#263`'s richness ladder: MLB full distribution → soccer probability at some
lines → WNBA means only → NFL nothing). A reader looking at a WNBA row sees the
same blank cell a defect would produce.

MLB's zero splits cleanly and the split is the finding:

```
400 MLB grid rows
  117  projection present, edge blocked, REASON STATED  -> attributable, and correct at this hour
  283  no projection at all, NO reason                  -> silent
    0  edge present
```

`#263`'s per-sport parity numbers were measured differently (per market, via
`audit_layer1_completeness.py`) and are not directly comparable to these
per-slice counts. **The discriminator is live and reachable** —
`per_sport_ingest.enrichment.projections` on `/api/board/layer2-shortlist` and
`projections` on `/api/board/book-grid` — and it is surfaced nowhere a person
reading the board can see it. That is `#263`'s open half.

### 3b. Game state — the join that fails, and it is not random

`[web]` 03:37–03:56Z. `attach_game_state` is sport-aware; the coverage is not.

| sport | chips found | grid rows matched | slice `game.state` present | unmatched |
|---|---|---|---|---|
| **mlb** | **5** | 1,220 / 3,604 | 149 / 400 | 20 team names listed |
| soccer | 61 | 720 / 720 | 400 / 400 | none |
| wnba | 1 | 278 / 715 | 147 / 400 | 4 team names listed |
| nfl | **0** (`reason: no_chips_for_date`) | 0 / 1,351 | 0 / 400 | — |

**MLB joins 5 of the 15 events on its own grid, and the 5 are the earliest.**
Enumerated `[web]` 03:46Z across `h2h`/`totals`/`spreads`:

```
19:05Z  ATL @ NYY   YES      23:10Z  CHC @ KC     no
20:11Z  ATH @ BOS   YES      23:11Z  MIN @ MIL    no
20:11Z  LAA @ MIA   YES      23:16Z  BAL @ TEX    no   (+4 more at 23:16Z, all no)
22:06Z  TOR @ PHI   no       00:11Z  LAD @ ARI    no
22:41Z  NYM @ PIT   YES      01:50Z  TB  @ SEA    no   <- the whole L2-A shortlist
22:46Z  CIN @ WSH   YES
```

Every game from 23:10Z onward has no chip. The chip source is a snapshot that
captured the early games as `final` and never picked up the rest.
**MEANINGLESS is not available as an explanation here** — these are real games
on the same grid, with quotes, on the same date. This is **NOT JOINED**.

**Related, and separately measured:** `/api/board/game-chips` **ignores its
`sport` parameter.** All eight sports plus the no-argument case return a
byte-identical 65-chip list (same SHA-1 over the matchup sequence). The list
mixes MLB finals, MLS fixtures dated Aug 1–2, and NCAAF fixtures out to Aug 28.
The *enrichment* is sport-aware (mlb 5 / soccer 61 / wnba 1 / nfl 0), so this is
the debug endpoint's parameter being inert, not the join. Low severity on its
own; high severity in context, because it is the surface someone would reach for
to diagnose the coverage gap above and it would mislead them.

### 3c. Margin model

`[web]` 03:37Z. Fills fair value where the feed only quotes one side.

| sport | one-sided rows | modelled | median hold | books profiled | observations |
|---|---|---|---|---|---|
| mlb | 1,071 | **100.0%** | 6.48% | 44 | 28,714 |
| wnba | 43 | **100.0%** | 6.66% | 18 | 2,088 |
| soccer | 652 | **100.0%** | 4.54% | 11 | 267 |
| nfl | 0 | n/a (100% two-sided) | 4.55% | 11 | 2,829 |

**Verdict: PASS on every sport with a shard.** This is S4 working. Soccer's
profile rests on 267 observations against MLB's 28,714 — thin, but stated, and
labelled `book_margin_model` so it is never confused with a two-sided consensus.

---

## 4. SELECTION — `opportunity_gate`, `blended_score`

`[web]` `/api/board/layer2-shortlist`, artifact `written_at 03:43:22Z`, read
**03:44:28Z**.

### The funnel, per sport

| sport | quote rows | grid rows | candidates | opportunities | dead | `rows_with_model_edge` | **selected** |
|---|---|---|---|---|---|---|---|
| mlb | 21,843 | 3,604 | 6,444 | 4,273 | 2,171 | **0** | **100** |
| nfl | 5,965 | 1,351 | 2,702 | 2,702 | 0 | **0** | **0** |
| soccer | 5,758 | 720 | 800 | 633 | 167 | **4** | **0** |
| wnba | 7,310 | 614 | 1,187 | 442 | 745 | **0** | **0** |
| nba/nhl/ncaaf/ncaab | absent from ingest entirely | | | | | | 0 |

```
opportunities_considered  8,050
rows_beyond_horizon       2,702   = NFL exactly           (horizon_days = 1)
rows_stale_kickoff        5,004   = soccer 633 + wnba 442 + MLB 3,929  (stale_kickoff_seconds = 7,200)
rows_below_value_floor        0
rows_beyond_quote_age         0   <- max_quote_age_seconds = 86,400
active_sports          ["mlb"]
```

Three attributable zeros and one that is not:

- **NFL: 2,702 of 2,702 dropped as `rows_beyond_horizon`.** `horizon_days: 1`.
  NFL's slate is five days out. This is §4b's *"weekly sports have no today"*
  made concrete: **L2-A is structurally NFL-blind at the default scope**, and
  §4b names the fix (scope is a `commence_time` filter over the same row, not a
  pipeline fork). Attributable, correctly reported, and a real product gap.
- **soccer and wnba: 100% dropped as `rows_stale_kickoff`.** Their 08-08 slates
  finished more than 2 hours before the artifact was written. Correct `[HOUR]`.
- **nba/nhl/ncaaf/ncaab: absent from `per_sport_ingest` entirely.** Out of
  season. Correct — but note they are absent, not zero, which is a weaker signal
  than `#296`'s `sweep_state` contract now provides for a swept-but-empty sport.
- **`rows_with_model_edge`: 0 for MLB, NFL, WNBA; 4 for soccer.** So
  `blended_score` runs on EV alone on effectively every ranked row. The
  differentiator does not reach the ranking. `layer2_shortlist.py:128-134`
  states the consequence precisely: under proportional de-vig EV is
  `1/overround - 1`, **identical for every side of a market**, so the board ranks
  markets by hold and picks a side by tie-break.

### THE FINDING: the entire cross-sport shortlist is one in-progress game priced 21 hours stale

`[web]`, artifact rebuilt 03:43:22Z, read 03:44:28Z:

```
rows                                  100
distinct event_id                       1     <- Tampa Bay Rays @ Seattle Mariners
commence_time                    01:50:00Z     (~1.9 h IN PROGRESS at read time)
market_state                       pregame     100/100
gate.reasons                            []     100/100
quote.suspect_stale                  False     100/100
quote.book_age_seconds    21.00 / 21.01 / 21.03 h   (min / median / max)
score.freshness_factor      0.25 on 67, 0.5 on 14, 1.0 on 14, 0.75 on 4, 0.9 on 1
model_edge_pct, score.sim_component   null     100/100
```

**The causal chain, each link measured separately:**

1. The TB @ SEA event is one of the 10 MLB events with **no game-state chip**
   (§3b). Its grid rows carry `game: {}`.
2. `layer2_board.py:494` sets `game_state`/`is_live` **inside `if game:`**. No
   game → neither field is ever set on the candidate.
3. `opportunity_gate.game_state_of` reads `row.get("game_state")`, gets `""`,
   and `""` is a member of `_PREGAME_TOKENS` → returns **`pregame`**. **Absence
   is mapped to a value, and it is the permissive one.**
4. `pregame` selects `PREGAME_MARKET_MAX_AGE_SECONDS = 86_400` instead of
   `LIVE_MARKET_MAX_AGE_SECONDS = 900`. 75,600 s < 86,400 → admitted, with an
   empty `reasons` list.
5. Under a correct `live` classification all 100 rows are `LANE_DEAD` with
   reason `live_market_stale`.

**Same-instant control, so this is not the grid being equally stale.** At
03:44:27Z, the same event's L1-A `h2h_lay` row reads `updated_at
2026-08-09T03:39:57Z`, best-cell `age_seconds` **258.3**,
`lag_behind_freshest_seconds` **1.0**. The grid is four minutes old. Only the
shortlist is 21 hours old.

**What is NOT claimed.** `book_age_seconds` is `side_best["age_seconds"]` — the
grid's own field, unmodified (`layer2_board.py:479`). Prop markets legitimately
go long between polls: measured on this same event, `batter_total_bases`
best-cell ages span 0.09 h – 14.95 h. **The 21-hour stamp is probably honest.
The defect is that a 21-hour price is admitted, ranked, and reported
`suspect_stale: False`** — not that it is recorded.

`layer2_shortlist.py:128-131` already predicts this in a comment: *"game state →
opportunity_gate reads `game_state`/`is_live`. Absent, every row looks pregame
and a SETTLED MARKET CAN RANK."* What was missing is that it is happening now,
on 100/100 rows, and that the cause is **upstream of the enrichment call** — the
chips do not exist to be joined, so the enrichment step cannot be blamed and
cannot fix it.

**This interacts with §4e/S1b.** S1b's fresh-best-price rule works: only 18 of
800 best cells on the MLB grid are flagged stale, median lag 41 s, and each
carries a `gaps` sentence naming the lag. The gate's own ceiling is what admits
the 21-hour row, and no amount of S1b fixes a state classifier that defaults to
the permissive branch.

### The 15 board columns

Against 100 real L2-A rows `[web]` 03:44Z. The brief's 200-row measurement is
consistent with this one; where they differ, the brief's is the larger sample.

| column | status here | correct blank? |
|---|---|---|
| title / prop line / matchup / odds / edge (EV) / state badge / team (game rows) | populated | — |
| `Live` | 98/100 carry `quote_seen_age_seconds` | — |
| **`Projected`** | **absent from the row** | **NO** — `#270`'s cheap join. `layer2_shortlist.py`'s working tree now copies `projection` onto the candidate (`layer2_board.py:522`); the served artifact does not yet carry it |
| **`Win%`** | blank | **YES for wnba/nfl** — no distribution exists to derive it. **NO for mlb** at a pregame hour |
| **`Edge` (model)** | `model_edge_pct` null 100/100 | **YES where `Win%` is** — it depends on it |
| **`Actual`** | blank | **YES** — has not happened on an unsettled row |
| **`Move`** | absent | **NO** — `line_odds_movement` has no source on an L2-A row |
| confidence badge | present but **must not be mapped** | `#270`: `book_confidence` distribution is `{1.0, 0.85, 0.7, 0.5}`; a `>= 0.7` badge fires on 68/100 here. It means "how many books quote this", not model confidence |

**Three of the blanks are correct behaviour and the next reader will file them
as defects.** That is why they are named here.

---

## 5. PRESENTATION

| board | endpoint | exists | is it a projection over `market_row`? | verdict |
|---|---|---|---|---|
| **L1-A** book grid | `/api/board/book-grid` | yes | **yes** — serve-time pivot on `cells`, no quality filter | **PASS**, the reference surface |
| **L1-B** advanced | — | **partial** | `projection` is on the grid row; there is no dedicated view | S3 incomplete |
| **L2-A** best bets | `/api/board/layer2-shortlist` | yes | yes — gate + rank over the same row | **served, but see §4** |
| **L2-B** arbitrage | `/api/board/cross-book`, `is_arbitrage` filter | yes | yes | not measured here |
| **L2-C** low hold | same row, ranked by hold | yes | yes | not measured here |

**Presentation caveats measured tonight:**

- **`/api/board/book-grid?sport=mlb&limit=2000` 502s reproducibly.**
  `limit=600` with a `market=` filter is fine. Web OOM-killed at
  **03:35:33Z**, and previously at 23:44:04Z and 23:38:37Z, all
  `oomKilled {memoryLimit: 2Gi}` per the Render events API. The L1-A serve-time
  pivot has no payload ceiling. This is not my lane; it is recorded because it
  cost three probes and will cost the next reader the same.
- **L2-A has no UI consumer**, per `#268`: `home.py` contains zero references to
  `layer2`/`shortlist`, and nothing in `templates/`/`static/` fetches the
  endpoint. Everything in §4 describes an endpoint, not a rendered board.
  `#268`'s rule applies — **verify the rendered page; an endpoint returning 200
  with rows is not a board.**
- **The North Star is silent on home-page composition.** It specifies five
  boards and a scope selector and says nothing about what the home page shows or
  in what order. That gap is not filled here.

---

## 6. BET LOGGING — and there are two ledgers, on two disks

**There is not one bet-logging path. There are two, they write different
stores, and only one of them is what `/portfolio` reads.**

| | **Ledger A — portfolio** | **Ledger B — evaluation** |
|---|---|---|
| written by | `POST /api/portfolio/bets` (bet slip, `bet_slip.js:206`) | `POST /api/intelligence/portfolio-event` (`intelligence.html:2046`) **and** `maybe_record_board_state_to_evaluation_ledger` |
| file | `data_root()/prediction_ledger.json` | `reports_root()/intelligence/evaluation_ledger_chunks/<date>.jsonl` |
| IO | `path.read_text()` / `path.write_text()` | `path.open("a")` (`_append_jsonl`) |
| read by | `/portfolio` | **never by `/portfolio`** |
| settled by | `prediction_reconciliation` autorun | `evaluation_settlement` autorun |
| identity | `prediction_id` (uuid4), `recommendation_id` | normalized value tokens |
| runs on | web writes; **refresh-worker settles** | web writes; **refresh-worker settles** |

`ledger_bridge.py` exists solely to cross this split, copying decided outcomes
B → A on `recommendation_id`. Its own docstring: both autoruns were enabled and
*"Production still showed `settled_count: 0` on five tracked bets."*

### The disk split — `[code]`, corroborated `[web]`/`[worker/kv]`

`render.yaml` mounts **three separate 50 GB disks at the identical path**:

```
web              syndicate-data-web              /opt/render/project/data
refresh-worker   syndicate-data-refresh-worker   /opt/render/project/data
live-odds-worker syndicate-data-live-odds-worker /opt/render/project/data
```

Both ledgers use plain filesystem IO. Both bet-logging routes run on **web**.
Both settlement autoruns run inside `scripts/run_refresh_worker.py` on
**refresh-worker**. Same path string, different disk — which is why it does not
look wrong in either process.

**Same-instant corroboration**, both read 03:54:10–03:54:11Z `[web]`:

```
/intelligence/api/opportunity-board   records 0   publish_count 0   settled_count 0   clv null   roi null
/api/portfolio/summary                total_tracked 0   pending_count 0   settled_count 0   roi null   avg_clv null
refresh-worker's own view [worker/kv]  total_recommendation_records 8,276
```

Web sees **0**; refresh-worker holds **8,276**.

**What is established and what is not.** The 8,276 records on refresh-worker are
written *by refresh-worker* (`maybe_record_board_state_to_evaluation_ledger`),
so they are on the same disk as the settler and are settleable in principle.
Whether a **web-logged** bet reaches refresh-worker is established from code and
`render.yaml`, and corroborated by the visibility gap — but **not observed
end-to-end**, because doing so requires writing a bet to production and this is
a read-only trace.

> **The experiment that would settle it, for whoever owns this:** log one test
> bet via `POST /api/intelligence/portfolio-event` on web, then read
> refresh-worker's `chunk_diagnostics.<date>.line_count` from
> `/api/ops/evaluation-settlement/status` before and after. If the line count
> does not move, the split is confirmed by measurement rather than by reading.

**Why this ordering matters for `#297`/`#299`.** The identity-key work is
necessary and it operates *downstream* of this. If a web-logged bet never
reaches refresh-worker's ledger, fixing the key vocabulary changes nothing for
user-logged bets — it changes settlement only for the worker-written board-state
records. Those are the 8,276.

`#297`'s `normalize_portfolio_event_identity` is wired into the route
(`intelligence.py:1943`) in the working tree and is **uncommitted** as of
`a000e2e4`. It normalizes path B only; the bet slip's path A is untouched.

---

## 7. SETTLEMENT

`[worker/kv]`, `/api/ops/evaluation-settlement/status`, autorun epoch
**2026-08-06T11:03:17Z — three days stale at read time.** Window
2026-07-17..2026-08-06.

```
total_recommendation_records   8,276
matched                            0
settled                            0
unmatched                      8,276
  unmatched_no_graded_rows     3,716   <- NO PRODUCER: zero graded rows for that sport/date
  unmatched_no_key_match       4,560   <- producer exists, key sets disjoint
  unmatched_bad_result             0
  unmatched_unsupported_sport      0
```

**The instrument already distinguishes NO PRODUCER from NOT JOINED, and it is
the only place in the system that does.** That distinction should be copied, not
rebuilt.

### `graded_rows_available` — the number that reframes everything else

```
mlb:2026-08-05    1        nfl:2026-08-05    0        soccer:2026-08-05  0        wnba:2026-08-05  0
mlb:2026-08-06    0        nfl:2026-08-06    0        soccer:2026-08-06  0        wnba:2026-08-06  0
```

**One graded row across eight sport×date combinations.** So the 4,560
`no_key_match` records failed against a pool of size 1 — and that single row is
a `moneyline`, which `_markets_compatible` rejects for every prop record
regardless of keys.

**This is the most important caveat in the document, and it cuts against the
lane I am documenting:** the identity break (§0, Break 1) is real, established
by code, and **currently un-observable in production, because the grader
supplies essentially nothing to match against.** Fixing the matcher alone would
settle 0 → 0. The grader has to produce rows first. `#275` closed with the
grader audit as its open work and this is the same conclusion reached from the
opposite end.

### Per-sport grading reality

Two independent measurements, and they disagree; both are reported rather than
reconciled, because they were taken from different surfaces at different times.

| sport | brief's lane, 07-19..08-08 | this trace `[worker/kv]`, 08-05/08-06 | attribution |
|---|---|---|---|
| soccer | 385 rows | 0 | — |
| mlb | 53 rows | 1 | — |
| **wnba** | **0 — DEFECT** | 0 | `processed_root()` read a root with **0 of 6 artifact families**. Fixed by `17d4f203`, **not deployed** |
| **nfl** | **0 — DEFECT** | 0 | grader read a directory nothing writes; fixed tonight (`b2d7e36f`), **still correctly 0** — no NFL games have been played |
| nba / nhl / ncaab / ncaaf | 0 | 0 | **MEANINGLESS** — out of season in August |

**Four zeros, four different causes, all rendering identically.** A deployed
fix, an undeployed fix, a fix that correctly still reads zero, and four
legitimate out-of-season absences — and the settlement summary shows one number
for all of them.

I did not re-derive the 07-19..08-08 row counts. Local `graded_rows_for_date`
returns 0 for all eight sports on this checkout (§0 provenance), and the
production grader runs only inside refresh-worker's process, which is not
reachable over HTTP.

### Closing price is not the closing price — `#295`, confirmed in code

`[code]`, `odds_refresh_tracking.py:1591-1603`. The stamp fires once, on the
transition into live, and records **`previous_line`/`previous_odds` — the value
observed at the tick before**:

```python
if was_confirmed_pregame and market_state.get("closing_line") is None and previous_line is not None:
    market_state["closing_line"]  = previous_line
    market_state["closing_price"] = previous_odds
```

So "closing price" means **the last pregame value observed at a polling
boundary**, and the width of that boundary is the capture cadence — ~26 min for
MLB game lines, and up to **14.95 h measured tonight on MLB props** (§1). The
brief's measured case — a seal holding `-140` from a quote 4.5 h stale against a
true close of `-181` — is exactly this mechanism, and the second mechanism (the
freeze-cycle seal) has the same shape at coarser granularity.

The code is honest about its own limits (it refuses to backfill when
`previous_line is None`, so a market first seen already live gets no stamp at
all). **The field name is what is dishonest.** Every CLV number computed against
it inherits the cadence as error.

---

## 8. EVALUATION — CLV, ROI, accuracy

`[web]` 03:54:11Z:

| metric | value | attribution |
|---|---|---|
| `settled_count` | **0** | §7 — the grader produces ~nothing |
| `roi` | **null** | depends on settled |
| `avg_clv` | **null** | depends on settled **and** on a closing price that is a polling artifact (§7) |
| `win_rate` | **null** | depends on settled |
| `publish_count` | **0** | web reads 0 of 30 ledger dates (`#287`) |
| `total_pnl` | 0 | — |

**The feedback loop is open at every one of its three joints**: no graded rows
to settle against, no cross-disk path from a logged bet to the settler, and a
closing price whose accuracy is bounded by the poll interval.

Two consequences that are already load-bearing elsewhere:

- **`blended_score`'s `_SCORE_SIM_WEIGHT = 0.5` is a stated prior nobody has
  measured**, and S6's exit condition is *"no measurement, no weight."* With
  `rows_with_model_edge` at 0 on three of four active sports (§4), the sim term
  is inert anyway — the weight is currently multiplying null.
- **`#292`'s open question — does settlement grade against best price or the
  arbitrary retained book? — is not answerable from any surface reachable
  here.** It requires reading what `odds_refresh_tracking` stamped, on
  refresh-worker's disk. The stake is stated in `#275`: the single-book capture
  defect was platform-wide in three classes and best-price re-grading measured
  **+2.79 ROI points**, so if the stamp is the retained book, every cross-sport
  ROI number in this repo compares unlike with unlike. **Start at the writer,
  not at settlement.**

---

## 9. The whole contract, one table

Rows are stages; a cell is that sport's verdict. `—` = out of season with no
shard at the measurement hour, which is **MEANINGLESS**, not a failure.

| stage | mlb | wnba | soccer | nfl | nba | nhl | ncaaf | ncaab |
|---|---|---|---|---|---|---|---|---|
| 1 CAPTURE | **PASS** 44 books | PASS 18 books | PASS 11 books | PASS 11 books | — | — | — | — |
| 2 ROW BUILD | **PASS** | **PASS** | PASS grid / **FAIL** source (162/162 no market_key) | **PASS** | — | — | — | — |
| 3 ENRICH · projection | PARTIAL 19.7%, **0 edge** | **MEANINGLESS** (means only) **rendered silently** | PARTIAL 30.6%, reasons stated | **NO PRODUCER**, labelled | NO PRODUCER, labelled | NO PRODUCER, labelled | NO PRODUCER, labelled | NO PRODUCER, labelled |
| 3 ENRICH · game state | **FAIL** 5/15 events | PARTIAL 278/715 | **PASS** 720/720 | **FAIL** 0 chips | — | — | — | — |
| 3 ENRICH · margin | PASS 100% | PASS 100% | PASS 100% | n/a (two-sided) | — | — | — | — |
| 4 SELECTION | **FAIL** — 100 rows, 1 event, `pregame` on a live game, 21 h prices | drops 100% `stale_kickoff` `[HOUR]` | drops 100% `stale_kickoff` `[HOUR]` | **FAIL** — 100% `beyond_horizon`, structurally blind | absent | absent | absent | absent |
| 5 PRESENTATION | L1-A PASS; L2-A has **no UI consumer** | L1-A PASS | L1-A PASS | L1-A PASS | — | — | — | — |
| 6 BET LOGGING | **FAIL** — two ledgers, web disk ≠ worker disk | same | same | same | same | same | same | same |
| 7 SETTLEMENT | **FAIL** 1 graded row | **FAIL** — fix `17d4f203` undeployed | **FAIL** 0 in window | correctly 0 (no games played) | — | — | — | — |
| 8 EVALUATION | **FAIL** — 0 settled, ROI/CLV null | FAIL | FAIL | FAIL | — | — | — | — |

---

## 10. What this trace found that was not already written down

Ordered by what it would change.

1. **The L2-A shortlist is one in-progress game priced 21 hours stale and
   labelled `pregame`** (§4). Mechanism established end to end; absence of a
   game-state chip is mapped to the *permissive* value rather than to `unknown`.
2. **OddsAPI burn is at 155% of the 5M cap** and accelerated ~3.4× in the last
   day (§1). Endpoint's own projection. No §4d lever closes it alone.
3. **Both bet ledgers are per-service disk files; bets are logged on web and
   settled on refresh-worker** (§6). Makes the identity-key work necessary but
   not sufficient for user-logged bets.
4. **The settlement identity break is currently un-observable** because the
   grader supplies 1 row across 8 sport×date pairs (§7). Fixing the matcher
   alone settles 0 → 0.
5. **`/api/board/game-chips` ignores `sport`** — byte-identical 65-chip list for
   all eight sports (§3b).
6. **Soccer's `prop_source_in` is 162/162 missing `market_key`** (§2).
7. **NCAAF's grader reads a real joinable game id and drops it** before emitting
   the graded row (§0, Break 3). NCAAB emits no `odds` at all.
8. **The opportunity-contract metrics store is keyed on display labels**, not
   dates: `""`, `"2026 Prese"`, `"2025 Week "` (§2).
9. **WNBA's correct blank is indistinguishable from a defect on the row.** The
   `"null by design"` marker exists at the summary level only (§3a).
10. **`GET /api/board/book-grid?sport=mlb&limit=2000` reproducibly 502s**; web
    OOM-killed three times in the last 4.5 h at a 2 Gi limit (§5).

**Not filed as todo items yet.** Per the `#293` rule, an ID is claimed by
writing its stub in the same commit that claims it, and I have asked the lead
for a block rather than grepping for a free number — grepping has collided nine
times. These will be filed once IDs are allocated.

## 11. What was NOT measured, and why

Stated so nobody reads absence here as evidence.

- **Per-sport graded row counts over 07-19..08-08.** The grader runs only inside
  refresh-worker's process. Local returns 0 for all eight sports.
- **The live values of the two region env vars.** Needed to confirm `us2` has
  not leaked onto prop calls (§1).
- **Whether `closing_price` holds best-of-book or the retained book** (`#292`).
  Requires reading refresh-worker's disk.
- **L2-B (arbitrage) and L2-C (low hold) row counts.** The endpoints exist and
  share the row; their output was not sampled.
- **Whether a web-logged bet reaches refresh-worker's ledger.** Requires a
  production write (§6 names the experiment).
- **Soccer's grader field emissions.** `syndicate/features/soccer/actuals` was
  not opened; the settlement/matcher lane is active in that path.
- **Anything at a pregame hour.** Every figure is from 03:37–03:57Z. Several
  zeros marked `[HOUR]` would read differently at 18:00Z, and the §4 finding in
  particular should be re-measured mid-slate — it may be **worse** then, since
  more games are simultaneously live and unchipped.

## 12. Files read, so the next reader can start where this stopped

`plan_layer2_north_star.md` · `CLAUDE.md` · `docs/ai_context/todo.md`
(`#263 #268 #270 #275 #278 #279 #286 #287 #288 #289 #292 #293`) ·
`opportunity_gate.py` · `layer2_board.py` · `pipeline/layer2_shortlist.py` ·
`graded_outcomes.py` · `evaluation_settlement.py` · `intelligence_evaluation.py`
· `prediction_ledger.py` · `ledger_bridge.py` · `odds_refresh_tracking.py` ·
`blueprints/intelligence.py` · `blueprints/ops.py` · `static/shared/bet_slip.js`
· `render.yaml`.

**`#295`, `#296`, `#297` and `#299` are cited from their code and from the
brief, not from `todo.md`: none of the four appears in `todo.md` or
`todo_closed.md` at `a000e2e4`.** They are live in an unpushed tree — the third
staleness point named in the ninth-collision entry, encountered while writing a
document about identity. `#296` and `#297` are visible as uncommitted working-tree
changes in `pipeline/layer2_shortlist.py`, `blueprints/intelligence.py` and
`evaluation_settlement.py`.
