# Crypto.com as a THIRD end-to-end venue — evaluation, 2026-08-28

> Requested: "evaluate crypto.com for integration into our portfolio betting
> platform — do not wire anything but examine how we have Kalshi and Poly setup
> and document if this is a 3rd end to end option."
> Source given: `https://crypto.com/exchange-pro/en-US/api`
>
> **NOTHING WAS WIRED. NO CODE CHANGED. NOTHING DEPLOYED.** This session ran
> from a LOCAL machine with full egress, so every venue reading below is a
> live HTTP response, not research. The prior evaluation
> (`cryptocom_client.py`, 2026-08-24) was written from a cloud sandbox whose
> proxy 403s CONNECT to `crypto.com` — it could not read the page it was
> reasoning about. That difference matters and produced one correction (§5).

## VERDICT

**Still no — but for one reason, not four, and one of my first four was wrong.**

**CORRECTED 2026-08-28 ~15:0x CDT, after the user pointed at
`https://crypto.com/us/sports`.** My first pass said "sports is not named
anywhere on that page." That was true of the *exchange-pro API page*, and I let
it read as a claim about the venue. **It is not.** Sports is a first-class
Crypto.com Predictions category, the product is deep and live, and I have now
read its market data directly. §1a–§1d replace the old §1.

What survives the correction, and is decisive on its own: **the only
machine-readable sports surface is the web app's own Cloudflare-gated internal
proxy.** A Render worker cannot read it — measured, 403, twice (§1c). There is
no documented API, no credential path short of a sales conversation, and no
OddsAPI row (§4). The venue is *attractive*; the **access** is the blocker.

**Recommendation: one business action, no engineering.** Use the
"Get Prediction Markets Data" contact form on
`crypto.com/exchange-pro/en-US/api` and ask for Predictions REST covering
sports. That is the only thing standing between this and a real evaluation, and
it is the user's call, not a code task. **Do not build a browser-driven
scraper** — §1d says why that is the wrong answer even though it demonstrably
works.

---

## 1a. The product is real, deep, and priced like Kalshi — READ LIVE

Read from `web.crypto.com` on 2026-08-28, in a real browser session:

- **Leagues offered:** Baseball, Soccer, Football, Golf, Basketball, Tennis,
  Esports, Motorsports, Fighting, Sailing, Hockey.
- **A real game, tonight:** `Boston @ New York Y`, Yankee Stadium,
  Aug 28 6:15 pm CDT — **BOS $0.42 / NYY $0.59**, with a price chart.
- **Unit convention is IDENTICAL to Kalshi**: "You receive a US$1 return per
  contract if your prediction is correct." A price in dollars **is** the
  probability. `kalshi_client`'s `dollars_to_probability` /
  `dollars_to_american` would port unchanged — the one place a new venue
  usually costs a 100× error, this one would not.
- **Vig is thin**: 0.42 + 0.59 = **1.01**, ~1 point. Competitive with Kalshi.
- **Liquidity is real**: one MLB game carried `cumulative_traded_usd`
  **"1370106.22"**.
- **Regulated**: "a derivatives product offered by Crypto.com｜Derivatives North
  America, a CFTC-regulated exchange", available nationwide.

On the merits of the venue this is a legitimate third exchange. The problem is
purely how to read it.

**One coverage caveat, and it matters for the board.** The MLB game page offers
**"Winner" only** — two contracts, `MLB-...-M-RedSox-O11` and
`MLB-...-M-Yankees-O12`. No spread, no total, no player prop was observed at
game level. This platform's board is h2h **plus** spreads, totals and props, so
even with perfect access the joinable surface may be moneyline-shaped. Not
fully surveyed — flagged, not concluded.

## 1b. There IS a JSON events endpoint — I found it and read it

Not documented anywhere. Discovered by watching the app's own network traffic:

```
GET https://web.crypto.com/api/proxy/public/knock-out/predictions/public/api/v1/events?limit=200
→ 200, application/json, 200 rows
   {"code":0,"message":"success","data":{"has_more":true,"data":[...]}}
```

