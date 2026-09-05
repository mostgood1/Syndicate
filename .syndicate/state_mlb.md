# state — mlb

Split out of `state.md` by `scripts/split_state.py`. Bodies are verbatim.
The INDEX of every subject, across every part, is in `state.md`; the
one-subject-one-section rule is global and spans these files.
Same rules as state.md: when a fact changes, EDIT THE LINE.

## [mlb-hitter-strikeouts-prop] MLB HITTER `strikeouts` WAS A DEAD FIELD FOR MONTHS; FIXED, DEPLOYED AND VERIFIED — AND NO BET WAS EVER PRICED OFF IT `[verified 2026-09-04/05, lanes mlb-hitter-so-dead-field + mlb-ladder-*]`

`_HITTER_PROP_DIST_SPECS` named row_key `"SO"`; the per-sim `hitter_stat_values`
dict — duplicated at `daily_update.py` `_simw_chunk` and `_sim_many` — never set
it, and the read is `.get(row_key, 0)`. So `strikeouts_dist` was `{0: n_sims}`
and `so_mean` `0.0` for EVERY hitter of EVERY game, from at least 2026-05-25.
Third instance of that file's two-copy drift (`#334`, `#429`).

**VERIFIED ON THE SERVED PAYLOAD, both states.** Before: `mean 0.0 / mode 0 /
modeProb 1.0 / maxTotal 0`, one rung `{total: 0, exactProb: 1.0}`. After
`0350dbd2` + a post-deploy sim: **`mean 1.095 / modeProb 0.402 / 5 rungs`**.
Control `prop=hits`, same player, unchanged in both states.

**NO PRICED RECOMMENDATION WAS EVER POSSIBLE, AND IT IS NOW A CODE-LEVEL
GUARANTEE, NOT A MARKET-FEED ACCIDENT.** `PropProjectionIndex.project()` returns
**None** for `batter_strikeouts` on a batter at 0.5 and 1.5 — `_HITTER_BUCKETS`
has 8 entries and strikeouts is not one. The certainty guard was separately
proven live with a positive control (a degenerate `batter_hits` row returns
`model_prob_over_refused: exact_certainty`). Nothing downstream was
contaminated: **no fitted hitter-props calibration artifact exists at all**, and
`props_actuals_2026-09-04.csv` (1,373 rows) carries no hitter-strikeouts market.

**THE MARKET FOR IT IS EMPTY, AND THAT IS SEPARATE FROM THE FIX.**
`oddsapi_hitter_props` requests 7 markets and returns 6: `batter_strikeouts`
present for **0 of 289 players**, against 270-283 for the other six. It IS
fetched and paid for (`DEFAULT_HITTER_MARKETS`) and IS joined
(`ladders_build.py` `hitter_strikeouts`, wired 2026-08-19 by `#440`).

**LADDER CERTAINTY REFUSAL SHIPPED WITH IT** (`fe519fff` + `9b660beb`, both
services live at `50b266da`, verified by content). `_dist_stats` now refuses an
exact `overLineProb` and labels it; the card says why. **SCOPE:** it fires only
with a degenerate histogram AND a market line, so it has never fired in
production and currently cannot — its evidence is 6 unit tests, and an absence
of refused rows is EXPECTED, not confirmation.

**VERIFIED ON TWO INDEPENDENTLY REBUILT DATES `[2026-09-05 05:13:08Z]`.**
2026-09-05 read `mean 0.0 / modeProb 1.0 / 1 rung` for 5h49m after the fix was
live, because its artifacts were written **106 seconds BEFORE** the deploy
(sims 23:24:40Z, ladders 23:20:30Z, deploy live 23:26:26Z) and nothing rebuilt
them. On its FIRST post-deploy build it read **`mean 1.042 / mode 1 /
modeProb 0.428 / maxTotal 4 / 5 rungs`**. 2026-09-04 corroborates across three
post-deploy rebuilds (`mean 1.087-1.095`, 5-6 rungs). **A deploy going live and
the artifact it changes being rebuilt are different events — here 5h49m apart —
so gate any such check on the ARTIFACT'S mtime, never on the deploy.**

