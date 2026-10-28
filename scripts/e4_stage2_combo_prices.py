"""E4 Stage 2: do Kalshi's same-game combo PRINTS price the sims' correlation? (lane `e4-combo-correlation`, #740 (d)).

PRE-REGISTERED: §7 of `.syndicate/findings_2026-10-26_e4_combo_correlation_preregistration.md` (`9f8d759e`, A1, A2)
and amendment A3, committed with this file BEFORE any price x probability x outcome join. Runs only for the four
cells Stage 1 passed under Holm: MLB SP-nested, MLB SP-other, NBA SP-nested, soccer GL.

READ-ONLY. Reads the fleet data root -- the #742 combo capture store, `book_quotes`, the frozen sims -- and sends
only unauthenticated public GETs: Kalshi leg-market metadata (`/markets?tickers=`, cached), one `/series/<ticker>`
fee read, and Stage 1's cached outcome GETs. Imports no order, execution or credential code.

    nice -n 19 /home/amyn/.venvs/syndicate/bin/python scripts/e4_stage2_combo_prices.py \
        --data-root ~/syndicate-prod/data --out /mnt/c/tmp/e4/stage2.json --cache /mnt/c/tmp/e4/cache

Unit: one TRADED two-leg combo whose legs are one game and map onto a passing cell. Its price q is the capture's
`last_price` (the last print's YES price). All arms share the legs' market marginals AT THE COMBO'S LINES and one
Gaussian copula; they differ only in rho: (a) 0, (b) the sim's, (c) the SGP measured copula (MLB/NBA).
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
import os
import statistics
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
for _p in (REPO_ROOT, REPO_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import e4_combo_correlation as s1  # noqa: E402
from syndicate.features.nfl.sgp import rho_for  # noqa: E402
from syndicate.features.shared.kalshi_catalogue import (  # noqa: E402
    event_blob_from_ticker,
    event_start_from_ticker,
    game_date_from_ticker,
    match_event_blob,
)

UTC = s1.UTC

# ----------------------------------------------------------------------------- registered constants (A3)
PASSING = (("mlb", "SP-nested"), ("mlb", "SP-other"), ("nba", "SP-nested"), ("soccer", "GL"))
MIN_GAMES, MIN_COMBOS = 20, 200
DELTA_MIN = 0.01                       # R2: |p_b - p_a| >= 1 pp
KALSHI_TAKER_RATE = 0.07
STORE_SUBDIR = ("reports", "intelligence", "kalshi_combo_capture")
META_BATCH = 100

MLB_SERIES = {"KXMLBHIT": "batter_hits", "KXMLBTB": "batter_total_bases", "KXMLBHR": "batter_home_runs",
              "KXMLBRBI": "batter_rbis"}
NBA_SERIES = {"KXNBAPTS": "player_points", "KXNBAREB": "player_rebounds", "KXNBAAST": "player_assists",
              "KXNBAPRA": "player_points_rebounds_assists"}
SOCCER_KINDS = ("GAME", "TOTAL", "BTTS")


# ----------------------------------------------------------------------------- leg shape (ticker only)
def _f(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def series_of(ticker: Any) -> str:
    return str(ticker or "").split("-")[0].upper()


def soccer_kind(series: str) -> str | None:
    """`KXEPLGAME` -> GAME; full-match result / total / BTTS only (never 1H, 2H or a team total)."""
    for kind in SOCCER_KINDS:
        if series.endswith(kind):
            head = series[: -len(kind)]
            if head.endswith(("1H", "2H", "TEAM")) or not head.startswith("KX"):
                return None
            return kind
    return None


def player_segment(ticker: Any) -> str | None:
    parts = str(ticker or "").split("-")
    return parts[2] if len(parts) >= 4 else None


def shape_cell(sport: str, league: str | None, a: str, b: str) -> str | None:
    """The cell a two-leg combo can belong to from its tickers alone, or None (counted, never tested)."""
    sa, sb = series_of(a), series_of(b)
    if sport == "mlb":
        if sa in MLB_SERIES and sb in MLB_SERIES and sa != sb and player_segment(a) == player_segment(b) and player_segment(a):
            stats = frozenset((s1.MLB_STAT[MLB_SERIES[sa]], s1.MLB_STAT[MLB_SERIES[sb]]))
            return "SP-nested" if stats in s1.MLB_NESTED else "SP-other"
        return None
    if sport == "nba":
        if sa in NBA_SERIES and sb in NBA_SERIES and sa != sb and player_segment(a) == player_segment(b) and player_segment(a):
            return s1.nba_kind(NBA_SERIES[sa], NBA_SERIES[sb])
        return None
    if sport == "soccer" and league in s1.SOCCER_LEAGUES:
        ka, kb = soccer_kind(sa), soccer_kind(sb)
        if ka and kb and not (ka == "GAME" and kb == "GAME"):
            return "GL"
    return None


# ----------------------------------------------------------------------------- the capture store (#742)
def store_dir(root: Path) -> Path:
    return Path(root).joinpath(*STORE_SUBDIR)


def iter_store(root: Path, first: date, last: date) -> Iterator[dict[str, Any]]:
    """Rows of `combos_<settled date>.jsonl.gz` for settlement dates first..last, first row per ticker, STREAMED."""
    for d in s1.daterange(first, last):
        path = store_dir(root) / f"combos_{d.isoformat()}.jsonl.gz"
        if not path.is_file():
            continue
        seen: set[str] = set()
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            for line in fh:
                if '"n_legs":2,' not in line:       # the store is sort_keys JSON with compact separators
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                t = row.get("ticker")
                if isinstance(row, dict) and t and t not in seen:
                    seen.add(t)
                    yield row


def candidate(row: Mapping[str, Any], funnel: Counter) -> dict[str, Any] | None:
    """A3 §3: a traded two-leg combo, both legs one game, game dated in the Stage 1 window, shaped like a passing cell."""
    if int(row.get("n_legs") or 0) != 2:
        return None
    funnel["two_leg"] += 1
    if not row.get("traded"):
        funnel["untraded"] += 1
        return None
    groups = row.get("same_game") or []
    if len(groups) != 1 or len(groups[0].get("legs") or []) != 2:
        funnel["not_one_game"] += 1
        return None
    g = groups[0]
    legs = row.get("legs") or []
    a, b = (str(x.get("market_ticker") or "") for x in legs)
    gd = game_date_from_ticker(a)
    if gd is None or not (s1.WINDOW_START.isoformat() <= gd <= s1.WINDOW_END.isoformat()):
        funnel["outside_window"] += 1
        return None
    cell = shape_cell(g.get("sport"), g.get("league"), a, b)
    if cell is None:
        funnel[f"not_a_cell:{g.get('sport')}"] += 1
        return None
    quote = row.get("quote_at_capture") or {}
    q = _f(quote.get("last_price"))
    if q is None or not (0.0 < q < 1.0):
        funnel["no_print_price"] += 1
        return None
    funnel[f"shaped:{g['sport']}|{cell}"] += 1
    return {"ticker": row.get("ticker"), "series": row.get("series"), "sport": g["sport"], "league": g.get("league"),
            "game_seg": g.get("game"), "game_date": gd, "shape_cell": cell, "q": q,
            "volume": _f(row.get("volume_fp")), "result": str(row.get("result") or "").lower(),
            "created_time": row.get("created_time"), "settlement_ts": row.get("settlement_ts"),
            "legs": [{"ticker": str(x.get("market_ticker") or ""), "side": str(x.get("side") or "").lower()}
                     for x in legs]}


def read_candidates(root: Path, funnel: Counter) -> list[dict[str, Any]]:
    out = []
    for row in iter_store(root, s1.WINDOW_START - timedelta(days=1), s1.WINDOW_END + timedelta(days=3)):
        c = candidate(row, funnel)
        if c is not None:
            out.append(c)
    return out


# ----------------------------------------------------------------------------- leg metadata (public GETs, cached)
META_KEYS = ("ticker", "event_ticker", "title", "yes_sub_title", "floor_strike", "strike_type", "rules_primary",
             "result")


def fetch_leg_meta(tickers: Iterable[str], cache: Path, get=None) -> tuple[dict[str, dict], dict[str, int]]:
    if get is None:
        from syndicate.features.shared.kalshi_maker_shadow import public_get_json as get
    path = Path(cache) / "stage2_leg_meta.json"
    meta: dict[str, dict] = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    want = sorted({t for t in tickers if t and t not in meta})
    stats = {"gets": 0, "failed": 0, "cached": len(meta)}
    for i in range(0, len(want), META_BATCH):
        batch = want[i:i + META_BATCH]
        payload = get("/markets", {"tickers": ",".join(batch), "limit": len(batch)})
        stats["gets"] += 1
        if not payload:
            stats["failed"] += 1
            continue
        for m in payload.get("markets") or []:
            if m.get("ticker") in batch:
                meta[m["ticker"]] = {k: m.get(k) for k in META_KEYS}
    Path(cache).mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(meta), encoding="utf-8")
    return meta, stats


def read_fee_multiplier(series: str, get=None) -> tuple[float, bool]:
    """(m, is_upper_bound): the combo series' own `fee_multiplier`; unreadable -> 1.0, stamped as an upper bound."""
    from syndicate.features.shared.venue_fees import VenueFeeError, kalshi_fee_params
    if get is None:
        from syndicate.features.shared.kalshi_maker_shadow import public_get_json as get
    try:
        _, m = kalshi_fee_params(get(f"/series/{series}") or {})
        return float(m), False
    except (VenueFeeError, TypeError, ValueError):
        return 1.0, True


