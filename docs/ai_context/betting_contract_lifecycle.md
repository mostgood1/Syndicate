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

---

## Read this first — the one instrument that already does the job

Every stage below is an exercise in telling three different zeros apart:

| verdict | meaning | cost of confusing it |
|---|---|---|
| **NO PRODUCER** | nothing computes this value for this sport | you go looking for a broken join that does not exist |
| **NOT JOINED** | a producer exists and its output does not reach the consumer | you build a producer that is already there |
| **MEANINGLESS** | the value cannot exist for this sport/market/state | you file a defect against correct behaviour |

**`unmatched_no_graded_rows` vs `unmatched_no_key_match`, on
`/api/ops/evaluation-settlement/status`, is the only thing in this system that
separates NO PRODUCER from NOT JOINED.** Every other surface renders both as one
zero. It is already built, it is in one place, and nothing else copies it. If one
sentence survives from this document, it should be that one — the pattern the
whole system needs already exists and is used once.

### Evidence-strength marker

Half of tonight's retractions were a structural proof reported as a live
observation. Every verdict below carries one of:

| marker | meaning |
|---|---|
| **`[live]`** | observed in production at a stated instant |
| **`[structural]`** | proven from code — it *cannot* work — but the failure was not observed running |
| **`[asserted]`** | taken from another lane's measurement, attributed, not re-derived here |

`[structural]` is not weaker than `[live]`; it is a different claim. A structural
proof that a game row can never match says nothing about whether a *normalization*
mismatch also exists — only the live half catches that.

### Provenance classes

- **`[web]`** — served by `syndicate-an21`, commit `b6ef6512`, reading web's own
  disk `syndicate-data-web`.
- **`[worker/kv]`** — refresh-worker's own view, reaching web through the
  keyvalue-backed `refresh_state_store`. The endpoint runs on web; **the numbers
  describe refresh-worker.**
- **`[code]`** — established by reading source and `render.yaml`, not by
  observing production.

**Local `data/**` was not used for any figure here.** It was tried first and is
empty: `graded_rows_for_date` returns **0 rows for all eight sports** across
2026-07-19..2026-08-08 on this checkout, and
`build_market_accuracy_payload('date=2026-08-05')` returns `days: []`. That is
CLAUDE.md's lossy-mirror trap and nothing here rests on it.

### Measurement window

All `[web]` and `[worker/kv]` figures are from **2026-08-09 03:37Z–04:06Z**, date
shard **2026-08-08**. At that instant the 08-08 MLB slate is 14/15 complete, the
WNBA and soccer slates are finished, and NFL is five days out. **Several zeros
below are correct for that hour and would be defects at 18:00Z.** Marked `[HOUR]`.

### Citation state of `#295`–`#299`

`#295`, `#296`, `#297` and `#299` **appear in neither `todo.md` nor
`todo_closed.md` on `origin/main` (`b6ef6512`)**, which carries `#290`–`#294`
only. Their entries are **written and stable in the L2-A / settlement-model
lane's working tree and are unpushed**, held by the user's commit hold. Content
cited here was confirmed with the coordinating session and is marked
**written, pending push**. An ID in a session's memory is not allocated, it is
remembered — **and one that is committed but unpushed is also remembered, just
more durably.**

---

## 0. The identity chain — the most important table in this document

A bet must stay joinable from the moment a book quotes it to the moment it is
graded. It does not. The chain uses **at least six identity vocabularies**.

| # | stage | identity key | vocabulary | source |
|---|---|---|---|---|
| 1 | CAPTURE | `event_id` + bookmaker + market + selection + line + `snapshot_ts` | **OddsAPI event hash** | `odds_book_quotes.py` |
| 2 | ROW BUILD | `(sport, event_id, market, segment, line, player_name)` → one market_instance, sides merged | OddsAPI hash | `book_grid.py` |
| 3 | ENRICH · game state | **team display name** | English names | `attach_game_state` |
| 4 | ENRICH · projections | **player name** / match | English names | `prop_projections`, `wnba_projections`, `soccer_projections` |
| 5 | SELECTION | `_IDENTITY_FIELDS` + `side` | OddsAPI hash | `layer2_board.py:60` |
| 6a | BET LOG · slip | `prediction_id` (uuid4), `recommendation_id` | opaque ids | `POST /api/portfolio/bets` |
| 6b | BET LOG · event | normalized **values** of {market, selection/pick/name, event_id, game_id, player, player_name, team, name, home, away} | mixed | `_evaluation_record_keys` |
| 7 | SETTLEMENT · graded | normalized **values** of {selection, player, team, home, away, title} | **English names only** | `_graded_row_keys` |
| 8 | MATCH | set intersection of normalized values → market compatibility → line equality | — | `match_graded_row` |
| 9 | BRIDGE B→A | `recommendation_id` | opaque id | `ledger_bridge.py` |
| — | MLB source truth | `game_pk` (e.g. `823834`) | **StatsAPI namespace** | `market_accuracy` |
| — | NCAAF source truth | numeric `id` | **CFBD namespace** | `graded_outcomes.py:547` |

### BREAK 1 — two identifier namespaces and no bridge between them

`[structural]`, `[asserted]` — `#299`, **written, pending push**.

**This is NOT "the join discards `event_id`".** That framing is wrong and was
retracted by the owning lane; it sends a reader hunting for a line of code that
does not exist. The corrected finding:

```
grep event_id|game_id|game_pk in graded_outcomes.py   ->  NO MATCHES
GRADED_OUTCOME_FIELDS                                 ->  no event identifier at all
MLB graded side    game_pk 823834                       <- StatsAPI
L2-A record side   event_id a22463fa1e60fc06243141f286915661   <- OddsAPI hash
```

**Nothing is thrown away. The two sides were never given a common identifier,
and the ids they do carry are in different namespaces.** It is a design gap
requiring a `game_pk ↔ event_id` bridge, not an omission requiring a one-line
fix. The bridge exists *implicitly* in the odds/board join — game-state chips
already match OddsAPI events to games — and is never exposed to settlement.

Consequence, measured on real production rows `[asserted]`:

```
GAME row key set -> {event_id, market}                    84 of 200 rows
                    neither type is EVER emitted by a graded row
                    -> empty intersection, structurally, always
PROP row key set -> {event_id, market, 'sonia citron'}
                    the player name is the ONLY viable key
```

Corroborated independently `[live]` `[worker/kv]`: `missing_event_identity` is
**0 across every sport and every stage** of `opportunity_contract_metrics_v1`
(§2). Event identity is present all the way through the recommendation side. It
simply has nothing to meet.

### ⚠ DO NOT ADD `market` TO THE GRADED KEY SET

This nearly shipped as the obvious fix and it manufactures silent wrong
settlements.

