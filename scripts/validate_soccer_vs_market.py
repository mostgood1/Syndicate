"""Validate SoccerSim outputs against live market odds.

Three modes:

- ``h2h``: simulate a league's upcoming fixtures with ratings computed from
  ingested team xG history and compare model three-way probabilities with
  devigged consensus market probabilities.
- ``props``: simulate player props for the fixtures in a fetched props CSV
  (see fetch_soccer_oddsapi_props_local.py) and compare model probabilities
  with book prices (devigged where two-sided). ``--starter-mode
  top_minutes`` applies a heuristic depth-chart lineup (top-11 by season
  minutes share per team) instead of raw season-long usage -- not a real
  confirmed lineup, since no lineup-confirmation source is wired up.
- ``anchor``: non-circular validation of market-anchoring. Anchors ratings
  toward one bookmaker's line, then evaluates against the devigged
  consensus of every *other* bookmaker for the same fixture, so the anchor
  source and the evaluation target are independent.

Usage:
    python scripts/validate_soccer_vs_market.py h2h --league epl
    python scripts/validate_soccer_vs_market.py props --league mls --props-csv data/soccer_source/mls/props/2026-07-19.csv --starter-mode top_minutes
    python scripts/validate_soccer_vs_market.py anchor --league epl --weight 0.4
"""

from __future__ import annotations

import argparse
import math
import os
import sys
import unicodedata
from pathlib import Path
from typing import Any

import pandas as pd
import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.soccer.adapters import build_soccer_simulation_adapter
from syndicate.features.soccer.features.loaders import build_soccer_simulation_input
from syndicate.features.soccer.features.loaders import compute_team_ratings
from syndicate.features.soccer.features.market_anchoring import anchor_team_ratings
from syndicate.features.soccer.features.market_anchoring import devig_decimal_odds
from syndicate.features.soccer.features.loaders import team_rows_from_match_history
from syndicate.features.soccer.features.team_names import match_team_name
from syndicate.features.soccer.ingestion.player_history import fetch_asa_mls_team_history

# Leagues without Understat coverage (xG team history): rated from
# football-data.co.uk match results instead (goals stand in for xG -- see
# team_rows_from_match_history).
_GOALS_BASED_RATING_LEAGUES = {"eredivisie", "primeira_liga", "championship", "belgian_pro_league"}

LEAGUE_SPORT_KEYS = {
    "epl": "soccer_epl",
    "la_liga": "soccer_spain_la_liga",
    "bundesliga": "soccer_germany_bundesliga",
    "serie_a": "soccer_italy_serie_a",
    "ligue_1": "soccer_france_ligue_one",
    "mls": "soccer_usa_mls",
    "eredivisie": "soccer_netherlands_eredivisie",
    "primeira_liga": "soccer_portugal_primeira_liga",
    "championship": "soccer_efl_champ",
    "belgian_pro_league": "soccer_belgium_first_div",
}

# Rating prior for teams absent from the history window (promoted sides):
# roughly relegation-zone strength.
PROMOTED_TEAM_RATING = {"attack_rating": -0.18, "defense_rating": -0.18}


