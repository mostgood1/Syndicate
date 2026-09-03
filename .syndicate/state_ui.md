# state — ui

Split out of `state.md` by `scripts/split_state.py`. Bodies are verbatim.
The INDEX of every subject, across every part, is in `state.md`; the
one-subject-one-section rule is global and spans these files.
Same rules as state.md: when a fact changes, EDIT THE LINE.

## [live-lens-snapshot] THE LIVE-LENS SNAPSHOT CANNOT BE DATED — it is a 4 MB KEYVALUE key, not a file, and archiving it would cost ~5.76 GB/day against a 256 MB store `[measured 2026-09-03, lane mlens-snapshot-dating]`

`data_root()/live/<sport>_live_lens.json` is ONE undated, MUTABLE object. It is
why `#625`(5) had to declare five blocks of the board artifact UNREPLAYABLE, and
the obvious fix — date it — **must not be built.** Measured at one instant:

- **IT IS NOT A FILE.** `_KEYVALUE_EXCLUDED_PATH_MARKERS` is only
  `migration_runs/`, so `live/` routes to the KEYVALUE store. That is also why
  `/api/ops/artifacts/export` reports **0 files under `live/*`** while the
  pattern IS allowlisted — the inventory globs a disk the object never touches.
- **SIZE: `live/mlb_live_lens.json` OCCUPIES ~4 MiB, ONE key — and that is an
  ALLOCATED size, not a payload size `[corrected 2026-09-03]`.**
  `/api/ops/keyvalue/usage` reports allocator-rounded memory: the two
  single-key buckets sit exactly **+96 bytes above a power of two**
  (4,194,400 = 4 MiB+96; `prediction_ledger.json` 2,097,248 = 2 MiB+96) while
  multi-key buckets have arbitrary gaps, which is jemalloc rounding large
  values to powers of two. **The true payload is in (2 MiB, 4 MiB].** The
  decision below is unchanged — even at the 2 MiB lower bound, 1,440 ticks/day
  is ~2.9 GB/day against a 256 MB store, ~11x capacity — but the figure first
  published was overstated by up to 2x.
- **STORE: 222.28 MB of 256 MB (86.8%), policy `volatile-lru`, 12,203 keys
  already evicted.** `reports/intelligence` alone is 189.51 MB of it.
- **COST OF DATING: 4 MB x 1,440 ticks/day = ~5.76 GB/day for MLB ALONE**, about
  22x the whole store's capacity, and five sports write on the same 60s tick.
- **AND IT WOULD BE UNRELIABLE AS WELL AS RUINOUS.** A path containing a date
  token automatically takes a TTL (`_default_keyvalue_ttl_seconds`), and under
  `volatile-lru` ONLY keys with a TTL are evicted — so dated snapshots would be
  the FIRST thing dropped. The archive would be partial with no way to know
  what was missing.

**WHAT WAS DONE INSTEAD:** the board artifact's `live_game_state` block now
carries a `lens_fingerprint` — a sha256 of the NORMALISED games plus counts and
the snapshot age, **98 bytes** on an artifact that IS dated, disk-backed and
mirrorable. It does NOT make the correction reproducible. It makes a divergence
**ATTRIBUTABLE**: two boards can be compared, and a replay can say "I had a
different lens input" instead of diverging for unstated reasons. The hash is
over the normalised games, not the raw payload, because the raw payload churns
on timestamps that change nothing.

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

- **THE GAMES RAIL AND THE BOARD CARD JOIN ON `sport_slug`, NEVER ON `sport` — and the LABEL comes from the chip's league `[verified in production 2026-08-27, web `78a95c7f` / `0e964af8` / `fb9261b8`, `#589`/`#590`/`#591`]`.** Two fields, and they are not interchangeable: `sport_slug` is the SLUG, `sport` is a DISPLAY string that for soccer's steam, prop and `#162` game-candidate paths is the **LEAGUE** (`"la liga"`). Every chip index in `loadGameChips` is keyed on `chip.sport` == the slug, so keying a lookup on `sport` returns null for a chip that is present — which is how one La Liga game seated two rail cards. `gameKey` had always read `sport_slug || sport`; `chipForGame` and `group.sport` read the same two fields with the OPPOSITE precedence, ten lines apart. **`chip.league_display` is the authoritative label: populated 213/213 on soccer chips across 10 leagues, and NULL on every mlb/nfl/wnba chip** (`game_chip_scoreboard.py:467` says so), so reading it cannot relabel another sport. Measured A/B, control = pre-change served bytes, one payload: 250→248 cards / 2→0 duplicate chips; head labels `SOCCER=213`→ten leagues; subtitles `SOCCER=489 LA LIGA=7`→ten leagues with 496 rows joining a league-carrying chip on both sides.
- **NO OTHER SPORT CAN HAVE THAT LABEL SPLIT `[code, 2026-08-27 — NOT a production reading for nba/nhl/ncaab]`.** The registry sets `name` to exactly `slug.upper()` for mlb/nba/wnba/nfl/ncaaf/ncaab/nhl (`intelligence.py:113-120`) and soccer's `"Soccer"` matches too, so `sport.get("name")` never diverges; the only override reads `league_display`, and every producer of that field imports `league_display_name` from `features/soccer/sources.py`. Measured 0 divergent rows for mlb/nfl/ncaaf/wnba on two payloads. **NBA, NHL and NCAAB had zero games and zero chips that day — covered by the code argument only.**
- **`data-syndicate-sport` IS AN IDENTIFIER ON THE MONEY PATH, NOT A CAPTION `[2026-08-27, `#591`; ledger half verified independently by lane `open-bet-live-status`]`.** `bet_slip.js:174` and `watchlist.js:129` read that attribute and `bet_slip.js:254,271` POST it as a bet's `sport` into `prediction_ledger`; **`settle_orders` and the venue resolvers KEY ON `sport`**, so a bet written as `"LA LIGA"` never joins a settlement source and **sits unresolvable forever rather than failing loudly**. It was being fed `item.sport`. Both sites now write the slug uppercased, matching `market_board.js:463,587`. **HAZARD, NOT CORRUPTION — measured twice, two sessions:** `/portfolio` holds `{mlb: 167, wnba: 17, nfl: 7, soccer: 2}` over 193 rows and no league string anywhere. Second time in one day that a UI-side display value turned out to be load-bearing on the execution ledger.
- **`bet_slip.js`'s POSTed units are CLEAN `[checked 2026-08-27]`:** `odds` is AMERICAN and `/api/portfolio/bets` stores it verbatim via `_coerce_float`; `stake` is dollars; `implied_probability` is a separate ledger field the slip never populates, so there is no odds→probability crossing. **Latent shape, not a live bug, in a file this lane did not own:** `prediction_ledger._coerce_probability` maps `1 < x <= 100` to `x/100`, so a value arriving in the wrong vocabulary INSIDE that band is silently rescaled (American `+50` → `0.50`) while `+150`/`-110` correctly become `None` — loud at the extremes, silent in the middle.
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
