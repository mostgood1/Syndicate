"""Grade H7 -- the NBA UNDER combination -- forward on the 2026-27 regular season, exactly as pre-registered.

Lane `signal-engine-nba`. Pre-registration: lane block "H7 PRE-REGISTERED 2026-10-13" + "H7 CLARIFICATION" (before any
2026-27 regular-season outcome existed). Nothing here is tuned on 2026-27 data; the constants below ARE the registration.

THE BET (per game date, regular season from the 2026-10-20 opener):
  1. Per book, the latest prop snapshot at or before tip-off minus 45 min (PRICE_SOURCES, first that has the line).
  2. Main line per (event, market, player): the point quoted TWO-SIDED by the most books (tie -> median Shin p_over
     nearest 0.5).
  3. Markets: player_threes, player_rebounds, player_rebounds_assists, player_assists ONLY.
  4. Player prior-10 mean MIN >= 30, from the as-of signal table for that date (`nba_source/signals/<season>/`).
  5. Bet the UNDER at the BEST price among US sportsbooks quoting that main line two-sided.
  6. Outcome from the season's player game log (regular season); DNP / missing -> void; push -> void.
PRIMARY: flat 1-unit ROI at that price, bootstrapped over games. SECONDARY: residual vs the median per-book Shin fair.

H7-LATE (lane block "H7-LATE PRE-REGISTERED", 2026-10-13, before any 2026-27 outcome): the identical bet restricted to
games dated 2027-02-01..2027-04-11 -- in 2025-26 the effect lived only in Feb-Apr.

BAR (the family rule, which replaced H7's single-test "95% CI above 0" when H7-late was added): each hypothesis's
one-sided p = (#{game-clustered bootstrap ROI <= 0} + 1) / (B + 1), B = 2000, seed 20261013; Holm at family-wise
one-sided alpha 0.025 -- the smaller p must be <= 0.0125, the other <= 0.025. Read ONCE, at the FINAL read (through
2027-04-11). Any read before that is INTERIM: reported, no verdict, no stopping.

Consequences of the registration, not choices made here: the tier is the as-of table's `min_prior10`, the mean of UP TO
the last 10 games of THIS season's log -- so opening night grades nothing (no prior game) and the first weeks rest on
fewer than 10 games, exactly as the 2025-26 tables behind H6b did. Price files are keyed by slate date; a line whose
tip-off falls on another US-Central date is counted (`other_date_line`) and not graded.

    python3 scripts/grade_h7_nba_unders.py --data-root ~/syndicate-prod/data --through 2027-01-31 --out h7.json
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import os
import random
import statistics
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
for _p in (REPO_ROOT, REPO_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from build_nba_signals import build_as_of, load_espn  # noqa: E402
from syndicate.features.shared.matchup_signals import norm_player, read_signal_table, residual_stats  # noqa: E402
from syndicate.features.shared.opportunity_signals import devig  # noqa: E402

# ---- the registration (do not edit after 2026-10-13) ----------------------------------------------------------------
SEASON = "2026-27"
SEASON_START_YEAR = 2026
OPENER = "2026-10-20"
FINAL_READ = "2027-04-11"
MARKETS = ("player_threes", "player_rebounds", "player_rebounds_assists", "player_assists")
MIN_PRIOR10 = 30.0
SNAPSHOT_LEAD = timedelta(minutes=45)
LATE_START = "2027-02-01"   # H7-late: the same bet on games 2027-02-01..FINAL_READ (registered 2026-10-13)
FAMILY_ALPHA = 0.025        # Holm over {H7, H7-late}, family-wise one-sided -- read ONCE, at the final read
BOOTSTRAP_B = 2000
BOOTSTRAP_SEED = 20261013
US_BOOKS = frozenset({
    "draftkings", "fanduel", "betmgm", "williamhill_us", "betrivers", "fanatics", "espnbet", "hardrockbet", "ballybet",
    "betparx", "fliff", "bovada", "betonlineag", "mybookieag", "betus", "lowvig",
})
MARKET_STATS = {"player_threes": ("FG3M",), "player_rebounds": ("REB",), "player_assists": ("AST",),
                "player_rebounds_assists": ("REB", "AST")}
# ----------------------------------------------------------------------------------------------------------------------


def _ts(v: Any) -> datetime | None:
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def central_date(commence: datetime) -> str:
    """US Central calendar date of a tip-off (CDT/CST by the US rule is close enough at day resolution: -5 h)."""
    return (commence - timedelta(hours=5)).date().isoformat()


def decimal(price: float) -> float:
    return 1.0 + price / 100.0 if price > 0 else 1.0 + 100.0 / -price


def _rows_csv(path: Path) -> Iterable[dict[str, Any]]:
    with path.open(encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            yield {"snapshot_ts": r.get("snapshot_ts"), "event_id": r.get("event_id"), "commence_time": r.get("commence_time"),
                   "bookmaker": r.get("bookmaker"), "market": r.get("market"), "side": r.get("outcome_name"),
                   "player_name": r.get("player_name"), "point": r.get("point"), "price": r.get("price")}


def _rows_book_quotes(path: Path) -> Iterable[dict[str, Any]]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            q = json.loads(line)
            if q.get("kind") != "prop":
                continue
            yield {"snapshot_ts": q.get("captured_at"), "event_id": q.get("event_id"), "commence_time": q.get("commence_time"),
                   "bookmaker": q.get("bookmaker"), "market": q.get("market"), "side": q.get("selection"),
                   "player_name": q.get("player_name"), "point": q.get("line"), "price": q.get("price")}


def price_rows(data_root: Path, day: str) -> tuple[str | None, list[dict[str, Any]]]:
    """The first PRICE_SOURCE (registration order) that has any H7-market row for `day`."""
    nba = data_root / "nba_source"
    candidates = [
        ("props_history", nba / "data" / "raw" / f"odds_nba_player_props_history_{day}.csv", _rows_csv),
        ("props_snapshot", nba / "data" / "raw" / f"odds_nba_player_props_{day}.csv", _rows_csv),
        ("book_quotes", nba / "tracking" / "book_quotes" / f"{day}.jsonl.gz", _rows_book_quotes),
        ("book_quotes", nba / "tracking" / "book_quotes" / f"{day}.jsonl", _rows_book_quotes),
    ]
    for name, path, reader in candidates:
        if not path.is_file():
            continue
        rows = [r for r in reader(path) if r.get("market") in MARKETS]
        if rows:
            return name, rows
    return None, []


def main_lines(rows: Iterable[Mapping[str, Any]], *, change_log: bool = False, lead: timedelta = SNAPSHOT_LEAD,
               fair_books: frozenset[str] | None = None) -> list[dict[str, Any]]:
    """Each book's LAST quote before the cutoff, then the main line per (event, market, player) with the best US under.

    Tip-off is the EARLIEST commence_time seen for the event: OddsAPI rewrites commence_time to the actual start once a
    game is live (measured 2026-10-05: 02:00:00Z scheduled, 02:10:53Z on the in-play rows), so a per-row cutoff would
    move with it.

    "Last quote" per (event, market, player, book) = the points present at that book's latest observation <= cutoff. In a
    SNAPSHOT file (props CSVs) every side must be in that snapshot; a point the book has since dropped is gone. The
    `book_quotes` CHANGE LOG appends only on a price change and never records a removal, so there a point counts if
    observed at the book's latest capture, and a side that did not change is carried forward from its last value.

    `lead` and `fair_books` exist for the rebounds-unders forward grader (tip - 10 min; the fair over US books +
    Pinnacle only); their defaults are H7's registration exactly (tip - 45 min; the fair over every two-sided book)."""
    rows = list(rows)
    commence_of: dict[str, datetime] = {}
    for r in rows:
        commence = _ts(r.get("commence_time"))
        event = str(r.get("event_id") or "")
        if commence is not None and event and (event not in commence_of or commence < commence_of[event]):
            commence_of[event] = commence
    last: dict[tuple, tuple[datetime, float]] = {}  # (event, market, player, book, point, side) -> (ts, price)
    book_ts: dict[tuple, datetime] = {}              # (event, market, player, book) -> latest observation <= cutoff
    for r in rows:
        snap, event = _ts(r.get("snapshot_ts")), str(r.get("event_id") or "")
        side = str(r.get("side") or "").strip().lower()
        try:
            point, price = float(r.get("point")), float(r.get("price"))
        except (TypeError, ValueError):
            continue
        if snap is None or event not in commence_of or side not in ("over", "under") or snap > commence_of[event] - lead:
            continue
        bk = (event, r["market"], norm_player(r.get("player_name")), str(r.get("bookmaker") or "").lower())
        key = bk + (point, side)
        if key not in last or snap >= last[key][0]:
            last[key] = (snap, price)
        if bk not in book_ts or snap > book_ts[bk]:
            book_ts[bk] = snap
    current_points = {k[:5] for k, (ts, _) in last.items() if ts == book_ts[k[:4]]}
    by_point: dict[tuple, dict[str, dict[str, float]]] = defaultdict(lambda: defaultdict(dict))
    for (event, market, player, book, point, side), (ts, price) in last.items():
        if (event, market, player, book, point) not in current_points:
            continue
        if not change_log and ts != book_ts[(event, market, player, book)]:
            continue
        by_point[(event, market, player, point)][book][side] = price
    candidates: dict[tuple, list[dict[str, Any]]] = defaultdict(list)
    for (event, market, player, point), books in by_point.items():
        two = {b: s for b, s in books.items() if "over" in s and "under" in s}
        fairs = [f[0] for f in (devig([s["over"], s["under"]], method="shin") for b, s in two.items()
                                if fair_books is None or b in fair_books) if f]
        if not fairs:
            continue
        us_unders = [s["under"] for b, s in two.items() if b in US_BOOKS]
        candidates[(event, market, player)].append({
            "event": event, "market": market, "player_key": player, "point": point, "books": len(fairs),
            "p_over": statistics.median(fairs),
            "best_us_under": max(us_unders, key=decimal) if us_unders else None,
            "date": central_date(commence_of[event])})
    out = []
    for cands in candidates.values():
        cands.sort(key=lambda c: (-c["books"], abs(c["p_over"] - 0.5)))
        out.append(cands[0])
    return out


