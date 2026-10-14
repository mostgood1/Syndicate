"""Each past game's OWN main closing line, for the board's prop recent-form bars.

User 2026-10-14 ("Build it now", lane past-line-overlays; step 3 of
findings_2026-10-09_history_charts_inventory.md): a recent-form bar is read
against the line THAT game was priced at, not only against today's line.

Display only. Nothing scores on these.

Source: ``<data>/settlement_inputs/closing_lines_<date>.csv`` (one merged file
per slate date, written by ``scripts/emit_settlement_inputs.py``; the first is
2026-09-30, so every chart's window starts there at the earliest). A bar's date
must equal the file's date exactly -- a neighbouring day's line is a different
game.

THE MAIN LINE. A player often has several closing lines for one market on one
date (ladders, different books): measured 2026-10-14, NHL 507 of 7,329 keys,
WNBA 825 of 1,069. The main line is the one whose closing OVER price is closest
to even money. A tie between two lines, or no priced over, is ``None`` -- the bar
shows no mark rather than a guessed one. Alternate-line markets are skipped
whole (by construction they hold many lines).

One file is parsed once per (path, mtime, size). No network.
"""

from __future__ import annotations

import csv
import threading
import unicodedata
from pathlib import Path
from typing import Any, Iterable

from syndicate.features.shared.prop_evidence.common import data_root

_LOCK = threading.Lock()
_CACHE: dict[str, tuple[tuple[int, int], dict[tuple[str, str, str], float | None]]] = {}
_FULL_SEGMENTS = {"", "full", "game"}


def _norm(text: Any) -> str:
    folded = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode("ascii")
    return " ".join(folded.casefold().split())


def _implied(price: Any) -> float | None:
    """American odds -> implied probability; decimal odds accepted too."""
    try:
        p = float(price)
    except (TypeError, ValueError):
        return None
    if p >= 100:
        return 100.0 / (p + 100.0)
    if p <= -100:
        return -p / (-p + 100.0)
    if 1.0 < p < 100.0:
        return 1.0 / p
    return None


def _path(day: str) -> Path:
    return data_root() / "settlement_inputs" / f"closing_lines_{day}.csv"


def _parse(path: Path) -> dict[tuple[str, str, str], float | None]:
    lines: dict[tuple[str, str, str], set[float]] = {}
    overs: dict[tuple[str, str, str], list[tuple[float, float]]] = {}
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            name = _norm(row.get("player_name"))
            market = _norm(row.get("market"))
            if not name or not market or "alternate" in market:
                continue
            if _norm(row.get("segment")) not in _FULL_SEGMENTS:
                continue
            raw = row.get("closing_line") or row.get("line")
            try:
                line = float(raw)
            except (TypeError, ValueError):
                continue
            key = (_norm(row.get("sport")), name, market)
            lines.setdefault(key, set()).add(line)
            if _norm(row.get("selection")) == "over":
                prob = _implied(row.get("closing_price"))
                if prob is not None:
                    overs.setdefault(key, []).append((abs(prob - 0.5), line))
    out: dict[tuple[str, str, str], float | None] = {}
    for key, values in lines.items():
        if len(values) == 1:
            out[key] = next(iter(values))
            continue
        ranked = sorted(overs.get(key) or [])
        if not ranked:
            out[key] = None
        elif len(ranked) > 1 and abs(ranked[1][0] - ranked[0][0]) < 1e-9 and ranked[1][1] != ranked[0][1]:
            out[key] = None
        else:
            out[key] = ranked[0][1]
    return out


def _index(day: str) -> dict[tuple[str, str, str], float | None]:
    path = _path(day)
    try:
        stat = path.stat()
    except OSError:
        return {}
    stamp = (int(stat.st_mtime_ns), int(stat.st_size))
    key = str(path)
    with _LOCK:
        hit = _CACHE.get(key)
        if hit and hit[0] == stamp:
            return hit[1]
    try:
        parsed = _parse(path)
    except Exception:  # noqa: BLE001 -- a chart must never break a card
        parsed = {}
    with _LOCK:
        _CACHE[key] = (stamp, parsed)
    return parsed


def _is_date(text: str) -> bool:
    return len(text) == 10 and text[4] == "-" and text[7] == "-" and text[:4].isdigit()


def past_main_lines(sport: Any, player_name: Any, market: Any, dates: Iterable[Any]) -> list[float | None]:
    """The main closing line for each date in ``dates`` (aligned, same order), or
    ``None`` where the date is not an ISO date (e.g. an NFL "26-W4" label), its
    file is absent, the player/market is not in it, or the main line is a tie."""
    key = (_norm(sport), _norm(player_name), _norm(market))
    out: list[float | None] = []
    for raw in dates:
        day = str(raw or "")[:10]
        out.append(_index(day).get(key) if _is_date(day) else None)
    return out


_WINDOW: dict[str, tuple[int, str | None]] = {}


def window_start() -> str | None:
    """The earliest slate date with a closing-line file, for labelling a chart's
    window. Called once per board row, so the directory is listed again only
    when its mtime changes (a file added or removed)."""
    folder = data_root() / "settlement_inputs"
    try:
        stamp = int(folder.stat().st_mtime_ns)
    except OSError:
        return None
    hit = _WINDOW.get(str(folder))
    if hit and hit[0] == stamp:
        return hit[1]
    first = None
    try:
        for name in sorted(p.name for p in folder.glob("closing_lines_*.csv")):
            day = name[len("closing_lines_"):-len(".csv")]
            if _is_date(day):
                first = day
                break
    except OSError:
        return None
    _WINDOW[str(folder)] = (stamp, first)
    return first
