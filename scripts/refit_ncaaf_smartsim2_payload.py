"""Re-fit gate: does the feature payload improve NCAAF margins AGAINST THE MARKET?

--------------------------------------------------------------------------
WHY THIS EXISTS AND WHAT IT DECIDES
--------------------------------------------------------------------------

`feature_payload.py` fills four blocks `drive_priors.py` reads, and it is
DEFAULT OFF because `state.md` says: *"DO NOT JUST WIRE IT. Both calibration
profiles were fit against a payload the engine cannot read, so this is a
mechanism added to a calibrated engine and owes a re-fit"* -- measured
elsewhere as a **negative interaction in 4 of 4 markets**.

This is that re-fit's evidence. It is the ONLY thing that should decide whether
the flag flips on.

--------------------------------------------------------------------------
THE BENCHMARK IS THE MARKET, NOT THE MODEL'S OWN PAST
--------------------------------------------------------------------------

`/api/board/book-grid?sport=ncaaf` already serves this model's verdict:

    margins  model MAE 15.775  vs  market MAE 12.212   n=2233  t=+17.20
             "loses to the closing line by 3.56 points of margin MAE"

So "payload ON is better than payload OFF" is NOT the question. The question is
whether ON closes any of that 3.56-point gap. A change that improves the model
against itself while still losing to the close has not earned a deploy.

--------------------------------------------------------------------------
NO LEAKAGE, AND THE RATING SOURCE IS THE TRAP
--------------------------------------------------------------------------

`state.md`: `/ppa/teams?year=S` is a SEASON AGGREGATE that contains the game
being predicted, and reading it inflated apparent skill 30% (r 0.663 vs 0.509
as-of, 558 games). Ratings here come from the PRIOR season only.

The payload's own blocks are season-scoped snapshots (returning production,
coach continuity, transfers) which describe the roster BEFORE the season is
played, so they are as-of by construction rather than by filtering.

Usage:
    python scripts/refit_ncaaf_smartsim2_payload.py --season 2025 --sims 200
"""
from __future__ import annotations

