# state — basketball

Split out of `state.md` by `scripts/split_state.py`. Bodies are verbatim.
The INDEX of every subject, across every part, is in `state.md`; the
one-subject-one-section rule is global and spans these files.
Same rules as state.md: when a fact changes, EDIT THE LINE.

## [nba-betting-card-assets-404] THE NBA BETTING-CARD CSS AND JS WERE 404 IN PRODUCTION -- FIXED, DEPLOYED AND VERIFIED ON THE SERVED PAYLOAD `[2026-09-05, lane ci-archives-nba-card-js, commit ba84b331, web 337facdc live 20:35:00Z]`

**Measured on production, `syndicate-an21.onrender.com`, 2026-09-05:**

    404      0 bytes  /nba/assets/betting-card-v2.js
    404     30 bytes  /nba/assets/betting-card-v2.css
    200 57,864 bytes  /wnba/assets/betting-card-v2.js
    200 17,881 bytes  /wnba/assets/betting-card-v2.css

and `/nba/season/2026/betting-card?profile=retuned&date=2026-06-05` serves
**HTTP 200** while referencing both of the 404s. The NBA season betting-card
page has been shipping with no stylesheet and no script.

**MECHANISM.** `nba/betting_card.py::_artifact_root()` returned exactly ONE
root and preferred `SYNDICATE_NBA_ARTIFACT_ROOT`, which `render.yaml` points
at the DISK -- `/opt/render/project/data/nba_source/source_artifacts` -- on
all three services. But `betting-card-v2.{css,js}` are git-tracked under
`data/nba_source/web/` and are in NO publish allowlist, so nothing ever copies
them onto a Render disk. **On Render the only copy is inside the ephemeral
checkout.** The lookup asked the one location the files can never be in, and
had no second candidate to fall through to.

**WHY WNBA IS FINE AND IS NOT A COUNTEREXAMPLE:** its copy is VENDORED into
the code tree at `syndicate/static/wnba/` and never depended on a root at all.
Two sports serving the same-named asset by two different mechanisms is what
made the difference legible -- read them together or NBA's 404 looks like the
route being wrong.

**THE PAGE HAD BEEN ANNOUNCING THIS ALL ALONG AND NOBODY READ IT.** Its asset
URLs carried `?v=1`. `1` is `source_betting_card_asset_version`'s literal
both-files-missing fallback -- every healthy stamp is a 19-digit mtime in ns.
A version string is a liveness signal here, not decoration.

**FIX (`ba84b331`).** `_artifact_roots()` returns candidates in preference
order and `source_web_text` resolves PER REQUESTED FILE across them, which is
what `source_roots.py` prescribes in its own comment.
`SYNDICATE_NBA_ARTIFACT_ROOT` stays FIRST, so anything that resolves today
resolves to the same file; the added candidates are `preferred_source_roots`
-- already used by `nba/sources.py` in the SAME package, which made
`betting_card.py` the package's lone hand-rolled resolver -- plus the checkout
as an unconditional last resort.

**VERIFIED LOCALLY UNDER PRODUCTION'S ENV SHAPE** (disk root with no `web/`,
assets in the checkout), same process, only the resolver varying:

    pre-fix   404      0 / 404     30 bytes   ?v=1
    post-fix  200 63,549 / 200 17,881 bytes   ?v=1781897524631551600

The pre-fix column reproduces production's numbers EXACTLY, including the
30-byte CSS body and the `?v=1`. Post-fix the served JS carries the rewritten
`/nba/api/season/` and `/nba/cards?date=` routes and none of the stale
`/betting-card?date=` form. Mutation-checked, 3 mutations, each red exactly
where predicted.

**DEPLOYED AND VERIFIED -- NOTHING OWED `[web `337facdc`, live 2026-09-05
20:35:00Z, `dep-dae7napt0dsc739580c0`]`.** Same probe before and after:

    before   404      0 bytes  .js      404     30 bytes  .css   ?v=1
    after    200 63,536 bytes  .js      200 17,881 bytes  .css   ?v=1788640200000000000

