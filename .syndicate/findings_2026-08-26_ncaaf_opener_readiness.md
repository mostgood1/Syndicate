# NCAAF opener readiness — measured 2026-08-26, 3 days before the 08-29 openers

> Started as a read-only evaluation; the user then asked for two of its
> recommendations to be acted on, so §1 and §2 now have a lane
> (`ncaaf-opener-regions-props`), a commit (`9be130e0`) and an env change
> behind them. See "USER DECISIONS" below — they narrow §1 and retire §4.
> Every number in the ANALYSIS sections is from **production** (`syndicate-an21.onrender.com`) or
> from a **live upstream API call**, taken 2026-08-26 ~22:2x–23:0xZ. Local
> checkout is used only to explain *why* production reads the way it does.

## Headline

| question asked | answer | evidence |
|---|---|---|
| are we getting odds? | **YES, and they are current** | 51/51 games priced; mean \|board − live consensus\| = **0.102** pts spread, **0.076** total |
| ...from the right books? | **NO** | 0 of 5 sharps/exchanges present; 6 of 11 bettable books |
| player props available? | **YES upstream, ZERO in product** | 6 of 6 probed openers have real props; production serves `shared_prop_rows: []` on all 51 |
| do teams have rosters? | **NO** | `0 active roster entries` on 51/51 cards, both teams |

---

## 1. Odds — working, live, but soft-book only

`GET /ncaaf/api/cards?week=1` → **51 games**, `board_row_counts.source =
smartsim2_standalone`, `dropped: 0`, `truncated: false`.

- **51/51 carry a market spread, total and moneyline.** 51/51 carry a non-null
  model (`home_mean`/`away_mean`/`margin_mean`) — `#458` is closed in practice:
  `CFBD_API_KEY` is now set on refresh-worker (len 64), and the board serves 51
  games rather than the 16 recorded in `todo.md #458`.
- **Freshness measured, not assumed.** Fetched the served board and a live
  OddsAPI `us` consensus in the same script run and differenced them over the
  46 matchable games:

      spread |board - live| : mean 0.102  max 1.277  exact(<=0.01) 20/46
      total  |board - live| : mean 0.076  max 1.682  exact(<=0.01) 26/46

  That is minute-scale line movement, not staleness. **The NCAAF odds path is
  genuinely refreshing.**

- **The book set is the problem.** `/api/board/book-grid?sport=ncaaf&date=2026-08-29`
  → 41 rows, 11 distinct books:

      betmgm betonlineag betrivers betus bovada draftkings
      fanatics fanduel lowvig mybookieag williamhill_us

  Against `book_shortlist.DEFAULT_BOOKS` (the books the operator can actually
  bet): **6 of 11 present** (draftkings, fanduel, betmgm, williamhill_us,
  betrivers, fanatics). **Absent: pinnacle, novig, prophetx, kalshi,
  polymarket** — every sharp and every exchange. Five of the eleven that ARE
  present (betonlineag, betus, bovada, lowvig, mybookieag) are not bettable, so
  the "11 books" tile overstates the actionable count by nearly half.

- **Cause is the region set.** `SYNDICATE_LIVE_ODDS_REFRESH_REGIONS = us` on all
  three services. Measured live, same instant, `americanfootball_ncaaf`:

  | region | events with books | books returned | credits |
  |---|---|---|---|
  | `us` | 111 | the 11 above | 3 |
  | `us2` | 110 | hardrockbet, ballybet, betparx, espnbet, rebet, fliff | 3 |
  | `us_ex` | **51** | **novig (51), prophetx (8), betopenly (6)** | 3 |
  | `eu` | 111 | **pinnacle (45)**, matchbook, betfair_ex_eu, coolbet, +9 | 3 |
  | `uk` | 110 | virginbet, grosvenor, casumo, betfair_ex_uk, +7 | 3 |

  `SYNDICATE_LIVE_ODDS_GAME_LINE_REGIONS = eu,us_ex` already exists as a knob;
  it is not reaching the NCAAF capture. **Credits are not the constraint** —
  quota read `x-requests-remaining: 4,853,063` during the probe.

