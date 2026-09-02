# Findings 2026-09-01 — Branch census: 193 local + 257 origin/deploy branches cleared, every deleted tip preserved under archive refs

Lane `orphan-branch-census`, session fbf1a34b. `[USER AUTHORIZATION 2026-09-01:
"same treatment for the stale session and deploy branches".]` Fourth census of
the day (sequencer → stashes → worktrees → branches).

## The design decision that made 450 deletions safe

Branch deletion is the one operation in this series that CAN orphan commits.
Tier verification began the usual way — 152 of 445 swept refs were plain
ancestors of origin/main (TIER1); the other 293 were divergent tips — but the
first blob-level checks showed the honest truth about divergent deploy tips:
their exact blobs often never landed because main EVOLVED past them (the
`refresh_nba_oddsapi_props.py` / `wnba/cards.py` samples). Proving semantic
subsumption 248 times over would have been days of judgment calls with real
false-landed risk in the dangerous direction.

So the clearance was made **lossless by construction instead of by proof**:
every deleted tip first received a ref under
`refs/archive/branch-census-2026-09-01/{local,remote}/<branch-name>` — same
SHAs, permanently reachable (gc-proof), invisible to `git branch`, and
restorable with one command:

    git update-ref refs/heads/<name> refs/archive/branch-census-2026-09-01/local/<name>

Coverage was verified name-by-name (comm against both candidate lists: 0
uncovered) BEFORE any deletion. This is a STRONGER guarantee than the stash
census had (odb-until-gc); the cost is that the objects stay in the repo
deliberately.

## What was cleared

- **Local: 193 of 215 `session/*` + `deploy/*` branches deleted.** The 22
  kept are exactly the protected set: every branch checked out in a surviving
  worktree (the OPEN-lane + active-session set from the worktree census) —
  the only OPEN-lane branch existing outside those was already among them.
- **Remote: all 257 `origin/deploy/*` branches deleted; `ls-remote` now
  returns ZERO.** The deploy-branch era (the 08-15 "serialisation is not
  composition" incident class, `autoDeploy=no` + deploy-from-main since
  08-18) is now fully retired from origin. Remote-tracking refs pruned to 0.
- Born mid-census by a live session and left alone: `session/mlb-202-edge-scan`
  (same pattern as the worktree census's three mid-census births).

## Out of scope, noted for a future pass

Local: `backup/*` (4), `claude/*` (3), `dep-*` strays (dep-rw, dep-tn-low,
dep-tn-rw, dep2-low, dep2-rw, ...), `fix/soccer-backtest-leakage`,
`mlb-sim-log5-investigation` (worktree outside C:/tmp), `wnba-only-daily-update`.
Remote: `claude/*` (27), `safety/*` (3), `hotfix/*` (2), `fix/*` (2), `wip`,
`staging`, `wnba-only-daily-update`. **`recover/stash-*` (3) are deliberately
NOT stale** — they own the June copilot-stash content (see the stash census).

## Numbers

| set | swept | deleted | kept | preservation |
|---|---|---|---|---|
| local session/* + deploy/* | 215 (+1 born mid-census) | 193 | 22 protected + 1 new | archive refs, coverage comm=0 |
| origin/deploy/* | 257 | 257 | 0 | archive refs (tips fetched locally first) |
| tiers | 152 TIER1-ancestor / 293 divergent | — | — | archive refs made per-tip proof unnecessary |
