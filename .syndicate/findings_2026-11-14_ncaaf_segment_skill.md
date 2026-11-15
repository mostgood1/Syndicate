# NCAAF quarter/half model probabilities — graded against the market and the box

`[2026-11-14, lane ncaaf-segment-skill, session 386d4115; todo #805; user "Yes, start it"]`

**ID note.** This lane reserved `#804` first (`2f6469464`, 22:59:16Z). Session 35bdf3a7
then wrote its NFL name-key item into `todo.md` as `#804` at 23:00:39Z (`2df699f9c`),
without a claim. This item therefore moved to `#805` (`8a569d952`), so that `#804` keeps
one meaning. Three places still say `#804` because they were already fixed before the move:
- the registered grader's docstring, since editing it would change the registered blob
  `8e9fbfdf5076`;
- the registration commit's subject (`eda9dbd3a`);
- the bootstrap seed, 804, which is part of the registered method.

## The defect

`ncaaf/segment_projections.segment_projection` stamped every h1/h2/q1-q4 view with the
FULL-GAME module's loss: `{"state": "measured_loss", "note": "...No per-segment skill
measurement exists yet..."}`. It carried no `established_loss_rel`, so:

- `projection_skill.normalize_existing_note` served it as `status: measured`;
- `measured_market_skill.skill_reliability` returned 1.0;
- the registry was never consulted.

The module's docstring said the loss "acts through ranking rather than through a blank
column". It did not.

**Served board 2026-11-14 22:48Z (4:48 PM CST), NCAAF, rows by the weight they earn:**

| rows | phase | note | weight |
|---|---|---|---|
| 1,617 quarter/half | pregame | `measured_loss`, no `established_loss_rel` | **1.0** |
| 288 full-game spreads, 39 h2h | pregame | margins, `established_loss_rel` 0.03718 | 0.814 |
| 284 full-game totals | pregame | totals, `established_loss_rel` 0.09722 | 0.514 |

A quarter total from a model whose full-game totals are measured 2.48x over-dispersed
outranked that model's own full-game total.

This is the NCAAF twin of NFL's `#752`, whose findings flagged it
(`findings_2026-11-13_nfl_segment_skill.md`, "Owed / follow-ups").

## Method — pre-registered in `lanes.md` (`eda9dbd3a`) before any outcome was read

Grader `scripts/ncaaf_segment_skill.py` (blob `8e9fbfdf5076`). It imports
`scripts/nfl_segment_skill.py` (blob `020cb082b5a9`, on main) for the de-vig, consensus
line, framing, outcome rule and statistics, unchanged. Seed 804, 2,000 reps.

- **Population:** every NCAAF game with all three of:
  - a pregame quote (`captured_at < commence_time`) on an h1/h2/q1-q4
    totals/spreads/h2h market, in the fleet's `ncaaf_source/tracking/book_quotes` files
    2026-10-01..11-12;
  - a sim block through **production's own bridge**: `oddsapi_lines.resolve_team` ->
    `game_projections._norm` -> the pair in a 2026 `smartsim2_projections_<s>_wk<w>.csv`
    -> its ESPN `game_id` -> that week's `smartsim2_segment_distributions` block. A pair
    in several weeks takes the week whose ESPN event is dated within a day of kickoff;
  - a final ESPN college-football linescore for that game id.
- **As-of, the one rule NFL did not need:** the sidecar's own `generated_at` must be
  strictly before kickoff.
  - Each week's file is rewritten through the week. Its last write lands on the
    Saturday: wk6-10 at 16:48-20:15Z, wk5 at 10-04 01:42Z.
  - SP+ refreshes in season.
  - So a file written after kickoff is neither what the board served nor clean of the
    game it prices. A file written before kickoff is, by construction, the one on disk
    at kickoff.
- **Market, model, unit, families, test, verdict:** as `#752`. Each book's last
  pregame two-sided pair, de-vigged proportionally; the modal line; production's
  `probability_above`; one observation per game x segment x market; families pooled
  over the six segments; dBrier with a game-clustered bootstrap 95% CI. The verdict is
  loses if CI lower > 0, beats if CI upper < 0, parity otherwise.
