# NBA quarter/half lines: does the raw sim earn any weight against the market? — PRE-REGISTRATION (todo #818)

Written 2026-11-16 ~5:30 PM CST, before any outcome below is read. User, 2026-11-16: "do the NBA segment re-grade
too", then, told no NBA segment grade exists, chose "Grade it now": register tonight, grade the regular-season games
already played in its own session, and re-grade on Mon 2026-12-07.

## Why, and how this differs from #752 (NFL) and #805 (NCAAF)

- **No NBA segment grade exists.** `measured_market_skill` has no NBA entries.
- **The board serves NBA quarter/half lines at the market's own price.**
  - `nba_game_projections._project_row` prices every h1/h2/q1-q4 row from the game's smart-sim histogram, then
    serves `served_game_probability`. That is a logit blend toward the de-vigged book:
    `blend_with_book(p_model, p_book, w)`.
  - The fleet's `nba_source/data/processed/nba_game_book_blend.json` (read 2026-11-16 23:0xZ, lane
    `nba-prop-calibration`, 2026-10-05):
    - w: `h2h:full` 0.0, `spreads:full` 0.0, `totals:full` 0.05, `default` 0.0;
    - provenance: "periods: unmeasured -> default 0 (the market)".
  - So every NBA period row is served at w = 0: the book's own fair, edge 0.
- **A grade of the SERVED number would read parity by construction.** The open question is the one the provenance
  names: do the raw sim's period probabilities carry anything beyond the line, enough to earn w > 0?
- The full-game weights came from `scripts/backtest_nba_lines_props.py --diagnose`, 2025-26: a fitted raw-sim
  weight of 0.00 on margin and 0.05 on total. That is the prior here.
- **The sim is market-anchored at the full-game level** (`market_anchor`: total_w 0.7, margin_w 0.95). Its period
  structure (how the anchored total and margin split across quarters) is its own.
- Other lanes have read 2026 NBA results (e.g. `findings_2026-11-07_basketball_interval_backtest.md`). This
  registration was written without reading them or any period outcome.

## Population

