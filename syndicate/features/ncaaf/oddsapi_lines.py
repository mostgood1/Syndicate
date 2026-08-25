"""OddsAPI game lines for the NCAAF board, read back out of the shared quote log.

WHY THIS EXISTS. `syndicate/features/ncaaf/cards.py` read its market lines from
exactly one path, `data/ncaaf_source/data/cfbd_lines_{season}_wk{week}.json`.
Measured 2026-08-25: that file is written only by `scripts/fetch_ncaaf_market_lines.py`
and `scripts/fetch_cfbd_lines.py`, **both of which have zero callers** on any
service, and no such file exists in git at any SHA. So `markets` was null on
0-of-51 games, which is why candidate generation produced 0 rows and every
priced surface downstream was empty.

WHY THE QUOTE LOG RATHER THAN A NEW FILE. `HOT_ARTIFACT_PATTERNS` is written in
sport-agnostic globs, and two of them already match NCAAF:

    *_source/tracking/book_quotes/*.jsonl        <- what this module reads
    *_source/data/book_grid/book_grid_*.json     <- what Layer 1 reads

so lines routed through the quote log cross worker->web on transport that is
already allowlisted and demonstrably running, and the SAME capture feeds both
Layer 1's grid and these cards. A bespoke `ncaaf_*_lines.json` would have needed
a new allowlist entry and would have given the board a second line source that
could disagree with Layer 1's.

WHAT THIS MODULE DOES NOT DO. It does not fetch. `scripts/fetch_ncaaf_oddsapi_game_lines.py`
captures; this reads. Keeping the read pure is what lets the board stay on the
"web reads precomputed artifacts" side of the runtime split.
"""

from __future__ import annotations

import gzip
import json
import statistics
import unicodedata
import re
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from syndicate.features.ncaaf.sources import team_registry_snapshot_path

# The canonical full-game market names the shared vocabulary tags quotes with
# (`syndicate/features/shared/market_segments.py::_MARKET_BASES`). Named here so
# a change there fails this module's tests rather than silently emptying the
# board -- an unrecognised market name produces no line, which is
# indistinguishable from "no book quoted it".
MARKET_H2H = "h2h"
MARKET_SPREADS = "spreads"
MARKET_TOTALS = "totals"

# Only full-game lines belong on a game card. A first-quarter total shown as the
# game total is `learnings.md` 2026-08-21's failure exactly: a number that is
# right and labelled wrong.
SEGMENT_FULL = "full"


def fold(value: Any) -> str:
    """Aggressive fold for TEAM-NAME MATCHING only -- never for board keys.

    Transliterates diacritics before stripping punctuation, which is the whole
    point: the board's own `_normalize_text` deletes non-ASCII outright, so CFBD's
    "San Jose State" (with an acute e) folds to `san jos state` there while
    OddsAPI's unaccented spelling folds to `san jose state`. Matching on that
    would silently drop every accented school. Here the accent is normalised
    AWAY to its base letter so both spellings meet.

    Deliberately NOT used to key the returned index -- see `build_line_index`.
    """
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower().replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _csv_rows(path: Path) -> list[dict[str, str]]:
    import csv

    if not path.is_file():
        return []
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle))
    except Exception:
        return []


# OddsAPI spellings the CFBD registry does not carry, folded key -> CFBD
# canonical name. SMALL AND VALIDATED ON PURPOSE.
#
# Every entry is checked against the registry when the map is built, and an
# entry naming a team that does not exist RAISES rather than being skipped --
# a silently-dropped alias is a team that quietly loses its line, which is the
# failure this whole module exists to remove.
#
# This is NOT `scripts/refresh_ncaaf_oddsapi.py`'s ALIASES table and must not be
# merged with it: that one targets a different vocabulary (it maps "ole miss" ->
# "mississippi", where CFBD's canonical name IS "Ole Miss"), so importing it
# here would mis-map rather than help.
#
# The list is short because it can only be verified against real OddsAPI
# responses, and this session had no egress to them. `--report` on the fetcher
# prints every unresolved name so the first live run says exactly what to add.
_ODDSAPI_NAME_SUPPLEMENT: Mapping[str, str] = {
    "umass": "Massachusetts",
    "umass minutemen": "Massachusetts",
    "southern california": "USC",
    "southern california trojans": "USC",
    "louisiana monroe": "UL Monroe",
    "louisiana monroe warhawks": "UL Monroe",
    "ulm": "UL Monroe",
    "miami ohio": "Miami (OH)",
    "miami oh": "Miami (OH)",
    "miami florida": "Miami",
    "miami fl": "Miami",
}


