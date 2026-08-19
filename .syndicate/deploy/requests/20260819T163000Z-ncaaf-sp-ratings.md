# Deploy request — NCAAF SP+ ratings + as-of PPA leak fix (refresh-worker)

    service:   refresh-worker (srv-d91dpertqb8s73co8ls0)
    sha:       f2eb719d  (branch deploy/ncaaf-sp-ratings-20260819b)
               REBUILT and READY. Parented on 23e70a80, the SHA live as of
               2026-08-19T16:52:58Z. Both blobs byte-identical to origin/main.
               Verify it is still the live SHA before firing -- see below.
    reason:    NCAAF margins are uncalibrated in production. Measured on the
               2026 wk1 slate: margin SD 1.74 vs a market 14.46, max margin 7.80
               vs 49.50. The model prices every college game as a coin flip.
    verify:    the SERVED board, two stages -- see verify: below.
    urgency:   NCAAF opens 2026-08-29. Not an outage; the board currently serves
               0 of 51 projections either way.

---

## Status: PENDING BY USER DECISION, 2026-08-19 ~17:4xZ

**Built, pushed, verified. Not deployed. Left pending deliberately.**

Blocked on the deploy CLAIM, which `nfl-player-props-backtest` acquired ~1 min
before I tried. I attempted `--force` (user-directed) and the permission
classifier denied it — correctly, since that session is live and had just taken
the lock. Not worked around.

**REFRESH-WORKER IS A CONTENDED SERVICE RIGHT NOW.** Three sessions wanted it
within the hour: `basketball-model-owner` (deployed `23e70a80` at 16:52:58Z),
`nfl-player-props-backtest` (holds the claim), and this lane.

**THE FIRST GRAFT WAS ALREADY INVALIDATED ONCE.** `d2277e63` was parented on
`6631748c`; basketball's deploy replaced that mid-wait, which would have made my
deploy REVERT theirs. Rebuilt as `f2eb719d` on `23e70a80`. **The same can happen
again** — see the precondition below.

### PRECONDITION before firing f2eb719d

    py -3 scripts/deploy_preflight.py --service refresh-worker --holder <lane>

Confirm the live SHA is still **`23e70a80`**. If it has moved, `f2eb719d` is
stale and reverts whoever deployed after it — REBUILD using the recipe below
against the new live SHA. Serialisation is not composition; the claim orders
deploys, it cannot make them cumulative.

---

## The rebuild recipe (only if the live SHA has moved)

```bash
LIVE=$(  # the CURRENT live refresh-worker SHA -- read it, do not assume 23e70a80
  py -3 scripts/deploy_preflight.py --service refresh-worker --holder <lane> \n    | grep -oE 'live commit +[0-9a-f]+' | awk '{print $3}' )
export GIT_INDEX_FILE=C:/tmp/syndicate-ncaaf-deploy.index
rm -f "$GIT_INDEX_FILE"
git read-tree $LIVE
for f in scripts/generate_smartsim2_ncaaf_projections.py \
         syndicate/features/ncaaf/cfbd.py; do
  git update-index --cacheinfo 100644,$(git rev-parse origin/main:$f),$f
done
TREE=$(git write-tree)
git diff-tree -r --name-only $LIVE $TREE      # MUST list exactly those 2 files
```

Then `commit-tree -p $LIVE`, push to a `deploy/` branch, and deploy that SHA.

**Assert before deploying:** each blob identical to `origin/main`'s, and the
diff-tree lists exactly two paths.

## What ships, and what is deliberately excluded

| file | why |
|---|---|
| `generate_smartsim2_ncaaf_projections.py` | SP+ replaces PPA as the rating source (margin SD 1.74 -> 15.37 against market 14.46; max 7.80 -> 50.64 against 49.50). Also the as-of PPA leak fix: r 0.663 -> 0.509, removing 30% inflation of apparent skill. |
| `syndicate/features/ncaaf/cfbd.py` | `.env` fallback in `CfbdClient.from_env`. **Five of seven NCAAF snapshot builders cannot run at all without it.** |

**EXCLUDED ON PURPOSE:** `play_simulator.py` and `calibration_profile.py`. Their
yardage-weight refactor is a no-op at defaults and NCAAF never overrides those
fields — verified, **0 references in the generator and 0 in the NCAAF profile**.
Excluding them also avoids grafting `964c89a4` (another lane's versioned-profile
seam), which is on `origin/main` but NOT in the live blob.

**Live SHA is NOT an ancestor of `origin/main`** — confirmed. This is why it is a
scoped graft and not a `main` deploy.

---

## verify: — TWO STAGES, and stage 1 alone proves nothing

**Stage 1, immediate — did the code land?** By CONTENT, never by deploy status:

```bash
git show <new-live-sha>:scripts/generate_smartsim2_ncaaf_projections.py | grep -c load_sp_ratings
git show <new-live-sha>:syndicate/features/ncaaf/cfbd.py | grep -c load_dotenv
```

Both must be non-zero.

**Stage 2, up to 24h — did it actually do anything?** The deploy does NOT produce
projections. The worker's season-projection autorun is on an 86400s timer and has
not fired since `CFBD_API_KEY` landed at 2026-08-18 21:43Z.

```bash
curl -s "https://syndicate-an21.onrender.com/ncaaf/api/cards?week=1" | python -c "import json,sys; d=json.load(sys.stdin); g=d['games']; print(sum(1 for x in g if x['predictions']['home_mean'] is not None),'of',len(g)); print(d.get('board_row_counts'))"
```

**PASS = ~51 of 51** carrying a non-null `predictions.home_mean`, with
`rating_source` on the artifact reading `cfbd_sp_plus_2026[scale=10]`.
**`16 of 16` is impossible** — the board cap fix is already live.

---

## KNOWN-WRONG AND SHIPPING ANYWAY — state this, do not let it be discovered

**Totals will serve at 1.67x market dispersion** (model SD 5.77 vs market 3.46).
Margins are calibrated; totals are not. The carrier is identified —
`total = drives x score% x pts/score`, and score% swings **20.8% -> 53.9%**
against a real ~35-45% while drives barely move — but the fix is in
`drive_simulator`'s conversion loop, which is **shared with NFL** and needs its
own NFL-impact measurement.

**Three scalar fixes are DEAD and must not be retried:** the index clamp (made
margins AND totals worse), the yardage weight asymmetry (parity was worst), and
the `scoring_environment` asymmetry (a 3x reduction moved total SD 0.07 points).
Evidence in `.syndicate/log/2026-08-19.md`.

**Rollback:** deploy **`23e70a80`** on refresh-worker — the SHA live before
this change, and the parent of `f2eb719d`. NCAAF returns to PPA ratings and the
leaked as-of path. (If the live SHA has moved on since, roll back to whatever
`f2eb719d`'s parent actually is: `git rev-parse f2eb719d^`.)
