# -*- coding: utf-8 -*-
"""H36, forward, paper: the published live corners number vs the in-play book, same line, same moment.

Lane `soccer-live-corners-book-test`. The rules are the registration, not this file:
`.syndicate/log/2026-09-18.md` ~10:54 CT (`ca9e46fc`). No bet is placed on anything this measures.

    item        one in-play `alternate_totals_corners` quote: (capture, book, line), BOTH sides priced, 0-130 min
                after `commence_time`
    join        to an ESPN match by `team_names.canonical_team_name` on BOTH names, same league, kickoff within
                30 min, exactly one candidate; unmatched is counted, never guessed. AMENDED before any qualifying
                capture: registered as the live pricer's exact key (`soccer_live_gameline_source._norm`), which
                joined 21 of 38 real in-play events against 34 for the canonical name (0 wrong fixtures). Whether
                the pricer's key would ALSO have matched is kept per item and reported.
    as-of       the LAST harvested row of that match at or before the book's `book_updated_at`, at most 600 s
                before it, with `corners_basis=prekickoff_pace_v1`. AMENDED 2026-09-18 before any outcome existed:
                registered as 180 s on an assumed ~60 s tick, but the live loop's ticks run 2-6 min apart once
                several matches are in play (measured from `projection_history`), so 180 s would drop a share of
                the supply that has nothing to do with the match. The registered 180 s subset is reported beside.
    ours        P(so_far + R > line), R ~ Poisson(projected_total_corners - so_far)   (H35's law)
    book        that book's two-sided price, de-vigged proportionally
    filters     settled lines (so_far > line) out; book probability outside [0.05, 0.95] out; ESPN final required
    metric      mean log-loss(ours) - log-loss(book); match-clustered bootstrap 2000 / seed 11 / 95%
    verdict     SUPPORTED iff the CI lies entirely below 0; graded at 150 matches or 2026-11-15; INSUFFICIENT if
                fewer by then

    py -3 scripts/soccer_season_audit/live_corners_book_grade.py pull  --harvest <dir> --cache <dir> [--env-root <dir>]
    py -3 scripts/soccer_season_audit/live_corners_book_grade.py grade --harvest <dir> --cache <dir> [--today YYYY-MM-DD]

`--harvest` is H32's harvest (`live_projections_<date>.jsonl`); `--cache` holds `espn/` (shared with H32's grader)
and `book_quotes/`. `grade` never touches the network.
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import math
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CHECKOUT = HERE.parents[1]
for p in (str(HERE), str(CHECKOUT)):
    if p not in sys.path:
        sys.path.insert(0, p)

MARKET = "alternate_totals_corners"
IN_PLAY_MINUTES = (0.0, 130.0)
KICKOFF_TOLERANCE = dt.timedelta(minutes=30)
ROW_WINDOW = dt.timedelta(seconds=600)
REGISTERED_WINDOW_S = 180.0      # the original rule, kept as a reported sensitivity
BOOK_P_RANGE = (0.05, 0.95)
LIVE_BASIS = "prekickoff_pace_v1"
CLIP = 1e-6
EDGES = (0.03, 0.05)
MINUTE_BUCKETS = ((0.0, 30.0), (30.0, 60.0), (60.0, 1e9))
GRADE_MATCHES = 150
GRADE_DATE = dt.date(2026, 11, 15)


# ---------------------------------------------------------------------------- prices (pure)

def devig_over(over_price, under_price) -> float | None:
    from syndicate.features.soccer.features.market_odds import american_to_probability  # noqa: E402

    po, pu = american_to_probability(over_price), american_to_probability(under_price)
    if po is None or pu is None or po + pu <= 0:
        return None
    return po / (po + pu)


def poisson_over(so_far: float, projected_total: float, line: float) -> float:
    """P(so_far + R > line) with R ~ Poisson(projected_total - so_far)."""
    need = int(math.floor(line - so_far)) + 1
    if need <= 0:
        return 1.0
    mu = max(float(projected_total) - so_far, 1e-9)
    cdf = sum(math.exp(-mu + i * math.log(mu) - math.lgamma(i + 1)) for i in range(need))
    return min(1.0, max(0.0, 1.0 - cdf))


def log_loss(p: float, happened: bool) -> float:
    p = min(1.0 - CLIP, max(CLIP, p))
    return -math.log(p if happened else 1.0 - p)


def settle(price, won: bool) -> float:
    """Profit of 1 u at an American price."""
    value = float(price)
    return (value / 100.0 if value > 0 else 100.0 / -value) if won else -1.0


# ---------------------------------------------------------------------------- quotes, join, as-of (pure)

def quote_items(rows, funnel: collections.Counter) -> list[dict]:
    """(odds event, captured_at, book, line) with BOTH sides, in play. The pair is only valid from the LATER of
    its two sides' `book_updated_at`."""
    from common import ts  # noqa: E402

    groups: dict = {}
    for r in rows:
        if r.get("market") != MARKET:
            continue
        ko, ca, bu = ts(r.get("commence_time")), ts(r.get("captured_at")), ts(r.get("book_updated_at"))
        if ko is None or ca is None:
            continue
        minutes = (ca - ko).total_seconds() / 60.0
        if not IN_PLAY_MINUTES[0] <= minutes <= IN_PLAY_MINUTES[1]:
            continue
        side = str(r.get("selection") or "").lower()
        if side not in ("over", "under"):
            continue
        key = (r.get("event_id"), r.get("captured_at"), r.get("bookmaker"), r.get("line"))
        g = groups.setdefault(key, {"league": r.get("league"), "home": r.get("home_team"), "away": r.get("away_team"),
                                    "commence": ko, "captured": ca, "book": r.get("bookmaker"), "line": r.get("line"),
                                    "book_updated": bu})
        g[side] = r.get("price")
        if bu is not None and (g["book_updated"] is None or bu > g["book_updated"]):
            g["book_updated"] = bu
    items = []
    for g in groups.values():
        funnel["in_play_groups"] += 1
        if g.get("over") is None or g.get("under") is None:
            funnel["one_sided"] += 1
            continue
        items.append(g)
    return items


