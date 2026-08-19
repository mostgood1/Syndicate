# hockeysim neutral-zone faceoff calibration — a real check, a null result

Closes the last item the faceoff-zone track left open (`hockeysim_engine_reference.md` §2o: "no
plausible consumption point exists for a neutral-zone-specific signal") — but with a real
measurement behind the conclusion this time, not just an assertion. This also retroactively checks
the three ALREADY-SHIPPED indices (EV/OZ/DZ, §2m/§2n/§2o) against the same standard, since none of
them had been checked this way before either.

## The question

Every prior faceoff-zone index this session built was verified two ways: (1) does it normalize
correctly (mean ≈1.0, the zero-sum self-consistency check), and (2) does layering it into the
engine leave the engine's own SIMULATED league-wide shot average undisturbed. Neither check asks
whether the index reflects something REAL about shot generation in the first place — both are
internal-consistency checks, not calibration against truth.

`scripts/calibrate_nhl_faceoff_nz_index.py` asks that directly: **does a team's SEASON-AGGREGATE
faceoff win rate, at any zone, correlate with their SEASON-AGGREGATE real `shots_per_60`**
(`team_game_rates.py`'s own real per-team data, already built this session)?

## Method

Pearson correlation between each index (NZ, and for context OZ/DZ/EV) and real `shots_per_60`
deviation from the league mean, across all 32 teams (all qualify — every team played 82 games,
well above the 10-game floor).

## Result

| index | correlation with real shots_per_60 deviation |
|---|---|
| `faceoff_nz_index` | −0.0025 |
| `faceoff_oz_index` | +0.0088 |
| `faceoff_dz_index` | −0.0101 |
| `faceoff_ev_index` | −0.0109 |

**Every correlation is under 0.02 in magnitude — indistinguishable from zero.** League mean
`shots_per_60` = 27.83 (real data), 32/32 teams qualified.

## What this means, stated plainly

**No real evidence supports wiring `faceoff_nz_index`.** Unlike OZ (a direct refinement of the
EV-blended consumption point — a win in a team's own attacking zone is definitionally closer to a
shot than an all-zone blend) and DZ (a clear dual causal story — a defensive-zone win both denies
the opponent and can spring a transition chance), neutral-zone faceoff wins have no comparably
direct link to shot generation, and this measurement finds none empirically either.

**This does NOT prove the engine's segment-level mechanism is wrong.** `_faceoff_multipliers`
models a LOCAL, moment-to-moment effect — does winning THIS specific draw shift shot generation in
the following seconds of THIS segment. A real effect at that timescale could exist and still wash
out completely in a season-long aggregate, diluted by everything else that happens across ~58
other minutes per game. This script cannot distinguish "no real effect" from "a real but small,
local effect invisible at this level of aggregation" — measuring the latter would need matching
real shot events to the ~15 seconds after each specific real draw (full event-sequence time-delta
analysis), a substantially larger undertaking than this pass, and out of scope here.

**The more important finding is arguably the retroactive one**: EV, OZ, and DZ — all three already
shipped and wired into production behavior — show the SAME null season-aggregate correlation. None
of them have ever been validated against real aggregate shot data; each was verified only against
its own internal normalization and the engine's own simulated output. That gap is real and applies
equally to all three, not just to the one this report declines to wire.

## Decision

`compute_team_faceoff_nz_index` is built and unit-tested (`tests/test_hockeysim_faceoff_ev_index.py`)
as real, reusable measurement infrastructure — but deliberately **NOT** added to
`scripts/build_nhl_special_teams_artifact.py`'s CSV output, **NOT** added to
`loaders.load_team_special_teams_map`, and **NOT** wired into `engine.py`. Publishing an unconsumed
field would recreate the exact "populated but confirmed dead" anti-pattern this session already
found and fixed once this pass (`blocks_per_60`/`penalties_per_60`, §2l) — a field that looks fixed
to anything checking population alone while doing nothing. The checklist (`nhl_sim_input_checklist.py`)
has nothing new to flag either way, since NZ was never added as a `HockeyTeamFeatures`/CSV field in
the first place.

## What remains genuinely open

- A segment-level (not season-aggregate) validation of the EV/OZ/DZ mechanism — the only kind of
  check that could actually confirm or refute the local, moment-to-moment effect
  `_faceoff_multipliers` claims to model. Would need real shot-event timestamps matched against
  real faceoff-event timestamps within each game, a substantially larger data-engineering project.
- `faceoff_alpha`/`faceoff_diff_clip`/`faceoff_mult_clip_*` remain the vendor's original,
  never-calibrated defaults — this report adds evidence that the SIGNAL feeding them (season-level
  win rate) may itself be too aggregated to matter, which is a different and arguably more
  fundamental question than whether the sensitivity constants are correctly tuned.
