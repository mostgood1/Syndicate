"""Cross-game parlays (lane `cheat-sheets`; user 2026-10-20: "what about cross slate SGPS?", then "can we do both?").

Two kinds. Both pay +100 or better at ONE book, take one leg per game, and draw legs from any sport on the day's sheets:

  * HIT RATE -- legs from the pool the same-game parlays draw on: the market, the player's last 10 and our sim all make
    each one likely. The likeliest ticket comes first. Legs from different games are taken as independent, so our
    probability is the product of theirs; no correlation lifts it.
    Measured 10-20 (NBA + NHL pools): 4 legs, 43-45% at +101..+103, worth -9% to -14% at the price. That is the books'
    margin, stacked four times.
  * VALUE -- legs that each beat their own price AT THAT BOOK by >= `VALUE_EV_PCT` against the no-vig fair. That is the
    sheet's "value" rule, applied per book because a parlay is placed at one book. Each leg's edge then compounds
    instead of the margin, and the best expected return comes first.

A book pays the full product of the legs on a parlay across games. It discounts a same-game parlay below that product.
So the price shown here is the price paid, and these tickets grade in units.

Pure functions: the builder supplies the legs and writes `cheatsheets/cross/<date>.json`.
"""
from __future__ import annotations

import hashlib
import itertools
from typing import Any, Iterable, Mapping, Sequence

from syndicate.features.shared import cheat_sheets as cs

# Sportsbooks that take a parlay across games. Exchanges and prediction markets (kalshi, polymarket, prophetx, novig)
# do not, so a leg priced only there cannot be in a ticket.
PARLAY_BOOKS = frozenset({
    "fanduel", "draftkings", "betmgm", "williamhill_us", "espnbet", "fanatics", "hardrockbet", "betrivers",
    "ballybet", "betparx", "bovada", "betonlineag", "mybookieag", "pinnacle",
})
MIN_DECIMAL = 2.0                     # +100 or better (user 2026-10-20, the same floor as the same-game parlays)
KINDS = {
    "hit_rate": {"label": "Cross-game parlays: higher hit rate", "sizes": (3, 4), "per_game_legs": 4, "per_sheet": 5,
                 "note": "One leg from each of 3 or 4 games, each one the market, the player's last 10 and our sim all "
                         "make likely; +100 or better at one book. No correlation across games: these carry the books' "
                         "margin on every leg, so read 'worth it at'."},
    # Capped at +300 and ranked by hit rate among the tickets whose legs beat their prices. Ranked by expected return
    # alone, the 10-15..10-19 backtest put long shots at +185..+3948 (3-37%) on top: not what the user asked of parlays
    # ("high hit rates, not long shots", 2026-10-17).
    "value": {"label": "Cross-game parlays: value", "sizes": (2, 3), "per_game_legs": 4, "per_sheet": 5, "max_decimal": 4.0,
              "note": "One leg from each of 2 or 3 games, each one beating the no-vig fair by 2% or more at the same "
                      "book; +100 or better. The edges multiply, so these are the parlays priced to win over time -- at "
                      "a lower hit rate."},
}


def _dec(american: Any) -> float | None:
    return cs.decimal_odds(american)


def american(decimal: float) -> int:
    return round((decimal - 1) * 100) if decimal >= 2 else round(-100 / (decimal - 1))


def _leg_key(leg: Mapping[str, Any]) -> tuple:
    return (leg["sport"], str(leg["event_id"]), str(leg.get("player") or ""), str(leg.get("market") or "").lower(),
            str(leg.get("side") or "").lower(), str(leg.get("line")))


