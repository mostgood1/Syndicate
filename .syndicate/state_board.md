# state — board

Split out of `state.md` by `scripts/split_state.py`. Bodies are verbatim.
The INDEX of every subject, across every part, is in `state.md`; the
one-subject-one-section rule is global and spans these files.
Same rules as state.md: when a fact changes, EDIT THE LINE.

## [board-freshness] BOARD FRESHNESS AND STALENESS

**THE BOARD HAS TWO INDEPENDENT CAUSES, and fixing one is not enough.**

- **Cause 1 — refusal rate.** 96.7% of board cycles were refused before any work:
  146 `MEMORY_GUARD_ABORT stage=pre_source_state_fingerprint` against 5 completed
  builds. **The guard doing the refusing protects a stage Layer 2 never runs**
  (`_MIN_SAFE_MEMORY_HEADROOM_BYTES`, sized for `build_intelligence_overview`).
  Production's own proof they are independent: on 3 of 5 builds
  `CANDIDATE_POOL_READY count=0` while `LAYER2_SHORTLIST` returned `rows=256` on
  the SAME cycle. `[measured 08-14 14:39Z]`
- **`#387`'s Layer 2 fix is CLOSED-VERIFIED on a full 3h clean window** —
  37 refreshes = 11.9/hour vs 1.7 baseline, longest gap 11.8 min vs 104.7,
  96 `MEMORY_GUARD_ABORT` (so not a boot-confounded quiet period),
  `LAYER2_GUARD_SKIP` 0, zero OOM. All five criteria met. Residual confound
  stated: abort rate 30.8/h vs 48.7/h baseline. `[measured 08-14 19:24Z]`
- **Cause 2 — THE QUOTE INPUT IS NOT MOVING *IN THE PREGAME REGIME ONLY*.** A
  shortlist rebuilt every 5 minutes off a 2-hour-old quote shard is a board that
  LOOKS fresh and is not — **strictly worse than one that is visibly stale,
  because nothing on it says so.** `[measured 08-14 15:1xZ]` **SCOPED 08-15
  02:5xZ: this holds for the empty-slate pregame regime. During a live slate the
  quote input moves every ~1 min and the BOARD REBUILD becomes the binding
  constraint instead — the arrow reverses.** See ODDS CADENCE.
- **QUOTE CHANGE → SERVED UI, END TO END, MEASURED. `[measured 08-15
  02:38–02:58Z, live MLB slate]`** Method:
  `end_to_end = row age_seconds + (server_time − generated_at)`, validated
  against an absolute book timestamp to a 22 s residual — which is what proves
  `age_seconds` is stamped at BUILD time, not at serve time.
  - **Layer 1** (`/api/board/book-grid?sport=mlb`), 15 samples at 60 s over 4
    builds: **min 143 s / p50 451 s / max 698 s** = **2.4 / 7.5 / 11.6 min**.
    Build gaps 10.8 / 5.1 / 4.2 min. Network is not a term (client−server −0.3
    to −0.7 s). **The floor is the board rebuild interval, not the 60 s fetch —
    capture is 6–10× faster than the board can consume it.**
  - **Layer 2** (`/api/board/layer2-shortlist`, which carries its own
    `written_at`): `written_at` **01:53:44Z unchanged for 64+ min**; end-to-end
    3660 → 4022 s (**61 → 67 min**), monotonic, **no rebuild observed**, so this
    is a LOWER BOUND, not a sawtooth. **CONFOUNDED — do not use as a baseline:**
    refresh-worker took three deploys in the preceding 31 min (`ae7318a2`,
    `934b3b81`, `548ded38`, all `#435`). `LAYER2_FAST_REFRESH` since 01:30Z =
    **0** and `MEMORY_GUARD_ABORT` = **0**, so it is NOT the known guard
    refusal — it simply was not running; worker alive and healthy at 02:51Z.
  - **Still unmeasured: a pregame-window end-to-end, and a deploy-free Layer 2
    window.** Both numbers above are live-slate, one sport.
    Full read: `.syndicate/tier5_quote_to_ui_2026-08-14.md`.
- **Layer 1 is NOT dark. `[re-measured 2026-08-16 16:26–16:37Z, lane
  `layer1-board-coverage`]`** The earlier "`count=0` on ~3 of 5 builds" reading
  did NOT reproduce: **4 distinct consecutive MLB builds, all non-zero**, and
  WNBA and soccer non-zero on every one. Same-instant sweep at 16:19:52Z —
  mlb 2,843 rows / 1,941 projected (68.3%), soccer 6,453 / 1,704 (26.4%),
  wnba 872 / 305 (35.0%); nba/nhl/ncaab correctly `no_precomputed_grid_artifact`.
  **Projection coverage does move build to build** (mlb 2,107 → 1,935 projected
  across 16:33:49 → 16:35:06 with `rows` flat at 3,006), so an availability
  claim needs the build stamp, not one read. Program Tier 4.
- **The candidate-pool path serves NEITHER board** and is the real deletion
  candidate. Layer 1 and Layer 2 are **siblings off the shared grid**, not
  sequential — which is the mechanism by which L1 can fail without L2 noticing.

---

## [board-intelligence-engine] BOARD / INTELLIGENCE ENGINE — structural facts, archived — **ARCHIVED 2026-08-19 to `state_archive_2026-08-19.md`, verbatim.**

## [locked-cards-retuned-no-autorun] `locked_cards_retuned` HAS NO AUTOMATIC TRIGGER, ANYWHERE `[measured 2026-08-18]`

- The only builder, `build_season_betting_cards_manifest.py`, is invoked two
  ways and **neither runs on Render**: the routine season-wide path only
  exists inside `daily_update.py` (GHA-only, `scripts/daily_update.ps1`,
  Render never calls it); the single-date backfill inside
  `run_refresh_worker.py` is manually env-var-gated
  (`MLB_BETTING_DAY_BACKFILL_DATE`).
- **The GHA cron itself defaults to backup-only**, not the full pipeline —
  `run_full_pipeline` defaults `false`; its own text calls the full-pipeline
  path a "manual fallback for backfills/recovery."
- Consequence, measured: the pregame odds freeze (`#265`/`#440` Phase 7) is
  fixed and improving (1→11→15 games captured, 08-16→08-18), but
  `season_betting_day_2026_08_17.json` still has exactly 2 games / `ml=1`,
  because nothing ever rebuilds it against the improved freeze. Full trace:
  `docs/ai_context/todo.md` under `#265`.
