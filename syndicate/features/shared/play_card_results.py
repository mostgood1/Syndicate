"""Result cards: what happened to a graded play card, and what we got wrong (lane `result-cards`).

User 2026-10-16: reconciled days should have graphics that show the reconciliation -- won or lost, the actual result,
"what REALLY happened in the game that caused the win or loss ie what did we get wrong - this is something that can
help optimize our sim engine". So a result card answers two different questions, and keeps them apart:

  * WAS IT A GOOD BET? The closing line, not the result. Our price against the market's closing no-vig fair is the
    honest skill number (it does not wait for luck); crossed with the result it gives four verdicts -- right side at
    the right price, good bet / bad result, cashed against the close, wrong side.
  * WHAT DID THE SIM GET WRONG? Only where the sim was the reason (a SYNDICATE PICK) and it projects in the line's own
    units (an over/under: a player's stat, a game total). A PRICE PLAY is never judged on the sim -- it was not the
    reason (user 2026-10-15). With box-score usage (`usage`: minutes, ice time, batters faced, plate appearances ...)
    a miss splits into OPPORTUNITY (less or more time than usual) and EFFICIENCY (normal time, a different rate) --
    the split the engine can act on.

Everything here reads what the grader and the reconcile already wrote; nothing is fetched. `postmortem()` is the
engine-ledger record, one per graded card.
"""
from __future__ import annotations

import html
import re
from typing import Any, Iterable, Mapping

OPPORTUNITY_BAND = 0.15          # usage within +-15% of the player's usual is "normal time"

QUADRANTS = {
    ("win", True): ("right_side", "good", "Right side at the right price: it cashed and our price beat the closing line"),
    ("loss", True): ("good_bet_bad_result", "good", "Good bet, bad result: our price still beat the closing line, and bets "
                                                     "like that pay over a season"),
    ("win", False): ("cashed_against_close", "warn", "It cashed, but the market closed against our price: a result we don't "
                                                      "count as skill"),
    ("loss", False): ("wrong_side", "bad", "Wrong side: the market moved against us before the start, and it lost"),
}


def _num(v: Any) -> float | None:
    try:
        return None if v is None or v == "" else float(v)
    except (TypeError, ValueError):
        return None


def _g(v: Any) -> str:
    f = _num(v)
    if f is None:
        return "-"
    return f"{f:g}" if f == int(f) or abs(f) >= 100 else f"{f:.1f}"


def outcome(result: Mapping[str, Any] | None) -> str | None:
    y = _num((result or {}).get("y"))
    return None if y is None else "win" if y == 1 else "loss" if y == 0 else "push"


def is_over_under(item: Mapping[str, Any]) -> bool:
    return str(item.get("side") or "").lower() in ("over", "under")


def is_total(item: Mapping[str, Any]) -> bool:
    return (item.get("kind") or "prop") != "prop" and str(item.get("market") or "").lower().startswith(("totals", "alternate_totals"))


def full_game(item: Mapping[str, Any]) -> bool:
    return str(item.get("segment") or "full").lower() in ("full", "full_game", "game", "")


def actual_value(item: Mapping[str, Any], entry: Mapping[str, Any] | None, score: Mapping[str, Any] | None) -> float | None:
    """The number the bet settled on: the grader's value for a prop, the final's combined score for a full-game total,
    the backed side's final margin for a full-game side. A segment bet's own number is not in the final score."""
    v = _num((entry or {}).get("v"))
    if v is not None:
        return v
    if not score or not full_game(item):
        return None
    home, away = _num(score.get("home")), _num(score.get("away"))
    if home is None or away is None:
        return None
    if is_total(item):
        return home + away
    side = str(item.get("side") or "").lower()
    return (home - away) if side == "home" else (away - home) if side == "away" else None


def close_verdict(close: Mapping[str, Any] | None) -> bool | None:
    """True when our price was still +EV at the market's closing no-vig fair; None without a two-sided close."""
    ev = _num((close or {}).get("ev_close_pct"))
    return None if ev is None else ev > 0


