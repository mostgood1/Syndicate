# BREAK-GLASS AUTHORIZED — web — 2026-08-18 ~22:0xZ (5:0x PM CDT)

**USER AUTHORIZED EXPLICITLY**, in session `repo-coordination`, in these words:
*"go ahead and authorize the break-glass for web"*. Logged here because a
deliberate override of `deploy-guard.py` is a user decision and the protocol
requires the override be written down, not carried in a session.

**FOR:** lane `convergence-phase7-crps`, which holds the web claim (acquired
2026-08-18 21:46:33Z, 45-min TTL → expires ~22:31:33Z / 5:31 PM CDT).
**SERVICE:** web / syndicate (`srv-d88ahvrbc2fs73eodu30`) only. Not
refresh-worker, not live-odds-worker.

---

## WHY THE GUARD CANNOT BE SATISFIED NORMALLY

`deploy_preflight.py --service web` returns **UNKNOWN**, reason
`sample is 356656s old (limit 180s)` — **4.1 days**. It is not a slow sample;
it is a frozen one. The same sample read "3.9 days old" at ~18:4xZ today, and
3.9 days + the ~3.2h since ≈ 4.1. It only ages. **No amount of waiting or
re-running will return CLEAR.**

**DO NOT widen `--max-sample-age-seconds`.** It was already proposed and refused
as vacuous, and correctly: it produces no evidence, it relabels absence as
permission. That is the "unknown must not default permissive" failure exactly.

## THE SUBSTITUTE MEASUREMENT — TAKEN, AND IT IS CLEAN

`GET /api/ops/memory` on live web, 2026-08-18 ~22:0xZ. **Every process
identified BY CMDLINE**, which is the standard the football-model-owner
precedent set at 18:3xZ today:

    pid   1   rss    3.23 MB  bash /home/render/graceful-shell-command.sh ...   INFRA
    pid  62   rss  136.85 MB  gunicorn wsgi:application (master, ppid 1)        INFRA
    pid  79   rss  405.91 MB  gunicorn wsgi:application (worker)                INFRA
    pid  80   rss  518.70 MB  gunicorn wsgi:application (worker)                INFRA

**process_count 4, JOB PROCESSES 0.** No `run_*_sim_job.py`, no
`tools/daily_update.py`, nothing under `scripts/`. All four are the web server
itself. **A deploy of web right now kills no work.** That is the finding the
break-glass rests on — not "the guard is annoying", but "the thing the guard
protects has been measured by other means and is safe".

Container at read time: 1715.95 / 2048 MB (83.8%), headroom 332 MB,
accounted RSS 1064.7 MB, unexplained 651.25 MB. The unexplained figure is
consistent with page cache and is not a blocker; web is display-only.

## THE OFF-MAIN HALF IS ALREADY SOUND — VERIFIED, NOT ASSUMED

The receipt read `OFF_MAIN` at 21:47:22Z and `UNKNOWN` at ~22:00Z, so
`--allow-off-main` was passed. That is justified **in substance** here, and the
reason is checkable:

    live web         841b6d84
    target           055dfc67
    is live an ancestor of target?      YES
    merge-base(live, target)            841b6d84
    commits in live but NOT in target   (none)

`055dfc67` was cut **directly off the live SHA** — the recipe the ledger
prescribes. It is CUMULATIVE and reverts nothing, so the hazard `OFF_MAIN`
exists to catch (two off-main deploys not composing; measured 2026-08-15, a
verified fix live 21:36:59Z and gone by 21:45:20Z) **does not apply to this
deploy**. Still say so in `deploys.md` when you land it.

---

## HOW TO CONSUME THIS

The guard's break-glass is keyed on the **deploying session's** `session_id`
(`_grant()`, `deploy-guard.py:284`), so this note cannot itself unlock anything
— only the session that will fire the deploy can write its own grant. Write:

    .syndicate/deploy/grants/<YOUR_session_id>.json

```json
{
  "service": "web",
  "note": "User-authorized break-glass 2026-08-18 ~22:0xZ. web emits no ALL_PROCESS_MEMORY so preflight is UNKNOWN-forever; substituted a live /api/ops/memory read, 4 processes all gunicorn/entrypoint by cmdline, 0 jobs. Target 055dfc67 contains live 841b6d84 (merge-base == 841b6d84) so the deploy is cumulative. See AUTHORIZATION-2026-08-18-web-breakglass.md.",
  "expires_epoch": 0
}
```

Set `expires_epoch` to **now + 1800** (30 min). Keep it short — this authorizes
*this* deploy, not a standing exemption. The guard prints loudly when a grant is
used, which is intended.

**AFTERWARDS, BOTH REQUIRED:** record the measurement in `.syndicate/deploys.md`
(`verify:` = the READING that proves it worked, not the thing you will watch),
then `python scripts/deploy_claim.py release --service web`.

---

## ROOT CAUSE — CORRECTED. MY FIRST ANSWER HERE WAS WRONG.

**Filed as `#465`.** The authorization above is UNAFFECTED — the 0-jobs
measurement and the ancestry check stand on their own. Only the *explanation*
changed.

**WHAT I FIRST WROTE, AND WHY IT WAS WRONG.** This section originally said web
emits no `ALL_PROCESS_MEMORY` because **`psutil` is not installed** — the
payload does carry `"psutil_available": false` and
`"errors": ["psutil_unavailable:ImportError"]`, and psutil is genuinely absent
from every `requirements*.txt`. That pairing is tempting and it is not the
cause. The same debug block shows `procfs_iterated_count: 4` against
`psutil_iterated_count: 0` — **the procfs fallback enumerated all four
processes successfully**, cmdlines and RSS included. Installing psutil on web
would not move this at all.

**THE ACTUAL CAUSE: no web code path CALLS the emitter.**
`log_all_process_memory` (`memory_observability.py:1944`, printing the line at
:1952) has exactly four callers, every one worker-side —
`run_refresh_worker.py`, `run_live_odds_refresh_worker.py`,
`refresh_odds_sources.py`, `pipeline/intelligence_state.py`. `syndicate/app.py`,
`wsgi.py` and all of `syndicate/blueprints/` have **zero** occurrences. Web runs
`gunicorn wsgi:application` and never executes any of the four.

The discriminating evidence was the CALLER TRACE, not the endpoint payload.
*Check that the line is emitted before concluding it is lost* — I had that rule
and did not apply it.

**WHY THE CORRECTION MAKES THE FIX BETTER, NOT WORSE.** `GET /api/ops/memory`
on web already returns a complete and FRESH enumeration — that is what the
measurement above is. Only the *log-line* channel is missing. So the fix is not
to instrument web with periodic work on the request path (which the worker-split
rule exists to prevent, and which `#241` already turned into a restart loop);
it is to **teach `deploy_preflight.py` to read `/api/ops/memory` for web**, i.e.
make the break-glass path the normal path. Until that lands, every web deploy
needs one of these files, and a guard that must be broken on every use has
stopped being a guard.
