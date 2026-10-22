# NBA injury feed: past dates lose their official snapshot, and light slates never read their own report — findings 2026-10-22

Lane `nba-injury-snapshot-overwrite`, session 6c89053f (side session of local_4ebfbce7). Todo `#730`. Follow-up of
`#725` lead 5 (`findings_2026-10-22_nba_injury_pdf_parser.md` §5). Times are US Central unless marked ET or Z.

**Substrates.**
- **Fleet, read-only:** `~/syndicate-prod/data/nba_source/data/raw/injuries.csv` copied 11:47 AM CT (mtime
  11:30:45 AM CT, 2,184 rows). Props-refresh logs `nba_source/logs/syndicate_refresh_oddsapi_props_2026-10-2{0..3}.log`
  and `smart_sim_2026-10-2{0,1,2}_*.json`, read 11:40–11:55 AM CT. Nothing on the fleet was changed.
- **Official PDFs:** the 167 reports lane `nba-injury-pdf-parser` fetched from `ak-static.cms.nba.com` (10-22
  ~10:25 AM CT). Parsed with main's fixed parser (`36eb357b`) against the fleet's `rosters_2026-27.csv`.
- **Code:** `origin/main`. A local run is evidence about the code, not about the fleet.

## 1. Who writes a date's rows, and from what

| writer | date asked for | when |
|---|---|---|
| live loop `_should_force_sim_rerun` -> `_fetch_injuries` (`live_refresh_loop.py:882-893`, `:657-674`) | `central_today_iso()` (`:6014`) | every lineup check: 1,800 s default (`:619-625`), every tick within 30 min of a tip |
| props refresh `_ensure_source_game_inputs` (`refresh_nba_oddsapi_props.py:2596-2605`) | the slate date | only while that slate's game predictions are missing, so **once per slate**, 1–2 days ahead: 10-20 at 10-19 1:01 AM; 10-21 at 10-19 3:04 AM; 10-22 at 10-20 9:31 AM; 10-23 at 10-21 6:04 AM |

`NBAInjuryDatabase.update_injuries` (`syndicate/features/nba/source_cli/scrapers/injuries.py`) takes the official
report from the season page (`_latest_pdf_url_for_date`). That page lists only TODAY's (ET) reports. If it finds
none, it scrapes Rotowire + ESPN. **Both scrapers stamp each row `datetime.now()`** (the fleet's clock is
Central), and `update_injuries` keeps that date.

There are two mechanisms:

- **(a) Nightly overwrite.** From midnight ET (11 PM CT) to midnight CT, the live loop still asks for its Central
  date D. The page lists no D reports, so the fallback rows, stamped D, REPLACE D's rows wholesale.
  - Bounded on 10-21 from the props-refresh lines: at **8:35 PM** `PROPS_OUT_PLAYER_REFUSED ... snapshot=2026-10-21
    out_on_feed=74`, the official shape, with the Curry/Moody swap. At **11:04 PM**, `out_on_feed=65`, which is
    exactly the fallback rows' 65 OUT.
- **(b) Lookahead merge.** A fetch for a future date finds no report. It deletes that date's rows (there are
  none), and MERGES the scrape (stamped today) into TODAY's snapshot with dedupe keep-last. So today's snapshot
  mixes official and fallback rows until the next live-loop fetch.
  - It never writes the future date itself. The fleet has **no 10-23 rows**, although
    `fetch-injuries --date 2026-10-23` ran 10-21 6:04 AM CT.

**Final rows per date on the fleet** (read 11:47 AM CT):

| dates | rows/day | statuses | source |
|---|---|---|---|
| 09-30 .. 10-18 | 59–139 | OUT + DAY-TO-DAY only, injury text `Out` / `Day-To-Day` | fallback (no official report is retrievable: 10-10..10-18 return 403) |
| **10-19** | 90 | OUT 35, DAY-TO-DAY 55 | **fallback** — official reports existed (48) |
| **10-20** | 81 | OUT 58, DAY-TO-DAY 23 | **fallback** — official reports existed (48) |
| **10-21** | 70 | OUT 65, DAY-TO-DAY 5 | **fallback** — official reports existed (48) |
| 10-22 (today) | 12 | OUT 9, QUESTIONABLE 3 | official (`Injury/Illness - ...`) |

**3 of 3 past dates that had official reports end as fallback rows.** So `injuries.csv` is not a record of any
official report for a past date.

## 2. The readers, and what the overwrite changed

### 2a. SmartSim exclusions (`_smart_sim_injuries_excluded_map_for_date_local`, `basketball_props_smart_sim.py`)

- **Rule:** the latest snapshot on or before D. A latest snapshot under half the previous one's rows counts as
  partial, and the previous one is used (`INJURY_SNAPSHOT_PARTIAL`).
