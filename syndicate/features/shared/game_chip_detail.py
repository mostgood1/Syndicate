"""The games-rail card's extra lines (approved mockup 4, lane games-rail-full-detail).

`pregame_footer`: one short line under a pregame card --
  MLB    probable starters + the moneyline favourite   "Messick vs Burke · CLE -120"
  NBA/WNBA  spread + total                             "BOS -4.5 · o/u 237.5"
  NHL    starting goalies + favourite + total          "Gibson / Daccord · DET -140 · o/u 6"
  NFL    slot (TNF/SNF/MNF) + spread + total           "TNF · DAL -3 · o/u 48.5"
  NCAAF  spread + total from the book grid's main line "UTSA -2.5 · o/u 61.5"
  soccer the line, when the game carries one
Every piece is optional and simply left out when its source has nothing --
never a placeholder, never a guess.

`live_detail`: the sport-specific live line, from fields the game dict already
carries (MLB runners / pitcher, football down & distance, soccer red cards).
Returns None when the source sends none; the card then shows only the clock.

Display only. All reads are local files cached by (path, mtime), so a chip build
does no network and re-reads nothing until the file changes.
"""

from __future__ import annotations

import csv
import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping
from zoneinfo import ZoneInfo

_CT = ZoneInfo("America/Chicago")
_LOCK = threading.Lock()
_FILE_CACHE: dict[str, tuple[tuple[int, int], Any]] = {}


def _num(value: Any) -> float | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out == out else None  # NaN -> None


def _odds(value: float) -> str:
    n = int(round(value))
    return f"+{n}" if n > 0 else f"−{abs(n)}"


def _line(value: float) -> str:
    text = f"{abs(value):g}"
    return f"+{text}" if value > 0 else (f"−{text}" if value < 0 else "PK")


def _data_roots() -> list[Path]:
    roots = []
    env = os.environ.get("SYNDICATE_DATA_ROOT")
    if env:
        roots.append(Path(env))
    roots.append(Path(__file__).resolve().parents[3] / "data")
    return roots


def _first(relative: str) -> Path | None:
    for root in _data_roots():
        path = root / relative
        if path.is_file():
            return path
    return None


def _cached(path: Path | None, loader: Callable[[Path], Any]) -> Any:
    if path is None:
        return None
    try:
        st = path.stat()
    except OSError:
        return None
    sig = (st.st_mtime_ns, st.st_size)
    key = str(path)
    with _LOCK:
        hit = _FILE_CACHE.get(key)
    if hit is not None and hit[0] == sig:
        return hit[1]
    try:
        value = loader(path)
    except Exception:  # noqa: BLE001 -- a footer must never break a chip
        value = None
    with _LOCK:
        _FILE_CACHE[key] = (sig, value)
        if len(_FILE_CACHE) > 64:
            _FILE_CACHE.pop(next(iter(_FILE_CACHE)), None)
    return value


def _team_key(sport: str, name: Any) -> str | None:
    if not name:
        return None
    try:
        from syndicate.features.shared.team_aliases import chip_join_key

        return chip_join_key(sport, str(name)) or str(name).strip().lower()
    except Exception:  # noqa: BLE001
        return str(name).strip().lower()


def _ct_date(start_utc: datetime | None) -> str | None:
    if start_utc is None:
        return None
    moment = start_utc if start_utc.tzinfo else start_utc.replace(tzinfo=timezone.utc)
    return moment.astimezone(_CT).date().isoformat()


# ---------------------------------------------------------------- the lines


def _market_lines(game: Mapping[str, Any]) -> dict[str, float | None]:
    """home/away moneyline, home spread, total -- first source that has each."""
    markets = game.get("markets") if isinstance(game.get("markets"), Mapping) else {}
    betting = game.get("betting") if isinstance(game.get("betting"), Mapping) else {}
    ml = markets.get("moneyline") if isinstance(markets.get("moneyline"), Mapping) else {}
    spread = markets.get("spread") if isinstance(markets.get("spread"), Mapping) else {}
    total = markets.get("total") if isinstance(markets.get("total"), Mapping) else {}
    tracked = game.get("trackedGameLines") if isinstance(game.get("trackedGameLines"), Mapping) else {}
    tracked_h2h = tracked.get("h2h") if isinstance(tracked.get("h2h"), Mapping) else {}

    def pick(*values: Any) -> float | None:
        for value in values:
            out = _num(value)
            if out is not None:
                return out
        return None

    return {
        "home_ml": pick(ml.get("home"), betting.get("home_ml"), tracked_h2h.get("home_odds")),
        "away_ml": pick(ml.get("away"), betting.get("away_ml"), tracked_h2h.get("away_odds")),
        "home_spread": pick(spread.get("home"), betting.get("home_spread")),
        "total": pick(total.get("line"), betting.get("total")),
    }


