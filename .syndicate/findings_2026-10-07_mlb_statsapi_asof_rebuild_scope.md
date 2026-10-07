# Scope: StatsAPI-only as-of rebuild of MLB 2026-07-16..09-27

User, 2026-10-07: "yes, scope the StatsAPI rebuild for 07-13..09-29". Scoping only; nothing is built yet.

## Why

The combined calibration (lane `mlb-combined-calibration`, shipped 2bb481ef) used up the season's
untouched regular-season data. Its fit set was 24 dates / 311 games and its validation set 15 / 203.
The fleet has no stored inputs for 07-13..09-29: they lived on Render, which is suspended. From 09-30 on
it is postseason, a different population. A follow-up question (the starter walk reading: fit -0.015,
validation +0.126 at 1.9 SE) cannot be settled without fresh data.

## The window

- StatsAPI schedule, gameType R: **74 dates, 07-16..09-27**.
  - The All-Star break is 07-13..07-15; the regular season ended 09-27.
  - **984 Final + 1 Completed Early**; 7 postponed and 1 cancelled are skipped.
- About 3x the shipped fit set, and about 1,950 starts.

## What the as-of builder needs, and where each piece comes from

The builder is `scripts/mlb_asof_roster_build.py`. Today it reads lineups.json, probables.json and the
stored sim record (context) from production's files.

| Input | Today (June) | StatsAPI source for 07-16..09-27 | Fidelity, measured on June 06-15..06-22 (104 games) |
|---|---|---|---|
| Season stats | DateBoundedClient, byDateRange <= D-1 | same, works for any date | n/a (already leak-free) |
| Statcast features | raw pitches <= D-1 | fleet raw_pitches/2026 runs to 09-30 | n/a |
| Probable starters | stored probables.json | feed `gameData.probablePitchers` | **169/184 = 92%** equal to stored (late changes / openers) |
| Park | stored sim record | `fetch_game_context` (production's own function) | **104/104** identical |
| Umpire | stored sim record | same | **104/104** identical |
| Weather | stored sim record | same | temperature median \|diff\| 1 F (max 11); wind string equal only **17/104** (pregame forecast vs game time) |
| Lineups | stored lineups.json | see below | see below |
| Bullpen availability | empty | empty (unchanged; optional upgrade: from prior days' feeds) | consistent with the fit regime |
| Outcomes | boxscores | boxscores (cached) | n/a |

### Lineups are the one real fidelity problem

Production mostly simmed on **projected** lineups. Of 208 June sides:

| Source | Sides |
|---|---|
| Rotowire "default vs RHP/LHP" | 175 |
| Rotowire same-day | 20 |
| Confirmed from the feed | 13 |

The projections matched the real starting nine at **0.768 mean overlap**, about 2 of 9 batters wrong. Two options:

- **A. Actual lineups from the feed** (`parse_confirmed_lineup_ids`, production's parser). Simple, but it
  is hindsight: inputs better than production had. That makes validation optimistic, mostly for hitter props.
- **B. An as-of projection from StatsAPI history**: the team's most frequent lineup vs RHP / vs LHP over
  its prior N games, from boxscores dated < D. This emulates Rotowire defaults. Historical Rotowire
  projections themselves are not recoverable.
  - Its fidelity is measurable on June (overlap with production's stored projections and with actual).

**Recommendation:** B as the primary input, gated on June fidelity, with A as a sensitivity arm.

## Work

1. **Builder `--source statsapi` mode.**
   - Games from the schedule; lineups (A or B); probables and context from the live feed.
   - Writes a minimal synthetic sim record (schedule, teams, weather, park, umpire), so the replay /
     decomposition / prop tools run unchanged. About 150 lines plus tests.
2. **As-of lineup projector (B).** About 80 lines plus a June fidelity probe.
3. **Shared StatsAPI cache across dates** for date-independent responses (full-season gameLog, which is
   filtered < D after fetch; person info; prior-season splits). byDateRange keys stay per date.
   - Today every date starts a fresh cache, and those requests dominate build time.
4. **Fidelity gate, pre-registered before any use.**
   - Rebuild 06-15..07-12 with `--source statsapi` and replay it against the existing stored-input rebuild.
   - Same moments and tolerances as the earlier gate: per-PA rates <= 0.003 (K/BF <= 0.005), starter outs
     <= 0.30, <=9 / ==15 shares <= 0.03, DP/PO <= 0.05, runs <= 0.30, within max(2 SE, tolerance).
   - This isolates exactly what the new source changes: lineups, probables and context.
5. **Build 07-16..09-27** into a scratch root (never the production data root), nice'd.

## Cost and risk

- **Runtime.** June builds ran about 35-40 min per date per worker at 5 workers, under contention.
  - 74 dates is about 9-10 h, less with the shared cache.
  - Feeds: 985 x ~1.5 MB is about 1.5 GB of cache.
- **Session work** for items 1-4: about half a day, plus the gate run (about 1 h).
- **Risks:**
  - Lineup projection B may not reach production's fidelity; the gate decides.
  - The wind-string drift changes HR context slightly; the gate measures it.
  - Fleet contention with production sims; run nice'd and outside the MLB sim windows.
  - StatsAPI rate limits: none seen across about 1,000 feed pulls this week.

## What it unlocks

- Re-check the starter walk question on about 1,950 starts.
- A fresh, untouched validation set for future MLB calibrations, plus a much larger fit set.
- Evaluation of the shipped calibration out of sample, on the second half of the season.
