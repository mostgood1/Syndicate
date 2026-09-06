# state — soccer

Split out of `state.md` by `scripts/split_state.py`. Bodies are verbatim.
The INDEX of every subject, across every part, is in `state.md`; the
one-subject-one-section rule is global and spans these files.
Same rules as state.md: when a fact changes, EDIT THE LINE.

## [soccer-prop-book-coverage] WIDENING SOCCER PROP REGIONS BUYS ONE SOFT BOOK FOR ~1M CREDITS/MONTH — **KNOB SHIPPED, DELIBERATELY LEFT OFF** `[measured 2026-09-06, lane prop-region-knob]`

Soccer player props are the platform's thinnest book coverage: **164 of 174
`oddsapi_props` rows single-book** on the served board (fanduel 135, betrivers
39), independently confirmed by lane `shortlist-prop-row-duplicates` off the
shortlist (199 rows, fanduel 193 / betrivers 39). Soccer rows OVERALL carry 12
books, so the thinness is the PROP CALL, not the `us` region.

**PROBED ON THE VENDOR RATHER THAN ARGUED.** Lecce @ Cagliari, +20h, `player_shots`:

    us            2 books   betrivers, fanduel      <- what we get today
    eu            1 book    onexbet
    us_ex         0 books   --
    us,eu,us_ex   3 books   betrivers, fanduel, onexbet   credits_this_call=3

**THE DECISION: `SYNDICATE_SOCCER_PROP_REGIONS` STAYS UNSET.** `eu` takes this
market from 2 books to 3 and the third is **onexbet, a soft book, not a sharp**.
The repo's measured **+2.79 ROI points** came from one book -> best-of-4-8;
2 -> 3 with a soft third is a much thinner version of that trade, against
**~1M credits/month** because OddsAPI bills props PER EVENT.

**`us_ex` ADDS NOTHING HERE, and that is the surprising half.** It is the region
carrying `novig` and `prophetx` — the sharps that took NCAAF game lines from 0
of 5 sharps to a real consensus — and they **do not quote soccer player shots at
all**. `pinnacle` likewise appears on soccer GAME LINES (already `eu,us_ex`) and
not on player shots. Coverage that transformed one market family says nothing
about another.

**THE BILLING MULTIPLIER IS NOW MEASURED, NOT QUOTED:** `x-requests-used` moved
**1 credit for `us` alone, 1 for `eu` alone, 3 for all three regions** — one per
region per event, exactly what `odds_regions.py` warns the prop side costs.

### THE TRAP THAT NEARLY PRODUCED A FALSE "VENDOR DOES NOT OFFER IT"

**Soccer props exist only in a window near kickoff, and BOTH ends read zero:**

    fixture +6 days      us 0 books, eu 0 books, credits_this_call=0
    game 1.6h IN PLAY    us 0 books, eu 0 books
    fixture +20h         us 2 books, eu 1 book        <- the only readable window

My first two probes picked a 6-day-out fixture and read zero on both regions —
which looks exactly like "EU does not sell this" and would have closed the
question wrongly. **A zero here measures the CALENDAR, not the region.** Same
property that made segment totals read `alternate`-only at 15:00Z and
`standard` by 16:44Z the same day. Any future probe must target a fixture
roughly 6-30h out and check `credits_this_call > 0` — a call that bills nothing
returned nothing and is not evidence.

**The knob itself is deployed and inert** (`a946a79d`, live in `11a6a829`
18:08:13Z): `prop_regions(sport, regions)` is per-sport so `eu` can be bought
for ONE sport rather than dragging NFL and NCAAF props onto the same tier, which
the single global `ODDS_API_REGION` could not express. Unset returns the base
`us`, so it spends nothing until someone takes this decision deliberately.

**If it is ever revisited:** re-probe near kickoff, and gate acceptance on lane
`prop-region-knob`'s criteria — `raw_market_agrees` stays 0, `books_quoting`
rises on keys present in BOTH before and after, using
`scripts/census_board_row_duplicates.py` with `limit=2000` (the endpoint
defaults to 200 and truncates silently).

## [soccer-market-anchor] MARKET-ANCHORING IS REACHABLE AND STILL OFF BY DECISION — MEASURED 2026-09-02 `[lane soccer-anchor-cost, main 686d8282/0844694c]`

**Weight stays 0.0. The blocker was never cost; it was two dead name joins, an
unreadable instrument, and n=10 of evidence on the wrong market.** Full
evidence: `.syndicate/findings_2026-09-02_soccer_anchor_cost.md`.

- **The 57/136 min cost figures counted priced EVENTS in a forward book to
  d+13.** `build_artifacts` is SINGLE-DATE, so the anchor never sees that list.
  Production-measured (refresh-worker `e4a471c0`, `SOCCER_UNIT_CONFIRMED`):
  **43 units, 4h interval, ~335 s spacing, unit = 27 s + 35 s/fixture, 136
  fixtures in the live 7-day horizon.** Live env: `..._SIM_HORIZON_DAYS=7` (code
  default 1), `..._WEEKLY_REFRESH_INTERVAL_SECONDS=14400`, anchor weight ABSENT.
- **BOTH NAME JOINS FIXED AND LANDED, NOT DEPLOYED.** Reach on the identical
  production basis: fixture→priced-event **66 → 122 of 136**;
  fixture→ratings-key **138 → 214 of 214**. `event_id` joins **0 of 136** — ESPN
  and OddsAPI ids never collide, so the feed has always run on the exact-name
  fallback. 11 tests, 8 fail pre-fix.
- **Fixing it made the anchor MORE expensive: 45.0 → 83.2 min per 4h interval**,
  against a build already costing 98.2 min (76% of the interval). Memory is not
  touched. 3 of 42 units already overrun their 335 s slot; 5 would.
- **CUTTING SOLVER SIMULATIONS IS FALSIFIED, do not propose it again without new
  evidence.** `D_cheap/D_anchor` on `expected_shots`: 50x5 **1.81**, 25x5 1.39,
  12x5 2.06 — the solver-budget choice moves the published projection MORE than
  anchoring does — and the shift REVERSES SIGN on 2 of 6 fixtures. The one safe
  trim is capping `max_iterations` at 5 (`100x7` costs +40% for RMSE 0.0491 vs
  0.0497).
- **The bisection is quantized to 32 lattice points** (0.01875 spacing, set by
  `shift_bound` and `max_iterations` alone). All 10 shifts in the original
  validation CSV sit on it, using 7 distinct values — precision below the
  lattice was never available and cannot be what produced the −40%.
- **THE EVIDENCE IS n=10, ONE SLATE, h2h ONLY**, and its source report calls it
  "a sensitivity check, not a tuned production default".
- **§4.4 is SMALL here, measured:** the anchor shifts the `expected_shots` LEVEL
  by **0.36%** against `shot_calibration`'s divisor whose own cross-window drift
  is ±8%. Re-fit AFTER arming, not before.