**Only identifier-shaped keys are safe in a value-intersection join.**
Category-shaped tokens are shared by every row of their type. Add `market` and a
record for one game overlaps a graded row for a **different** game on `h2h`
alone; `_markets_compatible` then passes (same market); and `h2h` has no line, so
the line check cannot catch it. The result is a settlement that is **wrong and
looks identical to a right one** — strictly worse than no match, because a
no-match is visible in `unmatched` and a false match is not.

The same argument rules out `market_family`, `segment`, `side`, and any other
enum. Teams and player names are the shared vocabulary because they are
identifier-shaped in practice.

### BREAK 2 — prop rows join on a single string

With `event_id` unable to meet anything and the market token correctly excluded, a
prop record's only viable key is the player name. It works because names happen
to be unique and to agree between two independently-built sources. Nothing
enforces either property.

### BREAK 3 — the graded contract has no slot for an identifier at all

`[code]`. `_ncaaf_graded_rows_for_date` reads CFBD's numeric game id, uses it for
its own dedup (`seen_game_ids`), and does not place it on the emitted row.

**Read this as evidence for Break 1, not as a second fix.** Emitting it would
bridge nothing — CFBD is a *third* namespace, no closer to the OddsAPI hash than
`game_pk` is. The point is that `GRADED_OUTCOME_FIELDS` has **no event-identifier
field for it to go in**, so even where a source id exists and is in hand, the
contract has nowhere to put it. That is the design gap stated from the other end.

### Per-grader identity emissions

`[code]`, `graded_outcomes.py`.

| sport | grader | event id | `title` | `home`/`away` | `team` | `player` | `odds` |
|---|---|---|---|---|---|---|---|
| mlb | `_mlb_graded_rows_for_date` | **none** | yes | **no** | yes | yes | yes |
| wnba / nba / nhl | `_local_market_accuracy_...` | **none** | **no** | games only | props only | props only | yes |
| nfl | `_nfl_graded_rows_for_date` | **none** | yes | yes | **no** | n/a | yes |
| ncaaf | `_ncaaf_graded_rows_for_date` | **none emitted** (CFBD id read, not carried) | yes | yes | **no** | n/a | yes |
| ncaab | `_ncaab_graded_rows_for_date` | **none** | yes | yes | **no** | n/a | **no** |
| soccer | `soccer/actuals` | not inspected — settlement lane owns this path | | | | | |

Two consequences the aggregate hides:

- **MLB emits `team` + `title` and never `home`/`away`; NFL/NCAAF/NCAAB emit
  `home`/`away`/`title` and never `team`.** A record normalized into one
  vocabulary matches one group of sports and not the other. `#297`'s
  `normalize_portfolio_event_identity` fills `home`, `away` **and** `team` — that
  is load-bearing, not belt-and-braces.
- **NCAAB emits no `odds` at all.** Its rows carry `result` and no price, so
  `_pnl_for_settlement` has nothing to compute a return from. NCAAB can be graded
  and can never be priced. Dormant until November.

---

## 1. CAPTURE

### Books and regions — S0b is lit, and the expensive mistake did NOT happen

`[live]` `[web]` 03:37Z:

| sport | distinct books | evidence of the extra regions |
|---|---|---|
| **mlb** | **44** | `pinnacle`, `betfair_ex_eu`, `matchbook`, `kalshi`, `polymarket`, `novig`, `prophetx`, `espnbet`, `hardrockbet`, `fliff`, `rebet` |
| wnba | 18 | `us` + `us2` shape only |
| soccer | 11 | `us` shape only |
| nfl | 11 | `us` shape only |
| nba / nhl / ncaaf / ncaab | 0 | no shard `[HOUR]` |

**Live env-vars, all three services** `[asserted]`, read by the coordinating
session via `/v1/services/<id>/env-vars`:

```
                                        web        refresh    live-odds
SYNDICATE_LIVE_ODDS_REFRESH_REGIONS     us         us         us
SYNDICATE_LIVE_ODDS_GAME_LINE_REGIONS   eu,us_ex   eu,us_ex   eu,us_ex
SYNDICATE_LIVE_ODDS_PROP_REGIONS        <ABSENT>   <ABSENT>   <ABSENT>
```

**Props are on `us` only. The extra regions are game-line-scoped, exactly as
S0b's nine tests were written to enforce.** The single most expensive
misconfiguration available — `us2` leaking onto per-event prop calls, ~1M
credits/month — **is ruled out by direct measurement.** Recorded with the values
so nobody re-opens it.

**Confirmed from the data side too, which is the stronger test.** `[live]`
04:19Z, comparing a **prop** market (base regions only — `_game_line_regions`
merges the extras into the game-line call *only*, `fetch_mlb_oddsapi_local.py:1564`)
against §4d's published region→book mapping:

```
batter_total_bases (PROP, us only), 14 distinct books
  eu-labelled present     : NONE
  us_ex-labelled present  : NONE
  us2-labelled present    : ballybet betparx espnbet fliff hardrockbet hardrockbet_oh rebet
```

**Zero `eu` and zero `us_ex` books reach a prop row.** The ~1M/month guard holds
in the data, not just in the env block.

**And that resolves the loose thread: those seven are not `us2`-only books.**
They arrive on prop calls under a base list of `us` with no `PROP_REGIONS`
override and no path that could add a region to a prop fetch — so they are in
`us`. **§4d's region→book mapping is stale** (it was queried once, 2026-08-07, at
1 credit per region). That matters beyond bookkeeping: §4d prices `us2` at
**+2,004,942/month** on the reasoning that *"`us2` costs real money because its
value is prop price-shopping"* — and seven of its eight books are already
arriving free on `us`. **Re-query the region→book mapping before anyone buys
`us2`.** Not filed as a defect; recorded as a costed assumption that no longer
holds.

### Why only MLB has the wide grid — and what it does to fair value

`[code]`. The env block above is set on **all three services**, yet only MLB
returns `eu`/`us_ex` books. The reason is not policy:

```
12 OddsAPI fetchers in scripts/
SYNDICATE_LIVE_ODDS_GAME_LINE_REGIONS / _game_line_regions appear in EXACTLY ONE
  -> scripts/fetch_mlb_oddsapi_local.py:1564
every other sport reads only the base list
  -> live_refresh_loop.py:2711 and ops_refresh.py:1223, both defaulting to "us"
```

**The S0b split is a per-sport *implementation*, present once, not a per-sport
scope.** The variable is configured platform-wide and read by one fetcher.

**The consequence is the part that matters, and it is not about cost.** The
`eu`/`us_ex` books are the **fair-value anchors** — `pinnacle`, `betfair_ex_eu`,
`matchbook` — and they reach **MLB and no other sport**. The North Star's own
stated follow-up to S0b is *"make `consensus_fair_probability` PREFER the sharp
books, or Pinnacle/Betfair are three votes among thirty-eight."* **That work is
structurally MLB-only until the extras are threaded into the other eleven
fetchers**, because for wnba, soccer, nfl and the rest there is no sharp book in
the pool to prefer. Their `no_vig_fair` is a consensus of US retail — and §2
shows soccer reaching a two-sided consensus on only **10.3%** of rows to begin
with.

