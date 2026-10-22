# The WNBA injury fetch took the NBA's official injury report — findings 2026-10-22

Lane `wnba-injury-nba-report`, session 898e35dc (side session of local_4ebfbce7). Follow-up to `#725`
(`findings_2026-10-22_nba_injury_pdf_parser.md` §4). Todo `#731`. Times are US Central (the fleet clock is CDT).

**Substrates.**
- The fleet's own files, read-only, ~11:00 AM–12:10 PM CT:
  - `wnba_source/logs/syndicate_refresh_oddsapi_props_<D>.log` (25 logs, 09-30..10-24);
  - `wnba_source/data/raw/injuries.csv`;
  - `wnba_source/data/processed/` (the boxscores and the `smart_sim_*` files);
  - the git reflog of `/home/amyn/Syndicate`.
- For May–July: the 6 mirrored WNBA props logs plus 3 `logs/*wnba*` logs in the primary checkout. These are
  dev-machine runs, so they are a **checkout** substrate, and they are used here only for what they do NOT contain.
  Also git history.
- The fix and its tests are a LOCAL RUN: evidence about the code, not about the fleet.

## 1. The writer: one function, two callers, and the official path did return rows

`NBAInjuryDatabase.update_injuries` (`syndicate/features/wnba/source_cli/scrapers/injuries.py`) is the only code
that writes the WNBA `raw/injuries.csv`. A grep for `injuries.csv` over `syndicate/`, `scripts/` and `pipeline/` finds
only readers besides it. Two callers run it, both as `python -m syndicate.features.wnba.source_cli.cli fetch-injuries --date D`:

| caller | where | leaves a log? |
|---|---|---|
| the WNBA props refresh | `scripts/refresh_wnba_oddsapi_props.py:3989` | yes: `syndicate_refresh_oddsapi_props_<D>.log`, with the run's whole-file summary |
| the live loop's lineup check | `live_refresh_loop._fetch_injuries` (`live_refresh_loop.py:657`), every lineup-check interval | **no**: `capture_output=True`, nothing is printed |

**Which path each logged run took.** The fallback always prints `Headless Rotowire fetch failed: No module named
'selenium'`: Rotowire's static page parses 0 rows, and selenium is not installed. A run that saves rows WITHOUT that
line took the official path, `official_ok = True`. Over the 25 logs:
- **Every run before 10-20 took the fallback.** There are three apparent exceptions (10-14, 10-17). Their output is
  interleaved with another command's, and their summaries carry no PDF status.
- **The first official-path write is 10-20 1:07 PM CT (18:07Z), the NBA's regular-season opener.**
  - It was used on every same-day run for date 10-20 until 11:10 PM CT.
  - It was used on every run for date 10-21 from 12:09 AM CT until 10:48 PM CT: **102 logged writes** between the
    two dates (49 + 53).
- **10-22:** all 63 props-refresh runs through 11:31 AM CT took the fallback. Why today's NBA report gave no rows is
  not determined.

**The rows were WRITTEN, not filtered.** The fleet's WNBA `processed/` holds 640 entries and **no `rosters_*.csv`**.
`pick_rosters_file` returns None, so `_clean_injury_player_names`, `_apply_roster_team_corrections` and
`_filter_to_roster_players` all return their input. The NBA rows were saved under the WNBA tricodes of the shared
cities.
- The parser findings expected the day to be "replaced by nothing". That is the WITH-roster case, a dev machine.
- On production the day was **replaced by the NBA's rows**.

**The proof is in the whole-file summaries the logged runs print.** The ESPN WNBA rows are OUT / DAY-TO-DAY only,
and they carry no TOR row. That holds for every fallback summary 09-30..10-20 and for the current file (1,027 rows,
21 dates). In those summaries:

| date's rows | first NBA write | restored by the fallback | NBA rows that day | QUESTIONABLE/PROBABLE/DOUBTFUL rows in file | TOR rows |
|---|---|---|---|---|---|
| 10-20 | 1:07 PM CT (props refresh) | 11:10 PM CT | 1 -> 39 | 0 -> 19 | 1 |
| 10-21 | **by 12:05 AM CT** (unlogged: the live loop) | 11:05 PM CT | not derived | 19 -> 0 | 1 -> 2 |

- 10-21's NBA rows were already in the file at 12:05 AM CT. The 12:05 AM props-refresh run, for date 10-22, printed
  19 PDF-status rows. The 11:10 PM fallback had left 0. Only the live loop writes in between.
