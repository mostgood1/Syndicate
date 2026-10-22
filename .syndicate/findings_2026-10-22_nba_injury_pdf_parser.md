# NBA official injury-report PDF parser: spliced names and the Available shift — findings 2026-10-22

Lane `nba-injury-pdf-parser`, session ef55f9f7 (side session of local_c0ccc55a). Follow-up to `#723`
(`findings_2026-10-22_nba_sim_minutes_allocation.md` §2 Q1a). Todo `#725`. Times are US Central.

**Substrates.**
- The PDFs are the NBA's own: 167 half-hourly reports, `Injury-Report_2026-10-19_12_00AM` .. `2026-10-22_11_00AM`
  (ET in the file names). They were fetched from `ak-static.cms.nba.com` 2026-10-22 ~10:25 AM CT. Earlier dates
  return 403 (10-10..10-18 probed). The season page lists only TODAY's 45 reports.
- The roster is the fleet's `nba_source/data/processed/rosters_2026-27.csv` (ESPN current, fetched 7:40 AM CT,
  519 names). A read-only copy was used.
- The code under test: the worktree, against `origin/main`'s parser. That file is unchanged since the 10-19 freeze
  (`5dba2973`).
- This is a LOCAL RUN: evidence about the code, not about the fleet. The fleet still runs the old parser.

## 1. The two defects, on the real token stream

pypdf extracts the report one word per line. `_parse_pdf_rows` (`syndicate/features/nba/source_cli/scrapers/injuries.py`)
walks those tokens.

**(a) A reason's last word is spliced into the next player's name.** The 10-21 5:00 PM ET report reads:

    ... Out Injury/Illness - Right ACL Tear Wilson, Jalen Questionable G League - Two- Way Orlando Magic ...

`looks_like_player_start` accepts `<word> Last,` as a two-token surname. That rule exists for `Lively II,` and
`Butler III,`. The reason loop therefore stops before `Tear`, and the next row is `Jalen` + `Tear Wilson`.
This is not occasional. Across all 167 reports, the tokens most often found right before a `Last,` token are:
- `Strain` 759, `Surgery` 759, `Way` 456, `Sprain` 334, `Soreness` 322, `Management` 188, `Tear` 161,
  `Tendinopathy` 145.
- The ONLY genuine two-token surnames in the corpus are `Lively II,` (60) and `Butler III,` (56).

The vendored `_NOISY_PLAYER_TOKENS` list (SORENESS, SPRAIN, STRAIN, SURGERY, MANAGEMENT ...) was a patch over exactly
these words. It is why the common ones were repaired, and why WAY, TEAR, TENDINOPATHY, SUBLUXATION, BURSITIS, BRUISE
and PROTOCOL were not.

**(b) An Available row takes the next player's status.** The 10-21 11:30 PM ET report reads:

    Curry, Stephen Available - Moody, Moses Out Injury/Illness - Left Patellar Tendon Repair / ...
    Awaka, Tobe Available - Claxton, Nic Out Injury/Illness - Left Hamstring Strain ...

`Available` was not in `STATUS_TOKS`. The status scan never stopped at the next `Last,`, so it ran on to Moody's `Out`.
- The old parser's row is `Stephen Available - Moody, Moses Surgery Curry`, OUT. The `Surgery` is defect (a), as well.
- The cleaner flagged it noisy and mapped it by last name + first initial to Stephen Curry.
- Moody's own row was lost.

This is the measured 10-21 swap (`GSW:+STEPHEN CURRY/-MOSES MOODY`, `CHI:+TOBE AWAKA.../-NIC CLAXTON`). It is now
confirmed on the real PDF; before this lane it had only been reproduced on a synthetic stream.

## 2. The fix (`syndicate/features/nba/source_cli/scrapers/injuries.py`)

- `Available` is a status token. It ends its row, and its rows are DROPPED before return.
  - It is not an injury, and the file has never carried such rows.
  - `features_enhanced.add_injury_features` counts rows per team (`*_injuries_total`), so writing them would move a
    model input.
  - Not on the report and Available both mean "plays" to every reader (snapshot semantics).
