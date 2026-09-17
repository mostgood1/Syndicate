"""NFL and NCAAF player-prop evidence.

NFL SOURCES (all allowlisted; measured on production web 2026-09-17):

    nfl_prop_projections_<season>_wk<week>.json
                                   sim_rows[] {game_id "Away Full|Home Full",
                                   market "receptions::jahmyr gibbs::4.5" | "anytime_td::<player>",
                                   sim_projection (P over), projected_value (mean), rate_source,
                                   sim_source, player_team}. ONLY wk1 exists (476,295 B, 09-10).
    fantasy/nfl_fantasy_projections_<season>.json
                                   players[] {id (gsis), name, team, pos, basis {target_share,
                                   carry_share, pass_share, depth_rank, availability, ...}},
                                   week_rows[week] / season_rows (PER-GAME means),
                                   week_opponents[week][player_id]
    schedule_<season>.csv          game_id, week, gameday/gametime (ET), away/home codes,
                                   scores, spread_line, total_line, moneylines, stadium
    smartsim2_projections_<season>_wk<week>.csv
                                   score/margin/total means + stdevs, home_win_rate, generated_at
    smartsim2_segment_distributions_<season>_wk<week>.json
                                   games[game_id].segments.full.{total_points_dist, margin_dist}
    tracking/nflverse/injuries/injuries_<season>.csv
                                   week, team, gsis_id, full_name, position, report_status
    fantasy/nfl_fantasy_usage_<season>.json
                                   player_game_lines[] -- per-game box lines. ALLOWLISTED BUT
                                   ZERO FILES ON PRODUCTION WEB (2026-09-17), so recent form is a
                                   named `artifact_missing` there until the worker publishes it.

**THE WEEK IS THE GAME'S, NOT THE NEWEST FILE'S.** `nfl_prop_projections.py`
falls back to the newest prop artifact and records that only in
`index.resolution`, so every week-2 board row carries week-1 prices with nothing
on the row saying so. The week here comes from `schedule_<season>.csv` (ET date +
both clubs), and a prop file for any other week is shown with a STALE row.

**A PROP P(over) IS NOT A SIMULATED DRAW.** `nfl/props.py` prices it from the
player's rate mean and stdev through a per-market Normal/log-normal blend. The
table says so beside the number. The stdev and sample size it used are not
written to the artifact; the row reads `projected_sd`/`sample_games` if a later
producer adds them and otherwise says "not published".

**THE OPPORTUNITY ENGINE ADJUSTS TDs ONLY.** Measured over all 8,738 week rows of
`nfl_fantasy_projections_2026.json`: a week row differs from the season row on
TD, 2-pt, kicking and D/ST columns and on NOTHING else -- yards, receptions and
attempts are identical. The matchup table states that rather than presenting
an unchanged number as an opponent adjustment.

NCAAF SOURCES (all allowlisted; measured 2026-09-17):

    processed/player_game_stats/ncaaf_player_game_stats_snapshot.csv
                                   CFBD per-player per-game box lines (weeks 1-2 of 2026)
    week_state/ncaaf_week_state_<season>.json
                                   unplayed_kickoffs[week].last -- places a kickoff in a week
    smartsim2_projections_<season>_wk<week>.csv / smartsim2_segment_distributions_...json

NO NCAAF PLAYER PROJECTION IS PUBLISHED, and web does not model:
`syndicate/features/ncaaf/prop_model.py` exists and is deliberately NOT called
here, so `player_sim` is a named `no_producer` absence. Team names resolve
through `ncaaf.oddsapi_lines.resolve_team` -- the validated resolver the board
join uses -- never a mascot match (~680 schools share mascots).

HOME/AWAY CAN DISAGREE BETWEEN THE BOARD AND THE MODEL. Measured 2026-09-17:
the board serves "Virginia Cavaliers @ West Virginia Mountaineers" while CFBD's
wk3 projection has home=Virginia. Same two teams in the same week (NCAAF) or on
the same date (NFL) is the same fixture, so it is joined, and a HOME/AWAY
DISAGREE row says so rather than the layer going silently empty.

EVERY READ IS ONE FILE PER FAMILY, nothing parsed is cached. The bounded
exceptions (the prior-season usage document, the neighbouring NCAAF projection
weeks on a miss) are named where they happen.
"""

from __future__ import annotations

import glob
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

from syndicate.features.shared.prop_evidence import common as C
from syndicate.features.shared.prop_evidence.contract import (
    ABSENT_NO_ARTIFACT,
    ABSENT_NO_MATCH,
    ABSENT_NO_PRODUCER,
    ABSENT_NOT_APPLICABLE,
    Layer,
    LayerEvidence,
    PropEvidence,
    PropSubject,
    absent,
    chart,
    table,
)
from syndicate.features.shared.prop_evidence.track_record import build_track_record

logger = logging.getLogger(__name__)

NFL_DIR = "nfl_source"
NCAAF_DIR = "ncaaf_source"

# lowercased board market -> (stat key, label). Display names are what the board
# serves; the raw OddsAPI keys are accepted because a producer has served them
# before (24 `player_receptions` rows, `nfl_prop_projections.py`).
MARKETS: dict[str, tuple[str, str]] = {
    "passing yards": ("passing_yards", "Passing yards"),
    "passing attempts": ("passing_attempts", "Passing attempts"),
    "passing tds": ("passing_tds", "Passing TDs"),
    "interceptions": ("interceptions", "Interceptions"),
    "rushing yards": ("rushing_yards", "Rushing yards"),
    "rushing attempts": ("rushing_attempts", "Rushing attempts"),
    "receptions": ("receptions", "Receptions"),
    "receiving yards": ("receiving_yards", "Receiving yards"),
    "anytime td": ("anytime_td", "Anytime TD"),
    "player_pass_yds": ("passing_yards", "Passing yards"),
    "player_pass_attempts": ("passing_attempts", "Passing attempts"),
    "player_pass_tds": ("passing_tds", "Passing TDs"),
    "player_pass_interceptions": ("interceptions", "Interceptions"),
    "player_rush_yds": ("rushing_yards", "Rushing yards"),
    "player_rush_attempts": ("rushing_attempts", "Rushing attempts"),
    "player_receptions": ("receptions", "Receptions"),
    "player_reception_yds": ("receiving_yards", "Receiving yards"),
    "player_anytime_td": ("anytime_td", "Anytime TD"),
}

# stat -> columns summed, per source. anytime_td is an EVENT (>= 1 TD), derived
# from the rushing + receiving TD columns; return/fumble TDs are not in either.
NFL_FANTASY_COLUMNS: dict[str, tuple[str, ...]] = {
    "passing_yards": ("passing_yards",),
    "passing_attempts": ("pass_attempts",),
    "passing_tds": ("passing_tds",),
    "interceptions": ("interceptions",),
    "rushing_yards": ("rushing_yards",),
    "rushing_attempts": ("carries",),
    "receptions": ("receptions",),
    "receiving_yards": ("receiving_yards",),
    "anytime_td": ("rushing_tds", "receiving_tds"),
}
NFL_USAGE_COLUMNS: dict[str, tuple[str, ...]] = {
    "passing_yards": ("pass_yards",),
    "passing_attempts": ("pass_attempts",),
    "passing_tds": ("pass_tds",),
    "interceptions": ("interceptions",),
    "rushing_yards": ("rush_yards",),
    "rushing_attempts": ("carries",),
    "receptions": ("receptions",),
    "receiving_yards": ("rec_yards",),
    "anytime_td": ("rush_tds", "rec_tds"),
}
# The volume column shown beside the stat.
NFL_USAGE_VOLUME: dict[str, tuple[str, str]] = {
    "passing_yards": ("pass_attempts", "Att"), "passing_attempts": ("pass_completions", "Cmp"),
    "passing_tds": ("pass_attempts", "Att"), "interceptions": ("pass_attempts", "Att"),
    "rushing_yards": ("carries", "Car"), "rushing_attempts": ("rush_yards", "Rush yds"),
    "receptions": ("targets", "Tgt"), "receiving_yards": ("targets", "Tgt"), "anytime_td": ("targets", "Tgt"),
}
NCAAF_COLUMNS = ("passing_attempts", "passing_yards", "passing_tds", "interceptions", "rushing_attempts",
                 "rushing_yards", "receptions", "receiving_yards", "anytime_td")
NCAAF_VOLUME: dict[str, tuple[str, str]] = {
    "passing_yards": ("passing_attempts", "Att"), "passing_attempts": ("passing_yards", "Pass yds"),
    "passing_tds": ("passing_attempts", "Att"), "interceptions": ("passing_attempts", "Att"),
    "rushing_yards": ("rushing_attempts", "Att"), "rushing_attempts": ("rushing_yards", "Rush yds"),
    "receptions": ("receiving_yards", "Rec yds"), "receiving_yards": ("receptions", "Rec"),
    "anytime_td": ("receptions", "Rec"),
}

STALE_GAME_PROJECTION_DAYS = 7


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _name_keys(value: Any) -> tuple[str, str, str]:
    """(name_key, without suffixes, with one-letter initials joined) from ONE normalisation.

    The third form is what `common.names_match` lacks: "D.J. Moore" normalises
    to `d j moore` and never meets the board's "DJ Moore".
    """
    key = C.name_key(value)
    loose_tokens = [t for t in key.split() if t not in C._NAME_SUFFIXES]
    joined: list[str] = []
    run = ""
    for token in loose_tokens:
        if len(token) == 1:
            run += token
            continue
        if run:
            joined.append(run)
            run = ""
        joined.append(token)
    if run:
        joined.append(run)
    return key, " ".join(loose_tokens), " ".join(joined)


class NameMatcher:
    """`common.names_match` against ONE subject name, fast enough for a full-file scan.

    A per-row `names_match` normalises both names twice; over the 8,115-row
    NCAAF snapshot that was 2.0 s per Ask (profiled 2026-09-17), and the file
    grows by ~4,000 rows a week. The subject is normalised once, each distinct
    row name at most once, and an ASCII row name that does not contain the
    subject's last name is rejected without normalising at all -- every token of
    `name_key(ascii)` is a substring of the lowercased name with apostrophes
    removed, so that rejection can never drop a real match.
    """

    def __init__(self, name: Any) -> None:
        self.keys = _name_keys(name)
        tokens = self.keys[1].split()
        self.last = tokens[-1] if tokens and len(tokens[-1]) > 1 else ""
        self.memo: dict[str, bool] = {}

    def __call__(self, raw: Any) -> bool:
        text = str(raw or "")
        hit = self.memo.get(text)
        if hit is not None:
            return hit
        if self.last and text.isascii() and self.last not in text.lower().replace("'", ""):
            hit = False
        else:
            other = _name_keys(text)
            hit = bool(self.keys[0]) and bool(other[0]) and (
                self.keys[0] == other[0] or self.keys[1] == other[1] or self.keys[2] == other[2])
        self.memo[text] = hit
        return hit


