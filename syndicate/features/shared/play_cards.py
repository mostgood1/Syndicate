"""Syndicate ROI play cards (lane `play-cards`, user 2026-10-14: "build the branded play-card generator").

A card is made ONLY from a cheat-sheet row whose PRICE CHECK passes -- the best available price beats the no-vig
market fair -- because that is the only edge Syndicate has measured to hold at the close (fair-price-v2: EV >= 2
picked on the Shin fair +1.53% at the close vs -5.45% on the old fair). The model and the player's recent form go on
the card as context and as risks, never as the reason: Syndicate's own tests found models trail the close in every
measured market and recent form mostly priced (findings_2026-10-1[34]_*). Big "model vs market" gaps are therefore
shown as a RISK, not an edge.

Selection (all line properties, nothing withheld from the board):
  * the board's own Suggested flag (EV >= +2% net of fee, two-sided fair, plausible + fresh quote), OR
    the cheat-sheet "value" verdict with EV in [MIN_EV, MAX_EV] and >= MIN_BOOKS books quoting the side;
  * EV above MAX_EV is treated as a stale or mis-paired quote, not an edge (the board caps plausibility at 5.26%);
  * at most `per_sport` cards per sport per day, highest EV first, one card per player.

Every card carries an id and a ledger record so `scripts/grade_play_cards.py` can settle it at the close and on the
result -- the public record is what makes "we post the losses" true.
"""
from __future__ import annotations

import hashlib
from typing import Any, Iterable, Mapping

MIN_EV = 2.0
MAX_EV = 10.0
MIN_BOOKS = 3
ONE_SIDED = frozenset({"book_margin_model", "one_sided", "assumed_hold"})
SPORT_LABELS = {"nfl": "NFL", "ncaaf": "NCAAF", "nhl": "NHL", "soccer": "Soccer", "nba": "NBA", "wnba": "WNBA",
                "ncaab": "NCAAB", "mlb": "MLB"}


def american_from_prob(p: float | None) -> int | None:
    if p is None or not 0 < p < 1:
        return None
    return int(round(-100 * p / (1 - p))) if p >= 0.5 else int(round(100 * (1 - p) / p))


def fmt_american(a: float | int | None) -> str:
    if a is None:
        return "-"
    a = int(round(float(a)))
    return f"+{a}" if a > 0 else str(a)


def eligible(row: Mapping[str, Any]) -> bool:
    check = row.get("check") or {}
    ev = check.get("ev_market")
    if not isinstance(ev, (int, float)) or ev > MAX_EV:
        return False
    if check.get("verdict") == "one_sided_fair" or row.get("fair_method") in ONE_SIDED:
        return False                     # no de-viggable pair: the "edge" is an assumed hold (measured 8.5 pts high)
    if row.get("suggested"):
        return True
    return check.get("verdict") == "value" and ev >= MIN_EV and int(row.get("books_quoting") or 0) >= MIN_BOOKS


def select(sheet: Mapping[str, Any], *, per_sport: int = 3) -> list[dict[str, Any]]:
    rows = [r for r in sheet.get("rows") or [] if eligible(r)]
    rows.sort(key=lambda r: (-(r["check"]["ev_market"] or 0), -int(r.get("books_quoting") or 0)))
    out, players = [], set()
    for r in rows:
        if r.get("player") in players:
            continue
        players.add(r.get("player"))
        out.append(dict(r))
        if len(out) >= per_sport:
            break
    return out


def card_id(sport: str, date: str, row: Mapping[str, Any]) -> str:
    key = f"{sport}|{date}|{row.get('event_id')}|{row.get('player')}|{row.get('market')}|{row.get('line')}|{row.get('side')}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]


