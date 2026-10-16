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
import html
import json
import re
import string
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

TEMPLATE = Path(__file__).resolve().parents[2] / "templates" / "play_cards" / "card.html"

MIN_EV = 2.0
# The public record starts here (user 2026-10-14: "today [is] our beta with tomorrow as the first official day where I
# will start posting them on X"). Cards dated earlier are BETA: kept on the ledger, never counted in the record.
OFFICIAL_START = "2026-10-15"
MAX_EV = 10.0
MIN_BOOKS = 3
ONE_SIDED = frozenset({"book_margin_model", "one_sided", "assumed_hold"})
SPORT_LABELS = {"nfl": "NFL", "ncaaf": "NCAAF", "nhl": "NHL", "soccer": "Soccer", "nba": "NBA", "wnba": "WNBA",
                "ncaab": "NCAAB", "mlb": "MLB"}

# The badge holds the sport's ball (user 2026-10-15: "the syndicate logo changed the ball being held based on sport").
# Baseball / football / basketball / soccer are cut from the X.com posts the user supplied; the puck was drawn onto the
# plain badge (user 2026-10-15: "add a hockey puck version of the logo"), since no post carried one.
BRAND_DIR = Path(__file__).resolve().parents[2] / "static" / "brand"
SPORT_BALL = {"mlb": "baseball", "nfl": "football", "ncaaf": "football", "nba": "basketball", "wnba": "basketball",
              "ncaab": "basketball", "soccer": "soccer", "nhl": "puck"}


def badge_name(sport: Any) -> str:
    """The brand badge file for a sport: `syndicate_roi_badge_<ball>.webp`, or the plain badge."""
    ball = SPORT_BALL.get(str(sport or "").strip().lower())
    return f"syndicate_roi_badge_{ball}.webp" if ball else "syndicate_roi_badge.webp"


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


def attach_heroes(sheet: dict[str, Any]) -> int:
    """Name each card's hero on the sheet (brand spec 2026-10-16: the athlete is the focus). A prop: the player's own
    cutout at its largest free size. A side: the backed team's star, the player the books offer the most markets on. A
    total: both teams' stars. Only rows a card can be made of, so the generator fetches a handful of images, not all."""
    from syndicate.features.shared import brand_kit

    sport, rows, named = sheet.get("sport"), sheet.get("rows") or [], 0
    for r in rows:
        if r.get("headshot_url") and eligible(r):
            r["hero_url"] = brand_kit.hero_url(sport, r["headshot_url"])
            named += 1
    for p in sheet.get("picks") or []:
        side = str(p.get("side") or "").lower()
        if p.get("kind") == "prop":
            if p.get("headshot_url"):
                p["hero_url"] = brand_kit.hero_url(sport, p["headshot_url"])
                named += 1
        elif side in ("home", "away"):
            star = brand_kit.team_star(rows, p.get(f"{side}_team"))
            if star:
                p["hero_url"], p["hero_name"] = brand_kit.hero_url(sport, star["headshot_url"]), star.get("player")
                named += 1
        elif str(p.get("market") or "").lower().startswith(("totals", "alternate_totals")):
            for k in ("away", "home"):
                star = brand_kit.team_star(rows, p.get(f"{k}_team"))
                if star:
                    p[f"hero_{k}_url"] = brand_kit.hero_url(sport, star["headshot_url"])
                    named += 1
    return named


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


def _brand_range(key: str, default: tuple[int, int]) -> tuple[int, int]:
    try:
        from syndicate.features.shared import brand_kit

        lo, hi = brand_kit.load()[key]
        return int(lo), int(hi)
    except Exception:  # noqa: BLE001 -- the card still renders without the brand file
        return default


