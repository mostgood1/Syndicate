from __future__ import annotations

"""Deterministic evidence fetchers for Ask the Syndicate.

These read sim artifacts straight off the data disk and turn them into
tables/charts plus a compact numeric summary for the LLM evidence pack.
Everything numeric here is computed in Python -- the LLM only narrates it,
which is what keeps the no-fabrication guarantee intact.

Coverage:
- MLB: per-game sim distributions (total runs, run margin, win probs),
  starter strikeout distributions, batter-vs-pitcher history for today's
  matchups, and the sim-vs-actual accuracy trend.
- WNBA: per-player sim projections joined to market prop lines, plus
  last-N game logs from boxscore history.
- NBA: last-N game logs from boxscore history.
- NHL: last-N game logs from player game stats.
"""

import csv
import glob
import json
import logging
import os
import re
import threading
import unicodedata
from typing import Any

logger = logging.getLogger(__name__)

MAX_CHART_POINTS = 30
MAX_LOOKBACK_FILES = 10
LAST_N_GAMES = 10
MAX_TABLES = 8
MAX_CHARTS = 5

_WNBA_TEAM_NAMES: dict[str, str] = {
    "ATL": "Atlanta Dream",
    "CHI": "Chicago Sky",
    "CON": "Connecticut Sun",
    "DAL": "Dallas Wings",
    "GSV": "Golden State Valkyries",
    "IND": "Indiana Fever",
    "LAS": "Los Angeles Sparks",
    "LVA": "Las Vegas Aces",
    "LV": "Las Vegas Aces",
    "MIN": "Minnesota Lynx",
    "NYL": "New York Liberty",
    "PHX": "Phoenix Mercury",
    "SEA": "Seattle Storm",
    "WAS": "Washington Mystics",
}


def _question_words(question: str) -> set[str]:
    return set(re.findall(r"[a-z0-9']+", str(question or "").lower()))


def _clip(text: Any, limit: int) -> str:
    value = str(text or "").strip()
    return value if len(value) <= limit else value[: limit - 1] + "…"


def _fold_diacritics(text: str) -> str:
    """Strip accents so "Pérez" tokenizes to "perez" instead of splitting into
    ["p", "rez"] under the ASCII-only [a-z0-9']+ pattern below -- MLB Stats
    API returns some player names accented and others not (e.g. "Eury Pérez"
    vs "Salvador Perez"), so name matching has to be accent-insensitive to be
    consistent regardless of which convention a given data source used.
    """
    normalized = unicodedata.normalize("NFKD", str(text or ""))
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def _name_matches(name: str, words: set[str]) -> bool:
    """True when a multi-word name is plausibly referenced by the question."""
    parts = [p for p in re.findall(r"[a-z0-9']+", _fold_diacritics(str(name or "")).lower()) if len(p) >= 3]
    if not parts:
        return False
    # Last name alone is enough for people; any distinctive word for teams.
    return any(part in words for part in parts)


def _person_matches(name: str, words: set[str]) -> int:
    """Match score for a person's name: 0 = no, 1 = last name only, 2 = first+last."""
    parts = [p for p in re.findall(r"[a-z0-9']+", _fold_diacritics(str(name or "")).lower()) if len(p) >= 3]
    if not parts or parts[-1] not in words:
        return 0
    return 2 if len(parts) > 1 and parts[0] in words else 1


def _question_lines(question: str) -> list[float]:
    """Numbers in the question that look like prop lines (e.g. 28.5, 8.5)."""
    return [float(m) for m in re.findall(r"\b(\d{1,3}\.5)\b", str(question or ""))]


def _to_float(value: Any) -> float | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        return float(value)
    except Exception:
        return None


def _dist_points(dist: dict[str, Any]) -> list[tuple[int, float]]:
    points: list[tuple[int, float]] = []
    for key, count in (dist or {}).items():
        try:
            points.append((int(key), float(count)))
        except (TypeError, ValueError):
            continue
    points.sort(key=lambda item: item[0])
    return points


def _dist_stats(dist: dict[str, Any]) -> dict[str, float] | None:
    points = _dist_points(dist)
    total = sum(count for _, count in points)
    if not points or total <= 0:
        return None
    mean = sum(value * count for value, count in points) / total
    cumulative = 0.0
    percentiles: dict[str, float] = {}
    targets = {"p10": 0.10, "p50": 0.50, "p90": 0.90}
    remaining = dict(targets)
    for value, count in points:
        cumulative += count
        for label, threshold in list(remaining.items()):
            if cumulative / total >= threshold:
                percentiles[label] = float(value)
                remaining.pop(label)
    return {"mean": round(mean, 2), **percentiles}


def _dist_chart(dist: dict[str, Any], *, title: str, x_label: str) -> dict[str, Any] | None:
    points = _dist_points(dist)
    total = sum(count for _, count in points)
    if not points or total <= 0:
        return None
    # Trim the extreme tail so the chart stays readable.
    if len(points) > MAX_CHART_POINTS:
        points.sort(key=lambda item: item[1], reverse=True)
        points = sorted(points[:MAX_CHART_POINTS], key=lambda item: item[0])
    return {
        "type": "bar",
        "title": title,
        "x_label": x_label,
        "y_label": "% of sims",
        "points": [
            {"x": str(value), "y": round(100.0 * count / total, 2)}
            for value, count in points
        ],
    }


def _latest_dated_file(pattern: str, date_regex: str) -> tuple[str, str] | None:
    """Return (path, iso_date) for the newest file whose name carries a date."""
    candidates: list[tuple[str, str]] = []
    for path in glob.glob(pattern):
        match = re.search(date_regex, os.path.basename(path))
        if match:
            iso = match.group(1).replace("_", "-")
            candidates.append((iso, path))
    if not candidates:
        return None
    candidates.sort()
    iso, path = candidates[-1]
    return path, iso


def _load_json(path: str) -> Any:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


# ---------------------------------------------------------------------------
# MLB
# ---------------------------------------------------------------------------


def _syndicate_data_root() -> str:
    return os.environ.get("SYNDICATE_DATA_ROOT", "data")


def _mlb_data_root() -> str:
    return os.environ.get(
        "MLB_BETTING_DATA_ROOT",
        os.path.join(_syndicate_data_root(), "mlb_source", "source_artifacts", "data"),
    )


def _mlb_daily_summary(selected_date: str | None) -> tuple[dict[str, Any], str] | None:
    daily_dir = os.path.join(_mlb_data_root(), "daily")
    if selected_date:
        path = os.path.join(daily_dir, f"daily_summary_{selected_date.replace('-', '_')}.json")
        if os.path.exists(path):
            return _load_json(path), selected_date
    found = _latest_dated_file(
        os.path.join(daily_dir, "daily_summary_????_??_??.json"),
        r"daily_summary_(\d{4}_\d{2}_\d{2})\.json",
    )
    if not found:
        return None
    path, iso = found
    return _load_json(path), iso


def _mlb_name_context(iso_date: str) -> dict[int, dict[str, Any]]:
    """game_pk -> {away/home full names + abbrs, pitcher id->name map} from hr_targets."""
    path = os.path.join(
        _mlb_data_root(), "daily", f"daily_summary_{iso_date.replace('-', '_')}_hr_targets.json"
    )
    context: dict[int, dict[str, Any]] = {}
    if not os.path.exists(path):
        return context
    try:
        payload = _load_json(path)
    except Exception:
        return context
    for game in payload.get("games") or []:
        if not isinstance(game, dict):
            continue
        pitchers: dict[int, str] = {}
        for target in game.get("targets") or []:
            if isinstance(target, dict):
                pid = target.get("opponent_pitcher_id")
                pname = target.get("opponent_pitcher_name")
                if isinstance(pid, int) and pname:
                    pitchers[pid] = str(pname)
        try:
            game_pk = int(game.get("game_pk"))
        except (TypeError, ValueError):
            continue
        context[game_pk] = {
            "away_name": str(game.get("away") or ""),
            "home_name": str(game.get("home") or ""),
            "away_abbr": str(game.get("away_abbr") or ""),
            "home_abbr": str(game.get("home_abbr") or ""),
            "pitchers": pitchers,
        }
    return context


def _mlb_game_matches(question: str, words: set[str], game: dict[str, Any], names: dict[str, Any]) -> bool:
    for team_text in (
        names.get("away_name"), names.get("home_name"),
        game.get("away"), game.get("home"),
    ):
        if team_text and _name_matches(str(team_text), words):
            return True
    # Tricodes are matched against the raw question to respect case (NYY, PIT).
    for tri in (str(game.get("away") or ""), str(game.get("home") or "")):
        if len(tri) >= 2 and re.search(rf"\b{re.escape(tri)}\b", question):
            return True
    starters = game.get("starter_names") or {}
    for starter in (starters.get("away"), starters.get("home")):
        if starter and _name_matches(str(starter), words):
            return True
    return False


