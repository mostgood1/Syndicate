# Product optimization program — one ranked lever table from Syndicate's own performance data

Lane `product-optimization-program`, session 3bf4646c (started by the rail monitor, `local_62433e58`).
User, 11-18 ~6:05 PM CST, in the rail monitor session: "we need to then take all this data to optimize the overall
Syndicate product".

Substrate: the fleet's disk (`~/syndicate-prod/data`) and `http://127.0.0.1:10000`, read-only, `nice -n 19`. Never the git
`data/` mirror. Times are Central.

## 1. Pre-registration (committed before any lever result was read)

Committed 11-18 6:19 PM CST (`4294294e1`), before the four evidence passes (A scorecard funnel, B live book, C rail flags and cheat
sheets, D engine and input defects) returned anything.

### 1.1 Hypothesis (copied from the lane block)

- **H1:** ranked by EV × confidence, the top levers are per-line calibration and selection (the long-shot tail, I-1; the
  board-to-staked selection gap) and input defects (#844), not new mechanisms.
- **H2:** at most a third of the candidate levers clear the scorecard's FDR + leave-one-date-out bar.
- **Falsified if:** the long-shot tail gap (0.154 hit vs 0.253 fair) loses significance under a game-clustered CI across
  the graded rail days, or more than half of the candidate levers clear FDR + LODO.

### 1.2 What counts as evidence

- Every number carries its denominator: bets or flags, distinct games or events, and dates. It also names its window.
- **95% intervals are clustered by game (event).** A bet-level interval is not accepted.
- **Edge vs noise, two bars:**
  - Benjamini-Hochberg at q = 0.10 over the whole family of slices each pass tested. The family size is stated.
  - Leave-one-date-out: the sign holds with any single date dropped.

  A statistical lever must clear both bars to be ranked for action. One that clears neither, or only one, goes to
  "watch". It gets a forward pre-registration, not a change.
- **Rolling windows are not independent.** The scorecard's 44 daily 28-day readings overlap. Only the newest window and
  non-overlapping windows count as samples.
- **A correctness defect needs no edge test.** Examples: a wrong timestamp max, a duplicated history, a dropped input.
  It is ranked on the money flow it touches and on how far it biases the other evidence. Its fix is still measured.

### 1.3 Ranking rule

- **Score = EV × confidence weight.**
  - EV is the expected value of the fix at today's volume. It is stated in its own units: $/day on the live book,
    units/day on the paper book, or log loss per game for an engine.
  - Confidence weights: high 1.0, medium 0.5, low 0.2.
- **Units are compared in two tiers:**
  - Live-money levers first. Live money is what the scale-up gate reads.
  - Then paper and board levers, ranked within their own tier.
  - EV is never converted across tiers by an assumed exchange rate.
- **Ties:** a lever that also removes a bias from other evidence ranks above one that does not.

### 1.4 Rules every lever obeys

- **Every line is its own decision.** No lever withholds a whole sport, market or price band. A tail or band finding
  becomes a per-line calibration or selection fix: a function of that line's own features.
- **Betting changes load only in windows.** The next is Tue 11-24, 2-7 AM CST (`.syndicate/betting_change_windows.md`).
  A betting change lands on main default-off, or waits on its branch.
- **Any fleet load needs the user's explicit OK,** plus claims and a preflight. A peer session's message is not the
  user's OK.
- **Never act on another lane's files.** Each lever goes to the lane whose goal covers it. A lever with no owner gets
  its own lane, or a todo item when it is not being worked now.

### 1.5 Known defects that bias the data

| id | defect | what it biases | dates |
|---|---|---|---|
| #844 | College live quotes read stale when fresh: `book_grid.py` takes the newest stamp by text | College live rows, so the live gate, rail flags and live college bets | until a fix loads |
| I-25 / #843 | NBA history duplicated (1,563 rows for 196 games), Elo inflated ~119 points | NBA pregame model probabilities | until 11-18 3:02 PM CST (BC-052) |
| I-24 / #841 | Understat down since 11-03; big-5 soccer prices on history frozen at 10-31 | Big-5 soccer model probabilities | 11-03 on |

## 2. Answer (11-18 ~6:50 PM CST)

- **No lever that changes live money clears the evidence bar today.**
  - The live book loses about $3.05/day on $61.75/day staked (since 11-03: −4.94% [−12.15, +2.26], 914 bets / 391
    events / 16 dates). **Venue fees are 78% of that loss.**
  - Picking sides is about break-even: selection at the fill price +0.65 [−8.63, +9.92]. Against a de-vigged two-sided
    close the picks are calibrated (+0.03 pp, 231 bets / 187 events).
  - 0 of 182 live slice tests clear BH, in either window.
  - The sim reaches live money only through ranking (≤ 1.5 EV points on ~$26.90/day of pregame stakes), so **no engine
    fix is worth more than about $0.40/day of live money** today.
- **What does clear the bar is calibration: our probabilities are over-confident, everywhere they are measured.**
  - **The sim's probability vs the fair:** rail flags hit 9.1 pp below the model's own probability [−12.7, −5.3]
    (1,120 flags / 177 games / 3 dates; 27 of 41 slices clear BH, LODO holds).
  - **The optimizer agrees:** 61 of 63 validated cells sit below 1 in both halves of the window. In 28 of them the
    evidence supports more shrink than the 0.5 floor allows.
  - **Our EV at the price we take:** the suggested set promised +3.41% and returned −3.02% [−5.53, −0.50], a gap of
    −6.43 [−8.95, −3.91] (11,748 bets / 1,338 games). Staked orders admitted at 5-7% EV returned −3.60% against +5.11%
    promised, −8.71 [−14.05, −3.37] (2,014 / 721). Realised ROI on admitted EV has slope −0.74 [−3.00, +1.48]; a
    calibrated EV would give 1.
- **So the program has two themes, plus defects.**
  - **T1, EV overstated at the price we take (winner's curse):** a lower-bound EV per line. It is ALREADY
    pre-registered as `decision-policy-paper` P1 `ev_lb` (paper2; no look yet at 133 bets / 101 games), so it is
    handed over, not re-registered.
  - **T2, the model's probability is over-confident:** one per-cell calibration applied everywhere a model probability
    is used: the rail flag, the board's EV, rank and stake, and the shared live probability. It has no owner. It
    replaces backlog I-1.
  - **Defects:** #844, which the user asked for on 11-18; two suspected scorecard grading defects (soccer props,
    NHL live goal-scorers); and the rail monitor's L-d.
- **Hypothesis judged (§5):**
  - H1 is FALSIFIED as written. The long-shot tail gap does not survive pooling: −1.4 pp [−10.7, +8.0], 107 flags /
    37 games, LODO fails. The 0.154 vs 0.253 was one day. The tail is part of a general over-confidence, not a tail
    effect.
  - H2 HOLDS: 7 of 26 statistical levers clear both bars (8 if C-6's ROI counts), all on calibration, accuracy or
    display metrics. None clears on money.

## 3. Ranked lever table

Score = EV × confidence weight (high 1.0, medium 0.5, low 0.2), ranked within each tier (§1.3). "Clears" means BH at
q = 0.10 over the pass's family AND leave-one-date-out (LODO). All intervals are 95%, clustered by game or event.

### 3.1 Tier 1: live money ($/day at $61.75/day staked, since 11-03)

| rank | lever (per line) | evidence | clears? | EV $/day | conf | score | owner | betting change |
|---|---|---|---|---|---|---|---|---|
| L1 | **Hold-value exits:** take profit only when the net bid beats the position's hold value (mid / model fair) plus the exit fee. Today the rule compares the bid with the ENTRY cost (B-1) | exit price − outcome −2.10 pp [−5.88, +1.69] (559 bets / 374 events / 30 dates); since 11-03 −3.74 [−8.73, +1.24]; net exit effect −2.56 pp of book stake since 11-03 | no (p 0.28 / 0.14); LODO yes | 0.51 (fee) + 1.07 (execution); ceiling 1.58 | med / low | **0.47** | `kalshi-exit-path` | yes. Build default-off + SHADOW (a shadow is not a betting change); switch-on 12-08 at the earliest |
| L2 | **Lower-bound EV at admission and sizing** (T1). Pass B also finds the venue's own fair is missing from the EV reference (B-4) | live: pregame won − consensus −2.94 [−6.40, +0.51] (1,156 / 570) against +2.38 claimed; Kalshi −3.95 [−7.74, −0.15]. Paper: A-1 and A-5 above | gap clears on paper (A-5 60/156 slices; A-1 in all 5 EV bands); live no (p 0.096) | live ≤ 1.25, expected ~0.6; paper ~3.9 at half stake | low (live) | 0.12 | `decision-policy-paper` (P1 `ev_lb` registered) | yes; it is paper2 first under D2 |
| L3 | **Over-side shrink of the consensus fair** on OVER lines, per line, never a side switch (B-3) | overs −14.37 [−23.7, −5.0] (415 / 260 / 30); pregame overs win 7.17 pp below the consensus vs 2.60 for unders; over − under CI spans 0 in both halves | no (p 0.003, family 182) | 0.4-0.85 | low | 0.17 | props: `prop-fair-side-lean` (holdout 11-27 9 AM CST). Game totals: folds into T2 (P1 below) | yes |
| L4 | **#830 game-shape cues** on in-play side choice (B-6) | in-play home −11.6 [−27.5, +4.3] (107 / 106 / 22); over −13.4 | no | ~0.5 | low | 0.10 | `live-bet-timing-forward` (interim 11-19 1:15 AM; verdict 12-02 10 AM CST) | yes |
| L5 | **Maker (post-only) entry** (B-2, S3) | maker fee 0.52 pp vs taker 3.07; pilot −4.76 [−27.5, +18.0] (32 / 31 / 22) | n/a | −0.36 to +0.10 | low | ≈ 0 | S3 re-judge ~11-24 at 30 timed fills (fill lines saved by task `SyndicateMakerPilotLines`) | yes |
| L6 | **Count exit fees in the readout** (B-7) | `fees_dollars` holds the entry fee only on 558 of 560 exited rows; fees understated 0.83-0.95 pp | n/a (accounting) | 0, but removes a bias from every fee-vs-selection split | high | first among the zero-EV fixes | `portfolio-monitor` (`live_book_edge_readout.py`) | no; any time |
| — | Stakes at the measurement minimum (B-5) | in-play 40% of dollars from 17% of bets, −7.25 [−21.2, +6.7] | — | 1.26-1.8 | — | **DECIDED** | user 11-18: "Yes, drop the cut" (portfolio monitor reading 44) | not re-raised |

### 3.2 Tier 2: board, paper and the evidence that gates future money

Units: paper $/day at the paper stakes ($1,337/day), Brier or log loss, or rows/flags per day. EV is never converted
into live dollars (§1.3).

| rank | lever (per line) | evidence | clears? | EV | conf | owner | betting change |
|---|---|---|---|---|---|---|---|
| **P1** | **T2: one per-cell calibrated probability, used everywhere a model probability is used.** `logit p' = logit fair + k_cell · (logit model − logit fair)`, k partially pooled per sport × market and taken from the optimizer's validated w*. Four uses: (a) the rail's ≥ 3 pp flag test (C-1, folds I-1); (b) the board's shown EV (A-5); (c) rank and stake below the 0.5 floor where the w* CI says so (A-3); (d) the shared live probability (C-2, C-5, C-6, D-13; generalises #816's college-totals fit) | rail hit − model −9.1 [−12.7, −5.3] (1,120 / 177 / 3); out of sample +0.024 nats/flag [+0.003, +0.047]. 28 of 61 validated cells have w* CI upper < 0.5 (7,137 rows/day; e.g. NBA live player points w* 0.165 [0.07, 0.26]). Pregame away picks: model 0.491, fair 0.389, hit 0.167 (30 / 30 / 15). Sim vs the line at favourite prices −20.8% [−34.0, −8.4] (127 / 70 / 5) | **yes** on calibration (27/41; A-3; C-5 q 0.074); **no** on money (A-3 stake gap −1.51 [−4.15, +1.14]) | (a) ~326 of ~373 rail flags/day stop, worth ≈ 0 at book; (b) honest EV on ~420 suggested lines/day; (c) Brier −23.9/day, ≤ $6.9/day paper; (d) not measurable here | high (the over-confidence), med (k per cell) | **unowned → new session proposed** (todo #847) | (a)(b) no; (c)(d) yes, default-off, 12-08 at the earliest |
| P2 | **#844:** the grid's newest stamp by parsed time, not text (D-3) | NCAAB full-game ML: 68.6% of fresh live minutes read stale (57 games / 6,112 minutes, 11-17 + 11-18); WNCAAB 62.7%; NBA / NHL / NFL / NCAAF / soccer 0 wrong rows | defect | ~7 NCAAB games/day regain a priced live ML; ~+98 NCAAB / +15 WNCAAB paper bets/day; live money ≈ 0 (no live order reads these rows) | high | `ncaab-total-overprojection` (building; LOAN of `book_grid.py` from `ncaaf-grid-build-speed`) | its lane's call; the user asked 11-18 ~6:40 PM CST: "get 844 landed default off for 11-24" |
| P3 | **#834 NBA live total anchor** (D-1) | gap vs Kalshi +1.78 (se 0.40) → +0.30 (0.41), 37 games. Re-derived since #821 (F1, 11-17 11:35 AM): engine − market +7.41 [+5.57, +9.25], 17 games / 2 dates (BH yes, LODO 6.31 / 7.88) | yes | ~+7.8 pp over-lean at the tip removed; ≈ 0.002 Brier per state; 238 + 1,096 paper / recommended bets/day | high | `nba-live-resim-total-anchor` | yes; **in the 11-24 batch (B)** |
| P4 | **NBA engine overshoot**, the root cause of P3 (D-8) | engine − its own target +4.83 (0.62), 32 games; +6.46 (0.62) since F1, 12 games; NBA live props lose in 9 of 10 markets (+0.014..+0.024 Brier, 160 games) | scorecard cells clear | segment totals and player remainders that P3 does not anchor; ~4,800 paper NBA live prop bets/day | med / low | `basketball-scenario-calibration` | yes |
| P5 | **#816 spread-only** (drop the level term) and the post-#816 NCAAB live totals refit (D-2, C-3) | walk-forward Brier 0.22994 vs 0.23082 (238 games); flags since the #816 load −9.4 pp vs fair [−16.3, −1.8] (245 / 71 / 2), hit − model −19.5 | over-confidence yes; vs fair no (q 0.157) | ~0.0009 Brier per row; 925 recommended bets/day | med | `ncaab-total-overprojection`; grade pre-registered 11-24 10 AM CST | yes; 12-08 at the earliest |
| P6 | **NFL touchdown multiplier 0.825 → 0.925** (D-6) | engine − real −2.31 [−4.21, −0.40], 257 games; held-out totals Brier −0.0113 [−0.0257, +0.0038], 29 games | pre-registered rule passes | ≤ $0.06/day live; NFL live ML on the board | med | batch task `nfl-level-refit-load-1120` | yes; **in the batch (A)** |
| P7 | **#836 end-game freshness refusal `on`** (D-5) | stale states in the last 5% lose to Kalshi by +0.174 nats (0.053), 767 instants / 85 games | no FDR; the 30 s cut was set on the same dates | board and paper late-game edges | med | **unowned** (its finder, lane `live-resim-endgame-staleness`, is closed) → `syndicate-decision-engine` | yes; 12-08 at the earliest, after a shadow read |
| P8 | **Value at the best price:** discount best-price EV by the line's own best book and shop gap (C-4). Same mechanism as T1 | Value −4.1 [−7.2, −0.7] (951 / 392 / 34); rows at best-price EV 2-5% −3.2 [−5.7, −0.9]; best price at Bovada −5.0 [−9.3, −0.5] | no (q 0.288) | removes about −1.5 u/day of display bets | med / low | `cheat-sheet-section-optimization` | no |
| P9 | **Sim vs the line:** admit on the calibrated probability edge, not the projection gap (C-6) | favourite-priced −20.8% [−34.0, −8.4], the section's entire −26.1 u | ROI q 0.068; excess no; LODO 5 dates | −5.3 u/day of display bets | low | `cheat-sheet-section-optimization` (k from P1) | no |
| P10 | **#835 NCAAF live totals:** widen ~1.2×, then re-fit k 2.48 (D-4) | sd ratio 0.75-0.85; log loss vs Kalshi +0.077 (0.054), one Saturday; the served cell is at parity over 7d because k absorbs it | no | mostly M2/M3's raw expert | low | unowned → `syndicate-decision-engine` (engine read) | yes |
| P11 | **NBA live overtime rate** (D-11) | first-tick P(OT) 2.14% [1.72, 2.56] on 50 games vs real 4.54% [3.54, 5.80] | descriptive | late-game ML / totals in ties | low | unowned → `basketball-scenario-calibration` | yes |
| P12 | **Wire NBA/WNBA `form_7` / `form_30`** (D-12): read by the quarter means and stress sigma, never passed | F0 Level-4 checklist: STRUCTURALLY UNFED | defect (model engine standard) | unknown until fed | low | unowned → `basketball-scenario-calibration` | yes |
| P13 | **NCAAF end-of-half profile** (#808, D-7) | 28d pregame `ncaaf|totals|q2` +0.0265 [+0.0108, +0.0428], 239 games / 20 dates | CI excludes 0; BH not stated | NCAAF segment lines | med | `football-scenario-calibration` | yes |
| P14 | **Understat splice** (#845, D-9) | backtest at 8 missing rounds −0.0054 [−0.0103, −0.0004]; the 69 real outage matches +0.0084 [+0.0015, +0.0185] (worse) | the two reads conflict | ≤ $0.03/day | low | `understat-fetch-failures`; queued 12-08, conditional | yes |
| P15 | **#842 day 1 fixed, day 2 retired** (D-10) | day 2 refused 115 of 127 attempts in 7.6 days | defect | input timing | med | **in the 11-24 batch (C, droppable)** | yes |
| P16 | **First-sighting EV haircut** (A-6) | NBA staked on lines already +EV at first sighting −7.00% vs +5.13% others; −12.1 [−23.4, −0.8], p 0.035; confounded | no | ~$3.6/day paper | low | lead for `decision-policy-paper` | yes |
| — | MLB live MC pulled starter (#819, D-14) | 41% of live ticks; remaining total +0.069 runs | — | 2027 | — | its lane | spring 2027 |

### 3.3 Tier 3: defects in the evidence itself (fix before trusting the numbers they touch)

| rank | defect | evidence | what it biases | owner | betting change |
|---|---|---|---|---|---|
| M1 | **The suggested grade sees half the suggested lines**: the recorder writes a line once per board date, at first sighting (A-4) | 304 of 610 suggested lines captured; only 16.0% of staked orders (1,607 of 10,036) sit on a graded suggested line | the suggested set, and any staked-vs-suggested comparison | `layer2-suggested-grader`: the `#sg` record, user "Yes, go ahead" (`de8773740`), loads after 10:30 PM CST 11-18 | no |
| M2 | **Soccer board player props look mis-graded** (suspected: players who did not play graded as losses) (A-7) | about −55% ROI vs about −7% market EV; player_shots live 25,549 bets / 267 games, hit 21.8% | soccer board −43.3% / published −34.8% in the scorecard | **unowned** → todo #848 | no |
| M3 | **NHL live goal-scorer rows priced after the goal** (suspected stale quote) (A-8) | 723 bets / 113 games, hit 8.4%, ROI +152.9% vs market EV +174.5% | NHL board / published ev10+ bands (+111% / +130%); not staked | **unowned** → todo #848 | no (grading); the board row itself is a display question |
| M4 | **Background builds at full priority slow the board** (the rail monitor's L-d) | board CPU per build 106-150 s at host load 1-2, 240-385 s at ~5, 500-600 s at 8-10; three nice-0 soccer builds for dates 4-6 days ahead (4:22, 4:55, 6:14 PM CST) beside the board child; cadence target 300 s, 11-17 peak 1,254-1,510 s | board freshness, hence rail flag timing | **unowned** → todo #849 | likely no (it delays only inputs for dates > 1 day out); confirm at load (learnings 11-18) |
| M5 | Exit fees missing from the readout's fee field | = L6 | fee-vs-selection splits | `portfolio-monitor` | no |

**Biases recorded against the other evidence (pass D):**
- #844 hides college live rows from 11-03, so the rail's "0 missed" cannot see them and the #816 fit never saw them.
- F1 (#821) plus the engine overshoot lean NBA live totals to the over from 11-17 11:35 AM. That reaches the
  scorecard, M2's 11-15..11-22 window, the 11-24 re-read and M3.
- #843 fed corrupted Elo into F1's first graded games (11-17 to the 11-19 slate), so the ~12-06 keep/revert grade
  starts on bad inputs.
- #816's raw pregame fallback means the scorecard's NCAAB pregame totals cells measure the raw engine through 11-18.
- #836: the experts' state-age field understates state age (NBA by a median 13 s, NCAAF by 40-93 s).
- NFL cells grade a level 2.3-2.8 points low. The NCAAF 28d live totals cell is mostly from before k 2.48 (11-13).
- #842: the day-2 look-ahead's opening and movement baselines are missing on 115 of 127 attempts since 11-10.
- I-25 inflated NBA Elo in every NBA row before 11-18 3:02 PM CST, so every NBA k and w* needs a re-read after it.

## 4. The 11-24 window package (Tue 11-24, 2-7 AM CST): proposed to the user

The batch already exists: scheduled task `nfl-level-refit-load-1120` (2:15 AM CST), one claimed ff and ONE drained
full down/up. Each change in it already has the user's own yes.

| | change | status | user's words | prediction owner |
|---|---|---|---|---|
| A | NFL profile t0.925 (P6) | branch `refit/nfl-level-t0.925` @ `12034bf24` | "Yes, that window" | the batch task |
| B | #834 NBA live total anchor env key (P3) | main `88193c0a7`, default off | "Yes, in 11-24" | `nba-live-resim-total-anchor` |
| C | #842 look-ahead keys (P15), droppable | on main, default off | "Fix day 1, retire day 2" | `lookahead-day2-phase-lock` |
| **D (DECIDED: in the batch)** | **#844 grid newest stamp by time (P2): `SYNDICATE_BOOK_GRID_NEWEST_BY_TIME=on`, GLOBAL in `local_production.env`** | **ON MAIN `25a5e480d`, DEFAULT OFF** (verified here 11-18 ~7:00 PM CST: enabled only for on/1/true/yes; absent and `off` keep the old text max; `tests/test_book_grid_newest_stamp.py` 23 passed). Roles that read it: refresh-worker (the book-grid artifact build, and the board child that inherits its env) and web (inline `/api/board/book-grid`, `/api/board/cross-book`). live-odds-worker builds no grid | 11-18 ~6:40 PM CST: "get 844 landed default off for 11-24" (that is the landing; adding it to the batch's load is asked separately) | `ncaab-total-overprojection` |

**D DECIDED.** USER 11-18 ~7:00 PM CST: "Yes, add it" (to "Add #844's key to the 11-24 window batch?"). Added as droppable CHANGE D to batch task `nfl-level-refit-load-1120` (Tue 11-24 2:15 AM CST, one ff + one drained down/up): prompt read back byte-identical 7:07 PM CST; schedule unchanged. Kit `C:/tmp/optprog/window1124/kit_env_844.sh` (self-tested on a dummy env file 7:04 PM CST: append, idempotent, restore, real file untouched). If the batch does not load D, D waits for 12-08.

**D's predictions,** registered by the builder before any load (its message to this lane, 11-18 ~6:55 PM CST),
plus the program's P844-5:
- Builder's A/B on real fleet shards (absent vs on):
  - NBA 11-17 (3,885 rows) and NHL 11-17 (1,470 rows) are byte-identical.
  - NCAAB 11-17: 190 of 2,139 rows change, and 58 cross the 120 s gate from stale to fresh.
  - NCAAB 11-18: 140 of 1,298 change, 13 cross. WNCAAB 11-17: 21 of 270 change, 3 cross.
  - Only `updated_at` and `age_seconds` change. A changed row is always younger, and 0 cross from fresh to stale.
- P1, reachability: on refresh-worker's first NCAAB grid after the load, at least 1 row with a venue cell carries a
  sportsbook-spelled `updated_at`. Before the load the count is 0.
- P2: NCAAB full-game moneyline rows with `age_seconds` ≤ 120 rise from ~25% (25.5% of live minutes on 11-17/18) to
  at least 70% on the first full evening slate. Fresh-by-time is 81.2%.
- P3: the NBA and NHL grids are unchanged.
- P4: NCAAB and WNCAAB `stale_quote` refusals per build fall, and priceable rows per build rise.
- P844-5 (program): live orders do not change. Passes B and D found no live order path that reads a grid row's age.
- **Betting change: the builder says yes, conservatively.** The live gate prices different college rows, and those
  rows reach the rail flags and the live gameline ledger. Classify it `yes` and load it in the window, as the user
  asked. A `no` would need an order-path trace that nobody has done.

**Left out, on purpose:**
- **The optional guard** `LIVE_ODDS_WORKER__SYNDICATE_STAKED_PROBABILITY_UNFITTED=market` (portfolio trace 11-18: 0 of
  1,634 live orders raw-sim sized). The program finds no money effect. A no-op in a measured batch only blurs the read.
  It is the user's call.
- **Nothing else is ready.** L1 exits need a shadow read first. P1 is not built. P5's grade runs 11-24 10 AM, after the
  window. P7 needs a shadow read. P14 is queued for 12-08 already. Those are the 12-08 candidates.

**What the batch is worth:** about $0/day of live money (passes B and D). Its value is board and paper accuracy. The
batch restarts the scale-up gate's clock anyway, so adding D costs no extra restart.

## 5. The pre-registered hypothesis, judged

- **H1: FALSIFIED as written.** Its own falsification clause fired: the long-shot tail gap loses significance pooled
  over the three graded rail days. fair < 0.40: hit 0.224 vs fair 0.238, −1.4 pp [−10.7, +8.0] (107 flags /
  37 games); LODO fails. The 0.154 vs 0.253 came from one day (11-17).
  - What is right in H1: calibration and selection (T2, T1) and input defects (#844) top the table. No new mechanism
    ranks.
  - What is wrong: the over-confidence is not a tail effect. It grows with the claimed gap (3-5 pp −0.3, 15+ pp
    −19.2). The tail (−13.7) cannot be separated from the body (−9.1).
- **H2: HOLDS.**
  - 7 of 26 statistical levers clear BH and LODO: A-3, A-5, C-1, C-2, C-5, D-1 and D-8. That is 27%, or 31% if C-6's
    ROI q 0.068 counts.
  - Every one clears on a calibration, accuracy or display metric. None clears on money.
  - 0 of 182 live-book tests, 0 of 153 suggested-set comparisons and 0 of 137 staked slices clear.

## 6. Hand-offs

| lever | owner | how it was handed | asked for |
|---|---|---|---|
| L1 hold-value exits | `kalshi-exit-path` (owner session gone) | lanes.md note | build default-off + shadow log; switch-on is a 12-08 user decision |
| L2 / P16 / P8 mechanism (T1) | `decision-policy-paper` | lanes.md note | evidence for P1 `ev_lb` at its 11-23 weekly read; A-6 as a lead; do not re-register |
| L3 over-side | `prop-fair-side-lean` | lanes.md note | the live-book overs number beside its 11-27 holdout (props); game totals go to P1 |
| L4 | `live-bet-timing-forward` | nothing new | (already registered) |
| L6 / M5 exit fees | `portfolio-monitor` | lanes.md note | count `exit_applied.exit_fee_dollars` in the readout's fee fields |
| P1 calibration everywhere | **new session proposed**; todo #847 | proposal card | lane, pre-registration, default-off build |
| P2 #844 | `ncaab-total-overprojection` (top session) | message 11-18 ~6:45 PM CST with the user's words | **DONE:** landed default-off `25a5e480d` (verified here), roles and predictions in §4 D |
| P5 | `ncaab-total-overprojection` | lanes.md note | C-3's post-#816 number |
| P4, P11, P12 | `basketball-scenario-calibration` | lanes.md note | the overshoot since F1, the OT rate, the unfed form inputs |
| P7, P10 | `syndicate-decision-engine` (umbrella) | lanes.md note | an owner for #836's shadow read and #835 |
| P8, P9 | `cheat-sheet-section-optimization` | lanes.md note | C-4 / C-6, and the family-corrected q values for the three headline numbers |
| M1 | `layer2-suggested-grader` | nothing new (already loading) | — |
| M2, M3 | **unowned**; todo #848 | proposal card | verify, then fix the grading |
| M4 (L-d) | **unowned**; todo #849 | proposal card | nice the non-urgent background builds behind a switch |
| rail I-1 | `layer2-rail-monitor` | report message | I-1 folds into P1; first-reading flags did not replicate |

## 7. Not levers: slices tested that did NOT clear (numbers kept so nobody re-derives them)

- **Live book** (182 tests, 0 clear):
  - phase: pregame −5.51, in-play −6.90;
  - sports: NBA −4.60, NHL −2.28, NFL −5.14, NCAAF −4.68, soccer −6.03, NCAAB −20.43 [−38.6, −2.2] (all pregame;
    BC-048 moved NCAAB pregame totals to market 11-18);
  - markets: totals −8.42, spreads −7.52, alt totals −2.80, alt spreads +0.12, moneylines −0.45, props −10.68;
  - venues: Kalshi −7.63, Polymarket −0.82;
  - claimed and fee-net EV bands are not monotone, so a higher floor is not supported;
  - lead time, sim agreement, bets per game, slippage, stake quartile ($0.39/day): no pattern.
  - Already settled before this program: S1 freshness (+0.21 pp [−2.82, +3.24] on 6,300 orders / 274 games), S2
    in-play favourites, trader-following (twice), the fee-net floor, the entry-spread limit, favourite-longshot, and
    the min-EV tuner (95 of 95 cells hold).
- **Scorecard and suggested set:**
  - staked NBA +4.08% [+0.17, +8.00] (p 0.041, fails BH over 8 sports); NCAAB staked +6.20% [−3.24, +15.64];
  - all-sports staked +2.35% [−0.22, +4.92], and the earlier separate window was −1.44%, so the sign flips;
  - board → published lifts +10.3 points, but all of it from negative-EV rows nobody bets (EV 0-2 +0.39, 2-5 +0.06);
  - suggested-set slices 0 of 153: live −4.38, alt −4.92, +201..+400 −10.44, NCAAF +9.14 (p 0.047), books from
    fanatics −13.2 to williamhill +33.5;
  - candidate rules R1 (books penalty) +0.97 [−4.60, +6.53], R2 (live quote < 60 s) +1.18 [−4.79, +7.15], R3 (fitted
    fair shrink) +3.79 [−7.14, +14.72], which acts as a gate (0 lines kept in 11 cells) and is rejected.
- **Rail flags** (41 slices):
  - pooled vs fair +2.2 pp [−1.5, +5.8];
  - first reading +0.3 [−6.1, +6.7]: the 11-17 0.333 vs 0.500 did not replicate on 11-15/16;
  - NBA totals +8.9 [+2.9, +15.2] (q 0.157), NCAAB ML +16.4, moneylines +11.9, underdogs +11.7, fair > 0.60 +11.3,
    quote age < 30 s +5.0: all fail BH.
- **Cheat sheets** (181 + 143 cells):
  - Value −4.1 (q 0.288), Matchups lift +3.5 (q 0.399), Syndicate picks −4.5 (q 0.48): each is real only as the
    review's single pre-specified test;
  - price plays on long dogs −3.5 vs fair (vig plus variance), hot streaks, consistency, skater vs goalie, and every
    player-vs-player section: q ≥ 0.23.

## 8. Could not measure

- **Live:**
  - in-play CLV (3 of 449 in-play bets have a close);
  - maker edge at fill (the ledger has no fill times);
  - which exit rule fired;
  - anything after BC-052 (0 decided bets yet).
- **Paper / scorecard:**
  - live-money orders by cell (the ledger archive holds paper only);
  - the overlay's per-cell history;
  - C-2 in money;
  - the causes of M2 and M3.
- **Rail:**
  - the 11-18 grade (10 of 64 flags final at 6:20 PM CST; the rail monitor's pre-registered grade runs tonight);
  - pregame and prop flags (the rail flags live game lines only).
- **Engine:**
  - P3's post-F1 Brier gain, #835 and the #816 7-day grade were left unread. Reading them would peek at M2's held-out
    window and the registered 11-24 grade.

## 9. Sources and reproduction

- **Evidence passes, 11-18 6:15-6:45 PM CST, read-only:**
  - lever tables `C:\tmp\optprog\{A,B,C,D}_levers.md` and `E_levers.md` (peer levers);
  - scripts and outputs `C:\tmp\optprog\{A,B,C,D}_*`.
  - `C:\tmp` is shared and not durable. This file carries every number the ranking rests on.
- **Fleet substrate:**
  - `~/syndicate-prod/data/reports/model_scorecard/model_scorecard_20261118.json`;
  - `reports/suggested_set/suggested_set_latest.json` (6:07 PM CST);
  - `cheatsheets/reviews/*.json` (10-15..11-17);
  - one GET of `/api/portfolio/live?on=all&show=all` at 6:16-6:17 PM CST (2,363 orders);
  - the ledger archive;
  - `/api/board/game-chips` for 11-15..11-17 (22 flags settled).
- **Rail grades:** `C:\tmp\railmon\grade*_out.json` (the rail monitor's), re-pooled.

## 10. What the three proposed sessions found (read 11-18 ~8:55 PM CST from main; every switch checked absent = off here)

The user started all three cards ~7:10 PM CST. The rail monitor started duplicates on the user's "start 847, 848, and
849" and stopped its own.

- **#847, calibration everywhere** (lane `cell-calibration-847`, `.syndicate/findings_2026-11-18_cell_calibration.md`):
  - **Built and on main, all default OFF:** (a) rail `SYNDICATE_CELL_CALIBRATION_RAIL`, (b) display
    `..._DISPLAY`, (c) rank/stake `..._RANK_STAKE` (betting), (d) live probability `..._LIVE_PROB` (betting; wired into
    `live_gameline_join` on a user-approved loan). Commits `75a787964`, `8acee817d`.
  - **H-S (scorecard rows, time split) PASSES:** dBrier −0.0062/row [−0.0102, −0.0021], 23,564 rows / 367 games / 7
    dates, 22 of 29 cells better.
  - **H-R (rail flags) FAILS on coverage, not sign:** +0.0010 nats/flag [−0.0030, +0.0051]. Only 182 of 1,120 flags
    sit in a cell the validated table serves.
  - So use (a) is NOT supported on its own evidence yet. Pass C's +0.024 nats/flag came from a rail-fitted k, not the
    optimizer's validated table.
  - Forward grade H-F on Thu 11-26. (c) and (d) are 12-08 window candidates and need the user's OK then.
- **#848, scorecard grading** (lane `scorecard-grading-defects`, CLOSED; `.syndicate/findings_2026-11-18_scorecard_grading_defects.md`):
  - **M2 soccer props: FALSIFIED for the bulk.** Did-not-play rows are voided. The −55% is the real return of one-way
    prop ladders at the recorded prices. What is wrong is the cell's MARKET EV: the one-way fair assumes a ~7% margin.
  - One real defect was found on the way: goal-scorer rows ignored their side.
  - **M3 NHL live goals: CONFIRMED, refined.** 780 of 782 ev10+ rows were priced on a quote their own book never
    returned after puck drop.
  - Fixes `soccer/2` and `nhl/2` are on main behind `SYNDICATE_SCORECARD_848_GRADING` (absent = off; grading only,
    not a betting change).
- **#849, background build priority** (lane `board-build-priority`, CLOSED, GOAL MET, NOT BUILT; `.syndicate/findings_2026-11-18_board_build_priority.md`):
  - Far-dated soccer autorun units cost the evening board ~6 s per build and ~19 s of a 371 s publication gap.
  - A lower priority cannot buy that back, so no switch was built (`238502852`).
- **Effect on the ranking:**
  - P1 holds as built-but-unproven: the scorecard grade passes, the rail grade fails on coverage, and the forward grade
    lands 11-26.
  - M2 becomes "the soccer prop cell's market EV is mis-stated", a display and optimizer-input defect, not grading.
  - M3 is fixed default-off.
  - M4 is closed as not worth building.

## 11. Status and next steps (11-20 ~9:45 AM CST)

### 11.1 What moved since 11-18 (read on main and the fleet)

- **Live book:** 30 d −7.38% [−12.8, −2.0] on 719 events. 11-19 alone: +4.21% [−10.8, +19.3] (51 bets / 23 games, won
  60.8% vs a 64.3% breakeven). Fees 3.89% of stake. Gate 13 of 800 on BC-053 (the portfolio monitor, readings 99-102).
  No change to §3.1.
- **Scorecard funnel:** unchanged across 11-18 / 11-19 / 11-20. The windows overlap, so that is expected.
  - NBA staked +4.1 / +3.7 / +4.2%; NCAAB +6.8 / +5.0 / +6.2.
  - Soccer board −43.3 / −43.4 / −44.1. #848 explains the soccer board number as one-way ladders priced against a
    mis-stated market EV.
- **Rail flags 11-19:** 167 flags / 37 games, hit 0.503 vs fair 0.506 (the rail monitor's daily summary). Flags at the
  fair again, consistent with §2.
- **Suggested set:** `#sg` coverage is 100% from 11-18 (`ee0ceee34`), so M1 is RESOLVED.

### 11.2 Hand-offs: who answered

| lever | owner | state 11-20 |
|---|---|---|
| L6 exit fees | `portfolio-monitor` | **RESOLVED** (its STATUS 11-19 ~12:05 PM CST) |
| P2 #844 | `ncaab-total-overprojection` | change D of the 11-24 batch; kit present; P1-P4 move to the rail monitor |
| P1 #847 | `cell-calibration-847` | built default-off; H-F scheduled 11-26 7:00 AM CST |
| M2/M3 #848 | `scorecard-grading-defects` | CLOSED; fixes default-off; loading is a BETTING change (overlay); 12-08 candidate |
| M4 #849 | `board-build-priority` | CLOSED, not built |
| L1 hold-value exits | `kalshi-exit-path` | **NO ANSWER: the owner session is gone.** Nobody is building it |
| L2 / T1 evidence | `decision-policy-paper` | note unread; its weekly read is 11-23 |
| P4 / P11 / P12 NBA engine | `basketball-scenario-calibration` | note unread |
| P7 / P10 (#836, #835) | `syndicate-decision-engine` | note unread; #836 still has no named owner |
| P8 / P9 cheat sheets | `cheat-sheet-section-optimization` | note unread |
| L3 overs | `prop-fair-side-lean` | note unread; its holdout is 11-27 |

### 11.3 The 11-24 window

- The batch task `nfl-level-refit-load-1120` now holds seven changes:
  - A: NFL t0.925
  - B: #834
  - C: #842
  - **D: #844**
  - E: #851
  - F: #853
  - G: #854
- D's kit and prompt are intact (read 11-20).
- The gate count restarts at the window load whatever is in it.

### 11.4 Calendar of the readings the re-rank waits for

- 11-23: decision-policy-paper weekly read (P1 `ev_lb`).
- 11-24: the window load (2:15 AM CST); M2's read (~10:30 AM); #816's grade (10 AM); the maker pilot re-judge.
- 11-26: #847's H-F (7:00 AM CST); then **this program's re-rank, scheduled task
  `product-optimization-rerank-1126` (9:30 AM CST, read-only)**. It also reruns the suggested-to-placed match handed
  over on 11-19 and drafts the 12-08 candidates.
- 11-27: prop-fair-side-lean's holdout.

### 11.5 Next steps

- **L1 DECIDED 11-20 ~9:50 AM CST: the user answered "Yes, start it" to "Start a session to build hold-value exits default-off with a shadow log?". Session local_552e5194 (hold-value-exits) STARTED with a brief: default-off rule plus a SHADOW log and grader, a LOAN of its sections from kalshi-exit-path (owner session gone), a pre-registered shadow grade, and a load plan for the user. No fleet load and no switch-on are approved; switch-on is a 12-08 window decision.**

1. **Gap, the user's call:** L1 hold-value exits has no live owner. To be a 12-08 candidate it needs a default-off
   build plus a shadow log running by about 11-24, so two weeks of shadow exits can be graded.
   - A shadow is not a betting change and can load any time with the user's OK.
   - Expected value is small: about $0.5/day, ceiling $1.58/day, not clearing BH. It is still the top-ranked live
     lever, and the shadow is how to find out cheaply.
2. **No action:** the unread hand-off notes sit at the top of each owner's lane block, and owners see them when they
   next work. #836's owner question goes into the 11-26 re-rank.
3. **12-08 package:** the 11-26 re-rank drafts it, and the user decides each change before 12-08.

### 11.6 Checks, 11-20 ~11:20 AM CST

- **Change H is in the batch, verified here.** The prompt names `LIVE_ODDS_WORKER__SYNDICATE_EXIT_HOLD_VALUE=shadow`
  and never `on`. H is wired through every stage, the same way D was:
  - decision quotes;
  - the restore chain, now B -> C -> D -> E -> F -> G -> H;
  - the kit `C:/tmp/hv856/kit_env_856.sh` and its self-test;
  - `tests/test_exit_hold_value.py` (failure drops H only);
  - apply checks (live-odds-worker `shadow`; refresh-worker and web ABSENT);
  - baseline, preflight and verification;
  - a "not a betting change" registration (F and H are never registered as betting changes).
  The user also approved it in the exits session directly ("Yes, ride 11-24", ~10:55 AM CST), and both approvals agree.
- **Batch integrity:** all 18 kit files named in the prompt exist on disk.
  - Risk 1: every kit lives in `C:\tmp`, which has been cleaned before (10-27). A missing kit drops only its own
    change, except the core `t834` kit, whose loss stops the batch.
  - Risk 2: only #834 has a fallback task. If the batch task misses its dispatch, every other change waits for 12-08.
- **Schedules (read 11-20 ~11:15 AM CST):** all enabled:
  - `nfl-level-refit-load-1120`, 11-24 08:15Z (2:15 AM CST);
  - `nba-total-anchor-load-1124`, 09:45Z;
  - `cell-calibration-847-hf-grade-1126`, 11-26 13:00Z (7:00 AM CST);
  - `product-optimization-rerank-1126`, 11-26 15:30Z (9:30 AM CST).
- **#836's shadow is LIVE on the fleet,** contrary to section 3.2 P7's "no line has printed". The fleet checkout
  carries `52e68382a` (fleet head `3c8ba5b14`). refresh-worker logged NHL `LIVE_ENDGAME_FRESHNESS mode=shadow` on
  11-19 10:33-11:50 PM CST: 191 end-game line-instants judged, 86 (45.0%) would be refused
  (`live_state_stale_in_endgame`).
  - No NBA or NCAAF shadow lines appear in refresh-worker.log yet.
  - ~~Nobody grades the shadow against outcomes.~~ **CORRECTED ~11:40 AM CST:** lane `engine-learner` has owned #836
    since 11-20 10:11 AM CST (user "fix gap"). It read the shadow over 11-18 and 11-19: NBA 542 of 3,665 end-game
    row-builds would refuse (15%), NCAAF 138 of 529 (26%), NHL 301 of 589 (51%). Todo #836 holds it; `on` is a
    12-08 ask on the user's yes. My refresh-worker.log grep saw only NHL because the log had rotated.
  - The 11-26 re-rank reads the owner's result. It does not re-grade it.

### 11.7 The user's "Yes, add it" (11-20 ~11:35 AM CST)

It followed two open asks: grade #836's shadow in the 11-26 re-rank, and schedule the exits shadow's 12-07 grade.
Both are read-only, so both were acted on.
- **#836:** already owned and shadow-read by `engine-learner` (section 11.6 corrected). Task
  `product-optimization-rerank-1126` was edited to read the owner's result rather than re-grade it, to treat L1 as
  NOT READY on 11-26 (its verdict is due 12-07), and to cover batch changes A-H. The prompt was read back
  byte-identical, and the schedule was untouched.
- **12-07 exits grade:** the `hold-value-exits` session was asked to schedule its pre-registered grade as a one-off
  read-only task before the 12-08 window. **Confirmed:** the 12-07 exits grade IS SCHEDULED (hold-value-exits, ledger `a3bc22764`, on the user's own "Yes, schedule it" ~11:20 AM CST in that session): read-only tasks `hold-value-shadow-grade-1207` (Mon 12-07 12:30 PM CST) and `-backup` (4:30 PM CST, stands down if graded), both enabled. The pre-registered window is shadow ticks and games through 12-06, verdict on or after 12-07 12:00 PM CST. That leaves the evening for the user's 12-08 decision.

## 12. Re-rank 11-26

Run 11-26 10:01-10:45 PM CST by a session started from the coordinating session (e32fef1a), with the stored prompt of
task `product-optimization-rerank-1126`. Its four scheduled attempts (9:30-10:34 AM CST) failed at the API with
ENOTFOUND during the host's DNS outage (about 12:00 AM-11:05 AM CST), and the task disabled itself. The user said "no
you do it" (~9:55 PM CST). Before this write, this file had no `## 12.`.
- **Read-only on the fleet:** GETs of `/api/portfolio/live` and `nice -n 19` reads of the data root. No deploy, claim,
  env edit, POST or scheduled-task edit.
- **#847 waited for:** its §5 landed on origin/main in `769387420` (~10:08 PM CST), and this section was written after it.
- **Scratch:** `C:\tmp\optprog_1126\`. This is NOT durable; the numbers are here.

### 12.1 Readings (a)-(i)

**(a) The 11-24 window batch: ALL of A-H loaded, and none was dropped.**
- **The load:** one claimed ff `d845fe345..672a18e87` at 2:30:10 AM CST, then ONE drained full down/up. Every role
  booted on `672a18e8` at 2:30:36-37 AM CST (`deploys.md:63060`, `:63125-63132`). The batch was 16 changes (A-P).
- **Each change** (load times CST 11-24, register rows `betting_changes.md:90-104`):
  - A NFL t0.925, 2:30:37, BC-059;
  - B #834 NBA live total anchor, 2:30:36, BC-060; 86 of 86 NBA ticks anchored (`deploys.md:63185`);
  - C #842 look-ahead keys, BC-061; Pb0-Pb2 held (`:63490-63492`);
  - D #844 grid newest stamp by time, BC-062;
  - E #851 Polymarket slate sweep on its own thread, BC-063; P1-P6 predicted (`:63380`);
  - F #853 one shared board copy in web, not a betting change; P5 falsified, 89.3 vs 77.7 builds an hour (`:63393`);
  - G #854 college orientation join, BC-064;
  - H #856 hold-value exits SHADOW, not a betting change.
- A and G have no post-load reading in the ledger.
- **Later loads:** every one after the batch is `betting change: no` (web 11-24 9:43 AM, BC-072, BC-073, 11-26 #861
  step 1d, the 11-26 11:40 AM live-odds-worker ff+TERM). The latest betting change is **BC-071 at 2026-11-24T08:30:37Z**.
  Nothing is pending. `betting_change.py candidates` still lists 2 unclassified loads, 11-18 17:58:30Z and 11-19
  04:46:22Z, both before the clock start.

**(b) M2's 11-24 read: FAIL on harm. M3 never started.**
- The verdict is `M2_VERDICT FAIL harm=1 [outcome:ON_BY_AGE:nba|totals|live|a<=60] judged=18 pass=1` (`50319e3d3`;
  `findings_2026-11-16_m2_gate.md:8-50`).
  - The harm: NBA live totals, d_ll +0.024058 [+0.013761, +0.034215], 60 games.
  - The only pass: `ncaaf|totals|live` −0.038165 [−0.063059, −0.014735], 63 games.
  - The gate uses a 99% bound per stratum, with no BH or LODO.
- **The diagnosis** (`882812442`, gates nothing): the re-sim's over-lean went from +0.113 in train to +0.359 after #821
  F1. With the re-sim weight zeroed, the harm is +0.0009 [−0.0001, +0.0022]. This is P4's mechanism (§12.4).
- **M3:** printed `NO_M3` 11-25 8:43 AM; user "yes, disable the M3 nightly task" (~9:35 AM 11-25); the lane is dormant.
- **M2b:** user "Hold M2b" (11-25 10:10 AM). Only task: `engine-learner-kalshi-recheck-1201` (12-01, NBA, gates nothing).
- **Nothing from these lanes goes to 12-08 except #836 `on`.**

**(c) decision-policy-paper 11-23: P1 `ev_lb` took NO look** (`findings_2026-11-23_decision_policy_weekly_read.md:10-19`,
`7ae99f1be`).
- It has 188 sharp-graded bets / 142 games. L1 needs 400 / 100: the games are met, the bets are not.
- Reported but not decisive:
  - fee-net CLV −0.18% [−0.91, +0.53];
  - against C0 on shared lines +4.17 pts [+1.72, +6.74], 75 bets / 64 games.
- Next look Mon 11-30 9:43 AM CST. P1's L1 is projected around 12-13..12-20.

**(d) The maker-entry re-judge (~11-24) was never scheduled and never ran.** The only re-judge task ran 11-14 (NOT YET
DUE, 14 of 30 timed fills; `lanes_closed.md:15821`).
- Read here from the live ledger (`execution_style = maker_pilot`): 80 posts; 33 rejected; 45 filled.
- 43 decided bets / 42 events, ROI **+1.65% [−16.55, +19.86]**, fees 0.56% of stake (10-25..11-25).
- 11-18 read: −4.76 [−27.5, +18.0] on 32 / 31.
- The registered criterion (edge at fill ≥ +1.5 pp, 90% lower bound > 0) was not computed.

**(e) #816's grade, 11-24 10:04 AM CST: it passes the registered FLIP-to-spread-only rule** (`findings_2026-11-16_ncaab_total_overprojection.md:196-263`).
- T3 (served − spread only) is +0.00484 [90% game-clustered +0.00230, +0.00737] on 284 live games / 7 nights.
  Spread only won 6 of 7 nights.
- Our bar is not the registered one:
  - the registered rule uses 90%, with no BH and no LODO;
  - z ≈ 3.1 would survive BH over T1-T5;
  - by the per-night table, dropping any single night keeps T3 > 0.
- **The gain is shrinking.** The daily refit's level fell from −0.288 to −0.040 over the window, so 11-21..11-23 were
  near ties.
- **No user words since the grade.** The last on record: "Keep until 11-24" (11-18 ~7:40 AM CST).

**(f) #847's forward grade H-F: PASSES** (`findings_2026-11-18_cell_calibration.md` §5, `769387420`, read 10:01 PM
CST 11-26 by the parallel re-run).
- ΔBrier −0.006815/row **[−0.009606, −0.004426]**, 32,372 rows / 486 games / 7 dates (11-19..11-25).
- **38 of 41 cells are better** (bar 27.3). The 3 worse are NCAAF spreads pregame (q1, h1, full) at k 0.365. Full
  was worse in H-S too.
- H-R is **not runnable** to new coverage: no `nba|*|live` cell and no college-totals live cell is served.

**(g) #830 and #844.**
- **#830's interim** (11-18 slate only, 90% CIs): C1, C2, C2x, C4, C4r and C6 INSUFFICIENT; C3 NOT CONFIRMED; C5 FAILS.
  The verdict task runs 12-02 10 AM CST.
- **#844 FINAL** (rail monitor, `deploys.md:63573-63582`):
  - P1 PREDICTED: 1,053 of 2,696 venue rows carry a sportsbook-spelled stamp, vs 22 of 1,213 on 11-19.
  - P2 PREDICTED: NCAAB moneyline rows fresh by row age 274 of 352 (77.8%), equal to fresh by cell, 0 mismatches. It
    was measured as a share of rows, not of live minutes.
  - P3 PREDICTED: NBA mismatch 0 of 48 samples. NHL was not sampled.
  - P4 NEITHER: NCAAB stale share flat (37.4% → 37.0%). WNCAAB's fell, but so did its priceable share.
- **Rail daily grade** (90% CIs, no BH or LODO):
  - 11-24: 631 flags / 102 games, hit 0.553 vs fair 0.501 [+0.011, +0.094], model 0.600;
  - 11-25: 550 / 91, hit 0.512 vs 0.481 [−0.012, +0.075], model 0.584;
  - 11-26: not written yet.
  - Flags still hit far below the model's own probability (−4.7 and −7.2 pp), the same over-confidence as §2.

**(h) The live book** (`py -3 scripts/live_book_edge_readout.py`, fleet GET 10:04 PM CST, 2,705 live orders, as of the
11-25 slate). ROI is net of fees, with event-clustered 95% intervals.

| window | bets / events | ROI | fees % of stake | before fees (selection at the fill price) | fee-net same-book CLV |
|---|---|---|---|---|---|
| last 30 (10-27..11-25) | 1,610 / 723 | **−7.51% [−13.19, −1.83]** | 3.89% | −3.62% | −0.63 pp ± 0.22 SE (624 bets); close calibration −4.05 pp (z −1.95) |
| last 7 (11-19..11-25) | 263 / 148 | +0.24% [−11.49, +11.96] | 3.11% | +3.35% | −1.53 pp (se 0.5; portfolio monitor) |
| since BC-071 (11-24T08:30:37Z) | 16 / 10 | +36.66% [−5.36, +78.67] | 2.29% | +38.94% | −5.18 pp, n = 2 |

- **Fees are now 52% of the 30-day loss** (3.89 of 7.51 pp). On 11-18 they were 78% (since 11-03).
- Selection before fees has gone from +0.65 to −3.62. The tool gives no CI on the before-fees figure, so this is not a
  tested change.
- **Gate: 10 of 800 events (NOT MET).** The clock starts at BC-071. This reconciles with the portfolio monitor's 6:30 PM
  CST reading: the same 30-day and 7-day numbers, and 10 of 800.
- **Live volume fell after BC-071** (0% live EV floor OFF; the live plans buy Suggested rows only). The fall was
  predicted by its lane: rows_in went from hundreds to tens (`lanes.md:2204-2213`).
  - Orders per UTC day: 53-68 on 11-17..11-23 (35 on 11-20), then 24 / 22 / 10 on 11-24 / 11-25 / 11-26. 11-26
    includes 11 h of outage.
  - Stake: ~$28-80/day before, ~$20-33/day after.
  - At about 3.75 events/day, the gate's 800 events are about 200 days away. **Every Tier-1 $/day below is rescaled by
    about 25/61.75 ≈ 0.4.**

**(i) The scorecard funnel** (`model_scorecard_20261126.json`, generated 11:30Z = 5:30 AM CST, during the outage).
28-day `optimizer.by_sport`, as pooled / recommended / staked ROI (staked bets):

| sport | 11-20 | 11-26 | games / dates (11-26) |
|---|---|---|---|
| NBA | −7.6 / −1.5 / +4.2% (4,633) | −7.5 / −1.4 / **+2.6%** (4,560) | 193 / 26 |
| NCAAB | −5.7 / −4.8 / +6.2% (598) | −5.7 / −4.7 / **+4.6%** (901) | 1,065 / 24 |
| soccer | −44.1 / −35.6 / −5.2% (586) | −42.8 / −31.4 / −1.5% (633) | 394 / 18 |
| NCAAF | −7.3 / −4.5 / +6.0% (1,277) | −7.3 / −4.5 / **−1.3%** (1,277) | 254 / 19 |
| NFL | −5.3 / −5.4 / −1.0% (1,217) | −5.3 / −5.1 / +2.4% (1,427) | 56 / 12 |
| NHL | −11.2 / −10.5 / −0.6% (1,550) | −10.4 / −9.9 / +0.5% (1,512) | 183 / 26 |
| WNCAAB | −7.5 / −4.9 / −1.7% (27) | −7.3 / −5.3 / +8.5% (43) | 388 / 24 |

- The windows overlap 22 of 28 days, so these are not independent samples. No CI is published per sport.
- The 11-26 NCAAB pooled and recommended counts equal 11-25's (251,373 / 153,870 bets): that run graded no new NCAAB
  rows.
- All-sports staked: +1.69% on 10,401 bets (predicted +3.95%).
- The pattern of §2 holds. The board loses, the recommended set loses less, and the staked paper book is near zero. NBA
  staked fell from +4.2 to +2.6 and NCAAF from +6.0 to −1.3, but neither move is a tested change.

### 12.2 STEP 2: the suggested-to-placed match, rerun

Method of `C:\tmp\optprog\A_join2.py` (11-18), unchanged. The identity is (game, market, player, segment, side, line,
phase), taken from `suggested_set_state.json` `graded` (37,543 lines, state written 11-26 13:23Z). The orders are the
settled paper orders in `execution_ledger_archive` (68,969 latest per key). Script: `C:\tmp\optprog_1126\s2_join.py`.
- **The window stops at the 11-24 slate:** the 13:23Z 11-26 grader ran in the outage and graded only 664 lines for 11-25.
  11-19..11-23 graded 2,592-4,899 lines a day.
- **The 11-18 numbers reproduce:** 1,784 of 10,576 in-set (16.9%), against 16.0% on 11-18. The difference is orders
  that settled later.

| window | orders (games / dates) | in-set share | in-set ROI | out-of-set ROI | in − out | LODO |
|---|---|---|---|---|---|---|
| **complete coverage:** submitted ≥ 04:46:47Z 11-19 (#sg live), slate ≤ 11-24 | 2,365 (398 / 7) | **95.4%** (2,257) | **+3.15% [−1.61, +7.91]** (377 g) | +7.72% [−13.93, +29.37] (49 g) | −4.57 [−26.55, +17.41], p 0.684 | fails |
| full: slate 10-21..11-24 | 12,949 (1,649 / 35) | 31.2% (4,039) | +0.25% [−3.78, +4.29] (979 g) | +3.11% [+0.46, +5.76] (1,295 g) | −2.86 [−7.64, +1.92], p 0.241 | holds |
| 11-18 (for reference) | 10,036 | 16.0% | −1.30% [−8.14, +5.55] | +3.04% [+0.32, +5.77] | −4.34 [−11.62, +2.94], p 0.243 | holds |

- **What this says:** once the recorder sees every suggested line, **95.4% of staked orders sit on one.** The 11-18
  "only 16.0%" was defect M1, the first-sighting recorder, not a selection gap.
  - The board-to-staked selection gap that H1 named is **not a lever.** The staked paper book IS the suggested set.
- **The slices clear nothing:** 0 of 9 slices clear BH at q 0.10 in either window.
  - Complete-coverage NCAAF in-set −20.18% [−39.15, −1.21] (194 / 55 g), p 0.037; NBA in − out +29.55 (18
    out-of-set orders), p 0.044.
  - The out-of-set group is 108 orders, too thin to compare.
- **Sensitivities:**
  - Including the 11-25 slate pushes out-of-set to 392 orders, because 11-25's lines are not graded yet. This is the
    lag, not selection.
  - Restricting to games with a graded line gives 96.8% in-set.

### 12.3 STEP 2b: the portfolio monitor's two slices under this program's bar

Scope: live bets **selected 10-24..11-22** (30 days through 11-22): 1,717 bets / 774 events / 30 dates. That is
`bets_from_orders` of the 10:04 PM CST GET. Nothing from 11-23 on is read, so the monitor's forward set is untouched.
Script: `C:\tmp\optprog_1126\s2b_slices_v2.py`.
- **The monitor's reading reproduces:** on its 11-22 window (10-23..11-21) the 0.30-0.45 band is −12.32% on 305 / 199,
  and on 10-24..11-22 it is −12.16% [−23.86, −0.46] on 281 / 189, the monitor's exact figure.
- **The family:** 12 price and EV bands × 3 metrics. The metrics:
  - net ROI;
  - net ROI − claimed EV, the monitor's comparison;
  - ROI before fees − claimed EV, like for like, because `ev_pct` is the EV at the venue price BEFORE the fee
    (`portfolio_commit.py:1224-1238` holds the separate `ev_pct_net_of_fee`).
- Only 6 bands have bets in the window: price .30-.45 / .45-.55 / .55-.70 / .70-.85, and EV 2-5 / 5-10. So the
  **family is m = 18 tests.** If the 18 empty band-tests were counted (m = 36), nothing would pass.

| slice | metric | bets / events | estimate, 95% event-clustered | p | BH (m 18) | LODO | halves |
|---|---|---|---|---|---|---|---|
| **price .30-.45** | net ROI | 281 / 189 | −12.16% [−23.86, −0.46] | 0.042 | **FAILS** (rank 4, threshold 0.022) | holds [−13.91, −9.75] | −14.20 / **+1.98** |
| **EV 2-5** | net ROI | 1,057 / 582 | −6.80% [−14.47, +0.87] | 0.082 | FAILS | holds | −8.38 / −3.74 |
| **EV 2-5** | net − claimed (+4.13) | 1,057 / 582 | **−10.93 pp [−18.59, −3.26]** | 0.0052 | **CLEARS** | holds [−12.25, −9.15] | −12.51 / −7.87 |
| **EV 2-5** | before fees − claimed | 1,057 / 582 | −7.54 pp [−15.24, +0.15] | 0.055 | FAILS | holds | −9.20 / −4.33 |
| price .55-.70 | net − claimed (+4.10) | 509 / 309 | −13.88 pp [−23.88, −3.89] | 0.0065 | CLEARS | holds | −17.31 / −7.05 |
| price .55-.70 | before fees − claimed | 509 / 309 | −10.87 pp [−20.89, −0.85] | 0.034 | FAILS | holds | −14.44 / −3.74 |
| price .45-.55 | net ROI / before fees − claimed | 643 / 442, 546 / 383 | −0.65% [−10.36, +9.06] / −0.03 [−11.45, +11.39] | 0.90 / 1.00 | — | — | — |

No other test has p < 0.11.

- **Slice 1, fill price 0.30-0.45: FAILS the bar. 11-18's NOISE verdict STANDS.**
  - It fails BH. LODO holds, but the two halves of the window disagree in sign (−14.20 before 11-08, +1.98 from
    11-08), which is the same split that made 11-18 call it noise.
  - **It is not the model over-rating underdogs, so the T2 / #847 mapping does not hold.** 265 of its 281 bets carry no
    model probability:
    - 133 are in-play orders sized on `inplay_book_median_novig`, −16.88% [−31.98, −1.78] (91 events);
    - 132 are legacy Kalshi orders with no sizing basis, all selected 10-24..10-31, −5.37% [−22.11, +11.38] (89 events);
      they leave the 30-day window by 11-30;
    - only 16 are model-sized (`model_edge`).
  - **Consequence for the monitor's pre-registered longshot lead:** its GO statistic, a model probability equal to the
    fill price plus `model_edge`, exists on 16 of 281 bets in this window. The forward read cannot be computed on
    the in-play bets. That is the portfolio monitor's to resolve before its forward read.
  - Stays on the noise list (§7) with these numbers.
- **Slice 2, claimed EV 2-5: it CLEARS as the monitor states it, and FAILS like for like.**
  - Net realised against the pre-fee claimed EV: −10.93 pp, clearing BH (m 18) and LODO with halves that agree. But
    about 3.4 pp of that gap is the fee, which `ev_pct` never included.
  - Like for like (before fees against the claimed EV): −7.54 [−15.24, +0.15], p 0.055, fails BH.
  - **11-18's NOISE verdict on the EV bands' ROI STANDS** (net ROI −6.80, p 0.082). The over-statement of EV at the
    price we take is real in point estimate, but it does not clear on the live book once fees are separated.
  - This is T1 (L2): it stays "watch". The lever it supports when it clears is a per-line fee-net lower-bound EV at
    admission and sizing: `decision-policy-paper` P1 `ev_lb`, which has 188 of the 400 bets its first look needs.
    Never an EV-band gate.
- **New, not one of the two slices: the over-statement sits at FAVOURITE prices.**
  - 0.55-0.70 gives −13.88 net / −10.87 like for like. The 0.45-0.55 band is inside noise like for like (−0.03).
  - This contradicts a longshot reading. It is found in this family, so it is a watch item for T1, not a lever.

### 12.4 Re-ranked table

Tier-1 dollars are at the post-BC-071 stake, about $25/day; 11-18 used $61.75/day. Marks are against §3.

**Tier 1: live money**

| rank | lever | mark | the reading that moved it (or not) | EV now ($/day) | owner | betting change |
|---|---|---|---|---|---|---|
| L1 | Hold-value exits | **UNCHANGED, still #1 live** | shadow LOADED 11-24 2:30 AM CST (change H) and logging: `reports/intelligence/execution_exits_hold_value/shadow_<UTC date>.jsonl`, 5,625 / 9,515 / 5,161 / 1,750 rows for 11-24..11-27 (to 04:11Z). Pre-registered verdict 12-07 | ~0.2, ceiling ~0.64 (was 0.51 + 1.07, ceiling 1.58) | `hold-value-exits` | yes; NOT READY until 12-07 |
| L2 | Lower-bound EV (T1) | **UNCHANGED** | P1 `ev_lb` took no look (188 / 142 of 400 / 100); live EV 2-5 like-for-like −7.54 [−15.24, +0.15] fails BH (§12.3) | live ≤ 0.5 | `decision-policy-paper` | yes |
| L3 | Over-side shrink | UNCHANGED | holdout 11-27 not yet read. 30-day live totals −13.75% ± 6.03 SE (360 / 283), p ≈ 0.023, fails BH by inspection over the readout's 16 sport/market slices | 0.2-0.35 | `prop-fair-side-lean`; game totals → P1 | yes |
| L4 | #830 game-shape cues | UNCHANGED | interim INSUFFICIENT / NOT CONFIRMED; verdict 12-02 | ~0.2 | `live-bet-timing-forward` | yes |
| L5 | Maker entry | UNCHANGED | +1.65% [−16.55, +19.86] (43 / 42); re-judge never run | ≈ 0 | S3 pilot (no re-judge scheduled) | yes |
| L6 | Exit fees in the readout | RESOLVED (11-19) | — | 0 | `portfolio-monitor` | no |

**Tier 2: board, paper, evidence**

| rank | lever | mark | the reading that moved it | owner | betting change |
|---|---|---|---|---|---|
| **P1** | **#847 calibration everywhere** | **MOVED UP: top board lever** | H-F PASS: −0.006815 [−0.009606, −0.004426], 486 games, 38 of 41 cells. H-R still not runnable | todo #847 (lane CLOSED) | (b) no; (c)(d) yes |
| P5 | #816 spread-only | **MOVED UP** | registered flip rule met, T3 +0.00484 [90% +0.00230, +0.00737], 284 games; gain shrinking | `ncaab-total-overprojection` | yes |
| P4 | NBA engine overshoot | **MOVED UP (corroborated)** | M2's only harm is NBA live totals d_ll +0.024 (60 games). The re-sim's over-lean went +0.113 → +0.359 after F1, and the harm goes when the re-sim weight is zeroed | `basketball-scenario-calibration` | yes |
| P2 | #844 newest stamp by time | **RESOLVED** | BC-062; P1-P3 PREDICTED, P4 NEITHER | `ncaab-total-overprojection` (closing) | — |
| P3 | #834 NBA live total anchor | **RESOLVED (loaded)** | BC-060, 86 of 86 NBA ticks anchored. Its keep or revert grade belongs to its lane | `nba-live-resim-total-anchor` | — |
| P6 | NFL t0.925 | RESOLVED (loaded) | BC-059; no post-load reading yet | its lane | — |
| P15 | #842 look-ahead | RESOLVED (loaded) | BC-061; Pb0-Pb2 held | `lookahead-day2-phase-lock` | — |
| P7 | #836 end-game freshness `on` | UNCHANGED | shadow counts only (NBA 15%, NCAAF 26%, NHL 51% would refuse); no outcome grade; the named held-out check has no record of running | `engine-learner` | yes |
| P10 | #835 (+ #852, #859) NCAAF live totals | UNCHANGED | 11-21 hold-out: log loss and slope pass, the 17+ mean F−c FAILS (+1.66 vs +0.86, 43 games). The 11-28 slate decides (task 11-30 10:30 AM CST) | NCAAF lanes | yes |
| P14 | #845 Understat splice | UNCHANGED | Understat still down (`state: down`, probe 11-26 10:09 PM CST); real-gap read worse, +0.0084 [+0.0015, +0.0185], until the 12-05/06 re-run | todo #845 | yes |
| — | M2 engine learner (D-level) | **FALSIFIED as gated** | FAIL harm=1, judged 18 / pass 1; M3 never ran; M2b held | `engine-learner` | — |
| P8, P9, P11-P13, P16 | — | UNCHANGED (not re-read) | — | as §3.2 | — |

**Tier 3, and the H1 selection gap**

| item | mark | reading |
|---|---|---|
| M1 suggested grade half-blind | RESOLVED (11-20), now measured | 95.4% of staked orders sit on a graded suggested line under full coverage (§12.2) |
| The board-to-staked selection gap (H1) | **FALSIFIED as a lever** | the 16.0% was M1. With complete coverage, in − out is −4.57 [−26.55, +17.41] on 108 out-of-set orders |

**The noise list** (§7) gains, with numbers:
- live price 0.30-0.45, −12.16 [−23.86, −0.46], fails BH, halves disagree;
- live EV 2-5 net ROI −6.80, like-for-like over-statement −7.54 (p 0.055);
- the 0.55-0.70 over-statement, like-for-like −10.87 (p 0.034, fails BH);
- the STEP 2 in-vs-out split in both windows;
- complete-coverage NCAAF in-set −20.18 (p 0.037, fails BH over 9).

**Not changed:** H1 FALSIFIED, H2 HOLDS (§5). No live-money lever clears the bar. The only thing that cleared on a
forward read is calibration (#847 H-F).

### 12.5 The 12-08 window candidates (Tue 12-08 2-7 AM CST)

Every "default-off" below was verified in the code on main at `388d77705`. This run adds nothing to any window task.

| candidate | on main, default off? (the env read) | owner, and the user's words so far | evidence and prediction | betting change | verdict |
|---|---|---|---|---|---|
| **#847 (c) rank/stake** `SYNDICATE_CELL_CALIBRATION_RANK_STAKE` | yes: `cell_calibration.py:85-88,141`, on only for on/1/true/yes; read at `optimizer_overlay.py:129` | `cell-calibration-847` (CLOSED; todo #847). No load words | H-F PASS on the frozen k. Predictions (cell findings §4.1): P-c1 ≥ 1 Layer 2 score with `optimizer_factor` < 0.5 on the first build (0 before); P-c2 0 rows < 0.10 and the board's row count unchanged; P-c3 paper orders in the 25 cells stay > 0/day (3 slates at 0 = a gate, revert); P-c4 no detectable money change (≤ $6.9/day paper, live ≈ $0) | yes | **READY** on evidence; needs the user's yes |
| **#847 (d) live probability** `SYNDICATE_CELL_CALIBRATION_LIVE_PROB` | yes: same parser; read at `live_gameline_join.py:1888`; skips college totals (`:1880`, #816's) | as above | H-F covers its 7 live cells (e.g. `ncaaf|totals|full|live` −0.019, `ncaab|spreads|full|live` −0.0009). Predictions (§4.2, P-d2 revised): P-d1 the `live_cell_calibration` stamp, edge ≈ k × raw; P-d2 priceable rows in moved cells fall by less than a third (half or more in NCAAB spreads refutes it), median abs(edge) ratio k ± 0.15; P-d3 Brier improves, flags in those cells hit within ±3 pp; P-d4 fewer live orders there, no detectable P&L | yes | **READY** on evidence; needs the user's yes |
| #848 scorecard grading `SYNDICATE_SCORECARD_848_GRADING` | yes: `population_outcomes_soccer.py:68-72`, `population_outcomes_nhl.py:69,76` | `scorecard-grading-defects` (CLOSED); todo #848. No load words | grading fix; needs ONE manual `publish_model_scorecard.py --max-board-dates 40 --publish --verify` off-peak (todo #848) | yes (overlay) | NOT READY: the 40-date refill is unscheduled |
| #816 spread-only | **NO, it is a code constant** (`total_prob_calibration.py:72` `FIT_LEVEL = True`); `False` on main would load at the next ff | `ncaab-total-overprojection`; "Keep until 11-24" (11-18), nothing since | the registered flip passes (§12.1 e); prediction per its lane: refit with the level off | yes | NOT READY: needs a default-off switch, or a window-only branch, first |
| #836 `on` `SYNDICATE_LIVE_ENDGAME_FRESHNESS` | **absent = SHADOW, and any unrecognised value = ON** (`live_endgame_freshness.py:53,77-84`) | `engine-learner` (user "fix gap", 11-20); the owner asks for `on` on the user's yes | shadow counts only; dev-window refused cell +0.174 nats (se 0.053), cut set on the same dates | yes | NOT READY under this bar: no held-out outcome grade |
| #852 + #835 (+ #859) NCAAF live totals | yes: `live_blowout_damping.py:33,49,57`; `live_total_dispersion.py:93-94`; `live_endgame.py:59-63` | NCAAF lanes. The user chose "Queue for 12-08 (Recommended)" (11-20 ~9:40 AM CST, an option label, conditional) and #859 "queue the end-game load set for the 12-08 window" (11-21 ~6:10 PM CST) | 11-21: 2 of 3 checks pass. The 11-28 slate decides | yes | NOT READY until the 11-30 check |
| #845 Understat splice `SYNDICATE_SOCCER_UNDERSTAT_SPLICE` | yes: `build_soccer_artifacts.py:161,165-166` | todo #845; "queue the splice for the 12-08 window" (11-18 4:57 PM CST) | Understat still down. Real-gap worse +0.0084 [+0.0015, +0.0185]; the backtest favours it at 4+ rounds | yes | NOT READY until the 12-05/06 re-read is shown to the user (its own condition) |
| L1 hold-value exits `on` `SYNDICATE_EXIT_HOLD_VALUE` | yes: `exit_hold_value.py:52-56,80-87`, only exactly `on` / `shadow` | `hold-value-exits`; "Yes, ride 11-24" (shadow only) | shadow loaded and logging (§12.4 L1); verdict 12-07 | yes | **NOT READY** (12-07) |
| #861 one model number `SYNDICATE_LAYER2_ONE_MODEL_NUMBER` | yes: `layer2_row_context.py:400-402` | `surface-consistency-oversight`; "Queue for 12-08" (11-24 ~11:25 AM CST) | not assessed here | per its lane | queued by the user; not assessed |
| Polymarket stale cancel `LIVE_ODDS_WORKER__SYNDICATE_POLYMARKET_STALE_CANCEL` | yes: `polymarket_stale_cancel.py:100-107` (off, shadow, on) | `polymarket-stale-cancel`; "yes, add the Polymarket stale cancel to the 12-08 queue" (relayed, 11-21); final yes owed | not assessed here | per its lane | queued; not assessed |
| #857 web anon limit `WEB__SYNDICATE_WEB_WORKER_ANON_LIMIT_MB=1500` | env only, absent = today | `web-recycle-anon-limit`; "Next scheduled restart" (11-25 ~10:10 AM CST) | — | no | not a betting change |
| #850 host overdraft | not verified here | "Yes, build it" covered the build only | — | — | proposal |

**READY for the 12-08 window: #847 (c) and (d) only.** Both are calibration loads. Their money predictions are "no
detectable change"; they ship for honest rank, stake and live edges.

**Outside the window, no betting change: #847 (b) display, `SYNDICATE_CELL_CALIBRATION_DISPLAY`.**
- H-F graded exactly the probability (b) shows.
- The code adds the calibrated columns beside the raw ones and says nothing ranks, admits or stakes on them
  (`layer2_board.py:5503-5509`). The lane classified it "not a betting change". This run did not trace every reader
  of those columns.
- Loading it needs the user's OK, claims, a preflight and an env load.

### 12.6 What is owed

- **The user:**
  - #847 (b) now, or not;
  - #847 (c) / (d) for 12-08;
  - #816 needs a default-off build before it can be a candidate;
  - #836 `on` is the owner's ask, without an outcome grade.
- **The portfolio monitor:** its longshot forward read needs a model probability that 265 of 281 band bets do not
  carry (§12.3). Noted here, not acted on.
- **#847:** the H-R re-run, when NBA live and college-totals live cells are served (todo #847).
- **The calendar:** 11-27 prop holdout (L3); 11-30 NCAAF check and P1 `ev_lb` look; 12-02 #830 verdict; 12-07 L1
  verdict; 12-08 the window.