- **NOT FIXED.** Next step if picked up: decide whether to add a routine,
  feature-flagged autorun (generalizing the existing single-date backfill) or
  fix the GHA default — either is a real, scoped change, neither attempted.

## [board-overview-skipped-for-memory] — VERIFIED 2026-08-27, refresh-worker `277062cd`

**The 8-sport overview was skipped ENTIRELY on every board build in steady
state.** 13:50-14:52Z: 18 consecutive `BOARD_OVERVIEW_READY sports=0`, both
dates. Each preceded by `OVERVIEW_STOPPED_FOR_MEMORY next_sport=mlb
floor=expensive floor_mb=3000 sports_done=0 sports_total=8`.

**`BUILD_SPAN_EXIT stage=build_intelligence_overview elapsed_s=0.0` DOES NOT
MEAN FAST.** It means the guard refused at sport 0 and the loop `break`ed. Read
it together with the `sports=` count or it inverts the diagnosis — a skipped
build looks like a cheap one.

**The expensive floor is unreachable at rest.** headroom = `max - anon`
(4096 - 1297 = 2799, confirmed against the emitted snapshot). Steady-state anon
is 1300-1550MB, so headroom is 2550-2800MB and never reaches the 3000MB floor.
Only 5 of ~40 iterations over 3h08m produced `sports=8`.

**Board cycle period** (`CALLING_COMPUTE` -> `RETURNED_FROM_COMPUTE`):
**~214s** when the overview is skipped, **674-783s** when it runs. Layer 2 is
NOT the cost — `LAYER2_SHORTLIST` publishes every iteration regardless (rows
1323-1330 today) and its tail runs in ~1s. The 460s is
`build_intelligence_overview` (305-366s) + `candidate_collection_with_fallback`
(155-176s).

FIX `6421bf7f` (`break` -> `continue`, plus today+1 throttle default 300 ->
1800s) IS ON MAIN AND **NOT DEPLOYED** — refresh-worker live on `600a753a`.
Production effect is UNOBSERVED. Lane `board-cycle-overview-throughput`.

## [board-overview-fix-verified] — VERIFIED 2026-08-27, refresh-worker

**A memory refusal now skips MLB alone instead of discarding all eight sports.**
`6421bf7f`, live since `b8163ef0` 17:02:59Z, still in on `fb9261b8`. Four paired
readings 18:01-18:58Z: guard fires `OVERVIEW_STOPPED_FOR_MEMORY next_sport=mlb
sports_done=0` at headroom 2775-3020MB and the build returns `sports=7` with MLB
ABSENT and the other seven present. Pre-fix the identical guard line returned
`sports=0` EIGHTEEN times running. Control: the four non-firing iterations read
`sports=8` with `mlb:g=7` present, so the gate in front of MLB is not relaxed.

Today's board went from rebuilt every ~7 min at `sports=0` — never actually
built — to every ~25 min at `sports=7`/`sports=8`. Slower and real.

