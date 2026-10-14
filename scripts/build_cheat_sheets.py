"""Build the daily cheat sheets (lane `cheat-sheets`): every pregame prop on the board, with its evidence and a price check.

For each sport: read the served Layer 2 rows, group the props by (game, player, stat), build Syndicate's prop evidence
ONCE per group (`prop_evidence.build_prop_evidence`: model distribution, recent form, matchup, usage, game sim,
environment, track record), and price-check every row in the group (`cheat_sheets.price_check`). NFL rows also get the
opponent's defense-vs-position rank for the player's position; NFL / NCAAF games get the sim's expected script.

Groups are built in priority order (Suggested first, then EV, then books quoting) up to a per-sport cap, because the
evidence costs 1-12 s per group on the fleet (measured 2026-10-14: NFL 0.9, NCAAF 1.8, soccer 1.1, NHL 12).

Writes `<data root>/cheatsheets/<sport>/<date>.json` (atomic). Read-only otherwise; no OddsAPI.

    python3 scripts/build_cheat_sheets.py --data-root ~/syndicate-prod/data --sports nfl,ncaaf,nhl,soccer
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import time
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.shared import cheat_sheets as cs  # noqa: E402

DEFAULT_CAPS = {"nfl": 150, "ncaaf": 80, "soccer": 120, "nhl": 30, "nba": 150, "wnba": 80, "ncaab": 80, "mlb": 100}
NFL_DVP_STAT = {
    "Receiving Yards": "rec_yds", "Receptions": "receptions", "Rushing Yards": "rush_yds",
    "Rushing Attempts": "carries", "Passing Yards": "pass_yds", "Passing TDs": "pass_td",
    "Pass Completions": "completions", "Passing Completions": "completions", "Interceptions": "interceptions",
    "Pass Interceptions": "interceptions", "Pass Attempts": "completions",
}


def central_today() -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=5)).date().isoformat()


def fetch_rows(base_url: str, sport: str) -> list[dict[str, Any]]:
    url = f"{base_url}/api/board/layer2-shortlist?limit=5000&sport={sport}"
    with urllib.request.urlopen(url, timeout=180) as resp:
        doc = json.load(resp)
    return [r for r in doc.get("rows") or [] if isinstance(r, dict)]


def latest_nfl_dvp(data_root: Path) -> dict[str, Any]:
    files = sorted(glob.glob(str(data_root / "nfl_source" / "tracking" / "derived" / "nfl_defense_vs_position_*.json")))
    if not files:
        return {}
    try:
        doc = json.loads(Path(files[-1]).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    doc["_file"] = Path(files[-1]).name
    return doc


def dvp_for(dvp: dict[str, Any], opponent: str | None, pos: str | None, market: str) -> dict[str, Any] | None:
    stat = NFL_DVP_STAT.get(market)
    if not stat or not opponent or not pos:
        return None
    cell = (((dvp.get("teams") or {}).get(opponent) or {}).get(pos) or {}).get(stat)
    if not isinstance(cell, dict):
        return None
    of = cell.get("of") or 32
    # rank 1 = FEWEST allowed. Report "allows the Nth most" so the sheet reads like the touts' and cannot be misread.
    most = (of + 1 - cell["rank"]) if isinstance(cell.get("rank"), int) else None
    return {"stat": stat, "per_game": cell.get("per_game"), "rank_fewest": cell.get("rank"), "nth_most": most, "of": of,
            "games": cell.get("games"), "through_week": dvp.get("through_week")}


def group_rows(rows: list[dict[str, Any]]) -> dict[tuple, list[dict[str, Any]]]:
    groups: dict[tuple, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        if r.get("kind") != "prop" or (r.get("game_state") or "pregame") != "pregame":
            continue
        if str(r.get("segment") or "full") != "full" or not r.get("player_name"):
            continue
        groups[(r.get("event_id"), r.get("player_name"), r.get("market"))].append(r)
    return groups


def priority(rows: list[dict[str, Any]]) -> tuple:
    sug = any(r.get("suggested") for r in rows)
    ev = max((r.get("ev_pct") for r in rows if isinstance(r.get("ev_pct"), (int, float))), default=-99.0)
    books = max((len((r.get("quote") or {}).get("book_prices") or {}) for r in rows), default=0)
    return (sug, ev, books)


def evidence_facts(row: dict[str, Any], selected_date: str) -> dict[str, Any]:
    from syndicate.features.shared.prop_evidence import build_prop_evidence

    out: dict[str, Any] = {}
    try:
        ev = build_prop_evidence(row, selected_date=selected_date)
    except Exception as exc:  # noqa: BLE001 -- one row's evidence must never stop the sheet
        return {"error": f"{type(exc).__name__}: {str(exc)[:160]}"}
    if ev is None:
        return {"error": "no evidence provider"}
    layers = ev.layers if isinstance(ev.layers, dict) else {le.layer: le for le in ev.layers}
    for layer, le in layers.items():
        name = getattr(layer, "value", str(layer))
        if getattr(le, "filled", False):
            out[name] = le.facts or {}
    return out


def news_impact(sport: str, selected_date: str, out_rows: list[dict[str, Any]],
                board_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Material status changes in the last ~36 h (news collector), each with its game's props on the board."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("news_price_follow", REPO_ROOT / "scripts" / "news_price_follow.py")
    npf = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(npf)
    start = (datetime.fromisoformat(selected_date) - timedelta(days=1)).date().isoformat()
    try:
        events = npf.injury_events(news_root, sport, start, selected_date)
    except Exception:  # noqa: BLE001 -- the news section is optional
        return []
    by_team: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in board_rows:
        if r.get("kind") == "prop" and (r.get("game_state") or "pregame") == "pregame":
            for side in ("home_team", "away_team"):
                by_team[str(r.get(side) or "").lower()].append(r)
    out = []
    for ev in sorted(events, key=lambda e: e["t0"], reverse=True)[:40]:
        game_props = by_team.get(str(ev.get("team") or "").lower(), [])
        others = sorted((r for r in game_props if r.get("player_name") != ev["player"]),
                        key=lambda r: -(r.get("ev_pct") or -99))[:5]
        out.append({"player": ev["player"], "team": ev["team"], "kind": ev["kind"], "status": ev.get("status"),
                    "previous_status": ev.get("previous_status"), "captured_at": ev["t0"],
                    "game_props_on_board": len(game_props),
                    "top_game_props": [{"player": r.get("player_name"), "market": r.get("market"), "line": r.get("line"),
                                        "side": r.get("side"), "ev_pct": r.get("ev_pct")} for r in others]})
    return out


news_root: Path | None = None


def build_sport(sport: str, rows: list[dict[str, Any]], *, selected_date: str, cap: int,
                dvp: dict[str, Any]) -> dict[str, Any]:
    t0 = time.time()
    groups = group_rows(rows)
    ordered = sorted(groups.items(), key=lambda kv: priority(kv[1]), reverse=True)[:cap]
    out_rows: list[dict[str, Any]] = []
    games: dict[str, dict[str, Any]] = {}
    for (event_id, player, market), grp in ordered:
        rep = max(grp, key=lambda r: len((r.get("quote") or {}).get("book_prices") or {}))
        facts = evidence_facts(rep, selected_date)
        form = facts.get("recent_form") or {}
        adv = facts.get("advanced") or {}
        match = facts.get("matchup") or {}
        env = facts.get("environment") or {}
        sim = facts.get("game_sim") or {}
        home, away = rep.get("home_team") or "", rep.get("away_team") or ""
        if event_id not in games:
            g = {"event_id": event_id, "matchup": f"{away} @ {home}", "commence_time": rep.get("commence_time")}
            if sport in ("nfl", "ncaaf") and sim:
                margin = sim.get("margin_mean")
                if isinstance(sim.get("home_score_mean"), (int, float)) and isinstance(sim.get("away_score_mean"), (int, float)):
                    margin = sim["home_score_mean"] - sim["away_score_mean"]
                g["script"] = cs.game_script({**sim, "margin_mean": margin}, home, away)
            games[event_id] = g
        dvp_cell = dvp_for(dvp, match.get("opponent"), adv.get("pos"), market) if sport == "nfl" else None
        for code in (adv.get("team"), match.get("opponent")):
            if isinstance(code, str) and code:
                games[event_id].setdefault("team_codes", set()).add(code)
        for r in grp:
            check = cs.price_check(r, form.get("values"))
            quote = r.get("quote") or {}
            out_rows.append({
                "event_id": event_id, "player": player, "team": adv.get("team") or (r.get("projection") or {}).get("player_team"),
                "pos": adv.get("pos"), "market": market, "line": r.get("line"), "side": r.get("side"),
                "suggested": bool(r.get("suggested")), "books_quoting": len(quote.get("book_prices") or {}),
                "book_prices": dict(sorted((quote.get("book_prices") or {}).items(), key=lambda kv: -kv[1])[:6]),
                "opponent": match.get("opponent"), "dvp": dvp_cell,
                "form_labels": (form.get("game_labels") or [])[:10],
                "injury": env.get("player_injury_status"),
                "shop": cs.shop_gap(quote.get("book_prices")),
                "evidence_error": facts.get("error"),
                "check": check.as_dict(),
            })
    for g in games.values():
        codes = sorted(g.pop("team_codes", set()))
        if sport == "nfl" and dvp.get("teams"):
            g["defense_allows_most"] = {c: cs.dvp_extremes(dvp["teams"], c) for c in codes if c in dvp["teams"]}
    sheet = {
        "schema": "cheat_sheet_v1", "sport": sport, "date": selected_date,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "groups_on_board": len(groups), "groups_built": len(ordered), "rows": out_rows,
        "games": list(games.values()), "sections": cs.sections(out_rows),
        "dvp_file": dvp.get("_file") if sport == "nfl" else None,
        "method": {"prior_strength_k": cs.PRIOR_STRENGTH, "k_is_provisional": cs.K_IS_PROVISIONAL, "streak_rate": cs.STREAK_RATE,
                   "streak_min_games": cs.STREAK_MIN_GAMES, "value_ev_pct": cs.VALUE_EV_PCT},
        "news": news_impact(sport, selected_date, out_rows, rows) if news_root else [],
        "build_seconds": round(time.time() - t0, 1),
    }
    return sheet


def write_atomic(path: Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(doc, default=str), encoding="utf-8")
    os.replace(tmp, path)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data-root", default=os.environ.get("SYNDICATE_DATA_ROOT") or "")
    ap.add_argument("--sports", default="nfl,ncaaf,nhl,soccer,nba,wnba,ncaab")
    ap.add_argument("--date", default=None, help="selected date (default: today, US Central)")
    ap.add_argument("--base-url", default=os.environ.get("SYNDICATE_BASE_URL") or "http://127.0.0.1:10000")
    ap.add_argument("--cap", type=int, default=None, help="override the per-sport group cap")
    args = ap.parse_args(argv)
    if not args.data_root:
        print("REFUSING: no --data-root", flush=True)
        return 2
    data_root = Path(os.path.expanduser(args.data_root))
    selected = args.date or central_today()
    dvp = latest_nfl_dvp(data_root)
    global news_root
    news_root = data_root if (data_root / "news").is_dir() else None
    for sport in [s.strip() for s in args.sports.split(",") if s.strip()]:
        try:
            rows = fetch_rows(args.base_url, sport)
        except Exception as exc:  # noqa: BLE001
            print(f"CHEAT_SHEET {sport} fetch failed: {type(exc).__name__}: {exc}", flush=True)
            continue
        sheet = build_sport(sport, rows, selected_date=selected, cap=args.cap or DEFAULT_CAPS.get(sport, 80), dvp=dvp)
        if not sheet["rows"]:
            print(f"CHEAT_SHEET {sport} date={selected} no pregame props on the board -- nothing written", flush=True)
            continue
        write_atomic(data_root / "cheatsheets" / sport / f"{selected}.json", sheet)
        counts = {k: len(v) for k, v in sheet["sections"].items()}
        print(f"CHEAT_SHEET {sport} date={selected} groups={sheet['groups_built']}/{sheet['groups_on_board']} "
              f"rows={len(sheet['rows'])} sections={counts} secs={sheet['build_seconds']}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
