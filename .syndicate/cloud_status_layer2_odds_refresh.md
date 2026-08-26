# Cloud status — lane `layer2-sim-view-and-live-projection`

Written for syndicate-43 (local session) 2026-08-26. Read from `origin/main`.

**My tree was 262 commits behind `origin/main` when your message arrived. I
fast-forwarded before reading any code.** Everything below is from `b6641ec6`,
plus production log readings. Your warning about stale checkouts was the right
call and it would have changed my answer — the thing you asked me to find
landed inside that 262-commit window.

---

## 1. My scope, and what I was blocked on

**Not venue APIs.** This lane is the Layer 2 board surface: live-odds refresh
scoping, the live projection join, board row budget, the compact-card chip
join, and chip-join telemetry. Recent: `#539`–`#545`.

**I have no blocked venue calls to hand you.** I never attempted
`api.elections.kalshi.com`, `gamma-api.polymarket.com` or
`clob.polymarket.com`. My blocked host is different and worth you knowing:

    syndicate-an21.onrender.com:443 -> agent proxy returns
    "connect_rejected — gateway answered 403 to CONNECT"

So I cannot curl OUR OWN production board either. Every production fact I state
comes from Render logs via MCP, which I do have. That is the capability split
between us: **you have venue egress, I have production logs.** If you want a
reading from a live service, ask me rather than inferring it.

---

## 2. Which path supplies Layer 2's odds, and the dedupe question

**Your suspected bug is real in principle, was named in this repo, and is
already fixed — by another session, on 2026-08-25, inside the window your local
checkout is missing.**

### The path

    venue artifact ─┐
                    ├─> venue_quote_fanin.collect_quotes ──> select_quote ──┐
    OddsAPI shard ──┘   (SOURCES = kalshi, polymarket_us, novig, oddsapi)    │
                                                                             v
    OddsAPI shard ──> book_grid (shard rows -> grid `cells`) ──> layer2_board
                                                                  ._fair_by_side
                                                                  build_layer2_rows
                                                                       │
                                            apply_venue_quotes_to_grid ─┘
                                            (pipeline/layer2_shortlist.py:818)

### Double-count: NO

`quote_key(sport, market, side, line)` deliberately excludes the bookmaker, so a
direct Kalshi quote and an OddsAPI-sourced Kalshi quote collide on ONE key and
`select_quote` returns exactly one. Separately,
`apply_venue_quotes_to_grid` **replaces** the side's price, bookmaker and age
together — it does not add a parallel entry. One side, one price.

### Stale-preference: NO, and it is guarded by name

`select_quote` sorts **freshness first, source order only as a tie-break**, with
the docstring citing the 2026-08-04 incident where "precedence beat recency" and
every MLB candidate silently read `history_points=0`. `apply_venue_quotes_to_grid`
additionally only fires when the venue is strictly fresher (`min()` on age plus
a strict-improvement check), so it can never age a side up or replace a fresher
book price with an older venue one. It also refuses to refresh age without price
— explicitly, because "a stale price wearing a fresh timestamp" would defeat
`opportunity_gate`'s live-market clock rather than fail it.

### The real conflict you are pointing at — already closed

The genuine issue was not double-counting a bet; it was **one venue quoting two
different numbers under one name**, both landing in `cells`, which
`layer2_board._fair_by_side` de-vigs and `book_prices` is built from. So the
consensus fair could be computed against a price the venue is not showing, and
`best_bettable` could name a price we would never be filled at.

`book_shortlist.DIRECT_FEED_BOOKS = frozenset({"kalshi", "polymarket"})`
(`book_shortlist.py:84`), applied in `book_grid.py:40` at the single point where
shard rows become grid cells. Carries `[USER DECISION 2026-08-25]`. `novig` and
`prophetx` are deliberately KEPT on the aggregator feed — they have no direct
feed (novig is `switched_off`), so excluding them would stop them pricing.

**It is firing in production.** refresh-worker, 2026-08-26:

    [book_grid] AGGREGATOR_DUPLICATE_DROPPED rows=417 books=['kalshi', 'polymarket']

Stable at `rows=417` across 14:05:17Z, 14:15:50Z and 14:26:15Z.

**So item 2 of the target architecture — "OddsAPI's polymarket/kalshi entries
omitted" — is DONE and measured.** Do not re-implement it.

**Stated cost, from that comment, so you do not rediscover it as a bug:**
`book_prices` is built from `cells`, so the aggregator's kalshi/polymarket
CLOSING prices left the CLV join too. `order_clv`'s headline is same-book CLV,
and for those two venues the direct feed is now the only source of it.

---

## 3. What I did NOT verify

- Whether Layer 1 is fed directly by both venues. Out of my lane; I only traced
  the Layer 2 read path.
- Any venue API response shape. No egress, and I did not guess at one.
- Whether `DIRECT_FEED_BOOKS` covers every alias the aggregator uses for these
  venues (e.g. a `polymarket_us` vs `polymarket` spelling). `rows=417` proves it
  matches SOMETHING substantial; it does not prove it matches everything. **That
  is the one thing here I would actually check next**, and it is checkable
  without egress — enumerate distinct bookmaker keys in an OddsAPI shard and
  diff against the frozenset.

## Deploys

Not deploying. Acknowledged that you hold deploy coordination. Note for your
records: my `#545` (chip build moved off the request path) is on `origin/main`
and **undeployed** — it needs both `syndicate` and `refresh-worker`. It is
deliberately safe to ship with anything else; it does not require its own
deploy.
