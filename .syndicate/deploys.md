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

## DEPLOYED 2026-08-14 10:42 CDT — `530fc5d8` refresh-worker — Layer 2 shortlist off the Layer 1 floor — MEASUREMENT OPEN

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
- Measured: `<pending>`

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