def _mlb_match_game(question: str, context: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], str] | None:
    """The slate game (plus its name-context) the question is about, shared
    by every MLB evidence fetcher that needs "which game/pitcher/team" --
    same matching `_mlb_focused_evidence` always used, factored out so
    `_mlb_player_history_evidence` doesn't have to re-derive it.
    """
    loaded = _mlb_daily_summary(str(context.get("selected_date") or "") or None)
    if not loaded:
        return None
    summary, iso_date = loaded
    outputs = summary.get("outputs") or []
    if not isinstance(outputs, list) or not outputs:
        return None
    name_context = _mlb_name_context(iso_date)
    words = _question_words(question)

    for game in outputs:
        if not isinstance(game, dict):
            continue
        try:
            game_pk = int(game.get("game_pk"))
        except (TypeError, ValueError):
            game_pk = -1
        names = name_context.get(game_pk, {})
        if _mlb_game_matches(question, words, game, names):
            return game, names, iso_date
    return None


def _mlb_focused_evidence(question: str, context: dict[str, Any]) -> dict[str, Any] | None:
    found = _mlb_match_game(question, context)
    if found is None:
        return None
    matched, matched_names, iso_date = found
    words = _question_words(question)

    full = matched.get("full") or {}
    away_label = matched_names.get("away_name") or str(matched.get("away") or "Away")
    home_label = matched_names.get("home_name") or str(matched.get("home") or "Home")
    matchup = f"{away_label} @ {home_label}"
    total_stats = _dist_stats(full.get("total_runs_dist") or {})
    margin_stats = _dist_stats(full.get("run_margin_dist") or {})

    tables: list[dict[str, Any]] = [
        {
            "title": f"SmartSim game outlook — {matchup} ({iso_date})",
            "columns": ["Metric", away_label, home_label],
            "rows": [
                ["Win probability", f"{100.0 * (_to_float(full.get('away_win_prob')) or 0):.1f}%", f"{100.0 * (_to_float(full.get('home_win_prob')) or 0):.1f}%"],
                ["Mean runs", f"{_to_float(full.get('away_runs_mean')) or 0:.2f}", f"{_to_float(full.get('home_runs_mean')) or 0:.2f}"],
            ],
        }
    ]
    charts: list[dict[str, Any]] = []
    total_chart = _dist_chart(
        full.get("total_runs_dist") or {},
        title=f"Simulated total runs — {matchup} ({iso_date})",
        x_label="Total runs",
    )
    if total_chart:
        charts.append(total_chart)

    evidence: dict[str, Any] = {
        "source": "mlb_daily_sim",
        "as_of": iso_date,
        "matchup": matchup,
        "win_probability": {
            "away": _to_float(full.get("away_win_prob")),
            "home": _to_float(full.get("home_win_prob")),
        },
        "mean_runs": {
            "away": _to_float(full.get("away_runs_mean")),
            "home": _to_float(full.get("home_runs_mean")),
        },
        "total_runs": total_stats,
        "run_margin_home_minus_away": margin_stats,
    }

    # Starter strikeout evidence: attach when a starter is named or the
    # question reads like a strikeout/pitcher-prop question.
    starters = matched.get("starter_names") or {}
    pitcher_names = matched_names.get("pitchers") or {}
    pitcher_props = matched.get("pitcher_props") or {}
    wants_pitching = bool(
        words & {"strikeout", "strikeouts", "k", "ks", "pitcher", "outs", "pitches", "innings"}
    ) or any(_name_matches(str(s), words) for s in starters.values() if s)
    if wants_pitching and isinstance(pitcher_props, dict):
        pitcher_rows: list[list[Any]] = []
        pitcher_evidence: list[dict[str, Any]] = []
        side_order = list(pitcher_props.items())
        fallback_labels = [
            f"{starters.get('away') or 'Away starter'}",
            f"{starters.get('home') or 'Home starter'}",
        ]
        for index, (pid, props) in enumerate(side_order[:2]):
            if not isinstance(props, dict):
                continue
            try:
                label = pitcher_names.get(int(pid)) or fallback_labels[min(index, 1)]
            except (TypeError, ValueError):
                label = fallback_labels[min(index, 1)]
            so_stats = _dist_stats(props.get("so_dist") or {})
            pitcher_rows.append([
                label,
                f"{_to_float(props.get('so_mean')) or 0:.2f}",
                f"{(_to_float(props.get('outs_mean')) or 0) / 3.0:.1f}",
                f"{_to_float(props.get('pitches_mean')) or 0:.0f}",
                f"{_to_float(props.get('walks_mean')) or 0:.2f}",
                f"{_to_float(props.get('er_mean')) or 0:.2f}",
            ])
            pitcher_evidence.append({
                "pitcher": label,
                "so": so_stats,
                "so_mean": _to_float(props.get("so_mean")),
                "innings_mean": round((_to_float(props.get("outs_mean")) or 0) / 3.0, 2),
                "pitches_mean": _to_float(props.get("pitches_mean")),
            })
            named = _name_matches(str(label), words)
            if named or len(side_order) == 1:
                so_chart = _dist_chart(
                    props.get("so_dist") or {},
                    title=f"Simulated strikeouts — {label} ({iso_date})",
                    x_label="Strikeouts",
                )
                if so_chart:
                    charts.append(so_chart)
        if pitcher_rows:
            tables.append({
                "title": f"Starter sim projections — {matchup} ({iso_date})",
                "columns": ["Starter", "K (mean)", "IP (mean)", "Pitches (mean)", "BB (mean)", "ER (mean)"],
                "rows": pitcher_rows,
            })
            evidence["starters"] = pitcher_evidence

    return {"evidence": evidence, "tables": tables, "charts": charts, "as_of": iso_date, "sport": "mlb"}


# ---------------------------------------------------------------------------
# WNBA
# ---------------------------------------------------------------------------


def _wnba_processed_dirs() -> list[str]:
    dirs: list[str] = []
    env_root = os.environ.get("WNBA_BETTING_DATA_ROOT")
    if env_root:
        dirs.append(os.path.join(env_root, "processed"))
    root = _syndicate_data_root()
    dirs.append(os.path.join(root, "wnba_source", "source_artifacts", "data", "processed"))
    dirs.append(os.path.join(root, "wnba_source", "data", "processed"))
    return dirs


def _wnba_latest(pattern_name: str, selected_date: str | None) -> tuple[Any, str] | None:
    best: tuple[str, str] | None = None
    for directory in _wnba_processed_dirs():
        if selected_date:
            path = os.path.join(directory, f"{pattern_name}_{selected_date}.json")
            if os.path.exists(path):
                return _load_json(path), selected_date
        found = _latest_dated_file(
            os.path.join(directory, f"{pattern_name}_????-??-??.json"),
            rf"{pattern_name}_(\d{{4}}-\d{{2}}-\d{{2}})\.json",
        )
        if found and (best is None or found[1] > best[1]):
            best = found
    if not best:
        return None
    path, iso = best
    return _load_json(path), iso


def _wnba_team_label(tri: str) -> str:
    return _WNBA_TEAM_NAMES.get(str(tri or "").upper(), str(tri or ""))


def _wnba_player_lines(props_payload: Any, player_name: str) -> list[dict[str, Any]]:
    lines: list[dict[str, Any]] = []
    if not isinstance(props_payload, dict):
        return lines
    target = str(player_name or "").lower()
    for game in props_payload.get("games") or []:
        if not isinstance(game, dict):
            continue
        recommendations = game.get("prop_recommendations") or {}
        for side in ("home", "away"):
            for entry in recommendations.get(side) or []:
                if not isinstance(entry, dict):
                    continue
                if str(entry.get("player") or "").lower() == target:
                    lines.append({
                        "market": entry.get("market"),
                        "side": entry.get("side"),
                        "line": entry.get("line"),
                        "price": entry.get("price"),
                        "book": entry.get("book"),
                        "edge": entry.get("edge"),
                        "ev_pct": entry.get("ev_pct"),
                        "tier": entry.get("tier"),
                        "summary": entry.get("basketball_summary"),
                    })
    return lines