**Checked that it is the REWRITTEN asset, not merely some file** -- a root fix
could plausibly serve the un-rewritten source and a byte count would not tell:
`/nba/api/season/` and `/nba/cards?date=` present; bare `/api/season/`,
`/betting-card?date=` and `/live-player-props-audit?date=` all absent.

The failure branch was pre-registered here BEFORE the deploy -- *if it stays
404 the assets are on no candidate root on Render and the move is to vendor
them the way WNBA does, not to add a fourth root* -- and did NOT fire. Kept
because it is still the right next move if this ever regresses.

**SIDE EFFECT WORTH NAMING.** These assets now honour `SYNDICATE_DATA_ROOT`,
which they never did -- removing
`test_nba_betting_card_js_rewrites_source_routes_to_syndicate_paths` from the
nine tests `session_worktree.py` documents as ignoring that variable. See
`[ci-suite-red-test]` in `state_ledger.md` for why that mattered.
## [wnba-live-lens-directory] THE WNBA LIVE-LENS READERS OPENED THE WRONG DIRECTORY — fixed and verified locally, NOT DEPLOYED `[verified 2026-08-31, lane wnba-accuracy-assessment, commit 9dbb870d]`

**Root cause, confirmed against LIVE Render config rather than inferred.**
`WNBA_LIVE_LENS_DIR=/opt/render/project/data/wnba_source/source_artifacts/data/live_lens`
is set on **both refresh-worker and web** (read via the Render env-vars API this
session). The vendored writer honours it
(`vendor/wnba_betting_repo/app.py::_live_lens_artifacts_dir`). Every
Syndicate-side reader built `.../data/**processed**/<file>`. Both halves were
internally consistent and never pointed at the same directory — and
`data/processed` is the writer's DEFAULT when the env is unset, which is exactly
why this reads correctly on a laptop and returns nothing in production.

`live_lens_local::_artifact_path`'s single-`Path` branch returned
`root / filename` **with no candidate search at all**, which is where it bit
hardest: four WNBA accuracy modules pass a bare `processed_root()`. They now
pass every candidate root (`#309`).

**FIXED:** NEW `syndicate/features/shared/live_lens_paths.py` resolves live-lens
filenames against the `live_lens` sibling of `data/processed`, and against
`<SPORT>_LIVE_LENS_DIR` when set — matched on the sport in the ROOT PATH, so a
WNBA read can never resolve against MLB's env (a filename carries a date but not
a sport, and a cross-sport hit would be silent). Additive: it can only turn a
miss into a hit, and CSV resolution is byte-identical.

**VERIFIED END-TO-END on REAL production files** (signals pulled off Render,
recon built from ESPN), in a temp tree with the production layout:

    old rule path exists  False   ->   new rule path exists  True
    one date   signals.exists true, recon all true,  n_settled  54   (was: payload None)
    14 days                                          n_settled 631
    by_period  Q1 55.1% (n=456) -> Q2 78.8% -> Q3 78.1% -> Q4 98.0%
    self_priced_excluded                                        701

**The last two reproduce `[wnba-live-edge-is-leakage]`'s independently-measured
numbers EXACTLY, from a different code path.** Two graders agreeing is the
evidence here, not either one alone.

**NOT DEPLOYED.** Production still reads the old paths and still returns zero on
every WNBA accuracy surface. The recon files exist only in a session scratchpad.

## [wnba-recon-producer] `recon_games` WAS WRITTEN PREGAME AND NEVER REWRITTEN; the producer now exists `[2026-08-31, lane wnba-accuracy-assessment, commit 9dbb870d]`

Settlement for every graded WNBA row joins against `recon_games_*.csv`,
`recon_quarters_*.csv` and `recon_props_*.csv`. Measured on production: **4
`recon_games` files in all of production**, and **in every one the outcome
columns (`home_pts`, `visitor_pts`, `actual_margin`, `total_actual`,
`margin_error`) are EMPTY STRINGS** — the file carries `pred_margin` and nothing
ever comes back to fill in what happened. `recon_quarters` has **never existed**.

`scripts/build_wnba_recon.py` is the missing half: outcome-only (it deliberately
does NOT write `pred_margin`, because a producer that writes both is how the
pregame version came to overwrite the outcome one), native ESPN, completed games
only. **DNPs are omitted rather than written as zeros** — a zero would settle
every UNDER on a player who never took the floor. OT periods are not folded into
Q4.