- **What the rule meets:** the official report lists only the teams on the slate, plus late-day submissions for
  the next day. The fallback lists all 30 teams. So on a light slate the day's own report is always "partial".
  The previous snapshot is then last night's fallback, which is mechanism (a)'s output.

Builds per slate, read from the props logs. Each line is one build that read the feed.

| slate | games | builds on the Central date | INJURY_SNAPSHOT_PARTIAL | read instead |
|---|---|---|---|---|
| 10-20 | 3 | 10 | **6 of 10: every build from 8:58 AM to 4:05 PM** (latest 11–38 rows vs 90) | 10-19 fallback |
| 10-21 | 11 | 18 | 0 of 18 | (own official report used) |
| 10-22 | 2 | 2 so far (7:40, 11:40 AM) | **2 of 2** (12 vs 70) | 10-21 fallback (the overwritten rows) |

- On 10-20 the guard did not fire at 12:00 AM and 6:30 AM; which snapshot those two builds read is not determined.
- It did not fire at 6:54 PM or 11:07 PM either. By 5 PM ET the report had grown to 46 rows (next-day
  submissions), and 46 is at least half of 90.
- The commit message's "6 of 6 game-day builds" counts the 8:58 AM – 4:05 PM window only.

**Effect, excluded sets on the slate's teams** (the official report in force at each build vs the snapshot read):
- **10-20:** DET's **Taurean Prince, Isaac Jones, Ugonna Onyenso** were OUT on the 9:30 AM ET report, and
  **Elijah Harkless** was added from 11:30 AM ET. All four were absent from the 10-19 rows the PARTIAL builds read.
  - That includes the three before DET–BOS's 2:00 PM CT tip (8:58, 10:32 and 11:40 AM), the last of which was the
    last pre-tip build.
  - BOS/NYK/PHI/SAS/OKC were identical. 0 wrongly excluded.
  - Limit: the 10-20 sim files were rebuilt after tip (11:08 PM CT), so their `context.excluded_players` cannot
    confirm the pre-tip read.
  - The evidence is the PARTIAL line plus the 10-19 rows. Nothing writes 10-19 after midnight CT 10-20, except
    the whole-file re-cleaning in §4.
- **10-22:** 0 differences on CLE/DEN/OKC/PHI. Last night's fallback happened to match the 11:00 AM ET report.
  The cost here is same-day changes: any status the NBA changes today never reaches today's sims.

### 2b. Props OUT refusal, Layer 2 OUT gate, board flag (`basketball_props_availability.out_players_for_date`)

- Latest snapshot on or before D, with no partial guard. On game day these read the day's own official report:
  10-22's log has `snapshot=2026-10-22`, while the SmartSim read 10-21. **So on light slates the two readers
  disagree about the same day.**
- Only a read for D made between 11 PM and midnight CT sees the overwritten rows (10-21 11:04 PM: 65 OUT,
  0 lines refused).

### 2c. `#723`'s minutes audit, `injury_listed` (`scripts/nba_sim_minutes_audit.py:129-145`)

- It reads D's rows "as it is now", and its docstring says they are "the last report of the day". After the
  overwrite they are last night's fallback.
- **10-21:** against the official 11:30 PM ET report, the fleet rows have **0 extra OUT players and miss 11**
  across 23 teams:
  - ATL: Jalen Wilson, Keshon Gilbert, RayJ Dennis
  - IND: Braden Smith
  - MEM: Carson Cooper, Javon Small
  - MIN: Rocco Zikarsky, Zyon Pullin
  - PHX: Drew Timme
  - TOR: Malachi Smith
  - UTA: Blake Hinson
- **9 of the 11 are in the 10-21 sims' `context.props_pool`**: all but Carson Cooper and Braden Smith.
- **10-20:** 8 OUT players missed across 26 teams.
- So the audit's "unlisted deep bench" bucket (68% of DNP minutes) can hold players who WERE OUT on the final
  report.
  - When the sim's stamp carries a spliced name, the audit's splice match catches the player anyway
    (`ROCCO WAY ZIKARSKY`). The others fall through.
  - Re-attributing them is `#723`'s job. Its confirmatory reading (10-22..10-27, owed ~10-28) reads the rows as
    they stand then: fallback without this fix on the fleet, the 11:30 PM ET report with it.

### 2d. Others

- **Live-loop fingerprint** (`live_refresh_loop.py:690-708`): it hashes the whole file and forces a re-sim when the
  hash changes. The overwrite changes the hash every night at ~11 PM CT. The tip freeze stops post-tip rebuilds.
- **NBA game features** (`features_enhanced.py:236-290`): counts each team's rows over a D-3..D+1 window of stacked
  snapshots, so past dates contribute fallback vocabulary (`DAY-TO-DAY` is not counted as QUESTIONABLE). Not
  measured.
