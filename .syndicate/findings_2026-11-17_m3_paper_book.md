# M3, the paper book: registration (decision engine #736, Phase 1B)

Status: **REGISTERED 2026-11-17 5:22 PM CST, before its data and before M2's verdict** (user "Yes, register it",
answering "Register M3 as drafted, with all five recommendations?").
Drafted the same day after "Yes, draft it", answering "Draft the M3 paper-book registration next?".
Lane `engine-paper-m3`. Nothing is built yet: the code is pinned by hash in an addendum on
main before the first M3 slate's data is read. Nothing from M2's test window was read to write it.

## What M3 decides, in plain words

- M2 (read Tue 11-24 10:30 AM CST) says whether the learner's probability beats the books' fresh price as a
  *forecast*. It does not say whether it beats **the price we can actually trade at**.
- M3 answers that question, on paper, one market group at a time: only the groups M2 passes.
- **Live**, the bar is the plan's: buy 1 contract at Kalshi's real ask, and five minutes later the position must be worth
  more than we paid plus the fee. That must hold on average over at least 400 bets in at least 100 games, with the
  error bars computed game by game. Then the result at settlement (ROI) must not contradict it.
- **Pregame**, the bar is Phase 2's edge gate, unchanged.
- A pass lets the user decide on a live canary (M4). Nothing switches on by itself.

## When it starts

- **Only on `M2_VERDICT PASS`**, and only for the strata that verdict line names. Any other verdict (FAIL,
  NOTHING_JUDGED, NOT_A_VERDICT) means no M3: the learner stays shadow-only and the result goes back to the user.
- The first M3 slate is the first slate after the read that returns PASS (11-24's night if the 11-24 read passes).
- **Registered 2026-11-17, a week before the 11-24 10:30 AM read**, while M2's verdict is unknown, so the bar
  cannot be shaped by which strata happen to pass.

## The model M3 uses: M2's own fit, frozen

- Exactly the function M2 certified: the M2 read's learner (pinned code `981ef14f6`, tau 0.5, applied weights only,
  outcome truth for live, close truth for pregame), fitted on the gate's frozen train slates 11-09..11-14.
- It is re-created after the read by re-running the read's own learner command (its pinned code, its opinion
  directories, outcome and close truth) through a small wrapper that saves each fit object whole: every parameter and
  its covariance, so a cell unseen in training falls back to its parents exactly as in the read.
- **Precondition:** the re-created fit's weight table equals the 11-24 read's `weights` to 1e-9. If not:
  `M3 NOT_A_VERDICT fit`, back to the user.
- **Forward opinions come from the same pinned experts (`981ef14f6`),** run nightly on each M3 slate. Amendment 2's
  reproduction rule applies per slate: a sport whose pinned experts do not reproduce production on a slate places no
  bet from that slate (counted, by check and count).
- Never re-fitted during the window. (A re-fit is an M4 question.)

## LIVE: the rule

**How it runs: a nightly replay against recorded Kalshi quotes, not a fleet change.**
- Nothing on the fleet computes `p_decision` today, and the experts are shadow-only by design. A real-time arm
  would mean running them in the live-odds-worker, a loan from lane `in-game-trading`, a fleet deploy and a worker
  restart.
- The in-play recorder already captures what a replay needs. It is the "Syndicate inplay nightly" task, polling
  Kalshi's public API every 10 s for NBA, NHL, NFL and NCAAF full-game lines, each row stamped with its receive time.
  - On dev Saturday 11-14 it held 2,478 NCAAF spread markets, 1,833 totals and 234 moneylines.
  - Each market was re-quoted every 22.6 to 26.7 s at the median; the 90th percentile was 31 to 107 s.
- The fleet's own Kalshi store cannot be used. It keeps at most 48 quotes per market (`MAX_POINTS_PER_MARKET`,
  `venue_daily_odds.py:97`). On 11-14, 5,018 of 8,000 NCAAF markets were at the cap, each spanning only about the
  last 2 hours.

**Which lines are eligible.** A live opinion from the pinned experts is eligible only if all of these hold:
- M2's PASS line names its stratum exactly as `<sport>|<family>|live|a<=60(outcome)`, and its prior is at most
  60 s old (M2 judged the fresh stratum only). Pregame entries read `<sport>|<family>|pregame(close)` the same way.
  NHL live can never be on the list (Amendment 1);
- it is not refused, and the learner moved it: `A = logit(p_decision) - logit(p_prior)` is not 0;
- its line is a full-game h2h, spread or total that the order path's resolver (`kalshi_board_join._resolve_event`,
  `_side_for_team`) places on a Kalshi market at exactly that line. Segments and props have no recorded Kalshi
  quote. NCAAF's dev gain was all full-game anyway: segments applied nothing.
- **Frame check per slate and family.** Some lines have both a fresh book prior and a recorded Kalshi mid. On those,
  the median |book - Kalshi| in the chosen orientation must be below the flipped one's. A failing family places no
  bet that slate (counted). This catches the 2026-08-08 backwards-spread shape. F2's frame rule passed 12 of 12
  families on 11-15/16.