`recon_quarters_*` was **absent from `HOT_ARTIFACT_PATTERNS` while both its
siblings were present**, so once produced it would have sat on the worker disk
and never reached web. Allowlisted with the producer, not after the first
period-total reads zero.

**NEITHER `build_wnba_recon.py` NOR `build_wnba_boxscores.py` IS SCHEDULED
ANYWHERE.** That is the remaining half and it was deliberately not wired:
periodic work on refresh-worker is what `#241` did when it caused a prod restart
loop (~1.4GB headroom), so it needs its own decision and its own measurement.
loop, so it needs its own decision and its own measurement. **The headroom
figure that rule carried (~1.4GB) is STALE — see
`[refresh-worker-headroom-2026-09-02]`; it is ~2.26GB of ANON, and the metric
most people read says 29-99MB.**

## [wnba-consensus-price] BOOK PRICES WERE AVERAGED ON THE AMERICAN SCALE; 43% OF CARD PRICES WERE IMPOSSIBLE `[2026-08-31, lane wnba-accuracy-assessment, commit 697c41f0]`

`_aggregate_game_odds_from_market_rows` took an **arithmetic mean of American
odds** across books for `home_ml`, `away_ml`, `home/away_spread_price` and
`total_over/under_price`. The American scale is discontinuous at ±100: `-110` and
`+110` are adjacent prices about 9 points of probability apart and their
arithmetic mean is `0`, which is not a price.

MEASURED on production WNBA cards: **55 of 128 priced fields (43.0%) were
strictly between -100 and +100** — `-89.125`, `-94.375`, `-62.25`, `-59.14`.
**Every EV computed off those fields was wrong.**

`_consensus_price_or_none` converts each book to implied probability, averages
there, converts back, and **rounds to 2dp** (the round-trip leaves float noise:
`-140` returns `-140.00000000000003`). Vig is deliberately KEPT — this is a
consensus PRICE, not a fair line. Values inside the ±100 hole are **rejected, not
coerced**; coercing one invents a probability. `+100` is the canonical spelling
of even money, because `-100` reads as a favourite at a glance. Lines (spreads,
totals) are linear and keep the arithmetic mean.

**Unit-verified only — no production card has been rebuilt through it, and it is
not deployed.**

## [wnba-two-artifact-roots] THE WNBA ARCHIVE HAS TWO ROOTS AND ONE OF THEM IS UNUSABLE — split on `source_path` before drawing ANY conclusion from a WNBA card `[verified 2026-08-31, lane wnba-accuracy-assessment]`

`/wnba/api/cards` serves from `wnba_source/data/processed/` (Syndicate-owned) or
`wnba_source/source_artifacts/…` (vendor bundle), resolved per requested file by
`#309`. **They are not two qualities of the same data; one of them is not data.**

Graded against ESPN ground truth over 2026-05-17..08-30:

| root | n | Brier skill | AUC | corr(**market line**, actual margin) |
|---|---|---|---|---|
| Syndicate | 106 | **+16.53%** | **0.7631** | **+0.6785** |
| vendor | 79 | **-72.36%** | **0.4018** | **-0.0396** |

**The decisive column is the last one, not the model's.** A real market spread
correlates ~+0.68 with the result. On the vendor root the LINE ITSELF carries no
information about the game it is attached to — those rows are mis-joined at
source. Corroborated by impossible lines concentrated there: |spread| > 20.5 on
9.2% of rows (max **55.0**), totals outside 145–200 on 11.9% (max **253.0**).

Two alternatives were tested and BOTH FAIL: it is **not a side flip** (flipping
`p_home` only reaches AUC 0.598, skill -30.6%) and **not a bad join** (all 74
fallback matches are the same team pair on the same day with minutes of tip
drift, and the fallback rate is equal across roots — SYND 48/107, VENDOR 26/85).
Controlled on the month, July carries both: Syndicate AUC **0.905** (n=26) vs
vendor **0.292** (n=23).

