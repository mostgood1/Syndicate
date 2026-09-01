"""What is exchange price-shopping worth on MLB GAME markets? (item 05 / `#624`)

RESULT, 2026-09-01, 2026-08-22..08-31, n=621 settled MLB game-market paper
orders. The headline is that **most of the improvement item 05 priced is
already banked**, and what is left is worth about three quarters of a point.

    per-side entry cost the book ACTUALLY PAID   0.88pp
    two-way hold on the quotes it paid into        1.96%
    exchanges make available on this population  +1.579pp
      of which the board ALREADY TOOK            +0.977pp  (62%)
      of which is still on the table             +0.602pp
      of THAT, held at a venue we can execute on  36%      <- the only claimable part

    priced per row, over the 551 rows that carry both cohorts:
      best sportsbook price, no exchanges at all   +4.49%
      the price it ACTUALLY took                   +6.69%
      best execution venue, or the fill            +7.43%   -> +0.74 points
      best price ANY book showed                   +8.45%   (unreachable books included)
      the FAIR price, zero hold                    +8.98%   <- ceiling

**+0.74 ROI points is the answer**, stable at +0.72..+0.77 across quote windows
of 15 to 120 minutes and both definitions of "exchange". The retracted +1.2%
was not merely mis-sloped: spending the superset's +1.57pp at the right slope
would have given roughly +3.8 points, five times the truth.

THE TELL, worth internalising: **+1.57pp of "improvement" is larger than the
0.88pp of entry cost this book pays in total.** A gain bigger than the whole
cost it is supposed to be removing cannot be about that book. That single
comparison is enough to reject the conversion without any of the machinery
below, and it was available in the published numbers.

WHY THIS EXISTS. `findings_2026-08-31_mlb_accuracy_assessment.md` section 7h
measured a real thing -- adding exchanges to the shopping set improves the best
available entry by **+1.57pp** across 13,093 game-market snapshot comparisons --
and then converted it to ROI with a constant that was wrong twice over:

  * **WRONG SLOPE.** It used "each 1pp of better entry is worth roughly +0.75pp
    of ROI" and attributed it to item 07's sensitivity table. That table is
    printed in the same document and gives ~1.77 (2.74 ROI points across
    4.05 -> 2.50pp per side). A 2.4x understatement.
  * **WRONG BOOK, which the corrected slope does not fix.** Item 07's table
    prices a PROP book ("unders, minus home runs and HRR", n=2,569). A prop
    book's ROI curve cannot convert a GAME-market entry improvement.

The correction block in that file says: publish no substitute number until a
game-market sensitivity exists. This builds it -- and then finds that the
population error was the larger of the two.

WHY A SLOPE IS NOT A PROPERTY OF THE MARKET TYPE. With flat 1u, a per-side
entry cost `c` and a no-vig probability `p`, `ROI(c) = mean(w / (p + c)) - 1`, so

    dROI/dc = -mean(w / (p + c)^2)   ~=   -(1 + ROI) / q

for `q = p + c`, the implied probability actually paid. **The slope is set by
the book's own realized return and its price level, not by whether the rows are
props or game lines.** Substituting one book's curve for another's is unsafe
because W and q differ, not because props and games are different worlds. Here
the two curves land at +1.91 (games) and +1.77 (props) across the same span --
close enough that the slope error alone was the *smaller* of section 7h's two
defects, and far enough that neither licenses the other.

--------------------------------------------------------------------------
FOUR THINGS THIS GETS RIGHT THAT AN OBVIOUS VERSION GETS WRONG
--------------------------------------------------------------------------

1. THE PRICE IS OLDER THAN THE ORDER, and anchoring on `submitted_at` corrupts
   everything downstream. Measured here: on 139 of 584 rows the book's quote at
   `submitted_at` differed from `fill_price` by more than 1pp, mean **-2.46pp**,
   worst -77pp -- because the board carries a price with a real age (section 5
   of the assessment: `book_age_seconds` median 202s, p90 1,308s). Taken at face
   value that made the book's mean entry cost come out NEGATIVE, i.e. paying
   less than fair, which is not a thing. The anchor here is instead **the last
   snapshot at or before submission at which that book actually showed
   `fill_price`** -- self-verifying, because the price has to match exactly.
   Median age of that quote at submission: 16.5 minutes.

2. THE BOOK THE DECISION IS ABOUT. The entry improvement is measured on the
   staked book's OWN population -- the keys it took, at the moments it took them
   -- not on the 13,093-row superset. On the prop side, restricting to the gate
   book moved the gain from +1.121pp to +0.955pp and the sign was not knowable
   in advance. Here it moves the CONCLUSION, not just the number.

3. THE COUNTERFACTUAL IS PRICED PER ROW, NOT THROUGH THE TABLE. The table is
   the reusable artifact and the thing item 05 asked for, but the answer does
   not need it: every row carries the best sportsbook price and the best
   any-venue price at its own anchor instant, so "what would this book have
   returned without exchanges" is a direct re-pricing. The table and the direct
   re-pricing are printed together and must agree.

4. THE PAYOUT MODEL IS THE LEDGER'S. Verified before use, not assumed: on 929
   settled MLB game-market orders `stake * (1/implied(fill_price) - 1)`
   reproduces the ledger's own `pnl_dollars` to within 0.02 of a stake on every
   row and to 1e-6 on 833. The re-pricing is the ledger's arithmetic with one
   input changed.

WHAT IT HOLDS FIXED, AND THEREFORE DOES NOT PROVE: the picks and the outcomes.
It prices the ENTRY only.

Usage:
    py -3 scripts/measure_game_market_option_value.py --start 2026-08-22 --end 2026-08-31
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BASE = "https://syndicate-an21.onrender.com"

# The venue set item 05 called "exchanges" (`measure_exchange_prop_option_value.py`).
# Kept IDENTICAL so this is comparable to the +1.57pp it corrects. `betfair_ex_*`
# and `matchbook` are exchanges too and are NOT in it; `--exchange-set wide` adds
# them, so the choice is reported rather than assumed.
EXCHANGES_NARROW = frozenset({"kalshi", "polymarket", "novig", "prophetx"})
EXCHANGES_WIDE = EXCHANGES_NARROW | {"betfair_ex_eu", "betfair_ex_uk",
                                     "matchbook", "smarkets", "betfair_ex_au"}

# Game-market families. `h2h_3_way` is excluded: a three-way market does not
# de-vig against ONE opposite side, and it is 23 of 999 staked rows.
GAME_MARKETS = frozenset({"h2h", "totals", "spreads", "totals_alt", "spreads_alt"})

# Section 1 of the 08-31 assessment: settled/dead prices contaminate 6.7% of
# priced games (`-100000` / `+99900`, overround 1.0000) and a naive backtest over
# them returned +101% to +331% ROI. Both filters below are its filters.
MAX_ABS_AMERICAN = 1000.0
OVERROUND_MIN = 1.001
OVERROUND_MAX = 1.30

# Per-side entry costs to price, in implied-probability points. The last five
# match item 07's prop grid exactly so the two curves can be read side by side;
# the run inserts the book's own measured cost as a labelled row.
SIDE_COST_GRID = (0.00, 0.25, 0.50, 0.75, 1.00, 1.50, 2.50, 3.75, 4.05)

# ------------------------------------------------------------------ published

# Item 07's PROP sensitivity, verbatim from the 08-31 assessment (per-side pp ->
# book ROI %). Present ONLY so a test can pin its slope at ~1.77 and prove the
# published 0.75 wrong. NOTHING here prices a game market off it.
PROP_SENSITIVITY = ((0.00, 8.48), (0.50, 7.49), (1.00, 6.52), (1.50, 5.57),
                    (2.50, 3.72), (3.75, 1.50), (4.05, 0.98))
PROP_SENSITIVITY_BOOK = "MLB player props, unders minus home runs and HRR, n=2,569"

# The GAME-market sensitivity, measured by this script on the run recorded in the
# docstring. `--emit-table` reprints it in this form after any re-run. Downstream
# code interpolates THIS -- never a constant, and never the prop table.
GAME_SENSITIVITY = ((0.00, 8.21), (0.25, 7.57), (0.50, 6.95), (0.75, 6.34),
                    (0.88, 6.03), (1.00, 5.76), (1.50, 4.62), (2.50, 2.50),
                    (3.75, 0.09), (4.05, -0.46))
GAME_SENSITIVITY_BOOK = ("MLB game markets (h2h/spreads/totals, full + segments), "
                         "621 settled paper orders, 2026-08-22..08-31")
GAME_MEASURED_SIDE_COST_PP = 0.88   # what the book actually paid; 1.77% two-way


def roi_from_table(side_cost_pp: float, table=GAME_SENSITIVITY) -> float:
    """Book ROI at a per-side entry cost, linearly interpolated on a published
    table. Clamped at both ends: this prices a venue change, and extrapolating
    past a measured endpoint would invent a number."""
    if not table:
        raise ValueError("no published table -- run the measurement first")
    if side_cost_pp <= table[0][0]:
        return table[0][1]
    if side_cost_pp >= table[-1][0]:
        return table[-1][1]
    for (x0, y0), (x1, y1) in zip(table, table[1:]):
        if x0 <= side_cost_pp <= x1:
            return y0 + (y1 - y0) * (side_cost_pp - x0) / (x1 - x0)
    raise AssertionError("unreachable: table is sorted and bracketed")


def table_slope(table, lo: float, hi: float) -> float:
    """ROI points gained per 1pp of CHEAPER entry across [lo, hi] of per-side
    cost. Positive means a better entry pays."""
    if hi <= lo:
        raise ValueError("hi must exceed lo")
    return (roi_from_table(lo, table) - roi_from_table(hi, table)) / (hi - lo)


# ------------------------------------------------------------------ primitives

def implied(price) -> float | None:
    """American price -> implied probability. A value strictly inside
    (-100, 100) is not an American price and is refused, never coerced; so is
    anything past the dead-price bound."""
    try:
        value = float(price)
    except (TypeError, ValueError):
        return None
    if -100.0 < value < 100.0:
        return None
    if abs(value) > MAX_ABS_AMERICAN:
        return None
    return (-value) / ((-value) + 100.0) if value < 0 else 100.0 / (value + 100.0)


def parse_ts(value) -> float | None:
    text = str(value or "").strip().replace("Z", "+00:00")
    if not text:
        return None
    try:
        return datetime.fromisoformat(text).timestamp()
    except ValueError:
        return None


def opposite(market: str, selection: str, line):
    """The other side of the same two-way market, spelled as `book_quotes`
    spells it. Spreads MIRROR the line (`away -1.5` pairs with `home +1.5`);
    totals and moneylines share it."""
    if market == "h2h":
        return {"home": "away", "away": "home"}.get(selection), line
    if market in ("totals", "totals_alt"):
        return {"over": "under", "under": "over"}.get(selection), line
    if market in ("spreads", "spreads_alt"):
        flipped = -line if isinstance(line, (int, float)) else None
        return {"home": "away", "away": "home"}.get(selection), flipped
    return None, None


def dates_between(start: str, end: str) -> list[str]:
    day, last, out = date.fromisoformat(start), date.fromisoformat(end), []
    while day <= last:
        out.append(day.isoformat())
        day += timedelta(days=1)
    return out


def admin_token(explicit: str) -> str:
    """Resolved LAZILY, at the first shard that is not already cached. A run off
    a warm cache needs no credential, and demanding one up front would make a
    read-only re-run fail in a worktree that has no `.env`."""
    if explicit:
        return explicit
    for env in (REPO_ROOT / ".env", Path.cwd() / ".env"):
        for line in (env.read_text(encoding="utf-8").splitlines() if env.exists() else []):
            if line.startswith("ADMIN_TOKEN="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("no ADMIN_TOKEN, and a shard is missing from the cache")


# ------------------------------------------------------------------ fetching

def fetch_orders(day: str, cache_dir: Path) -> list[dict]:
    """Filled paper orders for one date, from the served portfolio payload.

    `orphan_orders` is the ORDER-level view -- one row per venue book that
    actually took a price, which is the unit an entry improvement applies to.
    `settlement.by_market_family` is the POSITION-level view and is smaller;
    section 6 of the 08-31 assessment is that view, so the two counts differ by
    construction and neither is wrong."""
    dest = cache_dir / f"paper_{day}.json"
    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(f"{BASE}/api/portfolio/paper?date={day}", timeout=600) as response:
            dest.write_bytes(response.read())
    payload = json.loads(dest.read_text(encoding="utf-8"))
    rows = list(payload.get("orphan_orders") or [])
    for book in (payload.get("paper2") or []):
        positions = book.get("positions")
        if isinstance(positions, list):
            rows.extend(positions)
    for row in rows:
        row["_date"] = day
    return rows


# `book_quotes` shards silently LOSE ROWS (`#630`, lane `book-quotes-publish-clobber`,
# guard `51cf8b83`, fix `e78aee52`). Two services each append to their own local
# copy of the same daily file and then publish the WHOLE FILE, so web keeps
# whichever published last and the other writer's tail vanishes. Measured on
# 2026-09-01: a refetch an hour later LOST 1,318 exchange rows and gained none.
#
# THAT LANE'S GUARD CANNOT BE COPIED HERE, and the reason is worth stating because
# a verbatim copy looks like it works. It compares the EXCHANGE cohort's span
# against the SPORTSBOOK cohort's. The clobber is per-FILE, so it truncates every
# cohort one writer holds, TOGETHER. Measured on that lane's own worst date, the
# 2026-09-01 shard: of 58,820 GAME rows, `venue_direct` is ZERO -- every game row
# comes from the single OddsAPI writer, and its exchange and sportsbook cohorts
# span identically (06:07:26..23:43:15). Their metric therefore reads ~100% on a
# game-market measurement while the file is short: blind to exactly the failure it
# exists to catch, and silent about it.
#
# The discriminator has to be the WRITER, not the book. `source == "venue_direct"`
# marks the venue-direct capture; everything else is the OddsAPI path. Both write
# the same file, so if one's rows stop long before the other's, that file lost a
# tail. The check runs over the WHOLE shard -- prop rows included -- because the
# clobber is a property of the file, and on game markets the second writer leaves
# no rows to see.
WRITER_OVERLAP_FLOOR = 0.65
VENUE_DIRECT = "venue_direct"


def writer_report(rows) -> dict:
    """Do the two publishers of this shard cover the same span?

    `rows` is any iterable of raw shard rows (game AND prop). Returns the spans
    and the fraction of each writer's rows falling at or before the other's last
    row. One writer present is not a failure -- the race needs two, and before
    2026-09-01 16:11Z the venue-direct capture did not exist -- but it is
    reported as `single_writer` rather than silently passing as healthy."""
    direct, other = [], []
    for row in rows:
        stamp = parse_ts(row.get("captured_at") or row.get("snapshot_ts"))
        if stamp is None:
            continue
        (direct if row.get("source") == VENUE_DIRECT else other).append(stamp)
    if not direct or not other:
        return {"ok": True, "single_writer": True, "known": True,
                "direct_n": len(direct), "other_n": len(other),
                "reason": "one writer wrote this shard; the publish race needs two"}
    last_direct, last_other = max(direct), max(other)
    covered_direct = sum(1 for s in direct if s <= last_other) / len(direct)
    covered_other = sum(1 for s in other if s <= last_direct) / len(other)
    matchable = min(covered_direct, covered_other)
    return {
        "ok": matchable >= WRITER_OVERLAP_FLOOR, "single_writer": False, "known": True,
        "direct_n": len(direct), "other_n": len(other),
        "direct_span": (_hhmmss(min(direct)), _hhmmss(last_direct)),
        "other_span": (_hhmmss(min(other)), _hhmmss(last_other)),
        "matchable": matchable,
        "reason": "" if matchable >= WRITER_OVERLAP_FLOOR else
                  "one publisher's rows stop long before the other's -- this shard "
                  "was very likely clobbered by a competing whole-file publish",
    }


def _hhmmss(stamp: float) -> str:
    return datetime.utcfromtimestamp(stamp).strftime("%H:%M:%S")


def writer_report_path(day: str, cache_dir: Path) -> Path:
    return cache_dir / f"shard_writers_{day}.json"


def load_writer_report(day: str, cache_dir: Path) -> dict:
    """The report written when the shard was compacted.

    A cache built before this check existed has no sidecar, and that is UNKNOWN,
    not clear: the compacted file keeps only game rows, so the second writer's
    evidence is already gone and cannot be recovered from it. Unknown must not
    land on the permissive branch -- refetch, or say `--allow-clobbered` out
    loud."""
    path = writer_report_path(day, cache_dir)
    if not path.exists():
        return {"ok": False, "known": False, "single_writer": False,
                "reason": "no writer report -- the cache predates this check and the "
                          "compacted file cannot answer it; delete it and refetch"}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"ok": False, "known": False, "single_writer": False,
                "reason": "writer report unreadable"}


def fetch_quotes(day: str, token_arg: str, cache_dir: Path) -> Path:
    """One date's GAME quote rows, compacted out of the production shard.

    Also writes `shard_writers_<day>.json` from the WHOLE shard, before the game
    filter drops the evidence -- see the clobber note above."""
    dest = cache_dir / f"game_quotes_{day}.jsonl"
    if dest.exists() and writer_report_path(day, cache_dir).exists():
        return dest
    token = admin_token(token_arg)
    dest.parent.mkdir(parents=True, exist_ok=True)
    url = f"{BASE}/api/ops/artifacts/export?" + urllib.parse.urlencode(
        {"pattern": f"*mlb_source/tracking/book_quotes/{day}.jsonl"})
    request = urllib.request.Request(url, headers={"X-Admin-Token": token})
    with urllib.request.urlopen(request, timeout=1800) as response:
        payload = json.loads(response.read().decode("utf-8"))
    artifacts = payload.get("artifacts") or {}
    if not artifacts:
        raise SystemExit(f"no book_quotes shard for {day} on production")
    doc = next(iter(artifacts.values()))
    lines = doc.splitlines() if isinstance(doc, str) else [json.dumps(r) for r in doc]
    keep = ("snapshot_ts", "captured_at", "event_id", "bookmaker", "market",
            "segment", "selection", "line", "price", "source")
    every = []
    with dest.open("w", encoding="utf-8") as handle:
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            every.append(row)
            if row.get("kind") != "game":
                continue
            handle.write(json.dumps({k: row.get(k) for k in keep}) + "\n")
    report = writer_report(every)
    report["day"] = day
    report["shard_rows"] = len(every)
    writer_report_path(day, cache_dir).write_text(
        json.dumps(report, indent=2), encoding="utf-8")
    return dest


def load_quote_index(path: Path):
    """Two indexes over one date's game quotes.

    `by_side`  (event, market, segment, book, selection, line) -> [(ts, price)]
    `by_key`   (event, market, segment, selection, line) -> {book: [(ts, price)]}
    """
    by_side: dict[tuple, list] = defaultdict(list)
    by_key: dict[tuple, dict] = defaultdict(dict)
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except Exception:
            continue
        stamp = parse_ts(row.get("snapshot_ts") or row.get("captured_at"))
        if stamp is None:
            continue
        book = str(row.get("bookmaker") or "").lower()
        selection_key = (row.get("event_id"), row.get("market"), row.get("segment"),
                         row.get("selection"), row.get("line"))
        by_side[selection_key[:3] + (book,) + selection_key[3:]].append((stamp, row.get("price")))
        by_key[selection_key].setdefault(book, []).append((stamp, row.get("price")))
    for series in by_side.values():
        series.sort(key=lambda item: item[0])
    for books in by_key.values():
        for series in books.values():
            series.sort(key=lambda item: item[0])
    return by_side, by_key


def latest_at(series, at: float, window: float):
    """The last entry at or before `at`, if it is within `window` seconds."""
    if not series:
        return None
    best = None
    for item in series:
        if item[0] > at:
            break
        best = item
    if best is None or at - best[0] > window:
        return None
    return best


def best_available(books: dict, at: float, window: float, exchanges: frozenset):
    """The cheapest entry each cohort was SHOWING at `at`.

    Each book contributes its own latest quote at or before `at`; the minimum is
    then taken across books. Scanning a whole window for its lowest tick instead
    would credit a price that was gone by the time the decision was made -- the
    same defect that inverted item 05's first measurement.

    The EXCHANGE cohort is reported separately from "any book", because they
    answer different questions. Item 05 proposes making the board read the VENUE
    feeds; it cannot make the board bet at `onexbet`. A residual held by a book
    the platform has no execution path to is not a prize this item can claim."""
    best = {"sportsbook": None, "exchange": None, "any": None}
    holder = {"sportsbook": None, "exchange": None, "any": None}

    def offer(cohort: str, value: float, book: str) -> None:
        if best[cohort] is None or value < best[cohort]:
            best[cohort], holder[cohort] = value, book

    for book, series in books.items():
        entry = latest_at(series, at, window)
        if entry is None:
            continue
        value = implied(entry[1])
        if value is None:
            continue
        offer("any", value, book)
        offer("exchange" if book in exchanges else "sportsbook", value, book)
    return best, holder


# ------------------------------------------------------------------ the book

def price_book(orders: list[dict], indexes: dict, window: float,
               exchanges: frozenset) -> tuple[list[dict], Counter, list[float]]:
    """One priced row per staked order: what it paid, what was fair, what it won,
    and what else was on offer at the instant its price was live.

    The anchor is the last snapshot at or before submission at which the order's
    own book showed EXACTLY `fill_price`. That is what makes the row's no-vig
    probability a property of the price paid rather than of a later quote --
    see defect 1 in the module docstring."""
    priced, refused, ages = [], Counter(), []
    for order in orders:
        pair = indexes.get(order.get("_date"))
        if pair is None:
            refused["no_quote_shard"] += 1
            continue
        by_side, by_key = pair
        market = str(order.get("market") or "")
        segment = str(order.get("segment") or "full")
        side = str(order.get("side") or "")
        line = order.get("line")
        book = str(order.get("book") or "").lower()
        event = order.get("event_id")
        outcome = str(order.get("outcome") or "")
        if outcome not in ("won", "lost", "push"):
            refused["not_settled"] += 1
            continue
        submitted = parse_ts(order.get("submitted_at"))
        fill_price = order.get("fill_price")
        q_fill = implied(fill_price)
        if submitted is None or q_fill is None:
            refused["fill_price_or_timestamp_unusable"] += 1
            continue
        own_series = by_side.get((event, market, segment, book, side, line))
        if not own_series:
            refused["own_side_never_quoted"] += 1
            continue
        shown = [ts for ts, price in own_series
                 if ts <= submitted and price is not None and float(price) == float(fill_price)]
        if not shown:
            refused["fill_price_never_quoted_before_submit"] += 1
            continue
        anchor = shown[-1]
        ages.append((submitted - anchor) / 60.0)

        other_side, other_line = opposite(market, side, line)
        if other_side is None:
            refused["market_not_two_way"] += 1
            continue
        opposing = latest_at(by_side.get((event, market, segment, book, other_side, other_line)),
                             anchor, window)
        if opposing is None:
            refused["no_opposite_side_at_the_anchor"] += 1
            continue
        q_opposite = implied(opposing[1])
        if q_opposite is None:
            refused["opposite_price_unusable"] += 1
            continue
        overround = q_fill + q_opposite
        if not (OVERROUND_MIN < overround < OVERROUND_MAX):
            refused["overround_out_of_band"] += 1
            continue

        best, holder = best_available(
            by_key.get((event, market, segment, side, line)) or {}, anchor, window, exchanges)

        fair = q_fill / overround
        priced.append({
            "date": order.get("_date"), "market": market, "segment": segment,
            "side": side, "line": line, "book": book,
            "venue": str(order.get("venue") or ""), "outcome": outcome,
            "win": 1.0 if outcome == "won" else 0.0, "push": outcome == "push",
            "stake": float(order.get("fill_stake_dollars") or 0.0),
            "pnl": float(order.get("pnl_dollars") or 0.0),
            "q_fill": q_fill, "p": fair, "side_cost_pp": (q_fill - fair) * 100.0,
            "hold_pct": (overround - 1.0) * 100.0, "quote_age_min": (submitted - anchor) / 60.0,
            "best_sportsbook": best["sportsbook"], "best_exchange": best["exchange"],
            "best_any": best["any"], "holder_sportsbook": holder["sportsbook"],
            "holder_any": holder["any"],
        })
    return priced, refused, ages


# ------------------------------------------------------------------ pricing

def roi_at_entry(rows: list[dict], entry) -> float:
    """Flat-1u book ROI when each row enters at `entry(row)`.

    Pushes return the stake at any price, so they contribute exactly zero and
    are neither dropped from the denominator nor scored as losses."""
    if not rows:
        raise ValueError("no rows")
    total = 0.0
    for row in rows:
        if row["push"]:
            continue
        total += row["win"] / max(entry(row), 1e-6) - 1.0
    return 100.0 * total / len(rows)


def roi_at_quoted_price(rows: list[dict]) -> float:
    return roi_at_entry(rows, lambda row: row["q_fill"])


def roi_at_book_cost(rows: list[dict], target_pp: float, today_pp: float) -> float:
    """ROI if the book's MEAN per-side entry cost were `target_pp`, each row's
    own cost scaled in proportion.

    Item 07's prop book could set one uniform cost on every row because its vig
    was uniform (3.07-4.63pp across ten market/line cells). This book's is not:
    exchange-booked rows pay ~0.46pp and sportsbook-booked rows ~2.88pp, a 6x
    spread, so a uniform cost charges most rows several times what they paid and
    the curve stops passing through the price actually paid. Scaling keeps the
    anchor exact -- `roi_at_book_cost(rows, today, today) == roi_at_quoted_price`
    -- and `--uniform-cost` prints item 07's literal method beside it."""
    if today_pp <= 0:
        raise ValueError("today's cost must be positive")
    scale = target_pp / today_pp
    return roi_at_entry(rows, lambda row: row["p"] + scale * (row["q_fill"] - row["p"]))