@lru_cache(maxsize=1)
def _alias_map() -> dict[str, str]:
    """folded alias -> CFBD canonical team name.

    AMBIGUOUS ALIASES ARE DROPPED, NOT RESOLVED. The registry carries 684 teams
    across all divisions and `state.md` records the specific hazard: roughly 680
    schools share mascots, so "Wildcats" or "Bulldogs" identifies nobody. Any
    folded string that two different canonical teams both claim is removed from
    the map entirely, so a collision yields "unresolved" (a visible gap) rather
    than a confident wrong join (an invisible one).

    A BARE MASCOT IS NEVER A KEY. Mascots enter only as the tail of
    "<school> <mascot>", which is the shape OddsAPI actually sends
    ("TCU Horned Frogs"), and as a suffix `resolve_team` may strip.
    """
    mapping: dict[str, str] = {}
    collisions: set[str] = set()

    def offer(alias: Any, canonical: str) -> None:
        key = fold(alias)
        if not key or key.isdigit():
            return
        existing = mapping.get(key)
        if existing is None:
            mapping[key] = canonical
        elif existing != canonical:
            collisions.add(key)

    for row in _csv_rows(team_registry_snapshot_path()):
        canonical = str(row.get("canonical_team_name") or "").strip()
        if not canonical:
            continue
        school = str(row.get("school_name") or "").strip()
        mascot = str(row.get("mascot_name") or "").strip()

        # The high-confidence key first: OddsAPI's own "<School> <Mascot>".
        if school and mascot:
            offer(f"{school} {mascot}", canonical)
        offer(canonical, canonical)
        offer(school, canonical)
        offer(row.get("display_name"), canonical)
        # `aliases` is pipe-separated and INCLUDES the bare mascot, which is why
        # every alias goes through the collision check rather than being trusted.
        for alias in str(row.get("aliases") or "").split("|"):
            offer(alias, canonical)
        # Abbreviations collide hard across divisions (many "ACU"s); the
        # collision pass is what makes offering them safe.
        offer(row.get("abbreviation"), canonical)

    for key in collisions:
        mapping.pop(key, None)

    # The supplement is applied AFTER the collision pass and overrides it: these
    # are hand-verified answers to names the registry genuinely does not carry,
    # so they must survive a mascot collision rather than be dropped by it.
    known = {row for row in mapping.values()}
    if known:
        for alias, canonical in _ODDSAPI_NAME_SUPPLEMENT.items():
            if canonical not in known:
                raise ValueError(
                    "_ODDSAPI_NAME_SUPPLEMENT maps "
                    f"{alias!r} -> {canonical!r}, which is not a canonical team in "
                    f"{team_registry_snapshot_path()}. Fix the entry rather than "
                    "removing this check: a silently-skipped alias is a team that "
                    "quietly loses its market line."
                )
            mapping[fold(alias)] = canonical
    return mapping


@lru_cache(maxsize=1)
def _mascot_tails() -> tuple[str, ...]:
    """Folded mascot strings, longest first, for suffix stripping only."""
    seen: set[str] = set()
    for row in _csv_rows(team_registry_snapshot_path()):
        mascot = fold(row.get("mascot_name"))
        if mascot:
            seen.add(mascot)
    return tuple(sorted(seen, key=lambda item: (-len(item.split()), item)))


