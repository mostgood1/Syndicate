"""Cheat sheets with a price check on every row (lane `cheat-sheets`, user 2026-10-14).

The user's brief: touts on X post daily cheat sheets -- defense vs position, hit-rate / "consistency" streaks on alt
lines, game-flow sheets, strikeout ladders -- and Syndicate already holds every input behind them. What no tout shows
is whether THE PRICE already knows it. Syndicate's own measurements say it usually does: role, usage, matchup and
recency signals were tested pre-registered in six sports and found priced (findings_2026-10-1[34]_*_signals_v1.md).
So every row here carries four numbers side by side, and a verdict that only calls something value when the price
leaves room for it:

  market   the Shin fair probability of the side (the board's `quote.fair_probability`)
  model    Syndicate's own probability (`projection.model_prob_over`, side-adjusted), with its measured skill
  form     the player's hit record on THIS line and side, last 5 / last 10 (prop_evidence `recent_form.values`)
  posterior  a beta-binomial blend ANCHORED ON THE MARKET: (k * p_market + hits) / (k + games). A 5-for-5 streak moves
           a 75% price to 80% at k = 20, which is what a streak is worth when the line was set knowing it.

EV is computed at the best US price for each probability. Pure functions only: the generator
(`scripts/build_cheat_sheets.py`) does the IO, and the web page reads its JSON (no request-time compute).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

PRIOR_STRENGTH = 40.0          # k: games' worth of weight the market price carries in the consistency posterior.
# PROVISIONAL (2026-10-14): Syndicate's pre-registered signal tests found recent form / hot streaks mostly PRICED
# (MLB hot streak +0.0% on 3,556 lines; no NFL / NBA trend signal survived), so form gets little weight until the
# consistency backtest (C:/tmp/edge-analyses/consistency) fits k on outcomes. Pages label this column provisional.
K_IS_PROVISIONAL = True
STREAK_RATE = 0.8              # "consistent": cleared the line in >= 80% of the last N
STREAK_MIN_GAMES = 5
VALUE_EV_PCT = 2.0             # the board's Suggested threshold
SUSPECT_EV_PCT = 10.0          # above this an "edge" is a stale or mis-paired quote far more often than a price (the
                               # board caps plausibility at 5.26%; play cards refuse above 10)
ONE_SIDED_FAIR_METHODS = frozenset({"book_margin_model", "one_sided", "assumed_hold"})
MODEL_LEAN_PP = 5.0            # model vs market gap worth showing


def decimal_odds(american: float | int | None) -> float | None:
    if american is None:
        return None
    a = float(american)
    if a == 0:
        return None
    return 1.0 + (a / 100.0 if a > 0 else 100.0 / -a)


def ev_pct(prob: float | None, american: float | int | None, fee: float = 0.0) -> float | None:
    """EV per unit staked. `fee` is the venue's taker fee per $1 contract (0 for a sportsbook, whose margin is already
    in its price): a contract at implied q costs q + fee and pays 1, so EV = (p - q - fee) / (q + fee)."""
    dec = decimal_odds(american)
    if prob is None or dec is None:
        return None
    if not fee:
        return round(100.0 * (prob * dec - 1.0), 2)
    q = 1.0 / dec
    return round(100.0 * (prob - q - fee) / (q + fee), 2)


def taker_fee(row: Mapping[str, Any], book: Any, price: Any) -> float:
    """The board's own fee lookup (`venue_fees.taker_fee_per_contract`: Kalshi per series, Polymarket, ...). 0 when
    the venue charges none or the lookup fails -- a failed lookup is reported by the caller's reasons, not hidden."""
    dec = decimal_odds(price)
    if dec is None or not book:
        return 0.0
    try:
        from syndicate.features.shared import venue_fees

        fee, _basis, _bound = venue_fees.taker_fee_per_contract(
            book, 1.0 / dec, sport=row.get("sport"), market=row.get("market"), segment=row.get("segment"))
        return float(fee or 0.0)
    except Exception:  # noqa: BLE001
        return 0.0


def implied_from_price(american: float | int | None) -> float | None:
    dec = decimal_odds(american)
    return None if dec is None else 1.0 / dec


def side_hit(value: float, line: float, side: str) -> int | None:
    """1 = cleared, 0 = missed, None = push. `yes` (anytime / 1+) is over 0.5 when no line is given."""
    if value == line:
        return None
    if side in ("over", "yes"):
        return 1 if value > line else 0
    if side == "under":
        return 1 if value < line else 0
    return None


