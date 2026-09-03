# state — polymarket

Split out of `state.md` by `scripts/split_state.py`. Bodies are verbatim.
The INDEX of every subject, across every part, is in `state.md`; the
one-subject-one-section rule is global and spans these files.
Same rules as state.md: when a fact changes, EDIT THE LINE.

## [polymarket-live-totals-quote-names-no-game] 26 OF 28 LIVE POLYMARKET TOTALS QUOTES ON THE BOARD ARE SHARED ACROSS GAMES — one price per LINE, no game identity `[verified 2026-08-29 ~22:3xZ, lane live-venue-order-placement]`

Live Polymarket totals quotes in `quote.book_prices` are keyed on the LINE and
fanned out across every live game carrying that line:

    over  7.5 @ -400   AZ@SF, COL@ATL, HOU@NYM, SD@TB      (4 games)
    under 7.5 @ +344   the same 4
    over  8.5 @ +1233  3 games      over 9.5 @ +1900  3 games
    over 10.5 @ -6567  2 games

**IMPOSSIBILITY CHECK, which is what proves it a defect rather than a market:**
COL@ATL was 1 run in the 7th, so over 7.5 is worth ~2% (Kalshi quoted 0.08);
SD@TB was 13 runs, so over 7.5 had ALREADY WON at 100%. Both carry `-400`
(=80%). One price cannot be both.

**PREGAME rows are UNAFFECTED** — BAL@ATH, PHI@LAA, TEX@MIL totals all carry
prices unique to their game. The collapse is on the LIVE path only.

**`best_any_book` is `polymarket` on 28 of 28 live totals rows**, so the
fabricated cross-game quote is what the board presents as the best available
price; `model_edge_pct` reaches 14.92 on rows priced off it.

**NOT AN INCIDENT, A HAZARD — and the reason is specific.** `ev_pct` on these
rows is -0.99 to -1.40 so none is surfacing as a +EV bet, and the ORDER path
does not read `book_prices`: `execute_portfolio._polymarket_resolve_market`
prices from the per-market SLATE row. **No order has been priced off these
numbers.** Price shopping, best-book display, and any future `book_prices`
consumer on a live row ARE affected.

This is the defect OPEN lane `venue-quote-line-join` recorded as UNFIXED — "a
TOTALS key names no GAME", previously 672 soccer quotes collapsing to six keys.
Same class, now measured on MLB live with a one-read signature (identical price
on two games whose scores make it impossible).

**CONSEQUENCE FOR CROSS-VENUE WORK: no measurement on live Polymarket totals
means anything until the key names the game.** A net-edge computation over
these rows returned +10.93c to +84.75c per contract — recognised as impossible
(an 85% risk-free return against ~$900k daily turnover) and traced rather than
reported. The arithmetic was right; the input was another game's price.

SEPARATELY ANSWERED, the Kalshi side of the same question: of the 13 live
(game, line) totals combos, **6 ARE listed on Kalshi right now (join gap,
recoverable) and 7 are genuinely absent at the venue** — 5 because Kalshi
prunes settled in-play strikes as runs accumulate (SD@TB at 13 runs floors its
ladder at 13.5; KC@CLE at 10 floors at 10.5) and 2 because the game was final.
Pruning lags rather than tracking exactly: HOU@NYM at 6 runs still listed 5.5.

## [polymarket-fill-price-is-reported] THE VENUE REPORTS `avgPx`. "This path has no fill price" was FALSE and cost a 12h live halt `[verified 2026-08-30 18:41Z, live-odds-worker `fcadd126`, lane ncaaf-market-basis-picks]`

Three sessions diagnosed the 2026-08-30 execution halt as *"the venue gave no
price"*. **It gave one.** `venue_order_view` already read `avgPx`; TWO bugs in
the same function discarded it, and fixing either alone still left
`fill_price=None` — which is what forced `execution_ledger` onto its contract
bound, refused `13.13 > 10.8953`, and blocked BOTH venues.

Venue payload for `C65VD0R72KDG`, read by a one-shot probe (`a6eeaf17`):

    cumQuantity 13.13   leavesQuantity 0   ORDER_STATE_FILLED
    avgPx 0.2350        price(limit) 0.22
    side ORDER_SIDE_SELL   intent BUY_SHORT   outcomeSide OUTCOME_SIDE_NO
    commissionNotionalTotalCollected 0.1400

1. **The complement was applied on a side LABEL.** `outcomeSide=NO` turned
   `0.2350` into `0.7650`, absurd against a `0.22` limit — so the downstream
   guard correctly refused it. The guard worked; the complement was wrong. The
   reading is now chosen by which of `{avgPx, 1-avgPx}` the SUBMITTED LIMIT
   agrees with — semantics-free, because `order["price"]` is our own limit
   echoed back on the same scale. Reproduces 4/4 of the recorded fills.
2. **The limit check was DIRECTIONAL and read one way.** "A BUY cannot fill
   above its limit" is true; the unencoded inverse — a SELL cannot fill BELOW
   its limit — is equally true. This order is a SELL, so `0.2350 > 0.22` is
   price IMPROVEMENT and was refused as a violation.
3. **A value outside (0,1) is ABSENCE wearing a number.** `avgPx='0.0000'` on an
   unfilled order was treated as a price: on a BUY it survived as
   `recorded=0.0`, and `fill_stake_dollars` is derived as
   `contracts x fill_price`, so a real position would book at **$0**.

**verify:** `FILL_PRICE avgPx='0.2350' recorded=0.235`, `fill_cost=3.08555`
(= `13.13 x 0.235`, now OBSERVED not bounded); four orders across both side
conventions. **And the strongest reading — `FILL_ABOVE_LIMIT` fired 36 times in
one hour on orders with `filled=0.0` and now returns NOTHING.** That line means
"this price was impossible"; it had become noise and is trustworthy again.

**NOT PROVEN:** no BUY has reported `avgPx=0` and THEN filled since the deploy.
`FILL_PRICE_ZERO_WITH_FILL`/`FILL_PRICE_OUT_OF_RANGE` silence is equally what
"the condition never arose" looks like. **The halt's RECOVERY is not attributable
to this** — `9733a01a` + `77ca329a` cleared it; this fixes what is RECORDED.

## [polymarket-h2h-buys-the-wrong-side] POLYMARKET MONEYLINES BUY THE WRONG TEAM: `outcomes[0]` is not reliably the YES leg `[verified 2026-08-28, lanes portfolio-venue-and-side-integrity / venue-candidate-key-token-guard]`

`outcome_side_for_index` assumes `OUTCOME_SIDE_YES` buys `outcomes[0]`. It does
not. Measured against ground truth: polymarket h2h **5 agree, 3 MISMATCH**;
polymarket totals 9/0; kalshi totals 4/0. Totals are immune BECAUSE they resolve by
NAME (`over` -> YES); h2h has no name to fall back on, so the index is a positional
guess.

`aec-mlb-az-sf-2026-08-27`: our `side=home` (San Francisco), submitted
`OUTCOME_SIDE_YES outcome_index=0 outcome='San Francisco Giants'` at 0.48. StatsAPI
`Arizona 1 @ San Francisco 6`, Final, `home_win=True`. The venue graded it **lost**,
pnl **-5.871** (our exact cost basis), `held_side=POSITION_RESOLUTION_SIDE_SHORT`.
**We bet the winner and were paid a loss.**

Cleanest evidence, needing no team-name reasoning: four sibling futures in ONE
catalogue response, outcomes literally the strings "Yes"/"No", and
`tec-mlb-nlchamp-2026-09-27-atl` lists them **NO-first** while its three siblings
are YES-first.

**TWO DIFFERENT MAPPINGS — do not conflate them.** `outcomes[i] <-> outcomePrices[i]`
(alignment) is PROVEN correct. `OUTCOME_SIDE_YES <-> outcomes[0]` (the binding) is
the false one. An alignment proof says nothing about the binding.

`home`/`away` on Polymarket now REFUSES by name rather than guessing, and that
refusal is **LIVE on live-odds-worker since 2026-08-28T15:06:23Z** (escape hatch
`SYNDICATE_POLYMARKET_ALLOW_TEAM_SIDE=1`). It has **never fired in production** —
nothing tried to place an h2h in the observed window — so its reachability rests
on tests (`off != on`: 4 fail against it, pass with the hatch, asserted through
`order_body`) and on `verify_order_paths`, not on a production line.

**THE VENUE NAMES ITS OWN YES LEG, AND IT IS NOW MEASURED RATHER THAN INFERRED**
`[2026-08-28T20:08:15Z, live-odds-worker 54da64e1, post-go-live 20:05:22Z]`.
`marketSides[].long` + `.description`/`.team.name`, read on three NFL moneylines
(`bettable=True`): `long_index` = **0, 0, 1** — `was-bal` Commanders,
`atl-mia` Falcons, `hou-car` **Texans = outcomes[1]**. **So the YES leg is NOT
`outcomes[0]`**, confirmed on the venue's own field and corroborating the 3-of-8
wrong-team rate independently. `hou-car` repeats the `az-sf` signature exactly:
outcomes reversed against the slug, long side second.

WEAKER, FLAGGED NOT ASSERTED: on `hou-car` the long side's price (`0.5100`)
matches `outcomePrices[0]` while the long side is `outcomes[1]`, which would mean
the misalignment reaches the PRICE too. It rests on a ONE-CENT separation
(0.51 vs 0.50) — the thin-margin trap this file's own learnings record — and
needs a market where the long side is `outcomes[1]` AND the prices are far apart.
It also scratches `venue-join-refusal-visibility`'s alignment proof, which was
run on totals; flagged to them.

