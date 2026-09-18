"""NHL player-prop evidence.

SOURCES (all allowlisted in `artifact_publisher.HOT_ARTIFACT_PATTERNS`, all
measured on production web 2026-09-17 -- which carries LAST SEASON's files only;
NHL preseason starts 2026-09-19):

    props_recommendations_<date>.csv   date, player (full name), team (abbr), opp, market
                                       (SOG/GOALS/ASSISTS/POINTS), line, proj_lambda, p_over,
                                       over_price, under_price, book, side, price, ev ...
                                       Both roots: data/processed 01-25..06-10,
                                       source_artifacts 06-02..06-28. 06-10 and 06-12..06-28
                                       are HEADER-ONLY (158 bytes).
    predictions_<date>.csv             home, away (full names), proj_{home,away}_goals,
                                       model_total, p_{home,away}_ml, period{1,2,3}_*_proj,
                                       totals_line_used, p_over, p_under, puck-line probs, odds
    lineups_<date>.csv                 player_id, full_name, position, line_slot, pp_unit,
                                       pk_unit, proj_toi, confidence, team (abbr)
    player_rates_latest.csv            player_id, full_name ("B. Burns"), position, shot_weight,
                                       goal_weight, block_weight (per-game averages over the
                                       2025-26 regular season, `hockeysim_engine_reference.md`
                                       §2k), games, faceoff_weight/_draws/_games
    team_xg_latest.csv                 abbr, xgf60, xga60, games
    team_rates_latest.csv              abbr, shots_per_60, faceoff_win_pct, games
    team_special_teams_latest.csv      abbr, pp_pct, pk_pct, committed_per_game,
                                       pp_shot_index, pk_shot_index_allowed, block_rate_index ...
    team_elo_latest.csv                abbr, elo
    raw/player_game_stats.csv          gamePk, date (UTC), team (full name), player_id,
                                       player ("{'default': 'J. Eichel'}"), role, shots, goals,
                                       assists, blocked, timeOnIce, saves, shotsAgainst, decision

**P(OVER) IS POISSON ON THE MEAN, NOT A SIM DISTRIBUTION.** `build_nhl_artifacts.py:205`
replaces the boxscore sim's own empirical count with `Poisson(proj_lambda)`, so the
only probability this provider shows is labelled as the producer's pricing
assumption. No draws are published.

**THE JUNE PRODUCTION λ IS A CONSTANT.** Every SOG row of props_recommendations
2026-06-09/06-11/06-14 carries `proj_lambda 2.0`, every POINTS row 0.7, every
ASSISTS row 0.4 -- the empty-history returns of the vendor props models
(`vendor/nhl_betting_repo/nhl_betting/models/props.py:198,273,298`). 2026-05-27
carries 2.4 / 0.9 / 0.45, the vendor CLI's `_fallback_lambda`
(`vendor/.../cli.py:6307-6315`). A slate whose rows for a market all share one λ
is flagged on the table rather than presented as a per-player projection.

**SAVES AND BLOCKS HAVE NO PROP ROWS TO READ.** The producer writes a row only for a
collected book line (`build_props_for_date`), and the OddsAPI prop capture requests
`player_points,player_assists,player_goals,player_shots_on_goal` only
(`syndicate/local_nhl_odds.py:545`). A Kalshi `player_saves` board row therefore has
no `player_sim` source; that is a named `no_producer`, not a missing file.

**THE GAME LOG HAS A SCHEDULED WRITER SINCE `#674`.**
`nhl_source/source_artifacts/data/raw/player_game_stats.csv` was frozen at
2026-05-01..2026-06-15 (playoffs only, mtime 2026-06-19), written only by the vendor CLI
`collect_player_game_stats`. Now `syndicate/features/nhl/boxscore_log.py` adds every
finished game on each NHL refresh (`scripts/refresh_nhl_oddsapi.py`) and publishes the file.
Staleness is still stated from the newest game, not assumed. **A blank `shots` cell on a
skater row is ZERO shots**: the vendor parser's `stats.get("shots") or stats.get("sog")
or ... or p.get("shots")` (`collect.py:114`) turned `sog: 0` into None. Measured: 411 of
1,476 skater rows blank, and not one row carries `0.0` while 1.0..10.0 all occur. The new
writer writes 0 and repairs those blanks; the reader keeps treating a blank as 0 for any
copy written before that.

NOT PUBLISHED / NO PRODUCER (stated on the tables): `starting_goalies_<date>.csv`
(worker-side, not allowlisted), pregame goalie save % (only in-game,
`syndicate/features/nhl/live_lens.py`), rest / back-to-back, individual xG,
shots/60 and actual PP TOI.

NAMES. Board rows carry full names ("Jack Eichel") and full team names;
`lineups_<date>.csv` carries full names with `player_id`, which is the join key into
`player_rates_latest.csv` and the game log (both "J. Eichel"). Without a lineups
row the fallback is `initial_key` restricted to the board's two teams, refusing
when it stays ambiguous. Team names map through `local_nhl_odds._team_abbr`, the
strict map `bet_status_nhl` uses.
"""

from __future__ import annotations

import ast
import glob
import logging
import math
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
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

LOCAL_DIR = "nhl_source"
STALE_DAYS = 7
# Header-only dated files (a slate with no matched book lines, or no games) are
# skipped when falling back to an older date. Bounded: each is ~158 bytes.
MAX_EMPTY_SKIP = 60
GAME_LOG_RELATIVE = "raw/player_game_stats.csv"
NOT_PUBLISHED_PLAYER = "individual xG, shots/60, actual PP TOI"


@dataclass(frozen=True)
class NhlMarket:
    code: str                      # props_recommendations market code
    label: str
    role: str                      # "skater" | "goalie"
    log_columns: tuple[str, ...]   # player_game_stats columns summed
    rate_column: str | None        # player_rates_latest per-game column
    captured: bool                 # requested by the OddsAPI prop capture (local_nhl_odds.py:545)