# ----------------------------------------------------------------------------- parse a leg (A3 §4)
def parse_leg(sport: str, ticker: str, meta: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """The leg's YES event: {market, subject, line, code}; None when the metadata cannot say it."""
    if not meta:
        return None
    series = series_of(ticker)
    title = str(meta.get("title") or "")
    line = meta.get("floor_strike")
    if sport in ("mlb", "nba"):
        market = (MLB_SERIES if sport == "mlb" else NBA_SERIES).get(series)
        if market is None or meta.get("strike_type") != "greater" or line is None or ":" not in title:
            return None
        return {"market": market, "subject": s1.norm_name(title.split(":", 1)[0]), "line": s1.norm_line(line)}
    kind = soccer_kind(series)
    if kind == "TOTAL":
        ln = s1.norm_line(line)
        if meta.get("strike_type") != "greater" or ln is None or abs((ln % 1) - 0.5) > 1e-9:
            return None
        return {"market": "totals", "subject": "", "line": ln}
    if kind == "BTTS":
        return {"market": "btts", "subject": "", "line": None} if title.lower() == "both teams to score" else None
    if kind == "GAME":
        code = str(ticker).split("-")[-1].upper()
        if code == "TIE":
            return ({"market": "h2h", "subject": "", "line": None, "code": code, "draw": True, "club": ""}
                    if title == "Tie is the result" else None)
        if not title.endswith(" wins"):
            return None
        return {"market": "h2h", "subject": "", "line": None, "code": code, "draw": False,
                "club": title[: -len(" wins")]}
    return None


def soccer_code_names(metas: Iterable[tuple[str, Mapping[str, Any]]]) -> dict[str, dict[str, str]]:
    """Per league: Kalshi club code -> name, read off the GAME legs' own titles (`kalshi_catalogue` docstring)."""
    out: dict[str, dict[str, str]] = defaultdict(dict)
    for league, m in metas:
        t = str(m.get("ticker") or "")
        if soccer_kind(series_of(t)) == "GAME" and str(m.get("title") or "").endswith(" wins"):
            out[league][t.split("-")[-1].upper()] = str(m["title"])[: -len(" wins")]
    return out


# ----------------------------------------------------------------------------- market marginal at the combo's line
def line_index(latest: Mapping[tuple, tuple]) -> dict:
    """(event, market) -> player -> line -> book -> selection -> price, from A1's last-pregame-per-book table."""
    idx: dict = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: defaultdict(dict))))
    for (ev, book, mkt, player, line, sel), (_cap, price) in latest.items():
        idx[(ev, mkt)][player][line][book][sel] = price
    return idx


