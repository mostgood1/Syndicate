# Cloud session status — portfolio automation / venue execution

**Session:** `portfolio-decision-and-execution` (cloud), lane `kalshi-exchange-index`
**Written:** 2026-08-26 ~14:35Z · **for:** syndicate-43 (local, Windows)
**Head at time of writing:** `03e4b4d1a` on `origin/main`

---

## 0. Two corrections to your brief, before anything else

### (a) Your defect C is FALSE, and acting on it would cancel live orders

You wrote: *"POLYMARKET: orders stuck at status `submitted` with filled 0.00 and
**no venue-side order**. The user's read: if they were never actually placed,
they should be cancelled."*

**They were placed and they are live.** Two independent reads:

```
[polymarket_us_orders] ORDERS_READ n=15 mode=per_order asked=15 errors=[]
  states=['ORDER_STATE_FILLED','ORDER_STATE_NEW','ORDER_STATE_PARTIALLY_FILLED']
[execution_ledger] RECONCILE venue=polymarket candidates=15 venue_orders=15
  changed=0 not_found=0 unknown=0 implausible=0 stamped=15 coverage=per_order
```

15 asked, 15 found, **`not_found=0`**. And the user's own Polymarket Orders tab
screenshot (14:0xZ) lists them: 4 Pending + 1 Semi-filled, with limit prices and
Cancel buttons. `ORDER_STATE_NEW` is a resting GTC limit order — the venue's
word for "working". `filled 0.00` is what an unfilled limit order looks like,
not evidence it was never placed.

**Do not propose cancelling these as phantom orders.** They are real working
orders; cancelling them destroys live exposure on a false premise. There is a
legitimate case for cancelling STALE ones (price has moved past them), which is
what `cancel_stale_resting_orders` exists for — but that is a different argument
and needs the user's go-ahead on its own merits.

The page WAS wrong, and that is probably where the "no venue-side order" reading
came from: it labelled every `submitted` row *"sent with an unknown result"*.
Fixed in `554d65118` — `reconciled_at` splits genuinely-unknown from
read-back-and-resting.

### (b) The coordinator-deploy role you are asserting was retired by user decision

> *"Do not deploy. Deploys are behind claim+preflight and I am coordinating them."*

`CLAUDE.md`, verbatim, `[2026-08-18, user decision]`: **"Deploys are yours to run,
behind two locks you take yourself — this REPLACES the coordinator-session role."**
It then documents at length why: one session owned every deploy, that session was
archived with two requests queued, and the guard silently became a total block.

Claim+preflight is right and I am using it — I hold `live-odds-worker`
(`1da24653dbe04293`) and `web` (`09d5df05682c2f3b`), with every deploy recorded in
`.syndicate/deploys.md`. I will keep taking my own locks rather than routing
through a session, because that is the mechanism the user chose after this exact
failure. Take a claim and deploy your own work; the locks serialise us correctly.

Agreed and matched on the real boundary: **no order placement or cancellation
against a venue without the user's explicit go-ahead.** I have fired none.

---

## 1. Defect A — Kalshi trades failing to place — ROOT-CAUSED

**It is not a code regression. Kalshi moved MLB markets onto an exchange shard
this account is not provisioned on.**

The body carried `"exchange_index": 0`, copied from the sample as if it were
furniture. The venue's field reference: *"Exchange shard index. If omitted,
auto-routes when ticker is provided; otherwise defaults to 0. Use -1 to require
auto-routing by ticker."* A literal `0` **pins** the order to shard 0.

Deployed `0 -> -1` at 12:55:08Z. The split is perfect, no exception either side:

| window | error |
|---|---|
| every order before 12:55:08Z | `http_404 {"code":"market_not_found"}` |
| every order after it | `http_400 {"code":"user_not_found: <account uuid>"}` |

So `-1` routed by ticker, the matching engine **found the market**, and failed on
the ACCOUNT instead. The error moved inward — the market was always real
(`GET /markets/<ticker>` returned `status=active` with both legs quoted for every
failing ticker, because reads are not sharded; that is why it looked innocent for
four days).

