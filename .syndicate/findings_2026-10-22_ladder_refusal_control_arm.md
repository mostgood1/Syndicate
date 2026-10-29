# The ladder refusal control arm: first read, NO VERDICT CLAIMED (n=80, every interval spans zero) — but the refused rows' edge is entirely eaten by fees, and that needs no significance

`[2026-10-22 15:35Z / 10:35 CDT]` session `4ab694ed`
lane `ladder-refusal-control-arm`
`[outcomes used: 80 settled paper ladder rows, flat $1 each]`

## What the control arm is

The paper ladder books rows the sizer **REFUSED** — `ladder_reason:
below_suggested_floor` (839 of 878) or `suggested_not_staked` (39) — and places
them flat at $1 anyway, paper-only. So their realised ROI answers a question
`published-negative-ev` has never been able to ask: **what would have happened on
the bets we declined to stake.** Verified before reading: ladder plan positions
carry no `sizing` block at all (0 of 104), because a refused row was never sized.

## PRE-REGISTERED before any outcome was computed

- **H1:** the refused rows realise at or below break-even once fees are counted —
  the floor is doing its job.
- **Falsified only if** ladder ROI net of fees is POSITIVE with an interval
  excluding zero, in which case the floor is declining bets that make money.
- The population is the low-EV tail by construction (`ev_band` m1to0 538 of 878,
  0to1 288), so it must **not** be compared against the staked book pooled. The
  self-contained test is realised ROI against each band's **own** admitted EV.

## The reading

Union of the live document **and** the archive — see the method note below.
958 ladder rows, **80 settled**, window 2026-10-20..10-21, flat $1.

| cut | n | pnl | ROI | 95% interval | admitted gross | admitted **net** |
|---|---|---|---|---|---|---|
| **all settled ladder** | **80** | −$13.75 | **−17.19%** | ±22.14 → **spans 0** | +2.90% | **−0.04%** |
| `below_suggested_floor` | 75 | −$9.75 | −13.00% | ±23.15 → spans 0 | +2.83% | −0.09% |
| `suggested_not_staked` | 5 | −$4.00 | −79.98% | excludes 0, **n=5** | +3.97% | +0.72% |
| band `m1to0` | 43 | −$2.00 | −4.66% | ±32.17 → spans 0 | +2.26% | −0.63% |
| band `0to1` | 28 | −$7.27 | −25.98% | ±35.30 → spans 0 | +3.44% | +0.41% |
| band `1to2` | 8 | −$4.94 | −61.75% | excludes 0, **n=8** | +4.26% | +1.31% |

Outcomes 38 won / 42 lost. By sport: wnba 45 (−17.72% ±30.50), ncaaf 20
(−36.96% ±41.57), soccer 12 (+21.41% ±53.77), nhl 3.

## Verdict