STILL **NOT WIRED**: `todo.md #595` step 3 requires scoring the rule against all
8 venue-settled moneylines INCLUDING the 3 that went wrong before the refusal
comes off.

**THE CLASS IS NOW CAUGHT BY A MACHINE.** `paper_settlement._check_venue_grade`
cross-examines every VENUE-stated outcome against the real game result — the two
authorities are independent because ours applies the order's own `side` while the
venue's reads the realized P&L delta on the position it says we held, so a
disagreement is the signature of a wrong-side fill. Live on refresh-worker;
`/api/portfolio/live` serves `grade_conflicts: 3` / `$10.07`, 62 rows carrying
`grade_check` (58 True / 3 False / 1 None). It hit a PRE-REGISTERED prediction —
the three tickers were named before the reading. It never rewrites `outcome` or
`pnl_dollars`. `learnings.md` had recorded this class as "caught twice by a human
looking at a screen and zero times by a machine"; that is no longer true.

## [polymarket-vs-kalshi-prop-prices] — MEASURED 2026-09-01, MLB, production shard

**First cross-venue PROP price comparison the platform has ever been able to
make** (exchange prop prices were in `book_quotes` nowhere before today). Full
method + bounds: `.syndicate/findings_2026-09-01_polymarket_vs_kalshi_prop_prices.md`.

- **Both venues quote ASKS, not mids** — settled from the data by summing both
  sides of one bet at one venue (kalshi median **101.04%**, polymarket
  **101.93%**, ~0-1% below 100). Without this gate the whole comparison would
  have been an ask-vs-mid artifact.
- **The two books agree to about one 1c tick.** 390 bets quoted by both (61.7%
  of polymarket's 632, 48.2% of kalshi's 809): median difference **+0.00pp**,
  median |diff| **0.95pp**, p10/p90 -1.09/+1.13.
- **Staleness control PASSED:** median capture gap 111.8 min, but the
  within-10-minute subset (n=93) returns the same answer (median +0.00, |diff|
  0.90pp) — the agreement is real, not an artifact of comparing across time.
- **KALSHI IS THE TIGHTER BOOK: median spread 1.04pp vs polymarket 1.93pp**
  (~1.9x, and a much fatter tail: p90 2.07% vs 4.93%). That is where "better
  price: kalshi 37% / polymarket 26% / tie 37%" comes from.
- **POLYMARKET WINS ON PITCHER VOLUME MARKETS, and that is the only
  price-shopping signal here:** `earned_runs` 73% cheaper (median -1.13pp),
  `hits_allowed` 58% (-1.13pp). Kalshi wins `batter_total_bases` (15% poly),
  `outs` (12%), `strikeouts` (21%).
- **CROSS-VENUE ARBITRAGE: EFFECTIVELY NONE.** 502 two-sided cross-venue pairs,
  median 101.92%; **6 distinct** below 100% (1.2%), only **2 surviving a
  10-minute same-instant bound**, both ~99%. The other 4 have legs 49-119 min
  apart — stale legs, not mispricings. ~1pp gross is erased by any plausible
  fee, and **Polymarket's fee remains an OPEN question** (the "measured zero"
  was retracted as an instrument artifact; `DEFAULT_FEE_BUFFER = 0.04` is a
  placeholder). **DO NOT build an arb strategy on this.**
- **A doubled count was caught and is recorded:** the first pass reported 12
  sub-100% pairs; each was counted twice (both leg orderings). 6 is the number.
- **SOCCER: NO COMPARISON EXISTS, and it is not a reader problem.** ZERO
  exchange rows of ANY kind (kalshi or polymarket, prop or game) in **92,795
  soccer quote rows across SIX fixture dates** (08-31..09-05) — soccer shards by
  FIXTURE date, so one date would be the wrong window. Instrument calibrated:
  the same reader found 2,870 MLB exchange prop rows the same day. **TWO
  INDEPENDENT CAUSES, each sufficient:** (1) Kalshi soccer never reaches the
  join — `[kalshi_odds] QUOTE_CAPTURE ... sports=['mlb']`, upstream the known
  `unreadable_title` PARSER gap on ~665 real Kalshi soccer markets; (2)
  Polymarket soccer DOES match (~25 rows/cycle: `soccer|h2h` 4, `soccer|totals`
  21) but every one is GAME/TEAM level with an empty `player_name`, and the
  capture is props-only by its correctness bound — all 25 discarded per cycle.
- **THE PROPS-ONLY BOUND'S PREMISE IS EMPIRICALLY FALSE FOR SOCCER**, and this is
  the actionable half. The bound exists because OddsAPI already writes exchange
  GAME lines under the same dedup key (measured on MLB: 2,350 polymarket game
  rows 08-31). In soccer OddsAPI carries **no exchange rows at all**, so there is
  nothing to collide with. **NOT changed** — the guard also hedges against
  OddsAPI starting to carry them, and its stated release condition (`source` in
  `_KEY_FIELDS`, pinned by `tests/test_direct_feed_provenance.py`) is unmet.
- **CORRECTION, read from production:** `_capture_kalshi_quotes` runs on
  **refresh-worker**, not live-odds-worker (zero hits there). The docstring in
  `portfolio_commit._capture_polymarket_quotes` still says otherwise.
- **INSTRUMENT AMBIGUITY worth carrying:** `POLYMARKET_QUOTE_CAPTURE ...
  sports=['mlb','soccer']` lists sports with MATCHES, not sports with APPENDED
  ROWS. Soccer is in that field every cycle and contributes exactly zero quotes.
- **NOT ESTABLISHED:** anything about MODEL edge. This is venue-vs-venue price
  quality on one sport, one slate. Spread figures rest on the two-sided subset
  only (coverage is heavily one-sided at both venues).

## [polymarket-low-activity] — VERIFIED 2026-08-27, refresh-worker + live-odds-worker

**WHY POLYMARKET PLACES ALMOST NOTHING. Three stacked structural facts, NOT a
broken join.** Day totals $23.25 / 8 orders against a $100.01 / 50 cap — caps
are nowhere near binding.

Full refusals, `POLYMARKET_BOARD_JOIN`, 1,344-row board, matched=52:

```
market_type_not_a_game_line          6960   venue's non-sports catalogue, correct
segment_market_not_full_game         1240   halves/quarters, correct
board_market_not_a_game_line          935   OUR PROPS -- venue does not list them
no_matching_polymarket_market         298   league listed, our GAME not listed
outcomes_count_mismatch               296
no_polymarket_market_for_league_date   42   NCAAF absent entirely
side_not_an_outcome_of_this_market     17
```

1. **THE BOARD IS ~76% PLAYER PROPS AND POLYMARKET LISTS NONE.** Sampled live
   MLB board, 300 rows: `batter_hits` 103, `batter_hits_runs_rbis` 58,
   `batter_total_bases` 45, `strikeouts` 11, `outs` 10 = 227 props vs 73 game
   lines. That is the 935 refusal AND the entire Kalshi-217 vs Polymarket-52
   gap — Kalshi DOES list MLB props (`ORDER_PATH venue=kalshi` shows
   `batter_rbis`/`strikeouts`/`batter_hits_runs_rbis`; Polymarket's shows
   `{'totals': {'would_build': 3}}` and nothing else).
   **CORRECTED 2026-09-01 `[lane polymarket-prop-quote-capture]` — "LISTS
   NONE" was FALSE, and the inference shape is the lesson.** It rested on two
   refusal counters that refuse INDEPENDENTLY (venue-side
   `market_type_not_a_game_line` fires before any prop is compared to our
   board; board-side `board_market_not_a_game_line` fires before any board
   prop is compared to the venue), so neither could measure overlap. Measured
   against the venue's own catalogue (99 slug↔question pairs, 8/8 fixtures):
   PROP|mlb is the venue's LARGEST bucket (2,644/cycle), ~170 player props
   per fixture (hits/tb/hr/hrr/k/outs/er/wa/ha). The join now admits them —
   verified in production 18:10:22Z: `POLYMARKET_QUOTE_CAPTURE matches=436
   appended=374` (was 60/0), `market_type_not_a_game_line` 6,960→3,375,
   `board_market_not_a_game_line` 935→138. Props feed the QUOTE CAPTURE only;
   resolvers withhold them (`POLYMARKET_PROP_RESOLVERS armed=False
   withheld=374`) unless `SYNDICATE_POLYMARKET_PROP_RESOLVERS` is armed.
   Evidence: `.syndicate/findings_2026-09-01_polymarket_prop_census.md`;
   `todo #628`. Point 1's ~76%-props board composition remains TRUE — only
   the "lists none" half is retired.
2. **POLYMARKET LISTS A PARTIAL SLATE** of the remaining game lines.
   `POLYMARKET_UNMATCHED` samples show the venue offering entirely different
   fixtures — board wants `Baltimore Orioles @ St. Louis Cardinals`, venue
   offered `mil-nym`/`col-wsh`. So `no_match` mostly means "this game is not
   listed", not "listed under a name we do not know".
3. What survives is **3 positions, all `totals`, all already held**
   (`duplicates=3 placed=0`). Stable all day (matched 55/55/55/52 at
   15:21/15:25/16:01/18:57) — NOT a regression.