def usage_split(usage: Mapping[str, Any] | None, side: str, res: str | None) -> dict[str, Any] | None:
    """Opportunity vs efficiency from box-score usage {metric, unit, actual, usual, games}: usage outside the band
    explains the result through TIME; inside it, through RATE."""
    if not usage:
        return None
    actual, usual = _num(usage.get("actual")), _num(usage.get("usual"))
    if actual is None or not usual:
        return None
    ratio = actual / usual
    more = ratio > 1 + OPPORTUNITY_BAND
    less = ratio < 1 - OPPORTUNITY_BAND
    kind = "opportunity" if (more or less) else "efficiency"
    metric, unit, per = str(usage.get("metric") or "usage"), str(usage.get("unit") or ""), str(usage.get("per") or "chance")
    # The FACT (what happened) and the READING (the verdict) are separate lines; the card shows each once.
    fact = (f"{metric}: {_g(actual)}{unit} against a usual {_g(usual)}{unit} over the last {usage.get('games') or '?'} "
            f"{usage.get('of') or 'games'} ({ratio - 1:+.0%})")
    if kind == "opportunity":
        helped = (side == "under") == less        # less time helps an under, more time helps an over
        text = (f"Opportunity: {('fewer' if usage.get('count') else 'less') if less else 'more'} {metric.lower()} than usual "
                f"{'carried' if helped else 'sank'} it, not the rate")
    else:
        text = f"Efficiency: a normal {metric.lower()}, so the output per {per} decided it"
    return {"kind": kind, "ratio": round(ratio, 3), "fact": fact, "text": text}


def sim_judgement(item: Mapping[str, Any], label: str, actual: float | None) -> dict[str, Any] | None:
    """The sim's error, only where the sim was the reason (a SYNDICATE PICK) and projects in the line's own units. With
    the sim's spread (`projected_sd`, NFL publishes it) a miss is also placed against the sim's own range."""
    if label != "SYNDICATE PICK":
        return None
    if is_over_under(item) and _num(item.get("projected")) is None:     # no mean on file: judge the side it backed
        p_model, line = _num(item.get("p_model")), _num(item.get("line"))
        side = str(item.get("side") or "").lower()
        if p_model is None or actual is None or line is None or actual == line:
            return None
        right = (actual > line) == (side == "over")
        return {"projected": None, "actual": actual, "error": None, "right_side": right, "z": None,
                "text": f"SmartSim had the {side} at {p_model:.0%}: it {'came in' if right else 'did not come in'}"}
    if not is_over_under(item):            # a side: the sim backed it at p_model; was the side right?
        p_model, p_market = _num(item.get("p_model")), _num(item.get("p_market"))
        if p_model is None or actual is None:
            return None
        line = _num(item.get("line"))
        right = actual > (-line if line is not None else 0.0)
        return {"projected": None, "actual": actual, "error": None, "right_side": right,
                "text": (f"SmartSim backed this side at {p_model:.0%}"
                         f"{f' (the market said {p_market:.0%})' if p_market is not None else ''}: the side "
                         f"{'came in' if right else 'did not come in'}")}
    projected, line = _num(item.get("projected")), _num(item.get("line"))
    if projected is None or actual is None or line is None:
        return None
    error = actual - projected
    right_side = (projected > line) == (actual > line) and actual != line
    sd = _num(item.get("projected_sd"))
    z = round(error / sd, 2) if sd else None
    spread = ("" if z is None else f" ({'inside' if abs(z) <= 1 else 'outside'} the sim's own range, {abs(z):.1f} sd)")
    return {"projected": projected, "actual": actual, "error": round(error, 2), "right_side": right_side, "z": z,
            "text": (f"SmartSim projected {_g(projected)}; the actual was {_g(actual)} -- the sim was "
                     f"{'right' if right_side else 'wrong'} about the side of {_g(line)} and {abs(error):.1f} "
                     f"{'high' if error < 0 else 'low'}{spread}")}


