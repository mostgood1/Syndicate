

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
| MLB live game-line model | **ACCUMULATION 2026-09-03 [scheduled task `live-gameline-accuracy-snapshot`] — THE LIKE-FOR-LIKE POOL RESTARTED AT THE SCORER BOUNDARY AND IS 5 DATES / 54 GAMES, pooled diff -0.00266 (model 0.16976 vs market 0.17243), measured 2026-09-03 14:40 CT via `pool_live_gameline_trend.py`. IT MOVES EVERY NIGHT — RUN THE TOOL, DO NOT QUOTE THIS.** **SUPERSEDED (kept for the record): the 2-date / 28-game reading below — model 0.15110 vs market 0.16007, -0.00897, from the 4-of-29 `scored_markets` rows covering 09-01/09-02 only — rested on the stamp test that RESOLVED below disproves; 08-30 and 08-31 belong in the pool.** The 14-date / 171-game pool (model 0.26698 vs market 0.22798, **+0.03900**) **MIXES SCORER VERSIONS AND MUST NOT BE QUOTED AS A RESULT** — it is better than the retracted +0.06104 for the same reason that figure was retracted, not because the model improved. Per-date `priceable_only`: 09-01 **-0.00181** (n 317/317), 09-02 **-0.01614** (n 275/275); fresh (<=120s) **+0.00077** and **-0.00105**, i.e. PARITY on the only prices anyone could take. **DO NOT attribute the sign flip to the 09-01 staleness gate — NO A/B WAS RUN.** **RESOLVED 2026-09-03 — 08-30 AND 08-31 WERE BUILT BY THE POST-FIX SCORER AND ARE POOLABLE.** `scored_markets` is a SNAPSHOT-SCRIPT stamp, not a scorer stamp, so their missing stamp proved nothing. Settled by re-running `scripts/score_live_gameline_offline.py` (which imports the post-fix `score_ledger_records` verbatim) against production and taking the ratio production-scored-rows / h2h-only-rows: **08-26 14.74x, 08-27 7.46x, 08-29 7.46x vs 08-30 1.17x and 08-31 1.01x** — pre-fix dates fold in totals+spreads, these two do not. Same-ledger control: `records_considered` matches production EXACTLY on 08-26/27/29/30/31 (10406, 3030, 5554, 5904, 8161), so only the SCORED SUBSET differs. 08-30 reproduces exactly (n=249, briers 0.13400/0.19644). **08-28 is NOT evidence either way** — its capture recovered 4 of 15 games (`considered` 312 vs 6534) and its ratio 0.49 is a degenerate capture, not a scorer signal. **THE POOL IS THEREFORE 4+ DATES / 53+ GAMES** — 0.17279 vs 0.17497, **-0.00218** as of 2026-09-03 (was 2 dates / 28 games, -0.00897). **DO NOT QUOTE THAT NUMBER AS CURRENT: it moves every night.** `py -3 scripts/pool_live_gameline_trend.py --era post-fix` is AUTHORITATIVE and this prose is not — it splits by scorer era and `pool()` RAISES on a mixed-era set, so a cross-boundary figure is unreachable rather than merely discouraged. Still NOT a result: the two added dates disagree violently (**-0.06244** on 08-30 vs **+0.09183** on 08-31, 14 and 11 games), so per-date noise dwarfs the pooled difference. Backfill recovery for 09-01 is DETERMINISTIC — two board builds 16.5h apart wrote byte-identical rows. **`history.jsonl` IS TRACKED AND ON `main` `[2026-09-03]`** — verified by reading 29 rows / 14 dates (08-20..09-02) back out of `origin/main` itself, not by a push exit code. It had been untracked since 08-20 and the rows are **NOT regenerable** (each snapshots a board build that no longer exists), so the task brief's *"regenerated output, leave it uncommitted"* is WRONG for this file. Append-only by contract — never rewrite it in place to dedupe. The one-time landing narrative (cherry-pick onto `origin/main`, the 7-commit rebase, backup ref `backup/unpushed-main-2026-09-03` and its verified-nil deletion) is archived in `state_archive_2026-09-03.md`; its durable rule is now in `learnings.md` 2026-09-03, *"a line-level diff is the wrong instrument for a reworded ledger"*. **CORRECTED 2026-09-01 — THE n=98 / +0.07000 READING BELOW IS AN ARTIFACT OF A FIXED SCORER BUG AND MUST NOT BE QUOTED `[lane mlb-live-gameline-skill-audit]`.** Until `75cf9aec` (2026-08-30) the scorer compared totals `P(over)` and spreads `P(home covers)` against "did the home team win", so ~92% of the scored population was a category error. Proof by n: offline h2h-only scoring matches production EXACTLY on 08-30 (**249/249 rows, briers 0.13400/0.19644 identical**) and is 10-20x SMALLER on every earlier date (08-20: 156 vs 3,098). `reports/live_gameline_accuracy/history.jsonl` therefore pools across a scorer-version boundary; rows lacking `scored_markets` are NOT pre-fix by construction — that clause was wrong and is corrected above (2026-09-03): the stamp dates the SNAPSHOT SCRIPT, and 08-30/08-31 lack it while being post-fix. **WHAT IS ACTUALLY TRUE, measured over the RAW retained ledger (12 dates, 72,587 records, 157 games) against StatsAPI finals:** pooled over every quote age the model reads as PARITY (-0.00202, CI straddles 0) — but that is itself an artifact, because **27-30% of rows are priced against quotes older than 10 minutes** (p50 410s, p90 1,848s, **p99 74,997s**) and a stale price is a worse forecast, which flatters the model. On the FRESH cut (quote <=120s, the only prices anyone could take, n=2,574 rows / 147 games): **model Brier 0.18145 vs market 0.17049, diff +0.01096, bootstrap 95% CI over games [+0.00171, +0.02132], model worse in 98.9% of resamples.** So the model IS worse — by a QUARTER of the retracted figure, and for a different reason. **The loss concentrates where the board publishes:** on fresh quotes `|edge| >= 20pp` scores **+0.16305** (the biggest claimed edges are the biggest errors) and the first 45 minutes score +0.021, while the `priceable` rate was a flat 41-53% across the whole game with NO quote-age term. **RECALIBRATION IS NOT THE FIX AND WAS TESTED:** a 2-param home-lift + shrink looked clean in-sample (model mean 0.5178 vs actual 0.5412, sd 0.283 vs 0.253) and is WORSE out of sample (LOO 0.18388 vs 0.18145 raw). The encompassing regression on fresh quotes gives `+0.0975 +1.1246*logit(market) **-0.0391*logit(model)**` — the model carries no incremental information over the market at this n. 120-sim MC noise costs 0.00142 Brier and removing ALL of it closes only 12.7% of the gap. **SHIPPED AND LIVE `[2026-09-01, verified by CONTENT in `9a436fab`]`:** staleness gate at the join choke point (env `SYNDICATE_LIVE_GAMELINE_MAX_QUOTE_AGE_SECONDS`, default 600s, absent age REFUSES), `min_edge_pp` floor decoupling the publish bar from the sim count (default 0.0 = off), ledger v4 (inning/outs/`pregame_home_win_prob`), fresh-cut + `scorer_contract` provenance in the scorer, and `scripts/score_live_gameline_offline.py`. Commits `c01dabb1` (live in `417e19ed` 16:55:20Z) and `692214e0` (live in `9a436fab` 17:59:56Z) — **neither deployed by me; both were carried by OTHER lanes' deploys because they were on `origin/main`.** **The capability stamp is VERIFIED on a board with nothing to score:** MLB 18:01:09Z `{'pregame': 300}` and SOCCER 18:01:14Z `{'pregame': 39}` both serve `scorer_contract=2 fresh_quote_seconds=120.0`, where three hours earlier the identical branch served only `['enabled','finals_index','games_with_outcome','reason']`. **THE GATE ITSELF HAS NEVER FIRED IN PRODUCTION** — every sport on this path was pregame at 18:0xZ (`considered=0`, `withheld_by_reason={}`), so that empty dict describes the SLATE, not the gate; expected ~39.5% of live rows. Owed on scheduled task `verify-live-gameline-staleness-gate` (18:45 CT). Bound: 157 games; the clock was a WALL-CLOCK proxy because the ledger recorded none until v4. **The SUPERSEDED n=98 / +0.07000 (game-weighted +0.06104) reading over 8 nights 08-20..08-27 is archived in `state_archive_2026-09-03.md` — DO NOT re-quote it.** It is the scorer-bug artifact retracted above. **RETENTION IS NO LONGER A LAPTOP CRON `[2026-08-28, VERIFIED BY CONTENT]`**: `live_gameline_accuracy.py` records from the board build itself, deployed on both services at `8b8a6579` (refresh-worker live 15:59:38Z). The cron lost 7 of its first 8 nights — six disabled, one to Modern Standby suspending its python child 9h13m. **But NO row has been written in production yet** and the served counters are `null` until `#599` lands, so the worker-side path is DEPLOYED, NOT YET DEMONSTRATED. Lane `live-game-line-projection`. |
| Live-gameline collector (laptop cron) | **IT DOES NOT FAIL, IT GETS SUSPENDED — do not diagnose this as a missed cron `[2026-08-28, VERIFIED from this session's own transcript]`.** `live-gameline-accuracy-snapshot` fired on time 23:34:21 CT and issued its script call at 23:34:24; the tool result returned **08:49:37 the next morning, 9h15m13s later**, because Windows **Modern Standby** was entered 22:57:42 CT and not exited until 08:48:00 (Kernel-Power 506/507, one span, no wake between). By then the slate had rolled, so the run recorded `date=<next day>, games=0` — the write was DISPLACED onto the wrong date, not dropped. **The fire window fell inside standby on 6 of 10 nights (08-18..08-27).** Wake timers cannot fix it: AC=important-only, DC=disabled, nothing arms one. Judge the collector by whether a row EXISTS for the slate date, never by `captured_at`. `--date <yesterday>` (`cadfbe31`) recovers a displaced night; both nightly task prompts were hardened to stop the false alarm. |
| MLB 0-0 "FINAL" placeholder | **A 0-0 FINAL in a sport that cannot draw was passed through as an observed result `[2026-08-28, VERIFIED in production, FIX NOT DEPLOYED]`.** `is_final` (status text) and the score (`_side_score`'s seven candidates) are unrelated fields, so a FINAL status over an un-overwritten schedule placeholder read as a real 0-0. Measured on 08-27: `finals_seen=1462, finals_level=644 (44%)`, `games_with_outcome` **4 instead of ~15**, `no_final_outcome_for_game=1304`; same instant 08-26 read `finals_level=0`, 15 games. Not a time cutoff — HOU@NYY (23:05Z) kept its score, KC@TOR (23:07Z) did not. Fix `eca7e81b` suppresses it with a NAMED reason, keyed on `LEVEL_FINAL_IS_A_BAD_ROW` (allowlist — a 0-0 final is REAL in soccer/nfl/ncaaf and nulling it would re-break `a293bf14`). **THIS RECOVERS NO GAMES** — the scores are absent, not misclassified; it fixes the misreporting only. Owed: a deployed reading showing `finals_level` fall for 08-27 while 08-26 stays at 15. |
| MLB board `game.state` freshness | **CAUSE RELOCATED TWICE; THE THIRD IS UNMEASURED `[2026-09-04, lanes mlb-feed-live-terminal-refresh + mlb-final-state-mapping]`.** Symptom unchanged all day: 2026-09-03 had 9 MLB games, all 9 Final per StatsAPI, and `live_gameline_score` sees **7** — ATH@SEA and STL@LAD publish as `live`, and they are exactly the 2 that finished AFTER the 05:00Z midnight-Central roll. **TWO CAUSES EXONERATED BY MEASUREMENT, not by retraction.** (1) The wrong-slate live-lens overlay: real, fixed (`d77695ef`), and it was NOT this — before the gate it drove `live -> pregame`, and `build_finals_index` needs `state == 'final'`, so the game was skipped either way. Verified live: `rows_corrected` 187 -> 0 with `lens_date=2026-09-04 requested_date=2026-09-03`, while the same-date board still corrects 292 rows. (2) Feed staleness: the readers were fixed (`20221619`, final is terminal; the old predicate was INVERTED and never refreshed a cached LIVE payload) but that was not this either — `FEED_LIVE_REFRESH date=2026-09-03 ... skipped_final=9 attempted=0 failed=0`, i.e. **all nine cached payloads already read Final.** (3) **WHERE IT ACTUALLY IS, and no measurement has been taken:** the served status does not come from that map at all. `FEED_LIVE_STATUS` for all nine game_pks reads `present=True source_status_abstract='Final' is_final_predicate=True key_types=['int']` — both readers AGREE and the keying is int — yet at the same instant `/mlb/api/cards?date=2026-09-03` publishes `{"abstract": "Live"}` for those two and the 19:19:37Z board reads them `live`. `_source_status(None)` would give `Pregame/Scheduled`, so the consumer reads a DIFFERENT payload, not a missing one. **Suspect: `build_cards_page_context`'s source for a PAST date — artifact-backed vs inline-built.** REACHABILITY of the shipped fix is proven on the other date: `date=2026-09-04 ... no_cached_payload=16 attempted=16 succeeded=16`. A past date's board artifact IS rebuilt once per worker process (`_BOOK_GRID_LAST_RUN` is an in-process dict), so a RESTART is the only trigger and each deploy gives exactly one 09-03 build ~67s after boot. |
| MLB wrong-slate live-lens overlay | **FIXED ON `main`, NOT DEPLOYED `[2026-09-04, lane live-lens-date-gate]`.** `attach_live_game_state_from_lens` took `selected_date` and, for MLB, used it ONLY in a log line. There is ONE snapshot key per sport, always for `central_today_iso()`, and the grid join is by TEAM PAIR alone — so serving a past date applied TODAY's states to that date's rows, and MLB series repeat a matchup on consecutive days so it MATCHED rather than no-opped. Measured on the served 09-03 board: `lens_games: 16` (the 09-04 slate), `rows_corrected: 187`, `transitions: {'live->pregame': 187}` — 187 is exactly the ATH@SEA row count. A game Final for 28 minutes was published as `pregame 0-0`, and `live_edge_policy` reads `game.state`, so that re-opens edges on a settled market. **THIS DID NOT CAUSE THE MISSING FINALS** — the before-state was `live`, and `build_finals_index` requires `state == 'final'`, so that game was skipped either way; the cause is the row above. Gate is READ-SIDE ONLY: dating the snapshot is forbidden (`learnings.md` 2026-09-03, ~5.76 GB/day into a 256 MB keyvalue store at 86.8%), and the snapshot already carries its slate date. |
| `SYNDICATE_WEB_DYNO` blueprint drift | **RETRACTED 2026-09-04 — THERE IS NO DRIFT. I asserted one and it was an artifact of an UNPAGINATED API read.** Re-read WITH pagination: web `true`, live-odds-worker `false`, refresh-worker `false` (76 / 129 / **153** keys) — matching `render.yaml` exactly. My first read took one `limit=100` page of refresh-worker's 153 and reported the key ABSENT; `CLAUDE.md` warns to paginate this exact endpoint and I did not. **PROVEN FINE, not merely unproven** — independently confirmed from refresh-worker's own logs: `[mlb_cards] FEED_LIVE_PRUNE`, which sits behind `not _render_web_dyno()`, emits there every build (15:57:55Z, 15:59:32Z), and `board_contract_*`/`cards_context_*` memory samples likewise, while the web service emits none of the three. So `_render_web_dyno()` returns False on both workers and every gate behind it is LIVE. Nothing to fix; no deploy taken. |
| Worker-side score retention | **MERGED, NOT RUNNING `[2026-08-28, VERIFIED by content]`.** `74f026a9` moves retention into the board build (appends only when `games_with_outcome` improves), which removes the laptop and the midnight deadline. But `live_gameline_accuracy` is **`null` in the served payload** on both 08-27 and 08-28, and web runs `56e77588` — so it is on `origin/main` and not deployed (`autoDeploy = no`). **Until it deploys, the laptop cron is still the ONLY collector; do not retire the scheduled tasks.** |
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
- **live-odds-worker has NEVER been evicted.** `evicted: false` on all 23
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
- **`SYNDICATE_PORTFOLIO_EXCLUDED_FAMILIES` is UNSET** (default `mlb:player_prop`
  only) and **`SYNDICATE_PORTFOLIO_MIN_EV_PCT=0`**. Neither is a hidden throttle.

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
- **live-odds-worker memory is uptime-driven, not load-driven.** 100.0% at
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
| [nba-betting-card-assets-404] | THE NBA BETTING-CARD CSS AND JS HAVE BEEN 404 IN PRODUCTION -- fixed and landed, NOT DEPLOYED `[measured + fix | `state_basketball.md` |
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
| [wnba-game-state] | WNBA GAME-STATE AND FIXTURE COVERAGE — 2026-08-17 (lane `wnba-live-tier`) — **ARCHIVED 2026-08-19 to `state_ar | `state_basketball.md` |
| [wnba-fixture-identity] | WNBA fixture identity + the sweep ownership gap - VERIFIED 2026-08-17 — **ARCHIVED 2026-08-19 to `state_archiv | `state_basketball.md` |
| [wnba-sweep-ownership-gate] | WNBA SWEEP OWNERSHIP GATE + PHASE 2 AUTORUN `[collapsed 2026-08-18 from three 2026-08-17/18 snapshots; newest  | `state_basketball.md` |
| [basketball-smart-sim-engine] | NBA/WNBA smart-sim: allowlist, dead-gate fix, and an open staleness question — 2026-08-18 (lane `basketball-mo | `state_basketball.md` |
| [wnba-cards-fallback-recursion] | `_artifact_bundle` RE-ENTERED ITSELF 247 FRAMES DEEP AND REPORTED NOTHING — FIXED `[2026-09-03, lane wnba-card | `state_basketball.md` |
| [board-freshness] | BOARD FRESHNESS AND STALENESS | `state_board.md` |
| [board-intelligence-engine] | BOARD / INTELLIGENCE ENGINE — structural facts, archived — **ARCHIVED 2026-08-19 to `state_archive_2026-08-19. | `state_board.md` |
| [locked-cards-retuned-no-autorun] | `locked_cards_retuned` HAS NO AUTOMATIC TRIGGER, ANYWHERE `[measured 2026-08-18]` | `state_board.md` |
| [board-overview-skipped-for-memory] | — VERIFIED 2026-08-27, refresh-worker `277062cd` | `state_board.md` |
| [board-overview-fix-verified] | — VERIFIED 2026-08-27, refresh-worker | `state_board.md` |
| [board-compute-attribution] | — VERIFIED 2026-08-28, refresh-worker `4805abe5` | `state_board.md` |
| [board-window-staleness] | — **CAUSE FOUND AND VERIFIED 2026-08-29. It is neither the queue NOR build cost — see `[week-scoped-board-wind | `state_board.md` |
| [week-scoped-board-window] | SCOPED, NOT BUILT `[2026-08-29]` | `state_board.md` |
| [board-model-edge-coverage] | 2026-08-30 — 82% of the board is UNSIZABLE, and every `_alt` market is 0% | `state_board.md` |
| [live-edge-basis-label] | `edge_basis` WAS WRONG ON EVERY LIVE MONEYLINE ROW, AND THE MEASUREMENT THAT CERTIFIED IT COULD NOT HAVE SEEN THEM — fixed and landed `[2026-09-05, lane edge-basis-moneyline, NO DEPLOY]` | `state_board.md` |
| [nfl-board-projection-coverage] | NFL BOARD PROJECTION COVERAGE IS 100% `[measured 2026-09-04T23:19:34Z on the served payload, lanes nfl-project | `state_football.md` |
| [ncaaf-zero-orders-is-two-gates] | NCAAF SERVES ZERO ORDERS BY DESIGN, and it is TWO gates, not one `[verified 2026-09-01, lane game-market-entry | `state_football.md` |
| [ncaaf-live-resim] | SMARTSIM2 CAN BE RESUMED FROM MID-GAME; ITS ENTRYPOINT COULD NOT `[measured 2026-09-05, lane ncaaf-live-resim]` | `state_football.md` |
| [ncaaf-team-registry-two-files] | THE RESOLVER READS THE *SNAPSHOT*, AND THE FILE BESIDE IT IS OLDER AND DIFFERENT `[measured 2026-09-03]` | `state_football.md` |
| [football-smartsim2] | FOOTBALL (NFL + NCAAF) — smartsim2 runs on FOUR SCALARS `[measured 2026-08-18, lane football-model-owner]` | `state_football.md` |
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
| [kalshi-in-play-and-real-fees] | KALSHI TRADES IN-PLAY AND PUBLISHES ITS OWN FEE PARAMETERS; THE ARB THRESHOLD WAS ABOVE BREAK-EVEN EVERYWHERE  | `state_kalshi.md` |
| [kalshi-segment-on-full-game] | KALSHI PLACED SEGMENT BETS ON FULL-GAME CONTRACTS: the join key had no `segment` `[verified 2026-08-28, lane p | `state_kalshi.md` |
| [kalshi-venue-execution] | KALSHI ORDERS: the blocker was SHARD COLLATERAL, and spreads were inverting the bet `[verified 2026-08-26, lan | `state_kalshi.md` |
| [kalshi-coverage-vs-oddsapi] | KALSHI COVERAGE: capture is healthy, the JOIN is the bottleneck, and two prop vocabularies do not exist `[veri | `state_kalshi.md` |
| [kalshi-execution] | Kalshi execution — session close 2026-08-26 (lane `kalshi-exchange-index`) | `state_kalshi.md` |
| [kalshi-odds-refresh-bound] | THE VENUE FAN-OUT IS A COLD-START BURST ON A PERSISTED CLOCK, AND IT IS NOW TIME-BOUNDED `[2026-09-03, lane ka | `state_kalshi.md` |
| [layer2-board-keyvalue-ceiling] | THE BOARD'S CEILING IS THE COMBINED KEY, NOT THE SHARDS — and `per_sport=3000` corrupted production for ~29 mi | `state_layer2.md` |
| [layer2-realized-accuracy] | THE LAYER 2 BOARD'S REALIZED ACCURACY — the portfolio book is the surface, and the measurement chain is broken | `state_layer2.md` |
| [layer2_board_display] | LAYER 2 BOARD -- USER-VISIBLE DISPLAY BUGS, 2026-08-20 AUDIT | `state_layer2.md` |
| [layer1-layer2-boards] | LAYER 1 / LAYER 2 BOARDS — session briefs exist; three facts worth not re-deriving `[code read 08-16 11:2x CDT | `state_layer2.md` |
| [layer1-board-date-scoping] | THE BOARD WAS DROPPING GAMES TWO WAYS — both FIXED AND VERIFIED `[verified 2026-08-30 05:0x-05:5xZ, web+refres | `state_layer2.md` |
| [board-chip-coverage] | Layer 2 compact game cards — FULL chip coverage, verified 2026-08-26 | `state_layer2.md` |
| [chip-artifact-content-age] | A chip artifact's TIMESTAMP and its CONTENT age are different numbers — verified 2026-08-27 (lane `mlb-chip-li | `state_layer2.md` |
| [ci-suite-red-test] | CI'S OWN SUITE IS GREEN. THE "ONE RED TEST" WAS THE 31st DATA-ABSENCE FAILURE, NOT A SURVIVOR OF THEM `[correc | `state_ledger.md` |
| [state-file-split] | state.md IS AN INDEX PLUS NINE PARTS `[2026-09-03, scripts/split_state.py, commit 23bf6bc7]` | `state_ledger.md` |
| [session-harness] | SESSION HARNESS — what the hooks actually enforce | `state_ledger.md` |
| [worktree-test-data] | THE 92 RED TESTS IN A SESSION WORKTREE ARE THE ENVIRONMENT, NOT DEFECTS `[measured + shipped 2026-09-03]` | `state_ledger.md` |
| [test-baselines] | TEST BASELINES | `state_ledger.md` |
| [lane-state-carried] | LANE STATE RECORDS CARRIED THROUGH THE 2026-08-18 COLLAPSE — **ARCHIVED 2026-08-19 to `state_archive_2026-08-1 | `state_ledger.md` |
| [lane-guard-disclaimer-and-worktree-exemption-bugs] | TWO REAL BUGS FOUND IN `lane-guard.py`, NEITHER FIXED `[found 2026-08-18]` — **ARCHIVED 2026-08-19 to `state_a | `state_ledger.md` |
| [split-state-reindex-truncation] | `split_state.py --reindex --apply` DELETED EVERYTHING BELOW THE `[subject-index]` TABLE — **FIXED, ON MAIN (`2 | `state_ledger.md` |
| [discard-guard-origin-blindness] | `discard-guard.py` CALLED PUSHED CONTENT "NOWHERE ELSE", AND BLOCKED `git restore --staged` — **FIXED (`e3a515 | `state_ledger.md` |
| [mlb-hitter-strikeouts-prop] | MLB HITTER `strikeouts` WAS A DEAD FIELD FOR MONTHS; FIXED, DEPLOYED AND VERIFIED — AND NO BET WAS EVER PRICED | `state_mlb.md` |
| [mlb-sim-edge-is-anti-predictive] | THE MLB SIM'S CLAIMED EDGE IS ANTI-PREDICTIVE, AND THE PROP BOOK IS A REAL EDGE SPENT ON VIG `[verified 2026-0 | `state_mlb.md` |
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
| [ledger-and-primary-tree] | — MEASURED 2026-09-02, this machine | `state_model.md` |
| [ledger-precommit-guard] | LEDGER COMMITS ARE GUARDED AT TWO LEVELS — VERIFIED 2026-09-02 | `state_model.md` |
| [replay-diff-gate] | A PRODUCTION DAY NOW REPRODUCES OFFLINE, 0 MISMATCHES — and two board blocks provably CANNOT `[verified 2026-0 | `state_model.md` |
| [lane-ledger-conflict-guard] | THE LANE CHECKER USED TO PASS A FILE WITH CONFLICT MARKERS IN IT `[fixed 2026-08-30, `10f45a0c`; scope MEASURE | `state_model.md` |
| [settlement-resolver-coverage] | SETTLEMENT: NFL CAN BE GRADED, NCAAF IS WIRED-BUT-UNVERIFIED, and three sports still cannot settle a bet `[ver | `state_model.md` |
| [execution-ledger-cross-service-race] | THE MONEY LEDGER IS READ-MODIFY-WRITTEN BY TWO SERVICES WITH NO LOCK, and settlement writes are being silently | `state_model.md` |
| [probability-statistic-ownership] | PROBABILITY-STATISTIC OWNERSHIP `[measured 08-15, shipped `2ac3c6bc`]` | `state_model.md` |
| [nhl-sim-engine] | NHL SIM (hockeysim) — `nhl_sim_input_checklist.py` PASSES, exit 0 `[measured 2026-08-20, lane nhl-model-owner] | `state_model.md` |
| [model-skill] | MODEL SKILL (`#428`) — measured vs not | `state_model.md` |
| [sim-scheduling-blocker] | 2026-08-17 02:1xZ — VERIFIED (sim-scheduling): the primary goal has ONE blocker — **ARCHIVED 2026-08-19 to `st | `state_model.md` |
| [sim-edge-analysis-2026-09-01] | FULL-PLATFORM SIM-ENGINE EDGE ANALYSIS — strategy synthesis + new from-code facts `[2026-09-01, session syndic | `state_model.md` |
| [accuracy-autorun-rearm-state] | `#626`(h) IS ARMED, RAN, AND PASSED. The budget, not memory, is now the constraint. `[2026-09-04, lane accurac | `state_model.md` |
| [polymarket-live-totals-quote-names-no-game] | 26 OF 28 LIVE POLYMARKET TOTALS QUOTES ON THE BOARD ARE SHARED ACROSS GAMES — one price per LINE, no game iden | `state_polymarket.md` |
| [polymarket-fill-price-is-reported] | THE VENUE REPORTS `avgPx`. "This path has no fill price" was FALSE and cost a 12h live halt `[verified 2026-08 | `state_polymarket.md` |
| [polymarket-h2h-buys-the-wrong-side] | POLYMARKET MONEYLINES BUY THE WRONG TEAM: `outcomes[0]` is not reliably the YES leg `[verified 2026-08-28, lan | `state_polymarket.md` |
| [polymarket-vs-kalshi-prop-prices] | — MEASURED 2026-09-01, MLB, production shard | `state_polymarket.md` |
| [polymarket-low-activity] | — VERIFIED 2026-08-27, refresh-worker + live-odds-worker | `state_polymarket.md` |
| [polymarket-venue-join] | VERIFIED 2026-08-29, all three services on `95c4fb12` | `state_polymarket.md` |
| [polymarket-orders-are-cancelled] | 2026-08-30 — the venue cancels them, we re-place them, and nobody knows why | `state_polymarket.md` |
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
| [portfolio-live-surface] | `/portfolio` IS THE LIVE BUYING ENGINE, the venue caps BIND, and the VENUE now settles our bets `[verified 202 | `state_portfolio.md` |
| [portfolio-settlement] | PORTFOLIO SETTLEMENT — the ledger crossed no service boundary, and the join keyed on a value that drifts `[ver | `state_portfolio.md` |
| [order-model-attribution] | AN ORDER RECORDS THE SIM'S VERDICT — DEPLOYED AND VERIFIED ON PRODUCTION; THE COMMIT GATE MAKES FOUR OF THE NI | `state_portfolio.md` |
| [soccer-market-anchor] | MARKET-ANCHORING IS REACHABLE AND STILL OFF BY DECISION — MEASURED 2026-09-02 `[lane soccer-anchor-cost, main  | `state_soccer.md` |
| [soccer-board-coverage] | — MEASURED 2026-09-02, production, NOT A DEFECT | `state_soccer.md` |
| [soccer-live-match-state] | Soccer's live tier is WIRED AND VERIFIED ON LIVE MATCHES (2026-08-21) | `state_soccer.md` |
| [soccer-live-momentum] | FotMob momentum is production's signal now; the ESPN proxy carries none (2026-08-22) | `state_soccer.md` |
| [soccer-compact-cards] | Pregame + final compact cards redesigned and DEPLOYED, verified on production HTML (2026-08-22) | `state_soccer.md` |
| [soccer] | SOCCER | `state_soccer.md` |
| [soccer-live-tier] | SOCCER'S LIVE TIER — VERIFIED, AND WHAT IS NOT | `state_soccer.md` |
| [soccer-shots-prop-skill] | SOCCER SHOTS PROPS â€” THE POISSON SHAPE IS RIGHT AND THE MEAN IS INFLATED `[measured 2026-08-31, lane layer1- | `state_soccer.md` |
| [live-lens-snapshot] | THE LIVE-LENS SNAPSHOT CANNOT BE DATED — it is a 4 MB KEYVALUE key, not a file, and archiving it would cost ~5 | `state_ui.md` |
| [live-surface-tier5] | THE LIVE SURFACE — Tier 5 `[measured 08-15 02:3x–03:0xZ]` | `state_ui.md` |
| [ask-the-syndicate] | ASK THE SYNDICATE | `state_ui.md` |
| [ui-board-cards] | UI / BOARD CARDS | `state_ui.md` |
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
| [refresh-worker-headroom-2026-09-02] | THE ~1.4GB HEADROOM FIGURE IS STALE, AND THE METRIC EVERYONE READS IS THE WRONG ONE `[2026-09-02, lane m625-en | `state_worker.md` |
| [accuracy-autorun-OOM-2026-09-02] | THE ACCURACY AUTORUN OOM-KILLED refresh-worker. **RESOLVED — DISARMED AND VERIFIED 19:32Z.** `[2026-09-02, lan | `state_worker.md` |
| [local-fleet-runner] | THE THREE SERVICES RUN LOCALLY NOW — and doing it naively would have placed REAL ORDERS `[verified 2026-09-02, | `state_worker.md` |
| [artifact-allowlist-split] | THE ARTIFACT ALLOWLIST IS TWO LISTS NOW: READ WIDE, WRITE NARROW — and an allowlist-filtered inventory is NOT  | `state_worker.md` |
| [service-memory-saturation] | BOTH PRODUCTION SERVICES WERE MEMORY-SATURATED 2026-09-02/03 — MEASURED, and it BLOCKS analysis work `[lane so | `state_worker.md` |
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

### `[web-oom-leak]` UPDATE — the instrument is fixed and the growth has a SUSPECT, 2026-09-04T00:4xZ `[session b2b5b45b]`

**Supersedes the "needs an INSTRUMENT change" line in the entry above — that
change shipped (`442f82fe`) and is verified REACHED**, not merely deployed:
emissions carry `attribution_basis = process_anon_smaps_rollup` with a non-null
`process_anon_mb_now` and `unreadable = 0`. Attribution now differences THIS
PROCESS's anon (`/proc/self/smaps_rollup`), so its scope matches the per-worker
`inflight` guarantee.

**THE PREVIOUS CULPRIT WAS AN ARTEFACT.** `/api/ops/artifacts/publish` read
**211 MB** container-scoped and reads **1.15 MB across 81 solo requests**
per-process. A publish spawns a merge CHILD; the container-scoped instrument
charged the child to the parent's request. **Any earlier conclusion pointing at
publish came from measuring the wrong scope.**

**THE SUSPECT: `/api/intelligence/query`, ~82 MB PER CALL** — 408.0 MB over 5
calls, replicated on both workers. Infrequent and very expensive; nothing else is
within an order of magnitude (publish moves tens of MB across HUNDREDS of calls).
It does NOT recompute — `read_combined_intelligence_response` only reads what the
background loop already built — it MATERIALISES AND HYDRATES a large precomputed
payload, and CPython does not return freed arenas. `intelligence.py:1600` notes
slimming that payload would change an API contract, so the fix is not free.

**THE RANKING IS TRUSTWORTHY; THE SHARE IS NOT.** Attributed 408 MB against
342 MB of actual process growth. One contamination source remains and it is
named: `syndicate/app.py` runs the live-refresh and intelligence-state loops IN
THE SAME PROCESS, and `inflight` guarantees no other REQUEST, not no other
THREAD. Of three sources — cross-worker, merge children, same-process threads —
two are gone.

### `[web-oom-leak]` UPDATE 2 — the payload is down ~74% and the instrument is honest, 2026-09-04T02:3xZ `[session b2b5b45b]`

* **Per-request attribution now measures THIS PROCESS** (`/proc/self/smaps_rollup`),
  so its scope matches the per-worker `inflight` guarantee (`442f82fe`, verified
  REACHED). **Supersedes every earlier route ranking**: `/api/ops/artifacts/publish`
  read 211 MB container-scoped and **1.15 MB across 81 solo requests** per-process,
  because a publish spawns a merge CHILD that the old scope charged to the parent.
* **The largest per-request allocator is `/api/intelligence/query`, ~82 MB/call**
  (408 MB over 5 calls, both workers). It does NOT recompute; it materialises and
  hydrates a large precomputed payload.
* **That payload is now ~74% smaller.** The self-nested mirror is gone (50.0%,
  `53a1052b`) and the alias duplication is opt-in-slimmed (47.9% on a same-slate
  live A/B, `b3966bf1`): `recommendations` -> `top_opportunities`, `boardContract`
  -> `board_contract`, `by_sport` regrouped from `ranked_all`, described in
  `_response_aliases` and rebuilt client-side.
* **OPT-IN: a caller that does not send `slim_aliases` is byte-for-byte
  unaffected.** Verified live; a test exists whose only job is to fail if that
  ever changes.
* **STILL OPEN:** one contamination source remains and it is named —
  `syndicate/app.py` runs the live-refresh and intelligence-state loops IN THE
  SAME PROCESS, and `inflight` guarantees no other REQUEST, not no other THREAD.
  So the route RANKING is trustworthy and the exact SHARE is not.
* **NOT re-measured:** whether the ~74% cut moves the ~500 MB/h growth rate. That
  needs a fresh uninterrupted window.

### `[web-oom-leak]` UPDATE 3 — the rate is re-measured: +173 MB/h, down 66%, 2026-09-04T03:2xZ `[session b2b5b45b]`

**Supersedes the "NOT re-measured" line in UPDATE 2.** Fitted on 81 merge-child-free
plateau samples (25.5-62.7 min uptime) on web `b3966bf1`: **+173 MB/h, R^2 0.90**,
against the pre-cut **+503 MB/h, R^2 0.75, n=32**. Time to the 2,048 MB limit goes
**2.0 h -> 5.7 h**, i.e. past the 2.45-3.13 h uptimes at which this service was
being OOM-killed.

**Confounded in two ways, both registered before the measurement:** different time
of day (02:40Z vs 22:30Z), and the alias half of the payload cut is OPT-IN so it
only applies when a browser drives the page — meaning **-66% is most plausibly the
self-mirror half alone**. Consistent with the fix; not proof of it.

### `[web-oom-leak]` UPDATE 4 — rate down 66%, four mechanisms ruled out, 2026-09-04T14:5xZ `[session b2b5b45b]`

* **Growth rate re-measured after the payload cut: `+503 -> +173 MB/h`** (fitted,
  R^2 0.90, n=81 merge-child-free plateau samples). Time to the 2,048 MB limit
  **2.0 h -> 5.7 h**, past the 2.45-3.13 h uptimes at which web was being killed.
  Confounded by time of day, and the alias half of the cut is opt-in — so this is
  consistent with the fix, not proof of it.
* **The attributed SHARE is still not recoverable, and four candidates are now
  eliminated by measurement:** cross-worker cgroup scope (CONFIRMED, fixed by
  per-process anon); background loops (FALSIFIED — neither runs on web, and the
  gate built for them is INERT); GC timing (EXCLUDED — the one gen-2-overlapping
  request was POSITIVE while the non-overlapping group went negative);
  `LAST_RESULT` reassignment (EXCLUDED — 0.0 MB both halves).
* **THE CONSTRAINT THAT KILLS PER-STATEMENT PROBES:** CPython returns freed
  objects to pymalloc's ARENAS, not to the OS. An in-Python free cannot reduce
  `Anonymous:`. A negative anon delta therefore requires ARENA RELEASE — an
  emergent property of allocator free-list state, attributable to no statement,
  request or thread.
* **NEXT INSTRUMENT, if the symptom returns:** `malloc_info` / pymalloc arena
  counts around the negative windows, not another attribution probe.
  `memory_observability` already carries `parse_smaps` and `#435`'s arena-vs-anon
  comparison. The question is "when does an arena empty".
* The symptom is INTERMITTENT — zero negative routes in the last two windows.
  Nothing is confirmed; four things are ruled out.

### `[web-oom-leak]` UPDATE 5 — **POSITIVELY IDENTIFIED: 8-64MB anon mappings**, 2026-09-04T18:09Z `[session b2b5b45b]`

* **The growth is in LARGE ANONYMOUS MAPPINGS (8-64MB regions).** Measured on
  `76c0e174` via `smaps_trend` split by pid, gate pre-registered before the data:
  pid 79 `+148.70 MB / 37.3 min` with **80.5% in `8-64MB`**; pid 78
  `+54.10 MB / 34.6 min` with **85.4%** there. `UNNAMED` `0.00` on both — the
  breakdown sums to its own total. `<64KB` and `64KB-1MB` unchanged to the
  decimal across all 12 readings.
* **This is the first POSITIVE finding in `#632`; the previous five were
  exclusions.** It also explains WHY they were: pymalloc arenas cover ~40% of
  worker RSS and glibc `malloc_info` reached 13.9% coverage in `#435`. **Both are
  structurally blind to an allocation over 512 bytes**, so their flat readings
  were never evidence of a flat process.
* **CORRECTS an intermediate claim made the same session.** With only the size
  buckets recorded, the residual computed by subtraction read as 65-70%
  "non-mmap" and I proposed glibc's main arena. Recording `by_kind_mb` retired
  that: heap is **7.4% / 14.6%**, a minority term.
* **NOT ESTABLISHED:** what allocates those regions; and the rates
  (`+239.4` vs `+93.7 MB/h`) are EARLY-LIFE and not comparable to the `+173 MB/h`
  plateau figure. **The two workers differ 2.6x on one container in one window,
  unexplained.**
* **NEXT MEASUREMENT:** does the climb track which worker serves
  `/api/intelligence/query`? That discriminates the payload story from
  everything else, and it is answerable with the instrument already deployed.

### `[web-oom-leak]` UPDATE 6 — **query correlation is NULL, and `/api/intelligence/query` was never called**, 2026-09-04T18:2xZ `[session b2b5b45b]`

* **NO ROUTE'S CALL RATE EXPLAINS THE 8-64MB GROWTH.** Per-worker, per-interval,
  every quantity as a PER-MINUTE RATE (n=13 intervals, 2 workers): after
  dropping one high-leverage point every `|r| < 0.45`, and Pearson disagrees
  with Spearman in SIGN on three of five routes.
* **The `/api/intelligence/query` payload hypothesis is FALSIFIED for this
  window — the route received ZERO calls on either worker** while anon climbed
  +54.1 and +148.7 MB. The growth does not need an intelligence query to happen.
* **Two correlations that looked real and were not:**
  - Unnormalised, `/healthz` ranked TOP at `r=+0.682` — a route with
    `max_mb 0.00`. Differencing over UNEQUAL intervals let duration drive both
    sides. `/api/ops/artifacts/export` fell from `+0.348` to **`+0.037`** once
    normalised; the export hypothesis died there.
  - `/api/ops/artifacts/publish` at `r=-0.882` collapsed to **`-0.271`** when one
    3.1-minute interval was dropped. That was a claim about one point.
* **NEW AND POSITIVE: the 8-64MB memory IS RETURNED TO THE OS.** One interval
  (pid 79, 18:09:52->18:13:00) fell **-43.4 MB**. Large mappings are `munmap`ped
  back, unlike pymalloc arenas. **So this is not monotonic retention** — it is
  churn with a high-water mark, which is a different defect and admits different
  fixes (bounding concurrent peak, not finding a "leak").
* **INSTRUMENT LIMIT, stated so the null is read correctly:** emissions fire
  every 200 solo requests, giving 3-9 minute intervals and n=13. That is coarse
  enough to hide a real per-call effect. **This null bounds the effect size; it
  does not prove independence.**

### `[web-oom-leak]` UPDATE 7 — per-request attribution **FAILED ITS SHARE CHECK**, 2026-09-04T19:3xZ `[session b2b5b45b]`

* **A per-request smaps sampler was built, deployed (`5314e85b`, live 19:11:55Z)
  and its verdict WITHDRAWN.** It reported `/api/ops/artifacts/export` at
  **+145.10 of +145.10 MB** (100%); the share check against each process's own
  8-64MB climb gave **pid 79 = 0.0%** (process +90.30 MB, sampled requests
  +0.00) and **pid 80 = 175.0%** (process +23.20, attributed +40.60).
* **`sum(sampled)/sum(sampled)` is 100% by construction.** The denominator was a
  set of routes I chose, not the process's climb. Failing in BOTH directions
  rules out a scale error.
* **WHAT STANDS:** three events where ONE `/api/ops/artifacts/export` call grew
  anon by **39.9 / 56.9 / 48.3 MB** in the 8-64MB bucket and had not released it
  at teardown; two fired **one second apart**. 16 of 19 export calls cost
  **exactly 0.00**. The bimodality explains why five earlier probes read flat and
  why the route correlation was `r=+0.037`: a rare ~50 MB event averaged over
  3-9 minute intervals disappears.
* **WHAT DOES NOT STAND:** any claim about the FRACTION of `#632` those events
  represent.
* **WHY, hypothesised not established:** the sampler covers SOLO requests on an
  allowlist of two routes, and `skipped_concurrent` was **285** — most export
  calls are never sampled. pid 80's >100% additionally implies memory released
  after the window, consistent with the observed `-43.4 MB` interval.
* **INSTRUMENT COST: 64.93 ms mean / 150.50 ms max per sampled request**, 28-64x
  the synthetic estimate. Allowlist set to the sentinel `__off__`.
* **NEXT:** attribution must cover ALL requests, not an allowlist, and needs
  process readings dense enough to divide by — an emission every 200 solo
  requests cannot verify a 10-minute window.

### `[web-oom-leak]` UPDATE 8 — `proc_token` shipped INERT (fork inheritance); residual still unmeasured, 2026-09-04T20:3xZ `[session b2b5b45b]`

* **`proc_token` was generated at IMPORT and gunicorn forks workers AFTER the
  import**, so every worker inherited the same value — pid 99 and pid 98 both
  emitted `6178fc632433` (measured 20:24-20:26). Fixed by deriving it lazily and
  re-minting whenever `os.getpid()` changes (`b36d993f`).
* **The broken version produced a CONFIDENT WRONG ANSWER, not a null:**
  `r = +0.870`, "residual tracks skipping", 18.0% coverage over 3 "clean"
  windows. **DISCARDED** — those windows differenced one worker against another.
  The tell was a window reporting `solo 0` beside `attributed -103.22 MB`.
* **The residual is therefore STILL UNMEASURED.** Nothing about skipped requests
  as the gap is established; the earlier `r = +0.870` must not be quoted.
* Two instrument defects fixed and landed before it (`63e45361`): `routes` is
  truncated to `top=12` (differencing it read **4842% unexplained**), so
  `attributed_total_mb` is now untruncated; and `skipped_concurrent` counts
  CONTAMINATED WINDOWS, not requests — one overlap increments it twice.
* **NEXT:** collect >= 3 windows on `b36d993f`, with the collector refusing any
  token that spans more than one pid.

### `[web-oom-leak]` UPDATE 9 — **the residual is measured: 82.3% covered, and skipping is NOT the gap**, 2026-09-04T21:3xZ `[session b2b5b45b]`

* **16 clean windows, 2 distinct process tokens, ~50 min: process `+669.30 MB`,
  attributed `+550.67 MB`, residual `+118.63 MB` — 82.3% COVERED.** Stable under
  doubling n (75.9% at n=8). This is `#632`'s first stable share.
* **FALSIFICATION TEST FIRED — the residual does NOT track `skipped_concurrent`:**
  pearson `+0.236`, spearman `-0.047`, and `+0.087` without the single leverage
  window. Skipped requests are not the gap; the solo-only rule is not what hides
  the memory.
* **PER-WINDOW COVERAGE IS UNUSABLE** (`-130%` to `+452%`, over 100% in five
  windows, negative in four). Under munmap-heavy churn, a per-request delta and a
  net process change are different quantities. **Quote the aggregate, never a
  window.**
* `residual` vs `process climb` (pearson `+0.856`) is PARTLY DEFINITIONAL —
  `residual = process - attributed`. Not independent evidence.
* **Three earlier verdicts from this same collector were wrong**, all small-n
  coefficients: `-0.999` at n=3, `+0.870` on merged workers, `+0.710` at n=8
  collapsing to `-0.297` on leave-one-out. Gate is now n>=8 + leave-one-out +
  Spearman beside Pearson.
* **NEXT for `#632`:** the 8-64MB mappings are identified and requests own ~82%
  of the movement, but no single route owns it and per-request attribution
  cannot be made to compose. The open question is the remaining ~18% and whether
  the churn HIGH-WATER MARK — not a leak — is what OOMs the service.

### `[web-oom-leak]` UPDATE 10 — **RETENTION, not churn. Two independent instruments agree**, 2026-09-04T22:4xZ `[session b2b5b45b]`

* **`VmHWM - VmRSS` is ~29 MB on BOTH workers** (pid 98: 682.98 vs 654.28; pid 97:
  640.88 vs 612.09), and `process_anon_mb_now` EQUALS the running peak on both.
  A process sitting at its own all-time high-water mark has not returned memory.
  **Churn would show a large HWM-RSS gap. It does not.**
* **Independent confirmation from a 60-sample RSS poll of `/api/ops/memory`**
  (20 min, 20 s cadence): in EVERY series the floor equals the FIRST reading —
  worker 97 `380.8 -> 612.1`, worker 98 `434.8 -> 811.0 peak`, container
  `1248.0 -> 2037.0 peak`, unreclaimable `793.4 -> 1403.3 peak`. **Nothing ever
  returned below where it started.**
* **The container touched `2037.0 MB` — 99.5% of the 2048 MB limit**, ~11 MB of
  headroom, at a moment when a transient merge child (pid 198, 94 MB) was
  present. Steady state at the time of writing: **1888.5 MB, 92.2%, 159.5 MB
  headroom**.
* **THE SYNTHESIS, and it corrects an earlier reading in this same session:**
  worker retention is the DOMINANT term and transient children are a small
  additive one. An earlier note called them roughly equal partners; the
  `VmHWM-VmRSS` reading settles it. The children matter only because they land
  on a floor that retention has already raised.
* **INSTRUMENT DEFECT, mine:** `anon_extremes.floor_mb` is a RUNNING MINIMUM,
  and a running minimum over a rising series is always the FIRST reading — it
  can never rise, so it cannot detect a rising floor, which is the question it
  was built for. Both floors are pinned at their boot values. What answered the
  question was `VmHWM` vs `VmRSS`, added as a secondary reading. A WINDOWED
  minimum (last N) is the correct design.
* **`unexplained_memory_mb` is 385.5 MB** and is not yet investigated.

### `[web-oom-leak]` UPDATE 11 — merge caps lowered and **UNTESTED**; growth is NOT merges; the restart buys ~15 min, 2026-09-04T23:0xZ `[session b2b5b45b]`

* `SYNDICATE_ARTIFACT_MERGE_CHILD_CAP` **2 -> 1** (`e3a5154f`) and
  `SYNDICATE_ARTIFACT_MERGE_INFLIGHT_MB` **-> 16** (`3a9153f4`), both deployed on
  CLEAR preflights. **verify: UNTESTED — 0 merge children in 75 polls / ~20 min.**
* **The container ramped `1066.8 -> 1988.5 MB` (52% -> 97%) with NO merge child
  running.** Merges are not the driver of the current growth; both changes bound
  a path that is not firing.
* **The restart bought ~15 MINUTES, not hours:** `1888.5 (92.2%) -> 1133.4
  (55.3%)` at go-live, back to `1871.4` within 20 min.
* **CORRECTS my own earlier estimate.** I said "a few hours", carrying the
  `+173 MB/h` plateau rate from a quiet period into a much busier regime.
  Measured: `52% -> 96.7% in 11 minutes`. Stale baseline, different regime.
* Merge children are INTERMITTENT (two in flight at 22:29Z, pids 281/284, which
  delayed the first deploy) — so the caps may be exercised in a later window.
* **`#632` STILL HAS NO FIX.** Retention is the dominant mechanism (`VmHWM -
  VmRSS` ~29 MB both workers; every polled series floor == first reading), it has
  no identified owner, and neither env change touches it.

### `[web-oom-leak]` UPDATE 12 — **CORRECTION to UPDATE 10: it is BOTH, and my "retention, not churn" rested on one time point**, 2026-09-04T23:2xZ `[session b2b5b45b]`

* **UPDATE 10 said "RETENTION, not churn" on the strength of `VmHWM - VmRSS`
  reading ~29 MB on both workers. A later emission from the SAME session
  undercuts it.** The full series, in time order:

        22:17:09  pid 98   HWM 436.0  RSS 389.3   gap  46.8
        22:20:49  pid 97   HWM 606.2  RSS 571.9   gap  34.4
        22:22:57  pid 98   HWM 683.0  RSS 606.0   gap  77.0
        22:29:14  pid 97   HWM 640.9  RSS 612.1   gap  28.8
        22:31:00  pid 98   HWM 683.0  RSS 654.3   gap  28.7
        22:36:33  pid 97   HWM 766.8  RSS 612.1   gap 154.7   <-- 155 MB RETURNED

* **pid 97 reached 766.8 MB and came back down ~155 MB** — memory RETURNED, which
  is churn. **pid 98 held its HWM flat at 683.0 while RSS climbed 606.0 -> 654.3**
  — memory RETAINED. **Two workers in one container doing different things.**
* **The 29 MB reading I built a verdict on was a COINCIDENCE of one sample
  instant**, when both workers happened to sit near their peaks. Two emissions
  later the same worker read 154.7.
* **Correct statement: BOTH mechanisms are present.** Peaks are returned
  sometimes, and the baseline still trends up. UPDATE 10's exclusive framing is
  withdrawn; the container-level facts in it (ramp `1066.8 -> 1988.5`, restart
  buying ~15 min) stand.
* The `anon_extremes` collector printed `VERDICT: ... CHURN` — **ignore that
  line.** It is computed from `floor_mb`, a running minimum that cannot rise
  (UPDATE 10 records the defect). Its own caveat says to read `VmHWM - VmRSS`
  instead, which is what the series above does.
* **METHOD NOTE:** a single-timepoint reading of a monotone-vs-current gap cannot
  distinguish these mechanisms — the gap is near zero whenever a process happens
  to be AT its peak, regardless of whether it returns memory later. It needs a
  SERIES, and UPDATE 10 did not have one.

### `[web-oom-leak]` UPDATE 13 — **the retainer is NOT a module-level container: census explains 6.1% of growth**, 2026-09-05T02:5xZ `[session b2b5b45b]`

* **Two readings, one worker, 13.7 min apart, budget not exhausted:** census
  `59.0 -> 64.9 MB` (+5.9) while process anon went `389.3 -> 486.1 MB` (+96.8).
  **The census explains 6.1% of the growth.** Level coverage 15.6% / 12.5% on the
  two workers.
* **NAMED RETAINERS (level, not growth):**
  `_COMBINED_INTELLIGENCE_RESPONSE_CACHE` **~20 MB in ONE entry**;
  `soccer.cards._CARDS_CONTEXT_CACHE` 14.45 MB / 29;
  `mlb.cards._MLB_CARDS_CONTEXT_CACHE` 6-10 MB / 4 (**+11.21 MB on one added
  entry**); `_MLB_TODAY_CACHE` 7.6-10 MB; `LAST_RESULT` ~5 MB.
* **`LAST_RESULT` reconciles two earlier readings:** it HOLDS ~5 MB and grows
  0.0 MB per request. The per-request probe was right and so is this.
* **READ THE LIMIT BEFORE QUOTING THE 6.1%:** the walk's ROOTS are module globals
  that are already containers. A module-level OBJECT with caches in its
  `__dict__`, a class attribute, a closure, or thread-local state is never
  reached. The claim is **"not in container-typed module globals"**, NOT "not in
  Python". Widening the roots is the next step.
* **Instrument cost:** 1.2 s, ~10 MB transient, walk completes at 2M nodes. At
  lower caps the budget exhausts and the ranking becomes *biggest among whatever
  was reached first* — the 20k/100k/400k runs are NOT quotable.
* Worker anon grew **+96.8 MB in 13.7 min (~424 MB/h)** during this window,
  consistent with the fast regime measured earlier tonight.

### `[web-oom-leak]` UPDATE 13 — **the retained bytes are NOT Python objects (28.3%). The object-graph line is CLOSED.**, 2026-09-05T20:4xZ `[session b2b5b45b]`

* **Measured on pid 98 with a CONVERGED walk (891,276 nodes, not truncated):
  process anon `373.17 MB`, live Python objects `105.56 MB` — `28.3%`.
  `267.61 MB` (71.7%) is not Python objects.** Threshold pre-registered before
  the reading (`>=70%` Python / `<=35%` not).
* Convergence was the whole point: the same call read `7.2%` at a 200k cap and
  `28.5%` at 800k, both TRUNCATED. **A truncated walk reads as "not Python" —
  the correct answer here, reached for the wrong reason at any smaller cap.**
* **CORROBORATION, not proof:** an arena reading from a different worker hours
  earlier gave `bytes_in_allocated_blocks = 105.731 MB` against this walk's
  `105.56 MB` — independent methods agreeing to `0.16%`. Different epochs, so
  suggestive only.
* Implied decomposition (same caveat): `105.6 MB` live objects, `44.3 MB`
  pymalloc fragmentation, `223.2 MB` **outside pymalloc arenas entirely** —
  where the 8-64MB mappings identified earlier must live.
* **CLOSED: no Python-level probe can reach the 71.7%.** Root sets, retainer
  censuses and per-request attribution are all blind to non-object bytes.
  Remaining candidates: C-extension buffers, allocator behaviour below CPython,
  per-thread state.
* **STILL WORTH DOING, on its own merits and not as an OOM fix:**
  `_COMBINED_INTELLIGENCE_RESPONSE_CACHE` **37.50 MB** and
  `_CARDS_CONTEXT_CACHE` **12.67 MB** are real, nameable, unbounded caches.
* The census table and the heap ratio came from DIFFERENT workers (pid 99 vs
  98) — the endpoint round-robins. The ratio is self-consistent; the table is
  not a breakdown of it.

### `[web-oom-leak]` UPDATE 14 — **the GROWTH is non-Python too, not just the standing total**, 2026-09-05T21:0xZ `[session b2b5b45b]`

* UPDATE 13 measured a STOCK ratio at one instant (28.3%). That does not answer a
  GROWTH question — a heap could hold 28% of anon and still be the entire
  growing term. **Measured over 10.9 min, per worker, every walk CONVERGED (0
  truncated readings discarded):**

        pid 97   anon  +56.26 MB   heap  +0.19 MB   =  0.3% of the growth
        pid 98   anon +107.06 MB   heap +24.50 MB   = 22.9% of the growth

* **pid 97 is the decisive case: its Python heap sat at `104.68 -> 104.87 MB`,
  flat to 0.2 MB, while anon climbed 56 MB.** The verdict is upgraded from a
  snapshot to a trend: the growth itself is non-Python.
* **pid 98's 22.9% is an UPPER BOUND, not a measurement.** Consecutive walks on
  that worker swung `184.23 -> 167.18 MB` (~17 MB), so its `+24.50 MB` delta is
  only modestly above the instrument's own noise. Quote pid 97's `0.3%`.
* **RATE, measured in the same window and it is steep:** pid 97 `~307 MB/h`,
  pid 98 `~590 MB/h`, ~900 MB/h combined. Container at the end: **1756.6 MB,
  85.8%, 291 MB headroom.**
* Nothing changes about the `#632` conclusion except its strength: no
  Python-level probe can find the growing bytes.

### `[web-oom-leak]` UPDATE 15 — **CORRECTION: I quoted page cache as OOM pressure. Real pressure is 54%, not 86%.**, 2026-09-05T21:2xZ `[session b2b5b45b]`

* **`container_memory_mb` INCLUDES RECLAIMABLE PAGE CACHE and is NOT the OOM
  metric.** I quoted `1756.6 MB / 85.8% / 291 MB headroom` and projected an OOM
  in ~20 minutes. Minutes later the same figure had FALLEN to `1509.1 MB` while
  both workers' RSS went slightly UP — a ~247 MB move that no process made.
* Split over 5.1 min (7 samples, 50 s apart):

        total           +151.2 MB   -> +1786 MB/h   (cache swung 469 -> 588 MB)
        UNRECLAIMABLE    +98.8 MB   -> +1167 MB/h
        pid 98 rss       +53.9 MB
        pid 97 rss       +44.2 MB   (sum 98.1 ~= unreclaimable 98.8: consistent)

* **Standing pressure is `1103.7 MB` unreclaimable of 2048 = 54%**, not the 86%
  I reported. The difference is ~570 MB of file cache the kernel evicts under
  pressure before it OOMs anything.
* **GROWTH IS BURSTY, so no rate from a short window is trustworthy — including
  the ones above.** Both workers rose ~98 MB between 16:17:43 and 16:19:25 and
  were then FLAT to the decimal (`595.3` / `509.4`) for the remaining 3.5 min.
  Extrapolating `+1167 MB/h` across a window containing one burst is exactly the
  error that produced the "~20 minutes to OOM" claim.
* This is the standing `memory.current is page cache` rule, which I had recorded
  and did not apply: **split anon from file before calling anything pressure.**

### `[web-oom-leak]` UPDATE 16 — **bursts are ORDINARY TRAFFIC, and the "both workers" observation that started the lane was a SAMPLING ARTIFACT**, 2026-09-05T22:2xZ `[session b2b5b45b]`

* **7 settled bursts at 10 s cadence, 0 restarts inside the window:**
  `0/7 hit both workers`; sizes `17.6-41.8 MB` (mean `28.0`); gaps
  `3.3, 0.2, 1.6, 4.0, 0.2, 3.4 min`, spread/mean `1.79` against a periodicity
  bar of `<=0.35`. **Not simultaneous, not periodic — demand-driven request
  traffic on one worker at a time.** The scheduled-job / fan-out hypothesis is
  FALSIFIED.
* **THE LANE'S FOUNDING OBSERVATION DOES NOT SURVIVE.** It was opened on "both
  workers rose ~98 MB in ~100 s — one request cannot do that", taken from
  **50-SECOND sampling** (pid 98 `+53.9`, pid 97 `+44.2` over 5.1 min). At 50 s
  resolution *"one worker then the other"* is INDISTINGUISHABLE from *"both at
  once"*. At 10 s resolution it resolves into single-worker bursts, 7 for 7.
  **A conclusion drawn at a resolution coarser than the phenomenon.**
* **A FIRST RUN WAS DISCARDED ENTIRELY.** A peer deployed web at
  `16:29:52-16:32:58` and the detector had no restart guard, so it reported
  warm-up as bursts — including `+570 MB` and `+284 MB`. Pids are REUSED across a
  restart (97 and 98 both times), so the pid set looked continuous. Rebuilt with
  restart inference (RSS drop or a run of failed fetches) and a 10-minute settle
  window; the rerun excluded 3 warm-up bursts explicitly rather than silently.
* Consistent with the rest of `#632`: ~28 MB increments match the 8-64MB
  anonymous mappings already identified, and none of it is reachable from Python.
* Weak signals, recorded as such: pid 98 took **6 of 7** bursts (lopsided for
  round-robin, but n=7), and ONE burst coincided with a 98 MB child process
  (`272:pro`, the only child all window) — an anecdote, not a mechanism.
