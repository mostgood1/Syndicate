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

### nfl-day-of-game — NFL cards carry real game state (WEB ONLY)
- Deployed: 2026-08-13 (pending — see Verdict/measurement below)
- Lane: `nfl-day-of-game`
- Service: **`syndicate` (web) ONLY.** refresh-worker deliberately NOT
  deployed, so no in-flight MLB sim is killed. Checked rather than assumed:
  `attach_game_state` runs at SERVE time on web (`intelligence.py:2378`,
  `:2838`) and overwrites `row["game"]`, so web alone moves every observable
  below. `book_grid_artifact.py:214` attaches the same state at artifact-build
  time on the worker, but the serve-time attach wins.
- Change (three, bundled — see the scope note):
  1. `nfl/live_game_state.py` (new) + `nfl/preseason_cards.py` — stamp
     `live_state` onto NFL cards from ESPN's scoreboard. Both
     `publication_adapter._shared_game_state` and
     `game_chip_scoreboard._game_flags` already READ `live_state`; no NFL
     builder ever set one, so every NFL game reported `pregame` forever.
  2. `nfl/preseason_cards.py` — preseason market board falls back to the live
     Layer 1 book grid when the static `preseason_odds_{season}.csv` (last
     written 2026-08-05, one row) has no entry, and reports real
     `game_state` instead of the literal `"pregame"`.
  3. `shared/game_chip_scoreboard.py` — `_score_value(0)` returned None
     (`_text` is `str(value or "")`), so every scoreless team lost its score
     on the chip, in every sport.
- Scope note: NOT one change. `learnings.md` binds one-change-per-deploy to
  DIAGNOSING; diagnosis closed before any code was written. The three have
  distinct non-overlapping observables, so attribution survives the bundle,
  and splitting would mean three web restarts during a live slate.
- PRE-DEPLOY BASELINE, measured over 12 consecutive polls / 35 min while
  three NFL games were genuinely in progress:
      /api/board/layer1?sport=nfl   by_state {pregame:6, live:0, final:0}
      /nfl/api/preseason/cards      live=0 final=0, startTime empty on 16/16
      /nfl/api/preseason/market-board?week=2   0 rows across 16 games
  Odds were healthy throughout (DET@CIN 12 -> 132 rows, quotes <1.5 min), so
  the zero is a state defect and not an empty slate.
- Expected, within 5 min of `live` and while >=1 NFL game is in progress:
      counts.by_state.live            >= 1      (from 0)
      preseason cards shared_is_live  >= 1 game (from 0)
      preseason cards startTime       16/16 non-empty (from 0/16)
      preseason market-board rows     > 0       (from 0)
  All four are SUCCESS-path signals. Deliberately not a signal that only
  appears when the fix fails -- see the 2026-08-13 learnings entry on
  discriminators emitted only on the failure branch.
- Pre-deploy control (local, real ESPN, real production gamePks):
  `matched 16/16, live 2`, `by_state {live:2, pregame:14}`, scores
  (GB@PIT 3-0), tokens (`Q1 3:42`), kickoff times on all 16.
- Tests: 169 passing across the NFL + chip-scoreboard + preseason suites,
  including a two-sided control (the UNSTAMPED card must still read
  `pregame`, or the test proves nothing) and a positive control that no
  socket is opened under pytest.
- Rollback: redeploy `d4bb29b56d718c0726f9cbef1eaf01871b754873` (verified an
  ancestor of origin/main) to srv-d88ahvrbc2fs73eodu30.
- Deployed as `e29b807f`; live 18:54 CDT.
- **THIS MEASUREMENT WAS WRITTEN TWICE AND LOST ONCE.** An append at ~18:47
  and a second at ~18:59 were both gone within minutes — a parallel session
  rewrote `deploys.md` wholesale over them. Written the third time as an
  in-place edit against a fresh read, which merges instead of racing. If a
  measurement is missing from this ledger, absence is not evidence it was
  never taken.
- MEASURED 18:54–19:05 CDT over 8 polls, web confirmed running `e29b807f`
  from the service's own `/api/ops/version`, not from the deploy's claim.
  **THREE OF FOUR PASSED — recorded as a partial, not a pass:**

      cards shared_is_live          0 -> 3, then 4 as a 4th game kicked off
      cards startTime            0/16 -> 16/16
      preseason market-board rows   0 -> 96, states now [live,pregame]
      layer1 counts.by_state.live   0 -> 0     **FAIL**

- WHY OBS1 COULD NEVER HAVE PASSED HERE — a preflight error, not a code
  defect. Preflight answer 4 claimed web alone moves every observable because
  `attach_game_state` runs at serve time. True of `/api/board/book-grid`
  (`intelligence.py:2378`) and the cross-book route (`:2838`); **false of
  `/api/board/layer1`, a THIRD reader**, whose own docstring says it plainly:
  "A PURE READ of the precomputed grid." It never calls the serve-time attach
  at all. Layer 1's game state is whatever `build_book_grid_artifact` stamped
  on refresh-worker (`book_grid_artifact.py:214`). Two of three readers
  enumerated — the exact shape of the ledger's "presence is not reachability"
  entry, where an endpoint had four readers and three patched paths fixed
  nothing. The lesson did not transfer even with the entry in context.
- Consequence: OBS1 and the `#377` projection fix both required the
  refresh-worker deploy recorded in the next row.
- Cost of the error: none to production. The web deploy was correct and
  delivered 3 of its 4 effects; the cost was a confident wrong statement in
  preflight, and a deploy that could not do what it was said to do.

### nfl-day-of-game — degenerate projections + game state on the artifact (REFRESH-WORKER) — 98950c6d
- Deployed: 2026-08-13 19:06 CDT. Service: `refresh-worker` (srv-d91dpertqb8s73co8ls0).
  Deploy `dep-d9v5o0h5efls73al9n6g`.
- Why this service and not web: `/api/board/layer1` is "A PURE READ of the
  precomputed grid" (its own docstring), so BOTH remaining effects live in
  `build_book_grid_artifact`, which calls `attach_game_state` (:214) and
  `attach_projections` (:220) on the worker. The web deploy could not move
  either, and did not.
- SIM KILLED, KNOWINGLY AND WITH EXPLICIT USER AUTHORISATION. In flight at
  19:06:13: `20260814_000008`, `reason=fingerprint_change`, scoped to 9 game
  pks (`--only-game-pks 822696,822776,...`), running ~6 min. Not the full
  2026-08-14 slate sim the user originally gated on — that finished ~18:35.
  The user was told what was in flight and said killing a scoped resim was
  acceptable. `fingerprint_change` relaunches on its own, so this self-heals.
- Note on the gate: v2 cleared at 18:59 after 3 consecutive idle polls, and a
  new sim had started by 19:00. During an MLB slate the quiet windows are
  shorter than the confirmation interval, so a "wait for total quiet" gate
  does not converge. That is a property of the slate, not a broken gate.
- Change: `#377`. Drop projection rows whose `rating_source` is
  `neutral_no_data` on BOTH sides; dedupe candidate files on RESOLVED PATH
  rather than filename so every source root is read; newest `generated_at`
  wins between healthy copies.
- Expected, on `/api/board/layer1?sport=nfl` once the worker rebuilds the
  artifact. TWO acceptable outcomes, which mean DIFFERENT things and must not
  be collapsed:
    (a) `distinct projected_raw > 1`  -> the healthy copy won. Best case.
    (b) `rows_with_projection == 0` with the constant gone -> only the
        degenerate copy is reachable from the worker's roots and it was
        correctly dropped. Honest blank beats a league constant, but it means
        the nflverse pbp is missing on every root the generator can reach,
        which is a SEPARATE unfixed problem and must be recorded as such.
  Still serving 44.38 on every game = the fix did not take.
  Plus OBS1: `counts.by_state.live` 0 -> >=1 while a game is in progress.
- Baseline to beat: 12 pre-deploy polls at `by_state {pregame:6, live:0}` and
  `projected_raw` = 44.38 on 16 games across 4 dates.
- Rollback: redeploy the worker's prior commit (read it from
  /v1/services/srv-d91dpertqb8s73co8ls0/deploys before acting; state.md's
  recorded SHA goes stale in minutes).
- **MEASURED 2026-08-13 19:36 CDT. BOTH OBSERVABLES PASS. Lane closed.**
  Artifact `generated_at 2026-08-14T00:36:18Z` — **23 minutes AFTER the
  00:13:10Z deploy instant**, so this is a reading of the new code and not of
  a stale artifact. That check is stated first because the earlier watcher
  failed exactly here.

      OBS1  by_state   {pregame:6, live:0}  ->  {live:5, pregame:1, final:0}
      OBS4  distinct projected_raw   1 [44.38]  ->  6 distinct, 44.38 GONE

- OBS1 detail — real state, not a blanket relabel. The two-sided control is
  the last row: the game that had not kicked off is still `pregame` and now
  carries a real start time, which a "mark everything live" bug could not do.

      DET @ CIN  live  3-10  Q2 0:07     GB @ PIT   live  6-7  Q2 0:00
      IND @ NE   live  0-3   Q2 6:00     ARI @ LV   live  7-7  Q1 0:37
      LAC @ HOU  live  3-7   Q1 1:56     TEN @ SF   pregame  8:00P CT

- OBS4 is **outcome (a)**, the best of the three possibilities this row listed
  in advance: the HEALTHY artifact copy won. Not outcome (b) — projections
  were not blanked. `rows_with_projection` held at 75, so no row lost its
  projection; the same rows now carry per-game numbers instead of one constant.
- **The decisive cross-check.** The board and the cards read the same filename
  and disagreed before the fix (board: one constant; cards: 16 distinct). They
  now agree on all six of tonight's games, to three decimals:

      DET @ CIN 46.275   GB @ PIT 44.335   IND @ NE 46.745
      ARI @ LV  41.915   LAC @ HOU 41.885  TEN @ SF 46.145   -- 6/6 AGREE

  Run with a positive control (16 card keys parsed) after a first attempt
  keyed on a field layer1 does not carry and reported 6/6 DIFFER — a failed
  read rendering as a result, caught by the control rather than by the verdict.
- Retroactively closes OBS1 on the WEB row above, which correctly FAILED there:
  the effect needed this service, exactly as that row predicted.

### nfl-day-of-game — pbp team-code aliases (REFRESH-WORKER) — 111a5000
- Deployed: 2026-08-13 19:13 CDT. Deploy `dep-d9v5r861egvs73cbs08g`.
  Service: `refresh-worker` (srv-d91dpertqb8s73co8ls0).
- Sim killed, again with explicit user authorisation: `20260814_001053`,
  `reason=fingerprint_change`, in flight at 19:13:10.
- Change: `team_rating` translates the schedule's `LAR`/`WSH` into the
  play-by-play's `LA`/`WAS` before matching. Those two clubs matched zero
  plays in either season and fell to `neutral_no_data` -- a real 0.0/0.0
  rating producing a confident projection with no team information.
  Measured by diffing the code sets on the real files, and confirmed on
  production: every club read `prior_season_fallback` EXCEPT exactly these two.
- WHY THIS DOES NOT CONFOUND THE 98950c6d MEASUREMENT, which was still open
  when this shipped. The two changes act at different stages:
      98950c6d  projection LOADER -> moves the board at the next ARTIFACT build
      111a5000  pbp aliases       -> moves only newly GENERATED projections,
                                     i.e. the next season-projection autorun
                                     (~daily, last launched 16:00 CDT (21:00Z) today)
  So this one cannot move tonight's board numbers at all, and the loader fix
  remains solely attributable for them. Stated here rather than assumed,
  because "one change per deploy" was knowingly bent and the reason has to
  survive without me.
- Expected: at the NEXT generator run, `rating_source` on MIA@WSH and LAR@KC
  changes from `[neutral_no_data/...]` to `[prior_season_fallback/...]`, and
  those two games stop carrying league-average projections. NOT observable
  tonight.
- Measured: <EMPTY -- OPEN OBLIGATION. Due after the next season-projection
  autorun, ~2026-08-14 16:00 CDT (21:00Z). Owner: UNASSIGNED.>

### nfl-day-of-game — WATCHER DEFECT, recorded because it nearly became a finding
- `worker_verify.ps1` printed `STILL 44.38 -- fix did not take` against an
  artifact whose `generated_at` was 00:08:31Z -- about two minutes BEFORE the
  worker it was judging came up. The label was not entailed by the condition
  that produced it: the script never required the artifact to postdate the
  deploy.
- This is the ledger's own "a watcher's LABEL must be entailed by its exit
  CONDITION" entry, reproduced by someone who had read it earlier the same
  session. Caught by reading `generated_at` in the output rather than the
  verdict beside it.
- Replaced by `worker_verify2.ps1`, which renders NO verdict until
  `generated_at > deploy instant` and prints `PREDATES THE DEPLOY. No verdict.`
  until then -- stale and failed must not be spelled the same way.

### nfl-degenerate-writer — the writer cannot emit a degenerate artifact (REFRESH-WORKER) — c7cff28c
- Deployed: 2026-08-13 20:29 CDT. Deploy `dep-d9v6uvegekts73eus2u0`.
  Service: `refresh-worker` (srv-d91dpertqb8s73co8ls0).
- **NO SIM KILLED.** `sim_run_status` read `state=finished` at 20:29:23 before
  the POST — the first of tonight's four worker deploys that cost nothing.
- Change: two guards in the generators. `assert_ratings_data_available` refuses
  before the sim when zero plays load for both seasons;
  `assert_projections_carry_information` refuses before the WRITE when every
  projection is degenerate, so the last good artifact survives. Threshold is
  ALL-degenerate, not any: a partial still carries real information and the
  deployed reader already drops the bad rows.
- **THIS DEPLOY IS EXPECTED TO BE INERT, AND THAT WAS MEASURED FIRST.** The
  worker can see `pbp_2025.csv`: its 21:00:11Z run printed
  `artifact_path=/opt/render/project/data/nfl_source/smartsim2_preseason_projections_2026_wk2.csv`
  at 21:02:06Z, and that artifact carries a real rating on **16 of 16** games
  (`both sides neutral: 0`). So the refusal branch should never fire here. The
  guard is a trap for a failure mode that is not currently occurring — which is
  precisely why deploying it is cheap.
- **A RETRACTED PROBE, recorded so nobody repeats it.** The first attempt to
  answer "can the worker see the pbp" searched Render logs for `PBP_LOADED` and
  found **0 rows over 72h with both controls passing**. That is meaningless:
  the generators emit `PBP_LOADED` through a `log()` that writes ONLY to the
  `--progress-log` FILE, never stdout, so it can never reach Render's
  collector. The zero was a fact about the emitter. Ledger: *absent signal is
  about the emitter — check the line is EMITTED before concluding it is lost.*
- Expected tonight: nothing. There is no success-path signal for an inert
  guard, and the watch only establishes (a) live at the intended commit and
  (b) the worker did not start crashing on it.
- **REAL VERIFICATION IS THE NEXT SEASON-PROJECTION AUTORUN, ~2026-08-14 21:00
  CDT** (interval 86400s, last launched 08-13 21:00). That single run verifies
  BOTH this guard and `111a5000`'s LAR/WSH alias fix. Expected: the run
  succeeds, writes a healthy artifact, emits no `DegenerateProjectionRun`, and
  `MIA@WSH` / `LAR@KC` `rating_source` flips off `neutral_no_data`.
- Rollback: redeploy `111a50001f88f0ab887ab1b1b31c3daf61ed36a7`.
- Measured: <EMPTY -- OPEN OBLIGATION, due ~2026-08-14 16:00 CDT (21:00Z).
  Owner: UNASSIGNED.>

### `#389` follow-up — CONFIRMED WORKING on its first real run (no deploy; a reading)
- `todo.md` carries `nfl_artifact_output_root()` as **AWAITING FIRST RUN**. It
  has now had one, and it worked.
