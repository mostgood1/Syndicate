# Layer 1 model-edge join — full audit, every sport, every market

`[lane layer1-model-edge-join, 2026-08-30]`

## The question, and why the existing instrument could not answer it

> "plays hitting the layer 2 board / polymarket and kalshi ... the layer 1 board
> is not joining model edge pct correctly across the boards for all sports"

Correct, and worse than the framing suggested. The boards **do** carry a model
view — 7,970 of 13,262 rows carry a `projection`. What they do not carry is a
model **edge**, which is the only thing Layer 2 ranks on.

`scripts/audit_layer1_completeness.py` reported MLB at 80.0% and the platform
looking broadly healthy, because it counted `projection` and nothing else. A row
with `projected` and no edge contributes **nothing** to Layer 2: `blended_score`
falls back to EV alone, and under proportional devig EV against fair is
identical for both sides of a market, so those rows rank by the book's hold.
The audit was answering the question next to the one that matters. It now
reports `proj`, `edge`, `mfair` and the leading refusal reason side by side, and
takes `--state pregame|live|final`.

## Baseline — production, 2026-08-30

`/api/board/layer2-shortlist` → `per_sport_ingest[sport]`, the worker's own
counters:

| sport  | grid_rows | sides_priced | rows_with_model_edge | coverage |
|--------|-----------|--------------|----------------------|----------|
| mlb    | 2,912     | 5,316        | 318                  | 6.0%     |
| ncaaf  | 470       | 939          | **0**                | **0.0%** |
| nfl    | 1,247     | 2,494        | 674                  | 27.0%    |
| soccer | 14,395    | 15,682       | 339                  | 2.2%     |
| wnba   | 1,220     | 2,404        | 75                   | 3.1%     |
| **all**| —         | **26,835**   | **1,406**            | **5.2%** |

`/api/board/layer1?window=slate`, same instant: 13,262 rows, 7,970 projected,
**465 with `edge_vs_market_pct` (3.5%)**, **0 with `edge_vs_modelled_fair_pct`**.

Pregame only (`--state pregame`), which is the population that can legitimately
carry an edge at all:

| sport  | rows | projected | MODEL EDGE |
|--------|------|-----------|------------|
| mlb    | 239  | 92.5%     | 69.5%      |
| wnba   | 528  | 27.3%     | 15.0%      |
| nfl    | 169  | 75.7%     | 31.4%      |
| ncaaf  | 170  | 100%      | **0.0%**   |
| soccer | 191  | 63.9%     | **1.6%**   |

## D1 — the modelled-fair edge has never once run. Two breaks, in series.

`book_margin_model.modelled_fair_edge` prices a projection against a modelled
fair on rows the market cannot price two-sidedly. It has its own field, its own
basis, three call sites, and a user decision behind it (2026-08-17).

**Break 1 — ordering.** It reads `row["modelled_fair"]`, which
`attach_margin_model` writes. Every production path calls `attach_projections`
FIRST:

```
book_grid_artifact.py      attach_projections :222   attach_margin_model :340
pipeline/layer2_shortlist  attach_projections :1066  attach_margin_model :1069
blueprints/intelligence    attach_projections :2670  attach_margin_model :2677
```

The field was absent at the only moment it was ever read, on every sport, on
every path. **9,161 rows carry a `modelled_fair`; 0 carry the edge.**

Falsification test run rather than reasoned: with `modelled_fair` attached
first, the identical call on the identical row shape returns
`{'edge_vs_modelled_fair_pct': 3.75, ...}` where it returned `None` before.

**Break 2 — the reader.** `layer2_board._model_edge_for` accepted
`edge_vs_market_pct` and nothing else. Even a populated field would never have
ranked. Half a fix is inert; this needed both.

**Break 3 — the side key.** `modelled_fair` is keyed by the row's own side
vocabulary; the projection's `side` is its own framing and is frequently a
different token for the same outcome. Measured over the 9,161: 1,278 soccer
goal-scorer rows stamp `"over"` against a `("yes",)` row, 1,939 stamp the
PLAYER'S NAME, 73 stamp the genuine complement. Every one of those three needs
different handling and guessing inverts an edge.

**FIXED** — `board_enrichment.attach_modelled_fair_edges`, run from the tail of
`attach_margin_model` (the one hop downstream of both halves on all three call
sites). Key from the row, polarity from the projection, complement where they
differ, REFUSE-and-name where the polarity is unknown. Live and settled rows are
skipped so it cannot route around `live_edge_policy`.

