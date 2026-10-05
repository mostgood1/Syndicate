"""Local NHL artifact producer — the Syndicate-owned replacement for the vendor CLI subprocess.

Runs the ``hockeysim`` engine over a date's slate and writes the artifact CSVs the NHL UI reads,
ending the ``python -m nhl_betting.cli`` dependency (Phase 5, direct cutover). Reads only
Syndicate-owned inputs: the mirrored slate/roster/lineup/goalie artifacts + collected book odds
(``syndicate.local_nhl_odds`` collector output).

Pipeline per game: build_slate_features (projection-primed) -> inject consensus market lines ->
build_game_prediction on the UN-anchored lambdas (the `_raw` columns) -> market-anchor at the ONE
resolved weight -> build_game_prediction again on the anchored lambdas (the served columns).
Emits predictions_{date}.csv, recommendations_sim_{date}.csv (leaning pick per market), and
props_recommendations_{date}.csv (boxscore engine joined to collected prop lines).

MARKET ANCHORING IS ON BY DEFAULT HERE (pricing plane v1, P4). `loaders.build_game_features`'s
`anchor_to_market` flag defaults to False, but this producer never uses it -- it injects the
consensus lines itself and calls `market_anchoring.anchor_game_features` directly, so in production
(`scripts/refresh_nhl_oddsapi.py::_run_owned_generation`) every game with a usable moneyline is
anchored at 0.35 BEFORE the sim. The one production knob is `SYNDICATE_NHL_MARKET_ANCHOR_WEIGHT`
(absent => 0.35, bit-identical to the pre-flag artifact; `0` => no anchoring; any float in [0, 1]);
`--anchor-weight` / `--no-anchor` override it for a local run. Every predictions row records
`anchor_weight`, `anchor_state` (anchored | no_market | disabled), `p_home_ml_raw` and
`p_home_pl_-1.5_raw` so the pure model survives beside the served blend.

`build_props_for_date` builds its OWN slate with no market injected and no anchoring; it does not
consume the anchored lambdas (and `anchor_game_features` never touches `goals_per_60`, the field
the boxscore engine reads), so prop rows carry no anchoring provenance.

Usage:
    py -3 scripts/build_nhl_artifacts.py --date 2026-06-14 --props --recommendations
    py -3 scripts/build_nhl_artifacts.py --date 2026-06-14 --no-anchor --out-dir /tmp/out
"""
from __future__ import annotations

import argparse
import math
import sys
from collections import defaultdict
from dataclasses import replace
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from syndicate.features.nhl.sim_engine.hockeysim.adapters import build_game_prediction  # noqa: E402
from syndicate.features.nhl.sim_engine.hockeysim.artifacts import (  # noqa: E402
    prop_recommendation_row,
    write_predictions_csv,
    write_prop_projections_csv,
    write_props_recommendations_csv,
    write_recommendations_sim_csv,
)
from syndicate.features.nhl.sim_engine.hockeysim.contracts import (  # noqa: E402
    HockeyGamePrediction,
    HockeyMarketLines,
)
from syndicate.features.nhl.sim_engine.hockeysim.market_anchoring import (  # noqa: E402
    ANCHOR_STATE_ANCHORED,
    ENV_ANCHOR_WEIGHT,
    anchor_game_features,
    anchor_state_for,
    resolve_anchor_weight,
)
from syndicate.features.nhl.sim_engine.hockeysim.player_props import _starter_goalie_id, build_prop_projections  # noqa: E402
from syndicate.features.nhl.sim_engine.hockeysim.features.loaders import (  # noqa: E402
    _processed_dir,
    build_slate_features,
    nhl_source_root,
)
from syndicate.features.nhl.sim_engine.hockeysim.features.market_lines import (  # noqa: E402
    load_market_lines,
    market_for_game,
)
from syndicate.features.nhl.sim_engine.hockeysim.features.props_lines import (  # noqa: E402
    initial_surname_key,
    load_props_lines,
    normalize_name,
)


def _effective_anchor_weight(anchor: bool, anchor_weight: Optional[float]) -> float:
    """The ONE resolved weight this producer honours: ``--no-anchor`` => 0; an explicit kwarg wins;
    otherwise the env flag; otherwise 0.35 (``resolve_anchor_weight``)."""
    if not anchor:
        return 0.0
    weight, _source = resolve_anchor_weight(anchor_weight)
    return weight