**ONE REAL BUG — FIXED by `open-bet-live-status` (`2589365c`), LANDED NOT LIVE
on refresh-worker `[verified 2026-08-27 ~20:0xZ: live=7dd4ce07, does NOT
contain it]`.** A WNBA team-alias gap: `board: 'Washington Mystics @ Phoenix
Mercury'` refused `no_match` while `offered: [... 'wsh-phx@None']` — that IS
the fixture. Buckets `no_match|wnba|h2h: 7` + `no_match|wnba|totals: 15`.
MY REPORT WAS LESS PRECISE THAN THE FIX: I implied both tokens failed; they
measured `wsh` -> 'washington mystics' fine and `phx` -> None as the whole
failure. I had the sample and inferred from the pair instead of testing each
half. The CAUSE is systematic — `_basketball_alias_to_name` merges NBA and
WNBA and drops any key naming two clubs, so every city fielding both loses its
three-letter code (`phx`, `atl`, `chi`, `dal`, `ind`; `min` was supplemented
earlier for the same reason). Fixed as a class, NBA resolution verified
unaffected. refresh-worker runs the join, so the ~22 rows are NOT recovered
until that service deploys.

**THE DEAD BOOT HOOK IS GONE** — `_polymarket_catalogue_at_boot()` removed
(`fcdc5c57`), live-odds-worker live 19:43:37Z, verified here. Their control is
worth copying: `POLYMARKET_CATALOGUE: 0` read alongside `POLYMARKET_US_AUTH: 1`
and `POLYMARKET_US_SLATE: 2`, because all three at zero would have meant "no
boot observed", not "hook removed". `pipeline/polymarket_odds_refresh.py`
remains in the tree with a test suite and NO production caller — deleting a
tested module is its owner's call.

**DISPROVEN — DO NOT RE-PROPOSE.** I hypothesised the totals-only output came
from Polymarket SIDE RESOLUTION, citing `kalshi-spread-join-sign` item #4
(`over->YES/under->NO` a fixed constant while outcome orientation varies).
**Measured `side_not_an_outcome_of_this_market: 17` — the SMALLEST refusal in
the set.** `_probability_for_side` translates `home`/`away` into the row's own
team, matches literally then via `team_aliases`, and returns None rather than
picking positionally; there is no fixed over/YES constant in the board-join
path. That note is about the ORDER path. I attached a real defect to the wrong
module by topic adjacency instead of reading the function.

**NOT ESTABLISHED:** whether today is lower than previous days. Stability
WITHIN today is measured; day-over-day is not. The execution ledger is
`reports/intelligence/execution_ledger.json` (NOT `reports/execution/
live_ledger.jsonl` — I probed that first and it does not exist; the real path
is blocked too, so the conclusion held by luck off a wrong measurement).
**DO NOT "FIX" THIS BY ADDING IT TO `HOT_ARTIFACT_PATTERNS` — that is INERT.**
`execution_ledger._ledger_path()` writes through `write_json_file`, which
routes every path outside `migration_runs/` to the KEYVALUE store and returns
BEFORE touching disk, so there is no file behind that path.
`/api/ops/artifacts/export` is a DISK read; allowlisting turns
`403 not allowed` into an empty result — the guard passes and the data still
never arrives. Documented already at `ops.py:566`. The working shape is a
keyvalue-aware read, exactly like `api_ops_live_lens_snapshot_index`. Asked
`open-bet-live-status` (owns `ops.py` + `execution_ledger.py`) for a read-only
AGGREGATES endpoint — counts per venue per day, deliberately not rows, because
this is the money record. **THEY DECLINED TO BUILD IT ON A PEER REQUEST AND
WERE RIGHT TO.** It is a new outward-facing surface on the money record, which
is a SCOPE decision for the user, not something a peer can authorise — I named
that risk class and then asked a peer for it anyway. Escalated to the user with
the reasoning attached; still PENDING. So day-over-day Polymarket volume
remains unanswerable, and the structural answer above does not depend on it.

**READING TRUNCATED LOG LINES:** the Render logs API returns the full message
in `logs[].message` (2,331 chars for `POLYMARKET_UNMATCHED`); it is the
per-line DISPLAY that truncates. Fetch and slice the field rather than
concluding the detail is unavailable — the counts and samples that answered
all of the above were in a line that looked cut off.

## [polymarket-venue-join] VERIFIED 2026-08-29, all three services on `95c4fb12`

**Soccer, corners, BTTS and NCAAF now execute on Polymarket.** Readings are
post-`BOOTED` lines on refresh-worker, not post-`finishedAt`.

```
matched                              85 (15:22Z) -> 167 (19:08Z)
ambiguous_polymarket_match          206 -> 24     (3-way leg selection)
side_not_an_outcome_of_this_market   81 -> 22     (gt<line> polarity map)
no_candidates|ncaaf|*                90 -> 0      (cfb -> ncaaf alias)
no_match|soccer|alternate_totals_corners  37 -> 3 (line restored to _KEEP)
no_match|soccer|h2h              80 of 80 -> 0    (fixture matching)
kalshi unreadable_title            2264 -> 1790   (two soccer title grammars)
```

**Polymarket's soccer market grammar, measured rather than guessed:**
- 3-way h2h is **THREE Yes/No markets**, one per outcome, subject in the slug
  (`-liv`, `-draw`, `-not`). Not one market with three outcomes.
- Corners are `cor-all-gt<line>` PROP rows; `gt` states the direction, so
  **`Yes` = over**. 434 of them — the third-largest soccer PROP family.
- PROP vocabulary: `exact-score` 930, `fh-exact-score` 496, `cor-all` 434,
  `btts` 62, `ftts-<club>`, with `fh-`/`sh-` half variants.
- College football is filed under **`cfb`**, never `ncaaf` (2,194 rows).
- **The venue row's `line` field is the ONLY source for corners** — their slug
  carries no parseable number. `_KEEP` must retain `"line"` or every
  `_SLATE_STORAGE_FIELDS` reader silently gets `None`.

**`_has_segment` must screen `fh`/`sh`.** They are soccer halves and the old
pattern only matched digit-led ones (`1h`/`2h`), so 124 half-BTTS contracts were
admitted as full-game. Segment refusals 465 -> ~1,850 after the fix; that RISE is
the correction.

**STILL FAILING, deliberately:** MLB spreads, 22 rows. Outcomes are signed
numbers (`+1.50`/`-1.50`) against a board asking home/away, and the two observed
samples both carry `pos-1pt5`, so they cannot establish whose perspective the
venue states the spread from. Left refusing — a wrong polarity is a wrong-side
fill on live money.

**UNPROVEN, five readings:** `forward_date_widened` is `{}` on every production
read, night and day. The slate-vs-fixture date fix has never fired.

**ORDERS: there is NO Polymarket cancel path.** `kalshi_orders.py` has
`cancel_order`; `polymarket_us_orders.py` has submit/fetch/view and none.
Resting orders are GTC with no `commence_time` expiry, so a pre-game limit rests
into a live game — one was submitted 13 seconds before kickoff and never filled.
Cancelling requires Polymarket's own UI.

---

## [polymarket-orders-are-cancelled] 2026-08-30 — the venue cancels them, we re-place them, and nobody knows why

**THE ORDERS DO NOT REST AND FAIL TO FILL. THEY ARE CANCELLED.** That reframes
the original question: it is not a pricing or sizing problem at all.

**WE ARE NOT DOING IT — fifth cause eliminated.** `cancel_stale_resting_orders`
(15-min age, 1c band, max 3/pass) is a real venue-write loop, but
`run_live_odds_refresh_worker:1676-1699` feeds it ONLY Kalshi rows and says so:
*"Kalshi first and its result kept ... Polymarket's pass runs for its ledger
corrections only."* Polymarket's own `cancel_order` (`3170db13`) exists and is
NEVER CALLED. So the cancellations are venue-initiated.

**THE SUBMIT -> CANCEL -> RESUBMIT LOOP is real, and it is where the duplicate
exposure came from:**

    tsc-sea-lec-rom-2026-08-31   submit 01:02:05 -> CANCELED 01:30:32 -> resubmit 01:30:35
    tsc-mlb-phi-laa-2026-08-30   submit 16:42:25 -> cancelled -> 18:19:10 -> cancelled -> 20:48:00

The resubmit follows the observed cancel by THREE SECONDS — same tick.

**REFUTED: a fixed venue TTL.** `C6R7RS83JKDD` died ~28 min after submit, but its
replacement `C6RNQZ8B2KDE` has been `ORDER_STATE_NEW` for 40+ minutes
(01:30:35 -> 02:10:11) with no cancel. **REFUTED: market close** — sea-lec-rom
was cancelled ~15 HOURS before its 16:30Z kickoff.

**CORRECTION, MINE, CAUGHT BEFORE IT WAS REPORTED AS A FINDING.** I measured a
near-perfect +62s correlation between deploys and cancellations across six
deploys and nearly called it cancel-on-disconnect. It was an artifact: I matched
the raw text `order_state_canceled`, which appears on EVERY pass that re-prints
an already-cancelled row. Filtering to actual `RECONCILED` state TRANSITIONS
leaves **three events in 12h** — 18:18:51 (n=4), 19:59:16 (n=1), 01:30:32 (n=1)
— and only one is deploy-adjacent. **A re-report is not an event.**

**STILL WORTH EXPLAINING: 18:18:51 cancelled FOUR orders at once** (lad-det x2,
phi-laa, lal-cel-ath). A simultaneous batch looks like a session-level event, but
no restart appears in the 18:00-18:30Z logs.

**MEASURED 2026-08-31T02:34:51Z — EXPIRY IS DEAD. `goodTillTime=None` ON ALL
FIVE ORDERS, and `tif='TIME_IN_FORCE_GOOD_TILL_CANCEL'` on all five.**

    C6RNQZ8B2KDE  sea-lec-rom  NEW     created 01:30:36  tif=GTC  goodTillTime=None
    C6RYD4TDWKDH  bun-scp-scf  NEW     created 01:47:57  tif=GTC  goodTillTime=None
    C4N3GPYA4GNQ  nfl lar-lac  FILLED  created 08-27     tif=GTC  goodTillTime=None

