# Syndicate — multi-session coordination protocol

For running several Claude Code sessions against this repo without them
overwriting each other's documentation or deploying over each other's work.

**Design principle:** collisions are prevented **by construction**, not by
convention. Any rule of the form "sessions should remember to check X" fails the
first time a session is mid-task and context-pressured. Every mechanism below
makes the collision either impossible or immediately visible in git.

**The core rule:** *never two writers on one file.* Git merges concurrent
appends to **different** files without complaint. It conflicts on concurrent
rewrites of the **same** file. Almost every collision you are hitting is the
second case, and the fix is to stop having shared mutable documents.

---

## 0. Fix the root cause first

The ops kit has been committed locally at `74d38daa` since Aug 13 and never
pushed. Sessions running in separate worktrees on separate branches therefore
cannot see each other's `.syndicate/` at all — they are not colliding so much as
working blind and then discovering the divergence at merge time.

**Push it to the default branch before anything else here matters.** Nothing in
this protocol works while the coordination surface itself is unshared.

---

## 1. Lane claims — one file per lane

Replace any shared "who is working on what" document with a directory. Creating
a new file never conflicts; editing a shared list always can.

```
.syndicate/lanes/open/<lane-id>.md     # one per active lane
.syndicate/lanes/closed/<lane-id>.md   # git mv here when done
```

Each claim file, written once at lane start and not edited afterward:

```markdown
---
lane: board-ui-freshness-slip-books
opened: 2026-08-14T18:20:00Z
session: <short label the human can recognise>
branch: ui/freshness-slip
status: open
---

## Claims
- shared/layer1_board.html
- shared/layer1_board.py
- blueprints/intelligence.py

## Touches (read, may edit incidentally)
- static/shared/board_cards.css

## Deploy intent
none | prepare-only | requests-deploy: web

## Notes
One paragraph. What this lane is doing and what "done" looks like.
```

**Claims are globs against paths.** Two lanes may not claim overlapping globs.
`Touches` is advisory and does not block, but it tells the next session where to
look when something surprises them.

---

## 2. Documentation — append-only, one owner per file

The `.md` collisions come from several sessions rewriting the same living
documents.

**Rules:**

- A lane writes findings **only** to `.syndicate/lanes/open/<lane-id>.md` or to
  its own dated note (`.syndicate/audit_<date>_<topic>.md`). Those files have
  exactly one writer for their lifetime.
- `state.md`, `learnings.md`, `decisions.md` become **append-only**. Never
  rewrite, never reflow, never reorganise — append a dated entry at the end. Two
  appends to the end of a file usually merge cleanly; two rewrites never do.
- If a document genuinely needs restructuring, that is its own lane, claiming
  that file, with no other lane open against it.
- **Nothing is derived by hand.** If you want an index of open lanes, generate
  it (`ls .syndicate/lanes/open/`), do not maintain it.

**Why append-only rather than "coordinate carefully":** an agent asked to update
a summary document will helpfully reorganise it. That is the behaviour you want
in every other context and it is exactly what destroys a shared file.

---

## 3. Deploys — agents prepare, humans execute

This is the rule I would push hardest on. Three services, `autoDeploy = no`,
persistent disks, and a worker that is already OOMing means an agent that can
deploy unsupervised can take `live-odds-worker` down and leave it down — and
with several sessions, two agents can deploy different SHAs to the same service
minutes apart without either knowing.

**Default: no session deploys.** Sessions write a request; you execute it.

```
.syndicate/deploy/requests/<timestamp>-<lane-id>.md
```

```markdown
service: live-odds-worker
branch: memory/overview-sum-to-max
sha: 086702ae
reason: overview memory cutover; addresses end-of-slate OOM
verify: watch memory profile through end of slate; check whether OOM
        time-of-day moves rather than only whether it stops
rollback: previous deployed sha <fill in from preflight>
blast radius: worker only; no web impact expected
```

One file per request, so requests never conflict. You deploy in whatever order
you choose and move the file to `.syndicate/deploy/done/` with the result
appended.

