# Mirror — scheduled task `unknown-submit-balance-evidence-capture`

> ## ⚠ NOT RUNNING. NEEDS A ONE-TIME HUMAN APPROVAL. `[2026-08-30 04:1xZ]`
>
> **Two runs, two stalls, zero work done — and `lastRunAt` said it ran both
> times.** 03:10:47Z and 04:09:54Z: a session was created each time (so it
> EXECUTED — not a Modern Standby stall), then froze within a minute. The
> second run's transcript is TWO messages: the task prompt, then a single
> `Bash` call, nothing after. **It blocks on the permission prompt for its
> first `curl`.**
>
> **Narrowing it to read-only did NOT fix this and was the wrong remedy** —
> the blocker is the TOOL, not what the tool does. A brand-new scheduled task
> has no stored approvals, so its first `Bash` call prompts however innocuous
> the command is. Removing `.env`, the Render API and `git` changed nothing.
>
> **THE FIX IS A ONE-TIME "Run now" + approve.** Approvals granted during a run
> are stored on the task and auto-applied to every later run. Positive control,
> measured the same minute: `live-gameline-accuracy-snapshot` fired at 04:33:40Z
> and progressed normally — same machine, same scheduler, different only in
> having accumulated approvals.
>
> What you would be approving is now small, which is the one thing the
> narrowing did buy: one unauthenticated GET plus two local file writes. No
> credentials, no push.
>
> Until then the hourly schedule produces a stalled session per hour and NO
> measurement. Both stalls were archived. If nobody intends to approve it,
> DISABLE the task rather than leave it generating stalls, and leave the
> measurement to an interactive session — the lanes already record it as owed
> and unforceable.


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

## 2026-08-30 03:2xZ — NARROWED TO READ-ONLY after the first run stalled on a permission prompt

**The first version never did anything.** It dispatched at 03:10:47Z, created a
run session at 03:11:00Z, and then went silent — `lastActivityAt` frozen at
03:11:00 with `isRunning: true`, no heartbeat, no findings file. It stalled ~13
seconds in, waiting on a tool approval nobody was there to give. `lastRunAt`
said it ran.

**That is exactly what the heartbeat was added to catch, caught on run one.**
Without it, `lastRunAt: 03:10:47` plus a silent-on-null design reads as "ran,
found nothing" — a clean green from an instrument that had done nothing.

**Narrowed** `[user 2026-08-30: "narrow it to read-only so it runs unattended"]`
to one unauthenticated GET plus two local file writes. Removed: `.env`, the
Render logs API, and every `git` command including the push.

**WHAT WAS GIVEN UP, stated so nobody assumes coverage that is gone:**
`balance_settled` from the worker's `UNKNOWN_ORDER_PROBE`, and the log-derived
`LIVE_ORDER` positive control. The primary observable survives —
`balance_evidence` on the payload is the SAME arithmetic
(`venue_settlement._balance_evidence`, shared by the page and the probe).

**The control was rebuilt, not dropped.** `recent_orders_60m` is now counted
from `orders[].submitted_at` in the same payload. A null only means something if
the book is actually placing orders; a zero-order hour says nothing about 5xx
failures, and the task must say so rather than "nothing found".

Findings are written but LEFT UNCOMMITTED — an interactive session commits
them. If a row is ever captured, pull the matching `UNKNOWN_ORDER_PROBE` line
from the worker logs while it is still in retention.

---

---
name: unknown-submit-balance-evidence-capture
description: READ-ONLY, unattended: capture balance_evidence from the public portfolio payload the first time a Polymarket submit is lost to a 5xx.
---

Capture the first real observation of `balance_evidence` on a Polymarket submit the venue never answered.

READ-ONLY AND UNATTENDED BY DESIGN. Do NOT use credentials, do NOT read `.env`, do NOT call the Render API, do NOT run any `git` command, do NOT commit or push. The first version of this task did all of those and STALLED 13 SECONDS INTO ITS FIRST RUN on a permission prompt — `lastRunAt` said it ran, and it had done nothing. A watcher that needs a human to unblock it is not a watcher. Everything below is one unauthenticated HTTP GET plus two local file writes inside the project directory.

