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
from collections import Counter
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


_NAME_BIGRAM_RE = re.compile(r"\b([A-Z][a-zA-Z'.-]+)\s+([A-Z][a-zA-Z'.-]+)\b")

# Sentence-initial/interrogative words are capitalized purely by English
# convention ("How's Jokic looking?", "Has Cardoso cleared..."), not because
# they're a first name -- excluded so a bare last-name question doesn't
# falsely register as a conflicting full-name mention.
_NAME_BIGRAM_STOPWORDS = {
    "how", "how's", "what", "what's", "who", "who's", "why", "when", "where",
    "is", "isn't", "was", "were", "wasn't", "weren't", "has", "hasn't",
    "have", "haven't", "having", "does", "doesn't", "did", "didn't", "do",
    "don't", "can", "can't", "could", "couldn't", "will", "won't", "would",
    "wouldn't", "should", "shouldn't", "tell", "give", "show", "let's",
    "the", "a", "an", "this", "that", "and", "or", "but",
}


def _question_name_bigrams(question: str) -> set[tuple[str, str]]:
    """Capitalized "First Last"-shaped word pairs in the raw question, used to
    tell a genuine full-name mention apart from a bare surname mention.
    """
    return {
        (_fold_diacritics(a).lower(), _fold_diacritics(b).lower())
        for a, b in _NAME_BIGRAM_RE.findall(str(question or ""))
        if _fold_diacritics(a).lower() not in _NAME_BIGRAM_STOPWORDS
    }


def _person_conflicts_with_question_name(name: str, question_bigrams: set[tuple[str, str]]) -> bool:
    """True when the question pairs this person's surname with a different
    first name (e.g. "Yordan Alvarez" in the question vs. a candidate named
    "Jose Alvarez") -- a bare surname match should not count as this person
    when the question itself names someone else with that surname.
    """
    if not question_bigrams:
        return False
    parts = [p for p in re.findall(r"[a-z0-9']+", _fold_diacritics(str(name or "")).lower()) if len(p) >= 3]
    if len(parts) < 2:
        return False
    first, last = parts[0], parts[-1]
    return any(b == last and a != first for a, b in question_bigrams)


def _person_matches(name: str, words: set[str], question: str = "") -> int:
    """Match score for a person's name: 0 = no, 1 = last name only, 2 = first+last.

    A last-name-only match is downgraded to 0 when `question` pairs that
    surname with a different first name -- e.g. a question about "Yordan
    Alvarez" must not resolve to a slate player named "Andrew Alvarez" just
    because both end in "Alvarez" (reported production bug, 2026-08-01).
    """
    parts = [p for p in re.findall(r"[a-z0-9']+", _fold_diacritics(str(name or "")).lower()) if len(p) >= 3]
    if not parts or parts[-1] not in words:
        return 0
    if len(parts) > 1 and parts[0] in words:
        return 2
    if question and _person_conflicts_with_question_name(name, _question_name_bigrams(question)):
        return 0
    return 1


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


def _mlb_game_score(question: str, words: set[str], game: dict[str, Any], names: dict[str, Any]) -> int:
    """Score how well this game matches the question. Team/tricode hits and a
    full first+last starter match outrank a last-name-only starter match, so
    an unrelated pitcher who happens to share a batter's last name (e.g. two
    different "Alvarez"es on the same slate) never outscores -- and can't
    displace -- the team/person the question actually named.
    """
    best = 0
    for team_text in (
        names.get("away_name"), names.get("home_name"),
        game.get("away"), game.get("home"),
    ):
        if team_text and _name_matches(str(team_text), words):
            best = max(best, 100)
    # Tricodes are matched against the raw question to respect case (NYY, PIT).
    for tri in (str(game.get("away") or ""), str(game.get("home") or "")):
        if len(tri) >= 2 and re.search(rf"\b{re.escape(tri)}\b", question):
            best = max(best, 100)
    starters = game.get("starter_names") or {}
    for starter in (starters.get("away"), starters.get("home")):
        if not starter:
            continue
        score = _person_matches(str(starter), words, question)
        if score == 2:
            best = max(best, 90)
        elif score == 1:
            best = max(best, 10)
    return best