- **Slate shape, worth saying out loud:** board "Week 1" is 51 games spanning
  **08-29 → 09-07**. Only **7 kick off Saturday 08-29** (+1 at 08-30T00:00Z =
  Saturday night CT). This matches OddsAPI's own event list exactly (7 + 1).
  A user opening the board on Saturday sees 51 cards for an 8-game day; kickoff
  is present at `ncaaf_card.scoreboard.kickoff` but `shared_game_state.startTime`
  is `null` on all 51, so the shared board contract cannot sort or filter by it.

## 2a. PROPS WERE WIRED TO A DEAD RUNNER — corrected 2026-08-27

The capture built in §2 was attached to `refresh_ncaaf_oddsapi.py`, by analogy
with NFL, whose props hang off NFL's odds runner. **That runner cannot execute
for 2026 and never will.**

`_resolve_data_root` requires a
`college_football_schedule_<season>_predicted_totals_enhanced*.csv`. Git holds
**359 of them and every single one is season 2025** — zero for 2026. Even were
one found, `_should_skip_auto_refresh` returns True the moment
`prediction_season < current year`. So the props capture was wired to a path
that is structurally dead in exactly the season it was built for.

Measured on production 2026-08-27T01:04:55Z, both steps in ONE sweep:

    STEP_START name=ncaaf_game_lines_oddsapi  ... fetch_ncaaf_oddsapi_game_lines.py
    STEP_START name=ncaaf_lines_snapshot      ... refresh_ncaaf_oddsapi.py
    STEP_FAIL  name=ncaaf_lines_snapshot  runtime_seconds=0 return_code=1

The first is a NEW file from another lane (`#557`, `f5dd07af`) whose docstring
records that the old `cfbd_lines_*` path had "ZERO callers on any service" — it
replaced precisely the machinery this lane built on, hours earlier, and this
lane did not know. **That is the cost of not re-reading `origin/main` before
building on a sport's existing plumbing.**

### The instructive part: a legible failure is not a working step

The earlier `_resolve_data_root` fix (`d176b3e1`) was correct — the gate was
strictly narrower than its consumer, and widening it is right. It is also what
produced the error message above, naming every directory searched.

**And it moved the traceback deeper, which read as progress toward a working
capture when it was actually evidence the HOST was wrong.** A fix that makes a
step's failure legible and a fix that makes the step run are different things,
and the first can masquerade as the second for as long as nobody asks whether
the step should exist at all.

### Where it lives now

`ncaaf_player_props_oddsapi`, a sibling of the working game-lines capture in
`_build_ncaaf_steps`, independent of the legacy bundle and its data
(`28324d06`). Week-keyed — unlike the game-lines step beside it, which shards
by commence date because NCAAF weeks are not calendar windows — because
`ncaaf/props.py` reads back by `(season, week)` and a date-sharded file would
be invisible to the board. Last in the sweep, because lines are one call and
props are billed per event per market. Exactly ONE producer: the legacy
runner's invocation is removed rather than left dormant.

---

## 2. Player props — the coverage arrived; nothing consumes it

**Production serves zero.** `shared_prop_rows: []` and
`shared_prop_status_rows: []` on **all 51** cards. There is no NCAAF props
route. `syndicate/features/ncaaf/cards.py:360` states it plainly: *"No
player-prop rows: NCAAF has no props pipeline yet."*

**Upstream has them NOW.** Per-event OddsAPI probe, `regions=us`, the six
soonest openers:

| game (UTC kickoff) | books | markets returned | players |
|---|---|---|---|
| 08-29 16:00 UNC @ TCU | 6 | anytime_td 50, reception_yds 21, receptions 16, rush_yds 22 | 11 |
| 08-29 19:00 SJSU @ USC | 5 | + pass_yds, pass_tds | 10 |
| 08-29 19:30 NCST @ UVA | 6 | + pass_yds, pass_tds | 10 |
| 08-29 21:30 JVST @ NDSU | 3 | anytime_td only | 5 |
| 08-29 22:30 SAC @ EMU | 3 | anytime_td only | 4 |
| 08-29 23:00 NMSU @ FSU | 5 | anytime_td, rec_yds, receptions, rush_yds | 11 |

`us2` adds hardrockbet / espnbet / fliff carrying the **full** six-market set on
these games; `us_ex` adds prophetx on UNC@TCU.

This is exactly what `scripts/fetch_ncaaf_oddsapi_props_local.py`'s docstring
predicted: the 2026-08-05 "zero markets" reading was a **timing artifact**
(its NFL Hall-of-Fame-Game control also read zero), and coverage was expected
"~2026-08-23 to 2026-08-30". **It has arrived.**

