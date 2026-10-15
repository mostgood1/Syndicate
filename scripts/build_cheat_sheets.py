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
import re
import statistics
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
# Season phases (US Central dates). A sheet is built in the regular season AND the postseason, labelled with its
# phase -- the price check is phase-free, and form is what the player actually did. Preseason gets no sheet: its
# minutes and lineups are a different population (learnings: season-phase models). User 2026-10-14: "why isnt there
# an MLB cheat for today" -- the first version gated to regular seasons only and so skipped the MLB playoffs.
# Sports not listed (soccer: domestic leagues all year) are never gated. Extend each season here.
SEASON_PHASES = {
    "nfl": (("2026-09-10", "2027-01-10", "regular"), ("2027-01-16", "2027-02-14", "postseason")),
    "ncaaf": (("2026-08-29", "2026-12-12", "regular"), ("2026-12-13", "2027-01-20", "postseason")),
    "nhl": (("2026-10-06", "2027-04-17", "regular"), ("2027-04-18", "2027-06-25", "postseason")),
    "nba": (("2026-10-20", "2027-04-11", "regular"), ("2027-04-14", "2027-06-25", "postseason")),
    "ncaab": (("2026-11-02", "2027-03-15", "regular"), ("2027-03-16", "2027-04-06", "postseason")),
    "wnba": (("2027-05-14", "2027-09-12", "regular"), ("2027-09-13", "2027-10-25", "postseason")),
    "mlb": (("2026-09-29", "2026-11-05", "postseason"), ("2027-03-25", "2027-09-26", "regular"),
            ("2027-09-27", "2027-11-05", "postseason")),
}
NFL_DVP_STAT = {
    "Receiving Yards": "rec_yds", "Receptions": "receptions", "Rushing Yards": "rush_yds",
    "Rushing Attempts": "carries", "Passing Yards": "pass_yds", "Passing TDs": "pass_td",
    "Pass Completions": "completions", "Passing Completions": "completions", "Interceptions": "interceptions",
    "Pass Interceptions": "interceptions", "Pass Attempts": "completions",
}


def central_today() -> str:
    return cs_central(datetime.now(timezone.utc)).date().isoformat()


def cs_central(moment: datetime) -> datetime:
    from syndicate.features.shared.play_cards import central

    return central(moment)


def central_day(commence: Any) -> str | None:
    """The game's date in US Central -- the day whose sheet it belongs to."""
    try:
        return cs_central(datetime.fromisoformat(str(commence).replace("Z", "+00:00"))).date().isoformat()
    except (TypeError, ValueError):
        return None


def season_phase(sport: str, day: str) -> str | None:
    """'regular' / 'postseason' for a sport on a day, 'regular' when the sport is not gated, None outside both."""
    windows = SEASON_PHASES.get(sport)
    if windows is None:
        return "regular"
    return next((phase for start, end, phase in windows if start <= day <= end), None)


def in_season(sport: str, day: str) -> bool:
    return season_phase(sport, day) is not None


def kickoff_ct(commence: Any) -> str | None:
    """'Sun Oct 18 · 3:05 PM CT' -- the game's date and time in US Central (DST-aware where tzdata exists)."""
    from syndicate.features.shared.play_cards import kickoff_label

    return kickoff_label(commence) or None


def _position_indexes() -> dict[str, Any]:
    """Roster positions the evidence layer does not carry: NHL (F/D/G), NCAAF (by team), soccer (G/D/M/F).

    The same files and the same drop-don't-guess rule as `player_headshots` (a name on two players is dropped)."""
    from syndicate.features.shared import player_headshots as ph

    nhl = ph._unique((ph._norm(r.get("full_name")), str(r.get("position") or "").strip()) for r in ph._nhl_rows())
    ncaaf: dict[tuple[str, str], str] = {}
    for root in ph._roots("ncaaf"):
        roster = Path(root) / "source_artifacts" / "data" / "processed" / "roster" / "ncaaf_roster_snapshot.csv"
        if roster.exists():
            for r in ph._read_csv(roster):
                key = (str(r.get("team_id") or "").strip(), ph._norm(r.get("player_name")))
                if key[1] and str(r.get("position") or "").strip():
                    ncaaf.setdefault(key, str(r["position"]).strip())
            break
    soccer: dict[tuple[str, str], str] = {}
    for root in ph._roots("soccer"):
        files = sorted(Path(root).glob("*/api/rosters/rosters_*.csv"))
        for path in files:
            for r in ph._read_csv(path):
                pos = str(r.get("position_abbreviation") or r.get("position") or "").strip()
                if pos:
                    soccer.setdefault((ph._norm(r.get("team")), ph._norm(r.get("player_name"))), pos)
        if files:
            break
    return {"nhl": nhl, "ncaaf": ncaaf, "soccer": soccer}