- **DEPLOYED AND VERIFIED IN PRODUCTION 2026-09-02 22:54:26Z (refresh-worker
  `99c3731f`): the audit is a FIELD in `recommendations_{date}.json`.** Read off
  a production artifact whose `generated_at` (22:59:52Z) POSTDATES the deploy:
  `state=disabled weight=0.0 fixtures=4 attached=4 priced_events=21
  by_stage={event_id:0, exact_pair:2, fuzzy:2}` on
  `eredivisie/.../recommendations_2026-09-05.json`. `fuzzy=2` independently
  confirms the same day's name-join fix live — exactly the 2 fixtures predicted
  recovered for that league-date, from a code path the prediction never touched.
  Detail: `anchor.state` takes one of five named values
  (`odds_absent`, `odds_unreadable`, `disabled`, `no_priced_fixtures`,
  `anchored`) beside attach counts, the by-stage split and
  `teams_resolved`/`teams_unresolved`. Verified end to end on three real builds
  by reading the WRITTEN artifact: `disabled` with attached=2/2 and
  `by_stage={event_id:0, exact_pair:2, fuzzy:0}` — production's actual state,
  and a working feed plus a disarmed mechanism reads differently from a missing
  feed. Path matches `HOT_ARTIFACT_PATTERNS`
  (`soccer_source/*/api/recommendations/recommendations_*.json`), so it reaches
  web. **A refresh-worker deploy is owed before any production reading.**
- **WHY THE LOG LINE COULD NEVER SERVE:**
  `ops_refresh.py:1402` launches units with `stdout=DEVNULL`, so every
  `[soccer_anchor]` line is discarded. Control: every child-process token
  returns 0 log matches (incl. `player projections`, printed on every success)
  while parent tokens return normally. The audit must become a PUBLISHED
  ARTIFACT FIELD, not a log line.
- **THE COST QUESTION IS CLOSED: the surrogate SURVIVES HELD-OUT VALIDATION
  `[2026-09-02, 89,600 sims]`.** `b_train=3.6955` frozen on
  epl/la_liga/serie_a/bundesliga, scored on 8 fixtures from
  ligue_1/eredivisie/primeira_liga/championship (3 goals-rated; targets
  0.364-0.838 vs training 0.14-0.65). Surrogate mean |err| **0.0144** vs the
  500-simulation solver's **0.0225**; slope bias **+2.9%**. Neither
  pre-registered kill condition fired, so
  `shift = (logit(target) − logit(p_base)) / b` is a LIVE cost lever taking the
  anchor from **500 simulations per fixture to 0** — `p_base` is already
  published as `win_probability.home` at `simulations: 400`.
  **DO NOT REPEAT THE "TWICE AS ACCURATE" LINE.** Held out it is 1.3x once the
  `AZ Alkmaar v Willem II` CLAMP ARTIFACT is removed (both truth and surrogate
  pinned at `+shift_bound`), the sign test is p=0.289/0.453 (NOT significant),
  and the reference's own uncertainty (0.0187) exceeds the surrogate error being
  claimed. **The defensible claim is EQUAL ACCURACY AT ZERO COST.**
- **THE EDGE QUESTION IS ANSWERED, AND THE ANSWER IS NO `[2026-09-03, 6,486
  rows / 136 matches / 56 league-date units, 8 leagues, 2026-08-07..09-01]`.**
  Anchored vs base re-simulated in ONE harness with ratings `as_of` each fixture
  date, graded on REALIZED SHOTS from ESPN — never on a book price, because
  anchoring converges to the market by construction and scoring against it
  rewards exactly that.
  **base MAE 0.52126, anchored 0.52163 -> +0.00038 shots per player-match,
  +0.072% WORSE.** Per match: worse in **95/136 (70%)**, sign test p=0.0000,
  mean delta -0.00101, sd 0.01106, **t = -1.06**, median delta **+0.0000**.
  **The DIRECTION is consistent and the MAGNITUDE is inside the noise — report
  both.** A large n makes a nothing-sized effect "significant"; 0.0004 shots is
  nothing.
  **So anchoring MOVES prop values (2.9-5.1% relative) without making them more
  accurate. Movement without accuracy is noise, not signal — the
  derivative-market edge thesis for this mechanism is RETIRED.** Weight stays
  0.0 on evidence now, not on caution. Caveats all add noise SYMMETRICALLY (24
  teams resolved to zero players; season-aggregate player rows leak into both
  arms so only the paired delta is quotable; 1..31 priced events per date).
- **WHY ARMING IT WOULD CHANGE LITTLE:** the anchor moves h2h **3.58 pp** and
  props **2.9–5.1% relative**, while the staked soccer surface is **99 board
  rows / 58 fixtures, 74% h2h, ZERO player props**. Largest effect on the market
  the audit says not to stake; smallest on markets that do not reach the board.
  The real lever remains `[soccer-board-coverage]`'s: a model view worth ranking
  on.

## [soccer-board-coverage] — MEASURED 2026-09-02, production, NOT A DEFECT

**Soccer's thin board is a DELIBERATE QUALITY FILTER working correctly.** Full
evidence: `.syndicate/findings_2026-09-02_soccer_board_coverage.md`.

- Measured on `/api/board/layer2-shortlist`, one read, all sports: soccer
  **selects 1,547 rows and 129 reach the board (8%)**, against mlb 804/850
  (95%) and ncaaf 467/467 (100%). The counter accounting for it is
  `rows_uninformative_ev = 1547` — exactly soccer's selected count.
- **THE FILTER IS RIGHT.** `_row_ev_is_hold_restatement` drops a row whose
  `ev_pct` is arithmetically the book's own margin: for a one-sided market the
  price CANCELS and EV is `-hold` for every such row, so ranking on it ranks on
  WHICH BOOK QUOTED. It fires only where the row has NO model view. Its own
  evidence: 2,611 rows with a correct model edge topped out at **-4.73** against
  a live shortlist whose #50 was **+0.64**. The value floor cannot catch them —
  it is derived from the same hold, so filter and input move together.
- **WHY SOCCER SPECIFICALLY:** by recorded decision, not oversight.
  `soccer-model-dispersion` measured the model WORSE THAN MARKET IN 8 OF 9
  LEAGUES and declined to publish `model_edge_pct`. Corroborated: only 19% of
  the served soccer rows carry one.
- **CHAIN, every link deliberate:** weak model -> no published model edge -> EV
  degenerates to the book's hold -> filter removes the row -> few soccer
  fixtures on the board -> Kalshi soccer cannot match (ceiling 28 of 171).
- **DO NOT "FIX" THIS AS COVERAGE.** The two available moves are publishing a
  model edge the model has not earned, or exempting soccer from the filter —
  which puts ~1,400 rows ranked on the book's margin onto a money-adjacent
  board. If ever done: behind a flag, default off, caveat stated where the rows
  surface, and never described as a coverage fix.
- **THE REAL LEVER IS UPSTREAM:** give soccer a model view worth ranking on —
  `soccer-model-dispersion`'s open per-league discrimination work, not board
  plumbing.
- **THIRD REQUESTED FIX IN ONE SESSION THAT WAS ALREADY WORKING**, after the
  soccer TITLE PARSER and the FORWARD FIXTURE HORIZON. The other two would have
  shipped inert; this one would have degraded the board.

## [soccer-live-match-state] Soccer's live tier is WIRED AND VERIFIED ON LIVE MATCHES (2026-08-21)

