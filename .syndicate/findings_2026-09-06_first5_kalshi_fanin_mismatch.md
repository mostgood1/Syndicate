# The first5 rows priced at Kalshi 0.870 took a FULL-GAME contract. DEFECT, not a thin market. `[lane mlb-first5-kalshi-fanin-mismatch, 2026-09-06]`

**VERDICT: the suspected segment-to-full-game mismatch is REAL, it is on a
SECOND join that `_segments_agree` has never covered, and the competing "thin
first5 quote" explanation is not merely unlikely — it is structurally
impossible on that path.** A first5 board row cannot receive a `KXMLBF5TOTAL`
price at all; the two sides key on different market spellings and never meet.

Substrate: `render` for every production number (Render logs API + the user's
own reading of the served payload). Code checked **by CONTENT** against the SHA
each service was running. The replay is evidence about the CODE, and it is
labelled as such — `state.md`'s substrate rule.

---

## 0. The four questions, answered

| # | question | answer |
|---|---|---|
| 1 | which Kalshi ticker priced those rows? | a **`KXMLBTOTAL`** (full-game) contract at strike 4.5. Determined by construction, not read off a record — no match record existed. One is added in this change. |
| 2 | does `_segments_agree` run on this path? | **No.** It guards the ORDER path (`portfolio_commit` → `kalshi_ticker_resolver`). The board's PRICE comes from `venue_quote_fanin`, a different module with no segment check anywhere in it. |
| 3 | is there a full-game `KXMLBTOTAL` for MIL@CIN at 4.5? | **Necessarily yes** — entailed by the observation. Not independently confirmed: this session has no egress to Kalshi or to `syndicate-an21.onrender.com` (org policy blocks both). |
| 4 | the rate | **numerator 0, by construction**: of segment board rows carrying `price_source=kalshi`, the number whose matched series can be a SEGMENT series is exactly zero — no board row asks for the key a segment contract publishes under. **Denominator unmeasured from here** — see §6. |

---

## 1. There are TWO joins over the same Kalshi book, and only one is guarded

    ORDER PATH  (guarded)
      pipeline/portfolio_commit.py:673  -> kalshi_board_join.join_kalshi_to_board
      pipeline/kalshi_odds_refresh.py:1455       "
        -> both `matches.append` sites preceded by `_segments_agree`
        -> kalshi_ticker_resolver reads nothing but `matches`

    BOARD PRICE PATH  (unguarded)
      pipeline/layer2_shortlist.py:622  -> venue_quote_fanin.apply_venue_quotes_to_grid
        -> quote_key(sport, row["market"], side, line)
        -> side_best["price"] / ["bookmaker"] / ["price_source"] / ["venue_ref"]
        -> _reprice_live_benchmark writes cells[book][side] -> quote.book_prices
        -> venue_basis_edge(...) -> quote.venue_basis

`grep -c segment syndicate/features/shared/venue_quote_fanin.py` on the
deployed SHA: **0**. The word does not occur in the module.

The 2026-09-05 audit's choke-point claim ("`kalshi_ticker_resolver` reads
nothing but `matches`, and both `matches.append` sites are guarded") is
**correct and remains correct**. It is a claim about ticker resolution for
ORDERS. It was read as a claim about Kalshi reaching the board, and it is not
one.

**`segment_has_no_matching_series` reading 0 did not discriminate for exactly
this reason** — it is the other join's counter. On 2026-09-06 it was not even 0:
`[kalshi_odds] BOARD_JOIN` reported **160** at 17:05:41Z and **191** at
17:26:14Z. The guard was firing all day, on the path that was never the one
producing these rows.

## 2. The key algebra — measured by running the deployed code

`classify_market` (deployed SHA), on Kalshi's own titles taken verbatim from
`[kalshi_odds] TITLE` lines:

| series | title | `market` | quote key |
|---|---|---|---|
| `KXMLBF5TOTAL` | `First 5 innings: Over 4.5 runs` | `totals_1st_5_innings` | `mlb\|totals_1st_5_innings\|over\|4.5` |
| `KXMLBTOTAL` | `Full Game: Over 4.5 runs` | `totals` | `mlb\|totals\|over\|4.5` |

The board stores the PAIR, not the fused spelling: `market='totals'` +
`segment='first5'` (the user's own production reading; `book_grid._INSTANCE_FIELDS`
carries `segment` and `market` as separate fields). `_candidate_keys` and the
grid loop build the key from `market` alone.

So a **first5** board row and a **full-game** board row ask the identical
question — and only the full-game contract can answer it.

## 3. The reproduction — all four production numbers, exactly

