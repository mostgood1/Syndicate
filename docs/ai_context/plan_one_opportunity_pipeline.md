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

## 8. What I would check before writing any of it

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

## 9. The honest counter-argument

Per-sport freedom is cheap and shared contracts are expensive — this repo's own
board-contract convergence has been a multi-phase migration. That trade was
defensible while the cost was invisible. It is now visible: wrong player names on
cards, truncated lines, a regex scraper publishing narrative text as picks, and a
measured 2.79 ROI points of price improvement that cannot reach most of the
board. The trade has stopped paying.