def player_identity(row: dict[str, Any], *, sport: str, team: Any, pos: Any, context: dict[str, Any],
                    positions: dict[str, Any]) -> dict[str, Any]:
    """Headshot, which side the player is on, his team (name + logo), position, and the opponent's logo.

    Every lookup is name-based and drops ambiguity rather than guessing (a wrong face or crest reads as a wrong bet).
    `team` / `pos` from the evidence layer win; the rosters only fill what it left empty."""
    from syndicate.features.shared import player_headshots as ph
    from syndicate.features.shared.layer2_row_context import row_identity
    from syndicate.features.shared.team_logos import logo_url

    out: dict[str, Any] = {"headshot_url": None, "player_side": None, "team_name": None, "team_logo": None,
                           "opponent_name": None, "opponent_logo": None, "team": team, "pos": pos}
    try:
        ident = row_identity({**row, "sport": sport}, context)
    except Exception:  # noqa: BLE001 -- identity is decoration; it must never cost the sheet
        ident = {}
    out["headshot_url"] = ident.get("headshot_url")
    side = ident.get("player_side")
    if side not in ("home", "away") and team:
        # The evidence layer's team ("Sam Houston") is the short name of one side ("Sam Houston State Bearkats"):
        # match it by logo, else as the unique side whose name starts with it.
        mine = logo_url(sport, team)
        hits = [s for s in ("home", "away") if (mine and mine == logo_url(sport, row.get(f"{s}_team"), row.get(f"{s}_key")))
                or ph._norm(row.get(f"{s}_team")).startswith(ph._norm(team))]
        side = hits[0] if len(hits) == 1 else None
    out["player_side"] = side
    if side in ("home", "away"):
        other = "away" if side == "home" else "home"
        out["team_name"], out["opponent_name"] = row.get(f"{side}_team"), row.get(f"{other}_team")
        out["team_logo"] = logo_url(sport, out["team_name"], row.get(f"{side}_key"))
        out["opponent_logo"] = logo_url(sport, out["opponent_name"], row.get(f"{other}_key"))
        out["team"] = out["team"] or out["team_name"]
    name = ph._norm(row.get("player_name"))
    if not out["pos"]:
        if sport == "nhl":
            out["pos"] = positions.get("nhl", {}).get(name) or None
        elif sport == "ncaaf" and out["team_name"]:
            tid = ph._ncaaf_index()[2].get(ph._norm(out["team_name"]))
            out["pos"] = positions.get("ncaaf", {}).get((tid or "", name)) or None
        elif sport == "soccer" and out["team_name"]:
            out["pos"] = positions.get("soccer", {}).get((ph._norm(out["team_name"]), name)) or None
    return out


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


def _parse_ts(value: Any) -> datetime | None:
    try:
        t = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


STALE_LINE_MINUTES = 30


def quote_rows(data_root: Path, sport: str, day: str, *, skip_events: set[str], now: datetime) -> list[dict[str, Any]]:
    """Board-shaped pregame prop rows REBUILT from the quote logs, for `day`'s games that have STARTED.

    A game that kicked off before any sheet priced it (user 2026-10-14: "make sure we have sheets for each possible
    sport for 10-14") gets each book's LAST quote at or before kickoff; each book's two-sided pair is Shin-devigged
    and the fair is the median across books; the price is the best book's. A one-sided market (an anytime scorer) has
    no pair to devig and is left out rather than given an assumed hold. These rows carry no model projection."""
    import importlib.util

    from syndicate.features.shared.opportunity_signals import devig

    spec = importlib.util.spec_from_file_location("news_price_follow", REPO_ROOT / "scripts" / "news_price_follow.py")
    npf = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(npf)
    latest: dict[tuple, tuple[datetime, dict[str, Any]]] = {}
    book_last: dict[tuple, datetime] = {}
    games: dict[str, dict[str, Any]] = {}
    for q in npf.load_quotes(data_root, sport, day, day):
        if q.get("kind") != "prop" or str(q.get("segment") or "full") != "full" or not q.get("player_name"):
            continue
        event = str(q.get("event_id"))
        start, ts = _parse_ts(q.get("commence_time")), _parse_ts(q.get("captured_at"))
        if event in skip_events or start is None or ts is None or ts > start or start > now:
            continue
        if central_day(q.get("commence_time")) != day:
            continue
        key = (event, q.get("market"), q.get("player_name"), q.get("line"), q.get("bookmaker"), str(q.get("selection") or "").lower())
        if key not in latest or ts >= latest[key][0]:
            latest[key] = (ts, q)
        book_key = (event, q.get("market"), q.get("player_name"), q.get("bookmaker"))
        book_last[book_key] = max(book_last.get(book_key, ts), ts)
        games.setdefault(event, q)
    books: dict[tuple, dict[str, dict[str, float]]] = defaultdict(lambda: defaultdict(dict))
    for (event, market, player, line, book, side), (ts, q) in latest.items():
        # A book that MOVED its line leaves its old line's last quote in the log, and that stale price reads as a big
        # "edge" (Snell K under 5.5 at +178 = +16%, 10-14). Keep a book's line only if it was quoted within
        # STALE_LINE_MINUTES of that book's last update for the player + market -- the line it was still offering.
        if ts < book_last[(event, market, player, book)] - timedelta(minutes=STALE_LINE_MINUTES):
            continue
        books[(event, market, player, line)][book][side] = float(q["price"])
    rows = []
    for (event, market, player, line), by_book in books.items():
        sides = sorted({side for prices in by_book.values() for side in prices})
        if len(sides) != 2:
            continue
        fairs: dict[str, list[float]] = {side: [] for side in sides}
        for prices in by_book.values():
            if len(prices) == 2:
                for side, prob in zip(sides, devig([prices[x] for x in sides], method="shin") or []):
                    fairs[side].append(prob)
        if not fairs[sides[0]]:
            continue
        g = games[event]
        for side in sides:
            quoted = {book: prices[side] for book, prices in by_book.items() if side in prices}
            best = max(quoted, key=lambda b: cs.decimal_odds(quoted[b]))
            fair = statistics.median(fairs[side])
            rows.append({
                "kind": "prop", "game_state": "pregame", "segment": "full", "sport": sport, "event_id": event,
                "player_name": player, "market": market, "line": line, "side": side, "home_team": g.get("home_team"),
                "away_team": g.get("away_team"), "commence_time": g.get("commence_time"), "projection": {}, "rebuilt": True,
                "ev_pct": round(100 * (fair * cs.decimal_odds(quoted[best]) - 1), 2),
                "quote": {"price": quoted[best], "bookmaker": best, "fair_probability": fair,
                          "fair_method": "shin_last_pregame_quotes", "book_prices": quoted},
            })
    return rows


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
PVP_SPORTS = ("mlb", "nhl", "nba", "nfl")


