# state — layer2

Split out of `state.md` by `scripts/split_state.py`. Bodies are verbatim.
The INDEX of every subject, across every part, is in `state.md`; the
one-subject-one-section rule is global and spans these files.
Same rules as state.md: when a fact changes, EDIT THE LINE.

## [layer2-board-keyvalue-ceiling] THE BOARD'S CEILING IS THE COMBINED KEY, NOT THE SHARDS — and `per_sport=3000` corrupted production for ~29 min `[verified 2026-08-31 18:25-20:0xZ, lane layer2-cap-raise]`

**Rows are sharded per sport and the merge SERVES the board.** `combined_keeps_rows=False`
on the writer while web served 1,634 rows — an empty combined key cannot otherwise
yield rows. Board 932 → 1,634 at `per_sport=1000`.

**`per_sport=3000` BROKE IT.** The combined key carries card/metadata that scales at
~2,200 B/row **even with `rows: []`** (3,754,595 B at 1,634 rows; 9,648,192 B at
4,552). The write refused at `9,648,192 > 8,388,608` **after the shards had already
landed**, freezing `shard_row_total=1635`; the merge then dropped
`unplaceable=2917` rows and **all of NCAAF**, for ≥3 cycles. It does not self-heal.
So the ceiling is **~3,600 TOTAL rows**, not per-sport, and shard headroom says
nothing about it.

**Live config (refresh-worker only):** `SYNDICATE_LAYER2_ROWS_PER_SPORT=1000`,
`SYNDICATE_LAYER2_ROWS_TOTAL=3000`, `SYNDICATE_LAYER2_COMBINED_ROWS=0`. Web and
live-odds-worker carry NO `LAYER2` keys. **`ROWS_TOTAL=3000` is UNEXERCISED** —
today's board is ~1,600 rows, so it has never bound.

**Fixed and live** (`865c89be` 19:46:59Z, still in live `132559e1`): the merge sizes
from `max(index_total, highest_position+1)`, so a refused write leaves the board
STALE not WRONG, and `written_at` comes from the shards when stamps disagree —
without that the corrupted board reported `18:02:05Z` while serving 18:25 rows and
was **unfalsifiable** to any watcher keyed on `written_at`.

**THE FLIP IS VERIFIED IN PRODUCTION `[2026-08-31 22:50:26Z]`.** `cards` split into
per-sport keys makes the combined key FLAT in row count (451 → **0 B/row**,
measured on the real writer). `SYNDICATE_LAYER2_CARDS_INLINE=0` is live on
refresh-worker `7e678674`; web `7e678674` was deployed FIRST and its deployed SHA
confirmed to contain `_hydrate_layer2_cards` (it had ZERO an hour earlier — that
gate prevented a silent `cards_present=0`). Two clean pre-flip cycles passed
(1468==rows, 1498==rows, three sports each).

**EXERCISED AND PASSED** on the first rebuild under the flip: `combined_keeps_cards=False`
with `cards_present=2216 == rows`, all three sports — the writer stopped filling the
combined key AND web served every card back from the shards. The combined key is now
FLAT in row count, so the ~3,600-row ceiling that made `per_sport=3000` corrupt the
board is GONE. **A cap raise is now defensible but UNATTEMPTED, and must be measured
against the COMBINED key, not the shards** — that mistake caused the 18:25Z incident.
The 1534 → 2216 row change is SLATE (soccer 187 → 834), not headroom. **REVERT:** set
`SYNDICATE_LAYER2_CARDS_INLINE=1` and redeploy.

