from __future__ import annotations

import csv
import json
import os
import re
import statistics
from datetime import datetime
from typing import Any
from functools import lru_cache
from pathlib import Path

from syndicate.features.shared.timezone import CENTRAL_TIMEZONE

from syndicate.features.ncaaf.sources import available_weeks
from syndicate.features.ncaaf.sources import build_module_links
from syndicate.features.ncaaf.sources import default_ncaaf_source_root
from syndicate.features.ncaaf.sources import default_season
from syndicate.features.ncaaf.sources import _legacy_default_season_from_summary_index
from syndicate.features.ncaaf.sources import default_week
from syndicate.features.ncaaf.sources import ncaaf_week_and_card_keys_for_date
from syndicate.features.ncaaf.sources import format_moneyline
from syndicate.features.ncaaf.sources import format_num
from syndicate.features.ncaaf.sources import format_pct
from syndicate.features.ncaaf.sources import load_json
from syndicate.features.ncaaf.sources import ncaaf_target_week
from syndicate.features.ncaaf.sources import summary_path
from syndicate.features.football.sim_engine.smartsim2.historical_truth.ncaaf_historical_loader import load_games_season
from syndicate.features.ncaaf import props as ncaaf_props
from syndicate.features.ncaaf.smartsim2_blend import compute_blend
from syndicate.features.ncaaf.smartsim2_projection import CONSENSUS_SOURCE_LABEL
from syndicate.features.ncaaf.smartsim2_projection import LEGACY_ENGINE_SOURCE_LABEL
from syndicate.features.ncaaf.smartsim2_projection import SMARTSIM2_PUBLIC_LABEL
from syndicate.features.ncaaf.smartsim2_projection import SMARTSIM2_SOURCE_LABEL
from syndicate.features.ncaaf.smartsim2_projection import SmartSimNcaafProjection
from syndicate.features.ncaaf.smartsim2_projection import read_projection_artifact
from syndicate.features.ncaaf.smartsim2_trial_monitoring import record_trial_page_view
from syndicate.features.shared.discrete_nav import neighboring_values
from syndicate.features.shared.discrete_nav import resolve_selected_value
from syndicate.features.shared.game_board_contract import NULL_PLACEHOLDER
from syndicate.features.shared.game_board_contract import apply_game_board_contract
from syndicate.features.shared.market_inventory import join_odds_to_sim
from syndicate.features.shared.team_branding import read_team_branding_snapshot
from syndicate.features.shared.team_branding import team_branding_index_by_id


_WEEK1_PUBLISHABLE_MATCHUPS = {
    ("Western Michigan", "Michigan State"),
    ("Kennesaw State", "Wake Forest"),
    ("UNLV", "Sam Houston"),
    ("San Jose State", "Central Michigan"),
    ("Tennessee", "Syracuse"),
    ("Ball State", "Purdue"),
    ("Coastal Carolina", "Virginia"),
    ("Eastern Michigan", "Texas State"),
}

_WEEK1_SUPPRESSED_MATCHUPS = {
    ("Tarleton State", "Army"),
    ("Bethune-Cookman", "Florida International"),
    ("Nicholls", "Troy"),
    ("SE Louisiana", "Louisiana Tech"),
    ("Bryant", "New Mexico State"),
}

_WEEK1_COVERAGE_PROFILE = {
    "publishable": {
        "coverage_score": 1.0,
        "coverage_tier": "A",
        "publication_status": "publishable",
        "publication_priority": 3,
    },
    "suppressed": {
        "coverage_score": 0.675,
        "coverage_tier": "C",
        "publication_status": "suppressed",
        "publication_priority": 1,
    },
}


_NCAAF_CARD_CONTRACT_VERSION = "1"


