"""Understat outage, players half: does an ESPN re-source of big-5 player rates beat frozen Understat rates?

Lane `understat-fallback-backtest` (2026-11-18), H6 (pre-registered in `.syndicate/lanes.md` `13d4bb9f2`).
Research only: reads copies of the fleet's `players_*.csv` (Understat) and `history/player_match_log_*.csv`
(ESPN match summaries, one dated row per player per league match), writes JSON to `--out`.

THE RATE ESTIMATOR, NOT THE PROP ENGINE. Each appeared player-match is priced with the player's per-90
rate times his ACTUAL minutes (`lam = rate * minutes / 90`, Poisson): P(goal >= 1) from `xg_per90`,
P(shots >= 1) / P(shots >= 2) from `shots_per90`, P(assist >= 1) from `xa_per90`. Conditioning on the
minutes he played isolates what a re-source changes (the per-90 rate) from what it does not (expected
minutes, the team's volume, which come from the team ratings measured by the staleness backtest).

SOURCES, each shaped the way production shapes it:
- U (Understat): the stored rows -- already shrunk toward a (league, position) prior at ingestion
  (`player_history._shrink_toward_prior`, 180-minute stabilizer); `xg_per90` is model xG.
- E (ESPN, the in-repo fallback): season rows aggregated from the match log exactly as
  `espn_player_stats.aggregate_season_player_stats` does (true per-90 over real minutes, >= 3
  appearances, `xg_per90` = REALISED goals per 90), then production's load-time
  `build_soccer_artifacts._shrink_espn_goal_rates` (xg/xa only; shots unshrunk, as production).
- Across seasons, production keeps ONE row per player: the row with the most minutes
  (`_load_player_rows`), so a frozen current-season file only matters for players whose current-season
  minutes already exceed their previous-season minutes.

PARTS:
- P1 (source at equal data, leak-free, large n): 2025-26 rows of each source predict 2026-27 appearances
  (08-15..11-08). Paired on appearances where both sources have a 2025-26 row for the player.
- P2 (the actual decision, 11-01..11-08, the 69 outage matches): production-dedup rows for U FROZEN
  (2024/2025/2026 files as on the fleet, 2026 frozen at 10-31) vs E CURRENT (logs dated before each match
  day) vs E FROZEN (logs before 11-01), paired on appearances all three can price.
- P3 (squad exposure): share of 11-01..11-08 shots / goals taken by players whose production row is the
  frozen 2026 Understat row, by players with NO Understat row at all, and by players whose only rows are
  2024/2025 (they reach a squad only through the ESPN-roster rescue).
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from scripts.build_soccer_artifacts import _shrink_espn_goal_rates  # noqa: E402
from syndicate.features.soccer.features.lineups import _norm_player_name  # noqa: E402
from syndicate.features.soccer.features.team_names import match_team_name  # noqa: E402

LEAGUES = ("epl", "la_liga", "bundesliga", "serie_a", "ligue_1")
NOW_FROM, NOW_TO = "2026-11-01", "2026-11-08"


def espn_season_rows(log: pd.DataFrame, league: str, before: str | None = None) -> list[dict[str, Any]]:
    """`aggregate_season_player_stats` over a match-log frame (one season), optionally only days < `before`."""
    if before is not None:
        log = log[log["date"] < before]
    team_matches = log.groupby("team")["event_id"].nunique().to_dict()
    out = []
    for pid, g in log.sort_values("date").groupby("player_id"):
        if len(g) < 3:
            continue
        minutes = float(g["minutes"].sum())
        nineties = minutes / 90.0 if minutes > 0 else 0.0
        team = g["team"].iloc[-1]
        tm = team_matches.get(team, len(g))
        out.append({
            "league": league, "player_id": str(pid), "player_name": g["player_name"].iloc[-1], "team": team,
            "position": g["position"].iloc[0], "is_goalkeeper": "goalkeeper" in str(g["position"].iloc[0]).lower(),
            "appearances": len(g), "minutes_played": round(minutes, 1),
            "shots_per90": round(g["shots"].sum() / nineties, 4) if nineties else 0.0,
            "xg_per90": round(g["goals"].sum() / nineties, 4) if nineties else 0.0,
            "xa_per90": round(g["assists"].sum() / nineties, 4) if nineties else 0.0,
            "expected_minutes_share": round(min(1.0, minutes / (tm * 90.0)), 4) if tm else None,
            "source": "espn_true_per90",
        })
    return out


def dedup_max_minutes(season_rows: list[list[dict[str, Any]]], minutes_key: str, season_tags: list[int]) -> dict[str, dict]:
    """Production's rule: one row per player_id, the one with the most minutes (ties -> the later season)."""
    best: dict[str, dict] = {}
    for rows, tag in zip(season_rows, season_tags):
        for r in rows:
            pid = str(r["player_id"])
            m = float(r.get(minutes_key) or 0.0)
            if pid not in best or m >= float(best[pid].get(minutes_key) or 0.0):
                best[pid] = dict(r, _season=tag)
    return best


