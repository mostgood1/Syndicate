# Matchup signal plan -- advanced data as edge, NFL / NCAAF / NBA / NHL first -- 2026-10-13

Session 9e18a0e7. User direction: "We need a structured advanced data/matchup plan for all sports with a priority on
NFL, NCAAF, NBA, and NHL ... make sure you look at what industry standard is for advanced data analytics including
sources we are missing." Built from four parallel tracks: football / basketball / hockey data inventories (fleet disk +
origin/main, read-only) and an external survey of industry-standard analytics and sources. Companion to
`findings_2026-10-13_layer2_edge_deep_dive.md` §8 (restructured plan) -- this is its Track B, made concrete.

## 0. What the engine is

Every line on the board gets two readings, kept apart:

- **Likelihood of success** = the calibrated market probability (fair price v2, Shin) adjusted by the matchup signals
  that fire on it, each with its MEASURED lift.
- **Value** = whether the price already reflects that likelihood.

A **signal** is a named, point-in-time matchup feature for one bet type (e.g. "receiver's target share rising over the
last 3 games", "opponent allows the most shots per 60", "starter's teammate ruled out"). Each signal has a definition,
a source, and the moment it becomes known; its values are stored in a dated, append-only as-of table so no backtest
sees the future. Each signal is graded on the lines it fires on:

- lift vs the **baseline hit rate** -- does the signal predict at all?
- lift vs the **calibrated market probability** -- does the price already know it?

Discover on prior seasons, confirm on held-out / forward weeks, control false discoveries across the search, report n,
games, and the interval. On the board: validated signals show their lift; unvalidated ones show as research, labelled.

**Prior, stated once:** the ledger already shows much public data is priced (NFL QB-prop inputs, NFL injuries over 17
seasons, NCAAF situational factors, NHL moneyline inputs). Expect many signals to land as "strong, already priced". That
is a correct, useful answer -- it is the likelihood-vs-value split working, not a failure.

## 1. Do now -- time-critical, cannot be backfilled

| # | action | why now |
|---|---|---|
| 1 | **Timestamped, append-only news collectors.** NBA official injury report (15-min snapshots; game-day resubmission windows 8-10am / 11am-1pm), starting lineups pre-tip, referee assignments (official.nba.com ~9am ET). NHL injuries / scratches, Daily Faceoff confirmed goalies + line combos (persist the history), referee crews (NHL API right-rail). NFL practice participation (Wed-Fri), game designations, inactives at T-90 min -- with capture time. NCAAF conference availability reports (SEC / Big 12 / ACC / Big Ten). | News latency and teammate-absence signals need the TIME each fact became known. That history cannot be reconstructed later. NBA opens 10-20. |
| 2 | **Make the backfill data durable on the fleet.** NBA 2025-26 prop prices (`C:\tmp\nba_bt\out`: 1,984,547 rows, 1,294 events, one snapshot 45 min pre-tip + actuals); NHL 2023-26 box / PBP / landing caches, DFO goalie history (266 dates), 2025-26 game-line closes (`C:/tmp/nhllines`); NFL 2023-25 prop closes (`data/nfl_source/tracking/book_quotes/<season>_wk<W>.jsonl`, 64,007 graded bets); NCAAF props 2024-25 (`C:\tmp\football_scenarios\ncaaf_props`, 1,095 games). | Every one of these lives only on this dev machine, outside git and outside the fleet. They are the discovery sets; losing them costs a season. |
| 3 | **Fair price v2 (Shin) live** -- the yardstick every lift is measured against. Staged on the fleet (`d1189be2` + env), loads at the next supervisor `up` (window ~21:05Z 10-13). | A signal's lift vs market is meaningless against a biased fair. |

## 2. Shared infrastructure (build once, all sports)

1. **Signal registry** -- one module listing each signal: name, sport, bet types, definition, source artifact, as-of
   rule, and validation status / measured lift.
2. **As-of feature store** -- dated tables per sport (`<sport>_source/signals/<signal>/<date>.parquet|csv`), disk-backed
   under `SYNDICATE_DATA_ROOT`, allowlisted in `HOT_ARTIFACT_PATTERNS`, with an input checklist per
   `docs/ai_context/model_engine_standard.md`.
3. **Lift harness** -- extends `scripts/fair_price_eval.py`: join graded lines (recorder, quote logs, backfill) to signal
   values as-of the sighting time; report hit-rate lift vs baseline and vs the Shin fair, game-clustered CIs, FDR.
4. **Board surface** -- per row: `signals: [{name, value, lift_vs_base, lift_vs_market, status}]`, `likelihood`, and the
   existing value fields; the Suggested view keeps meaning "+EV".

## 3. NFL (priority 1)

Measurement substrate: 2023-25 prop closes (64,007 graded bets, dev -> fleet), 1999-2026 game closes on the fleet,
2026 forward ~700 two-sided prop lines and ~45 full-game lines per week; quote change logs since 09-30.

| signal | bet types | data today | gap / source / effort | in model today? |
|---|---|---|---|---|
| Snap share | rush att/yds, rec, rec yds | no | nflverse `load_snap_counts` (free; PFR-sourced, "unofficial") -- S | no |
| Target share, air-yards share, aDOT, inside-10 share (trend) | rec, rec yds, ATD | derivable from nflfastR pbp 2022-26 on the fleet | compute as-of -- S | no (season mean only; a pbp-share test was null as a MEAN input -- test it as a TREND / change signal) |
| Teammate absence -> usage redistribution | rec, rush, ATD | injuries 2009-25 (dev) + 2026 + ESPN inactives from 10-01 | timestamped inactives (item 1.1) | QB-start refusal only; the one borderline lead (`share_inj` rush yds corr 0.084 [0.02, 0.15]) |
| Game script x pace / PROE (residual over the existing multiplier) | pass att/yds, rush att, totals, 1H | pbp `xpass`, `pass_oe`; schedules spreads/totals | team as-of aggregates -- S; fix ONE neutral-situation definition | multiplier yes (+1.18 ROI pts, still negative); PROE no |
| Opponent defense vs position, pace- and opponent-adjusted | skill props | raw DvP week 4/5 only | rebuild 2022-26 from pbp -- S | display text only |
| Pressure / OL vs pass rush | pass yds, INT, sacks, spread | pbp sack / qb_hit proxy | FTN charting (in-season within 48 h, CC-BY-SA) -- M | no |
| Coverage man/zone | pass, rec | no | FTN charting in-season; nflverse participation only after the season -- M | no |
| Routes run, route participation, TPRR / YPRR | rec, rec yds | no | NO free in-season source: proxy snap share x dropbacks; paid PFF Pro ($199.99/yr, API; check commercial terms) or FTN / Fantasy Points Data -- M/L | no |
| Weather (wind, temp, precip; forecast) | totals, passing, kicking, 1H | observed only | forecast capture -- M (best academic prior of any matchup factor) | no |
| Rest, travel | spread, total | `home_rest` / `away_rest` | travel from venue -- S | no |

**Build order:** (1) snap + target / air-yards / inside-10 share trends; (2) teammate-absence redistribution;
(3) game script x pace / PROE residual; (4) adjusted defense vs position; (5) weather + rest on totals / 1H.

## 4. NCAAF (priority 2)

Substrate: NCAAF props 2024-25 (1,095 games, dev -> fleet), 2026 forward ~800 two-sided prop lines and ~175 full-game
lines per week. 64% of NCAAF prop lines are yes-only anytime TD (baseline those on the vig-inclusive price).

| signal | bet types | data today | gap / source / effort | in model today? |
|---|---|---|---|---|
| Pace / tempo (plays per game, seconds per play) | totals, segments, volume props | 2025 season-end snapshot only, overwritten | CFBD plays, as-of weekly -- M | default-off flag; otherwise a hardcoded 24.0 s/play. Totals are the model's worst market |
| Game script (spread / implied total) | all props | yes (quote logs, CFBD lines) | mirror NFL's multiplier -- S | no NCAAF multiplier exists |
| Weather | totals, passing | 2025 legacy CSVs | CFBD `/games/weather` -- M | no |
| Opponent-adjusted success rate, PPA, havoc, explosiveness (as-of) | yds props, sides, totals | SP+ / PPA computed in memory, not stored | persist weekly table -- S | game lines yes, props no |
| Role volume / QB change | rush, rec, pass | box counts 2023-26 | carry / reception share + QB-change detection -- M | season mean only |
| Availability reports | all | none (no NCAAF injury feed) | conference releases (item 1.1) -- M | no |

Source note: CFBD terms (2026-08-12) permit commercial use; tiers $1 / $5 / $10 per month (75k calls + realtime at
$10). The quota is shared with college basketball and was exhausted 08-30: move to the $10 tier.

**Build order:** (1) pace / tempo for totals and segments; (2) game-script multiplier for props; (3) weather;
(4) as-of opponent-adjusted efficiency table; (5) role / QB-change detection.

## 5. NBA (priority 3 -- opens 10-20)

Substrate: 2025-26 prop prices (1,984,547 rows, 203 dates, one snapshot 45 min pre-tip; durable copy first),
`player_game_log_2024|2025.csv` (28k rows each), stats.nba logs, 10 seasons of schedule features; forward from 10-20
the per-book change log. At ~7.5 games a night a 2-point lift needs most of a season forward-only: discover on 2025-26.

| signal | bet types | data today | gap / source / effort | in model today? |
|---|---|---|---|---|
| Minutes / role projection (the base layer) | all props, 1H / Q | game logs 2024-25, rotation stints 239 dates | role-change features -- S; FIX: `rotation_minutes` applied 0/70 sides (preseason guard), `starter_prob` merge matched 0 of 26 | partly; minutes bias -3.67, MAE 6.64 vs 5.27 for last-5 |
| Teammate-out usage shift + news latency | pts / reb / ast / 3pm / PRA, team totals | `raw/injuries.csv` from 09-30, date only, no capture time | timestamped official injury report (item 1.1) -- S | OUT exclusion only; on/off retired 10-13 (model-side redistribution exonerated -> test the PRICE lag, not the model) |
| Rest / back-to-back / 3-in-4 / travel | sides, totals, 1H; props via minutes | 11,969 games 2016-26, schedule-derived = point-in-time | travel / altitude from arenas -- S | B2B only (-1 possession / team) |
| Blowout risk x starter minutes | starter props, team totals, 2H / Q4 | spreads + minutes-by-margin on disk | S | `blowout_bench_rest` default off: untested |
| Pace-adjusted defense vs position; opponent-allowed rebound / 3PA / assist opportunity | pts / reb / ast / 3pm / PRA | one DvP file (39 of ~82 games); own team rates | rebuild DvP from full logs + possessions -- M; opponent-allowed rates -- S; FIX: `fg3a_rate` loaded then dropped | bounded multiplier (empty until 2026-27 games) |
| Referee crew | totals, FT-driven points | nothing stored | official.nba.com ~9am ET (item 1.1), history re-fetch -- M | no |
| Tracking: rebound chances, potential assists, touches | reb, ast | no | stats.nba.com tracking (ToS grey area; cloud IPs blocked; cdn.nba.com works) -- M | no |
| Player impact (DARKO / EPM / LEBRON) for injury-adjusted team ratings | sides, totals | no | public sites; check terms -- M | no |

Also missing: team totals and quarter lines are not fetched; home-court advantage is not applied (file absent).

**Build order:** (1) minutes / role (fix the two broken joins first); (2) rest / B2B / travel -- cleanest
point-in-time history, and a null validates the harness; (3) blowout risk x starter minutes; (4) pace-adjusted DvP +
opponent-allowed opportunity; (5) teammate-out PRICE lag once the timestamped injury log runs.

## 6. NHL (priority 4 -- in season)

Substrate: no prior-season skater prop prices on disk (saves closes only); buy 2025-26 via OddsAPI historical
(~66k credits for 5 markets, ~1.3% of the 5M cap -- probe one event first); 2026 forward ~3,900 lines / 50 games per
week (Pinnacle two-sided on ~2,800 lines). Player game logs 2023-26 (139k rows) on the fleet.

| signal | bet types | data today | gap / source / effort | in model today? |
|---|---|---|---|---|
| TOI and PP1 deployment -- level and CHANGE | SOG, points, assists, goals | game logs 3 seasons; lineups overwritten per run | change feature (last-3 vs 10 games, PP1 promotion) -- S; store per-game PP TOI -- S | level yes (overstated: L1 21.56 vs 19.39 real, PP 6.84 vs 4.66 min); change no |
| Individual shot rate (iCF/60, ixG, attempt-to-SOG conversion) | SOG, goals, points | per-game SOG mean only | from NHL API PBP + in-house xG -- M | SOG mean yes; attempts / ixG no |
| Opponent shots / xG allowed, score-adjusted (as-of) | SOG, points, saves, totals | team files overwritten (7 daily backups) | as-of rebuild from cached box scores -- S | game lines yes; **props no** (props ignore the opponent) |
| Opponent goalie: confirmed starter, GSAx | goals, points, saves, totals | DFO 17 dates on the fleet, 266 on dev; GSAx built | persist DFO history -- S | game lines yes (ML null); props never see GSAx |
| Rest / back-to-back incl. goalie B2B / travel | saves, SOG, totals | none | derivable from schedule -- S; travel -- M | no |
| Game script (implied team total, favourite) | SOG, points, saves | quote logs | S | no |
| Injuries / scratches / line combos | points, assists, goals, SOG | none (the injury builder is a placeholder) | ESPN injuries endpoint, DFO lines, right-rail scratches -- M, forward-only (item 1.1) | proxy only |
| Penalties / PP opportunity, referee crew | points, assists, saves, totals | team special teams (frozen to 11-01) | referees via right-rail -- M | team yes, referees no |

Sources: NHL API (play-by-play, shift charts; free, undocumented); MoneyPuck (free NON-commercial only -- a benchmark,
not a production input); Evolving-Hockey Pro (paid: xG, GSAx, RAPM); Daily Faceoff (goalies, lines); NHL EDGE
(descriptive, low priority). Period lines are never captured (the fetch omits them).

**Build order:** (1) TOI / PP1 deployment change; (2) opponent-adjusted shot suppression x individual shot rate (SOG,
saves -- SOG is the one skater market at parity with the book, so added information is measurable); (3) injury /
scratch collector + absence proxy test; (4) rest / B2B incl. goalie; (5) game script from implied team totals.

## 7. The other sports (after the four)

- **MLB** (offseason): backfill 2026 pitch-level Statcast (the vendor fetcher exists) for batter vs pitcher, batter vs
  arsenal, recency; outcomes from StatsAPI; historical batter props from OddsAPI. Re-test umpire signals: the 2026 ABS
  challenge system (~54% of ~10.5k challenges overturned) weakens them.
- **WNBA** (May 2027): full 2026 season test bed already on the fleet; same builders as NBA.
- **NCAAB** (November): 196,865 player-box rows; no odds log yet; CBBD shares CFBD's commercial terms and quota;
  KenPom ($25-30/yr, no API) and Torvik (free) for ratings.
- **Soccer**: FBref lost Opta advanced data (incl. xG) in January 2026; StatsBomb open data is a research subset;
  Premier League team sheets go out 75 min before kickoff (an expected-XI / late-change signal).

## 8. Industry-standard sources -- what we have and what to add

| tier | sources | status | action |
|---|---|---|---|
| Free, add now | nflverse (snap counts, pbp, NGS, FTN charting), NHL API (pbp, shifts), cdn.nba.com / ESPN, official injury reports (NFL / NBA / WNBA / conferences), official.nba.com referees, Daily Faceoff | partly used | collectors + as-of tables (items 1, 3-6) |
| Low-cost paid | CFBD $10/mo; PFF Pro $199.99/yr (API; verify commercial terms); Evolving-Hockey Pro; Cleaning the Glass; RotoWire news feed (quote) | none | buy only after a free signal in the same family shows lift (e.g. routes after snap-share lift) |
| Odds | Pinnacle API closed to the public 2025-07 (apply); SharpAPI ($79-399/mo); OpticOdds (quote, 100-200+ books); OddsAPI historical props since 2023-05 (5-min snapshots, 10 credits per market per region) | OddsAPI only | sharp reference first (fair price v2 + coverage plan, edge deep dive §7) |
| Enterprise | Genius (NFL official / NGS, exclusive), Sportradar (NHL exclusive, NBA non-exclusive), Second Spectrum, SIS, Stats Perform / Opta | none | not now |

Licensing cautions: MoneyPuck is non-commercial; stats.nba.com ToS is a grey area and blocks cloud IPs; Natural Stat
Trick, Baseball Savant and Understat terms were not found -- do not scrape commercially without asking.

## 9. Sequence

- **This week (to the NBA opener 10-20):** collectors running (item 1.1); backfill data durable on the fleet (1.2);
  fair price v2 live (1.3); signal registry + as-of store + lift harness skeleton; NFL snap / target-share and NBA
  minutes / role features built and tested on backfill.
- **Weeks 2-4:** top-3 signals per priority sport tested; board surface v1 (success indicators with measured lift;
  research-labelled for the unvalidated); NBA teammate-out price-lag reading once the injury log has a week.
- **Weeks 4-8:** remaining top-5 per sport; paid-data decisions driven by which free signals showed lift; MLB backfill.

## 10. Guards

- Every new input follows `docs/ai_context/model_engine_standard.md` (input checklist, disk-backed, allowlisted).
- Signals live in NEW files and as-of tables OUTSIDE the engines; files claimed by open lanes (e.g. NHL `loaders.py`,
  `backtest_nba_lines_props.py`) are not edited without the owner.
- Pre-register each signal's test (definition, split, metric, bar) before reading outcomes; report lift separately from
  EV; game-clustered intervals; false-discovery control across the search.
- One change per deploy; measurement before any engine change.
