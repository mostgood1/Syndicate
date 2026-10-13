"""Matchup signals: a registry, dated as-of tables, and the lift statistics they are judged by.

Lane `signal-engine-nba` (2026-10-13). Plan: `.syndicate/findings_2026-10-13_matchup_signal_plan.md` §0-§2.

A SIGNAL is a named, point-in-time matchup feature for one bet type and side ("minutes trending up -> overs"). Every
signal is judged twice on the lines it fires on:

  - lift vs the BASELINE: does the side win more often when the signal fires than when it does not? (does it predict)
  - lift vs the MARKET: residual = outcome - calibrated market probability (the Shin fair). (is it already priced)

A signal that predicts but whose residual is ~0 is "strong, already priced" -- a correct and useful answer: the board
shows it as likelihood, not as value. Status moves `candidate` -> `supported` / `priced` / `null` only on a
pre-registered test (lane block), never by being looked at.

AS-OF RULE. Every value is computed from games STRICTLY BEFORE the game date and stored in a dated table
`<data root>/<sport>_source/signals/<season>/<YYYY-MM-DD>.jsonl`, one row per (player, game). A table written for a
date never reads that date's results. Nothing here is consumed by a sim or by the board's score yet.
"""
from __future__ import annotations

import json
import math
import os
import random
import re
import statistics
import unicodedata
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

__all__ = [
    "SignalSpec",
    "REGISTRY",
    "norm_player",
    "signal_table_path",
    "write_signal_table",
    "read_signal_table",
    "minutes_features",
    "start_features",
    "team_rest_days",
    "residual_stats",
    "bh_adjust",
]


# ----------------------------------------------------------------------------- registry


@dataclass(frozen=True)
class SignalSpec:
    name: str
    sport: str
    side: str  # the side the signal argues for: "over" | "under"
    markets: tuple[str, ...]
    description: str
    source: str
    rule: str  # the firing rule, stated exactly as tested
    status: str = "candidate"  # candidate | supported | priced | null
    evidence: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


NBA_COUNTING_MARKETS = (
    "player_points", "player_rebounds", "player_assists", "player_threes",
    "player_points_rebounds_assists", "player_points_rebounds", "player_points_assists", "player_rebounds_assists",
)
_NBA_LOGS = "stats.nba player game logs (MIN, starts from ESPN logs), schedule, consensus pregame spread"

REGISTRY: dict[str, SignalSpec] = {
    spec.name: spec
    for spec in (
        SignalSpec("nba.minutes_trend_up", "nba", "over", NBA_COUNTING_MARKETS,
                   "Minutes rising: role growing faster than a season average shows.", _NBA_LOGS,
                   "mean MIN of the last 3 games - mean MIN of the 10 before them >= +4.0 (>= 13 prior games)",
                   status="null", evidence={"tested": "2026-10-13 lane signal-engine-nba, 2025-26 regular season backfill", "discover_residual": -0.0079, "confirm_residual": -0.017, "confirm_ci95": [-0.0404, 0.0047], "confirm_n": 23124, "confirm_games": 441, "confirm_hit_lift_vs_baseline": 0.0016, "verdict": "NOT SUPPORTED"}),
        SignalSpec("nba.minutes_trend_down", "nba", "under", NBA_COUNTING_MARKETS,
                   "Minutes falling: role shrinking.", _NBA_LOGS,
                   "mean MIN of the last 3 games - mean MIN of the 10 before them <= -4.0 (>= 13 prior games)",
                   status="null", evidence={"tested": "2026-10-13 lane signal-engine-nba, 2025-26 regular season backfill", "discover_residual": 0.0006, "confirm_residual": -0.0061, "confirm_ci95": [-0.0276, 0.0158], "confirm_n": 18510, "confirm_games": 418, "confirm_hit_lift_vs_baseline": -0.0282, "verdict": "NOT SUPPORTED"}),
        SignalSpec("nba.start_promotion", "nba", "over", NBA_COUNTING_MARKETS,
                   "Moved into the starting lineup.", _NBA_LOGS,
                   "started the previous game AND started <= 3 of the 10 games before it",
                   status="null", evidence={"tested": "2026-10-13 lane signal-engine-nba, 2025-26 regular season backfill", "discover_residual": -0.0137, "confirm_residual": 0.0066, "confirm_ci95": [-0.0335, 0.0478], "confirm_n": 6712, "confirm_games": 276, "confirm_hit_lift_vs_baseline": 0.024, "verdict": "NOT SUPPORTED"}),
        SignalSpec("nba.b2b", "nba", "under", NBA_COUNTING_MARKETS,
                   "Second night of a back-to-back for a heavy-minutes player.", _NBA_LOGS,
                   "team played the previous calendar day AND prior-10 mean MIN >= 28",
                   status="null", evidence={"tested": "2026-10-13 lane signal-engine-nba, 2025-26 regular season backfill", "discover_residual": 0.0337, "confirm_residual": 0.0269, "confirm_ci95": [-0.0091, 0.0585], "confirm_n": 12842, "confirm_games": 145, "confirm_hit_lift_vs_baseline": 0.0017, "verdict": "NOT SUPPORTED"}),
        SignalSpec("nba.blowout_risk", "nba", "under", NBA_COUNTING_MARKETS,
                   "Lopsided spread: starters sit late.", _NBA_LOGS,
                   "pregame consensus |spread| >= 10 AND prior-10 mean MIN >= 30",
                   status="null", evidence={"tested": "2026-10-13 lane signal-engine-nba, 2025-26 regular season backfill", "discover_residual": 0.0079, "confirm_residual": 0.0295, "confirm_ci95": [-0.0003, 0.0604], "confirm_n": 14473, "confirm_games": 163, "confirm_hit_lift_vs_baseline": 0.0045, "verdict": "NOT SUPPORTED"}),
        SignalSpec("nba.under_bias", "nba", "under", NBA_COUNTING_MARKETS,
                   "NBA prop UNDERS are priced too long: the de-vigged market under-rates them. A LIKELIHOOD "
                   "adjustment (raise p_under), not a bet on its own -- blind unders still lose to the hold.",
                   "pre-tip prop prices (8 US books), stats.nba outcomes",
                   "every main-line prop, UNDER side (H6a); strongest on prior-10 MIN >= 30 late in the season (H6b)",
                   status="supported",
                   evidence={"tested": "2026-10-13 lane signal-engine-nba H6 (pre-registered 804f11d5), 2025-26 regular season, main lines",
                             "discover_residual": 0.0101, "discover_ci95": [0.0038, 0.0157],
                             "confirm_residual": 0.0161, "confirm_ci95": [0.0078, 0.0235], "confirm_n": 46262, "confirm_games": 488,
                             "roi_best_price_confirm": -0.75, "roi_best_price_confirm_ci95": [-2.31, 0.70],
                             "min30_confirm_residual": 0.0258, "min30_confirm_ci95": [0.0108, 0.0407],
                             "verdict": "SUPPORTED as likelihood; NOT profitable blind"}),
    )
}


