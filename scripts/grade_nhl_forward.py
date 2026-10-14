"""Grade the NHL skater signals FORWARD on 2026-27, exactly as pre-registered (lane `signal-engine-nhl`).

Family (Holm at family-wise one-sided ALPHA, read once at FINAL_READ):
  K1 nhl.toi_up               OVER  SOG / points when TOI last 3 - base >= toi_up
  K2 nhl.toi_down             UNDER SOG / points when TOI last 3 - base <= -toi_down
  K3 nhl.opp_allows_shots     OVER  SOG when the opponent's shots against per game >= opp_sa_high
  K4 nhl.opp_suppresses_shots UNDER SOG when the opponent's shots against per game <= opp_sa_low
  K5 nhl.skater_under_bias    UNDER every main-line two-sided SOG / points / assists / goals prop

GAMES     regular season (gamePk 2026020xxx), scheduled start after REGISTERED_AT, game day <= FINAL_READ.
PRICES    the fleet quote logs `nhl_source/tracking/book_quotes/<date>.jsonl[.gz]` (append-on-change), the files dated
          game day - 2 .. game day + 1; per book the last observation at or before start - 10 min (the football grader's
          `close_main_lines`); fair = median per-book Shin over the US books + Pinnacle; price = the best US book.
FEATURES  `matchup_signals_nhl.AsOf` over `raw/player_game_stats.csv` (2026-27 regular season, games before the day).
OUTCOMES  the player's row in that game (first initial + surname inside the two teams); none -> void; pushes void.
PRIMARY   residual on the signal's side vs the Shin fair, game-clustered bootstrap B 2000 seed 20261014, one-sided
          p = (#boot <= 0 + 1) / (B + 1). SECONDARY: flat ROI at the best US price.

  --mode distributions  the K1-K4 thresholds from 2025-26 game-log FEATURES (no prices, no outcomes)
  --mode grade          the test (INTERIM before FINAL_READ is graded)
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

from grade_football_fade_leads import close_main_lines, quotes_path  # noqa: E402,F401
from grade_h7_nba_unders import US_BOOKS, holm, roi  # noqa: E402
from signal_lift_football import _read_jsonl, decimal  # noqa: E402
from syndicate.features.shared.matchup_signals import residual_stats  # noqa: E402
from syndicate.features.shared.matchup_signals_nhl import (  # noqa: E402
    NHL_MARKET_STATS,
    NHL_REGISTRY,
    SKATER_MARKETS,
    THRESHOLDS,
    AsOf,
    load_game_log,
    name_key,
    skater_eligible,
    skater_fires,
)

# ---- the registration -------------------------------------------------------------------------------------------------
REGISTERED_AT = datetime(2026, 10, 14, 1, 16, tzinfo=timezone.utc)  # the lane-block registration
SEASON = "2026"
FINAL_READ = "2026-12-31"
SEED, B, ALPHA = 20261014, 2000, 0.025
FAIR_BOOKS = US_BOOKS | {"pinnacle"}
FAMILY = {
    "K1": ("nhl.toi_up", ("shots", "points")),
    "K2": ("nhl.toi_down", ("shots", "points")),
    "K3": ("nhl.opp_allows_shots", ("shots",)),
    "K4": ("nhl.opp_suppresses_shots", ("shots",)),
    "K5": ("nhl.skater_under_bias", SKATER_MARKETS),
}
# ----------------------------------------------------------------------------------------------------------------------


def _raw(root: Path) -> Path:
    return root / "nhl_source" / "source_artifacts" / "data" / "raw"


def distributions(root: Path) -> dict[str, Any]:
    """K1-K4 feature quantiles on 2025-26 (features only): skater-games of regulars (season TOI >= 12 min) and
    team-games (opponent shots against per game, >= 5 games)."""
    log = load_game_log([_raw(root) / "player_game_log_20252026.csv"])
    asof = AsOf(log)
    trends, opp_sa = [], []
    for r in asof.rows:
        if r["role"] == "goalie":
            continue
        f = asof.skater(r["player_id"], "2025", r["date"])
        if f and f["toi_trend"] is not None and f["toi_season"] >= 12.0:
            trends.append(f["toi_trend"])
    seen = set()
    for team, games in asof.by_team.items():
        for t in games:
            if (t["opponent"], t["date"]) in seen:
                continue
            seen.add((t["opponent"], t["date"]))
            f = asof.team(t["opponent"], "2025", t["date"])
            if f and f.get("sa_pg") is not None:
                opp_sa.append(f["sa_pg"])

    def q(v):
        v = sorted(v)
        pick = lambda x: round(v[min(len(v) - 1, int(x * len(v)))], 3)  # noqa: E731
        return {"n": len(v), "p10": pick(0.10), "p50": pick(0.50), "p90": pick(0.90)} if v else {"n": 0}

    return {"toi_trend_regulars": q(trends), "opp_sa_pg": q(opp_sa)}


def collect(root: Path, final_read: str, ignore_registration: bool, counts: dict[str, int]) -> list[dict[str, Any]]:
    from syndicate.features.shared.team_aliases import canonical_team

    log = [r for r in load_game_log([_raw(root) / "player_game_stats.csv"]) if r["season"] == SEASON]
    asof = AsOf(log)
    by_game_key: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    games_by_day: dict[tuple[str, frozenset], str] = {}
    teams_in: dict[str, set[str]] = defaultdict(set)
    for r in asof.rows:
        by_game_key[(r["game"], r["key"])].append(r)
        teams_in[r["game"]].add(r["team"])
    for game, teams in teams_in.items():
        day = next(r["date"] for r in asof.rows if r["game"] == game)
        games_by_day[(day, frozenset(canonical_team("nhl", t) for t in teams))] = game
    graded_days = {r["date"] for r in asof.rows}
    records = []
    first = (REGISTERED_AT - timedelta(days=1)).date().isoformat()
    if ignore_registration and graded_days:  # a format check reads the season from its first game
        first = min(graded_days)
    day = date.fromisoformat(first)
    seen_lines: set[tuple] = set()
    while day.isoformat() <= final_read:
        d = day.isoformat()
        day += timedelta(days=1)
        if d not in graded_days:
            continue
        rows = []
        for k in (-2, -1, 0, 1):
            path = _quotes_for(root, (date.fromisoformat(d) + timedelta(days=k)).isoformat())
            if path is not None:
                rows += _read_jsonl(path)
        for line in close_main_lines(rows, books=FAIR_BOOKS, price_books=US_BOOKS, market_stats=NHL_MARKET_STATS):
            if line["stat"] not in SKATER_MARKETS:
                continue
            ident = (line["event"], line["stat"], line["player"])
            if ident in seen_lines:
                continue
            if not ignore_registration and line["kickoff"] <= REGISTERED_AT:
                counts["pre_registration_start"] += 1
                seen_lines.add(ident)
                continue
            teams = frozenset(canonical_team("nhl", str(line.get(k) or "")) for k in ("home_team", "away_team"))
            # A line belongs to the game on ITS OWN start date (Eastern game day), never to the day being walked:
            # files d-2..d+1 are read and a home-and-home puts the same two clubs on consecutive days
            # (correction 2026-10-14, before any window game was graded).
            if (line["kickoff"] - timedelta(hours=5)).date().isoformat() != d:
                continue
            game = games_by_day.get((d, teams))
            if game is None:
                continue  # another day's game: graded on its own day
            seen_lines.add(ident)
            match = by_game_key.get((game, name_key(line["player"])), [])
            if len(match) != 1 or line["best_under"] is None:
                counts["void_no_outcome_or_no_us_price"] += 1
                continue
            row = match[0]
            value = float(row[line["stat"]])
            if value == line["point"]:
                counts["void_push"] += 1
                continue
            sk = asof.skater(row["player_id"], SEASON, d) or {}
            opp = next((t for t in teams_in[game] if t != row["team"]), None)
            opp_f = asof.team(opp, SEASON, d) if opp else None
            feats = {"toi_trend": sk.get("toi_trend"), "opp_sa_pg": (opp_f or {}).get("sa_pg")}
            records.append({"day": d, "game": game, "stat": line["stat"], "player": line["player"], "point": line["point"],
                            "y_over": 1.0 if value > line["point"] else 0.0, "p_over": line["p_over"],
                            "best_under": line["best_under"], "feats": feats})
            counts["graded"] += 1
    return records


def _quotes_for(root: Path, day: str) -> Path | None:
    base = root / "nhl_source" / "tracking" / "book_quotes" / f"{day}.jsonl"
    for path in (base, base.with_name(base.name + ".gz")):
        if path.is_file():
            return path
    return None


def hypothesis_rows(records: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {h: [] for h in FAMILY}
    for r in records:
        fires = set(skater_fires(r["feats"]))
        for h, (name, stats) in FAMILY.items():
            if r["stat"] not in stats:
                continue
            if h != "K5" and name not in fires:
                continue
            side = NHL_REGISTRY[name].side
            y = r["y_over"] if side == "over" else 1.0 - r["y_over"]
            p = r["p_over"] if side == "over" else 1.0 - r["p_over"]
            row = {"game": r["game"], "y": y, "p": p, "day": r["day"]}
            if side == "under":
                row["pnl"] = (decimal(r["best_under"]) - 1.0) if y else -1.0
            out[h].append(row)
    return out


def report(records: list[dict[str, Any]], *, final: bool, counts: Mapping[str, int]) -> dict[str, Any]:
    rows = hypothesis_rows(records)
    out: dict[str, Any] = {"final_read": final, "counts": dict(counts), "hypotheses": {}}
    pvals = {}
    for h, (name, stats) in FAMILY.items():
        res = residual_stats(rows[h], B=B, seed=SEED)
        priced = [r for r in rows[h] if "pnl" in r]
        out["hypotheses"][h] = {"signal": name, "markets": stats, "side": NHL_REGISTRY[name].side, "residual": res,
                                "roi_best_us_under": roi(priced, B=B, seed=SEED) if priced else {"n": 0}}
        pvals[h] = res.get("p_one_sided")
    if final:
        out["holm"] = holm(pvals, alpha=ALPHA)
    for h in FAMILY:
        out["hypotheses"][h]["verdict"] = ("INTERIM (no verdict before the final read)" if not final
                                           else ("SUPPORTED" if out["holm"][h] else "NOT SUPPORTED"))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data-root", default=os.environ.get("SYNDICATE_DATA_ROOT") or "")
    ap.add_argument("--mode", choices=("distributions", "grade"), required=True)
    ap.add_argument("--through", default=None, help="last game day to grade (default: FINAL_READ)")
    ap.add_argument("--ignore-registration-time", action="store_true", help="format check on pre-registration games")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    if not args.data_root:
        print("REFUSING: no --data-root", flush=True)
        return 2
    root = Path(os.path.expanduser(args.data_root))
    if args.mode == "distributions":
        rep: dict[str, Any] = distributions(root)
    else:
        if not all(THRESHOLDS[k] for k in ("toi_up", "toi_down", "opp_sa_high", "opp_sa_low")):
            print("REFUSING: skater thresholds are not registered yet", flush=True)
            return 3
        through = min(args.through or FINAL_READ, FINAL_READ)
        counts: dict[str, int] = defaultdict(int)
        records = collect(root, through, args.ignore_registration_time, counts)
        final = through >= FINAL_READ and not args.ignore_registration_time and any(r["day"] >= FINAL_READ for r in records)
        rep = report(records, final=final, counts=counts)
        rep["through"] = through
    Path(args.out).write_text(json.dumps(rep, indent=1, default=str), encoding="utf-8")
    if args.mode == "distributions":
        print(json.dumps(rep), flush=True)
    else:
        print(f"NHL_FORWARD through={rep['through']} final={rep['final_read']} counts={rep['counts']}", flush=True)
        for h, e in rep["hypotheses"].items():
            s, r = e["residual"], e["roi_best_us_under"]
            print(f"  {h} {e['signal']:24s} {e['side']:5s} n={s.get('n')} g={s.get('games')} resid={s.get('residual')} "
                  f"ci={s.get('ci95')} p1={s.get('p_one_sided')} | ROI={r.get('roi_pct')} | {e['verdict']}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