def why_points(row: Mapping[str, Any], game: Mapping[str, Any] | None) -> tuple[list[tuple[str, str]], list[str]]:
    """(why as (tone, text), risk). Tone "for" backs the bet; "ctx" is context. The brand spec asks for 4-6 reasons
    (user 2026-10-16); they come from the row's own evidence and are never padded."""
    from syndicate.features.shared import cheat_sheets as cs

    c = row.get("check") or {}
    why: list[tuple[str, str]] = []
    risk: list[str] = []
    if row.get("injury"):
        risk.append(f"Listed {row['injury']}")
    if int(row.get("books_quoting") or 0) < 4:
        risk.append(f"Only {row.get('books_quoting')} books quote this side, so the fair rests on few prices")
    fair = american_from_prob(c.get("p_market"))
    why.append(("for", f"Best price {fmt_american(c.get('price'))} beats the no-vig fair ({fmt_american(fair)}) by {c.get('ev_market'):+.1f}%"))
    shop = row.get("shop") or {}
    if shop.get("gap_pp", 0) >= 1.0:
        why.append(("for", f"{shop.get('books')} books quote it; the median book is {shop['gap_pp']:.1f} pts worse than the best"))
    dvp = row.get("dvp") or {}
    if dvp.get("nth_most") and row.get("pos"):
        stat = str(dvp.get("stat", "")).replace("_", " ")
        n = int(dvp["nth_most"])
        side_good = (row.get("side") in ("over", "yes") and n <= 10) or (row.get("side") == "under" and n >= 23)
        text = f"{row.get('opponent')} allow the {_ordinal(n)} most {stat} to {row['pos']}s"
        why.append(("for", text)) if side_good else risk.append(text)
    script = (game or {}).get("script") or {}
    if script.get("read"):
        why.append(("ctx", f"Sim script: {script['read']}"))
    p_model, p_mkt = c.get("p_model"), c.get("p_market")
    if isinstance(p_model, (int, float)) and isinstance(p_mkt, (int, float)) and abs(p_model - p_mkt) >= 0.05:
        risk.append(f"Model says {p_model:.0%} vs market {p_mkt:.0%}: big model gaps are usually model error, not edge")
    for reason in c.get("reasons") or []:
        if "model loses to the book" in reason:
            risk.append("Our model trails the book in this market (measured), so it is context only")
            break
    # Form and history are CONTEXT, never the reason: streaks measured as already in the price (consistency backtest
    # 2026-10-14: 5/5 rungs hit 2.6 pts below the fair across NFL, NBA, MLB). One that argues against the side is a risk.
    line, side = row.get("line"), row.get("side")
    values = (c.get("form10") or {}).get("values") or []
    context = cs.recent_points(values, line=line, side=side, opponents=row.get("form_labels"), base=p_mkt)[-1:]
    context += [p for p in (cs.vs_team_point(row, line=line, side=side, base=p_mkt), cs.pvp_point(row.get("pvp"))) if p]
    for pt in context:
        text = f"{pt['label']}: {pt['text']}" if pt.get("label") else pt["text"]
        why.append(("ctx", text)) if pt.get("tone") != "against" else risk.append(text)
    return why, risk


def market_risks(fields: Mapping[str, Any]) -> list[str]:
    """What can beat this kind of bet even when the price is right -- true of every bet of its kind, so the case
    against is never empty (brand spec: 3-4 risks). The specific risks come first; these only top the list up."""
    kind, market = fields.get("kind") or "prop", str(fields.get("market") or "").lower()
    side, line = str(fields.get("side") or "").lower(), fields.get("line")
    p = _implied(str(fields.get("price") or "").replace("+", ""))
    out: list[str] = []
    if kind == "prop":
        out.append("One game, one stat line: a short night or a role change sinks an over" if side in ("over", "yes")
                   else "One big play is enough to beat an under" if side == "under"
                   else "Single-game props swing on role and minutes")
    elif market.startswith(("totals", "alternate_totals")):
        out.append("Pace and late scoring swing a total" if side == "over" else "One late score or overtime breaks an under")
    elif market.startswith(("spreads", "alternate_spreads")):
        if isinstance(line, (int, float)) and line <= -7:
            out.append("Big favourite: a late backdoor cover is live")
        elif isinstance(line, (int, float)) and line > 0:
            out.append("The cover needs the game close late")
        else:
            out.append("A spread can turn on the last possession")
    elif market.startswith("h2h"):
        out.append("An underdog loses more often than it wins: the edge is the price, not a likely win"
                   if p is not None and p < 0.5 else "A short price leaves little room if it goes wrong")
    if fields.get("segment_label") and str(fields.get("segment_label")).lower() not in ("full game", "full"):
        out.append(f"A {fields['segment_label']} bet is a small slice of the game: more variance")
    out.append("Variance: a +EV bet still loses often; the edge pays over many bets")
    out.append("Lines move: re-check the price before betting")
    return out


def finish_case(fields: dict[str, Any]) -> dict[str, Any]:
    """Cap the reasons at the brand maximum and top the case against up to the brand minimum with `market_risks`."""
    _lo, why_max = _brand_range("why_bullets", (4, 6))
    risk_min, risk_max = _brand_range("against_bullets", (3, 4))
    fields["why"] = list(fields.get("why") or [])[:why_max]
    fields["why_tones"] = list(fields.get("why_tones") or [])[:why_max]
    risk = [r for r in fields.get("risk") or [] if r]
    for extra in market_risks(fields):
        if len(risk) >= risk_min:
            break
        if extra not in risk and not ("re-check" in extra and any("re-check" in r for r in risk)):
            risk.append(extra)
    fields["risk"] = risk[:risk_max]
    return fields


def why_and_risk(row: Mapping[str, Any], game: Mapping[str, Any] | None) -> tuple[list[str], list[str]]:
    why, risk = why_points(row, game)
    _lo, why_max = _brand_range("why_bullets", (4, 6))
    return [text for _tone, text in why][:why_max], risk[:4] or ["Lines move: re-check the price before betting"]