def _mlb_match_game(question: str, context: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], str] | None:
    """The slate game (plus its name-context) the question is about, shared
    by every MLB evidence fetcher that needs "which game/pitcher/team" --
    same matching `_mlb_focused_evidence` always used, factored out so
    `_mlb_player_history_evidence` doesn't have to re-derive it. Picks the
    best-scoring game across the whole slate rather than the first hit, so
    slate order can't accidentally pick an unrelated game over the real
    match (see `_mlb_game_score`).
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

    best_score = 0
    best: tuple[dict[str, Any], dict[str, Any], str] | None = None
    for game in outputs:
        if not isinstance(game, dict):
            continue
        try:
            game_pk = int(game.get("game_pk"))
        except (TypeError, ValueError):
            game_pk = -1
        names = name_context.get(game_pk, {})
        score = _mlb_game_score(question, words, game, names)
        if score > best_score:
            best_score = score
            best = (game, names, iso_date)
    return best


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
    ) or any(_person_matches(str(s), words, question) > 0 for s in starters.values() if s)
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
            named = _person_matches(str(label), words, question) > 0
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


_WNBA_TEAM_ADVANCED_STAT_FIELDS = ("pace", "off_rtg", "def_rtg", "efg_pct", "tov_pct", "orb_pct", "ft_rate", "fg3a_rate", "fg3_pct", "ts_pct", "ast_per_100")


def _wnba_team_advanced_stats(selected_date: str | None) -> dict[str, dict[str, float]]:
    """Per-team pace/off_rtg/def_rtg/etc. snapshot at or before selected_date
    (or the most recent available). Confirmed against real mirrored data
    (team_advanced_stats_2026_asof_20260715.csv) that this already feeds
    the SmartSim projections upstream (basketball_props_smart_sim.py) but
    was never surfaced to Ask the Syndicate -- the closest WNBA analog to
    MLB's "opposing pitcher's own season rates" table, since there's no
    defender-assignment or bullpen-style concept anywhere in WNBA data.
    """
    target = str(selected_date or "").replace("-", "")
    # Same directory-priority reduce as _wnba_latest above: pick each
    # directory's own best candidate, then only replace the running best on
    # a STRICTLY later date, so a tie keeps the first (highest-priority,
    # e.g. WNBA_BETTING_DATA_ROOT) directory's file rather than whichever
    # candidate happens to sort last alphabetically across all directories.
    best: tuple[str, str] | None = None  # (asof_yyyymmdd, path)
    for directory in _wnba_processed_dirs():
        directory_candidates: list[tuple[str, str]] = []
        for path in glob.glob(os.path.join(directory, "team_advanced_stats_*_asof_*.csv")):
            match = re.search(r"_asof_(\d{8})\.csv$", path)
            if not match:
                continue
            try:
                if os.path.getsize(path) <= 0:
                    continue  # a 0-byte file has been observed in production for the non-asof variant
            except OSError:
                continue
            directory_candidates.append((match.group(1), path))
        if not directory_candidates:
            continue
        eligible = [c for c in directory_candidates if not target or c[0] <= target] or directory_candidates
        eligible.sort()
        candidate = eligible[-1]
        if best is None or candidate[0] > best[0]:
            best = candidate
    if best is None:
        return {}
    _, path = best
    stats: dict[str, dict[str, float]] = {}
    try:
        with open(path, encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                team = str(row.get("team") or "").strip().upper()
                if not team:
                    continue
                parsed = {
                    key: _to_float(row.get(key))
                    for key in _WNBA_TEAM_ADVANCED_STAT_FIELDS
                    if _to_float(row.get(key)) is not None
                }
                if parsed:
                    stats[team] = parsed
    except Exception:
        return {}
    return stats


def _wnba_team_pace_defense_table(team_tri: str, team_label: str, opponent_tri: str, opponent_label: str, stats_by_team: dict[str, dict[str, float]]) -> dict[str, Any] | None:
    team_stats = stats_by_team.get(str(team_tri or "").strip().upper())
    opp_stats = stats_by_team.get(str(opponent_tri or "").strip().upper())
    if not team_stats and not opp_stats:
        return None
    rows: list[list[Any]] = []
    for label, key, fmt in (
        ("Pace", "pace", "{:.1f}"),
        ("Off rating", "off_rtg", "{:.1f}"),
        ("Def rating", "def_rtg", "{:.1f}"),
        ("eFG%", "efg_pct", "{:.1%}"),
        ("TOV%", "tov_pct", "{:.1%}"),
        ("TS%", "ts_pct", "{:.1%}"),
    ):
        t_val = (team_stats or {}).get(key)
        o_val = (opp_stats or {}).get(key)
        if t_val is None and o_val is None:
            continue
        rows.append([label, fmt.format(t_val) if t_val is not None else "—", fmt.format(o_val) if o_val is not None else "—"])
    if not rows:
        return None
    return {
        "title": f"Team pace & defense — {team_label} vs {opponent_label}",
        "columns": ["Factor", team_label, opponent_label],
        "rows": rows,
    }


def _wnba_vs_opponent_history(player_name: str, team_tri: str, opponent_tri: str) -> list[dict[str, Any]]:
    """This player's box score line in every game this season where their
    team faced this specific opponent, self-joined by game_id since
    boxscores_history.csv has no opponent column.

    Not a BvP-style multi-season archive -- confirmed against real data
    that this repo's WNBA boxscore history only starts ~2026-04-25 (this
    season) and WNBA teams only meet 2-4 times/season, so the sample here
    is thin by construction, not a bug.
    """
    path = next(
        (os.path.join(d, "boxscores_history.csv") for d in _wnba_processed_dirs()
         if os.path.exists(os.path.join(d, "boxscores_history.csv"))),
        None,
    )
    if not path:
        return []
    team_tri = str(team_tri or "").strip().upper()
    opponent_tri = str(opponent_tri or "").strip().upper()
    target_name = str(player_name or "").strip().lower()
    if not team_tri or not opponent_tri or not target_name:
        return []

    by_game: dict[str, list[dict[str, Any]]] = {}
    with open(path, encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            game_id = str(row.get("game_id") or row.get("gameId") or "").strip()
            if game_id:
                by_game.setdefault(game_id, []).append(row)

    results: list[dict[str, Any]] = []
    for rows in by_game.values():
        teams_in_game = {str(r.get("TEAM_ABBREVIATION") or "").strip().upper() for r in rows}
        if team_tri not in teams_in_game or opponent_tri not in teams_in_game:
            continue
        for row in rows:
            if str(row.get("TEAM_ABBREVIATION") or "").strip().upper() != team_tri:
                continue
            if str(row.get("PLAYER_NAME") or "").strip().lower() != target_name:
                continue
            results.append({
                "date": str(row.get("date") or ""),
                "min": _to_float(row.get("MIN")),
                "pts": _to_float(row.get("PTS")),
                "reb": _to_float(row.get("REB")),
                "ast": _to_float(row.get("AST")),
            })
    results.sort(key=lambda r: r["date"], reverse=True)
    return results


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

    # Player question takes priority over team question. Score every player
    # across the whole slate and keep the best match rather than the first
    # hit, so a last-name-only match on an unrelated player (e.g. two
    # players sharing a surname) can't win just by appearing earlier in the
    # game/side iteration order.
    matched_player: dict[str, Any] | None = None
    matched_game: dict[str, Any] | None = None
    best_score = 0
    for game in games:
        if not isinstance(game, dict):
            continue
        sim = game.get("sim") or {}
        players = sim.get("players") or {}
        for side in ("home", "away"):
            for player in players.get(side) or []:
                if not isinstance(player, dict):
                    continue
                player_name = str(player.get("player_name") or "")
                score = _person_matches(player_name, words, question)
                if score > best_score:
                    best_score = score
                    matched_player = player
                    matched_game = game

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

        team_tri = str(matched_player.get("team") or "")
        opponent_tri = str(matched_player.get("opponent") or "")

        # This player's box score in every meeting vs this exact opponent
        # this season -- thin same-season sample (WNBA teams meet 2-4x/yr),
        # not a BvP-style archive, but real derived data, not guesswork.
        vs_opponent_games = _wnba_vs_opponent_history(name, team_tri, opponent_tri)
        if vs_opponent_games:
            tables.append({
                "title": f"{name} vs {opponent} this season ({len(vs_opponent_games)} meeting{'s' if len(vs_opponent_games) != 1 else ''})",
                "columns": ["Date", "MIN", "PTS", "REB", "AST"],
                "rows": [
                    [
                        g["date"],
                        f"{g['min']:.0f}" if g.get("min") is not None else "—",
                        f"{g['pts']:.0f}" if g.get("pts") is not None else "—",
                        f"{g['reb']:.0f}" if g.get("reb") is not None else "—",
                        f"{g['ast']:.0f}" if g.get("ast") is not None else "—",
                    ]
                    for g in vs_opponent_games
                ],
            })
        else:
            tables.append({
                "title": f"{name} vs {opponent} this season",
                "columns": ["Note"],
                "rows": [[f"No meetings between these teams yet this season, or {name} didn't play in them — WNBA teams only face each other a handful of times a year."]],
            })

        team_stats_by_tri = _wnba_team_advanced_stats(iso_date)
        pace_table = _wnba_team_pace_defense_table(team_tri, team, opponent_tri, opponent, team_stats_by_tri)
        if pace_table:
            tables.append(pace_table)

        evidence = {
            "source": "wnba_sim_detail",
            "as_of": iso_date,
            "player": name,
            "team": team,
            "opponent": opponent,
            "minutes_mean": minutes,
            "projections": evidence_stats,
            "market_lines": market_lines[:8],
            "vs_opponent_this_season": vs_opponent_games,
            "team_pace_defense": {
                "team": team_stats_by_tri.get(team_tri.upper()),
                "opponent": team_stats_by_tri.get(opponent_tri.upper()),
            },
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

        team_stats_by_tri = _wnba_team_advanced_stats(iso_date)
        pace_table = _wnba_team_pace_defense_table(
            away_tri, _wnba_team_label(away_tri), home_tri, _wnba_team_label(home_tri), team_stats_by_tri
        )
        if pace_table:
            tables.append(pace_table)

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


def _boxscore_last_n(directories: list[str], words: set[str], n: int, question: str = "") -> list[dict[str, Any]]:
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
                scores[name] = _person_matches(name, words, question)
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
    games = _boxscore_last_n(directories, words, LAST_N_GAMES, question)
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
                scores[name] = _person_matches(name, words, question)
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


# ---------------------------------------------------------------------------
# MLB bullpen + per-player simulated-probability lookups
#
# These read the same per-game roster snapshots and daily_summary outputs the
# rest of this module already reads, self-contained rather than importing
# syndicate.features.mlb.hr_targets's private loaders (see module docstring).
# ---------------------------------------------------------------------------

_ROSTER_PAYLOAD_CACHE_LOCK = threading.Lock()
_ROSTER_PAYLOAD_CACHE: dict[tuple[str, int], dict[str, Any]] = {}
_ROSTER_PAYLOAD_CACHE_MAX = 32


def _mlb_snapshot_root() -> str:
    return os.path.join(_mlb_data_root(), "daily", "snapshots")


def _mlb_roster_payload_for_game(selected_date: str, game_pk: int | None) -> dict[str, Any]:
    """Per-game roster snapshot (lineup/bench/starter/bullpen per side)."""
    if not selected_date or game_pk is None:
        return {}
    cache_key = (selected_date, int(game_pk))
    with _ROSTER_PAYLOAD_CACHE_LOCK:
        if cache_key in _ROSTER_PAYLOAD_CACHE:
            return _ROSTER_PAYLOAD_CACHE[cache_key]

    snapshot_dir = os.path.join(_mlb_snapshot_root(), selected_date)
    payload: dict[str, Any] = {}
    # Flat layout first: confirmed live (2026-07-27, hr_targets.py) that
    # production writes the full roster snapshot (bullpen_profiles etc.)
    # directly under snapshots/<date>/, not into roster_objs/ -- but a local
    # mirror can still have a roster_objs/roster_obj_*.json that matches the
    # same *pk<game_pk>*.json glob with only a minimal lineup/team payload
    # (no bullpen_profiles), which would silently shadow the real data if
    # checked first.
    for candidate_dir in (snapshot_dir, os.path.join(snapshot_dir, "roster_objs")):
        matches = sorted(glob.glob(os.path.join(candidate_dir, f"*pk{int(game_pk)}*.json")))
        if not matches:
            continue
        try:
            loaded = _load_json(matches[0])
        except Exception:
            continue
        if isinstance(loaded, dict) and any(
            isinstance(loaded.get(side), dict) and "bullpen_profiles" in loaded[side]
            for side in ("away", "home")
        ):
            payload = loaded
            break
        if isinstance(loaded, dict) and not payload:
            payload = loaded  # keep the best candidate seen so far, prefer one with bullpen data

    with _ROSTER_PAYLOAD_CACHE_LOCK:
        if len(_ROSTER_PAYLOAD_CACHE) >= _ROSTER_PAYLOAD_CACHE_MAX:
            _ROSTER_PAYLOAD_CACHE.pop(next(iter(_ROSTER_PAYLOAD_CACHE)), None)
        _ROSTER_PAYLOAD_CACHE[cache_key] = payload
    return payload


def _mlb_side_team_abbr(side_doc: dict[str, Any]) -> str:
    """A roster-snapshot side's team abbreviation. `team` is a nested object
    ({"team_id", "name", "abbreviation"}) in production snapshots, not a
    plain string -- confirmed against real mirrored data (2026-06-04,
    2026-07-12), unlike the flat string every other team field in this
    module uses (hr_targets' target["team"]/["opponent"]).
    """
    if not isinstance(side_doc, dict):
        return ""
    team = side_doc.get("team")
    if isinstance(team, dict):
        return str(team.get("abbreviation") or team.get("abbr") or "").strip().upper()
    return str(team or "").strip().upper()


def _mlb_bullpen_profiles_for_team(roster_payload: dict[str, Any], team_abbr: str) -> list[dict[str, Any]]:
    """The named team's bullpen_profiles list (role/leverage/availability/own
    season rates per reliever) from a roster snapshot payload.
    """
    team_abbr = str(team_abbr or "").strip().upper()
    if not team_abbr or not isinstance(roster_payload, dict):
        return []
    for side in ("away", "home"):
        side_doc = roster_payload.get(side)
        if isinstance(side_doc, dict) and _mlb_side_team_abbr(side_doc) == team_abbr:
            profiles = side_doc.get("bullpen_profiles")
            return [p for p in profiles if isinstance(p, dict)] if isinstance(profiles, list) else []
    return []


def _mlb_side_pitching_staff(side_doc: dict[str, Any]) -> list[dict[str, Any]]:
    """A team's starter plus bullpen, as a single list of pitcher profiles.

    The starter comes from starter_profile (season rates included) when
    present, else the thinner `starter` dict (id/name/role only).
    """
    if not isinstance(side_doc, dict):
        return []
    staff: list[dict[str, Any]] = []
    starter_profile = side_doc.get("starter_profile")
    starter = side_doc.get("starter")
    if isinstance(starter_profile, dict) and starter_profile.get("id") is not None:
        staff.append(starter_profile)
    elif isinstance(starter, dict) and starter.get("id") is not None:
        staff.append({**starter, "role": starter.get("role") or "SP"})
    bullpen_profiles = side_doc.get("bullpen_profiles")
    if isinstance(bullpen_profiles, list):
        staff.extend(p for p in bullpen_profiles if isinstance(p, dict))
    return staff


def _mlb_find_pitcher_in_slate(selected_date: str, words: set[str], question: str = "") -> tuple[int, str, str, dict[str, Any]] | None:
    """Best pitcher name match (starter OR reliever) across today's whole
    slate. Returns (game_pk, team, opponent_team, pitcher_profile).

    Fallback for pitcher questions that don't match hr_targets'
    opponent_pitcher_name -- confirmed against real mirrored data that many
    games only have ONE side's starter represented there (whichever team
    happened to have an HR-candidate batter that game), so the other
    starter -- not just relief arms -- can be entirely unreachable through
    the primary hr_targets-based match.
    """
    if not selected_date:
        return None
    snapshot_dir = os.path.join(_mlb_snapshot_root(), selected_date)
    if not os.path.isdir(snapshot_dir):
        return None
    best: tuple[int, tuple[int, str, str, dict[str, Any]]] | None = None
    for path in sorted(glob.glob(os.path.join(snapshot_dir, "roster_*_pk*.json"))):
        match = re.search(r"pk(\d+)", os.path.basename(path), re.IGNORECASE)
        if not match:
            continue
        game_pk = int(match.group(1))
        try:
            payload = _load_json(path)
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        sides = {
            side: _mlb_side_team_abbr(payload.get(side))
            for side in ("away", "home")
            if isinstance(payload.get(side), dict)
        }
        for side, team in sides.items():
            if not team:
                continue
            opponent_team = sides.get("home" if side == "away" else "away", "")
            for profile in _mlb_side_pitching_staff(payload.get(side)):
                score = _person_matches(str(profile.get("name") or ""), words, question)
                if score and (best is None or score > best[0]):
                    best = (score, (game_pk, team, opponent_team, profile))
    return best[1] if best else None


def _mlb_lineup_batters(side_doc: dict[str, Any]) -> list[dict[str, Any]]:
    lineup = side_doc.get("lineup") if isinstance(side_doc, dict) else None
    if isinstance(lineup, dict) and isinstance(lineup.get("batters"), list):
        return [row for row in lineup["batters"] if isinstance(row, dict)]
    if isinstance(lineup, list):
        return [row for row in lineup if isinstance(row, dict)]
    return []


def _mlb_find_batter_in_slate(selected_date: str, words: set[str], question: str = "") -> dict[str, Any] | None:
    """Best batter-name match across every team's full starting lineup for
    the date, returned in the same shape as an hr_targets target row.

    hr_targets only carries the ~30 HR-candidate batters leaguewide per day
    (confirmed against real mirrored data -- most starters, e.g. a leadoff
    or bottom-of-order hitter, are absent from it entirely), which silently
    made the whole BvP/matchup-probability/bullpen fetcher below a no-op
    for anyone not flagged as an HR candidate that day. This searches the
    full per-game lineup instead, so any starting batter resolves.
    """
    if not selected_date:
        return None
    snapshot_dir = os.path.join(_mlb_snapshot_root(), selected_date)
    if not os.path.isdir(snapshot_dir):
        return None
    best: tuple[int, dict[str, Any]] | None = None
    for path in sorted(glob.glob(os.path.join(snapshot_dir, "roster_*_pk*.json"))):
        match = re.search(r"pk(\d+)", os.path.basename(path), re.IGNORECASE)
        if not match:
            continue
        game_pk = int(match.group(1))
        try:
            payload = _load_json(path)
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        for side in ("away", "home"):
            side_doc = payload.get(side)
            if not isinstance(side_doc, dict):
                continue
            opponent_doc = payload.get("home" if side == "away" else "away")
            opponent_doc = opponent_doc if isinstance(opponent_doc, dict) else {}
            team = _mlb_side_team_abbr(side_doc)
            opponent_team = _mlb_side_team_abbr(opponent_doc)
            starter = opponent_doc.get("starter") if isinstance(opponent_doc.get("starter"), dict) else {}
            starter_profile = opponent_doc.get("starter_profile") if isinstance(opponent_doc.get("starter_profile"), dict) else {}
            for batter in _mlb_lineup_batters(side_doc):
                name = str(batter.get("name") or "")
                score = _person_matches(name, words, question)
                if not score or (best is not None and score <= best[0]):
                    continue
                try:
                    batter_id = int(batter.get("id"))
                except (TypeError, ValueError):
                    continue
                target = {
                    "player_name": name,
                    "batter_id": batter_id,
                    "team": team,
                    "opponent": opponent_team,
                    "game_pk": game_pk,
                    "opponent_pitcher_id": starter.get("id") if starter.get("id") is not None else starter_profile.get("id"),
                    "opponent_pitcher_name": str(starter.get("name") or starter_profile.get("name") or ""),
                    "batter_k_rate": batter.get("k_rate"),
                    "batter_bb_rate": batter.get("bb_rate"),
                    "batter_hr_rate": batter.get("hr_rate"),
                    "batter_inplay_hit_rate": batter.get("inplay_hit_rate"),
                    "pitcher_k_rate": starter_profile.get("k_rate"),
                    "pitcher_bb_rate": starter_profile.get("bb_rate"),
                    "pitcher_hr_rate": starter_profile.get("hr_rate"),
                    "pitcher_inplay_hit_rate": starter_profile.get("inplay_hit_rate"),
                }
                best = (score, target)
    return best[1] if best else None


_TOPN_MARKET_BASE_LABELS: dict[str, str] = {
    "hits": "Hits",
    "total_bases": "Total Bases",
    "rbi": "RBIs",
    "runs": "Runs Scored",
    "doubles": "Doubles",
    "triples": "Triples",
    "sb": "Stolen Bases",
    "hits_runs_rbis": "Hits+Runs+RBIs",
}
_TOPN_PROP_KEY_RE = re.compile(r"^(?P<base>.+)_(?P<threshold>\d+)plus$")


def _topn_market_label(prop_key: str) -> str:
    match = _TOPN_PROP_KEY_RE.match(str(prop_key or ""))
    if not match:
        return str(prop_key or "").replace("_", " ").title()
    label = _TOPN_MARKET_BASE_LABELS.get(match.group("base"), match.group("base").replace("_", " ").title())
    return f"{label} {match.group('threshold')}+"


def _topn_entry_probability(entry: dict[str, Any]) -> float | None:
    """A topn entry's probability field name isn't derivable from its prop_key
    (p_h_1plus for "hits_1plus", p_2b_1plus for "doubles_1plus", etc.) -- find
    it generically instead, preferring the calibrated variant when present.
    """
    cal_key = next((k for k in entry if k.startswith("p_") and k.endswith("_cal")), None)
    if cal_key:
        value = _to_float(entry.get(cal_key))
        if value is not None:
            return value
    plain_key = next((k for k in entry if k.startswith("p_") and not k.endswith("_cal")), None)
    return _to_float(entry.get(plain_key)) if plain_key else None


def _mlb_topn_probabilities_by_batter(outputs: Any) -> dict[int, dict[str, float]]:
    """One pass over daily_summary outputs -> {batter_id: {prop_key: probability}}
    across every hitter_props_likelihood_topn market, not just the 8 markets
    registered in _MLB_MARKET_REGISTRY (that registry only feeds the
    ranking/leaderboard fetcher, not a specific-player lookup).
    """
    by_batter: dict[int, dict[str, float]] = {}
    if not isinstance(outputs, list):
        return by_batter
    for game in outputs:
        if not isinstance(game, dict):
            continue
        topn = game.get("hitter_props_likelihood_topn")
        if not isinstance(topn, dict):
            continue
        for prop_key, entries in topn.items():
            if prop_key == "n" or not isinstance(entries, list):
                continue
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                try:
                    batter_id = int(entry.get("batter_id"))
                except (TypeError, ValueError):
                    continue
                probability = _topn_entry_probability(entry)
                if probability is None:
                    continue
                by_batter.setdefault(batter_id, {})[prop_key] = probability
    return by_batter


def _mlb_hitter_topn_probabilities(selected_date: str | None, batter_id: int | None) -> dict[str, float]:
    if batter_id is None:
        return {}
    loaded = _mlb_daily_summary(selected_date)
    if not loaded:
        return {}
    summary, _iso_date = loaded
    return _mlb_topn_probabilities_by_batter(summary.get("outputs") or []).get(int(batter_id), {})


def _mlb_bvp_evidence(question: str, context: dict[str, Any]) -> dict[str, Any] | None:
    loaded = _mlb_slate_targets(str(context.get("selected_date") or "") or None)
    if not loaded:
        return None
    targets, iso_date = loaded
    words = _question_words(question)

    # Batter question: their history vs today's opposing starter. hr_targets
    # only carries the ~30 HR-candidate batters leaguewide/day (confirmed
    # against real mirrored data -- most starters, e.g. a leadoff or
    # bottom-of-order hitter, are absent from it entirely), so fall back to
    # the full per-game lineup when the curated list doesn't have the name.
    batter_rows = [t for t in targets if _person_matches(str(t.get("player_name") or ""), words, question) > 0]
    if batter_rows:
        batter_rows.sort(key=lambda t: _person_matches(str(t.get("player_name") or ""), words, question), reverse=True)
        target = batter_rows[0]
    else:
        target = _mlb_find_batter_in_slate(iso_date, words, question)

    if target is not None:
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

        # Real worker-blended matchup probabilities for this exact game --
        # not season rates, the sim's own P(outcome) for hits/TB/RBI/runs/etc.
        topn_probs = _mlb_hitter_topn_probabilities(iso_date, batter_id)
        if topn_probs:
            topn_rows = [
                [_topn_market_label(key), f"{prob * 100:.1f}%"]
                for key, prob in sorted(topn_probs.items(), key=lambda kv: kv[1], reverse=True)
            ]
            tables.append({
                "title": f"Today's simulated matchup probabilities — {batter_name} ({iso_date})",
                "columns": ["Market", "Probability"],
                "rows": topn_rows,
            })

        # Both sides' own season per-PA tendencies, side by side -- component
        # rates, not a blended matchup probability (no worker-computed blend
        # exists for K/BB/in-play-out; see the market-probability table above
        # for the outcomes the sim does blend).
        season_rows: list[list[Any]] = []
        for label, batter_key, pitcher_key in (
            ("Strikeout rate", "batter_k_rate", "pitcher_k_rate"),
            ("Walk rate", "batter_bb_rate", "pitcher_bb_rate"),
            ("Home run rate", "batter_hr_rate", "pitcher_hr_rate"),
            ("In-play hit rate", "batter_inplay_hit_rate", "pitcher_inplay_hit_rate"),
        ):
            b_val = _to_float(target.get(batter_key))
            p_val = _to_float(target.get(pitcher_key))
            if b_val is None and p_val is None:
                continue
            season_rows.append([
                label,
                f"{b_val * 100:.1f}%" if b_val is not None else "—",
                f"{p_val * 100:.1f}%" if p_val is not None else "—",
            ])
        if season_rows:
            tables.append({
                "title": f"Season tendencies (own rates, not matchup-blended) — {batter_name} vs {pitcher_name}",
                "columns": ["Outcome", batter_name, pitcher_name],
                "rows": season_rows,
            })

        # Opposing bullpen: same career-BvP lookup used for the starter above,
        # generalized to any pitcher id, plus each arm's own season rates.
        bullpen_rows: list[list[Any]] = []
        bullpen_evidence: list[dict[str, Any]] = []
        opponent_team = str(target.get("opponent") or "").strip()
        try:
            game_pk = int(target.get("game_pk"))
        except (TypeError, ValueError):
            game_pk = None
        if game_pk is not None and opponent_team:
            roster_payload = _mlb_roster_payload_for_game(iso_date, game_pk)
            bullpen = _mlb_bullpen_profiles_for_team(roster_payload, opponent_team)
            bullpen.sort(
                key=lambda p: (_to_float(p.get("leverage_skill")) or 0.0, _to_float(p.get("availability_mult")) or 0.0),
                reverse=True,
            )
            for profile in bullpen[:6]:
                try:
                    reliever_id = int(profile.get("id"))
                except (TypeError, ValueError):
                    reliever_id = None
                reliever_name = str(profile.get("name") or "Reliever")
                role = str(profile.get("role") or "RP")
                career = _bvp_counts_for_pitcher(reliever_id).get(batter_id) if reliever_id is not None else None
                history = (
                    f"{career['pa']} PA, {career['hits']} H, {career['hr']} HR"
                    if career and (career.get("pa") or 0) > 0
                    else "no recorded history"
                )
                bullpen_rows.append([
                    f"{reliever_name} ({role})",
                    f"{(_to_float(profile.get('k_rate')) or 0) * 100:.1f}%",
                    f"{(_to_float(profile.get('bb_rate')) or 0) * 100:.1f}%",
                    f"{(_to_float(profile.get('hr_rate')) or 0) * 100:.1f}%",
                    history,
                ])
                bullpen_evidence.append({
                    "pitcher": reliever_name,
                    "role": role,
                    "k_rate": _to_float(profile.get("k_rate")),
                    "bb_rate": _to_float(profile.get("bb_rate")),
                    "hr_rate": _to_float(profile.get("hr_rate")),
                    "career_bvp": career or {"pa": 0},
                })
        if bullpen_rows:
            tables.append({
                "title": f"Opposing bullpen — vs {batter_name} ({iso_date})",
                "columns": ["Reliever (role)", "K rate", "BB rate", "HR rate", "Career vs batter"],
                "rows": bullpen_rows,
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
            "topn_probabilities": topn_probs,
            "opposing_bullpen": bullpen_evidence,
        }
        return {"evidence": evidence, "tables": tables, "charts": [], "as_of": iso_date, "sport": "mlb"}

    # Pitcher question: his history vs today's opposing lineup.
    pitcher_rows = [t for t in targets if _person_matches(str(t.get("opponent_pitcher_name") or ""), words, question) > 0]
    reliever_role: str | None = None
    game_pk: int | None = None
    opponent_team = ""
    park_weather_row: dict[str, Any] = {}
    if pitcher_rows:
        matched_row = pitcher_rows[0]
        pitcher_name = str(matched_row.get("opponent_pitcher_name") or "Pitcher")
        try:
            pitcher_id = int(matched_row.get("opponent_pitcher_id"))
        except (TypeError, ValueError):
            return None
        try:
            game_pk = int(matched_row.get("game_pk"))
        except (TypeError, ValueError):
            game_pk = None
        opponent_team = str(matched_row.get("team") or "").strip().upper()
        park_weather_row = matched_row  # game-level fields live directly on this row
    else:
        # Not found via hr_targets' opponent_pitcher_name -- confirmed
        # against real mirrored data that hr_targets only represents
        # whichever side happened to have an HR-candidate batter that game,
        # so this can be a bullpen arm OR the *other* team's starter.
        # Search the full slate (starters + bullpens) before giving up.
        pitcher_hit = _mlb_find_pitcher_in_slate(iso_date, words, question)
        if pitcher_hit is None:
            return None
        game_pk, _pitcher_team, opponent_team, found_profile = pitcher_hit
        pitcher_name = str(found_profile.get("name") or "Pitcher")
        reliever_role = str(found_profile.get("role") or "").strip() or None
        try:
            pitcher_id = int(found_profile.get("id"))
        except (TypeError, ValueError):
            return None
        # No hr_targets row named this pitcher at all -- best-effort look for
        # any target sharing this game_pk for park/weather context (they're
        # game-level, not batter-specific, so any target from the same game
        # carries the same values).
        park_weather_row = next((t for t in targets if t.get("game_pk") == game_pk), {}) if game_pk is not None else {}

    # The opposing lineup is every batter in the full per-game roster
    # lineup, not hr_targets' team-filtered rows -- confirmed against real
    # mirrored data that hr_targets can carry ZERO rows for a team even
    # when its starter IS represented (it only lists the handful of
    # HR-candidate batters per game, never a full lineup), so it can't be
    # the lineup source for either match path above.
    pitcher_rows = []
    if game_pk is not None and opponent_team:
        roster_payload = _mlb_roster_payload_for_game(iso_date, game_pk)
        for side in ("away", "home"):
            side_doc = roster_payload.get(side)
            if isinstance(side_doc, dict) and _mlb_side_team_abbr(side_doc) == opponent_team:
                for batter in _mlb_lineup_batters(side_doc):
                    try:
                        batter_id = int(batter.get("id"))
                    except (TypeError, ValueError):
                        continue
                    pitcher_rows.append({"batter_id": batter_id, "player_name": str(batter.get("name") or "")})
                break
    if not pitcher_rows:
        # Fall back to whatever hr_targets happens to carry for this team
        # rather than surfacing nothing at all (e.g. roster snapshot missing).
        pitcher_rows = [t for t in targets if str(t.get("team") or "").strip().upper() == opponent_team]
    if not pitcher_rows:
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

    # Today's opposing lineup's real worker-blended matchup probabilities --
    # one load + one pass shared across every batter, not a per-batter
    # daily_summary reload (this lineup can be 9+ hitters).
    lineup_topn_leaders: list[tuple[str, str, float]] = []
    lineup_topn_evidence: dict[str, dict[str, float]] = {}
    daily_summary_loaded = _mlb_daily_summary(iso_date)
    if daily_summary_loaded:
        topn_by_batter = _mlb_topn_probabilities_by_batter((daily_summary_loaded[0] or {}).get("outputs") or [])
        seen_names: set[int] = set()
        for target in pitcher_rows:
            try:
                batter_id = int(target.get("batter_id"))
            except (TypeError, ValueError):
                continue
            if batter_id in seen_names:
                continue
            seen_names.add(batter_id)
            probs = topn_by_batter.get(batter_id)
            if not probs:
                continue
            name = str(target.get("player_name") or batter_id)
            lineup_topn_evidence[name] = probs
            top_market, top_prob = max(probs.items(), key=lambda kv: kv[1])
            lineup_topn_leaders.append((name, _topn_market_label(top_market), top_prob))
    if lineup_topn_leaders:
        lineup_topn_leaders.sort(key=lambda item: item[2], reverse=True)
        tables.append({
            "title": f"Today's opposing lineup — simulated probabilities vs {pitcher_name} ({iso_date})",
            "columns": ["Batter", "Best market", "Probability"],
            "rows": [[name, market, f"{prob * 100:.1f}%"] for name, market, prob in lineup_topn_leaders[:10]],
        })

    # Park/weather multipliers are game-level, not batter-specific -- only
    # carried on hr_targets rows (park_weather_row, captured above; the
    # pitcher_rows rebuilt below come from the roster lineup instead, which
    # doesn't have these fields at all).
    park_weather_rows: list[list[Any]] = []
    for label, key, fmt in (
        ("Park HR mult", "park_hr_mult", "{:.2f}"),
        ("Weather HR mult", "weather_hr_mult", "{:.2f}"),
    ):
        value = _to_float(park_weather_row.get(key))
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
        "role": reliever_role,
        "lineup_bvp": [
            {"batter": name, **counts} for name, counts in lineup[:10]
        ],
        "lineup_bvp_pa_total": sum(counts.get("pa") or 0 for _, counts in lineup),
        "lineup_topn_probabilities": lineup_topn_evidence,
    }
    return {"evidence": evidence, "tables": tables, "charts": [], "as_of": iso_date, "sport": "mlb"}


# ---------------------------------------------------------------------------
# MLB recent-form game log + advanced Statcast profile
# ---------------------------------------------------------------------------


def _mlb_processed_dir() -> str:
    return os.path.join(_mlb_data_root(), "processed")


def _mlb_match_player_in_log(filename: str, words: set[str], question: str = "") -> tuple[str, int, list[dict[str, Any]]] | None:
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
        score = _person_matches(names.get(player_id, ""), words, question)
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


def _mlb_pitcher_chart_stat(words: set[str]) -> tuple[str, str, str]:
    """(row_key, y_label, chart-title phrase) for whichever pitching stat the
    question actually asked about -- a bare "wants_pitching" check (any of
    K/outs/pitches/innings) isn't enough to know WHICH one to chart; this
    picks among the columns already in the last-starts table.
    """
    if "outs" in words and not (words & {"strikeout", "strikeouts", "k", "ks"}):
        return "outs", "Outs", "outs recorded"
    if words & {"walk", "walks"}:
        return "bb", "BB", "walks"
    if "er" in words or "earned" in words:
        return "er", "ER", "earned runs"
    if words & {"pitch", "pitches"}:
        return "pitches", "Pitches", "pitch count"
    return "k", "K", "strikeouts"


def _mlb_opposing_lineup_statcast_table(question: str, context: dict[str, Any], pitcher_label: str) -> dict[str, Any] | None:
    """Today's opposing lineup's own Statcast approach (xwOBA/barrel/hard-hit/
    K-mult) -- distinct from _mlb_advanced_profile_table, which is the
    PITCHER's own stuff. Answers "how does the lineup match up against him"
    using the same today's-lineup batter list _mlb_bvp_evidence's pitcher
    branch already derives from hr_targets, just against the batter's own
    Statcast profile instead of career BvP counts.
    """
    loaded = _mlb_slate_targets(str(context.get("selected_date") or "") or None)
    if not loaded:
        return None
    targets, iso_date = loaded
    words = _question_words(question)
    pitcher_rows = [t for t in targets if _person_matches(str(t.get("opponent_pitcher_name") or ""), words, question) > 0]
    if not pitcher_rows:
        return None

    from syndicate.features.intelligence import _mlb_statcast_profile_from_ids

    seen: set[int] = set()
    entries: list[tuple[str, dict[str, Any]]] = []
    for target in pitcher_rows:
        try:
            batter_id = int(target.get("batter_id"))
        except (TypeError, ValueError):
            continue
        if batter_id in seen:
            continue
        seen.add(batter_id)
        profile = _mlb_statcast_profile_from_ids(batter_id=batter_id, pitcher_id=None)
        factors = (profile or {}).get("batter") if profile else None
        if not factors or all(value is None for value in factors.values()):
            continue
        name = str(target.get("player_name") or batter_id)
        entries.append((name, factors))
    if not entries:
        return None

    # Strongest matchup threat first (highest expected production).
    entries.sort(key=lambda item: _to_float(item[1].get("xwoba")) or -1.0, reverse=True)
    rows: list[list[Any]] = []
    for name, factors in entries[:9]:
        xwoba = _to_float(factors.get("xwoba"))
        barrel = _to_float(factors.get("barrel_rate"))
        hardhit = _to_float(factors.get("hardhit_rate"))
        k_mult = _to_float(factors.get("k_mult"))
        rows.append([
            name,
            f"{xwoba:.3f}" if xwoba is not None else "—",
            f"{barrel:.1%}" if barrel is not None else "—",
            f"{hardhit:.1%}" if hardhit is not None else "—",
            f"{k_mult:.2f}" if k_mult is not None else "—",
        ])
    return {
        "title": f"Opposing lineup Statcast approach vs {pitcher_label} (through {iso_date})",
        "columns": ["Batter", "xwOBA", "Barrel%", "HardHit%", "K mult"],
        "rows": rows,
    }


def _mlb_player_history_evidence(question: str, context: dict[str, Any]) -> dict[str, Any] | None:
    from syndicate.features.mlb.player_game_log import BATTER_LOG_FILENAME
    from syndicate.features.mlb.player_game_log import PITCHER_LOG_FILENAME

    words = _question_words(question)

    pitcher_match = _mlb_match_player_in_log(PITCHER_LOG_FILENAME, words, question)
    role = "pitcher" if pitcher_match else None
    match = pitcher_match
    if match is None:
        match = _mlb_match_player_in_log(BATTER_LOG_FILENAME, words, question)
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
        stat_key, stat_y_label, stat_phrase = _mlb_pitcher_chart_stat(words)
        charts.append({
            "type": "bar",
            "title": f"Actual {stat_phrase} — last {count} starts — {label}",
            "x_label": "Start date",
            "y_label": stat_y_label,
            "points": [{"x": str(r.get("date") or "")[5:], "y": float(r.get(stat_key) or 0)} for r in chronological],
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

    if role == "pitcher":
        lineup_table = _mlb_opposing_lineup_statcast_table(question, context, label)
        if lineup_table:
            tables.append(lineup_table)

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
# NCAAF
# ---------------------------------------------------------------------------


def _ncaaf_processed_csv_rows(subdir: str, filename: str) -> list[dict[str, Any]]:
    path = os.path.join(_syndicate_data_root(), "ncaaf_source", "source_artifacts", "data", "processed", subdir, filename)
    try:
        with open(path, "r", encoding="utf-8", newline="") as handle:
            return [dict(row) for row in csv.DictReader(handle)]
    except Exception:
        return []


def _ncaaf_team_registry_rows() -> list[dict[str, Any]]:
    return _ncaaf_processed_csv_rows("team_registry", "ncaaf_team_registry.csv")


def _ncaaf_teams_in_question(question: str) -> list[dict[str, Any]]:
    """Registry rows whose school/display name is plausibly referenced by
    the question.

    Deliberately NOT _name_matches (word-set overlap) -- real bug hit
    while testing this live: with ~680 FBS/FCS schools in the registry,
    dozens share a common word ("State", "Tech", "A&M"), so "Kansas State
    vs Iowa State" word-overlap-matched every "* State" school in the
    registry (Adams State, Alabama State, ...) instead of just the two
    actually named. Requires the FULL normalized school/display name as a
    contiguous phrase in the normalized question instead -- multi-word
    names can only match their own exact phrase this way. mascot_name/
    abbreviation are excluded entirely: mascots ("Wildcats", "Tigers") are
    shared by dozens of schools and abbreviations are too short (2-4
    letters) to be a safe substring match. Deduped by team_id, longest
    name matched first so a longer specific name (e.g. "Ohio State") is
    tried before a shorter substring of it could coincidentally match
    something else.
    """
    normalized_question = f" {_normalize_ncaaf_name(question)} "
    candidates: list[tuple[str, dict[str, Any]]] = []
    for row in _ncaaf_team_registry_rows():
        for field in ("school_name", "display_name"):
            name = row.get(field)
            if not name:
                continue
            normalized_name = _normalize_ncaaf_name(name)
            # >=3, not >=4: several real FBS school_name values ARE short
            # acronyms (TCU, USC, SMU, BYU, LSU) -- confirmed live that a
            # >=4 cutoff silently excluded TCU entirely, turning "North
            # Carolina vs TCU" into a single-team (no-op) match. Safe at 3
            # because this still requires the bounded whole-word/whole-
            # phrase substring match below, not a loose word-overlap check.
            if len(normalized_name) < 3:
                continue
            candidates.append((normalized_name, row))
    seen: set[str] = set()
    matches: list[dict[str, Any]] = []
    for normalized_name, row in sorted(candidates, key=lambda item: len(item[0]), reverse=True):
        team_id = str(row.get("team_id") or "").strip()
        if not team_id or team_id in seen:
            continue
        if f" {normalized_name} " in normalized_question:
            seen.add(team_id)
            matches.append(row)
    return matches[:4]


def _ncaaf_first_row_for_team(rows: list[dict[str, Any]], *, team_id: str, season: int) -> dict[str, Any] | None:
    season_text = str(season)
    fallback: dict[str, Any] | None = None
    for row in rows:
        if str(row.get("team_id") or "").strip() != team_id:
            continue
        if fallback is None:
            fallback = row
        if str(row.get("season") or "").strip() == season_text:
            return row
    return fallback


def _ncaaf_latest_csv_season(rows: list[dict[str, Any]]) -> int | None:
    """Most recent season actually present in a processed CSV.

    Deliberately NOT sources.default_season() (which tracks the recommendation-
    summary artifact's season, currently 2025) -- confirmed live that these
    team-context CSVs (coach continuity, returning production, roster) only
    ever carry season 2025 rows even though the live game slate has already
    moved on to 2026 (cards.py's own _team_context, called with the active
    2026 season, returns "Coach continuity unavailable"/empty for every team
    today -- a real, separate, pre-existing pipeline gap, not something to
    paper over here). Reading the season straight off the data means this
    fetcher keeps working, unchanged, whenever that pipeline catches up.
    """
    seasons = [int(row["season"]) for row in rows if str(row.get("season") or "").strip().isdigit()]
    return max(seasons) if seasons else None


def _ncaaf_team_profile_evidence(question: str, context: dict[str, Any]) -> dict[str, Any] | None:
    """Coach continuity, returning production, transfer-portal activity, and
    roster size for a team named in the question -- reads the same four
    processed CSVs syndicate/features/ncaaf/cards.py's _team_context reads,
    directly (this module never imports sport feature modules; every other
    section here reads its own artifacts the same way)."""
    teams = _ncaaf_teams_in_question(question)
    if not teams:
        return None
    team = teams[0]
    team_id = str(team.get("team_id") or "").strip()
    team_name = str(team.get("school_name") or team.get("display_name") or "").strip()
    returning_rows = _ncaaf_processed_csv_rows("returning_production", "ncaaf_returning_production_snapshot.csv")
    season = _ncaaf_latest_csv_season(returning_rows)
    if season is None:
        return None

    returning = _ncaaf_first_row_for_team(returning_rows, team_id=team_id, season=season) or {}
    coach = _ncaaf_first_row_for_team(_ncaaf_processed_csv_rows("coach_continuity", "ncaaf_coach_continuity_snapshot.csv"), team_id=team_id, season=season) or {}
    transfers = _ncaaf_processed_csv_rows("transfers", "ncaaf_transfer_portal_snapshot.csv")
    incoming = sum(1 for row in transfers if str(row.get("destination_team_id") or "").strip() == team_id and str(row.get("season") or "").strip() == str(season))
    outgoing = sum(1 for row in transfers if str(row.get("origin_team_id") or "").strip() == team_id and str(row.get("season") or "").strip() == str(season))
    roster = _ncaaf_processed_csv_rows("roster", "ncaaf_roster_snapshot.csv")
    active_roster_count = sum(1 for row in roster if str(row.get("team_id") or "").strip() == team_id and str(row.get("season") or "").strip() == str(season) and str(row.get("roster_status") or "").strip().lower() == "active")

    evidence = {
        "source": "ncaaf_team_profile",
        "team": team_name,
        "conference": team.get("conference"),
        "season": season,
        "head_coach": coach.get("head_coach_name"),
        "coach_tenure_years": _to_float(coach.get("coach_tenure_years")),
        "coach_continuity_score": _to_float(coach.get("continuity_score")),
        "coach_changed_this_season": str(coach.get("coach_changed") or "").strip() not in ("", "0", "false", "False"),
        "returning_starter_estimate": _to_float(returning.get("returning_starter_estimate")),
        "returning_production_percent_ppa": _to_float(returning.get("percent_ppa")),
        "transfers_in": incoming,
        "transfers_out": outgoing,
        "transfers_net": incoming - outgoing,
        "active_roster_count": active_roster_count,
    }
    table = {
        "title": f"{team_name} team profile ({season})",
        "columns": ["Metric", "Value"],
        "rows": [
            ["Head coach", evidence["head_coach"] or "-"],
            ["Coach tenure (years)", evidence["coach_tenure_years"]],
            ["Coach continuity score", evidence["coach_continuity_score"]],
            ["Coaching change this season", "Yes" if evidence["coach_changed_this_season"] else "No"],
            ["Returning starter estimate", evidence["returning_starter_estimate"]],
            ["Returning production (% PPA)", evidence["returning_production_percent_ppa"]],
            ["Transfers in / out / net", f"{incoming} / {outgoing} / {incoming - outgoing}"],
            ["Active roster size", active_roster_count],
        ],
    }
    return {"evidence": evidence, "tables": [table], "charts": [], "as_of": f"{season} season", "sport": "ncaaf"}


def _ncaaf_matchup_projection_evidence(question: str, context: dict[str, Any]) -> dict[str, Any] | None:
    """SmartSim 2.0's own projection plus the real market line for a
    scheduled matchup between two teams named in the question. Searches
    across the season's weeks for a projection naming both teams, rather
    than assuming "this week", since a question may reference any
    scheduled game."""
    from syndicate.features.ncaaf.cards import _resolve_ncaaf_active_season_and_weeks
    from syndicate.features.ncaaf.sources import default_ncaaf_source_root
    from syndicate.features.ncaaf.smartsim2_projection import read_projection_artifact

    teams = _ncaaf_teams_in_question(question)
    if len(teams) < 2:
        return None
    team_a_names = {_normalize_ncaaf_name(v) for v in (teams[0].get("school_name"), teams[0].get("display_name")) if v}
    team_b_names = {_normalize_ncaaf_name(v) for v in (teams[1].get("school_name"), teams[1].get("display_name")) if v}

    # The active season (this week's real slate) is tried first, then the
    # prior season as a fallback for a question about an already-completed
    # matchup -- confirmed live that sources.default_season() (which tracks
    # a different, stale artifact) can disagree with the season the actual
    # game board is on, so this resolves the same way cards.py's own
    # /ncaaf/cards route does rather than via that separate accessor.
    active_season, _weeks = _resolve_ncaaf_active_season_and_weeks()
    data_root = default_ncaaf_source_root() / "data"
    projection = None
    season = None
    week = None
    for candidate_season in (active_season, active_season - 1):
        for candidate_week in range(1, 21):
            for row in read_projection_artifact(season=candidate_season, week=candidate_week, data_root=data_root):
                home_norm = _normalize_ncaaf_name(row.home_team)
                away_norm = _normalize_ncaaf_name(row.away_team)
                if (home_norm in team_a_names and away_norm in team_b_names) or (home_norm in team_b_names and away_norm in team_a_names):
                    projection = row
                    season = candidate_season
                    week = candidate_week
                    break
            if projection is not None:
                break
        if projection is not None:
            break
    if projection is None:
        return None

    market_margin = None
    market_total = None
    lines_path = data_root / f"cfbd_lines_{season}_wk{week}.json"
    try:
        with lines_path.open("r", encoding="utf-8") as handle:
            games = json.load(handle)
        for game in games:
            if not isinstance(game, dict):
                continue
            if _normalize_ncaaf_name(game.get("homeTeam")) != _normalize_ncaaf_name(projection.home_team):
                continue
            if _normalize_ncaaf_name(game.get("awayTeam")) != _normalize_ncaaf_name(projection.away_team):
                continue
            lines = game.get("lines") if isinstance(game.get("lines"), list) else []
            spreads = [line["spread"] for line in lines if isinstance(line, dict) and line.get("spread") is not None]
            totals = [line["overUnder"] for line in lines if isinstance(line, dict) and line.get("overUnder") is not None]
            if spreads:
                market_margin = -(sum(spreads) / len(spreads))
            if totals:
                market_total = sum(totals) / len(totals)
            break
    except Exception:
        pass

    evidence = {
        "source": "ncaaf_smartsim2_projection",
        "season": season,
        "week": week,
        "home_team": projection.home_team,
        "away_team": projection.away_team,
        "model_home_points": round(projection.home_score_mean, 1),
        "model_away_points": round(projection.away_score_mean, 1),
        "model_margin": round(projection.margin_mean, 1),
        "model_total": round(projection.total_mean, 1),
        "model_home_win_probability": round(projection.home_win_rate, 3),
        "market_margin": market_margin,
        "market_total": market_total,
    }
    table = {
        "title": f"{projection.away_team} @ {projection.home_team} — Week {week} projection",
        "columns": ["Metric", "Model", "Market"],
        "rows": [
            ["Home margin", evidence["model_margin"], market_margin],
            ["Total points", evidence["model_total"], market_total],
            ["Home win probability", evidence["model_home_win_probability"], None],
        ],
    }
    return {"evidence": evidence, "tables": [table], "charts": [], "as_of": f"{season} week {week}", "sport": "ncaaf"}


def _normalize_ncaaf_name(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = text.replace("&", " and ")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", text)).strip()


def _ncaaf_ats_evidence(question: str, context: dict[str, Any]) -> dict[str, Any] | None:
    """A team's real against-the-spread record this season, computed
    directly from smartsim2_performance_log.jsonl's market_margin/
    actual_margin pairs -- independent of any model pick, the same
    "what would a neutral bettor have seen" record a sportsbook history
    page would show."""
    from syndicate.features.ncaaf.sources import default_ncaaf_source_root

    teams = _ncaaf_teams_in_question(question)
    if not teams:
        return None
    team = teams[0]
    team_name = str(team.get("school_name") or team.get("display_name") or "").strip()
    team_norm = _normalize_ncaaf_name(team_name)

    log_path = default_ncaaf_source_root() / "data" / "smartsim2_performance_log.jsonl"
    covers = losses = pushes = 0
    games: list[dict[str, Any]] = []
    try:
        with log_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                home_norm = _normalize_ncaaf_name(row.get("home_team"))
                away_norm = _normalize_ncaaf_name(row.get("away_team"))
                is_home = home_norm == team_norm
                is_away = away_norm == team_norm
                if not is_home and not is_away:
                    continue
                market_margin = _to_float(row.get("market_margin"))
                actual_margin = _to_float(row.get("actual_margin"))
                if market_margin is None or actual_margin is None:
                    continue
                team_line = market_margin if is_home else -market_margin
                team_actual = actual_margin if is_home else -actual_margin
                if team_actual > team_line:
                    covers += 1
                    result = "cover"
                elif team_actual < team_line:
                    losses += 1
                    result = "loss"
                else:
                    pushes += 1
                    result = "push"
                games.append({
                    "opponent": row.get("away_team") if is_home else row.get("home_team"),
                    "week": row.get("week"),
                    "line": team_line,
                    "actual_margin": team_actual,
                    "result": result,
                })
    except Exception:
        return None
    if not games:
        return None
    table = {
        "title": f"{team_name} against the spread this season",
        "columns": ["Week", "Opponent", "Line", "Actual margin", "Result"],
        "rows": [[g["week"], g["opponent"], g["line"], g["actual_margin"], g["result"]] for g in games],
    }
    evidence = {
        "source": "ncaaf_smartsim2_performance_log",
        "team": team_name,
        "ats_record": {"covers": covers, "losses": losses, "pushes": pushes},
    }
    return {"evidence": evidence, "tables": [table], "charts": [], "as_of": "season to date", "sport": "ncaaf"}


# ---------------------------------------------------------------------------
# NFL
# ---------------------------------------------------------------------------


def _nfl_team_branding_rows() -> list[dict[str, Any]]:
    path = os.path.join(_syndicate_data_root(), "nfl_source", "source_artifacts", "data", "processed", "team_branding", "nfl_team_branding.csv")
    try:
        with open(path, "r", encoding="utf-8", newline="") as handle:
            return [dict(row) for row in csv.DictReader(handle)]
    except Exception:
        return []


def _nfl_teams_in_question(question: str) -> list[str]:
    """Real full team names (e.g. "Kansas City Chiefs") plausibly referenced
    by the question -- bounded whole-phrase substring match, same approach
    _ncaaf_teams_in_question uses (and for the same reason: NFL team names
    are always City/State + Mascot, so no NCAAF-style shared-word collision
    risk, but a plain word-set overlap check would still be needlessly
    fragile). Only 32 real teams, so no short-acronym edge case either."""
    normalized_question = f" {_normalize_ncaaf_name(question)} "
    names = sorted(
        {str(row.get("display_name") or "").strip() for row in _nfl_team_branding_rows() if row.get("display_name")},
        key=len,
        reverse=True,
    )
    matches: list[str] = []
    for name in names:
        normalized_name = _normalize_ncaaf_name(name)
        if len(normalized_name) < 3:
            continue
        if f" {normalized_name} " in normalized_question and name not in matches:
            matches.append(name)
    return matches[:4]


def _nfl_real_lines_for_matchup(season: int, *, away_full_name: str, home_full_name: str) -> dict[str, Any] | None:
    pattern = os.path.join(_syndicate_data_root(), "nfl_source", f"real_betting_lines_{season}_*.json")
    key = f"{away_full_name} @ {home_full_name}"
    for path in sorted(glob.glob(pattern)):
        try:
            with open(path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except Exception:
            continue
        lines = payload.get("lines") if isinstance(payload, dict) else None
        if isinstance(lines, dict) and key in lines:
            return lines[key]
    return None


def _nfl_projection_weeks(season: int) -> list[int]:
    pattern = os.path.join(_syndicate_data_root(), "nfl_source", f"smartsim2_projections_{season}_wk*.csv")
    weeks: list[int] = []
    for path in glob.glob(pattern):
        match = re.search(r"_wk(\d+)\.csv$", path)
        if match:
            weeks.append(int(match.group(1)))
    return sorted(set(weeks))


def _nfl_matchup_evidence(question: str, context: dict[str, Any]) -> dict[str, Any] | None:
    """Real SmartSim 2.0 projection (scripts/generate_smartsim2_nfl_projections.py)
    plus the real market line for a scheduled matchup between two teams
    named in the question. Searches every week that actually has a
    generated projection artifact -- there's no single "current week"
    concept to assume here any more than there was for NCAAF."""
    from syndicate.features.nfl.smartsim2_projection import read_projection_artifact
    from syndicate.features.nfl.sources import default_nfl_source_root
    from syndicate.features.nfl.sources import latest_season

    teams = _nfl_teams_in_question(question)
    if len(teams) < 2:
        return None
    team_a = _normalize_ncaaf_name(teams[0])
    team_b = _normalize_ncaaf_name(teams[1])

    season = latest_season()
    data_root = default_nfl_source_root()
    projection = None
    week = None
    for candidate_week in _nfl_projection_weeks(season):
        for row in read_projection_artifact(season=season, week=candidate_week, data_root=data_root):
            home_norm = _normalize_ncaaf_name(row.home_team)
            away_norm = _normalize_ncaaf_name(row.away_team)
            # Projection rows carry short team codes ("KC"), not the full
            # names matched above -- compare via containment either way
            # since a code is always a substring/prefix relationship isn't
            # guaranteed, so match on whichever of the two identified full
            # names' branding row resolves to this code instead.
            home_full = _nfl_code_to_full_name(row.home_team)
            away_full = _nfl_code_to_full_name(row.away_team)
            if {_normalize_ncaaf_name(home_full), _normalize_ncaaf_name(away_full)} == {team_a, team_b}:
                projection = row
                week = candidate_week
                break
        if projection is not None:
            break
    if projection is None:
        return None

    home_full_name = _nfl_code_to_full_name(projection.home_team)
    away_full_name = _nfl_code_to_full_name(projection.away_team)
    lines_entry = _nfl_real_lines_for_matchup(season, away_full_name=away_full_name, home_full_name=home_full_name) or {}
    moneyline = lines_entry.get("moneyline") or {}
    run_line = lines_entry.get("run_line") or {}
    total_runs = lines_entry.get("total_runs") or {}

    evidence = {
        "source": "nfl_smartsim2_projection",
        "season": season,
        "week": week,
        "home_team": home_full_name,
        "away_team": away_full_name,
        "model_home_points": round(projection.home_score_mean, 1),
        "model_away_points": round(projection.away_score_mean, 1),
        "model_margin": round(projection.margin_mean, 1),
        "model_total": round(projection.total_mean, 1),
        "model_home_win_probability": round(projection.home_win_rate, 3),
        "market_home_moneyline": moneyline.get("home"),
        "market_away_moneyline": moneyline.get("away"),
        "market_spread": run_line.get("home"),
        "market_total": total_runs.get("line"),
    }
    table = {
        "title": f"{away_full_name} @ {home_full_name} — Week {week} projection",
        "columns": ["Metric", "Model", "Market"],
        "rows": [
            ["Home margin", evidence["model_margin"], evidence["market_spread"]],
            ["Total points", evidence["model_total"], evidence["market_total"]],
            ["Home win probability", evidence["model_home_win_probability"], None],
            ["Home moneyline", None, evidence["market_home_moneyline"]],
            ["Away moneyline", None, evidence["market_away_moneyline"]],
        ],
    }
    return {"evidence": evidence, "tables": [table], "charts": [], "as_of": f"{season} week {week}", "sport": "nfl"}


def _nfl_code_to_full_name(code: str) -> str:
    for row in _nfl_team_branding_rows():
        if str(row.get("abbreviation") or "").strip().upper() == str(code or "").strip().upper():
            return str(row.get("display_name") or code).strip()
    return str(code or "").strip()


def _nfl_completed_games_for_team(team_full_name: str, season: int) -> list[dict[str, Any]]:
    """Real completed games for one team this season, with real final
    scores -- read directly from nflverse play-by-play (the first row per
    game_id already carries home_team/away_team/home_score/away_score,
    constant for the whole game, so no need to scan to the end of each
    game). No performance-log equivalent exists for NFL (unlike NCAAF's
    smartsim2_performance_log.jsonl) -- this derives the same real
    information straight from the raw data."""
    path = os.path.join(_syndicate_data_root(), "nfl_source", "tracking", "nflverse", "pbp", f"pbp_{season}.csv")
    team_code = None
    for row in _nfl_team_branding_rows():
        if _normalize_ncaaf_name(row.get("display_name")) == _normalize_ncaaf_name(team_full_name):
            team_code = str(row.get("abbreviation") or "").strip().upper()
            break
    if not team_code:
        return []
    games: dict[str, dict[str, Any]] = {}
    try:
        with open(path, "r", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                if row.get("season_type") != "REG":
                    continue
                game_id = (row.get("game_id") or "").strip()
                if not game_id or game_id in games:
                    continue
                home_team = (row.get("home_team") or "").strip()
                away_team = (row.get("away_team") or "").strip()
                if team_code not in (home_team, away_team):
                    continue
                try:
                    home_score = float(row.get("home_score") or "")
                    away_score = float(row.get("away_score") or "")
                    week = int(row.get("week") or 0)
                except (TypeError, ValueError):
                    continue
                games[game_id] = {"home_team": home_team, "away_team": away_team, "home_score": home_score, "away_score": away_score, "week": week, "team_code": team_code}
    except Exception:
        return []
    return list(games.values())


def _nfl_latest_snapshot_rows(subdir: str, filename_prefix: str) -> tuple[int | None, list[dict[str, Any]]]:
    """Real rows from the most recent season's `{filename_prefix}_{season}_snapshot.csv`
    (roster_snapshot_builder.py / depth_chart_snapshot_builder.py's own real
    naming convention -- season-parameterized, not fixed to any one year).
    Globs rather than hardcoding a season, same reason as _nfl_projection_weeks:
    this module deliberately never imports sport feature modules, so it can't
    just ask nfl.sources.latest_season() -- every section here reads its own
    artifacts directly."""
    pattern = os.path.join(_syndicate_data_root(), "nfl_source", "source_artifacts", "data", "processed", subdir, f"{filename_prefix}_*_snapshot.csv")
    seasons: dict[int, str] = {}
    for path in glob.glob(pattern):
        match = re.search(rf"{filename_prefix}_(\d{{4}})_snapshot\.csv$", os.path.basename(path))
        if match:
            seasons[int(match.group(1))] = path
    if not seasons:
        return None, []
    latest = max(seasons)
    try:
        with open(seasons[latest], "r", encoding="utf-8", newline="") as handle:
            return latest, [dict(row) for row in csv.DictReader(handle)]
    except Exception:
        return latest, []


def _nfl_injury_report_count(team_code: str, season: int) -> int:
    path = os.path.join(_syndicate_data_root(), "nfl_source", "tracking", "nflverse", "injuries", f"injuries_{season}.csv")
    count = 0
    try:
        with open(path, "r", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                if str(row.get("team") or "").strip().upper() == team_code:
                    if str(row.get("report_status") or "").strip():
                        count += 1
    except Exception:
        return 0
    return count


def _nfl_team_profile_evidence(question: str, context: dict[str, Any]) -> dict[str, Any] | None:
    """Real roster size, depth-chart starter count, and current-season
    injury-report count for a team named in the question -- reads the same
    real nflverse-backed snapshot CSVs syndicate.features.football.ingestion
    writes (roster_snapshot_builder.py / depth_chart_snapshot_builder.py),
    directly (this module never imports sport feature modules). No
    coach-continuity/returning-production/transfer-portal equivalent exists
    for NFL (those are NCAAF/CFBD-specific concepts), so this is real NFL
    roster/depth/injury data, not a re-shaped copy of NCAAF's team profile."""
    teams = _nfl_teams_in_question(question)
    if not teams:
        return None
    team_name = teams[0]
    team_code = None
    for row in _nfl_team_branding_rows():
        if _normalize_ncaaf_name(row.get("display_name")) == _normalize_ncaaf_name(team_name):
            team_code = str(row.get("abbreviation") or "").strip().upper()
            break
    if not team_code:
        return None

    roster_season, roster_rows = _nfl_latest_snapshot_rows("rosters", "roster")
    depth_season, depth_rows = _nfl_latest_snapshot_rows("depth", "depth")
    if roster_season is None and depth_season is None:
        return None

    team_roster = [row for row in roster_rows if str(row.get("team_abbr") or row.get("team") or "").strip().upper() == team_code]
    team_depth = [row for row in depth_rows if str(row.get("team") or "").strip().upper() == team_code]
    starters = sum(1 for row in team_depth if str(row.get("depth_rank") or "").strip() == "1")
    position_group_counts = Counter(str(row.get("position_group") or row.get("position") or "").strip() for row in team_roster if row.get("position_group") or row.get("position"))

    # 2026's own injury file is real but empty this preseason (no
    # practices/games yet) -- reporting 0 honestly rather than falling back
    # to a prior season and presenting it as "current."
    current_season = roster_season or depth_season
    injury_count = _nfl_injury_report_count(team_code, current_season) if current_season else 0

    evidence = {
        "source": "nfl_team_profile",
        "team": team_name,
        "season": current_season,
        "roster_count": len(team_roster),
        "depth_chart_starters": starters,
        "position_group_counts": dict(position_group_counts.most_common(6)),
        "current_season_injury_report_count": injury_count,
    }
    table = {
        "title": f"{team_name} team profile ({current_season})",
        "columns": ["Metric", "Value"],
        "rows": [
            ["Roster size", evidence["roster_count"]],
            ["Depth-chart starters listed", evidence["depth_chart_starters"]],
            ["Players on this week's injury report", evidence["current_season_injury_report_count"]],
            *[[f"{group} on roster", count] for group, count in position_group_counts.most_common(6)],
        ],
    }
    return {"evidence": evidence, "tables": [table], "charts": [], "as_of": f"{current_season} season" if current_season else "unknown season", "sport": "nfl"}


def _nfl_ats_evidence(question: str, context: dict[str, Any]) -> dict[str, Any] | None:
    """A team's real against-the-spread record this season, computed from
    real completed games (final scores from nflverse play-by-play) vs. the
    real closing market line (real_betting_lines_*.json) -- same
    perspective-flip cover/loss/push logic as _ncaaf_ats_evidence."""
    from syndicate.features.nfl.sources import latest_season

    teams = _nfl_teams_in_question(question)
    if not teams:
        return None
    team_full_name = teams[0]
    season = latest_season()
    completed_games = _nfl_completed_games_for_team(team_full_name, season)
    if not completed_games:
        return None

    covers = losses = pushes = 0
    rows: list[dict[str, Any]] = []
    for game in completed_games:
        is_home = game["home_team"] == game["team_code"]
        home_full = _nfl_code_to_full_name(game["home_team"])
        away_full = _nfl_code_to_full_name(game["away_team"])
        lines_entry = _nfl_real_lines_for_matchup(season, away_full_name=away_full, home_full_name=home_full) or {}
        market_margin = _to_float((lines_entry.get("run_line") or {}).get("home"))
        if market_margin is None:
            continue
        actual_margin = game["home_score"] - game["away_score"]
        team_line = market_margin if is_home else -market_margin
        team_actual = actual_margin if is_home else -actual_margin
        if team_actual > team_line:
            covers += 1
            result = "cover"
        elif team_actual < team_line:
            losses += 1
            result = "loss"
        else:
            pushes += 1
            result = "push"
        opponent = away_full if is_home else home_full
        rows.append({"week": game["week"], "opponent": opponent, "line": team_line, "actual_margin": team_actual, "result": result})

    if not rows:
        return None
    rows.sort(key=lambda r: r["week"])
    table = {
        "title": f"{team_full_name} against the spread this season",
        "columns": ["Week", "Opponent", "Line", "Actual margin", "Result"],
        "rows": [[r["week"], r["opponent"], r["line"], r["actual_margin"], r["result"]] for r in rows],
    }
    evidence = {
        "source": "nfl_pbp_vs_real_betting_lines",
        "team": team_full_name,
        "ats_record": {"covers": covers, "losses": losses, "pushes": pushes},
    }
    return {"evidence": evidence, "tables": [table], "charts": [], "as_of": f"{season} season to date", "sport": "nfl"}


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
    if sport == "ncaaf":
        return [_ncaaf_matchup_projection_evidence, _ncaaf_team_profile_evidence, _ncaaf_ats_evidence]
    if sport == "nfl":
        return [_nfl_matchup_evidence, _nfl_team_profile_evidence, _nfl_ats_evidence]
    if sport == "":
        if _is_ranking_intent_question(_question_words(question)):
            return [_mlb_top_candidates_evidence]
        # No sport hint: cheap fetchers only. This is the common case for a
        # typed question, not a rare fallback -- context.sport only gets set
        # from a `?sport=` URL query param or a recognized team/league
        # keyword in the question text (_infer_sport), so a plain player
        # name (e.g. "antony volpe bet analysis") never sets it. Confirmed
        # live (2026-07-31): this silently skipped _mlb_bvp_evidence
        # entirely for that exact question even after it was fixed to
        # resolve any batter/pitcher, because it was never in this list.
        # It belongs here alongside the other per-player MLB fetchers
        # already run unconditionally in this branch (_mlb_player_history_evidence
        # already matches an arbitrary player name with no sport hint) --
        # it's cheap on a non-match (name-matching short-circuits fast).
        # Same reasoning extends to NBA/NHL: _SPORT_HINTS keyword sets don't
        # cover every way of asking about a player (e.g. "How's Jokic
        # looking tonight" has no NBA keyword at all), so their per-player
        # fetchers belong here too, not just under their own sport branch.
        return [
            _mlb_accuracy_evidence,
            _mlb_focused_evidence,
            _mlb_player_history_evidence,
            _mlb_bvp_evidence,
            _wnba_focused_evidence,
            lambda q, c: _basketball_last10_evidence(q, c, "nba"),
            _nhl_last10_evidence,
            _ncaaf_matchup_projection_evidence,
            _ncaaf_team_profile_evidence,
            _ncaaf_ats_evidence,
            _nfl_matchup_evidence,
            _nfl_team_profile_evidence,
            _nfl_ats_evidence,
        ]
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
