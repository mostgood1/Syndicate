"""NHL in-season team xG: `team_xg_<season>.csv` rebuilt from the current season as games are played.
Lane `nhl-season-inputs-in-season`.

WHY. Production projected every 2026-27 game from FROZEN 2025-26 season files: `team_xg_latest.csv` was
built 2026-08-18, `_ensure_season_inputs` only pulls missing `_latest` files, and nothing rebuilt season
inputs in-season. Team xG is the ONLY team-strength input to the game lines (`projection.project_game`;
Elo's blend weight is 0). The loaders already prefer `team_xg_<season>.csv` over `team_xg_latest.csv`
(`features/loaders.load_team_xg_map`), so writing the season file is the whole switch.

WHAT IT WRITES. Per team, an empirical-Bayes blend of last season and this season-to-date:
    rate = (W * prior + n * current) / (W + n)      n = the team's finished regular-season games
  * prior   -- `team_xg_latest.csv` exactly as production holds it (the previous full season);
  * current -- this season's play-by-play, every Fenwick shot incl. empty-net summed per game (the
    production aggregation of `scripts/build_nhl_xg_artifact.py`), scored by FROZEN_XG and put on the
    prior's scale by CURRENT_TO_PRIOR_SCALE.
MEASURED (scripts/nhl_season_inputs_experiment.py): W=10 chosen on 2024-25 (prior 2023-24), then frozen;
on 2025-26 from opening night (n=1,312, production form) blend - prior-only ML Brier -0.0033
[-0.0052, -0.0015], total MAE not worse; vs the close prior-only +0.0037 -> blend +0.0004.

FROZEN_XG. The production estimator (`shot_xg_model.featurize` + logistic), fit 2026-10-04 on 341,079
Fenwick shots of the 2023-24, 2024-25 and 2025-26 regular seasons (every one before 2026-27). On 2025-26
it ranks teams like production's own `team_xg_latest.csv` (corr 0.9987 xGF / 0.9984 xGA) at a level
3.27% higher, hence CURRENT_TO_PRIOR_SCALE = 1 / 1.0327.

NEVER RAISES. Generation must still run: any failure returns a status dict and writes nothing, so the
loaders keep reading the previous file (or `_latest`).
"""
from __future__ import annotations

import csv
import json
import math
import os
import tempfile
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

BLEND_WEIGHT_GAMES = 10.0
CURRENT_TO_PRIOR_SCALE = 1.0 / 1.0327
FROZEN_XG = {
    "intercept": -0.5954893263738329,
    # order == shot_xg_model.FEATURE_NAMES: distance, angle, is_rebound, is_empty_net, shot_type_backhand,
    # _deflected, _slap, _snap, _tip-in, _wrap-around, _other, strength_PP, strength_SH
    "coef": [-0.055017, -0.017572, -0.103703, 3.993485, -0.371359, -0.591091, 0.404817, 0.358949,
             -0.828223, -0.656677, -0.194265, 0.300123, 0.029769],
}
REGULAR_SEASON = 2
FINAL_STATES = frozenset({"FINAL", "OFF"})

FetchJson = Callable[[str], Any]


def season_code(day: date) -> str:
    """NHL season of a calendar date: September onward belongs to the season starting that year."""
    start = day.year if day.month >= 9 else day.year - 1
    return f"{start}-{start + 1}"


def _xg(shots: list) -> List[float]:
    from syndicate.features.nhl.sim_engine.hockeysim.historical_truth import shot_xg_model as X

    out = []
    for row in X.featurize(shots):
        z = FROZEN_XG["intercept"] + sum(c * v for c, v in zip(FROZEN_XG["coef"], row))
        out.append(1.0 / (1.0 + math.exp(-z)))
    return out


def game_xg(pbp: dict) -> Optional[Tuple[str, str, float, float]]:
    """(home_abbr, away_abbr, home xGF, away xGF) for one finished game's play-by-play."""
    from syndicate.features.nhl.sim_engine.hockeysim.historical_truth import shot_xg_model as X

    home, away = pbp.get("homeTeam") or {}, pbp.get("awayTeam") or {}
    if home.get("id") is None or not pbp.get("plays"):
        return None
    shots = X.parse_play_by_play_shots(pbp)
    xs = _xg(shots)
    home_id = int(home["id"])
    hx = sum(x for s, x in zip(shots, xs) if s.team_id == home_id)
    ax = sum(x for s, x in zip(shots, xs) if s.team_id != home_id)
    return str(home.get("abbrev") or "").upper(), str(away.get("abbrev") or "").upper(), hx, ax


def _read_prior(path: Path) -> Dict[str, Tuple[float, float]]:
    out: Dict[str, Tuple[float, float]] = {}
    try:
        for row in csv.DictReader(path.open(encoding="utf-8")):
            out[str(row["abbr"]).upper()] = (float(row["xgf60"]), float(row["xga60"]))
    except (OSError, KeyError, ValueError):
        return {}
    return out


def blend(prior: Dict[str, Tuple[float, float]], current: Dict[str, Tuple[int, float, float]],
          w: float = BLEND_WEIGHT_GAMES) -> Dict[str, Tuple[float, float, int]]:
    """{abbr: (xgf60, xga60, n_current)}. current = {abbr: (n, sum xGF, sum xGA)} on the PRIOR's scale."""
    out = {}
    for team, (pf, pa) in prior.items():
        n, sf, sa = current.get(team, (0, 0.0, 0.0))
        out[team] = ((w * pf + sf) / (w + n), (w * pa + sa) / (w + n), n)
    return out