def card_fields(row: Mapping[str, Any], *, sport: str, date: str, number: int, game: Mapping[str, Any] | None,
                label: str = "FREE PLAY") -> dict[str, Any]:
    c = row.get("check") or {}
    points, risk = why_points(row, game)
    side = str(row.get("side") or "").upper()
    line = row.get("line")
    market = str(row.get("market") or "").replace("player_", "").replace("_", " ")
    bet = f"{side} {line:g} {market}" if isinstance(line, (int, float)) else f"{side} {market}"
    values = (c.get("form10") or {}).get("values") or []
    matchup = (game or {}).get("matchup") or row.get("matchup") or ""
    away, _, home = matchup.partition(" @ ")
    return finish_case({
        "id": card_id(sport, date, row), "label": label, "number": number, "sport": SPORT_LABELS.get(sport, sport.upper()),
        "date": date, "matchup": (game or {}).get("matchup") or "", "commence_time": (game or {}).get("commence_time"),
        "player": row.get("player"), "team": row.get("team"), "bet": bet.upper(), "price": fmt_american(c.get("price")),
        "book": c.get("book"), "books": row.get("books_quoting"), "fair": fmt_american(american_from_prob(c.get("p_market"))),
        "edge": f"{c.get('ev_market'):+.1f}%", "win_prob": f"{(c.get('p_market') or 0):.0%}",
        "model_prob": None if c.get("p_model") is None else f"{c['p_model']:.0%}",
        "form_values": list(values)[:10][::-1], "form_labels": list(row.get("form_labels") or [])[:10][::-1],
        "line": line, "side": row.get("side"), "why": [t for _tone, t in points], "why_tones": [tone for tone, _t in points],
        "risk": risk, "pos": row.get("pos"), "headshot": row.get("headshot_url"), "team_logo": row.get("team_logo"),
        "hero": row.get("hero_src") or row.get("hero_url"),
        "home_logo": (game or {}).get("home_logo"), "away_logo": (game or {}).get("away_logo"),
        "kickoff_ct": (game or {}).get("kickoff_ct") or row.get("kickoff_ct"),
        "kind": "prop", "market": row.get("market"),
        **team_colors(sport, team=(row.get("team_name"), row.get("team")), away=away, home=home),
    })


def team_colors(sport: str, *, team: Iterable[Any] = (), away: Any = None, home: Any = None) -> dict[str, Any]:
    """The card's team accents (brand spec: "team colours as subtle accents only"); None where a team is unknown."""
    try:
        from syndicate.features.shared import brand_kit

        return {"team_color": brand_kit.team_color(sport, *team), "away_color": brand_kit.team_color(sport, away),
                "home_color": brand_kit.team_color(sport, home)}
    except Exception:  # noqa: BLE001 -- an accent is decoration
        return {"team_color": None, "away_color": None, "home_color": None}


# --------------------------------------------------------------------------------------------------------------------
# Syndicate picks (the Layer 2 board's suggested opps, promoted on the cheat sheet -- user 2026-10-15: "add the
# suggested opps as a picks section with pick graphics"). A pick can be a game line or a segment, so its card draws the
# sim against the market where a prop draws its last games, and its reasons come from the board's own written case.
# --------------------------------------------------------------------------------------------------------------------
def prob_svg(model: float | None, market: float | None, implied: float | None) -> str:
    """Three bars: our sim, the no-vig market, and what the price implies -- the card's case at a glance."""
    bars = [(label, v, color) for label, v, color in (("Our sim", model, "#8cff2e"), ("No-vig market", market, "#eef3f7"),
                                                       ("Price implies", implied, "#ff6b57")) if isinstance(v, (int, float))]
    if not bars:
        return ('<svg viewBox="0 0 400 300"><text x="200" y="150" fill="#9db0bf" font-size="24" text-anchor="middle" '
                'font-family="Barlow">No sim view on this pick</text></svg>')
    parts = ['<svg viewBox="0 0 400 300" xmlns="http://www.w3.org/2000/svg">']
    for i, (label, v, color) in enumerate(bars):
        y = 26 + i * 96
        width = max(4.0, 300 * float(v))
        parts.append(f'<text x="0" y="{y}" fill="#b9c8d4" font-size="22" font-family="Barlow" font-weight="700">{label}</text>')
        parts.append(f'<rect x="0" y="{y + 12}" width="{width:.1f}" height="44" rx="6" fill="{color}"/>')
        parts.append(f'<text x="{width + 10:.1f}" y="{y + 45}" fill="#f4f7fa" font-size="30" font-weight="800" '
                     f'font-family="Barlow">{float(v):.0%}</text>')
    parts.append("</svg>")
    return "".join(parts)


def _implied(american: Any) -> float | None:
    try:
        a = float(american)
    except (TypeError, ValueError):
        return None
    return 100 / (a + 100) if a > 0 else -a / (-a + 100)