def _norm_player(name: str) -> str:
    text = unicodedata.normalize("NFKD", str(name or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(text.lower().replace(".", " ").replace("-", " ").split())


def _american_to_prob(price: Any) -> float | None:
    try:
        value = float(price)
    except Exception:
        return None
    if math.isnan(value):
        return None
    if value > 0:
        return 100.0 / (value + 100.0)
    return -value / (-value + 100.0)


def _load_team_ratings(league: str, as_of: str) -> dict[str, dict[str, float]]:
    """`as_of` is the fixture date (audit §7 #6).

    This mode simulates UPCOMING fixtures against current market odds, so it
    does not leak the way the backtest did -- the history is all in the past
    either way. It still passes a date because `compute_team_ratings` now
    REQUIRES one, and that requirement is what stops the forward-looking and
    backward-looking callers being confused for each other again.
    """
    if league == "mls":
        rows = fetch_asa_mls_team_history(2026)
        return compute_team_ratings(rows, as_of=as_of)
    if league in _GOALS_BASED_RATING_LEAGUES:
        history_dir = REPO_ROOT / "data" / "soccer_source" / league / "history"
        frames = [pd.read_csv(path) for path in sorted(history_dir.glob("matches_*.csv"))]
        if not frames:
            raise SystemExit(f"no match history under {history_dir}; run fetch_soccer_history_local.py --kind matches first")
        match_rows = pd.concat(frames, ignore_index=True).to_dict("records")
        rows = team_rows_from_match_history(match_rows)
        return compute_team_ratings(rows, as_of=as_of, window=90)  # goals-based rows: two rows/match, so double the window
    history_dir = REPO_ROOT / "data" / "soccer_source" / league / "team_history"
    frames = [pd.read_csv(path) for path in sorted(history_dir.glob("teams_*.csv"))]
    if not frames:
        raise SystemExit(f"no team history under {history_dir}; run fetch_soccer_history_local.py --kind teams first")
    rows = pd.concat(frames, ignore_index=True).to_dict("records")
    # Most recent ~1.2 seasons of form per team.
    return compute_team_ratings(rows, as_of=as_of, window=45)


def _fill_promoted(ratings: dict[str, dict[str, float]], fixtures: list[dict[str, Any]]) -> list[str]:
    filled: list[str] = []
    for fixture in fixtures:
        for team in (fixture["home_team"], fixture["away_team"]):
            if match_team_name(team, list(ratings)) is None:
                ratings[team] = dict(PROMOTED_TEAM_RATING)
                filled.append(team)
    return filled


def run_h2h(league: str, *, simulations: int, out_path: Path | None) -> int:
    api_key = os.environ.get("ODDS_API_KEY")
    if not api_key:
        print("ERROR: ODDS_API_KEY is not set")
        return 2
    sport_key = LEAGUE_SPORT_KEYS[league]
    response = requests.get(
        f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds",
        params={"apiKey": api_key, "regions": "us,uk,eu", "markets": "h2h", "oddsFormat": "decimal"},
        timeout=30,
    )
    response.raise_for_status()
    events = response.json()
    print(f"{len(events)} events with h2h odds for {sport_key}")

    fixtures: list[dict[str, Any]] = []
    market_rows: list[dict[str, Any]] = []
    for event in events:
        home = str(event.get("home_team") or "")
        away = str(event.get("away_team") or "")
        if not home or not away:
            continue
        implied = {"home": [], "draw": [], "away": []}
        for bookmaker in event.get("bookmakers") or []:
            for market in bookmaker.get("markets") or []:
                if market.get("key") != "h2h":
                    continue
                prices: dict[str, float] = {}
                for outcome in market.get("outcomes") or []:
                    name = str(outcome.get("name") or "")
                    try:
                        decimal_price = float(outcome.get("price"))
                    except Exception:
                        continue
                    if decimal_price <= 1.0:
                        continue
                    if name == home:
                        prices["home"] = 1.0 / decimal_price
                    elif name == away:
                        prices["away"] = 1.0 / decimal_price
                    elif name.lower() == "draw":
                        prices["draw"] = 1.0 / decimal_price
                if len(prices) == 3:
                    overround = sum(prices.values())
                    for side in implied:
                        implied[side].append(prices[side] / overround)
        if not implied["home"]:
            continue
        consensus = {side: sum(values) / len(values) for side, values in implied.items()}
        fixtures.append({"home_team": home, "away_team": away, "commence_time": event.get("commence_time")})
        market_rows.append(consensus)

    if not fixtures:
        print("no fixtures with complete three-way odds")
        return 1

    fixture_date = str(fixtures[0].get("commence_time") or "")[:10]
    ratings = _load_team_ratings(league, fixture_date)
    promoted = _fill_promoted(ratings, fixtures)
    simulation_input = build_soccer_simulation_input(
        league=league,
        date=str(fixtures[0].get("commence_time") or "")[:10],
        fixtures=fixtures,
        ratings=ratings,
        simulations=simulations,
    )
    adapter = build_soccer_simulation_adapter(league)
    output = adapter.simulate_games(simulation_input)

    rows = []
    for match_output, market in zip(output.match_outputs, market_rows):
        model = match_output["win_probability"]
        rows.append(
            {
                "match": f"{match_output['matchup']['home_team']} v {match_output['matchup']['away_team']}",
                "model_home": model["home"],
                "model_draw": model["draw"],
                "model_away": model["away"],
                "market_home": round(market["home"], 4),
                "market_draw": round(market["draw"], 4),
                "market_away": round(market["away"], 4),
                "abs_diff_home": round(abs(model["home"] - market["home"]), 4),
                "abs_diff_draw": round(abs(model["draw"] - market["draw"]), 4),
                "abs_diff_away": round(abs(model["away"] - market["away"]), 4),
                "model_total": match_output["team_projection"]["total_mean"],
            }
        )
    frame = pd.DataFrame(rows)
    mae = (frame["abs_diff_home"].mean() + frame["abs_diff_draw"].mean() + frame["abs_diff_away"].mean()) / 3.0
    print(frame.to_string(index=False))
    print(f"\nfixtures: {len(frame)}  promoted-prior teams: {promoted}")
    print(f"three-way MAE vs devigged consensus: {mae:.4f}")
    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(frame.to_csv(index=False), encoding="utf-8")
        print(f"wrote {out_path}")
    return 0


def _fetch_h2h_odds_by_bookmaker(league: str, api_key: str) -> list[dict[str, Any]]:
    sport_key = LEAGUE_SPORT_KEYS[league]
    response = requests.get(
        f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds",
        params={"apiKey": api_key, "regions": "us,uk,eu", "markets": "h2h", "oddsFormat": "decimal"},
        timeout=30,
    )
    response.raise_for_status()
    events = response.json()
    fixtures: list[dict[str, Any]] = []
    for event in events:
        home = str(event.get("home_team") or "")
        away = str(event.get("away_team") or "")
        if not home or not away:
            continue
        by_book: dict[str, dict[str, float]] = {}
        for bookmaker in event.get("bookmakers") or []:
            book_key = str(bookmaker.get("key") or "")
            for market in bookmaker.get("markets") or []:
                if market.get("key") != "h2h":
                    continue
                prices: dict[str, float] = {}
                for outcome in market.get("outcomes") or []:
                    name = str(outcome.get("name") or "")
                    try:
                        decimal_price = float(outcome.get("price"))
                    except Exception:
                        continue
                    if decimal_price <= 1.0:
                        continue
                    if name == home:
                        prices["home"] = decimal_price
                    elif name == away:
                        prices["away"] = decimal_price
                    elif name.lower() == "draw":
                        prices["draw"] = decimal_price
                if len(prices) == 3:
                    by_book[book_key] = prices
        if by_book:
            fixtures.append(
                {"home_team": home, "away_team": away, "commence_time": event.get("commence_time"), "books": by_book}
            )
    return fixtures


def run_anchor_validation(
    league: str,
    *,
    anchor_book: str,
    weight: float,
    simulations: int,
    anchor_solver_simulations: int,
    out_path: Path | None,
) -> int:
    """Non-circular market-anchoring validation.

    Anchoring toward the same market consensus used to evaluate the model
    would be tautological -- telling the model the answer, then checking it
    matches. Instead: anchor toward one bookmaker's line (``anchor_book``),
    then evaluate against the devigged consensus of every *other* bookmaker
    for the same fixture. If the anchored model tracks the held-out
    consensus better than the unanchored model does, that's real evidence
    the mechanism generalizes rather than just fitting itself.
    """
    api_key = os.environ.get("ODDS_API_KEY")
    if not api_key:
        print("ERROR: ODDS_API_KEY is not set")
        return 2
    fixtures_raw = _fetch_h2h_odds_by_bookmaker(league, api_key)
    print(f"{len(fixtures_raw)} fixtures with h2h odds for {LEAGUE_SPORT_KEYS[league]}")

    usable = []
    for fixture in fixtures_raw:
        books = fixture["books"]
        if anchor_book not in books:
            continue
        other_books = {key: prices for key, prices in books.items() if key != anchor_book}
        if len(other_books) < 3:
            continue  # need a meaningfully independent held-out consensus
        usable.append(fixture)
    if not usable:
        print(f"no fixtures had both '{anchor_book}' odds and >=3 other bookmakers to hold out")
        return 1
    print(f"{len(usable)} fixtures have both an anchor book and a held-out consensus of other books")

    ratings = _load_team_ratings(league)
    promoted = _fill_promoted(ratings, [{"home_team": f["home_team"], "away_team": f["away_team"]} for f in usable])
    adapter = build_soccer_simulation_adapter(league)

    rows = []
    for index, fixture in enumerate(usable):
        home, away = fixture["home_team"], fixture["away_team"]
        anchor_probability = devig_decimal_odds(fixture["books"][anchor_book]).get("home")
        other_books = {key: prices for key, prices in fixture["books"].items() if key != anchor_book}
        held_out_implied = [devig_decimal_odds(prices) for prices in other_books.values()]
        held_out_consensus = {
            side: sum(sample.get(side, 0.0) for sample in held_out_implied) / len(held_out_implied)
            for side in ("home", "draw", "away")
        }
        if anchor_probability is None:
            continue

        home_key = match_team_name(home, list(ratings)) or home
        away_key = match_team_name(away, list(ratings)) or away
        home_rating = ratings.get(home_key, dict(PROMOTED_TEAM_RATING))
        away_rating = ratings.get(away_key, dict(PROMOTED_TEAM_RATING))

        base_input = build_soccer_simulation_input(
            league=league, date="anchor_validation", fixtures=[{"home_team": home, "away_team": away}], ratings=ratings, simulations=simulations
        )
        baseline_output = adapter.simulate_games(base_input)
        baseline_probability = baseline_output.match_outputs[0]["win_probability"]

        anchored_home, anchored_away = anchor_team_ratings(
            home_rating,
            away_rating,
            market_home_win_probability=anchor_probability,
            weight=weight,
            simulations=anchor_solver_simulations,
            seed=2000 + index,
        )
        anchored_ratings = {**ratings, home_key: anchored_home, away_key: anchored_away}
        anchored_input = build_soccer_simulation_input(
            league=league, date="anchor_validation", fixtures=[{"home_team": home, "away_team": away}], ratings=anchored_ratings, simulations=simulations
        )
        anchored_output = adapter.simulate_games(anchored_input)
        anchored_probability = anchored_output.match_outputs[0]["win_probability"]

        def _mae(model: dict[str, float], target: dict[str, float]) -> float:
            return sum(abs(model[side] - target[side]) for side in ("home", "draw", "away")) / 3.0

        rows.append(
            {
                "match": f"{home} v {away}",
                "anchor_book_home_prob": round(anchor_probability, 4),
                "held_out_consensus_home_prob": round(held_out_consensus["home"], 4),
                "n_held_out_books": len(other_books),
                "baseline_mae_vs_heldout": round(_mae(baseline_probability, held_out_consensus), 4),
                "anchored_mae_vs_heldout": round(_mae(anchored_probability, held_out_consensus), 4),
                "market_shift_applied": anchored_home.get("market_shift_applied"),
            }
        )

    frame = pd.DataFrame(rows)
    if frame.empty:
        print("no fixtures produced a comparable row")
        return 1
    print(frame.to_string(index=False))
    baseline_mae = frame["baseline_mae_vs_heldout"].mean()
    anchored_mae = frame["anchored_mae_vs_heldout"].mean()
    print(f"\nfixtures: {len(frame)}  anchor_book={anchor_book}  weight={weight}  promoted-prior teams: {promoted}")
    print(f"mean MAE vs held-out consensus -- baseline (unanchored): {baseline_mae:.4f}")
    print(f"mean MAE vs held-out consensus -- anchored:              {anchored_mae:.4f}")
    improved = (frame["anchored_mae_vs_heldout"] < frame["baseline_mae_vs_heldout"]).sum()
    print(f"anchoring improved {improved}/{len(frame)} fixtures vs the held-out consensus")
    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(frame.to_csv(index=False), encoding="utf-8")
        print(f"wrote {out_path}")
    return 0


def _poisson_at_least(mean_value: float, k: int) -> float:
    if mean_value <= 0.0:
        return 0.0 if k > 0 else 1.0
    cumulative = 0.0
    term = math.exp(-mean_value)
    for i in range(k):
        if i > 0:
            term *= mean_value / i
        cumulative += term
    return max(0.0, min(1.0, 1.0 - cumulative))


def _top_minutes_starter_ids(player_rows: list[dict[str, Any]], *, per_team: int = 11) -> set[str]:
    """Heuristic "likely lineup": each team's top-N players by season
    expected_minutes_share. This is NOT a confirmed or projected lineup from
    any lineup-confirmation source (none is wired up) -- it's a depth-chart
    proxy usable when fixtures are too far out for real lineups to exist
    yet. Treat results built from it as evidence about the starter-
    awareness *mechanism*, not as a claim about real lineup accuracy.
    """
    from syndicate.features.soccer.sim_engine.soccersim.player_props import player_row_key

    by_team: dict[str, list[tuple[float, str]]] = {}
    for index, row in enumerate(player_rows):
        team = str(row.get("team") or "")
        try:
            minutes = float(row.get("expected_minutes_share") or 0.0)
        except Exception:
            minutes = 0.0
        key = player_row_key(row, index, "x")
        by_team.setdefault(team, []).append((minutes, key))
    starters: set[str] = set()
    for rows in by_team.values():
        rows.sort(key=lambda pair: pair[0], reverse=True)
        starters.update(key for _, key in rows[:per_team])
    return starters


def run_props(
    league: str,
    props_csv: Path,
    *,
    simulations: int,
    out_path: Path | None,
    starter_mode: str = "none",
) -> int:
    props = pd.read_csv(props_csv)
    if props.empty:
        print(f"no prop rows in {props_csv}")
        return 1
    fixtures = [
        {"home_team": home, "away_team": away}
        for home, away in sorted({(str(row.home_team), str(row.away_team)) for row in props.itertuples()})
    ]
    print(f"{len(fixtures)} fixtures in props file")

    ratings = _load_team_ratings(league)
    promoted = _fill_promoted(ratings, fixtures)
    players_dir = REPO_ROOT / "data" / "soccer_source" / league / "players"
    player_frames = [pd.read_csv(path) for path in sorted(players_dir.glob("players_*.csv"))]
    if not player_frames:
        raise SystemExit(f"no player history under {players_dir}")
    player_rows = pd.concat(player_frames, ignore_index=True).to_dict("records")

    if starter_mode == "top_minutes":
        starter_ids = _top_minutes_starter_ids(player_rows)
        for fixture in fixtures:
            fixture["home_starter_ids"] = tuple(starter_ids)
            fixture["away_starter_ids"] = tuple(starter_ids)
        print(f"starter_mode=top_minutes: heuristic depth-chart lineup, {len(starter_ids)} flagged starter-rows total")

    simulation_input = build_soccer_simulation_input(
        league=league,
        date=str(props_csv.stem),
        fixtures=fixtures,
        ratings=ratings,
        player_rows=player_rows,
        simulations=simulations,
    )
    adapter = build_soccer_simulation_adapter(league)
    output = adapter.simulate_props(simulation_input)
    print(f"simulated {len(output.match_outputs)} matches, {len(output.player_outputs)} player projections")

    projections_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    match_by_id = {row["match_id"]: row for row in output.match_outputs}
    for row in output.player_outputs:
        match_row = match_by_id.get(row["match_id"]) or {}
        matchup = match_row.get("matchup") or {}
        event_key = f"{matchup.get('away_team')} @ {matchup.get('home_team')}"
        projections_by_key[(_norm_player(row["player_name"]), event_key)] = row

    joined: list[dict[str, Any]] = []
    for prop in props.to_dict("records"):
        key = (_norm_player(prop.get("player")), str(prop.get("event")))
        projection = projections_by_key.get(key)
        if projection is None:
            continue
        market = str(prop.get("market"))
        line = prop.get("line")
        over_prob = _american_to_prob(prop.get("over_price"))
        under_prob = _american_to_prob(prop.get("under_price"))
        model_prob = None
        market_prob = None
        # Books void player props on DNP, so posted prices are conditional on
        # the player appearing — compare against the conditional projections.
        if market == "Anytime Goalscorer":
            model_prob = projection["anytime_scorer_probability_if_playing"]
            market_prob = over_prob  # single-sided: includes vig
        elif market in {"Shots", "Shots On Target"} and line is not None and not pd.isna(line):
            expected = (
                projection["expected_shots_if_playing"]
                if market == "Shots"
                else projection["expected_shots_on_target_if_playing"]
            )
            model_prob = _poisson_at_least(float(expected), int(float(line) + 0.5))
            if over_prob is not None and under_prob is not None:
                market_prob = over_prob / (over_prob + under_prob)
            else:
                market_prob = over_prob
        if model_prob is None or market_prob is None:
            continue
        joined.append(
            {
                "player": prop.get("player"),
                "team_side": projection.get("side"),
                "event": prop.get("event"),
                "market": market,
                "line": line,
                "model_prob": round(float(model_prob), 4),
                "market_prob": round(float(market_prob), 4),
                "diff": round(float(model_prob) - float(market_prob), 4),
                "expected_minutes_share": projection.get("expected_minutes_share"),
                "book": prop.get("book"),
            }
        )

    frame = pd.DataFrame(joined)
    if frame.empty:
        print("no props matched to projections (name/event join produced nothing)")
        return 1
    print(f"matched {len(frame)} prop rows to projections ({len(frame) / len(props) * 100:.1f}% of {len(props)})")
    summary = frame.groupby("market").agg(
        rows=("diff", "size"),
        mean_model=("model_prob", "mean"),
        mean_market=("market_prob", "mean"),
        mae=("diff", lambda s: s.abs().mean()),
        bias=("diff", "mean"),
    )
    correlations = frame.groupby("market").apply(
        lambda g: pd.Series(
            {
                "pearson": g["model_prob"].corr(g["market_prob"]),
                "spearman": g["model_prob"].corr(g["market_prob"], method="spearman"),
            }
        ),
        include_groups=False,
    )
    summary = summary.join(correlations)
    print(summary.round(4).to_string())
    print(
        "note: single-sided rows (no under price) compare against raw implied "
        "probability including the book's full margin — negative bias there is "
        "expected; rank correlations are the vig-free signal."
    )
    if promoted:
        print(f"promoted-prior teams: {promoted}")
    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(frame.to_csv(index=False), encoding="utf-8")
        print(f"wrote {out_path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="mode", required=True)
    h2h = subparsers.add_parser("h2h")
    h2h.add_argument("--league", required=True, choices=sorted(LEAGUE_SPORT_KEYS))
    h2h.add_argument("--simulations", type=int, default=400)
    h2h.add_argument("--out", type=str, default=None)
    props = subparsers.add_parser("props")
    props.add_argument("--league", required=True, choices=sorted(LEAGUE_SPORT_KEYS))
    props.add_argument("--props-csv", required=True, type=str)
    props.add_argument("--simulations", type=int, default=400)
    props.add_argument("--out", type=str, default=None)
    props.add_argument(
        "--starter-mode",
        choices=("none", "top_minutes"),
        default="none",
        help="top_minutes: heuristic depth-chart lineup from season minutes share (not a confirmed real lineup)",
    )
    anchor = subparsers.add_parser("anchor")
    anchor.add_argument("--league", required=True, choices=sorted(LEAGUE_SPORT_KEYS))
    anchor.add_argument("--anchor-book", type=str, default="draftkings")
    anchor.add_argument("--weight", type=float, default=0.4)
    anchor.add_argument("--simulations", type=int, default=250)
    anchor.add_argument("--anchor-solver-simulations", type=int, default=120)
    anchor.add_argument("--out", type=str, default=None)
    args = parser.parse_args()

    if args.mode == "h2h":
        return run_h2h(args.league, simulations=args.simulations, out_path=Path(args.out) if args.out else None)
    if args.mode == "anchor":
        return run_anchor_validation(
            args.league,
            anchor_book=args.anchor_book,
            weight=args.weight,
            simulations=args.simulations,
            anchor_solver_simulations=args.anchor_solver_simulations,
            out_path=Path(args.out) if args.out else None,
        )
    return run_props(
        args.league,
        Path(args.props_csv),
        simulations=args.simulations,
        out_path=Path(args.out) if args.out else None,
        starter_mode=args.starter_mode,
    )


if __name__ == "__main__":
    raise SystemExit(main())
