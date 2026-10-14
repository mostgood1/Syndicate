"""Football matchup signals (NFL, NCAAF): as-of usage features, the registered firing rules, and their registry.

Lane `signal-engine-football` (2026-10-13). Plan: `.syndicate/findings_2026-10-13_matchup_signal_plan.md` §3-§4.
Statistics, storage and the SignalSpec shape are shared with the NBA engine (`matchup_signals.py`); the football
registry is kept here so the NBA lift harness, which iterates `matchup_signals.REGISTRY`, never sees football rows.

AS-OF RULE. Every feature for (season, week W) is computed from the player's / team's games in the SAME season with
week < W, and stored in `<data root>/<sport>_source/signals/<season>/wkNN.jsonl` (one row per player, plus one row per
team with `kind: "team"`). A table for week W never reads week W's games. Firing is evaluated from those stored
features with the thresholds below -- the tables hold features only, so a threshold can never leak into them.

SHARES. A player's share over a set of games = sum(player count) / sum(team count) over THOSE games (the player's own
appearances), not a mean of per-game shares. `l3` = the last 3 appearances, `base` = the appearances before them (at
least 2), `trend` = l3 - base (None when base is unknown).
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from syndicate.features.shared.matchup_signals import SignalSpec

__all__ = [
    "NFL_REC_MARKETS",
    "NFL_RUSH_MARKETS",
    "NFL_PASS_MARKETS",
    "NCAAF_REC_MARKETS",
    "NCAAF_RUSH_MARKETS",
    "NCAAF_YARDAGE_MARKETS",
    "FOOTBALL_MARKET_STATS",
    "THRESHOLDS",
    "FOOTBALL_REGISTRY",
    "week_key",
    "share_features",
    "nfl_signal_fires",
    "ncaaf_signal_fires",
    "nfl_eligible",
    "ncaaf_eligible",
]

# market display name in the OddsAPI-shaped quote logs -> stat key in the box / pbp aggregation
FOOTBALL_MARKET_STATS = {
    "Receptions": "receptions", "Receiving Yards": "receiving_yards", "Rushing Yards": "rushing_yards",
    "Rushing Attempts": "rushing_attempts", "Passing Yards": "passing_yards", "Passing Attempts": "passing_attempts",
    "Passing TDs": "passing_tds", "Interceptions": "interceptions",
}
NFL_REC_MARKETS = ("receptions", "receiving_yards")
NFL_RUSH_MARKETS = ("rushing_attempts", "rushing_yards")
NFL_PASS_MARKETS = ("passing_attempts", "passing_yards")
NCAAF_REC_MARKETS = ("receptions", "receiving_yards")
NCAAF_RUSH_MARKETS = ("rushing_yards",)
NCAAF_YARDAGE_MARKETS = ("passing_yards", "rushing_yards", "receiving_yards")

# The registered thresholds (lane block `signal-engine-football`, "FOOTBALL v1 PRE-REGISTERED"). RULE: each trend /
# PROE / pace threshold is the DISCOVER-window 10th (down) or 90th (up) percentile of that feature over the eligible
# quoted main lines, rounded; read from features only, before any outcome was loaded. The vacated-share features are
# zero-inflated (a percentile rule would fire on trivial absences), so they use a fixed "material teammate" cut: a
# fresh absence worth >= 10% of the team's targets / carries. Do not edit after registration.
THRESHOLDS: dict[str, float] = {
    "nfl_tgt_up": 0.07,          # target share last 3 - base >= +0.07   (discover p90 +0.0731)
    "nfl_tgt_down": 0.06,        #                          <= -0.06   (p10 -0.058)
    "nfl_carry_up": 0.14,        # carry share trend >= +0.14            (p90 +0.1406)
    "nfl_carry_down": 0.12,      #                   <= -0.12            (p10 -0.1184)
    "nfl_vac_tgt": 0.10,         # fresh vacated target share >= 0.10    (material teammate)
    "nfl_vac_carry": 0.10,       # fresh vacated carry share >= 0.10
    "nfl_proe_high": 4.5,        # team season-to-date mean PROE >= +4.5 (p90 +4.72)
    "nfl_proe_low": 7.0,         #                               <= -7.0 (p10 -7.19; the population centres near -2)
    "nfl_min_share": 0.10,       # an "active" receiver / rusher for the vacated signals
    "nfl_min_pass_share": 0.80,  # the team's starting passer for the PROE signals
    "ncaaf_carry_up": 0.17,      # (2025 discover p90 +0.1663)
    "ncaaf_carry_down": 0.09,    # (p10 -0.0922)
    "ncaaf_rec_up": 0.10,        # (p90 +0.1047)
    "ncaaf_rec_down": 0.08,      # (p10 -0.0813)
    "ncaaf_pace": 144.0,         # team + opponent offensive plays per game >= 144 (p90 144.37)
}


def week_key(week: int) -> str:
    return f"wk{int(week):02d}"


def share_features(prior: Sequence[tuple[float, float]], prefix: str) -> dict[str, Any]:
    """From (player count, team count) per prior appearance, oldest -> newest."""
    def share(games: Sequence[tuple[float, float]]) -> float | None:
        team = sum(t for _, t in games)
        return round(sum(p for p, _ in games) / team, 4) if team > 0 else None

    l3, base = list(prior[-3:]), list(prior[:-3])
    out = {f"{prefix}_season": share(prior), f"{prefix}_l3": share(l3) if len(l3) == 3 else None,
           f"{prefix}_base": share(base) if len(base) >= 2 else None}
    out[f"{prefix}_trend"] = (round(out[f"{prefix}_l3"] - out[f"{prefix}_base"], 4)
                              if out[f"{prefix}_l3"] is not None and out[f"{prefix}_base"] is not None else None)
    return out


def _ge(value: Any, threshold: float) -> bool:
    return value is not None and threshold > 0 and value >= threshold


def _le(value: Any, threshold: float) -> bool:
    return value is not None and threshold > 0 and value <= -threshold


def nfl_signal_fires(f: Mapping[str, Any], t: Mapping[str, float] = THRESHOLDS) -> list[str]:
    """The NFL rules on one player-week's as-of features. Unknown inputs never fire; a player listed OUT fires nothing."""
    if f.get("out_this_week"):
        return []
    fired: list[str] = []
    if _ge(f.get("tgt_trend"), t["nfl_tgt_up"]):
        fired.append("nfl.target_share_up")
    if _le(f.get("tgt_trend"), t["nfl_tgt_down"]):
        fired.append("nfl.target_share_down")
    if _ge(f.get("carry_trend"), t["nfl_carry_up"]):
        fired.append("nfl.carry_share_up")
    if _le(f.get("carry_trend"), t["nfl_carry_down"]):
        fired.append("nfl.carry_share_down")
    if _ge(f.get("vac_tgt_fresh"), t["nfl_vac_tgt"]) and (f.get("tgt_share_season") or 0) >= t["nfl_min_share"]:
        fired.append("nfl.vacated_targets")
    if _ge(f.get("vac_carry_fresh"), t["nfl_vac_carry"]) and (f.get("carry_share_season") or 0) >= t["nfl_min_share"]:
        fired.append("nfl.vacated_carries")
    passer = (f.get("pass_share_season") or 0) >= t["nfl_min_pass_share"]
    if passer and _ge(f.get("team_proe"), t["nfl_proe_high"]):
        fired.append("nfl.team_pass_heavy")
    if passer and _le(f.get("team_proe"), t["nfl_proe_low"]):
        fired.append("nfl.team_run_heavy")
    return fired