Not filed as a defect: nothing is broken and the scoping may be deliberate. But
it is a **silent per-sport asymmetry in fair value**, and fair value is the input
that every EV, edge, hold and arbitrage number downstream is computed against —
so a cross-sport comparison of any of those is comparing a sharp-anchored MLB
number against a retail-anchored one everywhere else.

**Where that does and does not reach L2-A — read `select_shortlist` before
extending this.** `[code]` The obvious inference is that the cross-sport
shortlist ranks sports against each other on incomparable EV. **Half of that is
wrong, and it is the alarming half:**

| step | cross-sport? | verdict |
|---|---|---|
| bucketing (`layer2_board.py:793`) | **no** — `by_sport`, `per_sport = 100` and `kind_floor = 30` **each** | a soccer row never loses a slot to an MLB row |
| value floor (`:813` → `_measured_floor_for_pool`, `:228`) | **no** — floor = `multiple × median best-price hold`, **from that sport's own pool** | **partially self-correcting**: hold is a property of the book set, so sharper books → lower hold → lower floor |
| final ordering (`:851`) | **YES** — `selected.sort(key=_score_of, reverse=True)` over every sport at once | **this is the real exposure** |

So it is an **ordering** effect, not a **selection** effect. With
`score.sim_component` null on 100/100 measured rows, `_score_of` is EV-driven,
so a shifted EV baseline moves a sport's rows up or down the *displayed* list.

**Direction and magnitude are unmeasured and are not guessed here.** A sharp
anchor yields a tighter no-vig fair, and whether that raises or lowers apparent
EV depends on which side is priced.

**It has also never been observed.** `active_sports: ["mlb"]` throughout this
trace — one sport — so **cross-sport ordering did not occur at any point that
was measured.** `[code]`, not `[live]`.

### Cost — the 155% reading is real and the window is contaminated

> **HEADLINE, so it is not quoted without its caveat: `projected_30d_credits =
> 7,737,455 = 155% of cap` is a true reading of a 27.6-hour window that
> CONTAINS A KNOWN INCIDENT. The standing rate is the 12-day aggregate —
> 74,870/day = 2.25M/month = 45% of cap — and even that includes the incident,
> so the real baseline is BELOW 45%. Do not carry "the cap is exhausted in 19.4
> days"; it is not supported.**

`[live]` `[web]` `GET /api/ops/oddsapi/quota`, 03:54:31Z. The 30-day projection
is the endpoint's own field.

```
aggregate since 2026-07-28T02:36Z (12.05 d)   902,524 cr    74,870/day   2.25M/30d    45% of 5M
recent window (27.6 h, ends 03:54Z)           296,697 cr   257,916/day   7.74M/30d   155% of 5M
projected_30d_credits (reported)                                         7,737,455   155% of 5M
```

S0 measured **62,076/day = 37.2%** on 2026-08-07. The window is **4.15×** that.
The header's `remaining: 14,187,817` is not real; every percentage is against 5M.

**The window contains a known incident.** refresh-worker ran an unbounded
process-spawn leak from ~22:35Z to 00:51Z (up to **26 concurrent
`refresh_odds_sources` processes**) plus **nine OOM kills each followed by a
fresh boot**, and every process and every reboot re-runs odds fetches. That is
entirely inside the 27.6-hour window `[asserted]`.

**Discriminator — the current rate, sampled `[live]` from `latest.used`, using
`observedAt` rather than read time:**

```
03:40:13 -> 04:04:38   +108 cr / 24.4 min  =   265 cr/h
04:04:38 -> 04:05:44   + 14 cr /  1.1 min  =   764 cr/h
04:05:44 -> 04:11:22   + 54 cr /  5.6 min  =   575 cr/h
04:11:22 -> 04:15:51   + 40 cr /  4.5 min  =   535 cr/h
OVERALL                +216 cr / 35.6 min  =   364 cr/h

hour-weighted expectation from the 12d aggregate  =  1,263 cr/h   -> measured 0.29x
window mean                                       = 10,554 cr/h   -> 29x the current rate
12d daily average                                 =  3,120 cr/h
```

**The current rate is 0.29× its own hours' historical norm — not 3.4× above it.**

**The internal inconsistency is the actual argument**, and it does not depend on
trusting any single sample. A window mean taken over a *full diurnal cycle*
should land near the daily average. Instead:

```
window mean            = 3.4x  the 12-day daily average
same clock hours NOW   = 0.29x the 12-day norm for those hours
```

**A uniform structural increase cannot produce both. A burst confined to part of
the window can** — which is the shape of the spawn incident.

Two caveats that keep this honest:
- The 12-day baseline **includes the incident night**, so the 1,263 cr/h
  expectation is inflated and 0.29× is *generous* to the structural hypothesis.
- **The trough is the weakest hour to test in.** 364 cr/h at 04:00Z does not
  prove the 22:00Z peak is normal. **The decisive test is a peak-hour comparison
  against the same clock hours on a prior day**, and the quota endpoint has **no
  per-day breakdown**, so it cannot be run from this surface. Listed in §11.

**Bottom line for a spend decision:** the 155% is a real reading of a
contaminated window. The defensible standing rate is the 12-day aggregate at
**45% of cap**, itself an upper bound. **The 19.4-day exhaustion figure that
follows from 257,916/day is withdrawn** — it was a true measurement carrying an
unearned inference, which is the same shape as the retractions this file has
been collecting all night.

Cost structure — S0's shape holds, and the multiplier is on call count, not on
cost per call:

| family | credits | share | | sport | credits | share | credits/call |
|---|---|---|---|---|---|---|---|
| props | 417,572 | 46.3% | | **mlb** | 859,100 | **95.2%** | 7.2 |
| segment | 302,593 | 33.5% | | soccer | 36,571 | 4.1% | 1.3 |
| alternate | 151,327 | 16.8% | | wnba | 6,292 | 0.7% | 6.1 |
| full_game | 29,952 | 3.3% | | nfl | 561 | 0.1% | 0.4 |
| **per-event-billed** | | **96.6%** | | (S0: 95.5%) | | | |

Soccer makes 27,547 calls for less credit than WNBA's 1,035. The
cheap-lever-hiding-in-soccer hypothesis stays falsified.

§4d prices the game-line region add at **+30,378/month ≈ 1k/day**. It cannot
produce a 196k/day increase. **The regions are not the cause.**

**No §4d lever gets 155% under 100% alone.** L1+L2 together were priced at ~47%
off, taking 7.74M to ~4.1M — the entire savings plan spent to return to where
S0b's projection started.

`by_hour_utc` (aggregate) peaks at 22:00Z = 154,942 against a 04:00Z trough of
6,073 — a **26× diurnal swing**. §4d's L4 off-hours gate has the clearest measured
shape and the smallest headline.