- **Why the window closes at midnight ET.** The season page lists only the current ET day's reports. After midnight
  ET, a fetch for D finds no PDF and falls back to ESPN, which re-wrote D. That is why today's file looks clean:
  48 WNBA rows on 10-20 and 10-21.

## 2. What it did on 10-21: a WNBA game day (ATL v GSV, boxscore on the fleet)

From the 10-21 refresh log (`SIM_AVAILABILITY`, `SMART_SIM_REUSE_*`) and the final pregame sim
`smart_sim_2026-10-21_ATL_GSV.json` (written 4:35 PM CT):

- **NBA players became WNBA ATL exclusions.** 9 of the final sim's 23 ATL exclusions are Hawks/Magic players,
  carrying the PDF splice words: `ANTHONY MAGIC BLACK`, `HENRI FRACTURE VEESAAR`, `IZAIYAH MANAGEMENT NELSON`,
  `JALEN TEAR WILSON`, `JONATHAN SPRAIN ISAAC`, `KESHON WAY GILBERT`, `MOUHAMED WAY GUEYE`, `NOAH RECOVERY PENDA`,
  `RAYJ HAWKS DENNIS`. They are inert in a WNBA pool. They are the evidence.
- **13 WNBA players read as returned from injury.** The fallback snapshot gave `readmitted_injury_return=0`; the NBA
  snapshot gave **13**.
  - `injury_explained_returns` re-admits a recency-excluded player whose latest snapshot no longer lists them OUT.
    The NBA rows list no WNBA player.
  - 5 of the 13 are on the ATL/GSV histories: Matilde Villa, Aaliyah Nye, Holly Winterburn, Iliana Rupert,
    Ndjakalenga Mwenentanda. None of them is in the 10-19 or the 10-21 boxscore.
- **Re-sim churn.** From 12:35 to 7:48 AM CT the exclusion drift flipped 13 times, and each flip rebuilt the sim
  (`stale=1 reuse=False`). Then it stayed in the NBA state, readmitted=13, through tip.
  - **The mechanism is the prefetch.** The props refresh also fetched for 10-22 / 10-23, hourly at ~:05, from 12:05
    to 7:06 AM CT. Those fetches took the fallback, since no NBA report exists for a future date.
  - ESPN stamps its rows `datetime.now()`, i.e. 10-21 (§6), so each prefetch put the WNBA rows back into the 10-21
    snapshot. The next same-day official write stripped them again.
  - 6 of the 7 "WNBA rows back" states follow a prefetch by ≤12 min. After the last one (7:06 AM CT), nothing put
    them back.
- **No minutes effect was found.** The final pregame sim does not mention the five anywhere: not in `players`, not
  in `rotation_minutes`, not excluded. They had no pool slot (no prop line). So the measured damage on 10-21 is a
  wrong exclusion list and re-sim churn, not misallocated minutes.
- **Game-level injury features, not measured.** `features_enhanced.add_injury_features` counts every row for the
  team in the window D-3..D+1. ATL's 10-21 counts therefore included the Hawks' rows. Whether the WNBA game model
  reads those columns was not measured.

## 3. The 2026 overlap (NBA playoffs mid-April–June, WNBA from May): NO damage. The window is 10-20 onward.

- **No Syndicate WNBA injury writer existed during the overlap.**
  - The live loop's WNBA `fetch-injuries` was added **2026-07-14** (`61ee0b0d`).
  - The props refresh's step was added **2026-07-17** (`ee363b8f`).
  - `git log -S fetch-injuries --before 2026-07-14` finds only the NBA daily update (`e6258caa`, `nba_betting.cli`).
- **No injury file existed either.** Every mirrored WNBA run in the window prints `No injury data found`. In
  `features_enhanced`, that line means `injuries.csv` does not exist. Where it appears: the props logs of 05-27 (3),
  06-12 (4) and 06-27 (1), and `logs/wnba_live_refresh_2026-06-05.log` plus two `refresh_wnba_2026-06-06_*` logs.
- **07-14 .. 10-19: no NBA report was reachable.**
  - From July, the WNBA fetch could only reach the 2026-27 season page.
  - The NBA publishes no official report off-season or in preseason. The parser lane found the 10-10..10-18 PDFs
    return 403.
  - The fleet logs 09-30..10-19 show no official-path write.
  - The Render-era logs 07-17..09-29 were not read. Nothing NBA-side existed to be read then.