**NOT extended to `_dist_ladder`, deliberately:** its `{total: 0, hitProb: 1.0}`
is P(X >= 0) and is correctly certain.

**Gate against regression:** `scripts/sim_input_checklist.py` now asserts
`set(spec row_keys) <= set(hitter_stat_values)` plus two-site drift, before the
roster glob and not gated on `--warn-only`, so it fails the daily job. Note the
REACHABILITY tests do NOT catch the two-site drift — `workers=1` never enters
`_simw_chunk`.
## [mlb-sim-edge-is-anti-predictive] THE MLB SIM'S CLAIMED EDGE IS ANTI-PREDICTIVE, AND THE PROP BOOK IS A REAL EDGE SPENT ON VIG `[verified 2026-09-01, lane mlb-accuracy-assessment]`

**DO NOT STAKE ON `model_edge_pct`.** `corr(claimed edge, win) = -0.1379` over
360 MLB moneyline sides at clean prices. The sim itself carries information
(`corr(sim, win) = +0.2344`) and the market carries more (`+0.3184`), so
`model_edge = sim - market` subtracts the better estimator from the worse and
what survives is the sim's ERROR. Totals: -0.0202 / +0.0331 / +0.1224.
Joining `model_edge_pct` onto more rows makes this worse, not better.

**Games, n=482 finals / 39 dates (2026-06-17..08-30).** ML calibrated (bias
-0.34pp), Brier 0.24307 vs climatology 0.24989, AUC 0.5904. On the 180
clean-priced games the market wins on every measure (0.22663 / 0.6746) and a
50/50 blend does not beat it. On 69 favourite-disagreements **the market is
right 59.4%**. Run totals are calibrated (PIT near-uniform, dispersion 4.821 vs
4.717 needed) with `corr(sim mean, actual) = 0.169` — calibration WITHOUT
information.

**Props, n=8,918 graded / n=7,015 joined to probabilities.** There is NO
comparator sign error: 7,014/7,015 pick over exactly when `model_prob_over >
market_prob_over`. **Inverting does not pay** — as-bet -5.83%, flipped -10.22%
at the measured vig, still -2.55% at a free opposite price, positive in 0 of 8
cells. The defect is CALIBRATION: LogLoss **1.92046** against a Brier of
0.26913, and **993 rows (14.2%) carry `model_prob_over` exactly 0.000** — 992
of them `batter_hits_runs_rbis` — on events the market prices at a median 48%
that go over 45.5%. **Removing them makes the book WORSE (-5.83% -> -6.35%),
so calibrate BEFORE fixing the null.**

**ENTRY COST IS UNIFORM — there are no cheap prop markets.** Vig share on the
quoted price runs **3.07pp to 4.63pp, a 1.5x spread**, and the ordering is the
INVERSE of the pool-based estimate that preceded it (`strikeouts 4.5` is the
cheapest, not the dearest). **A pool-rate-vs-quoted comparison mixes vig with
selection and must not be used for admission decisions.**

**THE BOOK IS A REAL EDGE BEING SPENT ON VIG.** Surviving book (unders, minus
home runs and HRR, n=2,569) priced exactly per row: **+8.48% at zero hold,
+0.98% at today's ~8.1% two-way, +6.52% at a 2% venue hold.** Anchors: ledger
stake-weighted +0.67%, flat-1u reconstruction at the quoted price +1.29%. So
venue economics is the whole lever; market selection is not.

**THE ROI-PER-ENTRY ANCHOR IN THE 08-31 ASSESSMENT IS WRONG.** It says 1pp of
better entry is worth ~**+0.75pp** of ROI, "anchored to item 07's sensitivity";
that table (above) gives **~1.77** — 2.74 points across 4.05pp→2.50pp per side.
**Do not reuse the 0.75, and do not reuse item 05's game-market "+1.57pp ≈
+1.2% ROI" that rests on it** (which has a second defect: it applies a *prop*
book's sensitivity to game-market rows). Corrected at the line in
`findings_2026-08-31_mlb_accuracy_assessment.md` (`17088500`);
`scripts/measure_exchange_prop_option_value.py` now interpolates the published
table with a test on the slope.

