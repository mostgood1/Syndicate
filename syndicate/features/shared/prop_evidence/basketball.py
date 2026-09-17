"""WNBA and NBA player-prop evidence.

SOURCES (all allowlisted, all measured on production web 2026-09-17 for WNBA):

    cards_sim_detail_<date>.json   games[].sim.players.{home,away}[]:
                                   min_mean, {pts,reb,ast,threes,stl,blk,tov,pra}_{mean,sd,q},
                                   prop_distributions[stat].distribution (100 draws),
                                   scenarios {close,medium,blowout}, team, opponent;
                                   games[].sim.injuries / market_anchor
    smart_sim_<date>_<HOME>_<AWAY>.json
                                   score {home_mean, away_mean, total_q, margin_q, p_home_win,
                                   p_home_cover, p_total_over...}, context {home_pace, away_pace,
                                   home_b2b, away_b2b, home_injuries_out, ...}, market
    props_recommendations_<date>.csv
                                   `model` column: per-stat means incl. pr/pa/ra combos
    boxscores_history.csv          per-player per-game box (MIN, PTS, REB, AST, FG3M, STL, BLK, TOV)
    team_advanced_stats_<season>.csv
                                   pace, off_rtg, def_rtg, efg_pct, tov_pct ...

**`min_mean`, NOT `minutes`.** Ask's old WNBA reader asked for `minutes`, a key
only the fallback stub writes (`basketball_props_smart_sim.py`), so the minutes
row never rendered on real sim output and the team table printed 0 minutes for
every player. Production writes `min_mean` (Paige Bueckers `min_mean 38.37`,
`state_basketball.md`). This reader uses the key the engine writes.

**P(over) is read off the published draws**, not a normal fitted to mean/sd. A
100-draw histogram is coarse -- the table says "100 sims" beside it so nobody
reads a 1-point difference as signal.

NBA reads the same families from `nba_source`. NBA has no slate until October;
its fixtures are the 2026-05-26 production files.
"""

from __future__ import annotations

import ast
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from syndicate.features.shared.prop_evidence import common as C
from syndicate.features.shared.prop_evidence.contract import (
    ABSENT_NO_ARTIFACT,
    ABSENT_NO_MATCH,
    ABSENT_NO_PRODUCER,
    ABSENT_NOT_PUBLISHED,
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

# board market -> (sim stat key, label, box-score columns summed)
MARKETS: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "player_points": ("pts", "Points", ("PTS",)),
    "player_rebounds": ("reb", "Rebounds", ("REB",)),
    "player_assists": ("ast", "Assists", ("AST",)),
    "player_threes": ("threes", "3-pointers made", ("FG3M",)),
    "player_steals": ("stl", "Steals", ("STL",)),
    "player_blocks": ("blk", "Blocks", ("BLK",)),
    "player_turnovers": ("tov", "Turnovers", ("TOV",)),
    "player_points_rebounds_assists": ("pra", "Pts+Reb+Ast", ("PTS", "REB", "AST")),
    "player_points_rebounds": ("pr", "Pts+Reb", ("PTS", "REB")),
    "player_points_assists": ("pa", "Pts+Ast", ("PTS", "AST")),
    "player_rebounds_assists": ("ra", "Reb+Ast", ("REB", "AST")),
}
# Markets whose outcome is a JOINT event over several stats. The sim publishes
# per-stat marginals only, so no honest P(yes) exists for these.
JOINT_MARKETS = {"player_double_double", "player_triple_double"}
# Combo stats the sim publishes a mean for (props_recommendations `model`) but no draws.
COMBO_NO_DRAWS = {"pr", "pa", "ra"}

_BOX_COLUMNS = ("MIN", "PTS", "REB", "AST", "FG3M", "STL", "BLK", "TOV")


def _local_dir(sport: str) -> str:
    return f"{sport}_source"


def candidate_dates(subject: PropSubject) -> list[str]:
    """Board date, then the tip's Eastern date, then its UTC date (`common.slate_dates`)."""
    return C.slate_dates(subject.selected_date, subject.commence_time)


