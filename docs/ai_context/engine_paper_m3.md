# Engine paper book M3: the live replay and its gate (Phase 1B, lane `engine-paper-m3`)

M3 tests whether the learner's adjustment makes money **at the price we can actually trade**, on paper, in the market
groups M2 passes. The rule is registered before its data in `.syndicate/findings_2026-11-17_m3_paper_book.md` (main
`9f37d556c`, user "Yes, register it"). This code applies that rule and nothing else.

Shadow only: it reads files, writes only the files its arguments name, places no order and imports no order module.

## The pieces

| File | What |
|---|---|
| `syndicate/features/shared/engine_paper_m3.py` | The rule's mechanics, pure: the recorder's Kalshi markets, their placement on our games, entry, mark, settlement, both arms, the frame check, slate reproduction, and the gate's statistics and looks. It never names the opinion producers' module (their shadow guard fails on any file under `syndicate/` that does). |
| `scripts/engine_paper_m3.py` | The glue to the PINNED learner and experts (`981ef14f6`): `save-fit`, `check-fit`, `replay`, `gate`. |
| `tests/test_engine_paper_m3.py` | Synthetic quotes through the real resolver. |
| `C:\tmp\elp\m3_kit\` | `code/` = the M2 kit's export of `981ef14f6` + the two M3 files; `m3_launch.py` captures the fleet's env as the M2 kit's `launch.py` does. The kit's files are CRLF; with CR stripped every pinned file equals `981ef14f6`'s blob (checked 2026-11-17). |

## Pipeline trace (one slate, one sport)

1. **The M2 verdict line** -> `pass_strata()` (`engine_paper_m3.py:334`): only `M2_VERDICT PASS`. Live strata
   `<sport>|<family>|live|a<=60(outcome)`, pregame `<sport>|<family>|pregame(close)`. Anything else raises.
2. **Reproduction** -> `reproduction()` (`:370`), Amendment 2's attribution over the pinned runner's stdout. No `RESULT`
   line, or a count not fully attributed, refuses the whole slate. A sport with a live alarm or mismatch places no bet
   that slate (`EXCLUDED_REPRODUCTION`).
3. **Games** -> the live line ledger (`live_gameline_ledger.ledger_path`): `event_id -> home_team, away_team`.
4. **Decision instants** -> `decision_instants()` (`scripts/engine_paper_m3.py:163`). Each opinion's evidence row is
   re-found in the pinned `EvidenceIndex`, by `evidence_game` or the ledger's names, then by `evidence_t`. Then
   `t_d = max(tick, the row's as_of)`. A row not found exactly once is refused `state_time_unknown:*`. That count is
   per OPINION and includes experts that carry no evidence row (segments). A candidate line left without a decision
   instant is counted `no_decision_instant` (0 on dev 11-14).
5. **Candidates** -> `candidates_for()` (`:210`):
   - the pinned `el.build_examples` with a placeholder label (the label is never read);
   - kept: phase live, a PASS stratum, prior <= 60 s, full-game h2h / spreads / totals, our side;
   - `p_decision = el.p_decision(ex, frozen fit)`; `A = logit(p_decision) - logit(p_prior)`.
6. **Kalshi markets** -> `load_recorder()` (`engine_paper_m3.py:182`): the recorder's `kalshi.jsonl`, this sport's GAME,
   SPREAD and TOTAL series, in receive-time order.
7. **Placement** -> `KalshiIndex` (`:240`): the order path's `_resolve_event`, with Kalshi's own code-to-name pairs
   from its GAME markets, and `_side_for_team`. The frame is the live join's:
   - totals: "Over L" is key L;
   - spreads: "<home> wins by over s" is key s, and "<away> wins by over s" is key -s with p = 1 - mid;
   - h2h: the home-named GAME market.

   Anything unreadable or ambiguous is refused by name.
8. **Frame check** -> `frame_check()` (`:481`): per family, the median |book prior - Kalshi mid| in the chosen
   orientation must be below the flipped one's, over >= 20 line-instants with a standing quote <= 60 s old.
   Otherwise the family is `unverified` (fewer lines, or a tie) or `FLIPPED`, and places no bet.
9. **Entries** -> `replay()` (`:507`), per arm:
   - the first quote received in `[t_d + 10 s, t_d + 70 s]`, two-sided and active;
   - A1: `p* = sigmoid(logit(m_our) + A)`. A2 (reported): `p_decision`;
   - buy our side if `p - ask - fee >= 0.03`, else the other side if `(1 - p) - ask - fee >= 0.03`; an ask outside
     [0.05, 0.95] is not taken;
   - one entry per (game, ticker); at one tick, one per (game, family): the largest edge.
10. **Fee** -> `taker_fee()` (`:431`): `kalshi_taker_fee_dollars(10, ask, multiplier) / 10`. The series' own multiplier,
    else the full rate, flagged `fee_unresolved`. (Kalshi's NCAAF spread and total series have no stored multiplier,
    so they pay the full rate.)
11. **Mark and settlement** -> `mark()` (`:466`): the mid of the first quote in `[entry + 300 s, entry + 420 s]`, or
    the settlement (1 / 0) when the market stopped for good first; else unmarked. ROI uses Kalshi's own `res`.
12. **The gate** -> `look()` (`:618`) over arm A1:
    - the game-clustered z of the mark-outs (`clustered_z`, `:581`);
    - O'Brien-Fleming looks `due_look()` (`:605`): L1 400 / 100 (z >= 3.935 / <= -3.935), L2 800 / 200 (2.783), L3
      1,200 / 300 or 2027-01-31 (>= 2.272 passes, else FAIL);
    - more than 10% unmarked: NOT_A_VERDICT;
    - after a mark-out PASS, an ROI 95% CI wholly below 0: CONTRADICTION;
    - HARM: a stratum with >= 100 bets in >= 30 games and z <= -2.576.

## Constants the registration implies but did not number

- The frame check's minimum of 20 line-instants, its 60 s quote age, and "a tie is unverified". Each refuses a bet and
  never makes one.
- Settlement is the first non-active quote after the market's LAST active one, so a pause it came back from is not
  a settlement.

## Running it (read-only, on the fleet, nice 19)

```bash
K=/mnt/c/tmp/elp/m3_kit; PY=/home/amyn/.venvs/syndicate/bin/python
# after the M2 read: re-run its learner (outcome truth) through the wrapper, then the precondition
nice -n 19 $PY $K/m3_launch.py save-fit --out $K/fit_outcome.npz -- run --opinions-dir <M2 kit>/train,<M2 kit>/test \
  --dates 2026-11-09..2026-11-22 --test-from 2026-11-15 --truth outcome --json $K/learner_outcome_rerun.json
nice -n 19 $PY $K/m3_launch.py check-fit --fit $K/fit_outcome.npz --read-json <M2 kit>/out/learner_outcome.json \
  --rerun-json $K/learner_outcome_rerun.json
# each slate: the pinned experts (the M2 kit's launch.py experts run ...), then
nice -n 19 $PY $K/m3_launch.py replay --date D --opinions <opinions_D.jsonl> --experts-out <experts_out_D.txt> \
  --fit $K/fit_outcome.npz --verdict <M2 kit>/out/m2_verdict.txt --recorder /mnt/c/tmp/inplay_D --out-dir $K/live
nice -n 19 $PY $K/m3_launch.py gate --bets-dir $K/live --state $K/looks.json --count-only   # counts only
```

## Known risk: gaps in the recorder (measured on dev 11-14)

The recorder writes a row on every poll; it does not skip unchanged quotes. But it takes its ticker list from the
fleet's Kalshi capture file (`kalshi_tickers`, re-read every 600 s), and that file had hit its 8,000-market budget on
11-14. So markets drop out of polling for minutes at a time. On dev 11-14, 8.7% of A1's bets (36 of 416) had no quote
in the mark window: 72 of both arms' 101 unmarked bets had the next quote 13 to 80 minutes later, and 29 had a quote
in the window that was not two-sided. Gaps also refuse entries (`no_quote_in_entry_window`: 1,636 candidates).
More than 10% unmarked at a look is `NOT_A_VERDICT`, so a heavy NCAAF Saturday is close to that bar.

**The nightly path prints counts only.** No mark-out, ROI or result is printed or read until `gate` is run without
`--count-only` at a due look, and each look is taken once (`looks.json`). `--rehearse` (dev slates only) marks every
line REHEARSAL.
