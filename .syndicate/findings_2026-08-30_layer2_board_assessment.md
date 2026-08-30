# FINDINGS — Layer 2 board: live NCAAF, scoring, cycles, odds freshness, exchanges

**Session** `5611932c-e849-4388-8da7-2c6b00c1c8a3`, lane `exchange-join-refusals`.
**Date** 2026-08-30. **Instrument** the served
`/api/board/layer2-shortlist` payload built `00:53:27Z` / served `01:09:57Z`,
plus refresh-worker (`srv-d91dpertqb8s73co8ls0`) logs over the preceding 6h.

> **STATUS OF EVERY NUMBER HERE: read off production, not inferred.** Where a
> conclusion is an inference from those numbers it says so. One claim in the
> first pass was WRONG and is retracted in §6; the REPLACEMENT fix proposed
> there was also wrong and is retracted in §6b. Read both before acting on
> anything about the 314 NCAAF `clubs_unresolved`.

---

## 0. The attack list, in priority order

| # | Target | Measured cost today | Owner / blocker |
|---|---|---|---|
| ~~1~~ | ~~Kalshi h2h keyed by team~~ | **NOT A DEFECT — 905 is a SUCCESS counter, see 6d** | withdrawn |
| 1 | Spread sign convention, **MLB + WNBA only** | ~443 quotes vs 139 board rows (was mis-sized as 3,290 — see 6d) | `kalshi-spread-join-sign` (UNOWNED, claims released) |
| 2 | Kalshi publishes 1,413 NCAAF quotes, wins **0** selections | undiagnosed downstream match failure, not an adapter refusal | unowned |
| 3 | Polymarket NCAAF h2h keyed by club NAME | **~11-43 markets, NOT 314** — see 6b | held by `live-venue-order-placement`; mechanism proven, prize small |
| ~~4~~ | ~~`oddsapi no_side_in_key`~~ | **WORTH ~0 — see 6e.** 4.2% unrecoverable (game lines, no side exists); 95.7% recoverable and REDUNDANT (same capture, no bookmaker, p50 4.5h vs the board's 58min) | withdrawn |
| 5 | NFL + NCAAF have no odds-history shard at all | whole sportsbook feed absent | unowned |
| 6 | Movement term saturates at 20 pts | 18 of 35 movement rows | unowned |
| 7 | Freshness ladder tops out at 3h | 95 of 200 served rows pinned at floor | unowned |
| 8 | Look-ahead builds a second date | ~⅓ of worker board budget | unowned |
| 9 | `/` is 18.5 MB / 6.4s TTFB | every page view | `render-web-request-path` (UNOWNED, released) |

---

## 1. Live NCAAF shows no opportunities — three stacked causes, none of them a broken pipe

Served board carries **6 NCAAF rows of 200**. `rows_with_model_edge = 0` for
NCAAF, against 423 mlb / 622 nfl / 229 soccer / 20 wnba.

**(a) The model edge is deliberately nulled on every NCAAF market.**
`syndicate/features/ncaaf/game_projections.py:275-390` sets
`edge_vs_market_pct = None` on totals (1.67x over-dispersed) and spreads
(margin MAE 15.775 vs market 12.212, n=2233, t=+17.20), and never sets the key
at all on h2h. `football/pick_gate.py` is the authority and it is CORRECT —
this is a measured model failure, not a plumbing gap. **Do not "fix" this by
un-nulling it.**

**(b) No live wiring for NCAAF anywhere.** From the build's own diagnostics:

    live_game_state:   supported=false  "no live status source wired for ncaaf"
    live_gamelines:    supported=false  "no live re-sim wired for ncaaf"
    live_projections:  supported=false  "no live re-sim wired for ncaaf"

`board_enrichment.py:210` is `{mlb, soccer}`; `:1260-1262` are
`{mlb, wnba, soccer}`. NCAAF is in none of the three.

**(c) So the pregame projection is stripped on exactly the live games.**
`live_edge_enforced_rows: 35` — 14 *"game is live: a pregame projection cannot
be priced against a live market"*, 21 *"game is final"*. That policy
(`live_edge_policy.py:87`) is right and it admits a live-AWARE projection;
NCAAF has none to be aware.

**What is left is `ev_pct` alone, and EV alone cannot pick a side.** EV against
a proportional de-vig is `1/overround - 1`, identical for every side. The two
live NCAAF rows on the board demonstrate it exactly:

    NMS @ FS  totals over  47.5  live  ev=-0.858  edge=None
    NMS @ FS  totals under 47.5  live  ev=-0.858  edge=None

Over and under, same game, same number. That is a hold measurement, not an
opportunity.

**INFERENCE (not a measurement):** the only live NCAAF signal that exists today
is cross-venue price, not model. Kalshi published **1,413 NCAAF quotes at 22.9s
old** and Polymarket **906 at 99.3s** in that same build, and Kalshi
contributed **zero** repriced NCAAF rows. That is §5. **Sizing note:** §6b
measures the Polymarket half of that at ~26 joinable markets, not the 314 the
counter suggests — the Kalshi half (905 quotes) is the larger prize and has not
been scope-checked.

---

## 2. The scoring model — three real defects, and one thing NOT to touch

`opportunity_signals.py:608`:

    value       = ev_pct + clip(0.125 * model_edge, +/-1.5) + clip(0.05 * move_pts, +/-1.0)
    reliability = book_confidence * freshness * price_reliability
    score       = min(value, value * reliability)

**DO NOT RAISE `_SCORE_SIM_WEIGHT`.** `settled: 0`; the sim is unvalidated, and
on NCAAF it is measured-bad. The `min()` is load-bearing (a discount must never
promote a negative row). Both are correct as they stand.

**(a) The movement cap saturates on 51% of the rows that carry movement.**
35 served rows have a nonzero move; **18 exceed the 20-point saturation point**
(0.05 x 20 = the +/-1.0 cap). Observed deltas:

    3 4 4 4 5 5 5 5 5 5 10 10 11 14 15 15 20 | 25 30 40 40 40 45 50 55 60
    100 130 150 175 240 245 250 490 2000

A 25-point move and a 2000-point move contribute identically. The cap was the
right structural answer to sim domination; at this weight it destroys the
signal's resolution exactly where steam is most informative.
**Proposed fix:** log-scale inside the cap —
`clip(sign(d) * 0.35 * ln(1+|d|), +/-1.0)` gives 25 -> 0.44, 240 -> 1.0, and
keeps the hard bound that makes domination structurally impossible.

**(b) The freshness ladder has collapsed into a two-value switch.**
`_SCORE_FRESHNESS` steps at 300/1800/3600/10800s. On the served board:

    30 rows at full 1.0   |   3 rows in the entire 300-1800s band   |   95 of 200 (47.5%) pinned at the 0.25 floor

A 3h01m price and a 12.4h price score identically. The ladder was calibrated
for prices that are minutes-to-hours old; the real board is BIMODAL (exchange
at seconds, sportsbook beyond three hours) because of §4.
**Proposed fix:** extend the ladder past 10800s with rungs at 6h and 12h so the
stale half of the board still ranks against itself.

**(c) `layer2_board.py:35` is stale and has already misled two readers.**
It still says *"`_SCORE_SIM_WEIGHT` is 0.0, so this board ranks on market EV and
price shopping ALONE"*. The constant is **0.125**. The comment three lines below
explicitly instructs changing that line in the same commit as the constant. A
session brief and an audit both inherited the wrong value from this header once
already.

Context: EV spans -2.95 to +5.13 (median +0.28; 113 of 200 positive).
`model_edge` is present on only **77 of 200** rows and typically contributes
+/-0.16. The honest description of the board remains *price-led, sim-breaks-ties*.

---

## 3. The cycle — one builder, two dates, and a floor mistaken for a cadence

Path: `IntelligenceState` tick -> `_refresh_layer2_shortlist_only()`
(`pipeline/intelligence_state.py:3983`) -> `pull_hot_artifacts()` ->
`build_layer2_shortlist()` -> `write_layer2_shortlist()`. Web only READS the
artifact; it never builds (`refuse_if_compute_in_request_path`, `:4028`).

**Measured cadence, 16 builds over 5h21m on refresh-worker:**

    19:32 20:01 20:38 21:03 21:18 21:33 21:56 22:20
    22:42 23:09 23:25 23:40 23:55 00:19 00:31 00:53
    gaps 12.3 - 37.2 min, median 22.5 min

`SYNDICATE_LAYER2_FAST_REFRESH_SECONDS=300` is a **FLOOR, not a cadence.** Real
board age at serve time on the sampled payload: **16.5 minutes**. Each build
takes **74-205s** and runs the worker at **90-95% of its 4GB ceiling**
(`container_memory_pct_of_max: 95.0` observed).

**Two dates are being built, alternately, and they are not merged:**

    02:56 date=2026-08-28 elapsed=188.5s  sports=[mlb,ncaaf,nfl,soccer,wnba]
    03:01 date=2026-08-28 elapsed= 98.5s
    03:07 date=2026-08-29 elapsed=114.3s  sports=[ncaaf,nfl,soccer,wnba]   <- no MLB
    03:14 date=2026-08-28 elapsed=180.5s
    03:53 date=2026-08-29 elapsed= 74.7s  sports=[ncaaf,nfl,soccer,wnba]

`SYNDICATE_LOOK_AHEAD_ENABLED`. They write different artifacts. Roughly a third
of the build budget goes to a date web is not serving. The
today/tomorrow/day-after flip-flop is already documented at
`intelligence_state.py:6579`.

**Where the throughput actually goes.** 8,444 considered -> 200 served:

    rows_beyond_quote_age  5177   <- 61% of everything, largest bucket by 4.6x
    rows_beyond_horizon    1124
    rows_below_value_floor  529
    rows_uninformative_ev   211
    rows_implausible_book    73

**The board's throughput problem is not compute. 61% of candidates are
discarded for staleness** against a 14h ceiling. Fixing §4 triples the ranking
pool without one extra CPU-second.

**The front door is the real latency**, and it is on web, not the constrained
worker:

    GET /                          18,543,430 bytes   TTFB 5.84-6.37s   total 6.37-6.97s
    GET /api/board/layer2-shortlist   402,895 bytes   total 0.55s

The page inlines what the API already serves 12x faster.

---

## 4. Odds freshness — two fetchers, two clocks, and one of them is stalled

Source ages, same build, same instant:

| source | age | quotes |
|---|---|---|
| kalshi | **20-24s** | 4,116 mlb / 1,413 ncaaf / 943 nfl / 1,153 soccer / 264 wnba |
| polymarket_us | **96-100s** | 200 / 906 / 736 / 128 / 100 |
| oddsapi (soccer) | 103s | 1,539 |
| oddsapi (mlb) | **3,568s (59m)** | 0 — `no_side_in_key:3647` |
| oddsapi (wnba) | **53,167s (14.8h)** | 0 — `no_side_in_key:68` |
| oddsapi_props (soccer) | **51,093s (14.2h)** | 18,217 |
| oddsapi (nfl, ncaaf) | — | **no shard exists at all** |

Exchange quotes ride the 60s live-odds loop. Sportsbook quotes ride a
FIXTURE-TIERED per-sport pregame sweep: `live_refresh_loop.py:4158`
`_FIXTURE_TIER_SECONDS` is 2h at 3-12h out, 8h at 12-48h, 24h beyond, with
`_PREGAME_SWEEP_INTERVAL_DEFAULTS = {"soccer": 8h}` over a 2h fallback, plus
off-hours ceilings of 900s/3600s. **That is the whole "why is this 2 hours old".**

Served distribution (`QUOTE_AGE_SERVED`, 1,175 rows):
`p50 3,470s (58m)` / `p90 33,793s (9.4h)` / `max 44,653s (12.4h)`.
Worst by sport: wnba 12.4h, soccer 9.4h, mlb 6.1h, ncaaf 2.4h, nfl 23s.

**THE FINDING THAT SHOULD WORRY US MOST.** Across those 16 builds `seen_p90`
went `14,497 -> 33,793s` while `19,269s` of wall-clock elapsed:

    age gained  19,296s
    time passed 19,269s
    ratio        1.0014

**The top decile of the board is not being refreshed at all.** It is the same
set of quotes aging in place, one second per second, for nine and a half hours.

> ### RETRACTED 2026-08-30 — "DEAD CAPTURE" WAS WRONG, AND SO WERE BOTH NAMED CAUSES
>
> This paragraph originally read *"That is a DEAD CAPTURE, not a slow cadence"*
> and named `no_side_in_key: 3647` and the missing NFL/NCAAF shards as the
> causes. **All three claims are false.** The ratio measurement stands; the
> diagnosis built on it did not.
>
> **The capture is alive.** The sidecar was 23 minutes fresh while rows sat at
> 10.7h. What the p90 cohort actually is, measured with the production
> classifier over the FULL cohort rather than a sample, and confirmed in
> production after deploy `77e61607` at `03:42:11Z`:
>
>     STALE_ROW_CAUSE soccer[stale=293 ... market_gone=293]   293 of 293, 100%
>
> `market_gone` = the row's `(event, market)` group has not been observed at
> all. Those rows are **all PREGAME with kickoff ~15h out**, so the feed did not
> legitimately close either. The mechanism is that market FAMILIES run on
> different sweeps — `h2h`/`totals` freshest 43.8 min, `alternate_totals_corners`
> 147.9 min, `player_shots` 403 min, `player_to_receive_card` 664.7 min —
> against **one flat 50,400s board ceiling**. The slow families dominate the
> tail and the flat ceiling cannot tell them apart.
>
> **`no_side_in_key` was independently disproved** in §6e: it is an honest
> refusal over data that is 95.7% redundant and 4.2% genuinely unrecoverable,
> worth ~0 either way. It never touched the p90.
>
> **Why it took a deploy to see it.** `_report_stale_row_causes` classified only
> the 3 worst rows per sport, so the line read `market_gone=3` against
> `stale=288` — "3 of 288 explained" when it meant "3 of 3 sampled". I read it
> that way myself. The cap is removed (lane `stale-row-cause-blind-spot`,
> `f454af96`), and the counts now sum to `stale=`.
>
> **Still open, and a product decision rather than a patch:** DROP `market_gone`
> rows (~⅓ of the served board) or replace the flat 14h ceiling with a
> per-family one. `value_floor_by_sport` already derives per family
> (`method: measured_hold`), so there is precedent for the second.

One build in the window (22:42Z) degenerated to `rows=467, seen_p50=25,864s` —
the whole board went 7h stale and recovered unremarked. **Worth an alert.**

---

## 5. Kalshi / Polymarket — carrying the board, and being thrown away

**What they contribute.** Of 8,444 rows, `6,189 stamped / 2,255 unstamped`, and
the winning price came from:

    kalshi 794 | polymarket_us 188 | oddsapi 33 | oddsapi_props 5,174

On GAME LINES the exchanges supply **982 of 1,015 best prices — 96.7%**. They
are effectively the only fresh game-line source on the platform.

**What they are NOT doing:**

- **Fair-value benchmark: live-only.** `_reprice_live_benchmark`
  (`venue_quote_fanin.py:1206`) requires live + two-sided + single-venue. It
  produced **21 rows across all five sports** (mlb 7, ncaaf 6, nfl 4, soccer 4,
  wnba 0), with `not_live` skipping 2,336 / 2,362 / 1,218 / 537 / 107.
  **Pregame, the exchange price is never part of the fair.**
- **Arbitrage: not wired.** `run_arb_scan` is called from
  `scripts/run_refresh_worker.py:4365` and the comment says it plainly —
  **"detection only."** It reaches neither the board nor the portfolio. No
  two-leg executor exists.

**Quotes discarded every cycle:**

| refusal | count | cause |
|---|---|---|
| `spreads_refused` (kalshi) | 1,499 | sign convention unresolved |
| `spreads_refused` (polymarket) | 1,789 | same |
| ~~`h2h_keyed_by_team` (kalshi)~~ | ~~905~~ | **NOT A REFUSAL — success counter. See 6d.** |
| `leg_without_price` (kalshi) | 813 | |
| `clubs_unresolved` (ncaaf polymarket) | 314 | **~26 recoverable, rest out of scope — §6b** |
| `clubs_unresolved` (soccer polymarket) | 168 | slug parsed to `'No'`/`'Yes'` — **read from PRODUCTION; reproduces as a FABRICATED ZERO in a worktree without `data/`, see 6c(3)** |
| `VENUE_REPRICE_KEYS unmatched` | 2,255 | venue priced it, key did not join |

**~3,290 exchange spread quotes per cycle are discarded on one unresolved sign
convention** (`venue_quote_adapters.py:592`). **SIZING CORRECTED IN 6d: 45% of
those are NFL and soccer, which carry ZERO board spread rows, and the quotes are
ladder rungs (~8/game) rather than games. The prize with real demand is MLB +
WNBA, ~443 quotes against 139 board rows.**

**Standing hazard, already in `state.md`:** 26 of 28 live Polymarket totals
quotes are keyed on the LINE and fanned across games. `best_any_book` is
`polymarket` on 28 of 28 live totals rows. The order path reads the slate row,
not `book_prices`, so no order has been priced off it — but any NEW
`book_prices` consumer inherits the defect.

---

## 6. RETRACTION — the 314 NCAAF `clubs_unresolved` are NOT missing alias entries

**This section corrects a claim this session made earlier in the same
assessment.** It is recorded rather than quietly edited, because the wrong
version was acted on to the point of opening a lane.

**What was claimed:** *"each one is a missing `team_aliases` entry"*, with the
implied fix being to populate the map.

**Where it came from:** the code's own comment in
`venue_quote_adapters._polymarket_ok_reason`, read instead of the data. That
comment is the belief a FORBIDDEN rule had already overturned the day before.

**The governing rule:** `learnings.md` 2026-08-29 — *"FORBIDDEN: closing a
name-join gap by POPULATING an alias map, without first checking the map's
source carries the missing name."* Built, measured, reverted on this exact
sport. Two reasons: a derived map cannot invent vocabulary its source lacks,
and populating one flips `teams_match` from *fall back to heuristics* to
*authoritative*, converting a counted miss into a confident wrong answer
(`canonical_team("ncaaf","MAS")` -> **`UMass Dartmouth`**).

**The check that rule demands, run 2026-08-30:**

    canonical_team("ncaaf", "Badgers")           -> None
    canonical_team("ncaaf", "Wisconsin Badgers") -> None    <- even the FULL name

There is no NCAAF alias map at all, so the join fails on **100%** of Polymarket
NCAAF moneylines — not merely on nicknames.

**Why a nickname map would be actively unsafe here, from the 684-team
registry** (`ncaaf_team_registry.csv`, `mascot_name` column):

    320 distinct mascots | 93 shared by more than one school
    457 of 684 teams (66.8%) sit on a SHARED mascot

    Tigers    25 schools     Aggies     6  (Texas A&M, Utah St, NM St, NC A&T, UC Davis, Delaware Valley)
    Bulldogs  23             Bearcats   6  (Cincinnati, McKendree, NW Missouri St, ...)
    Eagles    17             Badgers    1
    Wildcats  15             Aztecs     1

Mapping `"Aggies"` to any one school is a confident wrong answer on the other
five, at two-thirds coverage of the sport. **This is the rule's failure mode,
not an edge case.**

**The fix that IS correct, and the precedent for it is already in this repo.**
Do not resolve the NAME; resolve the GAME, then use the role. Commit
`a3386d6c` — *"#603 NCAAF: resolve the slug token pair from the moneyline — NOT
by populating the reverted alias map"* — did exactly this for the other half of
the same defect. The machinery exists: `_polymarket_pair_games`
(`venue_quote_adapters.py:918`) already learns `(away_token, home_token) ->
event_id` FROM THE MONEYLINE ROW'S OWN SLUG. Game identity never required the
club name. The h2h path keys on `canonical_team` (`:1198`) only because that
measured better for MLB and WNBA, where the resolver works; for NCAAF it
resolves nothing, so the role key is strictly better than the zero we get today.

**Status: MEASURED 2026-08-30, and the fix proposed above is ALSO WRONG.**
See §6b. Recorded rather than edited away, because it was the second confident
wrong answer in this assessment about the same 314 rows.

**The generalisable lesson, for `learnings.md` if it survives review:** a code
comment naming its own defect's cause is a HYPOTHESIS, not a measurement, and
it does not expire when the measurement that refutes it is written somewhere
else. This one had been refuted 24 hours earlier, in a file the reader was not
reading.

---

## 6b. MEASURED — `314` is mostly OUT OF SCOPE, and the prize is ~26 markets, not 157

Instrument: `scripts/probe_polymarket_ncaaf_slug_role_join.py`, reading
`/api/ops/polymarket/slate` (the keyvalue reader — `artifacts/export` scans DISK
and reports `count: 0` for this artifact; see `learnings.md` 2026-08-29) and
`/ncaaf/api/cards`. No venue API call.

    n=25 polymarket ncaaf h2h rows dated 2026-08-29 (population 165-166, ops.py:609 caps samples at 25)

    today's path: canonical_team resolves both  :  0/25    0.0%
    H1  slug token pair -> registry teams       :  2/25    8.0%   FALSIFIED
    H2  schedule-constrained mascot pair        :  4/25   16.0%   SOUND
        ambiguous (>1 carded game)              :  0/25    0.0%
        unmatched                               : 21/25   84.0%
          PROVABLY out of scope (no FBS pair)   : 15/21   71.4%
          scope UNDETERMINED                    :  6/21          UPPER BOUND, all inspected were FCS

**H1 IS DEAD — the same upstream-vocabulary wall the alias map hit.** Polymarket's
slug abbreviations are not the registry's: `nmxst` (registry has `NMSU`),
`flst` (`FSU`), `emich` (`EMU`), `sacst`, `cita`, `woff`, `morgst`, `indst` all
return `None`. `ncat` coincided. 23 of 25 fail on the slug alone. **The §6
proposal — "resolve the slug token pair, the precedent is `a3386d6c`" — does not
work on this feed, and I asserted it before measuring it.**

**H2 IS SOUND BUT SMALL.** Never resolve the name; constrain by our own slate.
Resolve each carded team to a registry id, read `mascot_name`, and join a
Polymarket row iff its outcome mascot PAIR matches exactly one scheduled game.
On 2026-08-29: **51 games -> 51 distinct mascot pairs, 0 colliding**, and 0 of 25
rows resolved ambiguously. **THE 0 COLLISIONS IS DOING THE REAL WORK AND IT WAS
CHECKED, NOT ASSUMED** — it is the property that makes a globally-ambiguous
mascot safe here, and the probe recomputes it per date and prints it
(`distinct mascot pairs=51 colliding=0`). A date where it is non-zero is a date
where this mechanism must refuse those rows, not resolve them. A mascot 25-way ambiguous globally ("Tigers") is
unique inside a two-team pair on one day — which is why this is safe where a
global map is FORBIDDEN: ambiguity is refused per-row against a real slate
instead of pre-resolved into an authoritative map. Order is never used; the pair
is unordered and the SCHEDULE supplies home/away.

**THE FINDING THAT MATTERS MOST, AND IT IS NOT A DEFECT.** 21 of 25 sampled
markets are games Syndicate does not card — Campbell v East Tennessee St, VMI v
Idaho St, Citadel v Wofford, Savannah St v South Carolina St, Stetson v South
Dakota St. The registry is **247 D-III / 171 D-II / 128 FCS / 138 FBS** and the
board cards FBS-vs-FBS. **Polymarket lists far more college football than this
platform boards, and those refusals are CORRECT.**

So: `clubs_unresolved: 314` is ~157 markets, of which **~11-43 are ours** —
pooled 7/50 = 14.0%, 95% Wilson [7.0%, 26.2%], point ~23 on a 164-market slate.
**The rate DRIFTS: 16% -> 12% within an hour as the slate shrank 166 -> 163 with
games going final.** Four consecutive runs at one slate state were identical, so
that is drift, not run-to-run noise. What is robust is the ORDER OF MAGNITUDE —
tens of markets, not hundreds. No point estimate here survives n=25, which is a
hard cap in `ops.py:609`. **Any plan sized off 314 is sized off a number that mostly means "out of
scope".** The counter is not lying — it counts what it says — but its NAME
invites reading it as a backlog, and it is not one.

**A correction inside this section, made before it shipped:** the first scope
test asked *"is any school sharing either mascot FBS?"* and called Citadel v
Wofford (both FCS) in-scope because "Bulldogs" is also Georgia's. That
over-reported recoverable misses **15x — 28.6% against a true ~0%.** Mascot
sharing is the exact ambiguity this probe exists to respect, and a scope test
that leaked across it was the same category error as the alias map, one level
up. The corrected test asks whether the pair could be FBS-vs-FBS at all.

**What this changes for §0.** Item 1 drops from the top of the attack list. It is
real, the mechanism is proven safe, and it is worth ~26 NCAAF markets — not the
sport-unblocking fix the first pass implied. **Items 2 (kalshi `h2h_keyed_by_team`
905) and 3 (spreads ~3,290) are now unambiguously the largest exchange prizes,
and neither has been through this kind of scope check yet. Do that before
sizing either.**

---

## 6c. METHOD + CONTROL — challenged by a peer session, checked, and it holds

Peer session `local_c1fb3f4e` (lane `mlb-resolver-write-side-effect`) raised
three objections to §6b's method.

**ATTRIBUTION, corrected at that session's request:** the slug-token-pair
mechanism and commit `a3386d6c` belong to lane **`live-venue-order-placement`**,
NOT to the peer session that reviewed this. They never touched
`venue_quote_adapters.py` or `venue_quote_fanin.py`. The 2/25 falsification in
§6b lands on that lane's mechanism and should be read there. All three were checked; none changes the
result, and two are worth carrying because they would have.

**(1) "Do not judge anything from the primary tree — it has DIVERGED."** True and
confirmed:

    primary HEAD  eaeefbdc   origin/main  574bc4d9
    HEAD is NOT an ancestor of origin/main -- 2 unpushed commits
      eaeefbdc  deploy 0c5243b4 measured...
      6529f849  CORRECTION: "VENUE_REPRICE never fires" was LOG TRUNCATION

The probe imports `team_aliases`, `ncaaf_team_registry` and
`polymarket_board_join` from that tree. **Control: all three are byte-identical
to `origin/main` (`git diff origin/main -- <path>` = 0 lines each), as is the
registry artifact under `data/ncaaf_source/.../team_registry/`.** The divergence
does not touch anything §6b read. A full clean-worktree re-run was therefore not
needed — but the diff IS the control and is why, not an assumption that it did
not matter.

**(2) "`2255` may be a truncated log window, not a count"** — the same shape as
`6529f849`, which corrected a "VENUE_REPRICE never fires" claim that turned out
to be log truncation. Checked against three independent readings of the same
build:

    VENUE_REPRICE_KEYS  sum(unmatched_by_sport)  = 213+403+874+53+712 = 2255
    VENUE_REPRICE       rows_in - stamped        = 8444 - 6189        = 2255
    VENUE_REPRICE       unstamped field                               = 2255

Three derivations, two of them from a different log line than the per-sport
breakdown. **`2255` is a real count.**

**(3) "`team_aliases.py` is fed from `data/`, so a worktree without it makes
every soccer pair resolve to None"** — measured by that session tonight, 9
failures with `data/` absent vs 144 passing with it present, and they had to
retract a public "code regression" claim over it. **This does not affect §6b**
(the NCAAF path reads `ncaaf_team_registry`, not `_soccer_alias_by_league`, and
the probe ran in the primary tree, which HAS `data/`). It DOES affect §5's
soccer line: that `clubs_unresolved: 168 ['No','Yes']` figure is read from
PRODUCTION worker logs, where `data/` is present, so it is real — **but anyone
reproducing it in a protocol worktree (`session_worktree.py` excludes `data/` by
default) will see a fabricated zero.** Flagged here because that is exactly the
trap that cost the peer session a retraction.

**THE PROBE'S FULL INPUT SET, enumerated — because the control in (1) is only
as good as this list.** The peer's point: a diff clears the inputs you thought
of, and much of `data/` in the primary tree is untracked mirror output of unknown
vintage.

| input | kind | cleared how |
|---|---|---|
| `team_aliases.canonical_team("ncaaf", …)` | code | **`_alias_map` has NO ncaaf branch — returns `{}` at line 505.** No disk read, no `data/` dependency |
| `ncaaf_team_registry.registry_path()` -> the CSV | `data/` | git-**TRACKED**, and `git diff origin/main` = 0 lines |
| `polymarket_board_join.parse_slug` | code | pure string parsing, no I/O; 0-line diff vs main |
| `/api/ops/polymarket/slate` | production | live read, not local |
| `/ncaaf/api/cards` | production | live read, not local |

**This makes the headline STRONGER than measured, not weaker.** `canonical_team`
for NCAAF is not "0 of 25 happened to fail" — the map is empty **by
construction**, so the function cannot return non-None for that sport on any
input. The 0/25 is structural. And the one `data/` input is tracked and diffed,
so `--date` on another day reads the same cleared CSV.

**RESIDUAL RISK, STATED RATHER THAN CLOSED.** §6b joins a LOCAL registry CSV
against a PRODUCTION slate and PRODUCTION cards, and `CLAUDE.md`'s standing rule
is that `data/**` in git is a lossy mirror of what Render computes. The exposure
is bounded on the schedule side — **51 of 51 carded games resolved to a registry
team, so a richer production registry cannot raise H2's numerator through that
path** — but a production registry whose `mascot_name` strings differ from the
mirror's would change the pair index. Not checked. It would have to differ on
one of the 4 matched or 6 undetermined rows to move the headline.

## 6d. SCOPE-CHECKED — the other two exchange items, and both shrink

Ran the §6b treatment on the remaining attack-list items, per the rule that came
out of the 314 result. **Both were oversized, one of them completely.**

### `h2h_keyed_by_team: 905` IS NOT A REFUSAL. It is a SUCCESS counter.

`venue_quote_adapters.py:628-631`:

    probability = _kalshi_leg_probability(row, "yes")
    if probability is None: no_price += 1
    if market == "h2h": h2h_keyed += 1        <- no `continue`
    else: line = ...
    ...
    if primary_key is None: prop_unnamed += 1; continue   <- the ONLY continue
    quotes.append(Quote(...))                              <- h2h reaches here

Those 905 quotes are **published, not discarded.** `_kalshi_ok_reason`'s own
docstring says so in terms — *"reported alongside the refusals rather than only
on failure: it is the number that says whether the moneyline re-key is reaching
anything at all"* — and I read it as a refusal anyway, because it is formatted
`name:count` inside a field called `reason`, indistinguishable from
`spreads_refused` and `leg_without_price` beside it.

**Attack item #1 is deleted. There is no defect there.** What IS real and
separate: Kalshi published 1,413 NCAAF quotes and contributed **0** selections
(`by_source={'polymarket_us': 86}`). That is a downstream match failure, not an
adapter refusal, and it has not been diagnosed.

### Spreads: 3,288 refused, but 45% have NO BOARD ROW TO MATCH

| sport | kalshi | polymkt | refused | spread rows on served board |
|---|---|---|---|---|
| mlb | 183 | 192 | 375 | 50 |
| wnba | 28 | 40 | 68 | 89 |
| ncaaf | 548 | 807 | **1355** | **1** |
| nfl | 472 | 554 | **1026** | **0 — no demand** |
| soccer | 268 | 196 | **464** | **0 — no demand** |
| **total** | 1499 | 1789 | **3288** | **140** |

**1,490 of 3,288 (45.3%) are NFL and soccer, which carry zero spread rows.**
Neither is an accident: soccer boards h2h/totals/BTTS/corners and does not card
spreads at all, and NFL has `available: 2` rows on the whole board today. Lifting
the sign convention changes nothing for either.

**AND THE QUOTES ARE LADDER RUNGS, NOT GAMES.** 25 sampled NCAAF spread markets
came from **3 distinct games** — one carrying 20 rungs:

    asc-cfb-hawaii-stan-2026-08-29-pos-5pt5    +5.50 / -5.50
    asc-cfb-hawaii-stan-2026-08-29-pos-4pt5    +4.50 / -4.50
    asc-cfb-nmxst-flst-2026-08-29-pos-31pt5   +31.50 / -31.50

~8 markets per game. So 807 NCAAF polymarket spread quotes are ~100 games, of
which we card 51 — and we card their MAIN line, not the ladder (`spreads: 1`,
`spreads_alt: 0` for NCAAF, against `spreads_alt: 43` for MLB and `86` for WNBA).

**Honest size of the spread prize: MLB + WNBA, 443 refused quotes against 139
existing board spread rows.** That is where demand and supply actually overlap.
It is worth doing. It is not 3,290.

### A FOURTH INSTANCE — `leg_without_price` / `no_price`, found by a peer session

Same shape, two lines above the one analysed above, and this one APPENDS:

    626  probability = _kalshi_leg_probability(row, "yes")
    627  if probability is None:
    628      no_price += 1                 <- no `continue`
    648  if primary_key is None: ...; continue    <- the ONLY continue
    651  quotes.append(Quote(... probability=probability,
                             american=probability_to_american(probability) ...))

`probability` is never reassigned between 626 and the append (checked), and
`probability_to_american(None)` returns `None` silently. **So a Quote with
`probability=None, american=None` IS published.**

**THE ASYMMETRY IS THE PROOF THIS IS AN OVERSIGHT, NOT A DESIGN CHOICE.** The
MIRROR leg in the same function guards correctly — `if mirror_probability is
None: no_price += 1` / `else: ... quotes.append(...)`. Same counter, same
function, opposite handling. Only the PRIMARY leg publishes priceless.

**IT IS NOT A CORRECTNESS BUG TODAY, and that was traced rather than assumed.**
`venue_quote_fanin.py:1128` refuses it at the point of use — `if quote.american
is None: continue`, commented *"No price is not a reprice. Refreshing the clock
here would be the age-only laundering this function refuses."* And there is **no
reader of `.probability` outside the adapter at all**, so the fan-in is the sole
consumer. The priceless quote is published and inert.

**TWO RESIDUAL HAZARDS, STATED:**
- A future consumer of the quote list that does not repeat the `american is
  None` guard turns ~700-800 inert quotes per cycle live. The mirror leg already
  shows what the primary leg should do.
- `status = "ok" if quotes else "no_rows"` means a source producing ONLY
  priceless quotes still reports `ok`. That is precisely the past incident
  `_kalshi_ok_reason`'s own comment records ("Every Kalshi quote was published
  priceless for as long as the adapter read `yes_bid`, and nothing said so").

Production magnitude, `leg_without_price`: mlb 557->679, nfl 69->79, ncaaf 49,
soccer 9->6, wnba 0. That count spans BOTH legs, so the published-priceless
subset is smaller than the number shown.

### The exchange items, resized — AND WHICH RESIZES ARE PERMANENT

**Two different kinds of number here, and conflating them would make this
finding read as unreliable when it is the SLATE that moved.**

| item | from | to | basis | reproducible? |
|---|---|---|---|---|
| `h2h_keyed_by_team` | 905 | **0** | INCREMENT SITE — code | **PERMANENT.** Re-reading the code gives 0 forever |
| `leg_without_price` | ~800 | **0 live** | INCREMENT SITE + consumer guard — code | **PERMANENT**, subject to the two hazards above |
| `clubs_unresolved` | 314 | ~11-43 | production slate, `2026-08-30T01-02Z` | **NO** — slate moved 166->163 within the hour |
| `spreads_refused` | 3,288 | ~443 | production slate + served board, same window | **NO** — same reason |

The first two rest on reading an increment site and cannot drift. The last two
are readings with a timestamp: someone re-running next week will reproduce the
zeros and will NOT reproduce 443 or 26. **That is the slate having moved, not
the method being unreliable** — and it is why the interval and the drift
measurement in 6b matter more than either point estimate.

**A headline of ~4,500 discarded exchange quotes collapses to a few hundred
genuinely actionable ones.** Every one of the three was oversized by reading a
counter's name instead of its denominator, and all three came from the same
`reason` string, where success and refusal are formatted identically.

**CAVEAT ON THE DENOMINATOR:** board spread rows are counted on the SERVED
shortlist (1,261 rows), which is post-filter. A sport could hold grid spread rows
that never clear the value/age floors. That would raise NCAAF's 1 — it cannot
plausibly rescue NFL (2 rows on the entire board) or soccer (does not card
spreads by design).

## 6e. SCOPE-CHECKED — `oddsapi no_side_in_key`, the item with PROVEN demand. Worth ~0.

This was ranked next-best precisely because MLB's board demand is not in doubt
(403 available rows, 250 served prop rows). **It still comes out near zero, and
by a different route than the other three: this counter is honest.**

`venue_quote_adapters.py:1325` is `no_side += 1; continue` — a REAL refusal, not
a success counter. The name means what it says. What was never checked is what
the refused rows CONTAIN.

Measured against the live 27.3MB MLB shard
(`mlb_source/artifacts/mlb/odds_history/2026-08-29.json`, `updated_at
2026-08-30T02:21:03Z`, streamed from production):

    3,538 market keys, 0 with `side=`   -> the adapter drops 100% of them

    3,388 (95.7%)  PLAYER PROPS   player_name=wilyer abreu|market=batter_hits_runs_rbis|selection=over
      150 ( 4.2%)  GAME LINES     event_id=..|home_team=..|away_team=..|market=h2h|bookmaker=fanduel
                                  (h2h 50, spreads 50, totals 50)

**THE TWO HALVES HAVE OPPOSITE ANSWERS AND THE COUNTER MERGES THEM.**

**Game lines — the refusal is CORRECT and the code comment is exactly right.**
One `last_odds` per (event, market, book) and nothing saying which team it
belongs to. Not recoverable from this shard at any effort. 4.2%.

**Props — the side IS present, under the field name `selection` (over 1,853 /
under 1,535).** The adapter reads `parsed_key.get("side")` and gets `None`. That
is a field-name mismatch, not absent data, and it is a one-line read.

**AND RECOVERING IT IS STILL WORTH NOTHING, which is the point of doing the
scope check rather than the fix.** Three independent reasons, each measured:

1. **Same capture.** `last_source_path` on every prop entry is
   `oddsapi_hitter_props_2026_08_29.json` (3,102) / `oddsapi_pitcher_props_…`
   (286) — the OddsAPI props capture **the board already reads**.
2. **Strictly less informative.** The shard's prop entry carries ONE aggregated
   `last_odds` and **no bookmaker field at all**. The board's prop rows already
   carry `book_prices` from **8 named books** — betmgm 237, draftkings 227,
   betonlineag 125, bovada 95, williamhill_us 94, betrivers 70, fanatics 23,
   fanduel 10 — median 3 books per row, on **250 of 250** served prop rows.
3. **Older, not fresher — so it loses freshest-wins.** Prop entry age against
   the shard's own `updated_at`: p25 147min, **p50 268.7min (4.5h)**, p75 454min,
   max 470min. The board's MLB rows sit at ~58min. **Only 730 of 3,388 (21.5%)
   are fresher than that**, and those bring no bookmaker with them.

So the fan-in would gain a source that is a staler, book-less copy of prices it
already has. **`no_side_in_key: 3647` is worth ~0 recoverable rows** — 4.2%
genuinely unrecoverable, 95.7% recoverable and redundant.

**WHY THIS ONE MATTERS MOST OF THE FOUR.** The other three collapsed because a
counter was mislabelled or its denominator was wrong. This counter is accurate
and the demand is real — **and the work is still worthless, because nobody had
asked what the refused rows contained.** A refusal count says how often a reader
said no. It says nothing about whether the thing refused was worth having.

**NOT ESTABLISHED:** whether soccer's `oddsapi_props` path (18,217 quotes,
`selected_by_source: 5,174`) is doing real work or the same redundancy — it wins
selections, so it is at least reaching the board, which MLB's does not. Different
architecture per sport; not measured here.

## 7. What this assessment does NOT establish

- **Nothing about model edge.** §1 says NCAAF's model is gated off and why; it
  says nothing about whether any other sport's model is right. `settled: 0`
  still stands platform-wide.
- **No arb viability claim.** §5 counts quotes DISCARDED. It does not claim a
  profitable pair exists. `findings_2026-08-29_live_venue_arb_economics.md` is
  the authority there and its verdict is that the binding constraint is venue
  COVERAGE OVERLAP — which is precisely why §0 items 1-3 come before any
  executor. Building the executor first would be building a consumer for an
  empty set.
- **The §2 fixes are PROPOSALS, unmeasured.** Both change ranking. Neither has
  been run against a served board and diffed.
- **§4's dead-capture finding names two causes and does not claim they are the
  only two.** The 1.0014 ratio proves the p90 cohort is not refreshing; it does
  not enumerate every reason.
