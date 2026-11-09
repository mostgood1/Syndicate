# Live NHL / NFL prop Actuals on the Layer 2 board — findings `[2026-11-09, lane nhl-nfl-live-prop-actuals, session 386d4115]`

## The defect, measured

Served board (`POST /api/intelligence/query`, `response.top_opportunities`), 2026-11-09 01:31Z, with SNF
TB@CHI and PIT@ANA live:

| sport | live prop rows | with Live proj. | with Actual | with an edge |
|---|---|---|---|---|
| NHL | 29 (PIT@ANA: SOG 9, GOALS 8, ASSISTS 6, SAVES 3, POINTS 3) | 0 | 0 | 0 |
| NFL | 140 (TB@CHI: Receiving Yards 57, Rushing Yards 26, Anytime TD 17, Receptions 16, Passing Yards 9, Rushing Attempts 7, Passing Attempts 4, Interceptions 2, Passing TDs 2) | 0 | 0 | 0 |

Cause: `board_enrichment.attach_live_projections_for_sport` returned `supported: False` for both
sports. `_LIVE_PROP_SPORTS` is mlb / wnba / soccer, plus nba behind its switch. No NHL or NFL producer
published per-player live numbers. `nhl/live_resim.py` publishes the moneyline only, and NFL's re-sim
is team-level.

## What shipped (commit `827b6259d`, NOT yet pushed or loaded at time of writing)

- **Producers, on the workers that already own each live game.** Each LIVE game's box score rides its
  snapshot as `livePlayerStats`:
  - NHL: live-odds-worker's re-sim tick, `live/nhl_live_lens.json`. It reads
    `/v1/gamecenter/{id}/boxscore` every tick and `rosterSpots` once per game per process.
  - NFL: refresh-worker's re-sim tick, `live/nfl_live_resim.json`, via ESPN's summary. This is the
    settlement read (`fetch_player_stat_rows`): every athlete and every field, with real zeros kept.

  Both run after the re-sim loop, each under its own wall clock (15 s for NHL, 20 s for NFL). They do
  not depend on re-sim refusals: a game the re-sim refused (intermission, `no_slate_features`,
  uninformative band) still gets its box.
- **Join, in the board build.** `live_player_actuals.attach_live_player_actuals` is routed for nhl/nfl
  ahead of the priced gate.
  - It uses the settlement graders' own market->field map, box parser and player matcher
    (`bet_status_nhl._prop_market` / `match_player`, `bet_status_nfl.prop_field` /
    `match_box_player`). So the Actual is what paper settlement would read at that moment.
  - It writes `actual_so_far` plus display flags only. It writes no `model_prob_over`, no
    `live_aware` and no `basis` change, so `live_edge_policy` keeps suppressing the edge.
  - Refusals are named, never shown as 0: no box / stale block (>20 min) / segment prop / unmapped
    market / player absent or ambiguous / stat not the player's role.

## Same-instant replay on the live slate (read-only, 01:47Z)

- **NFL TB@CHI, Q1 5:56:** 54 of 74 live prop rows got an Actual. The other 20 were
  `miss_player_absent`. Each was checked against the box: Godwin, Egbuka, Gainwell, Otton, Hurst and
  Tez Johnson are genuinely not in ESPN's box yet. ESPN lists a player only once he records a stat.
  - Not shown as 0, on purpose. "No stat yet", "inactive" and "name the matcher missed" look identical
    from the box. A wrong 0 would sit on a live row all game.
  - By market: Passing Attempts 3/3, Passing Yards 5/5, Passing TDs 2/2, Interceptions 2/2,
    Rushing Yards 16/19, Rushing Attempts 3/4, Receptions 9/14, Receiving Yards 10/18, Anytime TD 4/7.
- **NHL PIT@ANA (2026020282, LIVE):** the 01:31Z rows, replayed against the live box: 25 of 27.
  - Yegor Chinakhov is not in tonight's dressed box (40 players), so he gets no Actual. That is
    correct; the grader would void him at the final.
  - The NHL box lists every dressed player with zeros, so "absent" there means "not dressed".
- By 01:47Z the served board no longer carried PIT@ANA's props at all; its NHL props were the 11-09
  slate (Rangers, Flyers @ Canucks, Islanders), all pregame. Whether live NHL props are present at a
  given minute depends on the board's own row set.

## NHL Live proj. — NOT shipped, and why (measured)

The obvious source for a display-only NHL Live proj. is: actual + the re-sim's rest-of-game per-player
mean, taken from the sims it already runs. That source was measured on the fleet's own 11-08 slate
features (`~/syndicate-prod/data/nhl_source`), with n=200 shared seeds per arm and nice 19. The measure
point is P1 20:00, 0-0, where a resume IS the pregame game:

| market | pregame prop sim vs resume WITHOUT `special_teams_cal` (the live re-sim's config) | vs resume WITH it |
|---|---|---|
| SOG | +5.7% / +6.7% / +7.4% (FLA@BOS, VGK@BUF, TBL@WPG) | 0.0% (per-player MAD 0.0000) |
| GOALS | +4.1% .. +10.5% | 0.0% |
| ASSISTS | +6.4% .. +12.6% | 0.0% |
| POINTS | +5.5% .. +11.4% | 0.0% |
| BLOCKS | -2.0% .. +1.1% | 0.0% |
| SAVES | +5.1% .. +7.1% | 0.0% |

- `nhl/live_resim.resim_live_game` calls `run_hockeysim_game_from_state` with no `special_teams_cal`.
- The pregame prop sim (`hockeysim/player_props.build_prop_projections`) passes the calibrated profile:
  `pk_shot_multiplier 0.3369`, `pk_goal_multiplier 0.4645` and `pp_shot_multiplier 0.9108`, against an
  engine default of 1.0.

So the re-sim's rest-of-game player means run 4-13% hot. Showing them would put a Live proj. above the
pregame Projected at puck drop, before anything has happened. With the cal, the identity is exact.

**Bears on the PRICED live moneyline too (not this lane).** The live re-sim's scoring environment is
the uncalibrated one, so its goal rate runs high by the same mechanism. Whether that moves
`modelHomeWinProb` materially was not measured. Both teams inflate, so the effect on the moneyline is
second-order. The effect on totals is not, and that number is shown for display.

Two ways to an honest NHL Live proj.:
- (a) The re-sim passes `special_teams_cal`. This changes the priced live moneyline, so it needs a user
  decision and the nhl-live-resim owner.
- (b) A separate calibrated rest-of-game prop resume, ~3 s per game at puck drop (falling as the game
  runs). This costs live-odds-worker CPU on a 60 s tick.

## Found beside it, not fixed here

- **NHL live game-line join cannot match any NHL game.** The re-sim snapshot names clubs by
  `/v1/score`'s short name (`'Penguins' @ 'Ducks'`). Board rows carry `'Pittsburgh Penguins' @ 'Anaheim
  Ducks'`, and `live_gameline_join` compares plain lowercase. So even with lanes `live_resim`
  (`7d48129c5`), every NHL row misses.
  - `team_aliases.canonical_team('nhl', 'Penguins')` -> `'pittsburgh penguins'`. This join
    canonicalises both sides itself.
  - Note left for lane `nhl-live-resim-slate-root` in the session notes folder.
- **Freshness.** The Actual reaches the served board at the Layer 2 build cadence. The build in flight
  at 01:5xZ was logging `typical=38.7min`. NBA/MLB get a read-time refresh on web
  (`intelligence._refresh_live_columns_from_artifact`, lane `nba-live-proj-actuals`); NHL/NFL do not
  yet. Each Actual carries `live_actual_as_of`.