def marginal_at(idx: Mapping, ev: str, market: str, player: str, line: Any, sides: tuple[str, ...],
                event_side: str) -> dict[str, Any] | None:
    """A3 §5: A1's estimator at EXACTLY this line -- per-book two-sided de-vig, median; p in (0.02, 0.98)."""
    players = idx.get((ev, market)) or {}
    by_line = s1.name_lookup(players, player) if player else players.get("")
    if not by_line:
        return None
    books = by_line.get(line)
    if not books:
        return None
    ps = [d[event_side] for d in (s1.devig_book(pr, sides) for pr in books.values()) if d]
    if not ps:
        return None
    p = float(statistics.median(ps))
    if not (s1.P_MIN < p < s1.P_MAX):
        return None
    return {"p": p, "n_books": len(ps)}


# ----------------------------------------------------------------------------- the combo's three probabilities
def combo_probs(pa: float, pb: float, rho: float | None, side_a: str, side_b: str) -> float | None:
    """P(combo YES) under the §1 copula on the legs' YES-oriented marginals; a `no` leg takes the complement."""
    if rho is None:
        return None
    probs = s1.four_cell(np.array([pa]), np.array([pb]), float(np.clip(rho, -s1.RHO_CLIP, s1.RHO_CLIP)))[0]
    return float(probs[s1.cell_index(np.array([int(side_a == "yes")]), np.array([int(side_b == "yes")]))[0]])


def fee_per_contract(q: float, m: float) -> float:
    """A3 §7: Kalshi quadratic taker fee per contract, not rounded (order size is not captured)."""
    return KALSHI_TAKER_RATE * m * q * (1.0 - q)


def ev_yes(p: float, q: float, m: float) -> float:
    return p / (q + fee_per_contract(q, m)) - 1.0


def ev_no(p: float, q: float, m: float) -> float:
    return (1.0 - p) / ((1.0 - q) + fee_per_contract(1.0 - q, m)) - 1.0


def band_of(delta: float) -> str:
    """§7's bands of p_b - p_a in pp, per sign: <1, 1-3, 3-5, >=5."""
    pp = round(delta * 100.0, 9)
    if pp < 0:
        return "<=-5" if pp <= -5 else "(-5,-3]" if pp <= -3 else "(-3,-1]" if pp <= -1 else "(-1,0)"
    return "[0,1)" if pp < 1 else "[1,3)" if pp < 3 else "[3,5)" if pp < 5 else ">=5"