- **Grading:** no grading path reads `raw/injuries.csv`. The reader list is from a grep of `syndicate/`, `scripts/`
  and `pipeline/` on main.

## 3. The fix — `21b4bdb0`, ON MAIN, NOT ON THE FLEET

**Writer** (`update_injuries`, `NBAOfficialInjuryReportScraper`):
- Rows carry `source`: `nba_official`, `rotowire` or `espn`. Rows written before the column existed are blank, and
  blank counts as not official.
- **Fallback rows never replace a date whose rows are official.** The writer prints
  `INJURY_SNAPSHOT_KEPT_OFFICIAL` and writes nothing.
- **A fetch replaces only the dates its rows carry.** A lookahead no longer merges a scrape into today's official
  snapshot. A fetch whose rows are dated another day no longer deletes the requested day's rows.
- **A date that is over in ET gets its last report by direct URL**:
  `Injury-Report_<D>_{11_30PM,11_00PM,10_30PM,10_00PM}.pdf`, so at most 4 requests per fetch. Today and future
  dates are never probed.
- The report name is PRINTED (`INJURY_REPORT date= report= via=page|url rows=`), not stored. It changes every
  half hour, and the live loop re-sims whenever the file's bytes change. A test pins this.

**Reader** (the SmartSim guard):
- The game date's OWN official snapshot is trusted whatever its row count (`[smart_sim] INJURY_SNAPSHOT_OFFICIAL`).
- Every other case keeps the guard: a fallback snapshot, blank `source`, or an official report dated before the
  game date (a lookahead sim).
- WNBA's writer stamps no `source`, so WNBA is unchanged.

**Why the reader change is part of the fix.** With the writer fix alone, a past date's rows become its official
report, which speaks for that day's teams only. On a light slate the guard would still reject today's report, and
would then read yesterday's OFFICIAL report.
- A team on today's slate that is absent from yesterday's report would get no exclusions at all.
- Today that case is covered, by accident, by the all-team fallback.
- (10-22 itself would have been fine: 10-21's 11:30 PM ET report already listed the 10-22 teams, with identical
  sets.)

**Tests:** `tests/test_nba_injury_snapshot_writer.py`, 14 tests through `update_injuries`, `get_injuries_for_date`
and the real excluded-map function. Four behaviour mutants, each failing its own tests:
- the old replace-by-`date_str` writer with no refusal: 3 fail;
- no URL probe: 2 fail;
- the old guard: 1 fails;
- the report name stored in the file: 1 fails.

Also green: `test_sim_injury_feed_snapshot.py`, `test_nba_injury_pdf_parser.py`, 7 adjacent files (66 tests), and
`test_live_refresh_loop.py -k "injur or lineup or fingerprint"` (33 tests).

**What this does NOT do.**
- It keeps a date's LAST official report (11:30 PM ET), not the report a pre-tip build read. The build's own read
  is the sim file's `context.excluded_players`. A per-fetch history would be a new artifact; none was added.

**Expected on the fleet after an ff (no restart: `fetch-injuries` is a subprocess per call):**
1. The first write adds the `source` column. The file's bytes change once, so expect one forced NBA re-sim.
2. **Reading 1:** after midnight CT, the previous day's rows carry `source=nba_official` and official statuses
   (QUESTIONABLE/PROBABLE present, no DAY-TO-DAY).
3. **Reading 2:** on the next light slate, the props log prints `INJURY_SNAPSHOT_OFFICIAL` and no
   `INJURY_SNAPSHOT_PARTIAL` for the game date's builds.
4. Cost: at most 4 extra GETs per fetch for a past date with no reports, only between 11 PM and midnight CT.

## 4. Leads, not followed

- **NOT YET SUBMITTED teams.** The parser drops them. An official snapshot can therefore lack a team that has not
  submitted yet, and that team then gets no exclusions on the old path and the new one alike. Unmeasured.
- **Past snapshots are not immutable.** Every write re-runs `_clean_injury_player_names` and
  `_apply_roster_team_corrections` over ALL dates, with today's roster. This moves teams and drops "noisy" names in
  old rows: 10-19's rows list Tobias Harris under SAS. Pre-existing; not changed here.
- **The props refresh fetches injuries once per slate**, so a D+1/D+2 sim built early reads today's snapshot.
- **WNBA writer:** the same code, in a separate copy, and NOT edited. Its "official" source is the NBA's report
  (`#725` proposed a session).

## 5. Not done (needs the user's yes)

- **The fleet ff.** `21b4bdb0` is on main only. Any later fleet ff to a newer SHA carries it, so the ff-ing
  session's ride-along check should name it, with the four effects in §3.