**CAPS NOW STAGED AT 2000/6000, NOT DEPLOYED `[2026-09-01 01:3xZ]`.**
`SYNDICATE_LAYER2_ROWS_PER_SPORT=2000` + `ROWS_TOTAL=6000` are SET on
refresh-worker but the live SHA `6d024dc7` predates them; the 75% warn threshold
(`c461693e`) is on main and also undeployed. Both apply on the next
refresh-worker deploy by anyone. **MEASURED SAFE against REAL production rows —
combined key 220 B (0.0%), worst shard 50.6–55.2%** — which is the check that was
skipped before the 18:25Z incident. **UNTESTED AND UNTESTABLE TONIGHT: the board
is MLB-ONLY at ~547 rows** (slates finished; `LAYER2_BOARD_HEALTH` 01:14:48Z mlb
547, ncaaf 0, soccer 0), so nothing approaches even the OLD 1000 cap. Verifiable
only on a full multi-sport slate. **Two caveats:** the shard percentage is
SLATE-DEPENDENT (same config read 55.2% on a three-sport board, 50.6% on tonight's),
and 3000/sport sits at 74.6% — just UNDER the 75% line, so the warning is NOT a
guard against a 3000 raise.

**ALL THREE INCIDENT DEFECTS ARE CLOSED AND VERIFIED `[2026-09-01 00:15Z]`:** (1) the
refused write that left CORRUPTION not staleness — `865c89be`; (2) the shed that could
not shrink the combined key — cards split + flip; (3) the size instrument that measured
a payload nothing writes — `6d024dc7`, live 23:41:30Z on refresh-worker.
`SHORTLIST_PERSIST_LARGE` is GONE; `LAYER2_KEY_LARGE` reports **one number per KEY** and
names the lever that matches whichever key is biggest. Verified over two builds
(23:54:28Z, 00:15:02Z): both counters 0, `cards_present == rows`. Before the fix it fired
on EVERY build at `88.5 → 90.6 → 116.8 → 122.5` pct on a healthy board, advising a cap
that was not the constraint. **Do not act on any surviving reference to
`SHORTLIST_PERSIST_LARGE`; it no longer exists.** `openings` needs no split — `openings_index` never reaches the artifact.

**The board is GROUPED BY SPORT and always was** (FLOOR-THEN-MERIT, `layer2_board.py:2744`,
`4ef894e3`/#524) — NOT a sharding artifact. Reading `rows[:25]` reads the top of the
FIRST SPORT, not the board.

## [layer2-realized-accuracy] THE LAYER 2 BOARD'S REALIZED ACCURACY — the portfolio book is the surface, and the measurement chain is broken in four places `[verified 2026-08-31T17:3x-18:0xZ, lane layer2-accuracy-audit]`

**START HERE FOR ANY BOARD-ACCURACY QUESTION, NOT AT THE EVALUATION LEDGER.**
`pipeline/portfolio_commit.py:357` commits BOTH the paper and live portfolios
straight off `read_layer2_shortlist`, so `/api/portfolio/paper?date=` and
`/api/portfolio/live` are direct measurements of this board. The evaluation
ledger is the learning loop's INPUT, not the accuracy surface, and it currently
settles 0.2% (19,692 settleable, 35 settled).

**7 days, 2026-08-24..08-30, by bet type (paper):** game_line 142 settled 56.7%
**+25.3% ROI [95% CI +7.2..+43.4]** — the only bucket excluding zero;
game_total 141 / 47.5% / +9.8% [-9.3..+29.0]; player_prop 119 / 37.8% /
**-13.5%** [-33.5..+6.5]. **REAL MONEY INVERTS game_line:** h2h+spreads
12W-23L = **34.3% win, -23.9% ROI**. By sport (paper): mlb 375 settled (93% of
all), wnba 22, soccer 5, nfl 0, **ncaaf 0 — never bet, ever**.

**FOUR BROKEN LINKS, each measured, working backward from the board:**
1. **Board retention is ~4 days.** `/api/board/layer2-shortlist?date=` answers
   `no_shortlist_artifact` for 08-25/26/27. No retrospective longer than that
   is possible.
2. **MLB grading joins ~1 game in 14. FIX IS LIVE AND HAS NOT MOVED THE
   NUMBER. DO NOT RECORD THIS AS FIXED.** `[2026-08-31, lane layer2-accuracy-audit]`
   Baseline across the full window, both disks agreeing: `rows.all` =
   1/1/2/1/1/1/7 for 08-24..08-30 with 0/14/14/6/12/12/13 `Missing game-line
   match` warnings — **14 graded rows total, 71 lost joins.** That supply is
   what starves settlement (19,692 settleable, 35 settled).
   **WHAT IS LIVE:** `49c43aeb` (`_odds_paths` best-found-not-first-found +
   `daily/snapshots/` search), `04185203` (multi-date backfill), `a35591dc`
   (publish the rebuilt payload). `132559e1` (re-run a date that built but
   never published) is on main, NOT live.
   **THE BACKLOG REGRADE RAN AND RECOVERED NOTHING.** All seven dates rebuilt
   `ok=True` 19:03:47-19:08:33Z, each in **0.4-0.9 seconds** reporting
   `cards: 1`. A 14-game slate cannot be joined and graded in 0.4s. `ok=True`
   is an exit code, not a result.
   **WHY THE 14/14 PROOF DID NOT TRANSFER — READ THIS BEFORE TRUSTING ANY
   ARTIFACT-BASED PROOF IN THIS REPO.** The fix was proven on the freeze and
   live docs pulled from `/api/ops/artifacts/export`, **which runs on WEB and
   reads WEB's disk**. refresh-worker has its own disk. The proof established
   "the resolver works given these files present" and was used to claim "works
   on the worker", which was never tested. Presence is not reachability, across
   a service boundary this repo documents.
   **RESOLVED, and the resolver fix WORKS `[verified 2026-08-31 20:33Z]`.** The
   freeze IS reachable on refresh-worker at `daily/snapshots/<date>/`:
   2026-08-30 now reads `(pregame-freeze, 14 games)` with `Missing game-line
   match` **13 -> 0**, and raw moneyline candidates went **1-4 -> 12** against
   three pre-fix control dates. **The graded ROW count did not move (7 -> 7)**
   because `caps.ml = 1` absorbs the whole gain — so my claim that the join
   rate was starving settlement is **FALSIFIED by its own fix**. Graded rows
   come from the locked card, i.e. the policy's picks. See `todo #610`.
   **MLB prop supply is a SEPARATE defect (`todo #611`):** the prop pregame
   seal has produced nothing since 2026-08-16, so hitter/pitcher props grade
   against a post-slate remnant (~1 game). Leading cause **cadence** — measured
   2026-08-31, the MLB refresh ran 22:12:30Z against a 22:05:00Z first pitch,
   so `slate_started` was True and props were skipped by design. Not yet proven
   to be the whole cause. MLB odds refresh runs on **live-odds-worker**.
   **THE READING THAT DECIDES IT** is the always-on diagnostic shipped in
   `49c43aeb`: `Game lines read: <path> (pregame-freeze|live, N games)` in the
   payload warnings. `(live, 1 games)` => freeze unreachable worker-side, fix
   inert in production. `(pregame-freeze, 14 games)` => freeze found, failure
   is elsewhere. **It needs `132559e1` deployed** — the seven payloads carrying
   it were built before the publish call existed and nothing exports them.
   **MARKERS CANNOT BE CLEARED FROM OUTSIDE, measured:**
   `keyvalue/expire-run-artifacts` returns `matched_keys: 1` (surgical) and
   `skipped_no_run_stamp: 1` (refuses — run-stamped keys only); `keyvalue/sweep`
   only touches 10-day-stale keys. Hence the self-heal in `132559e1`.
   **THREE INSTRUMENTS WERE BLIND, all chosen for reachability rather than for
   answering the question:** `/mlb/api/market-accuracy` (wrong disk, and the
   backfill had no publisher), `graded_rows_available` (STALE — `epoch`
   unchanged for ~2h; moves only when the settlement autorun fires), and the
   builder's `stdout_tail` (JSON summary only, no warnings).
3. **NCAAF has never produced a graded row.** `_ncaaf_graded_rows_for_date`
   reads `cfbd_lines_*.json`; zero in the hot-artifact set.
4. **Soccer's biggest board market is ungradeable by construction.** Grader
   covers 3-way ML / totals@2.5 / BTTS; the board's #1 market is
   `alternate_totals_corners`, **573 of 2,623 rows (22%)**.

**THE FUNNEL IS THE OPTIMIZATION TARGET.** Refusals 08-24..08-31:
`no_model_edge_pct` **2,506**, `below_min_ev_pct` 1,567, below_min_stake 46,
zero_kelly 37 — ~4,150 against ~458 orders. Board side agrees:
**`model_edge_pct` is numeric on only 902 of 2,623 rows (34.4%)**,
`model_ev_pct` on 201. `ev_basis` = market_fair 1,451 / model_edge 184 /
model_probability 17 / unset 971 — on a `market_fair` basis the board is a
stale-price detector, not a model-vs-market edge.

**BOARD QUALITY, n=2,623 over the 4 dated snapshots:** books_quoting<=1 on
**1,511 (57.6%)**; book_age median 4,498s, **p90 36,816s (10.2h)**, >6h 21.3%,
`suspect_stale` 8.8%; movement not tracked 42.1%; `ev_pct`>0 on only 444
(16.9%), median **-2.35%**; model_skill measured 625 / unmeasured 882 / no
projection block 1,116. **Composition mismatch:** soccer 51% of board / 1.2% of
settled bets; ncaaf 33% / 0%; mlb 16% / 93%.

**NOT MEASURED, and it is the read that decides how to rank:** whether the
board's own `ev_pct`/`model_edge_pct`/`score` PREDICT the outcome. The
portfolio endpoints serve settlement marginals only (`by_sport`,
`by_market_family`, `by_venue_family`), never per-order rows, so no calibration
curve exists. Exposing settled orders with their board fields is the unblock.

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

## [layer1-board-date-scoping] THE BOARD WAS DROPPING GAMES TWO WAYS — both FIXED AND VERIFIED `[verified 2026-08-30 05:0x-05:5xZ, web+refresh-worker `d7cda903`]`

1. **A 9pm Central game was invisible.** The grid artifact is keyed by **UTC**
   date; the board scopes by **CENTRAL** game date; the read set was window+today.
   `window=day&date=2026-08-29` served **7 games** while
   `book_grid_2026-08-30.json` held Memphis @ UNLV at `02:19Z` = 9:19pm Central
   on the 29th. **7 -> 8 games, `rows_other_dates=0`.** Same game and cause
   `ncaaf/sources.py` already recorded; that fix corrected ONE consumer and the
   board was the second. Rule now lives in `layer1_board.artifact_read_dates`.
2. **Whole slates had no artifact.** `_SLATE_WINDOW_DAYS["ncaaf"]=7` sized BOTH
   display and BUILD; NCAAF week 1 spans ten days, so the last three days were
   unreachable by date. `?date=2026-09-05` **0 -> 67 games / 353 rows**; 09-06
   and 09-07 also reachable for the first time. Split into
   `artifact_window_days` (never below the display window). **The display width
   is UNCHANGED at 7** and `#565`'s per-sport cost pruning survives — three extra
   shard checks for NCAAF, none for any other sport.

## [board-chip-coverage] Layer 2 compact game cards — FULL chip coverage, verified 2026-08-26

Every compact card on the board resolves a live-scoreboard chip, measured from
refresh-worker logs the same evening:

    mlb 400/400   wnba 400/400   nfl 106/106   soccer 400/400

`CHIP_JOIN_COVERAGE` (`pipeline/layer2_shortlist.py`, per sport, every build) is
the instrument. It reports `chips=`, `chip_dates=`, resolution by index
(`by_id` / `by_matchup` / `by_canonical`), plus `needs_fallback`,
`no_chip_available` and `unknown_no_key` with named samples. Before it existed
this defect class was found ONLY by a person looking at the board — twice.

Three causes were closed, all previously invisible:

* **Phase offset.** The chip build resolved ONE matchday per league from
  `default_week(reference_date=today)`; on a Monday that is the matchday just
  played. 65 of 96 chips described finished fixtures. Soccer
  `no_chip_available` 251 -> 0; NFL was the same defect via an exact-date
  filter, 106 -> 0.
* **Two different names for one club.** Normalisation cannot bridge
  "Athletic Bilbao"/"Athletic Club"; both sides now carry `canonical_team`'s
  answer as a join key.
* **Alias gaps**, named by the telemetry itself: soccer `unknown_no_key`
  7 -> 0.

**The horizon is the CALLER's to ask for** (`include_upcoming`, default False).
`provider.games()` serves the home rail (means "today") and the chip strip
(means "the board's forward horizon"); overloading it silently doubled the
soccer home rail 98 -> 210 while fixing the board.

**The alias map has TWO CONSUMERS WITH DIFFERENT REACH.** `teams_match` falls
through to a shared-suffix heuristic; `canonical_team` is map-only and the chip
join calls it directly. A club can join fixtures fine and still return None for
a chip key. The asymmetry is principled: `teams_match` holds BOTH names and
answers "same club?", so a loose rule is safe; the chip index holds ONE name and
must mint a globally unique KEY, where the same rule mints collisions.

**`DIRECT_FEED_BOOKS` needs no widening.** `near_misses={}` across many builds,
one at 27,070 rows — the aggregator uses no spelling the exact match misses.
Reproduced independently by lane `board-staleness-visibility`.

## [chip-artifact-content-age] A chip artifact's TIMESTAMP and its CONTENT age are different numbers — verified 2026-08-27 (lane `mlb-chip-live-state`)

**`/api/board/game-chips` `published_at` bounds when the artifact was WRITTEN,
not how old the live state inside it is.** Measured 00:09:03Z, refresh-worker on
`f8d8b05f`: `published_at` 79 seconds old, content two innings — roughly fifteen
minutes — behind StatsAPI. `BOS` read `TOP 3` against `Bottom 5`; `MIL` read
`BOT 1 0-0` against `Bottom 3 4-0`.

**`#564`'s 120s freshness threshold and the page's stale badge both key on
`published_at`, so BOTH read healthy through this.** Same shape as
`[board-quote-staleness]`. A board build that takes ~750s cold stamps its
artifact at the END.

**THE DISCRIMINATOR BETWEEN A STALE CHIP AND A BLANKED ONE IS THE TOKEN, NOT
THE SCORE.** A blanked game (`#581`) carries `0-0` AND a bare `LIVE`/`FINAL`
with no inning. A stale game carries a real inning that is merely behind. Both
present as "the score is wrong", and reading the score alone gets it backwards
— this was nearly called a `#581` regression off a watcher line that reported
only score mismatches.

**THE CAUSE IS BOARD-BUILD DURATION, NOT THE LENS BOUND.** A first hypothesis
blaming `_MLB_LIVE_LENS_MAX_AGE_SECONDS = 15 * 60` was FALSIFIED the same hour:
one build later, WARM, the same worker with the same bound served an inning gap
of **max 1, mean 0.25 over 8 live games** (`pub=00:15:18Z`). A bound does not
know which build it is in — if it were admitting the staleness, a warm build
would be just as stale. The content is about ONE BUILD old, and this file
already carries the numbers: **cold 747.8s, warm 107.8s**.

**So the exposure is a ~12-minute window after every worker RESTART, not a
standing lag** — and a restart is what every deploy causes. refresh-worker was
deployed three times on the evening of 2026-08-26. Same family as
`[board-quote-staleness]` and `#563`'s deploy-cadence finding.

**Open as `todo.md #585`, not fixed.**
