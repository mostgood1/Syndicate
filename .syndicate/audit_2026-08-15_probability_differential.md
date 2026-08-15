# Probability substrate — differential test

**Program plan Tier 3a.** Lane `probability-differential-test`, 2026-08-15.
Harness: `scripts/probability_differential.py`. Test: `tests/test_probability_differential.py`.
Re-run with `python scripts/probability_differential.py` (I/O-free, no slate,
no deploy).

```
python scripts/probability_differential.py            # table + exit 1 on disagreement
python scripts/probability_differential.py --quiet    # disagreements only
python scripts/probability_differential.py --json     # machine-readable
```

---

## Headline

**The odds maths is not wrong anywhere. Every one of the 26
American→probability implementations agrees to ten decimal places on every
*valid* American price (±100, ±150, ±10000).** That result is worth stating
first, because "42 sites define a probability" reads like 42 chances to be
wrong and it is not.

**All the divergence is at the boundary** — `0`, `None`, `""`, a string price,
a float price — and that is where the live bugs are, because the boundary is
exactly what a missing or malformed quote looks like.

**One live pricing bug is confirmed in production, by direct join, today:**

| sport | market | side | `fair_probability` | published `fair_price` | correct |
|---|---|---|---|---|---|
| mlb | totals | under | 0.992056 | **−4900** | −12488 |
| mlb | totals | over | 0.007944 | **+4900** | +12488 |

Source: `/api/intelligence/query` on `syndicate-an21.onrender.com`, 1346
`fair_price` values served, **24 of them sitting exactly on ±4900 and not one
beyond it**, joined row-wise to the `fair_probability` that produced them. The
cause is a `max(0.02, min(0.98, p))` clamp copied into three places (and a
fourth inline). A clamp is not a guard: it converts an out-of-range input into
a confident wrong number instead of a refusal.

---

## What was run

| concept | impls | behaviour clusters | disagreeing grid points |
|---|---|---|---|
| `american_to_probability` | 26 | **10** | 8 of 14 |
| `american_to_decimal` | 6 | **5** | 8 of 14 |
| `probability_to_american` | 5 | **4** | 9 of 13 |

Grid: `0`, `+100`, `-100`, `+150`, `-150`, `+10000`, `-10000`, `None`, `""`,
`"+150"`, `"-150"`, decimal `2.5` and `1.5` arriving where American is
expected, and float `-110.5`. Inverse grid: `0.0`, `0.01`, `0.02`, `0.40`,
`0.50`, `0.5238`, `0.98`, `0.99`, `1.0`, `None`, `""`, `"0.5"`, and `50.0`
(percent arriving where a fraction is expected).

All 31 registered implementations import and run. Nothing was skipped.

---

## The disagreement table

### D1 — price `0` yields five different answers

| answer | count | who |
|---|---|---|
| `None` | 20 | the 15-member majority cluster, plus mlb.cards, hr_targets, fetch_mlb_oddsapi_local, market_lines, nhl adapters |
| **`0.0`** | 5 | `regrade_mlb_game_markets:_american_to_implied`, `bankroll_manager:_implied_probability_from_odds`, `intelligence:_american_implied_probability`, `intelligence:odds_to_implied_probability`, `odds_book_quotes:_implied_probability` |
| **`-0.0`** | 1 | `validate_soccer_vs_market:_american_to_prob` |

Every one of the six reaches `abs(0)/(abs(0)+100)` because `0 > 0` is false.
`0.0` is the **worst possible** substitution for a missing market probability:
`edge = model_prob - market_prob` becomes the entire model probability, so a
missing price manufactures the largest edge on the board rather than the
smallest.

- `bankroll_manager` is the one with a stake attached. Line 128 calls it on a
  raw `candidate["odds"]` with no upstream guard; `_odds_adjustment(0)` then
  returns `None` and falls back to `1.0`, so Kelly becomes
  `model_probability / 1.0` — a full-model-probability stake off one bad price.
- `odds_book_quotes` feeds `edge_vs_consensus_pct` (line 1177) **and**
  best-price selection (line 1081), where `_implied_probability(0) = 0.0` is the
  lowest possible value, so a zero price would win "best price" at every book
  comparison and be published as `best_price: 0`.
- `intelligence:odds_to_implied_probability` is **latent, not live**: both call
  sites (lines 1002, 8214) pre-guard with `_american_odds_value`, which returns
  `None` at 0. The function is unsafe; today nothing reaches it unsafely. Stated
  that way deliberately — it is a hazard, not a defect.

**No zero prices were found in production.** `quote.price` on 105 live
shortlist rows: 0 zeros, 0 floats, 0 strings. So D1 is a real defect with **no
demonstrated live trigger**; it is a landmine, not a fire.

### D2 — the ±4900 clamp, and it IS live

