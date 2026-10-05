"""NHL goalie GSAx factor for GAME-LINE totals (lane `nhl-game-lines-model`, user: "ship GSAx for totals with the
confirmed starters").

WHAT. Each team's goal lambdas are scaled by the OPPOSING starter's shrunk goals-allowed / xG-faced ratio relative to
the league (experiment V8, lane nhl-game-lines-model 2026-10-03):
    r_g = (GA_g + w * GA_prior_g + k * L) / (xG_g + w * xG_prior_g + k),   factor_g = r_g / L
  * GA_g, xG_g: this season's unblocked shots on goalie g with a goalie in net (no empty net), xG from FROZEN_XG;
  * GA_prior_g, xG_prior_g: the same for 2025-26 (PRIOR_2025_26), weight w = 0.25;
  * L: this season's league GA / xG; k = 160 xG. (k, w) were tuned on 2025-26 before 2026-01-01 and frozen.
  * a goalie with no shots faced this season gets NO factor (1.0), exactly as V8 did.
The starter is production's `starting_goalies_<date>.csv` (Daily Faceoff confirmed, else the collector's
projection), mapped to a player id through `lineups_<date>.csv`.

WHY. V8: totals improve (OOS OVER 6.5 vs the GF/GA baseline -0.0062 [-0.0115, -0.0012]); ML unchanged.
Applied ONLY to game lines (`scripts/build_nhl_artifacts`); props never see it. Off switch: SYNDICATE_NHL_GOALIE_GSAX=off.
NEVER RAISES.
"""
from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from syndicate.features.nhl.inseason_team_xg import _xg, season_code

ENV = "SYNDICATE_NHL_GOALIE_GSAX"
GSAX_K = 160.0
GSAX_PRIOR_W = 0.25
# 2025-26 regular season (1,312 games, 0 misaligned, 98 goalies): pid -> (xG faced by FROZEN_XG, goals allowed),
# unblocked non-empty-net shots on goal. Frozen 2026-10-05.
PRIOR_2025_26: Dict[int, Tuple[float, float]] = {
    8471734: (71.5106, 73), 8473503: (34.518, 33), 8474593: (118.913, 130), 8474596: (115.8259, 104),
    8475311: (139.3497, 151), 8475660: (88.088, 96), 8475683: (144.0703, 156), 8475717: (47.4071, 53),
    8475809: (118.3268, 98), 8475831: (90.1587, 83), 8475852: (28.9989, 35), 8475883: (109.9819, 111),
    8476316: (3.2528, 6), 8476341: (98.4385, 89), 8476412: (104.1772, 130), 8476434: (162.8012, 150),
    8476883: (162.1574, 136), 8476899: (11.8677, 10), 8476914: (95.2969, 92), 8476932: (74.9878, 80),
    8476945: (169.6527, 167), 8476999: (125.712, 133), 8477405: (0.7436, 2), 8477424: (183.8496, 186),
    8477465: (95.4063, 99), 8477480: (71.3222, 73), 8477484: (16.4303, 20), 8477831: (2.2207, 3),
    8477967: (61.3743, 55), 8477968: (111.6354, 110), 8477970: (54.6542, 59), 8477990: (2.4597, 4),
    8477992: (70.8012, 80), 8478007: (92.3369, 98), 8478009: (180.6413, 148), 8478024: (60.8461, 63),
    8478048: (150.6882, 127), 8478406: (100.5745, 90), 8478435: (141.7849, 124), 8478470: (81.5745, 84),
    8478499: (65.3753, 83), 8478872: (182.3187, 169), 8478916: (138.702, 141), 8478971: (83.7924, 81),
    8479193: (85.9448, 75), 8479292: (70.6533, 76), 8479312: (107.191, 93), 8479361: (124.7613, 126),
    8479394: (45.5943, 51), 8479406: (140.2024, 136), 8479496: (90.5236, 82), 8479973: (155.0964, 151),
    8479979: (156.2964, 145), 8480022: (0.1653, 0), 8480045: (100.9024, 85), 8480051: (7.289, 13),
    8480193: (101.1767, 101), 8480238: (4.05, 7), 8480280: (187.6384, 149), 8480313: (191.7299, 149),
    8480843: (181.2359, 173), 8480947: (145.3683, 161), 8480981: (130.8437, 118), 8481020: (80.8574, 67),
    8481033: (83.7495, 86), 8481035: (89.2212, 103), 8481519: (179.886, 163), 8481529: (10.4099, 9),
    8481544: (4.1836, 6), 8481551: (47.9697, 49), 8481611: (18.9234, 19), 8481668: (111.978, 128),
    8481692: (162.2603, 161), 8482076: (10.1282, 8), 8482123: (8.9221, 7), 8482137: (143.4358, 159),
    8482193: (10.8833, 7), 8482411: (1.043, 2), 8482445: (98.5901, 82), 8482447: (44.24, 64),
    8482487: (143.2733, 124), 8482515: (10.0565, 11), 8482661: (104.7934, 95), 8482761: (21.1285, 24),
    8482783: (4.7397, 8), 8482821: (88.6527, 97), 8482949: (3.5413, 1), 8482982: (171.5703, 150),
    8483114: (6.219, 8), 8483532: (12.3967, 8), 8483548: (105.7558, 100), 8483668: (8.95, 9),
    8483703: (11.5797, 12), 8483710: (59.2812, 50), 8483746: (1.4556, 3), 8484170: (54.0234, 43),
    8484268: (67.068, 71), 8484910: (3.1311, 2),
}


