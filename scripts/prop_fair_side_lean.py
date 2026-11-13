"""Does the board's two-sided PROP fair lean toward the over -- and why?  (lane `prop-fair-side-lean`, 2026-11-13)

The cheat-sheet section assessment (`findings_2026-11-13_cheat_sheet_section_assessment.md` §2) found NBA prop overs
hitting ~4 pts below the board's fair. On the board's own graded population (`score_ranking_backtest.py pull` rows,
the suggested-grade pulls 10-17..11-08) the NBA lean is -3.36 pts [-4.97, -1.70] over 56,428 over rows / 146 games,
flat across markets, fair levels, pricing books and date halves. This script rebuilds each graded row's fair from the
RAW book quotes, so the mechanism can be read rather than assumed.

  extract   for every graded pregame two-sided prop (consensus fair, y in {0, 1}), each book's last two-sided price
            at the sighting (`fair_price_eval`'s windows: <= --max-age-h old) and at the close (its last pregame
            quote, <= --max-stale-h before commence). Per book: the hold, the price asymmetry, and the OVER's fair
            under several de-vigs -- multiplicative, power, Shin (PRODUCTION `opportunity_signals.devig`), and the two
            one-sided readings `under_face` (the under's price taken as fair, all the margin on the over) and
            `over_face` (the reverse). The consensus of each is the median over books, as the board takes it.
  analyze   the over's lean (y - p_over) per sport, per method, at the sighting and the close; its dependence on the
            hold and on which side is juiced; a sharp book's own fair; each with a 95% interval by GAME.

Every row is framed on the OVER of its group, once per group, so a graded over and its graded under are one bet.

    nice -n 19 python3 scripts/prop_fair_side_lean.py extract --graded props.jsonl.gz \
        --data-root ~/syndicate-prod/data --sports nba,nfl --out quotes_rows.jsonl.gz
    python3 scripts/prop_fair_side_lean.py analyze --rows quotes_rows.jsonl.gz
"""
from __future__ import annotations

import argparse
import gzip
import importlib.util
import json
import random
import statistics
import sys
from collections import defaultdict
from datetime import timedelta
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.shared.opportunity_signals import devig, implied_probability  # noqa: E402

METHODS = ("mult", "power", "shin", "under_face", "over_face")
_DEVIG = {"mult": "multiplicative", "power": "power", "shin": "shin"}
SHARP_BOOKS = ("pinnacle",)
BOOT = 1000
SEED = 20261113


