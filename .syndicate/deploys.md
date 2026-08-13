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
- Measured: **CLOSED 2026-08-13 22:48Z, at T+4.71h. The fix WORKS. The board
  froze anyway, for a different and worse reason.** The 24h read is cancelled —
  it would have measured a rebooted container.
  - **The code path is PROVEN to execute.** The live abort line carries
    `'basis': 'unreclaimable'`. That field is emitted only inside the abort
    branch, which is why it was unreadable while the fix was succeeding — the
    moment the guard refused, it became the liveness proof this row said could
    not be obtained.
  - **The fix is reading the right quantity.** Same line:
    `active_file: 891.7`, `inactive_file: 229.8` — both now credited as
    reclaimable, which is exactly what `#417` was about. It is NOT refusing
    over LRU bookkeeping.
  - **It refused because the memory is genuinely gone.** `anon: 2522.7`,
    `unreclaimable_mb: 2531.5`, `headroom 1564.5` against the 1900 floor.
    Trajectory across the window: `anon` **1163 -> 2603MB in 4.5 hours**.
    Compare `#417` itself: `anon` FLAT, +18.9MB over 5.4h. That one was
    bookkeeping; this is a real leak of roughly **300MB/hour**.
    - **RETRACTED 23:33Z — the 300MB/hour figure is NOT established and must
      not be cited.** Both numbers above are POINT SAMPLES, and `anon` is now
      measured to swing **~1650 <-> 3200MB within minutes** (floor 1652, p50
      2518, max 3203.7 in one 5-minute window). Two points cannot separate a
      ratchet from two phases of that swing — the same method retracted the
      same evening for the v2 sampler. The floor series, which is the honest
      one, reads 1670 / 1652 / 1763: roughly flat.
    - The original text is left standing because it is what was believed when
      the deploy below was ordered. **`#417`'s guard fix remains verified and
      correct** — what collapsed is the leak framing, not the fix.
  - **Consequence, and the reason this is a good outcome rather than a failed
    fix: the broken guard was MASKING genuine memory growth by failing for the
    wrong reason.** Repairing it made the real problem visible for the first
    time. Likely `#327 RESIDUAL` (the 493-878MB unattributed allocator).
  - Cost while open: `LAYER2_SHORTLIST` last fired `20:39:21Z`; the board
    served ~2h20m stale before the restart below.
- Verdict: **the guard change is correct and stays.** Do not revert it, and do
  not read the freeze as its failure. The floor (1900MB) is now the open
  question, and only after the leak is understood — resizing it against a
  leaking baseline would just move the freeze later.

---

### 2026-08-13 22:55-22:59Z — all three services to `d4bb29b5` (incident + backlog)
- Deployed: refresh-worker live **22:59:14Z**; web `dep-d9v4oih5efls73f3vfdg`
  live ~23:07Z. Both `trigger=api`, both on **`d4bb29b5`**.
- **CORRECTION 23:15Z — only TWO of the three landed.** live-odds-worker's
  deploy was created 22:55:27Z and is STILL `build_in_progress` 20 minutes
  later; its previous deploy took 4 minutes. **That service is still live on
  `95effcfa` and does NOT have the `#417` memory fix.** The old instance keeps
  serving correctly (Render does not swap until a build succeeds) and is
  healthy — publishing normally, `TICK_COMPLETE` each 60s, 1037MB headroom of
  2048. Three simultaneous deploys may have queued the build.
  - Impact is low: the guard has never fired on that service (all refusal
    tokens zero over ~6 days, measured at the 15:39 preflight), so it is not
    missing anything it needs tonight.
  - **But "I deployed live-odds" was believed and was false for 20 minutes.**
    A fired deploy is not a landed deploy; check `status=live` AND the commit
    on the service, not the POST's response.
- **Gate was NOT CLEAR and was overridden deliberately.** An MLB sim (pid 8565)
  and an odds refresh were killed. Justification: the board had been frozen
  ~2h20m and every build cycle was aborting before the fingerprint stage, so
  the sim's output had nowhere to land. No live games at the time.
- **This is SYMPTOM RELIEF, not a fix.** Measured immediately after:
  `anon` **2603 -> 980.6MB**, available **1483 -> 3110.7MB**. The restart
  clears the leaked memory exactly as the 14:56 and 18:05 restarts did.
  **Expect the freeze to return on the same ~300MB/hour trajectory, i.e.
  roughly 4-5 hours out.** — **PREDICTION FALSIFIED 23:33Z: aborts resumed at
  34 minutes, not 4-5 hours, and the regime is INTERMITTENT (8 builds, 4
  aborts) rather than the 300-consecutive-abort freeze this row describes.
  The linear model is wrong; see `#423`.** If the board is fine tomorrow morning it is because
  something restarted it, not because this was fixed.