### Cadence and date-sharding

| sport | cadence evidence | shard key |
|---|---|---|
| mlb game lines | `h2h_lay` `observed_at` 03:39:57Z, read 03:44Z → **4 min** `[live]` | local date |
| mlb props | best-cell ages on one event span **0.09 h – 14.95 h** `[live]` | local date |
| mlb, first capture of a date | **~06:43Z** `[asserted]` (`#296`) | local date |
| soccer | not measured | **fixture date** (`#239`) — a today-only puller 404s and logs "absent" |
| wnba / nfl | not measured | local date |

The prop-vs-game-line cadence split is §4c's cost structure working as designed:
props bill per event and cannot be polled at game-line rates. **It becomes a
defect only downstream, where a 21-hour prop price is admitted to a ranked
recommendation surface without being labelled stale** (§4).

**Two capture paths with different region scope** `[live]`: the orchestrator run
at 03:39:56Z shows `--sports mlb,wnba --phase live --regions us`, while the MLB
grid carries 44 books. `refresh_odds_sources.py` and the live-refresh loop are
not configured alike. Not diagnosed; flagged because a reader comparing them sees
contradictory region sets and neither is wrong.

---

## 2. ROW BUILD — the canonical `market_row`

`[live]` `[web]` 03:37–03:56Z, first 400 rows of each sport's grid.

| field | mlb | wnba | soccer | nfl | others |
|---|---|---|---|---|---|
| rows in slate | **6,641** | 715 | 727 | 1,351 | **0** `[HOUR]` |
| `event_id` | 400/400 | 400/400 | 400/400 | 400/400 | — |
| `market` / `segment` | 400/400 | 400/400 | 400/400 | 400/400 | — |
| `line` | 370/400 | 373/400 | 172/400 | 170/400 | — |
| `player_name` | 148/400 | 350/400 | 336/400 | **0/400** MEANINGLESS | — |
| `home_team`/`away_team` | 400/400 | 400/400 | 400/400 | 400/400 | — |
| `commence_time` | 400/400 | 400/400 | 400/400 | 400/400 | — |
| `cells` / `best` / `consensus` | yes | yes | yes | yes | — |

**ROW BUILD is the healthiest stage in the system.** Identity is complete on
every sport with a shard. NFL's `player_name 0/400` is **MEANINGLESS** — its grid
is 400/400 `kind: game`.

### Grid width

| sport | rows | 3+ books | two-sided | single-book | best flagged stale |
|---|---|---|---|---|---|
| mlb | 6,641 | 64.1% | 83.9% | 1,623 | 472 |
| wnba | 715 | 41.5% | 94.0% | 266 | 34 |
| soccer | 727 | **13.2%** | **10.3%** | 557 | 1 |
| nfl | 1,351 | 16.2% | 100.0% | 614 | 0 |

Soccer is the thinnest grid on the platform. The margin model covers it (§3c),
but a real two-sided consensus is unavailable on ~90% of soccer rows.

### The one measured row-build identity break

`[live]` `[worker/kv]` `opportunity_contract_metrics_v1`, `service_role
refresh-worker-4tx2`, generated **03:55:54Z**:

| sport | date key | stage | rows | complete | with_quote | miss_event | **miss_market_key** | miss_entity |
|---|---|---|---|---|---|---|---|---|
| mlb | 2026-08-08 | game_candidate | 38 | 38 | 38 | 0 | 0 | 9 |
| mlb | 2026-08-08 | intelligence_game | 91 | 91 | 38 | 0 | 0 | 13 |
| mlb | 2026-08-08 | intelligence_prop | 30 | 30 | 26 | 0 | 0 | 0 |
| mlb | 2026-08-09 | game_candidate | 53 | 53 | **0** | 0 | 0 | 4 |
| **soccer** | 2026-08-08 | **prop_source_in** | **162** | **0** | 0 | 0 | **162** | 0 |
| wnba | 2026-08-08 | intelligence_prop | 11 | 11 | 11 | 0 | 0 | 0 |
| wnba | 2026-08-08 | intelligence_game | 4 | 4 | 0 | 0 | 0 | 4 |
| nfl | *(empty)* | game_candidate | 32 | 32 | 0 | 0 | 0 | 32 |
| nfl | 2026-08-08 | intelligence_game | 16 | 16 | 0 | 0 | 0 | 16 |
| nba / nhl / ncaab / ncaaf | 2026-08-08 | all | 0 | 0 | 0 | 0 | 0 | 0 |

- **`#305` — soccer `prop_source_in`: 162 rows, 162 missing `market_key`, 0
  complete.** Every soccer prop source row fails the contract at the market-key
  check. **NOT JOINED**, at 100%, not a tail.
- `missing_entity_name` on game candidates is **MEANINGLESS** — a game line has
  no entity.
- `missing_event_identity` is **0 everywhere** — the fact that makes Break 1 a
  pure namespace gap rather than a loss.
- **Date keys are display labels, not dates**: `nfl` under an *empty* key and
  under `"2026 Prese"`; `ncaaf` under `"2025 Week "` — a stale season year with
  the week number missing, still present after `#289` flagged it. A metrics store
  keyed on a truncated display string cannot be joined to a date.

---

## 3. ENRICHMENT

### 3a. Projections — where "a zero must be attributable" is won and lost

`[live]` `[web]` 03:37Z.

| sport | `supported` | rows considered | with projection | **with edge** | blanks carrying a reason | verdict |
|---|---|---|---|---|---|---|
| **mlb** | true | 6,641 (grid) / 3,604 (ingest) | 1,308 = **19.7%**; 117/400 slice | **0** | **117 of 117** say *"game is final: a pregame projection cannot be priced against a live market"*. **283 of 400 carry no projection and no reason.** | mixed |
| **soccer** | true | 727 / 720 | 222 = **30.5%**; 96/400 slice | 2 | 37 *"one-sided market: no two-sided fair to price against"*, 4 *"3-way market: two-leg de-vig would drop the draw"*, **55 unattributed** | best attribution on the platform |
| **wnba** | true | 563 / 494 | 71 = **12.6%**; 35/400 slice | **0** | **0 of 35.** `probability_fields: "null by design -- means only, no distribution"` exists **only at the summary level, never on the row** | **MEANINGLESS, rendered as silent** |
| **nfl** | **false** | — | 0 | 0 | `reason: "no projection source wired for nfl"` | **NO PRODUCER**, correctly labelled |
| nba / nhl / ncaaf / ncaab | **false** | — | 0 | 0 | `"no projection source wired for <sport>"` | **NO PRODUCER**, correctly labelled |

**Two denominators, and they are not the same.** The serve-time grid and the
persisted shortlist run the *same* `attach_projections` over the *same* shard and
report different `rows_considered`: mlb 6,641 vs 3,604, wnba 563 vs 494, soccer
727 vs 720. `build_layer2_shortlist` passes `max_grid_rows_per_sport`, which the
endpoint does not. **Quote whichever you like, but say which** — the same sport is
19.7% projected on one surface and 18.6% on the other and neither is wrong.
`#275`'s rule: *put the n in the number.*

