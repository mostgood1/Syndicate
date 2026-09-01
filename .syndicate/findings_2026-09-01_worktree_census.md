# Findings 2026-09-01 — Worktree census: 186 C:/tmp worktrees swept, 166 removed, 17 protected, 3 parked on the permission classifier

Lane `orphan-worktree-census`, session fbf1a34b. `[USER AUTHORIZATION
2026-09-01: "same treatment for the stale worktrees in C:/tmp".]` Third census
of the day, after the orphan sequencer and the 23-stash sweep.

## The fact that shaped the method

**Removing a worktree deletes NO commits and NO branches** — registrations and
working directories only. The only content ever at risk is uncommitted
modifications and untracked files, so the whole verification burden collapses
onto the dirty ones. The sweep proved additionally that **every one of the 186
worktree HEADs was reachable from a real ref** (`git rev-list --all`
membership, which excludes worktree HEADs themselves), so no removal could
orphan a commit even in principle.

## Sweep numbers

- 186 C:/tmp worktrees swept (status, HEAD ancestry vs origin/main,
  ref-reachability). 0 locked, 0 with missing directories.
- **Only 18 were dirty or carried untracked files.** Per-file verification of
  all 18: everything was runtime exhaust from the app having RUN in the
  worktree (`data/live/`, `memory_high_water.json`, quota counters, manifests,
  intelligence-state, backtest caches, vendor schedule churn) except:
  - `base_chk`: a draft of `_model_value_ev` — LANDED on main (7 hits).
  - `wt-deploy`: an 848-line 08-16 copy of `plan_2026-08-16_sim_scheduling.md`
    whose primary-tree version is a 1,040-line superset (also in main history).
- **166 removed** (155 clean + 11 verified-dirty). 23 remain, all accounted:

## Protected (17) — untouched by design

10 OPEN-lane worktrees (ncaaf-cfbd-quota-latch, ncaaf-games-cache-refresh,
ncaaf-no-orders, polymarket-yes-leg-binding, prop-rung-miss-rate,
soccer-board-mlb-parity, soccer-model-dispersion, soccer-overview-cost,
soccer-shot-shrinkage, wnba-live-odds-capture-gap); 6 active-session/task
worktrees (polymarket-prop-quote-capture, prop-unmatched-decomposition,
mlb-prop-freeze-source-trees, unknown-submit-retry-provenance,
gameline-snapshot-market-mix — the ENABLED nightly accuracy snapshot runs
there — and live-gameline-score-market-mix); plus mlb-prop-calibration-refit
(lane closed only TODAY; session may resume).

## Parked (3) — verified but NOT removed

`nfl-fantasy-projections`, `wnba-halftime-elapsed`, `wnba-live-props-data` —
each carries only untracked `data/live/`-class runtime output (verified), all
lanes long-archived, but the permission classifier refused their force-removal
repeatedly. Left standing rather than worked around. One
`git worktree remove --force <path>` each, by a human, finishes the job.

## Born mid-census (3) — evidence the machine is alive

`mlb-hrr-null-closed`, `mlb-position-substitution-on`,
`prop-name-disambiguator-derivation` appeared during the sweep, created by the
live sessions. Not in the census scope; not touched.

## Also cleaned / also noted

- **39 headless admin husks** under `.git/worktrees/` (no HEAD file, no
  registration — debris of worktrees deleted outside git going back weeks,
  incl. `boot-sync-healthcheck-kill`, four `w488_*`, three `wtal_*`) deleted;
  `git worktree prune` now runs clean and admin-dir count equals live count.
- **OneDrive wrinkle, now a known recipe:** `git worktree remove` on this repo
  reliably deletes the WORKING directory and unregisters, then fails with
  "Permission denied" deleting `.git/worktrees/<name>` (OneDrive handle). The
  removal is functionally complete at that point; a follow-up
  `rm -rf .git/worktrees/<name>` finishes it. Same handle class as the
  sequencer `--quit` exit-128 earlier today.
- **`C:/tmp/t5/` residue is NOT worktree content** — a tier5-live-read
  (08-14/15) scratch dump: probe scripts, JSON snapshots, and draft ledger
  fragments. The drafts were checked: the CADENCE learning and the
  nfl-live-edge-suppression lane both LANDED (learnings_archive.md,
  lanes_closed_archive.md). Out of scope, zero unlanded value; left in place.
- Out of scope (not C:/tmp): 2 worktrees inside other sessions' scratchpads,
  `Syndicate-mlb-sim-log5`, and the three `Syndicate-recover-*` recovery-branch
  worktrees. The recover ones are the June-stash content owners — leave them.

**Net: C:/tmp worktrees 186 → 23, every removal content-verified first, zero
recoveries needed (unlike the stash census, the worktrees held no unlanded
artifacts), zero commits orphaned.**
