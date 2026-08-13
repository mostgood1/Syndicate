# Syndicate — Deploy Ledger

> **Append only.** Never edit a past row. A row with an empty Measured
> column is an open obligation, not history.

---

### #394 — hash guard
- Deployed: 2026-08-12 20:26
- Change: compare the computed checksum instead of merely sending it, so
  unchanged artifacts are skipped rather than re-uploaded.
- Expected: sharp drop in redundant uploads per sweep.
- Measured: logging skips as intended. **Egress impact not isolated —
  deployed close to #395.** `[partial]`
- Rollback: revert #394
- Verdict: shipped, effect not cleanly attributed.

### #395 — rate ceiling
- Deployed: 2026-08-12
- Change: caps worst-case egress at 2 GB/hr per service.
- Expected: hard ceiling on blast radius, not a fix.
- Measured: `<pending>`
- Rollback: revert #395
- Verdict: mitigation, not remediation. Do not treat a flat graph under
  this cap as evidence the underlying issue is solved.

### Baseline measurement — first-byte sample
- Date: 2026-08-12
- n=29 uploads, 86.2 MB total. Min 325 B, median ~73 KB, max 11.6 MB.
- Read: highly skewed — bytes concentrated in a few large artifacts.
  Any fix must be evaluated on total bytes, not upload count.

### `#417`/`#387` — guard on unreclaimable memory
- Deployed: 2026-08-13 12:57 CDT (`17:57:53Z`), refresh-worker
  `srv-d91dpertqb8s73co8ls0`, deploy `dep-d9v0b8bncjis73an78hg`,
  commit **`03073270`**, trigger `api`.
- Preceded by: `/preflight` FAIL -> remediated. `check_deploy_safety.py`
  CLEAR at 12:53, 12:54 and 12:57 (MLB sim finished exit=0, odds refresh
  idle). Standing caveat accepted: **live games were in progress**, so
  live-lens ticks and live prop hydration took an interruption.
- Change: `memory_headroom_snapshot` decides on `max - unreclaimable`, where
  unreclaimable is `max(anon + shmem + slab_unreclaimable,
  current - reclaimable_file)` and `reclaimable_file` now includes
  `active_file`. Replaces `(max - current) + inactive_file +
  slab_reclaimable`, under which a kernel LRU promotion moved the verdict
  ~243MB with no change in memory pressure.
- **One substantive change.** Deployed at `03073270` rather than at the
  `origin/main` tip deliberately: the tip also carries another session's
  `live_refresh_loop.py` work (`#419`/`#420`), which would have made this two
  changes in one deploy and left neither cleanly attributable. Only `.py`
  delta vs the previously deployed `448e1816` is
  `memory_observability.py` + its tests.
- Expected: `MEMORY_GUARD_ABORT stage=pre_source_state_fingerprint` falls
  from ~300 per 5.4h to ~0 within 24h with `anon` flat (±25MB);
  `layer2_shortlist` `written_at` advances every ~65s instead of freezing;
  `#387`'s overview stops aborting at `sports_done=0 sports_total=8`.
- **Read `basis` BEFORE the abort count.** `basis=unreclaimable` proves the
  new path executed. `basis=reclaimable_cache` means it degraded to the old
  arithmetic and a zero abort count is inert-guard-shaped and means nothing.
  A zero is evidence only once the instrument is known able to read non-zero.
- Measured: `<pending>` — 24h read due **2026-08-14 ~13:00 CDT**.
  **OWNER ASSIGNED 2026-08-13 15:3x CDT: scheduled task `417-24h-read`**, a
  one-shot at 2026-08-14 13:00 CDT
  (`C:\Users\tempadmin\.claude\scheduled-tasks\417-24h-read\SKILL.md`). It
  carries the deploy boundary (`2026-08-13T18:05:38Z`), the service id, the
  verdict rule, and the three traps that caught this session (the ~35-second
  log-query window; `basis` being emitted only on the abort branch; and the
  positive-control requirement before believing any zero).
  - **Scheduled LOCALLY, not as a cloud routine, and that is load-bearing.**
    `.env` is gitignored (`.gitignore:3`) and untracked, so a cloud agent gets
    a checkout with no `RENDER_API_KEY` and cannot reach the Render API at all.
    It would have reported a null reading that looks exactly like a real one.
  - **Local tasks only run while the app is open.** If it is closed at 13:00
    the run happens at next launch — so a late timestamp on this row means
    "fired late", not "the worker was quiet". Check the run time before
    reading the numbers.
  - This row still stays open until the numbers are actually written into it.
    An assigned owner is not a measurement.