def facts(item: Mapping[str, Any], *, sport: str, actual: float | None, score: Mapping[str, Any] | None,
          close: Mapping[str, Any] | None, price: Any, home: str, away: str) -> list[str]:
    """WHAT HAPPENED: the final, the number the bet settled on, the close -- each a whole statement."""
    from syndicate.features.shared.play_cards import fmt_american

    out: list[str] = []
    h, a = _num((score or {}).get("home")), _num((score or {}).get("away"))
    if h is not None and a is not None:
        out.append(f"Final: {away} {_g(a)}, {home} {_g(h)}")
    line, side = _num(item.get("line")), str(item.get("side") or "").lower()
    stat = str(item.get("market") or "").replace("player_", "").replace("_", " ")
    if not full_game(item):
        out.append(f"The bet was on the {item.get('segment_label') or item.get('segment')}: graded on that part of the game")
    elif (item.get("kind") or "prop") == "prop" and actual is not None:
        out.append(f"{item.get('player_name') or item.get('player') or item.get('display_name')} finished with {_g(actual)} "
                   f"{stat} (the line was {_g(line)})")
    elif is_total(item) and actual is not None:
        out.append(f"The teams combined for {_g(actual)} (the line was {_g(line)})")
    elif side in ("home", "away") and actual is not None:
        team = home if side == "home" else away
        if str(item.get("market") or "").lower().startswith(("spreads", "alternate_spreads")) and line is not None:
            out.append(f"{team} {'won' if actual > 0 else 'lost' if actual < 0 else 'tied'} by {_g(abs(actual))}; "
                       f"{_g(line)} needed {'a win by more than ' + _g(-line) if line < 0 else 'a loss by less than ' + _g(line)}")
        else:
            out.append(f"{team} {'won' if actual > 0 else 'lost' if actual < 0 else 'tied'} by {_g(abs(actual))}")
    p_close, ev_close = _num((close or {}).get("p_close")), _num((close or {}).get("ev_close_pct"))
    if p_close is not None and ev_close is not None:
        best = (close or {}).get("best_close_price")
        out.append(f"At the close the market's no-vig price was {p_close:.0%}{f' (best {fmt_american(best)})' if best is not None else ''}: "
                   f"our {fmt_american(price)} was {ev_close:+.1f}% EV")
    else:
        out.append("No book quoted both sides of this exact line at the close, so the close can't judge it")
    return out


def verdict(res: str | None, close: Mapping[str, Any] | None, label: str, sim: Mapping[str, Any] | None,
            usage: Mapping[str, Any] | None, *, one_sided: bool = False) -> dict[str, Any]:
    """THE VERDICT: the close x result quadrant, then what the sim got wrong (picks only), then time vs rate.

    `one_sided`: the market is quoted on one side only (soccer player props: 0 of 5,948 book/line groups two-sided on
    10-23), so no two-sided close CAN exist -- `no_two_sided_close`, kept apart from `no_close` (a close we failed to
    find)."""
    beat = close_verdict(close)
    if res in ("win", "loss") and beat is not None:
        key, tone, head = QUADRANTS[(res, beat)]
    elif res == "push":
        key, tone, head = "push", "neutral", "A push: stake returned"
    else:
        key, tone, head = ("no_two_sided_close" if one_sided else "no_close"), "neutral", \
            ("It cashed" if res == "win" else "It lost" if res == "loss" else "Pending") + \
            ": with no two-sided close, the result is all we can judge"
    lines = [head]
    if sim:
        lines.append(sim["text"])
    elif label != "SYNDICATE PICK":
        lines.append("A price play: the price was the reason, so the sim isn't judged on it")
    if usage:
        lines.append(usage["text"])
    return {"key": key, "tone": tone, "lines": lines}


def tile_tone(good: bool | None) -> str:
    return "" if good is None or good else "bad"


