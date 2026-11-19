# Findings 2026-11-18 — two suspected scorecard grading defects (todo #848)

Lane `scorecard-grading-defects`, session 3095af15. Hypotheses H-S and H-N were written into the lane
(`9ff9649db`) before any test. Substrate: the FLEET's disk (`~/syndicate-prod/data`, read-only, nice 19) and
api-web.nhle.com; graded with the production settlers from this checkout. Scripts: `C:/tmp/g848/*.py`
(nothing in `C:/tmp/optprog` was edited). Every count below names its window.

## Verdict

| | suspected | found | fix |
|---|---|---|---|
| Soccer props (M2) | DNP / void graded as loss | **FALSIFIED for the bulk.** DNPs are voided (6,601 `dnp_void` in 4 board dates); the box is internally consistent; starters who played 60+ min show the same shortfall; an independent settler (NHL goals pregame) shows the same shape. The -55% is the real return of one-way prop ladders at the recorded prices. What is wrong is the cell's **market EV**: the one-way `book_margin_model` fair assumes ~7% margin. **One real defect found on the way:** goal-scorer rows ignored their side, so every `no` graded as its `yes`. | `soccer/2`: settle on the row's own side (default-off, §3) |
| NHL live goals (M3) | priced after the goal they settle on | **CONFIRMED, refined.** Only 3 of 782 ev10+ rows were sighted after their DECIDING goal, but **780 of 782 were priced on a quote their own book never returned after puck drop** (the other 2 were last seen before the sighting; 0 were seen at or after it). BetRivers' pregame "2+ goals" prices were the live best price. | `nhl/2`: void a live row whose own book quote was unseen in the 300 s before its sighting (default-off, §3) |

## 1. Soccer board player props (M2)

**Replay.** `C:/tmp/g848/soccer_replay.py` picks rows exactly as `grade_population` does (earliest sighting per
(sport, k, phase), every board date folded) and grades them with `SoccerPopulationSettler`. Board dates
11-07..11-10: 46,570 player-prop rows -> loss 27,819, win 4,645, `player_not_in_box` 7,489, `dnp_void` 6,601,
`player_ambiguous` 16.