# ----------------------------------------------------------------------------- join one sport's combos to Stage 1
def stage1_games(root: Path, fetch: s1.Fetcher, sport: str) -> tuple[list[dict], dict, dict, Counter]:
    """Stage 1's own games for the sport (identical loaders, gates and cache), plus A1's per-book quote table."""
    funnel: Counter = Counter()
    if sport == "mlb":
        mk = set(s1.MLB_STAT) | {"h2h", "totals"}
    elif sport == "nba":
        mk = set(s1.NBA_VEC)
    else:
        mk = {"h2h", "totals", "btts"}
    latest, events, _ = s1.load_quotes(root, sport, mk)
    legs = s1.market_legs(latest, events, sport)
    loader = {"mlb": s1.mlb_games, "nba": s1.nba_games, "soccer": s1.soccer_games}[sport]
    games = loader(root, fetch, legs, events, funnel)
    return games, latest, events, funnel


def blob_games(games: Sequence[Mapping[str, Any]], events: Mapping[str, Mapping[str, Any]]) -> list[dict]:
    out = []
    for i, g in enumerate(games):
        ev = events.get(g["event"]) or {}
        out.append({"event_id": i, "home_team": ev.get("home"), "away_team": ev.get("away"),
                    "commence_time": ev["commence"].isoformat() if ev.get("commence") else None,
                    "date": g["date"], "league": g.get("league")})
    return out


def join_game(c: Mapping[str, Any], games: Sequence[Mapping[str, Any]], bgames: Sequence[Mapping[str, Any]],
              code_names: Mapping[str, Mapping[str, str]]) -> tuple[dict | None, str]:
    """The Stage 1 game a combo is played in, by the PRODUCTION blob matcher (`match_event_blob`), or a named refusal."""
    t = c["legs"][0]["ticker"]
    blob = event_blob_from_ticker(t)
    d = date.fromisoformat(c["game_date"])
    near = [b for b in bgames if abs((date.fromisoformat(b["date"]) - d).days) <= 1
            and (c["sport"] != "soccer" or b.get("league") == c.get("league"))]
    if not near:
        return None, "no_stage1_game_that_day"
    res = match_event_blob(blob, near, sport=c["sport"], code_names=(code_names.get(c.get("league")) or None),
                           commence_hint=event_start_from_ticker(t))
    if res.get("status") != "ok":
        return None, f"game_{res.get('status')}"
    return games[res["event_id"]], "ok"


def _mlb_pid(joint: Mapping[str, Any], subject: str) -> str | None:
    players = joint.get("players") or {}
    by_name: dict[str, list[str]] = defaultdict(list)
    by_il: dict[str, list[str]] = defaultdict(list)
    for pid, meta in players.items():
        by_name[s1.norm_name(meta.get("name"))].append(pid)
        by_il[s1.initial_last(meta.get("name"))].append(pid)
    cand = by_name.get(subject) or by_il.get(s1.initial_last(subject)) or []
    return cand[0] if len(cand) == 1 else None