def _find_player(sport: str, subject: PropSubject) -> tuple[dict[str, Any], dict[str, Any], str, str, Path] | None:
    """(player, game, side, iso_date, path) from the first dated cards_sim_detail that holds the player."""
    for iso in candidate_dates(subject):
        path = C.first_existing(_local_dir(sport), f"processed/cards_sim_detail_{iso}.json")
        if path is None:
            continue
        try:
            payload = C.load_json(path)
        except Exception:
            logger.exception("prop_evidence basketball: unreadable %s", path)
            continue
        hits: list[tuple[dict[str, Any], dict[str, Any], str]] = []
        for game in payload.get("games") or [] if isinstance(payload, dict) else []:
            sim = game.get("sim") if isinstance(game, dict) else None
            players = sim.get("players") if isinstance(sim, dict) else None
            if not isinstance(players, dict):
                continue
            for side in ("home", "away"):
                for player in players.get(side) or []:
                    if isinstance(player, dict) and C.names_match(player.get("player_name"), subject.player_name):
                        hits.append((player, game, side))
        if len(hits) > 1:
            # The same name on two rosters in one slate: refuse rather than guess.
            logger.warning("prop_evidence basketball: %d sim rows named %r on %s", len(hits), subject.player_name, iso)
            return None
        if hits:
            player, game, side = hits[0]
            return player, game, side, iso, path
    return None


def _smart_sim(sport: str, game: dict[str, Any], iso: str) -> tuple[dict[str, Any], Path] | None:
    home = str(game.get("home_tri") or "").upper()
    away = str(game.get("away_tri") or "").upper()
    if not home or not away:
        return None
    path = C.first_existing(_local_dir(sport), f"processed/smart_sim_{iso}_{home}_{away}.json")
    if path is None:
        return None
    try:
        payload = C.load_json(path)
    except Exception:
        logger.exception("prop_evidence basketball: unreadable %s", path)
        return None
    return (payload, path) if isinstance(payload, dict) else None


def _model_means(sport: str, iso: str, player_name: str) -> dict[str, float]:
    """Per-stat means from `props_recommendations_<date>.csv` -- the only home of pr/pa/ra."""
    path = C.first_existing(_local_dir(sport), f"processed/props_recommendations_{iso}.csv")
    if path is None:
        return {}
    try:
        for row in C.iter_csv(path):
            if not C.names_match(row.get("player"), player_name):
                continue
            raw = row.get("model") or ""
            try:
                model = ast.literal_eval(raw) if raw.strip().startswith("{") else {}
            except (ValueError, SyntaxError):
                model = {}
            return {str(k): float(v) for k, v in model.items() if C.to_float(v) is not None}
    except Exception:
        logger.exception("prop_evidence basketball: unreadable %s", path)
    return {}


MAX_DATED_BOX_FILES = 90
DATED_BOX_LOOKBACK_DAYS = 150
STALE_FORM_DAYS = 7


def _box_sources(sport: str, as_of: str) -> list[Path]:
    """`boxscores_history.csv` plus the dated daily `boxscores_<date>.csv` files.

    **THE HISTORY FILE ALONE IS MONTHS STALE.** Measured on production
    2026-09-17: WNBA's `boxscores_history.csv` ends 2026-06-30 (its bootstrap
    stall is `#469`), while dated `boxscores_2026-08-25.csv` files exist through
    08-25. Same columns. Reading both is the difference between June and August
    form on a September playoff prop; the staleness that remains is stated on
    the table, not hidden.
    """
    paths: list[Path] = []
    history = C.first_existing(_local_dir(sport), "processed/boxscores_history.csv")
    if history is not None:
        paths.append(history)
    try:
        floor = (datetime.fromisoformat(as_of) - timedelta(days=DATED_BOX_LOOKBACK_DAYS)).date().isoformat()
    except ValueError:
        floor = ""
    dated: dict[str, Path] = {}
    for root in C.sport_roots(_local_dir(sport)):
        for raw in (root / "processed").glob("boxscores_????-??-??.csv"):
            iso = raw.name[len("boxscores_"):-len(".csv")]
            if floor and iso < floor or (as_of and iso > as_of):
                continue
            dated.setdefault(iso, raw)
    for iso in sorted(dated)[-MAX_DATED_BOX_FILES:]:
        paths.append(dated[iso])
    return paths


