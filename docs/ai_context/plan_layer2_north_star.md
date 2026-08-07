# The board family — Layer 1 (research) and Layer 2 (recommendations)

Written 2026-08-07. Supersedes the first draft of this file, which led with the
memory envelope and was mis-weighted: the look and feel is broadly right, the
**data pipeline's correctness and timeliness** is the problem, and the product
is not one board but a **family** of them.

Reference surfaces the user has named as the target: OddsJam's per-book grid and
its +EV / Low-Hold / Arbitrage tables, and player-props.com's projection+edge
view. Our differentiator over all of them is the **sim**.

---

## 1. The split

| | **Layer 1 — research** | **Layer 2 — recommendations** |
|---|---|---|
| question | "show me everything, let me look" | "what should I bet" |
| scope | **by sport, by day** — the full portfolio | **cross-sport, consolidated** |
| completeness | every market, every line, no quality filter | only what survives the gate |
| opinion | none — it presents, it does not rank | ranked, scored, opinionated |
| consolidates | betting lines + sim + advanced analytics | betting logic + sim factor |
| failure mode | missing a market | recommending a bad bet |

**Layer 1 is a microscope. Layer 2 is a shortlist.** A row can be absent from
Layer 2 and must still be present in Layer 1.

---

## 2. The five boards

### Layer 1

**L1-A — Book view.** The OddsJam grid. Every market for a sport/day, one
**column per book**, best price highlighted, market-family tabs (Main Markets /
Moneyline / Run Line / Total Runs / 1st Half …), live-state chip per row
("BOT 2"), `updated` per quote.

**L1-B — Advanced data view.** The player-props shape, per betting line:
`Line | Over | Under | Projected | Edge Proj | Edge Eff% | Avg/G | Edge AVG |
Injuries | rank columns | Min. Proj | L5 | L10`. This is where the sim and the
advanced analytics sit next to the market price. **This view is the reason we
exist** — OddsJam cannot show it.

### Layer 2

**L2-A — Best bets.** Ranked by the blended score: EV + sim edge + hold +
book confidence + freshness. The consolidated recommendation surface.

**L2-B — Arbitrage.** `PERCENT | REC. BET SIZE | EVENT | MARKET | BETS | BOOKS |
NO-VIG ODDS | WIDTH | UPDATED`. Requires two sides across *different* books,
simultaneously.

**L2-C — Low hold.** Same shape, ranked by hold rather than guaranteed profit.

---

## 3. One row contract, five views — non-negotiable

If we build five pipelines we will get five boards that disagree, and we will
spend the next month reconciling them. Today's lesson: **one rule, one place.**

Every board is a **projection or a filter over one canonical row**:

```
market_row = {
  identity:   sport, event_id, commence_time, home/away, player_name,
              market_key (canonical), selection, line, segment
  prices:     { book: {price, snapshot_ts} }        <- ALL books, not "best"
  derived:    best_price, best_book, books_quoting,
              no_vig_fair, hold, width, ev_pct, arb_pct
  sim:        projection, edge_proj, edge_eff_pct, confidence
  analytics:  avg_g, l5, l10, ranks, injuries
  state:      live/pregame, game_state, suspended, age_seconds
}
```

- **L1-A** = the row, pivoted on `prices`.
- **L1-B** = the row, pivoted on `sim` + `analytics`.
- **L2-A** = rows passing `opportunity_gate`, ranked by `blended_score`.
- **L2-B** = rows where `arb_pct > 0` across books.
- **L2-C** = rows ranked ascending by `hold`.