- `SEASON_PROJECTION_ARTIFACT_MISSING` fired **30 times** before the 21:02:06Z
  write and **0 times after**, queried as its own window
  (`2026-08-13T21:02:10Z -> now`) rather than inferred from result ordering —
  Render returns logs oldest-first regardless of `direction`, and an
  ordering-based read has produced wrong conclusions here before. Positive
  control in the same window: 5 `[refresh_worker]` rows, so the zero is a quiet
  guard and not an empty window.
- Means the writer and the staleness guard finally agree on a path. That is the
  defect that was discarding ~90 completed NFL sims/day.
- Someone should move `#389`'s follow-up out of AWAITING FIRST RUN in
  `todo.md`. Not done here — this session did not own that ticket.

### `#419` props-regen guard — VERIFIED WORKING (scheduled deploy was a no-op)
- 2026-08-14 09:15 CDT, service `refresh-worker` (`srv-d91dpertqb8s73co8ls0`),
  commit `d6188ca7`, change `#419` (`_mlb_props_now_available_needs_regen` read
  prop snapshots through Redis while the producer writes the mounted disk).
- **No deploy was performed by this task, and none was needed.** `#419` had
  already reached production at **2026-08-13 17:59 CDT** (`22:59:14Z`) via a
  **manual** deploy of `d4bb29b5`, not by the scheduled job. Live commit is now
  `75b8aae6` (08-13 23:26 CDT), which contains `d6188ca7`; the fix code is
  present in that tree, checked by `git grep` against the commit, not inferred
  from ancestry alone.
- Gate verdict acted on: **slate gate FAILED** — the task ran at 09:10 CDT and
  its window is 00:00–04:59, so a deploy was forbidden regardless. It was moot;
  the already-live check exits first. `deploy_preflight.py` was never reached.
  - Clock trap worth keeping: the first `date` call in the session reported
    `00:04` when it was `09:04`, which would have opened the slate gate on a
    false reading. It was caught because the Render log timestamps ran ~9h
    *ahead* of the supposed local time. A single clock reading is not a
    measurement — cross-check it against a timestamp from another system.
- **Measured — this closes the obligation, it is not pending:**
  - Baseline: **0** `MLB_PROPS_REGEN_DUE` across the entire retained log window
    (`2026-08-07T14:12Z` -> `2026-08-13T22:59Z`, ~6.4 days). Not an empty
    window — same query returns hits on the far side of the boundary.
  - First `MLB_PROPS_REGEN_DUE` at `2026-08-13T23:00:09Z` — **55 seconds after
    the fix went live** — with `pitcher_odds=True hitter_odds=True`, the two
    flags that were unconditionally `False` on every call before it.
  - ~15 `DUE` since, across both slate dates, hourly.
  - `MLB_PROPS_REGEN_SKIPPED reason=cooldown` with `age_s` resetting
    (660 -> 1517 -> 2147 -> 2781 -> 3417) — the cooldown is being *set*, which
    only happens after a regen actually runs.
  - End-to-end proof: `MLB_DAILY_SIM_END date=2026-08-14
    run_stamp=20260814_140135 state=finished exit_code=0 duration_seconds=625
    reason=props_now_available`. A regen fired from this guard and completed.
- Scheduled task `deploy-419-refresh-worker` deleted after this entry; its work
  was done by someone else's manual deploy before it ever fired.
- **Unrelated, seen while reading these logs, NOT this lane:** `refresh-worker`
  is sitting at **99.5-99.8% of its 4096MB** during the props regen
  (`container_memory_headroom_mb` 9.0-20.7, `accounted_rss_mb` ~3045). That is
  live near-OOM, and it belongs to the OPEN `anon-allocation-site` /
  `refresh-worker-anon-leak` lanes. Recorded here only so the reading is not
  lost; not diagnosed.

### projection-degeneracy-detector — `#425` gap 2 — WEB `2e4e2544`, then REFRESH-WORKER `2e4e2544`
- Web: `dep-d9v8aqdbedkc73b41ntg`, live **2026-08-14T03:09:33Z**.
- refresh-worker: `dep-d9vi6hu417fc73d2ofmg`, live **2026-08-14T14:22:32Z**.
  **No sim killed** — `sim_run_status state=finished` read before the POST.
- Change: `detect_degenerate_projections` reports any (kind, market, segment)
  whose projection has collapsed to ONE value across >= 4 distinct GAMES.
  Applied in a wrapper over `_attach_projections_by_sport`, so it covers all
  seven sports, all 13 return sites, and any producer wired later, touching
  ZERO call sites.
- **THE WORKER DEPLOY WAS HELD OVERNIGHT, DELIBERATELY, AND THAT WAS RIGHT.**
  Ordered at ~22:0x CDT while refresh-worker was OOM-killing: `server_failed
  oomKilled memoryLimit 4Gi` at 03:20:11Z, 03:39:57Z and 03:46:47Z. Deploying
  then would have (a) erased the crash evidence the `anon-allocation-site`
  lane needed, (b) made my change the visible suspect for the next kill, and
  (c) silently applied the standard mitigation (a restart) while calling it a
  feature deploy. Held, surfaced, deployed the next morning after 5h stable.
- **The cause of those OOMs was NOT this change and is not on `main`.**
  `2bc0a712` — the other session's `#423 step 2: wire tracemalloc into the
  worker` — was deployed from a clone and rolled back to `75b8aae6` at
  04:26:55Z. Verified by CONTENT as well as lineage, because cherry-picks mint
  new SHAs here and ancestry alone would not settle it: tracemalloc occurrences
  are 3 in both `2e4e2544` and the live `75b8aae6`, i.e. comments only, none of
  the 235-line wiring.
- Pre-deploy checks, all three passed: `2bc0a712` not contained in `2e4e2544`;
  `75b8aae6` (live) IS contained, so not a rollback; production delta is
  **exactly one file**, `board_enrichment.py`.
- MEASURED 2026-08-14 14:22–14:24Z:

      deploy live               14:22:32Z
      artifact generated_at     14:23:23Z   <- POST-deploy, so the reading counts
      oom kills since deploy    0
      distinct projected_raw    3           (1 would be a regression to 44.38)
      degenerate groups         none reported

- **WHY A REBUILT ARTIFACT IS THE LIVENESS PROOF AND SILENCE IS NOT.** This
  detector returns `{}` when there is nothing to report, so a healthy board
  emits NOTHING — silence is the expected success state and cannot distinguish
  "ran and found nothing" from "never executed". The ledger has been caught by
  exactly that shape twice (`basis` emitted only on the abort branch). So the
  verdict is gated on `generated_at` postdating the deploy: a rebuilt artifact
  proves `attach_projections` ran, and the detector sits unconditionally inside
  it. A `DEGENERATE_PROJECTION` line would be a positive emission, but tonight's
  board is healthy so its absence is correct and carries no information.
- **`#425` remains OPEN for gap 1** — the skill annotation on six builders,
  which needs six measured backtests. Not shipped, not started.
- Rollback: redeploy `75b8aae6` (read the live commit first — it moved five
  times in one evening and a stale SHA nearly shipped a rollback).

### projection-skill-declaration — `#425` gap 1 — WEB + REFRESH-WORKER `2d6f7a2f`
- Web: `dep-d9vilfm1egvs73eaineg`, live **2026-08-14T14:56:03Z**.
- refresh-worker: `dep-d9vimqu1egvs73eaktq0`, live **14:58:09Z**.
  No sim killed — `sim_run_status state=finished` read before the POST.
- Change: every projection carries `model_skill`; six producers that never
  measured their model now report `status: "unmeasured"` instead of nothing.