def predict_game(game, *, anchor_weight: float) -> HockeyGamePrediction:
    """One game's prediction row with anchoring provenance.

    Runs the (seeded, deterministic) game-market sim on the UN-anchored lambdas first -- that is
    the pure model, recorded as ``p_home_ml_raw`` / ``p_home_pl_minus_1_5_raw``. When the game is
    ``anchored`` (weight > 0 and a usable moneyline), the lambdas are shifted toward the book and
    the sim runs again on the anchored lambdas; that second run is the SERVED row, unchanged from
    the pre-flag producer. Otherwise the raw run IS the served row (served == raw).
    """
    state = anchor_state_for(game.market, anchor_weight)
    raw = build_game_prediction(game)
    served = raw
    if state == ANCHOR_STATE_ANCHORED:
        served = build_game_prediction(anchor_game_features(game, weight=anchor_weight))
    return replace(
        served,
        anchor_weight=float(anchor_weight),
        anchor_state=state,
        p_home_ml_raw=raw.p_home_ml,
        p_home_pl_minus_1_5_raw=raw.p_home_pl_minus_1_5,
    )


_CONFIRMED_GOALIES_DONE: Dict[Tuple[str, str], Dict[str, object]] = {}


def _ensure_confirmed_goalies(date: str, root: Optional[Path]) -> None:
    """Overlay Daily Faceoff CONFIRMED starters onto `starting_goalies_<date>.csv` once per date per process,
    before any producer reads the slate (lane `nhl-confirmed-goalies`). It runs after the collector, because
    generation collects first and then calls these producers. Never raises; off: SYNDICATE_NHL_CONFIRMED_GOALIES=off."""
    processed = _processed_dir(root)
    key = (str(processed), date)
    if key in _CONFIRMED_GOALIES_DONE:
        return
    from syndicate.features.nhl.confirmed_goalies import refresh_confirmed_goalies

    _CONFIRMED_GOALIES_DONE[key] = refresh_confirmed_goalies(processed.parent.parent, date)


def _apply_scoreadj_xg(games: list, date: str, root: Optional[Path]) -> list:
    """Game lines only: re-project each game from SCORE-ADJUSTED team xG (`team_xg_scoreadj_<season>.csv`,
    written beside `team_xg_<season>.csv` by `inseason_team_xg`) and give the game-market sim those period
    lambdas. Props build their own features and never see this. A game where either team lacks an adjusted
    rate keeps its unadjusted lambdas. Off switch: SYNDICATE_NHL_SCOREADJ_XG=off (user override 2026-10-05)."""
    from datetime import date as _date

    from syndicate.features.nhl.inseason_team_xg import load_scoreadj_map
    from syndicate.features.nhl.sim_engine.hockeysim.projection import project_game

    adj = load_scoreadj_map(_processed_dir(root), _date.fromisoformat(date))
    if not adj:
        return games
    out = []
    for g in games:
        ha, aa = adj.get(str(g.home.abbrev or "").upper()), adj.get(str(g.away.abbrev or "").upper())
        if ha is None or aa is None:
            out.append(g)
            continue
        pr = project_game(replace(g.home, xgf_per_60=ha[0], xga_per_60=ha[1]),
                          replace(g.away, xgf_per_60=aa[0], xga_per_60=aa[1]))
        out.append(replace(g, home=replace(g.home, period_goal_lambdas=tuple(pr.period_home_lambdas)),
                           away=replace(g.away, period_goal_lambdas=tuple(pr.period_away_lambdas))))
    return out


def _predictions_and_markets(
    date: str, *, root: Optional[Path], anchor: bool, anchor_weight: Optional[float],
) -> Tuple[List[HockeyGamePrediction], Dict[str, HockeyMarketLines]]:
    """Build every game's prediction for a slate (market-injected, anchored at the resolved weight)."""
    weight = _effective_anchor_weight(anchor, anchor_weight)
    _ensure_confirmed_goalies(date, root)
    games = _apply_scoreadj_xg(build_slate_features(date, root=root), date, root)
    lines = load_market_lines(date, root=root)
    predictions: List[HockeyGamePrediction] = []
    markets: Dict[str, HockeyMarketLines] = {}
    for g in games:
        market = market_for_game(lines, g.home.name, g.away.name)
        if market is not None:
            g = replace(g, market=market)
        markets[g.game_pk] = g.market
        predictions.append(predict_game(g, anchor_weight=weight))
    return predictions, markets


def build_predictions_for_date(
    date: str, *, root: Optional[Path] = None, anchor: bool = True,
    anchor_weight: Optional[float] = None, out_dir: Optional[Path] = None,
) -> Tuple[Path, int]:
    """Produce predictions_{date}.csv for a slate. Returns (path, game_count).

    ``anchor_weight=None`` (the production default) resolves through ``SYNDICATE_NHL_MARKET_ANCHOR_WEIGHT``,
    falling back to 0.35; ``anchor=False`` forces 0 (state ``disabled``).
    """
    predictions, markets = _predictions_and_markets(date, root=root, anchor=anchor, anchor_weight=anchor_weight)
    out_path = (out_dir or _processed_dir(root)) / f"predictions_{date}.csv"
    n = write_predictions_csv(out_path, predictions, markets)
    return out_path, n


