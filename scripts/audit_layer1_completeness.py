"""Audit Layer 1 board completeness: every sport, every market, five fields.

Answers one question per (sport, market): are IDENTITY, LINE, PROJECTION and
ODDS actually populated, or is the board rendering rows it cannot price?

    python scripts/audit_layer1_completeness.py
    python scripts/audit_layer1_completeness.py --sports wnba --date 2026-08-07
    python scripts/audit_layer1_completeness.py --base-url http://127.0.0.1:5000

WHY IT FETCHES PER MARKET. The unfiltered endpoint returns a global top-N ranked
by book coverage, so it silently drops the thin markets -- which are exactly the
ones an audit is looking for. Measured 2026-08-07: the unfiltered call surfaced
5 of MLB's 11 prop markets. Every count here comes from a per-market fetch.

WHAT COUNTS AS A LEGITIMATE BLANK, because a naive audit reports these as bugs:
  - `line` is NULL BY DESIGN on h2h and h2h_3_way (a moneyline has no line).
    Those markets are exempt rather than counted as gaps.
  - a projection is legitimately absent when the sim has no coverage for that
    player/market -- it is still reported, because "how much of the board carries
    a model view" is the number that decides whether Layer 1 is worth reading.
  - `player_name` is null on game lines and `home/away_team` is null on nothing;
    identity is therefore checked as "has a usable subject", not as one field.

WHY THERE IS AN `edge` COLUMN, AND WHY THIS AUDIT WAS MISLEADING WITHOUT ONE.

A projection is not a model view that Layer 2 can use. `layer2_board` ranks on
`projection.edge_vs_market_pct` (or, since `#601`, `edge_vs_modelled_fair_pct`);
a row carrying `projected` and no edge contributes NOTHING to the board, to the
shortlist, or to a venue order -- `blended_score` falls back to EV alone, and
under proportional devig EV against fair is identical for both sides of a
market, so such rows rank by the book's hold.

Measured 2026-08-30 with the projection column alone, this script reported MLB
at 80.0% and the platform looking broadly healthy. The same slate carried a
model EDGE on **3.5%** of rows, and Layer 2's own ingest counters agreed
(`rows_with_model_edge / sides_priced` = 1,406 / 26,835). The audit was
answering a question next to the one that matters.

So `proj` and `edge` are now reported side by side, plus `mfair` (the modelled
fair fallback) and the leading `edge_unavailable_reason`, because a zero edge
column is only actionable once it says WHICH refusal produced it -- a settled
market, a one-sided quote and a broken join are three different jobs.

`--state` scopes to pregame/live/final. A board of finished games legitimately
carries no edges at all, and reading that as a defect is the single easiest way
to misuse this script.
"""

from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_BASE = "https://syndicate-an21.onrender.com"
SPORTS = ["mlb", "nba", "wnba", "nhl", "nfl", "ncaaf", "ncaab", "soccer"]

# Moneylines carry no line. Counting them as "missing line" would bury the real
# gaps under a column of expected blanks.
LINE_EXEMPT_MARKETS = {"h2h", "h2h_3_way", "moneyline", "outright"}


def _get(url: str, timeout: float = 180.0):
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _has_identity(row) -> bool:
    if str(row.get("player_name") or "").strip():
        return True
    return bool(str(row.get("home_team") or "").strip() and str(row.get("away_team") or "").strip())


def _has_odds(row) -> bool:
    """A price on at least one side. `best` is the board's headline number."""
    best = row.get("best") or {}
    for side in row.get("sides") or []:
        price = (best.get(side) or {}).get("price")
        if price is not None:
            return True
    return False


def _has_two_sided_odds(row) -> bool:
    sides = row.get("sides") or []
    if len(sides) < 2:
        return False
    best = row.get("best") or {}
    return all((best.get(side) or {}).get("price") is not None for side in sides)


def _has_projection(row) -> bool:
    projection = row.get("projection")
    if not isinstance(projection, dict):
        return False
    return any(
        projection.get(key) is not None
        for key in ("projected", "model_prob_over", "edge_vs_market_pct")
    )


def _has_edge(row) -> bool:
    """A model view Layer 2 can actually RANK. See the module docstring."""
    projection = row.get("projection")
    if not isinstance(projection, dict):
        return False
    return projection.get("edge_vs_market_pct") is not None


def _has_modelled_edge(row) -> bool:
    """`#601`'s fallback: a one-sided market priced against the modelled fair.

    Reported SEPARATELY from `edge`, never folded into it -- a modelled fair and
    a measured one are different confidences and `#242` forbids letting the
    first wear the second's clothes.
    """
    projection = row.get("projection")
    if not isinstance(projection, dict):
        return False
    return projection.get("edge_vs_modelled_fair_pct") is not None


def _edge_reason(row) -> str:
    projection = row.get("projection")
    if not isinstance(projection, dict):
        return "no projection at all"
    if projection.get("edge_vs_market_pct") is not None:
        return ""
    reason = projection.get("edge_unavailable_reason")
    if reason is None:
        # ABSENT is not None. A row serving a blank edge with no reason field is
        # indistinguishable from a broken join, and is its own defect class --
        # so it gets its own bucket rather than being lumped in with the honest
        # refusals.
        return "BLANK WITH NO REASON"
    return str(reason)