def pick_card_fields(pick: Mapping[str, Any], *, sport: str, date: str, number: int, label: str | None = None,
                     form_values: list[float] | None = None, form_labels: list[str] | None = None) -> dict[str, Any]:
    from syndicate.features.shared import cheat_sheets as cs

    ev, p_model, p_mkt, books = pick.get("ev_pct"), pick.get("p_model"), pick.get("p_market"), int(pick.get("books") or 0)
    # SYNDICATE PICK when the sim backs the price edge, PRICE PLAY when it does not (user 2026-10-15: "if i tout our
    # sim and we show something like this it dvalues our work"). A price play's graphic never shows the sim's number.
    label = label or pick.get("label") or cs.pick_label(pick)
    play = label == cs.PRICE_PLAY_LABEL
    why: list[str] = []
    if play:
        why.append(cs.price_case(pick) + (f", {ev:+.1f}%" if isinstance(ev, (int, float)) else ""))
    elif isinstance(ev, (int, float)):
        why.append(f"Best price {fmt_american(pick.get('price'))} beats the no-vig fair "
                   f"({fmt_american(pick.get('fair_price'))}) by {ev:+.1f}%")
    # The board's case minus its model sentences: the model is context or risk on a card, never the reason (see
    # `why_and_risk`); the chart already sets the sim against the market. Form, matchup, splits and history stay.
    points = pick.get("points")
    if points is None:                          # a pick stored before its case was broken into points
        from syndicate.features.shared.cheat_sheets import pick_points

        points = pick_points(pick)
    # Ask the Syndicate's case as the X.com sheets show it: labelled checks, each a whole statement (user 2026-10-15:
    # "bullets that end with ... instead of full explanations"). A point that argues AGAINST the side -- 0 in 3 vs
    # this team -- is a risk, never a tick.
    said = [(pt.get("tone"), f"{pt['label']}: {pt['text']}" if pt.get("label") else pt["text"]) for pt in points]
    backing = sorted((x for x in said if x[0] != "against"), key=lambda x: x[0] != "for")   # what backs it, first
    why += [text for _tone, text in backing][:4]
    why_tones = ["for"] + [tone or "" for tone, _text in backing][:4]
    risk: list[str] = [text for tone, text in said if tone == "against"][:2]
    if play:
        risk.append("A price edge closes fast: re-check the price before betting")
    elif isinstance(p_model, (int, float)) and isinstance(p_mkt, (int, float)) and abs(p_model - p_mkt) >= 0.10:
        risk.append(f"Sim and market are far apart ({p_model:.0%} vs {p_mkt:.0%}): we size on the price, not the gap")
    if books and books < 4:
        risk.append("Only one book quotes it, so the fair rests on one price" if books == 1
                    else f"Only {books} books quote it, so the fair rests on few prices")
    is_prop = pick.get("kind") == "prop"
    fields = {
        "id": pick.get("pick_id"), "label": label, "number": number, "sport": SPORT_LABELS.get(sport, sport.upper()),
        "date": date, "matchup": pick.get("matchup") or "", "commence_time": pick.get("commence_time"),
        "player": pick.get("display_name"), "team": pick.get("team") if is_prop else (pick.get("segment_label") or "Full game"),
        "pos": pick.get("pos") if is_prop else None, "bet": str(pick.get("bet") or "").upper(),
        "price": fmt_american(pick.get("price")), "book": pick.get("book"), "books": books or None,
        "fair": fmt_american(pick.get("fair_price")), "edge": f"{ev:+.1f}%" if isinstance(ev, (int, float)) else "",
        "win_prob": f"{p_mkt:.0%}" if isinstance(p_mkt, (int, float)) else "",
        "model_prob": None if p_model is None else f"{p_model:.0%}",
        "form_values": list(form_values or [])[:10], "form_labels": list(form_labels or [])[:10],
        "line": pick.get("line"), "side": pick.get("side"), "why": why[:5], "why_tones": why_tones[:5],
        "risk": risk[:3] or ["Lines move: re-check the price before betting"],
        "headshot": pick.get("headshot_url") if is_prop else None, "team_logo": pick.get("team_logo"),
        "home_logo": pick.get("home_logo"), "away_logo": pick.get("away_logo"),
        "kickoff_ct": pick.get("kickoff_ct"), "hide_number": True,
        "kind": pick.get("kind"), "market": pick.get("market"), "segment_label": pick.get("segment_label"),
        "projected": pick.get("projected"), "price_play": play,
    }
    if play:     # the third tile is the market's consensus, never the sim
        fields.update({"tile3_k": "Books", "tile3_v": str(books or "–"), "tile3_s": f"consensus {fields['win_prob']}"})
        fields["model_prob"] = None
    if not fields["form_values"]:
        fields["chart_title"] = "Market vs price" if play else "Sim vs market"
        fields["chart_svg"] = prob_svg(None if play else p_model, p_mkt, _implied(pick.get("price")))
        fields["chart_caption"] = "the best price has to beat the no-vig market"
    # The hero (brand spec 2026-10-16): a prop's own player; a side's team star; a total's two stars. The generator
    # picks the star and caches the cutout (`hero_src`); `hero_url` is the remote copy for a PNG render.
    side = str(pick.get("side") or "").lower()
    backed = pick.get(f"{side}_team") if side in ("home", "away") else None
    fields.update({"hero": pick.get("hero_src") or pick.get("hero_url"),
                   "hero_away": pick.get("hero_away_src") or pick.get("hero_away_url"),
                   "hero_home": pick.get("hero_home_src") or pick.get("hero_home_url"),
                   "hero_name": pick.get("hero_name"), "team_logo": fields["team_logo"] or (
                       pick.get(f"{side}_logo") if side in ("home", "away") else None),
                   **team_colors(sport, team=(pick.get("team"), backed) if is_prop else (backed,),
                                 away=pick.get("away_team"), home=pick.get("home_team"))})
    return finish_case(fields)