def _ordinal(n: int) -> str:
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def why_and_risk(row: Mapping[str, Any], game: Mapping[str, Any] | None) -> tuple[list[str], list[str]]:
    c = row.get("check") or {}
    why, risk = [], []
    if row.get("injury"):
        risk.append(f"Listed {row['injury']}")
    if int(row.get("books_quoting") or 0) < 4:
        risk.append(f"Only {row.get('books_quoting')} books quote this side, so the fair rests on few prices")
    fair = american_from_prob(c.get("p_market"))
    why.append(f"Best price {fmt_american(c.get('price'))} beats the no-vig fair ({fmt_american(fair)}) by {c.get('ev_market'):+.1f}%")
    shop = row.get("shop") or {}
    if shop.get("gap_pp", 0) >= 1.0:
        why.append(f"{shop.get('books')} books quote it; the median book is {shop['gap_pp']:.1f} pts worse than the best")
    f10 = c.get("form10") or {}
    if f10.get("games"):
        line_word = "cleared" if (f10.get("rate") or 0) >= 0.5 else "hit"
        (why if (f10.get("rate") or 0) >= 0.5 else risk).append(
            f"{line_word.capitalize()} this line in {f10['hits']} of the last {f10['games']} games")
    dvp = row.get("dvp") or {}
    if dvp.get("nth_most") and row.get("pos"):
        stat = str(dvp.get("stat", "")).replace("_", " ")
        n = int(dvp["nth_most"])
        side_good = (row.get("side") in ("over", "yes") and n <= 10) or (row.get("side") == "under" and n >= 23)
        (why if side_good else risk).append(f"{row.get('opponent')} allow the {_ordinal(n)} most {stat} to {row['pos']}s")
    script = (game or {}).get("script") or {}
    if script.get("read"):
        why.append(f"Sim script: {script['read']}")
    p_model, p_mkt = c.get("p_model"), c.get("p_market")
    if isinstance(p_model, (int, float)) and isinstance(p_mkt, (int, float)) and abs(p_model - p_mkt) >= 0.05:
        risk.append(f"Model says {p_model:.0%} vs market {p_mkt:.0%}: big model gaps are usually model error, not edge")
    for reason in c.get("reasons") or []:
        if "model loses to the book" in reason:
            risk.append("Our model trails the book in this market (measured), so it is context only")
            break
    return why[:5], risk[:3] or ["Lines move: re-check the price before betting"]


def card_fields(row: Mapping[str, Any], *, sport: str, date: str, number: int, game: Mapping[str, Any] | None,
                label: str = "FREE PLAY") -> dict[str, Any]:
    c = row.get("check") or {}
    why, risk = why_and_risk(row, game)
    side = str(row.get("side") or "").upper()
    line = row.get("line")
    market = str(row.get("market") or "").replace("player_", "").replace("_", " ")
    bet = f"{side} {line:g} {market}" if isinstance(line, (int, float)) else f"{side} {market}"
    values = (c.get("form10") or {}).get("values") or []
    return {
        "id": card_id(sport, date, row), "label": label, "number": number, "sport": SPORT_LABELS.get(sport, sport.upper()),
        "date": date, "matchup": (game or {}).get("matchup") or "", "commence_time": (game or {}).get("commence_time"),
        "player": row.get("player"), "team": row.get("team"), "bet": bet.upper(), "price": fmt_american(c.get("price")),
        "book": c.get("book"), "books": row.get("books_quoting"), "fair": fmt_american(american_from_prob(c.get("p_market"))),
        "edge": f"{c.get('ev_market'):+.1f}%", "win_prob": f"{(c.get('p_market') or 0):.0%}",
        "model_prob": None if c.get("p_model") is None else f"{c['p_model']:.0%}",
        "form_values": list(values)[:10][::-1], "form_labels": list(row.get("form_labels") or [])[:10][::-1],
        "line": line, "side": row.get("side"), "why": why, "risk": risk,
        "pos": row.get("pos"), "headshot": row.get("headshot_url"), "team_logo": row.get("team_logo"),
        "home_logo": (game or {}).get("home_logo"), "away_logo": (game or {}).get("away_logo"),
        "kickoff_ct": (game or {}).get("kickoff_ct") or row.get("kickoff_ct"),
    }


def ledger_record(fields: Mapping[str, Any], row: Mapping[str, Any], *, sport: str, generated_at: str) -> dict[str, Any]:
    c = row.get("check") or {}
    return {"card_id": fields["id"], "generated_at": generated_at, "sport": sport, "date": fields["date"],
            "event_id": row.get("event_id"), "matchup": fields["matchup"], "commence_time": fields["commence_time"],
            "player": row.get("player"), "market": row.get("market"), "line": row.get("line"), "side": row.get("side"),
            "price": c.get("price"), "book": c.get("book"), "books_quoting": row.get("books_quoting"),
            "p_market": c.get("p_market"), "p_model": c.get("p_model"), "ev_market": c.get("ev_market"),
            "result": None, "close": None}


def pick_cards(sheets: Iterable[Mapping[str, Any]], *, per_sport: int = 3, label: str = "FREE PLAY") -> list[tuple[dict, dict, str]]:
    """(fields, row, sport) for every card across sheets, numbered per day in sport order."""
    out, n = [], 0
    for sheet in sheets:
        games = {g.get("event_id"): g for g in sheet.get("games") or []}
        for row in select(sheet, per_sport=per_sport):
            n += 1
            out.append((card_fields(row, sport=sheet["sport"], date=sheet["date"], number=n,
                                    game=games.get(row.get("event_id")), label=label), row, sheet["sport"]))
    return out
