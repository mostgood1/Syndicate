"""NCAAF weekly recommendation summary: `recommendations_summary/week_<N>.json` + `index.json`.

WHY (lane `intelligence-evidence-coverage`, goal item 5; user 2026-10-08 "build the NCAAF
recommendation-summary producer"). The NCAAF cards and picks pages fall back to these files, the
archive lists them, and the intelligence readiness gate requires "Weekly recommendation summary" and
"Recommendation index" -- but nothing on the fleet has written one since the source app was retired
(no file exists on the fleet, the git mirror or the primary tree). Everything a row needs is already
computed on the fleet:
  * the week's games -- `smartsim2_projections_<season>_wk<N>.csv`;
  * per game x market (h2h / spreads / totals, full game): the newest NCAAF book grid row
    (`data/book_grid/book_grid_<date>.json`), carrying every book's price per side AND the joined
    SmartSim2 projection (`projection.model_prob_over` for `projection.side`, its basis, and its
    MEASURED skill verdict).

Per side: model_prob, the best price across non-stale books (provider, American price, line),
implied_prob of that price, edge = model_prob - implied_prob, and a quarter-Kelly stake on a $100 base
(0 when the edge is <= 0). The model's own skill verdict is copied onto every row and into the summary
-- on 2026-10-08 it reads "loses to the closing line" for both sides and totals, and a summary row must
not present an edge without saying so.

    python scripts/build_ncaaf_recommendation_summary.py                 # newest projections week
    python scripts/build_ncaaf_recommendation_summary.py --week 6 --season 2026
    python scripts/build_ncaaf_recommendation_summary.py --all-weeks
"""

from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

MARKET_LABEL = {"h2h": "ML", "spreads": "SPREAD", "totals": "TOTAL"}
KELLY_FRACTION = 0.25
# A quote counts toward "best price" only when it is near the market: within this many probability
# points of the median implied probability across the books quoting that side, and >= 2 books quote it.
# Measured 2026-10-08 week 6: an exchange (novig) at +19900 (0.5% implied) on a side the books priced at
# ~45% topped the list as a 44-point "edge" -- a stale / no-liquidity quote, not a price.
MAX_GAP_FROM_MEDIAN = 0.10
MIN_BOOKS = 2
BANKROLL = 100.0


def ncaaf_data_dir() -> Path:
    override = str(os.environ.get("SYNDICATE_NCAAF_SOURCE_ROOT") or "").strip()
    root = Path(override) if override else Path(os.environ.get("SYNDICATE_DATA_ROOT", str(REPO / "data"))) / "ncaaf_source"
    return root / "data"


def _decimal(american: Any) -> float | None:
    try:
        a = float(american)
    except (TypeError, ValueError):
        return None
    if a >= 100:
        return 1.0 + a / 100.0
    if a <= -100:
        return 1.0 + 100.0 / -a
    return None


def _canon(name: Any) -> str:
    from syndicate.features.shared.team_aliases import canonical_team

    text = str(name or "").strip()
    return canonical_team("ncaaf", text) or text.lower()


def week_games(path: Path) -> dict[tuple[str, str], dict[str, str]]:
    import csv

    with path.open(encoding="utf-8", newline="") as handle:
        return {(_canon(r["home_team"]), _canon(r["away_team"])): r for r in csv.DictReader(handle)}


def newest_rows(grids: Iterable[Mapping[str, Any]], games: Mapping[tuple[str, str], Any]) -> dict[tuple, dict[str, Any]]:
    """(home, away, market) -> the newest full-game row for this week's games (grids newest first)."""
    out: dict[tuple, dict[str, Any]] = {}
    for grid in grids:
        for row in grid.get("rows") or []:
            if row.get("kind") != "game" or str(row.get("segment") or "full") != "full":
                continue
            market = str(row.get("market") or "")
            if market not in MARKET_LABEL:
                continue
            key = (_canon(row.get("home_team")), _canon(row.get("away_team")))
            if key in games and (key + (market,)) not in out:
                out[key + (market,)] = row
    return out


