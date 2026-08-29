# 2026-08-29 — the $1.84 unknown submit: RESOLVED, plus a defect the resolution exposed

## The question

`/portfolio` banner: "1 order(s) were sent and the venue never answered. Up to
$1.84 may or may not be at risk." Polymarket, MLS totals over 3.5,
Philadelphia Union @ New York Red Bulls, `tsc-mls-nyr-phi-2026-08-29-3pt5`,
idempotency key `5c53789d4d21d05fc501b05d`.

## ANSWER: the 503'd order never reached the venue. No orphan. MEASURED.

Polymarket `buyingPower`, from `/account/balances`, live-odds-worker log
`VENUE_BALANCES`:

| time (UTC) | buying power | what had happened |
|---|---|---|
| 21:05:56 | **96.05** | 40s before submit #1 |
| 21:12:47 | 96.05 | after the 503 |
| 21:18:46 | 96.05 | after the 503 |
| 21:25:09 | 96.05 | after the 503 |
| 21:32:08 | **94.15** | after submit #2 FILLED |

A GTC buy that lands reserves or spends immediately. **Three consecutive
readings spanning 19 minutes after submit #1 are unchanged at 96.05.** The
$1.84 never left the account on that attempt.

The single debit is -$1.8977 (cash 118.15 -> 116.25 agrees). Submit #2 filled
3.91 contracts @ $0.47 = $1.8377. **One order's worth of money moved, not two.**

The operator's "Venue shows no position" was CORRECT.

## Current true state of that market

`C60JWBG0WKDK`, **filled** 21:32:20Z, 3.91 contracts @ $0.47, $1.84. It is a
real, intended, open position on Over 3.5. Not "may or may not" — it is at
risk, deliberately.

## Timeline

- 21:06:36.29 SUBMIT #1 -> 21:06:37.69 `http_503 {"code":14}`, no order id, row `failed`
- 21:12:49 / 21:18:48 `UNKNOWN_ORDER_PROBE unknown=1 evidenced=0 sole_claim=True`
- **21:22:00.41 (web) `OPERATOR_RESOLUTION ... finding=not_placed`** -> row set `rejected`
- 21:25:39.76 SUBMIT #2 (retry freed by the resolution) -> 21:25:41.06 ok, `C60JWBG0WKDK`
- 21:32:20.99 `RECONCILED submitted->filled contracts=3.91 fill_price=0.47`

## DEFECT 1 — the retry DELETES the provenance the resolution promised to keep

`resolve_unknown_submit` docstring: *"THE ORIGINAL `error` AND `status` ARE
PRESERVED under `pre_resolution_*`. An operator can be wrong, and a record that
overwrites what actually happened leaves nothing to reverse."*

`not_placed` is the ONLY thing that sets `rejected`. `rejected` is the ONLY
thing (besides a retryable pause) that makes `record_order` **`orders.pop(index)`**
the row and write a fresh one. So the retry deletes `operator_resolution`,
`pre_resolution_status` and `pre_resolution_error` — exactly the fields
`resolve_unknown_submit` exists to preserve. `_LEAN_FIELDS` would not carry
them even if the pop were removed.

**Measured, and the contrast is the proof.** Two orders resolved `not_placed`
on 2026-08-28 (`tsc-nfl-sf-lv-2026-08-27-total-36pt5`, `aec-mlb-kc-tor-2026-08-27`)
STILL carry full provenance — because the board never re-proposed them, so
`record_order` was never called again. Today's was re-proposed, and its
provenance is gone. **The guarantee holds only where it does not matter and
fails where it does:** a live re-bet on the same market.

Live row now reads: submitted 21:25:38, filled, `error: None` — with no trace
that a 503 happened, that $1.84 sat unknown for 16 minutes, or that a human
made the judgement call that released it.

Consequence if the operator had been WRONG: two positions, one ledger row, and
the evidence needed to notice it deleted by the retry. `unknown_submits_resolved`
reads **2** — today's resolution is not counted, so the page cannot even report
that a human resolved one today.

## DEFECT 2 — Polymarket fees are not recorded

Account moved $1.8977; ledger records `fill_stake_dollars: 1.84`,
`fees_dollars: null`. **$0.06 of real money (~3.3% of notional) is unrecorded.**
Same class as the Kalshi finding already in `execution_ledger` ("FEES ARE REAL
MONEY AND WERE MODELLED AS ZERO EVERYWHERE"); the Polymarket order read does
not supply `taker_fees_dollars`, so nothing carries it across. Against edges
this system acts on at 3%, a 3.3% unrecorded cost is material.

## DEFECT 3 (latent) — `probe_unknown_polymarket_positions` says no read exists. One does.

Its docstring: *"Polymarket publishes no route that can settle the question."*
`/account/balances` was discovered 2026-08-26 and is fetched every worker tick.
It settled this case outright in five log lines. The probe should compare
buying power across the submit, not only the resolution feed, before asking a
human. `openOrders`/`unsettledFunds` both read 0.00 while a $6.02 order rested
— those two subfields look unfed and should NOT be relied on; `buyingPower`
and `cashBalance` both moved correctly and are the ones that work.
