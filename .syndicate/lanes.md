# Syndicate — Work Lanes

> Lanes are exclusive by file path. Two lanes may not claim the same file.
> Max concurrent OPEN lanes: 3 (see `state.md`).
> Managed by `/lane`. Do not hand-edit while a session is running.

## OPEN

#### snapshot-freshness — ~~DEPLOY REQUEST~~ **WITHDRAWN 20:25Z — DONE, NOTHING IS ASKED OF YOU.** `2efe76b1` is live on refresh-worker (20:25:16Z), verified by content. Cut on YOUR `415e23cb`, deployed into a lull after `daily_update --workflow ui-daily` finished — your work was not killed. Original request kept below for the record.

**Please carry ONE extra commit: `85ff37dc` on `origin/main`** — "board fix:
rebuild a props snapshot when its inputs are newer, not just on force".

- **WHY, measured on the served board at 14:3x CDT** (rec vs the board's OWN
  current market row): CHI@SEA spread `1.5` vs `2.5`; POR@PHX total `176.5` vs
  `178.5`; IND@ATL total `188.0` vs `187.5`. **A 2-point stale total is a
  fabricated edge**, not cosmetic lag.
- **CAUSE:** the three props-snapshot exporters gated on EXISTENCE, so the first
  build of a date won forever. `--force-refresh` bypasses it but the routine
  cycle never passes it. The `win_prob` counter dates it: `recommendations_slate`
  last built 00:53 CDT, `cards_props_snapshot` 00:11 CDT, every WNBA run since
  `rows=0` (no builder called) while market rows updated all day.
- **FIX:** gate on FRESHNESS — `_snapshot_inputs_are_newer` rebuilds when an
  input CSV is newer than the snapshot. Both producers, all three exporters.
- **ALREADY LIVE on live-odds-worker** (`46b5ec66`, 19:47:16Z), verified BY
  CONTENT. refresh-worker is the only service missing it.
- **HOW:** cherry-pick `85ff37dc` onto whichever live SHA you cut on — it applied
  cleanly onto `98a9cad8` and `0315f548`, so it should onto `415e23cb`. Tests:
  `tests/test_export_snapshot_force_refresh.py` → 34 passed. Verify after landing
  by CONTENT: `_snapshot_inputs_are_newer` present, 3 gated call sites.
- **RUNTIME EFFECT:** one extra small JSON build per cycle when inputs changed,
  nothing when they have not. Does NOT touch scheduling, sim, or memory paths.
  Deliberately bounded — the other ~30 `if existing:` short-circuits were left
  alone, because `live_refresh_loop`'s per-trigger `--force-refresh` would turn
  every trigger into a full artifact rebuild.
- **CONTEXT, NO BLAME:** my refresh-worker deploy at 19:41:37Z was superseded by
  `415e23cb` at 19:42:00Z. I am deliberately NOT re-firing so I do not cancel
  yours in return.
- **NOT A BLOCKER ON YOU.** refresh-worker builds `date+1`, so today's board is
  already fixed via live-odds-worker. If you would rather not carry it, ignore
  this and I will deploy it once your window is clear.
- **Cross-session messaging was UNAVAILABLE** — this lane's session is unattended
  (a scheduled-task run), and `send_message` refuses to send from those. The
  ledger is the channel; that is why this is here and not a DM.

### export-force-refresh-escape — OPEN — **DEPLOYED TO BOTH WORKERS 17:53Z (refresh-worker `b9f2b5f1`, live-odds-worker `e28594a7`), verified BY CONTENT; EFFECT UNMEASURED — needs a `:cards_props_snapshot` staged record from a forced run over an existing snapshot** — opened 2026-08-16 — session: win-prob-null-readable
- Goal: `--force-refresh` actually regenerates the three props SNAPSHOT exports
  instead of re-serving a stale per-date file. Testable: with `force_refresh=True`
  the builder is CALLED even when the snapshot exists; with `False` it is not.
- **Why: found while explaining a `rows=0` win_prob reading.** All three exporters
  short-circuit on a prior `<name>_<date>.json`, but only two take a
  `force_refresh` escape. `_export_cards_props_snapshot` (WNBA `:5082`) has NONE —
  and it is the builder that produced the `rows=32/null=3` reading, so its
  staleness is the least visible. NBA is worse: the whole trio lacks the escape
  AND `_materialize_artifact_bundle` has no `force_refresh` parameter to pass.
  The WNBA sibling comment already names this shape "the same reuse-forever bug".
- **DELIBERATELY NOT THE WHOLE CLASS.** ~30 `if existing:` short-circuits exist
  across the two producers (live snapshots, recon artifacts, game cards, season
  cards). `live_refresh_loop.py` passes `--force-refresh` on EVERY lineup/injury
  trigger, so adding escapes everywhere would turn each trigger into a full
  artifact rebuild on a 2GB worker — the same over-reach `#347`/the 2026-07-19
  `smart_sim_overwrite` fix already had to undo once. Scope is the props snapshot
  trio only; the rest is recorded, not touched.
- Files (exclusive to this lane; `_claims()` CLEAR and every OPEN lane's `Files:`
  block read — zero `oddsapi_props` mentions anywhere in `lanes.md`):
  - `scripts/refresh_wnba_oddsapi_props.py`
  - `scripts/refresh_nba_oddsapi_props.py`
  - `tests/test_export_snapshot_force_refresh.py` (new)
- Falsification test: if the builder still is not called under
  `force_refresh=True`, the gate is not the one at `:5082` — re-read the caller
  chain before changing anything else.
- Verification: new tests assert called/not-called in both files, plus targeted
  producer suites green. **NBA cannot be verified in production — out of season,
  its producer writes no artifact.** Default `False` keeps every path inert until
  someone actually forces a refresh.
- Blocked by: none. No deploy from this lane tonight unless asked.

