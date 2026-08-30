# Mirror — scheduled task `unknown-submit-balance-evidence-capture`

**This file is the CANONICAL text of the task prompt.** The live task lives at
`~/.claude/scheduled-tasks/unknown-submit-balance-evidence-capture/SKILL.md`,
which is **outside this repo and not under version control on any machine**.

**It is a COPY, and copies drift.** If you change the live task, update this
file in the same pass. If they disagree, the live task is what actually runs —
reconcile deliberately, do not assume this one is current.

Created 2026-08-30 (local), cron `0 * * * *`, `notifyOnCompletion: false`.
Recreate it from this file with the `schedule` skill or `create_scheduled_task`.

## What it is for, and why a scheduled task rather than a session watch

Two code paths shipped 2026-08-29 and NEITHER has been observed running:
`balance_settled` in `UNKNOWN_ORDER_PROBE` (`219d79ca`, live-odds-worker) and
the `/portfolio` banner's `balance_evidence` line (`3371ad96`, web). Both
require an unknown submit to EXIST, and there are none — so the measurement
cannot be forced, only waited for. A session watcher was armed first and dies
with its session; this survives.

**It CAPTURES rather than alerts, and that is the whole design.** The window is
minutes: a retry, or an operator answering "Venue shows no position", clears the
row and the evidence with it. An alert that arrives after the row is gone is
worth nothing.

**It writes to its own file, never to `lanes.md` or `state.md`.** Those are
contended by many sessions — on 2026-08-30 `lanes.md` sat in an unresolved
merge state for hours with three OPEN lanes existing on only one side. A
scheduled writer into a contended ledger would eventually lose someone's work.

**It is silent on a null run** (most runs), and when it does report nothing it
must state the `LIVE_ORDER` count as a positive control — absence of `http_503`
means nothing if no orders were being placed at all.

Output lands in `.syndicate/findings_unknown_submit_live_evidence.md`.

## 2026-08-30 — heartbeat added, because I had built the exact blind spot I keep logging

The task was SILENT on a null run by design (a watcher that speaks hourly is one
people stop reading). But silent-on-null plus `lastRunAt` recording DISPATCH
rather than execution means **"it ran and found nothing" and "it never ran"
are indistinguishable** — and this machine has stalled a scheduled run by 9h13m
under Modern Standby, so that is not hypothetical.

Step 0 now overwrites (never appends) `.syndicate/.unknown_submit_watch_heartbeat`
with one line carrying the UTC timestamp and the counts, written FIRST and again
at the END so a half-finished run is visible as one. **Local only, never
committed** — it answers a local question ("did this machine run it recently")
and committing it hourly would be the noise the silence was protecting against.

Also pinned in step 4: when reporting nothing found, the `LIVE_ORDER` count for
the same window must be stated. Absence of `http_503` is only evidence if orders
were actually being placed; a zero-order window says nothing about 503s.

---

---
name: unknown-submit-balance-evidence-capture
description: Capture balance_evidence / balance_settled the first time a Polymarket submit is lost to a 5xx; the window closes within minutes.
---

Capture the first real observation of `balance_evidence` / `balance_settled` on a Polymarket submit the venue never answered.

WHY THIS EXISTS. Two code paths shipped 2026-08-29 (`219d79ca` on live-odds-worker, `3371ad96` on web) and NEITHER has ever been observed running, because both require an unknown submit to exist and there were none. THE WINDOW IS SHORT: a retry or an operator clicking "Venue shows no position" clears the row within minutes, and once cleared the evidence is unrecoverable. So CAPTURE, do not merely notify. Full background: `.syndicate/lanes.md` lanes `unknown-submit-retry-provenance` and `unknown-submit-balance-evidence-ui`.

Work in `C:\Users\tempadmin\OneDrive\Coding\Syndicate`.

STEP 0 — HEARTBEAT, AND IT IS NOT OPTIONAL. Do this on EVERY run, first, before anything can fail. Overwrite (never append) the local file `.syndicate/.unknown_submit_watch_heartbeat` with ONE line:
  <UTC timestamp> ran=1 unknown_submits=<n or ?> live_orders=<n or ?> probe_lines=<n or ?> note=<short>