def finished_regular_games(fetch: FetchJson, *, start: date, end: date, base: str,
                           cache_dir: Optional[Path] = None) -> Tuple[List[dict], List[str]]:
    """Every finished regular-season game filed on start..end. A day at least two days old is settled,
    so its score payload is cached under `cache_dir` and never re-fetched (without this a late-season
    run would re-read ~200 days of the feed every sweep)."""
    from syndicate.features.shared.bet_status_nhl import parse_score_games

    games, unreadable = [], []
    seen = set()
    day = start
    while day <= end:
        payload = None
        cached_path = cache_dir / f"score_{day.isoformat()}.json" if cache_dir is not None else None
        settled = day <= end - timedelta(days=2)
        if settled and cached_path is not None and cached_path.exists():
            try:
                payload = json.loads(cached_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                payload = None
        if payload is None:
            payload = fetch(f"{base}/score/{day.isoformat()}")
            if settled and cached_path is not None and parse_score_games(payload) is not None:
                cached_path.parent.mkdir(parents=True, exist_ok=True)
                cached_path.write_text(json.dumps(payload), encoding="utf-8")
        parsed = parse_score_games(payload)
        if parsed is None:
            unreadable.append(day.isoformat())
        for g in parsed or []:
            if g.get("game_type") == REGULAR_SEASON and g.get("state") in FINAL_STATES and g["game_id"] not in seen:
                seen.add(g["game_id"])
                games.append(g)
        day += timedelta(days=1)
    return games, unreadable


def _write_atomic(path: Path, rows: List[Tuple[str, float, float, int]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["abbr", "xgf60", "xga60", "games"])
        for abbr, f, a, n in rows:
            w.writerow([abbr, round(f, 4), round(a, 4), n])
    os.replace(tmp, path)


def refresh_inseason_team_xg(artifact_root: Path, *, today: Optional[date] = None, fetch: Optional[FetchJson] = None,
                             season_start: Optional[date] = None, base: str = "https://api-web.nhle.com/v1") -> Dict[str, Any]:
    """Rebuild `<root>/data/processed/team_xg_<season>.csv` from the cached + newly finished games.
    Play-by-play is cached under `<root>/data/ingestion_cache/playbyplay_<gid>.json` (fetched once)."""
    status: Dict[str, Any] = {"wrote": False}
    try:
        if fetch is None:
            from syndicate.features.nhl.boxscore_log import fetch_json as fetch
        today = today or date.today()
        season = season_code(today)
        start_year = int(season[:4])
        season_start = season_start or date(start_year, 9, 15)
        processed = artifact_root / "data" / "processed"
        cache = artifact_root / "data" / "ingestion_cache"
        prior = _read_prior(processed / "team_xg_latest.csv")
        status.update(season=season, prior_teams=len(prior))
        if len(prior) < 30:
            status["reason"] = "prior team_xg_latest.csv missing or short; nothing written"
            return status
        games, unreadable = finished_regular_games(fetch, start=season_start, end=today, base=base, cache_dir=cache)
        status.update(finished_regular_games=len(games), unreadable_days=len(unreadable))
        current: Dict[str, List[float]] = {}
        fetched = cached = failed = 0
        for g in games:
            gid = g["game_id"]
            path = cache / f"playbyplay_{gid}.json"
            pbp = None
            if path.exists() and path.stat().st_size > 0:
                try:
                    pbp = json.loads(path.read_text(encoding="utf-8"))
                    cached += 1
                except (OSError, ValueError):
                    pbp = None
            if pbp is None:
                pbp = fetch(f"{base}/gamecenter/{gid}/play-by-play")
                if not isinstance(pbp, dict) or not pbp.get("plays"):
                    failed += 1
                    continue
                cache.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(pbp), encoding="utf-8")
                fetched += 1
            res = game_xg(pbp)
            if res is None:
                failed += 1
                continue
            h, a, hx, ax = res
            for team, xf, xa in ((h, hx, ax), (a, ax, hx)):
                e = current.setdefault(team, [0, 0.0, 0.0])
                e[0] += 1
                e[1] += xf * CURRENT_TO_PRIOR_SCALE
                e[2] += xa * CURRENT_TO_PRIOR_SCALE
        status.update(pbp_cached=cached, pbp_fetched=fetched, pbp_failed=failed)
        rates = blend(prior, {t: (int(v[0]), v[1], v[2]) for t, v in current.items()})
        rows = sorted((t, f, a, n) for t, (f, a, n) in rates.items())
        out = processed / f"team_xg_{season}.csv"
        _write_atomic(out, rows)
        status.update(wrote=True, path=str(out), teams=len(rows), games_used=sum(int(v[0]) for v in current.values()) // 2,
                      max_team_games=max((int(v[0]) for v in current.values()), default=0))
    except Exception as exc:  # noqa: BLE001 -- generation must still run on the previous file
        status["reason"] = f"error={type(exc).__name__}: {exc}"
    print(f"[nhl_inseason_xg] NHL_INSEASON_TEAM_XG {json.dumps(status, sort_keys=True)}", flush=True)
    return status
