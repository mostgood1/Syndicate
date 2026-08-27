# SCOPE — Novig order automation (Stage D, this lane's venue)

**PAUSED 2026-08-24, same day, explicit user decision:** "We can't automate
novig end to end for buying but we should use public endpoint/data to
populate our odds." Buy-side automation (this whole document) is NOT being
pursued further right now. `novig_orders.py` (`order_body`/`submit_order`)
stays exactly as built below -- correct, tested, safe by construction (never
reports a fill, paper-mode-first is structural) -- but nothing wires it to
`_venue_submitter` and no live order is planned. The active Novig work moved
to the public CSV mirror as an odds-population source; see
`novig_client.py`'s module header and `.syndicate/lanes.md`'s
`exchange-markets-api-integration` entry for that.

Drafted 2026-08-24, lane `exchange-markets-api-integration`, in response to
"start scoping novig" — the first of the three real-API venues from this
lane (polymarket / novig / prophetx) to get an order-automation design, per
this lane's own stated NEXT step (`todo.md #544`). This is a scope: it exists
to surface what is known, what is genuinely unknown, and what is blocked,
before any of it gets built.

**UPDATE 2026-08-24, same day — the user supplied real `docs.novig.com` page
content directly** (the "REST Endpoints / Rate Limits & URL's" and "Place
order" pages), not another research pass. This resolved §2's single biggest
gap: **the order-WRITE endpoint, previously "NOT FOUND", is now CONFIRMED
with an exact field-level contract.** `syndicate/features/shared/novig_orders.py`
now exists — `order_body()` (pure, unit-tested, matches the documented
`POST /emm/orders/place` schema exactly) and `cash_units_for_stake()` are
built; `submit_order` (the actual network call) is DELIBERATELY still not
written, because the response shape for a placed order was not part of what
was supplied — see the updated table below and `novig_orders.py`'s own
header for exactly what is confirmed vs still assumed. `novig_client.py`'s
`_MARKET_FIELDS` was also corrected against the same real content (three
invented field names — `market_type`, `is_consensus`, `scheduled_start` —
replaced with the real ones), and a confirmed `fetch_market(market_id)` was
added alongside the still-unconfirmed listing endpoint.

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
| Price unit | **CONFIRMED, now on BOTH sides** | Originally docs-research-only; the order-write contract independently documents `price` as "decimal probability, up to 3 decimal places" — the same convention as the read side, confirmed rather than merely corroborated. `novig_orders.order_body` rounds to 3dp per the documented constraint. |
| Order identity | **CONFIRMED (docs)** | An order targets an `outcomeId` (a UUID), never a market ID — matches the real `POST /emm/orders/place` schema field-for-field. The `index`-not-position warning from the original research stands for reading outcomes off a market; `order_body` itself just takes the id as given (via `request.venue_ticker`, reused from Kalshi's field). |
| Order READ endpoints | **CONFIRMED (docs), names + rate limits, response shape still not** | `emm/fills/all`, `emm/orders/all`, `emm/transactions` (32 burst / 512 per 60s), `emm/orders/{orderId}` (cancel, 512/s) — real paths and limits now known. The response FIELD NAMES for an order/fill object are still not — `venue_order_view` is deliberately not written for this reason; see `novig_orders.py` header. |
| **Order WRITE endpoint** | **CONFIRMED, field-level** | `POST https://api.novig.us/nbx/v2/emm/orders/place`, Bearer-token auth, body `{outcomeId, price, qty, currency, tif, ttl?, flags?}` — real schema with types, constraints and a worked `curl` example. `novig_orders.order_body()` implements this exactly, pure and unit-tested (16 tests, `tests/test_novig_orders.py`). |
| Order size unit | **CONFIRMED, and it's a DIFFERENT model from Kalshi's** | `qty` is MINIMAL CURRENCY UNITS, not a contract count — for `currency="CASH"`, 1 unit = $0.01 (independent of price, unlike Kalshi where price determines the contract count from a stake). A separate `currency="COIN"` denomination also exists, meaning and real-money-ness UNCONFIRMED. See `novig_orders.py`'s header for the full reasoning and the new open question this creates (below). |
| **NEW: does `qty` mean risked or to-win?** | **UNRESOLVED** | Not stated in anything supplied. `cash_units_for_stake` assumes RISKED (the conventional P2P-exchange reading), flagged as an assumption, not a confirmed fact — the one thing a future live order or a direct question to Novig should settle before real money moves. |
| **NEW: response shape of a placed order** | **UNCONFIRMED, but `submit_order` is BUILT AROUND that** | Only the HTTP status (201, "Order placed successfully") was supplied — no field names for the created order/wager object, and the docs' own words say a 201 means "placed in the QUEUE," not executed. `submit_order` (2026-08-24, `novig_orders.py`) reports every accepted order as `status: "submitted"` — never `"filled"` — and returns the whole decoded body as `raw_response` rather than parsing specific fields out of it. First real order is the verification step: read `response_keys`, THEN write `venue_order_view`. |
| **NEW: cancel endpoint's HTTP method** | **UNCONFIRMED** | Path confirmed (`{base}/emm/orders/{orderId}`, rate-limited 512/s); the rate-limit table names it "(Order cancellation)" without stating the verb. DELETE is assumed (REST convention), not read. |
| **NEW: rate limits** | **CONFIRMED, with one internal disagreement flagged** | Full table now known (order placement 64/s per one part of the source, 32/s per another part of the SAME source — noted, not silently picked; batch 64/s; cancel 512/s; kill-switch 1/30s; history tier 32 burst/512 sustained; everything else 256/s). **`Retry-After` and `X-RateLimit-Reset` on a 429 are MILLISECONDS, not seconds** — `novig_orders.backoff_seconds_from_headers` exists specifically because this is the same unit-trap shape as Kalshi's 100x price error. |
| **NEW: Novig's own kill switch** | **CONFIRMED to exist, not integrated** | `emm/kill`, rate-limited to once per 30s — a VENUE-SIDE panic button, structurally separate from this repo's `execution_guard.kill_switch_engaged()`. Not wired to anything; noted as a future integration candidate, not built. |
| Sandbox/demo environment | **CONFIRMED** | `PROD https://api.novig.us/nbx/v2`, **`QA https://api-qa.novig.us/nbx/v2`** — the QA host was previously unknown; `novig_client._QA_API_BASE` now records it, not yet wired into a `NOVIG_API_BASE`-style override the way `kalshi_client`'s Kalshi demo host is. |
| Auth mechanics beyond OAuth2 | **STRENGTHENED, still not fully closed** | The order-placement `curl` example shows a single `Authorization: Bearer $TOKEN` header and nothing else — no additional per-request signature field in the documented example, unlike Kalshi's RSA-PSS. This is stronger evidence than before that bearer-token-only is sufficient, but it is still evidence from a documented EXAMPLE, not a live call that actually succeeded. |

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
3. ~~**`novig_orders.py`, built AFTER an order-write endpoint is
   confirmed**~~ **DONE 2026-08-24.** The user supplied the real contract
   directly; `order_body()` and `cash_units_for_stake()` exist, pure and
   unit-tested (16 tests), matching `kalshi_orders.order_body_v2`'s own
   pattern of building from a real documented/supplied payload rather than
   inference. `submit_order` (the actual network call + response parsing) is
   still NOT written — the response shape of a placed order was not part of
   what was supplied, and guessing it now would repeat the exact mistake
   `kalshi_orders.py`'s header warns against, just one step later in the
   pipeline than before.
4. ~~**`novig_submitter()`**~~ **DONE 2026-08-24.** `novig_orders.submit_order`
   sends the real POST, handles 429s (backoff parsed correctly, ms→s),
   HTTP errors, network errors, and undecodable responses as named
   `NovigOrderError`s, and reports every accepted order as `submitted` —
   never `filled`, per the documented "placed in the queue" semantics.
   `novig_submitter` wires a price resolver to it, matching `kalshi_submitter`.
   30 tests, all mocked (`urllib.request.urlopen` — no network call from this
   session, same constraint as everywhere else in this lane).
5. **One `elif` in `_venue_submitter`.** Narrow-claim
   `pipeline/execute_portfolio.py` at this point, following the same
   released-stale-claim or explicit-narrow-claim precedent already used
   twice in this lane. **NOT YET DONE — this is the actual remaining gap**
   between "the adapter exists" and "the plan can place a real Novig order."
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