**Three different zeros in one column, and only two are stated on the row.**
WNBA's blank `Edge` is correct — its source is a per-player mean block with no
distribution, so no probability-space edge exists (`#263`'s ladder: MLB full
distribution → soccer probability at some lines → WNBA means only → NFL nothing).
A reader sees the same blank cell a defect would produce.

MLB's zero splits cleanly, and the split is the finding:

```
400 MLB grid rows
  117  projection present, edge blocked, REASON STATED  -> attributable, correct at this hour
  283  no projection at all, NO reason                  -> silent
    0  edge present
```

The discriminator is live and reachable —
`per_sport_ingest.enrichment.projections` and the grid's `projections` block —
and is surfaced nowhere a person reading the board can see it. That is `#263`'s
open half.

### 3b. Game state — the join that fails, and it is not random

`[live]` `[web]` 03:37–03:56Z.

| sport | chips found | grid rows matched | slice `game.state` |
|---|---|---|---|
| **mlb** | **5** | 1,220 / 3,604 | 149 / 400 |
| soccer | 61 | 720 / 720 | 400 / 400 |
| wnba | 1 | 278 / 715 | 147 / 400 |
| nfl | **0** (`reason: no_chips_for_date`) | 0 / 1,351 | 0 / 400 |

**MLB joins 5 of the 15 events on its own grid, and the 5 are the earliest:**

```
19:05Z  ATL @ NYY   YES      23:10Z  CHC @ KC     no
20:11Z  ATH @ BOS   YES      23:11Z  MIN @ MIL    no
20:11Z  LAA @ MIA   YES      23:16Z  BAL @ TEX    no  (+4 more at 23:16Z, all no)
22:06Z  TOR @ PHI   no       00:11Z  LAD @ ARI    no
22:41Z  NYM @ PIT   YES      01:50Z  TB  @ SEA    no   <- the whole L2-A shortlist
22:46Z  CIN @ WSH   YES
```

Every game from 23:10Z onward has no chip. **MEANINGLESS is unavailable as an
explanation** — these are real games on the same grid, with quotes, on the same
date. **NOT JOINED.**

**`#301` — `/api/board/game-chips` ignores its `sport` parameter.** `[live]` All
eight sports plus the no-argument case return a byte-identical 65-chip list (same
SHA-1 over the matchup sequence), mixing MLB finals, MLS fixtures dated Aug 1–2,
and NCAAF out to Aug 28. **The enrichment is correctly sport-aware** — mlb 5 /
soccer 61 / wnba 1 / nfl 0 — **so this is the debug endpoint's parameter being
inert, not the join.** Stated explicitly so nobody re-derives it. Severity is
contextual: this is the surface someone reaches for to diagnose `#300`, and it
would make an MLB-shaped defect look sport-wide.

### 3c. Margin model

`[live]` `[web]` 03:37Z.

| sport | one-sided rows | modelled | median hold | books profiled | observations |
|---|---|---|---|---|---|
| mlb | 1,071 | **100.0%** | 6.48% | 44 | 28,714 |
| wnba | 43 | **100.0%** | 6.66% | 18 | 2,088 |
| soccer | 652 | **100.0%** | 4.54% | 11 | 267 |
| nfl | 0 | n/a (100% two-sided) | 4.55% | 11 | 2,829 |

**PASS on every sport with a shard.** S4 working. Soccer's profile rests on 267
observations against MLB's 28,714 — thin, but stated, and labelled
`book_margin_model` so it is never confused with a two-sided consensus.

---

## 4. SELECTION — `opportunity_gate`, `blended_score`

`[live]` `[web]`, artifact `written_at 03:43:22Z`, read **03:44:28Z**.

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

- **NFL: 2,702 of 2,702 dropped as `rows_beyond_horizon`.** §4b's *"weekly sports
  have no today"* made concrete: **L2-A is structurally NFL-blind at the default
  scope.** §4b names the fix — scope is a `commence_time` filter over the same
  row, not a pipeline fork. Attributable, correctly reported, real product gap.
- **soccer and wnba: 100% dropped as `rows_stale_kickoff`.** Correct `[HOUR]`.
- **nba/nhl/ncaaf/ncaab: absent from `per_sport_ingest` entirely** — out of
  season, but *absent* is a weaker signal than zero-with-a-reason, which is
  exactly what `#296`'s `sweep_state` contract now provides.
- **`rows_with_model_edge`: 0 for MLB, NFL, WNBA; 4 for soccer.** `blended_score`
  runs on EV alone on effectively every ranked row. The differentiator does not
  reach the ranking. `layer2_shortlist.py:128-134` states the consequence: under
  proportional de-vig, EV is `1/overround - 1`, **identical for every side of a
  market**, so the board ranks markets by hold and picks a side by tie-break.

**`rows_below_value_floor: 0` does not mean the floor is inert.** `[code]` The
floor is not the flat `min_value_pct: -2.0` the payload reports at top level —
that is only the *fallback*. `_measured_floor_for_pool` (`layer2_board.py:228`)
derives a floor **per sport, from that sport's own pool**: regroup the one-side
rows back into markets, take each market's best-price hold, and set the floor at
`hold_multiple × median`. It reports its own evidence in `value_floor_by_sport`,
and it falls back to the flat value only when too few markets carry two sides —
*"which is not hypothetical"*, per its docstring, for exactly soccer's 10.3%
two-sided rate (§2).

Worth knowing for two reasons beyond this table. It is one of the few thresholds
in the repo that **measures itself and shows its working** rather than carrying a
constant. And it is what keeps §1's fair-value asymmetry from becoming a
selection bias — hold is a property of the book set, so a sharper book set lowers
the hold *and* the floor together.

### `#300` — the entire cross-sport shortlist is one in-progress game priced 21 hours stale

`[live]`, artifact rebuilt 03:43:22Z, read 03:44:28Z:

```
rows                                  100
distinct event_id                       1     <- Tampa Bay Rays @ Seattle Mariners
commence_time                    01:50:00Z     (~1.9 h IN PROGRESS at read time)
market_state                       pregame     100/100
gate.reasons                            []     100/100
quote.suspect_stale                  False     100/100
quote.book_age_seconds    21.00 / 21.01 / 21.03 h   (min / median / max)
model_edge_pct, score.sim_component   null     100/100
```

**Each link measured separately:**

1. TB @ SEA is one of the 10 MLB events with **no game-state chip** (§3b). Its
   grid rows carry `game: {}`.
2. `layer2_board.py:494` sets `game_state`/`is_live` **inside `if game:`**. No
   game → neither is ever set.
3. `opportunity_gate.game_state_of` reads `row.get("game_state")`, gets `""`, and
   `""` is in `_PREGAME_TOKENS` → returns **`pregame`**. **Absence is mapped to a
   value, and it is the permissive one.**
