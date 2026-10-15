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
    # Recent form is on the card's chart as context, never as a reason: streaks measured as already in the price
    # (consistency backtest 2026-10-14: 5/5 rungs hit 2.6 pts below the fair across NFL, NBA, MLB).
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
        return ('<svg viewBox="0 0 400 230"><text x="200" y="120" fill="#9db0bf" font-size="22" text-anchor="middle" '
                'font-family="Barlow">No sim view on this pick</text></svg>')
    parts = ['<svg viewBox="0 0 400 230" xmlns="http://www.w3.org/2000/svg">']
    for i, (label, v, color) in enumerate(bars):
        y = 22 + i * 68
        width = max(4.0, 300 * float(v))
        parts.append(f'<text x="0" y="{y}" fill="#9db0bf" font-size="17" font-family="Barlow" font-weight="600">{label}</text>')
        parts.append(f'<rect x="0" y="{y + 10}" width="{width:.1f}" height="30" rx="4" fill="{color}"/>')
        parts.append(f'<text x="{width + 10:.1f}" y="{y + 33}" fill="#f4f7fa" font-size="22" font-weight="800" '
                     f'font-family="Barlow">{float(v):.0%}</text>')
    parts.append("</svg>")
    return "".join(parts)


def _implied(american: Any) -> float | None:
    try:
        a = float(american)
    except (TypeError, ValueError):
        return None
    return 100 / (a + 100) if a > 0 else -a / (-a + 100)


def pick_card_fields(pick: Mapping[str, Any], *, sport: str, date: str, number: int, label: str = "SYNDICATE PICK",
                     form_values: list[float] | None = None, form_labels: list[str] | None = None) -> dict[str, Any]:
    ev, p_model, p_mkt, books = pick.get("ev_pct"), pick.get("p_model"), pick.get("p_market"), int(pick.get("books") or 0)
    why: list[str] = []
    if isinstance(ev, (int, float)):
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
    risk: list[str] = [text for tone, text in said if tone == "against"][:2]
    if str(pick.get("sim_view") or "") in ("disagrees", "contradicts"):
        risk.append("Our sim does not back this side: the edge is the price against the market")
    if isinstance(p_model, (int, float)) and isinstance(p_mkt, (int, float)) and abs(p_model - p_mkt) >= 0.10:
        risk.append(f"Sim {p_model:.0%} vs market {p_mkt:.0%}: gaps this big are usually model error, not edge")
    if books and books < 4:
        risk.append(f"Only {books} books quote it, so the fair rests on few prices")
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
        "line": pick.get("line"), "side": pick.get("side"), "why": why[:5],
        "risk": risk[:3] or ["Lines move: re-check the price before betting"],
        "headshot": pick.get("headshot_url") if is_prop else None, "team_logo": pick.get("team_logo"),
        "home_logo": pick.get("home_logo"), "away_logo": pick.get("away_logo"),
        "kickoff_ct": pick.get("kickoff_ct"), "hide_number": True,
    }
    if not fields["form_values"]:
        fields["chart_title"] = "Sim vs market"
        fields["chart_svg"] = prob_svg(p_model, p_mkt, _implied(pick.get("price")))
        fields["chart_caption"] = "the best price has to beat the no-vig market"
    return fields


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
        picks = [p for p in sheet.get("picks") or [] if p.get("pick_id")][:per_sport]
        for pick in picks:
            n += 1
            values, labels = pick_form(sheet, pick) if pick.get("kind") == "prop" else ([], [])
            out.append((pick_card_fields(pick, sport=sheet["sport"], date=sheet["date"], number=n, label="SYNDICATE PICK",
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
        return '<svg viewBox="0 0 400 230"><text x="200" y="120" fill="#9db0bf" font-size="22" text-anchor="middle" font-family="Barlow">No recent games on file</text></svg>'
    w, h, pad, base = 400, 230, 10, 190
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


def face_html(fields: Mapping[str, Any]) -> str:
    """Headshot with the team crest as a badge; the crest alone when there is no headshot; initials last."""
    e = lambda s: html.escape(str(s if s is not None else ""), quote=True)
    badge = f'<span class="badge"><img src="{e(fields["team_logo"])}" alt=""></span>' if fields.get("team_logo") else ""
    if fields.get("headshot"):
        return f'<div class="face"><img class="head" src="{e(fields["headshot"])}" alt="">{badge}</div>'
    if fields.get("team_logo"):
        return f'<div class="face"><img class="solo" src="{e(fields["team_logo"])}" alt=""></div>'
    initials = "".join(w[0] for w in str(fields.get("player") or "").split()[:2]).upper()
    return f'<div class="face"><span class="ini">{e(initials)}</span></div>'


def render_card(fields: Mapping[str, Any], logo_uri: str, template: str | None = None) -> str:
    matchup = fields.get("matchup") or ""
    away, _, home = matchup.partition(" @ ")
    e = lambda s: html.escape(str(s if s is not None else ""))
    crest = lambda src: f'<img class="crest" src="{html.escape(src, quote=True)}" alt="">' if src else ""
    meta = " · ".join(str(x) for x in (fields.get("team"), fields.get("pos")) if x)
    values, line, side = fields["form_values"], fields["line"], fields["side"]
    hits = sum(1 for v in values if v != line and ((v > line) if side in ("over", "yes") else (v < line))) \
        if values and line is not None else 0
    caption = fields.get("chart_caption") or (f"{hits} of last {len(values)} cleared {side} {line:g}" if values and line is not None else "")
    return string.Template(template if template is not None else TEMPLATE.read_text(encoding="utf-8")).safe_substitute(
        logo=logo_uri, label=e(fields["label"]), number=fields["number"], away=e(away), home=e(home),
        # "FREE PLAY #3"; a Syndicate pick is just "SYNDICATE PICK" (user 2026-10-15: "remove the number").
        tag=e(fields["label"]) if fields.get("hide_number") else f'{e(fields["label"])} #{fields["number"]}',
        sport=e(fields["sport"]), kickoff=e(fields.get("kickoff_ct") or kickoff_label(fields.get("commence_time"))),
        player=e(fields["player"]), player_meta=e(meta), face=face_html(fields),
        away_crest=crest(fields.get("away_logo")), home_crest=crest(fields.get("home_logo")),
        bet=e(fields["bet"]), price=e(fields["price"]), book=e(fields["book"]), books=e(fields["books"]),
        fair=e(fields["fair"]), edge=e(fields["edge"]), win_prob=e(fields["win_prob"]),
        model_note=e(f" · model {fields['model_prob']}" if fields.get("model_prob") else ""),
        chart=fields.get("chart_svg") or chart_svg(values, fields["form_labels"], line, side),
        chart_title=e(fields.get("chart_title") or "Last games"),
        chart_caption=e(caption), why="".join(f"<li>{e(w)}</li>" for w in fields["why"]),
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