def audit_sport(base_url: str, sport: str, date: str, state: str = "") -> dict:
    try:
        head = _get(f"{base_url}/api/board/book-grid?sport={sport}&date={date}&limit=1")
    except urllib.error.HTTPError as exc:
        return {"sport": sport, "error": f"HTTP {exc.code}"}
    except Exception as exc:  # network, timeout, decode
        return {"sport": sport, "error": f"{type(exc).__name__}"}

    markets = sorted(head.get("markets") or [])
    kinds = head.get("market_kinds") or {}
    if not markets:
        return {"sport": sport, "markets": [], "total_rows": head.get("total_rows") or 0}

    rows_out = []
    for market in markets:
        url = (
            f"{base_url}/api/board/book-grid?sport={sport}&date={date}"
            f"&market={urllib.parse.quote(market)}&limit=4000"
        )
        try:
            payload = _get(url)
        except Exception as exc:
            rows_out.append({"market": market, "error": f"{type(exc).__name__}"})
            continue
        rows = payload.get("rows") or []
        if state:
            # The grid stamps `game_state` during enrichment. A row with none is
            # DROPPED rather than kept, because an unknown state must not land
            # in whichever bucket the caller asked for -- that is the
            # permissive-default shape this repo has a standing rule about.
            rows = [r for r in rows if _row_state(r) == state]
        total = len(rows)
        if not total:
            rows_out.append({"market": market, "rows": 0})
            continue
        rows_out.append(
            {
                "market": market,
                "kind": kinds.get(market) or "?",
                "rows": total,
                "identity": sum(1 for r in rows if _has_identity(r)),
                "line": sum(1 for r in rows if r.get("line") is not None),
                "line_exempt": market in LINE_EXEMPT_MARKETS,
                "odds": sum(1 for r in rows if _has_odds(r)),
                "two_sided": sum(1 for r in rows if _has_two_sided_odds(r)),
                "projection": sum(1 for r in rows if _has_projection(r)),
                "edge": sum(1 for r in rows if _has_edge(r)),
                "modelled_edge": sum(1 for r in rows if _has_modelled_edge(r)),
                "edge_reasons": _top_reasons(rows),
            }
        )
    return {"sport": sport, "markets": rows_out, "date": date}


def _row_state(row) -> str:
    """Pregame / live / final for one grid row.

    Read off , which is where  puts it.
    The row-level  key exists and is null on every served row --
    reading THAT is how the first version of this filter returned 0 rows for
    every state, which reads exactly like an empty slate.
    """
    game = row.get("game")
    if isinstance(game, dict):
        return str(game.get("state") or "").strip().lower()
    return ""


def _top_reasons(rows, limit: int = 3) -> list:
    counts: dict = {}
    for row in rows:
        reason = _edge_reason(row)
        if not reason:
            continue
        counts[reason] = counts.get(reason, 0) + 1
    return sorted(counts.items(), key=lambda kv: -kv[1])[:limit]


def _pct(n: int, d: int) -> str:
    return f"{100.0 * n / d:5.1f}%" if d else "    -"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default=DEFAULT_BASE)
    parser.add_argument("--date", default="")
    parser.add_argument("--sports", default=",".join(SPORTS))
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--state",
        default="",
        choices=["", "pregame", "live", "final"],
        help="scope to one game state. A board of finished games legitimately "
             "carries no edges; reading that as a defect is the easiest way to "
             "misuse this script.",
    )
    args = parser.parse_args()

    date = args.date.strip()
    if not date:
        from datetime import datetime, timezone

        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    sports = [s.strip().lower() for s in args.sports.split(",") if s.strip()]
    results = [audit_sport(args.base_url, sport, date, args.state) for sport in sports]

    if args.json:
        print(json.dumps(results, indent=1))
        return 0

    scope = f"  state={args.state}" if args.state else ""
    print(f"Layer 1 completeness — {args.base_url}  date={date}{scope}\n")
    for result in results:
        sport = result["sport"]
        if result.get("error"):
            print(f"== {sport.upper()}: ERROR {result['error']}\n")
            continue
        markets = result.get("markets") or []
        if not markets:
            print(f"== {sport.upper()}: no markets on this date\n")
            continue
        total_rows = sum(m.get("rows") or 0 for m in markets)
        print(f"== {sport.upper()}  ({len(markets)} markets, {total_rows} rows)")
        total_edge = sum(m.get("edge") or 0 for m in markets)
        total_proj = sum(m.get("projection") or 0 for m in markets)
        # THE HEADLINE IS THE EDGE RATE, not the projection rate. See the module
        # docstring: 80% projected and 3.5% edged was the reading that hid this.
        print(
            f"   projected {_pct(total_proj, total_rows).strip()}   "
            f"MODEL EDGE {_pct(total_edge, total_rows).strip()}"
        )
        print(f"   {'market':26s} {'kind':5s} {'rows':>5s} {'ident':>7s} {'line':>7s} {'odds':>7s} {'2-side':>7s} {'proj':>7s} {'edge':>7s} {'mfair':>6s}")
        for m in markets:
            if m.get("error"):
                print(f"   {m['market']:26s} ERROR {m['error']}")
                continue
            n = m.get("rows") or 0
            if not n:
                print(f"   {m['market']:26s} {'':5s} {0:5d}   (no rows)")
                continue
            line_cell = "  exempt" if m["line_exempt"] else _pct(m["line"], n)
            print(
                f"   {m['market']:26s} {str(m.get('kind'))[:5]:5s} {n:5d} "
                f"{_pct(m['identity'], n)} {line_cell} {_pct(m['odds'], n)} "
                f"{_pct(m['two_sided'], n)} {_pct(m['projection'], n)} "
                f"{_pct(m.get('edge') or 0, n)} {(m.get('modelled_edge') or 0):6d}"
            )
            # WHY the edge column is what it is. A zero with no reason beside it
            # sends someone to debug a join that may be working correctly.
            if not (m.get("edge") or 0):
                for reason, count in m.get("edge_reasons") or []:
                    print(f"   {'':32s} {count:5d}  {str(reason)[:78]}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