**THE EVALUATION AUTORUN IS ARMED (`#626`(h)) — `8e189d1a` LIVE on refresh-worker
2026-09-02T15:29:45Z.** `ACCURACY_SUMMARY_ENABLE_REFRESH_WORKER_AUTORUN=true` set
via the SINGLE-KEY endpoint and read back; a Render env change needs a DEPLOY to
be injected. **It had never run once before this** — the flag was absent, the job
is default-OFF, so the loop `#626` exists to restore produced nothing.
**FIRST FIRE NOT YET VERIFIED.** The gate is 07:00 Central once/day and
`last_epoch` was 0, so it should fire on the first cycle after boot rather than
tomorrow — silence is therefore a signal, not a wait. Read
`reports/refresh_status/latest/accuracy_summary_autorun_status.json`; its
claim-before-work record distinguishes a refused gate from a death mid-pass.
**Env reads on Render MUST paginate** — `?limit=100` is the PAGE SIZE, and
refresh-worker has **153** keys; a single page read as a total is how I briefly
cited 100.

**MLB PLAYER PROPS ARE EXCLUDED FROM STAKING** — `commit_portfolio`, env
`SYNDICATE_PORTFOLIO_EXCLUDED_FAMILIES`, default `mlb:player_prop`, refusal
`market_family_excluded`. **VERIFIED IN PRODUCTION 2026-09-01T12:46Z: 1,860
refused against 1,876 MLB prop rows (99.1%), top market `batter_rbis:379`**;
re-confirmed later the same day, **982 `market_family_excluded` refusals** on
`/api/portfolio/paper`.
**`#624` STEP 6 — THE RE-ENABLE GATE — EVALUATED 2026-09-01: NOT MET, ON BOTH
CONDITIONS. The exclusion stays.** The gate needs the surviving book at **≤5%
effective two-way hold** and **≥ +3% ROI**. Exchange price-shopping, measured on
that book (`--book gate`, n=653, one date), with the Kalshi multiplier
**RESOLVED per series** so it is a point estimate and not a bound:
**+0.949pp entry → 6.2% hold → +2.65% ROI. Shortfall 0.35 ROI points.**
**The hold is the binding condition** (at ≤5% the table already pays +3.72%).
One date — re-measure over a week before anything is sized on it.

**KALSHI `fee_multiplier` IS PER SERIES AND GENERALISES TO NOTHING.** Read live
2026-09-01, **19 MLB series, 0 failures** —
`scripts/read_kalshi_fee_params.py`, re-runnable, because this is venue CONFIG
and can change:
**x0.5** KXMLBGAME KXMLBSPREAD KXMLBTOTAL KXMLBKS KXMLBOUTS KXMLBHIT KXMLBHR
KXMLBHRR KXMLBRBI KXMLBTB KXMLBSB KXMLBF5TOTAL KXMLBF5SPREAD KXMLBTEAMTOTAL ·
**x1.0** KXMLBERA KXMLBHA KXMLBWA KXMLBASGAME KXMLBINNINGTOTAL.
**Every batter-prop series is half rate**, so step 6's m=0.5..1.0 bound is
retired. **Every broader rule is FALSIFIED by this table:** not per sport (five
MLB series are full rate); not props-vs-games (`KXMLBASGAME` is a GAME at x1.0
while `KXMLBGAME` is x0.5); **not per market family** — `KXMLBTOTAL` and
`KXMLBF5TOTAL` are x0.5 while `KXMLBINNINGTOTAL` is **x1.0**, three totals
series at two rates. Three full-rate series sit inside the gate book (*unders
minus HR/HRR*, not *batter unders*).
**REGISTERED != FETCHED:** the first read covered the 14 in
`kalshi_catalogue.SERIES_SPORT` and was called complete; five more are fetched
without being registered there and **two are full rate**. `KXMLBF5GAME` 404s. **Resolving it did NOT close the gate** (+2.66% → +2.65%);
the 0.44-point width was an UNCERTAINTY, not a recoverable gain, and the earlier
note here calling it "worth 0.44 ROI points" was wrong about that.
Justified on the portfolio's own -19.27% ROI / 145 settled, NOT on the
over-side defect — that defect lives in the vendor season betting card, which
grep confirms is **not a staking input anywhere**.

