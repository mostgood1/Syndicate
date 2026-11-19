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
