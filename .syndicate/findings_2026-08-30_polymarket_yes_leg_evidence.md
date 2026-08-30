# Polymarket YES-leg binding (`#595` step 3) — the evidence

Session `5611932c`, 2026-08-30 ~18:3xZ. **No code changed. No claim taken.**
Both files are held by `polymarket-buy-limit-tick-floor` (session `6475567d`);
scope request sent to the running session "Polymarket order submission failure"
(`local_c1fb3f4e`).

## 1. The gate as written cannot be discharged

`yes_leg_index_from_market`'s docstring requires the rule be *"scored against
all 8 venue-settled moneylines"* before `team_side_needs_verified_yes_leg` comes
off. **That is unsatisfiable with retained data.** `marketSides` is deliberately
never persisted (`_slate_row_for_storage` — 8MB keyvalue ceiling), so the rule
cannot be re-run against a market that has already settled. The sentence blocks
the fix permanently rather than gating it. It needs restating as a FORWARD
criterion.

## 2. `long_index` VARIES — the blocking null result is dead

3h of `MONEYLINE_YES_LEG_SHAPE` off live-odds-worker, after the peer widened the
`[:3]` sample cap to one-per-league:

    wnba 1, boxing 1  |  mlb 0, nfl 0, cfb 0, atp 0, atpcq 0, cplcr 0

The all-NFL constant-`0` window that stalled this is gone. `wnba` is BETTABLE.
Decisive single row:

    aec-wnba-min-atl-2026-08-30   outcomes=["Dream","Lynx"]   long_index=1

Slug says Minnesota@Atlanta; `outcomes` is listed **Atlanta-first**. The
positional rule buys the Dream where the YES token pays the Lynx.

## 3. The mechanism, on 9 real markets

`POLYMARKET_ARTIFACT_PRICE`, 08-26/08-27. `outcomes` order vs slug order:

| relation | markets | n |
|---|---|---|
| matches slug | tb-det, phi-sea, pit-sd, hou-nyy, bos-mia | 5 |
| **REVERSED** | cle-laa, col-wsh, min-ath, az-sf | 4 |

`YES = outcomes[0]` is therefore a **coin flip**. Measured, not inferred. Index 0
always submitted YES and index 1 always NO, so the positional rule is confirmed
as what actually ran.

## 4. Hard ground truth — one settled case

`aec-mlb-az-sf-2026-08-27`: `outcomes=['San Francisco Giants', ...]`,
`outcome_index=0` (SF), `SUBMIT side=OUTCOME_SIDE_YES @0.48`. **SF won 6-1.**
Venue graded **LOST**, `pnl -5.871`, `held_side=POSITION_RESOLUTION_SIDE_SHORT`.

So YES does not pay SF → YES pays AZ = index 1 = **the slug-first team**. On
4/4 live bettable samples `long_index` also lands on the slug-first team. Two
independent encodings agree, and they agree with the one case real money settled.

## 5. Anomaly — ledger `outcome` is NOT safe as ground truth

In `/api/portfolio/live?all_dates=1`, `aec-mlb-cle-laa-2026-08-26` appears
**twice — side `home` and side `away`, BOTH graded `won`**, same timestamp
(`2026-08-26T23:01:13`). Opposite sides of one game cannot both win. At least one
grade is wrong. Scoring must use venue `held_side`, which that endpoint's
projection does not carry.

## 6. The fix this supports

- `_resolve_outcome_side` takes the row's `yesLegIndex`; YES iff
  `outcome_index == yesLegIndex`, else NO.
- `yesLegIndex is None` **keeps** the refusal, carrying `yesLegReason` so a
  census separates "venue never says" from "our join broke".
- **Corroboration gate** in `_polymarket_resolve_market` (slug, outcomes,
  resolution and `_side_for_team` are all already in hand there): compute the
  slug-first team's index and REFUSE, named, on disagreement with `yesLegIndex`.
  Two independent sources must concur before real money moves — the only honest
  substitute for 8 settled markets that no longer exist.

On az-sf this sends **NO** (`outcome_index=0 != yes_leg 1`), and NO is the token
that pays SF — the team we actually wanted. It makes the known-bad case right.

**Caution on my own evidence:** slug-first/away is an empirical regularity over
5 markets, not a documented venue contract. That is precisely why it belongs as
a gate that REFUSES on disagreement, never as the resolver.