- The status scan stops at a token ending in `,`. One row can no longer run into the next and take its status,
  whatever the unknown status word is.
- A two-token surname's first token must contain a letter. Without this, `- Moody,` made the name `Moses - Moody`.
- **Roster repair at emit.** A name that is not an exact roster name goes through `_roster_repair_name`.
  - Interior words are dropped until the name is exactly ONE roster player on that row's team.
  - The first and last words are kept. Ambiguous or unmatched names keep their raw form, so an off-roster name is
    never guessed.
  - Words dropped from the front of the surname are appended to the previous row's reason, which is where they were
    cut from (`G League - Two- Way`, `... ACL Tear`).
- `_clean_injury_player_names` (runs over the whole file on every write):
  - It applies the same repair, so ESPN/Rotowire rows and earlier snapshots are repaired on the next write.
  - It no longer maps a comma-merged name to either player. A merged row is two players, and mapping it to one is
    exactly the Curry-for-Moody error.
- A real two-word surname is kept by construction, because an exact roster match wins. The roster has one:
  `David Jones Garcia`. A suffix-only parser rule would have cut him to `David Garcia`, and a drop-only repair cannot
  put `Jones` back. That is why the roster decides and the parser does not.

**Tests:** `tests/test_nba_injury_pdf_parser.py`, 9 tests.
- Real 10-21 token streams go through the real `_parse_pdf_rows`, with only `PdfReader` stubbed.
- One test runs through `NBAInjuryDatabase.update_injuries`, the write path, with the URL and download stubbed.
- **Reachability:** the same file against `origin/main`'s parser fails 6 of 9. The 3 that pass both ways are guards:
  a normal row, two-word surnames kept, and an off-roster name never guessed.
- Related suites pass: 36 tests (`test_sim_injury_feed_snapshot`, `test_basketball_injury_exclusion_reinclusion`,
  `test_nba_source_cli_reachability`, `test_lineup_injuries_native`, `test_basketball_cli_env_data_root`).

## 3. Before / after on the real reports (`scripts/nba_injury_pdf_reparse.py`)

Each report goes through the write path's two steps (`_parse_pdf_rows` -> `_clean_injury_player_names`). The old
parser and the new one use the same roster. "Excluding" is the SmartSim set: OUT / DOUBTFUL / SUSPENDED / INACTIVE /
REST. Only a ROSTERED name can exclude anyone from a pool, so exclusion changes are counted on rostered names.

| 167 reports, 10-19..10-22 | old | new |
|---|---|---|
| rows written | 5,658 | 5,658 |
| rows whose name is on no roster | **971** (17.2%) | **0** |

The row count is unchanged by construction. A merged pair was one row before, and is one row now: the Available row
is dropped and the other player is kept.

**Status assignments that changed (rostered names, summed over reports):**
- **781 exclusions gained**: 29 players who were OUT/DOUBTFUL on the report and excluded under no matching name.
- **111 exclusions lost**: 12 players the old parser gave someone else's OUT. All 12 were listed Available on those
  reports: Curry, Awaka, Miller, Collins, Kessler, Simons, Bona, Slawson, Brown, Avdija, Potter, Harkless.
- 392 non-excluding rows gained. These are Questionable/Probable players now matched: Simons, Goldin, Gilbert,
  Wilson, Sexton, Potter, Wade, Howard, Prince.
- 91 non-excluding rows lost. These are Gardner and Kessler: Available players who had been given the next
  player's Questionable.
- 0 other status changes.

