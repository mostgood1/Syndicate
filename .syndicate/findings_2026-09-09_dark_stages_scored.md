# FINDINGS — the three dark stages were scored before being switched on. NONE of them is the lever. The funnel is 0.83% wide and model coverage is why

`[2026-09-09, lane segments-joint-v1. Counterfactual A/B with the REAL sizer over served rows, plus production's own funnel counters.]`

## Why this was scored instead of flipped

The step 5 recon ended by recommending that the dark stages be switched on "each
with a reading". **A flag flip on a live-armed executor is a decision the reading
should precede, not follow**, and `model_engine_standard.md`'s rule is
**reachability before correctness** — `off != on` — for anything behind a flag.
Both stages were run through their OWN code (`sizing_inputs_with_provenance`,
`sizing_candidate`, `compute_bet_size`), reloaded per arm, never reimplemented.

## THE PRODUCTION FUNNEL — authoritative, from `PLAN_WRITTEN`, 2026-09-10T00:11:12Z

    rows_in                  3029
      no_model_edge_pct      1872   61.8%   nfl 1503 | mlb 285 | soccer 84
      below_min_ev_pct        573   18.9%   top: totals:215
      market_family_excluded  501   16.5%   top: batter_rbis:122
      beyond_max_positions     56    1.8%   top: spreads:23
      below_min_stake           3
      zero_kelly_stake          2
    sized                      25
    positions                  22   staked $98.66  bankroll $1000 (stored)

**25 of 3,029 rows reach the sizer — 0.83%.** Every stage below acts on that 25.

`min_ev_pct = 2.0` and `bankroll = $1000` both resolve **`stored`**, not env —
the same store that overrode the execution caps this morning, read this time
from `/api/portfolio/settings`'s `sources` map rather than assumed.

## STAGE: pregame interval gate — DO NOT SWITCH ON. It is a no-op, and the reason is upstream

A/B over the 2,000 served shortlist rows, gate off vs on:

| refusal | OFF | ON |
|---|--:|--:|
| `no_model_edge_pct` | 1768 | 1768 |
| admitted | 232 | 231 |
| `prob_interval_swamps_edge` | 0 | **1** |

**ONE ROW IN TWO THOUSAND CHANGES** — a soccer `h2h` at `ev_pct = -4.54`, which
the `min_ev_pct = 2.0` floor refuses anyway. The gate's stamped verdicts say why:

    admitted 33 | no_std_err 198 | refused 1 | n/a (no model view) 1768

**198 of the 232 model rows (85.3%) are admitted under `no_std_err`.** The gate
needs `prob_std_err` or `sims_run`, and reachability by sport is decisive:

| sport | served rows | rows the gate can see |
|---|--:|--:|
| ncaaf | 836 | **0** |
| nfl | 811 | **0** |
| mlb | 242 | **0** |
| soccer | 111 | 34 |

Only soccer publishes an interval (`8b6a1f4d`, as `model_std_err_of`'s docstring
says). `model_std_err_of`'s second source, `sims_run`, fires on 5 rows.

**The docstring calls this "a deliberate, named gap ... tracked separately".
IT IS NOT A GAP, IT IS THE WHOLE SURFACE: 1.7% of the board is reachable.**
Turning the gate on buys nothing; publishing `prob_std_err` from MLB and football
projections is the prerequisite, and it is a per-sport data task.

## STAGE: Kelly-on-fair — REACHABLE, and CONSERVATIVE, but only once the EV floor is applied

The basis flips on **232 of 232** model rows (`kelly_basis` `implied` -> `fair`),
so unlike the interval gate this flag genuinely bites.

**MY FIRST READING OF IT WAS WRONG AND I CAUGHT IT BEFORE REPORTING IT.** Over
all 232 model rows, aggregate Kelly rises **+40.5%**, with 21 rows going from
zero stake to non-zero — which reads as a live-money exposure increase. **That
population is not the sizer's.** `portfolio_commit.py:835` applies
`min_ev_pct` BEFORE `sizing_candidate`, so 204 of those 232 rows (all
`ev_pct <= 0`) never reach `compute_bet_size` at all. On rows that DO:

| population | n | Kelly OFF | Kelly ON | delta | more | less |
|---|--:|--:|--:|--:|--:|--:|
| all model rows *(never sized)* | 232 | 7.5995 | 10.6789 | **+40.5%** | 128 | 13 |
| **`ev_pct >= 2.0` — what the sizer sees** | **10** | **0.1073** | **0.0795** | **−25.9%** | **0** | **4** |

The sign flip is exactly what `compute_bet_size`'s own docstring predicts: fair
stakes LESS when `ev_pct > 0` and MORE when the row is priced at or through the
hold. **The board is 88% negative-EV model rows, so the aggregate is dominated by
rows the floor already refuses.** Quoting +40.5% would have been a correct
arithmetic over a population that does not exist downstream — the same category
error as the entry-cost +4.1.

Direction on the real population: **conservative, ~−26%, closing 1 of 4 staked
rows.** Note it is a REALLOCATION, not only a reduction: `beyond_max_positions`
refused **56 rows**, so a freed slot is immediately refilled.

## STAGE: pricing calibration — NOT READY, and this is not a judgement call

`pricing_calibration_enabled` is absent-is-off; turning it on without a fitted
profile applies an identity transform AND stamps four new fields on every served
row, which is the exact outcome its docstring says the flag exists to prevent.
`scripts/fit_probability_calibration.py` must run and be scored first. **No flip
should be proposed for this one.**

## WHAT THE LEVER ACTUALLY IS

**`no_model_edge_pct` = 1,872 of 3,029 (61.8%), and NFL is 1,503 of it** — top
market `receiving yards:473`. That single term is larger than every stage effect
measured here by two orders of magnitude, and it is the work already in flight on
NFL prop projections. `sim_share=0.1214` on the same build corroborates it
independently.

**The three dark stages are not the reason the platform stakes $98.66. Model
coverage is.** Step 5's remaining value is the stamped stage trace and the
collapse of decision paths 2–5 — not a flag.

## LIMITS OF THIS READING, STATED BECAUSE THE DENOMINATOR IS THE FINDING

- **`/api/board/layer2-shortlist` CAPS AT 2,000.** `returned=2000` at both
  `limit=2000` and `limit=20000`, `per_sport_limit=2000`, against 5,228 selected
  and `opportunities_considered=20948`. **Every A/B percentage above is over that
  top-2,000 view, not the 3,029 rows the commit reads** (`run_portfolio_commit`
  takes `read_layer2_shortlist(date)["rows"]`, not this endpoint). I checked this
  before writing the numbers down, having read a default page cap as a slate once
  already today. Structural results (which sports carry an interval; that the
  basis flips on every model row; the sign of each effect) do not depend on it;
  the magnitudes do.
- My A/B does not apply `market_family_excluded` (501 rows) or
  `beyond_max_positions`, so my sized count (10) is below production's (25).
- One slate, one day, MLB/NFL/NCAAF/soccer as served at 2026-09-10T00:00Z.