def price_combo(c: Mapping[str, Any], g: Mapping[str, Any], legs: Sequence[Mapping[str, Any]], idx: Mapping,
                cells_c: Mapping[str, Any], funnel: Counter) -> dict[str, Any] | None:
    """Marginals at the combo's lines, the three arms' rho, and each leg's graded outcome; None + a funnel reason."""
    sport, ev = c["sport"], g["event"]
    la, lb = legs
    sides = [x["side"] for x in c["legs"]]
    if sport == "mlb":
        joint = g["sim"]["sim"]["joint"]
        pid_a, pid_b = _mlb_pid(joint, la["subject"]), _mlb_pid(joint, lb["subject"])
        if pid_a is None or pid_a != pid_b:
            funnel["player_unmatched"] += 1
            return None
        bat = g["box"]["batters"].get(pid_a)
        if not bat or bat["pa"] <= 0:
            funnel["void_no_pa"] += 1
            return None
        stats = [s1.MLB_STAT[x["market"]] for x in legs]
        ma = [marginal_at(idx, ev, x["market"], x["subject"], x["line"], ("over", "under"), "over") for x in legs]
        if None in ma:
            funnel["leg_no_market_at_line"] += 1
            return None
        index = {lab: i for i, lab in enumerate(joint["labels"])}
        rs = s1.joint_rho_s(joint, index, f"batter|{pid_a}|{stats[0]}", f"batter|{pid_a}|{stats[1]}")
        if rs is None:
            funnel["rho_undefined"] += 1
            return None
        rb = s1.spearman_to_gauss(rs)
        rc, lvl = rho_for(cells_c, f"{la['market']}|X", f"{lb['market']}|X", "same_player")
        ys = [int(bat[s] > x["line"]) for s, x in zip(stats, legs)]
        cell = "SP-nested" if frozenset(stats) in s1.MLB_NESTED else "SP-other"
        stat_pair = "~".join(sorted(stats))
    elif sport == "nba":
        # one player: `shape_cell` already required both tickers to carry the same player segment
        if date.fromisoformat(g["date"]) < s1.NBA_REGULAR_FROM:
            funnel["preseason"] += 1
            return None
        cal = g["sim"].get("nba_prop_calibration") if isinstance(g["sim"].get("nba_prop_calibration"), Mapping) else {}
        applied, file_k = bool(cal.get("applied")), cal.get("k") if isinstance(cal.get("k"), Mapping) else None
        rows = {s1.norm_name(r.get("player_name")): r for side in ("home", "away")
                for r in (g["sim"].get("players") or {}).get(side) or []}
        row = s1.name_lookup(rows, la["subject"])
        if row is None:
            funnel["player_no_sim_row"] += 1
            return None
        sig, why = s1.nba_cov(row, file_k, applied)
        if sig is None:
            funnel[f"player_cov_{why}"] += 1
            return None
        b = s1.name_lookup(g["espn"]["box"], la["subject"])
        if b is None:
            funnel["leg_no_box"] += 1
            return None
        if b.get("dnp") or any(b.get(k) is None for k in ("pts", "reb", "ast")):
            funnel["void_dnp"] += 1
            return None
        ma = [marginal_at(idx, ev, x["market"], x["subject"], x["line"], ("over", "under"), "over") for x in legs]
        if None in ma:
            funnel["leg_no_market_at_line"] += 1
            return None
        rb = s1.nba_rho(sig, la["market"], lb["market"])
        if rb is None:
            funnel["rho_undefined"] += 1
            return None
        rc, lvl = rho_for(cells_c, f"{s1.NBA_SGP[la['market']]}|X", f"{s1.NBA_SGP[lb['market']]}|X", "same_player")
        ys = [int(float(np.dot(s1.NBA_VEC[x["market"]], (b["pts"], b["reb"], b["ast"]))) > x["line"]) for x in legs]
        cell = s1.nba_kind(la["market"], lb["market"])
        stat_pair = "~".join(sorted(s1.NBA_SGP[x["market"]] for x in legs))
    else:
        h, a = g["score"]["home"], g["score"]["away"]
        ma, ys, evkeys = [], [], []
        ev_meta = g.get("_event_meta") or {}
        for x in legs:
            if x["market"] == "h2h":
                key = _soccer_side(x, ev_meta)
                if key is None:
                    funnel["club_unresolved"] += 1
                    return None
                m = marginal_at(idx, ev, "h2h", "", None, ("home", "draw", "away"), key)
                y = {"home": h > a, "draw": h == a, "away": h < a}[key]
                evkeys.append(f"h2h_{key}")
            elif x["market"] == "totals":
                m = marginal_at(idx, ev, "totals", "", x["line"], ("over", "under"), "over")
                y = (h + a) > x["line"]
                evkeys.append("totals")
            else:
                m = marginal_at(idx, ev, "btts", "", None, ("yes", "no"), "yes")
                y = h > 0 and a > 0
                evkeys.append("btts")
            ma.append(m)
            ys.append(int(y))
        if None in ma:
            funnel["leg_no_market_at_line"] += 1
            return None
        tline = next((x["line"] for x in legs if x["market"] == "totals"), None)
        sev = s1.soccer_events((g["sim"] or {}).get("scoreline_probabilities") or {}, tline)
        if sev is None:
            funnel["sim_no_scorelines"] += 1
            return None
        w = sev["w"]
        p1, p2 = float((w * sev[evkeys[0]]).sum()), float((w * sev[evkeys[1]]).sum())
        p11 = float((w * sev[evkeys[0]] * sev[evkeys[1]]).sum())
        rb = s1.tetrachoric(p1, p2, p11)
        if rb is None:
            funnel["rho_undefined"] += 1
            return None
        rc, lvl = None, "none"
        cell = "GL"
        kinds = sorted(k.split("_")[0].replace("h2h", "result") for k in evkeys)
        stat_pair = "~".join(kinds)
    pa_, pb_ = ma[0]["p"], ma[1]["p"]
    rho_c = rc if lvl != "none" else None
    out = {"ticker": c["ticker"], "sport": sport, "cell": cell, "stat_pair": stat_pair, "game": g["game"],
           "date": g["date"], "q": c["q"], "volume": c["volume"], "result": c["result"],
           "side_a": sides[0], "side_b": sides[1], "pA": pa_, "pB": pb_, "yA": ys[0], "yB": ys[1],
           "rho_b": float(np.clip(rb, -s1.RHO_CLIP, s1.RHO_CLIP)), "rho_c": rho_c,
           "line_a": legs[0]["line"], "line_b": legs[1]["line"], "mkt_a": legs[0]["market"], "mkt_b": legs[1]["market"]}
    out["p_a"] = combo_probs(pa_, pb_, 0.0, *sides)
    out["p_b"] = combo_probs(pa_, pb_, out["rho_b"], *sides)
    out["p_c"] = combo_probs(pa_, pb_, rho_c, *sides)
    out["y_ours"] = int(ys[0] == int(sides[0] == "yes") and ys[1] == int(sides[1] == "yes"))
    return out


