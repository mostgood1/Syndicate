# NFL live re-sim: the real timeouts left — 2026-11-16 (lane `nfl-live-timeouts`, todo #808)

User "Yes, wire it" (2026-11-16), to "Wire live timeouts left into the NFL live re-sim next?". This follows the
#808 end-of-half clock, on main as `38e237e6d..5ddfdd86e` with every switch OFF.

## What ESPN reports, read before any code

ESPN's NFL `situation` carries `homeTimeouts` and `awayTimeouts`. To check that they are timeouts LEFT in the
current half, the core API's final `situation` for each of the 12 games of 2026-11-15
(`sports.core.api.espn.com/v2/sports/football/leagues/nfl/events/{id}/competitions/{id}/situation`) was compared
with 3 minus the second-half timeouts in that game's play-by-play (`site.api.espn.com/.../summary?event={id}`).

| game | ESPN (home, away) | play-by-play, 3 minus second-half used |
|---|---|---|
| NE @ DET | 3, 3 | 3, 3 |
| BUF @ NYJ | 3, 2 | 3, 2 |
| CAR @ NO | 0, 0 | 0, 0 (CAR's lost challenge was charged as #1) |
| HOU @ CLE | 1, 2 | 1, 2 (the play text says CLV / HST) |
| JAX @ TEN | 0, 2 | 0, 2 (TEN's lost challenge was charged as #1) |
| KC @ ATL | 0, 2 | 0, 2 |
| MIA @ IND | 1, 0 | 1, 0 |
| MIN @ GB | 2, 1 | 2, 1 |
| LAR @ ARI | 3, 2 | 3, 2 (the play text says LA) |
| SEA @ LV | 0, 1 | 0, 1 |
| SF @ DAL | 0, 2 | 0, 2 |
| PIT @ CIN | 3, 3 | 3, 3 |

**12 of 12 match.** A first pass read 8 of 12. All four misses were the checker's own errors, never ESPN's: two
team codes in the play text differ from the header's, and a lost challenge is charged as a timeout without its own
"Timeout" play (the text gives it away: the next timeout called is "#2").

**Not yet read:** that the SITE scoreboard's live `situation` (the block `nfl/live_game_state.py` keeps for the
tick) carries the same two keys. The `nfl-live-possession-map` watcher logs the raw keys at MNF 2026-11-16.

## The wiring

Two lanes share the work, and their code touches disjoint files.

- **The adapter (lane `nfl-live-possession-map`, by request).** `scripts/_nfl_live_resim_tick.normalise_live_row`
  emits `home_timeouts` / `away_timeouts` from `situation.homeTimeouts` / `awayTimeouts`: an int 0..3, else None,
  in-progress rows only. Branch `claude/nfl-live-possession-map` @ `6b4bd4d95`, off main.
- **The consumer (this lane).** Branch commit `5453cc475`, off main until the user's OK:
  - `nfl/live_resim.live_state_from_row` reads the two keys (0..3, else None, never clamped);
  - `resim_live_game` passes them as smartsim2's `initial_timeouts_home` / `_away` only when present, and reports
    `timeouts_fed`;
  - `build_game_lens` publishes them in the lane's `live_state` when present.

## Readings

Q4 1:50, home leads 24-17 with the ball at its own 30. 400 sims each, PYTHONHASHSEED=0, test ratings.

| profile | timeouts (home, away) | home win (raw) | total mean | margin mean |
|---|---|---|---|---|
| the seven #808 switches ON | 3, 0 | 1.000 | 41.23 | 6.77 |
| the seven #808 switches ON | 3, 3 | 0.9975 | 43.40 | 7.98 |
| the seven #808 switches ON | not fed | 0.9975 | 43.40 | 7.98 |
| `end_of_half_clock` OFF | 3, 0 / 3, 3 / not fed | 1.000 | 41.995 | 7.93 (all three identical) |

- **Reachable:** with the clock ON, a defence with no timeouts cannot stop the leader, who kneels it out.
- **Inert today:** with the clock OFF the engine never reads timeouts. Pinned by
  `test_clock_off_is_byte_identical_with_and_without_timeouts` on real sims.
- **Unfed equals 3 each,** which is what the engine assumed before this.

## Tests

- `tests/test_nfl_live_resim_timeouts.py` (new, 10 tests):
  - the parse;
  - the row reaching the engine input (call-site capture);
  - clock OFF byte-identical;
  - clock ON off != on and in the expected direction;
  - the lane publish.
- On this branch: 116 passed across the NFL live re-sim, tick, player-exit, lens and end-of-half files.
- **Both branches merged** in a throwaway worktree (since removed): 109 passed across the six NFL live test files.
  An end-to-end probe from a raw `nfl_game_state_index`-shaped row (`homeTimeouts` 1, `awayTimeouts` 0, home's ball
  at its 30) reached the engine as `initial_timeouts` (1, 0), with possession home and field position 30.

## Owed

1. **The MNF read** of the site scoreboard's live `situation` keys (the possession-map watcher).
2. **Main.** Push `5453cc475` with the user's OK. It is inert alone: no row carries the keys until the adapter
   lands.
3. **The NFL profile load** (the seven switches, hfb 0.03, TD 0.825) and the #752 / #805 re-grade: the user's call.
   Live timeouts only matter after it.
4. **NCAAF is not wired.** Its profile stays OFF; `ncaaf/live_resim.py` maps `situation` separately.