import argparse
import glob
import json
import statistics
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _load_market(season: int, lines_dir: Path | None = None) -> dict[tuple[str, str], dict[str, Any]]:
    """(home, away) -> consensus spread/total from the CFBD lines files.

    `spread` is CFBD's HOME-relative line: negative when the home side is
    favoured. It is converted to a home MARGIN here (negated) because the
    model emits a margin, and `state.md` records a whole NFL analysis lost to
    exactly this sign -- `spread_line` used un-negated produced plausible
    numbers pointing at the wrong team.
    """
    out: dict[tuple[str, str], dict[str, Any]] = {}
    # `--lines-dir` because these files are UNTRACKED. Measured 2026-08-27:
    # 21 `cfbd_lines_*.json` exist in the primary working tree and `git
    # ls-files` returns 0 for them -- so they are on one developer machine, not
    # in git and therefore not on Render. A refit that silently found nothing
    # would report "no games joined" and read as a code fault.
    base = Path(lines_dir) if lines_dir else (REPO_ROOT / "data" / "ncaaf_source" / "data")
    for path in sorted(glob.glob(str(base / "cfbd_lines_*.json"))):
        try:
            payload = json.load(open(path, encoding="utf-8"))
        except Exception:
            continue
        rows = payload if isinstance(payload, list) else payload.get("data") or []
        for row in rows:
            if int(row.get("season") or 0) != int(season):
                continue
            home, away = str(row.get("homeTeam") or ""), str(row.get("awayTeam") or "")
            spreads = [l.get("spread") for l in (row.get("lines") or []) if l.get("spread") is not None]
            if not (home and away and spreads):
                continue
            out[(home, away)] = {
                "market_margin": -statistics.mean(float(s) for s in spreads),
                "home_points": row.get("homeScore"),
                "away_points": row.get("awayScore"),
                "books": len(spreads),
            }
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Re-fit gate: payload OFF vs ON, benchmarked against the market.")
    parser.add_argument("--season", type=int, default=2025)
    parser.add_argument("--sims", type=int, default=200)
    parser.add_argument("--limit", type=int, default=0, help="Cap games, for a fast smoke run.")
    parser.add_argument("--snapshot-root", type=Path, default=None,
                        help="Alternate processed/ dir for the payload snapshots. REQUIRED for any "
                             "season other than the one the board carries: the coach/transfer/"
                             "returning builders REPLACE rather than merge, so rebuilding in place "
                             "destroys the live board's rows.")
    parser.add_argument("--lines-dir", type=Path, default=None,
                        help="Where cfbd_lines_*.json live. They are UNTRACKED; on a fresh "
                             "checkout or on Render there are none.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        from dotenv import load_dotenv
        load_dotenv()
    except Exception:
        pass

    from syndicate.features.football.sim_engine.smartsim2.historical_truth.ncaaf_historical_loader import (
        load_games_season,
    )
    from syndicate.features.ncaaf import feature_payload

    market = _load_market(args.season, args.lines_dir)
    games = [
        g for g in load_games_season(args.season)
        if g.get("homeClassification") == "fbs" and g.get("awayClassification") == "fbs"
        and g.get("homePoints") is not None
        and (str(g.get("homeTeam") or ""), str(g.get("awayTeam") or "")) in market
    ]
    if args.limit:
        games = games[: args.limit]
    if not games:
        print(f"ERROR: no {args.season} FBS games joined to a market line.")
        print(f"       market keys loaded: {len(market)}  (0 usually means --lines-dir is wrong;")
        print(f"       cfbd_lines_*.json are untracked and absent from a fresh checkout)")
        return 3

    if args.snapshot_root:
        feature_payload.set_snapshot_root(args.snapshot_root)
    feature_payload.reset_caches()

    # PER-BLOCK COVERAGE, NOT "ANY BLOCK". The first version of this counted a
    # payload as covered if it was non-empty, and reported **714 (100.0%)**
    # while `returning_production` and `coach_continuity` -- the two blocks
    # that actually move the drive priors -- were absent for EVERY game. The
    # only block present was `roster_depth`, because the roster file is the one
    # snapshot that carries 2025 rows.
    #
    # A coverage number that aggregates across blocks cannot distinguish "the
    # payload is complete" from "one incidental block built", and it reported
    # the wrong one at full confidence.
    block_counts: dict[str, int] = {}
    built = 0
    for g in games:
        payload = feature_payload.build_payload(
            home_team=str(g.get("homeTeam")), away_team=str(g.get("awayTeam")), season=args.season
        )
        if payload:
            built += 1
        for block in payload:
            if block != "adapter_metadata":
                block_counts[block] = block_counts.get(block, 0) + 1

    actual, mkt = [], []
    for g in games:
        key = (str(g.get("homeTeam")), str(g.get("awayTeam")))
        actual.append(float(g["homePoints"]) - float(g["awayPoints"]))
        mkt.append(market[key]["market_margin"])

    market_mae = statistics.mean(abs(m - a) for m, a in zip(mkt, actual))

    # ---------------------------------------------------------------- the arms
    #
    # PRIOR-SEASON RATINGS, and this is the leakage trap `state.md` names:
    # `/ppa/teams?year=S` is a SEASON AGGREGATE containing the game being
    # predicted, and reading it inflated apparent skill 30% (r 0.663 vs 0.509
    # as-of, 558 games). SP+ for season S-1 is as-of by construction.
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "_gen", REPO_ROOT / "scripts" / "generate_smartsim2_ncaaf_projections.py"
    )
    gen = importlib.util.module_from_spec(spec)
    sys.modules["_gen"] = gen
    spec.loader.exec_module(gen)

    from syndicate.features.football.sim_engine.smartsim2.contracts import SmartSim2SimulationInput
    from syndicate.features.football.sim_engine.smartsim2.game_simulator import simulate_game

    sp_index = gen.load_sp_ratings(int(args.season) - 1)
    sp_means = gen.sp_league_means(sp_index)
    profile = gen.NCAAF_CALIBRATION_PROFILE

    def _margin(game: dict[str, Any], payload: dict[str, Any] | None) -> float | None:
        home, away = str(game.get("homeTeam")), str(game.get("awayTeam"))
        # NO BROAD EXCEPT HERE. The first version wrapped this in
        # `except Exception: return None` and called the result "no rating" --
        # while what actually happened was a TypeError from calling
        # `sp_offense_defense_rating` with 2 args instead of 3. All 25 games in
        # the smoke run reported "skipped: no rating", which is a data-shaped
        # answer to a code-shaped fault. An unmatched team is a legitimate None
        # from the function itself; a wrong call must crash.
        home_sp = gen.sp_offense_defense_rating(home, sp_index, sp_means)
        away_sp = gen.sp_offense_defense_rating(away, sp_index, sp_means)
        if home_sp is None or away_sp is None:
            return None
        h_off, h_def = home_sp
        a_off, a_def = away_sp
        margins: list[float] = []
        for i in range(args.sims):
            kwargs: dict[str, Any] = dict(
                home_team=home, away_team=away, seed=1337 + i,
                home_offense_rating=h_off, home_defense_rating=h_def,
                away_offense_rating=a_off, away_defense_rating=a_def,
            )
            if payload:
                kwargs["feature_generation_payload"] = payload
            out = simulate_game(SmartSim2SimulationInput(**kwargs), profile=profile)
            margins.append(float(out.final_score["home"]) - float(out.final_score["away"]))
        return statistics.mean(margins)

    off_err: list[float] = []
    on_err: list[float] = []
    mkt_err: list[float] = []
    skipped = 0
    for game, act in zip(games, actual):
        payload = feature_payload.build_payload(
            home_team=str(game.get("homeTeam")), away_team=str(game.get("awayTeam")), season=args.season
        )
        m_off = _margin(game, None)
        m_on = _margin(game, payload) if payload else None
        if m_off is None or m_on is None:
            skipped += 1
            continue
        key = (str(game.get("homeTeam")), str(game.get("awayTeam")))
        off_err.append(abs(m_off - act))
        on_err.append(abs(m_on - act))
        # PAIRED: the market error is recomputed on the SAME subset the arms
        # ran on, not taken from the full 714. An unpaired comparison against a
        # different denominator is how a model gets credited for games it never
        # simulated.
        mkt_err.append(abs(market[key]["market_margin"] - act))

    paired = len(off_err)
    result_arms = {
        "paired_games": paired,
        "skipped_no_rating_or_payload": skipped,
        "model_mae_payload_off": round(statistics.mean(off_err), 3) if off_err else None,
        "model_mae_payload_on": round(statistics.mean(on_err), 3) if on_err else None,
        "market_mae_same_subset": round(statistics.mean(mkt_err), 3) if mkt_err else None,
    }
    if off_err:
        result_arms["delta_on_minus_off"] = round(result_arms["model_mae_payload_on"] - result_arms["model_mae_payload_off"], 3)
        result_arms["gap_to_market_off"] = round(result_arms["model_mae_payload_off"] - result_arms["market_mae_same_subset"], 3)
        result_arms["gap_to_market_on"] = round(result_arms["model_mae_payload_on"] - result_arms["market_mae_same_subset"], 3)

    result = {
        "season": args.season,
        "games_joined": len(games),
        "payload_any_block": built,
        "payload_blocks": {
            b: {"games": n, "pct": round(100.0 * n / len(games), 1)}
            for b, n in sorted(block_counts.items())
        },
        # The blocks that actually move the priors. Reported separately because
        # they are the ones a re-fit depends on, and an aggregate hides them.
        "payload_priors_moving_pct": round(
            100.0 * min(
                block_counts.get("returning_production", 0),
                block_counts.get("coach_continuity", 0),
            ) / len(games), 1
        ),
        "market_mae": round(market_mae, 3),
        "market_margin_sd": round(statistics.pstdev(mkt), 3),
        "actual_margin_sd": round(statistics.pstdev(actual), 3),
        **result_arms,
    }

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"NCAAF re-fit gate -- season {args.season}")
        print(f"  FBS games joined to a market line : {result['games_joined']:,}")
        print(f"  payload builds (ANY block)        : {built:,}")
        for b, s in result["payload_blocks"].items():
            print(f"      {b:24s} {s['games']:>5,} ({s['pct']}%)")
        print(f"  blocks that MOVE the priors       : {result['payload_priors_moving_pct']}%")
        print("      (returning_production AND coach_continuity -- an aggregate")
        print("       'any block' figure reported 100% while both were absent)")
        print(f"  MARKET margin MAE (the bar)       : {result['market_mae']}")
        print(f"  market margin SD                  : {result['market_margin_sd']}")
        print(f"  actual margin SD                  : {result['actual_margin_sd']}")
        print()
        print(f"  ARMS -- paired on {result['paired_games']:,} games "
              f"({result['skipped_no_rating_or_payload']} skipped: no rating or no payload)")
        print(f"    model MAE payload OFF : {result.get('model_mae_payload_off')}")
        print(f"    model MAE payload ON  : {result.get('model_mae_payload_on')}")
        print(f"    market MAE, same games: {result.get('market_mae_same_subset')}")
        print(f"    delta ON - OFF        : {result.get('delta_on_minus_off')}  (negative = payload helps)")
        print(f"    gap to market OFF     : {result.get('gap_to_market_off')}")
        print(f"    gap to market ON      : {result.get('gap_to_market_on')}  (must reach <= 0 to earn a deploy)")
        print()
        print("  The bar is the MARKET, not payload-off. `state.md` records this")
        print("  model at margin MAE 15.775 vs market 12.212 (n=2233, t=+17.20).")
        print("  A payload that improves the model against itself and still loses")
        print("  to the close has not earned a deploy.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
