# Recovered 2026-09-10: code that existed only on this machine, kept INERT

`[lane census-rescue-0910, from the 2026-09-10 open-work census]`

Nothing in this file runs. Each item is here because its only copy was an
untracked file or an uncommitted worktree. Each is kept out of its live path for
the reason given. Landing any of them is a decision for its owner, not a side
effect of this rescue.

## 1. `.github/workflows/mlb-season-artifacts.yml` — never committed

Drafted 2026-09-07 to close `findings_2026-09-07_mlb_season_artifacts_frozen.md`:
five MLB season artifacts have not been rebuilt since 2026-08-18, and nothing
schedules their builders. Its own header records two user decisions: GitHub
Actions rather than a Render cron, and `pybaseball` kept out of
`requirements.txt`.

**Why it is NOT committed to `.github/workflows/`.** Committed there, it becomes
a scheduled job that PUBLISHES to production the moment Actions billing is
restored (billing has been locked since 2026-08-22). The findings file also names
a load-bearing step that nobody has verified: whether the arsenal builder's
`.venv_x64` interpreter workaround applies on a GitHub x64 runner.

To enable it:
1. Copy the block below to `.github/workflows/mlb-season-artifacts.yml`.
2. Add the secrets it names.
3. Run it once by `workflow_dispatch` before trusting the schedule.

```yaml
name: MLB season artifacts

# Rebuild the MLB season-scoped sim inputs and publish them to production.
#
# WHY THIS JOB EXISTS. Measured 2026-09-07: `arsenal`, `quality`, `batted_ball`,
# `pitch_splits` and `conditional_mix` all carried an embedded `generated_at` of
# 2026-08-17/18 while their disk mtimes refreshed daily -- `pull_season_artifacts()`
# copies each file from web onto the worker before every sim run, which touches
# the file and regenerates nothing. Three weeks of stale contents behind a fresh
# mtime. Nothing on any schedule rebuilt them: all five builders were written in
# one session on 2026-08-17 and each has exactly ONE commit in its whole history.
# The pitch-splits builder's own docstring called it at creation -- "remains open:
# a scheduled populator on the worker" -- and nobody closed it.
#
# WHY GITHUB ACTIONS AND NOT A RENDER CRON `[2026-09-07, user decision]`.
# The first reason offered for a Render cron was wrong and is corrected here so
# nobody re-derives it: a cron job would NOT get `SYNDICATE_DATA_ROOT` mounted.
# Render gives each service its own volume (`syndicate-data-web`,
# `syndicate-data-refresh-worker`, `syndicate-data-live-odds-worker`), so nothing
# that is not refresh-worker can write refresh-worker's disk. Either host has to
# publish over HTTP, so the disk was never an advantage. What remains is blast
# radius: a `render.yaml` push fires `blueprint_sync`, which rewrites the WHOLE
# env block of all three services and 502'd every route for ~2 minutes on
# 2026-08-08. This job needs no config push at all.
#
# WHY NOT refresh-worker's own tick: it is network-bound scrape work on the 4GB
# service with a documented OOM history, and `#241` caused a production restart
# loop doing exactly that.
#
# `pybaseball` is installed HERE and deliberately NOT added to `requirements.txt`
# `[2026-09-07, user decision]`: it would otherwise land in all three service
# images, including web's 2GB container, which has an open memory investigation.
#
# THIS JOB DOES NOT COMMIT ANYTHING. The `data/` tree in git is a lossy cold-start
# mirror, and the Daily Update workflow's own header records what happens when a
# job starts pushing it: ~370 files / ~51MB to `main`, daily, that nobody reads.
# Artifacts reach production over the API and nowhere else.

on:
  schedule:
    # Weekly, Mondays 09:00 UTC. Season aggregates move slowly -- the existing
    # in-repo statcast refresh uses a 7-day staleness default for the same
    # reason. 09:00Z is well clear of the MLB slate.
    - cron: '0 9 * * 1'
  workflow_dispatch:
    inputs:
      season:
        description: 'Season to build (defaults to the current UTC year)'
        required: false
        type: string
      dry_run:
        description: 'Build only -- do not publish to production'
        required: false
        type: boolean
        default: false

# No `contents: write`: this job pushes nothing to the repo, so it should not be
# able to. The Daily Update job needs that scope; this one must not inherit it.
permissions:
  contents: read