def value_legs(sheet: Mapping[str, Any], *, started: Iterable[str] = ()) -> list[dict[str, Any]]:
    """The sheet's legs that beat the no-vig fair by >= VALUE_EV_PCT at a parlay book, with only those books' prices.

    Sources:
      * prop rows, priced at every book that quotes them;
      * Syndicate picks and game lines, at their best book only, which is all the sheet keeps for them.
    Never used: a one-sided fair (no measured fair to beat), or an edge over SUSPECT_EV_PCT (a stale or mis-paired
    quote far more often than a price)."""
    sport, started = str(sheet.get("sport")), {str(e) for e in started}
    games = {str(g.get("event_id")): g for g in sheet.get("games") or []}
    out: dict[tuple, dict[str, Any]] = {}

    def add(leg: dict[str, Any]) -> None:
        if not leg["prices"] or str(leg["event_id"]) in started:
            return
        key = _leg_key(leg)
        if key not in out or max(leg["ev_by_book"].values()) > max(out[key]["ev_by_book"].values()):
            out[key] = leg

    def priced(p: float | None, prices: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, float]]:
        keep, evs = {}, {}
        for book, price in (prices or {}).items():
            if book not in PARLAY_BOOKS or p is None:
                continue
            ev = cs.ev_pct(p, price)
            if ev is not None and cs.VALUE_EV_PCT <= ev <= cs.SUSPECT_EV_PCT:
                keep[book], evs[book] = price, ev
        return keep, evs

    for row in sheet.get("rows") or []:
        check = row.get("check") or {}
        if str(row.get("fair_method") or "") in cs.ONE_SIDED_FAIR_METHODS or check.get("verdict") == "one_sided_fair":
            continue
        p = check.get("p_market")
        prices, evs = priced(p if isinstance(p, (int, float)) else None, row.get("book_prices") or {})
        game = games.get(str(row.get("event_id"))) or {}
        add({"sport": sport, "kind": "prop", "event_id": row.get("event_id"), "matchup": row.get("matchup") or game.get("matchup"),
             "commence_time": row.get("commence_time"), "player": row.get("player"), "market": row.get("market"),
             "side": row.get("side"), "line": row.get("line"), "p": p, "prices": prices, "ev_by_book": evs,
             "bet": f"{row.get('player')} {str(row.get('side') or '').title()} {row.get('line')} {row.get('market')}",
             "result_key": cs.prop_result_key(row)})
    for pick in sheet.get("picks") or []:
        if pick.get("dropped_at"):
            continue
        p = pick.get("p_market")
        prices, evs = priced(p if isinstance(p, (int, float)) else None, {pick.get("book"): pick.get("price")})
        add({"sport": sport, "kind": "pick", "event_id": pick.get("event_id"), "matchup": pick.get("matchup"),
             "commence_time": pick.get("commence_time"), "player": pick.get("player_name"), "market": pick.get("market"),
             "side": pick.get("side"), "line": pick.get("line"), "p": p, "prices": prices, "ev_by_book": evs,
             "bet": f"{pick.get('player_name') + ' ' if pick.get('player_name') else ''}{cs.pick_bet_text(pick)}",
             "result_key": cs.pick_result_key(pick)})
    for line in sheet.get("game_lines") or []:
        check = line.get("check") or {}
        if check.get("verdict") != "value":
            continue
        p = check.get("p_market")
        prices, evs = priced(p if isinstance(p, (int, float)) else None, {check.get("book"): check.get("price")})
        game = games.get(str(line.get("event_id"))) or {}
        words = {"h2h": "moneyline", "spreads": "", "totals": ""}.get(str(line.get("market")), str(line.get("market")))
        text = (f"{str(line.get('side')).title()} {line.get('line'):g}" if line.get("market") == "totals"
                else f"{line.get('side_name') or line.get('side')} {line.get('line'):+g}" if line.get("market") == "spreads"
                and isinstance(line.get("line"), (int, float)) else f"{line.get('side_name') or line.get('side')} {words}")
        add({"sport": sport, "kind": "line", "event_id": line.get("event_id"), "matchup": game.get("matchup"),
             "commence_time": line.get("commence_time"), "player": None, "market": line.get("market"),
             "side": line.get("side"), "line": line.get("line"), "p": p, "prices": prices, "ev_by_book": evs,
             "bet": text.strip(), "result_key": cs.line_result_key(line)})
    return list(out.values())


def hit_rate_legs(sport: str, pool: Mapping[str, Sequence[Mapping[str, Any]]], games: Mapping[str, Any], *,
                  started: Iterable[str] = ()) -> list[dict[str, Any]]:
    """A same-game parlay leg pool (`{event_id: [leg]}`, each leg with `p_side` and `prices`) as cross-game legs, at
    parlay books only."""
    started = {str(e) for e in started}
    out = []
    for event_id, legs in pool.items():
        if str(event_id) in started:
            continue
        for leg in legs:
            prices = {b: v for b, v in (leg.get("prices") or {}).items() if b in PARLAY_BOOKS}
            if not prices:
                continue
            words = str(leg.get("market") or "").replace("player_", "").replace("_", " ")
            out.append({"sport": sport, "kind": "prop", "event_id": event_id, "player_id": leg.get("player_id"), "team": leg.get("team"),
                        "matchup": (games.get(str(event_id)) or {}).get("matchup"),
                        "commence_time": leg.get("commence_time"), "player": leg.get("player"), "market": leg.get("market"),
                        "side": leg.get("side"), "line": leg.get("line"), "p": leg.get("p_side"), "p_market": leg.get("p_market"),
                        "prices": prices, "bet": f"{leg.get('player')} {str(leg.get('side') or '').title()} {leg.get('line')} {words}",
                        "result_key": cs.prop_result_key(leg)})
    return out


def _best_book(combo: Sequence[Mapping[str, Any]]) -> tuple[str, float] | None:
    books = set(combo[0]["prices"])
    for leg in combo[1:]:
        books &= set(leg["prices"])
    best = None
    for book in books:
        product = 1.0
        for leg in combo:
            d = _dec(leg["prices"][book])
            if not d:
                product = 0.0
                break
            product *= d
        if product and (best is None or product > best[1]):
            best = (book, product)
    return best


