# Deploy request — soccer-layer2-dates (live-lens observability)

- **service:** the worker(s) running the live-lens loop. Re-read 01:1xZ:
  `SYNDICATE_ENABLE_LIVE_LENS_LOOP = 'true'` on **BOTH** `refresh-worker`
  (`srv-d91dpertqb8s73co8ls0`) and `live-odds-worker` (`srv-d91dpertqb8s73co8lt0`);
  ABSENT on web. Observed soccer tick logs came from live-odds-worker.
  **If both genuinely run the loop, both need this or the fix is half-applied.**
- **sha:** `461774cb` (local `main` tip). **NOT PUSHED.**
- **urgency:** LOW. **Neither commit changes behaviour** — they only change what a
  failure looks like. Ride along with any worker deploy; do not open a window.

## the push is the awkward part, and it is why this is a message not just a file

`main` is **4 ahead / 239 behind** `origin/main`. The four ahead are interleaved, so
**my two cannot be pushed without the other two**:

| sha | files | what |
|---|---|---|
| `481de91d` | `live_lens_loop.py` +23 | MINE — soccer headroom gate now prints its skip |
| `1a764a8b` | `.syndicate/deploys.md` +85 | **LEDGER ONLY, not mine** |
| `1aba7e47` | `.syndicate/deploys.md` +38 | **LEDGER ONLY, not mine** |
| `461774cb` | `poll_soccer_live_state.py` +35 | MINE — poller logs each league's failure + traceback |

**The two that are not mine touch NO code — both are pure `deploys.md` writes.** So
the whole code delta is 58 lines across two files, both observability-only.

**No `render.yaml` in the range** — checked explicitly, so no `blueprint_sync`.

**I have NOT rebased or merged.** 239 behind on a shared tree with several sessions
holding uncommitted work is not something I will reconcile unilaterally. Landing this
is your call: pull the two commits across yourself, or tell me to reconcile and push.

## reason

The two silent handlers on the soccer live-lens path. Both are documented in the
2026-08-17 learnings entry as instances 2 and 5 of a family where the error path
rendered as the system's own "nothing here".

- `live_lens_loop.py`: soccer's headroom gate returned bare where MLB and WNBA both
  print `[LIVE_LENS_TICK_DIAG] ... reason=low_headroom`. **The gate is ARMED** —
  `SYNDICATE_SOCCER_LIVE_LENS_MEMORY_GATE_ENABLED` is ABSENT on all three services
  and absent means ENABLED (`_env_bool(default=True)`) at a 300MB floor. It was not
  tripping on 08-17 (measured, stays exonerated), but until this ships a trip is
  invisible.
- `poll_soccer_live_state.py`: **this is the handler that hid the 08-17 outage.** It
  caught each league's exception into an `errors` dict with no log line, and that dict
  reaches only `data/live/soccer_live_lens.json`, which is not in the publisher
  allowlist. Seven leagues wrote `(0 live games)` against ten active and the three
  missing were exactly the three with matches in play.

## verify

**Both were verified in BOTH directions locally, so post-deploy you only need the
quiet half.**

1. **The quiet case is the pass condition.** On a normal tick with no failures and
   sufficient headroom, expect **zero** `LEAGUE_POLL_FAILED` and **zero**
   `[LIVE_LENS_TICK_DIAG] sport=soccer` lines. A diagnostic that fires when nothing
   is wrong is worse than the silence it replaces.
2. Ten `wrote ... (N live games)` lines per tick, unchanged from the `6bdc50de`
   baseline. **This deploy must not change that number.**

Locally verified: gate trips -> line emitted + `{'ok': False, 'skipped': True,
'reason': 'low_headroom'}`; gate passes -> 0 lines. Poller, outage shape reproduced
-> 3 previously-silent failures logged with traceback, other 2 leagues still
processed; nothing failing -> 0 lines. 48 tests across four live-lens loop suites,
3 in the poller's own file, 36 across three soccer suites.

## rollback

`git revert 461774cb 481de91d`. Additive only — 58 inserted lines, 0 deleted, no
control-flow change in either.

---

## EXECUTED by the coordinator 2026-08-18 ~02:1xZ

**DEPLOYED to BOTH workers**, as this request's own service analysis concluded:
live-odds-worker `cdaeaa58`, refresh-worker `00e9a49f`, each cut on that
service's own live SHA. Both commits cherry-picked CLEAN onto both bases.

**The push this request was blocked on was already done.** All four commits in
the interleaved range reached `origin/main` at `9f255fca` before this was read.
The lane's refusal to rebase a 239-behind shared tree it did not own was correct
and is exactly what this role exists to absorb.

**COST, stated plainly:** refresh-worker had a live `run_mlb_daily_sim_job` and
this request says LOW urgency, "ride along with any worker deploy; do not open a
window." The user instructed both workers now, so the sim was spent on 58 lines
of observability. That was not this lane's ask and is recorded as the
coordinator's decision, not theirs.

**MEASUREMENT — and it is only visible on a failure:**
- `poll_soccer_live_state.py` should now name the league and print a traceback
  when a league's poll raises, instead of the tick reporting fewer leagues than
  `active_leagues_for_date` returned.
- `live_lens_loop.py` should now print `reason=low_headroom` when soccer's gate
  trips, matching MLB and WNBA. The gate is ARMED (absent env means enabled at a
  300MB floor) and was NOT tripping on 08-17, so a quiet slate proves nothing.

**A clean log is not evidence here.** Both changes alter what a FAILURE looks
like; neither emits on the happy path. The reading lands the next time soccer
actually fails.