def _box_games(sport: str, player_name: str, as_of: str) -> tuple[list[dict[str, Any]], Path | None]:
    """The player's PLAYED box rows (newest first, one per game), each with its opponent tricode."""
    sources = _box_sources(sport, as_of)
    if not sources:
        return [], None
    by_game_teams: dict[str, set[str]] = {}
    mine: dict[str, dict[str, Any]] = {}
    for path in sources:
        try:
            for row in C.iter_csv(path):
                game_id = str(row.get("game_id") or row.get("gameId") or "").strip()
                team = str(row.get("TEAM_ABBREVIATION") or row.get("teamTricode") or "").strip().upper()
                if game_id and team:
                    by_game_teams.setdefault(game_id, set()).add(team)
                name = str(row.get("PLAYER_NAME") or "").strip() or " ".join(
                    p for p in (str(row.get("firstName") or "").strip(), str(row.get("familyName") or "").strip()) if p)
                if not C.names_match(name, player_name):
                    continue
                date = str(row.get("date") or "")[:10]
                key = game_id or date
                entry: dict[str, Any] = {"date": date, "game_id": game_id, "team": team}
                for col in _BOX_COLUMNS:
                    entry[col] = C.to_float(row.get(col))
                mine.setdefault(key, entry)
        except Exception:
            logger.exception("prop_evidence basketball: unreadable %s", path)
    played: list[dict[str, Any]] = []
    for entry in mine.values():
        # A 0-minute line is a DNP: books void the bet, so it is not a miss.
        if not entry.get("MIN"):
            continue
        others = by_game_teams.get(entry["game_id"], set()) - {entry["team"]}
        entry["opponent"] = next(iter(others), "")
        played.append(entry)
    played.sort(key=lambda g: g["date"], reverse=True)
    return played, sources[0]


def _days_between(earlier: str, later: str) -> int | None:
    try:
        return (datetime.fromisoformat(later[:10]) - datetime.fromisoformat(earlier[:10])).days
    except ValueError:
        return None


def _stat_value(game: dict[str, Any], columns: tuple[str, ...]) -> float | None:
    values = [game.get(col) for col in columns]
    if any(v is None for v in values):
        return None
    return float(sum(values))  # type: ignore[arg-type]


def _team_advanced(sport: str, iso: str) -> dict[str, dict[str, float]]:
    season = iso[:4]
    path = C.first_existing(_local_dir(sport), f"processed/team_advanced_stats_{season}.csv")
    if path is None:
        found = C.latest_dated(_local_dir(sport), "processed/team_advanced_stats_*_asof_*.csv", r"asof_(\d{8})")
        path = found[0] if found else None
    if path is None:
        return {}
    out: dict[str, dict[str, float]] = {}
    try:
        for row in C.iter_csv(path):
            team = str(row.get("team") or "").strip().upper()
            if team:
                out[team] = {k: v for k, v in ((k, C.to_float(v)) for k, v in row.items() if k != "team") if v is not None}
    except Exception:
        logger.exception("prop_evidence basketball: unreadable %s", path)
    return out


# ---------------------------------------------------------------------------
# Layers
# ---------------------------------------------------------------------------


