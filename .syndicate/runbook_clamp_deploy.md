# RUNBOOK — deploy the fair-price clamp fix when the watcher triggers

**Standing decision, given by the user 2026-08-15: deploy it when the watcher
triggers.** This file exists because the trigger is transient and the session
holding that instruction will probably be gone. Execute it from zero context.

**The deploy is authorised. `/preflight` is NOT waived** — it can fail at trigger
time for reasons that do not exist now (an in-flight sim, a concurrent deploy, a
memory state). Authorisation covers the action, not the safety check. If the gate
fails for a NEW reason, hold and report; do not push through it.

---

## 0. Precondition — do not start without this

A record with `"verdict": "PRE_FIX_MISPRICE"` in `reports/clamp_watch/`
(`observations.jsonl`, or a `trigger_*.json`).

- `no_trigger` is **not** a precondition — it is the instrument saying it cannot
  see, and it is stamped as not-evidence in every record.
- `TRIGGER_UNCONFIRMED` means the confirming read failed. Re-run
  `python scripts/watch_clamp_trigger.py --once` before doing anything.
- `POST_FIX_OK` means production is already correct. **Stop — nothing to deploy.**

**From the trigger record, write down the ROW IDENTITY**: `sport`, `market`,
`side`, `game`, `fair_probability`, and `published_fair_price`. Step 6 needs it.

---

## 1. What is being deployed

Commit `7bb74c95`, two code files only:

- `syndicate/features/shared/layer2_board.py` — `_american_from_probability`
- `pipeline/intelligence_state.py` — the inline copy in
  `_backfill_layer2_board_columns`

Both delegate to `opportunity_signals.american_price`. The WNBA third
(`de0c367f`) is **already live**.

**WEB SERVICE ONLY** (`srv-d88ahvrbc2fs73eodu30`). Measured 2026-08-15:
`fair_price` is stamped at SERVE time — 0 of 108 shortlist-artifact rows carry
it against 1800 served. **No refresh-worker deploy, so no in-flight sim is at
risk.** Cost is ~2 minutes of 502s across every route.

---

## 2. Cut the branch from the LIVE web SHA — never from `main`

```bash
python scripts/deploy_preflight.py --service web
```

Take the `live commit` it prints. **Re-read it here; it moved 3+ times on
2026-08-15 and `state.md` goes stale in minutes.**

```bash
LIVE=<live commit from above>
git branch -f deploy/clamp-on-live $LIVE
git diff 7bb74c95~1 7bb74c95 -- syndicate/features/shared/layer2_board.py pipeline/intelligence_state.py > /tmp/clamp.patch
```

Apply the patch onto that branch. **Do NOT `git apply` in the shared working
tree** — it carries other sessions' uncommitted hunks. Use a temp index or a
throwaway worktree:

```bash
git worktree add --detach C:/tmp/wt-clampdeploy $LIVE
cd C:/tmp/wt-clampdeploy && git apply /tmp/clamp.patch && git add -A && git commit -m "clamp fix on live"
```

**`origin/main` is NOT web-deployable.** It contains `ad4b0a3a`, deployed then
deliberately reverted 2026-08-15 03:00Z by another session. Deploying the tip
undoes that rollback.

If the patch does not apply, someone changed those functions since `7bb74c95`.
**Stop and re-read them** — do not force it.

---

## 3. Run the gate and READ it

```bash
python scripts/check_deploy_safety.py
python scripts/deploy_preflight.py --service web
```

`render_deploy.py` deliberately does not run the gate for you. Note that
`deploy_preflight.py` reported `UNKNOWN: sample is 87440s old` on 2026-08-15 —
an UNKNOWN is not a CLEAR. Decide explicitly.

---

## 4. Deploy

```bash
python scripts/render_deploy.py --service web --commit <branch tip>
```

`render_deploy.py` re-reads the live SHA at deploy time and **refuses a
non-descendant**. If it refuses, the live SHA moved while you worked — go back
to step 2 and re-cut. Do not reach for `--allow-rollback` to get past it; that
flag exists for a deliberate rollback, and using it here would silently drop
whatever landed in between.

---

## 5. Confirm the code is actually live — by CONTENT, not ancestry

```bash
python scripts/deploy_preflight.py --service web     # get the new live commit
git show <new live>:syndicate/features/shared/layer2_board.py | grep -c "max(0.02"
git show <new live>:pipeline/intelligence_state.py | grep -c "max(0.02"
```

Both must print **0**. A deploy that "succeeded" while carrying the wrong tree
is a real failure mode here — it is how the WNBA half was found already live.

---

## 6. The measurement — and the honest failure mode

```bash
python scripts/watch_clamp_trigger.py --once
```

**Expected: `POST_FIX_OK`** — the out-of-clamp probability now prices beyond
±4900 (e.g. `p=0.992056` → `-12488`, not `-4900`), or the column is absent.

**THE TRAP, and it is the likely one.** The board rebuilds roughly every 25
minutes. If the triggering row is gone from the slate by the time you read, the
result is **INCONCLUSIVE — not success.** `no_trigger` after a deploy proves
nothing at all; it is the same reading the pre-deploy slate gave.

So the measurement is only valid if **the row identity from step 0 is still
present**. If it is not: record INCONCLUSIVE, leave the fix deployed (it is
correct in code and proven by test), and wait for the next trigger. Do not write
"verified" into `deploys.md` on a `no_trigger`.

---

## 7. Record it

Append to `.syndicate/deploys.md`: the deployed SHA, the before/after
`fair_price` for the named row, and the verdict — `VERIFIED`, or `INCONCLUSIVE
(row left the slate)`. A deploy with no measurement is not evidence of a fix.

## Rollback

```bash
python scripts/render_deploy.py --service web --commit <the pre-deploy live SHA> --allow-rollback
```

The change is additive and behaviour-preserving on every in-range probability
(pinned by `tests/test_fair_price_unclamped.py`), so rollback pressure should be
low. Roll back for an unrelated 502 storm, not for a blank `fair_price` cell —
blank is the intended output where no price can honestly be derived.