**The decision instant and the price (no peeking at a quote we could not have traded):**
- Decision instant `t_d`: the opinion's tick, or its game state's own time if that is later.
- **Entry:** the first recorded quote of that market received at or after `t_d + 10 s`, and no later than
  `t_d + 70 s`; otherwise no entry (counted).
  - The 10 s is the time to compute and send an order.
  - Taking the first quote **after** the decision, never the last one before it, is what stops a stale quote from
    manufacturing an edge. Kalshi re-prices in about 11 s; the books lag it.
- Asks outside [0.05, 0.95] are not taken.
- Price: that quote's ask on the chosen side (YES ask, or NO ask for the other side), plus Kalshi's taker fee per
  contract. The fee is `venue_fees.taker_fee_per_contract(..., in_play=True)` with the series multiplier, per
  contract on a 10-contract order, as the in-play scoreboard charges it.

**The gating arm, A1: the learner on top of Kalshi.**
- At the entry quote: `p* = sigmoid(logit(m_K) + A)`, where `m_K` is that quote's mid and `A` is the learner's
  adjustment above.
- Buy our side if `p* - ask - fee >= 0.03`. Otherwise buy the other side if `(1 - p*) - ask_other - fee >= 0.03`.
  The 0.03 floor is the one the in-play paper book uses today.
- **Why this arm and not `p_decision` itself.** `p_decision` is built on the books' price, and Kalshi leads the
  books in play. Betting `p_decision` against Kalshi's ask mostly bets the books against Kalshi. The plan already
  lists that as measured and not to be chased again. A1 bets only where the learner's own adjustment exceeds Kalshi's
  half-spread plus the fee plus 3c: with `A = 0` it can never qualify.
- **Limits:** one entry per (game, market) for the whole game. At one instant, at most one entry per (game, family):
  the qualifying market and side with the largest edge. 1 contract each. No exits: the entry is held to settlement.

**Reported beside it, never gating** (on the same instants and quotes):
- **A2:** `p_decision` against the ask, the plan's literal wording.
- **C0:** the books' median no-vig fair, today's in-play paper fair (`inplay_entries_paper.book_fair`).

A2 minus C0 is the learner's contribution measured the plan's way.

**Truth:**
- **Fast: the fee-net mark-out at +300 s, per contract.** It is the mid of the first recorded quote of that market
  received between `entry + 300 s` and `entry + 420 s` (the in-play paper book's own window), minus the ask, minus
  the fee. A market that settles first is marked at its settlement (0 or 1). Anything else is *unmarked* (counted).
- **Slow: the outcome.** Kalshi's own `result` for that market. ROI per contract = (payout - cost) / cost.

**The gate** (the structure of Phase 2's registered edge gate, `8d16ab07`, so the two halves read alike):
- **Statistic:** the mean mark-out per bet, with a game-clustered z.
  - The error bar sums residuals within each game: `SE = sqrt(sum_g S_g^2) / n * sqrt(G/(G-1))`.
- **Looks** are triggered by counts only (bets, games, unmarked), never by results. Three looks, O'Brien-Fleming,
  the same boundaries as Phase 2:

  | Look | Bets | Games | PASS if | FAIL if |
  |---|---|---|---|---|
  | L1 | ≥ 400 | ≥ 100 | z ≥ 3.935 | z ≤ -3.935 |
  | L2 | ≥ 800 | ≥ 200 | z ≥ 2.783 | z ≤ -2.783 |
  | L3 (≥ 1,200 / ≥ 300, or the calendar stop **2027-01-31**) | | | z ≥ 2.272 | otherwise |

  Between the boundaries, M3 continues to the next look.
- **Then ROI**, read only after a mark-out PASS. The game-clustered 95% CI of ROI wholly below 0 means `M3
  CONTRADICTION`: not a pass, and it goes back to the user. Otherwise the PASS stands.
- **HARM per stratum:** a stratum with ≥ 100 bets in ≥ 30 games and a mark-out z ≤ -2.576 cannot go to M4, even
  if the pooled arm passes.
- **`M3 NOT_A_VERDICT`** at a look if:
  - the fit check failed;
  - a pinned file's hash differs;
  - more than 10% of the look's bets are unmarked.
- Every look prints, per stratum and per sport: bets, games, unmarked, the frame and resolver refusals, and the A2
  and C0 lines.

**What a result permits.**
- PASS: the user decides on M4, a live canary reading A1 per D2/D6/D7, and only in strata without HARM.
- FAIL or CONTRADICTION: the learner stays shadow-only, the engine read goes to the sim owners, and the result goes
  back to the user.
- Nothing changes a stake, an order or the board until the user decides.

**What the live half cannot test:**
- Sports the recorder does not poll: NCAAB, WNCAAB, WNBA. If M2 passes only those, there is no live M3, and that
  goes back to the user.
- Segments and props.
- The fleet's own latency, beyond the 10 s allowance.
- Queue position and size: a 1-contract fill at the ask is assumed.

## PREGAME: the rule

- Only if M2 passes a pregame stratum. The dev rehearsal's pregame weights were about 0 (every group within 0.0001
  nats), so this may never start.
- Bar: Phase 2's edge gate, unchanged (`.syndicate/findings_2026-10-26_decision_policy_v1_preregistration.md`,
  `8d16ab07`):
  - fee-net CLV against Pinnacle's power-de-vigged close;
  - a game-clustered z with the O'Brien-Fleming looks above;
  - bets with no Pinnacle close never count, which includes all NCAAB;
  - ROI is read only after a pass.
