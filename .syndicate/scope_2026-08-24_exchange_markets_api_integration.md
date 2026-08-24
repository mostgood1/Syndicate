# SCOPE — market/odds pull for six prediction/event-market venues

Drafted 2026-08-24 in response to: "another session is working on Kalshi and
getting the full integration end to end done. This session focuses on other
exchange markets, starting with pulling all markets/odds via APIs. Once we
have each of these, we will focus on the end-to-end order automation to
replicate the Kalshi work." Venues: coinbase, prophetx, novig, polymarket,
robinhood, crypto.com ("OG").

**This lane builds ONE layer only: `kalshi_client.py`'s layer.** Read-only,
unauthenticated-where-possible, single-place schema assumption, `probe()`
reports the shape that actually came back rather than parsing blind. It does
NOT build `kalshi_auth.py`'s signed-order layer, `kalshi_odds_refresh.py`'s
scheduled-artifact-cache layer, `kalshi_board.py`'s board-join layer, or
`venue_scope.py`'s repricing layer. Those are the "end-to-end order
automation" phase the user named as next, and Kalshi's own build is the
reference to converge on when that phase starts.

---

## 0. The standing constraint this lane inherited from Kalshi's build

**Every venue host 403s CONNECT through this session's agent proxy** —
confirmed 2026-08-24 for all six (`exchange.coinbase.com`, `clob.polymarket.com`
/ `gamma-api.polymarket.com`, `api.novig.us`, `api.prophetx.co`,
`api.robinhood.com`, `api.crypto.com`), the same denial `kalshi_client.py`'s
header records for Kalshi's hosts. So none of this can be verified against a
live response from this sandbox. `kalshi_client`'s first live run (from
refresh-worker, which has real outbound access) corrected 10 of 17 field names
and a 100x price-unit error versus what was written blind. **Assume the same
error rate here — six times over — and build so a wrong assumption is cheap to
find and fix, never silently wrong:**

- Every schema assumption lives in ONE named constant per module
  (`_MARKET_FIELDS`, `_BASE_URLS`), nothing read positionally.
- `probe()` in every module reports `top_level_keys` / `market_keys` /
  `expected_but_absent` / `present_but_unexpected` from a real live call,
  never a parsed/assumed result.
- A failed fetch raises a NAMED error (`<Venue>Error`), never returns an empty
  list — an empty list is indistinguishable from "this venue lists nothing"
  and that confusion is exactly what cost the board 3.8 points of misattributed
  Kalshi coverage on 2026-08-23 (`state.md`, `kalshi_client.py` header).
- Price/odds fields are converted to American odds through a function whose
  UNIT ASSUMPTION is named and tested against hand-computed values — never
  assumed to match Kalshi's dollars-as-probability convention, because it
  probably won't (see venue table below).
- `scripts/probe_<venue>.py` exists for every module so the first production
  run (from refresh-worker, once this lands) is a one-command verification,
  identical in spirit to `scripts/probe_kalshi.py`.

## 1. Per-venue research findings (from this session, WebSearch/WebFetch —
   still UNVERIFIED against a live authenticated response; see §0)

Filled in per venue below as research completes. Each entry: product status,
base URL(s), endpoint(s), field names + price units, auth requirement, docs
citation, confidence.

## 2. What "pulling all markets/odds" means at this layer

For each venue, minimally:
- `fetch_markets(...)` — list open markets/contracts, normalized, paginated
  where the API supports it, with a `missing_fields` accounting per row so a
  wrong field-name guess is visible on the first live run instead of a
  silently-empty column.
- `normalize_market(raw)` — one row -> our shape, price converted to a
  probability AND to American odds via a named, tested conversion.
- `probe(...)` — raw-shape report, no parsing.
- No venue with no discoverable public API gets a fabricated one. If research
  finds the venue has NO public/unauthenticated market-data surface (a real
  possibility for ProphetX, Novig, Robinhood — all smaller or reseller
  products), that is reported AS the finding, same discipline `kalshi_client`
  used for `discover_series`'s "the endpoint is UNVERIFIED" note. A refusal by
  name beats a module that pretends to work.

## 3. Deliberately out of scope this lane

- Order placement, credentials that can write, account/balance reads.
- Scheduled artifact caching / TTL-backed refresh (`kalshi_odds_refresh.py`'s
  layer) — comes with the automation phase, once these six clients exist and
  their actual coverage is known.
- Board join / venue repricing (`kalshi_board.py`, `venue_scope.py`'s layer).
- `HOT_ARTIFACT_PATTERNS` allowlisting — nothing here writes a
  worker-to-web artifact yet.