The fetch script is built, its nine market keys are the validated ones
(`player_reception_yds` / `player_pass_interceptions`, not the two that 422'd),
and it degrades to a header-only CSV on an empty response. It is **not wired to
any worker autorun and has no consumer** — no Layer-1 inventory contribution,
no props page. Saturday's prop market will pass unrecorded unless something
runs it.

## 3. Rosters — FIXED 2026-08-27. **One claim in this section was wrong.**

> **RESOLVED.** All four context blocks now populate **102 of 102 team slots**
> on the served board, verified by running `cards._team_context` over the exact
> team names the 51 games carry — not by counting rows in a file, because the
> JOIN was what failed, not the presence of data.
>
>     roster_populated      102 / 102        coach_populated      102 / 102
>     transfer_populated    102 / 102        returning_populated  102 / 102
>
> e.g. North Carolina: `109 active roster entries`, `Bill Belichick |
> continuity 1 | tenure 3y`, `19 in / 26 out / net -7`, `3.1 starters | PPA
> 0.278 | Usage 0.316`. Shipped in `d195be63`.
>
> **THE CORRECTION, which matters more than the fix.** This section said *"a
> re-run alone will not fix roster"* and cited the builder's own report saying
> `Publishable rows: 0` for season 2026. **That was a misreading of a STALE
> REPORT dated 2026-08-01**, from a run that predated CFBD publishing 2026
> rosters, which nothing had regenerated since. Walked the pipeline against
> live CFBD before touching anything:
>
>     season 2026:  /roster -> 15,496 raw rows, 138 teams,
>                   0 missing position, 0 missing id
>                   -> 15,496 identity -> 15,496 roster rows, 0 issues
>
> The builder was never broken. **A report file is not a measurement of the
> thing it describes** — it is a measurement of the last time someone ran it.
> Rebuilt and committed: roster **15,496**, coach_continuity **138**,
> transfers **3,305**, returning_production **136**, team_registry refreshed,
> all with zero validation issues.
>
> **Two defects the rebuild exposed in the props path**, both found by re-running
> the real capture against the new data rather than by reasoning about it:
>
> 1. **An accented school name stopped matching itself.** The registry stores
>    `San José State`; the CFBD-derived board sends `San Jose State`; OddsAPI
>    sends `San José State Spartans`. The normaliser deleted the accent as
>    non-alphanumeric, so the registry form became `san jos state` while the
>    board form stayed `san jose state`. **That school's entire props panel
>    vanished with no error anywhere** — caught only because the game went from
>    4 rows to NO PROPS between two runs. Now folded via NFKD.
> 2. **The roster file accumulates seasons** (44,395 rows across 2025 and
>    2026). Indexed naively a transfer looks like a player on two teams, reads
>    as ambiguous, and gets dropped — silently deleting the players most likely
>    to be freshly quoted. Season preference added.
>
> The original diagnosis below stands and is left intact.

## 3. Rosters — dark on every card, and it is a season stamp

**Production: `0 active roster entries` on 51/51 cards, both teams.** Same
cards also read `Coach continuity unavailable` and `No transfer data` on 51/51.
`Returned production` is the only context block that renders.

**Root cause, with its own positive control.** `_team_context(team_name, season)`
(`syndicate/features/ncaaf/cards.py:1060`) filters all four snapshots on
`season == season`, and the board asks for **2026**. Season values in git `HEAD`:

| snapshot | rows in HEAD | season values | renders? |
|---|---|---|---|
| `returning_production` | 136 | **2026** | **yes** |
| `roster` | 28,899 | 2025 only | no |
| `coach_continuity` | 136 | 2025 only | no |
| `transfers` | 3,289 | 2025 only | no |

The one snapshot stamped 2026 is the one that renders. That is the control.

**The 2026 builds exist in the ledger and not in git.**
`docs/ai_context/ncaaf_data_pipeline.md` records, measured 2026-08-19: roster
**15,442** 2026 rows / 138 teams / 0 missing; coach_continuity **138**;
transfers **3,288**. Read directly out of `HEAD` blobs, **none of those rows are
committed.** Only `returning_production`'s 2026 build landed. This is the
"closed todo ≠ shipped" pattern again.

**And a re-run alone will not fix roster.**
`docs/reports/ncaaf_roster_snapshot_generation_report.md` says, for season 2026:

    Publishable rows: 0
    Was the roster snapshot generated successfully? Yes.
    How many publishable rows were produced? 0.

A green report over a zero-row result. Coach continuity (138) and transfers
(3,288) reported real counts for 2026; roster did not. Diagnose roster before
re-running it.

**Delivery caveat.** `cards.py::_processed_artifact_path` hardcodes the **repo
checkout** (`Path(__file__).parents[3] / "data" / "ncaaf_source" / ...`), while
every builder writes to `SYNDICATE_NCAAF_SOURCE_ROOT` (the mounted disk). So
these four snapshots reach the board **only via git → web deploy**. A worker
rebuild cannot reach the card. Confirmed against the hot-artifact inventory:
`/api/ops/artifacts/export?pattern=**/ncaaf*&names_only=1` on web returns
**2 files**, both `team_registry` — the four context snapshots are not
allowlisted.

## 4. Kalshi and Polymarket — **THIS SECTION'S CONCLUSION WAS WRONG. Read this first.**

> **RETRACTED 2026-08-26 ~23:5xZ.** Everything measured below about what Kalshi
> and Polymarket LIST is accurate and stands. The conclusion drawn from it —
> that a native Kalshi connector was "the largest single gain in market
> coverage available to NCAAF" and worth starting — was **wrong, because that
> connector already exists, is on `main`, and is running in production.**
>
> Observed in a live `live-odds-worker` log line, `2026-08-26T23:29:56Z`:
>
>     [live_odds_worker] KALSHI_GAME_SERIES found=170 added=165
>       by_sport={'nba': 35, 'mlb': 13, 'soccer': 31, 'wnba': 26,
>                 'nfl': 27, 'ncaaf': 27, 'ncaab': 4, 'nhl': 7}
>
> **27 NCAAF series, already being discovered.** The code: `pipeline/kalshi_discovery.py`,
> `pipeline/kalshi_odds_refresh.py`, `syndicate/features/shared/kalshi_board.py`,
> `kalshi_auth.py`, `kalshi_catalogue.py`, `scripts/probe_kalshi_polymarket_arb.py`,
> and a graded census at `docs/ai_context/kalshi_oddsapi_coverage_audit.md`.
> The user said so independently before this was found: *"We have our own
> pipeline to Kalshi and Polymarket."*
>
> **HOW THE ERROR WAS MADE, recorded because the mechanism will recur.** A
> repo-wide grep for `kalshi|polymarket` reported "Found 34 files" and only the
> first page was read — dominated by `.syndicate/` ledger files and
> `reports/*.json`. From the two CODE hits visible on that page
> (`book_shortlist.py`, `clv_join.py`) it was concluded that the two venues
> were merely bookmaker KEYS arriving through OddsAPI. **A truncated result set
> was treated as a survey.** Page to the end, or scope the grep to `*.py` and
> read the code hits, before reporting that a capability is absent.
>
> **What survives:** OddsAPI genuinely does not carry kalshi/polymarket for
> NCAAF (`us_ex` returns only novig/prophetx/betopenly, against an MLB control
> the same minute returning kalshi 19/19 and polymarket 19/19). That remains
> true and remains the reason not to widen regions to chase them. It is simply
> not a gap, because the native pipeline covers it.
>
> **Recommendation 4 below is RETIRED. Do not act on it.**

## 4. Kalshi and Polymarket

**OddsAPI does not carry either for NCAAF.** Proven with a same-instant control
rather than inferred: `baseball_mlb` + `us_ex` returns **kalshi 19/19 events,
polymarket 19/19**; `americanfootball_ncaaf` + `us_ex` returns only
novig/prophetx/betopenly. The region is right; the sport coverage is not there.

**Kalshi's native API has deep NCAAF, unauthenticated.**
`api.elections.kalshi.com/trade-api/v2`:

| series | open markets | two-sided quotes |
|---|---|---|
| `KXNCAAFGAME` (moneyline) | 678 | 678 |
| `KXNCAAFSPREAD` (alt-spread ladder) | 2,026 | 2,026 |
| `KXNCAAFTOTAL` (alt-total ladder) | 1,482 | 1,482 |

Opening-Saturday tickers (`26AUG29`/`26AUG30`):

| series | markets | median bid-ask | ≤0.02 | ≤0.05 | with volume | total volume |
|---|---|---|---|---|---|---|
| GAME | 94 | **0.020** | 44.7% | 73.4% | 81/94 | 1,821,805 |
| SPREAD | 929 | 0.390 | 14.0% | 24.0% | 225/929 | 346,059 |
| TOTAL | 646 | 0.250 | 10.2% | 23.7% | 102/646 | 144,617 |

So: **moneylines are a real, tight, independent price; the ladders are quoted
but mostly thin.** Do not describe the 4,186 quoted markets as 4,186 tradeable
ones.

Every FBS opener is listed and tight:

    KXNCAAFGAME-26AUG29UNCTCU     UNC 0.25/0.26   |  TCU 0.74/0.75
    KXNCAAFGAME-26AUG29NCSTUVA    NCST 0.35/0.36  |  UVA 0.64/0.65
    KXNCAAFGAME-26AUG29SJSUUSC    SJSU 0.00/0.01  |  USC 0.98/0.99
    KXNCAAFGAME-26AUG29NMSUFSU    NMSU 0.02/0.03  |  FSU 0.97/0.98
    KXNCAAFGAME-26AUG29JVSTNDSU   JVST 0.70/0.71  |  NDSU 0.29/0.30
    KXNCAAFGAME-26AUG29SACEMU     SAC 0.23/0.24   |  EMU 0.77/0.78

Note for the marquee opener: the board's model says **TCU 0.800** home win;
Kalshi's mid is **0.745**. A 5.5-point gap on the first game of the season,
against a 1-cent market.

Other NCAAF series Kalshi lists that we have no equivalent for at all:
`KXNCAAF1HWINNER`, `KXNCAAF1Q`, `KXNCAAF2Q`, `KXNCAAF3QSPREAD`,
`KXNCAAFTEAMTOTAL`, `KXNCAAFTEAMSACK`, `KXNCAAFTEAMRSHATT`,
`KXNCAAFTEAMRSHYDS`, `KXNCAAFOT`, `KXNCAAFAPRANK`, conference/award futures.

> **A correction recorded because it nearly became a finding.** A first pass
> reported "0 quoted" across all Kalshi NCAAF markets. That was a field-name
> error — Kalshi returns `yes_bid_dollars` / `yes_ask_dollars` / `volume_fp` /
> `open_interest_fp`, not `yes_bid` / `volume`. What caught it was the **MLB
> positive control reading 0 as well**, on a sport OddsAPI shows Kalshi quoting
> 19/19 the same minute. Absence of a signal was a fact about the reader.

**Polymarket has no per-game NCAAF markets.** `gamma-api.polymarket.com`:
`tag_slug=college-football` → **2 events**; `tag_slug=ncaaf` / `cfb` → season
futures only — 2026 national champion (vol 124,440), Heisman (1,071), conference
winners (20–377). Nothing to lean on for Saturday's games.
(`slug_contains=cfb` is not an honoured filter — it returns unrelated events.
Do not use it.)

---

## USER DECISIONS, 2026-08-26 — these SUPERSEDE the recommendations below

Recorded here because §4 above spends a lot of words arguing for something the
user had already solved, and a later session reading only the analysis would
redo it.

1. **`ODDS_API_REGIONS = us,us2`. NOT `us_ex`, NOT `eu`.** `[user]` "we only
   need US odds" then "stick to us and us2". So the region widening ships, but
   narrower than §1 proposed: no Pinnacle (that was `eu`), and no
   novig/prophetx (those are `us_ex`). SET on refresh-worker 2026-08-26 ~23:0xZ
   via the single-key endpoint; **live-odds-worker NOT SET — the call was
   refused by this session's permission classifier and is owed.**
   `ODDS_API_REGIONS` is read by `scripts/refresh_ncaaf_oddsapi.py` and nothing
   else (grepped), so it is NCAAF-scoped and cannot touch another sport.

2. **DO NOT BUILD A KALSHI OR POLYMARKET CONNECTOR.** `[user]` "We have our own
   pipeline to Kalshi and Polymarket." That retires recommendation 4 below
   entirely. The §4 measurements stay on the record as a description of what
   those venues carry for NCAAF — they are no longer an argument for building
   anything here.

3. **`us2` books are not in the bettable list.** It adds espnbet, hardrockbet,
   ballybet, betparx, rebet, fliff. None are in
   `book_shortlist.DEFAULT_BOOKS`, so they will be captured and then filtered
   out of anything actionable until that list is updated. Flagged to the user,
   not acted on — `book_shortlist.py` is a separate change and was not claimed
   by this lane.

### A CLAIM DOES NOT RESERVE A SERVICE AGAINST A HUMAN OPERATOR

Recorded because this session very nearly wrote the OPPOSITE into `deploys.md`,
and the wrong version would have taught the wrong lesson.

The user deployed refresh-worker and live-odds-worker to `23f065d4` from their
own terminal at **23:26:02Z / 23:26:11Z**, while lane
`ncaaf-opener-regions-props` held claims on both.

**Those claims were LIVE, not expired.** Acquired **22:57:41Z**, TTL **2700s**,
so they expired **23:42:41Z** — the deploys landed **16.6 minutes inside** the
window. This session first reported the claims as already expired and blamed
`deploy_claim.py status` for displaying them as HELD. That was arithmetic
error; the display was correct. Caught by `syndicate-27` before it reached the
ledger.

**The real finding: `.claude/hooks/deploy-guard.py` only intercepts an
ASSISTANT's Bash calls.** A deploy run by a person in their own terminal never
passes through the hook, so it never consults the claim. The claim serialises
sessions against each other and cannot reserve a service against a human.

**No harm done, and that is not the same as no hazard.** `23f065d4` was
strictly forward of everything live, so the bypass cost nothing. The hazard is
structural: anyone who believes a held claim reserves a service is wrong in
exactly the case where a rollback would be silent.

### What shipped

`9be130e0` on `origin/main` (lane `ncaaf-opener-regions-props`) — NCAAF prop
capture wired into `refresh_ncaaf_oddsapi.py`, plus the prop parser keeping
every bookmaker instead of one (60 -> 329 rows on the real wk1 openers, same
call, same credits; 74 of 130 selections quoted by >1 book). **NOT YET
DEPLOYED** — both workers returned `HOLD` on preflight (refresh-worker had
`run_mlb_daily_sim_job.py` in flight, live-odds-worker had
`refresh_odds_sources.py`), and a deploy kills those.

Also owed, deliberately out of lane: the `HOT_ARTIFACT_PATTERNS` entry for
`*_source/data/oddsapi_player_props_*.csv`. `artifact_publisher.py` is claimed
by OPEN lane `nfl-fantasy-projections`. Without it the props CSV lands on the
worker disk and in the shared quote log, but does not reach web.

---

## What is worth doing before Saturday, in order

1. **Add `us_ex` and `eu` to the NCAAF odds capture.** Buys Novig + ProphetX
   (bettable, currently absent) and **Pinnacle** (the de-vig reference the CLV
   program depends on). Existing knob, existing region strings, ~3 credits per
   region-call against 4.85M remaining.
2. **Run `fetch_ncaaf_oddsapi_props_local.py` for wk1 and give it a home.**
   The market is live now and will be gone after Saturday. Capture-only still
   has value; the join can follow.
3. **Rebuild + commit `coach_continuity` and `transfers` for 2026** (they
   reported real 2026 counts), and **diagnose the roster builder's
   "0 publishable rows"** before re-running it. Remember these reach the board
   only through git + a web deploy.
4. ~~**Kalshi native connector**~~ — **RETIRED, it already exists.** See the
   retraction at the head of §4: `pipeline/kalshi_discovery.py` is on `main`
   and discovering **27 NCAAF series** in production. Nothing to build.
5. **Polymarket** — nothing actionable for game lines. Revisit if they list
   per-game CFB.

## Probes used (kept in the session scratchpad, reproducible)

- `oddsapi_ncaaf_probe.py` — events, bulk lines, per-event props
- `oddsapi_regions_probe.py` — region × book matrix, lines and props
- `pred_markets_probe.py` / `pred_markets_detail.py` — Kalshi + Polymarket inventory
- `kalshi_control.py` / `kalshi_quotes.py` — the field-name correction and its control
- `kalshi_tightness.py` — bid-ask width distribution on opening Saturday
- `freshness.py` — served board vs live consensus, same run