def _favourite_ml(lines: Mapping[str, float | None], away: str, home: str) -> str | None:
    h, a = lines.get("home_ml"), lines.get("away_ml")
    if h is None or a is None:
        return None
    return f"{home} {_odds(h)}" if h <= a else f"{away} {_odds(a)}"


def _spread_text(home_spread: float | None, away: str, home: str) -> str | None:
    if home_spread is None:
        return None
    if home_spread == 0:
        return "PK"
    return f"{home} {_line(home_spread)}" if home_spread < 0 else f"{away} {_line(-home_spread)}"


def _total_text(total: float | None) -> str | None:
    return f"o/u {total:g}" if total is not None else None


def _surname(name: Any) -> str | None:
    text = str(name or "").strip()
    return text.split()[-1] if text else None


def _mlb_probables(game: Mapping[str, Any]) -> str | None:
    probable = game.get("probable") if isinstance(game.get("probable"), Mapping) else {}
    names = []
    for side in ("away", "home"):
        entry = probable.get(side)
        name = entry.get("fullName") if isinstance(entry, Mapping) else entry
        names.append(_surname(name))
    if not all(names):
        return None
    return f"{names[0]} vs {names[1]}"


def _load_goalies(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    with open(path, encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            key = _team_key("nhl", row.get("team"))
            if key and row.get("goalie"):
                out[key] = str(row.get("goalie")).strip()
    return out


def _nhl_goalies(game: Mapping[str, Any], day: str | None, away_name: str, home_name: str) -> str | None:
    if not day:
        return None
    table = _cached(_first(f"nhl_source/data/processed/starting_goalies_{day}.csv"), _load_goalies) or {}
    away_g = table.get(_team_key("nhl", away_name) or "")
    home_g = table.get(_team_key("nhl", home_name) or "")
    if not away_g or not home_g:
        return None
    return f"{_surname(away_g)} / {_surname(home_g)}"


def _nfl_slot(start_utc: datetime | None) -> str | None:
    if start_utc is None:
        return None
    local = (start_utc if start_utc.tzinfo else start_utc.replace(tzinfo=timezone.utc)).astimezone(_CT)
    weekday = local.weekday()  # Mon=0
    if weekday == 3:
        return "TNF"
    if weekday == 0 and local.hour >= 17:
        return "MNF"
    if weekday == 6 and local.hour >= 19:
        return "SNF"
    return None


def _american_prob(price: Any) -> float | None:
    p = _num(price)
    if p is None or p == 0:
        return None
    return 100.0 / (p + 100.0) if p > 0 else -p / (-p + 100.0)


def _load_book_grid_lines(sport: str) -> Callable[[Path], dict]:
    def load(path: Path) -> dict:
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = payload.get("rows") if isinstance(payload, Mapping) else payload
        best: dict[tuple, tuple[float, float]] = {}
        for row in rows or []:
            if not isinstance(row, Mapping) or str(row.get("kind") or "game") != "game":
                continue
            if str(row.get("segment") or "full") != "full" or row.get("market") not in ("spreads", "totals", "h2h"):
                continue
            consensus = row.get("consensus") if isinstance(row.get("consensus"), Mapping) else {}
            if row.get("market") == "h2h":
                # Two-way moneylines only: a three-way (draw) market has no
                # single favourite price worth a footer.
                h_ml, a_ml = _num(consensus.get("home")), _num(consensus.get("away"))
                if h_ml is not None and a_ml is not None and len(consensus) == 2:
                    best[(_team_key(sport, row.get("home_team")), _team_key(sport, row.get("away_team")), "h2h")] = (0.0, (h_ml, a_ml))
                continue
            sides = list(consensus.values())
            if len(sides) != 2:
                continue
            p1, p2 = _american_prob(sides[0]), _american_prob(sides[1])
            line = _num(row.get("line"))
            if p1 is None or p2 is None or line is None:
                continue
            key = (_team_key(sport, row.get("home_team")), _team_key(sport, row.get("away_team")), row.get("market"))
            balance = abs(p1 - p2)  # the MAIN line is the one priced closest to even
            if key not in best or balance < best[key][0]:
                best[key] = (balance, line)
        return {key: line for key, (_b, line) in best.items()}

    return load


def _book_grid_main(sport: str, day: str | None, home_name: str, away_name: str) -> dict[str, float | None]:
    if not day:
        return {}
    table = _cached(_first(f"{sport}_source/data/book_grid/book_grid_{day}.json"), _load_book_grid_lines(sport)) or {}
    hk, ak = _team_key(sport, home_name), _team_key(sport, away_name)
    away_line = table.get((hk, ak, "spreads"))  # grid lines are in the AWAY frame (#262)
    ml = table.get((hk, ak, "h2h")) or (None, None)
    return {
        "home_spread": -away_line if away_line is not None else None,
        "total": table.get((hk, ak, "totals")),
        "home_ml": ml[0],
        "away_ml": ml[1],
    }


def _fill_from_grid(sport: str, lines: dict, day: str | None, home_name: str, away_name: str) -> dict:
    if all(lines.get(k) is not None for k in ("home_ml", "away_ml", "home_spread", "total")):
        return lines
    grid = _book_grid_main(sport, day, home_name, away_name)
    return {**lines, **{k: v for k, v in grid.items() if lines.get(k) is None and v is not None}}


def pregame_footer(
    sport: str,
    game: Mapping[str, Any],
    *,
    away: str,
    home: str,
    away_name: str,
    home_name: str,
    start_utc: datetime | None,
) -> str | None:
    """The pregame card's one-line footer, or None when no source has anything."""
    try:
        sport = str(sport or "").lower()
        day = _ct_date(start_utc)
        lines = _fill_from_grid(sport, _market_lines(game), day, home_name, away_name)
        parts: list[str | None] = []
        if sport == "mlb":
            parts = [_mlb_probables(game), _favourite_ml(lines, away, home)]
        elif sport in {"nba", "wnba", "ncaab"}:
            parts = [_spread_text(lines["home_spread"], away, home), _total_text(lines["total"])]
        elif sport == "nhl":
            parts = [_nhl_goalies(game, day, away_name, home_name), _favourite_ml(lines, away, home), _total_text(lines["total"])]
        elif sport == "nfl":
            parts = [_nfl_slot(start_utc), _spread_text(lines["home_spread"], away, home), _total_text(lines["total"])]
        elif sport == "ncaaf":
            parts = [_spread_text(lines["home_spread"], away, home), _total_text(lines["total"])]
        elif sport == "soccer":
            # Three-way market: a favourite is only worth naming at minus money.
            fav = _favourite_ml(lines, away, home)
            parts = [fav if fav and "−" in fav else None, _total_text(lines["total"])]
        text = " · ".join(p for p in parts if p)
        return text or None
    except Exception:  # noqa: BLE001 -- a footer must never break a chip
        return None


# ---------------------------------------------------------------- live line


def _bases(offense: Mapping[str, Any]) -> str | None:
    on = [label for key, label in (("first", "1st"), ("second", "2nd"), ("third", "3rd")) if offense.get(key)]
    if not on:
        return "Bases empty"
    if len(on) == 3:
        return "Bases loaded"
    return "On " + " & ".join(on)


def live_detail(sport: str, game: Mapping[str, Any]) -> str | None:
    """The sport-specific live line from fields the game already carries, or None."""
    try:
        sport = str(sport or "").lower()
        live = game.get("live_state") if isinstance(game.get("live_state"), Mapping) else {}
        shape = live.get("game_shape") if isinstance(live.get("game_shape"), Mapping) else {}
        if sport == "mlb":
            linescore = live.get("linescore") or game.get("linescore") or {}
            offense = linescore.get("offense") if isinstance(linescore, Mapping) else None
            defense = linescore.get("defense") if isinstance(linescore, Mapping) else None
            parts = []
            outs = _num((linescore or {}).get("outs") if isinstance(linescore, Mapping) else None)
            if outs is None:
                outs = _num(live.get("outs"))
            if outs is not None:
                parts.append(f"{int(outs)} out" + ("" if int(outs) == 1 else "s"))
            if isinstance(offense, Mapping):
                parts.append(_bases(offense))
            pitcher = defense.get("pitcher") if isinstance(defense, Mapping) else None
            name = pitcher.get("fullName") if isinstance(pitcher, Mapping) else live.get("pitcher_name")
            pitches = _num(shape.get("pitcher_pitch_count") or live.get("pitcher_pitch_count"))
            if name:
                parts.append(f"{_surname(name)}" + (f" {int(pitches)}p" if pitches is not None else ""))
            text = " · ".join(p for p in parts if p)
            return text or None
        if sport in {"nfl", "ncaaf"}:
            down = _num(shape.get("down") or live.get("down"))
            dist = _num(shape.get("distance") or live.get("distance"))
            team = shape.get("possession_team") or live.get("possession_team") or live.get("possession")
            yard = shape.get("yard_line") or live.get("yard_line") or live.get("possession_text")
            parts = []
            if team:
                parts.append(f"{team} ball")
            if down and dist is not None:
                ordinal = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th"}.get(int(down), f"{int(down)}th")
                parts.append(f"{ordinal} & {int(dist) if dist else 'goal'}")
            if yard:
                parts.append(f"at {yard}")
            text = " · ".join(parts)
            return text or None
        if sport == "soccer":
            reds = []
            for side, label_key in (("away", "away_red_cards"), ("home", "home_red_cards")):
                n = _num(live.get(label_key))
                if n:
                    reds.append(f"{int(n)} red ({side})")
            return " · ".join(reds) or None
        if sport == "nhl":
            sog_h, sog_a = _num(live.get("home_sog")), _num(live.get("away_sog"))
            if sog_h is not None and sog_a is not None:
                return f"SOG {int(sog_a)}–{int(sog_h)}"
        return None
    except Exception:  # noqa: BLE001
        return None