Row shape (41 fields) is genuinely usable: `id`, `event_kind` ("MLB"),
`event_kind_asset_type` ("sports"), `event_type` (`match` 173 / `league` 27),
`title` ("Cleveland @ Los Angeles A"), `event_date`, `venue`, `status`,
`game_status`, `slug`, `close_date`, `cumulative_traded_usd`,
`rolling_24h_traded_usd`. 46 of the 200 were future-dated. Sibling endpoints:
`contract-availability` (returns `asset_type: "sports"`, `status: "available"`)
and `events/{uuid}`.

**This falsifies the flat "no public API has shipped" line** in
`cryptocom_client.py`'s `FINDING`, and my own first pass with it. An endpoint
exists and it serves sports. Three things then take it away again:

- **It carries no prices.** No bid, no ask, no size, no contract list — the
  event row stops at metadata. Contract prices are server-rendered into the
  Next.js RSC payload of the detail page. The only price JSON is a per-symbol
  sparkline —
  `.../coin-price-prediction/public/api/v1/predictions/charts?symbol=MLB-00008-260828-M-Yankees-O12_...&timeframe=all`
  — which returned **two points** for timeframe `all`:
  `[{"timestamp":1787875200,"value":"61"},{"timestamp":1787944740,"value":"59"}]`.
  That is a chart, not a quote.
- **Its filters are silently ignored.** `?kind=SPORTS` and `?kind=COMPANIES`
  returned **byte-identical 15,922-byte MLB payloads**. This repo's own scope
  doc names that exact behaviour as the worst kind of failure: the request
  succeeds, the filter is dropped, and a series looks empty when it is not.
  Only `limit` is honoured — and its own error text disagrees with itself
  ("between 1 and 2" and "between 1 and 20" on consecutive calls, while
  `limit=200` served 200 rows).
- **The proxy is an allowlist.** `markets`, `contracts`, `orderbook`, `quotes`,
  `tickers`, `instruments`, `leagues`, `categories` all →
  `403 {"code":-1,"message":"Invalid proxy path or method"}`. There is no
  undiscovered price path to find; the surface is exactly what the app calls.

## 1c. THE BLOCKER: Cloudflare. A worker cannot read it — measured twice

| client | result |
|---|---|
| real browser session (`cf_clearance` from the JS challenge) | **200 JSON** |
| `curl`, plain | **403** — Cloudflare "Attention Required!" HTML |
| `curl` + Chrome UA, `Accept`, `Accept-Language`, `Referer`, `sec-ch-ua`, `sec-fetch-*` | **403** — same HTML |

Both 403s were captured against the same endpoint minutes after the browser got
200 from it. `refresh-worker` and `live-odds-worker` fetch with
`urllib.request`; they would get that HTML. A fetcher returning HTML where JSON
was expected is precisely what `kalshi_client`'s header was written to prevent —
**an empty result indistinguishable from a venue that lists nothing.**

Kalshi's `api.elections.kalshi.com` and Polymarket's `gamma-api` /
`clob.polymarket.com` all answer a plain server-side GET (verified 2026-08-26,
`findings_2026-08-26_venue_api_unblock.md`). Crypto.com does not. That is the
whole difference between two integrated venues and this one.

## 1d. Why a browser-driven scraper is the wrong answer even though it works

It works — every reading in §1a and §1b came out of one. It should not ship:

- **It is the app's private BFF, not an API.** No contract, no versioning, no
  deprecation notice. The allowlist and the RSC payload shape can change in any
  frontend deploy, and the failure would be silent.
- **Prices still would not be in it.** Even granted the session, the quote a
  portfolio decision needs is rendered into an RSC payload — so the "adapter"
  is an HTML/flight-payload parser priced off a two-point sparkline. That
  cannot feed `venue_quote_fanin`, and it certainly cannot back an order.
- **It defeats a Cloudflare bot control on someone else's site.** That is a
  ToS question for the user before it is an engineering one — and the honest
  version of that question is just the contact form.