**All three live board gates read soccer's live re-sim and were measured on four
matches actually in play** `[verified 2026-08-21 19:23Z, lane
soccer-board-mlb-parity]`, board built 19:22:52Z i.e. AFTER the refresh-worker
deploy (compared, not assumed). gate 2 PASS: 1144 rows considered, 58
live-projected, 240/240 indexed, producer cap 4/12 reported. gate 3: index_size
4, 19 considered, 19 projected, **19/19 withheld by
`no_two_sided_market_price`** -- a named refusal, not a bare zero. gate 1
`supported=true`, no corrections owed. **Every live probability MOVED off
pregame** (Arsenal 0.79 -> 0.9125 after going 1-0; Standard Liege 0.41 ->
0.3375 goalless at 32'), which is the check that separates a live tier from a
pregame number in a live slot.

**NOT YET SEEN: gate 3 PRICING a live edge.** Only withholding by name. Needs a
live soccer market quoted two-sided; the four fixtures on 2026-08-21 were not.

**Soccer live state does NOT cross services via the per-league files.**
`poll_soccer_live_state.py` writes them with a raw `out_path.write_text()` on
live-odds-worker; the board builds on refresh-worker, and `read_json_file`
routes to keyvalue -- so neither the filesystem nor the key resolves. The only
crossing artifact is `live/soccer_live_lens.json`, written through
`refresh_state_store` by `live_lens_loop.py`, which carries
`poll_active_leagues_for_tick`'s FULL return (every in-play match, its
projection and its live props). `soccer/live_lens.py`'s docstring calling that
path a "bookkeeping/validation snapshot only" describes INTENT, not behaviour.

**Soccer's live projection publishes a scoreline distribution** (`9c8ec540`), so
live totals AND spreads price at any line rather than only at 2.5.

### Superseded: the 2026-08-20 card-only reading (kept because it is still true of the CARD)

`origin/main` `ca75e0a1`; LIVE in production as grafts `bd4b1a67`
(live-odds-worker, 21:33:45Z) and `075226dd` (web, 21:41:5xZ). Soccer's card
serves a real score in BOTH live and final states, a live clock, and a real box
score. Verified end to end against
La Liga fixture 401882908 in both states: at 83' the card read 1-0 with
`live_state.clock "83'"`; after full time it read Final 1-1 with a "Final
score" section, both goals (48' Camello, 84' Mariano) and team stats
(possession 51.8/48.2, shots 15/8). Verified on the SERVED surface after deploy:
`/soccer/api/cards?date=2026-08-20` reads `ALA 1 - 1 RAY` Final with Goals +
Match stats ahead of the sim box, 0 pre-kickoff games showing a score; 10 of 10
leagues published a `match_box` key that does not exist at the parent SHA.
**The LIVE CLOCK is NOT verified in production** -- every production reading so
far is of a FINISHED match, which correctly has no clock.

**A SECOND WEB DEPLOY (`79cb457e`, 22:00:0xZ) WAS NEEDED, and the reason is a
standing hazard:** web reads the GIT-TRACKED MIRROR of
`recommendations_2026-08-20.json` (`generated_at 2026-07-20`, `status_state
"pre"`), so every score source correctly refused it and the card went blank
three minutes after a green verification. `_effective_state_with_box` lets the
fresher per-match `match_box` reading set the state (upgrade-only; the kickoff
refusal still applies; a fixture with no `match_box` entry cannot be upgraded).
Now 6 of 6 reads serve `ALA 1 - 1 RAY` Final with real box sections WHILE THE
ARTIFACT IS STILL STALE. **The staleness itself is NOT fixed** -- that card's
sim projections, win probabilities and market tiles are still read from a
2026-07-20 artifact. Handed to a separate session.

Three facts worth not rediscovering:

- **`live_home_score`/`live_away_score` in `recommendations_*.json` are REAL.**
  They are ESPN's `competitors[].score` via `fetch_events`
  (`build_soccer_artifacts.py:289`) -- "0" before kickoff because that is what
  a scoreboard says before kickoff, `'2'`/`'0'` on a completed match. A prior
  session recorded them as a fabricated placeholder; that rested on a sample in
  which **all 57 git-tracked matches were `status_state == "pre"`**. They must
  be GATED on state, not removed: the live poller fetches `statuses={"in"}`, so
  this is the ONLY score path a FINAL match has.
- **Soccer's `picks_*.csv` and `recommendations_*.json` ARE allowlisted** --
  `artifact_publisher.py:460` and `:474` -- and both return **200 with real
  content** from `/api/ops/artifacts/export`. A prior note said 403/count=0.
- **`poll_soccer_live_state` now writes a `match_box` key** inside
  `live_state_{date}.json` (already allowlisted), covering `in` AND `post`,
  separate from `games` so a finished match never reads as live.

## [soccer-live-momentum] FotMob momentum is production's signal now; the ESPN proxy carries none (2026-08-22)

**A 5,552-match dataset (2024-08-09..2026-08-22, the 10 leagues tracked)
established that FotMob's own per-minute momentum series predicts DIRECTION
(which team scores next: dAUC +0.0707, AUC .577, calibrated) and carries
near-zero signal for WHETHER/HOW MANY/WHEN a goal happens (any-goal-in-15min
dAUC +0.0007).** Dataset committed: `reports/soccer_backtest/fotmob_2y.json.gz`
(4.7MB), loader `scripts/soccer_load_2y.py::load_2y()`. Full breakdown:
`reports/soccer_backtest/signal_decision_deepdive.json`.

**The production ESPN-commentary momentum proxy (`syndicate/features/soccer/
features/momentum.py`) was tested directly against its own weighting scheme
(699 matches, holdout, half-lives 30s-1800s) and carries NO measured
goal-timing signal at any setting** (dAUC -0.0006 to +0.0002, monotonically
worse as half-life grows). It is retired from production use, code and its
own docstring left intact.

**Deployed 2026-08-22 22:18:35Z to live-odds-worker, SHA `94a16efe`**
(confirmed via Render API): `poll_soccer_live_state.py` now sources momentum
from `syndicate/features/soccer/ingestion/fotmob_momentum.py` (resolves the
match via `fotmob_match_id.py`, by league+date+team-name, league ids pinned by
name AND country). `cards.py` `_momentum_chart` strength bands retuned to
FotMob's measured 0-100 scale (40/60/80, was 1.0/2.5/5.0 on the old proxy's
unbounded scale). No fallback to the ESPN proxy on a join/fetch miss --
`supported: False` hides the panel instead.

**NOT YET VERIFIED: the FotMob match-id join has never resolved a real
production fixture.** Confirmed the deploy is live and the new code path runs
each 60s tick (`generated_at` on the live-state artifact postdates the
deploy), but every league checked had zero live matches at verification time.
First real test: 6 MLS fixtures kick off 2026-08-23T01:30Z. Read
`soccer_source/mls/api/live_state/live_state_2026-08-23.json` after and check
for `momentum.source == "fotmob"` with a real match id on at least one game --
a silent 0% resolve rate looks identical to a quiet slate. Full detail:
`.syndicate/deploys.md` 2026-08-22 22:18:35Z entry.

## [soccer-compact-cards] Pregame + final compact cards redesigned and DEPLOYED, verified on production HTML (2026-08-22)

**Web live 23:08:55Z, SHA `a1dc1e9a`, confirmed via Render API + a direct
fetch of production HTML** (not just a health check). Two changes to
`_scoreboard_strip_soccer.html`, both in `syndicate/features/soccer/cards.py`
+ `syndicate/static/shared/dense_cards.css`:

- **Pregame compact card** now shows date/time, away/home rows with each
  side's sim-projected total, and a BTTS/goals/corners/top-sim-score facts
  grid (`_compact_pregame_facts`). Verified: `/soccer/cards?date=2026-08-23`
  served 24/24 cards with the new markup.
