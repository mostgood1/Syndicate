"""Do the app's surfaces show the SAME line the SAME way? A read-only cross-surface check.

WHY THIS EXISTS `[2026-11-23, lane surface-consistency-oversight, todo #861]`. Every
surface that shows a bet starts from the same universe (the Layer 2 shortlist, or the
quote grid under it). Each then re-derives fair, price, EV and the pick with its own
rules. Measured on the fleet 2026-11-23 19:25-19:32Z
(`.syndicate/findings_2026-11-23_surface_consistency.md`):

- Layer 2 and the cheat sheet gave the same line at the SAME book and SAME price
  different EVs (+4.01 vs +2.83, +1.33 vs +4.64). Age cannot do that: the input price
  is identical.
- Ask's headline `top_opportunities` was the same 5 rows for an NBA question and for
  "best bets". They were ranked by model edge, and 4 of the 5 carried a verdict that
  the model LOSES to the market.
- 0 of 33 live orders shared a position_key with the Stage A plan.
- The NHL sport cards put the away team above the market's fair on 7 of 7 games.

One reading is not oversight. This turns that reading into a check that can be run
again and that exits non-zero, in the spirit of `sim_input_checklist.py`.

WHAT IT DOES. GETs from the fleet only (3 in flight at most: 12 at once drew 7
connection resets from web on 2026-11-23). It also POSTs two read-only Ask queries.
Then it joins lines on (event_id, market, player, side, line, segment) and reports one
block per check:

  same_price_ev      pairs at the same book and price whose EVs differ by more than 0.5
  pick_flag          lines where Layer 2 Suggested and the cheat sheet's flag disagree
  ask_headline       Ask headline rows that are not the board's picks, or not in
                     the asked sport (model-skill counts reported, not judged)
  sim_attribution    Ask card text "Our sim has ... at X%" where X is the market fair
                     and the sim's own ladder differs by more than 5 pp
  plan_vs_orders     today's live orders absent from the Stage A plan, or not Suggested
  venue_price_hidden orders bought at a better price than the board's best for the
                     same line
  sport_card_bias    NHL sport-card win probability minus the Layer 1 consensus fair,
                     per side (mean signed pp)

It writes nothing to the fleet. Exit codes: 0 every check within its limit, 1 one or
more checks over, 2 a fetch failed (the reading is incomplete, so it is not a pass).
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import datetime as dt
import json
import re
import statistics
import sys
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

MAX_IN_FLIGHT = 3
EV_TOLERANCE_PTS = 0.5
SIM_GAP_PP = 5.0
ASK_QUESTIONS = {
    "ask_all": "What are the best bets today?",
    "ask_nba": "Best NBA bets tonight?",
}
CHEAT_SPORTS = ("nba", "ncaab", "nhl", "nfl", "ncaaf", "soccer")


# ---------------------------------------------------------------- identity + maths


def american_to_prob(price: Any) -> float | None:
    try:
        a = float(price)
    except (TypeError, ValueError):
        return None
    if a == 0 or -100 < a < 100:
        return None
    return 100.0 / (a + 100.0) if a > 0 else -a / (-a + 100.0)


def norm_market(market: Any) -> str:
    m = str(market or "").strip().lower().replace(" ", "_")
    return re.sub(r"^player_", "", m)


def norm_side(side: Any) -> str:
    s = str(side or "").strip().lower()
    return {"yes": "over", "no": "under"}.get(s, s)


def norm_line(line: Any) -> float | None:
    try:
        return round(float(line) * 2) / 2
    except (TypeError, ValueError):
        return None


def line_key(event_id: Any, market: Any, player: Any, side: Any, line: Any, segment: Any = "full") -> tuple:
    return (
        str(event_id or ""),
        norm_market(market),
        str(player or "").strip().lower(),
        norm_side(side),
        norm_line(line),
        str(segment or "full").strip().lower(),
    )


def norm_team(name: Any) -> str:
    return re.sub(r"[^a-z]", "", str(name or "").lower())


# ---------------------------------------------------------------- extraction


def layer2_records(payload: dict) -> dict[tuple, dict]:
    out: dict[tuple, dict] = {}
    for r in payload.get("rows") or []:
        q = r.get("quote") or {}
        pj = r.get("projection") or {}
        sim_raw = pj.get("p_model_raw")
        if sim_raw is not None and norm_side(r.get("side")) == "under":
            sim_raw = 1.0 - float(sim_raw)
        k = line_key(r.get("event_id"), r.get("market"), r.get("player_name"), r.get("side"), r.get("line"), r.get("segment"))
        if not k[0]:
            continue
        out.setdefault(
            k,
            {
                "fair": q.get("fair_probability"),
                "model": r.get("model_probability_cal"),
                "sim_raw": sim_raw,
                "ev": r.get("ev_pct"),
                "book": q.get("bookmaker"),
                "price": q.get("price"),
                "suggested": bool(r.get("suggested")),
                "live": bool(r.get("is_live")),
                "sport": r.get("sport"),
            },
        )
    return out


def cheat_records(payload: dict) -> dict[tuple, dict]:
    out: dict[tuple, dict] = {}
    for r in (payload.get("rows") or []) + (payload.get("game_lines") or []):
        ck = r.get("check") or {}
        k = line_key(r.get("event_id"), r.get("market"), r.get("player"), r.get("side"), r.get("line"))
        if not k[0]:
            continue
        out.setdefault(
            k,
            {
                "fair": ck.get("p_market"),
                "model": ck.get("p_model"),
                "ev": ck.get("ev_market"),
                "book": ck.get("book"),
                "price": ck.get("price"),
                "suggested": bool(r.get("suggested")),
                "verdict": ck.get("verdict"),
            },
        )
    return out


def _same_number(a: Any, b: Any) -> bool:
    try:
        return float(a) == float(b)
    except (TypeError, ValueError):
        return False


# ---------------------------------------------------------------- checks


def check_same_price_ev(l2: dict, other: dict, *, name: str, tolerance: float = EV_TOLERANCE_PTS) -> dict:
    """Same line, same book, same price: the EVs must agree. Only the fair can differ."""
    pairs = []
    for k, a in l2.items():
        b = other.get(k)
        if not b or a.get("live"):
            continue
        if not a.get("book") or a.get("book") != b.get("book") or not _same_number(a.get("price"), b.get("price")):
            continue
        if a.get("ev") is None or b.get("ev") is None:
            continue
        pairs.append((k, float(a["ev"]), float(b["ev"]), a.get("book"), a.get("price")))
    bad = [p for p in pairs if abs(p[1] - p[2]) > tolerance]
    return {
        "check": f"same_price_ev:{name}",
        "n": len(pairs),
        "bad": len(bad),
        "limit": 0,
        "examples": [
            {"line": "|".join(map(str, k)), "book": bk, "price": pr, "layer2_ev": round(e1, 2), f"{name}_ev": round(e2, 2)}
            for k, e1, e2, bk, pr in sorted(bad, key=lambda p: -abs(p[1] - p[2]))[:5]
        ],
    }


def check_pick_flag(l2: dict, cheat: dict) -> dict:
    joined = [(k, l2[k], cheat[k]) for k in cheat if k in l2 and not l2[k].get("live")]
    bad = [(k, a, b) for k, a, b in joined if a["suggested"] != b["suggested"]]
    return {
        "check": "pick_flag:layer2_vs_cheat",
        "n": len(joined),
        "bad": len(bad),
        "limit": 0,
        "cheat_flagged": sum(1 for _, _, b in joined if b["suggested"]),
        "both_flagged": sum(1 for _, a, b in joined if a["suggested"] and b["suggested"]),
        "examples": [
            {"line": "|".join(map(str, k)), "layer2": a["suggested"], "cheat": b["suggested"], "layer2_ev": a.get("ev"), "cheat_ev": b.get("ev")}
            for k, a, b in bad[:5]
        ],
    }


_LOSES_RE = re.compile(r"\blos(?:es|e|ing)\b", re.IGNORECASE)


def check_ask_headline(answer: dict, *, asked_sport: str | None) -> dict:
    """Ask's headline must be the BOARD'S picks, in the asked sport.

    Changed 2026-11-23 after step 1a was deployed (`d845fe345`). This first
    counted any row from a model measured to lose, or never measured, as bad.
    That was the shape of the defect when the headline ranked on model edge.
    Since the deploy, the headline rows are board picks chosen on PRICE, and the
    sim's skill verdict rides beside them as information. So a row is bad when
    it is not a board pick (`suggested` is not True) or is off-sport. The skill
    counts are still reported.
    """
    rows = ((answer.get("structured_response") or {}).get("top_opportunities")) or []
    # whole word: "beats the close" contains the letters "lose" (caught by the test)
    losing = [r for r in rows if _LOSES_RE.search(str(r.get("model_skill_verdict") or ""))]
    unmeasured = [r for r in rows if str(r.get("model_skill_status") or "") != "measured"]
    off_sport = [r for r in rows if asked_sport and str(r.get("sport") or "").lower() != asked_sport]
    not_a_pick = [r for r in rows if r.get("suggested") is not True]
    bad = {id(r) for r in not_a_pick + off_sport}
    return {
        "check": f"ask_headline:{asked_sport or 'all'}",
        "n": len(rows),
        "bad": len(bad),
        "limit": 0,
        "not_a_board_pick": len(not_a_pick),
        "off_sport": len(off_sport),
        "losing_model": len(losing),
        "unmeasured_model": len(unmeasured),
        "examples": [
            {"sport": r.get("sport"), "market": r.get("market"), "edge_pct": r.get("edge_pct"), "verdict": str(r.get("model_skill_verdict") or "")[:90]}
            for r in rows[:5]
        ],
    }


_OUR_SIM_RE = re.compile(r"Our sim has .*? at (\d+(?:\.\d+)?)%")


def check_sim_attribution(answer: dict, l2: dict, *, gap_pp: float = SIM_GAP_PP) -> dict:
    cards = ((answer.get("board_contract") or {}).get("cards")) or []
    n = 0
    bad = []
    for c in cards:
        m = _OUR_SIM_RE.search(str(c.get("detail") or ""))
        if not m:
            continue
        player = c.get("player") if isinstance(c.get("player"), str) else c.get("player_name")
        row = l2.get(line_key(c.get("event_id"), c.get("market"), player, c.get("side") or c.get("selection"), c.get("line"), c.get("segment")))
        if not row or row.get("sim_raw") is None or row.get("fair") is None:
            continue
        n += 1
        quoted = float(m.group(1)) / 100.0
        if abs(quoted - float(row["sim_raw"])) * 100 > gap_pp and abs(quoted - float(row["fair"])) * 100 <= 0.5:
            bad.append({"market": c.get("market"), "player": player, "quoted": round(quoted, 3), "sim_ladder": round(float(row["sim_raw"]), 3), "market_fair": round(float(row["fair"]), 3)})
    return {"check": "sim_attribution:ask_cards", "n": n, "bad": len(bad), "limit": 0, "examples": bad[:5]}


def check_plan_vs_orders(plan: dict, live: dict, l2: dict) -> dict:
    plan_keys = {p.get("position_key") for p in plan.get("positions") or []}
    orders = [o for o in live.get("orders") or [] if o.get("mode") == "live"]
    not_in_plan = [o for o in orders if o.get("position_key") not in plan_keys]
    on_board = []
    for o in orders:
        row = l2.get(line_key(o.get("event_id"), o.get("market"), o.get("player_name"), o.get("side"), o.get("line"), o.get("segment")))
        if row:
            on_board.append((o, row))
    return {
        "check": "plan_vs_orders",
        "n": len(orders),
        "bad": len(not_in_plan),
        "limit": 0,
        "plan_positions": len(plan_keys),
        "orders_on_board": len(on_board),
        "orders_on_board_suggested": sum(1 for _, r in on_board if r.get("suggested")),
        "side_picked_by": dict(Counter(str(o.get("side_picked_by")) for o in orders)),
        "venues": dict(Counter(str(o.get("book")) for o in orders)),
    }


def check_venue_price_hidden(live: dict, l2: dict) -> dict:
    n = 0
    bad = []
    for o in live.get("orders") or []:
        row = l2.get(line_key(o.get("event_id"), o.get("market"), o.get("player_name"), o.get("side"), o.get("line"), o.get("segment")))
        po, pb = american_to_prob(o.get("requested_price")), american_to_prob(row.get("price") if row else None)
        if not row or po is None or pb is None:
            continue
        n += 1
        if po < pb - 1e-9:  # the order paid less implied probability = a better price than the board shows
            bad.append({"market": o.get("market"), "order": f"{o.get('book')} {o.get('requested_price')}", "board_best": f"{row.get('book')} {row.get('price')}", "order_ev": o.get("ev_pct"), "board_ev": row.get("ev")})
    return {"check": "venue_price_hidden", "n": n, "bad": len(bad), "limit": 0, "examples": bad[:5]}


def check_sport_card_bias(cards: dict, layer1: dict, *, limit_pp: float = 2.0) -> dict:
    diffs = []
    for g in cards.get("games") or []:
        b = g.get("betting") or {}
        if b.get("p_away_win") is None:
            continue
        away, home = g.get("away_name") or (g.get("away") or {}).get("name"), g.get("home_name") or (g.get("home") or {}).get("name")
        for G in layer1.get("games") or []:
            if norm_team(G.get("away_team"))[:5] != norm_team(away)[:5] or norm_team(G.get("home_team"))[:5] != norm_team(home)[:5]:
                continue
            rows = [r for r in G.get("rows") or [] if r.get("market") == "h2h" and (r.get("segment") or "full") == "full"]
            if not rows:
                continue
            c = rows[0].get("consensus") or {}
            pa, ph = american_to_prob(c.get("away")), american_to_prob(c.get("home"))
            if pa is None or ph is None:
                continue
            diffs.append((float(b["p_away_win"]) - pa / (pa + ph)) * 100)
            break
    mean = statistics.mean(diffs) if diffs else None
    same_sign = max(sum(d > 0 for d in diffs), sum(d < 0 for d in diffs)) if diffs else 0
    return {
        "check": "sport_card_bias:nhl_away_ml",
        "n": len(diffs),
        "bad": int(bool(diffs) and abs(mean) > limit_pp),
        "limit": 0,
        "mean_signed_pp": round(mean, 2) if mean is not None else None,
        "same_sign_games": same_sign,
    }


# ---------------------------------------------------------------- fetch + run


def _endpoints(day: str) -> dict[str, tuple[str, str, dict | None]]:
    eps: dict[str, tuple[str, str, dict | None]] = {
        "l2": ("GET", f"/api/board/layer2-shortlist?date={day}&limit=2000", None),
        "plan": ("GET", f"/api/portfolio/plan?date={day}", None),
        "live": ("GET", f"/api/portfolio/live?date={day}", None),
        "l1_nhl": ("GET", f"/api/board/layer1?date={day}&sport=nhl", None),
        "nhl_cards": ("GET", f"/nhl/api/cards?date={day}", None),
    }
    for s in CHEAT_SPORTS:
        eps[f"cheat_{s}"] = ("GET", f"/api/cheatsheets/{s}/{day}", None)
    for k, q in ASK_QUESTIONS.items():
        eps[k] = ("POST", "/api/syndicate/query", {"question": q})
    return eps


def fetch_all(base_url: str, token: str, day: str, *, timeout: float = 150.0) -> tuple[dict[str, Any], dict[str, str]]:
    eps = _endpoints(day)

    def one(name: str):
        method, path, body = eps[name]
        headers = {"X-Admin-Token": token}
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body).encode()
        req = urllib.request.Request(base_url + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return name, json.loads(resp.read()), None
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return name, {}, None  # no sheet for that sport today: absent, not failed
            return name, None, f"HTTP {exc.code}"
        except Exception as exc:  # noqa: BLE001 -- any failure makes the reading incomplete
            return name, None, type(exc).__name__

    got: dict[str, Any] = {}
    errors: dict[str, str] = {}
    with cf.ThreadPoolExecutor(MAX_IN_FLIGHT) as pool:
        for name, payload, err in pool.map(one, eps):
            if err:
                errors[name] = err
            else:
                got[name] = payload
    return got, errors


def run_checks(got: dict[str, Any]) -> list[dict]:
    l2 = layer2_records(got.get("l2") or {})
    cheat: dict[tuple, dict] = {}
    for s in CHEAT_SPORTS:
        for k, v in cheat_records(got.get(f"cheat_{s}") or {}).items():
            cheat.setdefault(k, v)
    checks = [
        check_same_price_ev(l2, cheat, name="cheat"),
        check_pick_flag(l2, cheat),
        check_ask_headline(got.get("ask_all") or {}, asked_sport=None),
        check_ask_headline(got.get("ask_nba") or {}, asked_sport="nba"),
        check_sim_attribution(got.get("ask_nba") or {}, l2),
        check_plan_vs_orders(got.get("plan") or {}, got.get("live") or {}, l2),
        check_venue_price_hidden(got.get("live") or {}, l2),
        check_sport_card_bias(got.get("nhl_cards") or {}, got.get("l1_nhl") or {}),
    ]
    for c in checks:
        c["verdict"] = "OVER" if c["bad"] > c["limit"] else "OK"
    return checks


def main(argv: list[str] | None = None) -> int:
    from _base_url import admin_token, default_base_url

    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--base-url", default=default_base_url())
    ap.add_argument("--date", default=None, help="slate date (default: today, America/Chicago)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--write", default=None, help="write the full reading as JSON to this path")
    args = ap.parse_args(argv)

    if args.date:
        day = args.date
    else:
        from zoneinfo import ZoneInfo

        day = dt.datetime.now(ZoneInfo("America/Chicago")).date().isoformat()
    token = admin_token(args.base_url)
    if not token or len(token) > 256 or "\x00" in token:
        print("ADMIN TOKEN UNREADABLE (wsl.exe hop failed?) -- no reading taken", file=sys.stderr)
        return 2
    started = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    got, errors = fetch_all(args.base_url.rstrip("/"), token, day)
    finished = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    checks = run_checks(got)
    reading = {"date": day, "base_url": args.base_url, "read_from": started, "read_to": finished, "fetch_errors": errors, "checks": checks}
    if args.write:
        Path(args.write).write_text(json.dumps(reading, indent=1, default=str), encoding="utf-8")
    if args.json:
        print(json.dumps(reading, indent=1, default=str))
    else:
        print(f"surface consistency  date={day}  read {started} .. {finished}")
        for c in checks:
            extra = {k: v for k, v in c.items() if k not in ("check", "n", "bad", "limit", "verdict", "examples")}
            print(f"  {c['verdict']:4s} {c['check']:34s} bad {c['bad']:>4} of {c['n']:<5} {json.dumps(extra, default=str) if extra else ''}")
        if errors:
            print(f"  FETCH ERRORS (reading incomplete): {errors}")
    if errors:
        return 2
    return 1 if any(c["verdict"] == "OVER" for c in checks) else 0


if __name__ == "__main__":
    raise SystemExit(main())
