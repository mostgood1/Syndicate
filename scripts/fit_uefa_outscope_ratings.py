"""Out-of-scope UEFA club ratings: walk-forward FITTED vs PRIOR-ONLY vs PROMOTED (todo #699 item (ii)).

RESEARCH ONLY. Reads the research root of `fit_uefa_league_offsets.py` / `fit_uefa_offsets_prod_ratings.py`
(ESPN UEFA results + raw payloads, domestic placement, production's rating inputs) and writes
`report_outscope.json` there. Nothing in production reads it. The registration this runs is
`.syndicate/findings_2026-10-16_uefa_outscope_ratings.md` section 1.

    # 1. the association map + its pre-fit audit (no fit):
    python scripts/fit_uefa_outscope_ratings.py assoc --root C:/tmp/uefa-offsets
    # 2. walk-forward 2017-2026, then the 2026-10-16 snapshot:
    python scripts/fit_uefa_outscope_ratings.py run --root C:/tmp/uefa-offsets

Run at Idle / `nice -n 19`: the fleet shares the machine.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "scripts"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import numpy as np  # noqa: E402

import fit_uefa_offsets_prod_ratings as prod  # noqa: E402
from syndicate.features.soccer import uefa_league_offsets as ulo  # noqa: E402
from syndicate.features.soccer import uefa_outscope_ratings as uor  # noqa: E402

TEST_SEASONS = range(2017, 2027)
FIRST_SEASON = 2014
SNAPSHOT_DAY = date(2026, 10, 16)
SNAPSHOT_SEASON = 2027  # "the season after the last one in training"; inner validation = 2026
DESCRIPTIVE_HALF_LIVES: tuple[float | None, ...] = (182, 730, None)
# Pre-fit association audit (findings s2): {team_id: country}, geography only. Each is listed there.
OVERRIDES: dict[str, str] = {
    # ESPN's venue country is where the HOME match was played. Exile and shared stadium names put
    # these clubs in the wrong association (audit 2026-10-16, before any fit).
    "433": "Czechia",      # Sparta Prague: "Generali Arena" is also Austria Wien's stadium name
    "21631": "Czechia",    # Bohemians 1905 (Prague), same naming collision
    "2983": "Israel",      # Maccabi Petah-Tikva, home ties played in Bulgaria
    "12200": "Slovenia",   # ND Gorica (Nova Gorica), tagged Estonia
    "2530": "Belarus",     # Gomel, tagged Greece
    "22285": "Belarus",    # Isloch Minsk, home ties played in Hungary
    "131794": "Belarus",   # ML Vitebsk, ditto
    "12305": "Belarus",    # Neman Grodno, ditto
    "8142": "Belarus",     # Torpedo Zhodino, ditto (mode Hungary 4 of 8)
    "19251": "Serbia",     # Radnicki Nis, tagged North Macedonia
    "22332": "Ukraine",    # Kryvbas Kryvyi Rih, home ties played in Slovakia
    "22294": "Ukraine",    # Polissya Zhytomyr, ditto
    "21633": "Ukraine",    # SC Dnipro-1, ditto
}


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=1, default=str), encoding="utf-8")
    os.replace(tmp, path)


def _venues(root: Path) -> dict[str, str]:
    cache = root / "uefa_venues.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    out: dict[str, str] = {}
    for d in sorted((root / "raw").iterdir()):
        if d.is_dir() and d.name.startswith("uefa."):
            for f in sorted(d.glob("*.json")):
                out.update(uor.venue_countries(json.loads(f.read_text(encoding="utf-8"))))
    _write_json(cache, out)
    return out


def _associations(root: Path, placed, flags):
    venues = _venues(root)
    neutral = {e: bool(f.get("neutral")) for e, f in flags.items()}
    return uor.club_associations(placed, venues, neutral, overrides=OVERRIDES), venues


def _oos_sides(row) -> tuple[bool, bool]:
    return (not row["home_league"], not row["away_league"])


def cmd_assoc(args) -> int:
    root = Path(args.root)
    placed, flags = prod._placed(root)
    assoc, venues = _associations(root, placed, flags)
    oos_names: dict[str, str] = {}
    for row in placed:
        ho, ao = _oos_sides(row)
        if ho:
            oos_names[str(row["home_team_id"])] = row["home_team"]
        if ao:
            oos_names[str(row["away_team_id"])] = row["away_team"]
    by_country: dict[str, list[str]] = defaultdict(list)
    for c, name in oos_names.items():
        by_country[assoc.get(c) or "?"].append(name)
    audit = [a for a in assoc.audit if a["team_id"] in oos_names]
    out = {"events_with_venue_country": sum(1 for v in venues.values() if v), "events": len(venues),
           "oos_clubs": len(oos_names), "oos_unknown": len(by_country.get("?", [])),
           "associations": len([k for k in by_country if k != "?"]), "overrides": OVERRIDES,
           "audit": audit, "by_country": {k: sorted(v) for k, v in sorted(by_country.items())}}
    _write_json(root / "outscope_assoc_audit.json", out)
    print(json.dumps({k: v for k, v in out.items() if k not in ("audit", "by_country")}, indent=1), flush=True)
    for a in audit:
        print(f"AUDIT {a['team_id']:>7} {a['team']:<32} mode={a['mode'] or '-':<22} tie={a['tie']} {a['venues']}", flush=True)
    for k, v in out["by_country"].items():
        print(f"COUNTRY {k}: {'; '.join(v)}", flush=True)
    return 0


@dataclass
class Pending:
    """An eligible OOS match before the season's CONST fit turns in-scope ratings into (A, D)."""

    row: dict
    day: date
    home: tuple[str, float, float] | None  # (league, a, d) for an in-scope side
    away: tuple[str, float, float] | None
    neutral: bool
    extra_time: bool

    def materialise(self, const: ulo.CrossFit) -> uor.OOSMatch:
        hA = hD = aA = aD = 0.0
        if self.home:
            hA, hD = uor.effective_in_scope(self.home[1], self.home[2], self.home[0], const)
        if self.away:
            aA, aD = uor.effective_in_scope(self.away[1], self.away[2], self.away[0], const)
        r = self.row
        return uor.OOSMatch(event_id=r["event_id"], season=int(r["season"]), day=self.day,
                            competition=r["competition"], stage=r.get("stage") or "",
                            home_id=str(r["home_team_id"]), away_id=str(r["away_team_id"]),
                            home_oos=self.home is None, away_oos=self.away is None,
                            home_A=hA, home_D=hD, away_A=aA, away_D=aD, neutral=self.neutral,
                            home_goals=int(r["home_score"]), away_goals=int(r["away_score"]),
                            extra_time=self.extra_time)