def ledger_record(fields: Mapping[str, Any], row: Mapping[str, Any], *, sport: str, generated_at: str,
                  source: str = "auto") -> dict[str, Any]:
    if row.get("pick_id"):                      # a Syndicate pick: its own price, and the segment it is graded on
        return {"card_id": fields["id"], "generated_at": generated_at, "source": source, "sport": sport, "date": fields["date"],
                "event_id": row.get("event_id"), "matchup": fields["matchup"], "commence_time": fields["commence_time"],
                "player": row.get("player_name"), "kind": row.get("kind"), "pick_id": row.get("pick_id"),
                "market": row.get("market"), "line": row.get("line"), "side": row.get("side"),
                "segment": row.get("segment") or "full", "price": row.get("price"), "book": row.get("book"),
                "books_quoting": row.get("books"), "p_market": row.get("p_market"), "p_model": row.get("p_model"),
                "ev_market": row.get("ev_pct"), "beta": str(fields["date"]) < OFFICIAL_START, "result": None, "close": None}
    c = row.get("check") or {}
    return {"card_id": fields["id"], "generated_at": generated_at, "source": source, "sport": sport, "date": fields["date"],
            "event_id": row.get("event_id"), "matchup": fields["matchup"], "commence_time": fields["commence_time"],
            "player": row.get("player"), "market": row.get("market"), "line": row.get("line"), "side": row.get("side"),
            "price": c.get("price"), "book": c.get("book"), "books_quoting": row.get("books_quoting"),
            "p_market": c.get("p_market"), "p_model": c.get("p_model"), "ev_market": c.get("ev_market"),
            "beta": str(fields["date"]) < OFFICIAL_START, "result": None, "close": None}


def pick_form(sheet: Mapping[str, Any], pick: Mapping[str, Any]) -> tuple[list[float], list[str]]:
    """A prop pick's last games (oldest left, like a row's card): the board card's own recent games, kept on the pick,
    else the sheet row for the same bet."""
    recent = [v for v in pick.get("recent_values") or [] if isinstance(v, (int, float))][:10]
    if recent:
        labels = [str(x) for x in (pick.get("recent_opponents") or [])][:10] or \
            [str(d)[5:10] for d in (pick.get("recent_dates") or [])][:10]
        return recent[::-1], labels[::-1] if len(labels) == len(recent) else []
    for r in sheet.get("rows") or []:
        if (r.get("player") == pick.get("player_name") and str(r.get("market")) == str(pick.get("market"))
                and r.get("side") == pick.get("side") and r.get("line") == pick.get("line")):
            values = ((r.get("check") or {}).get("form10") or {}).get("values") or []
            return list(values)[:10][::-1], list(r.get("form_labels") or [])[:10][::-1]
    return [], []


def pick_cards(sheets: Iterable[Mapping[str, Any]], *, per_sport: int = 3, label: str = "FREE PLAY") -> list[tuple[dict, dict, str]]:
    """(fields, item, sport) for every card across sheets, numbered per day in sport order. The SYNDICATE PICKS come
    first -- the board's suggested opps (2026-10-15) -- and a sheet without any falls back to its value rows."""
    out, n = [], 0
    for sheet in sheets:
        from syndicate.features.shared.cheat_sheets import pick_label

        # The picks the sim backs first, then the price plays (user 2026-10-15).
        picks = sorted((p for p in sheet.get("picks") or [] if p.get("pick_id")),
                       key=lambda p: (p.get("label") or pick_label(p)) != "SYNDICATE PICK")[:per_sport]
        for pick in picks:
            n += 1
            values, labels = pick_form(sheet, pick) if pick.get("kind") == "prop" else ([], [])
            out.append((pick_card_fields(pick, sport=sheet["sport"], date=sheet["date"], number=n,
                                         form_values=values, form_labels=labels), pick, sheet["sport"]))
        if picks:
            continue
        games = {g.get("event_id"): g for g in sheet.get("games") or []}
        for row in select(sheet, per_sport=per_sport):
            n += 1
            out.append((card_fields(row, sport=sheet["sport"], date=sheet["date"], number=n,
                                    game=games.get(row.get("event_id")), label=label), row, sheet["sport"]))
    return out


# --------------------------------------------------------------------------------------------------------------------
# Rendering (the card HTML) and the ledger. Used by scripts/build_play_cards.py (PNG on the Windows host) and by the
# app's /cheatsheets card page (PNG in the browser), so both draw the same card.
# --------------------------------------------------------------------------------------------------------------------


def central(moment: datetime) -> datetime:
    """US Central with DST where tzdata exists (the fleet); CDT otherwise. Nothing user-facing is shown in UTC."""
    try:
        from zoneinfo import ZoneInfo

        return moment.astimezone(ZoneInfo("America/Chicago"))
    except Exception:  # noqa: BLE001
        return moment.astimezone(timezone(timedelta(hours=-5)))


def kickoff_label(commence: Any) -> str:
    try:
        t = central(datetime.fromisoformat(str(commence).replace("Z", "+00:00")))
    except (TypeError, ValueError):
        return ""
    return f"{t:%a %b} {t.day} · {t.hour % 12 or 12}:{t:%M} {'AM' if t.hour < 12 else 'PM'} CT"


