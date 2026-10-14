# Football matchup signals v1 -- 13 pre-registered NFL / NCAAF signals vs the closing price: none supported -- 2026-10-14

Lane `signal-engine-football` (session 9e18a0e7). Registered in the lane block at `ceff4ed3` (2026-10-14 00:05Z) BEFORE
any outcome was loaded; thresholds came from `signal_lift_football.py --mode distributions`, which joins lines to
features and reads no outcome. Code: `syndicate/features/shared/matchup_signals_football.py` (features, rules,
registry), `scripts/build_nfl_signals.py`, `scripts/build_ncaaf_signals.py`, `scripts/signal_lift_football.py`.

## Data

- **Lines:** backfilled CLOSING quotes, kickoff - 10 min. NFL `backfill/nfl_prop_closes_2023_25` (7 US books, 53 weeks);
  NCAAF `backfill/ncaaf_props_2024_25`. Two-sided O/U markets only (receptions, receiving / rushing / passing yards,
  rushing / passing attempts); Anytime TD and other yes-only markets excluded. One MAIN line per (event, market, player)
  (most two-sided books; tie -> median Shin p_over nearest 0.5); fair = median per-book Shin.
- **Features** (as-of, same season, weeks before): NFL from nflverse play-by-play (official targets, carries excluding
  kneels and two-point tries, air yards, pass attempts, per-play pass_oe) and nflverse injury reports (final status OUT);
  NCAAF from the CFBD player box (carries, receptions, pass attempts; no targets in the box).
- **Outcomes:** NFL -- production's per-play extractors (`nfl.player_stats._STAT_EXTRACTORS`); a player with no
  qualifying play is VOID (no snap data to tell a DNP from a zero; 703 voids). NCAAF -- the CFBD box row; none -> void
  (257). Pushes void.
- **Joined:** NFL 23,557 lines (discover 2023-24: 14,469 / 352 games; confirm 2025: 9,088 / 210 games). NCAAF 6,484
  (2025 weeks 1-8: 3,267 / 222 games; weeks 9-16: 3,217 / 226 games).
- **NCAAF 2024 excluded, measured before any outcome:** the 2024 box history is partial -- median 14.5 team plays per
  game in the as-of tables against 65 in 2025 -- so every 2024 share and pace would rest on a wrong denominator.

## Results (residual = hit rate - Shin probability on the signal's side; CI over games)

| signal (side) | discover resid (n) | confirm resid [95% CI] | confirm n / games | hit lift vs base (confirm) | verdict |
|---|---|---|---|---|---|
| nfl.target_share_up (over) | -0.2% (609) | -1.7% [-8.8, +5.8] | 342 / 115 | +0.4 pts | NOT SUPPORTED |
| nfl.target_share_down (under) | +0.1% (545) | -4.6% [-11.3, +2.0] | 304 / 95 | -7.0 | NOT SUPPORTED |
| nfl.carry_share_up (over) | **-9.9% [-17.4, -2.1]** (246) | -1.9% [-11.6, +8.4] | 146 / 64 | +1.1 | NOT SUPPORTED |
| nfl.carry_share_down (under) | +0.2% (236) | +3.2% [-7.0, +13.0] | 133 / 59 | +0.4 | NOT SUPPORTED |
| nfl.vacated_targets (over) | -1.6% (557) | **-10.5% [-17.4, -3.4]** | 364 / 58 | -8.3 | NOT SUPPORTED |
| nfl.vacated_carries (over) | -1.3% (165) | +4.1% [-8.5, +17.3] | 107 / 28 | +7.9 | NOT SUPPORTED |
| nfl.team_pass_heavy (over) | -4.2% (139) | -9.6% [-22.6, +4.3] | 72 / 32 | -10.4 | NOT SUPPORTED |
| nfl.team_run_heavy (under) | -1.6% (132) | -14.0% [-30.7, +5.0] | 25 / 13 | -14.9 | NOT SUPPORTED |
| ncaaf.carry_share_up (over) | -12.2% (18) | **-10.2% [-20.0, -0.0]** | 88 / 77 | -7.9 | NOT SUPPORTED |
| ncaaf.carry_share_down (under) | -6.1% (25) | +2.6% [-10.6, +17.0] | 53 / 49 | -0.7 | NOT SUPPORTED |
| ncaaf.reception_share_up (over) | -10.8% (53) | -5.3% [-13.4, +3.6] | 190 / 104 | -5.0 | NOT SUPPORTED |
| ncaaf.reception_share_down (under) | -10.1% (50) | +2.6% [-8.0, +12.8] | 111 / 62 | +1.8 | NOT SUPPORTED |
| ncaaf.fast_game (over) | +0.9% (240) | -4.0% [-13.9, +5.7] | 113 / 11 | -1.8 | NOT SUPPORTED |

BH (q = 0.10) on the confirm p-values: none survive, in either sport.

## Reading

1. **The closing price already knows usage.** Target-share and carry-share trends, team pass rate over expected and
   game pace carry no residual against the close. Consistent with the prior in the plan (§0) and with the NBA minutes
   result: role is the first thing books price.
2. **Where it is wrong, it is wrong the other way -- the market OVER-reacts to news.** Two signals came out
   significantly negative:
   - **Fresh vacated targets (NFL 2025):** receivers whose teammate (>= 10% of targets, played last week) is OUT went
     OVER 10.5 points less often than the close implied. The "next man up" over is overpriced. 2023-24 showed the same
     sign but small (-1.6%, n.s.).
   - **Carry-share spikes:** NFL discover -9.9% [-17.4, -2.1] (confirm -1.9%, n.s.); NCAAF -12.2% (n = 18) and -10.2%
     [-20.0, -0.0]. Recency over-reaction on rushing roles.
   Neither was registered in that direction, so neither is a finding yet -- they are the two leads worth their own
   pre-registration (fade the reaction: the UNDER), tested forward on 2026.
3. **An under tilt again, in some windows.** On the eligible baselines, the under side ran positive in NFL 2025
   (+2.6% on target / carry lines; the over side -1.9% / -2.8%) and in NCAAF 2025 weeks 1-8 (+8.7% / +11.1%), but not in
   NFL 2023-24 and much weaker in NCAAF weeks 9-16. The NBA H6 effect (prop unders under-priced) may be cross-sport;
   it needs the H6-style test (main lines, all eligible players, pooled) before it means anything.

## Limits

- One snapshot (the close): a signal can only show value against the sharpest price of the week. Nothing here says the
  OPENING line already knew -- an open-to-close CLV test needs opening quotes (the fleet logs them from 2026-09-30).
- NFL voids players with no qualifying play, which drops some under wins (703 voids); the under-side residuals are, if
  anything, slightly understated.
- NCAAF discover samples for trend signals are small (18-53 fired) because a trend needs 5 prior appearances and
  discover ends at week 8.
- No snap counts, routes, or coverage data (plan §3: nflverse snap counts are free but need a download; routes are paid).

## Next (football)

- **Register the two over-reaction leads** (fade fresh vacated targets; fade carry-share spikes) and test them FORWARD on
  2026 NFL weeks 7+ and NCAAF weeks 8+ with the fleet's own quote logs (opens and closes).
- **H6-style football unders test** (main lines, pooled) on 2023-25 NFL and 2025 NCAAF.
- Then the plan's remaining items: snap counts (download), opponent-adjusted defense vs position, weather on totals.
