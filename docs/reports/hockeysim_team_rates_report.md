# hockeysim team rates: `shots_per_60`/`blocks_per_60`/`penalties_per_60`/`faceoff_win_pct`

Closes 4 of `docs/ai_context/hockeysim_engine_reference.md` §5's remaining genuinely-absent
`HockeyTeamFeatures` fields — but with an important finding stated up front rather than buried:
**2 of the 4 are populated but confirmed UNREACHABLE — a dead gate, not a wiring fix.**

## What was built

`historical_truth/team_game_rates.py` — parses real per-game team rates from two sources already
bulk-fetched this session (no new fetch needed):

- **`shots_per_60`, `blocks_per_60`** — from the `boxscore` cache. SOG comes straight from the
  league's own recorded `homeTeam.sog`/`awayTeam.sog`. Blocks reuse `boxscore_block_rate.py`'s
  parser (§2g) rather than re-parsing the same payload a second way.
- **`faceoff_win_pct`** — from the `play-by-play` cache (§2i). `faceoff` events' `eventOwnerTeamId`
  is the WINNING team — verified directly against `rosterSpots` team assignment (0 mismatches
  across a 70-faceoff sample game) rather than assumed from documentation.

`scripts/build_nhl_team_rates_artifact.py` joins both sources per game (a game missing either is
skipped, never guessed) and aggregates per team across the season. Run against the full 1,312-game
cache: **1,312/1,312 games joined** (both boxscore and play-by-play cache complete). League
averages: shots/60 = 27.83, blocks/60 = **14.19** (exact match to §2g/§2h's independently-computed
block-rate truth — a strong cross-validation between two separately-built modules), faceoff_win_pct
= 0.5001 (essentially exact — a structural sanity check, since every faceoff has one winner and one
loser league-wide). Real per-team spread: COL (33.7 shots/60) and CAR (32.2) rate highest — the
SAME two teams that independently led xGF/60 in the §2i xG model, a second cross-validation.

**`penalties_per_60` deliberately has no new producer.** It's already computed —
`special_teams_builder.py`'s `TeamSpecialTeamsRates.committed_per_game` is the exact same quantity
(penalties committed per team per game), already written to `team_special_teams_*.csv`. The gap was
never a missing producer; `build_team_features` just never read that already-computed value into
the SEPARATE top-level `HockeyTeamFeatures.penalties_per_60` field (only into the nested
`special_teams["committed_per_game"]` dict, a different consumption path). Fixed in `loaders.py`.

## Wiring

`loaders.load_team_rates_map()` (new) + `build_team_features`'s new `rates_map` parameter, threaded
through `build_game_features`/`build_slate_features` the same way `xg_map`/`elo_map`/
`special_teams_map` already are. `shots_per_60`/`blocks_per_60`/`penalties_per_60`/
`faceoff_win_pct` are NOT `Optional` on `HockeyTeamFeatures` (unlike `xgf_per_60`/`elo_rating`) —
they carry hardcoded league-average defaults, so a value is only passed through when genuinely
available; an absent map lets the dataclass's own default apply, preserving the exact fallback
behavior this function had before these producers existed.

## The dead-gate finding

Checking reachability (not just population) before calling this "fixed" — the discipline
`model_engine_standard.md` §4.3 requires and this session has applied to every input so far —
surfaced a real, structural problem: `player_props.py`'s `_team_rates()` reads all 4 fields off
`HockeyTeamFeatures` into `TeamRates` (satisfying `nhl_sim_input_checklist.py`'s population check),
but `engine.py` only ever reads `TeamRates.shots_per_60`, `.goals_per_60`, and `.faceoff_win_pct`.
**`TeamRates.blocks_per_60` and `.penalties_per_60` are never read anywhere in `engine.py`.**

Verified, not assumed: `tests/test_hockeysim_props.py`'s `TeamRatesReachabilityTest` proves this
both ways —

- `test_shots_per_60_actually_changes_sog_projection` / `test_faceoff_win_pct_actually_changes_sog_projection`:
  an extreme swing on either field produces a clear, directional difference in projected SOG.
- `test_blocks_per_60_is_a_dead_gate_not_reachable` / `test_penalties_per_60_is_a_dead_gate_not_reachable`:
  an extreme swing (3.0 → 60.0 blocks/60; 1.0 → 12.0 penalties/60), same fixed seed, produces a
  **byte-identical** projection set. Not "close" — identical, because nothing in the simulation
  path ever reads the value.

This is structurally the same class of bug as basketball's `#467` (a real usage-share multiplier
that was CONSUMED, POPULATED, and never actually applied) — except here the "dead" status was true
from the start, not introduced by a later refactor.

## Why this wasn't force-fixed by wiring a new consumption mechanism

**`blocks_per_60`**: real block generation is already fully modeled by `special_teams_cal`'s
`block_rate_ev`/`block_rate_pk`/`block_rate_pp_def` (§2g/§2h) — a per-shot-event probability,
truth-calibrated, with its own per-team layer. That mechanism is strictly more granular than a flat
`blocks_per_60` rate. Bolting a second, independent block-volume signal onto `TeamRates` risks
exactly the double-counting `model_engine_standard.md` §4.4 warns against ("mechanism vs
estimator") — the same trap this session already navigated carefully for `block_rate_index`.

**`penalties_per_60`**: no PIM/penalty-minutes market or mechanism exists anywhere in
`player_props.py`'s market set (`SOG`/`GOALS`/`ASSISTS`/`POINTS`/`BLOCKS`/`SAVES`) or in
`engine.py`'s simulation. There is currently nothing for this value to drive even in principle.

Given both, wiring a NEW consumption path for either field would be a real design decision (add a
second block-volume signal risking double-counting, or invent a penalty-minutes market) — not a
population fix, and not something to make unilaterally inside this pass. **Flagged explicitly, not
silently left mischaracterized as "fixed."** The population/wiring itself is complete and correct;
whether to (a) build a genuine consumption mechanism for either field, or (b) remove them as
confirmed dead code (`TeamRates`, `HockeyTeamFeatures`, and their ~8 reference sites across the
package) is an open decision for a follow-up pass.

## Checklist impact

`scripts/nhl_sim_input_checklist.py`: alarm count drops from 7 to **3** — the checklist's own
population check cannot see the dead-gate distinction (it only traces `HockeyTeamFeatures` field →
populated boolean, one hop, the same scope every field in this checklist is measured at). The
remaining 3 alarms (`shot_weight`/`goal_weight`/`block_weight`, player-level usage weights) are a
distinct, still-open gap.

## Reachability tests, full list

- `tests/test_hockeysim_team_game_rates.py` — 13 tests, pure parsing/aggregation.
- `tests/test_hockeysim_loaders.py` — 6 new tests: reader, missing-file fallback, `build_team_features`
  wiring (present and absent), the `penalties_per_60`/`committed_per_game` reuse, and one full
  `build_game_features` end-to-end test.
- `tests/test_hockeysim_props.py` — 4 new tests: 2 proving reachability, 2 proving the dead gate.