def nfl_eligible(name: str, f: Mapping[str, Any], t: Mapping[str, float] = THRESHOLDS) -> bool:
    """Lines where the signal COULD have fired (its inputs are known) -- the baseline population."""
    if f.get("out_this_week"):
        return False
    if name in ("nfl.target_share_up", "nfl.target_share_down"):
        return f.get("tgt_trend") is not None
    if name in ("nfl.carry_share_up", "nfl.carry_share_down"):
        return f.get("carry_trend") is not None
    if name == "nfl.vacated_targets":
        return f.get("vac_tgt_fresh") is not None and (f.get("tgt_share_season") or 0) >= t["nfl_min_share"]
    if name == "nfl.vacated_carries":
        return f.get("vac_carry_fresh") is not None and (f.get("carry_share_season") or 0) >= t["nfl_min_share"]
    if name in ("nfl.team_pass_heavy", "nfl.team_run_heavy"):
        return f.get("team_proe") is not None and (f.get("pass_share_season") or 0) >= t["nfl_min_pass_share"]
    return False


def ncaaf_signal_fires(f: Mapping[str, Any], t: Mapping[str, float] = THRESHOLDS) -> list[str]:
    """NCAAF rules; `game_pace` (team + opponent plays per game, as of) is attached per game by the caller."""
    fired: list[str] = []
    if _ge(f.get("carry_trend"), t["ncaaf_carry_up"]):
        fired.append("ncaaf.carry_share_up")
    if _le(f.get("carry_trend"), t["ncaaf_carry_down"]):
        fired.append("ncaaf.carry_share_down")
    if _ge(f.get("rec_trend"), t["ncaaf_rec_up"]):
        fired.append("ncaaf.reception_share_up")
    if _le(f.get("rec_trend"), t["ncaaf_rec_down"]):
        fired.append("ncaaf.reception_share_down")
    if _ge(f.get("game_pace"), t["ncaaf_pace"]):
        fired.append("ncaaf.fast_game")
    return fired