- A **new arm** beside Phase 2's P1. Phase 2's own registration is frozen and is not touched. Its probability is
  `p_decision` on the PASS strata, and its selection is P1's: `EV_lb > 0` at the venue ask plus the fee.
- Its plumbing is pinned in an addendum before its first bet.

## What has to exist before the first live slate

1. `m3_fit`: re-creates and saves M2's fit, and checks it against the read's weights.
2. `m3_live_replay`: per night, the pinned experts' opinions plus the recorder's Kalshi rows, giving bets with
   entry, mark and settlement. Tests:
   - the entry is the first quote after `t_d + 10 s`;
   - one entry per game and market;
   - the frame check;
   - fees;
   - `A = 0` places no bet (off != on).
3. `m3_gate`: the looks and the verdict, rehearsed on dev nights (11-13 and 11-14) and marked REHEARSAL.
4. A nightly task on this host that runs after the recorder's `DONE`:
   - the pinned experts on the fleet at nice 19;
   - the replay;
   - the counts;
   - the gate, only at a look.

   It keeps a compact per-night extract (the entry and mark quotes and the settlement) plus the raw files' sha256,
   so a look never depends on gigabytes kept on C:.
5. A new lane (proposed `engine-paper-m3`) for the code and its tests. The code would be shadow-only and import no
   order module.
   - The pinned files' hashes go into an addendum on main before the first slate's data is read.
   - Rough timing: two to three days of build, so it is ready for the 11-24 night.

## Decisions, ADOPTED 2026-11-17 (user, verbatim: "Yes, register it", answering "Register M3 as drafted, with all five recommendations?")

Each recommendation below was adopted; the alternative beside it was not.

1. **Nightly replay against the recorder** (ADOPTED), not a real-time arm in the fleet's in-play paper loop.
   - Real time is the eventual M4 path, but it needs the experts running on the fleet, an `in-game-trading` loan, a
     deploy and a worker restart before anything is measured.
2. **Gating arm A1, the learner on top of Kalshi** (ADOPTED), not A2, `p_decision` against the ask (the plan's
   literal row). The other is reported either way.
3. **M2's exact fit, frozen** (ADOPTED), not a re-fit on 11-09..11-22.
   - The re-fit adds 8 days of data but is a function M2 never judged.
4. **The recorder runs to 2027-01-31** (ADOPTED), not an M3 calendar stop of 12-31.
   - L3's calendar stop is 2027-01-31, and NCAAF's bowls and playoff run to about 1-19.
   - The 12-31 stop is not set in the task or its script (read 2026-11-17: the Windows task "Syndicate inplay
     nightly" has no end date, and `inplay_nightly.py` has no date stop). It is the calendar stop of lane
     `in-game-trading`'s stage-2 test, with a note to delete the task after it. So the task is NOT deleted at
     12-31 and runs to 2027-01-31 for M3. The stage-2 test's own stop is unchanged.
5. **The nightly M3 task** (ADOPTED: a scheduled job on this host, Idle; a nice-19 research run on the fleet each
   night). It is created once the build is ready, in a turn the user types.

## Found while drafting (recorded either way)

- **"Phase 2's paper track" in the plan row is decision-policy-v1** (lane `decision-policy-paper`, prereg
  `8d16ab07`), not the older `paper2` portfolio plan. Its 11-16 read: P2 took L1 and failed it (413 bets / 270
  games, CLV -2.20%, z -7.12); P1 has 133 bets / 101 games, short of a look.
- **The fleet's Kalshi store keeps only each market's last 48 quotes** (about 2 hours of a busy market).
  - Slice 5's Kalshi prior, replayed from that store after the slate, has no Kalshi quote for most of a game's early
    part. It falls back to the book prior there.
  - This should be checked against F2's own `KALSHI_PRIOR` coverage before slice 5 is re-pinned (lane
    `engine-live-prior`).
- **C: has 162 GB free** (read 2026-11-17 evening), not the 1.6 GB recorded earlier that day. A Saturday's
  recording is about 1.3 GB.

## What was read to write this

- Code and ledger on `origin/main`: the plans; the M2 registration; `decision_policy_paper.py` and its prereg (via a
  read-only survey); `inplay_entries_paper.py`; `inplay_recorder.py`; `inplay_fair_score.py`; `venue_daily_odds.py`;
  `venue_fees.py`.
- Data, **dev slate 11-14 only:**
  - the fleet's Kalshi store and the recorder's Kalshi rows (quotes, fields, counts and cadence);
  - one row of the 11-14 in-play scoreboard file, printed to see its fields, which carried that one NCAAF market's
    settlement.
- The recorder log's DONE lines, which say only that a night finished.
- **Nothing from M2's test window (11-15..11-22):** no learner output, close, outcome or Kalshi quote of those
  slates.