def _soccer_side(leg: Mapping[str, Any], ev_meta: Mapping[str, Any]) -> str | None:
    """A GAME leg's club -> home / away (by the production club resolver, then token Jaccard), or draw for TIE."""
    if leg.get("draw"):
        return "draw"
    from syndicate.features.shared.kalshi_catalogue import club_key
    club = leg.get("club") or ""
    for side in ("home", "away"):
        ours = ev_meta.get(side)
        k1, k2 = club_key("soccer", club), club_key("soccer", ours)
        if k1 and k2 and k1 == k2:
            return side
    scores = {side: s1.jaccard(s1.team_tokens(club), s1.team_tokens(ev_meta.get(side))) for side in ("home", "away")}
    best = max(scores, key=scores.get)
    other = "away" if best == "home" else "home"
    if scores[best] >= 0.34 and scores[best] > scores[other]:
        return best
    return None


# ----------------------------------------------------------------------------- readings (A3 §8-§9)
def clustered_mean(values: Sequence[float], games: Sequence[Any]) -> dict[str, Any]:
    v = np.asarray(values, float)
    if len(v) == 0:
        return {"n": 0}
    return s1.summarize_diff(v, np.asarray(games))


def clustered_slope(x: Sequence[float], y: Sequence[float], games: Sequence[Any]) -> dict[str, Any]:
    """OLS of y on x with a game-clustered (CR1) sandwich SE for the slope."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    n = len(x)
    if n < 3 or float(np.var(x)) <= 0:
        return {"n": int(n)}
    xc = x - x.mean()
    beta = float((xc * (y - y.mean())).sum() / (xc ** 2).sum())
    alpha = float(y.mean() - beta * x.mean())
    e = y - alpha - beta * x
    sums: dict[Any, float] = defaultdict(float)
    for g, s in zip(games, xc * e):
        sums[g] += float(s)
    gn = len(sums)
    se = math.sqrt(sum(s * s for s in sums.values()) * gn / max(gn - 1, 1)) / float((xc ** 2).sum())
    return {"n": int(n), "games": gn, "slope": beta, "intercept": alpha, "se": se,
            "ci": [beta - 1.96 * se, beta + 1.96 * se]}


def band_table(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    out = {}
    groups: dict[str, list] = defaultdict(list)
    for r in rows:
        groups[band_of(r["p_b"] - r["p_a"])].append(r)
    for lab, rr in groups.items():
        games = [r["game"] for r in rr]
        out[lab] = {"combos": len(rr), "games": len(set(games)),
                    "mean_q": float(np.mean([r["q"] for r in rr])), "mean_p_a": float(np.mean([r["p_a"] for r in rr])),
                    "mean_p_b": float(np.mean([r["p_b"] for r in rr])),
                    "mean_p_c": (float(np.mean([r["p_c"] for r in rr if r["p_c"] is not None]))
                                 if any(r["p_c"] is not None for r in rr) else None),
                    "ev_b_yes": clustered_mean([r["ev_b"] for r in rr], games),
                    "realised_yes": clustered_mean([r["ret_yes"] for r in rr if r.get("ret_yes") is not None],
                                                   [r["game"] for r in rr if r.get("ret_yes") is not None]),
                    "ev_b_no": clustered_mean([r["ev_b_no"] for r in rr], games),
                    "realised_no": clustered_mean([r["ret_no"] for r in rr if r.get("ret_no") is not None],
                                                  [r["game"] for r in rr if r.get("ret_no") is not None])}
    return out


def r2_test(rows: Sequence[Mapping[str, Any]], side: str) -> dict[str, Any]:
    """R2: realised return on the side the sim's correlation favours, among |p_b - p_a| >= 1 pp; INSUFFICIENT below min n."""
    if side == "yes":
        sel = [r for r in rows if r["p_b"] - r["p_a"] >= DELTA_MIN and r.get("ret_yes") is not None]
        vals = [r["ret_yes"] for r in sel]
        evs = [r["ev_b"] for r in sel]
    else:
        sel = [r for r in rows if r["p_a"] - r["p_b"] >= DELTA_MIN and r.get("ret_no") is not None]
        vals = [r["ret_no"] for r in sel]
        evs = [r["ev_b_no"] for r in sel]
    games = [r["game"] for r in sel]
    res = clustered_mean(vals, games)
    res["mean_ev_b"] = float(np.mean(evs)) if evs else None
    enough = res.get("n", 0) >= MIN_COMBOS and res.get("games", 0) >= MIN_GAMES
    res["sufficient"] = bool(enough)
    ok = enough and res["mean"] > 0 and math.isfinite(res.get("p_two_sided", float("nan")))
    res["p_holm_input"] = res["p_two_sided"] if ok else 1.0
    return res


