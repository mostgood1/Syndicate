# Wind and QB practice status carry NO information beyond the NFL QB prop line -- lane `nfl-qb-prop-unpriced-inputs`

2026-10-09, session f628c245. Pre-registered in `lanes.md` (c6269fc6) before any number. Measurement only.
Substrate: `checkout` (OddsAPI historical quotes kickoff -10 min, two-sided, de-vigged per book; nflverse schedules
and injury reports). Script `scripts/measure_nfl_qb_prop_unpriced_inputs.py`; report
`C:\tmp\football_scenarios\passing_yards_coin\unpriced_inputs_report.json`. 2025 not read.

Why these two: the ledger had already ruled out pbp usage inputs (recency, share, injury redistribution;
`findings_2026-10-03_nfl_prop_mean_inputs.md`, corr <= 0.08), market-only edges (`..._nfl_off_market_edge.md`) and
sim game-script attribution (`findings_2026-10-07_football_player_attribution.md`). Practice participation was named
there as untested; game-day wind had never been tested for QB props.

## Test

Per input x and market: `y ~ a + b1*logit(p_book) + b2*x` on 2023, applied to 2024; game-clustered CIs.
`wind` = mph for outdoor/open games (dome/closed/missing = 0); `limited` = QB listed Limited or DNP that week.

| market | input | fit 2023 n / games (x != 0) | b2 [95% CI] | held 2024 n (x != 0) | LL book | LL combined | combined - book [95% CI] |
|---|---|---|---|---|---|---|---|
| passing_yards | wind | 4,110 / 127 (2,259) | -0.022 [-0.107, +0.020] | 5,984 (3,757) | 0.6706 | 0.6712 | +0.0005 [-0.0066, +0.0073] |
| passing_yards | limited | 4,110 / 127 (94) | +0.46 [-1.52, +2.92] | 5,984 (107) | 0.6706 | 0.6741 | +0.0035 [-0.0026, +0.0101] |
| passing_attempts | wind | 1,540 / 124 (866) | -0.014 [-0.057, +0.023] | 2,445 (1,554) | 0.6935 | 0.6940 | +0.0005 [-0.0041, +0.0050] |
| passing_attempts | limited | 1,540 / 124 (38) | -0.99 [-26.4, +1.1] | 2,445 (43) | 0.6935 | 0.6894 | -0.0041 [-0.0100, +0.0015] |

## Verdict

**Hypothesis confirmed in all four cells.** No b2 CI excludes 0 and no combination beats the book on 2024.
Wind is well powered (thousands of rows with wind > 0) and is simply priced by a kickoff-10min line. Practice is
UNDERPOWERED as pre-registered (38-107 rows a season), so it is "not shown", not "shown absent"; its 2024 point
estimate on attempts (-0.0041) leans the right way but its CI spans 0 and its fit CI is degenerate.

**Cumulative reading for NFL QB props at the kickoff line:** model probability, pbp usage, sim game script,
market-only signals, wind and practice status have all been tested; none adds information the line lacks. A kickoff
line in these markets looks efficient against every public input this platform holds. The only remaining direction
is TIMING (beating the line before it moves), which is a CLV question, not a model-input one.