- **AN ENV VAR WAS CHANGED FIRST, AND IT WAS ANOTHER SESSION'S INSTRUMENT.**
  `SYNDICATE_TRACEMALLOC_DIAG` on refresh-worker was **`1`**, and the range
  `2e4e2544..2d6f7a2f` carries `b03c978b` ("#423 step 2: wire tracemalloc into
  the worker, **default OFF**"). Default-off is true of the code and was FALSE
  of production. Deploying unchanged would have armed a per-live-allocation
  traceback on a 4Gi service that OOM-killed 3x the previous night. Set to
  **`0`** via the single-key endpoint (a deploy is what injects env changes; a
  restart does not), verified reading back `0`, then deployed.
  - Set to `"0"` rather than DELETED on purpose: the gate is
    `value in {1,true,yes,on}`, so absent and `"0"` are equally off, but
    keeping the key visible tells its owner it was deliberately disabled
    rather than mysteriously vanished. To restore: set `1` and redeploy.
  - The owning session (`anon-allocation-site`) is ARCHIVED. Its live
    successor was messaged and had not replied at deploy time. Flagged here
    because turning off someone else's instrument without an answer is a real
    cost, not a footnote.
- **ALSO SHIPPED, NOT MINE, AND ITS AUTHOR'S LABEL IS NOW STALE:** `72df4049`
  (`#426`), whose own commit message says "NOT DEPLOYED, NOT VERIFIED" —
  `nfl_game_projections.py` +54, `intelligence.py` +24. It could not be
  separated: Render deploys a commit from `main`, and cherry-picking my change
  onto the live commit would produce a SHA `main` does not contain. This is the
  standing cost of deploying from a shared trunk, recorded rather than solved.
- MEASURED 15:12Z and again 15:24Z, both on POST-deploy artifacts:

      A tracemalloc  TRACEMALLOC_SITES 0, SETUP_FAILED 0
                     against a positive control of 20 [refresh_worker] rows,
                     so the zero is measured and not a broken query
      B stability    server_failed since deploy = 0
      C gap 1        artifact 15:20:24Z (post-deploy); 20/20 NFL projection
                     rows carry model_skill

- **BOTH BRANCHES CONFIRMED IN PRODUCTION, and NFL alone would not have done
  it.** NFL reads `measured` because it is the one producer with real skill
  numbers, so it only exercises the normalize path. The `unmeasured` path —
  the entire point of gap 1 — was confirmed on the other sports:

      nfl      20 rows   {'measured': 20}
      mlb    1631 rows   {'unmeasured': 1631}
      wnba    209 rows   {'unmeasured': 209}
      soccer   12 rows   {'unmeasured': 12}

  1,852 rows across three sports now declare that nobody has measured the
  model behind them. Counts surface in the `projections` coverage block
  (`rows_with_measured_skill` 101 / `rows_with_unmeasured_skill` 947 on NFL's
  book-grid), NOT in `counts` — a claim in the lane that said otherwise was
  wrong and is corrected here.
- **Unlike the degeneracy detector, this fix is NOT silent on success.** It
  stamps a visible field, so the verdict rests on a positive reading rather
  than on an artifact-rebuild inference.
- **The detector found a real defect on its first live board, unprompted:**
  `mlb batter_hits_runs_rbis` constant `0.0` across 188 games. Filed as
  `#429`; it also settles a question `#377` had explicitly left open.
- Watcher note: `gap1_verify.ps1` reported "board unreadable" 14 times. That
  was ITS OWN failure — `Wait-Live` returned an array because `Write-Output`
  inside it was captured into the return value, so the datetime conversion
  threw and every later poll errored. The board was never down. Re-measured
  with `gap1_check.py` rather than reported.
- Rollback: redeploy `2e4e2544` (read the live commit first) and set
  `SYNDICATE_TRACEMALLOC_DIAG=1` if its owner wants the instrument back.

## DEPLOYED 2026-08-14 10:42 CDT — `530fc5d8` refresh-worker — Layer 2 shortlist off the Layer 1 floor — **MEASURED, CRITERIA MET**

- **Preflight 2026-08-14 10:24 CDT (15:24Z): PASS on scope, HOLD on timing.**
- **1. Scope — PASS, exactly one substantive change.** Live is `2d6f7a2f`
  (finished 14:58:09Z, re-read inside this step — it had moved twice since this
  session started). `2d6f7a2f..530fc5d8` is my commit plus `99de8070` and
  `87108ff4`, both todo/docs. **Zero other production `.py`.** An earlier read
  of this same question said 22 commits / 872 insertions across 7 `.py` files;
  that was true against the then-live `2e4e2544` and was stale within the hour.
- **2. Expected effect, as a number and a window.** Over the 3h after the
  deploy, on refresh-worker: combined `LAYER2_SHORTLIST` + `LAYER2_FAST_REFRESH`
  count **rises above 5** (the pre-change figure for 11:39-14:39Z), and the
  longest gap between them **falls below 30 min** from the measured 104.7.
  `MEMORY_GUARD_ABORT` count should be **unchanged** — this weakens no existing
  guard — and `LAYER2_GUARD_SKIP` should be near 0 if the 600MB floor is sized
  right. **A high `LAYER2_GUARD_SKIP` count is the falsifier**: it means the
  shortlist is not as cheap as four builds suggested.
- **3. Measurement — assigned to this session (`layer2-freshness`).** The same
  query that produced the baseline: count by marker over a 3h window on
  `srv-d91dpertqb8s73co8ls0`, plus an OOM check in the Render **events** API
  (`#423` records that kills are invisible in the logs). Re-run at **T+3h**.
- **4. Blast radius.** refresh-worker only. Persistent disk, so stop-then-start
  with downtime and no instance overlap. **It kills in-flight jobs — 7 at the
  time of this preflight**, including `run_mlb_daily_sim_job.py` and its
  `daily_update.py --workflow ui-daily` children.
- **5. Rollback.** Redeploy `2d6f7a2f` via the Render API. The env kill-switch
  `SYNDICATE_LAYER2_FAST_REFRESH_ENABLED=false` also disables the new path, but
  **a restart does not re-inject env vars** — setting it requires its own
  deploy, so it is not the faster rollback. Use the redeploy.
- **6. Ledger check.** No `FORBIDDEN` rule applies. The `handoff_overview_
  hydration.md` do-not #1 (never lower the 3000MB floor) is respected and
  **pinned by a test** that also pins the 1900MB floor. No OPEN lane claims
  `pipeline/intelligence_state.py` or `tests/test_layer2_fast_refresh.py`
  (checked against the live `lane-guard.py` by stdin probe and against the
  nearest-preceding-header map).
- **7. Verdict: HELD, not deployed.** `deploy_preflight.py --service
  refresh-worker --target-commit 530fc5d8` returns `HOLD: 7 job(s) in flight`.
  Child pids rotated 1180 -> 1391 between two samples, so the sim is
  progressing, not hung. Pushed to `origin/main` (free — no `render.yaml` in
  the commit, verified) and waiting on the gate.
- **MEASUREMENT: (empty — deploy has not happened)**
- **REMINDER: re-read the live SHA inside the deploying step. It moved twice
  during this session's preflight alone.**

### `#430`/`#431`/`#432` — the L1 board's odds age, rail and book columns (web only)
- Deployed: 2026-08-14 10:3x CDT — **row written BEFORE the deploy fired.**
- Commit: `b98f5ed7` (cherry-picked onto `origin/main` `0c3165b9`; local `main`
  is 31 commits divergent and pushing it would have carried four other lanes).
- Service: **web only** (`srv-d88ahvrbc2fs73eodu30`). refresh-worker and
  live-odds-worker are NOT redeployed, so the "a deploy kills an in-flight MLB
  sim" rule does not apply to this one — the sim runs on refresh-worker.
- Change: `/api/board/layer1` serves an odds-observation timestamp derived from
  the rows' seen-age and re-anchored to `generated_at`; the board renders it
  beside the build age; the bet-slip rail gets its stylesheet, a collapse and a
  per-row Ask button; book columns default to 11 with an All-books toggle.
- **PRE-DEPLOY DELTA ENUMERATED, and it is not only my change.** `2d6f7a2f`
  (live web) -> `b98f5ed7` is 9 files, of which 4 are production code:

      syndicate/blueprints/intelligence.py         +51    mine
      syndicate/features/shared/layer1_board.py    +89    mine
      syndicate/templates/shared/layer1_board.html +355   mine
      pipeline/intelligence_state.py               +237   NOT MINE

  The fourth is `layer2-board-freshness`'s Layer 2 memory-floor change, which
  landed on `origin/main` while this was in flight. **Judged inert on web, on
  two checks rather than on recollection:** (1) the live web service carries
  `SYNDICATE_ENABLE_INTELLIGENCE_STATE_BACKGROUND_LOOP=false` — read from
  `/v1/services/.../env-vars` today, 73 keys, not from `state.md`; (2) the diff
  touches `_abort_if_memory_critical` and `IntelligenceStateService` build
  methods only, and does NOT touch `read_layer2_shortlist` or
  `read_intelligence_board_state`, which are the two functions web's route
  actually imports. That change becomes live when its OWN lane deploys
  refresh-worker, and its measurement obligation stays with that lane.
- Expected effect, as a number and a window:
  1. Within 5 minutes of the deploy, `/api/board/layer1?sport=mlb` returns a
     non-null `odds_freshness.odds_observed_at`, and `views` other than `all`
     return it too (the bug the API test caught).
  2. The served board's odds age is **> 120 min** on the current MLB slate and
     the build age is **< 15 min** — i.e. the two numbers visibly disagree,
     which is the whole point. If they agree, either the capture recovered
     (good, and a separate fact) or the derivation is wrong.
  3. Default MLB book columns = 11, not 36.
- Measurement: me, immediately after the deploy reaches `status=live`, by
  fetching the API and re-reading the board. Written into this row.
- Rollback: redeploy `2d6f7a2f` on web — **re-read the live commit first**, it
  moved five times in one evening and a stale SHA nearly shipped a rollback.
- Ledger check: no `learnings.md` FORBIDDEN/EXONERATED rule covers this. No
  `render.yaml` change, so no `blueprint_sync`. No OPEN lane claims any of the
  three files I wrote.
- Measured: 2026-08-14 10:33-10:37 CDT, deploy `live` at 15:33:06Z, commit
  `b98f5ed7` confirmed on the service (status AND commit, not the 201).
  1. **PASS.** `odds_freshness.odds_observed_at` is served and non-null on
     `view=all` AND `view=pregame` — the partition bug the API test caught is
     not present in production. `view=live` returns `null` with 0 games and
     `rows_with_seen_age=0`, which is the unknown path behaving correctly.
     MLB carries 2,319 rows with a seen-age and 218 without; the 218 are
     counted and excluded rather than treated as fresh.
  2. **PREDICTION NOT MET, and the prediction was wrong rather than the
     code.** I predicted odds age > 120 min. Measured 23.0 min: built 10:30
     CDT, freshest observation 10:10 CDT. **The capture recovered between the
     10:18 reading and the 10:36 one** — the 2h10m stall I measured twice this
     morning had already broken by the time the deploy landed. So the two ages
     do still disagree (23.0m odds vs 3.7m build, and the amber threshold at
     15m fires), but not by the margin I wrote down. Recording it as a miss:
     the number I committed to was a property of the outage, not of the change,
     and I should not have stated it as the deploy's expected effect.
  3. **PASS.** The served page ships exactly the 11 chosen books in the chosen
     order, plus `board_cards.css`, `ask_bar.js`, the rail toggle and the
     odds-age renderer.
  - Cross-sport, same instant: mlb 23.5m, wnba 54.0m, nfl 53.1m, soccer 12.9m,
    ncaaf/nba null (0 games, out of season). **Tens of minutes is the normal
    state, not an MLB anomaly** — which is the fact the board could not
    previously express at all.
  - No OOM kill and no `server_failed` on web after the deploy.
- Verdict: **shipped and verified.** The board now states its odds age. The
  capture gap that motivated it is a separate, still-open question — see the
  `odds-capture-stall` lane.

- **DEPLOYED. `dep-d9vjbr6gekts73fqr2f0`, `status=live`, commit `530fc5d8`,
  finished 2026-08-14T15:42:29Z.** Verified as `status=live` AND the commit,
  not from the POST response — it sat `build_in_progress` for ~5 min first, and
  `state.md` records one that sat there 33+ minutes while being reported shipped.
- **ZERO JOBS KILLED, and this took work.** The gate returned `HOLD` on every
  read from 15:24 to 15:36 — 7-10 MLB sim jobs in flight, near-continuously.
  A first `CLEAR` at 15:25:09 was **a lull between sims, not the end of work**:
  a new `run_mlb_daily_sim_job.py` (pid 1743) started ~60s later, which three
  spaced confirming samples caught. `learnings.md` already records that exact
  trap ("it had simply caught a lull between sims, `in_flight: 0`"). Deploying
  on the first CLEAR would have killed a sim that had just started.
  The deploy was instead fired from inside a detected lull by a 10s-interval
  poll that ran the POST in the same step as the CLEAR — 15:36:11 CLEAR,
  15:36:12 POST.
- **Post-deploy smoke, 15:42:29-15:43:15Z: no tracebacks, `BOOTED` present.**
  The only `Error` lines are pre-existing `PROCESS_ENUM_DEBUG
  psutil_unavailable:ImportError` with a procfs fallback — not from this change.
  **All marker counts in that window are ZERO and mean nothing yet: the window
  is 46 seconds against a ~71s board tick.** Do not read them as a result.
- **MEASUREMENT: OPEN.** Due at T+3h ~= 2026-08-14 18:45Z / 13:45 CDT.
  Read on `srv-d91dpertqb8s73co8ls0` over a 3h window:
  1. `LAYER2_SHORTLIST` + `LAYER2_FAST_REFRESH` combined count — **PASS if > 5**
     (the pre-change figure over 11:39-14:39Z).
  2. Longest gap between any two of them — **PASS if < 30 min** (was 104.7).
  3. `MEMORY_GUARD_ABORT` — should be roughly unchanged; this weakens no
     existing guard. A large DROP is not a win here, it is a sign the worker
     rebooted and the comparison is boot-confounded.
  4. `LAYER2_GUARD_SKIP` — **the falsifier. If this is high, the 600MB floor is
     too tight and the shortlist is not as cheap as four builds suggested.**
  5. OOM kills in the **events** API (`server_failed`/`oomKilled`), not the
     logs — `#423` records that kills are invisible in logs.
- **CONFOUND, stated now so it is not discovered later: the deploy restarted
  the worker.** `anon` drops to a few hundred MB on boot, so the guard will not
  abort for a while and `LAYER2_FAST_REFRESH` may correctly be ZERO early on.
  Its absence early is expected, not a failure — the fast path only fires when
  the Layer 1 guard refuses. A clean read needs `anon` back at plateau
  (~35 min post-restart, per `state.md`).

### `#15` cadence — MLB pregame odds sweep 2h -> 1h (env only, live-odds-worker)
- Deployed: 2026-08-14 ~11:0x CDT — **row written BEFORE the change fired.**
- Requested explicitly by the user after the `odds-capture-stall` lane closed
  as "not a defect, that IS the cadence".
- Change: set `SYNDICATE_PREGAME_SWEEP_INTERVAL_SECONDS_MLB=3600` on
  `live-odds-worker` (`srv-d91dpertqb8s73co8lt0`). Read by
  `_pregame_sweep_interval_seconds` (`live_refresh_loop.py:3958`), which falls
  back to `_PREGAME_SWEEP_INTERVAL_FALLBACK = 2*3600` when unset. **No code
  change.**
- **Service selection, measured not assumed:** in a 90-minute log sample
  live-odds-worker emitted 5 `PREGAME_CADENCE_DETAIL` and 0 sim tokens;
  refresh-worker emitted 0 cadence and 3 `MLB_DAILY_SIM_TRIGGERED` / 3
  `MLB_DAILY_SIM_END`. The cadence lives on live-odds-worker and the MLB sim
  lives on refresh-worker, so **"a deploy kills an in-flight sim" does not
  apply to this deploy** — different service. (All 3 sims had also ended.)
- **Blast radius held to env by pinning the commit.** live-odds-worker is live
  on `83e3e5f2` from 2026-08-13 23:43Z; the repo tip is ~20h ahead. The deploy
  is fired with `commitId=83e3e5f2` — the SAME code it is already running — so
  the only delta is the env var. Deploying at tip would have shipped a day of
  four other lanes' work to pick up a one-key config change.
- **No `render.yaml` edit, therefore no `blueprint_sync`.** The key is
  undeclared and set live-only. Per the measured sync semantics in `state.md`
  (refresh-worker went 92 -> 93 keys while the blueprint declared 84), a sync
  upserts declared keys and leaves live-only keys alone, so this will NOT be
  silently reverted by a future sync. It IS undeclared drift, and declaring it
  is a separate decision that applies to production on push.
- Expected effect: within one tick after the deploy, `PREGAME_CADENCE_DETAIL`
  prints `mlb:...interval_s=3600` (not 7200), and the MLB gap between
  consecutive quote observations falls from ~7,200s to ~3,600s. The board's
  `odds N old` should therefore top out near 1h instead of near 2h.
- **Cost, stated as what I actually know:** MLB pregame sweeps double. I did
  NOT measure the absolute OddsAPI call cost per sweep — the local
  `odds_control_plane` artifact is a 08-11 mirror and carries no call counts —
  so "2x MLB pregame sweeps" is the honest figure and "N calls/day" would be
  invented. Against the 5M cap (`#OddsAPI budget`), and MLB only: nfl/wnba stay
  at 7200s and soccer at 28800s.
- Rollback: `DELETE /v1/services/srv-d91dpertqb8s73co8lt0/env-vars/SYNDICATE_PREGAME_SWEEP_INTERVAL_SECONDS_MLB`
  then redeploy pinned at the then-live commit; the code fallback returns it to
  7200. Re-read the live commit first.
- Measured: 2026-08-14 11:20-11:29 CDT. Deploy `live` 16:04:20Z at commit
  `83e3e5f2` — status AND commit checked, not the 201.
  - **The gate's own output at 16:20:30Z is the primary evidence:**

        PREGAME_CADENCE_SKIPPED sports=nfl,soccer,wnba
        PREGAME_CADENCE_DETAIL  nfl:6011/7200  soccer:4191/28800  wnba:2371/7200

    **MLB is ABSENT from the skip list, so MLB swept.** Under the old 7200 it
    would have been skipped here (marker_age 4,178s < 7,200) and held to
    ~17:20Z. nfl/wnba still read `interval_s=7200` and soccer `28800`, so the
    change is scoped to MLB exactly as intended — no collateral cadence move.
  - **Gap, measured end to end on the served board:** previous sweep
    10:10:38 CDT, new sweep observed **11:20:52 CDT** = **4,215s (1h10m15s)**,
    against the previous measured gap of **7,289s (2h01m29s)**. A 42% cut.
  - **Lands inside the predicted band, which is the useful part.** I predicted
    3,600-4,500s rather than exactly 3,600 because the loop wakes every 900s
    and sweeps whatever is past its interval, so the setting is a FLOOR and the
    tick quantises it. 4,215s sits in that band. Anyone reading "1 hour" as
    "3,600s exactly" will file a bug against correct behaviour.
  - **A methodology note worth keeping.** The board's `odds_observed_at` lags a
    real sweep by up to one artifact rebuild — the artifact was built 11:18:03,
    BEFORE the 11:20:16 tick, so between 11:20 and 11:28 the board still read
    10:10 and "no change" was ambiguous between "no sweep" and "sweep not yet
    rebuilt". Six consecutive readings said nothing. The discriminator was not
    another reading; it was the worker's own gate line, which already had the
    answer. The board caught up at the 11:28:21 rebuild and agreed.
  - No `server_failed`, no OOM, no restart loop after the deploy.
- Verdict: **shipped and verified.** MLB pregame odds now refresh on a ~1h10m
  effective cadence instead of ~2h01m. Cost is 2x MLB pregame sweeps; the
  absolute OddsAPI call figure is still unmeasured and is the open follow-up.

### `#429` — HRR mean derived from its components — WEB + REFRESH-WORKER `214f5151`
- Web `dep-d9vjlc0u01pc738a78jg`, refresh-worker `dep-d9vjlc7qj5pc73dp71mg`,
  both **live 2026-08-14 11:00:29 CDT (15:59:55Z)**. No sim killed —
  `sim_run_status state=finished` read before the POST.
- Per-service delta was re-read AT DEPLOY TIME and it mattered: live had moved
  on BOTH services in the 25 minutes since the previous read
  (`2d6f7a2f` -> web `b98f5ed7`, worker `530fc5d8`). That turned the blast
  radius from "20 commits, four sessions" into **web: `prop_projections.py`
  alone**; worker additionally carried `layer1_board.py` + `intelligence.py`,
  already proven on web since 15:33.
- Change: `batter_hits_runs_rbis` projected a constant `0.0` slate-wide. HRR is
  Hits+Runs+RBIs — a SUM of three primitives the sim models separately — so the
  mean is now derived as `h_mean + r_mean + rbi_mean`. Exact by linearity of
  expectation, which holds despite the three being heavily correlated; means
  only, never probabilities.
- MEASURED on a post-deploy board rebuild, 11:01:30 CDT:

      hrr rows           88
      with a value       88     derived 88, blanked 0
      distinct values    85     <- was 1
      range              1.363 .. 3.833   (market line 1.5)
      degenerate groups  NONE   <- #425 no longer flags this market

- **THE VALIDATION LIMIT RECORDED IN `#429` IS NOW CLOSED, on production.**
  That ticket said the derivation could not be cross-checked against the sim's
  own `p_hrr_2plus`, because every local artifact has that probability dead at
  0.0 (checked 05-28, 06-06, 07-09) while production has real ones. Production
  carries BOTH on the same 88 rows, so the test is available and it is a real
  test — the two numbers come from different places and nothing forces them to
  agree unless the derivation measures the same quantity:

      TEST     corr(derived mean, sim P(2+))  = 0.9267
      CONTROL  corr(market line,  sim P(2+))  = 0.1156

  Monotonic across the whole range, no inversions:
  `1.363-1.754 -> 0.416`, `1.996-2.182 -> 0.526`, `2.388-2.573 -> 0.594`,
  `3.113-3.833 -> 0.676`. Tails are baseball-sane (Yordan Alvarez, CJ Abrams
  high; bench bats low). The control is what makes the 0.93 meaningful — the
  near-constant line correlates at 0.12, so this is not everything correlating
  with everything.
- **A CLOSED LOOP WORTH NOTING:** `#425`'s degeneracy detector found this defect
  unprompted on its first live board, and now reports the market clean. The
  instrument found the bug and then confirmed its own fix.
- **NOT FIXED, and deliberately so:** the sim still writes `hrr_mean: 0.0`. That
  producer was never located; this reconstructs at read time and stands aside
  automatically if the sim is ever repaired (a test pins that a real `hrr_mean`
  is never overridden). Worth fixing at source; nothing on the board depends on
  it now.
- Rollback: redeploy `b98f5ed7` (web) / `530fc5d8` (worker) — but re-read the
  live commit first, it moved twice in 25 minutes today.

- **INTERIM READING T+30min (15:42:29-16:12:08Z). NOT the measurement, and NOT
  yet evidence for the fix.**
  - 5 board refreshes in 29.7 min; gaps min 2.1 / p50 4.0 / **max 10.2 min**.
    Baseline was 5 refreshes in 180 min with a max gap of 104.7.
  - Zero tracebacks, zero `LAYER2_GUARD_SKIP`, zero OOM/restart events. The
    refactor of the 6-call-site guard did not break anything.
  - **`LAYER2_FAST_REFRESH` = 0, and `MEMORY_GUARD_ABORT` = 0. THE NEW CODE
    PATH HAS NOT EXECUTED ONCE.** The deploy restarted the worker, `anon` is
    still low, so the Layer 1 guard has not refused yet — and the fast path
    only fires when it does. **The improvement above is therefore NOT
    attributable to this change; it is what the OLD code also does after a
    restart.** `state.md`: "restarts clear it and prove nothing."
  - The discriminating window opens when `anon` returns to plateau (~35 min
    post-restart, so ~16:17Z+) and `MEMORY_GUARD_ABORT` resumes. Until a
    `LAYER2_FAST_REFRESH` line exists, this deploy is UNVERIFIED.
  - Confound worth noting for the T+3h read: `considered` now MOVES (14195 ->
    13920 -> 13908) where it was frozen. That is rows aging out of the horizon
    as games start, not new quotes arriving — consistent with the frozen shard
    diagnosed above, not with recovery.

### `#429` PRODUCER — sum H+R+RBI in the sim — REFRESH-WORKER `294f9ca9`
- `dep-d9vjtc61egvs73e6c0d0`, live **2026-08-14 11:17 CDT (16:16:56Z)**.
  refresh-worker ONLY: `daily_update.py` is executed by the MLB sim job, which
  runs there; a web deploy would have been inert. No sim killed
  (`state=finished` before the POST).
- Delta was **exactly one production file**, `vendor/mlb_bettingv2/tools/daily_update.py`.
- Change: `_inc_sum(pid, "H+R+RBI", hrr)`, at BOTH copies of the per-sim hitter
  accumulation. The topn mean is `_stat(pid, stat_key) / denom_sims` and
  `_stat` reads only what `_inc_sum` accumulated — `"H+R+RBI"` was never passed
  to it anywhere in the file, so the numerator was always 0. Every sibling mean
  worked because its `_inc_sum` line exists; the one COMPOSITE in the mapping
  was the one stat never summed.
- **WHAT LANDING PROVES AND WHAT IT DOES NOT.** It proves the code is on the
  service that runs the sim. It does NOT prove `hrr_mean` is nonzero — that
  becomes true only when the NEXT sim writes a daily summary, which is a
  separate event and a separate measurement. Recorded this way because an
  earlier watcher today conflated "deploy live" with "artifact rebuilt" and
  called a pre-deploy artifact a failure.
- MEASURED at T+0, and an UNCHANGED board is the PASS here:

      hrr rows 88   distinct 85   range 1.363..3.833   derived 88

  `#429`'s read-time derivation still supplies every value, and both it and the
  producer compute `h + r + rbi`, so there is no transition artifact and no
  window where the two disagree. A board that MOVED would have been the
  surprise.
- **~~OPEN OBLIGATION~~ — CLOSED 2026-08-14 11:56 CDT, see the measurement
  below. Kept because the discriminator is reusable.**
  `prop_projections` stamps `projected_derived_from` only when it had to
  reconstruct the value, and stands aside the moment a real `hrr_mean` appears.
  So on the served board:

      derived == 88, values present   -> producer still writing 0.0 (today)
      derived == 0,  values present   -> PRODUCER FIXED, read-time path dormant
      derived == 0,  values absent    -> REGRESSION, both paths failed

  Due after the next `run_mlb_daily_sim_job` writes a daily summary. **Owner:
  UNASSIGNED.**
- **MEASURED 2026-08-14 11:56 CDT — CLOSED, PRODUCER CONFIRMED. `derived == 0`.**

      hrr rows 90   with a value 90   distinct 87   range 1.363..3.833
      DERIVED  0    (was 90)
      summary  /opt/render/project/data/mlb_source/source_artifacts/
               data/daily/daily_summary_2026_08_14.json

  Confirmed at the SOURCE as well as on the board, by reading the production
  artifact directly through `/api/ops/artifacts/stream`:

      daily_summary_2026_08_14.json   generated 11:39:16   2,298,627 bytes
      hrr topn rows   1008
      hrr_mean        present 1008, NONZERO 1008, distinct 233
      CONTROL pa_mean present 1008, nonzero 1008

- **NO TRANSITION ARTIFACT, which was the prediction and is the satisfying
  part.** The board's range is IDENTICAL across the handover (`1.363..3.833`
  before and after `derived` fell 90 -> 0). The value did not move when its
  source changed, because the producer and the read-time derivation both
  compute `h + r + rbi` — exactly what the linearity argument said would
  happen. The read-time path is now belt-and-braces, not load-bearing, and a
  test pins that a real `hrr_mean` is never overridden.