def _wnba_focused_evidence(question: str, context: dict[str, Any]) -> dict[str, Any] | None:
    selected_date = str(context.get("selected_date") or "") or None
    loaded = _wnba_latest("cards_sim_detail", selected_date)
    if not loaded:
        return None
    detail, iso_date = loaded
    games = detail.get("games") if isinstance(detail, dict) else None
    if not isinstance(games, list) or not games:
        return None
    words = _question_words(question)

    # Player question takes priority over team question.
    matched_player: dict[str, Any] | None = None
    matched_game: dict[str, Any] | None = None
    for game in games:
        if not isinstance(game, dict):
            continue
        sim = game.get("sim") or {}
        players = sim.get("players") or {}
        for side in ("home", "away"):
            for player in players.get(side) or []:
                if isinstance(player, dict) and _name_matches(str(player.get("player_name") or ""), words):
                    matched_player = player
                    matched_game = game
                    break
            if matched_player:
                break
        if matched_player:
            break

    if matched_player is not None and matched_game is not None:
        name = str(matched_player.get("player_name") or "Player")
        team = _wnba_team_label(str(matched_player.get("team") or ""))
        opponent = _wnba_team_label(str(matched_player.get("opponent") or ""))
        stats = [
            ("PTS", "pts_mean", "pts_sd"),
            ("REB", "reb_mean", "reb_sd"),
            ("AST", "ast_mean", "ast_sd"),
            ("3PM", "threes_mean", "threes_sd"),
            ("PRA", "pra_mean", "pra_sd"),
        ]
        rows: list[list[Any]] = []
        chart_points: list[dict[str, Any]] = []
        evidence_stats: dict[str, Any] = {}
        for label, mean_key, sd_key in stats:
            mean = _to_float(matched_player.get(mean_key))
            sd = _to_float(matched_player.get(sd_key))
            if mean is None:
                continue
            rows.append([label, f"{mean:.1f}", f"±{sd:.1f}" if sd is not None else "—"])
            chart_points.append({"x": label, "y": round(mean, 2)})
            evidence_stats[label.lower()] = {"mean": round(mean, 2), "sd": round(sd, 2) if sd is not None else None}
        minutes = _to_float(matched_player.get("minutes"))
        if minutes is not None:
            rows.append(["Minutes", f"{minutes:.1f}", "—"])

        tables = [{
            "title": f"SmartSim projection — {name} ({team} vs {opponent}, {iso_date})",
            "columns": ["Stat", "Sim mean", "Sim SD"],
            "rows": rows,
        }]
        charts = [{
            "type": "bar",
            "title": f"Projected stat line — {name} ({iso_date})",
            "x_label": "Stat",
            "y_label": "Sim mean",
            "points": chart_points,
        }]

        props_loaded = _wnba_latest("cards_props_snapshot", iso_date)
        market_lines = _wnba_player_lines(props_loaded[0], name) if props_loaded else []
        if market_lines:
            tables.append({
                "title": f"Market lines & model edges — {name} ({iso_date})",
                "columns": ["Market", "Side", "Line", "Price", "Book", "EV %", "Tier"],
                "rows": [
                    [
                        str(line.get("market") or ""),
                        str(line.get("side") or ""),
                        line.get("line"),
                        line.get("price"),
                        str(line.get("book") or ""),
                        f"{_to_float(line.get('ev_pct')) or 0:.1f}",
                        str(line.get("tier") or ""),
                    ]
                    for line in market_lines[:8]
                ],
            })

        evidence = {
            "source": "wnba_sim_detail",
            "as_of": iso_date,
            "player": name,
            "team": team,
            "opponent": opponent,
            "minutes_mean": minutes,
            "projections": evidence_stats,
            "market_lines": market_lines[:8],
        }
        return {"evidence": evidence, "tables": tables, "charts": charts, "as_of": iso_date, "sport": "wnba"}

    # Team/game question: top projected scorers for the matched game.
    for game in games:
        if not isinstance(game, dict):
            continue
        home_tri = str(game.get("home_tri") or "")
        away_tri = str(game.get("away_tri") or "")
        team_texts = [home_tri, away_tri, _wnba_team_label(home_tri), _wnba_team_label(away_tri)]
        tri_hit = any(
            len(tri) >= 2 and re.search(rf"\b{re.escape(tri)}\b", question)
            for tri in (home_tri, away_tri)
        )
        if not (tri_hit or any(_name_matches(text, words) for text in team_texts[2:])):
            continue
        sim = game.get("sim") or {}
        players = sim.get("players") or {}
        all_players = [
            p for side in ("away", "home") for p in (players.get(side) or []) if isinstance(p, dict)
        ]
        all_players.sort(key=lambda p: _to_float(p.get("pts_mean")) or 0.0, reverse=True)
        top = all_players[:8]
        if not top:
            return None
        matchup = f"{_wnba_team_label(away_tri)} @ {_wnba_team_label(home_tri)}"
        rows = [
            [
                str(p.get("player_name") or ""),
                str(p.get("team") or ""),
                f"{_to_float(p.get('pts_mean')) or 0:.1f}",
                f"{_to_float(p.get('reb_mean')) or 0:.1f}",
                f"{_to_float(p.get('ast_mean')) or 0:.1f}",
                f"{_to_float(p.get('pra_mean')) or 0:.1f}",
                f"{_to_float(p.get('minutes')) or 0:.0f}",
            ]
            for p in top
        ]
        tables = [{
            "title": f"SmartSim top projections — {matchup} ({iso_date})",
            "columns": ["Player", "Team", "PTS", "REB", "AST", "PRA", "MIN"],
            "rows": rows,
        }]
        charts = [{
            "type": "bar",
            "title": f"Projected points leaders — {matchup} ({iso_date})",
            "x_label": "Player",
            "y_label": "Projected PTS",
            "points": [
                {"x": str(p.get("player_name") or ""), "y": round(_to_float(p.get("pts_mean")) or 0.0, 1)}
                for p in top
            ],
        }]
        evidence = {
            "source": "wnba_sim_detail",
            "as_of": iso_date,
            "matchup": matchup,
            "top_projections": [
                {
                    "player": str(p.get("player_name") or ""),
                    "team": str(p.get("team") or ""),
                    "pts_mean": round(_to_float(p.get("pts_mean")) or 0.0, 1),
                    "pra_mean": round(_to_float(p.get("pra_mean")) or 0.0, 1),
                }
                for p in top
            ],
        }
        return {"evidence": evidence, "tables": tables, "charts": charts, "as_of": iso_date, "sport": "wnba"}

    return None


# ---------------------------------------------------------------------------
# Last-N game logs (WNBA / NBA / NHL)
# ---------------------------------------------------------------------------


def _nba_processed_dirs() -> list[str]:
    dirs: list[str] = []
    env_root = os.environ.get("NBA_BETTING_DATA_ROOT")
    if env_root:
        dirs.append(os.path.join(env_root, "processed"))
    root = _syndicate_data_root()
    dirs.append(os.path.join(root, "nba_source", "source_artifacts", "data", "processed"))
    dirs.append(os.path.join(root, "nba_source", "data", "processed"))
    return dirs