**Measured against production payloads** (real rows, real `modelled_fair`, the
new code run over them): model-edge coverage **3.2% → 21.9%**, +2,654 rankable
rows. All pregame. Priced 3,165, of which 552 exceeded the existing 15-point
ceiling and were correctly dropped.

**AND THE RANKING IMPACT IS ZERO, WHICH IS THE HONEST HALF OF THIS RESULT.**
Scored with the same `blended_score` Layer 2 uses, the 2,611 newly-priced rows
top out at **−4.73** against a live shortlist whose #50 is **+0.64** and whose
#1 is **+4.69**. Not one enters the top 200. The cause is structural: EV against
a `book_margin_model` fair is `-hold` for every such row regardless of the bet
(`_row_ev_is_hold_restatement` documents exactly this), so the hold term
dominates whatever the model edge says.

So this fix makes 2,654 rows **correct, visible and attributable**, and rescues
them from the `rows_uninformative_ev: 1269` exclusion — but it does **not** by
itself put plays on the board. See "the open decision" below.

## D2 — WNBA spreads: the sim's own line never matched itself

`wnba_game_projections` prices a real Monte Carlo `p_home_cover` when the row's
line IS the sim's own market line. It compared `row["line"]` against
`sim_market_home_spread` raw. Those are **opposite frames**: `#262` made the
grid's line canonical in the AWAY frame (`book_grid._canonical_line` is
`-line if selection == "home" else line`), while the sim's field is the HOME
side's number by its own name.

Every WNBA spreads row on production, 2026-08-30:

```
Golden State @ Portland    row  -5.5    sim  +5.5     <- the SAME line
Connecticut  @ Dallas      row +14.5    sim -13.5
LA Sparks    @ Seattle     row -15.5    sim  +1.0
```

`has_prob` False on 100% of them; **0 of 58 WNBA spreads rows carried an edge**.
TOTALS, whose line has no side and therefore no frame, matched on the first try
and priced (174.5 == 174.5) — which is what attributes this to the SIGN and not
to the data: the same mechanism works one branch over.

**The tests are why it survived.** Every fixture used `line=2.0` with
`sim_market_home_spread=2.0` — a state production cannot produce. They passed
throughout, on a slate shape that does not exist. Fixtures corrected to
production's frame and `test_spread_frames_must_be_opposite_to_match` added so a
same-frame fixture now fails.

`edge_vs_line` is NOT affected and was deliberately left alone: `projected -
row_line` is `margin + home_line`, the cover cushion, which is correct precisely
BECAUSE the row's line is away-framed. The two uses need opposite handling and
only one was wrong.

## D3 — WNBA's alternate ladder was documented and unreachable

The module docstring has said since `#263` that a `spreads_alt`/`totals_alt` row
"stays exactly as decision 3 describes: projected-only, probability null,
honestly labelled as an alternate line". The code could not produce that: the
market filter was `{"h2h","spreads","totals"}`, so an alt row never entered the
loop, was never counted in `rows_considered`, and reached the board with no
projection AND no reason — indistinguishable from a game the sim never ran.

Pregame 2026-08-30: `totals_alt` 162 rows, `spreads_alt` 98, against 20 `totals`
and 22 `spreads`. **The alternate ladder was six times the main line and all of
it was silent.** FIXED, plus `alternate_line_rows` / `rows_at_sim_market_line`
counters so the reachable population is visible rather than inferred.

## D4 — four producers served a blank edge with the reason key ABSENT