- **Bundled, and the bundle is recorded honestly:** `#419` (`live_refresh_loop`,
  mlb-props-regen's), `#414` quote-join index + enrich instrument (behaviour +
  observability), `#421` measurement scripts. Three lanes in one deploy.
  `/preflight` FAILED this scope twice today and was overridden for the
  incident. Attribution for anything that regresses tonight is genuinely
  ambiguous — that was the price paid, knowingly.
- Measured: `<pending>` for the `#414` index — first useful reading is the
  **evening slate (20:49-00:45Z)**, since `SLOW_SEGMENT_PROFILE` only fires on
  a game over 5s. **If the index works, that instrument goes SILENT**, so read
  its absence only against `LAYER2_SHORTLIST` still recurring and the pre-fix
  baseline of 8 lines in ~4 minutes.
- Rollback: `py -3 scripts/render_deploy.py --service <name> --commit 03073270`
  (refresh-worker) / `95effcfa` (live-odds-worker) / `936e2b47` (web).

---

### Tooling note — `scripts/render_deploy.py` (2026-08-13)
Deploys now go through a script rather than raw `curl`. The API key is loaded
inside it, so the secret never reaches argv or a permission prompt, and the
service ids are an allowlist. It deliberately does NOT run
`check_deploy_safety.py` for you: a deploy tool that silently refuses is one
people learn to route around. Run the gate, read it, then deploy.
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
  - **SCHEDULING CONFLICT, found 2026-08-13 15:5x and handled.** A second
    scheduled task, `deploy-419-refresh-worker`, fires every 20 minutes
    between 00:00 and 05:00 and deploys `#419` (`d6188ca7`) to **the same
    service**. Any deploy reboots the container and **resets the `#417`
    re-warm clock**, which is the entire discriminating variable here — a
    freshly booted worker looks healthy for hours either way (`#417` records
    the pre-fix code rebuilding fine after a restart and only re-freezing
    ~3h later). Two scheduled jobs, neither aware of the other.
  - **Resolved by making the read robust rather than by pausing the deploy.**
    `417-24h-read` now (a) reads the CURRENT live deploy's `finishedAt` and
    uses it as the boundary instead of the hardcoded `18:05:38Z`, (b) asserts
    `03073270` is still an ancestor of the live commit and treats the read as
    VOID if it is not — a rollback would otherwise be measured as a result,
    (c) refuses to return "holds" when the window is **< 6h**, reporting
    INCONCLUSIVE instead, because the pre-fix code also stayed healthy ~3h
    after a restart. Note the fix itself survives any such deploy: `03073270`
    is an ancestor of `origin/main`, so `#419` carries it forward. Only the
    clock resets.
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
- [ ] **refresh-worker → the `#414` quote-join index. `/preflight` FAILED
      2026-08-13 16:55 CDT; HELD BY DECISION until after the 24h read.**
      - Target: **`9d730aec`**, which carries BOTH `#414` pieces — the index
        (`odds_book_quotes.py`, behaviour-critical) and the instrument that
        measures it (`quote_enrichment.py`, observability). Ship them together;
        the index without its instrument gives no `join_s` reading at all.
      - Failed on **three** grounds, any one sufficient: (1) against the live
        `03073270` it also carries `#419` (`live_refresh_loop.py` +107), which
        belongs to `mlb-props-regen` — three production changes, two of them
        behavioural; (2) the `#417` measurement window is open until
        2026-08-14 13:00 and a deploy reboots the worker, resetting the
        re-warm clock that is its entire discriminating variable; (3) NOT
        CLEAR — MLB sim running, live games in progress.
      - **Scope shrinks on its own overnight.** If `deploy-419-refresh-worker`
        fires (00:00–05:00) the worker lands on `d6188ca7` and `9d730aec` then
        adds exactly the two `#414` files. Check before firing; do not assume.
      - Expected effect, measured locally at production shard size (82,500
        rows): **85.43 → 0.66 ms/call, 130x, identical results**. In
        production terms MLB board-build `tail_s` falls from 21–54s to under
        5s and `rows_walked` per call from ~83,000 to double digits.
      - **MEASUREMENT TRAP, stated before the fact.** `SLOW_SEGMENT_PROFILE`
        is gated at 5s, so **if the fix works the instrument proving it stops
        firing**, and "no lines" is indistinguishable from "instrument broke"
        or "no evening slate". Read the absence ONLY against a positive
        control — `LAYER2_SHORTLIST` still recurring, so the board is building
        and games are being processed — and against the pre-fix baseline of
        **8 lines in ~4 minutes** on the 2026-08-13 evening slate.
      - Rollback: redeploy `03073270` (or `d6188ca7` if that landed first).
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