**H1 is NOT FALSIFIED, and NO VERDICT IS CLAIMED** — exactly as pre-registered.
Falsification required a POSITIVE ROI with an interval excluding zero; nothing is
positive and significant (soccer's +21.41% spans zero on n=12). Every cell with
n≥28 spans zero. The only two intervals that exclude zero are n=5 and n=8, and
reporting either as a finding would be picking the two noisiest cells out of
eight — so they are shown and explicitly not relied on.

The point estimate is negative throughout and directionally consistent with the
floor doing its job, but −17.19% ±22.14 is not a measurement of anything yet.

## The one thing that does NOT need significance

**The refused rows' edge is entirely eaten by fees.** Admitted EV is **+2.90%
gross** and **−0.04% net** across the 80, and the same pattern holds in every
band (m1to0 +2.26% → −0.63%; below_suggested_floor +2.83% → −0.09%). That is a
statement about the PREDICTED values, not the outcomes, so it needs no sample at
all: **the floor is refusing rows whose gross edge is real and whose net edge is
approximately zero.** On that evidence the floor is not obviously miscalibrated —
it is declining bets that are not expected to make money after costs, which is
what it is for.

It also reframes the question. If the refused population is net-zero by
prediction, then the interesting measurement is not "does the floor cost us
money" but **"is the fee model right"** — because the entire refusal boundary is
being set by the fee term. `ev_pct` vs `ev_net_pct` is a ~2.9-point wedge, and
`fee_is_upper_bound: true` appears on Kalshi rows, meaning the fee is an
UPPER bound and the true net edge may be better than −0.04%. That is a lead, not
a result.

## METHOD NOTE — read the ARCHIVE or get zero

**The live document alone shows 0 settled ladder rows**, and a reader would
conclude the ladder is ungraded. It is not: `_trim_to_cap` moves out settled
PAPER rows FIRST, so settling is exactly what removes a paper row from the
document. All 80 settled ladder rows are in
`reports/intelligence/execution_ledger_archive/orders_2026-10.jsonl` (9,166 rows,
8,866 settled = 97%). Grading lag there: **median 25.5h, p75 79.4h, p90 121.2h**.

I nearly filed "the paper venues are never graded" off the document alone — every
paper venue reads 0% settled in it (paper 963, paper:kalshi:ladder 664,
paper:prophetx 163, paper:novig 141, all 0%), while live kalshi and polymarket
read 93% and 92%. That contrast looks exactly like a grading gap and is an
artifact of the trim. Any ledger reading over paper MUST union the archive.

## Owed

Re-read when there are **≥400 settled ladder rows** (878 unsettled are already
queued and the median lag is ~1 day, so that is days not weeks). Armed as its
own frame-guarded task for 2026-10-29T18:00Z. The re-read should also split by
`fee_is_upper_bound` and compare `ev_net_pct` against realised, to turn the fee
wedge above from an observation into a measurement.

## Re-read 2026-10-29 — POWER GATE PASSED (n=5,689): H1 HOLDS; the refused rows lose, and it is NOT the fee

`[2026-10-29 18:04Z / 1:04 PM CDT]` scheduled task `ladder-refusal-control-arm-reading`; frame guard: started 18:00:23Z against an 18:00:00Z slot (on time).
Read-only on the WSL fleet with the refresh-worker's env (backend/url/reports/data roots: present, lengths only). Fleet checkout `6d6e729dc`.

**Population.** Archive `orders_2026-10.jsonl` 23,608 lines -> 19,704 unique `idempotency_key`; live document 3,000; union (document wins) 22,617.
Ladder rows **7,376, settled 5,689** (3,185 won / 2,490 lost / 14 push), unsettled 1,687 (1,399 future, 286 within 48h of their game, **2 stale >48h** -- so the
paper-grading gap of `#744` does not bias this read). All `mode: paper`; every settled row staked exactly $1; venues `paper:kalshi:ladder` 3,854,
`paper:polymarket:ladder` 1,835. Window `selected_date` 2026-10-20..10-29, 10 dates. **Power gate (>=400 settled): PASSED.**

| cut | n | pnl | ROI (net) | 95% interval | ROI gross | admitted gross | admitted **net** |
|---|---|---|---|---|---|---|---|
| **all** | **5,689** | -$367.08 | **-6.45%** | +/-2.43 -> **excludes 0** | -3.65% +/-2.43 | +2.72% | -0.08% |
| `below_suggested_floor` | 5,410 | -$367.90 | -6.80% | +/-2.47 -> excludes 0 | -4.03% | +2.68% | -0.08% |
| `suggested_not_staked` | 279 | +$0.82 | +0.29% | +/-13.14 -> spans 0 | +3.77% | +3.42% | -0.04% |
| band `m1to0` | 3,427 | -$256.23 | -7.48% | +/-3.08 -> excludes 0 | -4.81% | +2.08% | -0.56% |
| band `0to1` | 1,786 | -$109.92 | -6.15% | +/-4.55 -> excludes 0 | -3.04% | +3.55% | +0.42% |
| band `1to2` | 393 | +$8.92 | +2.27% | +/-9.03 -> spans 0 | +5.09% | +4.20% | +1.35% |
| band `ge2` | 83 | -$9.85 | -11.87% | +/-15.46 -> spans 0 | -10.08% | +4.41% | +2.57% |
| `fee_is_upper_bound=True` | 3,292 | -$196.28 | -5.96% | +/-3.20 -> excludes 0 | **-2.98% +/-3.20** | +2.92% | -0.05% |
| `fee_is_upper_bound=False` | 2,397 | -$170.80 | -7.13% | +/-3.75 -> excludes 0 | -4.56% +/-3.75 | +2.45% | -0.11% |

By sport (net ROI): nba 3,115 -5.79% +/-3.06; ncaaf 1,095 -5.53% +/-5.75; soccer 478 -14.27% +/-10.20; mlb 460 -2.96% +/-8.87; nfl 384 -1.87% +/-9.92;
wnba 90 -9.47% +/-19.99; nhl 67 -43.03% +/-22.09. No sport is positive. Upper-bound x sport has one n<10 cell (mlb ub=True n=5) -- shown in the raw output, not relied on.

Intervals are from per-unit returns (1.96*sd/sqrt(n)) and treat rows as independent. Rows share games and dates, so that is optimistic; as a check, the
**date-clustered** estimate (mean of daily ROI over 10 dates) is **-6.97% +/-3.80** -- still excludes zero. Per date: 10-20 +2.24% (165), 10-21 -7.94% (485),
10-22 -5.73% (549), 10-23 -3.53% (698), 10-24 -4.51% (803), 10-25 -10.07% (762), 10-26 -12.10% (920), 10-27 -3.51% (537), 10-28 -4.25% (768), 10-29 n=2.
8 of the 9 full dates are negative.

### Verdict against H1

**H1 HOLDS.** Falsification required a POSITIVE ROI whose interval excludes zero; the ROI is NEGATIVE with an interval excluding zero -- in total, for
`below_suggested_floor`, and in both large bands. The floor is not declining bets that make money. The only positive cells (`suggested_not_staked`, band `1to2`)
span zero and are not called a finding.

### The fee wedge -- measured, and it is not the story

- Paper charges exactly the modelled fee: mean `fees_dollars` = **2.80% of stake**, identical to the mean admitted wedge `ev_pct - ev_net_pct` = 2.80pt
  (ub=True 2.98 / 2.97; ub=False 2.56 / 2.56). So the paper ledger **cannot** say whether an upper-bound fee overstates the true one -- that needs live
  Kalshi fills, not paper.
- What it CAN do is bound it. The true fee on a `fee_is_upper_bound` row lies between 0 and the charged amount, so its true ROI lies between net and gross:
  **[-5.96%, -2.98%]**, and even the zero-fee end (-2.98% +/-3.20) is not positive. The upper bound cannot be what keeps these rows from profit.
- Realised minus admitted, per row: **-6.37pt +/-2.43 against net EV and -6.37pt against gross EV** (ub=True -5.91 / -5.90, ub=False -7.01 / -7.01). The miss is
  the same size gross and net, so it lives in the PROBABILITY, not the fee.
- **Retraction.** The 10-22 read said the floor "is refusing rows whose gross edge is real". At n=5,689 the gross edge is not real: admitted +2.72%, realised
  -3.65% +/-2.43 gross. The refusal boundary is not being set by a mis-specified fee term; the refused tail's admitted EV is overstated by ~6pt.

### Engine read

On the refused tail the model over-states edge by ~6.4pt. On the STAKED book, `#698` reading B (deploys.md 2026-10-29 15:09Z) measured the
realised-vs-admitted gap at -1.05pp (SE 1.59) -- indistinguishable from zero. So the over-statement concentrates where the floor refuses, which is consistent
with the floor (and the staked/refused selection) being informative. LEAD, not followed: whether the refused-tail over-statement is a market-mix effect
(soccer -14%, nhl -43% on small n) or a probability-calibration effect near the floor; a calibration curve of admitted probability vs outcome on ladder rows
would separate them.

### Owed

Nothing on this question. The lane's goal is met; closing it is left to a session (this run was automated). Not re-armed.
Scripts: scratchpad `read.py`, `stale.py` (session 4770a15b); raw output `reading.txt` there.
