"""UEFA main-draw 1X2: model vs the de-vigged close, walk-forward blend, per-competition GO/NO-GO.

RESEARCH ONLY (todo #699 Stage 1 step 3). Reads the ESPN research root (`--uefa-root`, from
`fit_uefa_league_offsets.py`) and the OddsAPI close snapshots (`--closes`, from
`backfill_uefa_historical_closes.py`); writes `joined.json` / `report_close.json` under `--closes`.
Nothing in production reads them. The registration is
`.syndicate/findings_2026-10-16_uefa_close_backtest.md` section 1.

    # 1. the join + its audit, BEFORE any scoring:
    python scripts/backtest_uefa_vs_close.py join --uefa-root C:/tmp/uefa-offsets --closes C:/tmp/uefa-closes
    # 2. the walk-forward:
    python scripts/backtest_uefa_vs_close.py run  --uefa-root C:/tmp/uefa-offsets --closes C:/tmp/uefa-closes

Run at Idle / `nice -n 19`: the fleet shares the machine.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "scripts"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import numpy as np  # noqa: E402

import backfill_uefa_historical_closes as bf  # noqa: E402
import fit_uefa_offsets_prod_ratings as prod  # noqa: E402
import fit_uefa_outscope_ratings as fos  # noqa: E402
from syndicate.features.soccer import uefa_close_backtest as ucb  # noqa: E402
from syndicate.features.soccer import uefa_league_offsets as ulo  # noqa: E402
from syndicate.features.soccer import uefa_outscope_ratings as uor  # noqa: E402

TEST_SEASONS = range(2020, 2027)
BLEND_FIRST_SEASON = 2021
FIRST_SEASON = 2014
COMPETITIONS = ("ucl", "uel", "uecl")
# Pre-scoring join audit (findings s2, deviation 1): {espn_name: [extra names to score against
# OddsAPI's]}. The ESPN name is always tried too; the best "ok" join wins. Every entry was read off
# a MISSED join whose other club matched >= 0.8, and checked by hand. "Cercle Brugge KSV" ->
# "Club Brugge" came out of the same sweep and is WRONG (two clubs), so it is NOT here.
ALIASES: dict[str, list[str]] = {
    "Ajax Amsterdam": ["Ajax"], "Stade Rennais": ["Rennes"], "FK TSC": ["TSC Backa Topola"],
    "Omonia Nicosia": ["Omonoia"], "Racing Genk": ["Genk"], "Internazionale": ["Inter Milan"],
    "FC Twente": ["Twente Enschede"], "Vitória de Guimaraes": ["Vitoria SC"], "Apoel Nicosia": ["APOEL"],
    "Mainz": ["FSV Mainz 05"], "Rigas Futbola Skola": ["RFS"], "Drita Gjilan": ["Drita"],
    "CSU Craiova": ["Universitatea Craiova"], "Heart of Midlothian": ["Hearts"],
    "KI Klaksvik": ["Klaksvikar Itrottarfelag"], "Zenit St Petersburg": ["Zenit"], "FC Cologne": ["1. FC Koln"],
    "AGF": ["AGF Aarhus"],
}


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=1, default=str), encoding="utf-8")
    os.replace(tmp, path)


def _phases(uefa_root: Path) -> dict[str, str]:
    """{event_id: 'league' | 'knockout'} from the raw ESPN season slug."""
    out = {}
    for d in (uefa_root / "raw").iterdir():
        if not d.name.startswith("uefa.") or "_qual" in d.name:
            continue
        for f in d.glob("*.json"):
            for e in json.loads(f.read_text(encoding="utf-8")).get("events") or []:
                slug = str((e.get("season") or {}).get("slug") or "")
                out[str(e.get("id"))] = "league" if ("group" in slug or "league" in slug or "first-round" in slug) else "knockout"
    return out


def cmd_join(args) -> int:
    uefa_root, closes = Path(args.uefa_root), Path(args.closes)
    placed, _flags = prod._placed(uefa_root)
    rows = [r for r in placed if r["competition"] in COMPETITIONS and r["stage"] != "qualifying"
            and r["date"][:10] >= bf.FIRST_DAY]
    joined, audit_low, unmatched = {}, [], []
    reasons, sources = Counter(), Counter()
    for r in rows:
        ko = datetime.fromisoformat(r["date"].replace("Z", "+00:00")).replace(second=0, microsecond=0)
        path = bf.snapshot_path(closes, r["competition"], ko)
        if not path.exists():
            reasons["no_snapshot_file"] += 1
            unmatched.append({**_brief(r), "reason": "no_snapshot_file"})
            continue
        snap = json.loads(path.read_text(encoding="utf-8"))
        snap_ts = str(snap.get("timestamp") or "")
        events = [e for e in snap.get("data") or [] if str(e.get("commence_time")) > snap_ts]
        res = None
        for home in [r["home_team"]] + ALIASES.get(r["home_team"], []):
            for away in [r["away_team"]] + ALIASES.get(r["away_team"], []):
                cand = ucb.join_event(home, away, r["date"], events)
                if res is None or (cand.reason == "ok", cand.score) > (res.reason == "ok", res.score):
                    res = cand
        if res.reason != "ok":
            reasons[res.reason] += 1
            unmatched.append({**_brief(r), "reason": res.reason, "best": round(res.score, 3),
                              "candidates": [f"{e['home_team']} v {e['away_team']} {e['commence_time']}" for e in events
                                             if abs((datetime.fromisoformat(e['commence_time'].replace('Z', '+00:00')) - ko).total_seconds()) <= 3600][:12]})
            continue
        close = ucb.close_1x2(res.event, swapped=res.swapped)
        if close is None:
            reasons["no_complete_book"] += 1
            unmatched.append({**_brief(r), "reason": "no_complete_book"})
            continue
        probs, source, n_books = close
        reasons["ok"] += 1
        sources[source] += 1
        joined[r["event_id"]] = {"probs": probs, "source": source, "books": n_books, "score": res.score,
                                 "swapped": res.swapped, "snapshot": snap_ts,
                                 "api": f"{res.event['home_team']} v {res.event['away_team']}"}
        if res.score < 0.85:
            audit_low.append({**_brief(r), "api": joined[r["event_id"]]["api"], "score": round(res.score, 3),
                              "swapped": res.swapped})
    by_comp = Counter(r["competition"] for r in rows)
    ok_comp = Counter(r["competition"] for r in rows if r["event_id"] in joined)
    out = {"matches": len(rows), "joined": len(joined), "reasons": dict(reasons), "sources": dict(sources),
           "by_competition": {c: {"matches": by_comp[c], "joined": ok_comp[c]} for c in COMPETITIONS},
           "aliases": ALIASES, "audit_low_score": audit_low, "unmatched": unmatched, "joined_rows": joined}
    _write_json(closes / "joined.json", out)
    print(json.dumps({k: out[k] for k in ("matches", "joined", "reasons", "sources", "by_competition")}), flush=True)
    for a in sorted(audit_low, key=lambda a: a["score"]):
        print(f"LOW {a['score']:.3f} swapped={a['swapped']} ESPN {a['home']} v {a['away']} -> API {a['api']}", flush=True)
    for u in unmatched:
        print(f"UNMATCHED {u['reason']} {u['date']} {u['competition']} {u['home']} v {u['away']} best={u.get('best')} "
              f"cands={u.get('candidates')}", flush=True)
    return 0


def _brief(r) -> dict:
    return {"event_id": r["event_id"], "date": r["date"], "competition": r["competition"],
            "home": r["home_team"], "away": r["away_team"]}


def cmd_run(args) -> int:
    uefa_root, closes = Path(args.uefa_root), Path(args.closes)
    join = json.loads((closes / "joined.json").read_text(encoding="utf-8"))["joined_rows"]
    phases = _phases(uefa_root)
    pending, cross, assoc, _skipped, _app, _names = fos._build(uefa_root)
    oos_by_event = {p.row["event_id"]: p for p in pending}
    placed, flags = prod._placed(uefa_root)
    index = prod.ProdRatingIndex(uefa_root / "prod_history", use_aliases=True)
    skipped = Counter()

    # In/in matches: production ratings for both sides (eligibility as in item (i)).
    inin: dict[str, tuple[dict, tuple, tuple, dict]] = {}
    for r in placed:
        eid = r["event_id"]
        if eid not in join or eid in oos_by_event:
            continue
        if not (r["home_league"] and r["away_league"]):
            skipped["oos_but_ineligible"] += 1
            continue
        sides = []
        for side in ("home", "away"):
            lg = r[f"{side}_league"]
            if lg not in prod.WINDOW:
                sides.append(None)
                continue
            _, rating = index.lookup(lg, r[f"{side}_team"], ulo._day(r["date"]))
            sides.append(rating if rating and rating["matches"] >= ulo.MIN_DOMESTIC_MATCHES else None)
        if None in sides:
            skipped["in_scope_unrated"] += 1
            continue
        flag = flags.get(eid) or {"neutral": False, "extra_time": False}
        inin[eid] = (r, sides[0], sides[1], flag)

    rows = []
    for season in TEST_SEASONS:
        const = ulo.fit_cross_league([m for m in cross if FIRST_SEASON <= m.season < season], with_offset=True)
        ms = [p.materialise(const) for p in pending]
        train = [m for m in ms if FIRST_SEASON <= m.season < season]
        inner_train = [m for m in train if m.season < season - 1]
        inner_val = [m for m in train if m.season == season - 1]
        fits, taus = fos._fits_for(train, date(season, 7, 1), inner_train, date(season - 1, 7, 1), inner_val,
                                   assoc, const.beta)
        fitted = fits["fitted"]
        by_id = {m.event_id: m for m in ms if m.season == season}
        n0 = len(rows)
        for eid, j in join.items():
            if eid in by_id:
                m = by_id[eid]
                rates = fitted.rates(m)
                p_model = ulo.outcome_probs(*rates)
                ids, day = (m.home_id, m.away_id), m.day.isoformat()
                y = ulo.result_index(m)
                pair = "oos_oos" if (m.home_oos and m.away_oos) else "in_oos"
                comp = m.competition
            elif eid in inin and int(inin[eid][0]["season"]) == season:
                r, h, a, flag = inin[eid]
                cm = ulo.CrossMatch(event_id=eid, season=season, home_league=r["home_league"], away_league=r["away_league"],
                                    home_att=h["attack_rating"], home_def=h["defense_rating"],
                                    away_att=a["attack_rating"], away_def=a["defense_rating"],
                                    neutral=bool(flag["neutral"]), home_goals=int(r["home_score"]),
                                    away_goals=int(r["away_score"]), extra_time=bool(flag["extra_time"]))
                rates = const.rates(cm)
                p_model = ulo.outcome_probs(*rates)
                ids, day = (str(r["home_team_id"]), str(r["away_team_id"])), str(r["date"])[:10]
                y = ulo.result_index(cm)
                pair = "in_in"
                comp = r["competition"]
            else:
                continue
            rows.append({"event_id": eid, "season": season, "competition": comp, "pair": pair,
                         "home_id": ids[0], "away_id": ids[1], "day": day, "lam": list(rates),
                         "phase": phases.get(eid, "league"), "source": j["source"],
                         "p_model": list(p_model), "p_close": list(j["probs"]), "y": y})
        print(f"SEASON {season} scored={len(rows) - n0} beta={const.beta:.2f} tau={taus['fitted']}", flush=True)

    # Walk-forward blend weight.
    weights = {}
    for season in TEST_SEASONS:
        hist = [(r["p_model"], r["p_close"], r["y"]) for r in rows if r["season"] < season]
        weights[season] = ucb.choose_weight(hist) if season >= BLEND_FIRST_SEASON else None
    for r in rows:
        r["ll_model"] = ucb.log_loss(r["p_model"], r["y"])
        r["ll_close"] = ucb.log_loss(r["p_close"], r["y"])
        w = weights[r["season"]]
        if w is not None:
            r["w"] = w
            r["p_blend"] = list(ucb.blend(r["p_model"], r["p_close"], w))
            r["ll_blend"] = ucb.log_loss(r["p_blend"], r["y"])
        for k in ("model", "close") + (("blend",) if w is not None else ()):
            p = r[f"p_{k}"]
            r[f"br_{k}"] = sum((p[i] - (1.0 if i == r["y"] else 0.0)) ** 2 for i in range(3))

    blended = [r for r in rows if "ll_blend" in r]

    def ci(diffs):
        return ulo.paired_bootstrap_ci(diffs)

    def gate(sub):
        d = ci([r["ll_blend"] - r["ll_close"] for r in sub])
        if d[0] >= 0:
            v = "NO-GO / FALSIFIED"
        elif d[2] < 0:
            v = "GO"
        else:
            v = "NO-GO / NOT DEMONSTRATED"
        return {"n": len(sub), "d_blend_close": d, "verdict": v}

    verdicts = {c: gate([r for r in blended if r["competition"] == c]) for c in COMPETITIONS}
    verdicts["pooled"] = gate(blended)
    groups = {
        **{f"comp_{c}": (lambda c: lambda r: r["competition"] == c)(c) for c in COMPETITIONS},
        **{f"pair_{p}": (lambda p: lambda r: r["pair"] == p)(p) for p in ("in_in", "in_oos", "oos_oos")},
        "phase_league": lambda r: r["phase"] == "league", "phase_knockout": lambda r: r["phase"] == "knockout",
        "source_pinnacle": lambda r: r["source"] == "pinnacle", "source_average": lambda r: r["source"] == "average",
        **{f"season_{s}": (lambda s: lambda r: r["season"] == s)(s) for s in TEST_SEASONS},
    }
    secondary = {}
    for name, fn in groups.items():
        sub = [r for r in rows if fn(r)]
        bsub = [r for r in sub if "ll_blend" in r]
        secondary[name] = {
            "n": len(sub), "ll_model": float(np.mean([r["ll_model"] for r in sub])) if sub else None,
            "ll_close": float(np.mean([r["ll_close"] for r in sub])) if sub else None,
            "d_model_close": ci([r["ll_model"] - r["ll_close"] for r in sub]),
            "n_blend": len(bsub), "d_blend_close": ci([r["ll_blend"] - r["ll_close"] for r in bsub]),
            "d_brier_model_close": ci([r["br_model"] - r["br_close"] for r in sub]),
        }
    # Calibration by close-favourite decile (probability of the close's favourite outcome).
    calib = []
    fav = sorted(rows, key=lambda r: max(r["p_close"]))
    for i, chunk in enumerate(np.array_split(np.arange(len(fav)), 10)):
        sub = [fav[k] for k in chunk]
        if not sub:
            continue
        idx = [int(np.argmax(r["p_close"])) for r in sub]
        calib.append({"decile": i + 1, "n": len(sub),
                      "close_fav": float(np.mean([r["p_close"][k] for r, k in zip(sub, idx)])),
                      "model_fav": float(np.mean([r["p_model"][k] for r, k in zip(sub, idx)])),
                      "actual": float(np.mean([1.0 if r["y"] == k else 0.0 for r, k in zip(sub, idx)]))})
    report = {"registration": ".syndicate/findings_2026-10-16_uefa_close_backtest.md s1",
              "scored": len(rows), "blended": len(blended), "skipped": dict(skipped),
              "weights": weights, "verdicts": verdicts,
              "d_model_close_all": ci([r["ll_model"] - r["ll_close"] for r in rows]),
              "log_loss": {"model": float(np.mean([r["ll_model"] for r in rows])),
                           "close": float(np.mean([r["ll_close"] for r in rows])),
                           "blend_seasons_model": float(np.mean([r["ll_model"] for r in blended])),
                           "blend_seasons_close": float(np.mean([r["ll_close"] for r in blended])),
                           "blend": float(np.mean([r["ll_blend"] for r in blended]))},
              "secondary": secondary, "calibration": calib,
              "counts": {"pair": dict(Counter(r["pair"] for r in rows)),
                         "competition": dict(Counter(r["competition"] for r in rows)),
                         "source": dict(Counter(r["source"] for r in rows))},
              "rows": rows}
    _write_json(closes / "report_close.json", report)
    if getattr(args, "dump_features", False):
        _write_json(closes / "features.json", [
            {k: r[k] for k in ("event_id", "season", "competition", "pair", "phase", "source", "home_id", "away_id",
                               "day", "lam", "p_model", "p_close", "y", "ll_model", "ll_close")} for r in rows])
        print(f"FEATURES {closes / 'features.json'} rows={len(rows)}", flush=True)
    print("WEIGHTS", weights, flush=True)
    print("VERDICTS", json.dumps(verdicts), flush=True)
    print("LOG LOSS", json.dumps(report["log_loss"]), "MODEL-CLOSE", report["d_model_close_all"], flush=True)
    for name, v in secondary.items():
        print(f"SUB {name:<18} n={v['n']:>4} model-close={v['d_model_close'][0]:+.4f} "
              f"[{v['d_model_close'][1]:+.4f},{v['d_model_close'][2]:+.4f}] blend-close={v['d_blend_close'][0]:+.4f} "
              f"[{v['d_blend_close'][1]:+.4f},{v['d_blend_close'][2]:+.4f}] (n={v['n_blend']})", flush=True)
    for c in calib:
        print("CALIB", c, flush=True)
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("join", "run"):
        sp = sub.add_parser(name)
        sp.add_argument("--uefa-root", required=True)
        sp.add_argument("--closes", required=True)
        if name == "run":
            # Lane uefa-market-anchored-ratings: per-match club ids + model rates for the anchored test.
            sp.add_argument("--dump-features", action="store_true", help="also write features.json under --closes")
    args = p.parse_args(argv)
    return cmd_join(args) if args.cmd == "join" else cmd_run(args)


if __name__ == "__main__":
    raise SystemExit(main())