**DNP is not settled as a loss.** `_settle_goalscorer` / `_settle_player_stat` return `dnp_void` when the
box's `appeared` is false, and 6,601 rows took that path. Unused substitutes carry `appeared: false,
minutes: null` in the ESPN box (Brighton v Brentford 11-08: Kadioglu, Svoboda, Steele, Hadjam).

**The box is consistent.** 101 final matches, 11-06..11-11, 10 leagues: 0 boxes with zero player shots; player
shots sum to the team `Shots` stat (Standard Liege v Waasland-Beveren 23 = 15 + 8); mean player shots per match
23.6 (Ligue 1) to 32.2 (Bundesliga). Goal-scorer rows cannot drift from the score by construction:
`qualifying_goals` refuses unless the goal list equals the score AND the player tallies equal the non-own goals.
Anytime `yes` hit 0.084 over 3,474 rows, about the real per-appearance scoring rate (~2.5 scorers / ~30 players).

**The shortfall is in rows that are certainly graded right.** Starters with 60+ minutes, `player_shots` over:
8,456 rows, hit 0.292 vs fair 0.377 vs price-implied 0.411, ROI -41.1%; pregame and live identical (-41.1 /
-41.1). Conditioning on a full appearance should push the hit rate ABOVE the price; it sits 8.5 pp below the fair
at every fair decile (0.0-0.1: 0.026 vs 0.065; 0.4-0.5: 0.346 vs 0.454; 0.8-0.9: 0.745 vs 0.853; only 0.9+
meets it, 0.926 vs 0.917). Exact-name rows (-42.5%, 7,371) and fuzzy-name rows (-31.3%, 1,085) agree, so it is
not the name join.

**The same shape under a different settler.** The 11-18 optimizer artifact (28 days, 10-21..11-17):
`nhl|goals|full|pregame` -40.0% vs market EV -5.7% (11,049 bets / 192 games, NHL API settler);
`ncaaf|anytime td|full|pregame` -22.6% vs -5.7%. Two-sided cells read ROI = market EV (NBA live points -4.5 vs
-4.2; NFL receiving yards -5.7 vs -5.9; NHL sog live -4.9 vs -4.9). Every soccer prop row is one-sided
(`over` / `yes`) and priced against `fm = book_margin_model`.

**So the realised -55% is the hold of one-way ladders, and the cell's "market EV" is what is wrong.** It is a
fair question (one-way `book_margin_model` margin ~7% against a realised ~45-55%, larger at long prices), owned
by calibration (#847) and the fair lanes (`fair-price-v2`, `syndicate-fair-v1`), not by the settler.

**The defect that IS real.** `_settle_goalscorer` never read the side. `player_goal_scorer_anytime|<p>|full|no|`
graded as its `yes`: on 11-07 Erling Haaland (`no` +100, Pinnacle) and Harry Kane (`no` +161) both scored 0 and
both `no` rows settled LOSS. 152 of 143,878 anytime records in the 10-01..11-18 recorder are `no` (first / last
scorer have none). Small, so it does not move the -55%, but it inverts every row it touches.

**Fixed (`soccer/2`, behind `SYNDICATE_SCORECARD_848_GRADING`, absent = `soccer/1`):** a goal-scorer row settles on its own side; `no` wins exactly when `yes` loses (voids and
refusals unchanged); an unknown side refuses instead of grading as `yes`. The bump makes the scorecard drop and
re-grade soccer only (`model_scorecard.load_state`), and the optimizer and suggested-set states do the same
(which is why it is default-off, §3).

**Noted, not changed:** a substitute who came on after the first goal LOSES first scorer here, and some books
void that case (the settler's docstring already says so). Rows: first-scorer subs with < 30 min, 787 rows, hit
0.005. Separating them needs sub-on minutes against the first goal. Lead only. Also a lead: `ethan mbappe`
(FanDuel, 11-08) had a shots ladder priced like a star striker (over 0.5 at -1500) while his scorer price was
+440. That is an odds-identity question, not grading.

## 2. NHL live goal-scorer rows (M3)

**Replay.** `C:/tmp/g848/nhl_rows.py`, board dates 10-14..11-18, production `NhlPopulationSettler`: 23,658
`goals` rows. Live ev10+ (fp x decimal - 1 >= 0.10): **782 rows / 131 games, hit 0.092, ROI +154.6%, market EV
+181.1%**, against the artifact's 723 / 113 / 0.084 / +152.9 / +174.5 (window 10-21..11-17 by game date). The
box agrees with the play-by-play on every row (0 goal-count mismatches of 9,243 live rows).

**The literal hypothesis mostly fails.** Goal wall-clock times from the in-play recorder's ESPN snapshots (~60 s
cadence) against each row's sighting: 3 of 782 sighted after their deciding goal, 11 without a clock (all wins,
probably the same), 768 open. But 252 rows (89 games) were sighted after the player's EARLIER goal (a "2+
goals" row with one already in), and those carry 76% of the band's units (ROI +366%); the 516 rows whose player
had 0 goals at the sighting return -38.2%.

**The cause: the row's quote was not on offer.** The book quote store is change-deduped, so its end-of-day
last-seen sidecar (`nhl_source/tracking/book_quotes/<date>.state.json`, `[line, price, last_seen]`) is the
staleness measure. Joined per row (`C:/tmp/g848/nhl_last_seen.py`):

| live goals, 10-14..11-18 | rows | ev10+ |
|---|---|---|
| book never returned the quote after puck drop | 5,560 | 780 |
| last seen live, but before the sighting | 1,004 | 2 |
| seen at or after the sighting | 2,679 | 0 |

BetRivers wrote 3,610 pregame and **0 live** GOALS captures on 10-20, 1,963 and 0 on 11-10, while ESPN Bet had
4,152 / 4,923 live and Hard Rock 2,952 (11-10). 312 of the 319 rows priced after the player scored carry exactly
the book's last pregame price. Example (the test fixture): Cole Caufield goals over 1.5, 10-17, sighted
23:53:11Z at BetRivers +480, last seen 22:50:21Z, 25 min before puck drop (23:15:36Z); ESPN Bet quoted the same
line live at +300, last seen 01:20:57Z. The board's in-play window is read on the MARKET's newest prop capture,
not per book (learnings 2026-11-17, `nhl-inplay-props-drop`), so a book that pulled its props at puck drop keeps
its pregame price as the live best price whenever another book has just updated.

**The rule, measured on every NHL live market** (10-14..11-18; void = own-book quote last seen > 300 s before
the sighting):

| market | void rows | void ROI / mkt EV | kept rows | kept ROI / mkt EV |
|---|---|---|---|---|
| goals | 5,506 | -18.1 / +21.4 | 3,737 | -11.8 / -6.6 |
| sog | 2,676 | -4.6 / -4.9 | 7,433 | -5.1 / -4.9 |
| points | 3,300 | -4.0 / -3.9 | 7,201 | -6.9 / -5.8 |
| assists | 2,393 | -4.0 / -4.2 | 7,245 | -8.5 / -5.8 |
| saves | 564 | -4.8 / -4.9 | 996 | -5.7 / -5.3 |
| h2h / spreads / totals | 383 | -43.1 / -15.9 / -6.3 | 3,520 | -0.1 / -6.6 / -0.7 |
| ALL | 14,822 | -9.6 / +5.3 | 30,132 | -7.0 / -5.2 |

In the two-sided cells the stale rows already read like the kept ones (a stale pair cancels), so voiding them is
neutral there; in `goals` they are the whole distortion. 668 rows (mostly h2h / totals) have no sidecar entry
and are kept, counted.

A record-only rule ("the price last moved before puck drop", from `ba`) was rejected: it would void 2,511 rows
that WERE being quoted live (FanDuel 2,066; ROI -5.5 vs -7.2, normal) and miss 541 stale ones.

**Fixed (`nhl/2`, behind the same key, absent = `nhl/1`):** `NhlPopulationSettler` voids a GRADED live row whose own book quote was last seen more than
`LIVE_QUOTE_SEEN_MAX_SECONDS` (300, the board's in-play window) before its sighting:
`live_quote_unseen_at_sighting`. It reads the sidecar through the scorecard's own `fetch_export` (the
`*_source/tracking/book_quotes/*.state.json` allowlist entry; 0.2-2.1 MB per date). `view_from_record` now also
carries `sighted_at` and `bookmaker` (not bucket dimensions; `bucket_ids` unchanged). Unknown (no entry, no
file, an old caller's view) is graded as before and counted, never read as stale. Pregame rows are never checked.

**Not fixed here (a board question, and a betting-path one):** the live board offers a book's pregame quote as
a live price. A per-book seen-age on the in-play window would stop the rows at the source; that touches what the
board offers live, so it is a betting change and a decision for the user. Staked NHL live is about 0 (A-8), so
no live money is known to have taken these prices. The same join should be run on the other sports' live rows.

## 3. Why both fixes ship DEFAULT-OFF, and why loading them is a betting change

The brief said grading changes are not betting changes. This one is, through one channel. A settler version bump
(`soccer/1 -> soccer/2`, `nhl/1 -> nhl/2`) makes `model_scorecard.load_state`, `daily_optimizer.load_state` and
`grade_suggested_set.load_state` drop that sport's graded games and re-grade them from the retained board dates,
10 per daily run (`--max-board-dates 10`, ~36 dates to refill, so ~4 runs). The 11-18 11:30Z optimizer overlay
holds **14 soccer and 5 NHL `edge_shrink` cells** (factors 0.50-0.97: e.g. `soccer|player_shots|full|pregame`
0.974, `nhl|sog|full|pregame` 0.5), and `optimizer_overlay.factor_for_row` multiplies both the board score and
`portfolio_commit._sizing_skill_factor`. While a cell is short of its 60 games / 5 dates it leaves the overlay and
its rows go back to factor 1.0: larger stakes on soccer and NHL rows for a few days. That changes how live bets
are sized, so it is a betting change (CLAUDE.md 2026-11-16), and it loads only in a betting-change window.

And it would load early if it landed switched on: the job runs from the fleet checkout (`local_production.py`,
`cwd=REPO_ROOT`), so the next fast-forward by ANY lane would ship it at the following 11:30Z run. So both fixes
sit behind ONE key, `SYNDICATE_SCORECARD_848_GRADING` (on / 1 / true / yes). Absent, the code grades exactly as
`soccer/1` and `nhl/1` did, the versions stay `soccer/1` / `nhl/1` (no reset), the NHL settler reads no sidecar,
and the scorecard keeps exactly its old record fields. The `view_from_record` keys are additive and read only by
`nhl/2`. The core grader signature is unchanged (`7fed663d478b` in both A/B runs), so no other sport resets.

**The scorecard strips `bk` (found by the first A/B, fixed).** `model_scorecard.merge_board_date` keeps only
`KEEP_FIELDS`, which did not include the bookmaker, so with the settler on every pending NHL row reached `nhl/2`
as "unknown" and the first read-only run moved NO NHL cell. With the switch on, `strip_record` now also keeps
`bk` (`KEEP_FIELDS_848`); a test through `merge_board_date` fails without it. Rows of games still PENDING when the
switch turns on were stripped before it, so they carry no `bk` and grade as before (counted as unknown): about
one to two days of NHL games.

**A refill commits games before their later board dates arrive (an existing scorecard defect, not fixed here).**
`model_scorecard.grade_pending` commits any game whose kickoff has passed and that shows no not-final reason; it
does not wait for the board dates that still hold the game's records. After a version reset the refill fetches
today + yesterday + the 8 OLDEST incomplete board dates per run, so a soccer game (recorded up to 7 days ahead)
commits on its look-ahead sightings, and its game-day pregame and LIVE rows then arrive `late` and are dropped.
Measured on the first A/B (5 passes of 10 board dates, the daily job's refill): the same 448 soccer games on the
same 19 dates as production, but 41,516 graded rows against production's 170,978, and `player_shots` live 783 rows
/ 7 games against 25,549 / 267. NHL has no multi-day look-ahead and was unaffected (192 games, 75,715 rows,
identical to production). **So switching `soccer/2` on and letting the daily job refill would gut soccer's live
history for four weeks.** The load must refill in ONE run (`--max-board-dates 40`, every retained board date
fetched before anything is graded, as the single-pass A/B in §5 does), or `grade_pending` must first learn to wait.

To load (a betting change; the user's call; in a window): put `SYNDICATE_SCORECARD_848_GRADING=on` in
`~/syndicate-prod/local_production.env` (the job gets refresh-worker's env, built only at `up`), drained down/up,
`betting_change.py add --kind yes`, then ONE manual scorecard run with `--max-board-dates 40 --publish --verify`
(it reads every in-season sport's parts for ~36 dates through web's stream route: run it off-peak, inside the
window). Verify: the `GRADER` log line reads `soccer/2` and `nhl/2`; `STATE ... reset` names soccer and nhl; nhl
carries `extra_live_quote_unseen_at_sighting`; soccer's 28d coverage stays near 171k graded rows; the overlay's
14 soccer + 5 NHL cells are present on that run's overlay.

## 4. off != on

`tests/test_population_outcomes_scorecard_848.py`, on REAL rows (Barcelona v Racing 09-16 soccer fixtures; the
Caufield and Suzuki 10-17 recorder rows and their state entries), each fix shown both ways through the same code:
switch on (fixed) and absent (exactly the old grading: the Caufield row WIN, the sidecar never read; Olmo's `no`
LOSS). The versions move only with the switch (`off`, `0`, empty, `no` all keep `/1`). Before the switch was
added, the same tests against `origin/main`'s three modules failed 16 of 17 (the DNP void passes under both). The
stripped-state reachability test fails with HEAD's `model_scorecard.py` (no `bk`) and passes with the fix.
Neighbours pass: `test_population_outcomes_soccer.py`, `_nhl.py`, `_basketball.py`, `test_bucket_search.py`,
`test_model_scorecard.py`, `test_publish_model_scorecard.py`, `test_daily_optimizer.py`, `test_sim_gap_ev_study.py`,
`test_grade_suggested_set.py`, `test_score_ranking_backtest.py`, `test_optimizer_overlay.py`, `test_skill_overlay.py`,
`test_bet_status_nhl.py`, `test_soccer_settlement_props.py`.

## 5. The scorecard re-run (read-only)

**How.** The REAL `scripts/publish_model_scorecard.main`, unmodified, wrapped by `C:/tmp/g848/scorecard_ro.py`:
every `WebReader` read answered from the fleet's disk, every write redirected to a WSL scratch root, `publish`
refused, and the process run inside a private mount namespace with `~/syndicate-prod/data` bind-mounted
READ-ONLY (a probe write was refused). Fresh state, ONE pass over every retained board date (`--max-board-dates
40`), `--weekly off --simgap off --resamples 200`, one sport per run, nice 19, a 3.5 GB address-space cap.
`old` = this branch's base (`9ff9649db`), switch absent; `new` = the fix with the switch on. The only network
reads: the fleet's public `/api/board/game-chips` and api-web.nhle.com (cached).

**NHL (old reproduces production EXACTLY: 75,675 pooled bets, every cell identical to the 11-18 11:30Z artifact):**

| pooled, 28 d to 11-17 | prod / old | new (switch on) |
|---|---|---|
| `nhl\|goals\|full\|live` ev10+ | 723 bets / 113 g, ROI +152.9%, mkt EV +174.5% | **1 bet** |
| `nhl\|goals\|full\|live` all | 7,854, -13.6% / +11.1% | 3,174, -11.3% / -6.4% |
| `nhl\|goals\|full\|live` ev<0 | 6,943, -31.1% / -5.7% | 3,138, -11.3% / -6.5% |
| NHL ev10+, every cell | 1,084, +111.4% / +145.9% | 322, +36.0% / +95.8% |
| NHL pooled | 75,675, -11.76% / -3.68% | 63,384, -12.47% / -5.61% |
| NHL recommended (published) | 63,413, -11.47% / -2.51% | 52,784, -12.39% / -4.75% |
| `extra_live_quote_unseen_at_sighting` | 0 | 12,295 rows |

The goals cell's realised ROI and market EV now agree in sign and size. Two-sided live cells lose rows but barely
move (sog -5.0 / -4.9 -> -5.1 / -4.9). Pregame cells are untouched (pregame rows are never checked). The NHL ev10+
that remains is mostly `nhl|totals|full|live` (124 bets, +34.5% vs +45.0%), partly rows with no sidecar entry;
a lead, not claimed.

**Soccer (old reproduces production: 170,902 pooled bets vs 170,805, the same 448 games / 19 dates; the small
excess is records written after the 11:30Z run):**

| pooled, 28 d to 11-17 | prod / old | new (switch on) |
|---|---|---|
| `soccer\|player_goal_scorer_anytime\|full\|live` | 6,794 / 271 g, hit 0.0926, ROI -44.9% / mkt EV -8.7% | hit 0.0951, ROI -44.6% |
| `soccer\|player_goal_scorer_anytime\|full\|pregame` | 6,713 / 269 g, hit 0.0921, ROI -57.0% / -8.0% | hit 0.0947, ROI -56.7% |
| `soccer\|player_shots\|full\|live` | 25,549 / 267 g, -56.4% / -7.9% | unchanged |
| soccer pooled | 170,902, -43.25% / -7.21% | -43.23% / -7.21% |
| soccer recommended (published) | 82,953, -34.80% / -6.72% | -34.75% / -6.72% |

The soccer cells move only where the `no` rows sit, and only a little: the -55% is not a grading defect, so it
should not move. Raw outputs: `C:/tmp/g848/ab_nhl_single_pass.txt`, `ab_soccer_single_pass.txt`,
`ab_refill_5x10.txt` (the first, refill-order run that exposed both §3 findings), `ab_*_log.txt`.
