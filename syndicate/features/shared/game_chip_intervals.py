"""Interval projections on the basketball Games-rail chips (lane `basketball-interval-projections`, 2026-11-07).

WHY. User, 2026-11-07: "all basketball modules used to have very accurate qtr/half/full game score and spread
projections ... need the game rail cards to indicate the interval projections", then "we need college qtr/half
projections back". The sims already compute every interval: each publishes a total and a home-minus-away margin
histogram per half and quarter --

  ncaab / wncaab pregame  `college_basketball/pregame_sim` -> `<league>_source/data/pregame_sim/pregame_sim_<d>.json`
  ncaab / wncaab live     `ncaab/live_resim`               -> `live/<league>_live_resim.json` (keyvalue)
  nba pregame             `nba_game_projections.load_nba_game_projections` (smart-sim `dist.segments`)
  wnba pregame            `wnba_game_projections.load_wnba_game_projections`
  nba / wnba live         `nba/live_resim`                 -> `live/<league>_live_resim.json` (keyvalue)

-- and no rail card showed one. This module turns those histograms into one `intervals` block per chip. It READS
ARTIFACTS ONLY (no sim, no fetch), so it is safe on web as well as on the worker that publishes the chips.

WHAT THE BLOCK SAYS, and what it never does:
  - per period (men's college: 1H / 2H; women's college, NBA, WNBA: Q1-Q4), projected away and home points from
    the period's mean total T and mean home margin M: home = (T + M) / 2, away = (T - M) / 2;
  - each period's state: `settled` (the histogram is the real score), `in_progress`, or `ahead`;
  - the projected final: away, home, total, home margin, and a win probability where the board shows one.
  - NO PRICE. College segment pricing stays off (`SYNDICATE_COLLEGE_LIVE_SEGMENT_PRICING`, todo `#763`); this
    is display of the sim's own numbers.
  - NO NEUTRAL FILL. A chip whose game has no sim, or a live chip whose re-sim refused or has no lane, gets no
    block, and the card renders exactly as before.

WIN PROBABILITY. College pregame moneylines are served at the de-vigged fair (`college_game_projections`,
SYNDICATE_COLLEGE_MARGIN_MODEL_WEIGHT default 0.0), so the board shows no college pregame model win
probability; a rail card that showed the sim's would contradict it. It is left out there. Live college, NBA
and WNBA show the model probability the board already shows.

MARGINS. Live college margins are the market-anchored ones the board prices from (`ncaab/live_resim`
`_anchor_segments`, user 2026-11-02 "Fix + anchor"): the lane's `homeMargin` and the segments' anchored
`margin_dist`. The raw sim margin is never shown.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Callable, Iterable, Mapping

BASKETBALL_INTERVAL_SPORTS: frozenset[str] = frozenset({"nba", "wnba", "ncaab", "wncaab"})
COLLEGE_SPORTS: frozenset[str] = frozenset({"ncaab", "wncaab"})

#: The periods a card shows, in order. Men's college plays halves; everyone else quarters.
PERIODS: dict[str, tuple[str, ...]] = {
    "ncaab": ("h1", "h2"),
    "wncaab": ("q1", "q2", "q3", "q4"),
    "nba": ("q1", "q2", "q3", "q4"),
    "wnba": ("q1", "q2", "q3", "q4"),
}
LABELS: dict[str, str] = {"h1": "1H", "h2": "2H", "q1": "Q1", "q2": "Q2", "q3": "Q3", "q4": "Q4"}

SOURCE_PREGAME = "pregame_sim"
SOURCE_LIVE = "live_resim"

#: Cache lifetimes. A live lane moves every re-sim tick (~1-4 min); a pregame sim at most a few times a day.
_TTL_LIVE_SECONDS = 15.0
_TTL_PREGAME_SECONDS = 120.0

_cache: dict[tuple[str, ...], tuple[float, Any]] = {}
_cache_lock = threading.Lock()


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()


def _cached(key: tuple[str, ...], ttl: float, loader: Callable[[], Any]) -> Any:
    now = time.monotonic()
    with _cache_lock:
        hit = _cache.get(key)
        if hit is not None and now - hit[0] < ttl:
            return hit[1]
    try:
        value = loader()
    except Exception:  # noqa: BLE001 -- a source that cannot be read is an absent source, never a failed chip
        value = None
    with _cache_lock:
        _cache[key] = (now, value)
    return value


# ------------------------------------------------------------------------------------------- histograms

def hist_mean(hist: Any) -> float | None:
    """Mean of a `{value: count}` histogram (keys may be strings). None when empty or unreadable."""
    if not isinstance(hist, Mapping) or not hist:
        return None
    total = 0.0
    count = 0.0
    for raw_value, raw_count in hist.items():
        try:
            value, n = float(raw_value), float(raw_count)
        except (TypeError, ValueError):
            return None
        if n < 0:
            return None
        total += value * n
        count += n
    return total / count if count > 0 else None


def _split(total: float | None, margin: float | None) -> tuple[float | None, float | None]:
    """(away, home) points from a total and a home-minus-away margin."""
    if total is None or margin is None:
        return None, None
    return (total - margin) / 2.0, (total + margin) / 2.0


def _r1(value: float | None) -> float | None:
    return None if value is None else round(float(value), 1)


def _segment_means(block: Any) -> tuple[float | None, float | None]:
    """(mean total, mean home margin) of one segment block, whichever histogram names it carries.

    Pregame blocks are `{"total": hist, "margin": hist}`; live blocks `{"total_dist", "margin_dist", "total_mean"}`.
    """
    if not isinstance(block, Mapping):
        return None, None
    total = block.get("total_mean")
    try:
        total = float(total) if total is not None else None
    except (TypeError, ValueError):
        total = None
    if total is None:
        total = hist_mean(block.get("total_dist") if "total_dist" in block else block.get("total"))
    margin = hist_mean(block.get("margin_dist") if "margin_dist" in block else block.get("margin"))
    return total, margin


# ------------------------------------------------------------------------------------------- block

def _current_index(sport: str, period: Any) -> int | None:
    """0-based index into PERIODS[sport] of the period being played, from the 1-based live period."""
    try:
        p = int(period)
    except (TypeError, ValueError):
        return None
    if p < 1:
        return None
    periods = PERIODS[sport]
    if len(periods) == 2:  # halves: period 1 -> h1, 2 and every overtime -> h2
        return 0 if p == 1 else 1
    return min(p, 4) - 1


def build_block(
    sport: str,
    *,
    source: str,
    segments: Mapping[str, Any],
    final_total: float | None,
    final_margin: float | None,
    home_win_prob: float | None = None,
    live_period: Any = None,
    as_of: str | None = None,
    sims: Any = None,
) -> dict[str, Any] | None:
    """The chip's `intervals` block from one sim's segments. None when no period has a projection."""
    periods: list[dict[str, Any]] = []
    current = _current_index(sport, live_period) if source == SOURCE_LIVE else None
    for i, name in enumerate(PERIODS.get(sport, ())):
        block = segments.get(name) if isinstance(segments, Mapping) else None
        total, margin = _segment_means(block)
        away, home = _split(total, margin)
        if away is None:
            periods.append({"key": name, "label": LABELS[name], "away": None, "home": None, "total": None,
                            "home_margin": None, "state": "unavailable"})
            continue
        if source != SOURCE_LIVE:
            state = "ahead"
        elif isinstance(block, Mapping) and block.get("settled"):
            state = "settled"
        elif current is not None and i < current:
            # Past the period by the live clock but the block did not say settled: still the sim's number.
            state = "settled"
        elif current is not None and i == current:
            state = "in_progress"
        else:
            state = "ahead"
        periods.append({"key": name, "label": LABELS[name], "away": _r1(away), "home": _r1(home),
                        "total": _r1(total), "home_margin": _r1(margin), "state": state})
    if not any(p["away"] is not None for p in periods):
        return None
    f_away, f_home = _split(final_total, final_margin)
    final = {
        "away": _r1(f_away),
        "home": _r1(f_home),
        "total": _r1(final_total),
        "home_margin": _r1(final_margin),
        "home_win_prob": None if home_win_prob is None else round(float(home_win_prob), 3),
    }
    try:
        sims_n = int(sims) if sims is not None else None
    except (TypeError, ValueError):
        sims_n = None
    return {"source": source, "as_of": as_of, "sims": sims_n, "periods": periods, "final": final}


# ------------------------------------------------------------------------------------------- sources

def _college_pregame_games(sport: str, date_value: str) -> dict[str, Any]:
    from syndicate.features.college_basketball.pregame_sim import read_pregame_sims

    payload = read_pregame_sims(date_value, sport) or {}
    games = payload.get("games") if isinstance(payload, Mapping) else None
    return {str(k): v for k, v in (games or {}).items() if isinstance(v, Mapping) and v.get("dist")}


def _live_snapshot(sport: str) -> dict[str, Any] | None:
    from syndicate.features.shared.refresh_state_store import data_root, read_json_file

    snapshot = read_json_file(data_root() / "live" / f"{sport}_live_resim.json")
    return snapshot if isinstance(snapshot, Mapping) else None


def _nba_pregame(date_value: str) -> Any:
    from syndicate.features.shared.nba_game_projections import load_nba_game_projections

    return load_nba_game_projections(date_value)


def _wnba_pregame(date_value: str) -> Any:
    from syndicate.features.shared.wnba_game_projections import load_wnba_game_projections

    return load_wnba_game_projections(date_value)


def _join_key(sport: str, name: Any) -> str | None:
    from syndicate.features.shared.team_aliases import chip_join_key

    text = str(name or "").strip()
    if not text:
        return None
    try:
        return chip_join_key(sport, text) or text.lower()
    except Exception:  # noqa: BLE001
        return text.lower()


def _side(chip: Mapping[str, Any], side: str) -> Mapping[str, Any]:
    value = chip.get(side)
    return value if isinstance(value, Mapping) else {}


def _live_lane(snapshot: Mapping[str, Any] | None, sport: str, chip: Mapping[str, Any]) -> tuple[Mapping[str, Any], Mapping[str, Any]] | None:
    """(game row, live lane) for this chip: by ESPN event id first, then by the canonical team pair."""
    if not isinstance(snapshot, Mapping):
        return None
    key = str(chip.get("game_key") or "").strip()
    away_key = str(_side(chip, "away").get("key") or "").strip().lower()
    home_key = str(_side(chip, "home").get("key") or "").strip().lower()
    by_pair = None
    for game in snapshot.get("games") or []:
        if not isinstance(game, Mapping):
            continue
        lane = next((l for l in game.get("gameLens") or []
                     if isinstance(l, Mapping) and l.get("key") == "live" and isinstance(l.get("projection"), Mapping)), None)
        if lane is None:
            continue
        if key and str(game.get("event_id") or "").strip() == key:
            return game, lane
        if by_pair is None and away_key and home_key:
            a = _join_key(sport, game.get("away_name") or game.get("away"))
            h = _join_key(sport, game.get("home_name") or game.get("home"))
            if a == away_key and h == home_key:
                by_pair = (game, lane)
    return by_pair


def _live_block(sport: str, chip: Mapping[str, Any], snapshot: Mapping[str, Any] | None) -> dict[str, Any] | None:
    hit = _live_lane(snapshot, sport, chip)
    if hit is None:
        return None
    _game, lane = hit
    projection = lane["projection"]
    total = projection.get("total")
    margin = projection.get("homeMargin")
    try:
        total = float(total) if total is not None else None
        margin = float(margin) if margin is not None else None
    except (TypeError, ValueError):
        return None
    win = lane.get("modelHomeWinProb")
    try:
        win = float(win) if win is not None else None
    except (TypeError, ValueError):
        win = None
    return build_block(sport, source=SOURCE_LIVE, segments=projection.get("segments") or {}, final_total=total,
                       final_margin=margin, home_win_prob=win, live_period=projection.get("period"),
                       as_of=lane.get("liveStateAsOf"), sims=lane.get("simsRun"))


def _college_pregame_block(sport: str, chip: Mapping[str, Any], games: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not games:
        return None
    entry = games.get(str(chip.get("game_key") or "").strip())
    if not isinstance(entry, Mapping):
        return None
    segments = ((entry.get("dist") or {}).get("segments")) or {}
    total, margin = entry.get("total_mean"), entry.get("home_margin_mean")
    try:
        total = float(total) if total is not None else None
        margin = float(margin) if margin is not None else None
    except (TypeError, ValueError):
        return None
    if total is None or margin is None:
        total, margin = _segment_means(segments.get("full"))
    # No college pregame win probability: the board serves college moneylines at the de-vigged fair.
    return build_block(sport, source=SOURCE_PREGAME, segments=segments, final_total=total, final_margin=margin,
                       home_win_prob=None, as_of=entry.get("computed_at"), sims=entry.get("sims_run"))


def _pro_pregame_block(sport: str, chip: Mapping[str, Any], index: Any) -> dict[str, Any] | None:
    if index is None:
        return None
    home_name = _side(chip, "home").get("name")
    away_name = _side(chip, "away").get("name")
    if sport == "nba":
        entry = index.lookup(home_name, away_name, chip.get("start_time_utc"))
        if entry is None:
            home_abbr, away_abbr = _side(chip, "home").get("abbr"), _side(chip, "away").get("abbr")
            entry = index.lookup(home_abbr, away_abbr, chip.get("start_time_utc")) if home_abbr and away_abbr else None
        dist = getattr(entry, "dist", None) if entry is not None else None
        win = getattr(entry, "p_home_win", None) if entry is not None else None
        sims = getattr(entry, "sim_draws", None) if entry is not None else None
    else:
        entry = index.lookup(home_name, away_name)
        if entry is None:
            home_abbr, away_abbr = _side(chip, "home").get("abbr"), _side(chip, "away").get("abbr")
            entry = index.lookup(home_abbr, away_abbr) if home_abbr and away_abbr else None
        dist = entry.get("dist") if isinstance(entry, Mapping) else None
        win = entry.get("p_home_win") if isinstance(entry, Mapping) else None
        sims = (dist or {}).get("n") if isinstance(dist, Mapping) else None
    if not isinstance(dist, Mapping) or not isinstance(dist.get("segments"), Mapping):
        return None
    segments = dist["segments"]
    total, margin = _segment_means(segments.get("full"))
    return build_block(sport, source=SOURCE_PREGAME, segments=segments, final_total=total, final_margin=margin,
                       home_win_prob=win, sims=sims)


# ------------------------------------------------------------------------------------------- attach

def attach_interval_projections(chips: Iterable[dict[str, Any]], date_value: str, *, live_only: bool = False) -> dict[str, int]:
    """Put an `intervals` block on every basketball chip that has a sim; remove a stale one that no longer does.

    `live_only` re-reads live chips only (the serve-time path: the worker's copy of a live chip is as old as its
    last board build, the re-sim moves faster). Returns counts by outcome, for the caller's log line.
    """
    counts: dict[str, int] = {}

    def bump(name: str) -> None:
        counts[name] = counts.get(name, 0) + 1

    date_value = str(date_value or "")[:10]
    for chip in chips or []:
        if not isinstance(chip, dict):
            continue
        sport = str(chip.get("sport") or "").strip().lower()
        if sport not in BASKETBALL_INTERVAL_SPORTS:
            continue
        state = chip.get("state")
        if live_only and state != "live":
            continue
        block = None
        if state == "live":
            snapshot = _cached(("live", sport), _TTL_LIVE_SECONDS, lambda s=sport: _live_snapshot(s))
            block = _live_block(sport, chip, snapshot)
        elif state not in ("final",):
            if sport in COLLEGE_SPORTS:
                games = _cached(("pregame", sport, date_value), _TTL_PREGAME_SECONDS,
                                lambda s=sport: _college_pregame_games(s, date_value))
                block = _college_pregame_block(sport, chip, games)
            else:
                loader = _nba_pregame if sport == "nba" else _wnba_pregame
                index = _cached(("pregame", sport, date_value), _TTL_PREGAME_SECONDS, lambda f=loader: f(date_value))
                block = _pro_pregame_block(sport, chip, index)
        if block is None:
            if chip.pop("intervals", None) is not None:
                bump("removed")
            bump(f"{sport}:none:{state}")
            continue
        chip["intervals"] = block
        bump(f"{sport}:{block['source']}")
    return counts