4. `pregame` selects `PREGAME_MARKET_MAX_AGE_SECONDS = 86_400` instead of
   `LIVE_MARKET_MAX_AGE_SECONDS = 900`. 75,600 s < 86,400 → admitted, with an
   **empty `reasons` list** — the gate was built so nothing is dropped silently,
   and it reported no reason because on its own terms nothing was wrong.
5. Under a correct `live` label, all 100 rows are `LANE_DEAD /
   live_market_stale`.

**Same-instant control**, 03:44:27Z, same shard, same functions: that event's
L1-A `h2h_lay` row is `updated_at 03:39:57Z`, best-cell age **258.3 s**,
`lag_behind_freshest_seconds` **1.0**. **Fresh grid, 21-hour shortlist, same
second.** Without this control the finding reads as "everything is stale" and is
correctly dismissed.

**What is NOT claimed.** `book_age_seconds` is `side_best["age_seconds"]`, the
grid's own field, unmodified (`layer2_board.py:479`). Prop markets legitimately go
long between polls — measured on this same event, `batter_total_bases` best-cell
ages span 0.09 h – 14.95 h. **The 21-hour stamp is honest. The defect is that a
21-hour price is admitted, ranked, and reported `suspect_stale: false`** — not
that it is recorded. Two different bugs; only one is real.

**Third instance of one shape tonight.** Soccer's `_has_usable_game_state` keyed
on presence and a settled match returned to #1 on the live board; the `Live`
column is blank on 25 soccer rows for the same `if game:` reason; now
`game_state_of` maps absence to `pregame`. **Absence is not a state, and every
time this codebase treats it as one it picks the permissive reading.**

That `layer2_shortlist.py:128-131` *predicts* this — *"Absent, every row looks
pregame and a SETTLED MARKET CAN RANK"* — makes it worse, not better. The author
knew. Nobody measured whether it was happening. And the cause is **upstream of
the enrichment call**: the chips do not exist to be joined, so enrichment can
neither be blamed nor fix it.

### The 15 board columns

`[live]` against 100 rows. The `[asserted]` 200-row measurement is consistent.

| column | status | correct blank? |
|---|---|---|
| title / prop line / matchup / odds / edge (EV) / state badge / team (game rows) | populated | — |
| `Live` | 98/100 carry `quote_seen_age_seconds` | — |
| **`Projected`** | absent from the served row | **NO** — `#270`'s cheap join; the working tree now copies `projection` onto the candidate, the artifact does not yet carry it |
| **`Win%`** | blank | **YES for wnba/nfl** — no distribution exists. **NO for mlb** at a pregame hour |
| **`Edge` (model)** | null 100/100 | **YES where `Win%` is** — it depends on it |
| **`Actual`** | blank | **YES** — has not happened on an unsettled row |
| **`Move`** | absent | **NO** — `line_odds_movement` has no source on an L2-A row |
| confidence badge | **do not map** | `book_confidence` is `{1.0, 0.85, 0.7, 0.5}`; a `>= 0.7` badge fires on 68/100. It means "how many books quote this", not model confidence |

**Three of these blanks are correct behaviour and the next reader will file them
as defects.** That is why they are named.

---

## 5. PRESENTATION

| board | endpoint | is it a projection over `market_row`? | verdict |
|---|---|---|---|
| **L1-A** book grid | `/api/board/book-grid` | **yes** — serve-time pivot on `cells`, no quality filter | **PASS**, the reference surface |
| **L1-B** advanced | — | `projection` is on the grid row; no dedicated view | S3 incomplete |
| **L2-A** best bets | `/api/board/layer2-shortlist` | yes | served, but see `#300` |
| **L2-B** arbitrage | `/api/board/cross-book` | yes | not measured |
| **L2-C** low hold | same row, ranked by hold | yes | not measured |

**`#302` — the L1-A serve-time pivot has no payload ceiling.** `[live]`
`book-grid?sport=mlb&limit=2000` **502s reproducibly**; `limit=600` with a
`market=` filter is fine. Web `oomKilled {memoryLimit: 2Gi}` at **03:35:33Z**,
**23:44:04Z** and **23:38:37Z** per the Render events API. The North Star calls
this pivot *"the largest visible win available"* — **it ships with a cap or it
ships an outage.** Characterised and deliberately not probed further; a fourth
502 costs the service and buys nothing.

**L2-A has no UI consumer** `[asserted]` (`#268`): `home.py` has zero references
to `layer2`/`shortlist`, and nothing in `templates/`/`static/` fetches the
endpoint. Everything in §4 describes an endpoint, not a rendered board. **Verify
the rendered page; an endpoint returning 200 with rows is not a board.**

**The North Star is silent on home-page composition.** It specifies five boards
and a scope selector and says nothing about what the home page shows or in what
order. That gap is not filled here.

---

## 6–8. BET LOGGING, SETTLEMENT, EVALUATION

**Stages 6–8 are owned by the L2-A / settlement-model lane.** Cited, not
re-derived. Their entries are **written, pending push**.

### 6. Two ledgers — `#304`

| | **Ledger A — portfolio** | **Ledger B — evaluation** |
|---|---|---|
| written by | `POST /api/portfolio/bets` (`bet_slip.js:206`) | `POST /api/intelligence/portfolio-event` **and** `maybe_record_board_state_to_evaluation_ledger` |
| file | `data_root()/prediction_ledger.json` | `reports_root()/intelligence/evaluation_ledger_chunks/<date>.jsonl` |
| IO | `read_text` / `write_text` | `open("a")` — **neither uses the keyvalue store** |
| read by | `/portfolio` | **never by `/portfolio`** |
| settled by | `prediction_reconciliation` autorun | `evaluation_settlement` autorun |
| identity | `prediction_id`, `recommendation_id` | normalized value tokens |

`ledger_bridge.py` exists solely to cross this split, copying outcomes B → A on
`recommendation_id`. Its docstring: both autoruns were enabled and *"Production
still showed `settled_count: 0` on five tracked bets."*

**The disk split** `[structural]` `[code]`. `render.yaml` mounts **three separate
50 GB disks at the identical path**:

```
web              syndicate-data-web              /opt/render/project/data
refresh-worker   syndicate-data-refresh-worker   /opt/render/project/data
live-odds-worker syndicate-data-live-odds-worker /opt/render/project/data
```

Both ledgers use plain filesystem IO. Both logging routes run on **web**. Both
settlement autoruns run inside `run_refresh_worker.py` on **refresh-worker**.
**Same path string, different disk — which is why it looks correct in both
processes. Compare the DISK, not the path.**

**Same-instant corroboration** `[live]`, 03:54:10–03:54:11Z:

```
/intelligence/api/opportunity-board   records 0   publish_count 0   settled_count 0   clv null
/api/portfolio/summary                total_tracked 0   pending_count 0   settled_count 0
refresh-worker's own view [worker/kv]  total_recommendation_records 8,276
```