def build_recommendations_for_date(
    date: str, *, root: Optional[Path] = None, anchor: bool = True,
    anchor_weight: Optional[float] = None, out_dir: Optional[Path] = None,
) -> Tuple[Path, int]:
    """Produce recommendations_sim_{date}.csv (leaning pick per market). Returns (path, row_count).
    Anchor-weight resolution is identical to :func:`build_predictions_for_date`."""
    predictions, markets = _predictions_and_markets(date, root=root, anchor=anchor, anchor_weight=anchor_weight)
    out_path = (out_dir or _processed_dir(root)) / f"recommendations_sim_{date}.csv"
    n = write_recommendations_sim_csv(out_path, predictions, markets)
    return out_path, n


def _poisson_p_over(line: float, lam: float) -> float:
    """P(X > line) for X ~ Poisson(lam). Half-lines have no push (P(X==line)=0)."""
    lam = max(0.0, float(lam))
    k = math.floor(float(line)) + 1  # smallest integer strictly greater than a .5 line
    cdf = 0.0
    for i in range(0, k):
        cdf += math.exp(-lam) * (lam ** i) / math.factorial(i)
    return max(0.0, min(1.0, 1.0 - cdf))


def _game_type(game_pk: object) -> str:
    """NHL game id YYYYTTNNNN: TT 01 preseason, 02 regular season, 03 playoffs."""
    code = str(game_pk or "")[4:6]
    return {"01": "preseason", "02": "regular", "03": "playoff"}.get(code, "")


def _line_context(pf, is_sim_starter: bool, game_type: str) -> Dict[str, object]:
    """What the board's per-line gates need and the CSV did not carry."""
    if pf is None:
        return {"game_type": game_type}
    return {
        "line_slot": pf.line_slot or "",
        "proj_toi": round(float(pf.proj_toi or 0.0), 3),
        "sim_starter": ("1" if is_sim_starter else "0") if str(pf.position).upper() == "G" else "",
        "game_type": game_type,
    }


def _match_lines_to_game(game, lines: List[Dict[str, object]]) -> Dict[int, int]:
    """``{index into lines: player_id}`` for the book lines that belong to this game's players.

    Exact normalized full name first. Then, because the lineup feed has carried the boxscore's
    ABBREVIATED name ("A. Copp" for the book's "Andrew Copp") -- which matched 0 of 339 lines on
    2026-10-02 -- an initial+surname key, accepted only when (a) the line names this game's two
    teams and (b) exactly one player in the game carries that key. A line without team names gets
    the exact match only, so an abbreviation can never capture a player from another game.
    """
    full: Dict[str, int] = {}
    abbrev: Dict[str, List[int]] = defaultdict(list)
    for p in list(game.home_players) + list(game.away_players):
        full.setdefault(normalize_name(p.full_name), int(p.player_id))
        key = initial_surname_key(p.full_name)
        if key:
            abbrev[key].append(int(p.player_id))
    teams = {normalize_name(game.home.name), normalize_name(game.away.name)}
    out: Dict[int, int] = {}
    for idx, ln in enumerate(lines):
        pid = full.get(str(ln["name_key"]))
        if pid is None:
            line_teams = {normalize_name(ln.get("home_team")), normalize_name(ln.get("away_team"))}
            if line_teams != teams:
                continue
            cands = abbrev.get(initial_surname_key(ln.get("player_name")), [])
            if len(set(cands)) != 1:
                continue
            pid = cands[0]
        else:
            line_teams = {normalize_name(ln.get("home_team")), normalize_name(ln.get("away_team"))}
            if "" not in line_teams and line_teams != teams:
                continue
        out[idx] = pid
    return out