concurrency:
  group: mlb-season-artifacts
  cancel-in-progress: false

jobs:
  build-and-publish:
    runs-on: ubuntu-latest
    timeout-minutes: 30
    steps:
      - name: Check out repository
        uses: actions/checkout@v4
        with:
          persist-credentials: false

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install dependencies
        # `pybaseball` is the Statcast client the three builders import. The
        # repo's own usage lines name a `vendor/mlb_bettingv2/.venv_x64`
        # interpreter, which is a WINDOWS-ARM64 workaround for pybaseball's
        # native wheels -- it does not apply on this x64 Linux runner, which is
        # part of why the job lives here.
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt
          pip install pybaseball

      - name: Rebuild and publish MLB season artifacts
        env:
          ADMIN_TOKEN: ${{ secrets.ADMIN_TOKEN }}
          SYNDICATE_BASE_URL: ${{ secrets.SYNDICATE_BASE_URL }}
        run: |
          if [ -z "$ADMIN_TOKEN" ]; then
            echo "ADMIN_TOKEN secret is not set. Without it the publish would"
            echo "401 and this job would look like a success having shipped"
            echo "nothing -- which is the exact silent no-op it exists to end."
            exit 1
          fi
          SEASON="${{ github.event.inputs.season }}"
          if [ -z "$SEASON" ]; then SEASON="$(date -u +%Y)"; fi
          FLAGS="--publish --verify"
          if [ "${{ github.event.inputs.dry_run }}" = "true" ]; then FLAGS=""; fi
          echo "season=$SEASON flags=$FLAGS"
          python scripts/publish_mlb_season_artifacts.py --season "$SEASON" $FLAGS

      # The step above already fails on: a builder returning non-zero, an
      # artifact whose `generated_at` did NOT move (a build that produced
      # nothing is not a success), a publish that did not return OK, and a
      # read-back whose `generated_at` does not match what was just built.
      # Those checks live in the script rather than here so a local run is
      # gated identically to CI.
```

## 2. `scripts/merge_odds_history_artifact.py` — never committed, referenced by nothing

This is an out-of-process merge for published `odds_history` artifacts
(`#630`), written so web's gunicorn workers stop ratcheting memory on JSON
unions. No caller exists on `origin/main`, so committing it to `scripts/` would
add dead code. It is preserved here instead for whoever picks up `#630`.

```python
"""Merge one published `odds_history` artifact, OUT OF PROCESS. `#630`.

WHY A SUBPROCESS RATHER THAN A THREAD. The JSON union holds two parsed
documents: measured 276 MB peak on 88 MB of input (3.13x) on the real MLB
shard. Run inside gunicorn on web -- a 2Gi service -- that RATCHETED the memory
floor from 717.7 MB at boot to ~1030 MB once merges started, and it did not come
back, because CPython does not return freed arenas to the OS. A background
thread would not have helped: same process, same arenas.

A child process gives the whole address space back on exit, so the gunicorn
worker's RSS never grows. It also restores `CLAUDE.md`'s rule that the web
service does no heavy computation.

The parent writes the incoming body to a staging file and spawns this; it does
NOT wait. If this never runs, the target keeps the copy it already had -- stale
by one publish, which is the pre-merge behaviour and not a clobber.

THIS DELETES ITS OWN STAGING FILE, including on refusal. A staging file left
behind is disk that nothing will ever reclaim.

