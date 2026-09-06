# HANDOFF — `todo.md #119` needs the NCAAF half recorded, and I may not write it

**From:** lane `ncaaf-live-resim-wire`, session `520cd594-1ffa-4116-8951-4c4b53ffbfcf`, 2026-09-05 ~23:30Z
**To:** whoever holds `docs/ai_context/todo.md` — currently lane `accuracy-ledger-budget-raise` (session `82fe0160-00b0-4b4b-bd63-2ff14849f885`), per `lane_claims.claims_by_path` on `origin/main`.

## Why this is a file and not an edit

CLAUDE.md says `todo.md` is the canonical cross-session TODO list and that it
must be updated before finishing. It also says: *if another OPEN lane lists a
file you need, stop and surface the conflict; do not edit across lanes.* Those
two instructions collide on this file, and the second one wins.

**I wrote the edit, the post-write guard caught it, and I reverted it** (3,066,196
→ 3,068,028 → 3,066,196 bytes; `git status` clean). This file is the edit,
preserved verbatim, so the work is not lost and nobody has to reconstruct it.

`#71`'s check — "did shipped work actually reach `todo.md` or `todo_closed.md`" —
is therefore **NOT satisfied for this lane**, deliberately and visibly, rather
than satisfied by an out-of-lane write.

## What to do

Replace this exact prefix of the `| **119** |` row:

```
| **119** | 🟡 **Build live game-state tracking AND a live re-simulation model for NFL and NCAAF — currently neither exists.**
```

with the block below. Everything after that prefix in the original row is
untouched; the replacement re-states the original sentence at its end so the row
still reads as one continuous cell and nothing is deleted.

```
| **119** | 🟡 **NCAAF HALF SHIPPED 2026-09-05 AND PRODUCING; NFL HALF STILL OPEN — which is why this stays amber.** Both halves this item asked for now exist for NCAAF: (a) live game-state tracking landed earlier as `ncaaf/live_game_state.py` (ESPN team-id join, lane `ncaaf-live-lens-state`), and (b) the in-play win-probability re-simulation is `ncaaf/live_resim.py` (lane `ncaaf-live-resim`, `ca5be54b`) wired into refresh-worker's tick by lane `ncaaf-live-resim-wire` (`262fd2cf`, `933e9beb`, live on `ffe8714b`). It is NOT a bolt-on adjustment to the pregame number, which is what this item warned against: `simulate_game` resumes from the live quarter, clock, score, down, distance and field position and runs a rest-of-game Monte Carlo, and pregame output is bit-identical over 40 shared seeds. The shape guess in this item was right too — it IS drive-based rather than a continuous-time decay, because smartsim2's state machine already was. MEASURED IN PRODUCTION 2026-09-05T23:15:59Z: `/api/ops/live-lens/snapshot-index?sport=ncaaf` `sources_seen {live_resim: 8, pregame: 43}`, `index_size 8`, coverage `games 51, live_resimmed 8, refused 43` against 20 ESPN games in progress (8 FBS-vs-FBS, the rest FCS opponents the artifact never carries). Boise State led Oregon 17-7 in Q2 while the board published "Oregon 97.7%"; the re-sim says 0.2500 on neutral ratings. **OPEN AND NOT CLAIMED: the board half** — a live row carrying `projection.live_aware: true` — first join attempt missed 257 of 257 rows on a key-space mismatch (lens keyed from CFBD names, grid from the odds source's), fixed in `933e9beb`, reading owed on the next slate. **NFL HAS NEITHER HALF AND NOTHING HERE CHANGES THAT**; `#118` (NHL) is likewise untouched. Details: `state_football.md [ncaaf-live-resim]`, `deploys.md` 2026-09-05. Original text follows. — **Build live game-state tracking AND a live re-simulation model for NFL and NCAAF — currently neither exists.**
```

## The one thing to sanity-check before applying

The row stays **amber, not green**, and that is deliberate on two counts: NFL has
neither half and nothing in this work touched it, and the NCAAF board half is
measured-and-failed-then-fixed but **not yet re-read**. If you apply this after
that reading lands, the honest edit is to replace "reading owed on the next
slate" with the reading itself — not to promote the row.

## If the claim is stale

`accuracy-ledger-budget-raise` claims the WHOLE file, which is the widest
possible claim on the repo's most-shared document. If that lane is done with it,
releasing it is worth more than this handoff — every lane that ships anything has
to write here.
