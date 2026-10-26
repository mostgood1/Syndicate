# PRE-REGISTRATION -- E5: do Kalshi / Polymarket move LATER than the books after availability news? (lane `e5-venue-news-lag`, 2026-10-26)

Decision Engine plan (`docs/ai_context/plan_syndicate_decision_engine.md`) §4 **E5**, §6, §8 Phase 4. OFFLINE and
read-only on production (fleet `~/syndicate-prod/data`, nice 19; Kalshi PUBLIC unauthenticated GETs only). No deploy,
restart or env edit. No LLM anywhere (user decision 2026-08-14; D4).

**Committed before any news x venue or news x book join.** What was looked at before this commit, and only this:
directory listings and file-date coverage; record SHAPES (one NBA injury file, one NHL gameinfo file, one NBA
book_quotes file, three venue_odds files); the NBA 10-25 book capture cadence (median 4.1 min between distinct
captures, p90 10.6); `book_updated_at == snapshot_ts` on 441,068 / 441,068 rows (it is OddsAPI's snapshot time,
not the book's own change time); one Kalshi prop market's and one moneyline market's rules / candlestick SHAPE
(no event time involved). No price was read at any news time.

## Facts the design rests on (read before registering)

- **Kalshi player props do NOT resolve No when the player sits.** `KXNBA3PT-26OCT25TORMIN-TORSBARNES4-3`
  rules_secondary: *"If a player is inactive, or active but never takes the court, the market settles to a fair
  price."* So a ruled-out player's own prop carries no settlement edge, and its price is already roughly
  conditional on playing. Own props are a DESCRIPTIVE arm only (below); the economic test is on game lines.
- **Our venue logs cannot time a pregame event.** `venue_daily_odds.record_daily_odds` keeps the NEWEST 48 points
  per market (OLDEST out): 1,671 of 3,822 Kalshi NBA 10-25 markets sit at the cap, with retained points starting
  on game day. So the Kalshi clock is Kalshi's PUBLIC 1-minute candlesticks (`/series/{s}/markets/{t}/candlesticks`,
  `period_interval=1`, yes_bid / yes_ask OHLC; precedent `scripts/maker_vs_taker_shadow.py`), forward-filled from
  the last candle at or before t.
- **Polymarket US publishes no price history.** Its clock is our own `venue_odds/polymarket__*` points (board-loop
  cadence 3-13 min, 48-point cap, no depth, outcome labels not stored). Polymarket is therefore a LAG + INDICATIVE
  arm, reported apart; the economic verdict rests on Kalshi.
- **Book times are capture-limited.** A book move is known only to lie in (previous snapshot, snapshot] of our
  OddsAPI capture. The 2-min kill threshold is below that resolution, so the lag is computed at both bounds (below).
- `book_quotes` carries `kalshi` as an OddsAPI bookmaker: it is a VENUE and is excluded from every book set.

## 1. Events and de-duplication

Sources: `news/<sport>/injuries/*.jsonl` (ESPN, every 10 min since 2026-10-13 19:31Z) for nba, nfl, nhl, wnba, mlb;
`news/nhl/gameinfo/*.jsonl` scratches. Unplayable = `news_availability.availability_status(status) is not None`
(Out, Injured Reserve, Suspension, MLB injured lists) -- the same set the served gate uses. Doubtful /
Questionable / Day-To-Day are playable.

- **A run** = all records sharing one `captured_at`. The first run per sport is a baseline and never an event.
- **Name-level netting (the ESPN athlete-id churn fix).** State is keyed by (sport, `team_key`, `player_key`), not
  athlete id. After applying every record of a run by athlete id, a name is UNPLAYABLE if any of its still-listed ids
  carries an unplayable status, else PLAYABLE (listed-playable or not listed). A same-run `new` + `cleared` pair for
  one name therefore nets to no change.
- **Event** = the name's playability flips between consecutive runs: playable -> unplayable = `to_out`,
  unplayable -> playable = `to_in`. t0 = that run's `captured_at`.
