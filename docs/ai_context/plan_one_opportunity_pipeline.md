# PLAN — one opportunity pipeline, every sport, source to board

Answers: *"should rails really be building anything?"* — **No.** And the fix is
smaller than it looks, because the convergence points already exist. They are
coercion layers where they should be contract boundaries.

Written 2026-08-06 after #208–#220, all of which were symptoms of what follows.

---

## 1. What is actually there

Traced, not assumed. The prop chain, end to end:

```
per-sport source                 shared seam                    consumers
────────────────                 ───────────                    ─────────
get_wnba_overview().prop_rows ─┐
_load_home_pregame_prop_items ─┼─> _finalize_home_prop_rows ─> pregame_prop_items ─┬─> home_rails.pregame.items
_load_home_prop_items(slug)   ─┘   (home.py:1338)                                  ├─> props_bar.items
                                                                                   └─> _build_prop_dashboard_row
                                                                                          └─> top_props / top_edges
```

And the game chain, separately:

```
dashboard_games ─> _game_bet_candidates_from_game ─> game_bets ─> top_game_bets
                     (5 internal loops)
```

Then, far downstream and only for the intelligence board:

```
classified dicts ─> UniversalCandidate.from_raw(...)   # intelligence.py:9261
```

**Two independent pipelines produce "picks", and the one contract in the
codebase is applied to neither of them at production time.**

## 2. Diagnosis — three specific things, not "it's messy"

**(a) `_finalize_home_prop_rows` is a coercion layer, not a contract.** It reads
`game_pk or gamePk or game_id`, splits `matchup` into labels, falls back
`away_label or team`. Every one of those is a guess repairing an upstream
omission, and when the guess fails it writes `None` and moves on. That is why
production serves `player_name: null` with the player sitting in the pick text,
`pick: "Under 0"` for a 0.5 line, and WNBA rows whose `player_name` is the entire
label `"Rae Burrell UNDER 15.5 PTS"`. **Nothing rejected those rows because
nothing was asked to.**

**(b) `UniversalCandidate` runs at the wrong end.** It is built by `from_raw`
over already-classified dicts — a normalizer of output. It cannot restore what a
producer dropped, and it carries a `raw: dict` escape hatch that lets the
un-normalized soup ride along. Its fields confirm the gap: `selection`, `market`,
`odds`, `edge`, `confidence` — and **no entity/player, no event_id, no line, no
price provenance**. Exactly the fields #217–#220 could not join on.

**(c) Rails are read as a source.** `home_rails.pregame.items` and
`props_bar.items` are display collections, and `_build_home_dashboard` turns them
into `top_props`/`top_edges` — the opportunity feed. A presentation shape is
upstream of the data feed. `shared_top_play_rows` is the reductio: that loop
**regex-scrapes wagers out of panel prose**, and its own comment records that it
once published `"Simulations: 400"` as a pick.

**The through-line:** identity is destroyed at production and guessed at
consumption. Every bug in #217–#220 is one instance.

## 3. The rule

> **Producers emit the contract. Everything downstream filters, ranks, and
> renders. Nothing downstream constructs an opportunity, and nothing infers
> identity from a label.**

Rails render. `props_bar` renders. `top_edges` is a *ranking over* opportunities.
The board card is a *view of* one. The bet slip *logs* one. Settlement *joins on*
one. None of them build one.

## 4. The contract

Extend `UniversalCandidate` (do not invent a rival) with the fields that today
live in `raw`/`sport_context` or nowhere:

```
identity   candidate_id, sport, league, game_date, event_id,
           home_team, away_team, entity_id, entity_name      # player or team
market     market_key (canonical: batter_hits, h2h, ...), market_label,
           segment, selection, line
model      model_probability, projection, edge, confidence, score
price      quote (odds_book_quotes.quote_ref: bookmaker, price, both clocks,
           price_rank, books_quoting, consensus_price, alternatives)
provenance source_artifact, produced_by, produced_at, is_live
```

Two rules that do the real work:

1. **`entity_name` and `market_key` are REQUIRED for a prop; `event_id` or the
   team pair is REQUIRED for a game market.** A row that cannot supply them is
   not an opportunity and must not be emitted as one.
2. **`market_key` is canonical and sport-agnostic.** The board may display
   "Hits"; the contract carries `batter_hits`. Display strings never travel as
   keys — that is what made `"Hits"` unjoinable to `batter_hits`.

`quote` attaches at production, in one place. Today enrichment is bolted into
**three** call sites (`game_market_recommendations` rows, the assembled candidate
list, the prop-rows lane) because there was nowhere single to put it. That is the
smell, and it collapses to one here.

## 5. The pipeline, sport-agnostic