def outcome_strip(*, line: float | None, actual: float | None, projected: float | None, side: str, won: bool | None) -> str:
    """One number line: what the bet needed (dashed), our sim's projection (a picks-only diamond), the actual (the dot,
    coloured by the graded result). A side's number is its margin, so what it needed is -spread (0 on a moneyline)."""
    target = (-line if line is not None else 0.0) if side in ("home", "away") else line
    if target is None or actual is None:
        return ""
    pts = [v for v in (target, actual, projected) if v is not None]
    lo, hi = min(pts), max(pts)
    pad = max(1.0, (hi - lo) * 0.25)
    lo, hi = lo - pad, hi + pad
    w, x = 300.0, (lambda v: 8 + (w - 16) * (v - lo) / (hi - lo))
    parts = [f'<svg class="spark tall" viewBox="0 -14 {int(w)} 74" xmlns="http://www.w3.org/2000/svg">',
             f'<line class="track" x1="8" x2="{w - 8:.0f}" y1="30" y2="30"/>']
    parts.append(f'<line class="ln" x1="{x(target):.1f}" x2="{x(target):.1f}" y1="10" y2="50"/>'
                 f'<text x="{x(target):.1f}" y="2" text-anchor="middle">{"NEEDED" if side in ("home", "away") else "LINE"} {_g(target)}</text>')
    if projected is not None:
        px = x(projected)
        parts.append(f'<path class="sim" d="M{px:.1f} 20 l8 10 -8 10 -8 -10z"/>')
    parts.append(f'<circle class="{"hit" if won else "miss" if won is False else "track"}" cx="{x(actual):.1f}" cy="30" r="9"/>'
                 f'<text x="{x(actual):.1f}" y="57" text-anchor="middle">{_g(actual)}</text></svg>')
    key = '<b>LINE · <span class="k-sim">SIM</span> · ACTUAL</b>' if projected is not None else "<b>LINE · ACTUAL</b>"
    return f'<div class="mini"><div class="lbl">How it landed{key}</div>{"".join(parts)}</div>'