WHY THIS EXISTS. `balance_evidence` shipped on 2026-08-29 (`3371ad96`, web) and has NEVER been observed populated, because it requires an unknown submit to exist and there have been none. THE WINDOW IS SHORT: a retry, or an operator clicking "Venue shows no position", clears the row within minutes and the evidence with it. So CAPTURE, do not merely notice. Background: `.syndicate/lanes.md`, lanes `unknown-submit-retry-provenance` and `unknown-submit-balance-evidence-ui` (both CLOSED-VERIFIED; this is the one measurement they still owe).

Work in `C:\Users\tempadmin\OneDrive\Coding\Syndicate`.

STEP 1 — ONE request, no auth:
  curl -s "https://syndicate-an21.onrender.com/api/portfolio/live?on=all"

STEP 2 — HEARTBEAT, every run, even when nothing is found. Overwrite (never append) `.syndicate/.unknown_submit_watch_heartbeat` with ONE line:
  <UTC timestamp> ran=1 http=<code> unknown_submits=<n> recent_orders_60m=<n> note=<short>
This file is gitignored and must never be committed. Its purpose: this task is SILENT on a null run, and `lastRunAt` records DISPATCH not execution — without this line, "ran and found nothing" and "never ran" are identical. Write it even if step 1 failed (`http=000 note=fetch_failed`).

STEP 3 — THE POSITIVE CONTROL, computed from the same payload. Count orders in `orders[]` whose `submitted_at` is within the last 60 minutes; that is `recent_orders_60m`. **A null result only means something if the system is actually placing orders.** If `recent_orders_60m` is 0 the book was idle and your null says nothing about 5xx failures — say exactly that, do not say "nothing found".

STEP 4 — if `unknown_submits` is NON-EMPTY, capture it. For every row record verbatim: `idempotency_key`, `venue_ticker`, `selected_date`, `requested_stake_dollars`, `status`, `error`, `venue_order_id`, `submitted_at`, `venue_resolved_at`, `prior_attempts`, and the entire `balance_evidence` object (`verdict`, `reason`, `window`, `opening_dollars`, `closing_dollars`, `delta_dollars`, `confounding_orders`). Also `unknown_submit_dollars` and `unknown_submits_resolved`.
Append to `.syndicate/findings_unknown_submit_live_evidence.md` (create with an `# ...` H1 if absent). A DEDICATED file — never write to `lanes.md` or `state.md`, which many sessions contend for.
Head each entry with the UTC timestamp, then the verbatim JSON, then a one-line reading: `not_placed` (balance flat across the submit), `placed` (balance fell by at least the stake), or `unknown` with its reason (`confounded` / `no_bracketing_reading` / `unreadable` / `moved_but_not_by_this_order`). **`unknown` IS A REAL RESULT** — on a busy slate `confounded` is expected and is the guard refusing to guess, not a failure.
LEAVE IT UNCOMMITTED. A later interactive session commits it. Do not run git.

IDEMPOTENCE: before appending, read the file and skip any `idempotency_key` already recorded. Hourly runs must not duplicate.

BE SILENT WHEN THERE IS NOTHING: no findings file, no other ledger edits, no messages. A watcher that speaks every hour is one people stop reading. The heartbeat is a local file, not speech.

DO NOT attempt to create an unknown submit — that would mean deliberately failing a real money order. Finding none is the correct and expected outcome on nearly every run.

WHAT THIS VERSION GAVE UP, so nobody assumes it still covers them: the Render log query is gone, so `balance_settled` from `UNKNOWN_ORDER_PROBE` and the log-derived `LIVE_ORDER` control are NOT captured here. `balance_evidence` from the payload is the same arithmetic (`venue_settlement._balance_evidence`, shared by both paths), so the finding is preserved; only the worker-side confirmation is not. If a row IS captured, an interactive session should pull the matching `UNKNOWN_ORDER_PROBE` line from the worker logs while it is still in retention.