def roi_at_uniform_cost(rows: list[dict], cost_pp: float) -> float:
    """Item 07's literal method: the SAME per-side cost on every row."""
    return roi_at_entry(rows, lambda row: row["p"] + cost_pp / 100.0)


def stake_weighted_roi(rows: list[dict]) -> float | None:
    staked = sum(row["stake"] for row in rows)
    return 100.0 * sum(row["pnl"] for row in rows) / staked if staked else None


def describe(values: list[float]) -> str:
    data = sorted(values)
    n = len(data)
    return (f"n={n:<6} mean {statistics.fmean(data):+7.3f}  median {data[n // 2]:+7.3f}"
            f"  p25 {data[n // 4]:+7.3f}  p75 {data[(3 * n) // 4]:+7.3f}")


# ------------------------------------------------------------------ superset

def superset_option_value(shard_paths: dict, exchanges: frozenset) -> dict:
    """Section 7h's population, reproduced per date.

    A "snapshot" is `captured_at`, the REFRESH CYCLE stamp -- identical across
    every book written by one pass. `snapshot_ts` is each book's own last-update
    time and differs book to book by a second or two, so grouping on it would
    find almost no cross-book cells at all. Getting this wrong does not error:
    it silently produces a tiny population that still looks like a measurement.

    Verified against section 7h's published figures on 2026-08-31: this returns
    n=13,344 / 52.4% / median +0.232pp against a published 13,093 / 52.5% /
    +0.240pp -- the same measurement on the same day."""
    per_date: dict[str, dict] = {}
    for day, path in sorted(shard_paths.items()):
        cells: dict[tuple, dict] = defaultdict(dict)
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            cells[(row.get("captured_at"), row.get("event_id"), row.get("market"),
                   row.get("segment"), row.get("selection"),
                   row.get("line"))][str(row.get("bookmaker") or "").lower()] = row.get("price")
        gains, wins = [], 0
        for books in cells.values():
            if not any(book in exchanges for book in books):
                continue
            best_sb = best_any = None
            for book, price in books.items():
                value = implied(price)
                if value is None:
                    continue
                if best_any is None or value < best_any:
                    best_any = value
                if book not in exchanges and (best_sb is None or value < best_sb):
                    best_sb = value
            if best_sb is None or best_any is None:
                continue
            gain = (best_sb - best_any) * 100.0
            gains.append(gain)
            if gain > 1e-9:
                wins += 1
        if gains:
            per_date[day] = {"n": len(gains), "wins": wins, "gains": gains}
    return per_date


