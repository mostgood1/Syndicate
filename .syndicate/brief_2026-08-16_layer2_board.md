# SESSION BRIEF — Layer 2 board (the curation)

> Written 2026-08-16 by the session-setup pass. Paste the "Opening prompt" at
> the bottom into a fresh session. **This brief is an input, not a finding.**
> Program plan `.syndicate/plan_2026-08-14_program.md` carries the standing rule
> that cost three of four audits their premise: **spend the first ten minutes
> re-verifying the inputs a brief tells you not to re-derive.** Every anchor
> below is a `file:line` you can read, not a conclusion you may cite.

---

## 0. Protocol (non-negotiable, before any edit)

1. Read `.syndicate/state.md`, `.syndicate/lanes.md`, `.syndicate/learnings.md`.
2. `/lane open layer2-board-quality "the curated board scores, labels and moves correctly, and never contradicts the sim"`
3. `/preflight` before any deploy. `/checkpoint` every ~30 min.
4. **Commit through an isolated index** (`GIT_INDEX_FILE`), never `git add -A`,
   and read `git diff --cached --numstat`'s DELETION column first.

## 1. The collision you must resolve before writing a line

**`syndicate/features/shared/layer2_board.py` is claimed by OPEN lane
`spread-line-sign-convention`** (session `lane-cleanup`), which fixed the
away/home handicap inheritance at `layer2_board.py:852` and deployed to workers
~23:1xZ with **artifact output still unverified**. Its findings sit at
`lanes.md:207-320`.

Do not edit that file until you have either (a) reached the holding session via
`send_message` and taken the claim, or (b) confirmed the lane is closed. The
repo's own precedent is that this collision *dissolves by re-measuring* rather
than by negotiating — `clamp-fix-to-workers` found the same one and resolved it
by establishing the fix had already shipped. Do that first.

## 2. Files this lane owns (once §1 clears)

- `syndicate/features/shared/layer2_board.py` (1793 lines) — **contested, see §1**
- `syndicate/templates/intelligence.html`
- `syndicate/static/shared/bet_slip.js`, `syndicate/static/shared/board_cards.css`
- the `/api/board/layer2-shortlist` handler, `syndicate/blueprints/intelligence.py:2698+`

**Read-only:** `layer1_board.py`, `templates/shared/layer1_board.html`,
`blueprints/layer1_page.py` (the Layer 1 session), `pipeline/intelligence_state.py`
(`clamp-fix-to-workers`, memory lane), sim-engine internals (live session).
`opportunity_signals.py` is shared substrate — coordinate before writing, because
**item 2 below lands squarely inside it.**

## 3. The eight goals, as acceptance criteria

### G1 — the compact game rail lists every game, opp or not, and finals stay

Two halves. Games with no opportunity must still appear; a game going final must
**remain on the board and move to the end of the rail** rather than vanish. Start
at `_within_horizon` (`layer2_board.py:1476`) and `SHORTLIST_HORIZON_DAYS`
(`:1026`), and at the shared scoreboard hydration noted in
`blueprints/intelligence.py:2182`.

**Read the comment block at `layer2_board.py:1012-1026` before touching the
horizon.** It exists because the board once served 1,244 NFL rows starting 34–156
days out while no NFL game existed that day. "Quoted today" is not "playing
today". G1 widens what the *rail* shows; it must not widen what the *shortlist*
scores.

### G2 — Layer 1's data feeds Layer 2, and the scoring model gets audited

**The scoring model exists and is documented — audit it, do not rebuild it.**
`blended_score()`, `syndicate/features/shared/opportunity_signals.py:497-575`:

```
value       = ev_pct + 0.5 * model_edge                    (additive, both vig-free)
reliability = book_confidence * freshness * price_reliability   (multiplicative)
score       = min(value, value * reliability)
```

The `min()` is load-bearing and its reasoning is written in place: `value *
reliability` **inverts for negative value**, so the less a bad row was trusted the
better it ranked. Measured on 256 served rows: `corr(reliability, score) =
−0.8312` on the 156 negative rows against a `+0.8560` control on the 98 positive
ones. Do not "simplify" that away.

Three real audit questions, in order:

- **Is `freshness_factor` reading a signal that exists?** It discounts on quote
  age, and MLB odds were refreshed on a **~121.6 min** cadence. Lane
  `odds-cadence-off-the-mlb-peak` reports 1a/1b verified in production
  2026-08-16 05:51:48Z with the **effect still unmeasured**. Establish the real
  current sampling interval before trusting or tuning this term.
- **There is no movement or steam term in the score at all.** That is G4.
- **`_SCORE_SIM_WEIGHT = 0.5` on `model_edge`** — is a half-weight on the sim
  right, and does it hold when `model_edge` is absent? Note `blended_score`
  returns `None` when both value terms are missing, which is correct, and
  `_price_reliability` returns `1.0` on missing input, which is the
  unknown-must-not-default-permissive pattern — check whether that is deliberate
  here or an inherited default.

On the "Layer 1's data feeds Layer 2" half: the two boards are **siblings off the
shared grid, not sequential** (program Tier 4). Confirm the topology empirically
before asserting a pipeline that does not exist.

### G3 — best-book must use Layer 1's condensed book list

**Measured while writing this brief: Layer 2 has no book allowlist of any kind.**
Layer 1's list is a client-side JS array, `DEFAULT_BOOKS` at
`syndicate/templates/shared/layer1_board.html:267`, applied at `:839`/`:862` to
produce the "My books 11 / All books 36" toggle. Layer 2's row builder filters on
nothing equivalent, which is why picks surface on books the user cannot bet.