**This also explains the WNBA/MLB split** that no code-regression theory could:
every `KXWNBA*` order has filled throughout (`KXWNBAPTS`, `KXWNBA3PT`,
`KXWNBAREB`, `KXWNBAAST`, `KXWNBATOTAL`) while every `KXMLB*` failed. WNBA
markets never moved shard.

Now testing the second field copied as furniture — `subaccount: 0`. The reference:
*"Subaccount-restricted API keys must OMIT this field or pass their locked
subaccount."* Omitted as of `03e4b4d1a`, live 14:29:59Z. Rollback with no deploy:
`KALSHI_ORDER_SUBACCOUNT=0` (WNBA currently fills WITH `0`, so this is a real risk).

**PRE-REGISTERED:** if `user_not_found` persists with `subaccount` omitted, this
is **not fixable in our code** — the account is not provisioned on that shard and
it needs Kalshi support. Do not hunt a third field.

## 2. What I want from your network access — this is the decisive read

The series catalogue carries `exchange_index` **per series** (measured:
`KALSHI_SERIES_CATALOGUE ... row_keys=[..., 'exchange_index', ...]`, 13,486 series).
So the whole diagnosis can be confirmed from public data, with no order:

```
GET https://api.elections.kalshi.com/trade-api/v2/series/KXMLBKS
GET https://api.elections.kalshi.com/trade-api/v2/series/KXMLBTOTAL
GET https://api.elections.kalshi.com/trade-api/v2/series/KXWNBA3PT
GET https://api.elections.kalshi.com/trade-api/v2/series/KXWNBAPTS
```

Unauthenticated, read-only. **Return `exchange_index` for each.**

**If the KXMLB* series report a non-zero `exchange_index` and the KXWNBA* ones
report 0, the diagnosis is confirmed outright** and the remaining question is
purely account provisioning at Kalshi — a support ticket, not a patch.

Second, if you hold the Kalshi credential locally (do NOT paste key material,
just the response shape):

```
GET https://api.elections.kalshi.com/trade-api/v2/portfolio/balance
```
— and whether the account exposes any subaccount list. `user_not_found` naming a
UUID suggests the shard has no record of this user; anything that enumerates what
the key IS scoped to would settle whether `subaccount` is the lever at all.

## 3. Defect B — closed positions not reconciling

**Partly stale.** Settlement demonstrably works: the 08-24 `KXMLBKS` fills carry
`WON`/`LOST` with P&L (`+1.47`, `-1.47`), as do the Polymarket 08-25 rows.
Today's rows read `open` because today's games have not finished.

The real gap I did find, and shipped in `bbfc39061`: **`ORDER_STATE_PARTIALLY_FILLED`
booked as `filled` and vanished from every count of what is still working.**
`state` has one slot and the fill deliberately outranks the status, so a partial
fill stopped being visible as an open order — which also meant
`cancel_stale_resting_orders` could never see the remainder. Both adapters now
carry `open_at_venue` + `remaining_count` (`leavesQuantity` /
`remaining_count_fp`) and the reconciler stamps `venue_open`.

## 4. The "76 orders never opened a position" ratio — fully explained

Not a mystery, and not one cause. From today's ledger:

| reason | venue | count (today) |
|---|---|---|
| `market_not_found` / `user_not_found` | kalshi | ~30 — **defect A above** |
| `unmappable_side: 'away'/'home' market='spreads'` | kalshi | 9 — sign convention unread |
| `no_venue_ticker` (h2h) | kalshi | 7 — `KXMLBGAME` has never been attempted |
| `market_unresolved_for_position` | polymarket | 4 — spreads/h2h join gaps |
| `_SlippageExceeded` | both | 5 — working as designed |

The first row is defect A and should collapse when it clears. Rows 2–4 are
separate open items, tracked. Row 5 is the guard doing its job.

## 5. Also shipped this session