**WHY THIS IS STATED AT THIS LENGTH.** Pooled across both roots the WNBA sim
measures Brier skill **-21.5%**, AUC 0.595 — "worse than climatology, delete it".
Split on the root the same sim is **+16.5%**, AUC 0.763 — the best pregame asset
on the platform. **The first pass of the assessment that produced this line
reported the pooled number.** Any WNBA backtest, calibration fit or promotion
decision that reads `available_dates` and pulls cards without recording
`source_path` will silently mix the two and reach the wrong verdict. August 2026
is 100% Syndicate root; May–July is mixed.

## [wnba-winprob-inversion] THE WIN-PROBABILITY INVERSION ADDED A RETURN FRACTION TO A PROBABILITY `[fixed + deployed 2026-09-01, lane wnba-accuracy-assessment, commit bef61c33]`

`refresh_wnba_oddsapi_props` computed

    win_prob = _clamp_probability(implied_prob + (ev or 0.0))

`ev` is EV per unit staked; `implied_prob` is a probability. **Adding them is a
category error, not a wrong constant.** For a bet at implied probability p with
true probability q, `ev = q*(1/p - 1) - (1 - q) = q/p - 1`, so the inversion is
**`q = p * (1 + ev)`**.

Corroborated by the board's own published aggregates (105 graded rows): mean
implied 0.5265, mean claimed EV +22.7%, mean claimed `p_win` **0.7320** —
`p + ev` gives 0.7535, `p * (1 + ev)` gives 0.6460. Those means are over slightly
different subsets so that is corroboration; the dimensions settle it alone.

**It does not make the number right, only sound.** Realized was 0.4762, so the
edge is still overstated ~17pp after the fix — that residual is the measured
`corr(claimed EV, win) = +0.0466` problem (`todo #615`), which no formula fixes.

**Why it survived:** the expression is exactly correct at `ev = 0`, which is the
case anyone eyeballing it would check. **Worth checking the other sports'
producers for the same shape** — `refresh_nba_oddsapi_props` has the parallel
`_clamp_probability` chokepoint and was NOT measured, so its formula is unread,
not cleared.

## [wnba-settlement-live] WNBA SETTLES AGAIN — all three causes fixed, deployed and verified on the served payload `[verified 2026-09-01, lane wnba-accuracy-assessment]`

**SUPERSEDES the 2026-08-31 "every instrument reads zero" reading.** Measured on
production 2026-09-01:

    /wnba/api/live-player-props-lens-accuracy
      2026-08-29  n_settled 38    2026-08-30  n_settled 54
      win_rate 0.6415094339622641   recon {games, props, quarters} all true
    /api/ops/wnba/artifact-counts   games.gradeable & props.gradeable  false -> TRUE
    scripts/verify_wnba_settlement_gate.py  exit 0 (PASS) on both dates

`0.6415094339622641` is **byte-identical** to the local end-to-end run built
before any of it deployed. Live-lens signals went `exists: false -> true` on
**14 of 14 days**, **1,814 raw records** — the same count read independently off
the raw JSONL from a different code path.

**THE 0.6889 POOLED WIN RATE IS NOT A PERFORMANCE FIGURE.** It is the clock
leakage documented in `[wnba-live-edge-is-leakage]`, now measured by the
platform's own instrument. The payload says so itself; see that section.

Deployed: web `ad33df21`, refresh-worker + live-odds-worker `1c078f46`. All three
services carry it; both workers run `refresh_wnba_oddsapi_props`, so leaving one
behind would have had one writing slate rows with the corrected probability
inversion and the other with the broken one.

**What is NOT yet in force:** the producer-side fixes (totals withheld, EV
refusal, certainty clamp, the inversion) govern what is WRITTEN.
`p_win`/`ev_pct`/`market` are baked into `recommendations_slate_*.json`, and WNBA
does not rebuild until **2026-09-17**. A read-time clamp covers the display gap
(verified: max `p_win` 0.99, zero certainty claims) but the withholding does not
take effect until a rebuild.

### The three original causes, and what each turned out to be

## [wnba-instruments-all-zero] THE THREE CAUSES, AS FOUND `[historical, 2026-08-31; all three now fixed — see above]`