def resolve_team(name: Any) -> str | None:
    """An OddsAPI team name -> the CFBD canonical name the board joins on.

    Returns None rather than a guess. An unresolved team costs that game its
    line; a wrong one puts another game's price on this card.
    """
    key = fold(name)
    if not key:
        return None
    mapping = _alias_map()
    hit = mapping.get(key)
    if hit:
        return hit
    # "<school> <mascot>" where the pair was never registered together: strip a
    # known mascot tail and retry on the school alone. Longest tail first so
    # "Rainbow Warriors" is tried before "Warriors".
    for tail in _mascot_tails():
        suffix = " " + tail
        if key.endswith(suffix):
            stem = key[: -len(suffix)].strip()
            if stem:
                hit = mapping.get(stem)
                if hit:
                    return hit
    return None


def _iter_quote_rows(sport: str, date_str: str) -> Iterable[dict[str, Any]]:
    """Every row in one date's shard, in append order. Never raises."""
    try:
        from syndicate.features.shared.odds_book_quotes import resolve_book_quotes_path

        path = resolve_book_quotes_path(sport, date_str)
    except Exception:
        return []
    if not path or not Path(path).is_file():
        return []
    rows: list[dict[str, Any]] = []
    try:
        opener = gzip.open if str(path).endswith(".gz") else open
        with opener(path, "rt", encoding="utf-8") as handle:  # type: ignore[operator]
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                if isinstance(row, dict):
                    rows.append(row)
    except Exception:
        return []
    return rows


def _latest_per_key(rows: Iterable[Mapping[str, Any]]) -> dict[tuple, dict[str, Any]]:
    """Collapse the append log to one row per (game, market, selection, book).

    The log is append-only and ordered, so the LAST occurrence is current. That
    is also why a line that stopped being quoted keeps its last value here --
    freshness is the caller's problem, and `line_index_freshness` reports it
    rather than this function silently dropping stale rows.
    """
    latest: dict[tuple, dict[str, Any]] = {}
    for row in rows:
        if str(row.get("kind") or "game") != "game":
            continue
        if str(row.get("segment") or SEGMENT_FULL) != SEGMENT_FULL:
            continue
        key = (
            str(row.get("home_team") or ""),
            str(row.get("away_team") or ""),
            str(row.get("market") or ""),
            str(row.get("selection") or ""),
            str(row.get("bookmaker") or ""),
        )
        latest[key] = dict(row)
    return latest


def _as_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _selection_side(selection: Any, *, home_raw: str, away_raw: str) -> str | None:
    """Which side of the market a quote row is for: home / away / over / under.

    `quote_rows_from_oddsapi_events` ALREADY resolves OddsAPI's outcome names to
    these side tokens, so the canonical form is checked first. Measured while
    building this: assuming the row still carried the raw team name silently
    dropped every spread and moneyline while totals -- whose outcome name IS
    literally "Over" -- kept working, which looked like a books-coverage gap
    rather than a bug.

    The team-name branch stays as a fallback because the log is shared and a
    future writer may not go through that helper.
    """
    text = fold(selection)
    if not text:
        return None
    if text in ("home", "away", "over", "under"):
        return text
    if text == fold(home_raw):
        return "home"
    if text == fold(away_raw):
        return "away"
    if text.startswith("over"):
        return "over"
    if text.startswith("under"):
        return "under"
    return None


