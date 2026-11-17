# NFL game cards dropping off the Games Rail: the quarter/half fetch cadence (MNF 11-16)

Lane `nfl-rail-segment-cadence`, todo `#823`. Promoted from the 2026-11-16 lead of lane
`nfl-gameline-kickoff-shard`. User 2026-11-17: "look into the NFL game cards dropping off the rail".
**Diagnose only.** No code, env or fleet change was made. Everything below was read from the fleet,
read-only, at nice 19, on 11-17 between 8:55 and 9:45 AM CST. Times are CST (UTC-6) unless marked Z.

## Answer

During MNF the Games Rail lost NFL game cards whenever the quarter/half lines were more than 300 s
old. Two settings collide:

1. **The in-play overlay keeps only rows seen within 300 s**
   (`book_grid_artifact.inplay_overlay_max_price_age_seconds`, `:917`; `is_inplay_fresh_row`, `:975`).
   Each build REPLACES the whole overlay file (`_write_inplay_overlay_best_effort`, `:1200` / `:1223`).
2. **NFL in-play quarter/half lines are fetched only every 600 s**
   (`segment_odds_fetch.DEFAULT_LIVE_INTERVAL_SECONDS = {"ncaaf": 600, "nfl": 600}`, `:324`).
   This was a deliberate credit cut: lane `nfl-live-segment-interval`, 2026-10-03, user "yes, do #1
   for NFL". Its docstring already says "in-play quarter/half prices are up to this old". Full-game
   lines are not behind that gate and are fetched on every ~150 s lines run
   (`fetch_nfl_team_odds_local.py:432`).

So for the back ~5-6 minutes of every ~10-minute cycle, the only fresh NFL game rows are full-game
lines. Those almost never clear the shortlist's value floor. The overlay then carries 0-6 game
cards instead of 13-30. The rail shows only overlay cards of kind `game`
(`live_rail_rows.py:46` / `:82`), so it drops to those few full-game cards or to none.

This is not the kickoff-date shard (`#817`): every one of these rows was in the 11-16 shard.

## Evidence

**Segment capture instants.** Every LAC @ BAL quarter/half change was captured at one of 18
instants: 7:19, 7:30, 7:41, 7:52 and 8:02 PM, then every ~10 min to 10:16 PM. The gap between
instants was 610-660 s (p50 616 s): the 600 s gate, rounded up to the next lines run. No
quarter/half quote was captured between instants. So these stale windows are exact, not an
artefact of the shard logging changes only.

**Per-build reconstruction, 136 NFL 11-16 overlay builds, 01:18-04:26Z.** For each build: the rows
whose quote changed in the 300 s before the build's `BOOK_GRID_QUOTE_READ`, split full-game,
quarter/half and prop, against the build's `INPLAY_OVERLAY` line. This is a lower bound on the
in-play set. It is tight for quarter/half rows (above), and it tracks production on game-only builds
(39 rows reconstructed vs `rows_inplay` 46).

- **67 of 136 builds (49%) had no fresh quarter/half row.**
- **100.1 of 191.1 minutes (52%)**, 7:18-10:30 PM: the served overlay held no fresh quarter/half
  row.
- **Game-only builds (<= 65 in-play rows):**
  - 10 with fresh quarter/half rows made 13-30 cards;
  - 10 without made 0-6.
  - So nearly all NFL game cards are quarter/half lines.

**The builds whose game-card state is known all match:**

| build (CST) | fresh quarter/half rows | game cards | how known |
|---|---|---|---|
| 7:41:11 PM | 0 | none | rail trace: 172 cards, all props |
| 7:44:39 PM | 29 | yes | rail polls 7:44-7:45 PM served 26-30 MNF game rows |
| 7:45:50 PM | 29 | yes | rail polls 7:45-7:47 PM served game rows |
| 7:47:27 PM | 0 | none | 12th rail poll served 0 NFL game rows |

The 12-poll window (7:43:54-7:47:43 PM) sat inside the 7:41:31 PM capture's 300 s life plus one
build. That is why 11 of 12 polls looked healthy.

**The lead's original guess was half right.** It said game rows cross the 300 s limit between
"live-first rounds". They cross it between quarter/half CAPTURES. Full-game lines stayed fresh: they
were fetched every 2-3 min.

## A second, smaller instance: props (Layer 2 board, not the rail)

NFL player props are fetched only by `--mode full` runs (`scripts/refresh_nfl_oddsapi.py:277`). On
MNF those ran every ~2-15 min (7:26, 7:29, 7:36, 7:43, 7:45, 7:50 PM, then 8:04, 8:06 PM...).

- About 18 builds between 7:27 and 10:14 PM held <= 65 in-play rows, so few or no props.
- In those builds the board's in-play NFL props blinked out the same way.
- Not measured further. The rail does not show props.

## Instrument note

`odds_refresh.stderr.txt` is capped (~65.6 KB). On long runs it loses the `STEP_MARKER` lines. Run
`20261117_013843` had no `NFL_GAMELINE_QUOTE_SHARD` line in its stderr file, but
`odds_refresh.json`'s `stdout_markers` carried it. Read the JSON.

## Options (the user's decision; none applied)

| | change | cost | risk |
|---|---|---|---|
| A | NFL live quarter/half lines on every lines run (live interval 600 -> 0 / ~150 s) | Undoes the October credit cut. Measured then: 2,767-2,825 credits/h in a Sunday window with the gate, vs ~8.6k/h estimated without (estimate, never measured). Linear in live games: a 1-game primetime night is ~1/10 of a Sunday. | More API credits. Likely a **betting change** if NFL quarter/half lines are bet in play. |
| B | Same as A only when <= 2 NFL games are live (primetime), 600 s otherwise | Small: the primetime nights only. | Code change in `segment_odds_fetch`. Sunday keeps the flicker. |
| C | Overlay age limit per segment: quarter/half rows count as in-play up to ~700 s | No credits. | Shows quarter/half prices up to ~11 min old as in-play. A quarter line that old in a live game has usually moved. If the overlay feeds live bets, it is a betting change and an edge-quality risk. |
| D | Leave it: the 10-min cadence is the agreed price | None. | The rail keeps losing NFL game cards about half the time. Optionally the rail could say "quarter/half lines refresh every 10 min". |

NCAAF carries the same 600 s gate (`DEFAULT_LIVE_INTERVAL_SECONDS["ncaaf"]`), so the same flicker
should hit college Saturdays. That was not measured.

## Scripts (read-only, `C:\tmp\nflrail817\`)

| script | what it does |
|---|---|
| `overlay_lines.sh` | every NFL 11-16 INPLAY_OVERLAY line |
| `nfl_runs.py` | NFL odds-refresh steps per run |
| `fresh_recon.py`, `cycle_rate.py` | the per-build reconstruction and rates; output `cycle_rate_out.txt` |
| `seg_small.py` | every quarter/half capture instant |
| `build_ctx.sh` | log context around a build |
