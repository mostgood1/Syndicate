# Venue order reconciliation — the standard

> **What this is.** How to read back orders from Kalshi and Polymarket US:
> which routes return **all** orders (open *or* closed), what the fields mean,
> and the contract every venue reader must satisfy so that one reconciler can
> drive all of them.
>
> **Why it exists.** `[user 2026-08-27]` — *"We still have inconsistencies with
> the way the contracts are being reconciled. This needs to be standard."* They
> were real, they are named in [Known gaps](#known-gaps), and two of them are
> fixed in the same change that added this file.
>
> **Every field name and value below was MEASURED**, from `live-odds-worker`
> logs, with the timestamp against it. Nothing here is copied from a vendor doc
> or inferred from what a route "ought" to be called — that habit is what cost
> this repo an `http_410` on a moved Kalshi create route and an `http_501` on a
> reasoned-about Polymarket list route. [How to re-measure](#how-to-re-measure)
> is at the bottom; treat any unstamped claim as expired.

---

## 1. Why a second read exists at all

A submit response describes the moment of submission. It cannot describe what
the order did afterwards, and a limit order's entire purpose is to do something
afterwards. Both failure directions have been seen:

| | what happened | how it was caught |
|---|---|---|
| **We said filled, venue said resting** | ledger read `filled` for an order Kalshi showed with `Filled: 0` | **the user, looking at the Kalshi UI.** No log said anything was wrong — from inside the process nothing was. `2026-08-24T13:12Z` |
| **We said submitted, venue filled it later** | order correctly recorded `submitted`, fills an hour on. Settlement never grades it; the position is real the whole time | not yet bitten |

Neither is fixable by writing the submit path more carefully.

---

## 2. The reader contract

Every venue module exposes the same four things. `reconcile_live_orders` in
`execution_ledger.py` talks only to this contract, so adding a venue never
means branching inside the reconciler.

| symbol | shape | rule |
|---|---|---|
| `fetch_orders(*, limit, order_ids)` | `{"status","orders","coverage",...}` | **A failed read is an error, never an empty list.** `orders: []` on a failure reads as "the venue holds nothing", which is licence to write off a live position. |
| `fetch_order(order_id)` | `{"status","order"}` | Named failure, never raises — one unreadable order must not stop the pass. |
| `venue_order_view(order)` | `{"state","filled","price","fees",...}` | Reduces one venue order to ledger facts. `state` is **our** vocabulary (§4). |
| `ORDER_READ_COVERAGE` | `"book"` \| `"per_order"` | **Declared, not inferred** (§3). |

Two rules that hold for every venue:

- **`order_ids` is always accepted, and may be ignored.** Kalshi returns the
  whole book in one call and needs no hint; Polymarket *must* be told which
  orders to read. Accepting-and-ignoring keeps one call site in the reconciler.
- **A partial fill that was later cancelled is a FILL.** The filled size is read
  **before** the status and outranks it. Reading them the other way round
  reconciles a real position away to zero.

---

## 3. Coverage — the flag that says what a read proves

This is the crux of the reconciliation standard, and it was the first real
inconsistency.

| value | means | licenses |
|---|---|---|
| `book` | the read saw the **whole account** | orphan scan. `not_found = 0` means *we agree with the venue*. |
| `page` | a bounded page; there may be more | **no** orphan scan. |
| `per_order` | only the ids we handed it | **no** orphan scan. `venue_orders == candidates` is a tautology here, not a confirmation. |

An **orphan** is an order the venue holds that our ledger has no row for — the
case the write-ahead record exists for, and the only thing that can catch a
submit whose response was lost. It is detectable **only** under `book`.

> **The fix, 2026-08-27.** `kalshi_orders.fetch_orders` returned `coverage:
> "book"` *unconditionally* — including when the response was cut off at
> `limit`. A truncated page claimed the strongest guarantee in the system, and
> the orphan scan would then run against a partial book where every order past
> the cut reads as an orphan we do not hold. It now degrades to `page` when
> `n >= limit`, and says so in the log. Measured `2026-08-28T01:31Z`: `n=78`
> against `limit=100`, so today it is `book` **on the evidence** rather than by
> assumption.

---

## 4. The status vocabulary — one set, shared

`syndicate/features/shared/venue_order_states.py`.

| our state | venue words | reconciler does |
|---|---|---|
| `filled` | `executed` `filled` `matched` `closed` `complete` | book the position |
| `resting` | `resting` `pending` `open` `queued` `accepted` `active` `live` `new` | **leave alone** — may still trade |
| `dead` | `canceled` `cancelled` `expired` `rejected` `failed` `voided` | clear it |
| `unknown` | anything else | **leave alone** |

> **The second inconsistency, fixed 2026-08-27.** These were a private copy in
> each venue module and had drifted. `complete` was a fill on Polymarket and
> `unknown` on Kalshi; `failed` and `voided` were dead on one and unmapped on
> the other. The same word meant different things depending on which file read
> it, and neither venue promises never to use the other's vocabulary.
>
> **`unknown` is not a harmless default.** An unmapped status leaves the row
> unreconciled, and *an unreconciled order blocks live execution on every
> venue* — measured `2026-08-25T16:40:00Z`, when one resting Polymarket order
> blocked both scopes at once. A status unmapped merely because it was written
> into the other file is a live outage waiting on a word.
>
> Widening to the union only moves words **out of** `unknown`; it cannot re-map
> one already mapped, because the three sets are disjoint —
> `test_venue_order_states` asserts that rather than assuming it.

**Prefix stripping stays per-venue.** Polymarket ships `ORDER_STATE_FILLED`;
Kalshi ships `executed`. Strip **whole known prefixes only** — the first attempt
split on the last underscore, which tails `ORDER_STATUS_SOMETHING_NEW` to `new`
and reads a status we have never seen as confidently resting.

---

## 5. Kalshi

**Auth:** `kalshi_auth.signed_request`. **Base:** `_base_url()`.
**Path override:** `KALSHI_ORDER_READ_PATH` (default `/portfolio/orders`).

| purpose | route | returns |
|---|---|---|
| **All orders, open *and* closed** | `GET /trade-api/v2/portfolio/orders?limit=N` | `{"orders": [...]}` |
| One order | `GET /trade-api/v2/portfolio/orders/{order_id}` | `{"order": {...}}` |

> The read path shares a prefix with the **POST** route that returns `410` for
> creation. Reading there is fine; only the create verb moved. Learned by taking
> the 410 in production.

**Closed orders are included.** Measured `2026-08-28T01:25:01Z`: rows in the
list carry `status='executed'`. This is the one venue where a single call
answers "all orders, open or closed" — subject to the `limit` caveat in §7.

**Measured payload keys** — `ORDERS_READ n=78`, `2026-08-28T01:31:15Z`:

```
action  book_side  client_order_id  created_time  exchange_index
fill_count_fp  initial_count_fp  last_update_time
maker_fees_dollars  maker_fill_cost_dollars  no_price_dollars
order_id  outcome_side  remaining_count_fp  self_trade_prevention_type
side  status  subaccount_number  taker_fees_dollars
taker_fill_cost_dollars  ticker  type  user_id  yes_price_dollars
```

### `_fp` is plain contracts — settled by measurement

The suffix was undocumented, and the open question was whether it carried a
fixed-point scale: if it did, a 2-contract fill would read as some large number
and booking it would claim a position orders of magnitude too large. Two live
orders, `2026-08-28T01:25:01Z`:

```
fill_count_fp='16.00'  yes_price_dollars='0.4600'  taker_fill_cost_dollars='7.360000'
                                             16 × 0.46 = 7.36   exact
fill_count_fp='3.00'   yes_price_dollars='0.5200'  taker_fill_cost_dollars='1.560000'
                                              3 × 0.52 = 1.56   exact
```

- **Scale is 1. The unit is CONTRACTS.**
- The wire type is a **decimal string** with two places, not a number — every
  read goes through `_int_or_none` rather than indexing the value.
- **Fees are quoted separately and are NOT inside the fill cost.**

### Values

| ledger fact | from | note |
|---|---|---|
| filled count | `fill_count_fp` → `filled_count` → `fill_count` | falls back to `taker_fill_count + maker_fill_count`, then `initial − remaining` |
| fill price | `(taker_fill_cost_dollars + maker_fill_cost_dollars) ÷ filled` | the venue's own arithmetic. `count × price` was always a reconstruction, and division sidesteps guessing which of `yes_price_dollars` / `no_price_dollars` is our leg |
| fees | `taker_fees_dollars + maker_fees_dollars` | |
| still working | `remaining_count_fp` → `remaining_count` | a partial fill is a position **and** a live order for the remainder |

---

## 6. Polymarket US

**Auth:** `polymarket_us_auth.signed_request`. **Base:** `POLYMARKET_US_API_BASE`
or `BASE_URL`. **Overrides:** `POLYMARKET_US_ORDERS_LIST_PATH`,
`POLYMARKET_US_ORDER_GET_PATH`.

| purpose | route | returns |
|---|---|---|
| One order, **any state** | `GET /v1/order/{orderId}` | the documented read — **the only one that can say `dead`** |
| Open orders only | `GET /v1/orders/open?limit=N` | fallback; see below |
| ~~All orders~~ | `GET /v1/orders` | **`http_501`, `{"code":12}` UNIMPLEMENTED**, measured `2026-08-25T16:53:54Z` |

> Note the spelling: create is `POST /v1/orders`, read is `GET /v1/order/{id}`.
> Sibling paths differing by one character and one verb — which is why the list
> guess returned gRPC code 12 (*the path exists for POST and has no GET
> handler*) rather than a 404.

**There is no route that returns all orders.** `/v1/orders/open` is open-only,
so a cancelled or filled order is simply **absent** from it, and absence is
ambiguous — cancelled, filled, or just not returned. That route alone can never
clear a cancelled order, and an uncleared cancelled order blocks live execution
on every venue. Hence `ORDER_READ_COVERAGE = "per_order"`: reconciliation reads
`GET /v1/order/{id}` for each id it holds.

**Consequence, and it is a real limit rather than a bug:** an orphan scan is
**impossible** on this venue. A Polymarket order we hold no id for — a submit
whose response was lost — is invisible to every read available to us.

**Measured payload keys** — `ORDERS_READ n=4 mode=per_order`,
`2026-08-28T01:31:16Z`, `states=['ORDER_STATE_FILLED']` (so the per-order read
does return closed orders):

```
action  avgPx  cashOrderQty  commissionNotionalTotalCollected
commissionsBasisPoints  createTime  cumQuantity  goodTillTime  id
insertTime  intent  lastTransactTime  leavesQuantity
makerCommissionsBasisPoints  manualOrderIndicator  marketMetadata
marketSlug  outcomeSide  price  quantity  side  state  tif  type
```

### Values

| ledger fact | from | note |
|---|---|---|
| status | **`state`**, `status` as fallback | there is no `status` key at all — the first read mapped it to `unknown` and left the row blocking, which was *correct behaviour on an unknown status* |
| filled count | `cumQuantity` | `leavesQuantity` is the **unfilled remainder** — not a fill |
| fill price | `avgPx` | **see the warning below** |
| fees | `commissionNotionalTotalCollected`, `commissionsBasisPoints` | |

> ### `avgPx` is quoted on the YES side
>
> A **NO** order's fill price is its **complement**. Taking `avgPx` at face
> value recorded the other side's price on every `under`, and it halted trading
> on **both** venues at `2026-08-26T00:23:37Z`:
>
> ```
> RECONCILE_COUNT_IMPLAUSIBLE key=939fb90b24300f32c760b7bb
>   venue_count=2.39 requested=2.3920000000000003
> EXECUTION status=blocked reason=unreconciled_orders  (×2 venues)
> ```
>
> Recorded in `polymarket_us_orders.venue_order_view`, which is where the
> correction lives.

---

## 7. Known gaps

Open, and listed so nobody re-derives them.

1. **Kalshi has no pagination — but the field name is now MEASURED.** The list
   takes a `limit` and this reader has no `cursor` handling, so an account
   holding more than `limit` orders has an invisible tail. Coverage degrades to
   `page` when `n >= limit`, so the *consequences* are contained; the tail is
   still unread.

   The envelope was logged rather than guessed, and the first tick after deploy
   answered it — `2026-08-28T02:24:18Z`:

   ```
   [kalshi_orders] ORDERS_ENVELOPE keys=['cursor', 'orders'] n=78 limit=100
   ```

   **The field is `cursor`, at the top level of the response.** It took one
   production read, versus a guess that would have looked reasonable and cost
   an error round-trip — the same shape as the `http_501` on Polymarket's
   reasoned-about list route.

   **CLOSED `2026-08-28T02:58:17Z`.** The reader walks the cursor, deduping by
   `order_id`, bounded at 20 pages with a repeated cursor treated as a bound —
   never as an end of book. Live on the first tick:

   ```
   ORDERS_ENVELOPE keys=['cursor','orders'] n=78 limit=100 pages=1 exhausted=True
   ```

   **An empty cursor now OUTRANKS the `n >= limit` heuristic**, which is a
   correction and not just plumbing: a final page exactly `limit` long is the
   whole book if the venue says there is no more, and the old rule would have
   called it truncated and suppressed the orphan scan for nothing. The
   heuristic survives only where the response carries no `cursor` key at all.
   A FIRST-page failure is still an error; a LATER-page failure returns what
   was read as `page`, because those orders are real and only completeness was
   lost.
2. **Polymarket orphans are undetectable** (§6). Structural, not a defect —
   worth revisiting only if a list-all route appears. `probe_order_list_routes`
   exists to ask, read-only, and logs what it finds.
3. **Kalshi's list scope is not fully characterised.** `n=78` was stable across
   reads while the live ledger held ~200 rows across both venues and all dates.
   That is consistent with a venue-side retention or recency window, but it has
   **not** been established which, and this document does not claim it.

## First production run of the standard — `2026-08-28T02:24:18Z`

Live on `live-odds-worker` at `32b0cfaa`. Both readers, one tick:

```
RECONCILE venue=kalshi     candidates=14 venue_orders=78 changed=0 not_found=0
          unknown=0 implausible=0 stamped=14 coverage=book     orphans=26 orphans_ours=0
RECONCILE venue=polymarket candidates=2  venue_orders=2  changed=0 not_found=0
          unknown=0 implausible=0 stamped=2  coverage=per_order orphans=n/a
```

Reading it against §3 and §4: `coverage` is `book` for Kalshi **on the evidence**
(`n=78 < limit=100`, and `ORDERS_READ_TRUNCATED` stayed silent) and `per_order`
for Polymarket, which correctly reports `orphans=n/a` rather than a reassuring
zero. `unknown=0` on both venues is the shared vocabulary doing its job — no
status went unmapped, so nothing was left blocking live execution on a word.

The orphan scan, licensed only by `book`, found **26** Kalshi orders we hold no
row for: `ours=0`, `foreign_client=6`, `unclaimed=20`. `ours=0` is the number
that matters — no order of ours is sitting at the venue unrecorded.

---

## How to re-measure

Everything above comes from `live-odds-worker`, which is the only service that
places orders. `logger.info` does not reach Render's collector — these are all
`print(..., flush=True)`.

```bash
py -3 scripts/render_logs.py --service live-odds-worker --text "ORDERS_READ" --start 2026-08-28T00:00:00Z --tail 6 --width 900
```

| line | settles |
|---|---|
| `ORDERS_READ` | payload keys, row count, and for Polymarket the `states` seen |
| `ORDERS_ENVELOPE` | Kalshi's response envelope — **the cursor question** |
| `COUNT_FIELDS` | Kalshi count/money **values**, which is what settled `_fp` |
| `ORDERS_READ_TRUNCATED` | a page hit `limit`; coverage degraded |
| `ORDER_LIST_ROUTE_PROBE` | Polymarket candidate list routes, read-only |

Keys and statuses are logged, **values only for count and money fields**. An
order carries no credential, but it does carry our own positions — the log is
not the place for them.
