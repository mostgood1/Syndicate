# Soccer roster refresh — does it make the props more accurate? PRE-REGISTRATION — 2026-10-08

Lane `soccer-roster-refresh-accuracy` (session fc6fc474). Written 2026-10-08 ~11:30 CT, before any match
in the population had kicked off. Measured at writing: 0 finished matches with a post-refresh
pre-kickoff build; 99 upcoming in the nine roster-filtered leagues.

## The change being graded (already live; this is not a ship gate)

`6a97aafc` (fleet 2026-10-06 22:38:35Z; first run 2026-10-07 00:11–00:20Z) replaced the 2026-07-20 ESPN
roster seed with current ESPN squads. The roster's only reader in the builder is the departed-player
rescue, so the effect is on WHO is in each squad. Served drops, July -> new: bundesliga 193 -> 169,
ligue_1 245 -> 256, la_liga 179 -> 188, epl 92 -> 140, serie_a 153 -> 225, championship 81 -> 93,
eredivisie 70 -> 131, primeira 120 -> 130, belgian 92 -> 162. Shares re-normalise over the squad, so the
listed players' props move.

## Hypothesis H-RR

Listed appeared players were UNDER-predicted on 09-17..09-30 (SOT realised 0.256 vs 0.233,
`findings_2026-10-06_soccer_roster_only_players_result.md`). Removing departed players frees share for
them. **Expectation: arm B (new roster) has lower log loss than arm A (July roster) on both markets.**

## Design (fixed now)

- **Population:** matches in bundesliga, ligue_1, la_liga, epl, serie_a, championship, eredivisie,
  primeira_liga, belgian_pro_league whose fleet PRE-KICKOFF FREEZE entry
  (`recommendations_prekickoff_<date>.*.json`) has `kickoff` >= 2026-10-07T01:00Z, joined to a FULL-TIME
  ESPN summary (`outcomes.py` extraction). MLS excluded: no departed filter (measured: builds
  unchanged at 853 rows).
- **Arms:** both use the same snapshot of the leagues' player files, taken 2026-10-08T16:25:52Z, before
  every population match (`C:/tmp/soccer-roster-grade/inputs_2026-10-08`, MANIFEST.sha256 digest
  `440d029a419bd3a3`, 41 files). Both use each match's stored pre-kickoff team distribution.
  - **A:** `_load_player_rows` with the July roster (byte-identical to git seed 570ba09f, CR-stripped).
  - **B:** the same with the refreshed roster (snapshot of the fleet files written 2026-10-07 00:11–00:20Z).
  - The roster is the only variable. Engine: `build_soccer_player_features` -> `build_usage_profiles` ->
    `project_player_props`, the code on origin/main at grade time (the same for both arms).
- **Primary metric:** per-player log loss, B − A, on APPEARED outfield players listed in BOTH arms
  (bound one-to-one by `namejoin_diag.strict_match`). Two markets: P(SOT >= 1) from
  `shots_on_target_over_probabilities["0.5"]`, and `anytime_scorer_probability_if_playing`. Summed per
  match; bootstrap over matches, 2000 reps, seed 11, 95% percentile CI; clip 1e-6.
- **Secondary (descriptive):** realised/expected for listed appeared players (anytime, SOT) per arm;
  appeared players present in only one arm (B's rescues vs A's stale keeps) with their counts; per league.
- **When:** first grade on 2026-10-15 (after the 10-09..10-14 slates). If fewer than 60 matches are
  graded, re-grade once, cumulatively, on 2026-10-22 and report that as final, underpowered or not.
- **Verdicts:**
  - SUPPORTED: B − A CI wholly < 0 on both markets.
  - REFUTED: CI wholly > 0 on either.
  - INCONCLUSIVE: anything else.
- **Consequence:** the refresh is not reverted on any verdict, because a July squad list is wrong data.
  A REFUTED verdict opens a lead to re-fit the share calibration (the `calibration_role_mixture*`
  constants), which absorbed stale squads (engine standard 4.4). No re-tuning on this window.
- **Season phase:** all population matches are 2026-27 regular season; no phase mixing.