- **Not covered:** the separate WNBA source app (mostgood1/WNBA-Betting, its own service in May–June) and its own
  injury fetch. It is outside this measurement.
- **So the exposed window is every NBA game day from 10-20 on** on which the report lists a shared-city team:
  ATL, CHI, DAL, IND, MIN, PHX, POR, TOR, WAS. GSW does not map, because `golden state` -> GSV is not in the NBA
  set. The window runs from that day's first report until midnight ET. The WNBA season is still running.

## 4. The fix (`syndicate/features/wnba/source_cli/scrapers/injuries.py`, main `066c2158`)

- `update_injuries` reads ESPN's WNBA page **only**.
- The two other sources it used are deleted, because both are the NBA's report:
  - the NBA official-PDF scraper (`official.nba.com/nba-injury-report-<season>`);
  - Rotowire's `/basketball/injury-report.php` page.
  - Both classes were reached only from `update_injuries`, and the package exports only `NBAInjuryDatabase`.
  - Rotowire contributes 0 rows on the fleet today: the Headless line shows on every fallback run. So removing it
    changes no fleet output. It was a second latent NBA source: with selenium installed it returns NBA rows.
- **Why not "gate `official_ok` on rows surviving the WNBA roster filter".** That gate would have been inert on
  production: the fleet has no WNBA roster, so every NBA row survives the filter.
- **Tests:** `tests/test_wnba_injury_nba_report.py`, 6 tests.
  - All go through the real `update_injuries`, and one goes through the CLI entrypoint both fleet writers run.
  - Only the network (`requests.Session.get`), pypdf and the clock are stubbed. The NBA stream is the real 10-21
    Atlanta Hawks block.
  - **Against `origin/main`'s file: 5 fail, 1 passes** (the guard).
    - No roster: the Hawks are written as WNBA ATL rows (the fleet's case).
    - With a roster: the day is emptied (`{}`).
    - On both days the NBA's season page is requested.
    - The no-NBA-report day writes the same ESPN rows before and after (the guard).
  - Related suites: see the lane's verification line.

## 5. Not done (needs the user's yes)

- **The fix is not on the fleet.** The fleet was ff'd by other sessions today:
  - `5e734fb6` at 10:40 AM CT;
  - `36eb357b` (the NBA parser fix) at 11:29 AM CT;
  - `0a2986b4` at 11:37 AM CT.
  None of them carries this fix.
- **The next WNBA game is 10-24, ATL v GSV.** `smart_sim_2026-10-24_ATL_GSV.json` exists, and there are 1,381 prop
  lines.
  - It is a Saturday NBA slate, so a shared-city team is near-certain.
  - From midnight ET (10-23 11 PM CT), the 10-24 WNBA snapshot would be replaced by NBA rows until 10-24 11 PM CT.
  - **A fleet ff before 10-23 ~11 PM CT protects that game.** No restart is needed: `fetch-injuries` is a subprocess
    per call, for both writers.
- **Verify on the next NBA game day after the ff.** A WNBA `fetch-injuries` run's summary has 0 QUESTIONABLE /
  PROBABLE / DOUBTFUL / TOR rows, and `SIM_AVAILABILITY` shows `readmitted_injury_return=0`.
  - The "Headless Rotowire" line no longer appears at all, so it is not a predicate any more.
  - The pypdf `CryptographyDeprecationWarning` line also stops, because the module no longer imports pypdf.

## 6. Leads, not followed

- **WNBA: ESPN rows are stamped `datetime.now()`, not `--date`.** The NBA writer's copy of this was fixed the same day
  by `#730` (`21b4bdb0`: rows carry `source`, a fetch replaces only the dates its rows carry); the WNBA copy was not.
  `update_injuries` keeps an upstream date.
  - So a fetch for D that runs after local midnight deletes D's snapshot (`existing[date != D]`) and writes the
    next day's.
  - The fleet WNBA file has **no 10-12 snapshot**. The last 10-12 fetch ran 10-13 00:00:03 CDT.
  - A snapshot reader then falls back a day, which is the opposite of `#725`'s D-1 lead.
- **The fleet's WNBA roster-dependent cleaning has never run.** There is no `rosters_*.csv` in `processed/`, so the
  name cleaner, the team correction and the roster filter are no-ops on production.
- **`live_refresh_loop._fetch_injuries` discards its output.** Its writes can only be inferred, as §1 had to.