def build_props_for_date(
    date: str, *, root: Optional[Path] = None, n_sims: int = 400, out_dir: Optional[Path] = None,
) -> Tuple[Path, int]:
    """Produce props_recommendations_{date}.csv for a slate. Returns (path, row_count)."""
    _ensure_confirmed_goalies(date, root)
    games = build_slate_features(date, root=root)
    lines = load_props_lines(date, root=root)

    rows_out: List[Dict[str, object]] = []
    all_markets: List[Dict[str, object]] = []
    for g in games:
        line_pids = _match_lines_to_game(g, lines)
        if not line_pids:
            continue
        pid_market_line: Dict[Tuple[int, str], float] = {}
        for idx, pid in line_pids.items():
            r = lines[idx]
            pid_market_line.setdefault((pid, str(r["market"])), float(r["line"]))

        projs = build_prop_projections(g, lines=pid_market_line, n_sims=n_sims)
        proj_by_key = {(p.player_id, p.market): p for p in projs}
        game_type = _game_type(g.game_pk)
        starters = {_starter_goalie_id(tuple(g.home_players)), _starter_goalie_id(tuple(g.away_players))}
        meta = {int(p.player_id): p for p in list(g.home_players) + list(g.away_players)}
        # EVERY projected player x market, not only the pairs this producer holds a current line for
        # `[2026-10-03, lane nhl-player-props-projection]`: 166 of 232 unprojected 10-03 board rows were
        # projected players whose (player, market) quote came from a book or a moment this lines file
        # did not have. The board prices any line from the mean, so it needs the mean, not the line.
        book_name = {pid: str(lines[i].get("player_name") or "") for i, pid in line_pids.items()}
        for pr in projs:
            all_markets.append({
                "date": date,
                "player": book_name.get(int(pr.player_id)) or pr.player,
                "team": pr.team, "opp": pr.opp, "market": pr.market,
                "proj_lambda": round(float(pr.proj_lambda), 4),
                **_line_context(meta.get(int(pr.player_id)), int(pr.player_id) in starters, game_type),
            })

        for idx, pid in line_pids.items():
            r = lines[idx]
            pr = proj_by_key.get((pid, str(r["market"])))
            if pr is None:
                continue
            line = float(r["line"])
            p_over = _poisson_p_over(line, pr.proj_lambda)
            # `player` is the BOOK's name: every downstream join (the board, prop evidence) keys on
            # the sportsbook's full name, never on the lineup feed's spelling.
            proj_obj = replace(
                pr, player=str(r.get("player_name") or pr.player), line=line,
                p_over=round(p_over, 6), p_under=round(1.0 - p_over, 6),
            )
            op = r.get("over_price")
            up = r.get("under_price")
            row = prop_recommendation_row(
                proj_obj,
                over_price=int(round(float(op))) if op is not None else None,
                under_price=int(round(float(up))) if up is not None else None,
                book=str(r.get("book") or ""),
                context=_line_context(meta.get(pid), pid in starters, game_type),
            )
            if row:
                rows_out.append(row)

    out_path = (out_dir or _processed_dir(root)) / f"props_recommendations_{date}.csv"
    n = write_props_recommendations_csv(out_path, rows_out)
    write_prop_projections_csv(
        (out_dir or _processed_dir(root)) / f"props_recommendations_all_markets_{date}.csv", all_markets,
    )
    return out_path, n


def main() -> int:
    ap = argparse.ArgumentParser(description="Build local NHL artifacts (hockeysim producer)")
    ap.add_argument("--date", required=True, help="slate date YYYY-MM-DD")
    ap.add_argument("--root", default=None, help="artifact root (default data/nhl_source)")
    ap.add_argument("--no-anchor", action="store_true", help="disable market anchoring (anchor_state=disabled)")
    ap.add_argument("--anchor-weight", type=float, default=None,
                    help=f"pre-sim moneyline anchor weight in [0,1]; default: ${ENV_ANCHOR_WEIGHT}, else 0.35")
    ap.add_argument("--recommendations", action="store_true", help="also build recommendations_sim")
    ap.add_argument("--props", action="store_true", help="also build props_recommendations")
    ap.add_argument("--props-n-sims", type=int, default=400)
    ap.add_argument("--out-dir", default=None, help="output dir (default <root>/data/processed)")
    args = ap.parse_args()

    root = Path(args.root) if args.root else None
    out_dir = Path(args.out_dir) if args.out_dir else None
    anchor = not args.no_anchor
    weight, source = resolve_anchor_weight(args.anchor_weight)
    if not anchor:
        weight, source = 0.0, "--no-anchor"
    print(f"market anchor weight={weight} (source={source}, env={ENV_ANCHOR_WEIGHT})", flush=True)
    path, n = build_predictions_for_date(
        args.date, root=root, anchor=anchor, anchor_weight=weight, out_dir=out_dir,
    )
    if n == 0:
        print(f"No games for {args.date} (no mirrored scoreboard). Nothing written.")
        return 1
    print(f"Wrote {n} game predictions -> {path}")
    if args.recommendations:
        rpath, rn = build_recommendations_for_date(
            args.date, root=root, anchor=anchor, anchor_weight=weight, out_dir=out_dir,
        )
        print(f"Wrote {rn} game recommendations -> {rpath}")
    if args.props:
        ppath, pn = build_props_for_date(args.date, root=root, n_sims=args.props_n_sims, out_dir=out_dir)
        print(f"Wrote {pn} props recommendations -> {ppath}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