| impl | `0.0` | `1.0` | `50.0` | round-trip |
|---|---|---|---|---|
| `opportunity_signals:american_price` | `None` | `None` | `None` | **9/9** |
| `layer2_board:_american_from_probability` | +4900 | −4900 | −4900 | 7/9 |
| `wnba/cards:_american_from_prob` | +4900 | −4900 | −4900 | 7/9 |
| `pipeline/intelligence_state` (inline) | +4900 | −4900 | −4900 | 7/9 |
| `market_lines:_prob_to_american` | +999900 | −999900 | −999900 | 9/9 |

Round-trip = price the probability, read it back through the reference form.
The clamped three fail at `p=0.99`, recovering `0.98` — a full percentage point,
and the exact failure measured on the live board above.

`50.0` is the one that should worry us most. `confidence` is stored 0–100 and
probability 0–1 **in the same rows**. Three implementations turn that unit error
into `-4900`, which looks like a real price. One returns `None`.

### D3 — a fourth producer with no `def` to grep for

`pipeline/intelligence_state.py:1816` carries the clamped formula **inline**
inside `_backfill_layer2_board_columns`. No function-level audit counts it; the
board-engine audit's 42 did not. It was found by tracing the `fair_price` field
to its producers, not by searching for definitions. It is registered in the
harness through its real entry point.

So `fair_price` — one user-visible column — has **four** producers: one
unclamped and correct (`book_margin_model` → `american_price`), three clamped.

### D4 — string prices split the field

`"+150"` and `"-150"` are the wire format from JSON artifacts and CSV mirrors.

| answer | count |
|---|---|
| `0.4` / `0.6` | 22 |
| `RAISED TypeError` | 4 — `intelligence` ×2, `ncaab/mirror_export`, `odds_book_quotes` |

A raise here takes out the whole row, not the one cell.

### D5 — `""` splits it three ways

`None` ×20, `RAISED TypeError` ×4, `RAISED ValueError` ×2. Empty strings arrive
from CSV mirrors and from OddsAPI payloads with a null price.

### D6 — float prices: one truncates, two blank

At `-110.5` (consensus and averaged prices are floats):

| answer | who | consequence |
|---|---|---|
| `0.5249406` | 22 | correct |
| **`0.5238095`** | `mlb/hr_targets`, `regrade_mlb_game_markets` | **`int()` truncation silently reprices to −110** |
| `None` | `mlb/cards`, `fetch_mlb_oddsapi_local` | `int(str(...))` raises, card blanks |

`mlb/hr_targets` is the sharper one: it truncates *silently*, so a −110.5
consensus becomes −110 with nothing logged.

### D7 — decimal odds arriving where American is expected

No implementation refuses them; they cannot, from the value alone. Decimal 2.5
priced as American returns 0.9756 (or 0.9804 truncated). This is a **contract
gap, not an implementation bug** — the fix is a typed price at the boundary, not
a smarter converter. Recorded so nobody spends a session on it.

### D8 — `american_to_decimal` at `0`

`intelligence:_american_to_decimal` and `regrade_mlb_game_markets` both raise
**`ZeroDivisionError`** where four others return `None`. `intelligence`'s only
call site pre-guards, as in D1.

---

## Requirements, and the owner they select

The harness carries five named requirements per concept, each justified by a
case the codebase actually produces. The owner is whatever satisfies them —
not the biggest cluster, which would be a vote.

| concept | meet all | owner |
|---|---|---|
| `american_to_probability` | 15 of 26 | `shared/opportunity_signals.py::implied_probability` |
| `american_to_decimal` | 2 of 6 | `shared/live_lens_local.py::_american_to_decimal` |
| `probability_to_american` | **1 of 5** | `shared/opportunity_signals.py::american_price` |

- **`american_to_probability`** — the 15 survivors are behaviourally identical,
  so this one is a module-ownership call rather than a correctness one.
  `opportunity_signals` wins because it already exports the inverse
  (`american_price`), so the pair can be kept consistent in one file. Its
  by-copy twin `quote_enrichment:_implied_probability` is byte-identical.
- **`american_to_decimal`** — `live_lens_local` and `build_soccer_picks` tie;
  `live_lens_local` is in `shared/`. Neither is a natural home: **`opportunity_signals`
  has no decimal converter at all**, which is why five modules grew their own.
- **`probability_to_american`** — `american_price` is the **unique** survivor
  and the only implementation that round-trips 9/9 while also refusing `None`,
  `""`, `0.0`, `1.0` and `50.0`. `market_lines` also round-trips 9/9 but raises
  on `None` and prices `50.0` at −999900.

---

## STATUS UPDATE — 2026-08-15, lane `probability-clamp-removal`

**One of the three clamp sites is fixed. The other two are blocked on lane
ownership, not on effort or agreement.**

| clamp site | holder | status |
|---|---|---|
| `wnba/cards.py::_american_from_prob` | unclaimed | **FIXED** — delegates to `american_price`; harness scores it **5/5**, was 2/5 |
| `pipeline/intelligence_state.py:1816` (inline) | `memory-cutover-ship` | handoff sent, NOT edited |
| `shared/layer2_board.py::_american_from_probability` | `model-audit-devig-and-hygiene` | handoff sent, NOT edited |