def _player_sim(subject: PropSubject, found, stat: str | None, label: str, model_means: dict[str, float]) -> LayerEvidence:
    if subject.market_key in JOINT_MARKETS:
        return absent(Layer.PLAYER_SIM, f"{ABSENT_NO_PRODUCER}:sim publishes per-stat marginals, not the joint distribution a {subject.market} needs")
    if stat is None:
        return absent(Layer.PLAYER_SIM, f"{ABSENT_NOT_APPLICABLE}:market {subject.market} has no sim stat mapping")
    if found is None:
        return absent(Layer.PLAYER_SIM, f"{ABSENT_NO_MATCH}:{subject.player_name} not in cards_sim_detail for {', '.join(candidate_dates(subject))}")
    player, game, side, iso, path = found
    rows: list[list[Any]] = []
    charts: list[dict[str, Any]] = []
    facts: dict[str, Any] = {"stat": stat, "date": iso}

    if stat in COMBO_NO_DRAWS:
        mean = model_means.get(stat)
        if mean is None:
            return absent(Layer.PLAYER_SIM, f"{ABSENT_NO_MATCH}:no {stat} mean in props_recommendations_{iso}")
        rows.append(["Sim mean", C.fmt_num(mean, 2)])
        rows.append([f"P(over {C.fmt_line(subject.line)})", "not published (combo has no draws)"])
        facts.update({"mean": mean, "prob_over": None})
    else:
        mean = C.to_float(player.get(f"{stat}_mean"))
        sd = C.to_float(player.get(f"{stat}_sd"))
        q = player.get(f"{stat}_q") if isinstance(player.get(f"{stat}_q"), dict) else {}
        dist_block = (player.get("prop_distributions") or {}).get(stat) or (player.get("prop_ladders") or {}).get(stat) or {}
        dist = dist_block.get("distribution") if isinstance(dist_block, dict) else None
        sims = C.to_float(dist_block.get("simCount")) if isinstance(dist_block, dict) else None
        p_over = C.dist_prob_over(dist, subject.line)
        if mean is None and not dist:
            return absent(Layer.PLAYER_SIM, f"{ABSENT_NO_MATCH}:no {stat} projection for {subject.player_name}")
        rows.append(["Sim mean ± sd", f"{C.fmt_num(mean, 2)} ± {C.fmt_num(sd, 2)}"])
        if q:
            rows.append(["p10 / p50 / p90", f"{C.fmt_num(q.get('p10'))} / {C.fmt_num(q.get('p50'))} / {C.fmt_num(q.get('p90'))}"])
        if subject.line is not None:
            rows.append([f"Sim P(over {C.fmt_line(subject.line)})", f"{C.fmt_pct(p_over)} of {int(sims or 0)} sims" if p_over is not None else "—"])
            if p_over is not None:
                p_under = max(0.0, 1.0 - p_over - _dist_prob_equal(dist, subject.line))
                rows.append([f"Sim P(under {C.fmt_line(subject.line)})", C.fmt_pct(p_under)])
        facts.update({"mean": mean, "sd": sd, "quantiles": q, "prob_over": p_over, "sims": sims})
        chart_obj = C.dist_chart(dist, title=f"Simulated {label.lower()} — {subject.player_name} ({iso})",
                                 x_label=label, layer=Layer.PLAYER_SIM, line=subject.line)
        if chart_obj:
            charts.append(chart_obj)

    board_prob = C.to_float(subject.projection.get("model_prob_over"))
    market_prob = C.to_float(subject.projection.get("market_fair_prob_over"))
    if board_prob is not None or market_prob is not None:
        rows.append(["Board model P(over) vs market fair", f"{C.fmt_pct(board_prob)} vs {C.fmt_pct(market_prob)}"])
    min_mean = C.to_float(player.get("min_mean"))
    if min_mean is not None:
        rows.append(["Sim minutes", C.fmt_num(min_mean, 1)])
        facts["min_mean"] = min_mean
    title = f"Player sim — {subject.player_name} {label} {C.fmt_line(subject.line)} ({player.get('team') or ''} vs {player.get('opponent') or ''}, {iso})"
    return LayerEvidence(Layer.PLAYER_SIM, tables=[table(title, ["Measure", "Value"], rows, Layer.PLAYER_SIM)],
                         charts=charts, facts=facts, source=f"{subject.sport}:cards_sim_detail", as_of=C.mtime_iso(path) or iso)


