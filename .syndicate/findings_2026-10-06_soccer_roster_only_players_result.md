# Soccer roster-only players — the pre-registered test FAILED; not shipped — 2026-10-06

Lane `soccer-roster-only-players` (session fc6fc474). Registration:
`findings_2026-10-06_soccer_roster_only_players_prereg.md` (5c36cf37, session b9bb5f37). Every choice
the registration left open was fixed in `lanes.md` (landed 9c170ca4, ~14:40 CT) BEFORE the run. The
registered window was run ONCE (14:51–~15:45 CT). **Verdict: FAIL on all three clauses. The change
is not shipped and will not be re-tuned against this window.**

## What was tested

Arm A = the shipped engine on origin/main, replayed (`calibration_engine_replay` method: each
match's stored PRE-KICKOFF team distribution -> `_load_player_rows` -> `build_soccer_player_features`
-> `build_usage_profiles` -> `project_player_props`). Arm B = A's squads + ESPN-roster players with no
row in any of the league's `players_*.csv`: positional-median per-90 rates (G/D/M/F, rows >= 450 min),
`expected_minutes_share` 0.10, team totals unchanged (shares re-normalise, so their mass comes out of
listed teammates). Same distributions, same squads, so the pairing is exact.

Code (measurement only, not production): `scripts/soccer_season_audit/roster_only_players.py`,
`scripts/soccer_season_audit/roster_only_replay.py`. Report:
`C:/tmp/soccer-lpb/roster_only_registered_2026-10-06.json`.

## Data and coverage (substrate: session caches + fleet copies, NOT a verified mirror)

| family | source | coverage |
|---|---|---|
| pre-kickoff builds | `C:/tmp/soccer-lpb/cache/prod/recs` (`load_recs(prekickoff_only=True)`) | 314 builds; 119 in window |
| ESPN box scores | same cache, `outcomes.json` (fetched 10-02) | 712 matches, to 09-30 |
| player stats files | same cache, production pull of 2026-10-02 | LEAK: up to 15 days after a match |
| ESPN rosters | fleet `~/syndicate-prod/.../rosters_2026.csv` | = the git seed (committed 2026-07-20); bundesliga 142 / ligue_1 223 / la_liga 353 rows, partial |
| first-goal order | `%TEMP%/espn_shots_cache` (715 summaries) | 119 of 119 scored matches |

**Intersection: 119 matches on 7 dates, 2026-09-17..09-30, 3,121 appeared outfield players listed in
both arms.** The stats-file leak shrinks the roster-only set (biased toward the null); the stale roster
misses late-window signings. Both are stated, neither changes the direction below.

## Result (B − A, log loss per player, match bootstrap 2000, 95% CI)

| market | n players / matches | A | B | B − A | CI | registered bar |
|---|---|---|---|---|---|---|
| SOT 0.5 (if playing) | 3,121 / 119 | 0.54756 | 0.54918 | **+0.00162** | **[+0.00043, +0.00286]** | CI < 0 — **FAIL (significantly WORSE)** |
| anytime (if playing) | 3,121 / 119 | 0.28702 | 0.28723 | +0.00021 | [−0.00043, +0.00087] | CI < 0 — **FAIL (crosses 0)** |

| listed-player calibration (realised / expected) | A | B | bar |
|---|---|---|---|
| anytime, appeared listed players (n 3,121) | 1.033 | 1.074 | toward 1.0 — **FAIL** |
| first scorer, starters (2,135 starter-rows, 96 first goals; board's `scorer_race`) | 1.70 [1.56, 1.85] | 1.78 [1.62, 1.93] | toward 1.0 — **FAIL** |

(The registration quoted 1.33 for starters' first scorer; that was the board's STORED lists over 300
matches. The A/B comparison here computes both arms identically, which is what the clause asks.)

Season phase (descriptive, per lane choice 9): SOT B − A is positive in every substrate — current-season
rows +0.00147 [−0.00021, +0.00327] (n 2,225), prior-only +0.00264 (n 97), single-season (MLS)
+0.00193 [+0.00101, +0.00280]. Per league, SOT is worse in 7 of 10 (better: belgian, eredivisie,
primeira). Nothing here is a subgroup to rescue: the rule is pooled and was not re-chosen.

## Why it fails (diagnosis, NOT a re-tune)

The registration's premise was that listed players' shares are OVERstated because absent players' mass
is handed to them. The data say the opposite: listed appeared players are already UNDER-predicted
(SOT realised 0.256 vs A 0.233; starters' first scorer 1.70x), so moving mass OFF them makes every
listed number worse. The added players themselves are also under-predicted when they appear (67
appeared: SOT realised 0.164 vs predicted 0.109; goals 0.045 vs 0.035). Both point at the team total
being too SMALL for the people who actually play, not misallocated — consistent with lane
`soccer-shots-allocation-blend` (starters under-projected, 0.858 vs 1.101). A version that ADDS mass
instead of redistributing it is a different hypothesis and would need its own registration and a fresh
window; it is recorded as a lead, not run.

## Board coverage (what shipping would have bought)

Fleet, priced props 10-04..10-11, players with no exact-name sim row: 641 players / 19,816 lines. The
mechanism would have added **87 players / 1,987 lines** (epl 26, mls 40, serie_a 14, ligue_1 4,
bundesliga 2, la_liga 1) — consistent with the registration's 77 roster-only; it cannot reach the 139
in neither source. That coverage is real, but on this evidence the projections it adds come at the cost
of worse prices on the 3,121 listed players, so it is not a trade the pre-registered rule allows.

## Also found

Soccer ESPN rosters have NO production producer: `scripts/build_soccer_rosters.py` is manual, and the
fleet's files are the July git seed. Any future roster-based mechanism (and today's departed-player
rescue) is reading a July squad list.