`opportunity_gate.py` (#245) already owns eligibility and runs at **serve time**
so it cannot go stale in a cached pool. `opportunity_signals.py` (#238/#243)
already computes no-vig, hold, EV, arb, low-hold and the blended score. Those
two are the Layer 2 selectors and they exist. **The gap is Layer 1 and the
substrate, not Layer 2's logic.**

---

## 4. What we measured against this (2026-07-29 MLB shard, 39,370 rows)

```
DISTINCT BOOKS: 11
  draftkings 7,080 · betmgm 6,650 · bovada 4,021 · betrivers 3,955
  williamhill_us 3,861 · mybookieag 3,603 · betonlineag 3,541
  fanatics 2,404 · fanduel 2,353 · lowvig 1,018 · betus 884

GRID WIDTH — books per (event, market, selection, line):
  1,002 of 1,463 selections (68.5%) have 3+ books   -> grid is buildable TODAY
    282 selections are single-book                  -> blank no-vig/width

TWO-SIDED WITHIN ONE BOOK (needed for no-vig + width):
  3,045 of 4,450 (68.4%)

FRESHNESS: snapshot_ts, 78 distinct stamps across 34 hours ~= one per 26 min
```

Three conclusions, each with a direct consequence:

1. **L1-A is a presentation gap, not a capture gap.** We capture 11 books and
   render one "best price". The full grid is available from data already on
   disk. This is the largest visible win available and it costs the worker
   nothing — it is a serve-time pivot.
2. **Timeliness is the real defect.** ~26 minutes between snapshots is
   defensible pregame and *fatal* live: the OddsJam live board moves every
   pitch. A 26-minute-old live price is not stale, it is fiction. Showing an
   honest `UPDATED` column will make this obvious and it should.
3. **~31% of selections will show blank no-vig/width** — single-book or
   one-sided. `batter_home_runs` is 12,409 rows, **100% `over`** across all 11
   books; the other side is not in the feed. Only the margin model fills those.

---

## 4b. The temporal axis — "Today" and "forward looking"

**Not a sixth board.** A scope selector present on *every* board, because the
same row means different things at different horizons.

| scope | contains | why it exists |
|---|---|---|
| **Live** | in-progress games only | the OddsJam live grid; prices move per pitch |
| **Today** | today's slate, pregame | the default for daily sports (MLB/NBA/NHL/WNBA) |
| **Forward** | tomorrow → end of week | **the only useful view for weekly sports** (NFL, NCAAF), and where the softest lines live |

Two things make forward-looking load-bearing rather than nice-to-have:

1. **Weekly sports have no "today".** NFL and NCAAF slates are Thursday →
   Monday. A today-only board is empty six days a week for them. **Known
   blocker: NFL currently self-pins its week to 1** — that must be fixed before
   forward scope means anything for NFL.
2. **The best pregame edges are early.** Books post openers days ahead and move
   them as money arrives; the largest gaps between our sim and the market appear
   *before* the market sharpens. A today-only board structurally cannot see
   them.

Implementation: scope is a filter on `commence_time` over the same
`market_row`. It must **not** fork the pipeline. The one real pipeline
consequence is that the capture window must extend far enough forward — a
7-day lookahead for weekly sports, which is exactly the `#239` soccer
fixture-date lesson (quotes are sharded by *fixture* date, so a puller that only
ever asks for today gets a 404 and logs "absent").

---

## 4c. Pregame and live — both, and they are different products

Every board in §2 exists in both modes. They share the row contract and share
almost nothing else.

| dimension | **pregame** | **live** |
|---|---|---|
| capture cadence | 5–15 min is fine | **sub-60s or it is fiction** |
| price half-life | hours | seconds |
| "stale" means | normal — books post early and sit | **dead** |
| market shape | full two-sided consensus | suspends constantly; one-sided is common |
| fair value | consensus across 11+ books | often single-book; consensus unreliable |
| sim input | pregame projection | must fold in **live game state** — inning, score, outs, count, pitcher |
| arb pairing | pairs persist minutes | pairs persist **seconds** |
| cost of a stale row | a slightly wrong price | **a bet on a pitcher already pulled** |
| credit cost | low | **high, and non-linear for props** |

### What live actually costs

Game lines are one request per sport per poll. **Props are one request per
event**, so live prop polling scales with the slate:

```
MLB, 15 games, props polled every 60s for a ~3.5h window
  = 15 events x 210 polls = 3,150 requests x markets x regions
```

That is the single largest discretionary cost in the whole plan, and it is why
live cannot simply be "the same loop, faster".

**Required design — tiered live capture:**
- **Tier 1 (60s):** game lines for in-progress games. Cheap, one request per
  sport, and it is what the live grid's headline columns need.
- **Tier 2 (2–5 min):** props for in-progress games *only where a market is
  actually live and unsuspended*. Do not poll a suspended market.
- **Tier 3 (on state change):** re-poll an event when the game state changes
  materially (half-inning, pitching change, scoring play) rather than on a
  fixed clock. The live-lens loop already knows this.

### Non-negotiables for live

1. **Live capture belongs on `live-odds-worker`, not `refresh-worker`.** Two
   services, one serial process each, different budgets. Do not add a live loop
   to the worker that just stopped OOM-ing.
2. **`age_seconds` is a first-class column and must be honest.** A live row over
   ~900s is dead and `opportunity_gate` already drops it (#244/#245). Keep that
   rule in one place.
3. **Live arb requires same-snapshot pairing.** Requiring simultaneity dropped
   **88%** of raw pairs and took an apparent 716 arbs to **~3**. Without it the
   arb board is fiction that looks like profit.
4. **Ship pregame first.** A live board on an open feedback loop is
   *confidently wrong in real time*, which is strictly worse than being thin.

---

## 4d. Books and regions — measured, 2026-08-07

We request **one region** (`SYNDICATE_LIVE_ODDS_REFRESH_REGIONS = us`, on all
three services) and get 11–13 books. Every additional region is a config change,
not an engineering project.

**Measured burn:** 20,322 credits at 2026-08-01 18:01Z → 419,533 at
2026-08-07 15:15Z = 399,211 over 5.88 days = **67,844/day = 2.04M/month**. This
confirms the inherited plan's "2.02M/5M base" — that figure was right.

**CAP CONFIRMED: 5,000,000.** The 14.58M the headers report is not real.

### The cost structure — props are 98.5% of the bill

Everything else in this section follows from one fact: **OddsAPI serves player
props only from `/events/{id}/odds`, so props cost ONE REQUEST PER EVENT**, while
game lines are one request per *sport*. Measured on MLB:

```
game lines :  1 request  x  3 markets  =    3 credits per poll
props      : 18 requests x 11 markets  =  198 credits per poll
                                       -> props are 98.5% of cost, ~45% of rows
```

An earlier draft of this section priced regions off *row share* (49% game /
45% props) and was wrong by a factor of ~33 on the game-line adds. **Cost share
and row share are not the same quantity.** Corrected:

| apply a region to… | added/month |
|---|---|
| **game lines only** | **+30,378** — effectively free |
| props only | +2,004,942 — nearly doubles the bill |
| everything | +2,035,320 |

### The decision, priced correctly

| configuration | /month | % of 5M cap |
|---|---|---|
| NAIVE — all three regions on everything | 8,141,280 | **163%** — impossible |
| **SCOPED — `us2` everywhere, `eu`+`us_ex` on game lines only** | **4,131,396** | **82.6% — fits today** |

`us2` costs real money because its value is *prop price-shopping*, which is the
expensive family. `eu` and `us_ex` are fair-value anchors, only ever needed on
game lines, and are therefore nearly free. Take all three.

### Savings levers, to make room for live

Applied to the scoped 4.13M. **Percentages marked ASSUMED need the
`by_market_family` telemetry to confirm** — they are not measured.

| lever | assumption | running total | % of cap |
|---|---|---|---|
| start | — | 4,131,396 | 82.6% |
| **L1** event-scope props to board-eligible games only | ASSUMED 25% | 3,098,547 | 62.0% |
| **L2** cadence by time-to-start (far games hourly) | ASSUMED 30% | 2,168,983 | 43.4% |
| **L3** prune low-value prop markets | ~measured 10% | 1,952,085 | 39.0% |
| **L4** off-hours gate | ASSUMED 10% | 1,756,876 | 35.1% |

If the levers land anywhere near this, the configuration sits at **~35% of cap
with ~3.2M/month free for the live tier** — which is what makes live props
affordable at all (MLB live props alone are ~756K/month at 60s).

L1 and L2 are the two that matter and both are real engineering, not config.

### An open question worth answering early

**MLB is only ~16% of measured spend** (11,055 of 67,844 credits/day). Where
does the other 84% go? Soccer is the likely answer — many leagues, many
fixtures, and `#239` showed its shards behave differently. Before spending
effort on L1/L2 for MLB, measure the per-sport split: the cheapest lever may be
in a sport nobody has looked at.

### Declined, with reasons

- **`uk`** — its only unique value was Betfair exchange, and **`betfair_ex_eu`
  is already in `eu`**. Declined as redundant.
- **`au`** — negligible value for US sports.

### The books each region actually returns

Queried from the API 2026-08-07 (1 credit per region), not recited. 59 distinct
books exist across all regions; this configuration takes **25 net-new**.

**`eu` — 22 books, 20 net-new.** The fair-value region: **`pinnacle`**,
**`betfair_ex_eu`** (Betfair exchange), **`matchbook`**, plus `marathonbet`,
`onexbet`, `betsson`, `coolbet`, `nordicbet`, `tipico_de`, `sport888`,
`williamhill`, `unibet_*`, `winamax_*`, `betclic_fr`, `leovegas_se`, `gtbets`.

**`us_ex` — 5 books, all net-new.** Near-zero vig, genuinely independent price
discovery: `novig`, `prophetx`, `betopenly`, and the two prediction markets
**`kalshi`** and **`polymarket`**.

**`us2` — 8 books, all net-new.** Soft US retail, for price shopping and grid
width only: `ballybet`, `betanysports`, `betparx`, `espnbet` (theScore Bet),
`fliff`, `hardrockbet`, `hardrockbet_oh`, `rebet`.

### Still open

- **Verify whether `bookmakers=` is billed differently from `regions=`.** If it
  lets us cherry-pick `pinnacle` without buying all of `eu`, the anchor gets
  cheaper still. Low stakes now that `eu` on game lines is only ~30K/month, but
  it would matter if we ever wanted a sharp anchor on *props*.
- **Revive `by_market_family` + per-sport attribution** (dead: 2 observations,
  both 2026-08-01). The cost *structure* above is derived from the request shape
  and is solid; the **savings-lever percentages are not measured** and the
  per-sport split is unknown. See the open question above — MLB is only ~16% of
  spend.

*(A previous caveat here — that the game/prop split was a row-count proxy — is
now RESOLVED: the split is derived from request structure, not row counts. See
"The cost structure" above.)*

---

## 4e. STALENESS — the biggest single defect on the board

Measured on production, 2026-08-07, MLB: **1,528 of 3,246 rows (47%) have a
best price that lags the market.** Not a display bug. The board's headline
number — "best available price" — is wrong on nearly half the rows, and every
downstream number inherits it: EV, edge, arbitrage, low-hold, and the blended
score that ranks Layer 2.

### Four distinct causes, which need four different fixes

**C1 — capture cadence.** `snapshot_ts` shows ~78 stamps across 34 hours ≈ **one
per 26 minutes**. Defensible pregame; fiction live. *Fix: S2's tiered cadence.*

**C2 — books stop updating at different times.** "Freshest per book" across an
all-day append log still puts a 1pm price beside a 7pm one. This is why a best
price can sit 272 points clear of consensus (draftkings +388 against a +116
consensus, observed). *Fix: already labelled per-cell (`stale`,
`lag_behind_freshest_seconds`) — but labelling is not correcting. The board
should rank on a **fresh-only** best price and show the stale one as context.*

**C3 — no simultaneity requirement.** Any cross-book claim — best price,
arbitrage, low hold — is only true if the prices coexisted. Enforcing that
dropped **88%** of raw arb pairs and took an apparent 716 arbitrages to **~3**.
*Fix: a same-snapshot constraint on every cross-book derivation, not just arb.*

**C4 — dead markets.** A price on a suspended market or a pulled pitcher is not
stale, it is void. `opportunity_gate` (#245) already drops these from Layer 2 at
serve time. *Fix: none needed; keep the rule in one place.*

### The rule this implies

**Freshness is part of a price's identity, not metadata about it.** A price
without a timestamp is not a price. Every derived figure must state the window
it was computed over, and any figure combining two books must state that they
were observed together.

Concretely, and in priority order:

1. **Rank on a fresh-only best price.** Today `best` is the numerically best
   quote regardless of age, which is why 47% of rows lead with a laggard. Add a
   freshness bound to the *selection*, keep the stale quote visible as a cell.
   This is a small change and the largest single accuracy win available.
2. **Make `age_seconds` legible.** Done — game state (start time / live status)
   shipped alongside it, because 40 minutes old is normal pregame and fatal in
   the 7th.
3. **Same-snapshot pairing for every cross-book number**, not just arbitrage.
4. **Then** cadence (S2), which reduces how stale things get but cannot fix a
   selection rule that ignores age.

### Why the order matters

Cadence is the expensive fix and the tempting one. But at any cadence, a
selection rule that ignores age will still surface the most stale book as "best"
whenever that book's last price happened to be generous. **Fixing the rule is
cheap and helps immediately at today's cadence; fixing the cadence without the
rule buys less than it costs.**

---

## 5. Sequence

Ordered by what unblocks a **column**, not by subsystem.

### S0 — instrument the spend before changing it — **DONE 2026-08-07 19:15Z**

Measured on **production** via `GET /api/ops/oddsapi/quota`. Every bullet below
that is struck through was answered; two of them were answered *differently from
what this plan assumed*, and the difference changes S0b.

- ~~Confirm the OddsAPI cap.~~ **DONE: 5,000,000.**
- ~~Revive `by_market_family`.~~ **IT WAS NEVER DEAD.** Production has
  **127,650 observations** aggregating since **2026-07-28T02:36Z**. The "2
  observations" reading came from the **local mirror**
  (`reports/odds_control_plane/oddsapi_quota.json`), which is a lossy
  cold-start artifact — exactly the trap CLAUDE.md documents. *No work was
  needed; the instrument was working and we were reading the wrong disk.*
- ~~Find the missing 84%.~~ **THERE IS NO MISSING 84%. MLB *is* the spend.**

  | sport | credits | share |
  |---|---|---|
  | **mlb** | 489,055 | **92.8%** |
  | soccer | 31,817 | 6.0% |
  | wnba | 5,454 | 1.0% |
  | nfl | 453 | 0.1% |

  The assumption that the cheapest lever sat "in a sport nobody has looked at"
  is **falsified**. Soccer is 6%; there is no cheap win hiding there. Any real
  saving has to come out of MLB.

- ~~Confirm capture is actually running.~~ **It is.** Latest observation
  18:44:02Z against a ~26-minute cadence. The 90-second probe that "did not
  move" was simply shorter than one capture interval — a sampling artifact, not
  an outage.

**Where the money actually goes** (`by_market_family`, credits):

| family | credits | share |
|---|---|---|
| props | 315,046 | 59.8% |
| segment | 125,204 | 23.8% |
| alternate | 62,633 | 11.9% |
| full_game | 22,990 | 4.4% |
| event_list / other | 906 | 0.1% |

**Per-event-billed families (props + segment + alternate) = 95.5%.** §4d's
"props are 98.5% of cost" is right in shape and slightly overstated in
attribution: *props alone* is 59.8%, and it is `segment` + `alternate` —
both also per-event — that make up the rest. A lever aimed only at `props`
addresses 60% of spend, not 98%.

**Current burn, and it is better than §4d's baseline:**
```
API used = 422,246 since Aug 1 (6.80d)  ->  62,076 credits/day
                                        ->  1.86M/month  =  37.2% of the 5M cap
```
§4d assumed a 2.04M/40.7% baseline. We have **more headroom than planned**,
which makes S0b's ~4.13M projection land nearer 79% than 82.6%.

*(The API's own header reports a 15M cap. Per the standing note, do not believe
it — 5M is the contracted figure and every projection here uses it.)*

### S0b — enable the three regions, scoped (config, minutes)
`us2` everywhere; `eu` and `us_ex` on **game lines only** (~30K/month each).
Lands at ~4.13M/month = 82.6% of cap before any lever. Then make
`consensus_fair_probability` **prefer** the sharp books, or Pinnacle, Betfair
and the exchanges are just three votes among thirty-eight.
*Exit:* the L1-A grid shows 25 more books and `no_vig_fair` is anchored on
Pinnacle/Betfair rather than a consensus of retail books.

### S1 — L1-A, the book grid, PREGAME (days, serve-time only)
Pivot `book_quotes` into per-book columns. Best-price highlight, `books_quoting`,
width, no-vig where two-sided, honest `updated`. Market-family tabs off
`canonical_market_key` (#224/#247 already thread it end to end). Scope selector
(Live / Today / Forward) wired from the start — it is a `commence_time` filter,
not a pipeline fork.
*Exit:* a sport/day grid that matches the OddsJam screenshot, with real books,
and a Forward tab that is non-empty for NFL/NCAAF.

### S1b — rank on a FRESH best price (small, and the largest accuracy win)
47% of production rows currently lead with a stale "best". `best` selects the
numerically best quote regardless of age; bound that selection by freshness and
keep the stale quote visible as a cell. See §4e — this is cheap, helps at
today's cadence, and no amount of S2 fixes it.
*Exit:* `rows_with_suspect_best` falls sharply without `rows_single_book`
rising — i.e. we corrected the selection rather than hiding the data.

### S2 — cadence, and the live tier
Pregame to 5–15 min; live to sub-60s via the **tiered** design in §4c (game
lines 60s, props 2–5 min and only when unsuspended, plus state-change triggers).
**Live capture goes on `live-odds-worker`.** Fix NFL's week self-pinning here —
forward scope is meaningless for NFL without it.
*Exit:* live `age_seconds` under 60; pregame under 5 min; live prop credit cost
measured against the S0 budget, not assumed.

### S3 — L1-B, the advanced view (the differentiator)
Join sim projections + advanced analytics onto the same rows: `Projected`,
`Edge Proj`, `Edge Eff%`, `Avg/G`, `L5/L10`, injuries, ranks.
*Exit:* every prop row on a slate carries a projection or an explicit reason it
does not.

### S4 — fill the blanks
Book-margin model for one-sided markets, labelled
`fair_method: "book_margin_model"` so it is never confused with a true two-sided
consensus. Pinnacle (`regions="us,eu"`) on the **game-line fetch only** —
~+5.4% credits on a 2.02M/5M base; adding it to props would nearly double spend
for almost nothing.
*Exit:* no blank no-vig cells that are not explicitly labelled.

### S5 — L2-B and L2-C (arb + low hold)
Mostly exist in `opportunity_signals`. The hard part is **simultaneity**:
requiring it dropped 88% of raw arb pairs, and the honest count went 716 -> ~3.
Enforce same-snapshot pairing or the number is fiction.
*Exit:* an arb row can be acted on — both legs still live at the same instant.

### S6 — prove L2-A
`settled: 0` of 8,276. Until settlement works, `blended_score` runs on a stated
prior (`_SCORE_SIM_WEIGHT = 0.5`) that nobody measured. Verify #247, fix
settlement's dispatch (5th of 7 in an `elif` chain, so its interval is
advisory), backfill 3,716 ungraded records, then derive the weights from CLV.
*Exit:* **no measurement, no weight.**

---

## 6. Constraints carried over from the 2026-08-07 outage

Not a phase. Constraints on every step above.

- **S1 and S3 are serve-time pivots and must stay that way.** They cost the
  worker nothing. `opportunity_gate` is the model to copy.
- **Bound retention, not rate.** Six rate fixes failed that night; the one
  retention fix (#253, ≤96 cached page contexts -> ≤2) dropped the floor from
  ~3.1GB to ~0.8GB. Any worker cache gets a **byte** budget and an eviction log,
  never a bare entry count.
- **Stream anything date-sharded or append-only.** `read_text()` +
  `splitlines()` was the same defect in three separate files. A size ceiling
  decides what to *skip*; it never bounds what reading an accepted file costs.
- **Claim before you work.** Status written after the work, plus self-catch-up,
  is a latent infinite crash loop in any autorun.
- **One change per deploy window, pinned by `commitId`;** measure
  boot-normalised (the floor is a function of time-since-boot and every deploy
  reboots, so every fix looks good for five minutes); state the success bar
  before reading the data.