def _build(root: Path):
    placed, flags = prod._placed(root)
    assoc, _ = _associations(root, placed, flags)
    cross, _, cross_skipped, _, index = prod._build(root, use_aliases=True)
    pending: list[Pending] = []
    skipped = Counter()
    appearances: Counter = Counter()  # (season, team_id) OOS appearances, all UEFA rows
    names: dict[str, str] = {}
    for row in placed:
        ho, ao = _oos_sides(row)
        if not (ho or ao):
            continue
        season = int(row["season"])
        for side, oos in (("home", ho), ("away", ao)):
            if oos:
                appearances[(season, str(row[f"{side}_team_id"]))] += 1
                names[str(row[f"{side}_team_id"])] = row[f"{side}_team"]
        day = ulo._day(row["date"])
        sides = {}
        ok = True
        for side, oos in (("home", ho), ("away", ao)):
            if oos:
                sides[side] = None
                continue
            lg = row[f"{side}_league"]
            if lg not in prod.WINDOW:
                skipped[f"in_scope_league_not_rated_{lg}"] += 1
                ok = False
                break
            _, rating = index.lookup(lg, row[f"{side}_team"], day)
            if rating is None:
                skipped["in_scope_no_production_rating"] += 1
                ok = False
                break
            if rating["matches"] < ulo.MIN_DOMESTIC_MATCHES:
                skipped["in_scope_under_5_rated_matches"] += 1
                ok = False
                break
            sides[side] = (lg, float(rating["attack_rating"]), float(rating["defense_rating"]))
        if not ok:
            continue
        flag = flags.get(row["event_id"])
        if flag is None:
            skipped["no_status_flag_kept"] += 1
            flag = {"neutral": False, "extra_time": False}
        pending.append(Pending(row=row, day=day, home=sides["home"], away=sides["away"],
                               neutral=bool(flag["neutral"]), extra_time=bool(flag["extra_time"])))
    return pending, cross, assoc, skipped, appearances, names


