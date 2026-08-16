# HANDOFF — deploy `bf643d72` (pregame freeze → the reader's tree) to both workers

**Prepared 2026-08-16 ~20:3xZ by lane `grading-blocker-settled-zero`, which is an
UNATTENDED scheduled-task session and therefore must not fire the deploy itself.**
`state.md` records an unattended task committing code, claiming three services and
deploying against its own instructions at 01:0x–01:2xZ today; the prescribed remedy
is a claim tool that refuses an unattended holder, and that control does not exist
yet. Execute this from an ATTENDED session.

The code is committed and tested. Everything below is mechanical.

---

## What is being deployed, and why it needs both workers

`_freeze_oddsapi_pregame_markets` wrote the pregame odds seal to
`source_root/data/market/oddsapi`. The grading builder
(`build_season_betting_cards_manifest._odds_paths`) resolves odds from
`MLB_BETTING_DATA_ROOT`, which is `.../mlb_source/source_artifacts/data` on all
three services. **One path segment apart.** So the builder graded against a
2026-07-08 seal or none, warned `Missing game-line match` for ~14 of 15 games, and
`ml` graded **exactly 1 row on all 8 dates measured**. That is the first link in
the chain that ends with `settled: 0` and `sim_component: 0.0` on the Layer 2 board.

The freeze runs inside `refresh_odds_sources.py`, which executes on **both**
workers (observed live on live-odds-worker at 19:32Z, and refresh-worker runs its
own). Deploying one leaves the other still writing to the wrong tree.

`bf643d72` — 419 tests pass; the 3 new tests verified non-vacuous against pre-fix
behaviour. Detail in lane `grading-blocker-settled-zero` in `lanes.md`.

---

## Constants

    refresh-worker     srv-d91dpertqb8s73co8ls0
    live-odds-worker   srv-d91dpertqb8s73co8lt0

    commit             bf643d72
    base it was cut on af7e864d
    blob scripts/refresh_mlb_oddsapi.py        426bbd7056499843dfe5d42990962ca6235c01ff
    blob tests/test_oddsapi_pregame_freeze.py  b624f372666cdefca39d3703e106a3df044c734a

`RENDER_API_KEY` and `ADMIN_TOKEN` are in `.env`.

---

## STEP 0 — the check that decides whether any of this is safe

The deploy branch grafts **two blobs** onto the service's live SHA. That silently
reverts anyone else's edits to those two files if there are any. Re-run this at
execution time — it was empty at 20:3xZ but that is a lease, not a fact:

```bash
git fetch origin && git log --oneline af7e864d..origin/main -- scripts/refresh_mlb_oddsapi.py tests/test_oddsapi_pregame_freeze.py
```

**Empty → proceed. Non-empty → STOP** and merge properly instead of grafting;
someone else changed the same files and this recipe would revert them.

---

## STEP 1 — wait for a real lull, then claim BOTH

Both workers must be unclaimed **and** job-free. An expired claim with jobs still
running is not a lull — live-odds-worker had 3 jobs in flight at 19:32Z including
`refresh_odds_sources.py`, the very path this fix lives in.

```bash
py -3 scripts/deploy_claim.py status
```

```bash
py -3 scripts/deploy_preflight.py --service refresh-worker --holder <your-lane>
```

```bash
py -3 scripts/deploy_preflight.py --service live-odds-worker --holder <your-lane>
```

Do **not** trust `CLEAR` alone — `learnings.md:1112` is a FORBIDDEN entry recording
a CLEAR returned while three jobs were running. Read the process list in the output.

Then take both, so nobody lands between your two services:

```bash
py -3 scripts/deploy_claim.py acquire --service refresh-worker --holder <your-lane>
```

```bash
py -3 scripts/deploy_claim.py acquire --service live-odds-worker --holder <your-lane>
```

---

## STEP 2 — build the deploy branch WITHOUT switching the shared worktree

Eight sessions share this checkout. `git checkout -b` would move all of them.
This uses plumbing and an isolated index, so the working tree is never touched.

Do this per service, cutting from **that service's own current live SHA**
(`learnings.md`: a branch cut for web has been a rollback for refresh-worker).
Cut at deploy time — `learnings.md:2532` forbids letting a branch sit behind a gate.

```bash
RW_LIVE=$(curl -s -H "Authorization: Bearer $RENDER_API_KEY" "https://api.render.com/v1/services/srv-d91dpertqb8s73co8ls0/deploys?limit=1" | python -c "import sys,json;print(json.load(sys.stdin)[0]['deploy']['commit']['id'])")
```

```bash
git fetch origin && echo "live=$RW_LIVE" && git cat-file -t "$RW_LIVE"
```

Build the commit (repeat with `$LW_LIVE` and a different branch name for
live-odds-worker):

```bash
export GIT_INDEX_FILE=C:/tmp/idx.deployfreeze && git read-tree "$RW_LIVE" && git update-index --cacheinfo 100644,426bbd7056499843dfe5d42990962ca6235c01ff,scripts/refresh_mlb_oddsapi.py && git update-index --cacheinfo 100644,b624f372666cdefca39d3703e106a3df044c734a,tests/test_oddsapi_pregame_freeze.py && git diff --cached --stat
```

That diff must show **exactly 2 files**. If it shows more, the live SHA predates
other work and you are about to revert it — stop.

```bash
export GIT_INDEX_FILE=C:/tmp/idx.deployfreeze && TREE=$(git write-tree) && NEW=$(git commit-tree "$TREE" -p "$RW_LIVE" -m "deploy: pregame freeze writes to the grading reader's tree (bf643d72 grafted onto $RW_LIVE)") && echo "NEW=$NEW" && git push origin "$NEW:refs/heads/deploy/freeze-reader-tree-rw"
```