def names_match(a: Any, b: Any) -> bool:
    """`common.names_match`, plus "DJ Moore" == "D.J. Moore" (board vs nflverse spelling)."""
    return NameMatcher(a)(b)


def _norm_side(side: str | None) -> str:
    return "under" if side in {"under", "no"} else "over"


def _line_for(subject: PropSubject, stat: str | None) -> float | None:
    """The board line; an anytime-TD row has none, and its event is >= 1 TD."""
    if subject.line is not None:
        return subject.line
    return 0.5 if stat == "anytime_td" else None


def _season(subject: PropSubject) -> int | None:
    """A football season is named for the year it starts; Jan/Feb belong to the previous one."""
    text = _et_date(subject) or subject.selected_date
    try:
        year, month = int(text[:4]), int(text[5:7])
    except (ValueError, IndexError):
        return None
    return year - 1 if month <= 2 else year


def _et_date(subject: PropSubject) -> str:
    from syndicate.features.shared.nfl_game_projections import schedule_date_key

    return schedule_date_key(subject.commence_time) if subject.commence_time else subject.selected_date


def _parse_ts(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _kickoff_et(subject: PropSubject) -> str:
    moment = _parse_ts(subject.commence_time)
    if moment is None:
        return subject.selected_date or "—"
    from syndicate.features.shared.nfl_game_projections import SCHEDULE_TIMEZONE

    return moment.astimezone(SCHEDULE_TIMEZONE).strftime("%a %Y-%m-%d %H:%M ET")


def _days_between(earlier: str, later: str) -> int | None:
    try:
        return (datetime.fromisoformat(later[:10]) - datetime.fromisoformat(earlier[:10])).days
    except ValueError:
        return None


def _sum_columns(row: dict[str, Any], columns: tuple[str, ...], *, event: bool = False) -> float | None:
    values = [C.to_float(row.get(col)) for col in columns]
    if any(v is None for v in values):
        return None
    total = float(sum(values))  # type: ignore[arg-type]
    return (1.0 if total > 0 else 0.0) if event else total


def _week_label(season: Any, week: Any) -> str:
    try:
        return f"{int(season) % 100:02d}-W{int(week)}"
    except (TypeError, ValueError):
        return f"W{week}"


def _form_chart(points: list[tuple[str, float | None]], *, label: str, player: str, line: float | None,
                layer: Layer = Layer.RECENT_FORM) -> dict[str, Any] | None:
    """Chronological bar chart of the stat per game with the board line marked."""
    clean = [{"x": x, "y": y} for x, y in points if y is not None]
    if not clean:
        return None
    marker = {"y": line, "label": f"Line {C.fmt_line(line)}"} if line is not None else None
    return chart(f"{label} by game — {player} (last {len(clean)})", "Game", label, clean, layer, marker=marker)


def _load(path: Path | None, what: str) -> Any:
    if path is None:
        return None
    try:
        return C.load_json(path)
    except Exception:
        logger.exception("prop_evidence football: unreadable %s %s", what, path)
        return None


def _read_csv(path: Path | None, what: str) -> list[dict[str, str]]:
    if path is None:
        return []
    try:
        return list(C.iter_csv(path))
    except Exception:
        logger.exception("prop_evidence football: unreadable %s %s", what, path)
        return []


def _glob_weeks(local_dir: str, pattern: str) -> dict[int, Path]:
    """week -> path, across both roots, for a `..._wk*.<ext>` family (first root wins)."""
    found: dict[int, Path] = {}
    for root in C.sport_roots(local_dir):
        for raw in glob.glob(str(root / pattern)):
            match = re.search(r"_wk(\d+)\.[a-z]+$", raw)
            if match:
                found.setdefault(int(match.group(1)), Path(raw))
    return found


RUN_MISMATCH_POINTS = 0.5


def _run_mismatch(projection_row: dict[str, Any], full: dict[str, Any]) -> str | None:
    """A warning when the distribution file and the projection CSV are not the same run.

    Judged on the OUTPUT (mean points), not on file timestamps: NCAAF wk3's
    distribution file is stamped a day before its projection CSV and the means
    still agree to 0.05 points (measured 2026-09-17), because the sim is seeded.
    """
    gaps = []
    for side in ("home", "away"):
        a, b = C.to_float(projection_row.get(f"{side}_score_mean")), C.to_float(full.get(f"{side}_points_mean"))
        if a is not None and b is not None:
            gaps.append(abs(a - b))
    if gaps and max(gaps) > RUN_MISMATCH_POINTS:
        return f"DIFFERENT RUNS: distribution means differ from the projection by up to {max(gaps):.1f} points"
    return None


def _distribution_block(local_dir: str, season: int, week: int, game_id: str) -> tuple[dict[str, Any], Path, str] | None:
    path = C.first_existing(local_dir, f"smartsim2_segment_distributions_{season}_wk{week}.json")
    payload = _load(path, "segment distributions")
    games = payload.get("games") if isinstance(payload, dict) else None
    game = games.get(str(game_id)) if isinstance(games, dict) else None
    full = ((game or {}).get("segments") or {}).get("full") if isinstance(game, dict) else None
    if not isinstance(full, dict) or path is None:
        return None
    return full, path, str(payload.get("generated_at") or "")


# ---------------------------------------------------------------------------
# NFL readers
# ---------------------------------------------------------------------------


@dataclass
class NflGame:
    game_id: str
    season: int
    week: int | None
    gameday: str
    gametime: str
    home: str
    away: str
    row: dict[str, str]
    schedule: list[dict[str, str]] = field(default_factory=list)
    path: Path | None = None
    #: The board lists the clubs the other way round from the schedule. Same
    #: fixture (one meeting per date), so it is joined -- and said on the answer.
    board_reversed: bool = False


@dataclass
class NflPlayer:
    id: str
    name: str
    team: str
    pos: str
    index: int
    basis: dict[str, Any]


def _nfl_canon(value: Any) -> str | None:
    from syndicate.features.shared.team_aliases import canonical_team

    return canonical_team("nfl", value)


def _nfl_schedule(season: int | None) -> tuple[list[dict[str, str]], Path | None]:
    if season is None:
        return [], None
    path = C.first_existing(NFL_DIR, f"schedule_{season}.csv")
    return _read_csv(path, "schedule"), path


def _nfl_find_game(subject: PropSubject, schedule: list[dict[str, str]], path: Path | None, season: int | None) -> NflGame | None:
    home, away = _nfl_canon(subject.home_team), _nfl_canon(subject.away_team)
    if not schedule or not home or not away or season is None:
        return None
    date_key = _et_date(subject)
    row, reversed_ = None, False
    for flipped in (False, True):
        want_home, want_away = (away, home) if flipped else (home, away)
        same_teams = [r for r in schedule if _nfl_canon(r.get("home_team")) == want_home and _nfl_canon(r.get("away_team")) == want_away]
        exact = [r for r in same_teams if str(r.get("gameday") or "")[:10] == date_key]
        if not exact:
            # A board row with no commence_time carries only its board date, which is
            # the UTC day for a prime-time kickoff. One day either side, same clubs.
            exact = [r for r in same_teams if abs(_days_between(str(r.get("gameday") or ""), date_key) or 99) <= 1]
        if len(exact) == 1:
            row, reversed_ = exact[0], flipped
            break
    if row is None:
        return None
    week = C.to_float(row.get("week"))
    return NflGame(game_id=str(row.get("game_id") or ""), season=season, week=int(week) if week is not None else None,
                   gameday=str(row.get("gameday") or "")[:10], gametime=str(row.get("gametime") or ""),
                   home=str(row.get("home_team") or "").upper(), away=str(row.get("away_team") or "").upper(),
                   row=row, schedule=schedule, path=path, board_reversed=reversed_)


def _nfl_fantasy(season: int | None) -> tuple[dict[str, Any], Path] | None:
    if season is None:
        return None
    path = C.first_existing(NFL_DIR, f"fantasy/nfl_fantasy_projections_{season}.json")
    payload = _load(path, "fantasy projections")
    return (payload, path) if isinstance(payload, dict) and path is not None else None


def _nfl_find_player(fantasy, subject: PropSubject, game: NflGame | None) -> NflPlayer | None:
    if fantasy is None:
        return None
    payload, _ = fantasy
    matcher = NameMatcher(subject.player_name)
    hits: list[NflPlayer] = []
    for index, raw in enumerate(payload.get("players") or []):
        if isinstance(raw, dict) and matcher(raw.get("name")):
            hits.append(NflPlayer(id=str(raw.get("id") or ""), name=str(raw.get("name") or ""),
                                  team=str(raw.get("team") or "").upper(), pos=str(raw.get("pos") or ""),
                                  index=index, basis=raw.get("basis") if isinstance(raw.get("basis"), dict) else {}))
    if game is not None and len(hits) > 1:
        clubs = {_nfl_canon(game.home), _nfl_canon(game.away)}
        hits = [h for h in hits if _nfl_canon(h.team) in clubs]
    if len(hits) != 1:
        if len(hits) > 1:
            logger.warning("prop_evidence football: %d fantasy players named %r", len(hits), subject.player_name)
        return None
    return hits[0]


def _fantasy_row(payload: dict[str, Any], player: NflPlayer, week: int | None) -> dict[str, float] | None:
    """The player's per-game row for `week` (or the season row when week is None), keyed by column."""
    columns = payload.get("row_columns") or []
    rows = payload.get("season_rows") if week is None else (payload.get("week_rows") or {}).get(str(week))
    for row in rows or []:
        if isinstance(row, list) and row and row[0] == player.index:
            return {str(col): C.to_float(value) for col, value in zip(columns, row)}  # type: ignore[misc]
    return None


def _nfl_prop_artifact(season: int | None, game_week: int | None) -> tuple[dict[str, Any], Path, int, list[int]] | None:
    """The prop artifact for the game's week, else the newest EARLIER week (flagged by the caller)."""
    if season is None:
        return None
    weeks = _glob_weeks(NFL_DIR, f"nfl_prop_projections_{season}_wk*.json")
    if not weeks:
        return None
    if game_week is not None and game_week in weeks:
        week = game_week
    else:
        earlier = [w for w in weeks if game_week is None or w < game_week]
        week = max(earlier) if earlier else max(weeks)
    payload = _load(weeks[week], "prop projections")
    if not isinstance(payload, dict):
        return None
    return payload, weeks[week], week, sorted(weeks)


def _nfl_prop_rows(prop, stat: str, player_name: str) -> list[tuple[float | None, dict[str, Any]]]:
    if prop is None:
        return []
    matcher = NameMatcher(player_name)
    out: list[tuple[float | None, dict[str, Any]]] = []
    for row in prop[0].get("sim_rows") or []:
        if not isinstance(row, dict):
            continue
        parts = str(row.get("market") or "").split("::")
        if len(parts) < 2 or parts[0] != stat:
            continue
        if not matcher(row.get("entity") or parts[1]):
            continue
        out.append((C.to_float(parts[2]) if len(parts) > 2 else None, row))
    out.sort(key=lambda item: -1.0 if item[0] is None else item[0])
    return out


def _nfl_usage(season: int | None, player: NflPlayer | None) -> tuple[list[dict[str, Any]], Path | None, list[str]]:
    """The player's per-game lines from `nfl_fantasy_usage_<season>.json`, newest first.

    Reads the current season; opens the PRIOR season's document only when the
    current one is absent or holds no line for this player (at most two files,
    both one-per-season). Returns (lines, first path found, file names tried).
    """
    tried: list[str] = []
    if season is None or player is None or not player.id:
        return [], None, tried
    first_path: Path | None = None
    for year in (season, season - 1):
        name = f"nfl_fantasy_usage_{year}.json"
        tried.append(name)
        path = C.first_existing(NFL_DIR, f"fantasy/{name}")
        if path is None:
            continue
        first_path = first_path or path
        payload = _load(path, "fantasy usage")
        lines = [dict(line) for line in (payload.get("player_game_lines") or []) if isinstance(line, dict)
                 and str(line.get("player_id") or "") == player.id] if isinstance(payload, dict) else []
        if lines:
            lines.sort(key=lambda l: (int(l.get("season") or 0), int(l.get("week") or 0)), reverse=True)
            return lines, path, tried
    return [], first_path, tried


def _usage_opponent(line: dict[str, Any]) -> str:
    parts = str(line.get("game_id") or "").split("_")
    team = str(line.get("team") or "").upper()
    if len(parts) >= 4:
        away, home = parts[-2].upper(), parts[-1].upper()
        if team == away:
            return f"@{home}"
        if team == home:
            return f"vs {away}"
    return ""


# ---------------------------------------------------------------------------
# NFL layers
# ---------------------------------------------------------------------------


def _nfl_player_side(game: NflGame | None, team: str | None) -> str | None:
    if game is None or not team:
        return None
    canon = _nfl_canon(team)
    if canon and canon == _nfl_canon(game.home):
        return "home"
    if canon and canon == _nfl_canon(game.away):
        return "away"
    return None


def _nfl_player_sim(subject: PropSubject, stat: str | None, label: str, season: int | None, game: NflGame | None,
                    player: NflPlayer | None, prop, fantasy) -> LayerEvidence:
    if stat is None:
        return absent(Layer.PLAYER_SIM, f"{ABSENT_NOT_APPLICABLE}:market {subject.market} has no football stat mapping")
    line = subject.line
    prop_rows = _nfl_prop_rows(prop, stat, subject.player_name)
    week_row = _fantasy_row(fantasy[0], player, game.week) if fantasy and player and game and game.week else None
    fantasy_mean = _sum_columns(week_row, NFL_FANTASY_COLUMNS[stat]) if week_row else None
    if not prop_rows and fantasy_mean is None:
        if prop is None and fantasy is None:
            return absent(Layer.PLAYER_SIM, f"{ABSENT_NO_ARTIFACT}:nfl_prop_projections_{season}_wk*.json and fantasy/nfl_fantasy_projections_{season}.json not on this disk")
        where = f"nfl_prop_projections_{season}_wk{prop[2]}.json" if prop else "no prop artifact"
        return absent(Layer.PLAYER_SIM, f"{ABSENT_NO_MATCH}:{subject.player_name} has no {stat} row in {where} and no week row in nfl_fantasy_projections_{season}.json")

    rows: list[list[Any]] = []
    charts: list[dict[str, Any]] = []
    facts: dict[str, Any] = {"stat": stat, "game_week": game.week if game else None, "prob_over": None, "mean": None}
    as_of: str | None = None
    if prop is not None:
        payload, path, week, weeks = prop
        stale = game is None or game.week is None or week != game.week
        facts.update({"artifact_week": week, "artifact_weeks_on_disk": weeks, "stale_week": stale})
        generated = str(payload.get("generated_at") or "")
        as_of = generated or C.mtime_iso(path)
        rows.append(["Prop model file", f"{path.name} (generated {generated[:16].replace('T', ' ') or '—'})"])
        if game is None or game.week is None:
            rows.append(["STALE WEEK: unverified", f"this game is not in schedule_{season}.csv, so week {week} cannot be confirmed as its week"])
        elif week != game.week:
            rows.append([f"STALE WEEK: priced for week {week}", f"this game ({game.away} @ {game.home}) is week {game.week}; no week-{game.week} prop artifact is published (weeks on disk: {', '.join(map(str, weeks))})"])
    if prop_rows:
        token = C.fmt_line(line) if line is not None else None
        exact = next((row for ln, row in prop_rows if (ln is None and stat == "anytime_td") or (token is not None and ln is not None and C.fmt_line(ln) == token)), None)
        reference = exact or prop_rows[0][1]
        mean = C.to_float(reference.get("projected_value"))
        facts["mean"] = mean
        if stat == "anytime_td":
            p = C.to_float(reference.get("sim_projection"))
            rows.append(["Model P(scores a TD)", C.fmt_pct(p)])
            rows.append(["Probability basis", "shrunk per-game TD rate (player_stats.anytime_td_rate); no distribution"])
            facts["prob_over"] = p
        else:
            if exact is not None:
                p = C.to_float(exact.get("sim_projection"))
                facts["prob_over"] = p
                rows.append([f"Model P(over {C.fmt_line(line)})", C.fmt_pct(p)])
                if p is not None:
                    rows.append([f"Model P(under {C.fmt_line(line)})", C.fmt_pct(1.0 - p)])
            else:
                published = ", ".join(C.fmt_line(ln) for ln, _ in prop_rows if ln is not None)
                rows.append([f"Model P(over {C.fmt_line(line)})", f"not priced at this line (published lines: {published})"])
            rows.append(["Probability basis", _nfl_shape_text(stat)])
        rows.append(["Projected mean", C.fmt_num(mean, 2)])
        sd, sample = C.to_float(reference.get("projected_sd")), reference.get("sample_games")
        rows.append(["Spread (sd) / sample games", f"{C.fmt_num(sd, 2)} / {sample}" if sd is not None else "not published by the prop artifact"])
        facts.update({"sd": sd, "sample_games": sample})
        rows.append(["Rate basis", f"{reference.get('rate_source') or '—'} ({reference.get('sim_source') or '—'})"])
        priced_game = str(reference.get("game_id") or "")
        priced_clubs = {_nfl_canon(part) for part in priced_game.split("|")}
        same_game = priced_clubs == {_nfl_canon(subject.away_team), _nfl_canon(subject.home_team)} and None not in priced_clubs
        rows.append(["Priced game (artifact)", priced_game + ("" if same_game else "  — NOT this game")])
        facts["priced_game_is_this_game"] = same_game
        artifact_team = str(reference.get("player_team") or "")
        team_note = "" if (game is None or _nfl_player_side(game, artifact_team)) else "  — NOT a team in this game"
        rows.append(["Player team (artifact)", artifact_team + team_note])
        facts.update({"priced_game": priced_game, "artifact_player_team": artifact_team, "rate_source": reference.get("rate_source")})
        ladder = [(ln, C.to_float(row.get("sim_projection"))) for ln, row in prop_rows if ln is not None]
        facts["lines"] = [{"line": ln, "prob_over": p} for ln, p in ladder]
        if len(ladder) > 1:
            marker = {"x": C.fmt_line(line), "label": f"Line {C.fmt_line(line)}"} if line is not None else None
            charts.append(chart(f"Model P(over) by line — {subject.player_name} {label} (week {prop[2]})", "Line", "P(over) %",
                                [{"x": C.fmt_line(ln), "y": round(100.0 * p, 1)} for ln, p in ladder if p is not None],
                                Layer.PLAYER_SIM, marker=marker))
    elif prop is not None:
        rows.append(["Model P(over)", f"{subject.player_name} has no {stat} row in {prop[1].name}"])
    if fantasy_mean is not None and fantasy is not None and game is not None:
        fpayload, fpath = fantasy
        what = "expected rush+rec TDs" if stat == "anytime_td" else f"{label.lower()} per game"
        rows.append([f"Opportunity engine week {game.week} mean", f"{C.fmt_num(fantasy_mean, 2)} {what} (means only; no P(over))"])
        rows.append(["Opportunity engine", f"{fpayload.get('engine') or '—'} (generated {str(fpayload.get('generated_at') or '')[:16].replace('T', ' ')})"])
        facts["fantasy_week_mean"] = fantasy_mean
        as_of = as_of or str(fpayload.get("generated_at") or "") or C.mtime_iso(fpath)
    board_prob = C.to_float(subject.projection.get("model_prob_over"))
    market_prob = C.to_float(subject.projection.get("market_fair_prob_over"))
    if board_prob is not None or market_prob is not None:
        rows.append(["Board model P(over) vs market fair", f"{C.fmt_pct(board_prob)} vs {C.fmt_pct(market_prob)}"])
    team = player.team if player else str(subject.projection.get("player_team") or "")
    opponent = (game.away if _nfl_player_side(game, team) == "home" else game.home) if game and _nfl_player_side(game, team) else ""
    week_text = f"wk{game.week}" if game and game.week else "week unknown"
    title = f"Player sim — {subject.player_name} {label} {C.fmt_line(line)} ({team or '?'} vs {opponent or '?'}, NFL {season} {week_text})"
    return LayerEvidence(Layer.PLAYER_SIM, tables=[table(title, ["Measure", "Value"], rows, Layer.PLAYER_SIM)], charts=charts,
                         facts=facts, source="nfl:nfl_prop_projections+nfl_fantasy_projections", as_of=as_of)


def _nfl_shape_text(stat: str) -> str:
    weight = None
    try:
        from syndicate.features.nfl.props import _COVER_PROBABILITY_BLEND_WEIGHT

        weight = _COVER_PROBABILITY_BLEND_WEIGHT.get(stat)
    except Exception:
        weight = None
    if weight == 0:
        return "ASSUMED SHAPE: Normal fitted to the rate mean and stdev (log-normal blend weight 0 for this market) — not simulated draws"
    blend = f", log-normal weight {weight:g}" if weight is not None else ""
    return f"ASSUMED SHAPE: Normal/log-normal blend of the rate mean and stdev{blend} — not simulated draws"


def _nfl_recent_form(subject: PropSubject, stat: str | None, label: str, player: NflPlayer | None, usage, season: int | None) -> LayerEvidence:
    if stat is None:
        return absent(Layer.RECENT_FORM, f"{ABSENT_NOT_APPLICABLE}:market {subject.market} has no football stat mapping")
    lines, path, tried = usage
    if path is None:
        names = " / ".join(tried) if tried else f"nfl_fantasy_usage_{season}.json"
        return absent(Layer.RECENT_FORM, f"{ABSENT_NO_ARTIFACT}:{names} not on this disk -- no per-game NFL player stat artifact is published to web")
    if player is None:
        return absent(Layer.RECENT_FORM, f"{ABSENT_NO_MATCH}:{subject.player_name} has no gsis id (not in nfl_fantasy_projections_{season}.json) to join game lines")
    if not lines:
        return absent(Layer.RECENT_FORM, f"{ABSENT_NO_MATCH}:{subject.player_name} ({player.id}) has no lines in {' / '.join(tried)}")
    last = lines[:C.LAST_N_GAMES]
    columns = NFL_USAGE_COLUMNS[stat]
    volume_col, volume_label = NFL_USAGE_VOLUME[stat]
    event = stat == "anytime_td"
    line = _line_for(subject, stat)
    values = [_sum_columns(g, columns, event=event) for g in last]
    rows = [[_week_label(g.get("season"), g.get("week")), _usage_opponent(g), C.fmt_num(g.get(volume_col), 0),
             C.fmt_num(v, 0) if v is not None else "—"] for g, v in zip(last, values)]
    clean = [v for v in values if v is not None]
    rows.append([f"L{len(last)} avg", "", C.fmt_num(sum(C.to_float(g.get(volume_col)) or 0.0 for g in last) / len(last), 1),
                 C.fmt_num(sum(clean) / len(clean), 2) if clean else "—"])
    rate = C.hit_rate(values, line, _norm_side(subject.side))
    if rate:
        rows.append([f"Hit rate vs {C.fmt_line(line)}", "", "", C.hit_rate_text(rate)])
    seasons = sorted({int(g.get("season") or 0) for g in last})
    if season is not None and seasons and max(seasons) < season:
        rows.append([f"LAST SEASON: no {season} game lines published; these are {', '.join(map(str, seasons))}", "", "", ""])
    series = list(reversed([(_week_label(g.get("season"), g.get("week")), v) for g, v in zip(last, values)]))
    charts = [c for c in [_form_chart(series, label=label, player=subject.player_name, line=line)] if c]
    return LayerEvidence(
        Layer.RECENT_FORM,
        tables=[table(f"Last {len(last)} games — {subject.player_name} ({path.name})", ["Game", "Opp", volume_label, label], rows, Layer.RECENT_FORM)],
        charts=charts,
        facts={"games": len(last), "hit_rate": rate, "values": values, "seasons": seasons, "source_file": path.name},
        source="nfl:nfl_fantasy_usage", as_of=C.mtime_iso(path))


def _nfl_matchup(subject: PropSubject, stat: str | None, label: str, game: NflGame | None, player: NflPlayer | None,
                 fantasy, usage) -> LayerEvidence:
    if game is None:
        return absent(Layer.MATCHUP, f"{ABSENT_NO_MATCH}:{subject.away_team} @ {subject.home_team} on {_et_date(subject)} not in schedule_*.csv")
    team = player.team if player else str(subject.projection.get("player_team") or "")
    side = _nfl_player_side(game, team)
    if not side:
        detail = f"team {team} is not in {game.game_id}" if team else "team is unknown"
        return absent(Layer.MATCHUP, f"{ABSENT_NO_MATCH}:{subject.player_name}'s {detail}, so the opponent cannot be named")
    # The SCHEDULE names the opponent; the engine's `week_opponents` is checked
    # against it, never trusted over it.
    opponent = game.away if side == "home" else game.home
    engine_opponent = ""
    if fantasy and player and game.week:
        engine_opponent = str(((fantasy[0].get("week_opponents") or {}).get(str(game.week)) or {}).get(player.id) or "").upper()
    engine_agrees = not engine_opponent or _nfl_canon(engine_opponent) == _nfl_canon(opponent)
    facts: dict[str, Any] = {"opponent": opponent, "engine_opponent": engine_opponent or None, "engine_opponent_agrees": engine_agrees}
    tables: list[dict[str, Any]] = []

    results: list[list[Any]] = []
    allowed: list[float] = []
    for row in game.schedule:
        if str(row.get("gameday") or "") >= game.gameday:
            continue
        home, away = str(row.get("home_team") or "").upper(), str(row.get("away_team") or "").upper()
        if opponent not in (home, away):
            continue
        hs, as_ = C.to_float(row.get("home_score")), C.to_float(row.get("away_score"))
        if hs is None or as_ is None:
            continue
        own, other = (hs, as_) if opponent == home else (as_, hs)
        allowed.append(other)
        results.append([f"W{row.get('week')}", f"{'vs' if opponent == home else '@'} {away if opponent == home else home}", C.fmt_num(own, 0), C.fmt_num(other, 0)])
    if results:
        results.append(["Avg", "", "", C.fmt_num(sum(allowed) / len(allowed), 1)])
        tables.append(table(f"Opponent {opponent} — {game.season} results before this game (schedule)", ["Week", "Game", "Scored", "Allowed"], results, Layer.MATCHUP))
        facts["opponent_points_allowed"] = allowed

    if fantasy and player and game.week and stat:
        week_row = _fantasy_row(fantasy[0], player, game.week)
        season_row = _fantasy_row(fantasy[0], player, None)
        if week_row and season_row:
            wk = _sum_columns(week_row, NFL_FANTASY_COLUMNS[stat])
            ss = _sum_columns(season_row, NFL_FANTASY_COLUMNS[stat])
            rows = [[f"{label} per game, week {game.week} vs {engine_opponent or opponent}", C.fmt_num(wk, 3)], [f"{label} per game, season", C.fmt_num(ss, 3)]]
            if not engine_agrees:
                rows.insert(0, ["ENGINE OPPONENT MISMATCH", f"the engine's week-{game.week} opponent is {engine_opponent}; this game is vs {opponent}"])
            if wk is not None and ss is not None and abs(wk - ss) < 1e-6:
                rows.append(["Opponent adjustment", "none — the engine's week value equals its season value for this stat (it adjusts TD columns only)"])
            elif wk is not None and ss:
                rows.append(["Opponent/environment adjustment", f"{100.0 * (wk / ss - 1.0):+.1f}%"])
            basis = player.basis
            rows.append(["Team environment basis", f"{basis.get('environment') or '—'} ({basis.get('market_lined_games') or 0} lined games); team points/game {C.fmt_num(basis.get('team_points_per_game'), 2)}"])
            tables.append(table(f"Opportunity engine matchup view — {subject.player_name} wk{game.week} vs {opponent}", ["Measure", "Value"], rows, Layer.MATCHUP))
            facts["engine_week_vs_season"] = {"week": wk, "season": ss}

    lines = usage[0] if usage else []
    if lines and stat:
        vs = [g for g in lines if _usage_opponent(g).replace("vs ", "").lstrip("@") == opponent]
        if vs:
            columns = NFL_USAGE_COLUMNS[stat]
            vrows = [[_week_label(g.get("season"), g.get("week")), C.fmt_num(_sum_columns(g, columns, event=stat == "anytime_td"), 0)] for g in vs[:6]]
            rate = C.hit_rate([_sum_columns(g, columns, event=stat == "anytime_td") for g in vs], _line_for(subject, stat), _norm_side(subject.side))
            if rate:
                vrows.append([f"Hit rate vs {C.fmt_line(_line_for(subject, stat))}", C.hit_rate_text(rate)])
            tables.append(table(f"{subject.player_name} vs {opponent} ({len(vs)} game line{'s' if len(vs) != 1 else ''})", ["Game", label], vrows, Layer.MATCHUP))
            facts["vs_opponent"] = {"games": len(vs), "hit_rate": rate}
    if not tables:
        return absent(Layer.MATCHUP, f"{ABSENT_NO_MATCH}:no completed {opponent} game in schedule_{game.season}.csv and no engine row for {subject.player_name}")
    return LayerEvidence(Layer.MATCHUP, tables=tables, facts=facts, source="nfl:schedule+nfl_fantasy_projections")


def _nfl_advanced(subject: PropSubject, stat: str | None, label: str, game: NflGame | None, player: NflPlayer | None, fantasy, usage) -> LayerEvidence:
    if fantasy is None:
        return absent(Layer.ADVANCED, f"{ABSENT_NO_ARTIFACT}:fantasy/nfl_fantasy_projections_{_season(subject)}.json not on this disk")
    if player is None:
        return absent(Layer.ADVANCED, f"{ABSENT_NO_MATCH}:{subject.player_name} not in {fantasy[1].name}")
    payload, path = fantasy
    basis = player.basis
    rows: list[list[Any]] = [
        ["Team / position", f"{player.team} {player.pos}"],
        ["Depth chart rank", f"{basis.get('depth_rank') or '—'} (as of {str(basis.get('depth_chart_as_of') or '—')[:10]})"],
        ["Target share", C.fmt_pct(basis.get("target_share"))],
        ["Carry share", C.fmt_pct(basis.get("carry_share"))],
        ["Pass-attempt share", C.fmt_pct(basis.get("pass_share"))],
        ["Availability", C.fmt_pct(basis.get("availability"))],
        ["Share basis", f"{basis.get('share_source') or '—'} over {', '.join(map(str, basis.get('history_seasons') or [])) or '—'} ({C.fmt_num(basis.get('history_weighted_games'), 1)} weighted games){'; rookie' if basis.get('is_rookie') else ''}"],
    ]
    week = game.week if game else None
    week_row = _fantasy_row(payload, player, week) if week else _fantasy_row(payload, player, None)
    if week_row:
        scope = f"week {week}" if week else "season"
        rows.append([f"Projected volume per game ({scope})",
                     f"targets {C.fmt_num(week_row.get('targets'), 1)}, carries {C.fmt_num(week_row.get('carries'), 1)}, pass attempts {C.fmt_num(week_row.get('pass_attempts'), 1)}"])
    lines = usage[0] if usage else []
    if lines:
        recent = lines[:C.LAST_N_GAMES]
        def avg(col: str) -> str:
            vals = [C.to_float(g.get(col)) for g in recent]
            vals = [v for v in vals if v is not None]
            return C.fmt_num(sum(vals) / len(vals), 1) if vals else "—"
        rows.append([f"Actual volume per game, last {len(recent)} lines", f"targets {avg('targets')}, carries {avg('carries')}, pass attempts {avg('pass_attempts')}"])
    facts = {k: basis.get(k) for k in ("target_share", "carry_share", "pass_share", "depth_rank", "availability", "is_rookie", "history_seasons")}
    facts.update({"player_id": player.id, "team": player.team, "pos": player.pos})
    return LayerEvidence(Layer.ADVANCED, tables=[table(f"Role and usage — {subject.player_name} ({payload.get('engine') or 'fantasy engine'})", ["Measure", "Value"], rows, Layer.ADVANCED)],
                         facts=facts, source="nfl:nfl_fantasy_projections.basis", as_of=str(payload.get("generated_at") or "") or C.mtime_iso(path))


def _nfl_game_sim(subject: PropSubject, game: NflGame | None) -> LayerEvidence:
    if game is None:
        return absent(Layer.GAME_SIM, f"{ABSENT_NO_MATCH}:{subject.away_team} @ {subject.home_team} on {_et_date(subject)} not in schedule_*.csv")
    if game.week is None:
        return absent(Layer.GAME_SIM, f"{ABSENT_NO_MATCH}:{game.game_id} has no week in the schedule")
    name = f"smartsim2_projections_{game.season}_wk{game.week}.csv"
    path = C.first_existing(NFL_DIR, name)
    if path is None:
        return absent(Layer.GAME_SIM, f"{ABSENT_NO_ARTIFACT}:{name}")
    row = next((r for r in _read_csv(path, "game projections") if str(r.get("game_id") or "") == game.game_id), None)
    if row is None:
        return absent(Layer.GAME_SIM, f"{ABSENT_NO_MATCH}:{game.game_id} not in {name}")
    from syndicate.features.shared.nfl_game_projections import _is_degenerate_rating_source

    home, away = game.home, game.away
    generated = str(row.get("generated_at") or "")
    home_win = C.to_float(row.get("home_win_rate"))
    rows: list[list[Any]] = [
        ["Win probability", C.fmt_pct(1.0 - home_win) if home_win is not None else "—", C.fmt_pct(home_win)],
        ["Mean points", C.fmt_num(row.get("away_score_mean")), C.fmt_num(row.get("home_score_mean"))],
        ["Total (mean ± sd)", f"{C.fmt_num(row.get('total_mean'))} ± {C.fmt_num(row.get('total_stdev'))}", ""],
        [f"{home} margin (mean ± sd)", f"{C.fmt_num(row.get('margin_mean'))} ± {C.fmt_num(row.get('margin_stdev'))}", ""],
        ["Market total / spread (schedule)", C.fmt_num(game.row.get("total_line")), _spread_text(game.home, game.row.get("spread_line"))],
        ["Sims / rating source", f"{row.get('seeds_used') or '—'} / {row.get('rating_source') or '—'}", ""],
    ]
    facts: dict[str, Any] = {k: C.to_float(row.get(k)) for k in ("home_score_mean", "away_score_mean", "total_mean", "margin_mean", "total_stdev", "margin_stdev", "home_win_rate")}
    facts.update({"game_id": game.game_id, "week": game.week, "generated_at": generated})
    age = _days_between(generated[:10], game.gameday) if generated else None
    if age is not None and age > STALE_GAME_PROJECTION_DAYS:
        rows.append([f"STALE: generated {generated[:10]}, {age} days before kickoff", "", ""])
    facts["generated_days_before_kickoff"] = age
    if _is_degenerate_rating_source(row.get("rating_source")):
        rows.append(["DEGENERATE: both sides rated neutral_no_data (a league constant, not a matchup)", "", ""])
        facts["degenerate"] = True
    charts: list[dict[str, Any]] = []
    block = _distribution_block(NFL_DIR, game.season, game.week, game.game_id)
    total_line, spread_line = C.to_float(game.row.get("total_line")), C.to_float(game.row.get("spread_line"))
    if block is None:
        rows.append([f"Score distribution", f"smartsim2_segment_distributions_{game.season}_wk{game.week}.json not published for this game", ""])
    else:
        full, _, _ = block
        tdist, mdist = full.get("total_points_dist"), full.get("margin_dist")
        p_over = C.dist_prob_over(tdist, total_line)
        p_cover = C.dist_prob_over(mdist, spread_line)
        n = C.dist_summary(tdist)
        if p_over is not None:
            # margin_dist is HOME-POSITIVE (football_segment_distributions.py; its mean
            # equals home_points_mean - away_points_mean on the real file), and
            # spread_line > 0 favours home, so home covers when margin > spread_line.
            rows.append([f"Sim P(total over {C.fmt_line(total_line)}) / P({_spread_text(home, spread_line)} covers)", C.fmt_pct(p_over), C.fmt_pct(p_cover)])
        facts.update({"p_total_over": p_over, "p_home_cover": p_cover, "sims": (n or {}).get("n")})
        rows.append(["Distribution mean points", C.fmt_num(full.get("away_points_mean")), C.fmt_num(full.get("home_points_mean"))])
        mismatch = _run_mismatch(row, full)
        if mismatch:
            rows.append([mismatch, "", ""])
            facts["distribution_run_mismatch"] = True
        total_chart = C.dist_chart(tdist, title=f"Simulated total points — {away} @ {home} (wk{game.week})", x_label="Total points", layer=Layer.GAME_SIM, line=total_line)
        if total_chart:
            charts.append(total_chart)
    return LayerEvidence(Layer.GAME_SIM, tables=[table(f"Game sim — {away} @ {home} ({game.game_id}, generated {generated[:10] or '—'})", ["Metric", away, home], rows, Layer.GAME_SIM)],
                         charts=charts, facts=facts, source="nfl:smartsim2_projections+segment_distributions", as_of=generated or C.mtime_iso(path))


def _spread_text(home: str, spread: Any) -> str:
    """nflverse `spread_line` > 0 means the HOME side is favoured by that many points."""
    value = C.to_float(spread)
    if value is None:
        return "—"
    return f"{home} {'-' if value > 0 else '+'}{abs(value):g}" if value else f"{home} pk"


def _nfl_rest_days(game: NflGame, team: str) -> int | None:
    previous = [str(r.get("gameday") or "")[:10] for r in game.schedule
                if team in (str(r.get("home_team") or "").upper(), str(r.get("away_team") or "").upper())
                and str(r.get("gameday") or "")[:10] < game.gameday]
    return _days_between(max(previous), game.gameday) if previous else None


def _nfl_environment(subject: PropSubject, game: NflGame | None, player: NflPlayer | None) -> LayerEvidence:
    if game is None:
        return absent(Layer.ENVIRONMENT, f"{ABSENT_NO_MATCH}:{subject.away_team} @ {subject.home_team} on {_et_date(subject)} not in schedule_*.csv")
    team = player.team if player else str(subject.projection.get("player_team") or "")
    side = _nfl_player_side(game, team)
    row = game.row
    rows: list[list[Any]] = [
        ["Venue", f"{row.get('stadium') or '—'} ({'home' if side == 'home' else 'away' if side == 'away' else 'side unknown'} for {team or 'player'})"],
        ["Kickoff", f"{game.gameday} {game.gametime} ET (week {game.week})"],
    ]
    facts: dict[str, Any] = {"side": side, "stadium": row.get("stadium"), "board_reversed": game.board_reversed}
    if game.board_reversed:
        rows.append(["HOME/AWAY DISAGREE", f"board lists {subject.away_team} @ {subject.home_team}; schedule_{game.season}.csv has {game.away} @ {game.home} (schedule orientation used)"])
    spread, total = C.to_float(row.get("spread_line")), C.to_float(row.get("total_line"))
    home_ml, away_ml = C.to_float(row.get("home_moneyline")), C.to_float(row.get("away_moneyline"))
    if spread is not None and total is not None:
        # nflverse convention: spread_line > 0 means the HOME side is favoured by
        # that many points. Checked per game against the moneylines, not assumed.
        if home_ml is not None and away_ml is not None and spread != 0:
            consistent = (spread > 0) == (home_ml < away_ml)
            check = "sign checked against moneylines" if consistent else "SIGN DISAGREES WITH MONEYLINES — implied totals withheld"
        else:
            consistent, check = True, "sign not checkable (no moneylines or pick'em)"
        rows.append(["Market total / spread", f"{C.fmt_num(total, 1)} / {_spread_text(game.home, spread)} ({check})"])
        if consistent:
            home_implied, away_implied = total / 2 + spread / 2, total / 2 - spread / 2
            rows.append(["Implied team totals (away / home)", f"{game.away} {away_implied:.2f} / {game.home} {home_implied:.2f}"])
            facts["implied_totals"] = {"home": home_implied, "away": away_implied}
        facts.update({"spread_line": spread, "total_line": total, "spread_sign_consistent": consistent})
    away_rest, home_rest = _nfl_rest_days(game, game.away), _nfl_rest_days(game, game.home)
    rows.append([f"Rest days {game.away} / {game.home}",
                 f"{away_rest if away_rest is not None else 'first game'} / {home_rest if home_rest is not None else 'first game'}"])
    facts["rest_days"] = {"away": away_rest, "home": home_rest}
    injuries = _nfl_injuries(game, player, subject.player_name)
    if injuries is None:
        rows.append(["Injury report", f"injuries_{game.season}.csv not on this disk"])
    else:
        own_status, by_team = injuries
        rows.append([f"{subject.player_name} status (week {game.week})", own_status or f"not on the week-{game.week} report"])
        facts["player_injury_status"] = own_status
        for code in (game.away, game.home):
            names = by_team.get(code) or []
            rows.append([f"Injury report {code} week {game.week} (Out/Doubtful/Questionable)", ", ".join(names[:8]) + (f" +{len(names) - 8}" if len(names) > 8 else "") if names else "none listed"])
        facts["injuries"] = by_team
    rows.append(["Roof / weather", "not published (schedule_*.csv carries no roof, surface or weather field)"])
    facts["unpublished"] = ["roof", "weather"]
    return LayerEvidence(Layer.ENVIRONMENT, tables=[table(f"Game environment — {game.away} @ {game.home} ({game.game_id})", ["Factor", "Value"], rows, Layer.ENVIRONMENT)],
                         facts=facts, source="nfl:schedule+injuries", as_of=C.mtime_iso(game.path))


_INJURY_ORDER = {"Out": 0, "Doubtful": 1, "Questionable": 2}


def _nfl_injuries(game: NflGame, player: NflPlayer | None, player_name: str) -> tuple[str | None, dict[str, list[str]]] | None:
    path = C.first_existing(NFL_DIR, f"tracking/nflverse/injuries/injuries_{game.season}.csv")
    if path is None:
        return None
    clubs = {_nfl_canon(game.home): game.home, _nfl_canon(game.away): game.away}
    own: str | None = None
    matcher = NameMatcher(player_name)
    listed: dict[str, list[tuple[int, str]]] = {game.home: [], game.away: []}
    for row in _read_csv(path, "injuries"):
        if str(row.get("week") or "") != str(game.week):
            continue
        code = clubs.get(_nfl_canon(row.get("team")))
        if code is None:
            continue
        status = str(row.get("report_status") or "").strip()
        is_player = (player is not None and str(row.get("gsis_id") or "") == player.id) or matcher(row.get("full_name"))
        if is_player:
            own = f"{status or 'no game status'}; practice: {row.get('practice_status') or '—'} ({row.get('report_primary_injury') or row.get('practice_primary_injury') or '—'})"
        if status in _INJURY_ORDER:
            listed[code].append((_INJURY_ORDER[status], f"{row.get('full_name')} {row.get('position')} ({status})"))
    return own, {code: [text for _, text in sorted(items)] for code, items in listed.items()}


def build_nfl(subject: PropSubject) -> PropEvidence:
    evidence = PropEvidence(subject=subject, provider="football:nfl")
    stat, label = MARKETS.get(subject.market_key, (None, subject.market))
    season = _season(subject)
    schedule, schedule_path = _nfl_schedule(season)
    game = _nfl_find_game(subject, schedule, schedule_path, season)
    fantasy = _nfl_fantasy(season)
    player = _nfl_find_player(fantasy, subject, game)
    prop = _nfl_prop_artifact(season, game.week if game else None) if stat else None
    usage = _nfl_usage(season, player)

    evidence.set(_nfl_player_sim(subject, stat, label, season, game, player, prop, fantasy))
    evidence.set(_nfl_recent_form(subject, stat, label, player, usage, season))
    evidence.set(_nfl_matchup(subject, stat, label, game, player, fantasy, usage))
    evidence.set(_nfl_advanced(subject, stat, label, game, player, fantasy, usage))
    evidence.set(_nfl_game_sim(subject, game))
    evidence.set(_nfl_environment(subject, game, player))
    evidence.set(build_track_record(subject))
    return evidence


# ---------------------------------------------------------------------------
# NCAAF readers
# ---------------------------------------------------------------------------


def _ncaaf_resolve(name: Any) -> str | None:
    from syndicate.features.ncaaf.oddsapi_lines import resolve_team

    try:
        return resolve_team(name)
    except Exception:
        logger.exception("prop_evidence football: ncaaf resolve_team raised on %r", name)
        return None


@lru_cache(maxsize=4096)
def _fold_text(text: str) -> str:
    from syndicate.features.ncaaf.oddsapi_lines import fold

    return fold(text)


def _fold(value: Any) -> str:
    """`oddsapi_lines.fold`, memoised on the STRING (a pure function of ~700 school names, not a payload)."""
    return _fold_text(str(value or ""))


@dataclass
class NcaafGame:
    season: int
    week: int
    game_id: str
    home: str
    away: str
    row: dict[str, str]
    path: Path
    resolution: str
    #: CFBD's projection lists the schools the other way round from the board.
    board_reversed: bool = False


def _ncaaf_week_candidates(season: int, subject: PropSubject) -> tuple[list[int], str]:
    """Weeks to try for this kickoff, from `ncaaf_week_state_<season>.json`.

    NCAAF weeks are not calendar windows (2026 week 1 spans 08-29..09-07), so
    the week is the lowest one whose LAST unplayed kickoff is not before this one.
    """
    path = C.first_existing(NCAAF_DIR, f"week_state/ncaaf_week_state_{season}.json")
    payload = _load(path, "week state")
    kickoff = _parse_ts(subject.commence_time) or _parse_ts(f"{subject.selected_date}T23:59:00+00:00")
    unplayed = payload.get("unplayed_kickoffs") if isinstance(payload, dict) else None
    if isinstance(unplayed, dict) and kickoff is not None:
        weeks = sorted(int(w) for w in unplayed if str(w).isdigit())
        for week in weeks:
            last = _parse_ts((unplayed.get(str(week)) or {}).get("last"))
            if last is not None and last >= kickoff:
                return [week, week - 1, week + 1], "week_state"
    return [], "week_state_unavailable"


def _ncaaf_find_game(subject: PropSubject, season: int | None, home: str | None, away: str | None) -> NcaafGame | str:
    """The projection row for this fixture, or the named reason there is none."""
    if season is None:
        return f"{ABSENT_NO_MATCH}:no season for {subject.selected_date}"
    if not home or not away:
        unresolved = subject.home_team if not home else subject.away_team
        return f"{ABSENT_NO_MATCH}:team {unresolved!r} does not resolve to a CFBD school"
    available = _glob_weeks(NCAAF_DIR, f"smartsim2_projections_{season}_wk*.csv")
    if not available:
        return f"{ABSENT_NO_ARTIFACT}:smartsim2_projections_{season}_wk*.csv"
    # Target week first; the neighbouring weeks are opened ONLY when the fixture
    # is not in it (a rescheduled game), so the common case reads one file.
    candidates, resolution = _ncaaf_week_candidates(season, subject)
    if not candidates:
        # BOUNDED EXCEPTION to one-file-per-family: without week_state the week
        # cannot be placed, so the (small, ~12 KB) weekly files are scanned
        # newest week first until the fixture is found.
        candidates, resolution = sorted(available, reverse=True), "scan"
    fh, fa = _fold(home), _fold(away)
    for week in candidates:
        path = available.get(week)
        if path is None:
            continue
        reversed_hit = None
        for row in _read_csv(path, "ncaaf projections"):
            rh, ra = _fold(row.get("home_team")), _fold(row.get("away_team"))
            if rh == fh and ra == fa:
                return NcaafGame(season=season, week=week, game_id=str(row.get("game_id") or ""), home=home, away=away,
                                 row=row, path=path, resolution=resolution)
            if rh == fa and ra == fh:
                reversed_hit = row
        if reversed_hit is not None:
            # Same two schools in the same week is the same fixture. Measured
            # 2026-09-17: the board lists "Virginia Cavaliers @ West Virginia
            # Mountaineers" while wk3 has home=Virginia. Joined, and the
            # disagreement is carried onto the answer rather than hidden.
            return NcaafGame(season=season, week=week, game_id=str(reversed_hit.get("game_id") or ""), home=away, away=home,
                             row=reversed_hit, path=path, resolution=resolution, board_reversed=True)
    tried = ", ".join(f"wk{w}" for w in candidates if w in available)
    return f"{ABSENT_NO_MATCH}:{away} @ {home} not in smartsim2_projections_{season} ({tried or 'no candidate week on disk'})"


@dataclass
class NcaafBox:
    path: Path
    games: list[dict[str, Any]]
    team: str | None
    elsewhere: list[str]
    team_game: dict[tuple[str, str], dict[str, float]]
    game_meta: dict[str, dict[str, Any]]
    snapshot_dates: list[str]
    #: Both clubs in THIS game field a player of this name: refused, never guessed.
    ambiguous: list[str] = field(default_factory=list)


def _ncaaf_box(subject: PropSubject, home: str | None, away: str | None) -> NcaafBox | None:
    """ONE pass over the CFBD player-game snapshot: the player's lines plus per-team game sums."""
    path = C.first_existing(NCAAF_DIR, "processed/player_game_stats/ncaaf_player_game_stats_snapshot.csv")
    if path is None:
        return None
    wanted = {_fold(t): t for t in (home, away) if t}
    matcher = NameMatcher(subject.player_name)
    mine: dict[str, dict[str, Any]] = {}
    elsewhere: set[str] = set()
    team_game: dict[tuple[str, str], dict[str, float]] = {}
    game_meta: dict[str, dict[str, Any]] = {}
    dates: set[str] = set()
    try:
        for row in C.iter_csv(path):
            gid = str(row.get("game_id") or "").strip()
            team = str(row.get("team") or "").strip()
            if not gid or not team:
                continue
            meta = game_meta.setdefault(gid, {"season": row.get("season"), "week": row.get("week"), "teams": set()})
            meta["teams"].add(team)
            # CFBD's "Team" pseudo-player (298 of 8,115 rows, negative id) carries
            # kneel-downs and sack yardage, which NCAA charges to the team. It is
            # summed on purpose: leaving it out would make the team denominator
            # smaller than the box score it comes from.
            sums = team_game.setdefault((gid, team), {col: 0.0 for col in NCAAF_COLUMNS})
            entry: dict[str, Any] = {}
            for col in NCAAF_COLUMNS:
                # Inline, not `C.to_float`: 9 columns x every row of a file that
                # grows all season, and this loop was 40% of an Ask's time.
                raw = row.get(col)
                try:
                    value: float | None = float(raw) if raw else None
                except ValueError:
                    value = None
                if value is not None and value != value:  # NaN is missing, never a number
                    value = None
                entry[col] = value
                if value is not None:
                    sums[col] += value
            if row.get("source_snapshot_date"):
                dates.add(str(row.get("source_snapshot_date")))
            if matcher(row.get("player_name")):
                if _fold(team) in wanted:
                    entry.update({"game_id": gid, "team": team, "season": row.get("season"), "week": row.get("week")})
                    mine.setdefault(gid, entry)
                else:
                    elsewhere.add(team)
    except Exception:
        logger.exception("prop_evidence football: unreadable %s", path)
        return None
    teams = {g["team"] for g in mine.values()}
    ambiguous: list[str] = []
    if len(teams) > 1:
        # One name on BOTH rosters of this game: refuse rather than guess.
        logger.warning("prop_evidence football: %r matches players on %s", subject.player_name, sorted(teams))
        ambiguous = sorted(teams)
        mine, teams = {}, set()
    games = list(mine.values())
    for g in games:
        others = game_meta.get(g["game_id"], {}).get("teams", set()) - {g["team"]}
        g["opponent"] = next(iter(sorted(others)), "")
    games.sort(key=lambda g: (int(C.to_float(g.get("season")) or 0), int(C.to_float(g.get("week")) or 0), g["game_id"]), reverse=True)
    return NcaafBox(path=path, games=games, team=next(iter(teams), None), elsewhere=sorted(elsewhere),
                    team_game=team_game, game_meta=game_meta, snapshot_dates=sorted(dates), ambiguous=ambiguous)


# ---------------------------------------------------------------------------
# NCAAF layers
# ---------------------------------------------------------------------------


def _ncaaf_player_absent(subject: PropSubject, box: NcaafBox | None, home: str | None, away: str | None) -> str | None:
    if box is None:
        return f"{ABSENT_NO_ARTIFACT}:ncaaf_player_game_stats_snapshot.csv not on this disk"
    if not home or not away:
        return f"{ABSENT_NO_MATCH}:board teams do not resolve to CFBD schools ({subject.away_team} @ {subject.home_team})"
    if box.ambiguous:
        return f"{ABSENT_NO_MATCH}:{subject.player_name} is on BOTH rosters in this game ({', '.join(box.ambiguous)}) -- refused rather than guessed"
    if not box.games:
        detail = f" (same name found on {', '.join(box.elsewhere)}, not in this game)" if box.elsewhere else ""
        return f"{ABSENT_NO_MATCH}:{subject.player_name} has no {away}/{home} lines in ncaaf_player_game_stats_snapshot.csv{detail}"
    return None


def _ncaaf_recent_form(subject: PropSubject, stat: str | None, label: str, box: NcaafBox | None, home, away) -> LayerEvidence:
    if stat is None:
        return absent(Layer.RECENT_FORM, f"{ABSENT_NOT_APPLICABLE}:market {subject.market} has no football stat mapping")
    reason = _ncaaf_player_absent(subject, box, home, away)
    if reason:
        return absent(Layer.RECENT_FORM, reason)
    assert box is not None
    last = box.games[:C.LAST_N_GAMES]
    volume_col, volume_label = NCAAF_VOLUME[stat]
    event = stat == "anytime_td"
    line = _line_for(subject, stat)
    values = [None if g.get(stat) is None else ((1.0 if (g.get(stat) or 0) > 0 else 0.0) if event else g.get(stat)) for g in last]
    rows = [[_week_label(g.get("season"), g.get("week")), g.get("opponent") or "", C.fmt_num(g.get(volume_col), 0),
             C.fmt_num(v, 0) if v is not None else "—"] for g, v in zip(last, values)]
    clean = [v for v in values if v is not None]
    vol = [C.to_float(g.get(volume_col)) for g in last]
    vol = [v for v in vol if v is not None]
    rows.append([f"L{len(last)} avg", "", C.fmt_num(sum(vol) / len(vol), 1) if vol else "—", C.fmt_num(sum(clean) / len(clean), 2) if clean else "—"])
    rate = C.hit_rate(values, line, _norm_side(subject.side))
    if rate:
        rows.append([f"Hit rate vs {C.fmt_line(line)}", "", "", C.hit_rate_text(rate)])
    if len(last) < 3:
        rows.append([f"SMALL SAMPLE: {len(last)} game{'s' if len(last) != 1 else ''} in the snapshot (it holds {', '.join(sorted({str(m.get('season')) for m in box.game_meta.values()}))} only)", "", "", ""])
    series = list(reversed([(_week_label(g.get("season"), g.get("week")), v) for g, v in zip(last, values)]))
    charts = [c for c in [_form_chart(series, label=label, player=subject.player_name, line=line)] if c]
    through = box.snapshot_dates[-1] if box.snapshot_dates else "—"
    return LayerEvidence(
        Layer.RECENT_FORM,
        tables=[table(f"Last {len(last)} games — {subject.player_name}, {box.team} (CFBD box scores through {through})", ["Game", "Opp", volume_label, label], rows, Layer.RECENT_FORM)],
        charts=charts,
        facts={"games": len(last), "hit_rate": rate, "values": values, "team": box.team, "snapshot_through": through},
        source="ncaaf:player_game_stats_snapshot", as_of=through if through != "—" else C.mtime_iso(box.path))


def _ncaaf_allowed_by_team(box: NcaafBox, stat: str) -> dict[str, list[tuple[int, int, str, float]]]:
    """team -> [(season, week, opponent, stat allowed)] newest first, in ONE pass over the games.

    A game whose opposing side has no CFBD lines is skipped -- unmeasured, never
    "zero allowed".
    """
    out: dict[str, list[tuple[int, int, str, float]]] = {}
    for gid, meta in box.game_meta.items():
        teams = sorted(meta["teams"])
        if len(teams) < 2:
            continue
        season, week = int(C.to_float(meta.get("season")) or 0), int(C.to_float(meta.get("week")) or 0)
        for team in teams:
            others = [t for t in teams if t != team]
            allowed = sum(box.team_game[(gid, t)][stat] for t in others)
            out.setdefault(team, []).append((season, week, ", ".join(others), allowed))
    for games in out.values():
        games.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return out


def _ncaaf_matchup(subject: PropSubject, stat: str | None, label: str, box: NcaafBox | None, home, away) -> LayerEvidence:
    if stat is None:
        return absent(Layer.MATCHUP, f"{ABSENT_NOT_APPLICABLE}:market {subject.market} has no football stat mapping")
    reason = _ncaaf_player_absent(subject, box, home, away)
    if reason:
        return absent(Layer.MATCHUP, reason)
    assert box is not None and box.team is not None
    opponent = away if _fold(box.team) == _fold(home) else home
    by_team = _ncaaf_allowed_by_team(box, stat)
    snapshot_opp = next((t for t in by_team if _fold(t) == _fold(opponent)), None)
    facts: dict[str, Any] = {"opponent": opponent}
    tables: list[dict[str, Any]] = []
    allowed = by_team.get(snapshot_opp or "", [])
    if allowed:
        rows = [[_week_label(season, week), opp, C.fmt_num(value, 0)] for season, week, opp, value in allowed]
        avg = sum(value for *_, value in allowed) / len(allowed)
        rows.append(["Avg", "", C.fmt_num(avg, 1)])
        rank_text = _ncaaf_rank(by_team, snapshot_opp)
        if rank_text:
            rows.append(["Rank among FBS teams in snapshot", "", rank_text])
        tables.append(table(f"Opposing defence — {label.lower()} allowed by {opponent} ({len(allowed)} game{'s' if len(allowed) != 1 else ''}, not schedule-adjusted)",
                            ["Game", "Opponent faced", f"{label} allowed"], rows, Layer.MATCHUP))
        facts.update({"allowed_per_game": avg, "allowed_games": len(allowed), "allowed_rank": rank_text})
    vs = [g for g in box.games if _fold(g.get("opponent")) == _fold(opponent)]
    if vs:
        vrows = [[_week_label(g.get("season"), g.get("week")), C.fmt_num(g.get(stat), 0)] for g in vs]
        tables.append(table(f"{subject.player_name} vs {opponent}", ["Game", label], vrows, Layer.MATCHUP))
        facts["vs_opponent_games"] = len(vs)
    if not tables:
        return absent(Layer.MATCHUP, f"{ABSENT_NO_MATCH}:{opponent} has no measurable games in ncaaf_player_game_stats_snapshot.csv")
    return LayerEvidence(Layer.MATCHUP, tables=tables, facts=facts, source="ncaaf:player_game_stats_snapshot", as_of=C.mtime_iso(box.path))


def _ncaaf_rank(by_team: dict[str, list[tuple[int, int, str, float]]], team: str | None) -> str | None:
    """Rank of `team`'s allowed-per-game among FBS teams (the registry's own subdivision field)."""
    try:
        from syndicate.features.ncaaf.oddsapi_lines import fbs_canonical_names

        fbs = {_fold(name) for name in fbs_canonical_names()}
    except Exception:
        fbs = set()
    averages = {t: sum(value for *_, value in games) / len(games)
                for t, games in by_team.items() if games and (not fbs or _fold(t) in fbs)}
    if team not in averages:
        return None
    ordered = sorted(averages.values())
    scope = "" if fbs else " (FBS list unavailable: all teams)"
    return f"{ordered.index(averages[team]) + 1} of {len(ordered)} (1 = fewest allowed){scope}"


def _ncaaf_advanced(subject: PropSubject, stat: str | None, label: str, box: NcaafBox | None, home, away) -> LayerEvidence:
    if stat is None:
        return absent(Layer.ADVANCED, f"{ABSENT_NOT_APPLICABLE}:market {subject.market} has no football stat mapping")
    reason = _ncaaf_player_absent(subject, box, home, away)
    if reason:
        return absent(Layer.ADVANCED, reason)
    assert box is not None and box.team is not None
    games = box.games[:C.LAST_N_GAMES]

    def total(col: str, *, team: bool = False) -> float:
        if team:
            return sum(box.team_game.get((g["game_id"], box.team), {}).get(col, 0.0) for g in games)
        return sum(C.to_float(g.get(col)) or 0.0 for g in games)

    def share(col: str) -> str:
        denominator = total(col, team=True)
        return C.fmt_pct(total(col) / denominator) if denominator > 0 else "—"

    def ratio(num: str, den: str) -> str:
        d = total(den)
        return C.fmt_num(total(num) / d, 2) if d > 0 else "—"

    n = len(games)
    rows: list[list[Any]] = []
    if stat.startswith("passing") or stat == "interceptions":
        rows += [["Share of team pass attempts", share("passing_attempts")], ["Pass attempts per game", C.fmt_num(total("passing_attempts") / n, 1)],
                 ["Yards per attempt", ratio("passing_yards", "passing_attempts")],
                 ["TD / INT per game", f"{C.fmt_num(total('passing_tds') / n, 2)} / {C.fmt_num(total('interceptions') / n, 2)}"],
                 ["Rushing attempts per game", C.fmt_num(total("rushing_attempts") / n, 1)]]
    elif stat.startswith("rushing"):
        rows += [["Share of team rushing attempts", share("rushing_attempts")], ["Share of team rushing yards", share("rushing_yards")],
                 ["Carries per game", C.fmt_num(total("rushing_attempts") / n, 1)], ["Yards per carry", ratio("rushing_yards", "rushing_attempts")],
                 ["Receptions per game", C.fmt_num(total("receptions") / n, 1)]]
    else:
        rows += [["Share of team receptions", share("receptions")], ["Share of team receiving yards", share("receiving_yards")],
                 ["Receptions per game", C.fmt_num(total("receptions") / n, 1)], ["Yards per reception", ratio("receiving_yards", "receptions")],
                 ["Carries per game", C.fmt_num(total("rushing_attempts") / n, 1)], ["TD games", f"{sum(1 for g in games if (g.get('anytime_td') or 0) > 0)} of {n}"]]
    rows.append(["Targets / snaps / routes", "not published (CFBD box lines carry no targets or snap counts)"])
    return LayerEvidence(Layer.ADVANCED, tables=[table(f"Role and usage — {subject.player_name}, {box.team} ({n} game{'s' if n != 1 else ''}, CFBD box scores)", ["Measure", "Value"], rows, Layer.ADVANCED)],
                         facts={"games": n, "team": box.team}, source="ncaaf:player_game_stats_snapshot", as_of=C.mtime_iso(box.path))


def _ncaaf_game_sim(subject: PropSubject, game: NcaafGame | str) -> LayerEvidence:
    if isinstance(game, str):
        return absent(Layer.GAME_SIM, game)
    row = game.row
    generated = str(row.get("generated_at") or "")
    home_win = C.to_float(row.get("home_win_rate"))
    rows: list[list[Any]] = [
        ["Win probability", C.fmt_pct(1.0 - home_win) if home_win is not None else "—", C.fmt_pct(home_win)],
        ["Mean points", C.fmt_num(row.get("away_score_mean")), C.fmt_num(row.get("home_score_mean"))],
        ["Total (mean ± sd)", f"{C.fmt_num(row.get('total_mean'))} ± {C.fmt_num(row.get('total_stdev'))}", ""],
        [f"{game.home} margin (mean ± sd)", f"{C.fmt_num(row.get('margin_mean'))} ± {C.fmt_num(row.get('margin_stdev'))}", ""],
        ["Sims / profile / ratings", f"{row.get('seeds_used') or '—'} / {row.get('profile_name') or '—'} / {row.get('rating_source') or '—'}", ""],
    ]
    try:
        from syndicate.features.ncaaf.game_projections import skill_note

        rows.append(["Measured skill (margins)", skill_note("spreads")["verdict"], ""])
        rows.append(["Measured skill (totals)", skill_note("totals")["verdict"], ""])
    except Exception:
        logger.exception("prop_evidence football: ncaaf skill_note unavailable")
    facts: dict[str, Any] = {k: C.to_float(row.get(k)) for k in ("home_score_mean", "away_score_mean", "total_mean", "margin_mean", "total_stdev", "margin_stdev", "home_win_rate")}
    facts.update({"game_id": game.game_id, "week": game.week, "week_resolution": game.resolution, "generated_at": generated,
                  "board_reversed": game.board_reversed})
    if game.board_reversed:
        rows.append(["HOME/AWAY DISAGREE", f"board lists {subject.away_team} @ {subject.home_team}; CFBD projection has {game.away} @ {game.home}", ""])
    charts: list[dict[str, Any]] = []
    block = _distribution_block(NCAAF_DIR, game.season, game.week, game.game_id)
    if block is None:
        rows.append(["Score distribution", f"smartsim2_segment_distributions_{game.season}_wk{game.week}.json has no game {game.game_id}", ""])
    else:
        full, _, _ = block
        rows.append(["Distribution mean points", C.fmt_num(full.get("away_points_mean")), C.fmt_num(full.get("home_points_mean"))])
        summary = C.dist_summary(full.get("total_points_dist"))
        if summary:
            rows.append(["Sim total p10 / p50 / p90", f"{C.fmt_num(summary.get('p10'), 0)} / {C.fmt_num(summary.get('p50'), 0)} / {C.fmt_num(summary.get('p90'), 0)} ({int(summary['n'])} sims)", ""])
            facts["total_quantiles"] = {k: summary.get(k) for k in ("p10", "p50", "p90")}
        mismatch = _run_mismatch(row, full)
        if mismatch:
            rows.append([mismatch, "", ""])
            facts["distribution_run_mismatch"] = True
        total_chart = C.dist_chart(full.get("total_points_dist"), title=f"Simulated total points — {game.away} @ {game.home} (wk{game.week})", x_label="Total points", layer=Layer.GAME_SIM)
        if total_chart:
            charts.append(total_chart)
    return LayerEvidence(Layer.GAME_SIM, tables=[table(f"Game sim — {game.away} @ {game.home} (CFBD {game.game_id}, wk{game.week}, generated {generated[:10] or '—'})", ["Metric", game.away, game.home], rows, Layer.GAME_SIM)],
                         charts=charts, facts=facts, source="ncaaf:smartsim2_projections+segment_distributions", as_of=generated or C.mtime_iso(game.path))


def _ncaaf_environment(subject: PropSubject, game: NcaafGame | str, box: NcaafBox | None, home, away) -> LayerEvidence:
    if not home or not away:
        return absent(Layer.ENVIRONMENT, f"{ABSENT_NO_MATCH}:board teams do not resolve to CFBD schools ({subject.away_team} @ {subject.home_team})")
    team = box.team if box and box.team else None
    side = "home" if team and _fold(team) == _fold(home) else "away" if team and _fold(team) == _fold(away) else None
    rows: list[list[Any]] = [
        ["Venue", f"{home} home field ({side or 'side unknown'} for {team or subject.player_name}); neutral-site flag not published"],
        ["Kickoff", _kickoff_et(subject)],
    ]
    facts: dict[str, Any] = {"side": side}
    if not isinstance(game, str):
        facts["week"] = game.week
        if game.board_reversed:
            rows.append(["HOME/AWAY DISAGREE", f"board: {away} @ {home}; CFBD projection: {game.away} @ {game.home} — venue unverified"])
        proj_side = ("home" if _fold(team) == _fold(game.home) else "away") if team else None
        own_mean = game.row.get("home_score_mean" if proj_side == "home" else "away_score_mean") if proj_side else None
        opp_mean = game.row.get("away_score_mean" if proj_side == "home" else "home_score_mean") if proj_side else None
        if proj_side:
            rows.append(["Sim scoring environment (own / opponent points)", f"{C.fmt_num(own_mean)} / {C.fmt_num(opp_mean)} (total {C.fmt_num(game.row.get('total_mean'))})"])
            facts["sim_points"] = {"own": C.to_float(own_mean), "opp": C.to_float(opp_mean)}
        rows.append(["Sim rating inputs as of", str(game.row.get("rating_source") or "—")])
    if box is not None:
        for school in (away, home):
            played = sorted({(int(C.to_float(m.get("season")) or 0), int(C.to_float(m.get("week")) or 0))
                             for m in box.game_meta.values() if any(_fold(t) == _fold(school) for t in m["teams"])})
            if played:
                text = f"week {played[-1][1]} ({len(played)} game{'s' if len(played) != 1 else ''} in snapshot)"
                if not isinstance(game, str) and game.week - played[-1][1] > 1:
                    text += f" — {game.week - played[-1][1] - 1} week(s) off before week {game.week}"
                rows.append([f"{school} last played", text])
    rows.append(["Weather / injuries / market total", "not published for NCAAF (no weather, injury-report or game-line artifact on web)"])
    facts["unpublished"] = ["weather", "injuries", "market_total", "neutral_site"]
    return LayerEvidence(Layer.ENVIRONMENT, tables=[table(f"Game environment — {away} @ {home}", ["Factor", "Value"], rows, Layer.ENVIRONMENT)],
                         facts=facts, source="ncaaf:smartsim2_projections+player_game_stats_snapshot")


def build_ncaaf(subject: PropSubject) -> PropEvidence:
    evidence = PropEvidence(subject=subject, provider="football:ncaaf")
    stat, label = MARKETS.get(subject.market_key, (None, subject.market))
    season = _season(subject)
    home, away = _ncaaf_resolve(subject.home_team), _ncaaf_resolve(subject.away_team)
    game = _ncaaf_find_game(subject, season, home, away)
    box = _ncaaf_box(subject, home, away)

    # NOTHING IS PUBLISHED, AND WEB DOES NOT MODEL. `ncaaf/prop_model.py` is not
    # called here on purpose (worker split); the absence is the fact.
    evidence.set(absent(Layer.PLAYER_SIM, f"{ABSENT_NO_PRODUCER}:no NCAAF player projection artifact is published; web does not model (ncaaf/prop_model.py is not called)"))
    evidence.set(_ncaaf_recent_form(subject, stat, label, box, home, away))
    evidence.set(_ncaaf_matchup(subject, stat, label, box, home, away))
    evidence.set(_ncaaf_advanced(subject, stat, label, box, home, away))
    evidence.set(_ncaaf_game_sim(subject, game))
    evidence.set(_ncaaf_environment(subject, game, box, home, away))
    evidence.set(build_track_record(subject))
    return evidence