Two facts, both new. **The venue imposes NO expiry** — there is no clock on these
orders. And **the venue DID store the good-till-cancel we sent**, which had been
an assumption nothing ever read back.

The `created` timestamps close the TTL question outright: `C6RNQZ8B2KDE` has been
`ORDER_STATE_NEW` for **64 minutes** and counting, while its predecessor
`C6R7RS83JKDD` died at ~28. Cancellation is not a clock. **Sixth cause
eliminated.**

**THE 18:18:51 BATCH, CHASED 2026-08-31. Four more causes eliminated, and my own
framing of it is now suspect.**

Window bounded to **18:13:12 -> 18:18:51**: the prior polymarket reconcile pass
reported `changed=0`, this one `changed=4`. Inside that window:

- **NOT an account-wide sweep.** `candidates=10 venue_orders=10 changed=4` -- ten
  orders read, four cancelled. Selective. But the six survivors were already
  FILLED, i.e. terminal and uncancellable, so the four may still have been ALL
  the OPEN orders. That distinction is unresolved.
- **NOT insufficient collateral.** Balance FLAT at $87.26 across the window
  (18:12:47 / 18:18:36 / 18:26:44), and it did not RISE afterwards either, so
  those orders were not holding reserved funds.
- **NOT a restart or OOM.** The Render EVENTS API is empty from 17:30 to
  18:34:20Z.
- **NOT a deploy.** The nearest one STARTED 18:34:20, after the fact.

**THE VENUE DOES NOT SAY WHY.** Its per-order payload carries 24 fields and no
cancellation-reason field; `state` is the only status-bearing one.

**AND "FOUR AT ONCE" IS MY WORDING, NOT A MEASUREMENT.** We OBSERVED four
transitions in ONE reconcile pass spanning 5.6 minutes. Whether they were
cancelled SIMULTANEOUSLY is a different claim. `lastTransactTime` is returned on
every order and has never been logged: if the four share one timestamp it is a
single sweep; if they differ, they are independent events being treated as one
phenomenon.

**DEPLOYED AND READ 2026-08-31T02:50:52Z (96735d8a). One half works, the other
half was a miss.**

**`lastTransactTime` WORKS, and was validated BEFORE being relied on:**

    resting  sea-lec-rom  created 01:30:36.041  lastTransact 01:30:36.043  (untouched)
    filled   nfl lar-lac  created 08-27 18:33:31  lastTransact 19:40:20    (+67 min)
    filled   sea-juv-par  created 19:45:07        lastTransact 19:48:59    (+4 min)

It equals `created` to the millisecond for an untouched order and is the fill
time for a filled one. So the next cancellation shows whether the orders share
ONE timestamp (a sweep) or differ (independent events wrongly described as one
phenomenon). That question is now answerable; it was not before.

**`marketMetadata` IS A MISS — IT CARRIES NO MARKET STATE.** The full object fits
inside the 240-char bound: `{slug, icon, title, outcome, eventSlug, eventId}`.
Pure display metadata. **The market-state hypothesis cannot be tested from the
order payload at all.** Do not re-add this field expecting state — the state
proxy is `orderable` on the SLATE row, a different read in
`polymarket_us_markets` (held by `live-venue-order-placement`).

The bound did not hide it: the value came back UNCLIPPED, and that was checked
rather than assumed.

**Incidental, and it bears on the time-to-event hypothesis:** resting orders DO
fill, on very different timescales — `nfl lar-lac` at +67 minutes,
`sea-juv-par` at under 4.


**NEXT, CHEAP:** log `lastTransactTime` (exact transition time), `marketMetadata`
(market state -- the leading remaining explanation) and `intent`. Log-only, same
ORDER_STATE line, one deploy.


WHAT REMAINS: cancellations are SPORADIC EVENTS, not a rule. Three transitions in
12h, one of which took FOUR orders at once (18:18:51) with no restart in the
surrounding logs. That batch is now the whole remaining thread — a simultaneous
multi-order cancel is a session- or account-level action, not a per-order one.

Superseded, kept for the record:
**THE DECISIVE FIELD IS `goodTillTime`, AND WE NEITHER SET NOR LOG IT.** We send
`tif=TIME_IN_FORCE_GOOD_TILL_CANCEL` and no expiry, so the venue applies its own
default. It RETURNS `goodTillTime` on every order — `ORDERS_READ` prints the KEY
NAMES only, and `ORDER_STATE` logs cum/leaves/avgPx but not this. One line added
to `ORDER_STATE` would settle it. `polymarket_us_orders.py` is claimed by
`polymarket-yes-leg-binding`, so it needs that lane or an override, plus a deploy.

## [polymarket-resting-orders-do-not-encumber-cash] 2026-08-31T15:45Z — CONFIRMED by a before/after pair, after I doubted it

**The claim under test:** "an unfilled order holds no reserved funds", used as
the argument that placing early costs only CHURN, never capital. It rested on a
balance that was flat at $87.26 across a cancellation — weaker evidence than it
sounded, because a cancellation restoring funds looks identical to funds never
having been taken.

**The doubt:** the user's order screen showed Cash $75.55 against Portfolio
$89.95 with $10.09 of pending orders sitting in the gap.

**THE MEASUREMENT — the same instant either side of two real submits:**

    15:25:23Z  VENUE_BALANCES polymarket=ok:75.56   BEFORE both explores
    15:25:43Z  SUBMIT bal-col  $1.10
    15:25:45Z  SUBMIT ast-ars  $8.99
    15:42:16Z  VENUE_BALANCES polymarket=ok:75.56   AFTER, unchanged

$10.09 of NEW resting orders moved spendable capital by **$0.00**. The gap on
the screen is position value and reconciles exactly: 75.55 + 14.40 = 89.95.

**WHY THIS READING IS THE RIGHT ONE.** `venue_balances.py:372` sets
`spendable = buying_power if buying_power is not None else current`, and
`buyingPower` is the venue's own "unencumbered capital available for trading".
Encumbrance is precisely what that field would express, and it did not move.

**SO CHURN REALLY IS THE ONLY COST OF A RESTING ORDER**, and the pregame hold is
justified by duplicate-exposure risk alone — never by tied-up capital. Anyone
arguing the hold saves money is arguing something this measurement refutes.

## [polymarket-price-gate-leaks-by-crossing] 2026-08-31T16:05Z — FIXED AND DEPLOYED. The ceiling used to be checked against a price the venue never receives

**VERIFIED BY CODE TRACE, not by inference:**

    execute_portfolio.py:498   gate  _polymarket_hold_price(request, venue)
                               reads planned_probability(request.requested_price)
    execute_portfolio.py:1816  submit _polymarket_resolve_market(request)
                               applies crossing (+N ticks) THEN snap direction="up"

The gate runs ~1300 lines EARLIER than price resolution. Both crossing and the
snap round UP by design, so **the submitted price is systematically higher than
the price the ceiling was tested against.** Measured on the two live explores:

    gate saw   0.444 / 0.441      (logged in EXPLORE_PREGAME_BOUNDARY)
    venue got  0.45  / 0.45       (SUBMIT ... price={'value': '0.45'})

**CONSEQUENCE 1 — the ceiling is NOMINAL.** A planned 0.349 against a 0.35
ceiling passes the gate and is submitted at ~0.355+. There is no price at which
the gate actually bounds what is bought; it bounds an intermediate value.

**CONSEQUENCE 2 — every HELD/EXPLORE price in the logs is the WRONG NUMBER to
reason from.** Anyone deriving a boundary from those lines is reading planned
prices and attributing them to orders that rested at a higher price.

**NOT CURRENTLY MOVING A DECISION, and that is luck, not design.** The overshoot
is one tick, and 0.349 -> 0.36 stays inside the unobserved gap 0.335..0.410, so
no hold/place call flips today. The moment the ceiling is tuned NEAR the real
boundary — which is the whole point of the exploration arm — the leak lands
exactly where it does damage.

**FIXED `34d43512`, live 15:50:18Z.** `_polymarket_submit_price` resolves through
the SAME `_polymarket_resolve_market` placement uses, so there is no second copy
of the venue's rounding to go stale. Every `None` path — unresolvable side, stale
artifact, `_SlippageExceeded` — means "cannot tell" and PLACES, because the real
path refuses each by name moments later. The raise is caught deliberately: the
gate's call site does not handle it, so an escape would abort the placement loop
for every remaining position on the tick.

**VERIFIED by branch assertion:** `submit_price=` exists only in the new code and
appeared 4x at 15:53:26Z. HELD/EXPLORE now log `submit_price=` for the same
reason — the old field was a planned price attributed to an order resting higher,
and I reasoned from it wrongly once.

**FIX IS NOT "subtract a tick".** The gate must evaluate the price that will be
submitted, which means resolving tick/cross BEFORE the gate or applying the same
arithmetic in it. Anything else re-derives the venue's rounding by hand and goes
stale the next time tick size changes.

## [polymarket-soccer-h2h-bought-the-OPPOSITE-team] 2026-08-31T21:25Z — FIXED AND DEPLOYED on both services; the positive case is UNVERIFIED

**USER-REPORTED, LIVE MONEY.** Two orders bought the other team.

    atc-lal-osa-get   board "Getafe @ CA Osasuna", bet HOME -> bought GETAFE
                      Osasuna WON, the bet LOST.  -$5.96 realised
    atc-sea-ata-bol   board "Bologna @ Atalanta BC", bet HOME -> bought BOLOGNA
                      STILL OPEN on the wrong side. No deploy unwinds it.