**Per date (mean per report, then the day's last report):**

| date | reports | off-roster old -> new | +excl | -excl | last report: off-roster, +excl, -excl |
|---|---|---|---|---|---|
| 10-19 | 48 | 1.1 -> 0 | 0.5 | 0.0 | 11:30 PM ET: 4, 2, 0 |
| 10-20 | 48 | 6.4 -> 0 | 4.9 | 0.5 | 11:30 PM ET: 14, 12, 2 |
| 10-21 | 48 | 11.8 -> 0 | 10.4 | 1.8 | 11:30 PM ET: 12, 20, 9 |
| 10-22 | 23 | 2.0 -> 0 | 1.0 | 0.0 | 11:00 AM ET: 2, 1, 0 |

**On the last 10-21 report before the first tip (6:30 PM ET = 5:30 PM CT):**
- 14 off-roster names -> 0.
- 16 players gain an exclusion: Gilbert, Gueye, Wilson, Zikarsky, Furphy, Braden Smith, Bradley, Howard, Timme,
  Mark Williams, Simmons, Diop, Swain, Hawkins, Sexton, Claxton.
- 4 lose a wrong one: Awaka, Miller, Collins, Kessler.
- Curry was Probable at that hour. The Curry/Moody swap is on the reports from ~10 PM ET.

The defect is LIVE today. The fleet's `raw/injuries.csv` 10-22 snapshot (read 10:2x AM CT) holds
`Khalifa Tendinopathy Diop` OUT and `Dean Tear Wade` QUESTIONABLE.

## 4. WNBA copy (`syndicate/features/wnba/source_cli/scrapers/injuries.py`): same code, NOT edited

- `_parse_pdf_rows`, `STATUS_TOKS`, `looks_like_player_start` and the cleaner are textually identical to the NBA
  copy. The only difference is the `PdfReader is None` guard.
- The WNBA copy's "official" source is the **NBA** report: the same `SEASON_PAGE_TMPL`, `official.nba.com/nba-injury-report-...`.
  - Run on the 10-21 NBA PDF, it emits **33 NBA rows** under WNBA tricodes (the city tokens match: ATL 9, DAL 6,
    IND 4, CHI 3, MIN 3, PHX 3, POR 3, TOR 2).
  - `update_injuries` then sets `official_ok`, which SKIPS the ESPN WNBA fallback.
  - `_filter_to_roster_players` drops the NBA names, so on a day with an NBA report the day's WNBA rows would be
    replaced by nothing.
- The fleet's WNBA `injuries.csv` holds 48 WNBA rows on each of 10-19..10-22, when NBA reports exist. Which path
  wrote them is NOT determined.
- Porting the name fix there changes nothing a WNBA reader sees. The real defect is the wrong league's source, which
  bites when the seasons overlap (NBA playoffs in May-June, WNBA in October). Proposed as a separate session.

## 5. Leads, not followed

- **A past date's snapshot is overwritten by the fallback.** The season page lists only today's reports. A fetch for
  D-1 after midnight therefore finds no official PDF, falls back to Rotowire/ESPN, and REPLACES D-1's rows.
  - The fleet's 10-21 rows now read `injury = "Out"` (fallback-shaped): Moody OUT, no Curry.
  - So `injuries.csv` is not a record of the report the sim was built on.
  - Past reports stay fetchable by URL: 10-19..10-21 still are. 10-10..10-18 return 403; whether that is retention
    or no preseason reports is not determined. A D-1 fetch could try `Injury-Report_<D>_11_30PM.pdf` directly.
- A Chinese-order name ("Yang, Hansen" -> "Hansen Yang" vs roster "Yang Hansen") would not match. None was seen in
  this corpus.

## 6. Not done (needs the user's yes)

- Nothing is on the fleet. The fleet runs the old parser: `5e734fb6`, ff'd 10-22 by another session, does not carry
  this fix. Once this is on `main`, ANY later fleet ff to a newer SHA carries it along, so the ff-ing session's
  ride-along check should name it. Getting the fix there takes a fleet ff, with no
  restart: `fetch-injuries` is a subprocess per refresh. Then:
  - read the next `raw/injuries.csv` snapshot for 0 off-roster names;
  - read the next props refresh's `SMART_SIM_REUSE_STALE_EXCLUSIONS` for the repaired keys.
- The 10-21 minutes effect is in `#723`'s numbers: `injury_listed_unmatched` 99.4 min, plus the swaps. Re-attributing
  them is `#723`'s confirmatory reading, not this lane's.