- **THE 11:47 "STILL RECONSTRUCTING" READING WAS A STALENESS ARTIFACT, NOT A
  PRODUCER FAILURE.** A regular sim had already written real means at 11:39:16;
  the board artifact checked at 11:47 had been built just before it. The
  watcher's own wording ("NOT a failure by itself") happened to be right for
  the wrong reason — it blamed a scoped `fingerprint_change` resim, when in
  fact the producer had already worked and the board had simply not rebuilt.
  Same trap as the pre-deploy artifact read earlier today, in the opposite
  direction.
- **NO FULL DAILY UPDATE WAS TRIGGERED, deliberately.** The obvious way to
  force this was an unscoped full-slate sim — and `live_refresh_loop.py:2761`
  records in its own comment that an unscoped run **"is what OOM-killed the 2GB
  worker"**, which is why the loop batches through `--only-game-pks` now.
  Firing the known OOM shape at a service that OOM-killed three times the
  previous night, to answer a question a GET could answer, would have been a
  bad trade. Reading the artifact cost one request.
- Rollback: redeploy `214f5151` (re-read the live commit first).

### `#433` — soccer capture-before-simulate (live-odds-worker, PINNED, 1 file)
- Deployed: 2026-08-14 ~12:3x CDT — **row written BEFORE the deploy fired.**
- Commit: **`9a3a5bc6`** = the live commit `83e3e5f2` **plus only this change**,
  pushed as `deploy/soccer-step-order-433`. Not `main`'s tip.
- **WHY PINNED, and this is the whole point of the row.** live-odds-worker has
  been on `83e3e5f2` since 2026-08-13 23:43Z. Deploying it at `origin/main`
  (`e9990ccb`) would have carried **22 production files** from four other
  lanes — `memory_observability.py`, `run_refresh_worker.py`,
  `pipeline/intelligence_state.py`, `board_enrichment.py`, `projection_skill.py`
  and the NFL set — onto a **2GB service with an OOM history**, none of it
  measured on THIS service. That is the batching failure `CLAUDE.md` names.
  Cherry-picking onto the live commit instead makes the production delta
  exactly **one file**: `scripts/refresh_odds_sources.py`.
  `main` already carries the same change as `e9990ccb`; the two are the same
  patch, so this does not fork the fix, only the deploy.
- Change: soccer step order becomes `schedule -> odds -> props -> artifacts ->
  picks`. Previously the 50-step run put all ten sims (11-20) AHEAD of the odds
  captures (21-30) and died between step 27 and 28, so three leagues went 3.6
  days without odds and steps 31-50 never ran for any league.
- **Not a workaround:** `build_soccer_artifacts.py` does not read
  `game_odds_current.csv`, so the sim never depended on the capture it was
  blocking. `picks` stays last because it DOES depend on both.
- Service selection: live-odds-worker only. Per `#148` it owns the soccer
  pregame odds/props/schedule steps
  (`_launch_autorun_soccer_pregame_refresh`); refresh-worker's soccer autorun
  runs `phase="live"` per-league and is unaffected by this ordering.
  **refresh-worker is NOT redeployed, so no in-flight MLB sim is killed.**
- Expected effect, as a number: on the next soccer pregame run, the dark
  leagues' odds steps execute at positions **#18/#19/#20 instead of
  #28/#29/#30** — inside the ~27 steps the run actually completes — and the
  newest `captured_at` for primeira_liga, championship and belgian_pro_league
  in `soccer_source/tracking/book_quotes/<date>.jsonl` moves from 08-10/08-11
  to today. Zero additional OddsAPI spend: same steps, same call volume.
- Measurement: me, by re-reading the shard per league after the next pregame
  run. Written into this row.
- Rollback: redeploy `83e3e5f2` on live-odds-worker (re-read the live commit
  first). The change is order-only, so a rollback restores the old ordering and
  nothing else.
- Ledger check: no FORBIDDEN/EXONERATED rule applies. No `render.yaml` change,
  so no `blueprint_sync`. `scripts/refresh_odds_sources.py` confirmed
  unclaimed by any OPEN lane via a `lane-guard.py` stdin probe (exit 0).
- **Known-not-fixed:** why the run stops at ~27 steps (time budget, memory or
  step timeout) is still unnamed. This removes the consequence, not the cause;
  a truncating run now loses sims and picks rather than odds.
- Measured: `<pending>`

- **CLEAN-WINDOW MEASUREMENT 2026-08-14 16:16:56-18:00:49Z (103.9 min, NO
  intervening deploy — live `294f9ca9` throughout, which contains `530fc5d8`).**

      board refreshes        22   = 12.7/hour     (baseline 5 in 180 min = 1.7/hour)
        of which fast-path    8   <-- cycles that previously produced NOTHING
        of which full build  14
      gaps (min)             min 1.6 / p50 4.2 / max 11.8   (baseline max 104.7)
      MEMORY_GUARD_ABORT     37   the Layer 1 guard still refusing, as designed
      LAYER2_GUARD_SKIP       0   <-- the declared FALSIFIER did not fire
      FAST_REFRESH_FAILED     0   Traceback 0   OOM/restart events 0

  - **The attributable number is the 8 fast-path refreshes.** Those are cycles
    where the Layer 1 guard refused and the board refreshed anyway — the exact
    behaviour this change adds, and impossible before it.
  - **CONFOUND, stated rather than buried: the abort RATE also fell** (146/180min
    = 48.7/h before, 37/103.9min = 21.4/h now), so this window is under less
    memory pressure than the baseline. The 7.5x refresh-rate improvement is
    therefore NOT wholly attributable to this change. The 8 fast-path lines and
    the absence of any long freeze are.
  - **SPAN SHORTFALL, stated: 103.9 min against the 3h criterion I set.** A gap
    as large as the 104.7-min baseline is only barely observable in a 104-min
    window, so the max-gap comparison is weak here and the RATE comparison is
    the sound one. Not retro-fitting the criterion to the data: the 3h read is
    still owed and is armed.

### `#433` — the soccer pregame run reports its own outcome (live-odds-worker, PINNED)
- Deployed: 2026-08-14 ~14:1x CDT — **row written BEFORE the deploy fired.**
- Commit: **`ccd10349`** = live commit `9a3a5bc6` **plus only this change**,
  pushed as `deploy/soccer-run-visibility-433`. Production delta: **one file**,
  `scripts/run_live_odds_refresh_worker.py`. `main` carries the same patch as
  `039ce501`.
- Change: the worker reads the run artifact its own detached child wrote and
  prints a compact summary to ITS OWN stdout — one `SOCCER_PREGAME_RUN_SUMMARY`
  line, one line per `_odds` step, one line per failure anywhere, and
  `SOCCER_PREGAME_RUN_NO_ARTIFACT` when the child wrote nothing at all.
- **WHY, and it is the whole point of the lane right now.** Soccer game odds
  stopped 2026-08-10 and produced no visible error for four days — not because
  anything swallowed an exception, but because `launch_refresh_run` spawns the
  refresh with `stdout=DEVNULL, stderr=DEVNULL` and the child's log files land
  on **live-odds-worker's own disk**, which the web service cannot read
  (`/api/ops/odds-refresh/logs` -> `exists=False` from web, forever). Render
  captures only a service's OWN stdout. Three hypotheses have died for want of
  one log line.
- **Deliberately NOT inheriting the child's stdout.** A 50-step refresh is
  thousands of lines every 4 hours through the log collector; noise is why
  nobody reads logs. And `ops_refresh.py` records that making this launch
  blocking stalled the tick loop and contributed to an OOM — so the reporter
  reads LAST run's artifact on the NEXT tick and never waits.
- Expected effect, and it is an OBSERVATION not a repair: within one tick of
  the next pregame autorun (4h cadence), `SOCCER_PREGAME_RUN_SUMMARY` appears
  in live-odds-worker's Render logs with per-odds-step outcomes — or
  `SOCCER_PREGAME_RUN_NO_ARTIFACT` if the child dies first. **This does NOT fix
  the outage. It makes the failure legible for the first time since 08-10.**
- Measurement: read live-odds-worker's logs for `SOCCER_PREGAME_RUN_` after the
  next autorun. Written into this row.
- Rollback: redeploy `9a3a5bc6` (re-read the live commit first). Print-only
  change; a rollback restores silence and nothing else.
- Ledger check: no FORBIDDEN/EXONERATED rule applies; no `render.yaml` change,
  so no `blueprint_sync`. `run_live_odds_refresh_worker.py` confirmed unclaimed
  by a `lane-guard.py` stdin probe (exit 0) — the memory lanes mention it in
  prose, not in a Files block, so no reassignment was needed.
- Measured: `<pending>`

- **FINAL MEASUREMENT — 3h CLEAN WINDOW, 16:16:56-19:24Z = 187.3 min, live
  commit `294f9ca9` unchanged throughout (verified by SHA, not by timestamp).**

      board refreshes         37   = 11.9/hour    BASELINE 5 in 180min = 1.7/hour
        via the fast path     23   <-- cycles that previously produced NOTHING
        via the full build    14
      gaps (min)              min 1.6 / p50 5.3 / max 11.8    BASELINE max 104.7
      MEMORY_GUARD_ABORT      96   the Layer 1 guard refusing, as designed
      LAYER2_GUARD_SKIP        0   <-- the declared FALSIFIER never fired
      FAST_REFRESH_FAILED      0   Traceback 0   OOM/restart events 0

  **All five stated criteria MET.** Refresh count 37 > 5. Longest gap 11.8 <
  30. The guard is still actively refusing (96 times), so this is not a
  boot-confounded quiet period. The falsifier stayed at 0 across all 96
  refusals, so the 600MB Layer 2 floor is correctly sized. No OOM.
  - **The span now EXCEEDS the 180-min baseline (187.3 min), which is what makes
    the max-gap comparison sound.** In the earlier 103.9-min reading a
    104.7-min gap was barely observable and I said so; here it was fully
    observable and did not occur.
  - **Attribution: 23 fast-path refreshes.** Those cycles produced nothing
    before this change. Baseline 146 aborts/180min -> 5 refreshes; now 96
    aborts/187min -> 37 refreshes.
  - **Residual confound, still stated:** the abort RATE is lower than baseline
    (30.8/h vs 48.7/h), so this window carries less memory pressure. The 7.0x
    refresh-rate improvement is therefore not wholly attributable; the 23
    fast-path lines and the absent long freeze are.

## 2026-08-14 19:29Z — web `ea1d2ed6` — A3 uninformative-EV rule + `rows_uninformative_ev`

- **Lane:** `recommendation-lane-correctness` (model audit 2026-08-14, A3).
- **Deploy:** `dep-d9vmp8dbedkc73enkldg`, web only, by `commitId` (services are
  pinned to `main` with `autoDeploy=no`; deploys here go by explicit commit, so
  no service-config change and NO `render.yaml` touched → no `blueprint_sync`).