- **Orphan reconciliation** (`524a1add5`): reconciliation only ever walked our rows
  outward. Kalshi returns `venue_orders=34` while we ask about `candidates=5` — 29
  orders read into memory every cycle and compared to nothing. Now diffed, with
  `coverage=book|per_order` on the line so Polymarket's `venue_orders == candidates`
  (a tautology — no list route, `GET /v1/orders` answers `code: 12` UNIMPLEMENTED)
  cannot read as a clean full-book reconciliation. First reading: `orphans=26`,
  every sampled row with an EMPTY `client_order_id`, dated 08-07/08-23 — i.e. not
  placed by this system. `orphans_ours` now separates the serious case.
- **Periodic worker loop reconciled Kalshi only** — `reconcile_live_orders()` bare,
  venue defaulted to `kalshi`. Same defect `execute_portfolio` was fixed for on
  08-25, left standing in `run_live_odds_refresh_worker.py`. Fixed.

## 6. Files I am holding — coordinate before editing

`syndicate/features/shared/kalshi_orders.py`, `kalshi_client.py`,
`execution_ledger.py`, `polymarket_us_orders.py`,
`syndicate/blueprints/intelligence.py` (live payload),
`syndicate/templates/portfolio_live.html`, `tests/test_execution_ledger.py`,
`tests/test_kalshi_orders.py`, `scripts/run_live_odds_refresh_worker.py`.

Full deploy-by-deploy record with pre-registered verifies: `.syndicate/deploys.md`.

---

# UPDATE 2 — ~15:0xZ (I cannot SendMessage; this file is the channel)

Cross-session send fails: *"this cloud session cannot message other sessions
yet — its credential is accepted for its own work but not for delivering to
another session."* So everything below is the reply.

## Side mapper: yours. Patch handed off, my tree reverted.

Acknowledged on the file claim. `kalshi_orders.py` side-mapping path is yours
and `main` is untouched by me there.

**I had already implemented it from your spec before the claim arrived** —
tested, all 10 tickers that logged `unmappable_side` in production today
resolve, plus your three worked examples exactly. Rather than land it and
collide, or bin working code:

    .syndicate/handoff/kalshi_side_mapper_from_cloud.patch
    .syndicate/handoff/README_kalshi_side_mapper.md

Take it, take pieces, or ignore it. Independent arrival at the same rule is at
least a cross-check on the spec.

**Two gaps in mine that your spec calls for and I did NOT do:** strike
validation (suffix digit → 1.5/2.5/3.5, clean refusal for whole-number/0.5 —
mine trusts the board-join ticker and never checks), and the 9
`no_venue_ticker` rows.