Replayed through `apply_venue_quotes_to_grid` on the byte-identical deployed
code, with BOTH contracts in a real-shaped `kalshi_markets.json`, seven books,
one live first5 grid row for MIL@CIN:

| field | production 16:20Z | replay |
|---|---|---|
| `price_source` | `kalshi` | `kalshi` |
| `book_prices['kalshi']` | `-669` | `-669` |
| `consensus_probability` | `0.492611` | `0.492611` |
| `edge_pct` | `-38.535` | `-38.535` |
| `venue_basis.reason` | *"kalshi at 0.870 plus 0.0080 commission against a 7-book consensus"* | identical string |
| `venue_ref` | **not served** | **`KXMLBTOTAL-26SEP061340MILCIN-4`** |

`venue_ref` is the answer to question 1, and the reason it could not be read:
`venue_quote_fanin` stamps it on `best[side]`, and `layer2_board`'s quote
projection copies a **FIXED field list** that does not include it. No board row
has ever carried the contract that priced it.

## 4. The counterfactual kills the "thin first5 market" explanation

Same code, same row, three artifacts:

| artifact contains | first5 row's price | bound to |
|---|---|---|
| both contracts | `-669` | `KXMLBTOTAL-...MILCIN-4` |
| **only `KXMLBF5TOTAL`** | **none — `price_source=None`, `repriced=0`** | — |
| only `KXMLBTOTAL` | `-669` | `KXMLBTOTAL-...MILCIN-4` |

A first5 board row is **incapable** of receiving a first5 Kalshi price on this
path. 0.870 therefore cannot be a wide or stale F5 ask. There is no exoneration
to record.

## 5. The side that showed was the harmless one

Same replay, the other leg of the same contract:

    over    -669   venue_prob 0.869961   consensus 0.492611   edge_pct -38.535
    under   +590   venue_prob 0.144928   consensus 0.492611   edge_pct +33.899

The board showed the over, which ranks nowhere. The under is a fabricated
+33.9-point edge that would rank first — `state_kalshi.md`'s own sentence about
2026-08-28: *"a mis-keyed join presents as the best line on the board, so
edge-ranking selects for it."* "EV happened to be negative" is a property of
the leg that was looked at, not of the defect.

**Execution is still guarded.** `_segments_agree` and `bet_status.segment_refusal`
sit between a ranked segment row and a filled order, so this corrupts the BOARD,
the EV, the shortlist and anything grading against the board price — not, on
current evidence, a fill.

## 6. The rate, with what is and is not measurable from here

**Numerator — certain, and it is zero.** Of segment board rows carrying
`price_source=kalshi`, the number for which the matched series can be identified
as a SEGMENT series is **0/N**, necessarily: the adapter publishes every Kalshi
segment contract under a key (`<market>_<suffix>`) that no board row ever asks
for. Every such row is matched to a full-game series.

**Denominator — NOT measured, and the reason is an environment limit, not a
judgement.** This session's egress proxy denies `syndicate-an21.onrender.com`
(`connect_rejected`, organization policy) for both `curl` and `WebFetch`, so the
served payload is unreadable here. What production logs do give:

- `[layer2_shortlist] GRID_REPRICE sport=mlb` at **16:15:09Z** — the board build
  behind the 16:20Z reading — `sides_seen=4830 repriced=44 by_source={'kalshi': 44}`.
  Later: 17:03Z `70`, 17:24Z `88`, 17:53Z `83`, 17:59Z `125` of `sides_seen=6098`.
  At 16:40Z the split was `{'polymarket_us': 38, 'kalshi': 24}`.
- MLB's board is overwhelmingly segment rows:
  `[layer2_shortlist] LIVE_GAMELINE_JOIN sport=mlb` withheld
  `segment_is_not_full_game` **105 of 122** considered at 17:03Z and **469 of
  549** at 17:59Z. (A different denominator — live-gameline candidates — so it
  bounds nothing exactly; it says the population is not marginal.)
- Both series were captured all day: `[kalshi_odds] BY_GAME_DATE` for
  `2026-09-06` carries `KXMLBF5TOTAL: 105` and `KXMLBTOTAL: 167`.

**The exact split is now an instrument, not an inference.** The change adds
`[venue_quote_fanin] SEGMENT_MISMATCH_GRID sport=… count=… sides_seen=…
repriced=… matched={…} sample=[…] refusing=…`, printed unconditionally
including the zero. `count` is the defect's size (the counter is named
`segment_mismatch_detected`, not `_rejected`, because in the measuring stage
these pairings are counted and STILL USED); `matched` is
`<row segment>|<venue>|<series>` for every reprice that landed, so a
`first5|kalshi|KXMLBTOTAL` entry there IS the mis-binding, named. That is the
match record that did not exist.

