"""Amendment 3 of lane `football-sim-player-attribution`: which player-share estimator predicts carries and targets?

Pre-registered in `.syndicate/findings_2026-10-07_football_player_attribution.md` ("Amendment 3") before
this file. No sims: for every FIT team-game (nflverse 2023-24 REG, weeks 2+) each candidate predicts every
player's share of the team's CARRIES and TARGETS from plays strictly before the week, scored against what
happened by multinomial log-likelihood (an "other" bucket holds unlisted players, floored at 0.02).
Secondary: MAE of expected touches (share x the team's actual count) for the players QUOTED that game.

    py -3 scripts/football_attribution_shares.py
"""
from __future__ import annotations

import csv
import json
import math
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts.football_scenario_rates import idle_self  # noqa: E402
from scripts import backtest_football_attribution_props as B  # noqa: E402
from syndicate.features.football.sim_engine.smartsim2 import player_attribution as A  # noqa: E402

CANDIDATES = {
    "E0": dict(),
    "E1(H=2)": dict(half_life=2.0), "E1(H=4)": dict(half_life=4.0), "E1(H=8)": dict(half_life=8.0),
    "E2": dict(availability="last2_or_quoted"),
    "E3(H=2)": dict(half_life=2.0, availability="last2_or_quoted"),
    "E3(H=4)": dict(half_life=4.0, availability="last2_or_quoted"),
    "E3(H=8)": dict(half_life=8.0, availability="last2_or_quoted"),
}
OTHER_FLOOR = 0.02


def _season_rows(season: int) -> List[Dict[str, str]]:
    path = B.ROOT / "tracking" / "nflverse" / "pbp" / f"pbp_{season}.csv"
    with path.open(encoding="utf-8", newline="") as fh:
        return [{k: r.get(k, "") for k in B.USAGE_COLS} for r in csv.DictReader(fh) if r.get("season_type") == "REG"]


def main() -> None:
    idle_self()
    B.H.configure_env(B.ROOT)
    from syndicate.features.shared.team_aliases import canonical_team
    # who was quoted, per (game, team): the same production-resolved rows the backtest grades
    rows, _ = B.build_rows([2023, 2024])
    quoted: Dict[tuple, set] = defaultdict(set)
    for r in rows:
        quoted[(r["gid"], r["team"])].add(r["pid"])
    seasons = {s: _season_rows(s) for s in (2022, 2023, 2024)}
    ll = {c: {"carries": 0.0, "targets": 0.0, "n_carries": 0, "n_targets": 0} for c in CANDIDATES}
    mae = {c: {"carries": [], "targets": []} for c in CANDIDATES}
    n_tg = 0
    for season in (2023, 2024):
        rows_s = seasons[season]
        games = sorted({(int(r["week"]), r["game_id"]) for r in rows_s})
        for week, gid in games:
            if week < 2:
                continue
            game_rows = [r for r in rows_s if r["game_id"] == gid]
            cur = [r for r in rows_s if int(r["week"] or 0) < week]
            for team in sorted({r["posteam"] for r in game_rows if r["posteam"]}):
                carries: Dict[str, int] = defaultdict(int)
                targets: Dict[str, int] = defaultdict(int)
                for r in game_rows:
                    if r["posteam"] != team:
                        continue
                    if r["play_type"] == "run" and r["rusher_player_id"]:
                        carries[r["rusher_player_id"]] += 1
                    if r["play_type"] == "pass" and r["sack"] != "1" and r["receiver_player_id"]:
                        targets[r["receiver_player_id"]] += 1
                q = quoted.get((gid, canonical_team("nfl", team)), set())
                n_tg += 1
                for cname, kw in CANDIDATES.items():
                    u = A.build_team_usage(team, cur, seasons[season - 1], force_active=q, **kw)
                    for kind, actual, share_of in (("carries", carries, lambda p: p.carry_share),
                                                   ("targets", targets, lambda p: p.target_share)):
                        pred = {p.player_id: share_of(p) for p in u.players if share_of(p) > 0}
                        other = max(OTHER_FLOOR, 1.0 - sum(pred.values()))
                        total = sum(actual.values())
                        for pid, k in actual.items():
                            ll[cname][kind] += k * math.log(max(1e-6, pred.get(pid, other)))
                        ll[cname]["n_" + kind] += total
                        for pid in q:
                            mae[cname][kind].append(abs(pred.get(pid, 0.0) * total - actual.get(pid, 0)))
    print(f"FIT team-games scored: {n_tg} (2023-24 REG, weeks 2+)")
    print(f"{'candidate':10} {'LL/carry':>10} {'LL/target':>10} {'LL total':>12}   MAE quoted: carries / targets")
    out = {}
    for c, v in ll.items():
        tot = v["carries"] + v["targets"]
        mc = sum(mae[c]["carries"]) / max(1, len(mae[c]["carries"]))
        mt = sum(mae[c]["targets"]) / max(1, len(mae[c]["targets"]))
        out[c] = {"ll_per_carry": v["carries"] / v["n_carries"], "ll_per_target": v["targets"] / v["n_targets"],
                  "ll_total": tot, "mae_quoted_carries": mc, "mae_quoted_targets": mt}
        print(f"{c:10} {out[c]['ll_per_carry']:10.4f} {out[c]['ll_per_target']:10.4f} {tot:12.1f}   {mc:.3f} / {mt:.3f}")
    best = max(out, key=lambda c: out[c]["ll_total"])
    print(f"CHOSEN (max summed FIT log-likelihood): {best}")
    (B.OUT / "share_estimator_fit.json").write_text(json.dumps({"results": out, "chosen": best, "team_games": n_tg},
                                                               indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