**WEB RUNS `gunicorn --workers 2 --threads 4`** (read from `/api/ops/memory`'s
process list, 2026-09-02) — **two processes, four concurrent requests each**,
NOT eight single-request workers. `ops.py` carried the older "8 gunicorn slots"
figure and I reasoned from it once; `--threads 4` means request handlers can
race inside ONE process, so any in-process lock is not a bound.
**Memory instrument:** `/api/ops/memory` gives `container_memory_mb` (INCLUDES
page cache — inflated by any big-file work and not a leak),
`container_memory_unreclaimable_mb` (**the figure that matters**),
`container_memory_max_mb` 2048, and per-process `rss_mb`. Reading 2026-09-02
00:27Z, 3 min after a deploy: total 1549.2, **unreclaimable 890.4**, workers
410.7 / 507.3. Historical baseline ~750 MB. **A post-deploy reading proves
nothing — every deploy reboots the workers and resets the floor, and the FLOOR
is the ratchet.**

**`book_quotes` DAILY SHARDS ARE NOT APPEND-ONLY — THEY LOSE ROWS. Measured
2026-09-01, mechanism confirmed in code (`#630`, lane
`book-quotes-publish-clobber`).** Two services each append LOCALLY to their own
copy (`odds_book_quotes.append_book_quotes`, `open("a")` — correct), then
`artifact_publisher.publish_hot_artifact` does `read_text()` and pushes **the
whole file**. Separate disks, so **each publish overwrites the other's rows and
web keeps whoever published last.** Two reads of `2026-09-01.jsonl` an hour
apart: **1,318 exchange rows LOST, 0 gained**, clean tail truncation, while
sportsbook rows gained a whole hour. `count:1 truncated:False` — not an export
artifact. Sportsbook scars already present: **no hour 10, no hour 21, hour 15 has
8 rows.**
**THE DAMAGE IS INVISIBLE — every surviving row is real and correctly aligned,
so a clobbered shard still prints a tidy number.** It already produced one wrong
published conclusion: `#624` step 5/6's "67% of exchange quotes had no
time-aligned sportsbook price, plausibly the more liquid subset" was **76% this
defect** (1,365 of 1,795), not market liquidity.
**Before inferring anything from a coverage gap in a shard, compare the two
feeds' time spans, and read the artifact TWICE — if the second read is not a
superset, stop.** `measure_exchange_prop_option_value.py` refuses a date below
65% feed overlap (`51cf8b83`); it refuses 2026-09-01 itself at 46.1%.

**FIXED: MERGE-ON-RECEIVE, and VERIFIED IN PRODUCTION.** `/api/ops/artifacts/publish`
UNIONS an incoming artifact with what is on disk instead of replacing it, in BOTH
receive forms, for THREE families — `book_quotes` (line union, whole-line dedup,
existing file stays a byte PREFIX so the Range/tail pull stays valid),
`odds_history` (union by market key, entries WHOLESALE, never field-mixed), and
the `book_quotes/<date>.state.json` sidecar (union by quote key, newest
`last_seen` wins). **All three run in a SUBPROCESS**, because CPython does not
return freed arenas and a background thread would not have helped.
**READINGS:** superset test 0 lost / 7,104 gained (was 1,318 lost / 0 gained);
prefix invariant 10/10 windows byte-identical while the shard grew; 44 markets
preserved that a replace would have destroyed; `kept_existing_newer=2734` on one
shard — data that would have been overwritten by a STALER publish.
**MEMORY, and it is not our problem:** 775 merges cost +99 MB against +263 MB
from 68 merges pre-change. The residual climb is **`#632`'s ~75 MB/h anonymous
leak** — my 74.4 MB/h and a peer's independently-measured ~75 MB/h agree, and
`9494b9bd` records that the deploy cadence hides it.
**`#488`'s guard also fixed:** it recorded a publisher whose publish it had just
REFUSED, making the refusal a one-cycle delay. Its remaining PER-PROCESS hole is
`#634`.
**`#634` IS NOT MOOT:** 39 path families are published by BOTH workers, none
merged apart from the sidecar. The sweep skips >12 MiB, so big artifacts are
direct-publish only and small ones are contested.