- **Final compact card** now RECONCILES those same four facts against the
  real result (`_compact_final_reconciliation`) -- graded only where a real
  market line existed; an uncaptured market reports projected-vs-actual with
  no fabricated hit/miss. Verified: `/soccer/cards?date=2026-08-22` served 38
  finals with real hit/miss counts (19 hit / 62 miss); one card spot-checked
  by hand (Man Utd vs Hull City) matched the expected grading exactly,
  including the "no market line -> no verdict" rule.

Both reuse the SAME `_compact_pregame_facts(...)` call (hoisted to a local
before the per-game dict's `return`), so the two cards can never show
disagreeing projections for one match. 29 new tests. Deploy measurement:
`.syndicate/deploys.md` 2026-08-22 23:08:55Z entry.

## [soccer] SOCCER

**Owner: `soccer-model-coverage` (new) for the model; UI Lane G for the card.**

- **THE SQUAD FED TO THE SIM WAS WRONG TWICE OVER, BOTH FIXED AND MEASURED
  `[2026-08-20/21, lane soccer-board-mlb-parity]`.**
  (1) `_load_player_rows` unioned every season's `players_*.csv` and deduped
  keeping the newest row, so any player who ever appeared in the league
  survived forever under their last-known club — Arsenal carried Partey,
  Tierney, Jorginho, Sterling and Kiwior. **Arsenal 28 → 23**, verified on an
  artifact rebuilt `2026-08-20T23:43:04`.
  (2) `build_soccer_player_features` bound player rows to fixture teams by
  FUZZY match, so a club not playing today was absorbed by the nearest name —
  **26 Real Oviedo players inside a 21-man Real Sociedad**. **50 → 24**,
  verified on an artifact rebuilt `2026-08-21T01:01:32`, zero Oviedo players
  remaining. Live on workers `68acf3ca` / `a05412f9`.
- **`canonical_team_name` DESTROYED accents rather than stripping them, and
  that is why the fuzzy threshold was 0.72.** The ASCII scrub turned every
  non-ASCII char into a SPACE (`Alavés` → `alav s`), so an accented club name
  never canonicalized to its unaccented twin in the five leagues that have
  them. Fixed with NFKD folding; **0 distinct clubs merge** as a result.
  `match_team_name` no longer binds a player to a fixture at all.
- **SIX club pairs could absorb each other**, only when one plays and the
  other does not: **Manchester City ↔ Manchester United (0.812)**, Paris FC ↔
  PSG, Cercle ↔ Club Brugge, Real Oviedo ↔ Real Sociedad (0.750), LA Galaxy ↔
  LAFC (0.750), Atlanta ↔ Minnesota United (0.722). Only la_liga has been
  REBUILT AND READ; the other five are fixed by construction, unobserved.
- **A bad league slug used to serve EPL.** `/soccer/laliga/cards` (canonical is
  `la_liga`) returned 200 with Arsenal fixtures. `normalize_league` maps
  anything unknown onto `DEFAULT_LEAGUE`; a `url_value_preprocessor` now 404s
  it once for every route. Verified on the served site: 7/7 bad slugs 404,
  10/10 leagues 200. web `93b6d5a4`.
- **`players_*.csv` and `rosters_*.csv` are NOT in `HOT_ARTIFACT_PATTERNS`**
  (403 on `/api/ops/artifacts/export`). The builder's own inputs cannot be
  read from web, so any aggregate quoted about them is a LOCAL MIRROR number.
  `recommendations_*.json` and `picks_*.csv` ARE allowlisted — an earlier
  claim to the contrary was a malformed request, not a gap.
- **`week_dates_within_horizon` bounds artifact builds to today+1.** A league
  whose next fixture is further out builds NOTHING, and no re-trigger changes
  that — it is not a failure. Override is
  `SYNDICATE_SOCCER_SIM_HORIZON_DAYS`, and it needs a worker deploy to take.

- **Soccer serves ZERO shortlist rows and that is the INTENDED interim state,
  not an outage.** Its whole presence was one-book longshot props whose `ev_pct`
  was arithmetically `-assumed_hold_pct`. **Read `rows_uninformative_ev` before
  diagnosing soccer as broken** — soccer is ABSENT from `per_sport` rather than
  present at 0.
- **The A3 filter SELF-HEALS.** It keys on `fair_method`, so if soccer ever gets
  two-sided quotes the fair becomes `consensus` and the rows return with a real
  EV — no code change. `[from-code 08-14]`
- **Two endpoints disagree about projection coverage by 250×, same sport, same
  date, 45 seconds apart `[measured 08-14 19:1xZ]`:**
  `/api/board/layer1?sport=soccer` → 8,456 rows, 2,504 projected = **29.6%**;
  `/api/board/layer2-shortlist` → 8,512 rows, 12 projected = **0.1%**, with
  `rows_with_model_edge: 0`, `matches_in_source: 4`, `unmatched_match_rows:
  8,393`. **These are two different joins and at most one describes the board a
  user sees.** Settle this before raising coverage.
- ~~**SOCCER GAME ODDS HAVE NOT BEEN CAPTURED FOR ANY LEAGUE SINCE 08-10/08-11.**~~
  ~~**SUPERSEDED 2026-08-17 — capture is WORKING.**~~ ~~**RE-OPENED 2026-08-19,
  steps=0 dominant cause, NOT YET FULLY EXPLAINED.**~~ **FIXED AND VERIFIED
  2026-08-20, lane `soccer-odds-capture-cadence-gap`. Root cause, confirmed
  against production OddsAPI directly (not inferred): `_game_markets()`
  (`scripts/fetch_soccer_oddsapi_odds_local.py`) merged h1/h2 segment keys
  into the market list for the BULK `/sports/{sport}/odds` endpoint, which
  422s on an unsupported key across the WHOLE request — every capture had
  produced zero rows since `#343` shipped (2026-08-10 21:17:39 -0500, date
  matches the last good capture exactly). This IS what `steps=0` was: a
  silent per-request failure, not a scheduler or reporting-artifact bug.
  Fixed by narrowing the bulk-endpoint market list back to
  `DEFAULT_GAME_MARKETS` (h2h/totals/spreads); `_segment_market_map()`
  unchanged, still correct for tagging. Deployed to BOTH producers
  (`live-odds-worker` `575decf3`, `refresh-worker` `b2f4b197`). **VERIFIED
  from the writing service's own disk-content log** (not a status endpoint):
  real `book_quotes` growth observed post-deploy, 6 of 8 originally-stale
  matches re-confirmed with `captured_at` minutes old. 2 matches not
  individually re-checked.**
- **THERE IS EXACTLY ONE PRODUCER and it is not refresh-worker.** `phase=pregame`
  builds 50 steps including 10 odds steps; `phase=live` builds 20 steps and **0
  odds steps** — and refresh-worker's soccer autorun runs `phase="live"`, so it
  never fetches soccer odds at all, by design since `#148`. Everything depends on
  `_launch_autorun_soccer_pregame_refresh` on live-odds-worker, 4h cadence.
  **Single point of failure.** `[measured 08-14 18:5xZ, RE-CONFIRMED 08-19 by
  reading _build_soccer_steps directly — the "0 odds steps" claim is code-exact,
  not stale]`
- **WHY the step fails is STILL UNKNOWN.** No error has been observed anywhere.
  **Two hypotheses are DEAD — do not re-run them:** step truncation at #27 of 50
  (falsified by a ~6-step scoped run that captured nothing), and
  three-specific-leagues (all ten are affected). The `#433` step reorder is
  retained on its own merits but **must not be credited with fixing capture**.
- **The run's own logs are UNREADABLE FROM WEB** — `launch_refresh_run` spawns
  the child `stdout=DEVNULL, stderr=DEVNULL` onto the WORKER's disk, and Render's
  collector captures only a service's own stdout. That is the disk split, not an
  absence of logs, and it is how four days of failure produced no visible error.
- **The sim reports its own input is missing:** `SOCCER_PLAYER_ROWS_MISSING` on
  eredivisie, primeira_liga, championship. Observed once while looking at
  something else — **a lead, not a finding.** `[observed 08-14 19:25Z]`
- **Some markets can never carry an edge however good the model gets.**
  `player_shots` / `player_shots_on_target` map to a MEAN and `soccer_projections`
  refuses by design to derive a probability from a mean; the rows are one-sided
  so `_no_vig_over_probability` returns None. `player_to_receive_red_card` and
  `player_assists` are not in the market map at all.
- **MLS cannot be backtested from its current source at all.**
  `fetch_asa_mls_team_history` returns undated **season aggregates**, so a season
  average already contains the whole season and no `as_of` filter can repair it.
  The backtest returns `{}` for MLS with `AS_OF_DROPPED_UNDATED`. `[measured 08-14]`
- **`data/soccer_source/*/validation/*_backtest_*.csv` is NOT CITABLE** (leakage).
  Report soccer backtest accuracy as **unmeasured**. Production is unaffected —
  `build_soccer_artifacts` predicts forward.
- Soccer sims are ENABLED and running; one sim job = one league-date (`#282`).

---

## [soccer-live-tier] SOCCER'S LIVE TIER — VERIFIED, AND WHAT IS NOT

**BTTS AND CORNERS ARE CAPTURABLE, AND THE 07-21 "unavailable" NOTE WAS WRONG**
`[verified 2026-08-22 00:2xZ, live API probe, lane soccer-board-mlb-parity]`.
They are served from the **PER-EVENT** endpoint (the one the props fetcher
already calls), NOT the bulk one, so capture costs **no additional API calls**.
The Odds API's `INVALID_MARKET` carries two messages and only
`"Invalid markets: X"` means the key does not exist; `"not supported by this
endpoint"` means it does. Measured coverage, EPL MUN @ HUL:
`us` btts 7 / corners 7 (CHOSEN, user decision, 2 units/event) ·
`uk` 11/4 · `eu` 4/1 · all four regions 29/18.

**The full BTTS/corners path is BUILT AND TESTED, NOT IN PRODUCTION.** Capture,
de-vig (raw implied 1.0096 -> `p_btts_yes` 0.4903, below raw, correct
direction), main-line selection (9.5) and tiles all verified on real captured
data: `BTTS YES 55.5% | Model 55.5% | Market 49.0% | Edge +6.5 pts`. But
**`refresh-worker` executes the refresh and is on `49e4cef2`**, which predates
the capture — so no `game_markets_<date>.csv` exists in production and the
tiles correctly still read "no market captured".

**MOMENTUM IS NOT LIVE, FOR THE SAME REASON.** Soccer live_state is written by
**refresh-worker** (`SYNDICATE_ENABLE_SOCCER_WEEKLY_REFRESH_AUTORUN`, scoped in
`render.yaml` to "the sim and live_state") — not by live-odds-worker. And the
live-lens loop runs on BOTH workers writing the same aggregate, so a partial
deploy makes momentum **flicker** rather than be absent: whichever ticks last
wins. Publisher is on `06babca2`; refresh-worker is not.

**RETRACTED: "soccer box sections render 0 rows".** That 08-21 UI-audit finding
was a MEASUREMENT ERROR — table sections carry `table_rows` and set
`"rows": []` by design. Verified on production 2026-08-21 23:29Z: Goals 3/2/3/1
rows, Match stats 12 rows on all four fixtures, ARS squad 23. The cards were
always rendering. Two commits (`0aaf71f0`, `94a53639`) were shipped against a
symptom that never existed; neither is reverted (both are defensible in
isolation) but neither was needed.

**Home's cost is a CACHE MISS, not per-game compute** `[measured 2026-08-21
23:2xZ]`: 22.8s miss vs 1.03s hit on the same route, minutes apart.
`MLB_GAMES_STAGE_MS` stage timing is deployed (`8a7b2407`) and UNREAD.


**Live gates 1/2/3 work.** `[measured 2026-08-21 19:23Z, lane
soccer-board-mlb-parity]` Four live matches, on a board built AFTER the deploy
(checked, not assumed). Gate 2: 1144 rows considered, 58 live-projected,
240/240 snapshot rows indexed. Gate 3: reaching, and withholding 19/19 by
`no_two_sided_market_price` — a NAMED refusal, not a bare zero. Every live
probability moved off its pregame value (Arsenal 0.79 → 0.9125 after 1-0).

**The all-day zero was ONE SHADOWED IMPORT.** `live_lens_loop.py` raised
`UnboundLocalError: write_json_file` for mlb AND soccer — a conditional
function-local import in a WNBA branch bound the name local for the whole
function. NO live-lens snapshot was written for ANY sport. Three consumers
looked broken. Fixed `99e56561`, static regression test added.

**SOCCER PRICES ARE NOT CAPTURED DURING PLAY** `[2026-08-21]` —
`soccer_{league}_odds`/`_props`/`_picks` are `phases=("pregame",)`. The card's
`betting` block is frozen at the last pregame sweep, which is the SAME root
cause as gate 3's 19/19 withholding. A live-scoped refresh is written
(`b17c1999`, `_soccer_live_scope` + `--event-ids`) and **is NOT DEPLOYED**.
Props cost ONE CALL PER EVENT: unscoped 60s ticks are ~130k calls/day, scoped
to matches in play, single digits per tick.

**WNBA HAS NO GAME-LINES STEP** — only `wnba_oddsapi_props_job`. Identified
2026-08-21, NOT closed.

**Resumed sims were short a half's stoppage** `[held-out validated
2026-08-21]` — `espn_live_state` returns NOMINAL clock, so a resumption played
to the 90th minute and stopped, never simulating where 5.5% of goals occur.
Fixed `a27578bf`. Held-out (70 European matches, Aug 2026): bias eliminated at
all four cutoffs; **Brier 2.5 0.1454 → 0.1285 BETTER; MAE 0.6394 → 0.6665
WORSE** — adding real football adds variance. Brier at the line is the
objective; MAE of a point estimate is not.

**Momentum LEADS goals, computed from OUR OWN ESPN commentary**
`[measured 2026-08-21]` — pre-goal mean +1.141 vs control 0.000, Cohen's
d = +0.397 (n=76/638), goals EXCLUDED and the read strictly causal. No vendor
dependency, no id join. Published to `games[].momentum` and rendered on the
card — **never yet seen on a live card.**

**`second_half_shot_multiplier = 1.22` IS NOT WRONG.** Measured 57.1% ± 3.7pp
second-half goal share against its assumed 55–56% — inside one standard error.
Do not change it without a larger sample.

---

## [soccer-shots-prop-skill] SOCCER SHOTS PROPS â€” THE POISSON SHAPE IS RIGHT AND THE MEAN IS INFLATED `[measured 2026-08-31, lane layer1-model-edge-join]`

**Asked to measure model skill on the props carrying the board's largest model
edges. Two things are now measured and they point in opposite directions, which
is the whole result: the model's DISTRIBUTIONAL FORM is exonerated, and its
CENTRAL TENDENCY is not.**

The engine is `soccersim/player_props.py`: `poisson_at_least(mean, k)` over
`_SHOT_LINES = (0.5, 1.5, 2.5, 3.5)`. So a prop probability is exactly
`P(X >= k)` for `X ~ Poisson(mean)`, and only two things can be wrong â€” the
Poisson assumption, or the mean fed to it.

### 1. THE POISSON FORM IS EXONERATED, replicated across two leagues

Realized per-match, per-player shot counts from
`data/soccer_source/<league>/shot_events/shot_events_2025.csv` (`event_id` is
the match, `player_name` the shooter). **Zeros recovered** from the season
table's `games` minus the matches in which the player actually shot â€” without
that, the sample is shooters-only and every rate is biased high.

    league    matches  players   disp(var/mean)   P(>=2) obs   P(>=2) Poisson      bias
    la_liga       380      294             1.05       0.1926           0.1935   +0.0008
    epl           379      303             1.07       0.2129           0.2118   -0.0011
    POOLED          -      597             1.07       0.2029           0.2028   -0.0001

**Poisson assumes dispersion 1.00 and gets 1.07. It predicts P(shots>=2) to
within 0.01 percentage points pooled, on 597 players across 759 matches.** Both
leagues agree and the sign of the bias flips between them, which is what noise
looks like rather than a defect. **Do not "fix" the distribution.**

### 2. THE MEAN RUNS ABOVE THE PLAYER'S OWN REALIZED RATE

Inverting `poisson_at_least` on the served board's own `model_prob_over` gives
the mean the model actually used, comparable directly against that player's
season `shots_per90` â€” the model's OWN input file.

    board soccer shots-prop model rows   27
    matched to a season rate             23  (85%)
    SHOTS props (n=15): implied mean / player's own shots_per90
        median 1.19   mean 1.13   min 0.43   max 1.54
        ABOVE the player's own rate: 11 of 15 (73%)

**The worked case, which is also the board's #1 row.** Ante Budimir, over 1.5
shots: model `0.9423`, implied mean **4.57**. His actual season rate is **3.0952
shots/90 over 2995 minutes / 37 games** â€” and 4.57 would sit at roughly the
99th percentile of the league (max 5.01, p90 2.63, median 0.83). Under the
model's own Poisson, his realized rate implies **P = 0.7951**. The market's fair
was **0.8275**. **The market is pricing this within ~3 points of the player's own
realized rate; the model's entire 11.46-point "edge" is the mean inflation.**

**IT CLUSTERS BY TEAM, which points at the team-total step rather than at
players.** The five most inflated rows are all Osasuna (1.54, 1.53, 1.45, 1.19,
1.05). A per-player error would not line up by club; a team shot-total that is
too high, then distributed by `shot_share`, would.

### WHAT THIS IS NOT

**This is not a skill measurement of the model's per-match predictions**, and it
must not be quoted as one. Section 1 scores the FORM given a correct mean;
section 2 compares the model's mean to a season rate on ONE board snapshot,
n=15, dominated by one club. A model is entitled to deviate from a season rate
for opponent, home/away and expected minutes â€” **ratio is not error.**

**The real backtest is blocked on the same wall the `soccer-model-dispersion`
lane already recorded:** the usage-profile inputs are UNDATED SEASON
AGGREGATES (`players_2025.csv`), so the model cannot be replayed as-of a past
date. `shot_events` supplies the outcomes; nothing supplies the historical
INPUTS. Closing that needs dated player inputs, not another scorer.

### CONSEQUENCE FOR THE BOARD

`model_skill` on these rows reads `sample_games: 0, status: unmeasured` and that
is still literally true. But the board's largest model edges now have a named,
measured, non-speculative cause â€” **an inflated shot mean, clustered by team** â€”
which is a better basis for shrinking them than the units argument that was
tried and withdrawn. **The lever is the team shot total, not the scorer, and not
the distribution.**

### CORRECTION `[2026-08-31]` — the team shot total is APPROXIMATELY RIGHT. The defect is the per-player SHARE, and I inferred the wrong term from clustering

**Asked to fix the team shot total, went to measure it first, and the
measurement refutes my own diagnosis. Recorded before any code was touched.**

**WHAT I CLAIMED**, from the section above: the five most inflated rows were all
Osasuna, so "a per-player error would not line up by club; a team shot-total
that is too high, then distributed by `shot_share`, would."

**THE CLUSTERING WAS AN ARTEFACT OF THE BOARD, NOT OF THE MODEL.** The board
carried ONE Osasuna fixture with seven players listed and every other fixture
with one or two. Grouping by club therefore reproduces the fixture, not a
mechanism. The inflation ratios also ranged 1.05-1.54, which a single team-level
multiplier cannot produce.

**THE DECIDING MEASUREMENT — sum the implied means over one fixture:**

    CA Osasuna vs Getafe, 7 players on the board, summed implied mean   11.4
      Budimir 4.57 | Oroz 1.54 | R.Garcia 1.50 | Munoz 1.07
      Moncayola 1.05 | Catena 0.89 | Bretones 0.76
    Osasuna realized team shots/match (38 matches)                      11.03
    league realized team shots/match                                    11.72

**Seven players already account for 11.4 against a team that averages 11.0.**
The full XI would carry it somewhat higher — so the team total is mildly high at
most, nothing like the 1.95x my earlier back-calculation implied. That
calculation assumed the model used Budimir's realized share; it does not, which
is precisely the thing being measured.

**THE ACTUAL DEFECT IS THE TOP SHOOTER'S SHARE.** Budimir takes **4.57 of the
fixture's 11.4 modelled shots, about 40%**, against a realized share of
**89/419 = 21.2%** of Osasuna's shots across the season. Roughly double. The
allocation conserves the team total and mis-distributes within it — which is
why the mean looked inflated per player while the total looked fine.

**A MECHANISM IS NAMED IN THE CODE AND IS NOT YET CONFIRMED AS THE CAUSE.**
`build_usage_profiles`' docstring describes starter awareness: shares are
normalized across the squad weighted by expected minutes, and bench rows are
discounted to `bench_minutes_share = 0.15` rather than dropped, because season
per-90 rates "dilute a squad's volume across everyone who saw the field". That
renormalization necessarily RAISES every starter's share. Whether it raises the
top shooter's by ~1.9x, and whether that is the whole story, has **not** been
established — it needs the profile builder run on the real inputs, not inferred
from the served numbers.

**NOTHING WAS CHANGED.** `model_engine_standard.md` requires a documented
pipeline trace with file:line at each hop before an engine edit, and this repo's
own rule is that adding or altering a mechanism in a CALIBRATED engine requires
re-fitting the rates that were absorbing it — the soccer lane already has a
standing rule that any single-parameter fit must clear a held-out validation,
written after the most trustworthy-looking in-sample result failed one. A fix
aimed at the team total would have moved a term that is not wrong.

**Two model facts do survive intact and neither is affected by this
correction:** the Poisson form is exonerated (dispersion 1.07, P(shots>=2) bias
-0.0001 pooled over 597 players and 759 matches), and the served board's model
means run above the players' own realized rates (median 1.19x, 11 of 15).

### CORRECTION 2 `[2026-08-31]` — "nothing supplies the historical INPUTS" is WRONG. Stored dated PREDICTIONS exist, and the block is a season gap plus an id-space mismatch

**I wrote above that the real backtest is blocked because the usage-profile
inputs are undated season aggregates, so the model cannot be replayed as-of a
past date. That reasoning is sound and the CONCLUSION IS WRONG, because it
assumed a replay is the only route. It is not: the model's own OUTPUT is
already archived, dated, with the mean stored.**

`data/soccer_source/<league>/api/recommendations/recommendations_<DATE>.json`
carries `league`, `date`, `generated_at`, `matches` and `player_props`. Each
player-prop row holds exactly what a skill measurement needs, with **no
inversion and no replay**:

    player_id, player_name, team, side, position, match_id,
    expected_shots, expected_shots_if_playing,
    expected_shots_on_target, expected_shots_on_target_if_playing,
    expected_minutes_share, anytime_scorer_probability

**Coverage in the git mirror: 2,476 prediction rows over 55 distinct matches,
17 dated files, 10 leagues** (la_liga 6 dates, mls 4, serie_a 4, epl 2). Per
CLAUDE.md the mirror is a lossy subset — **production almost certainly holds
more, and that is where anyone should look first.**

**WHAT ACTUALLY BLOCKS THE JOIN — two things, both fixable, neither the one I
named:**

1. **The id spaces differ.** Predictions carry ESPN match ids
   (`401874745`, 9-digit); `shot_events_2025.csv` carries 6-digit ids
   (`740596`, Understat). Direct join: **0 of 55 overlapping.**
2. **AND THE SEASONS DO NOT OVERLAP, which is the binding one.** The stored
   predictions are dated 2026-07..2026-08; the shot outcomes on hand are the
   `2025` season file. No mapping fixes a window that does not intersect —
   this is the CLAUDE.md per-family coverage trap, firing on exactly the join
   it warns about.

**THE UNBLOCK IS SMALL AND SPECIFIC, and it follows from (1) rather than
around it: the predictions are keyed by ESPN match id, and
`syndicate/features/soccer/ingestion/espn_shot_events.py` already fetches shot
events FROM ESPN.** Pulling shot events for those 55 ESPN match ids yields a
DIRECT join — same id space, no mapping table, and the outcomes are for exactly
the matches that were predicted. That is a bounded fetch against a store that
already exists, not a modelling project.

**WHAT THE MEASUREMENT WOULD THEN BE, stated now so it is not designed after
seeing the numbers:** predicted `expected_shots` against realized shot count,
per (player, match). Report the RATE and its denominator; report bias
(mean predicted minus mean realized) and calibration separately, because the
Poisson form is already exonerated and only the MEAN is in question. Split by
`expected_minutes_share`, since starter awareness is the named suspect for the
top shooter's share being roughly double its realized value.

**Unchanged by this correction:** the Poisson exoneration (dispersion 1.07,
P(shots>=2) bias -0.0001 over 597 players / 759 matches) and the finding that
the fixture's team total is approximately right while the top shooter's share is
roughly double. Both rest on the 2025 outcome file alone and neither needs the
prediction archive.

### THE SKILL NUMBER `[measured 2026-08-31]` — the shots model OVER-PREDICTS BY 36%, and it is worst exactly where the board's edges come from

**`model_skill` on these rows has read `sample_games: 0, status: unmeasured`
since they shipped. It is now measured. n=2,476 (player, match) pairs over 55
matches and 8 leagues.**

The join nobody had made: archived predictions
(`api/recommendations/recommendations_<DATE>.json`) carry `expected_shots` — the
model's MEAN, already stored, no inversion and no replay — keyed by **ESPN**
match id; `espn_shot_events.extract_shot_events` reads shot events **from ESPN**.
Same id space, direct join. 55 of 55 matches fetched.

    predicted mean   0.5242
    realized  mean   0.3849
    BIAS            +0.1393        RATIO 1.362
    MAE              0.5558        constant-mean baseline 0.6035
                                   -> the model BEATS the baseline by 7.9%

**IT CARRIES REAL SIGNAL AND IS BADLY SCALED. Both halves matter.** Beating a
constant-mean baseline by 7.9% means the per-player ordering is informative —
this is not noise, and the fix is not to discard the model. It is level.

**CALIBRATION — over-prediction in every decile above the second, worsening:**

     pred range      n     pred   real     bias   ratio
     0.00-0.03     247    0.000  0.016   -0.016    0.03
     0.03-0.12     247    0.081  0.089   -0.008    0.91
     0.13-0.19     247    0.158  0.134   +0.024    1.18
     0.19-0.27     247    0.232  0.206   +0.025    1.12
     0.27-0.36     247    0.311  0.227   +0.084    1.37
     0.36-0.45     247    0.397  0.279   +0.117    1.42
     0.45-0.58     247    0.514  0.381   +0.134    1.35
     0.58-0.77     247    0.673  0.538   +0.134    1.25
     0.77-1.18     247    0.937  0.623   +0.313    1.50
     1.18-3.69     247    1.849  1.348   +0.501    1.37
     3.76-4.92       6    4.254  0.667   +3.587    6.38   <- n=6, treat as a flag

**THE TOP BUCKET IS WHERE THE BOARD'S EDGES LIVE.** Budimir's implied mean was
**4.57**, which lands in that last row. Six observations is not a result — but
the direction is consistent with every bucket beneath it and the magnitude is
not marginal, so it is recorded as **a flag with its denominator attached**, not
as a measurement.

**STARTER AWARENESS IS NOT CLEANLY IMPLICATED — the earlier suspect weakens.**
Bias by `expected_minutes_share`: sub/fringe **1.28** (n=860), rotation **1.44**
(n=1007), near-ever-present **1.33** (n=609). Present in every band and NOT
concentrated in the players a lineup renormalization would inflate most. This is
a broad level error, not a starter-share artefact.

**VALIDATION OF THE INSTRUMENT ITSELF, because a wrong outcome side would
manufacture exactly this result:**
- ESPN capture is complete: **24.15 shots/match extracted vs a 23.4/match
  season benchmark, ratio 1.03**, and all 1,328 events carry a player name.
- **A first pass reported ratio 1.434 and was WRONG.** Name matching was exact,
  so accented shooters (`Martin Ødegaard`, `Gabriel Magalhães`) scored as ZERO
  shots — 48 events, inflating the bias. Re-run with NFKD folding gives 1.362.
  The number above is the folded one.
- The remaining 375 unattributed shots belong to players absent from the
  prediction set entirely. That does not bias a per-row comparison; each
  predicted row is scored against its own realized count.

**STATED LIMITS.** 55 matches, dates 2026-07-20..2026-08-28 — the season's
opening weeks, when the model's own per-90 inputs rest on the fewest games, so
this may be a worst case rather than a steady state. Single snapshot of the
mirror; production holds more recommendation files and the measurement should be
re-run against them before anything is calibrated on it.

**WHAT THIS LICENSES.** `model_skill` for soccer shot props can stop saying
`unmeasured`: the honest verdict is **"beats a constant baseline by 7.9%, and
over-predicts the mean by 36%"**. A 1.36x level error is a sufficient and
measured reason to shrink these edges — the thing the units argument was
reaching for and could not justify. **It is NOT yet a licence to divide by 1.36
in the engine:** a calibrated engine needs the rates that were absorbing this
re-fit alongside it, and this lane's standing rule is that any single-parameter
fit clears a HELD-OUT validation on different matches than the fit.

### PRODUCTION RE-RUN `[2026-08-31]` — ratio 1.398 on 4x the data, and it is a SLOPE error, not a level error. **This supersedes the mirror number above.**

**n = 9,840 (player, match) pairs, 247 matches, 9 leagues**, against the mirror
run's 2,476 / 55 / 8. Predictions pulled from production via
`/api/ops/artifacts/export?pattern=soccer_source/*/api/recommendations/*.json`
— **144 files / 15,978 rows against the mirror's 22 / 2,476.**

    predicted mean   0.5844
    realized  mean   0.4181
    BIAS            +0.1663        RATIO 1.398      (mirror said 1.362)
    MAE              0.6263        constant-mean baseline 0.6494
                                   -> model BETTER by 3.6%   (mirror said 7.9%)

The direction and rough magnitude REPLICATE at 4x the sample. The model's margin
over a constant baseline is **half** what the mirror suggested, which is the
usual direction for a small-sample advantage.

### THE FINDING THAT CHANGES THE FIX: the bias has a SLOPE

     pred range        n     pred    real    ratio
     0.00-0.00       984    0.000   0.020     0.00
     0.00-0.13       984    0.072   0.132     0.55   <- UNDER-predicts
     0.13-0.22       984    0.176   0.189     0.93   <- UNDER-predicts
     0.22-0.31       984    0.263   0.226     1.17
     0.31-0.41       984    0.356   0.238     1.50
     0.41-0.53       984    0.466   0.335     1.39
     0.53-0.68       984    0.600   0.478     1.26
     0.68-0.91       984    0.787   0.577     1.36
     0.91-1.36       984    1.106   0.679     1.63
     1.36-5.64       984    2.019   1.307     1.54   <- OVER-predicts

**The model UNDER-predicts the bottom two deciles and OVER-predicts everything
from the fourth up. Its spread is too WIDE, not uniformly too high.** I recorded
"the error is level, not discard" off the mirror run; on production that is
wrong. **A constant divide-by-1.4 would over-correct the bottom and
under-correct the top.** What this shape calls for is shrinkage toward the mean
— a regression of predicted onto realized — and that is a re-fit, not a scalar.

**Universal across leagues, magnitude varies:** epl and eredivisie 1.22,
mls and bundesliga 1.31, serie_a 1.36, ligue_1 1.44, la_liga 1.51,
championship 1.85, primeira_liga 1.94. **Every league over-predicts**, so this is
the engine, not one league's inputs.

**By `expected_minutes_share`: 1.29 / 1.47 / 1.41** (sub-fringe / rotation /
near-ever-present). Broad. Starter awareness remains unimplicated.

### A DATA DEFECT FOUND BY THE INSTRUMENT CHECK, and it nearly inverted the result

**`belgian_pro_league` shot outcomes are UNUSABLE through ESPN: 3.00 shots per
match extracted against a ~23.4 benchmark, capture 0.13.** ESPN's `bel.1`
commentary carries no shot detail. Those matches DO return some events, so they
pass a naive "has events" filter and score as real matches in which nobody shot.

**Included, the pooled result reads ratio 1.524 and "model WORSE than baseline
by 1.7%". Excluded, it reads 1.398 and "BETTER by 3.6%".** One league with
missing outcomes flipped the headline verdict. Every other league validates at
0.92-1.34 capture. **Any future run of this measurement must validate capture
per league and exclude `belgian_pro_league`** — a missing outcome is not a zero,
and it biases in the direction that condemns the model.

### WHAT THIS LICENSES NOW

`model_skill` for soccer shot props: **"beats a constant baseline by 3.6% on
n=9,840; over-predicts the mean by 40%; the error has a slope — too wide, not
merely too high."** That is enough to justify shrinking these edges and enough to
say a scalar divisor is the WRONG correction. It is still not a licence to ship
a fitted shrinkage: this lane's standing rule is that any fit clears a HELD-OUT
validation on different matches than the fit, and the natural split here is by
DATE, since the archive spans 2026-07-20..2026-08-30.

### SHRINKAGE FITTED AND HELD-OUT VALIDATED `[2026-08-31]` — **a SCALAR DIVISOR WINS, and my pre-registered expectation was WRONG**

Criterion fixed before the held-out numbers were seen, per this lane's standing
rule. Split by DATE, never by row, so no match straddles it. Three candidates,
deliberately including the one I had argued against.

**MY RECORDED EXPECTATION: "AFFINE beats SCALAR, because the error has a SLOPE."
IT DOES NOT. A plain divisor is better held out, in every split and every
league.**

    HELD-OUT TEST, dates >= 2026-08-22, n=6,405 (train n=3,435, 88 matches)
      candidate                    MAE      bias    pred mean
      RAW                       0.6251   +0.1743      0.5726
      SCALAR   (x / 1.3331)     0.5551   +0.0312      0.4295
      AFFINE   (0.1021+0.5818x) 0.5748   +0.0370      0.4352
      constant-mean baseline    0.6278   +0.0000      0.3983
      realized mean on test                           0.3983

**Both pass the criterion; SCALAR passes by more.** It beats AFFINE on MAE and
on absolute bias, **in all 9 leagues individually** (mls, la_liga, serie_a, epl,
championship, ligue_1, eredivisie, primeira_liga, bundesliga) — so this is not a
pooled win carried by one league, which the date/league confound made a real
risk.

**STABLE ACROSS SPLIT POINTS AND DIRECTION:**

    split                 train n  test n   c(train)   SCALAR   AFFINE
    forward cut 08-08        1129    8711     1.2441   0.5691   0.6017
    forward cut 08-15        1818    8022     1.3135   0.5588   0.5854
    forward cut 08-22        3435    6405     1.3331   0.5551   0.5748
    REVERSE cut 08-22        6405    3435     1.4376   0.5535   0.5625

SCALAR wins all four. **But `c` drifts 1.24 -> 1.44 as the training window moves
later**, so the constant is NOT a fixed property of the engine over this window —
whether that is the over-prediction worsening or the league mix shifting is not
established, and it is the reason to re-fit on a schedule rather than hard-code a
number.

**WHY MY SLOPE READING WAS REAL AND STILL WRONG AS A DECISION.** The
under-prediction in the bottom two deciles is real (ratios 0.55 and 0.93), but
those rows predict 0.00-0.22 shots, so their absolute error is tiny. MAE is
dominated by the large-prediction rows, where the error is a clean level
over-shoot. **A miscalibration can be genuine and still not be worth correcting
for** — I inferred "slope, therefore a scalar is the wrong fix" from a ratio
table and did not check what carried the loss.

**THE SIZE OF THE PRIZE:** RAW barely beats predicting the average (0.6251 vs
0.6278, **0.4%**). Corrected, it beats it by **11.6%**. The model's ordering was
always informative; the level was eating almost all of the value.

### NOT SHIPPED, AND WHAT SHIPPING WOULD NEED

Nothing in the engine was changed. `scripts/fit_soccer_shot_shrinkage.py` is
committed so the fit is reproducible and re-runnable as the archive grows.

Shipping this divisor is a MECHANISM change to a calibrated engine, which this
repo requires be accompanied by a re-fit of the rates that were absorbing it —
the shot mean feeds `poisson_at_least`, whose FORM is already exonerated
(dispersion 1.07, P(>=2) bias -0.0001), so correcting the mean moves every shots
prop and every derived probability at once. It is also a live money-path change
on a board that currently ranks one-sided rows on model edge. **That is a
product decision, and the drifting `c` says it wants a scheduled re-fit rather
than a constant.**