def ncaaf_eligible(name: str, f: Mapping[str, Any], t: Mapping[str, float] = THRESHOLDS) -> bool:
    if name in ("ncaaf.carry_share_up", "ncaaf.carry_share_down"):
        return f.get("carry_trend") is not None
    if name in ("ncaaf.reception_share_up", "ncaaf.reception_share_down"):
        return f.get("rec_trend") is not None
    if name == "ncaaf.fast_game":
        return f.get("game_pace") is not None
    return False


_NFL_SRC = "nflverse play-by-play (REG, same season, weeks before), nflverse injury reports (final status)"
_NCAAF_SRC = "CFBD player box history (same season, weeks before)"

FOOTBALL_REGISTRY: dict[str, SignalSpec] = {
    spec.name: spec
    for spec in (
        SignalSpec("nfl.target_share_up", "nfl", "over", NFL_REC_MARKETS,
                   "Target share rising: the last 3 games show a bigger role than the season before them.", _NFL_SRC,
                   "target share over the last 3 appearances - over the >= 2 appearances before them >= +nfl_tgt_up"),
        SignalSpec("nfl.target_share_down", "nfl", "under", NFL_REC_MARKETS,
                   "Target share falling.", _NFL_SRC,
                   "target share last 3 - base <= -nfl_tgt_down"),
        SignalSpec("nfl.carry_share_up", "nfl", "over", NFL_RUSH_MARKETS,
                   "Carry share rising.", _NFL_SRC, "carry share last 3 - base >= +nfl_carry_up"),
        SignalSpec("nfl.carry_share_down", "nfl", "under", NFL_RUSH_MARKETS,
                   "Carry share falling.", _NFL_SRC, "carry share last 3 - base <= -nfl_carry_down"),
        SignalSpec("nfl.vacated_targets", "nfl", "over", NFL_REC_MARKETS,
                   "A teammate who played last game is OUT: his targets are redistributed.", _NFL_SRC,
                   "sum of season-to-date target shares of teammates listed OUT who appeared in the team's previous "
                   "game >= nfl_vac_tgt, and the player's own target share >= nfl_min_share"),
        SignalSpec("nfl.vacated_carries", "nfl", "over", NFL_RUSH_MARKETS,
                   "A teammate who played last game is OUT: his carries are redistributed.", _NFL_SRC,
                   "fresh vacated carry share >= nfl_vac_carry and the player's own carry share >= nfl_min_share"),
        SignalSpec("nfl.team_pass_heavy", "nfl", "over", NFL_PASS_MARKETS,
                   "The team passes more than the situation predicts (PROE) -- volume for its starting passer.",
                   _NFL_SRC, "team season-to-date mean pass_oe >= +nfl_proe_high and the player threw >= "
                   "nfl_min_pass_share of the team's attempts"),
        SignalSpec("nfl.team_run_heavy", "nfl", "under", NFL_PASS_MARKETS,
                   "The team passes less than the situation predicts.", _NFL_SRC,
                   "team season-to-date mean pass_oe <= -nfl_proe_low, starting passer"),
        SignalSpec("ncaaf.carry_share_up", "ncaaf", "over", NCAAF_RUSH_MARKETS,
                   "Carry share rising.", _NCAAF_SRC, "carry share last 3 - base >= +ncaaf_carry_up"),
        SignalSpec("ncaaf.carry_share_down", "ncaaf", "under", NCAAF_RUSH_MARKETS,
                   "Carry share falling.", _NCAAF_SRC, "carry share last 3 - base <= -ncaaf_carry_down"),
        SignalSpec("ncaaf.reception_share_up", "ncaaf", "over", NCAAF_REC_MARKETS,
                   "Reception share rising (box has no targets).", _NCAAF_SRC,
                   "reception share last 3 - base >= +ncaaf_rec_up"),
        SignalSpec("ncaaf.reception_share_down", "ncaaf", "under", NCAAF_REC_MARKETS,
                   "Reception share falling.", _NCAAF_SRC, "reception share last 3 - base <= -ncaaf_rec_down"),
        SignalSpec("ncaaf.fast_game", "ncaaf", "over", NCAAF_YARDAGE_MARKETS,
                   "Both offenses run many plays: more snaps for everyone.", _NCAAF_SRC,
                   "team + opponent offensive plays per game (rush att + pass att, season to date) >= ncaaf_pace"),
    )
}