def load_outcomes(path: Path) -> dict[tuple[str, str], dict[str, float]]:
    out: dict[tuple[str, str], dict[str, float]] = {}
    if not path.is_file():
        return out
    with path.open(encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            if (r.get("season_type") or "regular").strip().lower() not in ("regular", "regular season", ""):
                continue
            try:
                stats = {k: float(r[k]) for k in ("FG3M", "REB", "AST", "MIN")}
            except (TypeError, ValueError, KeyError):
                continue
            out[(norm_player(r.get("PLAYER_NAME")), str(r.get("date") or "")[:10])] = stats
    return out


def roi(rows: list[Mapping[str, Any]], B: int = BOOTSTRAP_B, seed: int = BOOTSTRAP_SEED) -> dict[str, Any]:
    """Flat-stake ROI with a game-clustered bootstrap: 95% CI and the one-sided p = (#{boot ROI <= 0} + 1) / (B + 1)."""
    if not rows:
        return {"n": 0, "p_one_sided": None}
    groups: dict[str, list] = defaultdict(list)
    for r in rows:
        groups[r["game"]].append(r)
    keys = list(groups)
    rng = random.Random(seed)
    boots = []
    if len(keys) >= 5:
        for _ in range(B):
            sample = [r for _ in keys for r in groups[rng.choice(keys)]]
            boots.append(100 * sum(r["pnl"] for r in sample) / len(sample))
        boots.sort()
    return {"n": len(rows), "games": len(keys), "roi_pct": round(100 * sum(r["pnl"] for r in rows) / len(rows), 2),
            "ci95": [round(boots[int(0.025 * B)], 2), round(boots[int(0.975 * B) - 1], 2)] if boots else None,
            "p_one_sided": round((sum(1 for b in boots if b <= 0) + 1) / (B + 1), 5) if boots else None}


def holm(pvals: Mapping[str, float | None], alpha: float = FAMILY_ALPHA) -> dict[str, bool]:
    """Holm step-down at family-wise one-sided `alpha`; a missing p (too few games) counts as 1.0 -- never supported."""
    ordered = sorted(pvals, key=lambda k: 1.0 if pvals[k] is None else pvals[k])
    out = {k: False for k in pvals}
    for i, k in enumerate(ordered):
        p = 1.0 if pvals[k] is None else pvals[k]
        if p > alpha / (len(ordered) - i):
            break
        out[k] = True
    return out


def tiers_for(data_root: Path, day: str, espn: tuple[list, dict] | None, counts: dict[str, int]) -> dict[str, Any]:
    """player_key -> min_prior10 from the as-of table the daily `nba-signals` job wrote. A date the job missed is rebuilt
    with that job's own function (`build_nba_signals.build_as_of`, games strictly before `day`) and counted."""
    rows = read_signal_table(data_root, "nba", SEASON, day)
    if not rows and espn is not None:
        rows = build_as_of(espn[0], espn[1], {}, day)
        counts["signal_tables_rebuilt"] += 1
    return {r["player_key"]: r.get("min_prior10") for r in rows}


def grade(data_root: Path, through: str) -> dict[str, Any]:
    through = min(through, FINAL_READ)
    log_path = data_root / "nba_source" / "data" / "processed" / f"player_game_log_{SEASON_START_YEAR}.csv"
    outcomes = load_outcomes(log_path)
    espn = load_espn(log_path) if log_path.is_file() else None
    counts: dict[str, int] = defaultdict(int)
    sources: dict[str, int] = defaultdict(int)
    bets: list[dict[str, Any]] = []
    day = date.fromisoformat(OPENER)
    end = date.fromisoformat(through)
    while day <= end:
        d = day.isoformat()
        day += timedelta(days=1)
        source, rows = price_rows(data_root, d)
        if source is None:
            counts["dates_without_prices"] += 1
            continue
        sources[source] += 1
        tiers = tiers_for(data_root, d, espn, counts)
        for line in main_lines(rows, change_log=(source == "book_quotes")):
            if line["date"] != d:
                counts["other_date_line"] += 1
                continue
            counts["main_lines"] += 1
            if line["best_us_under"] is None:
                counts["no_us_book"] += 1
                continue
            if line["player_key"] not in tiers:
                counts["no_signal_row"] += 1
                continue
            if (tiers[line["player_key"]] or 0) < MIN_PRIOR10:
                counts["below_min30"] += 1
                continue
            res = outcomes.get((line["player_key"], d))
            if res is None or (res.get("MIN") or 0) <= 0:
                counts["void_dnp_or_missing"] += 1
                continue
            value = sum(res[c] for c in MARKET_STATS[line["market"]])
            if value == line["point"]:
                counts["void_push"] += 1
                continue
            y = 1.0 if value < line["point"] else 0.0
            pnl = (decimal(line["best_us_under"]) - 1.0) if y else -1.0
            bets.append({"date": d, "game": line["event"], "market": line["market"], "player": line["player_key"],
                         "point": line["point"], "price": line["best_us_under"], "y": y, "p": 1.0 - line["p_over"], "pnl": pnl})
            counts["graded"] += 1
    final = through >= FINAL_READ
    late = [b for b in bets if b["date"] >= LATE_START]
    primary, primary_late = roi(bets), roi(late)
    family = {"method": "holm", "alpha_one_sided": FAMILY_ALPHA,
              "p_one_sided": {"H7": primary["p_one_sided"], "H7_late": primary_late["p_one_sided"]}}
    if final:
        family["supported"] = holm(family["p_one_sided"])
    interim = "INTERIM (no verdict before the final read)"
    verdict_of = lambda name: interim if not final else ("SUPPORTED" if family["supported"][name] else "NOT SUPPORTED")  # noqa: E731
    return {
        "season": SEASON, "through": through, "final_read": final, "verdict": verdict_of("H7"),
        "primary_roi_best_us_price": primary,
        "secondary_residual_vs_shin": residual_stats(bets) if bets else {"n": 0},
        "by_market": {m: roi([b for b in bets if b["market"] == m], B=400) for m in MARKETS},
        "h7_late": {"verdict": verdict_of("H7_late"), "window": [LATE_START, FINAL_READ],
                    "primary_roi_best_us_price": primary_late,
                    "secondary_residual_vs_shin": residual_stats(late) if late else {"n": 0},
                    "by_market": {m: roi([b for b in late if b["market"] == m], B=400) for m in MARKETS}},
        "family": family,
        "counts": dict(counts), "price_sources_by_date": dict(sources),
        "registration": {"markets": MARKETS, "min_prior10": MIN_PRIOR10, "snapshot_lead_min": 45,
                         "us_books": sorted(US_BOOKS), "opener": OPENER, "late_start": LATE_START,
                         "final_read": FINAL_READ, "bootstrap_b": BOOTSTRAP_B, "bootstrap_seed": BOOTSTRAP_SEED},
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data-root", default=os.environ.get("SYNDICATE_DATA_ROOT") or "")
    ap.add_argument("--through", default=None, help="last game date to grade (default: yesterday, US Central)")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    if not args.data_root:
        print("REFUSING: no --data-root", flush=True)
        return 2
    through = args.through or (datetime.now(timezone.utc) - timedelta(hours=5) - timedelta(days=1)).date().isoformat()
    report = grade(Path(os.path.expanduser(args.data_root)), through)
    Path(args.out).write_text(json.dumps(report, indent=1), encoding="utf-8")
    for name, block in (("H7", report), ("H7-late", report["h7_late"])):
        p = block["primary_roi_best_us_price"]
        print(f"{name} {block['verdict']} through={report['through']} n={p.get('n')} games={p.get('games')} "
              f"ROI={p.get('roi_pct')} ci={p.get('ci95')} p={p.get('p_one_sided')}", flush=True)
    print(f"counts={report['counts']} sources={report['price_sources_by_date']}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
