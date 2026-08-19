# hockeysim player usage weights (`shot_weight`/`goal_weight`/`block_weight`)

Closes the last 3 genuinely-absent inputs `docs/ai_context/hockeysim_engine_reference.md` §5
tracked — the checklist now reports a full **PASS**, the first time this session.

## Unlike the team-rates dead gate (§2j), these were ALREADY reachable

`engine.py`'s `_weighted_choice` reads `shot_weight`/`goal_weight`/`block_weight` directly to
decide WHICH on-ice skater gets credited for a shot, goal, or block — and `_build_game_state`
already had a documented fallback when they're absent: a **position-based heuristic scaled by
projected TOI** (forwards get more shot-weight, defensemen more block-weight), not a flat uniform
value. That heuristic is reasonable but cannot differentiate a team's top-line sniper from its
4th-line grinder at the same position and TOI — every player in a given position/TOI bucket was
treated identically. This pass replaces the heuristic with real, individually differentiated data
where available (>= 5 games tracked), while leaving the heuristic in place as the fallback for
everyone else (rookies, injury call-ups, anyone below the games floor).

## The new signal

`historical_truth/player_game_rates.py` parses the `boxscore` cache's
`playerByGameStats.{home,away}Team.{forwards,defense}[]` — already carries `sog`/`goals`/
`blockedShots` per skater per game, no new fetch. `scripts/build_nhl_player_rates_artifact.py`
aggregates each player's SHOTS/GOALS/BLOCKS across the season into a per-game average — exactly
the quantity `engine.py`'s own fallback-heuristic comment specifies ("weights are interpreted as
per-game totals and later divided by proj_toi to produce per-minute propensities").

Run against all 1,312 games: **47,231 skater-game records parsed, 828 players rated** (>= 5 games
floor — below that, a player is omitted entirely rather than trusting a noisy small sample, and
falls back to the position/TOI heuristic).

**Real per-player spread, external sanity check** — top 5 by `shot_weight` (shots/game):

| player | position | games | shot_weight | goal_weight | block_weight |
|---|---|---|---|---|---|
| N. MacKinnon | F | 80 | 4.375 | 0.663 | 0.438 |
| A. Matthews | F | 60 | 3.783 | 0.450 | 1.350 |
| C. Gauthier | F | 76 | 3.750 | 0.540 | 0.263 |
| J. Hughes | F | 61 | 3.738 | 0.443 | 0.525 |
| C. McDavid | F | 82 | 3.732 | 0.585 | 0.366 |

Nathan MacKinnon, Auston Matthews, Jack Hughes, and Connor McDavid — real, well-known elite
scorers — top the list. Not a coincidence: this is the same style of external validation
(matching known team/player reality) every per-team signal this session built has passed.

## Wiring

`loaders.load_player_rates_map()` (new, keyed by integer `player_id` rather than team abbreviation
— the first per-PLAYER, not per-team, reader in this package) + `build_player_features`'s new
`player_rates_map` parameter, threaded through `build_game_features`/`build_slate_features`.
`shot_weight`/`goal_weight`/`block_weight` are `Optional[float]` on `HockeyPlayerFeatures` (unlike
the team-rate fields) — `None` is the CORRECT "no data" value, since `engine.py` already handles
it via the position/TOI heuristic; a value is only passed through when the map genuinely has one.

## Reachability tested at the mechanism level, not just the wiring level

Because these were already consumed (unlike §2j), the interesting proof isn't "does population
reach `TeamRates`" but "does a REAL differentiated value actually change per-player attribution."
Three new tests in `tests/test_hockeysim_engine.py`, each holding TOI/position identical between
two synthetic players and varying ONLY the field under test:

- `test_player_shot_weight_actually_differentiates_shot_share` — `shot_weight=8.0` produces more
  shots credited to that player (80 seeded runs) than `shot_weight=0.2`.
- `test_player_block_weight_actually_differentiates_block_share` — same proof for `block_weight`,
  on a defenseman. Distinct from the per-TEAM `block_rate_index` mechanism (§2g), which governs
  how many total blocks a TEAM records; this governs WHICH skater gets credited for each one.
- `test_player_goal_weight_actually_differentiates_finishing_rate` — `goal_weight` drives a
  per-shot FINISHING multiplier (the `goal_weight`/`shot_weight` ratio), not attribution volume,
  so `shot_weight` is held fixed and only GOALS (not shots) are measured: a high ratio (elite
  finisher) produces more goals than a low ratio (poor finisher), 120 seeded runs.

All three pass — confirming the mechanism was correctly built and wired, not just "populated."

## Checklist impact

`scripts/nhl_sim_input_checklist.py`: **PASS — every field the engine reads is populated above its
floor.** Alarm count: 3 → 0. This closes the input-completeness audit this session's `#463` opened.

## What remains open

- **No goaltender-specific weight** — `SAVES` allocation still uses the existing starter-goalie
  detection, untouched by this pass; goalie shot-facing distribution was already reasonable
  (single starter gets ~all ice time) and wasn't part of the genuinely-absent list.
- **The position/TOI heuristic fallback is unchanged** — still applies to any player below the
  5-game floor (rookies, injury call-ups, players who missed most of the tracked season). This is
  intentional, not a gap: a real per-player rate from < 5 games would be noisier than the
  heuristic it would replace.
- **Not cross-validated against real per-player prop outcomes** (e.g., does a MacKinnon SOG
  projection now track his real SOG distribution better than before) — this pass proves the
  mechanism is reachable and the input data is real and externally plausible; a full prop-market
  backtest is a distinct, larger validation project, matching the same scope boundary the Elo
  backtest (§6) drew for its own mechanism.