def r3_logloss(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """R3 (descriptive): binary log loss of Kalshi's YES result under p_b vs p_a, game-clustered."""
    rr = [r for r in rows if r.get("y_kalshi") is not None]
    if not rr:
        return {"n": 0}
    y = np.array([r["y_kalshi"] for r in rr], float)
    pa = np.clip(np.array([r["p_a"] for r in rr]), s1.CELL_CLIP, 1 - s1.CELL_CLIP)
    pb = np.clip(np.array([r["p_b"] for r in rr]), s1.CELL_CLIP, 1 - s1.CELL_CLIP)
    ll = lambda p: -(y * np.log(p) + (1 - y) * np.log(1 - p))  # noqa: E731
    return {"D_ba": s1.summarize_diff(ll(pb) - ll(pa), np.array([r["game"] for r in rr])),
            "mean_y": float(y.mean()), "mean_p_a": float(pa.mean()), "mean_p_b": float(pb.mean())}


def finish_row(r: dict[str, Any], m: float, funnel: Counter) -> dict[str, Any]:
    q = r["q"]
    r["fee"] = fee_per_contract(q, m)
    for arm in ("a", "b", "c"):
        p = r[f"p_{arm}"]
        r[f"ev_{arm}"] = ev_yes(p, q, m) if p is not None else None
        r[f"ev_{arm}_no"] = ev_no(p, q, m) if p is not None else None
    r["y_kalshi"] = {"yes": 1, "no": 0}.get(r["result"])
    r["ret_yes"] = r["ret_no"] = None
    if r["y_kalshi"] is None:
        funnel["kalshi_result_not_yes_no"] += 1
    elif r["y_kalshi"] != r["y_ours"]:
        funnel["grading_disagrees_with_kalshi"] += 1
    else:
        r["ret_yes"] = r["y_kalshi"] / (q + r["fee"]) - 1.0
        r["ret_no"] = (1 - r["y_kalshi"]) / ((1.0 - q) + fee_per_contract(1.0 - q, m)) - 1.0
    return r


def readings(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {"cells": {}}
    pvals = {}
    for sport, cell in PASSING:
        rr = [r for r in rows if r["sport"] == sport and r["cell"] == cell]
        games = [r["game"] for r in rr]
        res: dict[str, Any] = {"combos": len(rr), "games": len(set(games))}
        if rr:
            res["bands"] = band_table(rr)
            res["R1_price_tracking"] = clustered_slope([r["p_b"] - r["p_a"] for r in rr],
                                                        [r["q"] - r["p_a"] for r in rr], games)
            res["mean_q_minus_p_a"] = clustered_mean([r["q"] - r["p_a"] for r in rr], games)
            res["mean_q_minus_p_b"] = clustered_mean([r["q"] - r["p_b"] for r in rr], games)
            cc = [r for r in rr if r["p_c"] is not None]
            if cc:
                res["mean_q_minus_p_c"] = clustered_mean([r["q"] - r["p_c"] for r in cc], [r["game"] for r in cc])
            res["R3_logloss"] = r3_logloss(rr)
            vw = [r for r in rr if r.get("ret_yes") is not None and (r.get("volume") or 0) > 0]
            if vw:
                res["volume_weighted_realised_yes"] = float(np.average([r["ret_yes"] for r in vw],
                                                                       weights=[r["volume"] for r in vw]))
        for side in ("yes", "no"):
            t = r2_test(rr, side)
            res[f"R2_{side}"] = t
            pvals[f"{sport}|{cell}|{side}"] = t["p_holm_input"]
        out["cells"][f"{sport}|{cell}"] = res
    passed = s1.holm(pvals)
    verdicts = []
    for key, ok in passed.items():
        sport, cell, side = key.split("|")
        t = out["cells"][f"{sport}|{cell}"][f"R2_{side}"]
        t["verdict"] = verdict_r2(t, ok)
        verdicts.append(t["verdict"])
    out["holm"] = {"pvals": pvals, "pass": passed}
    out["stage2_overall"] = ("EDGE_FOUND" if "EDGE" in verdicts else
                             "INSUFFICIENT" if set(verdicts) == {"INSUFFICIENT"} else "NO_EDGE_SHOWN")
    return out


def verdict_r2(t: Mapping[str, Any], holm_pass: bool) -> str:
    """A3 §9 R2: EDGE needs min n, CI above 0 and Holm (m = 8); CI above 0 without Holm is a LEAD."""
    if not t.get("sufficient"):
        return "INSUFFICIENT"
    if holm_pass and t["ci"][0] > 0:
        return "EDGE"
    return "LEAD" if t["ci"][0] > 0 else "NO EDGE"


# ----------------------------------------------------------------------------- main
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data-root", default=os.environ.get("SYNDICATE_DATA_ROOT") or "")
    ap.add_argument("--out", required=True)
    ap.add_argument("--cache", required=True)
    ap.add_argument("--funnel-only", action="store_true",
                    help="plumbing check before the run is authorised: write join counts only -- no price, "
                         "probability, outcome or reading is written or printed")
    args = ap.parse_args(argv)
    if not args.data_root:
        print("REFUSING: no --data-root", flush=True)
        return 2
    root = Path(os.path.expanduser(args.data_root))
    cache = Path(args.cache)
    report: dict[str, Any] = {"prereg": "9f8d759e", "amendments": ["A1 83f2e460", "A2 f5a503c6", "A3"],
                              "run_at": datetime.now(UTC).isoformat(), "funnel": {}}
    funnel: Counter = Counter()
    cands = read_candidates(root, funnel)
    report["funnel"]["store"] = dict(funnel)
    print("E4S2_STORE " + json.dumps(dict(funnel)), flush=True)
    meta, mstats = fetch_leg_meta((leg["ticker"] for c in cands for leg in c["legs"]), cache)
    report["leg_meta"] = mstats
    m, m_upper = read_fee_multiplier("KXMVECROSSCATEGORY")
    report["fee"] = {"series": "KXMVECROSSCATEGORY", "multiplier": m, "is_upper_bound": m_upper}
    print(f"E4S2_META {json.dumps(mstats)} fee_multiplier={m} upper_bound={m_upper}", flush=True)
    code_names = soccer_code_names((c["league"], meta[l["ticker"]]) for c in cands if c["sport"] == "soccer"
                                   for l in c["legs"] if l["ticker"] in meta)
    fetch = s1.Fetcher(cache)
    rows: list[dict] = []
    for sport in ("mlb", "nba", "soccer"):
        sc = [c for c in cands if c["sport"] == sport]
        f: Counter = Counter({"candidates": len(sc)})
        if not sc:
            report["funnel"][sport] = dict(f)
            continue
        games, latest, events, gfun = stage1_games(root, fetch, sport)
        f.update({f"stage1_{k}": v for k, v in gfun.items()})
        for g in games:
            g["_event_meta"] = events.get(g["event"]) or {}
        idx = line_index(latest)
        bgames = blob_games(games, events)
        cells_c = {}
        p = root / f"{sport}_source" / "sgp" / f"{sport}_sgp_correlations.json"
        if p.exists():
            cells_c = json.loads(p.read_text(encoding="utf-8"))
        for c in sc:
            legs = [parse_leg(sport, l["ticker"], meta.get(l["ticker"])) for l in c["legs"]]
            if None in legs:
                f["leg_unparsed"] += 1
                continue
            if any(l["side"] not in ("yes", "no") for l in c["legs"]):
                f["leg_side_unknown"] += 1
                continue
            g, why = join_game(c, games, bgames, code_names)
            if g is None:
                f[why] += 1
                continue
            r = price_combo(c, g, legs, idx, cells_c, f)
            if r is None:
                continue
            if (sport, r["cell"]) not in PASSING:
                f[f"not_passing:{r['cell']}"] += 1
                continue
            f["priced"] += 1
            rows.append(r if args.funnel_only else finish_row(r, m, f))
        report["funnel"][sport] = dict(f)
        print(f"E4S2_FUNNEL {sport} " + json.dumps(dict(f)), flush=True)
    if args.funnel_only:
        n = Counter((r["sport"], r["cell"]) for r in rows)
        g = {k: len({r["game"] for r in rows if (r["sport"], r["cell"]) == k}) for k in n}
        report["joined"] = {f"{s}|{c}": {"combos": v, "games": g[(s, c)]} for (s, c), v in sorted(n.items())}
        Path(args.out).write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
        print("E4S2_JOINED " + json.dumps(report["joined"]), flush=True)
        return 0
    report.update(readings(rows))
    report["fetch"] = {"gets": fetch.gets, "fail": fetch.fail}
    Path(args.out).write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
    keys = ["ticker", "sport", "cell", "stat_pair", "game", "date", "q", "volume", "result", "side_a", "side_b",
            "mkt_a", "line_a", "mkt_b", "line_b", "pA", "pB", "yA", "yB", "y_ours", "y_kalshi", "rho_b", "rho_c",
            "p_a", "p_b", "p_c", "fee", "ev_a", "ev_b", "ev_c", "ev_b_no", "ret_yes", "ret_no"]
    with open(Path(args.out).with_suffix(".combos.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=keys, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    for k, v in report["cells"].items():
        print(f"E4S2_CELL {k} combos={v['combos']} games={v['games']} "
              f"R2_yes={v['R2_yes'].get('verdict')} R2_no={v['R2_no'].get('verdict')} "
              f"R1_slope={(v.get('R1_price_tracking') or {}).get('slope')}", flush=True)
    print(f"E4S2_OVERALL {report['stage2_overall']}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