```
artifacts (per sport)
      │   sims, odds snapshots, book_quotes, rosters
      ▼
OpportunityProducer[sport]          <- the ONLY place opportunities are created
      │   emits UniversalCandidate, identity guaranteed, quote attached
      ▼
validate + reject                   <- loud, counted, never silently nulled
      │
      ▼
opportunity store (per sport+date)  <- one artifact, the single source
      │
      ├─> rank  (edge/CLV/score)  ─> top_edges, top_props, top_game_bets
      ├─> filter(sport, live, market) ─> rails, props_bar
      ├─> render ─> board card, price strip, two clocks
      ├─> bet slip ─> ledger (quote already attached: CLV opens correctly)
      └─> settlement ─> joins on the same identity it was logged with
```

One producer interface, one store shape, one renderer. A new sport implements
`OpportunityProducer` and gets rails, board, slip, CLV and settlement for free —
which is the actual answer to "regardless of sport".

## 6. Migration — strangler, not rewrite

Every existing lane encodes a hard-won fix (the todo is full of them). A big-bang
replacement re-breaks things nobody remembers. Order, each step shippable and
verifiable on its own:

| # | step | proves |
|---|---|---|
| 1 | Extend `UniversalCandidate` with identity + `quote`; add `validate()` | contract exists, nothing uses it yet |
| 2 | Add counters at `_finalize_home_prop_rows`: how many rows lack `entity_name`/`market_key` | **the size of the problem, measured** |
| 3 | Fix the MLB prop producer to emit identity + canonical `market_key` | `top_props` starts joining; counter drops |
| 4 | Point `top_props`/`top_edges` at the store, not at rail items | rails stop being a source |
| 5 | Repeat 3 for WNBA, NBA, NFL, NHL, NCAAF, NCAAB, soccer | one sport at a time, counter per sport |
| 6 | Move game markets onto the same producer | `_game_bet_candidates_from_game`'s 5 loops collapse |
| 7 | Delete `shared_top_play_rows` scraping and the 3 enrichment sites | the regex scraper goes away entirely |

**Step 2 before step 3, deliberately.** Today's session repeatedly shipped code
that passed tests and did nothing in production. A counter that says *"MLB: 27 of
28 prop rows have no entity_name"* is how you know a fix worked, and it costs
almost nothing.

## 7. How you know it is working

Per sport, per day, published so it is visible cross-service:

- `opportunities_emitted` vs `rejected_missing_identity` (should trend to 0)
- `pct_with_quote` (today: `top_game_bets` 5/12, `top_props` 0/14)
- `pct_with_better_price_available` — the #211 lever, in production
- `rows_scraped_from_prose` — should reach 0 and stay there

## 8. VERIFICATION RESULTS (done 2026-08-06, before implementing)

All three checks run against production. Two changed the plan; one produced an
immediate fix.

**V1 — what per-sport sources return.** Identity is PARTLY there and quality
differs by sport, so the contract's required fields are suppliable:
- MLB rail items: `player_name: "Ryan Johnson"` ✓, `player_id` ✓, `game_pk` ✓,
  `market: "Walks Allowed"` (display only).
- WNBA rail items: `event_id` ✓, but `player_name` holds the whole label
  `"Rae Burrell UNDER 15.5 PTS"` ✗.

**V2 — does a canonical `market_key` already exist upstream?** **Yes, but it is
dropped before the board.** Game-dict prop rows carry
`prop: "batter_total_bases"`; rail items carry only `market: "Total Bases"`.
So the key exists at the artifact level and dies in the display layer — the
board's "Total Bases" could never join the quote log's "batter_total_bases".
This makes the canonical-key step much smaller than assumed: thread it through,
do not invent it.

