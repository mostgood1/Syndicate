# NHL matchup signals v1 -- saves tested on 2025-26 (none supported, no under tilt); skaters registered forward -- 2026-10-14

Lane `signal-engine-nhl` (session 9e18a0e7). Registered in the lane block at 2026-10-14T01:16:45Z (landed `43f95c32`)
before any saves outcome was read and before any 2026-27 game after that time. Thresholds came from features only.
Code: `syndicate/features/shared/matchup_signals_nhl.py`, `scripts/nhl_saves_lift.py`, `scripts/grade_nhl_forward.py`.

## Data -- what exists and what does not

- **Skater prop prices before 2026-27: none** except 20 dates of the 2026 playoffs (a different population). Buying the
  2025-26 regular season from OddsAPI's historical endpoint was estimated at ~66k credits (plan §6) -- **not bought; a
  user decision.**
- **Saves closes 2025-26:** `backfill/nhl_lines_2025_26/odds_saves`, 449 regular-season games 2025-10-08..2026-02-01, one
  snapshot ~5 min before the scheduled start, 4-5 US books typical. 889 main lines; 810 joined to a goalie who played
  (79 void: the quoted goalie did not play, or an ambiguous name).
- **Outcomes / features:** NHL web API game logs (`player_game_log_<season>.csv`, `raw/player_game_stats.csv`), regular
  season only (game type from `gamePk`).
- **Forward 2026-27:** the fleet logs every NHL prop quote since 2026-09-30 (SOG, points, assists, goals, saves; DraftKings,
  FanDuel, BetRivers, BetOnline, Pinnacle).

## (A) Saves, 2025-26 -- discover < 2025-12-09 <= confirm (405 / 405 lines)

| signal (side) | discover resid (n) | confirm resid [95% CI] (n / games) | confirm hit lift vs base | verdict |
|---|---|---|---|---|
| saves_opp_volume_high (over; opp shots >= 30.2/g) | +3.5% (31) | +10.6% [-5.5, +25.9] (34 / 32) | +6.3 pts | NOT SUPPORTED |
| saves_opp_volume_low (under; <= 23.3/g) | -2.2% (34) | -2.2% [-17.4, +14.4] (40 / 39) | +4.0 | NOT SUPPORTED |
| saves_team_leaky (over; own SA last 5 - season >= 3.3) | +9.7% (25) | +10.2% [-3.4, +23.5] (53 / 50) | +5.3 | NOT SUPPORTED |
| saves_team_b2b (over; team played yesterday) | -2.2% (62) | +3.7% [-9.3, +16.1] (72 / 64) | -2.0 | NOT SUPPORTED |
| HU-NHL-saves (every line, UNDER) | +2.6% [-1.7, +7.0] (405) | **-5.4% [-10.2, -0.4]** (405 / 224) | -- | NOT SUPPORTED |

BH (q = 0.10): none. ROI of blind saves unders at the best book: -0.1% discover, **-15.6%** confirm.

**Reading.** The saves study was underpowered by construction (stated in the registration: only effects near 15 points
could pass). Two over-side signals -- a leaky own defence and a high-volume opponent -- point the same way in both windows
(+9.7% / +10.2%, +3.5% / +10.6%), but the intervals are wide and they are not findings. The NBA / NCAAF under tilt does
**not** carry to saves: in Dec-Feb the OVER beat the close (the eligible over-side baselines ran +4.6% / +5.1% too).

## (B) Skaters, FORWARD on 2026-27 -- registered, grader built, nothing graded yet

K1 toi_up (over; SOG, points; TOI last 3 - base >= 2.4 min), K2 toi_down (under; <= -2.3), K3 opp_allows_shots (over;
SOG; opponent shots against >= 28.7/g), K4 opp_suppresses_shots (under; SOG; <= 23.9/g), K5 skater_under_bias (under; all
two-sided SOG / points / assists / goals). Fair = median Shin over US books + Pinnacle; price = best US book; Holm over
K1-K5 at one-sided 0.025, read once after 2026-12-31. The registered window reports INTERIM with 0 graded (1,353 lines
from games that started before the registration were excluded).

