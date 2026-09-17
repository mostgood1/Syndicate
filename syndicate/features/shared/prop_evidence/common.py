"""Readers and shaping helpers every prop-evidence provider shares.

ONE ROOT RULE FOR EVERY SPORT. Web's disk carries two layouts per sport --
`<sport>_source/source_artifacts/data/...` (mirror-shaped) and
`<sport>_source/data/...` (what the workers publish). Measured on production
2026-09-17: WNBA's live `cards_sim_detail` is under `data/processed`, NHL's
`player_rates_latest.csv` under `data/processed`, MLB's `daily_summary` under
`source_artifacts/data/daily`, and NCAAF's player box scores under
`source_artifacts/data/processed/player_game_stats`. A reader that tries ONE of
them is inert for half the sports, so `candidate_paths` always yields both and
the caller takes the first file that exists.

EVERY READ IS BOUNDED TO ONE FILE, and nothing parsed is cached across requests.
The biggest file a provider opens is WNBA's `cards_sim_detail` (3.6 MB,
2026-09-17). Caching parsed payloads on web is how a 2 GB service accumulates
tens of MB per sport per date; an Ask is a human click, so re-reading is cheap.
"""

from __future__ import annotations

import csv
import glob
import json
import logging
import math
import os
import re
from pathlib import Path
from typing import Any, Iterable, Iterator

from syndicate.features.shared.prop_evidence.contract import Layer, chart

logger = logging.getLogger(__name__)

LAST_N_GAMES = 10
MAX_CHART_POINTS = 30

_NAME_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}


def data_root() -> Path:
    return Path(os.environ.get("SYNDICATE_DATA_ROOT", "data"))


def sport_roots(local_dir_name: str) -> list[Path]:
    """`<root>/<sport>_source/source_artifacts/data` then `<root>/<sport>_source/data`."""
    base = data_root() / local_dir_name
    return [base / "source_artifacts" / "data", base / "data", base]


def candidate_paths(local_dir_name: str, relative: str) -> Iterator[Path]:
    for root in sport_roots(local_dir_name):
        yield root / relative


def first_existing(local_dir_name: str, *relatives: str) -> Path | None:
    for relative in relatives:
        for path in candidate_paths(local_dir_name, relative):
            if path.is_file():
                return path
    return None


def latest_dated(local_dir_name: str, relative_glob: str, date_regex: str, *, on_or_before: str | None = None,
                 min_bytes: int = 0) -> tuple[Path, str] | None:
    """Newest file across both roots whose name carries a date, optionally not after a date.

    `min_bytes` skips header-only files: NHL's production `props_recommendations`
    for 06-22..06-28 are 158-byte headers, so "newest" without it is an empty file.
    """
    found: list[tuple[str, str]] = []
    for root in sport_roots(local_dir_name):
        for raw in glob.glob(str(root / relative_glob)):
            match = re.search(date_regex, os.path.basename(raw))
            if not match:
                continue
            iso = match.group(1).replace("_", "-")
            if on_or_before and iso > on_or_before:
                continue
            if min_bytes:
                try:
                    if os.path.getsize(raw) < min_bytes:
                        continue
                except OSError:
                    continue
            found.append((iso, raw))
    if not found:
        return None
    found.sort()
    iso, raw = found[-1]
    return Path(raw), iso


def eastern_date(stamp: str) -> str | None:
    """The US Eastern calendar date of an ISO timestamp -- the date every US slate file is keyed by.

    An 8:00 PM ET tip is `T00:00:00Z` the NEXT UTC day, so the UTC date alone
    misses every evening game's artifacts.
    """
    if not stamp:
        return None
    try:
        from datetime import datetime, timezone
        from zoneinfo import ZoneInfo

        parsed = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(ZoneInfo("America/New_York")).date().isoformat()
    except Exception:
        return str(stamp)[:10] or None


def slate_dates(selected_date: str, commence_time: str) -> list[str]:
    """Dates to try for a row's slate files: board date, then the tip's Eastern date, then its UTC date."""
    dates: list[str] = []
    for value in (selected_date, eastern_date(commence_time), str(commence_time or "")[:10]):
        if value and value not in dates:
            dates.append(value)
    return dates


def load_json(path: Path | str) -> Any:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def iter_csv(path: Path | str) -> Iterator[dict[str, str]]:
    with open(path, encoding="utf-8", newline="") as handle:
        yield from csv.DictReader(handle)