All six production surfaces return empty over the last 30 days:
`/wnba/api/market-accuracy` (`available: false`, 30/30), `live-lens-accuracy`,
`live-game-lens-accuracy`, `live-player-props-lens-accuracy`,
`live-player-props-audit`, and `/api/ops/clv/report?sport=wnba` (`resolved: 0`,
`openings: 0` — **WNBA CLV has never been measured**).
`/api/ops/wnba/artifact-counts` reports `games.gradeable: false` and
`props.gradeable: false` on 30 of 30 days.

**This is mostly a READER problem, not a missing-producer problem:**

1. **The live-lens readers open the wrong directory.** They report reading
   `…/data/`**`processed`**`/live_lens_signals_<date>.jsonl`. The files are in
   `…/data/`**`live_lens`**`/`. Verified by `artifacts/export?names_only=1`:
   **34 consecutive dates 2026-07-28..08-30 carry 106KB–1.23MB each**, and 14 of
   them parse to 1,814 real signal records. The live sim has been emitting a
   quarter-megabyte a day for five weeks and nothing reads it. **Fixing the path
   backfills five weeks of measurement retroactively — it does not need a game.**
2. **`recon_games_*.csv` is written pregame and never rewritten.** Only **4
   exist in all of production** (05-27, 05-28, 06-21, 06-23), and in every one
   `home_pts` / `visitor_pts` / `actual_margin` / `total_actual` /
   `margin_error` / `total_error` are **empty strings**. The file carries a
   prediction and nothing to compare it to. `recon_props_*.csv`: 33 dates, all
   05-20..06-26.
3. **The boxscore producer died 2026-08-26.** `boxscores_*.csv` runs
   2023-05-05..**2026-08-25** and stops. `scripts/build_wnba_boxscores.py` is the
   Syndicate-owned replacement and already exists.

Also: `/wnba/api/cards` **never marks a past WNBA game final** — all 213 cards
across 93 dates read `status: "Scheduled"`, `final: false`, including May. MLB's
equivalent endpoint does carry finals.

## [wnba-model-vs-board-mismatch] THE WNBA SIM'S ONE EDGE IS THE MONEYLINE, AND THE BOARD BET IT TWICE ALL SEASON `[verified 2026-08-31, lane wnba-accuracy-assessment]`

Measured on the **Syndicate root only** (see `[wnba-two-artifact-roots]`), graded
against ESPN.

**The asset.** Moneyline, n=106: Brier 0.20599 vs climatology 0.24680 (**skill
+16.53%**), **AUC 0.7631**, favourite accuracy 66.98%. Last 14 days (n=39):
skill **+34.50%**, **AUC 0.8413**, 76.92%. Top confidence band **89.7% straight
up** (n=29).

**What the board bets instead.** Of 466 recommendations: PROPS 277, ATS 85,
TOTAL 85, PROP 17, **ML 2**. Graded game lines (n=105): 50-55, hit 47.62% vs
implied 52.65%, **ROI -9.68%** (ATS -10.61% n=51, TOTAL -8.80% n=54). Totals are
not a tuning problem — the sim is a **strictly worse total estimator than the
line it bets into** (MAE 14.23 vs 11.87, corr 0.419 vs 0.581).

**Every stated confidence field is anti-informative and is used to rank and
size.** `corr(prop edge, win) = +0.0002` (n=656); `corr(prop ev_pct, win) =
-0.0157`; `corr(prop p_win, win) = -0.0552`; `corr(board EV, win) = +0.0466`.
Board `p_win` claims 73.20% and delivers **47.62% — overstated 25.58pp**. Prop
tier `High` (n=382) returns **-1.61%** while `Medium` (n=85) returns +15.72%; the
only calibrated band is `p_win` 0.4–0.6 (claimed 0.558, realized 0.563, +12.68%,
n=119). All 466 board rows are `card_bucket: "playable"` (no tiering),
`stake_units` is null on all 466 (no sizing), 36 claim `p_win = 1.000`, max
claimed EV **2264.8%**.

Props themselves are **break-even, not an edge**: n=656, hit 53.96% vs implied
52.17%, gap +1.80pp = **+0.92 SE**; ROI +3.32% ± 3.75pp. Neither significant.