def pick_row(rows: list[dict], as_of: dt.datetime) -> dict | None:
    """The LAST row at or before `as_of`, no more than `ROW_WINDOW` before it. A row after `as_of` is never used."""
    from common import ts  # noqa: E402

    best = None
    for row in rows:
        at = ts(row.get("generated_at"))
        if at is None or at > as_of or as_of - at > ROW_WINDOW:
            continue
        if best is None or at > best[0]:
            best = (at, row)
    return best[1] if best else None


def espn_matches(cache: Path) -> tuple[dict, dict]:
    """(league, canonical home, canonical away) -> [(event, kickoff, the pricer's own key)], and (league, event) ->
    final corners."""
    from forward_grade import outcome_from_summary  # noqa: E402
    from syndicate.features.shared.soccer_live_gameline_source import _norm  # noqa: E402 -- the pricer's own key
    from syndicate.features.soccer.features.team_names import canonical_team_name  # noqa: E402

    by_names, finals = collections.defaultdict(list), {}
    for path in Path(cache, "espn").glob("*.json"):
        league, _, event = path.stem.partition("__")
        try:
            outcome = outcome_from_summary(json.loads(path.read_text(encoding="utf-8")))
        except Exception:  # noqa: BLE001
            continue
        home = (outcome.get("teams") or {}).get("home") or {}
        away = (outcome.get("teams") or {}).get("away") or {}
        by_names[(league, canonical_team_name(home.get("name") or ""), canonical_team_name(away.get("name") or ""))].append(
            (event, outcome.get("kickoff"), (_norm(home.get("name")), _norm(away.get("name")))))
        if outcome.get("completed") and home.get("wonCorners") is not None and away.get("wonCorners") is not None:
            finals[(league, event)] = float(home["wonCorners"]) + float(away["wonCorners"])
    return dict(by_names), finals