**A WEEK-LONG EXCHANGE-PROP MEASUREMENT IS NOT AVAILABLE UNTIL 2026-09-08.**
Capture began 2026-09-01; 08-26..08-31 carry **exactly zero** exchange prop rows.
`--since/--until` pools dates when they exist.

**EXCHANGE PROP PRICES WERE NOT CAPTURED — a SOURCE gap, not a join. FIXED AND
VERIFIED IN PRODUCTION 2026-09-01 16:11Z.** `mlb_source/tracking/book_quotes/2026-08-31.jsonl`
— 274,129 rows / 124.4MB — held **26,710 exchange quotes on GAME markets and 0
on PROP markets**, because `book_quotes` is fed by OddsAPI and OddsAPI carries
game lines only for exchanges. Kalshi's own prices are now captured directly:
`[kalshi_odds] QUOTE_CAPTURE matches=662 sports=['mlb'] appended=603 no_sport=0`,
**603 PROP rows in the 2026-09-01 shard against 0 the day before**, all stamped
`source=venue_direct`; game rows unchanged at 225 (the capture is bounded to
props — a game row would collide with OddsAPI's copy under `_KEY_FIELDS`, which
has no source term, and the two would ALTERNATE rather than merge). **This makes
the prop side MEASURABLE; it does not show price shopping on props is worth
anything** — that is `todo #624` step 2. The game-market option-value number is
**+1.57pp gross worth `+0.74 ROI points`** `[re-derived 2026-09-01, lane
game-market-entry-roi-curve; the `~+1.2% ROI` first published is RETRACTED]` and
still must not be quoted for props.

Kalshi DOES quote MLB props (23 filled orders, `KXMLB*` tickers). **Until
2026-09-01 those prices reached us ONLY through the direct feed**
(`kalshi_markets.json` -> `kalshi_price_resolver`), wired into `venue_scope` for
paper2 and nowhere else; they now also reach `book_quotes`. On the board as
measured 2026-08-31, exchanges held `best_any_book` on **45 of 97** MLB game
rows and **0 of 103** prop rows — **"join what we already have" was a no-op on
MLB props, which is why step 1 was a CAPTURE and not a join.** The board's
comparison is UNCHANGED by that capture and the 0-of-103 reading still stands:
`quote.book_prices` is what the board reads, and changing it is step 3, gated on
step 2.

## [mlb-live-edge-forbidden] TWO STANDING CONSTRAINTS ON ANY MLB LIVE-EDGE WORK — lifted out of lane `live-prob-producer-reader-gap` when it closed `[2026-09-01]`

**Recorded here because the lane that held them is CLOSED and a constraint that
dies with its block is not a constraint.** Both are to be surfaced BEFORE any
live-edge work, not discovered during it.

1. **A live-edge attempt was SHIPPED AND BACKED OUT.** It priced
   `modelProbOver`, **bit-identical to the PREGAME probability on 24 of 28
   rows**; three props whose over had ALREADY WON still read 0.659 / 0.655 /
   0.745, producing +36.5% / +32.3% / +15.8%. Mean |edge| on decided rows
   **28.2% vs 12.0%** on undecided — **fabricated numbers twice the size of real
   ones, sorting straight to the top of an edge-ranked board.** Treat as a
   standing decision.
2. **The live model TRAILS the market**, measured by `live-game-line-projection`
   (CLOSED) on **8 of 9 scored dates**. **A live edge computed against a model
   that trails the market is a false edge.** Even a clean keying fix does not by
   itself make live opportunities safe to place.

