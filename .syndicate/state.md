

## [substrate-rule] A CLAIM MUST NAME ITS SUBSTRATE, AND THERE ARE THREE — the standard's §3b was widened and strengthened at the same time `[2026-09-02, lane m625-standard-substrate-label, commit 6211bdf9, NO DEPLOY]`

`model_engine_standard.md` §3b used to say the substrate "must be Render", full
stop. It now names three, because the invariant is **CHECKABILITY, not
remoteness** — every incident behind the old wording came from a mirror that was
PARTIAL and whose partiality was INVISIBLE.

- **`render`** — the served payload, `/api/ops/artifacts/*`, the live env-vars
  API. The ONLY substrate that answers *what is true right now*.
- **`mirror:<manifest_id>`** — admissible only when the day was synced by
  `mirror_manifest.py`, `verify --date <D>` passes **TODAY**, and the question is
  in the reproducible class. **Cite the id.**
- **`checkout`** — `data/**` in git. Still never a claim.

**A LOCAL RUN IS EVIDENCE ABOUT THE CODE, NEVER ABOUT THE DEPLOYMENT.** A
verified mirror can say what an input contains and whether this code reproduces
production's artifact from it; it can NEVER say whether production has that file
now, whether the output reaches a user, whether a job is enabled or ran, or
which commit is deployed. The dividing line is §3b's own worked example: NCAAF's
local **0 games** against production's **16** was a question about what
production PRODUCES.

**The 2026-08-18 user directive is preserved verbatim and marked unchanged.**
This ADDED one admissible case; an unverified local read is still not a claim.

Also fixed, because `#625`(2) had made them stale the same day: §3 and the gate
requirements said "allowlisted in `HOT_ARTIFACT_PATTERNS`" when there are now
two lists; and the "report UNMEASURED for a local checkout" rule now
distinguishes a verified mirror from a checkout — **and a gate that cannot tell
the two apart must assume checkout.**

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
opposite: it is trivially true when sections are titled by their DATE.

**THIS FILE WAS SPLIT `[2026-09-03, scripts/split_state.py]`.** It reached
746,526 B / 176 sections and no session reads that. What is left here is the
cross-cutting material plus the **`[subject-index]`** table at the bottom:
every subject, and which file holds it. The bodies live in
`state_<domain>.md` — mlb, soccer, football, basketball, venues, board,
board, ui, layer2, portfolio, worker, model, ledger, and the two venue
integrations polymarket and kalshi.

**Read state.md first, then open only the part you need.** Adding a subject to
a part means adding its index row: `py -3 scripts/split_state.py --reindex
--apply`. Plain `--apply` refuses once the index exists.

**ONE SUBJECT, ONE SECTION IS NOW GLOBAL — it spans the parts.** A slug in two
different files is the same stacking failure and is worse, because two files
are less likely to be read together than two sections of one file.
`state_key_check.py` pools slugs over every part and is what catches it; the
commit guard checks each file on its own and CANNOT see a cross-file stack.
Compaction was tried first and measured: only 0.2% of the file was reclaimable
superseded prose. This file is not bloated, it is big, because it is live
current truth.

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

- **2026-09-05 — COMPACT `learnings.md`, THEN RAISE ITS ALARM 400000 -> 460000.**
  Asked directly, with the numbers, and BOTH were done in that order.
  `compact_learnings.py --keep-from 2026-09-05` reclaimed **64,557 B**
  (462,498 -> 397,941) by moving 40 entries' bodies to `learnings_evidence.md`;
  headings conserved **896 -> 897, zero lost** (the +1 is a peer appending
  mid-run), verified independently of the tool because the diff reads as 1,201
  deletions on a shared file.
  **A correction I owed the user and had given backwards:** I said compaction
  would leave the file ~1,800 B OVER. It went UNDER by 2,059 B — I had compared
  against the tool's default `--cap 280000`, not the alarm's real 400,000.
  The raise was still right, for a different reason than the one I gave: a 0.5%
  margin against a measured **~6 KB/hour** of fleet growth is a red light again
  within the hour, which is the failure `session-start.sh` already names
  ("a warning that is always on is one nobody reads").
  Consequence to hold onto: **compaction is now nearly spent** — 369 of 432
  dated entries are ALREADY stubs and re-moving them reclaims zero — and what
  this alarm measures is the fleet's mistake-to-rule conversion rate
  (~40 new FORBIDDEN-class rules in 36 hours). **The next lever is neither a
  raise nor a compaction.** Reasoning is in the hook comment, not only here.