def align_data_root(data_root: Path) -> str | None:
    """Make the evidence layer read the SAME data root as `--data-root`, or say why not.

    The evidence layer finds its data through SYNDICATE_DATA_ROOT, not through `--data-root`. A hand run without it
    (2026-10-15) read the checkout's `data/` mirror and wrote sheets with no positions, no matchups and no player
    profiles -- and no error, because every layer reported a clean `absent_reason`. So an unset variable is set from
    `--data-root`, and one that names a DIFFERENT root is refused rather than silently mixed."""
    env_root = os.environ.get("SYNDICATE_DATA_ROOT")
    if env_root and Path(os.path.expanduser(env_root)).resolve() != Path(data_root).resolve():
        return f"SYNDICATE_DATA_ROOT={env_root} names a different root than --data-root {data_root}"
    os.environ["SYNDICATE_DATA_ROOT"] = str(data_root)
    return None


_NAME_SUFFIX = frozenset({"jr", "sr", "ii", "iii", "iv", "v"})


def _initial_last(name: Any) -> str:
    """'Zack Bolduc' / 'Zachary Bolduc' -> 'zbolduc'; suffixes ignored ('Jr.'); '' for a one-word name."""
    import unicodedata

    text = unicodedata.normalize("NFKD", str(name or "")).encode("ascii", "ignore").decode().lower()
    parts = [p for p in re.findall(r"[a-z][a-z'\-]*", text) if p.strip(".") not in _NAME_SUFFIX]
    return re.sub(r"[^a-z]", "", parts[0][:1] + parts[-1]) if len(parts) >= 2 else ""


IDENTITY_SPORTS = ("mlb", "nhl", "soccer", "nba", "wnba")
INDEX_FACE_SPORTS = ("nhl", "soccer", "nba", "wnba")   # name-only lookups in player_headshots (NCAAF needs the teams)
MLB_FACE = "https://img.mlbstatic.com/mlb-photos/image/upload/w_360,q_auto:best/v1/people/{id}/headshot/67/current"
NHL_FACE = "https://assets.nhle.com/mugs/nhl/latest/{id}.png"


def fill_identity(sport: str, rows: list[dict[str, Any]], date: str, cache: Path) -> dict[str, int]:
    """Faces and positions from the day's league rosters, for rows that have none -- the faces on the sheets AND on
    the play cards built from them (users 2026-10-15: "fix the MLB headshots", "add player headshots to the play
    cards too").

    MLB: the board carries a player id only on props the sim projected, and a sheet rebuilt from quotes carries none
    (10-14: a face on 60 of 214 rows, a position on none). NHL: the board's roster snapshot misses traded players.
    The rosters are the ones player-vs-player already fetches, cached for the day. Fills only what is empty; a name on
    two rosters is left alone. MLB faces are asked for at 360 px -- the board's 180 px is upscaled on a 260 px card.
    Rows kept from an earlier build also get a second look in the board's own index (`player_headshots`), so a lookup
    fix reaches the day's record and not only rows built after it."""
    filled = {"headshots": 0, "positions": 0}
    if sport in INDEX_FACE_SPORTS:
        from syndicate.features.shared import player_headshots as ph

        for r in rows:
            if not r.get("headshot_url"):
                url = ph.headshot_url({"sport": sport, "player_name": r.get("player")})
                if url:
                    r["headshot_url"] = url
                    filled["headshots"] += 1
    try:
        if sport == "mlb":
            from syndicate.features.mlb import batter_vs_pitcher as mod

            ids, face = mod.player_ids(mod.StatsApi(cache), date), MLB_FACE
        elif sport == "nhl":
            from syndicate.features.nhl import skater_vs_goalie as mod

            ids, face = mod.player_ids(mod.NhlApi(cache, cache.parent.parent / ".nhl_pbp"), date), NHL_FACE
        else:
            return filled
    except Exception as exc:  # noqa: BLE001 -- a missing face is a crest on the page, never a failed sheet
        print(f"CHEAT_SHEET {sport} roster ids failed: {type(exc).__name__}: {exc}", flush=True)
        return filled
    # A book's "Zack Bolduc" is the roster's "Zachary Bolduc": a second key, first initial + last name, used only when
    # exactly ONE player on the day's rosters carries it.
    by_initial: dict[str, Any] = {}
    for who in ids.values():
        key = _initial_last(who.get("name"))
        if key:
            by_initial[key] = None if key in by_initial else who
    for r in rows:
        if sport == "mlb" and "mlbstatic.com" in str(r.get("headshot_url") or "") and "/w_180," in r["headshot_url"]:
            r["headshot_url"] = r["headshot_url"].replace("/w_180,", "/w_360,")
        who = ids.get(mod._norm(r.get("player"))) or by_initial.get(_initial_last(r.get("player")))
        if not who:
            continue
        if not r.get("headshot_url") and str(who.get("id") or "").isdigit():
            r["headshot_url"] = face.format(id=int(who["id"]))
            filled["headshots"] += 1
        if not r.get("pos") and who.get("position"):
            r["pos"] = who["position"]
            filled["positions"] += 1
    return filled


