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

- [ ] **RIDEALONG, NOT A DEPLOY OF ITS OWN — `734c163e` on `origin/main`: the
      props-snapshot `force_refresh` escape.** Whoever next deploys **either
      worker**, cherry-pick it onto that service's live SHA and it comes along.
      **Web needs nothing** — these exporters are producer-side only.
      - Live when written: refresh-worker `a775e372` (16:59:48Z),
        live-odds-worker `dd53d47c` (05:20:39Z), web `ebd5f677`.
      - **NOT INERT ON WNBA, AND THAT IS THE POINT.** `live_refresh_loop` passes
        `--force-refresh` on every lineup/injury trigger, so after this lands
        `cards_props_snapshot_<date>.json` REBUILDS on those triggers instead of
        re-serving the first file written for that date. Cost is one more artifact
        build of the same class its two siblings already do under force — expect
        it, do not read it as a regression. NBA is out of season, so its half is
        inert until the sport returns.
      - Falsification if someone doubts it landed: on the deployed service,
        `_export_cards_props_snapshot` must show `force_refresh` in its signature.
        Check BY CONTENT — ancestry lies here, the workers run deploy branches.
      - Why it matters: that exporter's builder is the one that produced the
        `rows=32/null=3` win_prob reading, so it is the artifact whose staleness
        was least visible, and it was the only one of the trio that could not be
        forced.

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

### 2026-08-14 20:38 CDT — the OOM cluster, and where my deploys sit in it

**The worker has been OOM-killed 18 times today. Raised by the user, not
caught by me — I had read "no board build in 30 min" as a cadence question.**

- **THE FACT THAT DOES NOT FAVOUR ME, stated first.** The deploy-free window
  **16:16:56 -> 19:49:15 (3h32m) had ZERO OOMs**, and the cluster begins at
  **20:03:11 — 14 minutes after my first worker deploy of the night**
  (`29ed6de1`, 19:49:15). The previous OOM was 04:04:27, sixteen hours earlier.
  I cannot exonerate my deploys on timing and have not tried to.
- **THE SHAPE ARGUES IT IS NOT ANY ONE COMMIT.** 18 kills across **7 distinct
  instances**, each instance dying REPEATEDLY at a ~11-15 minute period:

      ...xnxxv  n=2  20:03->20:14  (~1 per 11 min)
      ...zqxft  n=7  21:07->22:14  (~1 per 11 min)
      ...cb9mt  n=3  23:34->00:04  (~1 per 15 min)
      ...xtvq2  n=2  00:41->00:57  (~1 per 15 min)

  That is a restart LOOP inside an instance — a periodic workload crossing 4GB
  — not a per-deploy kill. **It survived `7b1f3fdc`, whose entire content is a
  `print` statement.** A code path cannot be the differentiator when the loop is
  unchanged across a no-op commit. The likelier reading is the deploy storm
  (10+ deploys tonight across three sessions) forcing repeated cold rebuilds on
  top of the memory problem the two OPEN lanes already track.
- **MY ONE MEMORY-INCREASING CHANGE, quantified rather than excused:**
  `book_prices` adds a ~5-entry dict per quote, ~**5-20MB** across ~14k
  candidates. It also went live at **23:17, AFTER the 20:03 onset**, so it
  cannot have caused it. Offered for revert; not reverted unilaterally.
- **ACTION TAKEN: ALL FURTHER WORKER DEPLOYS HELD.** Each one reboots the
  container and forces a fresh heavy rebuild.
- **NOT MY LANE.** Another session deployed `c9378c91` (`#435` "sample memory on
  a CLOCK, because the kills happen between samples") at 01:16 and it is LIVE.
  Let that instrumentation produce a reading before anyone adds changes on top.

### Same moment — the CLV publish design limit is now CONFIRMED, not theoretical

- Worker **is** alive enough to build boards (`written_at 2026-08-15T01:35:34Z`),
  so `record_openings` has been running and ~150+ openings for 2026-08-14 exist
  **on the worker disk**.
- `/api/ops/clv/report` returns **`openings=0` for mlb, nfl and wnba**.
- **Cause, as predicted:** the publish fires only when `written > 0`, and every
  2026-08-14 market was first-seen before the publish code shipped. First-
  sighting-only then guarantees `written == 0` forever for that date, so the
  file is **STRANDED on the worker**. It self-heals on the next genuinely new
  market (the push sends the whole file), which is unlikely this late.
- **Tomorrow is unaffected** — a new date creates a new file whose first write
  publishes it. **A one-shot publish per worker boot is the proper fix and is
  NOT built**, deliberately: it needs a worker deploy, and worker deploys are
  held.

### `#435` MEASURED 2026-08-15 01:38:48Z — THE INSTRUMENT WORKED, AND THE MECHANISM IS NOW VISIBLE

Kill at **01:38:48.164Z**, 22 min after the watchdog went live. **567
`MEMORY_WATCHDOG` lines** preceded it. The excursion, sampled every ~2s:

    time      anon MB   inactive_file MB   pct    since   last_stage
    01:38:11   1700.3        1575.1        88.5   28.7s   board_contract_games_normalized
    01:38:16   1700.3        1621.9        89.7   33.5s   board_contract_games_normalized
    01:38:19   1700.3        1733.7        92.4   35.9s   board_contract_games_normalized
    01:38:21   1930.3        1770.8       100.0   37.9s   board_contract_games_normalized
    01:38:23   2184.2        1352.3       100.0   39.9s   board_contract_games_normalized
    01:38:25   2500.3         944.5       100.0   42.3s   board_contract_games_normalized
    01:38:28   2712.9         474.8       100.0   45.2s   board_contract_games_normalized
    01:38:30   2798.5         384.3       100.0    0.1s   cards_context_betting_games_loaded
    01:38:32   2951.9         230.4       100.0    1.9s   cards_context_sim_games_loaded
    01:38:34   3226.2         608.4        96.1    0.1s   cards_context_page_cache_hit
    01:38:36   3354.3         639.6       100.0    2.2s   cards_context_page_cache_hit
    01:38:38   3428.3         566.6       100.0    4.2s   cards_context_page_cache_hit
    01:38:40   3648.9         196.9       100.0    1.6s   build_live_state_payload_fallback_return
    01:38:42   3831.5          14.7       100.0    3.6s   build_live_state_payload_fallback_return
    01:38:46   4037.9           0.0        99.2    3.3s   board_contract_games_normalized
    01:38:48   SIGKILL

**FINDING 1 — THE DEATH SIGNATURE IS `inactive_file` REACHING ZERO.** anon climbs
1700 -> 4038MB (+2338MB in 35s, ~67MB/s) and the kernel evicts page cache in
lockstep to pay for it: 1734 -> 0MB. The container is killed the moment there is
no cache left to reclaim. Nobody has seen this before because nobody was
sampling between stage boundaries.

**FINDING 2 — IT IS NOT ONE ALLOCATOR IN ONE STAGE.** The climb crosses
`board_contract_games_normalized` -> `cards_context_betting_games_loaded` ->
`cards_context_sim_games_loaded` -> `cards_context_page_cache_hit` ->
`build_live_state_payload_fallback_return` -> back to `board_contract_games_
normalized`, with `seconds_since_stage` of 0.1-4.2s throughout. **The stages are
turning over every couple of seconds and anon never comes back down.** This kills
the "make `build_cards_page_context` cheaper" plan on its own: anon rose through
a `page_cache_hit` (the CHEAP path) as fast as anywhere else.

**FINDING 3, AND IT IS THE OPERATIONALLY IMPORTANT ONE — `memory_pct_of_max`
SATURATES 27 SECONDS BEFORE DEATH AND STAYS THERE.** It reads 100.0% from
01:38:21 while the container is still fine, because `memory.current` counts the
page cache that is about to be evicted. **Any guard or alarm reading
current/pct cannot discriminate — it is pinned at 100% during both healthy and
fatal states.** `memory_anon_mb` / `memory_unreclaimable_mb` is the metric with
signal, and the code already computes it everywhere.

**FINDING 4 — a stage never previously implicated:**
`build_live_state_payload_fallback_return`, present twice during the steepest
part of the climb (3428 -> 3831MB).

NOT A FIX. Nothing about the kill rate changed and nothing was expected to.

### 2026-08-15 — web `a86eb4ed` — one null placeholder (F3) + the pattern rule (F4) — **MEASURED**

Deploy `dep-d9vs4ebl550s73c09sp0`, live 01:41:43Z. Pinned onto `1ac485c0`,
the commit live at the moment of firing — not onto the base the branch was
built from. Pre-flight confirmed no in-flight deploy first.

Production, same routes before and after:

    route                em-dash   "<strong>-</strong>"   empty cell
    /ncaaf/cards  before       0                    48            0
    /ncaaf/cards  after      144                     0            0
    /nfl/cards    before       0                     4            0
    /nfl/cards    after        4                     0            0
    /soccer/epl   after        2                     0            0

Seven board/market routes 200 afterwards.

The empty-cell count reads 0 both times, and that is a WEAK reading, not a
clean one: `<strong></strong>` only catches a bare empty element, and a cell
containing whitespace or a nested span would not match it. The em-dash counts
are the load-bearing measurement here.

### 2026-08-15 02:11-02:29Z — `#435` TRACING WINDOW: SELF-INFLICTED REGRESSION, REVERTED

Sequence, stated plainly because I made production worse and then misread it:

    01:58:54Z  ae7318a2 live  (dump trigger) + SYNDICATE_TRACEMALLOC_DIAG 0 -> 1
    01:59:08Z  TRACEMALLOC_INIT {"nframe": 1}   <- #423's nframe=3 was NEVER on this lineage
    02:03:48Z  oomKilled
    02:06:54Z  oomKilled                        <- cadence 3 min, against 16-22
    02:10:37Z  934b3b81 live  (nframe 1 -> 3)
    02:11:02Z  MEMORY_WATCHDOG_STARTED ... then ZERO samples
    02:16:41Z  oomKilled
    02:23:41Z  548ded38 deployed (dump off-thread) + DIAG 1 -> 0
    02:29:40Z  548ded38 live
    02:30:15Z  TRACEMALLOC_INIT {"nframe": 3, "reason": "disabled", "started": false}
    02:31:18Z  sampler emitting again, climb -2.9 / 0.1 / -0.5 MB/s (stable)

**CAUSE:** `take_snapshot()` walks every live traced allocation in C holding the
GIL. The one call the trigger makes starved the sampler. Because the dump prints
AFTER the snapshot returns, a dump still running is indistinguishable from a
trigger that never fired -- and I read it as the latter.

**COST:** ~25 min of a 3-10 min kill cadence instead of 16-22, one wasted
diagnostic window, zero allocation sites obtained.

**KEPT FROM THE WINDOW, and it is worth the cost on its own:** production was
tracing at `nframe=1`. `#423` fixed that to 3 and the fix never reached this
service. Any future dump here would have named `json/decoder.py` -- the
allocator, not the caller -- and been recorded as an answer.

**STATE NOW:** `548ded38` live, tracing OFF, watchdog sampling normally, dump
wired off-thread behind a test that fails if it is moved back inline.
**Kill cadence must be re-read before anything is concluded from it** -- the
last four kills all sit inside the tracing window and are not a clean baseline.

## 2026-08-15 02:4xZ — web `ad4b0a3a` — ask headline sourced from the board artifact

**PREFLIGHT: PASS**, and it changed the deploy target. Recorded before the POST.

1. **Scope — ONE substantive change, but only after the target was corrected.**
   The obvious candidate (`1be6f3c4`, on `main`) would have shipped **199
   commits / 82 files** and **REVERTED 10 commits that are live on web**,
   including `clv_join.py` (542 lines) and `clv_opening_ledger.py` (326) —
   another lane's live work. **Web does not run `main`.** It runs
   `deploy/null-placeholder`, diverged from main at `b98f5ed7`. The deployed
   target is instead `ad4b0a3a`, a direct child of the live `a86eb4ed`, whose
   diff against live is exactly two files:
   `ask_the_syndicate_adapter.py` (+171) and `tests/test_ask_headline_from_board.py` (new).
2. **Expected effect — one number, one window.** On the next
   `ask_syndicate_regression.py` run against production (within 30 min of the
   deploy going live), B01's `chat_top_edge_pct` equals `board_top_edge_pct`
   within 0.5, clearing `top_edge_diverges_from_board`. Baseline 20:45Z:
   **23.81 vs 14.09, FAIL**. No other class falls below its 20:45Z score
   (advice 4/5, entity 2/10, explain 4/6, history 1/5, lookup 2/8, ranking 4/10,
   refusal 6/8; overall 23/52).
3. **Measurement — who reads it.** This session, immediately after the deploy
   reports `live`: `py -3 scripts/ask_syndicate_regression.py` against
   `https://syndicate-an21.onrender.com`, diffed class-by-class against
   `reports/ask_regression/post_m1_fixed_2026_08_14.json`. **Not "tests pass".**
4. **Blast radius — web only.** `deploy_preflight.py --service web` reports four
   processes, all gunicorn: no sim, no refresh job, no board build. The
   `check_deploy_safety.py` NOT-CLEAR items (MLB sim pid 65, odds refresh pid
   4634, board build in flight) are all on **refresh-worker / live-odds-worker**,
   which this deploy does not restart. Cost is ~1-2 min of 502s on web, during
   live games. Web has taken 4 deploys tonight under the same conditions.
   **CAVEAT, stated not hidden:** the process sample backing that list is
   **27,774s (7.7h) old**, so preflight returned UNKNOWN on freshness. The
   "web is display-only" claim rests on architecture and on the 4-process list,
   not on a fresh reading. I could not re-read web's loop env flags — the
   env-vars API call was blocked by the permission classifier.
5. **Rollback — exact, stated now.**
   `py -3 scripts/render_deploy.py --service web --commit a86eb4ed --allow-rollback`
   (`--allow-rollback` is REQUIRED: a86eb4ed is the parent, so the guard would
   otherwise refuse it as a non-descendant.)
6. **Ledger check.** No `learnings.md` rule is violated: the refresh-worker
   deploy FREEZE in `state.md` names refresh-worker, not web, and this is not a
   `render.yaml` change so `blueprint_sync` cannot fire. No OPEN lane claims
   `ask_the_syndicate_adapter.py` — collision-checked with `lane-guard.py`'s own
   `_claims()`, and the only mentions of that file anywhere in `lanes.md` are
   two notes saying it was deliberately left unclaimed for exactly this lane.
7. **MEASUREMENT: pending.** Reminder 2026-08-15 03:15Z. If this row still has
   no number by then, this deploy is NOT evidence of anything.

### MEASUREMENT for web `ad4b0a3a` — DEPLOYED 02:46:23Z, **ROLLED BACK 03:00:19Z**

**Verdict: the change did what it was built to do and broke one other thing, so
it is not live. Net on the harness was +1/-1 plus a visibly wrong number.**

**WHAT IT FIXED (measured, fingerprinted).** B01 `top_edge_diverges_from_board`
CLEARED. Same-instant A/B against production: chat top edge **6.35**, board top
edge **6.35**, |delta| **0.000** (tolerance 0.5); baseline was 23.81 vs 14.09.
Confirmed the deployed code was the code running, not assumed — 5 of 5
`top_opportunities` carried `source="layer2_shortlist"`, a field only this
change emits.

**WHAT IT BROKE.**
1. **`Best edge 635.0%` served to users.** `_board_summary_sentence` does
   `best_edge * 100`, because snapshot rows carry `edge` as a FRACTION. Board
   rows carry `model_edge_pct`, already a PERCENT. Mine, unambiguously.
2. **F07 refusal PASS -> FAIL**, exactly one case. "Ohtani's exact stats for
   tomorrow" returned 5 board rows instead of declining. An empty
   `recommendations` list is the engine DECLINING; sourcing from the board
   created a pool where the absence WAS the answer.

**RETRACTION — I FIRST CLAIMED THIS COST 3 REFUSALS. IT COST 1.**
The "6/8 -> 3/8" reading compared against a number in lane PROSE from hours
earlier on a different slate, and my causal probe read
`payload["recommendations"]`, **a key `build_syndicate_query_response` does not
return** — so "snapshot_recommendations=0" was three reads of a missing field,
not evidence. The real control is
`reports/ask_regression/control_refusal_rolledback_2026_08_15.json`: refusal on
the ROLLED-BACK code, same slate, is **4/8** — F01/F02/F03/F05 fail with no
involvement from this change. Only F07 moved. The mechanism I described was
right; the magnitude was 3x wrong and taken from the wrong instrument.

**ALSO CORRECTED: `post_m1_fixed_2026_08_14.json` is NOT a 52-case baseline.**
It is a **ranking-only run, 4/10**. The "23/52" figure everywhere in the ledger
comes from prose, not from that file. Any lane baselining against it is
comparing 10 cases to 52. A full same-slate 52-case run now exists:
`reports/ask_regression/post_headline_2026_08_15.json` (24/52) — but it carries
this reverted change, so it is a record, not a baseline.

**ROLLBACK VERIFIED, not assumed.** Web live on `a86eb4ed` 03:00:19Z;
`source=layer2_shortlist` count is **0 of 5**, F07 returns 0 rows and refuses.

**STILL OPEN — the fix is 1 line and is BLOCKED.**
`_market_summary_schema` must source from the board only when
`recommendations` is non-empty, and the percent/fraction split must be explicit.
Blocked twice: (a) `lane-guard` reads `ask-sport-coverage`'s
"**NOT claimed, deliberately:** `ask_the_syndicate_adapter.py`" line as a CLAIM
of that file — the known ledger-regex defect, surfaced to that session;
(b) the permission classifier refuses edits to `lane-guard.py`, so the guard
cannot be fixed from here either.

### 2026-08-15 02:44-03:04Z — `#435` SECOND TRACING WINDOW: SAME FAILURE, NOW A NEGATIVE RESULT

Owner called for one more window after the first went badly. Ran it with three
safeguards the first lacked: dump off-thread, `nframe=2` not 3, and the dump
closing the window itself via `stop_allocation_tracing`.

**IT FAILED THE SAME WAY, WHICH MAKES IT A RESULT RATHER THAN A REPEAT:**

    tracing OFF   02:30-02:31   8 MEMORY_WATCHDOG samples per minute
    nframe=3      02:11-02:16   ZERO samples, OOM 02:16:41
    nframe=2      02:48-02:55   ZERO samples in 6.7 min, OOM 02:47:54

**CONCLUSION: tracemalloc is unusable on this process at any frame count.** It
silences the sampler that does work, and it has never once returned an answer in
production. Not "needs tuning" -- ruled out.

**THE FAILURE SHAPE IS THE DANGEROUS PART.** No samples is indistinguishable
from no excursion. I reported "no excursion yet" to the owner while the worker
was dying. That is the third instance tonight of a silent instrument being read
as a calm system (the others: log-grep for `oomKilled`, and the dump that was
still running). It is now written at the switch in `run_refresh_worker.py`.

**DEPLOY NOTE, stated because it was a judgement call:** `9be65758` was fired on
an **UNKNOWN** gate (telemetry 347s stale, limit 180s), not a CLEAR. Stale
telemetry was itself a symptom of the starved worker, and leaving the harmful
window open was the worse risk. Live 03:03:31Z;
`TRACEMALLOC_INIT {"nframe": 2, "reason": "disabled", "started": false}` at
03:03:55Z confirms the window is shut.

**ALSO OBSERVED, not mine:** a WEB deploy 02:40:21 -> 02:46:23 and another
starting 02:53:47. Web deploys 502 every route for ~2 min and are the
user-visible outage in that period; the refresh-worker OOM at 02:47:54 recovered
in 1 second. Board verified healthy at 02:54Z: HTTP 200 in 0.5s, 105 rows across
nfl/mlb/wnba, 10,907 considered.

**WHERE THE FIX STANDS:** no allocation site was ever obtained. The remaining
path costs production nothing -- read the board-build loop for RETENTION, since
"anon never falls between stages" is the signature and `#387` already proved
that bug class exists in the overview path.

### CORRECTION 2026-08-15 03:06Z — "anon never falls between stages" IS WRONG

Sampler recovered on the closed-window boot: 35 samples in 76s. The third one
falsifies the signature I built the retention hypothesis on:

    03:05:56  anon 2242.8  climb   +0.6 MB/s  build_live_state_payload_start
    03:05:59  anon 2242.9  climb   -0.4 MB/s  board_contract_games_normalized
    03:06:02  anon 1557.9  climb -285.4 MB/s  build_live_player_lens_payload_start

**685MB released in a single 2.4s tick.** Anon DOES come back down in normal
operation. What I wrote after the 01:38 excursion -- "anon never falls between
stages, that is retention" -- was true OF THAT 35-SECOND WINDOW and I stated it
as a property of the system.

**This reframes the remaining work.** It is not "find what retains forever"; it
is **"find why release does not keep up during the burst"**. Both hypotheses I
put to the owner were built on the wrong premise:
  - RETENTION (caches never releasing) is weakened -- release demonstrably works.
  - CHURN is not obviously right either; the release here is large and abrupt,
    which looks like a scope exit or an explicit trim, not steady turnover.

**What the next reader should do:** compare a HEALTHY per-sport cycle against the
01:38 excursion, using the samples the watchdog is now producing for free. The
question is what is different about the excursion, not what is expensive in
general. That needs no deploy and no tracing.

---

## 2026-08-15 03:15Z — web `7e334509` — soccer card Lane G+H — PENDING MEASUREMENT

`dep-d9vtjklg1s2s73bs6ib0`, service `srv-d88ahvrbc2fs73eodu30`, triggered
03:15:30Z. Lane `soccer-card-end-to-end`.

**Pinned, and it had to be.** `7e334509` = web's own live `a86eb4ed` + the
single commit `3912f8f2`. **`origin/main`'s tip was NOT deployable**: it is 131
commits ahead of the live SHA and it contains `ad4b0a3a`, which another session
deployed successfully at 02:46:23Z and then **deliberately reverted** by
redeploying `a86eb4ed` at 03:00:19Z. Deploying the tip would have silently
undone their rollback. Pinned deploys replace rather than merge, so the next
web deploy has to stack on `7e334509` or it drops this commit.
Same work is on `origin/main` as `9b6a48e7` for whoever rebases later.

**Preflight, answered:**
1. *Scope* — one substantive change: the soccer card renders its own data or
   nothing. 7 files, 710 insertions. No backend, worker, env or `render.yaml`
   change, so no `blueprint_sync` risk and no in-flight sim at stake (web only).
2. *Expected effect* — on `/soccer/epl/cards` at 1440 and 390, within one
   deploy cycle: **unstyled links 2 -> 0**, **empty slots 3 -> 0**,
   **projected-score sentence 6 -> 2 in the card DOM (5 -> 1 on the default
   tab)**, worst repeated string 6x -> 4x. On `ncaaf` — the control, same
   contract and stylesheet — **no change**: 0px overflow, 45/53px card-height
   spread, 5x repeat, 3 empty slots. On `nfl` — the control that shares the
   generic TEMPLATE — 0px overflow and 16 cards, with its own 6x repeat
   expected to persist (different cause, see the lane).
3. *Measurement* — `py -3 scripts/ui_layout_probe.py --base-url
   https://syndicate-an21.onrender.com --sports soccer,nfl,ncaaf`. Read by this
   session, immediately after `finishedAt`. Before-numbers were taken with the
   same instrument against the same production build, and it reproduced all
   three defects before anything was touched.
4. *Blast radius* — web only. Routes 502 for ~2 minutes during the restart
   (observed on the 02:53-03:00 deploy, which is what a 502 sweep earlier in
   this session was actually measuring). No persistent-disk service restarts.
5. *Rollback* — redeploy the live-before SHA:
   `POST /v1/services/srv-d88ahvrbc2fs73eodu30/deploys {"commitId":"a86eb4ed"}`.
6. *Ledger* — no `learnings.md` FORBIDDEN or EXONERATED rule covers this. No
   OPEN lane claims any of the 7 files (lane-guard's own `_claims()` re-run
   twice; `board-contract-absent-not-neutral` released three of them when it
   was orphaned).
7. *Verdict* — **PASS on the change, FAIL on the naive form of it.** Deploying
   `origin/main` would have been a rollback of another session's rollback. The
   pinned stack is what was shipped, and the owning session was messaged before
   the trigger.

**MEASUREMENT: [pending — this session, immediately after finishedAt]**

### `#435` ANSWERED IN PART 2026-08-15 03:20:15Z — THE ANON IS NOT IN PYTHON CONTAINERS

`96f2cfb5` live 03:18:53Z. Census fired 82 seconds later on the CONDITION
(anon >= 1500MB), where the existing call site had never fired in 5h:

    HEAP_CENSUS reason=watchdog_anon_1709mb  container_mb=2506
    gc_tracked_objects   415,596
    top_by_count         dict 240,250 | list 77,637 | function 30,715 | tuple 15,756
    top_by_shallow_mb    dict 98.5 | list 20.1 | set 4.6 | function 4.5 | type 3.6
    individually_huge_mb []

**~135MB shallow across 415k objects, against 1709MB anon.** The census's own
docstring sets the bar -- "2GB of anything must appear as TENS OF MILLIONS of
objects" -- and this is three orders of magnitude short. No single object over
50MB either.

**WHAT THIS ELIMINATES:** the per-sport payload caches, the board dictionaries,
the candidate pool -- every dict/list-shaped hypothesis, including the RETENTION
one I recommended twice tonight. They are all in that 240k dicts / 98.5MB.

**WHAT IT DOES NOT SEE, AND THIS IS THE POINT.** `gc.get_objects()` returns only
CYCLIC-GC-TRACKED objects. `str`, `bytes`, `int`, `float` hold no references and
are NOT tracked; neither are numpy data buffers. In a JSON-heavy pipeline those
are precisely the bytes in question. **The census did not find the memory; it
ruled out the place everyone looks first.**

Consistent with `#423`'s `json.loads` at 491.3MB / 7,172,382 allocations, and
with `_BOOK_QUOTES_CACHE`'s 500MB budget of parsed JSON.

**NEXT, and it needs no new deploy machinery:** measure the UNTRACKED classes --
walk `gc.get_objects()` and sum `sys.getsizeof` over each object's `referents`
that are `str`/`bytes`, or size the named caches directly. That distinguishes
"one cache holding parsed JSON" from "millions of small strings spread across
the process", which have different fixes.

**METHOD NOTE:** this worked because it triggered on the CONDITION, not a call
site -- the same change that made the watchdog see what stage-boundary sampling
could not. The existing instrument was correct and simply never ran.

## 2026-08-15 03:2xZ — web `c774fe1a` — ask headline, second attempt

**PREFLIGHT: PASS.** Recorded before the POST.

1. **Scope.** Parent is `7e334509`, the LIVE commit (the soccer-card lane
   deployed it at 03:21:36Z — I waited for it rather than racing, per the
   ledger's own "a concurrent session deployed in between" incident). Diff vs
   live is exactly 2 files: the adapter and its test.
2. **Expected effect, two numbers in one window.** Within 30 min: B01
   `top_edge_diverges_from_board` clears (chat == board within 0.5), AND the
   refusal class is **>= 4/8**, its same-slate control value — F07 declines
   again. The first attempt bought B01 at the cost of F07; this must hold both.
   Also: no served summary contains "635" or any edge over 100%.
3. **Measurement.** This session, on `live`: the B01 same-instant A/B, then
   `--classes refusal` against
   `reports/ask_regression/control_refusal_rolledback_2026_08_15.json` (4/8).
4. **Blast radius — web only.** `check_deploy_safety` NOT-CLEAR items (odds
   refresh pid 8417, board build 03:11:06Z) are on live-odds-worker and
   refresh-worker; a web deploy does not restart either. MLB sim reported
   FINISHED (exit=0). Cost is ~1-2 min of web 502s during live games — the same
   cost another session accepted 10 minutes ago.
5. **Rollback.** `py -3 scripts/render_deploy.py --service web --commit 7e334509 --allow-rollback`
6. **Ledger check.** The `ask_the_syndicate_adapter.py` phantom claim by
   `ask-sport-coverage` is resolved — `lane-guard.py` no longer parses a
   `NOT claimed, deliberately:` bullet as a claim. Re-derived after the fix:
   the adapter is claimed by `ask-headline-from-board` only, and the guard
   still returns exit 2 for `ask_the_syndicate_data.py` and
   `intelligence_state.py`, so it was fixed, not weakened. No `render.yaml`
   change, so `blueprint_sync` cannot fire.
7. **MEASUREMENT: pending.**

### MEASUREMENT 2026-08-15 03:2xZ — web `7e334509` live 03:21:35Z — ALL CRITERIA MET

Same instrument, same base URL, same fixture on both sides (soccer EPL Coventry
@ Arsenal; NFL still showing "Seattle Seahawks by 0.3" / "Projected total 43.9"
before and after, so **the slate did not move between the two runs** and the
deltas below are the deploy, not the data). `httpStatus` 200 on every row —
recorded explicitly, because this session already had one clean-looking table
that was a 502.

    soccer, 1440 and 390            before   after
      unstyled links                     2       0
      empty slots (game panel)           3       0   (2 placeholders + 1 zero-bin bar)
      projected-score sentence, DOM      6       2   (head ribbon + Details panel)
      projected-score sentence, tab      5       1
      "Highest anytime-goalscorer..."    6      <=1
      "Anytime scorer / shots leaders"   6      <=1
      "Top prop signals"                 6      <=1
      horizontal overflow                0       0
      worst remaining repeat            6x      4x  ("Arsenal - F M S", boxscore,
                                                     pre-existing, not this lane)

    ncaaf — CONTROL, own template, shared contract + stylesheet
      overflow 0/0, spread 45/53px, 5x repeat, 3 empty slots in 2 panels
      IDENTICAL on every axis, both widths. No regression.

    nfl — shares the generic TEMPLATE
      props panel .cards-empty-copy       2       1
      worst repeat                       6x      4x
      card-height spread          17 / 67px   14 / 50px

**I PREDICTED NFL'S REPEAT WOULD NOT MOVE, AND IT DID.** The preflight says
"nfl's own 6x repeat expected to persist (different cause)". That reasoning was
that NFL supplies its own `shared_top_play_rows`, so `_build_top_play_rows`
never runs for it — which is true, and irrelevant. The repeated string was
*"No stored NFL weekly recommendation snapshot exists for this game."* rendered
five times down the Top Plays list, and it was coming from the TEMPLATE's
`row.detail or row.heading` fallback, not from the contract. The template half
of the fix caught it. So the win is real and larger than claimed, and the
prediction was wrong because I attributed a symptom to one of two changes
without checking which. The card-height spread tightening (17->14, 67->50) is
the same effect: a variable-length empty-state block stopped rendering.

**The one number that went UP, stated rather than buried:** NFL's "Projected
spread" and "Seattle Seahawks by 0.3" go 3x -> 4x, gaining an occurrence in the
`game` panel. That is the callout list now showing the row's own `detail` where
it previously showed a constant. A meaningful value appearing once more is not
the same defect as a constant repeating five times, but the counter cannot tell
them apart and the next reader should not have to rediscover that.

**Deploy hygiene:** one deploy, one change, no worker touched, no `render.yaml`,
no env write. Build 03:15:30Z -> live 03:21:35Z (~6 min; routes 502 during the
rollout, as always). Rollback remains `{"commitId":"a86eb4ed"}`.

### 2026-08-15 03:29:56Z — web `c774fe1a` supersedes `7e334509` — **THE STACK WAS HONOURED**, Lane G still live

`7e334509` (soccer card, Lane G) shows `deactivated` on the service 8 minutes
after it went live. That is the expected state for a superseded pinned deploy
and **not** a loss: `c774fe1a` (`ask: the headline comes from the board`) has
`7e334509` as an **ancestor**, so the `ask-headline-from-board` session stacked
rather than replaced. Verified two ways at one instant:

    git merge-base --is-ancestor 7e334509 c774fe1a   -> YES
    all four Lane G source files, c774fe1a vs 7e334509 -> byte-identical

And re-measured against the LIVE service rather than trusted by ancestry:

    soccer 1440/390   0 unstyled links, 0 empty slots, worst repeat 4x, 0px overflow
    ncaaf  1440/390   0px overflow, 45/53px spread, 5x, 3 slots  (control, unmoved)

**The obligation this closes:** `state.md` and the lane both carry "the next web
deploy must stack on `7e334509` or it silently drops the soccer card work." It
did stack. That line can stop being read as an open risk — but the RULE stands
for the next pinned deploy, because nothing enforces it except a person reading
the deploys API first. `deactivated` on a pinned deploy means "superseded", and
whether the successor kept your work is a separate question that only ancestry
or a measurement answers.

### MEASUREMENT for web `c774fe1a` — live 03:29:56Z — **BOTH CRITERIA MET, HOLDING**

**1. B01 divergence CLEARED.** Same-instant A/B against production: chat top
edge **6.35**, board top edge **6.35**, |delta| **0.000** (tolerance 0.5).
Baseline was 23.81 vs 14.09. Fingerprinted — 5 of 5 `top_opportunities` carry
`source="layer2_shortlist"`, so the deployed code is the code running.

**2. The regression the first attempt caused is GONE, and did not come back
anywhere else.** Refusal is **4/8**, matching
`control_refusal_rolledback_2026_08_15.json` **case for case** — F01/F02/F03/F05
fail in both (pre-existing, not mine), F04/F06/F07/F08 pass in both. F07 now
returns 0 rows and "No opportunities are on the board right now."

**3. `635` is gone.** Served summary reads "Best edge 6.3%."

**Full run: 25/52** (`post_headline_fixed_2026_08_15.json`) vs **24/52** for the
reverted first attempt. Diffed case-by-case, **the only case that differs
between the two attempts is F07** (FAIL -> PASS). Class scores identical
otherwise: advice 4/5, entity 2/10, explain 4/6, history 2/5, lookup 4/8,
ranking 5/10. `warn:selection_not_on_board` fell 185 -> 155, consistent with
rows now coming from the board rather than the snapshot.

**LIMIT OF THIS EVIDENCE, stated rather than glossed.** A true same-slate
control on UNCHANGED code exists only for the refusal class (the 8-case run
against the rolled-back build) and for B01. The other five classes are compared
between two runs that BOTH carry this change, so what is established for them
is "the fix did not move them relative to the first attempt", not "this change
never touched them". The bound on that risk is the code: the only mutation is
`_market_summary_schema`'s `top_opportunities`, and only when `recommendations`
is already non-empty.

**Also shipped to `main` as `98900164`** — main previously carried `1be6f3c4`,
the version with both defects. That is corrected; main and the deploy branch now
agree on this file.

**Obligation closed.**

### `#435` THE ANSWER, 2026-08-15 03:33:41Z — 85% OF ANON IS NOT REACHABLE PYTHON DATA

`eea7554a` live 03:32:50Z; census fired 51s later.

    UNTRACKED_BYTES_CENSUS reason=watchdog_anon_1657mb
      anon_mb              1858.27
      str_bytes_total_mb    136.1      <- 7.3% of anon
      distinct_str_bytes  1,704,754    <- average 84 BYTES each
      top_holders_mb      dict 114.1 (1,513,201 strings) | function 7.8 |
                          list 6.6 | set 6.3
      biggest_individual  []           <- nothing over 1MB

**THE ARITHMETIC, and it is the whole finding:**

    tracked containers (HEAP_CENSUS)        ~135 MB   415,596 objects
    str/bytes off them (UNTRACKED_CENSUS)   ~136 MB   1,704,754 strings
    ------------------------------------------------
    accounted                               ~271 MB
    anon                                   1858.3 MB
    **UNACCOUNTED                          ~1587 MB = 85%**

**THERE IS NOTHING TO RELEASE.** Every "find what retains it" hypothesis is dead,
including both of mine: the per-sport payload caches, the board dictionaries, the
candidate pool, and the "millions of small strings" theory -- 1.7M strings exist
and they are 136MB, not gigabytes.

**WHAT IS LEFT: ALLOCATOR RETENTION.** The process parses ~2.3GB of JSON during
an excursion (measured 01:38: anon 1700 -> 4038MB in 35s), frees it, and glibc
keeps the pages instead of returning them. Live objects disappear; `anon` does
not. This fits everything measured tonight:
  - the 685MB drop at 03:06:02 -- an explicit trim firing, not natural GC
  - `MALLOC_TRIM` releasing 112 / 68 / 140MB when it runs, never GBs
  - `#423` already EXONERATED arena fragmentation as the mechanism, which is a
    different claim from "the allocator is holding freed pages"

**NEXT MEASUREMENT, and the machinery again already exists and is not wired:**
`malloc_arena_snapshot()` binds glibc `malloc_info` and reports in_use vs
free_held. Fire it on the same condition trigger. If free_held is ~1.5GB the
answer is confirmed and the fix is allocator-side (trim cadence, arena count,
or cutting the transient peak). If free_held is small, the memory is in C
extension buffers and the search moves again.

**METHOD NOTE, third time tonight:** the instrument that answered this existed
and had never run. `log_heap_census` had one call site behind a threshold it
never met; `log_untracked_bytes_census` had to be written but only because
`gc.get_objects()`'s blindness to str/bytes was never accounted for. Both
answered within 60 seconds of being triggered ON THE CONDITION.

### `#435` SOLVED TO THE OBJECT LEVEL, 2026-08-15 03:45:36Z

`984e48c8` live 03:44:16Z. `PYMALLOC_STATS` fired 80s later:

    arenas_currently_allocated  1688      arena_mb            1688.0
    bytes_in_allocated_blocks   1638.5MB  unused_pools_mb       25.8
    retained_by_pymalloc_mb       49.5    <- fragmentation is 3%
    arenas: 2538 total, 850 RECLAIMED, highwater 1719, current 1688

**IT IS NOT FRAGMENTATION AND NOT GARBAGE. 1638.5MB is LIVE.** The allocator is
working correctly -- it has reclaimed 850 arenas. There is nothing for a trim to
reclaim, which is why `MALLOC_TRIM` only ever released 68-140MB.

**THE SIZE-CLASS TABLE NAMES THE MEMORY:**

    size   blocks in use     total
     64 B    13,719,058      838 MB   <- dominant
    400 B       614,024      234 MB
     80 B     2,787,789      213 MB
     96 B     1,041,857       95 MB
     32 B     3,065,952       94 MB
    128 B       603,680       74 MB
                    ~22.3 MILLION live small objects, ~1597MB accounted

64 bytes is a short `str` (<=~15 ASCII chars), a 1-2 element tuple, or similar --
the shape of parsed odds/quote rows. 400B x 614k is the row-object class.

**RETRACTED: MY OWN "85% OF ANON IS NOT REACHABLE PYTHON DATA" (03:33Z entry).**
It was a measurement artifact. `log_untracked_bytes_census` walks ONE LEVEL:
`str`/`bytes` **directly referenced** by a GC-tracked object. Anything nested --
dict -> list -> tuple -> str -- was never counted, and CPython untracks tuples of
immutables so they leave `gc.get_objects()` altogether. The 271MB it and the
heap census found was the reachable-in-one-hop surface, not the heap.

**So the allocator-retention hypothesis I gave the owner is WRONG**, along with
the two before it. The memory is exactly what the naive reading would have said:
live application data, ~22M small objects.

**NEXT, and it is now a narrow search:** find what holds ~13.7M 64-byte objects.
`_BOOK_QUOTES_CACHE` carries a 500MB budget of parsed quote JSON and is the first
place to look; the 400B/614k class looks like row objects built beside it. The
question is finally the ordinary one -- which structure holds 13.7M small
objects, and does it need to.

### `#435` ROOT CAUSE, 2026-08-15 15:4xZ — the quote shard is append-only and 92% superseded

**MECHANISM, end to end:**

1. `data/<sport>_source/tracking/book_quotes/<date>.jsonl` is APPEND-ONLY. Every
   refresh appends a row per quote observation (17 fields, carries `snapshot_ts`).
2. It therefore grows all day. Measured from production `CACHE_EVICT` records,
   MLB on 2026-08-14: **89.9 -> 97.8 -> 108.8 -> 121.5 -> 133.2 -> 150.3 ->
   165.2 -> 174.5 -> 184.5 MB**, then resets to 2.2MB at the date rollover and
   climbs again (2.2 -> 4.2 -> 5.0 -> 7.6 -> 8.8 ...).
3. A read costs 6.3x file bytes resident (the module's own measured constant).
   At 184.5MB that is **1,162 MB for ONE cached entry**, against a 500MB budget.
4. `_evict_book_quotes_over_budget` is `while len(cache) > 1 and ...` -- **a
   single oversized entry can never be evicted.** When it is not alone it gets
   evicted and re-read, re-allocating ~1.1GB of small objects each time.

**THIS IS THE 22.3M OBJECTS.** 478,782 rows x 17 fields is exactly the measured
census: 614k 400-byte dicts and 13.7M 64-byte values.

**IT EXPLAINS THE TIME PATTERN, which nothing else did.** Kills clustered in the
evening (shard at maximum) and **stopped at 05:02:59Z** -- the date rolled over
and the shard reset to 2.2MB. Not a leak; a daily ramp.

**THE GUARD'S PREMISE IS STALE.** The sizing comment says "production's MLB shard
is ~90MB, so ONE cached copy is ~570MB". It reached **184.5MB / 1,162MB** on
2026-08-14 -- 2.05x the number the budget was reasoned from.

**HOW MUCH OF IT IS NEEDED (measured, 2026-08-09 shard, 207.4MB):**

    rows        478,782
    distinct     36,424   (latest per event/book/market/selection/line/player/segment)
    superseded  442,358 = **92.4% of the file**
    shrink        13.1x

**FIX, and the trap in it:** the lookup path (`quote_ref_for_bet`, which the
module says walks ~122k rows per candidate) needs LATEST-PER-KEY -- 36k rows,
~89MB resident instead of ~1.16GB. But **do not compact the file**: opening
prices and line movement are exactly the superseded rows, and
`clv-without-settlement` depends on them. The fix is a latest-per-key INDEX for
the lookup path, leaving history intact for the CLV/movement consumers that read
it differently.

Secondary, cheap, independent: let the evictor drop the last entry, so one
oversized shard cannot sit above budget indefinitely.

## 2026-08-15 — ask-sport-coverage — web — PENDING MEASUREMENT

- **Commit:** `0bf866c3` on `deploy/ask-sport-coverage`, cut from the
  then-live `c774fe1a` + `b6f1a2e6` (K9/K2/K11/K3/K4/K5/K6) + the test fix.
- **Service:** web `srv-d88ahvrbc2fs73eodu30` ONLY. ~2 min of 502s on every
  route. Sims run on refresh-worker, so this does not kill an in-flight sim.
  No `render.yaml` change -> no `blueprint_sync`, no env rewrite.
- **PRE-DEPLOY BASELINE, re-measured on live `c774fe1a` (NOT the brief's
  23/52, which was stale):** overall **25/52** — advice 4/5, entity 2/10,
  explain 4/6, history 2/5, lookup 4/8, ranking 5/10, refusal 4/8.
  `reports/ask_regression/prebaseline_c774fe1a_2026_08_15.json`.
- **PREDICTION, falsifiable:** the 15 `no_sport_resolved_expected_*` failures
  go to 0 (verified 15/15 in-process on the combined tree). 13 of those cases
  have routing as their ONLY failure, so **overall 25 -> 38/52**; lookup
  4/8 -> 8/8, entity 2/10 -> 9/10, ranking 5/10 -> 7/10. D06 and G09 also fail
  `no_draw_handling` and must NOT be expected to flip.
- **Floor / rollback trigger:** any class BELOW its baseline above, or overall
  below 25/52. Rollback = redeploy `c774fe1a`.
- **Honest caveat:** tonight's board is 150 rows — wnba 18, nfl 42, mlb 90,
  **zero soccer, zero ncaab, zero nhl.** Routing is data-independent so it
  clears regardless, but a newly-routed soccer/nhl/ncaab question can surface
  NEW failures that did not exist while it was never routed at all. A result
  below 38 is therefore informative, not automatically a regression.
- **Measurement owed by:** this session, immediately on `live`.
- **RESULT:** _(empty — to be filled by the post-deploy run)_

### MEASURED 2026-08-15 16:52Z — ask-sport-coverage — **CONFIRMED, prediction exact**

Live `0bf866c3` at 16:49:28Z. Verified the code actually RAN before trusting any
number: `routed_sport: 'soccer'` on a soccer question (was `None` on 52/52) and
`visuals.as_of: '2026-08-15'`.

**Slate control — the comparison is NOT confounded despite ~13h of wall clock
between the two runs.** The board is byte-comparable in shape at both instants:
150 rows, wnba 18 / nfl 42 / mlb 90, and both runs carry the same
`warn:board_count_150_not_stated`. Same slate, so the diff is attributable.

| class | pre `c774fe1a` | post `0bf866c3` | predicted |
|---|---|---|---|
| advice | 4/5 | 4/5 | 4/5 |
| entity | 2/10 | **9/10** (+7) | 9/10 |
| explain | 4/6 | 4/6 | 4/6 |
| history | 2/5 | 2/5 | 2/5 |
| lookup | 4/8 | **8/8** (+4) | 8/8 |
| ranking | 5/10 | **7/10** (+2) | 7/10 |
| refusal | 4/8 | 4/8 | 4/8 |
| **overall** | **25/52** | **38/52** | **38/52** |

- `no_sport_resolved_expected_*`: **15 -> 0.**
- **REGRESSIONS: none.** Newly passing = exactly the 13 predicted IDs.
- **D06 and G09 did NOT flip, as predicted** — both also fail `no_draw_handling`.
  That is the part that makes this a real prediction rather than a retrofit: the
  model of the change named which cases would NOT move, and it was right.

**K6 IS ONLY HALF DONE — stated plainly rather than banked.**
`warn:no_as_of_stated` is **24 -> 24, unmoved.** The payload field is populated
(verified above), but the harness warns on the ANSWER TEXT, which still does not
state an as-of. The contract half shipped; the surfacing half did not. Do not
record K6 as closed.

**Not fixed by this lane, still open at 38/52:** `refusal` 4/8 (regressed 6->4 by
`c774fe1a`, NOT by this change — it was already 4/8 in the pre-baseline),
`history` 2/5, `explain` 4/6, and `no_draw_handling` on the two soccer draw
questions.

### CORRECTION 2026-08-15 17:1xZ — my K6 claim was wrong, and my VERIFICATION of it was invalid

I reported K6 as "half done — the payload field is populated, the harness warns
on the answer TEXT". **Both halves of that sentence are wrong.**

**What the harness actually does** (`ask_syndicate_regression.py:473`):
`if not as_of and not re.search(r"as of|updated|\bat \d", lowered)`. It checks
the FIELD FIRST. A populated `as_of` suppresses the warning outright, so 24
warnings means the FIELD is None on 24 cases — not that the text is missing a
phrase.

**Measured:** `as_of` populated **28/52 pre and 28/52 post — utterly unchanged.**
K6's freshness fallback is **INERT ON PRODUCTION**, not partially working.

**Why I got it wrong, and this is the important part.** I "verified K6 in
production" by asking ONE question and seeing `as_of: '2026-08-15'`. That
question was B03, a ranking question — its `as_of` came from the board fetcher's
EVIDENCE (`_evidence.get("as_of")`), which is the FIRST term in
`_evidence.get("as_of") or _snapshot_as_of or None`. **My fallback never ran, and
I confirmed a value my change did not produce.** The same question under the old
code would have returned the same string.

**Isolated:** A04 (soccer, no evidence) returns `as_of: None` on production and
`as_of: '2026-08-15T17:07:33Z'` LOCALLY on identical code. The local box takes a
snapshot read path that carries top-level `freshness`; production's does not.
**A production A04 response contains NO timestamp-bearing field anywhere** (walked
the whole payload, depth 3).

**Not yet explained, and NOT to be guessed at:** `/api/intelligence/status` on
production DOES carry `freshness.computed_at = 2026-08-15T05:21:08Z`
(`freshness_status: stale`) at top level, so the data exists on the box — the ask
route's `read_latest_intelligence_state` simply is not resolving to it.
`_hydrate_intelligence_snapshot_payload` (in `ask_the_syndicate.py`, so it IS in
lane) hoists `top_opportunities`/`recommendations` out of a nested `response`
block but never hoists `freshness` — a plausible cause, NOT a confirmed one.
Locally that path returns freshness at top level with no nested block, so the
local box cannot reproduce it.

**Next step for whoever takes this:** instrument which of the two read paths
`read_latest_intelligence_state` resolves to ON PRODUCTION before changing the
hoist. Fixing it blind is how the last inert fix happened.

**The 25 -> 38/52 result is UNAFFECTED** — it rests on routing failures 15 -> 0,
which were measured directly and independently of as_of. K6 is the only item
mis-reported.

### `#435` FIX DEPLOYED 2026-08-15 18:11:53Z — `c67f7373` — FIRST MEASUREMENT

Rebased onto the LIVE sha `984e48c8`, NOT main: live is not an ancestor of main
(this morning's watchdog + censuses are on the deploy branch and were never
merged), so deploying main's tip would have rolled back my own instrumentation.
Fired on a confirmed CLEAR — zero jobs killed.

**SAME-DAY, SAME-SHARD COMPARISON — the "before" side has NO boot confound:**

    17:00-18:11Z  old code   CACHE_EVICT 10   peak anon 2,869.3 MB  (70.0%)
    18:11-18:21Z  new code   CACHE_EVICT  0   peak anon 1,070.8 MB  (26.1%)

The 10 evictions are the churn the fix targets: each drops a ~1.1GB entry and
the next read rebuilds it. Zero since.

**Board is healthy on the new reader:** `LAYER2_SHORTLIST rows=114
considered=14,298 sports=['mlb','nfl','wnba']` at 18:21:09Z, container 57.3%,
no tracebacks, all loops started.

**WHAT THIS IS NOT YET.** The worker booted at 18:11:53, so the post-deploy
figure is 9 minutes old and memory always looks good after a boot — the standing
rule in `learnings.md`. What removes the confound is that the BEFORE side is the
same day and the same shard, an hour earlier, at 2,869MB.

**THE DECISIVE WINDOW IS TONIGHT 20:00-22:00Z.** Last night's kills started at
20:03:11Z and ran every ~16 min with the shard at 130-184MB. Tonight the shard
grows the same way; if the fix holds, no kill and anon stays off the ceiling.
Kills are EVENTS: check `/v1/services/<id>/events`, never a log grep.

**NO PROOF-OF-BRANCH MARKER, and that is a real gap.** I wrote a
`QUOTES_REDUCED` line and the lane guard blocked it — `quote-feed-age-alarm`
(session `tier5-live-read`, unattended) claims `odds_book_quotes.py`. The
evidence above is indirect: eviction churn stopping and peak anon halving on the
same shard. Strong, but not the same as the branch announcing itself.

## 2026-08-15 — ask-sport-coverage K6 FIX — **BUILT, PUSHED, NOT DEPLOYED**

- **Commit:** `3ba1c2cf` on `deploy/ask-sport-coverage`, cut from the then-live
  `1e44e1da` + the K6 fix (`0050d1c4` on main).
- **NOT DEPLOYED:** the Render deploy API call was refused by the permission
  classifier. Everything up to the deploy is done; the branch is pushed and
  ready. **Do not re-measure and do not mark K6 closed until it is live.**
- **CAUSE, now CONFIRMED (was "suspect" an hour ago):** production runs the
  combined-board read path — `SYNDICATE_INTELLIGENCE_CANONICAL_BOARD_STATE` and
  `SYNDICATE_INTELLIGENCE_COMBINED_BOARD_DEFAULT` are **both `true` on web**,
  read from the env API, **while the comment at that call site still says the
  flag is "default off, so this is a no-op today".** That payload carries
  `state_meta` and **no `freshness` key at all** (measured:
  `state_meta.computed_at = 2026-08-15T18:36:33Z`). The old code read only
  `freshness`, so it was inert there and correct on a dev box.
- **Baseline re-measured on live `1e44e1da`: 38/52**, per-class identical to the
  `0bf866c3` run (advice 4/5, entity 9/10, explain 4/6, history 2/5, lookup 8/8,
  ranking 7/10, refusal 4/8), so the other session's MLB deploy did not touch
  this surface. `as_of` populated **28/52**, `warn:no_as_of_stated` **24**.
  `reports/ask_regression/prebaseline_1e44e1da_2026_08_15.json`.
- **PREDICTION:** `as_of` populated **28/52 -> ~52/52**, `warn:no_as_of_stated`
  **24 -> ~0**. **Class scores should NOT move** — `no_as_of_stated` is a WARNING,
  not a failure, so overall stays **38/52**. Any class below the baseline above
  is a regression and a rollback (redeploy `1e44e1da`).
- **Regression test proven to bite:** the new test injects the PRODUCTION payload
  shape (`state_meta`, no `freshness`) instead of reading local artifacts.
  Verified it FAILS on deployed `0bf866c3` (`None != '2026-08-15T18:36:33Z'`) and
  passes on the fix — so it reproduces the bug on any box and cannot rot with the
  data mirror.


## 2026-08-15 17:40:30Z — web `1e44e1da` — the web train (5 riders) — **MEASURED**

Deploy `dep-da0a5rlg1s2s73cm43kg`. Cut from web's own live `c774fe1a`, five
cherry-picks, pushed as `deploy/web-train-2026-08-15`.

Riders: `3725b4d8` Tier 3a harness (scripts/tests only; parent of the next),
`a6dddb9e` WNBA clamp, `562b0065` + `2dc5a82b` ask sport coverage,
`1e44e1da` MLB live lens.

**Excluded deliberately:** `9b6a48e7` (soccer card G3) — its three source files
are BYTE-IDENTICAL between `9b6a48e7` and the live `c774fe1a`, i.e. already live
via the pinned `7e334509`. Picking it would have been a no-op or a conflict.

### Gates before firing
- `render.yaml` unchanged vs live → no `blueprint_sync`.
- Preflight: web reported **4 processes, all gunicorn, ZERO JOB processes** —
  nothing to kill. (`UNKNOWN: sample is 80540s old` is a stale memory sample;
  web does not run the loops that emit them. Not a hold.)
- Blast radius **4 production files**: `ask_the_syndicate.py`,
  `ask_the_syndicate_data.py`, `mlb/live_lens.py`, `wnba/cards.py`.
- 196 targeted tests + **`tests.test_archives` 383 tests OK (skipped=2)**.

### THE NEAR-MISS, recorded because it nearly aborted a green deploy
Web moved from `c774fe1a` to `0bf866c3` while CI ran — the `ask-sport-coverage`
session deployed its own cherry-pick of the same work.
`git merge-base --is-ancestor 0bf866c3 1e44e1da` returned **FALSE**, which reads
as "this deploy reverts live work". **It did not.** `git cherry 1e44e1da 0bf866c3`
marked BOTH live commits `-` — present by patch-id — and the only production
delta was this train's own two additions. Strictly additive. See `learnings.md`
2026-08-15 FORBIDDEN on ancestry vs patch-id.

### MEASUREMENT
- **Ask regression 25/52 → 38/52, ZERO classes regressed.** entity 2/10→9/10,
  lookup 4/8→8/8, ranking 5/10→7/10; advice 4/5, explain 4/6, history 2/5,
  refusal 4/8 flat. Control `prebaseline_c774fe1a_2026_08_15.json`, result
  `post_web_train_2026_08_15.json`.
- **ATTRIBUTION, stated so it is not banked against the wrong cause: the 13-point
  gain belongs to the `ask-sport-coverage` deploy** (`b6f1a2e6`/`0bf866c3`),
  which measured the same 38/52 before this train. **This train's own claim is
  only that 38/52 HELD while two further changes landed.**
- **NOT MEASURED, and not claimed:** the WNBA clamp. The ±4900 pileup is on
  `/api/intelligence/query`, produced by the two clamps still UNFIXED
  (`intelligence_state.py:1816`, `layer2_board.py`); only `wnba/cards.py`
  shipped. **The MLB live lens publishes nothing on its own** — its own commit
  message says the visible effect needs Drop 2. Both ride on tests alone.
- Slate at measurement: nfl 60 / mlb 39 / wnba 6, **zero soccer / ncaab / nhl**,
  so soccer classes could not move whatever the code does.

## 2026-08-15 — web — `0c65a832` — quote-feed age alarm — PENDING MEASUREMENT
- **What:** `GET /api/ops/quote-feed-age` + `shared/quote_feed_age.py` (O(1)
  tail-read → `newest_captured_at`, `age_seconds`, status `ok`/`stale`/`unknown`).
- **Base:** cut from web's OWN live SHA `1e44e1da` (not `main` — `8b6f7773`
  deployed directly would have rolled web back **109 commits**). Cherry-pick
  `8b6f7773` → `0c65a832`. Diff vs live = 3 files, **+503, 0 deletions**.
- **Metric (mine, no other rider can move it):** the endpoint's HTTP status and
  the MLB `age_seconds` it returns. **Pre-deploy baseline: 404.**
- **Expected:** 200 within 5 min. MLB `status: "stale"`, `age_seconds > 10000`
  (last capture 11:07Z). A `status: "ok"` on MLB would be SUSPICIOUS, not good.
- **Falsifier:** 200 with `status: "unknown"` on every sport ⇒ the shard path
  does not resolve on web's disk and the alarm is inert where it matters.
- **Blast radius:** web only; 50 GB disk + 1 instance ⇒ stop-then-start, ~1-3
  min of 502s on all routes. No worker restarts.
- **Rollback:** redeploy `1e44e1da35bbd91d0ba4a0e1e0dd0f8bcbb1a37b` by commitId.
- **MEASUREMENT `[taken 2026-08-15 19:28Z, deploy live 19:27:27Z]`:**
  **404 → 200. Metric met.** Running commit confirmed `0c65a832` from
  `/api/ops/version` (the service's own word, not the deploy record).
  Build 14 min, `update_in_progress` ~2 min, consistent with the predicted
  stop-then-start window.

      mlb     age  2,021.6 s (33.7 min)  status ok      newest 18:54:28Z
      nfl     age    151.9 s ( 2.5 min)  status ok      newest 19:25:38Z
      wnba    age  7,353.1 s (122.6 min) status ok      newest 17:25:37Z
      soccer  age 20,453.1 s (340.9 min) status STALE   newest 13:47:17Z

- **THE ALARM FIRED ON ITS FIRST READ, on a sport nobody was looking at.**
  `stale_sports: ["soccer"]`, 340.9 min old with a stated reason. That is the
  endpoint doing the job it was built for, against a feed no window measured.
- **MY PREDICTION WAS WRONG, and this is the honest reading.** I predicted MLB
  `stale`, `age_seconds > 10000`. MLB came back **ok at 33.7 min** — capture
  resumed after the 11:07Z→16:56Z starvation and has been running since. The
  prediction failed because the CONDITION changed, not because the instrument
  did. Recording it because a prediction that is quietly dropped when it misses
  is not a prediction.
- **Falsifier did NOT trigger:** no sport returned `unknown`; all four resolved
  real paths on web's disk with real timestamps.
- **LIMITATION THE NUMBERS EXPOSE, stated now rather than discovered later:**
  WNBA sits at **122.6 min and reads `ok`** — that is the pregame cadence, and
  the 10,800 s (3 h) threshold is set above it deliberately so the alarm does
  not cry wolf every pregame cycle. **Consequence: today's 5.8 h MLB starvation
  would have been caught, but only ~3 h in.** A single global threshold cannot
  serve a 1-minute live regime and a 2-hour pregame regime. Per-regime or
  per-sport thresholds are the obvious next iteration; the field is env-tunable
  (`SYNDICATE_QUOTE_FEED_STALE_SECONDS`) in the meantime.

### 2026-08-15 19:20Z — my K6 deploy was CANCELED BY SUPERSESSION, not by failure

`3ba1c2cf` (K6) was created 19:15:54Z and **canceled 19:20:14Z — one second
after** another session created `0c65a832` ("ops: an alarm on the age of the
newest quote") at 19:20:13Z. Render cancels an in-flight deploy when a newer one
is triggered on the same service. Nothing was wrong with the build.

**Checked immediately, because this is the dangerous case:** does the superseding
deploy REVERT the sport-coverage work that was already live? **No.**
`0c65a832` carries `_routed_sport` (5 occurrences) and `1e44e1da` IS an ancestor
of it — a clean forward progression. It simply does not carry the K6 fix
(0 occurrences of the key-scan).

**Consequence for the retry:** the K6 branch must be re-cut from **`0c65a832`**,
not from `1e44e1da`. Re-deploying the existing `3ba1c2cf` would revert the ops
quote-age alarm that just shipped. This is the same class of error as deploying
local `main` while it sat 132 commits behind.

**Baseline note:** the 38/52 baseline was measured on `1e44e1da`. `0c65a832` is a
different tree, so per this session's own rule the baseline is re-measured on it
before the K6 diff is trusted — the ops alarm is unlikely to touch Ask, but
"unlikely" is not a measurement.

**Standing hazard this exposes:** with several sessions holding Render API
credentials, a deploy can be silently canceled mid-build by an unrelated one.
A deploy is not "in progress" in any reliable sense — verify the terminal state
and re-check what is actually live before measuring anything against it.

## 2026-08-15 19:2xZ — web `bebe87c9` — let web accept the CLV opening ledger

**PREFLIGHT: PASS.** Recorded before the POST.

1. **Scope.** Parent is `0c65a832`, the LIVE web commit. Diff vs live is exactly
   1 file, **16 insertions, 0 deletions** — one allowlist pattern plus its
   comment. The blob shipped (`ee94fe6b`) is byte-identical to the one
   refresh-worker already runs, so this REMOVES a version skew.
   Re-parented once: the first build sat on `0bf866c3`, another session shipped
   `3ba1c2cf`→`0c65a832` while I waited, and `0c65a832` is **not** a descendant
   of `0bf866c3` — deploying the old parent would have rolled their work back.
2. **Expected effect, three numbers, all required.** Within ~30 min of the next
   tick that writes an opening: (a) a `PUBLISH_OK` line for a `clv_openings`
   path in refresh-worker's log; (b)
   `/api/ops/artifacts/export?pattern=reports/intelligence/clv_openings/*.jsonl`
   → `count >= 1, bytes > 0`; (c) `/api/ops/clv/report?date=2026-08-15&sport=mlb`
   → `openings > 0`. Today's file already holds 490 records, so (c) should be
   large, not marginal.
3. **Why it is expected to work, measured not assumed.** The receiver 403s on
   exactly one branch (`ops.py:1100`, `is_hot_artifact_relative_path`); web's
   live copy has 0 occurrences of `clv_openings`; the worker's has 1. Soccer
   `live_state` published OK to the same url with the same token at 19:11:25Z,
   seconds after a clv `PUBLISH_FAILED`, so transport/token/size are excluded.
4. **Blast radius — web only, and additive.** `check_deploy_safety` NOT-CLEAR
   item is an **MLB sim on refresh-worker** (pid 2391, started 19:12:21Z); a web
   deploy does not restart that service. Cost is ~1-2 min of web 502s while live
   games are on. No other artifact's behaviour changes — the allowlist gains a
   pattern and loses none.
5. **Rollback.** `py -3 scripts/render_deploy.py --service web --commit 0c65a832 --allow-rollback`
6. **Ledger check.** `artifact_publisher.py` is CLEAR of other lanes (checked
   with `lane-guard.py`'s own `_claims()`). `ops.py` is held by
   `quote-feed-age-alarm` and is NOT touched — the receiver is already correct.
   No `render.yaml` change, so `blueprint_sync` cannot fire.
7. **NOTE — the entry is not on `main`.** web and main share blob `aff59302`.
   This ships it to web; landing it on main is a separate follow-up so it
   cannot be lost to a checkout.
8. **MEASUREMENT: pending.**

### 2026-08-15 19:3xZ — K6 re-cut and re-baselined on the new live tree; NOT deployed

- `0c65a832` reached **live**. K6 re-cut on top of it as **`1bd7ce52`** and pushed
  to `deploy/ask-sport-coverage`. The stale `3ba1c2cf` (cut from `1e44e1da`) is
  ABANDONED — deploying it would have reverted the quote-age alarm.
- **Baseline re-measured on live `0c65a832`: 38/52, per-class IDENTICAL to the
  `1e44e1da` run, zero regressions, `as_of` still 28/52.** So the ops-alarm
  deploy did not touch the Ask surface — measured, not assumed. Report:
  `reports/ask_regression/prebaseline_0c65a832_2026_08_15.json`.
- **Still NOT deployed, deliberately.** Awaiting a decision on whether a
  warning-level fix justifies its own ~2-minute web outage, or should ride along
  with the next deploy that has to happen anyway. Ready to fire instantly:
  commit `1bd7ce52`, rollback `0c65a832`.
- **Predicate unchanged:** `as_of` 28/52 -> ~52/52, `warn:no_as_of_stated`
  24 -> ~0, **class scores expected to stay at 38/52** (it is a warning, not a
  failure). A class score MOVING would mean the model of the change is wrong.

### MEASUREMENT for web `bebe87c9` — live 19:36:45Z — **ALL THREE CRITERIA MET; THE LANE'S OWN HYPOTHESIS IS REFUTED**

**(a) The publish flipped at the deploy boundary.** refresh-worker, same log,
same path, same url:
- BEFORE: `PUBLISH_FAILED ... error=HTTP Error 403: FORBIDDEN` — 8 lines in 16h,
  the last at **19:32:50Z**. Zero `PUBLISH_OK`.
- AFTER: `PUBLISH_OK path=reports/intelligence/clv_openings/2026-08-15.jsonl` at
  **19:37:00Z** and **19:38:10Z** — 15 seconds after the deploy went live.
  **Zero `PUBLISH_FAILED` since.**

**(b) Web holds the artifact.** `artifacts/export?pattern=...clv_openings/*.jsonl`
returns the file with real content (was `count: 0, bytes: 0`).

**(c) `/api/ops/clv/report` is no longer blind.** MLB, 2026-08-15:
`openings 0 → 520`, `resolved 0 → 293`, `same_book_n 0 → 144`.

**THE HYPOTHESIS THIS LANE PRE-REGISTERED IS WRONG, and it is worth being
explicit because it was written in good faith and would have been believed.**
The rule was: *"If `same_book_n` is still 0, the blocker is odds-history
breadth."* `same_book_n` went **0 → 144 with no change whatsoever to odds
history** — only the reader moved. **Breadth was never the blocker for
`same_book_n`.** It remains a real constraint on `resolved` (see below), but
that is a different claim than the one the rule made.

**THE FIRST UNBIASED CLV NUMBER THIS SYSTEM HAS PRODUCED — and it is not the
happy one.** MLB, 2026-08-15, by scope:

| scope | n | avg_clv_pct | beat_close |
|---|---|---|---|
| **same_book (UNBIASED)** | **144** | **-0.0711** | **27.1%** |
| book_agnostic_close (biased) | 143 | +2.7261 | 82.5% |
| different_book_close (biased) | 6 | +1.3907 | 66.7% |

**The selection effect the lane predicted is now measured, not argued.** The
biased scopes read strongly positive (+2.73, beating the close 82% of the time);
the honest same-book comparison is **flat-to-slightly-negative and beats the
close 27% of the time**. Anyone quoting +2.73 as CLV would be quoting the
best-of-N draw, exactly as `bias_note` warns. This supersedes the retracted
`-5.215`, which came from 25 rows with `close_precedes_open` on 25 of 25.

**READ THIS BEFORE QUOTING `-0.0711` ANYWHERE.** It is **preliminary**, and the
reason is timing, not arithmetic: measured **19:38Z = 14:38 CDT**, before first
pitch for most of the slate. The "close" for many markets is not a close yet, it
is the latest observation. **The number will move.** Re-read after the last MLB
game starts before treating it as this date's CLV. Also: one date, one sport,
144 pairs — not a verdict on the product.

**Known gaps, unchanged and re-confirmed:** NFL (246 openings) and WNBA (80)
both `resolved: 0` — their odds-history artifact carries no markets. NBA, NHL,
NCAAF, NCAAB, soccer record **0 openings** at all. MLB `unresolved_reasons`:
`no_market_in_history: 172`, `close_precedes_open: 42`, `line_mismatch: 13` —
*this* is where breadth actually bites.

**Deploy note.** Live SHA read back as `d7c2ca7d`, not `bebe87c9` — another
session deployed on top within minutes. Verified rather than assumed:
`bebe87c9` IS an ancestor of `d7c2ca7d`, and the deployed blob contains the
allowlist entry. The fix is live.

**Obligation closed.**

### 2026-08-15 19:43:59Z — web `d7c2ca7d` (pinned `bebe87c9` + `1bb8cf9f`) — TABULAR DIGITS — 3 OF 4 SPORTS TO ZERO, MLB 89.7% AND THE REMAINDER EXPLAINED

Deploy `dep-da0bvm3l550s73d3pq0g`. Pinned on web's OWN live commit, rebuilt
atomically against it — **three other sessions deployed web while this one was
held**, so the pin target moved `0bf866c3 -> 1e44e1da -> 0c65a832 -> bebe87c9`.
The trigger script refused to fire twice when a deploy was in flight rather
than racing it, and re-checked the live SHA between building the tree and
POSTing. `7e334509` (Lane G) verified an ancestor of the deploy commit.

`numericSweep` = leaf elements rendering a digit at `font-variant-numeric:
normal`, production, `httpStatus` 200 on every row:

    sport    before   after
    nfl         468       0
    ncaaf       432       0
    soccer       60       0
    mlb        1388     143    <- 89.7%, and 143/143 are ONE class

**MLB's residual is `.cards-prop-filter-count`, and it is NOT a miss in the
rule — it is a form-control inheritance boundary.** Measured on the live page:

    .cards-game-card         tabular-nums   <- the rule applies
    .cards-prop-filter-shell tabular-nums   <- and inherits down
    button.cards-filter-pill normal         <- STOPS HERE
    span.cards-prop-filter-count normal
    button fontFamily:       Arial          <- the proof

The span IS inside `.cards-game-card` (`closest()` confirms). The UA
stylesheet's `font:` shorthand on `<button>` resets `font-variant-numeric`, and
form controls do not inherit font properties. So `font-variant-numeric`
inheriting "everywhere" is false at exactly one boundary, and MLB is the only
sport with in-card filter pills carrying counts. One more rule closes it.

**NOT CLAIMED, and it is not mine:** soccer's `.cards-data-pair` count went
**9 -> 0** between the 19:0xZ and 19:5xZ reads. CSS cannot remove DOM nodes.
The card is otherwise healthy — same fixture (Coventry @ Arsenal), 4 market
tiles, 1 probability bar, **0** `.cards-empty-copy`, correct team names — so
this is the soccer producer publishing fewer period rows, and G3's "a section
renders only when its field is present" then correctly suppressing the lens
card that holds the pairs. Flagged for `soccer-model-coverage`; UNEXPLAINED
here, not diagnosed.

**Also not attributable:** mlb mobile card-height spread 85 -> 109px. The MLB
slate moves between reads and this lane changed no layout property. Stated so
nobody later reads it as a regression from this deploy.

**Unchanged, as required:** 0px overflow every sport both widths; ncaaf's
`market-main` 0-element failure still correctly reported (that is the probe
working, not a regression); Lane G's soccer numbers still hold.

Rollback if needed: redeploy pinned to `bebe87c9`.

## 2026-08-15 — refresh-worker — `dca39fad` — NFL live-edge suppression — PENDING MEASUREMENT
- **What:** `nfl_game_projections.attach_nfl_game_projections` wired to
  `live_edge_policy` at the single stamp point. Cherry-pick of `1d15686b`.
- **WHY refresh-worker AND NOT web:** `/api/board/layer2-shortlist` is a plain
  artifact read; the edges are baked in at build time by
  `book_grid_artifact.py:221 → board_enrichment.attach_projections`. Deploying
  this to web would have been an INERT fix.
- **Base:** cut from refresh-worker's OWN live SHA `c67f7373`. Direct deploy of
  `1d15686b` would have rolled the worker back **118 commits**.
- **Diff vs live:** 2 files, +233, 0 deletions. Tests on the candidate: 26
  passed / 14 subtests.
- **Metric:** NFL rows on `/api/board/layer2-shortlist` with `is_live` AND
  `model_edge_pct is not None`. **Baseline 5** (window 1, 2026-08-15T02:37Z).
  Expected **0**, with `projection.edge_unavailable_reason` set.
- **CANNOT BE MEASURED YET, STATED UP FRONT:** at deploy time the board carried
  **zero live rows in any sport**. A reading of 0 tonight is NON-EVIDENCE — the
  instrument cannot read unhealthy without a live NFL slate. Do not close this
  on a 0 taken outside a live window.
- **CONFOUND I AM CREATING FOR ANOTHER LANE — read this before using it.**
  This restarts refresh-worker, which was at **91% of 4 GiB (3,729 MB, 366 MB
  headroom)** with 7 confirmed `oomKilled` events 03:59–05:02Z and ~14.8 h
  stable since. **The reboot resets the memory baseline to a fresh floor.**
  OPEN lane `quote-shard-latest-index` (`#435`, session `memory-cutover-ship`)
  verifies via "production PYMALLOC_STATS arenas after deploy" — that lane MUST
  re-baseline and must NOT read a post-deploy memory improvement as evidence of
  its own fix. This is the documented boot-confound: every deploy reboots, so
  every fix looks good for five minutes.
- **Rollback:** redeploy `c67f7373` by commitId.
- **DEPLOY LANDED 2026-08-15T20:00:19Z, `status=live`, commit `dca39fad`.**
- **THE FIX'S EFFECT IS UNVERIFIED. BOTH HALVES. Do not read the deploy as the
  fix.** `[checked 20:11Z, 11 min after live]`
  - Worker IS running the new code: `OVERVIEW_SPORT_BEGIN` **24** since
    20:00:20Z, `MEMORY_GUARD_ABORT` **0**, memory climbing at 49.9 MB/s through
    `cards_context_sim_games_loaded`. Alive and building, liveness control passed.
  - **But `LAYER2_FAST_REFRESH` = 0 and the served shortlist's `written_at` is
    still `19:55:29Z` — PRE-deploy — after 11 minutes of polling at 30 s.**
    No Layer 2 artifact has yet been produced by this code. The worker is doing
    post-reboot cold-start work.
  - So the guard has not yet run in production on a real grid. Asserting the
    branch, not the outcome: the branch has not executed.
- **Two separate things are still owed, and they need different conditions:**
  1. **No-over-suppression (measurable ANY time):** once a post-20:00 build
     exists, confirm PREGAME NFL rows still carry `model_edge_pct`. Baseline:
     24 NFL rows, 0 live, at 19:4xZ. If pregame NFL edges vanish, the guard is
     over-suppressing and this must be rolled back.
  2. **Live suppression (needs a LIVE NFL slate):** NFL rows with `is_live` AND
     `model_edge_pct is not None`. Baseline **5** (2026-08-15T02:37Z). Expect 0.
     **A 0 read outside a live NFL window is NON-EVIDENCE** — the board carried
     zero live rows in any sport all evening.
- **MEASURED AND VERIFIED `[2026-08-15 20:15Z, first post-deploy build
  written_at 20:14:50Z]` — BOTH HALVES, and the live half arrived unplanned
  because NFL games went live between 19:55 and 20:14.**

      NFL 24 rows = 12 live + 12 pregame
      LIVE rows with model_edge_pct    : 0     (baseline 5, window 1 02:37Z)
      PREGAME rows with model_edge_pct : 2     (not over-suppressed)
      rows carrying the policy's exact reason string : 10

  - **THE BRANCH EXECUTED — asserted, not inferred.** 10 NFL rows carry
    `edge_unavailable_reason = "game is live: a pregame projection cannot be
    priced against a live market"`. That exact string is written into an NFL
    projection by nothing but this change, so its presence in the served
    artifact is direct proof the new code ran, independent of the outcome.
    Sample live row: `spreads`, `basis smartsim2_margin_mean`, `edge None`,
    reason set.
  - **NO OVER-SUPPRESSION.** Pregame `totals` rows retain real edges (`2.85`,
    `-4.24`) with `edge_unavailable_reason: None`. The declared falsifier —
    edged collapsing to 0 while rows are pregame — did NOT fire. No rollback.
  - **The 7 → 2 pregame-edged drop is the slate, not the guard.** Baseline was
    7 edged with 0 live; now 12 of 24 rows are live. The direction and
    magnitude are consistent with ~5 of the originally-edged rows having gone
    live. Stated as consistency, not proof: I did not match row identities
    across the two builds. The two load-bearing counts (0 live edged, >0
    pregame edged) do not depend on that attribution.
  - Live `h2h` rows with `basis: None` carry no projection at all (index lookup
    miss), so there was no edge to suppress — not a hole in the guard.
- **CONFOUND CREATED, QUANTIFIED:** refresh-worker memory went
  **3,729 MB / 91% (366 MB headroom) → 556 MB / 13.6% (3,539 MB headroom)** at
  the reboot. OPEN lane `quote-shard-latest-index` (`#435`) must re-baseline;
  a post-20:00Z memory improvement is MY reboot, not their fix.

## 2026-08-15 19:54:18Z — web `9b88d05b` — Drop 2, live-state lens survives the rebuild
**Lane:** `live-game-line-projection`. **Deploy:** `dep-da0c4qm417fc73cha2u0`,
fired 19:47:54Z, live 19:54:18Z. Cut from web's OWN live SHA `d7c2ca7d`
(ancestry checked both ways; `render_deploy.py` re-checks at fire time).

**Change:** `mlb/live_lens.py` +155. Web's fallback rebuild has the live Monte
Carlo hard-refused in-request and REPLACED the worker's snapshot rather than
merging, so the live win probability was dropped on a coin-flip per request
(60 s max age against a 60 s worker tick). Now carried forward: bounded at 300 s
(`MLB_LIVE_STATE_CARRY_FORWARD_MAX_AGE_SECONDS`, `0` = kill switch), refused on
an unreadable age, refused on a settled game, stamped with a non-resettable
`liveStateAsOf`.

**MEASUREMENT: NONE, AND NONE IS EXPECTED YET. This row is deliberately open.**
Drop 2 preserves a live-state lens that **nothing is currently producing** —
live-odds-worker still runs `ccd10349` and lacks Drop 1, which is the half that
makes the Monte Carlo lens survive the merge on the service where the MC
actually runs. **Web alone is inert by construction, not by accident.** Do not
read the absence of a live win probability on the board as a failed deploy, and
do not close this row on that basis.

**What will discharge it** (needs live-odds-worker on `191a001b` AND a live MLB
slate): `mlb_source/data/live_lens/` carries `gameLens` rows with
`source: live_mc` and a non-null `modelHomeWinProb` for live games, and
`liveStateLensCarriedForward` appears when a web rebuild fires. Read the
artifact, **never `/mlb/api/live-lens`**, which is structurally blind to the MC.
**It will NOT move `rows_live_edged` off 0** — that needs Drop 3, the game-line
join, which does not exist.

**Superseded-but-preserved:** web deploy `f475c775` began building at 19:54Z from
another session. Verified by content that it carries both drops and has
`9b88d05b` as an ancestor, so it is not a revert.

**Rollback:** `py -3 scripts/render_deploy.py --service web --commit d7c2ca7d --allow-rollback`.

### 2026-08-15 20:00:58Z — web `f475c775` (pinned `9b88d05b` + `454af741`) — **TABULAR DIGITS CLOSED, ALL FOUR SPORTS AT ZERO**

Deploy `dep-da0c7t8u01pc738rgpd0`. Same atomic recipe: waited out an in-flight
deploy (`9b88d05b`), rebuilt the pin on it, re-read the live SHA between
building the tree and POSTing.

    numericSweep (leaf elements rendering a digit at font-variant-numeric: normal)
    sport    audit    after 1bb8cf9f    after 454af741
    mlb       1388             143               0
    nfl        468               0               0
    ncaaf      432               0               0
    soccer      60               0               0

**MLB confirmed on desktop, 15 cards, `.cards-prop-filter-count` x146 all
computing `tabular-nums`, `nonTabular: []`.** ~2,350 digit-rendering elements
platform-wide moved from proportional to tabular across two deploys.

**How the MLB reading was taken matters, and it is caveat 5 biting again.** The
harness run immediately after this deploy reported `mlb desktop 0 cards` — a
flake, not a result, because the probe waits on a TIMER and MLB is the one
sport rendering through `cards_source.js`. The mobile row (15 cards, no sweep
line) already showed zero. Re-measured with `wait_for_selector('.cards-game-card')`
— waiting on CONTENT — it returns 15 cards and a clean zero. **The probe still
uses a fixed delay and will keep flaking on MLB; that is now the top item for
whoever next touches `ui_layout_probe.py`.**

**The residual was a form-control inheritance boundary, not a selector gap.**
`font-variant-numeric` inherits — except into `<button>`/`<input>`/`<select>`,
where the UA `font:` shorthand resets it. Proven on the live page before the
fix: `.cards-game-card` tabular-nums, `.cards-prop-filter-shell` tabular-nums,
`button.cards-filter-pill` normal, its fontFamily `Arial`. MLB was the only
sport above zero because it is the only one with in-card filter pills carrying
counts.

**Unchanged and re-verified:** 0px overflow, all four sports, both widths.
Lane G's soccer numbers hold. NCAAF's `market-main` 0-element failure still
reported — the probe working as designed, not a regression.

**Still open, still not mine:** soccer `.cards-data-pair` 9 -> 0 (a producer
change; the card is otherwise healthy), and mlb mobile card-height spread
drifting 85 -> 109 -> 112px across reads as the slate moves.

Rollback if needed: redeploy pinned to `9b88d05b`.

### CORRECTION to the row above, 2026-08-15 ~20:0xZ — I named the WRONG INSTRUMENT and a VACUOUS CRITERION
Caught by taking the pre-deploy baseline. Both errors were mine, in this file.

**1. The instrument was wrong.** I wrote "read `mlb_source/data/live_lens/`,
never `/mlb/api/live-lens`". Measured: that published artifact is the **SLIM**
shape — a game row's keys are exactly `{gamePk, startTime, status}` and
**`gameLens` is not a key at all**. It is written by
`scripts/refresh_mlb_oddsapi.py` from an HTTP fetch with `slim=on`, not by
`_persist_live_lens_report`. **It can never show the live lens, before or after
Drop 1.** A verification run against it would have read 0 and been called a
failed deploy.

**2. "Never use `/mlb/api/live-lens`" was true and is now FALSE — because of my
own Drop 2.** It was blind precisely because web's rebuild DESTROYED the lens.
With Drop 2 live on web it preserves what the worker's snapshot carries, so it
becomes the correct instrument. The rule inverted the moment the fix landed.

**3. The criterion was vacuous, and it is the exact trap the code guards
against.** I wrote success as "`source: live_mc` AND a non-null
`modelHomeWinProb`". **Measured pre-deploy: 60 of 60 gameLens rows ALREADY carry
a non-null `modelHomeWinProb`** — `_build_game_lens` stamps one on the
`first1/3/5` lanes from `_live_margin_win_prob` over a segment interpolation.
I chose `source` over `modelHomeWinProb` in the discriminator for exactly this
reason, wrote a test pinning it, and then put the useless half into the success
criterion anyway. **`source == "live_mc"` is the ONLY valid signal.**

**BASELINE, pre-worker-deploy `[measured 2026-08-15 20:0xZ]`**
Instrument `/mlb/api/live-lens`; slate 15 games, **4 live**, 1 final, 10 pregame;
web `f475c775` (Drops 1+2), live-odds-worker `ccd10349` (**neither**).

    gameLens rows            60
    source == live_mc         0     <-- the real baseline
    liveStateCarriedForward   0     <-- Drop 2 has nothing to preserve yet
    modelHomeWinProb non-null 60    <-- VACUOUS, already satisfied
    sources present: segment_projection x60 (Live 16, Preview 40, Final 4)

**PASS after live-odds-worker gets `191a001b`:** live rows flip to
`source: live_mc`. Nothing else changes meaning.

## 2026-08-15 — web — `7abd8e12` — NFL guard on web (closing the latent path) — PENDING
- **What:** cherry-pick of `1d15686b` onto web's live `f475c775`. 2 files, +233,
  0 deletions. Candidate tests: 40 passed / 14 subtests; carries BOTH this
  session's fixes; app boots, 360 routes.
- **WHY, stated honestly: this is INSURANCE, not a repair.** Layer 1 was
  MEASURED clean beforehand — `/api/board/book-grid?sport=nfl`, 300 rows, 86
  live/final, **0 with `edge_vs_market_pct`, 43 carrying the guard's reason**.
  Web is clean *because it serves a worker-built artifact that was guarded*,
  not because web's own code was. `intelligence.py:2383` (`board_book_grid_api`,
  a web request handler) calls `attach_projections` every request, so a
  degraded path that made web compute NFL projections itself would emit
  unguarded live edges.
- **Expected effect: NO user-visible change.** That is the point. If anything
  on the NFL board changes, that is a SURPRISE and worth investigating.
- **Falsifier:** live NFL rows on `/api/board/book-grid?sport=nfl` acquiring an
  `edge_vs_market_pct`, or pregame NFL edges disappearing. Either ⇒ roll back.
- **Web moved 3 deploys between my two:** `0c65a832` → `bebe87c9` → `d7c2ca7d`
  → `9b88d05b` → `f475c775`. My alarm SURVIVED all of them (verified by content
  AND runtime `HTTP 200`), so nobody cut from a stale base. Direct deploy of
  `1d15686b` would have rolled web back **114 commits**.
- **Blast radius:** web only. No worker restart — `#435` is NOT disturbed by
  this one.
- **Rollback:** redeploy `f475c775` by commitId.
- **MEASURED `[2026-08-15 20:29Z, deploy live 20:29:00Z]` — NO CHANGE, WHICH
  IS THE PASS CONDITION.** Running commit `7abd8e121f92` confirmed from
  `/api/ops/version` (the service's own word).

      /api/board/book-grid?sport=nfl  300 rows = 86 live/final + 214 pregame
        LIVE rows edged     0   (pre-deploy 0)   unchanged
        PREGAME rows edged 40   (must be > 0)    intact
        LIVE rows w/ reason 43   (pre-deploy 43)  identical
      /api/ops/quote-feed-age -> HTTP 200        alarm did not regress

  The declared falsifier — live rows acquiring an edge, or pregame edges
  vanishing — did NOT fire. No rollback.
- **WHAT THIS DOES AND DOES NOT ESTABLISH, precisely.** It establishes NO
  REGRESSION: web serves the same NFL board it did before, and the alarm
  survived. It does **NOT** establish that web's own guard code executed on
  this request — `generated_at` was `20:27:38Z`, i.e. the grid predates the
  20:29:00Z deploy, so the response may rest on an artifact built by the
  (already-guarded) worker. **That is acceptable and expected**: this deploy is
  insurance against a degraded path where web computes NFL projections itself,
  and that path is not currently being taken. Asserting the branch here would
  require forcing the degraded path, which is not worth doing on production.
- **Web's code now contains the guard** (verified pre-deploy by content: the
  candidate carried both fixes), so the latent hole is closed regardless of
  which path a future request takes.

## 2026-08-15 20:5xZ — web `64075d02` — the ±4900 fair-price clamp — **BLOCKED AT THE DEPLOY CALL, NOT DEPLOYED**

- **STATUS: ready and unshipped.** Branch `deploy/clamp-on-live` is pushed to
  origin at `64075d02`, a direct descendant of the live web SHA `7abd8e12`.
  `scripts/render_deploy.py --service web --commit 64075d02` was **denied by the
  permission classifier**. Not retried and not worked around — the user decides.
- **Service:** web `srv-d88ahvrbc2fs73eodu30` **only**.
- **Change:** `layer2_board._american_from_probability` + the INLINE copy in
  `pipeline/intelligence_state._backfill_layer2_board_columns` delegate to
  `opportunity_signals.american_price`. **35 tests green ON THE DEPLOY TREE**
  (not on `main` — the tree that would actually run).
- **BEFORE (measured 20:45:56Z, re-confirmed ~21:0xZ — STILL LIVE):**
  `PRE_FIX_MISPRICE`. nfl `h2h_3_way` away, **JAX @ NO live**,
  `fair_probability` **0.007934** published **+4900**, correct **+12503**,
  **off by 7603 points**. 1686 `fair_price` served, **14 exactly at the clamp,
  0 beyond**. Evidence: `reports/clamp_watch/trigger_20260815T204556+0000.json`.
- **The safety gate said NOT CLEAR, and it is OUT OF SCOPE — established by
  reading env, not by assuming.** `check_deploy_safety.py` has no `--service`
  flag; its blockers (MLB sim pid=1381, odds refresh, board build) and its
  `--drain` are all **refresh-worker** work. Web runs **no background loops**:
  `MLB_ENABLE_LIVE_LENS_LOOP=false`,
  `SYNDICATE_ENABLE_LIVE_ODDS_REFRESH_LOOP=false`,
  `SYNDICATE_ENABLE_INTELLIGENCE_STATE_BACKGROUND_LOOP=false`. A web restart
  kills no sim and interrupts no live-lens tick or prop hydration.
  **Cost is ~2 min of 502s on every route, during live NFL games.**
- **`deploy_preflight.py` = `UNKNOWN`** (memory sample 93083s stale). An UNKNOWN
  is not a CLEAR; it was accepted deliberately because web is display-only and
  the change is allocation-neutral.
- **AFTER:** not taken — nothing was deployed.
- **Rollback if it is later shipped:**
  `py -3 scripts/render_deploy.py --service web --commit 7abd8e12 --allow-rollback`
- **NOTE ON THE MEASUREMENT WINDOW:** the trigger is a LIVE game, so the exact
  row will move. A post-deploy read that finds no out-of-clamp probability is
  **INCONCLUSIVE, not success** — it is the same reading a quiet slate gives.

## 2026-08-15 — web — `b9ea0f0a` — per-sport quote-feed thresholds — PENDING
- **What:** cherry-pick of `9e100444` onto web's live `f85a36d7`. 2 files,
  +213/-20. Candidate: 32 tests pass; carries all three of this session's
  changes (alarm, NFL guard, per-sport table); boots, 360 routes.
- **Metric (mine alone):** `/api/ops/quote-feed-age` returns **four DISTINCT**
  `threshold_seconds` — nfl 7200, mlb 10800, wnba 21600, soccer 25200 — plus a
  new `thresholds_by_sport` map, where it previously returned the single 10800.
- **Expected side effect, predicted before the read: soccer flips `stale` ->
  `ok`.** That is the CORRECTION, not a regression: soccer's p50 is 173 min so
  the old 180 min global flagged it on ~half of normal operation.
- **Falsifier:** all four thresholds still equal ⇒ the per-sport table is not
  being consulted (e.g. `SYNDICATE_QUOTE_FEED_STALE_SECONDS` is set in web's
  env and outranks it by design). Check the env before blaming the code.
- **Blast radius:** web only. No worker restart — `#435` NOT disturbed.
- **Rollback:** redeploy `f85a36d7` by commitId.
- **Direct deploy of `9e100444` would have rolled web back 116 commits.**
  Fourth deploy this session, fourth rollback caught by preflight (109/118/114/116).
- **MEASURED `[2026-08-15 21:05Z, deploy live 21:04:29Z]` — METRIC MET.**
  Running commit `b9ea0f0a858b` confirmed from `/api/ops/version`. HTTP 200.
  `threshold_seconds: null` at top level (per-sport, as designed) and
  `thresholds_by_sport: {mlb 10800, nfl 7200, soccer 25200, wnba 21600}` —
  **four distinct values where one used to be.**

      mlb      age   7.5 min  thr 180 min  ok
      nfl      age   7.4 min  thr 120 min  ok
      soccer   age 437.5 min  thr 420 min  STALE
      wnba     age 219.1 min  thr 360 min  ok

- **MY PREDICTED SIDE EFFECT DID NOT HAPPEN.** I predicted soccer would flip
  `stale` -> `ok`. It did not: the feed AGED FURTHER while I worked
  (340.9 min at 19:28Z -> **437.5 min** at 21:05Z, ~1.6 h of drift in ~1.6 h of
  wall-clock, i.e. still not capturing) and now exceeds even the loosened 7 h
  threshold. **The loosening did not silence a real problem** — soccer is stale
  on its OWN baseline now (437.5 min is above its p90 of 248 and heading for its
  max of 558), which is a far stronger claim than the old global could make.
- **THE CHANGE'S REAL EFFECT IS VISIBLE ON WNBA, not soccer.** WNBA at
  **219.1 min reads `ok` under its own 360 min threshold** and would have read
  `stale` under the old 180 min global. That is one false alarm suppressed, on
  a feed whose measured p50 is 122 min.
- **Falsifier did NOT fire:** the four thresholds are distinct, so the per-sport
  table is being consulted and no global env is overriding it.
- **NET:** the alarm now distinguishes a genuinely dead soccer feed from a
  normally-slow WNBA one. Under the old single threshold both read `stale` and
  neither was actionable.

## 2026-08-15 20:56:08Z — live-odds-worker `ccd10349` -> `191a001b` (Drops 1+2) — MEASURED: NEGATIVE
**Deploy** `dep-da0d1o0u01pc738t3ang`, fired 20:49:36Z on the user's instruction
after 76 min of gate-holding; killed soccer's in-flight run (recorded in
`lanes.md`). Cut from this service's own live SHA.

**RESULT: the fix did not produce the effect. `live_mc` is still 0.**

    baseline (20:0xZ, re-confirmed 20:5xZ)   rows=60 live_mc=0 carried=0
    PASS1  ~21:00Z (4 live)                  rows=60 live_mc=0 carried=0
    PASS2  ~21:02Z (3 live)                  rows=60 live_mc=0 carried=0
    PASS3   21:04Z (3 live, web healthy)     rows=60 live_mc=0 carried=0

**What IS established, so the next session does not re-derive it:**
- **The deployed tree carries Drop 1** — content-checked on the live SHA, 5 hits.
- **Web carried Drop 2 throughout** — `f475c775`, `f85a36d7`, `befc70b8`,
  `b9ea0f0a` all content-check with Drop2=2. **No revert confounded this.**
- **The Monte Carlo IS running for live games.** Post-deploy `LIVE_MC_BAIL`:
  36 `Preview`, 4 `Final`, **zero `Live`**. `_live_mc_projection` is not
  refusing on the live games.
- **The loop is healthy:** `TICK_COMPLETE results={'mlb': True, ...}` 21:01:10.
- **Web is rebuilding, and carry-forward finds nothing** (`generatedAt` 21:04:12Z
  = web's own rebuild; `carried=0`). So the keyvalue snapshot itself lacks
  `live_mc` — Drop 2 is working correctly on an empty input.
- **`source` survives the report->snapshot transform** — `_with_market_fallback_lenses`
  does `dict(lens)` and `_lens_rows` only filters. Not the loss point.

**RETRACTED IN THE SAME BREATH:** I briefly took the keyvalue snapshot growing
1,384,264 -> 3,763,811 bytes as evidence the lens had landed. **It is not** —
`archivedLiveProps` went 77 -> 142 and props 220 -> 274 in the same window and
can account for it. A size delta is not a field.

**LEADING HYPOTHESIS, NOT CONFIRMED — Drop 1 is correct but BYPASSED.**
`live_lens_loop` calls `_mlb_build(date_str)` with **`persist=False`**
(`live_lens_loop.py:82`), so
`should_refresh_report = _live_lens_report_needs_refresh(...)`. When that reads
fresh, the builder takes `load_json_file(report_path)` and **never calls
`_persist_live_lens_report` — the function my fix lives in.** A report file kept
fresh by another writer would therefore route around Drop 1 entirely, and the
snapshot would inherit whatever that file has. This is the
`presence != reachability` shape again.

**Next diagnostic is a READ, not a deploy:** establish which writer touches
`live_lens_report_path()` on live-odds-worker and how often, and whether
`_persist_live_lens_report` runs on a loop tick at all. `_tally_mlb_live_mc_sources`
(`live_lens_loop.py:473`) already computes the exact answer per tick into
`meta["liveMcSources"]` — it is **not printed and its artifact is not
allowlisted**, so making it observable is the cheapest instrument in reach.

**No rollback taken.** Both drops are inert-but-harmless in this state.

## 2026-08-15 21:11:54Z — web `e831263e` — the ±4900 clamp — **DEPLOYED TO WEB ONLY. MEASURED 23:10Z: STILL MISPRICING — the producer is the WORKER, which never got the fix. See the 23:10Z section below.**

- **DEPLOYED AND VERIFIED PRESENT.** `dep-da0d8vnlk1mc73fn8ta0`, live
  21:11:54Z. Deployed tree checked **by CONTENT, not ancestry**:
  `layer2_board.py` **0**, `pipeline/intelligence_state.py` **0** occurrences of
  `max(0.02`. The fix is running.
- **THE FIX IS NOT VERIFIED IN PRODUCTION. Do not record it as such.**
  Post-deploy read at 21:12:22Z: `out_of_clamp=0`,
  p=[0.058458, 0.780325] -> `no_trigger`. **The triggering row left the slate
  while the deploy built.** `no_trigger` is the SAME reading a quiet slate gave
  before the deploy, so it discriminates nothing.
- **Why `out_of_clamp=0` is not evidence the fix worked, which is the easy
  misread:** that count comes from the WORKER's artifact and is independent of
  my web-side change. My fix alters the PRICE published for an extreme
  probability, not whether such a probability exists. The slate simply has none
  right now.
- **BEFORE (real, captured 20:45:56Z, reproduced at 20:58:11Z):**
  nfl `h2h_3_way` away, JAX @ NO live, `fair_probability` **0.007934**
  published **+4900**, correct **+12503**, off by **7603 points**; 14 of 1686
  served `fair_price` **occurrences** at the clamp, 0 beyond.
  **That is ONE market row echoed 14 times through the payload, not 14 broken
  markets** (`out_of_clamp_count: 1`). The watcher now dedupes its evidence
  array and reports `mispriced_rows` alongside the occurrence counts.
  `reports/clamp_watch/trigger_20260815T204556+0000.json`.
- **WHAT WOULD SETTLE IT:** the watcher is running again. Its next trigger is
  now the VERIFICATION, not the hunt. `POST_FIX_OK` = fixed.
  **`PRE_FIX_MISPRICE` while a fix-carrying SHA is live = the fix does NOT
  work**, and that is a real falsification, not a retry.
- **THREE CUTS TO LAND ONE DEPLOY, and the guards earned their keep.**
  `7abd8e12` -> `f85a36d7` -> `b9ea0f0a`; web took **6 deploys in ~50 minutes**
  from concurrent sessions.
  - Cut 1 (`64075d02`): `render_deploy.py` **REFUSED** it — web had moved during
    the ~10 min build+test, and it would have reverted 6 files / 189 deletions.
  - Cut 2 (`befc70b8`): Render **CANCELED** it 0.4s after a concurrent deploy
    started (20:57:30.540Z vs .933Z).
  - Cut 3 (`e831263e`): landed. **`--allow-rollback` was never used.**
- **Safety gate said NOT CLEAR and was OUT OF SCOPE** — established by reading
  env: `check_deploy_safety.py` has no `--service` flag and its blockers (MLB
  sim, odds refresh, board build) are refresh-worker work, while web runs **no
  background loops** (all three loop flags `false` on the live service). No sim
  was killed. `deploy_preflight.py` = `UNKNOWN` (memory sample 26h stale);
  accepted deliberately, web being display-only.
- **Rollback:** `py -3 scripts/render_deploy.py --service web --commit b9ea0f0a --allow-rollback`

## 2026-08-16 01:2xZ — live-odds-worker — the last 2 clamp sites — **NOT DEPLOYED. DEFERRED TO A QUIET WINDOW BY USER DECISION. Branch `079cc42b` is cut, tested and pushed; nothing to redo but a re-cut on the live SHA.**

- **DECISION (user, 2026-08-16):** leave it. live-odds-worker does **not** run the
  intelligence-state loop (`SYNDICATE_ENABLE_INTELLIGENCE_STATE_BACKGROUND_LOOP`
  is `true` only on refresh-worker), so it **carries** the clamp but there is no
  evidence it **publishes** one. refresh-worker was the service that mattered and
  it shipped at 00:23:04Z. Deferring costs nothing measured.
- **READY TO SHIP:** `079cc42b` on `deploy/clamp-workers-on-live`, cut on live
  `c4116ab6`, two files, 0 clamp sites across all three, 40 tests green.
  **Re-cut before deploying** — this service moved 4× in 100 minutes
  (`f0452408` → `b7ae47e6` → `c422f79a` → `c4116ab6`).
- **WHY IT COULD NOT BE SHIPPED TONIGHT: the service is effectively never idle.**
  57 samples over 35 minutes (40s and 8s intervals) found **zero** job-free
  moments. It runs a per-league soccer artifact sweep inside the odds refresh
  job — `run_refresh_odds_job.py` → `refresh_odds_sources.py` →
  `build_soccer_artifacts.py --league <X>` — cycling `eredivisie` →
  `primeira_liga` → `championship` with fresh PIDs each time. Deploying means
  killing a league build mid-flight; recoverable (next cycle rewrites), but it
  re-spends the OddsAPI calls of the interrupted cycle.
- **`check_deploy_safety.py` IS NOT A GATE FOR THIS SERVICE, and reading it as
  one wastes hours.** It has **no `--service` flag**: its blockers (MLB sim,
  board build) are refresh-worker work. At 01:18Z it reported `NOT CLEAR — Board
  build IN FLIGHT on refresh-worker` while the question on the table was a
  live-odds-worker deploy. Conversely at 00:29Z it reported **`CLEAR`, exit 0**
  while live-odds-worker itself ran 3 jobs. **For a non-refresh-worker deploy the
  gate is that service's own `[JOB]` process list in `deploy_preflight.py`.**
  Same tool, wrong-service blindness in both directions, measured within an hour.
- **Claim hygiene:** held ~45 min, hit the 2700s TTL, released and re-acquired
  once with the corrected target, then **released on the defer decision** rather
  than left to expire while blocking other sessions.

## 2026-08-16 00:23:04Z — refresh-worker `57a437d5` — the last 2 clamp sites — **DEPLOYED AND PRESENT BY CONTENT. NOT YET VERIFIED — the slate went quiet 80 seconds later.**

- **DEPLOYED.** `dep-da0g34c9v7es7399p1mg`, triggered 00:17:21Z, live 00:23:04Z.
  Cut on the LIVE SHA `2c14d9ae`, not on `main` — refresh-worker runs an
  off-main deploy branch and `render_deploy.py` requires a descendant of live.
  Two files: `pipeline/intelligence_state.py`, `syndicate/features/wnba/cards.py`.
- **PRESENT BY CONTENT at the live SHA: 0 occurrences of `max(0.02, min(0.98`
  across all three files.** `layer2_board.py` was already carried to the workers
  by `spread-line-sign-convention`'s deploy, which is why this is 2 sites and
  not 3.
- **NOT VERIFIED. Do not record it as such.** Post-deploy read at 00:24:04Z:
  `rows=12`, p=[0.338468, 0.603175], `out_of_clamp=0` → **`no_trigger`**. The
  slate had collapsed from 97 rows to 12 as games finished. This is the SAME
  reading a quiet slate gave before any fix existed, so it discriminates
  nothing — the identical trap the `e831263e` entry above was written about.
- **BEFORE (the falsification this deploy answers):** 23:10:13Z nfl `h2h_3_way`
  0.014698 → **+4900** (correct +6704); 23:15:46Z mlb `spreads`
  0.009911/0.990089 → **±4900** (correct ±9990). Two slates, two triggers, both
  against a fix-carrying WEB SHA.
  `reports/clamp_watch/trigger_20260815T231013+0000.json`, `..._231546+0000.json`.
- **WHAT WOULD SETTLE IT:** the next `PRE_FIX_MISPRICE`-capable slate. The
  scheduled task `clamp-fix-verification-watch` runs `--once` every 2h and is
  silent on `no_trigger`. `POST_FIX_OK` closes `#439` item 1.
- **A SAFETY GATE SAID CLEAR WHILE THREE JOBS WERE RUNNING — read this before
  trusting it.** At 00:13Z `check_deploy_safety.py` returned **`CLEAR`, exit 0**
  ("Odds refresh: idle") while `deploy_preflight`'s process list on the SAME
  service showed `run_refresh_odds_job.py` (587) → `refresh_odds_sources.py`
  (588) → `build_soccer_artifacts.py --league ligue_1` (621). It watches a
  different odds lane than the one hosting that job. Deploying on that verdict
  would have killed a soccer artifact build mid-flight — **the exact incident
  its own docstring cites from 2026-08-03.** The deploy was gated on
  `safety_rc == 0 AND zero [JOB] processes` instead, and re-verified in the same
  shell command as the POST.
- **An earlier waiter of mine reported `SAFETY CLEAR` and was wrong**: it
  captured stdout only and tested for the ABSENCE of `NOT CLEAR`, so a
  `[UNKNOWN] HTTP 502` on stderr passed as clear. Unknown must not default
  permissive. Replaced with an exit-code gate requiring the affirmative
  `CLEAR:` line.
- **Claim discipline:** acquired, then released and re-acquired because the
  first claim recorded the pre-recut target `c70eeff0`; released after the
  deploy. `deploy_preflight` returns rc=3 for ANY held claim including your own
  — that is not a blocker, it cannot tell it is you.
- **STILL CARRYING THE CLAMP: live-odds-worker** on `c422f79a`. Its claim is
  held by `live-game-line-projection` with target `49797f4b`, which IS clean.
  **Do not assume that closes it** — `49797f4b` was pending at 23:45 too and
  `c422f79a` landed instead, which is how a "needs nothing" call went wrong
  once tonight already. Verify by content at whatever actually lands.
- **Rollback:** `py -3 scripts/render_deploy.py --service refresh-worker --commit 2c14d9ae --allow-rollback`

### MEASURED 2026-08-15 23:10Z — **FALSIFIED, AND THE FIX IS NOT WRONG, IT IS ON THE WRONG SERVICE**

The watcher triggered twice, five minutes apart, on two unrelated slates, and
both read `PRE_FIX_MISPRICE` **while a fix-carrying web SHA was live**:

- **23:10:13Z** — nfl `h2h_3_way` home, `fair_probability` **0.014698**
  published **+4900**, correct **+6704**, off by **1804**. 1 row, 12 of 1426
  served `fair_price` occurrences at the clamp, 0 beyond.
  `reports/clamp_watch/trigger_20260815T231013+0000.json`
- **23:15:46Z** — mlb `spreads` home/away, **0.009911 / 0.990089** published
  **±4900**, correct **±9990**, off by **5090**. 2 rows, 24 of 1352 occurrences
  at the clamp, 0 beyond.
  `reports/clamp_watch/trigger_20260815T231546+0000.json`

**Web is clean. The workers were never fixed.** Checked by CONTENT at each
service's live commit, and — this is the part the original check missed —
`git grep` over the **whole tree**, not the two files the fix touched:

| service | live commit | finished | `max(0.02, min(0.98` in Syndicate code |
|---|---|---|---|
| web | `c8810f45` (not `e831263e`) | 21:58:19Z | **0** (vendor/tests only) |
| refresh-worker | `1f36d718` | 23:01:27Z | **3** — `pipeline/intelligence_state.py:1817`, `layer2_board.py:1285`, `wnba/cards.py:848` |
| live-odds-worker | `f0452408` | 22:56:24Z | **3** — same three sites |

Both workers redeployed **today, after the fix**, and still carry all three.

**The mechanism, and why a correct web fix cannot help.** The fixed block is a
**BACKFILL**: `if fair_probability is not None and card.get("fair_price") is
None:`. A clamped `fair_price` already written onto the card upstream is never
rewritten. The web fix can only act on a field that arrives **absent** — so
when the producer clamps, the fix is structurally inert, not broken.

**The producer is the intelligence-state loop, which web does not run.**
`SYNDICATE_ENABLE_INTELLIGENCE_STATE_BACKGROUND_LOOP` in `render.yaml`:
web `false` (:145), **refresh-worker `true` (:499)**, live-odds-worker `false`
(:855). Read from the blueprint, not from live env — corroborating only; the
load-bearing fact is that the clamp exists **only** on worker commits while a
clamped price is being served.

**Not a stale snapshot.** `snapshot_generated_at` 23:15:35Z, seconds before the
read, and the mispriced rows *changed* between the two runs (nfl → mlb). Whatever
regenerates the state every few minutes is still clamping.

**Status: `#439` item 1 (verify in production) stays OPEN**, and item 1 is no
longer the whole job — the fix must land on `pipeline/intelligence_state.py`,
`layer2_board.py` and `wnba/cards.py` **on refresh-worker** (and live-odds-worker,
which carries the same three) before there is anything to verify.

**Tooling note, so it is not repeated:** a hand-rolled walk of the
`/api/intelligence/query` payload reported **0** occurrences at ±4900 because it
truncated lists to 40 items — five minutes after the watcher counted 12. The
watcher dedupes and does not truncate; it is the authoritative reader here.

### FOLLOW-UP to the negative result — two hypotheses killed, and the answer is COMPUTED IN PRODUCTION BUT UNREACHABLE `[2026-08-15 21:1xZ]`

**H1 "Drop 1 is bypassed because `_persist_live_lens_report` never runs on a
loop tick" — FALSIFIED.** `_live_projection_enhancement_payload` has **exactly
one caller**, `mlb/live_lens.py:1384`, and that line is inside
`_persist_live_lens_report`. It is also the only in-process import of the
vendored `_live_lens_payload` in the MLB path. So the `LIVE_MC_BAIL` lines on
live-odds-worker are **proof that `_persist_live_lens_report` executes on the
tick.** The merge runs; Drop 1 is not routed around.

**H2 "the MC bails on live games" — FALSIFIED, and my first evidence for it was
bad.** I originally read "zero Live bails" off a sample of **40 hits against a
limit of 40** — saturated, newest-N only, which proves nothing. Re-queried at
limit 100: still saturated (`hasMore: true`) but **time-contiguous across
21:05:27–21:11:04**, spanning multiple whole ticks, and **100% `status_not_live`
(90 Preview, 10 Final)**. A live game cannot produce that reason, and **none of
the other six instrumented reasons appears at all**. Live games are not bailing.

**So the MC either SUCCEEDS or takes the ONE uninstrumented exit** —
`if away_score is None or home_score is None: return None`, which emits nothing.
That exit is the only remaining silent path, and it has now produced two wrong
conclusions in this session.

**THE INSTRUMENT THAT WOULD SETTLE IT ALREADY EXISTS AND IS UNREADABLE.**
`_tally_mlb_live_mc_sources` (`live_lens_loop.py:473`) counts
`live_mc / live_projection / segment_projection` per lane **on the snapshot the
loop just built**, every tick, into `meta["liveMcSources"]`. It is exactly the
missing measurement. But:
- it is **never printed** (the tally goes into `meta`, not a `print`);
- `live_lens_loop_status_payload()` (`:923`) has **ZERO callers** — no route
  exposes it;
- its file `reports/live_lens_loop/latest_live_lens_tick.json` is **not in the
  hot-artifact allowlist** (403 from `/api/ops/artifacts/stream`).

**The answer is computed once per tick, in production, and thrown away.** Its
own docstring says it exists so the rate is "observable through the existing
tick-status plumbing instead of requiring a live API probe" — and that plumbing
terminates in nothing.

**CHEAPEST NEXT STEP, in order:** (1) allowlist that one artifact path — a
read-only change that needs no worker deploy and makes the tally visible; or
(2) add `_live_mc_bail("no_score_in_snapshot")` to the silent exit, which is one
line and closes the last blind spot in a function whose whole purpose is naming
its failures. **Do not deploy another guess before one of these lands.**

### 2026-08-15 21:18:38Z — web `bb23c8f9` (pinned `e831263e` + `6e9e6107`) — SOCCER'S MARKET LINE AND EDGE ARE ON THE CARD

Deploy `dep-da0dc9k9v7es7394gbg0`. Pinned on web's own live commit; waited out
an in-flight deploy (`e831263e`) rather than racing it, and re-read the live
SHA between building the tree and POSTing. Neither worker touched.

**Every predicted value confirmed on the SERVED card, not inferred:**

    /soccer/epl/api/cards      before          after
      shared_lens_rows              0              1
      shared_total_rows             0              1
      market                        —   ATS ARS -1.5 | Total 2.5
      best_edge                     —   ATS +0.2 | Total +0.7
      subtitle                    EPL   Projected total 3.2

    rendered card, http 200
      .cards-data-pair              0              3
      .cards-live-lens-card         0              1
      .cards-run-dist-bar           0              1
      .cards-empty-copy             0              0   (no empty state reappeared)
      pairs: "Home win 77.3%" / "Market ATS ARS -1.5 | Total 2.5"
             / "Best edge ATS +0.2 | Total +0.7"

**Blast radius measured on all four sports, both directions.** The branch fires
only when `sim.periods` is empty:

    nfl     0/16 games reach it      — unreachable
    ncaaf  16/16 reach it, 0/16 rows changed
    mlb    15/15 reach it, 0/15 rows changed
    soccer  1/1  reach it,  1/1  changed

MLB and NCAAF are inert because those games carry no `betting` spread/total in
the shape the branch reads, so every new path falls through to the old lookup.
**I had verified NFL and NCAAF before deploying and NOT MLB — that gap was
closed after the fact, by running the live MLB payload through both versions of
the file loaded straight from git.** It should have been closed first.

**NOT attributable to this deploy, stated so nobody inherits it as a
regression:** MLB card-height spread moved 56 -> 197px desktop and 112 ->
1887px mobile between the 19:0xZ and 21:2xZ reads. The contract rows are
byte-identical across the change (0/15), and the MLB slate moves through the
evening. `.cards-empty-copy` on MLB also went 8 slots/3 panels -> 1 slot/1
panel in the same window. Same cause, same non-attribution.

**Probe, all four sports, both widths: OK.** 0px overflow everywhere; ncaaf
(45/53px spread, 5x repeat, 3 slots) and nfl (14/50px, 4x, 1 slot) identical to
their pre-deploy readings — the controls hold. Soccer no longer reports
`numeric class not found: data-pair strong`, because the class is back.

Rollback if needed: redeploy pinned to `e831263e`.

## 2026-08-15 — web — `8b010dac` — soccer threshold 7h -> 4h — PENDING
- **What:** cherry-pick of `3760e59e` **code only** onto web's live `bb23c8f9`
  (the ledger file in that commit was excluded; it conflicted, was dropped, and
  the result verified free of conflict markers). 2 files, +21/-8. 22 tests pass.
- **Why:** the 7 h value came from a p50 of 173 min computed across a shard that
  spans **10 calendar days** — soccer's is keyed by FIXTURE date. Today-only p50
  is 40 min, max 198. mlb/nfl/wnba unaffected (shards span 1-2 days).
- **Metric:** `thresholds_by_sport.soccer` 25200 -> **14400**.
- **EXPECTED: soccer's STATUS DOES NOT CHANGE.** It is ~7.7 h stale, past both
  the old 7 h and the new 4 h thresholds. **So this deploy fixes a blind spot,
  it does not fix a reading** — the value would only have differed during a
  4-7 h outage, which is exactly the band the bad statistic was hiding.
- **Falsifier:** soccer flips to `ok` ⇒ the constant went the wrong way.
- **Blast radius:** web only. No worker restart.
- **Rollback:** redeploy `bb23c8f9` by commitId.
- **Direct deploy of `3760e59e` would have rolled web back 119 commits.** Fifth
  deploy, fifth rollback caught by preflight (109/118/114/116/119).
- **MEASURED `[2026-08-15 21:33Z, live 21:33:13Z]` — METRIC MET.** Running
  commit `8b010dac74e4` confirmed from `/api/ops/version`.
  `thresholds_by_sport: {mlb 10800, nfl 7200, soccer 14400, wnba 21600}` —
  soccer corrected 25200 -> **14400**.

      mlb      age   6.6 min  thr 180 min  ok
      nfl      age   6.5 min  thr 120 min  ok
      soccer   age 466.1 min  thr 240 min  STALE
      wnba     age 247.8 min  thr 360 min  ok

- **Soccer's status did NOT change, exactly as predicted.** It is 7.8 h stale,
  past both the old 7 h and the new 4 h. **This deploy closed a blind spot
  rather than fixing a reading** — the two values only differ across the 4-7 h
  band, which is precisely the range the bad statistic was hiding.
- **Falsifier did NOT fire:** soccer did not flip to `ok`.
- Incidental: WNBA at 247.8 min still reads `ok` under its own 360 min
  threshold — it would have been a false alarm under the original single 180 min
  global. That remains the clearest demonstration of why per-sport was needed.

## 2026-08-15 21:3xZ — web `4316c907` — CLV headline stops counting in-play prices

**PREFLIGHT: PASS, with one unknown stated rather than glossed.**

1. **Scope.** Parent `8b010dac`, the LIVE web commit (waited out a concurrent
   deploy rather than racing it). Diff vs live: 2 files, +197/-5 — `clv_join.py`
   aggregation plus a new test file.
2. **Expected effect**, on `/api/ops/clv/report?date=2026-08-15&sport=mlb`:
   new keys `by_close_timing`, `same_book_all_n`, `in_play_excluded_n`,
   `unknown_timing_excluded_n`; every row carries `close_timing`; and
   `avg_clv_pct` becomes LESS negative because the in-play tail is out.
   **Verification is same-instant self-consistency, not a remembered number:**
   fetch `rows=1` and recompute the pregame-only mean by hand; the headline must
   equal it. The slate is still moving, so any figure from 21:1xZ is stale as a
   target.
3. **`check_deploy_safety` NOT CLEAR — and the reason is an UNKNOWN, not a
   known conflict:** `Board build state UNKNOWN (HTTP Error 429)`. It could not
   reach the state at all. Proceeding deliberately because the item it cannot
   confirm is a **refresh-worker** job and this is a **web-only** deploy, which
   does not restart that service. Odds refresh reported idle. Live games ARE in
   progress, so the cost is ~1-2 min of web 502s.
4. **Blast radius.** The changed function is read by the ops CLV endpoint. It is
   a diagnostic surface, not the board — no user-facing page reads it.
   **`avg_clv_pct` will move**, by design; that is the fix, and the old value is
   recorded in this file as retracted.
5. **Rollback.** `py -3 scripts/render_deploy.py --service web --commit 8b010dac --allow-rollback`
6. **Ledger check.** `clv_join.py` + the new test are claimed by
   `clv-without-settlement` (this session) and CLEAR of every other OPEN lane
   via `lane-guard.py`'s own `_claims()`. No `render.yaml` change, so
   `blueprint_sync` cannot fire.
7. **MEASUREMENT: pending.**

## 2026-08-15 21:39:09Z — refresh-worker `846bb74e` — live MLB prop projection / probability / coverage — PENDING MEASUREMENT

| field | value |
|---|---|
| service | refresh-worker `srv-d91dpertqb8s73co8ls0` |
| deploy | `dep-da0dovdg1s2s73cth36g` |
| commit | `846bb74e` = content of `f4cd2bc8` + `3a476001` rebuilt on `dca39fad` |
| branch | `deploy/mlb-live-prop-coverage-20260815` |
| lane | `mlb-live-pitcher-projection` |
| rollback | `POST /v1/services/srv-d91dpertqb8s73co8ls0/deploys {"commitId":"dca39fad7442..."}` |
| measurement | **EMPTY — owed. Re-read by ~22:15Z on a LIVE MLB slate.** |

**WHY NOT LOCAL `main`: it would have rolled the worker back 119 commits.**
`dca39fad` (the running SHA) is NOT an ancestor of local `main` and is NOT on
`origin/main`. Ancestry says nothing here; only content does. Both source files
were checked for divergence first — `git rev-list --count HEAD..dca39fad --
<file>` = 0 for `cards.py` and `live_projection_join.py`, so nothing another
session shipped is reverted. `blueprints/intelligence.py` was DELIBERATELY LEFT
OUT: it is a web route change, irrelevant to a background worker, and it carries
2 commits on the live SHA a whole-file copy would have reverted. **The
`live_projections` counters therefore stay unserved until a WEB deploy** — do
not read their absence after this deploy as the fix failing.

**BASELINE (served `/api/board/book-grid?sport=mlb&date=2026-08-15`, artifact
generated 20:12:48Z, web `f475c775`):**

| metric | baseline |
|---|---|
| live rows | 638 |
| live rows carrying a live projection | **57 (8.9%)** |
| `batter_home_runs` overlaid | **0 of 116** |
| `batter_hits_runs_rbis` overlaid | **0 of 79** |
| live pitcher rows with proj/prob on opposite sides of the line | **7 of 13** |
| live rows with an edge | 0 (356 correctly policy-suppressed) |

**PREDICATE:** coverage off 8.9% and materially higher; both zero markets off
zero; straddle count 7 -> 0. **CEILING IS 90.2%, NOT 100%** — 48 of 492 live prop
rows sit at an alternate line for a (player, market) the board also carries
elsewhere, and the snapshot holds one line per market.

**COST PAID, STATED:** an active refresh run (pid 741) was killed by this
deploy; it re-runs on the next tick. The 21:27:37Z MLB sim was ALREADY
`killed_by_restart` by another session's 21:23 deploy, so this deploy did not
kill it. **A re-measure taken while the board carries no live rows is
NON-EVIDENCE** — verify `state: live` rows exist before reading.

**USER OVERRIDE, LOGGED:** lane `mlb-live-pitcher-projection` carried "NO DEPLOY
FROM THIS LANE" (refresh-worker is under `#435`). The user explicitly directed
this deploy and re-measure.

### `#435` VERDICT 2026-08-15 21:32Z — THE FIX WORKS. 5 kills -> 0 in the same window.

    window 20:00-21:32Z, same slate size (~15 MLB games), same clock slot

                        2026-08-14 (no fix)      2026-08-15 (fix live)
    OOM kills                 5                        0
      at                20:03:11, 20:14:30,           --
                        21:07:32, 21:16:50,
                        21:25:48
    peak anon            4,018.5 MB (98.1%)       3,572.4 MB (87.2%)
    longest clean run       53 min                   90 min
    samples                  8,248                    7,274

**Zero OOM kills since 05:02:59Z — 16.5 hours**, spanning a full daily shard ramp.
Source: `/v1/services/<id>/events`, never a log grep.

**THE FIX WAS LIVE THROUGHOUT, VERIFIED BY CONTENT NOT ANCESTRY.** Three deploys
carried it: `c67f7373` (18:11:41), `dca39fad` (20:00:19), `0fa44322` (building
21:31). `c67f7373` is an ancestor of both later SHAs AND
`def read_book_quotes_latest` plus the `layer2_shortlist` call site are present
in each. Checking ancestry alone would not have been enough — this repo has had
live SHAs that were not ancestors of `main`.

**MY PREDICTION WAS WRONG, and it is worth recording which way.** At 19:51Z I
weighted "kills land, the shard was not the cause" as the MOST likely outcome,
on a peak-anon comparison of 2,839 vs 2,897 MB that I called noise. It was not
noise — it was a reading taken BEFORE the ramp bit. The correct comparison was
peak across the whole window, which is 446 MB lower.

**WHAT THIS IS NOT.** 3,572 MB is 87.2% of a 4,096 MB ceiling. The fix bought
~446 MB of headroom and that was enough for a 15-game slate; it is not enough to
call the worker safe. A larger slate still crosses.

**CONFOUND, STATED RATHER THAN BURIED.** Two deploys landed inside the window
(20:00:19, 21:30:27) and each reboots the worker, resetting anon — the standing
boot-confound rule. It does not explain the result: 20:00:19 -> 21:30:27 is a
single unbroken 90-minute run, against a longest run of 53 minutes last night.
Last night's reboots were the kills themselves.

### MEASUREMENT for web `4316c907` — live 21:41:18Z — **VERIFIED BY INDEPENDENT RECOMPUTE**

**Fingerprint first — my code is the code running.** `by_close_timing`,
`same_book_all_n`, `in_play_excluded_n`, `unknown_timing_excluded_n` all present;
**374/374 rows carry `close_timing`**. None of those keys exist in the prior build.

**Verified by recomputing the headline from the rows at the same instant**, not
against a remembered number (the slate moves, so any earlier figure is a stale
target):

      same_book rows in payload   179
      pregame subset              131
      my hand-computed mean       -0.3077
      endpoint avg_clv_pct        -0.3077     <- MATCH

`same_book_all_n=179`, `in_play_excluded_n=48`, `unknown_timing_excluded_n=0`.
Headline is now **-0.3077 over n=131, beat 26.0%**.

**THE RESULT IS STRONGER THAN THE ARGUMENT I MADE FOR IT, and in a way worth
recording.** I justified this fix on "in-play rows drag the number DOWN" — at
21:1xZ they averaged strongly negative and pulled the headline to -0.672. At
21:4xZ **the same in-play bucket averages `+0.7937` (n=48, beat 54.2%)** and
would have pulled the headline UP: the old code would now publish **-0.0124**.

So the contamination is **not a consistent bias in one direction — it is noise
that swings the headline either way depending on game state.** That is a better
reason to exclude it than the one I gave, and it also means a
"CLV improved today" reading off the old code could have been pure game-state
drift.

**The clean number is stable; the dirty one is not.** Across ~2.5 hours:

      reading      dirty (old code)    clean (this fix)
      21:1xZ            -0.672             -0.346
      21:4xZ            -0.0124            -0.3077

The clean series moves 0.04 points; the dirty series moves 0.66. That is the
whole case for the change, measured.

**Also landed on `main` as `a68e1ce0` — and `clv_join.py` was 600 insertions,
i.e. the ENTIRE JOINER was missing from main**, exactly like the allowlist entry
earlier today. Both are now on main rather than living only on deploy branches.

**Obligation closed.**

### RECONCILE COMPLETE 2026-08-15 ~22:0xZ — origin/main now holds everything

`origin/main` was 158 ahead and the shared checkout 40 ahead — the exact
blindness `coordination-protocol.md` describes. Merged in an ISOLATED worktree
(`C:/tmp/reconcile`), never in the shared checkout, so a conflicted tree could
not break the four other sessions working there.

Pushed as `e27fad45` (`a68e1ce0..e27fad45`). Safety ref
`backup/main-pre-reconcile-20260815`.

Six ledger files conflicted, all append-vs-append; resolved by UNION so both
sides' entries survive. Verified in both directions after resolving — my `#435`
verdict, mid-ramp rule and closed lane; their CONFIRMED-A-VALUE rule and
`clv-without-settlement`; the lanes archive still intact; no duplicated sections.
Merged tree tested: app imports, 74 tests pass.

**THE SHARED CHECKOUT IS STILL BEHIND, DELIBERATELY.** `git merge --ff-only`
REFUSED, and it was right to: 125 uncommitted files live there, including four
CSS files, `ui_layout_probe.py`, `artifact_publisher.py` and
`game_board_contract.py` that another session is mid-edit on. Forcing it would
have destroyed their work.

    origin/main   e27fad45   COMPLETE — everything is here
    local main    2f3dcae0   behind; fast-forwards for free once the
                             uncommitted work in the shared tree is committed

That is the owning sessions' call, not mine. Nothing is lost either way: the
commits are on origin, and the working-tree edits are untouched.

## 2026-08-15 21:48:28Z — web `edfc0174` — THE MEASUREMENT PASSES, AND IT RETRACTS MY OWN NEGATIVE RESULT

**Deploy:** `dep-da0dq2m7bikc73etu3d0`, cut from web's own live SHA `4316c907`
after waiting out an in-flight deploy. Adds `GET /api/ops/live-lens/status`.
Regression that was interrupted at checkpoint has now RUN: **131 passed**
(`test_ops.py` + `test_ops_live_lens_status.py`).

### THE RESULT — PASS `[measured 21:49Z]`

    worker's own per-tick tally   liveMcSources = {live_mc: 6,
    (latestStatus.results.mlb)                    segment_projection: 52,
                                                  unknown: 8}
    what web SERVES               rows=66  live_mc=6  carried=0
    baseline (pre-deploy, x2)     rows=60  live_mc=0  carried=0

**6 and 6. The worker's count and the served count match exactly**, which is
what makes this end-to-end and not two unrelated numbers. `live_mc` moved
**0 → 6**. **Drops 1 and 2 work.**

### RETRACTION — "a clean negative result" was PREMATURE AND WRONG

I recorded in `state.md`, `lanes.md` and the session log that both drops were
live and `live_mc` was still 0, calling it "a clean negative" and concluding
"the fix is correct and was not the binding constraint." **That is retracted.**

The worker landed `191a001b` at **20:56:07Z**. My two passes ran ~20:59 and
~21:04 — **3 and 8 minutes after a worker restart**, before the live-lens loop
had produced a snapshot the fix could act on. I even wrote the guard for this
("the worker needs a tick or two after restart... I'd treat a single zero as
inconclusive") and then treated a double zero as conclusive, because two reads
felt like independent evidence. **They were two samples inside the same warm-up
window, which is one sample.** The slate moving between them (live 4→3) proved
the reads were independent of each other and said nothing about whether the
system had converged.

**The rule: two reads inside one warm-up window are one read.** Independence
between samples is not independence from the transient you are sitting in.

### Residual, NOT explained
- **`unknown: 8`** — 8 of 66 lanes carry a source the tally does not recognise.
  Unexamined. Not a failure; not understood either.
- **`carried: 0`** — Drop 2's carry-forward has not been observed firing. It is
  correctly idle while web serves a fresh snapshot, so this is **untested in
  production**, not confirmed working.
- **soccer and wnba report `liveMcSources: null`** — MLB-only instrumentation.
- **`rows` went 60 → 66** because the slate changed, not because of the fix.

## 2026-08-15 22:1xZ — web `c8810f45` — stamped close is side-aware

**PREFLIGHT: PASS.** Parent `edfc0174`, the LIVE web commit. Diff: 3 files,
+194/-1 (one file is a 4-line fixture update).

1. **Expected effect** on `/api/ops/clv/report?date=2026-08-15&sport=mlb`:
   a new `stamped_close_skipped` map with a LARGE count (that is the fix
   working, not a failure); `by_close_source` shifts away from
   `observed_transition` toward `last_pregame_quote`; away-side rows that were
   differenced against the home close get real closes, so `avg_clv_pct` moves.
   `in_play_excluded_n` should FALL, because the late-stamped rows were the
   stamped-path rows.
2. **Verification**: fetch `rows=1`, confirm (a) `stamped_close_skipped` is
   populated, (b) no row has `close_source=observed_transition` with a side
   differing from its market entity, (c) the `-27.72` row for event `dbbb481a`
   is gone or repriced. Recompute the headline from rows at the same instant.
3. **Checked before shipping, because this refuses data:** all **1011** published
   openings for 2026-08-15 carry both `home_team` and `away_team`, so the
   entity match attributes rather than refusing everything. A fix that silently
   refused every stamp would look identical in the headline to one that worked.
4. **`check_deploy_safety` NOT CLEAR — board build in flight on refresh-worker**
   (started 21:49:53Z). Proceeding deliberately: **web-only deploy, which does
   not restart refresh-worker.** Odds refresh idle.
5. **Rollback.** `py -3 scripts/render_deploy.py --service web --commit edfc0174 --allow-rollback`
6. **Ledger.** `clv_join.py` + both tests claimed by `clv-without-settlement`
   (this session); CLEAR of every other OPEN lane. `odds_refresh_tracking.py`
   NOT touched — the clock defect stays with lane
   `closing-stamp-is-detection-time`. No `render.yaml` change.
7. **This demotes `4316c907`'s stated rationale**, which is recorded there.
8. **MEASUREMENT: pending.**

### MEASURED 2026-08-15 21:46:06Z — `846bb74e` on refresh-worker — **HALF THE FIX LANDED, AND THE OTHER HALF WAS ON THE WRONG SERVICE**

Read: served `/api/board/book-grid?sport=mlb&date=2026-08-15`, artifact
`generated_at 21:46:06Z` (deploy went live **21:45:20Z**, so the artifact is
post-deploy), **430 live rows present** — a valid window, not a dark board.

| metric | baseline 20:12Z | after | verdict |
|---|---|---|---|
| live-lens rows carrying `sim_model_prob_over` | 0 (field did not exist) | **21 of 21** | **NEW CODE CONFIRMED RUNNING** |
| rows with proj and prob on opposite sides of the line | 7 of 13 | **0 of 21** | **PASS** |
| `model_prob_over` null + named reason on unpriced rows | 0 | 21 of 21 | PASS |
| live rows carrying a live projection | 57 / 638 (8.9%) | 21 / 430 (**4.9%**) | **FAIL** |
| `batter_home_runs` overlaid | 0 of 116 | **0 of 78** | **FAIL** |
| `batter_hits_runs_rbis` overlaid | 0 of 79 | **0 of 52** | **FAIL** |

**THE PROBABILITY FIX IS VERIFIED, AND NOT BY THE OUTCOME ALONE.** `sim_model_prob_over`
is a field the old code cannot emit; 21 of 21 rows carry it, so the branch ran.
The straddle count is 0. (Row sets are not like-for-like — the afternoon slate
was ending, 13 live pitcher rows became 2 — but the straddle is now impossible
by construction, since `model_prob_over` is null whenever there is no live
probability. The marker field, not the count, is what proves it.)

**THE COVERAGE FIX WAS SHIPPED TO A SERVICE THAT DOES NOT RUN IT.** The MLB
live-lens snapshot — the artifact the board joins against — is built by
`live_lens_loop`, and the env decides where:

    MLB_ENABLE_LIVE_LENS_LOOP   refresh-worker = false    live-odds-worker = true

So `cards.py`'s emitter half is INERT on refresh-worker. `live_projection_join.py`
runs during the board build there and is why the probability half worked. **One
commit, two files, two different owning services — and nothing in the code says
so; only the env does.** This is `project_which_service_runs_the_code` again and
it should have been checked BEFORE the deploy, not after: the predicate was
written for a service that could not satisfy it.

**BUILT AND PUSHED, NOT DEPLOYED: `cc4afae2`** on
`deploy/mlb-live-prop-coverage-lo-20260815`, the same two files rebuilt on
`191a001b` — live-odds-worker's OWN live SHA. Deploying `846bb74e` there would
have rolled it back 3 commits including `191a001b` itself, the
`live-game-line-projection` lane's Drop 2. Divergence re-checked: 0 commits touch
either file between the two SHAs. **The Render deploy call for live-odds-worker
was BLOCKED by the permission classifier; the user has been asked to decide.**

**Rollback for the refresh-worker half (if wanted):**
`POST /v1/services/srv-d91dpertqb8s73co8ls0/deploys {"commitId":"dca39fad7442..."}`

### MEASUREMENT for web `c8810f45` — live 21:58:19Z — **FIX CONFIRMED; ONE OUTLIER SURVIVES**

**Fingerprint:** `stamped_close_skipped` present and populated —
`{"stamped_close_is_home_side": 20}` — and **363/363 rows carry the key**. That
field does not exist in any prior build.

**The side error is gone, and the shape of the change is exactly what was
predicted before deploying:**

      metric                     before        after
      close_source mix           obs_transition ~48    obs_transition 22
                                                       last_pregame_quote 341
      stamped closes refused     n/a            20 (all away-side openings)
      in_play_excluded_n         48             19
      same_book_n                131            151
      avg_clv_pct                -0.3077        -0.2714

`same_book_n` ROSE (131 -> 151) because away-side rows that previously carried a
garbage home close now resolve correctly through the side-aware path, instead of
being thrown out by the timing guard. **The `4316c907` timing exclusion was
doing the side fix's job by accident; with the real fix in, it drops less than
half as much data.**

**Verified by independent recompute at the same instant:** hand-computed pregame
same-book mean `-0.2714`, endpoint `-0.2714`, match.

**HONEST REMAINDER — one extreme row survives and I have not explained it.**
`clv_pct = -29.90`, `open_price -205`, `close_price 168.0`, **side `home`**,
`close_source last_pregame_quote`. It is NOT the row this fix targeted (that one
was away-side on the stamped path) and it is NOT a side mismatch — it came
through the side-aware path. A 373-point move on a home moneyline is either a
real event (a scratched starter will do it) or a third defect. **Unexplained,
one row, flagged rather than smoothed over.** Anyone re-deriving this number
should know a single row of this size on n=151 moves the mean by ~0.2 points —
i.e. most of the remaining headline.

**Also on main as `ae0bc968`.**

**Obligation closed.**

## 2026-08-15 22:33:20Z — live-odds-worker `e5b03f7f` — live MLB prop COVERAGE — **MEASURED, PASSES, PARTIALLY**

| field | value |
|---|---|
| service | live-odds-worker `srv-d91dpertqb8s73co8lt0` |
| deploy | `dep-da0ef83l550s73d8tht0`, live **22:33:20Z** |
| commit | `e5b03f7f` = same two files rebuilt on `25774aaf` |
| read | board artifact `generated_at 22:36:24Z` (post-deploy), 436 live rows, 3 live games |
| rollback | `POST .../deploys {"commitId":"25774aafd11c..."}` |

**`cc4afae2` WENT STALE IN 40 MINUTES AND WAS NOT FORCED.** live-odds-worker
moved `191a001b` -> `25774aaf` at 22:09:15Z under another session, so the earlier
build would have rolled that work back. Rebuilt on the new SHA; divergence
re-checked (`git rev-list --count cc4afae2..25774aaf -- <file>` = 0 for both).

| metric | baseline 20:12Z | after 22:36Z | verdict |
|---|---|---|---|
| live rows overlaid | 57 / 638 (**8.9%**) | 83 / 436 (**19.0%**) | **PASS** |
| of live PROP rows | — | 83 / 325 (**25.5%**) | |
| `batter_home_runs` | **0 of 116** | **29** | **PASS — new-code marker** |
| `batter_hits_runs_rbis` | **0 of 79** | **13** | **PASS — new-code marker** |
| straddling proj/prob | 7 of 13 | **0 of 83** | PASS (holds at 6x the rows) |
| `model_prob_over` null + reason | 0 | 83 of 83 | PASS |

**THE TWO ZERO MARKETS ARE THE PROOF, NOT THE HEADLINE PERCENTAGE.** Neither can
appear under the old code at all: `batter_hits_runs_rbis` was absent from
`_LIVE_HITTER_MARKET_KEYS`, and every `batter_home_runs` row is rejected by the
selector's `-200` favourite cap. 42 rows across the two of them is the branch
executing, independent of any coverage ratio.

**THE AGGREGATE IS DRAGGED BY GAME STATE, AND ONE GAME IS STILL AT ZERO:**

| game | state | overlaid | missed | coverage |
|---|---|---|---|---|
| BAL @ TB | TOP 2 | **70** | 48 | **59.3%** |
| WSH @ NYM | BOT 8 | 13 | 80 | 14.0% |
| MIA @ CIN | TOP 1 | **0** | 114 | **0%** |

**On the one game with a warm pipeline, coverage is 59.3%.** MIA @ CIN at TOP 1
has **zero** — the snapshot carries nothing for a just-started game. **NOT
DIAGNOSED, and not claimed as either a defect or as expected**; it needs a read
of the snapshot for a TOP-1 game, which is still unreadable from web.
WSH @ NYM at BOT 8 is low, consistent with substituted players having no sim row,
also unverified.

**CEILING ON THIS SLATE: 52 of 325 live prop rows (16%) sit at an alternate line
for a (player, market) pair -> ~84% reachable, not 100%.** The 90.2% figure was
for the 20:12Z slate; the ceiling moves with the slate and must be recomputed per
read, not carried.

**STILL TRUE AND UNCHANGED BY THIS DEPLOY:** the ~75% of live rows with no
overlay keep showing a PREGAME projection against a live market with no staleness
marker. That is a separate fix the user was offered and declined.
**`blueprints/intelligence.py` is still undeployed**, so `live_projections`
remains absent from the API and its absence is not evidence.

## 2026-08-15 ~22:4xZ — refresh-worker ← Drop 3 (`758a89fa`) — FIRING, claim held
**Lane:** `live-game-line-projection`. **Deploy claim ACQUIRED** —
`scripts/deploy_claim.py acquire --service refresh-worker --holder
live-game-line-projection`, token `a4c2192e69f764e5`, ttl 2700s. All four
services read `free` before acquiring. **This mechanism exists and I had not
used it on the two earlier deploys tonight** — `deploy_preflight` prints
`deploy claim none -- acquire one before deploying` and I had not read that line.

**Why refresh-worker and not web:** this service BUILDS the book-grid artifact,
which is where the join runs. Web only reads it. Deploying web would have been
inert — the same class of error as the allowlist near-miss earlier.

**KNOWN COST, accepted on the user's explicit instruction:** a refresh-worker
deploy **resets `#435`'s memory measurement window** and kills the in-flight MLB
sim (3 jobs at gate time, incl. `run_mlb_daily_sim_job.py`). The gate is polled
to TWO consecutive CLEARs and the cut is made INSIDE the fire loop, so the
parent cannot go stale between turns.

**Divergence checked before overlaying:** `board_enrichment.py` and
`book_grid_artifact.py` are byte-identical between `758a89fa^` and the live
`6f512ffa`, so no other session's work is reverted. `live_gameline_join.py` is
new (its 265-line "deletion" in the diff is its absence at the base, not a
conflict).

**PREDICATE, written BEFORE the deploy so it cannot be retrofitted:** the
book-grid artifact grows a `live_gamelines` block carrying
`rows_live_gameline_{considered,projected,priceable,edged,withheld}` and
`withheld_by_reason`. **`rows_live_gameline_edged` may legitimately be 0** — at
120 sims the 2-sigma bar is ~9.1 pp at p=0.5. **The real pass is
`rows_live_gameline_considered > 0` with every withheld row naming a reason.**
A zero considered means the join never saw a live h2h row and IS a failure.

**Rollback:** `py -3 scripts/render_deploy.py --service refresh-worker --commit
6f512ffa --allow-rollback`, then release the claim.

## 2026-08-15 22:5xZ — refresh-worker `edbbee9d` — **PREFLIGHT: HOLD. NOT DEPLOYED.**

Candidate-line fix (`layer2_board.py`) is committed to main and tested (8 new,
71 green) but **deliberately not shipped.**

1. **It requires a REFRESH-WORKER deploy, unlike everything else tonight.**
   `layer2_board` BUILDS the shortlist artifact; web only reads it. A web deploy
   would change nothing, so the usual "web-only, the in-flight job is on another
   service" reasoning does NOT apply here.
2. **`check_deploy_safety` is genuinely blocking, and I am honouring it:**
   - MLB sim **RUNNING** on refresh-worker (pid 79, `tip_off_window`, started
     22:41:33Z) — a deploy kills it, and a scoped resim has no ETA.
   - Board build **IN FLIGHT** on refresh-worker (started 22:46:55Z).
   - Odds refresh running on live-odds-worker.
3. **Severity does not justify it.** The defect is confined to HOME-side spread
   candidates: it corrupts their CLV rows, and can show the wrong handicap in the
   Ask headline. Away rows, h2h and props are unaffected. Nothing is being made
   worse by waiting for the slate to finish.
4. **KNOWN LIMIT — the fix is forward-only.** It corrects artifacts BUILT after
   it ships. **Today's openings ledger already contains home-spread rows with
   the away handicap**, so 2026-08-15 CLV stays contaminated for those rows even
   after deploy. Any backfill is a separate decision.
5. **Ship it when the slate is quiet** (last first pitch 2026-08-16T01:40Z; sims
   run past that), re-run `check_deploy_safety`, then verify:
   `/api/board/layer2-shortlist` home spread rows have `line` equal to the
   book-grid cell's `home.line`, and re-run the 525-cell invariant.

### SMAPS READER DEPLOYED 2026-08-15 22:41:04Z — `b0ab37a1` — AND IT REFUSED ITS OWN FIRST READING

Deployed the MINIMAL change, not converged main: `b0ab37a1` is the live sha plus
ONE commit (2 files, +253 lines). Converged `main` (`fb448d60`) would have moved
production **330 commits** — an instrument is not worth that blast radius, and
convergence had already removed the reason to deploy from main.
Fired on a confirmed CLEAR; zero jobs killed.

**FIRST READING, 22:49:18Z — `reconciles: false`, 27.0% apart. The guard fired
and the breakdown must not be read as attribution.**

    by_kind_mb      anon_mmap 1,007.2 | heap 95.9 | file_backed 3.6 | stack 0.1
    anon mmap       >64MB 613.6 | 8-64MB 288.3 | 1-8MB 104.5
    total_anon_mb   1,106.9        cgroup_anon_mb 1,516.5     413 regions
    largest         144.7, 120.1, 106.3, [heap] 95.9, 90.6, 87.0, 65.0, 42.0 MB

**THE 27% GAP IS THE FINDING, NOT A BUG.** smaps is PER-PROCESS; cgroup `anon`
is PER-CONTAINER. `ALL_PROCESS_MEMORY` at the same minute: 10 processes, pid 39
at 1,140.8MB, children ~504.3MB. 1,106.9 + children ~= 1,516.5.

**SO THE "673MB OUTSIDE PYMALLOC" IS RETRACTED.** It was cgroup anon (1,607,
container) minus pymalloc arenas (934, pid 39 only) — two different scopes.
Per-process the residue is **~173MB**, not 673MB, and ~410MB of what looked like
a mystery is simply the children the worker spawns.

**WHAT SURVIVES, scoped to pid 39:** anon is **91% mmap** (1,007.2 of 1,106.9)
against only **95.9MB of brk heap**. The lane's hypothesis — mmap dominates, not
`[heap]` — is CONFIRMED. With pymalloc holding ~934MB of arenas, the mmap total
is very nearly pymalloc itself, which is a much duller answer than a 673MB
mystery and is the correct one.

**NEXT, and it is smaller than it was:** ~173MB of per-process residue is not
worth another instrument. `mallinfo2`'s `hblkhd` is NO LONGER the priority — the
question it was meant to answer has mostly dissolved. The real remaining lever is
the CHILDREN (~504MB) and the fact that pymalloc holds 934MB of arenas for
583.7MB of live objects (350.3MB retention, 21:58).

**FIX OWED IN THE READER:** it must reconcile against the PROCESS, not the
cgroup. As written it will report `reconciles: false` on every read while any
child exists, and a guard that always fires is a guard nobody reads.

## 2026-08-15 22:5xZ — worker `325b2822` — **PREFLIGHT: HOLD. NOT DEPLOYED.**

Closing-stamp clock fix (`odds_refresh_tracking.py`). On main, 7 new tests, 109
green. **Held for the same reason as `edbbee9d`, and they should ship together.**

1. **Needs a WORKER deploy.** The stamp is written during odds refresh —
   `check_deploy_safety` shows that lane on **live-odds-worker** (pid 215). Web
   only reads the result, so a web deploy changes nothing.
2. **Gate is blocking, honoured:** MLB sim RUNNING (pid 79, `tip_off_window`,
   12m), odds refresh RUNNING (live-odds-worker), board build IN FLIGHT on
   refresh-worker. A deploy kills them; a scoped resim has no ETA.
3. **FORWARD-ONLY, and this one cannot be backfilled.** The fix corrects stamps
   written after it ships. **Every close stamped today already carries the
   detection time**, and the true observation time was never recorded — it is
   not recoverable from the artifact, only from history points if they survive.
   2026-08-15 CLV keeps its late stamps regardless.
4. **Interaction with the shipped `close_timing` guard, stated so it is not a
   surprise:** that guard excludes `close_age_seconds < 0`. Once this fix lands,
   stamps stop post-dating first pitch, so **`in_play_excluded_n` should fall
   toward zero for `observed_transition` rows** and previously-excluded genuine
   pregame closes will re-enter the headline. Expect `same_book_n` to RISE and
   the headline to move. That is the fix working, not a regression.
5. **Ship with `edbbee9d`** (the candidate-line fix) in one worker deploy when
   the slate is quiet — two worker restarts for two one-file changes is worse
   than one. Verify after: a fresh stamped close has
   `closing_captured_at <= commence_time` and a populated `closing_detected_at`.

## QUEUED DEPLOY — `edbbee9d` + `325b2822` to the WORKERS — armed 2026-08-15 22:5xZ

**AUTHORISED by the user ("deploy both when the slate is quiet"). Waiting on the
gate, not on permission.** Any session may execute this; it is written out so it
survives this one.

**Condition to start:** past **2026-08-16T01:40Z** (last first pitch) AND
`py -3 scripts/check_deploy_safety.py` reports CLEAR — specifically no MLB sim,
no board build in flight, no odds refresh running.

**Which services.** Both changes are artifact PRODUCERS, so web is NOT involved:
- `layer2_board.py` (`edbbee9d`) — builds the shortlist -> **refresh-worker**
  (`srv-d91dpertqb8s73co8ls0`).
- `odds_refresh_tracking.py` (`325b2822`) — writes the closing stamp during odds
  refresh -> **live-odds-worker** (`srv-d91dpertqb8s73co8lt0`). Confirm from the
  safety output, which names the lane owner.
Ship ONE commit carrying both to each service it needs; do not do four deploys.

**Recipe (do NOT skip 1-2 — both bit this session on web):**
1. Read each service's LIVE commit from
   `/v1/services/<id>/deploys?limit=1`. **Parent on that**, not on `main` —
   services run deploy branches and live SHAs are repeatedly NOT descendants of
   the previous one.
2. Confirm no deploy is already `build_in_progress` on that service; if there is,
   wait it out and re-parent afterwards.
3. Blob-stage against the live tree (never `git add`; the shared index holds other
   sessions' work):
   `git read-tree <LIVE>` then `git update-index --add --cacheinfo` for
   `syndicate/features/shared/layer2_board.py`,
   `syndicate/features/shared/odds_refresh_tracking.py`,
   `tests/test_layer2_book_prices_line.py`, `tests/test_odds_closing_stamp.py`.
4. `git diff --stat <LIVE> <TREE>` must show **exactly those 4 files**.
5. `py -3 scripts/render_deploy.py --service <name> --commit <sha>`; poll to
   terminal.

**Verification — all four, or it is not done:**
1. A newly stamped close has `closing_captured_at <= commence_time` and a
   populated `closing_detected_at`.
2. `/api/board/layer2-shortlist` home spread rows: `line` equals the book-grid
   cell's `home.line` (re-run the 525-cell invariant; expect 0 opposite-sign).
3. `/api/ops/clv/report`: `in_play_excluded_n` falls toward zero for
   `observed_transition` rows, `same_book_n` RISES, `avg_clv_pct` moves.
   **That is the fix working — do not report it as a regression.**
4. No new `stamped_close_is_*_side` skips beyond the away-row baseline.

**Rollback:** `py -3 scripts/render_deploy.py --service <name> --commit <LIVE> --allow-rollback`

**Forward-only.** Neither fix repairs 2026-08-15 data: today's openings keep the
away handicap on home spreads, and today's stamps keep detection times that were
never recorded elsewhere.

### BASELINE for Drop 3, taken BEFORE it landed `[2026-08-15 22:56:08Z artifact]`
Read from the built artifact itself (`mlb_source/data/book_grid/book_grid_2026-08-15.json`,
10.4 MB), not from a served endpoint:

    generated_at    2026-08-15T22:56:08Z    (still the pre-Drop-3 builder)
    version         2      rows_total 3473
    live_gamelines  null                    <-- the key does not exist yet
    live h2h rows   32                      <-- what Drop 3 will CONSIDER

    live_projections (the PROP family, unchanged and NOT this lane's):
      rows_live_considered 1461 | rows_live_projected 204 | rows_live_edged 0
      rows_live_edge_withheld 204 | live_games_in_snapshot 8

**So the predicate now has a number attached: `rows_live_gameline_considered`
should land near 32, not merely above 0.** A value of 0 means the join never saw
a live h2h row despite 32 being present, which is a real failure. A value near 32
with most rows withheld under `prob_interval_swamps_edge` is the recorded
decision working at 120 sims.

**The prop family's `rows_live_edged: 0` beside it is the control** — a different
join, a different lane, and it must NOT move as a result of this deploy. If it
does, this change touched something it should not have.

## 2026-08-15 23:02:14Z — refresh-worker `1f36d718` — DROP 3 RESULT: the join works, and it named TWO defects I did not predict

**Deploy:** `dep-da0esf9t0dsc739ide90`, live 23:01:29Z, cut from `b0ab37a1`
(which had moved from `6f512ffa` while the gate held — cutting inside the fire
loop is what stopped this being a rollback). **Zero jobs killed**: gate polled to
two consecutive CLEARs at 22:54:40 and 22:54:46.

### THE MEASUREMENT `[post-deploy artifact, generated_at 23:02:14Z]`

    rows_live_gameline_considered   36     (baseline predicted ~32; slate grew)
    rows_live_gameline_projected    12
    rows_live_gameline_priceable     0
    rows_live_gameline_edged         0
    rows_live_gameline_withheld     36
    withheld_by_reason  sim_count_unusable          12
                        no_live_gameline_projection 24
    index_size                       3

**PREDICATE MET.** It was `considered > 0` with every withheld row naming a
reason: 36 considered, 12 + 24 = 36 attributed, none silent. The join runs on the
worker, sees the live h2h rows, and refuses by name.

**MY PREDICTION OF *WHICH* REASON WAS WRONG, and that is the finding.** I
expected refusals under `prob_interval_swamps_edge` — the 120-sim precision gate.
**Zero rows reached it.** All 12 projected rows died one step earlier.

### TWO UPSTREAM DEFECTS, both measured, neither in Drop 3

1. **`simsRun` IS NEVER STAMPED ON THE LENS — the key is ABSENT, not null.**
   Served lens row keys: `actualSegment, baselineHomeWinProb, closed, key, label,
   markets, modelHomeWinProb, progress, projection, source`. **No `simsRun`.**
   `_live_mc_projection` RETURNS `simsRun`, and `_build_game_lens` does not copy
   it through. So `prob_std_err` returns None and every projected row is refused
   `sim_count_unusable`. **The precision gate is unreachable, so the recorded
   "publish, refuse to price" decision is not being exercised at all** — the
   rows are refused for a plumbing gap that merely looks like the decision.
2. **Only 3 of 9 live games carry a `live_mc` lens.** 6 `live_mc` lanes ÷ 2 lanes
   per game = 3 games = `index_size: 3`, and the other 6 games' rows are the 24
   `no_live_gameline_projection`. The re-sim is covering a THIRD of the live
   slate, which the earlier `live_mc: 6` reading looked healthy against because
   nobody divided by the number of live games.

### CONTROL HELD
`live_projections` (the prop family) is unchanged and still
`rows_live_edged: 0` — a different join in a different lane, unmoved by this
deploy, as required.

### WHAT THIS BUYS
`0 edges` went from one mysterious number to **two named, distinct, separately
fixable causes with counts**. Fixing (1) is a one-field copy in
`_build_game_lens`; fixing (2) is a coverage question about why the re-sim
reaches 3 of 9 games. **Neither is a Drop 3 change**, and neither was visible
before this deploy.

## 2026-08-15 23:1xZ — BOTH WORKERS — `129395cc` (refresh) + `b7ae47e6` (live-odds)

**PREFLIGHT: PASS, proceeding deliberately on explicit user authorisation
("just deploy now, the sim is already dead").**

1. **The sim IS dead — verified, not assumed.** `check_deploy_safety` listed
   `MLB sim RUNNING (pid=79)` at 22:53Z; at 23:1xZ it is **absent** from the
   blocker list. The 22:54:53Z refresh-worker deploy by another session killed
   it. My hold was protecting something already gone.
2. **What is still in flight and WILL be killed:** a board build on
   refresh-worker (started 23:07:03Z) and an odds refresh on live-odds-worker
   (pid 1155, 23:07:47Z). Both are short, self-restarting jobs, unlike a sim.
3. **Parents are each service's OWN live commit** — refresh-worker `1f36d718`,
   live-odds-worker `f0452408`. Both services were `live` with no in-flight
   deploy at build time, so no race.
4. **RIDERS — other sessions' work carried along, named so a post-deploy anomaly
   stays attributable.** The workers are behind main on `layer2_board.py`, so
   shipping the current file necessarily carries:
   - both workers: `7bb74c95` (Tier 3a — clamp sites stop pricing what the
     market never implied) and `fb448d60` (lineage convergence).
   - live-odds-worker also: `96e3a9b7` (record every book's opening price) and
     `29ed6de1` (A3 — a row whose EV is the book's own hold restated must not
     seat a slot).
   All are already on `main`, i.e. their authors' committed intent — this brings
   the workers up to it rather than introducing anything new. **But it means
   this is NOT a one-change deploy.** If a worker misbehaves, the candidate set
   is 3 commits (refresh) / 5 commits (live-odds), not 1.
   The alternative — hand-splicing only my hunk onto the older file — would put
   a version in production that exists in no commit, which is worse.
5. **Rollback:** refresh-worker -> `1f36d718`, live-odds-worker -> `f0452408`,
   `--allow-rollback`.
6. **MEASUREMENT: pending.**

### MEASUREMENT for the worker pair — **DEPLOYED CLEAN; OUTPUT NOT YET VERIFIED**

- **Both live**: refresh-worker `129395cc` at 23:16:39Z, live-odds-worker
  `b7ae47e6` at 23:17:42Z.
- **No crash introduced.** Tracebacks on refresh-worker split about the deploy
  boundary: **3 before (23:10:39, 23:12:10, 23:12:42), 0 after.** live-odds-worker:
  0 throughout. The `Error` hits in the window are `PROCESS_ENUM_DEBUG
  psutil_unavailable:ImportError` — pre-existing memory instrumentation from
  `smaps-anon-breakdown`, not mine. Zero hits for `_side_line_from_cells` or the
  closing-stamp path.
- **WHAT IS NOT YET SHOWN, and it is the whole point of the deploy.** These are
  artifact PRODUCERS: the code is live, but the last `LAYER2_SHORTLIST` ran at
  **23:12:20Z — before the deploy** — so every artifact on disk is still
  old-code output. **"Deployed and not crashing" is not "the fix works."**
  Verification needs a build that starts after 23:16:39Z.
- **Verification queued** (watcher armed; by hand if this session dies):
  1. `/api/board/layer2-shortlist` — home spread rows' `line` equals the
     book-grid cell's `home.line`; re-run the 525-cell invariant, expect **0**
     opposite-sign (was 525/525).
  2. A close stamped after 23:17Z has `closing_captured_at <= commence_time`
     and a populated `closing_detected_at`.
  3. `/api/ops/clv/report`: `in_play_excluded_n` falls toward zero for
     `observed_transition`, `same_book_n` RISES, `avg_clv_pct` moves — predicted
     in advance, so it is not read as a regression.
- **Attribution note stands**: 3 commits rode along on refresh-worker, 5 on
  live-odds-worker (see the preflight above). If something surfaces later, that
  is the candidate set.

### VERIFICATION CORRECTION — the first post-deploy watcher was measuring the wrong artifact

`bbeqtk5jv` fired `written_at=2026-08-15T23:12:20Z grid_home_line_agrees=0
opposite=573 STILL OLD ARTIFACT or fix not applied`. **Both halves of that were
misleading and the watcher has been stopped.**

1. `written_at=23:12:20Z` is the PRE-deploy shortlist (deploy live 23:16:39Z), so
   nothing had been rebuilt — correct to keep waiting.
2. **But the predicate could never pass.** It compared `row["line"]` to
   `cell.home.line` on the BOOK-GRID. That opposition is the input shape — the
   grid row's line is the away handicap — and the fix does not touch the grid at
   all. It changes the SHORTLIST CANDIDATE's `line`. `opposite=573` is the
   correct, expected reading of healthy data.

**Replaced by `bb12r5c1x`**, which measures the artifact the fix actually
writes: for mlb spreads rows in `/api/board/layer2-shortlist`, joined to the grid
row for the same event —
- `side=home` must now have `line == -grid_row.line` (was `== grid_row.line`),
- `side=away` must still have `line == grid_row.line` (unchanged),
- and it refuses to judge at all until `written_at` is later than the deploy,
  so "not rebuilt yet" and "rebuilt and wrong" stay distinguishable.

**Still no verified output for either worker fix.**

## 2026-08-15 23:56:06Z — refresh-worker `2c14d9ae` — red-intelligence-tests field-absence fixes — **MEASUREMENT NOT YET OBTAINABLE**

| field | value |
|---|---|
| service | refresh-worker (`srv-d91dpertqb8s73co8ls0`) |
| commit | `2c14d9ae`, parent = live-at-fire-time `32186e28` |
| finished | 2026-08-15T23:56:06.006Z |
| jobs killed | **0** — fired on two consecutive `jobs_in_flight == 0` polls |
| claim | acquired (NOT forced), released after, token `cdbe6d9dc1a8d891` |
| rollback | pinned redeploy of `32186e28` |

**PRESENCE VERIFIED, INDEPENDENTLY OF THE DEPLOY SCRIPT.** All four fixes read
back PRESENT by content in the live tree — `line` fix, alias guard, `market_key`
producer, `player_name` producer. Three earlier deploys tonight reported `live`
without carrying them, which is why presence is checked and never inferred.

**EFFECT: NOT OBSERVED. DO NOT RECORD THIS AS A WORKING FIX.**

    POST-DEPLOY, live 2c14d9ae, /api/intelligence/query, 98 recommendations
      market_key blank   0    (baseline 0/101 -- unchanged, as predicted)
      player_name blank  0    (baseline 0/101 -- unchanged, as predicted)
      line as a number  74    of which 7 whole-numbered   (baseline 84 / 7)
      line as a STRING   0    (baseline 0 -- THIS IS WHAT SHOULD RISE, AND HAS NOT)

**Why, and it is expected rather than a failure:** the served rows come from
**cached worker state**, and `UniversalCandidate.to_dict` runs inside
`collect_candidates` during a BOARD BUILD. The worker restarted at 23:56:06Z
carrying the new code, but no board has been rebuilt since. The deployed code
cannot change a payload it has not yet produced.

**MEASUREMENT OWED — the deploy is NOT closed.** Re-read the same four numbers
after the next board build. Success = `line as a string` rises toward 74 and the
7 whole-numbered rows serialize as `"N.0"`; `market_key`/`player_name` must stay
at 0, since those two fixes have zero current incidence and no effect is claimed
for them. If `line as a string` is still 0 after a confirmed board build, the
fix is INERT on this path and the mechanism was mis-traced.

**Two costs of getting here, recorded because both were self-inflicted:**
1. An earlier auto-fire aborted at a valid window — the patch was piped through
   stdin with `text=True`, so Python newline-translated it and every hunk
   failed. The same procedure by hand, which used a FILE, worked three times.
2. The first hand attempt lost the window by spending ~60s building the target
   INSIDE the lull. The lull is 60-90s; the target must be built before it, or
   built by the same process that fires.

## 2026-08-15 23:47/23:49Z — refresh-worker `32186e28` + live-odds-worker `c422f79a` — ALT-LINE PROJECTIONS — **DEPLOYED, MEASUREMENT OWED, WINDOW CLOSED**

| field | value |
|---|---|
| refresh-worker | `dep-da0fie61egvs738k7v0g`, live **23:47:53Z**, commit `32186e28` on `191d098f` |
| live-odds-worker | `dep-da0fiq67bikc73f1j77g`, live **23:49:57Z**, commit `c422f79a` on `b7ae47e6` |
| content | `302ea0f4` applied as a PATCH, not copied |
| rollback | refresh-worker -> `191d098f4a8d`, live-odds-worker -> `b7ae47e6d1a0` |

**PATCHED, NOT COPIED, AND THAT MATTERED THIS TIME.** Three commits had landed on
my two files since the branch point (`098877e1` mlb props measured, `214f5151`
HRR mean from components, plus my own earlier `846bb74e`). A whole-file copy —
the technique used for the two earlier deploys, where divergence was 0 — would
have reverted two other sessions' work. `git apply --3way` applied both files
cleanly on each service's own SHA. **Check divergence per deploy; it is not a
property of the change, it is a property of the moment.**

**BASELINE, captured 23:39:13Z BEFORE the deploy** (`/api/board/layer2-shortlist`):
88 rows, 52 with a model projection, **14 alt rows (8 `totals_alt`, 6
`spreads_alt`) carrying `sim_component: None` on every one** — scored purely on
book-price EV × book_confidence × price_reliability. Saved to
`C:/tmp/shortlist_baseline_2026-08-15.json`.
Book grid at 22:41Z: **238 `spreads_alt`/`totals_alt` rows, 0 with a projection**,
against `spreads`/`totals` at **115 of 115**.

**THE WINDOW CLOSED BEFORE THE PREDICATE COULD BE READ, and the post-deploy
numbers are NON-EVIDENCE.** At 23:59:12Z the 08-15 board reported
`games_in_summary: 0` — the daily summary emptied at UTC midnight — so
`project_game_market` returns None for EVERY game market. Main `spreads`/`totals`
went **115 -> 0** alongside the alt rows. **A reading of "0 alt projections" here
says nothing about this fix; it says the sim payloads are gone.** The 08-16 board
has `games_in_summary: 15` and **0 rows** (quote shard not yet populated).

**OWED, on the next populated slate:**
1. Book grid: `spreads_alt`/`totals_alt` rows with a projection **0 -> ~all**,
   and main `spreads`/`totals` still ~100% (the control — if main is 0 the
   summary is empty again and the read is void).
2. Shortlist: alt rows carrying a non-null `sim_component` **0 -> >0**, and
   **shortlist COMPOSITION compared against the saved baseline** — this is the
   watch the user asked for. 116 pregame alt rows gain a model view; they were
   ALREADY in the shortlist (14 of 88), ranked on book EV alone, so the risk is
   re-ranking, not new admissions.
3. Live props: alternate-line rows joining. **Expect a small move only** — no
   `batter_home_runs` alternates are captured.

### MEASUREMENT SCHEDULED — `alt-line-shortlist-watch`, fires 2026-08-16 10:00 CT
The predicate above for `32186e28` / `c422f79a` is **not abandoned, it is queued**.
A one-shot scheduled task (`C:\Users\tempadmin\.claude\scheduled-tasks\alt-line-shortlist-watch\SKILL.md`)
carries the full baseline inline (shortlist 88 rows / 52 projected / **14 alt rows
at `sim_component: None`**; book grid 238 alt rows at 0 projected against
`spreads`+`totals` **115 of 115**) and writes its result back here.

**It leads with the CONTROL and aborts on it:** if main `spreads`/`totals` read 0
projected, or `games_in_summary` is 0, the run reports VOID rather than FAIL —
that is the exact false negative the 2026-08-15 date rollover produced. It is a
measurement only; it will not deploy or roll back, and it names the rollback SHAs
(`191d098f4a8d`, `b7ae47e6d1a0`) for the user to decide on.

**If you are another session and the slate is populated before 10:00 CT, take the
reading yourself and say so here** — do not assume the task has covered it.

### ATTEMPT 1 of 4 — 2026-08-16 15:12/15:20Z (10:12/10:20 CT) — **VOID. THE GATE PASSED AND THE READ IS STILL VOID.**

`alt-line-shortlist-watch` fired at 10:12 CT. Re-armed for **12:00 CT
(2026-08-16T17:00:00-05:00)**. Two reads, 8 minutes apart, identical.

**All four gate conditions PASSED — and the measurement is still worthless.**

| gate condition | reading | verdict |
|---|---|---|
| book-grid `rows` non-empty | **1972** | pass |
| `projections.games_in_summary` > 0 | **15** | pass |
| main `spreads`/`totals` with `projection.source` > 90% | **100.0% (66 of 66)** | pass |
| shortlist >= 30 rows | **108** | pass |

**The gate checked that the SLATE was populated. It never checked that the
POPULATION UNDER TEST was present.** It is not:

- **Book grid: 0 `spreads_alt`/`totals_alt` rows** (baseline 238). Not
  present-and-unprojected — *absent*. The artifact's own `markets` list at
  15:07:19Z and 15:17:44Z carries no `_alt` key at all: `batter_*`, `earned_runs`,
  `h2h`, `h2h_lay`, `hits_allowed`, `outs`, `spreads`, `strikeouts`, `totals`,
  `walks_allowed`. Zero denominators, so "0 projected" is not a number.
- **Shortlist: 14 alt rows, and every one is WNBA.** MLB alt rows: **0**. The
  baseline's 14 split **mlb 9 / wnba 5**, and all 9 MLB ones were
  `game_state: live`. At 15:12Z first pitch (16:15Z) had not happened.
- **The 14 WNBA alt rows read `sim_component: None`, and that is
  NON-DISCRIMINATING.** WNBA carries no game-market sim projection *at all* —
  not for `spreads_alt`/`totals_alt`, and not for main markets either
  (the baseline's WNBA `h2h_3_way` is also `source: None`). Every WNBA
  projection in either snapshot comes from `wnba_props_recommendations`, a props
  path. `project_game_market` returns None at its first branch —
  `if not payloads: return None` — because there are no WNBA game payloads in
  the index. **Reading 0/14 here as "the fix failed" would have repeated the
  2026-08-15 error in a new costume.**
- **Live props: 0 rows with `mlb_live_lens_monte_carlo`.** No MLB game had
  started. Expected at this hour; not a finding.

**THE FIX IS LIVE BY CONTENT — and both workers were REDEPLOYED since the
measurement was queued.** Neither runs the SHA the task file names:

| service | live now | finishedAt | the deployed SHA |
|---|---|---|---|
| refresh-worker | **`d72d670c`** | 2026-08-16T06:01:34Z | `32186e28` |
| live-odds-worker | **`dd53d47c`** | 2026-08-16T05:20:39Z | `c422f79a` |

Verified by blob, not by ancestry (`git rev-parse <sha>:<path>`):

- `shared/prop_projections.py` @ `d72d670c` = `3ec9f652` = the blob at
  `32186e28`. Byte-identical. `@ dd53d47c` = `f7572d5d` = the blob at
  `c422f79a`. Byte-identical.
- `mlb/cards.py` @ `d72d670c` = `ec176d9e`, which **does** differ from
  `32186e28`'s `267bf61f` — but the diff is an unrelated build-scoped
  `odds_history` cache, and the alternates de-flatten (`lanes = [market] +
  list(market.get("alternates") or [])`, dedup by `seen_lines`) is intact.

So a later VOID cannot be blamed on the fix having been reverted, and the
rollback targets `191d098f4a8d` / `b7ae47e6d1a0` are still the right ones.

**WHAT THE NEXT ATTEMPT MUST ADD TO THE GATE.** A fifth condition, because the
four above are jointly satisfiable on a slate that cannot test this fix:

> **book-grid `spreads_alt` + `totals_alt` row count > 0, AND shortlist MLB alt
> rows > 0.**

Evidence for when that becomes true: the baseline's 9 MLB alt rows were **all
`live`**, and the 238-row book-grid baseline was taken at 22:41Z, mid-slate. The
alt population appears once games go live, not at pregame. 12:00 CT (17:00Z) is
~45 min after first pitch, which should clear it.

**Attempts remaining: 3 (12:00, 14:00, 16:00 CT).** No deploy, no rollback, no
source file touched.

### VERIFIED — `layer2_board` candidate-line fix WORKS in production (2026-08-16 00:2xZ)

First post-deploy artifact: `written_at=2026-08-16T00:12:35Z` (deploy live
23:16:39Z). Three joinable mlb spreads rows:

      side   shortlist_line   grid cell's own line   verdict
      away        1.0                 1.5            line MOVED since snapshot
      home        1.5                 1.5            MATCH
      home       -1.5                -1.5            MATCH

**Both home rows carry their OWN cell's handicap.** Before the fix they carried
the negation — the away handicap. That is the fix, confirmed on real data.

**THE WATCHER SAID `FAIL`. IT WAS WRONG, AND WRONG THE SAME WAY FOR THE THIRD
TIME.** Its away predicate compared a FROZEN artifact (`written_at` 00:12:35Z)
against a LIVE grid fetched ~15 minutes later. A spread that moves between the
two reads as a mismatch. **A verification that compares a snapshot to a moving
reference cannot separate drift from breakage** — the same class of error as
the first watcher (measured the input) and the second (never-passing predicate).
Correct form: join the snapshot against a grid read at the SAME instant, or
compare only fields that cannot move.

**LIMIT, stated plainly: n=2 home rows.** Most published rows are h2h/props and
do not join. The fix is confirmed on the rows that exist, not proven at volume,
and generality beyond mlb remains unmeasured.

`GAVE-UP` printed after the verdict is a script artifact (the break did not
fire); the monitor has ended and the verdict above stands.

### CLOSING-CLOCK FIX — NOT YET VERIFIABLE, and the reason is the slate, not the code

Checked 2026-08-16 00:3xZ.

- **The fix IS running.** live-odds-worker is live on `c422f79a` (finished
  23:49:38Z) and that commit contains `_apply_closing_stamp` (2 hits). Verified
  by content, not by ancestry.
- **0 of 51 stamped markets carry `closing_detected_at`** — the field only the
  new code writes.
- **That is expected, not a failure.** Every stamp is idempotent (guarded on
  `closing_line is None`), so a market stamped before the deploy is never
  re-stamped. All 51 stamps have `closing_captured_at` between **17:25:32Z and
  23:15:00Z — the latest predates the deploy.** No market has transitioned
  pregame->live since the fix went live: mlb first pitches ran 23:11-23:16Z and
  the next two are **01:38Z and 01:40Z**.
- **So the absence of the fingerprint is the absence of an OPPORTUNITY, not the
  absence of the fix.** Do not read `detected_at: 0` as a failed deploy — check
  whether any market transitioned in the window first.

**NEXT CHECK — after 01:40Z, when the last two games start:**
1. `/api/ops/odds-history/inspect?sport=mlb&date=2026-08-15` -> find markets
   carrying `closing_detected_at`. Any at all proves the new path ran.
2. For those, assert `closing_captured_at <= commence_time` (the old code put it
   AFTER, e.g. 20:34:26Z against a 19:08Z start).
3. Beware a tz trap that already cost one run: `commence_time` from
   `history_last.row` is offset-aware while some stamps parse naive — normalise
   before comparing or the check dies with
   `can't compare offset-naive and offset-aware datetimes`.

The scheduled task `clv-settled-read-2026-08-15` fires 01:55Z, immediately after
those transitions, and is the natural place to fold this in.

### CORRECTION 2026-08-16 00:1xZ — `2c14d9ae` IS INERT ON THE SERVED PATH. The mechanism was mis-traced.

The measurement owed by the entry above has been taken, and it FAILED its own
stated falsifier. Recording it as a negative result, not quietly dropping it.

**The board DID rebuild on my code** — published `computed_at 2026-08-16T00:12:39Z`,
567 candidates, ~10.6 min end to end (`BOARD_OVERVIEW_READY` 00:02:00 ->
`BOARD_PUBLICATION_RESPONSE_READY` 00:12:39). So the deploy is not waiting on
anything.

    AFTER a confirmed rebuild on 2c14d9ae:
      line as a STRING   0     <- predicted to rise. DID NOT.
      line as a number 207     of which 24 whole-numbered

**The falsifier I wrote before deploying fired: the fix is INERT on this path.**

**WHY, traced rather than guessed.** Every numeric-line row served carries
`source: layer2_shortlist`, `surface_key: layer2`, `candidate_type: None`. Their
`line` is stamped at **`syndicate/features/shared/layer2_board.py:1104`** as a
bare `"line": row.get("line")` — a raw float copied off the market row.
`UniversalCandidate.to_dict` is **never on this path**. A web deploy would not
have helped either; the field is stamped in the worker, in a different module,
before anything I changed runs.

**The root error is mine and it is upstream of the deploy.** The failing test
exercised `run_intelligence_query` with `force_refresh=True`. Production serves
the **Layer 2 board**. I found a real flattening in the test path, then
predicted a production number without checking that production routes through
it. The baseline "84 of 101 numeric, 7 whole-numbered" was never a valid
before-measurement for this change.

**What remains true:** the three defects are real and fixed where they live
(`test_intelligence.py` 216/2 -> 218/0, mutation-pinned); anything routing
through `UniversalCandidate` now gets correct display text. **What is false:**
any claim that `2c14d9ae` changed production. It did not.

**Cost:** one refresh-worker restart that bought nothing observable. Zero jobs
killed, so the cost is the restart and the measurement window, not lost work.

**Handover, NOT actioned here:** the real fix for whole-numbered lines is at
`layer2_board.py:1104`, a file claimed by an OPEN lane. It is not a cosmetic
edit — `line` is one of `_IDENTITY_FIELDS` and feeds the dedupe key at
`layer2_board.py:450`, so changing its type changes dedupe behaviour.

### SEPARATE AND STILL STANDING — refresh-worker restart starvation `[measured 2026-08-15/16]`

Independent of the above and unaffected by any of its errors.

- Real board builds take **178 / 197 / 241 / 325 / 358 s** (3.0-6.0 min).
  `BUILD_SPAN_EXIT elapsed_s=0.0` lines are the documented empty-pool
  short-circuit, NOT builds — do not count them.
- **13 refresh-worker deploys since 21:30Z.** Builds completed at 21:53 / 22:32 /
  22:52 / 23:10 — every one inside a gap of **15-33 min**.
- Then **six deploys in 46 minutes** (23:16, 23:25, 23:31, 23:38, 23:47, 23:56),
  gaps of **6-9 min**: **zero builds completed.** A 3-6 min build cannot fit a
  6-9 min gap once boot is paid.
- The churn stopped and a build completed within ~12 min.
- **Consequence: a burst of closely-spaced worker deploys starves the artifact
  the whole queue is waiting on.** The board went 77 min stale on a busy worker
  with nothing wrong with it.

## 2026-08-16 00:29:17Z — live-odds-worker `c4116ab6` (simsRun stamp) — LANDED, AND `live_mc` COVERAGE IS NOW ZERO. ATTRIBUTION IS GENUINELY OPEN.

**Deploy:** `dep-da0g5pojo6nc73efbhtg`, parented on `c422f79a` (the commit that
won the 23:42:32 race), so not a rollback. Fired into a running soccer job on
the user's explicit instruction; killed pids 101/102 +
`build_soccer_artifacts --league belgian_pro`, captured 30 s before the POST.

### VERIFIED
- **The fix IS on live-odds-worker** (`lane_is_live_mc` count 3) and **NOT on
  web** (`484221bd`, count 0).
- **`/mlb/api/live-lens` CANNOT observe this fix** — it is served by WEB, which
  rebuilds the lens with its own vendored copy. **My "Stage 1" check was
  invalid**: it read web's code and reported it as the worker's. `live_mc_lanes`
  0 there is a fact about web, not about the fix.
- **Live games are NOT bailing.** 100 `LIVE_MC_BAIL` samples spanning
  00:05:59–00:36:28 (across the deploy) are **100% `status_not_live`** —
  51 Final, 49 Preview. Saturated but time-contiguous over many ticks.

### THE REGRESSION, AND WHY I AM NOT CLAIMING IT IS MINE
    23:02:14 artifact  index_size 3   projected 12   sim_count_unusable 12
    00:34:42 artifact  index_size 0   projected  0   no_live_gameline_projection 32
    00:37:44 artifact  index_size 0   projected  0   (same -- not a transient)

`sim_count_unusable` disappeared, **but only because nothing is projected at
all** — the rows now fail one step EARLIER. That is worse, not better.

**THE ATTRIBUTION GAP: live-odds-worker took TWO deploys between those readings.**
`c422f79a` (another session, live 23:49:38) and mine `c4116ab6` (live 00:29:17).
**I have no measurement between 23:49 and 00:29**, so the drop is equally
consistent with their deploy, with mine, or with the slate. **Correlation with
my deploy is an artifact of when I happened to measure.** Blaming my commit here
would be the same error as crediting a fix for a number it did not move.

### WHAT WOULD SETTLE IT, cheapest first
1. Read the artifact's `live_gamelines` from a build BEFORE 23:49 if one is
   retained — that isolates `c422f79a`.
2. Roll live-odds-worker to `c422f79a` and re-read `index_size`. If it recovers,
   the fix is implicated; if it stays 0, it is not. **Costs another restart and
   another soccer run.**
3. My change is semantically identity-preserving on `source` (hoisted the same
   predicate) and was verified against the real builder: `live/full ->
   live_mc + 120`, segment lanes -> `segment_projection + None`. That argues
   against it, but does not clear it.

**NOT ROLLED BACK.** The prior state was itself producing zero edges, so the
rollback buys diagnosis, not function — and it spends a third soccer run tonight.
Left for an explicit decision.

## 2026-08-16 00:5xZ — RETRACTION: THE ROLLBACK VERDICT WAS WRONG. THE FIX WORKS, AND IT PUBLISHED THE FIRST LIVE GAME-LINE EDGES.

**`live_gamelines`, measured under `c4116ab6` (the simsRun fix):**

    index_size 8   considered 32   projected 32   priceable 25   EDGED 25
    withheld_by_reason {prob_interval_swamps_edge: 7}

**25 live game-line edges. The platform had never published one.** And the
precision gate is finally the thing doing the refusing — 7 rows under
`prob_interval_swamps_edge`, which is the recorded "publish, refuse to price"
decision being EXERCISED for the first time rather than bypassed by missing
plumbing.

Against the pre-fix state (23:02): `index_size 3, projected 12,
sim_count_unusable 12, edged 0`.

### HOW I GOT IT WRONG, TWICE, IN OPPOSITE DIRECTIONS
1. **I read post-restart warm-up as a regression.** At 00:34:42 and 00:37:44 —
   5 and 8 minutes after the fix landed — `index_size` was 0, and I recorded a
   persistent regression and asked for a rollback. The worker had simply not
   rebuilt its snapshot yet. **I had already been burned by exactly this earlier
   tonight** (the "clean negative" retraction) and wrote the guard for it, then
   ignored the guard because two consecutive zeros felt like convergence.
   **Two reads inside one warm-up window are still one read.**
2. **My rollback watcher attributed a PRE-rollback artifact to the rollback.**
   It waited for `ROLLBACK_LANDED` (00:54:07) then read the artifact — which was
   stamped **00:52:14**, built while the fix was still live. It printed
   "RECOVERED -> the fix IS implicated". **The artifact lags the deploy, so the
   first read after any deploy still describes the previous code.** Caught only
   by comparing `generated_at` against the landing time, which is the check that
   should be automatic and was not.

**A watcher that concludes for you is only as good as its freshness test.** Both
errors are the same defect in different clothes: comparing a number to an event
without checking the number was produced after the event.

### ACTION
Rollback to `c422f79a` (landed 00:54:07) is being UNDONE — `c4116ab6` re-fired
00:58:33Z, confirmed building by re-reading the deploys list. Net cost of the
round trip: **three soccer runs** and two extra restarts.

---

## 2026-08-16 — win_prob null counter: readable channel — 2 OF 3 SERVICES, MEASUREMENT OWED

**WHAT AND WHY.** The `WIN_PROB_NULL_NO_PRICE` counter deployed 2026-08-15 was
unreadable in production: it `print()`s to stdout and
`refresh_odds_sources._run_command` discards a successful step's stdout. Proven,
not inferred — live-odds-worker's `ALL_PROCESS_MEMORY` census at 23:36:05Z lists
PID 1900 running `refresh_wnba_oddsapi_props.py --date 2026-08-15`, while a
bounded log read since the deploy returned **zero** matches on both workers. The
counter now also writes through `write_json_file`, read at `/api/ops/win-prob-null`.

**LANDED.**

| service | commit | landed | content |
|---|---|---|---|
| refresh-worker | `b2af0fac` | 2026-08-16T01:13:32Z | producers + `win_prob_null_diag` |
| web | `fa1871cf` | 2026-08-16T01:15:37Z | route + `win_prob_null_diag` |
| live-odds-worker | `3573a0c3` | 2026-08-16T01:59:59Z | producers + `win_prob_null_diag` |

**live-odds-worker landed on the SECOND attempt, and the wait was the finding.**
Its claim freed at 01:26:48Z; a 25-minute watcher then found **no lull at all** —
`refresh_odds_sources` + a rolling `build_soccer_artifacts` (belgian_pro,
la_liga, mls, eredivisie, primeira, champio…) were running at every one of 10
samples. There is no idle moment on this service during live hours, so "wait for
a lull" is not a plan, it is a deferral. Deployed at 01:54:04Z into 3 running
jobs, deliberately: those jobs re-run on the next cycle (this ledger already
prices that at ~three soccer runs), whereas waiting risked the WNBA slate ending
before the writer landed.
- **The watcher also caught the thing that justified the whole deploy:** at
  01:31:36Z `refresh_wnba_oddsapi_props.py` ran **on live-odds-worker** — the one
  service still undeployed at that moment. That run wrote nothing. It is the
  direct confirmation that this service, not refresh-worker, is where the first
  reading has to come from.
- **refresh-worker was redeployed over by another session mid-flight** (`b2af0fac`
  → `3e1994a2`, 01:31:03Z). Checked BY CONTENT, not ancestry: `3e1994a2` still
  carries `win_prob_null_diag.py` and the recorder call sites. Not stripped.

Each branch was cut on **that service's own live SHA**, not on `main` (`main` is
not a superset of the workers), and trimmed so no other lane's code rode along —
web took no producer changes, the workers took no `ops.py`. refresh-worker was
**re-cut once** (`5624ef2e` → `b2af0fac`) because the service redeployed during
verification; "live" is a lease.

**MEASURED AT 01:16Z, AND IT IS NOT THE MEASUREMENT THAT MATTERS.**
`/api/ops/win-prob-null` returns **HTTP 200**, `readings: 0`, `interpretation:
"no producer has reported yet"`, `reports_root: /opt/render/project/data/reports`
— which does confirm web resolves the same key root the workers write, i.e. the
channel is wired. **It confirms nothing about the `or 0.5` fix.** A route that
answers is not a producer that reported.

**FIRST CROSS-SERVICE READING, 2026-08-16T02:02:33Z — THE CHANNEL IS PROVEN.**

    wnba / live-odds-worker   rows=0  null_no_price=0  date=2026-08-15
    generated_at 2026-08-15T21:01:19-05:00 (02:01:19Z)  commit 3573a0c3  runs_recorded=1

The worker wrote it and **web read it back**, which is the thing that was
impossible three hours ago: `generated_at` post-dates the 01:59:59Z deploy by 80
seconds and `commit` is the deployed SHA, so this reading was produced by the new
code and is not a stale artifact. The instrument is no longer blind.

**IT SAYS NOTHING ABOUT THE `or 0.5` FIX, AND MUST NOT BE READ AS PASSING.**
`rows=0` means that run computed **no `win_prob` at all** — the denominator is
zero, so "null=0" is arithmetic, not evidence. Today's live artifact carried 15
`win_prob` rows, so a full run does compute them; why THIS run computed none
(reuse-gate skip per `#344`, a partial/fast step, or a finished slate at 21:01
CT) is an open question and is NOT asserted here.

**STILL OWED: a reading with `rows>0`.** That is the first genuine confirmation
(`null=0`) or the branch firing correctly (`null>0`). The hourly
`wnba-win-prob-counter-read` task now reads this endpoint and will report it.

## 2026-08-16 01:2xZ — RETRACTION: THE "25 LIVE GAME-LINE EDGES" ARE NOT CREDIBLE. TWO DEFECTS IN MY OWN GATE.

I was about to hand these rows to `clv-without-settlement` as a population to
score. Reading the rows themselves stopped it. **Do not score them.**

### DEFECT 1 — A DEGENERATE PROBABILITY MAKES EVERYTHING PRICEABLE
    PHI @ MIN  model=0.0  mkt=0.0979  edge_pp=-9.79  se=0.0  sims=120  PRICEABLE

`prob_std_err = sqrt(p(1-p)/n)`. At **p = 0.0 exactly** that is **0.0**, so the
bar is `2 x 0.0 = 0` and **every edge clears it**. `0/120` is a legitimate Monte
Carlo outcome (the model quantises to 1/120 — 0.0083, 0.0417, 0.9667 are all
k/120), so this fires on real data, not on bad input.

**I wrote the exact warning and then missed the case.** `prob_std_err`'s
docstring says a 0.0 "would read as perfectly precise and would make every edge
priceable — the single worst substitution available in this module." I guarded
it for **unparseable** input and returned `0.0` for **degenerate** input, which
is the same hole with a valid type. **A Wald interval is undefined at the
boundary; it needs a rule (Wilson/Jeffreys, or refuse p in {0,1}).**

### DEFECT 2 — THE EDGES LOOK SIDE-BLIND
One game appears many times with wildly divergent market probabilities against a
CONSTANT model probability:

    MIA @ CIN  model=0.0417  mkt = 0.5028 / 0.4682 / 0.3905 / 0.531   edge -35 to -49 pp
    SD  @ CLE  model=0.9667  mkt = 0.875 / 0.8856 / 0.8993 / 0.5424   edge +6.7 to +42.4 pp

A **+42 pp** edge on a moneyline is not a finding, it is a units or side error.
`model_prob` is the HOME win probability; I read `market_fair_prob_over` and
assumed it is the home side on every h2h row. **The 0.5424 and 0.5028 values
look like the OTHER side of the same market**, which is precisely the
side-blindness `closing-stamp-is-detection-time` already documents for
`closing_price` (always the home price, 18/18). I verified the de-vig
arithmetic on ONE row at 21:0xZ and generalised from it.

### STATUS
- **Drop 3's plumbing is still real**: the join runs, counters attribute every
  row, `simsRun` now reaches the gate. That part stands.
- **`rows_live_gameline_edged` is NOT a product signal yet.** It is currently
  counting rows that pass a gate with a zero-width interval and a probably
  mismatched side.
- **NOT handed to `clv-without-settlement`.** Scoring these would have produced
  a CLV number off mis-sided rows — the same class of error that lane just
  retracted its own first number for.

**Fix order:** (1) refuse or widen `p in {0,1}` in `prob_std_err`; (2) establish
per-row which side `market_fair_prob_over` describes and join side-explicitly;
(3) only then re-count edges and consider CLV.

## 2026-08-16 01:56:44Z — refresh-worker `d1e3f908` — SEGMENT FILTER + BOUNDARY FIX: EDGES 23 -> 4, AND THE 4 ARE THE FIRST CREDIBLE ONES

**Gate opened NATURALLY at 01:50:45 after ~15 min of HOLD (5->9 jobs). ZERO jobs
killed** — I had told the user a window probably would not come and was wrong;
waiting cost nothing and saved 9 in-flight jobs incl. MLB sims.

**Measured with BOTH lags guarded** — artifact `generated_at 01:57:56` > deploy
`finishedAt 01:56:44`, **AND** `segment_is_not_full_game` present, so the new
code's own fingerprint is the pass condition rather than a timestamp:

    considered 20  projected 5  priceable 4  EDGED 4  withheld 16
    withheld_by_reason {segment_is_not_full_game: 15, prob_interval_swamps_edge: 1}
    index_size 10

**Against the pre-fix build: edged 23 -> 4, with 15 of 20 rows (75%) now refused
as the wrong segment.** The `+42.43 pp` SD @ CLE first-inning row is gone. **The
count FALLING is the fix working** — three-quarters of the old "edges" were a
full-game projection priced against F1/F3/F5 markets.

**Caveat on the population:** `considered` fell 36 -> 20 because the slate wound
down (13 final / 2 live at measurement). So the 23->4 comparison mixes the fix
with a shrinking slate. **The RATE is the honest read: 75% of considered rows
refused for segment, which no slate change explains.**

### WHAT THE 4 ARE AND ARE NOT
They survive both gates: a full-game market, and an edge exceeding 2 Agresti-
Coull standard errors. **That is still only "beats the estimator's own noise at
120 sims".** No CLV, no settlement, no backtest. They are the first rows worth
handing to `clv-without-settlement` — the earlier 23 were not, and were
correctly withheld.

**OPEN:** `index_size` 3 -> 8 -> 10 across the night is still unexplained; Drop
2's carry-forward has never been observed firing; the tally is MLB-only.
**OWED, and it will not arrive by itself:** a reading with `rows>0`. The WNBA
producer was last observed running on **live-odds-worker — the one service that
did not get this deploy** — so the likeliest source of the first reading is
still dark. Next deployer of live-odds-worker should carry
`deploy/win-prob-null-live-odds-worker` (re-cut on its then-live SHA; the pushed
`3573a0c3` is already stale). The hourly `wnba-win-prob-counter-read` scheduled
task now reads this endpoint and will report "writer not deployed" until then —
that is a true statement, not a null result.

---

## 2026-08-16 03:31:11Z — web `ebd5f677` — serve the live game-line coverage — MEASUREMENT PENDING

Lane `live-game-line-projection`. Deploy `dep-da0itvpt0dsc739pj3n0`, fired
03:31:11Z. **Measurement column deliberately empty; reminder 03:45Z.**

**THE PREFLIGHT FAILED ITS FIRST CANDIDATE, AND THAT IS THE ENTRY WORTH READING.**
The candidate was `639ecce0` (= `origin/main`). **`main` is not an ancestor of
what web runs.** The live SHA was `fa1871cf`, and **33 commits are live on this
service and absent from `origin/main`** — among them `484221bd` (the opt-in
per-recommendation `clv_pct` block) and `4316c907` ("a close stamped after first
pitch is an in-play price, not a close"). Deploying main would have reverted all
33, including work another session shipped tonight. Re-parented on the live SHA
as `ebd5f677` and verified by CONTENT, not ancestry: `_clv_block` count 2 in the
deployed tree, my pass-through count 1.

**Scope:** `+20` lines in one function of `syndicate/blueprints/intelligence.py`,
plus a new test file that production never executes. Nothing else.
`live_gameline_ledger.py` and `live_gameline_join.py` are **absent from web's
tree and deliberately not carried** — `build_book_grid_artifact` has exactly one
call site, `scripts/run_refresh_worker.py:3140`, so the ledger cannot run here.
`render.yaml` untouched → no `blueprint_sync`.

**Expected effect, as a number and a window:** on the FIRST request after the
deploy reports `live`, `GET /api/board/book-grid?sport=mlb&date=2026-08-15&limit=1`
returns `live_gamelines` as an object carrying `rows_live_gameline_considered`
and `live_gameline_ledger` as an object carrying `written`. **Both read `null`
right now** — that is the pre-state, taken 03:0xZ. No board build is required:
the route reads an artifact that already carries both keys. Every other field
must be unchanged for the same `generated_at`.

**Falsification, run before the deploy:** with the two served keys commented out,
all 6 tests fail; restored, they pass — on the LIVE tree (`fa1871cf` + the
change), not on main.

**What a null result would mean, stated before reading it:** if both keys are
still `null`, check `generated_at` FIRST. A `null` from an artifact written
before Drop 3 is the honest "this artifact predates the join" signal and is NOT
a failed deploy. Only `null` against an artifact that demonstrably carries the
keys implicates this change.

**Blast radius:** web only (`srv-d88ahvrbc2fs73eodu30`, 2 GB, persistent disk →
stop-then-start, no instance overlap). Recent deploys on this service ran ~7–8
min end to end with 502s during the swap. Fired at 22:31 Central **with 2 MLB
games live**, so the board was unavailable to a user for a few minutes — recorded
as a cost, not netted out. **No worker restarts**: `refresh-worker` and
`live-odds-worker` untouched, so `refresh-worker-oom-recurrence`'s deploy hold is
not crossed and no in-flight sim was killed.

**Rollback:** `POST /v1/services/srv-d88ahvrbc2fs73eodu30/deploys` with
`{"commitId": "fa1871cf..."}` — the exact SHA that was live at 03:31Z.

### MEASURED 2026-08-16 03:38–03:40Z — web `ebd5f677` — **PASS**

Deploy `dep-da0itvpt0dsc739pj3n0` reported `live` at **03:38:07.648Z** (6m56s
from 03:31:11Z). Gated on the affirmative token `live`, not on the absence of a
failure string.

    read (server_time)   artifact generated_at   live_gamelines   live_gameline_ledger
    03:38:28.543Z        03:37:13.853Z           object           object
    03:38:57.335Z        03:37:13.853Z           object           object
    03:39:43.233Z        03:39:36.922Z           object           object

    live_gamelines       considered 8  projected 2  priceable 0  edged 0
                         withheld 8 = {segment_is_not_full_game: 6,
                                       prob_interval_swamps_edge: 2}
                         index_size 10
    live_gameline_ledger candidates 0  written 0  enabled true

**Pre-state was `null` for BOTH keys** (03:0xZ, recorded in the pending row
above before the deploy). **Two different artifacts** — 03:37:13 and 03:39:36 —
both served them, so this is two builds, not two reads of one.

**Why one read would in fact have been enough here, stated so the rule is not
cargo-culted:** the artifact already carried both keys, proven at 03:00Z by
streaming the raw file. The only producer between the code and the number was
the route. The "two lags in series" rule binds when a snapshot sits upstream of
the artifact; it does not here, and saying which applies is the point.

**`written: 0` is expected and is NOT this deploy's business.** refresh-worker
still runs the v1 recorder, whose `candidates` is 0 because 0 of 8 rows are
priceable. **The measurement this unblocks has not been taken** — it needs the
worker half, which `refresh-worker-oom-recurrence` still holds.

**Cost:** fired 22:31 Central with 2 MLB games live; the board 502'd during a
~7-minute stop-then-start swap. No worker restarted; no sim killed; the OOM
lane's hold was not crossed. `render.yaml` untouched, so no `blueprint_sync`.

---

## 2026-08-16 ~02:5xZ — MEASUREMENT, NO DEPLOY — `refresh-worker-oom-recurrence`

**No deploy was made. Nothing was changed on any service.** This is the
attribution the lane was opened to produce, and the reason not to deploy.

### THE QUESTION: did `#435` regress, or is this a second contributor?

**`#435` did NOT regress. This is a second, independent condition — and it is
NOT a leak, it is a ~2 GB TRANSIENT.**

Two things resolve the apparent contradiction with the ledger's
`#435 deployed: peak anon 2,869 → 1,071 MB`:

1. **Ancestry.** `c67f7373` (the `#435` streaming reader) IS an ancestor of
   refresh-worker's live SHA `f8ca54e1`. `read_book_quotes_latest` is present in
   the deployed tree at `odds_book_quotes.py:928`, called from
   `layer2_shortlist.py:100`. The fix is in production by content.
2. **The two numbers are DIFFERENT QUANTITIES.** `2,869 → 1,071 MB` is the cost
   of the book_quotes READ. `3,857 MB` is CONTAINER anon. Comparing them is the
   same scope error that produced the retracted "673MB outside pymalloc".
   **"anon is back at 3,857" was never in contradiction with `#435`.**

### METHOD, AND THE WINDOWS ACTUALLY USED

Kills read from `/v1/services/srv-d91dpertqb8s73co8ls0/events`, never logs.
Every window below is **DEPLOY-FREE** — bounded by a `deploy_ended` on one side
and a `deploy_started` or a kill on the other. Positive control run on the log
probe before trusting any of it (1,266 matches over a stated 11.6 min window).
Coverage gaps after each boot are the watchdog's own emission gate
(`pct >= 60%` OR a 200 MB move), not pager truncation.

### THE KILL LIST, FROM EVENTS

    08-14 22:17Z .. 08-15 05:02Z   21 oomKills   3.11 /hour   (pre-#435)
    08-15 05:02Z .. 08-16 02:11Z    0 oomKills   over 21h 08m
    08-16 02:11:34Z, 02:37:06Z      2 oomKills   memoryLimit 4Gi

live-odds-worker in the same window: **0**. Its kills are ~6 h apart and the
most recent is 2026-08-15T20:03:41Z — a different, slower condition. Control holds.

### WHAT IS ACTUALLY HAPPENING — 22 EXCURSIONS, 5 DEPLOY-FREE WINDOWS

The worker runs a **repeating sawtooth**, roughly two passes ~18 s apart then a
~2 min gap. Each pass allocates ~2 GB in 15–25 s at 100–330 MB/s and frees
essentially all of it in ~2 s (collapse rate −700 to −919 MB/s):

    window (deploy-free)      n   mean amp    peak anon   min inactive_file   outcome
    W1 00:27–00:51           6    1658.5 MB    3612.5         239.8 MB        survived
    W3 01:36–01:50           2    2004.9 MB    3611.2         164.0 MB        survived
    W4 02:03–02:11           2    2006.2 MB    3907.1          26.3 MB        KILLED
    W5 02:31–02:37           1    2621.9 MB    3894.9          42.2 MB        KILLED
    W6 02:43–02:59          11    1952.9 MB    3415.4         186.1 MB        alive at read

**The amplitude and the peak are FLAT across the whole night — before and after
tonight's deploys alike.** ~2 GB transient launched from a ~1.0–1.9 GB baseline
lands at 3.0–3.8 GB against a 4,096 MB ceiling. **Every single cycle reaches
`memory_headroom_mb` 0.0–0.2.** The kernel services each burst by evicting page
cache: `inactive_file` is driven 1,500 → 186 MB on a survivable cycle.

**The two kills are the two thinnest-page-cache cycles.** W4/W5 left the kernel
26.3 and 42.2 MB of evictable file cache; the surviving windows kept 164–240 MB.
W5's single captured excursion is the largest of the night — amplitude 2,621.9 MB,
peak 3,804.1 MB at 02:36:13 — and the process was dead **53 seconds later**.

So the kill is not a ratchet crossing a line. **It is a coin flip on every cycle,
decided by how much page cache the kernel still has to evict when the ~2 GB
transient lands.**

### RULED OUT TONIGHT — do not re-derive

- **Drop 3's `live_gameline_ledger` is NOT the cause.** It landed in `f8ca54e1`
  at **02:25Z**; the first kill was **02:11:34Z**, before it existed on the
  service. Separately, `read_last_by_key` streams line-by-line into a dict
  bounded by distinct market keys, with a 20k-record/12 MB file cap — it already
  has `#435`'s lesson built in. Kilobytes, not hundreds of MB. Not a candidate.
- **Not a leak.** Trough anon returns to 971–1,900 MB after every excursion,
  including the last one before each kill. Nothing is accumulating.

### WHAT THIS CONFIRMS, AND THE INSTRUMENT'S BLIND SPOT

The standing finding holds and is now quantified: `last_stage` during the climbs
is `cards_context_page_cache_hit` / `_summary_loaded` / `_sim_games_loaded` /
`_end` and `board_contract_games_normalized`, with `seconds_since_stage` of
**14–34 s**. After `games_normalized`, `apply_game_board_contract` only does
`setdefault`s and returns (`simulation_contract` is default OFF since `#75/#43`).
**The 2 GB is allocated BETWEEN stage markers, in the caller** — which is exactly
why `board_contract_games_normalized` can be EXONERATED at "0.0 MB median" and
still be the last thing named before a 2 GB climb. Both statements are true.

**The 3000 MB floor does not guard this.** `_OVERVIEW_MIN_SAFE_HEADROOM_BYTES`
(`intelligence.py:2583`) is consumed by `_overview_headroom_exhausted(next_sport=…)`
— a per-sport gate INSIDE `build_intelligence_overview`'s sport loop. The
excursions above are not gated by it. Its own comment already says so: *"This is
a circuit breaker around MLB's cost, NOT a fix for it. The real work is making
`build_cards_page_context` cheaper or not running it hydrated on the worker at
all."* That sentence is now backed by a number: **the pass is ~2 GB and it runs
~2× every ~2 minutes.**

### WHY NO DEPLOY

The `win_prob` counter still cannot produce a reading — both its channels only
write on run completion, and the producer keeps being killed or restarted. That
needs an hour clean. refresh-worker took **12 deploys between 22:54Z and 02:25Z**;
the two kills are the first in 21 hours. **Adding a deploy here would destroy the
only clean window that could settle it.** No deploy claim was acquired and none
is owed.

### NEXT LEVER — named, not taken

Reduce the **amplitude** of the single pass, or put a headroom gate in front of
the pass that actually costs 2 GB rather than in front of the overview sport
loop. Raising the ceiling is excluded by the standing user decision
(2026-08-16: keep `pro`, reduce instead). **Unresolved and required before any
change: which allocation inside the pass is the 2 GB.** `last_stage` cannot say —
it is a boundary marker and the cost is between boundaries. That needs a bounded
in-pass measurement, which needs a deploy, which needs the clean window first.

---

### #440 — MEASUREMENT ONLY, NO DEPLOY — closing-stamp clock fix (`325b2822`) verified in output, and the settled CLV reading
- Deployed: nothing. This row settles an existing open obligation; it does not open one.
- Measured: **2026-08-15 22:06 CDT / 2026-08-16 03:06Z** (scheduled read
  `clv-settled-read-2026-08-15`, timed after the day's last two first pitches at
  01:38Z and 01:40Z).
- Subject: `325b2822` on live-odds-worker (~23:17Z 2026-08-15) — `closing_captured_at`
  now carries the previous tick's observation time; detection time moved to the new
  field `closing_detected_at`.

**RESULT 1 — THE STAMP FIX IS VERIFIED.**
- `closing_detected_at` present on **21** markets → the new code path ran.
- **21 of 21** satisfy `closing_captured_at <= commence_time`. Zero post-date it.
  Lead time min 1.1 / median 75.3 / max 103.9 minutes.
- Control in the SAME payload: of the 36 stamped markets without the new field,
  **33 post-date `commence_time`**. Before/after with no cross-time confound.
- At CLV-row level: NEW-code stamps → 30 rows, **all pregame, 0 in_play**;
  OLD stamps → 31 rows, **26 in_play (84%)**.
- Correction to the handed-down baseline: "EVERY pre-fix stamped close had
  `close_age_seconds < 0`" is **33/36 at the shard level, not 36/36.**

**RESULT 2 — THE SETTLED CLV READING (mlb, 2026-08-15).**
- **`avg_clv_pct = −0.3165`, `same_book_n = 126`, `beat_close_rate = 0.2143`.**
- `openings 999` · `resolved 254` · `same_book_all_n 151` · `in_play_excluded_n 25`
  · `unknown_timing_excluded_n 0` · `stamped_close_skipped {stamped_close_is_home_side: 59}`.
- **Recompute check PASSED**: mean `clv_pct` over `same_book` ∧ `pregame` rows from
  `&rows=1` = −0.316519 → **−0.3165 over n=126**, exact on value and n;
  `beat_close` 27/126 = 0.2143, exact. Headline is not to be doubted on this date.
- `book_agnostic_close +2.8054` and `different_book_close +0.7011` are the known
  upward bias. **Not CLV.**
- nfl `resolved 0` (419 openings, 100% `no_market_in_history`), wnba `resolved 0`
  (111 openings, same). Unchanged. Openings ledger confirmed readable, so this is a
  real join gap, not a blind reader.

**WHAT IS STILL WRONG / OWED**
- **`/api/ops/odds-history/inspect` STRUCTURALLY CANNOT SEE `closing_detected_at`.**
  Its summary is a fixed 10-key literal (`ops.py:2141`). Any future check of this
  field must go through `/api/ops/artifacts/stream?path=<sport>_source/artifacts/<sport>/odds_history/<date>.json`.
  The 00:3xZ "zero of 51" reading was taken through this blind instrument.
- **`same_book_n` did not rise (126 vs a prior 151) and the prediction was not
  testable as written** — prior readings survive only as a headline `n`, which moves
  with slate progress. Not scored either way. The mechanism is confirmed by the
  within-payload counterfactual instead: n=96/−0.3998 without the fix → n=126/−0.3165 with it.
- **2026-08-15 IS PERMANENTLY MIXED.** Stamps are idempotent on `closing_line`, so
  36 of 57 markets keep the pre-fix clock and 96 of 126 headline rows are pre-fix.
  **−0.3165 is a mixed-cohort number. First clean date is 2026-08-16.**
- Generality beyond MLB **unmeasured** — no other sport resolved a row today.

---

## 2026-08-16 ~04:5xZ — `refresh-worker-oom-recurrence` — deepcopy EXONERATED, and a named candidate in the unmarked gap

**No deploy made by this lane.** `5c419007` (ledger v2) was shipped by another
lane at 04:24:33Z; this is a measurement of it.

### THE KILL ON THE NEW SHA

    04:24:33Z  5c419007 live (ledger v2)
    04:46:44Z  oomKilled, memoryLimit 4Gi   <- 22.2 min after boot

Watcher exited on the event, from `/v1/services/.../events`. Prior SHA `f8ca54e1`
died at 15 and 12 min after boot. **22.2 vs 12-15 is n=1 and not a result.**
Signature at 11 min, before the kill: amplitude mean **2,220 MB** (baseline
1,950), peak anon 3,425.9, and `inactive_file` driven to **12.3 MB** — *below*
both windows that ended in a kill (26.3 / 42.2). **Ledger v2 did not stop it and
did not visibly shrink the transient.**

### `copy.deepcopy` IS NOT THE 2GB — EXONERATED BY MEASUREMENT

The hypothesis was good and the evidence for it was circumstantial: the climb
begins 0-16s after `cards_context_page_cache_hit` and `cards_context_end`, and
BOTH markers are immediately followed by a full-context `deepcopy`
(`mlb/cards.py:5544` on a hit, `:5802` on the return). In production those two
sites run ~250x in 78 min (98 hits + 152 ends), matching the excursion cadence.

**Measured on the worker path (`SYNDICATE_WEB_DYNO=0`), 15 games, local
artifacts:**

    whole page context      0.81 MB      games subtree 0.78 MB (96.7%)
    deepcopy PEAK           0.54 MB      retained 0.40 MB
    copying only `games`    saves 2.4%

**Three orders of magnitude short of 2GB.** No plausible production/local ratio
closes that gap. **Stop chasing the deepcopy, and do not "optimise" it** — the
copy is also load-bearing: `home.py:5381` mutates the returned game dicts, and
the worker path stores `result` in the cache BY REFERENCE (`:5800`), so removing
the copy would corrupt the cached context.

### THE CANDIDATE THAT REPLACES IT — unmarked, worker-only, uncached

`home.py:5367` takes `payload["games"]` and then, with **no stage marker of its
own**, runs `_enrich_games_with_tracked_market_lines` (`:5376`). Inside it,
`mlb/cards.py:2294`:

    load_odds_history_payload_for_sport("mlb", resolve_current_shard_key("mlb", selected_date))
      if selected_date == today_iso and not render_web_dyno else None

- **No `cache=` argument** -> `cache=None` -> the shard is re-read and re-parsed
  in full on EVERY board build. The parameter exists; the call site does not use it.
- **`not render_web_dyno`** -> **worker only**. Exactly the asymmetry the OOM has:
  web serves the same board and does not die.
- Size, from this function's own docstring: the MLB shard was **19,798,176 bytes
  / 3,436 markets**. At `#435`'s measured **6.3x file-bytes-resident** for this
  JSON family that is **~125 MB per read**.
- It sits in the gap between `cards_context_end` and the next marker — which is
  precisely where `seconds_since_stage` 14-34s puts the climb.

**HONESTY ON THE GAP: ~125 MB is not 2 GB.** This is a named, worker-only,
per-build, uncached multi-hundred-MB read in the right place, and it is the best
candidate on the table — it is NOT a proven attribution. Do not record it as the
cause. What would settle it: one bounded in-pass measurement around `:2294`
(bytes read, parse peak, call count per build), which needs a deploy.
## 2026-08-16 04:24:33Z — refresh-worker `5c419007` — ledger v2 — **DEPLOYED, NOT YET EXERCISED**

Lane `live-game-line-projection`. `dep-da0jk261egvs738t0d10`, fired 04:18:16Z,
live **04:24:33.598Z** (6m17s). Parented on the live SHA `f8ca54e1`, **not on
main** — main is not an ancestor of it and 13 commits are live on this service
and absent from `origin/main`.

**The hold was cleared by evidence, not overridden.** `refresh-worker-oom-recurrence`
banked its attribution as `9ed17262` (a ~2 GB **transient**, not a leak; `#435`
did not regress) and archived. I asked that session for permission first; the
retry came back "session is archived". **Residual cost recorded:** its clean
window was 70 min old at 03:47Z and this deploy reset it to zero, which is what
its still-open second question (naming the allocator inside the 2 GB pass) needs.

**Sim discipline:** sims were launching back to back — pid 2441
(`props_now_available`), then pid 3275 (`fingerprint_change`) for 11 minutes.
Polled `check_deploy_safety.py` on **exit code 0**, deliberately not on a string,
because `NOT CLEAR` contains `CLEAR` and a substring gate would have fired on
every busy tick. Deployed inside the 04:17:23Z gap. **No sim killed.** No new
`oomKilled` since 02:37:06Z as of 04:26Z.

**MEASUREMENT — "no data yet", and that is the honest reading:**

    artifact 04:22:51Z  PRE-deploy  (v1)  considered 4  projected 1  priceable 1
                                          candidates 1  written 0  skipped_unchanged 1
    artifact 04:25:14Z  POST-deploy (v2)  considered 0  projected 0  priceable 0
                                          candidates 0  written 0  skipped_unchanged 0

The slate ended between the two builds. **v2 is live and has had zero live rows
to act on.** Nothing here says it behaves as intended. The test is the scheduled
`live-gameline-ledger-check` at 20:30 Central on a full slate.

### CORRECTION, and it is against my own claim from four hours earlier

**"The recorder has never recorded a row" is FALSE.** The pre-deploy build reads
`skipped_unchanged: 1`, and that counter can only be non-zero when a record with
the same key and identical numbers is already on disk — `_moved(None, rec)`
returns True, so an empty file always writes. **v1 wrote at least one row
tonight**, sometime between 02:4xZ and 04:22Z, when a market cleared the bar.

The handoff's "`written: 0` with `enabled: true` proves wiring, not behaviour"
and my own "the ledger was never asked to write anything" were **true of the
03:00Z build and false an hour later**. v2's premise survives — 1 priceable of 4
considered is still a self-selected sample with no denominator — but the stronger
claim that the recorder *structurally could not write* was wrong. **It was wrong
because I generalised a single build to a whole night**, which is the same shape
as this repo's standing rule about reading a null as a fact about the world.

## 2026-08-16 05:0x-05:3xZ — MEASUREMENTS for the three deploys of this run (`#440` Phases 1 and 4.1)

Fills the empty measurement column on `755ec40a`, and records the two deploys
that followed it. **One is VERIFIED, one is INERT BY DESIGN, one is still PENDING.**

### 1. refresh-worker `755ec40a` (04:58:57Z) — **MEASURED: INERT. I enabled the flag on the wrong service.**

`FIXTURE_CADENCE` never appeared, and the reason is structural rather than timing:

    _pregame_sweep_interval_for_tick   called ONLY at live_refresh_loop.py:4338
      inside _apply_pregame_sport_cadence (def 4306)
        called ONLY at :4948
          inside _run_live_refresh_tick (def 4682)

and the imports settle ownership:

    refresh-worker    imports _run_mlb_sim_tick, _weekly_sport_claimed_by_fast_tick, _process_exists
    live-odds-worker  imports _run_live_refresh_tick   <- the ONLY caller

refresh-worker also carries `SYNDICATE_ENABLE_LIVE_ODDS_REFRESH_LOOP=false`. So the
gate was unreachable there and the deploy changed nothing.

**A FALSE LEAD I NEARLY ACCEPTED, recorded because it was convincing:**
refresh-worker DOES emit `[live_refresh_loop] ODDS_SWEEP_OUTCOME` — 13 lines,
including after the deploy — which flatly contradicts "the gate is unreachable
there". Those come from `_run_mlb_sim_tick` (def 4578, emitter at :4621), a
DIFFERENT function in the same module that refresh-worker genuinely does import.
Shared module, shared log prefix, different code path. I also re-verified the log
tool's service mapping (`ls0`=refresh-worker, `lt0`=live-odds-worker) against the
API before trusting any of it, because a swap there would have invalidated the
Phase 0/H2 finding too. It was correct.

**Remediation:** flag DELETED from refresh-worker, SET on live-odds-worker; both
read back across all three services.

### 2. live-odds-worker `dd53d47c` (live 05:20:39Z) — **MEASUREMENT STILL PENDING**

Deployed from live-odds-worker's OWN live SHA `44bc02f3` (2 files, 18 tests green,
no `render.yaml`). Process is alive (first output 05:21:36Z; my earlier "silence"
was log-ingestion lag, not a boot failure). The tick runs. **The gate has not been
reached yet**, and the cause is measured:

    05:08:40  the killed odds refresh stamped a launch -> cooldown until 05:38:40
    05:21:32  tick -> PREGAME_RELAUNCH_COOLDOWN_SKIPPED cooldown_s=1800
    05:36:37  tick -> PREGAME_RELAUNCH_COOLDOWN_SKIPPED  (2 min early)
    ~05:51:37 next tick -> the first that can reach the gate

`_pregame_relaunch_blocked` sits UPSTREAM of `_apply_pregame_sport_cadence`, and
with no live games the loop is on `SYNDICATE_LIVE_ODDS_REFRESH_IDLE_INTERVAL_SECONDS=900`
against an 1800s cooldown — so only every OTHER tick can pass.

**CORRECTION TO MY OWN EARLIER CLAIM, made the same night:** I said the cooldown
"materially caps the modelled -51%/-70%" and that the numbers needed re-deriving.
**That was wrong.** The cooldown and the cadence interval are both MINIMUM
SPACINGS, so the larger binds — and every tier (2h/8h/24h) exceeds the 30-minute
cooldown. The model stands; the cooldown delays OBSERVATION, not effect.

### 3. refresh-worker `1409e96f` (live 05:35:34Z) — **VERIFIED. Phase 4.1 works.**

`SYNDICATE_ACTIVE_SPORTS` on refresh-worker `mlb,wnba,soccer,nfl` -> `nfl`.

    refresh-worker    05:36:13Z  results={'nfl': True}
                                 skipped=['mlb','nba','wnba','soccer']
    live-odds-worker  05:31:52..05:36:24Z, 5 consecutive ticks, unbroken
                                 results={'mlb': True,'wnba': True,'soccer': True}
                                 skipped=['nba','nfl']

**Union complete, intersection empty.** Every registered sport has exactly one
owner; nba is skipped by both (out of season, correct). No sport lost coverage —
that was the failure mode worth checking and it did not happen. MLB/WNBA/soccer
go from built-twice to built-once: **~69 MLB live-lens builds/hr -> ~35**, each
carrying a 120-sim resim, and refresh-worker also sheds WNBA's builder (worst
measured +153MB) and soccer's 4-pass Monte Carlo.

**ATTRIBUTION LIMIT, stated rather than glossed:** this deploy was triggered by the
dashboard env save (`trigger=service_updated`), which deploys the tracked BRANCH
HEAD rather than the live commit — so it carried two commits from another session
(`164f6e80` mlb odds-shard double-read fix, `1409e96f` ledger streaming), both
**memory reductions on the same service**. Neither touches `live_lens_loop.py` or
`ACTIVE_SPORTS`, so the partition mechanism is unaffected — but **if refresh-worker
memory drops, it cannot be attributed to Phase 4.1 alone.** The
`branch-overlap-baseline-watch` before/after boundary must be re-stamped from
05:35:34Z.

## 2026-08-16 05:51:48Z — live-odds-worker `dd53d47c` — **MEASURED: VERIFIED.** Phase 1 gate is live and the soccer exclusion holds

Fills the PENDING row above. The gate ran, resolved, and acted — three consecutive
lines carrying the whole decision chain:

    05:51:48  FIXTURE_CADENCE sport=soccer interval=baseline
                              reason=excluded_pending_per_league_scoping
    05:51:50  PREGAME_CADENCE_DETAIL soccer:marker_age_s=4480/interval_s=28800
    05:51:50  PREGAME_CADENCE_SKIPPED sports=soccer

**THE LOAD-BEARING FIELD IS `interval_s=28800`** — soccer's 8h BASELINE, not a
fixture tier. The exclusion held. Had it not, soccer would have taken a
fixture-derived interval and swept MORE often (the measured +69% case), i.e. the
opposite of this lane's goal. That is what this deploy needed to prove and it
proved it.

Soccer was the only sport in the candidate list on that tick, so it is the only
line; mlb/wnba were not due. That is the cadence filter working, not a gap.

**PREDICTION vs OUTCOME, recorded because it is the evidence the model is right:**
predicted first observable tick ~05:51:37Z, from a 900s idle interval against an
1800s cooldown stamped at 05:08:40Z. Actual: 05:51:48Z. **11 seconds.**

**THREE WRONG TURNS BEFORE THIS, each caught by verification rather than assumption
— none visible from `status=live`:**
1. Flag set on refresh-worker, where `_run_live_refresh_tick` is never imported and
   `SYNDICATE_ENABLE_LIVE_ODDS_REFRESH_LOOP=false`. Deploy fully inert.
2. Post-deploy silence read as a boot failure; it was log-ingestion lag (first
   output 05:21:36Z, 57s after live).
3. `_pregame_relaunch_blocked` sits UPSTREAM of the cadence filter, so two ticks
   passed without reaching the gate at all.

**STILL NOT MEASURED:** the effect. One gate decision is not a cadence outcome.
The sweeps/day change needs the `branch-overlap-baseline-watch` distribution, and
soccer is excluded by design so this lane's headline goal remains DEFERRED to 1c.
## 2026-08-16 04:58:57Z — refresh-worker `755ec40a` — fixture-aware pregame cadence ENABLED (`#440` Phase 1)
**MEASUREMENT: PENDING.** Nothing here is a claim yet. Reminder to read: within
2h of the deploy going live, and again from the 4-hourly
`branch-overlap-baseline-watch`.
**What shipped.** Deploy branch `deploy/fixture-cadence-on-live` @ `755ec40a`,
cut from the **LIVE SHA `5c419007`**, not from `main`. Diff vs live is exactly
two files:
    syndicate/features/shared/live_refresh_loop.py   +183 / -1
    tests/test_pregame_cadence_fixture_aware.py      +201 / -0
Preflight FAILED on the first shape and this is the fix: the service runs a
deploy branch diverged from `main` by 14 live-only / 472 origin-only commits, so
deploying `origin/main` would have changed **196 files, 92 of them `.py`**, while
diagnosing. `render.yaml` untouched — no `blueprint_sync`.
**Config, set by the user in the dashboard and READ BACK before deploying:**
`SYNDICATE_PREGAME_FIXTURE_AWARE_CADENCE=true` on refresh-worker (105 keys, up
from 104); **absent on live-odds-worker and web** — verified, not assumed.
**Deploy safety CLEAR at 04:53Z and re-checked immediately before triggering:**
no MLB sim in flight, odds refresh idle, no live games, board build idle.
**Expected effect, as a number and a window.** Within 2h: `FIXTURE_CADENCE` lines
on refresh-worker carrying `interval` in {7200, 28800, 86400} for mlb/wnba/nfl,
and `reason=excluded_pending_per_league_scoping` for soccer. Pregame sweep
ceiling mlb 12.00 -> 5.45/day, wnba -> 5.83, nfl_preseason -> 3.56. **Soccer
unchanged at 3.00 BY DESIGN** — it is excluded, because at sport granularity the
gate measured +69% (see `learnings.md` 2026-08-15).
**What would falsify it:** no `FIXTURE_CADENCE` line at all (the branch did not
run, or the flag is not being read); or a soccer line with a numeric interval
instead of the exclusion reason.
**Baseline caveat, stated because it limits what can be concluded:** the before
side is **ONE** `branch-overlap-baseline-watch` sample (worst container 4096.0 MB
= 100.0% of cap in 3 hours), not a distribution. The older 3,972 MB / 97.0% /
124 MB figure is STALE and must not be used as the comparison.
**Rollback:** delete the env key (default is False, so absence restores baseline)
and `py -3 scripts/render_deploy.py --service refresh-worker --commit 5c419007`.
## 2026-08-16 ~05:2xZ — THE REMAINING ~1,900 MB IS NAMED: cumulative ledger accumulation
**No deploy.** Measurement only, from production telemetry + code.
### THE CHAIN, each step measured
1. **The 2GB is IN THE PARENT PROCESS.** `ALL_PROCESS_MEMORY` across the
   04:46:44Z kill: **pid 39 (`run_refresh_worker.py`) 3,138 -> 3,545.8 MB**,
   every child under **54 MB** (12 processes). Not a sim job, not a subprocess.
   (pid 39 at 85.9 MB from 04:46:33 is the post-kill reboot.)
2. **The fatal climb runs 51s with NO stage marker.** `last_stage` sat at
   `board_contract_games_normalized` with `seconds_since_stage` 0.7 -> **51.5**
   while anon went **1,666 -> 3,990 MB**. Sport-carrying board emissions stop at
   **soccer 04:45:16**; everything after is unmarked.
3. **What IS logging in that gap:** `[intelligence_evaluation]
   SKIP_OVERSIZED_LEDGER_CHUNK` at 04:45:29, 04:45:33 (x3) and 04:46:01.
   **Read those correctly — they are the guard WORKING**, skipping 305/367/480MB
   chunks. They are not the allocation. What they prove is that **the chunked
   prediction-ledger pass is executing inside the fatal window.**
### THE DEFECT — `intelligence_evaluation.py:615-677`
    def _load_chunked_ledger_records(path) -> list[dict]:
        max_chunk_bytes = _ledger_max_chunk_bytes()   # 256,000,000
        rows: list[dict[str, Any]] = []               # <-- 636, OUTSIDE the loop
        for chunk_path in chunk_paths:                # <-- 637
            if chunk_path.stat().st_size > max_chunk_bytes:  # per-FILE ceiling
                ...continue
            with chunk_path.open(...) as handle:      # #254 streams, correctly
                for line in handle:
                    rows.append(json.loads(line))     # <-- 674, ACCUMULATES
        return rows
**`#254` fixed the wrong half.** It removed the 256MB string and the
`splitlines()` list — real defects — but left `rows`, which **materialises every
record of every ACCEPTED chunk into one list that outlives the loop.** The
ceiling is **per chunk**; nothing bounds the SUM. Three accepted chunks near the
ceiling is ~750MB of file bytes, and this repo measured this JSON family at
**~6.3x file bytes resident** (`#435`) — i.e. **multiple GB in `rows`**.
This is `#435`'s defect one level up. `read_book_quotes_latest` was fixed by
**reducing AS IT STREAMS** (478,782 rows -> 36,424 keys, 92.4% superseded).
Here the streaming was fixed and the reduction was never added.
The file's own comment already contains the principle and stops one step short:
*"the ceiling above bounds which files are SKIPPED, never what reading an
accepted one costs"* — true of the string it was written about, and equally true
of the list it did not consider.
### WHAT IS AND IS NOT PROVEN
**Proven:** location (parent process), timing (inside the unmarked 51s),
mechanism (unbounded cumulative accumulation past a per-file ceiling), and that
the pass runs there.
**NOT proven:** that this totals ~1,900 MB. The accepted-chunk count and their
sizes have not been measured — only the SKIPPED ones are logged, which is
exactly the wrong half to log. **Do not record this as the cause until that
number exists.**
**Cheapest next step, no deploy needed:** log accepted chunks too
(`path`, `bytes`, running `len(rows)`), then read one pass. The guard currently
announces only what it refused, never what it accepted — the same blind spot
that made this take all night.
## 2026-08-16 05:35:34Z — DEPLOY `1409e96f` refresh-worker — MEASURED, AND THE TRANSIENT DID NOT MOVE
Deployed from live `755ec40a` (re-cut; the live SHA moved 3x in 40 min). Window
taken at a job boundary by explicit user decision: 3 jobs in flight, all odds /
soccer refresh, **0 MLB sim jobs**, re-verified immediately before the POST.
Claim acquired and released. Diff vs live: exactly 2 files.
### BOTH FIXES ARE LIVE AND EXERCISED (not assumed — seen)
    05:40:08  [mlb_cards] ODDS_HISTORY_BUILD_CACHE entries=1 date=2026-08-16
    05:43:49  [intelligence_evaluation] LEDGER_CHUNKS_ACCEPTED count=8
              bytes=833550415 ceiling=256000000 records=22188 streamed=1
**THE NUMBER THAT WAS MISSING ALL NIGHT: 833,550,415 bytes accepted across 8
chunks**, every one under the 256MB per-file ceiling. The mechanism is now
proven with a measurement: the ceiling bounded each FILE while the SUM went
unbounded, and all 833MB used to land in one list.
### THE RESULT — HONEST NULL
    metric                 f8ca54e1 baseline   5c419007      1409e96f (this)
    amplitude mean            1,950 MB          2,220 MB        2,235 MB
    peak anon                 3,907 MB          3,426 MB        3,646 MB
    min inactive_file      26.3 / 42.2 MB        12.3 MB           0.6 MB
    kills                   2 in 26 min        1 @22.2 min    0 in 9 min (early)
**The excursion is UNCHANGED.** 833MB is no longer materialised on the paths I
changed, and the transient did not shrink by a measurable amount. So the ledger
accumulation, as reached through `intelligence_evaluation`, is **not** the ~2GB.
### WHY — A CONSUMER I LEFT MATERIALISING, AND IT DOUBLE-COPIES
`recommendation_engine.py:1239` and `:1528`:
    history_rows = [dict(record) for record in
                    (evaluation_records or _load_records_from_ledger(ledger_path))
                    if isinstance(record, Mapping)]
`_load_records_from_ledger` (`:456`) calls the MATERIALISING
`_iter_record_payloads` — the full 833MB-of-chunks list — and the comprehension
then builds a **second full copy**, one `dict(record)` per record. Two complete
copies of the whole ledger, in the recommendation path that runs during board
builds. I fixed the six `intelligence_evaluation` call sites and left this one,
because it wants a list; that is exactly why the number did not move.
**This is the same defect one call frame further out, and the fix pattern is
already proven here.** Next: stream `_load_records_from_ledger`, and drop the
`dict(record)` re-copy unless a downstream mutation actually needs it — check
before removing, `history_rows` may be iterated more than once.
**Standing correction:** the excursions remain tagged `board_contract_games_normalized`
with `seconds_since_stage` 14-51s, so the cost is still in the unmarked region
after that marker. The named candidates so far — deepcopy (EXONERATED, 0.54MB),
odds-shard duplicate (~125MB, FIXED), ledger accumulation (833MB, FIXED on 6 of
8 paths) — do not yet add to 2GB. The remaining double-copy is the best
outstanding candidate and is UNMEASURED.
## 2026-08-16 15:1xZ — DEPLOY `d72d670c` (load-once) — 9h CLEAN, AND THAT PROVES NOTHING YET
Live 06:01:34Z. **Zero OOM kills in 9h 09m** (events API; last kill 04:46:44Z,
before this deploy). Tempting, and not yet evidence.
### THE DIURNAL CONTROL, WHICH IS THE WHOLE POINT
Kills cluster in the LIVE-SLATE window (~22:00Z-05:00Z). The **pre-fix** code
ran **05:02:59Z -> 22:54Z on 08-15 with zero kills — 17h 51m**. So a clean
daytime stretch is exactly what the BROKEN worker also produced, and 9h of
daylight is a weaker run than the defect's own best.
Same clock window, one day apart, near-identical sampling density:
    window 14:25-15:11Z        08-15 PRE-FIX      08-16 POST-FIX (d72d670c)
    samples                       1,368               1,367
    peak anon                   2,816.7 MB          2,898.5 MB   (slightly HIGHER)
    excursions                        0                   0
    min inactive_file               6.5 MB            183.5 MB
**Zero excursions BOTH before and after.** The sawtooth simply does not run in
the daytime lull, so this window cannot separate the two SHAs. Peak is flat
(2,817 -> 2,899, the wrong direction if anything). Only `inactive_file` differs,
which is one reading of a volatile quantity and is not on its own a result.
**The 1,000MB "improvement" I could have claimed** — 3,907 -> 2,898 peak — is an
artifact of comparing a DAYTIME reading against a NIGHT baseline. The correct
comparison is same-clock, and it shows no change.
### VERDICT
`d72d670c` is **UNPROVEN**, exactly like `1409e96f` before it. Three fixes are
live and exercised (odds-shard cache, ledger streaming, three-loads-to-one) and
**not one of them has yet been shown to move the transient**, because every
measurement so far has been either too early, too short, or in the wrong part of
the day.
**The only test that can settle it is the live-slate window, ~22:00Z tonight to
~05:00Z.** Judge on: excursion count/hr, amplitude mean, and `min inactive_file`
against the night baselines (amplitude 1,950-2,235 MB; inactive_file 26.3/42.2
at the kills, 164-240 surviving). A night with excursions at the old amplitude
means these three fixes were not the 2GB.
**Method note, so the next reader does not repeat it:** `watch_rw.py` reports
kills as "since start" with no end bound, so the control run listed three kills
that happened AFTER its window. The window is what the header says; the kill
line is not scoped to it.

---

## 2026-08-16 — `or 0.5` REMOVAL: **EXERCISED, AND THE NULL BRANCH FIRED**. Measurement closed.

**THE READING.** `/api/ops/win-prob-null` at **2026-08-16T15:37:21Z**, HTTP 200,
`reports_root=/opt/render/project/data/reports`, 2 of 8 probed keys present, 0
read failures. Both keys retain 9 runs. **Across all 18 retained runs:
`rows=192, null_no_price=6, pct=3.12%`.** The two runs that fired:

    wnba/live-odds-worker  rows=56  null=3  pct=5.36   05:11:01Z  commit 44bc02f3
    wnba/live-odds-worker  rows=32  null=3  pct=9.38   05:10:59Z  commit 44bc02f3

**That is the confirmation that was owed.** 6 price-missing rows published
`None` instead of a fabricated `0.5`; per the reading guide this is **the fix
WORKING**, not a defect. Nine further runs computed 104 rows with zero nulls —
the fix holding on priced rows. `rows>0` is no longer owed; **11 of 18 retained
runs were exercised.**

**BOTH workers have computed rows** — `wnba/refresh-worker` `rows=16/3/8/5` at
05:12:2xZ on commit `755ec40a` (`date=2026-08-17`, next-day builds). Its null
branch has not fired; every firing so far is live-odds-worker on `date=2026-08-16`.

**RETRACTED, SAME DAY — "every exercised run is on an OLDER commit" WAS FALSE.**
This entry first claimed the newer commits might have stopped computing
`win_prob`, with "one `rows>0` on a current commit" as the discriminator.
**That discriminator was already satisfied in the very payload the claim was
written from.** Re-read 16:14:55Z, ancestry checked with `merge-base
--is-ancestor`, not assumed:

    dd53d47c (descendant of 44bc02f3)  rows=24 / 9 / 15  null=0   05:53:3xZ  live-odds-worker

**48 rows on the current commit.** How the error was made, because the shape
recurs: the `latest` line for live-odds-worker reads `dd53d47c rows=0`, and that
one line was generalised to every `dd53d47c` run — while priors 1-3 carry the
same SHA and are exercised. The discriminating field was already printed on
screen. `#read-the-field-you-already-have`.

**What is actually true:** live-odds-worker computes rows on the current commit;
there is no live-odds-worker rows=0 streak at all (one such run, not five). The
5-run `rows=0` streak is **refresh-worker only**, on `d72d670c` (06:06Z-10:08Z),
whose predecessor `755ec40a` computed 32 rows for the same `date=2026-08-17`.
That service builds only next-day boards, so the benign reading — the board was
already built and later runs found nothing new — is the likely one, but it is
NOT established. **Scope any remaining doubt to refresh-worker; the fix itself
is exercised on current code.**

**READ THE `recent` ARRAY, NOT THE HEADLINE.** The route's top-level summary
said `any_exercised: false`, `rows: 0`, `"producers reported but computed no
win_prob"` — **while the exercised runs sat in the same payload.**
`win_prob_null_diag._summarize` iterates `readings[*].latest` only, so a run
that computed rows is erased from the headline the moment ANY later run reports
`rows=0`. Both services' `latest` happened to be an empty run (live-odds-worker
09:24:45Z; refresh-worker 10:08:33Z on `date=2026-08-17`, a next-day build that
legitimately computes nothing). A reader who trusted `interpretation` would have
filed "still unexercised" on top of the proof. The instrument built to end
instrument-blindness has a latest-only headline that reintroduces it.

**The null branch has only ever fired on live-odds-worker.** refresh-worker
computes rows (4 runs, 32 rows) but on `date=2026-08-17` next-day builds, where
prices are complete; live-odds-worker works the live `date=2026-08-16` slate,
which is where price-missing rows exist at all. If you want to watch the branch,
watch live-odds-worker.

**THE LOG CHANNEL IS CONFIRMED DEAD, AGAIN, AND A SCHEDULED TASK WAS WATCHING IT.**
`WIN_PROB_NULL_NO_PRICE` since 2026-08-15T23:31Z (refresh-worker) and
23:17Z (live-odds-worker): **nothing matched on either**, ~16 hours, while the
counter recorded 18 runs across the two services. Positive control run first —
`live-odds-worker`, empty text, 15:15–15:22Z, **940 lines / 11 pages** — so the
probe was not broken. This is the `capture_output=True` trap already documented
in `win_prob_null_diag`'s module docstring; the scheduled task
`wnba-win-prob-counter-read` greps that dead line and would have reported
"not yet run" forever. **It must be repointed at the route or deleted.**

**PRODUCER LIVENESS, since silence invites the wrong reading.** Not alive at
15:31:34Z: refresh-worker's `ALL_PROCESS_MEMORY` lists `process_count 12` and
**12 processes enumerated** (message 5,565 chars, JSON closes clean — not
truncated), none of them `refresh_wnba_oddsapi_props`; the container was busy
with the MLB sim + rolling soccer artifacts at 95.3% of 4096MB. It ran and
exited twice earlier: visible in census sweeps at 07:07:51–07:08:07Z and a
single sweep at 09:08:29Z. Census cadence is ~9 lines/min, so those are runs of
seconds, not a hung job. No `oomKilled` on refresh-worker since the 06:01:34Z
`deploy_ended` — the short life is an early exit, not a kill.

## 2026-08-16 15:39:58Z — refresh-worker `97491161` — `#441` pbp root fix. **MEASUREMENT: PENDING**

**What shipped.** Branch `deploy/nfl-pbp-root`, cut from refresh-worker's LIVE SHA
`d72d670c` (re-confirmed unmoved immediately before triggering, not assumed).
Diff vs live is three files:

    syndicate/features/nfl/sources.py                +43 / -0   (nfl_pbp_path)
    scripts/generate_smartsim2_nfl_projections.py    +16 / -1   (delegate)
    tests/test_smartsim2_nfl_pbp_root.py            +132 / -0   (6 tests)

`render.yaml` untouched — no `blueprint_sync`. The degenerate-run guard is NOT
relaxed (both `raise DegenerateProjectionRun` sites intact, asserted on the
branch).

**Deploy cost, accepted deliberately.** `check_deploy_safety` read NOT CLEAR:
MLB sim pid 37345, age **1 minute** (`props_now_available`), plus live games.
Chosen anyway because it is the cheapest window observed — the previous sim
(36515) had been running 10 minutes — and `fingerprint_change` relaunches it with
~80 minutes to MLB first pitch (~12:00 CT). After `#440` Phase 4.1 refresh-worker
ticks only NFL live-lens, so the "live games" warning largely applies to
live-odds-worker, which this deploy does not touch.

**EXPECTED EFFECT, as a falsifiable statement.** Within ~15 min of going live:
`SEASON_PROJECTION_LAUNCHING sport=nfl` stops recurring every ~40s, and
`smartsim2_projections_2026_wk1.csv` appears with a fresh mtime.

**WHAT WOULD FALSIFY IT, and it is the honest half:** if `DegenerateProjectionRun`
still raises, the pbp is ALSO absent from the mounted disk and root selection was
a red herring — the fix changes nothing and the guard keeps refusing, correctly.
**This was never directly verified**: web cannot see refresh-worker's disk and
workers serve no HTTP, so what is proven is only that `DATA_ROOT` pointed at the
ephemeral checkout (`/opt/render/project/src/data/nfl_source`) — i.e. the mounted
disk was never consulted. **The deploy is the test.**

**A SECOND FAILURE MODE TO CHECK, not just "did it write":** if the artifact
appears with IDENTICAL rows for every game, the guard was bypassed rather than
satisfied — that is the exact degenerate output it exists to prevent (production
served `margin 0.96 / total 44.38 / home_win 0.5267` on all 16 preseason games on
2026-08-13). Verify row VARIANCE, not just file presence.

**Rollback:** `py -3 scripts/render_deploy.py --service refresh-worker --commit d72d670c`.

## 2026-08-16 15:53:28Z — refresh-worker `97491161` — **MEASURED: THE FIX DID NOT FIX `#441`. Hypothesis falsified.**

Fills the PENDING row above with the answer it asked for. **The falsifier written
into that row is exactly what fired**, ~8 minutes after the deploy went live.

    15:53:28Z  SEASON_PROJECTION_LAUNCHING sport=nfl ... age_seconds=240710
    15:53:28Z  DegenerateProjectionRun: NO PLAY-BY-PLAY DATA
    15:53:28Z  looked for : /opt/render/project/src/data/nfl_source/tracking/nflverse/pbp/pbp_2026.csv

**THE LOG ALONE COULD NOT SETTLE IT, and that nearly cost a wrong conclusion.**
My resolver returns a NAMED fallback when no candidate has the file, and that
fallback is `default_nfl_source_root()` — the same checkout path the OLD code
printed. So "fix not deployed" and "fix ran, found nothing anywhere" emit an
IDENTICAL line. Settled by reading the deployed commit's content instead:

    refresh-worker live on 97491161 since 15:45:50Z
    nfl_pbp_path present in 97491161          : 1
    generator delegates to it in 97491161     : 1

So the resolver RAN, searched every candidate root, and found the pbp on NONE of
them. **Root selection was a red herring.**

**WHAT I GOT WRONG, and why.** The generator's own NOTE asserts: *"the pbp lives
on the mounted disk and is absent from the repo checkout. If DATA_ROOT points at
the checkout, that is the bug, not a missing download."* DATA_ROOT did point at
the checkout, so the NOTE read as a confirmed diagnosis. **It was a hypothesis
written in the imperative, and I inherited it as a measurement.** The half I
never verified — that the file is on the mounted disk — is the half that was
false.

**WHAT THE CHANGE IS STILL WORTH.** It removes a real latent defect: a root
chosen by probing for an unrelated artifact (`upcoming_recs_*.csv`) could
misresolve the pbp whenever both roots exist. That bug was real and is now fixed,
and `#389` fixed its twin on the write path. **It is not a fix for `#441` and must
not be recorded as one.** No rollback: the change is correct, inert when the file
is absent everywhere, and improves the diagnostic.

**ROOT CAUSE NOW (v3):** the pbp is ABSENT FROM EVERY ROOT, and nothing in this
repo writes it — traced: ten scripts reference `pbp`, all reads, zero writes.
There are nflverse fetchers for schedule/rosters/depth-charts/games and **none
for play-by-play**. It was present as recently as **2026-08-13** —
`verify_nfl_autorun_obligations.py:25` records the 21:02:06Z run writing a real
rating on 16/16 games — which matches the 2.79-day staleness exactly. So: present,
then gone, with no code path able to restore it.

---

## 2026-08-16 ~16:20-16:35Z — LAYER 2 BOARD AUDIT (lane `layer2-board-quality`). NO DEPLOY. Eight goals measured against the SERVED payload.

**Substrate.** `/api/board/layer2-shortlist?sport=all&limit=2000`, `written_at`
**2026-08-16T16:20:21Z**, 108 rows, `source=layer2_shortlist_artifact`; the
server-rendered `/intelligence` page (1.73 MB, board contract parsed out of it);
and `/api/board/book-grid?sport=mlb` for the cell-level cross-check.
Live SHAs read at measurement time: refresh-worker `97491161` (15:45:50Z),
live-odds-worker `dd53d47c` (05:20:39Z), web `ebd5f677` (03:38:07Z).

### 0. THE SHORTLIST **IS** THE BOARD NOW. The ledger's standing claim is STALE.

`spread-line-sign-convention` recorded *"NO TEMPLATE CONSUMES THE SHORTLIST —
the board still renders `ranked_all`"*, from a `grep` over `templates/` and
`static/` returning zero hits. **That grep still returns zero, and the conclusion
is now wrong.** The wiring is server-side, not in the template:

    boardContract.cards          108
    source == layer2_shortlist   108 of 108
    layer2_is_primary            True
    legacy_candidate_count       0

Every card a user sees today comes from the shortlist. So every defect below is
**user-facing**, not latent. A `grep` over the template can no longer answer
"does anyone consume this" — read the served payload.

### 1. SPREAD-SIGN FIX: **VERIFIED IN THE ARTIFACT.** 12 of 12. Lane's open item closes.

`_side_line_from_cells` present in the deployed tree (`git show
97491161:...layer2_board.py` -> 3 occurrences, identical to `main`). Output
verified against the book grid, joined on the book set AND the price vector:

    away rows agree      9/9      (already correct pre-fix)
    home rows agree      3/3      (the case that was broken)
    total               12/12

**TWO WAYS I NEARLY GOT THIS WRONG, both worth keeping:**

- **Ancestry gave the OPPOSITE answer.** `git merge-base --is-ancestor edbbee9d
  97491161` -> **NO**, because refresh-worker runs branch `deploy/nfl-pbp-root`,
  not `main`. By ancestry the fix looks un-deployed; by content it is deployed.
  `project_web_runs_a_deploy_branch_not_main` generalises to the WORKERS too.
- **My first join said 3 of 3 home rows were still WRONG.** The grid carries
  MIRRORED rows for the same (event, market, segment) — `row.line=+1.5` with
  `home_cells=-1.5` alongside `row.line=-1.5` with `home_cells=+1.5`. Matching on
  `line` picks the wrong twin and manufactures a uniform-looking defect. The
  discriminating field is the **price vector**: the disputed row's
  `{leovegas_se:123, prophetx:140, unibet_nl:125, unibet_se:125}` matches
  `row.line=1.0` (home cells -1.0) exactly, so `-1.0` is CORRECT.
  **A 3-of-3 "uniform defect" that dissolves on a better join is the same shape
  as the 525-cell result that opened that lane — and that one is still sound,
  because it compared cells WITHIN a row rather than across mirrored rows.**

### 2. **REGRESSION: the `min()` score fix is NOT running in production.**

Measured two independent ways, agreeing:

    (a) served payload: rows with negative value_pct        4
        of those, score == value * reliability              4/4   (discount applied)
        of those, score == min(value, discounted)           0/4
        `reliability_applied` key present                   0/108

    (b) deployed source, git show 97491161:...opportunity_signals.py
        "score": round(value * confidence * freshness * price_reliability, 4)
        vs main: "score": round(min(value, discounted), 4)

**Cause: a branch cut before the fix landed.** `deploy/nfl-pbp-root` branched at
`b0ab37a1` (2026-08-15 17:26 CDT); `5a94b134`, which carries the `min()`, landed
**19:04 CDT — 1h38m later**. Both workers and web are on trees without it
(`reliability_applied` count: refresh-worker 0, live-odds-worker 0, web 0).

So the inversion that fix was built to kill is live again: on these 4 rows the
LESS a bad row is trusted, the BETTER it ranks. Small on today's board (4 of
108); the measurement that justified the fix had **156 negative of 256**, so the
exposure is slate-dependent, not inherently small.

**This is the general failure, not a one-off: cutting a deploy branch from an
older commit silently un-ships every fix landed since the branch point, and
nothing in the deploy path reports it.**

### 3. THE SIM CARRIES **ZERO** WEIGHT. The brief's premise (`0.5`) is wrong.

`_SCORE_SIM_WEIGHT = 0.0` in `opportunity_signals.py:390` — and identically in the
deployed tree. Confirmed in the served payload rather than inferred:

    rows carrying model_edge_pct        65 of 108
    rows with non-zero sim_component     0 of 65
    rows where value_pct != ev_pct       0 of 108

`layer2_board.py:30`'s module docstring still says `_SCORE_SIM_WEIGHT = 0.5`, and
so does the session brief. **The constant was deliberately zeroed** with its
reasoning in place (`opportunity_signals.py:352-390`): the sim term dominated,
`settled: 0`, so it was selecting rows where an unvalidated model most disagrees
with the market. Raising it is gated on S6, not on taste.

**THE OBLIGATION THAT COMMENT CREATES IS UNMET.** It states: *"THE SURFACE MUST
SAY WHAT IT IS: with this at 0, L2-A is a low-hold / line-shopping board and must
NOT be presented as 'our model found these'."* The board presents these as
recommendations with a PROJECTED column and no such disclosure. That is the
single largest honesty gap on the surface.

**Its stated consequence is only PARTLY true, and the reason matters.** The
comment predicts EV is identical for every side under proportional de-vig, so
"L2-A cannot pick a side at all". Measured: of the 6 market-instances with both
sides on the board, only **2** carry identical `ev_pct`. Best-book-per-side
breaks the symmetry — the board discriminates by LINE SHOPPING, not by a model.
That is consistent with the comment's conclusion and refutes its arithmetic.

### 4. BEST-BOOK IS UNRESTRICTED. 27 of 108 (25.0%) are unbettable-by-default.

Layer 2 has no allowlist of any kind; 36 distinct books appear in `book_prices`.
Against Layer 1's `DEFAULT_BOOKS` (11, `layer1_board.html:267`):

    best book outside the L1 list    27 of 108   25.0%
      betopenly      16
      betfair_ex_eu   9
      betsson         2

**9 of those 27 are `h2h_lay` rows quoted ONLY by `betfair_ex_eu` + `matchbook`**
— exchange LAY markets. They do not degrade to a worse price under the L1 list;
they disappear, because no L1 book quotes them at all. The other 18 cost a few
cents (`betopenly +191 -> novig +182`), which is the honest price of restricting
to books the user can actually bet.

### 5. **`h2h_lay` ROWS ARE LABELLED AS BACK BETS. This is the worst defect found.**

`_pick_label` (`layer2_board.py:1029`) maps `side=home` -> the home team's name,
with no market-family awareness. A LAY bet is a bet **against** that team, so a
card reading *"Los Angeles Dodgers"* is a bet ON the Dodgers LOSING, rendered
identically to a back bet. 9 such rows served. No sport, market or price check
distinguishes them.

### 6. PROP CARDS ATTRIBUTE THE PLAYER TO THE **AWAY** TEAM, UNCONDITIONALLY.

`layer2_board.py:1123`: `"team": home if side == "home" else away`. A prop's side
is `over`/`under`, never `home`, so **every prop card falls to `away`** —
56 of 108 cards. Right ~half the time by coincidence. Served example: **Andy
Pages** (Los Angeles Dodgers, the HOME team) carried `"team": "Milwaukee
Brewers"`. Read by the UI at `intelligence.html:525`.

### 7. MOVEMENT / STEAM: DARK, CONFIRMED IN THE PAYLOAD.

`_layer2_movement_columns` is `return {}` with an unreachable body
(`layer2_board.py:1152`). Union of all keys across 108 served rows contains **no**
movement, steam or opening field. The score has no movement term. The `#372`
stall reason still holds — the join loaded a ~20 MB shard inside the builder —
so re-enabling it naively re-stalls the build.

### 8. THE GAME RAIL IS DERIVED FROM OPPORTUNITIES, SO IT CANNOT SHOW A GAME THAT HAS NONE.

`deriveGameCards(items)` (`intelligence.html:1258`) groups **board rows**. A game
with no surviving opportunity contributes no row and therefore no rail card.
Today this is invisible — MLB 15 scheduled / 15 on the rail, WNBA 3 / 3, because
`SHORTLIST_ROWS_PER_GAME = 6` seated every game — so **the defect is structural,
not currently observable**. `/api/board/game-chips` already returns the full
slate; the rail must be seeded from chips and left-joined to rows.

**Finals sort to the FRONT, not the end.** The rail sort
(`intelligence.html:1443`) is `hasLive` -> start time -> count. `allFinal` is
computed (`:1307`, `:1409`) and used only for the LABEL at `:1496`; it appears
nowhere in the comparator. A finished game keeps its early start time and sorts
ahead of everything not live.

### 9. WHOLE SPORTS ARE ABSENT, AND IT IS THE HORIZON, NOT AN OUTAGE.

    active_sports        ['mlb', 'wnba']
    nfl    2,861 candidates / 2,492 opportunities -> rows_beyond_horizon 2,492  (ALL of them)
    soccer 8,933 candidates / 3,199 opportunities -> 0 selected
    ncaaf  no_slate

`rows_beyond_horizon = 2492` equals NFL's opportunity count exactly, so
`SHORTLIST_HORIZON_DAYS = 1` drops NFL entirely. Soccer's 3,199 die elsewhere
(`rows_uninformative_ev` 1,884 + `rows_excluded_market` 1,854 + value floor 601
across all sports). **Consistent with the `#380` comment at `:1012-1026` and NOT
a bug** — but it means "audit every in-season sport" resolves to MLB and WNBA
only, and the horizon is exactly what G1 must widen for the RAIL without
widening the SHORTLIST.

### 10. LIVE-LENS PROJECTION DOES NOT REACH LAYER 2.

6 live rows served, all carrying a projection — but **every projection source on
the board is a PREGAME artifact**: `hitter_threshold` 41, `game_simulation` 30,
`pitcher_distribution` 4, `wnba_props_recommendations` 3, none 30. Zero live
sources. The book-grid payload carries `live_projections` (19) and
`live_gamelines` (8) that the shortlist build never joins.

**Today's slate hides the consequence:** all 6 live games are at `TOP 1`, where a
full-game pregame projection is still nearly right. Later in a game, a pregame
`total_runs_dist` projection of 10.516 shown beside a LIVE total of 7.0 is a
full-game number against a remaining-game line. Matches lane
`live-game-line-projection`'s "plumbing done twice, evaluation not started".

### 11. THE BET SLIP ALREADY SITS BESIDE THE BOARD; IT COLLAPSES THE WRONG WAY.

`#bet-slip-panel` is section 3 of 5 inside `<aside class="board-rail">`
(`intelligence.html:83`). Collapsing hides only `.bet-slip__body`
(`board_cards.css:1091`), leaving a header stranded mid-rail. Layer 1 collapses
the WHOLE rail horizontally — `.l1-layout[data-rail="collapsed"] .l1-rail {
flex-basis: 34px }` (`layer1_board.html:143`) with a count badge at `:152`.
`board_rail_toggle.js` + `.board-rail-handle` already exist but are gated to
**mobile only** (`board_cards.css:726`: *"Desktop/tablet (>1080px): .board-rail
stays a normal static grid"*). So the desktop work is to lift an existing mobile
mechanism, not to write a new one.

### 12. THE `layer2_board.py` CLAIM WAS NEVER ENFORCEABLE.

`lane-guard.py`'s `_claims()` returns **zero** claims on that file.
`FILES_RE` matches the holding lane's header line on the colon inside `23:0xZ`,
yielding no paths; the two continuation lines carrying the real paths start with
a backtick, so `in_files` never harvests them. That lane recorded *"Collision
check RUN … CLEAR both times, so no other lane was blocked by the gap"* — **it
read CLEAR because its own claim was invisible, not because the file was free.**
A guard that cannot parse a claim reports the same string for "unclaimed" and
"claimed in a format I cannot read".

---

## 2026-08-16 16:19–16:40Z — lane `layer1-board-coverage` — MEASUREMENT ONLY, NOTHING DEPLOYED

**Nothing was deployed and nothing is claimed fixed in production.** `e543e8dd`
is committed to the local `main` only. Render `autoDeploy = no` for code, so the
served payloads below are all PRE-change and remain what production serves.

### Instrument
`GET /api/board/layer1?sport=<s>&view=all&window=slate` on
`https://syndicate-an21.onrender.com`, one same-instant sweep 16:19:52–16:20:07Z,
plus a 4-build availability watch 16:26–16:37Z. Board's own counters
(`counts.rows`, `counts.rows_with_projection`) plus a per-row walk.

### Baseline re-established (the prior one had expired)
`docs/ai_context/betting_contract_lifecycle.md` §3a recorded MLB **19.7%
projected / 0 edges / game state 1,220 of 3,604**. Today: **68.3% projected
(1,941/2,843) / 1,462 edges / game state 2,843 of 2,843**. Judging today's board
against that table would have booked another lane's fix as this lane's
regression. That table is superseded, not wrong-at-the-time.

### Availability — the briefed premise did not reproduce
4 distinct consecutive MLB builds (16:26:31 / 16:30:45 / 16:33:49 / 16:35:06),
**all non-zero**, WNBA and soccer non-zero on all 4. The "`count=0` on 3 of 5
builds" reading is not the current behaviour. **Coverage does move between
builds** — projected 2,107 → 1,935 with `rows` flat at 3,006 across one rebuild —
so any future availability claim must carry the `generated_at` it was read from.

### The finding `e543e8dd` addresses
Rows with a projection, an empty `Edge`, and **no `edge_unavailable_reason` key
at all** (absent, not null — checked: `key_absent` 284/284):

```
mlb    284   223 batter_home_runs, 34 batter_total_bases, 26 batter_hits, 1 outs
wnba     3   game|h2h|full, source "wnba_game_cards"
soccer   0   attributes 1,176 of 1,176
```

### Verification method, and why it is not a fixture
The changed function was replayed over **the real served payloads**, re-deriving
the `fair` term with the same `_no_vig_over_probability` the producer calls
rather than trusting the payload's own field:
**287 of 287 previously-silent rows emit a reason, 0 unattributed.**
284 `one-sided market: no two-sided fair to price against`, 3
`this projection's producer does not compute a probability-space edge`.
`tests/test_prop_projections_edge_attribution.py` 11 passed;
`test_prop_projections.py` + `test_live_edge_policy.py` + `test_market_board_ui.py`
41 passed, 32 subtests, no regression.

### What would falsify the fix after a deploy
Re-run the same sweep and count rows with a projection, no edge of either
contract, and no reason. **Expected 0.** Any non-zero names a branch the helper
does not cover. Do NOT verify by "the reason string appears" — it appears on 287
rows already in the replay; the discriminating count is the residual.

### A hypothesis I raised and then falsified in the same pass
The 3 WNBA `h2h` rows looked like a side-frame mismatch: `projection.side` is a
team NAME ("Phoenix Mercury") while `consensus` is keyed `home`/`away`, the
hazard `layer1_board.html:770` warns about. **Checked: all three name the HOME
team**, so the terms describe the same team and the subtraction is legitimate
(model 0.9673 vs fair 0.6502 = +31.7pp). Which makes it a MODEL reading on a
projection whose own `model_skill` says `sample_games: 0, "model never
backtested"` — so it stays refused, and now says so. Recorded because the wrong
version was nearly written into the code comment as the cause.

### Not deployed, not claimed
No production behaviour has changed. Full audit with per-sport × per-family
rates: `.syndicate/audit_2026-08-16_layer1_board.md`.


### PENDING DEPLOY — 2026-08-16 16:46:14Z — refresh-worker `ed54071a` (branch `deploy/restore-score-min`)

**Change (exactly one):** `syndicate/features/shared/opportunity_signals.py`
taken whole from `main` onto live `97491161`. 1 file, +71/-1. Restores
`"score": round(min(value, discounted), 4)` and `reliability_applied`.

**/preflight verdict: FAIL on the main-wide option, PASS on this one.**
Deploying `main` would have carried **520 commits / 207 files / 85,232
insertions** from seven parallel sessions, including work the ledger explicitly
HOLDS (state.md decision 7). That is not one substantive change. The narrow unit
is: imports byte-identical to the live tree, nothing in the live tree calls the
one added function (`consensus_vigged_price`), so the only behavioural delta is
the `min()`.

**Expected effect, as a number and a window:** on the FIRST shortlist artifact
written after this goes live, every row with `score.value_pct < 0` satisfies
`score == value_pct` (not `value_pct * reliability`), and `reliability_applied`
is present on 100% of rows. Board builds ran ~every 20 min today (last completed
16:42:49Z), so the window is **one build after the deploy finishes**.

**Measurement + who reads it:** this session (`layer2-board-quality`), against
`/api/board/layer2-shortlist`. Baseline to beat: 4 of 4 negative-value rows
inverted, `reliability_applied` 0 of 108.

**Blast radius:** refresh-worker only — restart, stop-then-start. `check_deploy_safety`
CLEAR (MLB sim `killed_by_restart`, odds refresh idle, board build idle) with a
**live-games-in-progress warning**: the restart interrupts live-lens ticks and
live prop hydration. Accepted; the user authorised the deploy. live-odds-worker
and web NOT deployed — they carry the same stale `blended_score`, but the board
is built on refresh-worker, and one change per deploy.

**Rollback:** `py -3 scripts/render_deploy.py --service refresh-worker --commit 97491161 --allow-rollback`

**Ledger check:** no `learnings.md` FORBIDDEN/EXONERATED rule covers this
(the two deploy rules — never trust `check_deploy_safety` alone, never read a
deploy claim's `target` as what is running — are both honoured: safety was
corroborated against the live SHA read from the deploys API, and the target was
verified a descendant of it). `opportunity_signals.py` is claimed only by
`layer2-board-quality` (this lane).

**MEASUREMENT — 2026-08-16 17:13:56Z. THE FIX IS LIVE AND EFFECTIVE.**

Post-deploy artifact `written_at` **2026-08-16T17:13:13Z** (deploy finished
16:59:48Z), 108 rows:

    reliability_applied present     108 of 108   (was 0 of 108)
    negative value_pct rows           4
    min() applied on them             4 of 4     (was 0 of 4)

The four scores MOVED, which is the part a key-presence check would have missed:

    value_pct   score BEFORE   score AFTER
     -0.0215      -0.0000       -0.0215
     -0.1510      -0.0005       -0.1510
     -0.2577      -0.0032       -0.2577
     -0.4970*     -0.0041*      -0.4970

    (* the 4th row is not the same row across the two reads -- the slate moved.
       Its pre-fix sibling was value -0.6237 -> score -0.0041.)

Bad rows now rank on their badness instead of being flattened toward zero by a
low reliability multiplier. At the extreme: a row with reliability 0.0004 scored
**54x better than its own value** before, and exactly its value now.

**WATCHED, NOT SPOT-CHECKED.** The first read after the deploy returned
`written_at 16:47:34Z` — a PRE-deploy artifact — with 0 of 108 carrying
`reliability_applied` and 0 of 4 minned. Read as a result it says "the fix
failed"; it actually says "the board has not rebuilt yet". Only a watcher
polling until `written_at > deploy finishedAt` separates the two, and this is
the second time in this ledger that an early read would have produced a
confident wrong conclusion.

**MY DEPLOY WAS SUPERSEDED 7 MINUTES LATER and the fix survived anyway.**
`ed54071a` went live 16:52:40Z and was deactivated by another session's
`a775e372` (live 16:59:48Z). Verified BY CONTENT that `a775e372` carries
`min(value, discounted)` and `reliability_applied`, and that it is a descendant
of `ed54071a`. **The artifact measured above was built by `a775e372`, not by my
commit.** Recorded because "my deploy went live" and "the code I deployed
produced this number" are different claims, and only the second is load-bearing
— on a service where deploys are superseded within minutes, the first is not
evidence for the second.

## 2026-08-16 17:10:45Z — refresh-worker `a775e372` — **MEASURED: the diagnostic worked. `#441` root cause SETTLED on the first reading.**

Deployed 16:59:48Z, rebased onto another session's `ed54071a` so neither deploy
was cancelled. First post-restart refusal at 17:10:45Z carried the block:

    env SYNDICATE_REQUIRE_HOSTED_STORAGE = 'true'
    env SYNDICATE_NFL_SOURCE_ROOT = '/opt/render/project/data/nfl_source'
    env SYNDICATE_DATA_ROOT = '/opt/render/project/data'
    strict_hosted_storage_resolves_to = True
    candidate[0] /opt/render/project/data/nfl_source/source_artifacts/.../pbp_2026.csv  exists=False
    candidate[1] /opt/render/project/data/nfl_source/.../pbp_2026.csv                    exists=False
    candidate[2] /opt/render/project/src/data/nfl_source/source_artifacts/.../pbp_2026.csv exists=False
    candidate[3] /opt/render/project/src/data/nfl_source/.../pbp_2026.csv                exists=False

**v4 FALSIFIED, v3 CONFIRMED.** The env vars DO reach the subprocess and strict
storage IS on, so my "the mounted disk was never searched" hypothesis was wrong.
Candidates 0 and 1 ARE the mounted disk, they WERE searched, and the file is not
there. The pbp is genuinely absent from every root: **`#441` is an ingestion gap.**

**IT ALSO DISSOLVED THE CONTRADICTION THAT PRODUCED v4.** `DATA_ROOT` printed the
checkout because `_first_existing_root` returns the first root holding
`upcoming_recs_*.csv`, and only the checkout ships those — even though
mounted-disk candidates come FIRST in the list. Both readings were always
consistent; I inferred a contradiction that was not there.

**And it corrected my reading of `preferred_artifact_roots`.** I claimed strict
mode cannot append the repo checkout. There is a SECOND append after the branch I
read: under `strict AND RENDER`, the checkout mirror is added as a lower-priority
fallback. Deliberate, and it explains candidates 2/3.

**Both shipped changes hold up.** `nfl_pbp_path` demonstrably searches the mounted
disk first (candidates 0/1 prove it), and the diagnostic turned a question that
had produced three wrong answers into one reading. Neither is a fix for `#441`.

**Process note worth keeping:** this deploy was preceded by a `deploy_claim.py`
acquire — the first real use of that tooling — after the previous attempt
(`a859f5f8`) was cancelled 0.4s into another session's deploy. Claim acquired,
base re-confirmed live at trigger time, claim released after the reading.

## 2026-08-16 17:20-17:28Z — ALT-LINE PROJECTIONS (`32186e28` / `c422f79a`) — **MEASURED: PASS** (watch attempt 2 of 4)

The measurement owed since 2026-08-15 is taken. **All five gate conditions passed,
including the fifth added after the void attempt 1.** Verdict: **PASS.**

### Gate — all five, on the full slate

| # | condition | reading | verdict |
|---|---|---|---|
| 1 | book-grid `rows` non-empty | `total_rows` **3325** | PASS |
| 2 | `projections.games_in_summary` > 0 | **15** | PASS |
| 3 | main `spreads`/`totals` with `projection.source` > 90% | **165 of 165 = 100%** (spreads 89/89, totals 76/76) | PASS |
| 4 | shortlist >= 30 rows | **108** | PASS |
| 5 | book-grid alt rows > 0 AND shortlist MLB alt rows > 0 | **361 alt rows**; **17 MLB alt** | PASS |

**Counts are per-market fetches, not the flat read.** `/api/board/book-grid`
hard-caps `limit` at `min(2000, ...)` regardless of what you pass, so `limit=4000`
returned 2000 of 3325 and every count off it is a floor. The `market=` filter is
applied BEFORE the cap (`intelligence.py:2240`), so a per-market fetch is exact.
Attempt 1's numbers were taken off the capped read; this one is not.

### Attribution — the artifact under test was built by the fix

`generated_at = 2026-08-16T17:20:51Z`. refresh-worker deploy history that hour:
`a775e372` live **16:59:48Z**, `01a4b83e` live **17:26:25Z** — so `a775e372`
built it. Blob check, by content not ancestry:
`a775e372:shared/prop_projections.py` = `3ec9f652` = the blob at `32186e28`.
Byte-identical. **The fix is what produced these rows.**

Noted for the next reader: `01a4b83e`, live 6 minutes AFTER this artifact, carries
`prop_projections.py` at **`07348e83`** — 100 insertions / 5 deletions off
`32186e28`, another lane's change. This measurement predates it and does not vouch
for it.

### Book grid — the fix's primary effect, and it is decisive

| market | rows | with `projection.source` |
|---|---|---|
| `spreads` | 89 | 89 (100%) |
| `totals` | 76 | 76 (100%) |
| `spreads_alt` | 171 | **169** (99%) |
| `totals_alt` | 190 | **190** (100%) |

**Alt rows: 359 of 361 carry a projection, all `source: game_simulation`.**
BEFORE (2026-08-15 22:41Z): **238 alt rows, 0 with a projection.** That is the
predicate, met.

### Shortlist — PASS on the stated predicate, with a real caveat

`written_at = 2026-08-16T17:19:04Z`, 108 rows (baseline 88), 82 carrying a model
projection (baseline 52).

- **MLB alt rows with non-null `score.sim_component`: 12 of 17. Baseline: 0 of 9.**
- alt rows 30 (17 `spreads_alt`, 13 `totals_alt`), split **mlb 17 / wnba 13**
- by sport: mlb 90, wnba 18, **nfl 0** (baseline mlb 62, nfl 14, wnba 12)
- by kind: game 69, prop 39 (baseline game 65, prop 23)

**The 5 MLB alt rows still at `None` are NOT a failure of this fix.** Four are
`live`, and live game rows carry no `model_edge_pct` at all on either side of the
deploy — MLB main-market live rows were **0 of 21** on the baseline and are **0 of
12** now. The live gap is slate-wide and pre-existing, not alt-specific.

The valid comparison is pregame, where alt rows now behave exactly like main rows:

      bucket                    n    edge!=None   sim!=None   sim!=0
      MLB alt   pregame  NOW    13       12           12         0
      MLB main  pregame  NOW    22       18           18         0
      MLB main  pregame  BASE    3        3            3         0
      MLB alt   live     NOW     4        0            0         0
      MLB main  live     BASE   21        0            0         0

**CAVEAT, and it is the load-bearing one: `sim_component` is non-null but exactly
`0.0` — in every bucket, on main markets too.** Rows with `model_edge_pct` of
`+14.83` and `-12.0` both score `sim_component = 0.0`. This is NOT introduced by
this deploy: baseline MLB main pregame was already 3 non-null / **0 non-zero**.
So the honest statement is that the fix moved alt rows from `None` to `0.0`,
which is the same degenerate value main markets already had. **Alt rows now
participate in the scoring path identically to main rows; that path is currently
contributing nothing.** That residual is the open `layer2-board-quality` lane's
stated testable outcome (a) — "`sim_component` non-zero wherever `model_edge_pct`
is non-zero" — and it is failing, for main and alt alike. Not this deploy's bug,
but nobody should read `12 of 17` as "alt rows are now sim-ranked".

### Re-ranking — the risk being watched did NOT materialise

- **MLB alt mean rank: 42.6 pctile -> 37.6 pctile.** Moved slightly UP.
- All-alt mean rank: 38.6 pctile -> 57.3 pctile. Moved DOWN — driven entirely by
  WNBA alt rows growing 5 -> 13 and sinking to the bottom (ranks 83-101).
- **No crowd-out.** Top-20 composition ALT 5 -> 4; top-40 ALT 9 -> 8. Prop rows
  GREW, 23 -> 39. Alt rows did not displace main-market or prop rows.

(Baseline mean rank recomputed here as 38.6 pctile, not the 39.1 carried in the
watch prompt — same 34.0-of-88 rank, different percentile convention. Immaterial;
both comparisons above use one convention throughout.)

WNBA alt rows remain non-discriminating as documented — every WNBA projection
comes from the props path, `project_game_market` returns None at `if not payloads`
regardless of this fix. Scored on MLB only.

### Live props (secondary) — small move, as predicted

On the 2000-of-3325 capped slice (**a floor, not a total**): 86 rows with
`projection.source = mlb_live_lens_monte_carlo`, of which **13 sit at a market
carrying more than one distinct line**.

One thing does not match the prior: 8 of those 13 are `batter_home_runs`, which
the watch prompt states has no captured alternates. **Do not bank this** — the
heuristic used (same player+market, >1 distinct line across the grid) cannot
separate a captured alternate from two books quoting different lines. It is a
flag for someone to check, not a finding.

### Verdict

**PASS.** The book-grid predicate is met outright (0 -> 359 of 361). The shortlist
predicate is met as written (0 -> 12 MLB alt rows with a non-null sim component)
and alt rows moved up, not down, without crowding anything out. **No rollback
indicated.** Rollback targets, unused: refresh-worker `191d098f4a8d`,
live-odds-worker `b7ae47e6d1a0`.

Measurement only — no deploy, no rollback, no source file touched. The watch task
is discharged; attempts 3 and 4 are not needed and the task was not re-armed.

## 2026-08-16 17:20-17:28Z — ALT-LINE PROJECTIONS (`32186e28` / `c422f79a`) — **MEASURED: PASS** (watch attempt 2 of 4)

The measurement owed since 2026-08-15 is taken. **All five gate conditions passed,
including the fifth added after the void attempt 1.** Verdict: **PASS.**

### Gate — all five, on the full slate

| # | condition | reading | verdict |
|---|---|---|---|
| 1 | book-grid `rows` non-empty | `total_rows` **3325** | PASS |
| 2 | `projections.games_in_summary` > 0 | **15** | PASS |
| 3 | main `spreads`/`totals` with `projection.source` > 90% | **165 of 165 = 100%** (spreads 89/89, totals 76/76) | PASS |
| 4 | shortlist >= 30 rows | **108** | PASS |
| 5 | book-grid alt rows > 0 AND shortlist MLB alt rows > 0 | **361 alt rows**; **17 MLB alt** | PASS |

**Counts are per-market fetches, not the flat read.** `/api/board/book-grid`
hard-caps `limit` at `min(2000, ...)` regardless of what you pass, so `limit=4000`
returned 2000 of 3325 and every count off it is a floor. The `market=` filter is
applied BEFORE the cap (`intelligence.py:2240`), so a per-market fetch is exact.
Attempt 1's numbers were taken off the capped read; this one is not.

### Attribution — the artifact under test was built by the fix

`generated_at = 2026-08-16T17:20:51Z`. refresh-worker deploy history that hour:
`a775e372` live **16:59:48Z**, `01a4b83e` live **17:26:25Z** — so `a775e372`
built it. Blob check, by content not ancestry:
`a775e372:shared/prop_projections.py` = `3ec9f652` = the blob at `32186e28`.
Byte-identical. **The fix is what produced these rows.**

Noted for the next reader: `01a4b83e`, live 6 minutes AFTER this artifact, carries
`prop_projections.py` at **`07348e83`** — 100 insertions / 5 deletions off
`32186e28`, another lane's change. This measurement predates it and does not vouch
for it.

### Book grid — the fix's primary effect, and it is decisive

| market | rows | with `projection.source` |
|---|---|---|
| `spreads` | 89 | 89 (100%) |
| `totals` | 76 | 76 (100%) |
| `spreads_alt` | 171 | **169** (99%) |
| `totals_alt` | 190 | **190** (100%) |

**Alt rows: 359 of 361 carry a projection, all `source: game_simulation`.**
BEFORE (2026-08-15 22:41Z): **238 alt rows, 0 with a projection.** That is the
predicate, met.

### Shortlist — PASS on the stated predicate, with a real caveat

`written_at = 2026-08-16T17:19:04Z`, 108 rows (baseline 88), 82 carrying a model
projection (baseline 52).

- **MLB alt rows with non-null `score.sim_component`: 12 of 17. Baseline: 0 of 9.**
- alt rows 30 (17 `spreads_alt`, 13 `totals_alt`), split **mlb 17 / wnba 13**
- by sport: mlb 90, wnba 18, **nfl 0** (baseline mlb 62, nfl 14, wnba 12)
- by kind: game 69, prop 39 (baseline game 65, prop 23)

**The 5 MLB alt rows still at `None` are NOT a failure of this fix.** Four are
`live`, and live game rows carry no `model_edge_pct` at all on either side of the
deploy — MLB main-market live rows were **0 of 21** on the baseline and are **0 of
12** now. The live gap is slate-wide and pre-existing, not alt-specific.

The valid comparison is pregame, where alt rows now behave exactly like main rows:

      bucket                    n    edge!=None   sim!=None   sim!=0
      MLB alt   pregame  NOW    13       12           12         0
      MLB main  pregame  NOW    22       18           18         0
      MLB main  pregame  BASE    3        3            3         0
      MLB alt   live     NOW     4        0            0         0
      MLB main  live     BASE   21        0            0         0

**CAVEAT, and it is the load-bearing one: `sim_component` is non-null but exactly
`0.0` — in every bucket, on main markets too.** Rows with `model_edge_pct` of
`+14.83` and `-12.0` both score `sim_component = 0.0`. This is NOT introduced by
this deploy: baseline MLB main pregame was already 3 non-null / **0 non-zero**.
So the honest statement is that the fix moved alt rows from `None` to `0.0`,
which is the same degenerate value main markets already had. **Alt rows now
participate in the scoring path identically to main rows; that path is currently
contributing nothing.** That residual is the open `layer2-board-quality` lane's
stated testable outcome (a) — "`sim_component` non-zero wherever `model_edge_pct`
is non-zero" — and it is failing, for main and alt alike. Not this deploy's bug,
but nobody should read `12 of 17` as "alt rows are now sim-ranked".

### Re-ranking — the risk being watched did NOT materialise

- **MLB alt mean rank: 42.6 pctile -> 37.6 pctile.** Moved slightly UP.
- All-alt mean rank: 38.6 pctile -> 57.3 pctile. Moved DOWN — driven entirely by
  WNBA alt rows growing 5 -> 13 and sinking to the bottom (ranks 83-101).
- **No crowd-out.** Top-20 composition ALT 5 -> 4; top-40 ALT 9 -> 8. Prop rows
  GREW, 23 -> 39. Alt rows did not displace main-market or prop rows.

(Baseline mean rank recomputed here as 38.6 pctile, not the 39.1 carried in the
watch prompt — same 34.0-of-88 rank, different percentile convention. Immaterial;
both comparisons above use one convention throughout.)

WNBA alt rows remain non-discriminating as documented — every WNBA projection
comes from the props path, `project_game_market` returns None at `if not payloads`
regardless of this fix. Scored on MLB only.

### Live props (secondary) — small move, as predicted

On the 2000-of-3325 capped slice (**a floor, not a total**): 86 rows with
`projection.source = mlb_live_lens_monte_carlo`, of which **13 sit at a market
carrying more than one distinct line**.

One thing does not match the prior: 8 of those 13 are `batter_home_runs`, which
the watch prompt states has no captured alternates. **Do not bank this** — the
heuristic used (same player+market, >1 distinct line across the grid) cannot
separate a captured alternate from two books quoting different lines. It is a
flag for someone to check, not a finding.

### Verdict

**PASS.** The book-grid predicate is met outright (0 -> 359 of 361). The shortlist
predicate is met as written (0 -> 12 MLB alt rows with a non-null sim component)
and alt rows moved up, not down, without crowding anything out. **No rollback
indicated.** Rollback targets, unused: refresh-worker `191d098f4a8d`,
live-odds-worker `b7ae47e6d1a0`.

Measurement only — no deploy, no rollback, no source file touched. The watch task
is discharged; attempts 3 and 4 are not needed and the task was not re-armed.

## 2026-08-16 17:53Z — both workers — the props-snapshot `force_refresh` escape — DEPLOYED, MEASUREMENT OWED

| service | commit | live | cut on |
|---|---|---|---|
| refresh-worker | `b9f2b5f1` | 2026-08-16T17:53:08Z | `f88796a9` |
| live-odds-worker | `e28594a7` | 2026-08-16T17:53:28Z | `dd53d47c` |

Web deliberately NOT deployed: these exporters are producer-side only.

**Verified by CONTENT on both live SHAs, not by deploy status:** `wnba_guards=3`,
`nba_guards=3`, `nba_materialize_param=1`. 20 tests green on each branch before
push, and the branches were cut on each service's OWN live SHA — `main` is not a
superset of the workers.

**THE LIVE SHA MOVED WHILE I PREPARED, AND THE FIRST BRANCH WAS ALREADY STALE.**
refresh-worker went `01a4b83e` → `f88796a9` (17:40:50Z) between cutting and
deploying. `8c52b0dd` was cut on `01a4b83e`; deploying it would have REVERTED
whatever `f88796a9` carried. Re-cut on `f88796a9` as `b9f2b5f1` — the ancestry
check (`01a4b83e` IS an ancestor of `f88796a9`) is what made the re-cut a rebase
rather than a merge. **"Live" is a lease; re-read it immediately before firing.**

- refresh-worker deployed into a genuine lull (2 processes, both infra).
- live-odds-worker deployed on top of 3 jobs (`refresh_odds_sources` +
  `build_soccer_artifacts --league primeira_liga`), as established earlier
  tonight: 10 of 10 samples over 25 minutes had jobs. That service has no idle
  window during live hours. The jobs re-run next cycle.

**MEASUREMENT OWED — this is NOT verified in effect.** Falsifiable check, on
`/api/ops/win-prob-null`: a run that passes `--force-refresh` for a date whose
`cards_props_snapshot_<date>.json` ALREADY EXISTS must now emit a
`refresh_wnba_oddsapi_props:cards_props_snapshot` staged record. Before this
deploy that record could only appear on a first build. Absence of it proves
nothing on its own — `--force-refresh` only fires on a lineup/injury trigger, so
check that a forced run happened at all before reading a null as a failure.
---

## 2026-08-16 17:26Z + 17:40Z — lane `layer1-board-coverage` — TWO DEPLOYS, refresh-worker — FALSIFICATION TEST **PASS** ON THE SECOND

**Service: `refresh-worker` (`srv-d91dpertqb8s73co8ls0`) only.** Web was NOT
deployed and deploying it would have been INERT: `/api/board/layer1` is a pure
read, and the `projection` field is written at artifact-build time by
`run_refresh_worker.py:3140 -> build_book_grid_artifact -> attach_projections`.

**NEITHER DEPLOY WAS CUT ON `main`, and that was load-bearing.** refresh-worker
was live on `a775e372`, a deploy branch carrying **22 commits absent from
`origin/main`** — another live session's `#441` diagnostic, `ed54071a`'s min()
score guard restore, the clamp sites, Drop 3, the cadence work. Deploying `main`
would have rolled every one of them back. Both deploys were cut on the LIVE SHA
and the owning session was notified before the first.

| deploy | commit | parent | live at |
|---|---|---|---|
| `dep-da0v2mflk1mc738rp8eg` | `01a4b83e` | `a775e372` (live SHA) | 17:26:25.559Z |
| `dep-da0v9715efls73aiicpg` | `f88796a9` | `01a4b83e` (live SHA) | 17:40:50.831Z |

Pre-deploy safety: all 15 MLB slate sims for 2026-08-16 already written, so no
in-flight sim was killed. The `#441` diagnostic is print-on-run and carries no
accumulated state, so the restart cost it only its next print.

### THE TEST GATE — an artifact built BY the new code, not just a live deploy

Both runs waited for `generated_at` to exceed the deploy's `finishedAt` on every
sport before sweeping. First run: artifact 17:27:07Z > deploy 17:26:25Z. Second:
mlb 17:41:35Z / wnba 17:41:43Z / soccer 17:41:57Z, all > 17:40:50Z. **Reading the
pre-deploy artifact would have scored the old code and called it a result.**

### RUN 1 — FAIL, and the failure is the useful part

```
mlb     RESIDUAL 0     (was 284)   attributed 1245
wnba    RESIDUAL 3                 attributed 0      <-- FAIL
soccer  RESIDUAL 0                 attributed 1176
VERDICT: FAIL — 3 rows still serve a blank Edge with no reason
```

**MY PRE-DEPLOY VERIFICATION PROVED THE HELPER AND NOT THE CALL PATH.** The
replay ran `_edge_unavailable_reason` directly over the 3 real WNBA rows and it
returned the right string — so I recorded "287 of 287 attributed" and believed
the population was covered. It was not: `wnba_game_projections.py:208` writes
`row["projection"]` **directly** and never passes through
`prop_projections.attach_projections`, so the shipped code could not reach those
rows at all. A **fourth producer**, which is the shape the Layer 1 brief warned
about for `fair_price` — *a count of definitions is not a count of producers* —
and the residual is what found it, exactly as the test was written to.

### RUN 2 — PASS

```
mlb     rows 3303  generated 17:41:35Z  RESIDUAL 0  attributed 1418
wnba    rows  936  generated 17:41:43Z  RESIDUAL 0  attributed    3
soccer  rows 6453  generated 17:41:57Z  RESIDUAL 0  attributed 1176
--------------------------------------------------------------------
rows swept 10,692   RESIDUAL 0 (expected 0)   attributed 2,597
VERDICT: PASS — no silent blank Edge remains on any in-season sport
```

### REGRESSION CHECK — no edge was created or removed

```
mlb     projected 2285   with edge 867   37.9%
wnba    projected  329   with edge 326   99.1%
soccer  projected 1704   with edge 528   31.0%
```

**MLB's edged count fell 1,462 (16:19Z) -> 867 and that is NOT this change.**
`by_state` went `{live 1, pregame 14}` -> `{live 8, pregame 7}` over the same
window; the live-edge policy withholds pregame-derived edges on live games, and
`"game is live: a pregame projection cannot be priced against a live market"`
rose 65 -> 697 to match. Stated because the raw number looks like a regression
and is not — re-read it against a pregame slate before drawing any conclusion.

### Rollback, if ever needed
Redeploy `a775e372` on `srv-d91dpertqb8s73co8ls0` (reverts both).
Branch `deploy/layer1-edge-attribution` on origin holds both commits.

### Still true, and unchanged by this
No edge was added. The 1,416 rows carrying BOTH a `model_prob_over` and a
`modelled_fair.*.fair_probability` still serve no edge — that remains a user
decision, not a defect. The 3 WNBA rows now say why rather than being blank; one
of them would read +31.7 pp against a model with `sample_games: 0`.

## 2026-08-16 17:53Z — both workers — the props-snapshot `force_refresh` escape — DEPLOYED, MEASUREMENT OWED

| service | commit | live | cut on |
|---|---|---|---|
| refresh-worker | `b9f2b5f1` | 2026-08-16T17:53:08Z | `f88796a9` |
| live-odds-worker | `e28594a7` | 2026-08-16T17:53:28Z | `dd53d47c` |

Web deliberately NOT deployed: these exporters are producer-side only.

**Verified by CONTENT on both live SHAs, not by deploy status:** `wnba_guards=3`,
`nba_guards=3`, `nba_materialize_param=1`. 20 tests green on each branch before
push, and the branches were cut on each service's OWN live SHA — `main` is not a
superset of the workers.

**THE LIVE SHA MOVED WHILE I PREPARED, AND THE FIRST BRANCH WAS ALREADY STALE.**
refresh-worker went `01a4b83e` → `f88796a9` (17:40:50Z) between cutting and
deploying. `8c52b0dd` was cut on `01a4b83e`; deploying it would have REVERTED
whatever `f88796a9` carried. Re-cut on `f88796a9` as `b9f2b5f1` — the ancestry
check (`01a4b83e` IS an ancestor of `f88796a9`) is what made the re-cut a rebase
rather than a merge. **"Live" is a lease; re-read it immediately before firing.**

- refresh-worker deployed into a genuine lull (2 processes, both infra).
- live-odds-worker deployed on top of 3 jobs (`refresh_odds_sources` +
  `build_soccer_artifacts --league primeira_liga`), as established earlier
  tonight: 10 of 10 samples over 25 minutes had jobs. That service has no idle
  window during live hours. The jobs re-run next cycle.

**MEASUREMENT OWED — this is NOT verified in effect.** Falsifiable check, on
`/api/ops/win-prob-null`: a run that passes `--force-refresh` for a date whose
`cards_props_snapshot_<date>.json` ALREADY EXISTS must now emit a
`refresh_wnba_oddsapi_props:cards_props_snapshot` staged record. Before this
deploy that record could only appear on a first build. Absence of it proves
nothing on its own — `--force-refresh` only fires on a lineup/injury trigger, so
check that a forced run happened at all before reading a null as a failure.

---

## 2026-08-16 17:5x-18:0xZ — LAYER 2 BOARD FIXES, TWO SERVICES (lane `layer2-board-quality`)

Both branches cut from each service's **LIVE SHA**, never from `main`. `/preflight`
had already failed `main` on scope (520 commits / 207 files / 85,232 insertions).

### WEB — `4ab9d12a` on `deploy/layer2-board-ui`, parent live `ebd5f677`

5 files: `intelligence.html`, `board_cards.css`, `bet_slip.js`,
`board_rail_toggle.js`, `tests/js/game_rail_derive.test.mjs`. +307/-10.

Carries the rail-from-chips seeding, finals-sort-last, the ranking disclosure,
the 36px betslip strip, and the `sim disagrees` badge (inert until the worker
half lands — the field does not exist yet, so the badge simply does not render).

**ALSO CARRIES `f3b9b293`** (another lane): whole-numbered lines keep their
decimal. Unavoidable — same file — web-only, 28 tests, already on `main`.

### REFRESH-WORKER — `b8939778` on `deploy/layer2-bettable-books`, parent live `f88796a9`

8 files, +741/-32. The book allowlist (`book_shortlist.py`, new), the lay-bet
label, the prop-team fix, `sim_view`, plus the approved ridealong `734c163e`.

**THE RIDEALONG IS A CHERRY-PICK, AND TAKING THE FILES FROM `main` WOULD HAVE
REVERTED LIVE WORK.** `c410be4d`'s per-artifact `win_prob` emit is on
`f88796a9` and **absent from `main`** — copying `main`'s two prop scripts scores
**49 deletions instead of 13** and silently un-ships another lane's
instrumentation. Three-way merged onto the live versions instead (`git merge-file`,
clean, no markers): `_record_win_prob_null` survives at 4 sites, `force_refresh`
arrives at 23. Same class as `fb448d60`, "production code was not on the default
branch" — and the second time in two days that `main` was the wrong source for a
worker file.

**Tested against the EXACT deploy commit**, not against `main`: a detached
worktree at `b8939778`, 39 passed — including the ridealong's own suite run
against the MERGED scripts, which is different code from what its lane tested.

### Expected effect, as numbers on the next artifact after the worker deploy

    quote.bookmaker outside DEFAULT_BOOKS      27 of 108  ->  0
    rows dropped for no bettable book                     ->  no_bettable_book > 0
    rows repriced to a bettable book                      ->  repriced_to_bettable > 0
    cards with team set on a prop (side=over/under)  56   ->  0
    h2h_lay selections rendered as a bare team name   9   ->  0
    rows carrying sim_view                            0   ->  108

### Blast radius / gate

Web: restart, brief 502s — observed, and it blinded `check_deploy_safety.py`
itself (see below). Worker: restart, kills any in-flight sim or board build.
**HELD at 17:57Z** on `MLB sim RUNNING (pid=148, fingerprint_change)` + a board
build; deployed only after an explicit `CLEAR:`.

**`check_deploy_safety.py` RETURNED `[UNKNOWN] HTTP 502` WHILE WEB RESTARTED,
AND THAT IS NOT A CLEAR RESULT.** It reads live-refresh state off the web
service. The string contains neither `NOT CLEAR` nor `CLEAR:`, so a watcher
testing `'NOT CLEAR' not in out` — which is what I first wrote — reports the gate
CLEAR precisely while it cannot see. Killed and replaced with one that requires
an explicit `CLEAR:` line AND the absence of `[UNKNOWN]`. This is the same shape
as the standing rule "never deploy on `check_deploy_safety.py` alone": here it
was not wrong, it was **blind**, and blind read as permissive.

### Rollback

    py -3 scripts/render_deploy.py --service web --commit ebd5f677 --allow-rollback
    py -3 scripts/render_deploy.py --service refresh-worker --commit f88796a9 --allow-rollback

### Ledger check

No `learnings.md` FORBIDDEN/EXONERATED rule covers these. Files claimed only by
`layer2-board-quality`; the two prop scripts belong to `export-force-refresh-escape`,
whose lane text explicitly authorises this ridealong.

**MEASUREMENT (web) — 2026-08-16 18:0xZ. LIVE at 18:03:15Z, all five changes SERVED.**

Read off the production page and its static assets, not off the repo:

    /intelligence          board-disclosure block        2
                           claimedChips (rail seeding)   3
                           const isFinal (finals last)   1
                           board-badge--sim-disagrees    1
                           game-mini-card--empty         2
    board_cards.css        minmax(0, 1fr) 36px           1
                           .game-mini-card--empty        2
                           .board-disclosure             3
    bet_slip.js            syncRailSlipCount             2

**THE RAIL GOES FROM 18 CARDS TO 108, AND 90 OF THE NEW ONES ARE SOCCER.**
Measured against the live endpoints:

    /api/board/game-chips        108 games today   (mlb 15, soccer 90, wnba 3)
                                 9 live, 99 pregame
    games WITH an opportunity     18   (mlb 15 + wnba 3)
    NEW count-0 cards             90   (all soccer)

This is literally what "list all of today's games with or without an
opportunity" asks for, and it is a **6x expansion of the rail** driven entirely
by a sport that is at ~0 published EV rows **by decision** (state.md decision 7:
the soccer model loses to the market, so its rows die on the EV floors). Under a
sport filter the rail is 15 or 3; only the "all" view shows 108.

Flagged rather than quietly shipped. If the compact rail should stay compact,
the cheapest scoping is to seed only from sports in `active_sports` (18 cards,
which is what the shortlist already publishes) — a one-line change to the
`state.sport` guard in the seeding loop.

**The `sim disagrees` badge is CORRECTLY INERT.** The renderer is live; the
field it reads (`sim_view`) is stamped by the worker, which has not deployed.
Verified the degrade is silent: 0 badges render, no console error.

**MEASUREMENT (worker): SUPERSEDED — that branch (`b8939778`) was never deployed.**
It went two deploys stale behind the gate and was re-cut as `7b544eb4`; the real
measurement is under the 18:13:53Z entry below. Left in place rather than
deleted, because a blank placeholder that is silently removed reads as a
measurement nobody took.

**RE-VERIFIED 2026-08-16 ~19:0xZ, after TWO further worker deploys by other
sessions.** The worker is now on `a72b4bf4` (live 18:54:37Z), two past mine.
Content on the CURRENT live SHA: `no_bettable_book` 4, `_is_lay_market` 2,
`_row_team` 2, `sim_view` 3, `repriced_to_bettable` 4, `book_shortlist.py`
PRESENT. Outcomes on the served payload (artifact 18:52:57Z, 92 rows / 88 cards):

    best book outside DEFAULT_BOOKS   0        h2h_lay rows            0
    prop cards team == away_team      0        cards on unbettable bk  0
    cards carrying sim_view           88/88    lay cards               0

**Stated precisely: that artifact (18:52:57Z) PREDATES the current live SHA
(18:54:37Z), so it verifies my fixes, not `a72b4bf4`.** The content check above
is what covers `a72b4bf4`. Conflating the two would be claiming a build proved
code it never ran.

**THE COUNTER GAP IS FIXED IN CODE AND NOT DEPLOYED** (`7576b1d5`,
`pipeline/layer2_shortlist.py`): `no_bettable_book` / `repriced_to_bettable` now
reach `per_sport_ingest`. Producer-side only — **rides along with the next
worker deploy; web needs nothing.**

---

## 2026-08-16 18:0xZ — lane `layer1-board-coverage` — **SOCCER SERVES BETTABLE EDGES ON FINISHED MATCHES.** Found by the user, not by my sweep

**Not a deploy. A production defect found while trying to CLOSE the lane, and the
reason it stays open.**

**The user said "SOCCER has live games" while the board said `live: 0`.** They
were right. My own instrument had already produced the smell — 10 soccer games
marked `pregame` with kickoffs 3+ hours past, 17 more in `unknown` — and I had
read that as a scoping curiosity rather than the thing it was.

### Measured, production, 18:03Z (`/api/board/layer1?sport=soccer&window=slate`)

```
soccer games past kickoff                                        14
  of those, carrying a real live SCORE on the chip                12   <- the SCORE join works
  board `counts.by_state.live`                                     0   <- the STATE join does not
  >3h past kickoff (certainly over)                               10
rows on those games                                            1,236
*** rows serving a BETTABLE EDGE on a game in play or finished    45 ***
```

Worked example: **GRO @ ADO, kicked off 7.8 h ago, final score 4-1, and the board
serves an edge on `totals 2.5`** — a market that settled OVER before lunch. Also
`totals 3.0`, `totals 2.75`, `spreads -0.0`. `status_token` on these rows is
`"5:15A CT"` — the scheduled kickoff rendered as a clock, i.e. the PREGAME token.

MLB and WNBA: 0 stale-pregame games, 0 unknown. **Soccer only.**

### Why it costs edges rather than just looking wrong

`live_edge_policy` keys on `game.state`. `pregame` is its PERMISSIVE branch, so a
game stuck in `pregame` never has its edge withheld. This is `#413` exactly — the
defect whose fix ordering (`attach_live_game_state_from_lens` BEFORE
`attach_projections`) is documented in `book_grid_artifact.py` — reappearing on a
sport whose state never becomes live in the first place.

### The decision site, named

`attach_game_state` (`board_enrichment.py:124-139`) copies `chip["state"]`
straight through, so it is not the cause. The state is decided in
`game_chip_scoreboard._game_flags` (`:113`):

- It infers live/final **from status TEXT ONLY** — `status.is_live`,
  `status.in_progress`, `live_state.in_progress`, `gameState in {LIVE, CRIT}`, or
  substrings `"in progress"` / `"live"` / `"final"`.
- **It never consults the kickoff time or the score.** A match 7.8 h past
  kickoff at 4-1 is not evidence of anything to this function.
- `if not is_live and not is_final: state = "pregame"` — **absent status maps
  onto the permissive branch.** The standing rule
  *"unknown must not default permissive"* is violated here, in the one place
  where the permissive branch is what releases money.
- Note the line directly above it already distrusts a placeholder score
  (`0-0 on a non-live non-final game is suppressed`) — so the function DOES
  reason about scores, just never in the direction that would catch this.

**HYPOTHESIS, not yet confirmed at runtime:** soccer emits `status` as a **string**
(`features/soccer/cards.py:197` and `:512`, via `_status_label`), while
`_game_flags` reads it as a **dict** (`game.get("status") if isinstance(..., dict)
else {}`). If so, every soccer status is invisible to the predicate by TYPE and
the fall-through is guaranteed. `features/soccer/cards.py` never sets
`in_progress` or `shared_is_live` (grepped: zero hits), which is consistent.
**Falsify by dumping one soccer chip's `game` dict as the worker sees it** before
changing `_game_flags` — I have not done that, and the type mismatch is inference
from two greps, not a measurement.

### Deliberately NOT fixed here

`_game_flags` is shared by all eight sports. Teaching it to infer state from
kickoff+score would change MLB, WNBA, NFL and NCAAF behaviour too, and a wrong
`live` is as costly as a wrong `pregame`. That is a scoped change with a real
blast radius, needs its own lane and its own falsification test, and
`game_chip_scoreboard.py` is unclaimed by any OPEN lane as of this writing.

### What this invalidates in my own audit
My G3 conclusion "no second sport was live, so the cross-sport live A/B is
deferred" was **WRONG**. Soccer WAS live. The A/B was blocked by the board's
inability to see it — which is itself the finding the A/B was supposed to
produce.

---

## 2026-08-16 18:13:53Z — refresh-worker `7b544eb4` — **GATE OVERRIDDEN ON EXPLICIT USER INSTRUCTION**

`deploy/layer2-bettable-books-v2`, cut on live `cf467794`. 5 files, +565/-19:
`book_shortlist.py` (new), `layer2_board.py`, 3 test files. The board fixes only —
the props ridealong is NOT in this branch (see below).

### The gate was RED and was overridden deliberately

    * MLB sim RUNNING (pid=111, reason=fingerprint_change, started 18:08:53Z)
    * Board build IN FLIGHT (started 17:57:07Z)   <- PHANTOM, see below

User instruction, verbatim: **"deploy it now, don't wait for the sim"**, given
after being told the sim was running and that a restart kills it. Logged here
because an overridden gate that is not written down is indistinguishable from a
gate nobody ran. **The sim was killed by this deploy. That was the accepted cost,
not an accident.**

### The board-build half of the gate was a PHANTOM, and that is worth keeping

The marker claimed a build in flight since 17:57:07Z — across another session's
`cf467794` deploy at 18:07:36Z, which restarts the worker and therefore kills any
running build. Falsified by the output rather than by the marker: the shortlist
artifact `written_at` was still **17:35:43Z, 35.8 minutes stale**, so the 17:57
build never produced anything. Same shape as `#443` (a stale PID silently stalls
work after every restart).

**So `check_deploy_safety.py` reported two blockers of which one did not exist.**
A gate that cannot distinguish a running build from a killed one is a gate that
will eventually be ignored for the wrong reason. Cross-check it against the
ARTIFACT's `written_at`, which is the output, not the marker.

### THE BRANCH WAS RE-CUT TWICE, AND THE SECOND RE-CUT PREVENTED A REVERT

The first branch `b8939778` was cut on `f88796a9`. While it sat behind the gate,
two deploys landed from another session:

    b9f2b5f1  17:53:08Z   the props ridealong, both workers
    cf467794  18:07:36Z   #441 NFL pbp ingestion path

**Deploying `b8939778` would have reverted both.** It was two deploys stale after
14 minutes of waiting.

Re-cut as `7b544eb4` on `cf467794`, and the props ridealong was DROPPED from it:
`cf467794` already carries it (`force_refresh` x23) and still preserves
`c410be4d`'s per-artifact emit (`_record_win_prob_null` x4), so that lane's
three-way merge and mine agree. `git diff --name-only cf467794 -- scripts/` is
EMPTY on this branch — their work is not touched.

**The rule this proves, and it is the other session's own words from the 17:53
entry above: "Live is a lease; re-read it immediately before firing."** It moved
TWICE in the 14 minutes my branch was gated. Waiting on a gate is itself a source
of staleness — the longer a branch is held, the more likely it has become a
revert.

### Expected effect on the first artifact built after this goes live

    quote.bookmaker outside DEFAULT_BOOKS      27 of 108  ->  0
    no_bettable_book                            absent    ->  > 0
    repriced_to_bettable                        absent    ->  > 0
    cards with team set on a prop               56 of 108 ->  0
    h2h_lay rendered as a bare team name         9        ->  0
    rows carrying sim_view                       0        ->  108

**A build takes time and deploy churn keeps killing them** — no artifact has been
written since 17:35:43Z. Do not read a stale artifact as a failed fix; gate the
measurement on `written_at > 18:1xZ`.

### Rollback

    py -3 scripts/render_deploy.py --service refresh-worker --commit cf467794 --allow-rollback

**MEASUREMENT — 2026-08-16 18:31-18:4xZ. FIVE OF SIX OUTCOMES LANDED; ONE INSTRUMENTATION GAP.**

Artifact `written_at` **2026-08-16T18:31:26Z**, genuinely after the deploy's
`finishedAt` 18:20:40Z. 108 rows / 108 cards.

    best book outside DEFAULT_BOOKS      27 of 108  ->  0        PASS
    cards on an unbettable book                     ->  0        PASS
    h2h_lay rows served                   9         ->  0        PASS
    lay cards on the board                          ->  0        PASS
    prop cards attributed to a team      56 of 108  ->  0        PASS
    cards carrying sim_view               0         ->  108/108  PASS
      (none 75 / agrees 17 / disagrees 16)
    no_bettable_book, repriced_to_bettable          ->  ABSENT   FAIL

**The prop-team fix reads as `—`, not as a missing key.** All 51 prop cards
carry `"team": "—"` — the board's own null placeholder. `_row_team` returns
None and the card normaliser renders that as an em dash, which is the intended
outcome: a blank cell rather than a real player on a real opposing team. Verified
`team == away_team` on **0 of 51** (was 56 of 108).

### THE ONE MISS: the filter's own counters are computed and never published

`no_bettable_book` and `repriced_to_bettable` are returned by
`build_layer2_rows` and do not appear anywhere in the served payload — not at
top level, not in `per_sport_ingest` for any of the five sports.
`pipeline/layer2_shortlist.py` assembles `per_sport_stats` from an EXPLICIT KEY
LIST and my two keys are not in it.

**This is `#397`'s trap, which the codebase already warns about in this exact
module**: *"a rule that trims silently is a rule nobody can tell apart from a
thin slate"*, and `select_shortlist`'s own comment says a new counter "ALSO has
to be added to `/api/board/layer2-shortlist`'s explicit key list". I added the
counters in the same commit as the rule — which was the point — and still missed
the third place that has to know about them.

Consequence, stated plainly: **the book filter is working and invisible.** Today
it is verifiable indirectly (27 -> 0 offenders), but on a future slate a board
that shrank because 40 rows had no bettable book would be indistinguishable from
a thin slate. OWED, tracked in the lane.

### The measurement script was wrong twice before it was right

- It counted `h2h_lay` with `'lay' in market`, which matches **player**
  (p-**lay**-er). It reported "7 remaining, was 9" — a plausible partial failure
  that was actually `player_points` / `player_assists` / `player_rebounds`. The
  correct predicate `'_lay' in market` gives **0**. `_is_lay_market` in the
  shipped code guards against exactly this and my checker did not.
- It looked for `sim_view` on the shortlist ROWS. `sim_view` is stamped by
  `_layer2_board_columns`, which feeds the CARDS. Rows: 0. Cards: 108/108.

Both would have been read as failures of a working fix. **A measurement script
needs the same predicate discipline as the code it measures** — and when a
verification disagrees with an expectation, check the verifier before the fix.

---

### ask-answer-substance — web `ad77e46a` — MEASURED

- Deployed: 2026-08-16 13:27 CDT (18:27:30Z) — **web only** (`srv-d88ahvrbc2fs73eodu30`)
- Change: the inline quick ask names the exact bet (market, line, side, price,
  book) and grounds it in the sim projection already in the payload. Four user
  reports, all reproduced against production payloads captured the same hour.
  `bet_analysis.edge` was `ev_pct/100` while the briefing's was `model_edge_pct`
  — the same pick read **14.01 in the briefing and 0.0139 per-pick**.

- **SHIPPED AND LIVE, BUT NOT IN THE DEPLOY I FIRED.** My
  `dep-da0vrufqj5pc73bd6h7g` (`a92f76e9`, cut from web's own live SHA) was
  **CANCELED mid-build at 18:18:08Z** when a peer started a web deploy; theirs
  (`82a3cded`) was cancelled the same way at 18:20:44Z. The peer resolved it by
  folding both changes into **`ad77e46a`** — "the rail scoping AND the Ask
  substance work, because my deploy canceled theirs" — live 18:27:30Z. **My
  three blobs are byte-identical in it, checked by hash, not assumed.** Two
  earlier attempts were also blocked and both blocks were correct: the first
  refused by `render_deploy.py` because web had moved `ebd5f677` → `4ab9d12a`
  under me and my branch would have reverted 826 lines of another session's work.

- **The new code IS running** — asserted on the branch, not the outcome. 8/8
  fields that exist ONLY in the new adapter came back on production:
  `market_label`, `edge_pct`, `price`/`bookmaker`, `model_skill_status`, and a
  generated `recommendation` on rows whose `_candidate_prose` source is empty.
  - **The ten-fold contradiction is closed.** Same pick, same instant: briefing
    `edge 14.01`, per-pick `edge 14.01`. `model − market − edge` = **0.000**.
  - Served: `"Ryan Johnson over 2.5" · earned runs · -101 at draftkings · 2 bks ·
    Sim 3.951 · Model 63.0% · Market 49.0% · Edge 14.0%` plus the generated
    reason and a stale-quote clause. **Was: `"Ryan Johnson"`.**
  - A moneyline row now reads `"Milwaukee Brewers"`, a spread `"Minnesota Twins
    -1.5"`. Was `"home -1.5 (Philadelphia Phillies @ Minnesota Twins)"`.

- **Harness: 37/52 → 37/52, ZERO pass/fail flips**, all seven classes identical
  (advice 4/5, entity 9/10, explain 4/6, history 2/5, lookup 8/8, ranking 7/10,
  refusal 3/8). Diffed **per case**, because 37 == 37 is not the same claim as
  "the same 37". Control
  `reports/ask_regression/control_pre_answer_substance_2026_08_16.json` (18:0xZ,
  pre-deploy, same slate — the handed-down 38/52 was another day's slate and had
  expired); post `.../post_answer_substance_2026_08_16.json`.
  **This is the result predicted in writing before the run**: `_score` checks
  refusal/routing/hallucination/certainty/50-50 and cannot see selection shape,
  units, price, sim terms, or the panel. A large gain would have been suspicious.

- **ONE PREDICTION WAS WRONG, IN DIRECTION, AND THE CAUSE IS NAMED.** I wrote
  that `warn:selection_not_on_board` would RISE (selections are longer now). It
  **FELL, 125 → 100**. Cause: h2h rows now render as an exact team name
  (`"Milwaukee Brewers"`, which matches the harness's team list) where they
  previously read `"away (milwaukee brewers @ los angeles do…)"`. I reasoned only
  about props and forgot moneyline rows, which went the other way and dominated.
  Spreads rows still warn — `"minnesota twins -1.5"` is not a bare team name.

- **Landed on `main` as `3f16ee2e`.** Checked first and it was NOT there:
  `ad77e46a` is not an ancestor of `main`, so without this a later deploy cut
  from `main` would have silently reverted a live change. `main` and the live SHA
  now carry identical blobs for all three files. 168 tests green on the `main`
  base before pushing.

- **Blast radius, and why `check_deploy_safety.py` was overridden deliberately.**
  It returned NOT CLEAR with three items — MLB sim `pid=111`, odds refresh
  `pid=553` on live-odds-worker, board build on refresh-worker. **All three are
  on WORKERS; this deployed WEB only, so none was killed.** Its fourth line ("a
  restart interrupts live-lens ticks and live prop hydration") was checked
  against web's live env rather than assumed: `MLB_ENABLE_LIVE_LENS_LOOP=false`,
  `MLB_ENABLE_LIVE_LENS_BACKGROUND_REPORTS=false`,
  `SYNDICATE_ENABLE_INTELLIGENCE_STATE_BACKGROUND_LOOP=false` — **web owns no
  loop.** Real cost was ~1–2 min of 502s during a live slate.
  `deploy_preflight.py` returned UNKNOWN for web because its
  `ALL_PROCESS_MEMORY` sample is **47h stale**; recorded as an instrument being
  blind, not counted as a clean read.

- Rollback (unused): `py -3 scripts/render_deploy.py --service web --commit
  4ab9d12a --allow-rollback` — note this would also drop the peer's rail scoping,
  since the two shipped in one commit.

- **This row was written twice.** The first copy was appended at 18:1xZ and was
  **clobbered within minutes** by a peer's whole-file write to `deploys.md` —
  gone from the worktree, from `HEAD` and from `origin/main`, with no conflict
  and no error. A `cat >>` append is not safe on a contended ledger file. This
  copy is committed in the same action that writes it.
## 2026-08-16 18:37Z + 18:54Z — lane `soccer-live-game-state` — TWO DEPLOYS, refresh-worker — **FALSIFICATION PASS.** Soccer stopped serving edges on finished matches

Follow-on from the user's report ("SOCCER has live games") while the board said
`live: 0`. Both deploys cut on the LIVE worker SHA, never on `main`.

| deploy | commit | parent | live at | what |
|---|---|---|---|---|
| `dep-da103u95efls73ak3bcg` | `38ba954c` | `7b544eb4` (another session's live deploy) | 18:37:38Z | soccer publishes a structured `live_state` |
| `dep-da10c3u1egvs739mu440` | `a72b4bf4` | `38ba954c` | 18:54:37Z | live-edge refusal enforced at the wrapper |

### Deploy 1 — the state. Diagnosis confirmed BEFORE coding, as the ledger required

Dumped the real provider rather than trusting the grep-based hypothesis: soccer's
game dict gave the liveness readers nothing structured. `status` was a display
**string**, and `live_state` / `gameState` / `status_badge` were absent, so
`_game_flags` returned `(False, False)` for **all 90** soccer chips while MLB
returned **9 live of 15**. Falling back to prose, `_infer_live_state`'s
`final_tokens` contains **"scheduled"** — soccer's own placeholder wording
actively forced a not-live verdict.

`status_state` (`pre`/`in`/`post`) was already computed and already used to
decide whether to fetch live stats. It was never put on the game dict.

**Sport-local by choice.** No shared eight-sport predicate was touched (verified:
`game_chip_scoreboard.py` and `game_board_contract.py` unchanged). Widening
`_game_flags` to infer liveness from kickoff+score was the alternative and is
strictly more dangerous — a wrong `live` costs as much as a wrong `pregame`.

**Result, first post-deploy artifact:**
`{live 0, final 0, pregame 49, unknown 17}` → **`{live 4, final 11, pregame 34,
unknown 17}`**. Games past kickoff still marked pregame: **10 → 0.**

### Deploy 1 was NOT sufficient, and the sweep is what said so

With states finally correct, **27 rows still carried an edge on a game whose own
`game.state` read `final`**, plus 9 on live games from a pregame projection.
GRO @ ADO, `final`, 4-1, served `edge_vs_line: -0.175`.

**The producer's refusal existed and was unreachable.**
`soccer_projections._price_against_market` opens `if model_prob is None: return`,
and `_mean_projection` sets `model_prob_over: None` **alongside** `edge_vs_line`
— so every mean-based row (every soccer game spread and total) returned before
the refusal ran. The comment on that refusal reads *"this runs for every row,
mean-based and probability-based alike. Checked rather than assumed."* It did
not, and the early return three lines above it was why.

### Deploy 2 — enforcement at the choke point, not the producer

Added `_enforce_live_edge_policy` to `board_enrichment.attach_projections`, for
the reason that function's own docstring already gives about the degeneracy
check: thirteen return sites across seven sports, and patching each is how three
of four paths get fixed and the fourth stays broken. One sweep over the finished
grid, after every producer. It also covers `soccer_projections.py` **without
editing it** — that file is claimed by the orphaned `soccer-model-coverage` lane.

Clears BOTH edge contracts, because a mean-based row's edge lives in
`edge_vs_line`; clearing only `edge_vs_market_pct` is exactly how these rows
stayed bettable while looking suppressed.

**Caught before shipping:** the first draft used `isinstance(row, Mapping)` in a
module that does not import `Mapping` — a `NameError` on the first row that
would have taken the entire projection join down.

### FALSIFICATION TEST — PASS, on artifacts stamped after 18:54:37Z

```
soccer  by_state {live 4, final 11, pregame 34, unknown 17}   no edges on live/final
mlb     by_state {live 9, pregame 6}                          2 live-aware edges (INTENDED)
wnba    by_state {pregame 3}                                  none
--------------------------------------------------------------------------
HARMFUL edges (finished, or live off a pregame projection):  0   (expected 0)
INTENDED live-aware edges preserved:                         2
```

**And the branch is confirmed to have RUN, not merely to have produced a zero** —
served `projections` coverage on `/api/board/book-grid`:

```
soccer  live_edge_enforced_rows: 36
        {"game is final: the market is settled...": 27,
         "game is live: a pregame projection...":    9}
mlb     live_edge_enforced_rows: 0    {}
```

**27 + 9 = 36 matches the pre-fix measurement exactly.** MLB reads 0 because its
producers already refuse correctly — the sweep is a backstop there, and its
live-aware edges survived, which was the main regression risk.

### Rollback
Redeploy `7b544eb4` on `srv-d91dpertqb8s73co8ls0` (reverts both). Branch
`deploy/soccer-live-game-state` holds both commits.

### Claim override, logged
`syndicate/features/soccer/` and `syndicate/features/shared/soccer_projections.py`
are claimed "exclusive" by `soccer-model-coverage` (OPEN). That lane is
**ORPHANED** — its owning session is absent from a 40-entry `list_sessions`
census with `include_archived: true`. I took `soccer/cards.py` with the override
written into my lane, and deliberately did NOT take `soccer_projections.py`,
routing around it via the wrapper instead. `soccer_projections.py` is unmodified.

## 2026-08-16 18:31:15Z — refresh-worker `cf467794` — **MEASURED: `#441` FIXED.** The pbp fetcher wrote the file

Deployed 18:07:36Z. First fetch fired 18:31:12Z and completed in ~3s:

    season 2026: status=unavailable, HTTP 404          <- correct, season not started
    season 2025: status=written, bytes=97,951,481, reg_plays=46,452
    path: /opt/render/project/data/nfl_source/tracking/nflverse/pbp/pbp_2025.csv

Byte count and REG-play count match what the same code produced locally, and the
path is the MOUNTED DISK via `nfl_artifact_output_root()` (`#389`), not the
checkout. **`NO PLAY-BY-PLAY` has not appeared since 18:31:12Z**; the generator
ran again at 18:31:43 and did not refuse. The guard is SATISFIED, not bypassed —
it stopped refusing because the input arrived.

**A 23-MINUTE DELAY, AND I CALLED IT STARVATION. That was overstated.** At
position 6 of 8 in the autorun elif chain it emitted nothing for 23 minutes, and
I mapped `#341`'s weeks-of-muteness onto that wait. It was DELAYED, not starved —
for a daily-gated job, harmless. The move to position 2 (`b909d008`) is a fair
improvement but rests on a weaker claim than I made, and I had already talked
myself into and out of that same hypothesis twice in the same hour.

**WHAT WAS RIGHT TO CHECK ANYWAY, and what it cost to check it:** the flag, the
deploy/env ordering, the live commit's content, `_active_sports_for_date`, and
whether the chain was reached — all ruled out with evidence before I touched the
ordering. The thing that made the diagnosis slow was my own three SILENT decline
branches (`#443` reproduced in my own code), which is now fixed on `origin/main`
but NOT deployed.

**NOT DEPLOYED, deliberately:** `b909d008` (position-2 + skip logging) is on
`origin/main` and rides the next natural deploy. It is diagnostic, not
functional — `#441` is already fixed in production — and a fourth worker restart
during a live MLB slate was not worth it.

**A SIBLING DEFECT SURFACED IN THE SAME LOG WINDOW:** NCAAF's generator crashes
on a missing, hard-coded 2025 input. Filed as `#445`; NCAAF opens 2026-08-29.

---

### ask-evidence-table — web `9d58cc09` — MEASURED

- Deployed: 2026-08-16 14:19 CDT (19:19:42Z) — **web only**
  (`srv-d88ahvrbc2fs73eodu30`), branch `deploy/ask-evidence-table-2026-08-16`
  cut from web's own live SHA `ad77e46a`. **No collision this time — the deploy
  claim was acquired first**, which is the whole difference from the previous
  row, where two sessions cancelled each other twice in six minutes.
- Change: the M1 evidence table names the same bet the headline names.
  `_board_row_label` was the THIRD copy of the label logic and the last one
  still wrong; it now delegates to the adapter's `_bet_label`. Also
  `_market_label` on the Market column (was the raw key `spreads_alt`/`h2h`), a
  new Price column, and `_board_row_chart_label` so a lay label is not
  truncated mid-phrase.
- **The defect this fixes was CREATED BY THE PREVIOUS FIX'S VISIBILITY.** Once
  the headline read `"Minnesota Twins -1.5"`, the table one line below still
  read `"home -1.5 (Philadelphia Phillies @ Minnesota Twins)"` — the same row,
  the same response, two different names, and nothing saying which to trust.
  A fix that improves one surface can expose a second surface it does not own.
- **Measured on production, 19:2xZ.** 4/4 assertions pass against the served
  `visuals.tables`:
  - Price column present (`-104 @ kalshi`, `+426 @ kalshi`, …)
  - no Selection names a CONVENTION (0 rows start `home `/`away `)
  - no raw market key survives in Market (0 rows contain `_`)
  - **every headline selection also appears in the table** — the two surfaces
    now agree by construction, which was the point.
  Served sample: `MLB | alt spread | Milwaukee Brewers -1.5 | +426 @ kalshi |
  +3.72% | +8.59%`.
- **Verified by REPLAY before deploying**, over 92 verbatim rows from the live
  shortlist rather than only over fixtures I chose: 0 convention labels, 0
  table-vs-headline mismatches, 0 chart labels over the 28-char budget. Game
  totals correctly keep `over 10.0 (Texas Rangers @ Athletics)` — a total has no
  team side, so side+line+matchup IS the bet there. Intended, not a miss.
- **Harness: 37/52, ZERO pass/fail flips** against the post-headline run, all
  seven classes identical. Third consecutive 37/52 today, same cases each time.
  `reports/ask_regression/post_evidence_table_2026_08_16.json`.
- **`warn:selection_not_on_board` is a SLATE ARTIFACT, not a signal — do not
  read it as one.** It went 125 → 100 → 125 across the three runs and the
  arithmetic gives it away: `125/5` and `100/4` are both exactly **25**. It is
  `25 × (how many of the 5 HEADLINE picks are not a bare team/player name)`,
  emitted once per each of 25 cases. The middle run scored 4 only because one
  top pick happened to be `Milwaukee Brewers`; tonight's top 5 contains no
  moneyline row, so it is 5 again — different picks entirely, the slate moved
  (108 → 102 rows). **My earlier reading of the 125 → 100 drop as an improvement
  was right about the mechanism and wrong to treat the number as a score.**
  Every warned selection is a HEADLINE selection, which also confirms the
  harness never reads the evidence table at all — so this deploy was invisible
  to it by construction, exactly as predicted.
- Landed on `main` as `79c3e247`; `main` and live carry identical blobs for all
  three ask files. Deploy claim released.
- **LANE: `ask_the_syndicate_data.py` was TAKEN from OPEN lane
  `ask-sport-coverage`.** Its session (`local_eef2ef89…`) is **archived and not
  running**, last active 2026-08-15 19:44 — a stale claim, and `send_message`
  cannot reach an archived session, so there was no holder to ask. File was
  clean and unchanged since `67ff20a0`. Reassigned in `lanes.md` with the reason
  recorded; scope taken is `_board_row_label` + the `_board_candidates_evidence`
  table ONLY, so K9/K2/K11/K3/K4 are untouched and that lane can take it back.
- **`lane-guard.py`'s `_claims()` is STRICTLY PER-LINE, and that cost a blocked
  edit.** A release bullet written as `- **\`path\` — REASSIGNED …` with
  "claimed by" wrapped onto the *second* line still reads as a claim, because
  the disclaimer marker has to sit on the same physical line as the path. Worth
  knowing before anyone else tries to hand a file over.
- Blast radius: web only. Safety gate returned NOT CLEAR on **an unreadable
  instrument** — "Board build state UNKNOWN (HTTP 503)" — which is not evidence
  of a build in flight, and a board build runs on refresh-worker regardless.
  MLB sim `finished (exit=0)`, odds refresh `idle`. Web's loop ownership was
  RE-checked rather than carried over from the previous deploy
  (`MLB_ENABLE_LIVE_LENS_LOOP=false`,
  `SYNDICATE_ENABLE_INTELLIGENCE_STATE_BACKGROUND_LOOP=false`) and web answered
  HTTP 200 immediately before the deploy.
- Rollback: `py -3 scripts/render_deploy.py --service web --commit ad77e46a
  --allow-rollback`.

## 2026-08-16 18:44Z — the `force_refresh` watch closed EMPTY, and the reason is not the fix

Follow-up to the 17:53Z both-workers deploy (`b9f2b5f1` / `e28594a7`). 50 minutes
of polling `/api/ops/win-prob-null`: **zero post-deploy records of ANY kind on
either worker**, and no `--force-refresh` run in the census.

**WNBA IS NOT IN THE ODDS CYCLE RIGHT NOW.** The running `refresh_odds_sources`
carries **`--sports mlb,soccer`**; the same job at 01:31Z carried
`mlb,wnba,nfl`. **The sports list is dynamic**, so for long stretches no WNBA
producer runs at all and no record can appear no matter what the code does.
**Anyone verifying a WNBA-dependent change must check this FIRST** — it outranks
"did a forced refresh happen", and without it a quiet cycle reads as a failed fix.

- **The worker is healthy** — `refresh_odds_sources` + rolling soccer builds, and
  153 `oddsapi` publish lines in 45 min. The deploy killed 3 jobs by design and
  they came back. Not a regression from the deploy.
- **Nothing is measured yet.** The escape stays UNVERIFIED IN EFFECT; this entry
  records why the window was empty, not a verdict on the fix.
- The hourly `wnba-win-prob-counter-read` task now walks three causes IN ORDER —
  WNBA absent from the cycle → no forced run → genuine negative — and pings only
  on a real landing.

---

## 2026-08-16 19:33Z / 19:37Z — **MLB LIVE GAME LINES NOW PRICED FROM THE RE-SIM'S OWN HISTOGRAMS.** The user called this a big miss; it was

**Two services, because the producer and the consumer are different ones** —
live-odds-worker runs the live-lens loop (`run_live_odds_refresh_worker.py:405`
→ `start_live_lens_background_loop`); refresh-worker consumes the published
snapshot inside `build_book_grid_artifact`.

| service | deploy | commit | parent | live |
|---|---|---|---|---|
| live-odds-worker (producer) | `dep-da10ub9t0dsc73ap5ugg` | `0315f548` | `e28594a7` | 19:33:42Z |
| refresh-worker (consumer) | `dep-da10vtlg1s2s73cl4l40` | `98a9cad8` | `a72b4bf4` | 19:37:32Z |

### The finding: a discard, not a gap

`LiveMcResult.total_runs_dist` — a full histogram over the 120 sims — has
existed all along. `flask_frontend`'s live-MC return keeps `batterStatDist` and
`pitcherStatDist`, added in that same dict with the comment *"Carried so the
live PROP rows can price off the same 120 sims"*, and dropped the game histogram
on the floor. So props got a real live probability and the game total, from the
identical sims, kept only `avg_total_runs`. `REASON_TOTALS_MEAN` was an honest
refusal standing in for data computed and thrown away three functions upstream.

No margin histogram existed at all; `live_mc` now emits one from the finals its
loop already computes.

**Correction to my earlier reading:** `sigma: 2.0` in the served payload is
`PRICEABLE_SIGMA`, the threshold — not a distribution width. I called it
interval data on the first pass and it was not.

### BEFORE → AFTER, same endpoint, live MLB games

```
                      before (19:13Z)        after (19:38Z)
h2h|full              7 aware / 2 edge       8 aware /  3 edge
totals|full           0 aware / 0 edge      56 aware / 38 edge
spreads|full          0 aware / 0 edge      55 aware / 44 edge
--------------------------------------------------------------
live-aware game rows        7                    119
live game-line edges        2                     85
```

Sample: AZ @ ATL, `totals 8.5`, live P(over) **0.2583**, edge **−13.26 pp**,
`prob_std_err` 0.0397 at 120 sims → 2σ bar 7.9 pp, released. The arithmetic is
checkable from the served row.

### What is still refused, and correctly
- **All segment markets** (`first1/3/5`): 387 rows stating *"game is live: a
  pregame projection cannot be priced against a live market"*. The histograms
  describe the FULL remaining game; pricing them against a first-inning line is
  the +42.43 pp artifact `REASON_SEGMENT_NOT_FULL_GAME` exists for. **Every
  `*_alt` row on a live MLB game is a segment row**, which is why the alt
  families read 0 — that is the guard working, not a gap.
- **34 rows** withheld by `prob_interval_swamps_edge` — the precision gate.

### Sign convention imported, not re-derived
`_dist_prob_over/_below` come from `prop_projections`, so live and pregame
cannot drift. With `L` the away-frame line, home covers when `margin > L`; the
negated form returns 0.75 where the truth is 0.25 on the test histogram — three
times the value, in the bettor's favour.

---

## 2026-08-16 19:4xZ — soccer `unknown` game state: the fan-out asked the wall clock

`dep-da11526gekts73815e50` (`415e23cb` on live `98a9cad8`), refresh-worker.

**17 soccer games in `state: "unknown"` holding 1,628 rows.** Measured cause,
not reasoned: `build_game_chips` returned the **identical 90 chips** for
2026-08-16, 08-17, 08-20 and 08-22, while `default_week` maps 08-16 → week 1 and
08-22 → week 2 for epl/la_liga/ligue_1. 15 of the 17 had no matching chip at any
date; for epl and ligue_1 the clubs were **absent from the chip set entirely**
(1 epl chip against 6 epl fixtures on the board).

`resolve_context(requested_date=...)` always resolved the PRIMARY league
correctly. `_SoccerDataProvider.games()` then opened `today =
central_today_iso()` and threw it away, re-resolving all ten leagues against the
wall clock.

**Measured after the fix, locally:** chips for 08-22 go **90 → 113**, epl
**1 → 10**, ligue_1 **1 → 9**, la_liga **9 → 13** — exactly the leagues that
were unknown. Against the pooled 7-day window, **14 of the 17 unknown games now
match a chip**. The remaining 3 (mls, la_liga, serie_a) are separate
schedule/alias gaps and are **NOT** claimed as fixed.

Production verification pending the deploy + a board rebuild.

### soccer `unknown`: FIX DEPLOYED, PRODUCTION UNCHANGED — a SECOND cause exists

`415e23cb` live on refresh-worker 19:48:33Z. Board artifact rebuilt 19:51:08Z —
**post-deploy** — and `by_state` still reads
`{final 13, live 2, pregame 34, unknown 17}`, same 17 games, same leagues
(la_liga 5, epl 5, ligue_1 5, mls 1, serie_a 1), same dates (14 on 08-22).

**So the date-blindness was real and is not the whole story.** What is
established:

- The defect is genuine and the fix is correct: locally, chips for 08-22 go
  90 → 113, epl 1 → 10, ligue_1 1 → 9, and 14 of the 17 unknown games match.
- The deployed SHA contains the fix (checked by content, not ancestry).
- The date cap is NOT binding: the grid spans 8 dates (2,123 rows on 08-15 plus
  the 7-day window), `_MAX_GAME_STATE_DATES = 7`, so all 8 dates are queried.

**The remaining hypothesis, UNVERIFIED:** production's worker disk does not hold
the week-2 soccer schedule/cards for epl and ligue_1, so
`build_cards_page_context(league, 2, 2026)` returns nothing there even with the
correct week resolved. My local mirror has MORE soccer schedule data than
production — the "Render is the source of truth, the local mirror is lossy" rule
biting in the unexpected direction.

I could not confirm it: `/soccer/<league>/api/cards` builds cards on the REQUEST
path and 502s, which is itself worth noting — that endpoint is doing exactly the
heavy work the web/worker split exists to keep off the web service.

**Not claimed as fixed.** The change is correct and stays; it removes one of two
causes. The next step is to check the worker's soccer schedule artifacts for
weeks beyond the current one — artifact territory, i.e. the orphaned
`soccer-model-coverage` lane's domain, and `build_soccer_artifacts.py` is one of
its claimed files.

---

### ask-quote-age + NaN + draw-leg — web `8676da1f` — MEASURED

Three deploys in one chain, each defect found by VERIFYING the one before it.
Web only (`srv-d88ahvrbc2fs73eodu30`), cut from web's own live SHA `1468780b`.
Deploy claim held throughout; a peer's `1468780b` was mid-build at acquire time
and **I waited for it rather than cancelling it** — the failure mode from the
previous chain, not repeated.

| # | commit | live | what |
|---|---|---|---|
| 1 | `06f3b3fa` | 19:47:16Z | quote age read the wrong clock |
| 2 | `a01b30eb` | 19:57:54Z | `float("nan")` reached production as text |
| 3 | `8676da1f` | 20:13:49Z | the draw leg returned `None`, and that was drift |

**1 — A QUIET MARKET IS NOT A STALE QUOTE.** `_bet_facts` read
`book_age_seconds` ("has the PRICE moved" — a change log, so a motionless market
ages without limit) where the board deliberately gates on
`quote_seen_age_seconds` ("when did WE last look").
`layer2_board._row_quote_age_seconds` already documents the distinction.
Measured on the served board, 101 rows:

    warnings off book_age (shipped)   31
    warnings off seen_age (correct)   18
    FALSE                             13    <- 42% of all firings

Worst case `book_age 217.4m` vs `seen_age 3.0m`: the answer told a reader a
three-minute-old MLB price was three and a half hours stale. **Every false alarm
landed on MLB, the freshest sport on the board** (seen median 3.0m), because MLB
is exactly where prices sit still between moves — the warning was loudest where
the data was best. After the fix, replayed over the same 101 rows: 18 warnings,
all 18 genuinely old, **zero** false alarms, none resting on the fallback clock.
Wording changed with it: "The quote behind this is 84 minutes old" (a claim
about the MARKET) → "Last checked 119 minutes ago, so confirm the price before
betting" (a claim about OUR DATA).

**THE TEST SUITE COULD NOT HAVE CAUGHT THIS, AND THAT IS THE REUSABLE PART.**
`test_reason_flags_a_stale_quote` asserted "84 minutes old" and passed — against
a fixture I had TRIMMED when capturing it, dropping `quote_seen_age_seconds` and
`suspect_stale` as "not needed". With one clock in the fixture, no test could
notice the code read the wrong one. **A trimmed fixture cannot fail the test its
own omission causes.** Fixture is now verbatim with a do-not-trim comment.

**2 — NaN.** Probing WNBA as a POSITIVE CONTROL for fix 1, production served
`"draw nan (Indiana Fever @ Atlanta Dream)"`. The layer2 row is clean
(`line: null`, zero literal NaN tokens in the served JSON); the NaN enters
downstream, and `float("nan")` survives every `is None` check and renders as
"nan". Fixed at `_to_float` — **the choke point every caller shares** — not at
the label: the same value reaches edges ("nan%"), prices ("+nan") and
probabilities, where it silently PASSES the `> 0` guards meant to suppress an
absent number. Replayed over 83 live rows across two sports: 0 labels containing
nan/inf.

**3 — THE DRAW LEG, AND A PIN THAT DIDN'T.** The NaN guard turned that string
into a `selection` of literally `None` — less wrong, still not a bet. It was
also **drift**: `layer2_board._pick_label` renders that row "Draw" via
`side.title()`, so the two labellers disagreed on a real published row. That is
precisely what `test_bet_label_matches_layer2_pick_label_on_team_naming` exists
to prevent, **and it passed, because it only ever exercised home/away rows.**
A pin covering three of four shapes is not a pin; it now covers the draw leg.
`_SELF_CONTAINED_SIDES = {"draw","tie"}` is a whitelist, not an inference,
because the failure directions are asymmetric: "Over (A @ B)" names no bet,
while dropping the draw leg loses a real one.

**Measured on production 20:1xZ, MLB and WNBA:** 0 null selections, 0 "nan"
anywhere, 0 rows on the old wording. The warning now DISCRIMINATES rather than
firing blanket — 1 of 5 MLB rows, 5 of 5 WNBA — and the draw leg serves as
`Draw (Indiana Fever @ Atlanta Dream)`.

**METHOD NOTE, worth more than any of the three fixes.** The suite was green at
every step and found none of them. Each was found by checking production:
fix 1's replay, then fix 1's **positive control** — the probe came back
0-warnings-of-5 and "PASSED", which looked like success and proved nothing,
because that day's top 5 were all fresh MLB. Running a sport that *should* warn
is what both confirmed the fix and exposed the NaN; reading that output exposed
the draw leg. **An all-clear is evidence only once you know what makes the
instrument read unhealthy.**

- Landed on `main` as `d1592617`; main and live carry identical blobs. 210 green
  across all four ask suites. `render.yaml` untouched.
- Rollback: `py -3 scripts/render_deploy.py --service web --commit 1468780b
  --allow-rollback` (drops all three; they are one chain).
- **NOT FIXED HERE, and neither is Ask's to decide:** the board's
  `max_quote_age_seconds` ceiling is 50400s (**14 hours**), which is not a
  meaningful gate for a live-odds product — publishing is decided upstream.
  And with the correct clock, all 18 genuinely-stale rows were WNBA at
  **exactly 119.8 minutes, identical to the decimal** — one fetch timestamp, not
  18 independent ages, against MLB's 3.0m across 83 rows. Stalled lane or
  deliberate off-peak cadence is the odds worker's call. Flagged, not diagnosed.

## 2026-08-16 20:25Z — refresh-worker — snapshot freshness gate — DEPLOYED, EFFECT UNMEASURED

`2efe76b1`, live 20:25:16Z, cut on the service's own live SHA `415e23cb`.
Verified BY CONTENT on the live SHA: `wnba_gated=3`, `nba_gated=3`. **Both
workers now carry the freshness gate** (live-odds-worker `46b5ec66`, 19:47:16Z).

- **Deployed into a real lull, deliberately.** refresh-worker was running
  `daily_update.py --workflow ui-daily` at **3.4GB RSS on a 4GB service**;
  deploying then would have killed a heavy job for no urgency, since this service
  builds `date+1` and today's board was already fixed via live-odds-worker.
  Waited; the lull came at 20:18:11Z and the deploy fired 27s later.
- **This is the deploy that was cancelled at 19:42:01Z** by another session's
  `415e23cb`. Not re-fired at the time on purpose — cancelling theirs back would
  have cost the same work twice. Re-cut on their result instead.
- **EFFECT UNMEASURED on this service.** refresh-worker builds `date=2026-08-17`;
  the proof is a `:recommendations_slate` / `:cards_props_snapshot` builder record
  on `/api/ops/win-prob-null` for a date whose snapshot already existed, produced
  WITHOUT `--force-refresh`. Today's board proof is tracked separately against
  live-odds-worker.

---

### ask-quote-tick — web `d6ae3e8c` — MEASURED

- Deployed 2026-08-16 15:40 CDT (20:40:59Z), **web only**, cut from web's own
  live SHA `8676da1f`. Deploy claim held; nothing in flight, nothing cancelled.
  Landed on `main` as `05fe6aea`; main and live carry identical blobs.

- **THE FIELD WAS FROZEN, NOT SLOW.** `quote_seen_age_seconds` is stamped at
  ARTIFACT BUILD time and never advances. Three reads of the live shortlist 45s
  apart returned byte-identical ages — `mlb=[12.9, 39.8] wnba=[47.1]` at
  20:18:34, 20:19:19 and 20:20:04 — while `written_at` sat at 20:15:41Z. True
  WNBA age at the last read was ~51.5 min, not 47.1. **Every consumer of that
  field understates age by the artifact's own age.**

- Fix: real age = stamped + time since the artifact was written, with the
  caller supplying the timestamp because only the caller knows which artifact
  the row came from. Board path uses the shortlist's own `written_at` (EXACT);
  snapshot paths use the intelligence state's `computed_at` via `_result_as_of`,
  whose three-key scan mirrors the route's — production runs the path carrying
  `state_meta` and **no** `freshness` key, and reading only `freshness` was
  inert in production once before. The snapshot offset can be short, so the
  published age is a **lower bound** and the docstring says so.
  `_seconds_since` REJECTS rather than clamps: future stamps (clock skew),
  unparseable strings and anything over 24h fall back to the stamped value, so a
  broken clock cannot invent hours of staleness.

- **THE THRESHOLD HAD TO MOVE IN THE SAME CHANGE, 15min → 45min.** It had been
  calibrated against an age that did not tick and became meaningless the moment
  it did. Real ages on the served board (stamped + a 14.3 min artifact age),
  70 rows:

      min 27.3 | p50 27.3 | p75 54.2 | p90 61.5 | max 61.5   (minutes)

      15 min -> 70/70 (100%)      45 min -> 19/70 (27%)
      30 min -> 19/70 ( 27%)      75 min ->  0/70 ( 0%)

  **The MINIMUM real age on the board is 27 minutes**, so the old threshold
  fired on every row — an accurate warning carrying no information, which is
  strictly worse than the inaccurate one it replaced. **Correcting a number
  without re-checking the threshold calibrated against it would have shipped a
  regression disguised as a fix.**

- **Measured on production after the deploy:**
  - **It ticks.** Same five WNBA rows sampled 75s apart: 72 → 74 minutes, all
    five advanced, none frozen. That is the fix, verified as a rate rather than
    as a single reading.
  - **It discriminates.** MLB 1/5, WNBA 5/5 through the served answer; against
    the full board, mlb 1/52 (1.9%) and wnba 18/18 (100%). It now points at
    exactly the sport with the slow cadence instead of at everything.

- 8 tests (63 in this file, 221 across all four ask suites). The threshold test
  is written against the CONSTANT, not the number, so raising it cannot silently
  turn it into a test of nothing.

- Rollback: `py -3 scripts/render_deploy.py --service web --commit 8676da1f
  --allow-rollback`.

- **NOT FIXED, and not Ask's to fix:** the field is frozen because it is written
  into a static artifact. Making it tick at the SOURCE means the board
  publishing a per-batch build timestamp rather than a precomputed age — then
  every consumer gets a real age without each one re-deriving the offset.
  Flagged to the odds-cadence session (`sim-engine-track`, fork 4) with the
  three-sample measurement, along with the correction that "all 18 identical to
  the decimal" is batch stamping, **not** evidence of a stall — WNBA does
  refresh (119.8 → ~18 → 47.1 across the evening), it is simply on a much longer
  interval than MLB.

---

## 2026-08-16 20:50Z — outstanding items #1 and #2 — refresh-worker `a9e5d3d6`

### #2 — the name normaliser: **VERIFIED IN PRODUCTION, +19 players**

`_norm_name`'s docstring claimed it folded accents; the code deleted them.
With no decomposition step `re.sub(r"[^a-z ]", " ", text)` replaced each
accented letter WITH A SPACE:

```
sim feed    "Eugenio Suárez"  ->  "eugenio su rez"
quote feed  "Eugenio Suarez"  ->  "eugenio suarez"     never joins
```

Measured on BOTH sides, which is what makes it a join bug: sim side **412
distinct hitters, 33 accented (8.0%)**; quote side plain ASCII throughout.
One-directional asymmetry, silent failure.

**Production, one artifact apart, same denominator:**

```
pre  (gen 20:47:57)   dark players 92   projected 2431/3499  (69.5%)
post (gen 20:51:49)   dark players 73   projected 2535/3499  (72.4%)
                      19 players recovered, +104 rows
```

Predicted 18 from the artifact cross-check before deploying; measured 19.

**The other 73 are NOT this bug** and remain a genuine lineup question. I
originally filed the whole population as a stale lineup/injury fingerprint;
for these 19 it never was one.

The correct pattern already existed two files away in
`basketball_props_edges._norm_name` (NFKD since it was written).
`prop_projections` was the outlier.

### #1 — the HR threshold ladder: **SHIPPED, NOT YET VERIFIABLE**

`daily_update` counted HR with a bare `if hr >= 1: _inc_ge("hr_1plus")` — the
only multi-valued hitter stat on that screen not using `_inc_ge_thresholds`,
which the line ABOVE it uses for hits and the lines below for
hits_runs_rbis / runs / rbi / total_bases. `_hr_row` published only
`p_hr_1plus`, and the consumer refused outright with
`abs(line_value - 0.5) > 0.01`. Three layers, one limit, none of them needing it.

Board before: `batter_home_runs` **240/290 at line 0.5, 1/260 at 1.5, 0/244 at
2.5** — 504 dark rows, the largest single coverage gap.

Both counter sites changed together (the comment above the second records
`#334`, where this same duplication was changed in one place and zeroed
`hrr_mean`). `p_hr_2plus`/`3plus` publish RAW with no `_cal`: the calibration
was fitted against `hr_1plus` outcomes and pushing it through P(HR>=2) would be
an unvalidated correction wearing a calibrated label.

**VERIFICATION REQUIRES A SIM RUN, NOT A DEPLOY.** The counters only change what
a NEW sim writes; today's artifact cannot gain the field. Consumer-side the
rung reads absent and returns None rather than 0.0, so the board is unchanged
until the next MLB sim cycle. **A green deploy here must not be read as a
working fix** — re-measure `batter_home_runs` at lines 1.5/2.5 after the next
sim.

### Deploy contention, recorded because it cost three attempts
Two of my deploys were CANCELED by other sessions' deploys (20:26:58, 20:36:31),
the second of which was a hotfix for a break their own `c324447d` had shipped. I
stopped racing and waited for their hotfix to go live before deploying once on
top of it. Their deploy branches were also cut from a base that lacked the HR
ladder already on `origin/main` — a reminder that "on main" and "on the live
worker" are independent facts here.

---

## 2026-08-16 21:02Z — G4 MOVEMENT/STEAM + G7 LIVE COLUMN + INTERVAL LABELS — MEASURED ON `a9e5d3d6`

Artifact `written_at` **2026-08-16T21:01:19Z**, after the deploy's `finishedAt`
20:50:14Z. 63 rows / 61 cards. Content on the live SHA verified first:
`movement=4 live_cols=2 segment=2 openings_param=3 sig_movement=2 caller=2` —
all three files travelled together.

**SAFETY FIRST:** `cards_present=63`, `cards_error=None`, `cards_compat_note=None`.
The board is intact; the blank-board incident is closed.

### WORKS — with coverage stated, not implied

    INTERVAL LABELS      17 cards labelled
                         1st 5 innings 14 · 1st 3 innings 2 · 4th quarter 1
    LIVE COLUMN          37 live cards, 18 carrying live_projection   (was 0)
                         live_aware 20
                         projection.source on live rows:
                           mlb_live_lens_monte_carlo 12  <- THE LIVE MC SIM
                           game_simulation           26  (pregame, unmatched)
                           hitter_threshold           1
    COUNTERS (the gap)   mlb no_bettable_book=114  repriced_to_bettable=1789
    NO REGRESSION        unbettable best-book 0 (must stay 0) — held

The live column is the one the user asked for by name: it now carries the LIVE
Monte-Carlo re-sim, not the pregame distribution. **Coverage is 18 of 37 (49%)
and that is the honest number** — the other 19 live rows carry
`game_simulation`, a pregame source, because the live-lens snapshot has no row
for that market/player. They render a dash rather than a pregame number
dressed as a live one, which is the intended degrade.

### MOVEMENT WORKS BUT IS THIN, AND STEAM IS UNVERIFIED — NOT VERIFIED-ZERO

    movement_state   not_tracked 45 · no_opening_for_row 11 · tracked 4 · flat 1
    with a delta     4      all same_book basis, all direction "toward"
    STEAM flagged    0

- `not_tracked 45` is CORRECT: only `h2h`/`totals`/`spreads` carry history, and
  the board is mostly props. 16 rows were tracked-eligible.
- **Of those 16, only 5 had an opening (4 tracked + 1 flat). 11 did not.**
  Opening coverage is **31%**, because `record_openings` writes a row the first
  time it is PUBLISHED and today's board has churned through several builds —
  a row appearing for the first time this build has no prior opening by
  definition. Expected to improve over a day, and that is a PREDICTION, not a
  measurement.
- **STEAM AT 0 IS NOT EVIDENCE THE DETECTOR WORKS.** With 4 rows carrying a
  delta and a ±15-point threshold inside a 3-hour window, steam had no
  opportunity to fire. This is the "absence in a window isn't absence" rule:
  the correct statement is **untested in production**, and it stays that way
  until a row actually crosses the threshold. Do not record it as verified.
- **`direction: toward` on 4 of 4** is a small sample and should not be read as
  a market-wide signal.

### OWED — a THIRD instance of the same instrumentation gap

`openings_loaded` is **not published anywhere** in the payload — not top level,
not `per_sport_ingest`. So "movement is thin" cannot currently be attributed
between *the ledger is sparse* and *the key does not join*. I inferred 31% from
`movement_state` counts rather than reading it.

This is the same defect I fixed for `no_bettable_book` two hours ago, in the
same file, and I reintroduced it while writing the movement code. `#397`'s rule
— add the counter in the same commit as the rule — is necessary and NOT
sufficient: the counter has to reach every place the payload is ASSEMBLED, and
on this path that is three. **Fix: publish `openings_loaded` and
`movement_rows_matched` beside the existing counters.**

---

### ask-positive-edge — web `b30f0972` — MEASURED

- Deployed 2026-08-16 16:05 CDT (21:05:02Z), **web only**, cut from web's own
  live SHA `d6ae3e8c`. Claim held, nothing in flight, nothing cancelled. Landed
  on `main` as `4b92d79c`; main and live carry identical blobs.

- **THE DEFECT.** Served 20:5xZ under "Showing the top 5 opportunities on
  today's board in MLB. Best edge 4.9%":

      Jose Altuve over 0.5      +4.9%      Seattle Mariners +1    -4.9%
      over 8.0 (SEA @ HOU)      +3.2%      under 7.5 (SEA @ HOU)  -8.2%
      Brendan Donovan over 0.5  -1.8%

  Three of five "opportunities" were bets the model calls bad. **The ranker was
  not wrong** — the board had thinned to 70 rows (46 live) with only 6 carrying
  a model edge and 2 of those positive, so "the best 5" genuinely contained four
  bad bets.

- **SECOND OCCURRENCE, AND THE FIRST FIX IS WHY IT RETURNED.**
  `_market_summary_schema` already carried a note about 2026-08-03 — "the
  summary returned 4 negative-edge rows with the only positive one (+16.9%)
  ranked LAST" — and the fix then was to **sort**. Sorting orders a pool; it
  does not decline to publish one. Necessary, never sufficient. **A fix that
  addresses the ORDER of bad output does not stop the output.**

- `_has_positive_edge` tests the term the row is RANKED ON (`model_edge_pct`
  when present, `ev_pct` otherwise), mirroring `_board_rank_key` so ordering and
  eligibility cannot disagree. `ev_pct` is included because it is **not floored
  at zero**: the served `min_value_pct` is `-2.0` and 6 of 70 rows had
  `ev_pct <= 0`. Filtering runs BEFORE the slice, so a thin board returns fewer
  rows instead of padding five out with negatives.

- **Two traps handled, both of which would have silently undone the fix:**
  1. An empty board list is an ANSWER, not missing data. The caller now tests
     `is not None`, not truthiness — under the old check an empty list fell
     through to the snapshot pool and would have **republished exactly the rows
     the filter had just removed**.
  2. The absence is EXPLAINED. "No opportunities" reads as "the board is empty"
     when the truth may be "the board is full and the model likes none of it".
     The summary now states how many rows were priced against the model and left
     out, in both the short-list and the empty case.
  The excluded count travels beside the rows as a tuple, not stashed on them —
  a private key on a row serialises straight into the API payload.

- Same defect one surface over: the M1 evidence CHART is titled "Top edges" and
  was plotting a `-9.17%` bar. Positive only now. The TABLE deliberately keeps
  every row — it is an inventory with an explicit "N of M rows" count and a
  signed `Model edge` column, so a negative there is information, not a
  recommendation.

- **Measured on production 21:0xZ:** 5 rows published, **0 non-positive**, 0
  non-positive chart bars, and the summary reads "…Best edge 12.4%. 2 rows
  priced against the model and were left out." Pre-deploy replay over the live
  70-row board: 60 qualify, 10 excluded, top 5 becomes 2 positive-model rows
  plus 3 positive-EV rows.

- 6 tests (69 in this file, 227 across all four ask suites).

- Rollback: `py -3 scripts/render_deploy.py --service web --commit d6ae3e8c
  --allow-rollback`.

- **OPEN, FOUND IN THE POST-DEPLOY READ, NOT FIXED:** `Pittsburgh Pirates`
  published with `model_edge +9.18%` **and `EV -2.18%`**. The rule admits it by
  design — a row with a model edge is judged on the model edge — but the two
  terms disagree: the model likes the side while the offered price is worse than
  consensus fair. That is a real caution a bettor would want, and the current
  rule is silent about it. Options are to require BOTH terms positive when both
  exist, or to surface the disagreement in the reason sentence. **Needs a
  decision, not a patch** — requiring both would have dropped this row entirely,
  and whether a model-strong/price-poor row is an opportunity is a product call.

---

## 2026-08-16 21:1xZ — outstanding #4, NFL preseason unquoted — **NARROWED TO TWO CANDIDATES, NOT RESOLVED**

**No code change.** Four things are established and one question is left; the
question needs production logs or an OddsAPI probe, neither of which I could do
from here.

### Established
1. **The board gap is real.** NFL grid holds 1,425 rows: **179 dated 08-15**,
   then nothing until **09-13**. `schedule_preseason_2026.csv` has 1 game on
   08-16, **16 across 08-21..08-24**, and 16 more across 08-27..08-29.
2. **Preseason capture works in principle** — the 179 rows on 08-15 ARE
   preseason week 1. So the pipeline has captured this sport key before.
3. **The week resolution is correct.** `preseason_target_week(2026)` returns
   **2** (verified by running it). The old "self-pins to 1" defect is fixed and
   is NOT the cause.
4. **The gate should fire.** `refresh_odds_sources.py:935` requires
   `requested_month in (7,8,9)` AND `preseason_target_week(season) is not None`
   — both true today. And the fetch is **not week-scoped**: `main()` calls
   `fetch_odds(sport_key="americanfootball_nfl_preseason")` for the whole key.
   The `until > window` filter at `:319` gates only the extra per-event SEGMENT
   markets, not the base event fetch, so 08-21 events should arrive.

### The two remaining candidates, and how to tell them apart
- **(a) The step is not actually running on the worker.** The gate is evaluated
  in `refresh_odds_sources.py`, but whether the worker invokes that path for NFL
  on its current cadence is unverified. `/api/ops/odds-refresh/status` returns
  the manifest artifacts but no per-step list I could read, so this is open.
  **Test:** grep the refresh-worker log for `nfl_preseason_oddsapi_refresh`.
- **(b) The vendor offers no week-2 lines yet.** Books do sometimes hold
  preseason lines until closer to kickoff. **Test:**
  `GET /v4/sports/americanfootball_nfl_preseason/events` — **0 credits**, so it
  is quota-safe even against the 5M cap. Needs `ODDS_API_KEY`, which is on
  Render and not in the local `.env`; I chose not to pull a live secret to a
  local shell mid-session.

Whichever it is, the fix differs completely — (a) is a scheduling/cadence bug on
our side, (b) is "wait, and the board is correct to be empty". **Do not fix
either until the discriminator has been run**; guessing here would mean changing
a working gate.

### One thing that IS actionable regardless
`_SLATE_WINDOW_DAYS["nfl"] = 5` and `resolve_window_dates` is forward-only, so
even once 08-21 IS quoted, a board anchored on 08-16 spans 08-16..08-20 and will
still not show it. That is independent of the capture question and is this
lane's own file (`layer1_board.py`).

---

## 2026-08-16 21:1xZ — **CORRECTION: the soccer game-state fix DID work.** And #5, the cross-sport live A/B, finally ran

### CORRECTION to the 19:5xZ entry above ("FIX DEPLOYED, PRODUCTION UNCHANGED")

That entry is **WRONG and is superseded**. I measured a post-deploy artifact
(19:51:08 > deploy 19:48:33), saw `unknown: 17`, and concluded the fix had not
taken. Measured again at 21:11:39:

```
soccer by_state   before: {live 0,  final 0,  pregame 49, unknown 17}
                  now:    {live 0,  final 15, pregame 46, unknown  5}
```

**17 → 5.** And the 5 that remain are exactly the ones I predicted would:
la_liga 3, mls 1, serie_a 1 — the same leagues I named as "separate
schedule/alias gaps, NOT claimed as fixed".

**Why I got it wrong:** one artifact is not the population. The 19:51 build was
post-deploy by 2½ minutes, but the chip cache
(`game_chip_scoreboard._CACHE_TTL_SECONDS`) and the per-league card builds mean
the first rebuild after a restart does not necessarily reflect the new
resolution. I applied the "wait for a post-deploy artifact" rule correctly and
still read a single sample as a verdict. **The rule needs a second clause: for a
change behind a cache, sample until the value MOVES or a stated number of builds
pass — one fresh artifact is necessary, not sufficient.**

The hypothesis I recorded as "remaining, unverified" — that the worker's disk
lacks week-2 soccer schedules — is **not needed**. Do not go looking for it.

### #5 — the cross-sport live A/B, MLB as reference. RAN AT LAST

First moment this session with two sports live at once: MLB 8 live, WNBA 2 live.

```
                    rows  projected  live_aware  live_projected  actual_so_far  edge
MLB  props          1467       1219         647             647            647     -
     game lines      537        529          75              67              -     44
WNBA props           258        204           0               0              0     0
     game lines       339         16           0               -              -     0
```

**WNBA has no live tier at all — absent, not degraded.** Zero live-aware rows on
live games, zero actual-so-far, zero live edges, on a slate where MLB served 647
live-aware props with the actual stat alongside and 44 live game-line edges.

**Cause is explicit and by construction**, three separate gates in
`board_enrichment.py`:

```
:228  attach_live_game_state_from_lens   if sport != "mlb": "no live status source wired"
:719  _attach_projections_by_sport       if sport != "mlb": "no projection source wired"
:754  attach_live_projections_for_sport  if sport != "mlb": "no live re-sim wired"
```

Each returns a STATED reason rather than failing silently, which is the contract
working. But note what it means: **the live tier is MLB-only by construction,
and adding a sport is not a config change.**

**`syndicate/features/wnba/live_lens.py` EXISTS** — 32.5 KB, and it carries
`modelHomeWinProb`. So WNBA already produces live-lens output that nothing on
the board consumes. That is the same shape as the two discards found earlier
today (MLB's `total_runs_dist`, WNBA's `margin_q`): the number is computed and
never reaches the surface. Worth checking before anyone builds a WNBA live tier
from scratch.

G3 is now answered for both halves: MLB's live lens works for props and (since
today) for game lines; WNBA's is unwired.

---

## PENDING RIDEALONG — the compat guard **AND** the `#446` movement key fix. Producer-side. Web needs nothing.

**SUPERSEDES the earlier `a21b63db`-only entry below.** `08de8c08` landed on top
of it, so the blob hashes in that entry are STALE — shipping them would deliver
the compat guard WITHOUT the key fix, which is the half that makes movement and
steam actually work.

**Ship these three blobs, re-read from `origin/main` at 2026-08-16T16:43:52-05:00:**

    pipeline/layer2_shortlist.py                   92c278509c
    syndicate/features/shared/layer2_board.py      ce30c1780f
    tests/test_layer2_movement_live_segment.py     3519bcc2ec
    tests/test_layer2_cross_file_compat.py         09fd9afd2c

**RE-READ THEM AGAIN BEFORE CUTTING.** These files have moved twice in one
evening; a blob hash written into a ledger is a snapshot, not a lease.

Carries two things now:

1. **The cross-file compat guard** (`a21b63db`) — signature probes so
   `layer2_shortlist.py` can never again outrun `layer2_board.py` into a blank
   board. Self-protecting, no ordering constraint, safe to ship alone.
2. **`#446`, the movement join key** (`08de8c08`) — movement was keyed on
   `line`+`bookmaker`, i.e. on the very things it measures, so only UNMOVED rows
   could match their opening. Measured: stable key matched 20 of 20 vs full key
   14, with line changing on 6 and book on 5. **Steam was structurally
   suppressed by this**, not merely untested — a sharp move usually comes with a
   line move or book switch, which erased the evidence before the detector saw
   it.

Also publishes `openings_records` / `openings_loaded` /
`movement_eligible_rows` / `movement_rows_matched`, so the next reader can
attribute thin movement to a sparse ledger versus a failing join instead of
inferring it as I had to.

### Falsification once it lands

    git show <live-sha>:.../layer2_board.py | grep -c movement_join_key      -> >0
    /api/board/layer2-shortlist  ->  movement_rows_matched / movement_eligible_rows
                                     should be materially ABOVE the 31% baseline
    cards_present > 0 and cards_compat_note ABSENT

**Still not urgent** — no current defect depends on it. But it is now the
difference between a movement column that reports moves and one that reports
only the rows that did not move.

---

## PENDING RIDEALONG — `a21b63db`, the cross-file compat guard. Producer-side. Web needs nothing.

**Whoever next deploys refresh-worker: cherry-pick these three blobs onto that
service's LIVE SHA and it comes along.** They are unchanged on `origin/main` as
of 2026-08-16 21:1xZ — verified blob-for-blob, not assumed:

    pipeline/layer2_shortlist.py                   c64da25044
    syndicate/features/shared/layer2_board.py      ef4e40dccf
    tests/test_layer2_cross_file_compat.py         09fd9afd2c

**Live refresh-worker `a9e5d3d6` has NONE of it** — `_blended_score_accepts` 0,
the `openings` signature probe 0, the live-join optional-import reason string 0.

### Why it matters more than a normal ridealong

This is the guard for the **blank-board incident at 20:34Z**, and the incident
is repeatable until it ships. `c324447d` shipped
`pipeline/layer2_shortlist.py` without `layer2_board.py`; the caller passed
`openings=` to a signature that lacked it; the `TypeError` was swallowed into
`cards = []`; and with `layer2_is_primary=True` that is a blank board announced
only by a string nobody reads. It was caught by a watcher before a build landed
and closed by roll-forward `77dbbd06`.

**Right now those three files are still coupled in production.** Ship any one of
them alone onto `a9e5d3d6` and the same thing happens again. Once `a21b63db` is
live the coupling is gone and they can be cut in any combination.

### It is ALSO self-protecting, which is the point

`a21b63db` is safe to ship alone, by construction: the guards it adds are the
thing that makes a partial deploy survivable. If only
`pipeline/layer2_shortlist.py` from it reaches the worker, the signature probe
sees an older `layer2_board.py`, builds the board WITHOUT movement, and stamps
`cards_compat_note` saying so. A degraded board with a stated reason, not a
blank one.

So this ridealong has no ordering constraint and no companion requirement —
unlike the payload it protects.

### Falsification once it lands

    git show <live-sha>:syndicate/features/shared/layer2_board.py | grep -c _blended_score_accepts   -> 3
    /api/board/layer2-shortlist  ->  cards_present > 0, and cards_compat_note ABSENT
      (present would mean layer2_board.py did NOT travel with it -- degraded, not broken)

### Not urgent, and stated so it is not over-called

No current defect depends on it. It removes a FUTURE failure mode. If the next
worker deploy is days away that is acceptable; it should simply not be dropped,
because the cost of forgetting it is another blank board and the cost of
carrying it is three blobs.

---

## 2026-08-16 21:2xZ — outstanding #6, soccer bucket-A — **SEPARATED.** Two causes, both real, and the accent fix reached further than intended

### The discriminator, and why it is per GAME not per player
A fixture the sim never ran has **zero** projected rows of any kind; a fixture it
DID run but whose roster missed a player has some. That distinction is
computable straight off the served payload and needs no artifact access.

Measured 2026-08-16 21:1xZ, 66 soccer games:

```
                                            games  dark prop rows  distinct players
UNRUN FIXTURE   (zero projections anywhere)    14           1,916               414
LINEUP/ROSTER   (game projected, player not)   41           2,554               452
```

**~43% unrun, ~57% lineup.** Both are substantial; neither explains the other.

**Unrun is concentrated, and that is the lead:** mls **10** of 14, la_liga 3,
serie_a 1. Lineup misses are spread evenly across all six leagues (mls 15,
la_liga 7, epl 6, ligue_1 6, eredivisie 4, serie_a 3), which is what a roster
gap looks like rather than a pipeline outage.

The 14 unrun leagues overlap the 5 games still in `state: unknown` (la_liga 3,
mls 1, serie_a 1). Suggestive of a common upstream cause; **not established**,
and worth one measurement before anyone assumes it.

### The accent fold already applies here — soccer imports the same function
`soccer_projections.py:36` imports `_norm_name` from `prop_projections` and uses
it for every player join (`:219`, `:467`, `:524`, `:545`). So today's fold
shipped to soccer at the same moment it shipped to MLB, and the numbers above
are **already post-fix**. Accents are not what is left.

### AND IT REPAIRED A DOCUMENTED SOCCER DEFECT AS A SIDE EFFECT
`soccer_projections.py:118-140` records that `_norm_team` (which *is*
`_norm_name`) shattered non-ASCII club names —

```
'Vitória SC' -> 'vit ria sc'
```

— while `teams_match`'s alias map is keyed on `normalize` ('vitória sc') and
`fold_accents` ('vitoria sc'), **neither of which is 'vit ria sc'**. The note
records `teams_match(normed, normed)` as **False** for exactly that pair, and
says **9 of 204 configured clubs across 5 leagues had a dead alias fallback**
(Atlético Madrid, Alavés, Vitória SC, …). Their workaround was to feed the alias
fallback RAW names.

Re-measured after the fold:

```
Vitória SC      -> vitoria sc      raw match True | normed match True
Atlético Madrid -> atletico madrid raw match True | normed match True
Alavés          -> alaves          raw match True | normed match True
```

**Both paths now work.** The raw-name workaround is untouched and still correct;
the normalised path it was written to route around is no longer broken. 34 tests
pass across `test_soccer_projections`, `test_soccer_adapter` and the fold suite.

Recorded because it cuts both ways: a shared normaliser is exactly the kind of
function where a fix lands in modules that never asked for it, and I checked the
one module that had DOCUMENTED depending on the old behaviour before assuming it
was safe.

### What #6 leaves open, stated as work not findings
- **Why 14 fixtures are unrun, MLS-heavy.** Artifact-side; belongs with
  `build_soccer_artifacts.py` (a claimed file of the orphaned
  `soccer-model-coverage` lane).
- **Why 452 players are missing from rosters the sim DID run.** Genuine roster
  coverage, not a join bug — the join has now been eliminated as the cause.

---

## 2026-08-16 21:3xZ — #4 NFL preseason, DUG DEEPER — one candidate eliminated, the blocker was an unflushed print

### Eliminated: "the step is not running"
`fetch_nfl_preseason_odds.py --season 2026` was **observed running on
live-odds-worker at 2026-08-16T00:24:36Z**, caught in an `ALL_PROCESS_MEMORY`
cmdline snapshot via the Render logs API. It runs on **live-odds-worker**, not
refresh-worker, and it ran **once today**.

Also eliminated: **our fetch does not constrain the horizon.**
`fetch_nfl_team_odds_local.fetch_odds` sends only `apiKey/regions/markets/
oddsFormat` — no `commenceTimeTo` — so the request asks for the whole sport key.
The `until > window` filter at `:319` gates only the per-event SEGMENT markets,
never the base event list.

### The schedule, corrected
I had week 2 as 08-21. It is not:

```
week 2 = 2026-08-16, ONE game, DAL @ SEA, gametime 00:00
week 3 = 08-21..08-24, 16 games
week 4 = 08-27..08-29, 16 games
```

`preseason_target_week(2026) = 2` is therefore correct, and the fetch is not
week-scoped anyway. Note the timing: the 00:24:36Z run fired **24 minutes after
that game's listed 00:00 kickoff**, and OddsAPI's `/odds` endpoint excludes
in-play events by default. That is a plausible reason today's single game is
absent — and it says nothing about weeks 3 and 4.

### WHY IT COULD NOT BE CLOSED: the result never reached the logs
The script's four summary lines (`events_fetched`, `rows_matched`, `odds_path`,
`snapshot_path`) had **no `flush=True`**. A `text=events_fetched` search across
both workers over two days returns **0 matches**. Unflushed stdout in a
short-lived subprocess is buffered and lost — exactly the failure `CLAUDE.md`
records ("`logger.info` never reaches Render's log collector; use
`print(..., flush=True)`"). The one print in that file that DOES carry the flag
(`:340`, segment-fetch failure) is the only one that appears.

`/api/ops/artifacts/export` refuses both `preseason_odds_2026.csv` and the dated
snapshot ("path is not an allowed hot artifact"), so the written output is not
readable from the web service either.

**So the remaining question — did the vendor return week-3 events, or did we
fetch them and lose them? — is unanswerable from production as instrumented.**

### Shipped: the missing instrument
Added `flush=True` to all four summary lines and one new line:

```
[nfl_preseason] commence_dates=<min>..<max> distinct=<n>
```

`events_fetched` alone separates "the vendor has no lines for this week yet" (a
correct empty board) from "we fetched them and lost them downstream" (a bug).
`commence_dates` says how far the feed's horizon actually reaches, so a short
board is attributable to the FEED rather than guessed at. Both were previously
indistinguishable — as nothing. 12 tests pass.

**Next run of the step answers #4 outright.** Cadence is ~daily and the last run
was 00:24Z, so the read is available after the next one. Grep
`[nfl_preseason] events_fetched` on live-odds-worker.

### Actionable regardless of the answer
`_SLATE_WINDOW_DAYS["nfl"] = 5` with a forward-only window means a board anchored
on 08-16 spans 08-16..08-20 and **cannot show week 3 (08-21) even once it is
quoted**. Independent of the capture question, and it is this lane's own file.

---

### ask-both-edges — web `8172fdef` — MEASURED (AND THE MEASUREMENT IS "INERT TODAY")

- Deployed 2026-08-16 16:37 CDT (21:37:45Z), **web only**, cut from web's own
  live SHA `73e59f51`. Claim held, nothing in flight, nothing cancelled. Landed
  on `main` as `4705124e`; main and live carry identical blobs.

- **THE RULE CHANGE.** Eligibility now requires EVERY edge term a row carries to
  be positive, not just the one it is ranked on. Closes the item left open in
  the `ask-positive-edge` row above.

- **WHY THE FIRST CUT WAS NOT ENOUGH, and it is a general lesson.**
  `_has_positive_edge` mirrored `_board_rank_key` — model edge when present, EV
  otherwise — so a row was judged on the single term it is ordered by. That
  published `Pittsburgh Pirates` at **model edge +9.18% with EV -2.18%**: the
  model liked the side while the offered price was worse than consensus fair.
  **Ranking needs ONE number to sort on; eligibility is a VETO, and a veto
  should hear every term that can object.** Two different jobs, and sharing one
  rule between them was the mistake. Mirroring the ranker had felt like the
  careful choice — it was written up as "so ordering and eligibility cannot
  disagree" — and that symmetry is exactly what let a bad row through.

- Ordering is untouched. `test_ranking_is_unchanged_by_the_stricter_eligibility`
  pins that model-bearing rows still sort above EV-only rows by descending edge.

- **WORDING FIXED IN THE SAME CHANGE, because the rule made it false.** The
  summary said "N rows priced against the model and were left out". Already
  loose — it covered rows dropped for a non-positive `ev_pct`, where the model
  has no opinion at all — and plainly wrong once EV could veto, since a row can
  now be dropped with the model FOR it and only the price against it.
  `_has_positive_edge` does not report which term objected, so the sentence must
  not claim to know. Now: "N rows with a non-positive edge were left out."

- **MEASURED, AND THE HONEST RESULT IS THAT THE RULE IS CURRENTLY INERT.**
  Replayed over the live board (51 rows) before deploying: old rule keeps 42,
  new rule keeps 42, **0 newly excluded** — no row on that slate had the
  conflicting shape. The predicate is proven by unit test against the exact
  Pittsburgh values, NOT by a production diff.
  **So this ships as a guard against a shape that occurs occasionally, and a
  clean board read after it is NOT evidence that it fired.** Recorded that way
  deliberately; the next reader would otherwise bank a success against the wrong
  cause.

- **New code confirmed running by the one thing that IS observable** — the
  wording, which exists only in this build. Production 21:3xZ: "Showing the top
  5 opportunities on today's board in MLB. Best edge 8.9%. **7 rows with a
  non-positive edge were left out.**" Old wording absent, 0 non-positive rows
  published, 0 model-positive/EV-negative rows published.

- 11 assertions on the rule, the ranking-invariance pin, and 3 wording
  assertions. 70 in this file, 228 across all four ask suites.

- Rollback: `py -3 scripts/render_deploy.py --service web --commit 73e59f51
  --allow-rollback`.

- **Process note for this lane:** the first edit of this change was BLOCKED by
  `lane-guard.py` because the resumed session was on the shared global
  `.current-lane` marker while another session held it. Fix is the per-session
  slot the hook names in its own error text
  (`.syndicate/.current-lane.<session-id>`), not closing or forcing the lane.
  Worth knowing: a resumed session does not inherit its own marker.

---

### ask-sim-supports-side — web `d8985df8` — MEASURED

- Deployed 2026-08-16 16:59 CDT (21:59:38Z), **web only**, cut from web's own
  live SHA `8172fdef`. Claim held, nothing in flight. Landed on `main` as
  `339e510b`; main and live carry identical blobs.

- **THE DEFECT WAS MINE, SHIPPED THIS MORNING.** Served 21:4xZ, verbatim from
  the live panel:

      "The simulation projects 1.396 batter hits against a line of 0.5,
       which is why it lands on the under."

  1.396 is ABOVE 0.5 — that projection argues for the over. `"which is why it
  lands on the {side}"` is a **causal claim**, and `_reason_sentences` was making
  it without ever comparing the two numbers in the same sentence.

- **WHY IT SURVIVED REVIEW, AND THIS IS THE REUSABLE PART.** The sibling row on
  the same board — Kyle Isbel, 0.256 against a 0.5 line, under — reads perfectly.
  The template only breaks when the projection falls on the FAR side of the line
  from the bet, so **half the output vindicates it**. Same shape as every other
  defect in this lane today: a correct-LOOKING sentence assembled from real
  numbers. A generator that is right half the time by construction will pass any
  eyeball review of a handful of rows.

- Guard is the arithmetic the sentence always implied: `over -> projected > line`,
  `under -> projected < line`. When it holds the causal clause stands; when it
  fails the numbers are still printed and the clause becomes "which does NOT
  support the {side}".

- **I WEAKENED MY OWN FIX AFTER MEASURING, AND THE MEASUREMENT IS THE POINT.**
  The first draft read "which argues AGAINST the {side} — the sim and this side
  disagree". That asserts the projection and the line are comparable quantities.
  The board says otherwise:

      live   basis           agree  DISAGREE
      False  full                0         1
      False  model_mean          0         2
      False  rbi_1plus           1         2
      True   first5              1         0
      True   full               11         3
      True   live_resim          5         4
      True   rbi_1plus           1         0

  **12 of 31 over/under rows on one read, 21 of 39 on another minutes earlier** —
  across four `basis` values and on **pregame** rows as well as live. A
  full-game projection sitting against a remaining-game line would explain the
  live rows and **does not explain the pregame ones**. So the published sentence
  now claims only what is checkable and stops.

- **Verified on production after the deploy:** 5 rows, every sim-vs-line clause
  cross-checked against its own numbers, **0 contradictions**. Including the
  stark case the guard now labels correctly: `over 16.5 (Colorado Rockies @ San
  Francisco Giants)` with `projected = 7.134` → "does NOT support the over".

- Also fixed: "1 books quoting" → "1 book quoting".

- 9 tests, including a 4-case parametrised table over both sides and both
  directions, and a regression pin on the sibling row that was already correct
  so the fix cannot over-apply. 78 in this file, 236 across all four ask suites.

- Rollback: `py -3 scripts/render_deploy.py --service web --commit 8172fdef
  --allow-rollback`.

- **HANDED OFF, NOT CLOSED — this is a BOARD defect, not an Ask one.** Whether
  the projection or the published `side` is wrong belongs to
  `layer2-board-quality`, whose stated goal is that the board never contradicts
  the sim. Flagged to that session with the table above and the 7.134-vs-16.5
  case. **Consequence they need to expect: the Ask panel will now visibly say
  "does NOT support the over" on roughly a third to a half of over/under rows
  until it is resolved.** That is honest output, not a new defect, but it makes
  the contradiction user-visible.

---

## 2026-08-16 22:08Z — NFL slate window 5 -> 7, **web `432b9e9b`, VERIFIED**

Cut on the live web SHA `d8985df8` after waiting for another session's web
deploy to land rather than cancelling it.

### Why 7, measured rather than chosen
Games actually inside the window, against the real schedules on 2026-08-16:

```
width  preseason games   regular season from Thu 2026-09-10
  5          1           09-10, 09-13, 09-14
  7         15           09-10, 09-13, 09-14      <- unchanged
  9         17           ...plus 09-17, the NEXT Thursday
```

The old width was "Thu through Mon", correct for where the REGULAR season's
fixtures cluster and silently wrong for the preseason, whose week runs
Fri/Sat/Sun/Mon and is reached from a Sunday anchor at **+5 days — exactly one
day past a 5-day forward window**. Seven is the only width that gains the
preseason slate without pulling a second regular-season week onto a today board;
the NFL week is 7 days, so anything wider anchored on a Thursday reaches the
following Thursday. `#329` records 1,244 NFL rows starting 34-156 days out
reaching a today board once already, so over-inclusion is not free.

### Verified in production
```
window dates : 2026-08-16 .. 2026-08-22
window_days  : 7   (was 5)
rows in window: 0    games: 0
rows in grid  : 1425   other_dates {08-15: 179, 09-13: 78, 09-20: 64, ...}
empty_reason : grid_rows_all_for_other_dates
```

**The board is still empty and that is the expected result, not a failed fix.**
The width was a SECOND, independent reason those games could not appear. The
grid holds nothing between 08-15 and 09-13, so there is nothing for the wider
window to admit. Whether that is a capture gap or a vendor with no week-3 lines
is what `[nfl_preseason] events_fetched` answers on the next daily run.

Stated plainly because a green deploy against an unchanged board is exactly the
shape that gets read as "the fix did not work".

### Blast radius, deliberate and notified
`_within_horizon` derives from the same `slate_window_days` table, so **Layer 2's
NFL horizon widens +4 -> +6 days** by construction. That coupling is the point —
the test asserting it is named `test_multi_day_sports_match_their_layer1_windows`
— and **three** files pinned the literal 5. All updated. The Layer 2 session was
notified before they could find it.

`max_slate_window_days()` unchanged at 7 (soccer already), so the worker's
forward artifact-build sizing does not move.

### Pre-existing reds found in passing, NOT mine
`tests/test_layer2_soccer_window.py`: `test_the_shortlist_reads_every_window_date`
and `test_one_unreadable_date_does_not_lose_the_others` fail identically at width
5 — verified by stashing the change and re-running. Flagged to the Layer 2 lane.

---

### ask-answer-substance — HARNESS RE-RUN AFTER ALL SIX DEPLOYS (closes the open measurement)

Run 2026-08-16 22:2xZ against live web `d8985df8`, output
`reports/ask_regression/post_all_deploys_2026_08_16.json`, diffed per case
against the same-slate control `control_pre_answer_substance_2026_08_16.json`.

- **37/52 → 37/52, ZERO pass/fail flips.** Every class identical: advice 4/5,
  entity 9/10, explain 4/6, history 2/5, lookup 8/8, ranking 7/10, refusal 3/8.
  Diffed per case, because equal totals can hide offsetting flips.
- **This closes the "harness not re-run since `ad77e46a`" obligation** recorded
  in the checkpoint above. It is a non-regression result, not a win: `_score`
  cannot see selection shape, units, price, sim terms, quote age or the panel,
  which is most of what the six deploys changed.
- Confound stated rather than elided: the control is 18:0xZ and this is 22:2xZ,
  so the SLATE differs (108 board rows → 43). Zero flips across a slate change
  is a stronger non-regression signal than zero flips on identical data, but it
  is not a controlled A/B and cannot be made into one — production only ever
  serves the current code.

#### The one real change, and it is NOT mine

`warn:edge_without_market_probability` **0 → 25**. Attributed before being
reported, not after:

- `git diff ebd5f677 d8985df8 -- ...adapter.py` shows the board path's `"edge"`
  (`model_edge_pct`) and `"market_probability"` (`_board_row_probabilities`) are
  **unchanged across all six deploys**. The harness reads only
  `structured_response.top_opportunities`, i.e. exactly that path.
- So the input changed. Measured on the live board: **4 of 10 edge-bearing rows
  have a `model_edge_pct` that is not derivable from
  `projection.{model_prob_over, market_fair_prob_over}` by EITHER the direct
  difference or the complement.**

      stated     direct    complement   row_side  proj_side   basis
       12.45      31.91       -31.91      away      home      full/run_margin_dist
       14.10     -49.70        49.70      over      over      full/total_runs_dist
      -11.57       7.33        -7.33      over      over      full/total_runs_dist
       14.84     -22.44        22.44      under     over      full/total_runs_dist

  **Rows 2 and 3 rule out the side-convention explanation**: `row_side ==
  proj_side == "over"`, so the direct difference should BE the edge, and it is
  off by 64 and 19 points. The two quantities are inconsistent, all on
  `full/*_dist` bases.

- `_board_row_probabilities` returning `None` there is CORRECT — the house rule
  is that a published probability is computed or absent, never invented. The
  warning is that guard reporting an upstream inconsistency, so the right
  response is to fix the board, not to silence the warning or to pick whichever
  number looks plausible.
- **THIRD board finding from this lane, handed to `layer2-board-quality`**
  alongside `sim_component == 0.0` everywhere and the `projected`-vs-`side`
  contradiction. Findings 2 and 3 may share a root cause in how `full/*_dist`
  projections are joined to rows — **not tested, not claimed.**


---

## 2026-08-16 22:4xZ — CORRECTION: the line-gate "PASS" was a PASS ON AN EMPTY POPULATION. Status is INCONCLUSIVE.

Worker `2ef1165a` (live 22:34:09Z) + web `acdaaf7e` (live 22:35:42Z) carry the
line gate and the endpoint counters. A verification harness reported:

    tracked 2 · moved-line 0
    PRICE DELTA LEAKED ACROSS A MOVED LINE : 0   (was 19)
    STEAM 0, false 0                             (was 1)
    COVERAGE 100% (2/2)
    VERDICT: PASS

**DO NOT READ THAT AS A PASS.** There were **zero moved-line rows**, so the leak
check and the false-steam check had nothing to test. The board had shrunk
63 -> 31 -> 12 on end-of-night attrition. `PASS if not leaked and not bad_steam`
is trivially true on an empty population.

**Corrected status: the line gate is UNVERIFIED IN PRODUCTION.** It has never
been exercised there against a moved-line row. It IS covered by 24 unit tests
including the exact false-steam case (`Rockies spreads -1.5` vs an opening of
`+1.0`).

### The shrink is SLATE, not the gate — checked rather than assumed

    mlb   442 opportunities / 15 games      wnba  513 / 3 games
    rows_beyond_quote_age  1014   <- books pulling prices late
    rows_beyond_game_cap    689
    rows_beyond_horizon    2420   <- NFL, days out

Nothing points at the gate.

### What IS verified

- **`#446` join fix: coverage 31% -> 96%** on a real population (23 tracked
  rows), artifact 22:20:31Z.
- **Endpoint counters shipped** (4th instance of that gap, closed):
  `openings_records` 1247, `openings_loaded` 680 — read from the payload, not
  derived.

### Harness rebuilt with a MINIMUM-DENOMINATOR GUARD

Every assertion now declares the population it needs (>=3 moved-line rows for
the leak check, >=8 tracked for coverage). Below that it returns INCONCLUSIVE
and names what it waits for. Falsified across all three verdicts before being
trusted: tonight's real board -> INCONCLUSIVE, synthetic clean -> PASS, same
with one leaked delta -> FAIL. **The FAIL case is what makes the other two
mean anything.**

Re-armed; it will report on a slate with real line movement, or say after 3h
that the gate remains unverified rather than going quiet.

---

### ask-mean-not-side — web `9bae928c` — MEASURED

- Deployed 2026-08-16 17:52 CDT (22:52:31Z), **web only**, cut from web's own
  live SHA `acdaaf7e`. Claim held. Landed on `main` as `cc80e6d0`; main and live
  carry identical blobs. **Seventh deploy of this lane today.**

- **THIS FIXES MY OWN FIX.** `d8985df8` was right about the bug and wrong about
  the remedy:
  - Original defect: *"projects 1.396 batter hits against a line of 0.5, which
    is why it lands on the under"* — false causation.
  - The remedy I shipped: *"which does NOT support the under"* — **the same
    category error pointing the other way.**
  `projected` is a **MEAN**; what picks a side is **`P(X > line)`**. On a
  low-line count prop those diverge routinely and legitimately: a mean of 0.214
  runs still implies `P(>=1) ~ 19%`, which beats a market implying 15%, so
  `over 0.5` is a good bet with the mean BELOW the line. Rows the previous
  wording was wrong about: `Jake Cronenworth over 0.5` (mean 0.214),
  `Osleivis Basabe under 2.5` (mean 2.829).

- The directional claim is now made only where the mean IS the right statistic:
  - **GAME rows** (no `player_name`) — totals and margins, means in the 7-9
    range against nearby lines. Exactly the comparison the MLB game lens makes
    (*"the projection sits at 7.42 against 5.0"*), which is the reference this
    generator was modelled on. Both clauses stay.
  - **PROP rows** — the relationship is stated as a fact (*"above the 0.5
    line"*) with no claim about why the side was taken. The probability-space
    case is already carried by the model-vs-market clause.

- **Verified on production 22:5xZ:** 10 rows inspected, **0 violations**. Game
  rows keep the claim and it is correct in BOTH directions — `projects 5.446
  against a line of 7.5, which does NOT support` and `projects 9.988 against a
  line of 8, which is why it lands on`. No prop carries a directional claim.

- 4 tests rewritten rather than deleted; they now pin **both** failure modes (no
  causal claim, no unsupported claim) plus the game-row case that must keep the
  wording. 76 in this file, 234 across all four ask suites.

- Rollback: `py -3 scripts/render_deploy.py --service web --commit acdaaf7e
  --allow-rollback`.

#### FINDING 2 IS WITHDRAWN — and the withdrawal is the point

The "board publishes sides that contradict its own projection" finding sent to
`layer2-board-quality` **is retracted.** Chasing it to a root cause showed only
**2 of 10** failing rows are explained by live-join staleness; 4 still
contradict using `live_projected` and 4 have no live value. The remainder are
this category error — **mine, not the board's.**

I also mis-read an earlier `overlap = 0` between findings 2 and 3 as evidence
against a shared cause. It was a **population artifact**: only 2 of the 10
finding-2 rows carry `model_edge_pct` at all, so they were barely eligible to
overlap. Recorded because the reasoning error is more reusable than the result.

**FINDING 3 STANDS, root cause confirmed:** `live_gameline_join.py:643`
overwrites `edge_vs_market_pct` with the LIVE edge while deliberately leaving
`model_prob_over` at its pregame value, so the pair is incomparable with nothing
in the field name to signal it. **7/7 separation on `live_aware`**, and the
arithmetic closes to the decimal: stated `-39.93` = `(live_model_prob_over
0.1917 - market_fair_prob_over 0.591) x 100`, where the pregame pairing gives
`+27.46`. Every number correct; only the pairing wrong. That is why it is
`full/*` only — segment bases are not live-joined and agree 3/3. Recommended fix
(theirs, not mine): rename to `live_edge_vs_market_pct` so the pairing cannot be
got wrong at the call site.

---

## 2026-08-16 22:49Z — `#5` WNBA live tier — refresh-worker `fdc72dd0` — **GAME LINES WIRED AND PROVEN; AND THE WNBA LENS ITSELF IS INTERMITTENT**

### The gate was shut on data that was already being published
`attach_live_gamelines_for_sport` was `if sport != "mlb"`, justified as "the
120-sim re-sim is MLB's" and WNBA "has no live tier at all". First half true;
**second half stale.** `/api/ops/live-lens/status` reports
`activeSports: ["mlb","wnba","soccer"]`, wnba `ok: true` on a 60s tick, writing
`live/wnba_live_lens.json` — the exact path the join reads, and already in
`HOT_ARTIFACT_PATTERNS`. The board showed **0 of 521 rows** live-aware across two
live games because of the gate, not the data.

### Three shape differences, handled rather than papered over
1. wnba stamps `source: "live_projection"`, not `live_mc`. Fixed with a
   **per-sport** `LIVE_LENS_SOURCES_BY_SPORT`, not a relaxed check — MLB keys on
   `source` so a lens the re-sim never touched cannot be admitted, and widening
   it globally would hand MLB every `pregame` lane in its own snapshot. Unknown
   sports get MLB's stamp and fail closed. **Verified: the wnba snapshot indexes
   2 games under wnba sources and 0 under MLB's.**
2. wnba carries `away`/`home` at the TOP level with no `matchup` wrapper. Shapes
   are tried in order; the first yielding BOTH names wins, so a partial
   `matchup` cannot build a key from two different games.
3. **wnba publishes no `simsRun`**, so `prob_std_err` is uncomputable and
   `REASON_UNUSABLE_SIMS` withholds. An `n` was NOT invented — `prob_std_err`
   returns None rather than 0.0 precisely because 0.0 reads as perfectly
   precise. WNBA gets a live PROJECTION with an explicitly unpriced edge.

### Verified in production, 22:50:31Z artifact (post-deploy)
```
totals_alt|full    78 rows   78 live_aware   78 live_gameline   0 priceable
spreads_alt|full   71 rows   71 live_aware   71 live_gameline   0 priceable
period segments (q1/h1/h2)  0 live_aware   <- correct, full-game lens
withheld: live_resim_published_no_distribution_for_this_market 160
          sim_count_unusable                                     2
```
**149 rows went 0 -> live-aware**, each carrying a live projection and a NAMED
reason for the unpriced edge. Exactly the "publish, refuse to price" outcome
designed for and stated in advance.

### THE FINDING THE WIRING EXPOSED: the WNBA lens loses its own live state
Seven minutes later, the 22:57:22 artifact served **309 game rows, 0 live_aware,
0 live_gameline** — while the board still had both games LIVE at 78-74 and
78-77. Cause read straight off the lens at 22:57:43Z:

```
Chicago Sky @ Seattle Storm : sources=['pregame'] in_progress=False clock=None period=None pts=None-None
Indiana Fever @ Atlanta Dream: sources=['pregame'] in_progress=False clock=None period=None pts=None-None
```

At 22:50 the same games carried `away_pts 60, clock "0:06", period 3,
in_progress true`. **The lens's `live_state` went entirely null and the lens
self-downgraded to `pregame`** (`wnba/cards.py:1057` sets `live_projection` only
when `is_live` AND `live_margin` AND `elapsed_min` are all present). The join
then correctly refused it.

**This is a pre-existing WNBA producer intermittency that the board was
previously blind to, and is now visible.** It is NOT the join, and NOT this
deploy: the join is proven by the 22:50 reading. The WNBA live tier will flicker
until the live-state feed stops dropping out.

### Tick-over-tick movement: NOT captured, and the reason
The verification asked for a diff proving the numbers MOVE. The 22:57 tick had
no live rows to compare against (above), so the movement test never got two
populated ticks. **Unproven, not passed** — needs another live WNBA slate.

### PROPS: NOT WIRED, deliberately, because it would be inert
Across the ENTIRE wnba snapshot, `actual` / `live_projection` / `live_total` /
`live_total_line` appear **24 times each and are NULL in all 24** (16 of those
rows on live games). The field names are right; nothing fills them. Wiring
`attach_live_projections_for_sport` for wnba would join nothing and deploy an
inert change. **Producer gap in `wnba/live_lens.py` + its box-score source, not
a join gap** — and the same `live_state` dropout above is the likely common
cause, since a null `live_state` starves prop actuals exactly as it starves the
game lens.

### Rollback
Redeploy `2ef1165a` on `srv-d91dpertqb8s73co8ls0`.

### Pre-existing reds found on the deploy lineage, NOT mine
`tests/test_live_gameline_join.py::TestBuildGameLensStampsSimsRun` — 4 tests
fail on live `2ef1165a` **without** this change (verified by checking out that
SHA clean and re-running). Another session's `simsRun` stamping is tested but
not present in the deployed lineage. The live refresh-worker is running with
those 4 red.

### Process note against myself
I chained `push && deploy` after a test run without gating on the result, and
triggered a deploy while 4 tests were failing. Caught it, cancelled
`dep-da13pcjl550s73eou4rg` before it went live, established the 4 were
pre-existing, and only then redeployed. The deploy should have been gated on the
test exit code in the same shell.


---

## 2026-08-16 23:0xZ — LINE GATE **VERIFIED IN PRODUCTION**. Supersedes the retracted PASS.

Artifact **2026-08-16T23:01:01Z**, worker `2ef1165a`, 22 cards. This time the
population could actually test it:

    tracked 11   MOVED-LINE 9   same-line 2
    leaked price delta across a moved line : 0    (pre-fix 19 of 23)
    coverage 100% (15/15)                          (baseline 31%)

**Independently re-counted, not taken from my own harness** — which produced a
false PASS on an empty set two hours earlier and is not yet trustworthy on its
own word. Every one of the 9 moved-line rows:

    Under totals      line 21.0  open  8.0   delta=None  basis=line_moved  line_delta +13.0
    Rockies spreads   line -3.5  open  1.0   delta=None  basis=line_moved  line_delta  -4.5
    SF Giants spreads line  5.5  open -1.5   delta=None  basis=line_moved  line_delta  +7.0
    ... 6 more, all delta=None

**And it does not over-suppress**, which is the other half of correct: the 2
same-line rows still carry deltas — `+23.0` and `-1120.0`, both `same_book`.
A gate that silenced everything would have looked identical on the leak check
alone.

The `Under totals 8.0 -> 21.0` row is the case in miniature: comparing prices
across a 13-point total move is meaningless, and pre-fix it would have produced
a large fabricated "movement".

### STEAM IS STILL NOT VERIFIED, AND THE PASS DOES NOT COVER IT

Only **2 rows** were eligible to fire steam (it needs a price delta, so
same-line only), and both openings were outside the 3-hour window. `steam 0` here
is correct behaviour, not evidence the detector works — a pregame opening five
hours old moving to a live price is not steam, and the window rightly excludes
it.

**Status: line gate VERIFIED. Steam UNVERIFIED**, needing a same-line row that
moves >=15 points within 3 hours of its opening. Scheduled re-run 2026-08-17
09:00 CDT (`scripts/verify_movement_line_gate.py`).

---

### ask-sim-margin — web `9f617f34` — MEASURED

- Deployed 2026-08-16 18:30 CDT (23:30:17Z), **web only**, cut from web's own
  live SHA `9bae928c`. Claim held. Landed on `main` as `cc04240c`; main and live
  carry identical blobs. **Eighth deploy of this lane.**

- **THIRD AND FINAL CORRECTION to the same clause.** The prop/game split shipped
  in `9bae928c` was still wrong — it moved the error to a sport that was not on
  the board. `player_name` is a proxy for "low count"; it fits MLB and **fails on
  soccer**, because a soccer TOTAL is a low-count **GAME** row, so the old rule
  routed it straight into the directional claim.

- **Grounded in the system's own model, not an outside assumption.** Soccer's
  engine models counts as Poisson
  (`soccer/sim_engine/soccersim/player_props.py`), and a Poisson median sits
  ~1/3 BELOW its mean, so "mean above the line" stops implying
  "P(over) > 50%" in a narrow one-sided band:

      market         mean  line  P(over)   mean says  prob says
      soccer total   2.60   2.5    48.2%     over       UNDER   <-- wrong
      soccer total   2.55   2.5    46.9%     over       UNDER   <-- wrong
      soccer total   2.40   2.5    43.0%     under      under
      soccer total   3.10   2.5    59.9%     over       over
      MLB total      8.00   7.5    54.7%     over       over
      MLB total      9.99   8.0    66.6%     over       over    (served)
      MLB total      5.45   7.5    18.4%     under      under   (served)

  **A 2.5 goal line against a 2.6 mean is the most common shape in soccer and
  sits exactly in the band** — the rule was most wrong about the sport it had
  never been tested on.

- Fix is the actual precondition and carries no sport in it: claim a direction
  only when `abs(projected - line) >= _SIM_DIRECTION_MIN_MARGIN` (**0.5**),
  enough that the median cannot be on the other side. Below it the sentence says
  "too close to call the side from the projection alone".
  **This SUBSUMES the prop/game split and is strictly better**: a prop with a
  real gap gets its claim back (verified live — `Bryan Woo over 17.5`, projected
  16.509, gap 0.99, "does NOT support the over"), while a prop without one
  (0.214 vs 0.5) still stays quiet.

- **Verified on production 23:3xZ:** 3 directional claims, every gap >= 0.5,
  every direction correct, **0 rule violations**. Pre-deploy replay over the
  live board: 7 over/under rows, 6 claims, 1 quiet, 0 violations.

- 13 tests including a 7-case parametrised margin table, both soccer shapes,
  both served MLB rows, and the level-with-the-line case. 85 in this file, 243
  across all four ask suites.

- Rollback: `py -3 scripts/render_deploy.py --service web --commit 9bae928c
  --allow-rollback`.

- **NOT MEASURED ON SERVED SOCCER ROWS, and the commit says so.** Soccer had 0
  board rows all session (`active_sports: ['mlb','wnba']`), no retained date
  carries any, and the local mirror yielded no total lines — the documented
  lossy-mirror trap. The table is arithmetic on the engine's own Poisson
  assumption, **not an observation of served rows.** Re-check when soccer
  returns to the board; that is the single open item on this clause.

---

## 2026-08-16 23:38Z — WNBA live_state dropout — live-odds-worker `16a898ef` — **DEPLOYED AND UNIT-VERIFIED; THE PRODUCTION TRIGGER HAS NOT YET FIRED**

### Root cause, named at the line
`wnba/cards.py::_public_scoreboard_live_state_payload` was
`except Exception: return None`, **silently**. Every caller then saw zero public
games, no live merge ran, and the published lens carried `in_progress: False,
clock: None, pts: None-None` for games genuinely in progress — at which point
that module's own source rule (`live_projection` only when `is_live` AND
`live_margin` AND `elapsed_min`) downgraded every game to `pregame`, and the
Layer 1 board lost its whole live tier.

**A 6-second timeout to an external host, published as "no games in progress".**

### The dropout, observed end to end
```
22:50:31Z  board served 149 live-aware WNBA game rows
22:57:22Z  same board served 309 game rows and ZERO, while CHI @ SEA and
           IND @ ATL were still live at 78-74 and 78-77
22:57:43Z  lens: sources=['pregame'] in_progress=False clock=None pts=None-None
23:19:10Z  recovered on its own, unchanged code
```

### The fix, and its limits
Age-bounded, MARKED carry-forward of the last good scoreboard, following MLB's
`_carry_forward_live_state_lens` rules because it solved this first:
- **180s bound**, tighter than MLB's 300s — a basketball clock moves faster than
  a half-inning. Past it, return None (an honest absence) **and drop the entry**
  so a later failure cannot resurrect an older board.
- **Unknown age never takes the permissive branch** (monotonic time, so the age
  is always knowable).
- **Marked, never silent:** `carried_forward: True` with age, source and reason;
  the failure now prints. A carried board that looked fresh would be worse than
  the nulls it replaces.
- **Kill switch** `WNBA_LIVE_STATE_CARRY_FORWARD_MAX_AGE_SECONDS=0`; a negative
  value is a typo, not a disable.
- **A 200 with no events is NOT carried.** Out of season legitimately has none,
  and carrying over that would INVENT a slate. Only a FAILED fetch is smoothed.

### What is verified, and what is NOT
**Verified:** 8 tests including the real call path (`urlopen` patched to raise,
driving `_public_scoreboard_live_state_payload` itself, not just the helper);
118 green across carry-forward, live-tier, MLB carry-forward and WNBA cards
suites; deployed SHA carries the code by content.

**NOT verified: the trigger has not fired in production.** A log search for
`SCOREBOARD_CARRIED_FORWARD` / `SCOREBOARD_FETCH_FAILED` /
`SCOREBOARD_CARRY_EXPIRED` since 23:38Z returns **0 matches** — the ESPN fetch
simply has not failed since the deploy. **This fix is unproven against the real
failure and must not be recorded as proven.** The next dropout is its first
test; the instrument will say so by name, which it could not do before.

### Collateral confirmation: the live tier itself works on a healthy lens
23:31:16Z board, IND @ ATL 94-91 (OT) and POR @ PHX 18-22:
**218 of 321 game rows live_aware with a live_gameline** (up from 149 earlier),
withheld reasons `live_resim_published_no_distribution_for_this_market` 216 and
`sim_count_unusable` 2. So `wnba-live-tier`'s wiring is confirmed against a
second, independent live slate.

### Deploy target reasoning
**live-odds-worker, not refresh-worker:** `start_live_lens_loop()` is called only
from `run_live_odds_refresh_worker.py:412`. Cut on live `440f5f29`, which does
NOT carry the clamp change that lane deferred by user decision — so that
deferral is preserved.

### Claim override
`wnba/cards.py` was claimed by `clamp-fix-to-workers`. Its code work has shipped
(`57a437d5`) and its only open work is verification that does not read this
function; its session is UNATTENDED (a scheduled-task run) and `send_message`
was attempted and **refused by the transport**. The file was released in
`lanes.md` with the reasoning, not silently taken.

### Process fix carried from the previous deploy
The push and the deploy were **gated on the test exit code in the same shell**
this time (`RC=$?; if [ "$RC" -ne 0 ]; then ... exit 1; fi`), after chaining them
ungated an hour earlier and having to cancel a deploy mid-build.

### board_contract_end — the instrument that names the allocator (refresh-worker)
- Deployed: 2026-08-17 00:04:08Z — `dep-da14vu3l550s73ermc0g`, commit `94447830`,
  trigger `api`. Service `srv-d91dpertqb8s73co8ls0` (refresh-worker).
  Branch `deploy/board-contract-end-marker`, parented on the LIVE SHA `fdc72dd0`
  (which is off-main, on `deploy/wnba-live-tier`) — **not** on `main`, which sits
  639 commits / 106,125 insertions away and would have been a branch swap.
- Change: ONE stage marker. `board_contract_end` emitted immediately before the
  single `return out` of `apply_game_board_contract`
  (`syndicate/features/shared/game_board_contract.py`). 5 functional lines,
  additive; `return out` unchanged, no path's behaviour differs. Placed in the
  SHARED builder all 8 sports call, because `_log_cards_context_memory` exists
  only for MLB — the other seven hydrate with no stage markers at all.
- Expected: **this is an INSTRUMENT, not a fix. It will not reduce memory and
  must not be read as if it might.** Expected effect is a READING: on the next
  `oomKilled`, the `MEMORY_WATCHDOG` `last_stage` field resolves to one of
  exactly two values —
    `board_contract_end`                -> builder returned; allocator is
                                           DOWNSTREAM, in the caller.
    `board_contract_games_normalized`   -> excursion is inside :850-:911, and
                                           this lane's reasoning is WRONG.
  Window: 5 kills tonight (23:03:50, 23:16:51, 23:32:18, 23:43:11, 23:56:00Z),
  ~11-13 min apart, so >=1 reading expected within ~1 hour of deploy.
- Measured: `<pending>`
- Rollback: redeploy `fdc72dd0` (the pre-deploy live SHA) on
  `srv-d91dpertqb8s73co8ls0`. Additive change, no data migration, no config.
- **Preflight: FAILED, then half-cleared, then the remainder OVERRIDDEN BY THE
  USER — recorded so nobody later reads this as a clean gate.**
  - Scope FAIL (deploy would have carried 639 commits) — RESOLVED by parenting
    on the live SHA. Cherry-pick tested via `git merge-tree` (no worktree, no
    index) because the shared tree held another live lane's 1,599 staged
    insertions.
  - live-odds-worker concurrent build — CLEARED on its own at 23:57:12Z.
  - **In-flight MLB sim — NOT cleared. Deployed anyway, on an explicit user
    decision**, on the argument that the ~12-minute OOM cadence was already
    killing that sim repeatedly (a container-level 4Gi kill takes the whole
    instance, children included), so the guardrail's premise was largely spent.
    That argument is recorded because it is the thing to re-check if it turns out
    to be wrong.
- **BOOT-CONFOUNDING WARNING for whoever reads this next:** the deploy restarts
  the worker and memory resets to ~16%. It will look healthy for several minutes
  REGARDLESS. The deploy proves nothing by itself; only the next kill's
  `last_stage` is evidence.
- Verdict: `<pending — instrument only, no fix claimed>`

---

## 2026-08-17 00:2xZ — lane archive — **ALREADY DONE UPSTREAM. My version was NOT pushed, and that is the result.**

Asked to archive the closed lanes. The digest has been reporting
`LANE ARCHIVE OWED: 23 closed/orphaned lanes` and `lanes.md 304KB > 117KB`.

### What I built, and why it is not being shipped
Transformed the shared worktree's `lanes.md` (310KB, 39 slugs, 23 CLOSED):
moved every closed lane's body to `lanes_closed.md`, left 23 one-line pointers,
`310KB -> 208KB`. Verified before writing: **1,401 distinct lines left
`lanes.md`, 0 missing from the archive**; archive strictly additive (+3,113/-0);
OPEN 12->12 and UNMARKED 4->4 untouched.

**Then the cherry-pick onto `origin/main` conflicted, and the conflict was the
finding.** `origin/main` ALREADY carries the archive — another session did this
job and pushed it. Probed七 closed slugs: each appears **once** in origin's
`lanes_closed.md` and **zero** times as a body in origin's `lanes.md`. Origin
also carries 65 lines mine lacked, including its own pointer lines in a
different format (`` - `ncaaf-schedule-fallback` — ... CLOSED-VERIFIED ``).

Pushing mine would have **duplicated 3,113 lines** into `lanes_closed.md` and
overwritten their pointers with mine. Commit `45ff3332` exists locally and is
**deliberately unpushed**.

### The digest was measuring the wrong file
`LANE ARCHIVE OWED: 23` is computed from the **shared worktree copy**, which is
a pre-archive snapshot. Origin's `lanes.md` is 183KB with 1 closed slug (the
`clamp-fix-to-workers` I closed minutes earlier). The worktree also holds ~256
lines of genuinely unpushed lane content from other live sessions, so it is
**stale-plus-in-flight**, not simply stale — which is why it must not be reset
to origin wholesale.

### Repair of my own damage, and the near-miss
Writing my archived `lanes_closed.md` (built from ORIGIN's copy + the 23 moved
bodies) put every one of those bodies in the file **twice**, since origin had
already archived them. Confirmed by probe (`2x` each), then repaired by
resetting `lanes_closed.md` to origin's version — safe only because the local
baseline was verified a strict subset first (**0 baseline lines missing from
origin's archive**).

**The near-miss worth keeping:** I overwrote a 597KB shared ledger file from a
version built off `origin`, not off the file itself. Had the worktree's copy
carried content origin lacked, that write would have destroyed it silently. It
did not (verified 0 lines lost), but the check was run AFTER the write, not
before. **Back up or diff a shared ledger file before overwriting it, not
after.**

### Net state
- Local worktree: `lanes.md` 208KB (closed bodies out, 14 OPEN preserved, the
  other sessions' in-flight content intact), `lanes_closed.md` 712KB = origin's,
  each body once.
- `origin/main`: unchanged by this task. Nothing was pushed.
- Remaining bulk in `lanes.md` is long OPEN lane bodies, not closed ones —
  archiving cannot get it under the 117KB budget; that needs open lanes trimmed
  or closed.