# ----------------------------------------------------------------------------- identity + storage


_SUFFIX_RE = re.compile(r"\b(jr|sr|ii|iii|iv|v)\b")


def norm_player(name: Any) -> str:
    """Join key for a player across sources ("Luka Dončić" == "luka doncic", "Jaren Jackson Jr." == "jaren jackson")."""
    text = unicodedata.normalize("NFKD", str(name or "")).encode("ascii", "ignore").decode("ascii").lower()
    text = re.sub(r"[.'`]", "", text)
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    text = _SUFFIX_RE.sub(" ", text)
    return " ".join(text.split())


def signal_table_path(data_root: Path | str, sport: str, season: str, day: str) -> Path:
    return Path(data_root) / f"{sport}_source" / "signals" / season / f"{day}.jsonl"


def write_signal_table(data_root: Path | str, sport: str, season: str, day: str, rows: Iterable[Mapping[str, Any]]) -> Path:
    """Replace one date's table atomically (a re-run recomputes the same as-of values)."""
    path = signal_table_path(data_root, sport, season, day)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
    os.replace(tmp, path)
    return path


def read_signal_table(data_root: Path | str, sport: str, season: str, day: str) -> list[dict[str, Any]]:
    path = signal_table_path(data_root, sport, season, day)
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


# ----------------------------------------------------------------------------- point-in-time features


def minutes_features(prior_minutes: Sequence[float]) -> dict[str, Any]:
    """From a player's minutes in games BEFORE this one (oldest -> newest)."""
    out: dict[str, Any] = {"games_prior": len(prior_minutes)}
    last10 = list(prior_minutes[-10:])
    out["min_prior10"] = round(statistics.fmean(last10), 3) if last10 else None
    if len(prior_minutes) >= 13:
        recent = statistics.fmean(prior_minutes[-3:])
        base = statistics.fmean(prior_minutes[-13:-3])
        out["min_trend"] = round(recent - base, 3)
    else:
        out["min_trend"] = None
    return out


def start_features(prior_starts: Sequence[int | bool | None]) -> dict[str, Any]:
    """From start flags of games BEFORE this one (oldest -> newest); None = unknown."""
    known = [s for s in prior_starts if s is not None]
    if len(known) < 11 or prior_starts[-1] is None:
        return {"started_last": None, "starts_prior10_before_last": None}
    return {"started_last": bool(prior_starts[-1]),
            "starts_prior10_before_last": int(sum(1 for s in prior_starts[-11:-1] if s))}


def team_rest_days(game_dates: Sequence[date], day: date) -> int | None:
    """Days since the team's previous game before `day` (1 = back-to-back), None if none."""
    prior = [d for d in game_dates if d < day]
    if not prior:
        return None
    return (day - max(prior)).days


# ----------------------------------------------------------------------------- lift statistics