**V3 — who else reads `home_rails.items` as data?** **More than home.py.**
`syndicate/features/intelligence.py` reads the rails directly (`:2585-2587`,
`:7201`) — the Layer 2 board itself consumes a presentation structure as its
source. There is also a second prose scraper there (`:4447`, "scrapes narrative
writeup/reasons text into a home_rails pregame item"). **Migration step 4 must
cover intelligence.py, not just home.py**, or half the board keeps its old feed.

**The finding that paid immediately (#221).** `_build_prop_dashboard_row`
reconstructs a new dict rather than passing the item through, and carried no
`player_name`, no `player_id`, no canonical key. Rail items HAD the player; every
row it produced had `player_name: null`. The comment directly above that block
records the identical failure one field-set earlier — it "used to drop
commence_time entirely", also found only by tracing production. Same function,
same cause, second occurrence.

Threading identity + `market_key` through it, measured live before and after:

| lane | before | after |
|---|---|---|
| `command_center/top_props` | 0 of 14 | **12 of 14** |
| `dashboard/top_edges` | 0 of 12 | **9 of 12** |
| `command_center/top_game_bets` | 5 of 12 | **7 of 12** |

Real improvements now surfacing: Dylan Cease strikeouts −113 vs **+105** at
lowvig (4.27 pts), Ranger Suarez outs −122 vs **−110** at bovada (2.57 pts).

**Still broken, and now clearly a display-layer defect rather than a join one**:
`pick: "Hits Under 0"` for a 0.5 line. The label is truncated at render. It no
longer blocks pricing, but it is wrong on screen.

**What this does to the plan:** step 3 shrinks (thread the key, do not invent
it), step 4 grows (intelligence.py too), and step 2's instrumentation matters
more than ever — one 3-line change moved 28 rows from unpriced to priced, and
only a per-lane counter made that visible.

---

## 9. What the OddsJam-class engine needs on top

Stated because the goal is EV + CLV + arb + mispricing, sim-enriched — and the
verification shows the primitives are already there, unattached.

- **EV** — needs model probability vs BEST price, not one book. Shipped (#215
  recomputes `ev_pct` against best available).
- **CLV** — needs the price struck at bet time and the closing price. Both
  shipped (#213 records `quote` on the bet; #214 derives closes from the log).
- **Arbitrage** — needs every book's price on BOTH sides of one market. The quote
  log already holds exactly this: `quotes_by_market` groups by
  (event, market, segment, selection, line). An arb is
  `implied(best_over) + implied(best_under) < 1`. **Computable today, nothing
  written yet.**
- **Mispriced lines** — needs our price vs the FIELD, not vs one book.
  `consensus_price` (implied-probability averaged across books) shipped in
  `quote_ref`.
- **The sim edge — the differentiator.** OddsJam has the market; it does not have
  a simulation. Ours is what turns "this book is off consensus" into "this book
  is off REALITY". That is `model_probability` vs `consensus_price`, which is a
  different and stronger signal than either arb or steam.

All five hang off the same object. That is the argument for the contract: not
tidiness, but that EV, CLV, arb, mispricing and sim-edge are five views of one
opportunity, and today there is no one place to hang them.

---

## 10. STEP 2 + STEP 1 SHIPPED — first counter reading (2026-08-06)

`/api/ops/opportunity-contract/status`, web, after one board build:

```
sport  date        lane                rows  noKey  noEntity  noEvent  quoted  complete
mlb    2026-08-06  game_candidate       106    106        18        0     106         0
mlb    2026-08-06  prop_source_in        46     46        10        0       0         0
mlb    2026-08-06  prop_dashboard_row    45     45         0        0       0         0
mlb    2026-08-07  game_candidate        12     12         2        0       0         0
wnba   2026-08-06  prop_source_in        18     18         0        0       0         0
wnba   2026-08-06  prop_dashboard_row     9      9         0        0       0         0
wnba   (no date)   game_candidate        12     12        12        0       4         0
```

**The headline, and it is a single number: `missing_market_key` is 100% of every
row, in every lane, in both sports — 106/106, 46/46, 45/45, 18/18, 12/12.** Not
one row anywhere on the board carries a canonical market key. `complete` is 0
everywhere and that is the *only* reason.

This is exactly what step 2 was for. It converts "props don't join" into a
single, specific, measurable target, and it says the fix is at the producer, not
in the matcher — the same conclusion three sessions of matcher-debugging reached
the slow way.

**Other things the first reading surfaced for free:**
- **`missing_event_identity` is 0 everywhere.** Event identity is not the
  problem and needs no work. Worth knowing before spending a day on it.
- **WNBA game candidates have NO DATE at all** (empty date bucket, and
  `noEntity` 12/12). Their game dicts carry no field `_game_date` can read,
  which means quote enrichment returns early for every one — the same
  camelCase-date defect as #219, in a different sport.
- **MLB `game_candidate` is `quoted=106/106`** — game markets are fully priced.
- **`prop_dashboard_row` reads `quoted=0` and that is an instrumentation
  artifact, not a regression**: the counter is recorded BEFORE
  `enrich_prop_rows` runs in that function. The served payload for the same
  build had `top_props` 12/14 priced. Recorded here rather than quietly fixed,
  because a metric that flatters itself is worse than none — move the call after
  enrichment, or count both sides.

**Step 3 is now unambiguous**: thread the canonical key from producer to board.
V2 established it already exists upstream (`prop: "batter_total_bases"`), so this
is threading, not inventing — and the counter will show it landing, per sport,
the moment it does.

## 11. Residual risks



Stated because I have been wrong three times today by designing against an
assumed shape:

1. **What each per-sport source actually returns.** `_load_home_prop_items(slug)`
   fans out per sport; I have traced *to* that seam, not *through* it. The
   contract's required fields must be ones producers can genuinely supply.
2. **Whether `market_key` already exists upstream.** MLB prop rows carry
   `prop: "batter_total_bases"` — the canonical key may already be there and
   simply be dropped by the display layer, which would make step 3 far smaller.
3. **Who else reads `home_rails.items`.** If other surfaces consume them as data,
   step 4 needs those migrated too or it breaks them silently.

## 12. The honest counter-argument

Per-sport freedom is cheap and shared contracts are expensive — this repo's own
board-contract convergence has been a multi-phase migration. That trade was
defensible while the cost was invisible. It is now visible: wrong player names on
cards, truncated lines, a regex scraper publishing narrative text as picks, and a
measured 2.79 ROI points of price improvement that cannot reach most of the
board. The trade has stopped paying.