- INTERIM (T+23min, 13:28 CDT). **Positive, NOT sufficient. Row stays open.**
  - `LAYER2_SHORTLIST` x3 post-deploy — 18:19:15, 18:25:21, 18:28:30Z —
    against **0** in the 4h12m before. `MEMORY_GUARD_ABORT` post-deploy: 0,
    against ~300 in 5.4h before. The board is rebuilding.
  - Steady state at T+23min: `unreclaimable` ~1902-1916MB -> ~2180-2194MB
    available against the 1900 floor. Margin ~280MB.
  - **Why this is not yet proof.** The container is 23 minutes from boot.
    `#417` recorded that the pre-fix code ALSO rebuilt after a restart
    (14:56 restart -> 15:08 build) and then re-froze roughly 3h later as it
    re-warmed — it was aborting again by 18:00. This deploy has not yet
    survived that re-warm interval, so the observation is still consistent
    with "rebooted" as well as with "fixed".
  - At the 18:22:25Z transient spike (`current` 4042.6, `unreclaimable`
    3100.1) the NEW formula would itself have refused (996MB available).
    No abort fired because the guard is evaluated per cycle, not
    continuously — the spike is intra-build. Recorded so a later reader does
    not mistake it for the guard failing to fire when it should.
  - Instrument caveat: a 100-line log query on this service spans **~35
    seconds**. Any "n samples above X" count from a single query is a
    statement about that window, not about the post-deploy period.
- Not verified, deliberately unclaimed: that the new code PATH executed.
  `basis` is emitted only inside the abort branch
  (`intelligence_state.py:3215`), so a working fix leaves it permanently
  silent. Its absence here is a fact about the emitter. Closing that gap
  needs a success-path log — a code change and a second deploy, deliberately
  not ridden along with this one.
- Rollback: redeploy `448e1816` on `srv-d91dpertqb8s73co8ls0` via
  `POST /v1/services/<id>/deploys {"commitId":"448e1816"}`. Code-only, no
  `render.yaml` in this deploy, so nothing to unwind on the config side.

---

### PENDING

- [ ] Internal-hostname cutover — expected effect, window, and rollback
      to be written by `/preflight` **before** it goes out.
      NOTE 2026-08-13: `state.md` and `lanes.md` both record this as CLOSED
      and verified in production (`PUBLISH_OK ... url=http://syndicate-an21`
      at `14:54:11Z`). This file is append-only, so it needs a **new row**
      appended by its owner rather than an edit here — read on its own,
      the deploy ledger currently understates what is already known.
- [ ] `#395` rate ceiling — still `Measured: <pending>` with no follow-up row.
- [ ] **live-odds-worker → the `#417` memory fix. `/preflight` FAILED
      2026-08-13 15:39 CDT; HELD BY DECISION until after the 24h read.**
      - Target when it goes: **`03073270`** — it isolates the change to
        `memory_observability.py` + tests. `origin/main` would also drag in
        another lane's `live_refresh_loop.py` (`#419`/`#420`), making it two
        substantive changes.
      - Why it failed: **no observable to move.** On
        `srv-d91dpertqb8s73co8lt0`, `SKIPPED_FOR_MEMORY`, `MEMORY_GATE`,
        `ODDS_REFRESH_MEMORY_HEADROOM_CHECK`, `MEMORY_GUARD_ABORT` and
        `insufficient` are **all zero** over the API's ~6-day text reach
        (positive control returned 30 hits, so the probe works). The bug is
        **latent here, never once fired.** No number to state, so no reader
        to assign.
      - Why held rather than shipped anyway: the identical change is
        **unverified on refresh-worker until 2026-08-14 13:00**. Shipping it
        to a second service inside that open window is the `#394`/`#395`
        mistake — two services changed, neither attributable.
      - **The risk to weigh when it does go.** live-odds-worker is **2GB with
        an OOM history**, and the fix is MORE permissive there. At
        `current=1900, anon=1000, active_file=800, inactive=100`: old gives
        `(2048-1900)+100 = 248MB` → refuse; new gives `2048-1000 = 1048MB` →
        allow. The new answer is believed correct (`active_file` is evictable;
        the kernel drops it rather than OOM-killing) but that is **thesis, not
        measurement**, and it has never been exercised on a 2GB container.
      - It DOES run the guard — `SYNDICATE_ENABLE_LIVE_ODDS_REFRESH_LOOP`,
        `SYNDICATE_ENABLE_LIVE_LENS_LOOP`, `MLB_ENABLE_LIVE_LENS_LOOP` all
        `true`, `SYNDICATE_LIVE_LENS_MIN_HEADROOM_MB=300`. So the fix is not
        inert here, unlike on web. `[measured 08-13 15:39]`
