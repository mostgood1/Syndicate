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
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
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


def streak_room_reason(hits: Any, games: Any, ev_post: float) -> str:
    """The note on a streak whose FORM-ADJUSTED estimate beats the price. It used to read "... and the price still
    leaves +3.0%" -- an endorsement next to a negative EV, when streaks like this ran 2.6 points BELOW the fair price in
    our backtest (user 2026-10-15 on the streak colours). The old text on past sheets is `OLD_STREAK_ROOM_REASON`."""
    return (f"{hits}/{games} on this line; form alone says {ev_post:+.1f}% vs the price, "
            "but streaks like this have run below the fair price")


# The wording before 2026-10-15, as past sheets carry it: "4/5 on this line and the price still leaves +3.0%".
OLD_STREAK_ROOM_REASON = re.compile(r"^(\d+)/(\d+) on this line and the price still leaves ([+-]?\d+(?:\.\d+)?)%$")


def reword_streak_reasons(rows: Iterable[dict[str, Any]]) -> int:
    """Rewrite the old streak note on already-published rows in place (user 2026-10-15: "update the old reason text on
    past sheets too"). Only that sentence changes -- no price, verdict or number -- and it returns how many moved."""
    changed = 0
    for row in rows:
        reasons = (row.get("check") or {}).get("reasons")
        if not isinstance(reasons, list):
            continue
        for k, text in enumerate(reasons):
            m = OLD_STREAK_ROOM_REASON.match(str(text))
            if m:
                reasons[k] = streak_room_reason(m.group(1), m.group(2), float(m.group(3)))
                changed += 1
    return changed


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
        reasons.append(streak_room_reason(form5["hits"], form5["games"], ev_post))
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
    # ONE filtered list for the count, the median and the best book: a text price used to raise in the best-book pick,
    # and an American 0 (no price) to crash the sort (lead from probability-differential-sweep-1015).
    priced = [(book, implied_from_price(float(p))) for book, p in (book_prices or {}).items()
              if isinstance(p, (int, float)) and not isinstance(p, bool) and float(p) != 0]
    if len(priced) < 3:
        return None
    implied = sorted(imp for _book, imp in priced)
    best = implied[0]
    median = implied[len(implied) // 2]
    best_book = min(priced, key=lambda kv: kv[1])[0]
    return {"best_book": best_book, "books": len(priced), "gap_pp": round(100.0 * (median - best), 2),
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
        "value": sorted((i for i in idx if verdict(i) == "value" and featurable(lines[i])), key=lambda i: -(ev(i) or 0))[:top],
        "shop": sorted((i for i in idx if (lines[i].get("shop") or {}).get("gap_pp", 0) >= 2.0 and featurable(lines[i])),
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


# Featured sections show a bet a reader would actually take (user 2026-10-15: "we need some sort of sanity cap on the
# lines being featured odds-wise"): a price inside this band, and ONE line per player + stat + side -- the
# best-EV rung -- not five ladder rungs of the same bet. "Every prop on the board" stays complete.
FEATURED_MIN_PRICE = -250
FEATURED_MAX_PRICE = 250


def featurable(row: Mapping[str, Any]) -> bool:
    price = (row.get("check") or {}).get("price")
    return isinstance(price, (int, float)) and FEATURED_MIN_PRICE <= price <= FEATURED_MAX_PRICE


def _stat_key(row: Mapping[str, Any]) -> tuple[str, str]:
    """A player + stat, whatever the rung or side ("player_points" and "player_points_alternate" are one stat)."""
    market = re.sub(r"_(alt|alternate)$", "", str(row.get("market") or "").strip().lower())
    return str(row.get("player") or ""), market


def primary_lines(rows: Sequence[Mapping[str, Any]]) -> set[int]:
    """ONE line per player + stat for the whole sheet (user 2026-10-15: "reduce some of duplicate player/lines across
    the sheets. players with o4.5 and o5.5 lines and pick one"). Measured on that day's sheets: no section repeated a
    player's stat, but ACROSS sections the same player sat at two rungs (NCAAF Josh Rodriguez u30.5 in Hot streaks,
    u32.5 in Streaks with room) or on both sides (NFL Lil'Jordan Humphrey over 6.5 in Hot streaks, under 6.5 in
    Matchups) -- 21 of 47 NFL player + stat groups. The line kept is the MAIN line -- the board's own rule for its
    picks (`alt_primaries`): most books quoting, then nearest the group's median, then the lower -- among the rungs a
    featured section could show (price in the band); of its two sides, the one whose price beats its no-vig fair by
    more (a one-sided market's EV is not comparable, so a two-sided quote wins). Not the best-EV rung across the
    ladder: that favours alt rungs, whose fair rests on fewer books.

    A row the build flagged `primary_locked` wins its group outright while it is still featurable: the line and side
    the day's first build chose stay put (user 2026-10-23, after NHL 10-16 Karlsson SOG u2.5 at 7/10 became the over
    at 3/10 when the prices moved -- `build_cheat_sheets.lock_primaries`)."""
    groups: dict[tuple[str, str], list[int]] = {}
    for i, r in enumerate(rows):
        if featurable(r):
            groups.setdefault(_stat_key(r), []).append(i)
    keep = set()
    for ids in groups.values():
        locked = [i for i in ids if rows[i].get("primary_locked")]
        if locked:
            keep.add(locked[0])
            continue
        books: dict[Any, int] = {}
        for i in ids:
            line = rows[i].get("line")
            books[line] = max(books.get(line, 0), int(rows[i].get("books_quoting") or 0))
        numeric = sorted(ln for ln in books if isinstance(ln, (int, float)))
        median = numeric[len(numeric) // 2] if numeric else 0.0
        main = min(books, key=lambda ln: (-books[ln], abs(ln - median) if isinstance(ln, (int, float)) else 0.0,
                                          ln if isinstance(ln, (int, float)) else 0.0))

        def side_score(i: int) -> tuple:
            c = rows[i].get("check") or {}
            ev = c.get("ev_market")
            return c.get("verdict") != "one_sided_fair", float(ev) if isinstance(ev, (int, float)) else float("-inf")

        keep.add(max((i for i in ids if rows[i].get("line") == main), key=side_score))
    return keep


def sections(rows: Iterable[Mapping[str, Any]], *, top: int = 25) -> dict[str, list[int]]:
    """Index lists into `rows` for each sheet section, each sorted by the number that matters for it. Every featured
    section draws from the same one line per player + stat (`primary_lines`); "every prop" stays complete."""
    rows = list(rows)
    def ev(i: int, key: str) -> float:
        v = (rows[i].get("check") or {}).get(key)
        return float(v) if isinstance(v, (int, float)) else float("-inf")
    every = range(len(rows))
    idx = sorted(primary_lines(rows))
    verdict = lambda i: (rows[i].get("check") or {}).get("verdict")
    out = {
        "value": sorted((i for i in idx if verdict(i) == "value"), key=lambda i: -ev(i, "ev_market")),
        "streaks_with_room": sorted((i for i in idx if verdict(i) == "streak_with_room"),
                                    key=lambda i: -ev(i, "ev_posterior")),
        "streaks_priced_in": sorted((i for i in idx if verdict(i) == "streak_priced_in"),
                                    key=lambda i: ev(i, "ev_posterior")),
        "shop_gaps": sorted((i for i in idx if (rows[i].get("shop") or {}).get("gap_pp", 0) >= 2.0),
                            key=lambda i: -(rows[i].get("shop") or {}).get("gap_pp", 0)),
        # Streaks are shown as what they measured to be: already in the price (consistency backtest 2026-10-14, NFL +
        # NBA + MLB, 2,197 tout-style 5/5 rungs: hit 2.6 pts BELOW the Shin fair [-4.9, -0.3], ROI -8.5%; a shrunk
        # streak estimate added nothing out of sample). One section, ordered by the record, EV = price vs fair.
        "hot_streaks": sorted((i for i in idx if verdict(i) in ("streak_with_room", "streak_priced_in")),
                              key=lambda i: (-_form(rows[i], "form10").get("rate", 0), -_form(rows[i], "form5").get("hits", 0))),
        # Strong form where only one side is quoted (soccer shots / SOT / assists are almost all one book, over only):
        # no fair price exists to measure the streak against, so it is shown as form and model -- never as edge.
        "hot_form": sorted((i for i in idx if verdict(i) == "one_sided_fair" and _hot(rows[i])),
                           key=lambda i: (-_form(rows[i], "form10").get("rate", 0), -_form(rows[i], "form5").get("hits", 0))),
        # Consistency (user 2026-10-15: "a consistency section for every sport to show the recent hit rate trends"):
        # every row with a full L10 sample and a 70%+ hit rate, best record first, whatever its price says -- the page
        # shows the trend (L5 vs L10) and the price beside it, and says plainly that streaks measured as priced in.
        "consistency": sorted((i for i in idx if _form(rows[i], "form10").get("games", 0) >= 8
                               and (_form(rows[i], "form10").get("rate") or 0) >= 0.7),
                              key=lambda i: (-(_form(rows[i], "form10").get("rate") or 0),
                                             -(_form(rows[i], "form5").get("rate") or 0))),
        # Matchups (user 2026-10-15: "matchup based cheat sheets"): the opponent ranks in the softest fifth at allowing
        # this stat for an over (toughest fifth for an under), most extreme first.
        "matchup_spots": sorted((i for i in idx if matchup_favors_side(rows[i]) or vs_opponent_strong(rows[i])),
                                key=lambda i: _matchup_extremity(rows[i])),
        # Player vs player (MLB). Batters vs the probable starter: one row per hitter + stat (the better-EV side),
        # biggest sample first. Pitchers vs the opposing roster: ONE row per pitcher -- his strikeout line when he has
        # one -- because the lineup line is the same for every market he is priced in.
        "pvp_batters": _one_per_player(rows, sorted(
            (i for i in idx if _pvp_kind(rows[i]) == "batter_vs_pitcher" and _pvp_pa(rows[i]) >= PVP_MIN_PA and featurable(rows[i])),
            key=lambda i: -_pvp_pa(rows[i])))[:top],
        "pvp_pitchers": _one_per_pitcher(rows, [i for i in idx if _pvp_kind(rows[i]) == "pitcher_vs_lineup"
                                                and _pvp_pa(rows[i]) >= PVP_MIN_PA and featurable(rows[i])])[:top],
        # NHL: skaters vs the opposing likely starter (2+ meetings), goalies vs today's opponent -- one row a player.
        "pvp_skaters": _one_per_player(rows, sorted(
            (i for i in idx if _pvp_kind(rows[i]) == "skater_vs_goalie" and _pvp_games(rows[i]) >= PVP_MIN_GAMES
             and featurable(rows[i])),
            key=lambda i: (-_pvp_games(rows[i]), -(((rows[i].get("pvp") or {}).get("line") or {}).get("sog") or 0))))[:top],
        "pvp_goalies": _one_per_player(rows, sorted(
            (i for i in idx if _pvp_kind(rows[i]) == "goalie_vs_team" and _pvp_games(rows[i]) >= PVP_MIN_GAMES
             and featurable(rows[i])),
            key=lambda i: -_pvp_games(rows[i])))[:top],
        # NBA defender matchups: who guarded him, 40+ partial possessions against today's opponent's defenders.
        "pvp_scorers": _one_per_player(rows, sorted(
            (i for i in idx if _pvp_kind(rows[i]) == "scorer_vs_defenders"
             and _pvp_stat(rows[i], "poss") >= PVP_MIN_POSS and featurable(rows[i])),
            key=lambda i: -_pvp_stat(rows[i], "poss")))[:top],
        # NFL plays on the ball (NOT coverage): receivers with 2+ plays by today's defenders on their targets, and
        # every quarterback against today's secondary.
        "pvp_receivers": _one_per_player(rows, sorted(
            (i for i in idx if _pvp_kind(rows[i]) == "receiver_vs_defenders"
             and _pvp_stat(rows[i], "plays") >= PVP_MIN_PLAYS and featurable(rows[i])),
            key=lambda i: -_pvp_stat(rows[i], "plays")))[:top],
        "pvp_qbs": _one_per_player(rows, sorted(
            (i for i in idx if _pvp_kind(rows[i]) == "qb_vs_defenders" and featurable(rows[i])
             and (_pvp_stat(rows[i], "plays") or (((rows[i].get("pvp") or {}).get("line")) or {}).get("hawks"))),
            key=lambda i: -_pvp_stat(rows[i], "plays")))[:top],
        # Everything on the board, for a game's own sheet (the page shows it there only).
        "every_prop": sorted(every, key=lambda i: (str(rows[i].get("market")), str(rows[i].get("player")),
                                                   rows[i].get("line") if isinstance(rows[i].get("line"), (int, float)) else 0,
                                                   str(rows[i].get("side"))))[:EVERY_PROP_CAP],
    }
    for key in ("value", "hot_streaks", "streaks_with_room", "streaks_priced_in", "hot_form", "consistency",
                "matchup_spots", "shop_gaps"):
        out[key] = out[key][:top]
    return out


EVERY_PROP_CAP = 200


# ----------------------------------------------------------------------------- posted graphics
# User 2026-10-17: "we need to look at why consistency sheets changed for NHL yesterday. Trying to promote these on
# twitter and the changes dont help for reconciling". Every build, every page view and the record re-derived a section
# from the rows of that moment, so a row that went out on a graphic could leave its section hours later. NHL 10-16: the
# consistency graphic at 12:34 PM CT showed LaCombe SOG u1.5 and Karlsson SOG u2.5; the 8:27 PM build's section held
# LaCombe and four others, Karlsson gone -- a section shows the main line's better-EV side, and that became his over
# (3/10). An exported section is now recorded beside the sheet (`<sport>/<date>.posted.json`, written by the
# blueprint) and what it recorded stays: every build keeps those rows, they lead their section on the page and in the
# reconciled view, and the record grades them at the price the graphic showed.
POSTED_SUFFIX = ".posted.json"
# The page's section keys -> the payload's, where the two differ (every other key is the same word).
POSTED_ROW_SECTIONS = {"matchups": "matchup_spots", "shop": "shop_gaps", "every": "every_prop"}
POSTED_LINE_SECTIONS = {"lines_value": "value", "lines_shop": "shop", "lines": "all"}


def load_posted(sheets_dir: Path | str, sport: str, day: str) -> dict[str, Any] | None:
    try:
        doc = json.loads((Path(sheets_dir) / sport / f"{day}{POSTED_SUFFIX}").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) and doc.get("sport") == sport and doc.get("date") == day else None


def posted_entries(posted: Mapping[str, Any] | None, kind: str) -> list[dict[str, Any]]:
    """Every posted row (`kind` "rows") or game line ("lines"), earliest post first, once per section: {section (the
    payload's key), card_id, posted_at, price, book, item (the sheet's copy when it was posted)}."""
    names = POSTED_ROW_SECTIONS if kind == "rows" else POSTED_LINE_SECTIONS
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for post in sorted(((posted or {}).get("posts") or []), key=lambda p: str(p.get("posted_at") or "")):
        page = str(post.get("section") or "")
        section = names.get(page, page)
        for e in post.get(kind) or []:
            if not (isinstance(e, Mapping) and e.get("card_id") and isinstance(e.get("item"), Mapping)):
                continue
            if (section, str(e["card_id"])) in seen:
                continue
            seen.add((section, str(e["card_id"])))
            out.append({"section": section, "card_id": str(e["card_id"]), "posted_at": post.get("posted_at"),
                        "price": e.get("price"), "book": e.get("book"), "item": dict(e["item"])})
    return out


def posted_first(posted: Mapping[str, Any] | None, kind: str) -> dict[str, dict[str, Any]]:
    """card_id -> the item's FIRST posting {at, price, book}: the price the record grades it at."""
    out: dict[str, dict[str, Any]] = {}
    for e in posted_entries(posted, kind):
        out.setdefault(e["card_id"], {"at": e["posted_at"], "price": e["price"], "book": e["book"]})
    return out


def with_posted(sheet: Mapping[str, Any], posted: Mapping[str, Any] | None, *,
                prior: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """The sheet with every posted row and game line on it. One a later board read lost (its main line moved, its group
    fell outside the build's cap) comes back as the last copy `prior` had, else as the copy that was posted, marked
    `posted_kept`; its game comes from `prior` when the sheet has none."""
    from syndicate.features.shared import play_cards as pc

    sport, day = str(sheet.get("sport")), str(sheet.get("date"))
    out = dict(sheet)
    added = 0
    for kind, field in (("rows", "rows"), ("lines", "game_lines")):
        entries = posted_entries(posted, kind)
        if not entries:
            continue
        items = list(out.get(field) or [])
        have = {pc.card_id(sport, day, it) for it in items}
        last = {pc.card_id(sport, day, it): it for it in (prior or {}).get(field) or []}
        for e in entries:
            if e["card_id"] in have:
                continue
            have.add(e["card_id"])
            items.append(dict(last.get(e["card_id"]) or e["item"], posted_kept=True))
            added += 1
        out[field] = items
    if added:
        events = {str(g.get("event_id")) for g in out.get("games") or []}
        need = {str(it.get("event_id")) for it in list(out.get("rows") or []) + list(out.get("game_lines") or [])} - events
        out["games"] = list(out.get("games") or []) + [g for g in (prior or {}).get("games") or []
                                                       if str(g.get("event_id")) in need]
        out["posted_kept"] = added
    return out


def posted_sgps(posted: Mapping[str, Any] | None) -> dict[str, dict[str, Any]]:
    """sgp_id -> {at, item}: every posted same-game parlay, by its first posting."""
    out: dict[str, dict[str, Any]] = {}
    for post in sorted(((posted or {}).get("posts") or []), key=lambda p: str(p.get("posted_at") or "")):
        for e in post.get("sgps") or []:
            if isinstance(e, Mapping) and e.get("sgp_id") and isinstance(e.get("item"), Mapping):
                out.setdefault(str(e["sgp_id"]), {"at": post.get("posted_at"), "item": dict(e["item"])})
    return out


def with_posted_sgps(tickets: Sequence[Mapping[str, Any]], posted: Mapping[str, Any] | None,
                     prior: Sequence[Mapping[str, Any]] | None = None) -> list[dict[str, Any]]:
    """The day's parlays with every POSTED one on them. A build re-suggests a game's parlays until it starts (the NHL
    refresh re-runs them whenever the ladders' alt prices change), so a ticket on an exported graphic could be gone an
    hour later. A posted ticket a build no longer suggests comes back as the last copy `prior` had, else as posted
    (`posted_kept`); every posted ticket carries `posted` {at} and leads, earliest post first."""
    first = posted_sgps(posted)
    if not first:
        return [dict(t) for t in tickets]
    have = {str(t.get("sgp_id")): t for t in tickets}
    last = {str(t.get("sgp_id")): t for t in prior or []}
    lead = []
    for sid, info in first.items():
        ticket = have.get(sid)
        if ticket is None:
            ticket = dict(last.get(sid) or info["item"], posted_kept=True)
        lead.append(dict(ticket, posted={"at": info["at"]}))
    return lead + [dict(t) for t in tickets if str(t.get("sgp_id")) not in first]


def pin_posted(secs: Mapping[str, Sequence[int]], cids: Sequence[str], entries: Sequence[Mapping[str, Any]], *,
               events: Sequence[Any] | None = None, event: Any = None, only: bool = False) -> dict[str, list[int]]:
    """`secs` with each section's posted items leading it, earliest post first, then the section's own order (an item
    the section would pick anyway is not repeated). `event` (with `events`, each item's event) narrows to one game.

    `only` -- a section that went out on a graphic is EXACTLY its posted items, nothing a later build added (user
    2026-10-22: "after reconciling I need the exported image to only reflect what was shared"). NHL 10-21: the
    consistency graphic at 11:51 AM CT carried 8 props; the reconciled section led with those 8 and then listed whatever
    the last build put in the section. A section never posted (in this scope) keeps its own rows."""
    index: dict[str, int] = {}
    for i, cid in enumerate(cids):
        index.setdefault(cid, i)
    out = {k: list(v) for k, v in secs.items()}
    lead: dict[str, list[int]] = {}
    for e in entries:
        i = index.get(e["card_id"])
        if i is None or (event is not None and str((events or [])[i]) != str(event)):
            continue
        ids = lead.setdefault(e["section"], [])
        if i not in ids:
            ids.append(i)
    for key, ids in lead.items():
        out[key] = list(ids) if only else ids + [i for i in out.get(key) or [] if i not in ids]
    return out


def posted_items(posted: Mapping[str, Any] | None, kind: str) -> dict[str, dict[str, Any]]:
    """card_id -> the item AS IT WAS POSTED (its first posting): what the graphic showed -- price, book, fair, form."""
    out: dict[str, dict[str, Any]] = {}
    for e in posted_entries(posted, kind):
        out.setdefault(e["card_id"], dict(e["item"]))
    return out


def matchup_summary(sport: str, matchup: Mapping[str, Any] | None, dvp: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """One shape for every sport's matchup: the opponent, where it ranks at allowing this stat (1 = allows the MOST),
    out of how many, and per game. NFL reads the defense-vs-position table; any evidence layer that reports
    `allowed_rank` as "N of M (1 = fewest allowed)" (NCAAF, NHL, basketball) is read the same way. None when the
    sport's evidence carries no rank (soccer reports ratings, not ranks)."""
    m = dict(matchup or {})
    if dvp and dvp.get("nth_most"):
        return {"opponent": m.get("opponent"), "nth_most": int(dvp["nth_most"]), "of": int(dvp.get("of") or 32),
                "per_game": dvp.get("per_game"), "stat": dvp.get("stat"), "pos": dvp.get("pos"), "source": "dvp"}
    raw = str(m.get("allowed_rank") or "")
    import re

    hit = re.match(r"\s*(\d+)\s+of\s+(\d+)", raw)
    if not hit:
        return None
    fewest, of = int(hit.group(1)), int(hit.group(2))
    if not 0 < fewest <= of:
        return None
    return {"opponent": m.get("opponent"), "nth_most": of - fewest + 1, "of": of,
            "per_game": m.get("allowed_per_game"), "stat": None, "pos": None, "source": "allowed_rank"}


def vs_opponent_record(matchup: Mapping[str, Any] | None, line: Any, side: Any) -> dict[str, Any] | None:
    """The player's record on THIS line + side against today's opponent (user 2026-10-15: "matchups should include
    performance against the opposing team"). The evidence computes it for its group's representative line and side
    only, so another line in the group gets the game count but no hit rate -- a record on a different line is not
    this bet's record."""
    vs = (matchup or {}).get("vs_opponent") or {}
    values = vs.get("values")
    side = str(side or "").lower()
    if isinstance(values, list) and values and (line is not None or side == "yes"):
        grade_line = 0.5 if line is None else float(line)
        rec = form_record(values, grade_line, side, len(values))      # every value, this line
        labels = list(vs.get("labels") or [])
        # The actual meetings, newest first -- one game is still worth showing as what happened, not as a rate.
        results = [{"label": labels[i] if i < len(labels) else "", "value": v,
                    "hit": side_hit(float(v), grade_line, side) if v is not None else None}
                   for i, v in enumerate(values[:3])]
        if not rec["games"] and not results:
            return None
        return {"games": rec["games"], "hits": rec["hits"], "same_line": True, "results": results}
    hr = vs.get("hit_rate") or {}
    games = int(hr.get("games") or vs.get("games") or 0)
    if not games:
        return None
    same = hr.get("line") == line and str(hr.get("side") or "").lower() == side
    return {"games": games, "hits": int(hr.get("hits") or 0) if same else None, "same_line": same}


# A record against one opponent means something only over a few meetings (user 2026-10-15: "vs opponent needs to be
# better than just 1 game, other line. that is not helpful").
VS_OPPONENT_MIN_GAMES = 3


def matchup_favors_side(row: Mapping[str, Any]) -> bool:
    mu = row.get("matchup") or {}
    k, n = mu.get("nth_most"), mu.get("of")
    if not k or not n:
        return vs_opponent_strong(row)
    fifth = max(1, round(n / 5))
    side = str(row.get("side") or "").lower()
    return (side in ("over", "yes") and k <= fifth) or (side == "under" and k > n - fifth)


def vs_opponent_strong(row: Mapping[str, Any]) -> bool:
    vs = row.get("vs_opponent") or {}
    return bool(vs.get("same_line")) and vs.get("games", 0) >= VS_OPPONENT_MIN_GAMES and (vs.get("hits") or 0) / vs["games"] >= 2 / 3


def _matchup_extremity(row: Mapping[str, Any]) -> float:
    mu = row.get("matchup") or {}
    if not mu.get("nth_most"):
        return 0.5                                   # a vs-opponent record alone sorts after the defensive extremes
    k, n = mu.get("nth_most") or 0, mu.get("of") or 1
    return k / n if str(row.get("side") or "").lower() in ("over", "yes") else (n - k + 1) / n


PVP_MIN_PA = 3     # a batter-vs-pitcher line under 3 plate appearances is not shown as a matchup


PVP_MIN_GAMES = 2   # NHL meetings: one game against a goalie is a box score, not a matchup line


PVP_MIN_POSS = 40   # NBA: under 40 partial possessions against a team's defenders is a handful of trips
PVP_MIN_PLAYS = 2   # NFL: one breakup or one tackle is an anecdote, not a matchup line


def _pvp_games(row: Mapping[str, Any]) -> int:
    return int((((row.get("pvp") or {}).get("line")) or {}).get("games") or 0)


def _pvp_stat(row: Mapping[str, Any], key: str) -> float:
    value = (((row.get("pvp") or {}).get("line")) or {}).get(key)
    return float(value) if isinstance(value, (int, float)) else 0.0


def _pvp_kind(row: Mapping[str, Any]) -> str | None:
    return (row.get("pvp") or {}).get("kind")


def _ev_of(row: Mapping[str, Any]) -> float:
    ev = (row.get("check") or {}).get("ev_market")
    return float(ev) if isinstance(ev, (int, float)) else float("-inf")


def _one_per_player(rows: Sequence[Mapping[str, Any]], ids: Sequence[int]) -> list[int]:
    """One row per batter (his career line vs the starter is the same for every prop he has): the best-EV prop,
    in the caller's order."""
    best: dict[Any, int] = {}
    order: list[Any] = []
    for i in ids:
        who = rows[i].get("player")
        if who not in best:
            order.append(who)
            best[who] = i
        elif _ev_of(rows[i]) > _ev_of(rows[best[who]]):
            best[who] = i
    return [best[w] for w in order]


def _one_per_pitcher(rows: Sequence[Mapping[str, Any]], ids: Sequence[int]) -> list[int]:
    by_player: dict[Any, list[int]] = {}
    for i in ids:
        by_player.setdefault(rows[i].get("player"), []).append(i)
    picked = []
    for group in by_player.values():
        ks = [i for i in group if "strikeout" in str(rows[i].get("market") or "").lower()]
        picked.append(max(ks or group, key=lambda i: _ev_of(rows[i])))
    return sorted(picked, key=lambda i: -_pvp_pa(rows[i]))


def _pvp_pa(row: Mapping[str, Any]) -> int:
    line = ((row.get("pvp") or {}).get("line") or {})
    return int(line.get("plateAppearances") or 0)


def _form(row: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    return (row.get("check") or {}).get(key) or {}


def _hot(row: Mapping[str, Any]) -> bool:
    f5, f10 = _form(row, "form5"), _form(row, "form10")
    return (f5.get("games", 0) >= STREAK_MIN_GAMES and f5.get("hits", 0) >= 4) or \
        (f10.get("games", 0) >= 8 and (f10.get("rate") or 0) >= STREAK_RATE)


SPORT_ORDER = ("nfl", "ncaaf", "nba", "nhl", "soccer", "ncaab", "wnba", "mlb")


_ROW_DROP = ("book_prices", "evidence_error")


def _line_text(line: Any) -> str:
    try:
        return f"{float(line):g}"
    except (TypeError, ValueError):
        return ""


def prop_result_key(row: Mapping[str, Any]) -> str:
    """A sheet prop's key in `<sport>/<date>.reconciled.json` -- the production grader's own match key
    (`grade_play_cards.match_key`: player_key, market and side lower-cased, line as a number), as text."""
    from syndicate.features.shared.basketball_props_availability import player_key

    return "|".join((player_key(row.get("player")), str(row.get("market") or "").strip().lower(),
                     str(row.get("side") or "").strip().lower(), _line_text(row.get("line"))))


def line_result_key(line: Mapping[str, Any]) -> str:
    """A game line's key in the reconciled file: the event, market, side (home/away/over/under) and line."""
    return "|".join((str(line.get("event_id") or ""), str(line.get("market") or "").strip().lower(),
                     str(line.get("side") or "").strip().lower(), _line_text(line.get("line"))))


def result_for(price: Any, graded: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """{y, units[, v]}: 1 unit at the sheet's best price -- a win pays the price, a loss costs the unit -- and `v`, the
    number the grader settled on (the actual stat; a total's combined score), when the reconcile captured it."""
    if not graded or graded.get("y") is None:
        return None
    y = float(graded["y"])
    dec = decimal_odds(price)
    units = (round(dec - 1, 3) if dec else None) if y == 1 else (-1.0 if y == 0 else 0.0)
    out = {"y": y, "units": units}
    if isinstance(graded.get("v"), (int, float)):
        out["v"] = graded["v"]
    return out


def sgp_results(tickets: Sequence[Mapping[str, Any]], reconciled: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    """WON / LOST / VOID / PENDING for each same-game parlay, with each leg's result and actual -- the paper ledger's
    rule (scripts/grade_sgp_paper.py imports this), so the reconciled page and the ledger can never disagree (user
    2026-10-17: "why arent SGPs reconciled for NHL on the live site" -- the grader wrote `sgp_graded.jsonl` and the page
    never read it). A ticket LOSES when any leg loses, is VOID when a leg is void or pushes (books' SGP void rules
    vary, so a void is never counted either way), WINS when every leg wins, and is PENDING otherwise."""
    props = (reconciled or {}).get("props") or {}
    void = (reconciled or {}).get("void") or {}
    # The player's ACTUAL stat from any graded line of the same player x market: an alt-rung leg ("OVER 30.5 saves")
    # is usually not a line the sheet itself graded. Measured 10-16: 11 of 13 NHL parlays sat "pending" for that alone.
    actual: dict[tuple[str, str], float] = {}
    voided: set[tuple[str, str]] = set()
    for key, val in props.items():
        parts = str(key).split("|")
        if len(parts) == 4 and isinstance(val, Mapping) and val.get("v") is not None:
            actual[(parts[0], parts[1])] = float(val["v"])
    for key in void:
        parts = str(key).split("|")
        if len(parts) == 4:
            voided.add((parts[0], parts[1]))
    # Legs the sheet never graded (a player off the sheet's rows): the reconcile reads them off the box-score log by the
    # leg's player id (`nhl.sgp_pool.leg_actuals`), keyed player|market.
    for key, value in ((reconciled or {}).get("leg_actuals") or {}).items():
        parts = str(key).split("|")
        if len(parts) == 2 and isinstance(value, (int, float)):
            actual.setdefault((parts[0], parts[1]), float(value))
    out = []
    for ticket in tickets:
        legs, results = [], []
        for leg in ticket.get("legs") or []:
            key = prop_result_key(leg)
            parts = key.split("|")
            pm = (parts[0], parts[1]) if len(parts) == 4 else None
            value = (props.get(key) or {}).get("v")
            if key in void or (pm in voided and pm not in actual):
                res = "void"
            elif key in props and props[key].get("y") is not None:
                res = "won" if float(props[key]["y"]) >= 1 else "lost"
            elif pm in actual:
                value = actual[pm]
                try:
                    line = float(leg.get("line"))
                except (TypeError, ValueError):
                    line = None
                side = str(leg.get("side") or "").lower()
                if line is None and side == "yes":                 # Anytime TD: a yes leg wins on any TD
                    res = "won" if value > 0 else "lost"
                elif line is None or value == line:
                    res = "void"                                   # a push is graded like a void: never won or lost
                elif side in ("over", "yes"):
                    res = "won" if value > line else "lost"
                else:
                    res = "won" if value < line else "lost"
            else:
                res = "pending"
            legs.append({"bet": leg.get("bet"), "key": key, "result": res, "actual": value})
            results.append(res)
        if "lost" in results:
            status = "lost"
        elif "void" in results:
            status = "void"
        elif results and all(r == "won" for r in results):
            status = "won"
        else:
            status = "pending"
        out.append({"status": status, "legs": legs})
    return out


# --------------------------------------------------------------------------------------------------------------------
# Syndicate picks: the Layer 2 board's SUGGESTED opps, promoted on the sheet (user 2026-10-15: "there are 7 suggested
# opps on the main layer2 board these need to translate somehow into the cheatsheet section - potentially as picks to
# promote"; "add the suggested opps as a picks section with pick graphics"). The source is the board's own cards
# (`/api/intelligence/query` -> response.board_contract.cards), so a pick reads exactly as it does on the board,
# including its written case (`detail`). The board's default view is the rule: suggested, pregame, the opportunity
# lane, MAIN lines only -- `is_alt_line` below is a port of the board's `isAltLine` (templates/intelligence.html).
# --------------------------------------------------------------------------------------------------------------------


def _alt_group(card: Mapping[str, Any]) -> str:
    return "|".join((str(card.get("event_id") or ""), str(card.get("market") or "").strip().lower(),
                     str(card.get("segment") or "full"), str(card.get("player_name") or "")))


def _num(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def alt_primaries(cards: Iterable[Mapping[str, Any]]) -> dict[str, float]:
    """(event, market, segment, player) -> its PRIMARY line: most books quoting, ties to the line nearest the group
    median, then the lower line -- the board's own rule, over every card on the board."""
    groups: dict[str, dict[float, int]] = {}
    for c in cards:
        line = _num(c.get("line"))
        if line is None:
            continue
        books = int(_num(((c.get("quote") or {}).get("books_quoting")) or c.get("books_quoting")) or 0)
        g = groups.setdefault(_alt_group(c), {})
        g[line] = max(g.get(line, 0), books)
    out = {}
    for key, by_line in groups.items():
        lines = sorted(by_line)
        if len(lines) <= 1:
            continue
        median = lines[len(lines) // 2]
        out[key] = min(lines, key=lambda ln: (-by_line[ln], abs(ln - median), ln))
    return out


def is_alt_line(card: Mapping[str, Any], primaries: Mapping[str, float]) -> bool:
    if str(card.get("market") or "").strip().lower().endswith("_alt"):
        return True
    key = _alt_group(card)
    line = _num(card.get("line"))
    return key in primaries and line is not None and line != primaries[key]


def _card_day(card: Mapping[str, Any]) -> str:
    return str(card.get("game_date") or card.get("source_board_date") or "")[:10]


def select_picks(cards: Sequence[Mapping[str, Any]], *, sport: str, day: str) -> list[Mapping[str, Any]]:
    """The board's suggested, pregame, main-line opportunities for this sport's games on `day`, best score first."""
    primaries = alt_primaries(cards)
    chosen = [c for c in cards
              if c.get("suggested") and str(c.get("sport") or "").lower() == sport and _card_day(c) == day
              and str(c.get("market_state") or c.get("lane") or "").lower() == "pregame"
              and str(c.get("board_lane") or "opportunity") == "opportunity" and not is_alt_line(c, primaries)]
    return sorted(chosen, key=lambda c: -(_num(c.get("board_score") or c.get("score")) or 0))


_LINE_WORDS = {"h2h": "Moneyline", "h2h_3_way": "Moneyline (3-way)", "spreads": "Spread", "totals": "Total"}


def pick_bet_text(pick: Mapping[str, Any]) -> str:
    """'Over 3.5 strikeouts' / 'Milwaukee Brewers moneyline · 1st 3 innings' / 'New York Knicks -5.5'."""
    side, line, market = str(pick.get("side") or ""), pick.get("line"), str(pick.get("market") or "")
    seg = f" · {pick['segment_label']}" if pick.get("segment_label") else ""
    if pick.get("kind") == "prop":
        words = market.replace("player_", "").replace("batter_", "").replace("pitcher_", "").replace("_", " ")
        return f"{side.title()} {line:g} {words}{seg}" if isinstance(line, (int, float)) else f"{side.title()} {words}{seg}"
    if market in ("totals", "totals_alt"):
        return f"{side.title()} {line:g}{seg}" if isinstance(line, (int, float)) else f"{side.title()}{seg}"
    if market in ("spreads", "spreads_alt") and isinstance(line, (int, float)):
        return f"{pick.get('display_name')} {line:+g}{seg}"
    if side == "draw":
        return f"Draw{seg}"
    return f"{pick.get('display_name')} {_LINE_WORDS.get(market, market).lower()}{seg}"


_ASK_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")
_ASK_MODEL_LEADS = ("Our sim has", "The live re-sim has", "No sim view", "It projects", "The model", "Our model", "The sim ")
# The board's narrative restating recent form ("Across his last 5 starts, he has averaged 12.4 outs"): read as Recent
# form, so the pick's own Last 5 / Last 10 replaces it instead of repeating it (2026-10-15, the Jax outs pick).
_ASK_RECENT_NARRATIVE = re.compile(r"^(Across|Over|In) (his|her|their|the) last \d+\b")
_ASK_LABEL = re.compile(r"^(Recent form|Matchup|Vs position|History vs this team|Splits(?: \([^)]*\))?|Season metrics[^:]*)\s*:\s*(.*)$")
_ASK_RANK = re.compile(r"\((\d+)(?:st|nd|rd|th) of (\d+)\)")
# "rank 6 of 32, 1 = fewest" (vs position) and "9 of 32 (1 = stingiest)" (opponent): where a defense ranks.
_ASK_FEWEST = re.compile(r"\s*\(rank (\d+) of (\d+), 1 = (fewest|stingiest)(?:; ([^)]*))?\)")
_ASK_STINGY = re.compile(r"\b(\d+) of (\d+) \(1 = (fewest|stingiest)\)")
_ASK_RECORD = re.compile(r"\bin (\d+) of (?:the last )?(\d+)\b")
_FROM_TOP = {"fewest": "most", "stingiest": "most generous"}


def _ordinal(n: int) -> str:
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def _rank_words(n: int, of: int, word: str) -> str:
    """"the 6th fewest of 32" / "the most of 32": a rank read from whichever end it is near."""
    if n <= of / 2:
        return f"the {word} of {of}" if n == 1 else f"the {_ordinal(n)} {word} of {of}"
    back = of - n + 1
    other = _FROM_TOP.get(word, f"least {word}")
    return f"the {other} of {of}" if back == 1 else f"the {_ordinal(back)} {other} of {of}"


def _rate_tone(hits: int, games: int, *, min_games: int = 3, base: Any = None) -> str:
    """'for' / 'against' / '' -- a record that backs this side, argues against it, or says little. Against the
    market's own fair probability when it is known (a 3-way first-inning win is a ~25% bet, so 3 of 10 is par, not a
    warning), else against a coin flip."""
    if games < min_games:
        return ""
    rate = hits / games
    if isinstance(base, (int, float)) and 0 < base < 1:
        return "for" if rate - base >= 0.15 else "against" if rate - base <= -0.15 else ""
    return "for" if rate >= 0.6 else "against" if rate <= 0.4 else ""


def _defense_tone(n: int, of: int, side: str) -> str:
    """A defense ranked `n` of `of` at allowing the FEWEST: the softest third backs an over, the stingiest an under."""
    allows_most = of - n + 1
    soft, tough = allows_most <= of / 3, allows_most > 2 * of / 3
    if side in ("over", "yes"):
        return "for" if soft else "against" if tough else ""
    if side == "under":
        return "for" if tough else "against" if soft else ""
    return ""


def _ask_clean(text: str, side: str = "", base: Any = None) -> tuple[str, str]:
    """One whole clause, never cut (user 2026-10-15: "we still have bullets that end with ... instead of full
    explanations"): a card has room for a full sentence when the sentence says one thing. Ranks read as words, and
    the tone says whether the clause backs the side."""
    text = re.sub(r"\s+", " ", text).strip().rstrip(".")
    text = re.sub(r"\s*\(blended with this season\)", "", text)
    text = re.sub(r", (\d+) GP\b", r" (\1 games)", text)
    tone = ""

    def ranked(m: re.Match, lead: str = "") -> str:
        nonlocal tone
        n, of = int(m.group(1)), int(m.group(2))
        tone = _defense_tone(n, of, side)
        extra = m.group(4) if m.re is _ASK_FEWEST else None
        return lead + _rank_words(n, of, m.group(3)) + (f" ({extra})" if extra else "")

    text = _ASK_FEWEST.sub(lambda m: ranked(m, ", "), text)
    text = _ASK_STINGY.sub(ranked, text)
    if not tone and (rec := _ASK_RECORD.search(text)):
        tone = _rate_tone(int(rec.group(1)), int(rec.group(2)), base=base)
    return text, tone


def ask_points(detail: Any, *, subject: Any = None, side: Any = None, base: Any = None, limit: int = 6) -> list[dict[str, str]]:
    """Ask the Syndicate's case for a pick -- the board card's `detail`, the paragraph Ask quotes -- as labelled
    points in the style of the X.com sheets (user 2026-10-15: "we also need the 'Ask The Syndicate' data to be cleaner
    in how its represented on these picks"). The sim's own numbers are NOT points: they live in the SmartSim tiles,
    and the model is context, never the reason. Season metrics keep their two best ranks. Each point carries a
    `tone`: "for" backs the side, "against" argues against it -- a record of 0 in 3 is shown, never ticked."""
    points: list[dict[str, str]] = []
    name, side = str(subject or "").strip(), str(side or "").lower()

    def add(label: str, body: str) -> None:
        text, tone = _ask_clean(body, side, base)
        if text:
            points.append({"label": label, "text": text, "tone": tone})

    for sentence in _ASK_SENTENCE.split(str(detail or "").strip()):
        sentence = sentence.strip()
        if not sentence or sentence.startswith(_ASK_MODEL_LEADS):
            continue
        if name:
            sentence = sentence.replace(f" {name} ", " ")
        m = _ASK_LABEL.match(sentence)
        label, body = (m.group(1), m.group(2)) if m else ("", sentence)
        if not m and _ASK_RECENT_NARRATIVE.match(sentence):
            label = "Recent form"
        if label.startswith("Season metrics"):
            items = [x.strip().rstrip(".") for x in body.split(";") if x.strip()]
            ranked = sorted(items, key=lambda x: (int(r.group(1)) / int(r.group(2))) if (r := _ASK_RANK.search(x)) else 9.0)
            for x in ranked[:2]:
                points.append({"label": "Season", "text": _ask_clean(x)[0], "tone": ""})
            continue
        body = re.sub(r";\s*log since [0-9-]+", "", body).replace(" logged games", " games")
        if label.startswith("Splits"):
            label, body = "Splits", body.split(";")[0]
        if label == "History vs this team":
            label = "Vs this team"
        if label == "Matchup":
            first, _, rest = body.partition(";")
            team = re.match(r"^(.*\bin \d+ of \d+) vs (\S+)$", first.strip())
            if team:     # "under 2.5 in 5 of 11 vs BUF" is the player's record against this team
                add(f"Vs {team.group(2)}", f"{team.group(1)} meetings")
            else:
                add("Matchup", first)
            if not rest.strip():
                continue
            label, body = "Opponent", rest.strip()
        add(label, body)
    return points[:limit]


def _g(value: Any) -> str:
    return f"{float(value):g}" if isinstance(value, (int, float)) else str(value)


def _side_words(side: str, line: Any) -> str:
    return f"{side} {_g(line)}" if side in ("over", "under") and line is not None else "cleared"


def recent_points(values: Sequence[Any] | None, *, line: Any, side: Any,
                  opponents: Sequence[Any] | None = None, base: Any = None) -> list[dict[str, str]]:
    """Recency and consistency on THIS line (user 2026-10-15: "and recency/consistency"): the last five games as they
    happened, newest first, then the hit record, average and range over the last ten."""
    side = str(side or "").lower()
    line = 0.5 if line is None and side == "yes" else line
    vals = [float(v) for v in values or [] if isinstance(v, (int, float))]
    if line is None or len(vals) < 3:
        return []
    words, opps = _side_words(side, line), list(opponents or [])
    f5 = form_record(vals, line, side, 5)
    # NFL / NCAAF labels already say where ("vs SF", "@WAS"); NHL's are bare ("NJD") and get the "v".
    against = lambda o: str(o) if str(o).startswith(("vs ", "v ", "@")) else f"v {o}"
    shown = ", ".join(f"{_g(v)} {against(opps[i])}" if i < len(opps) and opps[i] else _g(v) for i, v in enumerate(vals[:5]))
    out = [{"label": "Last 5", "text": f"{words} in {f5['hits']} of {f5['games']} (newest first: {shown})",
            "tone": _rate_tone(f5["hits"], f5["games"], base=base)}]
    if len(vals) >= 8:
        last = vals[:10]
        f10 = form_record(last, line, side, len(last))
        out.append({"label": f"Last {len(last)}",
                    "text": f"{words} in {f10['hits']} of {f10['games']}, averaging {sum(last) / len(last):.1f} "
                            f"(low {_g(min(last))}, high {_g(max(last))})",
                    "tone": _rate_tone(f10["hits"], f10["games"], min_games=8, base=base)})
    return out


def vs_team_point(row: Mapping[str, Any] | None, *, line: Any, side: Any, base: Any = None) -> dict[str, str] | None:
    """The player's meetings with today's opponent on THIS line, from the sheet row (the evidence's `vs_opponent`).
    A row priced at another rung is re-read at this one from its meetings' values."""
    vs = (row or {}).get("vs_opponent") or {}
    side = str(side or "").lower()
    opp = (row or {}).get("opponent") or "this team"
    words = _side_words(side, line)
    if vs.get("same_line") and row.get("line") == line and str(row.get("side") or "").lower() == side \
            and vs.get("hits") is not None and vs.get("games"):
        hits, games = int(vs["hits"]), int(vs["games"])
    else:
        values = [x.get("value") for x in vs.get("results") or [] if isinstance(x.get("value"), (int, float))]
        if not values or line is None:
            return None
        rec = form_record(values, line, side, len(values))
        hits, games = rec["hits"], rec["games"]
    if not games:
        return None
    results = [_g(x["value"]) for x in vs.get("results") or [] if isinstance(x.get("value"), (int, float))]
    tail = f" (latest {', '.join(results)})" if results else ""
    return {"label": f"Vs {opp}", "text": f"{words} in {hits} of {games} meetings{tail}",
            "tone": _rate_tone(hits, games, min_games=VS_OPPONENT_MIN_GAMES, base=base)}


_PVP_LABEL = {"batter_vs_pitcher": "Vs pitcher", "pitcher_vs_lineup": "Vs lineup", "skater_vs_goalie": "Vs goalie",
              "goalie_vs_team": "Vs team", "scorer_vs_defenders": "Vs defenders", "receiver_vs_defenders": "Vs defenders",
              "qb_vs_defenders": "Vs defenders"}


def pvp_point(pvp: Mapping[str, Any] | None) -> dict[str, str] | None:
    """Player vs player (user 2026-10-15: "we also need to feature relevant player vs opponent stats"): the same line
    the sheet's matchup sections show, at the same minimum sample."""
    pvp = pvp or {}
    kind, ln, summary = pvp.get("kind"), pvp.get("line") or {}, str(pvp.get("summary") or "").strip()
    enough = {"batter_vs_pitcher": int(ln.get("plateAppearances") or 0) >= PVP_MIN_PA,
              "pitcher_vs_lineup": int(ln.get("plateAppearances") or 0) >= PVP_MIN_PA,
              "skater_vs_goalie": int(ln.get("games") or 0) >= PVP_MIN_GAMES,
              "goalie_vs_team": int(ln.get("games") or 0) >= PVP_MIN_GAMES,
              "scorer_vs_defenders": float(ln.get("poss") or 0) >= PVP_MIN_POSS,
              "receiver_vs_defenders": float(ln.get("plays") or 0) >= PVP_MIN_PLAYS,
              "qb_vs_defenders": bool(ln.get("plays") or ln.get("hawks"))}.get(kind, False)
    if not enough or not summary:
        return None
    if kind == "scorer_vs_defenders":          # one clause per defender: the two who guarded him most
        summary = "; ".join(summary.split("; ")[:2])
    opp = str(pvp.get("opponent") or "").strip()
    if opp and opp.split(" (")[0] not in summary:
        summary = f"vs {opp}: {summary}"
    elif "(" in opp and opp[opp.index("("):] not in summary:
        summary += f" {opp[opp.index('('):]}"          # "(likely starter)"
    return {"label": _PVP_LABEL.get(kind, "Matchup"), "text": summary, "tone": ""}


_SCORE_UNIT = {"mlb": "runs", "nhl": "goals", "soccer": "goals"}


def full_segment(segment: Any) -> str:
    seg = str(segment or "full").strip().lower()
    return "full" if seg in ("", "full", "full_game", "game") else seg


def team_form_points(pick: Mapping[str, Any], team_recent: Mapping[str, Any] | None) -> list[dict[str, str]]:
    """A game pick's recency and consistency, from each team's recent scores (date, scored, allowed; newest first):
    for a side, its record and margin and how often it covered THIS number; for a total, how often each team's games
    went over it. A SEGMENT pick reads its own interval's history (user 2026-10-15: "we need the interval data") and
    only that: `team_recent_segment` must name the pick's segment, so an inning is never read off a full-game final.
    Tones are against the market's fair probability when the pick carries it."""
    segment = full_segment(pick.get("segment"))
    if not isinstance(team_recent, Mapping) or full_segment(pick.get("team_recent_segment")) != segment:
        return []
    window = 6 if segment == "full" else 10
    games = {k: [g for g in v if isinstance(g, (list, tuple)) and len(g) >= 3
                 and isinstance(g[1], (int, float)) and isinstance(g[2], (int, float))][:window]
             for k, v in team_recent.items() if isinstance(v, list)}
    names = {"home": pick.get("home_team") or "Home", "away": pick.get("away_team") or "Away"}
    market, side, line = str(pick.get("market") or ""), str(pick.get("side") or "").lower(), pick.get("line")
    span = str(pick.get("segment_label") or segment) if segment != "full" else ""
    unit, base = _SCORE_UNIT.get(str(pick.get("sport") or "").lower(), "points"), pick.get("p_market")
    out: list[dict[str, str]] = []
    if market.startswith(("totals", "alternate_totals")) and isinstance(line, (int, float)):
        for key in ("away", "home"):
            g = games.get(key) or []
            if len(g) < 3:
                continue
            totals = [s + a for _, s, a in g]
            rec = form_record(totals, line, side, len(totals))
            subject = f"its {span}" if span else "its games"
            out.append({"label": names[key], "text": f"{subject} went {side} {_g(line)} in {rec['hits']} of the last "
                                                     f"{len(g)}, averaging {sum(totals) / len(totals):.1f} {unit}",
                        "tone": _rate_tone(rec["hits"], rec["games"], min_games=4, base=base)})
        return out
    key = side if side in ("home", "away") else next((k for k, n in names.items() if n == pick.get("display_name")), None)
    if key is None:
        return []
    three_way = "3_way" in market
    for k in (key, "away" if key == "home" else "home"):
        g = games.get(k) or []
        if len(g) < 3:
            continue
        margins = [s - a for _, s, a in g]
        wins, ties = sum(1 for m in margins if m > 0), sum(1 for m in margins if m == 0)
        average = sum(margins) / len(margins)
        if span:   # "1st 3 innings: won 4, tied 3, lost 3 of its last 10" -- an interval ends level often
            text = f"{span}: won {wins}, tied {ties}, lost {len(g) - wins - ties} of its last {len(g)}, average margin {average:+.1f}"
        else:
            text = f"{wins}-{len(g) - wins} in its last {len(g)}, average margin {average:+.1f}"
        tone = ""
        if k == key and market.startswith("spreads") and isinstance(line, (int, float)):
            covers = sum(1 for m in margins if m + line > 0)
            decided = sum(1 for m in margins if m + line != 0)
            text += f"; would have covered {_g(line) if line < 0 else '+' + _g(line)} in {covers} of {len(g)}"
            tone = _rate_tone(covers, decided, min_games=4, base=base)
        elif k == key and market.startswith("h2h"):
            # A 2-way interval line pushes on a tie, so ties leave the record; 3-way, a tie is the draw and a loss.
            tone = _rate_tone(wins, len(g) if three_way else len(g) - ties, min_games=4, base=base)
        out.append({"label": names[k], "text": text, "tone": tone})
    return out


def _player_rows(sheet_rows: Iterable[Mapping[str, Any]], player: Any) -> list[Mapping[str, Any]]:
    return [r for r in sheet_rows or [] if player and r.get("player") == player]


def starter_points(pick: Mapping[str, Any], rows: Iterable[Mapping[str, Any]]) -> list[dict[str, str]]:
    """A game pick's player-vs-opponent lines: today's starters against the other side -- MLB pitchers against the
    opposing lineup, NHL goalies against the opposing team -- from the sheet's rows for the same game."""
    out, seen = [], set()
    for r in rows or []:
        pvp = r.get("pvp") or {}
        if str(r.get("event_id")) != str(pick.get("event_id")) or pvp.get("kind") not in ("pitcher_vs_lineup", "goalie_vs_team"):
            continue
        pt = pvp_point(pvp)
        if pt and r.get("player") not in seen:
            seen.add(r.get("player"))
            out.append({"label": str(r.get("player")), "text": pt["text"], "tone": ""})
    return out[:2]


def pick_points(pick: Mapping[str, Any], *, rows: Iterable[Mapping[str, Any]] = (), limit: int = 7) -> list[dict[str, str]]:
    """Every point a pick's case shows, ordered as the X.com sheets order them: recency and consistency, the player
    against this team and against today's opponent player, the defense, then Ask the Syndicate's splits and season.
    Sources: the board card's own recent games (kept on the pick), the sheet's rows for the player (or, for a game
    pick, its starters), and the board's written case. Nothing here is cut short."""
    side, line, base = str(pick.get("side") or "").lower(), pick.get("line"), pick.get("p_market")
    rows = list(rows or [])
    if pick.get("kind") != "prop":
        # A team pick's case compares two teams ("Net rating Raptors +1.6 vs Knicks +4.0"): no name is dropped.
        asked = ask_points(pick.get("detail"), side=side, base=base, limit=12)
        return (team_form_points(pick, pick.get("team_recent")) + starter_points(pick, rows) + asked)[:limit]
    asked = ask_points(pick.get("detail"), subject=pick.get("display_name"), side=side, base=base, limit=12)
    mine = _player_rows(rows, pick.get("player_name"))
    exact = next((r for r in mine if prop_result_key(r) == prop_result_key(
        {"player": pick.get("player_name"), "market": pick.get("market"), "side": side, "line": line})), None)
    same_stat = [r for r in mine if _stat_key(r)[1] == _stat_key({"market": pick.get("market")})[1]]
    values, opponents = pick.get("recent_values"), pick.get("recent_opponents")
    if not values:   # a row's last games are the player's stat, whatever rung it prices -- re-read at this line
        values = next((v for r in ([exact] if exact else []) + same_stat
                       if (v := ((r.get("check") or {}).get("form10") or {}).get("values"))), None)
    points = recent_points(values, line=line, side=side, opponents=opponents, base=base)
    if points:   # our own record over the same games says more than Ask's one-line summary of it
        asked = [p for p in asked if p["label"] != "Recent form"]
    # The player against this team: Ask's record is on the pick's own line; the sheet row's is the fallback.
    vs = next((p for p in asked if p["label"].startswith("Vs ") and p["label"] != "Vs position"), None)
    if vs is None:
        vs = vs_team_point(exact or next((r for r in same_stat if r.get("vs_opponent")), None), line=line, side=side, base=base)
    if vs:
        points.append(vs)
    pvp = next((pt for r in same_stat + mine if (pt := pvp_point(r.get("pvp")))), None)
    if pvp:
        points.append(pvp)
        asked = [p for p in asked if not (p["label"] == "Matchup" and p["text"].lower().startswith("vs "))]
    points += [p for p in asked if p is not vs]
    return points[:limit]


def pick_record(card: Mapping[str, Any], *, promoted_at: str) -> dict[str, Any]:
    """The slim pick the sheet keeps -- frozen at the price it was PROMOTED at, like every row of a day's record."""
    quote = card.get("quote") or {}
    out = {
        "pick_id": card.get("pick_id"), "kind": card.get("kind"), "sport": card.get("sport"), "event_id": card.get("event_id"),
        "matchup": card.get("matchup"), "home_team": card.get("home_team"), "away_team": card.get("away_team"),
        "player_name": card.get("player_name"), "player_id": card.get("player_id"), "display_name": card.get("display_name"),
        "market": card.get("market"), "side": card.get("side"), "line": card.get("line"), "segment": card.get("segment") or "full",
        "segment_label": card.get("segment_label"), "price": card.get("odds"), "book": quote.get("bookmaker"),
        "books": quote.get("books_quoting"), "fair_price": card.get("fair_price"), "p_market": quote.get("fair_probability"),
        "p_model": card.get("model_probability"), "ev_pct": card.get("ev_pct"), "sim_view": card.get("sim_view"),
        "projected": card.get("projected"), "detail": card.get("detail"), "headshot_url": card.get("headshot_url"),
        "commence_time": card.get("commence_time"), "board_score": card.get("board_score"), "promoted_at": promoted_at,
    }
    # The board's own recent games, kept so the pick's form still reads after the board drops it.
    out.update({k: card.get(k) for k in PICK_RECENT_FIELDS if card.get(k)})
    if out.get("kind") != "prop" and str(out.get("market") or "").startswith(("totals", "alternate_totals")):
        # A total is no team's pick: it reads by its game ("Over 47.5" under "Georgia Southern @ Old Dominion").
        out["display_name"] = out.get("matchup") or out.get("display_name")
    out["bet"] = pick_bet_text(out)
    out["points"] = pick_points(out)
    return out


PICK_RECENT_FIELDS = ("recent_values", "recent_dates", "recent_opponents", "recent_lines", "team_recent", "team_recent_segment")


# A SYNDICATE PICK is a price edge the sim BACKS; a price edge it does not back is a PRICE PLAY (user 2026-10-15: "if i
# tout our sim and we show something like this it dvalues our work" -- a pick posted beside "SmartSim 12%"). Both stay
# on the sheet and on the record; only the label and what the graphic shows differ. The board's own `sim_view` decides
# (`layer2_board`: the sign of the priced model edge); past the board's 15-point cap it has no priced view
# ("unpriced"), and the sim's probability against the market's decides instead -- Jax over 3.5 K, 75% vs 50%, IS backed.
SIM_BACKS = frozenset({"agrees", "live_agrees"})
SIM_AGAINST = frozenset({"disagrees", "live_disagrees", "contradicts", "live_contradicts", "neutral"})
PICK_LABEL, PRICE_PLAY_LABEL = "SYNDICATE PICK", "PRICE PLAY"
# BACKING IS A MARGIN, NOT A SIGN (user 2026-10-15, "1-point floor"). The board's `sim_view` has no floor: any edge above
# zero reads `agrees`. From 10-20 NBA totals serve a market-anchored blend with 5% weight on the sim (preseason 0), so
# the served sim sits ~0.2 pts off the market and would read as backing on a view that is 95% the market's. The sim
# must clear the market by a full point. Without both probabilities the margin is unknown: PRICE PLAY, never PICK.
SIM_BACKING_FLOOR = 0.01
# PRICE PLAY UNTIL GRADED (user 2026-10-15, "Puckline picks are price until graded"). A sim market that has never been
# graded cannot back a pick. NHL spreads got their first sim number at 21:54Z 10-15, when the puckline orientation fix
# went live (lane nhl-puckline-orientation). On its first slate it sat below the fair on home -1.5 in 9 of 10 games --
# a read or a bias, which one slate cannot tell apart. Remove an entry once the sim-gap study (`model_scorecard_simgap.json`,
# cells `nhl|spreads|...`) shows it graded at >= 30 games.
UNGRADED_SIM_MARKETS = frozenset({("nhl", "spreads")})


def sim_backs_pick(pick: Mapping[str, Any]) -> bool:
    view = str(pick.get("sim_view") or "").strip().lower()
    if view in SIM_AGAINST:
        return False
    market = str(pick.get("market") or "").strip().lower()
    if (str(pick.get("sport") or "").strip().lower(), market.removeprefix("alternate_")) in UNGRADED_SIM_MARKETS:
        return False
    p_model, p_market = pick.get("p_model"), pick.get("p_market")
    if not (isinstance(p_model, (int, float)) and isinstance(p_market, (int, float))):
        return False
    # `agrees` and the no-view fallback (past the board's 15-point cap) alike: the sim's probability over the market's.
    return p_model - p_market >= SIM_BACKING_FLOOR - 1e-9


def pick_label(pick: Mapping[str, Any]) -> str:
    return PICK_LABEL if sim_backs_pick(pick) else PRICE_PLAY_LABEL


BOOK_NAMES = {"draftkings": "DraftKings", "fanduel": "FanDuel", "betmgm": "BetMGM", "prophetx": "ProphetX",
              "betrivers": "BetRivers", "kalshi": "Kalshi", "polymarket": "Polymarket", "williamhill_us": "Caesars",
              "espnbet": "ESPN BET", "fanatics": "Fanatics", "bovada": "Bovada", "betonlineag": "BetOnline", "lowvig": "LowVig",
              "mybookieag": "MyBookie", "ballybet": "Bally Bet", "hardrockbet": "Hard Rock Bet", "betparx": "betPARX",
              "pinnacle": "Pinnacle", "novig": "Novig", "betanysports": "BetAnySports", "fliff": "Fliff"}


def book_name(key: Any) -> str:
    """A book's display name ("prophetx" -> "ProphetX"); an unknown key is title-cased, never dropped."""
    k = str(key or "").strip()
    return BOOK_NAMES.get(k.lower(), k.replace("_", " ").title() if k else "")


def price_case(pick: Mapping[str, Any]) -> str:
    """A price play's reason in one sentence: the market's consensus against the price on offer."""
    def american(p: Any) -> str:
        return f"{float(p):+g}" if isinstance(p, (int, float)) else str(p or "")
    books, p_market = pick.get("books"), pick.get("p_market")
    if isinstance(books, (int, float)) and books and isinstance(p_market, (int, float)):
        consensus = f"{int(books)} books put it at {p_market:.0%}" if int(books) > 1 else f"its one book's no-vig price is {p_market:.0%}"
    else:
        consensus = "the market puts it"
    return f"The edge is the price: {consensus} (fair {american(pick.get('fair_price'))}); {book_name(pick.get('book')) or 'the best book'} " \
           f"pays {american(pick.get('price'))}"


def pick_result_key(pick: Mapping[str, Any]) -> str:
    """A pick's key in the reconciled file -- the grader's own fields WITH the segment (a pick can be a 1st-3-innings
    moneyline): props by player, game picks by event."""
    seg = str(pick.get("segment") or "full").lower()
    if seg == "full_game":
        seg = "full"
    if pick.get("player_name") or pick.get("player"):
        return "p:" + prop_result_key({"player": pick.get("player_name") or pick.get("player"), "market": pick.get("market"),
                                       "side": pick.get("side"), "line": pick.get("line")}) + "|" + seg
    return "l:" + line_result_key(pick) + "|" + seg


def void_label(reason: Any) -> str:
    """The grader's reason a bet carries no result, in words a reader can check (user 2026-10-15: "some of the
    section reconciles are missing" -- a bare dash said nothing)."""
    r = str(reason or "").lower()
    if r == "push":
        return "Push"
    if "dnp" in r or "did_not_play" in r or "void" in r:
        return "Void: did not play"
    if any(k in r for k in ("not_in_box", "absent", "not_found", "unmatched", "ambiguous")):
        return "Not in the box score"
    if any(k in r for k in ("not_final", "not_started", "not_completed", "not_yet", "pending")):
        return "Not final"
    return "Not gradeable"


SOCCER_LEAGUES = {"epl": "Premier League", "championship": "Championship", "la_liga": "LaLiga", "bundesliga": "Bundesliga",
                  "serie_a": "Serie A", "ligue_1": "Ligue 1", "eredivisie": "Eredivisie", "primeira_liga": "Primeira Liga",
                  "belgian_pro_league": "Belgian Pro League", "mls": "MLS", "ucl": "Champions League", "uel": "Europa League",
                  "uecl": "Conference League"}
_UEFA = {"ucl", "uel", "uecl"}
# A club's name differs between feeds ("1. FC Köln" vs "FC Cologne", "Le Mans FC" vs "Le Mans"): the loose key folds
# accents, drops the affixes, and maps the exonyms that measured as different (2026-10-16).
_CLUB_AFFIXES = {"fc", "cf", "afc", "sc", "ac", "as", "ss", "us", "sv", "vfb", "vfl", "tsg", "club", "cd", "ud", "rc", "sd",
                 "rcd", "fk", "sk", "bk", "if", "aik", "cfc", "calcio", "de", "the"}
_EXONYMS = {"koln": "cologne", "munchen": "munich", "monchengladbach": "gladbach", "borussiamonchengladbach": "gladbach"}


def _loose(name: Any) -> str:
    import unicodedata

    text = unicodedata.normalize("NFKD", str(name or "")).encode("ascii", "ignore").decode().lower()
    words = [w for w in re.split(r"[^a-z]+", text) if w and w not in _CLUB_AFFIXES]
    key = "".join(words)
    return _EXONYMS.get(key, key)


@lru_cache(maxsize=1)
def _soccer_league_index() -> dict[str, frozenset]:
    """normalized team name -> the leagues whose branding snapshot lists it (the files `team_logos` already reads, one
    per league: `soccer_source/<league>/source_artifacts/data/processed/team_branding/*.csv`). Read once per process."""
    from syndicate.features.shared import team_logos
    from syndicate.features.shared.team_branding import read_team_branding_snapshot

    index: dict[str, set] = {}
    for path in team_logos._branding_files("soccer"):
        league = Path(path).parents[4].name
        for row in read_team_branding_snapshot(path):
            for key in (row.display_name, row.location, row.abbreviation):
                if team_logos._norm(key):
                    index.setdefault(team_logos._norm(key), set()).add(league)
            for key in (row.display_name, row.location):
                if _loose(key):
                    index.setdefault("~" + _loose(key), set()).add(league)
    return {k: frozenset(v) for k, v in index.items()}


def _leagues_of(name: Any) -> frozenset:
    from syndicate.features.shared import team_logos

    index = _soccer_league_index()
    hit = index.get(team_logos._norm(name))
    if hit:
        return hit
    try:
        from syndicate.features.shared.team_aliases import canonical_team

        canonical = canonical_team("soccer", name)
    except Exception:  # noqa: BLE001
        canonical = None
    if canonical and index.get(team_logos._norm(canonical)):
        return index[team_logos._norm(canonical)]
    return index.get("~" + _loose(name), frozenset()) if _loose(name) else frozenset()


def soccer_league(home: Any, away: Any) -> str | None:
    """The competition two clubs meet in: the domestic league both are listed in, else the UEFA one both are in. None
    when it cannot be told -- a missing league label, never a guessed one."""
    shared = _leagues_of(home) & _leagues_of(away)
    domestic = sorted(shared - _UEFA)
    if len(domestic) == 1:
        return SOCCER_LEAGUES.get(domestic[0], domestic[0])
    uefa = sorted(shared & _UEFA)
    return SOCCER_LEAGUES.get(uefa[0], uefa[0]) if len(uefa) == 1 and not domestic else None


def fill_teams(sheet: dict[str, Any]) -> int:
    """Every prop row names the team its player is on (user 2026-10-16: soccer sheets must say "what team they are on"):
    a row with no team but a known opponent in a known game is on the OTHER side of that game. Soccer games and rows
    also get their competition. Returns how many rows got a team. In place; never overwrites a team already set."""
    games = {g.get("event_id"): g for g in sheet.get("games") or []}
    soccer = str(sheet.get("sport") or "") == "soccer"
    if soccer:
        for g in games.values():
            if not g.get("league"):
                league = soccer_league(g.get("home_team"), g.get("away_team"))
                if league:
                    g["league"] = league
    filled = 0
    norm = lambda x: re.sub(r"[^a-z0-9]", "", str(x or "").lower())
    for r in sheet.get("rows") or []:
        g = games.get(r.get("event_id"))
        if not g:
            continue
        if soccer and g.get("league") and not r.get("league"):
            r["league"] = g["league"]
        if r.get("team") or not r.get("opponent"):
            continue
        home, away, opp = g.get("home_team"), g.get("away_team"), norm(r.get("opponent"))
        side = "home" if opp and opp in (norm(away),) else "away" if opp and opp in (norm(home),) else None
        if side is None:          # the opponent is named differently (a short club name): match by containment
            side = "home" if opp and (opp in norm(away) or norm(away) in opp) else \
                "away" if opp and (opp in norm(home) or norm(home) in opp) else None
        if side:
            r["team"] = r["team_name"] = g.get(f"{side}_team")
            r["team_logo"] = r.get("team_logo") or g.get(f"{side}_logo")
            r["team_logo_src"] = r.get("team_logo_src") or g.get(f"{side}_logo_src")
            filled += 1
    return filled


def _team_keys(sport: str, name: Any) -> set[str]:
    """The ways one team's name can be written: exact, canonical (team_aliases), loose (soccer affixes / accents)."""
    keys = {re.sub(r"[^a-z0-9]", "", str(name or "").lower())}
    try:
        from syndicate.features.shared.team_aliases import canonical_team

        canonical = canonical_team(sport, name)
        if canonical:
            keys.add(re.sub(r"[^a-z0-9]", "", str(canonical).lower()))
    except Exception:  # noqa: BLE001
        pass
    if _loose(name):
        keys.add("~" + _loose(name))
    return {k for k in keys if k and k != "~"}


def align_news(sheet: dict[str, Any]) -> dict[str, int]:
    """Tie every news item to ITS team's game on THIS sheet (user 2026-10-16: "make sure its aligned with the correct
    game on the schedule"). Measured before: NFL 10-15 0 of 40 items, NBA 10-16 0 of 13, MLB 10-16 0 of 7, NHL 10-16 1 of
    40 were for a team playing on that sheet -- the section listed league-wide news. Now:
      * an item whose team has no game on the sheet is DROPPED;
      * a kept item carries the game (event_id, matchup, kickoff) and `after_start` when it was captured after the start;
      * one row per player: the NET change across the window; a flicker back to where it started is no news;
      * its counts are THIS game's props on THIS sheet (all, and the team's own).
    In place; returns {"kept", "dropped_off_sheet", "dropped_no_change"}."""
    sport = str(sheet.get("sport") or "")
    index: dict[str, list[tuple[dict[str, Any], str]]] = {}
    for g in sheet.get("games") or []:
        for side in ("home", "away"):
            for key in _team_keys(sport, g.get(f"{side}_team")):
                index.setdefault(key, []).append((g, side))
    rows = sheet.get("rows") or []
    by_player: dict[tuple[str, str], dict[str, Any]] = {}
    dropped_off = 0
    for n in sorted(sheet.get("news") or [], key=lambda x: str(x.get("captured_at") or "")):
        hits = {id(g): (g, side) for k in _team_keys(sport, n.get("team")) for g, side in index.get(k, [])}
        if not hits:
            dropped_off += 1
            continue
        captured = str(n.get("captured_at") or "")
        # A doubleheader / two games in the window: the first game that starts after the news, else the latest one.
        ordered = sorted(hits.values(), key=lambda gs: str(gs[0].get("commence_time") or ""))
        g, side = next((gs for gs in ordered if str(gs[0].get("commence_time") or "") > captured), ordered[-1])
        key = (str(n.get("player") or "").lower(), str(g.get("event_id")))
        cur = by_player.get(key)
        if cur is None:
            cur = by_player[key] = dict(n, first_status=n.get("previous_status"), changes=0)
        cur.update({k: v for k, v in n.items() if k != "previous_status"})
        cur["changes"] += 1
        cur.update({"event_id": g.get("event_id"), "matchup": g.get("matchup") or f"{g.get('away_team')} @ {g.get('home_team')}",
                    "kickoff_ct": g.get("kickoff_ct"), "commence_time": g.get("commence_time"), "side": side,
                    "team_name": g.get(f"{side}_team"),
                    "after_start": bool(g.get("commence_time")) and captured >= str(g.get("commence_time"))})
    kept, no_change = [], 0
    for n in by_player.values():
        before, after = str(n.pop("first_status") or "").lower(), str(n.get("status") or "").lower()
        if before == after:
            no_change += 1
            continue
        n["previous_status"] = n.get("previous_status") if n["changes"] == 1 else (before or None)
        game_rows = [r for r in rows if r.get("event_id") == n["event_id"]]
        team_keys = _team_keys(sport, n.get("team_name"))
        n["props_this_game"] = len(game_rows)
        n["team_props_this_game"] = sum(1 for r in game_rows if _team_keys(sport, r.get("team_name") or r.get("team")) & team_keys)
        n.pop("game_props_on_board", None)
        kept.append(n)
    kept.sort(key=lambda x: str(x.get("captured_at") or ""), reverse=True)
    sheet["news"] = kept[:60]
    return {"kept": len(kept), "dropped_off_sheet": dropped_off, "dropped_no_change": no_change}


def page_payload(sheets: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """sport -> the sheet as the page shows it, sports in board order.

    Every row is kept (a game's own sheet needs all of its props), minus the fields the page never reads. Each row
    carries its card id and whether its price check passes (only those get a pick graphic). `game_sections` holds,
    per game, the same sections the full sheet has, as indexes into `rows`."""
    from syndicate.features.shared import brand_kit
    from syndicate.features.shared import play_cards as pc

    out: dict[str, dict[str, Any]] = {}
    for sheet in sorted(sheets, key=lambda d: SPORT_ORDER.index(d["sport"]) if d.get("sport") in SPORT_ORDER else 99):
        sport, day = str(sheet.get("sport")), str(sheet.get("date"))
        # The reconciled file (scripts/reconcile_cheat_sheets.py) rides in on the sheet; each row and line takes its
        # result, and the page keeps only the summary (user 2026-10-15: "toggles between pregame sheets and
        # reconciled sheets").
        sheet = dict(sheet, rows=[dict(r) for r in sheet.get("rows") or []], games=[dict(g) for g in sheet.get("games") or []])
        posted = sheet.pop("posted", None)
        posted = posted if isinstance(posted, Mapping) else None
        if posted:
            sheet = with_posted(sheet, posted)
        posted_rows, posted_lines = posted_first(posted, "rows"), posted_first(posted, "lines")
        fill_teams(sheet)                     # every row says whose player it is (user 2026-10-16)
        if sheet.get("news") and not any(n.get("event_id") for n in sheet["news"]):
            sheet["news"] = [dict(n) for n in sheet["news"]]
            align_news(sheet)                 # an older sheet's league-wide news -> this sheet's games only
        rec = sheet.get("reconciled") if isinstance(sheet.get("reconciled"), Mapping) else None
        graded_props = (rec or {}).get("props") or {}
        graded_lines = (rec or {}).get("lines") or {}
        rows = []
        faces = brand_kit.faces_allowed(sport)          # college: logos, never faces (user 2026-10-16)
        as_posted = posted_items(posted, "rows") if rec is not None else {}
        for r in sheet.get("rows") or []:
            cid = pc.card_id(sport, day, r)
            # RECONCILED: a row that went out on a graphic shows the copy that went out (2026-10-22: Seth Jones SOG o1.5
            # was posted at -115 DraftKings; the last build showed -105 BetOnline). Same bet -- the card id is the bet.
            src = dict(r, **{k: v for k, v in as_posted[cid].items() if k not in ("event_id",)}) if cid in as_posted else r
            row = {k: v for k, v in src.items() if k not in _ROW_DROP and (faces or k not in brand_kit.FACE_FIELDS)}
            row["card_id"] = cid
            row["card_ok"] = pc.eligible(src)
            first = posted_rows.get(row["card_id"])
            if first:
                row["posted"] = first
            if rec is not None:
                price = first["price"] if first and first.get("price") is not None else (r.get("check") or {}).get("price")
                row["result"] = result_for(price, graded_props.get(prop_result_key(r)))
                why = (rec.get("void") or {}).get(prop_result_key(r))
                if row["result"] is None and why:
                    row["result_note"] = void_label(why)
            rows.append(row)
        by_game: dict[Any, list[int]] = {}
        for i, r in enumerate(rows):
            by_game.setdefault(r.get("event_id"), []).append(i)
        doc = dict(sheet)
        doc["rows"] = rows
        row_ids = [r["card_id"] for r in rows]
        row_entries = posted_entries(posted, "rows")
        doc["sections"] = pin_posted(sections(rows), row_ids, row_entries)
        if posted:
            doc["posted"] = {"posts": len(posted.get("posts") or []), "rows": len(posted_rows), "lines": len(posted_lines)}
        finals = (rec or {}).get("scores") or {}
        doc["games"] = [dict(g, props=len(by_game.get(g.get("event_id"), [])),
                             **({"final": finals[str(g.get("event_id"))]} if str(g.get("event_id")) in finals else {}))
                        for g in sheet.get("games") or []]
        lines_posted = posted_items(posted, "lines") if rec is not None else {}
        lines = []
        for line in sheet.get("game_lines") or []:
            cid = pc.card_id(sport, day, line)
            shown = dict(line)
            shown.update(lines_posted.get(cid) or {})
            shown["card_id"] = cid
            lines.append(shown)
        for line in lines:
            if line["card_id"] in posted_lines:
                line["posted"] = posted_lines[line["card_id"]]
        if rec is not None:
            for line in lines:
                first = line.get("posted")
                price = first["price"] if first and first.get("price") is not None else (line.get("check") or {}).get("price")
                line["result"] = result_for(price, graded_lines.get(line_result_key(line)))
            doc["reconciled"] = {k: rec.get(k) for k in ("reconciled_at", "source", "counts")}
        picks = [dict(p) if faces else brand_kit.without_faces(p) for p in sheet.get("picks") or []]
        if rec is not None:
            graded_picks, pick_void = rec.get("picks") or {}, rec.get("picks_void") or {}
            for p in picks:
                p["result"] = result_for(p.get("price"), graded_picks.get(pick_result_key(p)))
                if p["result"] is None and pick_result_key(p) in pick_void:
                    p["result_note"] = void_label(pick_void[pick_result_key(p)])
        doc["picks"] = picks
        tickets = with_posted_sgps(sheet.get("sgp") or [], posted)   # posted parlays stay and lead (2026-10-17)
        if rec is not None:                              # the parlays graded from this day's results (2026-10-17)
            for s, res in zip(tickets, sgp_results(tickets, rec)):
                s["result"] = res
        if tickets:
            doc["sgp"] = tickets
        # The consistency ladder carries the row's face fields for its player cell: college keeps logos only, here too.
        doc["ladders"] = [dict(lad) if faces else brand_kit.without_faces(lad) for lad in sheet.get("ladders") or []]
        lines_by_game: dict[Any, list[int]] = {}
        for i, line in enumerate(lines):
            lines_by_game.setdefault(line.get("event_id"), []).append(i)
        doc["game_lines"] = lines
        line_ids, line_entries = [line["card_id"] for line in lines], posted_entries(posted, "lines")
        line_events, row_events = [line.get("event_id") for line in lines], [r.get("event_id") for r in rows]
        doc["game_line_sections"] = pin_posted(game_line_sections(lines), line_ids, line_entries)
        doc["game_line_sections_by_game"] = {
            str(event): pin_posted({k: [idx[j] for j in ids] for k, ids in game_line_sections([lines[i] for i in idx]).items()},
                                   line_ids, line_entries, events=line_events, event=event)
            for event, idx in lines_by_game.items()}
        doc["game_sections"] = {
            str(event): pin_posted({k: [idx[j] for j in ids] for k, ids in sections([rows[i] for i in idx]).items()},
                                   row_ids, row_entries, events=row_events, event=event)
            for event, idx in by_game.items()}
        if rec is not None and posted:
            # WHAT WAS SHARED, ONLY (user 2026-10-22). The reconciled view and its exported graphics read these; the
            # pregame view keeps the full sections above. A section never posted in a scope keeps its own rows there.
            sgp_ids = list(posted_sgps(posted))
            doc["shared"] = {
                "sections": pin_posted(sections(rows), row_ids, row_entries, only=True),
                "game_sections": {
                    str(event): pin_posted({k: [idx[j] for j in ids] for k, ids in sections([rows[i] for i in idx]).items()},
                                           row_ids, row_entries, events=row_events, event=event, only=True)
                    for event, idx in by_game.items()},
                "game_line_sections": pin_posted(game_line_sections(lines), line_ids, line_entries, only=True),
                "game_line_sections_by_game": {
                    str(event): pin_posted({k: [idx[j] for j in ids] for k, ids in game_line_sections([lines[i] for i in idx]).items()},
                                           line_ids, line_entries, events=line_events, event=event, only=True)
                    for event, idx in lines_by_game.items()},
                **({"sgp_ids": sgp_ids} if sgp_ids else {}),
            }
        out[sport] = doc
    return out


def brand_tokens() -> str:
    """The brand JSON's colours and fonts as CSS variables (user 2026-10-16: the sheets mirror the play cards' brand)."""
    from syndicate.features.shared import brand_kit

    return brand_kit.css_tokens()


def render_record_page(template: str, record: Mapping[str, Any] | None, *, logo_src: str, meta: Mapping[str, Any]) -> str:
    """The season record page: the same template, with `record.json` (cheat_sheet_record) inlined as its data."""
    data = json.dumps(record, default=str).replace("</", "<\\/")
    info = json.dumps(dict(meta), default=str).replace("</", "<\\/")
    return (template.replace("/*__DATA__*/null", data, 1).replace("/*__META__*/null", info, 1)
            .replace("__LOGO_SRC__", logo_src).replace("/*__BRAND_TOKENS__*/", brand_tokens(), 1))


def render_page(template: str, sheets: Iterable[Mapping[str, Any]], *, logo_src: str,
                meta: Mapping[str, Any] | None = None) -> str:
    """The branded page with the data inlined. `</` is escaped so no string in the data can close the script."""
    data = json.dumps(page_payload(sheets), default=str).replace("</", "<\\/")
    info = json.dumps(dict(meta or {"mode": "static"}), default=str).replace("</", "<\\/")
    return (template.replace("/*__DATA__*/null", data, 1).replace("/*__META__*/null", info, 1)
            .replace("__LOGO_SRC__", logo_src).replace("/*__BRAND_TOKENS__*/", brand_tokens(), 1))
