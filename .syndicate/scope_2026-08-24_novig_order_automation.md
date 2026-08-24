# SCOPE — Novig order automation (Stage D, this lane's venue)

Drafted 2026-08-24, lane `exchange-markets-api-integration`, in response to
"start scoping novig" — the first of the three real-API venues from this
lane (polymarket / novig / prophetx) to get an order-automation design, per
this lane's own stated NEXT step (`todo.md #544`). **Not started. No lane
extension claimed, no code written.** This is a scope: it exists to surface
what is known, what is genuinely unknown, and what is blocked, before any of
it gets built.

Everything below is measured against the OTHER session's live Kalshi
automation build (`kalshi_auth.py`, `kalshi_orders.py`, `execution_guard.py`,
`execution_ledger.py`, `pipeline/execute_portfolio.py` — all on `main` as of
this scope, several already exercised against Kalshi's real API per their
`MEASURED 2026-08-24T...` comments). That build is the reference shape to
converge on, not to reinvent.

---

## 1. What is already venue-agnostic and needs ZERO changes for Novig

Read closely, not assumed: `execution_ledger.py` (write-ahead record,
idempotency, paper/live mode) and `execution_guard.py` (dollar caps, daily
order cap, kill switch) contain no Kalshi-specific logic at all. Both take an
`OrderRequest` and a `submit` callable; neither cares which venue the callable
talks to. The one venue-specific line in the whole path is
`pipeline/execute_portfolio.py::_venue_submitter`:

```python
if name == "kalshi":
    from syndicate.features.shared.kalshi_orders import kalshi_submitter
    return kalshi_submitter(_kalshi_price_for)
return None
```

