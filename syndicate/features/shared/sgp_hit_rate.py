"""High-hit-rate same-game parlays: the sport-agnostic half (lanes `nhl-sgp-builder`, `nfl-sgp-builder`; user 2026-10-17:
"use the consistency sheets to build them so we can deliver high hit rates, not long shots. Between alt lines hit rates
and consistency data in general + our sim engine data we should generate high hit rate SGPS", then "Two tiers", long
shots "Off the sheet", and "once NHL is up and running we need NFL to function the same way").

A sport supplies its legs from EVERY priced alt rung in a game (its own game log, sim and lineup); this module holds
what every sport shares, so NHL and NFL cannot drift apart:

  * the three-read gate -- a rung is a leg only when the market (>= LEG_MIN_MARKET), the player's record (>=
    LEG_MIN_HITS of the last LEG_GAMES) and the sim (>= LEG_MIN_SIM) all make it likely. Its PROBABILITY stays the
    market's, nudged by the record (`consistency_posterior`, k=40): the 2026-10-14 consistency backtest found streaks
    already in the price, so the record and the sim SELECT legs and never inflate them;
  * the de-vig of an alt rung (the books' median implied over the market's typical main-line margin);
  * the two tiers and the ticket search; the "together" record for one team's legs.
"""
from __future__ import annotations

import collections
import itertools
import math
from typing import Any, Iterable, Mapping, Sequence

from syndicate.features.nfl import sgp as core

LEG_MIN_MARKET, LEG_MAX_MARKET = 0.75, 0.95   # above 95% a leg adds vig, not payout
LEG_MIN_HITS, LEG_GAMES = 8, 10
LEG_MIN_SIM = 0.75
DEFAULT_MARGIN = 1.05                          # the de-vig factor when the sheet has no main-line margin to read
POOL_CAP = 16                                  # legs per game kept for the search, best market probability first
# The two tiers (user 2026-10-17: "Two tiers"). On 10-17's NHL prices three ~87% legs win ~66% at about -200, and five
# win ~50% at about +110. `min_decimal` is the legs-multiplied price floor: a ticket that pays less is not a bet.
TIERS = (
    {"tier": "safer", "label": "Higher hit rate", "sizes": (2, 3), "min_joint": 0.62, "min_decimal": 1.40,
     "per_game": 2, "per_sheet": 10,
     "note": "Higher hit rate -- 2 or 3 legs, each one the market, the player's last 10 and our sim all make likely"},
    {"tier": "payout", "label": "Bigger payout", "sizes": (4, 5), "min_joint": 0.45, "min_decimal": 1.70,
     "per_game": 1, "per_sheet": 6, "note": "Bigger payout -- 4 or 5 of those legs, about half win, near even money"},
)
RULE = {"min_market": LEG_MIN_MARKET, "max_market": LEG_MAX_MARKET, "min_hits": LEG_MIN_HITS, "min_sim": LEG_MIN_SIM}
# MLB (user 2026-10-17: "MLB-specific bar"): no batter alt rung reaches 75% -- 1+ hit / 1+ H+R+RBI price at 0.65-0.71
# (10-16 TB @ CLE: 1 of 521 rungs passed the NHL gate). Legs at 65%+ that cleared 7 of 10; mostly 2-leg tickets.
MLB_RULE = {"min_market": 0.65, "max_market": 0.95, "min_hits": 7, "min_sim": 0.65}
MLB_TIERS = (
    {"tier": "safer", "label": "Higher hit rate", "sizes": (2,), "min_joint": 0.45, "min_decimal": 1.60, "per_game": 2,
     "per_sheet": 8, "note": "Higher hit rate -- 2 legs, each one the market, the player's last 10 and our sim all make "
                             "likely; in baseball that means about half of these win"},
    {"tier": "payout", "label": "Bigger payout", "sizes": (3,), "min_joint": 0.30, "min_decimal": 2.40, "per_game": 1,
     "per_sheet": 4, "note": "Bigger payout -- 3 of those legs, about a third win"},
)


