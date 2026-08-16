# Mirror — scheduled task `clamp-fix-verification-watch`

**This file is the CANONICAL text of the task prompt.** The live task lives at
`~/.claude/scheduled-tasks/clamp-fix-verification-watch/SKILL.md`, which is
**outside this repo and not under version control on any machine**. It runs
every 2h and is the mechanism that closes `#439` item 1, so the instructions
were mirrored here rather than left to survive only in a user directory.

**It is a COPY, and copies drift.** If you change the live task, update this
file in the same pass. If they disagree, the live task is what actually runs —
reconcile deliberately, do not assume this one is current.

Mirrored 2026-08-15 (local) after the prompt was rewritten to check
**refresh-worker** instead of web: refresh-worker `57a437d5` is the producer
(it runs the intelligence-state loop), and web's copy of the fix is inert
because its block is a backfill guarded on `fair_price` being absent.

A second, one-off task `clamp-watch-one-hour-check` was created the same evening
with the same verdict logic; it auto-disables after firing and is not mirrored.

Recreate the live task from this file with the `schedule` skill or
`create_scheduled_task`, cron `0 */2 * * *` (local time).

---

---
name: clamp-fix-verification-watch
description: Check whether the ±4900 fair-price clamp fix is verified in production; notify on a verdict.
---

Check whether the Syndicate ±4900 fair-price clamp fix has been verified in production. Run from `C:\Users\tempadmin\OneDrive\Coding\Syndicate`.

BACKGROUND (you start fresh with no memory of the session that created this):
A `max(0.02, min(0.98, p))` clamp in three places published a wrong "fair price" whenever a market's no-vig probability fell outside [0.02, 0.98] — e.g. 0.014698 published as +4900 where the correct price is +6704.

Deploy state as of 2026-08-16 00:23:04Z:
- **web** — carries the fix, and it is INERT there. Web's block is a *backfill* (`if fair_probability is not None and card.get("fair_price") is None:`), so a value already clamped upstream passes through untouched. **Web is not the producer. Do not check web.**
- **refresh-worker `57a437d5`** — THE PRODUCER, and it carries the fix. It runs the intelligence-state loop (`SYNDICATE_ENABLE_INTELLIGENCE_STATE_BACKGROUND_LOOP` is `true` only here). This is the service every check below is about.
- **live-odds-worker** — still carries the clamp, DEFERRED by user decision. It does not run the intelligence-state loop, so it is not the producer. Branch `079cc42b` is ready if it is ever wanted. **Do NOT deploy it.**

A web-only deploy was FALSIFIED in production on 2026-08-15 (23:10:13Z and 23:15:46Z), which is why the producer distinction above matters. The fix has still NEVER been observed working. Full context: `docs/ai_context/todo.md` item `#439`.

STEP 1 — run the instrument (read-only: two production HTTP calls, no API key):

```
py -3 scripts/watch_clamp_trigger.py --once
```

Note the board rebuilds on roughly a 25-minute cycle. Re-running faster than that re-reads the same artifact and cannot produce new information — do not retry a `no_trigger` in a tight loop.

STEP 2 — act on the exit code and verdict:

- **exit 0, `no_trigger`** — no market on the current slate has a probability outside [0.02, 0.98], so nothing is provable right now. **This is NOT evidence the fix works** — it is the same reading a quiet slate gives with the bug fully present. Do nothing further and send NO notification. Quiet runs are expected and common. Note that triggers have come from IN-PLAY markets late in games, not from a pregame board.

- **exit 10, verdict `POST_FIX_OK` (or `POST_FIX_OK_COLUMN_ABSENT`)** — THE FIX IS VERIFIED. An out-of-clamp probability priced correctly (beyond ±4900) or the column was correctly omitted. Send a PushNotification saying the clamp fix is verified in production. Append a short dated result to `.syndicate/deploys.md` under the **refresh-worker `57a437d5`** entry, citing the evidence file in `reports/clamp_watch/`. Then mark item 1 of `#439` in `docs/ai_context/todo.md` CLOSED, naming the evidence file that closed it.

- **exit 10, verdict `PRE_FIX_MISPRICE`** — THIS IS A FALSIFICATION, not a retry, and it is the more urgent outcome. A mispriced row is being published while a fix-carrying commit runs on the producer. Before reporting, confirm the deployed code by CONTENT rather than by ancestry — these SHAs move often (one service moved 4× in 100 minutes), and the workers run off-main deploy branches, so ancestry proves nothing:
  ```
  py -3 scripts/deploy_preflight.py --service refresh-worker    # read the live commit
  git grep -c "max(0.02, min(0.98" <live commit> -- pipeline/intelligence_state.py syndicate/features/wnba/cards.py syndicate/features/shared/layer2_board.py
  ```
  `git grep -c` prints nothing and exits non-zero when there are no matches — that is the clean result.
  - **If it prints nothing (0 sites) and the misprice is still published:** the attribution of the misprice to refresh-worker's intelligence-state loop is WRONG and the real producer is still unidentified. That is a genuine finding and this lane's stated falsification test. Send a PushNotification saying so plainly and write it up in `.syndicate/deploys.md`.
  - **If any file prints 1:** a deploy dropped the fix or rolled it back. Say that instead, and name the live commit.

- **`TRIGGER_UNCONFIRMED`** — the confirming read failed. A failed read is not a result. Re-run `--once` once; if it fails again, do nothing and send no notification.

RULES:
- Never record the fix as verified on a `no_trigger`. It discriminates nothing.
- `out_of_clamp=0` comes from the worker's artifact and reports whether such a probability EXISTS on the slate, not whether it was priced correctly. It is never evidence the fix worked.
- A deploy claim's `target` is an intention, not a deployment. Never infer what is running from a claim; read the live commit and check by content.
- Keep any notification under 200 characters, one line, no markdown.
- Do not deploy anything. This task only measures.
- If you write to `.syndicate/**` or `docs/ai_context/todo.md`, commit with an explicit pathspec (`git commit -- <paths>`) — the repo has concurrent sessions and a bare commit would sweep in their staged work. Never `git add -A`.