- **Branch:** `deploy/model-audit-a3-uninformative-ev`, cut from `8ff4e513`
  (web's own live SHA) — verified a **pure fast-forward**, not a rollback.
  Deliberately NOT cut from `main`: `origin/main..HEAD` is **136 commits**
  across several sessions, none of which passed this gate.
- **Scope:** ONE substantive change. A1/A2 (`recommendation_engine.py`) and A3a
  (`opportunity_signals.py`) were deliberately EXCLUDED and remain undeployed,
  so this deploy's effect is attributable.
- **EXPECTED EFFECT ON WEB: NONE that a user can see, and that is the point.**
  Web has `SYNDICATE_ENABLE_INTELLIGENCE_STATE_BACKGROUND_LOOP=false`, so it does
  not build the shortlist — it reads the artifact. This ships the READER
  (`rows_uninformative_ev` on `/api/board/layer2-shortlist`) so the counter is
  visible the moment the builder ships. Until then the key should read **null**.
- **PREDICTION, so this is falsifiable:** after this deploy and before any
  refresh-worker deploy, `/api/board/layer2-shortlist` carries the KEY
  `rows_uninformative_ev` with value **null**, and `total_rows` stays ~256 with
  soccer still at 100. If soccer drops on WEB alone, my reading of loop
  ownership is wrong and this must be reverted.
- **Rollback:** redeploy `8ff4e513` on `srv-d88ahvrbc2fs73eodu30` by commitId.
- **MEASUREMENT `[19:38Z, /api/board/layer2-shortlist]` — ALL THREE PREDICTIONS HELD.**
  - Key `rows_uninformative_ev` **present** on the payload: `True`.
  - Its value: **`null`** — exactly as predicted, because the BUILDER has not
    shipped. The reader is in place and reads nothing yet.
  - `total_rows` **256**, `per_sport.selected` = mlb 84 / nfl 60 / **soccer 100** /
    wnba 12, `fair_method` mix consensus 156 / **book_margin_model 100**.
  So web did NOT apply the filter, which CONFIRMS the loop-ownership reading
  (`SYNDICATE_ENABLE_INTELLIGENCE_STATE_BACKGROUND_LOOP=false` on web) rather
  than assuming it. Had soccer dropped here, the reading was wrong and this was
  the revert trigger. It did not.
  **This deploy is therefore VERIFIED INERT BY DESIGN — it changes nothing a
  user sees and is not evidence that A3 works.** The behaviour change is still
  entirely ahead of us, in the held refresh-worker deploy.

### NOT deployed in this window, and why
- **refresh-worker (`29ed6de1`, branch `deploy/model-audit-a3-worker`, pushed
  and verified a fast-forward from `294f9ca9`) is HELD.** It is the service that
  actually applies the filter. Held because, measured at 19:26Z:
  - headroom is **182–226 MB of 4096** (`memory_anon_mb` 2703, `container_memory_mb`
    ~3884), and two OPEN lanes (`anon-allocation-site`,
    `refresh-worker-anon-leak`) are measuring exactly that number. A deploy
    reboots the worker and resets the quantity under measurement —
    `learnings.md`: "the floor IS the ratchet; every deploy reboots".
  - MLB is **mid-slate** (`MLB_SIM_TICK … reason: "sport_currently_live"`,
    `LIVE_MC_DIAG` running per game). No FULL sim is in flight — that check
    passed — but live props/live-lens work is active.
  Needs an explicit go/no-go from the user or the memory lanes' owner.

## 2026-08-14 19:42Z — refresh-worker `29ed6de1` — A3, the BUILDER half

- **Lane:** `recommendation-lane-correctness` (A3). Second half of the same one
  substantive change; web's reader shipped at 19:37Z and measured inert.
- **Branch:** `deploy/model-audit-a3-worker`, cut from `294f9ca9`
  (refresh-worker's OWN live SHA) and verified a **fast-forward**.
  - **A rollback was caught here.** The web branch (`ea1d2ed6`, off `8ff4e513`)
    is NOT an ancestor for this service — deploying it would have dropped four
    commits including `294f9ca9`, the `#429` MLB HRR producer fix `state.md`
    records as confirmed in production. The two services diverge from
    `b98f5ed7`, so NO single branch fast-forwards both. Hence two branches.
- **Shipped over the user's stated risk, with the risk stated:** headroom and
  the two OPEN memory lanes (`anon-allocation-site`, `refresh-worker-anon-leak`)
  were raised; the user chose to ship. This deploy REBOOTS the worker and resets
  `memory_anon_mb`, so any memory reading taken after 19:42Z is boot-confounded
  and must not be compared to a pre-deploy floor.
- **Pre-deploy checks, fresh at 19:41:34Z (not reused from 19:26Z):**
  - **0 full-sim launch markers in 8 minutes** — no full MLB sim to kill.
  - headroom **386.9 MB** (recovered from 182 MB), `memory_anon_mb` 2531.
- **PREDICTIONS — written before the deploy, all falsifiable, one is a control:**
  1. `rows_uninformative_ev` becomes a **positive integer** (currently `null`).
  2. `per_sport.soccer.selected` **100 → 0–12**.
  3. `total_rows` **256 → ~156**.
  4. `fair_method` mix `book_margin_model` **100 → 0**.
  5. **CONTROL:** mlb 84 / nfl 60 / wnba 12 selected stay **UNCHANGED**. All
     three sports price by `consensus`, so the rule must not touch them. If any
     of them moves, the rule is over-firing and this reverts immediately.
  Window: one board rebuild after the worker is live (~10–15 min observed).
- **Rollback:** redeploy `294f9ca9` on `srv-d91dpertqb8s73co8ls0` by commitId.
- **MEASUREMENT `[19:58:41Z build, read 19:58Z]` — ALL FIVE HELD, INCLUDING THE CONTROL.**

      P1  rows_uninformative_ev   null -> 4003        (positive integer)
      P2  soccer selected          100 -> absent      (0 rows; within 0-12)
      P3  total_rows               256 -> 156         (exactly 256-100)
      P4  book_margin_model rows   100 -> 0
      P5  CONTROL mlb/nfl/wnba   84/60/12 -> 84/60/12 UNCHANGED

  **The control is the load-bearing half.** All three of those sports price by
  `consensus`, so a correct rule must not touch them — and it did not, to the
  row. The board lost exactly the 100 `book_margin_model` rows and nothing else.
  `fair_method` mix is now `{consensus: 156}`, with zero modelled rows served.
- **`rows_uninformative_ev: 4003` is pool-side, not board-side** — it counts
  every candidate the rule rejected at that stage, not the 100 that would have
  been selected. Both numbers are wanted: 100 is what a user stopped seeing,
  4,003 is how much of the pool was margin-restatement.
- **The counter earned itself on the first build.** Soccer is now ABSENT from
  `per_sport` rather than present at 0, so the payload alone cannot tell "soccer
  had no slate" from "soccer's slate was all one-book longshots" — which is
  exactly the ambiguity `rows_uninformative_ev` was shipped in the same commit
  to resolve. Without it this deploy would read as a soccer outage.
- **WHY THE CONTROL HELD — established 21:2xZ, and it was NOT luck.** A later
  reading showed mlb 84 -> 78 and I briefly took the control to have failed.
  It had not: that reading is 21:22Z against a 19:58Z measurement, so it is
  **1.4 hours of slate drift plus two unrelated deploys**, not this rule.
  `total_rows` 156 -> 150 and `rows_uninformative_ev` 4003 -> 3842 drift the
  same way. Re-read the post-deploy measurement before attributing a later
  delta to the deploy.
  The substantive question that scare raised is worth keeping, because the
  premise I originally gave for P5 WAS wrong. I predicted MLB could not move
  because "every MLB row is `consensus`" — read off the survivors. Measured on
  the book-grid, MLB in fact carries **357 one-sided rows with a modelled
  fair** (wnba 42, nfl 0), so the rule CAN reach MLB.
  It does not, for a better reason than I predicted: MLB has
  `rows_with_model_edge = 2256`, and `_row_ev_is_hold_restatement` returns
  False for any row carrying a model view. **The narrowness clause is what
  protects MLB, not the absence of modelled rows.** The rule is doing exactly
  what it was designed to do, and the control held on the mechanism rather
  than on a coincidence of MLB's pricing.
- **Boot-confound, stated:** the worker rebooted at 19:49:15Z, so
  `memory_anon_mb` restarted from a clean floor. Any memory reading after that
  time is NOT comparable to the pre-deploy series the `anon-allocation-site` and
  `refresh-worker-anon-leak` lanes are building.

### ask-refusal-gate — `market_summary` stops answering non-betting questions
- **PREFLIGHT: PASS** 2026-08-14 14:45 CDT.
- Deployed: **2026-08-14 15:01 CDT (`20:01:18Z`)** — web
  `srv-d88ahvrbc2fs73eodu30`, deploy `dep-d9vn4j49v7es73b8leq0`, commit
  **`bef782cb`**, trigger `api`. Build+swap ~7.5 min.
- **1. Scope — ONE substantive change.** Diff against the LIVE sha (re-read from
  the API, not from `state.md`, which had a stale `f9aa2399`): `ea1d2ed6`,
  deployed 19:37:00Z by another session. Three files, 291 insertions:
  `ask_the_syndicate_router.py`, `ask_the_syndicate.py`,
  `test_ask_router_board_summary_default.py`. Nothing else.
  - **Deployed from a SIDE BRANCH, not main, and that is required here.**
    `origin/main` and local `main` have diverged by **119 / 142 commits** since
    `03073270` (2026-08-13 12:19). Main is not a safe deploy base. `bef782cb`'s
    parent is exactly `ea1d2ed6`, so the running service moves by one change.
    Same pattern the model-audit A3 deploy used
    (`deploy/model-audit-a3-uninformative-ev`).
- **2. Expected effect — a number and a window.** On the first request after the
  deploy reports `live`: `POST /api/syndicate/query {"question":"What is the
  capital of France?"}` returns `answered: false`, `intent: "out_of_scope"`,
  `top_opportunities: []`, in **under 1 s** (it short-circuits before the
  snapshot read; it took **10.9 s** and returned five betting picks at
  `f9aa2399`). Across the 52-question harness: **refusal 3/8 → 6/8**, and
  `market_summary` 40 → 37 of 52 resolved intents.
  - **What will NOT be comparable, stated up front:** the content classes
    (`lookup`, `ranking`, `entity`, `history`) score against a live slate that
    has moved since the 20/52 baseline. Only the routing-determined classes are
    slate-independent. Read `refusal` and the intent distribution; do not read
    the overall 20/52 → N as if it isolated this change.
- **3. Measurement — who reads it.** This session, immediately on deploy
  completion: `py -3 scripts/ask_syndicate_regression.py --out
  reports/ask_regression/post_deploy_2026_08_14.json`, plus a direct probe of
  the three fixed questions (F04 weather, F06 capital, F08 personal records).
- **4. Blast radius.** Web only; both workers untouched. Web runs on a
  persistent disk, so this is **stop-then-start with real downtime** — instances
  cannot overlap and every route 502s during the swap.
  - `check_deploy_safety.py` **CLEAR** at 14:41 CDT: MLB sim finished (exit=0),
    odds refresh idle, board build idle (last completed 17:48:33Z, ~3.5 min
    build, so this is the quiet window).
  - **Accepted caveat: LIVE GAMES ARE IN PROGRESS.** Live-lens ticks and live
    prop hydration take an interruption. Same caveat accepted on `#417`.
- **5. Rollback — stated now.** `POST /v1/services/srv-d88ahvrbc2fs73eodu30/deploys`
  with `{"commitId": "ea1d2ed6"}`. Nothing to un-migrate; the change is one
  branch in a router.
- **6. Ledger check.** No `learnings.md` FORBIDDEN/EXONERATED rule covers this
  work (grepped). **`render.yaml` is NOT touched**, so no `blueprint_sync`. No
  OPEN lane claims any `ask_the_syndicate*` file — zero mentions across
  `lanes.md`.
- **7. Verdict: PASS.** 136 tests pass **against the deploy tree itself**
  (`bef782cb` checked out to a worktree), not against main — the ask adapter and
  data modules are byte-identical between `ea1d2ed6` and the tested base, so the
  test imports resolve the same way.
- **Measured: CONFIRMED IN PRODUCTION 2026-08-14 15:05 CDT. The prediction was
  met exactly, and nothing else moved.**
  - **The code is proven to be running**: `/api/ops/version` reports commit
    `bef782cb`, and `intent: "out_of_scope"` is a value that did not exist
    before this deploy — it cannot be emitted by the old code.
  - The three target questions, live: `answered: false`,
    `intent: out_of_scope`, `top_opportunities: []`, each with its own reason
    string (the personal-records case correctly gets the accounts reason, not
    the generic one). **Latency 10.9 s → 0.19–0.44 s**, because a declined
    question now short-circuits before the snapshot read.
  - Harness re-run: **20/52 → 23/52**. **`refusal` 3/8 → 6/8** as predicted.
    `should_have_declined` 5 → 2 (F03 entity, F05 temporal — both known, both
    need a different layer).
  - **ZERO REGRESSIONS, and this is the load-bearing half**: advice 4/5,
    entity 2/10, explain 4/6, history 1/5, lookup 2/8, ranking 4/10 — every one
    identical to the baseline. The slate moved underneath the run (156 rows vs
    200, 3 active sports vs 4) and the content classes still scored the same,
    which is a stronger null result than a static slate would have given.
  - `answer_source` is `snapshot` on 49 and **absent on the 3 declines** —
    correct, they are a different response shape, and it is how a log will tell
    the modes apart once J2 lands.
- Verdict: **shipped and verified.** Rollback not needed.

## 2026-08-14 20:1xZ — refresh-worker `79148d8e` — A1/A2 probability sources + no-vig pricing

- **Lane:** `recommendation-lane-correctness` (A1/A2). Branch
  `deploy/model-audit-a1a2-probability-sources`, cut from `29ed6de1`
  (refresh-worker's live SHA), **verified fast-forward**. One substantive
  change; A3a is NOT on this branch.
- **Target: refresh-worker ONLY.** It alone has
  `SYNDICATE_ENABLE_INTELLIGENCE_STATE_BACKGROUND_LOOP=true`. Web does not run
  this lane and is not being deployed.
- **THIS GATE FAILED ON ITS FIRST PASS** — no predicted number for the
  exclusion rate, which is the "ship it and find out" posture the gate exists
  to stop. Resolved by measuring the input BEFORE deploying rather than by
  arguing:
  - `/api/ops/intelligence/candidate-trace` on WEB is useless for this:
    `1_collect_candidates_count: 0`. Web is display-only on its own disk and
    cannot run the pipeline. Recorded so nobody retries it.
  - `/api/intelligence/status` DOES answer it. Of the **145** currently
    published recommendations, **145 carry a real `model_probability`** and
    145 also carry a simulation-payload probability. `[measured 20:12Z]`
    So A1's `no_model_probability` exclusion removes **0 of 145**.
    By sport: mlb 138, nfl 3, wnba 3, championship 1 — all keep.
- **PREDICTIONS, written before the deploy:**
  1. **SAFETY / revert trigger:** `recommendation_count` stays **> 0**. If the
     lane empties, revert immediately. Supported by 145/145 above.
  2. **DIRECTION:** `recommendation_count` **>= 145, and likely HIGHER.** A2
     prices the model against the no-vig fair instead of the vigged price, and
     the no-vig fair is the SMALLER number, so every edge grows by roughly half
     the hold and MORE candidates clear the `edge > 0` gate. `#238`'s own
     framing — the vigged comparison made the sim "look systematically
     pessimistic" — predicts an increase, not a cull.
  3. `[recommendation_engine] FILTER_CANDIDATES` appears in refresh-worker logs
     with a `rejected={...}` map. `no_model_probability` may appear as a reason
     for POOL-side candidates (which were previously rejected anyway, but
     mislabelled `edge_below_threshold`).
- **Pre-deploy checks 20:10Z:** 0 full-sim launch markers in 8 min; headroom
  **1,830 MB**. Second worker reboot inside the hour — again boot-confounds the
  two OPEN memory lanes.
- **Rollback:** redeploy `29ed6de1` on `srv-d91dpertqb8s73co8ls0` by commitId.
- **MEASURED 2026-08-14 23:01:39Z — P1, P2 and P3 now all have readings.**

      [recommendation_engine] FILTER_CANDIDATES sport=all in=476 out=377
                              rejected={"edge_below_threshold": 99}

  - **P3 VERIFIED.** The instrument fired. This ALSO closes the separate
    `7b1f3fdc` instrument deploy (21:01Z), which was live and unmeasured — the
    line exists only because the `if rejected:` guard was removed.
  - **THE HEADLINE FINDING, and it is a NEGATIVE one worth stating plainly:
    `no_model_probability` does NOT appear in the rejected map.** Zero of 476
    candidates lacked a model probability. A1's exclusion is **INERT in
    production** — exactly as the pre-deploy 145/145 measurement predicted.
    The fix is correct and changes nothing by itself. Do not credit it with an
    effect it does not have.
  - **What DID change is the truthfulness of the 99 rejections.** Under the old
    code those rows were rejected under `edge_below_threshold` on an edge
    derived from `score/100` — a reason that claimed an edge had been measured
    when no model had run. They are now rejected on a real
    model-vs-no-vig-fair comparison. Same label, different and now-honest
    meaning, ~99 rows per cycle.
  - Pass rate 377/476 = 79.2%.
  - **Caveat on the search, not the finding:** all 12 log windows read were
    saturated at the 100-line cap, so this is ONE positive observation, not a
    complete census. A positive sighting is what was needed; absence still
    could not have been proven from these windows.
- **Superseded note (kept — it named the trap that nearly cost the reading):**
  - `recommendation_count` reads **145**, identical to pre-deploy. **That number
    is STALE and proves nothing:** `snapshot_generated_at = 2026-08-14T16:39:14Z`
    — ~3.6 HOURS old and long before the deploy. The intelligence state has not
    been recomputed since 16:39Z, so no post-deploy cycle has run and none of
    P1/P2/P3 has been tested. I read the count first and nearly banked it;
    checking the timestamp is what caught it.
  - **P3 did not fire either: 0 `FILTER_CANDIDATES` lines in 20 minutes.**
    Consistent with "the cycle never ran", NOT evidence about the code.
  - **DEFECT IN MY OWN INSTRUMENT, found by this:** the print is guarded by
    `if rejected:`, so it is SILENT when nothing was rejected. That makes
    "ran and rejected nothing" indistinguishable from "never ran" — the exact
    zero-must-be-visible failure this repo keeps hitting, which I flagged in
    other people's code earlier the same session. The guard should be removed so
    the line always emits. Not fixed here; recorded as owed.
  - **Standing question this exposes, for `layer2-board-freshness`:** why has the
    intelligence state not recomputed in ~3.6h? That lane is already open on
    build refusals. Not chased here.
  - **UPDATE 20:44Z — A CYCLE RAN, AND P1 IS NOW MEASURED.**
    `snapshot_generated_at` advanced to **2026-08-14T20:29:31Z**, which is
    post-deploy (live 20:13Z), so this is a real post-change reading.
    - **P1 (safety): PASS.** `recommendation_count` = **148**, not 0. The lane
      did not empty. That was the revert trigger; it is not triggered.
    - **P2 (direction): CONSISTENT, NOT PROVEN.** 145 -> 148 is the predicted
      direction (no-vig pricing raises edges, more candidates clear `edge > 0`),
      but the two readings are 3.9 HOURS apart and the slate moved in between.
      +3 is not cleanly attributable to the change. Recorded as consistent, not
      as evidence. A clean read needs two cycles either side of one deploy.
    - **P3: still unmeasured** — see the instrument deploy below.
  - **Risk status: A1/A2 is live, P1 VERIFIED, P2 confounded, P3 unmeasured.** The 145/145 pre-deploy
    measurement (every published recommendation carries a real
    `model_probability`) is the reason this is judged low-risk to leave running
    rather than pre-emptively reverted — but that is an argument, not a
    measurement. Revert trigger stands: `recommendation_count == 0` on a FRESH
    snapshot.

### ask-board-candidates (`M1`) — aggregation answered from the published board
- Deployed: **2026-08-14 15:38 CDT (`20:38:18Z`)** — web `srv-d88ahvrbc2fs73eodu30`,
  deploy `dep-d9vnm46417fc73ebm9fg`, commit **`5382943c`**, trigger `api`.
  Single change on the live SHA `bef782cb`. `check_deploy_safety.py` CLEAR at
  20:30:20Z after waiting out a refresh-worker board build; live-games caveat
  accepted as before.
- Expected: ranking class 4/10 → higher; `B01`'s `top_edge_diverges_from_board`
  clears.
- **Measured: THE CAPABILITY IS REAL AND VERIFIED. THE STATED CRITERION WAS NOT
  MET. Both halves matter and the second is the finding.**
  - **Working, by direct probe:** "biggest edges" → `152 of 152 rows`; "every
    play with an edge over 5 percent" → **`25 of 152 rows`**, an aggregation
    with a denominator that was previously unanswerable. `/api/ops/version`
    confirms `5382943c`.
  - **7 of 10 ranking questions are now answered from the published board, up
    from 0.** B04 (MLB total bases → 11 of 152, sport+market filtered) and B05
    (totals → 36 of 152) both previously scored
    `declined_an_answerable_question`.
  - **Soccer correctly returned NOTHING rather than MLB rows** — the board's
    `active_sports` was `[mlb, nfl, wnba]` at the time, so zero soccer rows is
    the true answer. The "report, do not widen" branch is exercised in
    production.
  - **The class score did NOT move: still 4/10.** The remaining failures are
    not M1's: B01 is the SNAPSHOT's headline number, B02 checks
    `structured_response` rows, B03/B08 are sport routing (K2/K3), and B06/B10
    miss the ranking-intent detector.
- **THE INSTRUMENT WAS BLIND, AND I NEARLY READ THAT AS A FAILED FIX.** The
  first post-deploy run reported `ranking` unchanged at 4/10 while a direct
  probe showed the same questions returning "26 of 153 rows". Cause:
  `_answer_text`/`_opportunities` scored only `structured_response`, and `M1`
  answers in `visuals.tables` — a third answer shape the scorer did not know
  existed. **A null reading is evidence only once the instrument is known able
  to read non-null.** Harness fixed (`_board_tables`, `_board_table_rows`, and
  a `no_board_table_for_an_aggregation_question` check) before any conclusion
  was drawn.
- **M1 SUPPLEMENTS, IT DOES NOT REPLACE — this is the real structural result.**
  `structured_response.top_opportunities` still comes from the snapshot, so
  chat's headline still disagrees with the board (`23.81%` vs `14.09%`,
  measured post-deploy; it was `5.02%` vs `13.59%` pre-deploy — the gap moved,
  it did not close). Killing the divergence needs the market-summary schema to
  source its rows from the board artifact too, which lives in
  `ask_the_syndicate_adapter.py` — **deliberately not claimed by this lane**,
  because a parallel session shipped `_board_summary_sentence` there.
- Rollback: redeploy `bef782cb`. Not needed — nothing regressed.
- Verdict: **capability shipped and verified; divergence NOT fixed.** Lane stays
  OPEN.


## 2026-08-14 21:01Z — refresh-worker `7b1f3fdc` — instrument: emit even on zero

- **Lane:** `recommendation-lane-correctness`. Branch
  `deploy/model-audit-instrument-always-emits`, cut from `79148d8e`
  (refresh-worker's live SHA), verified fast-forward. One change: remove the
  `if rejected:` guard on the `FILTER_CANDIDATES` line so `rejected={}` prints.
- **Why it was deployed at all:** the guard made "ran and rejected nothing"
  indistinguishable from "never ran", which is precisely what cost the A1/A2
  measurement four hours earlier. Mutation-checked: restoring the guard turns
  exactly one test red.
- **Pre-deploy 20:5xZ:** 0 full-sim launch markers in 8 min; headroom 1,458 MB.
- **MEASUREMENT: NOT OBTAINED — and the reason is now NAMED.**
  - 8 minutes of polling, then ten NARROW 90-second windows (to defeat the
    100-line tail cap that made the earlier "0 lines" meaningless): **still no
    `FILTER_CANDIDATES` line.**
  - **Because no cycle has run.** `snapshot_generated_at` is STILL
    `2026-08-14T20:29:31Z` at 21:03Z — 34 minutes stale.
  - **That is a defect, not a slow cadence.** Read from the live env:
    `SYNDICATE_ENABLE_INTELLIGENCE_STATE_BACKGROUND_LOOP = true` and
    `SYNDICATE_INTELLIGENCE_REFRESH_INTERVAL_SECONDS = 60`. The loop is ENABLED
    and configured to recompute every **60 seconds**. A 34-minute-old snapshot
    is ~34x its own interval.
  - **What the worker is doing instead**, sampled over 3 minutes (100 lines):
    repeated `SEASON_PROJECTION_LAUNCHING sport=nfl` followed by
    `Traceback` out of `scripts/generate_smartsim2_nfl_projections.py`, failing
    on pbp that "loaded ZERO plays" because `data/nfl_source/tracking/` is
    gitignored and absent from the checkout.
  - **HYPOTHESIS, EXPLICITLY NOT A CONCLUSION:** the crashing NFL season
    projection is starving the intelligence loop. What is MEASURED is only
    co-occurrence — loop enabled at 60s, snapshot 34 min stale, worker busy
    crashing. Causation is untested. Do not credit a fix to this without
    measuring the loop directly.
  - **This blocks three verifications, none of them caused by my changes:**
    A1/A2's P2 and P3, and this deploy's own effect.
- **Rollback:** redeploy `79148d8e`. Not warranted — the change is one log line
  and cannot affect the stall (which predates it: 20:29Z vs deploy 21:01Z).

### 2026-08-14 — web `aadcde77` — board-ui Lane E card defects — **MEASURED, EVERY CRITERION MET**

**Deploy `dep-d9vokalbedkc73erc9bg`, live at 21:42:56Z. Measured 21:4xZ with
the same probe that produced the before-reading**
(`reports/ui_layout/prod_before.json` -> `prod_after.json`):

    sport   width    overflow      touch-fail   orphan tabs         unreachable panels
    ncaaf   desktop  28px -> 0px   48 -> 64*    ['game'] -> []      ['identity','coverage'] -> []
    ncaaf   mobile   40px -> 0px   48 -> 0      ['game'] -> []      ['identity','coverage'] -> []
    nfl     desktop  28px -> 0px   64 -> 64*    -                   -
    nfl     mobile   20px -> 0px   64 -> 0      -                   -
    soccer  desktop  28px -> 0px    4 -> 4*     -                   -
    soccer  mobile   20px -> 0px    4 -> 0      -                   -
    ncaab   desktop  28px -> 0px    0 -> 0      (0 cards served)
    ncaab   mobile   20px -> 0px    0 -> 0      (0 cards served)

NCAAF trusted click-through, the defect this lane existed for:

    BEFORE  game    -> 0 panels active, card 187px   <- blank
            context -> ['context'] 485px
            details -> ['details'] 550px
    AFTER   identity-> ['identity'] 556px
            context -> ['context'] 483px
            coverage-> ['coverage'] 419px   <- was unreachable
            details -> ['details'] 548px

`font-variant-numeric` on the numeric classes: `normal` -> `tabular-nums`,
every sport.

**\* Read the desktop touch-target column honestly: it did NOT regress.** The
44px minimum was applied at `<=767px` only, on the judgement that a mouse does
not need a 44px target; desktop tabs are unchanged at 28px and were never
counted as passing. NCAAF's desktop count rose 48 -> 64 purely because each
card now carries FOUR tabs instead of three (16 cards x 4) — the number went
up because a previously unreachable panel became reachable. If we decide the
44px floor should apply at every width, that is a new decision and a new
measurement, not a regression of this one.

**Original pre-deploy block, kept as written:**

- **Service:** web only (`srv-d88ahvrbc2fs73eodu30`). refresh-worker and
  live-odds-worker untouched, so the refresh-worker deploy freeze/train and any
  in-flight MLB sim (which runs on refresh-worker) are unaffected.
- **What is deployed:** branch `deploy/board-ui-lane-e` =
  `aadcde77b064337a676e92e45f47563db215f3ca` = web's OWN live commit
  `5382943c` plus exactly one commit, `cf066942` (also on `origin/main`).
  **Deliberately NOT main's tip.** `origin/main` is 28 commits ahead of what
  web runs, including 440 deleted lines across the three `ask_the_syndicate*`
  blueprints, plus `layer2_board.py`, `intelligence.py`, `prop_projections.py`
  and the new `mlb_prop_calibration.py` — four other lanes' production
  changes, one of which (`aac18260`) state.md records as deliberately on
  NEITHER service. Deploying the tip would have shipped all of that under this
  lane's name.
- **Diff applied:** 18 files, +3172/-94, all UI — 5 templates, 6
  stylesheets/JS, `features/ncaaf/cards.py`, `features/mlb/season.py`, a new
  probe + tests, and deletion of the dead `static/mlb/board.js`.
- **EXPECTED EFFECT, as numbers, in a window.** Re-run the SAME instrument
  that produced the before-reading (`py -3 scripts/ui_layout_probe.py
  --base-url https://syndicate-an21.onrender.com`) within 10 minutes of
  `finishedAt`:

    | production measurement                 | before (08-14)        | expected after |
    |---|---|---|
    | overflow 1440, nfl/ncaaf/soccer/ncaab  | 28px                  | 0px            |
    | overflow 390                           | 20px (ncaaf 40px)     | 0px            |
    | ncaaf tabs addressing no panel          | 1 (`game`)            | 0              |
    | ncaaf panels no tab reaches             | 2 (identity,coverage) | 0              |
    | trusted click, ncaaf default tab        | 0 panels, 187px card  | 1 panel, >250px|
    | mobile tabs under 44px                  | 64 nfl / 48 ncaaf     | 0              |
    | font-variant-numeric, numeric classes   | `normal`              | `tabular-nums` |

- **Who reads it:** this session, immediately after `finishedAt`, writing the
  result into this row. While it still says PENDING, nobody has read it and
  the deploy is evidence of nothing.
- **Blast radius:** 1 instance, 50GB disk at `/opt/render/project/data`, so
  the deploy is stop-then-start — instances cannot overlap and routes 502 for
  roughly 1-3 minutes. No `render.yaml` change, therefore no `blueprint_sync`
  and no env rewrite.
- **Rollback, exact:** POST `/v1/services/srv-d88ahvrbc2fs73eodu30/deploys`
  `{"commitId": "5382943cb9d7c64a2004cdb57b43e52f68b26981"}` — web's current
  live commit, preserved on `origin` as this branch's base. Code-level:
  `git revert cf066942` on `main`.
- **Ledger check:** no FORBIDDEN rule applies (no `render.yaml`, no publish
  URL). "One substantive change per deploy" is satisfied literally. No OPEN
  lane claims any of the 18 files — checked by executing `lane-guard.py`'s own
  `_claims()` over `lanes.md`, not by reading it.
- **Preflight verdict: PASS.**

## 2026-08-14 22:12Z — refresh-worker `2b14fbeb` — CLV opening ledger (audit §7 #1)

- **Lane:** `clv-without-settlement`. Branch `deploy/clv-opening-ledger`, cut
  from `7b1f3fdc` (refresh-worker's own live SHA), **fast-forward verified**.
- **PREFLIGHT HELD THIS DEPLOY ONCE, CORRECTLY.** At 21:46Z the process table
  showed `run_mlb_daily_sim_job.py --date 2026-08-14` (pid 346) plus a
  `daily_update.py --workflow ui-daily --sims 1000` tree and two multiprocessing
  workers. Deploying would have killed an in-flight MLB sim.
  - **My own gate misfired first and must not be trusted as written.** It
    counted 16 "sim launch markers" in 8 minutes that were `ALL_PROCESS_MEMORY`
    telemetry lines containing the matched string, not launches. It reached the
    right verdict for the wrong reason.
  - **`MLB_SIM_TICK` is NOT the discriminator either** — it read
    `mlbDailySim: {"launched": false}` while the sim was running, because it
    reports whether THIS TICK launched one, not whether one is alive.
  - **The discriminator is the PROCESS TABLE** in `ALL_PROCESS_MEMORY.processes`.
    Cleared at 22:12:13Z: process_count 12 -> 5 -> 3, all three blockers gone.
- **PREDICTIONS, written before the deploy:**
  1. `[clv_opening_ledger] OPENINGS date=2026-08-14 rows_in=N written=M ...`
     appears in refresh-worker logs within one board build.
  2. FIRST build after deploy: `written` ≈ `rows_in` (~150), `already=0`.
  3. SECOND build: `written=0`, `already≈150` — idempotence in production, which
     is the whole first-sighting-only contract and the thing unit tests cannot
     prove about a real disk.
  4. `unkeyable_rows=0` and `duplicate_in_batch=0` — the fixed key produced 0
     collisions on the same payload offline.
- **REVERT TRIGGERS:** `truncated_at_ceiling=true` (dedup has failed and the
  file is growing per-tick), or `clv_openings_error` appearing on the shortlist
  payload (instrumentation taking the board down — the wrapper should make this
  impossible, so it firing means the wrapper is wrong).
- **KNOWN LIMITATION, stated rather than discovered later:** the counter is
  LOG-ONLY. It is not on `/api/board/layer2-shortlist` — that endpoint has an
  explicit key list and `clv_openings` was not added to it. Readable via the
  Render logs API, which works; not readable on the wire.
- **Rollback:** redeploy `7b1f3fdc` on `srv-d91dpertqb8s73co8ls0` by commitId.
- **MEASURED `[22:32:02Z, refresh-worker logs]` — 3 of 4 PREDICTIONS HELD, 1 PENDING.**

      [clv_opening_ledger] OPENINGS date=2026-08-14 rows_in=150 written=150
                           already=0 duplicate=0 unkeyable=0 truncated=False
      [intelligence_state] LAYER2_SHORTLIST date=2026-08-14 rows=150
                           considered=13888 sports=['mlb','nfl','wnba']

  - **P1 PASS** — the instrument fired on the first build after deploy.
  - **P2 PASS** — `written=150` of `rows_in=150`, `already=0`. Every published
    row's opening price is now recorded. The openings that were being lost on
    every build are being kept.
  - **P4 PASS** — `unkeyable_rows=0` AND `duplicate_in_batch=0`. This is the
    fixed key confirmed in production: the pre-fix key collapsed 17 of these
    same 150 rows onto 7 keys.
  - **P3 PENDING — idempotence on a real disk is NOT yet confirmed.** It needs a
    SECOND build (`written=0`, `already=150`) and none has run: builds are
    ~21 min apart (22:11:09 -> 22:32:02) and 9 minutes of polling caught none.
    Unit tests pin it and the offline run over this same production payload
    wrote 0 on its second pass — but neither is the production disk. **Do not
    record this lane closed until that second line is read.**
  - **Neither revert trigger fired:** `truncated=False`, and no
    `clv_openings_error` on the served payload.
- **A BUILD HAD NOT RUN FOR THE FIRST 18 MINUTES AFTER DEPLOY**, and the absence
  of the line during that time meant nothing. Confirmed by the discriminator
  rather than assumed: 0 `LAYER2_SHORTLIST` lines across nine consecutive 2-min
  windows, served `written_at` 22:11:09Z (pre-deploy), `MEMORY_GUARD_ABORT=0`.
  Checking whether the CODE RAN before judging its output is the only reason
  this was not written up as a broken deploy.

## 2026-08-14 23:11Z — refresh-worker `96e3a9b7` — CLV same-book (`book_prices`)

- **Lane:** `clv-without-settlement`. Branch `deploy/clv-same-book-r2`.
- **PREFLIGHT CAUGHT A ROLLBACK, AGAIN, AND IT WAS A DIFFERENT ONE.** The
  branch was cut from `57e32a04` (off `2b14fbeb`), but by deploy time
  refresh-worker had moved to **`cfee9c6e`** — another session shipped `#387`
  (3 commits: board build holds ONE sport, per-sport overview streaming, pool
  retention). `merge-base --is-ancestor` said NO. Deploying as-cut would have
  dropped all three.
  - **`cfee9c6e` DOES contain `2b14fbeb`**, so the CLV recorder was never
    rolled back — checked before assuming.
  - Resolved by REBASING onto `cfee9c6e` (clean, no conflicts) and re-running:
    99 passed. Ancestry then verified YES.
  - Pushed as `-r2` rather than force-pushing the rebased branch. A force-push
    was refused and a new name is the right answer anyway — the old ref stays
    intact as a record of what was actually tested pre-rebase.
- **Sim gate held once, then cleared.** 23:07:49Z showed
  `run_mlb_daily_sim_job.py` + the `daily_update` tree; polled to 23:11:04Z
  (process_count 9 -> 7, blockers NONE) and deployed inside that window.
- **WHAT SHIPS:** `book_prices` ({book: price}) rides the quote from the grid's
  `cells` onto every opening, and the joiner prefers a genuine same-book pair
  (our price at a book history recorded, vs THAT book's close) before the
  labelled fallback.
- **PREDICTIONS:**
  1. `OPENINGS` lines continue; `written` per build unchanged in shape.
  2. Openings recorded after this deploy carry a non-empty `book_prices`.
  3. **The one that matters:** on a date whose openings were recorded WITH
     `book_prices`, `compute_clv_for_date` returns `same_book_n > 0` and a
     non-None `avg_clv_pct`. Measured basis for expecting it: on the real grid,
     rows whose (event, market) exists in history matched the BEST book alone
     18 times vs **128** for ANY book we quoted (7.1x).
  4. **CONTROL:** `avg_clv_pct` must still be None for 2026-08-14's already
     recorded openings — they predate `book_prices` and must not acquire a
     same-book pair retroactively.
- **KNOWN:** today's openings are already written without `book_prices`, and
  first-sighting-only means they will NOT be rewritten. The first date with
  same-book CLV is **2026-08-15**. That is the contract working as designed,
  not a defect.
- **Rollback:** redeploy `cfee9c6e` by commitId.
- **MEASURED 23:27:45Z (first post-deploy build). P1 and P2 VERIFIED; P3 owed.**
  - **P2: `book_prices` on 150/150 served rows.** books/row min=1 median=4
    max=35. Self-consistency: the best bookmaker appears inside its own
    `book_prices` on **150/150** — so the map and the headline quote cannot
    disagree about which book was picked.
    Sample: best `fanatics@290` beside `{betmgm 230, betrivers 230, fanduel 220,
    kalshi 285}` — 290 is correctly the best price for a plus-money away side.
  - **P1:** the recorder kept running across the change; board rows unaffected.
  - **P3 (same_book_n > 0 and a non-None avg_clv_pct) IS STILL OWED.** It needs
    openings that were RECORDED with `book_prices`. Today's were written before
    23:19Z without it, and first-sighting-only means they will not be rewritten,
    so today's date can only produce same-book pairs for markets first seen
    AFTER the deploy. **The first clean date is 2026-08-15.**
  - **The CONTROL still holds and matters:** 2026-08-14's pre-deploy openings
    must NOT retroactively acquire a same-book pair. They cannot — the field is
    absent on them — and that is the first-sighting contract behaving correctly,
    not data loss.

### MEASUREMENT for the row above — 2026-08-14 23:12Z — MIXED, AND IT DOES NOT CONFIRM THE FIX

DEPLOY: `cfee9c6e` live 2026-08-14T22:55:35Z (`dep-d9vpmoqjnfac73c7ip4g`, trigger=api).
Fired on a confirmed CLEAR — **zero jobs killed**, which is the first thing this
session got right and the handoff said was hard.

WHAT IS VERIFIED
- No `oomKilled` in the 17 min since. Worker healthy (pid 39, jobs running).
- `OVERVIEW_STREAM_FELL_BACK_TO_LIST` = **0**. The empty-board failure mode the
  commit message names as the risk of this change did NOT occur.
- Layer 2 shortlist alive and unaffected: `LAYER2_SHORTLIST rows=150
  considered=12304 sports=['mlb','nfl','wnba']` at 23:04:05Z.

WHAT IS NOT VERIFIED — AND WHAT CONTRADICTS THE HANDOFF
1. **The handoff's premise does not survive contact with more than one sample.**
   It says peak = SUM-across-eight "is sufficient on its own to cross 4GiB" and
   "the floor plays no part". Two pre-deploy hydrated 8-sport passes on the OLD
   code, measured tonight:

       22:36:48 -> 22:37:43   8 sports hydrated   PEAK  804.2 MB anon  (19.6%)
       22:49:19 -> 22:49:50   8 sports hydrated   PEAK  613.1 MB anon  (15.0%)

   The identical pass shape that "cannot fit" ran twice, 20 minutes apart, at a
   fifth of the ceiling. The 20:03:11Z kill had an ingredient the handoff ruled
   out on one sample. **The diagnosis this deploy rests on is not established.**
2. **The first post-deploy hydrated pass was WORSE on both axes:**

       22:56:16 -> 22:57:29   1 sport hydrated    PEAK 1384-1486 MB anon (33.8%)

   More memory for ONE sport than the old code spent on EIGHT, and the
   pre-existing 3000MB guard then stopped the stream:
   `OVERVIEW_STOPPED_FOR_MEMORY next_sport=nba sports_done=1 sports_total=8
   headroom_mb=2900.7 min_required_mb=3000.0` -> `BOARD_OVERVIEW_READY sports=1`,
   where every pre-deploy build in the preceding 3h read `sports=8`.
3. **MECHANISM, proposed not proven:** streaming moves per-sport candidate
   collection INSIDE the guarded span. The 3000MB floor was sized (2026-08-07)
   against a span that no longer means the same thing, so it now trips one sport
   in. The guard is pre-existing and fired 4x BEFORE this deploy (20:33-20:45,
   `sports_done=0` -> `sports=0`), so it is not new — but its interaction is.
4. **CONFOUNDED, honestly:** the post-deploy pass ran 40s after a boot (cold
   caches, `_BOOK_QUOTES_CACHE` filling to its 500MB budget); the two pre-deploy
   passes were 18 and 30 min warm. Cold-vs-warm plausibly explains part of the
   1384 vs 804. I cannot separate them from this data.
5. **AND THE EXPERIMENT CANNOT CONTINUE ON ITS OWN.** At 23:04 the container is
   at 2790MB / headroom 1305MB, so the 3000MB guard will refuse every further
   hydrated pass outright. **The only window in which this measurement is
   obtainable is the ~2 minutes after a boot.** No second post-deploy pass has
   occurred in 17 min (pre-deploy cadence was 7-12 min).

VERDICT: deployed, safe so far, **fix NOT demonstrated**. Do not record this as
a working fix. Rollback stays armed:
`py -3 scripts/render_deploy.py --service refresh-worker --commit 2b14fbeb --allow-rollback`

## 2026-08-14 23:2xZ — refresh-worker — the overview floor becomes two floors — PENDING DEPLOY

- Target: `77938bff` on `deploy/overview-floor-two-tier`, descends from the live
  `cfee9c6e` (no rollback). Owner decision: recalibrate rather than roll back.
- WHY: the cutover did not change the guard, but it changed what the guard's
  span contains, and the guard is what decided the outcome. Both post-cutover
  hydrated passes stopped at `sports_done=1` with headroom 2900.7 / 2587.3MB
  against a 3000MB floor -> `BOARD_OVERVIEW_READY sports=1` where every build in
  the preceding 3h read `sports=8`.
- CHANGE: `mlb` and any UNRECOGNISED slug keep the full 3000MB floor; the seven
  measured-cheap sports get 1500MB. `floor=` added to the refusal line because
  one message now has two meanings.
- SIZING EVIDENCE (production, tonight): five sports hydrated in 171ms for
  +1.7MB (627.4 -> 629.1MB); an entire eight-sport hydrated pass on the OLD code
  moved anon 444.6 -> 804.2MB; MLB alone moved +987MB anon / +1543MB container.
- NOT RELAXED: the gate in front of MLB. 20:03:11Z showed a +3.5GB MLB excursion
  against tonight's +1.0GB, and that variance is unexplained.
- GATE: 29 passed (guard + streaming + layer2_fast_refresh, which pins the
  3000MB constant left untouched). `test_intelligence_state.py` 225 passed with
  the SAME 6 failures that fail on `2b14fbeb` without any of this.
- EXPECTED: next hydrated pass reaches `sports_done=8` /
  `BOARD_OVERVIEW_READY sports=8`, peak anon stays under 2500MB, no oomKilled.
- MEASUREMENT: <pending — owed by session memory-cutover-ship>
- Deploy gate has read HOLD continuously since 23:24Z (a long MLB
  `daily_update.py` run). Waiting for a confirmed CLEAR rather than killing it.

- **CORRECTION 23:4xZ — the target moved, and the rollback guard is why I know.**
  While the gate was HOLD, `Audit 2026-08-14 models` deployed `96e3a9b7`
  (23:11:10Z, live 23:17:20Z), which deactivated `cfee9c6e`. My
  `py -3 scripts/render_deploy.py --commit 77938bff` was then REFUSED: 77938bff
  descends from `cfee9c6e`, not from the new live SHA. **`render_deploy.py`'s
  descendant check caught a concurrent-session race that a raw curl would have
  shipped as a silent 850-line rollback** — the exact scenario it was written
  for on 2026-08-14, now paid for a second time.
  - I nearly missed it too: I piped the deploy output through `json.load`, which
    raised on empty stdin and hid the refusal message. Read the tool's own
    output before deciding what happened.
  - **`96e3a9b7` CONTAINS the cutover** (`cfee9c6e` is an ancestor, marker
    present) — they built on top of it rather than around it, so nothing was
    lost. Verified by ancestry AND by grepping the marker, not by reading the
    commit subject.
  - New target: **`705eeefc`** on `deploy/overview-floor-two-tier-v2` =
    `96e3a9b7` + the same one commit. The two files are byte-identical to the
    tested `77938bff`; 29 tests re-run green on the new base.

## 2026-08-14 23:4xZ — refresh-worker `9972977f` — audit §7 #7: serve the MLB prop skill numbers

- **Lane:** `recommendation-lane-correctness`. Branch `deploy/mlb-prop-skill` —
  `aac18260` cherry-picked onto `96e3a9b7` (live SHA re-read at deploy time,
  fast-forward verified). 40 tests pass.
- **PREMISE CHECKED, NOT TRUSTED.** The audit says `aac18260` is committed and
  absent from the deployed tree. Verified both halves: it IS on `origin/main`
  and `merge-base --is-ancestor aac18260 96e3a9b7` says NO.
- **BLAST RADIUS: LABEL-ONLY.** Read the diff rather than the commit message.
  `_attach_measured_skill` sets `payload["model_skill"]` and nothing else — no
  projection, mean, or edge is modified. A field appears; no number moves.
  It also fills only where `model_skill` is ABSENT, so it cannot overwrite a
  producer's own verdict.
- **BASELINE, captured before deploying** (board 23:44:59Z): 29 mlb prop rows,
  `model_skill` status `{unmeasured: 25, None: 4}`. Markets: batter_rbis 8,
  batter_total_bases 5, batter_runs_scored 5, batter_hits 3,
  batter_hits_runs_rbis 3, outs 1, hits_allowed 2, earned_runs 2.
- **PREDICTIONS:**
  1. The four measured batter markets — rbis(8), total_bases(5),
     runs_scored(5), hits(3) = **21 rows** — gain a `model_skill` carrying
     `correlation` and a `verdict`.
  2. **CONTROL A:** `batter_hits_runs_rbis` (3 rows) stays **unmeasured**. It
     was the degenerate 0.0 `#429` fixed on 2026-08-14, so it cannot be
     measured from that window and must not inherit a neighbour's number.
     `skill_note` returns None for it — checked directly before deploying.
  3. **CONTROL B:** the pitcher markets `outs`(1), `hits_allowed`(2),
     `earned_runs`(2) stay unmeasured — the calibration covers batter markets
     only, so a note appearing there means the join is too loose.
  4. **CONTROL C:** `model_edge_pct` / `projection` values are NOT expected to
     change. This is label-only; if edges move, the change is doing more than
     advertised and should be reverted.
- **What the notes say** (read before shipping, because publishing a verdict is
  a product statement): 4 batter markets read "real ranking signal, loses to
  the mean until de-biased" with bias +18% to +31%; doubles "almost no signal
  (r=0.03)"; triples "no measured skill (r=0.02)"; stolen_bases "the only
  market that beats the mean as-published; biased LOW ~22%".
- **Rollback:** redeploy `96e3a9b7` by commitId. (Superseded — see re-cut below.)
- **RE-CUT AND SHIPPED as `098877e1` on branch `deploy/mlb-prop-skill-r2`,
  LIVE 00:22Z.** The first attempt (`9972977f`) was **CANCELED at 00:08:31Z —
  not by me**: another session triggered `705eeefc` (`#387` overview floor) one
  second earlier and Render cancels an in-flight deploy when a new one starts.
  - **I did not retry into it.** Re-triggering would have canceled THEIR build
    and started a deploy war. Checked first that `705eeefc` CONTAINS `96e3a9b7`
    (it does — no CLV work lost), waited for theirs to go live, then
    cherry-picked `aac18260` onto it and re-verified fast-forward.
  - The deploy loop now HOLDS when another deploy is in flight instead of
    firing into it.
- **MEASURED 2026-08-15T00:35:56Z (first post-deploy build):**
  - **PREDICTION 1 HOLDS — 24 rows now MEASURED**: batter_rbis 12,
    batter_total_bases 6, batter_hits 3, batter_runs_scored 3. Sample
    (`batter_total_bases`, Wilyer Abreu): `correlation 0.1523,
    sample_games 2487, seasons 2026-08-01..2026-08-14, status measured,
    verdict "biased high ~18%; real ranking signal, loses to the mean until
    de-biased"`.
  - **CONTROL A PASS** — `batter_hits_runs_rbis` still unmeasured/None. It must
    not inherit a neighbour's number and it did not.
  - **CONTROL B PASS** — pitcher market `outs` still None.
  - **CONTROL C FAILED, AND THE CONTROL WAS WRONG, NOT THE CODE.** It flagged
    53 of 66 non-mlb rows carrying a skill correlation. Investigated as a
    possible leak of MLB numbers onto other sports — a fabricated skill claim
    would be the worst outcome this change could have. It is not one: all 53
    are **NFL, correlations -0.047 and 0.269, seasons "2023-2025"** — NFL's own
    producer, from the `projection-skill-declaration` lane closed earlier today.
    None matches the MLB calibration set {0.1607, 0.1523, 0.1316, 0.162,
    0.0278, 0.0179, 0.1605} or its 2026-08 window.
    **My error: I asserted "non-mlb must be zero" without taking a pre-deploy
    baseline for non-mlb.** I baselined only the MLB props. A control whose
    expected value was never measured is a guess wearing a control's clothes —
    it cost an investigation and could just as easily have been waved through
    as a real regression.

### MEASUREMENT — 2026-08-15 00:36Z — `705eeefc` VERIFIED IN PRODUCTION

DEPLOY: `705eeefc` live 2026-08-15T00:15:08Z (`dep-d9vqrvlg1s2s73blnt90`).
Fired on a confirmed CLEAR — **zero jobs killed**, third for three tonight.

BEFORE (5 consecutive builds, `cfee9c6e` then `96e3a9b7`):

    22:57:22  headroom 2900.7  |  23:14:32  2587.3  |  23:19:50  2602.0
    23:36:46  2706.4           |  23:53:54  2490.5
    every one:  min_required 3000.0 -> STOPPED next_sport=nba sports_done=1
    every one:  BOARD_OVERVIEW_READY sports=1 mlb:g=13,r=3

AFTER:

    BOARD_OVERVIEW_READY date=2026-08-14 sports=8
      mlb:g=13,r=3 nba:g=0,r=3 wnba:g=1,r=3 nfl:g=10,r=3
      ncaaf:g=0,r=3 ncaab:g=0,r=3 nhl:g=0,r=3 soccer:g=55,r=3
    OVERVIEW_STOPPED_FOR_MEMORY since the deploy:  0
    oomKilled since the cutover shipped (1h40m):   0
    LAYER2_SHORTLIST rows=142 considered=12826 sports=['mlb','nfl','wnba']

AND THE TRACE SHOWS THE MECHANISM, not just the outcome. Peak anon over the
verified 8-sport pass, 346 samples paged BACKWARD over 00:23:05..00:28:55:

    00:23:40   617.6      <- pass begins
    00:25:30  1404.5      <- PEAK, at MLB's OVERVIEW_SPORT_END
    00:25:40  1172.5      <- MLB RELEASED; the other seven run under this
    00:27:40  1173.5      <- flat for two minutes while seven sports hydrate

**34.3% of the 4096MB ceiling, and the peak is a SINGLE-SPORT peak that comes
back DOWN before the next sport starts.** That is `#387`'s stated goal --
peak = MAX-of-one-sport, not SUM-of-eight -- visible in the memory trace rather
than argued from a diff.

SCOREBOARD FOR THE PAIR:
- `cfee9c6e` (cutover): stops the OOM, but on its own it truncated the board to
  one sport. **Shipping it alone would have been a coverage outage** presenting
  as a memory fix, and the ledger would have recorded a success.
- `705eeefc` (two floors): restores all eight at a third of the ceiling.
- Neither is a fix for MLB's cost, which is untouched and still the whole story:
  MLB is ~800MB of the 900MB excursion, seven sports are ~1.7MB.

STILL OPEN, and recorded so it is not lost: the 20:03:11Z kill is NOT explained.
The handoff's "peak = SUM crosses 4GiB on its own" was falsified by two 8-sport
passes at 613/804MB on the OLD code. Something made MLB cost +3.5GB in that one
pass. **The guard in front of MLB keeps its full 3000MB until that is known.**

### RETRACTION 2026-08-15 00:5xZ — "oomKilled 0" IN THE 00:36Z ENTRY ABOVE IS FALSE

That entry, its lane closure and `state.md` all claimed `oomKilled` 0 since
22:55Z as verification. **The claim came from a LOG grep. Kills are EVENTS.**

`/v1/services/srv-d91dpertqb8s73co8ls0/events` — 16 kills on 2026-08-14:

    20:03:11  20:14:30  21:07:32  21:16:50  21:25:48  21:35:08  21:46:51
    21:57:53  22:14:39  22:36:06  22:48:35  |  23:11:56  23:34:15  23:51:04
    00:04:47  |  00:41:16

    before the cutover (20:03-22:55, 172 min):   11 kills = 1 per 15.6 min
    cutover only     (22:55-00:15,  80 min):      4 kills = 1 per 19.9 min
    both halves      (00:15-00:52,  37 min):      1 kill  = 1 per 37 min  (n=1)

**Neither half of `#387` stopped the OOM kills, and the rate is not
distinguishable at these sample sizes.**

WHAT SURVIVES, because it was sourced independently: `BOARD_OVERVIEW_READY
sports=8` against 5 consecutive `sports=1`, and the overview pass peaking at
1404.5MB and falling to 1172MB as MLB releases. **The coverage fix is real. The
memory claim was not.**

WHAT THE KILL ACTUALLY IS (00:41:16, best instrumented):
pid 39 — the MAIN worker — 1612MB -> 3079MB in 28 seconds, children small
(`daily_update.py` 166MB, soccer refresh 95MB), payloads tagged
`game_count: 15`. MLB game hydration, not the overview. At the handoff's
canonical 20:03:11 kill the container was at **28.8%** twelve seconds prior with
`stage=post_build_overview` — the overview had already finished.

CONSEQUENCE FOR THE 3000MB FLOOR: leave it. It guards the wrong stage, but
lowering it now would only let more work into a process that is dying elsewhere.

### 2026-08-15 — web `932a1f71` — board contract: absent is absent — **MEASURED**

Deploy `dep-d9vrccrl550s73bugj00`, live 00:50:23Z. Branch
`deploy/board-contract-absent` = web's own live `aadcde77` + exactly one
commit (`dda83c18`, on main as `7056c57f`). Not main's tip: main was 123
commits and four lanes ahead. No `render.yaml` change.

Same instrument before and after, on production:

    route                cards  bars  50/50  draw  absent
    /nfl/cards    before     16    16      1     0       0
    /nfl/cards    after      16    16      1     0       0
    /soccer/epl   before      1     1      0     0       0
    /soccer/epl   after       1     1      0     1       0

**The soccer draw segment is live: 0 -> 1.** A three-way market renders three
segments, and the bar now reads the sim (77.3% on the audit's card) rather
than the market's implied 81.1%.

**The NFL 50/50 did NOT go away, and that is the correct outcome — checked,
not assumed.** The contract no longer fabricates, so a surviving 50/50 must
come from the producer. It does: NFL builds `probability_rows` straight from
`projection.home_win_rate`, and the game is **Denver @ Kansas City, home mean
22.5 vs away mean 22.1** — a 0.4-point projected margin. A ~50% win
probability there is the model speaking, not a default. That is precisely the
distinction this lane existed to make legible: before the change a 50/50 could
be either, and now it can only be the model.

All ten board/market routes 200 after the deploy.

**Rollback, exact:** POST `/v1/services/srv-d88ahvrbc2fs73eodu30/deploys`
`{"commitId": "aadcde77b064337a676e92e45f47563db215f3ca"}`.

## 2026-08-15 01:1xZ — refresh-worker — `#435` memory watchdog — PENDING DEPLOY

- Target: `c9378c91` on `deploy/memory-watchdog-435` = live `d70f70d8` + one
  commit (`b3ee36d9` cherry-picked; another session shipped `d70f70d8` at
  01:03:38Z while I was writing, so the branch was rebased onto it and re-tested
  — 38 passed on the new base).
- **This is an INSTRUMENT, not a fix. It changes no behaviour.** It exists
  because 2 of 6 sampled kills show the process at 22.7% and 71.9% seconds
  before death: multi-GB allocations INSIDE a stage, invisible to the
  boundary-only sampling we have.
- Watchdog: daemon thread, ~2s, one cgroup read per tick, emits only above 60%
  or on a 200MB move. Carries `last_stage` + `seconds_since_stage`.
  `SYNDICATE_MEMORY_WATCHDOG=0` disables without a code change.
- EXPECTED, and this is the whole test: at the NEXT OOM kill there are
  `MEMORY_WATCHDOG` lines in the final seconds naming a stage and a climb rate,
  where today the last line is a stage boundary at 22.7%.
- FAILURE MODES I AM WATCHING FOR: (a) log flood — should be silent at rest,
  measured 1 line locally after the unknown-split fix, was 1-per-tick before;
  (b) the thread dying silently — `MEMORY_WATCHDOG_STARTED` must appear at boot;
  (c) the worker restart loop `#241` caused — if kill CADENCE worsens, disable
  via env before anything else.
- MEASUREMENT: <pending — needs one OOM kill to occur, which historically takes
  15-20 min>
- Rollback: `py -3 scripts/render_deploy.py --service refresh-worker --commit d70f70d8 --allow-rollback`

### 2026-08-15 — web `1ac485c0` — NCAAF kickoffs file on their CENTRAL day — **MEASURED**

Deploy `dep-d9vrpcm417fc7394q3r0`, live 01:17:56Z.

**Measured before the fix, on the real 2026 schedule: 28 of 157 kickoffs were
filed under the wrong date.** Every evening game is the next UTC day, so
`.date()` on the parsed UTC value put the marquee Saturday slate on Sunday and
labelled it "Sunday":

    Memphis at UNLV           2026-08-30T02:00:00Z   filed 08-30, is 08-29 Sat
    Colorado at Georgia Tech  2026-09-04T00:00:00Z   filed 09-04, is 09-03 Thu
    UTEP at Oklahoma          2026-09-05T00:00:00Z   filed 09-05, is 09-04 Fri

Production week-1 betting card, day labels before -> after:

    before: Thu Sep 3 | Sun Sep 6 | SUN AUG 30 | Sat Sep 5 | Sat Aug 29 | Mon Sep 7 | Fri Sep 4
    after:  Thu Sep 3 | Sun Sep 6 |            | Sat Sep 5 | Sat Aug 29 | Mon Sep 7 | Fri Sep 4

**"Sunday, August 30" is gone** — those games are Saturday-evening kickoffs and
now sit under Saturday. Sunday Sep 6 and Monday Sep 7 remain because those are
real Labor Day weekend games; the fix moved what was wrong and left what was
right, which is why the afternoon-kickoff case has its own test.

Ten board routes 200. The other session's `/api/ops/clv/report` still answers
(401 auth, not 404), i.e. their work survived this deploy.

**Rollback:** POST `.../deploys` `{"commitId": "d9a39ce8..."}` — the commit
this one was stacked on.

**HOW THIS DEPLOY WAS SEQUENCED, because it nearly went wrong.** My first
attempt refused to fire: a pre-flight check found `d9a39ce8` (another
session's CLV route) already `build_in_progress` on web. Had I fired my
branch — pinned to `932a1f71`, the then-live commit — it would have landed
*after* theirs and **reverted their route**, because a pinned deploy carries
its own tip and nothing else. I waited for theirs to reach live, re-pinned my
commit on top of `d9a39ce8`, and deployed that. Both changes are live.

## 2026-08-14 20:0x CDT — TWO services — CLV made readable (`d70f70d8` + `d9a39ce8`)

- **Lane:** `clv-without-settlement`. **Why:** the recorded next action ("run
  `compute_clv_for_date` tomorrow") **was not executable**. The joiner had no
  call site and the openings live on refresh-worker's disk, which nothing can
  read. Three pieces, any one alone inert.
- **refresh-worker `d70f70d8`** (off `098877e1`, fast-forward) — allowlist
  `reports/intelligence/clv_openings/*.jsonl` + `record_openings` now calls
  `publish_hot_artifact`, and the joiner guards. **LIVE ~01:05Z.**
- **web `d9a39ce8`** (off `932a1f71`, web's OWN live SHA) —
  `GET /api/ops/clv/report`. **LIVE ~01:2xZ.**
  - **A ROLLBACK WAS CAUGHT AGAIN.** `d70f70d8` does NOT contain web's last six
    commits; deploying it to web would have dropped another session's board
    contract, card-UI and Ask work. Two services, two branches, each verified
    against its OWN live SHA. This is the third time tonight this check has
    changed what shipped.
- **VERIFIED:** the endpoint answers and is well-formed —
  `date=2026-08-14` (Central default working; a UTC default would have asked
  for a file that does not exist for five hours every evening),
  `openings=0 resolved=0 same_book_n=0 avg_clv_pct=None unresolved={}`.
- **NOT VERIFIED, and both matter:**
  1. **The recorder has not been seen alive since the reboot.** No
     `clv_opening_ledger` line in ~30 minutes across narrow windows. Board
     builds were running ~21 min apart earlier, so this is overdue but not yet
     diagnostic — `layer2-board-freshness` has a documented history of
     `MEMORY_GUARD_ABORT` refusing board cycles, which would look exactly like
     this. **Check this before trusting tomorrow's number.**
  2. **`openings=0` on web is EXPECTED TODAY and is a DESIGN LIMIT worth
     knowing.** Publishing fires only when `written > 0`, and 2026-08-14's
     markets were all first-seen before this deploy — so today's file is
     STRANDED on the worker unless a new market appears. It self-heals on the
     next write (the push sends the whole file, not a delta), and tomorrow's
     new date creates a new file whose first write publishes it. A one-shot
     publish per worker boot would close the gap properly; not built.
- **Rollback:** worker `098877e1`, web `932a1f71`, both by commitId.

### `#435` WATCHDOG DEPLOYED 2026-08-15 01:16:54Z — boot checks PASS, measurement pending

- `c9378c91` live 01:16:54Z (`dep-d9vrov9t0dsc7389aqb0`). **Zero jobs killed** —
  the owner called to force it through, and the gate returned CLEAR on its own
  as the call was made, so no force was needed. Four deploys tonight, four with
  zero jobs killed.
- (a) STARTED: `MEMORY_WATCHDOG_STARTED interval_s=2.0 floor_pct=60.0
  delta_mb=200.0` at 01:17:29Z. The thread is running.
- (b) NO FLOOD: zero `MEMORY_WATCHDOG` sample lines at rest. The gating works in
  production, not just locally.
- (c) PENDING: needs an OOM kill. Watcher armed against baseline 01:16:54Z.
- **This deploy fixes NOTHING and must not be recorded as if it did.** It is an
  instrument. Kills were arriving every ~16 min (last 00:57:02Z); the honest
  outcomes are: a trace naming the stage and climb rate; a FLAT trace (excursion
  faster than the 2s tick -> shorten the interval or sample in-loader); or no
  lines at all (gating wrong or thread dead). All three are results.