Web sees **0**; refresh-worker holds **8,276**.

**The 8,276 are worker-written board-state records**, on the settler's own disk,
settleable in principle. **Whether a web-logged bet crosses is `[structural]`,
not `[live]`** — observing it requires a production write, outside a read-only
brief.

> **The experiment, specified so someone else can run it:** log one bet via
> `POST /api/intelligence/portfolio-event` on web, then read
> `chunk_diagnostics.<date>.line_count` from
> `/api/ops/evaluation-settlement/status` before and after. If it does not move,
> the split is confirmed by measurement.

**Why this reorders `#297`.** If a web-logged bet never reaches the settler's
disk, **the key mismatch is the second thing that would stop it**, and a mapping
that makes keys intersect on a record that never arrives fixes nothing.

### 7. Settlement

`[live]` `[worker/kv]`, autorun epoch **2026-08-06T11:03:17Z — three days stale**.

```
total_recommendation_records   8,276      matched 0     settled 0
  unmatched_no_graded_rows     3,716      <- NO PRODUCER
  unmatched_no_key_match       4,560      <- producer exists, keys disjoint

graded_rows_available:  mlb:08-05 = 1  ... every other sport x date = 0
```

**One graded row across eight sport×date pairs, and it is a `moneyline` that
`_markets_compatible` rejects for every prop record regardless of keys.** The
4,560 "no key match" failed against a pool of size one.

**This is the caveat that reorders the settlement work, and it cuts against the
lane whose finding I am documenting: fixing the matcher alone settles 0 → 0.**
The graders not producing is the binding constraint; the key mismatch is real and
second in line. The owning lane's own conclusion agrees — the matcher is not the
problem, coverage is, and the cause sits a layer further out.

**`#297` is `[structural]`, NOT `[live]`.** The owning lane could not run the
live half: `graded_rows_for_date` returned **0 rows for wnba, soccer and mlb on
08-08** — settlement autorun is off and tonight's seal is damaged. **The
structural half proves a game row *cannot* match; only the live half would catch
a normalization mismatch in the fix.** Pass condition is a non-empty key
intersection, **not a 200**.

**Per-sport grading reality** — two measurements, different surfaces and times,
both reported rather than reconciled:

| sport | `[asserted]` lane, 07-19..08-08 | `[live]` this trace, 08-05/08-06 | attribution |
|---|---|---|---|
| soccer | 385 rows | 0 | — |
| mlb | 53 rows | 1 | — |
| **wnba** | **0 — DEFECT** | 0 | `processed_root()` read the wrong root. `17d4f203` was **deployed and inert**; really fixed by `d31091f7` (`#309`), pending deploy — see correction below |
| **nfl** | **0 — DEFECT** | 0 | grader read a directory nothing writes; fixed (`b2d7e36f`), **still correctly 0** — no NFL games played |
| nba / nhl / ncaab / ncaaf | 0 | 0 | **MEANINGLESS** — out of season |

**Four zeros, four causes, all rendering identically**: a deployed fix, an
inert fix, a fix that correctly still reads zero, and four legitimate
out-of-season absences.

**Correction, 2026-08-09 (`#309`/`#310`).** The WNBA row above was wrong in both
halves and is kept rather than deleted, because the way it was wrong is the
point.

- **"Not deployed" was false.** `17d4f203` is an ancestor of the live
  `27a7e9df` on web and refresh-worker (16:41Z).
- **"Fixed" was false.** The fix guards with `any(candidate.iterdir())` — "does
  this directory contain anything", not "does it contain the file you asked
  for". Root1 holds **427 files** on production, so it short-circuits True on
  the first candidate and returns `candidates[0]`: byte-identical to the
  pre-fix behaviour. Root1 is non-empty but *stale* — 43 `game_cards`, none for
  the requested date.
- **"0 of 6 artifact families" did not measure the grader's inputs.**
  `/api/ops/wnba/artifact-counts`, the endpoint built to diagnose this,
  checked six files of which **one** is a grader input, and omitted both
  `recon_*` files entirely. The measurement this row rested on was of a
  neighbouring population.

The real cause is that producer and consumer resolve **different roots from the
same env, by design**: the producer writes `<root>/data/processed`, while
`preferred_artifact_roots` unconditionally prepends a `<root>/source_artifacts`
variant for WNBA. NBA and NHL route through `preferred_source_roots`, which
injects no such variant — they are correct **by construction, not by luck**.
NCAAB is not covered by that statement.

A second, independent blocker survives the root fix: the grader needs four
files in two gated pairs, and both `recon_*` builders require
`boxscores_{date}.csv`. So a correct root can still settle zero.

### `#295` — closing price is a polling-boundary value. The deflated version.

`[asserted]`, **written, pending push**. Carried in its corrected form because the
dramatic version is wrong:

- **Three `*_pregame.json` exist in all of production**, MLB-only, 08-08-only —
  **the freeze was dead code until yesterday.**
- `evaluation_settlement.py` takes the **tracking stamp as primary**, with the
  seal only as fallback.
- ***"Every CLV number ever produced is wrong" is EXPLICITLY FALSE.***

**What survives:** the platform's closing price is the last pregame value
observed at a polling boundary, and the two mechanisms differ only in how coarse
that boundary is — the seal at freeze-cycle granularity (measured case: a price
4.5 hours stale against a true close), the tracking stamp at tick granularity.

Confirmed in code `[code]`, `odds_refresh_tracking.py:1591-1603` — the stamp
fires once, on the transition into live, recording `previous_line`/`previous_odds`
(the tick *before*), and correctly refuses to backfill when `previous_line is
None`. The code is honest about its limits. **The field name is what is
misleading**, and the width of the boundary is the capture cadence — ~26 min for
MLB game lines, up to 14.95 h measured on MLB props (§1).

### 8. Evaluation

`[live]` `[web]` 03:54:11Z: `settled_count` **0**, `roi` **null**, `avg_clv`
**null**, `win_rate` **null**, `publish_count` **0** (web reads 0 of 30 ledger
dates, `#287`), `total_pnl` 0.

**The feedback loop is open at three joints**: no graded rows to settle against,
no established cross-disk path from a logged bet to the settler, and a closing
price bounded by the poll interval.

- **`blended_score`'s `_SCORE_SIM_WEIGHT = 0.5` is a stated prior nobody has
  measured**; S6's exit condition is *"no measurement, no weight."* With
  `rows_with_model_edge` at 0 on three of four active sports, the sim term is
  inert — the weight is multiplying null.
- **`#292` is not answerable from any surface reachable here.** Does settlement
  grade against best price or the arbitrary retained book? It requires reading
  what `odds_refresh_tracking` stamped, on refresh-worker's disk. Stake per
  `#275`: single-book capture was platform-wide in three classes and best-price
  re-grading measured **+2.79 ROI points**, so if the stamp is the retained book,
  every cross-sport ROI number compares unlike with unlike. **Start at the
  writer, not at settlement.**