def build_line_index(
    rows: Iterable[Mapping[str, Any]],
    *,
    key_fn: Callable[[Any], str],
) -> dict[tuple[str, str], dict[str, Any]]:
    """Quote rows -> the index shape `_smartsim2_standalone_rows` already joins on.

    `key_fn` IS PASSED IN, not imported. It must be the board's own
    `_normalize_text`, because the projection index is keyed with that exact
    function and a second copy here would be free to drift. Passing it also
    breaks what would otherwise be an import cycle.

    Aggregation deliberately MIRRORS the CFBD reader this supplements, so the
    two sources cannot produce differently-shaped numbers for the same game:
    mean spread across books (negated -- see below), mean total, and the first
    book quoting BOTH moneylines rather than an average, since American odds do
    not average meaningfully.

    THE NEGATION IS THE EASY THING TO GET BACKWARDS. `market_margin` is a HOME
    MARGIN (positive = home favoured); a book's home spread is negative when the
    home side is favoured. `state.md` records the identical trap costing a whole
    analysis in NFL: using nflverse's `spread_line` negated inverted every
    conclusion while producing entirely plausible numbers.
    """
    latest = _latest_per_key(rows)

    per_game: dict[tuple[str, str], dict[str, Any]] = {}
    for (home_raw, away_raw, market, selection, book), row in latest.items():
        home = resolve_team(home_raw)
        away = resolve_team(away_raw)
        if not home or not away:
            continue
        key = (key_fn(home), key_fn(away))
        bucket = per_game.setdefault(
            key,
            {"spreads": {}, "totals": [], "h2h": {}, "home_name": home, "away_name": away},
        )
        line = _as_float(row.get("line"))
        price = row.get("price")
        side = _selection_side(selection, home_raw=home_raw, away_raw=away_raw)

        if market == MARKET_SPREADS and line is not None:
            # Only the HOME side's line; the away side is its mirror and
            # averaging the pair would cancel to zero.
            if side == "home":
                bucket["spreads"][book] = line
        elif market == MARKET_TOTALS and line is not None:
            # Over only, for the same reason -- over and under quote the SAME
            # number, so counting both would just double the sample.
            if side == "over":
                bucket["totals"].append(line)
        elif market == MARKET_H2H and price is not None:
            if side in ("home", "away"):
                bucket["h2h"].setdefault(book, {})[side] = price

    index: dict[tuple[str, str], dict[str, Any]] = {}
    for key, bucket in per_game.items():
        spreads = list(bucket["spreads"].values())
        totals = list(bucket["totals"])
        home_ml = away_ml = None
        for _book, prices in bucket["h2h"].items():
            if prices.get("home") is not None and prices.get("away") is not None:
                home_ml = prices.get("home")
                away_ml = prices.get("away")
                break
        index[key] = {
            "market_margin": (-statistics.mean(spreads)) if spreads else None,
            "market_total": statistics.mean(totals) if totals else None,
            "home_moneyline": home_ml,
            "away_moneyline": away_ml,
            "book_count": len(set(bucket["spreads"]) | set(bucket["h2h"])),
            "source": "oddsapi_book_quotes",
        }
    return index


def load_week_line_index(
    season: int,
    week: int,
    *,
    key_fn: Callable[[Any], str],
    kickoff_dates: Iterable[str],
) -> dict[tuple[str, str], dict[str, Any]]:
    """The week's line index, read from the quote shards its games kick off on.

    `kickoff_dates` is supplied by the caller rather than derived here because
    the board already holds the schedule -- and because NCAAF "week 1" spans ten
    calendar days (2026: 08-29 to 09-07), so guessing a date window from the week
    number would silently drop most of the slate.
    """
    rows: list[dict[str, Any]] = []
    for date_str in dict.fromkeys(str(d).strip() for d in kickoff_dates if d):
        rows.extend(_iter_quote_rows("ncaaf", date_str))
    if not rows:
        return {}
    return build_line_index(rows, key_fn=key_fn)


def resolution_report(names: Iterable[Any]) -> dict[str, Any]:
    """How many OddsAPI names resolved, and which did not.

    Exists so the join is verified as a COUNT over the real slate rather than
    spot-checked. `scripts/fetch_ncaaf_oddsapi_game_lines.py --report` prints
    this, and an unresolved name is the signal that the registry needs an alias,
    not that the fetch failed.
    """
    seen = Counter(str(n) for n in names if str(n or "").strip())
    resolved: dict[str, str] = {}
    unresolved: list[str] = []
    for name in seen:
        hit = resolve_team(name)
        if hit:
            resolved[name] = hit
        else:
            unresolved.append(name)
    return {
        "total": len(seen),
        "resolved": len(resolved),
        "unresolved": sorted(unresolved),
        "mapping": resolved,
    }
