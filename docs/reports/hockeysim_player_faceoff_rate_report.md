# hockeysim faceoff mechanism — the first player-level signal, and a reachability bug caught before shipping

Every faceoff signal this session built so far — EV, OZ, DZ, NZ, strength-state role, the joint
role-zone refinement — operates on TEAM-level rates. None of them know WHICH SPECIFIC PLAYERS are
actually dressed tonight. This closes that gap: a genuinely per-player faceoff win rate, folded
into a lineup-aware team-level percentage.

## A real trap in the data itself, caught before building on it

The `boxscore` cache already carries a per-skater `faceoffWinningPctg` field, the same cache every
other per-player signal this session built (`shot_weight`/`goal_weight`/`block_weight`) reads. A
direct spot-check of 480 real center-games found **22% show an EXACT `0.0` or `1.0`** — almost
always a game where that player took only 1-3 draws. Averaging those per-game rates EQUALLY with a
25-draw game (a naive `mean(faceoffWinningPctg per game)`, the same shape of computation
`shot_weight` uses successfully for shots/goals/blocks) puts several real, active centers at a
literal **0.0000 across 68-82 games** — not plausible for an NHL center, and a real instance of "a
rate, not a count" biting exactly the way this session's own standing rules warn about.

Fixed by going to `playbyplay`'s `details.winningPlayerId`/`losingPlayerId` on every faceoff event
instead — TRUE win/total COUNTS summed across every game a player appears in, never an average of
per-game ratios. Player names/positions come from the SAME payload's `rosterSpots` array, no
boxscore cross-reference needed.

## The real signal — hockey-sensible, externally validated

1,312 games, 238 players clear a 100-real-draw floor. Top rates: Claude Giroux (0.6308, 799
draws), Gabriel Landeskog (0.6231), Jonathan Toews (0.6209), J.T. Miller (0.6146) — all real,
well-known, plausible elite faceoff performers, the same external-validation pattern every
per-player/per-team signal this session has shown. League average among qualified players: 0.4867.
Bottom rates: ~0.30-0.34, a real, sensible spread (not the artificial 0.0-0.06 the boxscore-average
approach produced).

**No explicit "centers only" filter is needed.** This package's own roster/lineup CSVs only carry
the broad F/D/G position class, not the finer C/L/R split — a real, checked data-availability gap.
The 100-draw floor does that filtering implicitly: a winger who takes an occasional emergency draw
will not clear 100 real draws across a season, so `faceoff_weight` ends up populated almost
exclusively for players who actually take draws regularly (real hockey: centers), without needing
position data this package doesn't have.

## A reachability bug caught before shipping — the same discipline every piece this session has used

The first design overrode `TeamRates.faceoff_win_pct` directly with the lineup-aware value.
**This was completely dead weight in production, caught before shipping by asking "is this
actually reachable" rather than "is it populated."** `faceoff_win_pct` is `_resolve_faceoff_pct`'s
BOTTOM fallback tier — behind the per-team OZ/EV indices (§2m/§2n) and, for strength-state
segments, the role-specific index (§2y). ALL of those are 100% populated in real production data
(`nhl_sim_input_checklist.py`), so the fallback tier is never actually reached — a `faceoff_win_pct`
override would never fire for any team with the season-level indices this session already shipped.

Fixed by composing it as an ADDITIONAL multiplicative layer instead — the same "always applies
regardless of which tier resolved the base percentage" pattern the DZ/NZ layers already use, not a
new tier competing for priority. `special_teams["faceoff_lineup_pct"]` is a real 0-1 percentage
(not an index), applied via `_faceoff_multipliers` (the simple diff-based mechanism, not a
discrete-event curve — this is a persistent per-game roster-quality adjustment, not a discrete
in-the-moment event with its own measured decay shape).

**Gated `ev_only` only, matching DZ/NZ exactly** — does not yet extend to strength-state (PP/PK)
segments, a real, stated, deliberately narrow limitation rather than something rushed.

## Verified

- **31 new unit tests**: 12 on `parse_playbyplay_player_faceoffs`/`parse_playbyplay_roster_names`/
  `compute_player_faceoff_aggregates` (including two tests that directly discriminate TRUE win/total
  counts from a naive average-of-per-game-rates, the exact bug the boxscore approach hit), 8 on
  `compute_lineup_faceoff_pct` and `load_player_rates_map`'s new column, 6 on `build_game_features`'s
  layer attachment (including the rollback flag and the "omitted, not defaulted" no-data case), 3
  engine reachability/direction/bilateral-gate tests.
- `nhl_sim_input_checklist.py`: `faceoff_lineup_pct` shows up automatically (AST-derived from
  `st_home.get(...)`, not a hardcoded list) at **100.0% populated against the real local mirror** —
  confirms genuine end-to-end reachability, not just a synthetic-fixture pass.
- 634 hockeysim/nhl tests pass overall (up from 605).
- **Round-robin**: **-0.112%** (992-pairing round-robin, real per-team `faceoff_lineup_pct` from
  the local mirror's actual dressed rosters, 32 teams, real spread 0.43-0.55, vs the layer
  disabled) -- noise-level, in line with every other faceoff layer's near-zero aggregate shift
  this session measured. A separate no-data control (no team carrying `faceoff_lineup_pct` at
  all) confirmed an EXACT 0.000% delta, proving the bilateral gate correctly no-ops rather than
  silently defaulting.

## What this does NOT do

- No strength-state (PP/PK) extension yet -- roster composition plausibly matters there too, a
  real, stated next step, not attempted this pass.
- No per-team differentiation of WHICH specific line a center plays on within a game (a team's
  4th-line faceoff specialist and its 1st-line center both contribute via the SAME TOI-weighted
  formula) -- a coarser signal than a full line-matching model would give, but a real, measured
  improvement over a static season-long team average blind to tonight's actual roster.
- The `faceoff_win_pct`-override design was tried and explicitly reverted, not merely abandoned
  silently -- kept in this report as the clearest illustration this session has produced of
  "presence is not reachability" biting a brand-new signal, not just an inherited one.
