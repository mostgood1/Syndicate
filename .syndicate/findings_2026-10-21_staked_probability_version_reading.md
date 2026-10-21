# The armed 2026-10-21 `staked_probability_version` reading: TAKEN, and it returns a NULL with a structural cause — the field that exists to keep two ROIs separable never reaches anything that settles

`[2026-10-21 21:40Z / 16:40 CDT]` session `4ab694ed`
lane `published-negative-ev` — the reading armed for **2026-10-21 15:00Z**
`[outcomes used: the production execution ledger, 3,000 orders]`

## Verdict first

**The reading cannot deliver the forward-ROI split it was armed for, and the
reason is not sample size — it is that no artifact carrying an OUTCOME carries a
join key back to the artifact carrying the sizing version.** Zero settled
positions in every cell.

That is a more useful answer than a thin ROI would have been, because it is
fixable and it invalidates any future attempt at the same reading until it is.

## Preconditions, both discharged before reading

- **The tuned-cell condition.** The lane required that if `SYNDICATE_MIN_EV_TUNER=apply`
  or any override had landed, the reading must ALSO split on the tuned cell.
  Measured: `SYNDICATE_MIN_EV_TUNER` is **ABSENT on both workers**
  (refresh-worker and live-odds-worker), so the tuner is inert and the split is
  on `staked_probability_version` alone. (The apply wiring did land —
  `802bed61`, 2026-10-20, recorded inert — so this was checked, not assumed.)
- **Lateness.** The reading was due 15:00Z and taken at ~21:35Z, **6h 35m late**.
  It is a RETROSPECTIVE split of accumulated rows, so lateness adds rows rather
  than closing a window — and in the event it is **irrelevant**, because the
  blocker is structural. Stated so nobody re-arms it believing timing was the
  problem. (This lane's sibling `ncaaf-segment-refusal-cost` had an armed reading
  silently never dispatch, which is why that one now has a frame guard and this
  one did not.)

## What the split actually produced

Version map built from the MAIN plan **and every per-venue plan**, because live
execution reads the venue plan (`execute_portfolio.py:612`), not the main one —
my first pass omitted them and joined zero live orders as a result:

| source | position keys |
|---|---|
| main plan | 158 |
| `venue:novig` | 50 |
| `venue:prophetx` | 44 |
| `venue:kalshi` | 30 |
| `venue:polymarket` | 4 |
| **distinct total** | **286** |

Ledger: **3,000 orders** — 2,342 paper, 658 live; **958 settled** (535 lost, 422
won, 1 push), of which **576 are live**. So outcomes are abundant.

**Joined: 143 orders, all paper, none settled.**

| era | version | mode | n | stake $ | settled | ROI |
|---|---|---|---|---|---|---|
| post-#704 | `market_fair@unfitted` | paper | 27 | 66.63 | **0** | **no settled** |
| post-#704 | `unfitted` | paper | 18 | 227.60 | **0** | **no settled** |
| pre-#704 | `unfitted` | paper | 98 | 1161.54 | **0** | **no settled** |

**Unjoinable, with the reason — this is the finding:**

| mode | reason | n |
|---|---|---|
| live | **no `position_key` at all** | **552** |
| live | key present but in no plan I could read | 106 |
| paper | key present but in no plan I could read | 2,199 |

Every one of the 658 live orders is unjoinable. 552 of them do not carry a
`position_key` in the first place.

## The structural cause

`staked_probability_version` is written in **exactly one module** —
`portfolio_commit.py`, five sites — and documented in
`staked_probability_profile.py`. It appears **zero times** in every module that
settles or grades:

```
paper_settlement.py         0 mentions
evaluation_settlement.py    0 mentions
execution_ledger.py         0 mentions
ledger_bridge.py            0 mentions
```

It is stamped onto a plan POSITION and never travels to the order, so the moment
an order settles, which sizing basis produced it is unrecoverable except through
`position_key` — which 552 of 658 live orders do not carry.

**The irony is in the field's own comment**, at `portfolio_commit.py:1456`:

> *"WHAT THIS STAKE IS BET ON. Without it, model-edge and market-fair positions
> land in one settlement pool and their ROIs stop being separable — two
> different claims averaged into one uninterpretable number."*

The field was added for exactly this reading. It keeps the two bases separable
**in the plan** and loses them **at settlement**, which is the only place an ROI
exists. That is the gap, stated in the code's own terms.

## What I am NOT reporting as a result

The one non-null column above is **mean plan `ev_pct`**: post-#704
`market_fair@unfitted` 3.372, post-#704 `unfitted` 3.277, pre-#704 `unfitted`
2.219. **This is not evidence the new sizing is better.** It is PREDICTED EV,
and this lane exists because predicted EV was the misleading number in the first
place (the user's 2026-10-06 question was why published rows carry negative
predicted EV). Quoting a predicted-EV improvement as a forward-ROI result would
reproduce the exact error the lane was opened to explain. Recorded so the number
is on file and cannot be mistaken for the verdict.

## What would make this reading takeable

1. **Carry `sizing.staked_probability_version` onto the order at submit time**,
   the way `sizing.basis` would need to travel too. The ledger already has the
   room — it carries 48 other fields per order — and this is the smallest fix.
2. **Or guarantee `position_key` on every live order.** 106 of 658 have one, so
   the plumbing exists and is not universal; without it, no plan-side provenance
   can ever be attributed to a live outcome.
3. Plan retention is a lesser issue but real: `read_portfolio_plan` returned 0
   positions for 2026-10-01..10-10 and the on-disk `portfolio_plan_*.json` files
   stop at 10-01, so the pre-period available for any such split starts 10-11.

Until (1) or (2) lands, **any reading that splits settled outcomes on a sizing
provenance field is unavailable**, not merely underpowered — and that applies to
the lane's second owed reading (forward ROI under the new sizing) as well.
