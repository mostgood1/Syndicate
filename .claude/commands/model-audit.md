# Syndicate model-audit brief

Run this in Claude Code, which has the repo. Save findings to `.syndicate/` so
the other lanes and any scheduled job can read them.

Answer in order. Where the answer is "doesn't exist," say so plainly rather than
describing what the code could do — an absent backtest is the most important
finding in the audit, not a gap to paper over.

---

## 1. Inventory

- Where are model definitions? One module per sport, one generic module, or
  scattered through the refresh scripts?
- List every **sport × market** pair that produces a prediction today (e.g. MLB
  moneyline, MLB totals, EPL 1X2, NBA spread). Count them.
- Do the models share a common interface (fit / predict / feature builder), or
  does each sport reimplement its own pipeline?
- Which models are actually invoked at runtime vs. left over from earlier work?
  Grep call sites, don't infer from filenames.

**Why this matters:** the pair count is the number of things needing independent
calibration and monitoring. If it's above ~10 and there's no shared harness,
breadth is the problem before anything else is.

---

## 2. Validation — the highest-priority section

- Is there a backtest at all? Where?
- Is it **walk-forward** — trained only on data preceding each prediction — or a
  random train/test split? A random split on time-series sports data produces
  inflated results that will not survive contact with live betting.
- What does it score against?
  - **Outcomes** (did the bet win) — high variance, needs seasons of data
  - **Closing line** (did the model beat the market's final price) — far more
    statistical power, and the answer we want
- Are results reported per sport, or pooled into one aggregate number? Pooled
  numbers hide the usual pattern: one sport carrying several that lose.

### Point-in-time correctness — check this specifically

The most common silent failure in homegrown sports models. For each feature
source, ask: **would this value have been available, with this value, at the
moment the prediction was made?**

Concrete traps to grep for:

- Season-to-date aggregates (team ERA, xG, pace) recomputed from a current
  stats table rather than stored as-of the game date. If the table is
  backfilled or overwritten, every historical backtest sees end-of-season
  numbers when predicting April games.
- Closing line or closing-line-derived values used as features.
- Lineup, injury, or weather data whose timestamp is the *fetch* time rather
  than the publish time.
- Any `ORDER BY ... LIMIT 1` on a stats table without a date filter.
- Ratings systems (Elo and similar) rebuilt over full history at inference
  time instead of replayed forward.

Report each feature as point-in-time safe, unsafe, or unknown.

---

## 3. Closing-line value instrumentation

- Do we store, for every prediction: timestamp, model probability, the market
  line **at prediction time**, and the **closing** line? Any missing piece makes
  CLV uncomputable after the fact.
- If storage exists, produce CLV per sport, per market, per confidence bucket.
- If it doesn't: what's the smallest change that starts capturing it? Prefer
  appending to what the publish path already writes over building new
  infrastructure.

This is the measurement that decides where modeling effort goes. Everything in
section 6 depends on it.

---

## 4. Coverage vs. edge

- Do user-facing projections and edge/value picks come from the same code path?
- Is there a confidence or threshold gate, or does every game get a pick?
- If a model has no real signal for a matchup, what does it output — a
  market-anchored prior, or a number invented from thin features?

The goal is one model with two presentation layers: projections render
everywhere, edges surface only above a measured threshold.

---

## 5. Devigging

- Where are quoted odds converted to implied probabilities? One place or many?
- Which method — multiplicative, additive, Shin, power? Is it consistent across
  two-way and three-way markets?
- Multi-book handling: is there a consensus, and are books weighted?

Inconsistent devigging makes CLV numbers incomparable across sports, so this
needs to be right before section 3's output means anything.

---

## 6. Cost linkage

Tie the modeling layer back to the egress and sweep work:

- Which sports and markets drive artifact count and artifact **bytes**? Do the
  large artifacts (the 11.6 MB tail from the first-byte sample) cluster by
  sport?
- What sets sweep cadence today, and is it uniform across sports?
- For each sport: how fast do lines actually move? Sport-aware cadence should
  follow line-movement speed and measured edge, not byte cost alone — thinning
  sweeps also thins the line-movement history that features depend on.

---

## 7. Output

Write to `.syndicate/` as a dated audit note:

1. Sport × market inventory with counts
2. Validation verdict — walk-forward or not, scored against what, point-in-time
   findings per feature
3. CLV status — available, or the smallest change to start capturing it
4. Ranked list of what to fix, most load-bearing first

Do not change code in this pass. This is a read-only audit; findings first, then
a separate lane per fix.
