"""The `/ncaab/cards` payload, in the shape the WNBA parity cards page renders.

User, 2026-11-02: "the ncaab page needs a complete overhaul to match nba/wnba".
NBA and WNBA render their slates through the parity cards page
(`templates/wnba/cards_source.html` + `static/wnba/cards-parity.js`); NCAAB had
the generic shared board. This builds that page's payload from what NCAAB
actually has:

- the D1 slate (`ncaab/slate.py`: teams, logos, start, live state, scores), and
- the market, from the NCAAB book grid: consensus home spread, total and both
  moneylines at each game's MAIN line (the one priced closest to even), plus
  how many books quote the game.

NO MODEL, AND THE PAYLOAD DOES NOT PRETEND OTHERWISE. NCAAB has no pregame
projection, so `sim` carries only what the page needs to key a card, and the
page's NCAAB bootstrap sets `hasModel: false` -- it shows the market where WNBA
shows "Sim score" and "Model total", and offers no official pick. WIN is the
no-vig consensus moneyline probability; COV is left empty (at the market's own
line it is a coin flip by construction, and printing 50% would read as a model
output). PTS pregame is the market-implied team total ((total -/+ spread) / 2),
which is what the market projects, labelled as the market on the card.
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

from syndicate.features.ncaab.slate import central_start_label, slate_games


def _data_root() -> Path:
    env = str(os.environ.get("SYNDICATE_DATA_ROOT") or "").strip()
    return Path(env) if env else Path(__file__).resolve().parents[3] / "data"


def _num(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out == out else None


def _american_prob(price: Any) -> float | None:
    value = _num(price)
    if value is None or value == 0:
        return None
    return 100.0 / (value + 100.0) if value > 0 else -value / (-value + 100.0)


def _team_key(name: Any, league: str = "ncaab") -> str | None:
    try:
        from syndicate.features.shared.team_aliases import chip_join_key

        return chip_join_key(league, str(name or "")) or None
    except Exception:  # noqa: BLE001
        return None


_grid_cache: dict[str, tuple[float, dict]] = {}


def _grid_markets(day: str, league: str = "ncaab") -> dict[tuple[str, str], dict[str, Any]]:
    """(home key, away key) -> {home_spread, total, home_ml, away_ml, books} for one grid date."""
    from syndicate.features.college_basketball.league import league_for

    path = _data_root() / league_for(league).data_dir / "data" / "book_grid" / f"book_grid_{day}.json"
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return {}
    cached = _grid_cache.get(str(path))
    if cached is not None and cached[0] == mtime:
        return cached[1]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    rows = payload.get("rows") if isinstance(payload, Mapping) else payload
    best: dict[tuple[str, str, str], tuple[float, dict[str, Any]]] = {}
    books: dict[tuple[str, str], set[str]] = {}
    for row in rows or []:
        if not isinstance(row, Mapping) or str(row.get("kind") or "game") != "game":
            continue
        if str(row.get("segment") or "full") != "full":
            continue
        market = row.get("market")
        if market not in ("h2h", "spreads", "totals"):
            continue
        key = (_team_key(row.get("home_team"), league), _team_key(row.get("away_team"), league))
        if not key[0] or not key[1]:
            continue
        books.setdefault(key, set()).update(str(b) for b in (row.get("books") or []))
        consensus = row.get("consensus") if isinstance(row.get("consensus"), Mapping) else {}
        if market == "h2h":
            home_ml, away_ml = _num(consensus.get("home")), _num(consensus.get("away"))
            if home_ml is not None and away_ml is not None and len(consensus) == 2:
                best[(*key, "h2h")] = (0.0, {"home_ml": home_ml, "away_ml": away_ml})
            continue
        sides = list(consensus.values())
        line = _num(row.get("line"))
        if len(sides) != 2 or line is None:
            continue
        p1, p2 = _american_prob(sides[0]), _american_prob(sides[1])
        if p1 is None or p2 is None:
            continue
        balance = abs(p1 - p2)  # the MAIN line is the one priced closest to even
        if (*key, market) not in best or balance < best[(*key, market)][0]:
            # Grid lines are in the AWAY frame (#262): the home spread is its negation.
            value = {"home_spread": -line} if market == "spreads" else {"total": line}
            best[(*key, market)] = (balance, value)
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for (home, away, _market), (_balance, value) in best.items():
        out.setdefault((home, away), {}).update(value)
    for key, names in books.items():
        out.setdefault(key, {})["books"] = len(names)
    _grid_cache[str(path)] = (mtime, out)
    return out


def _half_step(value: float | None) -> float | None:
    # A consensus averaged across books is not a line anyone posted.
    return round(value * 2) / 2 if value is not None else None


def _betting(game: Mapping[str, Any], date_iso: str, league: str = "ncaab") -> dict[str, Any]:
    home, away = _team_key(game["home"].get("name"), league), _team_key(game["away"].get("name"), league)
    day = date.fromisoformat(date_iso)
    lines: dict[str, Any] = {}
    # Grids are keyed by CAPTURE date; an evening tip is priced in the next day's file too.
    for d in (day, day + timedelta(days=1)):
        for key, value in _grid_markets(d.isoformat(), league).get((home, away), {}).items():
            lines.setdefault(key, value)
    home_ml, away_ml = lines.get("home_ml"), lines.get("away_ml")
    p_home = p_away = None
    ph, pa = _american_prob(home_ml), _american_prob(away_ml)
    if ph is not None and pa is not None and ph + pa > 0:
        p_home, p_away = ph / (ph + pa), pa / (ph + pa)  # no-vig
    return {
        "home_ml": home_ml,
        "away_ml": away_ml,
        "home_spread": _half_step(lines.get("home_spread")),
        "total": _half_step(lines.get("total")),
        "p_home_win": p_home,
        "p_away_win": p_away,
        "books": lines.get("books"),
        "source": "market_consensus",
    }


def _implied_points(betting: Mapping[str, Any]) -> tuple[float | None, float | None]:
    total, spread = betting.get("total"), betting.get("home_spread")
    if total is None or spread is None:
        return None, None
    return _half_step((total + spread) / 2.0), _half_step((total - spread) / 2.0)  # (away, home)


def _status_detail(game: Mapping[str, Any]) -> str:
    live = game.get("live_state") or {}
    if live.get("final"):
        return "Final"
    if live.get("in_progress"):
        return str(live.get("status") or "Live")
    text = str(live.get("status") or "")
    if any(word in text.lower() for word in ("postponed", "canceled", "cancelled", "suspended")):
        return text
    return central_start_label(game.get("start_time_utc")) or "Scheduled"


def _card(game: Mapping[str, Any], date_iso: str, league: str = "ncaab") -> dict[str, Any]:
    away, home = dict(game.get("away") or {}), dict(game.get("home") or {})
    live = dict(game.get("live_state") or {})
    betting = _betting(game, date_iso, league)
    implied_away, implied_home = _implied_points(betting)
    started = bool(live.get("in_progress") or live.get("final"))
    event_id = str(game.get("event_id") or "")
    periods = [
        {"period": index + 1, "away": a, "home": h}
        for index, (a, h) in enumerate(zip(live.get("away_linescores") or [], live.get("home_linescores") or []))
    ]
    return {
        "gamePk": event_id,
        "game_id": event_id,
        "event_id": event_id,
        "gameType": league.upper(),
        "away_tri": away.get("abbr") or "",
        "home_tri": home.get("abbr") or "",
        "away_name": away.get("name") or "",
        "home_name": home.get("name") or "",
        "away_logo": away.get("logo") or "",
        "home_logo": home.get("logo") or "",
        "away": away,
        "home": home,
        "neutral_site": bool(game.get("neutral_site")),
        "venue": game.get("venue"),
        "odds": {"commence_time": game.get("start_time_utc")},
        "status": {"detailed": _status_detail(game)},
        "betting": betting,
        # The page keys a card off `sim.game_id`; `players_loaded` stops it
        # asking a sim-detail endpoint NCAAB does not have.
        "sim": {
            "game_id": event_id,
            "players_loaded": True,
            "score": {"away_mean": implied_away, "home_mean": implied_home,
                      "total_mean": betting.get("total"), "margin_mean": -betting["home_spread"] if betting.get("home_spread") is not None else None},
        },
        "live_state": {
            "in_progress": bool(live.get("in_progress")),
            "final": bool(live.get("final")),
            "status": _status_detail(game),
            "away_pts": away.get("score"),
            "home_pts": home.get("score"),
            "period": live.get("period"),
            "clock": live.get("clock"),
            "periods": periods,
        } if started else None,
        "prop_recommendations": {"away": [], "home": []},
        "game_market_recommendations": [],
        "warnings": [],
    }


def build_ncaab_source_cards_payload(date_iso: str, league: str = "ncaab") -> dict[str, Any]:
    """`league="wncaab"` (lane wncaab-module) builds women's college basketball's page the same way."""
    from syndicate.features.college_basketball.league import league_for

    spec = league_for(league)
    date_value = str(date_iso or "").strip()[:10]
    games = sorted(slate_games(date_value, league=league), key=lambda g: str(g.get("start_time_utc") or ""))
    parsed = date.fromisoformat(date_value)
    return {
        "date": date_value,
        "requested_date": date_value,
        "lookahead_applied": False,
        "players_included": False,
        "pregame_portfolio": {"enabled": False, "selected": 0, "candidates": 0},
        "games": [_card(game, date_value, league) for game in games if (game.get("away") or {}).get("name") and (game.get("home") or {}).get("name")],
        "prev_date": (parsed - timedelta(days=1)).isoformat(),
        "next_date": (parsed + timedelta(days=1)).isoformat(),
        "board_contract": {
            "schema": "game_board_v1",
            "surface": "parity_cards_v1",
            "sport": league,
            "module": "cards",
            "source_kind": "d1_slate_market_consensus",
            "live_lens_integrated": False,
        },
        "source_title": f"{spec.label} D1 slate + market consensus (no model)",
        "source_path": f"{spec.data_dir}/data/scoreboard/scoreboard_{date_value}.json",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