def _dist_prob_equal(dist: dict[str, Any] | None, line: float | None) -> float:
    if line is None or not dist:
        return 0.0
    points = C.count_points(dist)
    total = sum(c for _, c in points)
    if total <= 0:
        return 0.0
    return sum(c for x, c in points if x == line) / total


def _recent_form(subject: PropSubject, games: list[dict[str, Any]], box_path: Path | None, columns: tuple[str, ...] | None, label: str) -> LayerEvidence:
    if box_path is None:
        reason = ABSENT_NOT_PUBLISHED if subject.sport == "nba" else ABSENT_NO_ARTIFACT
        return absent(Layer.RECENT_FORM, f"{reason}:{subject.sport}_source boxscores_history.csv not on this disk")
    if not games:
        return absent(Layer.RECENT_FORM, f"{ABSENT_NO_MATCH}:{subject.player_name} not in boxscores_history.csv")
    last = games[:C.LAST_N_GAMES]
    rows: list[list[Any]] = []
    for game in last:
        stat = _stat_value(game, columns) if columns else None
        rows.append([game["date"], game.get("opponent") or "", C.fmt_num(game.get("MIN"), 0),
                     C.fmt_num(stat, 0) if stat is not None else "—"])
    values = [_stat_value(g, columns) for g in last] if columns else []
    rate = C.hit_rate(values, subject.line, subject.side) if columns else None
    avg = [v for v in values if v is not None]
    rows.append([f"L{len(last)} avg", "", C.fmt_num(sum((g.get('MIN') or 0) for g in last) / len(last), 1),
                 C.fmt_num(sum(avg) / len(avg), 1) if avg else "—"])
    if rate:
        rows.append([f"Hit rate vs {C.fmt_line(subject.line)}", "", "", C.hit_rate_text(rate)])
    stale_days = _days_between(last[0]["date"], subject.selected_date)
    if stale_days is not None and stale_days > STALE_FORM_DAYS:
        rows.append([f"STALE: newest box score is {stale_days} days before this game", "", "", ""])
    charts: list[dict[str, Any]] = []
    if columns:
        series = [{"date": g["date"], "value": _stat_value(g, columns)} for g in last]
        chart_obj = C.form_chart(series, stat_key="value", stat_label=label, player=subject.player_name, line=subject.line)
        if chart_obj:
            charts.append(chart_obj)
    return LayerEvidence(
        Layer.RECENT_FORM,
        tables=[table(f"Last {len(last)} games — {subject.player_name} (through {last[0]['date']})",
                      ["Date", "Opp", "MIN", label], rows, Layer.RECENT_FORM)],
        charts=charts,
        facts={"games": len(last), "hit_rate": rate, "values": values, "newest_game": last[0]["date"], "stale_days": stale_days},
        source=f"{subject.sport}:boxscores_history",
        as_of=last[0]["date"],
    )