Usage:
    py -3 scripts/merge_odds_history_artifact.py --target T --incoming S
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.shared.artifact_merge import merge_odds_history  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--target", required=True)
    ap.add_argument("--incoming", required=True)
    ap.add_argument("--relative-path", default="")
    ap.add_argument("--lock-wait-seconds", type=float, default=180.0)
    args = ap.parse_args()

    target = Path(args.target)
    incoming = Path(args.incoming)
    try:
        if not target.is_file():
            # Nothing to merge INTO. The parent only stages when the target
            # exists, so this means it vanished underneath us -- promote the
            # staged copy rather than dropping it on the floor.
            if incoming.is_file():
                incoming.replace(target)
                result = {"merged": False, "error": "target_absent: promoted staged copy"}
            else:
                result = {"merged": False, "error": "target_absent_and_staging_absent"}
        elif not incoming.is_file():
            result = {"merged": False, "error": "staging_absent"}
        else:
            result = merge_odds_history(target, incoming,
                                        lock_wait_seconds=args.lock_wait_seconds)
    except Exception as exc:  # never let a crash strand the staging file
        result = {"merged": False, "error": f"{type(exc).__name__}: {exc}"}
    finally:
        # A REFUSAL IS NOT A REASON TO DISCARD THE PUBLISH. If the merge could
        # not run, PROMOTE the staged copy -- that is the plain replace, i.e.
        # the pre-merge behaviour -- rather than dropping the data on the floor.
        # The first version unlinked unconditionally, which turned every
        # `merge_busy` into silent data loss.
        try:
            if incoming.is_file():
                if result.get("merged") or result.get("do_not_promote"):
                    # merged -> staging is spent.
                    # do_not_promote -> the staged copy is NOT VALID JSON, and
                    # promoting it would replace a good artifact with garbage.
                    # Dropping this publish is correct: the publisher sends its
                    # whole file again next cycle.
                    incoming.unlink(missing_ok=True)
                else:
                    incoming.replace(target)
                    result = dict(result)
                    result["promoted_staged_copy"] = True
        except Exception:
            try:
                incoming.unlink(missing_ok=True)
            except Exception:
                pass

    payload = dict(result)
    if args.relative_path:
        payload["path"] = args.relative_path
    try:
        payload["bytes"] = target.stat().st_size
    except Exception:
        pass
    # The parent is not waiting, so this line IS the record.
    print(f"[artifact_merge] ODDS_HISTORY_MERGE {json.dumps(payload, sort_keys=True)}", flush=True)
    return 0 if result.get("merged") else 1


if __name__ == "__main__":
    sys.exit(main())
```

## 3. `mlb_bettingv2` log5 selective-combine experiment — see the `.patch`

`recovered_2026-09-10_mlb_sim_log5_vendor.patch` is `git diff -- vendor` from the
`Syndicate-mlb-sim-log5` worktree.

- **Source:** branch `mlb-sim-log5-investigation`, based on `5333f96c`
  (2026-07-19), 7,168 commits behind main when read.
- **Contents:** `pitch_model.py`'s `_log5_selective_keys` / `_use_log5_combine`,
  plus `simulate.py`, `build_roster.py`, a feature-set builder and four tuning
  JSONs.
- **Status:** it is two months stale against a vendored engine that has moved
  since, so it will not apply cleanly. It is kept as a record of the experiment.

## 4. `recover/stash-intelligence` WIP — pushed as a rescue branch, too large for here

This is 234 KB of formerly uncommitted work from the
`Syndicate-recover-intelligence` worktree, dating from June 2026:
- parlay fallback tests, `_freshness_label` and `_sample_mlb_overview`;
- 47 of its 97 added functions are not on main.

It was committed and pushed as `rescue/intelligence-wip-2026-06-05`
(`398f02f8`) on 2026-09-10, after the user approved. That worktree is no longer
its only copy. The work is probably superseded; it is kept so that deleting it
is someone's decision, not an accident. It is not for `main`.

## 5. DROPPED, with the reason: `ncaaf-chip-compact`'s "alias map must stay empty" guard

Its worktree held a note in `team_aliases.py` and a test,
`test_ncaaf_alias_map_stays_empty`. `origin/main` reversed that premise
deliberately on 2026-09-09 in `04a82c38` ("ncaaf: give the sport a team alias
map, derived from the registry it already has"), so landing the guard would
fight a later decision. `chip_join_key`, the part that mattered, is already on
main.

## 6. LANDED, not preserved: deploy tooling and the unknown-submit watcher

- **`--reinject-env` + the main-tree `.env` fallback** (`dd70296e` + `5b90fc3e`,
  from `session/web-access-log-emitter-dead`) were landed on main by this lane.
  The two uncommitted `--allow-redundant` copies (in the primary tree and in
  `render-egress-known-volume-join`) were drafts of the same idea. `deploys.md`
  records a production preflight run under that spelling; the landed flag is
  `--reinject-env`.
- **`scripts/watch_unknown_submit.ps1`** was committed as-is. It runs as the
  Windows scheduled task that replaced the disabled Claude task
  `unknown-submit-balance-evidence-capture`, and it was in no version control.
