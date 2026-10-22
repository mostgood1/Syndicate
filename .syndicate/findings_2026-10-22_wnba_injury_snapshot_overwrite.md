# WNBA injury feed: a late fetch deleted a date's snapshot, a prefetch merged into today's — findings 2026-10-22

Lane `wnba-injury-snapshot-overwrite`, session f4ebcf5f (side session of local_154af8e3). Todo `#733`. The lead is
`#731` §6 (`findings_2026-10-22_wnba_injury_nba_report.md`). The NBA writer's copy of the same defect is `#730`
(`findings_2026-10-22_nba_injury_snapshot_overwrite.md`, fix `21b4bdb0`). Times are US Central unless marked Z.

**Substrates.**
- **Code:** `origin/main`. The fix and its tests are a LOCAL RUN: evidence about the code, not about the fleet.
- **Fleet, read-only, 2:37–2:40 PM CT:**
  - `~/syndicate-prod/data/wnba_source/data/raw/injuries.csv`: per-date row counts and the 10-22 rows;
  - the WNBA props-refresh logs `syndicate_refresh_oddsapi_props_2026-10-2{2,3,4}.log`;
  - `git log` of `/home/amyn/Syndicate`.
  - Nothing on the fleet was changed.
- **Not re-measured:** the missing 10-12 and the 10-21 flapping. Both are `#731`'s fleet readings (§2, §6 there).

## 1. The defect, re-derived for the WNBA copy

`NBAInjuryDatabase.update_injuries` (`syndicate/features/wnba/source_cli/scrapers/injuries.py`) is the only writer
of the WNBA `raw/injuries.csv`. Two callers run it as `cli fetch-injuries --date D`:
- the WNBA props refresh (`refresh_wnba_oddsapi_props.py:3989`), for each slate it refreshes, today's and up to
  two days ahead, hourly;
- `live_refresh_loop._fetch_injuries` (`live_refresh_loop.py:657`), for `central_today_iso()`.

Before the fix, two facts combined:
- **every fetch deleted `--date`'s rows** (`existing[date != date_str]`);
- **ESPN dated each row `datetime.now()`**, and `update_injuries` kept that date. Since `#731` (`066c2158`), ESPN is
  the only source, so every row the writer gets carries the scrape's day.

That gives two mechanisms:
- **(a) Late fetch.** A fetch for D that runs after midnight deletes D's rows and writes the scrape as D+1's. D is
  left with nothing. The fleet file has no 10-12; the last 10-12 fetch ran 10-13 12:00:03 AM CT (`#731` §6). A
  reader for 10-12 now reads 10-11's snapshot.
- **(b) Prefetch merge.** A fetch for D+1 or D+2 on D deletes the future date's rows (there are none) and MERGES its
  scrape into D's (dedupe keep-last by team/player/date). A player who has left ESPN's page keeps D's old row, so
  D stays a union of the day's scrapes until a same-day fetch replaces it.
  - With `#731`'s NBA rows in the file, this is what flipped the 10-21 snapshot: the NBA path wrote D, and each
    prefetch merged ESPN's rows back in. 13 WNBA sim rebuilds (`#731` §2).
  - With ESPN only, (b) still lists returned players for D, which is the permissive-in-reverse failure (an
    available player stays excluded).

## 2. The rule, and what was NOT ported from `#730`