def mtime_iso(path: Path | str | None) -> str | None:
    if not path:
        return None
    try:
        from datetime import datetime, timezone

        return datetime.fromtimestamp(os.path.getmtime(path), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except OSError:
        return None


def to_float(value: Any) -> float | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        text = str(value).strip()
        if not text or text.lower() in {"nan", "none", "null"}:
            return None
        out = float(text)
        return None if math.isnan(out) else out
    except (TypeError, ValueError):
        return None


def name_key(value: Any) -> str:
    """Accent-folded, punctuation-free, lowercase name -- the board's join rule."""
    from syndicate.features.shared.prop_projections import _norm_name

    return _norm_name(value)


def name_key_loose(value: Any) -> str:
    """`name_key` without generational suffixes ("Kenneth Walker III" == "Kenneth Walker")."""
    parts = [p for p in name_key(value).split() if p not in _NAME_SUFFIXES]
    return " ".join(parts)


def initial_key(value: Any) -> str:
    """"B. Burns" / "Brent Burns" -> "b burns" (NHL publishes first initials)."""
    parts = name_key_loose(value).split()
    if len(parts) < 2:
        return " ".join(parts)
    return f"{parts[0][0]} {parts[-1]}"


def names_match(a: Any, b: Any) -> bool:
    ka, kb = name_key(a), name_key(b)
    if not ka or not kb:
        return False
    return ka == kb or name_key_loose(a) == name_key_loose(b)


def fmt_pct(value: Any, digits: int = 1) -> str:
    number = to_float(value)
    return "—" if number is None else f"{100.0 * number:.{digits}f}%"


def fmt_num(value: Any, digits: int = 1) -> str:
    number = to_float(value)
    return "—" if number is None else f"{number:.{digits}f}"


def fmt_line(line: float | None) -> str:
    if line is None:
        return "—"
    return f"{line:g}"


# ---------------------------------------------------------------------------
# Distributions
# ---------------------------------------------------------------------------


def count_points(dist: dict[Any, Any] | None) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    for key, count in (dist or {}).items():
        x = to_float(key)
        c = to_float(count)
        if x is None or c is None or c < 0:
            continue
        points.append((x, c))
    points.sort(key=lambda item: item[0])
    return points


def dist_summary(dist: dict[Any, Any] | None) -> dict[str, float] | None:
    points = count_points(dist)
    total = sum(c for _, c in points)
    if not points or total <= 0:
        return None
    mean = sum(x * c for x, c in points) / total
    var = sum(c * (x - mean) ** 2 for x, c in points) / total
    out: dict[str, float] = {"mean": round(mean, 3), "sd": round(math.sqrt(var), 3), "n": total}
    cumulative = 0.0
    for label, threshold in (("p10", 0.10), ("p50", 0.50), ("p90", 0.90)):
        cumulative = 0.0
        for x, c in points:
            cumulative += c
            if cumulative / total >= threshold:
                out[label] = x
                break
    return out


def dist_prob_over(dist: dict[Any, Any] | None, line: float | None) -> float | None:
    """P(X > line) from a count histogram. Exact on the draws, no shape assumed."""
    if line is None:
        return None
    points = count_points(dist)
    total = sum(c for _, c in points)
    if total <= 0:
        return None
    return sum(c for x, c in points if x > line) / total


def dist_chart(dist: dict[Any, Any] | None, *, title: str, x_label: str, layer: Layer,
               line: float | None = None) -> dict[str, Any] | None:
    points = count_points(dist)
    total = sum(c for _, c in points)
    if not points or total <= 0:
        return None
    if len(points) > MAX_CHART_POINTS:
        keep = sorted(points, key=lambda item: item[1], reverse=True)[:MAX_CHART_POINTS]
        points = sorted(keep, key=lambda item: item[0])
    marker = {"x": fmt_line(line), "label": f"Line {fmt_line(line)}"} if line is not None else None
    return chart(
        title,
        x_label,
        "% of sims",
        [{"x": f"{x:g}", "y": round(100.0 * c / total, 2)} for x, c in points],
        layer,
        marker=marker,
    )


def poisson_prob_over(mean: float | None, line: float | None) -> float | None:
    """P(X > line) for Poisson(mean). Used ONLY to label a producer that priced this way."""
    if mean is None or line is None or mean < 0:
        return None
    k_max = int(math.floor(line))
    cdf = sum(math.exp(-mean) * mean ** k / math.factorial(k) for k in range(0, k_max + 1))
    return max(0.0, min(1.0, 1.0 - cdf))


# ---------------------------------------------------------------------------
# Recent form against the BOARD line
# ---------------------------------------------------------------------------


def hit_rate(values: Iterable[float | None], line: float | None, side: str | None) -> dict[str, Any] | None:
    """How often the stat cleared the board's line on the board's side.

    The old basketball helper only used lines TYPED into the question and applied
    them to every stat, so a board-row Ask ("Rhyne Howard points over 17.5")
    carried no hit rate at all. The line and side come from the row here.
    """
    if line is None:
        return None
    clean = [v for v in values if v is not None]
    if not clean:
        return None
    over = sum(1 for v in clean if v > line)
    under = sum(1 for v in clean if v < line)
    push = len(clean) - over - under
    # "no" on a yes/no market is the under side of its line; everything else is over.
    hits = under if side in {"under", "no"} else over
    return {"games": len(clean), "over": over, "under": under, "push": push, "hits": hits,
            "side": side or "over", "line": line, "rate": hits / len(clean)}


def hit_rate_text(rate: dict[str, Any] | None) -> str:
    if not rate:
        return "—"
    return f"{rate['hits']}/{rate['games']} {rate['side']} {fmt_line(rate['line'])} ({100.0 * rate['rate']:.0f}%)"


def form_chart(games: list[dict[str, Any]], *, stat_key: str, stat_label: str, player: str,
               line: float | None, layer: Layer = Layer.RECENT_FORM, date_key: str = "date") -> dict[str, Any] | None:
    points = []
    for game in reversed(games):  # chronological
        y = to_float(game.get(stat_key))
        if y is None:
            continue
        points.append({"x": str(game.get(date_key) or "")[5:] or str(game.get(date_key) or ""), "y": y})
    if not points:
        return None
    marker = {"y": line, "label": f"Line {fmt_line(line)}"} if line is not None else None
    return chart(f"{stat_label} by game — {player} (last {len(points)})", "Game", stat_label, points, layer, marker=marker)
