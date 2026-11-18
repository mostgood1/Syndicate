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

## Build and dev rehearsal, 2026-11-17 6:11 PM CST (dev slates 11-13 / 11-14: NOT the gate)

**Built** on local branch `engine-paper-m3`, commit `46439b912` (`refs/keep/engine-paper-m3-46439b912`). It is NOT on main; pushing
it needs the user's yes. Files:
- `syndicate/features/shared/engine_paper_m3.py`: the rule's mechanics, pure;
- `scripts/engine_paper_m3.py`: `save-fit`, `check-fit`, `replay`, `gate`;
- `tests/test_engine_paper_m3.py`: 21 tests, plus the experts' shadow guard (22 passed);
- `docs/ai_context/engine_paper_m3.md`: the pipeline trace.

Kit `C:\tmp\elp\m3_kit`:
- `code/` is the M2 kit's export of `981ef14f6`. With CR stripped, its learner, experts, resolver and fee files equal
  `981ef14f6`'s blobs.
- It adds the two M3 files (blobs `5efd781ef584`, `39e1b5ff8358`, equal to `46439b912`'s) and `m3_launch.py`.
- The hash addendum goes on main before the first M3 slate.

**Constants the rule implied but did not number** (each one can only refuse a bet):
- the frame check needs at least 20 line-instants, compares a standing quote no more than 60 s old, and treats a tie
  as unverified;
- settlement is the first non-active quote after the market's LAST active one.

**The dev rehearsal** (`m3_kit/rehearse.sh`, on the fleet at nice 19; every line REHEARSAL):
- **Fit precondition:** `save-fit` re-ran the dev learner (11-09..11-14, test from 11-13, outcome) through the
  wrapper. `check-fit`: the re-run's weight table equals the dev run's (622 rows), and the saved fit (1,058
  parameters) reproduces it.
- **Dev M2 verdict:** PASS on `ncaaf|spreads|live|a<=60` and `ncaaf|totals|live|a<=60`.
- **11-13:** 1,158 NCAAF line-instants and 0 eligible: 887 had a prior older than 60 s, 241 were not in a PASS
  stratum, 30 were not full-game.
- **11-14:** 34,281 line-instants and 9,991 eligible.
  - Kalshi markets placed: 2,893. Another 1,652 belong to games our ledger does not carry.
  - Frame check ok: spreads over 2,825 lines, median |book - Kalshi| 0.027 chosen vs 0.040 flipped; totals over 1,208
    lines, 0.027 vs 0.040. On the 33 bets priced away from 50/50: 0.057 vs 0.476.
  - A1: 416 bets in 54 games. Refused: 4,347 lines with no Kalshi market at that exact line, 2,956 below the floor,
    1,636 with no quote in the entry window.
  - A2: 709 bets.
  - Entry lag p10 / p50 / p90: 12 / 23 / 48 s.
- **A forced L1 on dev** (dev never reaches 400 bets / 100 games; this is 416 / 54):
  - **A1's mean mark-out is -3.30c per contract, z -5.33: FAIL, with HARM in both NCAAF strata.** That is the fee
    -1.67c, the half-spread -0.76c, and the mid's move by +300 s -0.86c.
  - A2 (reported): -2.41c, z -5.10. Fee -1.62c, half-spread -1.04c, move +0.25c.
- **Settlement ROI on dev** (not read by the gate unless a mark-out passes): A1 +2.4% per contract (95% CI -17% to
  +22%); A2 -2.4% (-17% to +12%). On one Saturday that is noise.
- **Reading.** On this one dev Saturday, NCAAF's live learner adjustment does not move Kalshi's price its way within 5
  minutes. In M2's dev run it beat the books' fresh price as a forecast; Kalshi has already priced it. This is one slate
  of 54 games next to the train window, not the gate. Nothing of M2's test window was read.

**Risk found: gaps in the recorder.**
- The recorder writes a row on every poll. But it takes its tickers from the fleet's Kalshi capture file
  (`inplay_recorder.kalshi_tickers`, re-read every 600 s), and that file was at its 8,000-market budget on 11-14.
  So markets drop out of polling for minutes at a time.
- On 11-14, 36 of A1's 416 bets (8.7%) had no mark:
  - of both arms' 101 unmarked bets, 72 had their next quote 13 to 80 minutes later;
  - 29 had a quote in the window that was not two-sided.
- More than 10% unmarked at a look is `NOT_A_VERDICT`.
- A fix belongs in lane `in-game-trading`'s recorder (its tickers taken from Kalshi's events directly). That needs a
  loan and the user's decision.

