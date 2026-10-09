# NFL QB props carry NO information beyond the book line -- lane `nfl-qb-prop-info-beyond-line`

2026-10-09, session f628c245. Pre-registered in `lanes.md` (c7a2085e) before any number. Measurement only.
Substrate: `checkout` (OddsAPI historical quotes, kickoff -10 min, two-sided, de-vigged per book; nflverse pbp);
evidence about the CODE (018a7c64, the version live on the fleet), not about served rows.
Script: `scripts/measure_nfl_qb_prop_info_beyond_line.py`; report `C:\tmp\football_scenarios\passing_yards_coin\info_beyond_line_report.json`.

## Test

`y ~ a + b1*logit(p_book) + b2*logit(p_model)` fitted on real 2023 quotes, applied unchanged to real 2024 quotes.
p_model = current production (starts-only rate, official attempts; under-2-starts rows excluded because production
refuses them). Game-clustered bootstrap CIs. 2025 not read.

| market | fit 2023 n / games | b1 (book) | **b2 (model) [95% CI]** | held 2024 n / games | LL book | LL model | LL combined | **combined - book [95% CI]** |
|---|---|---|---|---|---|---|---|---|
| passing_yards | 3,853 / 126 | 1.13 | **-0.24 [-0.78, +0.19]** | 5,702 / 231 | 0.6707 | 0.7074 | 0.6707 | **0.0000 [-0.0063, +0.0070]** |
| passing_attempts | 1,445 / 123 | 1.15 | **-0.10 [-0.81, +0.63]** | 2,329 / 229 | 0.6934 | 0.7595 | 0.6910 | **-0.0024 [-0.0064, +0.0021]** |

## Verdict

**Hypothesis confirmed, falsification not met, in both markets.** Once the line is known, the model's probability
adds nothing: b2's point estimate is negative and its CI spans 0, and the combined probability does not beat the
book out of sample. The model's own LL (0.7074 / 0.7595) is worse than the book's (0.6707 / 0.6934).
Consistency check: passing_yards LL_model 0.7074 equals the pre-registered starts-only read on the same rows.

**What this means for the board:** the 10-07/08 fixes (refusal, starts-only rate, official attempts) removed biases
that made the model actively harmful; they did not create an edge. A model edge on these markets is, on this
evidence, noise around the line -- each line remains its own decision (standing rule), but the model's side of it
has no measured value here. An edge would need inputs the line does NOT already price (none identified here);
that is a new lane, not a tuning pass on this model.
