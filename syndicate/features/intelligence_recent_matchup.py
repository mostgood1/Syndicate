"""Recency + matchup sentences for board rows -- what the explanation LEADS with.

User 2026-10-08: "we need to get the advanced data metrics to primarily focus
on recency and matchups (hitter vs pitcher, hitter vs team, etc)". The evidence
already exists: `prop_evidence` (Ask's providers) computes each player's recent
form against the row's own line and his record against this opponent, plus the
opponent's profile. This module turns those FACTS into two short sentences:

    Recent form: over 12.5 in 4 of the last 10 (avg 10.6).
    Matchup: over in 4 of 4 vs ATL this season; ATL defensive rating 95.5.

Season-long metrics (`intelligence_season_evidence`) follow as context.

Costs are bounded the way `prop_evidence.common.build_read_cache` documents:
inside a board build every file is parsed once, and a row's sentence is memoised
per (sport, player, market, line, side, opponent) -- books quoting the same bet
share it. Never raises: a provider failure yields no sentence, not a broken card.
"""

from __future__ import annotations

from typing import Any, Mapping

_MAX_VALUES = 10


def _num(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return None if out != out else out


def _fmt(value: float | None, digits: int = 1) -> str:
    if value is None:
        return "-"
    return f"{value:.{digits}f}" if abs(value - round(value)) > 1e-9 else f"{value:.0f}"


def _rate_phrase(rate: Mapping[str, Any] | None, *, last: bool = False) -> str | None:
    """'over 12.5 in 4 of the last 10' (last=True) or 'over 12.5 in 4 of 4' from a hit_rate dict."""
    if not isinstance(rate, Mapping):
        return None
    games = int(_num(rate.get("games")) or 0)
    if games <= 0:
        return None
    hits = int(_num(rate.get("hits")) or 0)
    side = str(rate.get("side") or "").strip().lower()
    line = _num(rate.get("line"))
    of = f"the last {games}" if last else f"{games}"
    if side in {"over", "under"} and line is not None:
        return f"{side} {_fmt(line)} in {hits} of {of}"
    return f"{hits} of {of}"


def recent_form_text(facts: Mapping[str, Any] | None) -> str | None:
    if not isinstance(facts, Mapping) or not facts:
        return None
    phrase = _rate_phrase(facts.get("hit_rate"), last=True)
    values = [v for v in (_num(x) for x in (facts.get("values") or [])[:_MAX_VALUES]) if v is not None]
    avg = f" (avg {_fmt(sum(values) / len(values))})" if values else ""
    if phrase:
        text = f"Recent form: {phrase}{avg}"
    elif values:
        text = f"Recent form: avg {_fmt(sum(values) / len(values))} over the last {len(values)}"
    else:
        return None
    stale = _num(facts.get("stale_days"))
    if stale is not None and stale > 14:
        text += f" (newest game {int(stale)} days ago)"
    return text + "."


def _opponent_detail(facts: Mapping[str, Any]) -> str | None:
    opponent = str(facts.get("opponent") or "").strip()
    if not opponent:
        return None
    # basketball: opponent_advanced {def_rtg, pace, ...} (+ optional *_rank)
    adv = facts.get("opponent_advanced")
    if isinstance(adv, Mapping) and _num(adv.get("def_rtg")) is not None:
        rank = adv.get("def_rtg_rank")
        rank_text = f" ({rank})" if rank else ""
        pace = _num(adv.get("pace"))
        pace_text = f", pace {_fmt(pace)}" if pace is not None else ""
        return f"{opponent} defensive rating {_fmt(_num(adv.get('def_rtg')))}{rank_text}{pace_text}"
    # hockey: opponent_profile {xg {xga60, xgf60}, ...}
    prof = facts.get("opponent_profile")
    if isinstance(prof, Mapping):
        xg = prof.get("xg") if isinstance(prof.get("xg"), Mapping) else {}
        xga = _num(xg.get("xga60"))
        now = facts.get("opponent_this_season") if isinstance(facts.get("opponent_this_season"), Mapping) else {}
        now_xga, now_games = _num(now.get("xga_pg")), _num(now.get("games"))
        this_season = ""
        if now_xga is not None and now_games:
            rank = now.get("xga_pg_rank")
            rank_text = f", {int(_num(rank))} of 32 (1 = stingiest)" if _num(rank) is not None else ""
            this_season = f"; this season {_fmt(now_xga, 2)} xG a game{rank_text}, {int(now_games)} GP"
        if xga is not None:
            blended = " (blended with this season)" if prof.get("xg_blended") else ""
            return f"{opponent} allows {_fmt(xga, 2)} xG/60{blended}{this_season}"
        if this_season:
            return f"{opponent}{this_season[1:]}"
    # NCAAF: allowed_per_game + allowed_rank
    allowed = _num(facts.get("allowed_per_game"))
    if allowed is not None:
        rank = facts.get("allowed_rank")
        return f"{opponent} allows {_fmt(allowed)} per game" + (f", rank {rank}" if rank else "")
    # NFL: opponent_points_allowed [week, ...]
    pts = [v for v in (_num(x) for x in (facts.get("opponent_points_allowed") or [])) if v is not None]
    if pts:
        return f"{opponent} has allowed {_fmt(sum(pts) / len(pts))} points a game ({len(pts)} games)"
    # soccer: opponent_rating {xg_against_per_match, ...}
    rating = facts.get("opponent_rating")
    if isinstance(rating, Mapping) and _num(rating.get("xg_against_per_match")) is not None:
        return f"{opponent} concedes {_fmt(_num(rating.get('xg_against_per_match')), 2)} xG a match"
    return None


def matchup_text(facts: Mapping[str, Any] | None) -> str | None:
    if not isinstance(facts, Mapping) or not facts:
        return None
    parts: list[str] = []
    vs = facts.get("vs_opponent")
    opponent = str(facts.get("opponent") or "").strip()
    if isinstance(vs, Mapping):
        phrase = _rate_phrase(vs.get("hit_rate"))
        if phrase and opponent:
            parts.append(f"{phrase} vs {opponent}")
    detail = _opponent_detail(facts)
    if detail:
        parts.append(detail)
    return ("Matchup: " + "; ".join(parts) + ".") if parts else None


# --------------------------------------------------------------------------- MLB
#
# MLB is not a prop_evidence provider (Ask serves it from its reference fetchers),
# so its board sentences are read here, lean, from the same artifacts:
#   * recent form -- `processed/mlb_batter_game_log.csv` / `mlb_pitcher_game_log.csv`
#     (built from feed_live; on 2026-10-08 they cover 17 dates since 06-14, so the
#     sentence says "logged games", never implies a full season);
#   * batter vs pitcher -- `statcast/bvp/bvp_pairs_<pitcher_id % 64>.json`
#     (career, schema mlb_bvp_pairs_v1, fields pa/hits/hr/so/bb/hbp/...), the
#     opposing starter from `daily/snapshots/<date>/probables.json`.
#   * phase 2 -- `scripts/build_mlb_matchup_splits.py` (raw Statcast pitches,
#     regular season) writes `derived/mlb_batter_game_log_statcast_<season>.csv`
#     (every batter-game of the season, so "last 10" reaches past feed_live's
#     window) and `derived/mlb_matchup_splits_<season>_asof_<date>.json` (batter
#     vs LHP/RHP and vs each team; pitcher vs LHB/RHB + throwing hand).
# All reads go through `prop_evidence.common`, so a board build's read cache
# parses each file once.

_MLB_BATTER_STAT = {
    "batter_hits": ("h",), "batter_total_bases": ("tb",), "batter_home_runs": ("hr",), "batter_rbis": ("rbi",),
    "batter_runs_scored": ("r",), "batter_strikeouts": ("so",), "batter_walks": ("bb",),
    "batter_hits_runs_rbis": ("h", "r", "rbi"),
}
_MLB_PITCHER_STAT = {
    "pitcher_strikeouts": ("k",), "pitcher_outs": ("outs",), "pitcher_hits_allowed": ("h",),
    "pitcher_earned_runs": ("er",), "pitcher_walks": ("bb",),
}
_MLB_LAST_N = 10


def _mlb_root():
    import os
    from pathlib import Path

    override = str(os.environ.get("SYNDICATE_MLB_DATA_ROOT") or "").strip()
    if override:
        return Path(override)
    from syndicate.features.shared.prop_evidence.common import data_root

    return data_root() / "mlb_source" / "source_artifacts" / "data"


# market columns the Statcast batter-game log carries (no runs / RBIs there)
_STATCAST_LOG_COLS = {"h", "tb", "hr", "so", "bb"}


def _mlb_derived(pattern: str) -> Any:
    """Newest `derived/<pattern>` file, parsed (CSV -> player_id -> rows, JSON -> dict); None if absent."""
    from syndicate.features.shared.prop_evidence import common as C

    directory = _mlb_root() / "derived"
    cache = C._READ_CACHE.get()
    key = ("mlb_derived", pattern, str(directory)) if cache is not None else None
    if key is not None and key in cache:
        return cache[key]
    files = sorted(directory.glob(pattern)) if directory.is_dir() else []
    out: Any = None
    if files:
        path = files[-1]
        if path.suffix == ".csv":
            out = {}
            for row in C.iter_csv(path):
                out.setdefault(str(row.get("player_id") or ""), []).append(row)
        else:
            payload = C.load_json(path)
            out = payload if isinstance(payload, Mapping) else None
    if key is not None:
        cache[key] = out
    return out


def _mlb_multi_log(group: str) -> dict[str, list[dict[str, str]]]:
    """player_id -> rows across EVERY `derived/mlb_player_game_log_<season>_<group>.csv` (StatsAPI).

    User 2026-10-08: "we need robust history ... years of data, not just days". Built by
    `scripts/build_mlb_player_game_logs.py` (2023 onward, every prop stat incl. runs / RBIs,
    regular season + postseason). Indexed once per board build.
    """
    from syndicate.features.shared.prop_evidence import common as C

    directory = _mlb_root() / "derived"
    files = sorted(directory.glob(f"mlb_player_game_log_*_{group}.csv")) if directory.is_dir() else []
    cache = C._READ_CACHE.get()
    key = ("mlb_multi_log", group, tuple(C._cache_key(f) for f in files)) if cache is not None else None
    if key is not None and key in cache:
        return cache[key]
    out: dict[str, list[dict[str, str]]] = {}
    for path in files:
        for row in C.iter_csv(path):
            out.setdefault(str(row.get("player_id") or ""), []).append(row)
    if key is not None:
        cache[key] = out
    return out


def _mlb_hand_multi() -> tuple[dict[tuple[str, str, str], dict[str, float]], list[int]]:
    """(group, player_id, 'vl'|'vr') -> counts summed over every `mlb_hand_splits_<season>.csv`, and the seasons."""
    from syndicate.features.shared.prop_evidence import common as C

    directory = _mlb_root() / "derived"
    files = sorted(directory.glob("mlb_hand_splits_*.csv")) if directory.is_dir() else []
    cache = C._READ_CACHE.get()
    key = ("mlb_hand_multi", tuple(C._cache_key(f) for f in files)) if cache is not None else None
    if key is not None and key in cache:
        return cache[key]
    sums: dict[tuple[str, str, str], dict[str, float]] = {}
    seasons: set[int] = set()
    for path in files:
        for row in C.iter_csv(path):
            k = (str(row.get("group")), str(row.get("player_id")), str(row.get("code")))
            cell = sums.setdefault(k, {"_seasons": set()})
            for f in ("pa", "ab", "h", "tb", "hr", "so", "bb"):
                cell[f] = cell.get(f, 0.0) + (_num(row.get(f)) or 0.0)
            if str(row.get("season") or "").isdigit() and (_num(row.get("pa")) or 0) > 0:
                seasons.add(int(row["season"]))
                cell["_seasons"].add(int(row["season"]))
    result = (sums, sorted(seasons))
    if key is not None:
        cache[key] = result
    return result


def _season_span(seasons: list[int]) -> str:
    if not seasons:
        return ""
    return f"{seasons[0]}-{str(seasons[-1])[2:]}" if len(seasons) > 1 else str(seasons[0])


def _slash(cell: Mapping[str, Any] | None) -> str | None:
    """'.271 AVG, 4 HR in 210 PA' from a splits cell; None below 10 PA."""
    if not isinstance(cell, Mapping):
        return None
    pa, ab = int(cell.get("pa") or 0), int(cell.get("ab") or 0)
    if pa < 10 or ab <= 0:
        return None
    avg = f"{int(cell.get('h') or 0) / ab:.3f}".lstrip("0")
    hr = int(cell.get("hr") or 0)
    return f"{avg} AVG, {hr} HR in {pa} PA"


def _mlb_log(kind: str) -> dict[str, list[dict[str, str]]]:
    """player_id -> rows (file order) from the batter/pitcher game log; {} if absent."""
    from syndicate.features.shared.prop_evidence import common as C

    path = _mlb_root() / "processed" / f"mlb_{kind}_game_log.csv"
    cache = C._READ_CACHE.get()
    key = ("mlb_log", kind, C._cache_key(path)) if cache is not None else None
    if key is not None and key in cache:
        return cache[key]
    out: dict[str, list[dict[str, str]]] = {}
    if path.is_file():
        for row in C.iter_csv(path):
            out.setdefault(str(row.get("player_id") or ""), []).append(row)
    if key is not None:
        cache[key] = out
    return out


def _mlb_probables(selected_date: str) -> list[Mapping[str, Any]]:
    from syndicate.features.shared.prop_evidence import common as C

    path = _mlb_root() / "daily" / "snapshots" / selected_date / "probables.json"
    if not path.is_file():
        return []
    payload = C.load_json(path)
    games = payload.get("games") if isinstance(payload, Mapping) else None
    return [g for g in games or [] if isinstance(g, Mapping)]


def _mlb_bvp(pitcher_id: int, batter_id: int) -> dict[str, int] | None:
    from syndicate.features.shared.prop_evidence import common as C

    path = _mlb_root() / "statcast" / "bvp" / f"bvp_pairs_{int(pitcher_id) % 64:02d}.json"
    if not path.is_file():
        return None
    shard = C.load_json(path)
    fields = [str(f) for f in (shard.get("fields") or [])]
    values = ((shard.get("pitchers") or {}).get(str(int(pitcher_id))) or {}).get(str(int(batter_id)))
    if not values:
        return {}
    try:
        return {f: int(v) for f, v in zip(fields, values)}
    except (TypeError, ValueError):
        return None


def _mlb_side_values(rows: list[Mapping[str, str]], cols: tuple[str, ...]) -> list[float]:
    values = []
    for row in rows:
        total = 0.0
        for col in cols:
            v = _num(row.get(col))
            if v is None:
                break
            total += v
        else:
            values.append(total)
    return values


def mlb_prop_recent_matchup_text(row: Mapping[str, Any], *, selected_date: str) -> str | None:
    """MLB prop: recent form from the game log + batter-vs-starter (career). Never raises."""
    try:
        market = str(row.get("market") or "").strip().lower()
        projection = row.get("projection") if isinstance(row.get("projection"), Mapping) else {}
        player_id = str(projection.get("player_id") or row.get("player_id") or "").strip()
        if not player_id:
            return None
        is_pitcher = market in _MLB_PITCHER_STAT
        cols = _MLB_PITCHER_STAT.get(market) or _MLB_BATTER_STAT.get(market)
        pieces: list[str] = []
        log_rows = _mlb_log("pitcher" if is_pitcher else "batter").get(player_id) or []
        if is_pitcher:
            log_rows = [r for r in log_rows if str(r.get("is_starter") or "") in {"1", "True", "true"}] or log_rows
        season_rows: list[Mapping[str, str]] = []
        if not is_pitcher:
            season_rows = (_mlb_derived("mlb_batter_game_log_statcast_*.csv") or {}).get(player_id) or []
        # the full-season Statcast log when it carries the market's columns
        # (feed_live covers 17 dates); runs / RBIs only live in feed_live. The
        # Statcast log is regular season only, so feed_live games dated after
        # its last game (the postseason) are appended -- "last 10" stays recent.
        source_rows = log_rows
        if season_rows and cols and set(cols) <= _STATCAST_LOG_COLS:
            cutoff = max(str(r.get("date") or "") for r in season_rows)
            source_rows = list(season_rows) + [r for r in log_rows if str(r.get("date") or "") > cutoff]
        # Multi-season StatsAPI logs, when built, are the base (every market, several seasons);
        # the feed_live / Statcast rows only add games they do not hold (by game, then by date).
        multi = (_mlb_multi_log("pitching" if is_pitcher else "hitting").get(player_id) or [])
        if is_pitcher:
            multi = [r for r in multi if str(r.get("is_starter") or "") in {"1", "True", "true"}]
        if multi:
            pks = {str(r.get("game_pk") or "") for r in multi} - {""}
            days = {str(r.get("date") or "") for r in multi}
            source_rows = list(multi) + [r for r in source_rows if str(r.get("game_pk") or "") not in pks
                                         and str(r.get("date") or "") not in days]
        recent = sorted(source_rows, key=lambda r: str(r.get("date") or ""))[-_MLB_LAST_N:]
        if cols and recent:
            values = _mlb_side_values(recent, cols)
            try:  # the chart side-channel must never cost the sentence
                paired = [(str(r.get("date") or ""), v) for r in recent for v in _mlb_side_values([r], cols)]
                _record_values(row, [v for _d, v in reversed(paired)], [d for d, _v in reversed(paired)])
            except Exception:  # noqa: BLE001
                pass
            line = _num(row.get("line"))
            side = str(row.get("side") or "").lower()
            if values and line is not None and side in {"over", "under"}:
                hits = sum(1 for v in values if (v > line if side == "over" else v < line))
                pieces.append(
                    f"Recent form: {side} {_fmt(line)} in {hits} of the last {len(values)} logged games "
                    f"(avg {_fmt(sum(values) / len(values))}; log since {recent[0].get('date')})."
                )
        splits = _mlb_derived("mlb_matchup_splits_*_asof_*.json") or {}
        hand_multi, hand_seasons = _mlb_hand_multi()
        if is_pitcher:
            mine = (splits.get("pitchers") or {}).get(player_id) or {}
            vs_l, vs_r = mine.get("vs_L") or {}, mine.get("vs_R") or {}
            multi_l, multi_r = hand_multi.get(("pitching", player_id, "vl")), hand_multi.get(("pitching", player_id, "vr"))
            if multi_l and multi_r and multi_l.get("pa", 0) >= 10 and multi_r.get("pa", 0) >= 10:
                vs_l, vs_r = multi_l, multi_r
                splits = dict(splits, season=_season_span(sorted(multi_l["_seasons"] | multi_r["_seasons"])))
            if int(vs_l.get("pa") or 0) >= 10 and int(vs_r.get("pa") or 0) >= 10:
                k_l = 100.0 * int(vs_l.get("so") or 0) / int(vs_l["pa"])
                k_r = 100.0 * int(vs_r.get("so") or 0) / int(vs_r["pa"])
                pieces.append(
                    f"Splits ({splits.get('season')} regular season): K rate {k_l:.0f}% vs LHB, {k_r:.0f}% vs RHB; "
                    f"opponents hit {_slash(vs_l)} (LHB), {_slash(vs_r)} (RHB)."
                )
        if not is_pitcher:
            newest = sorted(list(log_rows) + list(season_rows) + list(multi), key=lambda r: str(r.get("date") or ""))[-1:]
            team = str((newest or [{}])[0].get("team") or "")
            pitcher = _mlb_opposing_starter(row, team, selected_date)
            batter_splits = (splits.get("batters") or {}).get(player_id) or {}
            split_bits: list[str] = []
            span = str(splits.get("season") or "")
            if pitcher is not None:
                throws = ((splits.get("pitchers") or {}).get(str(pitcher[0])) or {}).get("throws")
                if throws in {"L", "R"}:
                    multi_hand = hand_multi.get(("hitting", player_id, "vl" if throws == "L" else "vr"))
                    hand = _slash(multi_hand) if multi_hand else None
                    if hand:
                        span = _season_span(sorted(multi_hand["_seasons"]))
                    else:
                        hand = _slash(batter_splits.get(f"vs_{throws}"))
                    if hand:
                        split_bits.append(f"vs {'LHP' if throws == 'L' else 'RHP'} {hand}")
            opponent = _mlb_opponent(row, team)
            vs_multi = [r for r in multi if opponent and _canonical_mlb(str(r.get("opponent") or "")) == opponent]
            if vs_multi:
                cell = {f: sum(_num(r.get(f)) or 0.0 for r in vs_multi) for f in ("pa", "ab", "h", "hr")}
                line_text = _slash(cell)
                years = sorted({str(r.get("date") or "")[:4] for r in vs_multi})
                if line_text:
                    who = next((str(r.get("opponent")) for r in vs_multi), "")
                    abbr = next((a for a in (batter_splits.get("vs_team") or {}) if _canonical_mlb(a) == opponent), who)
                    split_bits.append(f"vs {abbr} {line_text} ({years[0]}-{years[-1][2:]})" if len(years) > 1
                                      else f"vs {abbr} {line_text} ({years[0]})")
            elif opponent:
                for abbr, cell in (batter_splits.get("vs_team") or {}).items():
                    if _canonical_mlb(abbr) == opponent:
                        line = _slash(cell)
                        if line:
                            split_bits.append(f"vs {abbr} {line}")
                        break
            if split_bits:
                label = f"{span} regular season" if span == str(splits.get("season") or "") else span
                pieces.append(f"Splits ({label}): " + "; ".join(split_bits) + ".")
            # HISTORY vs this team across every logged season (StatsAPI logs), on the board's own line
            line, side = _num(row.get("line")), str(row.get("side") or "").lower()
            if opponent and multi and cols and line is not None and side in {"over", "under"}:
                vs_games = [r for r in multi if _canonical_mlb(str(r.get("opponent") or "")) == opponent]
                values = _mlb_side_values(vs_games, cols)
                if values:
                    hits = sum(1 for v in values if (v > line if side == "over" else v < line))
                    first = min(str(r.get("date") or "") for r in vs_games)
                    pieces.append(f"History vs this team: {side} {_fmt(line)} in {hits} of {len(values)} games since {first}.")
            if pitcher is not None:
                pid, name = pitcher
                counts = _mlb_bvp(pid, int(player_id))
                if counts is not None:
                    pa = counts.get("pa", 0)
                    if pa > 0:
                        hits_n = counts.get("hits", 0)
                        pieces.append(
                            f"Matchup: vs {name} (career) {hits_n} hit{'' if hits_n == 1 else 's'} in {pa} PA, "
                            f"{counts.get('hr', 0)} HR, {counts.get('so', 0)} K, {counts.get('bb', 0)} BB."
                        )
                    else:
                        pieces.append(f"Matchup: first career meeting with {name}.")
        return " ".join(pieces) or None
    except Exception as exc:  # noqa: BLE001
        print(f"[recent_matchup] MLB_FAILED error={type(exc).__name__}: {exc}", flush=True)
        return None


def _canonical_mlb(abbr: str) -> str | None:
    from syndicate.features.shared.team_aliases import canonical_team

    return canonical_team("mlb", str(abbr or "")) or None


def _mlb_opponent(row: Mapping[str, Any], team_abbr: str) -> str | None:
    """The canonical team the batter's team plays in this row's game."""
    home, away = _canonical_mlb(str(row.get("home_team") or "")), _canonical_mlb(str(row.get("away_team") or ""))
    mine = _canonical_mlb(team_abbr) if team_abbr else None
    if not home or not away or mine not in {home, away}:
        return None
    return away if mine == home else home


def _mlb_opposing_starter(row: Mapping[str, Any], team_abbr: str, selected_date: str) -> tuple[int, str] | None:
    """(pitcher id, name) of the starter the batter's team faces, from the date's probables."""
    from syndicate.features.shared.team_aliases import canonical_team

    home = canonical_team("mlb", str(row.get("home_team") or ""))
    away = canonical_team("mlb", str(row.get("away_team") or ""))
    mine = canonical_team("mlb", team_abbr) if team_abbr else None
    if not home or not away or mine not in {home, away}:
        return None
    for game in _mlb_probables(selected_date):
        g_home = canonical_team("mlb", str((game.get("home") or {}).get("abbr") or ""))
        g_away = canonical_team("mlb", str((game.get("away") or {}).get("abbr") or ""))
        if (g_home, g_away) != (home, away):
            continue
        side = "home" if mine == away else "away"  # the OTHER team's starter
        pid = game.get(f"{side}_probable_id")
        name = ((game.get(f"{side}_validation") or {}).get("selected_name")) or f"pitcher {pid}"
        try:
            return int(pid), str(name)
        except (TypeError, ValueError):
            return None
    return None


# ------------------------------------------------------------- NFL vs position
#
# Phase 2 (user 2026-10-08): `scripts/build_nfl_defense_vs_position.py` writes
# `nfl_source/tracking/derived/nfl_defense_vs_position_<season>_wk<NN>.json`
# (per defense, per position, per stat: per-game allowed + rank, 1 = fewest).
# The prop's player gets his position from the nflverse roster; the market
# names the stat.

_NFL_MARKET_STAT = (
    ("receiving yards", "rec_yds", "receiving yards"),
    ("receptions", "receptions", "receptions"),
    ("rushing yards", "rush_yds", "rushing yards"),
    ("rush attempts", "carries", "carries"),
    ("carries", "carries", "carries"),
    ("passing yards", "pass_yds", "passing yards"),
    ("pass completions", "completions", "completions"),
    ("completions", "completions", "completions"),
    ("passing td", "pass_td", "passing TDs"),
    ("pass td", "pass_td", "passing TDs"),
    ("interceptions", "interceptions", "interceptions"),
)
_POSITION_WORD = {"QB": "QBs", "RB": "RBs", "WR": "WRs", "TE": "TEs"}


def _nfl_root():
    import os
    from pathlib import Path

    override = str(os.environ.get("SYNDICATE_NFL_SOURCE_ROOT") or "").strip()
    if override:
        return Path(override)
    from syndicate.features.shared.prop_evidence.common import data_root

    return data_root() / "nfl_source"


def _nfl_dvp_table() -> Mapping[str, Any] | None:
    import re

    from syndicate.features.shared.prop_evidence import common as C

    derived = _nfl_root() / "tracking" / "derived"
    best = None
    for path in derived.glob("nfl_defense_vs_position_*_wk*.json") if derived.is_dir() else []:
        m = re.fullmatch(r"nfl_defense_vs_position_(\d{4})_wk(\d+)\.json", path.name)
        if m and (best is None or (int(m.group(1)), int(m.group(2))) > best[0]):
            best = ((int(m.group(1)), int(m.group(2))), path)
    return C.load_json(best[1]) if best else None


def _nfl_position(player_name: str, season: Any) -> str | None:
    from syndicate.features.shared.prop_evidence import common as C

    path = _nfl_root() / "tracking" / "nflverse" / "roster" / f"roster_{season}.csv"
    if not path.is_file():
        return None
    cache = C._READ_CACHE.get()
    key = ("nfl_roster_positions", C._cache_key(path)) if cache is not None else None
    index = cache.get(key) if key is not None else None
    if index is None:
        index = {}
        for row in C.iter_csv(path):
            pos = str(row.get("position") or "").upper()
            pos = {"HB": "RB", "FB": "RB"}.get(pos, pos)
            if pos in _POSITION_WORD:
                index.setdefault(str(row.get("full_name") or ""), pos)
        if key is not None:
            cache[key] = index
    for name, pos in index.items():
        if C.names_match(name, player_name):
            return pos
    return None


def nfl_vs_position_text(row: Mapping[str, Any], opponent: str | None) -> str | None:
    """'Vs position: GB allows 33.2 receiving yards a game to TEs (rank 6 of 32, 1 = fewest).' Never raises."""
    try:
        if not opponent:
            return None
        market = str(row.get("market") or "").lower()
        table = _nfl_dvp_table()
        if not table:
            return None
        position = _nfl_position(str(row.get("player_name") or ""), table.get("season"))
        if position is None:
            return None
        stat = None
        for token, key, words in _NFL_MARKET_STAT:
            if token in market:
                stat = (key, words)
                break
        if "anytime" in market or market.strip() in {"touchdowns", "anytime td"}:
            stat = ("rush_td", "rushing TDs") if position == "RB" else ("rec_td", "receiving TDs") if position in {"WR", "TE"} else None
        if stat is None:
            return None
        cell = (((table.get("teams") or {}).get(opponent) or {}).get(position) or {}).get(stat[0])
        if not isinstance(cell, Mapping):
            return None
        return (
            f"Vs position: {opponent} allows {_fmt(_num(cell.get('per_game')))} {stat[1]} a game to "
            f"{_POSITION_WORD[position]} (rank {cell.get('rank')} of {cell.get('of')}, 1 = fewest; through week {table.get('through_week')})."
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[recent_matchup] NFL_DVP_FAILED error={type(exc).__name__}: {exc}", flush=True)
        return None


# ------------------------------------------------------ NBA / WNBA vs position
#
# Phase 2 (user 2026-10-08): `scripts/build_basketball_defense_vs_position.py`
# writes `<sport>_defense_vs_position_<season>_<phase>_asof_<date>.json` beside
# the box-score history. The sentence reads the REGULAR-SEASON table of the
# board date's own season only -- never last season's (an NBA board in October
# 2026 gets nothing until 2026-27 games exist) and never a mixed-phase table.

_BB_MARKET_STAT = (
    ("points_rebounds_assists", "pra", "points + rebounds + assists"), ("pra", "pra", "points + rebounds + assists"),
    ("points_rebounds", "pr", "points + rebounds"), ("points_assists", "pa", "points + assists"),
    ("rebounds_assists", "ra", "rebounds + assists"),
    ("threes", "fg3m", "threes"), ("3-point", "fg3m", "threes"), ("3pt", "fg3m", "threes"),
    ("rebounds", "reb", "rebounds"), ("assists", "ast", "assists"), ("points", "pts", "points"),
)
_BB_POSITION_WORD = {"G": "guards", "F": "forwards", "C": "centers"}
_WNBA_TEAM_ALIASES = {"GS": "GSV", "LV": "LVA", "LA": "LAS", "NY": "NYL", "CONN": "CON", "WAS": "WSH", "PHO": "PHX"}


def _bb_season(sport: str, selected_date: str) -> str:
    if sport == "wnba":
        return selected_date[:4]
    year, month = int(selected_date[:4]), int(selected_date[5:7])
    start = year if month >= 8 else year - 1
    return f"{start}-{str(start + 1)[2:]}"


def _bb_dvp_table(sport: str, season: str) -> Mapping[str, Any] | None:
    import os
    from pathlib import Path

    from syndicate.features.shared.prop_evidence import common as C

    override = str(os.environ.get(f"SYNDICATE_{sport.upper()}_SOURCE_ROOT") or "").strip()
    root = Path(override) if override else C.data_root() / f"{sport}_source"
    directory = root / ("source_artifacts/data/processed" if sport == "nba" else "data/processed")
    pattern = f"{sport}_defense_vs_position_{season}_regular_asof_*.json"
    cache = C._READ_CACHE.get()
    key = ("bb_dvp", str(directory), pattern) if cache is not None else None
    if key is not None and key in cache:
        return cache[key]
    files = sorted(directory.glob(pattern)) if directory.is_dir() else []
    table = C.load_json(files[-1]) if files else None
    table = table if isinstance(table, Mapping) else None
    if key is not None:
        cache[key] = table
    return table


def basketball_vs_position_text(row: Mapping[str, Any], opponent: str | None, *, selected_date: str) -> str | None:
    """'Vs position: LVA allows 42.9 points a game to guards (rank 2 of 15, 1 = fewest; 2026 regular season).' Never raises."""
    try:
        sport = str(row.get("sport") or "").lower()
        if sport not in {"nba", "wnba"} or not opponent:
            return None
        market = str(row.get("market") or "").lower().replace(" ", "_")
        stat = next(((key, words) for token, key, words in _BB_MARKET_STAT if token in market), None)
        combo = sum(1 for word in ("points", "rebounds", "assists") if word in market)
        if stat is None or (combo > 1 and stat[0] in {"pts", "reb", "ast"}):  # a combo never reads one stat
            return None
        table = _bb_dvp_table(sport, _bb_season(sport, selected_date))
        if not table:
            return None
        from syndicate.features.shared.prop_evidence import common as C

        name = str(row.get("player_name") or "")
        position = next((pos for known, pos in (table.get("player_positions") or {}).items() if C.names_match(known, name)), None)
        if position not in _BB_POSITION_WORD:
            return None
        team = str(opponent).strip().upper()
        if sport == "wnba":
            team = _WNBA_TEAM_ALIASES.get(team, team)
        cell = (((table.get("teams") or {}).get(team) or {}).get(position) or {}).get(stat[0])
        if not isinstance(cell, Mapping):
            return None
        return (
            f"Vs position: {team} allows {_fmt(_num(cell.get('per_game')))} {stat[1]} a game to "
            f"{_BB_POSITION_WORD[position]} (rank {cell.get('rank')} of {cell.get('of')}, 1 = fewest; "
            f"{table.get('season')} regular season, {cell.get('games')} game{'' if cell.get('games') == 1 else 's'})."
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[recent_matchup] BB_DVP_FAILED error={type(exc).__name__}: {exc}", flush=True)
        return None


# ------------------------------------------------------------ NHL vs position
#
# User 2026-10-08 (props must weigh "average stats allowed to players position"):
# `scripts/build_nhl_defense_vs_position.py` writes
# `nhl_source/data/processed/nhl_defense_vs_position_<season>_asof_<date>.json` --
# per team, what opposing FORWARDS and DEFENSEMEN produce per game against it,
# this season's regular season only, with ranks. Box-score names are
# "R. Donato", so the player's position is matched on (first initial, surname)
# and refused when two skaters share that key with different positions.

_NHL_MARKET_STAT = {"sog": ("sog", "shots on goal"), "shots on goal": ("sog", "shots on goal"),
                    "player_shots_on_goal": ("sog", "shots on goal"), "points": ("points", "points"),
                    "player_points": ("points", "points"), "assists": ("assists", "assists"),
                    "player_assists": ("assists", "assists"), "goals": ("goals", "goals"),
                    "player_goals": ("goals", "goals"), "player_goal_scorer_anytime": ("goals", "goals")}
_NHL_POSITION_WORD = {"F": "forwards", "D": "defensemen"}


def _initial_surname(name: str) -> tuple[str, str] | None:
    parts = [p for p in str(name or "").replace(".", ". ").split() if p]
    if len(parts) < 2:
        return None
    return parts[0][0].lower(), " ".join(parts[1:]).lower().replace(".", "").strip()


def _nhl_dvp_table(selected_date: str) -> Mapping[str, Any] | None:
    import os
    from pathlib import Path

    from syndicate.features.shared.prop_evidence import common as C

    try:
        year, month = int(selected_date[:4]), int(selected_date[5:7])
    except (TypeError, ValueError):
        return None
    start = year if month >= 9 else year - 1
    override = str(os.environ.get("SYNDICATE_NHL_SOURCE_ROOT") or "").strip()
    root = Path(override) if override else C.data_root() / "nhl_source"
    directory = root / "data" / "processed"
    pattern = f"nhl_defense_vs_position_{start}-{start + 1}_asof_*.json"
    cache = C._READ_CACHE.get()
    key = ("nhl_dvp", str(directory), pattern) if cache is not None else None
    if key is not None and key in cache:
        return cache[key]
    files = sorted(directory.glob(pattern)) if directory.is_dir() else []
    table = C.load_json(files[-1]) if files else None
    table = table if isinstance(table, Mapping) else None
    if table is not None:
        index: dict[tuple[str, str], set[str]] = {}
        for name, pos in (table.get("player_positions") or {}).items():
            k = _initial_surname(name)
            if k:
                index.setdefault(k, set()).add(str(pos))
        table = dict(table, _index=index)
    if key is not None:
        cache[key] = table
    return table


def nhl_vs_position_text(row: Mapping[str, Any], opponent: str | None, *, selected_date: str) -> str | None:
    """'Vs position: BOS allows 20.8 shots on goal a game to forwards (rank 18 of 32, 1 = fewest; 4 games this season).'"""
    try:
        if not opponent:
            return None
        stat = _NHL_MARKET_STAT.get(str(row.get("market") or "").strip().lower())
        table = _nhl_dvp_table(selected_date)
        if stat is None or not table:
            return None
        k = _initial_surname(str(row.get("player_name") or ""))
        positions = (table.get("_index") or {}).get(k) if k else None
        if not positions or len(positions) != 1:
            return None  # unknown or ambiguous (two skaters, two positions): never guessed
        position = next(iter(positions))
        team = str(opponent).strip().upper()
        cell = (((table.get("teams") or {}).get(team) or {}).get(position) or {}).get(stat[0])
        if not isinstance(cell, Mapping) or position not in _NHL_POSITION_WORD:
            return None
        games = int(cell.get("games") or 0)
        return (
            f"Vs position: {team} allows {_fmt(_num(cell.get('per_game')))} {stat[1]} a game to "
            f"{_NHL_POSITION_WORD[position]} (rank {cell.get('rank')} of {cell.get('of')}, 1 = fewest; "
            f"{games} game{'' if games == 1 else 's'} this season)."
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[recent_matchup] NHL_DVP_FAILED error={type(exc).__name__}: {exc}", flush=True)
        return None


# ---------------------------------------------------------------- per-game values
#
# For the Layer 2 board's per-row L5/L10 charts (lane layer2-board-ui-redesign,
# user-approved 2026-10-08): the per-game values the "Recent form" sentence was
# computed from, kept beside it so the chart and the sentence can never disagree
# and no second evidence build is run. Written ONLY where that sentence's values
# are computed; additive -- the text, the memo and the budget are untouched.
# Bounded: cleared whole when it passes RECENT_VALUES_MAX (a board build is ~5k rows).

RECENT_VALUES: dict[tuple, dict[str, Any]] = {}
RECENT_VALUES_MAX = 20000


def _record_values(
    row: Mapping[str, Any],
    values: list[Any],
    dates: list[Any] | None = None,
    opponents: list[Any] | None = None,
) -> None:
    """Keep `values` (+ `dates` / `opponents` when they are ALIGNED with them) for the board chart.

    Labels are filtered TOGETHER with the values: dropping a `None` value used to
    happen after the fact, so one game with no stat silently cost the whole row
    its dates (the length check then failed). A label list that is not aligned
    with `values` is not used at all -- a mislabelled bar is worse than none.
    """
    if len(RECENT_VALUES) >= RECENT_VALUES_MAX:
        RECENT_VALUES.clear()
    raw = list(values)[:_RECENT_VALUES_N]
    labels = list(dates)[:_RECENT_VALUES_N] if dates and len(dates) >= len(raw) else None
    opps = list(opponents)[:_RECENT_VALUES_N] if opponents and len(opponents) >= len(raw) else None
    keep = [i for i, v in enumerate(raw) if v is not None]
    if not keep:
        return
    entry: dict[str, Any] = {
        "values": [float(raw[i]) for i in keep],
        "line": _num(row.get("line")),
        "side": str(row.get("side") or "").lower(),
    }
    if labels is not None:
        entry["dates"] = [str(labels[i]) for i in keep]
    if opps is not None:
        entry["opponents"] = [str(opps[i] or "") for i in keep]
    RECENT_VALUES[_memo_key(row)] = entry


def recent_values_for(row: Mapping[str, Any]) -> dict[str, Any] | None:
    """{values (newest first, <= 10), line, side, [dates], [opponents]} behind this row's Recent form sentence, or None."""
    return RECENT_VALUES.get(_memo_key(row))


_RECENT_VALUES_N = 10


def _memo_key(row: Mapping[str, Any]) -> tuple:
    return (
        str(row.get("sport") or "").lower(),
        str(row.get("player_name") or "").lower(),
        str(row.get("market") or ""),
        str(row.get("line")),
        str(row.get("side") or "").lower(),
        str(row.get("home_team") or ""),
        str(row.get("away_team") or ""),
    )


def prop_recent_matchup_text(row: Mapping[str, Any], *, selected_date: str, memo: dict | None = None) -> str | None:
    """Recency + matchup sentences for one prop row, or None. Never raises."""
    if str(row.get("kind") or "").lower() != "prop" or not row.get("player_name"):
        return None
    key = _memo_key(row)
    if memo is not None and key in memo:
        return memo[key]
    text = None
    if key[0] == "mlb":
        text = mlb_prop_recent_matchup_text(row, selected_date=selected_date)
        if memo is not None:
            memo[key] = text
        return text
    try:
        from syndicate.features.shared.prop_evidence import build_prop_evidence
        from syndicate.features.shared.prop_evidence.contract import Layer

        evidence = build_prop_evidence(dict(row), selected_date=selected_date)
        if evidence is not None:
            recent = evidence.layers.get(Layer.RECENT_FORM)
            match = evidence.layers.get(Layer.MATCHUP)
            try:  # the chart side-channel must never cost the sentence
                facts = getattr(recent, "facts", None) or {}
                if getattr(recent, "filled", True) and isinstance(facts.get("values"), list):
                    _record_values(row, facts["values"], facts.get("game_labels"), facts.get("opponents"))
            except Exception:  # noqa: BLE001
                pass
            match_facts = match.facts if match is not None else None
            pieces = [
                recent_form_text(recent.facts if recent is not None else None),
                matchup_text(match_facts),
            ]
            if key[0] == "nfl":
                opponent = str((match_facts or {}).get("opponent") or "").strip() or None
                pieces.append(nfl_vs_position_text(row, opponent))
            elif key[0] == "nhl":
                opponent = str((match_facts or {}).get("opponent") or "").strip() or None
                pieces.append(nhl_vs_position_text(row, opponent, selected_date=selected_date))
            elif key[0] in {"nba", "wnba"}:
                opponent = str((match_facts or {}).get("opponent") or "").strip() or None
                pieces.append(basketball_vs_position_text(row, opponent, selected_date=selected_date))
            text = " ".join(piece for piece in pieces if piece) or None
    except Exception as exc:  # noqa: BLE001 -- an explanation must never break a card
        print(f"[recent_matchup] FAILED sport={key[0]} error={type(exc).__name__}: {exc}", flush=True)
        text = None
    if memo is not None:
        memo[key] = text
    return text