## [mlb-exchange-shopping-value] EXCHANGE PRICE-SHOPPING IS WORTH `+0.74 ROI POINTS` ON GAME MARKETS AND `+2.43%` ON THE PROP GATE BOOK — both re-derived, both smaller than first published `[verified 2026-09-01, lane game-market-entry-roi-curve]`

**GAME MARKETS.** n=621 settled MLB game-market paper orders, 2026-08-22..08-31.
Three anchors bracket: ledger stake-weighted **+6.14%**, flat-1u at the quoted
price **+6.03%**, curve at the measured cost **+6.03%**. The book already enters
at **0.883pp per side**. Curve: `0.00pp → +8.21%`, `0.88 → +6.04`, `2.50 →
+2.50`, `4.05 → −0.46`; slope **+1.91** (2.50→4.05pp), **+2.45** (0→1pp).
Exchanges make **+1.579pp** available on this book's own rows; **+0.977pp is
already banked** and of the **+0.602pp** residual **63.7% sits at books with no
execution path**. Priced per row (n=551): no-exchange +4.49% → actual +6.69% →
best execution venue **+7.43%** → best any book +8.45% → fair +8.98%. **The
claimable figure is +0.74 points**, stable at +0.72..+0.77 across 15/30/60/120-min
windows. Machinery `scripts/measure_game_market_option_value.py` (+38 tests, 11
mutations each caught).

**The `~+1.2% ROI` in the 08-31 assessment is RETRACTED**, wrong three ways: a
`0.75` slope constant contradicting the table it cited (~1.77); a PROP book's
curve priced against a GAME measurement; and `+1.57pp` being **ONE DATE**
(2026-08-31 reproduces at n=13,344 / 52.4% / median +0.232pp against a published
13,093 / 52.5% / +0.240pp; pooled over ten dates it is **+1.101pp**). **The tell
needed no machinery: +1.57pp exceeds the 0.883pp of entry cost the whole book
pays.**

**PROPS, `#624` step 6 — STILL NOT MET on both conditions.** Re-measured on the
HEALED 2026-09-01 shard (`e78aee52` live on web; the date passes its own guard at
**100.0% matchable**, was 46.1%): gate book **n=1,235** (was 653), gain
**+0.824pp** (was +0.949), two-way hold **6.5%**, **ROI +2.43%** (was +2.65%),
shortfall **0.57** points (was 0.35). All props n=3,774, gross 70.1%/+1.709pp,
fee-aware **52.2%/+0.985pp** — which now sits almost exactly on the game-market
52.5%. **Repairing a file that had LOST rows made the exchange look WORSE**:
rows before the clobber's cutoff take it 64.5% of the time for +1.021pp, the
restored rows 40.2% for +0.737pp.

**LEVEL vs SLOPE — do not spend the level.** Settlement is `settled_by =
inferred`; real money ran **−5.5%** over adjacent days against paper's +9.4%.
Ten dates is not a rate. 308 of 929 orders are unpriced and returned **+15.85%**
against the priced rows' +6.14%, which plausibly OVERSTATES the residual.

## [mlb-live-lens-accuracy-refuses] THE MLB LIVE-LENS GRADER SETTLED FROM A RUNNING TALLY; it now refuses, and reads EMPTY because its feed never reaches web `[verified 2026-09-01, lane mlb-accuracy-assessment, commit 4b8d5436]`

**`/mlb/api/live-lens-accuracy` WAS FAIL-UNSAFE.** Pooled 2026-07-01..08-31 it
reported `over: 0 wins / 1,578` and `under: 206 / 206`. When the statsapi feed
was unavailable the grader fell back to `lastSeenSnapshot.actual` — the stat SO
FAR — so at a line of 0.5 an early tally of 0 graded every `over` a loss and
every `under` a win. A snapshot carries `actual` / `actualSoFar` /
`modelMean` / `liveProjection` and **no game state**, so in-progress and final
are indistinguishable there and both are now refused.

**THE FALLBACK WAS THE ONLY PATH THAT EVER RAN: `feedResolved = 0` on all 11
days that produced rows, against `feed_live_miss: 1,802`.** The cause is that
`data/raw/statsapi/feed_live/` is **not in `HOT_ARTIFACT_PATTERNS`**, so the
feed never reaches the web service that serves the endpoint.