def residual_stats(rows: Sequence[Mapping[str, Any]], *, B: int = 1000, seed: int = 20261013,
                   cluster: str = "game") -> dict[str, Any]:
    """Mean residual (y - p) with a 95% CI bootstrapped over `cluster`; also hit rate and mean market probability."""
    if not rows:
        return {"n": 0}
    groups: dict[Any, list[Mapping[str, Any]]] = defaultdict(list)
    for r in rows:
        groups[r[cluster]].append(r)
    keys = list(groups)

    def mean_res(sample: Sequence[Mapping[str, Any]]) -> float:
        return sum(r["y"] - r["p"] for r in sample) / len(sample)

    rng = random.Random(seed)
    boots = []
    if len(keys) >= 5:
        for _ in range(B):
            sample = [r for _ in keys for r in groups[rng.choice(keys)]]
            boots.append(mean_res(sample))
        boots.sort()
    point = mean_res(rows)
    # one-sided p-value that the true mean residual is <= 0 (share of bootstrap means <= 0)
    p_value = (sum(1 for b in boots if b <= 0) + 1) / (len(boots) + 1) if boots else None
    return {
        "n": len(rows), "games": len(keys),
        "hit_rate": round(sum(r["y"] for r in rows) / len(rows), 4),
        "mean_p": round(sum(r["p"] for r in rows) / len(rows), 4),
        "residual": round(point, 4),
        "ci95": [round(boots[int(0.025 * len(boots))], 4), round(boots[int(0.975 * len(boots)) - 1], 4)] if boots else None,
        "p_one_sided": None if p_value is None else round(p_value, 4),
    }


def bh_adjust(p_values: Mapping[str, float | None], q: float = 0.10) -> dict[str, bool]:
    """Benjamini-Hochberg: which hypotheses survive at false-discovery rate q."""
    items = sorted(((k, v) for k, v in p_values.items() if v is not None), key=lambda kv: kv[1])
    m = len(items)
    cutoff = 0
    for i, (_, p) in enumerate(items, start=1):
        if p <= q * i / m:
            cutoff = i
    keep = {k for k, _ in items[:cutoff]}
    return {k: (k in keep) for k in p_values}


# ----------------------------------------------------------------------------- firing rules (exactly as registered)


def nba_signal_fires(features: Mapping[str, Any]) -> list[str]:
    """The registry rules, applied to one player-game's as-of features. Unknown inputs never fire a signal."""
    fired: list[str] = []
    trend = features.get("min_trend")
    min10 = features.get("min_prior10")
    if trend is not None:
        if trend >= 4.0:
            fired.append("nba.minutes_trend_up")
        if trend <= -4.0:
            fired.append("nba.minutes_trend_down")
    if features.get("started_last") is True and features.get("starts_prior10_before_last") is not None \
            and features["starts_prior10_before_last"] <= 3:
        fired.append("nba.start_promotion")
    if features.get("rest_days") == 1 and min10 is not None and min10 >= 28:
        fired.append("nba.b2b")
    spread = features.get("spread_abs")
    if spread is not None and spread >= 10 and min10 is not None and min10 >= 30:
        fired.append("nba.blowout_risk")
    return fired


# ----------------------------------------------------------------------------- likelihood (SHADOW on the board)
#
# `[2026-10-13, user "yes go ahead with all three"]`, lane `signal-engine-nba`. A SUPPORTED signal adjusts the
# board's LIKELIHOOD -- the probability the bet wins -- and nothing else: the score, Suggested and the portfolio still
# read the market's Shin fair. The board stamps `likelihood` beside the fair so the two can be graded on the same
# rows (recorder `lk` / `lke`) before any consumer is switched to it.
#
# nba.under_bias delta: the pooled H6 residual over both windows, (81,395 x 1.01% + 46,262 x 1.61%) / 127,657
# = 1.23 probability points (findings_2026-10-13_nba_signals_v1.md). `SYNDICATE_NBA_UNDER_BIAS_DELTA` overrides it;
# 0 switches the adjustment off; an unparseable or negative value falls back to the measured default.
NBA_UNDER_BIAS_DELTA = 0.0123


def nba_under_bias_delta() -> float:
    raw = str(os.environ.get("SYNDICATE_NBA_UNDER_BIAS_DELTA") or "").strip()
    if raw:
        try:
            value = float(raw)
        except ValueError:
            return NBA_UNDER_BIAS_DELTA
        if value == value and 0.0 <= value <= 0.10:
            return value
    return NBA_UNDER_BIAS_DELTA


def likelihood_adjustments(row: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Probability-point adjustments the SUPPORTED signals make to this row's side, by name."""
    adjustments: list[dict[str, Any]] = []
    sport = str(row.get("sport") or "").strip().lower()
    side = str(row.get("side") or "").strip().lower()
    market = str(row.get("market") or "").strip().lower()
    if sport == "nba" and str(row.get("kind") or "") == "prop" and side in ("over", "under") \
            and market in REGISTRY["nba.under_bias"].markets:
        delta = nba_under_bias_delta()
        if delta:
            adjustments.append({"signal": "nba.under_bias", "delta": round(delta if side == "under" else -delta, 5)})
    return adjustments
