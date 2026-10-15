# A documented caveat came due: two soccer prop markets had readings, weren't registered, and 383 rows were ranking 9.3% too high

`[2026-10-15 19:2x–19:4xZ, session 4ab694ed, lane soccer-prop-skill-registry-gap, taking the propagation-gap lead filed on closing unmeasured-edge-risk-cost]`

## The caveat, verbatim, and its expiry date

`measured_market_skill.py:366-369`, dated `[2026-10-05, lane layer2-unmeasured-per-line]`:

> Shots (−22.4% [−40.6, −1.7]) and assists **DO have readings but are NOT
> registered: no board row carries `player_shots` or `player_assists`** (an entry
> no row can reach is the failure the key-shape block below describes).

That reason was **true on 2026-10-05 and expired the day the rows appeared.**
Measured on the served board at 19:20:07Z, row cap defeated (`1,406 ==
total_rows`):

| market | served rows | registered | `status` | factor | verdict |
|---|---|---|---|---|---|
| `player_shots_on_target` | 420 | yes | measured | 1.0 | at the price: no established loss |
| **`player_shots`** | **383** | **NO** | unmeasured | **1.0** | *model never backtested — projection is unvalidated* |
| **`player_assists`** | **130** | **NO** | unmeasured | **1.0** | *model never backtested — projection is unvalidated* |
| `player_first_goal_scorer` | 1 | yes | measured | 1.0 | no established loss |
| `player_last_goal_scorer` | 2 | yes | measured | **0.5** | at the price: LOSES, −66.8% |

**513 of 1,406 soccer rows (36.5%)** sat in the two markets the registry
deliberately omitted, each reading "never backtested" while this module
documented their readings four lines above the omission.

`player_last_goal_scorer` at **0.5** is the control: the mechanism works
wherever an entry exists.

## The consequence was NOT symmetric, which is the whole finding

`established_loss_rel` is derived, not stored — verified in the deployed code
(`measured_market_skill.py:733`): for an ROI entry it is
`round(max(0.0, -roi_ci95[1]), 5)`. With `SKILL_GAIN = 5.0`, `SKILL_FLOOR = 0.5`:

| market | ROI | CI | `established_loss_rel` | factor it should get | factor it had |
|---|---|---|---|---|---|
| **`player_shots`** | −22.4% | [−40.6%, **−1.7%**] | **0.0170** | **0.9150** | 1.0 |
| `player_assists` | −8.4% | [−47.0%, **+34.8%**] | 0.0 | 1.0 | 1.0 |

- **`player_shots` is an ESTABLISHED loss by this table's own rule** — *"for ROI
  that is the CI's UPPER bound below zero"* — and −1.7% is below zero. Its **383
  rows were ranking at 1.0 where the rule gives 0.915**: scores **~9.3% higher**
  than the measurement allows (`1/0.915 − 1`).
- **`player_assists` scores 1.0 either way.** Its CI straddles zero, so
  registering it changes the **label** and not the score. That is the propagation
  gap with no ranking cost, exactly as predicted when it was filed.

The derivation was checked against a live value before being trusted:
`player_last_goal_scorer`'s CI upper of −0.315 gives `max(0.5, 1.0 − 5.0×0.315)`
= **0.5**, which is what the served rows carry.

## Provenance, and how I calibrated my reading of it

`_SOCCER_PROPS_PRICE_SOURCE` names the source explicitly:
`.syndicate/findings_2026-10-02_soccer_lines_props_backtest.md` "Vs the book".
That table, line 148-153:

| market | player-lines / matches | ROI model EV>0 [CI] | bets |
|---|---|---|---|
| shots | 9,569 / 143 | **−22.4% [−40.6, −1.7]** | 199 |
| SOT | 5,182 / 143 | −7.1% [−41.3, +31.1] | 210 |
| anytime | 2,652 / 144 | −29.5% [−53.7, +0.8] | 487 |
| assists | 2,048 / 115 | **−8.4% [−47.0, +34.8]** | 93 |

**I did not trust my reading of that table until it reproduced the two entries
already in the registry.** SOT registered as `sample_games 143, bets 210, roi
−0.071, ci (−0.413, 0.311)` and anytime as `144, 487, −0.295, (−0.537, 0.008)` —
both match their rows exactly. So rows 150 and 153 are read on the same basis as
the two entries that were already trusted, from the same table and the same
source constant.

## What shipped

Both markets registered, following the siblings' shape and citing the same
source. The omission comment is replaced by a dated correction stating what
expired and what the asymmetric consequence was.

Verified through the **deployed** lookup, not the dict:

```
player_shots            status=measured class=loses_to_market loss_rel=0.017 factor=0.9150
player_assists          status=measured class=parity          loss_rel=0.0   factor=1.0000
player_shots_on_target  status=measured class=parity          loss_rel=0.0   factor=1.0000   (unchanged)
player_last_goal_scorer status=measured class=loses_to_market loss_rel=0.315 factor=0.5000   (unchanged)
```

**78 tests** in `tests/test_measured_market_skill.py` (22 → 26 test functions;
the existing parametrized guards — `test_every_real_entry_cites_a_measurement`
and the CI-vs-class agreement check — picked up the new entries automatically),
plus `tests/test_layer2_suggested_opps.py` green: **85 passed**.

**6 mutation cases, all accounted for:** either entry deleted (4 failures each),
shots' CI flipped positive so it stops being an established loss (2), shots' ROI
drifting from the backtest table (1), shots mislabelled PARITY against its own CI
(1) — and the sixth, a changed `source`, proved in memory because the heredoc
carrying its file-level anchor mangled the escapes.

## Two things I got wrong on the way, both caught by the repo's own guards

1. **My reachability test asserted `skill_note(...)["status"] == "measured"`.** It
   fails: `skill_note` deliberately carries no `status` — there is an existing
   test, `test_note_is_compact_and_carries_no_status`, saying so, and `status` is
   added by `normalize_existing_note` when the note lands on a row. The suite
   caught my test contradicting a documented invariant. Corrected to normalise
   first.
2. **My sixth mutant did not do what its label said** — the first version added
   an unrelated `_drift` field and "survived" without ever touching the `source`
   it claimed to change. **A surviving mutant is dead code, a missing test, or a
   mutant that does not do what it claims**; this was the third kind, and only
   reading the mutation distinguishes them.

## Not done, deliberately

**No restart, no deploy.** The fleet picks this up at its next refresh-worker
restart; the restart rule wants a claim plus idle-after-save plus a `deploys.md`
entry, and this is not urgent enough to spend one — the change can only
*down*-weight, which is the conservative direction. **So 383 rows are still
ranking at 1.0 until that restart**, and that is stated rather than implied.

`layer2_board.py` was not touched (held by four lanes). The `skill_pocket` reward
asymmetry from the parent lane is unchanged and still unowned: this fix makes the
penalty side complete, not the reward side.

## Method note

Row counts come from the served board with the cap defeated. The factor
arithmetic is the deployed `skill_reliability` over the deployed
`established_loss_rel`, checked against a live served value (0.5 on last scorer)
before being used for a counterfactual. Every number registered is quoted from a
table whose source constant the module already cites, and my reading of that
table was calibrated on two entries that were already in the registry.
