# Product optimization program — one ranked lever table from Syndicate's own performance data

Lane `product-optimization-program`, session 3bf4646c (started by the rail monitor, `local_62433e58`).
User, 11-18 ~6:05 PM CST, in the rail monitor session: "we need to then take all this data to optimize the overall
Syndicate product".

Substrate: the fleet's disk (`~/syndicate-prod/data`) and `http://127.0.0.1:10000`, read-only, `nice -n 19`. Never the git
`data/` mirror. Times are Central.

## 1. Pre-registration (committed before any lever result was read)

Written 11-18 ~7:00 PM CST, before the four evidence passes (A scorecard funnel, B live book, C rail flags and cheat
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

## 2. Lever table

(Filled from the evidence passes; see §3 for each pass's method and its noise list.)
