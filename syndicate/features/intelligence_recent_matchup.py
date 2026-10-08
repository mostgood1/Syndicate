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
        if xga is not None:
            return f"{opponent} allows {_fmt(xga, 2)} xG/60"
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
        recent = sorted(log_rows, key=lambda r: str(r.get("date") or ""))[-_MLB_LAST_N:]
        if cols and recent:
            values = _mlb_side_values(recent, cols)
            line = _num(row.get("line"))
            side = str(row.get("side") or "").lower()
            if values and line is not None and side in {"over", "under"}:
                hits = sum(1 for v in values if (v > line if side == "over" else v < line))
                pieces.append(
                    f"Recent form: {side} {_fmt(line)} in {hits} of the last {len(values)} logged games "
                    f"(avg {_fmt(sum(values) / len(values))}; log since {recent[0].get('date')})."
                )
        if not is_pitcher:
            team = str((sorted(log_rows, key=lambda r: str(r.get("date") or ""))[-1:] or [{}])[0].get("team") or "")
            pitcher = _mlb_opposing_starter(row, team, selected_date)
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
            pieces = [
                recent_form_text(recent.facts if recent is not None else None),
                matchup_text(match.facts if match is not None else None),
            ]
            text = " ".join(piece for piece in pieces if piece) or None
    except Exception as exc:  # noqa: BLE001 -- an explanation must never break a card
        print(f"[recent_matchup] FAILED sport={key[0]} error={type(exc).__name__}: {exc}", flush=True)
        text = None
    if memo is not None:
        memo[key] = text
    return text