def margins(sheet: Mapping[str, Any]) -> dict[str, float]:
    """market -> the typical main-line margin on this sheet (`*`: every market's)."""
    from syndicate.features.shared import alt_consistency as ac

    found: dict[str, list[float]] = collections.defaultdict(list)
    for row in sheet.get("rows") or []:
        f = ac._margin_factor(row)
        if f is not None:
            found[str(row.get("market") or "")].append(f)
    every = sorted(f for fs in found.values() for f in fs)
    out = {m: sorted(fs)[len(fs) // 2] for m, fs in found.items()}
    out["*"] = every[len(every) // 2] if every else DEFAULT_MARGIN
    return out


def alt_rungs(alt_rows: Iterable[Mapping[str, Any]], market_map: Mapping[str, str]) -> tuple[dict, dict]:
    """(event, player, market) -> rung -> {book: price} (the latest capture of each book's OVER rung), and each event's
    {home, away, commence_time}. `market_map`: the alternate key's base -> the sheet's market name."""
    latest: dict[tuple, tuple[str, Any]] = {}
    games: dict[str, dict[str, Any]] = {}
    for r in alt_rows:
        market = market_map.get(str(r.get("base_market") or ""))
        if market is None or str(r.get("side") or "").lower() != "over" or r.get("line") is None or r.get("price") is None:
            continue
        event = str(r.get("event_id") or "")
        games.setdefault(event, {"home": r.get("home_team"), "away": r.get("away_team"),
                                 "commence_time": r.get("commence_time")})
        key = (event, str(r.get("player") or ""), market, float(r["line"]), str(r.get("bookmaker") or ""))
        stamp = str(r.get("captured_at") or "")
        if key not in latest or stamp >= latest[key][0]:
            latest[key] = (stamp, r.get("price"))
    rungs: dict[tuple, dict[float, dict[str, Any]]] = collections.defaultdict(lambda: collections.defaultdict(dict))
    for (event, player, market, line, book), (_s, price) in latest.items():
        rungs[(event, player, market)][line][book] = price
    return rungs, games


def market_prob(books: Mapping[str, Any], factor: float) -> float | None:
    from syndicate.features.shared import alt_consistency as ac

    implied = sorted(x for x in (ac._book_prob(p) for p in books.values()) if x)
    return min(0.995, implied[len(implied) // 2] / factor) if implied else None


def gate(p_market: float | None, hits: int, p_sim: float | None, counts: collections.Counter,
         rule: Mapping[str, float] = RULE) -> bool:
    """The three reads; `counts` records which one removed a rung. `rule`: the sport's bar (MLB_RULE for baseball)."""
    if p_market is None or not (rule["min_market"] <= p_market <= rule["max_market"]):
        counts["market_gate"] += 1
        return False
    if hits < rule["min_hits"]:
        counts["record_gate"] += 1
        return False
    if p_sim is None:
        counts["no_sim"] += 1
        return False
    if p_sim < rule["min_sim"]:
        counts["sim_gate"] += 1
        return False
    return True


def leg_prob(p_market: float, hits: int, games: int) -> float:
    from syndicate.features.shared.cheat_sheets import consistency_posterior

    return consistency_posterior(p_market, hits, games)


SWEET_SPOT = 0.85     # a leg near here balances the hit rate against what it adds to the payout


def cap(pool: Mapping[str, list[dict[str, Any]]]) -> dict[str, list[dict[str, Any]]]:
    """At most POOL_CAP legs a game: every player-stat's rung nearest SWEET_SPOT first, then each one's next-nearest,
    so the search sees many players rather than one player's whole ladder -- and not only the surest rungs, whose
    product cannot reach either tier's price floor (five 93% legs multiply to about -200)."""
    out = {}
    for event, legs in pool.items():
        by_stat: dict[tuple, list[dict[str, Any]]] = collections.defaultdict(list)
        for leg in legs:
            by_stat[(leg["player"], leg["market"])].append(leg)
        for rungs in by_stat.values():
            rungs.sort(key=lambda x: abs(x["p_market"] - SWEET_SPOT))
        kept: list[dict[str, Any]] = []
        depth = 0
        while len(kept) < POOL_CAP and any(len(r) > depth for r in by_stat.values()):
            layer = sorted((r[depth] for r in by_stat.values() if len(r) > depth), key=lambda x: abs(x["p_market"] - SWEET_SPOT))
            kept += layer[:POOL_CAP - len(kept)]
            depth += 1
        out[event] = kept
    return out


def together(legs: Sequence[Mapping[str, Any]]) -> dict[str, int] | None:
    """Same-team tickets only: in the team's recent games where every player played, how often every leg cleared."""
    if len({leg.get("team") for leg in legs}) != 1:
        return None
    per = [dict(leg.get("_history") or []) for leg in legs]
    shared = set(per[0])
    for h in per[1:]:
        shared &= set(h)
    if not shared:
        return None
    hits = sum(1 for pk in shared if all(h[pk] > leg["line"] for h, leg in zip(per, legs)))
    return {"hits": hits, "games": len(shared)}


def _value(t: Mapping[str, Any]) -> float:
    return t["p_joint"] * (core.payout(t["legs_product_odds"]) or 0)


def tickets(pool: Mapping[str, list[dict[str, Any]]], cells: Mapping[str, Any], games: Sequence[Mapping[str, Any]], *,
            exclude: Any = None, relation: Any = None, tiers: Sequence[Mapping[str, Any]] = TIERS) -> list[dict[str, Any]]:
    """The two tiers, per game: every combination of the pool's legs (one rung per player-stat, never an excluded
    pair, every leg at one book) that pays at least the tier's floor and wins at least its rate, priced by the measured
    correlations. Every ticket clears the hit-rate floor; among them the one whose legs pay closest to (or over) its
    fair price leads -- heavy favourites stack vig, so a 66% ticket's legs can multiply to -244 against a fair -192
    (NHL NJ @ WSH, 10-17). Near-duplicates dropped."""
    relation = relation or core.relation_of
    by_event = {str(g.get("event_id")): g for g in games}
    out: list[dict[str, Any]] = []

    def clash(a, b):
        return (a["player"] == b["player"] and a["market"] == b["market"]) or (exclude is not None and exclude(a, b))

    for event_id, legs in pool.items():
        game = by_event.get(event_id) or {}
        for spec in tiers:
            cands = []
            for size in spec["sizes"]:
                for combo in itertools.combinations(legs, size):
                    if any(clash(a, b) for a, b in itertools.combinations(combo, 2)):
                        continue
                    if math.prod(leg["p_side"] for leg in combo) < spec["min_joint"] * 0.8:
                        continue                  # no measured correlation lifts a joint this far
                    best = core._best_book(list(combo))
                    if not best or best[1] < spec["min_decimal"]:
                        continue
                    cands.append(list(combo))
            built = []
            for start in range(0, len(cands), 400):
                chunk = cands[start:start + 400]
                by_size: dict[int, list[int]] = collections.defaultdict(list)
                for i, t in enumerate(chunk):
                    by_size[len(t)].append(i)
                for _size, idx in by_size.items():
                    pjs, levels = core.ticket_joints([chunk[i] for i in idx], cells, relation)
                    for i, pj, lv in zip(idx, pjs, levels):
                        t = chunk[i]
                        if pj != pj or pj < spec["min_joint"]:
                            continue
                        bk, prod = core._best_book(t)
                        rels = [relation(t[a], t[b]) for a in range(len(t)) for b in range(a + 1, len(t))]
                        tk = core._ticket(event_id, t, pj, lv, game, bk, prod, rels)
                        tk.update({"family": "hit_rate", "tier": spec["tier"], "tier_label": spec["label"],
                                   "tier_note": spec.get("note"), "show_estimate": False, "together": together(t)})
                        built.append((tk, t))
            built.sort(key=lambda x: (-_value(x[0]), -x[0]["p_joint"]))
            kept, kept_sets = [], []
            for tk, t in built:
                ids = {(x["player"], x["market"]) for x in t}
                if any(len(ids & other) >= len(ids) - 1 for other in kept_sets):
                    continue
                kept.append(tk)
                kept_sets.append(ids)
                if len(kept) >= spec["per_game"]:
                    break
            out += kept
    final: list[dict[str, Any]] = []
    for spec in tiers:
        mine = sorted((t for t in out if t["tier"] == spec["tier"]), key=lambda t: (-_value(t), -t["p_joint"]))
        final += mine[:spec["per_sheet"]]
    for t in final:
        for leg in t["legs"]:
            leg.pop("_history", None)
    return final
