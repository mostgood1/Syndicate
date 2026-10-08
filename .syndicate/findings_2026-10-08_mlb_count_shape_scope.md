# Scope: count-shape fix for the MLB pitch model

User, 2026-10-08: "yes, set HR to 1.5 and scope the count-shape fix". Scoping only; nothing is built yet.

## The defect (per-count diagnosis, 2026-10-08)

The shipped config was replayed on 311 June-fit games (4 sims/game) and compared with the same games' real pitch-by-pitch. Pitches/PA: **model 3.461 vs real 3.866 (-10.5%)**. Starters throw ~10 pitches/start too few. That gap was hidden before the combined calibration by +1.9 BF/start, a pair of opposing errors.

The model's outcome mix barely changes with the count; real hitters change sharply:

| count | in play (model / real) | called strike | swinging strike | ball |
|---|---|---|---|---|
| 0-0 | .131 / .116 | .300 / .290 | **.050 / .084** | .415 / .380 |
| 1-0 | **.250 / .165** | **.133 / .218** | .111 / .107 | .314 / .342 |
| 2-0 | **.234 / .162** | **.132 / .285** | .095 / .089 | .332 / .305 |
| 3-0 | **.283 / .021** | **.122 / .584** | .089 / .014 | .345 / .348 |
| 0-2 | .189 / .180 | **.140 / .038** | .141 / .142 | **.303 / .447** |
| 1-2 | .191 / .206 | **.129 / .037** | .139 / .151 | .311 / .381 |
| 2-2 | **.163 / .236** | **.157 / .053** | .110 / .152 | .318 / .294 |
| 3-2 | **.161 / .287** | .128 / .065 | .104 / .136 | **.359 / .232** |

- **Ahead in the count, model hitters swing and put the ball in play far too often**, so PAs end early.
- **With two strikes they take called third strikes 3-4x too often** and see too few balls.
- This is why single levers failed. Extra two-strike fouls, the early-count foul boost and the hook each moved pitches/PA by under 1 pitch per start, or bought it with outs (rounds 1-2, lanes.md).

It also blocks the late-season workload fix: the recency stamina mechanism (built, default off) removed the BF excess but worsened outs, because PAs are too short in pitches.

## Design

1. **Engine: a per-count outcome table.**
   - `PitchModelConfig.count_outcome_mult: {"b-s": {ball, called, swing, foul, inplay: mult}}`, applied in `pitch_model` to the six outcome weights just BEFORE the existing normalisation (`rest = 1 - p_hbp; s = p_ball + ...`).
   - The default is an empty dict, which is byte-identical; to be proven on seeded games like every engine change this week.
   - Player rates still modulate within each count, so the table reshapes; it does not replace.
2. **Fit the table by iterative proportional fitting.**
   - Real per-count outcome shares come from cached play-by-play on a FIT set.
   - Model shares come from replays (pbp="pitch").
   - Update `mult *= real_share / model_share` per cell; iterate to convergence (~3-5 rounds), with mults clamped to [0.2, 5].
   - Measured, not hand-tuned; about 60 cells. The 3-0 cells are thin (~1% of pitches), so they get extra shrinkage.
3. **Re-fit what the table absorbs.** PA-level K, BB and in-play rates will move once counts are reshaped. The current levers were fitted around the missing shape, so they must be re-fitted (the mechanism-vs-estimator rule):
   - `k_logit_bias`, `bb_ball_bias_mult`, `base_in_play`, `early_count_foul_boost`, `two_strike_extra_foul_prob`;
   - `starter_hook_add_pitches` (pitches/PA rises, so the pitch hook must give back);
   - the 13-moment objective + pitches/start; coordinate descent on FIT.
4. **Then re-try the workload fix** (the recency stamina weight) on top.

## Data and validation

- **FIT:** June-fit rosters (06-15..07-12, 311 games, real pbp cached) + window first half (07-16..08-21).
- **HOLDOUT:** window second half (08-22..09-27, 495 games).
  - **Disclosed:** already read in pooled evaluations, never used to fit count shape. No untouched regular-season data is left.
  - The 2027 season becomes the first clean test.
- **Ship checks** (pre-registered when built):
  - per-count mix error (a chi-square-style distance) halved;
  - pitches/PA gap halved;
  - no moment's |z| grows > 1.0;
  - starter SO/H/BB/ER/outs bias limits;
  - runs gap and prop log-loss no worse;
  - a June guard on K / outs.

## Cost

- Engine change + tests + byte-identical proof: ~half a day of session work.
- IPF rounds: ~4 x (replay ~15 min + real tallies, already cached) = ~1.5 h compute.
- Lever re-fit descent: ~10-14 arms x ~12 min = ~3 h.
- Holdout + props: ~1.5 h.
- Total: ~1 day elapsed, mostly unattended compute on the fleet at nice 19.

## Risks

- The table could over-fit thin cells (3-0, 3-1); mitigated by shrinking cells with few real pitches toward 1.0.
- Re-fitting six coupled levers can move K/BB props; the prop log-loss and starter SO checks guard that.
- It interacts with the HR multiplier: more balls in play move to deeper counts, so HR/BIP may shift. The objective includes HR/PA.