**The rule (same as `#730`'s):** a date's rows are ONE snapshot, and a fetch replaces the snapshot of exactly the
dates its rows carry. `--date` names the caller's slate and the roster season. It never selects which date is
replaced.
- Late fetch for D: rows dated D+1 replace D+1 only; D is kept.
- Prefetch for D+1 on D: rows dated D replace D (the new scrape, not a union); D+1 is not created and not touched.

**The row date, decided here.** ESPN's page describes NOW, so its rows carry the day of the scrape. Two
refinements, both because the rule above now trusts the row date to pick what is replaced:
- **Once per scrape.** The parser stamped each row with its own `now()`. A scrape parsed across midnight would
  split into D and D+1. Under the new rule it would replace D with only the rows parsed before midnight.
- **The Central calendar,** explicitly (`ZoneInfo("America/Chicago")`), not the process clock. The live loop asks
  with `central_today_iso()`, and Syndicate's slate day is Central. The fleet's clock happens to be CDT, so the fleet
  sees no change. A UTC process would have dated every scrape after 7 PM CDT to tomorrow, so the evening's scrapes,
  during the games, would never reach a reader for today.
- A row with no date (none today: ESPN always stamps) gets the scrape day, not `--date`. A prefetch must not
  create a future date's snapshot from today's page.

**Not ported from `#730`.**
- *Official rows are never replaced by fallback rows.* That rule protects a better source from a worse one for the
  same date. Since `#731` the WNBA writer has one source, so every write of a date is the same kind of row, and
  the latest scrape of a day is that day's best.
- *The `source` column.* No reader would use it. The SmartSim's own-report trust requires `nba_official`
  (`basketball_props_smart_sim.py:4969`), so `espn` would read exactly as no column does. And adding it changes
  every row's bytes on the first write. That changes the live loop's whole-file and per-game fingerprints, and
  so it forces a re-sim of every WNBA game, for nothing.
- *Direct-URL fetch of a past date's report.* ESPN has no per-date archive. A past date's snapshot is whatever
  was last scraped on that day.

**Observability.** Each write prints `INJURY_SNAPSHOT requested=<D> replaced=<dates> rows=<n>`. The props-refresh
log keeps it, while the live loop discards its subprocess output.

## 3. The readers (all on `origin/main`; none needs a change)

Every reader takes the latest snapshot on or before its date. So what the fix changes is which rows a date
HOLDS, not how anything reads them.

| reader | file:line | rule | effect of the fix |
|---|---|---|---|
| props OUT refusal / Layer 2 / board | `basketball_props_availability.py:90` (`out_players_for_date`; snapshot pick `:115`) | latest snapshot <= D; >7 days old counts only season-ending rows; **no partial guard** | a late fetch no longer moves a reader for D back to D-1; a prefetch no longer leaves returned players listed (refused) for D |
| WNBA recency rule, injury-explained returns | `wnba_sim_availability.py:197` (`_injury_snapshots`), `:215` (`_snapshot_on_or_before`, partial guard at `:220`), `:225` (`injury_explained_returns`) | a player re-admits only if every missed game's snapshot listed them OUT and the slate's latest does not | missed-game dates keep their own snapshot. Before: a deleted date read the day before (10-12 -> 10-11), so a player OUT only from D could not be "explained" for D. The slate's own snapshot is the latest scrape, not a union |
| SmartSim excluded map | `basketball_props_smart_sim.py:4943` (raw feed), partial guard `:4984` | latest snapshot <= the game date; under half the previous snapshot -> previous | same as above. WNBA rows carry no `source`, so the `#730` own-report branch never fires for WNBA |
| WNBA league status | `wnba/source_cli/league_status.py:239` (`_load_injuries_latest_upto`), partial guard `:261` | as the SmartSim | same |
| game-level injury features | `wnba/source_cli/features_enhanced.py:301` (`add_injury_features`), window `:353` | **sums every row** for the team over D-3..D+1 | counts scale with how many snapshots the window holds: a deleted date lowered them, a merged union raised them. The fix makes every fetched date present, so counts follow the number of fetched days. Pre-existing (a player OUT all week counts up to 5 times). Whether the game model's `feature_columns_enhanced.joblib` includes these columns was not read |
| live-loop re-sim trigger | `live_refresh_loop.py:692` (whole-file hash), `:745` (per-game rows hash) | any byte change forces a re-sim | no format change, so the ff itself forces nothing. A prefetch and a same-day fetch of an unchanged page now write identical bytes (test) |

## 4. The fix and the tests — main `ae2cb646`, NOT on the fleet

- `injuries.py`: `_scrape_day()` (`:33`), one stamp per scrape (`:315`), the replace rule (`:502-510`).
- `tests/test_wnba_injury_snapshot_writer.py`, 8 tests. All go through the real `update_injuries` and the real ESPN
  parser. Only the network (`requests.Session.get`) and the clock are stubbed, as in `#731`'s tests, so they also
  run against the old file.
  - **Late fetch for D** (10-13 12:00:03 AM CT): D's rows kept, D+1 written. Also through the readers
    (`out_players_for_date` -> snapshot 10-12, `_snapshot_on_or_before` -> 10-12) and through the CLI both fleet
    writers run.
  - **Prefetch for D+1 on D:** D replaced by the scrape, so a returned player drops off; no D+1 rows; D-1
    untouched.
  - **Midnight straddle:** one scrape, one date.
  - **UTC process:** dated on the Central calendar.
  - Guards: a same-day fetch replaces the day; a prefetch and a same-day fetch of the same page write the same
    bytes.
- **Reachability: on `origin/main`'s file (`git restore --source=origin/main`), 6 fail and the 2 guards pass.**
  The failures are the behaviours themselves:
  - D emptied (`set() == {...}`);
  - the reader at `2026-10-11`;
  - Nye still listed for 10-21;
  - the scrape split at midnight;
  - the scrape dated 10-22 by a UTC clock.
- **Three behaviour mutants of the fix each fail their own tests:**
  - per-row stamp: the straddle test fails;
  - process clock: the UTC test fails;
  - the old replace-by-`date_str` rule: 4 tests fail.
- Also green: `test_wnba_injury_nba_report.py`, `test_wnba_sim_availability.py`,
  `test_wnba_league_status_roster.py`, `test_sim_injury_feed_snapshot.py`, `test_lineup_injuries_native.py`,
  `test_smart_sim_reuse_exclusions.py`, `test_basketball_injury_exclusion_reinclusion.py`,
  `test_fit_wnba_sim_availability.py`, `test_nba_injury_snapshot_writer.py`,
  `test_basketball_props_out_player_refusal.py`, `test_board_out_player_props.py`.

## 5. Fleet reading, 2026-10-22 2:37–2:40 PM CT (read-only) — for `#731`, not this lane's defect

- The fleet runs `21b4bdb0`, which does **not** carry `066c2158` (`#731`).
- At 2:37 PM CT, the props refresh's fetch for 10-22 took the NBA official path: no Rotowire line in the log.
  - The WNBA 10-22 snapshot is now **2 NBA rows, both TOR, with spliced names**: `Nate Raptors Bittle`,
    `Malachi Fracture Smith` (the WNBA copy never got `#725`'s parser fix).
  - **46 ESPN rows for 10-22 were deleted.** The file went from 1,027 to 981 rows.
  - The other 20 dates hold 48–51 rows each, 10-01..10-21, with no 10-12.
- **The last 10-24 build had not read it.** At 4:08 AM CT it logged `PROPS_OUT_PLAYER_REFUSED ... snapshot=2026-10-22
  out_on_feed=48 lines_refused=0`, which is the ESPN snapshot.
  - Any 10-24 build from now reads 10-22 as its latest snapshot.
  - The props refusal has no partial guard, so it would read the 2 TOR rows.
  - The SmartSim, `wnba_sim_availability` and `league_status` would fall back to 10-21, since 2 is under half of 48.
- **So `#731`'s exposure for the 10-24 ATL v GSV game is open now**, not only from 10-23 11 PM CT. Its own
  estimate assumed the 10-24 snapshot; the lookahead build reads today's.
  - Measured cost so far: 0 lines. Even the correct snapshot refused 0, because the OUT players have no lines.
- This lane's fix is independent of `#731`'s. But an ff to `ae2cb646` or later carries both.

## 6. Not done, and leads

- **Fleet ff: the user's yes.** No restart is needed: `fetch-injuries` is a subprocess per call, for both writers.
  - Verify a late fetch: its props-log line `INJURY_SNAPSHOT requested=D replaced=D+1`, and D's rows still present
    the next morning.
  - Verify a prefetch: it prints `replaced=<today>`, and no future date appears in the file.
- **Not recoverable: 10-12's rows.** The CLI prints only per-team status counts.
- **Leads, not followed:**
  - `add_injury_features` sums stacked snapshots (§3). Whether the WNBA game model reads those columns is still
    unmeasured.
  - Every write re-cleans ALL dates with the roster of `--date`'s season (the `#730` lead). It is a no-op on the
    fleet, which has no WNBA `rosters_*.csv`.