**CAUSE.** `parse_slug` documents `<away>-<home>` and applies it to EVERY sport.
MLB really is away-first (`aec-mlb-bal-col` reports away_index=1 = Baltimore and
`bal` leads); both soccer fixtures are HOME-first. `_subject_is_side` checked
`subject == parsed[wanted]` FIRST and returned True. Its "definitive NO" guard
reads the SAME inverted parse, so it CONFIRMED the wrong answer rather than
contradicting it — two checks, one shared broken input. The alias check that
answers all four legs correctly sat below both and never ran.

**BLAST RADIUS EXACTLY 2**, by enumerating all 69 distinct Polymarket slugs
submitted in log retention: the other 67 are totals or team-named markets that
never route through the subject test.

**FIXED.** `8876b823` — the board's own team names decide, refusing when the
subject names both or neither; the positional parse is gone from this decision.
`d04d9f49` — `execute_portfolio` was handing that test the SLATE row, and
`_SLATE_STORAGE_FIELDS` has no team names, so alone it would have refused EVERY
soccer moneyline: fail-safe and silently dark.

    live-odds-worker  d04d9f49  live 21:02:07Z
    refresh-worker    8876b823  live 21:20:36Z  (ancestry-checked on the RUNNING
                                commit; deployed by `layer2-cap-raise`, not me)

**`parse_slug` IS NOT CHANGED.** Its orientation is still used for FIXTURE
matching, where both teams are present and the roles do not decide which game is
found. Anyone touching it should know the soccer orientation is inverted.

**VERIFIED: only the NEGATIVE.** The wrong-side path cannot execute — first tick
after showed `positions=4 placed=0 skipped=4`, MLB `YES_LEG agree=True`, zero
`POLYMARKET_SIDE_REFUSED`. **NO soccer h2h has resolved since either deploy**, so
a correct leg being selected and placed has NOT been observed. Tomorrow's slate.

**AND IT CONFOUNDS THE FILL EVIDENCE.** Two of the three pregame fills cited all
day as "cheap sides fill" (0.240, 0.250) ARE these wrong-side orders — cheap
BECAUSE they were away underdogs. The `ast-ars` confirmation stands alone; the
sample around it was thinner and dirtier than it was presented.

## [polymarket-two-dimensional-rule-PARTLY-CONFIRMED] 2026-09-01T01:20Z — the PREGAME half is solid on two probes; the LIVE half rests on ONE and is NOT replicating

**THE FIRST DELIBERATE TEST OF THE RULE, AND IT PASSED.** `ast-ars` was placed ON
PURPOSE at a price the rule predicted could not fill, to try to break it.

    created      15:25:45Z   pregame, submit_price 0.45
    kickoff      19:02:22Z   (hours_to_commence=1.5 @ 17:32:22Z)
    lastTransact 19:20:09Z   FILLED, kick+17m47s
    avgPx        0.4500      exactly the limit, no price improvement
    cum          19.97/19.97 leaves=0, complete fill
    ledger       RECONCILED submitted->filled fill_price=0.45

**PREGAME: ~20 book reads over 3h54m, cum=0 throughout, zero partials.
LIVE: filled inside 18 minutes.** `bal-col` is still resting and still pregame
(kickoff ~00:45Z), which is the control and it behaves.

**THE PRICE RULE IS NOT REFUTED.** It did NOT fill pregame at 0.45, well above
the 0.410 top of the observed resting range. The ceiling does not move on this.

**AND THE BIG ONE: THE HELD POPULATION IS DEFERRED, NOT FORFEITED.** The gate's
cost was recorded hours ago as "a bet that ~11.5% mean EV across six positions is
unreachable". That framing is now WRONG in the good direction: a held order
places once `hours <= 0` and fills like this one did. The EV is not thrown away.

**BUT DO NOT READ THIS AS A WIN FOR THE GATE — IT WEAKENS THE CASE FOR IT.**
This order was PLACED EARLY and nothing bad happened: no churn, no cancel, no
duplicate, and it filled at exactly its limit. Meanwhile the price it locked was
0.45 while the same market read 0.460 at 17:32Z, so placing early plausibly beat
placing at kickoff by ~1c on 19.97 shares. One instance, and the earlier drift
measurement was 3 up / 2 down / 2 flat with mean +0.005 — no systematic
direction. The honest position: the gate prevents duplicate exposure (a real,
measured $9.12 incident) and buys nothing else that this fill demonstrates.

**WHAT IS STILL UNMEASURED:** whether the model was RIGHT. `ev_pct=22.68` on this
position is the model's own claim. The bet settles with the match.

**REVISED, and this DOWNGRADES what I recorded at 19:25Z.** I wrote "the rule is
CONFIRMED" on ONE probe. The second probe is not behaving the same way.

    ast-ars  EPL totals   rested 3h54m pregame, FILLED kick+17m47s @ avgPx 0.4500
    bal-col  MLB h2h      rested 9h13m pregame, STILL RESTING at pitch+35m

`bal-col` reads at pitch -15/-10/-5/0/+5/+10/+15/+20/+25/+30/+35, every one
`cum=0 leaves=2.44`. `lastTransact` never moved off its 15:25:43Z submit.

**WHAT IS SOLID: the PREGAME half.** Two deliberately-placed probes at 0.45, ~20
book reads each, zero fills, zero partials, across two sports and two markets.
Near-even pregame orders do not fill. That is now well-supported.

**WHAT IS NOT: the LIVE half.** "Once live, everything fills" rests on ONE
observation (`ast-ars`) plus 8 earlier settled orders that were ALREADY under way
when observed — never a probe placed pregame and watched through the transition.
`bal-col` is exactly that probe and it is not filling.

**A DEADLINE WAS NEVER PART OF THE RULE.** `ast-ars` filling at +18m does not
make +35m late for a different market. This is a divergence in progress, not a
refutation. But the rule cannot be stated as general until it is qualified by
sport or market, or `bal-col` fills.

**CANNOT INDEPENDENTLY CONFIRM LIVENESS.** `gameStartTime` is ABSENT on all 10
`bal-col` slate rows (same class as the documented `line: None` gap), so "live"
here means only the board's `commence_time` — two readings agreeing on ~00:38-40Z
(`7.1h @ 17:32Z`, `5.2h @ 19:28Z`). If that value is wrong, the game is not live
and none of this is a live-window observation at all.

## [polymarket-held-population-is-6-of-6-POSITIVE-EV] 2026-08-31T17:33Z — the gate suppresses positive-EV bets; its whole defence is that they cannot fill

**FIRST MEASUREMENT OF WHAT THE HOLD COSTS.** `9d0fcb11` stamps `ev_pct` on every
gate line (live 17:28:43Z); the first tick after it, 17:32:20-22Z:

    ticker                       submit  ev_pct  edge_pct
    tsc-epl-ast-ars-2pt5          0.460   22.68     6.80
    aec-mlb-nyy-laa               0.465   16.32     2.45
    aec-mlb-det-min               0.470   14.03     2.29
    tsc-mlb-det-min-8pt5          0.460    8.14     8.64
    aec-mlb-mia-wsh               0.495    4.82    11.52
    tsc-mlb-bal-col-10pt5         0.465    3.27     2.51

    EXECUTED positions=8 placed=0 skipped=6 refused={'pregame_price_too_high': 6}
             duplicates=2   (the two resting experiments)

**6 of 6 POSITIVE. Mean +11.5% EV.** Unweighted — the log does not carry stake,
so this is per-position and NOT the dollar-weighted number.

**WHAT THIS DOES AND DOES NOT SAY.** It does NOT say the gate is wrong. EV is
only realisable if the order FILLS, and the gate's entire premise is that these
do not fill pregame — 8 resting observations, zero pregame fills above 0.410. If
that premise holds, suppressing them costs nothing and the +11.5% is unreachable
paper EV.

**BUT THE PREMISE IS NOW LOAD-BEARING IN DOLLARS, NOT JUST IN TIDINESS.** Before
this reading the hold looked free — churn avoidance. It is not free: it is a bet
that ~11.5% mean EV across six positions is unreachable. If the kickoff
experiment shows these fill, the gate is expensive and the ceiling must move.

**DO NOT TREAT `ev_pct` AND `edge_pct` AS THE SAME RANKING.** They disagree
sharply and consistently — `nyy-laa` is 16.32 EV on 2.45 edge, `mia-wsh` is 4.82
EV on 11.52 edge. They measure different things (return per stake vs probability
edge in points). Whichever one a decision uses must be named.

**AND EV HERE IS THE MODEL'S OWN CLAIM.** It is `ev_pct` off the plan position,
not a realised result. Nothing in this section is evidence the model is right —
today's six settle overnight and that is the first honest scoring.

## [polymarket-explore-arm-FIRING] 2026-08-31T16:05Z — the arm fired, STALLED on a float edge, and fires again; the falsifier is live

**`e8392f1b` live 15:21:40Z at rate 0.5. First tick after rollout:**

    EXPLORE  aec-mlb-bal-col-2026-08-31       0.444  +9.3h   rate=0.5
             tsc-epl-ast-ars-2026-08-31-2pt5  0.441  +3.6h   rate=0.5
    HELD     mia-wsh 0.485 │ nyy-laa 0.461    (both ABOVE the 0.45 band edge)
    EXECUTED positions=6 placed=2 filled=0 duplicates=2 skipped=2

`rate=0.5` appears in the log line itself, so the new code RAN — asserted by
branch, not by deploy state. The two held are correctly outside the band; the
two explored are correctly inside it. `ast-ars` drifted 0.450 -> 0.441, which is
what brought it into range.

**THESE TWO ORDERS ARE THE LIVE FALSIFIER.** Both are priced ABOVE 0.410, the
top of the observed resting range, and both were placed ON PURPOSE. The rule
says they will rest.

    EITHER FILLS  -> the rule is refuted, 0.35 is too low, and the ceiling must
                     be re-derived from where the fill landed.
    BOTH REST     -> the ordering survives its first deliberate test and n grows
                     from 3.

