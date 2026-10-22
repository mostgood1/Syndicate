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
