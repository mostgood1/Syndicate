# SESSION BRIEF — Layer 1 board (the known universe)

> Written 2026-08-16 by the session-setup pass. Paste the "Opening prompt" at
> the bottom into a fresh session. **This brief is an input, not a finding.**
> Program plan `.syndicate/plan_2026-08-14_program.md` carries the standing rule
> that cost three of four audits their premise: **spend the first ten minutes
> re-verifying the inputs a brief tells you not to re-derive.** Every anchor
> below is a `file:line` you can read, not a conclusion you may cite.

---

## 0. Protocol (non-negotiable, before any edit)

1. Read `.syndicate/state.md`, `.syndicate/lanes.md`, `.syndicate/learnings.md`.
2. `/lane open layer1-board-coverage "every in-season game and prop line maps to a sim prediction, pregame and live"`
3. `/preflight` before any deploy. `/checkpoint` every ~30 min.
4. **Commit through an isolated index** (`GIT_INDEX_FILE`), never `git add -A`,
   and read `git diff --cached --numstat`'s DELETION column first. Five other
   sessions share this worktree; a stale shared index has held a revert-in-
   waiting three times in two days.

## 1. What Layer 1 is, and why this session exists

Layer 1 is the **known universe** — every market, pregame and live — and the
user's research surface. Layer 2 is the curation of it. The hierarchy was
settled 2026-08-14 (program Tier 4); Layer 1 is not a legacy path and is not a
deletion candidate.

The measurement that motivates this session: **Layer 1 built `count=0` on 3 of 5
builds.** Under the old reading that was evidence of redundancy. Under the
correct one it is *the research surface being dark ~60% of the time*, unnoticed
because Layer 2 kept working off the shared grid. Confirm whether that is still
true before scoping anything else — the OOM fix and the odds-cadence work have
both landed since it was measured.

## 2. Files this lane owns

Claim these in `/lane open`:

- `syndicate/features/shared/layer1_board.py` (610 lines)
- `syndicate/templates/shared/layer1_board.html`
- `syndicate/blueprints/layer1_page.py`
- the `/api/board/layer1` handler, `syndicate/blueprints/intelligence.py:2479-2650`

**Read-only — held by other OPEN lanes. Do not edit; surface the conflict:**

| file | holder |
|---|---|
| `syndicate/features/shared/layer2_board.py` | `spread-line-sign-convention` (OPEN) — **and the Layer 2 session** |
| `syndicate/templates/intelligence.html`, `static/shared/bet_slip.js`, `static/shared/board_cards.css` | the Layer 2 session |
| `pipeline/intelligence_state.py` | `clamp-fix-to-workers`, memory lane |
| `syndicate/features/shared/opportunity_signals.py` | shared substrate — coordinate before writing |
| `scripts/run_refresh_worker.py`, sim-engine internals | the live sim-engine session |

## 3. The four goals, as acceptance criteria

### G1 — every game and prop line maps to a sim prediction pregame, **including alt lines**

The Layer 1 UI already computes and shows the shortfall: the header reads
`2802 markets / 1927 with a projection` and the `Proj` column is a dot on the
875 that miss. **That is your instrument — do not build a second one.** Start at
`_classify_enrichment` (`layer1_board.py:328`) and `_row_is_enriched`
(`:176`), which decide what counts as projected.

Deliverable: a per-sport, per-market-family table of *projected / total*, with
the alt families (`totals_alt`, `spreads_alt`, `h2h_3_way`, the `_F5`/`_F1`
period markets) broken out separately. In the attached MLB screenshot every
alt-line and period row has an empty `Proj` while its base market is populated —
establish whether that is systematic before theorising about causes.

**Report a rate, not a count.** "875 markets unprojected" is not a finding until
it is *875 of 2802, concentrated in N families*.

### G2 — a prop with no sim data is a fingerprint signal

Two distinct causes, and the whole value of this item is telling them apart:

- **One player missing across many stats** → the game sim's fingerprint is stale:
  lineup or injury state (projected lineups count). Trace back to the fingerprint
  the sim ran on and check its lineup/injury vintage.
- **One stat missing for every player** → the sim does not emit that quantity.
  Then the job is a mapping question: what *does* the sim produce that lines up
  with this prop, and is the gap a projection or an adapter?

Classify every unmapped prop into one of those two buckets before proposing a
fix. Do not open the sim engine's internals — that session is live. Report the
fingerprint finding to it via `send_message`.

### G3 — live lens updates projections **and** shows actual live stat results

MLB is the reference implementation and does this well. Establish MLB's live-lens
path concretely, then audit each other in-season sport against it as a
same-instant A/B on a live slate.

**Known constraint you must verify rather than assume:** program Tier 5 recorded
that no live *game-line* projection existed (`predictions.full` is the pregame
sim) and only props had a live tier. Lane `live-game-line-projection` has since
shipped **both halves** and reports "Tier 5's premise is TRUE in production; the
edges are UNEVALUATED." So the plumbing may now exist while nothing has checked
its output. Read that lane before measuring, and coordinate — do not re-do it.

### G4 — an edge on every play; for Layer 1 this is mostly EV

The `Edge` column is a dot on every row in the attached screenshot even where
`Proj`, `Fair` and `Best` are all populated. That is the sharpest single finding
available and it is reproducible from the payload — an EV computable from
`best_price` against `fair` should never render empty.

Establish which term is missing, at the producer. **Do not fix it by
backfilling at serve time**: the clamp incident proved a web-side backfill
(`if card.get(...) is None`) is structurally inert against an upstream value
that is already present-but-wrong.

## 4. Two traps this specific surface has already sprung

- **`fair_price` had four producers where definition-grepping found three.** The
  one confirmed live misprice came from an *inline* copy at
  `pipeline/intelligence_state.py:1816` with no `def` to grep for. **A count of
  definitions is not a count of producers** — trace the user-visible field
  backwards to its writers.
- **A clamp is not a guard.** `max(0.02, min(0.98, p))` answered an out-of-range
  input with a confident number: 24 served `fair_price` values sat exactly on
  ±4900 where one correct answer was −12488. If you find an unknown being mapped
  onto a plausible default anywhere in the Layer 1 path, that is the same defect
  family as G4's empty edge — it just fails loudly instead of quietly.

## 5. Which sports are in season

**Derive it; do not assume.** Read `reports/manifests/<sport>.json` and the
per-sport slate for today rather than reasoning from the calendar. A sport with
markets quoted today is not necessarily a sport playing today — that conflation
put 1,244 NFL rows starting 34–156 days out onto a "today" board once already
(`layer2_board.py:1012-1026`).

---

## Opening prompt

```
Read .syndicate/brief_2026-08-16_layer1_board.md and follow it.

You own the Layer 1 board — the known universe, pregame and live. Audit every
in-season sport for: (1) every game and prop line, alt lines included, mapped to
a sim prediction pregame; (2) props with no sim data classified as either a
stale game-sim fingerprint (lineup/injury, projected included) or a stat the sim
does not emit — and for the latter, what in the sim maps to it; (3) live-lens
projections updating during live games with the actual live stat alongside, MLB
as the reference; (4) an edge on every play — for Layer 1 that is mostly EV.

Open lane layer1-board-coverage first. A parallel session owns Layer 2
(layer2_board.py, intelligence.html, bet_slip.js, board_cards.css) and another
owns the sim engine — read-only on both, and use send_message rather than
editing across a lane.
```