**DO NOT BLANKET-RESCALE THE WIN PROBABILITY.** The implied margin SD in the
mapping is 10.87 against a pooled residual SD of 12.81, and refitting sigma to
18.25 lifts in-sample skill +16.53% → +21.51%. **It fails out of sample:** fit on
the first two-thirds by date (sigma 24.00), test on the last third → **+35.43%
vs the shipped +39.56%**. The overconfidence ratio decays **1.61 (May–Jun) → 1.15
(Jul) → 1.03 (Aug) → 1.02 (last 14d)**; the pooled figure is an early-season
legacy and current calibration is already near-exact. An **adaptive** (trailing
residual) sigma is justified; a constant rescale is not.

## [wnba-live-edge-is-leakage] THE WNBA LIVE ENGINE'S +41% ROI IS AN ARTEFACT — no live line has ever been captured `[verified 2026-08-31, lane wnba-accuracy-assessment]`

1,689 live player-prop signals over 2026-08-17..08-30, graded against FINAL ESPN
box scores (not the in-progress `actual` the record carries). Taken at face value
the engine reads **1249-440, hit 73.95%, ROI +41.18% at -110**. Three independent
proofs that it is not real:

1. **There is no live line.** `line_live_age_sec`, `line_live_span` and
   `line_live_n` are **null on 1,777 of 1,777** player-prop signals.
2. **39.4% of signals are priced against the model's own line.** `line_source` =
   oddsapi 944 / **model 701** / pregame 132. The `model` rows hit **91.21%**,
   and **99.17% in Q4**. It is grading itself.
3. **The hit rate tracks the clock.** On real `oddsapi` lines:
   **Q1 55.87% (n=537) → Q2 60.00% → Q3 75.73% → Q4 88.00%.** A full-game prop
   line from before tip is not purchasable in Q4.

**The only honest cell is Q1 + a real market line: n=537, 55.87%, +6.65% ROI —
+1.62 SE above the 52.38% breakeven. Suggestive, NOT significant.** `win_prob`
claims 0.6693 and realizes 0.5684 (overstated 10.09pp). All 1,814 signals are
`klass: BET` — no tiering, no abstention. Projections run low (Q1 `sim_mu` bias
**-2.240**, `pace_proj` **-1.098**), producing a structural UNDER lean (1,058
UNDER vs 744 OVER).

**A better estimator sits unused in the same record:** `corr(pace_proj, final) =
+0.7493` vs `corr(sim_mu, final) = +0.5611`, and on the honest cell `pace_proj`
picks the side at 56.84% vs `sim_mu`'s 54.72%. But in Q1 `sim_mu` is the better
POINT estimate (MAE 6.636 vs 7.453) and a naive 50/50 blend beat **neither**
(54.72%). Fit the combination; do not assume it.

## [wnba-execution-disconnect] THE WNBA BOARD NEVER SEES THE VENUE IT TRADES ON, AND LAYER 2 NEVER SEES WNBA `[verified 2026-08-31, lane wnba-accuracy-assessment]`

- **Zero Kalshi and zero Polymarket quotes across a full day's 1,115 WNBA Layer 1
  board rows.** The best-price set is draftkings, fanduel, betrivers, fanatics,
  betmgm, betonlineag, williamhill_us, bovada, mybookieag, betus — while **29
  Kalshi and 3 Polymarket WNBA orders have filled**. The surface that picks the
  bet cannot see the price the bet is filled at.
- **Layer 2 excludes WNBA upstream, not on value.** `/api/board/layer2-shortlist`
  reports `active_sports: ['ncaaf', 'soccer']`; WNBA has no `per_sport` entry at
  all. 0 rows on 13 of 14 days; 8 rows on 08-29 (all `game`, **0 `prop`**). Layer
  2 is the only surface that persists what it recommended and can be settled, so
  this is a second independent reason WNBA profitability is unmeasurable.
- **Layer 1 model coverage is 4–6%** — `rows_modelled_fair` is 20–56 of
  522–1,276 rows/day over 13 playing days. For the other ~95% it is a pure
  price-shopping board.