NBA 2026-27 **regular season** games (production's `nba_game_projections.season_phase_for_date` == "regular"), tips
**2026-10-20 12:00Z .. 2026-11-16 12:00Z** (through Sunday 11-15's games). A game x segment x market is graded if it
has all three of:
- (a) **a pregame quote** (`captured_at < commence_time`) on segment h1/h2/q1/q2/q3/q4 and market `totals`, `spreads`
  or `h2h`, in the fleet's `nba_source/tracking/book_quotes/<date>.jsonl.gz`.
  - These are the main markets only, as #752. The `_alt` and `h2h_3_way` markets are excluded.
  - Read 11-16 (counts only): every NBA event on 10-21, 11-04 and 11-12 carries quotes on all six segments.
- (b) **a sim histogram the board could have served before tip.**
  - The game's `smart_sim_<date>_<HOME>_<AWAY>.json`, found through production's bridge
    (`nba_game_projections.load_nba_game_projections`), must have a `score.dist.segments` block for the segment.
  - Its fleet **mtime** must be strictly before tip. The file carries no generation stamp, so copy it with `cp -p`.
  - The file is rewritten through the day. One written after tip is not the pregame file and is refused
    `sim_written_after_tip`, and the refusal is counted.
  - **If more than half the games are refused this way,** the result states which slice it rests on (e.g. by tip
    hour).
- (c) **a final ESPN NBA linescore.**

Expected size (not a target): smart-sim files exist for about 197 game-dates 10-20..11-15. The count-only run sets the
real number.

## Method

**Grader:** a new `scripts/nba_segment_skill.py`.
- It reuses `scripts/nfl_segment_skill.py` (blob `020cb082b5a9`) unchanged for the de-vig, consensus line, framing,
  outcome rule and statistics.
- If any of those needs an NBA change, it is a copy with the diff reported.
- **The grader's blob is committed to main after a `--count-only` run (which reads no box) and BEFORE any outcome
  is read.** The results cite that blob.

**Pricing:**
- Market: each book's last pregame two-sided pair, de-vigged proportionally; the consensus line (most books, ties to
  the median); the market probability is the mean of the de-vigged books at that line.
- Model (RAW): production's `_projection_from_dist(row, market, block, segment=..., sims=...)` `model_prob_over` at
  the consensus line. This is the probability BEFORE `served_game_probability`, in production's home/over framing.
- Box: production's `segment_actuals` rule for NBA (`segment_score_pair("nba", ...)`). Report how many games went
  to OT and which segments the rule puts OT in (#745's book-rule findings).
- Pushes are dropped.

**Statistics:**
- Unit: game x segment x market. Families: totals, spreads, h2h, each pooled over the six segments.
- Bootstrap: game-clustered, 2,000 reps, **seed 818**, for every CI below.
- PYTHONHASHSEED=0, Idle priority.

## Gates

**G1 — the raw sim against the market (all graded games).**
- Per family: dBrier = Brier(raw) - Brier(market), with its CI.
- Verdict: beats if the CI's upper bound < 0, loses if its lower bound > 0, else parity.
- Also #752's logistic table: the outcome on logit(market) + logit(raw), giving the model's weight beside the
  market and each side's calibration slope.

**G2 — does a family EARN a period weight? (the decision gate)**
- FIT window: tips before 2026-11-02 12:00Z. TEST window: tips 2026-11-02 12:00Z .. 2026-11-16 12:00Z.
- Per family, on FIT: w_fit = the w on the grid {0, 0.05, ..., 1.0} minimising the Brier of production's
  `blend_with_book(p_raw, p_market, w)`. Ties go to the smaller w.
- On TEST: d = Brier(blend at w_fit) - Brier(market), with its CI.
- **A family earns a weight only if w_fit > 0 AND the TEST CI's upper bound < 0.** Otherwise it stays at 0.
- Per-segment fits are reported, not gated.

**G3 — engine read (descriptive, not gated).**
- Per segment: the sim's mean total and margin vs the actual (bias with CI), the PIT outer-20% share of totals, and
  quarter shares.
- `market_anchor.model_margin_raw`: the one file read while registering (`smart_sim_2026-11-12_MIN_DAL.json`) has
  exactly 0.0. Report how many graded games carry exactly 0.0, as a possible upstream defect for the NBA sim's
  owners. It is not fixed here.

## Predictions, registered now

| # | prediction |
|---|---|
| P1 | G1: no family beats the market. Totals and spreads read loses or parity; h2h reads parity. |
| P2 | G2: w_fit = 0 for spreads and h2h; totals w_fit <= 0.10. |
| P3 | G2: no family earns a weight. |
| P4 | G3: the sim's full-game mean total is within 1.5 points of the actual, and at least one quarter's mean-total bias CI excludes 0. |

## The Dec 7 re-grade (scheduled by the grading session once its grader blob is on main)

- **Population:** regular-season tips 2026-11-16 12:00Z .. 2026-12-07 12:00Z, same conditions (a)-(c).
- **G1** is re-run on those games. **G2's TEST** is re-run with each family's w_fit FROZEN from this grade, as a
  fresh held-out.
- Same grader blob and seed.
- It runs as a one-time task, Mon 2026-12-07 1:00 PM CST, after the NCAAF re-grade at 10:00 AM.

## What the result is allowed to change

- **Nothing is changed by the grade itself.** It writes results here, plus the todo, the log and a deploys.md
  READING.
- **If a family earns a weight,** the candidate change is per-segment keys (`<family>:h1` .. `<family>:q4` at
  w_fit) in the fleet's `nba_game_book_blend.json`. That changes served NBA period probabilities and edges: the
  user decides, with the Dec 7 re-grade as the held-out confirmation.
- **If none earns,** w = 0 stands, now measured. Rewriting the file's provenance line is also a fleet data edit, so
  it too is the user's call.
- **Out of scope:**
  - `measured_market_skill` entries for NBA segments: at w = 0 the served row is the market, so there is no edge
    to rank.
  - The `_alt` and `h2h_3_way` markets.
  - Live rows.
  - The WNBA.

## Data (copied read-only from the fleet, never written back)

- Quotes: `~/syndicate-prod/data/nba_source/tracking/book_quotes/`, the date files 2026-10-19 .. 2026-11-16
  (`.jsonl.gz`, or `.jsonl` for a day still being written). Not the `.state.json` files.
- Sims: `~/syndicate-prod/data/nba_source/data/processed/smart_sim_<date>_*.json` for dates 2026-10-20 .. 2026-11-15,
  copied with `cp -p` (the mtime is the as-of evidence).
- The season-phase source production reads (`season_phase_for_date`) and `nba_game_book_blend.json`, for the record.
- Linescores: ESPN NBA scoreboard, cached to `linescores.json` in the run directory.
- Run directory: `C:\tmp\nba_seg\` (new).
