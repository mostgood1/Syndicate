"""Grade S1F -- the high-volume-opponent SAVES OVER -- forward on 2026-27, exactly as pre-registered (signal-engine-nhl).

User 2026-10-14: "yes register the forward saves test". One hypothesis, no family:

  S1F  nhl.saves_opp_volume_high  OVER the goalie's saves line when the OPPONENT's season-to-date shots for per game
       >= 30.2 (>= 5 team games) -- the v1 rule and threshold. Evidence before registration: +10.6% (v1 confirm, 34 lines),
       +9.1% [+0.8, +17.5] on 138 unseen 2025-26 games (v3), +11% ROI at the best over across 203 bets.

GAMES     regular season (gamePk 2026020xxx), scheduled start after REGISTERED_AT, game day <= FINAL_READ.
PRICES    the fleet quote logs `nhl_source/tracking/book_quotes/<date>.jsonl[.gz]` (files dated game day -2 .. +1), market
          SAVES; per book the last observation at or before start - 3 min (the 2025-26 saves snapshot), change-log rule
          (`close_main_lines`); main line per goalie = most two-sided books (tie -> Shin p nearest 0.5); fair = median
          per-book Shin over the H7 US books, price = the best US over -- both as in the 2025-26 evidence (no Pinnacle).
FEATURES  `matchup_signals_nhl.AsOf` over `raw/player_game_stats.csv` (2026-27 regular season, games before the day).
OUTCOME   the goalie's row in that game (first initial + surname, role goalie); none -> void (he did not play); push void.
PRIMARY   fired residual (y_over - p_over) vs the Shin fair, game-clustered bootstrap B 2000 seed 20261014, one-sided
          p = (#boot <= 0 + 1) / (B + 1): SUPPORTED iff p <= 0.025 at the final read. SECONDARY: flat ROI at the best US
          over; the pooled saves-over residual on every graded line (context). Earlier reads are INTERIM.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
for _p in (REPO_ROOT, REPO_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from grade_football_fade_leads import close_main_lines  # noqa: E402
from grade_h7_nba_unders import US_BOOKS, roi  # noqa: E402
from signal_lift_football import _read_jsonl, decimal  # noqa: E402
from syndicate.features.shared.matchup_signals import residual_stats  # noqa: E402
from syndicate.features.shared.matchup_signals_nhl import (  # noqa: E402
    NHL_MARKET_STATS,
    THRESHOLDS,
    AsOf,
    load_game_log,
    name_key,
    saves_fires,
)

# ---- the registration -------------------------------------------------------------------------------------------------
REGISTERED_AT = datetime(2026, 10, 14, 2, 53, tzinfo=timezone.utc)  # the lane-block registration
SEASON = "2026"
FINAL_READ = "2027-04-18"
CLOSE_LEAD = timedelta(minutes=3)
SIGNAL = "nhl.saves_opp_volume_high"
SEED, B, ALPHA = 20261014, 2000, 0.025
# ----------------------------------------------------------------------------------------------------------------------


def _quotes_for(root: Path, day: str) -> Path | None:
    base = root / "nhl_source" / "tracking" / "book_quotes" / f"{day}.jsonl"
    for path in (base, base.with_name(base.name + ".gz")):
        if path.is_file():
            return path
    return None


def collect(root: Path, through: str, ignore_registration: bool, counts: dict[str, int]) -> list[dict[str, Any]]:
    from syndicate.features.shared.team_aliases import canonical_team

    log = [r for r in load_game_log([root / "nhl_source" / "source_artifacts" / "data" / "raw" / "player_game_stats.csv"])
           if r["season"] == SEASON]
    asof = AsOf(log)
    goalies: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    teams_in: dict[str, set[str]] = defaultdict(set)
    day_of: dict[str, str] = {}
    for r in asof.rows:
        teams_in[r["game"]].add(r["team"])
        day_of[r["game"]] = r["date"]
        if r["role"] == "goalie":
            goalies[(r["game"], r["key"])].append(r)
    games_by_day = {(day_of[g], frozenset(canonical_team("nhl", t) for t in ts)): g for g, ts in teams_in.items()}
    graded_days = set(day_of.values())
    first = (REGISTERED_AT - timedelta(days=1)).date().isoformat()
    if ignore_registration and graded_days:  # a format check reads the season from its first game
        first = min(graded_days)
    records, seen = [], set()
    day = date.fromisoformat(first)
    while day.isoformat() <= through:
        d = day.isoformat()
        day += timedelta(days=1)
        if d not in graded_days:
            continue
        rows = []
        for k in (-2, -1, 0, 1):
            path = _quotes_for(root, (date.fromisoformat(d) + timedelta(days=k)).isoformat())
            if path is not None:
                rows += _read_jsonl(path)
        for line in close_main_lines(rows, books=US_BOOKS, lead=CLOSE_LEAD, market_stats=NHL_MARKET_STATS):
            if line["stat"] != "saves":
                continue
            ident = (line["event"], line["player"])
            if ident in seen:
                continue
            if not ignore_registration and line["kickoff"] <= REGISTERED_AT:
                seen.add(ident)
                counts["pre_registration_start"] += 1
                continue
            teams = frozenset(canonical_team("nhl", str(line.get(k) or "")) for k in ("home_team", "away_team"))
            game = games_by_day.get((d, teams))
            if game is None:
                continue  # another day's game
            seen.add(ident)
            match = goalies.get((game, name_key(line["player"])), [])
            if len(match) != 1 or line["best_over"] is None:
                counts["void_goalie_did_not_play_or_no_price"] += 1
                continue
            g = match[0]
            if g["saves"] == line["point"]:
                counts["void_push"] += 1
                continue
            opp = next((t for t in teams_in[game] if t != g["team"]), None)
            opp_f = asof.team(opp, SEASON, d) if opp else None
            feats = {"opp_sf_pg": (opp_f or {}).get("sf_pg")}
            y = 1.0 if g["saves"] > line["point"] else 0.0
            records.append({"day": d, "game": game, "goalie": line["player"], "point": line["point"], "y": y,
                            "p": line["p_over"], "price": line["best_over"],
                            "pnl": (decimal(line["best_over"]) - 1.0) if y else -1.0,
                            "fires": SIGNAL in saves_fires(feats), "opp_sf_pg": feats["opp_sf_pg"]})
            counts["graded"] += 1
    return records


def report(records: list[dict[str, Any]], *, final: bool, counts: Mapping[str, int]) -> dict[str, Any]:
    fired = [r for r in records if r["fires"]]
    res = residual_stats(fired, B=B, seed=SEED)
    verdict = ("INTERIM (no verdict before the final read)" if not final
               else ("SUPPORTED" if res.get("p_one_sided") is not None and res["p_one_sided"] <= ALPHA else "NOT SUPPORTED"))
    return {"final_read": final, "counts": dict(counts), "signal": SIGNAL, "threshold": THRESHOLDS["saves_opp_sf_high"],
            "primary_residual_over": res, "secondary_roi_best_us_over": roi(fired, B=B, seed=SEED) if fired else {"n": 0},
            "context_all_saves_over": residual_stats(records, B=600, seed=SEED), "verdict": verdict}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data-root", default=os.environ.get("SYNDICATE_DATA_ROOT") or "")
    ap.add_argument("--through", default=None, help="last game day to grade (default: FINAL_READ)")
    ap.add_argument("--ignore-registration-time", action="store_true", help="format check on pre-registration games")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    if not args.data_root:
        print("REFUSING: no --data-root", flush=True)
        return 2
    through = min(args.through or FINAL_READ, FINAL_READ)
    counts: dict[str, int] = defaultdict(int)
    records = collect(Path(os.path.expanduser(args.data_root)), through, args.ignore_registration_time, counts)
    final = through >= FINAL_READ and not args.ignore_registration_time and any(r["day"] >= "2027-04-01" for r in records)
    rep = report(records, final=final, counts=counts)
    rep["through"], rep["records"] = through, records
    Path(args.out).write_text(json.dumps(rep, indent=1, default=str), encoding="utf-8")
    p, r, c = rep["primary_residual_over"], rep["secondary_roi_best_us_over"], rep["context_all_saves_over"]
    print(f"S1F through={through} final={final} counts={rep['counts']}", flush=True)
    print(f"  fired n={p.get('n')} g={p.get('games')} hit={p.get('hit_rate')} p={p.get('mean_p')} resid={p.get('residual')} "
          f"ci={p.get('ci95')} p1={p.get('p_one_sided')} | ROI best over={r.get('roi_pct')} {r.get('ci95')} | {rep['verdict']}",
          flush=True)
    print(f"  context: every graded saves line, over residual={c.get('residual')} n={c.get('n')}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