**READ THEM AS EXPLORATION, NOT AS ORDINARY FILLS.** They were selected BECAUSE
the rule predicts they fail. Pooling an exploration fill with an ordinary one
would corrupt exactly the measurement the arm exists to produce — that is why
the line is logged distinctly.

**AND STILL: A FILL HERE IS NOT PROFIT.** These are near-even sides chosen to
test a boundary, not because they are good bets. Whatever they do, the EV
question is separate and unanswered.

**CORRECTION, and it is why "the arm is firing" was not enough.** It fired twice
at 15:25Z and then STALLED. `0.35 + 0.10` is `0.44999999999999996`, so a 0.450
order fell outside a band whose configured top is 0.45. LATENT ALL DAY and made
reachable by the submit-price fix: planned prices (0.441, 0.444) are arbitrary
and never land on the edge, while SUBMIT prices are snapped to the tick and land
on round boundaries constantly — 0.45 is exactly where a 0.44 or 0.445 quote
crosses to. The arm's single most probable price was the one it could not place.
Fixed `3db201bc`, live 15:59:13Z; verified 16:03:16Z, `EXPLORE bal-col
submit_price=0.450`, with 0.460/0.465/0.490 correctly held.

**THE EXPERIMENTS, as of 16:20Z:** both rest at 0.45, `cum=0`, full `leaves`,
across FIVE independent book reads. The pregame price rule holds on its first
DELIBERATE test — the evidence moved from 3 passive observations to 5, and from
observed to probed. Kickoff is the decisive reading: `ast-ars` ~18:57Z,
`bal-col` ~00:45Z.

## [polymarket-explore-arm-too-slow] 2026-08-31T15:11Z — the arm is LIVE and CORRECT, and its sample rate is close to zero

**Deployed `b6c02dff`, live 15:07:47Z. First tick: `EXPLORE_PREGAME_BOUNDARY 0`,
and that is arithmetic, not a fault.**

    HELD    0.485  0.465  0.461  0.450        band = 0.35 .. 0.45
    -> only ONE of four is inside the band, and at rate 0.10 one order explores
       10% of the time.

**AND DETERMINISM MEANS IT NEVER RE-ROLLS.** Assignment is
`sha1(position_key)`, deliberately, so the same position gets the same verdict
forever — that is what stops the churn. The consequence is that the arm samples
**new POSITIONS, not ticks**: repeating a held order every 5 minutes gives no
extra chances. With a handful of new boundary positions a day at 10%, this
yields roughly **one exploration order every several days**.

**So the falsifier is alive but nearly static.** Better than the
self-confirming gate it replaced, and far short of what re-deriving a threshold
needs.

**TWO TUNABLE FIXES, neither applied:**
  - **RAISE THE RATE.** 0.10 was picked for a large population; the real
    boundary population is 1-3 positions per tick. 0.25-0.50 would sample
    meaningfully at a still-bounded cost, since the cost is churn and not stake.
  - **WIDEN THE BAND** past 0.45. Weaker: 0.46-0.49 has been observed resting
    repeatedly, so it buys churn for information already held.

**Prefer the rate.** `SYNDICATE_POLYMARKET_EXPLORE_RATE`, and on Render an env
change needs a deploy either way.

**ALSO OBSERVED, unrelated and pre-existing:** `POLYMARKET_US_SLATE
status=skipped reason=sports_routes_404_on_this_host_measured_2026-08-24`. It is
NOT blocking the order path — `ORDER_PATH` and `EXECUTED` both ran this tick —
but if the slate ever stops refreshing, price resolution refuses on staleness and
the symptom looks identical to a dead arm.

## [polymarket-gate-is-self-confirming] 2026-08-31T13:42Z — THE GATE DESTROYED ITS OWN FALSIFIER

**Asked whether `sf-atl` (pregame, ~0.400, the closest observation to the
boundary) ever filled. IT WAS NEVER PLACED — the gate held it.** There is no
order, so there is no answer, and there never will be while the gate runs.

    tracked orders now: 5, ALL FILLED, resting: NONE
      0.210 juv-par(past)  0.240 ata-bol  0.250 osa-get
      0.335 ath-tex        0.490 lar-lac(past)

**Every surviving order fits the rule perfectly, and that is exactly what a
self-confirming filter looks like.** The stated falsifier is "a PREGAME FILL
above 0.410" — but near-even pregame orders are the ONLY population that could
produce one, and the gate suppresses all of them. The evidence base is now
frozen at n=3 pregame fills and cannot grow.

**THIS IS A DESIGN DEFECT, NOT A DATA GAP.** The 0.35 ceiling was chosen as a
risk decision pending more evidence, and the gate as built guarantees that
evidence never arrives. Any threshold in 0.335-0.410 will look correct forever.

**THE FIX IS AN EXPLORATION ARM.** Let a small, bounded fraction of near-even
pregame orders through — a holdout — so the boundary keeps being tested at a
known, capped cost. Without one, the rule cannot be re-derived and the
"re-derive as the gap fills in" note in `_polymarket_max_pregame_price` is
unachievable by construction.

**NOT BUILT. Flagged only.** It is a live-money selection change and this
session has already deployed one gate on a hypothesis that died within the hour.

## [polymarket-cheap-side-selection-risk] 2026-08-31 — HIGHER FILL VOLUME IS NOT SUCCESS. The gate changes the BET MIX.

**Raised by `polymarket-yes-leg-binding` and it is the most important
consequence of the price gate, not a footnote.**

The rule places cheap pregame sides and holds near-even ones. That is not a
neutral execution filter — **it is a SELECTION CHANGE**. It systematically
shifts what we bet toward LONGSHOTS, because those are the sides with a book
pregame.

**Everything established tonight is about whether an order FILLS. Nothing
establishes whether a cheap pregame fill is a GOOD BET.** Those are different
questions and the 11-order sample answers only the first.

**SO DO NOT READ RISING FILL VOLUME AS SUCCESS.** A gate that doubles fills
while shifting the mix toward longshots could easily be EV-negative and would
look like progress on every count we currently print. The EV of the cheap-side
population must be scored SEPARATELY, against the closing line or realised
settlement, before this gate is judged to have helped.

**Concretely: `placed`, `filled` and fill-rate are now MISLEADING as success
metrics for this change.** The honest metric is P&L or CLV on the orders the
gate lets through, versus what the un-gated policy would have produced.

**THE CEILING IS 0.35, AND THAT IS A RISK CHOICE, NOT A MEASUREMENT.** Nothing
has ever been observed between 0.335 and 0.410; every threshold in that gap fits
the data equally. 0.35 places only what has been watched to fill; 0.41 would
place an unmeasured band on the assumption it behaves like the cheap side. Since
churn is the stated harm, it errs toward not placing. **0.37 shipped first and
was the worst available choice — the midpoint of a gap is the one value with no
evidence behind it.**

**FALSIFIER, either ends the rule:** a pregame FILL above 0.410, or a pregame
REST below 0.335. Only the ORDERING is claimed. `sf-atl` at 0.400 is the closest
live observation to the boundary.

## [polymarket-price-gate-LIVE] 2026-08-31T05:58Z — the price gate is live and holding the right population

**`0c3f102f` deployed THROUGH a preflight HOLD `[user: "deploy it through
anything running"]`.** Cost recorded rather than skipped: it killed three
in-flight jobs — `refresh_odds_sources.py`, its parent `run_refresh_odds_job.py`,
and a `build_soccer_artifacts.py --league serie_a` build. All re-run next tick.

**First tick:**

    HELD_PREGAME_NEAR_EVEN x5   mia-wsh 0.485 +16.8h │ det-min 0.455 +17.7h
                                nyy-laa 0.429 +19.7h │ lec-rom 0.481 +10.5h
                                sf-atl  0.400 +16.1h
    EXECUTED positions=8 placed=0 duplicates=3 skipped=5
             refused={'pregame_price_too_high': 5}

Every held order is near-even AND pregame — exactly the population that has
never filled across 12 observations. **Nothing cheap was suppressed**, which is
the failure mode the old time gate had.

**A PRECISION CAVEAT WORTH KEEPING.** The gate reads
`planned_probability(requested_price)`, not the venue quote, and they differ
slightly: `sf-atl` gates at 0.400 while its venue price was 0.410; `mia-wsh`
0.485 vs 0.490. The slippage guard bounds that gap at 3c, so a decision NEAR THE
CEILING could flip on which number is used. Away from 0.37 it makes no
difference; at the boundary it would.

**STILL UNVALIDATED:** the 0.37 ceiling. n=3 pregame fills, and the boundary
lies in the never-observed gap 0.335 -> 0.410. `sf-atl` at 0.400 is now the
closest observation to it — if that price ever fills, the ceiling is too low.

## [polymarket-TIME-IS-NOT-THE-VARIABLE] 2026-08-31T05:29Z — TIME-TO-EVENT IS REFUTED. The gate's premise is false.

**A PREGAME ORDER FILLED, 18.6 HOURS BEFORE KICKOFF, WITHIN ~18 MINUTES.**

    aec-mlb-ath-tex-2026-08-31   mlb h2h   kickoff 09-01T00:05Z  18.6h out  FILLED cum=5.25 @0.335
    tsc-sea-lec-rom-...-2pt5     soccer totals  kickoff 08-31T16:30Z  11.0h out  resting 1.4h
    tsc-epl-ast-ars-...-2pt5     soccer totals  kickoff 08-31T19:00Z  13.5h out  resting 1.4h