Anyone with egress can have the denominator now, without a deploy:

    curl -s '<base>/api/board/layer2-shortlist?limit=2000' | python3 -c "
    import json,sys,collections
    rows=json.load(sys.stdin).get('rows') or []
    seg=[r for r in rows if str(r.get('segment') or 'full') not in ('full','full_game','game')]
    c=collections.Counter((r.get('sport'), r.get('segment'), (r.get('quote') or {}).get('bookmaker')) for r in seg)
    print('segment rows:', len(seg), 'of', len(rows))
    print('venue-priced:', sum(n for k,n in c.items() if k[2] in ('kalshi','polymarket')))
    for k,n in c.most_common(30): print(' ', k, n)"

## 7. The defect spans BOTH venues, exactly as 2026-08-28 did

`polymarket_us_outcome` refuses a segment CONTRACT outright — *"A FIRST-QUARTER
TOTAL IS NOT A GAME TOTAL"* — and `kalshi_outcome` publishes segment contracts
under the fused spelling. Both protect a **full-game row from a segment price**.
**Neither protects a segment row from a full-game price**, so a first5 row takes
Polymarket's whole-game total the same way. `GRID_REPRICE` at 16:40:22Z shows
`polymarket_us: 38` repriced sides on mlb. One guard covers both; a test pins it.

## 8. TWO SIDE FINDINGS, neither of them mine to fix

**(a) The whole-game token has two spellings and the ORDER path's comparator
does not fold them.** `segment_for_board_row` returns `full_game` verbatim, and
`segment_for_series('KXMLBTOTAL')` is `full` — so a board row spelled
`full_game` would be refused a ticker by `_segments_agree`. It is not biting
today: `BOARD_JOIN` matched 545-845 rows per join, which rows spelled
`full_game` could not have done, so production writes `full`. But the synonym is
alive in FIXTURES — `test_venue_basis_wiring.py:37`,
`test_venue_unnamed_quote_ambiguity.py:43`,
`scripts/portfolio_commit_input_checklist.py:53` — and
`layer2_board._segment_label` accepts all three. `kalshi_catalogue.py` is held
by lane `ncaaf-h1-kalshi-series`; not touched.

**(b) This nearly shipped as an outage and the tests caught it.** The first
version of the guard compared `normalize_segment(...)` to `full`, which folds
only the empty string. It failed **10 tests across two suites** whose grid rows
say `full_game` — i.e. it would have stripped the venue price off every
whole-game row spelled that way. The fold is now explicit, pinned by a
parametrised test over all four spellings, and the reasoning is in the code.

## 9. What this change is, and what it deliberately is not

**IS:** a refusal plus an instrument. It can only remove a pairing.
`_segment_disagrees` reuses `segment_for_board_row` (the ORDER path's own
resolver) for the row and `split_segment_market_key` for the quote — one
resolver per side, not a third vocabulary.

**IS NOT:** a widening. Binding a first5 row to a real `KXMLBF5TOTAL` contract
needs the two sides to agree on a key. That is a separate change that stakes
money and owes its own measurement — `state_kalshi.md` records why the honest
route there is a board row at the venue's strikes, never a looser join.

**STAGED, BY USER DECISION 2026-09-06: "instrument first, fix second".**
`_SEGMENT_REFUSAL_ENABLED` ships **False**. The first deploy COUNTS the
mis-bindings and changes no price -- `SEGMENT_MISMATCH_GRID` then carries
`refusing=False`, `count=<the defect's size>`, `sides_seen=<denominator>` and a
`matched` map in which a `first5|kalshi|KXMLBTOTAL` entry IS the mis-binding,
named. The second deploy flips the constant.

A CONSTANT, NOT AN ENV KEY, and the reason is repo-specific: an env key means
either a `render.yaml` push -- which fires `blueprint_sync` and rewrites the
whole env block on live services -- or a live-API edit that leaves the blueprint
drifted. A one-line constant costs the second deploy that was asked for and
leaves nothing behind.

**THE FAILURE MODE OF STAGING, PINNED:** shipping the flag off *and* the
measurement off returns a zero that reads exactly like a healthy board.
`test_the_shipped_default_counts_without_refusing` asserts both halves on one
call -- the price is still `-669` and the count is still `2`.

**NOT DEPLOYED.** 18 tests in `tests/test_venue_quote_segment_join.py`, the
first two of which are reachability (`off != on`) rather than correctness;
3,078 green across the venue/kalshi/segment/book_grid/shortlist/layer2/
polymarket/portfolio/execution/settlement surface.