**If you do want agent deploys**, then exactly one session holds the deploy role
at a time, declared in its lane claim as `deploy intent: requests-deploy:
<service>`, and no other lane may claim that service concurrently. But
prepare-only is safer and costs you about thirty seconds per deploy.

---

## 4. Session start and end protocol

Fold into the existing commands rather than adding new ones.

### `/lane` (extend)

At lane start, in order:

1. `git fetch && git pull` on the default branch
2. List `.syndicate/lanes/open/` and read every claim file
3. **Check the proposed claims against every open claim.** Overlap → stop and
   report, do not proceed
4. Print deployed SHA per service (see `/preflight` below) and note them in the
   claim file
5. Write the claim file, commit, **push immediately** — an unpushed claim is not
   a claim
6. Create the worktree and branch

### `/preflight` (extend)

- Print deployed SHA for **all three** services and the current worktree's HEAD,
  and state plainly when they differ. Deploy drift has affected four audits;
  every finding is scoped to a moving target until this is default output.
- Re-read open lane claims and warn if this lane's diff touches a file claimed
  by another lane.

### `/checkpoint` (extend)

- Append to the lane file, never rewrite it.
- Push. A checkpoint that only exists locally does not coordinate anything.

### `/close` (new, or fold into `/postmortem`)

- `git mv` the claim from `open/` to `closed/`, appending outcome and the SHA
  merged.
- Append one dated line to `learnings.md` if the lane produced a durable rule.
- Remove the worktree.

---

## 5. Worktree hygiene

`.claude/worktrees/` holds full repo copies, which has already caused a
timed-out `find` and triple-counted greps in Pass 1.

- Confirm `.claude/worktrees/` is in `.gitignore` **and** excluded from the
  Render build context. If those copies ship in the image they are dead weight,
  and worth ruling out as a contributor to the disk climb on
  `live-odds-worker`.
- Every audit or scan command must be scoped to the source tree explicitly. Put
  the exclusion in the engineer agent's standing notes, not in each prompt.
- One worktree per open lane. Remove it at `/close`. Stale worktrees are how the
  count grows until scans time out.

---

## 6. Concurrency cap

Worth saying plainly: coordination overhead is real, and this repo has 43 files
over 1,000 lines with 47% of its code in 25 files. Those large files are exactly
what several concurrent lanes will collide on, because almost any change lands
in one of them.

**Cap open lanes at three**, and pick them so their claims are far apart in the
file tree. Two lanes both touching `features/intelligence.py` (11,068 lines) will
merge-conflict regardless of any protocol here.

A reasonable concurrent set from the current program: one deploy/verify lane
(Tier 0), one measurement lane (Tier 1), one correctness lane (Tier 2). Those
three barely overlap. Adding a fourth on the probability substrate would collide
with the correctness lane immediately, since both land in
`recommendation_engine`.

---

## 7. What this does not solve

- **Concurrent edits to the same large source file.** No protocol fixes that;
  only claim discipline and the concurrency cap do.
- **Semantic conflicts** — two lanes each correct in isolation, wrong together.
  The claim file's `Notes` paragraph is the only defence, which is why it should
  say what "done" looks like rather than what the lane is called.
- **Sessions that ignore the protocol.** Put the start protocol in
  `.claude/agents/syndicate-engineer.md` so it is loaded by default rather than
  remembered.

---

## Implementation order

1. Push the ops kit (`74d38daa`)
2. Create `.syndicate/lanes/{open,closed}/` and write a claim file for every
   session currently in flight — including retroactively for
   `board-ui-freshness-slip-books`
3. Add the deployed-SHA output to `/preflight`
4. Extend `/lane` with the pull-read-check-write-push sequence
5. Switch `state.md` / `learnings.md` / `decisions.md` to append-only and say so
   in a header line at the top of each
6. Create `.syndicate/deploy/requests/` and route the two held branches
   (`9ec20a06`, `086702ae`) through it as the first two requests