def result_overrides(fields: Mapping[str, Any], item: Mapping[str, Any], card: Mapping[str, Any], *,
                     entry: Mapping[str, Any] | None, score: Mapping[str, Any] | None,
                     usage: Mapping[str, Any] | None = None) -> tuple[dict[str, str], dict[str, Any]]:
    """(template overrides, the classification). `fields` is the card's own fields (play_cards.card_fields /
    pick_card_fields), `item` the sheet row or pick, `card` the ledger record with `result` and `close`."""
    from syndicate.features.shared.play_cards import fmt_american

    e = lambda s: html.escape(str(s if s is not None else ""))
    label = str(fields.get("label") or "")
    res = outcome(card.get("result"))
    close = card.get("close") or {}
    actual = actual_value(item, entry, score)
    side = str(item.get("side") or "").lower()
    matchup = str(fields.get("matchup") or "")
    away, _, home = matchup.partition(" @ ")
    sim = sim_judgement(item, label, actual)
    use = usage_split(usage, side, res)
    said = facts(item, sport=str(fields.get("sport") or ""), actual=actual, score=score, close=close,
                 price=card.get("price"), home=home or "Home", away=away or "Away")
    if use:
        said.insert(min(2, len(said)), use["fact"])
    v = verdict(res, close, label, sim, use)
    units = _num((card.get("result") or {}).get("units"))
    word = {"win": "WIN", "loss": "LOSS", "push": "PUSH"}.get(res or "", "PENDING")
    stamp = (f'<div class="stamp {res or "pending"}">{word}'
             f'{f"<small>{units:+.2f}u</small>" if units is not None else ""}</div>')
    h, a = _num((score or {}).get("home")), _num((score or {}).get("away"))
    ev_close = _num(close.get("ev_close_pct"))
    over_under = is_over_under(item)
    projected = _num(item.get("projected")) if (label == "SYNDICATE PICK" and over_under) else None
    # The card's OWN numbers (the ledger stamped them when the card was made); a sheet row keeps moving after that.
    edge = _num(card.get("ev_market"))
    p_model = _num(card.get("p_model")) if card.get("p_model") is not None else _num(item.get("p_model"))
    t3 = (("SmartSim", _g(projected), "projected") if projected is not None else
          ("Sim win %", f"{p_model:.0%}", "sim backed it") if label == "SYNDICATE PICK" and p_model is not None else
          ("Edge at card", f"{edge:+.1f}%" if edge is not None else str(fields.get("edge") or "-"), "vs the fair price"))
    tone_panel = {"good": ("green why", "", "for"), "warn": ("blue facts", "blue", "fact"),
                  "neutral": ("blue facts", "blue", "fact"), "bad": ("red against", "red", "")}[v["tone"]]
    actual_text = (_g(actual) if actual is not None else "-")
    if side in ("home", "away") and actual is not None:
        actual_text = f"{actual:+g}"
    ticker_tail = f'<i>|</i><b class="{res or "pending"}">{word}{f" {units:+.2f}u" if units is not None else ""}</b>'
    over = {
        "stamp": stamp, "price": e(fmt_american(card.get("price"))),
        "kickoff": e(f"FINAL · {_g(a)}–{_g(h)}" if h is not None and a is not None else "FINAL"),
        "mini": outcome_strip(line=_num(item.get("line")), actual=actual, side=side, projected=projected,
                              won=None if res in (None, "push") else res == "win"),
        "outlook_title": "The reconciliation",
        "t1_k": "Result", "t1_v": e(word), "t1_s": e(f"{units:+.2f}u at {fmt_american(card.get('price'))}" if units is not None else "not settled"),
        "t1_cls": tile_tone(None if res is None else res != "loss"),
        "t2_k": "Actual", "t2_v": e(actual_text), "t2_s": e(f"line {_g(item.get('line'))}" if item.get("line") is not None else "final margin"),
        "t2_cls": tile_tone(None if res is None else res != "loss"),
        "t3_k": e(t3[0]), "t3_v": e(t3[1]), "t3_s": e(t3[2]),
        "t3_cls": tile_tone(None if not sim else sim["right_side"]),
        "t4_k": "Close", "t4_v": e(f"{ev_close:+.1f}%" if ev_close is not None else "n/a"),
        "t4_s": "our EV at the close" if ev_close is not None else "no two-sided close",
        "t4_cls": tile_tone(close_verdict(close)),
        "why_title": "What happened", "why_panel_cls": "blue facts", "why_tab_cls": "blue",
        "why": "".join(f'<li class="fact">{e(x)}</li>' for x in said[:5]),
        "against_title": "The verdict", "against_panel_cls": tone_panel[0], "against_tab_cls": tone_panel[1],
        "risk": "".join(f'<li class="{tone_panel[2]}">{e(x)}</li>' for x in v["lines"][:4]),
        "ticker_tag": "Final", "ticker_tail": ticker_tail,
    }
    classification = {"outcome": res, "verdict": v["key"], "tone": v["tone"], "beat_close": close_verdict(close),
                      "ev_close_pct": ev_close, "clv_pp": _num(close.get("clv_pp")), "actual": actual,
                      "projected": _num(item.get("projected")) if over_under else None,
                      "sim": sim, "usage": dict(usage) if usage else None, "usage_kind": (use or {}).get("kind")}
    return over, classification