def chart_svg(values: list[float], labels: list[str], line: float | None, side: str | None) -> str:
    """Last-N bars (oldest left), the line dashed; green = cleared the bet's side, red = missed."""
    if not values or line is None:
        return '<svg viewBox="0 0 400 300"><text x="200" y="150" fill="#9db0bf" font-size="24" text-anchor="middle" font-family="Barlow">No recent games on file</text></svg>'
    w, h, pad, base = 400, 300, 10, 258
    top = max(max(values), float(line)) * 1.15 or 1.0
    n = len(values)
    bw = (w - 2 * pad) / n
    y = lambda v: base - (v / top) * (base - 20)
    parts = [f'<svg viewBox="0 0 {w} {h}" xmlns="http://www.w3.org/2000/svg">']
    for i, v in enumerate(values):
        hit = v != line and ((v > line) if side in ("over", "yes") else (v < line))
        x = pad + i * bw + bw * 0.14
        color = "#8cff2e" if hit else "#ff5a4a"
        parts.append(f'<rect x="{x:.1f}" y="{y(v):.1f}" width="{bw * 0.72:.1f}" height="{base - y(v):.1f}" rx="3" fill="{color}"/>')
        parts.append(f'<text x="{x + bw * 0.36:.1f}" y="{y(v) - 6:.1f}" fill="#f4f7fa" font-size="17" font-weight="700" text-anchor="middle" font-family="Barlow">{v:g}</text>')
        lab = html.escape(str(labels[i] if i < len(labels) else "").split("-")[-1].split(" ")[-1])[:6]
        parts.append(f'<text x="{x + bw * 0.36:.1f}" y="{base + 22}" fill="#9db0bf" font-size="13" text-anchor="middle" font-family="Barlow">{lab}</text>')
    parts.append(f'<line x1="{pad}" x2="{w - pad}" y1="{y(float(line)):.1f}" y2="{y(float(line)):.1f}" stroke="#1fa8ff" stroke-width="3" stroke-dasharray="8 6"/>')
    parts.append(f'<text x="{w - pad}" y="{y(float(line)) - 8:.1f}" fill="#1fa8ff" font-size="17" font-weight="700" text-anchor="end" font-family="Barlow">line {float(line):g}</text>')
    parts.append("</svg>")
    return "".join(parts)


def _is_total(fields: Mapping[str, Any]) -> bool:
    return (fields.get("kind") or "prop") != "prop" and str(fields.get("market") or "").lower().startswith(("totals", "alternate_totals"))


_ENERGY = ('<svg class="energy" viewBox="0 0 760 668" preserveAspectRatio="none" xmlns="http://www.w3.org/2000/svg">'
           '<g filter="url(#soft)"><polyline class="bolt" points="700,40 664,118 690,124 640,214"/>'
           '<polyline class="bolt-g" points="250,520 214,578 236,584 196,650"/></g>'
           '<polyline class="bolt-core" points="700,40 664,118 690,124 640,214"/>'
           '<path class="bolt" d="M120 470 Q 380 300 720 380" opacity=".35"/></svg>')


def stage(fields: Mapping[str, Any]) -> dict[str, str]:
    """The HERO (brand spec 2026-10-16: "the athlete is the focus", 40-60% of a prop card, 35-50% of a side or a total):
    the cutout as tall as the space from the banner to the dashboard, over the team-colour glow, an energy ring and the
    crest. A side without a star's face shows its crest large; a total shows both teams equally."""
    e = lambda s: html.escape(str(s if s is not None else ""), quote=True)
    logo, face = fields.get("team_logo"), fields.get("hero") or fields.get("headshot")
    tight = bool(face) and str(fields.get("sport") or "").upper() in ("MLB", "NHL")   # square, head-tight cutouts
    glow = '<div class="team-glow"></div><div class="ring"></div>' + _ENERGY
    color = fields.get("team_color")
    style = f"--tc: {color};" if color and re.fullmatch(r"#[0-9A-Fa-f]{6}", str(color)) else ""
    if _is_total(fields):
        faces = [(k, fields.get(f"hero_{k}")) for k in ("away", "home") if fields.get(f"hero_{k}")]
        if len(faces) == 2:
            crests = "".join(f'<img class="crest-duo bg {k}" src="{e(fields[f"{k}_logo"])}" alt="">'
                             for k in ("away", "home") if fields.get(f"{k}_logo"))
            body = "".join(f'<img class="head {k}" src="{e(src)}" alt="">' for k, src in faces)
            return {"hero": glow + crests + body + '<span class="vs">VS</span>', "stage_class": "duo", "stage_style": style}
        if fields.get("away_logo") or fields.get("home_logo"):
            crests = "".join(f'<img class="crest-duo {k}" src="{e(fields[f"{k}_logo"])}" alt="">'
                             for k in ("away", "home") if fields.get(f"{k}_logo"))
            return {"hero": glow + crests + '<span class="vs">VS</span>', "stage_class": "duo", "stage_style": style}
    if face:
        crest = f'<img class="crestbg" src="{e(logo)}" alt="">' if logo else ""
        return {"hero": glow + crest + f'<img class="head" src="{e(face)}" alt="">',
                "stage_class": "tight" if tight else "solo", "stage_style": style}
    if logo:
        return {"hero": glow + f'<img class="crest-big" src="{e(logo)}" alt="">', "stage_class": "solo", "stage_style": style}
    initials = "".join(w[0] for w in str(fields.get("player") or "").split()[:2]).upper()
    return {"hero": glow + f'<span class="ini">{e(initials)}</span>', "stage_class": "solo", "stage_style": style}