def _thin(appearances: Counter, seasons) -> tuple[Counter, set[str]]:
    keep = set(seasons)
    n: Counter = Counter()
    for (s, c), k in appearances.items():
        if s in keep:
            n[c] += k
    return n, {c for c, k in n.items() if k < uor.THIN_MATCHES}


def _fits_for(train, anchor, val_train, val_anchor, val, assoc, beta, half_life=uor.HALF_LIFE_DAYS, taus=None):
    """Arms (a), (a0), (b), (c) on `train` (weights to `anchor`), tau by the inner rule unless given."""
    w = uor.recency_weights([m.day for m in train], anchor, half_life)
    if taus is None:
        wv = uor.recency_weights([m.day for m in val_train], val_anchor, half_life)
        _, ta_b, sb = uor.select_taus(val_train, wv, val, assoc, mode=uor.MODE_PRIOR)
        tc_c, ta_c, sc = uor.select_taus(val_train, wv, val, assoc, mode=uor.MODE_FITTED)
        taus = {"prior": (None, ta_b), "fitted": (tc_c, ta_c), "inner_scores": {"prior": sb, "fitted": sc}}
    promoted = (beta * uor.PROMOTED_RATING, beta * uor.PROMOTED_RATING)
    fits = {
        "promoted": uor.fit_outscope(train, assoc, mode=uor.MODE_FIXED, weights=w, fixed=promoted),
        "zero": uor.fit_outscope(train, assoc, mode=uor.MODE_FIXED, weights=w, fixed=(0.0, 0.0)),
        "prior": uor.fit_outscope(train, assoc, mode=uor.MODE_PRIOR, weights=w, tau_assoc=taus["prior"][1]),
        "fitted": uor.fit_outscope(train, assoc, mode=uor.MODE_FITTED, weights=w,
                                   tau_club=taus["fitted"][0], tau_assoc=taus["fitted"][1]),
    }
    return fits, taus


