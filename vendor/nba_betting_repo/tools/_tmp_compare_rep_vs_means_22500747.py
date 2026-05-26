from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import numpy as np

from nba_betting.config import paths
from nba_betting.player_priors import PlayerPriorsConfig, compute_player_priors
from nba_betting.sim.connected_game import simulate_connected_game
from nba_betting.sim.quarters import GameInputs, simulate_quarters

# Allow importing the evaluator module as a plain file.
TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))
import evaluate_connected_realism as e


def main() -> None:
    d = "2026-02-07"
    gid = "22500747"

    processed = paths.data_processed
    logs = pd.read_csv(processed / "player_logs.csv")

    preds = e._load_predictions(processed, e._parse_date(d))
    if preds is None or preds.empty:
        raise SystemExit("missing predictions")
    odds = e._load_game_odds(processed, e._parse_date(d))
    preds = e._fill_market_lines(preds, odds)

    games = e._games_from_player_logs_for_date(logs, e._parse_date(d))
    row = games.loc[games.game_id.astype(str) == gid].iloc[0]
    htri = row.home_tri
    atri = row.away_tri

    # Find matching prediction row
    pr = None
    for _, r in preds.iterrows():
        # preds uses full team names; normalize via to_tricode
        try:
            ht = e.to_tricode(str(r.get("home_team") or ""))
            at = e.to_tricode(str(r.get("visitor_team") or ""))
        except Exception:
            continue
        if ht == htri and at == atri:
            pr = r
            break
    if pr is None:
        raise SystemExit("could not match prediction row")

    home_ctx, away_ctx, market_total, market_home_spread = e._build_context_from_row(pr)
    inp = GameInputs(date=d, home=home_ctx, away=away_ctx, market_total=market_total, market_home_spread=market_home_spread)

    qsum = simulate_quarters(inp, n_samples=3500)

    props = e._load_props_predictions(processed, e._parse_date(d))
    if props is None:
        raise SystemExit("missing props_predictions")

    home_roster, away_roster = e._rosters_from_actual_logs(logs, gid, htri, atri)

    minutes_priors = e._build_minutes_priors(logs, end_date=e._parse_date(d), lookback_days=21)

    cfg = PlayerPriorsConfig(days_back=21, min_games=3, min_minutes_avg=4.0)
    player_priors = compute_player_priors(d, cfg=cfg)

    sim = simulate_connected_game(
        qsum.quarters,
        home_tri=htri,
        away_tri=atri,
        props_df=props,
        home_roster=home_roster,
        away_roster=away_roster,
        minutes_priors=minutes_priors,
        player_priors=player_priors,
        minutes_lookback_days=21,
        n_samples=1200,
        seed=1 + int(gid[-4:]),
        date_str=d,
    )

    rep = sim.get("rep") or {}
    means = sim.get("means") or {}

    def to_team_box(box: dict) -> pd.DataFrame:
        return e._sim_team_box(rep, box)  # type: ignore

    # Use evaluator helpers to compute metrics
    act_h = e._actual_team_box(logs, gid, htri)
    act_a = e._actual_team_box(logs, gid, atri)

    rep_h = e._sim_team_box(rep, "home_box")
    rep_a = e._sim_team_box(rep, "away_box")

    mean_h = e._sim_team_box(means, "home_box")
    mean_a = e._sim_team_box(means, "away_box")

    rep_home_m = e._match_and_score(act_h, rep_h, top_k=8)
    rep_away_m = e._match_and_score(act_a, rep_a, top_k=8)
    mean_home_m = e._match_and_score(act_h, mean_h, top_k=8)
    mean_away_m = e._match_and_score(act_a, mean_a, top_k=8)

    print("GAME", gid, d, atri, "@", htri)
    print("rep minutes mae", rep_home_m["min_mae_topk"], rep_away_m["min_mae_topk"])
    print("mean minutes mae", mean_home_m["min_mae_topk"], mean_away_m["min_mae_topk"])
    print("away_minutes_source", ((sim.get("diagnostics") or {}).get("away_minutes") or {}).get("minutes_source"))


if __name__ == "__main__":
    main()