**The order that FILLED was FURTHER from kickoff than the two that did not.**
Time-to-event cannot explain that, and it was the hypothesis `f6f45321` was
built on. **The gate's stated premise — "pregame orders do not fill at any
price" — is FALSE.**

**WHAT ACTUALLY SEPARATES THEM IS THE MARKET, NOT THE CLOCK.** Filled: an MLB
MONEYLINE (`aec-`). Resting: SOCCER TOTALS (`tsc-`). Also newly placed and
resting are three more MLB moneylines (det-min, nyy-laa, sf-atl) at 16-20h, so
one h2h fill out of four is not yet a rate either — but one fill is enough to
kill "pregame never fills".

**THE GATE IS LIVE AND SUPPRESSING 13 OF 17 POSITIONS ON A FALSE PREMISE.** It
did not block this fill (18.6h is inside the 24h window), so nothing is known to
have been lost yet. But it is keyed on the WRONG AXIS, and the orders it holds
are mostly far-out SOCCER h2h — a market family we have never seen fill at any
horizon, which is a different reason from the one written into the code.

**RECOMMENDED: disable it** (`SYNDICATE_POLYMARKET_MIN_HOURS_TO_COMMENCE=0`, or
revert `f6f45321`) until the axis is established. On Render an env change needs
a deploy, so a revert is the faster off-switch.

**THE REAL QUESTION IS NOW LIQUIDITY BY MARKET FAMILY:** do soccer `tsc-` totals
EVER fill, at any horizon? Every fill on record is MLB or NFL. If soccer totals
never fill, the fix is not timing at all -- it is not offering them.

## [polymarket-placement-hold] 2026-08-31 — LIVE, and it holds 13 of 17 positions

**Deployed `f6f45321`, live 04:36Z. First tick:**

    EXECUTED positions=17 placed=0 duplicates=2 retried=2 skipped=13
             refused={'too_early_to_place': 13}

    held: 38.1h, 86.4h, 129.4h, 129.4h, 131.4h, 131.9h ... (threshold 24.0h)

**NOTHING BORDERLINE IS CAUGHT.** Every held order is 38h+ out; the 0-24h window
is untouched, which is the design. But **13 of 17 is a large suppression** and it
is the dominant refusal on the venue now — that is a real behavioural change, not
a marginal one.

**AND IT INTERACTS WITH THE YES-LEG FIX.** Almost every held order is an `atc-`
**h2h** market — the moneylines `8b0d27df` unblocked earlier today. Opening h2h
produced a large set of far-future soccer moneyline candidates, and this gate is
now holding them. Neither change is wrong; the combination is what produces
`placed=0`, and reading either one alone would mislead.

**WHY HOLDING THEM IS RIGHT ON THE EVIDENCE:** pregame orders do not fill at any
price we have tried (quote, and a tick above), while 8 of 8 fills came on
live-or-past markets. An order 5 days out cannot fill and only buys the
submit -> cancel -> resubmit churn that produced the $9.12 duplicate.

**WHAT WOULD MAKE THIS WRONG, and how it would show:** if far-out orders DO fill
given enough time, this suppresses real bets. The test is already running for
free — `lec-rom` and `ast-ars` sit live at 0.49 with kickoffs ~12h out, inside
the window and therefore still placed. If they fill near kickoff and nothing
ever fills far out, the gate is justified and 24h can be tuned from evidence
instead of judgement.

## [polymarket-crossing-RESULT] 2026-08-31 — CROSSING DOES NOT HELP. Price is not the constraint pregame.

**THE EXPERIMENT RAN PROPERLY AND ANSWERED.** The user cancelled the three
resting orders on the venue, freeing their position keys; the next tick
re-placed all three ONE TICK ABOVE the quote:

    04:07:01  tsc-sea-lec-rom-2026-08-31-2pt5  0.49  (quote 0.48)  kickoff ~12h
    04:07:06  tsc-bun-scp-scf-2026-09-05-2pt5  0.46  (quote 0.45)  kickoff 5 DAYS
    04:07:08  tsc-epl-ast-ars-2026-08-31-2pt5  0.49  (quote 0.48)  kickoff ~12h

    EXECUTED positions=17 placed=3 filled=0 duplicates=0

**AND THEY STILL DID NOT FILL** — reported by the USER from the venue's own
Orders screen. That is the tenth eliminated cause: **PRICE**.

**WHAT IT MEANS.** We bid the quote: rests. We bid a tick above: rests. On the
same markets, at two prices, pregame. The book is not there at any price we have
tried. Combined with 8 of 8 fills occurring on LIVE-or-PAST markets and 3 of 3
pregame orders resting, **time-to-event is now supported by a direct experiment
rather than by correlation alone.**

**THE FIX IS PLACEMENT TIMING, NOT PRICING.** Nothing in the pricing path is
wrong: the tick snap is a no-op on on-grid quotes, the slippage guard gates the
sent price, the quote is a real ask (sums 1.005-1.030), and crossing it changes
nothing.

**HONEST LIMITS, because this was ~15 minutes:**
- One tick may be too small. The dial reaches 3 (`SYNDICATE_POLYMARKET_CROSS_TICKS`).
- `nfl lar-lac` once took **67 minutes** to fill, so a short no-fill window is
  suggestive, not proof.
- Two fixtures are ~12h out and one is 5 days; none is near kickoff, which is
  exactly the regime the hypothesis says DOES fill.
- The clean confirmation is free and arrives on its own: if these same orders
  fill as their kickoffs approach, time-to-event is settled outright.

**CALIBRATION GAINED FOR FREE.** The user's three cancels produced DISTINCT
`lastTransactTime` values 0.66-0.82s apart, spanning 1.47s. So a real
multi-order cancel action looks like sub-second-spaced DISTINCT timestamps, not
one shared one — the yardstick that was missing when the 18:18:51 "four at once"
claim had to be withdrawn as unverified.

## [polymarket-crossing-experiment] 2026-08-31 — LIVE and CORRECT, but it has no test case yet

**Deployed `0fc174c6`, live 03:48:28Z. It fired on all three pending orders at
03:50:47:**

    tsc-sea-lec-rom-2026-08-31-2pt5  quote=0.48 snapped=0.48 crossed=0.49  tick=0.01
    tsc-bun-scp-scf-2026-09-05-2pt5  quote=0.44 snapped=0.44 crossed=0.45  tick=0.01
    tsc-epl-ast-ars-2026-08-31-2pt5  quote=0.48 snapped=0.48 crossed=0.49  tick=0.01

**AND NOTHING WAS SUBMITTED.** `EXECUTED ... positions=17 placed=0 filled=0
duplicates=3 retried=13`. The three resting orders HOLD THEIR POSITION KEYS, so
each crossed price was computed and then discarded as a duplicate. Predicted
before the deploy, and it is why the run is INCONCLUSIVE rather than negative.

**THE CODE IS PROVEN; THE HYPOTHESIS IS NOT TESTED.** Crossing arithmetic is
confirmed correct on three real orders. Whether a crossed price FILLS is still
unknown, because no crossed order has ever reached the venue.

**TO GET THE READING — cancel the three resting orders.** The venue's own Orders
screen has a Cancel button per row (user screenshot). Cancelling frees the
position keys, and the next tick re-places them at 0.49 / 0.45 / 0.49 instead of
0.48 / 0.44 / 0.48. Then:
    fills   -> size sits one tick above; PRICE was the problem
    rests   -> no book exists pregame; the fix is placement TIMING, not price

A `cancel_order` adapter exists (`3170db13`) and is NEVER CALLED, so this is a
human action tonight, not an automated one.

**DIAGNOSTIC THAT EARNED ITS KEEP:** the watcher logged `price evals since
deploy=0` for the first three checks. Without that counter, three minutes of
silence would have read as "crossed and did not fill" when the order path simply
had not ticked since the reboot.

## [polymarket-pregame-orders-rest] 2026-08-31 — THREE pending orders, ALL pregame, ALL bid AT the quote

**USER SCREENSHOT of Polymarket's own Orders screen, 03:2xZ**, corroborated
against our logs. Three PENDING, every one a SOCCER TOTAL on a fixture that has
not kicked off:

    Buy Over 2.5   Aston Villa v Arsenal   17.37 @ 48c   $8.34   Until Cancelled
    Buy Under 2.5  US Lecce v AS Roma       5.97 @ 52c   $3.10   Until Cancelled
    Buy Over 2.5   SC Paderborn v Freiburg 27.97 @ 44c  $12.31   Until Cancelled

**"Until Cancelled" is the venue's own UI confirming `goodTillTime=None`** —
independent corroboration of the API measurement.

**WE ARE BIDDING EXACTLY THE VENUE'S QUOTE, not under it.** Measured at our last
evaluation of each:

    tsc-sea-lec-rom-2026-08-31-2pt5   quote 0.48  sent 0.48  snapped=False  Under
    tsc-bun-scp-scf-2026-09-05-2pt5   quote 0.44  sent 0.44  snapped=False  Over

The 52c shown for lec-rom is the NO-side display complement of our 0.48, not a
different price. All three orders ARE tracked in our ledger (the third is
`tsc-epl-ast-ars-2026-08-31-2pt5`, order C6SRM9D8MKDN) — no ledger gap.

**THE PATTERN IS NOW CONSISTENT ACROSS EVERY ORDER WE HAVE OBSERVED:**

    PREGAME market   ->  rests, cum=0, never touched   (3 of 3 pending)
    LIVE/PAST market ->  fills                          (8 of 8 settled)

That is the peer's TIME-TO-EVENT hypothesis, and it has survived every test that
killed the others: tick floor, stale ask, bidding a mid, our own cancel loop,
market close, venue expiry, insufficient collateral, restart/OOM, deploy.

