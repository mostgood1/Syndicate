# Deploy manifest — refresh-worker

**Purpose.** Refresh-worker deploys are expensive in a way web deploys are not:
each one **kills any in-flight MLB sim and board build**, and each one **reboots
the container, resetting the memory floor** that `refresh-worker-oom-recurrence`
needs deploy-free windows to measure. So changes queue here and ship together,
rather than one deploy per change.

**This file is a queue, not a record.** Shipped entries move to `deploys.md`
with their measurement. An entry sitting here has NOT been deployed.

---

## How to use it

**1. Never deploy `main`.** Refresh-worker runs a deploy branch, not `main`, and
it is far behind: live `8e3d2f95` is **56 commits / 38 files** behind `origin/main`
as of 2026-08-17 15:1xZ — and that drifted from 55/37 in the ten minutes it took
to write this file, which is the point of the standing caveat at the bottom. The
ledger records a prior attempt — deploying `main`
outright **failed preflight on scope**: 520 commits, 207 files, 85,232 insertions
from seven sessions, *including work the ledger holds*.

**2. Cut from the service's OWN live SHA** and cherry-pick only the queued
commits:

```bash
git worktree add --detach /c/tmp/rw-ship <LIVE_SHA>
git -C /c/tmp/rw-ship cherry-pick <sha1> <sha2> ...
git -C /c/tmp/rw-ship push origin HEAD:refs/heads/deploy/refresh-worker-<date>
```

**3. Re-read the live SHA immediately before deploying.** `render_deploy.py`
refuses a target that is not a descendant of the current live commit, and it is
right to: on 2026-08-14 a "pure restart" became a rollback of 850 lines within
ninety seconds because a peer deployed in between.

**4. Verify by CONTENT, not ancestry.** Because the worker runs cherry-picks,
`git merge-base --is-ancestor` lies here. Compare blobs:
`git rev-parse <LIVE_SHA>:<path>` against your branch's.

**5. Gate before firing.**
```bash
py -3 scripts/check_deploy_safety.py     # MLB sim / board build / live games
py -3 scripts/deploy_claim.py status     # is another session mid-ship?
```
`NOT CLEAR` on refresh-worker means an in-flight sim **will die**. Unlike web,
that is a real cost — wait for it.

**6. Check the OOM lane's window.** `refresh-worker-oom-recurrence` is OPEN with
the allocator inside its ~2 GB transient still unnamed, and its evidence is "22
excursions over **5 deploy-free windows**". A deploy resets that. Its stated hold
("until its attribution is written") IS satisfied — attribution is written — so
this is a courtesy, not a block. Tell them.

---

## Queued

**EMPTY as of 2026-08-17 17:0xZ — all three entries SHIPPED.** Deployed together
as `b20072cd` (`dep-da1jkhm417fc73akijag`, live 16:50:48Z), cut from the then-live
`8e3d2f95`:

| file | commits | outcome |
|---|---|---|
| `live_gameline_join.py` | `28b03fef` | **MEASURED** — `edge_basis` observed on served rows, 17:44:30Z. Row closed in `deploys.md`. |
| `wnba/cards.py` | `ea9a2be8`, `a3cecedd` | shipped. **Verification owed by its owner** — I did not assess it. |
| `game_shape.py` | `28cc8814` | shipped. **Verification owed by its owner** — I did not assess it. Brought a 5,416-line generated `mlb_leverage_table.py`, function-locally imported, measured at 1.14 MiB resident / 30.9 MiB transient import peak before firing. |

**Two of the three carry unmeasured verification obligations that are not mine.**
Shipping is not verifying; their lanes should confirm behaviour on a live slate.

**Next deployer: re-derive from scratch.** Do not treat the table above as the
queue — it is history now. Run the content diff at the top of this file against
the then-current live SHA.

## Previously queued (shipped, kept for the recipe)

Determined **by content** (`git diff --name-only <LIVE_SHA> origin/main`, filtered
to worker-run paths), not by reading commit subjects: of 10 commits touching
worker code since the live SHA, **7 are already present** in `8e3d2f95` as
cherry-picks. Only these three files actually differ.

### 1. `syndicate/features/shared/live_gameline_join.py` — `28b03fef` — `+31 −0`
- **What:** sets `projection["edge_basis"] = "live" | "pregame"` so a consumer can
  tell which probability `edge_vs_market_pct` was computed against.
- **Risk: minimal — purely additive.** Adds one key, changes no existing value,
  and nothing reads it yet.
- **Why it is queued rather than shipped:** it has no urgency of its own, so it
  was not worth killing a running sim for. Owner decision, 2026-08-17.
- **Verification owed:** `edge_basis` present on `full/*` live rows of
  `/api/board/layer2-shortlist`, `"live"` where `live_aware` is true. **It has
  never been observed on a served row.** Open obligation in `deploys.md` under
  `live-edge-basis`.
- **Do NOT "tidy" this into a rename.** `layer2_board._model_edge_for` reads
  `edge_vs_market_pct` directly; renaming makes the board price LIVE rows off a
  PREGAME edge. Pinned by `tests/test_live_gameline_edge_basis.py`.
- Lane: `live-edge-basis`. Tests: 6, and 114 green in a clean worktree.

### 2. `syndicate/features/wnba/cards.py` — `ea9a2be8`, `a3cecedd` — `+162 −5`
- **What:** `#455` — a WNBA pbp skeleton was served over real data all day and
  stored so it kept being served; and a completed overtime game published as in
  progress, forever.
- **Risk: NOT assessed by me.** Another lane's work; the largest diff of the
  three. **Its owner should confirm before it ships.**
- Verification owed: unknown to me — ask the owner.

### 3. `syndicate/features/shared/game_shape.py` — `28cc8814` — `+69 −7`
- **What:** leverage wired into `game_shape`; "the refusal is lifted because the
  premise changed".
- **Risk: NOT assessed by me.** Another lane's work.
- Verification owed: unknown to me — ask the owner.

---

## Not queued, and why

- **Everything else in the 55 commits.** 34 of the 37 differing files are web-side
  or non-runtime (ledger, tests, scripts). Web already runs them.
- **`memory_observability.py`, `pipeline/intelligence_state.py`,
  `live_gameline_score.py`, `live_gameline_ledger.py`** — commits touched them,
  but their content is **already identical** on `8e3d2f95`. Listing them would
  have been a false queue built from commit subjects rather than content; one of
  those subjects is verbatim the live SHA's own.

## Standing caveat

Entries here go stale: `origin/main` moves constantly (seven sessions) and the
live SHA moves whenever anyone deploys. **Re-derive the diff at ship time** with
the command at the top of "Queued" — do not trust the SHAs above without
re-checking them against the then-current live commit.