def _matchup(subject: PropSubject, found, games: list[dict[str, Any]], columns: tuple[str, ...] | None, label: str,
             advanced: dict[str, dict[str, float]]) -> LayerEvidence:
    if found is None:
        return absent(Layer.MATCHUP, f"{ABSENT_NO_MATCH}:opponent unknown without the player's sim row")
    player = found[0]
    opponent = str(player.get("opponent") or "").upper()
    rows: list[list[Any]] = []
    facts: dict[str, Any] = {"opponent": opponent}
    tables: list[dict[str, Any]] = []
    vs = [g for g in games if str(g.get("opponent") or "").upper() == opponent] if opponent else []
    if vs and columns:
        season = subject.selected_date[:4]
        vs = [g for g in vs if g["date"][:4] == season] or vs
        for game in vs[:6]:
            rows.append([game["date"], C.fmt_num(game.get("MIN"), 0), C.fmt_num(_stat_value(game, columns), 0)])
        rate = C.hit_rate([_stat_value(g, columns) for g in vs], subject.line, subject.side)
        if rate:
            rows.append([f"Hit rate vs {C.fmt_line(subject.line)}", "", C.hit_rate_text(rate)])
        facts["vs_opponent"] = {"games": len(vs), "hit_rate": rate}
        tables.append(table(f"{subject.player_name} vs {opponent} ({len(vs)} meeting{'s' if len(vs) != 1 else ''})",
                            ["Date", "MIN", label], rows, Layer.MATCHUP))
    team = str(player.get("team") or "").upper()
    opp_stats = advanced.get(opponent) or {}
    team_stats = advanced.get(team) or {}
    if opp_stats:
        def rank(field: str, reverse: bool) -> str:
            ordered = sorted((v.get(field) for v in advanced.values() if v.get(field) is not None), reverse=reverse)
            value = opp_stats.get(field)
            return f"{ordered.index(value) + 1} of {len(ordered)}" if value in ordered else "—"
        def_rows = [
            ["Defensive rating (pts allowed /100)", C.fmt_num(opp_stats.get("def_rtg")), rank("def_rtg", False) + " (1 = stingiest)"],
            ["Pace", C.fmt_num(opp_stats.get("pace")), rank("pace", True) + " (1 = fastest)"],
        ]
        if team_stats:
            def_rows.append([f"{team} pace (own)", C.fmt_num(team_stats.get("pace")), ""])
        tables.append(table(f"Opposing defence — {opponent} (team advanced stats)", ["Measure", "Value", "League rank"], def_rows, Layer.MATCHUP))
        facts["opponent_advanced"] = opp_stats
    if not tables:
        return absent(Layer.MATCHUP, f"{ABSENT_NO_MATCH}:no meetings with {opponent or 'opponent'} and no team advanced stats row")
    return LayerEvidence(Layer.MATCHUP, tables=tables, facts=facts, source=f"{subject.sport}:boxscores_history+team_advanced_stats")


def _advanced(subject: PropSubject, found, stat: str | None, games: list[dict[str, Any]], label: str) -> LayerEvidence:
    if found is None:
        return absent(Layer.ADVANCED, f"{ABSENT_NO_MATCH}:{subject.player_name} not in cards_sim_detail")
    player, game, side, iso, path = found
    teammates = ((game.get("sim") or {}).get("players") or {}).get(side) or []
    rows: list[list[Any]] = []
    facts: dict[str, Any] = {}
    min_mean = C.to_float(player.get("min_mean"))
    recent_minutes = [g.get("MIN") for g in games[:C.LAST_N_GAMES] if g.get("MIN") is not None]
    rows.append(["Sim minutes", C.fmt_num(min_mean, 1)])
    if recent_minutes:
        rows.append([f"Actual minutes, last {len(recent_minutes)}", C.fmt_num(sum(recent_minutes) / len(recent_minutes), 1)])
    base_stat = stat if stat in {"pts", "reb", "ast", "threes", "stl", "blk", "tov", "pra"} else None
    if base_stat:
        mean = C.to_float(player.get(f"{base_stat}_mean"))
        team_total = sum(C.to_float(p.get(f"{base_stat}_mean")) or 0.0 for p in teammates if isinstance(p, dict))
        if mean is not None and team_total > 0:
            share = mean / team_total
            rows.append([f"Share of team sim {label.lower()}", C.fmt_pct(share)])
            facts["team_share"] = share
        if mean is not None and min_mean:
            per36 = mean / min_mean * 36.0
            rows.append([f"{label} per 36 min (sim)", C.fmt_num(per36, 1)])
            facts["per36"] = per36
    scenarios = player.get("scenarios") if isinstance(player.get("scenarios"), dict) else {}
    q_key = f"{base_stat}_q" if base_stat else None
    for name in ("close", "medium", "blowout"):
        block = scenarios.get(name) if isinstance(scenarios.get(name), dict) else None
        if block and q_key and isinstance(block.get(q_key), dict):
            q = block[q_key]
            rows.append([f"{label} if game is {name} (n={block.get('n')})",
                         f"p50 {C.fmt_num(q.get('p50'))} (p10 {C.fmt_num(q.get('p10'))} – p90 {C.fmt_num(q.get('p90'))})"])
    facts.update({"min_mean": min_mean, "recent_minutes": recent_minutes})
    return LayerEvidence(Layer.ADVANCED, tables=[table(f"Role and usage — {subject.player_name} ({iso})", ["Measure", "Value"], rows, Layer.ADVANCED)],
                         facts=facts, source=f"{subject.sport}:cards_sim_detail+boxscores_history", as_of=C.mtime_iso(path) or iso)