- **2026-08-25 — REAL EXECUTION CAPS: bankroll $1000, Kalshi $50/day,
  Polymarket $100/day, $10 max order, 10 orders/day per exchange, 15 combined.**
  Asked directly, with the numbers. Bankroll was already `$1000`
  (`portfolio_settings.DEFAULT_BANKROLL_UNITS`, a 2026-08-22 decision, no code
  change needed). Everything else is now the code default in
  `execution_guard.py` (PR #62, `210844950`) AND the live `live-odds-worker`
  env vars (`SYNDICATE_EXECUTION_MAX_DAY_DOLLARS_KALSHI=50`, `_POLYMARKET=100`,
  `_ALL_VENUES=150`) — **verified live in production 2026-08-25T19:35Z**, both
  venues' `caps={...}` lines match exactly.
  Consequence to hold onto: **the env vars had drifted from the stated policy
  before this fix** — production was running a flat `$40`/day cap identical
  for both venues (`$80` combined), the leftover of an earlier
  "small numbers a first funded week should survive being wrong about" phase.
  The user caught this by asking "are you sure this is set correctly now?"
  rather than accepting an earlier report that the code change alone was done —
  a code-default change is NOT sufficient to fix a service with an explicit,
  contradicting env-var override; verify against live logs, not the diff.
  The per-venue day-dollar cap is a **day-SPEND cap standing in for real
  funded balance**, not a running capital-availability ledger — nothing here
  subtracts an open position's stake from tomorrow's budget.

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

- **NFL / WNBA / NCAAF CLV CLOSES EXIST AS OF 2026-09-21 (web `de6da1b7`)** -- from the per-book quote
  log (`book_quotes`), for any market odds history lacks: 09-20 nfl 3,056 / wnba 4,116 resolved,
  ncaaf 09-19 board 5,346, all same-book; mlb's 4,947 history rows byte-identical. Unstarted games and
  in-play openings are refused by name (`not_started`, `opened_in_play`) on EVERY close source --
  `a720941d`, live on all three services (web `00cc059b` 19:25:27Z): mlb 2026-09-21 report read
  19:27:11Z had 0 resolved rows for unstarted games (971 of 1,102 before). Lane
  `clv-close-from-book-quotes`, CLOSED 2026-09-21.
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
- **Lane LOANS are honoured by all three lane hooks as of 2026-10-08** (`a99d1c1c`). `lane-guard`, `scope-guard` and `lane-postwrite-check` judge a `(LOAN from <lender>` on the borrower's `Files:` line against origin/main + local additions, and only when the lender truly holds the path (`lane_claims_source.honoured_loan`). Verified live in the primary tree: a borrower is allowed, a non-borrower is blocked; a self-granted loan still blocks/warns (tests).

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
| MLB live game-line model | **TOTALS/SPREADS AND FIRST5 ARE NOW SCORED, POOLED AND REPORTED `[2026-09-28, MEASURED, lane gameline-spread-total-scoring]`.** Totals/spreads were scored since contract 3 (09-08) but never pooled or printed; `pool_live_gameline_trend.py` now pools them per family (headline `model_minus_line_mae`) and per `--sport`. Post-fix, fresh cut, 09-07..09-27: totals line closer by 0.231 runs (245 games), spreads model closer by 0.138 runs (244), all under-powered; 09-09 is a permanent totals/spreads gap (rows never ledgered); nothing before ledger v5 (`5876bbc9`, 09-06 late) is scoreable. first5 h2h OBSERVATIONS (recorded since 09-08, never published) scored for the first time by re-score: 12 dates / 134 games, paired Brier -0.00221. The board build scores MLB segments as `live_gameline_score.segments` since refresh-worker `15ddf78e` (live 2026-09-28 16:09:11Z) via StatsAPI `/linescore` for FINAL games; first production reading OWED on the first 2026-09-29 final. first5 totals/spreads, first1 and first3 carry NO model forecast in the ledger -- producer gap. **PUBLICATION IS ON AGAIN FOR MLB `[2026-09-16, MEASURED, user decision, lane board-category-gates]`.** `SYNDICATE_LIVE_GAMELINE_PUBLISH_DISABLED_SPORTS` was DELETED from refresh-worker and re-injected with `b59887db` (live 18:50:42Z); MLB `LIVE_GAMELINE_BUILD` builds with priceable > 0 went from 0 of 20 before to 3 of 11 after, with 4 games in play (`deploys.md` 18:45:03Z). HISTORY, superseded 2026-09-16: from 2026-09-10 `SYNDICATE_LIVE_GAMELINE_PUBLISH_DISABLED_SPORTS=mlb` was set on refresh-worker, and `6c727968` had been live since 13:44 CDT. Every MLB live game-line row that reaches pricing is refused `model_edge_publishing_disabled_for_sport` on h2h, spreads and totals, with `edge_pp`/`prob_std_err` still recorded and the ledger still written (served board at 13:45 CDT: 4 refused, 0 priceable, `written 7`). f5c2468a's misplaced `sport=` had aborted the whole MLB and soccer attach from 2026-09-09 03:58Z until then (153 `BOOK_GRID_LIVE_GAMELINE_FAILURE`). **Non-MLB isolation `[2026-09-12, MEASURED on the per-record ledgers, lane mlb-stop-publishing-edges]`: SOCCER PROVEN** — 305 priceable rows after the switch (09-11 29 of 57, 09-12 276 of 928), 0 refused by it; a disabled sport reads 0 priceable by construction. **NCAAF UNMEASURABLE** — 0 priceable on every date read, before (09-05, 09-06) and after (09-11, 09-12), all refused upstream of the switch, so its zero refusals are NOT evidence. **WNBA has no ledger** (404) until its 09-17 return. MLB 09-12 is the positive control: 6 rows refused by name, 0 priceable. **`pregame_home_win_prob` IS POPULATED IN PRODUCTION `[2026-09-08, MEASURED, lane mlb-pregame-baseline-feed]`.** It had been null on EVERY MLB ledger row since it shipped in `4d20ea00` — 0 of 2872 v4 and 0 of 531 v5 rows over 08-20..09-07 — while `progress_fraction`/`inning`/`outs`, added in the SAME commit over the SAME hops, were 2872/2872. TWO defects in `_build_game_lens`: (a) it read `baseline_probs.get("homeWin")` while the only producers write `home_win_prob` — those camelCase strings occur at exactly three sites in the vendor tree and all three are READS, no writer; (b) fixing (a) alone still yields None, because `card["predictions"]` has no `live` key and `live_gameline_from_lens` returns the FIRST `live_mc` row, which the lane order makes `live`. Mapped `live` -> the FULL-GAME baseline. **Only the end-to-end test caught (b); four unit tests were green with it broken.** Live on **live-odds-worker** as `57052784`, 20:44:27Z. **MEASURED: 178/178 priced full-game h2h rows non-null, 10/10 games, 32 distinct values, against a pre-fix control of 0** (2026-09-07, same script and predicate). Detail: `deploys.md` `## 2026-09-09 01:40:53Z`. **A FALSE `FALSIFIED` WAS PUBLISHED AND WITHDRAWN MID-VERIFICATION** — the instrument scored every `game_state: live` row, and the 109 it found were all `first5` segment REFUSALS carrying no h2h lane; the field is legitimately null on those. Restrict to `market=h2h` + `segment=full` + non-null `model_home_win_prob`. **THE MODEL STILL LOSES TO THE MARKET, AND THREE FIXES ARE NOW CLOSED `[2026-09-08, MEASURED over 252 games / 19 dates, recomputed from the raw h2h ledger against StatsAPI finals]`.** The scorer-era split does NOT bind a recomputation that filters `market=='h2h'` itself, so the poolable sample is **252 games / 19 dates, not 121 / 9**. Fresh cut (<=120s): **pooled +0.00905, bootstrap-over-games CI [+0.00154, +0.01686]** — excludes zero, so on the raw ledger this is NO LONGER under-powered. Error is **monotone in the model's own disagreement**, in BOTH eras independently: <=2pp -0.00001, 10-20pp +0.02178, 20pp+ **+0.12433**; `>10pp` +0.03432 CI [+0.00650,+0.06077], model worse on 14 of 18 dates (p=0.0154). **Murphy decomposition says the deficit is RESOLUTION, not calibration:** reliability gap +0.00055 **CI spans zero**, resolution gap +0.00790 CI [+0.00065,+0.01511], resolution 92-98% of the gap at every bin count. The model is MORE spread (sd 0.28231 vs 0.26601) and LESS informative. **So recalibration is capped at 6.5% of the gap** — perfect calibration lands 0.17711 vs the market's 0.17020 — which explains the LOO failure already on file. **Segment-wise encompassing regression finds NO subpopulation worth gating to:** 2 of 12 cells excluded zero in-sample (`|lead|4+`, `5-10pp`) and NEITHER survived leave-one-date-out; the blend is significantly WORSE out of sample (+0.00371, CI [+0.00116,+0.00646]). **Recalibration, subpopulation gating and model/market reweighting are all closed. What remains is raising RESOLUTION (better live-state inputs) or not publishing model-vs-market edges — a product decision, not a measurement.** **ACCUMULATION 2026-09-03 [scheduled task `live-gameline-accuracy-snapshot`] — THE LIKE-FOR-LIKE POOL RESTARTED AT THE SCORER BOUNDARY AND IS 5 DATES / 54 GAMES, pooled diff -0.00266 (model 0.16976 vs market 0.17243), measured 2026-09-03 14:40 CT via `pool_live_gameline_trend.py`. IT MOVES EVERY NIGHT — RUN THE TOOL, DO NOT QUOTE THIS.** **SUPERSEDED (kept for the record): the 2-date / 28-game reading below — model 0.15110 vs market 0.16007, -0.00897, from the 4-of-29 `scored_markets` rows covering 09-01/09-02 only — rested on the stamp test that RESOLVED below disproves; 08-30 and 08-31 belong in the pool.** The 14-date / 171-game pool (model 0.26698 vs market 0.22798, **+0.03900**) **MIXES SCORER VERSIONS AND MUST NOT BE QUOTED AS A RESULT** — it is better than the retracted +0.06104 for the same reason that figure was retracted, not because the model improved. Per-date `priceable_only`: 09-01 **-0.00181** (n 317/317), 09-02 **-0.01614** (n 275/275); fresh (<=120s) **+0.00077** and **-0.00105**, i.e. PARITY on the only prices anyone could take. **DO NOT attribute the sign flip to the 09-01 staleness gate — NO A/B WAS RUN.** **RESOLVED 2026-09-03 — 08-30 AND 08-31 WERE BUILT BY THE POST-FIX SCORER AND ARE POOLABLE.** `scored_markets` is a SNAPSHOT-SCRIPT stamp, not a scorer stamp, so their missing stamp proved nothing. Settled by re-running `scripts/score_live_gameline_offline.py` (which imports the post-fix `score_ledger_records` verbatim) against production and taking the ratio production-scored-rows / h2h-only-rows: **08-26 14.74x, 08-27 7.46x, 08-29 7.46x vs 08-30 1.17x and 08-31 1.01x** — pre-fix dates fold in totals+spreads, these two do not. Same-ledger control: `records_considered` matches production EXACTLY on 08-26/27/29/30/31 (10406, 3030, 5554, 5904, 8161), so only the SCORED SUBSET differs. 08-30 reproduces exactly (n=249, briers 0.13400/0.19644). **08-28 is NOT evidence either way** — its capture recovered 4 of 15 games (`considered` 312 vs 6534) and its ratio 0.49 is a degenerate capture, not a scorer signal. **THE POOL IS THEREFORE 4+ DATES / 53+ GAMES** — 0.17279 vs 0.17497, **-0.00218** as of 2026-09-03 (was 2 dates / 28 games, -0.00897). **DO NOT QUOTE THAT NUMBER AS CURRENT: it moves every night.** `**THE `priceable_only` CUT IS NOW PERMANENTLY EMPTY FOR MLB, AND IT DIED SILENTLY `[2026-09-12, MEASURED on the per-record ledger, lane live-gameline-accuracy-cut-repoint]`.** Downstream consequence of the publication switch at the top of this cell. `priceable` is a PUBLICATION verdict, not a measurement-validity one, so when MLB edge publishing went off no row is marked priceable any more: ledger 2026-09-11 = 13,187 records, `priceable=True` on **ZERO**, `model_edge_publishing_disabled_for_sport` on 245; 2026-09-09 = 12,967 records, **41** priceable, that reason ABSENT. **The pool did not shrink to match — it FROZE** (`best_per_date` skips a date whose cut has no brier), still reading "12 dates, 146 games" unchanged and unmarked, and would have re-printed that forever. `priceable_only` is therefore a CLOSED series ending 2026-09-10, final reading **-0.00049 / 146 games / 12 dates**; do not extend it. **The AUTHORITATIVE command is now `py -3 scripts/pool_live_gameline_trend.py --era each --cut fresh_quotes_only`**, which reads **+0.00816 / 306 games / 25 dates** (2026-09-24, and it MOVES — run the tool, do not quote this). **THE 08-30/08-31 HOLE IN THAT CUT IS CLOSED, AND ITS CAUSE GENERALISES `[2026-09-24, MEASURED, lane live-gameline-rescore-0830-0831]`:** those two dates had outcomes but contributed NOTHING, and no re-capture could ever fix it, because **the board RE-SERVES A STORED SUMMARY for a past date rather than recomputing** — proof: the 09-23 re-capture of 08-30 carries `scored_markets` yet `fresh_quote_seconds=None`, which the scorer sets UNCONDITIONALLY to a constant. They are the only two dates summarised inside the ~47h window between `75cf9aec` and `4d20ea00` (the commit that ADDED the cut). The DATA was never missing: `quote_age_seconds` is on **100%** of records (5,904/5,904 and 8,161/8,161), stamped since `7e1d0cac` 2026-08-15. `scripts/rescore_live_gameline_date.py` (`48a5eace`) re-scores a date's ledger with the CURRENT scorer and REFUSES unless it reproduces the retained `all_records` briers to 5dp AND both row counts — both dates verified EXACT. Recovered: 08-30 **-0.04291** (n=117/117, 14 games), 08-31 **+0.04092** (n=366/366, 11 games). **08-31 needed the BOARD's population, not the fullest:** StatsAPI has 12 finals, the board scored 11, and a leave-one-out search identified the one game the board never saw — `824314` BAL @ COL, first pitch 00:1xZ; scoring all 12 gives +0.03591 over 458/412, plausible and wrong. **So any cut is frozen for every date summarised before the cut shipped. CENSUS DONE SAME DAY, AND THE HOLE IS 5x BIGGER THAN THE TOOL REPORTED `[2026-09-24, MEASURED over all 80 history rows]`:** `fresh_quotes_only` is absent on **10 FURTHER dates, 08-20..08-29, 118 games** — and `coverage_gap` never named them because they are PRE-FIX era, where the tool prints `No date in this era carries cut=... Nothing to pool`, which reads benign. `by_quote_age` has the identical 10-date hole (same commit `4d20ea00`). `all_records` and `last_per_game` are frozen on NO date. `priceable_only`'s 5 empty dates (09-11..09-15, 58 games) are the publication switch above, a DIFFERENT cause. **A SEPARATE AND LARGER GAP, NOW FIXED FOR FUTURE DATES `[2026-09-24, `b9b38221`]`: six scorer outputs were never persisted by the OBSERVER at all, on every date** — `point_forecast`, `point_forecast_markets`, `by_quote_age_cumulative`, `quote_age_absent`, `unmeasured`, `segment_actuals_supplied`. `point_forecast` is contract 3 (`d3492bb4`, 2026-09-08, totals/spreads scored on the POINT FORECAST against the line): **0 of 80 rows carried it**, so the totals/spreads measurement had NEVER entered the retained history for any date. **CAUSE: DRIFT BETWEEN TWO COPIES OF ONE ALLOWLIST, not a missing capability** — the worker twin `live_gameline_accuracy.build_row` had retained all six since `d3492bb4`; the local `snapshot_live_gameline_score.py` held a second hand-written copy that was never updated. Falsified on `origin/main` by driving ITS script with a payload carrying all seven keys: **dropped 7 of 7**. Fixed at the choke point — one `RETAINED_SCORE_KEYS` constant both captures read, since a test comparing two lists would be a third place to forget. **FIRST RETAINED READING, 2026-09-23 / 16 games:** spreads `hit_rate` **0.61373**, `model_mae` **1.86768** vs `line_mae` **1.93884** (model beats the line); totals `hit_rate` **0.33060**, `model_mae` **2.76961** vs `line_mae` **1.80287** (model much worse, against a 0.5 baseline). ONE DATE — not a verdict, and `independent_unit` is games, so n=16. This only helps dates captured from 2026-09-24 on; every earlier date's `point_forecast` is gone unless re-scored from its ledger. **ATTEMPTED AND PARTLY RECOVERED `[2026-09-24, `f0a9a6a8`]`: 7 of the 10 dates / 97 games are now in the pool, and the OTHER THREE ARE THE INTERESTING RESULT.** The 10 early ledgers are intact and retrievable (GET verified on 08-20 3,899,726 B / 08-26 8,313,889 B / 08-29 4,551,522 B; `quote_age_seconds` on 100% of h2h rows). **But the BOARD's population for these dates is UNRECONSTRUCTABLE, so they can only be scored on StatsAPI's.** The pre-fix scorer (`ad4bc5c6`) keys finals on `game_pk` OR `event_id` off the board GRID, and `findings_2026-09-08` measured that the served grid no longer rebuilds that index (0 entries against the server's own `finals_seen: 2598`). Replayed on 08-29: `records_considered` matches **5554/5554 exactly** and it still yields 15 games / n=5380 against the retained 16 / 4917. That is also why the strong gate cannot serve these dates — their retained `all_records` measures the pre-fix bug, so the current scorer will not reproduce it BY DESIGN. The weaker anchor `--expect-records-considered` proves only that the same LEDGER was scored and REFUSES unless `--finals-population statsapi` is passed. **Recovered (each anchor exact, each paired diff reproducing `score_live_gameline_offline.py` to the last digit on an independent code path): 08-21 +0.02169, 08-22 +0.02749, 08-23 +0.01721, 08-25 +0.00565, 08-26 +0.00205, 08-27 -0.01045, 08-29 -0.00120.** **NOT recovered, by the gate rather than by omission: `08-24` anchors fine but has ZERO rows at the 120s cut** — genuinely empty at the fresh cut, not frozen, and now the pool's sole named coverage gap; **`08-28`** fails the anchor (best capture saw 6,466 records mid-stream vs 6,534 now); **`08-20`** fails it the other way, and **DIAGNOSED 2026-09-24: NOTHING SHRANK — `/api/ops/artifacts/stream` SERVES A STALE SNAPSHOT, and this is a standing hazard for every past-ledger read.** The board artifact for 08-20 (`generated_at` **2026-08-22T01:28:22Z**, which is what the 08-27 bulk capture read) counted **4,817**; the stream serves **4,809** today. Mechanism, from the code rather than inferred: the ledger is WRITTEN on refresh-worker's disk and the board is BUILT there (`ops.py:2976` comment; `render.yaml` gives only refresh-worker the intelligence-state loop), so the artifact's count is the WORKER's file. `api_ops_artifacts_stream` resolves `target = data_root() / relative_path` and `send_file`s it — **the serving service's OWN disk, i.e. web's**, which holds the ledger only because something pulled it (`artifact_publisher.py:1277` allowlists it as STREAMED, explicitly NOT swept, and notes "allowlisting only PERMITS a push; something has to make it"). `append_records` opens `"a"` and has only a CAP, never a delete, so the writer cannot shrink a file — confirmed by reading it. The served 08-20 file is internally clean: 4,809 valid records, **0 duplicate lines**, `recorded_at` monotonic in file order, single date. **NOT DETERMINED** (needs the worker's disk, which has no HTTP): whether web never received the last 8 appends, or a later pull overwrote web's copy with an older snapshot. Late appends are real — 08-21's ledger carries `recorded_at` up to **2026-08-23T01:20Z**, two days past its slate. **Scope: 1 of ~16 dates.** The 08-27 bulk capture wrote seven dates in one run and six match today's stream EXACTLY (08-21 8070, 08-22 4223, 08-23 7644, 08-24 1718, 08-25 6534, 08-26 10406); only 08-20 differs, which is why a two-disk story needed the per-date evidence and not just the architecture. **OPERATIVE RULE: a past ledger fetched from `stream` is NOT necessarily the file the board scored. Anchor every re-score on `records_considered` (or exact reproduction) and REFUSE on mismatch** — `rescore_live_gameline_date.py` already does, and that is the only reason this was visible at all. **THE POOL NO LONGER AVERAGES TWO SELECTIONS SILENTLY:** `pool()` splits on `finals_population` (absent reads as `board`, correct by construction), so the headline **403 games / 32 dates +0.00873** always prints as **board 306 games +0.00816** and **statsapi 97 games +0.01052**. Neither side has won on either population. And they are not unmeasured: `scripts/score_live_gameline_offline.py` + the 252-game / 19-date recomputation recorded above already covers that window (fresh cut +0.00905, CI [+0.00154, +0.01686]). **That is a DIFFERENT POPULATION from history's 306 games / 25 dates — do not splice them.** HISTORY: this cut read +0.00460 / 134 games / 11 dates (2026-09-12, PAIRED — the first reading of +0.00571 was an unpaired artifact: the pool subtracted `model` over all its rows from `market` on dates where the model scored rows with no market price; fixed by lane `gameline-trend-paired-pool`) — still under-powered, neither side ahead. That cut conditions on quote age, which `priceable_only` never did and `learnings.md:854` requires. Fresh rows on 09-11 are 531, ALL `segment: full`, 114/114 over 14 games — not segment-contaminated. The tool now EXITS 3 and prints `HEADLINE CUT IS STALE` when the newest date with outcomes carries no data for the requested cut (`bad972ff`, `c7852ac8`; offline tooling, NOT deployed, needs no deploy). This prose is not authoritative; run the tool — it splits by scorer era and `pool()` RAISES on a mixed-era set, so a cross-boundary figure is unreachable rather than merely discouraged. Still NOT a result: the two added dates disagree violently (**-0.06244** on 08-30 vs **+0.09183** on 08-31, 14 and 11 games), so per-date noise dwarfs the pooled difference. Backfill recovery for 09-01 is DETERMINISTIC — two board builds 16.5h apart wrote byte-identical rows. **`history.jsonl` IS TRACKED AND ON `main` `[2026-09-03]`** — verified by reading 29 rows / 14 dates (08-20..09-02) back out of `origin/main` itself, not by a push exit code. It had been untracked since 08-20 and the rows are **NOT regenerable** (each snapshots a board build that no longer exists), so the task brief's *"regenerated output, leave it uncommitted"* is WRONG for this file. Append-only by contract — never rewrite it in place to dedupe. The one-time landing narrative (cherry-pick onto `origin/main`, the 7-commit rebase, backup ref `backup/unpushed-main-2026-09-03` and its verified-nil deletion) is archived in `state_archive_2026-09-03.md`; its durable rule is now in `learnings.md` 2026-09-03, *"a line-level diff is the wrong instrument for a reworded ledger"*. **CORRECTED 2026-09-01 — THE n=98 / +0.07000 READING BELOW IS AN ARTIFACT OF A FIXED SCORER BUG AND MUST NOT BE QUOTED `[lane mlb-live-gameline-skill-audit]`.** Until `75cf9aec` (2026-08-30) the scorer compared totals `P(over)` and spreads `P(home covers)` against "did the home team win", so ~92% of the scored population was a category error. Proof by n: offline h2h-only scoring matches production EXACTLY on 08-30 (**249/249 rows, briers 0.13400/0.19644 identical**) and is 10-20x SMALLER on every earlier date (08-20: 156 vs 3,098). `reports/live_gameline_accuracy/history.jsonl` therefore pools across a scorer-version boundary; rows lacking `scored_markets` are NOT pre-fix by construction — that clause was wrong and is corrected above (2026-09-03): the stamp dates the SNAPSHOT SCRIPT, and 08-30/08-31 lack it while being post-fix. **WHAT IS ACTUALLY TRUE, measured over the RAW retained ledger (12 dates, 72,587 records, 157 games) against StatsAPI finals:** pooled over every quote age the model reads as PARITY (-0.00202, CI straddles 0) — but that is itself an artifact, because **27-30% of rows are priced against quotes older than 10 minutes** (p50 410s, p90 1,848s, **p99 74,997s**) and a stale price is a worse forecast, which flatters the model. On the FRESH cut (quote <=120s, the only prices anyone could take, n=2,574 rows / 147 games): **model Brier 0.18145 vs market 0.17049, diff +0.01096, bootstrap 95% CI over games [+0.00171, +0.02132], model worse in 98.9% of resamples.** So the model IS worse — by a QUARTER of the retracted figure, and for a different reason. **The loss concentrates where the board publishes:** on fresh quotes `|edge| >= 20pp` scores **+0.16305** (the biggest claimed edges are the biggest errors) and the first 45 minutes score +0.021, while the `priceable` rate was a flat 41-53% across the whole game with NO quote-age term. **RECALIBRATION IS NOT THE FIX AND WAS TESTED:** a 2-param home-lift + shrink looked clean in-sample (model mean 0.5178 vs actual 0.5412, sd 0.283 vs 0.253) and is WORSE out of sample (LOO 0.18388 vs 0.18145 raw). The encompassing regression on fresh quotes gives `+0.0975 +1.1246*logit(market) **-0.0391*logit(model)**` — the model carries no incremental information over the market at this n. 120-sim MC noise costs 0.00142 Brier and removing ALL of it closes only 12.7% of the gap. **SHIPPED AND LIVE `[2026-09-01, verified by CONTENT in `9a436fab`]`:** staleness gate at the join choke point (env `SYNDICATE_LIVE_GAMELINE_MAX_QUOTE_AGE_SECONDS`, default 600s, absent age REFUSES), `min_edge_pp` floor decoupling the publish bar from the sim count (default 0.0 = off), ledger v4 (inning/outs/`pregame_home_win_prob`), fresh-cut + `scorer_contract` provenance in the scorer, and `scripts/score_live_gameline_offline.py`. Commits `c01dabb1` (live in `417e19ed` 16:55:20Z) and `692214e0` (live in `9a436fab` 17:59:56Z) — **neither deployed by me; both were carried by OTHER lanes' deploys because they were on `origin/main`.** **The capability stamp is VERIFIED on a board with nothing to score:** MLB 18:01:09Z `{'pregame': 300}` and SOCCER 18:01:14Z `{'pregame': 39}` both serve `scorer_contract=2 fresh_quote_seconds=120.0`, where three hours earlier the identical branch served only `['enabled','finals_index','games_with_outcome','reason']`. **THE GATE ITSELF HAS NEVER FIRED IN PRODUCTION** — every sport on this path was pregame at 18:0xZ (`considered=0`, `withheld_by_reason={}`), so that empty dict describes the SLATE, not the gate; expected ~39.5% of live rows. Owed on scheduled task `verify-live-gameline-staleness-gate` (18:45 CT). Bound: 157 games; the clock was a WALL-CLOCK proxy because the ledger recorded none until v4. **The SUPERSEDED n=98 / +0.07000 (game-weighted +0.06104) reading over 8 nights 08-20..08-27 is archived in `state_archive_2026-09-03.md` — DO NOT re-quote it.** It is the scorer-bug artifact retracted above. **RETENTION IS NO LONGER A LAPTOP CRON `[2026-08-28, VERIFIED BY CONTENT]`**: `live_gameline_accuracy.py` records from the board build itself, deployed on both services at `8b8a6579` (refresh-worker live 15:59:38Z). The cron lost 7 of its first 8 nights — six disabled, one to Modern Standby suspending its python child 9h13m. **But NO row has been written in production yet** and the served counters are `null` until `#599` lands, so the worker-side path is DEPLOYED, NOT YET DEMONSTRATED. Lane `live-game-line-projection`. |
| Live-gameline collector (laptop cron) | **IT DOES NOT FAIL, IT GETS SUSPENDED — do not diagnose this as a missed cron `[2026-08-28, VERIFIED from this session's own transcript]`.** `live-gameline-accuracy-snapshot` fired on time 23:34:21 CT and issued its script call at 23:34:24; the tool result returned **08:49:37 the next morning, 9h15m13s later**, because Windows **Modern Standby** was entered 22:57:42 CT and not exited until 08:48:00 (Kernel-Power 506/507, one span, no wake between). By then the slate had rolled, so the run recorded `date=<next day>, games=0` — the write was DISPLACED onto the wrong date, not dropped. **The fire window fell inside standby on 6 of 10 nights (08-18..08-27).** Wake timers cannot fix it: AC=important-only, DC=disabled, nothing arms one. Judge the collector by whether a row EXISTS for the slate date, never by `captured_at`. `--date <yesterday>` (`cadfbe31`) recovers a displaced night; both nightly task prompts were hardened to stop the false alarm. |
| MLB 0-0 "FINAL" placeholder | **A 0-0 FINAL in a sport that cannot draw was passed through as an observed result `[2026-08-28, VERIFIED in production, FIX NOT DEPLOYED]`.** `is_final` (status text) and the score (`_side_score`'s seven candidates) are unrelated fields, so a FINAL status over an un-overwritten schedule placeholder read as a real 0-0. Measured on 08-27: `finals_seen=1462, finals_level=644 (44%)`, `games_with_outcome` **4 instead of ~15**, `no_final_outcome_for_game=1304`; same instant 08-26 read `finals_level=0`, 15 games. Not a time cutoff — HOU@NYY (23:05Z) kept its score, KC@TOR (23:07Z) did not. Fix `eca7e81b` suppresses it with a NAMED reason, keyed on `LEVEL_FINAL_IS_A_BAD_ROW` (allowlist — a 0-0 final is REAL in soccer/nfl/ncaaf and nulling it would re-break `a293bf14`). **THIS RECOVERS NO GAMES** — the scores are absent, not misclassified; it fixes the misreporting only. Owed: a deployed reading showing `finals_level` fall for 08-27 while 08-26 stays at 15. |
| MLB board `game.state` freshness | **CAUSE RELOCATED TWICE; THE THIRD IS UNMEASURED `[2026-09-04, lanes mlb-feed-live-terminal-refresh + mlb-final-state-mapping]`.** Symptom unchanged all day: 2026-09-03 had 9 MLB games, all 9 Final per StatsAPI, and `live_gameline_score` sees **7** — ATH@SEA and STL@LAD publish as `live`, and they are exactly the 2 that finished AFTER the 05:00Z midnight-Central roll. **TWO CAUSES EXONERATED BY MEASUREMENT, not by retraction.** (1) The wrong-slate live-lens overlay: real, fixed (`d77695ef`), and it was NOT this — before the gate it drove `live -> pregame`, and `build_finals_index` needs `state == 'final'`, so the game was skipped either way. Verified live: `rows_corrected` 187 -> 0 with `lens_date=2026-09-04 requested_date=2026-09-03`, while the same-date board still corrects 292 rows. (2) Feed staleness: the readers were fixed (`20221619`, final is terminal; the old predicate was INVERTED and never refreshed a cached LIVE payload) but that was not this either — `FEED_LIVE_REFRESH date=2026-09-03 ... skipped_final=9 attempted=0 failed=0`, i.e. **all nine cached payloads already read Final.** (3) **WHERE IT ACTUALLY IS, and no measurement has been taken:** the served status does not come from that map at all. `FEED_LIVE_STATUS` for all nine game_pks reads `present=True source_status_abstract='Final' is_final_predicate=True key_types=['int']` — both readers AGREE and the keying is int — yet at the same instant `/mlb/api/cards?date=2026-09-03` publishes `{"abstract": "Live"}` for those two and the 19:19:37Z board reads them `live`. `_source_status(None)` would give `Pregame/Scheduled`, so the consumer reads a DIFFERENT payload, not a missing one. **Suspect: `build_cards_page_context`'s source for a PAST date — artifact-backed vs inline-built.** REACHABILITY of the shipped fix is proven on the other date: `date=2026-09-04 ... no_cached_payload=16 attempted=16 succeeded=16`. A past date's board artifact IS rebuilt once per worker process (`_BOOK_GRID_LAST_RUN` is an in-process dict), so a RESTART is the only trigger and each deploy gives exactly one 09-03 build ~67s after boot. |
| MLB wrong-slate live-lens overlay | **FIXED ON `main`, NOT DEPLOYED `[2026-09-04, lane live-lens-date-gate]`.** `attach_live_game_state_from_lens` took `selected_date` and, for MLB, used it ONLY in a log line. There is ONE snapshot key per sport, always for `central_today_iso()`, and the grid join is by TEAM PAIR alone — so serving a past date applied TODAY's states to that date's rows, and MLB series repeat a matchup on consecutive days so it MATCHED rather than no-opped. Measured on the served 09-03 board: `lens_games: 16` (the 09-04 slate), `rows_corrected: 187`, `transitions: {'live->pregame': 187}` — 187 is exactly the ATH@SEA row count. A game Final for 28 minutes was published as `pregame 0-0`, and `live_edge_policy` reads `game.state`, so that re-opens edges on a settled market. **THIS DID NOT CAUSE THE MISSING FINALS** — the before-state was `live`, and `build_finals_index` requires `state == 'final'`, so that game was skipped either way; the cause is the row above. Gate is READ-SIDE ONLY: dating the snapshot is forbidden (`learnings.md` 2026-09-03, ~5.76 GB/day into a 256 MB keyvalue store at 86.8%), and the snapshot already carries its slate date. |
| `SYNDICATE_WEB_DYNO` blueprint drift | **RETRACTED 2026-09-04 — THERE IS NO DRIFT. I asserted one and it was an artifact of an UNPAGINATED API read.** Re-read WITH pagination: web `true`, live-odds-worker `false`, refresh-worker `false` (76 / 129 / **153** keys) — matching `render.yaml` exactly. My first read took one `limit=100` page of refresh-worker's 153 and reported the key ABSENT; `CLAUDE.md` warns to paginate this exact endpoint and I did not. **PROVEN FINE, not merely unproven** — independently confirmed from refresh-worker's own logs: `[mlb_cards] FEED_LIVE_PRUNE`, which sits behind `not _render_web_dyno()`, emits there every build (15:57:55Z, 15:59:32Z), and `board_contract_*`/`cards_context_*` memory samples likewise, while the web service emits none of the three. So `_render_web_dyno()` returns False on both workers and every gate behind it is LIVE. Nothing to fix; no deploy taken. |
| Worker-side score retention | **MERGED, NOT RUNNING `[2026-08-28, VERIFIED by content]`.** `74f026a9` moves retention into the board build (appends only when `games_with_outcome` improves), which removes the laptop and the midnight deadline. But `live_gameline_accuracy` is **`null` in the served payload** on both 08-27 and 08-28, and web runs `56e77588` — so it is on `origin/main` and not deployed (`autoDeploy = no`). **Until it deploys, the laptop cron is still the ONLY collector; do not retire the scheduled tasks.** **AND THE COLLECTOR HAS BEEN DEAD SINCE 2026-10-01 `[2026-10-05/06, MEASURED via list_task_runs]`.** `live-gameline-accuracy-snapshot` last DISPATCHED 2026-10-01T04:30:13Z and captured nothing after: its run froze 11 s in on a three-segment Bash compound and sat `status: running`, which blocks every later firing. Nothing was wrong with the script, the scorer or the cron — an unattended run cannot answer a permission prompt. Same signature on `archive-closed-lanes-0917` (15.9 s, dead since 10-01) and `soccer-inplay-693-verify` (13 s, dead since 10-02); at 20:41Z **0 of 8 enabled cron tasks had run in 3 h** and the freshest cron dispatch of ANY task was 72.3 h old. **RECOVERED AND CAPTURING AGAIN `[2026-10-06 ~17:20Z, MEASURED ON THE ARTIFACTS]`.** Frozen runs cleared and all three prompts hardened (one statement per tool call, a constant helper path `C:	mp\sched-task-scratch\<task-id>
un.py`); the approvals then landed on the task side. Proof is the OUTPUT, not a status field: `history.jsonl` **162 -> 167 rows** with 2026-10-06 ncaaf/soccer captures and a 10-05 soccer backfill; the archive task committed `0a8b3e44` (**32 CLOSED blocks archived**, owners idle 586-13755m, lanes.md 573,199 -> 470,851 B, dormant OPEN set 0 -> 19 / 92,045 B) and `b81748b4` (1 more); and on a later trigger two of the three tasks reported *already being started by their own schedule*. **THE OUTAGE NIGHTS ARE RECOVERED `[2026-10-06, `643a3a92`, lane gameline-history-backfill-0930-1004]` — and they needed no re-score.** The board had RETAINED a full summary per night (fresh cut, totals/spreads, first5), so `--date` re-served it and a plain backfill capture recovered the measurement; `rescore_live_gameline_date.py` would have exited 3 because it anchors on a retained `all_records` row and these dates had none. 10 rows appended (172 -> 182, 0 deletions): mlb 09-30/10-01/10-03/10-04, ncaaf 10-01/10-03, soccer 09-30/10-01/10-03/10-04. Pools: mlb 37 -> 41 dates (462 -> 472 games), ncaaf 11 -> 13 (198 -> 249), soccer 21 -> 23 (224 -> 226). **2026-10-02 is a PERMANENT gap** — `NO_DATA_FOR_DATE` and its ledger is HTTP 404 (MLB off-day between the Wild Card and Division Series) — as are ncaaf 09-30 and 10-04. |
| WNBA live game-line model | **SCORED FOR THE FIRST TIME `[2026-08-27, recovered]` — model BEATS the market, but the sample is thin and SELECTED, so do not bank it.** Pooled 08-20..08-26 `priceable_only` (n 101 BOTH sides): model Brier **0.11116** vs market **0.23620**, diff **-0.12504**. 18 `games_with_outcome`. **THE CAVEAT IS THE HEADLINE:** only **101 of 12,669** considered records survive — `record_carries_no_model_probability` accounts for 9,367 and two of the seven dates score n=0. That surviving 0.8% is the subset the model was confident enough to price, i.e. selected on the model's own confidence, so beating the market there is NOT evidence of general skill. Needs a full-population read before it means anything. Lane `live-game-line-projection`. |
| Soccer live game-line model | **SCORED AND NOW SOUND — DRAWS INCLUDED `[2026-08-27, backfilled]`. The model TRAILS the market, and fixing the draw bug did NOT rescue it.** Re-scored offline over the retained ledger + full `book_grid` artifacts for 08-21..08-26 using the fixed `build_finals_index(sport='soccer')`. **FIXED: 51 games, pooled `priceable_only` n 333 both sides — model Brier 0.31099 vs market 0.20332, diff +0.10767.** Against the same records under the pre-fix rule: 38 games, 0.31927 vs 0.20126, +0.11801. So the fix recovered **13 games (+34%)** and moved the gap only 0.010 — **the earlier soccer verdict was biased but not wrong**. Per-date diffs (fixed): 08-23 +0.09985 (n=159), 08-24 +0.06608 (105), 08-25 +0.02761 (9), 08-26 +0.21316 (60); 08-21 and 08-22 yield n=0 priceable. **BOUND — the artifact `rows` list is CAPPED at 6,000: 08-22 has `rows_truncated` 3,014 and 08-23 2,265, so those dates' finals indices are built from a truncated grid and their games are a LOWER BOUND.** Also note `finals_seen`/`finals_level` count ROWS, not games. Lane `live-game-line-projection`. |
| soccer team-name aliases (`2b0b708b`+`2e3265d7`) | **FIXED AND VERIFIED IN PRODUCTION, twice.** 13 aliases. `unmatched_match_rows` **2,587 -> 87** (-96.6%), `unmatched_fixtures` 12 -> 3, `rows_with_projection` 9,598 -> **10,684** of ~20,025 (48.0% -> 53.3%); belgian/epl/la_liga/mls/serie_a to exactly zero. `matches_in_source` 95 and `ambiguous_keys` 0 unchanged across the measurement, and the result HELD on a second reading 17 min later. Offline reachability: 0 of 13 fixtures join with the map emptied, 13 of 13 with it. Survivors are fixture-absence, not names: the board carries BOTH directions of `PSG v Rennes` (81 rows), and primeira_liga's Braga/Benfica are absent from the sim slate. |
| soccer LIVE edge (`edged=0`) | **CAUSE MEASURED 2026-08-22 18:04:56Z: a DE-VIG gap, not the pregame join.** `edge_withheld=133, edge_why={'no_fair_value_devig_failed': 133}` — 133 of 133 rows HAVE a pregame projection, which REFUTED the hypothesis the split was built to confirm. Soccer player props are one-sided, so `market_fair_prob_over` is never set; `attach_margin_model`'s replacement lands in `quote["fair_probability"]` (`layer2_board:1097`) while the live join reads `projection["market_fair_prob_over"]` (`live_projection_join:718`). The number exists and the reader cannot see it. **Bridging it is a PRICING decision** — `layer2_board:587-604` treats a `book_margin_model` fair as an ESTIMATE (12% prop hold vs 4.5% moneyline). NOT taken. |
| refresh-worker memory accumulation | **UPTIME-DRIVEN AND FULLY RECLAIMED BY A RESTART — measured twice on 2026-08-22.** 96.8% / 2,019MB "unexplained" -> **2.3% / 2.9MB** across the 19:29Z restart; and 90.9% -> 15.6% across the 17:04Z one. Not a leak that survives the process, and not any single job's working set. It re-accumulates over hours. |
| publisher sweep vs `_PUBLISH_MAX_BYTES` | **A FILE OVER THE 12MB CEILING HAD NO RETRY PATH — fixed `468faace`, SHIPPED AND UNPROVEN IN THE FIELD.** `publish_hot_artifact` withholds its checksum on failure because "a failed publish must be retried next sweep"; `_publish_skip_reason` refuses over-ceiling files BEFORE that function is reached, so the retry it names did not exist for the largest artifacts. The ceiling is NOT raised (its own comment forbids it; the sweep would then ship 51MB odds_history shards every cycle) — the bound is exempted only for paths a direct publish already FAILED on, and the exemption ends on the next success. Affirmative token: `SWEEP_REPAIRING`. A quiet log proves nothing. |
| MLB sim cadence vs deploys | **WAITING FOR "NO SIM RUNNING" IS UNBOUNDED.** Three `run_mlb_daily_sim_job` runs fired in 2.5 hours on 2026-08-22 (2-game 17:02, 15-game 18:51 taking ~26 min, 5-game 19:16) and a 4-game one started during the 19:38 deploy. The usable rule is to wait for an EXPENSIVE run, not for silence; `fingerprint_change` runs re-fire automatically. |
| production HTTP from a Claude session | **REACHABLE — corrected 2026-08-28.** `https://syndicate-an21.onrender.com/portfolio` returned `http=200` in `0.46s`, and a whole session of board verification ran off direct `curl` of the page and `/api/portfolio/live`. The previous line said UNREACHABLE (`connect_rejected`, 403 to CONNECT) and was steering sessions away from a check that works — the SERVED payload is the fastest way to falsify a UI claim. Render logs remain the only route for WORKER-side facts, which is a different thing. |
| soccer model | **LOSES to the market** — multiclass Brier 0.5875 vs 0.5737, worse in 8 of 9 leagues; errors sit on FAVOURITES |
| `#445` NCAAF season projections | FIXED, **not deployable until the season opens** (~08-29) |
| `#455` / `#456` | both FIXED; deploy state per service, check by content |
| game shape | contract for five sports, **n = 0** — emit still blocked |
| play-by-play coverage | **5 sports of 8** |
| WNBA pbp | **not a corpus** |

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

### Soccer / MLB / NCAAF join + cadence — MEASURED 2026-09-03..04 `[lane prop-join-yield]`

- **Soccer projection coverage is 57.0%, not 19.0%.** `_attach_projections_over_window`
  looped soccer per date while `board_enrichment` already resolves its 7-day slate
  window inside each call. Fixed `ac735931`. `considered` 146,034 -> ~21,000
  (**6.9x**), `unmatched_match` 67.4% -> **0.6%**. Counts quoted off the windowed
  line before 2026-09-03 22:19Z are inflated ~7x.
- **82% of unprojected MLB PLAYER prop rows are a name-join miss**, not an honest
  blank: `player_unmatched_name 191` of `player_rows_considered 1423` (13.4%)
  against `player_no_projection 43`. Counter shipped `c5e78549`.
- **`sim_view: none` conflated two states.** 3,306 rows carry a model number with
  no priced edge; they are `unpriced` since `36161e83`. Read `unpriced` before
  treating `none` as "the sim had no view".
- **NCAAF pregame quote cadence is ~640s, not ~12,948s.** Autorun `a9247011` +
  `SYNDICATE_ENABLE_NCAAF_LINES_REFRESH_AUTORUN=1` on live-odds-worker, 300s,
  game-day gated, 9 credits/run. **Measure on `quote_seen_age_seconds` (time since
  we LOOKED), never `book_age_seconds` (time since the price MOVED).**
- **FALSE FROM 2026-09-09 — corrected 2026-09-12 by lane `live-odds-worker-oom-loop`:** 80
  `oomKilled memoryLimit=2Gi` between 2026-09-09T19:43:39Z and 2026-09-13T00:07:50Z, 0 before,
  timed to the Kalshi daily-book write. Since `e332b531` (streaming writer, live
  2026-09-13T00:14:31Z, over `58736a69`'s arena cap + trim, then `77199c48` MLB live-lens
  payload fix at 04:43:50Z): VERIFIED 0 `oomKilled` / 0 unexplained exits from 00:14:31Z to
  22:31:19Z (22 h 17 m, events fully paged; designed recycles 11:15:00Z and 17:27:42Z, each
  matched to its `RECYCLING` line). That window was ENDED BY A DEPLOY (`637278e3`, 22:31Z)
  after only 5 h 31 m of the 09-13 live slate, so a >= 6 h kill-free LIVE slate is still OWED
  and the kills are NOT yet shown stopped under full load (`deploys.md` 2026-09-13 23:23Z)
  (`.syndicate/findings_2026-09-12_live_odds_worker_oom.md`). The claim below was true of
  2026-08-26..09-04 only and is kept for the record:
- ~~**live-odds-worker has NEVER been evicted.**~~ `evicted: false` on all 23
  `server_failed` since 2026-08-26; 20 are a scheduled self-recycle
  (`SYNDICATE_LIVE_ODDS_WORKER_MAX_UPTIME_SECONDS`, default 21600) that exits at
  ~82% of max. Nine days at 95-100% of 2GB, zero platform kills. The autorun costs
  10.4% -> 19.0% of samples within 50MB of the limit, with excursions NOT timed to
  its runs (median 154s into a 300s loop).

### NCAAF live lanes + the buy funnel — MEASURED 2026-09-04 01:2xZ `[lane prop-join-yield]`

- **NCAAF live rows reach the board.** `(live, live) 236`, `(live, pregame) 0`,
  after `9d106d11`. MLB rose 104 -> 1,272 on the same change.
- **`_refresh_layer2_live_state` RUNS ON WEB, NOT ON A WORKER.**
  `LAYER2_LIVE_RESTATED` fired 99 times on web in two hours and ZERO times on
  refresh-worker or live-odds-worker. Deploy the lane restatement to WEB.
- **Kalshi and Polymarket size ZERO positions, and it is not the venue.**
  `venue_priced` 276/534 and 264/383, balances funded, caps not binding. Every
  row is refused by `market_family_excluded` (274/180) or `no_model_edge_pct`
  (252/180). NCAAF is 173 of Kalshi's; it can NEVER buy, because
  `ncaaf/game_projections.py` nulls `edge_vs_market_pct` by design.
- **The `sport:family` staking exclusion is REMOVED** (`4484cae1`, live on refresh-worker 16:11:39Z 2026-09-16, user
  decision; `SYNDICATE_PORTFOLIO_EXCLUDED_FAMILIES` no longer exists; first plan after it held 12 MLB prop positions of 25) and **`SYNDICATE_PORTFOLIO_MIN_EV_PCT=0`**. Neither is a hidden throttle.
- **EV-only (market-fair) staking is allowed in EVERY sport** (2026-09-16, user decision): `SYNDICATE_PORTFOLIO_MARKET_FAIR_SPORTS` reads `mlb,nba,wnba,nhl,nfl,ncaaf,ncaab,soccer` on refresh-worker, live 20:58:44Z (`deploys.md` 20:53:17Z: plan 21:10:26Z `rows_in` 4117, 77 positions, 0 `no_model_edge_pct`, 0 skipped commits). A row with no sim edge is still REFUSED IN-PLAY (`in_play_market_fair`, 36 on that plan; user decision to keep). Any change to that env must run `scripts/portfolio_commit_input_checklist.py` with the env first: the 17:28Z attempt failed it and SKIPPED every commit.
- **Stored portfolio settings** (`POST /portfolio/settings` 16:29:39Z, read back `stored`): `max_positions` 150, `max_slate_exposure_fraction` 0.35, bankroll 1000, `min_ev_pct` 2.0. On the first plan after, the exposure ceiling ($350) bound and the position count did not (`deploys.md` 16:46:12Z).

### Order attribution is COMPLETE, and the dataset is EMPTY — 2026-09-04 02:2xZ `[lane prop-join-yield]`

- **Every order now records WHY.** `_LEAN_FIELDS` carries `model_edge_pct`,
  `ev_pct`, `sim_view`, `sim_line_gap`, `sim_probability_railed`,
  `side_picked_by`, `stake_fraction_ev_only`, `sim_share_of_stake`. Live on BOTH
  order-placing services from `ab42b221` (02:12:41Z / 02:17:12Z, 4.5-min
  ambiguous window). Per-order size ~1,184 B against a 5,000 cap = ~70% of the
  8MB refusal ceiling; still bounded.
- **IT RECOVERS NOTHING RETROSPECTIVELY and there is nothing new to read.** The
  638 settled bets pre-date the fields, and **no order has been written since
  2026-09-03T15:27:33Z**. The measurement is unblocked and unpopulated.
- **The board buys nothing because the model is not allowed to speak on most
  rows.** Both venue plans size 0: kalshi 534 rows -> 274 `market_family_excluded`
  + 252 `no_model_edge_pct` + 8 `below_min_ev_pct`; polymarket 383 -> 180/180/20/3.
  Venues are healthy (`venue_priced` 276/534 and 264/383, funded, caps slack).
- ~~**live-odds-worker memory is uptime-driven, not load-driven.**~~ **SUPERSEDED
  2026-09-12 (lane `live-odds-worker-oom-loop`): the kills since 2026-09-09 are a per-tick
  ANON transient (~0.5-0.9 GB, between samples) during `venue_daily_odds.record_daily_odds`,
  not uptime; kill-to-kill runs 10-13 min.** Original reading, true of 09-04 only: 100.0% at
  23:37Z, 66.0% at 02:00Z after a recycle. `evicted: false` on all 23
  `server_failed` since 2026-08-26 — nine days at 95-100%, zero platform kills.

## [subject-index] SUBJECT INDEX — every subject, and which file holds it

One subject, one section, ACROSS ALL FILES. `state_key_check.py` checks
that globally; a slug appearing twice anywhere is the stacking failure.
Regenerate with `py -3 scripts/split_state.py --reindex --apply` after
adding a subject, or add its row here by hand. Plain `--apply` REFUSES
once this index exists: re-splitting would orphan the parts.

| subject | title | file |
|---|---|---|
| [substrate-rule] | A CLAIM MUST NAME ITS SUBSTRATE, AND THERE ARE THREE — the standard's §3b was widened and strengthened at the  | `state.md` |
| [how-to-use] | HOW TO USE THIS FILE | `state.md` |
| [user-decisions] | USER DECISIONS `[2026-08-14 ~21:5x CDT]` | `state.md` |
| [open-problems] | OPEN PROBLEMS | `state.md` |
| [shipped-verified] | SHIPPED / VERIFIED — current status by item `[2026-08-18; replaces a dozen dated snapshot sections]` | `state.md` |
| [live-sha-authority] | LIVE SHAs — ASK THE SERVICE, NOT THE LEDGER `[2026-08-18 ~21:2xZ]` | `state.md` |
| [nba-betting-card-assets-404] | THE NBA BETTING-CARD CSS AND JS WERE 404 IN PRODUCTION -- FIXED, DEPLOYED AND VERIFIED ON THE SERVED PAYLOAD ` | `state_basketball.md` |
| [wnba-live-lens-directory] | THE WNBA LIVE-LENS READERS OPENED THE WRONG DIRECTORY — fixed and verified locally, NOT DEPLOYED `[verified 20 | `state_basketball.md` |
| [wnba-recon-producer] | `recon_games` WAS WRITTEN PREGAME AND NEVER REWRITTEN; the producer now exists `[2026-08-31, lane wnba-accurac | `state_basketball.md` |
| [wnba-consensus-price] | BOOK PRICES WERE AVERAGED ON THE AMERICAN SCALE; 43% OF CARD PRICES WERE IMPOSSIBLE `[2026-08-31, lane wnba-ac | `state_basketball.md` |
| [wnba-two-artifact-roots] | THE WNBA ARCHIVE HAS TWO ROOTS AND ONE OF THEM IS UNUSABLE — split on `source_path` before drawing ANY conclus | `state_basketball.md` |
| [wnba-winprob-inversion] | THE WIN-PROBABILITY INVERSION ADDED A RETURN FRACTION TO A PROBABILITY `[fixed + deployed 2026-09-01, lane wnb | `state_basketball.md` |
| [wnba-settlement-live] | WNBA SETTLES AGAIN — all three causes fixed, deployed and verified on the served payload `[verified 2026-09-01 | `state_basketball.md` |
| [wnba-instruments-all-zero] | THE THREE CAUSES, AS FOUND `[historical, 2026-08-31; all three now fixed — see above]` | `state_basketball.md` |
| [wnba-model-vs-board-mismatch] | THE WNBA SIM'S ONE EDGE IS THE MONEYLINE, AND THE BOARD BET IT TWICE ALL SEASON `[verified 2026-08-31, lane wn | `state_basketball.md` |
| [wnba-live-edge-is-leakage] | THE WNBA LIVE ENGINE'S +41% ROI IS AN ARTEFACT — no live line has ever been captured `[verified 2026-08-31, la | `state_basketball.md` |
| [wnba-execution-disconnect] | THE WNBA BOARD NEVER SEES THE VENUE IT TRADES ON, AND LAYER 2 NEVER SEES WNBA `[verified 2026-08-31, lane wnba | `state_basketball.md` |
| [wnba-game-lines-gradeable] | WNBA GAME LINES CAN BE GRADED — a player box gives the team score, and always could `[verified 2026-08-28, lan | `state_basketball.md` |
| [espn-egress-and-wnba-boxscores] | ESPN SERVES RENDER FROM ONE OF TWO HOSTS, and the WNBA boxscore had no producer `[verified 2026-08-26, lane ka | `state_basketball.md` |
| [wnba] | WNBA | `state_basketball.md` |
| [wnba-props-model-skill] | WNBA PROPS: NO MARKET BEATS THE BOOK; ALL FOUR ESTIMATORS + INJURY EXCLUSIONS LIVE ON | `state_basketball.md` |
| [wnba-game-state] | WNBA GAME-STATE AND FIXTURE COVERAGE — 2026-08-17 (lane `wnba-live-tier`) — **ARCHIVED 2026-08-19 to `state_ar | `state_basketball.md` |
| [wnba-fixture-identity] | WNBA fixture identity + the sweep ownership gap - VERIFIED 2026-08-17 — **ARCHIVED 2026-08-19 to `state_archiv | `state_basketball.md` |
| [wnba-sweep-ownership-gate] | WNBA SWEEP OWNERSHIP GATE + PHASE 2 AUTORUN `[collapsed 2026-08-18 from three 2026-08-17/18 snapshots; newest  | `state_basketball.md` |
| [basketball-smart-sim-engine] | NBA/WNBA smart-sim: allowlist, dead-gate fix, and an open staleness question — 2026-08-18 (lane `basketball-mo | `state_basketball.md` |
| [wnba-cards-fallback-recursion] | `_artifact_bundle` RE-ENTERED ITSELF 247 FRAMES DEEP AND REPORTED NOTHING — FIXED `[2026-09-03, lane wnba-card | `state_basketball.md` |
| [nba-model-skill-2025-26] | THE NBA MODEL IS LESS ACCURATE THAN THE PLAYER'S OWN AVERAGE, AND THE REASONS ARE MEASURED — as-of 2025-26 bac | `state_basketball.md` |
| [nba-layer2-projections] | NBA LINES CARRY THE MODEL ON LAYER 2 -- game lines LIVE and VERIFIED; props wired but no NBA prop quote exists | `state_basketball.md` |
| [board-freshness] | BOARD FRESHNESS AND STALENESS | `state_board.md` |
| [board-intelligence-engine] | BOARD / INTELLIGENCE ENGINE — structural facts, archived — **ARCHIVED 2026-08-19 to `state_archive_2026-08-19. | `state_board.md` |
| [locked-cards-retuned-no-autorun] | `locked_cards_retuned` HAS NO AUTOMATIC TRIGGER, ANYWHERE `[measured 2026-08-18]` | `state_board.md` |
| [board-overview-skipped-for-memory] | — VERIFIED 2026-08-27, refresh-worker `277062cd` | `state_board.md` |
| [board-overview-fix-verified] | — VERIFIED 2026-08-27, refresh-worker | `state_board.md` |
| [board-compute-attribution] | — VERIFIED 2026-08-28, refresh-worker `4805abe5` | `state_board.md` |
| [board-window-staleness] | — **CAUSE FOUND AND VERIFIED 2026-08-29. It is neither the queue NOR build cost — see `[week-scoped-board-wind | `state_board.md` |
| [week-scoped-board-window] | SCOPED, NOT BUILT `[2026-08-29]` | `state_board.md` |
| [board-model-edge-coverage] | 2026-08-30 — 82% of the board is UNSIZABLE, and every `_alt` market is 0% | `state_board.md` |
| [live-edge-basis-label] | `edge_basis` WAS WRONG ON EVERY LIVE MONEYLINE ROW, AND THE MEASUREMENT THAT CERTIFIED IT COULD NOT HAVE SEEN  | `state_board.md` |
| [coverage-report-artifact] | THE DATA-COVERAGE PAGE IS ARTIFACT-BACKED — worker publishes, web reads, and the cross-service read is PROVEN  | `state_board.md` |
| [combined-board-state-rows-lost] | THE COMBINED BOARD DROPS EVERY PERSISTED STATE ROW; ITS AGE IS TOMORROW'S SHORTLIST — FIXED, LIVE ON WEB `b6a0 | `state_board.md` |
| [board-per-date-freshness] | THE COMBINED BOARD DATES EACH WINDOW DATE ON ITS OWN; THE CHIP SHOWS TODAY APART FROM TOMORROW — LIVE ON WEB ` | `state_board.md` |
| [inplay-overlay-board-cadence] | THE BOARD'S IN-PLAY ROWS COME FROM THE BOOK GRID EVERY TICK, NOT THE SHORTLIST — LIVE ON ALL THREE SERVICES `[ | `state_board.md` |
| [intelligence-season-evidence] | INTELLIGENCE EXPLANATIONS NAMED METRICS THEY NEVER READ, AND THE READINESS GATE COULD NOT SEE THE DATA ROOT -- fixed on main `ced2618f`, NOT LOADED | `state_board.md` |
| [nfl-model-accuracy-backtest] | NFL GAME LINES AND PROPS LOSE TO THE CLOSE IN EVERY MARKET; THE PROP PROBABILITY CARRIES NO INFORMATION AT THE | `state_football.md` |
| [ncaaf-sim-view-coverage] | NCAAF GAME LINES CARRY A SIM VIEW ON EVERY MARKET; EDGES ARE BOUNDED BY THE 15-POINT CAP; STAKES STAY ON PRICE | `state_football.md` |
| [nfl-live-prop-capture] | NFL PER-QUARTER PLAYER PRODUCTION IS CAPTURED AND RETRIEVABLE — the allowlist alone moved ZERO bytes `[verifie | `state_football.md` |
| [nfl-prop-distribution-too-narrow] | THE NFL PROP MODEL'S SPREAD IS 0.21x-0.65x OF PLAUSIBLE, AND THE SPREAD NEVER GOT THE SMALL-SAMPLE TREATMENT T | `state_football.md` |
| [nfl-model-edge-suppressed] | NFL'S MODEL EDGE REACHES 3% OF THE SERVED BOARD, AND THE 15-POINT GUARD IS RIGHT TO REJECT IT `[measured 2026- | `state_football.md` |
| [nfl-board-projection-coverage] | NFL BOARD PROJECTION COVERAGE IS 100% `[measured 2026-09-04T23:19:34Z on the served payload, lanes nfl-project | `state_football.md` |
| [ncaaf-zero-orders-is-two-gates] | NCAAF ZERO ORDERS — SUPERSEDED 2026-09-11: the paper portfolio HOLDS NCAAF orders and they GRADE end-to-end; t | `state_football.md` |
| [ncaaf-team-registry-two-files] | THE RESOLVER READS THE *SNAPSHOT*, AND THE FILE BESIDE IT IS OLDER AND DIFFERENT `[measured 2026-09-03]` | `state_football.md` |
| [smartsim2-total-carrier] | THE ENGINE OVER-APPLIES TEAM QUALITY TO THE TOTAL IN BOTH FOOTBALL SPORTS, AND THE IN-ENGINE DIAL CANNOT REACH | `state_football.md` |
| [nfl-total-level-gain] | THE TOTAL WAS PRICED FROM A GAIN NOBODY FITTED, AND IT IS NOW SHRUNK AND VERIFIED ON THE SERVED BOARD `[measur | `state_football.md` |
| [nfl-rating-units] | NFL'S SIM COULD NOT TELL TEAMS APART. THE CAUSE WAS THE SCALE CONSTANT, **NOT** A UNITS DEFECT — that diagnosi | `state_football.md` |
| [football-smartsim2] | FOOTBALL (NFL + NCAAF) — smartsim2 runs on FOUR SCALARS `[measured 2026-08-18, lane football-model-owner]` | `state_football.md` |
| [ncaaf-calibration-profile-live] | THE PROMOTED NCAAF PROFILE IS LIVE, AND PROMOTING ONE IS A **CODE DEPLOY** `[verified 2026-09-05, render]` | `state_football.md` |
| [nfl-archived] | NFL — earlier closed work, archived — **ARCHIVED 2026-08-19 to `state_archive_2026-08-19.md`, verbatim.** | `state_football.md` |
| [football-model-leaks] | FOOTBALL — TWO MODEL LEAKS, BOTH FIXED `[verified 2026-08-19, lane football-model-owner]` | `state_football.md` |
| [football-board-defects] | FOOTBALL BOARDS — THREE DEFECTS SHIPPED AND MEASURED `[2026-08-18/19]` — **ARCHIVED 2026-08-19 to `state_archi | `state_football.md` |
| [football-engine-levers] | FOOTBALL ENGINE — THE PAYLOAD IS THE WEAK LEVER `[measured 2026-08-19]` | `state_football.md` |
| [ncaaf-chip-grid-join] | THE CHIP->GRID JOIN CALLED `teams_match` WITH ITS ARGUMENTS INVERTED `[measured 2026-08-29T18:43-18:59Z, web+w | `state_football.md` |
| [ncaaf-live-lens-state] | THE NCAAF LIVE LENS'S STATE BRANCH WAS UNREACHABLE, NOT EMPTY — **FIXED AND VERIFIED IN PRODUCTION** `[measure | `state_football.md` |
| [ncaaf-market-basis-edge] | NCAAF SERVES PICKS AGAIN — on a MARKET basis; the model gate is UNCHANGED and still denies `[verified 2026-08- | `state_football.md` |
| [ncaaf-board-surfaces] | NCAAF BOARD SURFACES — projections published, compact strip rebuilt, live lens state-aware `[measured 2026-08- | `state_football.md` |
| [ncaaf-props-live] | NCAAF PLAYER PROPS ARE ON THE BOARD — first capture in this platform's history `[measured 2026-08-27T03:07:03Z | `state_football.md` |
| [ncaaf-payload-vs-market] | THE ADVANCED-DATA PAYLOAD DOES NOT CLOSE THE GAP TO MARKET — a VALID null `[measured 2026-08-27, 693 paired ga | `state_football.md` |
| [ncaaf-readiness-2026] | NCAAF SEASON READINESS — the model is ready, the MARKET is not connected to it `[measured 2026-08-25, four day | `state_football.md` |
| [nfl-autorun-chain-order] | THE NFL AUTORUN CHAIN RAN THE FANTASY ARTIFACT ABOVE ITS OWN INPUTS — FIXED IN CODE, NOT DEPLOYED `[measured 2 | `state_football.md` |
| [ncaaf-capture-live] | NCAAF captures from real OddsAPI: 184/184 teams, 432 rows on the 08-29 slate `[measured 2026-08-25T23:07:25Z,  | `state_football.md` |
| [ncaaf-sweep-env-gate] | RESOLVED — `SYNDICATE_ACTIVE_SPORTS` now carries `ncaaf,nfl`; the capture runs `[measured 2026-08-25T23:07:25Z | `state_football.md` |
| [ncaaf-oddsapi-lines] | NCAAF GAME LINES — LIVE IN PRODUCTION, 432 rows captured on the 08-29 slate `[measured 2026-08-25T23:07:25Z, l | `state_football.md` |
| [ncaaf-margin-calibration] | NCAAF MARGINS ARE CALIBRATED; TOTALS ARE NOT `[verified 2026-08-19]` | `state_football.md` |
| [ncaaf-ratings-leak] | NCAAF RATINGS WERE LEAKED FOR BACKTESTS — FIXED `[verified 2026-08-19]` | `state_football.md` |
| [ncaaf-2026-data] | NCAAF 2026 DATA IS BUILT AND SLATE-COMPLETE `[verified 2026-08-19]` | `state_football.md` |
| [nfl-fantasy-engine] | NFL FANTASY FOOTBALL ENGINE — **PASSES ITS FALSIFICATION TEST ON ALL FOUR CRITERIA, AND IS LIVE ON PRODUCTION  | `state_football.md` |
| [nfl-player-props-model] | NFL PLAYER-PROP MODEL: `#471` FULLY CLOSED, ALL 6 TUNED CONSTANTS STABILITY-VERIFIED, ALLOWLIST GAP FIXED+LIVE | `state_football.md` |
| [nfl-data-ingestion-autoruns] | NFL ROSTER/DEPTH-CHART/INJURIES INGESTION — ALL 3 AUTORUNS ARMED, DEPLOYED, CONFIRMED FIRING — ONE PUBLISH SUC | `state_football.md` |
| [nfl-player-props] | NFL player props: capture fixed, model priced and BEATEN by the market | `state_football.md` |
| [nfl-game-context] | Game context is built and measured, and INERT in production | `state_football.md` |
| [cfbd-monthly-quota-exhausted] | 2026-08-30 — LIVE: NCAAF projections are FAILING in production, on opener weekend | `state_football.md` |
| [ncaaf-live-resim] | SMARTSIM2 CAN BE RESUMED FROM MID-GAME; ITS ENTRYPOINT COULD NOT `[measured 2026-09-05, lane ncaaf-live-resim] | `state_football.md` |
| [nfl-season-open-date] | THE 09-09 vs 09-10 DISAGREEMENT IS A TIMEZONE, NOT AN ERROR — READ 2026-09-07 `[lane soccer-unfed-inputs]` | `state_football.md` |
| [nfl-ncaaf-ui-parity] | NFL RENDERED THE GENERIC BOARD PARTIALS WHILE NCAAF RENDERED THE FOOTBALL ONES — one string, three surfaces `[ | `state_football.md` |
| [nfl-props-week1-dead] | NFL PLAYER PROPS WERE STRUCTURALLY DEAD EVERY WEEK 1, AND THE MODEL RAN ON THE SERVICE WITHOUT THE DATA `[FIXE | `state_football.md` |
| [ncaaf-tbd-kickoff] | A TBD NCAAF KICKOFF IS A DATE, NOT A TIME — fixed, deployed to refresh-worker `889d4e12` and web `0022ecb1`, v | `state_football.md` |
| [ncaaf-prop-quote-join-date] | NCAAF LEGACY PROP ROWS JOIN THE KICKOFF-DATE QUOTE SHARD — fixed `3157bb7b`, LIVE on refresh-worker `f833f7ec` | `state_football.md` |
| [nhl-ncaab-club-maps] | NHL AND NCAAB HAVE CLUB MAPS; EVERY SPORT SYNDICATE COVERS NOW DOES `[verified in production 2026-09-24 02:07: | `state_football.md` |
| [nfl-chip-week-enumeration] | NFL CHIPS WERE BUILT FOR WEEK 1 BECAUSE THE WEEK ENUMERATORS READ ONE ROOT - FIXED AND VERIFIED IN PRODUCTION  | `state_football.md` |
| [nfl-live-gameline-join] | NFL LIVE RE-SIM LANES WERE UNREADABLE BY THE BOARD JOIN — FIXED AND DEPLOYED, LIVE READING OWED `[deployed 202 | `state_football.md` |
| [nfl-game-day-injuries] | NFL GAME-DAY INJURY CAPTURE IS ENABLED ON REFRESH-WORKER; ITS STATUSES FILE NOW CROSSES TO LIVE-ODDS-WORKER —  | `state_football.md` |
| [kalshi-in-play-and-real-fees] | KALSHI TRADES IN-PLAY AND PUBLISHES ITS OWN FEE PARAMETERS; THE ARB THRESHOLD WAS ABOVE BREAK-EVEN EVERYWHERE  | `state_kalshi.md` |
| [kalshi-segment-on-full-game] | KALSHI PLACED SEGMENT BETS ON FULL-GAME CONTRACTS: the join key had no `segment` `[verified 2026-08-28, lane p | `state_kalshi.md` |
| [kalshi-venue-execution] | KALSHI ORDERS: the blocker was SHARD COLLATERAL, and spreads were inverting the bet `[verified 2026-08-26, lan | `state_kalshi.md` |
| [kalshi-coverage-vs-oddsapi] | KALSHI COVERAGE: capture is healthy, the JOIN is the bottleneck, and two prop vocabularies do not exist `[veri | `state_kalshi.md` |
| [kalshi-execution] | Kalshi execution — session close 2026-08-26 (lane `kalshi-exchange-index`) | `state_kalshi.md` |
| [kalshi-odds-refresh-bound] | THE VENUE FAN-OUT IS A COLD-START BURST ON A PERSISTED CLOCK, AND IT IS NOW TIME-BOUNDED `[2026-09-03, lane ka | `state_kalshi.md` |
| [kalshi-quote-capture-coupling] | Kalshi quote capture ran ONLY inside the heavy board build — a refused heavy build stopped it for every sport  | `state_kalshi.md` |
| [layer2-board-keyvalue-ceiling] | THE BOARD'S CEILING IS THE COMBINED KEY, NOT THE SHARDS — and `per_sport=3000` corrupted production for ~29 mi | `state_layer2.md` |
| [layer2-realized-accuracy] | THE LAYER 2 BOARD'S REALIZED ACCURACY — the portfolio book is the surface, and the measurement chain is broken | `state_layer2.md` |
| [layer2-score-outcomes] | THE BOARD'S SCORE, GRADED ON OUTCOMES AND CLOSES FOR THE FIRST TIME -- real price edge, fee-blind ranking, non | `state_layer2.md` |
| [layer2-movement-term] | EVERY LAYER 2 ROW IS NOW COMPARED WITH ITS OWN LINE'S OPENING — line_moved 913 -> 0, verified `[2026-09-20 16: | `state_layer2.md` |
| [sim-weight-clv-decomposition] | `_SCORE_SIM_WEIGHT`'s OWN UNBLOCK CONDITION WAS RUN, AND THE ANSWER IS NO — leave `(0.125, 1.5)` alone `[2026- | `state_layer2.md` |
| [layer2_board_display] | LAYER 2 BOARD -- USER-VISIBLE DISPLAY BUGS, 2026-08-20 AUDIT | `state_layer2.md` |
| [layer1-layer2-boards] | LAYER 1 / LAYER 2 BOARDS — session briefs exist; three facts worth not re-deriving `[code read 08-16 11:2x CDT | `state_layer2.md` |
| [layer1-board-date-scoping] | THE BOARD WAS DROPPING GAMES TWO WAYS — both FIXED AND VERIFIED; a THIRD (soccer projections, late kickoffs) f | `state_layer2.md` |
| [board-chip-coverage] | Layer 2 compact game cards — FULL chip coverage, verified 2026-08-26 | `state_layer2.md` |
| [chip-artifact-content-age] | A chip artifact's TIMESTAMP and its CONTENT age are different numbers — verified 2026-08-27 (lane `mlb-chip-li | `state_layer2.md` |
| [chip-refresh-worker-pull-hop] | REFRESH-WORKER'S HOT-ARTIFACT PULL FLOOR WAS SET BY LIVE-ODDS-WORKER — one shared keyvalue watermark; fix `082 | `state_layer2.md` |
| [layer2-rail-group-join-keys] | THE GAMES RAIL BUILT EACH GAME FROM ITS FIRST ROW, AND A SHORT CLUB NAME MINTED A FAKE ABBR — both FIXED and V | `state_layer2.md` |
| [layer2-market-gone-league-cadence] | `_drop_market_gone_rows` DELETED LIVE MARKETS whenever a partial pass was the newest stamp (soccer per league, | `state_layer2.md` |
| [kalshi-prop-quote-identity] | KALSHI PROP QUOTES WERE FILED UNDER THE CANONICAL KEY WITH NO GAME, AND REFRESH-WORKER'S NFL PROP ARTIFACT WAS | `state_layer2.md` |
| [layer2-live-quote-age] | LIVE LAYER 2 ROWS WERE AGED ON THE MOVEMENT CLOCK — the observation gate and the in-play sizing refusal are LI | `state_layer2.md` |
| [layer2-prior-date-carryover] | A GAME STILL LIVE AT MIDNIGHT CT LOST ITS LAYER 2 BOARD — the carryover and the stale-live label are LIVE; the | `state_layer2.md` |
| [mlb-doubleheader-joins] | A TEAM PAIR WAS NOT A GAME: EVERY MLB DOUBLEHEADER JOIN COLLAPSED, AND SIX ARE NOW FIXED AND LIVE `[verified 2 | `state_layer2.md` |
| [nhl-chip-start-time] | NHL CHIPS CARRIED NO START TIME AND NO STATUS TOKEN UNTIL 2026-09-22 — FIXED AND LIVE -- BOTH HALVES MEASURED  | `state_layer2.md` |
| [ncaaf-kickoff-cache] | AN UPCOMING NCAAF CARD READ "TBD" BECAUSE THE COMMITTED CFBD CACHE WAS THE JULY SNAPSHOT — FIXED BOTH HALVES,  | `state_layer2.md` |
| [mlb-live-gameline-venue-segment] | MLB LIVE GAME LINES SERVE NO SIM EDGE BECAUSE THE VENUES QUOTE FULL-GAME CONTRACTS AND THE LIVE BOARD IS MOSTL | `state_layer2.md` |
| [layer2-board-redesign] | LAYER 2 BOARD PAGE: ONE NAV, VISIBLE FILTERS, RESEARCH RAIL + SLIP TRAY, LOGOS, AND AN EMBED THAT PARSES -- LIVE on web `2735d39a`, refresh-worker `6eae7e0a` | `state_layer2.md` |
| [segment-misgrade-regrade] | 53 OF 173 SETTLED SEGMENT ORDERS WERE GRADED AGAINST THE WRONG ACTUAL — 30.6%, AND THE ERRORS NEARLY CANCEL `[ | `state_ledger.md` |
| [stale-test-triage] | "THE TEST IS STALE" IS A HYPOTHESIS, AND IT WAS WRONG FOR 4 OF 18 `[2026-09-05, lane stale-test-repair, commit | `state_ledger.md` |
| [full-suite-completes] | THE FULL SUITE RAN TO COMPLETION FOR THE FIRST TIME -- 15,307 tests, 61m06s, and the 27 "NEW" failures are 6 p | `state_ledger.md` |
| [github-actions-dead] | GITHUB ACTIONS RUNS AGAIN FROM 2026-09-10 (billing fixed by the user); `ci.yml` GATED NOTHING 2026-08-22..2026 | `state_ledger.md` |
| [ci-suite-red-test] | CI'S OWN SUITE IS GREEN. THE "ONE RED TEST" WAS THE 31st DATA-ABSENCE FAILURE, NOT A SURVIVOR OF THEM `[correc | `state_ledger.md` |
| [state-file-split] | state.md IS AN INDEX PLUS NINE PARTS `[2026-09-03, scripts/split_state.py, commit 23bf6bc7]` | `state_ledger.md` |
| [session-harness] | SESSION HARNESS — what the hooks actually enforce | `state_ledger.md` |
| [worktree-test-data] | THE 92 RED TESTS IN A SESSION WORKTREE ARE THE ENVIRONMENT, NOT DEFECTS `[measured + shipped 2026-09-03]` | `state_ledger.md` |
| [test-baselines] | TEST BASELINES | `state_ledger.md` |
| [lane-state-carried] | LANE STATE RECORDS CARRIED THROUGH THE 2026-08-18 COLLAPSE — **ARCHIVED 2026-08-19 to `state_archive_2026-08-1 | `state_ledger.md` |
| [lane-guard-disclaimer-and-worktree-exemption-bugs] | TWO REAL BUGS FOUND IN `lane-guard.py`, NEITHER FIXED `[found 2026-08-18]` — **ARCHIVED 2026-08-19 to `state_a | `state_ledger.md` |
| [split-state-reindex-truncation] | `split_state.py --reindex --apply` DELETED EVERYTHING BELOW THE `[subject-index]` TABLE — **FIXED, ON MAIN (`2 | `state_ledger.md` |
| [discard-guard-origin-blindness] | `discard-guard.py` CALLED PUSHED CONTENT "NOWHERE ELSE", AND BLOCKED `git restore --staged` — **FIXED (`e3a515 | `state_ledger.md` |
| [git-store-onedrive] | ONEDRIVE MANAGES `.git` AND `.syndicate`, AND IT SILENTLY BREAKS `git worktree remove` `[2026-09-06, lane git- | `state_ledger.md` |
| [todo-id-allocation] | A TODO ID IS RESERVED BY A PUSH TO `main` BEFORE ANY WORK — one claim-only `[skip ci]` commit per allocation ` | `state_ledger.md` |
| [full-suite-run-method] | RUNNING THE FULL SUITE ON THIS MACHINE NEEDS BATCHING, AN ISOLATION RETRY AND A PINNED MANIFEST — and the fail | `state_ledger.md` |
| [test-suite-writes-tracked-mirror] | THE TEST SUITE WROTE INTO THE TRACKED `data/` MIRROR, AND NOTHING SAID SO — **GUARDED SINCE 2026-09-09** `[lan | `state_ledger.md` |
| [live-gameline-ledger-key] | THE LIVE-GAMELINE LEDGER MERGED UP TO 14 GAMES INTO ONE RECORD - the key had no `event_id` and `game_pk` is us | `state_ledger.md` |
| [live-gameline-clv-impact] | THE LEDGER'S PAIR-KEYED GAME IDENTITY COST NO PUBLISHED NUMBER AND REFUSED A WHOLE WINDOW - and its root cause | `state_ledger.md` |
| [lane-claim-parser-holes] | THREE CLAIM SHAPES GUARDED NOTHING AND NOTHING REPORTED IT -- ALL THREE FIXED `[2026-09-23, lane polymarket-co | `state_ledger.md` |
| [lane-claim-truncation] | A LANE CAN CLAIM FILES THE GUARD DOES NOT ENFORCE, AND NOTHING SAID SO -- 17 OPEN lanes affected, now REPORTED | `state_ledger.md` |
| [mlb-hitter-strikeouts-prop] | MLB HITTER `strikeouts` WAS A DEAD FIELD FOR MONTHS; FIXED, DEPLOYED AND VERIFIED — AND NO BET WAS EVER PRICED | `state_mlb.md` |
| [mlb-sim-edge-is-anti-predictive] | THE MLB SIM'S CLAIMED EDGE IS ANTI-PREDICTIVE, AND THE PROP BOOK IS A REAL EDGE SPENT ON VIG `[verified 2026-0 | `state_mlb.md` |
| [mlb-certainty-claims] | MLB PUBLISHES LIVE WIN PROBABILITIES OF EXACTLY 0.0 AND 1.0, PRICES THEM, AND TWO OF THEM LOST `[measured 2026 | `state_mlb.md` |
| [mlb-live-edge-forbidden] | TWO STANDING CONSTRAINTS ON ANY MLB LIVE-EDGE WORK — lifted out of lane `live-prob-producer-reader-gap` when i | `state_mlb.md` |
| [mlb-exchange-shopping-value] | EXCHANGE PRICE-SHOPPING IS WORTH `+0.74 ROI POINTS` ON GAME MARKETS AND `+2.43%` ON THE PROP GATE BOOK — both  | `state_mlb.md` |
| [mlb-live-lens-accuracy-refuses] | THE MLB LIVE-LENS GRADER SETTLED FROM A RUNNING TALLY; it now refuses, and reads EMPTY because its feed never  | `state_mlb.md` |
| [mlb-sim-engine] | MLB SIM — INPUTS FULLY FED, STILL NO MARKET EDGE `[measured 2026-08-18, lane convergence-phase7-crps; supersed | `state_mlb.md` |
| [mlb-resim-rules] | 2026-08-17 01:3xZ — VERIFIED (sim-scheduling): the real MLB re-sim rules | `state_mlb.md` |
| [mlb-pitch-mix] | MLB CONDITIONAL PITCH MIX — MECHANISM VALIDATED, MARKET SILENT `[2026-08-18]` | `state_mlb.md` |
| [mlb-sim-artifacts-live] | WEB `055dfc67` — THE FIVE MLB SIM ARTIFACTS ARE IN PRODUCTION `[2026-08-18 22:54:51Z]` — **ARCHIVED 2026-08-19 | `state_mlb.md` |
| [mlb-sim-log-unreachable] | RETRACTED — THE SIM LOG *IS* REACHABLE REMOTELY `[2026-08-19]` | `state_mlb.md` |
| [mlb-sim-log-unreachable-retracted] | FINDING — THE MLB SIM JOB'S DIAGNOSTICS ARE UNREACHABLE FROM ANYWHERE `[2026-08-19, WRONG]` | `state_mlb.md` |
| [mlb-vendor-exit-audit] | MLB VENDOR EXIT — 18 OF 20 PIPELINE STAGES HAVE NO NATIVE PRODUCER `[2026-08-20, MEASURED]` | `state_mlb.md` |
| [mlb-ladders-native-builder] | MLB LADDERS — NATIVE BUILDER SHIPPED TO THE TREE `[2026-08-19]` | `state_mlb.md` |
| [mlb-live-lens-row-shape] | The live-lens report has TWO writers and TWO row shapes — verified 2026-08-26 (lane `mlb-chip-live-state`) | `state_mlb.md` |
| [mlb-sim-retrigger-churn] | THE MLB DAILY SIM CROWDED THE BOARD OFF refresh-worker; A RE-SIM COSTS ~15 MIN WHATEVER ITS SCOPE — FINGERPRIN | `state_mlb.md` |
| [mlb-traditional-doubleheader-join] | A TRADITIONAL DOUBLEHEADER COULD NEVER CLEAR THE 45-MINUTE SEPARATION RULE -- FIXED PREGAME; THE IN-PLAY FIX I | `state_mlb.md` |
| [mlb-asof-backtest] | THE MAY–JULY MLB ENGINE BEATS THE DE-VIGGED BOOK IN 0 OF 23 MARKETS (10 WORSE); MOSTLY A LEVEL ERROR, LED BY S | `state_mlb.md` |
| [scheduled-model-evaluation] | MODEL EVALUATION IS SCHEDULED NOW -- a daily Render cron grades the PRICED population per sport x market x seg | `state_model.md` |
| [settlement-autorun-live-settles-zero] | THE EVALUATION-SETTLEMENT AUTORUN WAS LIVE ALL ALONG AND SETTLED ZERO — the switch was never the blocker, the  | `state_model.md` |
| [ledger-and-primary-tree] | — MEASURED 2026-09-02, this machine | `state_model.md` |
| [ledger-precommit-guard] | LEDGER COMMITS ARE GUARDED AT TWO LEVELS — VERIFIED 2026-09-02 | `state_model.md` |
| [replay-diff-gate] | A PRODUCTION DAY NOW REPRODUCES OFFLINE, 0 MISMATCHES — and two board blocks provably CANNOT `[verified 2026-0 | `state_model.md` |
| [lane-ledger-conflict-guard] | THE LANE CHECKER USED TO PASS A FILE WITH CONFLICT MARKERS IN IT `[fixed 2026-08-30, `10f45a0c`; scope MEASURE | `state_model.md` |
| [settlement-resolver-coverage] | SETTLEMENT: NFL CAN BE GRADED, NCAAF IS WIRED-BUT-UNVERIFIED, and three sports still cannot settle a bet `[ver | `state_model.md` |
| [execution-ledger-lost-live-rows] | 30 LIVE FILLS PLACED 2026-09-01..09-04 ARE MISSING FROM THE EXECUTION LEDGER, BY DESIGN NOT RESTORED — correct | `state_model.md` |
| [execution-ledger-cross-service-race] | THE MONEY LEDGER IS WRITTEN BY THREE SERVICES, AND SINCE 2026-09-11 EVERY WRITE IS ONE COMPARE-AND-SWAP (#656) | `state_model.md` |
| [execution-ledger-archive] | THE EXECUTION LEDGER'S RECORD CAP (3,000) MOVES ROWS TO A DISK ARCHIVE; FULL-HISTORY READERS READ BOTH `[verified on the fleet 2026-10-08T17:01Z, lane execution-ledger-keyvalue-growth]` | `state_model.md` |
| [probability-statistic-ownership] | PROBABILITY-STATISTIC OWNERSHIP `[measured 08-15, shipped `2ac3c6bc`]` | `state_model.md` |
| [nhl-sim-engine] | NHL SIM (hockeysim) — `nhl_sim_input_checklist.py` PASSES, exit 0 `[measured 2026-08-20, lane nhl-model-owner] | `state_model.md` |
| [nhl-player-props] | NHL PLAYER PROPS PROJECTED AND PRICED, PER-LINE GATED; PP/PK units from real PP/SH minutes; engine still loses to player average in most markets (ice-time and per-minute errors cancel) `[verified 2026-10-05, lanes nhl-player-props-projection / nhl-pp-units-real-toi]` | `state_model.md` |
| [model-skill] | MODEL SKILL (`#428`) — measured vs not | `state_model.md` |
| [sim-scheduling-blocker] | 2026-08-17 02:1xZ — VERIFIED (sim-scheduling): the primary goal has ONE blocker — **ARCHIVED 2026-08-19 to `st | `state_model.md` |
| [sim-edge-analysis-2026-09-01] | FULL-PLATFORM SIM-ENGINE EDGE ANALYSIS — strategy synthesis + new from-code facts `[2026-09-01, session syndic | `state_model.md` |
| [accuracy-autorun-rearm-state] | `#626`(h) IS ARMED, RAN, AND PASSED. The budget, not memory, is now the constraint. `[2026-09-04, lane accurac | `state_model.md` |
| [nhl-live-resim] | NHL HAS A LIVE RE-SIM AND IT CAN NOW SEE ITS SLATE -- but no NHL game has yet reached the board with a probabi | `state_model.md` |
| [polymarket-live-totals-quote-names-no-game] | 26 OF 28 LIVE POLYMARKET TOTALS QUOTES ON THE BOARD ARE SHARED ACROSS GAMES — one price per LINE, no game iden | `state_polymarket.md` |
| [polymarket-fill-price-is-reported] | THE VENUE REPORTS `avgPx`. "This path has no fill price" was FALSE and cost a 12h live halt `[verified 2026-08 | `state_polymarket.md` |
| [polymarket-capital-is-margin-held] | POLYMARKET'S CASH IS NOT ITS BUYING POWER: `marginRequirement` HOLDS IT, and the venue tells us in a field we  | `state_polymarket.md` |
| [polymarket-h2h-buys-the-wrong-side] | POLYMARKET MONEYLINES BUY THE WRONG TEAM: `outcomes[0]` is not reliably the YES leg `[verified 2026-08-28, lan | `state_polymarket.md` |
| [polymarket-vs-kalshi-prop-prices] | — MEASURED 2026-09-01, MLB, production shard | `state_polymarket.md` |
| [polymarket-low-activity] | — VERIFIED 2026-08-27, refresh-worker + live-odds-worker | `state_polymarket.md` |
| [polymarket-venue-join] | VERIFIED 2026-08-29, all three services on `95c4fb12` | `state_polymarket.md` |
| [polymarket-orders-are-cancelled] | 2026-08-30 — the venue cancels them, we re-place them, and nobody knows why | `state_polymarket.md` |
| [polymarket-no-fill-size-is-gross-capped] | A POLYMARKET **NO** ORDER IS CHECKED AGAINST **$1.00 PER CONTRACT** AND CHARGED THE **NET** — **5 of 5 NO orde | `state_polymarket.md` |
| [polymarket-resting-orders-do-not-encumber-cash] | 2026-08-31T15:45Z — CONFIRMED by a before/after pair, after I doubted it | `state_polymarket.md` |
| [polymarket-price-gate-leaks-by-crossing] | 2026-08-31T16:05Z — FIXED AND DEPLOYED. The ceiling used to be checked against a price the venue never receive | `state_polymarket.md` |
| [polymarket-soccer-h2h-bought-the-OPPOSITE-team] | 2026-08-31T21:25Z — FIXED AND DEPLOYED on both services; the positive case is UNVERIFIED | `state_polymarket.md` |
| [polymarket-two-dimensional-rule-PARTLY-CONFIRMED] | 2026-09-01T01:20Z — the PREGAME half is solid on two probes; the LIVE half rests on ONE and is NOT replicating | `state_polymarket.md` |
| [polymarket-held-population-is-6-of-6-POSITIVE-EV] | 2026-08-31T17:33Z — the gate suppresses positive-EV bets; its whole defence is that they cannot fill | `state_polymarket.md` |
| [polymarket-explore-arm-FIRING] | 2026-08-31T16:05Z — the arm fired, STALLED on a float edge, and fires again; the falsifier is live | `state_polymarket.md` |
| [polymarket-explore-arm-too-slow] | 2026-08-31T15:11Z — the arm is LIVE and CORRECT, and its sample rate is close to zero | `state_polymarket.md` |
| [polymarket-gate-is-self-confirming] | 2026-08-31T13:42Z — THE GATE DESTROYED ITS OWN FALSIFIER | `state_polymarket.md` |
| [polymarket-cheap-side-selection-risk] | 2026-08-31 — HIGHER FILL VOLUME IS NOT SUCCESS. The gate changes the BET MIX. | `state_polymarket.md` |
| [polymarket-price-gate-LIVE] | 2026-08-31T05:58Z — the price gate is live and holding the right population | `state_polymarket.md` |
| [polymarket-TIME-IS-NOT-THE-VARIABLE] | 2026-08-31T05:29Z — TIME-TO-EVENT IS REFUTED. The gate's premise is false. | `state_polymarket.md` |
| [polymarket-placement-hold] | 2026-08-31 — LIVE, and it holds 13 of 17 positions | `state_polymarket.md` |
| [polymarket-crossing-RESULT] | 2026-08-31 — CROSSING DOES NOT HELP. Price is not the constraint pregame. | `state_polymarket.md` |
| [polymarket-crossing-experiment] | 2026-08-31 — LIVE and CORRECT, but it has no test case yet | `state_polymarket.md` |
| [polymarket-pregame-orders-rest] | 2026-08-31 — THREE pending orders, ALL pregame, ALL bid AT the quote | `state_polymarket.md` |
| [polymarket-fill-time-to-event] | 2026-08-30 — the leading hypothesis is TIME TO EVENT, not liquidity at our size | `state_polymarket.md` |
| [polymarket-order-fills] | 2026-08-30 — four causes REFUTED; fills are mostly fine | `state_polymarket.md` |
| [polymarket-slate-budget-kept-props-dropped-game-lines] | THE POLYMARKET SLATE SPENT ITS 8 MB ON PROPS AND DROPPED THE WEEKEND'S GAME LINES — fixed in `3bafdd2b` `[veri | `state_polymarket.md` |
| [polymarket-pregame-hold-premise-falsified] | THE PREGAME NEAR-EVEN HOLD'S OWN FALSIFIER WAS ALREADY IN THE LEDGER — and the live Polymarket book shows no e | `state_polymarket.md` |
| [polymarket-ask-at-build-step1] | THE LARGEST CLAIMED POLYMARKET EDGES ARE NOT EXECUTABLE — 0 of 3 builds planned at >= 20% EV were marketable;  | `state_polymarket.md` |
| [portfolio-sign-in-and-books] | EVERY PORTFOLIO PAGE IS BEHIND A SIGN-IN, AND THERE IS MORE THAN ONE PORTFOLIO `[verified on production 2026-0 | `state_portfolio.md` |
| [portfolio-live-surface] | `/portfolio` IS THE LIVE BUYING ENGINE, the venue caps BIND, and the VENUE now settles our bets `[verified 202 | `state_portfolio.md` |
| [portfolio-settlement] | PORTFOLIO SETTLEMENT — the ledger crossed no service boundary, and the join keyed on a value that drifts `[ver | `state_portfolio.md` |
| [portfolio-sim-sizing-gate] | ONLY A MODEL MEASURED TO BEAT THE MARKET SIZES MONEY; TODAY NONE IS, SO STAKES FOLLOW PRICE `[verified on prod | `state_portfolio.md` |
| [order-model-attribution] | AN ORDER RECORDS THE SIM'S VERDICT — DEPLOYED AND VERIFIED ON PRODUCTION; THE COMMIT GATE MAKES FOUR OF THE NI | `state_portfolio.md` |
| [soccer-roster-only-players] | SOCCER SIM SQUADS: ADDING ROSTER-ONLY PLAYERS (TEAM TOTALS FIXED) FAILED ITS PRE-REGISTERED TEST, AND THE ESPN | `state_soccer.md` |
| [soccer-projection-unit-dates] | SOCCER PREGAME PROJECTIONS: MLS UNITS WERE KEYED ON THE UTC DATE, SO EVENING KICKOFFS GOT EMPTY FILES; EPL/SER | `state_soccer.md` |
| [soccer-confirmed-lineups] | CONFIRMED XI REACHES THE SOCCER SIM IN THE LAST MINUTE BEFORE KICKOFF, BUT ONLY 7-10 OF 11 STARTERS ARE RECOGN | `state_soccer.md` |
| [soccer-season-market-audit] | SEASON TO DATE NO SOCCER MARKET BEATS THE CLOSE, AND THE PROP MODEL IS PRICING LAST SEASON'S SQUADS `[measured | `state_soccer.md` |
| [soccer-prop-book-coverage] | WIDENING SOCCER PROP REGIONS BUYS ONE SOFT BOOK FOR ~1M CREDITS/MONTH — **KNOB SHIPPED, DELIBERATELY LEFT OFF* | `state_soccer.md` |
| [soccer-input-gate] | THE SOCCER INPUT GATE NOW RUNS, AND 4 OF ITS 9 ALARMS WERE DECISIONS — MEASURED 2026-09-07 `[lane soccer-unfed | `state_soccer.md` |
| [soccer-market-anchor] | MARKET-ANCHORING IS REACHABLE AND STILL OFF BY DECISION — MEASURED 2026-09-02 `[lane soccer-anchor-cost, main  | `state_soccer.md` |
| [soccer-board-coverage] | — MEASURED 2026-09-02, production, NOT A DEFECT | `state_soccer.md` |
| [soccer-live-match-state] | Soccer's live tier is WIRED AND VERIFIED ON LIVE MATCHES (2026-08-21) | `state_soccer.md` |
| [soccer-live-espn-inputs] | SOCCER LIVE STATE: ESPN's RANGE scoreboard is stale (fixed, LIVE); the live score dropped penalties and own go | `state_soccer.md` |
| [soccer-live-momentum] | FotMob momentum is production's signal now; the ESPN proxy carries none (2026-08-22) | `state_soccer.md` |
| [soccer-compact-cards] | Pregame + final compact cards redesigned and DEPLOYED, verified on production HTML (2026-08-22) | `state_soccer.md` |
| [soccer] | SOCCER | `state_soccer.md` |
| [soccer-live-tier] | SOCCER'S LIVE TIER — VERIFIED, AND WHAT IS NOT | `state_soccer.md` |
| [soccer-shots-prop-skill] | SOCCER SHOTS PROPS â€” THE POISSON SHAPE IS RIGHT AND THE MEAN IS INFLATED `[measured 2026-08-31, lane layer1- | `state_soccer.md` |
| [soccer-moneyline-precision] | SOCCER'S MONEYLINE EDGE IS NOW GATED ON ITS OWN SIM NOISE, AND 61% OF IT WAS INSIDE THAT NOISE `[measured 2026 | `state_soccer.md` |
| [soccer-shot-woodwork-undercount] | EVERY SHOT OFF THE WOODWORK WAS MISSING FROM SHOT TOTALS — FIXED, LIVE ON live-odds-worker `20d589ed` 2026-09- | `state_soccer.md` |
| [live-lens-snapshot] | THE LIVE-LENS SNAPSHOT CANNOT BE DATED — it is a 4 MB KEYVALUE key, not a file, and archiving it would cost ~5 | `state_ui.md` |
| [live-surface-tier5] | THE LIVE SURFACE — Tier 5 `[measured 08-15 02:3x–03:0xZ]` | `state_ui.md` |
| [ask-the-syndicate] | ASK THE SYNDICATE | `state_ui.md` |
| [ui-board-cards] | UI / BOARD CARDS | `state_ui.md` |
| [brand-marks-and-error-pages] | TWO BRAND MARKS, SPLIT BY RENDER SIZE — and the app finally has error pages `[verified 2026-09-09, lane brand- | `state_ui.md` |
| [client-slate-date] | THE BROWSER'S SLATE DATE IS CENTRAL, FROM ONE FUNCTION, AND A RATCHET NOW HOLDS IT `[verified 2026-09-09 in pr | `state_ui.md` |
| [live-odds-worker-memory-is-page-cache] | live-odds-worker memory: THE 09-06 "NOT IN DANGER" VERDICT WAS OVERTAKEN — 70+ OOM kills 09-09..09-13; allocat | `state_venues.md` |
| [603-cross-game-quote-keys] | VENUE QUOTES NAMED NO GAME; FIXED ON EVERY PATH, DEPLOYED, AND STILL UNPROVEN AFTER THREE READINGS `[2026-08-3 | `state_venues.md` |
| [venue-fee-economics] | FEES ARE READ FROM THE VENUE AND VERIFIED AGAINST 18/18 REAL FILLS; THE ARB THRESHOLD WAS ABOVE BREAK-EVEN EVE | `state_venues.md` |
| [venue-join-refusal-visibility] | WHY THE EXCHANGES DO NOT EXECUTE SOCCER OR PROPS, and the two instruments that were lying about it `[verified  | `state_venues.md` |
| [live-odds-worker-deploy-gate] | THE DEPLOY GATE IS UNREACHABLE ON live-odds-worker, and the documented override CANNOT WORK AS WRITTEN `[measu | `state_venues.md` |
| [venue-candidate-key-ambiguity] | BOARD JOIN KEYS: a bare token could name another fixture's team, and the guard's own counter cannot see it fir | `state_venues.md` |
| [odds-cadence] | ODDS CADENCE AND CAPTURE | `state_venues.md` |
| [venue-odds-storage] | `venue_odds` LIVES ON DISK, NOT IN THE SHARED KEYVALUE `[measured + deployed 2026-09-02, lane venue-odds-byte- | `state_venues.md` |
| [sharp-reference-price] | SHARP REFERENCE PRICE — WE HAVE ONE. The audit's caveat is STALE. | `state_venues.md` |
| [board-quote-staleness] | Board freshness vs QUOTE staleness — verified 2026-08-26 (lane `board-staleness-visibility`) | `state_venues.md` |
| [exchange-refresh-cadence] | — VERIFIED 2026-08-27, live-odds-worker `34b4d4b4` | `state_venues.md` |
| [exchange-venues] | Crypto.com is NOT a third venue — VERIFIED 2026-08-28, local full-egress session | `state_venues.md` |
| [venue-market-universe] | The venues list ~25,000 markets and the board acts on 277 — VERIFIED 2026-08-30 | `state_venues.md` |
| [render-crons] | THE THREE CRON SERVICES: WHAT THEY ARE, AND FOUR FACTS THAT COST A SESSION TO LEARN `[2026-09-08, lane render- | `state_worker.md` |
| [ci-suite-pytest-step] | THE FULL SUITE RUNS ONLY WHEN CHUNKED, AND IT IS GREEN WITH AN EMPTY BASELINE `[verified 2026-10-02, lane ci-r | `state_worker.md` |
| [odds-history-segment-keys] | THE odds_history SHARD CARRIES `segment=` KEYS NOW — and three separate key builders were segment-blind, in tw | `state_worker.md` |
| [refresh-worker-headroom-2026-09-02] | THE ~1.4GB HEADROOM FIGURE IS STALE, AND THE METRIC EVERYONE READS IS THE WRONG ONE `[2026-09-02, lane m625-en | `state_worker.md` |
| [accuracy-autorun-OOM-2026-09-02] | THE ACCURACY AUTORUN OOM-KILLED refresh-worker. **RESOLVED — DISARMED AND VERIFIED 19:32Z.** `[2026-09-02, lan | `state_worker.md` |
| [local-fleet-runner] | THE THREE SERVICES RUN LOCALLY NOW — and doing it naively would have placed REAL ORDERS `[verified 2026-09-02, | `state_worker.md` |
| [local-production-host] | PRODUCTION RUNS ON ONE MACHINE NOW — `scripts/local_production.py`, and self-publish MUST be off on a shared d | `state_worker.md` |
| [artifact-allowlist-split] | THE ARTIFACT ALLOWLIST IS TWO LISTS NOW: READ WIDE, WRITE NARROW — and an allowlist-filtered inventory is NOT  | `state_worker.md` |
| [service-memory-saturation] | BOTH PRODUCTION SERVICES WERE MEMORY-SATURATED 2026-09-02/03 — MEASURED, and it BLOCKS analysis work `[lane so | `state_worker.md` |
| [live-odds-worker-deploy-window] | `deploy_preflight` ALMOST NEVER CLEARS ON live-odds-worker DURING A LIVE SLATE, and the reason is a LONG-RUNNI | `state_worker.md` |
| [render-egress-spikes] | WEB'S BILL IS ~10 ANOMALOUS HOUR-BUCKETS, NOT A LEAK — normal hours ARE explained, the spikes are NOT, and six | `state_worker.md` |
| [render-egress-cause] | **THE BILLING HALF IS RETRACTED — RENDER'S METER DOES NOT COUNT INBOUND EXTERNAL BYTES.** The mechanism is rea | `state_worker.md` |
| [web-anon-leak] | THE WEB SERVICE LEAKS ANONYMOUS MEMORY, ~75 MB/h, AND THE DEPLOY CADENCE HIDES IT `[verified 2026-09-01, lane  | `state_worker.md` |
| [render-server-failed-is-three-events] | `server_failed` IS NOT A FAILURE COUNT — read `details.reason`, one of its meanings is a HEALTHY DELIBERATE EX | `state_worker.md` |
| [refresh-worker-memory] | MEMORY — refresh-worker: THE OOM IS FIXED; A SLOW RATCHET REMAINS `[verified 2026-08-17, superseding four earl | `state_worker.md` |
| [deploy-discipline] | DEPLOY DISCIPLINE — read before any deploy | `state_worker.md` |
| [services-config-platform] | SERVICES, CONFIG, PLATFORM | `state_worker.md` |
| [oom-kills-census] | KILLS ARE EVENTS — there is now a tool, and a census `[measured 08-16 17:5xZ]` — **ARCHIVED 2026-08-19 to `sta | `state_worker.md` |
| [live-refresh-ownership] | LIVE ODDS REFRESH — WHO OWNS WHAT, and the three defects that made "live bets" scarce `[verified 2026-08-22/23 | `state_worker.md` |
| [shortlist-payload-budget] | THE PERSISTED SHORTLIST IS ONE KEYVALUE WRITE, and the cliff was on the calendar `[verified 2026-08-23, lane l | `state_worker.md` |
| [published-shortlist] | THE PUBLISHED SHORTLIST — edges, EV, CLV | `state_worker.md` |
| [artifact-delivery-topology] | AN ARTIFACT AN ENGINE READS IS A THREE-SERVICE CHANGE `[measured 2026-08-31]` | `state_worker.md` |
| [fleet] | FLEET `[2026-08-18 02:1xZ — goes stale in minutes; re-read before deploying]` — **ARCHIVED 2026-08-19 to `stat | `state_worker.md` |
| [deploy-ownership] | DEPLOY OWNERSHIP — SELF-SERVE BEHIND TWO LOCKS `[verified 2026-08-18, user decision, REPLACES the coordinator  | `state_worker.md` |
| [sim-scheduling-deploy-lineage] | STALE-TREE DEPLOY LINEAGE — the MECHANISM is real, the SEVERITY I first reported was wrong `[collapsed 2026-08 | `state_worker.md` |
| [web-request-path-latency] | WEB'S 502s WERE `/healthz` STARVATION, NOT SLOW COLD BOOTS — FIXED AND MEASURED `[2026-08-22, lane render-web- | `state_worker.md` |
| [web-boot-sync-healthz] | THE BOOT SYNC WAS A SECOND `/healthz` STARVATION SOURCE — 72.20s, NOW 0.65s `[verified 2026-08-27, lane boot-s | `state_worker.md` |
| [web-preflight-dead-sample] | WEB'S PREFLIGHT SAMPLE HAS BEEN DEAD SINCE 2026-08-14 — CAUSE STILL UNKNOWN AFTER FOUR WRONG ANSWERS `[2026-08 | `state_worker.md` |
| [refresh-worker-deploy-hold] | refresh-worker: THE OOM DEPLOY HOLD IS ORPHANED. Branch READY, NOT DEPLOYED. `[2026-08-18]` — **ARCHIVED 2026- | `state_worker.md` |
| [test-intelligence-runtime] | `tests/test_intelligence.py` IS SLOW, NOT STALLED — and the "warm state" finding is RETRACTED `[2026-09-03, la | `state_worker.md` |
| [refresh-worker-disk-2026-09-13] | refresh-worker's 48.9 GB disk: FULL 09-12 23:39Z -> 09-13 14:15Z, COMPACTED to 16.3 GB free `[verified 2026-09 | `state_worker.md` |
| [streamed-pull-append-only-tail] | `pull_streamed_artifact` sends NO `since=` on append-only tails — web's stream route 304'd before Range and fr | `state_worker.md` |
| [refresh-worker-heavy-build-refusal] | refresh-worker's heavy build is refused for hours once the MAIN PROCESS settles above ~2.2 GB after its first  | `state_worker.md` |
| [refresh-run-lanes] | Refresh-run lane topology, and refusals are now LOGGED [verified 2026-09-25/26] | `state_worker.md` |
| [pregame-sweep-cadence] | THE IDLE LOOP NOW WAKES WHEN A SPORT'S OWN PREGAME SWEEP IS DUE; soccer schedules refetch a near window betwee | `state_worker.md` |
| [web-oom-leak] | WEB SERVICE MEMORY GROWTH — the UPDATE 1..44 chain from 2026-09-04; was UNINDEXED until 2026-10-04 | `state_worker.md` |