def score_items(items: list[dict], by_names: dict, finals: dict, history: dict, funnel: collections.Counter) -> list[dict]:
    from syndicate.features.shared.soccer_live_gameline_source import _norm  # noqa: E402
    from syndicate.features.soccer.features.team_names import canonical_team_name  # noqa: E402
    from live_corners_forward_grade import elapsed_minutes  # noqa: E402
    from common import ts  # noqa: E402

    scored = []
    for it in items:
        funnel["two_sided"] += 1
        key_names = (it["league"], canonical_team_name(it["home"] or ""), canonical_team_name(it["away"] or ""))
        candidates = [c for c in by_names.get(key_names, [])
                      if c[1] is not None and abs(c[1] - it["commence"]) <= KICKOFF_TOLERANCE]
        if len(candidates) != 1:
            funnel["unmatched" if not candidates else "ambiguous"] += 1
            continue
        key = (it["league"], str(candidates[0][0]))
        if it["book_updated"] is None:
            funnel["no_book_updated_at"] += 1
            continue
        row = pick_row(history.get(key, []), it["book_updated"])
        if row is None:
            funnel["no_row_within_window"] += 1
            continue
        if row.get("corners_basis") != LIVE_BASIS or row.get("projected_total_corners") is None \
                or row.get("home_corners_so_far") is None or row.get("away_corners_so_far") is None:
            funnel["row_not_on_live_basis"] += 1
            continue
        try:
            line = float(it["line"])
        except (TypeError, ValueError):
            funnel["no_line"] += 1
            continue
        so_far = float(row["home_corners_so_far"]) + float(row["away_corners_so_far"])
        if so_far > line:
            funnel["line_already_settled"] += 1
            continue
        p_book = devig_over(it["over"], it["under"])
        if p_book is None:
            funnel["unparseable_price"] += 1
            continue
        if not BOOK_P_RANGE[0] <= p_book <= BOOK_P_RANGE[1]:
            funnel["book_p_out_of_range"] += 1
            continue
        final = finals.get(key)
        if final is None:
            funnel["no_final"] += 1
            continue
        if final == line:
            funnel["push"] += 1
            continue
        funnel["scored"] += 1
        happened = final > line
        ours = poisson_over(so_far, float(row["projected_total_corners"]), line)
        sim_total = row.get("sim_projected_total_corners")
        sim = poisson_over(so_far, float(sim_total), line) if sim_total is not None else None
        scored.append({"match": key, "league": it["league"], "book": it["book"], "line": line, "happened": happened,
                       "pricer_key_matches": candidates[0][2] == (_norm(it["home"]), _norm(it["away"])),
                       "ours": ours, "sim": sim, "book_p": p_book, "over": it["over"], "under": it["under"],
                       "minute": elapsed_minutes(row), "kickoff": it["commence"],
                       "lag_s": (it["captured"] - it["book_updated"]).total_seconds(),
                       "row_age_s": (it["book_updated"] - ts(row.get("generated_at"))).total_seconds(),
                       "d_ours": log_loss(ours, happened) - log_loss(p_book, happened),
                       "d_sim": (log_loss(sim, happened) - log_loss(p_book, happened)) if sim is not None else None})
    return scored


# ---------------------------------------------------------------------------- grade

def verdict(n_matches: int, ci_hi: float, today: dt.date) -> str:
    if n_matches >= GRADE_MATCHES:
        return "SUPPORTED" if (ci_hi == ci_hi and ci_hi < 0) else "FALSIFIED"
    return "WATCHING" if today < GRADE_DATE else "INSUFFICIENT"


def _clustered(scored: list[dict], field: str):
    from live_corners_forward_grade import paired_boot  # noqa: E402 -- H32's match-clustered bootstrap, same seed

    by = collections.defaultdict(list)
    for s in scored:
        if s[field] is not None:
            by[s["match"]].append(s[field])
    return paired_boot(list(by.values())), len(by)