A **format check** on the 2026-27 games before the registration (Oct 7-13; NOT evidence) joined the live files end to
end: 5,463 graded lines over 85 games, 316 void (5.5%). It found one defect, fixed before any window game: in
`--ignore-registration-time` mode the grader still started at the registration day (2 games instead of 85).

## Next (NHL)

- **Decision for the user:** buy the 2025-26 regular-season skater props (~66k OddsAPI credits, ~1.3% of the cap; probe
  one event first) to get a discovery season for K1-K5 instead of waiting for the forward read.
- The two over-side saves leads, if wanted, as their own forward registration on 2026-27 saves (the fleet logs them).
- Plan §6 items not yet built: PP1 deployment (needs per-game PP TOI), opponent goalie / GSAx for skater props, injuries
  and scratches (the collector is running since 10-13).

## v2 -- the bought 2025-26 skater season (2026-10-14T02:24Z): K1-K5 NOT SUPPORTED, no under tilt

**Purchase** (user: "yes buy the 2025-26 skater props, probe one game first"): `scripts/nhl_skater_props_pull.py`, OddsAPI
historical event odds, US region, shots on goal / points / assists / goals at start - 10 min. Probe: 1 game, 40 credits, 7
books. Full run: 1,311 games, **52,430 credits** (52,470 with the probe; estimate 52,480), 0 failed calls. Files:
`backfill/nhl_lines_2025_26/odds_skater_props/<gamePk>.json` on the fleet (copied, 1,312), source `C:/tmp/nhllines`.

**Test** (registered at `7990e51b` before any close was joined to an outcome; thresholds the forward family's, set from
features): 73,652 main lines, **67,737 graded** over 1,312 games (5,915 void: no game-log row / ambiguous name), split
2026-01-04 (656 games each side).

| signal (side) | discover resid (n) | confirm resid [95% CI] (n / games) | confirm hit lift vs base | verdict |
|---|---|---|---|---|
| K1 toi_up (over; SOG, points) | +1.5% (1,531) | +0.6% [-1.8, +2.9] (2,022 / 502) | -0.1 pts | NOT SUPPORTED |
| K2 toi_down (under; SOG, points) | -0.6% (1,055) | -0.9% [-3.9, +1.8] (1,532 / 443) | +0.7 | NOT SUPPORTED |
| K3 opp_allows_shots (over; SOG) | -0.8% (1,166) | +1.4% [-2.7, +5.7] (701 / 89) | +2.1 | NOT SUPPORTED |
| K4 opp_suppresses_shots (under; SOG) | -0.5% (809) | +3.5% [-0.2, +7.4] (737 / 113) | +3.4 | NOT SUPPORTED |
| K5 every line, UNDER | -0.4% [-1.2, +0.5] (33,957) | -0.1% [-1.0, +0.8] (33,780 / 656) | -- | NOT SUPPORTED |

K5 by market (discover / confirm): shots -0.1% / +0.8%, points -0.5% / -0.7%, assists +0.1% / +0.2%, goals **-1.8%
[-2.8, -0.7]** / -1.4% (the goal OVER ran slightly long). Blind skater unders at the best book: -5.3% / -4.9%.

**Reading.** The NHL skater close prices ice-time trends and the opponent's shot suppression -- consistent with the plan's
note that SOG is "the one skater market at parity with the book". Unlike NBA and NCAAF props there is **no under tilt** in
NHL skater or saves props; the cross-sport under effect is a basketball / college-football effect, not a universal one.
K4 (fade shot-suppressing opponents' SOG overs) is the nearest miss (+3.5% in confirm, discover -0.5%) -- a lead at most.
The forward family (K1-K5 on 2026-27) still runs to its 2026-12-31 read at no cost; on this history its prior is weak.

**Next (NHL), if wanted:** PP1 deployment and line-mate changes need per-game PP TOI / line data (not in the game log);
injuries and scratches are being collected since 10-13 (an absence test needs a few weeks of it); the 2025-26 saves
history covers only 449 games -- the remaining ~860 would cost ~8,600 credits (saves, 10 per game) and would roughly double
the saves sample for the two over-side leads.
