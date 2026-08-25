# Kalshi and Polymarket: what we capture, what we drop, and why

**Measured 2026-08-25 against production.** Every number here is from a
production log line, named at the point it is used. Nothing is inferred from
the local checkout — `data/**` in git is a lossy mirror and cannot answer any
question on this page.

The brief was "we are playing whack-a-mole with these exchanges". That is
accurate, and the deep dive found the mechanism. It is **not** a missing market
grammar, which is what every previous round of work assumed. It is a **starved
fetch queue** on Kalshi and a **join that discards two thirds of an already-paid-for
feed** on Polymarket.

---

## 0. The one-paragraph answer

The two venues fail in opposite places. **Kalshi's gap is UPSTREAM**: we never
fetch most of the book, because registration is gated on a hand-written title
grammar and the fetch queue is monopolised by out-of-season series. **Polymarket's
gap is DOWNSTREAM**: we already fetch 12,897 sports markets every cycle and then
throw 8,000 of them away at the join. In both cases the durable artifact is a
*by-product of the join*, so nothing anywhere records what the venue actually
offered. That is the structural defect behind "whack-a-mole": coverage can only
grow one hand-written rule at a time, and nothing measures what is still missing.

---

## 1. KALSHI

### 1.1 The funnel, measured

| stage | count | source |
|---|---:|---|
| series in Kalshi's catalogue | 13,450 | `KALSHI_SERIES_CATALOGUE count=13450` |
| series whose ticker carries a sport token | ~1,132 | `KALSHI_SPORT` lines, summed |
| series REGISTERED for fetching | **191** | `TICK series_wanted=191` |
| markets actually stored | **883** | `TICK markets=883` |
| markets joined to the board | **4** | `BOARD_JOIN matched=4` |

Sport tokens, from `KALSHI_SPORT`: NBA 351, NFL 320, MLB 174, NCAAF 125, WNBA
91, NHL 51, NCAAB 20. (NBA's count includes WNBA series — the token scan is
longest-first but the *reported* figure is per token, so treat ~1,132 as an
upper bound.)

**191 of ~1,132 sports series, and 4 joined markets out of 883.**

### 1.2 Gate 1 — registration requires a hand-written title grammar

`auto_game_series_from_catalogue` registers a series only if
`game_market_from_title(title)` resolves, and `auto_series_from_catalogue`
registers a prop series only if the title matches `Player <stat>` AND
`canonical_market_key` resolves that stat. Everything else is invisible —
not refused, not counted, absent.

This is the whack-a-mole loop as written into the code: **a market family
becomes visible only after someone writes the phrase that names it.**

### 1.3 Gate 2 — THE STARVED QUEUE (the real one)

```
TICK series_wanted=191 due=191 fetched=12 cap=12 interval_s=120 markets=883
  this_tick={'KXATTENDMLB': (0,'series_filter'), 'KXMLBASGAME': (0,'series_filter'),
             'KXMLBFTGAME': (0,'series_filter'), 'KXMLBSTGAME': (0,'series_filter'),
             'KXMVENBAMULTIGAMEEXTENDED': (0,...), 'KXMVENBASINGLEGAME': (0,...),
             'KXMVENFLMULTIGAME': (0,...), 'KXMVENFLSINGLEGAME': (0,...),
             'KXNBA1HSPREAD': (0,...), 'KXNBA1HWINNER': (0,...),
             'KXNBA1QSPREAD': (0,...), 'KXNBA1QTOTAL': (0,...)}
  oldest_s=142655   trimmed=0
```

Read at 16:41:09Z and again at 16:56:45Z — **byte-identical, same twelve
series, all returning zero**. Attendance markets, the All-Star game, parlay
series, and NBA quarter lines in August. Meanwhile `oldest_s=142655` is
**39.6 hours** of stale prices on the series that do have markets.

**Mechanism.** `fetched_at` moved only when a fetch returned markets — correct
intent, to stop a *failure* blanking a series and starting its clock. But a
series with genuinely zero open markets never got stamped either. `_due_series`
then saw `age=None`, sorted it at `inf` ahead of everything, and it returned to
the front of the queue on every tick, permanently. Backoff cannot absorb it:
it lasts `min(interval, FAILED_RETRY_SECONDS)` = 120s, and ticks are ~15
minutes apart.

