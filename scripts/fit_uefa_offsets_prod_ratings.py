"""UEFA offsets on PRODUCTION's ratings, constant vs recency-weighted (todo #699 Stage 1 item (i)).

RESEARCH ONLY. Reads the research root of `fit_uefa_league_offsets.py` plus production's rating
inputs pulled with production's own fetcher; writes `report_prod.json` there. Nothing in
production reads it. The registration this runs is
`.syndicate/findings_2026-10-16_uefa_offsets_recency_prod.md` section 1.

    # production's rating inputs (big 5 Understat teams 2014..2026; goals leagues
    # football-data matches 2013..2026), one season per call:
    python scripts/fetch_soccer_history_local.py --league epl --kind teams --seasons 2014 \
        --out-dir C:/tmp/uefa-offsets/prod_history/epl/team_history
    # 1. the ESPN -> production name map, for the pre-fit audit (no fit):
    python scripts/fit_uefa_offsets_prod_ratings.py names --root C:/tmp/uefa-offsets
    # 2. walk-forward NONE / CONST / REC, then parameters with bootstrap intervals:
    python scripts/fit_uefa_offsets_prod_ratings.py run --root C:/tmp/uefa-offsets

Run at Idle / `nice -n 19`: the fleet shares the machine.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "scripts"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import numpy as np  # noqa: E402

import fit_uefa_league_offsets as base_driver  # noqa: E402
from syndicate.features.soccer import uefa_league_offsets as ulo  # noqa: E402
from syndicate.features.soccer.features.loaders import _as_iso_day  # noqa: E402
from syndicate.features.soccer.features.loaders import compute_team_ratings  # noqa: E402
from syndicate.features.soccer.features.loaders import team_rows_from_match_history  # noqa: E402
from syndicate.features.soccer.features.team_names import match_team_name  # noqa: E402
from syndicate.features.soccer.ingestion.uefa_history import season_of  # noqa: E402

BIG5 = ("epl", "la_liga", "bundesliga", "serie_a", "ligue_1")
GOALS = ("eredivisie", "primeira_liga", "belgian_pro_league")
# Registered: production's call shape (build_soccer_artifacts._load_team_ratings) and the
# fleet's disk depth read 2026-10-16 (Understat 3 seasons, football-data 4).
WINDOW = {**{lg: 45 for lg in BIG5}, **{lg: 90 for lg in GOALS}}
SEASONS_BACK = {**{lg: 2 for lg in BIG5}, **{lg: 3 for lg in GOALS}}
PRIMARY_HALF_LIFE_DAYS = 730
DESCRIPTIVE_HALF_LIVES = (365, 1095, 1460)
TEST_SEASONS = range(2017, 2027)
FIRST_SEASON = 2014
SNAPSHOT_DAY = date(2026, 10, 16)
# Registered pre-fit name audit: explicit aliases for pairings the audit finds WRONG.
# Every entry is a section-5 deviation in the findings file. {(league, espn_name): prod_name}
ALIASES: dict[tuple[str, str], str] = {}


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=1, default=str), encoding="utf-8")
    os.replace(tmp, path)


def _read_csvs(paths) -> list[dict]:
    rows = []
    for path in paths:
        with path.open(encoding="utf-8", newline="") as fh:
            rows.extend(csv.DictReader(fh))
    return rows


class ProdRatingIndex:
    """Production's `compute_team_ratings` per (league, kickoff day), on the fleet's disk depth."""

    def __init__(self, prod_root: Path):
        self.rows: dict[str, list[tuple[int, str, dict]]] = {}
        self.seasons_on_disk: dict[str, list[int]] = {}
        for lg in BIG5 + GOALS:
            if lg in BIG5:
                files = sorted((prod_root / lg / "team_history").glob("teams_*.csv"))
                raw = _read_csvs(files)
            else:
                files = sorted((prod_root / lg / "history").glob("matches_*.csv"))
                raw = team_rows_from_match_history(_read_csvs(files))
            parsed = []
            for r in raw:
                day = _as_iso_day(r.get("date"))
                if day:
                    parsed.append((int(float(r["season"])), day, r))
            self.rows[lg] = parsed
            self.seasons_on_disk[lg] = sorted({s for s, _, _ in parsed})
        self._cache: dict[tuple[str, date], dict] = {}

    def ratings(self, league: str, day: date) -> dict:
        key = (league, day)
        if key not in self._cache:
            cutoff = day.isoformat()
            season = season_of(cutoff)
            lo = season - SEASONS_BACK[league]
            subset = [r for s, d, r in self.rows.get(league, ()) if lo <= s <= season and d < cutoff]
            assert all(_as_iso_day(r.get("date")) < cutoff for r in subset), "rating input on/after kickoff"
            self._cache[key] = compute_team_ratings(subset, as_of=cutoff, window=WINDOW[league]) if subset else {}
        return self._cache[key]

    def lookup(self, league: str, espn_name: str, day: date):
        table = self.ratings(league, day)
        name = ALIASES.get((league, espn_name)) or match_team_name(espn_name, list(table))
        return name, (table.get(name) if name else None)


def _placed(root: Path):
    uefa = base_driver._load_uefa(root)
    domestic = json.loads((root / "domestic_rows.json").read_text(encoding="utf-8"))
    flags = json.loads((root / "uefa_flags.json").read_text(encoding="utf-8"))
    membership = ulo.build_membership(domestic)
    return ulo.place_matches(uefa, membership), flags


def _build(root: Path):
    placed, flags = _placed(root)
    index = ProdRatingIndex(root / "prod_history")
    matches: list[ulo.CrossMatch] = []
    days: dict[str, date] = {}
    skipped = Counter()
    names: dict[str, dict] = {}
    for row in placed:
        if not ulo.is_cross_league(row):
            continue
        day = ulo._day(row["date"])
        sides = {}
        for side in ("home", "away"):
            lg, espn = row[f"{side}_league"], row[f"{side}_team"]
            if lg not in WINDOW:
                sides[side] = None
                skipped[f"league_not_rated_{lg}"] += 1
                continue
            prod_name, rating = index.lookup(lg, espn, day)
            entry = names.setdefault(f"{lg}|{espn}", {"league": lg, "espn": espn, "prod": Counter(), "unmatched": 0})
            if prod_name:
                entry["prod"][prod_name] += 1
            else:
                entry["unmatched"] += 1
            sides[side] = rating
        h, a = sides.get("home"), sides.get("away")
        if h is None or a is None:
            skipped["no_production_rating"] += 1
            continue
        if h["matches"] < ulo.MIN_DOMESTIC_MATCHES or a["matches"] < ulo.MIN_DOMESTIC_MATCHES:
            skipped["under_5_rated_matches"] += 1
            continue
        flag = flags.get(row["event_id"])
        if flag is None:
            skipped["no_status_flag"] += 1
            flag = {"neutral": False, "extra_time": False}
        matches.append(ulo.CrossMatch(
            event_id=row["event_id"], season=int(row["season"]),
            home_league=row["home_league"], away_league=row["away_league"],
            home_att=h["attack_rating"], home_def=h["defense_rating"],
            away_att=a["attack_rating"], away_def=a["defense_rating"],
            neutral=bool(flag["neutral"]), home_goals=int(row["home_score"]),
            away_goals=int(row["away_score"]), extra_time=bool(flag["extra_time"])))
        days[row["event_id"]] = day
    name_map = [{"league": e["league"], "espn": e["espn"], "prod": dict(e["prod"]), "unmatched": e["unmatched"]}
                for e in sorted(names.values(), key=lambda e: (e["league"], e["espn"]))]
    return matches, days, skipped, name_map, index


def recency_weights(train, days, anchor: date, half_life_days: int) -> list[float]:
    return [0.5 ** ((anchor - days[m.event_id]).days / half_life_days) for m in train]


def cmd_names(args) -> int:
    root = Path(args.root)
    matches, _, skipped, name_map, index = _build(root)
    multi = [e for e in name_map if len(e["prod"]) > 1]
    unmatched = [e for e in name_map if e["unmatched"]]
    out = {"seasons_on_disk": index.seasons_on_disk, "eligible": len(matches), "skipped": dict(skipped),
           "clubs": len(name_map), "multi_target": multi, "unmatched": unmatched, "map": name_map}
    _write_json(root / "prod_name_map.json", out)
    print(json.dumps({k: v for k, v in out.items() if k != "map"}, indent=1, default=str), flush=True)
    for e in name_map:
        print(f"{e['league']:<20} {e['espn']:<32} -> {e['prod']} unmatched={e['unmatched']}", flush=True)
    return 0


def _ci(values) -> list[float]:
    return [float(np.quantile(values, 0.025)), float(np.quantile(values, 0.975))]


def cmd_run(args) -> int:
    root = Path(args.root)
    matches, days, skipped, name_map, index = _build(root)
    report: dict = {"registration": ".syndicate/findings_2026-10-16_uefa_offsets_recency_prod.md s1",
                    "seasons_on_disk": index.seasons_on_disk,
                    "eligible": {"cross_league_rated": len(matches), "skipped": dict(skipped),
                                 "extra_time": sum(m.extra_time for m in matches),
                                 "neutral": sum(m.neutral for m in matches),
                                 "by_season": dict(sorted(Counter(m.season for m in matches).items()))},
                    "name_map_unmatched": [e for e in name_map if e["unmatched"]]}
    print("ELIGIBLE", report["eligible"], flush=True)

    hls = (PRIMARY_HALF_LIFE_DAYS,) + DESCRIPTIVE_HALF_LIVES
    rows, per_season = [], {}
    for season in TEST_SEASONS:
        train = [m for m in matches if FIRST_SEASON <= m.season < season]
        test = [m for m in matches if m.season == season]
        if not test:
            continue
        anchor = date(season, 7, 1)
        fits = {"none": ulo.fit_cross_league(train, with_offset=False),
                "const": ulo.fit_cross_league(train, with_offset=True)}
        for hl in hls:
            fits[f"rec{hl}"] = ulo.fit_cross_league(train, with_offset=True,
                                                    weights=recency_weights(train, days, anchor, hl))
        for m in test:
            row = {"season": m.season, "big5": m.home_league in BIG5 and m.away_league in BIG5}
            for k, f in fits.items():
                s = ulo.score_match(f, m)
                row[f"ll_{k}"], row[f"br_{k}"] = s["log_loss"], s["brier"]
            rows.append(row)
        rec = f"rec{PRIMARY_HALF_LIFE_DAYS}"
        d_rec = ulo.paired_bootstrap_ci([r[f"ll_{rec}"] - r["ll_const"] for r in rows if r["season"] == season])
        d_prod = ulo.paired_bootstrap_ci([r["ll_const"] - r["ll_none"] for r in rows if r["season"] == season])
        per_season[season] = {"n_train": fits["none"].n_matches, "n_test": len(test),
                              "d_rec_const": d_rec, "d_const_none": d_prod,
                              "beta": {k: f.beta for k, f in fits.items()},
                              "offsets_vs_epl": {k: {lg: v - f.offsets.get("epl", 0.0) for lg, v in f.offsets.items()}
                                                 for k, f in fits.items() if f.offsets}}
        print(f"SEASON {season} train={fits['none'].n_matches} test={len(test)} "
              f"REC-CONST={d_rec[0]:+.4f} [{d_rec[1]:+.4f},{d_rec[2]:+.4f}] "
              f"CONST-NONE={d_prod[0]:+.4f} [{d_prod[1]:+.4f},{d_prod[2]:+.4f}]", flush=True)

    rec = f"rec{PRIMARY_HALF_LIFE_DAYS}"

    def contrast(a, b, metric="ll", subset=lambda r: True):
        return ulo.paired_bootstrap_ci([r[f"{metric}_{a}"] - r[f"{metric}_{b}"] for r in rows if subset(r)])

    h_rec, h_prod = contrast(rec, "const"), contrast("const", "none")
    wf = {
        "n_test": len(rows), "n_big5": sum(r["big5"] for r in rows),
        "n_2020_26": sum(r["season"] >= 2020 for r in rows),
        "log_loss": {k: float(np.mean([r[f"ll_{k}"] for r in rows]))
                     for k in ["none", "const"] + [f"rec{h}" for h in hls]},
        "H_REC": {"d_log_loss": h_rec, "verdict": ulo.verdict(*h_rec)},
        "H_PROD": {"d_log_loss": h_prod, "verdict": ulo.verdict(*h_prod)},
        "secondary": {
            "rec_minus_none": contrast(rec, "none"),
            "brier_rec_minus_const": contrast(rec, "const", "br"),
            "brier_const_minus_none": contrast("const", "none", "br"),
            "big5_rec_minus_const": contrast(rec, "const", subset=lambda r: r["big5"]),
            "big5_const_minus_none": contrast("const", "none", subset=lambda r: r["big5"]),
            "s2020_26_rec_minus_const": contrast(rec, "const", subset=lambda r: r["season"] >= 2020),
            "s2020_26_const_minus_none": contrast("const", "none", subset=lambda r: r["season"] >= 2020),
        },
        "descriptive_half_lives": {f"rec{h}_minus_const": contrast(f"rec{h}", "const") for h in DESCRIPTIVE_HALF_LIVES},
        "per_season": per_season,
    }
    report["walk_forward"] = wf
    print("LOG LOSS", wf["log_loss"], flush=True)
    print("H_REC", wf["H_REC"], "H_PROD", wf["H_PROD"], flush=True)
    print("SECONDARY", json.dumps(wf["secondary"]), flush=True)
    print("DESCRIPTIVE", json.dumps(wf["descriptive_half_lives"]), flush=True)

    # Parameters with intervals: CONST on all 2014..2026, REC as of SNAPSHOT_DAY, NONE beta.
    pool = [m for m in matches if m.season >= FIRST_SEASON]
    w_snap = recency_weights(pool, days, SNAPSHOT_DAY, PRIMARY_HALF_LIFE_DAYS)
    point = {"none": ulo.fit_cross_league(pool, with_offset=False),
             "const": ulo.fit_cross_league(pool, with_offset=True),
             "rec": ulo.fit_cross_league(pool, with_offset=True, weights=w_snap)}
    rng = np.random.default_rng(699)
    draws: dict[str, dict[str, list[float]]] = {k: defaultdict(list) for k in point}
    for _ in range(args.boot):
        idx = rng.integers(0, len(pool), size=len(pool))
        sample = [pool[i] for i in idx]
        fits = {"none": ulo.fit_cross_league(sample, with_offset=False),
                "const": ulo.fit_cross_league(sample, with_offset=True),
                "rec": ulo.fit_cross_league(sample, with_offset=True, weights=[w_snap[i] for i in idx])}
        for k, f in fits.items():
            for p in ("mu", "eta", "beta"):
                draws[k][p].append(getattr(f, p))
            epl = f.offsets.get("epl")
            for lg, v in f.offsets.items():
                draws[k][lg].append(v)
                if epl is not None:
                    draws[k][f"{lg}@epl"].append(v - epl)
    kept = [(m, w) for m, w in zip(pool, w_snap) if not m.extra_time]
    raw_n, w_sum, w_sq = Counter(), Counter(), Counter()
    for m, w in kept:
        for lg in (m.home_league, m.away_league):
            raw_n[lg] += 1
            w_sum[lg] += w
            w_sq[lg] += w * w
    params = {}
    for k, f in point.items():
        entry = {p: {"value": getattr(f, p), "ci95": _ci(draws[k][p])} for p in ("mu", "eta", "beta")}
        entry["n"] = f.n_matches
        if f.offsets:
            offs = {}
            for lg in ulo.DOMESTIC_LEAGUES:
                o = {"cross_league_matches": raw_n.get(lg, 0)}
                if k == "rec":
                    o["effective_matches"] = (w_sum[lg] ** 2 / w_sq[lg]) if w_sq[lg] else 0.0
                if lg in f.offsets and raw_n.get(lg, 0) >= ulo.MIN_OFFSET_MATCHES:
                    o.update({"offset": f.offsets[lg], "ci95": _ci(draws[k][lg]),
                              "vs_epl": f.offsets[lg] - f.offsets.get("epl", 0.0),
                              "vs_epl_ci95": _ci(draws[k][f"{lg}@epl"])})
                else:
                    o["status"] = "NOT ESTIMABLE"
                offs[lg] = o
            entry["offsets"] = offs
        params[k] = entry
        print("PARAMS", k, json.dumps(entry, default=float), flush=True)
    report["parameters"] = {"boot": args.boot, "snapshot_day": SNAPSHOT_DAY.isoformat(),
                            "half_life_days": PRIMARY_HALF_LIFE_DAYS, **params}
    _write_json(root / "report_prod.json", report)
    print(f"REPORT {root / 'report_prod.json'}", flush=True)
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    names = sub.add_parser("names")
    names.add_argument("--root", required=True)
    run = sub.add_parser("run")
    run.add_argument("--root", required=True)
    run.add_argument("--boot", type=int, default=1000)
    args = p.parse_args(argv)
    return cmd_names(args) if args.cmd == "names" else cmd_run(args)


if __name__ == "__main__":
    raise SystemExit(main())