def player_vs_player(sport: str, rows: list[dict[str, Any]], date: str, cache: Path) -> tuple[Any, dict]:
    """(module, {(normalized player, market): block}) for a sport's player-vs-player source. `cache` is
    `<data root>/cheatsheets/.<sport>_cache/<date>`; long-lived caches sit beside it under `cheatsheets/`."""
    if sport == "mlb":
        from syndicate.features.mlb import batter_vs_pitcher as mod

        return mod, mod.matchups(rows, date=date, api=mod.StatsApi(cache))
    if sport == "nhl":
        from syndicate.features.nhl import skater_vs_goalie as mod

        return mod, mod.matchups(rows, date=date, api=mod.NhlApi(cache, cache.parent.parent / ".nhl_pbp"))
    if sport == "nba":
        from syndicate.features.nba import defender_matchups as mod

        return mod, mod.matchups(rows, date=date, api=mod.NbaApi(cache, cache.parent.parent / ".nba_seasons"))
    if sport == "nfl":
        from syndicate.features.nfl import defender_matchups as mod

        return mod, mod.matchups(rows, date=date, source=mod.Source(cache.parent.parent.parent, date))
    return None, {}


def build_sport(sport: str, rows: list[dict[str, Any]], *, selected_date: str, cap: int,
                dvp: dict[str, Any], context: dict[str, Any] | None = None,
                positions: dict[str, Any] | None = None, pvp_cache: Path | None = None) -> dict[str, Any]:
    from syndicate.features.shared.team_logos import logo_url

    t0 = time.time()
    # A day's sheet holds that day's games only (US Central), user 2026-10-14: "All cheat sheets should be for the
    # current day only". Sunday's NFL props wait for Sunday's sheet.
    rows = [r for r in rows if central_day(r.get("commence_time")) == selected_date]
    groups = group_rows(rows)
    ordered = sorted(groups.items(), key=lambda kv: priority(kv[1]), reverse=True)[:cap]
    out_rows: list[dict[str, Any]] = []
    games: dict[str, dict[str, Any]] = {}
    # Game lines: every pregame full-game spread / moneyline / total the board prices today (user 2026-10-15: "we also
    # need game lines/ml/totals as a cheat sheet"). No evidence call -- the board row already carries the model and
    # the sim projection.
    game_lines: list[dict[str, Any]] = []
    for r in rows:
        if r.get("kind") != "game" or (r.get("game_state") or "pregame") != "pregame":
            continue
        if str(r.get("segment") or "full") != "full" or r.get("market") not in cs.GAME_MARKETS:
            continue
        event_id = r.get("event_id")
        home, away = r.get("home_team") or "", r.get("away_team") or ""
        if event_id not in games:
            games[event_id] = {"event_id": event_id, "matchup": f"{away} @ {home}", "commence_time": r.get("commence_time"),
                               "kickoff_ct": kickoff_ct(r.get("commence_time")), "home_team": home, "away_team": away,
                               "home_logo": logo_url(sport, home, r.get("home_key")),
                               "away_logo": logo_url(sport, away, r.get("away_key")), "rebuilt": bool(r.get("rebuilt"))}
        quote = r.get("quote") or {}
        proj = r.get("projection") or {}
        side = str(r.get("side") or "")
        side_name = home if side == "home" else away if side == "away" else side
        game_lines.append({
            "event_id": event_id, "market": r.get("market"), "side": side, "side_name": side_name, "line": r.get("line"),
            "books_quoting": len(quote.get("book_prices") or {}), "shop": cs.shop_gap(quote.get("book_prices")),
            "suggested": bool(r.get("suggested")), "fair_method": quote.get("fair_method"),
            "projected": proj.get("projected"), "projection_basis": proj.get("basis"), "projection_side": proj.get("side"),
            "commence_time": r.get("commence_time"), "kickoff_ct": games[event_id]["kickoff_ct"],
            "check": cs.game_line_check(r),
        })
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
            g = {"event_id": event_id, "matchup": f"{away} @ {home}", "commence_time": rep.get("commence_time"),
                 "kickoff_ct": kickoff_ct(rep.get("commence_time")), "home_team": home, "away_team": away,
                 "home_logo": logo_url(sport, home, rep.get("home_key")), "away_logo": logo_url(sport, away, rep.get("away_key")),
                 "rebuilt": bool(rep.get("rebuilt"))}
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
        ident = player_identity(rep, sport=sport, team=adv.get("team") or (rep.get("projection") or {}).get("player_team"),
                                pos=adv.get("pos"), context=context or {}, positions=positions or {})
        for r in grp:
            check = cs.price_check(r, form.get("values"))
            quote = r.get("quote") or {}
            out_rows.append({
                "event_id": event_id, "player": player, "team": ident["team"], "pos": ident["pos"],
                "team_name": ident["team_name"], "team_logo": ident["team_logo"], "headshot_url": ident["headshot_url"],
                "opponent_logo": ident["opponent_logo"], "kickoff_ct": games[event_id]["kickoff_ct"],
                "commence_time": rep.get("commence_time"), "market": market, "line": r.get("line"), "side": r.get("side"),
                "suggested": bool(r.get("suggested")), "books_quoting": len(quote.get("book_prices") or {}),
                "book_prices": dict(sorted((quote.get("book_prices") or {}).items(), key=lambda kv: -kv[1])[:6]),
                "opponent": match.get("opponent") or ident["opponent_name"], "dvp": dvp_cell,
                "matchup": cs.matchup_summary(sport, match, dvp_cell),
                "vs_opponent": cs.vs_opponent_record(match, r.get("line"), r.get("side")),
                "matchup_ratings": ({"opp_xga": (match.get("opponent_rating") or {}).get("xg_against_per_match"),
                                     "opp_ga": (match.get("opponent_rating") or {}).get("goals_against_per_match")}
                                    if sport == "soccer" and match.get("opponent_rating") else None),
                "form_labels": (form.get("game_labels") or [])[:10],
                "injury": env.get("player_injury_status"),
                "shop": cs.shop_gap(quote.get("book_prices")),
                "fair_method": quote.get("fair_method"),
                "evidence_error": facts.get("error"),
                "check": check.as_dict(),
            })
    # Player vs player (user 2026-10-15: "add player vs player matchups like batter vs pitcher"): MLB batter vs the
    # probable starter, pitcher vs the opposing roster -- StatsAPI, cached for the day on the data root.
    # NHL (user 2026-10-15: "add skater vs goalie for NHL"): skater vs the opposing likely starter, goalie vs today's
    # opponent -- the NHL's public API; finished games' shot lists cached for good.
    # NBA / NFL (user 2026-10-15: "add defender matchups for NFL and NBA"): who guarded him (NBA.com tracking); plays
    # on the ball by today's defenders (nflverse play-by-play on the data root -- NOT coverage, see the module).
    if sport in PVP_SPORTS and out_rows and pvp_cache is not None:
        try:
            pvp_mod, pvp = player_vs_player(sport, out_rows, selected_date, pvp_cache)
        except Exception as exc:  # noqa: BLE001 -- a missing matchup is a blank cell, never a failed sheet
            print(f"CHEAT_SHEET {sport} player-vs-player failed: {type(exc).__name__}: {exc}", flush=True)
            pvp, pvp_mod = {}, None
        for r in out_rows:
            r["pvp"] = pvp.get((pvp_mod._norm(r.get("player")), str(r.get("market") or "").strip().lower())) if pvp_mod else None
    for g in games.values():
        codes = sorted(g.pop("team_codes", set()))
        if sport == "nfl" and dvp.get("teams"):
            g["defense_allows_most"] = {c: cs.dvp_extremes(dvp["teams"], c) for c in codes if c in dvp["teams"]}
    sheet = {
        "schema": "cheat_sheet_v1", "sport": sport, "date": selected_date,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "groups_on_board": len(groups), "groups_built": len(ordered), "rows": out_rows,
        "games": list(games.values()), "sections": cs.sections(out_rows), "game_lines": game_lines,
        "dvp_file": dvp.get("_file") if sport == "nfl" else None,
        "method": {"prior_strength_k": cs.PRIOR_STRENGTH, "k_is_provisional": cs.K_IS_PROVISIONAL, "streak_rate": cs.STREAK_RATE,
                   "streak_min_games": cs.STREAK_MIN_GAMES, "value_ev_pct": cs.VALUE_EV_PCT},
        "news": news_impact(sport, selected_date, out_rows, rows) if news_root else [],
        "build_seconds": round(time.time() - t0, 1),
    }
    return sheet


