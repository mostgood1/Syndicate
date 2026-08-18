# Plan — make MLB the best sim engine we have, accurate AND beating the market

> Written 2026-08-17, lane `convergence-phase7-crps`, after the falsification
> test came back NEGATIVE. Every number here is tagged `[measured]` or
> `[from-code]`; anything untagged is an argument, not a fact.
>
> **Read the caveat in §0 before using any of this to justify work.**

---

## 0. The finding that sets the framing

**MLB hitter props LOSE to the market in every clean family.** `[measured
2026-08-17, 12 dates, 5,437 rows]`

| family | n | model Brier | market Brier | gap |
|---|---|---|---|---|
| hits | 1529 | 0.24318 | **0.23315** | +0.0100 |
| runs | 1442 | 0.23230 | **0.23081** | +0.0015 |
| total_bases | 1161 | 0.24854 | **0.24188** | +0.0067 |

I expected this to come back positive and said in advance that a negative result
would change the direction. It did, so it does.

**But read the magnitude.** These are gaps of 0.0015–0.010 Brier, not a rout.
This is a model carrying real conditional signal (r = 0.13–0.16 `[measured
08-14]`) landing just behind the price. **The programme is therefore "close a
measured gap", not "scale an existing edge", and not "the engine is worthless".**

**Nothing in this plan may be promoted on the assumption that an edge exists.
None has been demonstrated.**

---

## 1. Where to aim, and why it is not game lines

`[measured, from state.md]`

| market | sharp reference coverage |
|---|---|
| MLB **game lines** | **102 of 102 = 100%** (pinnacle, betfair_ex_eu, matchbook) |
| MLB **props** | **0%** |

Game lines are priced by sharps and our live game-line model already **loses to
the market** (Brier +0.03842 over 3,638 records, worst on the rows we publish,
+0.056 on `priceable_only`) `[measured 08-17]`. Beating Pinnacle is the hardest
problem in the building and we are not close.

Props are priced by soft books with no sharp anchor, and price shopping alone was
measured at **+2.79 ROI points** there. **Props remain the right target** — the
market is beatable in principle; we simply do not beat it yet.

---

## 2. What is actually wrong, per market

### 2a. Pitcher outs — DO NOT INVEST. Serve `unmeasured`.

`[measured 2026-08-17, n=267, 1000 sims]`

    corr(sim_mean, actual)  = +0.05
    sd(forecast) = 1.19 outs   vs   sd(actual) = 4.06 outs
    skill vs climatology       = -6.74%

The engine predicts nearly the same value for every start. **A calibration layer
cannot fix an r of 0.05** — proven on hold-out: at production's leash a scalar
shift recovers +3.08 skill points, at the best leash it makes things WORSE
(−0.48), because the residual bias is date-to-date noise.

**Why:** outs is dominated by MANAGER HOOK BEHAVIOUR — a human decision a
plate-appearance simulator has no information about.

**Action: withhold or serve `unmeasured`. Do not ship a calibration profile.**

### 2b. Hitter props — this is where the work goes

The largest measured error in the engine `[measured 08-14]`:

    pa_mean  +18.4%   ab_mean  +17.2%
    per-PA rates STILL +12.2% after normalising
    opportunity explains 55% of the count bias

Every counting prop inherits it. A ~0.01 Brier gap is exactly the size of thing
an 18% opportunity error can produce.

---

## 3. The programme, ordered by measured leverage

**P1 — Fix the opportunity model (`pa_mean`/`ab_mean`).**
55% of count bias, in the market that matters, with an existing harness
(`backtest_mlb_props.py`). Then RE-MEASURE the residual per-PA rate bias.
**Exit:** `pa_mean` bias < 5%, and the §0 table re-run.

**P2 — Give managers individual identities.**
`data/manager/manager_tendencies.json` **does not exist** and its loader silently
returns `{}` `[from-code]`, so **all 30 teams share one hardcoded hook profile**.
Fit per-manager hook distributions from `feed_live` pbp (618+105 files
`[measured]`). This is the direct attack on `sd(forecast) = 1.19`.
**Exit:** `sd(forecast)` on outs rises materially; re-run §2a's correlation.
**Note:** this may rescue outs. It is the only thing that might.

**P3 — Deploy `mlb_prop_calibration` (`aac18260`).**
Committed and **NOT DEPLOYED** `[measured 08-14]`. The only measured MLB skill
numbers in existence are not being served — every MLB prop row reads
`unmeasured` on the live board. Cheap, and it makes the board honest.

**P4 — Raise MLB live sims 120 → 300.**
At 120, SE is ±4.56pp and `PRICEABLE_SIGMA=2.0` demands a **~9.1pp edge** before
publishing. At 300 that threshold falls to ~5.7pp. **Measured memory cost: ~0**
if the caller accumulates (0.07 MB flat across 25/50/100 sims); worst case
retain is ~11.4 MB per 1000 sims per game. **300 is the measured knee** —
1000 buys +0.08pp over 300 `[measured, Phase 9]`.
**Confirm the call-site regime (accumulate vs retain) before requesting.**

**P5 — Re-run the market comparison after each of P1–P4.**
`scripts/grade_mlb_hitter_props_vs_market.py` is the scoreboard. The programme
succeeds when a clean family's gap crosses zero, and not before.

---

## 4. Explicitly NOT in scope

- **Chasing game lines.** Sharp-priced, model already loses, no path.
- **State-conditional learning on outs** (`#451`). Conditioning a forecast whose
  centre carries r = 0.05 adds resolution to noise. Revisit only after P2.
- **Extending live sims to more sports** (plan Phase 3). No existing engine has
  been shown to beat a market anywhere; scaling that is premature.
- **Any promotion on statistical improvement alone.** The betting grade this
  session was CONFOUNDED (ALWAYS OVER returned 58.78%/+8.16% with no model), and
  `starter_tto_quality_scaling` was once promoted on a clean statistical win and
  reverted the same session for costing real accuracy.

---

## 5. Instruments this plan depends on (all built this session)

| script | answers |
|---|---|
| `skill_census_crps.py` | does a forecast beat climatology, with CI and leak detection |
| `grade_mlb_hitter_props_vs_market.py` | **does it beat the price** |
| `diagnose_mlb_outs_deficit.py` | is a deficit bias or an uninformative centre |
| `sim_count_requirement.py` | how many sims a market needs |
| `scope_sim_memory.py` | what raising sims costs in MB |

---

## 6. Open, and honest

- `model_raw` == `model_cal` in every family — production's calibration layer is
  either identity on these rows or is not being read. **Unexplained.**
- `hits_runs_rbis` is excluded from §0: the extractor matches probability fields
  by threshold without checking family, so it can read `p_h_2plus` on an hrr
  bucket. **Fix before quoting that family.**
- 12 dates, June 2026. Direction is consistent across three independent
  families; MAGNITUDE needs a paired test.
- Whether MLB's per-PA rate model (the residual +12.2%) is fixable at all is
  **unknown** — P1 answers it.