def classify(item: Mapping[str, Any], card: Mapping[str, Any], *, label: str, entry: Mapping[str, Any] | None,
             score: Mapping[str, Any] | None, usage: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """The engine reading of one graded bet: the verdict, the sim's error (where it was the reason), time vs rate."""
    res = outcome(card.get("result"))
    close = card.get("close") or {}
    actual = actual_value(item, entry, score)
    sim = sim_judgement(item, label, actual)
    use = usage_split(usage, str(item.get("side") or "").lower(), res)
    from syndicate.features.shared.cheat_sheets import ONE_SIDED_FAIR_METHODS

    one_sided = (str(item.get("fair_method") or "") in ONE_SIDED_FAIR_METHODS
                 or (item.get("check") or {}).get("verdict") == "one_sided_fair")
    v = verdict(res, close, label, sim, use, one_sided=one_sided)
    over_under = is_over_under(item)
    return {"outcome": res, "verdict": v["key"], "tone": v["tone"], "beat_close": close_verdict(close),
            "ev_close_pct": _num(close.get("ev_close_pct")), "clv_pp": _num(close.get("clv_pp")), "actual": actual,
            "projected": _num(item.get("projected")) if over_under else None,
            "projected_sd": _num(item.get("projected_sd")) if over_under else None,
            "sim": sim, "usage": dict(usage) if usage else None, "usage_kind": (use or {}).get("kind")}


def _units(price: Any, y: float | None) -> float | None:
    p = _num(price)
    if y is None or p is None:
        return None
    return round((p / 100 if p > 0 else 100 / -p), 3) if y == 1 else (-1.0 if y == 0 else 0.0)


def sheet_postmortem(sheet: Mapping[str, Any], reconciled: Mapping[str, Any] | None, *, usage: Any = None,
                     closes: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
    """The engine ledger for one sheet: one record per GRADED FEATURED bet -- the Syndicate picks, every featured row
    section and the game-line value section (user 2026-10-16: "what did we get wrong ... can help optimize our sim
    engine"). `usage(card, item)` adds box-score usage; `closes[card_id]` the closing fair. Read-only of its inputs."""
    from syndicate.features.shared import cheat_sheets as cs
    from syndicate.features.shared import play_cards as pc
    from syndicate.features.shared.cheat_sheet_record import FEATURED

    if not reconciled:
        return []
    sport, day = str(sheet.get("sport")), str(sheet.get("date"))
    featured = {k for k, _ in FEATURED}
    scores = reconciled.get("scores") or {}
    out: list[dict[str, Any]] = []

    def add(item: Mapping[str, Any], card: dict[str, Any], *, label: str, entry: Mapping[str, Any] | None, sections: list[str]):
        if outcome(card.get("result")) is None:
            return
        found = usage(card, item) if callable(usage) and (item.get("kind") or "prop") == "prop" else None
        c = classify(item, card, label=label, entry=entry, score=scores.get(str(item.get("event_id"))), usage=found)
        out.append({**postmortem(card, dict(item, label=label), c), "source": "sheet", "sections": sections})

    in_sections: dict[int, list[str]] = {}
    for key, ids in (sheet.get("sections") or {}).items():
        if key in featured and key != "lines_value":
            for i in ids:
                in_sections.setdefault(int(i), []).append(key)
    rows = sheet.get("rows") or []
    for i, keys in sorted(in_sections.items()):
        if i >= len(rows):
            continue
        row = rows[i]
        entry = (reconciled.get("props") or {}).get(cs.prop_result_key(row))
        chk = row.get("check") or {}
        y = _num((entry or {}).get("y"))
        cid = pc.card_id(sport, day, row)
        card = {"card_id": cid, "sport": sport, "date": day, "event_id": row.get("event_id"), "kind": "prop",
                "market": row.get("market"), "line": row.get("line"), "side": row.get("side"), "price": chk.get("price"),
                "book": chk.get("book"), "books_quoting": row.get("books_quoting"), "p_market": chk.get("p_market"),
                "p_model": chk.get("p_model"), "ev_market": chk.get("ev_market"), "player": row.get("player"),
                "result": None if y is None else {"y": y, "units": _units(chk.get("price"), y)},
                "close": (closes or {}).get(cid) or {}}
        add(dict(row, p_model=chk.get("p_model"), p_market=chk.get("p_market")), card,
            label=pc.row_label(sport, row), entry=entry, sections=keys)
    for pick in sheet.get("picks") or []:
        entry = (reconciled.get("picks") or {}).get(cs.pick_result_key(pick))
        y = _num((entry or {}).get("y"))
        card = {"card_id": pick.get("pick_id"), "sport": sport, "date": day, "event_id": pick.get("event_id"),
                "kind": pick.get("kind"), "pick_id": pick.get("pick_id"), "market": pick.get("market"), "line": pick.get("line"),
                "side": pick.get("side"), "segment": pick.get("segment"), "price": pick.get("price"), "book": pick.get("book"),
                "books_quoting": pick.get("books"), "p_market": pick.get("p_market"), "p_model": pick.get("p_model"),
                "ev_market": pick.get("ev_pct"), "player": pick.get("player_name"),
                "result": None if y is None else {"y": y, "units": _units(pick.get("price"), y)},
                "close": (closes or {}).get(str(pick.get("pick_id"))) or {}}
        add(pick, card, label=pick.get("label") or cs.pick_label(pick), entry=entry, sections=["picks"])
    lines = sheet.get("game_lines") or []
    for i in (sheet.get("sections") or {}).get("lines_value") or []:
        if int(i) >= len(lines):
            continue
        line = dict(lines[int(i)], kind="game")
        entry = (reconciled.get("lines") or {}).get(cs.line_result_key(line))
        chk = line.get("check") or {}
        y = _num((entry or {}).get("y"))
        card = {"card_id": f"line:{cs.line_result_key(line)}", "sport": sport, "date": day, "event_id": line.get("event_id"),
                "kind": "game", "market": line.get("market"), "line": line.get("line"), "side": line.get("side"),
                "price": chk.get("price"), "book": chk.get("book"), "books_quoting": line.get("books_quoting"),
                "p_market": chk.get("p_market"), "p_model": chk.get("p_model"), "ev_market": chk.get("ev_market"),
                "result": None if y is None else {"y": y, "units": _units(chk.get("price"), y)},
                "close": (closes or {}).get(f"line:{cs.line_result_key(line)}") or {}}
        add(dict(line, p_model=chk.get("p_model"), p_market=chk.get("p_market")), card,
            label=cs.pick_label({"sport": sport, "market": line.get("market"), "p_model": chk.get("p_model"),
                                 "p_market": chk.get("p_market")}), entry=entry, sections=["lines_value"])
    return out


def engine_summary(records: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Counts with their denominators: verdicts, opportunity vs efficiency on losses, the sim's side record and its
    mean error where it projected (positive = the sim was LOW)."""
    recs = list(records)
    verdicts: dict[str, int] = {}
    for r in recs:
        verdicts[r.get("verdict") or "?"] = verdicts.get(r.get("verdict") or "?", 0) + 1
    losses = [r for r in recs if r.get("outcome") == "loss" and r.get("usage_kind")]
    sims = [r["sim"] for r in recs if r.get("sim")]
    errors = [s["error"] for s in sims if isinstance(s.get("error"), (int, float))]
    return {"graded": len(recs), "verdicts": verdicts,
            "losses_with_usage": len(losses),
            "losses_opportunity": sum(1 for r in losses if r["usage_kind"] == "opportunity"),
            "sim_judged": len(sims), "sim_right_side": sum(1 for s in sims if s.get("right_side")),
            "sim_errors": len(errors), "sim_mean_error": round(sum(errors) / len(errors), 2) if errors else None}


def postmortem(card: Mapping[str, Any], item: Mapping[str, Any], classification: Mapping[str, Any]) -> dict[str, Any]:
    """The engine-ledger record for one graded card: the bet, the prices, the sim, the actual and the classification."""
    keep = ("card_id", "sport", "date", "event_id", "kind", "pick_id", "market", "line", "side", "segment", "price", "book",
            "books_quoting", "p_market", "p_model", "ev_market", "result")
    out = {k: card.get(k) for k in keep}
    out.update({"player": card.get("player") or item.get("player_name") or item.get("player"),
                "label": item.get("label") or card.get("label"), "sim_view": item.get("sim_view"), **classification})
    return out


def find_item(sheet: Mapping[str, Any], card: Mapping[str, Any]) -> Mapping[str, Any] | None:
    """The sheet pick (by pick_id) or row (by card id) a ledger card was made from."""
    from syndicate.features.shared import play_cards as pc

    if card.get("pick_id"):
        return next((p for p in sheet.get("picks") or [] if p.get("pick_id") == card["pick_id"]), None)
    return next((r for r in sheet.get("rows") or [] if pc.card_id(card["sport"], card["date"], r) == card["card_id"]), None)


def reconciled_entry(reconciled: Mapping[str, Any] | None, item: Mapping[str, Any]) -> Mapping[str, Any] | None:
    from syndicate.features.shared import cheat_sheets as cs

    if not reconciled:
        return None
    if item.get("pick_id"):
        return (reconciled.get("picks") or {}).get(cs.pick_result_key(item))
    return (reconciled.get("props") or {}).get(cs.prop_result_key(item))


def slug(text: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(text or "").lower()).strip("-")[:40]


def iter_due(cards: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """Ledger cards with a settled result (win, loss or push)."""
    return [c for c in cards if outcome(c.get("result")) is not None]