def side_rows(row: Mapping[str, Any]) -> list[dict[str, Any]]:
    """One result per side of one market row: model prob, best price, implied prob, edge, stake."""
    proj = row.get("projection") if isinstance(row.get("projection"), Mapping) else {}
    p = proj.get("model_prob_over")
    if p is None:
        return []
    market = str(row["market"])
    home, away = str(row.get("home_team") or ""), str(row.get("away_team") or "")
    if market == "totals":
        prob = {"over": float(p), "under": 1.0 - float(p)}
    else:
        named_home = _canon(proj.get("side")) == _canon(home)
        prob = {"home": float(p) if named_home else 1.0 - float(p), "away": 1.0 - float(p) if named_home else float(p)}
    skill = proj.get("model_skill") if isinstance(proj.get("model_skill"), Mapping) else {}
    try:
        row_line = float(row.get("line"))
    except (TypeError, ValueError):
        row_line = None
    want_line = None
    if row_line is not None:
        # Spreads arrive in the AWAY frame (book_grid._canonical_line, `#262`): `line` is the away
        # team's line L, and game_projections prices P(home margin > L) -- home covering at -L.
        want_line = ({"over": row_line, "under": row_line} if market == "totals"
                     else {"away": row_line, "home": -row_line})
    out = []
    for side, model_prob in prob.items():
        quotes = []
        for book, cell in (row.get("cells") or {}).items():
            quote = (cell or {}).get(side) or {}
            dec = _decimal(quote.get("price"))
            if dec is None or quote.get("stale"):
                continue
            # The model's probability is AT THE ROW'S LINE; a quote on another line is another bet.
            if market != "h2h" and want_line is not None:
                try:
                    if abs(float(quote.get("line")) - want_line[side]) > 1e-9:
                        continue
                except (TypeError, ValueError):
                    continue
            quotes.append((dec, book, quote.get("price"), quote.get("line")))
        if len(quotes) < MIN_BOOKS:
            continue
        implied_all = sorted(1.0 / q[0] for q in quotes)
        mid = implied_all[len(implied_all) // 2] if len(implied_all) % 2 else (implied_all[len(implied_all) // 2 - 1] + implied_all[len(implied_all) // 2]) / 2
        sane = [q for q in quotes if abs(1.0 / q[0] - mid) <= MAX_GAP_FROM_MEDIAN]
        best = max(sane, key=lambda q: q[0]) if sane else None
        if best is None:
            continue
        dec, book, price, line = best
        implied = 1.0 / dec
        edge = model_prob - implied
        kelly = (model_prob * dec - 1.0) / (dec - 1.0) if dec > 1 else 0.0
        label = {"home": home, "away": away, "over": "Over", "under": "Under"}[side]
        out.append({
            "home_team": home, "away_team": away, "commence_time": row.get("commence_time"),
            "event_id": row.get("event_id"), "market": MARKET_LABEL[market],
            "side": label if line is None else f"{label} {line:+g}" if market == "spreads" else f"{label} {line:g}",
            "line": line, "provider": book, "price_american": price, "model_prob": round(model_prob, 4),
            "implied_prob": round(implied, 4), "edge": round(edge, 4),
            "stake": round(max(0.0, KELLY_FRACTION * kelly) * BANKROLL, 2) if edge > 0 else 0.0,
            "projected": proj.get("projected"), "model_basis": proj.get("basis"),
            "model_skill_verdict": skill.get("verdict"), "books_quoting": len(quotes),
            "market_median_implied": round(mid, 4),
        })
    return out


def build_week(season: int, week: int, *, data_dir: Path | None = None, max_grid_files: int = 10) -> dict[str, Any]:
    data_dir = data_dir or ncaaf_data_dir()
    proj = data_dir / f"smartsim2_projections_{season}_wk{week}.csv"
    if not proj.is_file():
        raise SystemExit(f"no projections for {season} week {week}: {proj}")
    games = week_games(proj)
    files = sorted(glob.glob(str(data_dir / "book_grid" / "book_grid_????-??-??.json")), reverse=True)[:max_grid_files]
    grids = (json.loads(Path(f).read_text(encoding="utf-8")) for f in files)
    rows = newest_rows(grids, games)
    results = [r for row in rows.values() for r in side_rows(row)]
    results.sort(key=lambda r: (-(r["edge"] or 0.0), r["home_team"], r["market"]))
    verdicts = sorted({(r["market"], r["model_skill_verdict"]) for r in results if r.get("model_skill_verdict")})
    summary = {
        "schema": "ncaaf_recommendation_summary_v2", "season": season, "week": week,
        "generated_utc": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "source": {"projections": proj.name, "book_grids": [Path(f).name for f in files]},
        "games_in_week": len(games), "games_with_prices": len({(r["home_team"], r["away_team"]) for r in results}),
        "model_skill": [{"market": m, "verdict": v} for m, v in verdicts],
        "stake_rule": f"{KELLY_FRACTION:g} Kelly on a ${BANKROLL:g} base, 0 when edge <= 0",
        "results": results,
    }
    out_dir = data_dir / "recommendations_summary"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"week_{week}.json"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(summary), encoding="utf-8")
    os.replace(tmp, path)
    _update_index(out_dir, season, week, path, len(results))
    print(f"[ncaaf_summary] WEEK season={season} week={week} games={len(games)} priced_games={summary['games_with_prices']} "
          f"rows={len(results)} positive_edge={sum(1 for r in results if r['edge'] > 0)} -> {path}", flush=True)
    return summary


def _update_index(out_dir: Path, season: int, week: int, path: Path, count: int) -> None:
    index_path = out_dir / "index.json"
    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        index = {}
    weeks = [w for w in (index.get("weeks") or []) if isinstance(w, dict) and int(w.get("week") or -1) != week]
    weeks.append({"week": week, "season": season, "count": count, "path": str(path),
                  "fetch": {"rc": 0, "source": "book_grid + smartsim2_projections (build_ncaaf_recommendation_summary.py)"}})
    index.update(weeks=sorted(weeks, key=lambda w: int(w["week"])),
                 generated_utc=dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"))
    tmp = index_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(index, indent=1), encoding="utf-8")
    os.replace(tmp, index_path)


def _available(data_dir: Path) -> list[tuple[int, int]]:
    found = []
    for f in glob.glob(str(data_dir / "smartsim2_projections_*_wk*.csv")):
        m = re.search(r"smartsim2_projections_(\d{4})_wk(\d+)\.csv$", f)
        if m:
            found.append((int(m.group(1)), int(m.group(2))))
    return sorted(found)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--season", type=int, default=None)
    parser.add_argument("--week", type=int, default=None)
    parser.add_argument("--all-weeks", action="store_true", help="every projections week of the newest season")
    args = parser.parse_args(argv)
    data_dir = ncaaf_data_dir()
    available = _available(data_dir)
    if not available:
        raise SystemExit(f"no smartsim2 projections under {data_dir}")
    season = args.season or available[-1][0]
    weeks = [w for s, w in available if s == season]
    for week in (weeks if args.all_weeks else [args.week or weeks[-1]]):
        build_week(season, week, data_dir=data_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