### layer2-board-quality — OPEN — **ALL 8 GOALS SHIPPED. `#446` fixed and MEASURED (coverage 31% -> 96%). Its over-correction VERIFIED FIXED in production 23:01Z. Its over-correction (price compared across moved lines, one FALSE STEAM live ~15 min) found and re-gated; that gate is DEPLOYING, UNVERIFIED.** — opened 2026-08-16 — session: layer2-board-quality
> **`live_gameline_join.py` IS NOW CLAIMED — added 2026-08-16 ~00:1xZ by the
> `ask-answer-substance` session, which holds no claim on this lane.** Board
> finding 3, which I reported to you earlier, has its root cause in
> `syndicate/features/shared/live_gameline_join.py:643` — and **that file is now
> guarded**, so an edit there will be BLOCKED by `lane-guard.py`.
>
> **CORRECTION, same night, measured — I overstated this in the first version of
> this note.** I wrote that the file "was silently unprotected". It was not:
> against `2dd384b0` (before any of tonight's `lanes.md` work) it was **already
> claimed by `mlb-live-gameline-distributions`**. What my change actually did was
> add a SECOND claimant.
>
> `live-game-line-projection` had declared these files all along, but its
> `- Files:` block sat under a heading with no `OPEN` in it, so `_claims()`
> yielded nothing FOR THAT LANE. Merging its stray stub heading (that lane's only
> `OPEN` marker) onto the entry owning the block started enforcing four files:
> `live_gameline_ledger.py`, `live_gameline_join.py`, `blueprints/intelligence.py`,
> `tests/test_live_gameline_ledger.py`.
>
> **So the real state is a CROSS-LANE CONFLICT, not a gap I closed:**
> `live_gameline_join.py` is now claimed by **`live-game-line-projection` AND
> `mlb-live-gameline-distributions`** — two OPEN lanes on one file, which is the
> thing the lane protocol exists to prevent. Both are `OPEN` and neither has a
> live session. Whoever picks this up should reconcile the two before editing,
> not just satisfy the guard.
>
> **So: coordinate with `live-game-line-projection` before touching it.** That
> lane reads `OPEN, UNOWNED` (its session checkpointed 15:2xZ), so it may be
> takeable rather than blocked.
>
> **Restating the finding so it does not die with my session.**
> `live_gameline_join.py:643` overwrites `projection["edge_vs_market_pct"]` with
> the LIVE edge while deliberately leaving `model_prob_over` at its PREGAME value
> (the live probability goes to a NEW `live_model_prob_over` key). The edge then
> refers to a different probability than the one printed beside it, with nothing
> in the field name to say so. **7/7 separation on `live_aware`**; arithmetic
> exact — stated `-39.93` = `(live_model_prob_over 0.1917 − market_fair_prob_over
> 0.591) × 100`, where the pregame pairing gives `+27.46`. Every number is
> correct; only the PAIRING is wrong, which is why it is `full/*` only (segment
> bases are not live-joined and agree 3/3). Suggested fix: rename to
> `live_edge_vs_market_pct` so the pairing cannot be got wrong at the call site.
>
> **Also withdrawn, so you do not chase it:** my earlier "board publishes sides
> that contradict its own projection" report was MY error — a mean-vs-`P(X>line)`
> category mistake in the Ask reason generator, fixed on my side. Only finding 3
> stands. Full record in `deploys.md` under `ask-sim-margin` and `ask-both-edges`.

- **`#446` SHIPPED AND MEASURED.** worker `bdb3dc58` live 22:09:54Z; artifact
  22:20:31Z: **coverage 31% -> 96%**, tracked rows 4 -> 23, first-ever steam
  flag. The diagnosis and the fix were both right.
- **THEN THE OVER-CORRECTION, found by not believing two numbers.** 19 of 23
  tracked rows compared prices at DIFFERENT lines (`Under totals 7.0` vs an
  opening of 11.0 -> "+242"), and **the one steam flag was FALSE** (`Rockies
  spreads -1.5` vs opening `+1.0`). A loose key makes a row VISIBLE; it does not
  make its price COMPARABLE. `_opening_key`'s docstring had said so and I read
  it as being about settlement.
  - The 1636-pt delta in that same reading was **NOT** a bug: a pregame +109
    underdog live at ~-1527. Checked before assuming.
- **RE-GATED `3662d552`** — price delta only when the line is unchanged; nothing
  emitted otherwise, because score and steam both read that field. Deployed
  worker `2ef1165a` + web `acdaaf7e` (endpoint counters, 4th instance of that
  gap).
- **UNVERIFIED AT CHECKPOINT: the gate itself.** Both deploys were
  `update_in_progress`. Verification harness armed (`brey4hlgd`) and **proven to
  discriminate** — against the pre-fix board it fires on both signatures (17
  leaked deltas, 1 false steam). PASS requires both at 0 and coverage READ from
  the counters rather than derived.
- **NEXT ACTION:** read that harness's verdict. If it says FAIL, roll worker back
  to `bdb3dc58` (coverage win without the gate) rather than to `a9e5d3d6`.

- **`#446` — MOVEMENT WAS KEYED ON THE THING IT MEASURES.** Found by chasing a
  number that went the WRONG WAY against my own prediction (opening coverage
  31% -> 29% when I said it would rise). `_opening_key` includes `line` and
  `bookmaker`, so a row matched its opening only if it had NOT moved.
  Measured over two artifacts 20 min apart: stable key matched 20, full key 14,
  line changed on 6 and book on 5.
  - **It also explains steam.** A sharp move usually comes WITH a line move or
    book switch, so the biggest moves were the most reliably erased. **Steam was
    structurally suppressed, not merely unverified** — the earlier "0 flagged,
    untested" entry understated it.
  - Fixed `08de8c08`: `movement_join_key` (stable). `_opening_key` UNCHANGED —
    right for settlement, wrong for this question. Regression test pins the
    production case (-1.5 -> -2.5, draftkings -> fanduel: invisible before, now
    **-27 pts same-book**, crosses the 15-pt threshold).
  - Counter gap closed (3rd instance in this file): `openings_records`,
    `openings_loaded`, `movement_eligible_rows`, `movement_rows_matched`.
- **NOT LIVE.** Live worker `a9e5d3d6` has `movement_join_key` 0 and
  `_blended_score_accepts` 0. **Production movement still reports only rows that
  did not move.** Handed to `sim-engine-track`; recorded in `deploys.md` under
  the superseding PENDING RIDEALONG entry.
- **Whether coverage rises after the fix is PREDICTED, NOT MEASURED** — and the
  last prediction I made about this number was wrong. A content-gated watcher
  (fires only on a SHA carrying `movement_join_key`, falsified against 3 real
  SHAs) will measure it.

- **G4 / G7 / INTERVALS MEASURED 2026-08-16 21:02Z** on `a9e5d3d6` (live
  20:50:14Z), artifact 21:01:19Z, 63 rows / 61 cards. Safety first:
  `cards_present 63`, no `cards_error`, no `cards_compat_note`.

      intervals   17 labelled: 1st 5 innings 14 · 1st 3 innings 2 · 4th quarter 1
      live column 18 of 37 live cards carry live_projection   (was 0)
                  source mlb_live_lens_monte_carlo on 12 -- the LIVE MC sim
      counters    mlb no_bettable_book=114  repriced_to_bettable=1789
      regression  unbettable best-book 0 -- held
      movement    tracked 4 · flat 1 · no_opening_for_row 11 · not_tracked 45
      steam       0 flagged

- **STEAM IS UNVERIFIED, NOT VERIFIED-ZERO.** 4 rows carried a delta against a
  ±15-point / 3-hour threshold, so it had no opportunity to fire. Recording 0 as
  a pass would be the "absence in a window isn't absence" error. **It stays
  untested until a row crosses the threshold.**
- **Movement coverage is 31% of tracked-eligible rows** (5 of 16 had an
  opening). `record_openings` writes on first publish and the board churned
  through several builds today, so a first-appearance row has no opening by
  definition. Expected to improve over a day — a PREDICTION, not a measurement.
- **Live coverage is 49% (18/37)** and the other 19 render a dash rather than a
  pregame number dressed as live, which is the intended degrade.
- **OWED — third instance of the same gap:** `openings_loaded` is unpublished,
  so thin movement cannot be attributed between a sparse ledger and a failing
  key join. Fix: publish `openings_loaded` + `movement_rows_matched` beside the
  existing counters, in `pipeline/layer2_shortlist.py`.
- **BLANK-BOARD INCIDENT 20:34Z, caused by this lane's design.** `c324447d`
  shipped the caller without the callees; caught before any build landed; closed
  by roll-forward `77dbbd06`. Guarded in code as `a21b63db` (signature probes +
  optional import + 6 tests). The three files are no longer coupled — any
  combination is now safe.

- **DEPLOYED 2026-08-16 AND MEASURED.** refresh-worker `7b544eb4` (live
  18:20:40Z), web `ad77e46a` (live 18:27:30Z). Both cut on their service's LIVE
  SHA, never on `main` (`/preflight` failed `main` on scope: 520 commits).
  Post-deploy artifact `written_at` 18:31:26Z:

      best book outside DEFAULT_BOOKS   27 of 108 -> 0        PASS
      h2h_lay rows served                9        -> 0        PASS
      prop cards attributed to a team   56 of 108 -> 0        PASS
      cards carrying sim_view            0        -> 108/108  PASS
      rail cards (live chips + rows)   108        -> 18       PASS
      no_bettable_book / repriced       absent    -> absent    FAIL

- **BLOCKER FOUND IN THE COMBINED DEPLOY, 2026-08-16 ~20:1xZ — THE THREE WORKER
  FILES MUST TRAVEL TOGETHER OR THE BOARD GOES BLANK.**
  `sim-engine-track` queued a branch carrying `pipeline/layer2_shortlist.py`
  alone. Measured against live refresh-worker `415e23cb`:

      main  layer2_shortlist.py:391  layer2_rows_to_board_cards(rows, openings=openings_index)
      live  layer2_board.py          def layer2_rows_to_board_cards(rows)   ("openings": 0 occurrences)

  **It does not crash, which is worse.** The call is inside `try/except
  Exception` that sets `shortlist["cards"] = []`; with `layer2_is_primary=True`
  and `legacy_candidate_count=0` that is a **BLANK BOARD** carrying a
  `cards_error` string nobody watches. Second instance one level down: main's
  `layer2_board.py:1070` calls `blended_score(movement_price_delta=...)` and
  live `opportunity_signals.py` has 0 occurrences of that parameter.
  - **MINIMUM COHERENT SET:** `pipeline/layer2_shortlist.py` +
    `syndicate/features/shared/layer2_board.py` +
    `syndicate/features/shared/opportunity_signals.py`. `book_shortlist.py` and
    both `attach_live_*_for_sport` are ALREADY on `415e23cb` — verified, not
    assumed.
  - **Post-deploy check, because the failure is SILENT:** `cards_present > 0`
    AND no `cards_error` on `/api/board/layer2-shortlist`. Either fails -> the
    files did not travel together -> roll back.
- **WEB IS DONE AND NEEDS NO FURTHER DEPLOY.** Verified BY CONTENT on live web
  `a01b30eb` (20:04:16Z): `claimedChips` 3, `chipCentralDate` 2,
  `board-disclosure` 2, `const isFinal` 1, `sim-disagrees` 1, `segment_label` 1;
  `bet_slip.js` / `board_cards.css` / `board_rail_toggle.js` /
  `blueprints/intelligence.py` all empty-diff against `main`. `boardSports` is
  absent ON PURPOSE (removed when soccer was restored to the rail) — do not read
  its absence as a regression.
- **The Layer 1 lane independently found the same live-tier gap** (`model_edge_pct:
  None` on 7 live spreads + 10 live totals) and routed it here rather than
  editing across the lane. Same item as `1d03855e`; both confirmed to them.
- **DEPLOY HANDED TO `sim-engine-track` 2026-08-16 ~19:5xZ, BY USER DECISION.**
  My worker payload is NOT mine to fire; it rides their next refresh-worker
  deploy. Everything below is on `origin/main` and on NO service:
  - `1d03855e` — `#372` movement/steam re-enabled from the CLV opening ledger,
    live projection joins wired into the shortlist build, movement folded into
    the score (capped). `layer2_board.py`, `opportunity_signals.py`,
    `pipeline/layer2_shortlist.py`.
  - `7576b1d5` — publishes `no_bettable_book` / `repriced_to_bettable`.
  - Tests: 15 new pytest + 10 node rail assertions. Suite 315 -> 330 passes,
    **21 failed before and after** (all pre-existing).
  - **Two items flagged to them explicitly rather than smuggled in:**
    `blended_score` gained a `movement_price_delta` parameter (defaults None, so
    every existing caller is unaffected), and the shortlist build now runs two
    extra enrichment steps that read the published live-lens snapshot — MLB-only
    real work, the rest return `supported: False`. Offered to gate the second
    behind a flag if their scheduling work objects.
- **NO UNDEPLOYED LAYER 1 BOARD CHANGES EXIST — checked, not assumed.**
  `layer1_board.py`, `layer1_board.html` and `layer1_page.py` all diff EMPTY
  against `main` on BOTH live SHAs (worker `98a9cad8`, web `1468780b`). The
  Layer 1 lane's soccer live-state and finished-match-edge fixes shipped at
  18:37:38Z and 18:54:37Z and are live.
- **OWED -> FIXED IN CODE, NOT DEPLOYED (`7576b1d5`).**
  `no_bettable_book` / `repriced_to_bettable` now reach `per_sport_ingest`.
  The gap was that `#397`'s "add the counter in the same commit as the rule" is
  NOT SUFFICIENT — the counter has to be added everywhere the payload is
  ASSEMBLED, which on this path is three places. Producer-side, so it **rides
  along with the next worker deploy**; web needs nothing. Falsification once it
  ships: `per_sport_ingest.mlb.no_bettable_book` is present and an integer.
- **Found and PARTLY fixed on the way, handed on:** `test_layer2_shortlist_wiring`
  patched `read_book_quotes` while the code calls `read_book_quotes_latest`, so
  its fixtures were INERT and the tests read the real disk (same defect as
  `test_layer2_sweep_state`'s, fixed earlier today). Renamed; **1 of 7 goes
  green.** The other **6 are red for a deeper reason, traced not guessed**: the
  fixtures' quote-row shape no longer satisfies `build_book_grid` —
  reproduced directly as `quote_rows: 1` in, `grid_rows: 0` out. Not this
  lane's, not a one-line fix, and it makes those tests environment-dependent
  until someone owns it.
- **STILL NOT DONE — G4 (movement/steam) and G7 (live-lens projection).**
  G4 is blocked on the odds sampling interval (`odds-cadence-off-the-mlb-peak`,
  effect unmeasured) and on `#372`'s stall cause. G7 overlaps
  `live-game-line-projection`; the shortlist joins only PREGAME projection
  sources while the grid carries `live_projections` (19) unread.
- **NO UI ELEMENT HAS BEEN SEEN RENDERING.** Web is verified as SERVED BYTES
  (`boardSports` 2, `chipCentralDate` 2, `board-disclosure` 2 on the live page)
  and as LOGIC (`node tests/js/game_rail_derive.test.mjs`, 9 assertions, and it
  discriminates). The betslip 36px strip, the count-0 rail card, the disclosure
  and the sim badge have never been looked at in a browser with data.
- **The count-0 rail card is unexercised in production** — all 18 games today
  carry an opportunity, so only the synthetic harness covers that branch.
- `ad77e46a` also carries another session's Ask work (`a92f76e9`), which my
  earlier web deploy CANCELLED. Union verified disjoint; that session notified
  and asked to verify their half by content.

- **CHECKPOINT 2026-08-16 ~18:0xZ. STATUS BY GOAL:**

  | goal | finding (measured, 108 served rows) | state |
  |---|---|---|
  | G1 rail | rail derived from ROWS, so a game with no opp cannot appear; finals sorted to the FRONT | **FIXED, committed `625b6284`, NOT deployed** |
  | G2 score | `_SCORE_SIM_WEIGHT` is **0.0** not 0.5; sim in 0 of 65 eligible rows | **audited; disclosure shipped to main, weight unchanged (gated on S6)** |
  | G3 books | no allowlist; **27/108 (25.0%)** best-book unbettable | **FIXED, committed `217c2bd5`, NOT deployed** |
  | G4 movement | `return {}`; 0 movement keys on 108 rows | **NOT DONE — blocked, see below** |
  | G5 anti-sim | 32/108 negative `model_edge_pct`, 43 no model | **LABELLED (`sim_view`), committed, NOT deployed** |
  | G6 labels | `h2h_lay` rendered as a back bet (9 rows); **56/108** props attributed to the AWAY team | **FIXED, committed `217c2bd5`, NOT deployed** |
  | G7 live | 6 live rows, **0** live projection sources; grid holds `live_projections` (19) unjoined | **NOT DONE — see below** |
  | G8 betslip | collapses to the bottom of the page on desktop (layout drops to `1fr`) | **FIXED, committed `625b6284`, NOT deployed** |

- **THE ONE THING THAT IS ACTUALLY LIVE:** the `min()` score guard, absent from
  all three services because `deploy/nfl-pbp-root` was cut 1h38m before it
  landed. Deployed as `ed54071a`, superseded by another session's `a775e372`,
  and **verified on a post-deploy artifact** (17:13:13Z): `reliability_applied`
  108/108, `min()` applied 4/4, scores moved. Working in `deploys.md`.
- **NOTHING ELSE FROM THIS LANE IS DEPLOYED.** Six fixes sit on `main` only.
  They need a deploy decision and a `/preflight`; deploying `main` outright
  FAILED preflight on scope (520 commits / 207 files / 85,232 insertions from
  seven sessions, including work the ledger HOLDS).
- **G4 is BLOCKED, not skipped.** Re-enabling `_layer2_movement_columns` naively
  re-stalls the shortlist build (`#372`: a ~20MB shard loaded inside the
  builder, 70 minutes of no `LAYER2_SHORTLIST` and no exception). The docstring
  states where it belongs — where the odds tracker already holds the data. It
  also shares G2's prerequisite: the real odds sampling interval, owned by
  `odds-cadence-off-the-mlb-peak` (1a/1b verified, **effect unmeasured**).
- **G7 is NOT DONE and overlaps another lane.** The shortlist's
  `attach_projections` joins only PREGAME sources; `live_projections` (19) and
  `live_gamelines` (8) exist on the grid payload and are never read. Today's
  slate hides it — all 6 live games were at `TOP 1`, where a full-game pregame
  projection is still nearly right. Coordinate with `live-game-line-projection`
  (reports both halves shipped, v2 unexercised) before building anything.
- **UI CHANGES ARE UNRENDERED.** `deriveGameCards` is verified as LOGIC
  (`node tests/js/game_rail_derive.test.mjs`, and the test discriminates — the
  pre-change function fails 4 of 5). The disclosure was seen in served local
  HTML. **The betslip collapse, the sim badge and the count-0 rail cards have
  never been seen rendering**: the local combined-board path takes minutes to
  hydrate 8 sports and no page load completed.
- **Cross-lane:** `send_message` sent to `Layer 1 board coverage audit` asking
  who should own the shared book list (it means editing `layer1_board.html`,
  theirs). **No reply at checkpoint.** `book_shortlist.py` is the proposed
  owner and is live in the tree; Layer 1 does not read it yet.
- **NEXT ACTION for whoever picks this up:** decide the deploy for the six
  committed fixes (narrow branch off the live SHA, as `ed54071a` did — NOT
  `main`), then verify the four UI ones in a browser, which needs a page load
  the local box has not managed.
- Goal: the curated board scores, labels and moves correctly, and never contradicts the sim. **Testable outcome:** on the served `/api/board/layer2-shortlist` payload, (a) `sim_component` is non-zero wherever `model_edge_pct` is non-zero, (b) every `quote.bookmaker` is in the shared book shortlist, (c) no row carries a negative `model_edge_pct` without an explicit label, (d) negative-value rows are not promoted by low reliability.
- Files:
  - `syndicate/features/shared/layer2_board.py`
  - `syndicate/features/shared/opportunity_signals.py`
  - `pipeline/layer2_shortlist.py`
  - `syndicate/templates/intelligence.html`
  - `syndicate/static/shared/bet_slip.js`
  - `syndicate/static/shared/board_cards.css`
  - `syndicate/static/shared/board_rail_toggle.js`
  - `syndicate/features/shared/book_shortlist.py`
  - `syndicate/blueprints/intelligence.py`
- **CLAIM ON `layer2_board.py` TAKEN FROM `spread-line-sign-convention` 2026-08-16, RESOLVED BY CONTENT RATHER THAN BY NEGOTIATION** (the `clamp-fix-to-workers` precedent):
  - That lane's outstanding item was "artifact output still unverified". **It is now verified: `_side_line_from_cells` is PRESENT in the deployed tree** — `git show 97491161:syndicate/features/shared/layer2_board.py` returns 3 occurrences, identical to `main`. The fix is live on refresh-worker.
  - **Ancestry was the WRONG test and gave the WRONG answer.** `edbbee9d` is NOT an ancestor of live `97491161` (`git merge-base --is-ancestor` → NO), because refresh-worker runs branch `deploy/nfl-pbp-root`, not `main`. Testing by content reverses that conclusion.
  - The holding session (`Orphaned lanes cleanup` = `lane-cleanup`) is ARCHIVED and not running — `list_sessions include_archived:true`, last activity 2026-08-16T01:14:03Z.
- **THE CLAIM WAS NEVER ENFORCED ANYWAY, AND THE HOLDING LANE MIS-READ ITS OWN CHECK.** `lane-guard.py`'s `_claims()` cannot see `spread-line-sign-convention`'s Files block: `FILES_RE` matches its header line (on the colon inside `23:0xZ`), yielding no paths, and the two continuation lines carrying the actual paths start with a backtick, not `-`, so they are never parsed. Measured: a `_claims()` run over `lanes.md` returns **zero** claims on `layer2_board.py`. That lane recorded "Collision check RUN … CLEAR both times, so no other lane was blocked by the gap" — the guard read CLEAR because **its own claim was unparseable**, not because the file was free. My Files block above puts each path on its own `-` bullet so it actually parses.
- Hypothesis: n/a for the audit half (measurement, not diagnosis). Per-goal hypotheses are recorded against G1–G8 below as they are tested.
- Falsification test: per goal. The standing one for the whole lane — if the served payload already satisfies (a)–(d) above, the brief's premise is wrong and the lane closes without a code change.
- Verification: the SERVED payload from `/api/board/layer2-shortlist`, written to `deploys.md`. Not a unit test — the user has twice reported a board defect that automated checks missed.
- Blocked by: none. Read-only on `layer1_board.py`, `templates/shared/layer1_board.html`, `blueprints/layer1_page.py` (Layer 1 session), sim-engine internals, and `pipeline/intelligence_state.py`.
- **CORRECTION 22:4xZ — the line gate is UNVERIFIED, not passing.** The harness
  said PASS on **0 moved-line rows** (board down to 12 cards on end-of-night
  attrition), so the leak and false-steam checks tested nothing. Shrink
  confirmed as SLATE (`rows_beyond_quote_age` 1014, `rows_beyond_game_cap` 689),
  not the gate. Harness rebuilt with a minimum-denominator guard and falsified
  across INCONCLUSIVE / PASS / FAIL. **Re-verify on a slate with live line
  movement — realistically tomorrow.**
- **LINE GATE VERIFIED IN PRODUCTION 2026-08-16 23:01:01Z** — supersedes both the
  retracted empty-set PASS and the "UNVERIFIED" line above. **9 moved-line rows,
  0 leaked a price delta** (pre-fix: 19 of 23 leaked). Coverage 100% (15/15).
  Independently re-counted rather than taken from my own harness, which had
  produced a false PASS two hours earlier.
  - **It does not over-suppress**: the 2 same-line rows still carry deltas
    (+23.0, -1120.0, both `same_book`). A gate that silenced everything would
    look identical on the leak check alone.
- **STEAM REMAINS UNVERIFIED and the gate PASS does not cover it.** Only 2 rows
  were eligible (steam needs a price delta, so same-line only) and both openings
  were outside the 3h window. `steam 0` is correct behaviour, not evidence.
  Needs a same-line row moving >=15 pts within 3h of its opening.
  Scheduled re-run 2026-08-17 09:00 CDT.
### clv-without-settlement — OPEN — **GOAL RE-SCOPED 2026-08-15 23:5xZ: `clv_pct` PER RECOMMENDATION ALREADY EXISTS; THE GAP IS EXPOSURE, AND THE PREDICTION LEDGER IS THE WRONG SUBSTRATE** — opened 2026-08-14 — session: lane-cleanup
- **SETTLED CLV READING 2026-08-15 22:06 CDT / 2026-08-16 03:06Z (scheduled read,
  taken after the last two first pitches at 01:38Z and 01:40Z).**
  - **mlb headline: `avg_clv_pct = −0.3165` over `same_book_n = 126`,
    `beat_close_rate = 0.2143` (27/126).** `openings 999`, `resolved 254`,
    `same_book_all_n 151`, `in_play_excluded_n 25`,
    `unknown_timing_excluded_n 0`, `stamped_close_skipped
    {stamped_close_is_home_side: 59}`, `by_close_source {last_pregame_quote 187,
    observed_transition 67}`, `unresolved_reasons {no_market_in_history 368,
    no_pregame_observation 246, close_precedes_open 113, line_mismatch 18}`.
  - `by_close_timing`: pregame n=126 −0.3165 · in_play n=25 −0.3498.
  - `by_book_scope`: same_book n=151 −0.322 · book_agnostic_close n=92 **+2.8054**
    · different_book_close n=10 **+0.7011**. **The two positives are the known
    upward bias (best-of-N opening vs one book's close). NOT CLV. Never quote.**
  - **INSTRUMENT CHECK PASSED.** Recomputed the headline from `&rows=1`: mean
    `clv_pct` over rows with `close_book_scope == same_book` AND `close_timing ==
    pregame` = **−0.316519 → −0.3165 over n=126**, exact match on both the value
    and the n. `beat_close` recomputed 27/126 = 0.2143, also exact. The report is
    reporting what it says it reports.
  - **`same_book_n` DID NOT RISE — and the prediction was not testable as
    written.** It reads 126 against the last preliminary reading's 151. But the
    prior readings (−0.0711 n=144, −0.668 n=167, −0.3077 n=131, −0.2714 n=151)
    are mid-slate headline `n` only; I do not hold their payloads, and `n` moves
    with how many games have started, how many stamps landed, and the 59
    `stamped_close_is_home_side` skips. **A raw `n` comparison across hours is
    confounded and I am not treating 126 < 151 as a regression OR as a
    refutation.** The mechanism the prediction was about IS confirmed, on the
    within-payload counterfactual: **30 rows that the old code would have
    excluded as `in_play` are in the headline** (n=96 → n=126, −0.3998 →
    −0.3165). See `closing-stamp-is-detection-time` for the attribution.
  - **nfl and wnba UNCHANGED: `resolved = 0`.** `openings` 419 / 111,
    `unresolved_reasons` **100% `no_market_in_history`** for both (419/419,
    111/111). **This is NOT the blind-reader pattern** — the openings ledger is
    readable (`/api/ops/artifacts/export?pattern=reports/intelligence/clv_openings/*.jsonl&names_only=1`
    → `2026-08-15.jsonl` 1,126,475 B, mtime 02:20:33Z). Openings are recorded and
    visible; the join fails because odds-history holds no matching market for
    them. That is a separate, unowned gap.
  - **CONTAMINATION, stated not glossed:** both fixes are FORWARD-ONLY and shipped
    ~23:17Z, so this date is permanently mixed. **36 of 57 stamped markets carry
    the pre-fix clock** (33 of them post-dating first pitch), and 96 of the 126
    headline rows are pre-fix. **−0.3165 is a mixed-cohort number.** The first
    clean reading is 2026-08-16.
- **MEASURED BEFORE BUILDING, and it stopped the build:**
  - `/api/portfolio/summary`: **3 prediction records**, all sport `multi`,
    `settled: 0`, `avg_clv: null`. That is the whole ledger.
  - Same instant, published recommendations: **11,864 opportunities considered**,
    ~600 openings recorded for the date.
  - So `PredictionResult.clv_pct` — the field that exists and is never populated
    — sits on a table with **3 rows**. Filling it would make
    `/api/portfolio/summary.avg_clv` a real number computed over 3
    records: **a metric with no denominator, which is worse than null** because
    null is honestly empty and a number invites use.
- **`clv_pct` PER RECOMMENDATION IS ALREADY PRODUCED.** `compute_clv_for_date`
  emits one row per published opening, each carrying `clv_pct`, `beat_close`,
  `close_source`, `close_timing`, `model_edge_pct` and `ev_pct`, keyed by
  `event_id|market|player|segment|side|line|bookmaker`. **An opening IS a
  published recommendation** — that key is the recommendation's identity.
  Reachable now: `/api/ops/clv/report?date=...&sport=...&rows=1` (179 same-book
  rows today).
- **THE REAL GAP, stated precisely:** the per-recommendation CLV exists only on
  an ops diagnostic endpoint. Nothing a user or the board reads carries it. The
  work is EXPOSURE, not computation — and that is a different, smaller job than
  the lane's original wording implies.
- **THREE SUBSTRATES, materially different work — needs a decision, not a
  default:**
  1. **Attach at artifact build** (`layer2_shortlist`) — every published row
     carries its own `clv_pct`. Truest home; costs a WORKER deploy and only
     applies to rows built after it ships.
  2. **Join at serve time** on web — `/api/board/layer2-shortlist` merges the
     joiner's rows by key. Web-only deploy, works on today's data immediately,
     but recomputes per request (the joiner is a pure read, so it is legal).
  3. **Backfill the prediction ledger** — REJECTED on the evidence above until
     something actually writes recommendations into it at volume.
- **NOT STARTED. No files claimed for this.** Recorded so the next session does
  not rebuild what exists or build onto the 3-row table.

 — OPEN — **PUBLISH FIXED AND MEASURED (web `bebe87c9`, live 19:36:45Z): `same_book_n` 0 → 144, FIRST UNBIASED CLV = -0.07% AT A 27.1% BEAT RATE (PRELIMINARY, TAKEN PRE-FIRST-PITCH). THE LANE'S BREADTH HYPOTHESIS IS REFUTED** — opened 2026-08-14 — session: lane-cleanup
- **RESULT 2026-08-15 19:38Z — the publish fix landed and it changed the answer.**
  `PUBLISH_FAILED`×8/16h (`HTTP 403 FORBIDDEN`, last 19:32:50Z) → `PUBLISH_OK`×2
  at 19:37:00Z and 19:38:10Z, 15s after the deploy; zero failures since. Web now
  holds the artifact. MLB: `openings 0→520`, `resolved 0→293`,
  `same_book_n 0→144`. Also landed on main as `baec34a8` — it had existed ONLY
  on deploy branches (web and main both carried blob `aff59302`).
- **THE PRE-REGISTERED RULE IS REFUTED. Do not re-derive it.** "If `same_book_n`
  is still 0, the blocker is odds-history breadth" — `same_book_n` moved 0→144
  with **no change to odds history**; only the reader moved. Breadth is real but
  it constrains `resolved`, not `same_book_n`:
  `no_market_in_history: 172`, `close_precedes_open: 42`, `line_mismatch: 13`.
- **FIRST UNBIASED NUMBER, and the selection effect is now measured:**

      scope                    n     avg_clv   beat_close
      same_book (UNBIASED)   144     -0.0711      27.1%
      book_agnostic_close    143     +2.7261      82.5%
      different_book_close     6     +1.3907      66.7%

  The biased scopes say the board crushes the close; the honest one says it is
  flat-to-negative and beats the close **27%** of the time. Supersedes the
  retracted `-5.215`.
- **THE LANE'S GOAL WAS ALREADY MET — `clv_pct` PER RECOMMENDATION EXISTS AND
  SHIPS. Do not build it.** Checked 2026-08-15 21:1xZ before writing any code:
  `/api/ops/clv/report?date=...&sport=mlb&rows=1` returns **355 rows, 355 of
  them carrying `clv_pct`**, plus `beat_close`, `close_book_scope`,
  `model_edge_pct` (291/355) and `ev_pct` — no grading, no outcome, no
  `settle_result`, exactly as the goal specifies. `clv_join.py` has done this
  since it was written; it was invisible only because of the 403 publish bug
  fixed earlier today. **The build was already done and the lane did not know.**
  - **The prediction ledger is NOT the recommendation stream and must not be
    used as one** — `/api/portfolio/summary` reports **3 predictions, 0
    settled, `avg_clv: null`** for a single pseudo-sport `multi`, against 636
    MLB openings recorded today. `record_result()` is also the wrong door: it
    computes `clv_pct` only via the settlement path this lane is defined to
    avoid.
- **WHAT WAS ACTUALLY MISSING IS THE SEGMENTATION THE AUDIT WANTED IT FOR.
  Computed below on the 172 unbiased same-book rows — biased scopes excluded.**
- **§4, THE THRESHOLD QUESTION: model edge DOES buy CLV, and the honest
  threshold is far higher than 2%.**

      model_edge bucket    n     avg_clv    beat_close
      edge < 0            69     -0.419        26.1%
      0-2%                25     -1.772        24.0%
      2-5%                17     -1.245        29.4%
      5-10%               25     -0.112        32.0%
      10%+                12     +1.396        41.7%

  Monotone in BOTH columns from `0-2%` up, and **only the 10%+ bucket is
  positive**. On this evidence a 2% threshold publishes rows that lose CLV.
  **Unexplained and left unexplained:** `edge < 0` (-0.419) beats `0-2%`
  (-1.772). Do not build a story on it; n is small.
- **THE HEADLINE LOSS IS ONE BOOK-MARKET CELL, NOT A BROAD PROBLEM.** Two
  findings looked separate ("h2h is bad", "fanduel is bad"); cross-tabbing
  showed they are one:

      cell                        n      avg_clv    beat
      ALL same_book             172      -0.672     27.9%
      FanDuel h2h ONLY           54      -2.648     20.4%
      EVERYTHING ELSE           118      +0.232     31.4%

  FanDuel h2h is **31.4% of rows and 124% of the total loss** — remove it and
  the board's CLV is **positive**. It is not h2h generally (DraftKings h2h
  `+0.488`, n=24) and not FanDuel generally (FanDuel totals `+0.122`, spreads
  `+0.132`).
- **ANSWERED 2026-08-15 21:5xZ — AND MY OWN "FanDuel h2h" HEADLINE IS RETRACTED.
  IT IS NOT A FANDUEL PROBLEM AND NOT AN h2h PROBLEM.**
  - **The cause: rows whose "close" was sampled AFTER FIRST PITCH.**
    `close_age_seconds = (commence - stamp)` (`clv_join.py:216,254`), so a
    NEGATIVE value means the close observation is POST-COMMENCE — an in-play
    price, not a close. **37 of 172 same-book rows (21.5%) are post-commence,
    and they carry 60% of the entire loss.**
  - **The worst four rows are one event.** `dbbb481a…` h2h away: open `-186`,
    "close" `+168`, stamped 20:34:26Z against a 19:08Z first pitch — 86 minutes
    into the game. That is a team going behind early, priced live. It is not
    CLV. Four published openings (kalshi, polymarket, betopenly, betfair_ex_eu)
    all matched that same FanDuel pair, so one bad close entered the mean four
    times at ~-27 points each.
  - **CLEANED, THE FANDUEL CELL IS UNREMARKABLE AND DRAFTKINGS IS WORSE:**

        cell                              n     avg_clv    beat
        ALL same_book (as I reported)   172     -0.672    27.9%
        EXCLUDING post-commence closes  135     -0.346    25.2%
          FanDuel h2h, cleaned           47     -0.616    23.4%
          DraftKings h2h, cleaned        21     -1.378    14.3%

    **"Strip FanDuel h2h and CLV is positive" does not survive cleaning. Do not
    act on it.** The board's honest same-book CLV on this date is about
    **-0.35**, not -0.67, and it is not concentrated in one book-market cell.
  - **How I got it wrong, recorded because the shape repeats:** I read a
    negative `close_age_seconds` as "close precedes open" WITHOUT reading the
    field's definition, then built an attribution on it. The guard for
    close-precedes-open (`:430`) was never the issue — it correctly did not
    fire, because `close > open` on all 37 rows. **Two different defects can
    both produce a negative number in a field you did not define.**
  - **H4 (favourite asymmetry) and H2 (stale openings) are REFUTED by data:**
    FanDuel vs DraftKings h2h open-price medians 102 vs 115.5, favourite share
    41% vs 29%, `close_age` medians 8025s vs 8265s — comparable on every axis.
    **H3 stays refuted at the code level.** What remains of H1 is small and is
    NOT FanDuel-specific.
  - **`n=172` IS NOT 172 INDEPENDENT OBSERVATIONS.** The same book's open/close
    pair is reused for every published opening on that event/market/side, so one
    pair can enter the mean many times. Any confidence interval over these rows
    is overstated until that fan-out is collapsed.
- Files (claimed 2026-08-15 22:0xZ, collision check CLEAR via `lane-guard.py`'s
  own `_claims()`): `syndicate/features/shared/clv_join.py`,
  `tests/test_clv_close_timing.py` (new).
- **DEFECT FIXED AND VERIFIED — web `4316c907` live 21:41:18Z, main `a68e1ce0`.**
  Headline now counts same-book AND pregame closes only. Verified by recomputing
  the mean from the rows at the same instant: `-0.3077` both ways, n=131,
  `in_play_excluded_n=48`, 374/374 rows carry `close_timing`.
  - **The in-play bucket flipped sign between readings** — strongly negative at
    21:1xZ, **`+0.7937` (n=48, beat 54.2%) at 21:4xZ**. The old code would now
    publish `-0.0124`. **The contamination is noise, not a fixed bias**, and it
    could have manufactured a "CLV is improving" story out of game-state drift.
  - Clean series moved 0.04 pts across 2.5h (`-0.346` -> `-0.3077`); dirty series
    moved 0.66 pts (`-0.672` -> `-0.0124`).
  - `clv_join.py` was **entirely absent from main** until `a68e1ce0` (600
    insertions), the same "lives only on a deploy branch" pattern as the
    allowlist entry.
- **OLD, kept for the record:**
- **THE DEFECT TO FIX (its own change, not done here):** `compute_clv_for_date`
  labels post-commence closes but still counts them in the headline
  `avg_clv_pct`. The docstring already anticipates this — *"a caller that wants
  only gold data can filter on them"* — but the headline IS that caller and does
  not filter. Either exclude `close_age_seconds < 0` from the headline or report
  it as a separate scope beside `same_book`, the way book scopes already are.
- **HYPOTHESES FOR THE FanDuel-h2h CELL, WRITTEN BEFORE TESTING (2026-08-15 21:3xZ):**
  - **H3 — join artifact (best-of-N open vs FanDuel close). REFUTED AT THE CODE
    LEVEL BEFORE ANY DATA WAS PULLED.** `clv_join.py:380` sets
    `open_price_override = book_prices.get(book)` whenever it matches a
    same-book close, and `:435` prefers that override over
    `opening.get("price")`. So within `same_book`, open and close are the SAME
    book's prices. The best-of-N price only survives as `open_price_best_book`,
    which is not what `clv_pct` is computed from. **This candidate is dead;
    do not re-raise it without new evidence.**
  - **H1 — real movement.** FanDuel h2h genuinely drifts against the sides we
    publish. Falsified if open/close timing and price levels look like
    DraftKings h2h, which is `+0.488` over the same events.
  - **H2 — stale openings.** Our recorded FanDuel opening is old relative to its
    close, so we are comparing a price nobody could still get. Falsified if
    `open_captured_at` / `close_age_seconds` for the FD cell match the rest.
  - **H4 — favourite/underdog asymmetry (NEW, and the arithmetic favours it).**
    `clv_pct` is in probability POINTS, and `_implied_from_american` is convex:
    the same relative move is worth more points at -250 (71.4%) than at +150
    (40%). If the FD h2h rows sit systematically on heavy favourites, the cell
    can read negative from the METRIC's scale rather than from worse prices.
    Falsified if the FD and DK h2h price distributions are comparable.
  - **H5 — side selection.** We publish one side (the value side); if that side
    is systematically the one that drifts out at FanDuel, the cell is real but
    is a statement about our selection, not about FanDuel.
  - **Sign convention, stated so nobody re-derives it backwards:** `clv_pct =
    (closing_implied - original_implied) * 100`. **Negative means the close is
    LONGER than the price we took** -- we took a short price and it drifted out.
- **CAUSE OF THE FanDuel-h2h CELL IS NOT ESTABLISHED.** Candidates not
  discriminated: FanDuel moneyline closes genuinely moving against us; our
  openings at FanDuel being stale relative to its close; or a `matched_bookmaker`
  artifact in the join. **Do not act on this until one is measured** — its own
  lane.
- **ALL OF THE ABOVE IS PRELIMINARY, same caveat as the headline:** rows fetched
  ~21:1xZ with roughly 10 of 14 MLB games unstarted, so most "closes" are latest
  observations. One date, one sport. Several buckets are n < 25. Re-run after
  the settled read before anything is promoted to a threshold change.
- **SECOND READING 2026-08-15 20:4xZ (4 of 14 MLB games started) — THE NUMBER IS
  MOVING, AND DOWNWARD.** Same endpoint, same date, ~1h later:

      reading           games started   same_book_n   avg_clv   beat_close
      19:38Z (first)         0 of 14         144      -0.0711      27.1%
      20:4xZ (second)        4 of 14         167      -0.668       29.3%

  - The biased scope barely moved (`book_agnostic_close` +2.7261 -> +2.8425,
    n=143 -> 164, beat 82.5% -> 83.5%), so the gap between the honest and the
    flattering number **widened** from ~2.80 to ~3.51 points.
  - `different_book_close` FLIPPED SIGN, +1.3907 -> **-0.5665** (n=6 -> 9). At
    n<10 that is noise; do not read it as a trend.
  - `unresolved_reasons` grew as expected: `close_precedes_open` 42 -> 64,
    `line_mismatch` 13 -> 19, plus a new `no_pregame_observation: 4`.
    `no_market_in_history` held at 172.
  - **STILL NOT THE SETTLED NUMBER.** Last first pitch is **2026-08-16T01:40Z
    (20:40 CDT)** — 10 of 14 games had not started at this reading.
  - **DIRECTION OF TRAVEL MATTERS FOR ANYONE WAITING ON THIS:** both readings
    are negative and the second is 9x more negative. Nothing here supports "the
    board beats the close"; the evidence so far points the other way.
- **A re-read is ARMED** (background monitor, fires after 01:45Z) to capture the
  settled figure. If this session is gone when it fires, run by hand:
  `/api/ops/clv/report?date=2026-08-15&sport=mlb` and record `same_book_n`,
  `avg_clv_pct`, `beat_close_rate` plus the `by_book_scope` table.
- **Minor data oddity, logged not chased:** `by_book_scope` carries a bucket
  keyed `None` with `n=0`. Harmless today; it means some row's scope label is
  null rather than a scope name. Worth a look only if `n` ever becomes nonzero.
- **`-0.0711` IS PRELIMINARY — timing, not arithmetic.** Taken 14:38 CDT, before
  first pitch for most of the slate, so most "closes" are latest observations.
  **Re-read after the last MLB game starts.** One date, one sport, 144 pairs.
- **STILL OPEN, and this is what the lane is now for:** (1) re-read post-slate
  and record the settled number; (2) NFL 246 openings / WNBA 80 both `resolved:
  0` — odds history has no markets for them; (3) NBA/NHL/NCAAF/NCAAB/soccer
  record **0 openings at all** — nobody has asked why; (4) `clv_pct` per
  recommendation, the lane's original goal, is NOT built.
- **Handed back:** lane left OPEN and unclaimed at the end of this session; the
  per-session marker was released. `artifact_publisher.py` is free.

- **THE PUBLISH FAILURE IS DIAGNOSED. Every link measured 2026-08-15 19:0xZ,
  no link inferred.**
  1. **Recorder healthy.** refresh-worker: `[clv_opening_ledger] OPENINGS
     date=2026-08-15 ... already=490`. **490 real openings exist.**
  2. **Sender tries.** refresh-worker (live `c67f7373`) HAS
     `reports/intelligence/clv_openings/*.jsonl` in `HOT_ARTIFACT_PATTERNS`, so
     it calls `publish_hot_artifact` — but only `if written:`, which is why the
     attempts are sparse rather than per-tick.
  3. **Receiver refuses: `HTTP Error 403: FORBIDDEN`**, 8 times in 16h.
     `_write_published_artifact` returns 403 on exactly one condition —
     `if not is_hot_artifact_relative_path(relative_path)` (`ops.py:1100-1101`).
  4. **Web's copy does not have the pattern.** Live web `0bf866c3` →
     0 occurrences of `clv_openings`.
  5. **Not a transport, token or size problem, and this was checked rather than
     assumed:** soccer `live_state` artifacts logged `PUBLISH_OK` to the SAME
     url with the SAME token at 19:11:25Z, seconds after a clv `PUBLISH_FAILED`.
     Zero `SKIP_NOT_CONFIGURED` lines. The file is ~286KB against a 4MiB stream
     threshold, so it takes the proven JSON-envelope path.
- **CORRECTION TO MY OWN FIRST READING, made before acting on it.** I said the
  entry was "on origin/main" and that web had merely fallen behind. **It is NOT
  on main.** Blob for `artifact_publisher.py` is `aff59302` on BOTH web
  `0bf866c3` and `origin/main`; the worker carries `ee94fe6b`. I had grepped the
  WORKING FILE and reported it as main. The entry exists only on the worker's
  deploy branch and in the working tree — it has never been committed to main,
  so it is one `git checkout` away from being lost.
- **THE FIX IS A DEPLOY, NOT A CODE CHANGE.** Diff between web's blob and the
  worker's is a single pure addition: the comment plus
  `"reports/intelligence/clv_openings/*.jsonl"`. The working tree is
  byte-identical to the worker's deployed blob (`ee94fe6b`), so shipping it to
  web makes sender and receiver agree.
- Files (exclusive to this lane): `syndicate/features/shared/artifact_publisher.py`.
  Collision check RUN via `lane-guard.py`'s own `_claims()`: CLEAR.
  **NOT claimed:** `syndicate/blueprints/ops.py` (held by `quote-feed-age-alarm`)
  — no edit needed there, the receiver logic is already correct.
- Falsification test: if web still 403s after the allowlist ships, the 403 is
  NOT coming from the allowlist branch and `ops.py:1100` is the wrong line —
  re-read the receiver before changing anything else.
- Verification: (1) a `PUBLISH_OK` line for a `clv_openings` path in
  refresh-worker's log; (2) `/api/ops/artifacts/export?pattern=...clv_openings/*.jsonl`
  returns `count >= 1, bytes > 0`; (3) `/api/ops/clv/report?date=2026-08-15&sport=mlb`
  returns `openings > 0`. **All three, or it is not fixed.**
- **DOES NOT CLOSE THE LANE.** This unblocks the measurement; it does not
  produce `clv_pct`. Breadth remains untested.

- **STATUS 2026-08-14 19:50 CDT.** Recorder LIVE (`2b14fbeb`) + `book_prices`
  LIVE (`96e3a9b7`). Joiner is **library-only, no call site, NOT deployed**
  (`deploy/clv-joiner-guards-r2`, `2f596260`). 42 tests green.
- **THE `-5.215` SAME-BOOK AVERAGE IS RETRACTED. Do not resurrect it.** It came
  from 25 rows and looked right — it even had the OPPOSITE SIGN to the biased
  scopes, which is what a genuine bias correction looks like. Two independent
  defects, now refused by name:
  - `line_mismatch` / `line_unverifiable` — history keys carry no line, the
    point's `line` block does; `home -5.0` was being differenced against a
    `home -1.5` close.
  - `close_precedes_open` — **25 of 25** closes were captured BEFORE their
    openings. **This is a PRODUCTION condition**, not a backfill artifact: it
    fires whenever a market is first published after the last pregame
    observation of it.
- **Current honest output on real data:** `same_book_n=0`, `avg_clv_pct=None`,
  `unresolved={close_precedes_open: 38, no_market_in_history: 14,
  no_pregame_observation: 23, line_mismatch: 1}`.
- **BLOCKED ON THE WORKER OOM LOOP `[2026-08-14 20:38 CDT]`.** The worker has
  been OOM-killed **18 times** today, ~1 per 11-15 min per instance across 7
  instances. Tomorrow's measurement needs the worker to stay up long enough to
  record a full day of openings, so **this lane is downstream of the memory
  lanes.** `#435` (`c9378c91`) is live and owns the diagnosis. **Worker deploys
  are HELD.**
- **TODAY'S OPENINGS ARE STRANDED ON THE WORKER.** `/api/ops/clv/report` reads
  `openings=0` for all sports while the worker has ~150+ recorded, because the
  publish fires only on `written > 0` and every 08-14 market was first-seen
  before the publish shipped. Not a bug in the recorder; a gap in when it
  pushes. One-shot-per-boot publish is the fix, and it needs a worker deploy.
- **THE MEASUREMENT IS NOW EXECUTABLE (shipped 2026-08-14 ~20:05 CDT).** It was
  not before: the joiner had no call site and the openings were unreadable off
  the worker. `GET /api/ops/clv/report?sport=<s>[&date=<d>][&rows=1]` is live on
  web (`d9a39ce8`); the worker publishes the openings (`d70f70d8`).
- **NEXT ACTION — the first clean measurement is 2026-08-15 (Central).**
  Production's 08-14 openings only began at 18:32 CDT, so tonight's file is
  late-loaded and its closes mostly predate its openings. Tomorrow, run
  `compute_clv_for_date('2026-08-15', sport)` per sport and read
  `same_book_n` + `avg_clv_pct`. **If `same_book_n` is still 0, the blocker is
  odds-history breadth** (median 2 books per event-market vs the board's best
  of ~13), not the joiner.
- **Known gaps, measured, each its own lane if pursued:** NFL and WNBA resolve
  0 — their odds-history artifact for 08-14 has no markets at all. MLB
  `_alt`/`_lay`/`3_way` families are absent from history entirely.
- **JOINER BUILT 22:5xZ** — `syndicate/features/shared/clv_join.py`, branch
  `deploy/clv-joiner` (`57e32a04`, off `2b14fbeb`). **Library only, no call
  site, NOT deployed** — it ships no production behaviour.
- **THE FIRST CLV NUMBERS THIS SYSTEM HAS EVER PRODUCED, on 150 real openings:**

      scope                  n    avg_clv   beat_close
      different_book_close  32     +6.206    29/32 (91%)
      book_agnostic_close   27     +2.716    18/27 (67%)
      same_book              0         --       --

  **`avg_clv_pct` is None and that is the correct answer.** A +6.2-pt average
  at a 91% beat rate is a SELECTION EFFECT, not skill: the board publishes the
  BEST price across books by construction, so pairing that opening with another
  book's close compares a best-of-N draw to a single draw. The headline counts
  same-book rows only; biased scopes are reported beside it, never blended.
- **What the join can and cannot reach** `[measured, mlb 78 openings]`:
  - props **28/28 matched (100%)**
  - `no_market_in_history` 18 — `h2h_lay`, `totals_alt`, `h2h_3_way`,
    `spreads_alt` are absent from odds history entirely (capture-side gap)
  - 32 game rows matched only via a DIFFERENT book
  - **NFL 0/60 and WNBA 0/12** — their odds-history artifact for 2026-08-14 has
    no markets at all. Capture-side, not a join defect. **Own lane.**
- **THE CHEAP FIX FOR SAME-BOOK CLV, and the next action:** have the opening
  ledger record a MAINSTREAM-book price alongside the best-book one. Odds
  history tracks fanduel/betmgm/draftkings; the board picks polymarket /
  prophetx / betfair_ex. One extra field on each opening makes an unbiased
  same-book comparison possible from tomorrow. Without it the headline stays
  None no matter how good the joiner gets.
- **Recorder is LIVE and verified** — refresh-worker `2b14fbeb`,
  `OPENINGS rows_in=150 written=150 ... truncated=False` at 22:32:02Z.
  Idempotence on the production disk (`written=0 already=150`) is STILL
  unconfirmed; builds are ~21 min apart.
- **UPDATE 22:3xZ — option (a) chosen by the user and SHIPPED.** refresh-worker
  `2b14fbeb`, live 22:20Z. `[clv_opening_ledger] OPENINGS ... rows_in=150
  written=150 already=0 duplicate=0 unkeyable=0 truncated=False` at 22:32:02Z.
  Openings are now being recorded; they were being lost on every build before.
- **OWED, in order:** (1) read a SECOND `OPENINGS` line to confirm idempotence
  in production (`written=0 already=150`) — builds are ~21 min apart; (2) build
  the joiner. (3) optional: put `clv_openings` on
  `/api/board/layer2-shortlist`, which currently omits it (log-only).
- **THE JOINER'S KNOWN PROBLEM, inherited deliberately:** odds history is keyed
  `event_id|home_team|away_team|market|bookmaker` with **no side and no line**;
  the side lives as `entity` INSIDE the history points. The opening ledger keys
  on `event_id|market|player|segment|side|line|bookmaker`. Mapping `side` ->
  `entity` is the unsolved half and must be measured against real data, not
  assumed — the settlement join already failed exactly here (4,560
  `no_key_match` of 8,276).
- **The close is the easy half and is already available:** stamped
  `closing_line` on only ~1.7% of markets, but `history_points > 0` on 100%, so
  derive it from the last pregame observation and LABEL which one was used
  (`observed_transition` vs `last_pregame_quote`) plus `close_age_seconds`.
- Goal: audit §7 ranked fix **#1** — produce `clv_pct` per recommendation with
  no dependency on grading, outcomes or `settle_result`. The audit calls this
  the one measurement that unblocks §4's threshold, §6's cadence decision, and
  every "where should modelling effort go" question.
- **READ-ONLY SO FAR. No files claimed, no code changed.**

**FINDING 1 — the CLOSE side is in far better shape than the audit implies,
but not where it says.** `[measured 08-14 21:3xZ via /api/ops/odds-history/inspect]`

      sport/date        markets   closing_line STAMPED   history_points > 0
      mlb  2026-08-13       1074          18  ( 1.7%)        1074 (100%)
      wnba 2026-08-13        119          11  ( 9.2%)         119 (100%)
      mlb  2026-08-14       3361           0  ( 0.0%)   (no transitions yet)

  The stamp fires only when the pregame->live transition is OBSERVED
  (`odds_refresh_tracking.py:1599` requires `was_confirmed_pregame` and a prior
  `is_live is False`). Only 81 of 1074 MLB markets were ever seen live at all.
  **Building the join on the STAMPED close yields ~18 rows.** But every market
  has history (median 20 points), so a close is DERIVABLE for ~100% by taking
  the last pregame observation before `commence_time`.
- **Design consequence:** the two are NOT the same measurement and must never be
  mixed silently — the `book_margin_model` lesson. A CLV row must carry
  `close_source` = `observed_transition` (gold, ~2%) vs `last_pregame_quote`
  (derived, ~100%) plus `close_age_seconds` = commence_time - captured_at, so a
  close taken 2h early (the pregame sweep cadence) is visible as such.

**FINDING 2 — THE BLOCKER. The OPENING side is effectively unavailable, and the
audit's premise that this is reachable "without touching the 367 MB chunk path"
does not hold.** `[measured 08-14]`
  - `data/prediction_ledger.json` holds **3 records** (it is the portfolio's
    positions — the `pending_count: 3` on `/api/portfolio/summary`), NOT the
    8,276 recommendations.
  - The 8,276 recommendation records WITH their opening `quote` are written to
    `evaluation_ledger_chunks/<date>.jsonl` — the 367 MB path.
  - `board_state_ledger_recorded_fingerprints` is only per-date HASHES; it
    records THAT a board state went into those chunks, not the openings.
  - **The chunks are not merely expensive, they are being SKIPPED at read time.**
    Observed in refresh-worker logs 21:24:54Z:
    `[intelligence_evaluation] SKIP_OVERSIZED_LEDGER_CHUNK path=2026-08-05.jsonl
    bytes=367229260 ceiling=256000000`. And 19 of 21 dates do not exist at all.
  - So openings are unreadable for every date, including the two that exist.

**THE DECISION THIS NEEDS (not mine to take alone — it is a build):**
  - **(a) Record a compact opening snapshot going forward.** One small JSONL per
    date, first-sighting-only per `market_id`: sport, market, side, price,
    bookmaker, books_quoting, fair_prob, model_prob, captured_at. Bounded by
    distinct market_ids/day (~3.4k for MLB), so kilobytes, not 367 MB. The
    joiner then needs no chunk access at all. **Cost: first real CLV number is
    ~24h away, not today.** This is what "unrecorded is unrecoverable" implies.
  - **(b) Recover openings from the 08-05/08-06 chunks.** Rejected unless
    overridden: they exceed the read ceiling and are already skipped, so this
    means raising a guard that exists for OOM reasons on a 4 GB worker, to
    recover 2 dates.
- **Recommendation: (a).** It is the audit's own "smallest change that starts
  capturing CLV" once Finding 2 is accounted for, and it does not touch the
  memory-sensitive path the two OPEN memory lanes are working.
- **NEXT ACTION:** get a decision on (a) vs (b). If (a), claim
  `pipeline/intelligence_state.py` (writer) — **currently held by
  `layer2-board-freshness`, so that lane must be consulted first.**
- Files: none claimed yet, deliberately.

### quote-join-enrich-cost — FOLLOW-UP 2026-08-14 04:37Z — the fix HOLDS, the workload OUTGREW it

- **UNION-NARROWING ANALYSIS 2026-08-14 05:0xZ — TRACED, NOT SHIPPED. Read the
  equivalence warning before writing any of it.**
  - **Where the ~12k rows/call come from.** The union is
    `by_event | by_player | team_groups`
    (`odds_book_quotes.py` ~1292-1307). For a GAME row, `wanted_teams` pulls in
    **every quote row for that game** — every market x every book x every
    selection. That branch dominates; `by_event` and `by_player` are narrow.
  - **OPTION A — market prefilter.** The caller already passes `market`. A
    `by_market` index intersected with the union would cut it by roughly the
    markets-per-game factor (potentially 10x+).
    **NOT equivalence-preserving.** Today the order is identity FIRST, then
    market narrowing with `candidates = narrowed or candidates`. That trailing
    `or` means a market-vocabulary mismatch **falls back to every row of the
    game**. Prefiltering by market removes that fallback: rows that today
    return a same-game quote would return `None`.
    Arguably MORE correct — but it is a silent-failure join, and the decision
    to drop the fallback must be made deliberately, not as a side effect of an
    optimisation.
  - **OPTION B — skip `team_groups` when `by_event` or `by_player` already hit.**
    Team matching is the FALLBACK identity signal; when `event_id` matched, its
    rows are the same game anyway. Same objection: it changes which rows reach
    `identified`, so it is not equivalence-preserving either.
  - **WHY NEITHER WAS SHIPPED TONIGHT.** The original `#414` index was safe
    because it was PROVABLY equivalent — 30+ query shapes asserted identical
    against a full-scan reference, exercising `by_event`, `by_player`,
    `by_teams_fallthrough` AND `no_identity`. Both options above deliberately
    change the identified set, so a differential test cannot pass; they need a
    test that PINS the new semantics, plus an explicit answer to "is losing the
    market fallback intended?".
  - This function's own docstring is the reason for the caution: *"a missing
    quote is visibly missing, a wrong one silently misprices the card and, once
    `#213` records it at bet time, poisons CLV."*
  - **RECOMMENDED ORDER for whoever takes it:** (1) decide the fallback
    question — it is a product call, not a performance one; (2) write the test
    that pins the chosen semantics; (3) then implement. Doing 3 first is how a
    silent mispricing ships.

- **The `#414` index is still doing its job.** 833,619 rows walked against a
  13,215,068-row shard = **6.3% scanned**, ~16x reduction, consistent with the
  21.5x measured at 00:18Z. It has not degraded.
- **But per-game cost is climbing again: 7-8s -> 14.70s.** Fresh MLB readings:
  ```
  04:37:09  total 14.70s  walked  833,619  shard 13,215,068  calls 69
  04:29:34  total  9.12s  walked  760,417  shard 12,832,072  calls 44
  04:15:55  total  4.76s  walked   16,642  shard     49,172  calls  2
  ```
- **TWO separable drivers, and neither is the index failing:**
  1. **Call count 20 -> 69 per game.** More candidates enriched — good for board
     richness, linear in cost.
  2. **Cost per call 0.2755 -> 0.7346s (2.7x).** The shard grew again:
     **~191k rows/call now**, against ~216k earlier and ~83k yesterday
     afternoon. 6.3% of a bigger shard is still more rows.
- `join` is **14.69 of 14.70s**; `post`, `score` and `unattributed_s` are all
  0.00. The segment split is clean and the join is the entire cost — same shape
  as before the fix, at a lower level.
- The two small games at 04:15 (3.95s / 4.76s on a 49,172-row shard) confirm
  cost tracks shard size closely, which is what a join-dominated profile
  predicts.
- **NEXT LEVER, unchanged from what this lane already named: the residual ~12k
  rows walked PER CALL.** Indexing removed the full-shard scan; what remains is
  a linear pass over the candidate union, and at 69 calls a game that is ~833k
  row visits per game. Narrowing the union, or making the per-row test cheaper,
  is the remaining work.
- **Do not read this as a regression of the fix.** Without the index those same
  games would walk 13.2M rows instead of 833k. The lane's verification stands;
  this records that the win is real and eroding under growth.

### quote-join-enrich-cost — PRODUCTION RESULT IN 2026-08-14 00:18Z — the index works, 21.5x measured

- **Both profilers fired at 00:11:15 and 00:18:46Z**, after
  `SYNDICATE_SLOW_ROW_TOTAL_SECONDS=1` / `SYNDICATE_SLOW_ENRICH_TOTAL_SECONDS=1`
  were set on refresh-worker (both were absent, defaulting to 5s — at which the
  instruments could never fire if the fix worked).
  ```
  SLOW_SEGMENT_PROFILE  total_s=7.17 tail_s=7.17 enrich_block=7.17
                        rows_walked=502,157  shard_rows=10,806,750  calls=50
  SLOW_ENRICH_PROFILE   total_s=7.17 join_s=7.16 post_s=0.00 score_s=0.00
                        accounted_s=7.17 unattributed_s=0.00
                        candidates=26 join_calls=26 join_s_per_call=0.2755
  ```
- **READ THESE COUNTERS AS CUMULATIVE, NOT PER-CALL.** `_bump` accumulates
  across the window, so `shard_rows` is 50 calls x ~216k, not a 10.8M-row
  shard. Per call: **216,135 rows before -> 10,043 walked now = 21.5x
  reduction, measured in production.**
- **Board-build cost 21-54s -> 7-8s.** The `#414` cause is fixed.
- **Not the 130x measured locally, and the same line says why: the shard GREW.**
  ~83k rows/call this afternoon -> ~216k now (2.6x). The index is working
  against a target that got bigger. Quote the 21.5x, not the 130x.
- `unattributed_s=0.00` — the segment accounting is complete, so the split is
  trustworthy.
- **`join_s` is still 7.16 of 7.17s.** The join remains essentially the entire
  cost; it is just 3-7x less of it. **The next lever is the residual ~10k
  rows/call, not the scan that is already gone.** Do not re-optimise the scan.
- Verification for this lane is now MET in production. What remains open is
  only whether 7-8s is acceptable, which is a different question.

### ask-sport-coverage — OPEN — ROUTING WIN LIVE + MEASURED 25->38/52 ZERO REGRESSIONS; K6 FIX IN origin/main BUT UNDEPLOYED (riding along, predicate UNMEASURED); SOCCER/NCAAB/NHL UNPROVEN ON DATA — opened 2026-08-15 — session: ask-sport-coverage
> **K6 DEPLOY STATUS, added 2026-08-15 ~20:3xZ by the coordinating session (no
> claim on this lane).** Your K6 fix `3ba1c2cf` is **NOT LIVE**. It was fired at
> 19:15:54Z and **CANCELLED mid-build at ~19:20** when a peer session started
> `dep-da0bnrflk1mc73fk95ig` — Render cancels an in-flight deploy when a new one
> begins. Re-checked against live `7abd8e12` at 20:22Z **by patch-id: still
> absent.** It is built, tested (137 green, `render.yaml` untouched, 1
> production file) and pushed as **`deploy/ask-k6-2026-08-15` (`3d68dfe4`)**,
> cut from `bebe87c9`. It was never fired because a deploy was in flight on both
> attempts. **So `K6 RETRACTED AS INERT ON PROD` still stands and no as-of
> predicate has been measured** — the retraction is not resolved by this commit
> existing on `origin/main`.
- Goal: the deterministic path names and answers for all eight sports, not
  three. Single testable outcome: `scripts/ask_syndicate_regression.py` moves
  `lookup` (2/8) and `entity` (2/10) above baseline with **no** class
  regressing, measured against the post-M1 **23/52** in
  `reports/ask_regression/post_m1_fixed_2026_08_14.json`.
- Scope, in order (from `plan_2026-08-14_ask_the_syndicate.md` K9/K2/K11/K3/K4/K5/K6):
  - K9 — NFL nickname matching (`_nfl_teams_in_question` needs the full team
    name; `_nfl_matchup_evidence` returns `None` at `len(teams) < 2`). Audit the
    same function per sport.
  - K2/K11 — `soccer` and `ncaab`: no `_SPORT_HINTS` entry, no
    `_fetchers_for_sport` branch (falls to `return []`).
  - K3 — routing collisions: `wnba` its own entry; score `_SPORT_HINTS` matches
    instead of first-match-wins; exact-match the sport filter; emit a reason
    when the filter matches nothing.
  - K4 — dispatch bugs: `nba` -> `_wnba_focused_evidence`; no-sport ranking ->
    MLB-only. **Check first whether M1 already subsumed the second.**
  - K5/K6 — `routed_sport` in the payload; as-of from `freshness.computed_at`.
- Files (exclusive to this lane):
  - `syndicate/blueprints/ask_the_syndicate_router.py`
  - NOT claimed — `syndicate/blueprints/ask_the_syndicate_data.py` is now claimed by OPEN lane `ask-answer-substance` (REASSIGNED 2026-08-16 18:5xZ).
    Kept on ONE physical line on purpose: `_claims()` is strictly per-line, so a
    marker wrapped onto the second line leaves the path on an unmarked first
    line and it still reads as a claim. Cost me one blocked edit to learn.
  - `syndicate/blueprints/ask_the_syndicate.py`
  - `tests/test_ask_sport_coverage.py`
  - `.claude/hooks/lane-guard.py`
- Collision check RUN via `lane-guard.py`'s own `_claims()`, not by grep: 19
  claims across 4 OPEN lanes at open time, **zero** overlap with the files above.
- NOT claimed, and DELIBERATELY KEPT OUT OF THE `Files` BLOCK ABOVE —
  `_claims()` reads every nested bullet under `- Files:` as a CLAIM, so a
  disclaimer written there becomes a phantom claim. **This lane did exactly that
  and it blocked real work**: `ask-headline-from-board` could not apply a
  one-line fix to `ask_the_syndicate_adapter.py` (a live `Best edge 635.0%`
  regression) because this lane's "NOT claimed" line was being read as a claim
  on it. Corrected 2026-08-15; both entries are now top-level bullets:
  - `syndicate/blueprints/ask_the_syndicate_adapter.py` — held by OPEN lane
    `ask-headline-from-board`.
  - `scripts/ask_syndicate_regression.py` — defines the predicate this lane is
    judged by; editing it would be marking my own exam. (`ask-headline-from-board`
    claims it, which contradicts the brief's "claimed by nobody".)
- Read-only dependency: `pipeline/intelligence_state.py`
  (`read_layer2_shortlist`), claimed by OPEN `memory-cutover-ship`. If a fix
  needs to WRITE there, this lane stops and hands off.
- Hypothesis: n/a for K2/K11/K3/K4/K5/K6 (defects read from code). For K9 the
  measured claim is that entity strictness alone, not missing data, is why NFL
  produces zero evidence.
- Falsification test for K9: after nickname matching resolves
  `"Patriots vs Seahawks projection"` to two teams, `_nfl_matchup_evidence`
  still returns `None` — which would mean the artifact, not the matcher, is the
  cause.
- Verification: `py -3 scripts/ask_syndicate_regression.py --out
  reports/ask_regression/latest.json` re-run and diffed per class against
  23/52. Anything that does not move a class score is NOT done. Production
  re-measure needs a deliberate `/preflight`-gated deploy (`autoDeploy: no`).
- Blocked by: none.
- MARKER CONTENTION, recorded: `.syndicate/.current-lane` is a single global
  token but four sessions are live. It held `ask-headline-from-board` when this
  lane opened. Taken for this lane and the holding session notified; they must
  re-write it before editing the adapter.

### soccer-model-coverage — OPEN — BACKTEST DELIVERED (MODEL LOSES TO MARKET, 1,112 matches, gap +0.0139); 4 FIXES BUILT + TESTED, NONE COMMITTED; #2 DELIBERATELY HELD; CALIBRATION HARNESS NEVER RUN ON REAL DATA — opened 2026-08-15 — session: soccer-model
> **DEPLOY STATUS UPDATE 2026-08-15 22:3xZ (coordinating session, no claim).**
> The **soccer as-of pair IS NOW LIVE** on live-odds-worker (`25774aaf`,
> 22:09:15Z) — `allow_undated` present in 5 places in
> `soccer/features/loaders.py`, verified by content in the deployed tree, with
> `191a001b` an ancestor so nothing was dropped. Both halves shipped together,
> so `50fd7fe2`'s MLS-emptying regression cannot recur. This supersedes the
> earlier note here saying it was built but undeployed.
> **Unchanged:** fixes #1 (seed bootstrap) and #3 (accent join) are still NOT
> committed by this lane, and **#2 (3-way de-vig) remains deliberately HELD** by
> user decision — the model measures worse than the market (Brier 0.5875 vs
> 0.5737, worse in 8 of 9 leagues) and its errors sit on favourites.
> **CROSS-LANE, added 2026-08-15 ~21:5xZ by the coordinating session (no claim).**
> The soccer **as-of pair** (`0b0d44d9` + `f05a21c4`, audit §7 #6) is on
> `origin/main` and is built into `deploy/low-props-soccer-asof-2026-08-15`
> (`25774aaf`) together with the prop `0.5` fix — but **it is NOT deployed**.
> live-odds-worker has been `HOLD` for 26+ minutes (odds refresh + rolling
> soccer builds) so no lull was found. **Take both commits or neither**:
> `50fd7fe2`, the first half, once emptied MLS ratings in production on its own.
> Route one (warm the mirror, then deploy) is armed for that service and is the
> proven technique — see `state.md`.
> **CLAIMS RELEASED 2026-08-15 AT SESSION ARCHIVE — the lane is NOT done.**
> Owning session `soccer-model` is being archived deliberately, so its file
> claims are released rather than left as an orphaned lock. This is the same
> failure mode this lane inherited from `soccer-projection-gap`; releasing on
> the way out is the fix.
> **THE WORK IS UNFINISHED AND LIVES UNCOMMITTED IN THE SHARED WORKTREE** — 9
> files, listed in `log/2026-08-15.md`. Anyone taking these files must read the
> RECONCILIATION and RECIPE CORRECTION blocks below first: `loaders.py` depends
> on the orphaned `soccer-backtest-leakage` as-of work, which `origin/main` does
> not have. **Do not `git checkout` or revert these paths casually** — that
> discards a day of tested work that no branch holds.
> **To resume: `/lane open soccer-model-coverage` and re-take the files.**
> Everything below is measured unless labelled otherwise, but re-verify before
> relying on it.
- Goal: soccer carries a REAL model on the published board. **Testable outcome:**
  `/api/board/layer2-shortlist` reports soccer rows with `model_edge_pct`
  non-null at a rate > 0 (today: `rows_with_model_edge: 0`,
  `unmatched_match_rows: 8,393` against `matches_in_source: 4`), AND a
  leak-free soccer backtest number exists for at least one league.
- **FIRST QUESTION, BEFORE ANY BUILD — the headline number is disputed 250x.**
  Two production endpoints, same sport, same date, 45s apart `[measured
  2026-08-14 19:1xZ by session model-audit]`:
  - `/api/board/layer1?sport=soccer` — rows 8,456, `rows_with_projection` 2,504 = **29.6%**
  - `/api/board/layer2-shortlist` — rows 8,512, `rows_with_projection` **12** = **0.1%**,
    `rows_with_model_edge` 0, `matches_in_source` 4, `unmatched_match_rows` 8,393
  These are two different joins and **at most one describes the board a user
  sees.** Settle which before building. If the defect is the layer2 join rather
  than projection coverage, raising coverage fixes nothing and this lane's
  shape changes.
- Hypothesis (H1): the layer2 ingest's match-key join is broken/starved
  (`matches_in_source: 4` is not a coverage number, it is an empty source), and
  projection COVERAGE at 29.6% is a separate, less urgent fact.
- Hypothesis (H2): `SOCCER_PLAYER_ROWS_MISSING league=eredivisie|primeira_liga|
  championship` `[live-odds-worker logs 19:25Z, observed once, LEAD not finding]`
  means the sim's own input is absent, so the projections that would feed either
  join are not being produced for those leagues.
- Falsification test: for H1 — if `matches_in_source` rises with no change to
  projection coverage and `rows_with_model_edge` stays 0, the join is not the
  binding constraint. For H2 — if a league that DOES project has an equally
  empty `players/` dir, the log line is not diagnostic.
- Verification: production `layer2-shortlist` counters re-read after the change,
  plus a leak-free backtest number computed with per-match as-of ratings and its
  per-family date coverage + intersection printed alongside.
- Blocked by: none. **Coordinate with UI Lane G (soccer card end-to-end) — the
  UI plan's G4 says to run these together.**
- **SCOPE FENCES, measured, do not rediscover:**
  - `player_shots` / `player_shots_on_target` map to a **mean**;
    `soccer_projections` refuses by design to derive a probability from a mean,
    and the rows are 100% one-sided so `_no_vig_over_probability` returns None.
    `player_to_receive_red_card` / `player_assists` are not in the market map.
    **These markets can never carry an edge.** Scope around, not into.
  - **MLS cannot be backtested from its current source at all** —
    `fetch_asa_mls_team_history` returns undated season aggregates; a season
    average already contains the season. Needs a per-match source that does not
    exist here.
  - **Soccer `game` odds are frozen platform-wide** (stop at 2026-08-10T20:54:06,
    all leagues); only `prop` rows are fresh, from a different producer.
  - `data/soccer_source/*/validation/*_backtest_*.csv` are **NOT CITABLE**
    (leakage, retired). Soccer backtest accuracy is **unmeasured** until this
    lane produces a leak-free number.
  - The models lane's uninformative-EV filter keys on
    `fair_method == "book_margin_model"` and **self-heals** — do not try to
    defeat it.
- Files (exclusive to this lane):
  - `syndicate/features/soccer/`
  - `scripts/build_soccer_artifacts.py`
  - `scripts/validate_soccer_vs_market.py`
  - `scripts/backtest_soccer_live_lens.py`
  - `tests/test_soccer_feature_loaders.py`
  - `tests/test_soccer_projections.py`
  - `tests/test_soccer_adapter.py`
  - `tests/test_build_soccer_artifacts.py`
  - `syndicate/features/shared/soccer_projections.py`
  - `scripts/run_live_odds_refresh_worker.py`
  - `tests/test_soccer_three_way_devig.py`
  - `tests/test_soccer_seed_bootstrap.py`

- CLAIM WIDENED 2026-08-15 02:5xZ: `soccer_projections.py` lives under
  `features/shared/`, not `features/soccer/`, and the player-props root cause is
  in the live-odds-worker ENTRYPOINT. Checked against every OPEN lane's parsed
  claims before taking them: neither is claimed. `run_refresh_worker.py` is
  deliberately NOT claimed — the `#435` session is live on that service.

- NOT this lane's files (held by live sessions, read-only here):**
  `syndicate/features/shared/recommendation_engine.py`,
  `syndicate/features/shared/layer2_board.py`,
  `syndicate/features/shared/layer1_board.py`,
  `syndicate/features/shared/opportunity_signals.py`,
  `pipeline/intelligence_state.py`, soccer card templates and `board_cards` CSS.

### live-game-line-projection — CLOSED-VERIFIED 2026-08-17 00:4xZ — v2 EXERCISED on a live slate: `written=13` across two builds, 2 of them NON-priceable — opened 2026-08-15 — session: live-gameline-eval (closed by `layer1-board-coverage`)
- **The lane's own SINGLE NEXT ACTION was run, verbatim:** read
  `live_gameline_ledger` off `/api/board/book-grid?sport=mlb&date=2026-08-16`
  during a live slate, **across two builds, never one.**
- **Its stated success criterion — quoted — is MET:** *"one live slate where
  `live_gameline_ledger.written > 0` and the counters are reachable from an
  API."*
  ```
  BUILD 1  00:37:48.762827Z   written=13 candidates=13 skipped_unchanged=0
                              projected=13 priceable=11  -> 2 NON-priceable
  BUILD 2  00:39:58.257836Z   written=13 candidates=13 skipped_unchanged=0
                              projected=13 priceable=11  -> 2 NON-priceable
  ```
  Counters served on the API, no 10 MB artifact stream needed — the second
  half of the goal.
- **The v2 discriminator held, and it is the part that could have been
  faked.** The lane warned that `skipped_unchanged > 0` is NOT the signal
  (seen under v1 at 04:22:51Z, which refuted this lane's own earlier claim).
  Here `skipped_unchanged` is **0** and `written 13` exceeds `priceable 11`,
  so **2 rows that v1 could never have written were recorded** — on both
  builds. Withheld: `segment_is_not_full_game` 49,
  `prob_interval_swamps_edge` 2, of 62 considered.
- Measurement in `deploys.md` with the window stated, which was this lane's
  literal Verification line.
- **TWO THINGS THIS DOES NOT ESTABLISH, carried forward so they do not
  disappear with the lane:**
  1. **The edges are still UNSCORED.** The old heading's "THE EDGES ARE
     UNEVALUATED" is a broader ambition than the Goal this lane actually
     stated. The ledger can now produce a sample; nobody has measured
     whether those 11 edged rows were RIGHT. **Needs its own lane.**
  2. **The ledger's RSS was never measured.** This lane records an
     `oomKilled` at 04:46:44Z, 22 min after its deploy added work to
     refresh-worker, and says plainly it is *not* claiming exoneration.
     **That debt is NOT discharged here** — it stays with
     `refresh-worker-oom-recurrence` (OPEN). Kill switch, no deploy:
     `MLB_LIVE_GAMELINE_LEDGER_ENABLED=0` (currently ABSENT = enabled).

**STATUS AT CHECKPOINT `[15:2xZ]`.** Nothing uncommitted; everything is on
`origin/main` and content-verified there. web `ebd5f677` live 03:38:07Z,
refresh-worker `5c419007` live 04:24:33Z — and `LEDGER_VERSION = 2` is
content-verified on the CURRENTLY live `d72d670c`, which another lane deployed
at 06:01:34Z and carried it forward. Board at 15:17Z reads `index_size 0,
considered 0` — Sunday pregame, nothing live yet.

**THE SINGLE NEXT ACTION:** read `live_gameline_ledger` off
`/api/board/book-grid?sport=mlb&date=2026-08-16` during tonight's slate
(scheduled `live-gameline-ledger-check`, 20:30 Central). **The discriminator
for v2 is `written` rising on rows that are NOT priceable.**
`skipped_unchanged > 0` is NOT it — that was already observed under v1 at
04:22:51Z, which is what refuted this lane's own "never recorded a row".
Read across two builds, never one.

**ONE UNPAID DEBT:** an `oomKilled` fired at 04:46:44Z, 22 min after my
deploy added work to refresh-worker. Recorded by `refresh-worker-oom-recurrence`,
and `44ad2f9d` reports `d72d670c` as 9h clean since — **but I never measured
the ledger's RSS and I am not claiming exoneration.** Kill switch, no deploy
needed: `MLB_LIVE_GAMELINE_LEDGER_ENABLED=0` (currently ABSENT = enabled).

— original re-take header follows —
### live-game-line-projection — SUPERSEDED (see CLOSED-VERIFIED 2026-08-17 00:4xZ above) — RE-TAKEN 2026-08-16 03:0xZ (session `live-gameline-eval`) — TIER 5'S PREMISE IS TRUE IN PRODUCTION; THE EDGES ARE UNEVALUATED
- Goal: make the ledger capable of producing a sample at all, and make its
  counters readable without streaming a 10 MB artifact. Success = one live slate
  where `live_gameline_ledger.written > 0` and the counters are reachable from
  an API.
- Files: `syndicate/features/shared/live_gameline_ledger.py`,
  `tests/test_live_gameline_ledger.py`.
- **`syndicate/blueprints/intelligence.py` RELEASED 2026-08-17 00:4xZ — second
  double-claim on this lane, resolved the same way as the first.** It was
  contested with `layer2-board-quality`, which holds it in a nine-path list and
  reads **ALL 8 GOALS SHIPPED**; this lane is `OPEN, UNOWNED` since 15:2xZ and its
  own stated single next action is a READ of `/api/board/book-grid`. Finishing it
  needs no edit here. **TO RE-TAKE:** put the path back and tell
  `layer2-board-quality`.
- **`syndicate/features/shared/live_gameline_join.py` RELEASED 2026-08-17 00:2xZ
  — it was double-claimed, and this lane is the one that does not need it.**
  Reconciled by the `ask-answer-substance` session (holds no claim on either
  lane) on evidence, not preference:
  - `mlb-live-gameline-distributions` also claims it, is the file's ACTIVE
    EDITOR (`c7e39e58`, "the re-sim's own histograms, not just their means", is
    its work and is already in the file), and its goal is literally "consume +
    price" there. Its session is idle-but-resumable, last active 00:15Z.
  - this lane reads `OPEN, UNOWNED` since the 15:2xZ checkpoint, and its own
    stated SINGLE NEXT ACTION is a READ of `/api/board/book-grid` — finishing it
    requires no edit here.
  **HOLDER CHANGED WITHIN THE HOUR, 2026-08-17 00:3xZ:**
  `mlb-live-gameline-distributions` went **CLOSED-VERIFIED** and
  **`wnba-live-tier`** (restored, same work family) now holds this path. Still exactly
  one holder, which is the point — but the counterpart to coordinate with is now
  `wnba-live-tier`, not the closed lane.
  **TO RE-TAKE:** put the path back on the `- Files:` line above and tell
  `wnba-live-tier`. The release is a coordination decision
  between two unattended lanes, not a judgement that this lane's interest was
  invalid — it wrote the `edge_vs_market_pct` line that sits there.
- Collision check at re-take: no OPEN lane claims any of the four above.
  `refresh-worker-oom-recurrence` names `syndicate/features/intelligence.py` as an
  expected candidate — a DIFFERENT file from `syndicate/blueprints/intelligence.py`.
  **Kept OUT of the `- Files:` block on purpose:** `_claims()` reads every nested
  line under `- Files:` as a CLAIM, so a disclaimer written there becomes a
  PHANTOM claim on a file this lane does not hold. `ask-sport-coverage` was bitten
  by exactly this and it blocked another lane's one-line fix.
- Deploy intent: **PREPARE ONLY.** The recorder runs on refresh-worker, and
  `refresh-worker-oom-recurrence` has an explicit hold on deploys to that service
  until its attribution is written. Request file, not a deploy.
- Verification: written to `deploys.md` with the window stated.
- Blocked by: refresh-worker deploy hold (`refresh-worker-oom-recurrence`) for
  the recorder half only. The web half is unblocked.
- **Took `.syndicate/.current-lane` from `refresh-worker-oom-recurrence`** — one
  single-valued marker, N sessions, the known root cause. That lane claims no
  files, so the cost is bounded.

**MEASURED 2026-08-16 03:00–03:1xZ on a LIVE slate (2 games live, 13 final).**
Source: the `book_grid_2026-08-15.json` artifact streamed from web
(`/api/ops/artifacts/stream`, 9,953,474 bytes, `generated_at 03:00:00.538Z`) and
`/mlb/api/live-lens` at 03:00Z. Both read at the same instant, both post-date
`f8ca54e1`.

    live_gamelines       considered 8  projected 2  priceable 0  edged 0
                         withheld 8 = {segment_is_not_full_game: 6,
                                       prob_interval_swamps_edge: 2}
                         index_size 10
    live_gameline_ledger candidates 0  written 0  enabled true

1. **`index_size` IS EXPLAINED. It is not a live-game count and nothing is
   wrong.** It counts snapshot games carrying a `live_mc` lens. Census at 03:0xZ:
   **10 of 15 games carry one — 8 FINAL and 2 LIVE.** A Final keeps its last
   `live_mc` lens, so the number is monotone through a slate: 3 → 8 → 10 is just
   how many games had gone live-or-through-live by each read. **The join loop
   filters on `game.state == live` on the GRID side, so the Final entries are
   never used** — the counter is misleading, not the join. Retire the "unexplained"
   framing; the defect, if any, is that this is the one counter in the block with
   no denominator, which is exactly what invited the wrong reading.
2. **THE RECORDER CANNOT PRODUCE A SAMPLE, AND THIS IS THE REAL BLOCKER.**
   `build_records` skips any row that is not `priceable`; `priceable` requires the
   edge to clear a 2σ bar at 120 sims. Tonight that is **0 of 8**, so
   `candidates: 0` — the ledger was never asked to write anything. **The
   scheduled `live-gameline-ledger-check` will very likely read `written: 0`
   again tomorrow, and that will mean neither "broken" nor "working."**
3. **The filter's stated justification is wrong by three orders of magnitude.**
   The docstring refuses non-priceable rows because "recording thousands of
   refusals per build would bury the handful CLV can score." The measured
   population is **8 rows per build, 2 of them projected.** There are no
   thousands. Recording every PROJECTED row costs ~2 records/build against a
   20,000-record file cap, and it is the difference between a sample and none.
4. **`liveStateAsOf` and `liveStateCarriedForward` are `None` on all 10 lensed
   games, including the 2 live ones.** Consistent with "Drop 2's carry-forward has
   never fired" AND with "the stamp is only applied on the carry-forward path."
   **Not disambiguated — do not record either as established.**

**BOTH HALVES ARE NOW DEPLOYED — 2026-08-16 04:2xZ. `DEPLOYED NOWHERE` below is
SUPERSEDED; the rest of that block still reads true.**
- web `ebd5f677` live 03:38:07Z — the counters are served. Measured null -> object
  across two artifacts.
- refresh-worker `5c419007` live 04:24:33Z — ledger v2. **Deployed and NOT YET
  EXERCISED:** the slate ended between the last pre-deploy build and the first
  post-deploy one, so `considered` went 4 -> 0 and v2 has had no live row to act
  on. Both parented on their service's LIVE SHA, never on main.
- The `refresh-worker-oom-recurrence` hold cleared on its own evidence
  (`9ed17262`: a ~2 GB transient, not a leak) rather than being overridden. I
  asked that session first; it archived between the question and the answer.

**CORRECTION TO THIS LANE'S OWN FINDING #2 ABOVE — read it before quoting the
arc.** "The recorder has never recorded a row" is **FALSE**. The 04:22:51Z
pre-deploy build read `priceable 1, candidates 1, skipped_unchanged 1`, and
`skipped_unchanged` cannot be non-zero unless a matching record already sits on
disk — an empty file always writes, because `_moved(None, rec)` is True. **v1
wrote at least one row tonight**, between 02:4xZ and 04:22Z. The 03:00Z reading
was real and I generalised it to a night. v2's premise survives (1 priceable of 4
considered is a self-selected sample), but "it structurally could not write" was
an overclaim.

**NEXT ACTION is now purely measurement, and the plumbing question is closed.**
`live-gameline-ledger-check`, 20:30 Central 08-16, on a full slate:
`written > 0` on one build, then **`skipped_unchanged > 0` on a later one** —
the second is the real test, and note it has ALREADY been observed once under
v1, so the discriminator for v2 is `written` rising on rows that are NOT
priceable. Read across two builds, never once.

**CHECKPOINT 2026-08-16 03:4xZ.** Shipped to `origin/main`, DEPLOYED NOWHERE:
`c87f6634` (ledger v2 + the book-grid pass-through + 2 test files),
`bbc70d16` (the two deploy requests), `4e82d4b7` (the learnings rule).
97 tests pass, and the pass-through was falsified first — commenting out the two
served keys fails all 6 new tests.

**THE ONE THING THAT DECIDES WHETHER TOMORROW IS A TEST:** the v2 recorder must
be on refresh-worker before the scheduled `live-gameline-ledger-check` fires at
**08-16 20:30 Central**. Against v1 it reads `written: 0` again and means nothing.
That deploy is HELD by `refresh-worker-oom-recurrence`, deliberately — the hold is
correct and the deadline is real, and only the user can trade them off.

**NEXT ACTION for whoever picks this up:** not code. Get the refresh-worker
deploy decided. Everything after it is measurement:
`live_gameline_ledger.written > 0` on one build, then `skipped_unchanged > 0` on
a later one — **the second is the real test**, because the append proving it
writes is not the dedup proving it writes only on movement. Read it across two
builds, never once.
**Lane stays OPEN** — the projection ships, but nothing yet says the edges are good.

**SHIPPED AND LIVE (content-verified per service, not by ancestry):**
- live-odds-worker `c4116ab6` — the live MC stamps `simsRun`.
- refresh-worker `f8ca54e1` — the game-line join, the segment filter, the
  Agresti-Coull boundary, and the CLV recorder.
- web carries D1+D2; it needs neither the vendor stamp nor the join.

**THE ARC, in measured numbers:**

    baseline   index 3   projected 12  edged 0   (sim_count_unusable 12)
    +simsRun   index 8   projected 32  edged 25  <- FIRST EVER, and WRONG
    +segment   index 10  projected  5  edged 4   <- first credible ones
    tail       index 10  projected  2  edged 0   (slate over; ledger written 0)

**THE 25 WERE FAKE AND I RETRACTED THEM MYSELF**, caught while packaging them
for handoff: Wald `sqrt(p(1-p)/n)` is **0.0 at p in {0,1}**, so the 2-sigma bar
was ZERO and everything cleared it; and the full-game projection was priced
against every SEGMENT (SD @ CLE `first1` gave **+42.43 pp**). Both fixed.

**WHAT IS NOT ESTABLISHED — do not let the arc imply otherwise:**
- **No CLV, no settlement, no backtest.** Surviving means an edge exceeds the
  ESTIMATOR'S OWN NOISE at 120 sims. It says nothing about the model.
- **The recorder has never recorded a row** — it went live on a finished slate.
  `written: 0` with `enabled: true` proves wiring, not behaviour.
- **`index_size` 3 -> 8 -> 10 across the night is unexplained.**
- **Drop 2's carry-forward has never been observed firing.**
- The tally is MLB-only; soccer/wnba report `liveMcSources: null`.

**HANDOFFS, all verified present in HEAD:**
- `clv-without-settlement` — the rows are TRANSIENT (edged 25→4→1 on one slate);
  the recorder is the prerequisite, and `clv_join.py` was deliberately untouched.
  Carries two corrections: **Pinnacle is 15/30 in production** (the sharp SET is
  30/30), and "close" is ill-defined for a live market.
- `memory-watchdog-435` — a **2,092 MB** in-process excursion, pid 39, 34 s,
  children proven flat. ~3x `#327`'s largest.
- `soccer-model-coverage` — `SOCCER_PREGAME_AUTORUN_FAILED` lock contention.

**COSTS I IMPOSED, recorded rather than netted out:** three soccer runs killed,
one wrong rollback of a working fix, and two deploys fired over another
session's claim. **No claims held; refresh-worker and live-odds-worker are free.**

**NEXT SESSION STARTS HERE:** tomorrow's live slate is the first real test —
does the ledger grow only on movement, and do the surviving edges beat a sharp
close. **That is evaluation, not plumbing.** The plumbing is done.

### refresh-worker-oom-recurrence — OPEN — **ATTRIBUTED, NO DEPLOY MADE. `#435` did NOT regress (`c67f7373` is an ancestor of live `f8ca54e1`; the ledger's `2,869 -> 1,071` is the book_quotes READ, not container anon — different quantities). The kill is a ~2 GB TRANSIENT, not a leak: 22 excursions over 5 deploy-free windows, amplitude FLAT all night, every cycle reaches headroom 0.0, and the two kills are the two thinnest-page-cache cycles (inactive_file 26.3 / 42.2 MB vs 164–240 MB surviving). Measurement in `deploys.md`. ALSO THIS SESSION: adjudicated the stale shared index (3 revert-in-waiting blobs disarmed, incl. one that would have stripped the LIVE Drop 3 hook), notified the 2 reachable live sessions, and FIXED `commit-guard.py` to gate on the staged BLOB rather than name-status — 4-case falsification suite passes, 5273ms -> 659ms. OPEN because the allocator inside the 2 GB pass is still UNNAMED and needs an in-pass measurement, which needs a deploy, which needs the clean window (42.8 min at 03:19Z) to mature first** — opened 2026-08-16 — session: refresh-worker-oom-recurrence
- Goal: Decide, on evidence, whether the two `oomKilled` events (02:11:34Z,
  02:37:06Z, `memoryLimit 4Gi`, refresh-worker only — live-odds-worker zero in
  the same window) mean `#435` REGRESSED or that `#435` fixed one contributor
  and a SECOND one is now binding. Then attack whichever is actually binding.
  Success = a written attribution in `deploys.md` backed by a **deploy-free**
  window, with the window stated.
- Files: none claimed yet — this lane is diagnostic until the attribution is made.
- **Expected candidates when it turns into a change** (deliberately NOT under
  `- Files:` — `_claims()` reads every indented line there as a CLAIM, so listing
  a candidate inside that block claims it):
  `syndicate/features/intelligence.py` (the 3000MB
  `_OVERVIEW_MIN_SAFE_HEADROOM_BYTES` floor), `syndicate/blueprints/home.py`
  (MLB hydration entry), `syndicate/features/shared/memory_observability.py`.
  Checked against every OPEN lane's `- Files:` at open time: the only claims held
  anywhere were `pipeline/intelligence_state.py` +
  `syndicate/features/wnba/cards.py` (`clamp-fix-to-workers`). No overlap.
  **These five were live PHANTOM claims until 2026-08-17 00:4xZ**, including a
  contested `wnba/cards.py` against `wnba-live-tier`.
- Hypothesis (to be falsified, NOT assumed): `#435`'s `read_book_quotes_latest`
  streaming fix is still in effect on the deployed tree, and the 3,857MB anon at
  02:37:00Z is a DIFFERENT contributor — the standing finding that the kill is
  MLB game hydration in the main worker process (`build_cards_page_context`
  running HYDRATED), which the 3000MB floor does not guard because that floor
  sits in front of `build_intelligence_overview`.
- Falsification test: if the deployed refresh-worker SHA does not contain the
  `#435` streaming reader, or if the book_quotes read is measurably back at
  whole-file cost on the current shard, the hypothesis is WRONG and this is a
  regression, not a second contributor. Positive control required on every log
  query; kills read from `/v1/services/<id>/events`, never from logs.
- Known confound, stated before measuring: refresh-worker took **four deploys
  between 01:31 and 02:25** (win_prob instrument work). Every deploy reboots and
  re-runs hydration cold. Any before/after spanning that window is confounded —
  the window used must be deploy-free and long enough to re-warm (the floor is
  the ratchet).
- Verification: an attribution written to `.syndicate/deploys.md` with its
  working, naming the window and the number of kills in it. No deploy to
  refresh-worker unless the attribution demands one — the `win_prob` counter
  cannot produce a reading until this service gets an hour without a kill or a
  deploy, which is a reason to keep deploys OFF, not to add one.
- Blocked by: none.

#### soccer-model-coverage — COMMIT HYGIENE + FINAL TEST NUMBERS 2026-08-15

**DO NOT COMMIT `loaders.py` AGAINST `origin/main`. The as-of work it builds on
is UNMERGED, and a naive commit would sweep in another lane's branch work.**
`[measured]` `git show origin/main:.../loaders.py | grep -c as_of` returns **0** —
`compute_team_ratings` on `origin/main` has no `as_of` parameter at all. The
whole `soccer-backtest-leakage` machinery lives only on branch
`fix/soccer-backtest-leakage` (tip `2dcca4fe`) and in this shared worktree.
`git merge-base --is-ancestor fix/soccer-backtest-leakage origin/main` -> **NO**.

    vs origin/main                    loaders.py  153 insertions  (THEIRS + MINE, mixed)
    vs fix/soccer-backtest-leakage    loaders.py   73 insertions / 3 deletions  (MINE only)

`validate_soccer_vs_market.py`, `backtest_soccer_live_lens.py` and
`build_soccer_artifacts.py` show **zero** diff against that branch — the
worktree already matches it, which is why they read as "modified" against a
local `main` that is 129 commits behind `origin/main`.
`soccer_projections.py` (+120) and `run_live_odds_refresh_worker.py` (+30) ARE
purely mine — those files are identical at `HEAD` and `origin/main`.

**RECIPE: branch from `fix/soccer-backtest-leakage`, not from `main`.** Stack,
do not merge — the same rule `learnings.md` records for pinned deploys. Commit
through an isolated `GIT_INDEX_FILE` with an explicit pathspec, never
`git add -A`, and read `git diff --cached --stat` before committing: the shared
index has held another session's 4,993 staged deletions before.

**Exactly 7 files, no strays** `[git status, scoped]`:

    M  scripts/run_live_odds_refresh_worker.py
    M  syndicate/features/shared/soccer_projections.py
    M  syndicate/features/soccer/features/loaders.py
    ?? scripts/backtest_soccer_h2h_calibration.py
    ?? syndicate/features/soccer/seed_bootstrap.py
    ?? tests/test_soccer_history_date_parsing.py
    ?? tests/test_soccer_seed_bootstrap.py

**FINAL TEST STATE:** full `-k soccer` after all four changes —
**571 passed, 0 failed** (1273s), against a 553/0 baseline taken before the
loaders change; the delta is the 18 new soccer-matching tests. Blast-radius set
378/0. Every new test mutation-verified red.

**NOTHING COMMITTED, NOTHING PUSHED, NOTHING DEPLOYED.** Fix 1 is inert until a
live-odds-worker deploy. Fix 2 should NOT ship without the calibration number —
see the dispersion finding above.

#### live-game-line-projection — STATUS 2026-08-15 03:5xZ — SPEC PHASE COMPLETE, NO CODE WRITTEN
- **Deliverable:** `.syndicate/spec_live_game_line_projection.md` (`9067b606`).
- **H1 (the merge at :1094 rejects the MC lens) — EFFECT CONFIRMED, MECHANISM
  NOT YET DISCRIMINATED.** The served snapshot carries 3 card-derived lanes,
  `source: None`, 0 `modelHomeWinProb`, against `_build_game_lens`'s 6 sourced
  lanes. Whether the merge rejected it or the payload never arrived is spec §6.1
  and is the FIRST build step — recorded as unproven rather than banked.
- **H2 (the published report is the slim shape with no `gameLens` field) —
  CONFIRMED** from the deployed `ccd10349:scripts/refresh_mlb_oddsapi.py:764` and
  the published artifact's own zeroed `perf` + `gameLens rows 0`.
- **The MC runs:** 9 `LIVE_MC_BAIL` per tick × 11 ticks, all `status_not_live`,
  against 9 Final / 5 Live. One uninstrumented exit named in the spec.
- **Sequencing correction, re-derived here:** `0.1` is not a prerequisite for the
  live product; the 1800s cooldown is bypassed whenever any game is live.
- **`rows_live_edged` is a PROP counter and this lane does not move it** — the
  lane's own success metric is a new `rows_live_gameline_*` family. The brief's
  framing invites that conflation; recorded so it is not made.
- **Awaiting a product answer on spec §8.1** (120 sims → ±4.56 pp SE; publish
  refusing to price / raise the sim count / never price). Recommendation: publish
  refusing to price, zero added compute.
- No deploy. refresh-worker was `update_in_progress` (`eea7554a`) at lane-open.

#### soccer-model-coverage — RECIPE CORRECTION 2026-08-15. MY OWN PREVIOUS NOTE WAS WRONG.

**"Branch from `fix/soccer-backtest-leakage`" IS WRONG AND WOULD BE A MASSIVE
ROLLBACK.** `git diff --stat origin/main fix/soccer-backtest-leakage` =
**127 files, 3,618 insertions, 33,673 DELETIONS** — the branch predates a full
day of many sessions' work (clv_join, layer2 uninformative-EV, the UI lanes,
the whole `.syndicate` ledger). It is also 114 lines BEHIND `origin/main` on
`scripts/run_live_odds_refresh_worker.py`, the very file I edited. This is the
same shape as `state.md`'s "a branch cut for web is a ROLLBACK for
refresh-worker" — I reproduced the mistake one note after quoting the rule.

**THE ACTUAL SITUATION.** The `soccer-backtest-leakage` as-of change is
UNCOMMITTED IN THE SHARED WORKTREE (its session is archived; `origin/main` has
`as_of` count **0**). It spans `loaders.py`, `build_soccer_artifacts.py`,
`validate_soccer_vs_market.py`, `backtest_soccer_live_lens.py` and
`tests/test_soccer_team_ratings_as_of.py`. **My date fix sits on top of it and
is meaningless without it** — `_as_iso_day` repairs a comparison that only
exists in that change.

**SO THE COMMIT NEEDS A DECISION, NOT A RECIPE — flagging rather than
guessing.** Branch from `origin/main`, then either:
 (a) two commits — land the orphaned as-of work first (it is CLOSED-VERIFIED
     and was always meant to land), then mine on top, preserving attribution; or
 (b) one commit that states plainly it carries both.
Either way the `compute_team_ratings` signature change forces its callers to
come along, so the 5 as-of files cannot be left behind.
**Do NOT cherry-pick my `loaders.py` alone onto `origin/main`** — it would call
`compute_team_ratings(as_of=...)` against a signature that has no such
parameter.

#### live-game-line-projection — H1 CONFIRMED 2026-08-15 04:0xZ, and the open discriminator is now MOOT
- **Method:** imported the codebase's own `_lens_rows_have_projection_signal`
  and evaluated `should_use_projection_lens`'s three disjuncts over the served
  production payload, per live game. Not a code reading — the real function over
  real data.
- **Result: `False` on 5 of 5 live games.** `card_game_lens` non-empty (4 rows),
  game is live, and the card's text-derived lens HAS signal — e.g. game 824159
  `first1 projection={'homeMargin': 0.57, 'total': 1.31}`.
- **This moots the discriminator the spec listed as build step §6.1.** The third
  disjunct was the only one that could rescue the MC lens, and it is False
  *because the card lens has signal*, independent of what the MC produced. So
  **even if the MC payload arrives with a full lens, it is discarded.** Whether
  it arrives no longer changes the outcome — only the fix's shape.
- Residual caveat, stated: the card lens was read from web's served payload as a
  proxy for the worker's. Same producer (`_live_lens_segments_from_card`) both
  places, and the values are visibly pregame interpolations, but it is a proxy.
- **USER DECISION on spec §8.1 (2026-08-15): PUBLISH, REFUSE TO PRICE.** Ship at
  120 sims carrying `probStdErr` and a `priceable` gate; do not raise the sim
  count now. Zero added compute; leaves the raise available once §6.2 measures
  what a sim costs on live-odds-worker (84–89% of 2 GB).

#### soccer-model-coverage — THE OWED NUMBER, DELIVERED 2026-08-15. THE MODEL LOSES TO THE MARKET.

**First leak-free soccer backtest number this repo has ever had.**
`scripts/backtest_soccer_h2h_calibration.py`, **1,112 matches / 9 leagues**,
ratings recomputed per match day with `as_of` set to that day — only
meaningful because `_as_iso_day` repaired the inert filter first.

    MODEL  multiclass Brier  0.5875
    MARKET multiclass Brier  0.5737   (proportionally de-vigged closing odds, same matches)
    gap                     +0.0139   lower is better -> THE MODEL LOSES

    league               n   model   market     gap   m_stdev  mkt_stdev
    eredivisie         126  0.5211   0.5064  +0.0147   0.1886   0.2257
    primeira_liga      125  0.5722   0.5405  +0.0317   0.1596   0.2088
    championship       126  0.6158   0.6061  +0.0097   0.1237   0.1540
    belgian_pro_league 120  0.6045   0.6056  -0.0011   0.1484   0.1696
    epl                120  0.5794   0.5572  +0.0222   0.1617   0.2021
    la_liga            123  0.5947   0.5846  +0.0101   0.1518   0.1545
    bundesliga         126  0.5840   0.5653  +0.0187   0.1898   0.1861
    serie_a            120  0.5970   0.5869  +0.0101   0.1574   0.1724
    ligue_1            126  0.6201   0.6117  +0.0084   0.1367   0.1566

**Worse in 8 of 9 leagues; two-sided sign test p = 0.039.** The lone exception
(belgian_pro_league, -0.0011) is noise at n=120 and must not be reported as a
win.

**THE UNDER-DISPERSION DIAGNOSIS IS CONFIRMED BY AN INDEPENDENT ROUTE.** Mean
model stdev(P home) **0.1575** vs market **0.1811**, narrower in **8 of 9**
leagues. eredivisie's reliability curve shows the model too TIMID at both
ends: predicted 0.144 -> actual 0.000; predicted 0.823 -> actual 1.000. The
production-artifact stdev (0.1364 over 166 rows) and this backtest stdev
(0.1575 over 1,112) agree on the shape.

**THE DECISION THIS FORCES.** Soccer's model must NOT publish `model_edge_pct`
yet. A model that loses to the closing line over 1,112 matches emits edges that
are noise against a better-informed price — and its errors are systematically
on the favourites, so those edges point at underdogs. **Fix #2 removes a stale
BLOCK; it does not make the number publishable.** Ship #1 (seeds), #3 (accent
join) and #4 (as-of) freely — they are correctness fixes with no such hazard.

**Coverage, per the `data/**` rule:** eredivisie 918 history rows spanning
2023-08-11..2026-05-17; with result 918; with complete closing odds 918;
**intersection 918**. This does not rest on a narrow join. Matches are skipped
where either side has <20 prior as-of matches (eredivisie: 180 skipped, 126
scored at `--limit 120`), so early-season rows are not scored as though the
model had an opinion.

**Named, cheap levers, neither done:** sharpen the distribution, and raise
`adapters._DEFAULT_SIMULATIONS` from 300 (±2.9pp of pure Monte Carlo noise).
`SoccerSimulationOutput.evaluation.calibration.win_probability.brier` is still
`None` — the harness exists but is not wired into the sim's own slot.
Full result: `reports/soccer_backtest/h2h_calibration_2026-08-15.json`.

### clamp-fix-to-workers — CLOSED-VERIFIED 2026-08-17 00:0xZ — the ±4900 clamp is gone from all three live services, and 7,002 served fair_price values carry none**
- **CLOSED 2026-08-17 00:0xZ, ~10 minutes after the refusal below, because
  the missing piece SHIPPED IN THE INTERVAL — and not by me.** Another
  session deployed `c348da53` to live-odds-worker at 23:57:12Z
  ("converge origin/main into live-odds-worker's deploy lineage"), which
  carried the clamp removal along with everything else on main. Credit
  where it belongs; this lane did not ship it.
- **I did NOT ship a duplicate.** The user authorised shipping the deferred
  fix; before cutting anything I re-read the live SHA and found it had
  moved from `16a898ef` to `c348da53` with the work already in it. Cutting
  on the stale SHA would have re-applied a change that was already live.
- **STRUCTURAL HALF: PASSES.** Clamp sites (`max(0.02, min(0.98`) by
  content at each service's CURRENT live SHA, all three re-read at 00:0xZ:
  ```
  web              9f617f34   0   (intelligence_state 0, cards 0, layer2_board 0)
  refresh-worker   fdc72dd0   0   (0, 0, 0)
  live-odds-worker c348da53   0   (0, 0, 0)
  ```
  Both sites now delegate to `american_price`, which REFUSES a probability
  outside (0,1) instead of clamping it.
- **PRODUCT-LEVEL SWEEP, the number this lane never had:** **7,002 served
  `modelled_fair.fair_price` values** across mlb + wnba + soccer,
  **0 at ±4900**. That is a real denominator, against the 6-row shortlist
  the watcher kept reading.
- **THE ORIGINAL BEHAVIOURAL CRITERION NEVER FIRED, AND IS NOW MOOT —
  stated rather than quietly dropped.** `watch_clamp_trigger.py --once`
  returned `no_trigger` on all FOUR reads (00:24Z, 01:30Z, 23:49Z,
  00:00:39Z); the last read `p=[0.227201, 0.512829] out_of_clamp=0`. It was
  never satisfied because no slate in that window carried an out-of-clamp
  probability. It is moot because a `POST_FIX_OK` proves a clamped
  PRODUCER priced correctly, and there is no longer a clamped producer on
  any live service. **What remains unproven by THIS lane is that
  `american_price` prices an extreme probability correctly in production —
  a different claim, covered by its own unit tests, not by this one.** — opened 2026-08-15 — session: clamp-fix-verification-watch
- **CLOSE ATTEMPTED AND REFUSED 2026-08-16 23:5xZ.** Both halves of this
  lane's own Verification line were checked. Neither passes.
  - **Behavioural half: still never fired.** `watch_clamp_trigger.py --once`
    at 23:49:14Z read `served_rows=6 p=[0.145882, 0.874966] out_of_clamp=0`
    -> `no_trigger (proves nothing)`. That is the THIRD inconclusive read
    (00:24Z, 01:30Z, 23:49Z). A quiet slate reads identically with the bug
    fully present, which is why this lane already refused to bank it.
  - **Structural half: FAILS, and this is the new finding.** Clamp sites by
    content at each service's LIVE SHA, counting `max(0.02, min(0.98`:
    ```
    web              9f617f34   0
    refresh-worker   fdc72dd0   0
    live-odds-worker 16a898ef   2   <- intelligence_state.py 1, wnba/cards.py 1
    ```
- **One of the two is dormant; the other is REACHABLE AND PUBLISHING.**
  - `pipeline/intelligence_state.py` — dormant on this service:
    `SYNDICATE_ENABLE_INTELLIGENCE_STATE_BACKGROUND_LOOP=false` in its live
    env, so the loop never starts. **Dormant is not fixed** — loop ownership
    is an env flag that moves with no diff, so this is a latent re-arm.
  - `syndicate/features/wnba/cards.py:848` — **REACHABLE.**
    `_american_from_prob` still clamps, and it is called at :1614/:1616 to
    produce `home_ml`/`away_ml` on the WNBA cards THIS SERVICE BUILDS AND
    PUBLISHES (it runs `start_live_lens_loop`). The served lens carries
    those exact fields in each game's `betting` block.
- **Not observed firing today, and that is not evidence of absence.** The
  served WNBA cards at 23:5xZ read `away_ml` -749.55 / 186.21 / 146.13 —
  no value at ±4900, because no game today is lopsided enough to push a win
  probability past 0.98. Same quiet-slate confound as the watcher.
- **What would let this lane close:** ship the deferred fix to
  live-odds-worker (`079cc42b`, re-cut on live `16a898ef`), taking all three
  services to 0 sites. At that point the clamp CANNOT be published because
  it does not exist, and the never-firing behavioural trigger stops being
  load-bearing. **That deploy was DEFERRED BY USER DECISION and is NOT being
  taken unilaterally.**
- Note: tonight's live-odds-worker deploy (`16a898ef`, the WNBA live_state
  carry-forward) was deliberately cut on live `440f5f29`, which already
  carried these 2 sites — so it PRESERVED the deferral rather than
  silently resolving or worsening it.
- Files: `pipeline/intelligence_state.py`, `syndicate/features/wnba/cards.py`.
  - **`syndicate/features/shared/layer2_board.py` DELIBERATELY NOT TOUCHED** — it
    is claimed by OPEN `spread-line-sign-convention`, and that lane's worker
    deploy already carried the layer2_board fix to both workers. Collision found,
    then dissolved by re-measuring rather than by negotiating. 3 sites → 2.
  - Collision check on the two: `clv-without-settlement` claims no files;
    `ask-sport-coverage` lists `intelligence_state.py` read-only;
    `soccer-model-coverage` lists both as "NOT this lane's files". CLEAR.
- Hypothesis: n/a — the producer is established by content, not guessed.
- Falsification test: if refresh-worker deploys with 0 clamp sites and a
  subsequent trigger still reads `PRE_FIX_MISPRICE`, the producer is NOT the
  intelligence-state loop and this attribution is wrong.
- Verification: `watch_clamp_trigger.py --once` → `POST_FIX_OK`, plus 0 clamp
  sites by content at the new live refresh-worker SHA.
- **Blocked by: the refresh-worker deploy claim**, held by `red-intelligence-tests`
  (target `037eb356`, since 23:35:01Z), which still carries both sites.
  `send_message` is unavailable from this scheduled-task session, so the claim
  was NOT taken and no coordination message could be sent. Waiting for release.

- **RESULT 2026-08-16 00:23:04Z — refresh-worker shipped `57a437d5`.** 0
  occurrences of `max(0.02, min(0.98` across all three files at the live SHA.
  Cut on live `2c14d9ae`, not main. Gated on `safety_rc == 0 AND zero [JOB]
  processes`, re-verified in the same shell command as the POST.
- **VERIFICATION DID NOT HAPPEN AND IS NOT CLAIMED.** 00:24:04Z read: `rows=12`,
  p=[0.338468, 0.603175], `out_of_clamp=0` → `no_trigger`. The slate collapsed
  from 97 rows as games finished. Same reading a quiet slate gives with the bug
  fully present. The 2-hourly `clamp-fix-verification-watch` task carries this.
- **`live-odds-worker` DEFERRED, not forgotten.** It carries the clamp but does
  not run the intelligence-state loop, so it is not the producer of the measured
  misprice. It is also effectively never idle — 57 samples over 35 min, zero
  job-free moments, running a per-league soccer artifact sweep. `079cc42b` is
  cut, tested and pushed; re-cut on the live SHA before shipping.
- **CORRECTION LOGGED: I twice called live-odds-worker "already fixed" off a
  PENDING claim target.** `49797f4b` was clean and never landed as-is; `c422f79a`
  then `c4116ab6` landed instead, both still clamping. **A claim's target is an
  intention, not a deployment.** Verify by content at the live SHA, every time.
- **TWO SAFETY-TOOL DEFECTS, both in `learnings.md` 2026-08-16:**
  `check_deploy_safety.py` reports CLEAR while jobs run on the service (measured
  on BOTH workers), and has no `--service` flag so it also blocks on the wrong
  service's work. And a wait loop of mine read a stderr HTTP 502 as CLEAR by
  testing for the absence of a failure string.
- **2026-08-16 03:1xZ — THE INSTRUMENT WAS BLIND IN THE WINDOW IT WATCHES, and
  every `no_trigger` since it was built is weaker evidence than it looked.**
  `watch_clamp_trigger.py` gated the confirming read on
  `/api/board/layer2-shortlist`, then judged `/api/intelligence/query`. Two
  different populations. Measured same-instant at 03:14:08Z: **shortlist 0 rows,
  served payload 18 priced rows** — 8,345 opportunities considered and all 8,345
  filtered out (horizon 2,488 + stale_kickoff 2,666 + quote_age 1,256 +
  excluded_market 689 + uninformative 1,246, summing exactly).
  The shortlist drops `stale_kickoff_seconds = 7200` and
  `max_quote_age_seconds = 50400` — **exactly the in-play late-game population
  both real triggers came from** (20:45Z, and 23:10/23:15Z at p=0.009911/0.990089).
  So the gate could read 0 while a misprice was live on a row it had filtered out.
  Found because the user disbelieved a `rows=0` reading, not by the instrument.
- **FIXED, not just recorded.** The trigger now derives from the served payload
  itself — the same surface the verdict judges. The shortlist is still read, as
  recorded context that can no longer suppress a check; both counts print.
  Self-test 11/11. Live at 03:24:19Z: `served_rows=30 (shortlist=12)`, so the
  old gate would still have judged on under half the population.
  - A defect found while writing it: emitting UNPRICED probabilities (needed, or
    `POST_FIX_OK_COLUMN_ABSENT` is unreachable and the fix working becomes
    invisible) double-counted every quoted row — once priced at the parent, once
    unpriced at the `quote` node. Harmless while only pairs were emitted; a
    phantom unpriced twin on every correctly-priced row the moment they were not.
    Caught by the new self-test, not in review.
- **STILL NO VERDICT ON THE FIX.** 03:24:19Z read the corrected population:
  30 rows, p=[0.057749, 0.871508], nothing outside [0.02, 0.98] → `no_trigger`.
  Genuinely quiet, now measured on the right surface. `#439` item 1 stays OPEN.
- **THE SHORTLIST/SERVED MISMATCH IS NOT A DEFECT — AND THAT IS WORSE FOR THE
  OLD GATE THAN "NARROWER" WAS.** Measured 03:3xZ, same instant. They are two
  different pipelines, not two views of one:
  - **Different date window.** shortlist `date: 2026-08-15`, `horizon_days: 1`
    (single date, `central_today_iso()`); served `dates_covered:
    ['2026-08-15','2026-08-16','2026-08-17']`. Late at night the shortlist's
    one-day horizon empties by construction while tomorrow's board is live —
    which is exactly the 0-vs-18 reading, and it will recur every night.
  - **Different pool.** served `source: combined_board_window` (the legacy
    `ranked_all` pool). The shortlist is `layer2_shortlist_artifact`.
  - **Different gates.** horizon / quote_age / stale_kickoff / excluded_market /
    uninformative are applied at BUILD time on refresh-worker for the shortlist
    only; `combined_board_window` does not carry them.
  This is known in-progress L2-A migration, stated in the route's own docstring
  (`intelligence.py:2698`): the board still renders `ranked_all`, the canonical
  board state the shortlist lands in "is never written (both migration flags
  default False and are off)", and pointing the board at L2-A rows "is the goal".
  **So the old gate was not a narrow view of the product — it was an artifact
  nothing user-facing serves.** The clamp misprices were always measured on the
  served path (`layer2_board.py:1345`: 1346 `fair_price` values, 24 on ±4900),
  which is the population the instrument now reads. Consistent, and the reason
  the gate had to go rather than be widened.
  - Sports move within minutes: 03:24Z served WNBA only; 03:3xZ served
    mlb 168 + wnba 216 priced occurrences. Do not treat one read's sport mix
    as the slate's shape.