MARKETS: dict[str, NhlMarket] = {
    "player_shots_on_goal": NhlMarket("SOG", "Shots on goal", "skater", ("shots",), "shot_weight", True),
    "player_goals": NhlMarket("GOALS", "Goals", "skater", ("goals",), "goal_weight", True),
    "player_assists": NhlMarket("ASSISTS", "Assists", "skater", ("assists",), None, True),
    "player_points": NhlMarket("POINTS", "Points", "skater", ("goals", "assists"), None, True),
    "player_blocked_shots": NhlMarket("BLOCKS", "Blocked shots", "skater", ("blocked",), "block_weight", False),
    "player_saves": NhlMarket("SAVES", "Saves", "goalie", ("saves",), None, False),
}
# Spellings `market_keys` passes through unchanged (anything `player_*`) but
# `bet_status_nhl._PROP_STATS` settles as the same stat.
_LOCAL_ALIASES = {
    "player_total_saves": "player_saves",
    "player_goalie_saves": "player_saves",
    "goalie_saves": "player_saves",
    "player_blocks": "player_blocked_shots",
}
# `bet_status_nhl._ANYTIME_GOAL_MARKETS`: goals > 0.5, yes/no.
_ANYTIME_GOAL_MARKETS = frozenset({
    "player_goal_scorer_anytime", "player_anytime_goal_scorer", "anytime_goal_scorer",
    "anytime_goalscorer", "player_anytime_goal", "anytime_goal", "goal_scorer_anytime",
})
_ANYTIME_LINE = 0.5


def resolve_market(market_key: str) -> tuple[str | None, float | None]:
    """(canonical market in MARKETS or None, default line for line-less markets)."""
    key = str(market_key or "").strip().lower()
    if key in _ANYTIME_GOAL_MARKETS:
        return "player_goals", _ANYTIME_LINE
    try:
        from syndicate.features.shared.market_keys import canonical_market_key

        canonical = canonical_market_key("nhl", key) or key
    except Exception:
        canonical = key
    if canonical.endswith("_alternate"):
        canonical = canonical[: -len("_alternate")]
    canonical = _LOCAL_ALIASES.get(canonical, canonical)
    return (canonical if canonical in MARKETS else None), None


def _team_abbr(value: Any) -> str | None:
    from syndicate.local_nhl_odds import _team_abbr as odds_team_abbr

    return odds_team_abbr(value)


def _days_between(earlier: str, later: str) -> int | None:
    try:
        return (datetime.fromisoformat(later[:10]) - datetime.fromisoformat(earlier[:10])).days
    except ValueError:
        return None


def _eastern_date(ts: datetime) -> str:
    try:
        from zoneinfo import ZoneInfo

        return ts.astimezone(ZoneInfo("America/New_York")).date().isoformat()
    except Exception:
        return (ts - timedelta(hours=5)).date().isoformat()