def tickets(legs: Sequence[Mapping[str, Any]], kind: str, *, min_decimal: float = MIN_DECIMAL,
            min_sports: int = 1) -> list[dict[str, Any]]:
    """The kind's tickets: one leg per game, every leg priced at the ticket's book, the legs multiplied >= `min_decimal`.
    Both kinds: the likeliest first (value: among tickets whose legs beat their prices, up to +300). A ticket sharing
    all but one leg with a better one is dropped."""
    spec = KINDS[kind]
    by_game: dict[str, list[Mapping[str, Any]]] = {}
    for leg in legs:
        if isinstance(leg.get("p"), (int, float)) and leg.get("prices"):
            by_game.setdefault(f"{leg['sport']}|{leg['event_id']}", []).append(leg)
    for g, ls in by_game.items():
        if kind == "hit_rate":
            # The legs that can reach +100 in 3-4: the cheaper side of the pool (market <= 85%), likeliest first.
            ls = [l for l in ls if (l.get("p_market") or l["p"]) <= 0.85] or ls
            by_game[g] = sorted(ls, key=lambda l: -l["p"])[:spec["per_game_legs"]]
        else:
            by_game[g] = sorted(ls, key=lambda l: -max(l["ev_by_book"].values()))[:spec["per_game_legs"]]
    built = []
    for size in spec["sizes"]:
        for gs in itertools.combinations(sorted(by_game), size):
            if min_sports > 1 and len({g.split("|", 1)[0] for g in gs}) < min_sports:
                continue                 # "across sports": a one-sport ticket belongs to that sport's own list
            for combo in itertools.product(*(by_game[g] for g in gs)):
                best = _best_book(combo)
                if not best or best[1] < min_decimal or best[1] > spec.get("max_decimal", float("inf")):
                    continue
                book, dec = best
                p = 1.0
                for leg in combo:
                    p *= float(leg["p"])
                ev = p * dec - 1
                if kind == "value" and ev <= 0:
                    continue
                built.append((p, ev, book, dec, combo))
    built.sort(key=lambda x: (-x[0], -x[1]))           # likeliest first; the value kind holds only EV > 0 tickets
    out, kept = [], []
    for p, ev, book, dec, combo in built:
        ids = {_leg_key(l) for l in combo}
        if any(len(ids & other) >= len(ids) - 1 for other in kept):
            continue
        kept.append(ids)
        legs_out = [{"sport": l["sport"], "kind": l["kind"], "event_id": l["event_id"], "matchup": l.get("matchup"),
                     "commence_time": l.get("commence_time"), "player": l.get("player"), "market": l.get("market"),
                     "side": l.get("side"), "line": l.get("line"), "bet": l["bet"], "price": l["prices"][book],
                     "p": round(float(l["p"]), 4), "result_key": l["result_key"],
                     **({"player_id": l["player_id"], "team": l.get("team")} if l.get("player_id") else {})} for l in combo]
        ident = "|".join(sorted("/".join(map(str, _leg_key(l))) for l in combo)) + "|" + book
        out.append({"xg_id": "xg_" + hashlib.sha1(ident.encode()).hexdigest()[:12], "kind": kind, "label": spec["label"],
                    "note": spec["note"], "size": len(combo), "book": book, "decimal": round(dec, 4),
                    "price": american(dec), "p_joint": round(p, 4), "ev_pct": round(100 * ev, 1),
                    "worth_it_odds": american(1 / p) if 0 < p < 1 else None,
                    "sports": sorted({l["sport"] for l in combo}), "legs": legs_out})
        if len(out) >= spec["per_sheet"]:
            break
    return out


def grade(ticket: Mapping[str, Any], reconciled_by_sport: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """{status, units, legs}: LOST as soon as a leg loses; WON when every leg left wins; a void leg (push, did not
    play) is dropped and the rest re-multiplied, as books settle a regular parlay; PENDING otherwise. 1 unit a ticket.

    A prop leg is graded by the same rule as the same-game parlays (`cheat_sheets.sgp_results`): its own line, else
    the player's actual stat for the game (an alt rung is rarely a line the sheet graded). A pick or a game line is
    graded from the day's reconciled picks / lines."""
    results, dec = [], 1.0
    for leg in ticket.get("legs") or []:
        rec = reconciled_by_sport.get(leg["sport"]) or {}
        actual = None
        if leg["kind"] == "prop":
            one = cs.sgp_results([{"legs": [leg]}], rec)[0]["legs"][0]
            status, actual = one["result"], one.get("actual")
        else:
            bucket = (rec.get("picks") if leg["kind"] == "pick" else rec.get("lines")) or {}
            voids = (rec.get("picks_void") if leg["kind"] == "pick" else {}) or {}
            res = bucket.get(leg["result_key"])
            y = res.get("y") if isinstance(res, Mapping) else None
            status = ("won" if y == 1 else "lost" if y == 0 else "void" if y is not None or leg["result_key"] in voids
                      else "pending")
            actual = res.get("v") if isinstance(res, Mapping) else None
        if status == "won":
            dec *= cs.decimal_odds(leg["price"]) or 1.0
        results.append({"bet": leg["bet"], "result": status, "actual": actual})
    states = [r["result"] for r in results]
    if "lost" in states:
        return {"status": "lost", "units": -1.0, "legs": results}
    if "pending" in states:
        return {"status": "pending", "units": None, "legs": results}
    if all(s == "void" for s in states):
        return {"status": "void", "units": 0.0, "legs": results}
    return {"status": "won", "units": round(dec - 1, 3), "legs": results}