**The consequence that matters most: registering more series makes coverage
WORSE.** Each newly discovered out-of-season series joins the permanent front
of the queue. Discovery registering 171 game series actively starved the live
ones. Every previous attempt to widen coverage was pushing on the wrong end.

> **Fixed** in `d58cb0b8c`: the stamp follows the READ, not the payload. An
> empty read is `fetched`; `filter_ignored` and `failed` still leave the stamps
> disagreeing so backoff is untouched; an empty read keeps the last known
> markets rather than blanking them.

### 1.4 Gate 3 — the join

```
BOARD_JOIN kalshi_markets=883 board_rows=1290 matched=4
  reasons={'market_is_for_another_date': 532, 'unreadable_title': 216,
           'no_matching_board_row': 121, 'would_match_but_wrong_date': 10}
```

`event_not_on_our_board` is now **0** (was 20) after the date check was hoisted
above the event resolver — those were all stale-date games, not club-code alias
gaps. **There is no alias gap on this slate.**

`unreadable_title: 216` is itself two different facts sharing one counter.
From `JOIN_TITLES`, six of ten sampled series are **season futures**
("Will Minnesota be the 2026 AL Central Division Winner") — markets we would
never bet — sitting alongside markets we want and cannot parse. Futures are
separable without any title parsing: `KXMLBALCENT-26-MIN` carries no game date,
`KXMLBF5-26AUG241940TEXCWS-TIE` does.

### 1.5 Alt lines and ladders

A Kalshi *series* IS a ladder: one series holds every strike
(`KXMLBTOTAL-…-8`, `-9`, …). Because we fetch by series, **the whole ladder
arrives** — capture is not the problem. `_event_key` then keys on
`(event, market, line)`, so only the rungs our board already carries survive.
Every other rung is fetched, paid for, and dropped without record.

---

## 2. POLYMARKET

### 2.1 The funnel, measured

| stage | count | source |
|---|---:|---|
| sports markets fetched | **12,897** | `POLYMARKET_BOARD_JOIN markets=12897` |
| indexed as joinable game lines | **4,794** | `indexed=4794` |
| joined to the board | **73** | `matched=73` |

```
refusals={'market_type_not_a_game_line': 6838, 'segment_market_not_full_game': 1064,
          'board_market_not_a_game_line': 792, 'no_polymarket_market_for_league_date_market': 342,
          'outcomes_count_mismatch': 209, 'no_matching_polymarket_market': 54,
          'side_not_an_outcome_of_this_market': 29}
```

### 2.2 What is dropped, and it is already paid for

- **`market_type_not_a_game_line: 6,838`** — `SPORTS_MARKET_TYPE_PROP` and
  `DRAWABLE_OUTCOME`. **Polymarket player props exist, we fetch 6,838 of them
  every cycle, and we discard all of them.** Slugs like
  `astatc-nfl-lar-lac-2026-08-27-…`.
- **`segment_market_not_full_game: 1,064`** — quarter/half markets
  (`tsc-nfl-tb-jax-2026-08-28-1q…`), refused by `_has_segment`.
- **`outcomes_count_mismatch: 209`** — a real venue-side shape: two outcomes,
  one price. Worth a separate look; it is not a scope decision.

Unlike Kalshi, **nothing upstream needs to change**. The feed is already in
memory. The loss is entirely at the join.

### 2.3 Alt lines and ladders

Ladders are separate slugs distinguished by modifiers — `-8pt5`,
`gs-pos-4pt5`, `m1rh-neg-2pt5`. They are fetched and parsed
(`_line_from_modifiers`), then subject to the same constraint as Kalshi: only
rungs matching a board row survive.

### 2.4 The fetch boundary is sound

`find_first_game_offset` binary-searches the offset where the game block
begins rather than hardcoding it, because ids grow daily. 12,897 rows against
a 30 × 500 = 15,000 page budget, so the slate is not being truncated — but
that headroom is thin and should be watched as the book grows.