---

## STEP 3 — ROUTE ONE: warm the mirror, then deploy

`POST /deploys` 404s with *"service does not have a commit"* for anything pushed
after that service's last build: **Render's git mirror is per-service and refreshes
only at build time.** Proven twice. So deploy the service's own live commit first
(a no-op in code) to force a fetch, wait for it to finish, then deploy the target.
**Two restarts per service. Fire the two steps BY HAND**, not from a watcher.

Warm-up:

```bash
curl -s -X POST -H "Authorization: Bearer $RENDER_API_KEY" -H "Content-Type: application/json" -d "{\"commitId\":\"$RW_LIVE\"}" "https://api.render.com/v1/services/srv-d91dpertqb8s73co8ls0/deploys"
```

Wait for `finishedAt` to be non-null before the next call — a deploy does not race
another deploy here, it **CANCELS** it (`learnings.md:2549`):

```bash
curl -s -H "Authorization: Bearer $RENDER_API_KEY" "https://api.render.com/v1/services/srv-d91dpertqb8s73co8ls0/deploys?limit=1" | python -c "import sys,json;d=json.load(sys.stdin)[0]['deploy'];print(d['commit']['id'][:8],d['status'],d.get('finishedAt'))"
```

Then the target (`$NEW` from step 2), and wait for `finishedAt` again. Repeat the
whole of steps 2–3 for live-odds-worker with `srv-d91dpertqb8s73co8lt0`.

---

## STEP 4 — verify BY CONTENT, never by ancestry

`learnings.md:2370` — FORBIDDEN: `git merge-base --is-ancestor` answers a question
about history; deployment is a question about content. Both workers run branch
`main` with `autoDeploy: no`, and the live SHA is routinely not an ancestor of main.

```bash
git fetch origin && for s in srv-d91dpertqb8s73co8ls0 srv-d91dpertqb8s73co8lt0; do SHA=$(curl -s -H "Authorization: Bearer $RENDER_API_KEY" "https://api.render.com/v1/services/$s/deploys?limit=1" | python -c "import sys,json;print(json.load(sys.stdin)[0]['deploy']['commit']['id'])"); echo -n "$s $SHA -> _freeze_market_dirs count "; git show "$SHA:scripts/refresh_mlb_oddsapi.py" | grep -c "_freeze_market_dirs"; done
```

Both must print **2** (the def plus its call site). `0` means the fix is not live
on that service regardless of what the SHA is.

Release the claims:

```bash
py -3 scripts/deploy_claim.py release --service refresh-worker --holder <your-lane>
```

---

## STEP 5 — the measurement, and why it is NOT tomorrow morning

**The fix is forward-only.** It seals future slates; it does not repair the already
collapsed freezes for 08-09..08-16. 08-16's freeze was already down to 8 games and
falling by 18:13Z, so **the scheduled check `grading-freeze-payload-check`
(2026-08-17 07:00 CT) reads date 08-16 and cannot show this fix.**

First measurable date is **08-17**, whose card builds ~04:40Z on **08-18**. Re-aim
that task: `update_scheduled_task`, `taskId: "grading-freeze-payload-check"`,
`fireAt` ~`2026-08-18T07:00:00-05:00`, and change the target date in its prompt
from 08-16 to 08-17.

**Predicate.** Freeze for 08-17 should hold ~the full slate and be monotonically
non-decreasing across passes; `ml` graded rows should go from the invariant **1**
to roughly slate size; `Missing game-line match` warnings should fall from 4–14
toward 0.

    /mlb/api/market-accuracy?date=2026-08-17   -> days[0].rows.all, count market=="ml"
    export pattern **/betting_day_payloads_retuned/season_betting_day_2026_08_17.json -> len(games)
    export pattern **/snapshots/2026-08-17/oddsapi_game_lines_2026_08_17_pregame.json -> len(games)

**Even a full PASS does not move `sim_component` off 0.0.** Graded rows are not
settled rows: the settlement autorun is off by user decision (`todo.md:13464`), so
`settled` stays 0 and `_SCORE_SIM_WEIGHT` stays gated until that is decided
separately.

---

## ROLLBACK

Redeploy each service's pre-deploy live SHA — the `$RW_LIVE` / `$LW_LIVE` you
captured in step 2, same `POST /deploys` call. Capture and write them down BEFORE
step 3; they are the only rollback target and they move constantly.

---

## Traps that actually fired today, so you do not rediscover them

- **Live SHAs move 5+ times an hour.** refresh-worker went `a72b4bf4` → `98a9cad8`
  inside the 6 minutes between one preflight and its execution. Re-read immediately
  before each call.
- **`06c5aa6e` was CANCELLED mid-build at 19:42:01Z** by another session's deploy.
  Hold both claims for the whole window.
- **`/api/ops/artifacts/export` is filtered by `HOT_ARTIFACT_PATTERNS`**
  (`ops.py:1342`) and runs on **web**, reading **web's** disk. It returns `count: 0`
  for trees it does not cover — including `market/oddsapi`. A zero from it is not
  absence, and it cannot see refresh-worker's disk at all.
- **`/api/ops/evaluation-settlement/status` serves a STORED file.** Its `epoch` read
  2026-08-06T11:03:17Z on 08-16 — ten days stale. Check `epoch` before quoting
  `settled` as current.
- **The commit-guard hook reads the SHARED index**, not your `GIT_INDEX_FILE`, so it
  false-positives on isolated-index commits — and its suggested `git restore --staged`
  has twice OMITTED a path it flagged. Verify `git diff --cached --stat` and
  `--diff-filter=D --name-only` yourself afterwards.
- **`.syndicate/lanes.md` is rewritten wholesale by other sessions.** A lane header
  written here was silently lost twice today. Re-read after writing.