**STILL INFERENCE, AND THIS IS THE LIMIT:** we cannot see the order BOOK. The
slate gives ONE price per outcome, not depth. "The quote exists but no size sits
behind it pregame" explains everything observed and remains untested, because
nothing we have reads depth.

**THE EXPERIMENT THAT WOULD SETTLE IT** is a live-money change and needs a
decision: bid ONE TICK ABOVE the quote on pregame markets. If size exists just
above, it fills; if nothing fills at any price pregame, the market genuinely has
no book yet and the fix is placement TIMING, not price.

## [polymarket-fill-time-to-event] 2026-08-30 — the leading hypothesis is TIME TO EVENT, not liquidity at our size

**Raised by `polymarket-yes-leg-binding` off the `ORDER_STATE` instrument, and it
is better than my own.** n=2 resting vs 8 settled, and the separation is on the
market's DATE, not its price:

    RESTING (2, both cum=0 NEVER TOUCHED)   2026-08-31 and 2026-09-05
    SETTLED (8)                             7 past, 1 today

Confirmed against the board: `tsc-sea-lec-rom-2026-08-31-2pt5` is ROM@LEC
starting 2026-08-31T16:30Z, and `tsc-bun-scp-scf-2026-09-05-2pt5` is SCF@SCP
starting 2026-09-05T13:30Z — **both PREGAME**, one five days out. Every fill was
on a live-or-finished market. A Bundesliga total five days away plausibly has no
resting size because nobody is trading it yet.

**This fits my own counter-example better than size does.** `sea-tor` filled
11.17 at 0.435 while `lad-det` rested at 10.66 — near-identical size, opposite
outcome, which "no liquidity at our quantity" cannot explain and time-to-event
can.

**AND I CAN NO LONGER TEST IT ON THAT PAIR.** Both MLB fixtures have aged off the
board, the same way KC@CLE did, so their kickoff times are unavailable. That
check is gone; it needed to be run while they were live.

**MY LIQUIDITY HYPOTHESIS IS NOT DEAD, IT IS CONFOUNDED.** Every untouched order
in this sample is on an unplayed market, so the sample cannot separate the two.
n=2 is not a rate and neither of us is claiming it is.

**THE DISCRIMINATING TEST, needing no new code now `ORDER_STATE` is live:**
bucket `cum==0` resting orders by HOURS TO COMMENCE. If never-touched
concentrates far from kickoff and fills concentrate near it, the fix is WHEN we
place, not what we price. **If untouched orders appear at t-30min too, the
liquidity story survives and time-to-event is dead.** Run it on a full slate, not
on tonight's two.

**IF IT HOLDS, it reframes the original complaint** ("barely placing orders, and
the ones placed aren't processed"): we would be placing into books that do not
exist yet, and the remedy is placement timing rather than pricing, sizing, the
venue join, or the tick logic — all four of which have now been eliminated by
measurement.

## [polymarket-order-fills] 2026-08-30 — four causes REFUTED; fills are mostly fine

**5 of 7 Polymarket orders FILLED today.** The two that did not (`lad-det`,
`phi-laa`) ended `order_state_canceled` with 0 contracts — CANCELLED, not
resting. The premise "we bid the ask and never fill" was overstated.

**Four proposed causes are refuted by measurement, not argument:**
- tick-size floor — 12 of 12 quotes on-grid post-deploy, snap never fired. The
  submit-time quote for `lad-det` was 0.51 and we sent 0.51; the 0.515 was read
  30 minutes later. My claim, retracted. The fix is a NO-OP and stays only
  because the slippage guard now gates the SENT price.
- stale ask — 44s old at submit.
- bidding a mid — `prices[]` sums 1.005–1.030 over 8 binary markets: an ASK.
- "orders rest forever" — they are cancelled, not resting.

**Still unexplained:** why two orders were cancelled. `ORDER_STATE` logging of
`cumQuantity`/`leavesQuantity` shipped (`bf1dd290`) and HAS NOT BEEN READ yet.
That is the next reading.

**Why the board is game-totals only** — four separate limits, only one now lifted:
- h2h: FIXED by `8b0d27df`, verified live 19:54:08 (`yes_leg_index=0 agree=True`).
  Not yet proven to pick the right SIDE — `yes_leg_index=0` equals the old
  positional answer; the discriminating case needs `yes_leg_index=1`.
- props: refused BY DESIGN in `polymarket_board_join.py` — a prop priced by a
  guessed player token is a real order on the wrong person.
- spreads: **THERE IS NO SPREAD DEFECT. The question was malformed and the error
  was mine.** I said "71 board spread rows reach ORDER_PATH zero times" and built
  a day of tracing on it. Those 71/65 come from `SPREAD_SIGN_AUDIT`'s
  `board_spread_rows`, which counts ODDS-BOARD rows (of `board_rows=1230`) across
  all sports. They are NOT portfolio candidates.
  MEASURED 2026-08-30T21:25Z on `/api/portfolio/live?all_dates=1`, unfiltered:
  the ENTIRE portfolio holds **1 spread row** -- mlb, `KC@CLE away 2.5`, venue
  KALSHI, ticker `KXMLBSPREAD-26AUG301340KCCLE-CLE3`, and it PLACED AND FILLED.
  All markets in the portfolio: totals 12, earned_runs 4, spreads 1, and one each
  of four prop types.
  So the portfolio selects almost no spreads, and the one it selected succeeded.
  That is a SELECTION outcome (edge/threshold), not a plumbing failure, and no
  part of the venue join, the tick logic or the order path is implicated.
  A cheap follow-up IF spread volume is wanted: ask why the ranker emits ~1
  spread candidate a day against 65 board rows. That is a modelling question.
- spreads, SUPERSEDED TRACE (the join mechanics below are accurate; both
  conclusions I drew from them were not). Earlier "the join never matches them"
  was WITHDRAWN
  -- it rested on ONE fixture that had already left the slate.
  KC@CLE started 18:40Z. Its TOTALS resolved fine at 19:05/19:10/19:17Z, and the
  spread `no_venue_ticker` drops are all 19:33-20:24Z, i.e. AFTER it aged out.
  Confirmed 21:15Z: `?slug=kc-cle` now returns `matched=0` for spreads AND for
  totals AND for h2h -- the whole fixture is gone, so a zero there says nothing
  about spread coverage. The TOTALS control is what caught this; without it the
  zero reads as "the venue lists no spread".
  A game that has started dropping out of the slate is CORRECT behaviour, so
  there may be no spread defect at all.
  WHAT IS ESTABLISHED: the venue carries orderable, correctly-signed MLB spreads
  for LIVE fixtures -- `asc-mlb-lad-det-2026-08-30-neg-1pt5 line=-1.5
  orderable=true`, plus pos-1pt5/neg-2pt5/pos-2pt5 (`?slug=lad-det` -> matched=4,
  which also proves the filter works).
  TO SETTLE IT: catch a board spread row and a live venue fixture at the SAME
  moment. No Polymarket-scoped spread reached ORDER_PATH in the 90 min to 21:10Z,
  so it could not be tested then. The tooling now exists and is verified.
  (Superseded detail below is kept only for the join mechanics it records.)
- spreads, ORIGINAL TRACE (mechanics still valid, CONCLUSION withdrawn):
  The venue carries 200 `mlb|spreads` (1,900 spreads overall, from
  `/api/ops/polymarket/slate`). Spreads DO reach `ORDER_PATH` -- 9 times in 12h,
  correcting an earlier "zero" that came from a 6-tick window -- and every one is
  dropped `no_venue_ticker`, i.e. the JOIN produced no slug.
  `spread_side_needs_verified_team_mapping` fires ZERO times, so we never even
  build a candidate for the order-time sign gate to refuse: the drop is at the
  join's EXACT signed line match (`abs(candidate.line - board_line) > 1e-9`),
  upstream of it. `POLYMARKET_BOARD_JOIN` (refresh-worker, NOT live-odds-worker)
  matches 48 of 1197 board rows, with `no_matching_polymarket_market: 140`.
  `SPREAD_SIGN_AUDIT` -- the instrument that would settle whether the venue's
  `pos`/`neg` means home or away -- reports `fixtures=0 rate=None
  verdict=NON-IDENTIFYING` and has never identified anything.
  CORRECTION: I reported that endpoint as "aggregates only, rows:0". WRONG --
  the key is `samples`, not `markets`/`rows`, and I read the wrong field. It
  returned rows all along.
  What it could NOT do was aim: `?league=mlb&market=spreads` capped at 25
  samples in slate order, all `hou-nym`/`lad-det`/`tex-mil`, so the fixture
  being diagnosed was neither present nor absent. `?slug=` and `?limit=` now
  exist, with `matched_samples`/`samples_truncated` (`508a7e79`) -- NOT YET
  DEPLOYED, web still runs 165c448f.
  Already shown by the un-aimed sample: `asc-mlb-<fixture>-2026-08-30-neg-1pt5`
  carries `line=-1.5 orderable=true`, so a board row at `home -1.5` is NOT
  missing for want of a market at that line. The open question is now narrow and
  answerable: is the KC@CLE fixture in the venue's spread list at all? One call
  to `?league=mlb&market=spreads&slug=kc-cle` settles it once deployed.
- alt/period totals: the venue carries them (`tsc-...-1q-17pt5`); we never
  attempt them. UNTRACED.

**`not_found` latch:** live execution was halted on BOTH venues from 19:47:34Z
by one order with no venue id. Fixed correctly by `dd33c865` (per-order read;
three refusing paths keep blocking). My `63661af1` auto-reject was UNSAFE and is
reverted (`ef0d2d47`) — absent from the OPEN book is not absent from the venue.

﻿
