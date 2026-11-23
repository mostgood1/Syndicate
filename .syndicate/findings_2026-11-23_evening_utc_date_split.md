# Evening-UTC soccer date split — findings 2026-11-23

Lane `evening-utc-date-split`. Session 20548d56-8b05-4d8b-9a01-fcf1072e0ba6, taking over from the fleet-watcher
(86352bc9), which opened it on the rail monitor's 11-22 reading.

## Symptom (rail monitor, 2026-11-22)

Real Salt Lake @ Vancouver (MLS, 7:30 PM CT = 01:30Z on 11-23, final 2-0):

- It was filed under 2026-11-23 in the book grid, while its live state and the 2-minute autorun stayed on 11-22.
- All 9 of its 11-23 LIVE_GAMELINE_BUILDs read index=0 considered=0.
- Its overlay gaps were 785, 809 and 667 s, and it placed 0 orders.

## Diagnosis: the date is set by the QUOTE WRITER, not the grid

- `scripts/fetch_soccer_oddsapi_odds_local.py:451` and `scripts/fetch_soccer_oddsapi_props_local.py:505` file soccer
  quotes into `book_quotes` by `commence_time[:10]`, which is the UTC day.
- `_build_book_grid_artifact` builds one grid per date from ONE shard (`book_grid_artifact.py:546`), so the shard key
  decides the grid date.
- NCAAF and NFL already shard by `odds_book_quotes.kickoff_shard_date`, the Central day. NCAAF was fixed for exactly
  this on 09-21, and `clv_join._candidate_shard_dates` reads both. Soccer was never converted.
- Kalshi soccer rows already land on the Central day.

Fleet logs (`~/syndicate-prod/logs/{refresh,live-odds}-worker.log*`):

| window (Z) | build date | index | considered | what it was |
|---|---|---|---|---|
| 11-22 18:00-01:34 | 11-22 | 3-6, then 1 | 28-90 (fell to 9-18 late) | daytime and early-evening matches, about one build a minute |
| 11-23 01:35-01:38 | 11-22 | 0 | 0 | Charlotte @ Chicago at 90'+, `skipped_key_player_out=1`, not RSL |
| 11-23 01:42-03:25 | 11-22 | **1** (RSL, `indexed=1`) | **2** | 10 builds; the two rows are Kalshi |
| same | 11-23 | 0 | 0 | `aggregate=stale_date`: there was no 11-23 live state yet |

`book_grid_2026-11-23` held 473 RSL rows (commence `2026-11-23T01:30:00Z`); `book_grid_2026-11-22` held 0 after the
06:01Z rebuild. The 11-22 live state (`soccer_source/mls/api/live_state/live_state_2026-11-22.json`) carries RSL in
`match_box`/`projection_history` from 01:41Z to 03:34Z.

**Hypothesis: SURVIVES, refined.** The live index for the Central day HAD the match. The rows were in the other date's
grid because the writer keyed them by UTC. Non-crossing matches did not show the gap (about one build a minute, with
`considered` in the tens). A literal "replay keyed by the CT day" cannot be run: the live state's `games` is emptied
after the final, so the per-tick projection is gone. The index (`indexed=1`) and the rows (473 in the other grid) are
the two halves of the join, and both were measured.

Only MLS kicks off after 00:00Z among the tracked leagues (`LEAGUE_SPORT_KEYS`: 12 European leagues plus MLS).

## The change (default OFF)

Env key `SYNDICATE_SOCCER_QUOTE_SHARD_CENTRAL`. Absent means today's behaviour; only `1/on/true/yes` turns it on.

- `syndicate/features/shared/soccer_quote_shard.py` (new) provides `soccer_quote_shard_date(row, now=)`:
  - off: the old inline expression, byte for byte;
  - on: `kickoff_shard_date` (Central), or now's Central date for a row with no kickoff.
- The two soccer writers call it.
- `book_grid_artifact.drop_events_moved_to_another_date`, for soccer only and with the key on, also treats a row in its
  OLD UTC-day shard as filed by its own kickoff. A match quoted before the switch then drops out of the UTC-day grid
  once the Central shard has looked at it more recently. Without this, its pre-switch prices would linger there as a
  servable ghost (the 10-20 Iowa @ Minnesota class). Off: the rule is unchanged.
- Tests: `tests/test_soccer_quote_shard_central.py` covers off/on/absent, reachability through BOTH real writers
  (off != on), the ghost drop on/off, and other sports untouched. 26 pass with `tests/test_book_grid_moved_kickoff.py`.
  The soccer writer suites pass. The failures in `test_odds_refresh_tracking.py` and `test_ncaaf_oddsapi_game_lines.py`
  are environmental (the worktree has no `data/`) and touch no changed file.