def _game_sim(subject: PropSubject, found, smart) -> LayerEvidence:
    if found is None:
        return absent(Layer.GAME_SIM, f"{ABSENT_NO_MATCH}:game unknown without the player's sim row")
    if smart is None:
        _, game, _, iso, _ = found
        return absent(Layer.GAME_SIM, f"{ABSENT_NO_ARTIFACT}:smart_sim_{iso}_{game.get('home_tri')}_{game.get('away_tri')}.json")
    payload, path = smart
    score = payload.get("score") if isinstance(payload.get("score"), dict) else {}
    market = payload.get("market") if isinstance(payload.get("market"), dict) else {}
    home, away = str(payload.get("home") or ""), str(payload.get("away") or "")
    if not score:
        return absent(Layer.GAME_SIM, f"{ABSENT_NO_MATCH}:smart_sim has no score block")
    tq = score.get("total_q") or {}
    mq = score.get("margin_q") or {}
    rows = [
        ["Win probability", C.fmt_pct(score.get("p_away_win")), C.fmt_pct(score.get("p_home_win"))],
        ["Mean points", C.fmt_num(score.get("away_mean")), C.fmt_num(score.get("home_mean"))],
        ["Total (mean; p10–p90)", f"{C.fmt_num(score.get('total_mean'))} ({C.fmt_num(tq.get('p10'))}–{C.fmt_num(tq.get('p90'))})", ""],
        [f"{home} margin (mean; p10–p90)", f"{C.fmt_num(score.get('margin_mean'))} ({C.fmt_num(mq.get('p10'))}–{C.fmt_num(mq.get('p90'))})", ""],
        ["Market total / home spread", C.fmt_num(market.get("market_total")), C.fmt_num(market.get("market_home_spread"))],
        ["Sim P(home covers) / P(total over)", C.fmt_pct(score.get("p_home_cover")), C.fmt_pct(score.get("p_total_over"))],
    ]
    charts: list[dict[str, Any]] = []
    team_points = [
        {"x": f"{away} p10", "y": C.to_float((score.get("away_q") or {}).get("p10")) or 0.0},
        {"x": f"{away} p50", "y": C.to_float((score.get("away_q") or {}).get("p50")) or 0.0},
        {"x": f"{away} p90", "y": C.to_float((score.get("away_q") or {}).get("p90")) or 0.0},
        {"x": f"{home} p10", "y": C.to_float((score.get("home_q") or {}).get("p10")) or 0.0},
        {"x": f"{home} p50", "y": C.to_float((score.get("home_q") or {}).get("p50")) or 0.0},
        {"x": f"{home} p90", "y": C.to_float((score.get("home_q") or {}).get("p90")) or 0.0},
    ]
    if any(p["y"] for p in team_points):
        charts.append(chart(f"Simulated team points — {away} @ {home}", "Team / percentile", "Points", team_points, Layer.GAME_SIM))
    return LayerEvidence(Layer.GAME_SIM,
                         tables=[table(f"Game sim — {away} @ {home} ({payload.get('date') or ''}, {payload.get('n_sims') or ''} sims)",
                                       ["Metric", away, home], rows, Layer.GAME_SIM)],
                         charts=charts,
                         facts={k: score.get(k) for k in ("home_mean", "away_mean", "total_mean", "margin_mean", "p_home_win", "p_home_cover", "p_total_over")},
                         source=f"{subject.sport}:smart_sim", as_of=C.mtime_iso(path))


