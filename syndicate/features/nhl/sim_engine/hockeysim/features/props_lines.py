"""Reader for collected player-prop book lines (the props producer's market input).

Reads ``data/nhl_source/data/props/player_props_lines/date=YYYY-MM-DD/oddsapi.csv`` (written by the
``local_nhl_odds`` collector), keeping only current rows. The mirror often lacks ``player_id`` on
prop lines, so matching to the engine's per-player projections is by **normalized name** — the same
basis the vendor used (``name::<lower name>`` merge key).
"""
from __future__ import annotations

import unicodedata
from pathlib import Path
from typing import Dict, List, Optional

from .loaders import _odds_games_dir, _read_csv_rows

# canonical market tokens the engine projects
_MARKET_ALIASES = {
    "sog": "SOG", "shots_on_goal": "SOG", "shots": "SOG",
    "goals": "GOALS", "assists": "ASSISTS", "points": "POINTS",
    "saves": "SAVES", "blocks": "BLOCKS", "blocked_shots": "BLOCKS",
}


def normalize_name(value: object) -> str:
    """Lowercase, strip accents/punctuation -> stable name key for matching."""
    s = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii")
    return " ".join("".join(c for c in s.lower() if c.isalnum() or c.isspace()).split())


def _canonical_market(value: object) -> Optional[str]:
    token = str(value or "").strip().lower().replace(" ", "_")
    if token in _MARKET_ALIASES:
        return _MARKET_ALIASES[token]
    up = token.upper()
    return up if up in {"SOG", "GOALS", "ASSISTS", "POINTS", "SAVES", "BLOCKS"} else None


def _props_lines_path(date: str, root: Optional[Path] = None) -> Path:
    games_dir = _odds_games_dir(root)  # .../data/odds/games
    return games_dir.parent.parent / "props" / "player_props_lines" / f"date={date}" / "oddsapi.csv"


def load_props_lines(date: str, *, root: Optional[Path] = None) -> List[Dict[str, object]]:
    """Return current prop-line rows: name_key, player_name, market, line, over/under price, book."""
    rows = _read_csv_rows(_props_lines_path(date, root))
    out: List[Dict[str, object]] = []

    def _f(v: object) -> Optional[float]:
        try:
            return float(v) if str(v).strip() != "" else None
        except (TypeError, ValueError):
            return None

    for r in rows:
        is_current = str(r.get("is_current") or "").strip().lower()
        if is_current in ("false", "0", "no"):
            continue
        market = _canonical_market(r.get("market"))
        line = _f(r.get("line"))
        name = str(r.get("player_name") or "").strip()
        if not (market and name and line is not None):
            continue
        out.append({
            "name_key": normalize_name(name),
            "player_name": name,
            "team": str(r.get("team") or "").strip(),
            "market": market,
            "line": line,
            "over_price": _f(r.get("over_price")),
            "under_price": _f(r.get("under_price")),
            "book": str(r.get("book") or "").strip(),
        })
    return out