def cmd_run(args) -> int:
    root = Path(args.root)
    pending, cross, assoc, skipped, appearances, names = _build(root)
    report: dict = {"registration": ".syndicate/findings_2026-10-16_uefa_outscope_ratings.md s1",
                    "overrides": OVERRIDES,
                    "eligible": {"oos_matches": len(pending), "skipped": dict(skipped),
                                 "both_oos": sum(p.home is None and p.away is None for p in pending),
                                 "extra_time": sum(p.extra_time for p in pending),
                                 "by_season": dict(sorted(Counter(int(p.row["season"]) for p in pending).items()))}}
    print("ELIGIBLE", json.dumps(report["eligible"]), flush=True)
    if args.coverage_only:
        return 0

    rows, per_season = [], {}
    for season in TEST_SEASONS:
        const = ulo.fit_cross_league([m for m in cross if FIRST_SEASON <= m.season < season], with_offset=True)
        ms = [p.materialise(const) for p in pending]
        train = [m for m in ms if FIRST_SEASON <= m.season < season]
        inner_train = [m for m in train if m.season < season - 1]
        inner_val = [m for m in train if m.season == season - 1]
        test = [m for m in ms if m.season == season]
        anchor = date(season, 7, 1)
        fits, taus = _fits_for(train, anchor, inner_train, date(season - 1, 7, 1), inner_val, assoc, const.beta)
        desc = {}
        for hl in DESCRIPTIVE_HALF_LIVES:
            wd = uor.recency_weights([m.day for m in train], anchor, hl)
            desc[f"prior_hl{hl}"] = uor.fit_outscope(train, assoc, mode=uor.MODE_PRIOR, weights=wd,
                                                     tau_assoc=taus["prior"][1])
            desc[f"fitted_hl{hl}"] = uor.fit_outscope(train, assoc, mode=uor.MODE_FITTED, weights=wd,
                                                      tau_club=taus["fitted"][0], tau_assoc=taus["fitted"][1])
        _, thin = _thin(appearances, range(season - 3, season))
        for m in test:
            row = {"season": season, "competition": m.competition, "main": m.stage != "qualifying",
                   "both_oos": m.home_oos and m.away_oos,
                   "thin": (m.home_oos and m.home_id in thin) or (m.away_oos and m.away_id in thin)}
            for k, f in {**fits, **desc}.items():
                s = uor.score_match(f, m)
                row[f"ll_{k}"], row[f"br_{k}"] = s["log_loss"], s["brier"]
            rows.append(row)
        srows = [r for r in rows if r["season"] == season]
        d_fit = ulo.paired_bootstrap_ci([r["ll_fitted"] - r["ll_prior"] for r in srows])
        d_pri = ulo.paired_bootstrap_ci([r["ll_prior"] - r["ll_promoted"] for r in srows])
        f = fits["fitted"]
        per_season[season] = {"n_train": f.n_matches, "n_test": len(test), "const_beta": const.beta,
                              "tau": {"prior": taus["prior"], "fitted": taus["fitted"]},
                              "inner_scores": taus["inner_scores"],
                              "d_fitted_prior": d_fit, "d_prior_promoted": d_pri,
                              "fitted": {"mu": f.mu, "eta": f.eta, "g_A": f.g_A, "g_D": f.g_D},
                              "log_loss": {k: float(np.mean([r[f"ll_{k}"] for r in srows])) for k in fits}}
        print(f"SEASON {season} train={f.n_matches} test={len(test)} beta={const.beta:.2f} tau={taus['prior'][1]:g}/"
              f"{taus['fitted']} FIT-PRIOR={d_fit[0]:+.4f} [{d_fit[1]:+.4f},{d_fit[2]:+.4f}] "
              f"PRIOR-PROMOTED={d_pri[0]:+.4f} [{d_pri[1]:+.4f},{d_pri[2]:+.4f}]", flush=True)

    def contrast(a, b, metric="ll", subset=lambda r: True):
        return ulo.paired_bootstrap_ci([r[f"{metric}_{a}"] - r[f"{metric}_{b}"] for r in rows if subset(r)])

    def n(subset):
        return sum(1 for r in rows if subset(r))

    h_fit, h_prior = contrast("fitted", "prior"), contrast("prior", "promoted")
    subsets = {
        "oos_vs_in_scope": lambda r: not r["both_oos"], "oos_vs_oos": lambda r: r["both_oos"],
        "ucl": lambda r: r["competition"] == "ucl", "uel": lambda r: r["competition"] == "uel",
        "uecl": lambda r: r["competition"] == "uecl",
        "main_draw": lambda r: r["main"], "qualifying": lambda r: not r["main"],
        "thin": lambda r: r["thin"], "not_thin": lambda r: not r["thin"],
    }
    wf = {
        "n_test": len(rows),
        "log_loss": {k: float(np.mean([r[k] for r in rows])) for k in rows[0] if k.startswith("ll_")},
        "H_FIT": {"d_log_loss": h_fit, "verdict": ulo.verdict(*h_fit)},
        "H_PRIOR": {"d_log_loss": h_prior, "verdict": ulo.verdict(*h_prior)},
        "secondary": {
            "fitted_minus_promoted": contrast("fitted", "promoted"),
            "fitted_minus_zero": contrast("fitted", "zero"),
            "promoted_minus_zero": contrast("promoted", "zero"),
            "brier_fitted_minus_prior": contrast("fitted", "prior", "br"),
            "brier_prior_minus_promoted": contrast("prior", "promoted", "br"),
            "brier_fitted_minus_promoted": contrast("fitted", "promoted", "br"),
            "seasons_fitted_below_prior": sum(1 for v in per_season.values() if v["d_fitted_prior"][0] < 0),
            "seasons_prior_below_promoted": sum(1 for v in per_season.values() if v["d_prior_promoted"][0] < 0),
            "subsets": {name: {"n": n(fn), "fitted_minus_prior": contrast("fitted", "prior", subset=fn),
                               "prior_minus_promoted": contrast("prior", "promoted", subset=fn),
                               "fitted_minus_promoted": contrast("fitted", "promoted", subset=fn)}
                        for name, fn in subsets.items()},
        },
        "descriptive_half_lives": {
            f"hl{hl}": {"fitted_minus_prior_same_hl": contrast(f"fitted_hl{hl}", f"prior_hl{hl}"),
                        "fitted_minus_primary_fitted": contrast(f"fitted_hl{hl}", "fitted"),
                        "prior_minus_primary_prior": contrast(f"prior_hl{hl}", "prior")}
            for hl in DESCRIPTIVE_HALF_LIVES},
        "per_season": per_season,
    }
    report["walk_forward"] = wf
    print("LOG LOSS", json.dumps(wf["log_loss"]), flush=True)
    print("H_FIT", wf["H_FIT"], "H_PRIOR", wf["H_PRIOR"], flush=True)
    print("SECONDARY", json.dumps(wf["secondary"]), flush=True)
    print("DESCRIPTIVE", json.dumps(wf["descriptive_half_lives"]), flush=True)

    # Snapshot as of 2026-10-16.
    const = ulo.fit_cross_league([m for m in cross if m.season >= FIRST_SEASON], with_offset=True)
    ms = [p.materialise(const) for p in pending if p.day < SNAPSHOT_DAY]
    inner_train = [m for m in ms if m.season < SNAPSHOT_SEASON - 1]
    inner_val = [m for m in ms if m.season == SNAPSHOT_SEASON - 1]
    fits, taus = _fits_for(ms, SNAPSHOT_DAY, inner_train, date(SNAPSHOT_SEASON - 1, 7, 1), inner_val,
                           assoc, const.beta)
    f = fits["fitted"]
    counts, thin = _thin(appearances, range(2023, 2027))
    current = {c for (s, c) in appearances if s in (2025, 2026)}
    table = [r for r in uor.rating_table(f, const.beta, names, counts, thin) if r["team_id"] in current]
    seen_current = {r["team_id"] for r in table}
    report["snapshot"] = {
        "day": SNAPSHOT_DAY.isoformat(), "const_beta": const.beta, "const_offsets": const.offsets,
        "tau": {"prior": taus["prior"], "fitted": taus["fitted"]},
        "mu": f.mu, "eta": f.eta, "g_A": f.g_A, "g_D": f.g_D,
        "associations": {k: {"m_A": v[0], "m_D": v[1]} for k, v in sorted(f.assoc.items(), key=lambda kv: -sum(kv[1]))},
        "coverage": {"oos_clubs_2025_26": len(current), "rated": len(seen_current),
                     "unrated_prior_only": len(current - seen_current),
                     "fitted_ge_threshold": sum(1 for r in table if not r["thin"]),
                     "thin_lt_threshold": sum(1 for r in table if r["thin"]),
                     "threshold": uor.THIN_MATCHES, "window_seasons": [2023, 2026],
                     "unknown_association": sum(1 for c in current if not assoc.get(c))},
        "clubs": table,
    }
    print("SNAPSHOT", json.dumps({k: v for k, v in report["snapshot"].items() if k != "clubs"}, default=float), flush=True)
    for r in table[:25]:
        print(f"TOP {r['team']:<30} {r['association']:<16} A={r['A']:+.2f}±{r['A_se']:.2f} D={r['D']:+.2f}±{r['D_se']:.2f} "
              f"n3={r['recent_matches']} thin={r['thin']}", flush=True)
    _write_json(root / "report_outscope.json", report)
    print(f"REPORT {root / 'report_outscope.json'}", flush=True)
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("assoc", "run"):
        sp = sub.add_parser(name)
        sp.add_argument("--root", required=True)
        if name == "run":
            sp.add_argument("--coverage-only", action="store_true", help="eligibility counts, no fit")
    args = p.parse_args(argv)
    return cmd_assoc(args) if args.cmd == "assoc" else cmd_run(args)


if __name__ == "__main__":
    raise SystemExit(main())