## Addendum: the code, pinned 2026-11-17 7:03 PM CST (before any M3 slate's data is read)

The M3 code is on main as `95ae83f74` (user "Yes, push it", answering "Push the M3 code to main?"). It was rebased
unchanged from the rehearsed local `46439b912`: the same blobs, and 59 tests passed on `95ae83f74` (M3, the experts'
shadow guard, the learner).

| File on main | blob |
|---|---|
| `scripts/engine_paper_m3.py` | `5efd781ef584aa0e275b77fece82b5a543a78b63` |
| `syndicate/features/shared/engine_paper_m3.py` | `39e1b5ff83582d60773e47b2611a88cbf86c12b9` |
| `tests/test_engine_paper_m3.py` | `785d61b90372c75fd461dc7ab478699bc921c01d` |
| `docs/ai_context/engine_paper_m3.md` | `6f902c7653513c8eb3be51eff681bfc96fded617` |

The kit `C:\tmp\elp\m3_kit`. Each file's sha256 as stored; the `code/` files are CRLF:

| Kit file | sha256 |
|---|---|
| `m3_launch.py` | `d1bec7637517c5e5413ba4040b980e4fc8beffd6f422b89ce2e7d02cb3c0f423` |
| `rehearse.sh` | `6ec799538a17f07dcc04b2a40bc1db9a3bcbb9961dea8245e0591a78de82d5c5` |
| `code/PINNED_SHA` | `8170a5112905ec406d4060f6232a7df867181d0a2a9425b610a20597542f4058` |
| `code/scripts/engine_paper_m3.py` | `d445c67b2fde08663fb322365edf68205c7cf33cdb16e22fc34fc45469063d70` |
| `code/syndicate/features/shared/engine_paper_m3.py` | `ffba9bb4f424f556750f3558a2e9d28f4b45e4023c1bae1ba27810886e7ef325` |
| `code/scripts/engine_learner.py` | `e59d7d6f94c537ed1e0b8c79b6d129649f835ca6bdcb11f5a82f626e280bf9b7` |
| `code/syndicate/features/shared/engine_learner.py` | `b9d5db099b9131df95544ddf78e7082b9bdfb9497cba443c2cc3806eea088fd9` |
| `code/scripts/engine_experts.py` | `ede517b2bf0059b5c020a38d882cc577ee1502adb8430a6f35b23ded6d1e274b` |
| `code/syndicate/features/shared/engine_experts.py` | `812e4e8a8c504efbb7c73296491d16f9e6cbce5c8b52ef25744a2fabce08e461` |
| `code/syndicate/features/shared/kalshi_board_join.py` | `e08f88ca129695902675d12d9e05f06e33d4ca9a2b800d1144d0734a60654ae4` |
| `code/syndicate/features/shared/venue_fees.py` | `c0782f5b1c3319eae5077b93e29e602268b49a02fba9119e3b5a9502d3220aea` |