def shrink_espn(rows: dict[str, dict]) -> dict[str, dict]:
    vals = list(rows.values())
    _shrink_espn_goal_rates(vals)  # mutates in place, production's load-time shrink
    return rows


class UnderstatIndex:
    """ESPN (name, team) -> Understat player row, by accent-folded name within the league."""

    def __init__(self, rows: dict[str, dict], espn_teams: list[str]):
        self.by_name: dict[str, list[dict]] = defaultdict(list)
        us_teams = set()
        for r in rows.values():
            self.by_name[_norm_player_name(r["player_name"])].append(r)
            us_teams.update(t.strip() for t in str(r.get("team") or "").split(","))
        self.team_map = {t: match_team_name(t, sorted(us_teams)) for t in espn_teams}
        self._club_rows: dict[str, list[dict]] = {}

    def _club(self, row: dict) -> list[str]:
        return [t.strip() for t in str(row.get("team") or "").split(",")]

    def find(self, name: str, espn_team: str) -> dict | None:
        """Exact folded name (unique, or unique at the club); else, AT THE CLUB, a unique candidate whose
        folded tokens contain the other's ("Gabriel" / "Gabriel Magalhaes", "Alisson" / "Alisson Becker")
        or whose surname matches with a SequenceMatcher ratio >= 0.8 ("Konsa" / "Ezri Konsa Ngoyo")."""
        from difflib import SequenceMatcher

        key = _norm_player_name(name)
        us_team = self.team_map.get(espn_team)
        cands = self.by_name.get(key) or []
        if len(cands) == 1:
            return cands[0]
        hits = [c for c in cands if us_team and us_team in self._club(c)]
        if len(hits) == 1:
            return hits[0]
        if not us_team:
            return None
        club_rows = self._club_rows.get(us_team)
        if club_rows is None:
            club_rows = [r for rows in self.by_name.values() for r in rows if us_team in self._club(r)]
            self._club_rows[us_team] = club_rows
        toks = set(key.split())
        fuzzy = []
        for r in club_rows:
            other = _norm_player_name(r["player_name"])
            otoks = set(other.split())
            if toks and otoks and (toks <= otoks or otoks <= toks):
                fuzzy.append(r)
            elif key.split()[-1:] and other.split()[-1:] and SequenceMatcher(None, key.split()[-1], other.split()[-1]).ratio() >= 0.8                     and SequenceMatcher(None, key, other).ratio() >= 0.6:
                fuzzy.append(r)
        return fuzzy[0] if len(fuzzy) == 1 else None


def _p_at_least(lam: float, k: int) -> float:
    lam = max(lam, 1e-9)
    if k == 1:
        return 1.0 - math.exp(-lam)
    return 1.0 - math.exp(-lam) * (1.0 + lam)


def _ll(p: float, hit: bool) -> float:
    p = min(max(p, 1e-9), 1 - 1e-9)
    return -math.log(p if hit else 1.0 - p)


