# `_model_edge_for` now names its refusals — and the obvious way to do it would have leaked one side's reason onto the other

`[2026-10-15 22:1x–22:5xZ, session 4ab694ed, lane model-edge-refusal-reason, taking the layer2_board lead on user instruction]`

## Why this needed no override

`layer2_board.py` is held by four other OPEN lanes, and the protocol says surface
a contested file rather than edit it. **It did not need overriding** — all four
claims are *section-scoped*, and none covers `_model_edge_for`:

| lane | declared scope |
|---|---|
| `layer2-live-segment-actuals` | `_game_total_actual` + its call in `_live_projection_columns` only |
| `layer2-suggested-opps` | `_stamp_suggested` + its call in `build_layer2_rows` + the `suggested` card columns only |
| `fair-price-v2` | `_resolve_fair` + `_consensus_fair` + fair_v2 shadow stamping only |
| `signal-engine-nba` | `_stamp_likelihood_shadow` + its call in `build_layer2_rows` only |
| **this lane** | **`_model_edge_for` refusal reasons only** |

`check_lane_invariants` agrees, in its own words: *"`layer2_board.py`: 5 lanes
hold DIFFERENT declared sections of it, which is not a contest (the guard permits
each)."* Note that two lanes already share `build_layer2_rows` at *different call
sites*, which is the precedent for scoping inside one function.

**Verified separation after the change:** all seven diff hunks fall inside
`_model_edge_for` (2373–2550) plus its one call site, and the four other lanes'
named functions show **0 touched lines** each. Their tests pass (21).

## The defect

`_model_edge_for` has **four** `return None` paths and, until now, none said
which fired. So a coverage count could not distinguish a **refused** model
opinion from an **absent** one. Measured 2026-10-15 on the served board: of 809
rows carrying a projection and no `model_edge_pct`, **464 (57.4%) were the
plausibility ceiling alone** — and naming them required
`scripts/audit_model_edge_gap.py` to re-derive this function's branches from
*outside*, which is the drift the module's own comments warn about repeatedly.

## The hypothesis was falsified, and that chose the design

I expected to stamp `projection["edge_unavailable_reason"]` in place, since the
per-sport builders already own that field. **That would have been a bug.**

`_model_edge_for(row, side, fair)` receives the **grid** row, whose `projection`
is shared by both sides of a market; the per-side object is the `candidate` the
fan-out builds by copying a fixed field list. Stamping the projection would leak
the reason computed for one side onto the other, **last-writer-wins** — the exact
class of defect this module has paid for before.

So instead:

- `_model_edge_for` takes an **optional out-dict** and names its own refusal;
- the call site stamps `candidate["model_edge_refusal"]`, which is per side;
- `projection["edge_unavailable_reason"]` is **never touched**, so the upstream
  per-sport reasons (e.g. `prob_interval_swamps_edge` on 49 soccer rows) keep
  their provenance and the two cannot be confused;
- omitting the parameter is **inert**, which is how every existing caller behaves.

The four named refusals, verified through the deployed function:

```
no projection        edge=None  {'reason': 'no_projection'}
ceiling              edge=None  {'reason': 'edge_exceeds_plausibility_ceiling',
                                 'edge': 15.87, 'ceiling': 15.0}
not an opposite      edge=None  {'reason': 'projection_side_not_an_opposite',
                                 'projected_side': 'home', 'row_side': 'draw'}
ACCEPTED (control)   edge=4.2   {}          <- no reason on an accepted edge
inert without the arg -> None
```

The ceiling carries **both** the edge it rejected and the bound it failed,
because *"dropped, not clamped"* is only actionable with both.

## Tests, and the gap mutation testing exposed

**11 tests.** One per refusal path, plus an accepted-edge control, plus the
properties that make it safe: the out-param is inert when omitted, the shared
projection is **never** mutated, two sides of one market get their own dicts, and
an upstream `edge_unavailable_reason` survives untouched.

**6 mutation cases, 4 caught, 2 explained:**

| mutant | result |
|---|---|
| the ceiling stops naming itself (the shipped defect) | **caught** (2 failures) |
| the ceiling drops the numbers that make it actionable | **caught** |
| not-an-opposite stops naming the two sides | **caught** |
| **the call site stamps the shared projection instead of the candidate** | **caught** — see below |
| `_note_refusal` writes when no out-dict was passed | survived — **bad mutant**: it assigns a throwaway local, so the caller's dict is unaffected either way |
| "stamp the SHARED projection" | survived — **bad mutant**: it writes a `globals()` key and never touches a projection |

The two survivors are *mutants that do not do what their labels say* — the third
category in this session's own taxonomy (dead code / missing test / bad mutant),
and the second time today I built one.

**The fourth mutant found a real gap and it is now closed.** My tests drove
`_model_edge_for` directly and therefore protected nothing at the call site:
moving the stamp to `row["projection"]` passed all nine. No cheap behavioural
fixture for `build_layer2_rows` exists in this suite (the lightest candidate only
mentions it in prose), so the guard reads the **source** and asserts the stamp
targets `candidate` and not any projection dict, and that it is gated on
`model_edge is None`. **It is labelled a source guard, because a structural guard
misses meaning** — it cannot tell that the stamp is *correct*, only that it is
not writing the shared projection, which is the one mistake worth blocking.

## Not done

**No restart, no deploy.** This is observability-only — an additive field on
refused rows, no scoring change — and a restart happened at 20:25:06Z tonight;
the restart rule says batch non-urgent changes. **So the field is not on the
served board yet**, and `scripts/audit_model_edge_gap.py` still re-derives the
branches externally until it is. Stated rather than implied.

The second half of the original lead is untouched and still unowned: whether a
15-point bound derived on MLB game h2h belongs on NFL/NCAAF player props
unchanged. That is a modelling question, not an observability one.

## Method note

Edits were confined to `_model_edge_for`'s own line span after a first attempt
using file-wide string anchors matched one of them **three times** — 
`projection = row.get("projection")` is a repeated idiom in this 5,000-line
module. Separation from the other four lanes was verified by diff hunk range and
by grepping their named functions for touched lines, not by assertion.