---

## 9. The whole contract, one table — with what each stage does with ABSENCE

The last column is the question that would have caught all three instances of
tonight's recurring defect: **not "does the field exist" but "when it doesn't,
what value is substituted, and is that the permissive or the restrictive one."**

| stage | mlb | wnba | soccer | nfl | nba/nhl/ncaaf/ncaab | **absence →** |
|---|---|---|---|---|---|---|
| 1 CAPTURE | PASS 44 books | PASS 18 | PASS 11 | PASS 11 | — `[HOUR]` | no shard vs no slate: **`#296` `sweep_state` now distinguishes** ✔ |
| 2 ROW BUILD | PASS | PASS | grid PASS / **source FAIL** (`#305`) | PASS | — | absent field left absent ✔ |
| 3 ENRICH · projection | PARTIAL, **0 edge** | **MEANINGLESS, silent** ✘ | PARTIAL, reasons stated ✔ | NO PRODUCER, labelled ✔ | NO PRODUCER, labelled ✔ | reason on the row for soccer/mlb-final; **none for wnba** ✘ |
| 3 ENRICH · game state | **FAIL** 5/15 | PARTIAL 278/715 | PASS 720/720 | **FAIL** 0 chips | — | **absent → `pregame`, the PERMISSIVE branch** ✘✘ (`#300`) |
| 3 ENRICH · margin | PASS | PASS | PASS | n/a | — | absent → labelled `book_margin_model` ✔ |
| 4 SELECTION | **FAIL** `#300` | 100% `stale_kickoff` `[HOUR]` ✔ | 100% `stale_kickoff` `[HOUR]` ✔ | **FAIL** 100% `beyond_horizon` | **absent, not zero** ✘ | reasons emitted for every drop ✔ — except the one that never fires |
| 5 PRESENTATION | L1-A PASS / **`#302` no cap** | L1-A PASS | L1-A PASS | L1-A PASS | — | `gaps` sentence per thin row ✔ |
| 6 BET LOGGING | **`#304`** two ledgers, web disk ≠ worker disk | same | same | same | same | silent — same path, different disk ✘✘ |
| 7 SETTLEMENT | **FAIL** 1 graded row | **FAIL**, fix undeployed | **FAIL** 0 | correctly 0 ✔ | — | **`no_graded_rows` vs `no_key_match` — the one place this is done right** ✔✔ |
| 8 EVALUATION | FAIL 0 settled | FAIL | FAIL | FAIL | — | null, undifferentiated ✘ |

---

## 10. Findings, with allocated IDs

Allocated by the coordinating session.

> **These six IDs are claimed HERE, in this table, in the commit that writes it —
> not in `todo.md`.** At the time of writing, `todo.md` carried **163 uncommitted
> lines from another lane**, and staging that file would have swept their work
> into my commit. Not staging another lane's changes is the stronger rule, so
> this document is the claiming record and it is pushed. Stubs follow into
> `todo.md` once that lane commits.
>
> **And `#306` — which I was told was next free — was already taken** by that
> same uncommitted lane while this section was being written. That is the tenth
> collision, by the mechanism this document's own citation-state note names: an
> ID in an unpushed tree is remembered, not allocated. **Ask before taking
> `#306`.**

| ID | finding | strength |
|---|---|---|
| **`#300`** | L2-A: absent game-state chip → `pregame` → 24 h ceiling → 100/100 rows, one in-progress game, 21 h prices. **Blocks the board swap.** | `[live]` |
| **`#301`** | `/api/board/game-chips` ignores `sport` — identical 65-chip list for all eight | `[live]` |
| **`#302`** | Web OOM; `book-grid?limit=2000` 502s reproducibly; L1-A pivot has no payload ceiling | `[live]` |
| **`#303`** | OddsAPI: a 155%-of-cap reading over a **contaminated** window. Standing rate is **45% of cap** and falling. **The 19.4-day exhaustion figure is withdrawn.** §4d's `us2` pricing rests on a **stale region→book map** — 7 of its 8 books already arrive free on `us` | `[live]`; the structural inference is refuted, the peak-hour test remains open |
| **`#304`** | Two ledgers on two disks; bets log on web, settle on refresh-worker | `[structural]` |
| **`#305`** | soccer `prop_source_in` 162/162 missing `market_key` | `[live]` |

**Riders, not entries:** NCAAF's grader reading a CFBD id it cannot emit; NCAAB
emitting no `odds` at all; the opportunity-contract metrics store keyed on
display labels; WNBA's correct blank being indistinguishable from a defect.

## 11. What was NOT measured, and why

So absence here is never read as evidence.

- **Per-sport graded row counts over 07-19..08-08** — the grader runs only inside
  refresh-worker's process; local returns 0 for all eight sports.
- **The peak-hour burn comparison** (§1) — the decisive test for whether 155% is
  structural or incident-inflated. The quota endpoint has no per-day breakdown.
- **A fresh region→book query.** §1 shows §4d's map is stale from the *data*
  side; confirming it costs 1 credit per region against `/v4/sports/.../odds`.
- **Whether the sharp-anchor asymmetry (§1) is deliberate.** Established that
  only MLB's fetcher reads the game-line extras; **not** established whether
  that was a choice or an unfinished rollout. That determines whether it is a
  scoping decision to record or eleven fetchers to change.
- **`#292`** — best-price vs retained book. Requires refresh-worker's disk.
- **L2-B and L2-C row counts.** The endpoints exist and share the row.
- **Whether a web-logged bet reaches refresh-worker's ledger** — needs a
  production write; §6 names the experiment.
- **Soccer's grader field emissions** — the settlement lane owns that path.
- **Anything at a pregame hour.** Every figure is 03:37–04:06Z. Figures marked
  `[HOUR]` would read differently at 18:00Z, and **`#300` should be re-measured
  mid-slate, where it may be worse** — more games simultaneously live and
  unchipped.

## 12. Files read

`plan_layer2_north_star.md` · `CLAUDE.md` · `docs/ai_context/todo.md`
(`#263 #268 #270 #275 #278 #279 #286 #287 #288 #289 #292 #293`) ·
`opportunity_gate.py` · `layer2_board.py` · `pipeline/layer2_shortlist.py` ·
`graded_outcomes.py` · `evaluation_settlement.py` · `intelligence_evaluation.py` ·
`prediction_ledger.py` · `ledger_bridge.py` · `odds_refresh_tracking.py` ·
`blueprints/intelligence.py` · `blueprints/ops.py` · `static/shared/bet_slip.js` ·
`render.yaml`.

`#296` and `#297` are visible as uncommitted working-tree changes in
`pipeline/layer2_shortlist.py`, `blueprints/intelligence.py` and
`evaluation_settlement.py` at `a000e2e4`.