---

## 3. The structural defect

**Both venues' durable artifacts are by-products of the join.**

- Kalshi: `kalshi_markets.json` — merged, **undated**, capped at 6,000.
- Kalshi: `kalshi_market_history.json` — real movement tracking (48 points ×
  4,000 tickers), **undated path**, and only over the ~883 markets we fetch.
- Polymarket: `polymarket_us_games.json` — a single **undated current slate**.
  **There is no Polymarket movement history at all.**

So no artifact anywhere answers *"what did this venue offer, at what price, at
what time, on this date"* — which is precisely the question a CLV or
line-movement model needs, and the question that makes coverage gaps visible
instead of silent.

---

## 4. The solution: a venue-native daily odds layer

Invert the dependency. **Capture first, join second.** The artifact records what
the venue offered; the join becomes a consumer of it rather than its gatekeeper.

```
venue API ──► venue-native daily odds artifact (dated, complete, movement)
                          │
                          ├──► Layer 1 board  (prices, alt-line ladders)
                          └──► Layer 2 shortlist / edges / CLV
```

### 4.1 Artifact shape

One file per venue, per sport, per date:

```
reports/intelligence/venue_odds/<venue>/<sport>/<YYYY-MM-DD>.json
```

Split per sport because the keyvalue store refuses at 8 MB and
`layer2_shortlist` already occupies 5.0 MB of that budget
(`KEYVALUE_WRITE_LARGE size_bytes=5047682`). A single whole-book file would
start failing silently one sport from now.

Each row is **compact and venue-native** — the venue's own identifiers, not the
board's:

```json
{"id": "KXMLBGAME-26AUG251840BOSMIA-BOS", "series": "KXMLBGAME",
 "market": "h2h", "line": null, "side": "BOS",
 "event": "26AUG251840BOSMIA", "game_date": "2026-08-25",
 "points": [{"t": "2026-08-25T16:41:09Z", "yes": 0.52, "no": 0.49}]}
```

Rules, each of which exists because of a failure already on record:

1. **Every market the venue listed for a sport is a row**, joined or not. A
   market we cannot yet parse is stored with `market: null` and its raw title,
   so tomorrow's grammar can be written from data instead of guesses.
2. **Points append intraday, capped per market** (48, as `kalshi_board`
   already does) and trimmed loudly.
3. **The date token is the GAME date**, from the ticker/slug — never
   `close_time`, which is a settlement deadline days later, and which once
   refused 100% of a slate.
4. **A dated path takes a 10-day keyvalue TTL.** That is acceptable for the
   daily file and NOT for the opening line, so openings continue to live in
   the undated `clv_opening_ledger`.
5. **Coverage is reported per sport on every write** — listed, parsed,
   unparsed-by-family. A gap becomes a number rather than a silence.

### 4.2 Why this ends the whack-a-mole

Today, an unparsed market family is *invisible*: not refused, not counted, not
stored. The only way to discover it is for a human to notice a market on the
venue's website. With capture-first, an unparsed family is a **counted row with
its raw title**, so:

- coverage is measurable per sport per venue, continuously;
- a new grammar is written against real strings, never invented ones (three
  invented grammars matched none of production and left 302 markets unreadable);
- the ladder is retained whole, so alt-line coverage stops depending on whether
  OddsAPI happened to carry that rung.

### 4.3 Order of work

1. ~~Kalshi queue starvation~~ — **done, `d58cb0b8c`**. Nothing else matters
   until the queue rotates; every other fix would be measured through 39.6-hour-old prices.
2. Kalshi: separate futures from unparseable via the ticker's game date, so
   `unreadable_title` becomes a real number.
3. The daily odds writer, both venues, capture-first. Kalshi's
   `record_snapshot` is the working prototype — generalise it rather than
   inventing a second one.
4. Polymarket: stop discarding 6,838 props and 1,064 segment markets at the
   join; they are already fetched.
5. Widen Kalshi registration once the queue rotates and coverage is
   measurable — in that order, because registration without rotation makes it
   worse.