def enabled(env: Optional[Dict[str, str]] = None) -> bool:
    raw = str((env if env is not None else os.environ).get(ENV) or "").strip().lower()
    return raw not in {"0", "off", "false", "no"}


def goalies_in_order(pbp: dict) -> List[Optional[int]]:
    """goalieInNetId for exactly the shots `shot_xg_model.parse_play_by_play_shots` keeps, in the same order."""
    from syndicate.features.nhl.sim_engine.hockeysim.historical_truth import shot_xg_model as X

    home_id = (pbp.get("homeTeam") or {}).get("id")
    out: List[Optional[int]] = []
    for pl in pbp.get("plays") or []:
        if pl.get("typeDescKey") not in X._FENWICK_TYPES:
            continue
        d = pl.get("details") or {}
        if d.get("eventOwnerTeamId") is None or d.get("xCoord") is None or d.get("yCoord") is None:
            continue
        try:
            float(d["xCoord"]); float(d["yCoord"]); tid = int(d["eventOwnerTeamId"])
        except (TypeError, ValueError):
            continue
        if X._situation_state(pl.get("situationCode"), shooter_is_home=(tid == home_id)) is None:
            continue
        g = d.get("goalieInNetId")
        out.append(int(g) if g is not None else None)
    return out


def game_goalie_shots(pbp: dict, xg_fn=None) -> Optional[List[Tuple[int, float, int]]]:
    """[(goalie id, xG, goal)] for every non-empty-net unblocked shot on a goalie; None when misaligned."""
    from syndicate.features.nhl.sim_engine.hockeysim.historical_truth import shot_xg_model as X

    shots = X.parse_play_by_play_shots(pbp)
    gids = goalies_in_order(pbp)
    if len(gids) != len(shots):
        return None
    xs = (xg_fn or _xg)(shots)
    return [(gk, float(x), int(s.is_goal)) for s, gk, x in zip(shots, gids, xs) if gk is not None and not s.is_empty_net]


def gsax_factor(pid: Optional[int], table: Dict[int, Tuple[float, float]], league_ratio: float,
                prior: Optional[Dict[int, Tuple[float, float]]] = None, k: float = GSAX_K, w: float = GSAX_PRIOR_W) -> Optional[float]:
    """>1 = worse than the league. None (no factor) when the goalie has faced no shot this season."""
    prior = PRIOR_2025_26 if prior is None else prior
    if pid is None or pid not in table or not league_ratio:
        return None
    xg, ga = table[pid]
    if w and pid in prior:
        pxg, pga = prior[pid]
        xg += w * pxg
        ga += w * pga
    return ((ga + k * league_ratio) / (xg + k)) / league_ratio


def season_table(artifact_root: Path, day: date) -> Tuple[Dict[int, Tuple[float, float]], float, Dict[str, Any]]:
    """({pid: (xG faced, goals allowed)}, league GA / xG, status) from this season's cached regular-season
    play-by-play (`ingestion_cache/playbyplay_<YYYY>02*.json`, cached by `inseason_team_xg`) for games played
    STRICTLY BEFORE `day` -- as-of even when an old slate is rebuilt. In memory, no network, no file written."""
    season = season_code(day)
    cache = Path(artifact_root) / "data" / "ingestion_cache"
    agg: Dict[int, List[float]] = {}
    games = misaligned = later = 0
    for f in sorted(cache.glob(f"playbyplay_{season[:4]}02*.json")):
        try:
            pbp = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if str(pbp.get("gameDate") or "")[:10] >= day.isoformat():
            later += 1
            continue
        rows = game_goalie_shots(pbp)
        if rows is None:
            misaligned += 1
            continue
        games += 1
        for gk, x, g in rows:
            e = agg.setdefault(gk, [0.0, 0.0])
            e[0] += x
            e[1] += g
    xg = sum(v[0] for v in agg.values())
    ga = sum(v[1] for v in agg.values())
    status = {"season": season, "day": day.isoformat(), "games": games, "misaligned": misaligned,
              "skipped_not_before_day": later, "goalies": len(agg)}
    return {k: (v[0], v[1]) for k, v in agg.items()}, (ga / xg if xg > 0 else 0.0), status