- **Registry rule:** each family's pooled figure on its six segment entries.
  `established_loss_rel` = max(0, CI lower) / Brier(market).

**Count-only run before the push** (`--count-only` reads no box):

- Quoted: 362 games, 6,467 segment markets.
- Refused: 3,485 `sidecar_written_after_kickoff`, 86 `no_projection_pair` (FCS
  opponents). 0 lacked an ESPN event or a final.
- **Eligible: 161 games, 2,896 markets.**

The registry team snapshot's sha (`cceced97`) is the same on the fleet's data root and
in the worktree.

## Population graded

- **161 games, 2,774 lines:** weeks 5-10, kickoffs 10-04 02:30Z .. 11-08 03:30Z.
- 122 pushes were dropped.
- Lines by sim week: wk10 862, wk9 620, wk8 551, wk7 395, wk6 277, wk5 69.
- The as-of rule leaves the Saturday slates from mid-afternoon (Central) on. The
  weeknight games and the early-Saturday games were priced off a write that has since
  been overwritten, so they cannot be graded.
- The median number of books at the consensus line is 2.

## Result vs the market

| family | lines | games | Brier model | Brier market | dBrier [95% CI] | verdict | `established_loss_rel` | rank weight |
|---|---|---|---|---|---|---|---|---|
| totals | 964 | 161 | 0.2725 | 0.2495 | **+0.0230 [+0.0115, +0.0349]** | **loses** | 0.04617 | **0.769** |
| spreads | 966 | 161 | 0.2560 | 0.2480 | **+0.0080 [+0.0010, +0.0153]** | **loses** | 0.00387 | 0.981 |
| h2h | 844 | 161 | 0.2299 | 0.2242 | +0.0057 [−0.0012, +0.0131] | parity | 0 | 1.0 |
| all | 2,774 | 161 | | | +0.0125 [+0.0069, +0.0186] | loses | | |

**Nothing beyond the line.** A logistic fit of the outcome on logit(market) +
logit(model) gives the model this weight beside the market:

| family | model weight | model calibration slope | market calibration slope |
|---|---|---|---|
| totals | −0.08 | **−0.03** | 0.94 |
| spreads | +0.01 | 0.18 | 1.36 |
| h2h | +0.12 | 0.72 | 1.09 |

The model's quarter/half totals carry no information about the outcome.

- Its probabilities sit a mean 11.1 points from the market's.
- Those gaps are what the board shows as edges.

