# Session isolation — one worktree per session, and deploys that compose

**Status: ADOPTED** `[2026-08-18, user decision: "adopt the worktree flow for all
sessions"]`. `CLAUDE.md` → "Before touching code" now requires it. Written by
lane `football-model-owner`; tooling is `scripts/session_worktree.py`.

**Read "Migration" before opening a worktree.** Adoption does NOT carry the
primary tree's uncommitted work with it, and at adoption there were **48
modified tracked files and 104 untracked paths** in there, including real code
from at least two lanes. Opening a fresh worktree and carrying on strands all of
it in a tree everyone has just agreed to stop looking at. Land your files first;
`session_worktree.py adopt --lane <slug>` tells you which are yours.

---

## The problem, stated precisely

There are two contention problems and they are constantly mistaken for one.

**Deploys contend with deploys.** Two sessions deploying one service minutes
apart. This is *solved*: `scripts/deploy_claim.py` is a per-service mutex
(`O_CREAT|O_EXCL`, 45-minute expiry so a dead holder frees itself, `--force` to
break one), and since 2026-08-18 `deploy-guard.py` enforces it plus a fresh
preflight. It works.

**Commits contend with commits.** Every session shares one working tree and one
git index. `git add` is a global mutation. This is *not* solved, and it is the
root of a family of incidents:

| date | what happened |
|---|---|
| 2026-08-14/15 | 4,993 staged deletions sat in the shared index while the working tree matched HEAD. A bare `git commit` from **any** session would have un-shipped six files of `ask_the_syndicate` M1 work without touching one file on disk. |
| same night | the same index staged the deletion of the **only** copy of the pre-collapse ledger, plus truncations of two more files. Caught by inspection, not by a guard. |
| 2026-08-18 | a working copy of `todo.md` would have dropped five open items (`#448`, `#449`, `#454`, `#455`, `#456`) to zero copies — one of them an active OOM crash loop. Caught by a diff run only because something *else* looked odd. |

Every one is the same bug: **two sessions, one index.** `commit-guard.py`, the
blob-staging recipes, and the rule "never chain `add` and `commit`" are all
compensation for it. They are good compensation. They are not a fix, and each
one is a rule a context-pressured session has to remember.

The tell that nobody reads as a symptom: **there are ~100 stale worktrees under
`C:/tmp`.** Sessions already reach for isolation constantly. It is just ad hoc,
per-push, and never cleaned up.

---

## The change

**Git already solved this.** Each worktree gets its own index at
`.git/worktrees/<name>/index` — verified, and demonstrated by the prototype:
staging a file in a session worktree leaves the primary tree's index empty.

```bash
python scripts/session_worktree.py open  --lane <slug>    # your own tree + index
python scripts/session_worktree.py list                   # who has what
python scripts/session_worktree.py land  --lane <slug>    # rebase onto main, push
python scripts/session_worktree.py close --lane <slug>    # clean up
```

With this, `git add -A` is safe. Cross-session staging accidents become
structurally impossible rather than caught by review. `commit-guard.py` becomes
belt-and-braces instead of the only thing between a tidy and a silent revert.

### The cost is smaller than it looks, and one part of it is a benefit

Worktrees **share the object store** — the 1.83 GiB pack is not copied. The
per-worktree cost is the checkout alone.

And **34,690 of 37,745 tracked files (92%) are under `data/`**, which `CLAUDE.md`
itself calls a cold-start safety net and "a lossy mirror", explicitly not what
production computed. So the default excludes it, via sparse-checkout:

```
files on disk    3,055   (34,690 skipped -- data/ excluded)
```

That is not only a size trick. It removes, structurally, the error this repo
keeps making: drawing a conclusion about production from a local `data/` tree of
unknown vintage. A session that genuinely needs the mirror passes `--with-data`
and thereby says so out loud.

---

## The second half: deploys that compose

Isolation fixes commits. It does **not** fix the deploy failure, which is a
different thing wearing the same clothes.

Services run **deploy branches cut from live SHAs, not from `main`**. So two
deploys do not compose. Measured 2026-08-15: a verified refresh-worker fix went
live at 21:36:59Z and was gone by 21:45:20Z, because a peer cut their branch
from an earlier live SHA. Two "successful" deploys, one silently undone, nothing
warned. The claim did its job — the deploys were correctly serialized. They were
serialized and still destroyed each other, because **ordering is not the same as
composing.**

Cutting from the live SHA feels safer because `main` is not trusted. The cost of
that instinct is measured and it is a lost shipped fix.

**DECIDED AND ENFORCED** `[2026-08-18, user decision: "deploy from main"]`.
Deploy a SHA contained in `origin/main`, never a branch cut from a live SHA.
The later deploy then contains the earlier one by construction, and the claim's
serialization becomes sufficient.

`deploy_preflight.py` returns **`OFF_MAIN` (exit 4)** for a target commit that is
not an ancestor of `origin/main`, and `deploy-guard.py` blocks on it like any
other non-CLEAR verdict. Escape hatch: `--allow-off-main`, recorded in
`deploys.md`.