@lru_cache(maxsize=1)
def _prediction_rows() -> tuple[dict[str, Any], ...]:
    data_root = default_ncaaf_source_root() / "data"
    if not data_root.exists():
        return ()
    candidate_paths = sorted(
        data_root.glob("college_football_schedule_*_predicted_totals_enhanced*.csv"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    fallback_rows: tuple[dict[str, Any], ...] = ()
    for path in candidate_paths:
        try:
            with path.open("r", encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                headers = set(reader.fieldnames or [])
                required = {"home_team", "away_team", "predicted_home_points", "predicted_away_points", "predicted_total_points"}
                if not required.issubset(headers):
                    continue
                rows = tuple(dict(row) for row in reader)
                if "model_home_win_prob" in headers:
                    return rows
                if not fallback_rows:
                    fallback_rows = rows
        except Exception:
            continue
    return fallback_rows


@lru_cache(maxsize=1)
def _prediction_source_path() -> Path | None:
    data_root = default_ncaaf_source_root() / "data"
    if not data_root.exists():
        return None
    candidate_paths = sorted(
        data_root.glob("college_football_schedule_*_predicted_totals_enhanced*.csv"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for path in candidate_paths:
        try:
            with path.open("r", encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                headers = set(reader.fieldnames or [])
                required = {"home_team", "away_team", "predicted_home_points", "predicted_away_points", "predicted_total_points"}
                if required.issubset(headers):
                    return path
        except Exception:
            continue
    return None


_SMARTSIM2_PROJECTION_FILENAME_RE = re.compile(r"^smartsim2_projections_(\d{4})_wk(\d+)\.csv$")


def _smartsim2_standalone_seasons_and_weeks() -> dict[int, list[int]]:
    """Every (season, week) with a real, already-generated SmartSim 2.0
    projection artifact on disk -- independent of whether the legacy engine
    has any data for that season. The engine's own predicted-totals snapshot
    is only ever refreshed for its own season (see the 2026 season bootstrap:
    NCAAFCompare, the engine's real source, was unavailable), so this is the
    only reliable signal for "is there real projection data for a season the
    engine hasn't touched".

    Deliberately NOT lru_cache'd (confirmed live 2026-08-02: a
    maxsize=1-cached version returned an empty dict for the lifetime of a
    worker process once it had computed that result before this session's
    real 2026 files landed on Render's persistent disk via bootstrap --
    the cache never re-observed the new files without a full worker
    restart). New weeks get generated periodically by this session's own
    autorun trigger, so this needs to see the real directory contents on
    every call, same as syndicate.features.nfl.sources.week_summaries's
    equivalent, uncached, glob."""
    data_root = default_ncaaf_source_root() / "data"
    if not data_root.exists():
        return {}
    result: dict[int, list[int]] = {}
    for path in data_root.glob("smartsim2_projections_*_wk*.csv"):
        match = _SMARTSIM2_PROJECTION_FILENAME_RE.match(path.name)
        if not match:
            continue
        season = int(match.group(1))
        week = int(match.group(2))
        result.setdefault(season, []).append(week)
    for season in result:
        result[season] = sorted(set(result[season]))
    return result


def _engine_seasons_and_weeks() -> dict[int, list[int]]:
    result: dict[int, list[int]] = {}
    for row in _prediction_rows():
        try:
            season = int(str(row.get("season") or "").strip())
            week = int(str(row.get("week") or "").strip())
        except (TypeError, ValueError):
            continue
        result.setdefault(season, []).append(week)
    for season in result:
        result[season] = sorted(set(result[season]))
    return result


def _engine_rows_for_season_week(season: int, week: int) -> list[dict[str, Any]]:
    """Reuses ``_runtime_prediction_rows()``'s own completeness filtering and
    (away, home) dedup (a row missing predicted points, or a duplicate
    matchup, was never a valid engine row) and adds a season filter on top --
    harmless today (the engine CSV has only ever held one season), but
    required once its glob covers more than one season's file."""
    return [row for row in _runtime_prediction_rows(week) if str(row.get("season") or "").strip() == str(season)]


def _resolve_ncaaf_active_season_and_weeks() -> tuple[int, list[int]]:
    """The season/week source of truth for the runtime cards page: prefers
    whichever season has the most recent real data across *either* the
    legacy engine's predicted-totals snapshot or SmartSim 2.0's own
    projection artifacts, so a season the engine has no data for is still
    reachable once real SmartSim 2.0 projections exist for it."""
    engine_seasons = _engine_seasons_and_weeks()
    smartsim2_seasons = _smartsim2_standalone_seasons_and_weeks()
    all_seasons = set(engine_seasons) | set(smartsim2_seasons)
    if not all_seasons:
        # Not default_season() -- that now calls back into this function,
        # which would recurse forever when neither source has any data.
        return (_legacy_default_season_from_summary_index() or 2025), []
    active_season = max(all_seasons)
    weeks = sorted(set(engine_seasons.get(active_season, [])) | set(smartsim2_seasons.get(active_season, [])))
    # Navigation must not offer a week the board will refuse to populate.
    # `_smartsim2_projection_index` returns {} beyond the pregame window, so
    # without this filter a stale future-week artifact left on the mounted disk
    # still appears in the week list and resolves to a page with zero games --
    # a label and a body that disagree, which reads as an outage rather than as
    # "not simmed yet". Keep at least one week so the board never navigates to
    # nothing at all.
    in_window = [w for w in weeks if _week_is_within_pregame_window(active_season, w)]
    return active_season, (in_window or weeks[:1])


def _ncaaf_default_active_week(season: int, weeks: list[int]) -> int:
    """Prefer the real calendar-driven target week (mirrors
    syndicate.features.nfl.sources.default_week's own fix) over "last
    available week" -- once a season's whole real schedule has generated
    SmartSim 2.0 projections, "last available" degenerates to the season
    finale even during the offseason/preseason. Falls back to "last
    available" once every real game has a final score or the real season
    isn't loaded yet."""
    if not weeks:
        return 1
    target = ncaaf_target_week(season)
    if target is not None and target in weeks:
        return target
    return weeks[-1]


def _smartsim2_standalone_market_lines(
    season: int,
    week: int,
    *,
    kickoff_dates: tuple[str, ...] = (),
) -> dict[tuple[str, str], dict[str, float | None]]:
    """Market lines for one week, OddsAPI first and CFBD as the fallback.

    `#557`. The CFBD path below is kept and still tried, but it has had NO
    PRODUCER on any service since it was written -- `fetch_ncaaf_market_lines.py`
    and `fetch_cfbd_lines.py` have zero callers, and no `cfbd_lines_*.json`
    exists in git at any SHA -- which is why `markets` was null on 0-of-51 games
    and candidate generation produced 0 rows.

    OddsAPI lines arrive through the SHARED QUOTE LOG rather than a file of
    their own, so the same capture feeds these cards and Layer 1's book grid,
    and so the artifact crosses worker->web on an allowlist glob that already
    matches NCAAF (`*_source/tracking/book_quotes/*.jsonl`).

    ORDER MATTERS AND IS DELIBERATE. OddsAPI wins when it has the game: it is
    the live-captured source, while any CFBD file that ever appears would be a
    hand-run snapshot. The two are MERGED PER GAME, not chosen wholesale, so a
    game OddsAPI does not carry still gets a CFBD line if one exists.
    """
    merged: dict[tuple[str, str], dict[str, float | None]] = {}
    try:
        from syndicate.features.ncaaf.oddsapi_lines import load_week_line_index

        merged.update(
            load_week_line_index(
                season,
                week,
                key_fn=_normalize_text,
                kickoff_dates=kickoff_dates,
            )
        )
    except Exception:
        # A quote-log failure must not empty a board that CFBD could still fill.
        merged = {}

    data_root = default_ncaaf_source_root() / "data"
    path = data_root / f"cfbd_lines_{season}_wk{week}.json"
    if not path.exists():
        return merged
    try:
        with path.open("r", encoding="utf-8") as handle:
            games = json.load(handle)
    except Exception:
        return merged
    index: dict[tuple[str, str], dict[str, float | None]] = {}
    if not isinstance(games, list):
        return merged
    for game in games:
        if not isinstance(game, dict):
            continue
        lines = game.get("lines") if isinstance(game.get("lines"), list) else []
        spreads = [line["spread"] for line in lines if isinstance(line, dict) and line.get("spread") is not None]
        totals = [line["overUnder"] for line in lines if isinstance(line, dict) and line.get("overUnder") is not None]
        market_margin = -statistics.mean(spreads) if spreads else None
        market_total = statistics.mean(totals) if totals else None
        # Moneyline prices aren't averaged across providers the way
        # spread/total are (American odds don't average meaningfully) --
        # take the first provider line that actually quotes both sides.
        home_moneyline = None
        away_moneyline = None
        for line in lines:
            if not isinstance(line, dict):
                continue
            if line.get("homeMoneyline") is not None and line.get("awayMoneyline") is not None:
                home_moneyline = line.get("homeMoneyline")
                away_moneyline = line.get("awayMoneyline")
                break
        key = (_normalize_text(game.get("homeTeam")), _normalize_text(game.get("awayTeam")))
        index[key] = {
            "market_margin": market_margin,
            "market_total": market_total,
            "home_moneyline": home_moneyline,
            "away_moneyline": away_moneyline,
        }
    # Per-GAME merge, OddsAPI winning: a CFBD snapshot fills only the games the
    # live capture does not carry, and never overwrites a live-captured price.
    for cfbd_key, cfbd_value in index.items():
        merged.setdefault(cfbd_key, cfbd_value)
    return merged


@lru_cache(maxsize=8)
def _ncaaf_week_kickoff_dates(season: int, week: int) -> tuple[str, ...]:
    """The calendar dates a week's games actually kick off on.

    The quote log is sharded by DATE and this board is scoped by WEEK, and for
    NCAAF those spans differ sharply: 2026 week 1 runs 08-29 to 09-07, so a date
    window guessed from the week number would miss most of the slate. Taken off
    the schedule rather than computed.

    Not filtered to FBS-vs-FBS: an extra date costs one absent-file check, while
    a missing one costs every game on it its line.
    """
    try:
        schedule = load_games_season(season)
    except Exception:
        return ()
    return tuple(
        dict.fromkeys(
            # `.split("T")[0]`, not `[:10]`: `#525`'s guard test scans this
            # file for board-sized slice caps and a bare `[:10]` trips it. It is
            # right to -- the check cannot tell an ISO date prefix from a slate
            # cap, and weakening it to admit this would blunt the thing that
            # catches a real row-budget cliff. Splitting on the separator says
            # what is meant anyway, and handles a bare "YYYY-MM-DD" unchanged.
            str(game.get("startDate") or "").split("T")[0]
            for game in schedule
            if isinstance(game, dict) and game.get("week") == week and game.get("startDate")
        )
    )


def _smartsim2_standalone_rows(season: int, week: int) -> list[dict[str, Any]]:
    """Real schedule + real SmartSim 2.0 projections, joined directly --
    used only for a (season, week) the legacy engine has no rows for, so
    this never overrides or competes with the engine's own path."""
    try:
        schedule = load_games_season(season)
    except Exception:
        return []
    projection_index = _smartsim2_projection_index(season, week)
    if not projection_index:
        return []
    # The quote log is sharded by CALENDAR DATE and this board is scoped by
    # WEEK, and for NCAAF those are very different spans: 2026 week 1 runs
    # 08-29 to 09-07, so a date window guessed from the week number would drop
    # most of the slate. Take the dates off the schedule we are already holding.
    lines_index = _smartsim2_standalone_market_lines(
        season, week, kickoff_dates=_ncaaf_week_kickoff_dates(season, week)
    )
    rows: list[dict[str, Any]] = []
    for game in schedule:
        if not isinstance(game, dict) or game.get("week") != week:
            continue
        if game.get("homeClassification") != "fbs" or game.get("awayClassification") != "fbs":
            continue
        home_team = str(game.get("homeTeam") or "").strip()
        away_team = str(game.get("awayTeam") or "").strip()
        if not home_team or not away_team:
            continue
        key = (_normalize_text(home_team), _normalize_text(away_team))
        projection = projection_index.get(key)
        if projection is None:
            continue
        market = lines_index.get(key, {"market_margin": None, "market_total": None})
        rows.append(
            {
                "game_id": str(game.get("id") or f"{season}_{week}_{home_team}_{away_team}"),
                "home_team": home_team,
                "away_team": away_team,
                "start_date": game.get("startDate"),
                "venue": game.get("venue"),
                "projection": projection,
                "market_margin": market.get("market_margin"),
                "market_total": market.get("market_total"),
                "home_moneyline": market.get("home_moneyline"),
                "away_moneyline": market.get("away_moneyline"),
                "market_book_count": market.get("book_count"),
                "market_source": market.get("source"),
            }
        )
    return rows


_NCAAF_MARKET_BOARD_DISPLAY_LABELS = {
    "moneyline_home": "Moneyline",
    "moneyline_away": "Moneyline",
    "spread": "Spread",
    "total": "Total",
}


def _ncaaf_cover_probability(*, line: float, mean: float | None, stdev: float | None) -> float | None:
    """P(actual > line) under a Normal(mean, stdev) model -- used for both
    "home covers this spread" and "game goes over this total". None when
    there's no real distribution to draw the probability from (no stdev
    available yet, e.g. no SmartSim 2.0 shadow data for this game), rather
    than fabricating one from the point estimate alone: a raw margin/total
    point value (e.g. 57.9 projected points) is not a probability and must
    never be dropped into a 0-1 field the board renders as a percentage.
    """
    if mean is None or stdev is None or stdev <= 0:
        return None
    return 1.0 - statistics.NormalDist(mean, stdev).cdf(line)


def _market_metric_row(margin: float | None) -> dict[str, Any] | None:
    """The market spread as a compact-card metric: a SIGNED HOME SPREAD.

    THE VALUE MUST FIT IN ABOUT SIX CHARACTERS, and that constraint drove the
    format rather than taste. `.cards-mini-metrics--strip` is
    `repeat(3, minmax(0, 1fr))` with a 15px value font, so a strip tile shows
    roughly six characters and CLIPS the rest with no wrap and no ellipsis
    (`#549`, pre-existing -- the model's own "Projected total 50.3" was already
    losing its last character). Measured on the rendered board: "TCU -14.9"
    came out as "TC -14", and "North Dakota State -14.8" overran the
    neighbouring tile entirely. Promoting this row into `metrics[:3]`, where
    only short values had ever lived, is what exposed it.

    The fix belongs in `dense_cards.css`, which is another lane's file, so the
    format adapts instead: "-14.9" is the standard compact spread notation
    (negative = home favoured), it is unambiguous with "AWAY @ HOME" printed
    directly above it, and it fits. The MAIN card's `market_tiles` have room and
    keep the explicit favourite-side form ("TCU -14.9").

    None when no book has quoted it, so the caller drops the row rather than
    rendering a tile that says "-" -- an empty tile reads as a broken card,
    while a missing one just means the model rows move up.
    """
    if margin is None:
        return None
    if margin == 0:
        return {"label": "Market spread", "value": "PK"}
    # `-margin`: a home margin of +14.9 (home favoured) is a home spread of -14.9.
    return {"label": "Market spread", "value": f"{-margin:+.1f}"}


def _smartsim2_standalone_market_tiles(row: dict[str, Any], projection: Any = None) -> list[dict[str, Any]]:
    """The four header tiles, showing the real line once one exists.

    These used to be four hardcoded placeholders ("Source / Tier / Status /
    Priority") because there was never a price to put in them. Now that there
    can be, the first two carry it -- and when there is still no line they say
    so plainly rather than showing a dash that reads as a broken tile.
    """
    margin = _safe_float(row.get("market_margin"))
    total = _safe_float(row.get("market_total"))
    books = row.get("market_book_count") or 0

    if margin is None:
        spread_title, spread_sub = "No line", "No book quoted yet"
    else:
        # Shown from the FAVOURITE's side, which is how a spread is read aloud.
        favourite = row.get("home_team") if margin > 0 else row.get("away_team")
        spread_title = "Pick'em" if margin == 0 else f"{favourite} -{abs(margin):.1f}"
        spread_sub = f"Market spread - {books} book{'s' if books != 1 else ''}"

    # MODEL AGAINST MARKET, which is what a compact card is FOR. Two of these
    # four tiles used to be metadata -- "Source: SmartSim 2.0" and a book count
    # -- so a card could carry a full projection and a full market line and
    # show the reader neither of them side by side. MLB's card is the
    # reference: `cards-market-row` puts the comparison above the fold.
    #
    # This is only possible now because the projection reaches the shared
    # contract at all; before 2026-08-27 `shared_predictions.margin_mean` and
    # `.total_mean` were null on 51/51 cards.
    model_margin = _safe_float(getattr(projection, "margin_mean", None))
    model_total = _safe_float(getattr(projection, "total_mean", None))
    home_team = row.get("home_team")
    away_team = row.get("away_team")

    # SIGN CONVENTION, stated because `state.md` records a whole NFL analysis
    # lost to it: BOTH margins are home-relative and positive means the home
    # side is favoured. The edge is model minus market, so positive = the model
    # likes the HOME side more than the book does.
    if model_margin is None:
        spread_model_sub = "No model spread"
    else:
        model_fav = home_team if model_margin > 0 else away_team
        model_spread_text = "Pick'em" if model_margin == 0 else f"{model_fav} -{abs(model_margin):.1f}"
        if margin is None:
            spread_model_sub = f"Model {model_spread_text}"
        else:
            spread_model_sub = f"Model {model_spread_text} · {model_margin - margin:+.1f} vs market"

    if model_total is None:
        total_model_sub = "No model total"
    elif total is None:
        total_model_sub = f"Model {model_total:.1f}"
    else:
        total_model_sub = f"Model {model_total:.1f} · {model_total - total:+.1f} vs market"

    home_win = _safe_float(getattr(projection, "home_win_rate", None))
    if home_win is None:
        win_title, win_sub = "No model", "Win probability unavailable"
    else:
        win_side = home_team if home_win >= 0.5 else away_team
        win_title = f"{win_side} {max(home_win, 1.0 - home_win) * 100:.0f}%"
        win_sub = "Model win probability"

    return [
        {"label": "Spread", "title": spread_title, "sub": spread_model_sub if model_margin is not None else spread_sub},
        {
            "label": "Total",
            "title": f"{total:.1f}" if total is not None else "No line",
            "sub": total_model_sub if model_total is not None else ("Market total" if total is not None else "No book quoted yet"),
        },
        {"label": "Win probability", "title": win_title, "sub": win_sub},
        {
            "label": "Books",
            "title": str(books) if books else "-",
            "sub": str(row.get("market_source") or "No market capture"),
        },
    ]


def _smartsim2_standalone_betting(row: dict[str, Any], projection: Any) -> dict[str, Any]:
    """The block `publication_adapter._shared_markets` actually reads.

    Keys are ITS vocabulary, not this module's: `home_ml`/`away_ml`,
    `home_spread`/`away_spread`, `total`, plus `p_*` probabilities. Renaming any
    of them here silently empties the board's market block, because a key that
    never resolves yields a null that is indistinguishable from "no book quoted
    this" -- the exact shape `learnings.md` 2026-08-21 was written about.

    THE SPREAD SIGN IS INVERTED ON PURPOSE. `market_margin` is a home margin
    (positive = home favoured); a book's `home_spread` is negative when home is
    favoured.

    Probabilities are the MODEL's, priced against the MARKET's line -- P(home
    covers the book's spread) and P(the game goes over the book's total) -- which
    is what makes an edge computable downstream. They stay None without a line,
    rather than being computed against the model's own number, which would
    compare the model to itself and read as a permanent edge of zero.
    """
    margin = _safe_float(row.get("market_margin"))
    total = _safe_float(row.get("market_total"))

    home_cover = away_cover = total_over = total_under = None
    if margin is not None:
        # `line=margin`, NOT `-margin`: home covers when the realised HOME MARGIN
        # beats the market's home margin, and both sides of this comparison are
        # already in home-margin space. `_ncaaf_market_board_rows_for_game`
        # (below) passes `margin_line` the same way, and the two must agree or
        # the card and the market board price the same game differently.
        # Caught by a sanity read, not by a test: the inverted form returned
        # P(cover)=0.97 for a game the model has the home side LOSING to the
        # spread by 4.6 points, which is plausible-looking and completely wrong.
        home_cover = _ncaaf_cover_probability(
            line=margin,
            mean=_safe_float(getattr(projection, "margin_mean", None)),
            stdev=_safe_float(getattr(projection, "margin_stdev", None)),
        )
        if home_cover is not None:
            away_cover = 1.0 - home_cover
    if total is not None:
        total_over = _ncaaf_cover_probability(
            line=total,
            mean=_safe_float(getattr(projection, "total_mean", None)),
            stdev=_safe_float(getattr(projection, "total_stdev", None)),
        )
        if total_over is not None:
            total_under = 1.0 - total_over

    home_win = _safe_float(getattr(projection, "home_win_rate", None))
    return {
        "home_ml": row.get("home_moneyline"),
        "away_ml": row.get("away_moneyline"),
        "home_spread": (-margin) if margin is not None else None,
        "away_spread": margin if margin is not None else None,
        "total": total,
        "p_home_win": home_win,
        "p_away_win": (1.0 - home_win) if home_win is not None else None,
        "p_home_cover": home_cover,
        "p_away_cover": away_cover,
        "p_total_over": total_over,
        "p_total_under": total_under,
    }


class _EngineRowProjection:
    """Duck-typed projection built from a LEGACY ENGINE ROW's own columns.

    WHY THIS EXISTS. `_ncaaf_shared_predictions_block` reads a projection
    OBJECT, and only `_smartsim2_standalone_rows` puts one on a row (:395).
    The engine path has no such object -- so after the NameError fix it
    published `{}` and served a board with no projected spread or total, which
    is the exact defect the shared-predictions work set out to remove.

    It was never a DATA gap. Legacy engine rows carry
    `predicted_home_points`, `predicted_away_points`, `predicted_total_points`,
    `predicted_win_margin` and `home_win_prob` -- the projection was there in
    columns the whole time, just not in the shape the helper reads.

    Found by session syndicate-27 while fixing a NameError I introduced in
    16673341. They fixed the crash correctly with `row.get("projection")` and
    asked whether `{}` was the intended end state for these paths. For the BET
    row it is -- a wager is not a game projection. For the ENGINE row it was
    not, and this closes it.

    NO STDEVS, deliberately. Engine rows carry no dispersion, so the cover and
    over probabilities stay None rather than being computed from a fabricated
    spread. Absent stays absent.
    """

    __slots__ = ("home_score_mean", "away_score_mean", "margin_mean", "total_mean",
                 "margin_stdev", "total_stdev", "home_win_rate")

    def __init__(self, row: dict[str, Any]) -> None:
        self.home_score_mean = _safe_float(row.get("predicted_home_points"))
        self.away_score_mean = _safe_float(row.get("predicted_away_points"))
        self.total_mean = _safe_float(row.get("predicted_total_points"))
        margin = _safe_float(row.get("predicted_win_margin"))
        if margin is None and self.home_score_mean is not None and self.away_score_mean is not None:
            margin = round(self.home_score_mean - self.away_score_mean, 3)
        self.margin_mean = margin
        self.margin_stdev = None
        self.total_stdev = None
        self.home_win_rate = _safe_float(row.get("home_win_prob") or row.get("home_win_probability"))


def _engine_row_projection(row: dict[str, Any]) -> Any:
    """`None` when the row has no projection at all, so `{}` still results."""
    if not isinstance(row, dict):
        return None
    projection = _EngineRowProjection(row)
    if projection.home_score_mean is None and projection.total_mean is None:
        return None
    return projection


def _ncaaf_shared_predictions_block(
    projection: Any,
    *,
    market_margin: Any = None,
    market_total: Any = None,
) -> dict[str, Any]:
    """The SHARED contract's `predictions` block, which NCAAF never populated.

    MEASURED ON PRODUCTION 2026-08-27, all 51 week-1 cards -- the numbers were
    on the card the whole time, in the wrong place:

        shared_predictions.home_mean    null  |  metrics["Home mean"]        30.3
        shared_predictions.away_mean    null  |  metrics["Away mean"]        20.0
        shared_predictions.margin_mean  null  |  metrics["Projected spread"] TCU by 10.3
        shared_predictions.total_mean   null  |  metrics["Projected total"]  50.3
        shared_predictions...home_win    0.8  |  the ONLY field that was set

    `metrics` is a DISPLAY list of label/value pairs. `shared_predictions` is
    what Layer 1, Layer 2, the compact cards and the market board read, so every
    cross-sport consumer saw a projected score of nothing and no projected
    spread or total -- on a betting product, the two numbers a line is actually
    compared against. `publication_adapter._shared_predictions` reads
    `predictions`, `sim.score`, `score` and `sim.periods.full`; NCAAF set none.

    ONE HELPER, THREE CALLERS. There are three NCAAF card-contract builders
    (`_build_ncaaf_card_contract`, `_build_smartsim_ncaaf_card_contract`,
    `_build_smartsim2_standalone_ncaaf_card_contract`) and a per-site copy is
    how one of them silently keeps the old behaviour. Market lines are optional
    because only the standalone builder has them in scope -- without them the
    means still publish and only the cover probabilities stay None, which is
    honest: absent must stay absent, never a neutral 0.5.

    Cover/over probabilities use `_ncaaf_cover_probability`, the same function
    the market board rows use, so the board and the contract cannot disagree
    about the same game.
    """
    if projection is None:
        return {}
    margin_mean = _safe_float(getattr(projection, "margin_mean", None))
    total_mean = _safe_float(getattr(projection, "total_mean", None))
    margin_stdev = _safe_float(getattr(projection, "margin_stdev", None))
    total_stdev = _safe_float(getattr(projection, "total_stdev", None))
    home_mean = _safe_float(getattr(projection, "home_score_mean", None))
    away_mean = _safe_float(getattr(projection, "away_score_mean", None))
    home_win = _safe_float(getattr(projection, "home_win_rate", None))

    home_cover = away_cover = total_over = total_under = None
    margin_line = _safe_float(market_margin)
    total_line = _safe_float(market_total)
    if margin_line is not None:
        home_cover = _ncaaf_cover_probability(line=margin_line, mean=margin_mean, stdev=margin_stdev)
        if home_cover is not None:
            away_cover = round(1.0 - home_cover, 6)
    if total_line is not None:
        total_over = _ncaaf_cover_probability(line=total_line, mean=total_mean, stdev=total_stdev)
        if total_over is not None:
            total_under = round(1.0 - total_over, 6)

    return {
        "home_mean": home_mean,
        "away_mean": away_mean,
        "margin_mean": margin_mean,
        "total_mean": total_mean,
        "margin_stdev": margin_stdev,
        "total_stdev": total_stdev,
        "probabilities": {
            "home_win": home_win,
            "away_win": (round(1.0 - home_win, 6) if home_win is not None else None),
            "home_cover": home_cover,
            "away_cover": away_cover,
            "total_over": total_over,
            "total_under": total_under,
        },
    }


def _ncaaf_market_board_rows_for_game(
    *,
    game_id: Any,
    market_margin: Any,
    market_total: Any,
    home_moneyline: Any,
    away_moneyline: Any,
    model_margin: Any,
    model_total: Any,
    model_margin_stdev: Any = None,
    model_total_stdev: Any = None,
    home_win_probability: Any,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Raw odds + sim rows for one NCAAF game's moneyline/spread/total
    markets -- mirrors syndicate.features.mlb.cards._mlb_market_board_rows_for_game.

    No player-prop rows: NCAAF has no props pipeline yet (a separate,
    not-yet-built phase). model_margin/model_total should already reflect
    whatever the caller considers the best available model signal (blended
    margin/total when present, degrading to SmartSim 2.0 or the legacy
    engine's own projection) -- this function doesn't itself choose between
    sources, only shapes whatever it's given into inventory rows.

    sim_projection on a spread/total row is only ever a real cover/over
    probability (via _ncaaf_cover_probability, when a stdev is available) --
    never the raw point projection, which belongs in projected_value
    instead (same contract MLB/NBA already use: sim_projection is always a
    0-1 fraction the board renders as a percent, projected_value is the raw
    count).
    """
    odds_rows: list[dict[str, Any]] = []
    sim_rows: list[dict[str, Any]] = []

    home_prob = _safe_float(home_win_probability)
    if home_moneyline is not None and away_moneyline is not None:
        odds_rows.append({"game_id": game_id, "market": "moneyline_home", "period": "full_game", "entity": None, "side": "home", "odds": home_moneyline, "market_type": "game"})
        odds_rows.append({"game_id": game_id, "market": "moneyline_away", "period": "full_game", "entity": None, "side": "away", "odds": away_moneyline, "market_type": "game"})
        if home_prob is not None:
            model_side = "home" if home_prob >= 0.5 else "away"
            sim_rows.append({"game_id": game_id, "market": "moneyline_home", "period": "full_game", "entity": None, "sim_projection": home_prob, "model_side": model_side, "sim_source": "ncaaf_model"})
            sim_rows.append({"game_id": game_id, "market": "moneyline_away", "period": "full_game", "entity": None, "sim_projection": 1.0 - home_prob, "model_side": model_side, "sim_source": "ncaaf_model"})

    margin_line = _safe_float(market_margin)
    if margin_line is not None:
        odds_rows.append({"game_id": game_id, "market": "spread", "period": "full_game", "entity": None, "side": "home", "line": margin_line, "market_type": "game"})
        model_margin_value = _safe_float(model_margin)
        if model_margin_value is not None:
            cover_prob = _ncaaf_cover_probability(line=margin_line, mean=model_margin_value, stdev=_safe_float(model_margin_stdev))
            sim_rows.append({"game_id": game_id, "market": "spread", "period": "full_game", "entity": None, "sim_projection": cover_prob, "projected_value": model_margin_value, "sim_source": "ncaaf_model"})

    total_line = _safe_float(market_total)
    if total_line is not None:
        odds_rows.append({"game_id": game_id, "market": "total", "period": "full_game", "entity": None, "side": "over", "line": total_line, "market_type": "game"})
        model_total_value = _safe_float(model_total)
        if model_total_value is not None:
            over_prob = _ncaaf_cover_probability(line=total_line, mean=model_total_value, stdev=_safe_float(model_total_stdev))
            sim_rows.append({"game_id": game_id, "market": "total", "period": "full_game", "entity": None, "sim_projection": over_prob, "projected_value": model_total_value, "sim_source": "ncaaf_model"})

    return odds_rows, sim_rows


def build_ncaaf_chip_games(context_label: str, *, season: int | None = None) -> list[dict[str, Any]]:
    """MINIMAL game dicts for the scoreboard chips. Builds no cards at all.

    ------------------------------------------------------------------
    WHY THIS EXISTS: THE CHIP PATH TOOK THE SITE DOWN
    ------------------------------------------------------------------

    `_NCAAFDataProvider.games()` answers the chips path with
    `build_smartsim_cards_page_context` PLUS `build_ncaaf_market_board` --
    roughly two full 51-game board builds, measured locally at **3.15s + 3.26s
    = 6.4s warm**. That was survivable only because the date resolver was
    broken and returned `[]` before reaching any of it: an accidental circuit
    breaker.

    Fixing the resolver (2026-08-29) removed the breaker and put that build on
    the HOME PAGE's request path behind a 30s TTL, on a 2GB display-only
    service with two gunicorn workers. Measured on production: `/` went
    **3.5s -> 37.9s** and `/ncaaf/cards` returned **502**. Reverted within
    minutes. Full account: `deploys.md` 2026-08-29 12:18 CT.

    ------------------------------------------------------------------
    A CHIP DOES NOT NEED A CARD
    ------------------------------------------------------------------

    `build_game_chip` reads only: the team pair, live/final flags, the two
    scores, a status token and a kickoff. It reads no projection, no market
    tile, no team context, no roster and no market board. Every expensive
    thing the card builder does is discarded before a chip is emitted.

    So this assembles those fields directly from the season schedule -- the
    same source, the same FBS gate and the same `f"{week}_{away}_{home}"` key
    formula the card builder uses, so a chip and its card cannot disagree about
    identity -- and then stamps live state through the ordinary ESPN join.

    `_team_context` is deliberately NOT called: it is the expensive part (roster
    counts, transfer counts, coach and returning-production joins per team) and
    a chip needs none of it. Branding is resolved directly, which is what
    supplies the ESPN team id the live-state join keys on.

    Returns `[]` for a date with no FBS games -- the same "no slate" answer the
    provider already gives, and never a fabricated one.
    """
    resolved_season = int(season) if season is not None else int(default_season())
    resolved = ncaaf_week_and_card_keys_for_date(resolved_season, context_label)
    if resolved is None:
        return []
    week, card_keys = resolved

    try:
        schedule = load_games_season(resolved_season)
    except Exception:
        return []

    games: list[dict[str, Any]] = []
    for row in schedule:
        if not isinstance(row, dict) or row.get("week") != week:
            continue
        if row.get("homeClassification") != "fbs" or row.get("awayClassification") != "fbs":
            continue
        home_team = str(row.get("homeTeam") or "").strip()
        away_team = str(row.get("awayTeam") or "").strip()
        if not home_team or not away_team:
            continue
        game_pk = f"{week}_{away_team}_{home_team}".replace(" ", "_")
        if game_pk not in card_keys:
            continue

        away_branding = _resolve_branding(str((_resolve_team(away_team) or {}).get("team_id") or ""))
        home_branding = _resolve_branding(str((_resolve_team(home_team) or {}).get("team_id") or ""))
        games.append(
            {
                "gamePk": game_pk,
                "card_variant": "ncaaf_main",
                # `status` is the week label until the ESPN join replaces it on
                # a started game -- identical to the full card's behaviour.
                "status": _week_label(week, season=resolved_season),
                "startTime": row.get("startDate"),
                "away": {
                    "abbr": _abbr(away_team),
                    "name": away_team,
                    # Carries the ESPN team id; the live-state join keys on it.
                    "logo_url": away_branding.logo_url if away_branding else None,
                },
                "home": {
                    "abbr": _abbr(home_team),
                    "name": home_team,
                    "logo_url": home_branding.logo_url if home_branding else None,
                },
            }
        )

    _attach_live_state(games, resolved_season, week)
    return games


def build_ncaaf_market_board(week: int) -> dict[str, Any]:
    """Layer 1 market/odds inventory for NCAAF game markets (moneyline,
    spread, total), one entry per game -- mirrors
    syndicate.features.mlb.cards.build_mlb_market_board. No player props:
    that pipeline doesn't exist for NCAAF yet.

    Reuses the same assembled game data build_smartsim_cards_page_context
    already produces for /ncaaf/cards -- not a new data source. Market
    lines are looked up independently per game via
    _smartsim2_standalone_market_lines (real CFBD sportsbook lines) rather
    than trusting whatever the upstream card-contract happened to attach,
    since the legacy-engine card path doesn't carry market_margin/
    market_total on its own scoreboard.
    """
    season, weeks = _resolve_ncaaf_active_season_and_weeks()
    resolved_week = resolve_selected_value(int(week or 0), weeks, _ncaaf_default_active_week(season, weeks) if weeks else default_week())
    context = build_smartsim_cards_page_context(resolved_week)
    games = context.get("games") if isinstance(context.get("games"), list) else []
    # The kickoff dates must be passed here too, and forgetting them is quiet
    # rather than loud: without them the OddsAPI index comes back EMPTY and this
    # board silently falls through to `scoreboard`'s copies of margin/total --
    # which exist, so spreads and totals still render while the MONEYLINE rows,
    # which have no scoreboard fallback, just never appear. Measured: 16 rows
    # over 8 games instead of 24.
    lines_index = _smartsim2_standalone_market_lines(
        season,
        resolved_week,
        kickoff_dates=_ncaaf_week_kickoff_dates(season, resolved_week),
    )

    board_games: list[dict[str, Any]] = []
    for game in games:
        if not isinstance(game, dict):
            continue
        ncaaf_card = game.get("ncaaf_card") if isinstance(game.get("ncaaf_card"), dict) else {}
        scoreboard = ncaaf_card.get("scoreboard") if isinstance(ncaaf_card.get("scoreboard"), dict) else {}
        away = game.get("away") if isinstance(game.get("away"), dict) else {}
        home = game.get("home") if isinstance(game.get("home"), dict) else {}
        away_name = str(away.get("name") or "").strip()
        home_name = str(home.get("name") or "").strip()
        away_abbr = str(away.get("abbr") or "AWY").strip().upper()
        home_abbr = str(home.get("abbr") or "HME").strip().upper()
        game_pk = game.get("gamePk")
        teams = ncaaf_card.get("teams") if isinstance(ncaaf_card.get("teams"), dict) else {}
        away_team_ctx = teams.get("away") if isinstance(teams.get("away"), dict) else {}
        home_team_ctx = teams.get("home") if isinstance(teams.get("home"), dict) else {}

        market = lines_index.get((_normalize_text(home_name), _normalize_text(away_name)), {})
        model_margin = scoreboard.get("blend_margin")
        if model_margin is None:
            model_margin = scoreboard.get("smartsim2_margin")
        model_total = scoreboard.get("blend_total")
        if model_total is None:
            model_total = scoreboard.get("smartsim2_total_points") or scoreboard.get("total_points")

        odds_rows, sim_rows = _ncaaf_market_board_rows_for_game(
            game_id=game_pk,
            market_margin=market.get("market_margin") if market.get("market_margin") is not None else scoreboard.get("market_margin"),
            market_total=market.get("market_total") if market.get("market_total") is not None else scoreboard.get("market_total"),
            home_moneyline=market.get("home_moneyline"),
            away_moneyline=market.get("away_moneyline"),
            model_margin=model_margin,
            model_total=model_total,
            model_margin_stdev=scoreboard.get("smartsim2_margin_stdev"),
            model_total_stdev=scoreboard.get("smartsim2_total_stdev"),
            home_win_probability=scoreboard.get("home_win_probability"),
        )
        inventory = join_odds_to_sim(odds_rows, sim_rows)
        for row in inventory:
            row["market"] = _NCAAF_MARKET_BOARD_DISPLAY_LABELS.get(row.get("market"), row.get("market"))

        board_games.append(
            {
                "gamePk": game_pk,
                "matchup": f"{away_abbr} @ {home_abbr}",
                "away_abbr": away_abbr,
                "home_abbr": home_abbr,
                "away_logo": away_team_ctx.get("logo_url"),
                "home_logo": home_team_ctx.get("logo_url"),
                "game_state": "live" if game.get("shared_is_live") else "pregame",
                "detail": game.get("detail"),
                "rows": inventory,
            }
        )

    return {
        "date": context.get("date") or f"week_{resolved_week}",
        "requested_date": context.get("date") or f"week_{resolved_week}",
        "week": resolved_week,
        "season": season,
        "available_weeks": weeks,
        "games": board_games,
        "using_sample_data": bool(context.get("using_sample_data")),
        "source_path": context.get("source_path"),
    }


def _prediction_weeks() -> list[int]:
    weeks = sorted(
        {
            int(str(row.get("week") or "0").strip() or 0)
            for row in _prediction_rows()
            if str(row.get("week") or "").strip().isdigit()
        }
    )
    return [week for week in weeks if week > 0]


@lru_cache(maxsize=1)
def _prediction_index() -> dict[tuple[str, str, str], dict[str, Any]]:
    index: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in _prediction_rows():
        week = str(row.get("week") or "").strip()
        home_team = _normalize_text(row.get("home_team"))
        away_team = _normalize_text(row.get("away_team"))
        if not week or not home_team or not away_team:
            continue
        index.setdefault((week, away_team, home_team), row)
    return index


_BLEND_TRIAL_DIAGNOSTICS_ENV_VAR = "SMARTSIM_BLEND_TRIAL_DIAGNOSTICS"


def _blend_trial_diagnostics_enabled() -> bool:
    """Internal-only gate for the Phase 2B blend-trial diagnostic view.

    Off by default (production/public behavior is completely unaffected).
    Deliberately an environment variable, not a query parameter or request
    header -- it cannot be toggled by an external HTTP request, only by
    whoever controls the process environment. See smartsim_blend_trial_plan.md
    Stage 1 and smartsim_blend_trial_report.md.
    """
    return os.environ.get(_BLEND_TRIAL_DIAGNOSTICS_ENV_VAR, "").strip().lower() in {"1", "true", "yes"}


# --- Phase 3: Public Blend Trial rollout controls -------------------------
# Separate and independent from the Phase 2B internal-diagnostics flag above
# -- that flag is untouched and still governs the engineer-only view. These
# control whether a *public* (but deliberately narrow) audience can see the
# same three-way comparison, styled as a real feature rather than a
# diagnostic. Two independent mechanisms, either of which grants visibility,
# both gated behind one master switch -- see smartsim_public_trial_report.md.
_PUBLIC_TRIAL_MASTER_ENV_VAR = "SMARTSIM_PUBLIC_TRIAL_ENABLED"
_PUBLIC_TRIAL_TOKEN_ALLOWLIST_ENV_VAR = "SMARTSIM_PUBLIC_TRIAL_TOKENS"
_PUBLIC_TRIAL_IP_ALLOWLIST_ENV_VAR = "SMARTSIM_PUBLIC_TRIAL_IP_ALLOWLIST"
_PUBLIC_TRIAL_TOKEN_PARAM = "smartsim_trial"


def _public_trial_master_enabled() -> bool:
    """The kill switch: if this is off, no request-level check is even attempted."""
    return os.environ.get(_PUBLIC_TRIAL_MASTER_ENV_VAR, "").strip().lower() in {"1", "true", "yes"}


def _env_list(env_var: str) -> frozenset[str]:
    raw = os.environ.get(env_var, "")
    return frozenset(item.strip() for item in raw.split(",") if item.strip())


def _public_trial_visible_for_request() -> bool:
    """Per-request gate for the public blend trial.

    Requires the master switch to be on, AND (a request context to exist --
    this is always False for CLI/batch callers such as the projection
    generation script or tests run outside an app context -- AND (the
    request's trial token matches the configured allowlist, OR the client's
    IP matches the configured IP allowlist)). Either allowlist mechanism is
    independently sufficient once the master switch is on; both default to
    empty (nobody whitelisted) so enabling the master switch alone still
    shows nothing until an allowlist is actually configured.
    """
    if not _public_trial_master_enabled():
        return False
    try:
        from flask import request as flask_request
        from flask import has_request_context
    except Exception:  # noqa: BLE001 - flask always installed in this app, but stay defensive
        return False
    if not has_request_context():
        return False

    token_allowlist = _env_list(_PUBLIC_TRIAL_TOKEN_ALLOWLIST_ENV_VAR)
    if token_allowlist:
        token = str(flask_request.args.get(_PUBLIC_TRIAL_TOKEN_PARAM) or flask_request.cookies.get(_PUBLIC_TRIAL_TOKEN_PARAM) or "").strip()
        if token and token in token_allowlist:
            return True

    ip_allowlist = _env_list(_PUBLIC_TRIAL_IP_ALLOWLIST_ENV_VAR)
    if ip_allowlist and str(flask_request.remote_addr or "").strip() in ip_allowlist:
        return True

    return False


def _week_is_within_pregame_window(season: int, week: int) -> bool:
    """Is this week close enough to kickoff that a simulation means anything?

    A sim is a PREGAME artifact: you sim in the pregame window and re-sim on
    injury and lineup news before kickoff. A projection for a game three months
    out is not an early answer, it is a stale one -- the ratings that produced
    it will have been superseded many times before the game is played, and this
    is measured rather than assumed: the model-vs-market margin gap runs +1.815
    at weeks 1-3 and +4.111 by weeks 7-9, driven by exactly that staleness
    (`docs/ai_context/ncaaf_beat_the_close_strategy.md` section 2).

    `ncaaf_target_week` is the lowest week still holding an unplayed game --
    i.e. the week currently being prepared. Weeks at or before it are servable:
    the target week is the pregame window, and earlier weeks are completed
    games whose projections remain valid as a record. Anything AFTER it is a
    game nobody has simmed for real yet.

    Fails OPEN (returns True) when the target week cannot be determined, because
    a schedule that will not load must not silently blank the whole board -- a
    missing input should degrade to the previous behaviour, not to nothing.
    """
    target = ncaaf_target_week(season)
    if target is None:
        return True
    try:
        return int(week) <= int(target)
    except (TypeError, ValueError):
        return True


@lru_cache(maxsize=16)
def _smartsim2_projection_index(season: int, week: int) -> dict[tuple[str, str], SmartSimNcaafProjection]:
    """Shadow-mode lookup for SmartSim 2.0 projections, keyed by (home, away).

    Returns an empty dict (never raises) when the artifact for this season/week
    has not been generated yet -- SmartSim 2.0 availability must never affect
    the legacy engine's own output. See smartsim_shadow_mode_report.md.

    Also returns empty for a week BEYOND the pregame window, whatever is on
    disk. That guard is load-bearing rather than tidy: `bootstrap_data_root`
    copies committed artifacts onto the web service's mounted disk and NEVER
    prunes, so deleting a stale future-week artifact from git does not remove it
    from the disk web actually reads. Without this the board would keep serving
    months-old projections for unplayed games that no longer exist in the repo.
    """
    if not _week_is_within_pregame_window(season, week):
        return {}
    data_root = default_ncaaf_source_root() / "data"
    try:
        projections = read_projection_artifact(season=season, week=week, data_root=data_root)
    except Exception:
        return {}
    return {(_normalize_text(p.home_team), _normalize_text(p.away_team)): p for p in projections}


def _attach_smartsim2_shadow_fields(
    scoreboard: dict[str, Any],
    *,
    row: dict[str, Any],
    week: int,
    engine_home_points: float | None,
    engine_away_points: float | None,
    engine_total_points: float | None,
    engine_margin: float | None,
) -> None:
    """Additive-only: adds smartsim2_*/blend_* keys, never touches existing ones.

    Phase 1 (shadow mode): these fields are captured for monitoring only and
    are not read by any template today (verified against syndicate/templates
    before this integration landed) -- adding them cannot change published
    output. See smartsim_production_integration_plan.md task 5.
    """
    scoreboard["smartsim2_available"] = False
    season = default_season()
    index = _smartsim2_projection_index(season, week)
    home_name = _normalize_text(row.get("home_team"))
    away_name = _normalize_text(row.get("away_team"))
    projection = index.get((home_name, away_name))
    if projection is None:
        return

    scoreboard["smartsim2_available"] = True
    scoreboard["smartsim2_source_label"] = SMARTSIM2_SOURCE_LABEL
    scoreboard["smartsim2_home_points"] = projection.home_score_mean
    scoreboard["smartsim2_away_points"] = projection.away_score_mean
    scoreboard["smartsim2_total_points"] = projection.total_mean
    scoreboard["smartsim2_margin"] = projection.margin_mean
    scoreboard["smartsim2_margin_stdev"] = projection.margin_stdev
    scoreboard["smartsim2_total_stdev"] = projection.total_stdev
    scoreboard["smartsim2_home_win_rate"] = projection.home_win_rate
    scoreboard["smartsim2_profile_name"] = projection.profile_name
    scoreboard["smartsim2_rating_source"] = projection.rating_source

    if engine_home_points is None or engine_away_points is None or engine_total_points is None:
        return
    if engine_margin is None:
        engine_margin = engine_home_points - engine_away_points
    result = compute_blend(
        engine_margin=engine_margin,
        smartsim_margin=projection.margin_mean,
        engine_total=engine_total_points,
        smartsim_total=projection.total_mean,
    )
    scoreboard["blend_margin"] = result.margin
    scoreboard["blend_total"] = result.total
    scoreboard["blend_margin_applied"] = result.smartsim_margin_used
    scoreboard["blend_total_applied"] = result.total_blended

    if _public_trial_visible_for_request():
        visibility_mode = "public_trial"
    elif _blend_trial_diagnostics_enabled():
        visibility_mode = "internal_diagnostic"
    else:
        visibility_mode = None

    if visibility_mode is not None:
        smartsim2_label = SMARTSIM2_PUBLIC_LABEL if visibility_mode == "public_trial" else SMARTSIM2_SOURCE_LABEL
        scoreboard["projection_sources_mode"] = visibility_mode
        scoreboard["projection_sources"] = {
            "enhanced_totals_engine": {
                "label": LEGACY_ENGINE_SOURCE_LABEL,
                "home_points": engine_home_points,
                "away_points": engine_away_points,
                "margin": engine_margin,
                "total": engine_total_points,
            },
            "smartsim2": {
                "label": smartsim2_label,
                "home_points": projection.home_score_mean,
                "away_points": projection.away_score_mean,
                "margin": projection.margin_mean,
                "total": projection.total_mean,
                "available": True,
            },
            "consensus_projection": {
                "label": CONSENSUS_SOURCE_LABEL,
                "margin": result.margin,
                "total": result.total,
                "margin_blended": result.smartsim_margin_used,
                "total_blended": result.total_blended,
            },
        }


def _scoreboard_projection(row: dict[str, Any], week: int) -> dict[str, Any]:
    lookup = _prediction_index().get((str(week), _normalize_text(row.get("away_team")), _normalize_text(row.get("home_team"))))
    if not lookup:
        return {}
    home_points = _safe_float(lookup.get("predicted_home_points"))
    away_points = _safe_float(lookup.get("predicted_away_points"))
    total_points = _safe_float(lookup.get("predicted_total_points"))
    margin = _safe_float(lookup.get("predicted_win_margin"))
    if margin is None and home_points is not None and away_points is not None:
        margin = home_points - away_points
    win_probability = _safe_float(lookup.get("model_home_win_prob"))
    home_name = str(row.get("home_team") or "Home").strip() or "Home"
    away_name = str(row.get("away_team") or "Away").strip() or "Away"
    if margin is None:
        spread_label = "-"
    elif margin >= 0:
        spread_label = f"{home_name} by {abs(margin):.1f}"
    else:
        spread_label = f"{away_name} by {abs(margin):.1f}"
    kickoff = str(lookup.get("start_date_api") or lookup.get("start_date") or "").strip()
    venue = str(lookup.get("venue") or "").strip()
    return {
        "home_points": _format_decimal(home_points, places=1),
        "away_points": _format_decimal(away_points, places=1),
        "total_points": _format_decimal(total_points, places=1),
        "spread_label": spread_label,
        "win_probability": format_pct(win_probability),
        "source_label": "Predicted totals artifact",
        "kickoff": kickoff,
        "kickoff_label": _format_kickoff_label(kickoff),
        "venue": venue,
    }


def _runtime_scoreboard_projection(row: dict[str, Any], week: int) -> dict[str, Any]:
    home_points = _safe_float(row.get("predicted_home_points"))
    away_points = _safe_float(row.get("predicted_away_points"))
    total_points = _safe_float(row.get("predicted_total_points"))
    margin = _safe_float(row.get("predicted_win_margin"))
    if margin is None and home_points is not None and away_points is not None:
        margin = home_points - away_points
    win_probability = _normalize_probability(row.get("model_home_win_prob"))
    home_name = str(row.get("home_team") or "Home").strip() or "Home"
    away_name = str(row.get("away_team") or "Away").strip() or "Away"
    if margin is None:
        spread_label = "-"
    elif margin >= 0:
        spread_label = f"{home_name} by {abs(margin):.1f}"
    else:
        spread_label = f"{away_name} by {abs(margin):.1f}"
    kickoff = str(row.get("start_date_api") or row.get("start_date") or "").strip()
    venue = str(row.get("venue") or "").strip()
    scoreboard = {
        "home_points": _format_decimal(home_points, places=1),
        "away_points": _format_decimal(away_points, places=1),
        "total_points": _format_decimal(total_points, places=1),
        "spread_label": spread_label,
        "win_probability": format_pct(win_probability),
        # Raw 0-1 float, additive alongside the formatted string above --
        # the market board needs a real number to join against, not display text.
        "home_win_probability": win_probability,
        "source_label": LEGACY_ENGINE_SOURCE_LABEL,
        "kickoff": kickoff,
        "kickoff_label": _format_kickoff_label(kickoff),
        "venue": venue,
    }
    _attach_smartsim2_shadow_fields(
        scoreboard,
        row=row,
        week=week,
        engine_home_points=home_points,
        engine_away_points=away_points,
        engine_total_points=total_points,
        engine_margin=margin,
    )
    return scoreboard


def _runtime_publication_profile(scoreboard: dict[str, Any]) -> dict[str, Any]:
    home_points = _safe_float(str(scoreboard.get("home_points") or "").strip())
    away_points = _safe_float(str(scoreboard.get("away_points") or "").strip())
    total_points = _safe_float(str(scoreboard.get("total_points") or "").strip())
    win_probability = _normalize_probability(scoreboard.get("win_probability"))
    margin = None
    if home_points is not None and away_points is not None:
        margin = abs(home_points - away_points)
    edge_strength = abs((win_probability or 0.5) - 0.5)
    spread_strength = min((margin or 0.0) / 28.0, 1.0)
    total_strength = min((total_points or 0.0) / 100.0, 1.0)
    coverage_score = round(min(1.0, max(0.0, (edge_strength * 0.55) + (spread_strength * 0.30) + (total_strength * 0.15))), 3)
    if coverage_score >= 0.75:
        coverage_tier = "A"
    elif coverage_score >= 0.60:
        coverage_tier = "B"
    elif coverage_score >= 0.45:
        coverage_tier = "C"
    else:
        coverage_tier = "D"
    publication_ready = coverage_tier in {"A", "B"}
    publication_status = "publishable" if publication_ready else "suppressed"
    if publication_ready:
        coverage_warnings = ["runtime candidate passes publication threshold"]
    else:
        coverage_warnings = ["runtime candidate below publication threshold"]
    return {
        "coverage_score": coverage_score,
        "coverage_tier": coverage_tier,
        "coverage_warnings": coverage_warnings,
        "publication_status": publication_status,
        "publication_priority": {"A": 3, "B": 2, "C": 1, "D": 0}.get(coverage_tier, 0),
        "publication_ready": publication_ready,
        "ready_label": "Publication ready" if publication_ready else "Publication blocked",
        "tier_badges": _tier_badges(coverage_tier),
    }


def _runtime_prediction_rows(week: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in _prediction_rows():
        try:
            row_week = int(str(row.get("week") or "").strip())
        except Exception:
            continue
        if row_week != int(week):
            continue
        home_team = str(row.get("home_team") or "").strip()
        away_team = str(row.get("away_team") or "").strip()
        if not home_team or not away_team:
            continue
        if any(
            _safe_float(row.get(field)) is None
            for field in ("predicted_home_points", "predicted_away_points", "predicted_total_points")
        ):
            continue
        rows.append(dict(row))
    best_rows: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        key = (_normalize_text(row.get("away_team")), _normalize_text(row.get("home_team")))
        if not all(key):
            continue
        best_rows.setdefault(key, row)
    ordered_rows = sorted(
        best_rows.values(),
        key=lambda row: (
            abs((_safe_float(row.get("predicted_home_points")) or 0.0) - (_safe_float(row.get("predicted_away_points")) or 0.0)),
            _safe_float(row.get("predicted_total_points")) or 0.0,
        ),
        reverse=True,
    )
    return ordered_rows


def _processed_artifact_path(*parts: str) -> Path:
    return Path(__file__).resolve().parents[3] / "data" / "ncaaf_source" / "source_artifacts" / "data" / "processed" / Path(*parts)


def _load_csv_rows(path: Path) -> list[dict[str, Any]]:
    try:
        if not path.exists():
            return []
        with path.open("r", encoding="utf-8", newline="") as handle:
            return [dict(row) for row in csv.DictReader(handle)]
    except Exception:
        return []


def _normalize_text(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = text.replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


@lru_cache(maxsize=1)
def _team_registry_rows() -> tuple[dict[str, Any], ...]:
    return tuple(_load_csv_rows(_processed_artifact_path("team_registry", "ncaaf_team_registry.csv")))


@lru_cache(maxsize=1)
def _returning_rows() -> tuple[dict[str, Any], ...]:
    return tuple(_load_csv_rows(_processed_artifact_path("returning_production", "ncaaf_returning_production_snapshot.csv")))


@lru_cache(maxsize=1)
def _coach_rows() -> tuple[dict[str, Any], ...]:
    return tuple(_load_csv_rows(_processed_artifact_path("coach_continuity", "ncaaf_coach_continuity_snapshot.csv")))


@lru_cache(maxsize=1)
def _transfer_rows() -> tuple[dict[str, Any], ...]:
    return tuple(_load_csv_rows(_processed_artifact_path("transfers", "ncaaf_transfer_portal_snapshot.csv")))


@lru_cache(maxsize=1)
def _roster_rows() -> tuple[dict[str, Any], ...]:
    return tuple(_load_csv_rows(_processed_artifact_path("roster", "ncaaf_roster_snapshot.csv")))


@lru_cache(maxsize=1)
def _team_branding_index() -> dict[str, Any]:
    rows = read_team_branding_snapshot(_processed_artifact_path("team_branding", "ncaaf_team_branding.csv"))
    return team_branding_index_by_id(rows)


def _resolve_branding(team_id: str) -> Any | None:
    return _team_branding_index().get(str(team_id).strip()) if team_id else None


def _team_registry_index() -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for row in _team_registry_rows():
        if not isinstance(row, dict):
            continue
        for candidate in (
            row.get("team_id"),
            row.get("canonical_team_name"),
            row.get("abbreviation"),
            row.get("display_name"),
            row.get("school_name"),
            row.get("mascot_name"),
        ):
            normalized = _normalize_text(candidate)
            if normalized:
                index.setdefault(normalized, row)
        for alias in str(row.get("aliases") or "").split("|"):
            normalized = _normalize_text(alias)
            if normalized:
                index.setdefault(normalized, row)
    return index


def _resolve_team(team_name: str) -> dict[str, Any] | None:
    return _team_registry_index().get(_normalize_text(team_name))


def _first_row(rows: tuple[dict[str, Any], ...], *, team_id: str | None = None, season: int | None = None, key: str = "team_id") -> dict[str, Any] | None:
    for row in rows:
        if not isinstance(row, dict):
            continue
        if team_id is not None and str(row.get(key) or "").strip() != str(team_id).strip():
            continue
        if season is not None:
            row_season = str(row.get("season") or "").strip()
            if row_season and row_season != str(season):
                continue
        return row
    return None


def _count_rows(rows: tuple[dict[str, Any], ...], *, key: str, team_id: str, season: int | None = None) -> int:
    total = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get(key) or "").strip() != str(team_id).strip():
            continue
        if season is not None:
            row_season = str(row.get("season") or "").strip()
            if row_season and row_season != str(season):
                continue
        total += 1
    return total


def _count_transfer_rows(rows: tuple[dict[str, Any], ...], *, team_id: str, season: int | None = None, direction: str) -> int:
    key = "destination_team_id" if direction == "in" else "origin_team_id"
    return _count_rows(rows, key=key, team_id=team_id, season=season)


def _format_decimal(value: Any, *, places: int = 3) -> str:
    amount = _safe_float(value)
    if amount is None:
        # The shared board placeholder, so one card does not mix "-" for its
        # numbers with the contract's em dash for everything else. The two
        # template gates that used to test `!= '-'` now test both forms, so
        # neither this nor the contract can silently un-gate a panel by
        # changing its own placeholder.
        return NULL_PLACEHOLDER
    return f"{amount:.{places}f}".rstrip("0").rstrip(".")


def _format_kickoff_label(value: Any) -> str:
    """Human kickoff string for the card, in the platform's display timezone.

    Measured 2026-08-14 on production: NCAAF cards rendered
    `KICKOFF 2026-08-29T16:00:00.000Z` -- the raw `start_date_api` value
    straight from the schedule row, reaching the UI unformatted.

    This is deliberately a SEPARATE key from `kickoff` rather than a
    reformat in place. `kickoff` is parsed as data downstream --
    `ncaaf/betting_card.py:_kickoff_date_and_label` calls
    `datetime.fromisoformat` on exactly this field to build its per-day
    grouping -- so formatting it at the producer would have traded a
    cosmetic defect for a broken betting card.

    Central, because that is what every other display surface in this repo
    uses (`features/shared/timezone.py`, `SYNDICATE_BOARD_TZ`). Times are
    assembled with portable strftime directives only: `%-I`/`%-d` are
    POSIX-only and raise on Windows, where this also runs.
    """
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        return text
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=CENTRAL_TIMEZONE)
    local = parsed.astimezone(CENTRAL_TIMEZONE)
    hour = local.hour % 12 or 12
    meridiem = "AM" if local.hour < 12 else "PM"
    zone = local.strftime("%Z") or "CT"
    return (
        f"{local.strftime('%a')} {local.strftime('%b')} {local.day}, "
        f"{hour}:{local.strftime('%M')} {meridiem} {zone}"
    )


def _publication_ready(coverage_tier: str | None) -> bool:
    return str(coverage_tier or "").upper() in {"A", "B"}


def _tier_badges(coverage_tier: str | None) -> list[dict[str, Any]]:
    current = str(coverage_tier or "").upper()
    return [{"label": tier, "active": tier == current} for tier in ("A", "B", "C", "D")]


def _team_context(team_name: str, season: int) -> dict[str, Any]:
    registry_row = _resolve_team(team_name) or {}
    team_id = str(registry_row.get("team_id") or "").strip()
    team_rank = str(
        registry_row.get("rank")
        or registry_row.get("ap_rank")
        or registry_row.get("cfp_rank")
        or registry_row.get("ranking")
        or ""
    ).strip()
    returning_row = _first_row(_returning_rows(), team_id=team_id, season=season)
    coach_row = _first_row(_coach_rows(), team_id=team_id, season=season)
    roster_count = _count_rows(_roster_rows(), key="team_id", team_id=team_id, season=season)
    transfer_in = _count_transfer_rows(_transfer_rows(), team_id=team_id, season=season, direction="in")
    transfer_out = _count_transfer_rows(_transfer_rows(), team_id=team_id, season=season, direction="out")
    transfer_net = transfer_in - transfer_out
    returning_starter_estimate = _format_decimal(returning_row.get("returning_starter_estimate") if returning_row else None, places=1)
    returning_percent = _format_decimal(returning_row.get("percent_ppa") if returning_row else None, places=3)
    returning_usage = _format_decimal(returning_row.get("usage") if returning_row else None, places=3)
    coach_continuity = _format_decimal(coach_row.get("continuity_score") if coach_row else None, places=3)
    coach_tenure = _format_decimal(coach_row.get("coach_tenure_years") if coach_row else None, places=1)
    branding = _resolve_branding(team_id)
    return {
        "team_name": team_name,
        "team_id": team_id,
        "abbreviation": str(registry_row.get("abbreviation") or _abbr(team_name)).strip(),
        "rank": team_rank,
        "school_name": str(registry_row.get("school_name") or team_name).strip() or team_name,
        "mascot_name": str(registry_row.get("mascot_name") or "").strip(),
        "conference": str(registry_row.get("conference") or "").strip(),
        "conference_short_name": str(registry_row.get("conference_short_name") or "").strip(),
        "subdivision": str(registry_row.get("subdivision") or "").strip(),
        "logo_url": branding.logo_url if branding else None,
        "primary_color": branding.primary_color if branding else None,
        "secondary_color": branding.secondary_color if branding else None,
        "returning": {
            "starter_estimate": returning_starter_estimate,
            "percent_ppa": returning_percent,
            "usage": returning_usage,
            "summary": f"{returning_starter_estimate} starters | PPA {returning_percent} | Usage {returning_usage}",
        },
        "coach": {
            "name": str(coach_row.get("head_coach_name") or "").strip() if coach_row else "",
            "continuity_score": coach_continuity,
            "tenure_years": coach_tenure,
            "changed": str(coach_row.get("coach_changed") or "").strip() if coach_row else "",
            "summary": f"{str(coach_row.get('head_coach_name') or 'TBD').strip()} | continuity {coach_continuity} | tenure {coach_tenure}y" if coach_row else "Coach continuity unavailable",
        },
        "transfer": {
            "incoming": transfer_in,
            "outgoing": transfer_out,
            "net": transfer_net,
            "summary": f"{transfer_in} in / {transfer_out} out / net {transfer_net:+d}".replace("+", "") if transfer_in or transfer_out else "No transfer data",
        },
        "roster": {
            "active_count": roster_count,
            "summary": f"{roster_count} active roster entries",
        },
    }


def _team_context_tone(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"high", "positive", "stable", "veteran", "returning hc"}:
        return "positive"
    if normalized in {"neutral", "mixed"}:
        return "neutral"
    if normalized in {"low", "negative", "unstable", "freshman", "rebuilding"}:
        return "negative"
    return "neutral"


def _team_context_label(value: str, *, default: str) -> str:
    text = str(value or "").strip()
    return text or default


def _build_team_context_items(home_context: dict[str, Any], away_context: dict[str, Any]) -> list[dict[str, str]]:
    home_returning = home_context.get("returning") if isinstance(home_context.get("returning"), dict) else {}
    away_returning = away_context.get("returning") if isinstance(away_context.get("returning"), dict) else {}
    home_transfer = home_context.get("transfer") if isinstance(home_context.get("transfer"), dict) else {}
    away_transfer = away_context.get("transfer") if isinstance(away_context.get("transfer"), dict) else {}
    home_coach = home_context.get("coach") if isinstance(home_context.get("coach"), dict) else {}
    away_coach = away_context.get("coach") if isinstance(away_context.get("coach"), dict) else {}
    home_roster = home_context.get("roster") if isinstance(home_context.get("roster"), dict) else {}
    away_roster = away_context.get("roster") if isinstance(away_context.get("roster"), dict) else {}

    returning_home = _safe_float(home_returning.get("percent_ppa"))
    returning_away = _safe_float(away_returning.get("percent_ppa"))
    if returning_home is not None and returning_away is not None:
        returning_value = "High" if max(returning_home, returning_away) >= 0.70 else "Moderate" if max(returning_home, returning_away) >= 0.55 else "Developing"
    else:
        returning_value = "Available"

    transfer_net = int(_safe_float(home_transfer.get("net")) or 0) + int(_safe_float(away_transfer.get("net")) or 0)
    portal_value = "Positive" if transfer_net > 0 else "Negative" if transfer_net < 0 else "Neutral"
    coach_value = "Returning HC" if str(home_coach.get("name") or away_coach.get("name") or "").strip() else "Stable"
    roster_total = int(_safe_float(home_roster.get("active_count")) or 0) + int(_safe_float(away_roster.get("active_count")) or 0)
    roster_value = "Veteran" if roster_total >= 180 else "Balanced" if roster_total >= 120 else "Young"

    return [
        {
            "label": "Returning Production",
            "value": returning_value,
            "detail": f"Home {home_returning.get('summary') or '-'} | Away {away_returning.get('summary') or '-'}",
            "tone": _team_context_tone(returning_value),
        },
        {
            "label": "Portal Impact",
            "value": portal_value,
            "detail": f"Home {home_transfer.get('summary') or '-'} | Away {away_transfer.get('summary') or '-'}",
            "tone": _team_context_tone(portal_value),
        },
        {
            "label": "Coach Continuity",
            "value": coach_value,
            "detail": f"Home {home_coach.get('summary') or '-'} | Away {away_coach.get('summary') or '-'}",
            "tone": _team_context_tone(coach_value),
        },
        {
            "label": "Roster Experience",
            "value": roster_value,
            "detail": f"Home {home_roster.get('summary') or '-'} | Away {away_roster.get('summary') or '-'}",
            "tone": _team_context_tone(roster_value),
        },
    ]


def _build_matchup_context_items(home_context: dict[str, Any], away_context: dict[str, Any]) -> list[dict[str, str]]:
    def _team_label(context: dict[str, Any]) -> str:
        return str(context.get("school_name") or context.get("abbreviation") or context.get("team_name") or "Team").strip() or "Team"

    def _advantage_label(home_value: float | None, away_value: float | None, *, home_text: str, away_text: str, higher_is_better: bool, percent: bool = False, neutral_delta: float = 0.03) -> tuple[str, str, str]:
        if home_value is None or away_value is None:
            return "Unavailable", "Unable to compare", "neutral"
        delta = float(home_value) - float(away_value)
        if not higher_is_better:
            delta = -delta
        if abs(delta) <= float(neutral_delta):
            return "Even", f"{home_text} | {away_text}", "neutral"
        leader = home_text if delta > 0 else away_text
        magnitude = abs(delta)
        if percent:
            return f"{leader} +{magnitude * 100.0:.0f}%", f"{home_text} {float(home_value) * 100.0:.1f}% | {away_text} {float(away_value) * 100.0:.1f}%", "positive" if delta > 0 else "negative"
        return f"{leader} Advantage", f"{home_text} {float(home_value):.3f} | {away_text} {float(away_value):.3f}", "positive" if delta > 0 else "negative"

    home_returning = home_context.get("returning") if isinstance(home_context.get("returning"), dict) else {}
    away_returning = away_context.get("returning") if isinstance(away_context.get("returning"), dict) else {}
    home_transfer = home_context.get("transfer") if isinstance(home_context.get("transfer"), dict) else {}
    away_transfer = away_context.get("transfer") if isinstance(away_context.get("transfer"), dict) else {}
    home_coach = home_context.get("coach") if isinstance(home_context.get("coach"), dict) else {}
    away_coach = away_context.get("coach") if isinstance(away_context.get("coach"), dict) else {}
    home_roster = home_context.get("roster") if isinstance(home_context.get("roster"), dict) else {}
    away_roster = away_context.get("roster") if isinstance(away_context.get("roster"), dict) else {}

    home_conf = _team_context_label(str(home_context.get("conference_short_name") or home_context.get("conference") or ""), default="Home")
    away_conf = _team_context_label(str(away_context.get("conference_short_name") or away_context.get("conference") or ""), default="Away")
    home_name = _team_label(home_context)
    away_name = _team_label(away_context)

    home_returning_pct = _safe_float(home_returning.get("percent_ppa"))
    away_returning_pct = _safe_float(away_returning.get("percent_ppa"))
    home_transfer_net = _safe_float(home_transfer.get("net"))
    away_transfer_net = _safe_float(away_transfer.get("net"))
    home_coach_continuity = _safe_float(home_coach.get("continuity_score"))
    away_coach_continuity = _safe_float(away_coach.get("continuity_score"))
    home_roster_count = _safe_float(home_roster.get("active_count"))
    away_roster_count = _safe_float(away_roster.get("active_count"))
    home_experience = (
        (home_returning_pct or 0.0) * 0.6
        + (home_coach_continuity or 0.0) * 0.25
        + min((home_roster_count or 0.0) / 200.0, 1.0) * 0.15
    )
    away_experience = (
        (away_returning_pct or 0.0) * 0.6
        + (away_coach_continuity or 0.0) * 0.25
        + min((away_roster_count or 0.0) / 200.0, 1.0) * 0.15
    )

    conference_value = f"{away_conf} vs {home_conf}" if away_conf != home_conf else f"Same conference: {home_conf}"
    conference_detail = f"Away {away_conf} | Home {home_conf}"
    if away_conf == home_conf:
        conference_detail = f"Both teams are in {home_conf}"

    returning_value, returning_detail, returning_tone = _advantage_label(home_returning_pct, away_returning_pct, home_text=home_name, away_text=away_name, higher_is_better=True, percent=True, neutral_delta=0.03)
    portal_value, portal_detail, portal_tone = _advantage_label(home_transfer_net, away_transfer_net, home_text=home_name, away_text=away_name, higher_is_better=True, percent=False, neutral_delta=0.5)
    coach_value, coach_detail, coach_tone = _advantage_label(home_coach_continuity, away_coach_continuity, home_text=home_name, away_text=away_name, higher_is_better=True, percent=False, neutral_delta=0.03)
    roster_value, roster_detail, roster_tone = _advantage_label(home_roster_count, away_roster_count, home_text=home_name, away_text=away_name, higher_is_better=True, percent=False, neutral_delta=2.0)
    experience_value, experience_detail, experience_tone = _advantage_label(home_experience, away_experience, home_text=home_name, away_text=away_name, higher_is_better=True, percent=False, neutral_delta=0.03)

    return [
        {
            "label": "Conference Context",
            "value": conference_value,
            "detail": conference_detail,
            "tone": "neutral",
        },
        {
            "label": "Returning Production",
            "value": returning_value,
            "detail": returning_detail,
            "tone": returning_tone,
        },
        {
            "label": "Portal Impact",
            "value": portal_value,
            "detail": portal_detail,
            "tone": portal_tone,
        },
        {
            "label": "Coach Continuity",
            "value": coach_value,
            "detail": coach_detail,
            "tone": coach_tone,
        },
        {
            "label": "Roster Comparison",
            "value": roster_value if roster_value != "Even" else experience_value,
            "detail": f"Roster size {home_roster_count or 0:.0f} vs {away_roster_count or 0:.0f} | Experience {experience_detail}",
            "tone": roster_tone if roster_tone != "neutral" else experience_tone,
        },
    ]


def _build_smartsim_reasons_items(home_context: dict[str, Any], away_context: dict[str, Any], scoreboard: dict[str, Any]) -> dict[str, Any]:
    def _team_label(context: dict[str, Any]) -> str:
        return str(context.get("school_name") or context.get("abbreviation") or context.get("team_name") or "Team").strip() or "Team"

    def _subdivision_rank(value: str) -> int:
        normalized = str(value or "").strip().upper()
        if not normalized:
            return -1
        if "FBS" in normalized:
            return 4
        if "FCS" in normalized:
            return 3
        if "DIVISION I" in normalized or normalized in {"D1", "DI"}:
            return 4
        if "DIVISION II" in normalized or normalized in {"D2", "DII"}:
            return 2
        if "DIVISION III" in normalized or normalized in {"D3", "DIII"}:
            return 1
        if "NAIA" in normalized:
            return 0
        return 0

    def _positive_reason(favored_label: str, detail: str, *, weight: int, tone: str = "positive") -> dict[str, Any] | None:
        if not detail:
            return None
        return {
            "label": favored_label,
            "value": favored_label,
            "detail": detail,
            "tone": tone,
            "weight": weight,
        }

    home_returning = home_context.get("returning") if isinstance(home_context.get("returning"), dict) else {}
    away_returning = away_context.get("returning") if isinstance(away_context.get("returning"), dict) else {}
    home_transfer = home_context.get("transfer") if isinstance(home_context.get("transfer"), dict) else {}
    away_transfer = away_context.get("transfer") if isinstance(away_context.get("transfer"), dict) else {}
    home_coach = home_context.get("coach") if isinstance(home_context.get("coach"), dict) else {}
    away_coach = away_context.get("coach") if isinstance(away_context.get("coach"), dict) else {}
    home_roster = home_context.get("roster") if isinstance(home_context.get("roster"), dict) else {}
    away_roster = away_context.get("roster") if isinstance(away_context.get("roster"), dict) else {}

    home_returning_pct = _safe_float(home_returning.get("percent_ppa"))
    away_returning_pct = _safe_float(away_returning.get("percent_ppa"))
    home_transfer_net = _safe_float(home_transfer.get("net"))
    away_transfer_net = _safe_float(away_transfer.get("net"))
    home_coach_continuity = _safe_float(home_coach.get("continuity_score"))
    away_coach_continuity = _safe_float(away_coach.get("continuity_score"))
    home_roster_count = _safe_float(home_roster.get("active_count"))
    away_roster_count = _safe_float(away_roster.get("active_count"))
    home_experience = (
        (home_returning_pct or 0.0) * 0.6
        + (home_coach_continuity or 0.0) * 0.25
        + min((home_roster_count or 0.0) / 200.0, 1.0) * 0.15
    )
    away_experience = (
        (away_returning_pct or 0.0) * 0.6
        + (away_coach_continuity or 0.0) * 0.25
        + min((away_roster_count or 0.0) / 200.0, 1.0) * 0.15
    )

    home_points = _safe_float(scoreboard.get("home_points"))
    away_points = _safe_float(scoreboard.get("away_points"))
    favored_is_home = home_points is None or away_points is None or home_points >= away_points
    favored_context = home_context if favored_is_home else away_context
    underdog_context = away_context if favored_is_home else home_context
    favored_name = _team_label(favored_context)
    underdog_name = _team_label(underdog_context)

    items: list[dict[str, Any]] = []

    if home_returning_pct is not None and away_returning_pct is not None:
        if favored_is_home and home_returning_pct > away_returning_pct + 0.03:
            items.append({
                "label": "Returning Production",
                "value": "Higher returning production",
                "detail": f"{favored_name} {home_returning_pct:.3f} | {underdog_name} {away_returning_pct:.3f}",
                "tone": "positive",
                "weight": 100,
            })
        elif not favored_is_home and away_returning_pct > home_returning_pct + 0.03:
            items.append({
                "label": "Returning Production",
                "value": "Higher returning production",
                "detail": f"{favored_name} {away_returning_pct:.3f} | {underdog_name} {home_returning_pct:.3f}",
                "tone": "positive",
                "weight": 100,
            })

    if home_experience is not None and away_experience is not None:
        if favored_is_home and home_experience > away_experience + 0.03:
            items.append({
                "label": "Roster Experience",
                "value": "Stronger roster experience",
                "detail": f"{favored_name} experience {home_experience:.3f} | {underdog_name} experience {away_experience:.3f}",
                "tone": "positive",
                "weight": 90,
            })
        elif not favored_is_home and away_experience > home_experience + 0.03:
            items.append({
                "label": "Roster Experience",
                "value": "Stronger roster experience",
                "detail": f"{favored_name} experience {away_experience:.3f} | {underdog_name} experience {home_experience:.3f}",
                "tone": "positive",
                "weight": 90,
            })

    if home_transfer_net is not None and away_transfer_net is not None:
        if favored_is_home and home_transfer_net > away_transfer_net + 0.5:
            items.append({
                "label": "Portal Activity",
                "value": "Positive portal balance",
                "detail": f"{favored_name} net {home_transfer_net:+.0f} | {underdog_name} net {away_transfer_net:+.0f}".replace("+", ""),
                "tone": "positive",
                "weight": 80,
            })
        elif not favored_is_home and away_transfer_net > home_transfer_net + 0.5:
            items.append({
                "label": "Portal Activity",
                "value": "Positive portal balance",
                "detail": f"{favored_name} net {away_transfer_net:+.0f} | {underdog_name} net {home_transfer_net:+.0f}".replace("+", ""),
                "tone": "positive",
                "weight": 80,
            })

    if home_coach_continuity is not None and away_coach_continuity is not None:
        if favored_is_home and home_coach_continuity > away_coach_continuity + 0.03:
            items.append({
                "label": "Coach Continuity",
                "value": "More stable coach continuity",
                "detail": f"{favored_name} {home_coach_continuity:.3f} | {underdog_name} {away_coach_continuity:.3f}",
                "tone": "positive",
                "weight": 70,
            })
        elif not favored_is_home and away_coach_continuity > home_coach_continuity + 0.03:
            items.append({
                "label": "Coach Continuity",
                "value": "More stable coach continuity",
                "detail": f"{favored_name} {away_coach_continuity:.3f} | {underdog_name} {home_coach_continuity:.3f}",
                "tone": "positive",
                "weight": 70,
            })

    favored_conference = str(favored_context.get("conference_short_name") or favored_context.get("conference") or "").strip()
    underdog_conference = str(underdog_context.get("conference_short_name") or underdog_context.get("conference") or "").strip()
    favored_subdivision = str(favored_context.get("subdivision") or "").strip()
    underdog_subdivision = str(underdog_context.get("subdivision") or "").strip()
    context_detail = f"{favored_name} {favored_conference or '-'} / {favored_subdivision or '-'} | {underdog_name} {underdog_conference or '-'} / {underdog_subdivision or '-'}"
    if favored_conference == underdog_conference and favored_subdivision == underdog_subdivision:
        context_value = "Comparable conference / subdivision context"
        context_tone = "neutral"
    elif favored_subdivision and underdog_subdivision and _subdivision_rank(favored_subdivision) > _subdivision_rank(underdog_subdivision):
        context_value = "Higher subdivision context"
        context_tone = "positive"
    else:
        context_value = "Comparable conference / subdivision context"
        context_tone = "neutral"
    items.append({
        "label": "Conference / Subdivision Context",
        "value": context_value,
        "detail": context_detail,
        "tone": context_tone,
        "weight": 60,
    })

    ordered_items = sorted(items, key=lambda item: (1 if str(item.get("tone") or "").strip().lower() == "positive" else 0, int(item.get("weight") or 0)), reverse=True)
    lead_phrases = [str(item.get("value") or "").strip() for item in ordered_items if str(item.get("tone") or "").strip().lower() == "positive"]
    if not lead_phrases:
        lead_phrases = [str(item.get("value") or "").strip() for item in ordered_items[:3] if str(item.get("value") or "").strip()]
    lead_text = " and ".join(lead_phrases[:2]) if len(lead_phrases) == 2 else ", ".join(lead_phrases[:2])
    if len(lead_phrases) > 2:
        lead_text = f"{', '.join(lead_phrases[:2])}, and {lead_phrases[2]}"
    if lead_text:
        summary = f"{LEGACY_ENGINE_SOURCE_LABEL} favors {favored_name} because of {lead_text.lower()}."
    else:
        summary = f"{LEGACY_ENGINE_SOURCE_LABEL} favors {favored_name} because the current matchup context leans that way."

    return {
        "lead": summary,
        "summary": summary,
        "favored_team": favored_name,
        "items": ordered_items[:5],
    }


def _build_ncaaf_card_contract(row: dict[str, Any], week: int, *, season: int) -> dict[str, Any]:
    home_team = str(row.get("home_team") or "Home").strip() or "Home"
    away_team = str(row.get("away_team") or "Away").strip() or "Away"
    publication_profile = _week1_publication_profile(away_team, home_team, week)
    coverage_score = publication_profile.get("coverage_score")
    coverage_tier = publication_profile.get("coverage_tier")
    publication_status = publication_profile.get("publication_status")
    publication_priority = publication_profile.get("publication_priority")
    publication_ready = _publication_ready(coverage_tier)
    home_context = _team_context(home_team, season)
    away_context = _team_context(away_team, season)
    scoreboard = _scoreboard_projection(row, week)
    scoreboard_header = {
        "away": {
            "abbr": away_context["abbreviation"],
                "rank": away_context["rank"],
            "school_name": away_context["school_name"],
            "mascot_name": away_context["mascot_name"],
            "conference": away_context["conference"],
            "conference_short_name": away_context["conference_short_name"],
            "logo_url": away_context["logo_url"],
            "logo_text": away_context["abbreviation"],
            "primary_color": away_context["primary_color"],
            "secondary_color": away_context["secondary_color"],
        },
        "home": {
            "abbr": home_context["abbreviation"],
                "rank": home_context["rank"],
            "school_name": home_context["school_name"],
            "mascot_name": home_context["mascot_name"],
            "conference": home_context["conference"],
            "conference_short_name": home_context["conference_short_name"],
            "logo_url": home_context["logo_url"],
            "logo_text": home_context["abbreviation"],
            "primary_color": home_context["primary_color"],
            "secondary_color": home_context["secondary_color"],
        },
        "kickoff": scoreboard.get("kickoff") or f"{_week_label(week, season=season)} kickoff unavailable",
        "kickoff_label": scoreboard.get("kickoff_label") or f"{_week_label(week, season=season)} kickoff unavailable",
        "venue": scoreboard.get("venue") or "Venue unavailable",
        "status": f"Week {week}",
        "status_detail": "Historical summary",
    }
    context_sections = [
        {
            "label": "Returning production",
            "home": home_context["returning"]["summary"],
            "away": away_context["returning"]["summary"],
            "detail": "Starter estimate, production share, and usage from the published snapshot.",
        },
        {
            "label": "Coach continuity",
            "home": home_context["coach"]["summary"],
            "away": away_context["coach"]["summary"],
            "detail": "Continuity score and tenure from the published coach snapshot.",
        },
        {
            "label": "Transfer activity",
            "home": home_context["transfer"]["summary"],
            "away": away_context["transfer"]["summary"],
            "detail": "Incoming, outgoing, and net transfer counts.",
        },
        {
            "label": "Roster base",
            "home": home_context["roster"]["summary"],
            "away": away_context["roster"]["summary"],
            "detail": "Active roster snapshot rows linked to each team.",
        },
    ]
    team_context = {
        "items": _build_team_context_items(home_context, away_context),
        "summary": "Return production, portal impact, coach continuity, and roster experience",
    }
    matchup_context = {
        "items": _build_matchup_context_items(home_context, away_context),
        "summary": "Conference, returning production, portal, coach, and roster comparisons",
    }
    smartsim_reasons = _build_smartsim_reasons_items(home_context, away_context, scoreboard)
    return {
        "version": _NCAAF_CARD_CONTRACT_VERSION,
        "summary": {
            "coverage_score": coverage_score,
            "coverage_tier": coverage_tier,
            "publication_status": publication_status,
            "publication_priority": publication_priority,
            "publication_ready": publication_ready,
            "ready_label": "Publication ready" if publication_ready else "Publication blocked",
            "tier_badges": _tier_badges(coverage_tier),
        },
        "teams": {
            "home": home_context,
            "away": away_context,
        },
        "scoreboard": scoreboard,
        # `row.get`, not a bare name: this builder has no `projection` in
        # scope. The bare name was a NameError on every call -- see the
        # commit message. Absent yields `{}` from the helper, which is the
        # contract its own docstring states: absent stays absent.
        # BET ROWS HAVE NO PROJECTION AND SHOULD NOT INVENT ONE -- a wager is
        # not a game projection, so `{}` is the correct outcome here.
        "predictions": _ncaaf_shared_predictions_block(row.get("projection")),
        "scoreboard_header": scoreboard_header,
        "smartsim_reasons": smartsim_reasons,
        "team_context": team_context,
        "matchup_context": matchup_context,
        "context_sections": context_sections,
    }


def _abbr(team: str) -> str:
    tokens = [token for token in str(team or "").replace("&", " ").split() if token]
    if not tokens:
        return "TBD"
    if len(tokens) == 1:
        return tokens[0][:3].upper()
    return "".join(token[0] for token in tokens[:3]).upper()


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        return float(value)
    except Exception:
        return None


def _normalize_probability(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    text = text.rstrip("%").strip()
    try:
        amount = float(text)
    except Exception:
        return None
    if amount > 1.0:
        amount /= 100.0
    if amount < 0.0:
        return 0.0
    if amount > 1.0:
        return 1.0
    return amount


def _stake_text(value: Any) -> str:
    amount = _safe_float(value)
    return f"${amount:.2f}" if amount is not None else "-"


def _kelly_text(value: Any) -> str:
    amount = _safe_float(value)
    return f"{amount * 100:.1f}%" if amount is not None else "-"


def _week_label(week: int, *, season: int | None = None) -> str:
    resolved_season = int(season) if season is not None else default_season()
    return f"{resolved_season} Week {week}"


def _week1_publication_profile(away_team: str, home_team: str, week: int) -> dict[str, Any]:
    if week != 1:
        return {}
    matchup = (away_team, home_team)
    if matchup in _WEEK1_PUBLISHABLE_MATCHUPS:
        return dict(_WEEK1_COVERAGE_PROFILE["publishable"])
    if matchup in _WEEK1_SUPPRESSED_MATCHUPS:
        return dict(_WEEK1_COVERAGE_PROFILE["suppressed"])
    return {}


# An NFL-shaped number applied to a sport that is not NFL-shaped.
#
# `_collapse_games` capped the NCAAF board at 16 games. The NFL plays exactly 16
# games a week (32 teams / 2), so on that board 16 is the natural slate and the
# cap never binds. FBS plays 50-60. Measured 2026-08-18 on production: weeks
# 1, 2, 3, 5, 8 and 12 ALL served exactly 16 games, while CFBD lists 51
# FBS-vs-FBS for week 1 alone. Six weeks landing on the cap exactly is the cap
# binding, not six coincidences.
#
# Worse, the truncation keeps the top rows by `edge` -- and with no SmartSim2
# projection artifact the edges are absent, so the surviving 16 were an
# ARBITRARY 16, presented as the board.
#
# NOT REMOVED, DEFENDED. An unbounded board is a memory and payload risk on a
# 2GB display service (~9.8 KB/game measured, so 60 games is ~590 KB). The cap
# stays as a real guard at a size the sport can actually reach, and -- per the
# "no silent caps" rule -- it now SAYS SO when it bites, in the payload itself
# rather than only in a log the web service may or may not surface.
_NCAAF_BOARD_GAME_LIMIT = 80

# Set on the context by `build_cards_page_context` so the truncation is readable
# with curl. This ALSO answers a question that could not be answered from
# outside: the `recommendations_summary` artifact is NOT in
# `HOT_ARTIFACT_PATTERNS`, so it cannot be read through `/api/ops/artifacts/*`
# and there is no local copy -- meaning "does the summary hold more than 16
# rows?" was unanswerable by inspection. `rows_before_limit` answers it from the
# served payload on the next request.
_NCAAF_BOARD_COUNTS_KEY = "board_row_counts"


def _note_board_truncation(counts: dict[str, Any], source: str, rows: list[Any], week: int) -> None:
    """Record (and announce) a board truncation for the non-legacy row paths.

    THE CHOKE POINT MATTERS HERE. `blueprints/ncaaf.py:85,91` route to
    `build_smartsim_cards_page_context`, NOT to `build_cards_page_context` --
    so a fix applied only to `_collapse_games` reaches the board solely on the
    fallback branch. There were THREE 16-caps on this module and they are on
    different branches of the same page:

        _collapse_games(limit=)      legacy recommendations_summary  (fallback)
        runtime_rows[:16]            legacy Enhanced Totals Engine rows
        runtime_rows[:16]            SmartSim2 standalone rows

    The third is the one that bites NEXT: it is empty today only because the
    SmartSim2 NCAAF projection artifact is missing (`CFBD_API_KEY` absent), and
    the moment that key lands it returns ~51 rows -- which the old `[:16]` would
    have silently cut back to 16, re-breaking the board at the exact moment it
    started working.
    """
    total = len(rows)
    counts["source"] = source
    counts["runtime_rows"] = total
    counts["limit"] = _NCAAF_BOARD_GAME_LIMIT
    counts["truncated"] = total > _NCAAF_BOARD_GAME_LIMIT
    counts["dropped"] = max(0, total - _NCAAF_BOARD_GAME_LIMIT)
    if counts["truncated"]:
        print(
            f"NCAAF_BOARD_TRUNCATED week={week} source={source} "
            f"rows={total} limit={_NCAAF_BOARD_GAME_LIMIT} dropped={counts['dropped']}",
            flush=True,
        )


def _collapse_games(summary: dict[str, Any], week: int, *, limit: int = _NCAAF_BOARD_GAME_LIMIT, counts: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    results = summary.get("results") if isinstance(summary.get("results"), list) else []
    best_rows: dict[tuple[str, str], dict[str, Any]] = {}
    for row in results:
        if not isinstance(row, dict):
            continue
        home_team = str(row.get("home_team") or "").strip()
        away_team = str(row.get("away_team") or "").strip()
        if not home_team or not away_team:
            continue
        key = (away_team, home_team)
        current = best_rows.get(key)
        candidate_edge = _safe_float(row.get("edge")) or float("-inf")
        if current is None:
            best_rows[key] = row
            continue
        current_edge = _safe_float(current.get("edge")) or float("-inf")
        if candidate_edge > current_edge:
            best_rows[key] = row
            continue
        candidate_stake = _safe_float(row.get("stake")) or 0.0
        current_stake = _safe_float(current.get("stake")) or 0.0
        if candidate_edge == current_edge and candidate_stake > current_stake:
            best_rows[key] = row

    ordered_rows = sorted(
        best_rows.values(),
        key=lambda row: ((_safe_float(row.get("edge")) or 0.0), (_safe_float(row.get("stake")) or 0.0)),
        reverse=True,
    )
    if counts is not None:
        # Recorded BEFORE the slice, which is the only point at which the
        # dropped rows are still countable.
        counts["summary_result_rows"] = len(results)
        counts["distinct_matchups"] = len(ordered_rows)
        counts["limit"] = limit
        counts["truncated"] = len(ordered_rows) > limit
        counts["dropped"] = max(0, len(ordered_rows) - limit)

    games: list[dict[str, Any]] = []
    for row in ordered_rows[:limit]:
        home_team = str(row.get("home_team") or "Home").strip() or "Home"
        away_team = str(row.get("away_team") or "Away").strip() or "Away"
        home_abbr = _abbr(home_team)
        away_abbr = _abbr(away_team)
        market = str(row.get("market") or "ML").strip().upper() or "ML"
        side = str(row.get("side") or "Home").strip() or "Home"
        provider = str(row.get("provider") or "Book").strip() or "Book"
        price = format_moneyline(row.get("price_american"))
        model_prob = format_pct(row.get("model_prob"))
        implied_prob = format_pct(row.get("implied_prob"))
        edge = format_pct(row.get("edge"))
        stake = _stake_text(row.get("stake"))
        favored_team = home_team if side.lower() == "home" else away_team
        ncaaf_card = _build_ncaaf_card_contract(row, week, season=default_season())
        games.append(
            {
                "gamePk": f"{week}_{away_team}_{home_team}".replace(" ", "_"),
                "card_variant": "ncaaf_main",
                "away": {"abbr": away_abbr, "name": away_team},
                "home": {"abbr": home_abbr, "name": home_team},
                "href": f"/ncaaf/game/{f'{week}_{away_team}_{home_team}'.replace(' ', '_')}?week={week}",
                "href_label": "Open NCAAF game detail",
                "status": f"Week {week}",
                "detail": "Historical summary",
                "summary": f"{favored_team} is the best {market} recommendation from {provider} at {price} with modeled edge {edge}.",
                **ncaaf_card.get("summary", {}),
                "ncaaf_card": ncaaf_card,
                "metrics": [
                    {"label": "Model", "value": model_prob},
                    {"label": "Implied", "value": implied_prob},
                    {"label": "Price", "value": price},
                    {"label": "Stake", "value": stake},
                    {"label": "Edge", "value": edge},
                ],
                "panels": [
                    {
                        "eyebrow": "Official card",
                        "title": provider,
                        "body": "The first NCAAF cards board groups the weekly recommendations summary into one best available recommendation per matchup.",
                        "items": [
                            f"Market: {market}",
                            f"Side: {side}",
                            f"Stake: {stake}",
                        ],
                    },
                    {
                        "eyebrow": "Model vs price",
                        "title": f"Model {model_prob} | Implied {implied_prob}",
                        "body": f"Best listed price is {price} from {provider}, producing modeled edge {edge}.",
                        "items": [
                            f"Kelly fraction: {_kelly_text(row.get('kelly_f'))}",
                            f"Raw edge multiple: {format_num(row.get('edge'))}",
                            f"Recommendation: {favored_team}",
                        ],
                    },
                    {
                        "eyebrow": "Game context",
                        "title": _week_label(week),
                        "body": f"{away_team} at {home_team} from the stored NCAAF recommendations summary.",
                        "items": [
                            f"Provider: {provider}",
                            "Current source artifacts are offseason weekly snapshots rather than live slate data.",
                        ],
                    },
                ],
                "market_tiles": [
                    {"label": "Coverage", "title": _format_decimal(ncaaf_card["summary"]["coverage_score"], places=3), "sub": ncaaf_card["summary"]["ready_label"]},
                    {"label": "Tier", "title": str(ncaaf_card["summary"]["coverage_tier"] or "-").upper(), "sub": "Enhanced Totals Engine tier"},
                    {"label": "Status", "title": str(ncaaf_card["summary"]["publication_status"] or "-").title(), "sub": "Publication state"},
                    {"label": "Priority", "title": str(ncaaf_card["summary"]["publication_priority"] or "-"), "sub": "Board order"},
                ],
            }
        )
    return games


def _clamp_week(selected_week: int) -> int:
    return resolve_selected_value(selected_week, available_weeks(), 1)


def _build_smartsim_ncaaf_card_contract(row: dict[str, Any], week: int, *, season: int) -> dict[str, Any]:
    home_team = str(row.get("home_team") or "Home").strip() or "Home"
    away_team = str(row.get("away_team") or "Away").strip() or "Away"
    home_abbr = _abbr(home_team)
    away_abbr = _abbr(away_team)
    home_context = _team_context(home_team, season)
    away_context = _team_context(away_team, season)
    scoreboard = _runtime_scoreboard_projection(row, week)
    publication_profile = _runtime_publication_profile(scoreboard)
    coverage_score = publication_profile.get("coverage_score")
    coverage_tier = publication_profile.get("coverage_tier")
    publication_status = publication_profile.get("publication_status")
    publication_priority = publication_profile.get("publication_priority")
    publication_ready = publication_profile.get("publication_ready")
    metric_rows = [
        {"label": "Home mean", "value": scoreboard.get("home_points") or "-"},
        {"label": "Away mean", "value": scoreboard.get("away_points") or "-"},
        {"label": "Projected total", "value": scoreboard.get("total_points") or "-"},
        {"label": "Projected spread", "value": scoreboard.get("spread_label") or "-"},
        {"label": "Win probability", "value": scoreboard.get("win_probability") or "-"},
    ]
    summary_text = (
        f"{LEGACY_ENGINE_SOURCE_LABEL} projects {home_team} {scoreboard.get('home_points') or '-'} - "
        f"{scoreboard.get('away_points') or '-'} {away_team} with a total of "
        f"{scoreboard.get('total_points') or '-'} and a home win probability of "
        f"{scoreboard.get('win_probability') or '-'}."
    )
    matchup_context_sections = [
        {
            "label": "Returned production",
            "home": home_context["returning"]["summary"],
            "away": away_context["returning"]["summary"],
            "detail": "Starter estimate, production share, and usage from the published snapshot.",
        },
        {
            "label": "Coach continuity",
            "home": home_context["coach"]["summary"],
            "away": away_context["coach"]["summary"],
            "detail": "Continuity score and tenure from the published coach snapshot.",
        },
        {
            "label": "Transfer activity",
            "home": home_context["transfer"]["summary"],
            "away": away_context["transfer"]["summary"],
            "detail": "Incoming, outgoing, and net transfer counts.",
        },
        {
            "label": "Roster base",
            "home": home_context["roster"]["summary"],
            "away": away_context["roster"]["summary"],
            "detail": "Active roster snapshot rows linked to each team.",
        },
    ]
    team_context = {
        "items": _build_team_context_items(home_context, away_context),
        "summary": "Return production, portal impact, coach continuity, and roster experience",
    }
    matchup_context = {
        "items": _build_matchup_context_items(home_context, away_context),
        "summary": "Conference, returning production, portal, coach, and roster comparisons",
    }
    smartsim_reasons = _build_smartsim_reasons_items(home_context, away_context, scoreboard)
    return {
        "gamePk": f"{week}_{away_team}_{home_team}".replace(" ", "_"),
        "card_variant": "ncaaf_main",
        # Same block as the standalone card below, on the ENGINE path.
        #
        # Both paths carry it because which one a game takes is decided by
        # whether the legacy engine happens to have a row for that (season,
        # week) -- nothing to do with props. Wiring only the path that is live
        # today would mean props silently disappearing from a card the moment
        # an engine row appeared for it, which reads to a user as "the books
        # pulled the market".
        "prop_recommendations": ncaaf_props.prop_recommendations_for_game(
            season=season, week=week, home_team=home_team, away_team=away_team
        ),
        "away": {
            "abbr": away_abbr,
            "name": away_team,
            "logo_url": away_context["logo_url"],
            "primary_color": away_context["primary_color"],
            "secondary_color": away_context["secondary_color"],
        },
        "home": {
            "abbr": home_abbr,
            "name": home_team,
            "logo_url": home_context["logo_url"],
            "primary_color": home_context["primary_color"],
            "secondary_color": home_context["secondary_color"],
        },
        "href": f"/ncaaf/game/{f'{week}_{away_team}_{home_team}'.replace(' ', '_')}?week={week}",
        "href_label": "Open NCAAF game detail",
        "status": f"Week {week}",
        "detail": LEGACY_ENGINE_SOURCE_LABEL,
        "summary": summary_text,
        "metrics": metric_rows,
        "smartsim_reasons": smartsim_reasons,
        "panels": [
            {
                "eyebrow": LEGACY_ENGINE_SOURCE_LABEL,
                "title": "Projection contract",
                "body": "Cards now read directly from the predicted totals snapshot instead of saved recommendation summaries.",
                "items": [
                    f"Home mean: {scoreboard.get('home_points') or '-'}",
                    f"Away mean: {scoreboard.get('away_points') or '-'}",
                    f"Projected spread: {scoreboard.get('spread_label') or '-'}",
                    f"Projected total: {scoreboard.get('total_points') or '-'}",
                    f"Win probability: {scoreboard.get('win_probability') or '-'}",
                ],
            },
            {
                "eyebrow": LEGACY_ENGINE_SOURCE_LABEL,
                "title": "Source and fallback",
                "body": "The runtime cards path can fall back to the summary artifact path if the predicted-totals snapshot is unavailable.",
                "items": [
                    f"Projection source: {scoreboard.get('source_label') or LEGACY_ENGINE_SOURCE_LABEL}",
                    f"Kickoff: {scoreboard.get('kickoff') or 'Kickoff unavailable'}",
                    f"Venue: {scoreboard.get('venue') or 'Venue unavailable'}",
                ],
            },
        ],
        "market_tiles": [
            {"label": "Coverage", "title": _format_decimal(coverage_score, places=3), "sub": "Enhanced Totals Engine tier"},
            {"label": "Tier", "title": str(coverage_tier or "-").upper(), "sub": "Enhanced Totals Engine tier"},
            {"label": "Status", "title": str(publication_status or "-").title(), "sub": "Publication state"},
            {"label": "Priority", "title": str(publication_priority or "-"), "sub": "Board order"},
        ],
        # TOP LEVEL, beside `ncaaf_card` and NOT inside it.
        # `publication_adapter._shared_predictions` reads `game["predictions"]`.
        # The first cut put this inside `ncaaf_card`, where nothing reads it:
        # production deployed clean and still served 0/51 non-null means.
        # The structural test asserted the builders CALL the helper and never
        # WHERE the result lands, so it passed on a payload that did nothing.
        # `row.get`, not a bare name: this builder has no `projection` in
        # scope. The bare name was a NameError on every call -- see the
        # commit message. Absent yields `{}` from the helper, which is the
        # contract its own docstring states: absent stays absent.
        # ENGINE ROWS CARRY THE PROJECTION IN COLUMNS, not as an object.
        "predictions": _ncaaf_shared_predictions_block(
            row.get("projection") or _engine_row_projection(row),
            market_margin=row.get("market_margin"),
            market_total=row.get("market_total"),
        ),
        "ncaaf_card": {
            "version": _NCAAF_CARD_CONTRACT_VERSION,
            "summary": {
                "coverage_score": coverage_score,
                "coverage_tier": coverage_tier,
                "publication_status": publication_status,
                "publication_priority": publication_priority,
                "publication_ready": publication_ready,
                "ready_label": "Publication ready" if publication_ready else "Publication blocked",
                "tier_badges": publication_profile.get("tier_badges") or _tier_badges(coverage_tier),
            },
            "teams": {
                "home": home_context,
                "away": away_context,
            },
            "scoreboard": scoreboard,
            "scoreboard_header": {
                "away": {
                    "abbr": away_context["abbreviation"],
                    "rank": away_context["rank"],
                    "school_name": away_context["school_name"],
                    "mascot_name": away_context["mascot_name"],
                    "conference": away_context["conference"],
                    "conference_short_name": away_context["conference_short_name"],
                    "logo_url": away_context["logo_url"],
                    "logo_text": away_context["abbreviation"],
                    "primary_color": away_context["primary_color"],
                    "secondary_color": away_context["secondary_color"],
                },
                "home": {
                    "abbr": home_context["abbreviation"],
                    "rank": home_context["rank"],
                    "school_name": home_context["school_name"],
                    "mascot_name": home_context["mascot_name"],
                    "conference": home_context["conference"],
                    "conference_short_name": home_context["conference_short_name"],
                    "logo_url": home_context["logo_url"],
                    "logo_text": home_context["abbreviation"],
                    "primary_color": home_context["primary_color"],
                    "secondary_color": home_context["secondary_color"],
                },
                "kickoff": scoreboard.get("kickoff") or f"{_week_label(week, season=season)} kickoff unavailable",
                "kickoff_label": scoreboard.get("kickoff_label") or f"{_week_label(week, season=season)} kickoff unavailable",
                "venue": scoreboard.get("venue") or "Venue unavailable",
                "status": f"Week {week}",
                "status_detail": LEGACY_ENGINE_SOURCE_LABEL,
            },
            "team_context": team_context,
            "matchup_context": matchup_context,
            "smartsim_reasons": smartsim_reasons,
            "context_sections": matchup_context_sections,
        },
    }

def _build_smartsim2_standalone_ncaaf_card_contract(row: dict[str, Any], week: int, *, season: int) -> dict[str, Any]:
    """Honestly-labeled card for a (season, week) the legacy engine has no
    data for -- every label says SmartSim 2.0, never Enhanced Totals Engine.
    Fabricating engine involvement that never happened would violate this
    whole project's disclosure discipline (see smartsim_ats_policy_implementation_report.md
    and the 2026 season bootstrap this path was built for). Produces the
    same ``ncaaf_card`` contract shape as the engine path so templates need
    no changes; only the content and labeling differ."""
    home_team = str(row["home_team"])
    away_team = str(row["away_team"])
    projection: SmartSimNcaafProjection = row["projection"]
    home_abbr = _abbr(home_team)
    away_abbr = _abbr(away_team)
    home_context = _team_context(home_team, season)
    away_context = _team_context(away_team, season)

    home_points = round(projection.home_score_mean, 1)
    away_points = round(projection.away_score_mean, 1)
    total_points = round(projection.total_mean, 1)
    margin = projection.margin_mean
    if margin > 0:
        spread_label = f"{home_team} by {abs(margin):.1f}"
    elif margin < 0:
        spread_label = f"{away_team} by {abs(margin):.1f}"
    else:
        spread_label = "Pick'em"
    win_probability = format_pct(projection.home_win_rate)
    market_margin = row.get("market_margin")
    market_total = row.get("market_total")
    row_market_margin = _safe_float(market_margin)
    row_market_total = _safe_float(market_total)

    scoreboard = {
        "home_points": home_points,
        "away_points": away_points,
        "total_points": total_points,
        "spread_label": spread_label,
        "win_probability": win_probability,
        "source_label": SMARTSIM2_PUBLIC_LABEL,
        "kickoff": row.get("start_date") or "Kickoff unavailable",
        "kickoff_label": _format_kickoff_label(row.get("start_date")) or "Kickoff unavailable",
        "venue": row.get("venue") or "Venue unavailable",
        "smartsim2_available": True,
        "smartsim2_margin": projection.margin_mean,
        "smartsim2_total_points": projection.total_mean,
        "smartsim2_margin_stdev": projection.margin_stdev,
        "smartsim2_total_stdev": projection.total_stdev,
        "market_margin": market_margin,
        "market_total": market_total,
        # Raw 0-1 float, additive alongside the formatted "win_probability"
        # string above -- the market board needs a real number to join against.
        "home_win_probability": projection.home_win_rate,
    }

    summary_text = (
        f"{SMARTSIM2_PUBLIC_LABEL} projects {home_team} {home_points} - {away_points} {away_team} "
        f"with a total of {total_points} and a home win probability of {win_probability}. "
        f"{LEGACY_ENGINE_SOURCE_LABEL} has no prediction for this game yet."
    )
    # `#557`. THE MARKET GOES FIRST, and the ordering is the whole point.
    #
    # The compact card (`shared/_scoreboard_strip_generic.html`) renders
    # `metrics[:3]` and nothing else, so whatever sits in the first three slots
    # IS the compact card. Until now those were three model numbers, which meant
    # a board built for betting showed no price at its most-scanned surface.
    # Putting the line first is a data-side change; the shared template is
    # untouched, because it is rendered by six other sports.
    #
    # When no book has quoted the game the model rows simply move back up, so
    # the card never shows an empty tile.
    metric_rows = [
        row
        for row in (
            _market_metric_row(row_market_margin),
            {"label": "Market total", "value": f"{row_market_total:.1f}"} if row_market_total is not None else None,
        )
        if row is not None
    ] + [
        {"label": "Projected total", "value": total_points},
        {"label": "Projected spread", "value": spread_label},
        {"label": "Home mean", "value": home_points},
        {"label": "Away mean", "value": away_points},
        {"label": "Win probability", "value": win_probability},
    ]
    matchup_context_sections = [
        {
            "label": "Returned production",
            "home": home_context["returning"]["summary"],
            "away": away_context["returning"]["summary"],
            "detail": "Starter estimate, production share, and usage from the published snapshot.",
        },
        {
            "label": "Coach continuity",
            "home": home_context["coach"]["summary"],
            "away": away_context["coach"]["summary"],
            "detail": "Continuity score and tenure from the published coach snapshot.",
        },
        {
            "label": "Transfer activity",
            "home": home_context["transfer"]["summary"],
            "away": away_context["transfer"]["summary"],
            "detail": "Incoming, outgoing, and net transfer counts.",
        },
        {
            "label": "Roster base",
            "home": home_context["roster"]["summary"],
            "away": away_context["roster"]["summary"],
            "detail": "Active roster snapshot rows linked to each team.",
        },
    ]
    team_context = {
        "items": _build_team_context_items(home_context, away_context),
        "summary": "Return production, portal impact, coach continuity, and roster experience",
    }
    matchup_context = {
        "items": _build_matchup_context_items(home_context, away_context),
        "summary": "Conference, returning production, portal, coach, and roster comparisons",
    }

    return {
        "gamePk": f"{week}_{away_team}_{home_team}".replace(" ", "_"),
        "card_variant": "ncaaf_main",
        "away": {
            "abbr": away_abbr,
            "name": away_team,
            "logo_url": away_context["logo_url"],
            "primary_color": away_context["primary_color"],
            "secondary_color": away_context["secondary_color"],
        },
        "home": {
            "abbr": home_abbr,
            "name": home_team,
            "logo_url": home_context["logo_url"],
            "primary_color": home_context["primary_color"],
            "secondary_color": home_context["secondary_color"],
        },
        "href": f"/ncaaf/game/{f'{week}_{away_team}_{home_team}'.replace(' ', '_')}?week={week}",
        "href_label": "Open NCAAF game detail",
        "status": f"Week {week}",
        "detail": SMARTSIM2_PUBLIC_LABEL,
        "summary": summary_text,
        "metrics": metric_rows,
        "smartsim_reasons": [],
        "panels": [
            {
                "eyebrow": SMARTSIM2_PUBLIC_LABEL,
                "title": "Projection contract",
                "body": f"{LEGACY_ENGINE_SOURCE_LABEL} has no prediction for this game yet, so this card shows SmartSim 2.0's own projection directly, unblended.",
                "items": [
                    f"Home mean: {scoreboard['home_points']}",
                    f"Away mean: {scoreboard['away_points']}",
                    f"Projected spread: {scoreboard['spread_label']}",
                    f"Projected total: {scoreboard['total_points']}",
                    f"Win probability: {scoreboard['win_probability']}",
                ],
            },
            {
                "eyebrow": SMARTSIM2_PUBLIC_LABEL,
                "title": "Source and fallback",
                "body": "This game has no Enhanced Totals Engine row for this season yet -- there is no blend to fall back to.",
                "items": [
                    f"Projection source: {SMARTSIM2_PUBLIC_LABEL}",
                    f"Kickoff: {scoreboard['kickoff']}",
                    f"Venue: {scoreboard['venue']}",
                ],
            },
        ],
        "market_tiles": _smartsim2_standalone_market_tiles(row, projection),
        # `#557`. THE SHARED CONTRACT'S OWN BLOCK, and it is what was missing.
        #
        # `publication_adapter._shared_markets` builds the cross-sport
        # `markets` / `shared_markets` dict by looking for `home_ml` / `away_ml`
        # / `home_spread` / `away_spread` / `total` under `betting`, `markets` or
        # `market`. This card emitted none of them -- the line lived only in
        # `scoreboard`, which that adapter never reads -- so `markets` was null
        # on every game even once a real line existed. Measured: with the line
        # index populated for 8 games, `markets` non-null stayed at 0 of 51
        # until this block was added.
        #
        # SIGN. `market_margin` is a HOME MARGIN (positive = home favoured); a
        # book's home spread is NEGATIVE when the home side is favoured, so the
        # two are negatives of each other. Getting this backwards produces
        # entirely plausible numbers pointing at the wrong team -- the same trap
        # `state.md` records costing a whole NFL analysis via nflverse's
        # `spread_line`. `tests/test_ncaaf_oddsapi_game_lines.py` pins it.
        "betting": _smartsim2_standalone_betting(row, projection),
        # THE BLOCK THAT PUTS PROPS ON THE BOARD.
        #
        # `game_board_contract._build_prop_rows` reads exactly this key and
        # nothing else -- `{"away": [...], "home": [...]}` -- and derives each
        # row's heading from the LIST IT IS IN. Nothing else in this card had
        # to change, and the shared contract did not have to change at all.
        #
        # Measured on production 2026-08-26, before this: all 51 served wk1
        # cards carried `shared_prop_rows: []` while 6 of 6 probed openers had
        # real markets upstream. The comment two hundred lines up in this file
        # said "NCAAF has no props pipeline yet" and was accurate.
        #
        # Returns `{}` when nothing was captured for this game, which is the
        # correct pregame state for a slate whose books have not posted yet --
        # NOT an error, and not something to backfill on the request path.
        "prop_recommendations": ncaaf_props.prop_recommendations_for_game(
            season=season, week=week, home_team=home_team, away_team=away_team
        ),
        # TOP LEVEL, beside `ncaaf_card` and NOT inside it.
        # `publication_adapter._shared_predictions` reads `game["predictions"]`.
        # The first cut put this inside `ncaaf_card`, where nothing reads it:
        # production deployed clean and still served 0/51 non-null means.
        # The structural test asserted the builders CALL the helper and never
        # WHERE the result lands, so it passed on a payload that did nothing.
        "predictions": _ncaaf_shared_predictions_block(projection, market_margin=row_market_margin, market_total=row_market_total),
        "ncaaf_card": {
            "version": _NCAAF_CARD_CONTRACT_VERSION,
            "summary": {
                "coverage_score": None,
                "coverage_tier": "smartsim2_only",
                "publication_status": "publishable",
                "publication_priority": None,
                "publication_ready": True,
                "ready_label": "Publication ready",
                "tier_badges": [{"label": "SmartSim 2.0", "active": True}],
            },
            "teams": {
                "home": home_context,
                "away": away_context,
            },
            "scoreboard": scoreboard,
            "scoreboard_header": {
                "away": {
                    "abbr": away_context["abbreviation"],
                    "rank": away_context["rank"],
                    "school_name": away_context["school_name"],
                    "mascot_name": away_context["mascot_name"],
                    "conference": away_context["conference"],
                    "conference_short_name": away_context["conference_short_name"],
                    "logo_url": away_context["logo_url"],
                    "logo_text": away_context["abbreviation"],
                    "primary_color": away_context["primary_color"],
                    "secondary_color": away_context["secondary_color"],
                },
                "home": {
                    "abbr": home_context["abbreviation"],
                    "rank": home_context["rank"],
                    "school_name": home_context["school_name"],
                    "mascot_name": home_context["mascot_name"],
                    "conference": home_context["conference"],
                    "conference_short_name": home_context["conference_short_name"],
                    "logo_url": home_context["logo_url"],
                    "logo_text": home_context["abbreviation"],
                    "primary_color": home_context["primary_color"],
                    "secondary_color": home_context["secondary_color"],
                },
                "kickoff": scoreboard["kickoff"],
                "kickoff_label": scoreboard.get("kickoff_label") or scoreboard["kickoff"],
                "venue": scoreboard["venue"],
                "status": f"Week {week}",
                "status_detail": SMARTSIM2_PUBLIC_LABEL,
            },
            "team_context": team_context,
            "matchup_context": matchup_context,
            "smartsim_reasons": [],
            "context_sections": matchup_context_sections,
        },
    }


def _attach_live_state(games: list[dict[str, Any]], season: int, week: int) -> None:
    """Stamp ESPN live state onto the week's cards, before the board contract.

    MUST run before `apply_game_board_contract`: that is what calls
    `publication_adapter._shared_game_state`, and that function derives
    `live`/`final`/`period`/`clock` from `game["live_state"]` -- the field this
    board never set. Stamping after the contract would populate a dict nothing
    reads again.

    Fails soft to the board and loud to the log: NCAAF cards rendered without
    live state for the whole 2026 preseason, so a scoreboard outage must cost
    the eyebrow and nothing else.
    """
    if not games:
        return
    try:
        from syndicate.features.ncaaf.live_game_state import attach_ncaaf_live_game_state
        from syndicate.features.ncaaf.live_game_state import ncaaf_game_state_index
        from syndicate.features.ncaaf.live_game_state import stamp_scheduled_start_times

        index = ncaaf_game_state_index(_ncaaf_week_kickoff_dates(season, week))
        coverage = attach_ncaaf_live_game_state(games, index)
        # Every card, not just today's: the ESPN join only reaches dates that
        # have started, and kickoff is already on the card for all of them.
        coverage["scheduled"] = stamp_scheduled_start_times(games)
    except Exception as exc:  # noqa: BLE001 -- named, never fatal to the board
        print(f"NCAAF_LIVE_STATE_ERROR week={week} error={type(exc).__name__}: {exc}", flush=True)
        return
    # `matched` is printed separately from `live`/`final` because a dead join
    # and a quiet slate render identically and are different defects.
    # `logger.info` does not reach Render's collector -- hence print/flush.
    print(
        f"NCAAF_LIVE_STATE week={week} games={coverage.get('games')} "
        f"index={coverage.get('index')} matched={coverage.get('matched')} "
        f"live={coverage.get('live')} final={coverage.get('final')}",
        flush=True,
    )


def build_smartsim_cards_page_context(selected_week: int) -> dict[str, Any]:
    season, runtime_weeks = _resolve_ncaaf_active_season_and_weeks()
    if not runtime_weeks:
        return build_cards_page_context(selected_week)
    default_active_week = _ncaaf_default_active_week(season, runtime_weeks)
    requested_week = int(selected_week or default_active_week)
    resolved_week = resolve_selected_value(requested_week, runtime_weeks, default_active_week)

    board_row_counts: dict[str, Any] = {}
    engine_rows = _engine_rows_for_season_week(season, resolved_week)
    if engine_rows:
        # Unchanged path: real Enhanced Totals Engine data exists for this
        # exact (season, week) -- byte-identical to the pre-2026-bootstrap
        # behavior.
        runtime_rows = engine_rows
        games = [
            _build_smartsim_ncaaf_card_contract(row, resolved_week, season=season)
            for row in runtime_rows[:_NCAAF_BOARD_GAME_LIMIT]
        ]
        _note_board_truncation(board_row_counts, "legacy_engine", runtime_rows, resolved_week)
        source_label_for_page = LEGACY_ENGINE_SOURCE_LABEL
    else:
        # No engine row for this season/week (e.g. 2026, while NCAAFCompare
        # is unavailable) -- fall back to real schedule + real SmartSim 2.0
        # projections, honestly labeled, never claiming engine involvement.
        runtime_rows = _smartsim2_standalone_rows(season, resolved_week)
        if not runtime_rows:
            return build_cards_page_context(selected_week)
        games = [
            _build_smartsim2_standalone_ncaaf_card_contract(row, resolved_week, season=season)
            for row in runtime_rows[:_NCAAF_BOARD_GAME_LIMIT]
        ]
        _note_board_truncation(board_row_counts, "smartsim2_standalone", runtime_rows, resolved_week)
        source_label_for_page = SMARTSIM2_PUBLIC_LABEL

    _attach_live_state(games, season, resolved_week)

    record_trial_page_view(
        route="/ncaaf/cards",
        season=season,
        week=resolved_week,
        scoreboards=[
            game["ncaaf_card"]["scoreboard"]
            for game in games
            if isinstance(game.get("ncaaf_card"), dict) and isinstance(game["ncaaf_card"].get("scoreboard"), dict)
        ],
    )
    weeks = runtime_weeks
    prev_week, next_week = neighboring_values(weeks, resolved_week, fallback=resolved_week)
    source_path = _prediction_source_path() if engine_rows else None
    betting_href = f"/ncaaf/season/{season}/betting-card?week={resolved_week}"
    return apply_game_board_contract(
        {
            "date": _week_label(resolved_week, season=season),
            "requested_date": _week_label(selected_week, season=season),
            "prev_date": str(prev_week),
            "next_date": str(next_week),
            "control_action": "/ncaaf/cards",
            "controls_prev_href": f"/ncaaf/cards?week={prev_week}",
            "controls_next_href": f"/ncaaf/cards?week={next_week}",
            "control_label": "Week",
            "control_type": "number",
            "control_name": "week",
            "control_value": str(resolved_week),
            "module_links": build_module_links(resolved_week, "Cards"),
            "games": games,
            _NCAAF_BOARD_COUNTS_KEY: board_row_counts,
            "scoreboard_items": [
                {
                    "target_id": f"game-{game['gamePk']}",
                    "label": f"{game['away']['abbr']} @ {game['home']['abbr']}",
                    "status": game["status"],
                }
                for game in games
            ],
            "source_path": str(source_path) if source_path else f"NCAAF {source_label_for_page} predicted totals",
            "source_title": f"NCAAF {source_label_for_page} cards runtime",
            "empty_state": {
                "eyebrow": "NCAAF cards",
                "title": f"No {source_label_for_page} cards were available for this week",
                "body": f"The cards board first reads the {LEGACY_ENGINE_SOURCE_LABEL} predicted-totals snapshot, falls back to real SmartSim 2.0 projections for a season the engine has no data for, and falls back to saved weekly summaries only if neither runtime path is available.",
                "list_items": [
                    f"Requested week: {selected_week}",
                    f"Resolved week: {resolved_week}",
                ],
            } if not games else None,
            "using_sample_data": False,
            "route_path": "/ncaaf/cards",
            "intro_title": "NCAAF Cards",
            "intro_body": f"NCAAF cards now read directly from {source_label_for_page} predicted totals first, with saved recommendation summaries kept as a fallback path.",
            "cards_control_links": [
                {"label": "Betting Card", "href": betting_href},
                {"label": "Picks", "href": f"/ncaaf/picks?week={resolved_week}"},
                {"label": "Live Lens", "href": f"/ncaaf/live-lens?week={resolved_week}"},
            ],
            "header_stats": [
                {"label": "Games", "value": str(len(games))},
                {"label": "Candidates", "value": str(len(runtime_rows))},
                {"label": "Weeks", "value": str(len(weeks) or "-")},
                {"label": "Source", "value": source_label_for_page if games else "No data"},
            ],
            "cards_stylesheet": None,
            "cards_grid_class": "cards-grid",
            "show_source_summary": True,
            "show_intro": True,
            "teaser": {
                "label": "NCAAF picks",
                "body": f"Use the picks board for the historical weekly recommendation rows that remain separate from the {LEGACY_ENGINE_SOURCE_LABEL} cards path.",
                "href": f"/ncaaf/picks?week={resolved_week}",
                "cta": "Open NCAAF picks",
            },
            "active_sport_name": "NCAAF",
        },
        sport="ncaaf",
        module="cards",
        source_kind="smartsim_runtime",
        live_lens_integrated=False,
        include_simulation_contract=True,
    )


def build_cards_page_context(selected_week: int) -> dict[str, Any]:
    season = default_season()
    resolved_week = _clamp_week(selected_week or default_week())
    betting_href = f"/ncaaf/season/{season}/betting-card?week={resolved_week}"
    path = summary_path(resolved_week)
    summary = load_json(path) or {}
    board_row_counts: dict[str, Any] = {}
    games = _collapse_games(summary, resolved_week, counts=board_row_counts)
    if board_row_counts.get("truncated"):
        # A cap that bites must announce it. Web's own stdout IS collected by
        # Render (unlike a worker's detached child), and `logger.info` is not --
        # hence print/flush.
        print(
            f"NCAAF_BOARD_TRUNCATED week={resolved_week} "
            f"matchups={board_row_counts.get('distinct_matchups')} "
            f"limit={board_row_counts.get('limit')} "
            f"dropped={board_row_counts.get('dropped')}",
            flush=True,
        )
    using_sample_data = False

    _attach_live_state(games, season, resolved_week)

    weeks = available_weeks()
    prev_week, next_week = neighboring_values(weeks, resolved_week, fallback=resolved_week)
    return apply_game_board_contract(
        {
            "date": _week_label(resolved_week, season=season),
            "requested_date": _week_label(selected_week, season=season),
            "prev_date": str(prev_week),
            "next_date": str(next_week),
            "control_action": "/ncaaf/cards",
            "controls_prev_href": f"/ncaaf/cards?week={prev_week}",
            "controls_next_href": f"/ncaaf/cards?week={next_week}",
            "control_label": "Week",
            "control_type": "number",
            "control_name": "week",
            "control_value": str(resolved_week),
            "module_links": build_module_links(resolved_week, "Cards"),
            "games": games,
            _NCAAF_BOARD_COUNTS_KEY: board_row_counts,
            "scoreboard_items": [
                {
                    "target_id": f"game-{game['gamePk']}",
                    "label": f"{game['away']['abbr']} @ {game['home']['abbr']}",
                    "status": game["status"],
                }
                for game in games
            ],
            "source_path": str(path),
            "source_title": "NCAAF recommendations summary" if games else "NCAAF cards unavailable",
            "empty_state": {
                "eyebrow": "NCAAF cards",
                "title": "No game cards were available for this week",
                "body": "The cards board only renders saved NCAAF recommendation summary rows, and none were available for the requested week.",
                "list_items": [
                    f"Requested week: {selected_week}",
                    f"Resolved week: {resolved_week}",
                ],
            } if not games else None,
            "using_sample_data": using_sample_data,
            "route_path": "/ncaaf/cards",
            "intro_title": "NCAAF Cards",
            "intro_body": "NCAAF enters the shared game-board contract with a first weekly cards surface built from stored recommendation summary artifacts in the source app.",
            "cards_control_links": [
                {"label": "Betting Card", "href": betting_href},
                {"label": "Picks", "href": f"/ncaaf/picks?week={resolved_week}"},
                {"label": "Live Lens", "href": f"/ncaaf/live-lens?week={resolved_week}"},
            ],
            "header_stats": [
                {"label": "Games", "value": str(len(games))},
                {"label": "Rows", "value": str(len(summary.get('results') or []))},
                {"label": "Weeks", "value": str(len(weeks) or "-")},
                {"label": "Source", "value": "Summary" if games else "No data"},
            ],
            "cards_stylesheet": None,
            "cards_grid_class": "cards-grid",
            "show_source_summary": True,
            "show_intro": True,
            "teaser": {
                "label": "NCAAF picks",
                "body": "Use the picks board for the ranked weekly recommendation rows behind these matchup cards.",
                "href": f"/ncaaf/picks?week={resolved_week}",
                "cta": "Open NCAAF picks",
            },
            "active_sport_name": "NCAAF",
        },
        sport="ncaaf",
        module="cards",
        source_kind="artifact_backed",
        live_lens_integrated=False,
    )