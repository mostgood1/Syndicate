# Venue-API findings — 2026-08-26, session syndicate-43 (LOCAL, full egress)

> WHY THIS FILE EXISTS: cloud sessions cannot reach the Kalshi/Polymarket API
> hosts or docs.kalshi.com. Several code comments record guesses made under that
> blindness. Everything below was READ FROM THE VENUE from a non-proxied network.
> Nothing here is inferred. No code was changed and nothing was deployed.

## Egress: the block is the cloud sandbox, not the venue
Measured, all HTTP 200:
  api.elections.kalshi.com/trade-api/v2/exchange/status   (exchange_active, trading_active)
  external-api.kalshi.com/trade-api/v2/exchange/status
  gamma-api.polymarket.com/markets ; clob.polymarket.com/ok
`kalshi_client.py:18` ("the agent proxy denies api.elections.kalshi.com,
connect_rejected") is a CLOUD-SANDBOX fact. It must not drive host selection.

## The order path was a guess and the guess was RIGHT
`kalshi_orders.py:243` kept `/portfolio/events/orders` hedged because "the docs
host is blocked from this environment". Fetched docs.kalshi.com/api-reference/
orders/create-order-v2: `POST /portfolio/events/orders` is correct.
Required (all STRINGS): ticker, side, count, price, time_in_force,
self_trade_prevention_type. Optional: client_order_id, post_only,
cancel_order_on_pause, reduce_only, subaccount(int), order_group_id,
exchange_index(int). There is NO `action` field. exchange_index: "If omitted,
auto-routes when ticker is provided; otherwise defaults to 0. Use -1 to require
auto-routing by ticker." => `_V2_EXCHANGE_INDEX_AUTO = -1` is correct.

## The tickers were never wrong
Public lookups, all HTTP 200: KXMLBTOTAL-26AUG261607CLELAA-9,
KXMLBKS-26AUG261940TEXCWS-TEXMGORE1-7, KXMLBTOTAL-26AUG261310TBDET-8.
`market_not_found` was the shard, as the shard-fix comment concluded.

## Chronology (from /api/portfolio/live?show=all, 106 orders)
kalshi 8 filled / 40 failed / 27 rejected; polymarket 18 filled / 9 rejected / 4 submitted.
  36x market_not_found -- LATEST 11:44:49Z, all PRECEDE deploy a46797d1b
      (exchange_index -1) 12:55:08Z. Zero after. SHARD FIX EFFECTIVE, BUT BOUND:
      only n=4 submits have REACHED the venue since, and they are the 4 below.
      'No market_not_found since' rests on those 4, not on a large sample.
  4x user_not_found -- 13:13:43Z..13:20:17Z, after the shard fix, before deploy
      03e4b4d1a ("Omit the Kalshi subaccount") 14:29:59Z.

## THE SUBACCOUNT FIX IS UNTESTED -- and the ladder is blocked one rung EARLIER
First Kalshi cycle after 14:29:59Z was 14:32:02-14:32:05Z, 8 submits.
ALL EIGHT were OrderBuildError -- killed locally, none reached the venue:
  6x unmappable_side (away x4, home x2) market='spreads'
  2x no_venue_ticker (one spreads, one h2h)
A quiet venue here means orders stopped being SENT, not that auth was fixed.

## Kalshi side vocabulary -- SOLVED from live markets
home/away is not an axis Kalshi has. A game-line ticker NAMES A TEAM in its
suffix; the side is yes/no relative to that team.
Event KXMLBSPREAD-26AUG261907KCTOR lists BOTH teams x three strikes, all
strike_type "greater": KC2/KC3/KC4 = 1.5/2.5/3.5, TOR2/TOR3/TOR4 = same.
`yes_sub_title == no_sub_title` on these -- sub_title DOES NOT discriminate.
RULE: selected team == ticker team -> "yes"; the other team -> "no".
  KC -1.5 = YES on KC2.  TOR +1.5 = NO on KC2.  TOR -1.5 = YES on TOR2.
Suffix digit -> strike: 2=1.5, 3=2.5, 4=3.5. Only 1.5/2.5/3.5 exist; a whole or
0.5 spread has NO market and must refuse, not round.
H2H is the same shape: KXMLBGAME-26AUG261907KCTOR-KC "Kansas City wins" /
-TOR "Toronto wins". Catalogue already registers both series
(kalshi_catalogue.py:203-204), so the gap is the side mapper, not registration.

## Polymarket: the "phantom pending orders" premise is FALSIFIED
All 4 "submitted" orders are REAL, LIVE, UNFILLED limit orders:
venue_open=true, venue_status=order_state_new, venue_remaining_count 3.28-15.02,
reconciled 14:32:08Z. Cancelling them destroys working orders. Ages 06:36Z..09:34Z
against commence times 20:08Z..23:46Z -- resting, not stuck.

## NEW BUG: settled_at stamped on OPEN, UNFILLED orders
All 4 open Polymarket orders carry settled_at ~400ms after submitted_at, with
outcome null and status submitted:
  C3RQ5Y2J4FSQ sub 09:34:50.225994Z / settled 09:34:50.609766Z
  C3QRVK3EJFSH sub 08:28:53.720854Z / settled 08:28:54.173527Z
  C3Q3KSN08FSK sub 07:40:42.921333Z / settled 07:40:43.305617Z
  C3P5Y2D16FSP sub 06:36:41.160077Z / settled 06:36:41.655524Z
Something stamps settled_at at submit-ack. Any settlement/P&L/reconcile logic
keyed off settled_at is reading a lie, and a row that already looks settled will
be skipped by a settlement sweep -- a live candidate root cause for the
"closed positions not reconciling" symptom. UNCONFIRMED: writer not yet traced.

## Layer 1 direct-feed: NOT readable from web (unconfirmed cause)
`/api/ops/artifacts/export` returns count=0 for reports/intelligence/*kalshi*,
*polymarket*, and kalshi_markets.json. `/api/ops/odds-refresh/status` shows NO
kalshi or polymarket lane at all. Consistent with either the enable gate being
off or the artifact not being allowlisted/published to web. NOT DIAGNOSED --
reading live-odds-worker env vars was blocked by the permission classifier
(they hold venue secrets); needs the user or a session with that permission.

## ROOT CAUSE OF THE KALSHI PLACEMENT FAILURE: SHARD PROVISIONING, NOT CODE
`[2026-08-26T15:0xZ, from the user's 10:04 CT cycle + public market reads]`

**The subaccount fix is DISPROVEN.** Deploy `03e4b4d1a` live 14:29:59Z; a real
prop order reached the venue at 15:04:08Z and returned the SAME error:
`KXMLBERA-26AUG261910MILNYM-MILDMAY3-2` -> http_400
`{"code":"user_not_found: 22c67b4f-2bbf-4692-b325-85d508b94dc7"}`.

**`exchange_index` is on the PUBLIC market payload** -- no credentials needed.
Read for every order with a known outcome. The split is perfect, n=9:

| outcome | shard | ticker |
|---|---|---|
| FILLED | 0 | KXMLBKS-26AUG242145CINSF-CINCBURNS26-7 (MLB, 08-24) |
| FILLED | 0 | KXMLBKS-26AUG241840BOSMIA-MIASALCANTARA22-5 (MLB, 08-24) |
| FILLED | 0 | KXWNBA3PT-26AUG26GSCONN-GSGWILLIAMS1-2 |
| FILLED | 0 | KXWNBATOTAL-26AUG26TORSEA-177 |
| FILLED | 0 | KXWNBAREB-26AUG25WSHPHX-PHXNMACK4-8 |
| FAILED | 3 | KXMLBERA-26AUG261910MILNYM-MILDMAY3-2 |
| FAILED | 3 | KXMLBTOTAL-26AUG261607CLELAA-9 |
| FAILED | 3 | KXMLBSPREAD-26AUG261907KCTOR-KC2 |
| FAILED | 3 | KXMLBKS-26AUG261940TEXCWS-TEXMGORE1-7 |

**Everything that ever filled is shard 0. Everything that fails is shard 3.**
The two MLB fills on 08-24 were shard 0, so today's MLB markets are on a shard
those were not -- which is why this broke on 08-25 with no deploy of ours in
between, and it retires the last hypothesis that a code regression caused it.

This explains BOTH rungs of the ladder and closes it:
- `exchange_index: 0` (pinned) -> market is not on shard 0 -> `market_not_found`
- `exchange_index: -1` (auto)  -> routes to shard 3, market found -> `user_not_found`
Both errors were literally true and NEITHER was ours. `-1` is still correct and
must be kept: it is what let the venue state the real problem.

**NO CODE CHANGE CAN FIX THIS.** It needs the account enabled on shard 3 --
a venue/account action. A distinct exchange shard that is a separate entity
would require its own account agreement, which presents exactly as
`user_not_found` for a UUID that is valid elsewhere.

**DO NOT READ WNBA FILLS AS "KALSHI WORKS".** WNBA is shard 0 and will keep
filling regardless; that green says nothing about MLB. The only worthwhile
code-side change is a guard that REFUSES a Kalshi order whose market
`exchange_index` is not a shard we have ever filled on, by name -- turning a
confusing venue 400 into a legible refusal.

## Also confirmed this cycle
- `no_venue_ticker` on an h2h order (HOU@NYY) -- the moneyline keying defect
  recorded in the `kalshi-spread-join-sign` lane. Real, still open.
- `spreads away 1.5 -> ...-TEX2` still present in production: the inversion the
  join fix corrects. Fix is on `main` (`a09ec780`) and NOT deployed.