def hero_html(fields: Mapping[str, Any]) -> str:
    """The hero's markup alone (kept for callers that only need the picture)."""
    return stage(fields)["hero"]


def mini_html(fields: Mapping[str, Any]) -> str:
    """Under the odds plate: a prop's last games against the line; a backed pick's sim against the market. A PRICE
    PLAY shows neither -- its graphic never carries the sim's number (user 2026-10-15)."""
    values, line, side = fields.get("form_values") or [], fields.get("line"), fields.get("side")
    if values and isinstance(line, (int, float)):
        top = max(max(values), float(line)) * 1.12 or 1.0
        n, w, h = len(values), 300, 58
        bw = w / n
        y = lambda v: h - (v / top) * (h - 4)
        parts = [f'<svg class="spark" viewBox="0 0 {w} {h}" xmlns="http://www.w3.org/2000/svg">']
        hits = 0
        for i, v in enumerate(values):
            hit = v != line and ((v > line) if side in ("over", "yes") else (v < line))
            hits += hit
            parts.append(f'<rect class="{"hit" if hit else "miss"}" x="{i * bw + bw * .14:.1f}" y="{y(v):.1f}" '
                         f'width="{bw * .72:.1f}" height="{h - y(v):.1f}" rx="2"/>')
        parts.append(f'<line class="ln" x1="0" x2="{w}" y1="{y(float(line)):.1f}" y2="{y(float(line)):.1f}"/></svg>')
        label = f'<div class="lbl">Last {n}<b>{hits} of {n} {html.escape(str(side or ""))} {float(line):g}</b></div>'
        return f'<div class="mini">{label}{"".join(parts)}</div>'
    if fields.get("price_play") or not fields.get("model_prob") or not fields.get("win_prob"):
        return ""
    try:
        sim, mkt = float(str(fields["model_prob"]).rstrip("%")) / 100, float(str(fields["win_prob"]).rstrip("%")) / 100
    except ValueError:
        return ""
    bars = (f'<svg class="spark" viewBox="0 0 300 58" xmlns="http://www.w3.org/2000/svg">'
            f'<rect class="bar-sim" x="0" y="4" width="{max(4, 220 * sim):.1f}" height="20" rx="3"/>'
            f'<text x="{max(4, 220 * sim) + 8:.1f}" y="20">SIM {sim:.0%}</text>'
            f'<rect class="bar-mkt" x="0" y="34" width="{max(4, 220 * mkt):.1f}" height="20" rx="3"/>'
            f'<text x="{max(4, 220 * mkt) + 8:.1f}" y="50">MKT {mkt:.0%}</text></svg>')
    return f'<div class="mini"><div class="lbl">SmartSim<b>vs no-vig</b></div>{bars}</div>'


def card_text(fields: Mapping[str, Any]) -> dict[str, str]:
    """Headline / subline / bet line / the bottom strip's bet, by what the pick is. A TOTAL is no team's bet, so its
    headline is the bet itself ("OVER 47.5") -- the game's two names in the headline crushed the card (2026-10-15)."""
    bet = str(fields.get("bet") or "")
    name = str(fields.get("player") or "")
    if (fields.get("kind") or "prop") == "prop":
        meta = " · ".join(str(x) for x in (fields.get("team"), fields.get("pos")) if x)
        return {"headline": name, "subline": meta, "betline": bet, "strip": f"{name} {bet}".strip()}
    seg = str(fields.get("segment_label") or "Full game")
    if _is_total(fields):
        return {"headline": bet, "subline": f"Game total · {seg}", "betline": "", "strip": f"{bet} · {seg}"}
    rest = bet[len(name):].strip(" ·") if name and bet.upper().startswith(name.upper()) else bet
    if str(fields.get("market") or "").lower().startswith("spreads") and "SPREAD" not in rest.upper():
        rest = f"{rest} spread"
    return {"headline": name, "subline": "", "betline": rest, "strip": f"{name} {rest}".strip()}


