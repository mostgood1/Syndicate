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
- **ADDENDUM: a descriptive split by engine.** Registered 2026-11-17 12:42 PM CST (18:42Z), before any re-grade
  outcome exists; user: "Yes, add the split".
  - **Why:** todo `#821` F1 was switched on at 2026-11-17 17:35:08Z (11:35 AM CST). See the `deploys.md` entries at
    17:34:59Z and the verification at 17:45:20Z. From then on, the NBA sim takes the game model's numbers, with the
    injury penalties off. The re-grade window (11-16 12:00Z .. 12-07 12:00Z) therefore holds sims from two engines.
  - **Arms**, read from each sim's own `market_anchor`:
    - **F1**: `game_model_fed` is true AND `nba_total_inputs.skip_outs_penalties` is true.
    - **PRE**: `game_model_fed` is absent or false AND `skip_outs_penalties` is absent or false.
    - **MIXED**: anything else. It is counted and named, but not graded.
    - Each arm is cross-tabbed against the sim's fleet mtime before/after 17:35:08Z, and any disagreement is named.
  - **Method:** the frozen grader, unchanged, runs once per arm. Each run uses a copy of the data root that holds
    only that arm's sims, so the other games refuse `no_smart_sim_file`. Quotes, linescores, window, seed and frozen
    w are the same as the main run.
    - Check: each arm's graded games + the other arm's + MIXED = the main run's graded games.
  - **Reported per arm and family:** G1 dBrier with its CI, and G2's frozen d with its CI.
  - **It changes nothing registered.** The verdicts, P1/P3/P4 and any weight confirmation rest on the whole
    population; the split alone cannot confirm or refute a weight. PRE holds only sims written before 11:35 AM CST
    11-17, so its CIs will be wide.
  - **Other loads:** any other NBA sim engine load inside the window is named with its time (from `deploys.md`; for
    example `#820`'s h2-includes-OT switch). No further split is graded.

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

## COUNT-ONLY (2026-11-16 6:46 PM CST, before any outcome was read) — session 24d2e336, lane `nba-segment-grade`

- **Grader on main BEFORE the graded run:** `scripts/nba_segment_skill.py` blob `d43e9de2d4d7`, commit `43aa06ec6`
  (pushed 6:56 PM CST). Tests `tests/test_nba_segment_skill.py` (5 pass: bridge, as-of refusal, phase/window
  refusals, count-only reads no box, G2 tie rule).
- It imports `nfl_segment_skill.py` (blob `020cb082b5a9`) **unchanged** for `iter_quotes`, `consensus_markets`,
  `segment_outcome`, `grade`, `clustered_ci`, `brier`. No copy, so no diff to report.
- **Copy** (read-only, `wsl -- bash /mnt/c/tmp/nba_seg/copy.sh`, 00:45:50Z..00:46:31Z): 27 quote files (10-20 ..
  11-16; the fleet has no 10-19 or 11-03 file, and 11-15 / 11-16 were still `.jsonl`), 197 sims 10-20 .. 11-15
  (`cp -p`; Windows mtime and size match the fleet `stat` for 197 of 197, manifest `smart_sim_fleet_stat.tsv`), 29
  `game_cards_<d>.csv` (10-19 .. 11-16), 28 phase scoreboards, `nba_game_book_blend.json`.
  - **Not in the registration's Data list, and needed to follow it:** production's bridge
    (`load_nba_game_projections`) finds a game's sim through `game_cards_<d>.csv`, so those were copied too.
- **Population (count-only reads no box, so it is conditions (a) + (b)):**

| | games | game x segment x market |
|---|---|---|
| quoted (pregame, main markets, six segments) | 205 | 3,690 |
| refused `outside_window` | 8 | 144 |
| refused `sim_written_after_tip` | 3 | 54 |
| **eligible** | **194** | **3,492** (1,164 per family) |

  - Every eligible game carries all 18 segment x market cells. No refusal for phase, bridge, histogram or model.
  - 25 slate dates, 10-21 .. 11-15 (2 to 15 games each). The 3 as-of refusals are 3 of 197 sims: the 10-20 slate's
    three games (no 10-20 game is eligible, and 10-20 has 3 sims; the tip freeze went live 10-21 11:56 AM CT). So the
    "more than half refused" clause does not apply.
  - The eligible sims were written 2.0 to 1,296 minutes before tip (median 70).

## RESULTS (graded 2026-11-16 7:01-7:06 PM CST) — session 24d2e336, lane `nba-segment-grade`

**Verdict: no family earns a period weight; w = 0 stands, now measured. The raw sim LOSES to the market in all three
families.** P1 failed (h2h reads loses, not parity), P2 failed (spreads and h2h fit w > 0), P3 held, P4 held.

- **Grader:** `scripts/nba_segment_skill.py` blob `d43e9de2d4d7` (main `43aa06ec6`, pushed 6:56 PM CST, before this
  run), with `nfl_segment_skill.py` blob `020cb082b5a9` unchanged (`git hash-object` of both matched at run time).
  Seed 818, 2,000 reps, PYTHONHASHSEED=0, Idle. Output: `C:\tmp\nba_seg\result.json` and `result.obs.json`; ESPN
  cache `linescores.json` (29 dates 10-19 .. 11-16, 205 events).

### Population actually graded

- **192 games, 3,399 game x segment x market** (totals 1,151, spreads 1,150, h2h 1,098). Tips 10-21 23:00Z ..
  11-16 02:10Z (10-21 6:00 PM .. 11-15 8:10 PM CST), 25 slate dates. 11 of the 192 went to overtime.
- **Refused (markets / games):** `outside_window` 144 / 8 (the 11-16 slate); `sim_written_after_tip` 54 / 3 (the
  10-20 slate, sims rewritten 04:08Z 10-21 = 10:08 PM CST 10-20); `push` 57 markets in 52 games; `no_espn_event` 36 / 2.
- **The 2 `no_espn_event` games are a defect in my join, not condition (c).**
  - Their sims carry an NBA.com id, not ESPN's: `smart_sim_2026-10-31_NOP_ATL` 22600149 and
    `smart_sim_2026-11-07_IND_DEN` 22600189. ESPN has a final box for each (401909898, 401909938).
  - So the registered population is 194 games, and the frozen grader graded 192 of them.
  - **Descriptive sensitivity** (not the registered result): `C:\tmp\nba_seg\sensitivity_2games.py`
    (-> `sensitivity_2games.json`) re-runs the same grader with a name/date box match when the id misses. 194 games.
    Every G1 verdict and every G2 "earns" is unchanged. Spreads w_fit moves 0.20 -> 0.15 (TEST d +0.00051
    [-0.00021, +0.00129]); totals and h2h w_fit are unchanged.
- **Whole-number lines:** 86 observations. On these, production's `_dist_prob_over` keeps the push mass in the
  denominator, so the raw P(over) + P(under) < 1. That is production's number, graded as served.
- **Overtime:** production's `segment_score_pair("nba")` puts every OT period in `h2`; `q4` is the fourth quarter
  alone; `h1` and `q1`-`q3` never see OT.

### G1 — raw sim vs the de-vigged consensus (all graded games)

| family | lines | games | Brier raw | Brier market | dBrier | 95% CI | verdict | logistic w_market / w_model | slope raw / market |
|---|---|---|---|---|---|---|---|---|---|
| totals | 1,151 | 192 | 0.26218 | 0.24950 | +0.01268 | [+0.00560, +0.01976] | **loses** | 0.859 / -0.082 | 0.012 / 0.771 |
| spreads | 1,150 | 192 | 0.25262 | 0.24825 | +0.00437 | [+0.00057, +0.00816] | **loses** | 1.402 / -0.112 | 0.202 / 1.297 |
| h2h | 1,098 | 192 | 0.23661 | 0.23125 | +0.00536 | [+0.00141, +0.00940] | **loses** | 1.257 / +0.045 | 1.151 / 1.290 |
| pooled | 3,399 | 192 | 0.25068 | 0.24318 | +0.00750 | [+0.00408, +0.01127] | loses | 1.301 / -0.075 | 0.446 / 1.241 |

- **Nothing beyond the line:** w_model is about 0 in every family.
- **The raw totals carry no information on the outcome at all:** a calibration slope of 0.012.
- **Per segment (reported, not gated):** 15 of 18 read parity, with n of about 190 each.
  - The 3 that lose: totals/h2 +0.0273 [+0.0110, +0.0444], totals/q4 +0.0172 [+0.0022, +0.0324], spreads/h2
    +0.0089 [+0.0009, +0.0166].
  - None beats the market. The full per-segment table is `result.json` `g1.by_segment`.

### G2 — does a family EARN a period weight? (FIT tips < 11-02 12:00Z: 88 games; TEST 11-02 12:00Z .. 11-16 12:00Z: 104 games)

| family | w_fit | FIT n | TEST n | Brier blend / market (TEST) | d | 95% CI | earns? |
|---|---|---|---|---|---|---|---|
| totals | **0.00** | 528 | 623 | 0.25022 / 0.25022 | 0 | [0, 0] | no (w_fit = 0) |
| spreads | **0.20** | 527 | 623 | 0.25038 / 0.24970 | +0.00068 | [-0.00026, +0.00172] | no |
| h2h | **0.25** | 504 | 594 | 0.22662 / 0.22535 | +0.00127 | [+0.00010, +0.00247] | no; the fitted blend is WORSE on TEST |

- On FIT, the gain from w_fit over w = 0 was tiny: spreads Brier 0.246539 -> 0.246396, h2h 0.238200 -> 0.237861
  (the full curve is `result.json` `g2.families.<family>.fit_curve`).
- **Neither gain carried to TEST.**
- **Per-segment fits (reported, not gated):** w_fit ranges 0 .. 0.8. None has a TEST CI wholly below 0. Two have a
  TEST CI wholly ABOVE 0 (the fitted blend hurts): h2h/h1 (w 0.8) +0.0109 [+0.0011, +0.0204] and h2h/q2 (w 0.6)
  +0.0085 [+0.0016, +0.0150]. These are noisy fits on about 85 games.

### G3 — engine read (descriptive; the 192 graded games, each game's as-of sim)

| segment | sim mean total | actual | total bias [CI] | margin bias [CI] | PIT outer-20% |
|---|---|---|---|---|---|
| full | 228.60 | 227.72 | +0.87 [-1.72, +3.45] | -0.42 [-2.44, +1.62] | 0.172 |
| regulation | 228.10 | 226.33 | +1.76 [-0.70, +4.37] | -0.35 [-2.42, +1.69] | 0.167 |
| h1 | 114.40 | 113.88 | +0.52 [-1.23, +2.13] | +0.25 [-1.42, +1.84] | 0.151 |
| h2 | 113.70 | 113.84 | -0.14 [-2.26, +1.79] | -0.68 [-2.13, +0.82] | 0.219 |
| q1 | 57.23 | 56.49 | +0.74 [-0.40, +1.87] | -0.37 [-1.60, +0.89] | 0.135 |
| q2 | 57.16 | 57.39 | -0.22 [-1.40, +1.08] | +0.61 [-0.62, +1.77] | 0.167 |
| q3 | 56.98 | 57.59 | -0.61 [-1.89, +0.62] | -1.20 [-2.50, +0.01] | 0.161 |
| q4 | 56.72 | 54.86 | **+1.86 [+0.60, +3.10]** | +0.60 [-0.47, +1.77] | 0.151 |

- **Quarter shares, sim vs actual:** q1 0.250 / 0.248, q2 0.250 / 0.252, q3 0.249 / 0.253, q4 0.248 / 0.241.
  - The sim spreads scoring evenly across the four quarters. The real fourth quarter is the lowest-scoring and the
    third the highest, and q4 is the one bias whose CI excludes 0.
- **PIT outer-20% is below 0.20 in every segment except h2,** so outcomes land in the middle of the sim's
  distribution too often: the period distributions are too wide.
- **`market_anchor.model_margin_raw` is exactly 0.0 in 72 of 192 graded games (37.5%)**; it is nonzero in 120.
  - In those 72 games, the anchored margin is 0.95 x the market spread plus nothing from the sim's own margin model.
  - This is a possible upstream defect for the NBA sim's owners. It is not fixed here.
- **Possible upstream defect: the pregame sim's `h2` histogram excludes overtime.**
  - `basketball_props_smart_sim._SIM_DIST_SEGMENTS_LOCAL` builds `h2` from quarters (2, 3) only, while the box rule
    and the books settle `h2` with every OT. 11 of the 192 games went to OT.
  - The live re-sim's `h2` already takes OT (`nba/live_resim._segments`); the pregame `score.dist` does not.
  - totals/h2 is the worst-losing segment (+0.0273). That is consistent with the mismatch but not shown to be caused
    by it. Not fixed here.

### Predictions

| # | prediction | result |
|---|---|---|
| P1 | no family beats the market; totals and spreads loses or parity; h2h parity | **FAILED**: none beats and totals/spreads lose, but h2h LOSES (+0.00536 [+0.00141, +0.00940]), not parity |
| P2 | w_fit = 0 for spreads and h2h; totals w_fit <= 0.10 | **FAILED**: spreads 0.20, h2h 0.25 (totals 0.00 holds) |
| P3 | no family earns a weight | **HELD** |
| P4 | full-game mean total within 1.5 pts of actual, and >= 1 quarter's total-bias CI excludes 0 | **HELD**: full +0.87; q4 +1.86 [+0.60, +3.10] |

### What this changes

- **Nothing was changed.** `nba_game_book_blend.json` stays at w = 0 on every period, now measured. Rewriting its
  `periods: unmeasured` provenance line is a fleet data edit and the user's call.
- **No decision is owed on weights,** since no family earned one.
- **Dec 7 re-grade:** scheduled task `nba-segment-regrade-818`, Mon 2026-12-07 1:00 PM CST. Tips 11-16 12:00Z ..
  12-07 12:00Z, same blob and seed. G2 TEST runs with the weights FROZEN from this grade: totals 0.00, spreads 0.20,
  h2h 0.25 (`--frozen-w totals=0,spreads=0.2,h2h=0.25`).