def form_record(values: Sequence[float] | None, line: float | None, side: str, n: int) -> dict[str, Any]:
    """Hit record over the newest `n` values (values are newest first), pushes excluded."""
    if not values or line is None:
        return {"games": 0, "hits": 0, "rate": None, "values": []}
    window = [float(v) for v in list(values)[:n] if v is not None]
    outcomes = [side_hit(v, float(line), side) for v in window]
    graded = [o for o in outcomes if o is not None]
    hits = sum(graded)
    return {"games": len(graded), "hits": hits, "rate": round(hits / len(graded), 3) if graded else None,
            "values": window}


def consistency_posterior(p_market: float | None, hits: int, games: int, k: float = PRIOR_STRENGTH) -> float | None:
    """Beta-binomial mean with the MARKET as the prior: what a streak is worth once the price already knew it."""
    if p_market is None:
        return None
    return round((k * p_market + hits) / (k + games), 4)


def side_prob(p_over: float | None, side: str) -> float | None:
    if p_over is None:
        return None
    if side in ("over", "yes"):
        return float(p_over)
    if side == "under":
        return 1.0 - float(p_over)
    return None


def skill_note(model_skill: Mapping[str, Any] | None) -> str | None:
    """One plain line from `projection.model_skill`: does the model beat, tie or lose to the book in this market?"""
    if not isinstance(model_skill, Mapping):
        return None
    rel = model_skill.get("established_loss_rel")
    status = str(model_skill.get("status") or model_skill.get("verdict") or "").lower()
    if isinstance(rel, (int, float)) and rel > 0:
        return f"model loses to the book in this market (measured, {rel:+.1%} worse)"
    if "parity" in status or "tie" in status:
        return "model ties the book in this market"
    if "beat" in status:
        return "model beats the book in this market (measured)"
    if status in ("unmeasured", "insufficient", "insufficient_sample"):
        return "model skill not yet measured in this market"
    return None


@dataclass
class PriceCheck:
    p_market: float | None
    p_model: float | None
    p_posterior: float | None
    price: float | None
    book: str | None
    ev_market: float | None
    ev_model: float | None
    ev_posterior: float | None
    form5: dict[str, Any]
    form10: dict[str, Any]
    verdict: str
    reasons: list[str]

    def as_dict(self) -> dict[str, Any]:
        return {"p_market": self.p_market, "p_model": self.p_model, "p_posterior": self.p_posterior,
                "price": self.price, "book": self.book, "ev_market": self.ev_market, "ev_model": self.ev_model,
                "ev_posterior": self.ev_posterior, "form5": self.form5, "form10": self.form10,
                "verdict": self.verdict, "reasons": self.reasons}


def price_check(row: Mapping[str, Any], form_values: Sequence[float] | None) -> PriceCheck:
    quote = row.get("quote") if isinstance(row.get("quote"), Mapping) else {}
    proj = row.get("projection") if isinstance(row.get("projection"), Mapping) else {}
    side = str(row.get("side") or "").lower()
    line = row.get("line")
    line = 0.5 if line is None and side == "yes" else line
    price = quote.get("price")
    p_market = quote.get("fair_probability")
    p_market = float(p_market) if isinstance(p_market, (int, float)) else None
    p_model = side_prob(proj.get("model_prob_over"), side)
    form5 = form_record(form_values, line, side, 5)
    form10 = form_record(form_values, line, side, 10)
    p_post = consistency_posterior(p_market, form10["hits"], form10["games"])
    # Every EV here is NET of the venue's taker fee: the exchanges (Kalshi, Polymarket, ...) dominate the best prices,
    # and the board's own Suggested rule is fee-net -- a gross EV would sell the fee as edge.
    fee = taker_fee(row, quote.get("bookmaker"), price)
    ev_m, ev_mod, ev_post = ev_pct(p_market, price, fee), ev_pct(p_model, price, fee), ev_pct(p_post, price, fee)
    reasons: list[str] = []
    if fee:
        reasons.append(f"after the {quote.get('bookmaker')} fee ({100 * fee:.1f}c a contract)")
    streak = form5["games"] >= STREAK_MIN_GAMES and (form5["rate"] or 0) >= STREAK_RATE
    one_sided = (str(quote.get("fair_method") or "") in ONE_SIDED_FAIR_METHODS
                 or quote.get("assumed_hold_pct") is not None)
    if one_sided:
        # A one-sided market (yes-only scorer / over-only shots) has no de-viggable pair: its "fair" assumes a hold and
        # was measured 8.5 pts overstated (findings_2026-09-21_layer2_score_outcomes.md). Never value; say why.
        verdict = "one_sided_fair"
        reasons.append("one-sided market: the fair price assumes a hold, so EV here is not comparable")
    elif ev_m is not None and ev_m > SUSPECT_EV_PCT:
        verdict = "suspect_price"
        reasons.append(f"best price beats the fair by {ev_m:+.1f}% -- too big to trust: check the price is still up")
    elif ev_m is not None and ev_m >= VALUE_EV_PCT:
        verdict = "value"
        reasons.append(f"best price beats the fair by {ev_m:+.1f}%")
    elif streak and ev_post is not None and ev_post >= 0:
        verdict = "streak_with_room"
        reasons.append(f"{form5['hits']}/{form5['games']} on this line and the price still leaves {ev_post:+.1f}%")
    elif streak:
        verdict = "streak_priced_in"
        imp = implied_from_price(price)
        reasons.append(f"{form5['hits']}/{form5['games']} on this line, but the price already implies "
                       f"{imp:.0%}" if imp else "streak, but no usable price")
    else:
        verdict = "neutral"
    if p_model is not None and p_market is not None and abs(p_model - p_market) * 100 >= MODEL_LEAN_PP:
        lean = "above" if p_model > p_market else "below"
        reasons.append(f"model {p_model:.0%} vs market {p_market:.0%} ({lean})")
    note = skill_note(proj.get("model_skill"))
    if note:
        reasons.append(note)
    return PriceCheck(p_market, p_model, p_post, price, quote.get("bookmaker"), ev_m, ev_mod, ev_post, form5, form10,
                      verdict, reasons)