Two details that make the check real rather than decorative:

- **The receipt is bound to its SHA.** A `CLEAR` taken for one commit no longer
  authorises a deploy of any other for the next 15 minutes — otherwise the
  OFF_MAIN verdict would be trivially sidestepped by preflighting a main commit
  and deploying something else. Abbreviated and full SHAs compare by prefix.
- **A stale fetch reads as off-main, not on-main.** `origin/main` is read from
  the local repo, so "git could not say" lands on the blocking branch with
  `git fetch origin` named in the reason. An unknown must not default permissive.

This trades "ship only my change" for "ship everything on main", and that is a
real cost — it is the reason cutting from the live SHA felt safer. The trade was
taken because the alternative has already cost a verified fix in production.

---

## What this does NOT solve, stated plainly

**Ledger conflicts get more frequent, not less.** `lanes.md`, `state.md`,
`learnings.md` and `todo.md` are append-heavy and edited by everyone. Today one
session's write silently wins because they share a tree. Under isolation those
become real merge conflicts at `land` time.

That is the *right* outcome — a conflict is a collision you can see — but it is
more work per landing, and pretending otherwise would be dishonest.

**Do NOT reach for `merge=union` to make those conflicts disappear.**
`learnings.md`, 2026-08-18: *a union merge CANNOT carry a deliberate deletion; a
collapse pushed through one is undone, and comes back bigger.* Union merge on
these files would silently resurrect every block a collapse removed. It is the
obvious fix and it is forbidden.

**It does not fix the ledgers themselves.** They are already incoherent —
7 slugs with multiple OPEN blocks, 3 lanes both open and filed, 6 duplicated
todo ids. Isolation stops *new* damage from being invisible; it repairs nothing.
`scripts/lane_identity_check.py` and `scripts/todo_id_reconcile.py` measure it.

**`land` reports the checkers, it does not gate on them.** Both exit non-zero on
the repo today. Gating would block every session on day one over damage they did
not cause, and a gate that blocks all work is removed the same afternoon.

---

## Migration

**The order matters. Step 1 is not optional and is not a formality.**

1. **LAND YOUR EXISTING WORK FROM THE PRIMARY TREE FIRST.**

       python scripts/session_worktree.py adopt --lane <slug>

   Measured at adoption: **48 modified tracked files, 104 untracked** in the
   primary tree, including NHL hockeysim code (`loaders.py`, `projection.py`,
   `test_hockeysim_loaders.py`), `artifact_publisher.py`, and the MLB/NBA/WNBA
   vendor trees. A fresh worktree does not carry any of it.

   `adopt` matches dirty paths against your lane's `Files:` claims using
   `lane-guard.py`'s own parser, so it hands you the same list the guard
   enforces. **It has two blind spots and says so on every run:** it cannot see
   UNTRACKED files (a new file your lane never declared cannot be matched to
   you), and it cannot see work your lane never claimed. Running it on
   `nhl-model-owner` at adoption returned **1 of that lane's ~4 dirty files**,
   because the lane declared its docs and checklist but never declared the
   hockeysim internals it was editing. Read `git status --porcelain` yourself
   before concluding you are done.

2. **Then open your worktree.** `session_worktree.py open --lane <slug>`.
   New lanes skip step 1 — they have nothing stranded.

3. **The primary tree becomes reference/read-only by convention** once lanes
   have moved. It stays the convenient place to READ the ledger, and
   `.syndicate/` edits are least painful there while several sessions append.

4. **Reap the ~100 stale worktrees under `C:/tmp`.** Some may still be in use;
   `session_worktree.py list` shows only `session/*` ones, so legacy ones need a
   human pass. Do not bulk-delete — at least one holds a named deploy branch.

5. **Keep `commit-guard.py`.** Isolation makes cross-session staging impossible
   only for sessions that actually moved; until the primary tree is clean and
   quiet, it is still the thing standing between a tidy and a silent revert.

**What adoption does not make safe.** A worktree isolates the INDEX, not the
ledger. `.syndicate/*` and `docs/ai_context/todo.md` are still one shared
sequence of appends, and per-session copies turn today's silent last-writer-wins
into merge conflicts at `land` time. That is the better failure, not the absent
one. `merge=union` remains FORBIDDEN as a way to make it quiet.

## Open questions for the user

- Deploy from `main` (composing) vs. from live SHAs (isolated)? This is the real
  decision in this document.
- Should `land` eventually gate on the ledger checkers once the current damage
  is repaired?
- Where should session worktrees live? Default is `C:/tmp/syndicate-sessions`,
  overridable with `SYNDICATE_SESSION_ROOT`. `C:/tmp` is not durable across
  reboots, which is a feature for scratch and a hazard for unlanded commits —
  `close` refuses to discard unlanded work, but a wiped `C:/tmp` will not ask.