**Segment alone** (descriptive; the verdict is the family's): every segment loses or
sits at parity, with no segment's point estimate in the model's favour.

- Totals clear zero on h1 (+0.045 [+0.019, +0.070]), q1 (+0.022 [+0.003, +0.040])
  and q2 (+0.029 [+0.008, +0.049]).
- Spreads clear zero only on q2 (+0.013 [+0.0004, +0.026]).
- The figures are in `measured_market_skill._NCAAF_SEGMENT_ALONE`.

**Hypothesis** ("loses in every family, as at game level"):
- **Supported for totals and spreads.**
- **Falsified for h2h.** It is parity: the CI spans 0, with the point estimate
  against the model.

## Engine read (descriptive; 161 games, sidecar written before kickoff)

| segment | sim mean total | actual | bias [95% CI] | outer-20% PIT share (0.20 = calibrated) |
|---|---|---|---|---|
| full | 50.7 | 52.0 | −1.3 [−4.3, +1.7] | 0.37 |
| h1 | 24.5 | 25.8 | −1.3 [−3.2, +0.6] | 0.37 |
| h2 | 26.2 | 26.2 | −0.0 [−1.9, +1.9] | 0.29 |
| q1 | 10.9 | 10.2 | +0.7 [−0.4, +1.9] | 0.27 |
| **q2** | **13.6** | **15.7** | **−2.0 [−3.3, −0.8]** | 0.27 |
| q3 | 11.9 | 11.5 | +0.5 [−0.7, +1.6] | 0.26 |
| q4 | 14.1 | 14.1 | −0.1 [−1.3, +1.3] | 0.27 |

- **Quarter shares (sim vs actual):** q1 0.215 / 0.196, **q2 0.269 / 0.301**, q3
  0.236 / 0.221, q4 0.278 / 0.272.
- **This is NFL's shape** (q2 0.279 vs 0.313 there): the sim under-scores Q2 and
  over-scores Q3. The likely mechanism is the one lane `football-scenario-calibration`
  holds: `halftime_kickoff` is OFF, and there is no end-of-half surge. That lane owns
  the engine.
- **The distributions are far too narrow or off-centre.** 37% of full-game and H1
  totals land in the sim's outer 20%.

## What changes (code)

- **`measured_market_skill.py`:** 18 entries, `("ncaaf", totals|spreads|h2h, h1..q4,
  pregame)`. Each carries its family's pooled measurement, as pre-registered, with
  `segment_alone` descriptive only. Live rows get no pregame note.
- **`ncaaf/segment_projections.py`:**
  - `segment_projection` no longer stamps `model_skill`, and `_skill_note` is deleted.
  - `attach_projection_skill`, which runs after the join, reads the registry.
  - NFL's producer, which reuses `segment_projection`, already drops the note: no
    change there.
- **Rank effect:** totals segment rows ×0.769, spreads ×0.981, h2h unchanged.
  - Nothing is withheld: the user's rule is that every line is its own decision
    (2026-10-05).
  - Only rank (`score`) moves, never `value_pct` or stake size (`_apply_skill_reliability`).
- **Tests:**
  - `tests/test_ncaaf_segment_skill.py`: the bridge, the as-of refusal, the named
    refusals, count-only reading no outcome, the loss_rel rule, a planted edge found, a
    worse model found losing, book-vs-book parity, 18 pregame notes and no live one, the
    rank weights, and the served path, where the old note scored 1.0 against 0.769 /
    0.981 / 1.0 with pricing unchanged.
  - `tests/test_ncaaf_segment_projections.py`: the producer stamps no note.

## Replay on the served board (worktree code, read-only)

- **Input:** the served NCAAF 11-14 grid (built 23:09:21Z), 1,626 segment rows with
  projections. Projections were stripped and re-attached by the new producer from the
  fleet's wk11 sidecar, then `attach_projection_skill` ran.
- **Notes:** 1,626 of 1,626 come from the registry: totals 629 loses, spreads 667
  loses, h2h 330 parity.
- **Probabilities:** 1,626 of 1,626 identical to served. That compares against
  `model_prob_over`, or `sim_model_prob_over` where the board blanked a started game's
  pregame number (`pregame_on_live`).
- **Rank weight:** served 1.0 on all 1,626. New: totals 0.769, spreads 0.981, h2h 1.0.

## Owed / follow-ups

- **Push and load are the user's decision.** The load is a fleet ff plus a claimed,
  drained refresh-worker TERM (the board build and Layer 2 scoring), and a reload-web.
- **Then a served reading:** NCAAF segment rows carry `basis measured_market_skill` on
  the first grid after the restart.
- **Re-grade** as Saturdays accumulate. Nothing here re-grades on its own.
- **Grade the weeknight and early-Saturday games.** That needs each sidecar write kept,
  not overwritten. The board serves those games off writes this grade cannot see.
  - A dated copy per write (`..._wk<w>.<generated_at>.json`) would make every NCAAF game
    gradable.
  - Not done here. **Built in todo #807**: `sim_history/ncaaf/` + `--archive`.

## Reproduce

Data was copied read-only from the fleet to `C:\tmp\ncaaf_seg\` (not in git):
- `sidecars\`: wk1, wk4-11 CSVs and sidecars;
- `quotes\`: the 31 date files 10-01..11-12;
- `linescores.json`: the ESPN cache, 41 dates, 365 FBS games, all final;
- `result.json` and `result.obs.json`.

```
py -3 scripts/ncaaf_segment_skill.py --sidecars C:\tmp\ncaaf_seg\sidecars --quotes C:\tmp\ncaaf_seg\quotes --linescores C:\tmp\ncaaf_seg\linescores.json --out C:\tmp\ncaaf_seg\result.json
```

Replay: `C:\tmp\ncaaf_seg\replay.py`.