def paper_roi(scored: list[dict], edge: float) -> dict:
    bets = profit = 0.0
    for s in scored:
        if s["ours"] - s["book_p"] >= edge:
            bets += 1
            profit += settle(s["over"], s["happened"])
        elif s["book_p"] - s["ours"] >= edge:
            bets += 1
            profit += settle(s["under"], not s["happened"])
    return {"bets": int(bets), "profit": profit, "roi": profit / bets if bets else float("nan")}


def grade(harvest_dir: Path, cache: Path, today: dt.date | None = None) -> dict:
    from forward_grade import today_ct  # noqa: E402
    from live_corners_forward_grade import load_harvest  # noqa: E402

    today = today or today_ct()
    funnel = collections.Counter()
    history = collections.defaultdict(list)
    for row in load_harvest(harvest_dir):
        history[(str(row.get("league")), str(row.get("event_id")))].append(row)
    quote_rows = []
    for path in sorted(Path(cache, "book_quotes").glob("*.jsonl")):
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                if MARKET not in line:
                    continue
                try:
                    quote_rows.append(json.loads(line))
                except Exception:  # noqa: BLE001 -- a half-written last line on a live file
                    continue
    items = quote_items(quote_rows, funnel)
    by_names, finals = espn_matches(cache)
    scored = score_items(items, by_names, finals, dict(history), funnel)

    (point, (lo, hi)), n_matches = _clustered(scored, "d_ours")
    (sim_point, sim_ci), _ = _clustered(scored, "d_sim")
    (reg_point, reg_ci), reg_n = _clustered([s for s in scored if s["row_age_s"] <= REGISTERED_WINDOW_S], "d_ours")
    ages = sorted(s["row_age_s"] for s in scored)
    weeks = collections.Counter(s["kickoff"].strftime("%G-W%V") for s in {s["match"]: s for s in scored}.values())
    report = {
        "today": today.isoformat(), "funnel": dict(funnel), "matches": n_matches, "items": len(scored),
        "diff_ours_minus_book": point, "ci": (lo, hi),
        "diff_sim_minus_book": sim_point, "ci_sim": sim_ci,
        "sensitivity_registered_180s": {"matches": reg_n, "diff": reg_point, "ci": reg_ci},
        "row_age_s": {"median": statistics.median(ages) if ages else float("nan"),
                      "p90": ages[int(0.9 * (len(ages) - 1))] if ages else float("nan")},
        "roi": {str(e): paper_roi(scored, e) for e in EDGES},
        "per_league": {lg: {"items": len(v), "matches": len({s["match"] for s in v}), "diff": statistics.fmean(s["d_ours"] for s in v)}
                       for lg, v in sorted(_group(scored, lambda s: s["league"]).items(), key=lambda kv: str(kv[0]))},
        "per_minute": {f"{int(lo_)}-{'' if hi_ > 1e8 else int(hi_)}": {"items": len(v), "diff": statistics.fmean(s["d_ours"] for s in v)}
                       for (lo_, hi_), v in sorted((k, v) for k, v in _group(scored, _minute_bucket).items() if k[0] is not None)},
        "book_lag_s_median": statistics.median(s["lag_s"] for s in scored) if scored else float("nan"),
        "matches_the_pricers_own_key_joins": len({s["match"] for s in scored if s["pricer_key_matches"]}),
        "matches_per_week": dict(sorted(weeks.items())),
    }
    report["verdict"] = verdict(n_matches, hi, today)
    return report


def _group(scored, key):
    out = collections.defaultdict(list)
    for s in scored:
        out[key(s)].append(s)
    return out


def _minute_bucket(s):
    m = s.get("minute")
    for lo, hi in MINUTE_BUCKETS:
        if m is not None and lo <= m < hi:
            return (lo, hi)
    return (None, None)


# ---------------------------------------------------------------------------- pull (network)

