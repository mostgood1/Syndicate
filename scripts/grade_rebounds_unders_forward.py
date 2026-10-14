"""Grade R1 -- REBOUNDS UNDERS -- forward on the 2026-27 NBA and 2027 WNBA regular seasons, exactly as pre-registered.

Lane `signal-engine-nba` (user 2026-10-14: "yes register the rebounds unders forward test"). The lead: rebounds unders
held in both halves of the bought 2026 WNBA season (+3.0% / +2.4%) and were a per-market survivor of NBA H6 (+1.7%), but
neither result survived its multiplicity correction. Two hypotheses, read independently, Bonferroni-split:

  R1-NBA   UNDER on every main-line `player_rebounds` prop, 2026-27 NBA regular season, final read after 2027-04-11
  R1-WNBA  the same on the 2027 WNBA regular season, final read after 2027-09-30
  bar      each: one-sided p <= 0.0125 (family-wise 0.025) on the residual y_under - p_under (Shin fair), game-clustered
           bootstrap B 2000 seed 20261014, p = (#boot <= 0 + 1) / (B + 1). SECONDARY: flat ROI at the best US under.

PRICES   per league, the first source with any rebounds row for the slate date: `<sport>_source/data/raw/
         odds_<sport>_player_props_history_<date>.csv`, else `odds_<sport>_player_props_<date>.csv`, else
         `<sport>_source/tracking/book_quotes/<date>.jsonl[.gz]` (the H7 order). Per book the LAST quote at or before tip
         - 10 min (`grade_h7_nba_unders.main_lines`, change-log rule for the log); main line per (event, player) = most
         two-sided books (tie -> Shin p nearest 0.5); fair = median per-book Shin over the US books + Pinnacle (prediction
         markets and exchanges excluded); price = the best US book.
OUTCOME  the ESPN game log `<sport>_source/data/processed/player_game_log_<season start>.csv`, regular-season rows only
         (playoff and All-Star rows never join); no row or 0 minutes -> void; push -> void.
GAMES    game day in the league window and tip after REGISTERED_AT. Earlier reads are INTERIM.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import os
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]
for _p in (REPO_ROOT, REPO_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import grade_h7_nba_unders as h7  # noqa: E402
from syndicate.features.shared.matchup_signals import residual_stats  # noqa: E402

# ---- the registration -------------------------------------------------------------------------------------------------
REGISTERED_AT = datetime(2026, 10, 14, 3, 13, tzinfo=timezone.utc)  # the lane-block registration
LEAGUES = {
    "R1-NBA": {"sport": "nba", "log": "player_game_log_2026.csv", "start": "2026-10-20", "final": "2027-04-11"},
    "R1-WNBA": {"sport": "wnba", "log": "player_game_log_2027.csv", "start": "2027-05-01", "final": "2027-09-30"},
}
MARKET = "player_rebounds"
LEAD = timedelta(minutes=10)
FAIR_BOOKS = h7.US_BOOKS | {"pinnacle"}
ALPHA_EACH = 0.0125
SEED, B = 20261014, 2000
# ----------------------------------------------------------------------------------------------------------------------


def _rows_csv(path: Path) -> Iterable[dict[str, Any]]:
    """H7's CSV reader plus the two clubs (H7 never needed them)."""
    with path.open(encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            yield {"snapshot_ts": r.get("snapshot_ts"), "event_id": r.get("event_id"), "commence_time": r.get("commence_time"),
                   "bookmaker": r.get("bookmaker"), "market": r.get("market"), "side": r.get("outcome_name"),
                   "player_name": r.get("player_name"), "point": r.get("point"), "price": r.get("price"),
                   "home_team": r.get("home_team"), "away_team": r.get("away_team")}


def _rows_book_quotes(path: Path) -> Iterable[dict[str, Any]]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            q = json.loads(line)
            if q.get("kind") != "prop":
                continue
            yield {"snapshot_ts": q.get("captured_at"), "event_id": q.get("event_id"), "commence_time": q.get("commence_time"),
                   "bookmaker": q.get("bookmaker"), "market": q.get("market"), "side": q.get("selection"),
                   "player_name": q.get("player_name"), "point": q.get("line"), "price": q.get("price"),
                   "home_team": q.get("home_team"), "away_team": q.get("away_team")}


def price_rows(root: Path, sport: str, day: str) -> tuple[str | None, list[dict[str, Any]]]:
    raw = root / f"{sport}_source" / "data" / "raw"
    bq = root / f"{sport}_source" / "tracking" / "book_quotes"
    candidates = [
        ("props_history", raw / f"odds_{sport}_player_props_history_{day}.csv", _rows_csv),
        ("props_snapshot", raw / f"odds_{sport}_player_props_{day}.csv", _rows_csv),
        ("book_quotes", bq / f"{day}.jsonl.gz", _rows_book_quotes),
        ("book_quotes", bq / f"{day}.jsonl", _rows_book_quotes),
    ]
    for name, path, reader in candidates:
        if path.is_file():
            rows = [r for r in reader(path) if r.get("market") == MARKET]
            if rows:
                return name, rows
    return None, []


def grade_league(root: Path, name: str, through: str, counts: dict[str, int]) -> list[dict[str, Any]]:
    from syndicate.features.shared.team_aliases import canonical_team

    cfg = LEAGUES[name]
    sport = cfg["sport"]
    outcomes = h7.load_outcomes(root / f"{sport}_source" / "data" / "processed" / cfg["log"])
    rows_out = []
    day, end = date.fromisoformat(cfg["start"]), date.fromisoformat(min(through, cfg["final"]))
    while day <= end:
        d = day.isoformat()
        day += timedelta(days=1)
        source, rows = price_rows(root, sport, d)
        if source is None:
            continue
        counts[f"{name}:{source}_days"] += 1
        meta: dict[str, tuple] = {}
        for r in rows:
            meta.setdefault(str(r.get("event_id")), (r.get("commence_time"), r.get("home_team"), r.get("away_team")))
        for line in h7.main_lines(rows, change_log=(source == "book_quotes"), lead=LEAD, fair_books=FAIR_BOOKS):
            if line["date"] != d:
                continue
            commence, home, away = meta.get(line["event"], (None, None, None))
            if not (canonical_team(sport, home) and canonical_team(sport, away)):
                counts[f"{name}:not_two_league_clubs"] += 1  # e.g. an All-Star game, which the ESPN log labels regular
                continue
            tip = h7._ts(commence)
            if tip is not None and tip <= REGISTERED_AT:
                counts[f"{name}:pre_registration"] += 1
                continue
            if line["best_us_under"] is None:
                counts[f"{name}:no_us_price"] += 1
                continue
            res = outcomes.get((line["player_key"], d))
            if res is None or (res.get("MIN") or 0) <= 0:
                counts[f"{name}:void_dnp_or_missing"] += 1
                continue
            if res["REB"] == line["point"]:
                counts[f"{name}:void_push"] += 1
                continue
            y = 1.0 if res["REB"] < line["point"] else 0.0
            rows_out.append({"league": name, "date": d, "game": line["event"], "player": line["player_key"],
                             "point": line["point"], "y": y, "p": round(1.0 - line["p_over"], 5),
                             "price": line["best_us_under"],
                             "pnl": (h7.decimal(line["best_us_under"]) - 1.0) if y else -1.0})
            counts[f"{name}:graded"] += 1
    return rows_out


def report(rows: list[dict[str, Any]], through: str, counts: dict[str, int]) -> dict[str, Any]:
    out: dict[str, Any] = {"through": through, "counts": dict(counts), "hypotheses": {}}
    for name, cfg in LEAGUES.items():
        rs = [r for r in rows if r["league"] == name]
        res = residual_stats(rs, B=B, seed=SEED)
        final = through >= cfg["final"] and any(r["date"] >= cfg["final"][:7] for r in rs)
        verdict = ("INTERIM (no verdict before the final read)" if not final
                   else ("SUPPORTED" if res.get("p_one_sided") is not None and res["p_one_sided"] <= ALPHA_EACH
                         else "NOT SUPPORTED"))
        out["hypotheses"][name] = {"residual_under": res, "roi_best_us_under": h7.roi(rs, B=B, seed=SEED) if rs else {"n": 0},
                                   "final_read": final, "alpha": ALPHA_EACH, "verdict": verdict}
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data-root", default=os.environ.get("SYNDICATE_DATA_ROOT") or "")
    ap.add_argument("--through", default=None, help="last game day (default: yesterday, US Central)")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    if not args.data_root:
        print("REFUSING: no --data-root", flush=True)
        return 2
    through = args.through or (datetime.now(timezone.utc) - timedelta(hours=5) - timedelta(days=1)).date().isoformat()
    root = Path(os.path.expanduser(args.data_root))
    counts: dict[str, int] = defaultdict(int)
    rows = [r for name in LEAGUES for r in grade_league(root, name, through, counts)]
    rep = report(rows, through, counts)
    Path(args.out).write_text(json.dumps(rep, indent=1), encoding="utf-8")
    print(f"R1 through={through} counts={rep['counts']}", flush=True)
    for name, e in rep["hypotheses"].items():
        s, r = e["residual_under"], e["roi_best_us_under"]
        print(f"  {name:8s} n={s.get('n')} g={s.get('games')} hit={s.get('hit_rate')} p={s.get('mean_p')} "
              f"resid={s.get('residual')} ci={s.get('ci95')} p1={s.get('p_one_sided')} | ROI={r.get('roi_pct')} | "
              f"{e['verdict']}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
