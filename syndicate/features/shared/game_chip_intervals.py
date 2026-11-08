"""Interval projections on the Games-rail chips: basketball (lane `basketball-interval-projections`, 2026-11-07),
then every other sport (lane `all-sport-interval-projections`; see `OTHER_SPORTS_SOURCES` for what each engine
publishes and does not).

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
#: Phase 3 (lane `all-sport-interval-projections`): every other sport, from what its engine publishes. See
#: `OTHER_SPORTS_SOURCES` below for what each one has and does not have.
OTHER_INTERVAL_SPORTS: frozenset[str] = frozenset({"soccer", "nhl", "nfl", "ncaaf", "mlb"})
INTERVAL_SPORTS: frozenset[str] = BASKETBALL_INTERVAL_SPORTS | OTHER_INTERVAL_SPORTS

#: The periods a card shows, in order. Men's college plays halves; everyone else quarters.
PERIODS: dict[str, tuple[str, ...]] = {
    "ncaab": ("h1", "h2"),
    "wncaab": ("q1", "q2", "q3", "q4"),
    "nba": ("q1", "q2", "q3", "q4"),
    "wnba": ("q1", "q2", "q3", "q4"),
    "soccer": ("h1", "h2"),
    "nfl": ("q1", "q2", "q3", "q4"),
    "ncaaf": ("q1", "q2", "q3", "q4"),
    # CUMULATIVE, not a partition: baseball's segments are first-N-innings (the F1 / F3 / F5 markets), and that is
    # what the sim publishes. Each column is the projected score after that many innings.
    "mlb": ("f1", "f3", "f5"),
    # None shown: hockeysim's `periodN_*_proj` are its INPUT rates split by fixed league shares
    # (`hockeysim/projection.py` period_shares 0.2924 / 0.3478 / 0.3598, the same for every game), not a sim
    # output -- a neutral fill by another name. The card shows the projected final alone.
    "nhl": (),
}
LABELS: dict[str, str] = {"h1": "1H", "h2": "2H", "q1": "Q1", "q2": "Q2", "q3": "Q3", "q4": "Q4",
                          "f1": "F1", "f3": "F3", "f5": "F5"}

#: Decimals a card shows per cell. Goals and runs need one; points do not.
PRECISION: dict[str, int] = {"soccer": 1, "nhl": 1, "mlb": 1}

#: Sports whose block may carry the projected final with no period: the engine simulates the full game but
#: publishes no per-period number (NHL pregame and live; soccer, NFL and NCAAF live). Never basketball.
FINAL_ONLY_SPORTS: frozenset[str] = frozenset({"soccer", "nhl", "nfl", "ncaaf"})

#: Live win probabilities the BOARD withholds (`board_enrichment.LIVE_PROBABILITY_WITHHELD_SPORTS` holds nfl,
#: ncaaf, ncaab, wncaab). A rail card must not show what the board blanks. Only this phase's two are applied here;
#: the basketball path above predates this and still shows live college win% (raised with its owner, 2026-11-08).
LIVE_WIN_WITHHELD: frozenset[str] = frozenset({"nfl", "ncaaf"})

#: What each non-basketball source publishes, so the next reader does not re-survey (2026-11-07):
OTHER_SPORTS_SOURCES = """
  soccer pregame  `soccersim` per-run half goals -> `<league>/api/recommendations/recommendations_<d>.json`
                  `periods.{h1,h2}.{home_mean,away_mean}` (simulated means; no half histograms), `team_projection`,
                  3-way `win_probability`. UEFA cups have no sim and so no block.
  soccer live     `poll_soccer_live_state` resumed sim -> keyvalue `live/soccer_live_lens.json`, projected final
                  goals + 3-way probabilities only. No half split: the resumed runs' half_log is never aggregated.
  nhl pregame     hockeysim `predictions_<d>.csv`: projected goals per side incl. OT/SO, total, home margin,
                  p_home_ml. Its period columns are fixed shares (see PERIODS).
  nhl live        `nhl/live_resim` -> keyvalue `live/nhl_live_lens.json`, total + home margin + win prob. The event
                  engine counts goals per period but nothing publishes them. No lane in an intermission.
  nfl / ncaaf     smartsim2 `quarter_log` -> `smartsim2_segment_distributions_<season>_wk<w>.json` (flag
    pregame       SYNDICATE_FOOTBALL_SEGMENT_DISTRIBUTIONS): `segments.{full,q1..q4,h1,h2}` with per-side means and
                  total / margin histograms. NO win probability here: the board's comes from the projections CSV.
  nfl / ncaaf     `nfl/live_resim` (`live/nfl_live_resim.json`) and `ncaaf/live_resim` (`live/ncaaf_live_lens.json`):
    live          final total + home margin only; both throw the resumed quarter_log away.
  mlb pregame     `daily_summary_<d>.json` `outputs[].{first1,first3,first5,full}` per-side run means + win probs.
                  Per-inning distributions exist only behind SYNDICATE_MLB_INNING_DISTRIBUTIONS (off).
  mlb live        NOT SHOWN YET: `live/mlb_live_lens.json` has a simulated F5 lane (`live_mc_first5`) and a full lane
                  (`live_mc`), but F1/F3/F7 lanes are pregame-mean interpolations and the F5 lane's `homeMargin` is
                  never written. Season over 2026-11-07, so there is no live game to verify a reader against.