def pull(harvest_dir: Path, cache: Path, env_root: Path | None = None) -> dict:
    """ESPN summaries through H32's pull, then each `book_quotes` date the harvest spans plus the day before
    (the file is keyed by the event's date). A date older than two days is fetched once; newer ones are refreshed."""
    import forward_grade as fg  # noqa: E402
    import live_corners_forward_grade as h32  # noqa: E402

    tally = collections.Counter(h32.pull(harvest_dir, cache))
    (Path(cache) / "book_quotes").mkdir(parents=True, exist_ok=True)
    base, token, _ = fg._prod(env_root)
    dates = set()
    for path in Path(harvest_dir).glob("live_projections_*.jsonl"):
        day = dt.date.fromisoformat(path.stem.rsplit("_", 1)[1])
        dates.update({day, day - dt.timedelta(days=1)})
    fresh_after = dt.datetime.now(dt.timezone.utc).date() - dt.timedelta(days=2)
    for day in sorted(dates):
        dest = Path(cache) / "book_quotes" / f"{day.isoformat()}.jsonl"
        if dest.exists() and day < fresh_after:
            tally["book_quotes_cached"] += 1
            continue
        try:
            fg._stream(base, token, f"soccer_source/tracking/book_quotes/{day.isoformat()}.jsonl", dest)
            tally["book_quotes_fetched"] += 1
        except Exception as exc:  # noqa: BLE001 -- counted, never silent
            tally[f"book_quotes_fail_{type(exc).__name__}"] += 1
    return dict(tally)


def print_report(r: dict) -> None:
    print(f"H36 {r['today']}: funnel {r['funnel']}")
    print(f"  matches {r['matches']}, items {r['items']}  |  log-loss ours - book {r['diff_ours_minus_book']:+.4f} "
          f"[{r['ci'][0]:+.4f}, {r['ci'][1]:+.4f}]  |  sim - book {r['diff_sim_minus_book']:+.4f}  |  book lag median {r['book_lag_s_median']:.0f}s")
    sens = r["sensitivity_registered_180s"]
    print(f"  row age median {r['row_age_s']['median']:.0f}s p90 {r['row_age_s']['p90']:.0f}s  |  registered 180 s subset: "
          f"{sens['matches']} matches, diff {sens['diff']:+.4f} [{sens['ci'][0]:+.4f}, {sens['ci'][1]:+.4f}]")
    for e, v in r["roi"].items():
        print(f"    paper edge >= {e}: {v['bets']} bets, profit {v['profit']:+.2f} u, ROI {v['roi']:+.3f}")
    for lg, v in r["per_league"].items():
        print(f"    {lg:16s} matches {v['matches']:3d} items {v['items']:4d}  diff {v['diff']:+.4f}")
    for b, v in r["per_minute"].items():
        print(f"    minute {b:>6}  items {v['items']:4d}  diff {v['diff']:+.4f}")
    print(f"  matches per week {r['matches_per_week']}   of which the live pricer's own name key joins "
          f"{r['matches_the_pricers_own_key_joins']}")
    print("H36:", r["verdict"])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("pull", "grade"):
        p = sub.add_parser(name)
        p.add_argument("--harvest", required=True)
        p.add_argument("--cache", required=True)
        if name == "pull":
            p.add_argument("--env-root", default=None, help="checkout holding the gitignored .env")
        else:
            p.add_argument("--today", help="YYYY-MM-DD (CT); default today")
    args = ap.parse_args(argv)
    if args.cmd == "pull":
        print(json.dumps(pull(Path(args.harvest), Path(args.cache), Path(args.env_root) if args.env_root else None), sort_keys=True))
        return 0
    report = grade(Path(args.harvest), Path(args.cache), dt.date.fromisoformat(args.today) if args.today else None)
    Path(args.cache).mkdir(parents=True, exist_ok=True)
    Path(args.cache, "live_corners_book_grade.json").write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
    print_report(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
