"""Measure per-league strength offsets from cross-league UEFA results (todo #699, Stage 1 step 2).

RESEARCH ONLY. Writes into a research root outside git; nothing in production reads it.
The registration this runs is `.syndicate/findings_2026-10-16_uefa_league_offsets.md` section 1.

    # 1. UEFA results (existing fetcher), then domestic results + UEFA status flags:
    python scripts/fetch_uefa_history.py --seasons 2014-2026 --out-root C:/tmp/uefa-offsets/uefa
    python scripts/fit_uefa_league_offsets.py pull --root C:/tmp/uefa-offsets
    # 2. coverage, walk-forward test, offsets with bootstrap intervals:
    python scripts/fit_uefa_league_offsets.py run --root C:/tmp/uefa-offsets

`pull` caches one JSON per (slug, calendar year) and skips cached years; ~0.3 s between calls.
Run at Idle / `nice -n 19`: the fleet shares the machine.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from syndicate.features.soccer import uefa_league_offsets as ulo  # noqa: E402
from syndicate.features.soccer.ingestion import uefa_history  # noqa: E402
from syndicate.features.soccer.ingestion.espn_lineups import LEAGUE_ESPN_SLUGS  # noqa: E402
from syndicate.features.soccer.sources import UEFA_COMPETITIONS  # noqa: E402

DOMESTIC_YEARS = range(2013, 2027)
UEFA_YEARS = range(2014, 2028)
TEST_SEASONS = range(2017, 2027)
FIRST_SEASON = 2014


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    os.replace(tmp, path)


def _cached_year(cache: Path, slug: str, year: int, pause: float):
    path = cache / slug / f"{year}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8")), False
    payload = uefa_history.fetch_year(slug, year)
    _write_json(path, payload)
    time.sleep(pause)
    return payload, True


def cmd_pull(args) -> int:
    root = Path(args.root)
    cache = root / "raw"
    fetched = 0
    domestic: dict[str, list[dict]] = {}
    for league in ulo.DOMESTIC_LEAGUES:
        slug = LEAGUE_ESPN_SLUGS[league]
        rows: dict[str, dict] = {}
        for year in DOMESTIC_YEARS:
            payload, did = _cached_year(cache, slug, year, args.pause_seconds)
            fetched += did
            for row in uefa_history.completed_rows(payload, competition=league, stage="league", espn_slug=slug):
                rows.setdefault(row["event_id"], row)
        domestic[league] = sorted(rows.values(), key=lambda r: (r["date"], r["event_id"]))
        print(f"DOMESTIC league={league} slug={slug} matches={len(domestic[league])}", flush=True)
    _write_json(root / "domestic_rows.json", domestic)
    flags: dict[str, dict] = {}
    for comp in UEFA_COMPETITIONS:
        for _, slug in uefa_history.slugs_for(comp):
            for year in UEFA_YEARS:
                payload, did = _cached_year(cache, slug, year, args.pause_seconds)
                fetched += did
                flags.update(ulo.match_flags(payload))
    _write_json(root / "uefa_flags.json", flags)
    print(f"PULL requests={fetched} uefa_flag_events={len(flags)} "
          f"extra_time={sum(f['extra_time'] for f in flags.values())} "
          f"neutral={sum(f['neutral'] for f in flags.values())}", flush=True)
    return 0


def _load_uefa(root: Path) -> list[dict]:
    rows: dict[str, dict] = {}
    for comp in UEFA_COMPETITIONS:
        for path in sorted((root / "uefa" / comp / "history").glob("uefa_results_*.csv")):
            with path.open(encoding="utf-8", newline="") as fh:
                for row in csv.DictReader(fh):
                    rows.setdefault(row["event_id"], row)
    return sorted(rows.values(), key=lambda r: (r["date"], r["event_id"]))


def _cross_matches(placed, flags, index, skipped: Counter) -> list[ulo.CrossMatch]:
    out = []
    for row in placed:
        if not ulo.is_cross_league(row):
            continue
        day = ulo._day(row["date"])
        home = index.rating(row["home_league"], row["home_team_id"], day)
        away = index.rating(row["away_league"], row["away_team_id"], day)
        if not home or not away or home[2] < ulo.MIN_DOMESTIC_MATCHES or away[2] < ulo.MIN_DOMESTIC_MATCHES:
            skipped["no_domestic_rating"] += 1
            continue
        flag = flags.get(row["event_id"])
        if flag is None:
            skipped["no_status_flag"] += 1
            flag = {"neutral": False, "extra_time": False}
        out.append(ulo.CrossMatch(
            event_id=row["event_id"], season=int(row["season"]),
            home_league=row["home_league"], away_league=row["away_league"],
            home_att=home[0], home_def=home[1], away_att=away[0], away_def=away[1],
            neutral=bool(flag["neutral"]), home_goals=int(row["home_score"]),
            away_goals=int(row["away_score"]), extra_time=bool(flag["extra_time"])))
    return out


def _score_arms(train, test):
    base = ulo.fit_cross_league(train, with_offset=False)
    off = ulo.fit_cross_league(train, with_offset=True)
    rows = []
    for m in test:
        a, b = ulo.score_match(base, m), ulo.score_match(off, m)
        rows.append({"event_id": m.event_id, "season": m.season,
                     "big5": m.home_league in BIG5 and m.away_league in BIG5,
                     "d_log_loss": b["log_loss"] - a["log_loss"], "d_brier": b["brier"] - a["brier"],
                     "ll_base": a["log_loss"], "ll_off": b["log_loss"]})
    return base, off, rows


BIG5 = {"epl", "la_liga", "bundesliga", "serie_a", "ligue_1"}


def cmd_run(args) -> int:
    root = Path(args.root)
    uefa = _load_uefa(root)
    domestic = json.loads((root / "domestic_rows.json").read_text(encoding="utf-8"))
    flags = json.loads((root / "uefa_flags.json").read_text(encoding="utf-8"))
    report: dict = {"registration": ".syndicate/findings_2026-10-16_uefa_league_offsets.md s1"}

    membership = ulo.build_membership(domestic)
    placed = ulo.place_matches(uefa, membership)
    cov = ulo.coverage(placed)
    cov["membership_conflicts"] = len(membership.conflicts)
    cov["by_competition"] = {c: ulo.coverage([r for r in placed if r["competition"] == c])
                             for c in UEFA_COMPETITIONS}
    for c in cov["by_competition"].values():
        c.pop("pairs", None)
    cov["by_season"] = {s: {k: v for k, v in ulo.coverage([r for r in placed if int(r["season"]) == s]).items()
                            if k in ("matches", "both_placed_share", "cross_league")}
                        for s in sorted({int(r["season"]) for r in placed})}
    per_league_uefa = Counter()
    for r in placed:
        for side in ("home_league", "away_league"):
            per_league_uefa[r[side] or "(outside our ten)"] += 1
    cov["club_appearances_by_league"] = dict(per_league_uefa.most_common())
    clubs_out = Counter()
    names = {}
    for r in placed:
        for side in ("home", "away"):
            if not r[f"{side}_league"]:
                clubs_out[r[f"{side}_team_id"]] += 1
                names[r[f"{side}_team_id"]] = r[f"{side}_team"]
    cov["unplaced_clubs_with_20plus_matches"] = sum(1 for n in clubs_out.values() if n >= 20)
    report["coverage"] = cov
    print(json.dumps({k: v for k, v in cov.items() if k not in ("pairs", "by_competition", "by_season")}, indent=1), flush=True)

    index = ulo.DomesticRatingIndex(domestic)
    skipped = Counter()
    matches = _cross_matches(placed, flags, index, skipped)
    report["eligible"] = {"cross_league_rated": len(matches), "skipped": dict(skipped),
                          "extra_time": sum(m.extra_time for m in matches),
                          "neutral": sum(m.neutral for m in matches)}
    print("ELIGIBLE", report["eligible"], flush=True)

    # Walk-forward, registered: train seasons FIRST_SEASON..S-1, test S.
    all_rows, per_season = [], {}
    for season in TEST_SEASONS:
        train = [m for m in matches if FIRST_SEASON <= m.season < season]
        test = [m for m in matches if m.season == season]
        if not test:
            continue
        base, off, rows = _score_arms(train, test)
        all_rows.extend(rows)
        mean, lo, hi = ulo.paired_bootstrap_ci([r["d_log_loss"] for r in rows])
        per_season[season] = {"n_train": base.n_matches, "n_test": len(rows), "d_log_loss": mean,
                              "ci": [lo, hi], "beta_base": base.beta, "beta_off": off.beta,
                              "eta_off": off.eta}
        print(f"SEASON {season} train={base.n_matches} test={len(rows)} dLL={mean:+.4f} [{lo:+.4f},{hi:+.4f}]", flush=True)
    primary = ulo.paired_bootstrap_ci([r["d_log_loss"] for r in all_rows])
    brier = ulo.paired_bootstrap_ci([r["d_brier"] for r in all_rows])
    big5 = ulo.paired_bootstrap_ci([r["d_log_loss"] for r in all_rows if r["big5"]])
    report["walk_forward"] = {
        "n_test": len(all_rows),
        "log_loss_base": float(np.mean([r["ll_base"] for r in all_rows])),
        "log_loss_offset": float(np.mean([r["ll_off"] for r in all_rows])),
        "d_log_loss": primary, "d_brier": brier,
        "d_log_loss_big5_only": big5, "n_big5": sum(r["big5"] for r in all_rows),
        "per_season": per_season, "verdict": ulo.verdict(*primary),
    }
    print("PRIMARY dLL", primary, "VERDICT", report["walk_forward"]["verdict"], flush=True)
    print("BRIER", brier, "BIG5", big5, flush=True)

    # Offsets on all seasons, with percentile bootstrap intervals.
    full = ulo.fit_cross_league(matches, with_offset=True)
    full_base = ulo.fit_cross_league(matches, with_offset=False)
    train_matches = [m for m in matches if not m.extra_time]
    league_n = Counter()
    for m in train_matches:
        league_n[m.home_league] += 1
        league_n[m.away_league] += 1
    rng = np.random.default_rng(699)
    draws: dict[str, list[float]] = defaultdict(list)
    for _ in range(args.boot):
        sample = [matches[i] for i in rng.integers(0, len(matches), size=len(matches))]
        fit = ulo.fit_cross_league(sample, with_offset=True)
        epl = fit.offsets.get("epl")
        for lg, v in fit.offsets.items():
            draws[lg].append(v)
            if epl is not None:
                draws[f"{lg}@epl"].append(v - epl)
    offsets = {}
    for lg in ulo.DOMESTIC_LEAGUES:
        n = league_n.get(lg, 0)
        entry = {"cross_league_matches": n}
        if lg in full.offsets and n >= ulo.MIN_OFFSET_MATCHES:
            entry.update({
                "offset": full.offsets[lg],
                "ci95": [float(np.quantile(draws[lg], 0.025)), float(np.quantile(draws[lg], 0.975))],
                "vs_epl": full.offsets[lg] - full.offsets.get("epl", 0.0),
                "vs_epl_ci95": [float(np.quantile(draws[f"{lg}@epl"], 0.025)),
                                float(np.quantile(draws[f"{lg}@epl"], 0.975))],
            })
        else:
            entry["status"] = "NOT ESTIMABLE"
        offsets[lg] = entry
        print("OFFSET", lg, json.dumps(entry), flush=True)
    report["full_fit"] = {"n": full.n_matches, "mu": full.mu, "eta": full.eta, "beta": full.beta,
                          "beta_no_offset": full_base.beta, "offsets": offsets, "boot": args.boot}
    print("FULL", {k: v for k, v in report["full_fit"].items() if k != "offsets"}, flush=True)
    _write_json(root / "report.json", report)
    print(f"REPORT {root / 'report.json'}", flush=True)
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    pull = sub.add_parser("pull")
    pull.add_argument("--root", required=True)
    pull.add_argument("--pause-seconds", type=float, default=0.3)
    run = sub.add_parser("run")
    run.add_argument("--root", required=True)
    run.add_argument("--boot", type=int, default=1000)
    args = p.parse_args(argv)
    return cmd_pull(args) if args.cmd == "pull" else cmd_run(args)


if __name__ == "__main__":
    raise SystemExit(main())