- **Persistence (flap filter):** the new state must still hold at the next run of that sport; otherwise dropped
  and counted `flap`.
- **t0 certainty:** if the previous run of that sport is > 25 min before t0 (host sleep), the event is counted
  `t0_uncertain` and excluded from every timing and EV measure.
- **NHL scratches:** first sighting of (game_id, player) in a gameinfo scratch list = `to_out`, t0 = that capture,
  for that game only; dropped (`flap`) if the player is absent from that game's scratch list at its last capture
  before `start_utc`.
- **One unit per team-game burst:** events for the same team and the same next game within 30 min of the first are
  merged into one unit (t0 = the earliest, sign of the kind). A burst holding both `to_out` and `to_in` is excluded
  (`mixed_burst`).
- "Confirmed in a lineup" has no source in the window except NHL scratches and `to_in` clears; it is not measured
  separately. NBA official report: `nba_source/data/raw/injuries.csv` is a DATE-granular snapshot with no report
  time, so it cannot be a t0; it is used only to report the share of NBA `to_out` units whose game-date official
  row says OUT.

## 2. Population and window

- t0 in [2026-10-13T19:31Z (after the baseline run), 2026-10-26T18:00:00Z], next game commencing in (t0, t0 + 8 d],
  game commenced by the run time (so the outcome and t_end exist). Sports nba, nfl, nhl, wnba, mlb.
- **Game identity:** the next game is the book event (`book_quotes`) for the player's team (as `news_price_follow`
  does). A venue moneyline is joined to it only when the venue event has exactly two team markets matching the book
  game's two teams (Kalshi label = city prefix of the team name, a trailing single letter must match the next word's
  initial; NHL by `team_abbreviation`). Anything else is excluded and counted `identity_refused`.
- **Unit eligibility, per venue:** the venue moneyline has a quote at or before t0 (Kalshi: a candle at or before
  t0 within 24 h; Polymarket: a recorded point in [t0 - 30 min, t0]); and >= 2 non-venue books have an h2h pair for
  the game at or before t0 within the 120 min before t0.
- **PRIMARY population = impact units:** the player had >= 1 prop line at any non-venue book, or a Kalshi player-prop
  market, for that game at or before t0 (known at t0, so implementable). ALL units are reported beside it.
- **Polymarket orientation:** our points carry no outcome label, so the team side is the orientation (yes or no)
  closer to the book consensus for the team at the last point at or before t0 - 30 min; if that consensus is within
  0.08 of 0.50 the unit is excluded (`pm_orientation_ambiguous`). Pre-treatment data only.

## 3. Measures (game moneyline of the player's team; sign s = -1 for to_out, +1 for to_in)

- **Venue price V(t):** Kalshi mid (yes_bid + yes_ask) / 2 of the team's YES market, forward-filled from 1-min
  candles; Polymarket team-side recorded price.
- **Book prices:** each non-venue book's Shin-devigged team probability (`opportunity_signals.devig(method="shin")`)
  from its latest h2h pair at or before t; consensus B(t) = the median across books that had a pair at or before t0.
- **Window:** W = min(120 min, commence - t0); t_end = min(t0 + 60 min, commence - 1 min).
- **Venue first move** tau_V = first t in (t0, t0 + W] with s * (V(t) - V(t0)) >= 0.02.
- **Book first move** tau_B = first book snapshot in (t0, t0 + W] at which any single book's own devigged
  probability satisfies s * (p(t) - p(t0)) >= 0.01. Its time is bracketed by that book's previous snapshot
  (early bound) and the snapshot (late bound); the PRIMARY value is the midpoint.
- **Lag** = tau_V - tau_B (minutes), on units where tau_B exists. tau_V absent within W -> the lag is censored at
  (t0 + W) - tau_B and enters the median at that value (a lower bound; share censored reported).
  Also reported: tau_V - t0 and tau_B - t0 distributions, and the share of the venue's t0 -> t_end move (toward
  B(t_end)) already made BEFORE t0 (V(t0) vs V(t0 - 60 min)).