# ------------------------------------------------------------------ main

def build_table(rows: list[dict], today_pp: float, uniform: bool = False):
    grid = sorted(set(SIDE_COST_GRID) | {round(today_pp, 2)})
    price = roi_at_uniform_cost if uniform else (
        lambda data, cost: roi_at_book_cost(data, cost, today_pp))
    return tuple((cost, price(rows, cost)) for cost in grid)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--start", default="2026-08-22")
    parser.add_argument("--end", default="2026-08-31")
    parser.add_argument("--window-minutes", type=int, default=30,
                        help="how stale the OPPOSING side and the rival books may "
                             "be at the anchor instant (the anchor itself is exact)")
    parser.add_argument("--admin-token", default="")
    parser.add_argument("--exchange-set", choices=("narrow", "wide"), default="narrow")
    parser.add_argument("--venue", default="", help="e.g. 'paper' or 'paper:kalshi'")
    parser.add_argument("--uniform-cost", action="store_true",
                        help="also print item 07's literal uniform-cost table")
    parser.add_argument("--superset", action="store_true",
                        help="reproduce section 7h's 13,093-row measurement (slow)")
    parser.add_argument("--cache-dir",
                        default=str(REPO_ROOT / "reports" / "game_market_option_value"))
    parser.add_argument("--emit-table", action="store_true")
    parser.add_argument("--allow-clobbered", action="store_true",
                        help="score a date whose shard lost rows to the publish "
                             "race anyway. Reproduces a pre-guard number exactly; "
                             "say so wherever you quote the result.")
    args = parser.parse_args()

    exchanges = EXCHANGES_WIDE if args.exchange_set == "wide" else EXCHANGES_NARROW
    cache = Path(args.cache_dir)
    window = args.window_minutes * 60.0

    orders: list[dict] = []
    indexes: dict = {}
    shard_health: dict = {}
    for day in dates_between(args.start, args.end):
        orders.extend(fetch_orders(day, cache))
        indexes[day] = load_quote_index(fetch_quotes(day, args.admin_token, cache))
        shard_health[day] = load_writer_report(day, cache)

    # A clobbered shard hands back a clean-looking curve, so this refuses BEFORE
    # anything is priced rather than footnoting it afterwards.
    print(f"\nSHARD INTEGRITY  (`#630` publish race -- WRITER spans, not book cohorts)")
    bad = []
    for day, report in shard_health.items():
        if report.get("single_writer"):
            note = f"single writer ({report.get('other_n', 0)} rows) -- race needs two"
        elif not report.get("known"):
            note = report.get("reason", "unknown")
        else:
            note = (f"venue_direct {report['direct_n']} {report['direct_span'][0]}"
                    f"..{report['direct_span'][1]}  |  other {report['other_n']} "
                    f"{report['other_span'][0]}..{report['other_span'][1]}  "
                    f"matchable {100 * report['matchable']:.1f}%")
        print(f"  {day}  {'ok ' if report.get('ok') else 'BAD'}  {note}")
        if not report.get("ok"):
            bad.append(day)
    if bad and not args.allow_clobbered:
        print(f"\nREFUSING {len(bad)} date(s): {', '.join(bad)}")
        print("  A shard that lost a publish race produces a confident curve off a")
        print("  truncated file. Re-fetch (delete the cache entry), or pass")
        print("  --allow-clobbered and say so wherever you quote the number.")
        return 2
    if bad:
        print(f"\n  --allow-clobbered: scoring {len(bad)} date(s) that FAILED the check.")

    staked = [o for o in orders
              if str(o.get("sport")) == "mlb"
              and str(o.get("market")) in GAME_MARKETS
              and str(o.get("status") or "filled") == "filled"]
    if args.venue:
        staked = [o for o in staked if str(o.get("venue")) == args.venue]

    print(f"\nMLB GAME-MARKET STAKED BOOK, {args.start}..{args.end}"
          + (f", venue={args.venue}" if args.venue else "")
          + f", exchanges={args.exchange_set}, window={args.window_minutes}m")
    print(f"  filled orders in game families: {len(staked)}")
    rows, refused, ages = price_book(staked, indexes, window, exchanges)
    print(f"  priced: {len(rows)}")
    for reason, count in refused.most_common():
        print(f"    refused {reason}: {count}")
    if not rows:
        print("\nnothing priced -- no table")
        return 1
    ages.sort()
    print(f"  age of the anchoring quote at submission, minutes: "
          f"median {ages[len(ages) // 2]:.1f}  p90 {ages[int(0.9 * len(ages))]:.1f}")
    print(f"\n  by market:  {dict(Counter(r['market'] for r in rows))}")
    print(f"  by book:    {dict(Counter(r['book'] for r in rows).most_common(8))}")
    print(f"  by venue:   {dict(Counter(r['venue'] for r in rows))}")
    print(f"  outcomes:   {dict(Counter(r['outcome'] for r in rows))}")
    print(f"  dates:      {len(set(r['date'] for r in rows))}")

    costs = [r["side_cost_pp"] for r in rows]
    today = statistics.fmean(costs)
    print(f"\nENTRY COST ACTUALLY PAID  (quoted implied - same-book no-vig, at the anchor)")
    print(f"  per side, pp:     {describe(costs)}")
    print(f"  two-way hold, %:  {describe([r['hold_pct'] for r in rows])}")
    exchange_booked = [r for r in rows if r["book"] in exchanges]
    other_booked = [r for r in rows if r["book"] not in exchanges]
    for label, subset in (("exchange-booked", exchange_booked), ("sportsbook-booked", other_booked)):
        if subset:
            print(f"    {label:<18} n={len(subset):<5} "
                  f"mean {statistics.fmean([r['side_cost_pp'] for r in subset]):+.3f}pp")

    print(f"\nCOVERAGE BIAS -- what the refusals cost, measured rather than assumed")
    priced_keys = Counter((r["date"], r["book"], r["market"], r["side"], str(r["line"]),
                           round(r["q_fill"], 6), r["stake"]) for r in rows)
    dropped = []
    for order in staked:
        if str(order.get("outcome")) not in ("won", "lost", "push"):
            continue
        value = implied(order.get("fill_price"))
        key = (order.get("_date"), str(order.get("book") or "").lower(), str(order.get("market")),
               str(order.get("side")), str(order.get("line")),
               round(value, 6) if value is not None else None,
               float(order.get("fill_stake_dollars") or 0.0))
        if priced_keys.get(key):
            priced_keys[key] -= 1
        else:
            dropped.append(order)
    if dropped:
        staked_dollars = sum(float(o.get("fill_stake_dollars") or 0.0) for o in dropped)
        pnl = sum(float(o.get("pnl_dollars") or 0.0) for o in dropped)
        print(f"  priced   n={len(rows):<5} ledger ROI {stake_weighted_roi(rows):+.2f}%")
        print(f"  refused  n={len(dropped):<5} ledger ROI "
              f"{100.0 * pnl / staked_dollars if staked_dollars else float('nan'):+.2f}%"
              f"   books: {dict(Counter(str(o.get('book')) for o in dropped).most_common(4))}")
        print(f"  The refused rows are NOT a random sample: they are dominated by venue")
        print(f"  prices `book_quotes` never captured, and they returned better. The LEVEL")
        print(f"  of the curve below is therefore conservative; its SLOPE, which goes as")
        print(f"  (1 + ROI) / q, is understated by roughly the same proportion.")

    ledger = stake_weighted_roi(rows)
    print(f"\nANCHORS, all three stated rather than hidden")
    if ledger is not None:
        print(f"  ledger stake-weighted return on these rows : {ledger:+.2f}%")
    print(f"  flat-1u reconstruction at the quoted price : {roi_at_quoted_price(rows):+.2f}%")
    print(f"  the curve at the measured cost ({today:.2f}pp)     : "
          f"{roi_at_book_cost(rows, today, today):+.2f}%   (identical by construction)")

    table = build_table(rows, today)
    print(f"\nGAME-MARKET SENSITIVITY  (n={len(rows)}, flat 1u, every row re-priced exactly)")
    print(f"  NOTE the first column is 2 x the per-side cost. It equals the measured")
    print(f"  two-way hold ({statistics.fmean([r['hold_pct'] for r in rows]):.2f}% here) only at even money: proportional de-vig")
    print(f"  charges each side in proportion to its price, and this book's mean implied")
    print(f"  price paid is {statistics.fmean([r['q_fill'] for r in rows]):.3f}, so 2 x cost runs "
          f"{200 * statistics.fmean([r['q_fill'] for r in rows]):.0f}% of the hold.")
    print(f"  {'2 x per side':>14}{'per side':>11}{'book ROI':>11}")
    for cost, roi in table:
        marker = "  <- what it actually paid" if abs(cost - round(today, 2)) < 1e-9 else ""
        print(f"  {2 * cost:>13.2f}%{cost:>10.2f}pp{roi:>10.2f}%{marker}")
    if args.uniform_cost:
        print(f"\n  item 07's literal uniform-cost method, for comparison:")
        for cost, roi in build_table(rows, today, uniform=True):
            print(f"  {2 * cost:>13.2f}%{cost:>10.2f}pp{roi:>10.2f}%")

    print(f"\nSLOPE, ROI points per 1pp of CHEAPER entry")
    print(f"  games, across 2.50 -> 4.05pp per side : {table_slope(table, 2.50, 4.05):+.2f}")
    print(f"  games, across 0.00 -> 1.00pp per side : {table_slope(table, 0.00, 1.00):+.2f}"
          f"   <- the range this book operates in")
    print(f"  item 07's PROP table, 2.50 -> 4.05pp  : {table_slope(PROP_SENSITIVITY, 2.50, 4.05):+.2f}")
    print(f"  the constant the 08-31 write-up used  : +0.75   (WRONG, retracted)")

    # ---------------------------------------------------------------- shopping
    shoppable = [r for r in rows if r["best_sportsbook"] is not None and r["best_any"] is not None]
    print(f"\nENTRY IMPROVEMENT ON THIS BOOK'S OWN POPULATION"
          f"   ({len(shoppable)} of {len(rows)} rows carry both a sportsbook and a best-any quote)")
    if shoppable:
        available = [(r["best_sportsbook"] - r["best_any"]) * 100.0 for r in shoppable]
        banked = [(r["best_sportsbook"] - r["q_fill"]) * 100.0 for r in shoppable]
        residual = [(r["q_fill"] - r["best_any"]) * 100.0 for r in shoppable]
        print(f"  exchanges make available   {describe(available)}")
        print(f"    an exchange beats every sportsbook on "
              f"{100.0 * sum(1 for g in available if g > 1e-9) / len(available):.1f}% of rows")
        print(f"  the book ALREADY took      {describe(banked)}")
        print(f"  still on the table         {describe(residual)}")
        unclaimed = [r for r in shoppable if r["q_fill"] - r["best_any"] > 1e-9]
        if unclaimed:
            held_by_exchange = [r for r in unclaimed if r["holder_any"] in exchanges]
            share = sum((r["q_fill"] - r["best_any"]) for r in held_by_exchange) / \
                sum((r["q_fill"] - r["best_any"]) for r in unclaimed)
            print(f"  the residual sits on {len(unclaimed)} rows; "
                  f"{100.0 * share:.1f}% of it is held by an EXECUTION VENUE, the rest by")
            print(f"    books with no execution path: "
                  f"{dict(Counter(r['holder_any'] for r in unclaimed if r['holder_any'] not in exchanges).most_common(5))}")

        print(f"\nPRICED PER ROW -- the counterfactual, not the table")
        base = roi_at_quoted_price(shoppable)
        rungs = (
            ("best SPORTSBOOK price, no exchanges at all",
             roi_at_entry(shoppable, lambda r: r["best_sportsbook"])),
            ("the price it ACTUALLY took", base),
            ("best price at an EXECUTION VENUE or the fill, whichever is cheaper",
             roi_at_entry(shoppable, lambda r: min(r["q_fill"], r["best_exchange"])
                          if r["best_exchange"] is not None else r["q_fill"])),
            ("best price ANY book showed (includes books we cannot bet at)",
             roi_at_entry(shoppable, lambda r: r["best_any"])),
            ("the FAIR price -- zero hold, the ceiling no venue beats",
             roi_at_entry(shoppable, lambda r: r["p"])),
        )
        for label, value in rungs:
            print(f"  {label:<62}{value:+7.2f}%")
        print(f"  -> exchange access is worth   {rungs[1][1] - rungs[0][1]:+.2f} ROI points"
              f"  -- ALREADY BANKED, not available to spend again")
        print(f"  -> routing to the best VENUE  {rungs[2][1] - rungs[1][1]:+.2f} ROI points"
              f"  -- what item 05's board change could actually claim")
        print(f"  -> perfect shopping anywhere  {rungs[3][1] - rungs[1][1]:+.2f} ROI points"
              f"  -- an upper bound, not a plan")
        print(f"\n  cross-check through the table, which must agree in sign and rough size:")
        for label, delta in (("already banked", statistics.fmean(banked)),
                             ("residual, all books", statistics.fmean(residual))):
            after = roi_at_book_cost(rows, max(0.0, today - delta), today)
            print(f"    {label:<21} {delta:+.3f}pp -> "
                  f"{roi_at_book_cost(rows, today, today):+.2f}% to {after:+.2f}%"
                  f"  ({after - roi_at_book_cost(rows, today, today):+.2f} points)")

    # ---------------------------------------------------------------- superset
    if args.superset:
        shards = {day: fetch_quotes(day, args.admin_token, cache)
                  for day in dates_between(args.start, args.end)}
        per_date = superset_option_value(shards, exchanges)
        print(f"\nSUPERSET -- section 7h's population, reproduced per date")
        print(f"  {'date':<12}{'n':>8}{'improves':>11}{'mean':>9}{'median':>9}")
        pooled: list[float] = []
        for day, result in per_date.items():
            gains = sorted(result["gains"])
            pooled.extend(gains)
            print(f"  {day:<12}{result['n']:>8}{100.0 * result['wins'] / result['n']:>10.1f}%"
                  f"{statistics.fmean(gains):>+9.3f}{gains[len(gains) // 2]:>+9.3f}")
        if pooled:
            pooled.sort()
            print(f"  {'POOLED':<12}{len(pooled):>8}"
                  f"{100.0 * sum(1 for g in pooled if g > 1e-9) / len(pooled):>10.1f}%"
                  f"{statistics.fmean(pooled):>+9.3f}{pooled[len(pooled) // 2]:>+9.3f}")
        print(f"  section 7h published:  n=13,093   52.5%   +1.570   +0.240")
        print(f"  -> the published figure is ONE DATE. Pooled over ten it is lower, and")
        print(f"     the superset is not what a staked book faces in any case: it counts")
        print(f"     every cell of every key, including the ones nothing was ever bet on.")

    if args.emit_table:
        print("\nGAME_SENSITIVITY = ("
              + ", ".join(f"({c:.2f}, {r:.2f})" for c, r in table) + ")")

    print("\nCAVEATS, which the number does not survive without:")
    print("  * settlement is `settled_by = inferred` -- our own grading, no venue")
    print("    confirmation. Section 6 measured real money at -5.5% over adjacent days")
    print("    against paper's +9.4%, so the LEVEL of this curve is optimistic. The")
    print("    SLOPE is far less sensitive than the level; say which one you spent.")
    print("  * 10 dates is not a rate. Re-run over a longer window before sizing.")
    print("  * the staked population is SELECTED -- these keys were taken partly")
    print("    because their price looked good, so the exchange win-rate here runs")
    print("    well above the superset's. That is correct for 'what did this book")
    print("    gain' and wrong for 'what do exchanges offer in general'.")
    print("  * refused rows are orders whose fill price never appears in their own")
    print("    book's captured series before submission; a coverage bound, not a")
    print("    random sample.")
    if any(r.get("single_writer") for r in shard_health.values()):
        print("  * the shard-integrity check above passes on SINGLE-WRITER dates by")
        print("    construction. That is a real exoneration for them -- the race needs")
        print("    two publishers -- but it is not a general clean bill for the file.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