def _parse_minutes(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    if ":" in text:
        try:
            mins, secs = text.split(":", 1)
            return round(float(mins) + float(secs) / 60.0, 1)
        except ValueError:
            return None
    return _to_float(text)


def _boxscore_row_stats(row: dict[str, str]) -> dict[str, Any] | None:
    """Normalize a boxscore row across the two column dialects (nba_api / espn)."""

    def pick(*keys: str) -> str:
        for key in keys:
            value = str(row.get(key) or "").strip()
            if value:
                return value
        return ""

    name = pick("PLAYER_NAME") or " ".join(
        part for part in (pick("firstName"), pick("familyName")) if part
    ).strip()
    date = pick("date")
    if not name or not date:
        return None
    pts = _to_float(pick("PTS", "points"))
    reb = _to_float(pick("REB", "reboundsTotal"))
    ast = _to_float(pick("AST", "assists"))
    threes = _to_float(pick("FG3M", "threePointersMade"))
    minutes = _parse_minutes(pick("MIN", "minutes"))
    if pts is None and reb is None and ast is None:
        return None
    return {
        "name": name,
        "date": date,
        "team": pick("TEAM_ABBREVIATION", "teamTricode"),
        "min": minutes,
        "pts": pts or 0.0,
        "reb": reb or 0.0,
        "ast": ast or 0.0,
        "threes": threes or 0.0,
        "pra": (pts or 0.0) + (reb or 0.0) + (ast or 0.0),
    }


def _boxscore_last_n(directories: list[str], words: set[str], n: int) -> list[dict[str, Any]]:
    """Stream boxscore history and return the matched player's last n games."""
    path = next(
        (os.path.join(d, "boxscores_history.csv") for d in directories
         if os.path.exists(os.path.join(d, "boxscores_history.csv"))),
        None,
    )
    if not path:
        return []
    by_player: dict[str, list[dict[str, Any]]] = {}
    scores: dict[str, int] = {}
    with open(path, encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            name = str(row.get("PLAYER_NAME") or "").strip() or " ".join(
                part for part in (str(row.get("firstName") or "").strip(), str(row.get("familyName") or "").strip()) if part
            )
            if not name:
                continue
            if name not in scores:
                scores[name] = _person_matches(name, words)
            if scores[name] <= 0:
                continue
            stats = _boxscore_row_stats(row)
            if stats:
                by_player.setdefault(name, []).append(stats)
    if not by_player:
        return []
    # Prefer first+last matches over last-name-only; break ties on recency.
    best = max(
        by_player,
        key=lambda name: (scores[name], max(g["date"] for g in by_player[name])),
    )
    games = sorted(by_player[best], key=lambda g: g["date"], reverse=True)
    return games[:n]


def _last10_hit_rates(games: list[dict[str, Any]], lines: list[float]) -> list[dict[str, Any]]:
    rates: list[dict[str, Any]] = []
    for line in lines[:2]:
        entry: dict[str, Any] = {"line": line, "over_counts": {}}
        for stat in ("pts", "reb", "ast", "threes", "pra"):
            entry["over_counts"][stat] = sum(1 for g in games if (g.get(stat) or 0) > line)
        entry["games"] = len(games)
        rates.append(entry)
    return rates


def _basketball_last10_evidence(question: str, context: dict[str, Any], sport: str) -> dict[str, Any] | None:
    words = _question_words(question)
    directories = _wnba_processed_dirs() if sport == "wnba" else _nba_processed_dirs()
    games = _boxscore_last_n(directories, words, LAST_N_GAMES)
    if not games:
        return None
    name = games[0]["name"]
    as_of = games[0]["date"]
    rows = [
        [g["date"], g["team"], f"{g['min']:.0f}" if g.get("min") is not None else "—",
         f"{g['pts']:.0f}", f"{g['reb']:.0f}", f"{g['ast']:.0f}", f"{g['threes']:.0f}", f"{g['pra']:.0f}"]
        for g in games
    ]
    count = len(games)
    averages = {
        stat: round(sum(g[stat] for g in games) / count, 1)
        for stat in ("pts", "reb", "ast", "threes", "pra")
    }
    rows.append([
        f"L{count} avg", "", "",
        f"{averages['pts']:.1f}", f"{averages['reb']:.1f}", f"{averages['ast']:.1f}",
        f"{averages['threes']:.1f}", f"{averages['pra']:.1f}",
    ])
    tables = [{
        "title": f"Last {count} games — {name} (through {as_of})",
        "columns": ["Date", "Team", "MIN", "PTS", "REB", "AST", "3PM", "PRA"],
        "rows": rows,
    }]
    chronological = list(reversed(games))
    charts = [{
        "type": "bar",
        "title": f"Points by game — {name} (last {count})",
        "x_label": "Game date",
        "y_label": "PTS",
        "points": [{"x": g["date"][5:], "y": g["pts"]} for g in chronological],
    }]
    evidence: dict[str, Any] = {
        "source": f"{sport}_boxscore_history",
        "as_of": as_of,
        "player": name,
        "last_games": [
            {k: g[k] for k in ("date", "team", "min", "pts", "reb", "ast", "threes", "pra")}
            for g in games
        ],
        "averages": averages,
    }
    hit_rates = _last10_hit_rates(games, _question_lines(question))
    if hit_rates:
        evidence["hit_rates_vs_question_lines"] = hit_rates
    return {"evidence": evidence, "tables": tables, "charts": charts, "as_of": as_of, "sport": sport}


def _nhl_data_dir() -> str:
    env_root = os.environ.get("NHL_DATA_DIR")
    if env_root:
        return env_root
    return os.path.join(_syndicate_data_root(), "nhl_source", "source_artifacts", "data")


def _nhl_player_name(raw: str) -> str:
    """NHL rows store names as serialized dicts like {'default': \"N. MacKinnon\"}."""
    text = str(raw or "").strip()
    match = re.search(r"""['"]default['"]\s*:\s*['"](.+?)['"]\s*}""", text)
    return match.group(1) if match else text


def _nhl_last10_evidence(question: str, context: dict[str, Any]) -> dict[str, Any] | None:
    path = os.path.join(_nhl_data_dir(), "raw", "player_game_stats.csv")
    if not os.path.exists(path):
        return None
    words = _question_words(question)
    by_player: dict[str, list[dict[str, Any]]] = {}
    scores: dict[str, int] = {}
    with open(path, encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            name = _nhl_player_name(row.get("player"))
            if not name:
                continue
            if name not in scores:
                scores[name] = _person_matches(name, words)
            if scores[name] <= 0:
                continue
            date = str(row.get("date") or "").strip()[:10]
            if not date:
                continue
            by_player.setdefault(name, []).append({
                "name": name,
                "date": date,
                "team": str(row.get("team") or ""),
                "role": str(row.get("role") or ""),
                "shots": _to_float(row.get("shots")) or 0.0,
                "goals": _to_float(row.get("goals")) or 0.0,
                "assists": _to_float(row.get("assists")) or 0.0,
                "blocked": _to_float(row.get("blocked")) or 0.0,
                "toi": str(row.get("timeOnIce") or ""),
                "saves": _to_float(row.get("saves")),
                "shots_against": _to_float(row.get("shotsAgainst")),
                "decision": str(row.get("decision") or ""),
            })
    if not by_player:
        return None
    best = max(by_player, key=lambda n: (scores[n], max(g["date"] for g in by_player[n])))
    games = sorted(by_player[best], key=lambda g: g["date"], reverse=True)[:LAST_N_GAMES]
    as_of = games[0]["date"]
    count = len(games)
    is_goalie = any(g.get("saves") not in (None, 0.0) for g in games)
    if is_goalie:
        tables = [{
            "title": f"Last {count} games — {best} (through {as_of})",
            "columns": ["Date", "Team", "Saves", "Shots Against", "Decision"],
            "rows": [
                [g["date"], g["team"], f"{g['saves'] or 0:.0f}", f"{g['shots_against'] or 0:.0f}", g["decision"] or "—"]
                for g in games
            ],
        }]
        chart_stat, chart_label = "saves", "Saves"
    else:
        tables = [{
            "title": f"Last {count} games — {best} (through {as_of})",
            "columns": ["Date", "Team", "Shots", "Goals", "Assists", "Blocked", "TOI"],
            "rows": [
                [g["date"], g["team"], f"{g['shots']:.0f}", f"{g['goals']:.0f}", f"{g['assists']:.0f}", f"{g['blocked']:.0f}", g["toi"] or "—"]
                for g in games
            ],
        }]
        chart_stat, chart_label = "shots", "Shots"
    chronological = list(reversed(games))
    charts = [{
        "type": "bar",
        "title": f"{chart_label} by game — {best} (last {count})",
        "x_label": "Game date",
        "y_label": chart_label,
        "points": [{"x": g["date"][5:], "y": g.get(chart_stat) or 0.0} for g in chronological],
    }]
    evidence = {
        "source": "nhl_player_game_stats",
        "as_of": as_of,
        "player": best,
        "role": "goalie" if is_goalie else "skater",
        "last_games": games,
    }
    return {"evidence": evidence, "tables": tables, "charts": charts, "as_of": as_of, "sport": "nhl"}


# ---------------------------------------------------------------------------
# MLB batter-vs-pitcher
# ---------------------------------------------------------------------------

_BVP_CACHE_LOCK = threading.Lock()
_BVP_CACHE: dict[int, dict[int, dict[str, int]]] = {}
_BVP_CACHE_MAX_PITCHERS = 8

_BVP_COUNT_FIELDS = ("pa", "hits", "hr", "so", "bb", "hbp", "inplay_pa", "inplay_hits")


def _bvp_counts_for_pitcher(pitcher_id: int) -> dict[int, dict[str, int]]:
    """Aggregate career BvP counts for one pitcher from the daily index files.

    The 47 index files total ~70MB, so results are cached per pitcher and the
    cache is kept small; a cold lookup is a few seconds, warm ones are free.
    """
    with _BVP_CACHE_LOCK:
        if pitcher_id in _BVP_CACHE:
            return _BVP_CACHE[pitcher_id]

    directory = os.path.join(_mlb_data_root(), "cache", "statcast", "bvp", "statcast_bvp_file_daily")
    pitcher_key = str(pitcher_id)
    # date -> batter_id -> counts; overlapping index files repeat dates, so
    # keep one payload per date before summing.
    per_date: dict[str, dict[str, dict[str, Any]]] = {}
    for path in glob.glob(os.path.join(directory, "*.json")):
        try:
            payload = _load_json(path)
        except Exception:
            continue
        by_date = payload.get("by_date") if isinstance(payload, dict) else None
        if not isinstance(by_date, dict):
            continue
        for day, pitcher_map in by_date.items():
            if not isinstance(pitcher_map, dict):
                continue
            batters = pitcher_map.get(pitcher_key)
            if isinstance(batters, dict) and day not in per_date:
                per_date[day] = batters

    totals: dict[int, dict[str, int]] = {}
    for batters in per_date.values():
        for batter_key, counts in batters.items():
            try:
                batter_id = int(batter_key)
            except (TypeError, ValueError):
                continue
            if not isinstance(counts, dict):
                continue
            bucket = totals.setdefault(batter_id, {field: 0 for field in _BVP_COUNT_FIELDS})
            for field in _BVP_COUNT_FIELDS:
                try:
                    bucket[field] += int(counts.get(field) or 0)
                except (TypeError, ValueError):
                    continue

    with _BVP_CACHE_LOCK:
        if len(_BVP_CACHE) >= _BVP_CACHE_MAX_PITCHERS:
            _BVP_CACHE.pop(next(iter(_BVP_CACHE)), None)
        _BVP_CACHE[pitcher_id] = totals
    return totals


def _mlb_slate_targets(selected_date: str | None) -> tuple[list[dict[str, Any]], str] | None:
    """Flattened hr_targets rows: batter name/id + today's opposing starter."""
    daily_dir = os.path.join(_mlb_data_root(), "daily")
    path_date: tuple[str, str] | None = None
    if selected_date:
        path = os.path.join(daily_dir, f"daily_summary_{selected_date.replace('-', '_')}_hr_targets.json")
        if os.path.exists(path):
            path_date = (path, selected_date)
    if path_date is None:
        path_date = _latest_dated_file(
            os.path.join(daily_dir, "daily_summary_????_??_??_hr_targets.json"),
            r"daily_summary_(\d{4}_\d{2}_\d{2})_hr_targets\.json",
        )
    if path_date is None:
        return None
    path, iso = path_date
    try:
        payload = _load_json(path)
    except Exception:
        return None
    targets: list[dict[str, Any]] = []
    for game in payload.get("games") or []:
        if isinstance(game, dict):
            for target in game.get("targets") or []:
                if isinstance(target, dict):
                    targets.append(target)
    return targets, iso


def _bvp_rate_row(label: str, counts: dict[str, int]) -> list[Any]:
    pa = counts.get("pa") or 0
    hits = counts.get("hits") or 0
    hr = counts.get("hr") or 0
    so = counts.get("so") or 0
    bb = counts.get("bb") or 0
    avg_denominator = max(pa - bb - (counts.get("hbp") or 0), 1)
    return [label, pa, hits, hr, bb, so, f"{hits / avg_denominator:.3f}" if pa else "—"]


def _mlb_bvp_evidence(question: str, context: dict[str, Any]) -> dict[str, Any] | None:
    loaded = _mlb_slate_targets(str(context.get("selected_date") or "") or None)
    if not loaded:
        return None
    targets, iso_date = loaded
    words = _question_words(question)

    # Batter question: their history vs today's opposing starter.
    batter_rows = [t for t in targets if _person_matches(str(t.get("player_name") or ""), words) > 0]
    if batter_rows:
        batter_rows.sort(key=lambda t: _person_matches(str(t.get("player_name") or ""), words), reverse=True)
        target = batter_rows[0]
        batter_name = str(target.get("player_name") or "Batter")
        pitcher_name = str(target.get("opponent_pitcher_name") or "opposing starter")
        try:
            batter_id = int(target.get("batter_id"))
            pitcher_id = int(target.get("opponent_pitcher_id"))
        except (TypeError, ValueError):
            return None
        counts = _bvp_counts_for_pitcher(pitcher_id).get(batter_id)
        title = f"BvP — {batter_name} vs {pitcher_name} (career, through {iso_date})"
        if counts and (counts.get("pa") or 0) > 0:
            tables = [{
                "title": title,
                "columns": ["Matchup", "PA", "H", "HR", "BB", "SO", "AVG"],
                "rows": [_bvp_rate_row(f"{batter_name} vs {pitcher_name}", counts)],
            }]
        else:
            tables = [{
                "title": title,
                "columns": ["Matchup", "PA", "H", "HR", "BB", "SO", "AVG"],
                "rows": [[f"{batter_name} vs {pitcher_name}", 0, 0, 0, 0, 0, "no history"]],
            }]
        profile_rows = []
        for label, key, fmt in (
            ("K rate", "batter_k_rate", "{:.1%}"),
            ("BB rate", "batter_bb_rate", "{:.1%}"),
            ("HR rate", "batter_hr_rate", "{:.1%}"),
            ("In-play hit rate", "batter_inplay_hit_rate", "{:.1%}"),
            ("Sim P(HR 1+)", "p_hr_1plus", "{:.1%}"),
            ("Park HR mult", "park_hr_mult", "{:.2f}"),
            ("Weather HR mult", "weather_hr_mult", "{:.2f}"),
        ):
            value = _to_float(target.get(key))
            if value is not None:
                profile_rows.append([label, fmt.format(value)])
        if profile_rows:
            tables.append({
                "title": f"Matchup profile — {batter_name} ({iso_date})",
                "columns": ["Factor", "Value"],
                "rows": profile_rows,
            })
        evidence = {
            "source": "mlb_bvp",
            "as_of": iso_date,
            "batter": batter_name,
            "pitcher": pitcher_name,
            "career_bvp": counts or {"pa": 0},
            "matchup_profile": {
                key: _to_float(target.get(key))
                for key in ("batter_k_rate", "batter_hr_rate", "batter_inplay_hit_rate", "p_hr_1plus", "park_hr_mult", "weather_hr_mult")
                if _to_float(target.get(key)) is not None
            },
        }
        return {"evidence": evidence, "tables": tables, "charts": [], "as_of": iso_date, "sport": "mlb"}

    # Pitcher question: his history vs today's opposing lineup.
    pitcher_rows = [t for t in targets if _person_matches(str(t.get("opponent_pitcher_name") or ""), words) > 0]
    if not pitcher_rows:
        return None
    pitcher_name = str(pitcher_rows[0].get("opponent_pitcher_name") or "Pitcher")
    try:
        pitcher_id = int(pitcher_rows[0].get("opponent_pitcher_id"))
    except (TypeError, ValueError):
        return None
    counts_by_batter = _bvp_counts_for_pitcher(pitcher_id)
    lineup: list[tuple[str, dict[str, int]]] = []
    seen: set[int] = set()
    for target in pitcher_rows:
        try:
            batter_id = int(target.get("batter_id"))
        except (TypeError, ValueError):
            continue
        if batter_id in seen:
            continue
        seen.add(batter_id)
        counts = counts_by_batter.get(batter_id)
        if counts and (counts.get("pa") or 0) > 0:
            lineup.append((str(target.get("player_name") or batter_id), counts))
    lineup.sort(key=lambda item: item[1].get("pa") or 0, reverse=True)

    if lineup:
        tables = [{
            "title": f"BvP — today's lineup vs {pitcher_name} (career, through {iso_date})",
            "columns": ["Batter", "PA", "H", "HR", "BB", "SO", "AVG"],
            "rows": [_bvp_rate_row(name, counts) for name, counts in lineup[:10]],
        }]
    else:
        # Sparse/no career history (common for young pitchers) isn't the
        # same as "nothing to show" -- say so instead of silently vanishing.
        tables = [{
            "title": f"BvP — today's lineup vs {pitcher_name} (career, through {iso_date})",
            "columns": ["Note"],
            "rows": [[f"No recorded plate appearances vs today's lineup yet — {pitcher_name}'s career BvP sample here is limited."]],
        }]

    # Park/weather multipliers are game-level, not batter-specific, so any
    # matched target row carries them -- same fields the batter-direction
    # branch above already surfaces via profile_rows.
    park_weather_rows: list[list[Any]] = []
    for label, key, fmt in (
        ("Park HR mult", "park_hr_mult", "{:.2f}"),
        ("Weather HR mult", "weather_hr_mult", "{:.2f}"),
    ):
        value = _to_float(pitcher_rows[0].get(key))
        if value is not None:
            park_weather_rows.append([label, fmt.format(value)])
    if park_weather_rows:
        tables.append({
            "title": f"Park/weather — {pitcher_name} ({iso_date})",
            "columns": ["Factor", "Value"],
            "rows": park_weather_rows,
        })

    evidence = {
        "source": "mlb_bvp",
        "as_of": iso_date,
        "pitcher": pitcher_name,
        "lineup_bvp": [
            {"batter": name, **counts} for name, counts in lineup[:10]
        ],
        "lineup_bvp_pa_total": sum(counts.get("pa") or 0 for _, counts in lineup),
    }
    return {"evidence": evidence, "tables": tables, "charts": [], "as_of": iso_date, "sport": "mlb"}


# ---------------------------------------------------------------------------
# MLB recent-form game log + advanced Statcast profile
# ---------------------------------------------------------------------------


def _mlb_processed_dir() -> str:
    return os.path.join(_mlb_data_root(), "processed")


def _mlb_match_player_in_log(filename: str, words: set[str]) -> tuple[str, int, list[dict[str, Any]]] | None:
    """Best name match in a pitcher/batter game-log CSV -> (label, player_id,
    that player's rows sorted most-recent-first). Same "score by name, break
    ties on recency" shape as `_boxscore_last_n`, just against a per-player
    CSV instead of a name column mixed in with every other stat.
    """
    path = os.path.join(_mlb_processed_dir(), filename)
    if not os.path.exists(path):
        return None
    by_player: dict[int, list[dict[str, Any]]] = {}
    names: dict[int, str] = {}
    try:
        with open(path, newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                try:
                    player_id = int(row.get("player_id") or 0)
                except (TypeError, ValueError):
                    continue
                if player_id <= 0:
                    continue
                by_player.setdefault(player_id, []).append(row)
                names[player_id] = str(row.get("player_name") or names.get(player_id) or "")
    except Exception:
        return None
    if not by_player:
        return None

    best_id: int | None = None
    best_score = 0
    best_date = ""
    for player_id, rows in by_player.items():
        score = _person_matches(names.get(player_id, ""), words)
        if score == 0:
            continue
        latest_date = max((str(r.get("date") or "") for r in rows), default="")
        if score > best_score or (score == best_score and latest_date > best_date):
            best_id, best_score, best_date = player_id, score, latest_date
    if best_id is None:
        return None
    rows = sorted(by_player[best_id], key=lambda r: str(r.get("date") or ""), reverse=True)
    return names.get(best_id) or "Player", best_id, rows


def _mlb_advanced_profile_table(label: str, player_id: int, role: str) -> dict[str, Any] | None:
    from syndicate.features.intelligence import _mlb_statcast_profile_from_ids

    if role == "pitcher":
        profile = _mlb_statcast_profile_from_ids(batter_id=None, pitcher_id=player_id)
        factors = (profile or {}).get("pitcher") if profile else None
        field_specs = [
            ("EV allowed", "ev_mean_allowed", "{:.1f} mph"),
            ("Barrel% allowed", "barrel_rate_allowed", "{:.1%}"),
            ("HardHit% allowed", "hardhit_rate_allowed", "{:.1%}"),
            ("xwOBA allowed", "xwoba_allowed", "{:.3f}"),
            ("HR mult", "hr_mult", "{:.2f}"),
            ("K mult", "k_mult", "{:.2f}"),
            ("In-play mult", "inplay_mult", "{:.2f}"),
        ]
    else:
        profile = _mlb_statcast_profile_from_ids(batter_id=player_id, pitcher_id=None)
        factors = (profile or {}).get("batter") if profile else None
        field_specs = [
            ("Exit velocity", "ev_mean", "{:.1f} mph"),
            ("Barrel%", "barrel_rate", "{:.1%}"),
            ("HardHit%", "hardhit_rate", "{:.1%}"),
            ("xwOBA", "xwoba", "{:.3f}"),
            ("Pulled-air rate", "pulled_air_rate", "{:.1%}"),
            ("HR mult", "hr_mult", "{:.2f}"),
            ("K mult", "k_mult", "{:.2f}"),
        ]
    if not factors:
        return None

    rows: list[list[Any]] = []
    for row_label, key, fmt in field_specs:
        value = factors.get(key)
        if value is not None:
            rows.append([row_label, fmt.format(value)])
    if role == "pitcher":
        top_mix = factors.get("top_pitch_mix") or []
        mix_text = ", ".join(
            f"{item.get('pitch_type')} {float(item.get('share') or 0):.0%}"
            for item in top_mix if isinstance(item, dict) and item.get("pitch_type")
        )
        if mix_text:
            rows.append(["Top pitch mix", mix_text])
    if not rows:
        return None

    generated_at = str((profile or {}).get("generated_at") or "")
    season_note = f" (Statcast sample as of {generated_at[:10]})" if generated_at else ""
    return {
        "title": f"Advanced Statcast profile — {label}{season_note}",
        "columns": ["Factor", "Value"],
        "rows": rows,
    }


def _mlb_player_history_evidence(question: str, context: dict[str, Any]) -> dict[str, Any] | None:
    from syndicate.features.mlb.player_game_log import BATTER_LOG_FILENAME
    from syndicate.features.mlb.player_game_log import PITCHER_LOG_FILENAME

    words = _question_words(question)

    pitcher_match = _mlb_match_player_in_log(PITCHER_LOG_FILENAME, words)
    role = "pitcher" if pitcher_match else None
    match = pitcher_match
    if match is None:
        match = _mlb_match_player_in_log(BATTER_LOG_FILENAME, words)
        role = "batter" if match else None
    if match is None:
        return None
    label, player_id, all_rows = match

    tables: list[dict[str, Any]] = []
    charts: list[dict[str, Any]] = []
    evidence: dict[str, Any] = {"source": "mlb_player_game_log", "player": label, "role": role}

    if role == "pitcher":
        starts = [r for r in all_rows if str(r.get("is_starter") or "0") == "1"]
        if not starts:
            return None
        last_n = starts[:LAST_N_GAMES]
        as_of = last_n[0].get("date") or ""
        rows = [
            [r.get("date"), r.get("opponent"), r.get("ip"), r.get("k"), r.get("bb"), r.get("er"), r.get("pitches")]
            for r in last_n
        ]
        count = len(last_n)
        avg = lambda key: sum(float(r.get(key) or 0) for r in last_n) / count  # noqa: E731
        rows.append([f"L{count} avg", "", f"{avg('outs') / 3.0:.1f}", f"{avg('k'):.1f}", f"{avg('bb'):.1f}", f"{avg('er'):.1f}", f"{avg('pitches'):.0f}"])
        tables.append({
            "title": f"Last {count} starts — {label} (through {as_of})",
            "columns": ["Date", "Opponent", "IP", "K", "BB", "ER", "Pitches"],
            "rows": rows,
        })
        chronological = list(reversed(last_n))
        charts.append({
            "type": "bar",
            "title": f"Actual strikeouts — last {count} starts — {label}",
            "x_label": "Start date",
            "y_label": "K",
            "points": [{"x": str(r.get("date") or "")[5:], "y": float(r.get("k") or 0)} for r in chronological],
        })
        evidence["last_starts"] = [
            {k: r.get(k) for k in ("date", "opponent", "ip", "k", "bb", "er", "pitches")} for r in last_n
        ]

        found = _mlb_match_game(question, context)
        opponent_abbr = None
        if found is not None:
            matched, _names, _iso = found
            starters = matched.get("starter_names") or {}
            for side in ("away", "home"):
                if starters.get(side) and _name_matches(str(starters.get(side)), words):
                    opponent_abbr = str(matched.get("home" if side == "away" else "away") or "")
                    break
        if opponent_abbr:
            vs_team = [r for r in starts if str(r.get("opponent") or "") == opponent_abbr]
            evidence["vs_opponent_starts"] = len(vs_team)
            if vs_team:
                vs_rows = [
                    [r.get("date"), r.get("ip"), r.get("k"), r.get("bb"), r.get("er")]
                    for r in vs_team
                ]
                tables.append({
                    "title": f"History vs {opponent_abbr} — {label}",
                    "columns": ["Date", "IP", "K", "BB", "ER"],
                    "rows": vs_rows,
                })
    else:
        last_n = all_rows[:LAST_N_GAMES]
        as_of = last_n[0].get("date") or ""
        rows = [
            [r.get("date"), r.get("opponent"), r.get("ab"), r.get("h"), r.get("hr"), r.get("rbi"), r.get("bb"), r.get("so")]
            for r in last_n
        ]
        count = len(last_n)
        avg = lambda key: sum(float(r.get(key) or 0) for r in last_n) / count  # noqa: E731
        rows.append([f"L{count} avg", "", f"{avg('ab'):.1f}", f"{avg('h'):.1f}", f"{avg('hr'):.2f}", f"{avg('rbi'):.1f}", f"{avg('bb'):.1f}", f"{avg('so'):.1f}"])
        tables.append({
            "title": f"Last {count} games — {label} (through {as_of})",
            "columns": ["Date", "Opponent", "AB", "H", "HR", "RBI", "BB", "SO"],
            "rows": rows,
        })
        chronological = list(reversed(last_n))
        charts.append({
            "type": "bar",
            "title": f"Actual hits — last {count} games — {label}",
            "x_label": "Game date",
            "y_label": "H",
            "points": [{"x": str(r.get("date") or "")[5:], "y": float(r.get("h") or 0)} for r in chronological],
        })
        evidence["last_games"] = [
            {k: r.get(k) for k in ("date", "opponent", "ab", "h", "hr", "rbi", "bb", "so")} for r in last_n
        ]

    advanced_table = _mlb_advanced_profile_table(label, player_id, role)
    if advanced_table:
        tables.append(advanced_table)

    if not tables:
        return None
    return {"evidence": evidence, "tables": tables, "charts": charts, "as_of": as_of, "sport": "mlb"}


# ---------------------------------------------------------------------------
# MLB top-candidates leaderboards ("best HRR targets today", "top TB targets")
# ---------------------------------------------------------------------------

# Ranking-intent words are checked first and are deliberately narrow ("best"
# and "top" alone are too generic -- "what's the best bet today" already
# routes elsewhere). This whole path only activates when the question is
# unambiguously asking for a ranked list, which also means it takes
# precedence over team/player matching -- see _fetchers_for_sport, which
# routes ranking-intent questions to *only* this fetcher. That precedence is
# what fixes "best TB targets today" no longer resolving "TB" as the Tampa
# Bay Rays tricode: a market word is required too, so a bare "how do the
# Rays look, TB's pitching tonight" question is unaffected.
_RANKING_INTENT_WORDS = {"target", "targets", "candidate", "candidates", "leader", "leaders", "leaderboard"}

# Field names come straight from hitter_props_likelihood_topn's per-market
# lists in daily_summary_*.json (e.g. total_bases_1plus entries carry
# p_tb_1plus / p_tb_1plus_cal / tb_mean) -- confirmed against real data
# rather than guessed, since the stat-code prefix differs per market (tb,
# rbi, r, 2b, 3b, sb, hrr) and doesn't follow a single derivable pattern.
_MLB_MARKET_REGISTRY: tuple[dict[str, Any], ...] = (
    {"key": "hr", "words": {"hr", "hrs"}, "phrases": ("home run", "home runs", "homer", "homers", "long ball"), "source": "hr_targets", "label": "Home Run"},
    {"key": "hrr", "words": {"hrr"}, "phrases": ("hits runs rbis", "hits+runs+rbis", "h+r+rbi"), "source": "topn", "prop_key": "hits_runs_rbis_2plus", "prob_field": "p_hrr_2plus", "label": "Hits+Runs+RBIs 2+"},
    {"key": "total_bases", "words": {"tb"}, "phrases": ("total base", "total bases"), "source": "topn", "prop_key": "total_bases_1plus", "prob_field": "p_tb_1plus", "label": "Total Bases"},
    {"key": "hits", "words": {"hits"}, "phrases": (), "source": "topn", "prop_key": "hits_1plus", "prob_field": "p_h_1plus", "label": "Hits"},
    {"key": "rbi", "words": {"rbi", "rbis"}, "phrases": (), "source": "topn", "prop_key": "rbi_1plus", "prob_field": "p_rbi_1plus", "label": "RBIs"},
    {"key": "runs", "words": {"runs"}, "phrases": ("runs scored",), "source": "topn", "prop_key": "runs_1plus", "prob_field": "p_r_1plus", "label": "Runs Scored"},
    {"key": "doubles", "words": {"doubles"}, "phrases": (), "source": "topn", "prop_key": "doubles_1plus", "prob_field": "p_2b_1plus", "label": "Doubles"},
    {"key": "triples", "words": {"triples"}, "phrases": (), "source": "topn", "prop_key": "triples_1plus", "prob_field": "p_3b_1plus", "label": "Triples"},
    {"key": "sb", "words": {"sb"}, "phrases": ("stolen base", "stolen bases"), "source": "topn", "prop_key": "sb_1plus", "prob_field": "p_sb_1plus", "label": "Stolen Bases"},
)


def _is_ranking_intent_question(words: set[str]) -> bool:
    return bool(words & _RANKING_INTENT_WORDS)


def _detect_mlb_market(question: str, words: set[str]) -> dict[str, Any] | None:
    normalized = f" {str(question or '').lower()} "
    for market in _MLB_MARKET_REGISTRY:
        if words & market["words"]:
            return market
        if any(phrase in normalized for phrase in market.get("phrases", ())):
            return market
    return None


def _mlb_hr_candidates_evidence(selected_date: str | None) -> dict[str, Any] | None:
    daily_dir = os.path.join(_mlb_data_root(), "daily")
    loaded: tuple[str, str] | None = None
    if selected_date:
        path = os.path.join(daily_dir, f"daily_summary_{selected_date.replace('-', '_')}_hr_targets.json")
        if os.path.exists(path):
            loaded = (path, selected_date)
    if loaded is None:
        loaded = _latest_dated_file(
            os.path.join(daily_dir, "daily_summary_????_??_??_hr_targets.json"),
            r"daily_summary_(\d{4}_\d{2}_\d{2})_hr_targets\.json",
        )
    if loaded is None:
        return None
    path, resolved_date = loaded
    try:
        payload = _load_json(path)
    except Exception:
        return None

    candidates: list[dict[str, Any]] = []
    for game in payload.get("games") or []:
        if not isinstance(game, dict):
            continue
        for target in game.get("targets") or []:
            if not isinstance(target, dict):
                continue
            score = _to_float(target.get("hr_target_score"))
            if score is None:
                continue
            candidates.append({
                "player": str(target.get("player_name") or ""),
                "team": str(target.get("team") or ""),
                "opponent_pitcher": str(target.get("opponent_pitcher_name") or ""),
                "score": score,
                "p_hr_1plus": _to_float(target.get("p_hr_1plus")),
                "reason": _clip(target.get("primary_reason") or target.get("hr_target_summary"), 200),
            })
    if not candidates:
        return None
    candidates.sort(key=lambda item: item["score"], reverse=True)
    top = candidates[:10]
    if top[0]["score"] <= 0:
        return None  # degenerate/unpopulated market -- see the matching guard above

    rows = [
        [
            c["player"], c["team"],
            f"vs {c['opponent_pitcher']}" if c["opponent_pitcher"] else "",
            f"{(c['p_hr_1plus'] or 0.0) * 100:.1f}%",
            f"{c['score']:.1f}",
        ]
        for c in top
    ]
    tables = [{
        "title": f"Top HR candidates — {resolved_date}",
        "columns": ["Player", "Team", "Opponent Pitcher", "P(HR 1+)", "HR Target Score"],
        "rows": rows,
    }]
    charts = [{
        "type": "bar",
        "title": f"HR probability leaders — {resolved_date}",
        "x_label": "Player",
        "y_label": "P(HR 1+) %",
        "points": [{"x": c["player"], "y": round((c["p_hr_1plus"] or 0.0) * 100, 1)} for c in top],
    }]
    evidence = {"source": "mlb_hr_targets", "as_of": resolved_date, "top_candidates": top}
    return {"evidence": evidence, "tables": tables, "charts": charts, "as_of": resolved_date, "sport": "mlb"}


def _mlb_market_candidates_evidence(market: dict[str, Any], selected_date: str | None) -> dict[str, Any] | None:
    loaded = _mlb_daily_summary(selected_date)
    if not loaded:
        return None
    summary, resolved_date = loaded
    outputs = summary.get("outputs") or []
    if not isinstance(outputs, list):
        return None

    prop_key = market["prop_key"]
    prob_field = market["prob_field"]
    candidates: list[dict[str, Any]] = []
    for game in outputs:
        if not isinstance(game, dict):
            continue
        away, home = str(game.get("away") or ""), str(game.get("home") or "")
        entries = ((game.get("hitter_props_likelihood_topn") or {}).get(prop_key)) or []
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            prob = _to_float(entry.get(f"{prob_field}_cal")) or _to_float(entry.get(prob_field))
            if prob is None:
                continue
            team = str(entry.get("team") or "")
            opponent = home if team == away else away if team == home else ""
            candidates.append({
                "player": str(entry.get("name") or ""),
                "team": team,
                "opponent": opponent,
                "probability": prob,
                "lineup_order": entry.get("lineup_order"),
            })
    if not candidates:
        return None
    candidates.sort(key=lambda item: item["probability"], reverse=True)
    top = candidates[:10]
    if top[0]["probability"] <= 0:
        # Every candidate at exactly 0% means this market isn't populated
        # for today's slate upstream (observed for hits_runs_rbis_2plus on
        # 2026-07-12: all 270 entries across every game were 0.0, not a
        # real -- if rare -- probability distribution). Showing a "top 10"
        # that's actually a meaningless tie at zero would be worse than no
        # table at all.
        return None

    label = market["label"]
    rows = [
        [c["player"], c["team"], f"vs {c['opponent']}" if c["opponent"] else "", f"{c['probability'] * 100:.1f}%"]
        for c in top
    ]
    tables = [{
        "title": f"Top {label} candidates — {resolved_date}",
        "columns": ["Player", "Team", "Opponent", f"P({label} {prop_key.rsplit('_', 1)[-1].replace('plus', '+')})"],
        "rows": rows,
    }]
    charts = [{
        "type": "bar",
        "title": f"{label} probability leaders — {resolved_date}",
        "x_label": "Player",
        "y_label": "Probability %",
        "points": [{"x": c["player"], "y": round(c["probability"] * 100, 1)} for c in top],
    }]
    evidence = {"source": f"mlb_{market['key']}_candidates", "as_of": resolved_date, "market": label, "top_candidates": top}
    return {"evidence": evidence, "tables": tables, "charts": charts, "as_of": resolved_date, "sport": "mlb"}


def _mlb_top_candidates_evidence(question: str, context: dict[str, Any]) -> dict[str, Any] | None:
    words = _question_words(question)
    if not _is_ranking_intent_question(words):
        return None
    market = _detect_mlb_market(question, words)
    if market is None:
        return None
    selected_date = str(context.get("selected_date") or "") or None
    if market["source"] == "hr_targets":
        return _mlb_hr_candidates_evidence(selected_date)
    return _mlb_market_candidates_evidence(market, selected_date)


# ---------------------------------------------------------------------------
# MLB sim accuracy trend (trust layer)
# ---------------------------------------------------------------------------

_ACCURACY_KEYWORDS = {
    "accuracy", "accurate", "calibration", "calibrated", "track", "record",
    "trust", "reliable", "reliability", "performing", "performance",
}


def _mlb_accuracy_evidence(question: str, context: dict[str, Any]) -> dict[str, Any] | None:
    words = _question_words(question)
    if not (words & _ACCURACY_KEYWORDS):
        return None
    pattern = os.path.join(
        _mlb_data_root(), "eval", "batches", "season_2026_ui_daily_live", "sim_vs_actual_????-??-??.json"
    )
    files = sorted(glob.glob(pattern))[-14:]
    if not files:
        return None
    rows: list[list[Any]] = []
    series: list[dict[str, Any]] = []
    for path in files:
        match = re.search(r"sim_vs_actual_(\d{4}-\d{2}-\d{2})\.json", os.path.basename(path))
        if not match:
            continue
        day = match.group(1)
        try:
            payload = _load_json(path)
        except Exception:
            continue
        full = ((payload.get("assessment") or {}).get("full_game")) or {}
        totals = full.get("totals") or {}
        moneyline = full.get("moneyline") or {}
        pitchers = full.get("pitcher_props_starters") or {}
        games = totals.get("games")
        ml_accuracy = _to_float(moneyline.get("accuracy"))
        total_mae = _to_float(totals.get("mae"))
        so_mae = _to_float(pitchers.get("so_mae"))
        rows.append([
            day,
            games if games is not None else "—",
            f"{ml_accuracy:.0%}" if ml_accuracy is not None else "—",
            f"{total_mae:.2f}" if total_mae is not None else "—",
            f"{so_mae:.2f}" if so_mae is not None else "—",
        ])
        series.append({
            "date": day,
            "games": games,
            "moneyline_accuracy": ml_accuracy,
            "total_runs_mae": total_mae,
            "starter_so_mae": so_mae,
        })
    if not series:
        return None
    as_of = series[-1]["date"]
    ml_points = [s for s in series if s["moneyline_accuracy"] is not None]
    overall = {
        "days": len(series),
        "avg_moneyline_accuracy": round(
            sum(s["moneyline_accuracy"] for s in ml_points) / len(ml_points), 3
        ) if ml_points else None,
        "avg_total_runs_mae": round(
            sum(s["total_runs_mae"] for s in series if s["total_runs_mae"] is not None)
            / max(sum(1 for s in series if s["total_runs_mae"] is not None), 1), 2
        ),
    }
    tables = [{
        "title": f"SmartSim vs actual — last {len(rows)} evaluated days (through {as_of})",
        "columns": ["Date", "Games", "ML accuracy", "Total runs MAE", "Starter K MAE"],
        "rows": rows,
    }]
    charts = [{
        "type": "bar",
        "title": "Moneyline accuracy by day",
        "x_label": "Date",
        "y_label": "Accuracy %",
        "points": [
            {"x": s["date"][5:], "y": round(100.0 * s["moneyline_accuracy"], 1)}
            for s in ml_points
        ],
    }] if ml_points else []
    evidence = {
        "source": "mlb_sim_vs_actual",
        "as_of": as_of,
        "daily": series,
        "overall": overall,
    }
    return {"evidence": evidence, "tables": tables, "charts": charts, "as_of": as_of, "sport": "mlb"}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def _fetchers_for_sport(sport: str, question: str) -> list:
    if sport == "mlb":
        # A ranking-intent question ("best HRR targets today") is a
        # fundamentally different shape than a game/player question, and
        # letting both kinds of fetcher run together is what previously
        # made "best TB targets today" return the Tampa Bay Rays' game (TB
        # matched as a tricode) instead of a Total Bases leaderboard.
        # Ranking intent takes exclusive precedence when detected.
        if _is_ranking_intent_question(_question_words(question)):
            return [_mlb_top_candidates_evidence]
        return [
            _mlb_accuracy_evidence,
            _mlb_focused_evidence,
            _mlb_player_history_evidence,
            _mlb_bvp_evidence,
        ]
    if sport == "wnba":
        return [
            _wnba_focused_evidence,
            lambda q, c: _basketball_last10_evidence(q, c, "wnba"),
        ]
    if sport == "nba":
        return [
            lambda q, c: _basketball_last10_evidence(q, c, "nba"),
            _wnba_focused_evidence,
        ]
    if sport == "nhl":
        return [_nhl_last10_evidence]
    if sport == "":
        if _is_ranking_intent_question(_question_words(question)):
            return [_mlb_top_candidates_evidence]
        # No sport hint: cheap fetchers only.
        return [_mlb_accuracy_evidence, _mlb_focused_evidence, _mlb_player_history_evidence, _wnba_focused_evidence]
    return []


def collect_focused_evidence(question: str, context: dict[str, Any]) -> dict[str, Any] | None:
    """Best-effort question-specific evidence; merges all matching sections. Never raises."""
    sport = str(context.get("sport_slug") or context.get("sport") or "").strip().lower()
    sections: list[dict[str, Any]] = []
    for fetcher in _fetchers_for_sport(sport, question):
        try:
            result = fetcher(question, context)
        except Exception:
            name = getattr(fetcher, "__name__", "<lambda>")
            logger.exception("Ask focused-evidence fetcher %s failed", name)
            continue
        if isinstance(result, dict):
            sections.append(result)

    if not sections:
        return None
    tables: list[dict[str, Any]] = []
    charts: list[dict[str, Any]] = []
    evidence_sections: list[dict[str, Any]] = []
    for section in sections:
        tables.extend(section.get("tables") or [])
        charts.extend(section.get("charts") or [])
        if isinstance(section.get("evidence"), dict):
            evidence_sections.append(section["evidence"])
    return {
        "evidence": evidence_sections,
        "tables": tables[:MAX_TABLES],
        "charts": charts[:MAX_CHARTS],
        "as_of": max(str(s.get("as_of") or "") for s in sections),
        "sport": sections[0].get("sport"),
    }