def _fpe() -> Any:
    spec = importlib.util.spec_from_file_location("fair_price_eval", REPO_ROOT / "scripts" / "fair_price_eval.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _open(path: Path, mode: str = "rt"):
    return gzip.open(path, mode, encoding="utf-8") if str(path).endswith(".gz") else open(path, mode, encoding="utf-8")


def side_of(value: Any) -> str | None:
    s = str(value or "").strip().lower()
    return "over" if s in ("over", "yes") else "under" if s in ("under", "no") else None


# ----------------------------------------------------------------------------- per book


def book_over_fairs(over_price: Any, under_price: Any) -> dict[str, float] | None:
    """One book's two-sided price -> the OVER's fair under each method, its hold and its asymmetry.

    None when the book's hold is one production refuses (`devig` returns nothing) -- the board drops such a book."""
    io, iu = implied_probability(over_price), implied_probability(under_price)
    if io is None or iu is None:
        return None
    out: dict[str, float] = {}
    for m, name in _DEVIG.items():
        fair = devig([over_price, under_price], method=name)
        if not fair:
            return None
        out[m] = float(fair[0])
    out["under_face"] = 1.0 - iu
    out["over_face"] = io
    out["hold"] = io + iu - 1.0
    out["asym"] = io - iu          # > 0: the over is the juiced (shorter) side
    return out


def consensus(per_book: Mapping[str, Mapping[str, float]]) -> dict[str, Any] | None:
    """Median over books of each method's over-fair, the hold and the asymmetry (the board's consensus shape)."""
    if not per_book:
        return None
    out: dict[str, Any] = {k: statistics.median(v[k] for v in per_book.values()) for k in (*METHODS, "hold", "asym")}
    out["books"] = sorted(per_book)
    return out


def prices_at(history: Mapping[str, Mapping[str, Sequence[tuple]]], *, t: Any, max_age_h: float, max_stale_h: float,
              ) -> tuple[dict[str, dict[str, float]], dict[str, dict[str, float]]]:
    """book -> {side: price} at the sighting `t` and at the close, with `fair_price_eval`'s age windows."""
    sight: dict[str, dict[str, float]] = defaultdict(dict)
    close: dict[str, dict[str, float]] = defaultdict(dict)
    for book, sides in history.items():
        for side, h in sides.items():
            prior = [x for x in h if t is not None and x[0] <= t and t - x[0] <= timedelta(hours=max_age_h)]
            if prior:
                sight[book][side] = prior[-1][1]
            last = h[-1]
            if last[2] - last[0] <= timedelta(hours=max_stale_h):
                close[book][side] = last[1]
    return sight, close


def fairs_from(prices: Mapping[str, Mapping[str, float]]) -> tuple[dict[str, Any] | None, dict[str, dict[str, float]]]:
    per_book = {}
    for book, sides in prices.items():
        if "over" in sides and "under" in sides:
            f = book_over_fairs(sides["over"], sides["under"])
            if f:
                per_book[book] = f
    return consensus(per_book), per_book


# ----------------------------------------------------------------------------- extract


def load_graded(path: Path, sports: set[str]) -> list[dict[str, Any]]:
    """Graded pregame two-sided props, one row per group (the over's frame). A group whose only graded row is the
    under is kept, its outcome flipped -- the over lost exactly when the under won."""
    by_group: dict[tuple, dict[str, Any]] = {}
    with _open(path) as fh:
        for line in fh:
            r = json.loads(line)
            sport, _, event = str(r.get("game") or "").partition("|")
            side = side_of(r.get("side"))
            if (sport not in sports or not event or r.get("phase") != "pregame" or not r.get("player")
                    or r.get("fm") != "consensus" or r.get("y") not in (0.0, 1.0) or side is None or not r.get("t")
                    or not isinstance(r.get("fp"), (int, float))):
                continue
            key = (sport, event, r.get("market"), r.get("segment"), str(r.get("player")).casefold(), r.get("line"))
            framed = {"sport": sport, "event_id": event, "game": r["game"], "date": r.get("date"), "market": r.get("market"),
                      "segment": r.get("segment"), "player": r.get("player"), "line": r.get("line"), "t": r["t"],
                      "y_over": r["y"] if side == "over" else 1.0 - r["y"],
                      "fp_over": float(r["fp"]) if side == "over" else 1.0 - float(r["fp"])}
            held = by_group.get(key)
            if held is None or (side == "over" and held.get("_side") != "over"):
                framed["_side"] = side
                by_group[key] = framed
    return list(by_group.values())


def extract(rows: list[dict[str, Any]], data_root: Path, *, max_age_h: float, max_stale_h: float,
            read_quotes: Callable[..., Mapping[tuple, list[tuple]]] | None = None) -> list[dict[str, Any]]:
    fpe = _fpe()
    read_quotes = read_quotes or fpe.read_quotes
    out: list[dict[str, Any]] = []
    for sport in sorted({r["sport"] for r in rows}):
        mine = [r for r in rows if r["sport"] == sport]
        for r in mine:
            r["gkey"] = fpe.group_key(r["event_id"], r["market"], r["segment"], r["player"], "over", r["line"])
        hist = read_quotes(data_root, sport, {r["event_id"] for r in mine}, {r["gkey"] for r in mine})
        by_group: dict[tuple, dict[str, dict[str, list[tuple]]]] = defaultdict(lambda: defaultdict(dict))
        for (g, book, side), h in hist.items():
            sd = side_of(side)
            if sd:
                by_group[g][book][sd] = sorted(h, key=lambda x: x[0])
        kept = 0
        for r in mine:
            sight_px, close_px = prices_at(by_group.get(r["gkey"], {}), t=fpe.ts(r["t"]), max_age_h=max_age_h,
                                           max_stale_h=max_stale_h)
            sight, sight_books = fairs_from(sight_px)
            if sight is None:
                continue
            close, close_books = fairs_from(close_px)
            rec = {k: r[k] for k in ("sport", "game", "date", "market", "player", "line", "t", "y_over", "fp_over")}
            rec["sight"] = sight
            rec["close"] = close
            rec["sharp_sight"] = {b: sight_books[b]["shin"] for b in SHARP_BOOKS if b in sight_books}
            rec["sharp_close"] = {b: close_books[b]["shin"] for b in SHARP_BOOKS if b in close_books}
            out.append(rec)
            kept += 1
        print(f"EXTRACT {sport} graded groups {len(mine)} with a sighting fair {kept}", flush=True)
    return out


# ----------------------------------------------------------------------------- analyze


def boot_mean(values_by_game: Sequence[Sequence[float]], *, B: int = BOOT, seed: int = SEED) -> tuple[float, float] | None:
    """95% interval of the pooled mean, resampling GAMES (props of one game move together)."""
    groups = [list(v) for v in values_by_game if v]
    if len(groups) < 2:
        return None
    rng = random.Random(seed)
    n, means = len(groups), []
    for _ in range(B):
        s = c = 0.0
        for _ in range(n):
            g = groups[rng.randrange(n)]
            s += sum(g)
            c += len(g)
        means.append(s / c)
    means.sort()
    return means[int(0.025 * B)], means[int(0.975 * B) - 1]


def lean(rows: Iterable[Mapping[str, Any]], fair: Callable[[Mapping[str, Any]], float | None]) -> dict[str, Any] | None:
    """Mean of (y_over - fair) in points, with its interval by game."""
    by_game: dict[Any, list[float]] = defaultdict(list)
    for r in rows:
        p = fair(r)
        if p is not None:
            by_game[r["game"]].append(r["y_over"] - p)
    n = sum(len(v) for v in by_game.values())
    if not n:
        return None
    ci = boot_mean(list(by_game.values()))
    return {"n": n, "games": len(by_game), "pts": round(100 * sum(map(sum, by_game.values())) / n, 2),
            "ci": [round(100 * ci[0], 2), round(100 * ci[1], 2)] if ci else None}


def slope_on(rows: Sequence[Mapping[str, Any]], x: Callable[[Mapping[str, Any]], float | None],
             fair: Callable[[Mapping[str, Any]], float | None], *, B: int = BOOT, seed: int = SEED) -> dict[str, Any] | None:
    """OLS slope of (y_over - fair) on x, in points per unit of x, with its interval by game."""
    pts = [(r["game"], x(r), r["y_over"] - p) for r in rows if (p := fair(r)) is not None and x(r) is not None]
    if len(pts) < 30:
        return None

    def fit(sample: Iterable[tuple]) -> float | None:
        xs, ys = zip(*[(a, b) for _, a, b in sample]) if sample else ((), ())
        if len(xs) < 3:
            return None
        mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
        sxx = sum((a - mx) ** 2 for a in xs)
        return None if sxx <= 0 else sum((a - mx) * (b - my) for a, b in zip(xs, ys)) / sxx

    by_game: dict[Any, list[tuple]] = defaultdict(list)
    for p in pts:
        by_game[p[0]].append(p)
    games = list(by_game.values())
    rng = random.Random(seed)
    draws = []
    for _ in range(B):
        sample = [p for _ in games for p in games[rng.randrange(len(games))]]
        s = fit(sample)
        if s is not None:
            draws.append(s)
    draws.sort()
    point = fit(pts)
    return {"n": len(pts), "games": len(games), "slope_pts": None if point is None else round(100 * point, 2),
            "ci": [round(100 * draws[int(0.025 * len(draws))], 2), round(100 * draws[int(0.975 * len(draws)) - 1], 2)]
            if draws else None}


def _at(when: str, method: str) -> Callable[[Mapping[str, Any]], float | None]:
    return lambda r: (r.get(when) or {}).get(method)


def analyze(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for sport in sorted({r["sport"] for r in rows}):
        mine = [r for r in rows if r["sport"] == sport]
        both = [r for r in mine if r.get("close")]
        rep: dict[str, Any] = {
            "groups": len(mine),
            "reconstruction": {"board_fp": lean(mine, lambda r: r["fp_over"]),
                               "abs_diff_shin_vs_board_median_pts": round(100 * statistics.median(
                                   abs(r["sight"]["shin"] - r["fp_over"]) for r in mine), 2)},
            "sighting": {m: lean(mine, _at("sight", m)) for m in METHODS},
            "close_same_rows": {m: lean(both, _at("close", m)) for m in METHODS},
            "sighting_same_rows": {"shin": lean(both, _at("sight", "shin"))},
            "hold_slope_shin": slope_on(mine, lambda r: r["sight"]["hold"], _at("sight", "shin")),
            "by_hold": {}, "by_juiced_side": {}, "by_books": {}, "sharp": {},
        }
        for lo, hi in ((0.0, 0.05), (0.05, 0.07), (0.07, 0.09), (0.09, 0.11), (0.11, 1.0)):
            rep["by_hold"][f"{lo:.2f}-{hi:.2f}"] = lean([r for r in mine if lo <= r["sight"]["hold"] < hi], _at("sight", "shin"))
        for label, cond in (("over juiced (asym > +0.02)", lambda a: a > 0.02), ("even (|asym| <= 0.02)", lambda a: abs(a) <= 0.02),
                            ("under juiced (asym < -0.02)", lambda a: a < -0.02)):
            rep["by_juiced_side"][label] = lean([r for r in mine if cond(r["sight"]["asym"])], _at("sight", "shin"))
        for label, cond in (("1 book", lambda n: n == 1), ("2 books", lambda n: n == 2), ("3-4 books", lambda n: 3 <= n <= 4),
                            ("5+ books", lambda n: n >= 5)):
            rep["by_books"][label] = lean([r for r in mine if cond(len(r["sight"]["books"]))], _at("sight", "shin"))
        for book in SHARP_BOOKS:
            have = [r for r in mine if book in (r.get("sharp_sight") or {})]
            rep["sharp"][book] = {"own_fair": lean(have, lambda r, b=book: r["sharp_sight"][b]),
                                  "consensus_same_rows": lean(have, _at("sight", "shin"))}
        out[sport] = rep
    return out


# ----------------------------------------------------------------------------- pull (the forward read's input)


class LocalReader:
    """`score_ranking_backtest`'s web reader, swapped for the data root's own disk (the fleet: one shared disk)."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def text(self, relative: str) -> str | None:
        path = self.root / relative
        return path.read_text(encoding="utf-8") if path.is_file() else None


def _srb() -> Any:
    spec = importlib.util.spec_from_file_location("score_ranking_backtest_pfsl", REPO_ROOT / "scripts" / "score_ranking_backtest.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def prop_records(texts: Iterable[str | None], parse: Callable[[str], list[dict[str, Any]]],
                 identity: Callable[[str], Mapping[str, Any] | None]) -> list[dict[str, Any]]:
    """Opportunity-lane PROP records (a player in the key) from population parts -- the suggested-grade 'all' set."""
    out = []
    for text in texts:
        for r in parse(text or ""):
            if r.get("ln") == "opportunity" and (identity(str(r.get("k") or "")) or {}).get("player_name"):
                out.append(r)
    return out


def pull(data_root: Path, *, start: str, end: str, sports: Sequence[str], out: Path, cache: Path) -> dict[str, Any]:
    """Grade every opportunity-lane prop record sighted on `start`..`end` whose kickoff is on or before `end`, with
    `score_ranking_backtest.grade_rows` -- the grader, settlers and selection rule the suggested-grade pulls use."""
    from datetime import date as date_cls

    srb = _srb()
    bs = srb.msc.load_bucket_search()
    pub = srb._load_publisher()
    reader = LocalReader(data_root)

    def parts():
        for day in srb._days(start, end):
            for sport in sports:
                for part in range(bs.MAX_PARTS):
                    text = reader.text(f"reports/intelligence/{bs.POPULATION_SUBDIR}/{day}__{sport}__part{part:03d}.jsonl")
                    if text is None:
                        break
                    yield text

    records = prop_records(parts(), bs.parse_records_text, srb.parse_population_key)
    print(f"RECORDS props {len(records)} {start}..{end} sports={list(sports)}", flush=True)

    from syndicate.features.mlb.prop_outcomes import MlbPropGrader
    from syndicate.features.shared.population_outcomes import build_extra_settler

    cache.mkdir(parents=True, exist_ok=True)
    mlb = MlbPropGrader(cache_dir=cache / "statsapi")
    settler = build_extra_settler(cache_dir=cache / "settlers", fetch_export=reader.text)
    bs.SCORECARD.index_chips = srb.stable_chip_index(bs.SCORECARD.index_chips)
    chip_lists: dict[str, list[Any]] = {}

    def chips_for(day: str) -> list[Any]:
        if day not in chip_lists:
            local = cache / "chips" / f"{day}.json"
            if local.exists():
                chip_lists[day] = json.loads(local.read_text(encoding="utf-8"))
            else:
                chip_lists[day] = pub.fetch_chips_with_retry(bs, day)
                local.parent.mkdir(parents=True, exist_ok=True)
                local.write_text(json.dumps(chip_lists[day]), encoding="utf-8")
        return chip_lists[day]

    def grade(recs, chips_by_date, named, *, today):
        return bs.grade_population(recs, chips_by_date, named, today=today, prop_settler=mlb.settle,
                                   score_source=mlb.final_score, extra_settler=settler)

    today = (date_cls.fromisoformat(end) + timedelta(days=1)).isoformat()
    rows, reasons = srb.grade_rows(records, grade=grade, chips_for=chips_for, central_date=bs.SCORECARD.central_date,
                                   today=today)
    with _open(out, "wt") as fh:
        for r in rows:
            fh.write(json.dumps(dict(r, kind="prop")) + "\n")
    summary = {"records": len(records), "graded": len(rows), "reasons": dict(reasons.most_common(10)), "out": str(out)}
    print(f"PULL {json.dumps(summary)}", flush=True)
    return summary


def holdout(rows: Sequence[Mapping[str, Any]], *, sport: str, fit: tuple[str, str] | None, test: tuple[str, str],
            delta: float | None = None) -> dict[str, Any] | None:
    """The registered check: a shift FITTED on `fit` dates (or a frozen `delta`) scored on `test` dates by log loss.

    dLL < 0 is better; its interval is by game. Rows are the over-framed groups `load_graded` returns."""
    from syndicate.features.shared import prop_fair_side as pfs

    mine = [r for r in rows if r["sport"] == sport]
    if delta is None:
        assert fit is not None
        fitted = pfs.fit_delta((r["fp_over"], r["y_over"]) for r in mine if fit[0] <= str(r["date"]) <= fit[1])
        if not fitted:
            return None
        delta = float(fitted["delta"])
    scored = [r for r in mine if test[0] <= str(r["date"]) <= test[1]]
    if not scored:
        return None
    gain: dict[Any, list[float]] = defaultdict(list)
    for r in scored:
        gain[r["game"]].append(pfs.log_loss(pfs.shift(r["fp_over"], delta), r["y_over"]) - pfs.log_loss(r["fp_over"], r["y_over"]))
    ci = boot_mean(list(gain.values()))
    n = sum(len(v) for v in gain.values())
    return {"sport": sport, "delta": round(delta, 4), "fit": list(fit) if fit else None, "test": list(test),
            "lean_before": lean(scored, lambda r: r["fp_over"]),
            "lean_after": lean(scored, lambda r, d=delta: pfs.shift(r["fp_over"], d)),
            "dll": round(sum(map(sum, gain.values())) / n, 6), "dll_ci": [round(ci[0], 6), round(ci[1], 6)] if ci else None,
            "passes": bool(ci and ci[1] < 0)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    ex = sub.add_parser("extract")
    ex.add_argument("--graded", required=True)
    ex.add_argument("--data-root", required=True)
    ex.add_argument("--sports", default="nba,nfl")
    ex.add_argument("--out", required=True)
    ex.add_argument("--max-age-h", type=float, default=12.0)
    ex.add_argument("--max-stale-h", type=float, default=6.0)
    an = sub.add_parser("analyze")
    an.add_argument("--rows", required=True)
    an.add_argument("--json", default=None)
    ho = sub.add_parser("holdout", help="the registered log-loss check of the side shift")
    ho.add_argument("--graded", required=True, nargs="+", help="graded pulls (jsonl[.gz]); groups are de-duplicated")
    ho.add_argument("--sports", default="nba,nfl,nhl,ncaaf")
    ho.add_argument("--fit", default=None, help="FROM..TO kickoff dates the shift is fitted on")
    ho.add_argument("--delta", type=float, default=None, help="a FROZEN shift instead of a fit (forward reads)")
    ho.add_argument("--test", required=True, help="FROM..TO kickoff dates it is scored on")
    pl = sub.add_parser("pull", help="grade the board's prop population from the data root's own disk")
    pl.add_argument("--data-root", required=True)
    pl.add_argument("--start", required=True, help="first SIGHTING date (population part) -- a day before the first kickoff")
    pl.add_argument("--end", required=True, help="last kickoff date graded")
    pl.add_argument("--sports", default="nba,nfl")
    pl.add_argument("--out", required=True)
    pl.add_argument("--cache", default=None)
    args = ap.parse_args(argv)
    if args.cmd == "pull":
        out = Path(args.out).expanduser()
        pull(Path(args.data_root).expanduser(), start=args.start, end=args.end,
             sports=[s.strip() for s in args.sports.split(",") if s.strip()], out=out,
             cache=Path(args.cache).expanduser() if args.cache else out.parent / "pull_cache")
        return 0
    if args.cmd == "holdout":
        sports = {s.strip() for s in args.sports.split(",") if s.strip()}
        seen: dict[tuple, dict[str, Any]] = {}
        for path in args.graded:
            for r in load_graded(Path(path), sports):
                seen.setdefault((r["game"], r["market"], r["segment"], str(r["player"]).casefold(), r["line"]), r)
        fit = tuple(args.fit.split("..")) if args.fit else None
        test = tuple(args.test.split(".."))
        for sport in sorted(sports):
            print(json.dumps(holdout(list(seen.values()), sport=sport, fit=fit, test=test, delta=args.delta)), flush=True)
        return 0
    if args.cmd == "extract":
        rows = load_graded(Path(args.graded), {s.strip() for s in args.sports.split(",") if s.strip()})
        print(f"GRADED groups {len(rows)}", flush=True)
        out = extract(rows, Path(args.data_root).expanduser(), max_age_h=args.max_age_h, max_stale_h=args.max_stale_h)
        with _open(Path(args.out), "wt") as fh:
            for r in out:
                fh.write(json.dumps(r) + "\n")
        print(f"WROTE {len(out)} -> {args.out}", flush=True)
        return 0
    rows = [json.loads(line) for line in _open(Path(args.rows))]
    result = analyze(rows)
    print(json.dumps(result, indent=1))
    if args.json:
        Path(args.json).write_text(json.dumps(result, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