The fix is not to copy the array. **One owner for the book shortlist, consumed by
both boards** — a client-side constant in a Jinja template cannot be that owner.
This is the same "one source owns it, every consumer reads it" shape as the
spread-sign lane.

### G4 — line/odds movement and steam are dark; get them back and into the score

**They did not decay — they were deliberately disabled, and the reason matters.**
`_layer2_movement_columns` (`layer2_board.py:1152`) is `return {}` with an
unreachable body below it. `#372` turned it off because the join loaded
`load_odds_history_payload_for_sport` — a **~20 MB MLB shard** — *inside* the
builder, and `#370` made it try two shard keys, so a miss loaded a second
multi-MB payload. It **stalled the shortlist build entirely**: last good build
00:22:21Z, then 70 minutes of reaching `EXPOSURE_BUDGETS_APPLIED` and never
printing `LAYER2_SHORTLIST` again. No exception, so no failure log either. Every
producer-side fix queued behind that build stopped shipping.

**Naively re-enabling it re-stalls the board.** The docstring states where it
belongs: *where the odds tracker already holds the data, not in a per-build read
of a multi-megabyte artifact.*

Two further facts already established, both worth keeping:

- Only `h2h`, `totals`, `spreads` carry history — `_MOVEMENT_TRACKED_MARKETS`
  (`:1244`). Overlap on the served board was **event+market 11 of 73**. The
  `"Not tracked"` label is a string derived from the market name, does no IO, and
  is deliberately retained; it covered 179 of 200 rows.
- `_movement_shard_keys` (`:1206`) shards **Central date first**. A UTC-first
  shard worked for eighteen hours a day and failed totally for six — the
  pre-midnight measurement "proved" a bug that was real.

Program plan, Corrections: nothing in the movement family — the 23 movement
implementations, `movement_velocity`, the steam detector — should be trusted or
extended until the real sampling interval is known. That is the same
prerequisite as G2's freshness term; settle it once, use it for both.

### G5 — opportunities served against our own sim

`_model_edge_for` is at `layer2_board.py:783` and `_fair_by_side` at `:670`.
Program Tier 2 (model Lane A) already names "negative-model-edge rows" as a
known-wrong behaviour with no metric required to justify the fix.

Establish first **whether the sim disagreed or was absent** — 143 of 200
published rows carried no model at all. A row with no model is not a row that
contradicts the model, and the two need different fixes. Then decide: suppress,
or label. That is a product call — surface it rather than picking silently.

### G6 — matchup/pick columns are vague about side and team

`_pick_label` (`layer2_board.py:1029`) already resolves player → home team → away
team → title-cased side, and exists because the card normaliser otherwise renders
the literal string `"candidate"`. So the column is not unhandled — audit what it
actually emits per market family. In the attached screenshot, `-1.5 · spreads`
against a matchup of `CHICAGO WHITE SOX @ DETROIT TIGERS` with pick
`Detroit Tigers` is readable, but `Over  7.5 · totals` with matchup
`BALTIMORE ORIOLES @ TAMPA BAY RAYS` does not say *whose* total, and the
`0.5 · batter_rbis` rows do not carry the line's direction.

Note this column depends on the spread-sign fix from §1 being correct. Sequence
accordingly.

### G7 — a live game with a still-valid opportunity shows its live-lens projection

Gate on **the line still existing**, not on the game being live. Coordinate with
the Layer 1 session, which owns the same question from the universe side (its
G3), and with lane `live-game-line-projection` — that lane reports both halves
shipped and **v2 still unexercised**, i.e. plumbing done twice, evaluation not
started. Read it before measuring.

### G8 — the betslip must collapse the way Layer 1's does

A small arrow to the right of the board, not a collapse to the bottom of the
screen. Layer 1's implementation is the reference — read
`templates/shared/layer1_board.html`; write in `templates/intelligence.html`,
`static/shared/bet_slip.js`, `static/shared/board_cards.css`. The smallest item
here; do it early for a clean win, not last.

## 4. Which sports are in season

**Derive it; do not assume.** Read `reports/manifests/<sport>.json` and today's
per-sport slate. See G1's horizon warning — quoted ≠ playing.

## 5. Verification standard

`.syndicate/` rule: **never claim a fix works without a measurement written to
`deploys.md`.** For this board that means the *served payload* from
`/api/board/layer2-shortlist`, not a unit test. The user has twice reported a
board defect that automated checks missed — go straight to the served payload.
One change per deploy while diagnosing.

---

## Opening prompt

```
Read .syndicate/brief_2026-08-16_layer2_board.md and follow it.

You own the Layer 2 board — Syndicate's curation of the universe. Audit every
in-season sport for: (1) the compact game rail listing all of today's games with
or without an opportunity, finals staying on and moving to the end of the rail;
(2) Layer 1's data reaching Layer 2, and an audit of the blended_score scoring
model; (3) best-book restricted to the same condensed book list Layer 1 uses;
(4) line/odds movement and steam tracked again and folded into the score;
(5) no opportunity served that contradicts our own sim; (6) matchup/pick columns
unambiguous about side and team; (7) live-lens projection shown once a game is
live and the opportunity's line still exists; (8) the betslip collapsing to a
small arrow beside the board, as Layer 1 does.

Resolve the layer2_board.py claim held by OPEN lane spread-line-sign-convention
BEFORE editing it, then open lane layer2-board-quality. A parallel session owns
Layer 1 and another owns the sim engine — read-only on both, and use
send_message rather than editing across a lane.
```