- **Real money, all-time:** wnba **31 settled, $124.96 staked, +$4.09 / +3.31%**,
  14-17 (45.16%). Kalshi 29 orders **-$3.48**; Polymarket 3 orders **+$7.57**.
  The only sport in the black (mlb -13.39%, nfl -4.06%, soccer -46.87%) — and
  **n=31 on $125 is noise; do not scale stakes on it.** Settlement now records
  losses as well as wins, so the wins-only defect in
  `[wnba-game-lines-gradeable]` is closed.
- **43.0% of priced card fields (55 of 128) are arithmetically impossible** —
  strictly between -100 and +100 (`-89.125`, `-94.375`). Averaging American odds
  across books is invalid across the ±100 discontinuity; average implied
  probabilities instead. Any EV off that field is wrong.
- **Schedule (ESPN, verified):** FIBA World Cup break — **no WNBA games
  2026-08-31..2026-09-16**, then **30 games 09-17..09-25**, then playoffs to
  10-20. The absent WNBA quote shard right now (`status: unknown`, "no quote
  shard for this sport and date") is the schedule, not a defect.
- Slate coverage season-to-date: 192 of 277 completed games carded (69.3%); the
  gap is 11 zero-coverage days + 32 partial days, all June/July. **Last 14 days
  is 39/39 = 100% — that gap has already closed.**

Full assessment and the 5-tier plan:
`.syndicate/findings_2026-08-31_wnba_accuracy_assessment.md`.

## [wnba-game-lines-gradeable] WNBA GAME LINES CAN BE GRADED — a player box gives the team score, and always could `[verified 2026-08-28, lane portfolio-venue-and-side-integrity]`

`bet_status_wnba` refused every WNBA spread, moneyline and total since the module
was written, on a REASONED premise in its own source: "this capture is a PLAYER box
and has none [no team scores], so the fix is upstream in the capture". The clause is
true; the conclusion does not follow. **In basketball a team's score IS the sum of
its players' points** — no team-level scoring exists — and `boxscores_<date>.csv`
carries `TEAM_ABBREVIATION` and `PTS`. Nothing upstream had to change.

Derived (sum of player `PTS`) vs ESPN official, 2026-08-25: CHI 81/CON 87, DAL
96/POR 78, PHX 84/WSH 94 — **six of six exact, both sides of all three games**.
Repeated 08-26: `401857176` GS 89 / CON 64.

**WHAT IT COST, and the honest size of it.** WNBA game lines in the live book:
**FIVE, all-time.** One settled — `settled_by=venue`. Two (`GSV @ CON` 2026-08-26,
over and under 151.5) sat ungraded two days because Kalshi did not settle them and
nothing else could. Two are today's and correctly pending. So the value is NOT the
two rows: it is that **1 of 5 got an outcome because the venue chose to settle it
and 1 of 5 did not**, and that coin flip is what goes away. 15 of 20 WNBA orders are
player props, which already worked.

Refuses by cause — `no_final_box_for_date` (wait), `game_not_in_final_box`,
`final_box_roster_too_thin_to_total` (<5 a side is a TRUNCATED capture, and a total
summed off half a roster settles the UNDER on a score that never happened),
`final_box_is_full_game_not_<seg>`, `no_matchup_on_order`. Keyed on the tri-code
matchup because the order carries an OddsAPI hash and the CSV an ESPN id;
home/away re-checked explicitly since `_matchup_key` is a frozenset.

**LANDED (`56426d9a`) AND DEPLOYED** — refresh-worker `73a7e358`, live
2026-08-28T17:26:40Z. **THE PRODUCTION READING IS OWED:** no settlement pass has
run since that boot, so the two rows have NOT yet graded in production (they grade
offline against production's own boxscore rows: over WON, under LOST, total 153).
The STRONGER test is forward — tonight's two 08-28 totals grading
`matched_by: final_boxscore_team_totals` rather than `settled_by: venue`. Repairing
old rows proves the backfill; only the forward reading proves the dependency broke.

**NOT a producer failure.** "The boxscore capture died after 08-25" was my own
wrong reading of `/api/ops/artifacts/export`, which is a DISK read while the
producer and consumer both use `read_text_file` (keyvalue).
`final_player_boxscore?date=2026-08-26&count_only=1` returns `games: 2`.

## [espn-egress-and-wnba-boxscores] ESPN SERVES RENDER FROM ONE OF TWO HOSTS, and the WNBA boxscore had no producer `[verified 2026-08-26, lane kalshi-spread-join-sign]`

**`site.api.espn.com` returns HTTP 403 to Render -- from WEB AND FROM BOTH
WORKERS. `site.web.api.espn.com` does not.** Both serve the same paths. The
403 is the HOST, not egress in general, and the two must never be conflated:
`WNBA_LIVE_BOX_CAPTURED games=3 players=66` proves only the SUMMARY host.
Measured both ways 2026-08-26; the swap produced `{"ok":true,"games":3}` on the
first attempt where the other host had 403'd minutes earlier. Overridable via
`SYNDICATE_WNBA_SCOREBOARD_URL`.

**`wnba_source/data/processed/boxscores_<date>.csv` HAD NO PRODUCER IN
SYNDICATE.** Every caller of the vendor fetcher lives in
`vendor/*_betting_repo/`; `artifact_freshness.py:67` monitored the family with
nothing behind it. Coverage 2026-05 **18**, 06 **0**, 07 **0**, 08 **1**.
`scripts/build_wnba_boxscores.py` is the Syndicate-owned replacement (native
ESPN, `--via-web` for Render), wired beside `settle_orders`.

**WNBA SETTLEMENT WAS WINS-ONLY BY CONSTRUCTION.** `bet_status_wnba` hardcodes
`is_final=False` (the LIVE box carries no game status) and `resolve_bet_status`
decides only on `is_final` OR the value CROSSING -- so an over that fell short
never decided. Production read `wnba 2 settled, roi 115.21, win 100%`: that is
selection bias, not performance. The resolver now reads the final boxscore and
returns `is_final=True`. **NOT YET VERIFIED IN PRODUCTION** -- refresh-worker
was not deployed; `not_decided_yet: 6` is unchanged.

**PUBLISHING IS NOT THE SAME STORE AS THE CONSUMER READS.**
`/api/ops/artifacts/publish` writes `data_root()/path` on WEB'S FILESYSTEM;
`bet_status_wnba` reads via `read_text_file`, i.e. KEYVALUE, on refresh-worker.
84 backfilled files went to production and are invisible to settlement.

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

## [wnba-game-state] WNBA GAME-STATE AND FIXTURE COVERAGE — 2026-08-17 (lane `wnba-live-tier`) — **ARCHIVED 2026-08-19 to `state_archive_2026-08-19.md`, verbatim.**

## [wnba-fixture-identity] WNBA fixture identity + the sweep ownership gap - VERIFIED 2026-08-17 — **ARCHIVED 2026-08-19 to `state_archive_2026-08-19.md`, verbatim.**

## [wnba-sweep-ownership-gate] WNBA SWEEP OWNERSHIP GATE + PHASE 2 AUTORUN `[collapsed 2026-08-18 from three 2026-08-17/18 snapshots; newest reading wins]` — **ARCHIVED 2026-08-19 to `state_archive_2026-08-19.md`, verbatim.**

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

## [wnba-cards-fallback-recursion] `_artifact_bundle` RE-ENTERED ITSELF 247 FRAMES DEEP AND REPORTED NOTHING — FIXED `[2026-09-03, lane wnba-cards-fallback-recursion, no deploy needed]`

`_artifact_bundle` called `_games_from_live_state_fallback`, which called it
straight back; neither is memoised. **Trigger is an EMPTY artifact, not a date:**
no `game_cards_<today>.csv` -> 247 calls / depth 247 / 2 RecursionErrors; ONE row
-> depth 1 and the fallback never runs (back-control confirmed). Disabled on
Render by `_render_web_dyno()`, so it was always a cold/dev path.

Fixed with `_artifact_bundle(..., allow_fallback: bool = True)`; the fallback's
call back in passes `False`. Depth **247 -> 1**, and the failure is now NAMED
(`LIVE_STATE_FALLBACK_FAILED`) instead of swallowed by `except Exception`.
**The cost was never the point (~5.7s); the SILENCE was** — "no cards today" and
"the stack blew" were the same observable, which is how it survived unnoticed.