"""

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
        _file_cache.clear()


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


_PER_SIDE_KEYS: tuple[tuple[str, str], ...] = (
    ("home_mean", "away_mean"),
    ("home_points_mean", "away_points_mean"),
    ("home_runs_mean", "away_runs_mean"),
)


def _segment_means(block: Any) -> tuple[float | None, float | None]:
    """(mean total, mean home margin) of one segment block, whichever histogram names it carries.

    Pregame blocks are `{"total": hist, "margin": hist}`; live blocks `{"total_dist", "margin_dist", "total_mean"}`.
    Other sports publish each side's mean (soccer `home_mean`, football `home_points_mean`, MLB `home_runs_mean`):
    the exact means, so they are read before any histogram the same block also carries.
    """
    if not isinstance(block, Mapping):
        return None, None
    for home_key, away_key in _PER_SIDE_KEYS:
        if home_key in block and away_key in block:
            try:
                home, away = float(block[home_key]), float(block[away_key])
            except (TypeError, ValueError):
                return None, None
            return home + away, home - away
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
    final_only_ok: bool = False,
    draw_prob: float | None = None,
    away_win_prob: float | None = None,
) -> dict[str, Any] | None:
    """The chip's `intervals` block from one sim's segments. None when no period has a projection.

    `final_only_ok`: the source simulates the whole game but publishes no period (FINAL_ONLY_SPORTS), so a block
    with the projected final alone is still the sim's own number. It still needs that final.
    `draw_prob` / `away_win_prob`: three-way sports (soccer), where 1 - P(home) is not P(away).
    """
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
    f_away, f_home = _split(final_total, final_margin)
    if not any(p["away"] is not None for p in periods):
        if not (final_only_ok and sport in FINAL_ONLY_SPORTS and f_away is not None):
            return None
        periods = []
    final = {
        "away": _r1(f_away),
        "home": _r1(f_home),
        "total": _r1(final_total),
        "home_margin": _r1(final_margin),
        "home_win_prob": None if home_win_prob is None else round(float(home_win_prob), 3),
    }
    if draw_prob is not None and away_win_prob is not None:
        final["draw_prob"] = round(float(draw_prob), 3)
        final["away_win_prob"] = round(float(away_win_prob), 3)
    try:
        sims_n = int(sims) if sims is not None else None
    except (TypeError, ValueError):
        sims_n = None
    block = {"source": source, "as_of": as_of, "sims": sims_n, "periods": periods, "final": final}
    if PRECISION.get(sport):
        block["precision"] = PRECISION[sport]
    return block


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


# ------------------------------------------------------------------------------------------- other sports
#
# Phase 3 (lane `all-sport-interval-projections`). Same rules as basketball: published artifacts only, matched to
# the chip by its own id or its canonical team pair, and no block -- never a filled one -- when nothing matches.

def _f(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out == out else None  # NaN is absent


#: Parsed JSON by path, kept while the file's (mtime, size) is unchanged. The TTL cache above re-asks every 2 min;
#: without this every re-ask re-parsed ~15 soccer league-day files (2.4 s cold on the fleet, 2026-11-08).
_file_cache: dict[str, tuple[int, int, Any]] = {}
_FILE_CACHE_MAX = 256


def _read_json_unchanged(path: Any) -> Any:
    """The parsed JSON at `path`, re-read only when its mtime or size moved. None if absent or unreadable."""
    import json

    try:
        stat = path.stat()
    except OSError:
        return None
    key = str(path)
    with _cache_lock:
        hit = _file_cache.get(key)
    if hit is not None and hit[0] == stat.st_mtime_ns and hit[1] == stat.st_size:
        return hit[2]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    with _cache_lock:
        if len(_file_cache) >= _FILE_CACHE_MAX:
            _file_cache.clear()
        _file_cache[key] = (stat.st_mtime_ns, stat.st_size, payload)
    return payload


def _chip_days(chip: Mapping[str, Any], date_value: str) -> list[str]:
    """The calendar days a chip's game may be filed under: its Central day first, then its UTC day, then the board's.

    Producers file by different clocks (soccer and NHL by the slate day, MLB by StatsAPI's official date), and a 7 PM
    Central start is tomorrow in UTC. Every match is still made on the chip's own id or team pair, so a wrong day
    finds nothing rather than the wrong game.
    """
    days: list[str] = []
    start = str(chip.get("start_time_utc") or "").strip()
    if start:
        try:
            from syndicate.features.shared.timezone import central_date_from_iso

            central = central_date_from_iso(start)
            if central is not None:
                days.append(central.isoformat())
        except Exception:  # noqa: BLE001
            pass
        if len(start) >= 10:
            days.append(start[:10])
    if date_value:
        days.append(date_value)
    out: list[str] = []
    for day in days:
        if day and day not in out:
            out.append(day)
    return out


def _chip_pair(sport: str, chip: Mapping[str, Any]) -> tuple[str | None, str | None]:
    """(away, home) canonical keys of the chip: its own `key`, else its name through `chip_join_key`."""
    out = []
    for side in ("away", "home"):
        team = _side(chip, side)
        key = str(team.get("key") or "").strip().lower() or None
        out.append(key or _join_key(sport, team.get("name")))
    return out[0], out[1]


def _pair_matches(sport: str, chip: Mapping[str, Any], away: Any, home: Any) -> int:
    """+1 when (away, home) is the chip's pair, -1 when it is the chip's pair reversed, 0 otherwise."""
    chip_away, chip_home = _chip_pair(sport, chip)
    if not chip_away or not chip_home:
        return 0
    a, h = _join_key(sport, away), _join_key(sport, home)
    if (a, h) == (chip_away, chip_home):
        return 1
    if (a, h) == (chip_home, chip_away):
        return -1
    return 0


def _flip_segments(segments: Mapping[str, Any]) -> dict[str, Any]:
    """Per-side segments restated in the other frame (home <-> away). Only per-side means survive a flip."""
    out: dict[str, Any] = {}
    for name, block in (segments or {}).items():
        if not isinstance(block, Mapping):
            continue
        for home_key, away_key in _PER_SIDE_KEYS:
            if home_key in block and away_key in block:
                out[name] = {home_key: block[away_key], away_key: block[home_key]}
                break
    return out


# -- soccer pregame: soccersim's simulated half goals

def _soccer_pregame_matches(league: str, day: str) -> dict[str, Any] | None:
    """`{event id: match}` from one league-day's recommendations artifact, plus `_generated_at`. None if absent."""
    from syndicate.features.soccer.sources import recommendations_path

    payload = _read_json_unchanged(recommendations_path(league, day))
    if not isinstance(payload, Mapping):
        return None
    out: dict[str, Any] = {"_generated_at": payload.get("generated_at")}
    for match in payload.get("matches") or []:
        if isinstance(match, Mapping):
            key = str(match.get("event_id") or match.get("match_id") or "").strip()
            if key:
                out[key] = match
    return out


def _soccer_pregame_block(chip: Mapping[str, Any], date_value: str) -> dict[str, Any] | None:
    league = str(chip.get("league") or "").strip().lower()
    key = str(chip.get("game_key") or "").strip()
    if not league:
        return None
    for day in _chip_days(chip, date_value):
        matches = _cached(("pregame", "soccer", league, day), _TTL_PREGAME_SECONDS,
                          lambda lg=league, d=day: _soccer_pregame_matches(lg, d))
        if not matches:
            continue
        match = matches.get(key) if key else None
        if not isinstance(match, Mapping):
            match = next((m for k, m in matches.items() if k != "_generated_at" and isinstance(m, Mapping)
                          and _pair_matches("soccer", chip, (m.get("matchup") or {}).get("away_team"),
                                            (m.get("matchup") or {}).get("home_team")) == 1), None)
        if not isinstance(match, Mapping):
            continue
        team = match.get("team_projection") or {}
        total, margin = _f(team.get("total_mean")), _f(team.get("margin_mean"))
        win = match.get("win_probability") or {}
        return build_block("soccer", source=SOURCE_PREGAME, segments=match.get("periods") or {},
                           final_total=total, final_margin=margin, home_win_prob=_f(win.get("home")),
                           draw_prob=_f(win.get("draw")), away_win_prob=_f(win.get("away")),
                           as_of=matches.get("_generated_at"), sims=match.get("simulations"))
    return None


# -- live snapshots with a projected final only (no per-period output)

#: Where each live producer publishes (keyvalue-backed via `read_json_file`).
_OTHER_LIVE_PATHS: dict[str, str] = {
    "soccer": "soccer_live_lens.json",
    "nhl": "nhl_live_lens.json",
    "ncaaf": "ncaaf_live_lens.json",
    "nfl": "nfl_live_resim.json",
}


def _other_live_snapshot(sport: str) -> dict[str, Any] | None:
    from syndicate.features.shared.refresh_state_store import data_root, read_json_file

    name = _OTHER_LIVE_PATHS.get(sport)
    if not name:
        return None
    snapshot = read_json_file(data_root() / "live" / name)
    return snapshot if isinstance(snapshot, Mapping) else None


def _snapshot_is_for(snapshot: Mapping[str, Any], chip: Mapping[str, Any], date_value: str) -> bool:
    """A live snapshot answers only for its own slate, give or take a day: a stale one would show an old projection.

    A day either way because the producers stamp `date` by different clocks -- measured 2026-11-08 00:10Z, the
    NCAAF lens said `2026-11-08` (UTC) over the Central 11-07 slate and the NHL lens `2026-11-07`. The team-pair match
    is what picks the game; this only refuses a snapshot left over from another slate.
    """
    from datetime import date as _date

    day = str(snapshot.get("date") or "")[:10]
    if not day:
        return True
    try:
        snap_day = _date.fromisoformat(day)
    except ValueError:
        return False
    for chip_day in _chip_days(chip, date_value):
        try:
            if abs((_date.fromisoformat(chip_day) - snap_day).days) <= 1:
                return True
        except ValueError:
            continue
    return False


def _soccer_live_block(chip: Mapping[str, Any], snapshot: Mapping[str, Any] | None, date_value: str) -> dict[str, Any] | None:
    if not isinstance(snapshot, Mapping) or not _snapshot_is_for(snapshot, chip, date_value):
        return None
    key = str(chip.get("game_key") or "").strip()
    league = str(chip.get("league") or "").strip().lower()
    for game in snapshot.get("games") or []:
        if not isinstance(game, Mapping) or str(game.get("event_id") or "").strip() != key:
            continue
        if league and str(game.get("league") or "").strip().lower() not in ("", league):
            continue
        proj = game.get("projection")
        if not isinstance(proj, Mapping):
            return None
        home, away = _f(proj.get("projected_final_home_goals")), _f(proj.get("projected_final_away_goals"))
        if home is None or away is None:
            return None
        return build_block("soccer", source=SOURCE_LIVE, segments={}, final_total=home + away,
                           final_margin=home - away, home_win_prob=_f(proj.get("home_win_probability")),
                           draw_prob=_f(proj.get("draw_probability")), away_win_prob=_f(proj.get("away_win_probability")),
                           as_of=snapshot.get("generated_at"), sims=proj.get("simulations"), final_only_ok=True)
    return None


def _resim_lane(sport: str, game: Mapping[str, Any]) -> Mapping[str, Any] | None:
    """The game's live re-sim lane with a projection, or None (a refused lane carries none)."""
    for lane in game.get("gameLens") or []:
        if not isinstance(lane, Mapping) or lane.get("source") != SOURCE_LIVE:
            continue
        if not isinstance(lane.get("projection"), Mapping):
            continue
        # NFL's lane has no `key` and states success as `ok`; NHL and NCAAF key theirs "live".
        if sport == "nfl" and lane.get("ok") is False:
            continue
        if sport != "nfl" and lane.get("key") != "live":
            continue
        return lane
    return None


def _final_only_live_block(sport: str, chip: Mapping[str, Any], snapshot: Mapping[str, Any] | None,
                           date_value: str) -> dict[str, Any] | None:
    """NHL / NCAAF / NFL live: the re-sim's projected final (no period output), matched by team pair."""
    if not isinstance(snapshot, Mapping) or not _snapshot_is_for(snapshot, chip, date_value):
        return None
    for game in snapshot.get("games") or []:
        if not isinstance(game, Mapping):
            continue
        orientation = _pair_matches(sport, chip, game.get("away_name"), game.get("home_name"))
        if orientation == 0 and sport == "nfl":
            orientation = _pair_matches(sport, chip, game.get("away_code"), game.get("home_code"))
        if orientation != 1:
            # A reversed pair is a different frame; these producers key by the live feed's own home team, so a
            # reversal means the join is wrong rather than the venue -- no block.
            continue
        lane = _resim_lane(sport, game)
        if lane is None:
            return None
        projection = lane["projection"]
        total, margin = _f(projection.get("total")), _f(projection.get("homeMargin"))
        if total is None or margin is None:
            return None
        win = None if sport in LIVE_WIN_WITHHELD else _f(lane.get("modelHomeWinProb"))
        return build_block(sport, source=SOURCE_LIVE, segments={}, final_total=total, final_margin=margin,
                           home_win_prob=win, as_of=lane.get("liveStateAsOf") or lane.get("as_of"),
                           sims=lane.get("simsRun"), final_only_ok=True)
    return None


# -- nhl pregame: hockeysim's projected final

def _nhl_pregame(day: str) -> Any:
    from syndicate.features.nhl.game_projections import load_nhl_game_projections

    return load_nhl_game_projections(day)


def _nhl_pregame_block(chip: Mapping[str, Any], date_value: str) -> dict[str, Any] | None:
    for day in _chip_days(chip, date_value):
        index = _cached(("pregame", "nhl", day), _TTL_PREGAME_SECONDS, lambda d=day: _nhl_pregame(d))
        if index is None or not getattr(index, "by_pair", None):
            continue
        entry = index.lookup(_side(chip, "home").get("name"), _side(chip, "away").get("name"))
        if entry is None:
            continue
        # `lookup` restates a reversed pair in the board's frame (`NhlGameProjectionEntry.oriented`).
        return build_block("nhl", source=SOURCE_PREGAME, segments={}, final_total=entry.model_total,
                           final_margin=entry.model_spread, home_win_prob=entry.p_home_ml, final_only_ok=True)
    return None


# -- nfl / ncaaf pregame: smartsim2's simulated quarters

def _nfl_segment_blocks() -> dict[str, Any]:
    """`{"by_id": {game id: block}, "by_pair": {(season, home, away): block}}` over every weekly artifact."""
    from syndicate.features.shared.nfl_segment_projections import load_nfl_segment_blocks

    by_pair = load_nfl_segment_blocks() or {}
    return {"by_pair": by_pair,
            "by_id": {str(b.get("game_id")): b for b in by_pair.values() if isinstance(b, Mapping) and b.get("game_id")}}


def _nfl_pregame_block(chip: Mapping[str, Any]) -> dict[str, Any] | None:
    from syndicate.features.shared.nfl_segment_projections import _season_for, _team_key

    blocks = _cached(("pregame", "nfl"), _TTL_PREGAME_SECONDS, _nfl_segment_blocks)
    if not blocks:
        return None
    block = blocks["by_id"].get(str(chip.get("game_key") or "").strip())
    if block is None:
        season = _season_for(chip.get("start_time_utc"))
        home = _team_key(_side(chip, "home").get("name")) or _team_key(_side(chip, "home").get("abbr"))
        away = _team_key(_side(chip, "away").get("name")) or _team_key(_side(chip, "away").get("abbr"))
        block = blocks["by_pair"].get((season, home, away)) if season and home and away else None
    if not isinstance(block, Mapping) or not isinstance(block.get("segments"), Mapping):
        return None
    return _football_block("nfl", block["segments"], block.get("sims"))


def _ncaaf_pregame(day: str) -> Any:
    from syndicate.features.ncaaf.segment_projections import load_ncaaf_segment_inputs

    blocks, game_ids = load_ncaaf_segment_inputs(day)
    return {"blocks": blocks or {}, "game_ids": game_ids or {}}


def _ncaaf_pregame_block(chip: Mapping[str, Any], date_value: str) -> dict[str, Any] | None:
    from syndicate.features.ncaaf.game_projections import _norm

    home, away = _norm(_side(chip, "home").get("name")), _norm(_side(chip, "away").get("name"))
    if not home or not away:
        return None
    for day in _chip_days(chip, date_value):
        inputs = _cached(("pregame", "ncaaf", day), _TTL_PREGAME_SECONDS, lambda d=day: _ncaaf_pregame(d))
        if not inputs or not inputs.get("blocks"):
            continue
        flipped = False
        game_id = inputs["game_ids"].get((home, away))
        if game_id is None:
            game_id = inputs["game_ids"].get((away, home))
            flipped = game_id is not None
        block = inputs["blocks"].get(str(game_id)) if game_id is not None else None
        if not isinstance(block, Mapping) or not isinstance(block.get("segments"), Mapping):
            continue
        segments = _flip_segments(block["segments"]) if flipped else block["segments"]
        return _football_block("ncaaf", segments, block.get("sims"))
    return None


def _football_block(sport: str, segments: Mapping[str, Any], sims: Any) -> dict[str, Any] | None:
    total, margin = _segment_means(segments.get("full"))
    # No win probability: the board's football moneyline probability is the projections CSV's (`home_win_rate`,
    # or NCAAF's blend), and a second number for the same game from this sidecar would contradict it.
    return build_block(sport, source=SOURCE_PREGAME, segments=segments, final_total=total, final_margin=margin,
                       home_win_prob=None, sims=sims)


# -- mlb pregame: the daily sim's first-N-innings segments

def _mlb_daily_summary(day: str) -> dict[str, Any] | None:
    """`{game_pk: output row}` from `daily_summary_<day>.json`, read ONLY.

    Not `mlb.sources.daily_artifact_path`: that resolver copies a newer file between roots as a side effect, and
    this runs on web as well as the worker.
    """
    from syndicate.features.mlb.sources import _artifact_roots, _source_roots

    name = f"daily_summary_{day.replace('-', '_')}.json"
    for root in [*_artifact_roots(), *_source_roots()]:
        payload = _read_json_unchanged(root / "data" / "daily" / name)
        if not isinstance(payload, Mapping):
            continue
        rows = payload.get("outputs")
        out: dict[str, Any] = {"_generated_at": payload.get("generated_at")}
        for row in rows or []:
            if isinstance(row, Mapping) and row.get("game_pk") is not None:
                out[str(row["game_pk"]).strip()] = row
        return out
    return None


def _mlb_pregame_block(chip: Mapping[str, Any], date_value: str) -> dict[str, Any] | None:
    key = str(chip.get("game_key") or "").strip()
    if not key:
        return None
    for day in _chip_days(chip, date_value):
        summary = _cached(("pregame", "mlb", day), _TTL_PREGAME_SECONDS, lambda d=day: _mlb_daily_summary(d))
        row = (summary or {}).get(key)
        if not isinstance(row, Mapping):
            continue
        segments = {"f1": row.get("first1"), "f3": row.get("first3"), "f5": row.get("first5")}
        full = row.get("full") if isinstance(row.get("full"), Mapping) else {}
        total, margin = _segment_means(full)
        return build_block("mlb", source=SOURCE_PREGAME, segments=segments, final_total=total, final_margin=margin,
                           home_win_prob=_f(full.get("home_win_prob")), as_of=summary.get("_generated_at"))
    return None


def _other_sport_block(sport: str, chip: Mapping[str, Any], state: Any, date_value: str) -> dict[str, Any] | None:
    if state == "live":
        if sport == "mlb":
            return None  # see OTHER_SPORTS_SOURCES: no verified live reader yet
        snapshot = _cached(("live", sport), _TTL_LIVE_SECONDS, lambda s=sport: _other_live_snapshot(s))
        if sport == "soccer":
            return _soccer_live_block(chip, snapshot, date_value)
        return _final_only_live_block(sport, chip, snapshot, date_value)
    if state != "pregame":
        return None
    if sport == "soccer":
        return _soccer_pregame_block(chip, date_value)
    if sport == "nhl":
        return _nhl_pregame_block(chip, date_value)
    if sport == "nfl":
        return _nfl_pregame_block(chip)
    if sport == "ncaaf":
        return _ncaaf_pregame_block(chip, date_value)
    if sport == "mlb":
        return _mlb_pregame_block(chip, date_value)
    return None


# ------------------------------------------------------------------------------------------- attach

def attach_interval_projections(chips: Iterable[dict[str, Any]], date_value: str, *, live_only: bool = False) -> dict[str, int]:
    """Put an `intervals` block on every chip whose game has a sim; remove a stale one that no longer does.

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
        if sport not in INTERVAL_SPORTS:
            continue
        state = chip.get("state")
        if live_only and state != "live":
            continue
        block = None
        if sport in OTHER_INTERVAL_SPORTS:
            try:
                block = _other_sport_block(sport, chip, state, date_value)
            except Exception:  # noqa: BLE001 -- one sport's unreadable source must never cost another's blocks
                bump(f"{sport}:error")
                block = None
        elif state == "live":
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