- **A headless browser does not fit the runtime.** §3's argument against FIX
  applies with equal force to a Chromium process inside a 2–4GB worker that
  reboots on every deploy.

## 2. The API page contradicts itself about REST — quoted, both places

Read directly from the served HTML of `crypto.com/exchange-pro/en-US/api`:

**Platform-coverage table:**

```
DCM (Predictions) | REST Coming soon | WebSocket Coming soon | FIX Available
FCM (Predictions) | REST Coming soon | WebSocket Coming soon | FIX Available
```

**"Prediction markets data" showcase section, ~400 words later:**

```
Access: REST API — Available | WebSocket — Coming soon
```

Same page, same load. The public REST catalogue
(`api.crypto.com/exchange/v1/public/get-instruments`, HTTP 200, 530,758 bytes)
holds **957 instruments — 578 `CCY_PAIR`, 367 `PERPETUAL_SWAP`, 12 `FUTURE`,
zero event contracts**: a crypto-derivatives schema with no event, outcome or
resolution field. And the page's own documented sample path has no host that
answers it — `api.crypto.com/api/v1/predictions/events?kind=COMPANIES` → 404
`{"code":"10004","msg":"BAD_REQUEST"}`; `predictions.crypto.com` and
`api.predictions.crypto.com` do not resolve;
`api.crypto.com/exchange/v1/public/get-prediction-instruments` → 404;
`exchange-docs.crypto.com` → a 167-byte JS shell with **zero** occurrences of
"prediction".

So the *documented institutional* surface genuinely does not serve sports
predictions over REST today. §1b's endpoint is a different thing entirely — the
consumer app's own proxy — and neither the marketing page nor the docs mention
it.

Note what the marketing page's coverage claim actually is: predictions across
**crypto, politics and economics**. Sports is absent from *that page* while
being a headline category of the product (§1a). The API page describes the
DCM/FCM institutional feed, not the consumer sports book. **Neither one is
evidence about the other** — that conflation is what my first pass got wrong,
and it is the general trap for anyone re-checking this later.

## 3. FIX is the wrong shape for every seam we have

FIX is the one Predictions protocol the coverage table marks Available. It is a
persistent-session binary protocol for institutional order routing.
`venue_quote_adapters.py`'s first line is the constraint it violates:

> "One adapter per odds source. Each reads an ARTIFACT, never a venue API."

Every venue price in this platform arrives as a periodic HTTP pull written to a
dated artifact by a worker, on the venue's own cadence
(`pipeline/venue_odds_loop.py`). A FIX venue would need a long-lived session, a
new binary-protocol dependency, a session/sequence-number manager, and a
process that holds a socket open — inside a worker that reboots on every
deploy. That is not a new adapter; it is a new runtime.