**So Novig's entire automation surface is two new files** —
`novig_auth.py` (signing) and `novig_orders.py` (order body + submit/fetch/
cancel + a `novig_submitter()` adapter matching `kalshi_submitter`'s shape) —
**plus one `elif` branch** in `_venue_submitter`. Nothing about caps, the
kill switch, the ledger schema, or idempotency needs to change or be
understood twice.

`_venue_submitter` and `pipeline/execute_portfolio.py` are claimed by lane
`portfolio-decision-and-execution` as of this scope — a narrow claim on that
one function is the same move already made for
`scripts/run_refresh_worker.py` this lane, and should happen at
implementation time, not now.

## 2. What Novig-specific work is needed, and what is CONFIRMED vs UNKNOWN

Research for this scope (WebSearch — `docs.novig.com` itself is
proxy-blocked from this session, same denial every venue host in this lane
carries) reached real, named documentation pages this time, not only
third-party write-ups. That is a meaningfully better starting position than
`novig_client.py`'s original research pass had, but it is still NOT a live
call, and `kalshi_client`'s and `kalshi_orders`'s own history in this repo —
10 of 17 field names wrong, then a 410 on an inferred order path, then a
100x-off price unit, each caught only by a live call — is the standing
reason not to treat any of the "CONFIRMED" rows below as verified until a
real response says so.

| Question | Status | Detail |
|---|---|---|
| Price unit | **CONFIRMED (docs)** | `docs.novig.com/api-reference/data-model`: prices are decimal probabilities 0.001–0.999, "the stake per $1.00 payout" — 0.524 means $0.524 staked to win $1.00. **Same convention as Kalshi's dollars**, so `novig_client.probability_to_american` (already written, tested) is very likely also `novig_orders`'s conversion — but a market READ field and an ORDER WRITE field agreeing is exactly the assumption that produced Kalshi's 100x error, so this still wants a live check before being trusted for a write. |
| Order identity | **CONFIRMED (docs)** | `docs.novig.com/api-reference/outcome-ids`: an order targets an `outcomeId` (a UUID), **never a market ID**, and each outcome carries an `index` field that must be used to determine side — "the order of outcomes in an array does not determine their meaning." A side-mapping bug here is the exact class of error `kalshi_orders.py`'s `_side_to_kalshi` refuses-by-name rather than defaults; Novig's version needs the same discipline, keyed on `index`, not position. |
| Order READ endpoints | **CONFIRMED (docs), names only** | `/orders`, `/fills`, `/transactions` exist as user-history endpoints, max 256 items/request (default 100). This is `kalshi_orders.fetch_orders`'s counterpart, endpoint NAME confirmed, response SHAPE not. |
| **Order WRITE endpoint** | **NOT FOUND** | No search surfaced a `POST /orders` (or equivalent) path, method, or request body — the single most important fact for automation and the one this scope could not establish. This is the Novig equivalent of the sample payload Kalshi's owner had to supply by hand after the documented route 410'd; nothing here plays that role yet. |
| Order size unit | **UNKNOWN** | Kalshi orders in CONTRACTS (a $1-payout unit, floored from the stake). Whether Novig's write contract wants a contract/share count, a dollar stake directly, or something else is not established by anything found. |
| Sandbox/demo environment | **UNKNOWN** | Kalshi has a documented demo host (`demo-api.kalshi.co`) that a build can point at before risking a funded account. Nothing found confirms or denies one for Novig. |
| Auth mechanics beyond OAuth2 | **PARTIALLY CONFIRMED** | `novig_client.py`'s `load_credentials()`/`_fetch_token()` already implement the client-credentials exchange against `docs.novig.com`'s described flow ("secure OAuth 2.0 authentication ... get your access token and start trading in minutes"). Whether a SIGNED request (à la Kalshi's RSA-PSS per-call signature) is ALSO required on top of the bearer token is not established — Kalshi needed both; assuming Novig needs only the bearer token because the docs describe it as sufficient for "trading" is a real research gap, not a confirmed fact. |

## 3. The precondition this scope cannot get past: no credential exists

`novig_client.py`'s `load_credentials()` already refuses by name
(`no_client_id` / `no_client_secret`) with nothing configured — per every
source, Novig's OAuth tier is **founder-gated, not self-serve**. There is no
sandbox call, no probe run, no order-body verification possible until a
credential is actually issued. This is the same blocking precondition
`kalshi_orders.py`'s header describes for its own unverified assumptions,
except Kalshi's owner evidently HAS a credential now (the `MEASURED
2026-08-24T14:37:16Z` live order-read comments prove it) and Novig's does
not yet. **Requesting Novig partner access is therefore the actual next
action, ahead of any code** — everything in §4 is designed so it is cheap to
execute the moment a credential exists, not so it can be built blind first.

## 4. Proposed build, staged the way Kalshi's was (once a credential exists)

1. **`novig_auth.py`** — lift `novig_client.py`'s `load_credentials()` /
   `_fetch_token()` into a dedicated module (matching `kalshi_auth.py`'s
   separation from `kalshi_client.py`), add a `probe_auth()` that reads ONE
   authenticated GET (`/orders` or `/fills` with `limit=1`, never a write) and
   reports the shape that comes back — same role `kalshi_auth.probe_auth()`
   plays, and the cheapest possible check of whether the token alone
   authorizes a call or a second signature is also required.
2. **Read verification before any write path is written.** Run
   `novig_client.fetch_open_markets()` for real (it already exists, already
   refuses by name without credentials) and diff its live response against
   `_MARKET_FIELDS`/`_OUTCOME_FIELDS` — this repeats `kalshi_client.probe()`'s
   role and is strictly cheaper than guessing at the order body next.
3. **`novig_orders.py`, built AFTER an order-write endpoint is confirmed**,
   not before. Kalshi's `order_body_v2` exists only because the owner
   supplied a real sample payload by hand after the documented route 410'd —
   inventing a Novig equivalent from nothing, the way this repo's Kalshi
   build explicitly says NOT to do a second time, would repeat exactly the
   mistake `kalshi_orders.py`'s header warns against. **If Novig's own
   onboarding for a partner credential includes an OpenAPI 3.1 spec or a
   sample payload (the docs mention an OpenAPI 3.1 spec exists), get that
   FIRST and build `order_body` from it, pure and unit-tested, the same way
   `kalshi_orders.order_body_v2` is.**
4. **`novig_submitter()`**, matching `kalshi_submitter`'s shape exactly —
   bound to a live-price resolver, raises rather than sends at an unpriced
   contract.
5. **One `elif` in `_venue_submitter`.** Narrow-claim
   `pipeline/execute_portfolio.py` at this point, following the same
   released-stale-claim or explicit-narrow-claim precedent already used
   twice in this lane.
6. **Paper mode first, exactly as Kalshi's own build requires structurally**
   (`place_order`'s `mode != LIVE` branch is unconditional and venue-blind) —
   a Novig paper book proves the wiring before `SYNDICATE_EXECUTION_LIVE_ARMED`
   is ever considered for it.

## 5. Non-goals of this scope

- No code written yet. No credential requested yet -- that is a decision for
  whoever owns the Novig partner relationship, not something this session can
  do unilaterally.
- No claim taken on `pipeline/execute_portfolio.py` yet -- premature before
  there is a `novig_orders.py` to wire in.
- Legal/ToS review for automating orders on Novig is **explicitly still
  open** (`todo.md #544`'s own NEXT section: "whichever of
  polymarket/novig/prophetx clears legal/ToS review") -- this scope does not
  answer that question and automation should not proceed past §4 step 1
  without it being answered.