def _environment(subject: PropSubject, found, smart) -> LayerEvidence:
    if found is None:
        return absent(Layer.ENVIRONMENT, f"{ABSENT_NO_MATCH}:game unknown without the player's sim row")
    player, game, side, iso, _ = found
    sim = game.get("sim") if isinstance(game.get("sim"), dict) else {}
    rows: list[list[Any]] = [["Venue", "Home" if side == "home" else "Away"]]
    facts: dict[str, Any] = {"side": side}
    if smart is not None:
        context = smart[0].get("context") if isinstance(smart[0].get("context"), dict) else {}
        own, opp = (side, "away" if side == "home" else "home")
        for label, key in (("Pace (own / opp)", "pace"), ("Back-to-back (own / opp)", "b2b"), ("Injuries out (own / opp)", "injuries_out")):
            a, b = context.get(f"{own}_{key}"), context.get(f"{opp}_{key}")
            if a is None and b is None:
                continue
            fmt = (lambda v: C.fmt_num(v, 1)) if key == "pace" else (lambda v: "yes" if v is True else "no" if v is False else str(v))
            rows.append([label, f"{fmt(a)} / {fmt(b)}"])
            facts[key] = {"own": a, "opp": b}
        if context.get("roster_mode"):
            rows.append(["Roster mode (as of)", f"{context.get('roster_mode')} ({context.get('asof_date') or ''})"])
    injuries = sim.get("injuries") if isinstance(sim.get("injuries"), dict) else {}
    for label, key in (("Injured (own team)", side), ("Injured (opponent)", "away" if side == "home" else "home")):
        names = [str(i.get("player_name") if isinstance(i, dict) else i) for i in (injuries.get(key) or [])]
        if names:
            rows.append([label, ", ".join(names[:6]) + (f" +{len(names) - 6}" if len(names) > 6 else "")])
    anchor = sim.get("market_anchor") if isinstance(sim.get("market_anchor"), dict) else {}
    if anchor.get("state") == "on":
        rows.append(["Sim anchored to market", f"total weight {anchor.get('total_w')}, margin weight {anchor.get('margin_w')} (raw total {C.fmt_num(anchor.get('model_total_raw'))} → {C.fmt_num(anchor.get('anchored_total'))})"])
        facts["market_anchor"] = {k: anchor.get(k) for k in ("total_w", "margin_w", "model_total_raw", "anchored_total")}
    return LayerEvidence(Layer.ENVIRONMENT, tables=[table(f"Game environment — {subject.player_name} ({iso})", ["Factor", "Value"], rows, Layer.ENVIRONMENT)],
                         facts=facts, source=f"{subject.sport}:smart_sim.context+cards_sim_detail")


def build(subject: PropSubject) -> PropEvidence:
    sport = subject.sport
    evidence = PropEvidence(subject=subject, provider=f"basketball:{sport}")
    stat, label, columns = MARKETS.get(subject.market_key, (None, subject.market, None))
    found = _find_player(sport, subject)
    iso = found[3] if found else (candidate_dates(subject) or [subject.selected_date])[0]
    model_means = _model_means(sport, iso, subject.player_name) if stat in COMBO_NO_DRAWS else {}
    games, box_path = _box_games(sport, subject.player_name, iso)
    smart = _smart_sim(sport, found[1], found[3]) if found else None
    advanced_stats = _team_advanced(sport, iso)

    evidence.set(_player_sim(subject, found, stat, label, model_means))
    if subject.market_key in JOINT_MARKETS:
        evidence.set(absent(Layer.RECENT_FORM, f"{ABSENT_NOT_APPLICABLE}:{subject.market} is a joint event; per-stat logs shown elsewhere"))
    else:
        evidence.set(_recent_form(subject, games, box_path, columns, label))
    evidence.set(_matchup(subject, found, games, columns, label, advanced_stats))
    evidence.set(_advanced(subject, found, stat, games, label))
    evidence.set(_game_sim(subject, found, smart))
    evidence.set(_environment(subject, found, smart))
    evidence.set(build_track_record(subject))
    return evidence
