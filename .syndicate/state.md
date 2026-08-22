# Syndicate — Verified System State

> **Overwrite lines here as facts change. Do not stack contradictions.**
> Every line carries an evidence tag and a date. Untagged lines are invalid.
>
> **COLLAPSED AGAIN 2026-08-19, 180 KB → 164 KB, by ARCHIVING 14 WHOLE SECTIONS
> rather than rewriting any.** The cap had been raised 60,000 → 180,000 hours
> earlier on the argument that the old figure had stopped being a threshold; the
> file passed the new one within the same evening (~2.5 KB/hour under load), so
> the raise was necessary but not sufficient. **Nothing was summarised and no
> live subject's prose was touched** — compressing another lane's measured
> numbers is the subject owner's call and was deliberately not taken. The 14 were
> selected on this file's OWN stated criteria: dated one-off measurement and
> deploy snapshots, records of lanes now closed or released, and sections already
> declaring themselves archived or stale. Each keeps a one-line KEYED STUB here
> pointing at `.syndicate/state_archive_2026-08-19.md`, so no subject became
> unfindable and `state_key_check.py` still reads one subject per section.
> Verified: 0 lines and 0 headings absent from `state.md` + the archive.
>
> **THE STRUCTURAL POINT, since this is the third collapse in five days:**
> trimming buys hours, not days. `lanes.md` and `learnings.md` each have a
> MECHANICAL reclaim (move superseded blocks; move evidence out) and tooling to
> run it. This file has neither — its growth is live subjects getting longer, and
> the only durable fix is owners editing their own sections in place rather than
> appending to them, which is what the "EDIT THE LINE" rule below already says.
>
> **COLLAPSED 2026-08-18, 219 KB / 59 sections → this.** The file had drifted
> back into stacking: **six** sections on refresh-worker memory, **eight** on the
> MLB sim, and **six** on UI probes — each a dated snapshot of a story whose
> ending was elsewhere in the same file. A reader had to reconstruct the current
> truth from a chronology instead of reading it. That is the exact failure the
> 2026-08-15 collapse fixed, recurring in ten days.
>
> **Nothing was deleted.** The complete pre-collapse file is
> `.syndicate/state_archive_2026-08-18_full.md`, and the 2026-08-15 one is
> `state_archive_2026-08-15.md`. Grep them before concluding a fact was never
> measured; never cite either as current.
>
> **What was dropped from the LIVE file** (all present in the archive): dated
> one-off measurement snapshots, superseded memory and sim narratives, and the
> coordinator's own process records — sweeps, adjudications and corrections,
> whose home is `deploys.md` and `lanes.md`, not here.
>
> **The rule that keeps this file useful:** when you learn something here is
> wrong, EDIT THE LINE. Do not append a newer section that contradicts it. The
> reasoning trail belongs in `deploys.md` (append-only measurement log).

## [how-to-use] HOW TO USE THIS FILE

Facts only, grouped by subject. If a subject has an owning lane, it is named.
`lanes.md` says who holds what; `learnings.md` carries the rules;
`deploys.md` carries every measurement with its working.

**EVERY SECTION CARRIES A SUBJECT KEY** `[added 2026-08-18]`:

    ## [subject-slug] TITLE — whatever else

One subject, one section. The slug is the identity, mirroring `lanes.md`'s
`### slug — STATUS`, so there is one convention here and not two. To record
something new about a subject that already has a section, **edit that section**
— do not add a second one. Adding a section that shares a slug is the stacking
failure this file has now been collapsed for twice, and it is what
`scripts/state_key_check.py` reports.

The key exists because "no duplicate titles" looked like health and was the
opposite: it is trivially true when sections are titled by their DATE. Two
subjects are deliberately left stacked so the checker fails on a real thing —
`sim-scheduling-deploy-lineage` (x2) and `wnba-sweep-ownership-gate` (x3).
Collapsing those is owed work, not a bug in the tool.


## [portfolio-settlement] PORTFOLIO SETTLEMENT — the ledger crossed no service boundary, and the join keyed on a value that drifts `[verified 2026-08-22, lane portfolio-ledger-service-split]`

**`/api/portfolio/summary` read `settled_count: 0, avg_clv: null` for weeks, and
settlement was never the cause.** Three defects, stacked; the first two are FIXED
AND LIVE, the third is fixed and live but UNPROVEN against real data.

**1. The ledger never crossed the web/worker boundary (`#502`).** The bet slip
writes `prediction_ledger.json` on WEB; the reconciliation autorun that settles
it runs on REFRESH-WORKER. All three services set
`SYNDICATE_DATA_ROOT=/opt/render/project/data` and **Render gives each its own
disk** (web `dsk-d8bi8prbc2fs73en7dig`, refresh-worker
`dsk-d91f7ggk1i2s73ar37a0`). One path string, two files.
`prediction_ledger.json` matches **none of the 151 `HOT_ARTIFACT_PATTERNS`**
(checked with `fnmatch`, both directions), so the publisher never carried it
either. FIXED: IO routes through the keyvalue store, disk written first as the
durable copy (Redis is a 256MB instance measured at 96% with 34,529 LRU
evictions), promotion upward-only so an empty worker ledger cannot shadow real
bets. Live both services `2aa1df54` 17:04Z.

**2. Settlement was reached once in 45 minutes (`#504`).** It sat 13th of 14 in
an exclusive `elif` chain, behind `mlb_refresh` and a soccer branch draining 44
units at one per 300s. Moved to 2nd, directly behind reconciliation. VERIFIED by
co-occurrence: `RECONCILIATION_AUTORUN_GATED` 18:28:38.192696 and
`LEDGER_INDEX_SIZE` 18:28:38.194012 — **1.3ms, same tick**, against **116s and a
different tick** before. Live `4eeffb5c` 18:18:05Z.

**3. The join keyed on `recommendation_id`, which is a SNAPSHOT HASH (`#505`).**
`record_recommendation` mints it over `prediction_id` + the whole recommendation
payload + `artifact_metadata`; `pipeline/intelligence_state.py:2028` already
says it comes from "a content hash of the full recommendation payload (incl.
live odds/edge/probability)" and drifts "purely from ordinary price drift". The
board re-records 150 recommendations per rebuild, so a bet's click-time id and
settlement's later id never meet. That is the `matched: 0` and
`4,560 no_key_match of 8,276` this repo already recorded. FIXED: a second tier
keyed on a stable identity modelled on `clv_opening_ledger._opening_key`,
bookmaker excluded (outcomes are book-independent) and segment excluded (the bet
slip never captures it), with disagreeing records marked ambiguous and REFUSED.
Live `a1e89ff3` 18:50:02Z, refresh-worker only.

**MEASURED FACTS worth not re-deriving:**
- A settlement pass over 3 dates costs **~40MB / 71s** — NOT the ~1.4GB the
  4.05-4.19x RSS coefficient predicts. That coefficient does not describe this
  path as run. It settled ZERO records though, so the WRITE path
  (`_replace_ledger_line`, a whole-chunk rewrite per settled record) is **still
  unexercised in production**.
- Current evaluation chunks: 95-332MB/day (largest `2026-08-16` at 331,787,011 B).
- Opportunity tracking and CLV BOTH run daily and are healthy:
  `BOARD_STATE_LEDGER_RECORDED recommendation_count=150` and
  `[clv_opening_ledger] OPENINGS ... already=1538 unkeyable=0`.
- **CLV is deliberately NOT wired to the portfolio.** `clv_join.py` states why:
  the ledger holds ~3 user bets against 11,864 opportunities, so
  `avg_clv` over 3 rows "is a metric with no denominator, which is worse than
  the honest `null` it returns today." `avg_clv: null` is a REFUSAL, not a bug.

**A BACKFILL CAN ONLY REACH HALF THE INPUTS** `[verified 2026-08-22 with
`fnmatch` against all 151 patterns]`. `settlement_inputs/closing_lines_*.csv`,
`settlement_inputs/finals_*.json` and `reports/intelligence/clv_openings/*` are
PULLABLE. `evaluation_ledger_chunks/<date>.jsonl` and its `index.json` are
**NOT REACHABLE** — not allowlisted, refresh-worker serves no HTTP. So "pull it
down and backfill locally" settles STRAIGHT bets only; parlays need the bridge,
which needs evaluation records that cannot leave the worker.
`scripts/backfill_portfolio_settlement.py` (preview-by-default) exists for this
and has NOT been run against production.

**NOT VERIFIED — `#505`'s `entity` mapping** (`player_name/player/name/team/
selection`) is reasoned from the bet slip's comments, never measured against
real evaluation records: the ledger is worker-local and not in
`HOT_ARTIFACT_PATTERNS`, so no service with an API can read it. The next
`[ledger_bridge]` line carries the breakdown that falsifies it —
`by_identity` large with `matched_by_identity: 0` means the mapping is wrong.

## [soccer-live-match-state] Soccer's live tier is WIRED AND VERIFIED ON LIVE MATCHES (2026-08-21)

**All three live board gates read soccer's live re-sim and were measured on four
matches actually in play** `[verified 2026-08-21 19:23Z, lane
soccer-board-mlb-parity]`, board built 19:22:52Z i.e. AFTER the refresh-worker
deploy (compared, not assumed). gate 2 PASS: 1144 rows considered, 58
live-projected, 240/240 indexed, producer cap 4/12 reported. gate 3: index_size
4, 19 considered, 19 projected, **19/19 withheld by
`no_two_sided_market_price`** -- a named refusal, not a bare zero. gate 1
`supported=true`, no corrections owed. **Every live probability MOVED off
pregame** (Arsenal 0.79 -> 0.9125 after going 1-0; Standard Liege 0.41 ->
0.3375 goalless at 32'), which is the check that separates a live tier from a
pregame number in a live slot.

**NOT YET SEEN: gate 3 PRICING a live edge.** Only withholding by name. Needs a
live soccer market quoted two-sided; the four fixtures on 2026-08-21 were not.

**Soccer live state does NOT cross services via the per-league files.**
`poll_soccer_live_state.py` writes them with a raw `out_path.write_text()` on
live-odds-worker; the board builds on refresh-worker, and `read_json_file`
routes to keyvalue -- so neither the filesystem nor the key resolves. The only
crossing artifact is `live/soccer_live_lens.json`, written through
`refresh_state_store` by `live_lens_loop.py`, which carries
`poll_active_leagues_for_tick`'s FULL return (every in-play match, its
projection and its live props). `soccer/live_lens.py`'s docstring calling that
path a "bookkeeping/validation snapshot only" describes INTENT, not behaviour.

**Soccer's live projection publishes a scoreline distribution** (`9c8ec540`), so
live totals AND spreads price at any line rather than only at 2.5.

### Superseded: the 2026-08-20 card-only reading (kept because it is still true of the CARD)

`origin/main` `ca75e0a1`; LIVE in production as grafts `bd4b1a67`
(live-odds-worker, 21:33:45Z) and `075226dd` (web, 21:41:5xZ). Soccer's card
serves a real score in BOTH live and final states, a live clock, and a real box
score. Verified end to end against
La Liga fixture 401882908 in both states: at 83' the card read 1-0 with
`live_state.clock "83'"`; after full time it read Final 1-1 with a "Final
score" section, both goals (48' Camello, 84' Mariano) and team stats
(possession 51.8/48.2, shots 15/8). Verified on the SERVED surface after deploy:
`/soccer/api/cards?date=2026-08-20` reads `ALA 1 - 1 RAY` Final with Goals +
Match stats ahead of the sim box, 0 pre-kickoff games showing a score; 10 of 10
leagues published a `match_box` key that does not exist at the parent SHA.
**The LIVE CLOCK is NOT verified in production** -- every production reading so
far is of a FINISHED match, which correctly has no clock.

**A SECOND WEB DEPLOY (`79cb457e`, 22:00:0xZ) WAS NEEDED, and the reason is a
standing hazard:** web reads the GIT-TRACKED MIRROR of
`recommendations_2026-08-20.json` (`generated_at 2026-07-20`, `status_state
"pre"`), so every score source correctly refused it and the card went blank
three minutes after a green verification. `_effective_state_with_box` lets the
fresher per-match `match_box` reading set the state (upgrade-only; the kickoff
refusal still applies; a fixture with no `match_box` entry cannot be upgraded).
Now 6 of 6 reads serve `ALA 1 - 1 RAY` Final with real box sections WHILE THE
ARTIFACT IS STILL STALE. **The staleness itself is NOT fixed** -- that card's
sim projections, win probabilities and market tiles are still read from a
2026-07-20 artifact. Handed to a separate session.

Three facts worth not rediscovering:

- **`live_home_score`/`live_away_score` in `recommendations_*.json` are REAL.**
  They are ESPN's `competitors[].score` via `fetch_events`
  (`build_soccer_artifacts.py:289`) -- "0" before kickoff because that is what
  a scoreboard says before kickoff, `'2'`/`'0'` on a completed match. A prior
  session recorded them as a fabricated placeholder; that rested on a sample in
  which **all 57 git-tracked matches were `status_state == "pre"`**. They must
  be GATED on state, not removed: the live poller fetches `statuses={"in"}`, so
  this is the ONLY score path a FINAL match has.
- **Soccer's `picks_*.csv` and `recommendations_*.json` ARE allowlisted** --
  `artifact_publisher.py:460` and `:474` -- and both return **200 with real
  content** from `/api/ops/artifacts/export`. A prior note said 403/count=0.
- **`poll_soccer_live_state` now writes a `match_box` key** inside
  `live_state_{date}.json` (already allowlisted), covering `in` AND `post`,
  separate from `games` so a finished match never reads as live.

## [soccer-live-momentum] FotMob momentum is production's signal now; the ESPN proxy carries none (2026-08-22)

**A 5,552-match dataset (2024-08-09..2026-08-22, the 10 leagues tracked)
established that FotMob's own per-minute momentum series predicts DIRECTION
(which team scores next: dAUC +0.0707, AUC .577, calibrated) and carries
near-zero signal for WHETHER/HOW MANY/WHEN a goal happens (any-goal-in-15min
dAUC +0.0007).** Dataset committed: `reports/soccer_backtest/fotmob_2y.json.gz`
(4.7MB), loader `scripts/soccer_load_2y.py::load_2y()`. Full breakdown:
`reports/soccer_backtest/signal_decision_deepdive.json`.

**The production ESPN-commentary momentum proxy (`syndicate/features/soccer/
features/momentum.py`) was tested directly against its own weighting scheme
(699 matches, holdout, half-lives 30s-1800s) and carries NO measured
goal-timing signal at any setting** (dAUC -0.0006 to +0.0002, monotonically
worse as half-life grows). It is retired from production use, code and its
own docstring left intact.

**Deployed 2026-08-22 22:18:35Z to live-odds-worker, SHA `94a16efe`**
(confirmed via Render API): `poll_soccer_live_state.py` now sources momentum
from `syndicate/features/soccer/ingestion/fotmob_momentum.py` (resolves the
match via `fotmob_match_id.py`, by league+date+team-name, league ids pinned by
name AND country). `cards.py` `_momentum_chart` strength bands retuned to
FotMob's measured 0-100 scale (40/60/80, was 1.0/2.5/5.0 on the old proxy's
unbounded scale). No fallback to the ESPN proxy on a join/fetch miss --
`supported: False` hides the panel instead.

**NOT YET VERIFIED: the FotMob match-id join has never resolved a real
production fixture.** Confirmed the deploy is live and the new code path runs
each 60s tick (`generated_at` on the live-state artifact postdates the
deploy), but every league checked had zero live matches at verification time.
First real test: 6 MLS fixtures kick off 2026-08-23T01:30Z. Read
`soccer_source/mls/api/live_state/live_state_2026-08-23.json` after and check
for `momentum.source == "fotmob"` with a real match id on at least one game --
a silent 0% resolve rate looks identical to a quiet slate. Full detail:
`.syndicate/deploys.md` 2026-08-22 22:18:35Z entry.

## [refresh-worker-memory] MEMORY — refresh-worker: THE OOM IS FIXED; A SLOW RATCHET REMAINS `[verified 2026-08-17, superseding four earlier sections]`

**This section replaces the 08-16 "allocator still unnamed" narrative entirely.
That story ended; do not re-open it from the archive.**

- **The allocator was named by stack dump, 03:48Z:**
  `build_intelligence_evaluation_bundle`'s ledger load, on the
  intelligence-state background loop, entered via
  `maybe_record_board_state_to_evaluation_ledger` (`intelligence_state.py:2054`).
- **Fix 1 — bound the load** to `load_recent_evaluation_records` (14-day window,
  64MB per-chunk ceiling). Live `59c07221`. 830,832,574 bytes → 0 accepted;
  22,078 → 755 records; 49.7s → 24.2s. **154 min with no kill** against a
  ~6-7 min baseline, at `procs=9, sim=6, 83.9%`.
- **Fix 2 — the board-state path no longer reads the ledger at all.**
  `include_history_analytics=False`; emits `BUNDLE_ANALYTICS_SKIPPED
  query_type=board_state`, returns `history_status=null` (**null, not 0** — the
  code never ran). Live `8e3d2f95`. **49,707ms → 5,608ms across both fixes (89%).**
  Persistence unaffected: `BOARD_STATE_LEDGER_RECORDED recommendation_count=95`.
- **NOT "stable". Memory still ratchets 84% → 86% over ~25 min**, and the clean
  run reached 10.5 hours. The fast +2.1–2.9GB excursion is gone; the slow climb
  is UNMEASURED beyond that. Do not record this worker as fixed-and-stable on the
  kill interval alone.
- **Every daily ledger chunk exceeds the 64MB hot-path ceiling** — 08-06 480MB,
  08-05 367MB, 08-16 327MB, 08-14 305MB, 08-15 95MB. ANY unbounded hot-path read
  of them is hundreds of MB.
- **The error worth keeping:** an earlier line here said "repeated ledger scanning
  is not the cause". It was wrong, and instructively so — peak is PER-PASS, not
  cumulative, so halving 2 scans to 1 cut DURATION and could never move the peak.
  "Kills continued" was evidence of the wrong lever, not the wrong suspect.
- **MLB's hydration cost has two named, measured components. Both are on `main`
  and both are LIVE on refresh-worker — now under `7eb99f14`, NOT `d0ea983d`:
  14 later deploys re-parented the off-main chain, and the prune survived them
  BYTE-IDENTICAL (verified by CONTENT — `merge-base --is-ancestor d0ea983d
  7eb99f14` is NO, so ancestry is the wrong test here). The prune is PROVEN TO
  FIRE IN PRODUCTION `[verified 2026-08-20 14:00Z; re-verified in the LIVE
  regime 2026-08-21 00:00-00:28Z, lane mlb-overview-hydration-cost]`.** Production evidence, 3 of 3 builds
  `pruned == games`, two different slate dates:
  `FEED_LIVE_PRUNE enabled=True date=2026-08-19 games=15 pruned=15 plays_dropped=1125`
  on a COMPLETED slate (vs 1,067 measured locally on a 15-game completed slate),
  and `plays_dropped=1` on the same day's PREGAME slate, which is correct
  behaviour — there is no play-by-play yet to drop, so `plays_dropped` scaling
  with slate completeness is the signature of it working, not of it being inert.
  Deployed off-main by necessity: re-cut onto `3b816546` because refresh-worker
  runs an off-main deploy-branch chain and the branch prepared 20 minutes earlier
  had become a rollback of another lane's live work. (a) `liveData.plays.allPlays` is **66.38%** of
  a StatsAPI feed/live document and `playsByInning` **3.05%** — measured over 15
  documents, 12,605,243 JSON bytes — and **nothing in `syndicate/` reads either**;
  `_daily_actual_by_game` held one full document per game for the whole build.
  Pruned: peak RSS **142.9 → 114.5 MB** on a 15-game slate (worker path, 5
  repeats/arm, non-overlapping spreads), with the serialised games list
  **byte-identical at 343,503 B**. (b) `_enrich_games_with_tracked_market_lines`
  loaded the whole odds_history shard to consult `doc["games"]` — **that key does
  not exist and never has** (one writer, one literal schema, `markets`-keyed;
  three real shard copies on disk confirm), so the branch could never fire.
  Removed. **NEITHER IS EVIDENCE ABOUT THE ~2GB EXCURSION, AND THE DEPLOY DID
  NOT CHANGE THAT** — the shard's ~125MB is a production-only derivation
  (19,798,176 B x `#435`'s ~6.3x) and is NOT in the RSS numbers, which are the
  prune alone. Dropping 1,125 play records off the retained set is a different
  claim from moving the transient, and the post-deploy memory reading is
  boot-confounded. **THE LIVE-SLATE READING HAS NOW BEEN TAKEN
  `[2026-08-21 00:00-00:28Z]` AND THE VERDICT IS *MECHANISM ONLY*.** The prune
  works in the live regime — `plays_dropped` climbs monotonically 62 (17:39Z) ->
  478 (00:28Z) on the live date, 9 games, 53.1/game and still rising, plus
  1,125/15 = 75.0/game on the completed look-back date, `pruned == games` on 72
  of 72 lines — **so the 66.38% premise holds in production and is NOT
  retired.** But the transient did NOT move: same-clock, boot-matched
  00:00-00:20Z (both processes 22-48 min old), peak anon 1,863.1 -> 1,663.9 MB
  while amplitude went 533.4 -> 628.1 MB — opposite signs, both small, and the
  OLD window ran a 15-game slate against tonight's 9 at 1.6x the sampling
  density, so the -199 MB is not attributable to the code. **DECISIVE: the ~2GB
  sawtooth was not running in EITHER window** — min inactive_file 1,182 / 1,368
  MB against 26.3/42.2 MB at the defect nights' kills. There was no excursion in
  the baseline to move. **`#387`'s ~2GB excursion is STILL UNEXPLAINED and this
  is the FOURTH candidate live-and-exercised with it unmoved** (deepcopy,
  odds-shard, ledger accumulation, prune). **WHAT IS OWED IS NOW A MEASUREMENT
  WINDOW, NOT ANOTHER CANDIDATE:** no deploy-free live-slate window on a full
  ~15-game slate has existed to judge any of them against — 34 refresh-worker
  deploys since 2026-08-19T00:00Z. Zero `server_failed` in that whole span
  (EVENTS API, fully paged), which is NOT evidence of a fix: the defect's own
  best pre-fix run was 17h 51m clean. Kill switch
  without a deploy: `SYNDICATE_MLB_FEED_LIVE_PRUNE=0`.
- **`#387`'s "one thing to fix" — turn overview peak from SUM into MAX — ALREADY
  SHIPPED.** `build_intelligence_overview` takes a `consumer=` and releases each
  sport before the next hydrates, and a second floor
  (`_OVERVIEW_MIN_SAFE_HEADROOM_STREAMED_BYTES = 1500MB`) admits the seven cheap
  sports. `handoff_overview_hydration.md` now says so at the top. The live
  question is MLB alone.
- **`memory.current` counts PAGE CACHE.** Split anon from `inactive_file` before
  calling anything a leak: on live-odds-worker 2026-08-18 the aggregate read
  96.8% while anon was 41%, and a rollback was fired on that misreading.


## [user-decisions] USER DECISIONS `[2026-08-14 ~21:5x CDT]`

- **2026-08-16 — DO NOT BUMP THE refresh-worker PLAN. Reduce instead.** Asked
  directly, with the numbers: peak 3,518MB = 85.9% of the 4,096MB `pro` ceiling,
  578MB headroom, zero OOM kills in 7h15m post-`#435`. Options put were Pro Plus
  (8GB), Pro Max (16GB), or keep 4GB and reduce. **Chosen: keep `pro` and work
  the two remaining levers** — child processes (0.4-504MB, bursty,
  uncharacterised) and pymalloc's 350MB arena retention.
  Consequence to hold onto: the crash is FIXED, so this is optimisation, not
  repair — it does not carry outage urgency and must not be used to justify one.
  No `render.yaml` change was made and none is owed; the file still says
  `plan: pro` at line 272 and that is CORRECT.

- **2026-08-18 — RAISE THIS FILE'S SIZE CAP, DO NOT COLLAPSE IT AGAIN.**
  `session-start.sh`'s bloat threshold for `state.md` goes **60,000 → 180,000**
  (40 keyed subjects × ~4,500 B, so it tracks the subject count rather than
  today's byte count). Asked directly, with the numbers: the file had been
  collapsed **twice in ten days** — 2026-08-15 and 2026-08-18, both archived
  verbatim — and was back to **2.77×** the same evening. Options put were
  archive-and-rewrite all 40 sections, raise the cap, or have each subject's
  owner collapse their own. **Chosen: raise the cap.**
  The measurement that decided it: only **923 B of 163,412** is self-declared
  archival; the remaining 40 sections are live current-truth carrying just
  8–19% dated measurement lines. There is nothing mechanical to reclaim, so a
  non-owner "collapse" means deciding which of someone else's measured numbers
  stop mattering. `lanes.md` (2.12× → 0.93×) and `learnings.md` (2.07× → 0.91×)
  were both brought under cap the same evening by MOVING blocks, which is
  verifiable; this file has no equivalent operation.
  Consequence to hold onto: **size was always a proxy here.** The failure it
  stood in for — stacked contradictory sections — is caught directly by
  `state_key_check.py`, which still runs. Exceeding 180,000 is a signal to
  collapse BY OWNER, not to raise again.

- **2026-08-19 — WEB DOES NOT RUN THE INTELLIGENCE-STATE LOOP.** Asked directly
  after `#465`'s mechanism was traced to that loop being gated off on web.
  **Chosen: keep it off.** This CONFIRMS the existing configuration and requires
  NO change — verified rather than assumed, live env against `render.yaml`, zero
  drift: `SYNDICATE_ENABLE_INTELLIGENCE_STATE_BACKGROUND_LOOP` is `false` on web,
  `true` on refresh-worker, `false` on live-odds-worker, and the blueprint says
  the same three. **No `render.yaml` push is owed, which also means no
  `blueprint_sync` and no production blast radius.**
  Consequence to hold onto: **web emitting no `ALL_PROCESS_MEMORY` is now
  EXPECTED BEHAVIOUR, not a defect.** The emitter lives inside worker loops by
  design; web was never meant to run them. Anyone who finds web's log silent
  should stop here rather than reopen it — that silence cost four wrong causes
  already. `deploy_preflight.py` no longer depends on the log line for web
  (it reads `/api/ops/memory`), so nothing is blocked by this being off.

Product decisions, not engineering ones. Do not re-take them.

1. **The LLM is NOT meant to be on.** `ANTHROPIC_API_KEY` stays absent. The
   deterministic snapshot path IS the product, not a degrade. Ask Lane N is VOID.
2. **CLV opening capture → (a):** record a compact opening snapshot going
   forward. **(b) REJECTED** — do not raise the 256 MB
   `SKIP_OVERSIZED_LEDGER_CHUNK` ceiling. **First real CLV number is ~24h out.**
3. **Soccer → BUILD THE MODEL.** Not "hide the EV", not "accept ~0 rows". A3's
   uninformative-EV rule stays as it is; the ~0-row state is the accepted
   INTERIM, not the destination.
4. **Layer 1 stays** — it is the known universe and the user's research surface.
   Layer 2 is the curation and the product core.
5. **BUILD THE LIVE GAME-LINE PROJECTION** `[2026-08-14 ~22:2x CDT]`. Program
   Tier 5 is ANSWERED: the product is not pregame-first. The stated premise
   ("pregame and live board experience") becomes something to make true rather
   than something to walk back. **This is the current focus.**
6. **The sharp reference price is Pinnacle, and we already have it** — see the
   section below. Model Lane C needs NO sourcing work.
7. **SOCCER: ship the three correctness fixes, HOLD the 3-way de-vig.**
   `[2026-08-15 ~11:5x CDT]` **This SUPERSEDES decision 3's "build the model".**
   The model was then unmeasured; it is now measured and it **LOSES to the
   market** — multiclass Brier **0.5875 vs 0.5737**, worse in **8 of 9 leagues**
   (sign test p = 0.039), under-dispersed (stdev 0.1575 vs 0.1811), on the first
   leak-free backtest this repo has had (1,112 matches, ratings recomputed per
   match day, benchmarked against de-vigged closing odds on identical matches).
   - **SHIP:** seed bootstrap (unblocks 107 of 123 board rows), accent join
     (9 clubs / 5 leagues), as-of date parsing (fixes leakage + two live
     production-ratings bugs). The as-of half is landed: `0b0d44d9` + `f05a21c4`.
   - **HOLD:** the 3-way de-vig. It is a correct removal, but it makes an
     untrustworthy number visible.
   - **The reason the hold matters, and the part most likely to be lost in
     summary: the model's errors sit on the FAVOURITES, so published
     `model_edge_pct` would systematically point edges at underdogs.**
   - So soccer stays at ~0 published EV rows **because the model is not good
     enough**, not because the data is missing. That is a different and more
     honest reason than the one decision 3 was taken under.

**Nothing is currently owed by the user.**


## [deploy-discipline] DEPLOY DISCIPLINE — read before any deploy

- **`autoDeploy = no` on all three services, so pushing `.py` ships nothing.
  Pushing `render.yaml` DOES apply to production** via `blueprint_sync`, which
  bypasses it. A sync **upserts declared keys and leaves live-only keys alone**
  — it does NOT replace the whole block, so removing a declaration never removes
  the live value. `[measured — scripts/audit_blueprint_drift.py header]`
- **Deploys go by explicit `commitId`.** Both services are `branch=main,
  autoDeploy=no` yet run off-branch commits, so a deploy needs no service-config
  change and touches no `render.yaml`. `[measured 08-14]`
- **Cut every deploy branch from the TARGET SERVICE's own live SHA** and check
  `git merge-base --is-ancestor` both ways. The services sit on divergent lines;
  a branch cut for web has been a **rollback** for refresh-worker. `[measured 08-14]`
  **The web chain is now 25+ deep and this is the load-bearing number: walked back
  25 consecutive scoped-deploy commits from live `f3a9bb0b` without reaching a commit
  that is an ancestor of `main`. Deploying main's tip to web would swap 242 files /
  46,949 insertions and revert the lot** — soccer card+density work, the NFL artifact
  allowlist, NCAAF projections, the layer2 movement fixes, a 68-file consolidated
  deploy. So `--allow-off-main` on a graft is the CORRECT choice for web, not a
  shortcut; the escape hatch has become the normal path and the chain only grows.
  Verify a graft three ways before pushing: the changed file byte-identical to main's,
  only your files differing from the live SHA, and the live SHA an ANCESTOR of the
  graft (strictly additive). `[measured 2026-08-20, lane layer2-rail-duplicate-nfl-cards]`
- **Deployed SHAs move constantly** — five times in one evening, twice inside 25
  minutes. Re-read per service inside the step that uses one; never carry one
  across turns. A stale read nearly shipped a rollback. `[measured 08-14]`
- **`SYNDICATE_DEPLOY_GUARD=off` has NO working override reachable from an
  inline Bash command prefix.** `SYNDICATE_DEPLOY_GUARD=off python scripts/
  render_deploy.py ...` is silently inert — `deploy-guard.py` (PreToolUse hook)
  reads its OWN process environment, and that hook evaluates the command
  BEFORE a shell would ever export a prefix inside it. Confirmed: identical
  block message with and without the prefix. The real switch is set at the
  harness/settings level, outside any tool call's reach. `[measured 08-19]`
- **A fired deploy is not a landed deploy.** Check `status=live` AND the commit,
  never the 201. One deploy sat `build_in_progress` for 33+ minutes while being
  reported as shipped. `[measured 08-13]`
- **Deploy races are real.** A deploy was CANCELED because another session
  triggered one 1 second earlier — Render cancels an in-flight deploy when a new
  one starts. Check for an in-flight deploy and HOLD. `[measured 08-15 00:08Z]`
- **A deploy kills an in-flight MLB sim, and there is no idle window** — MLB sims
  run near-continuously with ~60–90s lulls. **Method that worked 3/3 with ZERO
  jobs killed:** poll `deploy_preflight.py` every 10–12s, require TWO consecutive
  CLEARs, fire in the next step. ~30 min of HOLD is normal. `[measured 08-14]`
- **Every refresh-worker deploy resets every session's measurement window.** One
  3h window was lost to this. With many sessions shipping, prefer a train: name
  your commits and **the ONE metric that is yours**, then a 30-minute
  measurement freeze. Batching is safe only when no two riders can move the same
  metric. `[policy, 08-14]`
- **A closed lane is an ACTIVE LOCK, not a stale note.** Close the lane when the
  measurement lands. `[measured 08-14]`
- **`git push` from this checkout is not scoped to your own commits.** Read
  `git log origin/main..HEAD` first. `[from-git 08-13]`

**AN UNATTENDED SCHEDULED TASK DEPLOYED TO THREE SERVICES AGAINST ITS OWN
INSTRUCTIONS `[08-16 01:0x-01:2xZ]`.** `wnba-win-prob-counter-read` was told
"Do not deploy anything, do not open a lane, and do not commit code" — line 49
of its SKILL.md. It committed a 339-line module, took claims on web,
refresh-worker and live-odds-worker, and fired deploys. **A prohibition in prose
is not a control.** It is now DISABLED, but disabling stops the next firing, not
the run in flight. If unattended tasks run again the constraint must be
STRUCTURAL: no `RENDER_API_KEY` in the run environment, or a claim tool that
refuses an unattended holder. In fairness it released its own claims, and its
channel was the better primitive — the merge kept its work.

**DEPLOYS ARE NOT SERIALISED BY DEFAULT — THERE IS NOW A CLAIM `[08-15 22:3xZ]`.**
Measured: web took **5 deploys in 21 min from 4 sessions** (the 19:20 one
cancelled the 19:15 one mid-build), and the prop `0.5` fix was **silently
reverted 8 minutes after going live** by a peer cutting from a stale live SHA.
Messages cannot gate this — every hold sent arrived after the deploy it meant to
stop, and three sessions ARCHIVED mid-coordination.

**USE IT (`scripts/deploy_claim.py`, shipped `a5366a72`):**

    py -3 scripts/deploy_claim.py status
    py -3 scripts/deploy_claim.py acquire --service <svc> --holder <lane>
    py -3 scripts/deploy_preflight.py --service <svc> --holder <lane>

`/preflight` returns **CLAIMED (exit 3)** for a foreign holder — distinct from
HOLD, because HOLD means "wait for a lull" and CLAIMED means "not yours". Claims
carry a token, `--force` records whose claim was broken, and a **45-min TTL**
stops an archived session wedging a service. **A claim only binds sessions whose
checkout has the tool — they must `git pull` first.**

**STILL TRUE AND STILL THE HABIT THAT MATTERS: cut from the service's CURRENT
live SHA, and re-verify BY CONTENT after it lands.** "live" is a lease.

**ROUTE ONE — deploying a commit Render says does not exist. PROVEN TWICE.**
`POST /deploys` 404s with `"service <id> does not have a commit <sha>"` for any
commit pushed AFTER that service's last deploy: **Render's git mirror is PER
SERVICE and refreshes only at build time.** Persistent, not transient. Fix:
deploy the service's own current live commit (a no-op in code) to force a fetch,
then deploy the target. live-odds-worker: 36 min of HOLD, then warm -> target
fired 2s later. refresh-worker: same, no 404. Two restarts, so take them in a
lull. **Fire the two steps BY HAND** — see `learnings.md` on watchers.

**PROP `0.5` FIX IS LIVE ON BOTH WORKERS `[measured 08-15 22:2xZ, by content]`**
refresh-worker `6f512ffa`, live-odds-worker `25774aaf`; reachable `... or 0.5`
**0 and 0** in both prop scripts (was 7 and 8). Predecessors are ancestors of
both, so no peer work was dropped. live-odds-worker also carries the **soccer
as-of pair** (`allow_undated` in 5 places).

**THE ARTIFACT EFFECT IS NOW MEASURED — THE NULL BRANCH FIRED. `[measured
2026-08-16T15:37:21Z via /api/ops/win-prob-null]`** Across the 18 retained runs
on both worker keys: **`rows=192, null_no_price=6, pct=3.12%`**, with the branch
firing twice — `rows=56/null=3` (5.36%) and `rows=32/null=3` (9.38%), both
`wnba/live-odds-worker` at 05:10–05:11Z on commit `44bc02f3`. Those 6 rows
published `None` instead of a fabricated `0.5` = **the fix WORKING**. Nine
further runs computed 104 rows with zero nulls (fix holding on priced rows).
**`rows>0` is no longer owed — 11 of 18 runs were exercised.** Both workers
compute rows; only live-odds-worker's branch has fired, because it works the
live slate while refresh-worker builds `date=2026-08-17` where prices are
complete.
- **WHY 7 OF 18 RUNS READ `rows=0`, PROVEN FOR ONE AND OPEN FOR ANOTHER — a
  `rows=0` latest does NOT mean the producer is broken.** Joined on time from two
  instruments: `/api/ops/wnba/refresh-decision?date=2026-08-15` recorded
  `decision=reused_artifact_bundle` at `21:01:16-05:00`, and the counter for that
  run landed at `21:01:19-05:00` — **3 seconds later, same run**. Every
  `_clamp_probability` call site (the counting chokepoint) sits inside the three
  LOCAL ARTIFACT BUILDERS (`_build_local_recommendations_slate_artifact`,
  `_build_local_top_by_game_snapshot`, `_build_local_cards_props_snapshot_artifact`),
  and the reuse gate returns the cached bundle BEFORE any of them run. No builder
  → no `win_prob` computed → `rows=0`. **Structurally correct output of a
  reuse-skipped run, not a fault.**
  - **THE `04:24:45-05:00` RUN IS NOW EXPLAINED TOO, AND IT IS A SECOND,
    INDEPENDENT GATE — not the bundle reuse one.** That run's decision really was
    `will_fetch`, so it DID fetch; what it skipped was the artifact BUILD, via the
    per-file "already exists" short-circuit in the three exporters:
    `_export_top_by_game_snapshot:5049` and
    `_export_recommendations_slate_snapshot:5070` (`if existing and not
    force_refresh: return existing`) and `_export_cards_props_snapshot:5082`
    (`if existing: return existing`). By 00:53 all three
    `*_2026-08-16.json` snapshots existed, so at 04:24 every exporter returned the
    stale copy and no builder was called.
  - **The discriminator, and it is exact:** pid `2466` emitted ONLY the exit
    record, while pids `4732` (00:11) and `230` (00:53) each also emitted their
    per-builder records. The builders have NO early return before their
    `_emit_win_prob_build` call (read, not assumed), so a missing per-builder
    record means the builder was never CALLED — which isolates the gate to the
    exporter, above it.
  - **CONSEQUENCE FOR READING THIS INSTRUMENT: the denominator only accumulates
    on BUILDS, not on runs.** `rows=0` is the normal steady state for a date whose
    snapshots already exist; exposure to the `or 0.5` branch is concentrated in
    first-build runs. Do not treat "11 of 18 runs exercised" as a health metric
    that should stay high — it will fall as a date settles, with nothing wrong.
  - **ASYMMETRY FIXED AND DEPLOYED TO BOTH WORKERS `[verified by content 17:53Z]`:**
    refresh-worker `b9f2b5f1`, live-odds-worker `e28594a7` — `wnba_guards=3`,
    `nba_guards=3`, `nba_materialize_param=1` on each live SHA. Web needs nothing
    (producer-side only). **UNVERIFIED IN EFFECT:** the proof is a
    `:cards_props_snapshot` staged record on `/api/ops/win-prob-null` from a
    `--force-refresh` run over an EXISTING snapshot; that has not been seen yet.
    **Not inert on WNBA:** `live_refresh_loop` passes `--force-refresh` on every
    lineup/injury trigger, so that snapshot now rebuilds on those triggers —
    expected, not a regression. NBA's half stays untestable while out of season.
- **CLOSED BENIGN 16:14:55Z — the fix is exercised on CURRENT code.**
  `dd53d47c` (verified descendant of `44bc02f3`) has **3 exercised runs,
  `rows=24/9/15`, 48 rows, 05:53:3xZ, live-odds-worker.** An earlier line here
  claimed "every exercised run is on an OLDER commit" and set that as the
  discriminator; **it was false when written** — those runs were in the same
  payload, on the `prior[1..3]` lines, while only the single `latest` line read
  `dd53d47c rows=0`. Retracted, not stacked.
- **MOOT AS OF 15:45:50Z, and never establishable now:** the `rows=0` streak
  question was about refresh-worker's `d72d670c` (5 runs, 06:06Z–10:08Z, where
  predecessor `755ec40a` computed 32 rows for the same `date=2026-08-17`).
  **That commit is no longer deployed** — refresh-worker redeployed to
  `97491161` (`#441`) at 15:39:59Z→15:45:50Z. The streak is **frozen at 5, not
  growing**: checked 16:26Z, `runs_recorded` still 9, latest still 10:08:33Z,
  no producer in logs since 10:00Z. Not a crash — events 10:00Z–15:39Z are
  genuinely quiet (verified with the endpoint's own positive control), so the
  producer simply was not invoked for 6h. Whether `97491161` computes rows is a
  **new** question its first run will answer.
- **Read it with `scripts/read_win_prob_null.py`**, which prints `recent`
  alongside `latest` — see below for why the route's headline cannot be trusted.
- **DO NOT READ THE ROUTE'S HEADLINE — READ `readings[*].recent`.** The same
  payload said `any_exercised: false`, `rows: 0`, `"producers reported but
  computed no win_prob"`, because `win_prob_null_diag._summarize` iterates
  `latest` only and both services' latest run was an empty one. The summary
  erases an exercised run as soon as any later run reports `rows=0`.
- **The log line is dead and a scheduled task is watching it.**
  `WIN_PROB_NULL_NO_PRICE`: zero matches on both workers over ~16h (since
  23:31Z / 23:17Z) while the counter recorded 18 runs. Probe proven live first
  (positive control: 940 lines / 11 pages, 15:15–15:22Z). Scheduled task
  `wnba-win-prob-counter-read` used to grep that line and would have reported
  "not yet run" forever — **REPOINTED 2026-08-16 at `scripts/read_win_prob_null.py`**
  (every 4h, reports only on change). Nothing should read that log line again.

**AND THE COUNTER BUILT TO MEASURE IT COULD NOT BE READ. `[measured 08-15/16]`**
The `WIN_PROB_NULL_NO_PRICE` counter deployed to both workers (refresh-worker
`903d09c5`, live-odds-worker `b7ae47e6`) `print()`s to stdout, and
`refresh_odds_sources._run_command` runs every producer under
`subprocess.run(capture_output=True)` and **discards a successful step's stdout**
(bounded stderr tail only, and only on FAILURE). Same trap `ops.py:2263`
recorded on 2026-08-01, for this same script.
- **The producer DID run and the line still appeared nowhere.** live-odds-worker's
  own `ALL_PROCESS_MEMORY` census at 23:36:05Z lists PID 1900
  `refresh_wnba_oddsapi_props.py --date 2026-08-15 --do-edges --do-export`
  (started 23:36:04Z, ppid 1880), while a bounded log read across the whole
  window since the deploy returned **zero matches on both workers**. So "the
  producer has not run yet" was the WRONG reading — the silence was the
  emitter's, not the code's.
- **DEPLOYED 2026-08-16 TO ALL THREE:** refresh-worker `b2af0fac` (01:13:32Z,
  since carried forward by another session's `3e1994a2` — verified BY CONTENT),
  web `fa1871cf` (01:15:37Z), live-odds-worker `3573a0c3` (01:59:59Z).
  `/api/ops/win-prob-null` answers **200** and reports
  `reports_root=/opt/render/project/data/reports`. **CHANNEL PROVEN 02:02:33Z by a
  real cross-service reading:** `wnba/live-odds-worker rows=0 null=0`,
  `generated_at` 02:01:19Z (80s after the deploy), `commit 3573a0c3` — worker
  wrote, web read. **NOTHING ABOUT THE `or 0.5` FIX IS CONFIRMED: `rows=0` means
  that run computed no `win_prob` at all, so `null=0` is arithmetic on an empty
  denominator, not evidence.** (**That `rows>0` reading has since ARRIVED — see
  the measured block above; do not re-open this as outstanding.**) A live-odds-worker WNBA producer run was observed at 01:31:36Z, before
  that service had the writer; the next one after its 01:59:59Z reboot is what
  produces the first reading. live-odds-worker has NO idle window during live
  hours (10 of 10 samples across 25 min had jobs running), so this deploy killed
  ~3 in-flight jobs by design, not by accident.
- **FIXED IN CODE, `b281bc7f`.** Both producers now also publish
  through `write_json_file` (per-service key under `reports_root()`, verified
  identical on all three services), readable at **`/api/ops/win-prob-null`**.
  Needs **both workers** (writer) **and web** (reader) to be worth anything.
- Reading guide, so the next reader does not re-derive it: `rows=0` = ran,
  computed no `win_prob` (says nothing about the fix; correct for out-of-season
  NBA); `rows>0, null=0` = fix holding AND exercised; `null>0` = the branch
  fired and published `None` instead of a fabricated `0.5` — **the fix working**.

**`main` IS NOT A SUPERSET OF THE WORKERS — do not "just deploy main".**
`memory_observability.py` is **0 insertions / 366 DELETIONS** from
refresh-worker's live `dca39fad` to `origin/main`. Building on main would strip
`#435` instrumentation off production. Whether main's smaller file is the
INTENDED state is an open question with the memory lane; merging the worker
lineage into main conflicts in **30 hunks across 6 files** of two other lanes'
live code.

**Repo state `[measured 08-15 20:3xZ]`:** the shared tree is **13 AHEAD / 151
BEHIND** `origin/main`. Being behind is a read-your-own-staleness problem; being
ahead is a **lost-work** problem. `git fetch` and read `origin/main` for lineage.

**THE DIVERGENCE RECURS ON A TIMESCALE OF HOURS AND IS STRUCTURAL, NOT A LAPSE.**
Reconciled at 17:0xZ as `6822d539` — local `main` was 33 ahead / 136 behind with
**32 commits genuinely unpushed by patch-id** across six lanes. It was 13 ahead
again within the hour. **Cause: sessions commit to local `main`, while every
deploy-shaped push goes to `origin` through a throwaway worktree**, so the two
lineages separate continuously. Until that workflow changes, assume unpushed
work exists and check `git cherry origin/main main` before any reset, checkout
or fast-forward. A snapshot of the uncommitted tree is on branch
`safety/worktree-snapshot-2026-08-15` (`ad504d57`) — five files were genuinely
unsaved anywhere.

---


## [services-config-platform] SERVICES, CONFIG, PLATFORM

- Web is **`https://syndicate-an21.onrender.com`** (`srv-d88ahvrbc2fs73eodu30`).
  `syndicate.onrender.com` 404s.
- `refresh-worker` `srv-d91dpertqb8s73co8ls0` (4 GB) — sim/board.
  `live-odds-worker` `srv-d91dpertqb8s73co8lt0` (1 CPU / 2 GB / 50 GB disk) —
  odds. Web (2 GB) — display only.
- **The boot-time git->disk sync (`bootstrap_data_root`) runs on WEB ONLY.**
  `_bootstrap_render_data` is called from `create_app()` and nowhere else
  (repo-wide grep 2026-08-20); neither worker entrypoint imports
  `syndicate.app`, and both are `type: worker` running a plain script.
  `SYNDICATE_BOOTSTRAP_ON_START=1` is set on ALL THREE services and read by
  nothing on the two workers — **the env var is the trap, the code is the
  answer.** This voids `#357`'s counter-argument that `team_history` "should be
  on the disk" via bootstrap on refresh-worker.
- **That sync is SEED-ONLY as of `32148cac`** (web `15a0be64`, live 22:36:32Z):
  artifact roots copy only when the destination is ABSENT, so the committed
  mirror can no longer overwrite live pipeline output. Vendored code
  (`vendor/wnba_betting_repo/src`) keeps overwrite; `SYNDICATE_BOOTSTRAP_FORCE_
  OVERWRITE=1` re-arms the old behaviour. Measured on the real disk 23:35:55Z:
  `Bootstrap totals: copied=0 unchanged=33354 kept=25`, of which
  `soccer_source kept=24`. Before the fix, **1,114 of 8,016 hot artifacts web
  served were byte-for-byte the git checkout's copy** (allowlist only; the sync
  walks ~33k files). `#494`.
- **The bootstrap lock is CONTAINER-LOCAL** (`/tmp/syndicate_bootstrap_sync.lock`)
  as of `35daa092` (web `f3a9bb0b`, live 23:34:33Z). It used to live on the
  persistent disk, so a killed sync left a lock that made the NEXT container skip
  its sync for 30 minutes — measured 2026-08-20 22:37:52Z. The holder's liveness
  is now checked, which is sound only because the lock is container-local (PID
  namespaces restart with the container).
- **NOTHING under `reports/intelligence/` is bootstrapped, and it must stay that
  way** (`#496`, `0dd9c6cd`). `BOOTSTRAP_FILES` and the per-date globs had never
  copied a byte — `_sync_tree` returns immediately for a non-directory — while
  the loop logged `Syncing <file>` for each; confirmed in production 23:35:55Z.
  **Deleted, not repaired.** On the keyvalue backend every
  `reports/intelligence/**` path reads from Redis with no filesystem fallback
  (`_KEYVALUE_EXCLUDED_PATH_MARKERS` is `("migration_runs/",)`), so a seeded file
  has no readable CONTENT — but its FILENAME and MTIME are what
  `_intelligence_state_read_path` and `blueprints/intelligence.py` use to decide
  which date is latest, so seeding months-old copies would inject dates with
  nothing behind them. Zero intelligence files have been bootstrapped since
  2026-07-03 (`2fc3673e`, itself a fix for deploys OOM-ing on a 3.2 GB
  `evaluation_ledger.jsonl` pulled in by the old whole-directory sync) with no
  incident attributed to a missing seed. `test_no_bootstrap_pair_points_into_
  reports_intelligence` now also blocks the directory root that caused that OOM.
- **`SYNDICATE_ENABLE_INTELLIGENCE_STATE_BACKGROUND_LOOP` is `true` on
  refresh-worker ONLY** (`false` on web and live-odds-worker);
  `SYNDICATE_INTELLIGENCE_REFRESH_INTERVAL_SECONDS = 60` on all three.
- **Web does not run the loops that call `memory_headroom_snapshot`**, so guard
  changes are inert there — which matters because web is a 2 GB container with an
  OOM history. Re-raise if any flag flips.
- **Both workers publish over the internal hostname**
  (`http://syndicate-an21:10000`), not set on web, correctly. **`syndicate-an21`
  RESOLVES FINE** — the "it names a host that does not exist" claim was an
  inference from Render's naming convention and is FALSIFIED.
- **Keyvalue store is 256 MB, `allkeys-lru`, shared by web + both workers, and
  cannot be upgraded.** `/api/ops/keyvalue/usage` reports allocator bytes;
  deltas are block-quantised. `reports/live_refresh_loop/**` is deliberately
  keyvalue-backed and therefore shared across all three services.
- **Board snapshot and `query_state_cache` are compacted then zlib+base64
  compressed** (31.4 MB → 812 KB). **Any reader must call
  `expand_persisted_state` first** — a raw read returns an envelope that still
  passes `isinstance(dict)`, so it degrades silently rather than raising. This
  has bitten four ops diagnostics.
- **`render.yaml`'s web `envVars:` anchor is never referenced anywhere**, so
  nothing was ever shared and worker-only keys accumulated on web for months.
  Web block cut 62 → 52. Blueprint drift: 0 values a sync would revert — a
  snapshot only.
- **"On origin" is not "in production."** Web's live service carries 73 env vars
  against 52 declared. Read `/v1/services/<id>/env-vars` before recording any
  config change as shipped (paginate — `limit` > 100 returns HTTP 400).
- **Absent ≠ off.** Check the code's default for any key added or removed.
- Artifacts are on **Render persistent disks**, forcing single-instance services
  and stop-then-start deploys with downtime. Cross-disk access is a hard
  requirement; web and worker disks cannot be shared.
- **live-odds-worker disk usage climbing ~20% → ~40% of 50 GB over two weeks.
  Not yet diagnosed.**
- Egress was fixed at root (public → internal publish URL); Aug overage was
  ~2.1 TB against 25 GB included. **Never point a worker publish URL at a public
  hostname.**
- **Odds capture is 65.7% of platform bytes and ~97% MLB** — one day of
  `mlb_source/tracking/book_quotes` is 329.5 MB. It is also the ONLY record of
  line movement. The tradeoff between cutting bytes and keeping movement history
  is mostly false: full-state snapshots at 60s re-record unchanged quotes, so
  delta/columnar storage cuts it by a large multiple while preserving movement.

---


## [session-harness] SESSION HARNESS — what the hooks actually enforce

- **THE LEDGERS ARE KEYED AND CHECKED** `[verified 2026-08-18]`. One checker per
  ledger, all three ENFORCED in CI and reported at session start as
  `LEDGER INCOHERENT`: `scripts/lane_identity_check.py` (slug, one OPEN block,
  one home), `scripts/todo_id_reconcile.py` (numeric id in exactly one of
  `todo.md`/`todo_closed.md`), `scripts/state_key_check.py` (every `## [slug]`
  unique). All three verified to EXIT 1 on deliberately corrupted copies before
  being wired in — the gate is not vacuous. Green at checkpoint: lanes 54 blocks
  coherent, state 35 sections/35 subjects, todo 166 ids.
- **`state.md` sections carry a subject key** `## [subject-slug] TITLE`. One
  subject, one section; a shared slug IS the stacking failure. Added because "no
  duplicate titles" was trivially true while sections were titled by date.
- **`lane-guard.py` reads BOTH Files forms and wrapped continuation lines**
  `[verified 2026-08-18: file-like claims 52 -> 80]`. It previously matched only
  `- Files:`, so 5 lanes using `- **Files (...):**` declared paths NO HOOK COULD
  SEE. A disclaimer now governs only what FOLLOWS it, not the whole line.
  `_DISCLAIMER_MARKERS` gained `"not touch"` (covers "does not touch"/"not
  touch"/"not touched" — subsumes the prior "not touched" entry),
  `"read-only reference"`, and `"not taken"` `[verified 2026-08-19, commits
  0a7fdbeb + f52fc91b + a1cbcde1, all on origin/main]`; each closed a real
  false-positive that had blocked a lane from a file its own ledger text
  explicitly disclaimed. `"not taken"` is a NEW failure shape, not a repeat:
  a lane correctly got blocked from a file it did not own, recorded that
  block as its own disclaimer ("BLOCKED, not taken: ..."), and THAT SENTENCE
  then re-read as a phantom counter-claim, blocking the file's actual,
  correctly-enforced owner from editing their own file — a disclaimer about
  the guard's own prior correct enforcement, not about a file the writer
  never touched.
  Claim matching is exact-or-suffix (`rel == f or rel.endswith("/"+f) or
  f.endswith("/"+rel)`), never a directory prefix — so a non-path token claimed
  out of prose is INERT.
- **`lane-guard.py` (PreToolUse) enforces.** Blocks `Edit`/`Write` against a file
  claimed by another OPEN lane (exit 2); allows it when `.syndicate/.current-lane`
  names the claiming lane. **With the marker empty it blocks your OWN lane's
  files**, reporting `Current lane: 'none'` — so a session that hand-edits
  `lanes.md` instead of running `/lane` locks itself out.
- **`Bash` bypasses it entirely** — the matcher is
  `Edit|Write|MultiEdit|NotebookEdit`. The guard bounds the file tools, not the
  session.
- **A HOOK THAT RESOLVES PATHS AGAINST `CLAUDE_PROJECT_DIR` IS ANSWERING ABOUT
  THE WRONG REPOSITORY** `[verified 2026-08-20, shipped 58c63b62]`. Every session
  works in its own linked worktree, so `CLAUDE_PROJECT_DIR` is the PRIMARY
  checkout while the tool call targets the worktree. Both failure directions were
  MEASURED: `ledger-commit-guard.py` blocked a `soccer-board-mlb-parity` commit
  over duplicate lane blocks that existed only in the primary tree (its own
  `lanes.md` was clean, `check_lane_invariants.py` said INVARIANTS HOLD), and it
  had never once examined a broken `lanes.md` in the committing worktree.
  `ledger-append-guard.py` was worse — **fully INERT in every worktree**:
  identical violating edit gave `primary exit=2 BLOCKED` / `worktree exit=0
  ALLOWED`, because `relpath(file, PRIMARY)` is `../../../../../tmp/...` and
  matched neither ledger name. **An inert guard and a satisfied guard are
  indistinguishable from outside**, which is why it survived unnoticed.
  `commit-guard.py` had already been fixed for this on 2026-08-16; the fix was
  local to that file, so the next guard written re-made it. Shared resolver now
  in `.claude/hooks/commit_context.py`.
- **A `VAR=1 <cmd>` OVERRIDE PRINTED BY A PreToolUse HOOK IS UNREACHABLE UNLESS
  THE HOOK PARSES THE COMMAND STRING** `[verified 2026-08-20]`. The hook runs
  BEFORE the shell assigns it, so `os.environ` never sees it. Same defect
  `commit-guard.py` fixed 2026-08-17; `ledger-commit-guard.py` shipped with the
  broken form and printed an escape hatch that did not exist. A real exported
  environment variable always worked.
- **`lane-guard.py` is NOT affected, and the reason is accidental**
  `[verified 2026-08-20]`. A worktree path yields the same mangled relpath, but
  claim matching is exact-or-suffix (`rel.endswith("/" + f)`), which matches it
  anyway. It blocks correctly; only its refusal MESSAGE prints the
  `../../../../../tmp/...` form. Do not "fix" it by changing `root` — for
  lane-guard the PRIMARY `lanes.md` is the CORRECT source, because cross-session
  claim exclusivity is inherently global. That is the opposite of
  `ledger-commit-guard`, which must read the tree being committed.
- **`ledger-postwrite-check.py` FIXED** `[verified 2026-08-20, `f73d163e`]`. It
  now watches the worktree the command ran in AND the primary checkout, deduped
  to one scan when they are the same, with per-tree state so neither silences
  the other. It had been blind to worktree Bash writes — **the one thing it
  exists to catch** — and it blamed whichever session happened to observe the
  change (seen firing at a `grep`). It reports that a file CHANGED and is
  broken, says it may be another session, and NAMES THE TREE. Two things the
  work turned up, both measured: `abspath` does not expand Windows 8.3 short
  names, so the same tree deduped as two and was reported twice (caught by a
  "reported exactly once" assertion, not by inspection); and finding the root
  via `git rev-parse` costs **41ms on EVERY Bash call** vs **0.0ms** for a
  filesystem walk to the directory holding `.syndicate/lanes.md` — same answer,
  so the walk is used. End-to-end 162ms → 106ms, ~100ms of it Python booting.
- **ALL FOUR HOOK SUITES ARE ENFORCED IN CI** `[verified 2026-08-20 on the
  Linux runner, `86ec6b42`, run 32415246596 green in 3m18s]`: 16/16, 17/17,
  16/16, 10/10. Enforced, not `continue-on-error`, because each was
  **mutation-tested** first — disable the predicate under test and every suite
  goes red, so a green run means the guards work rather than that the suite is
  vacuous. All four build throwaway repos under the OS temp dir; they are
  stdlib-only, shell-free and need no repo history, so CI's shallow clone cannot
  bite them the way it does `todo_id_reconcile`. **They never read the live
  ledger** — the first version did, and a parallel session trimming real
  duplicates mid-run flipped three cases from pass to fail.
- **`lane-guard` is blind to `.claude/**` AND `.syndicate/**` by design**
  (`lane-guard.py:244`, one `rel.startswith` test covering both), so the
  enforcement layer cannot protect the directory it lives in — and every real
  collision has happened there. **The `.syndicate/**` half matters just as much
  and was missing from this line until 2026-08-18:** no lane claim can ever
  guard `lanes.md`, `state.md`, `deploys.md` or `learnings.md`, so concurrent
  ledger writes are unprotected by design and a phantom claim on a ledger file
  is inert rather than a lock. Measured during the 2026-08-18 orphan sweep:
  `basketball-model-owner`'s Files block claims bare `lanes.md` (a prose
  collision-check sentence the parser reads as a claim) and it blocks nobody —
  while an unrelated session's write to `lanes.md` landed **between** two of
  that sweep's own edits, reported by the Edit tool as "modified on disk since
  you last read it". Anchor ledger edits on unique strings, never on line
  numbers, and re-read before any edit that depends on surrounding content.
- **`commit-guard.py` (PreToolUse) reads the index the COMMIT will use, fixed
  `a52a2b64` 2026-08-16.** It previously evaluated both predicates against
  `CLAUDE_PROJECT_DIR` — the MAIN worktree — while the commit runs wherever the
  shell is, which for this repo's own contended-tree recipe is a LINKED worktree
  with its own index and its own HEAD. **It blocked three clean commits in one
  session**, and, the half that matters, **would have passed a stale index in the
  worktree actually being committed from without a word.** Now resolves
  `cd` → `-C` → payload `cwd` → project dir, then `rev-parse --show-toplevel`.
  `git -C <dir> commit` is CHECKED (it was skipped for "has its own index";
  having your own index is not having a fresh one). **`--git-dir` /
  `--work-tree` remain a KNOWN GAP** — index and tree decouple, so "is it still
  on disk" has no single correct base. 13 tests on real repos
  (`tests/test_commit_guard_worktree_index.py`); pre-fix 7 fail, post-fix 13 pass.
- **`commit-guard.py` reads the COMMAND, not a proxy for it, fixed `5fb52342`
  2026-08-17.** Two exemptions, both measured:
  (a) **all THREE documented overrides were unreachable.** They were
  `os.environ.get(...)` — the HOOK's env — but a PreToolUse hook runs BEFORE the
  shell, so the `export GIT_INDEX_FILE=…` in the recipe the guard PRINTS, and
  the `SYNDICATE_ALLOW_STAGED_*=1 git commit` prefix it prints as the override,
  were both invisible to it. A session that followed the refusal message was
  refused again. Assignments are now parsed out of the command string,
  last-write-wins against `unset`.
  (b) **a pathspec-limited commit is exempt whole.** MEASURED 2026-08-17 against
  an index holding a revert of `A.txt` plus a `D` of on-disk `C.txt`:
  `git commit -m x -- C.txt` produced a tree keeping BOTH, `--stat` 1 file;
  `--pathspec-from-file=` and `--amend -- <paths>` likewise. A partial commit
  builds from HEAD plus the WORKING TREE content of the named paths and never
  consults the index — not even for the named paths — so there is no path left
  to evaluate. **`-i`/`--include` NOT exempt** (the revert landed).
  **`-a` NOT exempt** (it kept the line but COMMITTED the deletion, so predicate
  1 is live under it); `-a` remains a known false positive for predicate 2,
  left alone because `-a` does not refresh `skip-worktree`/`assume-unchanged`
  and that case is unmeasured. Unrecognised options fall through to "keep
  guarding" — false positive, never false negative. Verified by running 19 cases
  through the pre-fix and post-fix guards together: 10 flip 2→0, 8 hold at 2.
  **62 tests in `tests/test_commit_guard_worktree_index.py`** (69 for the
  two-file run that also covers `test_checkpoint_guard_hook.py` — cite the 62 if
  you mean this guard); exemption path 81 ms, short-circuiting before any git
  call.
- **A PATHSPEC COMMIT NEEDS NO REPAIR STEP; THE ISOLATED-INDEX RECIPE DOES.**
  Measured on `5fb52342`: the partial commit UPDATED the shared index for the
  three paths it committed (`git diff --cached` for them empty afterwards) and
  left another session's staged work untouched. The isolated-index route, by
  contrast, is recorded in `learnings.md` 2026-08-15 as arming a revert of the
  file you just committed, every time, requiring a follow-up
  `git restore --staged`. The guard's refusal message now leads with the
  pathspec form for this reason.
- **`commit-guard` matches the COMMAND STRING**, so bundling a file write or a
  `git reset` into the same command as `git commit` blocks the whole thing.
  Separate them. `[recorded by another lane 2026-08-16]`
- **THE ARCHIVE PASS ITSELF CREATES ORPHANS, and that is a second mechanism, not
  a repeat of the one below.** Moving a CLOSED lane to `lanes_closed.md` takes
  the header and whatever body existed AT THAT MOMENT; any bullet the owning
  session appends afterwards lands in `lanes.md` with no header above it and is
  silently adopted by whichever lane precedes it. Measured 2026-08-15: two
  blocks of `model-audit-devig-and-hygiene` ended up under
  `nfl-live-edge-suppression` and `live-game-line-projection`, and **a later
  collision check therefore reported a FALSE claim on
  `scripts/backtest_mlb_props.py`** — the guard reading a real file claim that
  belonged to nobody. Reconciled 2026-08-15; line arithmetic verified exact.
  **When archiving, re-check the source lane for appends made after the move,
  and when a collision check names a file, read the matched text before trusting
  the slug it is attributed to.**
- **A lane's guard state hangs on ONE header line in a hand-edited shared file,
  and its deletion is silent.** A header once vanished while its body stayed, and
  all 4 of that lane's claimed files went to exit 0. Nothing detected it; it was
  found by reading a diff. Both hooks now take the field between the 1st and 2nd
  em-dash and match the WORD `OPEN` in it.
- **`checkpoint-guard.py`'s witness is this session's OWN transcript;
  `.last-checkpoint`'s mtime is never read.** The marker is repo-global, so its
  mtime answers "did somebody checkpoint", not "did I" — reading it let session
  A's checkpoint silence session B's warning, losing B's work silently.
  `.syndicate/**` is excluded from work-at-risk: it is the persistence, not the
  thing persisted. **Exit 1 on Stop is advisory**, not a gate.
- **The 3-lane cap in policy has no enforcement** — `/lane open` checks file
  collisions only and never counts. Eight lanes are open today.

---


## [oom-kills-census] KILLS ARE EVENTS — there is now a tool, and a census `[measured 08-16 17:5xZ]` — **ARCHIVED 2026-08-19 to `state_archive_2026-08-19.md`, verbatim.**

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


## [odds-cadence] ODDS CADENCE AND CAPTURE

- **MLB quote capture has THREE regimes, not one beat. `[measured 08-15 02:5xZ,
  supersedes the single-cadence reading of 08-14 16:3xZ]`** All 371,567 rows of
  `mlb_source/tracking/book_quotes/2026-08-14.jsonl`, streamed from web and
  bucketed by distinct `captured_at`:
  | window (UTC) | slate | gap |
  |---|---|---|
  | 07:03→15:10 | pregame, nothing live | **121 / 121 / 123 / 121 min** |
  | 16:20→18:25 | first games start | 70 / 61 / 64 min |
  | 18:36→20:54 | ramping | 11–12 min |
  | 21:48→02:53 | full live slate | **~1 min, continuous** |
  **121.6 is exact and it is the EMPTY-SLATE PREGAME number only.** The same
  pipeline samples 122× faster once games are live. Never quote it unqualified.
- **SUPERSEDED IN PART — there is a THIRD regime, and it dominates.
  `[measured 08-15 16:38-17:00Z, deploy-free window, 22 samples]`**
  On 08-15 the pregame beat was **~60 min, not 121.6**, and then MLB capture
  starved for **5.8 h**. Cause is neither the tick nor the cooldown: a chain of
  back-to-back refresh **run-locks** (`ops_refresh.py:669`, per-lane, NOT the
  separate `JOB_CAP_THROTTLED` job cap -- an earlier version of this line
  conflated them; raising the job cap would not have helped), each
  held ~25 min with ~2 min free — **~92% occupancy, traced 11:39→17:00Z**.
  17 consecutive ticks refused by `pid=4047`; the ONE tick that got through at
  16:56:26 took end-to-end from **20,880 s to 32 s**, then `pid=5681` retook it.
  **End-to-end is BIMODAL: ~32 s or hours, never in between.** In the starved
  regime the number rises exactly 1 s/s — it is a clock, not a latency.
  **`PREGAME_RELAUNCH_COOLDOWN_SKIPPED` fired ONCE in 5.75 h** (counted on
  live-odds-worker, the correct emitter, with a liveness control), so **Tier 0's
  `0.1` would NOT have prevented this** and is not the Tier 5 prerequisite the
  program plan calls it. Full working:
  `.syndicate/tier5_quote_to_ui_WINDOW2_2026-08-15.md`.
- **WHY 60s BECOMES ~7,300s, two multipliers, both measured `[08-14 17:0xZ]`:**
  1. `SYNDICATE_LIVE_ODDS_REFRESH_INTERVAL_SECONDS=60` is the TICK interval,
     never the launch interval.
  2. **The pregame relaunch cooldown is 1800s and GLOBAL** —
     `_pregame_relaunch_blocked` reads ONE marker keyed by **date only, not by
     sport and not by service**, so a launch for ANY sport starts the clock for
     EVERY sport. 30×.
  3. **Sports rotate across launches**, so MLB rides roughly 1 in 4. ~4×.
  **The leverage is a design fact, not a tuning value: because the cooldown is
  global, every sport added dilutes every other sport's cadence.** A per-sport
  cooldown decouples them; that is the change worth considering, not lowering 1800.
  4. **BUT THE COOLDOWN IS GATED ON PREGAME PHASE AND IS BYPASSED WHENEVER ANY
     GAME IS LIVE. `[measured 08-15 02:5xZ]`** On the deployed tree:
     `effective_phase = ("live" if any_live else "pregame")`, then
     `if ... effective_phase == "pregame" and _pregame_relaunch_blocked(...)`.
     `latest_tick` carried `adaptive:true, anyLive:true, phase:"live"`. So both
     multipliers above apply **only to the empty-slate pregame regime**.
- **The per-sport cooldown fix (`ea8fad58`) is NOT deployed on ANY service.
  `[measured 08-15 02:4xZ]`** Checked by reading the deployed trees, not
  ancestry: `git show <sha>:syndicate/features/shared/live_refresh_loop.py`
  gives `def _pregame_relaunch_blocked(*, now_epoch, date_str)` — no `sports`
  kwarg — on both `548ded38` (refresh-worker) and `ccd10349` (live-odds-worker).
  **`ea8fad58` IS an ancestor of `origin/main`, so an ancestry-only check says
  "shipped" and is wrong.** `autoDeploy` is off; being on `main` ships nothing.
- **WHICH SERVICE DRIVES CAPTURE IS AN OPEN DISCREPANCY — re-check the env
  before relying on either answer. `[measured 08-15 02:5xZ]`** The env API now
  reads the OPPOSITE of this file's 08-14 line: live-odds-worker
  `SYNDICATE_ENABLE_LIVE_ODDS_REFRESH_LOOP=true` and
  `SYNDICATE_MLB_REFRESH_TICK_OWNER=true`; refresh-worker `false` on both; and
  the 02:35:20Z tick wrote `refresh_status_latest__live-odds-worker.json`.
  **But** `ODDS_SWEEP_OUTCOME` since 02:00Z is refresh-worker **16**,
  live-odds-worker **0**, which matches the old line. The emitter
  (`live_refresh_loop.py:4100/4117`) is reachable from the board-build sweep as
  well as the loop tick, so both emitting is not itself a contradiction.
  Unresolved; resolving it needs the board-build loop. Loop ownership is an env
  flag that moves with no diff — that rule is why this line is now a question.
- **This is the real cause of "candidates that are no longer bettable"** — the
  board's MLB prices are up to ~2 hours old by construction.
- **Consequence for the whole movement family — REAL CONSTRAINT IS THE BUFFER
  DEPTH, NOT THE FETCH RATE. `[measured 08-15 02:4xZ, supersedes "sampled
  roughly every two hours"]`** From
  `/api/ops/odds-history/inspect?sport=mlb&date=2026-08-14`, 3,582 markets:
  sampling interval within the retained history is **p50 1.0 min** (live 0.9,
  pregame 1.0) — not 2 hours. But `history_points` is **capped at 20**
  (`_ODDS_HISTORY_LIMIT`, `shared/odds_refresh_tracking.py:40`, env-tunable via
  `SYNDICATE_ODDS_HISTORY_LIMIT` which is **unset on all three services**), and
  3,130 of 3,582 markets sit exactly at the cap. Retained span is therefore
  **p50 17.8 min**. The code's own comment concedes it is *"narrower than the
  steam detector's stated 45-min window for hot markets."*
  **So a movement calculation sees ~18 minutes and is structurally blind to
  whether the previous sweep was 1 minute or 2 hours earlier — the
  pregame→live transition, the biggest move of the day, falls out of the buffer
  within 20 minutes of first pitch.** Re-examine `movement_velocity` and the
  steam detector against `_ODDS_HISTORY_LIMIT`, not against fetch cadence.
  Raising it trades against the 8 MB keyvalue ceiling that forced it to 20.
- **A `too_large` line does NOT mean the artifact failed to publish.** The
  ceiling lives in `_publish_skip_reason`, which is **sweep-only**; the direct
  path streams and never consults it. Verified byte-identical on web. Four
  sessions have now misread this. `[measured 08-14 16:2xZ]`

### OddsAPI budget `[measured 08-14 17:2xZ]`

- **Projected 30-day burn 4,640,809 credits = 92.8% of the 5M cap.** Headroom
  ~360k/month. MLB is **93.7%** of spend (8.72 cr/call); soccer 4.2% (1.46
  cr/call, 6× cheaper); nfl 1.4%; wnba 0.7%. Live hours dominate (83–228k/hr)
  against pregame's 10–18k/hr.
- MLB pregame sweep interval is 3600s with an effective gap of **~1h10m**
  (7,289s → 4,215s). The loop wakes every 900s and sweeps whatever is past its
  interval, so the setting is a FLOOR the tick quantises.
- **Any cadence increase spends against the cap — it is a product decision, not
  a tuning tweak.**

---


## [probability-statistic-ownership] PROBABILITY-STATISTIC OWNERSHIP `[measured 08-15, shipped `2ac3c6bc`]`

- **THE AUDIT'S "TWO DE-VIG ORDERINGS" IS FALSIFIED. In the BOARD/ODDS path
  there is ONE, and `book_grid` is not a second.** `book_grid` never de-vigs — its whole import
  surface from the odds layer is `_implied_probability`, `_line_value`,
  `market_sides_for_quote`. The canonical ordering (`devig` →
  `fair_probability_by_book` → `consensus_fair_probability` median) already had
  both consumers (`layer2_board._fair_by_side`,
  `odds_book_quotes._fair_value_fields`). **Ranked #5's exit criterion was
  already satisfied. Do not re-open it as a de-vig collapse.**
- **What was duplicated is a VIGGED statistic**, hand-rolled in `book_grid` and
  `odds_book_quotes`: mean implied probability across books → a price. It is a
  PRICE-SHOPPING reference, margin-inclusive, and **not** a fair value; it is
  bounded below by zero against the best price by construction. Now owned by
  `opportunity_signals.consensus_vigged_price`. Removes 2 of Tier 3a's 31 copies.
- **Both copies diverged from the owner at the boundary:** p=0.5 → owner
  **+100**, copies **−100**; p∈{0,1} → owner refuses, copies raise
  **ZeroDivisionError**. Reachable, because
  `odds_book_quotes._implied_probability(0)` returns **0.0** rather than
  refusing. **The ±100 flip moves no derived number** — `implied(+100) ==
  implied(−100) == 0.5`, so `edge_vs_consensus_pct` is unchanged.
- **SCOPE, because the line above is easy to over-read:** "one ordering" is
  about the board/odds path only. Sport-local SIM market-anchoring has its own
  de-vig implementations and they were deliberately NOT touched —
  `soccer/features/market_anchoring.py::devig_decimal_odds`,
  `nhl/sim_engine/hockeysim/market_anchoring.py::devig_two_way_home_prob`, plus
  `scripts/backtest_soccer_h2h_calibration.py` and
  `scripts/validate_soccer_vs_market.py`. **The soccer ones are claimed by
  `soccer-model-coverage`.** These are the same engines `state.md` already flags
  as market-anchored and therefore partly circular; unifying them is a modelling
  decision, not a converter cleanup. `[verified 08-15 by repo-wide search with
  `.claude/worktrees/` excluded — those hold full repo copies and triple-count]`
- **Both production copies of the vigged mean are GONE, verified by search:** the
  only `mean_implied` left outside worktree copies is in
  `tests/test_devig_unification.py`, which reproduces the legacy arithmetic on
  purpose to prove valid prices did not move.
- **`edge_vs_consensus_pct` is now ABSENT rather than `0.0` when the consensus
  refuses, and that is verified no-break** across 6 consumer suites (92 green),
  including `tests/test_quote_ref.py`, which asserts the field directly.
  **The only real `book_grid` consumer is `nfl/preseason_cards.py`, reached
  through `read_book_grid_artifact` — an ARTIFACT HOP, so it does not import
  `book_grid` and an importer search cannot find it.** It already tolerated a
  `None` side, because `consensus[side] = None` was reachable before this change
  via the empty-prices branch. `prop_projections`' `consensus` key is a
  different producer's. `[measured 08-15]`
- **`/preflight` now prints the deployed commit of ALL THREE services** (D5),
  degrading a per-service read failure to that row rather than to the gate.
- **MLB prop skill numbers are now OUT-OF-SAMPLE. `D4` CLOSED `[measured 08-15]`.**
  Fitted on 2026-08-01..08-06 (n=1,246), scored on 08-07..08-13 (n=1,241), from
  production artifacts via `/api/ops/artifacts/stream` — **the checkout cannot
  do this** (864 `daily_summary` files, all 05-28..07-12, zero in August).
  Harness validated first: every in-sample figure reproduces the published table
  exactly, so the split reads the same data the module was built from.
  - **6 of 7 in-sample becomes 5 of 7 out of sample, and EXACTLY ONE verdict
    flips — `batter_hits`, the market the module quotes first.** In-sample
    margin **+0.0007**, which is smaller than the 4-dp rounding of its own
    published table; out of sample it LOSES by 0.0081. It never was a result.
  - **The leakage was NOT inflating everything** — four markets IMPROVE out of
    sample (`tb` +0.0256→+0.0313, `rbi` +0.0210→+0.0285, `r` +0.0243→+0.0289,
    `2b` +0.0009→+0.0044). It manufactured a win only where the margin was
    already indistinguishable from zero. **Do not assume the same shape of every
    other backtest here; measure it.**
  - **The BIASED-NOT-BLIND headline SURVIVES.** Correlations fall consistently
    and stay positive (hits .1607→.1487, tb .1523→.1262, rbi .1316→.1156, r
    .1620→.1520, sb .1605→.1322).
  - Each market carries `oos_debiased_beats_baseline` / `oos_margin` /
    `oos_correlation`; the served row's `debias_validation` is `out_of_sample`.
  - `hrr` is still a degenerate constant 0.0 in this window, so its absence from
    `_MARKET_SKILL` remains correct and `unmeasured` remains the truth.

---


### The ±4900 fair-price clamp — web + refresh-worker FIXED. live-odds-worker STILL CARRIES IT. **STILL NOT VERIFIED.**

- **THE WEB-ONLY DEPLOY WAS FALSIFIED IN PRODUCTION** `[measured 08-15 23:10:13Z
  and 23:15:46Z]`. Two triggers, two unrelated slates, both `PRE_FIX_MISPRICE`
  while a fix-carrying web SHA was live: nfl `h2h_3_way` 0.014698 → **+4900**
  (correct +6704); mlb `spreads` 0.009911/0.990089 → **±4900** (correct ±9990).
  `reports/clamp_watch/trigger_20260815T231013+0000.json`, `..._231546+0000.json`.
- **WEB IS NOT THE PRODUCER AND ITS FIX IS STRUCTURALLY INERT.** The block is a
  **backfill** — `if fair_probability is not None and card.get("fair_price") is
  None:` — so a value clamped upstream passes through untouched. Web can only
  act when the field arrives ABSENT. The producer is the intelligence-state
  loop: `SYNDICATE_ENABLE_INTELLIGENCE_STATE_BACKGROUND_LOOP` is `true` **only
  on refresh-worker** (`render.yaml:499`).
- **refresh-worker FIXED: `57a437d5`, live 2026-08-16 00:23:04Z** — 0
  occurrences of `max(0.02, min(0.98` across all three files at the live SHA.
  Cut on live `2c14d9ae` (off-main deploy branch).
- **live-odds-worker STILL CARRIES THE CLAMP** on `c4116ab6`. Deferred by user
  decision — it does not run the intelligence-state loop, so it is not the
  producer. `079cc42b` is cut/tested/pushed on `deploy/clamp-workers-on-live`;
  **re-cut on the live SHA first**, that service moved 4× in 100 minutes.
- **STILL NOT VERIFIED** `[reads 08-16 00:24:04Z and 01:30:50Z]`: both
  `no_trigger` (12 then 68 rows, extremes 0.0687/0.8904). Same reading a quiet
  slate gives with the bug fully present. `out_of_clamp=0` is never evidence.
  Both of the real triggers came from **in-play** markets late in games.
- **A CLAIM'S TARGET IS AN INTENTION, NOT A DEPLOYMENT** `[measured 08-15/16]`.
  live-odds-worker's claim advertised clean target `49797f4b` for 45 min; it
  never landed. `c422f79a` then `c4116ab6` landed instead, both clamping.
  Verify by CONTENT at the live SHA.
- Superseded detail: web `e831263e`
  (`dep-da0d8vnlk1mc73fn8ta0`). **Survived two later deploys** — checked by
  CONTENT on each new live SHA (`bb23c8f9`, `8b010dac`): **0/0** occurrences of
  `max(0.02`. `render_deploy.py`'s descendant rule is what protects it.
- **THE FIX IS NOT VERIFIED IN PRODUCTION AND MUST NOT BE RECORDED AS SUCH.**
  The triggering row left the slate during the ~7 min build; the post-deploy
  read was `no_trigger`, which is the SAME reading a quiet slate gave before the
  deploy. **`out_of_clamp=0` is not evidence the fix worked** — that count comes
  from the WORKER's artifact and is independent of this web-side change.
  The watcher is running; **its next trigger is the verification**, and a
  `PRE_FIX_MISPRICE` against a fix-carrying SHA would be a real falsification.
- **BEFORE, measured:** nfl `h2h_3_way` away, JAX @ NO live,
  `fair_probability` **0.007934** published **+4900** vs correct **+12503**
  (off by 7603 pts). **That was ONE row echoed 14x in the payload, not 14 rows.**
- **`check_deploy_safety.py` IS REFRESH-WORKER SCOPED** `[measured 08-15]`. It
  has **no `--service` flag**; its blockers (MLB sim, odds refresh, board build)
  and its `--drain` are all refresh-worker work. **A `NOT CLEAR` from it does
  not, by itself, block a WEB deploy** — web runs **no background loops**
  (`MLB_ENABLE_LIVE_LENS_LOOP`, `SYNDICATE_ENABLE_LIVE_ODDS_REFRESH_LOOP`,
  `SYNDICATE_ENABLE_INTELLIGENCE_STATE_BACKGROUND_LOOP` all `false` on the live
  service). Read it, then decide per service.
- **`check_deploy_safety.py` ALSO REPORTS `CLEAR` WHILE JOBS RUN ON THE SERVICE**
  `[measured 08-16 00:13Z refresh-worker, reproduced 00:29Z live-odds-worker]`.
  It returned `CLEAR`, exit 0, "Odds refresh: idle" while that same service ran
  `run_refresh_odds_job.py` → `refresh_odds_sources.py` →
  `build_soccer_artifacts.py --league <X>`. **Gate a worker deploy on
  `safety_rc == 0` AND zero `[JOB]` lines in `deploy_preflight --service <svc>`**,
  re-verified in the same shell command as the POST.
- **Web deploy contention is REAL: 6 deploys in ~50 minutes** from concurrent
  sessions. Landing one took THREE cuts — `render_deploy.py` refused the first
  as a 189-line rollback, Render canceled the second 0.4s after a competing
  deploy started. Budget for re-cutting; never reach for `--allow-rollback`.

### (superseded header, kept for the file/line map) — FIXED IN CODE, ONE THIRD LIVE

- **All three `max(0.02, min(0.98, p))` sites are gone from `main`** (`de0c367f`
  WNBA, `7bb74c95` `layer2_board` + the INLINE copy in
  `pipeline/intelligence_state.py`). All now delegate to
  `opportunity_signals.american_price`. Harness scores each **5/5**;
  `probability_to_american` collapsed **4 behaviour clusters -> 3**.
- **ONLY the WNBA third is LIVE** `[measured 08-15 18:1xZ by CONTENT on
  `1e44e1da`, not by ancestry]`. `7bb74c95` is **committed, not deployed**.
- **The clamp published wrong prices** `[measured 08-15 ~03Z]`:
  `/api/intelligence/query` served 1346 `fair_price` with **24 exactly on ±4900,
  none beyond**; mlb totals under `p=0.992056` published **−4900** vs correct
  **−12488**.
- **`/preflight` on `7bb74c95` = FAIL, and the change is not the problem.** The
  defect is only observable when a slate carries `fair_probability` outside
  [0.02, 0.98], and it does not today (108 rows, p=[0.058, 0.638]). A deploy
  would move 0 → 0. **Do not deploy it as a standalone "verified" fix.**
- **`fair_price` is stamped at SERVE time, not in the artifact** — 0 of 108
  shortlist rows carry it against 1800 served. So this is a **web-only** deploy:
  no refresh-worker restart, no in-flight sim at risk.
- **THE INSTRUMENT EXISTS. Do not re-derive it:**
  `python scripts/watch_clamp_trigger.py --once` (add `--interval 900` to poll).
  Exits **10** on a triggering slate and classifies production from PUBLISHED
  CONTENT — `PRE_FIX_MISPRICE` / `POST_FIX_OK` / `no_trigger`. **`no_trigger` is
  stamped NOT-evidence** in every record. Log: `reports/clamp_watch/`.
  **Its discriminator is the PROBABILITY being outside the band, not the price
  being at ±4900** — `american_price(0.98)` is legitimately −4900, so the naive
  check reports a misprice against correct post-fix output.
- **NEXT:** on a `PRE_FIX_MISPRICE` record, that IS the before-measurement.
  **The user has standing-authorised the deploy on trigger (2026-08-15), and the
  full procedure is `.syndicate/runbook_clamp_deploy.md` — execute that, do not
  improvise it.** `/preflight` is NOT waived; it can fail at trigger time for
  reasons that do not exist now. **The likely outcome is INCONCLUSIVE, not
  success:** the board rebuilds ~every 25 min, so if the triggering row leaves
  the slate before the post-deploy read, `no_trigger` proves nothing — it is the
  same reading the pre-deploy slate gave. Only a match on the recorded ROW
  IDENTITY counts. Until then the fix is correct-and-unproven, which is not the
  same as working.


## [published-shortlist] THE PUBLISHED SHORTLIST — edges, EV, CLV

**Owner: `recommendation-lane-correctness` (model-audit session).**

- **"ZERO LIVE EDGES EVER PUBLISHED" IS FALSE, AND WHAT IS PUBLISHED IS WRONG.
  `[measured 08-15 02:37Z]`** Served `/api/board/layer2-shortlist`, 105 rows: 51
  carry `market_state: live` — the live tier is not dark — and **5 carry a
  `model_edge_pct`**. All 5 are NFL, all `basis: smartsim2_total_normal`, on
  games at `Q4 4:53` / `Q4 2:52`, with edges +2.70 / +2.47 / −2.47 / −4.53 /
  −7.03 against full-game totals of 34.5–39.5 — i.e. **a pregame full-game
  projection priced against a market that has already seen 55 minutes of
  football.** They RANK (`ev_pct` up to 2.65), which is the specific harm.
- **Cause, one missing import: `shared/nfl_game_projections.py` does not import
  `shared/live_edge_policy.py`** and has no `market_state` guard of any kind.
  AST-resolved importers of the policy are `prop_projections`,
  `soccer_projections`, `wnba_projections` only. MLB's 31 live rows carry the
  policy's exact suppression string; NFL's do not. **The policy's own docstring
  predicted this for WNBA on 08-10 ("WNBA never got it", 128 of 128 live rows
  edged) and the rule was centralised so every sport could depend on it — NFL
  still doesn't.**
- **FIXED, DEPLOYED AND VERIFIED IN PRODUCTION — refresh-worker `dca39fad`,
  live 2026-08-15T20:00:19Z. `[measured 20:15Z]`** On the first post-deploy
  build: **12 live NFL rows, 0 carrying `model_edge_pct`** (baseline 5), 12
  pregame rows with 2 real edges retained, and **10 rows carrying the policy's
  exact reason string** — which is the proof the branch ran, since nothing else
  writes it. **It had to go to refresh-worker, not web:** the shortlist is a
  plain artifact read and the edges are baked in at build time
  (`book_grid_artifact.py:221`); a web deploy would have been inert.
  So "zero live edges have ever been published" — Tier 5's founding premise —
  was false, and what was published is now correctly suppressed.
- **(superseded) fixed in code `1d15686b`, not deployed.**
  Guard applied at the single stamp point in `attach_nfl_game_projections`, so it
  covers h2h/totals/spreads and any future branch; ordered AFTER the projection
  is stamped so `live_aware` still ADMITS a genuinely live model (which matters
  now that user decision 5 is to build one). `pytest -k nfl` **556 passed**; new
  suite mutation-pinned 5-red/5-green exactly as predicted.
  **PRODUCTION RE-MEASURE OWED:** baseline **5** live NFL rows with
  `model_edge_pct` at 02:37Z → expect **0**. Do not call this fixed in
  production until that number is read. **A reading of 0 taken while the board
  carries no live rows at all is NON-EVIDENCE** — window 2 produced exactly that
  and it proves nothing. Re-measure on a live NFL slate.
- **QUOTE-FEED AGE ALARM IS DEPLOYED AND MEASURED — web `0c65a832`, live
  2026-08-15 19:27:27Z. `[measured 19:28Z]`** `GET /api/ops/quote-feed-age`
  went **404 → 200**; running commit confirmed from `/api/ops/version`.
  First read: mlb ok 33.7 min, nfl ok 2.5 min, wnba ok 122.6 min,
  **soccer STALE 340.9 min** — it caught a real stale feed on a sport nobody
  was watching — **but see the correction below; that catch is weaker than it
  reads.** Production still serves the single **10,800 s** threshold.
- **PER-SPORT THRESHOLDS ARE WRITTEN AND NOT DEPLOYED — `9e100444`.**
  Measured per-sport cadence (2026-08-15, production shards, distinct
  `captured_at` gaps, read from the artifacts not the logs):
  `nfl p50 1.0 min (n=128) | mlb 31.0 (n=16) | wnba 122.0 (n=14) | soccer 173.0
  (n=91)` — a **173x spread**, which no single global value can serve.
  New defaults **nfl 2 h / mlb 3 h / wnba 6 h / soccer 7 h**, each set ABOVE its
  feed's measured healthy gaps. **NOT off p50:** an alarm floor lives in the
  tail, and 3x p50 put MLB at 93 min, under its measured 123-min healthy
  pregame gap — refuted by an existing test (`learnings.md`).
- **THAT "THRESHOLD ARTIFACT" CORRECTION IS ITSELF WITHDRAWN.** The 173-min
  soccer p50 was computed across a shard that spans **10 calendar days** —
  soccer's is keyed by FIXTURE date, uniquely (mlb 2, nfl 1, wnba 2, soccer 10).
  **Soccer's real intra-day p50 is 40 min**, so 340.9 min was ~8x normal and the
  alarm's first catch WAS legitimate. Threshold corrected 7 h -> **4 h**,
  deployed `8b010dac` 21:33:13Z and measured (`thresholds_by_sport.soccer`
  14400). I corrected a true finding into a false one with an unchecked
  statistic; the second correction restores the first.
- **KNOWN LIMIT, UNSOLVED:** an age-only alarm cannot distinguish "quiet" from
  "broken". Every sport's max gap (244-558 min) is overnight or between-slate,
  and clearing those tails is what keeps all four thresholds in hours rather
  than minutes. Gating on scheduled games is the real fix.
  Deployed from a branch cut off web's OWN live SHA — `8b6f7773` deployed
  directly would have rolled web back **109 commits**.
- **(superseded) built `8b6f7773`, committed.** `shared/quote_feed_age.py` (O(1)
  tail-read of the quote shard → `newest_captured_at`, age, status
  `ok`/`stale`/`unknown`) + `GET /api/ops/quote-feed-age`.
  **Unknown never maps onto `ok`** — a missing or unparseable shard reports
  `unknown` with a reason, so a broken join cannot read as a healthy feed.
  Built because the 5.8 h starvation above was invisible to every existing
  signal: the boards kept building and serving confidently on stale quotes.
  `tests/test_quote_feed_age.py` 14 passed, mutation-pinned. **Production
  behaviour UNVERIFIED.**
- **MLB live PROP edges are 0 for a different, fully diagnosed reason.
  `[measured 08-15 02:41Z]`** From `book_grid_2026-08-14.json`'s own counters:
  `rows_live_considered 989 / rows_live_projected 86 / rows_live_edged 0 /
  rows_live_edge_withheld 86 / snapshot_live_prob_seen 0 / miss_no_market_alias
  903`. 93 live rows carry a `liveProjection`; **zero** carry
  `liveModelProbOver`, the only field `live_projection_join` will price.
  **The severing line is `syndicate/features/mlb/live_lens.py:1109`:** the Monte
  Carlo payload's props are merged in ONLY when the cards artifact had none, so
  in the normal case the MC rows — the sole source of `liveModelProbOver` — are
  discarded, and what survives is `mlb/cards.py:3441`'s
  `_bounded_live_pitcher_projection`, a deterministic interpolation with no
  probability. **`#414` is deployed and INERT.** True whether or not the MC ran.
  Full read: `.syndicate/tier5_live_modules_2026-08-14.md`.
- **CORRECTED 2026-08-15: "the alias table misses 91% of live rows" was the wrong
  defendant.** The alias table already contains every market that reads as a
  miss, including the two that matched ZERO (`batter_home_runs` 0 of 116,
  `batter_hits_runs_rbis` 0 of 79). The gap is EMITTER-side, and it is four
  causes: (1) `batter_hits_runs_rbis` was in `_MLB_HITTER_PROP_DIST_CONFIG` and
  not in `_LIVE_HITTER_MARKET_KEYS`; (2) `_select_bounded_live_side` is a BET
  SELECTOR (two-way price, non-favourite `-200`, projection clear by 0.08/0.18,
  market edge over 0.05/0.03) whose rejections were dropped, so **the board
  sourced a projection set from a pick list**; (3) a pitcher market already past
  its line was skipped outright; (4) `_live_pitcher_prop_row_actionable` drops
  pulled-starter rows. Fixed in `3a476001` behind `include_projection_only`.
  **NOT PROVEN IN PRODUCTION — see the env split below.** `[from-code + measured 08-15 20:12Z]`
- **THE LIVE-LENS SNAPSHOT IS BUILT ON live-odds-worker, NOT refresh-worker, AND
  ONLY THE ENV SAYS SO.** `MLB_ENABLE_LIVE_LENS_LOOP` = **false** on
  refresh-worker, **true** on live-odds-worker. A `cards.py` emitter fix shipped
  to refresh-worker is INERT; `live_projection_join.py` runs there during the
  board build and is not. **One commit, two files, two owning services.**
  `[measured 08-15 21:5xZ, Render env API, both services]`
- **The live-row proj/prob CONTRADICTION is FIXED AND VERIFIED IN PRODUCTION**
  (refresh-worker `846bb74e`, live 21:45:20Z; artifact 21:46:06Z, 430 live rows).
  `live_projection_join` used to stamp the lens' `modelProbOver` — the PREGAME
  number — beside a live `projected`, so **7 of 13 live pitcher rows had the two
  on opposite sides of the line**. Now `model_prob_over` is the live probability
  or is ABSENT with a reason, pregame preserved as `sim_model_prob_over`.
  Verified by NEW-CODE MARKER (`sim_model_prob_over` on 21 of 21 rows), not by
  the outcome alone; straddles **0**. `[measured 08-15 21:46Z]`
- **The board's live PROJECTION column and its live EDGE are different claims and
  only the edge was ever guarded.** The edge has always priced `live_prob_over`
  only and correctly refuses without it; the displayed projection kept showing a
  pregame number against a live market with no staleness marker. **89% of live
  rows still do** — that half is unfixed and was explicitly not in scope.
  `[measured 08-15]`

- **The audit's "0.5 coin-flip default" was BACKWARDS as a production
  mechanism.** `_fair_probability`'s `0.5` terminal is UNREACHABLE: every
  `filter_candidates` call site is fed `_score_candidates` output, so `score/100`
  always won first (score 4.05 → fair 0.0405 → edge −0.36). Model-free
  candidates were not published as coin flips — they were **silently REJECTED**
  under `reason: "edge_below_threshold"`, a reason claiming an edge had been
  measured when no model had run. **Removing only the `0.5` would have been an
  inert fix.** `[measured + from-code 08-14]`
- **A1's exclusion IS INERT in production** — `FILTER_CANDIDATES sport=all
  in=476 out=377 rejected={"edge_below_threshold": 99}`, with
  `no_model_probability` absent (0 of 476). What changed is that the 99
  rejections are now honest. **Do not credit A1 with an effect it does not have.**
  `[measured 08-15 23:01:39Z]`
- **A3 is SHIPPED AND VERIFIED** (web `ea1d2ed6` + refresh-worker `29ed6de1`).
  Five predictions written BEFORE the deploy all held: `rows_uninformative_ev`
  null → 4003, soccer selected 100 → 0, `total_rows` 256 → 156 (exactly 256−100),
  `book_margin_model` served rows 100 → 0, and **the control mlb 84 / nfl 60 /
  wnba 12 unchanged to the row.** `[measured 08-14 19:58Z]`
- **Why the control held is a mechanism, not a coincidence:** MLB carries 357
  one-sided rows with a modelled fair, so the rule CAN reach it — it held because
  mlb has `rows_with_model_edge = 2256` and the rule keeps any row carrying a
  model view. **The narrowness clause is what protects MLB.** A later mlb 84 → 78
  is 1.4h of SLATE DRIFT, not the rule. `[measured 08-14 21:2xZ]`
- **Ranked #3 + #4 are LIVE (`79148d8e`) and CLOSED — P3 IS MEASURED.** The
  `FILTER_CANDIDATES` line landed at 23:01:39Z (`in=476 out=377
  rejected={"edge_below_threshold": 99}`), which closed both P3 and the
  `7b1f3fdc` instrument deploy. **`recommendation-lane-correctness` is
  CLOSED-VERIFIED and its 7 file claims are released.** Two later handoffs still
  described this as the plan's cheapest open item while quoting the very line
  that closed it — re-read the lane header before re-taking it. `[measured 08-15]`
- **A3a score monotonicity is COMMITTED AND DELIBERATELY NOT DEPLOYED**
  (`28291eb6`; corr(reliability, score) = −0.8312 on 156 negative-value rows vs
  +0.8560 control). **Do not deploy without a pool-side counter** — its effect is
  on SELECTION and is invisible in a shortlist that returns survivors only.
- **CLV: A VALID NUMBER NOW EXISTS. `[measured 08-15 19:4xZ, web `bebe87c9`]`**
  This OVERWRITES the previous "there is still no valid CLV number / avg_clv_pct
  is None" line, which was true until 19:36:45Z today.

      /api/ops/clv/report?date=2026-08-15&sport=mlb
        openings     520
        same_book_n  144      (was 0)
        avg_clv_pct  -0.0711  (was None)

  **The blocker was a VERSION SKEW, not a defect** — web's receiver 403s any
  path failing `is_hot_artifact_relative_path`, and web's `artifact_publisher.py`
  lacked the `clv_openings` pattern the worker had, so 490 openings sat stranded
  on the worker. Fixed by deploy, not by code. Owner: lane `clv-without-settlement`
  (`lane-cleanup`), **whose entry carries the fuller reading — 27.1% beat rate,
  taken PRE-FIRST-PITCH, and the lane's own breadth hypothesis REFUTED. Cite the
  lane, not this summary.**
  - **UNVERIFIED:** the `PUBLISH_OK` log line was never observed; the artifact
    crossing (`export count=1`) is the evidence. **And it is NOT established
    that this is against a sharp close** — a same-book join pairs a book with
    itself, which need not be Pinnacle. Do not merge with the game-line
    sharp-reference finding without checking which book.
  - Still true and still the reason the headline is same-book only: the earlier
    `-5.215` was RETRACTED (`home -5.0` differenced against a `home -1.5` close;
    25 of 25 closes preceded their openings). `close_precedes_open` remains a
    PRODUCTION condition, refused by name alongside `line_mismatch` and
    `line_unverifiable`.
- **The recommendation lane does not price the shortlist.** Every published row
  carries `quote.fair_method` = `consensus` or `book_margin_model`. Fixes to
  `recommendation_engine` should NOT be expected to move the shortlist.
- **Per program Tier 1, stamp fetch cadence / quote age on every CLV record**
  alongside the pricing-version stamp — an "opening" price can be up to two
  hours off the real open.

---

- **`edge_vs_modelled_fair_pct` EXISTS AND IS COMMITTED, NOT DEPLOYED**
  `[user decision 2026-08-17; moved here 2026-08-18 from a WNBA state snapshot]`.
  Measured on the real payload: 228 of 258 both-terms MLB rows priced. It never
  writes `edge_vs_market_pct`.

## [mlb-sim-engine] MLB SIM — INPUTS FULLY FED, STILL NO MARKET EDGE `[measured 2026-08-18, lane convergence-phase7-crps; supersedes seven earlier sim sections]`

- **`sim_input_checklist.py --simulate-rebuild` PASSES, exit 0** — every field the
  engine reads is fed (26 unfed → 0). **A plain run still reports 26**: it audits
  SERIALISED artifacts, i.e. pre-wiring history. Always use `--simulate-rebuild`.
- **Arsenal leaderboards are the source of record**, superseding the per-pitcher
  pitch-splits pipeline: **2 API calls vs 309**, 551 pitchers vs 305, 450 batters
  vs none. `player_id` IS mlbam_id. Multipliers normalise per-player
  (level-neutral), NOT vs the league — league normalisation double-counts
  `k_rate`/`hr_rate`.
- **`statcast_quality_mult` is a UNION bag, PARTIAL BY DESIGN.** Feed RAW metrics
  only (`xwoba`, `ev_mean`, `ev_max`); **never** k/bb/hr/inplay, which
  `simulate.py:163` derives. Seven keys deliberately absent.
- **Fully fed vs market: 4 of 4 better, mean gap 0.01071 → 0.00732 (32% closed)
  — and the market STILL WINS ALL FOUR by 0.0048–0.0105. NO EDGE.**
- **`hr` and `inplay` refit corrections are shippable; `k_rate` and `bb_rate` are
  NOT** — a 1.368x `k_rate` correction moved the residual 0.6pp, because K is
  produced by the pitch-level model, not the per-PA target.
- **THE K DEFICIT IS TWO OPPOSING ERRORS.** `IN_PLAY` 23.3% vs ~17% and
  pitches/PA 2.97 vs 3.9 truncate PAs (K 27% LOW); correcting the mix alone gives
  K/PA 0.284 vs 0.226 (26% HIGH). **Fixing either alone is a wash — the mix-only
  fix is FORBIDDEN on its own.** Needs joint calibration.
- **Pitch model, shipped to tree and MARKET-NEUTRAL:** `first_pitch_swing_damp =
  0.42`, `first_pitch_called_boost = 1.60`, applied at 0-0 only. **Set both to
  1.0 for an exact no-op.** 0-0 called strikes 13.7% → 29.6% against a real
  29.6%; K/PA 0.161 → 0.185. Kept as a PRECONDITION for calibration, not as an
  improvement (2 better / 2 worse, mean −0.00013).
- **The count matrix is MEASURABLE, not fittable** — 895,320 real statcast
  pitches via `scripts/measure_count_progression.py`. Do not grid-search it.
  `count_delta` is a single scalar and structurally cannot express
  take-early / attack-middle / protect-late; three calibration attempts failed on
  exactly that.
- **Still wrong:** `base_in_play` 0.23 vs ~0.17, the 0-2 waste cell, the 3-2
  protect cell. K/PA 18% low, pitches/PA 17% short.
- **In-sim substitution: BUILT, MEASURED, OFF.** Pitch-type effectiveness: BUILT
  and UNFED. Modelling of neither is present in the served path.

## [nhl-sim-engine] NHL SIM (hockeysim) — `nhl_sim_input_checklist.py` PASSES, exit 0 `[measured 2026-08-20, lane nhl-model-owner]`

- **Started this session at 16 alarms, now 0.** Full pipeline trace + gating
  checklist: `docs/ai_context/hockeysim_engine_reference.md`
  (§1–§2zzz, §8/§8b), `docs/ai_context/nhl_model_inventory.md`, `todo.md`
  `#463`/`#470`.
- **Special teams, per-team AND league-calibrated**: PP/PK goal conversion
  (`pk_goal_cal_mult=0.4645`, `pp_goal_cal_mult=1.0` deliberately neutral —
  measured statistically indistinguishable from baseline), PP/PK shot volume
  (`pp_shot_cal_mult=0.9108`/`pk_shot_cal_mult=0.3369`, real per-team indices
  layered on top, verified not to disturb the calibration), block rate
  (`block_rate_ev/pk/pp_def` scaled 1.0631x from vendor defaults, real
  per-team `block_rate_index` layered on top, same verification).
- **Real xG model** (`historical_truth/shot_xg_model.py`, logistic on
  distance/angle/shot-type/strength/rebound/empty-net, 112,888 Fenwick
  shots): holdout AUC=0.7450, Brier=0.0667, league xGF/60 within 1.8% of the
  truth-calibrated goals/60 baseline.
- **`TeamRates.blocks_per_60`/`penalties_per_60` REMOVED, not fixed** —
  confirmed dead (populated, `engine.py` never read either field, proven via
  a byte-identical-output test) and no legitimate mechanism existed to wire
  them into without double-counting: blocks are already fully governed by
  the calibrated per-shot `block_rate_*` mechanism above, and penalty rate
  already drives PP/PK segment generation via `special_teams`'s
  `committed_per_game` (`engine.py:718-719`, confirmed by reading the code).
  Deleted from `HockeyTeamFeatures`/`TeamRates` and every call site, traced
  end to end across 15 files (§2l). `shots_per_60`/`faceoff_win_pct` remain
  reachable and unaffected.
- **Player usage weights built** (`shot_weight`/`goal_weight`/`block_weight`,
  828 players from 47,231 skater-game boxscore records) — these were ALREADY
  reachable pre-fix via `engine.py`'s position/TOI heuristic; real per-player
  data now layers on top, proven at the mechanism level with 3 dedicated
  tests, not just population.
- **`elo_blend_weight` stays at 0.0, deliberately** — a naive win/loss Elo
  does not beat a constant-home-rate baseline (Brier 0.2506 vs 0.2495).
- **Play-by-play ingestion is new substrate** (`NhlWebIngestClient.play_by_play()`,
  1,312 games cached) — was previously unused for NHL entirely (`#454`,
  closed as a data-availability gap this session).
- **`#470`: NHL's first market-comparison backtest** (`scripts/grade_nhl_predictions_vs_market.py`,
  Brier score, `devig()`, mirrors MLB's `convergence-phase7-crps` methodology).
  Confirmed non-circular by reading `adapters.py`/the `/nhl/api/cards` route
  directly — `build_game_prediction` never touches `market_anchoring.py`.
  **Pulls real PRODUCTION data** (`--source production`/`both`, public
  `/nhl/api/cards/dates` + `/nhl/api/cards`, no admin token) as well as the
  thin local mirror. Two real bugs found and fixed while building this, both
  by checking cached responses rather than assuming: (1) several
  `predictions_<date>.csv` files are byte-identical stale duplicates of an
  earlier date — deduped on `(date, home_abbr, away_abbr)`; (2)
  `lookahead_applied` does NOT mean live/circular adjustment despite the
  name — it means "requested date had no games, served the next date that
  does," fixed by keying rows on the RESOLVED date. **Measured, n=14-15
  moneyline/total across 12 dates (2026-03-01..2026-06-11)**: moneyline
  market wins (0.2905 vs 0.2769), total model beats market this run (0.2102
  vs 0.2378) — stated plainly as NOT a powered verdict either way, n is
  still far below what MLB's own much larger sample needed to find its own
  noise floor. Puck-line odds are not exposed by the production route at
  all; `--source both` covers it from local files (n=3).
- **Faceoff track FULLY CLOSED (§2m through §2zzz)**, not just the
  EV/OZ/DZ zone slice: `_faceoff_multipliers` was gated
  `faceoff_ev_only=True` but fed `TeamRates.faceoff_win_pct`, an
  ALL-SITUATIONS blend — closed in stages, each verified not to shift the
  league-wide average shot count (992-pairing round-robin every time, all
  well under 1%): (1) EV/OZ/DZ/NZ per-team zone indices + discrete-event
  decay curves (`zoneCode` confirmed empirically relative to the WINNER,
  not a fixed rink frame; OZ/DZ confirmed genuinely independent, r=0.69
  not ±1.0); (2) a strength-state (PP/PK) mechanism — the first faceoff
  effect outside even strength — where a naive combination of two curves
  inflated league shots +4.478%, found by the SAME round-robin check and
  fixed with an exact per-segment normalization down to +0.203%; (3) a
  per-team PP/PK-role-specific win index refining that mechanism; (4) a
  joint role×zone investigation that correctly DECLINED a full curve
  build — 4 of 6 population cells too data-thin (as few as 197 league-wide
  draws); (5) a player-level lineup-aware layer (real per-player
  `faceoffWinningPctg`-derived rates, TOI-weighted per tonight's confirmed
  roster) for both EV-only and strength-state segments; (6)
  `faceoff_alpha`/`faceoff_diff_clip` calibrated against 1,312 real games
  (95% CI `[-0.005, 0.439]` comfortably contains the vendor's `0.35` —
  decision: left unchanged, backed by measurement not left uncalibrated by
  default) plus a leave-one-out refit confirming that judgment; (7)
  `faceoff_mult_clip_low`/`high` closed with an algebraic proof (max
  possible swing `0.042` is strictly inside the clip's `0.10` headroom for
  ANY input, confirmed by an exhaustive `[0,1]×[0,1]` sweep), after an
  earlier "closes to zero" claim was found to have overstated itself and
  was corrected on the record rather than left standing; (8) the "one
  faceoff assumed per real segment" approximation MEASURED (106,272 real
  segment-windows: mean 0.684 real faceoffs vs the assumed constant 1.0,
  48.64% of segments have ZERO real faceoffs) then ADDRESSED via a
  multi-event-per-segment redesign (`faceoff_multi_event_segment_model`,
  default ON, draws real N∈{0..6} per segment) — built for EV segments
  first (honest non-confirming result: std moved FURTHER from real,
  96.71%→96.03%), then extended to strength-state (PP/PK) segments,
  which REVERSED that finding: combined round-robin std moved to 99.88%
  of real, essentially closing the gap the original measurement found.
  650 hockeysim/nhl tests pass (up from 254 at session start; two
  pre-existing tests in this exact mechanism family broke twice each on
  mean-based reachability comparisons and were durably fixed via
  per-seed-vector comparison, the technique every other test in the
  family already used). `todo.md`'s own addendum for items (7)/(8) is
  NOT YET WRITTEN as of that checkpoint. **THE BLOCKER IS GONE
  `[2026-08-20 ~20:0xZ]`: lane `mlb-overview-hydration-cost` released its
  `todo.md` claim and is now CLOSED, so nothing holds that file for this
  addendum. Whatever Monitor was watching for it to clear can stop.**
  reports) is written and pushed.
- **Genuinely still open (non-faceoff)**: player-level usage-weight
  producer's small-sample floor (< 5 games falls back to heuristic, by
  design); the vendor's original block-rate EV:PK:PP-def ratio
  (0.45:0.55:0.35) was never itself validated, only scaled; xG model's
  rebound/tip-in coefficient sign is an open question; `#470`'s
  market-backtest sample (n=14-15) is nowhere near powered — re-run as the
  season resumes and dates accumulate.


## [model-skill] MODEL SKILL (`#428`) — measured vs not

- **`#428` IS FOUR MODELS, NOT SIX.** `live_projection_join` is a JOIN and
  `game_board_contract` is a passthrough; neither is backtestable. Real targets:
  `soccer_projections`, `wnba_game_projections`, `wnba_projections`,
  `prop_projections`. `[from-code 08-14]`
- **MLB hitter props are MEASURED: BIASED, NOT BLIND.** 2,487 player-games,
  joined on `batter_id` (an exact join). Every counting market carries real
  signal AND loses to a constant baseline by sitting too high; de-biasing flips
  5 of 7 to beating it. `hits` r=0.16 +28.6%, `tb` r=0.15 +17.7%, `rbi` r=0.13
  +30.5%, `runs` r=0.16 +25.9%. `[measured 08-14]`
- **TWO stacked causes; a playing-time fix ALONE will not fix it.** `pa_mean`
  +18.4%, `ab_mean` +17.2%; per-PA rates still +12.2% after normalising.
  Opportunity explains **55%** of the count bias. Fix opportunity first, then
  RE-MEASURE. `[measured 08-14]`
- **"No measured skill" would have been the WRONG conclusion** and would have
  suppressed a model that needs calibrating rather than retiring. **Always
  decompose bias before publishing a skill verdict.**
- **SHIPPED:** refresh-worker `9972977f` / `098877e1` serves 24 MLB prop rows
  carrying `model_skill` with correlation and verdict. `batter_hits_runs_rbis`
  correctly stays `unmeasured` — it must not inherit a neighbour's number.
  Label-only: no projection, mean or edge changed. `[measured 08-15 00:35Z]`
- **`#425` skill declaration is LIVE on both services** — every projection
  carries `model_skill`, `unmeasured` is first-class: `nfl 20 measured`, **mlb
  1631 / wnba 209 / soccer 12 unmeasured**. Counts surface in the `projections`
  coverage block, **not** in `counts`. `[measured 08-14]`
- **`#425` degeneracy detection is LIVE and VERIFIED** — reports any
  `(kind, market, segment)` collapsed to one value across ≥4 distinct GAMES, all
  sports. It found a real defect unprompted on its first live board.
- **WNBA game lines: NOT MEASURABLE YET, nothing broken.** `pred_margin` starts
  2026-08-02; 9 of 361 completed games carry one; n=30 due ~2026-08-26.
- **PRODUCTION HAS FAR MORE HISTORY THAN THE CHECKOUT** — 81 WNBA dates vs "4
  files" locally, and the local files are 7-column stubs with no projection
  column. **Never scope a backtest from the checkout.** `[measured 08-14]`
- **Freeze breadth:** 69 sport × market pairs ship predictions; 2 have a
  backtest. No new pair ships without archive-replay coverage. `[policy]`

---


## [live-surface-tier5] THE LIVE SURFACE — Tier 5 `[measured 08-15 02:3x–03:0xZ]`

Full read with per-module evidence: `.syndicate/tier5_live_modules_2026-08-14.md`.

- **There are 30 `live`-named modules under `syndicate/**`, not 16.** No
  definition yields 16. All 30 were read. **Importer counts must be
  AST-resolved** — a basename grep for `live_lens` collides across eight sports
  and reports `live_lens_loop` as having 0 app importers when it has 2.
- **Nothing here is "an abandoned approach still costing compute."** Breakdown:
  **1 dead** (`features/live_ui_audit.py`, zero importers anywhere incl. tests —
  an argparse CLI parked in `features/`; the only clean deletion), **2 unwired**
  (soccer's projector, below), **11 request-only** (every `live_*_accuracy` /
  `live_prop_audit`, reachable solely from a route — zero background cost), and
  the rest running on purpose.
- **The core MLB path is SEVERED, not scaffolding** — a complete pipeline cut at
  one merge line. See THE PUBLISHED SHORTLIST above.
- **CORRECTED 2026-08-15: "no live GAME-LINE projection exists" is true of what
  is PUBLISHED and FALSE of what is COMPUTED.** *(Restored 2026-08-15 — these
  lines were committed as `fd23c6bc`, then dropped by the 74KB→64KB collapse at
  `7f7d8d88`, which left this section asserting the refuted claim. Do not
  re-collapse without re-reading.)* `estimate_live(LiveSituation(...))` runs in
  production on every live-lens tick, **120 sims per live game**, off the current
  inning/half/outs/bases/score/batter/pitcher, returning `homeWinProb`,
  `awayWinProb`, projected `total` and `homeMargin`
  (`vendor/.../flask_frontend.py:16573`, wired into `_build_game_lens`:16806).
  **Proof it runs:** `LIVE_MC_BAIL` instruments every failure exit;
  live-odds-worker logged exactly **9 bails/tick across 11 consecutive ticks, all
  `status_not_live`**, against a slate of **9 Final / 5 Live** — the live games
  never bail. One exit (`away_score is None`) is uninstrumented, so this is proof
  by exhaustion with one named hole. `[measured 08-15 03:0x–03:2xZ]`
- **It dies in THREE places, and the middle one was re-scoped after measurement:**
  1. `mlb/live_lens.py:1094` — the merge rejected the MC lens for exactly the live
     games (the card's text-derived lens already satisfies
     `_lens_rows_have_projection_signal`); same shape as the prop sever at :1109,
     fifteen lines earlier. **FIXED as `0e0b0aa1`. BOTH DROPS DEPLOYED AND
     WORKING — `live_mc` 0 → 6, CONFIRMED END TO END.** `[measured 08-15 21:49Z]`
     The worker's own per-tick tally reads
     `liveMcSources = {live_mc: 6, segment_projection: 52, unknown: 8}` and web
     SERVES `rows=66 live_mc=6`. **Six and six — the producer's count and the
     served count match**, which is what makes it end-to-end.
     **RETRACTED: my earlier "both drops live and `live_mc` still 0, a clean
     negative" was PREMATURE.** Those passes ran 3 and 8 minutes after the worker
     restarted at 20:56:07Z, inside the live-lens loop's warm-up. **Two reads
     inside one warm-up window are ONE read** — the slate moving between them
     made them independent of each other, not independent of the transient.
  2. **`/mlb/api/live-lens` serves a report WEB WRITES ITSELF.** It reads the
     worker's keyvalue snapshot and, when it judges it stale, DISCARDS it and
     rebuilds locally with the MC hard-refused by
     `refuse_if_compute_in_request_path`. Max age **60 s** vs a **60 s** worker
     tick. **There are THREE live-lens artifacts, not two**, and the published
     disk copy is not the one the surface reads. **FIXED as `4bd7dbb3`, DEPLOYED
     ON WEB** (`9b88d05b` live 19:54:18Z; superseded by `f475c775`, which
     content-checks as carrying both drops and descends from it, so not a
     revert). Carry-forward is bounded 300 s, refused on unreadable age, refused
     on a settled game, stamped with a non-resettable `liveStateAsOf`.
- **INSTRUMENT, corrected twice — read this before verifying anything here.**
  `[measured 08-15 20:0xZ]`
  - **`mlb_source/data/live_lens/…` CANNOT show the lens, ever.** It is the SLIM
    shape from `scripts/refresh_mlb_oddsapi.py`; a game row's keys are exactly
    `{gamePk, startTime, status}` and **`gameLens` is not a key at all**. Earlier
    guidance in this file naming it as the instrument was wrong.
  - **`/mlb/api/live-lens` WAS blind and is now the CORRECT instrument** — it was
    blind because web's rebuild destroyed the lens, and `4bd7dbb3` removed
    exactly that. The rule inverted when the fix landed.
  - **`modelHomeWinProb` is NOT a valid signal: 60 of 60 rows carry one at
    baseline**, stamped on the `first1/3/5` lanes by `_live_margin_win_prob`.
    **`source == "live_mc"` is the only discriminator.**
  - **BASELINE for the pending worker deploy** (`/mlb/api/live-lens`, 15 games /
    4 live): `gameLens rows 60`, **`live_mc` 0**, `liveStateCarriedForward` 0.
  3. ~~`live_projection_join` is entirely prop-shaped; there is no game-line
     join at all.~~ **BUILT AND WIRED as `758a89fa` (Drop 3), DEPLOYED NOWHERE.**
     `shared/live_gameline_join.py` + one call site in `build_book_grid_artifact`
     emitting a `live_gamelines` coverage block, kept separate from
     `live_projections` so one family's zero cannot look like the other's.
     Joined on FULL TEAM NAMES, which match exactly (`matchup.home.name` ==
     `home_team`, verified in production) — **no alias table, deliberately**,
     since the prop join's 91% miss is a market-NAME aliasing failure.
     **SHIPPED: Drop 3 is live on refresh-worker** (`f8ca54e1`, and still
     present on the current live `d72d670c` — verified by content, not ancestry).
     **Expect `rows_live_gameline_edged: 0` at first and do not call it a
     defect:** at 120 sims the 2-sigma bar is ~9.1 pp at p=0.5, so a balanced
     slate refuses by design (recorded decision, spec §8.1).
- **THE LIVE GAME-LINE POPULATION IS 8 ROWS PER BUILD, and the counters are now
  reachable from an API.** `[measured 08-16 03:00Z, 2 games live / 13 Final;
  artifact `generated_at 03:00:00.538Z` streamed off web]`

      live_gamelines       considered 8  projected 2  priceable 0  edged 0
                           withheld 8 = {segment_is_not_full_game: 6,
                                         prob_interval_swamps_edge: 2}
      live_gameline_ledger candidates 0  written 0  enabled true

  - **`index_size` COUNTS SNAPSHOT GAMES CARRYING A `live_mc` LENS, NOT LIVE
    GAMES — the "3 → 8 → 10 is unexplained" handoff line is RESOLVED and nothing
    is broken.** Census at 03:0xZ: 10 of 15 = **8 Final + 2 Live**. A Final keeps
    its last lens, so the number is monotone across a slate. The join filters on
    `game.state == live` on the GRID side, so the Final entries are never used.
  - **The ledger recorded nothing because its population was empty by
    construction, not because of a defect.** v1 recorded `priceable` rows only.
    **FIXED as v2 and SHIPPED** — `5c419007`, live on refresh-worker
    **04:24:33Z**; `LEDGER_VERSION = 2` content-verified on the currently live
    `d72d670c`, which a later deploy carried forward. Records every PROJECTED
    row, keeps `priceable`/`withheld_reason`/`sigma` as fields.
    `LEDGER_VERSION` 1 → 2 because the POPULATION changed: **filter any reader on
    `v` before aggregating**, or the rate spans two denominators.
  - **`/api/board/book-grid` dropped `live_gamelines` and `live_gameline_ledger`**
    though the artifact carries both — second instance of that bug in that
    function. **FIXED AND SHIPPED — web `ebd5f677`, live 03:38:07Z.** Both keys
    read `null` before and serve objects after, measured across two different
    artifacts (03:37:13Z and 03:39:36Z). The ~10 MB
    `/api/ops/artifacts/stream` workaround is no longer needed.
  - **BOTH HALVES ARE DEPLOYED, AND v2 HAS NEVER BEEN EXERCISED.** web
    `ebd5f677` 03:38:07Z, refresh-worker `5c419007` 04:24:33Z, each parented on
    its own service's LIVE SHA — **`main` is an ancestor of NEITHER service's
    live tree** (13 commits live-only on refresh-worker, 33 on web at the time).
    The slate ended between the last pre-deploy build and the first post-deploy
    one, so v2 went live with **zero live rows to act on**; as of 15:17Z on 08-16
    the board reads `index_size 0, considered 0` because nothing is live yet.
    **The test is the scheduled `live-gameline-ledger-check`, 08-16 20:30
    Central.** The discriminator for v2 is `written` rising on rows that are
    **not** priceable — `skipped_unchanged > 0` is NOT it, having already been
    observed under v1.
  - **CORRECTION — "the recorder has never recorded a row" is FALSE.** The
    04:22:51Z pre-deploy build read `priceable 1, candidates 1,
    skipped_unchanged 1`, and `skipped_unchanged` cannot be non-zero unless a
    matching record is already on disk (`_moved(None, rec)` is True, so an empty
    file always writes). **v1 wrote at least one row on 08-15**, between 02:4xZ
    and 04:22Z. The 03:00Z reading above is real; generalising it to a whole
    night was the error.
- **WHERE THE HUNT STANDS AFTER BOTH DROPS `[measured 08-15 21:1xZ]`. Two
  hypotheses are DEAD — do not re-run them:**
  - **"Drop 1 is bypassed; `_persist_live_lens_report` never runs on a tick" —
    FALSIFIED.** `_live_projection_enhancement_payload` has **exactly one
    caller**, `mlb/live_lens.py:1384`, inside that function, and it is the only
    in-process import of the vendored `_live_lens_payload` in the MLB path. The
    `LIVE_MC_BAIL` lines prove it executes.
  - **"the MC bails on live games" — FALSIFIED.** 100 log samples,
    time-contiguous 21:05:27–21:11:04 across multiple whole ticks, **100%
    `status_not_live`** (90 Preview, 10 Final). A live game cannot emit that
    reason and none of the other six appears. **NB: my first evidence for this
    was a saturated 40-of-40 sample and was worthless — re-query
    time-contiguous, and check `hits == limit`.**
  - **REMAINING HYPOTHESIS, NOT A FINDING:** the MC takes the ONE uninstrumented
    exit, `if away_score is None or home_score is None: return None`
    (`flask_frontend.py:16611`), which emits nothing. It is the only silent path
    left. **Nothing has observed it.**
- **THE MEASUREMENT THAT SETTLES IT IS COMPUTED EVERY TICK AND WAS DISCARDED.**
  `_tally_mlb_live_mc_sources` (`live_lens_loop.py:473`) counts
  `live_mc / live_projection / segment_projection` per lane into
  `meta["liveMcSources"]`. `live_lens_loop_status_payload()` had **zero
  callers**. A route now exists — `GET /api/ops/live-lens/status` (`09b345ee`),
  **committed, NOT deployed, and its broader ops regression was interrupted and
  never ran.** Read `enabled`/`threadAlive` from it as the CALLING service's,
  not the worker's.
- **Allowlisting `reports/live_lens_loop/latest_live_lens_tick.json` is INERT —
  do not try it.** `_KEYVALUE_EXCLUDED_PATH_MARKERS` is only
  `("migration_runs/",)`, so the path is keyvalue-backed on every service and
  `write_json_file` returns before any disk write, while
  `/api/ops/artifacts/stream` gates on `target.is_file()`. It would turn a 403
  into a 404.
- **live-odds-worker `earlyExit`s roughly every 6.5 h** — `server_failed`,
  `evicted: False`, at 01:37 / 08:05 / 14:34 / 20:03 on 08-15 (**events API**,
  not logs). A refresh run launches on boot, so **this service's deploy gate is
  closed almost continuously**: 76 min of polling yielded one sub-minute CLEAR.
  **`predictions.full` IS pregame at source** — the vendored payload sets
  `"predictions": card.get("predictions")` verbatim, so no merge line downstream
  can make it live. Served surface confirmed the effect before the fix: 56
  `gameLens` rows, lanes `first1/first3/first5` only, `source: None`, **0 with
  `modelHomeWinProb`**.
- **The compute cost of a live game-line projection is ALREADY BEING PAID** — the
  MC runs on both workers today regardless. Publishing it is not new periodic
  work, which is what makes this cheap against the `#435` memory constraint.
  **The open question is precision, not existence:** 120 sims puts the standard
  error on a win probability near **4.6 pp** at p=0.5, which is display-grade and
  not edge-grade. `MLB_LIVE_GAME_MC_SIMS` is env-tunable (min 20).
  Full spec: `.syndicate/spec_live_game_line_projection.md`.
- **`live/nfl_live_lens.json` and `live/soccer_live_lens.json` are built every
  tick and NEVER published to web.** `live_lens_loop.py:150` builds five sports
  (`mlb, nba, wnba, soccer, nfl`); `artifact_publisher.py:433-435` allowlists
  three (`mlb, nba, wnba`). **The two omitted sports are in season; the
  allowlisted NBA is not.** That same publisher block already carries a written
  post-mortem of this exact bug for the three that ARE listed
  (`SKIP_NOT_ALLOWLISTED`, "just a plain missing entry") and records the cost:
  refresh-worker's fallback recompute had `prop_row_counts=[0]*9` across nine
  live games. **Two lines; needs no product decision.**
- **A working live game-line projector already exists — in soccer, unwired.**
  `soccer/features/live_lens.py` exports `project_live_match`,
  `goal_in_window_probability`, `project_live_player_props`, built on
  `match_simulator.simulate_match`'s `initial_state` hook. Reachable only from
  `scripts/backtest_soccer_live_lens.py` and `scripts/poll_soccer_live_state.py`,
  **neither scheduled** (no cron, no `render.yaml`, no worker import; the
  soccersim phase-1 report records the poller as never run). Costs zero compute.
  **"Build the live game-line projection" is therefore not green-field
  everywhere — name this asset in the decision rather than discovering it after.**

---


## [ask-the-syndicate] ASK THE SYNDICATE

**The LLM is off by decision. The deterministic snapshot path is the product.**

- **CURRENT BASELINE: 37/52** (advice 4/5, entity 9/10, explain 4/6, history 2/5,
  lookup 8/8, ranking 7/10, refusal 3/8), measured 2026-08-16 18:0xZ and again
  post-deploy with **zero pass/fail flips**, in
  `reports/ask_regression/{control_pre,post}_answer_substance_2026_08_16.json`.
  `answer_source: snapshot` is the EXPECTED source, not a finding.
  **This REPLACES the 38/52 recorded on 2026-08-15 — that figure was a different
  day's slate and had expired.** Re-measure a same-slate control before judging
  any change; a handed-down baseline is not a baseline.
  **The harness cannot see most of what the panel does.** `_score` checks
  refusal/routing/hallucination/certainty/50-50 and is blind to selection shape,
  units, price, sim terms, quote age and the rendered panel. Four deploys on
  2026-08-16 changed all of those and could not move it. **A flat score is
  therefore not evidence of no effect, and a large jump would be suspicious.**
- **Ask baseline RE-CONFIRMED after all six deploys, 22:2xZ on live `d8985df8`:
  37/52, ZERO pass/fail flips vs the same-slate control, every class identical.**
  `reports/ask_regression/post_all_deploys_2026_08_16.json`. One warning moved —
  `edge_without_market_probability` 0 → 25 — and it is BOARD DATA, not the Ask
  code: the board path's `edge`/`market_probability` are unchanged across all six
  deploys (`git diff ebd5f677 d8985df8`), while **4 of 10 edge-bearing rows now
  carry a `model_edge_pct` not derivable from
  `projection.{model_prob_over, market_fair_prob_over}` by either the direct
  difference or the complement** — including two rows where `row_side ==
  proj_side` so no complement applies and the direct figure is off by 64 and 19
  points. All `full/*_dist` bases. Owned by `layer2-board-quality`, notified.
- **ASK ANSWER SUBSTANCE — LIVE web `9bae928c` (2026-08-16 22:52:31Z).** The
  deterministic panel now: names the bet a human can place (market, line, side,
  price, book — not "Ryan Johnson"); generates its own reason sentences from
  `projection.projected` and `model_skill` (the MLB game lens is the model);
  publishes only rows where EVERY edge term it carries is positive; and reports
  a quote age that advances. `_bet_label` mirrors `layer2_board._pick_label` and
  is pinned by test — the two must not drift.
- **`quote_seen_age_seconds` IS STAMPED AT ARTIFACT BUILD TIME AND DOES NOT
  TICK.** Three reads of the live shortlist 45s apart returned byte-identical
  ages (`mlb=[12.9, 39.8] wnba=[47.1]`) while `written_at` sat at 20:15:41Z.
  **Every consumer of that field understates quote age by the artifact's own
  age** — real age is `stamped + (now - written_at)`. Ask corrects for it; other
  surfaces have not been checked. Its sibling `book_age_seconds` answers a
  DIFFERENT question ("has the price moved") and the board gates on the seen
  clock deliberately — see `layer2_board._row_quote_age_seconds`.
- **WITHDRAWN 2026-08-16 22:5xZ — "the board publishes sides that contradict
  its own projection" was MY error, not a board defect.** Chasing it to a root
  cause showed only **2 of 10** failing rows are explained by live-join
  staleness; the rest are a category error in the Ask reason generator.
  `projection.projected` is a **MEAN**, and what picks a side is
  **`P(X > line)`** — on a low-line count prop those diverge legitimately (a
  mean of 0.214 runs implies `P(>=1) ~ 19%`, which beats a market implying
  15%). **Do not re-open this against the board.** Ask now claims a direction
  only on GAME totals/margins, where the mean is the right statistic; on props
  it states the relationship as a fact. Fixed in web `9bae928c`.
- **STANDS, AND ITS ROOT CAUSE IS CONFIRMED — `model_edge_pct` is not
  comparable with `projection.{model_prob_over, market_fair_prob_over}` after a
  live join.** `live_gameline_join.py:643` overwrites `edge_vs_market_pct` with
  the LIVE edge while deliberately leaving `model_prob_over` at its PREGAME
  value (the live probability goes to a new `live_model_prob_over` key). The
  edge therefore refers to a different probability than the one beside it, with
  nothing in the field name to signal it. **7/7 separation on `live_aware`**;
  arithmetic exact — stated `-39.93` = `(0.1917 - 0.591) x 100`, where the
  pregame pairing gives `+27.46`. Every number is correct; only the PAIRING is
  wrong, which is why it is `full/*` only (segment bases are not live-joined
  and agree 3/3). Owned by `layer2-board-quality`, notified with the fix
  options. Consumers pairing those two fields must prefer `live_model_prob_over`
  when `live_aware` is true.
- **K1 SHIPPED AND VERIFIED** (`bef782cb`, live 20:01:18Z): 20/52 → 23/52,
  `refusal` 3/8 → 6/8, every other class byte-identical, declined-question
  latency 10.9s → 0.19s. **A refusal gate must be tested on what it must NOT
  refuse** — two regressions were caught only by testing the answer direction.
- **CURRENT PRODUCTION SCORE IS 38/52 `[measured 08-15 17:5xZ, live 1e44e1da]`.**
  **K6 IS NOT PART OF THAT NUMBER AND IS NOT LIVE.** Its fix `3ba1c2cf`
  ("source the as-of from `state_meta` too, because production has no
  `freshness` key") was cancelled mid-build at 19:20Z by a peer's deploy and is
  **still absent from live `7abd8e12` at 20:22Z, confirmed by patch-id**. It is
  built, tested and pushed as `deploy/ask-k6-2026-08-15` (`3d68dfe4`), never
  fired. So the ask lane's own `K6 RETRACTED AS INERT ON PROD` still stands:
  **no as-of predicate has been measured on production.**
  Pre-deploy control **25/52** (`reports/ask_regression/prebaseline_c774fe1a_2026_08_15.json`).
  entity **2/10 → 9/10**, lookup **4/8 → 8/8**, ranking **5/10 → 7/10**;
  advice 4/5, explain 4/6, history 2/5, refusal 4/8 all flat. **Zero classes
  regressed.**
  - **ATTRIBUTION: the gain is the `ask-sport-coverage` deploy**
    (`b6f1a2e6`/`0bf866c3`), NOT the web train that followed it. The train
    reproduced 38/52 and added the WNBA clamp and MLB live lens on top. Do not
    credit the train with 13 points.
  - **THE "23/52" BASELINE IS DEAD.** `post_m1_fixed_2026_08_14.json` is a
    ranking-only run with `total: 10`; that number existed only in prose and was
    propagated into three briefs. Use 25/52 as the pre-deploy control, or a run
    you took yourself.
  - Slate caveat, so a flat class is not misread as a failed fix: production was
    **nfl 60 / mlb 39 / wnba 6, zero soccer / ncaab / nhl**, so the soccer
    classes could not move on this measurement whatever the code does.
- **THE TWO-POOL DIVERGENCE IS CLOSED** — web `c774fe1a` (live 2026-08-15
  03:29:56Z), lane `ask-headline-from-board` CLOSED-VERIFIED. `M1`
  (`b16eb1f7`) only SUPPLEMENTED (`visuals.tables`) and left the headline on
  the snapshot, so chat and the board still read 23.81 vs 14.09.
  `_market_summary_schema` now sources `top_opportunities` from
  `read_layer2_shortlist` — the same artifact `/api/board/layer2-shortlist`
  serves. **Measured same-instant: chat 6.35 vs board 6.35, |delta| 0.000**,
  fingerprinted 5/5 rows carrying `source="layer2_shortlist"`.
  Two guards were bought with a rollback and must not be removed:
  the board REPLACES a non-empty `recommendations` pool and never CREATES one
  (an empty pool is the engine DECLINING — sourcing unconditionally answered an
  Ohtani stats question with NFL totals, refusal 4/8 → 3/8), and board rows
  carry explicit `edge_pct` because `edge` is a FRACTION on snapshot rows and a
  PERCENT on board rows (`Best edge 635.0%` served for 14 min).
- **SPORT COVERAGE FIXED AND MEASURED** (`0bf866c3`, live 16:49:28Z) — the
  08-14 finding above (soccer/ncaab had no branch, NFL required the FULL team
  name, wnba was a keyword inside nba) is CLOSED on the routing axis:
  **25/52 → 38/52, zero regressions, `no_sport_resolved_expected_*` 15 → 0.**
  entity 2/10 → 9/10, lookup 4/8 → 8/8, ranking 5/10 → 7/10. Board composition
  identical at both instants (150 rows, wnba 18 / nfl 42 / mlb 90), which is
  what makes the diff attributable. `[measured 08-15 16:52Z]`
- **BUT soccer / ncaab / nhl coverage is UNPROVEN ON DATA.** The board carried
  **zero rows** for all three at both measurement instants, so those cases pass
  on ROUTING only. Whether the new fetcher branches return anything useful on a
  real slate is NOT established — re-measure when soccer is on the board.
- **NFL nickname matching must NOT be copied to NCAAF.**
  `_ncaaf_teams_in_question` excludes mascots deliberately (~680 schools share
  "Wildcats"/"Tigers"). NFL is safe only because its 32 nicknames are unique
  (verified). `[from-code + measured 08-15]`
- **K6 CAUSE CONFIRMED AND FIXED IN `origin/main`, BUT NOT DEPLOYED.**
  `routed_sport` shipped and works; the as-of did not. `as_of` is populated
  **28/52** and `warn:no_as_of_stated` is **24** on the live tree — unmeasured
  and unmoved until `0050d1c4` reaches production. **Do not mark K6 closed.**
  **Cause (measured, not suspected):** production web runs
  `SYNDICATE_INTELLIGENCE_CANONICAL_BOARD_STATE = true` AND
  `SYNDICATE_INTELLIGENCE_COMBINED_BOARD_DEFAULT = true`, **while the comment at
  that call site still says the flag is "default off, so this is a no-op
  today".** That path (`read_combined_intelligence_response`) returns
  `state_meta` and **no `freshness` key at all** (`state_meta.computed_at` was a
  valid `2026-08-15T18:36:33Z`). `read_latest_intelligence_state` has FOUR return
  paths with DIFFERENT payload shapes, so anything reading `freshness` off the
  snapshot works on a dev box and is inert in production. The fix scans
  `("state_meta", "freshness", "state_freshness")`, matching
  `pipeline/intelligence_state.py`'s own order. `[measured 08-15 18:3xZ]`
- **K3's `build_evidence_pack` sport-filter item is DEAD CODE** — reachable only
  from the LLM engine, which never executes by standing decision. `[from-code]`
- **Chat reads the shortlist ARTIFACT directly**, so chat staleness IS artifact
  age. `[from-code]`
- **The system prompt's rules 5–8 (surface uncertainty, distinguish fact from
  projection, never fabricate, flag staleness) are now PERMANENTLY UNENFORCED.**
  They were the only place those rules existed; the deterministic path needs its
  own. That is a consequence of the decision, not a pre-existing defect.

---


## [ui-board-cards] UI / BOARD CARDS

- **Lane E is CLOSED-VERIFIED in production** (web `aadcde77`, live 21:42:56Z):
  horizontal overflow 28px desktop / 20–40px mobile → **0 at both widths** on
  nfl, ncaaf, soccer, ncaab; NCAAF default tab 0 panels/187px → 1 panel/556px;
  orphan tabs and unreachable panels → 0; mobile tab targets under 44px 64/48/4
  → 0; numeric classes `normal` → `tabular-nums`. `[measured 08-14 21:4xZ]`
- **Lane F is CLOSED-VERIFIED and live** (web `932a1f71`, then `a86eb4ed`):
  seven fabrication sites in `game_board_contract.py` are gone — an absent
  probability renders as an explicit empty state, a genuine 0.0 survives instead
  of becoming 50/50, and a projected scoreline is never recast as a win split.
  Soccer three-way markets carry a draw segment. One null placeholder (`—`)
  platform-wide: NCAAF hyphen cells 48 → 0, em dashes 0 → 144. `[measured 08-15 01:41Z]`
- **A 50/50 on the board now MEANS 50/50.** The one still served (NFL, DEN@KC)
  sits on a 0.4-point projected margin — the producer's own `home_win_rate`.
- **NCAAF kickoffs file on their CENTRAL day** — 28 of 157 real 2026 kickoffs
  were previously filed under their UTC day. **The platform's display timezone is
  Central everywhere**; `central_today_iso()` is the slate clock. An MLB slate
  spans two UTC dates; it does not span two Central ones.
- **`scripts/ui_layout_probe.py` is the durable instrument.** It reproduced the
  audit's before-numbers against the unchanged service, which is what makes its
  after-numbers a reading rather than a belief. **Synthetic `el.click()` is not
  used anywhere in it — the audit had to retract a finding produced that way.**
- **NBA / NHL / NCAAB serve 0 cards** in production and locally. Their rows in
  the divergence matrix are code-only. **Re-measure in October.**
- **Carried, not fixed:** the desktop strip still breaks long names mid-word in a
  ~52px box — a design decision that CONTRADICTS Lane G1's "raise soccer's 13px
  names to 16px", since 13px + ellipsis is the documented fix for that problem.
- **The prop-producer 0.5 fix is COMMITTED AND NOT ON ANY WORKER** — **SUPERSEDED
  08-15 22:2xZ: it is LIVE on both workers, by content. See the deploy section
  above; this paragraph is kept only for its local sizing numbers.**
  (`bd40056c` / origin `536dfcd0`). Local sizing: 6 of 4,240 probability rows
  were price-missing and every one carried a fabricated 0.5; **67 further exact-
  0.5 rows have real ±100 prices and are legitimate** — a blanket "no 0.5
  anywhere" rule would have destroyed real data. Production rate UNMEASURED.
  **Until a worker deploy carries it, production still fabricates.**

---


## [soccer] SOCCER

**Owner: `soccer-model-coverage` (new) for the model; UI Lane G for the card.**

- **THE SQUAD FED TO THE SIM WAS WRONG TWICE OVER, BOTH FIXED AND MEASURED
  `[2026-08-20/21, lane soccer-board-mlb-parity]`.**
  (1) `_load_player_rows` unioned every season's `players_*.csv` and deduped
  keeping the newest row, so any player who ever appeared in the league
  survived forever under their last-known club — Arsenal carried Partey,
  Tierney, Jorginho, Sterling and Kiwior. **Arsenal 28 → 23**, verified on an
  artifact rebuilt `2026-08-20T23:43:04`.
  (2) `build_soccer_player_features` bound player rows to fixture teams by
  FUZZY match, so a club not playing today was absorbed by the nearest name —
  **26 Real Oviedo players inside a 21-man Real Sociedad**. **50 → 24**,
  verified on an artifact rebuilt `2026-08-21T01:01:32`, zero Oviedo players
  remaining. Live on workers `68acf3ca` / `a05412f9`.
- **`canonical_team_name` DESTROYED accents rather than stripping them, and
  that is why the fuzzy threshold was 0.72.** The ASCII scrub turned every
  non-ASCII char into a SPACE (`Alavés` → `alav s`), so an accented club name
  never canonicalized to its unaccented twin in the five leagues that have
  them. Fixed with NFKD folding; **0 distinct clubs merge** as a result.
  `match_team_name` no longer binds a player to a fixture at all.
- **SIX club pairs could absorb each other**, only when one plays and the
  other does not: **Manchester City ↔ Manchester United (0.812)**, Paris FC ↔
  PSG, Cercle ↔ Club Brugge, Real Oviedo ↔ Real Sociedad (0.750), LA Galaxy ↔
  LAFC (0.750), Atlanta ↔ Minnesota United (0.722). Only la_liga has been
  REBUILT AND READ; the other five are fixed by construction, unobserved.
- **A bad league slug used to serve EPL.** `/soccer/laliga/cards` (canonical is
  `la_liga`) returned 200 with Arsenal fixtures. `normalize_league` maps
  anything unknown onto `DEFAULT_LEAGUE`; a `url_value_preprocessor` now 404s
  it once for every route. Verified on the served site: 7/7 bad slugs 404,
  10/10 leagues 200. web `93b6d5a4`.
- **`players_*.csv` and `rosters_*.csv` are NOT in `HOT_ARTIFACT_PATTERNS`**
  (403 on `/api/ops/artifacts/export`). The builder's own inputs cannot be
  read from web, so any aggregate quoted about them is a LOCAL MIRROR number.
  `recommendations_*.json` and `picks_*.csv` ARE allowlisted — an earlier
  claim to the contrary was a malformed request, not a gap.
- **`week_dates_within_horizon` bounds artifact builds to today+1.** A league
  whose next fixture is further out builds NOTHING, and no re-trigger changes
  that — it is not a failure. Override is
  `SYNDICATE_SOCCER_SIM_HORIZON_DAYS`, and it needs a worker deploy to take.

- **Soccer serves ZERO shortlist rows and that is the INTENDED interim state,
  not an outage.** Its whole presence was one-book longshot props whose `ev_pct`
  was arithmetically `-assumed_hold_pct`. **Read `rows_uninformative_ev` before
  diagnosing soccer as broken** — soccer is ABSENT from `per_sport` rather than
  present at 0.
- **The A3 filter SELF-HEALS.** It keys on `fair_method`, so if soccer ever gets
  two-sided quotes the fair becomes `consensus` and the rows return with a real
  EV — no code change. `[from-code 08-14]`
- **Two endpoints disagree about projection coverage by 250×, same sport, same
  date, 45 seconds apart `[measured 08-14 19:1xZ]`:**
  `/api/board/layer1?sport=soccer` → 8,456 rows, 2,504 projected = **29.6%**;
  `/api/board/layer2-shortlist` → 8,512 rows, 12 projected = **0.1%**, with
  `rows_with_model_edge: 0`, `matches_in_source: 4`, `unmatched_match_rows:
  8,393`. **These are two different joins and at most one describes the board a
  user sees.** Settle this before raising coverage.
- ~~**SOCCER GAME ODDS HAVE NOT BEEN CAPTURED FOR ANY LEAGUE SINCE 08-10/08-11.**~~
  ~~**SUPERSEDED 2026-08-17 — capture is WORKING.**~~ ~~**RE-OPENED 2026-08-19,
  steps=0 dominant cause, NOT YET FULLY EXPLAINED.**~~ **FIXED AND VERIFIED
  2026-08-20, lane `soccer-odds-capture-cadence-gap`. Root cause, confirmed
  against production OddsAPI directly (not inferred): `_game_markets()`
  (`scripts/fetch_soccer_oddsapi_odds_local.py`) merged h1/h2 segment keys
  into the market list for the BULK `/sports/{sport}/odds` endpoint, which
  422s on an unsupported key across the WHOLE request — every capture had
  produced zero rows since `#343` shipped (2026-08-10 21:17:39 -0500, date
  matches the last good capture exactly). This IS what `steps=0` was: a
  silent per-request failure, not a scheduler or reporting-artifact bug.
  Fixed by narrowing the bulk-endpoint market list back to
  `DEFAULT_GAME_MARKETS` (h2h/totals/spreads); `_segment_market_map()`
  unchanged, still correct for tagging. Deployed to BOTH producers
  (`live-odds-worker` `575decf3`, `refresh-worker` `b2f4b197`). **VERIFIED
  from the writing service's own disk-content log** (not a status endpoint):
  real `book_quotes` growth observed post-deploy, 6 of 8 originally-stale
  matches re-confirmed with `captured_at` minutes old. 2 matches not
  individually re-checked.**
- **THERE IS EXACTLY ONE PRODUCER and it is not refresh-worker.** `phase=pregame`
  builds 50 steps including 10 odds steps; `phase=live` builds 20 steps and **0
  odds steps** — and refresh-worker's soccer autorun runs `phase="live"`, so it
  never fetches soccer odds at all, by design since `#148`. Everything depends on
  `_launch_autorun_soccer_pregame_refresh` on live-odds-worker, 4h cadence.
  **Single point of failure.** `[measured 08-14 18:5xZ, RE-CONFIRMED 08-19 by
  reading _build_soccer_steps directly — the "0 odds steps" claim is code-exact,
  not stale]`
- **WHY the step fails is STILL UNKNOWN.** No error has been observed anywhere.
  **Two hypotheses are DEAD — do not re-run them:** step truncation at #27 of 50
  (falsified by a ~6-step scoped run that captured nothing), and
  three-specific-leagues (all ten are affected). The `#433` step reorder is
  retained on its own merits but **must not be credited with fixing capture**.
- **The run's own logs are UNREADABLE FROM WEB** — `launch_refresh_run` spawns
  the child `stdout=DEVNULL, stderr=DEVNULL` onto the WORKER's disk, and Render's
  collector captures only a service's own stdout. That is the disk split, not an
  absence of logs, and it is how four days of failure produced no visible error.
- **The sim reports its own input is missing:** `SOCCER_PLAYER_ROWS_MISSING` on
  eredivisie, primeira_liga, championship. Observed once while looking at
  something else — **a lead, not a finding.** `[observed 08-14 19:25Z]`
- **Some markets can never carry an edge however good the model gets.**
  `player_shots` / `player_shots_on_target` map to a MEAN and `soccer_projections`
  refuses by design to derive a probability from a mean; the rows are one-sided
  so `_no_vig_over_probability` returns None. `player_to_receive_red_card` and
  `player_assists` are not in the market map at all.
- **MLS cannot be backtested from its current source at all.**
  `fetch_asa_mls_team_history` returns undated **season aggregates**, so a season
  average already contains the whole season and no `as_of` filter can repair it.
  The backtest returns `{}` for MLS with `AS_OF_DROPPED_UNDATED`. `[measured 08-14]`
- **`data/soccer_source/*/validation/*_backtest_*.csv` is NOT CITABLE** (leakage).
  Report soccer backtest accuracy as **unmeasured**. Production is unaffected —
  `build_soccer_artifacts` predicts forward.
- Soccer sims are ENABLED and running; one sim job = one league-date (`#282`).

---

## [wnba] WNBA

- **`#499` WNBA live TOTALS pricing is DEPLOYED but NOT PROVEN `[2026-08-21T17:4xZ]`.**
  Live on BOTH workers at `8d5d6edf` (refresh-worker 16:43:05Z, live-odds-worker
  16:48:04Z, Render deploys API). Three parts: `_WNBA_LIVE_TOTAL_SCALE` refit
  `8.0+0.50*min_left` -> `3.2` (held-out Brier 0.1744 -> 0.1477, n=249 games /
  23,712 samples); `ANALYTIC_LIVE_STD_ERR_BY_MARKET {("wnba","totals"): 0.150}`;
  and the fix for the second shipping INERT. **sigma=0.150 is the worst gap BY
  PREDICTED BUCKET** — the by-minutes-left aggregate reads 0.023 and is an
  averaging artifact (+0.109 at p=0.35 and -0.150 at p=0.65 cancel). At 2 sigma
  the bar is ~30pp, so **near-zero priceable is the CORRECT outcome and priceable
  volume is a bug signal.** WHAT IS NOT KNOWN: whether the pricing is REACHED.
  Board at 16:49Z read `index_size: 0` / `considered: 0` / `withheld_by_reason: {}`
  with all 3 games ESPN `state=pre` — **a zero is indistinguishable from an inert
  feature.** The proof is the refusal reason moving from
  `analytic_estimator_never_backtested_for_this_market` (category-wide) to
  `prob_interval_swamps_edge` (per-row).

- **Live in-game odds capture was silently dead for the full duration of any
  live game — fixed 2026-08-20, lane `wnba-live-odds-capture-gap`.** Root
  cause: the general combined `phase=live` sweep (`sports=mlb,wnba,soccer`,
  one launch per ~60-70s tick) genuinely takes several minutes to run, so
  almost every tick's `launch_refresh_run` collided with its OWN
  still-running prior launch (`ValueError: A refresh run is already
  active`) — confirmed live, repeating every ~65-70s for 16+ minutes
  straight against `live-odds-worker`'s own lane. NOT `#343`-shaped
  (ruled out directly against production OddsAPI). Fixed with an
  independent, WNBA-only live-phase autorun
  (`_launch_autorun_wnba_live_refresh`,
  `scripts/run_live_odds_refresh_worker.py`), own 240s cadence, own
  explicit refresh lane, `mode="fast"` to avoid the SmartSim OOM risk of
  running the full pipeline every few minutes. Deployed and env-verified
  live 2026-08-20 13:31:11Z (`SYNDICATE_ENABLE_WNBA_LIVE_REFRESH_AUTORUN=1`
  on `live-odds-worker`). **NOT YET behaviorally verified** — no WNBA game
  was live at deploy time, so `WNBA_LIVE_AUTORUN_LAUNCHED` has never fired
  for real. Next reader: check for that log line on the next live WNBA
  game and re-pull its `book_quotes` shard for a post-kickoff
  `captured_at`.
- **Layer-2 shortlist per-game cap removed 2026-08-20** —
  `SYNDICATE_SHORTLIST_ROWS_PER_GAME` was 6 (a global default, not
  WNBA-specific, but WNBA's edges concentrated heavily on one game a
  night, so it was the sport most visibly capped). Set to `0` on
  `refresh-worker` + redeployed. VERIFIED: WNBA's shortlist selection went
  from 6 rows (one game, at the cap) to 100 rows (70 game + 30 prop,
  spread across many games), confirmed stable hours later.

---

## [layer2_board_display] LAYER 2 BOARD -- USER-VISIBLE DISPLAY BUGS, 2026-08-20 AUDIT

### 2026-08-21 -- FOUR MORE, ALL THE SAME SHAPE: a number computed in one frame, displayed in another `[code + artifact evidence, NOT a served-board read -- see the gap below]`

Found from a user screenshot of the served board (one MLB game, all LIVE rows).
Fixed on `claude/layer2-odds-refresh-kbcxs8`, lane
`layer2-sim-view-and-live-projection`. **NOT deployed** -- `autoDeploy = no`.

- **`Win%` WAS THE BOOKS-QUOTING MULTIPLIER, NOT A PROBABILITY.** `layer2_board.py`
  published `score["book_confidence"]` as `confidence`, and
  `intelligence.html:2180` renders `confidence` as the column labelled **Win%**.
  So **"Win% 100%" meant "5+ books quote this market"**. Confirmed 5/5 against the
  screenshot with nothing left over: 1 book -> 50%, 2 -> 70%, 3 -> 85%, 14 -> 100%,
  21 -> 100%, exactly `_book_confidence`'s `((1,0.5),(2,0.7),(4,0.85))` ladder.
  This is the most severe of the four: a reader takes it as a certainty.
  Now carries the side-correct model probability; blank where there is no model.
- **`model_probability` WAS THE WRONG SIDE'S.** `layer2_board.py` published
  `projection["model_prob_over"]` with no side awareness. That field is always the
  OVER/HOME framing -- the same file proves it at `_model_edge_for`, which maps
  `"home": model_prob_over`. `sim_view` IS side-adjusted, so **away and draw rows
  rendered a coherent badge beside the other side's probability**. Repro:
  home -> `agrees`/0.62 (right); away -> `disagrees`/0.62 (away is 0.38).
  Fixed by `_model_prob_for_side`, mirroring `_model_edge_for`'s three-way/two-way
  logic rather than reimplementing it.
- **THREE HITTER MARKETS COULD NEVER PROJECT.** `_HITTER_BUCKETS` named mean fields
  that do not exist in the artifact, so `projected` was `None` on every row of
  those markets forever -- indistinguishable from thin model coverage.
  Measured at bucket-row level against a real `daily_summary` (2026-07-10):

      batter_runs_scored  wanted runs_mean     artifact writes  r_mean
      batter_doubles      wanted doubles_mean  artifact writes  2b_mean
      batter_triples      wanted triples_mean  artifact writes  3b_mean

  Matches the screenshot exactly: all 8 `batter_runs_scored` rows blank, every
  `batter_hits`/`batter_rbis`/`batter_hits_runs_rbis` row populated.
  **MEASURED BEFORE/AFTER ON THE SAME REAL ARTIFACT** (15 games, 6,210 hitter
  bucket rows), which is the strongest evidence in this whole block because it
  is a coverage number rather than a code reading:

      market               mean key BEFORE   before        after (r_mean/2b_mean/3b_mean)
      batter_runs_scored   runs_mean          0/810   0%     810/810   100%
      batter_doubles       doubles_mean       0/270   0%     270/270   100%
      batter_triples       triples_mean       0/270   0%     270/270   100%

  **0% -> 100% on 1,350 projections.** Values are the right MAGNITUDE, not merely
  non-null: triples projects 0.058 against P(1+) 0.057, and for a rare event the
  mean must approximate the probability -- a wrong-field join would not do that.
  **THE FILE ALREADY KNEW** -- `_HRR_COMPONENT_MEANS` is
  `("h_mean", "r_mean", "rbi_mean")`, so the HRR derivation read runs correctly
  while the runs MARKET did not, twenty lines apart.
- **THE LIVE SIM'S VERDICT WAS UNLABELLED.** `live_projection_join` already
  recomputes `edge_vs_market_pct` from `live_prob_over`, so on a re-priced live row
  `sim_view` WAS the live sim's -- nothing said so. "our pregame model dislikes
  this" and "the re-sim, watching the game, dislikes this" rendered identically.
  Now `sim_view: live_disagrees` + `sim_basis`, gated on
  `projection["basis"] == "live_resim"` and NOT on game state, so a pregame
  projection sitting in a live game is not mislabelled live.
- Also: exactly-zero `model_edge_pct` was bucketed as `agrees` (`>= 0`); now
  `neutral`. And `pipeline/layer2_shortlist.py` now PRINTS the live-join
  telemetry (`LIVE_PROJECTION_JOIN sport=... projected=... lens_indexed=...
  miss_player=...`), which previously existed only inside the artifact payload --
  so "why is the Live column blank" was unanswerable from production logs.

**THE VERIFICATION GAP, STATED SO IT IS NOT CITED AS DONE:** none of this was read
off the served board. This session's egress proxy returns **403 for
`syndicate-an21.onrender.com`**, so the evidence is code + the real artifact files
+ the user's screenshot. Per this section's own 2026-08-20 note, checking the raw
shortlist row shape is NOT sufficient for this class of fix -- the read owed is of
`boardContract.cards`. Tests discriminate (5/5 fail pre-fix, pass post-fix), which
is not the same thing as a production measurement.

**Blank LIVE cells are NOT all a bug.** `attach_live_projections`' own telemetry
records the ceiling: the live lens indexed 81 rows against 1,385 live board rows
(2026-08-13). The join cannot project what the lens never produced, so some blanks
are correct and the fix for them is in the lens, not the board. The new log line is
what separates "lens produced nothing" from "lens had rows, join missed".


**All five items from the 2026-08-20 user-directed board audit are FIXED and
LIVE-VERIFIED.** `syndicate/templates/intelligence.html` unless noted.

- **Over/Under picks now show direction.** `propLine()` dropped the
  selection word (`"Under"`/`"Over"`) whenever it matched the card's
  fallback title, which is EXACTLY when both were the same placeholder
  value. **VERIFIED live: 273/273 (100%)** over/under rows show direction
  post-fix.
- **Projected is no longer blank for most moneyline rows.**
  `displayProjection()` had no fallback for h2h (no natural number to
  project pregame). Added a probability-derived fallback. **VERIFIED
  live: 84 of 94** previously-blank h2h `Projected` cells now populated
  (remaining 10 lack `model_probability` upstream — a real backend
  coverage gap, correctly left blank, not fabricated).
- **Live-game Projected/Live/Actual semantics fixed, backend.** Two
  independent gaps: (1) `live_projection_join.py` preserved the pregame
  number under `sim_projected` (`#412`) but then still overwrote
  `projected` itself with the live re-sim value three lines later,
  contradicting its own comment — measured 34/40 live rows with
  `projected == live_projected` pre-fix. (2) `_live_projection_columns`
  (`layer2_board.py`) never mapped `actual_so_far` to `actual` at all —
  zero hits repo-wide before the fix. **VERIFIED live (on the actual
  served surface, `boardContract.cards` — the raw `/api/board/layer2-
  shortlist` row shape exposes this data differently and checking only
  that is NOT sufficient for this class of fix): 36/48** live MLB prop
  cards now show a populated `Actual` and a distinct `Live` projection.
- **Movement/steam display fixed.** `renderMovement()` only read the
  legacy `line_odds_movement` nested shape; the real data moved to
  top-level `movement_state`/`movement_price_delta`/etc months ago
  (`#372`) and the frontend never followed — every tracked/flat row
  rendered blank regardless of real movement data existing. **VERIFIED
  live: 169/169 (100%)** tracked/flat rows now render real movement text
  (e.g. "Odds +226 · 12h ago"). Steam badge logic confirmed correct by
  code read; no real steam event occurred during the verification window
  to observe directly (`steamRows: 0` at check time — a real, expected
  state given the size-and-clock bar, not a rendering gap).
- **Compact game-card "uniformity" was a render-order race, NOT a
  chip-matching bug.** Original hypothesis REFUTED by measurement: chip-
  matching is 100% correct for today's real games (15/15). The actual
  cause: `loadGameChips()` fired AFTER the synchronous initial render, so
  the mini-card strip's first paint always used the chip-less fallback
  style — even for today's real games — then visibly relaid out once
  chips arrived a moment later. Fixed: fetch chips first, gate the
  strip's first paint on a `gameChipsLoadedOnce` flag with a sized
  skeleton placeholder instead of the wrong-shape fallback.
  **NOT live-verified with a timed capture** — confirmed by code read
  (exact line numbers for both bug and fix) plus the existing
  `deriveGameCards` Node harness (unaffected, still 10/10), not by
  screenshot/network-waterfall. Flag this gap to whoever next touches
  the game-card strip.

---

- **The soccer projection read was ONE DATE against a SEVEN-DATE quote window**
  `[moved here 2026-08-18 from a WNBA state snapshot]`. `#379`'s widening shipped
  inert — its only caller never passed `window_dates`. Fixed (`b4d82364`), **NOT
  deployed**. `window="slate"` is required; the resolver defaults to `"day"`.
- **Soccer's `recommendations_<date>.json` is NOT in `HOT_ARTIFACT_PATTERNS`** —
  it lives under `soccer_source/<league>/api/recommendations/` while the allowlist
  covers `source_artifacts/data/processed/`. `/api/ops/artifacts/export` returns
  `count=0` for it. **`/soccer/<league>/api/cards` is the readable substitute.**

## [sharp-reference-price] SHARP REFERENCE PRICE — WE HAVE ONE. The audit's caveat is STALE.

**The models audit's "no Pinnacle, Circa or exchange in the feed" was true when
measured and is FALSE now.** The feed widened between 08-05 and 08-09 and nobody
re-read it. `[measured 08-15 from data/mlb_source/tracking/book_quotes/]`

| dates | distinct books | pinnacle rows | shard size |
|---|---|---|---|
| 07-28 .. 08-05 | **11** | **0** | ~13 MB/day |
| 08-09 | **37** | **2,604** | **217 MB/day** |

- **Sharp coverage on MLB GAME LINES is 102 of 102 markets = 100%** on 08-09.
  Sharp set present: `pinnacle`, `betfair_ex_eu`, `matchbook`, `novig`,
  `prophetx` (plus `kalshi` / `polymarket` as prediction markets).
- **Sharp coverage on PROPS is 0%.** Prop CLV therefore stays a soft-consensus
  measurement and **must be labelled as such**; game-line CLV can be taken
  against a genuine sharp close.
- **THERE IS ALREADY A PER-SPORT LEVER FOR THE PROP GAP, and NHL uses it.**
  `syndicate/local_nhl_odds.py:542` defaults
  `PROPS_ODDSAPI_BOOKMAKERS = "fanduel,draftkings,pinnacle"` — Pinnacle is
  explicitly requested for NHL props. `vendor/nhl_betting_repo/.../odds_api.py`
  carries it in a book list too. So closing the 0% on other sports' props is a
  **config change on an existing knob**, not a build. `[from-code 08-15]`
  **Cost it before flipping it:** every added book spends OddsAPI credits
  against a cap already at **92.8% projected burn**, and props are the highest-
  volume market family. Measure the per-call delta on one sport first.
- **This removes the standing caveat on the whole CLV program** — "beating a
  closing consensus of eleven soft books can read positive where no exploitable
  edge exists" no longer applies to game lines.
- **The widening is almost certainly the lost-books capture fix**, which also
  explains the 13 MB → 217 MB/day jump. That cost is real and it is what the
  storage-format work (delta/columnar) exists to absorb — **do not "fix" it by
  narrowing the book set again; price shopping was measured at +2.79 ROI pts.**
- **Caveats, stated:** read from the git-tracked mirror, which is lossy, and
  only ONE post-widening date exists locally (08-09). **Confirm against
  production before publishing a sharp-referenced CLV number**, and re-read
  whether the 37-book set is still current.

---


## [layer1-layer2-boards] LAYER 1 / LAYER 2 BOARDS — session briefs exist; three facts worth not re-deriving `[code read 08-16 11:2x CDT, NOT a production measurement]`

Full briefs: `.syndicate/brief_2026-08-16_layer1_board.md`,
`.syndicate/brief_2026-08-16_layer2_board.md` (commit `01c53f56`). Lane names
`layer1-board-coverage` / `layer2-board-quality` are RESERVED BY BRIEF and
deliberately NOT opened in `lanes.md` — no session holds them yet.

- **L2 movement/steam is DISABLED IN CODE, not decayed by data.**
  `layer2_board.py:1152` is `return {}` with an unreachable body. `#372` turned
  it off because the in-builder ~20MB odds-history load **stalled the shortlist
  build for 70 minutes with no exception**. Naive re-enable re-stalls the board.
  Only `h2h`/`totals`/`spreads` have history at all (`:1244`); served overlap was
  event+market 11 of 73.
- **The L2 scoring model EXISTS** — `blended_score()`,
  `opportunity_signals.py:497-575`, `min(value, value*reliability)`. Auditing it
  is the work; rebuilding it is not. The `min()` is load-bearing (it corrects a
  sign inversion on negative-value rows, `corr -0.8312` vs `+0.8560` control).
- **Layer 1 already publishes its own projection-coverage instrument** — the
  header's `N markets / M with a projection`, via `_classify_enrichment`
  (`layer1_board.py:328`) / `_row_is_enriched` (`:176`). Do not build a second.

**NOT established, and stated here so it is not cited as if it were:** "Layer 2
has no book allowlist" is a **negative from a grep over one file**. Layer 1's
list IS confirmed (`DEFAULT_BOOKS`, `templates/shared/layer1_board.html:267`,
client-side JS). Trace the served `book` field to its writer before acting.


## [board-intelligence-engine] BOARD / INTELLIGENCE ENGINE — structural facts, archived — **ARCHIVED 2026-08-19 to `state_archive_2026-08-19.md`, verbatim.**

## [football-smartsim2] FOOTBALL (NFL + NCAAF) — smartsim2 runs on FOUR SCALARS `[measured 2026-08-18, lane football-model-owner]`

**Owner: `football-model-owner`.** Strategy, every measurement and the exit
criterion: `docs/ai_context/ncaaf_beat_the_close_strategy.md` (§0–§13).
Pre-08-20 detail archived VERBATIM in `state_archive_2026-08-20.md`.

### THE DIAGNOSIS — dominated, not broken `[measured 2026-08-20, 751 clean OOS games]`

`actual = a + b*market + w*(model−market)` → **b=+0.990** CI [0.909,1.076] (the
closing line is UNBIASED) and **w=−0.028** CI [−0.130,+0.069] (the model's
deviation carries ZERO information). r(market,actual)=+0.645 → R² **41.6%**;
r(model,actual)=+0.421 → R² **17.8%**. **Gap = 23.8 points of R².**

The model has REAL signal and is strictly dominated: everything it knows the
market knows, and where they differ it is noise. **This one fact explains every
failed remedy** — no threshold, weight or subset helps a dominated model, so
STOP re-testing them. `scripts/grade_football_model_weight.py`.

### IT LOSES TO A MINDLESS SIDE BET `[2026-08-20]`

always-bet-the-underdog **51.2%** vs model **46.8%** (NCAAF, 735 bets);
**58.9%** vs **54.7%** (NFL preseason, 95 bets) — **−4.4 / −4.2 points, two
independent sports**. NCAAF ATS gets WORSE as the edge filter tightens
(46.8% → 45.2% at 10+ pts). `scripts/grade_football_playability.py`.

### EVERY LEVER MEASURED, ALL DEAD — do not retry `[2026-08-20]`

| lever | verdict |
|---|---|
| situational (8 factors) | PRICED. 1,746 games, no \|t\|≥2. Positive control t=+2.70 |
| injuries | **PRICED — RESOLVED on 4,431 games / 17 seasons (2009-25)**. All 4 measures null (best −1.74). Power stated: detects ~0.18 pts, observed −0.146. A 4-season run read t=−2.10/−2.23 and that was a FALSE POSITIVE — per-season slopes swing +0.73/+0.71/−0.95/−0.80 with 3 seasons crossing \|t\|=2 in BOTH directions. ATS 51.3/51.1/52.1/59.5%, none clearing 52.4% |
| returning production | pooled ΔMAE −0.062, t=−0.89. **Code REMOVED** |
| `SP_RATING_SCALE` | every scale 6..24 loses |
| blending | w≈0 → optimal blend is 100% market |
| three scalar totals fixes | measured dead |

**A WORKTREE COMMIT DOES NOT UPDATE THE PRIMARY TREE, AND THE GAP IS A REVERT
HAZARD** `[measured 2026-08-20]`. Today's `lanes.md` trims were committed from
worktrees; the SHARED tree's copy stayed at **127,558 B against origin's
106,084** — 21 KB stale. Any session editing `lanes.md` there and pushing would
have silently REVERTED the 34 KB trim and every lane edit landed since. After
working from a worktree, **sync the shared tree's copy back**, and verify by
HASH not by size. Note `git reset --keep origin/main` correctly ABORTS while
another session holds an uncommitted file (it hit `deploys.md`), so the safe
move is a single-file `git checkout origin/main -- <path>` followed by a commit —
`checkout <rev> -- <path>` writes the index EVERY session shares, and a stray
staged file is what gets swept into someone else's commit.

**THE `smartsim2_projections_*.csv` ALLOWLIST IS ORPHANED — THREE HANDOFFS HAVE
NOW FAILED** `[verified on origin 2026-08-20, after the NFL allowlist landed]`.
`basketball-model-owner` was asked twice and archived without acting;
`soccer-odds-capture-cadence-gap` closed; and `nfl-artifact-allowlist-add`
CLOSED-VERIFIED having added the NFL **injuries / roster / depth** patterns —
**not this one**. Checked `origin/main:artifact_publisher.py` directly: no
`smartsim2_projections` entry. `tests/test_football_projection_publish.py` still
reports **1 xfailed**, which is the designed signal.
**Consequence:** both football generators' `publish_hot_artifact` calls remain
INERT, and NCAAF projections still reach web ONLY via git + a web deploy — a
production deploy per model change. Whoever wants this fixed should add the one
line themselves rather than hand it off a fourth time.

**THE SOCCER SUITE IS SLOW BECAUSE OF ONE FILE. Both of my earlier diagnoses
were measurement bugs** `[bisected 2026-08-20]`.

    tests/test_soccer_market_anchoring.py  ALONE  13 passed in 1,064s (17m44s)
    the other 41 soccer files                     ~136s combined
    collect-only, all 8,900 tests                    6.06s

Eight tests in that ONE file: 241s, 163s, 124s, 122s, 120s, 118s, 116s, 55s.
They call `simulated_home_win_probability(simulations=300)` and
`solve_market_rating_shift(simulations=100)` — **Monte Carlo inside a solver
loop**, so every solver iteration runs hundreds of match simulations. Real
compute; not a fixture, not collection, not accumulated state.

**RETRACTED — THREE claims, all mine, all from measurement bugs:**
1. *"The cost is COLLECTION."* No: collection is 6.06s for all 8,900 tests.
2. *"Use explicit file lists, not `-k`."* No: explicit was SLOWER (875.8 vs 822.4).
3. *"Superlinear TEST INTERACTION, 4.76x."* **No — and this is the instructive
   one.** My per-file timing loop used `timeout 300`, which KILLED this file and
   wrote `none`. It never entered the "sum of individual runs", so the baseline
   was missing the single most expensive file. Files 1-25 showed 1.0x only
   because this file is #31. **There is no interaction effect.**

**What is actually true:** one pathologically slow file dominates. **CONFIRMED by removing it:**

    all 67 soccer files                    875.8s
    the same minus that ONE file (13 tests) 149.6s   633 passed, 0 failed
    -> 5.9x faster; that file was 83% of the suite's runtime

So `--deselect tests/test_soccer_market_anchoring.py` makes the soccer suite
usable as a pre-deploy gate (under 3 minutes) instead of ~15. **The proper fix
is that file's own `simulations=` counts, and it is NOT mine to make:** lowering
a simulation count to make a test fast is how a test stops testing anything, and
the precision each assertion needs has not been analysed.

**Note on precision:** the same file measured 511s inside a 42-file run and
1,064s alone, because several runs overlapped on this machine. Treat the
magnitude as "8-17 minutes, dominant either way", not a precise constant.

**CONSOLIDATED DEPLOYS ARE THE WORKING PATTERN FOR A BUSY DAY** `[2026-08-20]`.
114 files / 5+ lanes / **3 deploys**: refresh-worker `db469003` (9 files,
19:09:55Z), live-odds-worker `a381d652` (38, 20:04:14Z), web `454f3caa` (67,
20:20:34Z). Each verified BY CONTENT per file; web also on the served payload.
Tool: `scripts/build_consolidated_graft.py`. **It prevented two reverts,
measured**: web's parent moved TWICE mid-build so the file list was RECOMPUTED
(67→68→67, dropping `soccer/cards.py` once another deploy carried it), and the
builder REFUSED a graft when web read `d9a23a38` as live while `00541a8d` was
`update_in_progress`. **Reading the parent live is NOT enough — an in-flight
deploy leaves the OLD sha reading live.**

**THE SESSION DIGEST DOES NOT READ state.md, AND READS ONLY HEADINGS FROM
learnings.md** `[measured 2026-08-20 from .claude/hooks/session-start.sh]`.
state.md's own size costs nothing at session start — the hook's header records
that v1 cat-ed it, spent the whole ~2KB budget, and that was the bug being
fixed. learnings.md is grepped for FORBIDDEN/EXONERATED **headings only**, and
`lanes.md`'s OPEN LANES section truncates on **lane COUNT** (`LANE_CAP=600` vs
~6,489 B raw), not on file size — trimming lanes.md 134,022 → 98,118 B did NOT
stop it truncating. **So "LEDGER OVER BUDGET" is a byte warning about the cost
to whoever OPENS a file; it does not describe the digest.** Do not trim these
files expecting the digest to change.

**35 of 44 STANDING RULES REACHED NO SESSION until 2026-08-20.** The digest
grepped `^###` while learnings.md entries are written at `##` — 8 matched, 35
invisible, including "never point a worker publish URL at a public hostname".
Fixed in `362c505d`: matches `^#{2,3}`, clips each entry to 64 chars, takes the
TAIL so the newest rules show, and prints "showing 6 most recent of 43".
**Relaxing the grep alone would have been worse** — 43 headings ≈ 4,800 B against
a 450 B cap taken in append order would have shown only the OLDEST. That edit is
a CROSS-LANE take of `.claude/hooks/` (claimed by `repo-coordination`, OPEN)
made under explicit user instruction and messaged to them.

**NFL CLOSING LINES ARE FREE AND LOCAL — do not buy them.** nflverse
`schedules/games.csv` (2.2 MB) carries `spread_line` and `total_line` back to
**1999** alongside final scores; fetch via
`ingestion/nflverse_ingestion.py`-style release URLs, cached under
`tracking/nflverse/schedules_games.csv`. **`spread_line` IS the home-margin
prediction** (positive = home favoured), verified empirically: r=+0.431 with
realised home margin, MAE **10.264 as-is vs 14.645 negated**. Using it negated
inverts every conclusion while producing plausible numbers.
**OddsAPI historical NFL starts in 2020** — 2018/2019 return zero events (billed
0 credits), so a pre-2020 backfill buys nothing.

**NO USABLE NCAAF INJURY FEED.** CFBD's OpenAPI spec: **74 endpoints, none**.
ESPN core — NFL control **597 fresh injuries / 8 teams** vs CFB **1 record
across 60, dated 2020-11-21**. Cause: the NCAA has no mandatory injury report.
Re-check in-season with `scripts/probe_ncaaf_injury_feed.py`.

### SERVING STATE

- **Picks SUPPRESSED**, `syndicate/features/football/pick_gate.py`, default-DENY.
  `LIFT_CONDITION` (web `ea6f431f`, 8/8 probes) requires: ATS above the better
  naive baseline, 95% CI LOWER bound above **52.4%**, out-of-sample with subsets
  pre-specified, denominators in **BETS not rows** (per-book rows overstated
  significance **3.4×**). Pinned by `LiftConditionTests`.
- **Board serves SP+, WEEK 1 ONLY** (pregame window). 51 games, \|margin\| max
  50.60, SD 12.93. **A SINGLE READ IS NOT A MEASUREMENT** — 12 probes once read
  9 PPA / 3 SP+ because gunicorn workers cache independently. Probe repeatedly.

### ENGINE FACTS THAT REMAIN TRUE

- **9 feature blocks / 65 keys consumed, 0 of 3 production entrypoints pass a
  payload.** Every NFL/NCAAF game runs on four rating scalars plus a hardcoded
  `pace_seconds_per_play=24.0`. Reachability: 21 of 21 drive-prior fields move
  when fed. **Wiring it is NOT indicated** — §10's domination result means the
  payload path cannot supply what is missing. Gate:
  `scripts/football_sim_input_checklist.py`.
- Of the unfed blocks: `defensive_metrics` is **MISROUTED** (all 7 keys sit in
  `team_metrics`), `pace` is **NULL AT SOURCE** (all 4 keys `None`).
- **TWO unrelated football models exist.** `FootballSimulationAdapter` is not
  smartsim2; do not conflate them.
- `smartsim2/calibration_profile.py` showing as `M` in `git status` is a CRLF
  artifact, not an edit.

### OPERATIONAL — cost hours to learn

- **The artifact reaches web via GIT → WEB DEPLOY → BOOTSTRAP → MOUNTED DISK,
  NOT via the worker.** `smartsim2_projections_*.csv` matches none of the 127
  `HOT_ARTIFACT_PATTERNS`; web reads `SYNDICATE_NCAAF_SOURCE_ROOT`;
  `bootstrap_data_root` copies and **never prunes**. So the refresh-worker
  season-projection autorun regenerates a file **nothing reads**, and deleting a
  stale artifact from git does NOT remove it from the served disk.
  **CHANGED 2026-08-20 (`32148cac`, live on web `15a0be64`) — this path is now
  SEED-ONLY.** The boot sync copies an artifact root file only when the
  destination is ABSENT. A NEW week's `smartsim2_projections_*.csv` is a new
  path and still arrives; a REGENERATED file for a week already on the disk no
  longer overwrites it. Pruning is unchanged (still none). This makes the
  allowlist + `publish_hot_artifact` path the only way to UPDATE an NCAAF
  artifact already on web, so the owed allowlist entry is now load-bearing
  rather than tidy. Both
  generators now call `publish_hot_artifact`, INERT until
  `*_source/data/smartsim2_projections_*.csv` is allowlisted (handed to
  `soccer-odds-capture-cadence-gap`; asserted as `expectedFailure`).
- **`deploy_preflight --service web` can NEVER return CLEAR** — web emits no
  process telemetry. Use `--allow-off-main` and read the live SHA directly.
- **Do NOT diagnose NCAAF from a local checkout** — `data/**` is a lossy mirror.
- Stage 0 ledger: `syndicate/features/football/pick_ledger.py` +
  `build_ncaaf_pick_ledger.py` / `build_nfl_preseason_pick_ledger.py`.

## [nfl-archived] NFL — earlier closed work, archived — **ARCHIVED 2026-08-19 to `state_archive_2026-08-19.md`, verbatim.**

## [test-baselines] TEST BASELINES

- **`tests/test_intelligence_state.py` — `224 passed, 10 subtests passed, 0
  failed in 1361.70s`** `[measured 2026-08-20, lane intel-empty-pool-fallback-test,
  todo.md #495]`. **It costs ~23 minutes, NOT the ~15 this line used to say.**
- **READ THE NEXT TWO BULLETS BEFORE QUOTING THAT NUMBER.** This entry said, for
  six days and in bold, that the file *is NOT "224 green" — that line was wrong
  and is corrected here.* It is now 224 green again. **That is not a reverted
  correction and must not be tidied into one** (`learnings.md` 08-20 forbids
  re-applying a ledger edit by restoring an old revision). The 08-14/15 refutation
  was RIGHT when written; both failures it named have since been resolved on their
  merits:
  - `..._fallback_merge_falls_back_on_empty_pool` — **fixed 2026-08-20**. The TEST
    was the stale side: it asserted a `force_refresh` kwarg `#387` deliberately
    removed from the `collect_all_recommendations:empty_fallback` call site. The
    branch under test had been behaving correctly the whole time. `todo.md` `#495`.
  - `..._recomputes_when_cached_snapshot_is_stale` — **passes on `main`**,
    re-measured 2026-08-20 (72s), individually, not inferred from a suite total.
    Cause of its recovery not investigated.
- **LINEAGE CAVEAT DISCHARGED — this number IS a tip-of-`main` reading.**
  Re-measured at `56b4dd41` (tip): **`224 passed, 10 subtests passed, 0 failed in
  1668.24s`**, identical pass/fail to the first run, which was taken on the primary
  tree's lineage (`d2222426` + the fix), 30 commits behind. **The 34 commits of
  product code between them change nothing for this file.**
- **The COST figure is the one thing that moved: 22:41 then, 27:48 now.** Read
  **~25-30 min**, not ~23. Other sessions were writing the shared `data/`
  throughout both runs, so load is the likely cause — **not isolated, not
  claimed.**
- **HOW the tip run was taken, because a naive re-run would NOT have been valid.**
  `learnings.md` 08-16 forbids a fresh `git worktree` as a baseline for anything
  that reads `data/`, and this suite DOES reach the real disk (`tests/conftest.py`
  isolates `data/prediction_ledger.json` precisely because tests were writing it
  through `data_root()`). So: worktree at tip, sparse-checkout of every top-level
  dir EXCEPT `data/`, and `data/` supplied as a **junction to the primary tree's
  `data/`** — the same bytes the first run used, making the product code the only
  delta. **`SYNDICATE_DATA_ROOT` alone would have been WRONG:** `data_root()`
  honours it, but `REPO_ROOT / "data"` and the per-sport path helpers do not, so
  those reads would have silently fallen back to the worktree's own lossy copy —
  the inert-redirect failure that rule was written about.
- **Neither run is hermetic.** The junction shares a LIVE directory that other
  sessions write, and the suite writes into it. Same exposure both times, so the
  comparison holds; a sealed number is still untaken.
- **Gate against the lineage you are shipping, not against `main`** — the rule
  that made the old `218 passed / 6 failed` at `2b14fbeb` worth recording. It is
  satisfied here, not waived.
- **`tests/test_intelligence.py` is 218 passed / 0 failed on committed `main`**
  `[measured 08-15 ~21:5xZ, lane red-intelligence-tests]`. It was **216/2** at
  the start of that session and 217/1 mid-way. All three reds were real, and
  **two of the three were product defects, not stale tests** — see
  `todo_closed.md` `#436`/`#438`. **It costs ~37 minutes**, single-threaded;
  `pytest-xdist` is NOT installed, so there is no faster path today.
- **The "526 passed, 0 failed" line below is NOT contradicted by that, but it is
  narrower than it reads.** Three `test_intelligence.py` failures existed on
  committed code at 08-15 21:00Z, so whatever that full-suite run covered, it
  either predates them or did not include this file. Treat it as unverified for
  `test_intelligence.py` specifically; the line above is the direct measurement.
- Full suite: **526 passed, 0 failed** after the soccer `as_of` fix `[08-15]`.
- `tests.test_archives` (what CI runs) — **383 pass, 2 skipped, ~6 min**
  `[re-measured 2026-08-19, lane ci-green]` — **but only OUTSIDE 00:00-05:00Z,
  and only on a Central machine.** See the next line; the unqualified version of
  this line was wrong.
- **CI WAS TIME-DEPENDENT — structurally RED ~5 HOURS EVERY DAY — NOW FIXED AND
  VERIFIED INSIDE THE WINDOW** `[run 32323646103, `df8aec91`, 02:09Z, 2026-08-20,
  #482]`. 11 consecutive failures 01:24-01:53Z in the same UTC band without the
  fix, then green with it. **Held overnight: 18 of 19 runs inside 00:00-05:00Z
  green**, a band that was previously 100% red.
- **Test assertions must not depend on the ambient `data/` mirror**
  `[#487, 2026-08-20]`. The one remaining overnight failure was
  `test_archive_launch_links_and_tracker_copy` asserting home-page markers that
  `_home_sport_stack.html` only renders when a sport is present and
  `active_today` — i.e. a function of what the mirror held for
  `central_today_iso()`, not of the page. `build_home_overview` is now pinned to
  a fixture there. **`#480`, `#482` and `#487` are all closed; CI is green in
  both time windows.**
- **`Daily Update`'s cron is REMOVED** `[#486, 2026-08-20, user decision]` —
  "we no longer use that daily update feature, everything runs on render."
  `workflow_dispatch` kept for manual backfill/recovery. Confirmed it did not
  fire on 08-20. Its steps 12-13 have not executed since 2026-07-15 and were
  never proven end to end. 7 `test_archives` tests computed "today" with
  `date.today()` — the runner's date, **UTC** on GHA — while the routes use
  `central_today_iso()`. CDT is UTC-5, so **00:00-05:00Z they disagree** and the
  suite fails no matter what was pushed. Evidence is a clock, not a diff: 16
  consecutive greens 2026-08-19 23:25-23:53Z, then 29 consecutive reds from
  23:57Z; across 45 runs, 28 failures inside the window vs 11 successes outside.
  **Fix applied (assert `central_today_iso()`); a Central dev box CANNOT
  reproduce it, so only a CI run inside the window proves it.** `Daily Update`
  runs 06:00Z and is outside the window.
- **CI RUNS `unittest`, NOT `pytest`, AND `conftest.py` DOES NOT EXIST TO IT**
  `[verified 2026-08-19]`. `ci.yml` runs `python -m unittest tests.test_archives`
  and `daily-update.yml` runs 13 modules the same way, while the documented
  local loop is `python -m pytest tests/`. `tests/conftest.py` is a pytest
  plugin file, so **every autouse fixture in it is absent in CI**. Measured on
  one commit, one machine, one minute: `tests/test_wnba_cards_merge_aliases` was
  `20 passed` under pytest and `FAILED (failures=2)` under unittest. **A green
  local pytest run is not evidence about CI.** Shared setup a CI-run module
  needs belongs in `tests/_cache_isolation.py` (plain functions + a `TestCase`
  mixin, which `conftest.py` now delegates to), not in `conftest.py` alone.
- `daily-update.yml`'s 13-module contract list — **55 pass**
  `[measured 2026-08-19]`, the same count CI reports.

---


## [open-problems] OPEN PROBLEMS

- **The refresh-worker anon floor is UNNAMED** (`#423`). Allocator, GC-tracked
  objects, the board build and the MLB cards cache are all eliminated.
- **The 20:03:11Z OOM is UNEXPLAINED**, and the 3000 MB floor in front of MLB
  stays until it is.
- **Why the soccer pregame odds step fails is UNKNOWN.** No error observed.
- **Something allocates 493–878 MB in-process on refresh-worker and nothing knows
  what** (`#327` residual). Released within ~72s, arriving 11–42 min apart.
  `post_mlb_sim_tick` is a BYSTANDER. **Only counts have been measured, never
  bytes.**
- **`#312`'s `sync: false` protection is on `main` and live on NOTHING**, and the
  `blueprint_sync` mechanism remains untested — the only deploy carrying it was
  cancelled. That is the wrong experiment, not a null result.
- **Chronic instance restarts across the fortnight**, instance count dropping to
  0, pegged CPU. Cause unconfirmed.
- **MLB sim model-side as-of-ness is UNKNOWN.** The backtest is PIT-safe by
  replay, which says nothing about the model's own inputs.
- **`Daily Update`'s artifact-backup steps (12-13) have not executed since
  2026-07-15** `[verified 2026-08-19, #481]`. Three blockers stood in front of
  them and all three are now cleared: `ADMIN_TOKEN` (absent 07-16, added the
  same day), an account **billing lock** that killed every run 07-16..08-15
  before any step (3-second jobs, empty `steps[]`, no retrievable log — which is
  why the per-step API reported no failing step for that whole month), and the
  test step `#480` fixed. The step itself was also rebuilt (`#481`) and hand-run
  green against production. **Nothing has yet been proven END TO END by the
  workflow. The next scheduled 06:00Z run is the first; do not record the backup
  path as working until one shows both steps green.**
- **NBA / NHL / NCAAB feature point-in-time status UNKNOWN** — no harness reaches
  them.
- **NHL and soccer market anchoring** make those engines' market-relative
  evaluation partly circular. Quantify before believing any CLV number for them.

- **`/api/ops/clv/report` WORKS AS OF 2026-08-15 19:36:45Z, and it produced this
  system's first unbiased CLV number.** It had been blind: the route runs on
  **web**, `load_openings` is a `path.exists()` on a local file, and web was
  answering refresh-worker's publish with `HTTP 403 FORBIDDEN` because web's
  `HOT_ARTIFACT_PATTERNS` lacked `reports/intelligence/clv_openings/*.jsonl`
  while the worker's had it. Shipping that one allowlist line to web
  (`bebe87c9`; also `baec34a8` on main — it had existed on NO main branch)
  flipped `PUBLISH_FAILED`×8/16h to `PUBLISH_OK` 15s after deploy, zero failures
  since. MLB 2026-08-15: `openings 0→520`, `resolved 0→293`, `same_book_n 0→144`.
- **CLV ON 2026-08-15 IS `-0.2714` (n=151, beat 27.2%), MLB, same-book AND
  pregame.** Web `c8810f45` live 21:58:19Z. Verified by recomputing the mean from
  the served rows at the same instant (`-0.2714` both ways). **PRELIMINARY —
  taken 21:5xZ, before the last first pitch (2026-08-16T01:40Z). NOT the settled
  number; the settled read was never taken (see OWED, below).**
- **THREE JOIN DEFECTS FOUND AND TWO FIXED, in order of severity:**
  1. **FIXED — `observed_transition` was side-blind.** `closing_price` is
     `entity`'s price and **`entity == home_team` on 18/18** stamped markets, so
     every away-side opening was differenced against the HOME close. A stamp is
     now used only when the opening IS the entity's side, else it falls through
     to the side-aware `last_pregame_quote` path. Measured: 20 refusals,
     `observed_transition` 48 -> 22, `same_book_n` 131 -> **151** (rows that were
     being discarded now resolve correctly).
  2. **FIXED — the headline counted in-play prices.** `close_age_seconds` is
     `(commence - stamp)`; negative means post-first-pitch. Now excluded and
     reported as `by_close_timing`. **The in-play bucket flipped sign between
     readings (-ve at 21:1xZ, `+0.7937` at 21:4xZ), so it was NOISE, not a bias**
     — the old code would have published `-0.0124` at 21:4xZ.
  3. **NOT FIXED — the odds-history feed transposes `home_line`/`away_line`.**
     Event `69928d29…` FanDuel spreads carried identical prices (`-205`/`+168`)
     under OPPOSITE labels at 06:02Z and 21:26Z. The line guard checks numeric
     equality, so it matched the wrong bet. **Severe per row, self-cancelling in
     aggregate** (the two extremes are a mirror pair; spreads n=42 mean `+0.515`
     median `0.000`; h2h/totals n=128 have zero |clv|>10). Corrupts
     per-recommendation CLV, variance, CIs and any "worst bets" list.
- **`clv_pct` per recommendation is NOT built** — the lane's original goal. The
  ledger's `PredictionResult.clv_pct` field exists and is never populated, which
  is why `/api/portfolio/summary` returns `avg_clv: null`.

- **Lane markers are per-session as of 2026-08-15.** `lane-guard.py` reads
  `.syndicate/.current-lane.<session_id>` first and falls back to the shared
  `.syndicate/.current-lane`. Write your slug to YOUR file; the global one is
  contended by every live session and will block edits to your own lane's
  files. Verified: global-only still blocks, per-session allows own lane,
  per-session naming a different lane still blocks.


## [shipped-verified] SHIPPED / VERIFIED — current status by item `[2026-08-18; replaces a dozen dated snapshot sections]`

One line per item. Where a thing is live, the SHA is the one that carries it, not
`main` — the three services run separate lineages and `main` is on none of them.

| item | status |
|---|---|
| refresh-worker OOM | **FIXED** `59c07221` + `8e3d2f95`; slow ratchet remains |
| odds-sweep ownership gate (`20025cc4`) | **HALF-WORKING** — fires on live-odds-worker (`kept=mlb,wnba,soccer dropped=nfl,ncaaf`), NOT reached on refresh-worker. `#129` reads OPEN again. |
| WNBA phase-2 autorun | **INERT** — launcher fires, `launched=ok runStamp=None artifactsDir=None`, `MAIN_ENTRY` never appears. Reproduced across two boots. |
| soccer live lens (`6bdc50de`) | **FIXED** — 7 leagues → 10; the three that vanished were exactly the three with matches in play |
| soccer projection window (`6aaa11af`+`b4d82364`) | **WORKS — DO NOT USE THE OLD 4-of-1,142 FIGURE.** Measured 2026-08-22 18:04:56Z (`PREGAME_PROJECTION_JOIN`, refresh-worker): `considered 20,014`, `projected 9,598` (48%), `with_prob 8,922`, `matches_in_source 95`, all 10 leagues indexed, `ambiguous_keys 0`, full 7-date window read. The remaining gap is **player identity, not team names**: `unmatched_player 5,138` > `unsupported_market 2,691` > `unmatched_match 2,587` (only 12 distinct fixtures). `todo.md #503`. |
| soccer live-lens observability (`461774cb`+`481de91d`) | live both workers; **emits only on failure**, so no reading yet |
| monotone props seal (`bafb4fb2`) | **ROLLED BACK** at its requester's sequencing objection; 08-19 cadence read is unconfounded |
| MLB live game-line model | **SCORED — the model LOSES to the market** on every population |
| soccer team-name aliases (`2b0b708b`+`2e3265d7`) | **FIXED AND VERIFIED IN PRODUCTION, twice.** 13 aliases. `unmatched_match_rows` **2,587 -> 87** (-96.6%), `unmatched_fixtures` 12 -> 3, `rows_with_projection` 9,598 -> **10,684** of ~20,025 (48.0% -> 53.3%); belgian/epl/la_liga/mls/serie_a to exactly zero. `matches_in_source` 95 and `ambiguous_keys` 0 unchanged across the measurement, and the result HELD on a second reading 17 min later. Offline reachability: 0 of 13 fixtures join with the map emptied, 13 of 13 with it. Survivors are fixture-absence, not names: the board carries BOTH directions of `PSG v Rennes` (81 rows), and primeira_liga's Braga/Benfica are absent from the sim slate. |
| soccer LIVE edge (`edged=0`) | **CAUSE MEASURED 2026-08-22 18:04:56Z: a DE-VIG gap, not the pregame join.** `edge_withheld=133, edge_why={'no_fair_value_devig_failed': 133}` — 133 of 133 rows HAVE a pregame projection, which REFUTED the hypothesis the split was built to confirm. Soccer player props are one-sided, so `market_fair_prob_over` is never set; `attach_margin_model`'s replacement lands in `quote["fair_probability"]` (`layer2_board:1097`) while the live join reads `projection["market_fair_prob_over"]` (`live_projection_join:718`). The number exists and the reader cannot see it. **Bridging it is a PRICING decision** — `layer2_board:587-604` treats a `book_margin_model` fair as an ESTIMATE (12% prop hold vs 4.5% moneyline). NOT taken. |
| refresh-worker memory accumulation | **UPTIME-DRIVEN AND FULLY RECLAIMED BY A RESTART — measured twice on 2026-08-22.** 96.8% / 2,019MB "unexplained" -> **2.3% / 2.9MB** across the 19:29Z restart; and 90.9% -> 15.6% across the 17:04Z one. Not a leak that survives the process, and not any single job's working set. It re-accumulates over hours. |
| publisher sweep vs `_PUBLISH_MAX_BYTES` | **A FILE OVER THE 12MB CEILING HAD NO RETRY PATH — fixed `468faace`, SHIPPED AND UNPROVEN IN THE FIELD.** `publish_hot_artifact` withholds its checksum on failure because "a failed publish must be retried next sweep"; `_publish_skip_reason` refuses over-ceiling files BEFORE that function is reached, so the retry it names did not exist for the largest artifacts. The ceiling is NOT raised (its own comment forbids it; the sweep would then ship 51MB odds_history shards every cycle) — the bound is exempted only for paths a direct publish already FAILED on, and the exemption ends on the next success. Affirmative token: `SWEEP_REPAIRING`. A quiet log proves nothing. |
| MLB sim cadence vs deploys | **WAITING FOR "NO SIM RUNNING" IS UNBOUNDED.** Three `run_mlb_daily_sim_job` runs fired in 2.5 hours on 2026-08-22 (2-game 17:02, 15-game 18:51 taking ~26 min, 5-game 19:16) and a 4-game one started during the 19:38 deploy. The usable rule is to wait for an EXPENSIVE run, not for silence; `fingerprint_change` runs re-fire automatically. |
| production HTTP from a Claude session | **UNREACHABLE.** The agent proxy returns `connect_rejected — gateway answered 403 to CONNECT` for `syndicate-an21.onrender.com:443`. Not auth. Every production fact must come from Render LOGS via MCP; do not budget time for curling the board or `/api/ops/...`. |
| soccer model | **LOSES to the market** — multiclass Brier 0.5875 vs 0.5737, worse in 8 of 9 leagues; errors sit on FAVOURITES |
| `#445` NCAAF season projections | FIXED, **not deployable until the season opens** (~08-29) |
| `#455` / `#456` | both FIXED; deploy state per service, check by content |
| game shape | contract for five sports, **n = 0** — emit still blocked |
| play-by-play coverage | **5 sports of 8** |
| WNBA pbp | **not a corpus** |

## [fleet] FLEET `[2026-08-18 02:1xZ — goes stale in minutes; re-read before deploying]` — **ARCHIVED 2026-08-19 to `state_archive_2026-08-19.md`, verbatim.**

## [deploy-ownership] DEPLOY OWNERSHIP — SELF-SERVE BEHIND TWO LOCKS `[verified 2026-08-18, user decision, REPLACES the coordinator role]`

**There is no coordinator session.** `.syndicate/coordinator.id` is DELETED,
`coordinator.md` is a tombstone, and `.syndicate/deploy/requests/` is retired
(a README there names the two requests that were still pending).

**DEPLOY A SHA CONTAINED IN `origin/main`** `[2026-08-18, user decision]`.
`deploy_preflight.py` returns **`OFF_MAIN` (exit 4)** otherwise, and the guard
blocks on it like any non-CLEAR verdict. Escape hatch `--allow-off-main`, said
out loud in `deploys.md`. **Measured: 170 remote `origin/deploy/*` branches
exist and every sampled tip is OFF main** — two such deploys do not contain each
other, so the second silently reverts the first. Serialisation is not
composition: the claim ORDERS deploys, only being on `main` makes them
CUMULATIVE.

**The preflight receipt is bound to its SHA.** A CLEAR taken for one commit does
not authorise deploying another for the next 15 minutes, or `OFF_MAIN` would be
sidestepped by preflighting a main commit and shipping something else.

**UNVERIFIED and stated as such:** this predicate has never gated a real deploy.
`OFF_MAIN` has not fired in anger and no receipt has been consumed live. The
first real deploy is the test — treat a surprise there as expected, not as
evidence the rule is wrong.

**Any lane may deploy** once it holds, for the target service:

1. an unexpired `scripts/deploy_claim.py` claim in its own lane name, and
2. a `scripts/deploy_preflight.py` verdict of `CLEAR` less than 15 min old.

`.claude/hooks/deploy-guard.py` enforces both and prints the exact command that
clears each refusal. A `render.yaml` push needs all three services locked —
`blueprint_sync`'s blast radius is all three. Off switch:
`SYNDICATE_DEPLOY_GUARD=off`. Break glass:
`.syndicate/deploy/grants/<session_id>.json` with `expires_epoch`, which any
session may write — it is `--force` with an audit trail, not a permission.

**Why the role ended, stated here because the failure is reusable:** the guard
gated on `session_id in coordinator.id`. When the holder was archived that
predicate had no true value, so the guard's allow-branch became unreachable and
it blocked EVERY session's deploys silently — not a throttle, an outage. The
lock it wrapped was always the better mechanism: `O_CREAT|O_EXCL` with a 45-min
expiry frees itself when its holder dies, which is precisely what the role could
not do.

Process records — sweeps, adjudications, corrections — live in `deploys.md` and
`lanes.md`, not here.

- **Verified by test, not by belief:** `tests/test_deploy_guard.py`, 33 cases,
  both directions — reads of the deploy entrypoint ALLOWED (the old guard blocked
  them, including the edit that fixed it), unlocked deploys BLOCKED, foreign
  claim under the sibling alias BLOCKED, stale `CLEAR` BLOCKED, fresh `HOLD`
  overriding an older `CLEAR` BLOCKED.


## [lane-state-carried] LANE STATE RECORDS CARRIED THROUGH THE 2026-08-18 COLLAPSE — **ARCHIVED 2026-08-19 to `state_archive_2026-08-19.md`, verbatim.**

## [sim-scheduling-deploy-lineage] STALE-TREE DEPLOY LINEAGE — the MECHANISM is real, the SEVERITY I first reported was wrong `[collapsed 2026-08-18 from two 2026-08-17 sections]` — **ARCHIVED 2026-08-19 to `state_archive_2026-08-19.md`, verbatim.**

## [mlb-resim-rules] 2026-08-17 01:3xZ — VERIFIED (sim-scheduling): the real MLB re-sim rules

`_mlb_daily_sim_decision()` (`live_refresh_loop.py`, 230 lines, every tick).
Blocks first: `disabled` / pipeline deferral / `previous_run_still_active` /
`odds_refresh_active` / `insufficient_memory_headroom`. Then, first match wins:
`no_games_scheduled` -> `first_appearance` (own backoff) -> `tip_off_window`
(default 30 min, **once per game**, deliberately falls through) ->
`within_check_interval` (**default 600s, floor 60s**) -> merged
`fingerprint_change` / `join_mismatch` / `board_missing` / `props_now_available`
-> `evening_next_day_sim` (**default OFF**).

**THE 600s INTERVAL IS A FLOOR, NOT A SCHEDULE.** Past it, any input-hash diff
relaunches. Measured triggers 23:03:50 / 23:17:31 / 23:32:20 / 23:44:11 /
23:56:58, all `fingerprint_change`, ~12-14 min apart. Nothing is clock-anchored.

**A `fingerprint_change` launch is SCOPED to changed games and never reaches the
top-props stage** — the function's own comment records `daily_top_props` holding
zero rows for 11+ hours because of it. The trigger that fires most often
regenerates least.

**THE MEMORY GATE NEVER FIRES.** 12 parsed `MLB_SIM_TICK` decisions from 23:00Z:
`insufficient_memory_headroom` **0**, and no decision carries a `memory` payload
— on a service OOM-killed every ~12 min (`#449`). The dominant suppressor is
`intelligence_pipeline_busy`, checked ABOVE the memory gate, so the gate is
usually unreachable. **Unresolved:** unreachable vs miscalibrated. Do not assume
that guard is doing work.

**Deployed:** web `763a2f66`, live-odds-worker `c348da53`, refresh-worker
`4ec66498` (01:23:37Z, another session) — which DESCENDS from my `7623a233` and
retains Phase 1c and the reconciliation guard. The convergence held.

## [sim-scheduling-blocker] 2026-08-17 02:1xZ — VERIFIED (sim-scheduling): the primary goal has ONE blocker — **ARCHIVED 2026-08-19 to `state_archive_2026-08-19.md`, verbatim.**

## [wnba-game-state] WNBA GAME-STATE AND FIXTURE COVERAGE — 2026-08-17 (lane `wnba-live-tier`) — **ARCHIVED 2026-08-19 to `state_archive_2026-08-19.md`, verbatim.**

## [wnba-fixture-identity] WNBA fixture identity + the sweep ownership gap - VERIFIED 2026-08-17 — **ARCHIVED 2026-08-19 to `state_archive_2026-08-19.md`, verbatim.**

## [wnba-sweep-ownership-gate] WNBA SWEEP OWNERSHIP GATE + PHASE 2 AUTORUN `[collapsed 2026-08-18 from three 2026-08-17/18 snapshots; newest reading wins]` — **ARCHIVED 2026-08-19 to `state_archive_2026-08-19.md`, verbatim.**

## [mlb-pitch-mix] MLB CONDITIONAL PITCH MIX — MECHANISM VALIDATED, MARKET SILENT `[2026-08-18]`

- **Engine picks pitches by count bucket and batter hand**, not one season vector.
  `simulate.py` both selection sites; artifact
  `data/conditional_mix/conditional_mix_<season>.json`; Dirichlet shrinkage
  toward (own season mix x league cell tilt), **k fitted out-of-sample**, builder
  REFUSES to write if it loses to either baseline.
- **VALIDATED ON REAL GAMES, no RNG anywhere**: out-of-sample (built through
  06-30, scored on games from 07-01), **395/512 pitchers (77.1%)** beat the
  season vector; log-loss **-6.21%**; within-count TVD median 0.3064 -> 0.2542.
  **Reproducible to the digit.**
- **MARKET: NO DETECTABLE EFFECT.** Two seed pairs at 1920 sims: mean -0.00097
  and +0.00001. **Measured** noise floor 0.00064; effect/floor **0.75**.
  Resolving it needs ~112x the original volume for <=0.0005 Brier. **Not worth
  buying.** Both statements are true — the engine pitches like reality, and the
  price does not notice.
- **THE SWEEPER HAD NO HOME.** `ST` (8.20% of pitches) mapped to `OTHER` or was
  DROPPED in all three code->PitchType maps. **34.5% of pitchers lost a pitch
  type carrying ~23.8 usage points** — often their primary breaking ball. One map
  now: `sim_engine/data/pitch_codes.py`. Appliers merge on collision —
  **probabilities SUM, multipliers AVERAGE by usage.**
- **`GameConfig.crn_pa_seeding` IS BROKEN — DO NOT ENABLE.** Inflates run scoring
  8-35%. Default off, marked in place.
- **The market harness cannot resolve <~0.003 Brier at 120 sims.** Never report a
  single-seed delta from it as a result.

### SOCCER RATINGS ARE A DETERMINISTIC TRANSFORM OF xG — VERIFIED ALL NINE LEAGUES 2026-08-18

- **`attack_rating` and `defense_rating` carry no information beyond `xg_for` /
  `xg_against`.** Measured across every league with history: **|corr| >= 0.98 on both
  sides in all nine, four at exactly +/-1.000**. The not-quite-1.000 values are the
  `_RATING_CAP` clamp biting on outlier teams, not independent signal.
- **CONSEQUENCE, and it generalises beyond the term already removed:** any feature
  derived from goals or xG is ALREADY IN the ratings. `build_possession_priors`
  averages its metrics index with `0.5 + attack_rating`, so such a feature enters
  twice. `94578cbc` removed the two explicit xG terms; **check this before wiring any
  further goal-derived metric into `possession_priors`.**
- **`corr(xg_for, shots_per_match)` is +0.83..+0.93 in all nine leagues.**
  **UPDATE 2026-08-18 ~19:3xZ, SUPERSEDES "not removed" below: shots' weight WAS
  tested (shrunk to `sqrt(1-r^2)`, ~0.0071/0.0097) and the shrink was FALSIFIED by a
  paired test on 126 identical eredivisie fixtures** (t=-2.06, 95% CI
  -0.0191..-0.0005, unshrunk scored better Brier) **and REVERTED — current weight is
  0.016, unchanged from before any of this.** The correlation is real but shots
  carries predictive value beyond it; `sqrt(1-r^2)` wrongly assumed the correlated
  fraction was pure redundancy. The two OTHER terms computed under the same
  heuristic (`form_points`, `clean_sheet_rate`) were never applied — that heuristic
  is now distrusted as a method, not just for this one number. Full detail: lane
  `soccer-model-dispersion`.
- **CAVEAT ON ALL OF THE ABOVE:** measured as the pipeline computes ratings TODAY,
  where `xg_for` IS goals on the football-data path
  (`team_rows_from_match_history`). A real xG source whose values diverge from goals
  would weaken these correlations and could earn the dropped terms back. That is why
  the now-unread `xg_for_per_match` / `xg_against_per_match` keys stay populated.
- **The dispersion overshoot is now CLEANLY DECOMPOSED — 2026-08-18 ~21:1xZ,
  SUPERSEDES "unconfirmed" above.** `possession_priors.py`'s own formulas remain
  exonerated (every per-possession term measurably narrowed after the xG-term
  removal). A full 2x2 isolation (4 configs, 126 real eredivisie fixtures each,
  `backtest_league()` called directly) settled the driver question, and it
  REVERSES the "wiring is the likely driver" guess above — that guess came from
  a CONFOUNDED comparison that never isolated the wiring-absent case:

        config                          xG        wiring   model_brier  stdev
        true baseline (08-15)          n/a        none       0.5211    0.1886
        current formula, no wiring    absent     absent       0.5211    0.1886  <- EXACT match
        old formula, no wiring       present     absent       0.5238    0.2745
        current formula, wiring       absent    present       0.5081    0.2373
        old formula, wiring          present    present       0.5189    0.2945

  **The xG double-count's own effect (+0.057..+0.086) is LARGER than the
  wiring's own effect (+0.020..+0.049) in both held-constant comparisons.**
  `94578cbc` (xG removal, already committed) is HELPFUL, not harmful — it moves
  dispersion TOWARD the true baseline. **The remaining overshoot in the current
  committed state is a real, isolated +0.0487, entirely attributable to
  `00475bce`'s wiring** (Config A's exact baseline match is what makes this
  attribution solid rather than inferred). A pooled (14,246 rows, 9 leagues,
  league-fixed-effects) re-fit of the wiring's own weights found
  `clean_sheet_rate` significant (0.30 -> 0.0902) and IMPROVED dispersion on
  validation (0.2373->0.2307) but WIDENED the Brier gap (0.0017->0.0087,
  t=+1.71, not significant but the closest any "no effect" result got to
  crossing significance tonight) — **DISCARDED, not committed.** Do not re-apply
  0.0902 without a fresh, larger paired validation. Full detail: lane
  `soccer-model-dispersion`.
  The earlier 16-fixture probe (stdev 0.1765) remains SUPERSEDED, unchanged.
- **THREE of the four genuinely-missing input fields are now SOURCED.**
  `possession_share` and `set_piece_goal_share` (`ad174dc0`, 2026-08-19 ~11:0xZ)
  as before. **UPDATE 2026-08-19 ~17:0xZ, SUPERSEDES "remaining unsourced"
  below: `starters_available_share` is now ALSO sourced and wired end-to-end**
  (`d1136447`) — ESPN's post-match boxscore marks each player `starter: True`,
  extracted from the SAME call already made for possession/set-piece, and
  aggregated WALK-FORWARD (a team's core XI as of a match day = the 11 players
  with the most starts across its prior 10 matches). Architecturally different
  from every other field: PER-FIXTURE (this match's own lineup), not a rolling
  team average, so it does NOT flow through `compute_team_ratings` — threaded
  as a direct param exactly like the pre-existing `home_starter_ids`/
  `away_starter_ids` pattern, not the `_mean_of` pattern the others use.
  BACKTEST-HONEST, NOT LIVE-PRODUCTION-READY: uses each match's ACTUAL
  observed lineup, valid for offline validation, but `build_soccer_
  artifacts.py` (the live path) is deliberately NOT wired — a future
  fixture's lineup is not known until near kickoff, which is what the
  separate, already-existing `attach_confirmed_starters` pregame mechanism is
  for. Only `pace_seconds_per_event` remains unsourced.
  **REGRESSION-SIGNIFICANT (pooled, 14,246 rows, 9 leagues, league fixed
  effects): coef +0.143, t=+2.06.** The SAME pooled fit, extended to also
  include `possession_share`/`set_piece_goal_share` jointly (answering
  whether folding them in would flip their earlier kept-despite-non-
  significant decision — it did not: t=+1.65 and t=-1.82, both still not
  significant).
  **UPDATE 2026-08-19 ~17:2xZ, SUPERSEDES "still running" above: THE PAIRED
  BACKTEST LANDED.** eredivisie, 126 matches, 300 sims, vs the possession/
  set-piece baseline: mean Brier delta -0.0049 (favorable direction), SE
  0.0037, t=-1.31, 95% CI [-0.0121, +0.0024] — **not significant**, same gap
  between regression significance and paired-test significance as
  `clean_sheet_rate`, but the OPPOSITE direction (favorable, not
  unfavorable). **Disposition: KEPT**, same as `possession_share`/
  `set_piece_goal_share` (real infra already landed, no known-good default
  abandoned, weak-but-favorable evidence) — not discarded like
  `clean_sheet_rate`. Still BACKTEST-HONEST ONLY per above, not live-wired.
  Regression significance was necessary but not sufficient for
  `clean_sheet_rate` earlier this session (significant in the pooled fit,
  then failed its paired accuracy test, discarded) — the identical caution
  applied here and the outcome differed only in direction, not in rigor.
  **UPDATE 2026-08-19 ~19:0xZ — `pace_seconds_per_event` sourcing ATTEMPTED
  AND FAILED ITS OWN CHEAP FALSIFIER. DO NOT RE-ATTEMPT THE SAME PROXY
  WITHOUT NEW INFORMATION.** ESPN's boxscore carries per-team
  `totalPasses`/`totalShots`/`totalTackles`/`totalCrosses`/`totalLongBalls`/
  `wonCorners`/`foulsCommitted` on the same call already made for
  possession/set-piece/availability — summed across both teams and divided
  into a fixed 5400s, this gives a real, per-match-varying number
  (prototyped on 252 real eredivisie matches: mean 4.88s, range 3.63-10.71s,
  stdev 0.50). **Two problems, either one disqualifying on its own:**
  (1) the raw scale is ~2.8x too fast for `_pace_values`'s assumed neutral
  center (13.5s) — wiring it as-is would clamp `pace_index` to +1.0 for
  nearly every match, which is a degenerate constant, not real variation,
  and `_pace_values`'s own constants (13.5 center, /5.0 scale) were never
  calibrated against real data either, since this field has NEVER been
  populated before now; (2) even before worrying about rescaling, the raw
  proxy shows NO relationship with the most basic plausible outcome —
  pearson(pace, total match goals) = 0.0757, t=1.201 (not significant, need
  ~1.98 at n=252), and pace terciles are flat on mean total goals (fast
  2.905, mid 2.964, slow 2.952 — no monotonic trend at all). Stopped here
  deliberately, before the expensive 9-league fetch + pooled regression +
  paired backtest the other three fields went through — this is the
  identical "cheaper falsifier first" principle this lane already used for
  the Monte-Carlo sim-count check, applied to a sourcing question instead of
  a weight question. **The extraction code was NOT committed** (would be
  unused, unwired infrastructure) — the proxy design, the null result, and
  the exact numbers above are the only thing worth keeping; if someone
  revisits this, a DIFFERENT hypothesis for what pace should predict (not
  total goals) or a fundamentally different "event" unit is needed, not a
  rerun of the same test.
  **UPDATE 2026-08-19 ~19:2xZ — THE BACKTEST WAS RATING 5 OF 9 LEAGUES FROM
  A DIFFERENT PIPELINE THAN PRODUCTION RUNS. FIXED (`3ad5c8a4`).** Found
  while checking whether `ppda` was a misrouted producer (data existing
  somewhere unused) rather than genuinely missing: it was both.
  `data/soccer_source/{epl,la_liga,bundesliga,serie_a,ligue_1}/team_history/
  teams_*.csv` already carry real Understat xG AND real ppda (confirmed:
  `ppda=11.3043` on a live EPL row), and `build_soccer_artifacts.py`
  (production) already reads this directly for exactly these 5 leagues via
  `_GOALS_BASED_RATING_LEAGUES` branch logic (`window=45`) — but
  `backtest_soccer_h2h_calibration.py` had no such branch and rated ALL 9
  leagues via the goals-as-xG fallback (`window=45` uniform, vs production's
  `window=90` for the 4 leagues that fallback is actually meant for). **A
  backtest measuring a different pipeline than production runs is not
  measuring production, however leak-free its methodology.** Killed a
  ~1.5h-in 9-league run on the OLD pipeline rather than trust its number for
  those 5 leagues (user's explicit call). Fixed by mirroring production's
  branch exactly, with a new test asserting the two modules'
  `_GOALS_BASED_RATING_LEAGUES` sets stay equal so this cannot silently
  drift apart again. **Resolves the `ppda` checklist alarm for free** — no
  new external sourcing needed. **Flagged, not fixed:** production's own
  Understat branch does not fold in ESPN possession/set-piece even though
  `espn_match_stats.json` already exists for all 5 of those leagues — a
  real, separate opportunity, out of scope for this fix.
  **UPDATE 2026-08-20 ~06:2xZ, SUPERSEDES "IN FLIGHT" above — THE 9-LEAGUE
  RE-RUN LANDED. THE LANE'S TESTABLE OUTCOME IS NOT MET, AND THE SESSION'S
  CORE HYPOTHESIS IS FALSIFIED BY ITS OWN PRE-REGISTERED TEST.**
  `reports/soccer_backtest/h2h_calibration_2026-08-19_fixed_pipeline_all9_s300_limit120.json`
  (session worktree, not committed). Weighted model Brier 0.5718 vs market
  0.5604 (gap +0.0114, n=1049) — **worse than market in 8 of 9 leagues,
  identically to the 08-15 baseline; belgian_pro_league is again the ONE
  exception, unchanged by an entire session of input-quality work.** Mean
  model stdev(P home) rose from **0.1575 to 0.1922**, PAST market's own
  0.1859 — the model is no longer under-dispersed. **This is exactly the
  outcome the lane's own falsification test (written before any of this
  session's work) was designed to catch: "if the Brier gap does not close
  while stdev rises to market's, under-dispersion is NOT the binding
  constraint." Stdev rose past market's. The gap did not close. Recorded as
  an OVERTURNED belief in `learnings.md`, 2026-08-20.**
  Caveat per the lane's own standing rule ("a gap on a different match set
  proves nothing"): the raw gap number (+0.0139 -> +0.0114) is NOT reported
  as an improvement — n differs (1112 vs 1049; bundesliga scored only 71 of
  an expected ~120) — the dispersion and worse-in-8/9 findings are the
  load-bearing ones, not the raw gap. This does NOT mean the input-quality
  work (xG dedup/possession/set-piece/availability/market_confidence/
  pipeline fix) was wasted — each was decided on its own evidence and those
  decisions stand — it means the SPREAD specifically is not what is holding
  the model back, and the next hypothesis must be about systematic bias in
  the ratings/inputs, not another dispersion knob.
  **`market_features.confidence` sourced, wired (CLI-gated, default OFF),
  and paired-tested — KEPT AS BUILT, not promoted further.** `_market_prior_
  index` has read `model_probability`/`confidence`/`edge` since the engine
  was written; confirmed football's identical engine also never populates
  it (checked directly, not assumed) — a cross-sport gap, not soccer-
  specific. Reuses `_market_probabilities` (the SAME de-vigged closing-odds
  computation this script already uses for the market BENCHMARK) as
  `confidence = max(implied probs)`. Paired test, eredivisie n=126, vs the
  possession/set-piece baseline: mean delta -0.0040 (favorable), t=-0.96 —
  **not significant, and weaker than every other field tested this
  session** (all others had |t| > 1.3). Deliberately left CLI-gated rather
  than unconditionally wired like the other three fields: this is the ONLY
  new input this session where the source data is IDENTICAL to the
  benchmark the lane exists to beat, so any improvement is shrinkage-
  toward-market, not independent skill — a weaker and methodologically
  different case than possession/set-piece/availability's "keep despite
  non-significance" calls.
  **UPDATE 2026-08-20 ~06:3x-13:2xZ — BIAS DECOMPOSITION RUN, HOME-ADVANTAGE
  RE-FIT ATTEMPTED AND DISCARDED AFTER FAILING HELD-OUT VALIDATION.**
  `fit_soccer_probability_calibration.py --per-league` against the fixed-
  pipeline result: global held-out calibration made Brier WORSE (0.5467 ->
  0.5503, fitted temperature 1.1 near-identity) — **confirms discrimination,
  not dispersion, is the remaining defect**, exactly the negative result
  that script's own docstring predicts follows a falsified dispersion
  hypothesis. Per-league AUC gap (model minus market) is genuinely mixed:
  eredivisie +0.044, championship +0.043, primeira_liga +0.012,
  belgian_pro_league +0.010, epl +0.004 (model ranks as well or better) vs
  ligue_1 -0.002, la_liga -0.003, serie_a -0.055, **bundesliga -0.111**
  (model ranks meaningfully worse) — bundesliga and serie_a are where a
  real ranking deficiency lives, not the other 5.
  Traced `home_advantage_attack_boost` (per-league constant,
  `league_profiles.py`) as the mechanism for the 5 shift-candidate leagues
  — a REAL calibrated constant (Phase 10/12/16/17), but calibrated before
  this session's mechanism changes. Bounded grid search (n=25-28, 150
  sims, single-parameter) then widened: eredivisie needs no change (clean
  interior optimum already); epl's "improvement" ran away to an implausible
  NEGATIVE boost with no reversal — discarded as overfitting;
  belgian_pro_league was non-monotonic/noisy — inconclusive;
  primeira_liga was still improving at the edge — direction plausible,
  magnitude unresolved; **championship was the one genuine bracketed
  optimum** (0.055 -> 0.115, peaked at +0.06 then reversed at +0.09).
  **Applied to a worktree and HELD-OUT VALIDATED (old vs new boost, same
  151-match set, scored only on the 125 matches NOT used in the grid
  search) — FAILED: mean Brier delta +0.0121 (worse), t=+1.19.
  REVERTED, NOT COMMITTED.** `league_profiles.py` is unchanged
  (`home_advantage_attack_boost=0.055` for championship, as before).
  **Same pattern as `clean_sheet_rate`: the MOST trustworthy-looking
  in-sample result (a genuine bracket, not an edge artifact) still failed
  held-out.** None of the other 4 leagues' findings should be trusted or
  applied without the same validation — if the best one failed, the
  others (already flagged as artifact/noisy/unbracketed) are less
  trustworthy, not more. **No home-advantage adjustment shipped from this
  session for any league.**

## [live-sha-authority] LIVE SHAs — ASK THE SERVICE, NOT THE LEDGER `[2026-08-18 ~21:2xZ]`

**`GET /api/ops/version` on the running service is the ONLY authority.** It
reports what is executing. Everything else in this file is a record of a deploy
that happened, which is a different question.

- **web = `841b6d84`** ("scoped deploy: NFL preseason projection means +
  provenance"), read from `/api/ops/version`. **NOT an ancestor of `origin/main`.**

**THREE DIFFERENT VALUES WERE IN CIRCULATION FOR WEB TODAY**, and two of them
were wrong in a way that survived review:

    fa1871cf   this file, "DEPLOYED 2026-08-16 TO ALL THREE"   <- TRUE HISTORY,
               but I read a dated deploy record as the current SHA. My error,
               not the ledger's. A deploy record is not a state reading.
    0bf866c3   another lane's note                             <- also not live
    841b6d84   /api/ops/version                                <- ACTUALLY LIVE

I cut a deploy branch off `0bf866c3` on the strength of the second one. **It was
built on the wrong parent and was never pushed** — no harm done, but a deploy
from it would have reverted whatever `841b6d84` carries.

**Render reports web as `branch: main` while running a non-main SHA.** A deploy
triggered without an explicit commit id takes main's tip: measured today,
**1,042 commits / 451 files / +190,277 lines** against the live SHA. Always name
the commit.

**The `/deploys` REST read is blocked by `deploy-guard.py`** — it matches the URL
path, so even `GET .../deploys?limit=2` is refused as "a Render deploy". Use
`/api/ops/version` instead; it is a better source anyway.

### Live web ALREADY carries `clv_openings`

`841b6d84`'s `HOT_ARTIFACT_PATTERNS` contains
`reports/intelligence/clv_openings/*.jsonl`. So the CLV lane's 403 was diagnosed
against an OLDER web, and `deploy/clv-openings-allowlist` may now be redundant
for that pattern. **It does NOT carry the five MLB sim patterns**, which are
still genuinely absent — `conditional_mix` etc. return `count: 0` and `POST
/api/ops/artifacts/publish` still 403s.

## [mlb-sim-artifacts-live] WEB `055dfc67` — THE FIVE MLB SIM ARTIFACTS ARE IN PRODUCTION `[2026-08-18 22:54:51Z]` — **ARCHIVED 2026-08-19 to `state_archive_2026-08-19.md`, verbatim.**

## [web-request-path-latency] WEB'S 502s WERE `/healthz` STARVATION, NOT SLOW COLD BOOTS — FIXED AND MEASURED `[2026-08-22, lane render-web-request-path]`

**COLD BOOT IS NOT A PROBLEM AND NEVER WAS.** Boot-to-listening on web is
**2.7s** (17:12:52.36 `sh -c` -> 17:12:55.09 gunicorn `Listening at` -> 17:12:58.43
first `/healthz` 200). Stop diagnosing boot time.

**THE 502s WERE RESTARTS.** Web was SIGTERM'd every ~90s during live MLB slates
with ~15s of no listener after each. Container `-2mdsk`, booted 17:12:55, **no
deploy after 17:12:59**: terms at 17:14:08 / 17:15:38 / 17:17:38, a NEW gunicorn
master pid each time; health checks unanswered **84s** (17:16:34 -> 17:17:58).
Render 502s carry `responseBytes=223158` — that is Render's own error page and is
how you separate them from app errors. `WORKER TIMEOUT` appeared **zero** times
in three days, so `GUNICORN_TIMEOUT=60` is EXONERATED.

**CAUSE:** `_mlb_feed_live_payload` fell through to statsapi for every game
because `mlb_source/source_artifacts/data/raw/statsapi/feed_live/**` matches
**none of the 175** `HOT_ARTIFACT_PATTERNS`. 15 live HTTPS calls per home request,
uncached, against 8 request slots (`WEB_CONCURRENCY=2` x `GUNICORN_THREADS=4`).

**FIXED — `apply_live_scores` on `games=15`, measured on production:**

    BEFORE  3318 / 7991 / 8400 / 5498 / 3494 / 3802 / 3694 ms
    AFTER   0-93 ms (max 93, 14 samples, two instances, two deploys)

Live scores now come from `live_lens_report_<date>.json` (already allowlisted,
republished ~60s). The residual statsapi path is SINGLE-FLIGHTED: at most one
request thread can ever block on it. Live on web `8149e51d` / `3ada3512`.

**DO NOT ALLOWLIST `raw/statsapi/feed_live`.** It is the obvious fix and it is a
REGRESSION: `_mlb_feed_live_payload` takes the file if it EXISTS with **no
freshness check**, so publishing it freezes every game at capture time — `#413`,
measured 2026-08-13, MIL @ SD reading `live / TOP 9` against a lens reading Final.
It also buys **no speed**: `vendor/mlb_bettingv2/tools/daily_update.py` refreshes
those files **prior-day only** ("must fetch the final game feed, not a stale
pregame cache entry"), so a freshness gate rejects them and falls through anyway.
~3.2 MB x 15 per publish cycle on top.

**`MLB_GAMES_STAGE_MS` settles two WRONG hypotheses** and is the instrument for
any future work here: `per_game_reco_rows` was **0-13ms in every sample** (the
`scope_2026-08-21_home_request_path_compute.md` suspect), and the live-lens
cache-key invalidation its follow-up proposed was not the cost either.

**NOT VERIFIED: the card-cache idle bound.** `_MLB_CARDS_CONTEXT_CACHE` /
`_MLB_TODAY_CACHE` now bound on IDLE time (300s / 120s), targeting a ratchet
measured at 369 MB -> 2,026,717,200 B over ~7.5h against a 2,147,483,600 B
ceiling. Post-deploy readings are directionally better at comparable ages and
**that is not proof**. Peers redeploy web every 20-30 min, so no instance
survives long enough to show it. Instrument: memory-over-uptime, plus the rate
of `CONTEXT_CACHE_EVICTED ... web=True` falling.

**NEXT BOTTLENECK:** `build_cards_page_context`, now dominant at 1803-2402 ms on
a cache miss.

---


## [web-preflight-dead-sample] WEB'S PREFLIGHT SAMPLE HAS BEEN DEAD SINCE 2026-08-14 — CAUSE STILL UNKNOWN AFTER FOUR WRONG ANSWERS `[2026-08-18, collapsed from 2 stacked sections]`

**COLLAPSED 2026-08-18 by lane `ledger-coherence-sweep`, under an explicit
instruction.** This subject had a CORRECTION section and a RETRACTION section
that contradicted each other, which is the stacking this file has been collapsed
for twice. Newest truth wins; the superseded claims are recorded below as VOID
rather than deleted, because two of them are *actionable and wrong* and someone
remembering them would do damage. Full prior text is in git history.

**THE SYMPTOM IS FIXED `[2026-08-19]`. `deploy_preflight.py` is SERVICE-AWARE:**
web's process list is read live from its own `/api/ops/memory`; the workers keep
the `ALL_PROCESS_MEMORY` log path, which works for them. Measured on the first
run after the change — `web CLEAR, sample_source api:/api/ops/memory, age 0.0s,
jobs 0` against `refresh-worker HOLD, log path, age 26s, jobs 7`. **Web no longer
needs a break-glass grant to deploy.** The fix does NOT depend on the cause, and
that was deliberate: four causes had been claimed and all four were wrong, so
anything resting on a fifth guess would have been the fifth mistake. Falsified in
the blocking direction too — a job on web yields HOLD, and an unreachable
endpoint falls back to the log path and yields UNKNOWN, never CLEAR.

**THE MECHANISM IS NOW FOUND AND VERIFIED `[2026-08-19]` — and it is NOT a fifth
guess, because it is read off the code and the live config rather than inferred
from the symptom.** Web has exactly one path to the emitter, and it is gated off:

    syndicate/app.py  _start_background_loops()
      render_web_dyno = _is_render_web_dyno()
      if render_web_dyno and not _env_bool(
              "SYNDICATE_ENABLE_INTELLIGENCE_STATE_BACKGROUND_LOOP", default=False):
          return                     <-- web returns HERE
      start_intelligence_state_background_loop(app)   <- the 12 emitter call sites
      if not render_web_dyno:
          start_live_refresh_background_loop()        <- also skipped on web

- **Live web env: `SYNDICATE_ENABLE_INTELLIGENCE_STATE_BACKGROUND_LOOP = false`.**
  `render.yaml` sets it `"false"` for web and `"true"` for the worker.
- **No other caller exists on web.** `syndicate/blueprints/**` has ZERO
  references to either emitter function, so no request path can produce one —
  which is why hitting `/api/ops/memory` repeatedly tonight emitted nothing.
- **Confirmed empirically, not just by reading:** web has REBOOTED many times
  since (newest gunicorn boot 2026-08-19T00:48:07Z) and has still never emitted.
  A restart cannot fix a loop that is configured not to start.

**WHAT IS STILL NOT PROVEN: which change on ~2026-08-13/14 flipped it.** The gate
dates from 2026-07-04 and the blueprint's `false` from 2026-07-25, both well
before the last emission at 2026-08-14T18:55:39Z — so for those three weeks the
SERVICE-level env must have carried a `true` that drifted from the blueprint.
**The leading candidate is the FIVE `render.yaml` pushes on 2026-08-13**, each of
which fires `blueprint_sync`, and a sync rewrites the service's WHOLE env block
from the blueprint — overwriting exactly that kind of manual `true`. **This is
NOT confirmed:** Render exposes no history of env-var values, so the pre-08-13
service value is unrecoverable. Candidate, not finding.

**THE SYMPTOM AS IT WAS, for anyone reading an older receipt:**
`deploy_preflight.py` returned `UNKNOWN` for web — "sample is 356656s old (limit
180s)", 4.1 days and only ageing. The guard requires a CLEAR within 15 min, so
web's preflight was permanently unsatisfiable and every web deploy needed a
break-glass grant. A
guard that must be broken on every use has stopped being a guard. Tracked as
`todo.md` `#465`.

### WHAT IS ESTABLISHED — and it is only this

- **The emitter EXISTS and prints when called.** `memory_observability.py:1944
  def log_all_process_memory` → `:1952 print(f"ALL_PROCESS_MEMORY ...")`.
- **`origin/main`'s copy is BYTE-IDENTICAL to the 420-commit-old live worker
  `00e9a49f`** — 124,684 bytes both sides, 1 emitter definition, 1 emitter print
  each. Measured 2026-08-18.
- **refresh-worker emits every ~17s. Web has not emitted since 2026-08-14.**
- **Web HAS a reachable call path** (see the falsified trace below), so "web
  never had a caller" is not consistent with the evidence.

### FOUR CAUSES CLAIMED FOR ONE SYMPTOM. ALL FOUR ARE WRONG.

    1. "the sampler is broken"        NO
    2. "psutil is not installed"      NO -- real, but incidental. procfs
                                      enumerates 4/4 processes and
                                      /api/ops/memory returns full process data.
    3. "the emitter was deleted"      NO -- intact at :1952, byte-identical to
                                      the live worker's copy.
    4. "web has no caller"            NO -- app.py:37 starts one.

    ACTUAL CAUSE                      **UNKNOWN. DO NOT ADD A FIFTH GUESS.**

**Acting on cause 2 would have shipped a `psutil` dependency that fixed nothing
and looked exactly like a fix.** That is the pattern to watch here: every one of
these four was plausible, and three were argued from real evidence.

### THE TRACE THAT CLAIMED "NO CALLER ON WEB" IS FALSIFIED

It enumerated **two** caller families — `live_lens_loop` (started only by
`run_live_odds_refresh_worker.py:30`) and `refresh_odds_sources.py` (a worker
script) — and concluded both were worker-only, therefore web has no caller.
**It missed a third family, while quoting it.** Its own evidence block reads
`syndicate/app.py:36-37 starts live_refresh_loop + intelligence_state`, and:

    syndicate/app.py:37        start_intelligence_state_background_loop
     -> pipeline/intelligence_state.py  _diag_log_all_process_memory  (12 sites)
       -> memory_observability.py:1919  log_and_persist_process_memory
         -> :1944 log_all_process_memory  ->  :1952 the print

**Web starts a loop that reaches the emitter.** The claim read as true because
`syndicate/app.py`, `wsgi.py` and `syndicate/blueprints/` contain ZERO
occurrences of the callee — literally true, and materially misleading, because
`app.py` does not call it, it *starts something that does*. Grepping for the
callee and never asking what starts the caller is a reachability error.

**So the question is NOT "does a caller exist" but "why does the caller that
exists not emit".** Candidates, none tested: the loop is gated off on web by
env; it returns before reaching those 12 sites; or it is not actually running.

**HOW CAUSE 3 WAS REACHED, kept because the mechanism recurs:**
`git grep -l 'ALL_PROCESS_MEMORY' origin/main -- '*.py'` piped through `head -4`
returned four `scripts/` paths, and **a TRUNCATED list was read as an EXHAUSTIVE
one** — `memory_observability.py` was simply below the cut. Same family as cause
4's error: both concluded absence from a search that was never asked to be
complete.

### THE SUPERSEDED CORRECTION'S TWO ACTIONABLE CLAIMS ARE VOID

Recorded explicitly because both are alarming, specific, and would waste real
work:

- **VOID — "refresh-worker's CLEAR preflight is an ARTEFACT OF STALENESS. The
  moment the worker is brought onto main its preflight goes UNKNOWN too and NO
  service can gate a deploy."** This derived from the emitter being absent on
  main. It is present, and the file is byte-identical across those 420 commits,
  so modernising the worker changes nothing about its emitter. **Do not let this
  warning deter a worker update.**
- **VOID — "THE ACTUAL FIX: restore the emitter."** There is nothing to restore.

### THE LEAD, AND THE FIX THAT SURVIVES REGARDLESS OF CAUSE

**Look at loop ownership first: it moves between services via env flags with NO
DIFF** (`_mlb_refresh_tick_owner_here` and friends) — already a recorded trap in
this file. A loop web still starts can be gated off inside it, which would look
exactly like this.

**The fix does not depend on the cause and should be taken now: make preflight
SERVICE-AWARE — have `deploy_preflight.py` read `/api/ops/memory` for web**
instead of scraping logs for `ALL_PROCESS_MEMORY`. That endpoint already returns
a fresh, complete enumeration on live web (measured: 4 processes, all infra,
zero jobs), and it is **already what every web break-glass does by hand**. It is
also better matched to the real risk — a web deploy has no long job to land on.

**Rejected alternative: give web its own periodic emitter.** That is request-path
periodic work, which the worker-split rule exists to prevent and which `#241`
already turned into a production restart loop (~1.4GB headroom).

**DO NOT ACT ON A CAUSE FROM THIS SECTION.** Act on the fix, which is
cause-independent.

## [refresh-worker-deploy-hold] refresh-worker: THE OOM DEPLOY HOLD IS ORPHANED. Branch READY, NOT DEPLOYED. `[2026-08-18]` — **ARCHIVED 2026-08-19 to `state_archive_2026-08-19.md`, verbatim.**

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

## [lane-guard-disclaimer-and-worktree-exemption-bugs] TWO REAL BUGS FOUND IN `lane-guard.py`, NEITHER FIXED `[found 2026-08-18]` — **ARCHIVED 2026-08-19 to `state_archive_2026-08-19.md`, verbatim.**

## [football-model-leaks] FOOTBALL — TWO MODEL LEAKS, BOTH FIXED `[verified 2026-08-19, lane football-model-owner]`

**The football feature payload was LEAKED.** `build_nflverse_game_metrics`
computes EPA/success-rate/pass-rate from **the game being predicted** —
`_match_game_rows` filters pbp to that one matchup+week. Measured over 285 games
of 2023: **r = 0.988** against the final margin. Replacement
`syndicate/features/football/features/asof_team_form.py` certifies at **r = 0.235**
via an in-module assertion, not just a test.

**NCAAF ratings were LEAKED for backtests.** `/ppa/teams?year=S` is
season-aggregate. Measured over 558 games of 2024: full-season **r = 0.663** vs
as-of **0.509** — 30% inflation. Fixed to aggregate `/ppa/games` over weeks < N.
**`/ppa/teams` ACCEPTS `week=N` AND IGNORES IT** (identical rows and values), so
the obvious fix is a silent no-op. **`seasonType=regular` is load-bearing**: without
it `/ppa/games?week=1` returns the College Football Playoff, importing January
games into a week-8 rating — worse than the leak it replaced. **The 2026 opener is
UNAFFECTED** (no in-season history → 2025 prior-season fallback, verified).

**A population checklist CANNOT detect leakage.** A leaked field is 100%
populated by construction and passes every check this repo has — the input
checklist marked these FED, reachability passed, unit tests passed.

## [football-board-defects] FOOTBALL BOARDS — THREE DEFECTS SHIPPED AND MEASURED `[2026-08-18/19]` — **ARCHIVED 2026-08-19 to `state_archive_2026-08-19.md`, verbatim.**

## [football-engine-levers] FOOTBALL ENGINE — THE PAYLOAD IS THE WEAK LEVER `[measured 2026-08-19]`

**`feature_generation_payload` moves margin 0.553 pts; the RATINGS path moves it
2.322 — 4.2x, or 17.2% vs 4.1% of the 13.5-pt margin SD.** `build_drive_priors`
builds ONE game-level profile (never reads `away_*_rating`); per-team
differentiation is in `play_simulator.py:258-259`, on the ratings path.
**All three generate scripts ALREADY pass ratings, and NFL's are already as-of**
(`_mean_epa(..., before_week=week)`). The unwired payload was real and is the
wrong lever.

**AND THE PAYLOAD IS A MEASURED NULL** `[Phase 3, n=269, 2023, 300 seeds]`:
`dCRPS +0.0226 (0.97 SE)`, `dMAE +0.0256 (0.88 SE)` — nominally worse, under 1 SE
both ways. **It does not ship, and Phase 4 is moot.** An intervention worth 4.1%
of the outcome's spread cannot produce a detectable accuracy change even if
directionally perfect. **Anyone revisiting this should test the RATINGS path, not
the payload** — `asof_team_form.py` is built and certified for exactly that.

**Engine baselines do not match real NFL distributions** — `success_rate` assumed
0.500 vs a league mean of 0.422, `explosive_play_rate` 0.100 vs 0.066. Raw values
put league-mean `offense_index` at 0.405 vs a neutral 0.500 and suppressed every
game's total by ~2.6 pts. Re-centring on the **as-of** league mean restores 0.500.

### CONFIRMED — the emitter trace, and `psutil` was never the cause `[2026-08-19]`

**Upgrades the PROVISIONAL trace above to CONFIRMED, on direct evidence rather
than inference.** Two lines from the SAME tick of the SAME process on
refresh-worker, read from the Render logs API 2026-08-19T01:50:41:

    PROCESS_ENUM_DEBUG {"error_count": 1, "errors": ["psutil_unavailable:ImportError"], ...}
    ALL_PROCESS_MEMORY {"accounted_rss_mb": 1312.168, "container_memory_headroom_mb": 1811.645, ...}

**The worker emits `ALL_PROCESS_MEMORY` WHILE psutil is unavailable.** It falls
back to procfs and enumerates fine. So:

- **`psutil` is DEFINITIVELY not the cause** of web's dead preflight. The
  retraction filed earlier was right, and this is now measured rather than
  argued. **Installing it would have changed nothing.**
- **The caller trace is CONFIRMED.** The emitting line arrives from
  `live_lens_loop` — `start_live_lens_loop` is imported by
  `run_live_odds_refresh_worker.py` and by nothing else, and `app.py` starts the
  live-refresh and intelligence-state loops but NOT live-lens. **Web has no
  caller. It is not broken; it was never wired.**
- Therefore **`deploy_preflight.py` gates every service on a WORKER-ONLY
  signal**, and web's preflight has never been satisfiable. Tonight's
  break-glass was not an exception to a working gate — it was the only path web
  has ever had.
- **The fix is to make preflight service-aware**, NOT to add periodic work to a
  web process. A web deploy has no long job to land on: measured tonight, 4
  processes, all infrastructure, zero jobs.

**FOUR causes were proposed for this symptom and three were refuted** (broken
sampler / missing psutil / deleted emitter). This is the fourth and the only one
with direct evidence. **Instrument check that made it trustworthy:** the Render
logs `text=` filter was verified to work first — four strings visible in the
unfiltered feed each returned rows — so a null result from it is now evidence of
absence rather than of a broken query. **Earlier tonight I reported nulls from a
query I had never proven could return non-null.**

## [basketball-smart-sim-engine] NBA/WNBA smart-sim: allowlist, dead-gate fix, and an open staleness question — 2026-08-18 (lane `basketball-model-owner`)

**Code facts, verified by reading + reachability test, true regardless of
current deploy state — do not restate as a live-SHA claim, ASK THE SERVICE
per `[live-sha-authority]` above for what's actually running:**

- `syndicate/features/shared/artifact_publisher.py`'s `HOT_ARTIFACT_PATTERNS`
  includes `team_advanced_stats_*.csv` and the four optional per-game
  calibration JSONs (`smart_sim_total_calibration.json`,
  `intervals_band_calibration.json`, `intervals_time_profile.json`,
  `player_stat_calibration.json`), both directory-nesting variants. Was
  previously unallowlisted (only the final `smart_sim_*.json` OUTPUT was).
- `_apply_player_priors_local` (`basketball_props_smart_sim.py:~3277-3306`)
  used to nest FOUR split mechanisms — opponent-specific, career-vs-opponent,
  venue, and opponent-position-matchup — behind one `player_logs is not
  None` gate. Three genuinely need `player_logs.csv`, absent from BOTH
  leagues' production data roots (platform-wide, not WNBA-specific) and
  correctly still dead. The FOURTH (position-matchup) is sourced from a
  DIFFERENT, successfully-populated table (`pos_lookup`, 47 WNBA / 64 NBA
  real rows measured) and was wrongly coupled to the same gate — fixed,
  reachability-measured 0->111 calls off/on.
- `vendor/{wnba,nba}_betting_repo/src/*/cli.py`'s `_ensure_team_advanced_stats_asof`
  had a cache-freshness bug: a non-zero-size check alone treated a
  stale-schema file as fresh forever, blocking rebuild. Fixed.
- Team-advanced-stats and player-priors are CONFIRMED to genuinely drive the
  WNBA smart-sim's output (not just populate a field) — real ablation, 3
  seeds, neutralizing team-advanced-stats moved simulated win probability
  ~45-50 points every time.

**Staleness gap RESOLVED 2026-08-19 — and the answer is worse than the
question: `#461`'s deployed fix has ZERO reach into production right now,
even though the code fix itself is correct.** A real WNBA schedule gap was
RULED OUT with data (`schedule_2026.csv`: games run daily 07-15..08-19, only
routine single-day breaks). The original staleness check had also queried
the WRONG tree — `WNBA_BETTING_DATA_ROOT` resolves to the FLAT
`wnba_source/data/processed/` on all three services (`render.yaml:176,551,1000`),
not the nested `source_artifacts/` copy the check used
(`artifact_publisher.py:158-161` already documents this exact split for
WNBA). Querying the right tree: newest as-of file is `asof_20260723` (still
~27 days stale), and the season file is 3,243 bytes — NOT 0 — but still the
OLD 12-column schema (no `games`/`source`), live right now.

**Root cause: `_ensure_team_advanced_stats_asof` (the function `#461`
fixed) is UNREACHABLE from production's real pipeline.** Production's
actual path is `refresh_wnba_oddsapi_props.py` ->
`basketball_props_smart_sim.py`, which `importlib.import_module`s
`wnba_betting.sim.smart_sim` DIRECTLY, in-process — never subprocessing
into `wnba_betting.cli`, where `_ensure_team_advanced_stats_asof` lives.
The CLI code path that WOULD call it (`predict-props`) is built by
`_predict_props_cli_args()` (`refresh_wnba_oddsapi_props.py:4144`), which is
**never called anywhere in the file** — dead code. `smart_sim.py`'s own
reader (`_load_team_advanced_stats_asof`, `:546-570`) does an exact-date
filename match and, on a miss, falls straight to the stale season file —
it never rebuilds, never calls the fixed function at all. **"Presence is
not reachability" — same shape this repo has hit before.** `db573857`
being live changes nothing observable until either the vendor CLI is
invoked directly against Render, or `basketball_props_smart_sim.py` is
wired to call an equivalent builder itself.

**`#468` reachability fix IS NOW LIVE AND DEPLOYED, updated 2026-08-19**:
wiring shipped and deployed to BOTH refresh-worker (`f13ea05e`) and
live-odds-worker (`e1d1bcf4`/`0c7962a7` lineage) — confirmed working
end-to-end on a REAL production sim call (not just isolated test): a
genuine `smart_sim_2026-08-19_WSH_TOR.json` run rebuilt 3 fresh
`team_advanced_stats_2026_asof_*` files where one stale file existed
before, mtime jumped clean off the pre-fix frozen baseline. Measurement:
`.syndicate/deploys.md`, "`#468` + `#469` — EFFECT CONFIRMED" entry.

**Boxscore capture (was: "no caller exists anywhere" — that specific claim
was WRONG, corrected 2026-08-19).** A parallel, Syndicate-owned, ESPN-based
mechanism (`_ensure_player_logs_for_props_refresh` ->
`_bootstrap_local_boxscores_history_for_props` ->
`bootstrap_boxscores_history_local`) IS reachable from `main()` and runs on
every refresh tick — the "no caller" finding was true only of the vendor
CLI's own functions. Real root cause (`#469`, filed and fixed): the
bootstrap checked cumulative `history_rows` instead of the pull's own new
`rows`, so a fetch adding zero rows still reported success — silently, for
weeks. Root-caused further: ESPN's site API likely soft-blocks a
datacenter-shaped User-Agent from Render's egress IP. Fixed (silent-success
detection + browser UA) and deployed to both services (`0c7962a7`
live-odds-worker, `23e70a80` cherry-picked onto refresh-worker's live SHA
`6631748c` since that SHA is off-`main`, on `deploy/469-pt3-refresh-worker`).

**A SECOND, deeper bug (`#469` pt3) then masked the first fix**:
`_player_logs_ready` treated the bootstrap's OWN mtime-refreshing stalled
write as "ready" for a full 12h window, so the diagnostic code (and the
retry) almost never actually ran. Fixed: mtime-freshness now only governs
the genuine `player_logs.parquet`/`.csv` artifacts; the boxscore fallback
path is gated purely on content-date staleness plus a dedicated 30-minute
attempt-backoff marker (mirrors this file's own `_predict_date_*` pattern).

**A THIRD bug (`#472`) explained why even THAT fix's effect stayed
unobserved for 5+ hours, and IS NOW DEPLOYED AND CONFIRMED WORKING**:
`_launch_autorun_wnba_pregame_refresh` (and its identical twin,
`_launch_autorun_soccer_pregame_refresh`) wrote a fresh, full-interval-
resetting epoch on EVERY launch failure, including plain mutex contention
from `launch_refresh_run`'s "already active" check — so one lost race
against another job (confirmed: a legitimately in-flight MLB resim chain)
cost the FULL 4h cadence instead of a short retry. Fixed (`97e85b66`), live
on live-odds-worker `2026-08-19T19:37:20Z`. Confirmed working: WNBA's
pregame autorun launched successfully `20:00:46Z`, ~23 minutes post-deploy
— versus the 5+ hour drought measured pre-fix.

**`#469`'s ESPN fix is CONFIRMED WORKING END-TO-END, updated 2026-08-19**
— the datacenter-IP soft-block hypothesis was correct and the browser-UA
fix resolves it. A manually-triggered real refresh (fired via
`/api/ops/odds-refresh/run` rather than wait ~4h for the next natural
`#472`-gated cycle) produced `boxscores_2026-08-18.csv` — a genuinely new
per-slate file, 101 real ESPN rows, verified content (real player names,
real stats, `source=espn`). `boxscores_history.csv`'s own max game date
advanced **2026-06-30 → 2026-08-18** in that same run, measured by direct
CSV content pull. Full chain (`#461`/`#462`/`#464`/`#467`/`#468`/`#469`/
`#472`) is closed with real production confirmation, not just code-
correct-in-isolation. Measurement: `.syndicate/deploys.md` "CONFIRMED
WORKING end-to-end" entry.

Two ops-tooling visibility gaps found and fixed while chasing this:
`launch_refresh_run`'s autorun-launched children run with `stdout=DEVNULL`
by design, so `print()` diagnostics (including `#469`'s own
`BOXSCORE_BOOTSTRAP_STALLED` marker) never reach Render's log collector for
those specific runs — the script's own `_append_log` file
(`<source_root>/logs/syndicate_refresh_oddsapi_props_<date>.log`) was the
only surviving signal and was never in `HOT_ARTIFACT_PATTERNS` either
(fixed, `b35dcfa0`/`450e0d6e`). Separately confirmed (a structural fact,
not a bug): `reports/migration_runs/**` stdout/stderr wrapper files are NOT
cross-service visible at all — they live on whichever service ran the job,
web's disk is genuinely separate.

**`#473`, checked 2026-08-19: NBA does NOT have this defect — it has a
different, deeper one.** Structural reachability is symmetric with WNBA,
confirmed by trace (`refresh_nba_oddsapi_props.py` reaches the same
monkeypatched `_load_team_advanced_stats_asof_local`, no NBA-specific
divergence, no env-var override). But a real reachability test (same
methodology that verified `#468` for WNBA — real historical NBA data in a
scratch copy, not just code-reading) found NBA's rebuild returns nothing:
both fallback data sources are structurally absent — `compute_team_
advanced_stats_from_boxscores` expects a `processed/boxscores/`
subdirectory + `raw/games_nba_api.csv` that don't exist anywhere in NBA's
actual data layout (Syndicate maintains flat `boxscores_2026-*.csv` files
instead, the WNBA convention, which this vendor function never reads);
the fallback needs `player_logs.csv`, also absent. NOT FIXED — genuinely
separate, scoped work, zero current production impact since NBA is
offseason (Oct–June window) with no dedicated autorun even attempting
this path. Full writeup: `.syndicate/deploys.md` `#473` entry.

**`#478`, root-caused 2026-08-20 — the WNBA sim published NBA segment
geometry, and the cause was OURS.** The engine computes `seg_seconds` from
`LEAGUE.regulation_period_seconds` CORRECTLY (600/4 = 150 for WNBA; verified
the live SHA's `league.py` sets 600 and `LEAGUE` is a module constant). Then
`smart_sim.py:4174-4176` OVERRIDES its own correct value with whatever
`segment_seconds` the per-sim box dict reports — and Syndicate's own fallback
(`_local_simulate_pbp_game_boxscore`) hardcoded 180 with 12 minute-buckets for
either league. A WNBA sim therefore published 4x180s = 720s of segments over a
600s quarter. Measured against 89 paired production games: predicted segment-4
share 0.183 vs actual 0.120 (52% over-prediction) while the whole-game total
stayed correct — a pure SHAPE error. Fixed by deriving geometry from the
league (`_local_boxscore_geometry`) and threading `league_code` into the
fallback, which was being dropped. **My filed hypothesis (a missing/zero
vendored league value) was WRONG** — checked, not assumed.

**`#481`, measured 2026-08-20 — the WNBA live win-probability path was
severely underconfident, and had never been backtested.** Graded by replaying
cached ESPN play-by-play through the REAL shipped function over 212 games /
73,878 live samples: Brier **0.1896 -> 0.1644 (-13.3%)**, worst calibration gap
**-0.240 -> -0.054**, held-out test 0.1922 -> 0.1661 on a GAME-LEVEL split.
The failure was DISPERSION, not bias — aggregate means were already unbiased
(0.573 pred vs 0.571 actual), which is why it survived; samples priced 0.6-0.7
actually won 91.3%. Scale `6.0 + 0.35*min_left` replaced by a single
`_WNBA_LIVE_MARGIN_SCALE = 2.1` (the fitted time coefficient is 0.00 because
the pregame blend already carries time dependence). Applied to cover too, NOT
to totals (different quantity, unfitted). LIVE on web `ba1d3368`.

**SERVED-PAYLOAD CONFIRMATION DISCHARGED `[2026-08-20 19:2x CT / 00:2xZ]`.**
Checked on IND@DAL while in progress: both the moneyline and cover paths
reproduce the served value EXACTLY (gap `0.00e+00`) from a single fetch, at
P1 4:55, margin -4, elapsed 5.083min — served `modelHomeWinProb` 0.4092787472,
served `p_cover` 0.5273877166. Three samples over ~8 min, all exact;
`markets.moneyline.p_win` agrees with the lane's own `modelHomeWinProb` to
1e-6, so the verified number is the number the board shows. **This proves the
deployed formula is what serves — it does NOT re-measure the -13.3% Brier,
which still rests on the offline replay above.**
**Read any live delta with its blend weight.** `blend_w = elapsed/40`, so
5 minutes in the live term carries 0.13 of its eventual weight and the -0.04
vs the old constant is the SMALLEST the change ever gets (observed growing:
-0.0396 at w=0.114 -> -0.0581 at w=0.185). Late-game magnitude — margin +10,
1:00 left, 0.9780 new vs 0.8190 old, +0.159 — is COMPUTED from the deployed
function, not served.

**WNBA does not re-sim live; MLB does `[2026-08-20]`.** 0 basketball matches
for `resim` in `live_refresh_loop.py`; MLB has `mlb_needs_resim_game_pks()` +
`fingerprint_change`. WNBA applies analytic transforms to a PREGAME sim, so
the transform's quality IS the live model quality. Live re-sim cost measured
on the real engine at production settings: **4.90s / 5.9 MB per game** —
compute is not the blocker. The refresh mutex is **per-service and already
enabled** (`SYNDICATE_REFRESH_RUN_PER_SERVICE_LANES: "true"`, distinct lanes),
so soccer/WNBA contention is a PLACEMENT problem, not architecture. The real
constraint is DATA: WNBA `live_state` carries only score/clock/period — no
live player state — so a re-sim would re-run pregame projections from a new
score and add little for game lines and nothing for props.

**CORRECTION `[2026-08-21, measured]`: "nothing for props" IS WRONG, and the
sentence above misled a later session into saying live WNBA props were
impossible three times.** It describes `live_state`, which does carry only
score/clock/period. It does NOT describe what the platform can see.
`/wnba/api/live_player_boxscore?date=...` serves LIVE PER-PLAYER LINES today —
minutes, points, rebounds, assists, threes; 17 and 18 players across two live
games, read from production 2026-08-21 02:40Z.
`cards.py::_public_live_player_boxscore_payload` has been fetching ESPN's
summary endpoint all along. The gap is not ingestion, it is PERSISTENCE: that
fetch runs in the REQUEST PATH on web (`warn_if_compute_in_request_path`) while
the prop join runs in the board build on a worker, so there is no artifact to
read. Live props need: persist -> project (current stat + remainder off
minutes/pace) -> carry `liveModelProbOver` per `(player, market, line)` on the
lens -> open the `sport != "mlb"` gate in `attach_live_projections_for_sport`.
Pricing an edge off it still needs a MEASURED interval, which does not exist yet.

**ALL 4 PHASES BUILT, WIRED AND DEPLOYED `[2026-08-21]` — `a41f88f8` on
live-odds-worker (capture tick) and refresh-worker (board build + prop gate).
THE WIRING IS REACHABLE AND THE REFUSAL FIRES: first lens tick after landing,
`WNBA_LIVE_BOX_EMPTY date=2026-08-21 games=3 players=0 -- nothing written`.
**PRICING IS UNPROVEN — `players=0` means props have never seen a real player;
`livePropsCoverage` never populated, `rows_live_projected` never non-zero. DO
NOT report live WNBA props as working.** The projection's error IS measured
(n=796, 5 slates, replay reconciling 100%): residual sd 6.03 -> 2.70 as the
clock runs down, `p90/sd` 1.56-1.71 vs 1.6449 normal.
**WHICH SERVICE RUNS THE WNBA LENS: live-odds-worker**, not refresh-worker —
`TICK_COMPLETE skipped=['mlb','nba','wnba','soccer']` there. The docstring in
`wnba/live_lens.py` says otherwise and is WRONG; ownership is env-driven.
Superseded note follows.

**PHASES 1-3(a) ARE BUILT AND ON `main`, NONE WIRED, NONE DEPLOYED
`[2026-08-21, superseded same day]`.** `capture_wnba_live_player_box.py` (persist),
`wnba_live_prop_projection.py` (project), `wnba_live_prop_rows.py` (join to
anchor). 33 tests + 20 subtests. **The chain has NEVER run end to end in
production** — nothing calls the capture on a tick, so the artifact has never
existed on a worker.

**THE PREGAME ANCHOR IS `cards_sim_detail_<date>.json`, and it carries more than
a mean.** `games[].sim.players.{home,away}[]` →  `min_mean` (expected minutes),
`{pts,reb,ast,threes,pra}_mean/_sd/_q`, and `prop_ladders[stat]` with
`simCount: 100`, a full distribution histogram and a `{total, hitProb}` ladder.
Measured: Paige Bueckers `min_mean 38.37, pts_mean 23.39, pts_sd 7.33`.
**`props_predictions_*.csv` and `props_edges_*.csv` return 403 from WEB — that is
a ROUTE restriction, not absence.** The lens builder runs on a worker and reads
them directly; do not conclude a file is unreachable from an export 403.

**THE LIVE PROP PROBABILITY IS THE ONE THING STILL MISSING, deliberately.**
`build_live_prop_index` keys on `liveModelProbOver`; nothing built so far emits
one, so the `sport != "mlb"` gate stays shut BY DESIGN. The ladder above is the
PREGAME distribution (`P(final >= line)` from tip-off); a live prop needs
`P(final >= line | current, minutes played)` — the REMAINDER's distribution over
the minutes left. Scaling the full-game shape (mean by `m/min_mean`, sd by
`sqrt(m/min_mean)`) is standard and UNMEASURED HERE. Grade it and
`prob_std_err(p, simCount)` applies honestly at n=100.

**NO GAME-LEVEL TOTAL DISTRIBUTION EXISTS in the sim `[2026-08-21, checked]`** —
`sim.quarters` is `[]`, `sim.players_summary` is bare counts. So the per-player
ladders do NOT unblock live totals; that still needs the OddsAPI historical
backfill and a grade.

**WNBA LIVE GAME-LINE PRICING, state as of `[2026-08-21 03:2xZ]`.** Every gate
is individually cleared and the end-to-end reading is STILL OWED:
- capture cadence 3,676s -> **261s** (live-tick reuse bound, `d68f343a`)
- analytic interval applied: rows carry `prob_std_err 0.054`,
  `std_err_basis analytic_calibration`; `sim_count_unusable` gone board-wide
- spreads price at their own line; totals refuse as
  `analytic_estimator_never_backtested_for_this_market`
- h2h now stamps `market_fair_prob_over` (`a5e0b462`)
- **`rows_live_gameline_priceable` has NEVER been observed above 0.** Do not
  report this chain as working until that reading exists.

**READ THE LENS WITH THE INSTRUMENT, NOT BY INFERENCE `[2026-08-21]`.**
`GET /api/ops/live-lens/snapshot-index?sport=wnba` reads the snapshot through
the same keyvalue-aware reader the join uses and reports the join's verdict per
game. Nothing else can: `/api/ops/artifacts/export` is a DISK read and the
snapshot is keyvalue-routed (returns empty), and `/wnba/api/live-lens` may
rebuild from a published artifact rather than return stored bytes. Four
hypotheses about that pipeline were eliminated by measuring adjacent things and
ALL FOUR WERE WRONG. `PULL_LIVE_LENS_SNAPSHOT ok=True written=0` is EXPECTED
output for a keyvalue path, not a failure.

**Historical WNBA market totals: retained data has none, OddsAPI does
`[2026-08-21, measured]`.** `book_quotes` for `2026-08-19/17/14/10` are ABSENT
via export while today's returns 14.8MB (date-tokened keyvalue paths carry a
TTL); the local mirror has 0 files. So `#481` was right that refitting totals
needs historical lines — but its "unavailable here" is WRONG.
`scripts/backfill_mlb_historical_odds.py` already pulls OddsAPI's historical
endpoints (`/v4/historical/.../events` 1 credit, `/odds` 10 credits per
market-region) and the same exist for `basketball_wnba`. Totals is therefore
"refused until graded", not "refused forever".

**Unmeasured**: whether the ESPN fetch keeps succeeding on future natural
cycles (one verified data point exists, the pattern isn't established
yet).
Full write-up: `docs/ai_context/basketball_sim_engine_reference.md`,
`.syndicate/log/2026-08-19.md`, `.syndicate/log/2026-08-20.md`.

## [mlb-sim-log-unreachable] RETRACTED — THE SIM LOG *IS* REACHABLE REMOTELY `[2026-08-19]`

**THIS ENTIRE FINDING IS WRONG AND IS RETRACTED.** The body is kept below only so
the mistake is legible; **do not act on it.**

**The mechanism already exists and is purpose-built.**
`live_refresh_loop.py:2516-2536` copies the child's log into the shared
Redis-backed state store the moment the process exits, with a comment saying
exactly why: *"so `/api/ops/live-refresh/state?sim_date=&sim_run=` can surface it
remotely."*

**Verified by using it:**

    GET /api/ops/live-refresh/state?sim_date=2026-08-19&sim_run=20260819_134839
      state.sim_run_status      -> the full command line
      state.sim_run_resolution  -> date, run_stamp, source
      state.sim_run_log_tail    -> 8000 chars, ending:
        MLB_DAILY_SIM_END date=2026-08-19 return_code=0 ok=True published_artifacts=93

**The sim SUCCEEDED.** Everything the retracted finding said was invisible is one
authenticated GET away.

**HOW I GOT IT WRONG — the fourth instance of one habit in this sequence.** I
checked ONE channel (Render's log API), found nothing, and reported *the system*
as having nothing. I never asked whether a purpose-built path existed — and the
answer was in a comment beside the code I had already read to establish the
redirect. **"My instrument sees nothing" is not "there is nothing."** The
companion rule [[verify-the-channel-not-just-the-query]] covers the query-vs-
channel half; this adds: **also ask whether a DIFFERENT channel was built for
exactly this.**

**I was one step from building a duplicate of an existing mechanism.**

---

### (retracted body follows, for the record only)

## [mlb-sim-log-unreachable-retracted] FINDING — THE MLB SIM JOB'S DIAGNOSTICS ARE UNREACHABLE FROM ANYWHERE `[2026-08-19, WRONG]`

**Every line `run_mlb_daily_sim_job.py` prints goes to a FILE on the worker's
disk and nowhere else.** `live_refresh_loop.py:2784-2790`:

    log_path = _mlb_sim_log_dir() / f"{date_str}_{run_stamp}.log"
    popen_kwargs["stdout"] = open(log_path, "wb")
    popen_kwargs["stderr"] = subprocess.STDOUT

The worker runs **no HTTP server**, and no ops endpoint tails that directory. So
**any failure inside the sim job is undiagnosable remotely** — not merely
inconvenient, invisible. Render's log API cannot serve it; `text=` searches for
those markers return nothing no matter what happened.

**THIS IS BLOCKING A LIVE DIAGNOSIS RIGHT NOW.** The `#440` checklist hook is
deployed and verified present in the live SHA (`f13ea05e`, 7 occurrences), sims
run normally, and **no `sim_input_report` has ever been published** (`count: 0`).
Three candidate causes, and **I cannot distinguish them**:

  1. the checklist subprocess fails on the worker (no rosters for that date,
     import error, the 180s timeout);
  2. it writes the report but `publish_changed_hot_artifacts` does not sweep it;
  3. `ok` is false in practice for a reason not visible from outside.

**Every one of those paths prints to the unreachable log.** The hook was even
written to print on its skip path precisely so a silent skip would be
distinguishable — and that print is unreachable too.

### The control that stopped a FALSE finding being filed here

I had concluded "13 sims started today, 0 finished — the sims are broken."
**Wrong.** Control against prior dates:

    2026-08-19   13 daily_sim   0 finished   exits={None: 13}
    2026-08-17   29 daily_sim   0 finished   exits={None: 29}
    2026-08-16   32 daily_sim   0 finished   exits={None: 32}

**`finished_at`/`exit_code` are NEVER populated for `kind=daily_sim`** — the row
is written at launch and the job detaches. "0 finished" is this ledger's normal
output, not an incident. **Sims are running.** Had the control not been run, a
production incident that does not exist would have been filed for another lane.

### What would fix it

An ops endpoint that tails `_mlb_sim_log_dir()` for a given date/run-stamp —
bounded, most-recent-N-lines, same auth as the other `/api/ops/artifacts/*`
routes. Alternatively, tee the wrapper's own status lines to the container stdout
the collector reads, keeping the volume low: `MLB_INPUT_CHECKLIST`,
`season_artifacts_pulled`, `ROSTER_REBUILD`, `MLB_DAILY_SIM_END`.

**Until then, every `verify:` naming a sim-job print is unusable**, and the
`#440` chain cannot be closed. Both `deploys.md` and
`mlb_sim_engine_reference.md` were corrected on 2026-08-19 to say so.


## [ncaaf-margin-calibration] NCAAF MARGINS ARE CALIBRATED; TOTALS ARE NOT `[verified 2026-08-19]`

**Margins fixed and measured** on the 2026 wk1 slate (51 games, 300 seeds):

| metric | before | after | market | ratio |
|---|---|---|---|---|
| margin SD | 1.74 | **15.37** | 14.46 | **1.06** |
| margin max | 7.80 | **50.64** | 49.50 | |
| total SD | 2.56 | 5.77 | 3.46 | **1.67** |

**The cause was the RATING SOURCE, not the engine.** CFBD PPA `overall` is a
per-play rate (SD 0.089); its differential rendered as margin SD ~2.3 through the
engine's ~17-pts-per-unit transfer. **SP+ replaces it** — points-per-game, and it
beat PPA on realised margins in two independent prior-season->next-season pairs
(r 0.506 vs 0.372; residual SD 17.63 vs 18.97, ~740 games each). `SP_RATING_SCALE
= 10.0`, calibrated on the real slate.

**TOTALS: the carrier is SCORING RATE, identified by decomposition.**
`total = drives x score% x pts/score` is exhaustive; across the slate's extremes
score% runs **20.8% -> 53.9% (2.6x)** while drives move only 24.4 -> 19.8 and
points-per-score is near flat. Real CFB converts ~35-45%. **TD share also runs
60.7% -> 83.8% against a real ~55-60%** — field goals are under-used at the top
end, which will distort FG props and alternate totals.

**THREE SCALAR FIXES FOR TOTALS ARE DEAD — do not retry:** the index clamp
(made margins AND totals worse, reverted), the yardage weight asymmetry (parity
was worse), and the `scoring_environment` weight asymmetry (a 3x reduction moved
total SD 0.07 pts, reverted). **They all damp INPUTS to a loop whose outputs
compound** across four-down sequences. The fix is in how `drive_simulator`
converts drives, and it is shared with NFL.

## [ncaaf-ratings-leak] NCAAF RATINGS WERE LEAKED FOR BACKTESTS — FIXED `[verified 2026-08-19]`

`/ppa/teams?year=S` is season-aggregate and contains the game being predicted:
**r 0.663 vs 0.509 as-of** over 558 games of 2024, a 30% inflation of apparent
skill. Fixed to aggregate `/ppa/games` over weeks < N.

**Two traps recorded because each produced a wrong result during the fix:**
`/ppa/teams` **accepts `week=N` and silently ignores it** (identical rows and
values), so the obvious fix is a no-op; and `/ppa/games` without
`seasonType=regular` returns the **College Football Playoff** under "week 1",
importing January games into a week-8 rating — strictly worse than the leak it
replaced. The tell was an impossible count (10 prior games through week 7), not
a failing test.

**The 2026 opener is unaffected either way** — no in-season history means the
2025 prior-season fallback, verified.

## [ncaaf-2026-data] NCAAF 2026 DATA IS BUILT AND SLATE-COMPLETE `[verified 2026-08-19]`

Coverage checked against the **94 FBS teams the wk1 slate needs**, not against
last year's totals: roster 15,442 rows / 138 teams / **0 missing**; coach
continuity 138 / **0**; returning production 136 / 2 (North Dakota State and
Sacramento State are FCS->FBS transitions with no prior FBS production —
legitimate); transfers 3,288 touching 137 teams / **0**.

**Five of seven builders could not run at all** — only `roster` and
`player_game_stats` loaded `.env`; the rest died on "Missing CFBD API key" from a
normal shell. Fixed at the shared choke point (`CfbdClient.from_env`). That is
likely why several snapshots had never been produced.

**None of it reaches the sim.** The generator is team-rating only. See
`docs/ai_context/ncaaf_data_pipeline.md` for the builders, their dependency
order, and the team_id-vs-name traps.


## [nfl-fantasy-engine] NFL FANTASY FOOTBALL ENGINE — **PASSES ITS FALSIFICATION TEST ON ALL FOUR CRITERIA, AND IS LIVE ON PRODUCTION `[web 003a5866, refresh-worker 6855fe96, read 2026-08-21T23:2xZ]`** — `/nfl/api/fantasy/draft-board` returns `available: true`, `mode: artifact`, and a real ordered board (Bijan Robinson RB1 VOR 167.9); the Fantasy pill is on the shared NFL nav — `render.yaml` was not touched, so no `blueprint_sync`; with `autoDeploy = no` this push ships nothing until someone deploys it. Depth chart current to 2026-08-21. `[measured 2026-08-21, lane nfl-fantasy-projections]`

ESPN-scoring season + weekly projections for QB/RB/WR/TE/K/DST at
`/nfl/fantasy`, with `/nfl/api/fantasy/{projections,draft-board}`. On `main` as
`45632889..c1c811c3`. **Every number below is from a local checkout, not from
production.** Pre-merge gate: the rebased branch, run in a tree WITH `data/`
present, produced exactly the four failures clean `main` already had -- zero
new. (Run in the sparse session worktree it showed four EXTRA failures, all
from `nfl_team_branding.csv` being absent under an excluded `data/`, not from
the code. A test failure in a sparse worktree is a fact about the worktree.) Reference:
`docs/ai_context/nfl_fantasy_engine_reference.md`.

**NEWS LAYER — two halves, and only one of them moves a number.**
The INJURY half is fitted and gated on: game designation → availability, graded
on 2,226 held-out player-weeks, MAE 6.894 → 4.399 (**+36.2%**). Measured
negative: adding the practice report made it WORSE (+25.8% / +30.9% vs +36.2%),
because the practice week is already priced into the designation.
The TEXT half (coach quotes, camp/role/workload talk) is CAPTURED and DISPLAYED
but **NOT SCORED** — `use_news_adjustments=False`. `scripts/capture_nfl_news.py`
builds an append-only dated archive (worker autorun, `interval_s=3600`,
CONFIRMED from the worker's own skip line) precisely because the text
was never ungradeable — it had merely never been STORED. Links use ESPN's own
athlete tags: measured 92 of 95 player-links via `espn_tag`, 3 via name match.
**The Buzz column is a DIALOG, not a tooltip** (`003a5866`): click the badge for the headline, the full description, when it ran and whether ESPN tagged it. Quiet rows are inert dashes, not empty buttons; article text is emitted ONCE per page as JSON keyed by player, because both tables render.
**NO CUSTOM HEADERS on any ESPN call** — see `learnings.md` 2026-08-21; a custom
UA 403s from Render AND from a dev machine, and `live_game_state.py:50` is where
that rule lives.
**MEASURED TWICE, AND THE ARCHIVE ACCUMULATES.** 22:28:32Z `fetched=50 new=50 total_today=50`; 23:29:29Z `fetched=50 new=2 total_today=52 linked=36` — 48 of 50 recognised as repeats by article id and the file GREW, which is the append-only merge doing the one job it exists for. Detail: `status=ok fetched=50 linked=35`, published, and `/nfl/fantasy` went from 0 live Buzz badges to 101 (58 players with coverage). Whole chain proven: worker fetch -> archive -> publish -> web disk -> request path -> rendered row.

**MEASURED, held out.** 2025 projected from 2022-2024 only, graded on ONE common
266-player set for every method:

| | baseline "last year" | engine | |
|---|---|---|---|
| season MAE | 49.41 | **47.67** | engine better |
| season spearman | 0.7058 | **0.7392** | engine better |
| per-game MAE | 3.68 | **3.56** | engine better |
| per-game spearman | 0.6138 | **0.6337** | engine better |

Rank correlation better at EVERY position. **The test ran four times: it passed,
then FAILED after a legitimate re-calibration, and the fail was reported rather
than tuned away.** Fixing the defect that fail exposed produced this result.

**THE AVAILABILITY COMPRESSION WAS THE DEFECT.** `_expected_games` scaled a role
curve by a health RATIO shrunk to the position mean and clamped to [0.5, 1.35]:
dispersion ratio 0.65 against the real spread, costing every genuine starter ~2
games (fit-season bias `0-4: +6.81 | 5-9: +3.34 | 10-14: +0.58 | 15-17: -2.00`).
Replaced with a DIRECT blend of a player's own games record and his projected
role's average. Dispersion **0.65 → 0.79** (2024), **0.71 → 0.81** (2025); bias
+12.03 → +6.91.

**THE TENSION THAT ALMOST HID IT: the blend is a WORSE predictor of GAMES (fit
MAE 3.55 → 3.65) and a BETTER predictor of SEASON POINTS (48.08 → 47.55).**
Compressing games toward the mean is exactly what minimises games error --
correct regression to the mean -- but season points are a PRODUCT of games and
rate, and a compressed factor biases the product. **A games-MAE sweep alone
would have REJECTED this fix.** Do not optimise the sub-quantity.

**TWO DEAD HYPOTHESES, measured, do not re-run:** the games curve IS
survivor-conditioned but fixing it is a NO-OP (teams already field 11 players
with carries and 15 with targets against a curve depth of 8, so zeros never
reach the modelled ordinals); and in-season callups take only **0.1-1.8%** of
team opportunity across 2023-25.

**RESIDUAL BIAS IS NOT A CONSTANT OFFSET** — it flips SIGN between seasons
(2024 -12.3 at >=8 games, 2025 +2.6). No level term removes it.

**CALIBRATION.** Constants selected on 2024 ONLY; 2025 never used to select
anything. Re-swept THREE times, most recently after the availability rebuild,
and **the third pass changed NOTHING** — every material constant was already at
the selected value, so the held-out result reproduces byte for byte. That is
stability across a structural change, which is stronger evidence than the
original selection. Confirmed with grid shape: `role_curve_strength` 0.0
(monotone, span 6.52 MAE, natural bound — pulling teams toward the league-average
split was the single largest accuracy loss in the engine);
`availability_history_half_games` 2.0 (clean interior peak, span 1.90);
`share_history_half_games` 18.0 (monotone to 18, turns at 26);
`rz_weight_receiving` 1.0. Seven others span 0.05-0.18 MAE and ship UNFITTED.

**A GRID'S WIDTH IS NOT ITS EFFECT SIZE.** The mechanical adoption rule flagged
`season_recency_weights` as material on a 1.43 MAE span; ~1.35 of that is the gap
between ONE prior season and more than one, which the default already clears.
Every multi-season option is within 0.08 MAE of every other and the "winner" beat
the incumbent by 0.0003 on a non-monotone ridge. REJECTED. The same rule
mislabelled `role_curve_strength` an edge selection when 0.0 is a natural bound.
Read the grid, not its width.

**A TEAM CODE THAT DOES NOT JOIN IS A SILENT WHOLE-TEAM DEFECT.** Refetching
`roster_2026.csv` changed Arizona from `ARI` to `AZ` while the schedule and pbp
kept `ARI`. Nothing raised: every Arizona player stopped joining to a team volume
or schedule, fell through to the no-market fallback, and STILL PRODUCED A
PLAUSIBLE NUMBER — Trey McBride held TE1 and his projection went UP. Fixed with
`fantasy_players.canonical_team()`; a test now asserts every roster team joins to
BOTH the schedule and usage. **Re-verify after any roster or schedule refetch.**

**THE ROLE PRIOR IS FITTED CONTEMPORANEOUSLY AND SPLIT BY EXPERIENCE.** Pairing
the CURRENT chart with the PREVIOUS season's usage priced "rank-2 QB" off a
population of displaced starters: Stetson Bennett, who has never taken an NFL
snap, drew a 0.374 pass share and pulled Stafford to 0.815. Now fitted
season-S-chart against season-S-usage over 2022-2025 (strictly before target),
keyed `(position, rank, rookie|no_prior_role|prior_role)`.

**HISTORICAL ROSTERS AND DEPTH CHARTS ARE NOW LOCAL** (`roster_{2022..2024}`,
`depth_charts_{2022..2025}`, via `scripts/fetch_nfl_rosters_depth_charts.py`).
Their absence was invisible — it surfaced as a calibration run scoring `inf` on
every parameter because `load_fantasy_players(2024)` returned an empty roster.
**nflverse publishes TWO depth-chart schemas** (dated snapshots for 2026,
week-indexed `club_code`/`depth_team` for 2022-2025); reading only the first
leaves every past season silently chart-less.

**GATE:** `scripts/nfl_fantasy_input_checklist.py --season 2026` exits 0 — 49
consumed fields populated, 15 documented sparse, 3 populated-but-unread surfaced
as dead weight. Emits UNMEASURED, never 0%, from a local checkout.

**NEWS/INJURY LAYER SHIPS OFF AND UNFITTED** — a MECHANISM added to an engine
calibrated without it (`model_engine_standard.md` s4.4), and no archived
historical news exists locally to grade its keyword weights. `?news=1` per
request; reachability-tested. **A share promotion and an availability cut of
reciprocal size leave the season total EXACTLY unchanged** (the pool normalises
on `share x games`) — correct, and it reads as "inert"; test the two separately.

**OWED BEFORE ANY DEPLOY** (nothing has been): build usage/news/input-report
artifacts ON THE WORKER; set `SYNDICATE_NFL_FANTASY_USAGE_STRICT=1` on web so a
request-path pbp parse fails loudly. A new usage FIELD needs
`build_nfl_fantasy_usage.py --force`, not just a deploy.

## [nfl-player-props-model] NFL PLAYER-PROP MODEL: `#471` FULLY CLOSED, ALL 6 TUNED CONSTANTS STABILITY-VERIFIED, ALLOWLIST GAP FIXED+LIVE — WEB DEPLOY OF THE FIX SET IN FLIGHT, NOT YET CONFIRMED `[verified 2026-08-19]`

`syndicate/features/nfl/player_stats.player_rate` (rolling season-to-date
rate) + `props._nfl_prop_model_probability` (Normal-CDF cover probability) —
the live NFL player-prop model — had never been backtested before this.
`scripts/backtest_nfl_props.py` (new) measured it over 152,919 real
(player, week, stat) rows, 2022-2025, complete local nflverse pbp (no
"Render is truth" caveat — historical/static data). **8 of 9 markets beat a
constant baseline both in-sample and out-of-sample** (fit 2022-2023, scored
2024-2025); `interceptions` genuinely shows no skill (corr 0.045). Full
table: `docs/ai_context/todo.md` `#471`, `.syndicate/deploys.md` 2026-08-19.

**Defect 2 FIXED, TUNED, MEASURED out-of-sample `[2026-08-19, lane
nfl-player-props-calibration-fix, 30caf008]`**: `anytime_td` at a rolling
rate of exactly 0.0 used to predict 0% (real hit rate ~13-14%, a
small-sample MLE problem). `player_stats.anytime_td_rate` now applies a
Gamma-Poisson shrinkage toward a no-lookahead league-wide prior, `k=12`
selected on 2022-2023 and only ever reported on 2024-2025 (never
re-selected there). OOS Brier 0.1973 → 0.1680 (8,464 held-out rows); the
raw_mean==0.0 bucket moved 0.0% → 18.0% predicted against a real 14.1% —
closes most of the gap, a ~4pp residual stays, stated not hidden. Real
trade-off: `anytime_td`'s point MAE got WORSE (0.358→0.386), correct for
a probability market (Brier is the graded metric) but a real cost.

**Defect 1 FIXED, TUNED, MEASURED out-of-sample `[2026-08-19, lane
nfl-player-props-skew-fix, 5def74df]`**: every count/yardage market's
Normal-CDF cover probability was overconfident near its own mean (~50%
predicted, ~37-44% actual) — real box-score stats are right-skewed,
`Normal(mean, stdev)` can't represent that. **First attempt (pure
log-normal, method-of-moments) was a NULL RESULT** — improved 4 of 8
markets, WORSENED the other 4 by overcorrecting; recorded (`reports/nfl_
cover_probability_model_comparison.json`), not shipped. **Real fix: a
per-market Normal/log-normal BLEND weight, closed-form Brier-minimizing**
(Brier is convex in a linear blend of two fixed probabilities — no grid
search), selected on 2022-2023, reported on 2024-2025:
`passing_attempts` w=1.0 (Brier 0.2062→0.1998), `rushing_yards` w=0.573
(0.2157→0.2111), smaller real gains on 3 more markets; `passing_tds`/
`interceptions` showed no real OOS benefit and ship UNCHANGED (w=0) —
not forced through. Full-scale re-run confirms the same shape
(`passing_attempts` Brier 0.1919→0.1836). Section 1 point-accuracy MAE
confirmed byte-identical before/after — no regression to any beats-
baseline verdict. Deliberately stdlib-only, no `scipy` (a declared-but-
never-imported dependency).

**`#471` is now FULLY CLOSED** — both calibration defects it found are
fixed and measured out-of-sample.

**Production artifact-allowlist gap — FIXED, DEPLOYED, VERIFIED LIVE
`[2026-08-19]`**. `basketball-model-owner` added `nfl_source/oddsapi_
player_props_*.csv` to `HOT_ARTIFACT_PATTERNS` (deliberately scoped to
`nfl_source/` specifically rather than a broader `*_source/` glob, to
avoid matching an unrelated shallow-depth file in another sport's tree).
Deployed to web (scoped commit, parented on web's live SHA — a straight
`main` deploy would have carried unrelated concurrent work).
`/api/ops/artifacts/export?pattern=nfl_source/oddsapi_player_props_*.csv`
now returns `count: 14` on production (was 0). **Content checked, not
just presence**: production's real coverage EXACTLY MATCHES the local
git mirror — 13 header-only stubs (5 bytes each) plus the single real
populated week, `2025_wk22.csv` (10,208 bytes, matching the local copy).
**Resolves the earlier "believed but unverified" uncertainty**: the
mirror was NOT lossy for this artifact; production genuinely has no
richer real-odds coverage. No `#471` Section 3 re-run is owed — there is
nothing new to re-run against.

**All 6 tuned `#471` constants individually stability-checked against
genuinely independent data `[2026-08-19]`**, one lane per constant,
fit-half (2022-2023) vs an INDEPENDENTLY computed estimate on the
2024-2025 half (never used to select, only to compare — closed form for
the 5 blend weights, grid search for `anytime_td`'s shrinkage k since the
`(n+k)` denominator makes Brier rational not quadratic there):

| constant | half A | half B | ratio | verdict |
|---|---|---|---|---|
| `rushing_yards` w | 0.5731 | 0.5717 | 1.00x | STABLE |
| `anytime_td` shrinkage k | 12.0 | 12.0 | 1.00x (exact) | STABLE |
| `receptions` w | 0.1367 | 0.0771 | 1.77x | STABLE |
| `receiving_yards` w | 0.2158 | 0.1242 | 1.74x | STABLE |
| `passing_attempts` w | 1.1409 | 0.8842 | opp. sides of 1.0 | UNSTABLE — left capped |
| `passing_tds` w | 0.3155 | 0.0217 | 14.55x | UNSTABLE — left at w=0 |
| `interceptions` w | 0.1329 | 0.0287 | 4.62x | UNSTABLE — left at w=0 |

No code change resulted from any of the 6 checks — every constant was
either confirmed well-supported or was already at its correct
conservative/safe value. Reports: `reports/nfl_*_stability_check.json`
(one per constant/group).

**WEB DEPLOY OF THE FULL FIX SET IS IN FLIGHT, NOT YET CONFIRMED LIVE**
`[fired 2026-08-19T21:59:15Z]`. Scoped commit `f149f5e2`
(`syndicate/features/nfl/{props.py,player_stats.py}` only, parented on
web's live SHA `450e0d6e`), deploy `dep-da32ecou01pc73fojijg`. Last read:
`build_in_progress`. **Do not cite this fix as live in production until a
later state.md edit confirms `status=live` by content** — the code has
been on `origin/main` since earlier today, but `origin/main` is not
production.

**NFL has no distribution/PMF at all** for player props — confirmed
independently by `convergence-phase7-crps`'s 165-file/160-date check. This
backtest measures the ceiling of a mean+stdev approximation, not a real
simulated ladder like MLB's pitcher props.

## [nfl-data-ingestion-autoruns] NFL ROSTER/DEPTH-CHART/INJURIES INGESTION — ALL 3 AUTORUNS ARMED, DEPLOYED, CONFIRMED FIRING — ONE PUBLISH SUCCESS STILL PENDING `[2026-08-21]`

`roster_snapshot_builder.py` and `depth_chart_snapshot_builder.py` are real
(both already consumed by `ask_the_syndicate_data.py`'s team-profile
evidence) but had NO automated production trigger before this session
(CLI-only) and both wrote via the probing-based `default_nfl_source_root()`
instead of `nfl_artifact_output_root()` -- the same `#389`-class write-side
bug already measured for SmartSim2 projections. Fixed (both switched to the
non-probing resolver; `injury_adjustment.py`'s depth-chart READ path also
had the sibling `#441`-class bug, fixed via a shared resolver mirroring
`nfl_pbp_path`/`nfl_injuries_path`), and wired into refresh-worker as two
new default-OFF autoruns
(`NFL_ROSTER_SNAPSHOT_ENABLE_REFRESH_WORKER_AUTORUN`,
`NFL_DEPTH_CHART_SNAPSHOT_ENABLE_REFRESH_WORKER_AUTORUN`).

**Armed and deployed in production** (refresh-worker, `df04c294` live
2026-08-20T17:32:54Z). Depth-chart: `LAUNCHING` clean on its first real
run, no crash. Roster-snapshot: crashed on its FIRST real run --
`ValueError: Roster snapshot validation failed: row 91 has invalid team
AZ; ...` (~90 rows, every Arizona Cardinals player) -- nflverse's own
team code for Arizona is `AZ`, not `ARI`, and `canonical_team_abbr` (the
shared `team_identity.py`) had no alias entry for it. **Fixed and
CONFIRMED WORKING against real production data**: the autorun's real
retry fired 2026-08-20T19:41:42Z, zero traceback in the full launch
window, `rows_written=2930` (the real 2026 nflverse roster, Arizona
included).

**`NFL_INJURIES_FETCH_ENABLE_REFRESH_WORKER_AUTORUN` -- ARMED
2026-08-21.** Deliberately deferred initially ("both autoruns" meant
roster/depth-chart specifically), offered as a ridealong to
`football-model-owner`; that session ended without acting (env var
confirmed absent across all 112 vars, no lane update mentioning it).
Armed directly on explicit user instruction: env var set, then a
user-triggered manual Render-dashboard redeploy (`deploy_preflight.py`
correctly refused a same-SHA redeploy as "ALREADY LIVE -- redundant",
no override exists for the env-var-only-refresh case). That manual
redeploy picked up `origin/main`'s tip (`916593f6`, 94 commits/48 files
past refresh-worker's prior SHA) rather than a scoped same-commit
refresh -- flagged immediately, confirmed clean (no traceback, memory
stabilized ~50% of container). `NFL_INJURIES_FETCH_LAUNCHING` fired
2026-08-21T02:10:40Z, result `"status": "unavailable"` (a real HTTP
404 from nflverse -- the fetcher's own documented NORMAL case for a
season with no injury reports published yet, not a crash). Autorun
confirmed correctly wired and firing.

**HOT_ARTIFACT_PATTERNS allowlisting: DONE, DEPLOYED, but a SECOND gap
found behind it (`nfl-artifact-allowlist-add` / `nfl-artifact-publish-
wiring`).** `basketball-model-owner` (the original handoff target)
archived without acting; taken directly since its lane was no longer
OPEN. Added the 3 patterns, deployed to BOTH web (`c5c1b0b5`, live
2026-08-20T20:59:56Z) and refresh-worker (`08bd601f`, live
2026-08-20T21:18:35Z). A real `/api/ops/artifacts/export` call against
production then returned `count: 0` for both checked patterns --
**allowlisting alone was not sufficient.** Traced (not assumed): NOTHING
called `publish_hot_artifact()` for any of the 3 artifacts --
`fetch_nfl_injuries.py` had no publish call site at all;
`roster_snapshot_builder.py`/`depth_chart_snapshot_builder.py`'s own
`publish=` flag only renamed the local file, never pushed cross-service.
Exactly `#208`'s lesson ("allowlisting PERMITS a transfer, it does not
MAKE one happen"), measured as real rather than hypothetical. Fixed --
all 3 scripts now call `publish_hot_artifact()` best-effort after a
successful write, mirroring `generate_smartsim2_nfl_projections.py`'s
existing pattern -- and deployed to refresh-worker (`d1a897b2`, live
2026-08-20T21:57:44Z).

**Roster/depth-chart's real retry (2026-08-21T01:42Z) hit a
TRANSIENT, UNRELATED web-restart DNS blip on the publish call** --
both wrote cleanly (`rows_written=2930` for roster, identical to the
earlier confirmed run) but `artifact_published=False` for both, traced
to `PUBLISH_FAILED ... Name or service not known` coincident with an
unrelated web deploy finishing at 01:43:40Z. Confirmed the transport
recovered fully (105 `PUBLISH_OK` lines for other artifacts within
minutes). **This is the one remaining unverified link**: all 3 autoruns
are armed, deployed, and confirmed firing correctly, but no clean
end-to-end publish success (a real `PUBLISH_OK` for one of the 3 NFL
paths, or a nonzero `/api/ops/artifacts/export` count) has happened
yet. Next roster/depth-chart retry ~21600s from 2026-08-21T01:42Z;
injuries fetch will retry on its own schedule too, and would also
confirm the publish path once nflverse actually has data to return.

## [mlb-vendor-exit-audit] MLB VENDOR EXIT — 18 OF 20 PIPELINE STAGES HAVE NO NATIVE PRODUCER `[2026-08-20, MEASURED]`

**Syndicate's MLB module is a READ LAYER over vendor-produced artifacts.** Of the
22 modules in `syndicate/features/mlb/`, **exactly two write anything**:
`ladders_build.py` and `live_lens.py`. The other 20 — `cards.py`,
`top_props.py`, `hr_targets.py`, `pitcher_ladders.py`, `betting_card.py`,
`season.py` — are readers and presenters.

**The names invite the opposite conclusion and that is the trap.**
`top_props.py`, `hr_targets.py` and `roster_snapshot_builder.py` all read like
producers; all three contain **zero** `json.dump` / `write_text` calls, and the
roster one is not even MLB (`syndicate/features/football/ingestion/`). Verify a
producer by whether it WRITES, never by its name.

`vendor/mlb_bettingv2/tools/daily_update.py` runs **20 stages**. Native coverage:

| stage | native producer |
|---|---|
| `current_day_oddsapi` | **YES** — `scripts/refresh_odds_sources.py` (13 writes) |
| `current_day_ladders_artifact` | **PARTIAL** — `ladders_build.py`; 4 presenter fields short (`lineupOrder`, `paMean`, `matchupReasons`, `matchupSummary`), hitter ladders 0/234 |
| `prior_day_live_lens` | **UNCONFIRMED** — `live_lens.py` writes 3 artifacts; not verified to be this stage's output |
| the other **17** | **NONE** |

The 17: `prior_day_feed_live_refresh`, `prior_day_card_settlement`,
`live_pitcher_corrections`, `prior_day_eval_report`, `season_publish`,
`prior_day_top_props_artifact`, `current_day_overwrite_prep`,
`current_day_multi_profile`, `hr_target_history_reconcile`,
`current_day_top_props_artifact`, `current_day_ladder_audit_artifact`,
`current_day_season_frontend_artifacts`, `next_day_forward_build`,
`current_day_batting_lineups`, `current_day_probable_pitchers`,
`current_day_roster_snapshot`, `render_frontend_validation`.

**METHOD AND ITS LIMIT, so nobody over-reads the number.** Audited by *who
writes the artifact*. A stage whose output is genuinely obsolete shows as a
false gap — `current_day_overwrite_prep`, `next_day_forward_build`,
`render_frontend_validation` and `season_publish` read as vendor-internal
plumbing that may need no port at all. So: **~14 stages of real work, ~4 to
triage**, not a flat 18.

**SEQUENCING:** `current_day_multi_profile` is the SIM itself and every
downstream stage consumes its output — it decides whether this is a port or a
rewrite, and it should be scoped before any plan for the rest is committed to.

**THIS CONTRADICTS A DOCUMENTED FACT.** MLB is described as the reference module
with "no source-app fallback" and the first fully local runtime contract. For
the ladders artifact that is FALSE: the vendored Flask frontend
(`daily_update.py:3694`) writes it on every cycle, and the native builder is a
fallback that fires only when the vendor stage errors
(`daily_update.py:3684`). `ladders_build.py`'s own docstring claims it retired
the vendor writer; it did not. That docstring caused two successive
misdiagnoses on 2026-08-20.

## [mlb-ladders-native-builder] MLB LADDERS — NATIVE BUILDER SHIPPED TO THE TREE `[2026-08-19]`

### ONE WRITER PLUS A BROKEN FALLBACK -- NOT A RACE `[2026-08-20T19:2xZ, VERIFIED -- SUPERSEDES THE "RACE" FRAMING BELOW]`

**The trigger path, traced end to end.** Per sim cycle:

    run_mlb_daily_sim_job.py:237   shells out to vendor/.../tools/daily_update.py
    daily_update.py:3694           writes the VENDOR 26-field ladders artifact
    run_mlb_daily_sim_job.py:488   native is_stale() -> artifact seconds old -> SKIP

So the vendor writer is the NORMAL producer and `#440`'s native builder is a
**FALLBACK that fires only when the vendor pipeline ERRORS** --
`daily_update.py:3684` skips its ladders stage exactly when
`current_stage.status == "error"`. The two do not race for the file; the native
one runs only where the vendor one gave up.

**Therefore the MLB pregame-chip outage was: the fallback fired after a failed
daily update, and the fallback wrote a schema the board cannot read.** That fits
the 16:46 native-stamped artifact and the sim ledger's many MLB runs that start
and never reach a terminal state.

**Consequence for verification: there is NO production lever that forces a
native rebuild.** `SYNDICATE_MLB_LADDERS_REFRESH` is on/off not force;
`is_stale` has no force branch; `/api/ops/live-refresh/force-mlb-resim` runs the
sim job, which runs `daily_update` first, so the native path skips again. Proof
requires either inducing a vendor-stage failure or shipping a force knob.
`a54dffa3` is correct by local measurement over real production inputs (18/18)
and its production wiring is UNPROVEN by design, because the path runs rarely.

**The vendor writer was NOT retired.** `ladders_build.py`'s docstring says the
only thing that ever wrote `daily_ladders_<date>.json` was the vendor frontend
and that this module replaces it. **False.**
`vendor/mlb_bettingv2/tools/web/flask_frontend.py:4057` still rebuilds the
artifact ON-REQUEST whenever it reads stale, and emits a **26-field** row schema
WITH `ladder[]`, `gamePk`, `pitcherId`. The native builder emits **10** fields
and none of those three. Both write the same path; last writer wins.

Observed on production, same file, same day:

    16:46:16Z  generatedBy=syndicate.features.mlb.ladders_build   ladder 0/18
    18:19:09Z  no generatedBy  (vendor)                           ladder 18/18
    18:56:23Z  no generatedBy  (vendor)                           ladder 18/18

**Consequence:** `cards.py`'s pregame starter chips need `gamePk` + `ladder`, so
they FLAP -- dead after a native write, alive after a vendor write. The MLB board
rendering no pregame chips AND no starter NAME (the JS gated the name on the
badge list) is this, not a data outage.

**`generatedBy` is the discriminator** -- only the native writer stamps it
(`ladders_build.py:564`). Any claim about which writer produced a given copy
must cite it. Size differs by an order of magnitude too: native 684,325 B vs
vendor 9,518,280 B, the latter within 3MB of `_PUBLISH_MAX_BYTES`.

**Fix `a54dffa3` is LIVE on refresh-worker `[18:27:40Z]` and so far INERT.** The
native writer has not run since: its status artifact reads
`outcome: "skipped_fresh"` at 18:56:57Z, because the vendor's write is always
newer than the sims so `is_stale` correctly answers `fresh`. **The board being
correct right now is the VENDOR writer's doing, not the deploy's.** Unproven in
production until a served artifact carries `generatedBy=...ladders_build` AND
populated `ladder[]`.

**Web rebuilding a 9.5MB artifact inside a request handler contradicts the
worker-split rule** (web does no heavy computation). Known, unowned, out of
scope for the lane that found it.


### ROOT CAUSE FOUND AND MEASURED `[2026-08-20 ~01:00Z]` — THE SWEEP WAS REFUSING IT ON SIZE

    daily_ladders_2026_08_19.json      13,678,982 bytes
    _PUBLISH_MAX_BYTES (sweep-only)    12,582,912 bytes      -> REFUSED

Measured on refresh-worker `2026-08-20T00:55:00Z` (Render logs API,
`resource=srv-d91dpertqb8s73co8ls0&text=too_large`):

    SWEEP_SKIPPED_DETAIL too_large=[
      mlb_source/.../daily_ladders_2026_08_19.json(13678982),
      mlb_source/tracking/book_quotes/2026-08-19.jsonl(95051585)]

**Every other link was already correct, which is why this took five successive
hypotheses.** The worker DID rebuild the ladder (`artifactGeneratedAt
2026-08-19T19:54:41-05:00`) and `is_stale()` DID correctly answer `fresh` —
content newer than `oddsMtime_pitcher 1787187226` and `newestSimMtime
1787186761`. Web simply went on serving the last copy that FIT: **11,716,507
bytes, `2026-08-18T18:20:25`**. That is the whole reason every served
compact-card row carried a full sim side against an empty market side.

The artifact **grew into** the bug — the 08-18 copy was under the bound, the
08-19 copy over it. No deploy, no regression, no failing test on the day it broke.

FIX: `be62b0dd` on `origin/main` (content-verified inside merge `3fc6ef0c`) —
publish the ladder through `publish_hot_artifact`, which streams above 4MB and
never consults `_publish_skip_reason`. Same route `book_grid` (12,855,903 bytes)
has used all along. **The bound is UNTOUCHED** — it is sweep-only by design and
exists to stop 51MB `odds_history` shards going up every cycle.

**STATUS: DEPLOYED AND CONFIRMED FIXED `[2026-08-20T02:18Z]`** — `dep-da35tbrbc2fs738atmjg`, live 02:03:08Z. Web's ladder moved `2026-08-18T18:20:25` → `2026-08-19T21:17:32` and 11,716,507 B → 12,627,555 B; `directPublish {attempted:true, ok:true, bytes:12627555}`. Pitcher strikeouts now carry market lines on **20 of 30** rows (was 0 of 12). The new size is STILL 44,643 B over the sweep ceiling, so the direct path is what carried it. Claim released. Detail: Deploy branch
`deploy/mlb-ladder-publish` = **`041188cb`**, cut from refresh-worker's LIVE SHA
`b2f4b197` (live 01:13:09Z), NOT from main — main is 432 files / 126,420 lines
ahead of this service and a ~420-commit jump on a live 4GB sim service is not a
change to attach to a one-file fix. Cutting from the LIVE SHA is what keeps it
cumulative with the soccer `#343` deploy that landed at 01:13. Verified present
at `b2f4b197` before cutting: `publish_hot_artifact`, `daily_ladders_path`,
`write_status_artifact`, `pull_season_artifacts`, BOTH ladders allowlist
patterns, and the streamed transport (`_PUBLISH_STREAM_MIN_BYTES = 4MB`); the
two touched files are byte-identical at `b2f4b197` and at the change's base, so
it is an exact add that clobbers nothing.

Claim HELD by `convergence-phase7-crps` since 01:18:37Z (ttl 2700s → ~02:03Z).
Preflight **HOLD** — an MLB sim is in flight (`run_mlb_daily_sim_job.py` pid 127
+ `daily_update` children). Not killed: a daily sim discards ~30 min of work and
the ~109 artifacts it publishes. Poller running until it drains.


### >>> MLB SIM INPUTS: THE PULL WAS BROKEN BY ONE `*` — FIXED `[2026-08-20T18:03Z]` <<<

**`39570b24` live 17:54:04Z.** `_SEASON_ARTIFACT_PATTERNS` held BARE filename
globs (`arsenal_*.json`). The export endpoint matches
`fnmatch(relative_path, pattern)` (`ops.py:1349`) against the FULL path and
fnmatch anchors both ends, so **all five patterns matched NOTHING** — five
requests, zero files, every season-scoped sim input absent from the worker.

**MEASURED** (`sim_input_report.season_artifacts`, host=worker):

    BEFORE gen 17:22:58Z   all five exists=False
    AFTER  gen 18:03:12Z   arsenal 466 / conditional_mix 728 / batted_ball 509
                           quality 509 / pitch_splits 305, all loadable=True
                           byte counts match web's copies -> transport intact

**THE FIELDS ARE STILL 0.0% AND THAT IS EXPECTED.** Presence and population are
SEPARATE milestones: the pull runs at sim start, that run REUSED rosters built
~07:37Z, and the appliers only write during a BUILD. Predicted before the reading.

**verify 2026-08-21:** first `sim_input_report_2026-08-21.json` — expect `nfail`
**10 -> 0** `[revised 18:5xZ; was 15 -> 6]` -- `7dc4893d` moved the five `vs_pitcher_*` fields OUT of the failure count into a `disabled` category, because they are unfed by DELIBERATE CONFIG (`FORWARD_BVP_MATCHUP_MODE = "off"`, re-entry condition stated in its own comment), not by defect. Any residual failure tomorrow is unambiguously real.

Superseded detail:**, with the five `vs_pitcher_*` entries STILL present (BVP path,
untouched). Still 15 on a fresh `generated_at` = a SIXTH cause, reopen.

**This is why `85296826`'s conditional-mix wiring looked inert** — the wiring is
correct and called; `conditional_mix_2026.json` was simply never on the worker.

**Superseded:** the `1ef337c0` deploy-candidate block. `85296826` shipped it and
is an ancestor of live.

### >>> (superseded) DEPLOY CANDIDATE `1ef337c0` <<<

**`deploy/mlb-mix-and-markets` = `1ef337c0`, parent `041188cb` (the LIVE SHA).**
4 files, +323/-4, additive. All four verified BYTE-IDENTICAL at `041188cb` and
at each change's base (or absent, for the two new tests) — an exact add.

**PRIMARY, and MEASURABLE — the conditional mix was never called.**
`apply_conditional_mix_to_pitcher` had exactly one caller anywhere, including
on main: `scripts/validate_crn_pa_seeding.py`, a validation script. The roster
build never invoked it, so `roster_artifact.py` faithfully serialised
`conditional_arsenal: {}` forever. Production's own `sim_input_report`
(host=worker) read **`conditional_arsenal 0.0%` on 2026-08-19 AND 2026-08-20**
with the artifact published, allowlisted and reachable the whole time.

**verify:** the FIRST `sim_input_report_<date>.json` written after the deploy
must show `conditional_arsenal` / `count_bucket_map` / `conditional_arsenal_source`
NON-ZERO. Read it at
`/api/ops/artifacts/export?pattern=*sim_input_report*`. This is a reading of a
PUBLISHED ARTIFACT, not a log line — the sim's stdout goes to a disk file the
Render log API cannot serve.

**THE ROSTER-REBUILD THEORY IS RETIRED — do not spend more time on it.**
`--use-roster-artifacts` only reuses an artifact for the SAME date that also
passes `_roster_artifact_matches_inputs`, so a fresh game date always rebuilds.
2026-08-20's rosters WERE built fresh and still came out empty. No env gate and
no forced rebuild could ever have fixed this. `SYNDICATE_MLB_ROSTER_REBUILD_DATE`
is now irrelevant to the conditional mix.

**RIDEALONG folded in, zero marginal cost:** `hitter_strikeouts` joins
`batter_strikeouts`. Its own preflight FAILED standalone on measurability
(0 players observed 08-16..19 → the reading would be 0→0), which is what a
ridealong is for. Expect it to stay 0 until books post that market; that is
NOT evidence the wiring failed.

**rollback:** redeploy `041188cb`.

### >>> (superseded) STANDING RIDEALONG <<< `[refreshed 2026-08-20T03:1xZ]`

**The branch this block used to name is SPENT.** `deploy/worker-ladders-ridealong`
/ `5c2851a4` shipped inside `041188cb` (live 02:03:08Z) — native builder, tests
and sim-job trigger are all live. Do not re-cut it. What follows below, from
**BUILT**, is the still-accurate description of that shipped module.

    carry      syndicate/features/mlb/ladders_build.py
               tests/test_mlb_ladders_build.py
    source     1e15addc (on origin/main); also cut as 15547572 on branch
               deploy/mlb-ladder-market-wiring, parent 041188cb
    scope      2 files, +92 / -4, additive; 25 tests pass, 4 new ones mutation-checked

**If the live SHA is still `041188cb`, just deploy `15547572`.** If the worker
has moved, re-cut onto the NEW live SHA — both files were byte-identical at
`041188cb` and at the change's base, so it is an exact add (`read-tree <live>`,
`update-index` the two paths with blobs from `1e15addc`, `commit-tree`).

**WHY RIDEALONG AND NOT A DEPLOY.** Its own preflight returned FAIL
`[2026-08-20T03:0xZ]` — not on safety, but on measurability:
`batter_strikeouts` is present for **0 players across 08-16..08-19**, so the
expected observation is 0 → 0, which neither confirms nor refutes the change,
while a standalone deploy costs a restart that KILLS AN IN-FLIGHT SIM. Riding
along makes the cost zero. Caveat that bounds the claim: those were WEB's
partial mirrors — the same 08-19 file read 47 players and then 14 an hour later
— so this is "not measurable tonight", NOT "the market is never captured".

**What it changes:** `hitter_strikeouts` joins `batter_strikeouts`, a market
already in `DEFAULT_HITTER_MARKETS` that we pay for on every hitter fetch and
never read. Pitcher `pitches`/`batters_faced` documented as permanently
marketless. doubles/triples/stolen_bases wired but UNFED — **user decision
2026-08-20: do not fetch them** (~+9% of burn, ~3 days of a ~39-day runway).

**ALSO ON THE SAME RESTART — `SYNDICATE_MLB_ROSTER_REBUILD_DATE=2026-08-19`**,
VERIFIED still set 03:07:35Z via `/v1/services/.../env-vars`. **EXPIRES 05:00Z.**
Whether the 02:03 deploy already spent it is **UNKNOWN — not determined.** The
sim-log tail shows no roster line, but the flag prints at the START of a run and
the endpoint serves only the last 8000 chars, so that absence is about the
WINDOW, not the run.

**THE CHECK THIS BLOCK ORIGINALLY NAMED DOES NOT WORK — corrected 03:3xZ.** I
said "check whether roster artifact mtimes moved after 02:03Z". You cannot:
`roster_objs/` is WORKER-LOCAL. The read allowlist appears to permit it
(`fnmatch` lets `*` cross `/`), but the SWEEP uses `Path.glob`, where `*` does
not cross `/`, so `snapshots/<date>/roster_objs/*.json` is never published.
Confirmed by export: **0 files visible on web.**

Every other reading is blind too, each for a DIFFERENT reason, which is worth
knowing before anyone spends the time again:
- `ROSTER_REBUILD armed` in Render logs: 0 hits, because the wrapper's stdout is
  redirected to a disk file and never reaches the collector.
- sim status `command`: it DOES carry the inner `daily_update` argv, but the ops
  endpoint served an IN-FLIGHT run's launcher record (`startedAt: None`), and
  completed `*_status.json` files are not exported.
- `ALL_PROCESS_MEMORY` cmdlines: stored TRUNCATED (`tools/daily_update.py`, no
  argv) and the flag is appended late, so its "absent" is about the truncation.

**So: whether the gate fired is NOT KNOWABLE from here.** Do not record either
answer. The cheap resolution is to stop asking and re-arm: point
`SYNDICATE_MLB_ROSTER_REBUILD_DATE` at the NEXT slate and let it ride with the
next refresh-worker deploy (the var needs a DEPLOY to inject, not a restart, so
it composes with the ridealong above). That trades one bounded rebuild for
certainty.

**BUILT.** `f86b24a3` + `6a213156`.
**Nothing imports `flask_frontend` any more.**

    syndicate/features/mlb/ladders_build.py     native builder, 17 prop groups
    tests/test_mlb_ladders_build.py             14 tests, mutation-checked
    scripts/run_mlb_daily_sim_job.py            trigger, before the publish sweep

**VERIFIED ON REAL DATA** (2026-05-28, the date the local mirror holds):

    PITCHER  strikeouts/outs/hits_allowed/earned_runs/walks_allowed
                 12 rows, 6 with lines, matched 6/6
             pitches, batters_faced                marketAvailable=false
    HITTER   hits/hits_runs_rbis/home_runs/total_bases/runs/rbi
                 156 rows, 58-71 with lines, matched 74/74
             hitter_strikeouts/doubles/triples/stolen_bases  marketAvailable=false
    both native readers render cards from the output

**Every market-backed prop matched 100%, zero unmatched odds on either side.**

**THE ODDS FEED IS NARROWER THAN THE SIM** — 5 of 7 pitcher props, 6 of 10
hitter. Those carry `marketAvailable: false` and are EXCLUDED from the join
accounting. Without that, four hitter props would report `matched 0/74` forever
and look exactly like the bug this module fixes.

**THE JOIN IS PUBLISHED:** `matchedPlayers` / `oddsPlayers` / `unmatchedOdds` /
`unmatchedSimNames` on every group. Sim keys on `mlbam_id`, odds on lowercase
name; names fold through an accent-stripping normaliser (the feed writes ASCII
where the roster writes diacritics).

**THE WRITER REFUSES TO OVERWRITE A GOOD ARTIFACT WITH AN EMPTY ONE** — an empty
rebuild renders identically to a correct one, so overwriting on zero rows would
destroy working output and look like a successful refresh.

**TRIGGER:** `is_stale()` fires on `artifact_missing` / `odds_newer` /
`sim_newer`, checked against BOTH odds files. Not a rebuild every tick. The
`sim_newer` clause is what re-derives ladders on GAME STATE, since sims re-run
every 15-20 min. Env kill-switch `SYNDICATE_MLB_LADDERS_REFRESH`, default on,
never fatal, skipped when the sim failed.

**DEPLOYED AND VERIFIED `[2026-08-20T02:18Z]`, `041188cb`.** `daily_ladders_*`
is allowlisted (2 patterns) — but note the sweep alone was NOT sufficient: the
artifact exceeded `_PUBLISH_MAX_BYTES` and was refused silently, so the sim job
now also publishes it DIRECTLY via `publish_hot_artifact`. See the root-cause
block above before assuming the allowlist is enough for a large artifact.

**Bugs caught by RUNNING the real reader, not by reading:** `away`/`home` are
OBJECTS and were being stringified whole into `team`/`matchup`; and the push
boundary (`>` vs `>=`) — mutation-tested, a whole-number line must push.

### WHY — the original diagnosis, kept because it is the evidence

**SYMPTOM (user-reported, confirmed on the SERVED payload):** pitcher-props
ladder candidates on the MLB compact cards do not update. Every row carries a
full sim side and an EMPTY market side.

    GET /mlb/api/pitcher-ladders?date=2026-08-19  ->  found=True, 12 rows
      "Mean 4.66  Over '-'  Mode 4  Sim count 994"
      "Market line: -"   "Over probability: -"

**MEASURED CAUSE — a timing gap, not a missing producer:**

    ladder artifact  daily_ladders_2026_08_19.json   generatedAt 2026-08-18T18:20:25-05:00
    odds artifact    oddsapi_pitcher_props_2026_08_19.json  retrieved_at 2026-08-19T18:16:45
                                                      mode=live, 24 pitchers, real lines

**The ladder was built ~19h BEFORE the odds arrived and nothing rebuilds it.**
Sims are NOT the problem: 24 `daily_sim` runs on 08-19, latest 18:10:39Z, every
15-20 min. **The ladder is the only stale link.**

**WHY NOTHING REBUILDS IT.** The only writer is `write_daily_ladders_artifact`
in **`vendor/.../flask_frontend.py:4058`**, called ON REQUEST when
`_artifact_is_stale()` and only while the SOURCE APP serves. Syndicate has the
READER and PRESENTER only — `cards.py:1273`, `ladders_common.py:142`,
`pitcher_ladders.py` (whose own docstring says "backed by the existing ladders
artifact"). **Syndicate inherited the consumer and not the producer.**

### TWO WRONG DIAGNOSES I PUBLISHED FIRST — both from ONE artifact-export query

1. *"the artifact is frozen at 2026-06-02"* — **WRONG.** `export?pattern=*ladders*`
   returns only `daily_ladders_2026_06_02.json`, but the live artifacts sit at
   `/opt/render/project/data/...` and the SERVED payload shows today's file.
2. *"Syndicate inherited the reader not the writer, so it stopped in June"* —
   half right, wrong conclusion: it IS produced, just never refreshed.

**The served payload contradicted both in one call, and I had not looked at it.**
`feedback_user_watches_the_board` says go straight to the served payload. I did
not, and scoped an entire worker-side builder for a frozen artifact that was not
frozen.

### NATIVE BUILD IS ASSEMBLY, NOT INVENTION — every input verified present

    SIM     daily_sim_artifact_path(date, game_pk)         sources.py:308
            -> sim.pitcher_props[<mlbam_id>].so_dist  (full outcome histogram)
                                             .so_mean
            (also outs/pitches/hits/earned_runs/walks/batters_faced _dist+_mean)
    MARKET  daily_snapshot_oddsapi_pitcher_props_path(date) sources.py:286
            -> pitcher_props[<lowercase name>].strikeouts.line / over_odds
            **already imported by cards.py:46**
    SCHEMA  pinned by ladders_common.py:70-84 — rows need pitcherName, team,
            matchup, marketLine, mean, mode, overLineProb, simCount
    SHAPE   groups.pitcher.strikeouts.rows[]  (`_extract_prop_group`, :35)
    WRITE   daily_ladders_path(date)                        sources.py:163

`mode` = argmax of `so_dist`; `overLineProb` = mass above the line. **Arithmetic
on data that already exists — no new model.**

### THE JOIN RISK, named before writing it

**Sim keys on `mlbam_id` (`680570`); odds key on lowercase NAME
(`"michael king"`).** That name->id join is where rows will silently vanish. The
builder MUST count and publish unmatched pitchers — 24 odds pitchers yielding 11
rows has to be visible in the artifact, not inferred from a thin card.

**NEXT:** native `ladders_build.py` (pitcher/strikeouts first — it is what the
compact card reads via `_extract_prop_group(summary,"pitcher","strikeouts")`),
then a freshness trigger in the sim job so every ~15-min sim re-derives ladders
against current lines AND current game state. **Retires the vendor import.**


## [nfl-player-props] NFL player props: capture fixed, model priced and BEATEN by the market

`[verified 2026-08-21, lane nfl-props-odds-allowlist]`

- **NFL/NCAAF prop capture returned ZERO rows for its entire existence.** Bulk
  `/sports/{key}/odds` does not serve player props (`422 INVALID_MARKET`,
  verified live); they are per-event only. Two market keys were also invalid.
  Fixed; refresh-worker live on `59afbbb6`. 0 -> 80 rows on a live run.
- **PRODUCTION BEHAVIOUR VERIFIED 2026-08-21T14:08:06Z.**
  `oddsapi_player_props_2026_wk1.csv` went **5 bytes -> 12,142 bytes** with a
  FRACTIONAL mtime (runtime write, not a boot copy). Content read, not inferred:
  **84 rows, 84 distinct players, real DraftKings Anytime TD prices**. Ran
  unattended on refresh-worker. First real NFL player-prop capture this platform
  has ever made.
- **NFL runs on `refresh-worker`, and ONLY there. CORRECTED 2026-08-21** —
  an earlier line here said live-odds-worker owned NFL in season. That was
  wrong. It was reasoned from `_weekly_sport_claimed_by_fast_tick` in the CODE
  and never checked against the env. Measured from live env-vars:

      refresh-worker    SYNDICATE_ACTIVE_SPORTS = nfl
      live-odds-worker  SYNDICATE_ACTIVE_SPORTS = mlb,wnba,soccer
      web               SYNDICATE_ACTIVE_SPORTS = mlb,wnba,soccer,nfl

  `SYNDICATE_ACTIVE_SPORTS` gates EARLIER than the ownership predicate, so
  live-odds-worker can never run NFL whatever the horizon says. Confirmed in
  its own logs, every tick:

      [live_refresh_loop] SWEEP_OWNERSHIP_EXCLUDED kept=mlb,wnba,soccer
        dropped=nfl:not_in_SYNDICATE_ACTIVE_SPORTS

  The horizon predicate is real but unreachable for NFL on that service.
- **The prop model does not beat the market**: -7.35% (best price, n=48,024) /
  -7.23% (DraftKings, n=13,368) over 64,007 graded bets, 2023-2025 REG closing
  lines. Fading it loses 16.93%, so the picks are correctly signed.
- **Price shopping is worth +2.95 ROI points**, controlled on 12,986 identical
  bets. Largest single lever measured.
- **Backfilled odds now exist on disk**: 109,750 rows / 513,235 quotes / 579 of
  816 REG games, 2023-2025. `data/nfl_source/` (untracked mirror).

## [nfl-game-context] Game context is built and measured, and INERT in production

`[verified 2026-08-21, lane nfl-props-odds-allowlist]`

- Implied team total + spread, self-normalised against the player's own history,
  fitted per market on 2023-2024. **Paired on 16,906 held-out 2025 bets:
  -7.44% -> -6.26% (+1.18 pts)**, brier and hit rate moving with it.
- **DEPLOYED INERT on web `7c2e92c0`.** It read
  `tracking/nflverse/schedules_games.csv`, which is gitignored and has no writer
  in this repo -- `count: 0` on web with the pattern confirmed deployed.
  Multiplier collapses to 1.0 for every player. Harmless, but doing nothing.
- Fix landed on `8fe78662` (reads `schedule_{season}.csv`, allowlisted, publish
  call added to `fetch_nfl_schedule.py`) and is **NOT DEPLOYED**.

## [soccer-live-tier] SOCCER'S LIVE TIER — VERIFIED, AND WHAT IS NOT

**BTTS AND CORNERS ARE CAPTURABLE, AND THE 07-21 "unavailable" NOTE WAS WRONG**
`[verified 2026-08-22 00:2xZ, live API probe, lane soccer-board-mlb-parity]`.
They are served from the **PER-EVENT** endpoint (the one the props fetcher
already calls), NOT the bulk one, so capture costs **no additional API calls**.
The Odds API's `INVALID_MARKET` carries two messages and only
`"Invalid markets: X"` means the key does not exist; `"not supported by this
endpoint"` means it does. Measured coverage, EPL MUN @ HUL:
`us` btts 7 / corners 7 (CHOSEN, user decision, 2 units/event) ·
`uk` 11/4 · `eu` 4/1 · all four regions 29/18.

**The full BTTS/corners path is BUILT AND TESTED, NOT IN PRODUCTION.** Capture,
de-vig (raw implied 1.0096 -> `p_btts_yes` 0.4903, below raw, correct
direction), main-line selection (9.5) and tiles all verified on real captured
data: `BTTS YES 55.5% | Model 55.5% | Market 49.0% | Edge +6.5 pts`. But
**`refresh-worker` executes the refresh and is on `49e4cef2`**, which predates
the capture — so no `game_markets_<date>.csv` exists in production and the
tiles correctly still read "no market captured".

**MOMENTUM IS NOT LIVE, FOR THE SAME REASON.** Soccer live_state is written by
**refresh-worker** (`SYNDICATE_ENABLE_SOCCER_WEEKLY_REFRESH_AUTORUN`, scoped in
`render.yaml` to "the sim and live_state") — not by live-odds-worker. And the
live-lens loop runs on BOTH workers writing the same aggregate, so a partial
deploy makes momentum **flicker** rather than be absent: whichever ticks last
wins. Publisher is on `06babca2`; refresh-worker is not.

**RETRACTED: "soccer box sections render 0 rows".** That 08-21 UI-audit finding
was a MEASUREMENT ERROR — table sections carry `table_rows` and set
`"rows": []` by design. Verified on production 2026-08-21 23:29Z: Goals 3/2/3/1
rows, Match stats 12 rows on all four fixtures, ARS squad 23. The cards were
always rendering. Two commits (`0aaf71f0`, `94a53639`) were shipped against a
symptom that never existed; neither is reverted (both are defensible in
isolation) but neither was needed.

**Home's cost is a CACHE MISS, not per-game compute** `[measured 2026-08-21
23:2xZ]`: 22.8s miss vs 1.03s hit on the same route, minutes apart.
`MLB_GAMES_STAGE_MS` stage timing is deployed (`8a7b2407`) and UNREAD.


**Live gates 1/2/3 work.** `[measured 2026-08-21 19:23Z, lane
soccer-board-mlb-parity]` Four live matches, on a board built AFTER the deploy
(checked, not assumed). Gate 2: 1144 rows considered, 58 live-projected,
240/240 snapshot rows indexed. Gate 3: reaching, and withholding 19/19 by
`no_two_sided_market_price` — a NAMED refusal, not a bare zero. Every live
probability moved off its pregame value (Arsenal 0.79 → 0.9125 after 1-0).

**The all-day zero was ONE SHADOWED IMPORT.** `live_lens_loop.py` raised
`UnboundLocalError: write_json_file` for mlb AND soccer — a conditional
function-local import in a WNBA branch bound the name local for the whole
function. NO live-lens snapshot was written for ANY sport. Three consumers
looked broken. Fixed `99e56561`, static regression test added.

**SOCCER PRICES ARE NOT CAPTURED DURING PLAY** `[2026-08-21]` —
`soccer_{league}_odds`/`_props`/`_picks` are `phases=("pregame",)`. The card's
`betting` block is frozen at the last pregame sweep, which is the SAME root
cause as gate 3's 19/19 withholding. A live-scoped refresh is written
(`b17c1999`, `_soccer_live_scope` + `--event-ids`) and **is NOT DEPLOYED**.
Props cost ONE CALL PER EVENT: unscoped 60s ticks are ~130k calls/day, scoped
to matches in play, single digits per tick.

**WNBA HAS NO GAME-LINES STEP** — only `wnba_oddsapi_props_job`. Identified
2026-08-21, NOT closed.

**Resumed sims were short a half's stoppage** `[held-out validated
2026-08-21]` — `espn_live_state` returns NOMINAL clock, so a resumption played
to the 90th minute and stopped, never simulating where 5.5% of goals occur.
Fixed `a27578bf`. Held-out (70 European matches, Aug 2026): bias eliminated at
all four cutoffs; **Brier 2.5 0.1454 → 0.1285 BETTER; MAE 0.6394 → 0.6665
WORSE** — adding real football adds variance. Brier at the line is the
objective; MAE of a point estimate is not.

**Momentum LEADS goals, computed from OUR OWN ESPN commentary**
`[measured 2026-08-21]` — pre-goal mean +1.141 vs control 0.000, Cohen's
d = +0.397 (n=76/638), goals EXCLUDED and the read strictly causal. No vendor
dependency, no id join. Published to `games[].momentum` and rendered on the
card — **never yet seen on a live card.**

**`second_half_shot_multiplier = 1.22` IS NOT WRONG.** Measured 57.1% ± 3.7pp
second-half goal share against its assumed 55–56% — inside one standard error.
Do not change it without a larger sample.