`prop_projections` was fixed for this on 2026-08-16 ("284 of MLB's 2,843 served
rows ... a reader could not tell them from a broken join"). Three producers
never went through it. Measured pregame 2026-08-30:

| producer | rows | markets |
|---|---|---|
| `nfl_game_projections` h2h | 25 | every NFL moneyline |
| `nfl_game_projections` spreads | 50 | every NFL spread |
| `wnba_projections` (props) | 42 | points_rebounds, points_assists, rebounds_assists |
| `wnba_game_projections` | 11 | off-line spreads/totals |

Absent and None are different answers — absent indicts the producer, None
indicts the input. All four now always set the key and always carry a reason.

## D5 — NFL h2h could be priced and was not, and the clock is running

The NFL h2h branch produced `model_prob_over` and never set
`edge_vs_market_pct` at all. `skill_note` returns None for a **regular-season**
profile, so the caveat that justifies withholding an edge does not exist there —
and the 2026 regular season opens **2026-09-10, eleven days after this
measurement**. Left alone, the silent branch becomes the silent branch on every
real NFL moneyline of the season.

Now: preseason profile → REFUSE, naming the measured verdict (`#377`'s argument
unchanged, corr −0.047 over 146 games). Regular season → PRICE it, exactly as
the totals branch does.

## D6 — NFL spreads refused on a premise the grid contradicts

The reason read "spread row does not state which side its line belongs to". It
does, and has since `#262`. The real blocker is the margin model's −0.047
correlation, which the h2h branch one level up already names. The old wording
implied a labelling fix would unlock it; it would not. Reason corrected, refusal
unchanged. The test that pinned the false premise was rewritten with the reason
recorded in it.

## D7 — MLB `batter_strikeouts`: a pitcher market under a batter market's key

betrivers publishes starting-pitcher strikeouts under `batter_strikeouts`. Four
rows 2026-08-30 — Seth Lugo 4.5, Parker Messick 6.5, Drew Rasmussen 5.5, Zebby
Matthews 4.5, all starters, all in a band no batter reaches. They joined to
nothing while the identical market under `strikeouts` ran at 94.3%. Aliased **by
subject, not by key**: only when the named player is a pitcher this slate's sim
projected, so a genuine batter-strikeouts market still falls through to the
hitter path.

---

# Gaps found and NOT taken, with the reason

**MLB live props — the largest single remaining hole, and it belongs to another
lane.** `snapshot_live_prob_seen: 0` while the live lens carries
`with_live_projection: 256` on 294 live rows. `liveModelProbOver` is the only
field `live_projection_join` prices and the producer never emits it: cards props
win at `syndicate/features/mlb/live_lens.py:1298`, so the Monte Carlo rows —
the sole source of that field — are discarded whenever the cards artifact has
any. 241 rows refuse with `no_live_probability`. **OPEN lane
`live-prob-producer-reader-gap` holds `live_projection_join.py` and is a
declared no-code-change diagnostic lane.** Surfaced, not taken.

**NCAAF — 0 edges on 100% of rows, by policy, and it is the Kalshi blocker.**
Every projection carries `model_skill`: margin MAE 15.775 vs market 12.212,
n=2233, t=+17.20; totals 1.67× over-dispersed and never scored. The refusal is
correct. But NCAAF also indexes **1 game** against 39 scheduled
(`rows_unmatched: 458` of 470 on 08-30, source
`smartsim2_projections_2026_wk1.csv`), which is a separate coverage problem.
Owned by `ncaaf-pace-block` and `ncaaf-no-orders`.

**WNBA h2h — 0 edges by an explicit standing decision.** `model_skill` reads
`sample_games: 0`; the code's own comment records a measured +31.7pp moneyline
edge off an unvalidated sim as the reason. Turning it on is "a separate call for
whoever backtests the sim", and I did not take it.

**Soccer props with no projection at all — 2,120 pregame rows.**
`alternate_totals_corners` 310, `player_to_receive_card` 176,
`player_to_receive_red_card` 171, `btts` 72, plus ~1,391 unmatched players. The
model does not emit these markets. Engine work under
`docs/ai_context/model_engine_standard.md`, not a join.

**NBA / NHL / NCAAB — no projection source wired at all**
(`board_enrichment._attach_projections_by_sport` falls through to
`{"supported": False}`). All three are out of season; it is a structural gap,
not a live one.

**MLB `h2h_lay` — 14 rows, deliberately NOT projected.** Prices are in the same
frame as `h2h` (checked on 6 games: 4 near-identical, all 6 same direction), so
it *looks* safe to alias. But a lay bet wins when the side LOSES, and the grid
does not record which reading it stored. On a moneyline, where books are
sharpest, an inverted recommendation is the worst available outcome for 14 rows
on exchange-only books. Recorded rather than guessed.

---

# The open decision, for the user

D1 makes 2,654 rows carry a correct model edge and **none of them reach the
board**, because their EV is structurally `-hold`. Making them rank means
computing EV against the MODEL's probability instead of against the modelled
fair — a real and meaningful number, but one that is fully dependent on models
whose `model_skill` currently reads `sample_games: 0, "never backtested"` for
soccer props.

That is a product decision with real downside, not a join fix, so it is **not
taken here**. It is the difference between "the board shows the model's view"
and "the board recommends acting on it".

# Verification owed

Re-run after deploy and state, from the served payload:
`rows_with_model_edge / sides_priced` per sport, before and after, plus the count
carrying `edge_vs_modelled_fair_pct`, plus `rows_at_sim_market_line` for WNBA
spreads (currently structurally 0). A rate with its denominator, not a test pass.