def _parse_ts(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def slate_dates(subject: PropSubject) -> list[str]:
    """The game's US-Eastern date first, then the board date.

    NHL files are keyed by the Eastern slate date (`local_nhl_odds._commence_date_et`).
    A 7 PM ET puck drop is `T23:00:00Z` or the NEXT UTC day, so the UTC date is
    never a candidate here: it would pick up the following night's slate.
    """
    dates: list[str] = []
    ts = _parse_ts(subject.commence_time)
    for value in (_eastern_date(ts) if ts else "", subject.selected_date):
        if value and value not in dates:
            dates.append(value)
    return dates


def slate_date(subject: PropSubject) -> str:
    dates = slate_dates(subject)
    return dates[0] if dates else ""


def _stale_note(what: str, iso: str, subject: PropSubject, *, threshold: int,
                suffix: str = " — not this game's data") -> tuple[str | None, int | None]:
    slate = slate_date(subject)
    days = _days_between(iso, slate)
    if days is None or days <= threshold:
        return None, days
    return f"STALE: {what} is dated {iso}, {days} days before this game ({slate}){suffix}", days


# ---------------------------------------------------------------------------
# Dated files
# ---------------------------------------------------------------------------


def _has_rows(path: Path) -> bool:
    try:
        with open(path, encoding="utf-8", newline="") as handle:
            handle.readline()
            for line in handle:
                if line.strip():
                    return True
    except OSError:
        return False
    return False


def pick_dated(stem: str, subject: PropSubject) -> tuple[Path, str, list[str]] | None:
    """`processed/<stem>_<date>.csv`: the game's own date if on disk, else the newest non-empty earlier file.

    The game's own file is authoritative even when header-only (its producer ran
    and matched nothing). An OLDER header-only file says nothing about this game,
    so the fallback skips it and records its date. Returns (path, iso, skipped).
    """
    for iso in slate_dates(subject):
        path = C.first_existing(LOCAL_DIR, f"processed/{stem}_{iso}.csv")
        if path is not None:
            return path, iso, []
    bound = slate_date(subject)
    found: dict[str, str] = {}
    pattern = re.compile(rf"^{re.escape(stem)}_(\d{{4}}-\d{{2}}-\d{{2}})\.csv$")
    for root in C.sport_roots(LOCAL_DIR):
        for raw in glob.glob(str(root / "processed" / f"{stem}_*.csv")):
            match = pattern.match(os.path.basename(raw))
            if not match:
                continue
            iso = match.group(1)
            if bound and iso > bound:
                continue
            found.setdefault(iso, raw)
    skipped: list[str] = []
    for iso in sorted(found, reverse=True):
        path = Path(found[iso])
        if _has_rows(path):
            return path, iso, skipped
        skipped.append(iso)
        if len(skipped) >= MAX_EMPTY_SKIP:
            break
    return None


def _read_rows(path: Path | None) -> list[dict[str, str]]:
    if path is None:
        return []
    try:
        return list(C.iter_csv(path))
    except Exception:
        logger.exception("prop_evidence nhl: unreadable %s", path)
        return []


def _team_table(name: str) -> tuple[dict[str, dict[str, float]], Path | None]:
    path = C.first_existing(LOCAL_DIR, f"processed/{name}")
    out: dict[str, dict[str, float]] = {}
    for row in _read_rows(path):
        abbr = str(row.get("abbr") or "").strip().upper()
        if abbr:
            out[abbr] = {k: v for k, v in ((k, C.to_float(v)) for k, v in row.items() if k != "abbr") if v is not None}
    return out, path


def _rank(table_rows: dict[str, dict[str, float]], abbr: str, field: str, *, descending: bool) -> str:
    value = (table_rows.get(abbr) or {}).get(field)
    ordered = sorted((v[field] for v in table_rows.values() if v.get(field) is not None), reverse=descending)
    if value is None or value not in ordered:
        return "—"
    return f"{ordered.index(value) + 1} of {len(ordered)}"


# ---------------------------------------------------------------------------
# Player identity
# ---------------------------------------------------------------------------


@dataclass
class Identity:
    player_id: str | None = None
    team: str | None = None           # abbr, only when it is one of the board's two teams
    seen_team: str | None = None      # abbr the newest file carried, even if not in this game
    lineup: dict[str, str] | None = None
    lineup_path: Path | None = None
    lineup_date: str | None = None
    ambiguous: bool = False
    confidence_uniform: bool = False


def _board_teams(subject: PropSubject) -> tuple[str | None, str | None]:
    return _team_abbr(subject.home_team), _team_abbr(subject.away_team)


def _resolve_identity(subject: PropSubject, lineups: tuple[Path, str, list[str]] | None) -> Identity:
    home, away = _board_teams(subject)
    game_teams = {t for t in (home, away) if t}
    ident = Identity()
    if lineups is None:
        return ident
    path, iso, _ = lineups
    ident.lineup_path, ident.lineup_date = path, iso
    rows = _read_rows(path)
    ident.confidence_uniform = len(rows) > 1 and len({str(r.get("confidence") or "") for r in rows}) == 1
    matches = [r for r in rows if C.names_match(r.get("full_name"), subject.player_name)]
    if not matches:
        return ident
    in_game = [r for r in matches if str(r.get("team") or "").upper() in game_teams] or matches
    ids = {str(r.get("player_id") or "").strip() for r in in_game}
    if len(ids) != 1:
        ident.ambiguous = True
        return ident
    row = in_game[0]
    ident.player_id = next(iter(ids)) or None
    ident.lineup = row
    ident.seen_team = str(row.get("team") or "").upper() or None
    if ident.seen_team in game_teams:
        ident.team = ident.seen_team
    return ident


# ---------------------------------------------------------------------------
# Game log
# ---------------------------------------------------------------------------


def _log_name(raw: Any) -> str:
    text = str(raw or "").strip()
    if text.startswith("{"):
        try:
            parsed = ast.literal_eval(text)
            if isinstance(parsed, dict) and parsed.get("default"):
                return str(parsed["default"])
        except (ValueError, SyntaxError):
            pass
    return text


def _toi_minutes(value: Any) -> float | None:
    text = str(value or "").strip()
    match = re.match(r"^(\d+):(\d{2})$", text)
    if not match:
        return None
    return int(match.group(1)) + int(match.group(2)) / 60.0


def game_log_path() -> Path | None:
    return C.first_existing(LOCAL_DIR, GAME_LOG_RELATIVE)


@dataclass
class GameLog:
    path: Path | None
    games: list[dict[str, Any]]       # this player's PLAYED games before this game, newest first
    window: tuple[str, str] | None    # (first, last) Eastern game date in the whole file
    player_name: str | None = None
    ambiguous: bool = False
    matched_by: str = "player_id"


def _game_log(subject: PropSubject, ident: Identity, market: NhlMarket | None) -> GameLog:
    path = game_log_path()
    if path is None:
        return GameLog(None, [], None)
    home, away = _board_teams(subject)
    game_teams = {t for t in (home, away) if t}
    cutoff = _parse_ts(subject.commence_time)
    slate = slate_date(subject)
    teams_by_game: dict[str, set[str]] = {}
    dates: list[str] = []
    candidates: dict[str, list[dict[str, Any]]] = {}
    role = market.role if market else None
    wanted_initial = C.initial_key(subject.player_name)
    for row in _read_rows(path):
        game_pk = str(row.get("gamePk") or "").strip()
        team = _team_abbr(row.get("team")) or str(row.get("team") or "").strip().upper()
        ts = _parse_ts(row.get("date"))
        if game_pk and team:
            teams_by_game.setdefault(game_pk, set()).add(team)
        if ts is None:
            continue
        date_et = _eastern_date(ts)
        dates.append(date_et)
        player_id = str(row.get("player_id") or "").strip()
        if ident.player_id:
            if player_id != ident.player_id:
                continue
        elif C.initial_key(_log_name(row.get("player"))) != wanted_initial:
            continue
        if role and str(row.get("role") or "").strip().lower() != role:
            continue
        # Only games BEFORE this one: the board's kickoff when known, else its slate date.
        if cutoff is not None:
            if ts >= cutoff:
                continue
        elif slate and date_et >= slate:
            continue
        toi = _toi_minutes(row.get("timeOnIce"))
        if not toi:
            continue  # a dressed backup goalie (00:00) did not play: books void, not a miss
        is_skater = str(row.get("role") or "").strip().lower() == "skater"
        shots = C.to_float(row.get("shots"))
        if shots is None and is_skater:
            shots = 0.0  # collect.py:114 drops sog == 0 to None; see module docstring
        entry = {
            "game_pk": game_pk, "ts": ts, "date": date_et, "team": team, "player_id": player_id,
            "name": _log_name(row.get("player")), "role": str(row.get("role") or ""), "toi": toi,
            "shots": shots, "goals": C.to_float(row.get("goals")), "assists": C.to_float(row.get("assists")),
            "blocked": C.to_float(row.get("blocked")), "saves": C.to_float(row.get("saves")),
            "shots_against": C.to_float(row.get("shotsAgainst")), "decision": str(row.get("decision") or ""),
        }
        candidates.setdefault(player_id or entry["name"], []).append(entry)
    window = (min(dates), max(dates)) if dates else None
    if not ident.player_id and len(candidates) > 1:
        in_game = {pid: rows for pid, rows in candidates.items() if any(r["team"] in game_teams for r in rows)}
        if len(in_game) != 1:
            return GameLog(path, [], window, ambiguous=True)
        candidates = in_game
    games = next(iter(candidates.values()), [])
    for game in games:
        others = teams_by_game.get(game["game_pk"], set()) - {game["team"]}
        game["opponent"] = next(iter(others), "")
        game["type"] = "playoff" if game["game_pk"][4:6] == "03" else "regular" if game["game_pk"][4:6] == "02" else ""
    games.sort(key=lambda g: g["ts"], reverse=True)
    return GameLog(path, games, window, player_name=games[0]["name"] if games else None,
                   matched_by="player_id" if ident.player_id else "initial_key")


def _stat(game: dict[str, Any], columns: tuple[str, ...]) -> float | None:
    values = [game.get(col) for col in columns]
    if any(v is None for v in values):
        return None
    return float(sum(values))  # type: ignore[arg-type]


def _effective_side(side: str | None) -> str | None:
    return {"yes": "over", "no": "under"}.get(str(side or ""), side)


# ---------------------------------------------------------------------------
# Poisson labelling (the producer's assumption, never a sim)
# ---------------------------------------------------------------------------


def _poisson_pmf(mean: float, k: int) -> float:
    if mean <= 0:
        return 1.0 if k == 0 else 0.0
    return math.exp(-mean + k * math.log(mean) - math.lgamma(k + 1))


def poisson_prob_under(mean: float | None, line: float | None) -> float | None:
    """P(X < line) for Poisson(mean) -- the complement of over, less the push mass."""
    if mean is None or line is None or mean < 0:
        return None
    k_max = math.ceil(line) - 1
    return max(0.0, min(1.0, sum(_poisson_pmf(mean, k) for k in range(0, k_max + 1))))


def poisson_chart(mean: float, line: float | None, *, player: str, label: str, file_label: str) -> dict[str, Any]:
    spread = 4.0 * math.sqrt(max(mean, 0.25))
    lo = max(0, int(math.floor(mean - spread)))
    hi = int(math.ceil(mean + spread))
    if line is not None:
        lo, hi = min(lo, max(0, int(math.floor(line)))), max(hi, int(math.ceil(line)) + 1)
    hi = min(hi, lo + C.MAX_CHART_POINTS - 1)
    points = [{"x": str(k), "y": round(100.0 * _poisson_pmf(mean, k), 2)} for k in range(lo, hi + 1)]
    marker = {"x": C.fmt_line(line), "label": f"Line {C.fmt_line(line)}"} if line is not None else None
    return chart(
        f"Poisson(λ={mean:g}) — the producer's pricing assumption, not a sim distribution — {player} {label} ({file_label})",
        label, "% probability (Poisson)", points, Layer.PLAYER_SIM, marker=marker,
    )


# ---------------------------------------------------------------------------
# Layers
# ---------------------------------------------------------------------------


def _player_sim(subject: PropSubject, market: NhlMarket | None, line: float | None,
                props: tuple[Path, str, list[str]] | None) -> LayerEvidence:
    if market is None:
        return absent(Layer.PLAYER_SIM, f"{ABSENT_NOT_APPLICABLE}:market {subject.market} has no NHL projection mapping")
    if props is None:
        return absent(Layer.PLAYER_SIM, f"{ABSENT_NO_ARTIFACT}:no props_recommendations_<date>.csv on or before {slate_date(subject)}")
    path, iso, skipped = props
    rows = _read_rows(path)
    mine = [r for r in rows if str(r.get("market") or "").strip().upper() == market.code
            and C.names_match(r.get("player"), subject.player_name)]
    if not mine:
        if not market.captured and not any(str(r.get("market") or "").strip().upper() == market.code for r in rows):
            return absent(Layer.PLAYER_SIM, (
                f"{ABSENT_NO_PRODUCER}:props_recommendations has a {market.code} row only for a collected book line, "
                "and the OddsAPI prop capture requests no such market (local_nhl_odds.py:545)"))
        detail = "header-only" if not rows else f"{len(rows)} rows, none for this player"
        return absent(Layer.PLAYER_SIM, f"{ABSENT_NO_MATCH}:{subject.player_name} {market.code} not in props_recommendations_{iso}.csv ({detail})")
    row = next((r for r in mine if line is not None and C.to_float(r.get("line")) == line), mine[0])
    mean = C.to_float(row.get("proj_lambda"))
    if mean is None:
        mean = C.to_float(row.get("proj"))
    if mean is None:
        return absent(Layer.PLAYER_SIM, f"{ABSENT_NO_MATCH}:props_recommendations_{iso}.csv row for {subject.player_name} has no proj_lambda")
    file_line = C.to_float(row.get("line"))
    p_over = C.poisson_prob_over(mean, line)
    p_under = poisson_prob_under(mean, line)
    market_lambdas = [C.to_float(r.get("proj_lambda")) for r in rows if str(r.get("market") or "").strip().upper() == market.code]
    market_lambdas = [v for v in market_lambdas if v is not None]
    degenerate = len(market_lambdas) >= 2 and len(set(market_lambdas)) == 1

    table_rows: list[list[Any]] = [
        ["Producer mean λ (proj_lambda)", C.fmt_num(mean, 2)],
        ["P(over) basis", "Poisson(λ) on the producer's mean — its pricing assumption, not simulated draws"],
    ]
    if line is not None:
        table_rows.append([f"P(over {C.fmt_line(line)}) — Poisson(λ)", C.fmt_pct(p_over)])
        table_rows.append([f"P(under {C.fmt_line(line)}) — Poisson(λ)", C.fmt_pct(p_under)])
    if file_line is not None and file_line != line:
        table_rows.append([f"File's own line {C.fmt_line(file_line)}: published p_over (Poisson)", C.fmt_pct(row.get("p_over"))])
    table_rows.append(["File row (book, side, price)", f"{row.get('book') or '—'}, {row.get('side') or '—'} {row.get('price') or ''}".strip()])
    if degenerate:
        table_rows.append([f"DEGENERATE SLATE: all {len(market_lambdas)} {market.code} rows in this file carry λ {C.fmt_num(market_lambdas[0], 2)}",
                           "one constant for every player — not a per-player projection"])
    stale, stale_days = _stale_note(f"props_recommendations_{iso}.csv", iso, subject, threshold=0)
    if stale:
        table_rows.append([stale, ""])
    if skipped:
        table_rows.append([f"Newer header-only files skipped ({len(skipped)})", ", ".join(skipped[:5]) + (" …" if len(skipped) > 5 else "")])
    title = (f"Player sim — {subject.player_name} {market.label} {C.fmt_line(line)} "
             f"({row.get('team') or ''}, props_recommendations_{iso})")
    facts = {
        "market_code": market.code, "file_date": iso, "lambda": mean, "prob_over": p_over, "prob_under": p_under,
        "prob_basis": "poisson_on_mean", "published_line": file_line, "published_p_over": C.to_float(row.get("p_over")),
        "degenerate": degenerate, "degenerate_rows": len(market_lambdas) if degenerate else 0,
        "stale_days": stale_days, "skipped_empty_files": skipped, "team": row.get("team"),
    }
    return LayerEvidence(
        Layer.PLAYER_SIM,
        tables=[table(title, ["Measure", "Value"], table_rows, Layer.PLAYER_SIM)],
        charts=[poisson_chart(mean, line, player=subject.player_name, label=market.label, file_label=f"props_recommendations_{iso}")],
        facts=facts, source="nhl:props_recommendations", as_of=iso,
    )


def _recent_form(subject: PropSubject, market: NhlMarket | None, line: float | None, log: GameLog) -> LayerEvidence:
    if market is None:
        return absent(Layer.RECENT_FORM, f"{ABSENT_NOT_APPLICABLE}:market {subject.market} has no box-score stat mapping")
    if log.path is None:
        return absent(Layer.RECENT_FORM, (
            f"{ABSENT_NO_ARTIFACT}:nhl_source {GAME_LOG_RELATIVE} not on this disk "
            "(written by the NHL refresh on refresh-worker, syndicate/features/nhl/boxscore_log.py)"))
    window = f"{log.window[0]}..{log.window[1]}" if log.window else "empty"
    if log.ambiguous:
        return absent(Layer.RECENT_FORM, f"{ABSENT_NO_MATCH}:{subject.player_name} is ambiguous in player_game_stats.csv (initial + surname) and no lineups row fixes the id")
    if not log.games:
        return absent(Layer.RECENT_FORM, f"{ABSENT_NO_MATCH}:no played {market.role} games for {subject.player_name} before this game in player_game_stats.csv (covers {window})")
    last = log.games[:C.LAST_N_GAMES]
    values = [_stat(g, market.log_columns) for g in last]
    side = _effective_side(subject.side)
    rate = C.hit_rate(values, line, side)
    rows: list[list[Any]] = []
    for game, value in zip(last, values):
        rows.append([game["date"], game.get("opponent") or "", C.fmt_num(game["toi"], 1), C.fmt_num(value, 0)])
    clean = [v for v in values if v is not None]
    rows.append([f"L{len(last)} avg", "", C.fmt_num(sum(g["toi"] for g in last) / len(last), 1),
                 C.fmt_num(sum(clean) / len(clean), 2) if clean else "—"])
    if rate:
        rows.append([f"Hit rate vs {C.fmt_line(line)}", "", "", C.hit_rate_text(rate)])
    types = {g.get("type") for g in last}
    if types == {"playoff"}:
        rows.append([f"All {len(last)} games are playoff games", "", "", ""])
    if log.matched_by != "player_id":
        rows.append([f"Matched by initial + surname ({log.player_name}); no lineups id", "", "", ""])
    stale, stale_days = _stale_note("newest game", last[0]["date"], subject, threshold=STALE_DAYS, suffix="")
    if stale:
        rows.append([f"{stale}; game log covers {window}", "", "", ""])
    series = [{"date": g["date"], "value": v} for g, v in zip(last, values)]
    charts = [c for c in [C.form_chart(series, stat_key="value", stat_label=market.label, player=subject.player_name, line=line)] if c]
    return LayerEvidence(
        Layer.RECENT_FORM,
        tables=[table(f"Last {len(last)} games — {subject.player_name} (player_game_stats, through {last[0]['date']})",
                      ["Date", "Opp", "TOI", market.label], rows, Layer.RECENT_FORM)],
        charts=charts,
        facts={"games": len(last), "hit_rate": rate, "values": values, "newest_game": last[0]["date"],
               "stale_days": stale_days, "log_window": list(log.window) if log.window else None,
               "game_types": sorted(t for t in types if t), "matched_by": log.matched_by},
        source="nhl:player_game_stats", as_of=last[0]["date"],
    )


def _player_team(ident: Identity, log: GameLog, props_team: str | None, subject: PropSubject) -> tuple[str | None, str | None, list[str]]:
    """(team, side, teams seen) -- the first source that places the player on one of this game's two teams."""
    home, away = _board_teams(subject)
    seen: list[str] = []
    for team in (props_team, ident.seen_team, log.games[0]["team"] if log.games else None):
        team = str(team or "").strip().upper()
        if not team:
            continue
        seen.append(team)
        if team == home:
            return team, "home", seen
        if team == away:
            return team, "away", seen
    return None, None, seen


def _matchup(subject: PropSubject, market: NhlMarket | None, line: float | None, team: str | None, log: GameLog,
             seen: list[str], teams: dict[str, tuple[dict[str, dict[str, float]], Path | None]]) -> LayerEvidence:
    home, away = _board_teams(subject)
    if team is None:
        return absent(Layer.MATCHUP, (
            f"{ABSENT_NO_MATCH}:{subject.player_name}'s team is not resolvable to {away or subject.away_team} @ "
            f"{home or subject.home_team} (files list {', '.join(dict.fromkeys(seen)) or 'no team'})"))
    opponent = away if team == home else home
    tables: list[dict[str, Any]] = []
    facts: dict[str, Any] = {"team": team, "opponent": opponent}
    if market is not None and log.games:
        vs = [g for g in log.games if g.get("opponent") == opponent]
        if vs:
            rows = [[g["date"], C.fmt_num(g["toi"], 1), C.fmt_num(_stat(g, market.log_columns), 0)] for g in vs[:8]]
            rate = C.hit_rate([_stat(g, market.log_columns) for g in vs], line, _effective_side(subject.side))
            if rate:
                rows.append([f"Hit rate vs {C.fmt_line(line)}", "", C.hit_rate_text(rate)])
            facts["vs_opponent"] = {"games": len(vs), "hit_rate": rate}
            tables.append(table(f"{subject.player_name} vs {opponent} ({len(vs)} meeting{'s' if len(vs) != 1 else ''}, player_game_stats)",
                                ["Date", "TOI", market.label], rows, Layer.MATCHUP))
    xg, _ = teams["team_xg_latest.csv"]
    rates, _ = teams["team_rates_latest.csv"]
    special, _ = teams["team_special_teams_latest.csv"]
    profile: list[list[Any]] = []

    def add(label: str, source: dict[str, dict[str, float]], abbr: str, field: str, descending: bool, note: str, digits: int = 2) -> None:
        value = (source.get(abbr) or {}).get(field)
        if value is None:
            return
        shown = C.fmt_pct(value) if field.endswith("_pct") else C.fmt_num(value, digits)
        profile.append([label, shown, f"{_rank(source, abbr, field, descending=descending)} ({note})"])

    role = market.role if market else "skater"
    if role == "goalie":
        add(f"xG for per 60 ({opponent})", xg, opponent, "xgf60", True, "1 = most dangerous")
        add(f"Shots per 60 ({opponent})", rates, opponent, "shots_per_60", True, "1 = most shots", 1)
        add(f"Power play % ({opponent})", special, opponent, "pp_pct", True, "1 = best")
        add(f"PP shot index ({opponent})", special, opponent, "pp_shot_index", True, "1 = most PP shots")
        add(f"Penalties committed per game ({team}, own)", special, team, "committed_per_game", True, "1 = most")
    elif market is not None and market.code == "BLOCKS":
        add(f"Shots per 60 ({opponent})", rates, opponent, "shots_per_60", True, "1 = most shots to block", 1)
        add(f"xG for per 60 ({opponent})", xg, opponent, "xgf60", True, "1 = most dangerous")
    else:
        add(f"xG against per 60 ({opponent})", xg, opponent, "xga60", False, "1 = stingiest")
        add(f"Penalty kill % ({opponent})", special, opponent, "pk_pct", True, "1 = best PK")
        add(f"PK shots-allowed index ({opponent})", special, opponent, "pk_shot_index_allowed", False, "1 = fewest")
        add(f"Penalties committed per game ({opponent})", special, opponent, "committed_per_game", True, "1 = most PP chances")
        if market is None or market.code == "SOG":
            add(f"Shot-block rate index ({opponent})", special, opponent, "block_rate_index", True, "1 = blocks most")
    if profile:
        games = (xg.get(opponent) or special.get(opponent) or {}).get("games")
        tables.append(table(f"Opponent profile — {opponent} (team_xg / team_rates / team_special_teams _latest, {C.fmt_num(games, 0)} games)",
                            ["Measure", "Value", "League rank"], profile, Layer.MATCHUP))
        facts["opponent_profile"] = {
            "xg": xg.get(opponent), "rates": rates.get(opponent), "special_teams": special.get(opponent)}
    if not tables:
        return absent(Layer.MATCHUP, f"{ABSENT_NO_MATCH}:no meetings with {opponent} and no team_xg/team_rates/team_special_teams row for {opponent}")
    return LayerEvidence(Layer.MATCHUP, tables=tables, facts=facts, source="nhl:player_game_stats+team_*_latest",
                         as_of=C.mtime_iso(teams["team_xg_latest.csv"][1]))


def _player_rates_row(ident: Identity, subject: PropSubject) -> tuple[dict[str, str] | None, Path | None, bool]:
    path = C.first_existing(LOCAL_DIR, "processed/player_rates_latest.csv")
    if path is None:
        return None, None, False
    rows = _read_rows(path)
    if ident.player_id:
        hit = next((r for r in rows if str(r.get("player_id") or "").strip() == ident.player_id), None)
        return hit, path, False
    wanted = C.initial_key(subject.player_name)
    hits = [r for r in rows if C.initial_key(r.get("full_name")) == wanted]
    if len(hits) > 1:
        return None, path, True
    return (hits[0] if hits else None), path, False


def _advanced(subject: PropSubject, market: NhlMarket | None, ident: Identity, log: GameLog) -> LayerEvidence:
    role = market.role if market else "skater"
    rows: list[list[Any]] = []
    facts: dict[str, Any] = {}
    sources: list[str] = []
    rate_row, rate_path, rate_ambiguous = (None, None, False) if role == "goalie" else _player_rates_row(ident, subject)
    if rate_row:
        games = C.to_float(rate_row.get("games"))
        for label, field in (("Shots on goal per game", "shot_weight"), ("Goals per game", "goal_weight"),
                             ("Blocked shots per game", "block_weight")):
            mark = " ◀ this market" if market is not None and market.rate_column == field else ""
            rows.append([f"{label} (season, {C.fmt_num(games, 0)} GP){mark}", C.fmt_num(rate_row.get(field), 3)])
        faceoff = C.to_float(rate_row.get("faceoff_weight"))
        if faceoff is not None:
            rows.append(["Faceoff win % (draws)", f"{C.fmt_pct(faceoff)} ({C.fmt_num(rate_row.get('faceoff_draws'), 0)})"])
        facts["player_rates"] = {k: C.to_float(rate_row.get(k)) for k in ("shot_weight", "goal_weight", "block_weight", "games", "faceoff_weight")}
        sources.append("player_rates_latest")
    elif rate_ambiguous:
        rows.append(["Season per-game rates", "ambiguous name in player_rates_latest.csv (initial + surname) and no lineups id"])
    lineup = ident.lineup
    if lineup:
        rows.append(["Line slot", lineup.get("line_slot") or "—"])
        if role != "goalie":
            rows.append(["Power-play unit", C.fmt_num(lineup.get("pp_unit"), 0) if C.to_float(lineup.get("pp_unit")) else "none"])
            rows.append(["Penalty-kill unit", C.fmt_num(lineup.get("pk_unit"), 0) if C.to_float(lineup.get("pk_unit")) else "none"])
        rows.append(["Projected TOI (min)", C.fmt_num(lineup.get("proj_toi"), 1)])
        confidence = C.fmt_num(lineup.get("confidence"), 2)
        if ident.confidence_uniform:
            confidence += " (same value on every row of the file — a default, not a measured confidence)"
        rows.append(["Lineup confidence", confidence])
        facts["lineup"] = {k: lineup.get(k) for k in ("line_slot", "pp_unit", "pk_unit", "proj_toi", "confidence", "team")}
        sources.append(f"lineups_{ident.lineup_date}")
        stale, _ = _stale_note(f"lineups_{ident.lineup_date}.csv", ident.lineup_date or "", subject, threshold=0)
        if stale:
            rows.append([stale, ""])
    recent = log.games[:C.LAST_N_GAMES]
    if recent:
        rows.append([f"Actual TOI, last {len(recent)} (min)", C.fmt_num(sum(g["toi"] for g in recent) / len(recent), 1)])
        facts["recent_toi"] = [round(g["toi"], 2) for g in recent]
        if role == "goalie":
            against = [g["shots_against"] for g in recent if g.get("shots_against") is not None]
            saves = [g["saves"] for g in recent if g.get("saves") is not None and g.get("shots_against") is not None]
            if against:
                rows.append([f"Shots against per game, last {len(against)}", C.fmt_num(sum(against) / len(against), 1)])
                if sum(against) > 0:
                    rows.append([f"Save % (actual), last {len(against)}", C.fmt_pct(sum(saves) / sum(against), 1)])
        sources.append("player_game_stats")
    if not sources:
        # An ambiguity note alone is not evidence: the layer is absent, and says why.
        why = "ambiguous (initial + surname) in player_rates_latest.csv with no lineups id" if rate_ambiguous \
            else "not in player_rates_latest.csv, lineups or player_game_stats.csv"
        return absent(Layer.ADVANCED, f"{ABSENT_NO_MATCH}:{subject.player_name} {why}")
    if role == "goalie":
        rows.append(["Not published", "pregame goalie save % / GSAx (no producer; player_rates rates skaters only)"])
    else:
        rows.append(["Not published", f"{NOT_PUBLISHED_PLAYER} (no producer)"])
    return LayerEvidence(
        Layer.ADVANCED,
        tables=[table(f"Role and usage — {subject.player_name} ({', '.join(sources)})", ["Measure", "Value"], rows, Layer.ADVANCED)],
        facts=facts, source="nhl:" + "+".join(sources), as_of=C.mtime_iso(rate_path) or ident.lineup_date,
    )


def _find_prediction(subject: PropSubject, predictions: tuple[Path, str, list[str]] | None) -> tuple[dict[str, str] | None, str | None]:
    if predictions is None:
        return None, None
    home, away = _board_teams(subject)
    path, iso, _ = predictions
    if not home or not away:
        return None, iso
    for row in _read_rows(path):
        if _team_abbr(row.get("home")) == home and _team_abbr(row.get("away")) == away:
            return row, iso
    return None, iso


def _game_sim(subject: PropSubject, predictions: tuple[Path, str, list[str]] | None, row: dict[str, str] | None) -> LayerEvidence:
    home, away = _board_teams(subject)
    if predictions is None:
        return absent(Layer.GAME_SIM, f"{ABSENT_NO_ARTIFACT}:no predictions_<date>.csv on or before {slate_date(subject)}")
    _, iso, _ = predictions
    if row is None:
        reason = ABSENT_NO_MATCH if iso in slate_dates(subject) else ABSENT_NO_ARTIFACT
        return absent(Layer.GAME_SIM, (
            f"{reason}:predictions_{iso}.csv has no {away or subject.away_team} @ {home or subject.home_team} row"
            + ("" if reason == ABSENT_NO_MATCH else f" (no file for {slate_date(subject)})")))
    a, h = away or "Away", home or "Home"

    def pair(away_key: str, home_key: str, fmt) -> list[Any]:
        return [fmt(row.get(away_key)), fmt(row.get(home_key))]

    periods = lambda side: " / ".join(C.fmt_num(row.get(f"period{p}_{side}_proj"), 2) for p in (1, 2, 3))  # noqa: E731
    rows: list[list[Any]] = [
        ["Win probability"] + pair("p_away_ml", "p_home_ml", C.fmt_pct),
        ["Projected goals"] + pair("proj_away_goals", "proj_home_goals", lambda v: C.fmt_num(v, 2)),
        ["Projected goals P1 / P2 / P3", periods("away"), periods("home")],
        ["Model total vs line used", f"{C.fmt_num(row.get('model_total'), 2)} vs {C.fmt_num(row.get('totals_line_used'), 1)}", ""],
        ["P(total over / under the line)", f"{C.fmt_pct(row.get('p_over'))} / {C.fmt_pct(row.get('p_under'))}", ""],
        ["Puck line P(away +1.5) / P(home -1.5)"] + pair("p_away_pl_+1.5", "p_home_pl_-1.5", C.fmt_pct),
        ["Moneyline odds in the file"] + pair("away_ml_odds", "home_ml_odds", lambda v: C.fmt_num(v, 0)),
    ]
    if row.get("p_f10_yes"):
        rows.append(["P(goal in first 10 min)", C.fmt_pct(row.get("p_f10_yes")), ""])
    if row.get("anchor_state"):
        rows.append(["Market anchoring", f"{row.get('anchor_state')} at weight {row.get('anchor_weight') or '—'}",
                     f"raw P(home) {C.fmt_pct(row.get('p_home_ml_raw'))}"])
    stale, stale_days = _stale_note(f"predictions_{iso}.csv", iso, subject, threshold=0)
    if stale:
        rows.append([stale, "", ""])
    points = []
    for p in (1, 2, 3):
        points.append({"x": f"P{p} {a}", "y": C.to_float(row.get(f"period{p}_away_proj")) or 0.0})
        points.append({"x": f"P{p} {h}", "y": C.to_float(row.get(f"period{p}_home_proj")) or 0.0})
    charts = [chart(f"Projected goals by period — {a} @ {h} (predictions_{iso})", "Period / team", "Goals", points, Layer.GAME_SIM)] \
        if any(p["y"] for p in points) else []
    facts = {k: C.to_float(row.get(k)) for k in ("proj_home_goals", "proj_away_goals", "model_total", "p_home_ml",
                                                   "p_away_ml", "totals_line_used", "p_over", "p_under")}
    facts.update({"file_date": iso, "stale_days": stale_days})
    return LayerEvidence(Layer.GAME_SIM,
                         tables=[table(f"Game sim — {a} @ {h} (predictions_{iso})", ["Metric", a, h], rows, Layer.GAME_SIM)],
                         charts=charts, facts=facts, source="nhl:predictions", as_of=iso)


def _environment(subject: PropSubject, side: str | None,
                 teams: dict[str, tuple[dict[str, dict[str, float]], Path | None]]) -> LayerEvidence:
    home, away = _board_teams(subject)
    if not home or not away:
        return absent(Layer.ENVIRONMENT, f"{ABSENT_NO_MATCH}:team names {subject.away_team!r} @ {subject.home_team!r} do not map to NHL abbreviations")
    elo, elo_path = teams["team_elo_latest.csv"]
    special, _ = teams["team_special_teams_latest.csv"]
    rows: list[list[Any]] = []
    facts: dict[str, Any] = {"side": side}
    if elo.get(away) or elo.get(home):
        rows.append(["Team Elo (team_elo_latest)", C.fmt_num((elo.get(away) or {}).get("elo"), 0), C.fmt_num((elo.get(home) or {}).get("elo"), 0)])
        facts["elo"] = {"away": (elo.get(away) or {}).get("elo"), "home": (elo.get(home) or {}).get("elo")}
    if special.get(away) or special.get(home):
        sa, sh = special.get(away) or {}, special.get(home) or {}
        rows.append([f"Power play % / penalty kill % ({C.fmt_num(sa.get('games') or sh.get('games'), 0)} games)",
                     f"{C.fmt_pct(sa.get('pp_pct'))} / {C.fmt_pct(sa.get('pk_pct'))}", f"{C.fmt_pct(sh.get('pp_pct'))} / {C.fmt_pct(sh.get('pk_pct'))}"])
        rows.append(["Penalties committed per game", C.fmt_num(sa.get("committed_per_game"), 2), C.fmt_num(sh.get("committed_per_game"), 2)])
        facts["special_teams"] = {"away": sa, "home": sh}
    if not rows:
        return absent(Layer.ENVIRONMENT, f"{ABSENT_NO_ARTIFACT}:no team_elo_latest/team_special_teams_latest row for {away} or {home}")
    rows.append(["Player's side", "player's team" if side == "away" else "", "player's team" if side == "home" else ""]
                if side else ["Player's side", "unresolved", "unresolved"])
    rows.append(["Starting goalies", "not published: starting_goalies_<date>.csv is worker-side and not allowlisted to web", ""])
    rows.append(["Goalie save % (pregame)", "no producer: save % exists only in-game (nhl/live_lens.py)", ""])
    rows.append(["Rest / back-to-back", "no producer", ""])
    return LayerEvidence(Layer.ENVIRONMENT,
                         tables=[table(f"Game environment — {away} @ {home}", ["Factor", away, home], rows, Layer.ENVIRONMENT)],
                         facts=facts, source="nhl:team_elo+team_special_teams", as_of=C.mtime_iso(elo_path))


def build(subject: PropSubject) -> PropEvidence:
    evidence = PropEvidence(subject=subject, provider="nhl")
    canonical, default_line = resolve_market(subject.market_key)
    market = MARKETS.get(canonical) if canonical else None
    line = subject.line if subject.line is not None else default_line

    props = pick_dated("props_recommendations", subject)
    lineups = pick_dated("lineups", subject)
    predictions = pick_dated("predictions", subject)
    ident = _resolve_identity(subject, lineups)
    log = _game_log(subject, ident, market)
    teams = {name: _team_table(name) for name in (
        "team_xg_latest.csv", "team_rates_latest.csv", "team_special_teams_latest.csv", "team_elo_latest.csv")}

    player_sim = _player_sim(subject, market, line, props)
    evidence.set(player_sim)
    evidence.set(_recent_form(subject, market, line, log))
    team, side, seen = _player_team(ident, log, player_sim.facts.get("team") if player_sim.filled else None, subject)
    evidence.set(_matchup(subject, market, line, team, log, seen, teams))
    evidence.set(_advanced(subject, market, ident, log))
    prediction, _ = _find_prediction(subject, predictions)
    evidence.set(_game_sim(subject, predictions, prediction))
    evidence.set(_environment(subject, side, teams))
    evidence.set(build_track_record(subject))
    return evidence