**Post-fix, verified on the served payload:** `by_klass` is EMPTY, 0 of 61 days
available, `snapshotActualNotFinal: 1,784` (= 1,578 + 206 exactly), 11 days
carrying `snapshot_actual_not_final:N`. **MLB live accuracy remains
UNMEASURABLE; the endpoint now agrees with that instead of contradicting it.**

**SCHEDULED DEFECT, NOT FIXED:** `live_lens_daily_accuracy.py:207-211` falls
back `entry.marketLine` -> **`last_seen.marketLine`** -> `first_seen.marketLine`
— the LATEST line rather than the line at signal time. Unreachable while the
outcome-side refusal returns 0 rows. **It comes due the moment `feed_live` is
published; whoever takes that decision must fix it in the same change.**

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

## [mlb-sim-artifacts-live] WEB `055dfc67` — THE FIVE MLB SIM ARTIFACTS ARE IN PRODUCTION `[2026-08-18 22:54:51Z]` — **ARCHIVED 2026-08-19 to `state_archive_2026-08-19.md`, verbatim.**

## [mlb-sim-log-unreachable] RETRACTED — THE SIM LOG *IS* REACHABLE REMOTELY `[2026-08-19]`

**THIS ENTIRE FINDING IS WRONG AND IS RETRACTED.** The body is kept below only so
the mistake is legible; **do not act on it.**

*(superseded body archived in `state_archive_2026-09-03.md`)*

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

## [mlb-live-lens-row-shape] The live-lens report has TWO writers and TWO row shapes — verified 2026-08-26 (lane `mlb-chip-live-state`)

**`live_lens_report_<date>.json` is written by two producers over one path, and
they do not agree on the row shape.** `live_lens_loop` writes the FULL shape —
20 keys per row, including `matchup.score` and `gameLens[0].progress`.
`scripts/refresh_mlb_oddsapi.py` fetches `/api/cron/live-lens-reports?slim=on`
and writes `{gamePk, startTime, status}` only; its own docstring says so, and
`slim=on` is deliberate (commit `5c12acf2`, a full slate payload caused a prior
incident).

**The served copy flips continuously.** Sampled every ~50s on 2026-08-26:
`22:39:26Z` SLIM, `22:40:48Z` FULL, `22:41:57Z` SLIM — and that last one carried
a `generatedAt` **2m38s EARLIER** than the FULL it replaced. An older report
overwriting a newer one, not merely a poorer one.

**A SLIM ROW IS NOT AN ANSWER, AND IT USED TO PASS FOR ONE.** It carries
`status`, so `abstract`/`detailed` are populated and any guard keyed on those is
satisfied. `_mlb_live_lens_state_from_row` returned non-None with
`away_pts`/`home_pts` None and no inning; `#413`'s consumer contract reads
non-None as "covered", so `_apply_mlb_live_scores` skipped statsapi for the
WHOLE slate and zero-filled. Measured: SLIM current gives 6 of 8 non-pregame MLB
chips `0-0` with a bare `LIVE`/`FINAL` token on both serve paths; FULL current
gives 8 of 8 exact against StatsAPI. Fixed in `58be8c0d` (`todo.md #581`); the
writer race itself is `#582` and is NOT fixed.

**HOW TO READ A LENS-SHAPE MEASUREMENT.** The shape sampled through
`/api/ops/artifacts/export` is **web's** copy. Each service holds its own, so a
SLIM reading on web says nothing about what refresh-worker's chip build saw. Any
before/after on this must name the service AND the serve path (`source` on
`/api/board/game-chips`), not just the shape.

**`scripts/pending_deploys.py` does not know refresh-worker executes
`syndicate/blueprints/home.py`.** It listed a `home.py` commit as pending for web
only. `pipeline/layer2_shortlist.py:511` calls `build_game_chips`, which imports
`home.py` to register the sport providers. Do not use that tool as a coverage
answer for this file.