DO NOT COMMIT THIS FILE — it is a local liveness marker, it is gitignored-by-intent, and committing it hourly would be noise. Its whole purpose: this task is SILENT on a null run, so without a heartbeat "it ran and found nothing" and "it never ran / died on step 1" are indistinguishable, and `lastRunAt` records DISPATCH, not execution (this machine has stalled a scheduled run by 9h13m under Modern Standby). Rewrite the line at the END of the run too, with the real counts, so a half-finished run is visible as one.

STEP 1 — the banner observable (no credentials needed):
  curl -s "https://syndicate-an21.onrender.com/api/portfolio/live?on=all"
Parse JSON. Look at `unknown_submits`. If NON-EMPTY, record verbatim for every row: `idempotency_key`, `venue_ticker`, `selected_date`, `requested_stake_dollars`, `status`, `error`, `venue_order_id`, `submitted_at`, `venue_resolved_at`, `prior_attempts`, and the whole `balance_evidence` object (`verdict`, `reason`, `window`, `opening_dollars`, `closing_dollars`, `delta_dollars`, `confounding_orders`). Also `unknown_submit_dollars` and `unknown_submits_resolved`.

STEP 2 — the probe observable (needs credentials):
Read `RENDER_API_KEY` from the gitignored `.env` by sourcing it in the same shell command; never print it. Owner `tea-d2bb5n95pdvs73cje4fg`, service `srv-d91dpertqb8s73co8lt0` (live-odds-worker). Query the Render logs API over the last 90 minutes:
  https://api.render.com/v1/logs?ownerId=<owner>&resource=<service>&startTime=<now-90min ISO Z>&limit=50&text=UNKNOWN_ORDER_PROBE
Also `text=http_503`, `text=OPERATOR_RESOLUTION`, and `text=LIVE_ORDER` (the last is the POSITIVE CONTROL — see step 4). Record matching lines verbatim with timestamps. The `UNKNOWN_ORDER_PROBE` line is the prize: it carries `balance_settled=N` and `findings=[...]` with `balance_evidence` per order.

STEP 3 — write it down, ONLY if something was found:
Append to `.syndicate/findings_unknown_submit_live_evidence.md` (create with an `# ...` H1 if absent). A DEDICATED file — do NOT write to `lanes.md` or `state.md`; those are contended by many sessions and a scheduled writer will eventually lose someone's work.
Head each entry with the UTC timestamp. Record the verbatim payload/log lines, then a one-line reading: `not_placed` (balance flat across the submit), `placed` (balance fell by at least the stake), or `unknown` with its reason (`confounded` / `no_bracketing_reading` / `unreadable` / `moved_but_not_by_this_order`). `unknown` IS A REAL RESULT — on a busy slate `confounded` is expected and is the guard refusing to guess, not a failure.
Then commit and push ONLY that one file, from a throwaway worktree off origin/main, NEVER from the shared primary tree:
  git worktree add --detach /c/tmp/usle origin/main
  (write it there, git add that path only, commit, git push origin HEAD:main, git worktree remove --force /c/tmp/usle)
Before pushing, verify `git diff --cached --numstat` lists ONLY that file.

IDEMPOTENCE: before appending, read the file and skip any `idempotency_key` or log timestamp already recorded. Hourly runs must not duplicate.

STEP 4 — reporting, and the control that makes a null mean something:
BE SILENT WHEN THERE IS NOTHING: write no findings file, commit nothing, open no lane, edit no other ledger file. A watcher that speaks every hour is one people stop reading. (The heartbeat in step 0 is not "speaking" — it is a local file, not a message.)
When you report nothing found, ALWAYS state the `LIVE_ORDER` count in the same window. **Absence of `http_503` is only evidence if orders were actually being placed.** If `LIVE_ORDER` is 0 the worker was idle and your null says nothing about 503s — say exactly that rather than "nothing found".

DO NOT attempt to create an unknown submit. That would mean deliberately failing a real money order. Seeing none is the correct and expected outcome on most runs.