#### smaps-anon-breakdown — CLOSED 2026-08-15 23:5xZ
**HYPOTHESIS CONFIRMED.** pid 39 anon is **91% mmap** (1,007.2 of 1,106.9MB)
against only **95.9MB of brk `[heap]`**. Falsification was "if `[heap]` dominates,
`mallinfo2`'s `arena` is the follow-up rather than `hblkhd`" — it does not.

**AND THE LANE'S PREMISE WAS RETRACTED BY ITS OWN INSTRUMENT.** The "673MB
outside pymalloc" this lane was opened to chase was cgroup `anon` (1,607MB,
CONTAINER) minus pymalloc arenas (934MB, pid 39 ONLY). Different scopes. The
smaps reader's reconciliation check refused its first production read
(`reconciles: false`, 27.0%) and that refusal was the finding. Per-process the
residue is **~173MB**; ~410MB was always just the 8-10 child processes.

**CONSEQUENCE: `mallinfo2` IS NOT THE NEXT STEP.** I recommended it two hours
ago. The question it was for has largely dissolved, and with pymalloc holding
~934MB of arenas the mmap total is very nearly pymalloc itself — a duller answer
than a mystery, and the right one.

**SHIPPED:** `b0ab37a1` (reader) live 22:41:04Z, minimal — live sha + 1 commit,
not converged main, which would have moved production 330 commits for an
instrument.
**NOT SHIPPED:** `c7747a29` (reconcile against the process, not the container).
Three sessions held the deploy claim in 70 min and the live sha moved twice under
a rebase, so it is filed as a request rather than raced for —
`.syndicate/deploy/requests/2026-08-15T2350Z-smaps-reconciliation.md`.
Until it lands the reader reports `reconciles: false` on every read. Cosmetic;
the breakdown itself is correct.
- [(superseded lane detail](lanes_closed.md) — (superseded lane detail — the original body this lane was opened with)
- [quote-join-enrich-cost (detail below, kept for the file/line map)](lanes_closed.md) — quote-join-enrich-cost (detail below, kept for the file/line map) — session: memory-guard
- [memory-guard-reclaimable (detail below, kept for the file/line map)](lanes_closed.md) — memory-guard-reclaimable (detail below, kept for the file/line map) — session: memory-guard
- [render-yaml-web-block-hygiene](lanes_closed.md) — render-yaml-web-block-hygiene — DONE 2026-08-13 — **NO LANE WAS EVER OPENED**
- [(superseded lane detail, kept for the file/line map)](lanes_closed.md) — (superseded lane detail, kept for the file/line map)
- [hooks-enforcement-wiring](lanes_closed.md) — hooks-enforcement-wiring — DONE 2026-08-13 — **NO LANE WAS EVER OPENED**
- [red-intelligence-tests](lanes_closed.md) — red-intelligence-tests — CLOSED-VERIFIED 2026-08-15 — all three reds fixed, 218/0, shipped `1322d0a8`/`d348e040`/`4ae71c4a`, pushed `89c3d94
- [mlb-live-pitcher-projection](lanes_closed.md) — mlb-live-pitcher-projection — CLOSED-VERIFIED 2026-08-16 — (a)/(b)/(c) all measured on 423 rows, 0 violations; live coverage 11.6% -> 50.3%;
- [board-publish-stall](lanes_closed.md) — board-publish-stall — CLOSED-FALSIFIED 2026-08-16 — no stall, no publish failure; the REAL result is that my deployed fix is INERT and resta
- [line-decimal-renderer](lanes_closed.md) — line-decimal-renderer — CLOSED-VERIFIED 2026-08-16 — shipped `f3b9b293`; 5 live rows change, 77 untouched; WEB DEPLOY OWED — opened 2026-08-

#### smaps-anon-breakdown — DEPLOY LANDED 2026-08-16 00:57:32Z (`ada731f5`)
The reconciliation fix is live and the guard is meaningful again. First reading
01:07:38Z:

    reconciles               true      (was false, 27.0% off)
    reconciles_within_pct    0.0
    total_anon_mb          1,672.4     smaps, per-process
    process_rss_anon_mb    1,672.6     RssAnon, per-process
    other_processes_anon_mb    0.4     children, now a LABELLED figure
    cgroup_anon (container) 1,673.0

Two independent kernel accountings of one process agreeing to 0.0%.

**BREAKDOWN NOW TRUSTWORTHY — the lane hypothesis holds on a clean reading:**
`anon_mmap` **1,540.3MB (92%)** against `heap` 128.3MB, `file_backed` 3.6,
`stack` 0.1; mmap split >64MB 741.3 | 8-64MB 639.1 | 1-8MB 159.3 over 426 regions.

**NOTE `other_processes_anon_mb` = 0.4 HERE, not the ~504MB seen at 22:49.** The
children were simply not running at this instant. That is exactly why the old
container-vs-process comparison was unusable: the gap is not a constant to
subtract, it moves with whatever the worker has spawned.

COST: five rebases across five live SHAs (`6f512ffa` -> `129395cc` -> `32186e28`
-> `2c14d9ae` -> `57a437d5`) and four claim holders. On a worker with five
sessions deploying, a two-file change should ride along, not chase.

#### live-game-line-projection — 2026-08-16 ~01:1xZ — THE PREMISE IS TRUE: 25 LIVE GAME-LINE EDGES PUBLISHED
- **Tier 5's goal is met in production.** `index_size 8 / considered 32 /
  projected 32 / edged 25 / prob_interval_swamps_edge 7`, on an artifact
  provably generated after the deploy. Baseline `index 3 / projected 12 /
  sim_count_unusable 12 / edged 0`.
- **Live:** live-odds-worker `c4116ab6` (simsRun stamp), refresh-worker
  `1f36d718` (the join). Web needs neither.
- **THE THREE DROPS, all shipped and measured:** D1 merge condition
  (`0e0b0aa1`), D2 carry-forward (`4bd7dbb3`), D3 join+wiring (`758a89fa`) plus
  the `simsRun` stamp (`49797f4b`) that made the precision gate reachable.
- **NOT ESTABLISHED — the 25 edges are UNVALIDATED.** Clearing 2 sigma at 120
  sims means the edge beats the ESTIMATOR'S noise, not that the model is right.
  No CLV, no settlement, no backtest. **Next work is evaluation, not more
  plumbing** — game lines carry 100% Pinnacle coverage, the strongest position
  on the platform.
- **OPEN:** why `index_size` was 3 earlier and 8 now is unexplained; Drop 2's
  carry-forward has still never been observed firing; the tally is MLB-only.
- **I no longer hold the live-odds-worker claim** — `clamp-fix-to-workers` took
  it ~00:34 and my last two fires went over it. Not force-released; theirs.

- **CHECKPOINT 2026-08-16 01:4xZ — state of the lane for whoever picks it up.**
  - All deploy claims RELEASED. Nothing held by this session.
  - Committed: `86ee112f` (falsification), `0f70969b` (lane), `25e34c63`
    (deploy record + 2 learnings), `1b76c232` (defer + `#439`), `1bd520c2`
    (state.md + the claim-target learning).
  - **NEXT ACTION: run `py -3 scripts/watch_clamp_trigger.py --once` when
    games are IN PLAY.** Both real triggers (23:10Z, 23:15Z) came from live
    in-play markets; the two `no_trigger` reads were a pregame board with
    extremes 0.0687/0.8904. A one-off task fires 2026-08-15 21:31 CDT and the
    recurring `clamp-fix-verification-watch` runs every 2h.
  - **`POST_FIX_OK` closes `#439` item 1.** `PRE_FIX_MISPRICE` now that
    refresh-worker is clean would falsify the intelligence-state attribution —
    that is this lane's stated falsification test, and it is still live.
  - Session log: `.syndicate/log/2026-08-15.md`, final section.

### odds-cadence-off-the-mlb-peak — OPEN — **1a/1b VERIFIED IN PRODUCTION 2026-08-16 05:51:48Z (`dd53d47c`, live-odds-worker): gate runs, soccer exclusion HOLDS at interval_s=28800 baseline. EFFECT still unmeasured; lane goal DEFERRED to 1c (blocked).** — opened 2026-08-16 — session: sim-engine-track
**Scoped only. No code, no deploy. Handing this over rather than starting it at
02:00 local on a fixed crash.**

- **Goal:** stop the soccer/odds refresh branch running concurrently with MLB's
  memory peak. Target: remove ~202.6MB from the worst combined moment, against a
  margin measured at **124MB** (worst combined 3,972.0MB = 97.0% of 4,096MB).
- **THE OWNER'S DOMAIN POINT IS THE PREMISE, and it is confirmed by the data:**
  soccer and the US sports run on opposite schedules, so soccer has no fixture
  reason to be refreshing during MLB's evening peak. Measured 18:11Z-01:5xZ,
  samples with BOTH branches live, against pid 39's peak that hour:

        hr   soccer   mlb   BOTH   pid39 peak
        18      113   383    101       3,230
        19      355   689    317       2,369
        20      241   501    223       3,300
        21      206   215    101       3,328
        22       91   353     82       3,302
        00      206    84     33       3,628

  **Soccer runs in EVERY hour MLB peaks.** The collision is cadence, not fixtures.
- **The concurrency is real** (unlike the `daily_update` chain, which is nested —
  see the correction above). The odds branch hangs off its own child of pid 39:
  `run_refresh_odds_job` -> `refresh_odds_sources` -> `build_soccer_artifacts`
  = 20.4 + 95.5 + 86.7 = **202.6MB** alongside the MLB chain.

**DO NOT START FROM SCRATCH — TWO PIECES ALREADY EXIST:**
1. **`9ec20a06` is written, tested and HELD** — "odds: the pregame relaunch
   cooldown is per-sport, not one clock for all eight"
   (`live_refresh_loop.py` +115, `tests/test_pregame_cooldown_per_sport.py`
   +132). NOT on `origin/main`. It was held because it changes odds cadence and
   would confound `soccer-odds-coverage`'s per-league measurement — that is the
   SAME mechanism this lane needs, so check whether it already does the job
   before writing anything.
2. The `soccer-odds-coverage` lane owns per-league cadence. **Coordinate; do not
   take its files.**

- **Hypothesis:** a per-sport cadence that ties soccer's refresh to its own
  fixture window removes most of the 202.6MB overlap without reducing soccer's
  data quality, because the refreshes during MLB's peak are polling leagues with
  no imminent kickoff.
- **Falsification test:** if soccer's refreshes during 18-22Z are in fact serving
  imminent kickoffs (check `commence_time` on what those runs write), then the
  overlap is REQUIRED and the lever is memory, not scheduling.
- **Verification:** re-run the hour table above; `BOTH` should fall in MLB's peak
  hours, and worst-combined should drop from 3,972MB. Must be a WORST-COMBINED
  measurement across all processes — a per-process figure is what made the margin
  look like 578MB when it was 124MB.
- **Cost note:** OddsAPI spend. Changing cadence changes call volume against a 5M
  cap; `9ec20a06` was held partly for that call.

#### PHASE 1 OPENED 2026-08-15 — scope, files, and what is deliberately NOT in it
- **Goal (single testable outcome):** a sport's pregame sweep interval becomes a
  function of time-to-next-fixture instead of a constant, so leagues with no
  imminent kickoff stop sweeping during MLB's evening peak.
- **Files (exclusive to this lane):** `syndicate/features/shared/live_refresh_loop.py`,
  `tests/test_pregame_cadence_fixture_aware.py` (new). Collision check RUN
  2026-08-15 against all OPEN lanes: both CLEAR.
- **DELIBERATELY OUT OF SCOPE — a collision I am not going to work around.**
  Plan step 1c (per-league soccer scoping) needs `scripts/build_soccer_artifacts.py`
  and `scripts/run_live_odds_refresh_worker.py`, and **both are claimed by OPEN lane
  `soccer-model-coverage`.** Phase 1 ships 1a (commence-time providers) and 1b
  (tiered interval) only. 1c requires coordinating with that lane first.
- **Hypothesis:** most soccer refreshes during 18-22Z serve fixtures days away, so
  a time-to-kickoff gate removes the overlap at no freshness cost.
- **ALREADY FALSIFICATION-TESTED, TWICE, AND IT SURVIVED BOTH:**
  1. This lane's own cmdline test: 43 of 71 invocations (61%) during 18-22Z were
     for kickoffs 2+ days out; 19Z was 100% future-dated.
  2. `#440` Phase 0/H1, independent source (fixtures, not processes):
     **9 European leagues, n=200, 0.0% of kickoffs in the 18:00-01:00 CT band, and
     zero at ANY hour after 14:00 CT.** MLS is the exception at 94.6%, n=111.
- **The rule that falls out, and it is fixture-relative ON PURPOSE:** H1 also
  CORRECTED the believed band table (European soccer is 05:00-14:00 CT, not
  01:00-09:00, and US fixtures start at 11:00, so an 11:00-14:00 contested band
  exists). A clock-based "no soccer in the evening" rule would have been built on
  wrong hours and would break MLS. Gate on time-to-next-kickoff, never on the clock.
- **Verification, and the baseline is NOT the one in this lane's scope block:**
  re-run the hour table from `reports/branch_overlap/baseline.jsonl`, which the
  scheduled task `branch-overlap-baseline-watch` is now accruing. **The 2026-08-16
  figure in this lane (3,972 MB / 97.0% / 124 MB margin) IS ALREADY STALE — the
  first watcher sample read 4096.0 MB = 100.0% of cap in three separate hours.**
  Judge Phase 1 against the accrued distribution, not against that number.
- **Cost gate before shipping:** cadence changes OddsAPI call volume against a 5M
  cap. The tiering should REDUCE calls; measure, do not assume.
- **Do not shelve `9ec20a06`** (per-sport pregame cooldown). It is a freshness fix
  and pushes overlap up; independent clocks PLUS fixture-awareness serves both.
- Blocked by: none. 1c blocked on `soccer-model-coverage`.

#### odds-cadence-off-the-mlb-peak — CHECKED 2026-08-16 02:0xZ: `9ec20a06` does NOT do it
Answering the scope's own question so nobody re-reads that branch.

**It pushes the OPPOSITE way for memory.** Its purpose is FRESHNESS:
`_pregame_relaunch_blocked` read one marker keyed by date, so any sport's launch
started the 1800s cooldown for all eight; MLB rode every 2nd-4th launch and its
quote capture ran every **121.6 min**, which is why the board served prices up to
two hours old and carried candidates that were no longer bettable.

The fix decouples that — each sport cools against its OWN last launch. Checked
the diff explicitly: **no concurrency limit, no memory gate, no serialisation.**
Its direct effect is MORE independent launches, i.e. soccer MORE likely to run
during MLB's peak, not less. The author mitigated exactly one tick of that risk
(a sport with no entry inherits the legacy epoch "so the first tick after this
deploys does not stampede every sport at once") — after that first tick all eight
are free.

**SO THE TWO GOALS ARE IN GENUINE TENSION, and that is the finding:**
- FRESHNESS wants independent clocks -> more overlap.
- MEMORY wants fewer concurrent branches at MLB's peak -> less overlap.

**Do NOT shelve `9ec20a06` for this lane.** Two-hour-stale MLB prices are a
product defect that directly produces unbettable candidates; that outranks 202MB
on a worker that is no longer crashing.

**THE RESOLUTION IS THE OWNER'S DOMAIN POINT:** independent clocks PLUS
fixture-awareness serves both. Soccer keeps its own cadence, but that cadence
follows soccer's kickoffs — which are opposite the US evening. MLB gets its 30-min
freshness; soccer stops polling leagues with no imminent kickoff during MLB's peak.

**NEXT MEASUREMENT IS THE FALSIFICATION TEST ALREADY IN THIS LANE:** read
`commence_time` on what the 18-22Z soccer runs write. Imminent kickoffs -> the
overlap is required and the lever is memory, not scheduling.

#### odds-cadence-off-the-mlb-peak — FALSIFICATION TEST RUN 2026-08-16 02:1xZ: IT DOES NOT FIRE
The test was: "if the 18-22Z soccer refreshes are serving IMMINENT kickoffs, the
overlap is REQUIRED and the lever is memory, not scheduling." They are not.

111 distinct soccer invocations parsed from `ALL_PROCESS_MEMORY` cmdlines
(`--soccer-leagues` + `--soccer-date`), 18:00Z onward. Kickoff DATE being fetched,
by hour:

    18Z   08-15 x4, 08-16 x4, 08-17 x2, 08-21 x6
    19Z   08-19 x2, 08-22 x10          <- 100% FUTURE, 4-7 days out
    20Z   08-15 x2, 08-16 x2, 08-17 x2, 08-20 x2, 08-22 x8
    21Z   08-15 x6, 08-16 x6, 08-17 x3
    22Z   08-15 x2, 08-16 x2, 08-17 x2, 08-21 x6

**43 of 71 invocations during 18-22Z (61%) are for kickoffs 2+ DAYS AWAY.** And
19Z — the hour with the MOST overlap (317 both-branch samples) — was ENTIRELY
future-dated. Nothing it fetched kicked off for four days.

**SO THE OWNER'S DOMAIN POINT IS CONFIRMED AND QUANTIFIED.** Those refreshes can
be deferred out of MLB's peak at no freshness cost, because their fixtures are
days away.

**ONE EXCEPTION THAT MUST NOT BE BROKEN: MLS.** It is the single most-refreshed
league (20 of 111) and its kickoffs genuinely ARE in the US evening. The European
leagues — la_liga 17, championship 16, primeira_liga 14, belgian_pro_league 12,
eredivisie 12, epl 8, ligue_1 8, serie_a 4 (91 of 111) — kick off in the European
day. A blanket "no soccer during the MLB peak" rule would break MLS; the rule has
to be fixture-relative, not league-blind or clock-blind.

**IMPLEMENTATION SHAPE THIS IMPLIES:** gate a league's pregame refresh on
time-to-kickoff rather than on a global clock. Leagues whose next fixture is >N
hours out get a slow cadence; MLS in its own evening stays fast. That serves
`9ec20a06`'s freshness goal AND this lane's memory goal, which is why the two are
only in tension while the cadence is fixture-blind.

#### HANDOFF to `clv-without-settlement` — live game-line edges, and the reason there is nothing to score yet
From `live-game-line-projection`, 2026-08-16 ~02:1xZ. **Read the structural
point before the data — it is the actual deliverable.**

**THE ROWS ARE TRANSIENT AND NOTHING PERSISTS THEM.** `live_gamelines` is
recomputed from scratch on every board build, for whatever games are live at
that instant. Measured tonight, same slate, three builds:

    01:11Z  edged 25   (pre-fix, inflated by segment + boundary defects)
    01:57Z  edged  4   (post-fix)
    02:06Z  edged  1   (slate winding down)

**A CLV number needs (edge at time T) paired with (price at settlement), and the
first half is never written down.** By the time a game settles, the row that
carried its edge has been overwritten several times. **This is the same gap this
lane already solved for recommendations with the opening-snapshot recorder
(`2b14fbeb`, 584 bytes/record) — game-line edges need the equivalent, and it
does not exist.** That recorder is the prerequisite; scoring is downstream of it.

**THE ONE ROW LIVE AT HANDOFF** (artifact `2026-08-16T02:06:59Z`) — offered as a
shape to design against, **not** as a sample to draw a conclusion from, n=1:

    game_pk 824966  TEX @ ATH  state=live  segment=full  market=h2h
    model_home_win_prob 0.6   market_fair_prob 0.4069   edge_pp +19.31
    prob_std_err 0.04405 (Agresti-Coull, n=120)   sims_run 120
    event_id 1145a9db8d138b13599e168a340ad3c7   home Athletics / away Texas Rangers
    sharp books: pinnacle, betfair_ex_eu, matchbook, novig, prophetx   pinnacle=True

**WHAT THESE ROWS DO AND DO NOT WARRANT.** Surviving means: a full-game market,
and an edge exceeding 2 Agresti-Coull standard errors of a 120-sim estimate.
**It means the edge beats the ESTIMATOR'S OWN NOISE. It says nothing about
whether the model is right.** No settlement, no backtest, no CLV.

**TWO CORRECTIONS TO CARRY, both from my own retractions tonight:**
- **`state.md`'s "100% of MLB game lines carry a sharp quote" is confirmed for
  the sharp SET (30/30 in production) but PINNACLE SPECIFICALLY IS 15/30.** A
  "CLV against the Pinnacle close" covers about half the population. Confirmed
  against production, not the mirror.
- **"Closing price" is ill-defined for a LIVE market** — it runs continuously to
  settlement. Decide explicitly whether the close is the last observed price
  before settlement, and note `closing-stamp-is-detection-time` records
  `closing_price` as **always the home price (18/18)**, which would mis-pair
  every away-side row.

**I deliberately did NOT build a parallel CLV path.** `clv_join.py` is yours and
the recorder decision is yours. Producing my own number would have duplicated
the machinery and inherited the side defect.

#### HANDOFF to `memory-watchdog-435` — a 2,092 MB in-process excursion, attribution already done
From `live-game-line-projection`, 2026-08-16 ~02:3xZ. **First refresh-worker OOM
of the day** (user's report: none until this one).

**THE KILL.** `server_failed reason={'evicted': False, 'oomKilled':
{'memoryLimit': '4Gi'}}` at **02:11:34Z** — events API, not logs.

**THE ALLOCATOR IS pid 39, THE MAIN WORKER. Every child is a bystander.**
`ALL_PROCESS_MEMORY`, two samples 34 s apart:

    02:10:49  container 2458.8 MB (60%)   pid 39 rss 1191.1 MB
    02:11:23  container 4094.6 MB (100%)  pid 39 rss 3283.4 MB
    02:11:34  oomKilled

    pid 39 (run_refresh_worker.py)   1191 -> 3283 MB   = +2,092 MB in 34 s
    pid 353 (daily_update.py)        207.7 -> 207.7    FLAT
    pid 394                           95.1 -> 143.7    +48
    pid 383                           79.1 ->  79.4    FLAT
    multiprocessing pool workers     ~54 MB each       FLAT

**THIS KILLS THE OBVIOUS HYPOTHESIS.** The running job was
`daily_update.py --sims 1000 --workers 2`, so "the sim's worker pool multiplies
memory" is the natural guess. **It is wrong** — every pool worker sits at ~54 MB
and the parent is flat to the decimal. It is ONE in-process allocation on the
main thread.

**`post_mlb_sim_tick` IS A BYSTANDER, as `state.md` already says.** Both
`CONTAINER_MEMORY` samples carry that stage and the whole excursion happens
between them. The label names the victim, not the allocator.

**WHY THIS ONE IS WORTH THE WATCHDOG.** `#327`'s open problem is "something
allocates 493-878 MB in-process and nothing knows what". **This is 2,092 MB,
roughly 3x the largest previously recorded** — which is why it crossed 4 GiB
instead of being absorbed. If the ~2 s timer sampler is deployed it should have
caught the interior of this window; if it is not, this is the strongest case yet
for shipping it.

**CONFOUND, STATED.** refresh-worker took **five deploys in the preceding hour**
(01:13, 01:24, 01:31, 01:56 mine, and 02:19 mine AFTER the kill), and `state.md`
records that every deploy resets the memory baseline. **"No OOM all day" partly
describes a worker that had not been restarted repeatedly until tonight — do not
treat it as a controlled baseline.**

**MY OWN CHANGES, assessed rather than assumed:**
- **The CLV ledger (`f8ca54e1`) is EXONERATED for this kill — it deployed
  02:19:10, EIGHT MINUTES AFTER it.** It was not running.
- The segment/boundary fix (`d1e3f908`, live 01:56:44) WAS running. It makes
  `attach_live_gamelines` do strictly LESS work (an early `continue`) and adds
  scalar arithmetic; the join has been live since 23:01 without OOMs. **On the
  stack, but not memory-shaped. Not cleared — just not indicated.**
- **FORWARD RISK THAT IS MINE:** the ledger's `read_last_by_key` parses the whole
  JSONL into a dict **on every board build**. Empty today, grows with the slate,
  and it now runs on this worker. **If a second OOM appears, suspect it first —
  `MLB_LIVE_GAMELINE_LEDGER_ENABLED=0` disables it with no deploy.**


- `win-prob-null-readable` — CLOSED-VERIFIED 2026-08-16 *(full entry in `lanes_closed.md`)*
  — **and the question it existed to enable is now ANSWERED, 16:14:55Z:** the
  `or 0.5` removal is exercised in production (`rows=192, null=6, 3.12%`;
  branch fired twice, 5.36% and 9.38%) and exercised on CURRENT code
  (`dd53d47c`, 48 rows). Read it with `scripts/read_win_prob_null.py`, never
  from the Render logs and never from the route's `latest`-only headline.
- `slate-size-headroom` — CLOSED 2026-08-16 *(full entry in `lanes_closed.md`)*
- `worker-child-processes` — CLOSED 2026-08-16 *(full entry in `lanes_closed.md`)*

#### `clv-without-settlement` — SETTLED READING 2026-08-15 MLB, recorded by `live-game-line-projection`
Read from `/api/ops/clv/report?sport=mlb&date=2026-08-15` at ~2026-08-16 02:5xZ,
after the scheduled task `clv-settled-read-2026-08-15` fired 01:55:33Z. **Not my
lane — recorded because I had the reading and the context; interpret it yourself.**

**THE NUMBER (same-book, close observed BEFORE first pitch):**

    avg_clv_pct      -0.4049 %
    beat_close_rate   21.64 %   (29 of 134)
    same_book_n      134   |  same_book_all_n 159  |  book_biased_n 107
    openings         987   ->  resolved 266

**IT GOT WORSE ON SETTLEMENT.** This lane's own preliminary figure was
**-0.07 % at a 27.1 % beat rate**, taken pre-first-pitch. Settled it is
**-0.4049 % at 21.64 %**. The direction of that move is the finding.

**DO NOT QUOTE `book_agnostic_close`.** It reads **+2.6793 % at an 83.16 % beat
rate on n=95** and is an ARTIFACT, not a result — the report's own `bias_note`
says pairing a best-of-N opening against another book's close is **biased
upward**. That is precisely what the same-book restriction exists to remove, and
it is the most quotable wrong number in the payload.

**`by_close_timing` — and this is the part that touches Tier 5:**

    pregame   n=134   avg -0.4049 %   beat 21.64 %
    in_play   n= 25   avg -0.3498 %   beat 36.00 %

**IN-PLAY IS A SEPARATE, EXCLUDED BUCKET (`in_play_excluded_n: 25`) — AND
IN-PLAY IS EXACTLY WHAT `live-game-line-projection` PRODUCES.** The live
game-line edges cannot be scored through this path as it stands; they would land
in the bucket this report sets aside. **This empirically confirms the caveat in
my handoff above** ("close is ill-defined for a live market"): it is not a
theoretical objection, the pipeline already treats those rows as un-scoreable.
Deciding what "close" means for a market that runs continuously to settlement is
a prerequisite for scoring the live game-line ledger, and it is this lane's call.

**LIMITS, stated so nobody over-reads a single evening:** one slate; `resolved`
is **266 of 987** openings, so roughly a quarter of published rows got a close at
all — the 134 that carry the headline are ~14 % of what was published. Whether
the unresolved 721 differ systematically from the resolved 266 is **unknown and
not tested**, and if they do the -0.4049 % is not representative.

> *(The blockquote and body below are this lane's HISTORY, kept for the
> reasoning trail. The status above supersedes them — 2026-08-16 reconcile.)*
> **STATUS LINE CORRECTED 2026-08-15 ~18:0xZ by the coordinating session.** It
> read "NOT DEPLOYED" and that is no longer true: `0e0b0aa1` rode the web train
> and is in the deployed tree (`dep-da0a5rlg1s2s73cm43kg`, live 17:40:30Z).
> **This does NOT discharge the lane's measurement obligation.** By this lane's
> own commit message the change publishes nothing on its own — the visible
> effect needs Drop 2 — so "deployed" here means *present*, not *proven*. No
> production predicate was declared for it and none was measured. Do not read
> the deploy as evidence the lens now serves a live win probability.
- Goal: MLB game lines carry a projection computed from the CURRENT game state
  rather than the pregame sim. **Testable outcome:** on a live MLB slate, a
  published artifact carries a live win probability per live game whose value
  MOVES between two consecutive builds while the pregame `predictions.full`
  for the same game does not — and `rows_live_edged` on the book-grid counters
  is > 0 for game-line markets.
- **THE PREMISE IS FALSE AND THAT IS THIS LANE'S CENTRAL FINDING.** "No live
  game-line projection exists" is a statement about PUBLICATION, not about
  computation. `estimate_live(LiveSituation(...))` runs in production today,
  120 sims per live game, on every live-lens tick, and returns `homeWinProb`,
  `awayWinProb`, projected `total` and `homeMargin` from the live inning /
  outs / bases / score / batter / pitcher state. Evidence in
  `.syndicate/spec_live_game_line_projection.md` §1.
- Files (exclusive to this lane):
  - `.syndicate/spec_live_game_line_projection.md` (new — the deliverable of
    this phase)
  - `syndicate/features/mlb/live_lens.py` — the merge site at 1090-1100 that
    discards the live-MC game lens for exactly the live games.
- Hypothesis (H1): the live MC's `gameLens` is dropped by
  `_enhance_card_row_with_live_projection`'s `should_use_projection_lens`
  because the card's own pregame-derived lens already satisfies
  `_lens_rows_have_projection_signal`, so the branch is False on precisely the
  live games it was written to serve.
- Hypothesis (H2): a second, independent drop — the report that is PUBLISHED
  is the slim HTTP-fetched shape from `scripts/refresh_mlb_oddsapi.py`, which
  carries no `gameLens` at all. Fixing H1 alone therefore changes nothing that
  crosses to web.
- Falsification test: for H1 — a live game whose card row carries NO gameLens
  still shows no `source: live_mc` row after the merge, which would mean the
  MC payload never reached the merge. For H2 — a published report that already
  carries `gameLens` rows, which would mean the slim path is not the binding
  drop.
- Verification: (1) the spec is reviewed and its scope agreed BEFORE any engine
  work — this phase produces no source edit; (2) any later code change is
  measured on the published artifact, never through web's `/mlb/api/live-lens`,
  which recomputes a cards fallback locally and is structurally blind to the MC
  (`cardsFallback: True`, `simContextAvailable: False` on 14/14 games, measured).
- Blocked by: none. **NO DEPLOY FROM THIS LANE.** refresh-worker is under
  `#435` and had a deploy in flight (`eea7554a`) at lane-open.

#### live-game-line-projection — ARCHIVE ADDENDUM 2026-08-16 ~03:0xZ (supersedes the "next session" line in the archive above)
Recorded after the archive block, and it **changes the next step**.

The settled MLB CLV read for 2026-08-15 (`ceecf863`) shows
**`in_play_excluded_n: 25` — in-play is a SEPARATE, EXCLUDED bucket**, and
in-play is exactly the population this lane produces. **So the live game-line
edges cannot be scored through the existing CLV path at all**, however many rows
the ledger accumulates.

**The blocker is therefore a DECISION, not more data:** what does "close" mean
for a market that runs continuously to settlement? That is
`clv-without-settlement`'s call, and it gates everything this lane ships.

**Revised order for whoever picks this up:**
1. **Settle the in-play close definition** with `clv-without-settlement`. Until
   then the ledger accrues rows nobody can score.
2. Then read the **8/16 20:30 CDT** scheduled check — dedup working, rows
   accumulating. That proves the RECORDER, which is still worth knowing.
3. Only then ask whether the edges are any good.

**Unchanged:** no claims held; live-odds-worker `c4116ab6`, refresh-worker
`f8ca54e1`, both content-verified. The plumbing is done.

#### CALL-VOLUME CHECK RUN 2026-08-15 — budget clear, and it found a defect in 1a/1b
The gate this lane required before enabling anything. It cleared the cost question
and then failed the thing it was checking, which is the point of running it.

- **BUDGET IS NOT A CONSTRAINT.** `/api/ops/oddsapi/quota`: `projected_30d_credits`
  **3,134,318** against the 5M cap = **62.7%**, 4,353 credits/hr. By sport since
  2026-07-28: mlb 1,627,718 (**93.0%**), soccer 71,912 (**4.1%**), nfl 37,639,
  wnba 13,475. **Soccer cadence is not a cost lever.** (Headers claim ~13.3M
  remaining; `CLAUDE.md` records that as untrue — 5M used here.)
- **THE DEFECT — 1a/1b IS WRONG FOR SOCCER, THE ONE SPORT THIS LANE IS ABOUT.**
  Tiers modelled against the real 2026 fixture lists, 336 hours:

        mlb            12.00 -> 5.45 sweeps/day   -55%
        wnba           12.00 -> 5.83              -51%
        nfl_preseason  12.00 -> 3.56              -70%
        soccer          3.00 -> 5.08              +69%   WRONG DIRECTION

  `_next_fixture_epoch` resolves ONE clock per sport, but soccer's "sport" is ten
  leagues on ten calendars, so the gap is the MINIMUM across all of them and is
  almost never large: **the 24h tier is reached in 0.0% of hours.** The gate would
  have made soccer sweep MORE often — increasing the exact overlap this lane
  exists to remove. Per-league: 24h tier in **49.3%** of league-hours, volume flat
  (3.03/day) but redistributed OFF the peak.
- **I shipped 1a/1b naming soccer as the motivating case. The measurement says
  soccer is the one sport it hurts.** Recorded rather than quietly patched.
- **FIX (`8640f872`):** `_FIXTURE_CADENCE_EXCLUDED_SPORTS = {"soccer"}`, numbers in
  the code, 3 tests pinning it — including a control that fails if the gate is
  disabled outright rather than only for soccer, and a note that the MLS test must
  be REWRITTEN when 1c lands, not deleted. 52 tests green.
- **CONSEQUENCE FOR THIS LANE'S GOAL: 1c is a PREREQUISITE, not an optimisation.**
  Phase 1's headline benefit — soccer off the MLB peak — is DEFERRED until 1c,
  which is blocked on `soccer-model-coverage`. What ships today is a -51% to -70%
  cut in the pregame sweep ceiling for the single-league sports, which is real but
  is NOT what this lane set out to get. State it that way in any status.
- **WHAT THE MODEL IS NOT:** `sweeps/day` is a ceiling on the PREGAME cadence, not
  measured call volume — launches are further gated by the 1800s relaunch cooldown
  and the off-hours gates, and the 60s live tick is not governed by this cadence at
  all. **The credit delta stays UNMEASURED** until the flag is enabled on one
  service and the quota re-read.
- Gates remaining before enabling: the baseline distribution from
  `branch-overlap-baseline-watch` (accruing; one sample is not a distribution).

#### 1a/1b VERIFIED 2026-08-16 05:51:48Z — the gate runs and the exclusion holds
- Three consecutive lines carry the whole decision chain on live-odds-worker:
  `FIXTURE_CADENCE sport=soccer interval=baseline reason=excluded_pending_per_league_scoping`
  -> `PREGAME_CADENCE_DETAIL soccer:marker_age_s=4480/interval_s=28800`
  -> `PREGAME_CADENCE_SKIPPED sports=soccer`.
- **`interval_s=28800` is the load-bearing field**: soccer's 8h BASELINE, not a
  fixture tier. Had the exclusion failed, soccer would have swept MORE often
  (+69%, measured) — the opposite of this lane's goal.
- Predicted the first observable tick at ~05:51:37Z from a 900s idle interval
  against an 1800s cooldown; actual 05:51:48Z. **11 seconds.**
- **THREE WRONG TURNS FIRST, all invisible from `status=live`:** flag on the wrong
  service (refresh-worker never imports `_run_live_refresh_tick`); post-deploy
  silence that was log-ingestion lag, not a boot failure; and
  `_pregame_relaunch_blocked` sitting UPSTREAM of the cadence filter.
- **STILL UNMEASURED: the EFFECT.** One gate decision is not a cadence outcome.
  Needs the `branch-overlap-baseline-watch` distribution. And soccer is excluded
  by design, so **this lane's headline goal stays DEFERRED to 1c**, blocked on
  `soccer-model-coverage`.
- Full measurement in `deploys.md`; unrelated defect found while measuring
  Phase 2's premise is filed as `#441` (NFL week-1 projection unwritten 2.36 days,
  relaunching ~107x/day).

### refresh-worker-oom-recurrence — OPEN — **MECHANISM SETTLED, ALLOCATOR STILL UNNAMED. `#435` did NOT regress (scope error: book_quotes READ vs container anon). The failure is a ~2GB TRANSIENT in the PARENT process (pid 39, children <54MB), decided by evictable page cache (inactive_file 26.3/42.2 at kills vs 164-240 surviving), climbing 51s with NO stage marker. THREE fixes shipped and exercised in live `d72d670c` — odds-shard duplicate `51ae7218`, ledger streaming `21f8a165`, 3-ledger-loads-to-1 `aa190d58` — and NONE has been shown to move the transient. deepcopy EXONERATED by measurement (0.54MB peak). Daytime windows are worthless as evidence; the live-slate band 22:00Z-05:00Z is scheduled via `scripts/oom_band_report.py` + two one-time tasks. OPEN pending that result** — opened 2026-08-16 — session: refresh-worker-oom-recurrence
- **HANDED IN 2026-08-16 ~19:55Z by `branch-overlap-baseline-watch` (scheduled
  run). This lane's to interpret, not the reporter's — filed as observation,
  no diagnosis, no code or config touched.**
  - **Two NEW `oomKilled` on refresh-worker: `2026-08-16T19:17:25.767Z` and
    `19:30:07.124Z`** (14:17:25 / 14:30:07 local), `memoryLimit=4Gi`, 12.7 min
    apart. With the two already-known daytime kills (`16:34:32Z` / `17:19:42Z`
    = 11:34:32 / 12:19:42 local) that is **4 `oomKilled` in one afternoon**.
  - **Why it may bear on this lane's plan:** the heading above records
    "Daytime windows are worthless as evidence; the live-slate band
    22:00Z-05:00Z is scheduled". The 19:17Z/19:30Z pair falls OUTSIDE that
    band, so `oom_band_report.py` as scheduled will not see it. Whether that
    makes daytime evidentially interesting, or these are a different mode from
    the live-slate transient, is this lane's call — the reporter is not making
    it.
  - Source: `py -3 scripts/render_events.py --service refresh-worker
    --failures-only --since 2026-08-16T14:52:07Z`, which **COVERED
    15:39:59.060Z .. 19:48:33.617Z** (63 events, 1 page). The events read
    starts ~48 min AFTER the memory window opened — **nothing is claimed about
    kills in 14:52Z-15:40Z**, and coverage ends 19:48:33Z.
  - Memory context from the same run, cgroup `memory.current` — **INCLUDES page
    cache; this is NOT a leak claim and NOT an imminent-OOM claim**: covered
    14:52:07Z..19:51:47Z, 1967 samples, 0 malformed. `WORST container (any
    sample)` **4096.0 MB = 100.0% of cap**; `WORST while BOTH branches live`
    **4096.0 MB**; both-live share **326/1967 = 16.6%**. Local hour 14 — the
    hour holding both new kills — n=290, worst 4096.0, worst@BOTH 4096.0. At-cap
    has been the reading in every record since 2026-08-15 and is not itself news.
  - Raw record appended to `reports/branch_overlap/baseline.jsonl`
    (`run_mode=scheduled`).
  - Delivery note: no live session holds this lane — both
    `refresh-worker OOM: two kills in 25 min` sessions are archived and stopped
    (last activity 15:33:05Z). This ledger entry IS the handoff.

### layer1-board-coverage — CLOSED-VERIFIED 2026-08-17 — all four goals answered, and the last unmet criterion was EXECUTED (it returned a defect, which was then fixed and verified)
- **THE ONE OPEN CRITERION IS NOW MET.** This lane closed-refused twice for
  the same gap: the cross-sport LIVE A/B needed two sports live at once.
  **It was run 2026-08-16 22:2xZ** on a real live WNBA slate against a live
  MLB slate. Result: WNBA had **0 of 521 rows** carrying any live field —
  i.e. no live tier at all. That answer was the deliverable; it was then
  fixed (`wnba-live-tier`) and verified at **218 of 321 game rows
  live_aware**.
- G1 rates, G2 bucket classification, G3 (MLB live lens measured moving),
  G4 (missing term named at the producer, fixed in `e543e8dd`, 287/287
  attributed) all delivered and recorded in `deploys.md`.
- Scope added mid-lane and also delivered: the HR threshold ladder
  (`hr_2plus`/`hr_3plus`), the NFL window 5->7, and the soccer game-state
  defect that was serving edges on finished matches.
- Goal: for every in-season sport, a per-sport/per-market-family RATE of
  `projected / total` (alt and period families broken out), every unprojected
  prop classified as EITHER stale-fingerprint OR sim-does-not-emit-this-stat,
  and the `Edge` column's missing term named AT ITS PRODUCER.
- Files (claimed): `syndicate/features/shared/layer1_board.py`,
  `syndicate/templates/shared/layer1_board.html`,
  `syndicate/blueprints/layer1_page.py`,
  `syndicate/blueprints/intelligence.py` (the `/api/board/layer1` handler only).
  Edited in the end: `syndicate/features/shared/prop_projections.py` +
  `tests/test_prop_projections_edge_attribution.py` — checked against every OPEN
  lane's `- Files:` at edit time and claimed by none. Read-only throughout on
  `layer2_board.py`, `intelligence.html`, `bet_slip.js`, `board_cards.css`,
  `soccer_projections.py`, `pipeline/intelligence_state.py`, sim internals.
- **THIS ENTRY WAS WRITTEN TWICE.** The first append was silently overwritten in
  the worktree by a parallel session's read-modify-write of `lanes.md`, and my
  own commit then staged THEIR 44 lines under my message without either of us
  noticing. See the learnings entry of the same date. Re-appended, not rewritten.
- **RESULT** (full audit `.syndicate/audit_2026-08-16_layer1_board.md`;
  measurement + falsification test in `deploys.md`, 2026-08-16 16:19–16:40Z):
  - **Both briefed premises were wrong, and re-checking them first was the whole
    value of the first ten minutes.** Layer 1 is NOT dark (**5 of 5** consecutive
    builds non-zero). Alt lines are NOT unprojected on MLB (`totals_alt` 86/86,
    `spreads_alt` 76/77) — they are unprojected on **WNBA** (419/419 dark). The
    `Edge` column is not blank everywhere: MLB serves **1,462** edges, and most
    rows lacking one already state why on the row.
  - The prior baseline in `docs/ai_context/betting_contract_lifecycle.md` §3a
    (MLB 19.7% projected / **0** edges / game state 1,220 of 3,604) is **EXPIRED**
    — today 68.3% / 1,462 / 2,843 of 2,843. Quoting it would book another lane's
    fix as this lane's regression.
  - **G1** rates measured per sport × family. mlb 1,941/2,843 (68.3%), soccer
    1,704/6,453 (26.4%), wnba 305/872 (35.0%). The MLB gap is **LINE-shaped, not
    market-shaped**: `batter_home_runs` 0.5 → 82.8%, 1.5 → **0.4%**, 2.5 → **0%**.
  - **G2** every unprojected prop classified. mlb 504 no-such-rung / 337
    player-dark (63 players) / 42 residual; soccer 1,293 / 3,128 (836) / 268;
    wnba 39 / 41 / 0. Mapping named: the sim publishes a `<stat>_<N>plus` ladder
    and `hr_2plus`, `hr_3plus`, `hits_runs_rbis_1plus` are the missing rungs.
  - **G3** MLB live lens MEASURED working for props (27 of 201 `live_projected`
    moved, 3 `actual_so_far` advanced over 4 min, right direction) and NOT
    working for game lines (0 live projections on every `game|*` family).
  - **G4** missing term named at the producer: `prop_projections.py` set
    `edge_vs_market_pct = None` and no reason — key **ABSENT** on 284/284 —
    while its soccer sibling has always attributed the same refusal. Fixed in
    `e543e8dd`; replay over real served payloads gives **287/287 attributed, 0
    silent**. The refusal itself is correct (`#238`) and unchanged.
- **NOT DONE, owned elsewhere, routed by `send_message`:** missing sim rungs, the
  63 dark MLB players, WNBA needs a distribution → sim-engine session. The 1,416
  rows carrying BOTH EV terms → Layer 2 session and a **user decision**,
  deliberately not taken here because `modelled_fair` is a book-margin ESTIMATE,
  not a de-vig. The WNBA `wnba_game_cards` +31.7pp finding could NOT be delivered
  (that session is unattended) — it lives in audit §4b and `e543e8dd`'s message.
- Falsification test for the undeployed fix: re-sweep and count rows with a
  projection, no edge of either contract, and no reason. **Expected 0.** Do NOT
  verify by "the reason string appears" — it already appears on 287 rows in
  replay; the residual is the discriminator.
- Verification: met for G1/G2/G4 and for G3-props. **Unmet:** cross-sport live
  A/B (no second live sport in the window). Lane stays OPEN for that.
- Blocked by: none.

### grading-blocker-settled-zero — OPEN — opened 2026-08-16 — session: alt-line-shortlist-watch
- Goal: `settled > 0` on `/api/ops/evaluation-settlement/status`. **NOTE the reading this lane opened on was STALE — see the correction in the checkpoint below.**
- Why it matters: this is the S6 gate that holds `_SCORE_SIM_WEIGHT` at 0.0, which is why `sim_component` is 0.0 on every scored row. Raising the weight without it is forbidden by `opportunity_signals.py:340` (measured 286/300 negative-EV rows at 0.5).
- Files:
  - `syndicate/features/shared/graded_outcomes.py`
  - `syndicate/features/shared/evaluation_settlement.py`
  - `scripts/refresh_mlb_oddsapi.py` (read-only so far)
- Hypothesis: the blocker is on the GRADED side, not the matching side.
- Verification: per-date graded row counts off `/mlb/api/market-accuracy`, then a re-read of production `settled`.
- Blocked by: none. `EVALUATION_SETTLEMENT_ENABLE_REFRESH_WORKER_AUTORUN=false`, OFF BY USER DECISION (`todo.md:13464`).
- **LEDGER HAZARD, recorded because it bit this lane:** the lane header written at open time was **silently lost** — another session rewrote `lanes.md` between this session's two appends, dropping the header while keeping the later checkpoint, which then sat orphaned under `ui-probe-curvature-detection` (a CLOSED lane). Re-appended here whole. An append to this file is not safe against a concurrent full rewrite.

- **CHECKPOINT 2026-08-16 ~18:1xZ — DIAGNOSED, NOTHING CHANGED. One correction, one falsified hypothesis, one named mechanism.**
- **CORRECTION, and it invalidates the framing this lane opened with.** `settled 0 / graded_rows_available 1` is **NOT a current reading**. `/api/ops/evaluation-settlement/status` is read-only over a STORED status file, and its `epoch` decodes to **2026-08-06T11:03:17Z** — ten days stale, frozen since the autorun was disabled. It describes the world BEFORE the 2026-08-08 pregame-freeze repair. Nobody has measured `settled` since. I reported it as the live gate reading; it is not.
- **Grading is no longer ~zero.** Measured live today off `/mlb/api/market-accuracy`, `rows.all` per date:

      08-04  1     08-08  79    08-12  13
      08-05  1     08-09  79    08-13   7
      08-06  0     08-10  18    08-14   9
      08-07 37     08-11   7    08-15   7

  The 08-04..08-06 floor is the pre-repair era; 08-07 onward is non-zero. Against the historical baseline in `graded_outcomes.py` (06-04 all=971, 07-04 782, 07-08 626) it is still 10-100x down.
- **THE SHARP SYMPTOM: `ml` graded rows = EXACTLY 1 on every date measured (8 of 8)**, with 4-14 `Missing game-line match` warnings each. `season_betting_day_2026_08_15.json` carries `games` with **one** key (`824966`) against a ~15-game slate. Game-line grading is not thin, it is pinned at one.
- **HYPOTHESIS FALSIFIED — it is not a freeze/reader PATH mismatch.** I suspected the writer wrote to `daily/snapshots/<date>/` while `_odds_paths` reads `market/oddsapi/`. Wrong: `_freeze_oddsapi_pregame_markets` writes BOTH destinations (`refresh_mlb_oddsapi.py:677`, `:699`), and the reader's freeze preference is present (`build_season_betting_cards_manifest._odds_paths:765`). Both halves of the 08-08 repair are in the tree with tests (`tests/test_oddsapi_pregame_freeze.py`, `tests/test_season_betting_cards_odds_paths.py`).
- **AND THE INSTRUMENT THAT SUGGESTED IT IS BLIND.** `/api/ops/artifacts/export` returned `count: 0` for `**/market/oddsapi/*` — including the LIVE files that must exist. It also returns `count: 0` for `evaluation_ledger_chunks/*.jsonl` while `chunk_diagnostics` in the same payload proves a 367MB chunk is on disk. **That endpoint's root does not cover these trees; a 0 from it is not absence.** I nearly banked a wrong root cause on it.
- **MECHANISM (code-supported, not yet proven in production): the freeze is thin because the MLB odds refresh does not run PREGAME on most days.** Freeze contents measured: 08-11 **13 games**, 08-16 **14 games**, but 08-12 / 08-15 / 08-09 only **1-3 games**. `_merge_pregame_game_lines` (`refresh_mlb_oddsapi.py:610-631`) is merge-only and never shrinks — but it only ADDS an event that is still pregame (`already under way -> continue`). So a refresh pass that first runs after first pitch contributes nothing, forever. The seal is only as good as the earliest pass that touched it.
- **This overlaps `odds-cadence-off-the-mlb-peak`** (1a/1b verified, effect unmeasured). If that lane moved sampling off the MLB pregame window, it is the same fact seen from the other end. Coordinate before changing cadence.
- **NEXT TEST, cheap and decisive:** today's 08-16 freeze already holds 14 games. If tomorrow's `season_betting_day_2026_08_16.json` grades ~15 `ml` rows instead of 1, the mechanism is confirmed and the fix is scheduling, not logic. If it still grades 1 with a 14-game freeze present, the reader is not reaching the freeze in production and the next suspect is `_odds_data_roots()` ordering on the mounted disk.
- **NOT DONE / NOT CHANGED:** no source file touched, no deploy, no env change. `_SCORE_SIM_WEIGHT` untouched. The settlement autorun remains off by user decision.

### mlb-live-gameline-distributions — CLOSED-VERIFIED 2026-08-17 — live MLB totals and spreads carry a live projection AND a priced edge — opened 2026-08-16 — session: layer1-board-coverage
- **VERIFICATION RAN AND PASSED**, production, live slate 2026-08-16 22:23Z
  (6 live MLB games): `game|spreads` **65 rows / 36 live_aware / 28 edged**,
  `game|totals` **65 / 37 / 30**, `game|h2h` 24 / 6 / 3. Before this lane the
  same families read **0 live_aware and 0 edged on every live game**.
- Re-closing: an earlier close of this lane was clobbered back to OPEN by a
  parallel rewrite of `lanes.md`. The measurement above is unchanged.
- Goal: a LIVE MLB game carries a live projection and a priced edge on its
  TOTALS and SPREADS, not just its moneyline, sourced from the same 120-sim
  re-sim and gated on the same interval. **Testable outcome:** on the served
  `/api/board/layer1?sport=mlb&view=live`, `totals|full` and `spreads|full` go
  from **0 live_aware / 0 edge** to non-zero, and every released edge carries a
  `prob_std_err` that cleared `PRICEABLE_SIGMA`.
- Files (all checked unclaimed at open):
  - `vendor/mlb_bettingv2/sim_engine/live_mc.py` (add a margin histogram)
  - `vendor/mlb_bettingv2/tools/web/flask_frontend.py` (carry the histograms)
  - `syndicate/features/shared/live_gameline_join.py` (consume + price)
  - `tests/test_live_gameline_join.py`, `tests/test_mlb_live_game_line_lens.py`
- **NOT taken:** `syndicate/features/mlb/live_lens.py` — claimed by
  `refresh-worker-oom-recurrence` and `odds-cadence-off-the-mlb-peak`. Avoid; if
  the merge side turns out to need a change, stop and coordinate.
- **The finding, measured 2026-08-16 19:13Z on 8 live MLB games:**
  `h2h|full` 8 rows / 7 joined / 2 priceable / 2 edges — the moneyline works.
  Every other game family is **0 live_gameline, 0 live_aware, 0 edge** across
  **470+ rows**: `totals_alt|first5` 98, `spreads_alt|first5` 79, `totals|full`
  41, `spreads|full` 36, and the rest. They render a PREGAME projection on a
  live game.
- **Root cause, and it is a discard, not a gap.** `live_mc.LiveMcResult` already
  carries `total_runs_dist: Dict[int, int]` — a full histogram over the 120
  sims. `flask_frontend`'s live-MC return (`:16683`) keeps `batterStatDist` and
  `pitcherStatDist` — added, in that same dict, with the comment *"Carried so
  the live PROP rows can price off the same 120 sims that produced the numbers
  above, instead of falling back to the pregame distribution"* — and drops
  `total_runs_dist` on the floor. So the props got a real live probability and
  the game total, from the identical sims, kept only `avg_total_runs`.
  `live_gameline_join` then has nothing but a mean, which is exactly what
  `REASON_TOTALS_MEAN = "totals_mean_not_distribution"` reports.
- `sigma: 2.0` in the served payload is `PRICEABLE_SIGMA`, the threshold — NOT a
  distribution width. I misread it as interval data on the first pass; it is not.
- No margin histogram exists yet. The MC's loop already computes `home_final -
  away_final` per sim, so it is a two-line addition in the same loop, not a new
  model.
- Falsification test: if `totals|full` still reports 0 `live_aware` after the
  dists are published and consumed, the diagnosis is wrong and the lens is not
  the carrier. Check `projections`/`live_gameline` coverage counters first.
- Verification: (a) unit tests price a known histogram at a known line;
  (b) production `view=live` shows non-zero live_aware + edge on totals/spreads;
  (c) Layer 2 inherits it with no Layer 2 change, since it reads the same grid.
- Blocked by: none.

### wnba-live-tier — OPEN — **GAME LINES SHIPPED AND VERIFIED (218/321 rows live_aware). PROPS NOT WIRED — the source emits nothing. Tick-over-tick movement UNPROVEN.** — opened 2026-08-16 — session: layer1-board-coverage
- Goal: WNBA live games carry a live tier on the Layer 1 board, GAME LINES and
  PROPS. Baseline was **0 of 521 rows** across 2 live games.
- Files: `syndicate/features/shared/live_gameline_join.py`,
  `syndicate/features/shared/board_enrichment.py`,
  `tests/test_wnba_live_tier.py`,
  `tests/test_wnba_scoreboard_carry_forward.py`.
  - **NOT claimed by this lane any more:** `syndicate/features/wnba/cards.py` is
    now held by `game-shape-capture` under a claim override taken 2026-08-16
    ~20:1x CDT **on explicit user instruction**, for ONE function only
    (`build_live_pbp_stats_payload`, `:6390`), to fix `#455`. Logged rather than
    silent, so it can be judged:
    1. **The user directed it** — "take the override and fix it - i dont think
       its actually being worked on by any other lane." That is the authority
       here; the reasoning below is corroboration, not the basis.
    2. **Coordination was attempted three times and never reached a reader.**
       fork 2 (`local_c83b3d44`) archived before replying to two handoffs; a
       third was sent to fork 4 (`local_0cec671d`, running) and is unanswered.
    3. **Zero functional overlap with this lane's own work**, which is the live
       TIER on the Layer 1 board (`attach_live_gamelines_for_sport`,
       `LIVE_LENS_SOURCES_BY_SPORT`). `build_live_pbp_stats_payload` is the pbp
       stats endpoint and is untouched by it.
    4. **It plausibly FIXES this lane's own blocker** — its status reads "PROPS
       NOT WIRED — the source emits nothing", and `#455` is a stuck all-null
       skeleton, which is exactly what a prop consumer reads as nothing.
    **If this lane wants the file back, this note is the record.**
- **DONE — game lines.** `attach_live_gamelines_for_sport` was gated
  `if sport != "mlb"` on a docstring claim that WNBA "has no live tier at all",
  which had gone stale: the live-lens loop already ran for wnba on a 60s tick,
  writing the exact path the join reads. Shipped `fdc72dd0` (refresh-worker) via
  a per-sport `LIVE_LENS_SOURCES_BY_SPORT` (wnba stamps `live_projection`, not
  `live_mc`) plus a top-level team-name fallback (wnba has no `matchup`
  wrapper). **Verified twice on production live slates: 149 rows, then 218 of
  321.** No `simsRun` is published by wnba, so the edge is withheld by
  `REASON_UNUSABLE_SIMS` — an n was NOT invented to open the gate.
- **DONE — the live_state dropout.** `_public_scoreboard_live_state_payload` was
  `except Exception: return None`, publishing a 6s ESPN timeout as "no games in
  progress". Age-bounded MARKED carry-forward shipped `16a898ef`
  (live-odds-worker). **Its trigger has NOT fired in production yet** — unit
  verified only.
- **NOT DONE — props.** Across the entire wnba snapshot, `actual` /
  `live_projection` / `live_total` / `live_total_line` appear 24 times each and
  are **NULL in all 24**. Wiring the prop join would be inert. Producer gap in
  `wnba/live_lens.py` and its box-score source.
- **NOT DONE — tick-over-tick movement.** The stated verification wanted a diff
  proving the numbers MOVE. The second tick had no live rows to compare, so it
  is **unproven, not passed**. Needs another live WNBA slate.
- Verification: game-line half MET (two independent live slates). Props half and
  movement UNMET. Lane stays OPEN for those.
- Blocked by: none.

#### game-shape-capture — WNBA pbp CAPTURE BUILT; THE SOURCE IS SERVING A FROZEN SKELETON (`#455`) `[2026-08-16 ~19:3x CDT]`

**The user corrected me and the correction found a production defect.** I had
reported "no WNBA pbp corpus exists on Render" and, when asked "did you check
render disk", had to answer no — I inferred unreachability from
`HOT_ARTIFACT_PATTERNS` without checking whether the data was there.

**Two of my own claims were wrong:**
1. "Production has been accumulating all season" — **false**. The endpoint
   returns 0 games for 2026-06-27 and 2026-07-15; it serves live only.
2. "The allowlist is the root cause" — **not the binding constraint**. Adding
   the pattern would export an empty set. I had proposed a fix that would have
   cost a web deploy and changed nothing.

**What the checkout files actually are:** cached API responses. The
`payload`/`ttl`/`ok`/`generated_at` wrapper is an HTTP cache envelope, not a
data record — which explains all three anomalies at once (17 records on 2 dates,
test fixtures `0000000001` mixed in, mid-game partials beside completed games).

**THEN THE USER SAID: 2 of today's 3 games are FINAL and one is LIVE.** The
endpoint returned all-null for all three. Reproduced and filed as **`#455`**:
`build_live_pbp_stats_payload` (`wnba/cards.py:6390`) never computes pbp — it
replays a stored snapshot and otherwise emits a hardcoded all-null skeleton,
**and a skeleton has a non-empty `games` list, so once persisted it is served in
preference to real data all day** (`:6401`). `generated_at` read
**16:14:21 CDT, frozen ~3 hours** on a `ttl=1` re-fetch.

**BUILT:** `scripts/capture_wnba_pbp.py` + `tests/test_capture_wnba_pbp.py`.
Its defining rule is a REFUSAL: it never stores a skeleton, counts them
separately, and **exits 2** when every record is one, so "captured nothing"
cannot read as "nothing happened". Storing what the endpoint returns would have
industrialised the defect — a corpus of confident nulls with a fake denominator.
`--probe` reports without writing.

**12 tests, 5 of 5 mutations caught** (skeleton counted as signal, zero-valued
home/away counted as signal, storing with no signal, probe mode writing,
possessions-only detection dropping early live ticks).

**Deliberately NOT done:** no second implementation of the `poss_est` formula.
Inventing one is how two numbers that should agree start disagreeing.

#### game-shape-capture — `#456` NBA DATE-SCOPE FIX BUILT; `#455` WNBA BLOCKED BY A CLAIM `[2026-08-16 ~19:5x CDT]`

**NBA does NOT share `#455`.** Checked component by component rather than assumed: NBA **never persists** (zero write calls in `nba/live_lens.py`), so WNBA's sticky-skeleton mechanism cannot occur. Both sports DO emit the identical all-null `ok: True` skeleton, so the instrument-blindness half is shared.

**NBA has its own defect, confirmed in production**: one undated snapshot path served for every requested date (`2025-12-25` -> payload date `2026-06-13`). Filed as **`#456`**, fix built and tested, **NOT DEPLOYED**. The refusal fires on the real endpoint path — `nba.py:_allow_stored_date_fallback()` returns `False`, verified BEFORE writing the fix rather than after.

**A PRE-EXISTING FAILURE, NOT MINE:** `test_nba_refresh_runner.py::test_main_materializes_core_artifacts_into_bundle_root` fails identically with my change reverted to `origin/main`'s version. Attributed by measurement, not assumed.

**`#455` (WNBA) CANNOT BE FIXED BY THIS LANE.** `syndicate/features/wnba/cards.py` is claimed by **`wnba-live-tier` (OPEN)** — re-checked immediately before the edit; no edit was made. Handed to that session. **Worth their attention: their own lane status reads "PROPS NOT WIRED — the source emits nothing." That may BE `#455`** — the skeleton is exactly what a prop consumer would see as "the source emits nothing."

#### refresh-worker-oom-recurrence — CALLER-SIDE TRACE `[2026-08-17 ~00:3xZ]` — **the allocator's SPAN is now named, and BOTH designed brakes on it are measurably inert**
- **Verdict reproduced twice** (`deploys.md`): `last_stage=board_contract_end` on
  the 00:19:48Z kill (`94447830`, anon 1209->3998MB/~25s) and the 00:32:32Z kill
  (`7c2b1a17`, anon 1354->3751MB/~16s). Different commits; the second had no
  concurrent deploy in its window. `apply_game_board_contract` is exonerated.
- **The span, from the loop structure** (`intelligence.py:2793-2835`): between
  `OVERVIEW_SPORT_BEGIN` (a bare `print`, so it CANNOT set `last_stage` — which
  is why the climb looked unmarked) and the `overview_sport_end` stage marker,
  there are exactly two calls: **`_build_sport_overview`** (`home.py:6733`) and
  **`_emit(sport_row)`**. For non-MLB sports the board contract is the LAST
  statement of the cards builder (`nfl/cards.py:505` is
  `return apply_game_board_contract(...)`), so `board_contract_end` is the last
  marker before the stack unwinds — the allocator is ABOVE it, in that span.
- **MEASURED IN PRODUCTION, window 00:24:01Z (7c2b1a17 live) -> 00:35:50Z,
  containing the 00:32:32Z kill:**

      OVERVIEW_SPORT_BEGIN            30   incl. a FULL 8-sport pass at 00:33:38-40
                                           with force_refresh=True skip_game_hydration=False
      OVERVIEW_SPORT_END              30
      OVERVIEW_REBUILD_RATE_LIMITED    0   <-- #251's throttle on hydrated rebuilds
      OVERVIEW_STOPPED_FOR_MEMORY      0   <-- #250's memory circuit breaker

  **The expensive path runs all 8 sports hydrated under `force_refresh=True`,
  and neither guard built to bound it engages — across a window containing an
  OOM kill that reached headroom 0.0.**
- **This REPRODUCES `#336` on current code.** That entry recorded
  `OVERVIEW_REBUILD_RATE_LIMITED` firing ZERO times over 29 minutes and 11 passes
  and left the reason unresolved. It is still zero. The defect is open, not
  historical.
- **The retention mechanism `home.py:6766-6782` describes is the standing
  hypothesis, NOT yet confirmed by me:** `_HOME_OVERVIEW_TTL_SEC` is 10s against
  a ~90s board loop, so the cache "structurally cannot hit" while still RETAINING
  the previous hydrated row — the process holds the old context and builds a new
  one on top. That comment's own 2026-08-07 numbers are `+2.9GB in 73s`. Tonight's
  shape is +2.4GB in 16s and +2.8GB in 25s: same magnitude, much faster.
- **NOT CLAIMED, and the next person must not read it as claimed:** I have not
  shown WHICH of the two calls allocates, and I have not established why either
  guard is silent. Two candidate reasons for the memory guard, untested:
  (a) it is checked BETWEEN sports, so an excursion INSIDE one sport is invisible
  to it by construction — `#250`'s own comment says this; (b)
  `_overview_headroom_exhausted` (`intelligence.py:2635-2661`) returns **False**
  when the snapshot is `None` or lacks `sufficient`, i.e. **unknown maps onto the
  permissive branch and emits no reason** — the failure shape
  `feedback_unknown_must_not_default_permissive` describes.
- **NEXT, in order:** (1) determine why `OVERVIEW_STOPPED_FOR_MEMORY` is silent —
  (a) vs (b) above is decidable by reading one snapshot at a check point;
  (2) instrument the `_build_sport_overview` / `_emit` boundary the way
  `board_contract_end` instrumented the builder's return, since that split is now
  the whole remaining question; (3) only then touch the floors.
#### PHASE 1C — **VERIFIED IN PRODUCTION 2026-08-17 00:11:36Z.** Lane goal met.
- The lane's pre-registered outcome, met exactly: `FIXTURE_CADENCE sport=soccer
  league=mls due:imminent_handoff_to_t_window:1107s` against `championship` /
  `la_liga` / `primeira_liga` all `skip:mid:18-19h_out`, plus `scope=league
  due=mls of=4` and a live process carrying `--soccer-leagues mls`.
- Shipped as part of a three-service CONVERGENCE (live-odds-worker `c348da53`,
  web `763a2f66`, refresh-worker `7c2b1a17`), each a real merge on its own live
  SHA. 303 tests passed pre-deploy; 0 tracebacks post-deploy.
- **Falsification test did NOT fire:** per-league resolution did reach distinct
  tiers, so league granularity WAS the missing term.
- **Still open in this lane's neighbourhood, NOT done:** soccer live sims. A live
  MLS match serves 321 rows / 5 projections / 0 live_aware. `#440`'s Phase 3 has
  no soccer item at all. That is a plan defect, recorded in `state.md`.
- **Found while deploying, unrelated to this lane:** `#449` refresh-worker OOM
  loop (23 kills / 8 hours). `#447` red layer2 wiring tests. `#448` unattended
  scheduled tasks wedging deploy claims.

## Archived lanes (full bodies in `lanes_closed.md`)
- `nfl-pbp-root-resolution` — nfl-pbp-root-resolution — **CLOSED 2026-08-16 — resolution mechanism PROVEN CORRECT and the hypothesis FALSIFIED in the same reading. `#441` root caus → `lanes_closed.md`.
- `render-events-reader` — render-events-reader — CLOSED-VERIFIED 2026-08-16 — **`scripts/render_events.py` + `tests/test_render_events.py` SHIPPED TO THE TREE (no deploy — this → `lanes_closed.md`.
- `ui-probe-settle-plateau` — ui-probe-settle-plateau — CLOSED 2026-08-16 — the settle now needs 2400ms of stillness, and a verdict resting on absence says so — opened 2026-08-16 — → `lanes_closed.md`.
- `ui-probe-desktop-height-model` — ui-probe-desktop-height-model — CLOSED 2026-08-16 — desktop is UNFITTABLE, not mis-tuned; measured the floor instead of tuning the threshold — opened  → `lanes_closed.md`.
- `ui-probe-tie-floor-tracking` — ui-probe-tie-floor-tracking — CLOSED 2026-08-16 — floor collected on every row; 5 of 6 stable, mlb mobile fires the rule at 2.06x — opened 2026-08-16  → `lanes_closed.md`.
- `ui-probe-tie-statistic` — ui-probe-tie-statistic — CLOSED 2026-08-16 — implemented as decided; the statistic did NOT help and the instability is the SLATE — opened 2026-08-16 — → `lanes_closed.md`.
- `ui-probe-tracked-statistic-revert` — ui-probe-tracked-statistic-revert — CLOSED 2026-08-16 — reverted to worstGroupPx; exposed and fixed two false alarms that were failing a healthy board → `lanes_closed.md`.
- `branch-overlap-baseline-instrumentation` — branch-overlap-baseline-instrumentation — CLOSED 2026-08-16 — the baseline was sampling hours where the failure does not happen — session: `branch-ove → `lanes_closed.md`.
- `ui-probe-baseline-nfl-ncaaf` — ui-probe-baseline-nfl-ncaaf — CLOSED 2026-08-16 — armed for nfl/ncaaf only; mlb stays watch-only — opened 2026-08-16 — session: ui-probe-rerun-compare → `lanes_closed.md`.
- `mlb-mobile-live-residual` — mlb-mobile-live-residual — CLOSED 2026-08-16 — HYPOTHESIS FALSIFIED; it is a false alarm, the Live fit is convex and `fitRatio` cannot see curvature — → `lanes_closed.md`.
- `branch-overlap-manual-run-marker` — branch-overlap-manual-run-marker — CLOSED — opened 2026-08-16 — session: `branch-overlap-baseline-watch` — verified in production 2026-08-16T19:52:23+ → `lanes_closed.md`.
- `ui-probe-peer-deviation-gate` — ui-probe-peer-deviation-gate — CLOSED 2026-08-16 — one model-free height rule; production green, coverage gap printed — opened 2026-08-16 — session: u → `lanes_closed.md`.
- `layer1-board-coverage` — layer1-board-coverage — UPDATE 2026-08-16 17:5xZ — **DEPLOYED AND FALSIFICATION TEST PASSED. Supersedes this lane's "UNDEPLOYED" line above.** → `lanes_closed.md`.
- `ui-probe-curvature-detection` — ui-probe-curvature-detection — CLOSED 2026-08-16 — `curved` forces `reliable:false`; Preview (the falsification case) is not flagged — opened 2026-08- → `lanes_closed.md`.
- `ui-probe-proportional-budget` — ui-probe-proportional-budget — CLOSED 2026-08-16 — shipped; falsification test FIRED (proportional does not tighten the spread) but it fixes the width → `lanes_closed.md`.
- `layer1-board-coverage` — layer1-board-coverage — **CLOSE REFUSED 2026-08-16 18:0xZ.** Verification is not met, and a NEW production defect was found in this lane's own scope w → `lanes_closed.md`.
- `soccer-live-game-state` — soccer-live-game-state — CLOSED-VERIFIED 2026-08-16 18:56Z — a kicked-off match is no longer `pregame`, and no finished match carries an edge → `lanes_closed.md`.
- `ui-probe-tab-click-race` — ui-probe-tab-click-race — CLOSED 2026-08-16 — cause UNPROVEN and not reproduced; the blindness that made it undiagnosable is fixed — opened 2026-08-16 → `lanes_closed.md`.
- `layer1-board-coverage` — layer1-board-coverage — SCOPE ADDED 2026-08-16 20:0xZ — the HR threshold ladder → `lanes_closed.md`.
- `ui-probe-peer-min-group` — ui-probe-peer-min-group — CLOSED 2026-08-16 — verdicts need n>=3; thin groups reported, never dropped — opened 2026-08-16 — session: ui-probe-rerun-co → `lanes_closed.md`.
- `sim-scheduling` — sim-scheduling — **DEPLOYED AND MEASURED 2026-08-16 21:2xZ.** `#441` verified live; `#445` shipped but unverifiable today; layer2 (both halves) shippe → `lanes_closed.md`.
- `game-shape-capture` — game-shape-capture — UPDATE 2026-08-16 ~23:0xZ (checkpoint) — **PRIMITIVE COMMITTED `af3017e6`; EMIT STILL BLOCKED; HANDOFF SENT** → `lanes_closed.md`.
- `ncaaf-schedule-fallback` — ncaaf-schedule-fallback — **CLOSED-VERIFIED 2026-08-16 — `#445` fixed in `483bb9dd`, on `origin/main`. NOT DEPLOYED (NCAAF opens 08-29)** — opened 202 → `lanes_closed.md`.
- `nfl-pbp-fetcher` — nfl-pbp-fetcher — **CLOSED-VERIFIED 2026-08-16 18:31:15Z — pbp_2025.csv written on the mounted disk (97,951,481 bytes, 46,452 REG plays) and the guard → `lanes_closed.md`.
- `closing-stamp-is-detection-time` — closing-stamp-is-detection-time — CLOSED-VERIFIED — **OUTPUT MEASURED 2026-08-15 22:06 CDT / 2026-08-16 03:06Z. 21/21 new-code stamps precede first pi → `lanes_closed.md`.
- `spread-line-sign-convention` — spread-line-sign-convention — CLOSED-VERIFIED 2026-08-16 — **ARTIFACT OUTPUT NOW MEASURED: 12 of 12 MLB spreads rows correct on the served shortlist ( → `lanes_closed.md`.
- `commit-guard-reads-wrong-index` — commit-guard-reads-wrong-index — CLOSED 2026-08-16 — the guard read the MAIN worktree's index while the commit used another one — session: `live-gamel → `lanes_closed.md`.
- `ask-answer-substance` — ask-answer-substance — **CLOSED-VERIFIED 2026-08-16 — 8 deploys, all measured, live web `9f617f34`. The inline quick ask names a bet a human can place → `lanes_closed.md`.

> Moved 2026-08-15 to bring this file back under the digest budget.
> Nothing was deleted. Each line points at a full body — including the
> file/line maps and the ORPHANED lanes' resume notes.

- `mlb-prop-oos-calibration` — mlb-prop-oos-calibration — CLOSED-VERIFIED 2026-08-15 — D4 CLOSED: the split ran on production, `batter_hits` is the one verdict that did NOT survive  → `lanes_closed.md`.
- `probability-clamp-removal` — probability-clamp-removal — CLOSED-VERIFIED 2026-08-15 — WNBA site fixed, scored 5/5, shipped as `de0c367f`; the other TWO sites are held by other OPE → `lanes_closed.md`.
- `probability-differential-test` — probability-differential-test — CLOSED-VERIFIED 2026-08-15 — harness + table + owners shipped as `d448a100`; ONE live misprice CONFIRMED in production → `lanes_closed.md`.
- `soccer-backtest-leakage` — soccer-backtest-leakage — CLOSED-VERIFIED 2026-08-14 — **ARCHIVED to `lanes_closed.md`**. Audit §7 #6. HEAD `2dcca4fe`; `50fd7fe2` ALONE IS UNSAFE TO  → `lanes_closed.md`.
- `ask-headline-from-board` — ask-headline-from-board — CLOSED-VERIFIED 2026-08-15 — web `c774fe1a` live 03:29:56Z; B01 delta 0.000 and refusal 4/8 matching its control, both measu → `lanes_closed.md`.
- `recommendation-lane-correctness` — recommendation-lane-correctness — CLOSED-VERIFIED 2026-08-14 — 4 shipped+measured; A3a (`28291eb6`) HELD BACK BY CHOICE, not by doubt — opened 2026-08 → `lanes_closed.md`.
- `soccer-odds-coverage` — soccer-odds-coverage — ORPHANED-CLAIMS-RELEASED 2026-08-15 — claims on `refresh_odds_sources.py` released; the per-league cadence is NOT fixed — opene → `lanes_closed.md`.  **ORPHANED — resume notes + file claims in the archive.**
- `soccer-projection-gap` — soccer-projection-gap — ORPHANED-CLAIMS-RELEASED 2026-08-15 — it claimed NO files; the 30% projection coverage is unchanged — opened 2026-08-14 — sess → `lanes_closed.md`.  **ORPHANED — resume notes + file claims in the archive.**
- `wnba-skill-backtest` — wnba-skill-backtest — CLOSED-VERIFIED 2026-08-14 — opened 2026-08-14 — session: nfl-day-of-game → `lanes_closed.md`.
- `wnba-skill-backtest` — wnba-skill-backtest — CLOSED-VERIFIED — superseded header, kept for the file/line map → `lanes_closed.md`.
- `odds-capture-stall` — odds-capture-stall — CLOSED 2026-08-14 — NOT A DEFECT: the 2h gap IS the configured pregame cadence → `lanes_closed.md`.
- `board-ui-freshness-slip-books` — board-ui-freshness-slip-books — CLOSED 2026-08-14 — all three shipped and verified → `lanes_closed.md`.
- `build-time-estimate` — build-time-estimate — CLOSED 2026-08-14 — board build timed at ~2-4 min on current code; estimator can no longer collapse to ~0 — opened 2026-08-14 —  → `lanes_closed.md`.
- `layer2-board-freshness` — layer2-board-freshness — CLOSED-VERIFIED 2026-08-14 (memory follow-on lives on branch `memory/overview-sum-to-max`, undeployed) — 3h clean window, all → `lanes_closed.md`.
- `projection-skill-declaration` — projection-skill-declaration — CLOSED-VERIFIED 2026-08-14 — opened 2026-08-14 — session: nfl-day-of-game → `lanes_closed.md`.
- `projection-skill-declaration` — projection-skill-declaration — CLOSED-VERIFIED — superseded header, kept for the file/line map → `lanes_closed.md`.
- `projection-degeneracy-detector` — projection-degeneracy-detector — CLOSED-VERIFIED 2026-08-14 — opened 2026-08-14 — session: nfl-day-of-game → `lanes_closed.md`.
- `projection-degeneracy-detector` — projection-degeneracy-detector — CLOSED-VERIFIED — superseded header, kept for the file/line map → `lanes_closed.md`.
- `anon-allocation-site` — anon-allocation-site — ORPHANED-REASSIGNED 2026-08-15 — file claims released to `memory-watchdog-435`; the lane's OWN FINDINGS ARE NOT CLOSED — opened → `lanes_closed.md`.  **ORPHANED — resume notes + file claims in the archive.**
- `nfl-degenerate-writer` — nfl-degenerate-writer — CLOSED-VERIFIED 2026-08-13 — opened 2026-08-13 — session: nfl-day-of-game → `lanes_closed.md`.
- `nfl-degenerate-writer` — nfl-degenerate-writer — CLOSED-VERIFIED — superseded header, kept for the file/line map → `lanes_closed.md`.
- `refresh-worker-anon-leak` — refresh-worker-anon-leak — ORPHANED-REASSIGNED 2026-08-15 — file claims released to `memory-watchdog-435`; the leak itself IS STILL UNEXPLAINED — open → `lanes_closed.md`.  **ORPHANED — resume notes + file claims in the archive.**
- `nfl-day-of-game` — nfl-day-of-game — CLOSED-VERIFIED 2026-08-13 — opened 2026-08-13 — session: nfl-day-of-game → `lanes_closed.md`.
- `nfl-day-of-game` — nfl-day-of-game — CLOSED-VERIFIED — superseded header, kept for the file/line map → `lanes_closed.md`.
- `quote-join-enrich-cost` — quote-join-enrich-cost — CLOSED 2026-08-14 — all three verification criteria MET → `lanes_closed.md`.
- `checkpoint-witness` — checkpoint-witness — CLOSED 2026-08-13 — opened 2026-08-13 — session: hooks-test → `lanes_closed.md`.
- `checkpoint-guard-scope` — checkpoint-guard-scope — CLOSED-VOID 2026-08-13 — opened 2026-08-13 — session: hooks-test → `lanes_closed.md`.
- `memory-guard-reclaimable` — memory-guard-reclaimable — CLOSED 2026-08-13 — fix VERIFIED, and it uncovered a leak → `lanes_closed.md`.
- `mlb-props-regen` — mlb-props-regen — ORPHANED-CLAIMS-RELEASED 2026-08-15 — `live_refresh_loop.py` released; the props-regen fixes are NOT confirmed shipped — opened 2026 → `lanes_closed.md`.  **ORPHANED — resume notes + file claims in the archive.**
- `hooks-enforcement-test` — hooks-enforcement-test — CLOSED 2026-08-13 — opened 2026-08-13 — session: hooks-test → `lanes_closed.md`.
- `intelligence-state-red-baseline` — intelligence-state-red-baseline — CLOSED 2026-08-13 — opened 2026-08-13 — session: intel-state-baseline → `lanes_closed.md`.
- `board-transport` — board-transport — CLOSED 2026-08-13 (work measured 08-10/11) → `lanes_closed.md`.
- `sim-execution-observability` — sim-execution-observability — CLOSED-PENDING-MEASUREMENT 2026-08-13 → `lanes_closed.md`.
- `soccer-sim-grouping` — soccer-sim-grouping — CLOSED 2026-08-10 — shipped and verified, one thread handed on → `lanes_closed.md`.
- `layer1-live-tier` — layer1-live-tier — CLOSED-PENDING-MEASUREMENT 2026-08-13 → `lanes_closed.md`.
- `internal-hostname-cutover` — internal-hostname-cutover — CLOSED 2026-08-13 — verified in production → `lanes_closed.md`.
- `internal-hostname-cutover` — internal-hostname-cutover — CLOSED — opened 2026-08-13 — session: <name> → `lanes_closed.md`.
- `ask-refusal-gate` — ask-refusal-gate — CLOSED-VERIFIED 2026-08-14 — refusal 3/8 -> 6/8 in production, zero regressions — opened 2026-08-14 — session: ask-audit → `lanes_closed.md`.
- `ask-board-candidates` — ask-board-candidates — ORPHANED-CLAIMS-RELEASED 2026-08-15 — `ask_the_syndicate_data.py` released; M1 SHIPPED but a REVERT OF IT IS STAGED IN GIT — op → `lanes_closed.md`.  **ORPHANED — resume notes + file claims in the archive.**
- `board-ui-visible-defects` — board-ui-visible-defects — CLOSED-VERIFIED 2026-08-14 — deployed as web `aadcde77`, every criterion measured in production — opened 2026-08-14 — sessi → `lanes_closed.md`.
- `memory-cutover-ship` — memory-cutover-ship — CLOSED-VERIFIED 2026-08-15 — `#387` shipped in TWO halves (`cfee9c6e` + `705eeefc`), sports=8 restored, peak 34.3% of ceiling —  → `lanes_closed.md`.
- `board-contract-absent-not-neutral` — board-contract-absent-not-neutral — ORPHANED-CLAIMS-RELEASED 2026-08-15 — 6 claims released incl. `game_board_contract.py`; partial work IS committed  → `lanes_closed.md`.  **ORPHANED — resume notes + file claims in the archive.**
- `mlb-oom-outlier-2003z` — mlb-oom-outlier-2003z — CLOSED 2026-08-15 — QUESTION WAS MALFORMED: no outlier, 16 kills that day; H1 falsified — opened 2026-08-15 — session: memory- → `lanes_closed.md`.
- `mlb-hydration-oom-435` — mlb-hydration-oom-435 — CLOSED 2026-08-15 — `build_cards_page_context` is 2 of 6 kills, NOT the common factor — opened 2026-08-15 — session: memory-cu → `lanes_closed.md`.
- `memory-watchdog-435` — memory-watchdog-435 — CLOSED-VERIFIED 2026-08-15 — watchdog + 3 censuses live; ROOT CAUSE FOUND: append-only quote shard, 92.4% superseded, 6.3x read  → `lanes_closed.md`.
- `odds-props-fabricated-probability` — odds-props-fabricated-probability — ORPHANED-CLAIMS-RELEASED 2026-08-15 — the two prop-refresh scripts released; work committed, artifact effect UNMEA → `lanes_closed.md`.  **ORPHANED — resume notes + file claims in the archive.**
- `soccer-card-end-to-end` — soccer-card-end-to-end — CLOSED-VERIFIED 2026-08-15 — deployed as web `7e334509`, every criterion measured in production — opened 2026-08-15 — session → `lanes_closed.md`.
- `model-audit-devig-and-hygiene` — model-audit-devig-and-hygiene — CLOSED-VERIFIED 2026-08-15 — #5 falsified then collapsed for real + D5 done (`2ac3c6bc`, committed, NOT deployed, cons → `lanes_closed.md`.


#### game-shape-capture — SOCCER ADDED, EMIT LANDED; ALL FIVE SPORTS NOW HAVE A CONTRACT `[2026-08-17 ~00:3xZ]`

**Soccer has the RICHEST live state of any sport here and is the ONLY one
carrying real in-game EVENTS.** Measured on a populated record
(`data/soccer_source/mls/api/live_state/live_state_2026-07-22.json`, CF Montréal
v Toronto FC): shots, shots on target, corners and red cards per side, plus
`half` / `clock_remaining` / scores. **Only 3 of 14 live_state files on disk are
populated at all** — the rest are `count: 0`.

- **Only sport where a true EVENT RATE is derivable.** `shots_per_minute` is a
  real tempo statistic, not the scoring-rate proxy basketball and football had
  to settle for. `shot_dominance` says who is actually on top — 0-0 with shots
  9-5 is not a balanced match, and the scoreline cannot say so.
- **`clock_remaining` IS REMAINING-IN-THAT-HALF, NOT IN THE MATCH**
  (`_current_half_and_clock_remaining`, `_HALF_SECONDS = 2700`). half 2 /
  1800s is the **60th minute**. Reading it as remaining-in-match inverts the
  entire progress axis; mutation S1 fires on exactly that.
- **THE REFUSAL THAT MATTERS MOST, AND IT IS UNIQUE TO SOCCER: the same
  `live_state` embeds the MODEL'S OWN `projection` and `goal_windows` blocks.**
  They are excluded from the shape. Game shape is what a model's error is scored
  AGAINST; folding the model's prediction into it makes the analysis circular —
  "is the model wrong when the model says X" cannot separate a bad model from a
  bad state. No other sport's live_state carries its projection inline, so
  nothing else in the module guards this. Mutation S2 fires on the leak.
- **KNOWN BLIND SPOT, FLAGGED NOT PAPERED OVER:** the producer clamps
  `clock_remaining` at 0 and never returns a half above 2, so second-half
  stoppage is invisible — 90' and 95' both read `match_minute == 90.0`.
  `clock_saturated` marks that case so it can be excluded. Fixing it needs the
  ingestion contract to carry the raw match clock.
- **Zero-shot dominance is `None`, not 0.5** — "nobody has shot yet" and "both
  sides equally" are different states, and collapsing them files every goalless
  opening into the balanced cell.
- **Possession and xG are NOT captured and are NOT invented.** Shots on target
  is not a substitute for either.

**Margin bands are in GOALS** (level / 1 / 2 / 3+) — a fourth distinct scale.
Buckets cap at **13** (3 phases x 4 bands): `first_half`, `second_half`,
`closing` (final 15 min). `red_card_diff` is deliberately NOT in the bucket
despite being one of the strongest state variables in the sport — it would
double the space, and it stays on the record as the obvious first re-cut.

**EMIT LANDED.** `soccer/ingestion/espn_live_state.py` was UNCLAIMED (checked
immediately before the edit). `build_live_state` now binds its dict and attaches
`state["game_shape"]` **before** any projection is merged in by the caller —
the ordering is pinned by a test.

**90 tests green** across `test_game_shape` (57), `test_nfl_live_game_state`
(20), `test_soccer_espn_live_state` (10), `test_poll_soccer_live_state` (3).
**8 of 8 soccer mutations caught** — 6 on the primitive (remaining-in-match
clock, model-output leak, 0.5 dominance default, unflagged saturation, widened
closing window, `half > 2` accepted) and 2 on the emit (shape never attached,
shape built from a synthetic dict rather than the real state).

**STATUS ACROSS THE LANE:** MLB and WNBA primitives on main with emits BLOCKED
by `Layer 1 board coverage audit (fork 2)`; **NFL and soccer emits LANDED**;
NCAAF has a contract and **no producer at all**. **n = 0 everywhere — not one
production slate has run through any of it.**

#### game-shape-capture — CHECKPOINT 2026-08-16 ~19:0x CDT — **ALL WORK ON `origin/main`; LANE STAYS OPEN ON VERIFICATION**

`origin/main` `8a01fa3d`; ref `lane/game-shape-capture` -> same. Five commits,
all verified reachable: `597f4a80` `862aac3a` `2dd384b0` `5cb588f2` `8a01fa3d`.
**90 tests, 31 of 31 mutations caught.** `#454` filed.

**WHY THIS LANE IS NOT CLOSED, stated so nobody closes it on the commit count:**
its verification is *one live slate with a non-zero bucket distribution read
across two builds*, and **that has not run. n = 0 for every sport.** Two emits
exist (NFL, soccer); neither is deployed and neither has seen a production game.

**NEXT ACTIONS, in order:**
1. Read `game_shape` off a live NFL preseason or soccer fixture — the only step
   that turns any of this from prepared into measured.
2. MLB + WNBA emits: two handoffs to `Layer 1 board coverage audit (fork 2)`
   are **unanswered**. If declined, wait for the lanes to close; do not edit
   across them.
3. NCAAF needs a live-state PRODUCER built (no `live_game_state` analog exists).
   Season opens **08-29** — this is the only dated item in the lane.
4. Owed consolidation: `wnba/cards.py:891` should delegate to
   `basketball_elapsed_minutes`; blocked on that file's holder.

#### game-shape-capture — SCOPE ADDED 2026-08-16 ~19:5x CDT — WNBA pbp possessions (`#454` first step)

Files added to this lane: `scripts/wnba_pbp_possessions.py` (new),
`tests/test_wnba_pbp_possessions.py` (new). Both unclaimed; `scripts/` carries
no lane claim.

**THE ANSWER TO "TAKE WNBA PBP FOR MODELLING" IS: THE DATA IS REAL AND THE
SAMPLE IS NOT.** Possessions genuinely exist — `pbp_possessions.poss_est`,
computed as `FGA + TOV + 0.44*FTA - OREB`
(`vendor/wnba_betting_repo/app.py:3572`) — and the values are sound. But on the
tracked mirror:

| stage | count |
|---|---|
| files scanned | 53 |
| game records | 120 |
| with possession data | **17** |
| placeholder ids excluded (`0000000001`…) | 8 |
| **partial / mid-game excluded** | 5 |
| **USABLE GAMES** | **4** |
| dates with possessions | 2 (`''` and `2026-06-27`) |

The four survivors read 73.02 / 74.96 / 78.02 / 85.30 possessions per team —
plausible WNBA figures, which is the sanity check that the underlying
`poss_est` is sound. **No aggregate is emitted: `--min-games` defaults to 10 and
the tool refuses at n=4, naming the shortfall.** Fitting anything on this would
be `#377` committed by the tool written to prevent it. **The mirror is lossy —
production coverage is UNKNOWN and unreadable from here (no `ADMIN_TOKEN`, and
`/api/ops/artifacts/export` reads WEB's disk).**

**TWO DEFECTS IN MY OWN FIRST VERSION, both found by running it rather than by
review:**
1. **Partial snapshots counted as games.** A `pace_per_team` of **2.5**
   (CHI@DAL, one quarter) and **27.18** (CON@TOR, halftime) sat next to real
   ~75-possession games. These are LIVE snapshots; most are mid-game. Fixed by
   `quarters_complete()` (all four `q_totals` non-null).
2. **Repeated snapshots of the same game counted twice.** SEA@TOR and CON@TOR
   each appeared twice with byte-identical totals. Fixed by a dedupe keyed on
   `(game_id, teams)` keeping the highest total.
The docstring had CLAIMED a `partial` flag the code never implemented — a
comment that overstated the code, caught by reading the output.

**A VACUOUS TEST, CAUGHT BY MUTATION AND FIXED.** `test_team_possessions_ignores
_the_zero_valued_home_and_away_keys` passed with the key filter REMOVED, because
the `poss_est <= 0` filter already drops those keys on real data. It pinned the
zero filter, not the key filter, so the key filter could have been deleted
silently. Added
`test_the_key_filter_is_load_bearing_independently_of_the_zero_filter`, which
puts NON-zero values under `home`/`away` — the double-counting case. Mutation P1
now fires.

**15 tests, 6 of 6 mutations caught** (home/away key filter, completeness needing
all four quarters, placeholder ids accepted, aggregate emitted below the floor,
a refusal smuggling a mean out with it, duplicates not collapsed).

**`game_shape.py` COMMENT AMENDED, not the flag.** `possession_pace_available:
False` is correct for the card payload that function reads; the comment now says
so precisely and points at the `live_pbp_stats` family where possessions DO
live, with the coverage caveat and the tricode-vs-home/away trap attached.

### score-live-gameline-edges — OPEN — opened 2026-08-17 — session: layer1-board-coverage
- **Goal:** the live game-line model's probabilities are SCORED against realised
  outcomes, and against the market recorded on the same row. **Testable
  outcome:** a written report over N ledger records with the window stated,
  carrying (a) Brier + calibration buckets for `model_home_win_prob`, (b) the
  SAME two for `market_fair_prob` on the identical rows, and (c) the difference.
  **(b) is the point.** A Brier score alone says nothing about whether the model
  is worth running; the market benchmark on the same rows is the only comparison
  that answers it. `soccer-model-coverage` already found its model LOSING to the
  market by this kind of test — that outcome is expected, permitted, and is a
  result, not a failure of this lane.
- **Why this lane exists now.** `live-game-line-projection` closed
  2026-08-17 00:4xZ having proved the ledger can produce a sample (`written=13`
  across two builds, 2 of them non-priceable). It explicitly carried forward:
  *"the ledger can now produce a sample; nobody has measured whether those 11
  edged rows were RIGHT."* This is that lane.
- **THE SAMPLE IS CURRENTLY UNREACHABLE, and that is the first task, not the
  scoring.** Measured 2026-08-17 00:4xZ: the ledger writes to
  `mlb_source/data/live_gameline_ledger/live_gameline_ledger_<date>.jsonl` on the
  WORKER's disk, and that path matches **zero** entries in
  `HOT_ARTIFACT_PATTERNS` — `/api/ops/artifacts/export?pattern=...` returns
  `count 0, bytes 0`. The COUNTERS are served on `/api/board/book-grid`; the
  RECORDS are not published anywhere. Three routes, to be chosen on evidence:
  1. publish the ledger (needs `artifact_publisher.py` — **NOT this lane's**),
  2. score worker-side and publish only the small summary,
  3. pull a copy and score offline for the first read.
  **Route 3 first**, because it needs no deploy and answers whether the sample is
  even large enough to score.
- **Files (claimed):**
  - `scripts/score_live_gameline_edges.py` (new)
  - `tests/test_score_live_gameline_edges.py` (new)
  - `syndicate/features/shared/live_gameline_ledger.py` (a READER only; the
    writer is settled and must not be touched)
  Collision check run with `lane-guard.py`'s own `_claims()` at open time: all
  three CLEAR.
- **NOT claimed, and why:**
  - `syndicate/features/shared/artifact_publisher.py` and `clv_join.py` — held by
    OPEN `clv-without-settlement`. Route 1 above needs the first; **coordinate,
    do not take it.** That lane owns the CLOSE half of CLV and this lane owns
    OUTCOME scoring; they are different questions on the same records.
  - `syndicate/features/shared/intelligence_evaluation.py` — CLEAR, but reuse
    `_calibration` (`:1477`, already computes Brier + MAE) rather than writing a
    fourth copy. Claim it only if it must change.
- **Hypothesis (falsifiable, stated before measuring):** the live game-line
  model's `model_home_win_prob` is NOT better calibrated than `market_fair_prob`
  on the same rows — i.e. Brier(model) >= Brier(market).
- **Falsification test:** Brier(model) < Brier(market) on a sample of stated size,
  with the win-rate and calibration buckets printed alongside so a single-number
  win cannot hide a bad curve.
- **Verification:** a report in `deploys.md` with the window, the sample size, and
  BOTH Brier scores. Scored two ways and both reported: over `priceable: true`
  rows (what the board actually showed) and over ALL projected rows (the model
  itself). The ledger writes `priceable` as a FIELD not a filter precisely so
  this split is possible — a pass restricted to priceable measures the publish
  gate, not the model.
- **Outcomes come from final scores, NOT from settlement.** The record carries
  `game_pk` plus live `home_score`/`away_score`; the final result is joined from
  the scoreboard. **This lane is therefore NOT blocked by
  `grading-blocker-settled-zero`**, whose `EVALUATION_SETTLEMENT_...AUTORUN` is
  off by user decision.
- **Known trap inherited from the writer, do not re-discover:** the ledger's own
  docstring records that the closing-price recorder
  (`closing-stamp-is-detection-time`) writes the HOME price on every row (18/18),
  so any CLV-style pairing against it inherits a known defect. This lane scores
  against OUTCOMES and sidesteps that; if it ever reaches for a close, read that
  note first.
- Blocked by: none. First step is Route 3.

#### game-shape-capture — `#455` FIXED UNDER A LOGGED CLAIM OVERRIDE `[2026-08-16 ~20:2x CDT]`

**Override taken on explicit user instruction** — "take the override and fix it - i dont think its actually being worked on by any other lane" — on `syndicate/features/wnba/cards.py`, ONE function (`build_live_pbp_stats_payload`). Recorded in `wnba-live-tier`'s own Files block, phrased as a release the guard recognises rather than bypassed. Coordination had been attempted three times: fork 2 archived before replying to two handoffs; a third went to fork 4 (running) and is unanswered.

**THE FIX, two halves:**
1. The stored-payload short-circuit required `bool(games)` — and a skeleton HAS games. Now requires `any(_has_pbp_signal(g))`.
2. The skeleton was PERSISTED, which is what made it sticky: the stored copy then satisfied the short-circuit on every later request. Now gated on the same predicate, so it can never be written.

**FOUR SIGNAL SOURCES, and the fourth was missing from my first attempt.** The existing `test_live_pbp_stats_payload_uses_local_snapshot` stores a real snapshot whose games carry ONLY `pbp_recent.points_total` (9 and 14). My predicate ignored `pbp_recent`, rejected that snapshot, and the test failed. **The suite caught a genuine gap in the fix, not a stale expectation.** Its own trap: the skeleton hardcodes `window_sec: 180`, so counting that field would make every skeleton read as real and silently undo the change — excluded explicitly, pinned by a test.

**THE `Mapping` NEAR-MISS, AGAIN, IN THE SAME FILE.** My first draft used `isinstance(x, Mapping)` in a module that does not import it — a `NameError` on the FIRST record, which would have taken the endpoint down. `lanes.md` already records `wnba-live-tier` hitting the identical thing here. Caught the same way both times: by running it.

**TWO VACUOUS TESTS OF MY OWN, CAUGHT BY MUTATION.** W1 (revert the short-circuit to `bool(games)` — the original defect) and W3 (count `home`/`away` as signal) both passed against a broken implementation. A replayed skeleton and a freshly built one are both all-null, so "no signal" cannot tell them apart — the stored fixture now carries a sentinel and the test asserts its ABSENCE. W3 was the same vacuity already fixed once this session in `scripts/wnba_pbp_possessions.py` and reintroduced here. **After fixing both: 5 of 5 mutations fire.**

**13 tests green. Full WNBA suite: 405 passed, 4 failed — all 4 PRE-EXISTING**, verified by re-running against `origin/main`'s `cards.py` (4 fail there too). My one real regression was the `pbp_recent` gap and it is closed.

**NOT DEPLOYED.** No deploy requested. The fix changes what a live endpoint serves; it needs a web deploy to take effect, and that is a decision, not a formality.