**THE THROTTLE HALF DID NOT "BUY NOTHING" — IT COST BOARD FRESHNESS, AND I
MISSED IT FOR NINE HOURS `[CORRECTED 2026-08-28 21:4xZ]`.** Raising the code
default 300 -> 1800s starved the THIRD date in a 3-day window. Measured from
the user's own board screenshot and confirmed per date:
```
date         last build     age     candidates
2026-08-28   21:20:24        19m      278
2026-08-29   21:37:15         3m       68
2026-08-30   17:15:20       264m       42   <- sets computed_at
```
`17:15:20Z` is 12:15 PM Central — EXACTLY the "as of" the board displayed at
4:33 PM. `combined_board_window` reports `computed_at` as the OLDEST
contributor's stamp by design, so one starved date drags the whole board's
shown vintage down by 4h24m while today and tomorrow were 19m and 3m fresh.
**MITIGATED:** `SYNDICATE_INTELLIGENCE_BOARD_WINDOW_SLOW_REFRESH_SECONDS=600`
set on refresh-worker (env overrides the 1800 code default; inert until that
service next deploys). `SYNDICATE_INTELLIGENCE_BOARD_WINDOW_DAYS=2` is the
alternative — it drops 08-30 so the board stops claiming a date it is not
maintaining — but that changes coverage and is a user decision.
**THE ERROR:** I optimised a metric I chose (today's SHARE of cycles) and
never checked the metric the user SEES (`computed_at`). Recording it as
"bought nothing" was incomplete — it bought nothing AND cost this. Same
family as the share-of-the-whole rule: measuring the wrong quantity
confidently. ORIGINAL ENTRY FOLLOWS.
~~THE THROTTLE HALF BOUGHT NOTHING and is recorded as such.~~ Default 300 ->
1800s does throttle (future-date builds ~7min -> ~30min) but today's SHARE of
iterations did not move (5/4/1 over 127 min vs a 9/9 baseline — 50% both ways).
The `>=4:1` bar I wrote was unreachable: the board window is THREE dates, and
the overview fix slowed each build 150s -> 534s, so there are fewer builds to
redistribute. The two changes interact; I did not predict it.

**REMAINING LEVER, no lane:** the 534s overview itself — MLB's
`build_cards_page_context` running hydrated on the worker — not the throttle.
### CFBD IS OUT OF QUOTA UNTIL 1 SEPTEMBER — A MONTH, NOT A WINDOW

Measured 2026-08-27 from the 429 itself: `X-CallLimit-Remaining: 0`,
`{"message":"Monthly call quota exceeded."}`. **Monthly cap, so it resets
2026-09-01 — AFTER the 08-29 openers.** Retrying cannot shorten it; polling
sustains it. NCAAF projections therefore CANNOT be regenerated before the
season starts, and the board will serve the 08-19 artifact through opening
weekend.

Consequence for provenance: `profile_source`/`profile_version` are stamped only
by a SUCCESSFUL run, so the live CSV reads `unknown` until September. Until
then the refresh-worker log line below is the only evidence that exists.

Not blocked by this: OddsAPI props/lines (different provider, own budget), the
team and pace snapshots (already built), and the board itself.

### THE PROMOTED NCAAF CALIBRATION ARTIFACT LOADS IN PRODUCTION — CONFIRMED

Read from the Render logs API on refresh-worker, 2026-08-27 21:21:37Z:

    [calibration] ncaaf profile source=artifact version=ncaaf-goal-line-refit-1
                  goal_line_touchdown=True drive_yardage_multiplier=0.95

`source=artifact`, not `default`, with three discriminating fields agreeing —
`goal_line_touchdown` defaults False, `drive_yardage_multiplier` defaults 1.15.
This discharges the confirmation owed since the promotion.

**Those four runs then CRASHED on the 429 and wrote nothing.** They failed
safely: board intact at 51 cards, 0 missing projection values. A ratings-less
artifact written over the good one would have looked exactly like success.

### `header_stats` NOW RENDERS ON THE SHARED RANK BOARD — 21 of 21 ROUTES

`header_stats` is a REQUIRED argument of `build_rank_page_context` (31 call
sites, 23 files) that `shared/rank_board.html` read NOWHERE; it rendered the
optional `summary_panel.summary_stats` instead. Production sweep 2026-08-27
found **14 routes with a full board of cards rendering no slate stats**, and 1
rendering them. It survived because 11 sport-specific templates DO loop over
`header_stats` — load-bearing there, inert on the shared board.

Fixed at the template (`12928720`, live 22:03:52Z) as an `elif`, so a builder
supplying its own `summary_panel` is untouched. After: **21 of 21 rank_board
routes render slate stats.** Verify by counting `feature-summary-pill`, NOT by
grepping panel prose — "on the board" is body text that only appears on a
populated slate and reads as a false negative on most routes out of season.

## [board-compute-attribution] — VERIFIED 2026-08-28, refresh-worker `4805abe5`

**THE BOARD BUILD'S COST IS NAMED. 84% attributed, and every venue/IO
hypothesis is DEAD.** One complete build, `BOARD_BUILD_TIMING wall_s=678.8
cpu_s=664.1 off_cpu_pct=2.2`:

```
build_intelligence_overview          331.09s   49%
candidate_collection_with_fallback   168.40s   25%
layer2_shortlist_build                51.00s    8%
kalshi_odds_refresh                   12.84s
portfolio_commit                       5.38s
pull_hot_artifacts                     1.15s
kalshi_board_join                      0.91s
manifest_odds_history_join             0.31s
candidate_building                     0.01s
                                    --------
named                                571.1s   84%
unattributed                         107.7s   16%
```

**`off_cpu_pct=2.2` — THIS BUILD DID ESSENTIALLY NO WAITING. There is no I/O
win available.** Confirmed twice, independently: the ratio itself, and
`pull_hot_artifacts=1.15s` measured directly.

### THREE HYPOTHESES RETIRED, ALL MINE, ALL WRONG

1. **"The artifact_publisher HTTP pulls are a large part of it."** They are
   **1.15s, ~0.2%**. I had measured ~37s of pull lines by GAP-BETWEEN-LOG-LINES
   earlier and treated that as cost; the span says otherwise.
2. **"The Polymarket join is a credible largest-single-item."** It is
   **0.25s** (`POLYMARKET_BOARD_JOIN elapsed_s=0.25 markets=15303 indexed=7717
   board_rows=1008`). Wrong by three orders of magnitude. Instrumenting it was
   still correct — it was the largest UNMEASURED block and is now RULED OUT
   rather than suspected.
3. **"Compute doubled; suspect venue-loop contention."** The series is 480.6,
   650.9, 778.8, 593.1, 735.5, 865.2, 1058.9, 855.6, 678.8 — and the 865.2s
   build at 00:24Z PREDATES the venue loop. I read two points as a trend.

### WHAT IS ACTUALLY LEFT, and it is where the first measurement pointed

`build_intelligence_overview` (331s) + `candidate_collection_with_fallback`
(168s) = **499s of 679s (73%)**. The overview is MLB's
`build_cards_page_context` running HYDRATED on the worker — named as "the real
work... untouched" by a code comment since 2026-08-07 and still true. **The
next lever is an OPTIMISATION task, not an instrumentation one.** The
measurement work is finished; do not spend more on spans.

The residual 107.7s (16%) is spread across gaps individually too small to
chase.

## [board-window-staleness] — **CAUSE FOUND AND VERIFIED 2026-08-29. It is neither the queue NOR build cost — see `[week-scoped-board-window]`.**

**SYMPTOM, from the user's own board:** `combined_board_window · as of Aug 28,
12:15 PM · 1746 candidates` displayed at 4:33 PM. `computed_at` is the OLDEST
contributing date's stamp BY DESIGN (`read_combined_intelligence_response`), and
that anchoring is load-bearing: `_apply_freshness_recompute` would otherwise
recompute the age to ~0 and hand back `is_fresh: True`. **The number on the board
is TRUE. There is no display bug and no display fix.**

### SUPERSEDED CAUSE — kept visible because it is actionable and WRONG

Recorded 2026-08-28 in `b1f791fd`: *"`_ensure_default_board_window_watched`
re-queues TODAY every loop iteration, UNTHROTTLED, while future dates are
throttled ... ELIGIBILITY WAS NEVER THE CONSTRAINT; SLOT ALLOCATION IS,"* with
"round-robin the pending queue" named as the real fix.

**REFUTED 2026-08-29.** The starvation mechanism is really in the code; it is not
what was happening. `BUILD_SPAN_ENTER stage=pull_hot_artifacts`, refresh-worker,
00:28-03:55Z, `days=2` + `SLOW_REFRESH=600`:

```
00:28  08-28    01:35  08-28    02:31  08-28    03:54  08-28
00:49  08-28    02:07  08-29    03:16  08-29
01:20  08-29
```

The dates ALTERNATE. Allocation is roughly fair. **Do not build the round-robin.**

### ACTUAL CAUSE — build duration

| stage | range (s) |
|---|---|
| `build_intelligence_overview` | 257 – **1158** |
| `candidate_collection_with_fallback` | 119 – **656** |
| layer2 + kalshi + portfolio | ~100 – 400 |

**900–2000s per build.** Two dates alternating fairly => each date rebuilt every
30–66 min => the older one sets `computed_at`. That is the whole symptom.

**WHY THE THREE CONFIG ATTEMPTS COULD NOT HAVE WORKED.** All three moved slot
ALLOCATION, which was never binding. A knob that redistributes a fixed amount of
work between two dates cannot reduce the age of the older one -- it can only
choose WHICH date is stale. That is why `SLOW_REFRESH=600` made `08-29` worse
(3m -> 84m) and why `days=2` was absorbed by today (36 min post-boot, two builds,
both `08-28`). Three spellings of the same non-fix.

1. `SLOW_REFRESH_SECONDS` code default 300 -> 1800 (mine). Starved the third date
   to 264m. Recorded as "bought nothing" having measured only today's SHARE of
   cycles, never `computed_at`.
2. `SLOW_REFRESH_SECONDS=600` env override. **Made it WORSE.**
3. `BOARD_WINDOW_DAYS=2`. Dropped `08-30` correctly; today absorbed the slot.

### CHECKED AND EXONERATED

The hydrated-overview rate limit (`SYNDICATE_HYDRATED_OVERVIEW_MIN_REBUILD_SEC=900`)
reads `cache_entries=0` on every pass and fired ZERO times in 4 hours -- but
retention is `max(10, 900)` = 900s and the per-date gap is 1220–1307s, so the
cache is CORRECTLY empty. `#336`'s own comment already predicted this. Raising the
interval would make it bind only by serving an overview older than the gap:
trading a measured number for a hidden one. **NOT DONE, deliberately.**

### CURRENT ENV ON refresh-worker (all set by me, all live)

`SYNDICATE_INTELLIGENCE_BOARD_WINDOW_DAYS=2`,
`SYNDICATE_INTELLIGENCE_BOARD_WINDOW_SLOW_REFRESH_SECONDS=600`. Code default for
the latter is 1800 and is ALSO mine — env currently wins. `DAYS=1` remains
available and is NOT set: it makes `computed_at` current by NARROWING WHAT THE
BOARD CLAIMS, which is not what was asked for.

### THE FIX — and BOTH earlier answers in this section are superseded

**MEASURED on the served payload, 2026-08-29 18:13:02Z:**

```
computed_at 2026-08-28T23:03:31Z   age 68,971 s (19.2 h)   newest_age 300 s
by_date  2026-08-29  153 candidates, 12 sports
         2026-08-30   42 candidates, ["serie a"]   <- 19.2h old, REAL ROWS
         2026-08-31    0 candidates                <- ignored (#603)
```

`2026-08-30` has ONLY soccer fixtures (`SCHEDULE_RECONCILE_CHECK
scheduled_games=0`). `_supported_intelligence_dates()` covers FIVE DAILY SPORTS
ONLY, so that date is never eligible to BUILD, while the read side correctly
shows its 42 real rows — whose 19.2h stamp then sets `computed_at`.

**BUILD SPEED CANNOT MOVE THIS**, which is why nothing did: three config changes
AND two verified performance fixes (`lstat` 7,955 -> absent; soccer bracket
363s -> 80.5s, full board build 1005s vs a 900-2000s baseline) all left it at 19.2h.

`#603` (landed `a1d7ad4e`, verified firing) removed EMPTY dates from the age —
08-31 no longer counts. 08-30 is not empty, so it still does, correctly.

**The remaining fix is scoped, not built: `[week-scoped-board-window]` below.**
### KNOWN, NOT ACTIONED — USER DECISION

`#385` records that refilling the legacy pool costs **~580s per build and
contributes 0 rows** when Layer 2 owns the board, gated on
`board_l2a_fallback_enabled()` (`SYNDICATE_BOARD_L2A_ENABLED`, default OFF).
Turning it on is a PRODUCT decision: the board template reads 70 fields per row
and ~40 have no source on an L2-A row, so cards render leaner. Surfaced, not flipped.

### SEPARATELY MEASURED — worth someone's lane

Soccer generates 151 candidates per build and loses ALL of them at
`CANDIDATE_SLATE_FILTER` (`SPORT_LOST_ALL_CANDIDATES sport=soccer no_match=28
chips=351 -- alias gap, NOT a date exclusion`), while Polymarket reports
`no_candidates|soccer|alternate_totals_corners: 222` and `no_match|soccer|h2h: 93`.
Soccer is currently the most expensive sport in the build AND contributes zero
board rows.

## [week-scoped-board-window] SCOPED, NOT BUILT `[2026-08-29]`

**THE REMAINING CAUSE OF BOARD STALENESS, after everything else today was fixed
and did not fix it.**

### Evidence, served payload 18:13:02Z

```
state_meta: computed_at 2026-08-28T23:03:31Z   age 68,971 s (19.2 h)
            newest_age 300 s   artifacts_dated 4   status stale
            source combined_board_window+layer2_fallback
by_date:    2026-08-29  153 candidates, 12 sports
            2026-08-30   42 candidates, ["serie a"]   <- 19.2h old, REAL ROWS
            2026-08-31    0 candidates                <- correctly ignored (#603)
```

### The chain

1. `2026-08-30` has ONLY soccer fixtures. `SCHEDULE_RECONCILE_CHECK date=2026-08-30
   scheduled_games=0` for MLB; `BETTING_PAYLOAD_READ exists=False`.
2. `_supported_intelligence_dates()` unions FIVE DAILY LOADERS ONLY --
   `mlb_available_daily_summary_dates`, `nba_/wnba_/ncaab_/nhl_available_dates`.
   **No soccer, no NFL, no NCAAF.**
3. `_default_board_window_dates()` = today UNION (window INTERSECT supported), so a
   soccer-only date is NEVER ELIGIBLE TO BUILD.
4. The read side deliberately does not filter, so it still shows tomorrow's 42
   Serie A rows -- which are real, so `#603`'s row-gate correctly passes them.
5. Their 19.2h stamp sets `computed_at`. **No build-speed work can ever move this.**

The code already names the gap: *"soccer's available-date probe is per-league --
conflating either into this rolling day-window would be the wrong shape for them.
Tracked as a separate follow-up (`_default_week_scoped_dates`, not yet implemented)."*

### The primitives ALREADY EXIST -- this is not new plumbing

- `soccer.sources.available_dates(league)` -> reads `display_prediction_dates.json`
  under `_api_root(league)`. One JSON per league, 10 leagues in `LEAGUE_DISPLAY_NAMES`.
- `soccer.sources.active_leagues_for_date(date)` -> `league_active_for_date` per league.
- Path resolution for those reads is no longer a cost: the `source_roots` cache
  landed today (`lstat` 7,955 -> absent).

### Proposed change (v1, SOCCER ONLY)

```
_week_scoped_supported_dates()  -> union of available_dates(league) over leagues
_default_board_window_dates()   -> today UNION (window INTERSECT (daily UNION week_scoped))
```

**NFL/NCAAF DELIBERATELY OUT OF v1.** They are week-scoped, not date-scoped; mapping
week -> dates is a different transform and the existing comment is right that
bolting it on here is the wrong shape. Soccer is date-indexed already, so it fits
the rolling window as-is.

### THE PART THAT MUST NOT BE SKIPPED: this makes today WORSE unless throttled

Each eligible date costs a FULL BOARD BUILD. Measured 2026-08-29 17:32-17:49,
post-fix: **1005 s wall** (24.72 pull + 177.34 overview + 282.67 collect + 137.04
layer2 + 106.34 kalshi + 122.62 portfolio). Today is currently the ONLY eligible
date and rebuilds every ~21 min. Add tomorrow and they alternate: **~42 min each.**

So the naive widening trades a 19.2h displayed age for a 42-min one AND HALVES
TODAY'S REFRESH RATE. `SYNDICATE_INTELLIGENCE_BOARD_WINDOW_SLOW_REFRESH_SECONDS`
exists precisely for this and already applies to non-today dates -- **verify it
BINDS before widening**, because this lane has already shipped three tuning changes
to that knob that did nothing (see `[board-window-staleness]`).

> **PARTLY SUPERSEDED 2026-09-03 — "IT BINDS" IS WRONG (see the correction
> below the block). The COST-MODEL half stands and was measured again.**
> `[lane board-window-throttle-binds]` Measured per-date `BUILD_SPAN_ENTER`
> intervals, 744-minute window on refresh-worker:
>
>     2026-09-02  today, unthrottled   39 builds   median gap 15.8 min
>     2026-09-03  tomorrow, throttled   7 builds   median gap 38.8 min
>
> Tomorrow sits ABOVE the 30-min floor; today runs free. **"They alternate at
> ~42 min each" did NOT happen — today is 15.8 min, not 42.** The throttle SHEDS
> the extra date's turns instead of alternating, so **widening does not halve
> today's refresh rate.** The paragraph above is kept because its CAUTION was
> right and produced this measurement; only its arithmetic is superseded.
>
> Method note: a first pass read a 12-line log tail and concluded tomorrow
> out-built today 3:1. Over the full span it is 39 to 7 the other way — a tail
> read as a population, which is the standing "a rate, not a count" rule.

> **CORRECTION 2026-09-03 — THE THROTTLE DOES NOT BIND, AND THE FLOOR IT WAS
> JUDGED AGAINST WAS NEVER IN EFFECT.** `[lane board-throttle-600s-remeasure]`
>
> The block above reasons against a 30-minute floor. The code is
> `max(30, _env_int(SYNDICATE_INTELLIGENCE_BOARD_WINDOW_SLOW_REFRESH_SECONDS, 1800))`
> and the LIVE value on refresh-worker is **`600`**, read from the Render API.
>
> Re-measured from `BUILD_SPAN_ENTER stage=pull_hot_artifacts`, refresh-worker,
> covered window **2026-09-02T12:42:56Z → 2026-09-03T02:16:34Z (13.6 h)**,
> 341 matching lines over 5 pages:
>
>     date        n   min      p25      median    max        (gap seconds)
>     2026-09-02  46  128.1    806.9     940.8    3,484.7    <- today, no floor
>     2026-09-03   5  1,331.2  2,329.3   3,854.1  28,518.5   <- non-today
>
> **THE FLOOR NEVER CLIPS.** Of the non-today gaps: **0 below 600 s, and 0 in
> [600, 750) s** — no pile at the floor. The smallest gap tomorrow ever achieved
> is **1,331.2 s = 2.2x the floor**. A constraint that is never the binding one
> is not "binding"; a gap sitting ABOVE a floor is not evidence the floor caused
> it.
>
> **AND THE 1800 s FLOOR WAS DEMONSTRABLY NOT IN EFFECT**, which removes the
> objection that the env value is only confirmed for the process that booted at
> 01:10Z: a **1,331.2 s (22.2 min) gap CANNOT EXIST under an 1800 s floor**. So
> the effective floor across the whole measured window was <= 1,331 s,
> independently corroborating the API's `600`.
>
> **WHAT ACTUALLY SPACES THE BUILDS IS SERIALISATION.** Today's median gap
> 940.8 s against the ~1005 s measured full-board-build cost is a ratio of
> **0.94** — the worker builds today essentially BACK-TO-BACK, and non-today
> dates get whatever turns are left (median 64 min, worst 7.9 h).
>
> **WHAT STILL STANDS:** the cost model *"add tomorrow and they alternate at
> ~42 min each"* is still wrong. Today measured **15.7 min median here**, against
> 15.8 min in the superseded block — two independent windows agreeing. Widening
> did not halve today's refresh rate.
>
> Sample caveat, stated rather than buried: non-today n=5 gaps. The post-deploy
> window where `600` is directly confirmed holds **n=0** non-today builds (1.1 h),
> so this rests on the full window plus the <=1,331 s inference above, not on the
> post-deploy segment.

### Risks

1. **Today regresses** if the throttle does not bind. Measured earlier today with 2
   eligible dates: per-date period 30-66 min.

   > **STILL LIVE 2026-09-03 — the throttle does NOT bind, so this risk is NOT
   > discharged.** `[lane board-throttle-600s-remeasure]` Today is currently
   > protected only because the window holds TWO dates on a saturated worker, not
   > because anything sheds load. The soccer index offers **8 forward days** (see
   > risk 2), and with the floor at `600` they would compete freely.
   > **The mechanism exists and is simply set too low to fire** — raise
   > `SYNDICATE_INTELLIGENCE_BOARD_WINDOW_SLOW_REFRESH_SECONDS` above the
   > serialisation period as part of any widening, and re-measure that it clips.

   > **RAISED AND INJECTED 2026-09-03.** `[lane board-window-floor-raise]` Env
   > `600` -> `1800` (single-key endpoint; absent from `render.yaml`), injected by
   > a SAME-SHA redeploy of `f84eb21b` (live 03:08:48Z) so no code shipped with
   > it. Then `33b181ee` (live 04:20:45Z) made the floor OBSERVABLE for the first
   > time: `BOARD_WINDOW_QUEUE_GATED` / `BOARD_WINDOW_QUEUED`, both branches, so
   > the gate has a denominator.
   >
   > **The mechanism is demonstrated; the RATE is not measured yet.** A non-today
   > enqueue was GATED at `elapsed_s=725` against `floor_s=1800` — under the old
   > `600` floor that same enqueue would have been ADMITTED. n=2, twelve minutes
   > after a cold start: that is a mechanism, NOT a clip rate.
   >
   > Owed: `py -3 scripts/measure_board_window_clip_rate.py` (committed, carries
   > its own baseline). **A clip rate of 0 is a LEGITIMATE RESULT** meaning the
   > queue coalesces and the floor is the wrong lever — not a failed measurement.
2. **`display_prediction_dates.json` staleness** -- if that artifact lags, the same
   class of bug recurs one level down. WHO WRITES IT AND HOW OFTEN IS UNVERIFIED.

   > **DISCHARGED 2026-09-02 — THE INDEX IS NOT STALE. IT LEADS.**
   > `[lane soccer-date-index-staleness]` Read live off production disk,
   > `/api/ops/artifacts/export?pattern=soccer_source/*/api/display_prediction_dates.json`,
   > `count=10 truncated=False` — all ten leagues, nothing elided.
   >
   > **WHO WRITES IT:** `build_soccer_artifacts.py:696` calls `_update_date_index`
   > at the END of a league+date build, right after the recommendations file.
   > ACCUMULATE-ONLY — read `dates`, add `iso_date`, write sorted + `latest`.
   > Nothing ever removes a date.
   >
   > **HOW OFTEN:** the soccer weekly autorun, live on refresh-worker —
   > `SYNDICATE_ENABLE_SOCCER_WEEKLY_REFRESH_AUTORUN=true`,
   > `SYNDICATE_SOCCER_WEEKLY_REFRESH_INTERVAL_SECONDS=14400` (4 h),
   > `SYNDICATE_SOCCER_SIM_HORIZON_DAYS=7`. So every 4 hours across a SEVEN-DAY
   > forward horizon, which is exactly why the index leads rather than lags.
   >
   > **MY HYPOTHESIS WAS REFUTED.** I predicted the index records dates that were
   > BUILT and so could never hold tomorrow, making the widening INERT. Wrong:
   > 9 of 10 leagues carry a future date, out to **+7 days**, and NO league's max
   > is before today. The builder runs a horizon, not just today.
   >
   > Per-day league counts, measured (central dates):
   >
   >     today +0  2026-09-02   2 leagues    +3  2026-09-05   7 leagues
   >           +1  2026-09-03   3 leagues    +4  2026-09-06   7 leagues
   >           +2  2026-09-04   7 leagues    +5..+7           3,1,3 leagues
   >
   > **The widening has real input:** a 2-day window yields both `2026-09-02` and
   > `2026-09-03`; 8 forward days carry at least one league. Note TODAY IS THE
   > THIN DAY (2 leagues) while +2..+4 carry 7 each — an argument FOR widening,
   > since most soccer activity sits two to four days out.
   >
   > Residual, NOT a blocker: the index is accumulate-only and never pruned
   > (MLS reaches back to 2026-07-22), so anything intersecting it must be
   > window-bounded. `#631`'s formula already intersects the board window.

   > **CAUTION RAISED ON RISK 1 BY THE SAME READ.** The live
   > `SYNDICATE_INTELLIGENCE_BOARD_WINDOW_SLOW_REFRESH_SECONDS` on refresh-worker
   > is **`600`**, not the code default `1800` the throttle analysis above reasons
   > against (`max(30, _env_int(KEY, 1800))`). Read from the Render API
   > 2026-09-03T02:2xZ; the running process booted 01:10:00Z (`f84eb21b`), so
   > `600` is what it holds. **"Tomorrow's 38.8-min median sits above the 30-min
   > floor" is therefore not evidence the throttle binds** — against a 10-minute
   > floor a 38.8-minute gap means the floor is NOT the constraint, and something
   > else is spacing those builds.
   >
   > What SURVIVES that correction, because it was measured directly rather than
   > inferred from the floor: **with two eligible dates, today still built at a
   > 15.8-minute median** — so widening did not halve today's refresh rate. The
   > practical conclusion stands; the MECHANISM story ("the throttle binds") does
   > not, and re-measuring it needs its own pass.
3. Memory: builds are serial, and the OOM history is on `build_intelligence_overview`
   per build, not across concurrent dates -- likely fine, not verified.

### Verification predicate, to be written down BEFORE deploying

- `BUILD_SPAN_ENTER stage=pull_hot_artifacts date=<tomorrow>` appears at all.
- Served `state_meta.computed_at` age drops below the slow-refresh interval.
- Today's own per-date period does not exceed ~30 min.
- REFUTED IF today's period doubles without tomorrow's age improving.

### THE ALTERNATIVE, and why it is worse

Gate `computed_at` on "is this date in the BUILD window" rather than "does it have
rows". Cheap, no extra builds -- but the board would then read FRESH while showing
19.2h-old Serie A rows. That is a display that lies, and `#334`/`#563` exist because
this repo has already been burned by asserted freshness. **Not recommended.**

### Effort

~30 lines plus tests for the eligibility change. The real work is the cost
verification, not the code.

---

## [board-model-edge-coverage] 2026-08-30 — 82% of the board is UNSIZABLE, and every `_alt` market is 0%

**MEASURED on the full board**, `/api/board/layer2-shortlist?date=2026-08-30&limit=2000`,
1198 rows -- the same `rows_in` `PLAN_WRITTEN` reports. My count of rows carrying
`model_edge_pct` is 218/1198 = 18.2%, which reproduces production's own
`no_model_edge_pct=980` exactly, so this is the same population the sizer sees.

`no_model_edge_pct` is not a threshold. Without a model view `model_probability`
== `fair`, so Kelly is exactly ZERO and the row cannot be SIZED at all
(`portfolio_commit.py:259`). Those rows can rank; they can never be bet.

    market              rows   w/ view   coverage
    totals               344        34      9.9%
    h2h                  142        65     45.8%
    spreads_alt          131         0      0.0%
    totals_alt           128         0      0.0%
    spreads               63         2      3.2%
    batter_hits           45        23     51.1%
    batter_hits_runs_rbis 40        21     52.5%
    batter_total_bases    32        19     59.4%
    strikeouts            10         0      0.0%
    TOTAL               1198       218     18.2%

**EVERY `_alt` MARKET IS EXACTLY ZERO** -- `spreads_alt` 0/131, `totals_alt`
0/128, and the other zero rows are small prop families. That is 259 rows, 22% of
the board, that can never produce a bet no matter what the venues quote.

**The whole plan funnel, arithmetic closing exactly:**
1198 rows -> 980 no model view -> 218 -> 213 below min EV -> 5 -> 2 below min
stake -> 3 sized -> 2 zero Kelly -> **1 position**.

**This is why "the ranker only picks one spread".** 63 spread rows existed, TWO
were sizable, and one survived EV and Kelly. The ranker did about as well as its
inputs allowed. The constraint is MODEL COVERAGE, not selection, and not any
part of the venue join / tick logic / order path -- none of which refuse spreads.

**AND NCAAF IS SEPARATELY BROKEN, not only gated.** Of its 373 rows ~193 carry
the gate's named refusals; **~180 carry "no projection object at all"** — no
reason, no projection dict. That is a generator that never ran, and it has a
cause: see `[cfbd-monthly-quota-exhausted]`. Deliberate suppression and a failed
generator were being counted as one thing.

**WHY totals is 9.9%: NCAAF dominates an opener-weekend board and its model is
DELIBERATELY WITHHELD.** 281 of the 344 totals rows are NCAAF, and NCAAF carries
a named, measured refusal:

    totals   "totals are 1.67x over-dispersed against the market and were
              never scored against the close"                        139 rows
    spreads  "margin model loses to the closing line by 3.563 points
    /h2h      of MAE over 2233 [games]"                               54 rows

That is a model that was BACKTESTED, FOUND WORSE THAN THE CLOSE, and suppressed.
Correct behaviour. NCAAF is 373 rows, ZERO covered, across every market.

**EXCLUDING NCAAF, totals coverage is 34/63 = 54%.** The 9.9% is composition.

Coverage by sport, whole board:
    soccer   103 rows   87 covered   84.5%
    mlb      332 rows  117 covered   35.2%
    wnba     390 rows   14 covered    3.6%
    ncaaf    373 rows    0 covered    0.0%

MLB + soccer = 435 rows, 47% covered -- the sports with a working model.
NCAAF + WNBA = 763 rows (64% OF THE BOARD), 1.8% covered.

WNBA's near-zero is a DIFFERENT cause: its board is mostly alternate lines
(`spreads_alt` 126, `totals_alt` 115) and the reason given is
`analytic_probability_is_only_valid_at_its_own_line` -- the analytic model
cannot price away from the line it was computed at. That is also why every
`_alt` market is 0% board-wide.

So "the board outgrew the model" is too vague. Precisely: the board added two
sports, one whose model is gated because it MEASURED WORSE THAN THE CLOSE, and
one whose board is mostly alt lines its model structurally cannot price.

The code's own baseline comment records 65 of 108 rows carrying `model_edge_pct`
on 2026-08-16 (60%). Coverage is now 18%, but the board grew ~11x (108 -> 1198)
while covered rows grew ~3x (65 -> 218). That is the board outgrowing the model,
which is a different problem from the model breaking -- do NOT read it as a
regression without checking per-market coverage against that date.

Venue-scoped coverage is much better than board-wide: the Polymarket line
reports `sim_view_on=14/29` (48%). The unprojected mass is mostly rows the
venues do not quote anyway.

## [live-edge-basis-label] `edge_basis` WAS WRONG ON EVERY LIVE MONEYLINE ROW, AND THE MEASUREMENT THAT CERTIFIED IT COULD NOT HAVE SEEN THEM — fixed and landed `[2026-09-05, lane edge-basis-moneyline, commits 5ce75195 + fda5c28a, NO DEPLOY]`

`projection.edge_basis` says WHICH probability `edge_vs_market_pct` was paired
against. `_apply_verdict` derived it from `live_projected` — the parameter that
decides whether to PUBLISH the live probability — not from the probability the
edge was priced from. The MONEYLINE branch of `attach_live_gamelines` passes no
`live_projected`, deliberately, so **every live h2h row was labelled `pregame`
while its edge came from `hit["home_win_prob"]`, the live number.** Present from
the key's first commit (`28b03fef`, 2026-08-16); not a regression.

MEASURED 2026-09-05 with the real functions, decided NCAAF game, `sims=200`:

    verdict   model_prob 1.0   market_prob 0.310   edge_pp 69.0   priceable true
    published edge_vs_market_pct 69.0 == (1.0 - 0.310) * 100      <- the LIVE pair
    the pregame pair (0.977 - 0.310) = 66.7, and is NOT what came out
    published edge_basis "pregame"

**THE FIX IS THE LABEL ONLY**: it is now read off `verdict["model_prob"]`, which
is what `edge_pp` is computed from in all three pricers, and `_apply_verdict` has
no caller but `attach_live_gamelines` — so every verdict reaching it was priced
from a live `hit` and `"pregame"` was never a reachable correct answer.

**THE OBVIOUS WIDENING IS FORBIDDEN AND THE REASON IS IN THIS FILE'S DOMAIN.**
Passing `live_projected=hit["home_win_prob"]` on the moneyline branch would also
write `live_model_prob_over`, which `layer2_board._live_projection_columns`
(~:2214) maps onto `live_model_probability` **with no side awareness**. On an h2h
row that value is the HOME win probability, so an AWAY moneyline row would render
the home team's number in the Live column — the defect `_model_prob_for_side`
exists to fix, on the same field, one column over. Also unguarded on that path:
`refuse_published_certainty` checks only `model_prob_over`, so a
`live_model_prob_over` of 1.0 would publish a certainty. **If h2h ever needs to
serve that column, it needs a side-aware source, not the raw key.**

**WHO READS `edge_basis`: ONE CONSUMER, AND IT NEVER SEES THESE ROWS.**
`football/pick_gate.filter_pick_rows` (default `basis_key="edge_basis"`); its only
caller `ncaaf/picks.py:70` feeds it recommendation-artifact rows, and its
vocabulary is `{"model","market"}` — disjoint from `{"live","pregame"}`. A latent
name collision, no current overlap. NOT `layer2_board._model_edge_for` (reads
`edge_vs_market_pct`), NOT `live_gameline_ledger.build_records` (reads
`lg["model_prob"]` off the gameline block), NOT `live_edge_policy`, and it appears
in no template, JS or TS. **So the change is label-only on the served payload.**

**POPULATION.** Served board, substrate `render` 2026-09-05T21:26Z: 54 live rows
across all sports, `rows_live_gameline_edged: 0` on mlb AND soccer,
`supported: false` on ncaaf — ZERO rows carried the label at that instant, which
is an instant and not a population. The historical population, substrate `render`
21:53Z: soccer h2h ledger 411 records / **191 priceable with a final**;
`history.jsonl` (substrate `checkout`, 36 captures 08-20..09-05) adds mlb **110**
and wnba **14**. All labelled `pregame` by construction.

**`_MODEL_EDGE_MAX_POINTS = 15.0` IS NOT RELAXED**, and this does not license
relaxing it — see `[board-model-edge-coverage]`. The bound is still the guard that
drops the worst live rows; `edge_basis` being correct is a precondition for
revisiting it, not a reason to.

**TWO CORRECTIONS 2026-09-05 ~23:1xZ, both raised by lane `ncaaf-live-resim-wire`
and both verified here before being accepted.**

1. **`"no live re-sim wired for ncaaf"` IS REFRESH-WORKER'S COMMIT, NOT WEB'S,
   and I attributed it to the wrong service twice.** `build_book_grid_artifact`
   calls `attach_live_gamelines_for_sport` (`book_grid_artifact.py:318`) and
   writes the `live_gamelines` block at `:425`; its only caller is
   `run_refresh_worker.py:5371`. The route `board_book_grid_api`
   (`intelligence.py:2676`) PREFERS `read_book_grid_artifact` and falls through to
   a serve-time pivot only when the artifact is absent — so on mlb/soccer/ncaaf I
   read a worker-built artifact, and on wnba (`live_gamelines: null`, a different
   payload shape) I read the fallback. **What misled me was an accurate docstring
   about the OTHER path**, on `board_layer2_shortlist_api`: "unlike
   `/api/board/book-grid` above — which is a serve-time pivot and computes its own
   grid". True of the fallback, false of what production served.
   **The reading itself stands; only the service does not.** It decides which
   deploy discharges it, so it is not a detail.
2. **PROVEN BY THE STRING FLIPPING WHEN REFRESH-WORKER DEPLOYED, which is
   stronger than either attribution argument — and my first attempt at this
   proof was itself a stale-artifact reading.** At 23:09:37Z I read
   `{"supported": false, "reason": "no live re-sim wired for ncaaf"}` and was
   about to record "still inert". That artifact's `generated_at` was 23:06:54Z
   and refresh-worker deployed `ffe8714b` at **23:07:14Z — 20 seconds later**, so
   the reading described the OLD code. `[gate verification on artifact mtime]`
   caught in the act. Re-read at 23:13:53Z against an artifact 3 seconds old:
   **`supported: true`, the string GONE.** `262fd2cf` is inside `ffe8714b`. A
   string that flips exactly when refresh-worker deploys, while web sat live and
   unchanged throughout, settles the service.

3. **THE REFUSAL MOVED ONE STAGE DOWN, AND THE FIX IS STILL INERT ON NCAAF —
   for a different reason than either lane expected.** 23:13:50Z artifact:
   `supported: true`, `reason: "no published live-lens snapshot"`,
   `rows_live_gameline_edged: 0`, 97 live NCAAF rows, **0 carrying a
   `live_gameline` block and 0 carrying `edge_basis`**. The sport is registered;
   the producer is deployed; the snapshot is not being written.
   `/api/ops/live-lens/snapshot-index?sport=ncaaf` → `snapshot_present: false`,
   `no_snapshot_at_path`, `/opt/render/project/data/live/ncaaf_live_lens.json`.
   **CONTROL RUN, and it is what makes that a finding rather than a null:** the
   same endpoint on the same web service reports `snapshot_present: true` for
   **mlb, wnba AND soccer** in the same directory. So the path resolves, the
   web/worker transport is not the confound, and the absence is NCAAF-specific.
   Owed by `ncaaf-live-resim-wire`, NOT `ncaaf-live-resim` as written above.

4. **CORRECTION TO (3), AND IT IS THE SAME ERROR AS (2) COMMITTED TWICE INSIDE
   ONE HOUR.** "The producer is deployed and not writing" was a STALE READ. The
   first tick wrote at **23:15:29Z**; my window was 23:13–23:15Z. I read the
   consumer before the producer had run once, having caught myself doing exactly
   that ninety seconds earlier. At 23:28Z: `snapshot_present: true`,
   `snapshot_generated_at 2026-09-05T18:26:33-05:00`, 51 games,
   `sources_seen {live_resim: 6, pregame: 45}`.
   **AND MY CONTROL WAS SOUND BUT NOT A DISCRIMINATOR.** mlb/wnba/soccer being
   present did eliminate the disk split — and I then treated "the confound I
   thought of is eliminated" as "my hypothesis is confirmed", while a third
   explanation was live the whole time: the tick had not run. Both produce
   `no_snapshot_at_path`. **The discriminator existed and was the PRODUCER'S OWN
   SIGNAL** — refresh-worker's `NCAAF_LIVE_RESIM {... "written": true ...}` line
   at 23:15:51Z. Asking "did the producer run" from the consumer's absence is the
   standing error `[absent signal is about the emitter]`; a null on the consumer
   needs the producer's emission and an elapsed-time denominator before it means
   anything.
   **THE REAL DEFECT WAS ONE HOP FURTHER ON, AND IT WAS BIGGER:** 257 of 257 rows
   missed at 23:17:39Z with a PERFECT index (`index_size 8`,
   `skipped_no_team_names 0`) — the lens keyed from the CFBD projections artifact
   and the grid from the odds source spell teams differently,
   `('baylor','auburn')` vs `('baylor bears','auburn tigers')`. Fixed by that lane
   as `933e9beb`. **So live NCAAF h2h rows were WITHHELD before the join, never
   mislabelled**, and this lane's `edge_basis` fix gets its first NCAAF population
   when `933e9beb` deploys. The fixture shape that hid it is now pinned by
   `test_a_naming_convention_mismatch_is_VISIBLE_and_never_a_silent_zero`.