Also: the page says the audience is **"institutions, market makers and data
partners"**, and the Predictions CTA is a *contact form* ("Get Prediction
Markets Data"), not a signup. Both Kalshi and Polymarket US are self-serve.
This is a commercial-agreement gate before it is an engineering one — the same
wall ProphetX is already stuck behind (`lanes.md
[exchange-markets-api-integration]`: "blocked on a partner credential with no
self-serve path").

## 4. No aggregator fallback — OddsAPI does not carry it

`us_ex` region bookmaker keys: `betopenly`, `kalshi`, `novig`, `polymarket`,
`prophetx`. **No crypto.com, CDNA, OG.com, or Crypto.com Predictions entry.**

This closes the one cheap door. `novig` and `prophetx` have no direct feed and
still price, because OddsAPI carries them — `book_shortlist.DEFAULT_BOOKS`
lists them and `DIRECT_FEED_BOOKS` deliberately does not. Crypto.com would get
neither treatment: it has no aggregator row AND no reachable direct feed. It
cannot appear on the board at all, in any mode, by any existing path.

## 5. CORRECTION to the record — `cryptocom_client.py`'s stated premise is wrong

`syndicate/features/shared/cryptocom_client.py`, `FINDING["rejected_source"]`,
says:

> "A third-party marketing site advertised `GET /api/v1/predictions/events?kind=COMPANIES`.
> NOT implemented — **uncorroborated by any Crypto.com-owned source** …"

**That endpoint is printed on Crypto.com's own page**, in the hero terminal
sample, under the comment `# Predictions — market data`, with a response body
whose example row is `{"id": "8741d85d-…", "title": "OpenAI IPO Date", "kind":
"COMPANIES", "type": "league", "status": "active", "contracts_count": 2}`. The
"third-party marketing site" was quoting Crypto.com, not inventing.

**The DECISION was right; the REASON given for it is false.** That distinction
is the standing rule from `learnings.md` (2026-08-28: *FORBIDDEN: trusting a
refusal's stated premise without rechecking it*) — a future session reading
that docstring would believe a Crypto.com-owned endpoint had been shown not to
exist, when what is actually true is stronger and different: **it is
Crypto.com's own documented sample and no public host answers it** (§1). The
example row is also evidence for §1's conclusion, not against it — `kind` is
`COMPANIES`, `title` is an IPO date. It is not a sports surface.

Two smaller items in the same `FINDING` are now upgraded from inference to
measurement: `confidence` says the "coming soon" claim is "search-snippet only,
the agent proxy denied a direct read" — it has now been read directly (§2), and
the truth is *the page says both things*. And `probe()`'s stated unblock signal
("HTML that mentions a live REST path") **would fire today and would be wrong**
— the page mentions a REST path and marks it Available in one place, while no
host serves it. That probe needs a stricter bar (§7).

**And the headline `status` is now falsified, not merely under-evidenced.**
`FINDING["status"] = "no_public_api_yet"` with "No public REST/WebSocket
market-data API has shipped" is wrong as written: a JSON endpoint serving
sports events exists and was read (§1b). The *conclusion* — do not build
against it — still holds, for the reasons in §1b–§1d, but the record should say
**"an undocumented, Cloudflare-gated, price-less app proxy exists; no
sanctioned server-readable API does"**, because those two statements send a
future session to completely different places.

**FIXED 2026-08-28, on explicit user instruction** ("fix the cryptocom_client.py
finding with what you found"), under lane `cryptocom-finding-correction`. The
files are claimed by `exchange-markets-api-integration` (`lanes.md`, OPEN, goal
complete, idle, session `71a74bb7` gone); the cross-lane edit and its override
are logged in that lane block rather than made silently. Scope held to three
files — `cryptocom_client.py`, `scripts/probe_cryptocom.py`,
`tests/test_cryptocom_client.py`. The other lane's five sibling venue clients
are untouched.

What changed:

- `FINDING["status"]`: `no_public_api_yet` → **`no_sanctioned_server_readable_api`**,
  and `product` → `cryptocom_predictions_sports_event_contracts`. The whole
  ten-item `measured_2026_08_28` block is new, carrying every reading in §1a–§1c.
- `rejected_source` → **`corrected_source`**, stating that the endpoint is
  Crypto.com's own documented sample and is dead (no host answers it), rather
  than a stranger's invention. Still NAMED, so it cannot read as never
  considered.
- New `coverage_caveat` (moneyline-only at game level) and a rewritten
  `open_question` (Predictions / Predict / OG.com brand boundary), both carrying
  the `polymarket_us_markets` two-exchanges precedent as the reason they must be
  settled before any build.
- **`probe()` no longer lets any page's prose decide anything.** It reads the
  two surfaces that can be true or false, and returns `unblocked` — default
  False, flipped only by a non-crypto `inst_type` in the *sanctioned* Exchange
  catalogue, counted over rows via `CRYPTO_DERIVATIVE_INSTRUMENT_TYPES`, never
  grepped. The app proxy is recorded and can never unblock. An HTML body is
  named (`looks_like_bot_challenge`), not parsed as empty.
- `status == "error"` now means *no check reached the venue*, distinct from
  *the venue answered and the answer was no* — the flat `error` key is
  preserved for the probe scripts.

Verified: `python -m pytest tests/test_cryptocom_client.py tests/test_probe_exchange_markets.py`
→ **16 passed**, including an off≠on pair proving the gate flips
(`test_probe_unblocks_only_on_a_non_crypto_instrument` against
`test_probe_reports_blocked_when_the_catalogue_is_all_crypto`). The old
assertions were confirmed to FAIL against the new module before being replaced.

Live run, 2026-08-28 ~15:2x CDT:

```
[cryptocom] PROBE status=ok unblocked=False reason=exchange_rest_lists_no_event_contracts
[cryptocom] EXCHANGE_REST http=200 instruments=957 non_crypto=0 by_type={"CCY_PAIR": 578, "PERPETUAL_SWAP": 367, "FUTURE": 12}
[cryptocom] APP_PROXY http=None error=http_403 interpretation=unreadable_server_side:http_403
```

Nothing committed and nothing deployed; no deploy claim taken.

---

## 6. How Kalshi and Polymarket are actually set up — the bar "end-to-end" means

**~13,400 lines across 42 shared modules touch both venue names.** "End to end"
in this repo is not a client; it is sixteen seams, each of which exists because
something broke without it. A third venue must fill every one.

### The stack, in pipeline order

| # | Layer | Kalshi | Polymarket | What it owns |
|---|---|---|---|---|
| 1 | Read client | `kalshi_client.py` (655) | `polymarket_client.py` (416) + `polymarket_us_sports_client.py` (250) | public market data; `probe()` reports the RAW shape, never a parse |
| 2 | Discovery | `pipeline/kalshi_discovery.py` (245) | — | what the venue lists, once per boot |
| 3 | Scheduled price refresh | `pipeline/kalshi_odds_refresh.py` (1525) | `pipeline/polymarket_odds_refresh.py` (258) | venue-cadence artifact; persisted stamp so a reboot cannot reset the clock |
| 4 | Loop owner | `pipeline/venue_odds_loop.py` (206) | same | the venue's cadence, not the board build's |
| 5 | Catalogue | `kalshi_catalogue.py` (1269) | `polymarket_us_markets.py` (1648) | series ↔ sport/market registry |
| 6 | Board join | `kalshi_board_join.py` (978) | `polymarket_board_join.py` (1334) | venue market ↔ our board row, incl. side vocabulary |
| 7 | Venue-native board | `kalshi_board.py` (342) | — | immutable opening line + bounded movement history, for CLV |
| 8 | Quote adapter / fan-in | `venue_quote_adapters.py` (1303), `venue_quote_fanin.py` (1097) | same | artifact → priced candidate |
| 9 | Daily odds capture | `venue_daily_odds.py` (643) | same | dated capture independent of the join |
| 10 | Book identity | `book_shortlist.py` — `DEFAULT_BOOKS`, `DIRECT_FEED_BOOKS` | same | the ONE owner of "can this operator bet here" |
| 11 | Auth | `kalshi_auth.py` (381) — RSA-PSS per request | `polymarket_us_auth.py` (301) — Ed25519 | no credential ⇒ named refusal, never a half-built client |
| 12 | Order adapter | `kalshi_orders.py` (1537) | `polymarket_us_orders.py` (1130) | the ONLY file that knows the venue's units |
| 13 | Execution spine | `execution_ledger.place_order` / `_venue_reader:1123` | same | record → submit → complete; adapter chosen by venue name |
| 14 | Submitter dispatch | `pipeline/execute_portfolio.py:529 _venue_submitter` | same | **returns `None` for an unknown venue — refuses, never falls through** |
| 15 | Caps & guard | `execution_limits_settings.VENUES = ("kalshi","polymarket")`, `execution_guard.py` | same | per-venue day dollars / day orders |
| 16 | States, balances, settlement | `venue_order_states.py` (86), `venue_balances.py` (475), `venue_settlement.py` (960), `paper_settlement.py` (1286) | same | one status vocabulary; settle from the venue's own record |

### The four rules a third venue inherits — each paid for

- **A wrong schema guess is the default expectation.** `kalshi_client`'s first
  live run corrected **10 of 17 field names and a 100× price-unit error** —
  caught only because `probe()` reports the shape instead of parsing it. Every
  assumption lives in ONE named constant; nothing is read positionally.
- **An empty list is never an answer.** A failed fetch raises a named
  `<Venue>Error`. "Venue lists nothing" and "our fetcher broke" are the same
  observation otherwise — that confusion cost 3.8 points of misattributed
  Kalshi board coverage on 2026-08-23.
- **Never port another venue's vocabulary.** Kalshi has no `no` side (an UNDER
  is an ASK at the complement); Polymarket US has a real
  `OUTCOME_SIDE_NO` + `ORDER_ACTION_BUY`. Copying Kalshi's inversion to
  Polymarket would have sent *sell YES at 1−p* where *buy NO at p* was meant —
  a real order, a different position, entirely plausible in a log.
- **A gap in the READ side is a latch, not a missing feature.** Polymarket
  shipped without one; an unreconciled order then blocked live mode on
  **every** venue, and nothing in the system could clear it
  (`execution_ledger.py:1123` header, measured 2026-08-25T16:40Z).

There is also a venue-identity trap worth naming for any future third venue:
Polymarket needed **two separate modules for two exchanges under one brand**
(`gamma-api.polymarket.com` global vs `api.polymarket.us`), because an account
funded on one is not funded on the other — pricing off the global book and
filling on the US venue "does not fail; it produces plausible edges against
prices that do not exist where the order lands." Crypto.com has exactly this
shape already: the international in-app **Predict** feature, the US **CDNA**
DCM/FCM, and the spun-out **OG.com** are three brandings whose boundaries this
session could not resolve either. If it is ever built, that ambiguity must be
settled BEFORE a line of code, not after.

---

## 7. What would change the answer, and the watch that costs nothing

Two of the three gates I first wrote are now **already met** — §1a settles
"sports is covered", §1b settles "a JSON sports endpoint exists". What remains
is a single gate, and it is the one that was always doing the work:

**A sports market-data endpoint that answers a plain server-side GET, with a
price in the body.** Three parts, all required:

1. **Reachable without a browser.** The bar is a `urllib.request` GET from a
   worker returning 200 JSON — not 403 Cloudflare HTML (§1c). This is the gate.
2. **Carries a quote, not a chart.** A bid/ask (or at minimum a current price)
   per contract, in a listing response. The events endpoint has none and the
   sparkline is two points (§1b).
3. **Sanctioned.** Either a documented public API, or credentials from the
   contact form. The app's internal proxy is neither (§1d).

**The existing probe would report a false positive today, twice over.**
`cryptocom_client.probe()`'s stated unblock signal is "HTML that mentions a live
REST path" — the marketing page mentions one and marks it Available while no
host serves it (§2). And a future session that finds §1b's endpoint from a
browser would wrongly read it as unblocked. The correct bar is **a live 200,
from a plain server-side HTTP client, whose parsed body contains a sports
contract WITH A PRICE**; until all three hold the honest report stays
`no_public_api_yet`, regardless of what any page says.

The recommended investment is not code. It is **one contact-form submission**
(see VERDICT), plus that stricter probe re-run monthly.

## 8. Files read (nothing modified)

`cryptocom_client.py`, `probe_cryptocom.py`, `kalshi_client.py`,
`kalshi_auth.py`, `kalshi_orders.py`, `kalshi_board.py`, `kalshi_odds_refresh.py`,
`polymarket_us_{auth,markets,orders}.py`, `polymarket_client.py`,
`book_shortlist.py`, `execution_ledger.py`, `execute_portfolio.py`,
`execution_limits_settings.py`, `venue_{quote_adapters,quote_fanin,settlement,balances,order_states,daily_odds}.py`,
`venue_odds_loop.py`, `paper_settlement.py`,
`.syndicate/scope_2026-08-24_exchange_markets_api_integration.md`,
`.syndicate/findings_2026-08-26_venue_api_unblock.md`, `lanes.md:1573`.