MARKETS = {
    "goal1": ("xg_per90", "goals", 1),
    "shots1": ("shots_per90", "shots", 1),
    "shots2": ("shots_per90", "shots", 2),
    "assist1": ("xa_per90", "assists", 1),
}


def price(row: dict, minutes: float) -> dict[str, float]:
    return {m: _p_at_least(float(row.get(field) or 0.0) * minutes / 90.0, k) for m, (field, _, k) in MARKETS.items()}


def cluster_boot(values: dict[str, list[float]], n: int = 2000, seed: int = 1118) -> tuple[float, float, float, int]:
    """Mean per appearance, CI by resampling MATCHES (appearances in one match are not independent)."""
    keys = list(values)
    sums = np.array([sum(values[k]) for k in keys])
    counts = np.array([len(values[k]) for k in keys])
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(keys), size=(n, len(keys)))
    means = sums[idx].sum(axis=1) / counts[idx].sum(axis=1)
    return float(sums.sum() / counts.sum()), float(np.quantile(means, 0.025)), float(np.quantile(means, 0.975)), int(counts.sum())


def compare(apps: list[dict], a: str, b: str) -> dict[str, Any]:
    out = {}
    for m, (_, stat, k) in MARKETS.items():
        per_match: dict[str, list[float]] = defaultdict(list)
        lla, llb, pa, pb, hits = [], [], [], [], []
        for x in apps:
            hit = float(x[stat]) >= k
            la, lb = _ll(x[a][m], hit), _ll(x[b][m], hit)
            per_match[str(x["event_id"])].append(lb - la)
            lla.append(la); llb.append(lb); pa.append(x[a][m]); pb.append(x[b][m]); hits.append(hit)
        mean, lo, hi, n = cluster_boot(per_match)
        out[m] = {"n": n, "matches": len(per_match), f"ll_{a}": round(float(np.mean(lla)), 5), f"ll_{b}": round(float(np.mean(llb)), 5),
                  f"d_ll_{b}_minus_{a}": [round(mean, 5), round(lo, 5), round(hi, 5)],
                  f"mean_p_{a}": round(float(np.mean(pa)), 4), f"mean_p_{b}": round(float(np.mean(pb)), 4),
                  "actual_rate": round(float(np.mean(hits)), 4)}
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", type=Path, default=Path(r"C:\tmp\ustale_1118\fleet_src"))
    ap.add_argument("--out", type=Path, default=Path(r"C:\tmp\ustale_1118\players\summary.json"))
    args = ap.parse_args()
    try:
        import psutil
        psutil.Process().nice(psutil.IDLE_PRIORITY_CLASS)
    except Exception:  # noqa: BLE001
        pass

    p1_apps: list[dict] = []
    p2_apps: list[dict] = []
    p3: dict[str, Any] = {}
    join_audit: dict[str, Any] = {}
    for league in LEAGUES:
        base = args.src / league
        logs = {s: pd.read_csv(base / "history" / f"player_match_log_{s}.csv") for s in (2024, 2025, 2026)}
        us = {s: pd.read_csv(base / "players" / f"players_{s}.csv").to_dict("records") for s in (2024, 2025, 2026)}
        espn_teams = sorted(set(logs[2026]["team"]) | set(logs[2025]["team"]))

        # ---- P1: 2025-26 rows -> 2026-27 appearances (08-15..11-08), outfield only.
        u25 = {str(r["player_id"]): r for r in us[2025]}
        e25 = shrink_espn({r["player_id"]: r for r in espn_season_rows(logs[2025], league)})
        u_index = UnderstatIndex(u25, espn_teams)
        apps26 = logs[2026][(logs[2026]["minutes"] > 0) & (~logs[2026]["position"].astype(str).str.contains("Goalkeeper"))]
        joined = 0
        for x in apps26.to_dict("records"):
            er = e25.get(str(x["player_id"]))
            ur = u_index.find(x["player_name"], x["team"])
            if er is None or ur is None:
                continue
            joined += 1
            p1_apps.append({"league": league, "event_id": x["event_id"], "date": x["date"], "goals": x["goals"], "shots": x["shots"],
                            "assists": x["assists"], "U": price(ur, x["minutes"]), "E": price(er, x["minutes"])})
        join_audit[league] = {"p1_appearances": int(len(apps26)), "p1_paired": joined,
                              "team_map_misses": [t for t, v in u_index.team_map.items() if v is None]}

        # ---- P2: production-dedup rows on the 69 outage matches.
        uf = dedup_max_minutes([us[2024], us[2025], us[2026]], "minutes", [2024, 2025, 2026])
        uf_index = UnderstatIndex(uf, espn_teams)
        e_prev = [espn_season_rows(logs[2024], league), espn_season_rows(logs[2025], league)]
        ef = shrink_espn(dedup_max_minutes(e_prev + [espn_season_rows(logs[2026], league, before=NOW_FROM)],
                                           "minutes_played", [2024, 2025, 2026]))
        now = logs[2026][(logs[2026]["date"] >= NOW_FROM) & (logs[2026]["date"] <= NOW_TO) & (logs[2026]["minutes"] > 0)]
        ec_by_day = {d: shrink_espn(dedup_max_minutes(e_prev + [espn_season_rows(logs[2026], league, before=d)],
                                                      "minutes_played", [2024, 2025, 2026]))
                     for d in sorted(now["date"].unique())}
        tally = defaultdict(float)
        for x in now.to_dict("records"):
            outfield = "goalkeeper" not in str(x["position"]).lower()
            ur = uf_index.find(x["player_name"], x["team"])
            # P3 exposure (shots and goals weights), every appeared player incl. those with no row.
            if ur is None:
                cls = "no_understat_row"
            elif int(ur["_season"]) == 2026:
                cls = "row_is_frozen_2026"
            elif not any(str(r["player_id"]) == str(ur["player_id"]) for r in us[2026]):
                cls = "prior_season_only_row"
            else:
                cls = "row_is_prior_season_has_2026_row"
            for stat in ("shots", "goals"):
                tally[f"{stat}:{cls}"] += float(x[stat])
                tally[f"{stat}:all"] += float(x[stat])
            tally[f"apps:{cls}"] += 1
            tally["apps:all"] += 1
            ec = ec_by_day[x["date"]].get(str(x["player_id"]))
            er = ef.get(str(x["player_id"]))
            if not outfield or ur is None or ec is None or er is None:
                continue
            p2_apps.append({"league": league, "event_id": x["event_id"], "date": x["date"], "goals": x["goals"], "shots": x["shots"],
                            "assists": x["assists"], "UF": price(ur, x["minutes"]), "EC": price(ec, x["minutes"]),
                            "EF": price(er, x["minutes"]),
                            "ec_row_2026": int(ec["_season"]) == 2026, "uf_row_2026": int(ur["_season"]) == 2026})
        p3[league] = dict(tally)

    pooled_p3 = defaultdict(float)
    for t in p3.values():
        for k, v in t.items():
            pooled_p3[k] += v
    summary = {
        "P1_source_at_equal_data_2025_26_rows_predict_2026_27": compare(p1_apps, "U", "E"),
        "P1_dates": [min(x["date"] for x in p1_apps), max(x["date"] for x in p1_apps)],
        "P2_outage_matches_frozen_U_vs_current_E": compare(p2_apps, "UF", "EC"),
        "P2_freshness_within_espn_EF_vs_EC": compare(p2_apps, "EF", "EC"),
        "P2_share_rows_from_2026": {"UF": round(float(np.mean([x["uf_row_2026"] for x in p2_apps])), 4),
                                    "EC": round(float(np.mean([x["ec_row_2026"] for x in p2_apps])), 4), "n": len(p2_apps)},
        "P3_exposure_pooled": dict(pooled_p3),
        "P3_by_league": p3,
        "join_audit": join_audit,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(summary, indent=1, default=str), encoding="utf-8")
    print(json.dumps(summary, indent=1, default=str)[:6000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