IMAGE_FIELDS = (
    ("rows", (("headshot_url", "headshot_src", 96), ("headshot_url", "headshot_card_src", 260),
              ("team_logo", "team_logo_src", 96), ("opponent_logo", "opponent_logo_src", 96))),
    ("games", (("home_logo", "home_logo_src", 96), ("away_logo", "away_logo_src", 96))),
    ("picks", (("headshot_url", "headshot_src", 96), ("headshot_url", "headshot_card_src", 260),
               ("team_logo", "team_logo_src", 96), ("home_logo", "home_logo_src", 96), ("away_logo", "away_logo_src", 96))),
)


def fetch_board_cards(base_url: str) -> list[dict[str, Any]]:
    """The Layer 2 board's own cards -- the request the board page makes (templates/intelligence.html,
    `intelligenceQueryPayload`) -- so a promoted pick is exactly what the board shows, with its written case."""
    body = {"question": "top edges today", "mode": "recommendation", "timing": "all", "background": False,
            "force_refresh": False, "slim_aliases": False, "drop_row_diagnostics": True}
    req = urllib.request.Request(f"{base_url}/api/intelligence/query", data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as resp:
        doc = json.load(resp)
    cards = (((doc.get("response") or {}).get("board_contract") or {}).get("cards")) or []
    return [c for c in cards if isinstance(c, dict)]


def build_picks(cards: list[dict[str, Any]], sheet: dict[str, Any], *, sport: str, day: str, now: datetime) -> list[dict[str, Any]]:
    """The board's suggested opps for this sport's games on `day` (user 2026-10-15: "add the suggested opps as a picks
    section with pick graphics"), each with its crests and, for a prop the sheet also prices, the sheet row's team."""
    from syndicate.features.shared.team_logos import logo_url

    rows_by_key = {cs.prop_result_key(r): r for r in sheet.get("rows") or []}
    out = []
    for card in cs.select_picks(cards, sport=sport, day=day):
        pick = cs.pick_record(card, promoted_at=now.isoformat(timespec="seconds"))
        pick["home_logo"], pick["away_logo"] = logo_url(sport, pick.get("home_team")), logo_url(sport, pick.get("away_team"))
        if pick.get("kind") == "prop":
            row = rows_by_key.get(cs.prop_result_key({"player": pick["player_name"], "market": pick["market"],
                                                      "side": pick["side"], "line": pick["line"]}))
            if row:
                pick.update({"team": row.get("team"), "pos": row.get("pos"), "team_logo": row.get("team_logo"),
                             "headshot_url": pick.get("headshot_url") or row.get("headshot_url"), "card_row": True})
        else:   # a side's crest; a total (no side) wears the home crest
            pick["team_logo"] = logo_url(sport, card.get("display_name")) or pick["home_logo"]
        if "mlbstatic.com" in str(pick.get("headshot_url") or "") and "/w_180," in pick["headshot_url"]:
            pick["headshot_url"] = pick["headshot_url"].replace("/w_180,", "/w_360,")
        pick["kickoff_ct"] = kickoff_ct(pick.get("commence_time"))
        out.append(pick)
    return out


_PICK_PRESENTATION = ("display_name", "detail", "team_logo", "home_logo", "away_logo", "headshot_url",
                      "team", "pos", "kickoff_ct", "segment_label", "bet", "player_id") + cs.PICK_RECENT_FIELDS


# The board's MLB pitcher markets ("strikeouts", "outs", ...) against the names `intelligence_recent_matchup` keys
# its game-log columns on ("pitcher_strikeouts", ...). Measured 2026-10-15: 0 of the board's 11 pitcher props carried
# recent games because of the mismatch -- every batter market matched.
MLB_PITCHER_MARKETS = {"strikeouts": "pitcher_strikeouts", "outs": "pitcher_outs", "hits_allowed": "pitcher_hits_allowed",
                       "earned_runs": "pitcher_earned_runs", "walks_allowed": "pitcher_walks"}


def fill_pick_history(pick: dict[str, Any], *, day: str, intervals: Any) -> str | None:
    """The recent games a pick's case reads, filled at build time when the board card did not carry them (user
    2026-10-15: "we should fix the gaps - for example we need the interval data"): a prop's last games from the
    board's own provider (`intelligence_recent_matchup`, the sentence behind the card's Recent form), a full-game
    pick's team scores (`team_recent_results`), and a SEGMENT pick's interval scores (`interval_history`). What
    filled it, or None. A provider that fails leaves the pick as it was -- a gap, never a broken sheet."""
    sport, when = str(pick.get("sport") or "").lower(), pick.get("commence_time") or day
    try:
        if pick.get("kind") == "prop":
            if pick.get("recent_values"):
                return None
            from syndicate.features.intelligence_recent_matchup import prop_recent_matchup_text, recent_values_for

            player_id = pick.get("player_id")
            if not player_id and (m := re.search(r"/people/(\d+)/", str(pick.get("headshot_url") or ""))):
                player_id = m.group(1)                # an MLB pick promoted before its id was kept
            row = {k: pick.get(k) for k in ("sport", "player_name", "market", "side", "line", "event_id",
                                            "commence_time", "home_team", "away_team")}
            row.update({"kind": "prop", "player_id": player_id})
            if sport == "mlb":   # the board names pitcher markets bare; the provider's log keys are prefixed
                row["market"] = MLB_PITCHER_MARKETS.get(str(row.get("market") or "").lower(), row.get("market"))
            prop_recent_matchup_text(row, selected_date=day)
            recent = recent_values_for(row) or {}
            values = list(recent.get("values") or [])[:10]
            if not values:
                return None
            pick["recent_values"] = values
            for src, dst in (("dates", "recent_dates"), ("opponents", "recent_opponents")):
                labels = recent.get(src)
                if isinstance(labels, (list, tuple)) and len(labels) >= len(values):
                    pick[dst] = [str(x) for x in list(labels)[: len(values)]]
            return "prop_recent"
        segment = cs.full_segment(pick.get("segment"))
        if pick.get("team_recent") and cs.full_segment(pick.get("team_recent_segment")) == segment:
            return None
        if segment == "full":
            from syndicate.features.shared.team_recent_results import is_score_market, team_recent_results

            if not is_score_market(pick.get("market")):
                return None
            home = team_recent_results(sport, pick.get("home_team"), when)
            away = team_recent_results(sport, pick.get("away_team"), when)
        else:
            if intervals is None:
                return None
            home = intervals.team_results(sport, pick.get("home_team"), when, segment)
            away = intervals.team_results(sport, pick.get("away_team"), when, segment)
    except Exception as exc:  # noqa: BLE001
        print(f"CHEAT_SHEET pick history {pick.get('pick_id')} failed: {type(exc).__name__}: {exc}", flush=True)
        return None
    if not (home or away):
        return None
    pick["team_recent"], pick["team_recent_segment"] = {"home": home, "away": away}, segment
    return f"team_{segment}"


def merge_picks(fresh: list[dict[str, Any]], prior: dict[str, Any] | None, *, rows: list[dict[str, Any]] | None = None,
                cards: list[dict[str, Any]] | None = None, day: str | None = None, intervals: Any = None) -> list[dict[str, Any]]:
    """A day's picks are a RECORD: one promoted earlier keeps its first price and stays when the board drops it later
    (its line moved, its game started); a new one joins. Board score order, earliest promotions first on ties."""
    kept = {p.get("pick_id"): dict(p) for p in (prior or {}).get("picks") or [] if p.get("pick_id")}
    on_board = {c.get("pick_id"): c for c in cards or [] if c.get("pick_id")}
    for p in fresh:
        if p.get("pick_id") in kept:
            # The PRICE is frozen at first promotion; how the pick READS (its name, its case, its crests, its recent
            # games) follows the board while the board still carries it.
            kept[p["pick_id"]].update({k: p[k] for k in _PICK_PRESENTATION if p.get(k) is not None})
        else:
            kept[p.get("pick_id")] = p
    # Whether the board STILL suggests it at this build: the suggested set moves with prices within minutes
    # (measured 2026-10-15: 3 of 7 dropped and 1 joined between a build and the next read), and a pick the board
    # no longer backs must say so before anyone posts it.
    live = {p.get("pick_id") for p in fresh}
    for pick_id, p in kept.items():
        p["on_board"] = pick_id in live
        card = on_board.get(pick_id)
        if card is not None and pick_id not in live:     # still on the board, just not suggested: its games still read
            p.update({k: card[k] for k in cs.PICK_RECENT_FIELDS if card.get(k)})
        if p.get("kind") != "prop" and str(p.get("market") or "").startswith(("totals", "alternate_totals")) and p.get("matchup"):
            p["display_name"] = p["matchup"]          # a total reads by its game
            p["team_logo"] = p.get("team_logo") or p.get("home_logo")
        if day:
            fill_pick_history(p, day=day, intervals=intervals)
        # The case is re-read at every build (user 2026-10-15: full explanations, player vs opponent, recency and
        # consistency) from the pick's kept games, the sheet's row for the player, and the board's written case.
        p["points"] = cs.pick_points(p, rows=rows or [])
    return sorted(kept.values(), key=lambda p: (-(p.get("board_score") or 0), str(p.get("promoted_at"))))


def attach_images(sheet: dict[str, Any], cache: Path) -> dict[str, int]:
    """Cache each headshot / logo once on the data root and point the sheet at the app's same-origin copy."""
    from syndicate.features.shared import cheat_sheet_images as img

    counts = {"urls": 0, "cached": 0}
    seen: dict[tuple[str, int], str | None] = {}
    for section, fields in IMAGE_FIELDS:
        for item in sheet.get(section) or []:
            for src_field, out_field, size in fields:
                url = item.get(src_field)
                if not url:
                    continue
                if (url, size) not in seen:
                    seen[(url, size)] = img.cache_image(url, cache, size)
                    counts["urls"] += 1
                    counts["cached"] += seen[(url, size)] is not None
                item[out_field] = img.local_src(seen[(url, size)])
    return counts


def merge_with_record(sheet: dict[str, Any], prior: dict[str, Any] | None, *, now: datetime) -> dict[str, Any]:
    """A day's sheet is a RECORD (user 2026-10-14: "even if games have started, these cheat sheets should be
    historical records"). A game this build no longer prices -- it started, or left the board -- keeps the rows the
    last build gave it, frozen at those prices; a game this build prices replaces its rows with the fresher ones."""
    if not prior:
        return sheet
    day = sheet["date"]
    priced = {r.get("event_id") for r in sheet["rows"]}
    kept_rows = [r for r in prior.get("rows") or []
                 if r.get("event_id") not in priced and central_day(r.get("commence_time")) == day]
    kept_events = {r.get("event_id") for r in kept_rows}
    kept_games = [g for g in prior.get("games") or [] if g.get("event_id") in kept_events]
    for g in kept_games:
        g.setdefault("frozen_at", prior.get("generated_at"))
    priced_lines = {g.get("event_id") for g in sheet.get("game_lines") or []}
    kept_lines = [g for g in prior.get("game_lines") or []
                  if g.get("event_id") not in priced_lines and central_day(g.get("commence_time")) == day]
    if kept_lines:
        line_events = {g.get("event_id") for g in kept_lines} - {g.get("event_id") for g in sheet["games"]} - kept_events
        kept_games += [g for g in prior.get("games") or [] if g.get("event_id") in line_events]
        sheet = dict(sheet, game_lines=list(sheet.get("game_lines") or []) + kept_lines)
    if not kept_rows and not kept_lines:
        return sheet
    merged = dict(sheet)
    merged["rows"] = sheet["rows"] + kept_rows
    merged["games"] = list(sheet["games"]) + kept_games
    merged["sections"] = cs.sections(merged["rows"])
    merged["rows_frozen"] = len(kept_rows)
    return merged


def write_atomic(path: Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(doc, default=str), encoding="utf-8")
    os.replace(tmp, path)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data-root", default=os.environ.get("SYNDICATE_DATA_ROOT") or "")
    ap.add_argument("--sports", default="nfl,ncaaf,nhl,soccer,nba,ncaab,wnba,mlb")
    ap.add_argument("--date", default=None, help="selected date (default: today, US Central; 'tomorrow' = the day ahead)")
    ap.add_argument("--base-url", default=os.environ.get("SYNDICATE_BASE_URL") or "http://127.0.0.1:10000")
    ap.add_argument("--cap", type=int, default=None, help="override the per-sport group cap")
    ap.add_argument("--from-quotes", action="store_true",
                    help="add the day's STARTED games that no sheet priced, rebuilt from their last pregame quotes")
    args = ap.parse_args(argv)
    if not args.data_root:
        print("REFUSING: no --data-root", flush=True)
        return 2
    data_root = Path(os.path.expanduser(args.data_root))
    refusal = align_data_root(data_root)
    if refusal:
        print(f"REFUSING: {refusal}", flush=True)
        return 2
    selected = args.date or central_today()
    if selected == "tomorrow":                      # the day ahead (user 2026-10-15): an early look, refreshed later
        selected = (datetime.fromisoformat(central_today()) + timedelta(days=1)).date().isoformat()
    dvp = latest_nfl_dvp(data_root)
    from syndicate.features.shared.layer2_row_context import load_layer2_row_context

    context = load_layer2_row_context(selected)
    try:
        positions = _position_indexes()
    except Exception as exc:  # noqa: BLE001
        print(f"CHEAT_SHEET positions unavailable: {type(exc).__name__}: {exc}", flush=True)
        positions = {}
    global news_root
    news_root = data_root if (data_root / "news").is_dir() else None
    try:
        board_cards = fetch_board_cards(args.base_url)
    except Exception as exc:  # noqa: BLE001 -- no picks this run; every sheet still builds
        print(f"CHEAT_SHEET board cards unavailable: {type(exc).__name__}: {exc}", flush=True)
        board_cards = []
    # Interval scores for segment picks (first-3-innings, Q1, P1 ...), cached per date: finals never change.
    from syndicate.features.shared.interval_history import IntervalHistory

    intervals = IntervalHistory(data_root / "cheatsheets" / ".interval_cache", today=central_today())
    for sport in [s.strip() for s in args.sports.split(",") if s.strip()]:
        target = data_root / "cheatsheets" / sport / f"{selected}.json"
        if not in_season(sport, selected):
            # The sheet's sections wait for the regular season, but the board's suggested picks do not: a sport the
            # board promotes today gets a picks-only sheet (2026-10-15: a preseason NBA spread was one of the board's 7).
            if not cs.select_picks(board_cards, sport=sport, day=selected):
                print(f"CHEAT_SHEET {sport} date={selected} not in its regular season or postseason -- skipped", flush=True)
                continue
            try:
                prior = json.loads(target.read_text(encoding="utf-8")) if target.is_file() else None
            except (OSError, ValueError):
                prior = None
            sheet = build_sport(sport, [], selected_date=selected, cap=1, dvp=dvp, context=context, positions=positions)
            sheet["picks"] = merge_picks(build_picks(board_cards, sheet, sport=sport, day=selected,
                                                     now=datetime.now(timezone.utc)), prior, cards=board_cards,
                                         day=selected, intervals=intervals)
            sheet["phase"] = season_phase(sport, selected) or "preseason"
            sheet["picks_only"] = True
            attach_images(sheet, data_root / "cheatsheets" / ".img_cache")
            write_atomic(target, sheet)
            print(f"CHEAT_SHEET {sport} date={selected} picks-only sheet: {len(sheet['picks'])} picks", flush=True)
            continue
        try:
            prior = json.loads(target.read_text(encoding="utf-8")) if target.is_file() else None
        except (OSError, ValueError):
            prior = None
        try:
            if args.from_quotes:
                kept = {str(r.get("event_id")) for r in (prior or {}).get("rows") or []}
                rows = quote_rows(data_root, sport, selected, skip_events=kept, now=datetime.now(timezone.utc))
            else:
                rows = fetch_rows(args.base_url, sport)
        except Exception as exc:  # noqa: BLE001
            print(f"CHEAT_SHEET {sport} fetch failed: {type(exc).__name__}: {exc}", flush=True)
            continue
        sheet = build_sport(sport, rows, selected_date=selected, cap=args.cap or DEFAULT_CAPS.get(sport, 80), dvp=dvp,
                            context=context, positions=positions,
                            pvp_cache=data_root / "cheatsheets" / f".{sport}_cache" / selected)
        sheet = merge_with_record(sheet, prior, now=datetime.now(timezone.utc))
        try:
            sheet["picks"] = merge_picks(build_picks(board_cards, sheet, sport=sport, day=selected, now=datetime.now(timezone.utc)),
                                         prior, rows=sheet.get("rows"), cards=board_cards, day=selected, intervals=intervals)
        except Exception as exc:  # noqa: BLE001 -- a missing picks section is a gap, never a failed sheet
            print(f"CHEAT_SHEET {sport} picks failed: {type(exc).__name__}: {exc}", flush=True)
            sheet["picks"] = list((prior or {}).get("picks") or [])
        if sport in IDENTITY_SPORTS and sheet.get("rows"):   # after the merge, so a kept row gets its face too
            filled = fill_identity(sport, sheet["rows"], selected, data_root / "cheatsheets" / f".{sport}_cache" / selected)
            print(f"CHEAT_SHEET {sport} identity filled {filled}", flush=True)
        sheet["phase"] = season_phase(sport, selected)
        if not sheet["rows"] and not sheet.get("game_lines") and not sheet.get("picks") and prior is None:
            print(f"CHEAT_SHEET {sport} date={selected} no {selected} games with pregame props -- nothing written", flush=True)
            continue
        images = attach_images(sheet, data_root / "cheatsheets" / ".img_cache")
        write_atomic(target, sheet)
        counts = {k: len(v) for k, v in sheet["sections"].items()}
        have = {k: sum(1 for r in sheet["rows"] if r.get(k)) for k in ("team", "pos", "headshot_url", "team_logo")}
        print(f"CHEAT_SHEET {sport} date={selected} groups={sheet['groups_built']}/{sheet['groups_on_board']} "
              f"rows={len(sheet['rows'])} frozen={sheet.get('rows_frozen', 0)} picks={len(sheet.get('picks') or [])} sections={counts} identity={have} "
              f"images={images} secs={sheet['build_seconds']}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