def render_card(fields: Mapping[str, Any], logo_uri: str, template: str | None = None) -> str:
    from syndicate.features.shared.cheat_sheets import book_name

    matchup = fields.get("matchup") or ""
    away, _, home = matchup.partition(" @ ")
    e = lambda s: html.escape(str(s if s is not None else ""))
    crest = lambda src: f'<img class="crest" src="{html.escape(src, quote=True)}" alt="">' if src else ""
    text = card_text(fields)
    values, line, side = fields["form_values"], fields["line"], fields["side"]
    hits = sum(1 for v in values if v != line and ((v > line) if side in ("over", "yes") else (v < line))) \
        if values and line is not None else 0
    caption = fields.get("chart_caption") or (f"{hits} of last {len(values)} cleared {side} {line:g}" if values and line is not None else "")
    proj = fields.get("projected")
    sim_note = (f"proj {float(proj):.1f} vs {float(line):g}" if isinstance(proj, (int, float)) and isinstance(line, (int, float))
                else "sim win rate")
    try:
        from syndicate.features.shared import brand_kit

        brand, brand_css = brand_kit.load(), brand_kit.css_tokens()
    except Exception:  # noqa: BLE001 -- a card without the brand file still renders, in the browser's defaults
        brand, brand_css = {}, ""
    panels, tagline, footer = brand.get("panels") or {}, list(brand.get("tagline") or ["", "", ""]), brand.get("footer") or {}
    hexed = lambda c: c if c and re.fullmatch(r"#[0-9A-Fa-f]{6}", str(c)) else None
    books = fields.get("books")
    tile3 = (e(fields.get("tile3_k") or "SmartSim"), e(fields.get("tile3_v") or fields.get("model_prob") or "–"),
             e(fields.get("tile3_s") or sim_note))
    hero = stage(fields)
    return string.Template(template if template is not None else TEMPLATE.read_text(encoding="utf-8")).safe_substitute(
        brand_css=brand_css, wordmark=e(brand.get("wordmark") or "Syndicate ROI"),
        logo=logo_uri, label=e(fields["label"]), number=fields["number"], away=e(away), home=e(home),
        # "FREE PLAY #3"; a Syndicate pick is just "SYNDICATE PICK" (user 2026-10-15: "remove the number").
        tag=e(fields["label"]) if fields.get("hide_number") else f'{e(fields["label"])} #{fields["number"]}',
        sport=e(fields["sport"]), kickoff=e(fields.get("kickoff_ct") or kickoff_label(fields.get("commence_time"))),
        player=e(fields["player"]), headline=e(text["headline"]), subline=e(text["subline"]), betline=e(text["betline"]),
        strip_bet=e(text["strip"]), sep=e(brand.get("ticker_separator") or "|"),
        hero=hero["hero"], stage_class=hero["stage_class"], stage_style=e(hero["stage_style"]), mini=mini_html(fields),
        away_style=f"--tc: {hexed(fields.get('away_color'))};" if hexed(fields.get("away_color")) else "",
        home_style=f"--tc: {hexed(fields.get('home_color'))};" if hexed(fields.get("home_color")) else "",
        away_crest=crest(fields.get("away_logo")), home_crest=crest(fields.get("home_logo")),
        bet=e(fields["bet"]), price=e(fields["price"]), book=e(book_name(fields["book"])), books=e(books),
        bks="bk" if books == 1 else "bks",
        fair=e(fields["fair"]), edge=e(fields["edge"]), win_prob=e(fields["win_prob"]),
        tile3_k=tile3[0], tile3_v=tile3[1], tile3_s=tile3[2],
        # The METRIC DASHBOARD's four cards (brand spec): best price, the fair, the sim (or the books on a price play), edge.
        t1_k="Best price", t1_v=e(fields["price"]),
        t1_s=f'{e(book_name(fields["book"]))} · {e(books)} {"bk" if books == 1 else "bks"}' if books else e(book_name(fields["book"])),
        t2_k="Fair line", t2_v=e(fields["fair"]), t2_s=f"no-vig {e(fields['win_prob'])}",
        t3_k=tile3[0], t3_v=tile3[1], t3_s=tile3[2],
        t4_k="Edge", t4_v=e(fields["edge"]), t4_s="vs the fair price",
        outlook_title=e(panels.get("market") or "Market outlook") if fields.get("price_play")
        else e(panels.get("sim") or "SmartSim outlook"),
        why_title=e(panels.get("why") or "Why we like it"), against_title=e(panels.get("against") or "Case against"),
        tag_1=e(tagline[0] if tagline else ""), tag_2=e(tagline[1] if len(tagline) > 1 else ""),
        tag_3=e(tagline[2] if len(tagline) > 2 else ""), handle=e(brand.get("handle") or "@SyndicateROI"),
        disclaimer=e(footer.get("disclaimer") or ""), age=e(footer.get("age") or ""),
        chart=fields.get("chart_svg") or chart_svg(values, fields["form_labels"], line, side),
        chart_title=e(fields.get("chart_title") or "Last games"),
        chart_caption=e(caption),
        why="".join(f'<li class="{"for" if (tones[i] if i < len(tones) else "for") == "for" else "ctx"}">{e(w)}</li>'
                    for tones in [fields.get("why_tones") or []] for i, w in enumerate(fields["why"])),
        risk="".join(f"<li>{e(r)}</li>" for r in fields["risk"]))


def ledger_path(data_root: Path | str) -> Path:
    return Path(data_root) / "playcards" / "ledger.jsonl"


def read_ledger(path: Path) -> list[dict[str, Any]]:
    out = []
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    return out


def append_ledger(path: Path, records: Iterable[Mapping[str, Any]]) -> int:
    """Append each record whose card_id is not on the ledger yet; returns how many were added."""
    seen = {r.get("card_id") for r in read_ledger(path)}
    new = [dict(r) for r in records if r["card_id"] not in seen]
    if new:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            for r in new:
                fh.write(json.dumps(r, default=str) + "\n")
    return len(new)


def card_number(ledger: Iterable[Mapping[str, Any]], date: str, card: str) -> int:
    """The card's number for its day: its place on the ledger, or the next one if it is not there yet."""
    ids = [r.get("card_id") for r in ledger if r.get("date") == date]
    return ids.index(card) + 1 if card in ids else len(ids) + 1