# ----------------------------------------------------------------------------- game script (NFL / NCAAF)


def game_script(game_sim: Mapping[str, Any] | None, home: str, away: str, *, lean_points: float = 3.5) -> dict[str, Any] | None:
    """Expected script from the sim: who leads, by how much, and the generic volume read for each side."""
    if not isinstance(game_sim, Mapping):
        return None
    margin = game_sim.get("margin_mean")  # home minus away
    total = game_sim.get("total_mean")
    if not isinstance(margin, (int, float)):
        return None
    out: dict[str, Any] = {"margin_mean": round(float(margin), 1), "total_mean": total,
                           "home_win": game_sim.get("home_win_rate")}
    if abs(margin) < lean_points:
        out["script"] = "close"
        out["read"] = "close game expected: no strong script lean"
        return out
    leader, trailer = (home, away) if margin > 0 else (away, home)
    out.update({"script": "lean", "leader": leader, "trailer": trailer,
                "helped": [f"{leader} rushing volume", f"{trailer} passing volume"],
                "hurt": [f"{leader} late passing", f"{trailer} rushing volume"],
                "read": f"{leader} projected ahead by {abs(margin):.1f}"})
    return out


# ----------------------------------------------------------------------------- price shopping


def shop_gap(book_prices: Mapping[str, float] | None) -> dict[str, Any] | None:
    """Best vs median book on the SAME line and side: how much a bettor gives away by not shopping.

    Reported as implied-probability points (median implied minus best implied) -- a cost, not an edge: the board
    already prices at the best book. Needs >= 3 books so the median is not the best book itself.
    """
    prices = [float(p) for p in (book_prices or {}).values() if isinstance(p, (int, float))]
    if len(prices) < 3:
        return None
    implied = sorted(implied_from_price(p) for p in prices)
    best = implied[0]
    median = implied[len(implied) // 2]
    best_book = min((book_prices or {}).items(), key=lambda kv: implied_from_price(kv[1]) or 9)[0]
    return {"best_book": best_book, "books": len(prices), "gap_pp": round(100.0 * (median - best), 2),
            "best_implied": round(best, 4), "median_implied": round(median, 4)}


# ----------------------------------------------------------------------------- game lines

GAME_MARKETS = ("spreads", "h2h", "totals")


def game_line_check(row: Mapping[str, Any]) -> dict[str, Any]:
    """The price check for a spread / moneyline / total: best price vs the no-vig fair, net of the venue fee.

    The model probability is the board's own calibrated number for THIS side (`model_probability_cal`, else raw); it
    is shown, never the reason -- the game models were measured to trail the close (findings_2026-10-1[34]_*)."""
    quote = row.get("quote") if isinstance(row.get("quote"), Mapping) else {}
    price, book = quote.get("price"), quote.get("bookmaker")
    p_market = quote.get("fair_probability")
    p_market = float(p_market) if isinstance(p_market, (int, float)) else None
    p_model = row.get("model_probability_cal")
    if not isinstance(p_model, (int, float)):
        p_model = row.get("model_probability_raw")
    p_model = float(p_model) if isinstance(p_model, (int, float)) else None
    fee = taker_fee(row, book, price)
    ev_m, ev_mod = ev_pct(p_market, price, fee), ev_pct(p_model, price, fee)
    one_sided = str(quote.get("fair_method") or "") in ONE_SIDED_FAIR_METHODS or quote.get("assumed_hold_pct") is not None
    reasons: list[str] = []
    if one_sided:
        verdict = "one_sided_fair"
    elif ev_m is not None and ev_m > SUSPECT_EV_PCT:
        verdict = "suspect_price"
        reasons.append(f"best price beats the fair by {ev_m:+.1f}% -- too big to trust: check the price is still up")
    elif ev_m is not None and ev_m >= VALUE_EV_PCT:
        verdict = "value"
        reasons.append(f"best price beats the fair by {ev_m:+.1f}%")
    else:
        verdict = "neutral"
    if fee:
        reasons.append(f"after the {book} fee ({100 * fee:.1f}c a contract)")
    if p_model is not None and p_market is not None and abs(p_model - p_market) * 100 >= MODEL_LEAN_PP:
        reasons.append(f"model {p_model:.0%} vs market {p_market:.0%} ({'above' if p_model > p_market else 'below'})")
    return {"price": price, "book": book, "p_market": p_market, "p_model": p_model, "ev_market": ev_m,
            "ev_model": ev_mod, "verdict": verdict, "reasons": reasons}


def game_line_sections(lines: Sequence[Mapping[str, Any]], *, top: int = 25) -> dict[str, list[int]]:
    idx = range(len(lines))
    ev = lambda i: (lines[i].get("check") or {}).get("ev_market")
    verdict = lambda i: (lines[i].get("check") or {}).get("verdict")
    return {
        "value": sorted((i for i in idx if verdict(i) == "value"), key=lambda i: -(ev(i) or 0))[:top],
        "shop": sorted((i for i in idx if (lines[i].get("shop") or {}).get("gap_pp", 0) >= 2.0),
                       key=lambda i: -(lines[i].get("shop") or {}).get("gap_pp", 0))[:top],
        "all": sorted(idx, key=lambda i: (GAME_MARKETS.index(lines[i]["market"]) if lines[i].get("market") in GAME_MARKETS else 9,
                                           str(lines[i].get("side"))))[:300],
    }


# ----------------------------------------------------------------------------- matchup extremes (NFL DvP)


def dvp_extremes(dvp_teams: Mapping[str, Any], defense: str, *, top: int = 4) -> list[dict[str, Any]]:
    """The categories where `defense` allows the MOST (rank 1 = fewest), worst first -- the tout DvP line, sourced."""
    out = []
    for pos, stats in ((dvp_teams or {}).get(defense) or {}).items():
        for stat, cell in (stats or {}).items():
            if isinstance(cell, Mapping) and isinstance(cell.get("rank"), int):
                of = cell.get("of") or 32
                out.append({"defense": defense, "pos": pos, "stat": stat, "nth_most": of + 1 - cell["rank"],
                            "of": of, "per_game": cell.get("per_game"), "games": cell.get("games")})
    return sorted(out, key=lambda c: c["nth_most"])[:top]


# ----------------------------------------------------------------------------- sections


def sections(rows: Iterable[Mapping[str, Any]], *, top: int = 25) -> dict[str, list[int]]:
    """Index lists into `rows` for each sheet section, each sorted by the number that matters for it."""
    rows = list(rows)
    def ev(i: int, key: str) -> float:
        v = (rows[i].get("check") or {}).get(key)
        return float(v) if isinstance(v, (int, float)) else float("-inf")
    idx = range(len(rows))
    verdict = lambda i: (rows[i].get("check") or {}).get("verdict")
    return {
        "value": sorted((i for i in idx if verdict(i) == "value"), key=lambda i: -ev(i, "ev_market"))[:top],
        "streaks_with_room": sorted((i for i in idx if verdict(i) == "streak_with_room"),
                                    key=lambda i: -ev(i, "ev_posterior"))[:top],
        "streaks_priced_in": sorted((i for i in idx if verdict(i) == "streak_priced_in"),
                                    key=lambda i: ev(i, "ev_posterior"))[:top],
        "shop_gaps": sorted((i for i in idx if (rows[i].get("shop") or {}).get("gap_pp", 0) >= 2.0),
                            key=lambda i: -(rows[i].get("shop") or {}).get("gap_pp", 0))[:top],
        # Streaks are shown as what they measured to be: already in the price (consistency backtest 2026-10-14, NFL +
        # NBA + MLB, 2,197 tout-style 5/5 rungs: hit 2.6 pts BELOW the Shin fair [-4.9, -0.3], ROI -8.5%; a shrunk
        # streak estimate added nothing out of sample). One section, ordered by the record, EV = price vs fair.
        "hot_streaks": sorted((i for i in idx if verdict(i) in ("streak_with_room", "streak_priced_in")),
                              key=lambda i: (-_form(rows[i], "form10").get("rate", 0), -_form(rows[i], "form5").get("hits", 0)))[:top],
        # Strong form where only one side is quoted (soccer shots / SOT / assists are almost all one book, over only):
        # no fair price exists to measure the streak against, so it is shown as form and model -- never as edge.
        "hot_form": sorted((i for i in idx if verdict(i) == "one_sided_fair" and _hot(rows[i])),
                           key=lambda i: (-_form(rows[i], "form10").get("rate", 0), -_form(rows[i], "form5").get("hits", 0)))[:top],
        # Everything on the board, for a game's own sheet (the page shows it there only).
        "every_prop": sorted(idx, key=lambda i: (str(rows[i].get("market")), str(rows[i].get("player")),
                                                 rows[i].get("line") if isinstance(rows[i].get("line"), (int, float)) else 0,
                                                 str(rows[i].get("side"))))[:EVERY_PROP_CAP],
    }


EVERY_PROP_CAP = 200


def _form(row: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    return (row.get("check") or {}).get(key) or {}


def _hot(row: Mapping[str, Any]) -> bool:
    f5, f10 = _form(row, "form5"), _form(row, "form10")
    return (f5.get("games", 0) >= STREAK_MIN_GAMES and f5.get("hits", 0) >= 4) or \
        (f10.get("games", 0) >= 8 and (f10.get("rate") or 0) >= STREAK_RATE)


SPORT_ORDER = ("nfl", "ncaaf", "nba", "nhl", "soccer", "ncaab", "wnba", "mlb")


_ROW_DROP = ("book_prices", "evidence_error")


def page_payload(sheets: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """sport -> the sheet as the page shows it, sports in board order.

    Every row is kept (a game's own sheet needs all of its props), minus the fields the page never reads. Each row
    carries its card id and whether its price check passes (only those get a pick graphic). `game_sections` holds,
    per game, the same sections the full sheet has, as indexes into `rows`."""
    from syndicate.features.shared import play_cards as pc

    out: dict[str, dict[str, Any]] = {}
    for sheet in sorted(sheets, key=lambda d: SPORT_ORDER.index(d["sport"]) if d.get("sport") in SPORT_ORDER else 99):
        sport, day = str(sheet.get("sport")), str(sheet.get("date"))
        rows = []
        for r in sheet.get("rows") or []:
            row = {k: v for k, v in r.items() if k not in _ROW_DROP}
            row["card_id"] = pc.card_id(sport, day, r)
            row["card_ok"] = pc.eligible(r)
            rows.append(row)
        by_game: dict[Any, list[int]] = {}
        for i, r in enumerate(rows):
            by_game.setdefault(r.get("event_id"), []).append(i)
        doc = dict(sheet)
        doc["rows"] = rows
        doc["sections"] = sections(rows)
        doc["games"] = [dict(g, props=len(by_game.get(g.get("event_id"), []))) for g in sheet.get("games") or []]
        lines = list(sheet.get("game_lines") or [])
        lines_by_game: dict[Any, list[int]] = {}
        for i, line in enumerate(lines):
            lines_by_game.setdefault(line.get("event_id"), []).append(i)
        doc["game_lines"] = lines
        doc["game_line_sections"] = game_line_sections(lines)
        doc["game_line_sections_by_game"] = {
            str(event): {k: [idx[j] for j in ids] for k, ids in game_line_sections([lines[i] for i in idx]).items()}
            for event, idx in lines_by_game.items()}
        doc["game_sections"] = {
            str(event): {k: [idx[j] for j in ids] for k, ids in sections([rows[i] for i in idx]).items()}
            for event, idx in by_game.items()}
        out[sport] = doc
    return out


def render_page(template: str, sheets: Iterable[Mapping[str, Any]], *, logo_src: str,
                meta: Mapping[str, Any] | None = None) -> str:
    """The branded page with the data inlined. `</` is escaped so no string in the data can close the script."""
    data = json.dumps(page_payload(sheets), default=str).replace("</", "<\\/")
    info = json.dumps(dict(meta or {"mode": "static"}), default=str).replace("</", "<\\/")
    return (template.replace("/*__DATA__*/null", data, 1).replace("/*__META__*/null", info, 1)
            .replace("__LOGO_SRC__", logo_src))
