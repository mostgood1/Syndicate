# FINDINGS: should NHL consistency rank by hit rate first? No. Hit rate alone is priced in; the profit sits inside the build's pool

Session 9e18a0e7, 2026-10-23, 10:30–11:00 AM CT. Lane `cheat-sheets`. Read-only. Asked by the user ("consistency should
prob go hit rate first? All I know is the NHL consistency sheet has huge ROI right now"), after
`findings_2026-10-23_cheat_sheet_section_growth.md` found the section churns because each build re-picks NHL's top
30 player+stat groups by (Suggested, best EV, books quoting).

## What the numbers rest on

- **Record page:** `/api/cheatsheets/record` on the fleet, generated 2026-10-23 7:53 AM CT. NHL consistency (official,
  10-15 onward plus the 10-14 beta day) is **46-14, +18.51 u on 60 bets (+30.9%)**, positive on all 9 days. The
  shared-only record is 18-5, +7.65 u (+33.3%) on 23.
- **Inside the pool:** every graded row of each day's final NHL sheet (`cheatsheets/nhl/<date>.json`, the 30 built
  groups, every line and side), graded by `<date>.reconciled.json` `props`, 10-14..10-22. 488 rows graded. Flat
  1 u at the sheet's price. Script: scratchpad `nhl_consistency_split.py`.
- **Outside the pool:** every priced NHL pregame prop in the opportunity population, first sighting, 10-17..10-22.
  That is 8,817 rows. 5,443 were in the -250..+250 band and resolved to one player in the game log; 40 were ambiguous
  and 59 had no log. Flat 1 u at the first-sighting price.
  - L10 comes from the fleet's NHL game logs (`nhl_source/source_artifacts/data/raw/player_game_stats.csv` +
    `player_game_log_<season>.csv`): games before the slate day, TOI > 0, pushes excluded.
  - The rule is the section's own: at least 8 graded of the last 10, and at least 70% hit.
  - Script: scratchpad `nhl_hitrate_first.py`.
- Intervals: 2,000 bootstrap resamples over games. Several NHL sheet days have only 2 games, so the single-day
  intervals are too narrow to read alone.

## 1. Inside the pool: the rule separates sharply, and row EV does not matter

| sheet rows (30 built groups, all lines/sides) | bets / games | hit (break-even) | ROI [95% by game] |
|---|---|---|---|
| L10 >= 70% (the consistency rule) | 172 / 47 | 78.5% (66.7%) | **+20.2% [+9.4, +30.8]** |
| L10 < 70% | 316 / 53 | 41.8% (49.1%) | -18.5% [-29.3, -6.6] |
| in the served section (main line, better-EV side) | 69 / 34 | 79.7% (60.3%) | +36.1% [+17.4, +53.6] |
| qualifies, not in the section | 103 / 32 | 77.7% (71.0%) | +9.6% [-3.1, +21.1] |
| qualifying, row EV > 0 | 51 / 28 | 74.5% | +18.8% [+2.0, +40.1] |
| qualifying, row EV <= 0 | 121 / 32 | 80.2% | +20.8% [+6.1, +33.7] |

By stat (qualifying): SOG +47.9% (42), points +16.3% (38), assists +8.7% (89, heavy-juice unders). L10 bands are
flat: 70-79% +21.5%, 80-89% +20.9%, 90%+ +17.4%.

## 2. Outside the pool: hit rate alone is priced in

| hit-rate-first section (one row per player+stat+game, main line = most books, qualifying side) | bets / games | ROI [95% by game] |
|---|---|---|
| **all qualifiers** | 942 / 45 | **-1.4% [-6.5, +3.7]** |
| inside the day's 30-group pool | 66 / 31 | +16.1% [-3.1, +34.3] |
| **outside the pool** | 876 / 45 | **-2.7% [-7.8, +2.4]** |
| every qualifying line and side (not one per group) | 1,073 / 45 | -2.5% [-7.8, +2.5] |
| every non-qualifying line and side | 4,370 / 45 | -9.7% [-11.9, -7.5] |

No stat is clear of 0: SOG +4.2% [-3.7, +12.6], points -1.0%, assists -6.2%. L10 bands are again flat.

This agrees with the 2026-10-14 consistency backtest (NFL + NBA + MLB: 5/5 streaks 2.6 pts below the Shin fair, ROI
-8.5%). Over the whole NHL market, a 70%+ L10 is in the price.

## 3. What about the pool matters? Not found

The pool is the build's top 30 groups by (Suggested, best EV in the group, books quoting) at build time. I rebuilt
that key over the population: the group's best EV anywhere, any line or side, with no cap.
- It does NOT separate the hit-rate-first rows: group best EV < 0 gives -2.1% (803); 0-2 gives +17.0% (53);
  2-5 gives -10.3% (56); 5-10 gives +10.4% (23).
- The bands are not monotone and every interval spans 0.
- So either the pool's edge comes from build-time specifics the population does not carry (the sheet prices at
  the best book at build time, not the first sighting), or the ~70 in-section bets over ~34 games are partly luck.
- **Open, to re-read at ~100 NHL games** (scheduled; see below).

## 4. Decision taken (user, in chat 2026-10-23: "proceed")

- **Do NOT rank consistency by hit rate first.** It would add hundreds of rows a week from outside the pool, and they
  grade -1 to -3%.
- **Keep the pool's selection and make it stable instead:**
  1. A posted section is frozen in every view, with later qualifiers in a separate no-export block. Lane
     `cheat-sheet-section-growth` builds this, with files on loan from `cheat-sheets`.
  2. A group built on day D stays in every later day-D build while its game has not started.
  3. The line and side are locked at the group's first day-D build.
  4. Each row carries its pool rank, so the re-grade can split by it.
  Items 2-4 are built in lane `cheat-sheets`.