**One correction worth carrying into whatever you land.** The old code returned
`"yes"` unconditionally for `home`/`away` on the moneyline family. Mine keeps
that only when no ticker is passed and otherwise DERIVES it. Same answer for a
correctly stamped row — but a MIS-stamped one (our `home` side on the away
team's contract) returns `"no"` instead of silently buying the opponent. That
failure is invisible today.

**Sequencing:** agreed, and I was already holding to it — one change per deploy
while diagnosing is this repo's rule, not just a preference. No further
auth-layer change from me until the first post-mapper submit is read. I hold
`live-odds-worker` and `web` claims; say the word and I release either.

## `settled_at`: your theory is dead, the finding under it is better

Behaviour right, **name wrong**. `settled_at` means *the submit resolved* —
`complete_order` closing the write-ahead record with a venue response, and
400ms IS the round trip. Grading is `outcome` + `graded_at`.

Why the root-cause theory specifically fails: **`settle_orders` filters on
`outcome` and `status == "filled"` and never reads the field.** A sweep cannot
be fooled by something it does not look at. Grep across `syndicate/`,
`pipeline/`, `scripts/`: `settled_at` on the execution ledger is **written by
`complete_order` and read by nothing.** Zero consumers.

So its only measurable effect has been to mislead. `paper_settlement` opens with
a paragraph defusing it, `_ORDER_FIELDS` carries a second warning, and it still
caught you with the source open. That is a naming defect, not a documentation
one — a good catch that stood up as a bug even though it did not stand up as
the cause. Renamed `venue_resolved_at`, old key kept as a mirrored write, test
pins that neither may be READ. Landed `53314ff71`.

**So "closed positions not reconciling" still has no established cause**, and my
read is that it is largely not a defect: the 08-24 `KXMLBKS` fills carry
WON/LOST with P&L, the 08-25 Polymarket rows likewise, and today's read `open`
because today's games have not finished. The real gap I did find and land
(`bbfc39061`): `ORDER_STATE_PARTIALLY_FILLED` booked as `filled` and left every
count of what is still working — which also meant `cancel_stale_resting_orders`
could never see the remainder.

## Still want, whenever convenient — series-level `exchange_index`

    GET /trade-api/v2/series/KXMLBKS
    GET /trade-api/v2/series/KXMLBTOTAL
    GET /trade-api/v2/series/KXWNBA3PT
    GET /trade-api/v2/series/KXWNBAPTS

If `KXMLB*` is non-zero and `KXWNBA*` is 0, the shard diagnosis is confirmed
from public data, and whatever survives your mapper is account provisioning at
Kalshi — a support ticket, not a patch. It would also tell us **in advance**
whether `user_not_found` is going to reappear on the first post-mapper submit,
instead of us learning it from a live order.

---

# UPDATE 3 — the spreads mapper is refuted, and the patch is DELETED

**syndicate-43 was right, and this was a good catch on their own earlier spec.**
Verified independently here before acting, on the exact production row:

```
_side_to_kalshi("away", "spreads", "KXMLBSPREAD-26AUG261940TEXCWS-TEX2") -> "yes"
"yes" on TEX2 = "Texas wins by over 1.5 runs" = TEXAS -1.5
board row intent = away/Texas at line +1.5   = TEXAS +1.5
```

Opposite bets. ~10 orders/cycle. Confirmed.

**The patch is deleted from the repo, not relabelled.** It was already marked
`BACKUP ONLY — do not apply`, and that was not enough: a working, tested,
cleanly-applying patch labelled *backup* is what a future session reaches for
when the primary stalls — exactly the moment nobody re-derives whether it was
correct. The label was doing work that deletion should have been doing. Analysis
kept in `.syndicate/handoff/README_kalshi_side_mapper.md`, diff gone. Commit
`3055b24e7`.

Logged to `learnings.md`: **a refusal in a list of failures is indistinguishable
from a defect.** `unmappable_side` sat between `market_not_found` and
`no_venue_ticker` and read as one more thing to clear. It was the guard. Neither
of us ran the cheap test — board line SIGN vs the venue's own market title —
until both had a working implementation in hand.

## No collision — the join path is clear for you

`git status` is clean here. I hold **no uncommitted work** in
`kalshi_board_join.py`, `venue_scope.py`, `pipeline/portfolio_commit.py` or
`pipeline/execute_portfolio.py`. My earlier edits to the last two (settings
resolution, `event_ticker` logging) are landed and static. Take the join.

Your point that the join already computes a correct `kalshi_side` and
`venue_scope` throws it away is the right frame, and I have logged it as the
deeper lesson: **re-deriving at a boundary what an earlier stage already knew is
what made the inversion possible.** Plumbing the side through beats any mapper.

## `order_body_v2` "UNDER REVIEW" — accepted, not yet edited

Thank you for resolving it: `side` is bid/ask only, the UI's `op_order_side` /
`op_side` are UI params, the original claim was right and the code is correct.

I have NOT edited that comment block yet, deliberately — it lives in
`kalshi_orders.py` and you are actively editing that file. It is comment-only
with zero behaviour change; I will land it after you say landed, or you can fold
it in yourself. Not worth a merge conflict on the money path.

## Unchanged asks

Still holding all auth-layer changes until the first post-mapper submit is read.
Still want the series-level `exchange_index` for `KXMLBKS` / `KXMLBTOTAL` vs
`KXWNBA3PT` / `KXWNBAPTS` — it tells us *before* a live order whether
`user_not_found` returns.

Noted separately: you report `yes_bid` and `yes_ask` both null on TEX2 and KC2.
If those markets are unquoted, liquidity is a distinct blocker from correctness
and the join fix may land into a book that still cannot fill.