`recommendation-lane-correctness` closed and released `layer2_board.py`, but the
new OPEN lane `model-audit-devig-and-hygiene` claimed it the same day — so the
file was never free. That lane's goal (a) is "exactly one function turns book
prices into a fair probability", which makes it the right owner rather than a
detour.

**One stale comment left behind, and it will mislead:**
`layer2_board.py:1280`'s docstring says it "Mirrors `wnba/cards.py::_american_from_prob`
... including its 2%-98% clamp". The WNBA copy no longer clamps. Flagged to the
owning lane; not editable from here.

**Behaviour change worth stating plainly:** a WNBA moneyline derived from a
degenerate model probability (exactly 0.0 or 1.0) now renders **blank** instead
of ±4900. That is the board contract ("absent renders as absent", web
`932a1f71` / `a86eb4ed`) and is asserted as intended in
`tests/test_wnba_fair_price_unclamped.py`, so a future reader finds it recorded
rather than mistaking it for a regression. Also, at exactly p=0.5 the price is
now `+100` rather than `-100` — same probability, and `+100` is the convention.

---

## Recommendation

Ordered by evidence, not by size of diff.

1. ~~**Fix the clamp (D2). This is the only confirmed live misprice.**~~
   **1 of 3 done (WNBA); 2 blocked on lane ownership — see the status table.**
   Original text:
   **Fix the clamp (D2). This is the only confirmed live misprice.** Replace the
   `max(0.02, min(0.98, p))` clamp in `layer2_board`, `wnba/cards` and the
   inline copy in `pipeline/intelligence_state.py` with `american_price`, which
   refuses out-of-domain input. Two MLB totals rows are wrong on the board right
   now. **Owned by the `recommendation-lane-correctness` lane** for
   `layer2_board`; `wnba/cards` and `intelligence_state` are unclaimed.
2. **Guard the five `0.0`-returning converters (D1).** No live trigger found, but
   `bankroll_manager` has a stake attached and `odds_book_quotes` feeds a
   published edge. One-line `if value == 0: return None` each.
3. **Delete the truncating `int()` conversions (D6)** in `mlb/hr_targets` and
   `regrade_mlb_game_markets`. Silent repricing is worse than a blank.
4. **Then consolidate onto the three owners** — 31 implementations to 3. Do this
   *after* 1–3, so the consolidation is a mechanical move of already-correct
   behaviour rather than a behaviour change wearing a refactor's clothes.
5. **Add `american_to_decimal` to `opportunity_signals`** so the shared module
   covers all three directions and the next module has nothing to re-grow.

---

## Scope notes

- **The 240 bare `except: pass` are out of scope** per the program plan, and
  nothing here touches them.
- **The plan's "40 sites substituting 0.5" over-count is confirmed as a
  correction and NOT re-litigated.** Nothing in this pass touched
  `drive_priors.py`, `faceoff_win_pct`, or any `0.5 * (1.0 + math.erf(...))`
  normal CDF. One 0.5 substitution was observed in passing at
  `bankroll_manager.py:129` (`implied_probability` falls back to 0.5 for stake
  sizing) — recorded, not fixed, not in this lane.
- **`recommendation_engine.py`, `layer2_board.py` and `opportunity_signals.py`
  were read only.** They belong to `recommendation-lane-correctness`. The
  harness imports them; it does not edit them.
- **A naming hazard worth one line:** `recommendation_engine:_parse_american_odds`
  is named like a parser and returns a **probability**. It is behaviourally
  correct (it is in the 15-member survivor cluster) — the risk is a caller
  reading the name and treating the result as a price.
- **Three implementations of a fourth concept** (`_american_profit` in
  `prediction_reconciliation`, `evaluation_settlement`, `ledger_bridge`) were
  found and deliberately **not** differential-tested — price→profit is not
  price→probability. They are a candidate for the next pass.
- **Two converters are unreachable by any tool**, defined inside function
  bodies: `refresh_wnba_oddsapi_props.py::_implied` and
  `intelligence_audit.py::decimal_to_american`.

## What is measured vs. inferred

- **Measured, production, 2026-08-15:** the 1346 `fair_price` values, the 24 at
  ±4900 with none beyond, and the two-row join proving the clamp fired. One
  fetch of `/api/intelligence/query`.
- **Measured, production:** 105 live shortlist rows carry `fair_probability` on
  all 105 and `fair_price` on **none** — so the shortlist route does not serve
  the clamped value; the intelligence-query route does.
- **Measured, local:** all 31 implementations over the grid. Deterministic,
  reproducible by re-running the harness.
- **NOT measured:** whether a `0` price has ever occurred in production. Local
  `reports/intelligence/layer2_shortlist_*.json` mirrors are **all zero-row**
  (the documented `data/**` lossy-mirror trap), and one live fetch of 105 rows
  found none. Absence in one 105-row window is not absence.
- **NOT measured:** `/api/board/game-chips` carries neither field, on all eight
  sports. The 8-sport form 502s; the per-sport form does not. Read as a
  data-shape fact, not as a clean bill of health.