`odds_book_quotes.py` was NOT edited: the OPEN lane `book-quotes-splice-repair` claims it.

## Kit: `C:\tmp\w_eud\` (WSL `/mnt/c/tmp/w_eud/`)

- `kit_env_eud.sh check|apply|restore <backup>` appends ONE global line `SYNDICATE_SOCCER_QUOTE_SHARD_CENTRAL=on` to
  `~/syndicate-prod/local_production.env`. It backs the file up first, keeps its mode, is idempotent, and prints no
  other values.
  - Global because the writers run as subprocesses of whichever role fetches soccer and inherit its env.
  - Env is built only at `up`, so it needs the window's drained down/up.
- `kit_selftest_eud.sh` runs against a dummy file. Ran 11-23 14:24Z: apply, idempotent re-apply and restore all OK;
  real file unchanged; all three roles ABSENT.
- `kit_after_up_eud.sh [LOAD_UTC]` is read-only. For every 00:00-05:59Z soccer kickoff it prints which grid holds the
  rows (CENTRAL / utc-day / other), the rows touched after the load, and, in play, the rail's h2h rows carrying a live
  model.

Baseline, 11-23 14:24Z (key ABSENT on every role). Every crossing match's OddsAPI rows are in its utc-day grid:

| match | kickoff (Z) | utc-day grid | rows |
|---|---|---|---|
| LAFC @ STL | 11-24 01:00 | 11-24 | 427 |
| HOU @ SJ | 11-25 03:00 | 11-25 | 183 |
| MIA @ CLB | 11-28 01:00 | 11-28 | 148 |
| VAN @ RSL | 11-28 03:00 | 11-28 | 173 |
| STL @ LAFC | 11-29 01:30 | 11-29 | 46 |
| DAL @ POR | 11-29 03:30 | 11-29 | 162 |

The 2-10 rows in other grids are Kalshi rows or forward captures.

## Pre-registered predictions (for the load, whichever window)

- **P-E1 (shard).** Within one soccer fetch cycle after `up`, a crossing match's new rows land in its CENTRAL-day grid.
  - `kit_after_up_eud.sh <LOAD>` reads `post_load_rows > 0` there and `post_load_rows == 0` in its utc-day grid.
  - Kalshi and forward-capture "other" rows do not count.
- **P-E2 (ghost).** Once the UTC-day shard has been quiet for 6 h past the load, the UTC-day grid's
  `MOVED_KICKOFF sport=soccer` line reads `events_moved >= 1`, and that match's rows leave the UTC-day grid.
  - Only for matches whose kickoff is still ahead.
  - For every other sport the moved-kickoff counters are unchanged.
- **P-E3 (live model, the point).** During the next crossing MLS match in play, the soccer LIVE_GAMELINE_BUILD for its
  Central date reads:
  - `indexed >= 1`;
  - `considered >= 100` (RSL had 473 rows; 11-22: `considered=2`);
  - `written > 0`.
  Its rail h2h rows carry `live_model_probability` (N of N, as for daytime matches), and Rail Watch's
  `overlay_offdate_inplay` stays empty for it.
- **P-E4 (no collateral).** Daytime soccer matches are unchanged: same grid date, and the same about-one-a-minute build
  cadence with considered in the tens. No other sport's shard changes.
- **Falsified if** a crossing match in play shows `indexed=1` with `considered < 10` on its Central-date build after
  P-E1 holds. That would mean the rows moved but the join still misses, for example on a team-name or event-id
  mismatch, and the cause is not the date.

## Risks and notes

- **Transition night.** A match quoted before the load keeps its old rows in the UTC-day shard. P-E2's drop handles
  future kickoffs. A match already in play at the load would keep stale rows there, but none is in play at 2-7 AM CT.
- **Settlement.** `scripts/emit_settlement_inputs.py` reads `closing_quotes` from the slate-date shard. With the key
  on, a crossing match's closing quotes move to its Central day, which is the slate date the bet carries. This aligns
  it. Watch the first crossing match's settlement row for `closing` presence.
- **Verification depends on the window.** Every crossing kickoff in the grids is between 11-24 and 11-29.
  - A 11-24 window load is verifiable on 11-25 03:00Z (HOU @ SJ), 11-28 and 11-29.
  - A 12-08 load may have no crossing MLS match until the 2027 season.
  - LAFC @ STL (11-24 01:00Z) happens before either window, and will again have no live model.