- `code/` is the M2 kit's export of `981ef14f6`. With CR stripped, its learner, experts, resolver and fee files equal
  `981ef14f6`'s blobs, and its two M3 files equal `95ae83f74`'s (checked by this addendum's own script).
- **Not pinned yet:** the nightly runner and its scheduled task. They are created after M2's 11-24 verdict and pinned
  in a further addendum before the first M3 slate's data is read.
- A change to any file above before the first slate needs a new addendum; after it, an amendment.

## Addendum: the nightly runner, pinned 2026-11-17 7:43 PM CST (before any M3 slate's data is read)

Built after "Yes, build it", answering "Build the nightly runner now, ready for 11-24?". It is the registered steps in
order and nothing else; the source is below. Each morning it does this:
- M2's verdict: no file means WAITING; anything but `M2_VERDICT PASS` means NO_M3, which goes back to the user.
- Once: save the fit and check it. A failed check writes STOP_fit.
- Each slate from 11-24 that the in-play recorder logged `DONE`: the pinned experts (M3's live sports only), then the
  replay. A night with no DONE two days later is RECORDER_MISSING, counted with no bets.
- `gate --count-only`, and the look itself only when one is due.

**Dev rehearsal** (`rehearse_nightly.sh`, 7:06 to 7:41 PM CST on the fleet, nice 19; REHEARSAL):
- the fit check passed (622 rows);
- the frozen experts were re-run fresh on 11-13 and 11-14 and reproduced production with 0 mismatches (11-14:
  91,333 NCAAF opinions);
- the 11-14 replay produced the same 1,125 bet rows as the first rehearsal, identical row by row (A1 416, A2 709);
- `M3_NO_LOOK_DUE`: 54 games is short of L1.

| Kit file (`C:\tmp\elp\m3_kit`) | sha256 |
|---|---|
| `m3_nightly.py` | `fa97ac1dad06e66fd68a5d86755d3d5e49e557793589156c391d9556e41319f9` |
| `run_nightly.sh` | `0aab46bad4c5bc21f6910f808258a16900e8ab6395570b61c8b445c06d6c3747` |
| `m3_nightly_live.json` | `135d824f810e7cc9abaa6f64b31319db7d5e5051d5576c4963000ca60d7e3db8` |
| `task_prompt_nightly.md` | `8f1421fb34ee695cee801fa2a48ff40f523bb945bae16ca641c79730fb652c8f` |
| `rehearse_nightly.sh` | `2df0658f5b2f889392596172f18b0f908c75ff03ccdf4146de721ec4e78a6312` |
| `m3_nightly_rehearse.json` | `8ed6b5c2a12d680335a2d260b7b4d0a31917f11db995d0553bb25ea3b83f28b3` |
| `m3_launch.py` | `d1bec7637517c5e5413ba4040b980e4fc8beffd6f422b89ce2e7d02cb3c0f423` |

- The task prompt was fixed before pinning: an early exit (WAITING / NO_M3 / NO_LIVE_ARM / STOPPED / ERROR) ends the
  morning's wait, because those exits print no `end` line.
- **The scheduled task itself is created in a turn the user types**, from `task_prompt_nightly.md` exactly as pinned.
- A change to any file above before the first slate needs a new addendum; after it, an amendment.

### `m3_nightly_live.json`

```json
{
  "first_slate": "2026-11-24",
  "last_slate": null,
  "rehearse": false,
  "m2_kit": "/mnt/c/tmp/elp/m2gate_kit",
  "verdict": "/mnt/c/tmp/elp/m2gate_kit/out/m2_verdict.txt",
  "read_learner_json": "/mnt/c/tmp/elp/m2gate_kit/out/learner_outcome.json",
  "learner_args": ["run", "--opinions-dir", "/mnt/c/tmp/elp/m2gate_kit/train,/mnt/c/tmp/elp/m2gate_kit/test",
                   "--dates", "2026-11-09..2026-11-22", "--test-from", "2026-11-15", "--truth", "outcome"],
  "recorder_dir": "/mnt/c/tmp/inplay_{date}",
  "recorder_log": "/mnt/c/tmp/inplay_nightly.log",
  "out": "/mnt/c/tmp/elp/m3_kit/live"
}
```

### `m3_nightly.py` (sha256 fa97ac1dad06e66fd68a5d86755d3d5e49e557793589156c391d9556e41319f9)

```python
"""M3's nightly runner (decision engine #736, lane engine-paper-m3). READ-ONLY on the fleet; run at nice 19.

Registered rule: .syndicate/findings_2026-11-17_m3_paper_book.md. This runner only orders the registered steps:
  0. M2's verdict: no file -> WAITING; anything but `M2_VERDICT PASS` -> NO_M3 (goes back to the user). A REHEARSAL
     line counts only in a rehearsal config.
  1. once: the fit -- re-run the M2 read's own learner command through `save-fit`, then `check-fit` against the read's
     JSON. A failed check writes STOP_fit and nothing further runs until the user decides.
  2. each slate from `first_slate` to yesterday (Central) not yet processed, once the in-play recorder logged
     `DONE <date>` (a night with no DONE two days later is processed as RECORDER_MISSING: no bets, counted):
     the pinned experts runner (the M2 kit's launch.py, M3's live sports only), then `replay`.
  3. `gate --count-only`; only if a look is due, `gate` (the look is taken once and recorded in looks.json).
It prints COUNTS ONLY until a look is due. Usage: m3_nightly.py <config.json> [--today YYYY-MM-DD]
"""
import json
import os
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

KIT = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
CT = ZoneInfo("America/Chicago")
RECORDER_SPORTS = ("nba", "nhl", "nfl", "ncaaf")


def say(out, line):
    stamp = datetime.now(timezone.utc).astimezone(CT).strftime("%Y-%m-%d %I:%M %p CT")
    text = f"{stamp} {line}"
    print(text, flush=True)
    with open(os.path.join(out, "nightly.log"), "a", encoding="utf-8") as fh:
        fh.write(text + "\n")


def run(cmd, stdout_path):
    with open(stdout_path, "w", encoding="utf-8") as fh:
        return subprocess.run(["nice", "-n", "19", *cmd], stdout=fh, stderr=subprocess.STDOUT).returncode


def last_line(path):
    lines = [x for x in open(path, encoding="utf-8", errors="replace").read().splitlines() if x.strip()]
    return lines[-1] if lines else ""


def recorder_done(log_path):
    done = set()
    if os.path.exists(log_path):
        for line in open(log_path, encoding="utf-8", errors="replace"):
            parts = line.split()
            if len(parts) >= 3 and parts[1] == "DONE":
                done.add(parts[2])
    return done


def main():
    cfg_path = sys.argv[1]
    cfg = json.load(open(cfg_path, encoding="utf-8"))
    today = sys.argv[sys.argv.index("--today") + 1] if "--today" in sys.argv else \
        datetime.now(timezone.utc).astimezone(CT).date().isoformat()
    out = cfg["out"]
    rehearse = bool(cfg.get("rehearse"))
    tag = "REHEARSAL " if rehearse else ""
    for sub in ("bets", "opinions", "experts", "logs"):
        os.makedirs(os.path.join(out, sub), exist_ok=True)
    m2 = cfg["m2_kit"]
    m3 = [PY, os.path.join(KIT, "m3_launch.py")]
    rh = ["--rehearse"] if rehearse else []
    say(out, f"{tag}M3_NIGHTLY start today={today} config={os.path.basename(cfg_path)}")

    # 0. M2's verdict
    if not os.path.exists(cfg["verdict"]):
        say(out, f"{tag}M3_NIGHTLY WAITING m2_verdict_missing {cfg['verdict']}")
        return 0
    vline = last_line(cfg["verdict"])
    is_pass = vline.startswith("M2_VERDICT PASS ") or (rehearse and vline.startswith("REHEARSAL M2_VERDICT PASS "))
    if not is_pass:
        say(out, f"{tag}M3_NIGHTLY NO_M3 verdict={vline[:200]!r}")
        return 0
    live = sorted({item.split("|")[0] for item in vline.split("[", 1)[1].split("]", 1)[0].split(", ")
                   if "|live|" in item} & set(RECORDER_SPORTS))
    if not live:
        say(out, f"{tag}M3_NIGHTLY NO_LIVE_ARM (no PASS live stratum in a recorded sport) verdict={vline[:200]!r}")
        return 0
    if os.path.exists(os.path.join(out, "STOP_fit")):
        say(out, f"{tag}M3_NIGHTLY STOPPED fit check failed earlier; see logs/check_fit.txt")
        return 0

    # 1. the fit, once
    fit = os.path.join(out, "fit_outcome.npz")
    if not os.path.exists(fit):
        rerun = os.path.join(out, "learner_outcome_rerun.json")
        rc = run([*m3, "save-fit", "--out", fit, "--", *cfg["learner_args"], "--json", rerun],
                 os.path.join(out, "logs", "save_fit.txt"))
        say(out, f"{tag}M3_NIGHTLY save-fit rc={rc}")
        if rc != 0 or not os.path.exists(fit):
            say(out, f"{tag}M3_NIGHTLY ERROR save-fit rc={rc}")
            return 1
        rc = run([*m3, "check-fit", *rh, "--fit", fit, "--read-json", cfg["read_learner_json"], "--rerun-json", rerun],
                 os.path.join(out, "logs", "check_fit.txt"))
        say(out, f"{tag}M3_NIGHTLY check-fit rc={rc} {last_line(os.path.join(out, 'logs', 'check_fit.txt'))[:200]}")
        if rc != 0:
            open(os.path.join(out, "STOP_fit"), "w").write(today + "\n")
            os.replace(fit, fit + ".failed")
            return 0

    # 2. each slate not yet processed
    done = recorder_done(cfg["recorder_log"])
    d = date.fromisoformat(cfg["first_slate"])
    stop = min(date.fromisoformat(today) - timedelta(days=1),
               date.fromisoformat(cfg["last_slate"]) if cfg.get("last_slate") else date.max)
    while d <= stop:
        ds = d.isoformat()
        report = os.path.join(out, "bets", f"report_{ds}.json")
        if not os.path.exists(report):
            folder = cfg["recorder_dir"].format(date=ds)
            if ds in done:
                opinions = os.path.join(out, "opinions", f"opinions_{ds}.jsonl")
                exp_out = os.path.join(out, "experts", f"experts_out_{ds}.txt")
                rc = run([PY, os.path.join(m2, "launch.py"), "experts", "run", "--date", ds, "--sports", ",".join(live),
                          "--opinions", opinions], exp_out)
                say(out, f"{tag}M3_NIGHTLY experts {ds} sports={','.join(live)} rc={rc} {last_line(exp_out)[:160]}")
                rc = run([*m3, "replay", *rh, "--date", ds, "--opinions", opinions, "--experts-out", exp_out,
                          "--fit", fit, "--verdict", cfg["verdict"], "--recorder", folder,
                          "--out-dir", os.path.join(out, "bets")], os.path.join(out, "logs", f"replay_{ds}.txt"))
                for line in open(os.path.join(out, "logs", f"replay_{ds}.txt"), encoding="utf-8", errors="replace"):
                    if "M3_SLATE" in line:
                        say(out, line.strip())
                if rc != 0:
                    say(out, f"{tag}M3_NIGHTLY ERROR replay {ds} rc={rc}")
                    return 1
            elif d <= date.fromisoformat(today) - timedelta(days=3):
                json.dump({"date": ds, "slate_refused": "RECORDER_MISSING: no DONE line two days after the slate"},
                          open(report, "w"))
                say(out, f"{tag}M3_SLATE {ds} RECORDER_MISSING (no bets, counted)")
            else:
                say(out, f"{tag}M3_NIGHTLY {ds} waiting for the recorder's DONE line")
                break
        d += timedelta(days=1)

    # 3. counts; a look only when due
    gate = [*m3, "gate", *rh, "--bets-dir", os.path.join(out, "bets"), "--state", os.path.join(out, "looks.json"),
            "--today", today]
    run([*gate, "--count-only"], os.path.join(out, "logs", "gate_count.txt"))
    lines = [x.strip() for x in open(os.path.join(out, "logs", "gate_count.txt"), encoding="utf-8") if "M3_" in x]
    for line in lines:
        say(out, line)
    if any("M3_LOOK_DUE" in x for x in lines) and not rehearse:
        run(gate, os.path.join(out, "logs", f"gate_look_{today}.txt"))
        for line in open(os.path.join(out, "logs", f"gate_look_{today}.txt"), encoding="utf-8"):
            if "M3_" in line:
                say(out, line.strip())
    say(out, f"{tag}M3_NIGHTLY end")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

## Addendum: the nightly task created, 2026-11-17 7:49 PM CST

- The user said "Yes, create it", answering "Create the M3 nightly task, 8:30 AM CT daily from 11-25?".
- Task `engine-paper-m3-nightly` ("M3 paper book nightly"): cron `30 8 * * *` local time. The app adds a dispatch delay
  and lists it at 8:41 AM CT; the first run is 2026-11-18. It is saved in Bypass permissions mode, and this session is
  notified when each run finishes. Until M2's 11-24 verdict, the runner prints only `WAITING m2_verdict_missing`.
- **The prompt was revised once before any run, and before any M3 data:**
  - New sha256 `670796f2b32eebe9aedc60953033fccc3074fbe2f46822aae357f074d7f2e0bb`, replacing the `8f1421fb34ee695c...` pinned above.
  - Why: an unattended run is refused changes to scheduled tasks, so "disable this task" would fail, and the same
    ledger entry would then be written every morning.
  - Now each status (NO_M3 / NO_LIVE_ARM / STOPPED) and each look is written ONCE, after grepping `origin/main` for
    it. If disabling is refused, the entry says "needs the user".
  - Nothing else in the prompt, and nothing in the runner, kit or code, changed.
- Checked: the task's stored body equals `m3_kit/task_prompt_nightly.md` byte for byte.


## Addendum 5: which live re-sim each bet came from, registered 2026-11-18 10:39 AM CST (before any M3 slate's data is read)

- **User:** "Yes, do it", answering "Build the re-sim change timeline and register it in M3 before its first slate?".
- **Why.** The live expert reads what the live re-sims publish. Other lanes change those re-sims almost daily, and an
  evidence row does not record the code that wrote it. M3 freezes M2's weights for up to ten weeks, so without a record
  no result could say which re-sim it measured.
- **What it adds. Report-only:** the gate, its looks and boundaries, the HARM and NOT_A_VERDICT rules, the counts that
  trigger a look, and every pinned M3 file are unchanged.
  1. Every morning, before the runner, the nightly task captures the fleet's role starts and checkout moves and
     rebuilds the per-sport version timeline. It is read-only and reads no M3 result. The role logs rotate in about
     four days, which is why it runs every morning.
  2. On a look morning only, after the verdict is written, one line per (sport, version): arm A1's bets, games,
     unmarked, mean mark-out and game-clustered z (the gate's own `clustered_z`), with A2 beside it. These lines change
     no verdict; the user reads them with it.
  3. From 11-24 on, each newly loaded re-sim version gets one log line (`M3_EPOCH_NEW`), so a change to what M3
     measures is never silent.
- **How a version is found** (`m3_kit/epochs/m3_epochs.py`):
  - The role that runs each re-sim: NBA in the live-odds-worker (its own loop, in-thread); NCAAF and NFL in the
    refresh-worker (`_run_ncaaf_live_resim_tick`, `_run_nfl_live_resim_tick`). NHL live is never eligible
    (Amendment 1).
  - A role runs the checkout HEAD as it stood when the role last started. Starts come from each role log's
    `==== start` line, the refresh-worker's exit records (+5 s) and each `up`'s bootstrap stamp. HEAD comes from the
    fleet checkout's reflog.
  - A new version begins at a start whose HEAD changed the code of the sport's re-sim files: its module, the engine it
    simulates with and the shared helpers it imports. Comment- and docstring-only edits do not count (the files' ASTs
    are compared). For `scripts/run_refresh_worker.py` and two shared NBA helpers, only the named functions count.
- **Limits:**
  - Env-only changes are not detected; `deploys.md` records them. The env backups dated inside 11-08..11-18 are
    labelled for NCAAB (11-09, 11-10), the board split and NHL props (11-18).
  - NBA before 11-14 10:29 AM CST is approximate. Those live-odds-worker logs have rotated away, so a checkout move is
    taken as loaded at once. The worker also recycles itself about every 6 h, so the true load can be up to ~6 h later.
  - The file lists are deliberately wide. A version can begin at a change that alters nothing in practice (a
    default-OFF switch, or another sport's refusal in a shared file); each version lists its commits.
- **Pins** (sha256):
  - `m3_kit/epochs/m3_epochs.py` `b5209d5a6dcb0fe722a9d97a0210b4b2b09858c95d98999de91ea6beb6332ccf`
  - `m3_kit/epochs/run_epochs.sh` `508361e8858789f36880bf5257a7e1b78efe8026723415ad90d99e843d201c4e`
  - `m3_kit/epochs/run_report.sh` `c453547bc49503b002ab3de13d572674deb380c6b6a5585c28c2292dfbb2fe4c`
  - The nightly task's prompt is now `d4c8e87a7fb9449da008504451b9d77a70829654fcf40cecc4cd08e50cfd9d15`, replacing `670796f2b32eebe9...` (the old text is kept as
    `m3_kit/task_prompt_nightly_670796f2.md`). It adds the morning capture (step 2), the look report (step 4) and the
    `M3_EPOCH_NEW` log line, and checks the three pins above; a mismatch there skips only the epoch steps. Nothing else
    in the prompt changed, and nothing in the runner, the kit's M3 files or the M3 code.
  - Checked: the task's stored body equals `m3_kit/task_prompt_nightly.md` byte for byte.
- **Checked on dev data, NOT the gate:**
  - On the 11-14 rehearsal bets the report reproduces the rehearsal exactly: A1 416 bets / 54 games, mean -0.0330,
    z -5.33; A2 -0.0241, z -5.10.
  - Synthetic bets at 11-13, 11-16 and 11-17 were tagged `nba-E4`, `nba-E8` and `nfl-E5`, the versions loaded then.
  - Capture and timeline together take 47 s.

### The timeline, 11-08..11-18

Built 11-18 10:34 AM CST (`m3_kit/epochs/timeline.json`). A version is the re-sim code a role ran from one load to the next code-changing load.

**NBA** (runs in the live-odds-worker; its starts are logged from 11-14 10:29 AM CST; before that, a checkout move is taken as loaded at once and marked approx (the worker also recycles itself about every 6 h)):

| version | from (CST) | fleet SHA | how it loaded | the code changes that started it |
|---|---|---|---|---|
| `nba-E0` | 11-07 6:00 PM | `af4244afd` | window start (approx) | (the window's starting code) |
| `nba-E1` | 11-08 11:22 AM | `a3d72c82b` | ff-assumed (approx) | a3d72c82b nba live props (#762 (6)): a market the books pull mid-game keeps a DISPLAY-ONLY Live proj. / Live actual |
| `nba-E2` | 11-09 8:00 AM | `e2558013c` | ff-assumed (approx) | e2558013c #762 (7): one player, one key -- the NBA live re-sim and the board join use the engine's canonical player name |
| `nba-E3` | 11-10 12:04 PM | `eeb2461c7` | ff-assumed (approx) | eeb2461c7 nba live re-sim: keep re-simming a game still live at midnight Central (#776) |
| `nba-E4` | 11-11 5:39 PM | `837320ab5` | ff-assumed (approx) | 837320ab5 nba live re-sim: record its own P(overtime) per lane and in live_resim_history (#789); #788's overtime miss wa |
| `nba-E5` | 11-14 9:37 AM | `fee389971` | ff-assumed (approx) | 68fbb8eeb nba live_resim: anchor the live full-game margin to the closing line, as college does; the join prices an anch |
| `nba-E6` | 11-15 12:25 PM | `f6f1ad93a` | rolelog | 7a5f4d09e live-player-exit-gate: live_player_status -- who has left a live game, from the ESPN summary feed<br>11ecd2bbf live-player-exit-gate: NFL live re-sim refuses a game whose QB has left it (key_player_out) + WNBA ejection pl |
| `nba-E7` | 11-15 7:44 PM | `db2af02ab` | rolelog | 60188bad1 live-player-exit-gate: NCAAF -- a live QB exit refuses the game key_player_out, and in-play entries hold on it<br>db2af02ab live-player-exit-gate: football detector catches a QB who leaves with NO injury line -- once another passer ta |
| `nba-E8` | 11-16 12:15 PM | `a39058946` | rolelog | 2c39a3043 live-player-exit-gate: NBA -- a starter gone mid-game (ejection / foul-out / in-game injury) refuses the live <br>09925a4b1 live-player-exit-gate: NBA -- a foul-out the engine already models is PRICED, not refused (user 11-16 "No, kee |
| `nba-E9` | 11-17 12:13 PM | `92ae7490a` | rolelog | f668eb6b9 live-player-exit-gate: MLB -- a starter out for injury or ejection refuses the game's live lines (todo 814) |
| `nba-E10` | 11-17 3:53 PM | `91d865fd5` | rolelog | cc90fb653 render-config-retirement step 2: every service-marker reader prefers a neutral SYNDICATE_* name; the launcher  |

**NCAAF** (runs in the refresh-worker; its starts are logged from 11-10 11:13 PM CST; before that, from its exit records and each `up`):

| version | from (CST) | fleet SHA | how it loaded | the code changes that started it |
|---|---|---|---|---|
| `ncaaf-E0` | 11-07 6:00 PM | `af4244afd` | window start (approx) | (the window's starting code) |
| `ncaaf-E1` | 11-11 12:45 PM | `b43236e17` | rolelog | b43236e17 ncaaf live: segment blocks (h1 h2 q1-q4) for the board's Live column, display only (todo #785) |
| `ncaaf-E2` | 11-15 12:24 PM | `32ccf391b` | rolelog | 7a5f4d09e live-player-exit-gate: live_player_status -- who has left a live game, from the ESPN summary feed<br>11ecd2bbf live-player-exit-gate: NFL live re-sim refuses a game whose QB has left it (key_player_out) + WNBA ejection pl |
| `ncaaf-E3` | 11-15 7:28 PM | `db2af02ab` | rolelog | 60188bad1 live-player-exit-gate: NCAAF -- a live QB exit refuses the game key_player_out, and in-play entries hold on it<br>db2af02ab live-player-exit-gate: football detector catches a QB who leaves with NO injury line -- once another passer ta |
| `ncaaf-E4` | 11-16 10:29 AM | `a39058946` | rolelog | 2c39a3043 live-player-exit-gate: NBA -- a starter gone mid-game (ejection / foul-out / in-game injury) refuses the live <br>38e237e6d smartsim2: the end-of-half fix mechanism (todo #808), every new switch default OFF and byte-identical<br>6c5f8633b smartsim2: #808 v2 end-of-half mechanism -- kneel-out, timeouts and spikes by need, Q4 kick timing, quarter-ke<br>5ddfdd86e smartsim2: #808 v3 -- kneel_out_q4_only, the kneel-out in Q4 only (default OFF, inert without the kneel-out) |
| `ncaaf-E5` | 11-17 9:47 AM | `17ff69398` | rolelog | f668eb6b9 live-player-exit-gate: MLB -- a starter out for injury or ejection refuses the game's live lines (todo 814) |

**NFL** (runs in the refresh-worker; its starts are logged from 11-10 11:13 PM CST; before that, from its exit records and each `up`):

| version | from (CST) | fleet SHA | how it loaded | the code changes that started it |
|---|---|---|---|---|
| `nfl-E0` | 11-07 6:00 PM | `af4244afd` | window start (approx) | (the window's starting code) |
| `nfl-E1` | 11-09 8:48 AM | `aa5f50ac5` | exit+5s | b2a5013e2 live NHL/NFL props: display-only box-score Live actual on the Layer 2 board |
| `nfl-E2` | 11-15 12:24 PM | `32ccf391b` | rolelog | 7a5f4d09e live-player-exit-gate: live_player_status -- who has left a live game, from the ESPN summary feed<br>11ecd2bbf live-player-exit-gate: NFL live re-sim refuses a game whose QB has left it (key_player_out) + WNBA ejection pl |
| `nfl-E3` | 11-15 7:28 PM | `db2af02ab` | rolelog | 60188bad1 live-player-exit-gate: NCAAF -- a live QB exit refuses the game key_player_out, and in-play entries hold on it<br>db2af02ab live-player-exit-gate: football detector catches a QB who leaves with NO injury line -- once another passer ta |
| `nfl-E4` | 11-16 10:29 AM | `a39058946` | rolelog | 38e237e6d smartsim2: the end-of-half fix mechanism (todo #808), every new switch default OFF and byte-identical<br>6c5f8633b smartsim2: #808 v2 end-of-half mechanism -- kneel-out, timeouts and spikes by need, Q4 kick timing, quarter-ke<br>5ddfdd86e smartsim2: #808 v3 -- kneel_out_q4_only, the kneel-out in Q4 only (default OFF, inert without the kneel-out)<br>6f7cb9eb3 nfl live resim: take the real timeouts left from the live row (todo #808, lane nfl-live-timeouts) |
| `nfl-E5` | 11-17 9:47 AM | `17ff69398` | rolelog | f668eb6b9 live-player-exit-gate: MLB -- a starter out for injury or ejection refuses the game's live lines (todo 814)<br>9049537d1 nfl live re-sim: carry the drive in progress from ESPN's situation (todo 813, lane nfl-live-possession-map; us<br>17ff69398 nfl live tick: carry ESPN's timeouts left (home_timeouts / away_timeouts, int 0-3 else None) for lane nfl-live |
| `nfl-E6` | 11-18 2:03 AM | `3920a2d4d` | rolelog | ee47c930a nfl live re-sim: seed each game by its ESPN event id (todo 813 part 2) |


## Addendum 5, a limit it missed (2026-11-18 11:51 AM CST, before any M3 slate's data is read; nothing else changes)

Data-file switches are not detected either, only code. The first one inside the window: **F1 of todo `#821`** (`feed_game_model` with the outs penalties off, in the NBA processed root's `nba_sim_total_inputs.json`) was switched on 2026-11-17 at 11:35 AM CST (`deploys.md` 17:34:59Z). It is a data-file switch, not code, so the version timeline cannot see it. It moves the NBA pregame sim's totals, which the NBA live re-sim starts from. Lane `nba-live-total-anchor` measured 11-18's 12 NBA pregame totals at +6.78 (se 1.04) above the closing line (`.syndicate/findings_2026-11-18_nba_live_total_anchor.md`). The per-version lines
cannot separate such a switch, and `M3_EPOCH_NEW` covers code only; `deploys.md` records the switches.