- **Signed drift** D = s * (V(t_end) - V(t0 + 1 min)) for the venue, and the same for B as the reference.
- **Placebo:** the same unit, market, sign and rules started at p0 = t0 - 60 min (window 15 min, ending before the
  ESPN source time can plausibly fall). Reported: directional-move rates within 15 min (news vs placebo) and the
  placebo-adjusted EV below.
- **Own-prop arm (DESCRIPTIVE ONLY, no economic test):** the player's Kalshi prop markets for that game: share with
  a mid move >= 2c, or the yes_ask/yes_bid withdrawn, within 15 min of t0 vs the placebo window; and the books'
  share of the player's prop keys that receive a new record within 15 min. Kalshi settles an inactive player's prop
  at a fair price, so no edge is claimed from this arm in either direction.

## 4. Economic test (fee-net, at the venue's executable price)

For h in {1, 5, 15} min after t0, on the news-favoured side (s = -1: buy the team's NO at 1 - yes_bid; s = +1: buy
YES at yes_ask), with the eventual book consensus as truth q = B(t_end) for that side:

    EV_h = q / (ask_h + fee(ask_h)) - 1,   fee = venue_fees.taker_fee_per_contract(venue, ask_h, venue_ref=ticker)[0]

Reported per h: mean EV_h, share > 0, game-clustered 95% CI; the placebo EV at p0 + h on the same unit and side;
and the paired difference EV_h - EV_placebo_h (the E5 increment net of any standing E1 sharp-venue gap).
Secondary truth (noisy, reported only): the realised Kalshi `result` of the team market.
Polymarket: the same at the recorded price with the filed taker fee (`polymarket`), labelled INDICATIVE.

**CIs:** game-clustered bootstrap, 2,000 draws, seed 20261026, 95% percentile. Pooled across sports for the
verdict; per sport reported. n units, n games and n events stated on every line.

## 5. Kill rule and verdict (the plan's, made operational) -- per venue

- **KILL (timing, not edge)** if EITHER (a) the median lag over primary units is < 2 min at the PRIMARY (midpoint)
  book time, OR (b) the venue's signed drift D has a 95% CI whose lower bound is <= 0 (the venue does not, on
  average, still have to move in the news direction after we know).
- **UNRESOLVED** if (a) is decided differently at the early and late book bounds (the 2-min line falls inside our
  capture resolution) and (b) does not kill.
- **Recommendation mapping (Phase 4 bus):**
  - not killed AND the paired EV increment at h = 1 or h = 5 has a CI lower bound > 0 AND mean EV_h > 0 with CI
    lower bound > 0 -> **build the bus as a TIMING strategy** (taker trigger), still per line.
  - not killed but the EV conditions fail -> **build the bus as CANCEL-PROTECTION only** (resting maker orders are
    exposed during the lag; no taker strategy).
  - killed -> no timing strategy. Cancel-protection is then judged by tau_V - t0: if the venue has mostly moved
    BEFORE our t0, a 10-min collector cannot protect resting orders and the bus needs the official-schedule
    cadence first; that is stated as the finding rather than a build.
- **Minimum n:** a verdict needs >= 30 primary units over >= 15 games for that venue; below it the venue is
  UNDERPOWERED and the recommendation says so. Every line stays its own decision: nothing here proposes a
  market-level switch.

## 6. Coverage rule (CLAUDE.md)

Before any result, the run prints per-source date coverage (news per sport, book_quotes per sport, Kalshi candles
fetched per unit, Polymarket venue_odds per sport/date) and the intersection, and the findings report the number of
units / games / dates the result rests on.

## 7. Deviations

Any change after this commit is written as a dated AMENDMENT below with its reason, before the result it affects is
read. Bugs fixed in the script that do not change a definition above are listed in the findings.
