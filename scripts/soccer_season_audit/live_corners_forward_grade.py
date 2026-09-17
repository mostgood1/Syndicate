# -*- coding: utf-8 -*-
"""H32, forward: are the PUBLISHED live corners (pre-kickoff estimate over the clock) better than the sim's?

Lane `soccer-live-corners-stage2`. The rules are the registration, not this file:
`.syndicate/log/2026-09-17.md` ~15:05 CT (H32), with its operational cadence amended ~17:10 CT (harvest
every 15 minutes, because `live_state` keeps only in-play matches) and the durable capture of 22:44:03Z
(`projection_history` inside the artifact).

    population  snapshots whose `corners_basis` is `prekickoff_pace_v1` and that carry
                `sim_projected_total_corners`, for matches with an ESPN final corners count for both teams
    per match   the LAST snapshot in each bucket 20-40', 40-60', 60-80'
    arms        published = `projected_total_corners`; sim = `sim_projected_total_corners`, from the SAME
                snapshot -- paired by construction, no replay, no ratings question
    metric      MAE against the final total, pooled over buckets; paired match-clustered bootstrap,
                2000 reps, seed 11, 95%
    verdict     MET iff the CI of mean(|err published| - |err sim|) lies entirely below 0; graded at
                100 matches or 2026-11-15, whichever is first; with fewer by then, INSUFFICIENT

Reported, never graded: per bucket, per league, each arm's bias, and the share of snapshots in the window
whose audit state was not `applied` (the production reachability reading).

    py -3 scripts/soccer_season_audit/live_corners_forward_grade.py pull  --harvest <dir> --cache <dir>
    py -3 scripts/soccer_season_audit/live_corners_forward_grade.py grade --harvest <dir> --cache <dir>

`--harvest` is where `harvest_live_projections.py` writes (`live_projections_<date>.jsonl`). `pull` fetches
ESPN match summaries for the events it finds there; `grade` never touches the network.
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import io
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
CHECKOUT = HERE.parents[1]
for p in (str(HERE), str(CHECKOUT)):
    if p not in sys.path:
        sys.path.insert(0, p)

LIVE_BASIS = "prekickoff_pace_v1"
BUCKETS = ((20.0, 40.0), (40.0, 60.0), (60.0, 80.0))
HALF_SECONDS = 45.0 * 60.0
GRADE_MATCHES = 100
GRADE_DATE = dt.date(2026, 11, 15)
BOOT_REPS, BOOT_SEED = 2000, 11


# ---------------------------------------------------------------------------- snapshots (pure)

def elapsed_minutes(row: dict) -> float | None:
    """Match minutes played at the snapshot, from its own half and remaining clock."""
    try:
        half = int(row.get("half"))
        remaining = float(row.get("clock_remaining"))
    except (TypeError, ValueError):
        return None
    return max(0.0, (half - 1) * HALF_SECONDS + (HALF_SECONDS - remaining)) / 60.0


def bucket_of(minute: float | None) -> tuple[float, float] | None:
    if minute is None:
        return None
    for lo, hi in BUCKETS:
        # half-open, except the last bucket includes its upper edge (80')
        if lo <= minute < hi or (hi == BUCKETS[-1][1] and minute == hi):
            return (lo, hi)
    return None


def audit_state(row: dict) -> str | None:
    """History rows carry `live_corners_state`; live-block rows carry the whole audit under `live_corners`."""
    if row.get("live_corners_state") is not None:
        return str(row["live_corners_state"])
    audit = row.get("live_corners")
    return str(audit.get("state")) if isinstance(audit, dict) and audit.get("state") is not None else None


def load_harvest(harvest_dir: Path) -> list[dict]:
    rows = []
    for path in sorted(Path(harvest_dir).glob("live_projections_*.jsonl")):
        with io.open(path, encoding="utf-8") as handle:
            for line in handle:
                try:
                    rows.append(json.loads(line))
                except Exception:  # noqa: BLE001 -- a half-written last line is expected on a live cache
                    continue
    return rows


def pick_snapshots(rows: list[dict]) -> tuple[dict, collections.Counter]:
    """(league, event_id) -> {bucket: row}, the LAST eligible snapshot per bucket, plus a funnel."""
    funnel = collections.Counter()
    chosen: dict = collections.defaultdict(dict)
    for row in rows:
        funnel["snapshots"] += 1
        bucket = bucket_of(elapsed_minutes(row))
        if bucket is None:
            continue
        funnel["in_a_bucket"] += 1
        state = audit_state(row)
        if state is not None and state != "applied":
            funnel[f"audit_{state}"] += 1
        if row.get("corners_basis") != LIVE_BASIS or row.get("sim_projected_total_corners") is None \
                or row.get("projected_total_corners") is None:
            continue
        funnel["eligible"] += 1
        key = (str(row.get("league")), str(row.get("event_id")))
        held = chosen[key].get(bucket)
        if held is None or str(row.get("generated_at") or "") > str(held.get("generated_at") or ""):
            chosen[key][bucket] = row
    return dict(chosen), funnel


# ---------------------------------------------------------------------------- statistics + verdict

def paired_boot(units: list[list[float]], reps: int = BOOT_REPS, seed: int = BOOT_SEED):
    """Mean of the pooled differences, and a match-clustered percentile CI (a match's buckets move together)."""
    import random

    stat = lambda s: sum(sum(u) for u in s) / max(sum(len(u) for u in s), 1)  # noqa: E731
    if not units:
        return float("nan"), (float("nan"), float("nan"))
    point = stat(units)
    if len(units) < 5:
        return point, (float("nan"), float("nan"))
    rng = random.Random(seed)
    k = len(units)
    vals = sorted(stat([units[rng.randrange(k)] for _ in range(k)]) for _ in range(reps))
    return point, (vals[int(0.025 * reps)], vals[int(0.975 * reps) - 1])


def verdict(n_matches: int, ci_hi: float, today: dt.date) -> str:
    if n_matches >= GRADE_MATCHES:
        return "MET" if (ci_hi == ci_hi and ci_hi < 0) else "FALSIFIED"
    return "WATCHING" if today < GRADE_DATE else "INSUFFICIENT"


def _mean(xs):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else float("nan")


def grade(harvest_dir: Path, cache: Path, today: dt.date | None = None) -> dict:
    from forward_grade import outcome_from_summary, today_ct  # noqa: E402 -- the audit's box-score reader

    today = today or today_ct()
    rows = load_harvest(harvest_dir)
    chosen, funnel = pick_snapshots(rows)

    finals: dict = {}
    for path in Path(cache, "espn").glob("*.json"):
        league, _, event = path.stem.partition("__")
        try:
            outcome = outcome_from_summary(json.loads(path.read_text(encoding="utf-8")))
        except Exception:  # noqa: BLE001
            continue
        home = (outcome.get("teams") or {}).get("home") or {}
        away = (outcome.get("teams") or {}).get("away") or {}
        if outcome.get("completed") and home.get("wonCorners") is not None and away.get("wonCorners") is not None:
            finals[(league, event)] = float(home["wonCorners"]) + float(away["wonCorners"])

    units, per_bucket, per_league = [], collections.defaultdict(list), collections.defaultdict(list)
    for key, buckets in chosen.items():
        funnel["matches_with_an_eligible_snapshot"] += 1
        final = finals.get(key)
        if final is None:
            continue
        funnel["matches_graded"] += 1
        diffs = []
        for bucket, row in buckets.items():
            err_pub = float(row["projected_total_corners"]) - final
            err_sim = float(row["sim_projected_total_corners"]) - final
            record = {"pub": err_pub, "sim": err_sim}
            per_bucket[bucket].append(record)
            per_league[key[0]].append(record)
            diffs.append(abs(err_pub) - abs(err_sim))
        units.append(diffs)

    pooled = [r for rs in per_bucket.values() for r in rs]
    point, (lo, hi) = paired_boot(units)
    in_window = funnel["in_a_bucket"]
    not_applied = sum(v for k, v in funnel.items() if k.startswith("audit_"))
    report = {
        "today": today.isoformat(),
        "funnel": dict(funnel),
        "matches": len(units),
        "snapshots_graded": len(pooled),
        "mae_published": _mean(abs(r["pub"]) for r in pooled),
        "mae_sim": _mean(abs(r["sim"]) for r in pooled),
        "bias_published": _mean(r["pub"] for r in pooled),
        "bias_sim": _mean(r["sim"] for r in pooled),
        "diff": point, "ci": (lo, hi),
        "per_bucket": {f"{int(b[0])}-{int(b[1])}": {"n": len(rs), "mae_published": _mean(abs(r["pub"]) for r in rs),
                                                     "mae_sim": _mean(abs(r["sim"]) for r in rs)}
                       for b, rs in sorted(per_bucket.items())},
        "per_league": {lg: {"n": len(rs), "mae_published": _mean(abs(r["pub"]) for r in rs),
                            "mae_sim": _mean(abs(r["sim"]) for r in rs)} for lg, rs in sorted(per_league.items())},
        "share_not_applied_in_window": (not_applied / in_window) if in_window else float("nan"),
    }
    report["verdict"] = verdict(report["matches"], hi, today)
    return report


# ---------------------------------------------------------------------------- pull (network)

def pull(harvest_dir: Path, cache: Path) -> dict:
    """ESPN summaries for every event the harvest has seen, cached; a finished one is fetched once."""
    from forward_grade import outcome_from_summary  # noqa: E402
    from syndicate.features.soccer.ingestion.espn_lineups import fetch_match_summary  # noqa: E402

    (Path(cache) / "espn").mkdir(parents=True, exist_ok=True)
    events = sorted({(str(r.get("league")), str(r.get("event_id"))) for r in load_harvest(harvest_dir)
                     if r.get("league") and r.get("event_id")})
    tally = collections.Counter()
    for league, event in events:
        dest = Path(cache) / "espn" / f"{league}__{event}.json"
        if dest.exists():
            try:
                if outcome_from_summary(json.loads(dest.read_text(encoding="utf-8"))).get("completed"):
                    tally["cached_final"] += 1
                    continue
            except Exception:  # noqa: BLE001
                pass
        try:
            summary = fetch_match_summary(league, event)
        except Exception as exc:  # noqa: BLE001 -- counted, never silent
            tally[f"fail_{type(exc).__name__}"] += 1
            continue
        dest.write_text(json.dumps(summary), encoding="utf-8")
        tally["fetched"] += 1
        time.sleep(0.35)
    tally["events"] = len(events)
    return dict(tally)


def print_report(r: dict) -> None:
    print(f"H32 {r['today']}: funnel {r['funnel']}")
    print(f"  matches graded {r['matches']}, snapshots {r['snapshots_graded']}  |  MAE published {r['mae_published']:.3f} "
          f"vs sim {r['mae_sim']:.3f}  |  bias {r['bias_published']:+.3f} vs {r['bias_sim']:+.3f}")
    print(f"  mean |err| diff (published - sim) {r['diff']:+.4f} [{r['ci'][0]:+.4f}, {r['ci'][1]:+.4f}]  "
          f"audit not 'applied' in window: {r['share_not_applied_in_window']:.3f}")
    for name, v in r["per_bucket"].items():
        print(f"    {name:>6}'  n {v['n']:4d}  published {v['mae_published']:.3f}  sim {v['mae_sim']:.3f}")
    for lg, v in r["per_league"].items():
        print(f"    {lg:20s} n {v['n']:4d}  published {v['mae_published']:.3f}  sim {v['mae_sim']:.3f}")
    print("H32:", r["verdict"])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("pull", "grade"):
        p = sub.add_parser(name)
        p.add_argument("--harvest", required=True)
        p.add_argument("--cache", required=True)
        if name == "grade":
            p.add_argument("--today", help="YYYY-MM-DD (CT); default today")
    args = ap.parse_args(argv)
    if args.cmd == "pull":
        print(json.dumps(pull(Path(args.harvest), Path(args.cache)), sort_keys=True))
        return 0
    today = dt.date.fromisoformat(args.today) if args.today else None
    report = grade(Path(args.harvest), Path(args.cache), today)
    Path(args.cache).mkdir(parents=True, exist_ok=True)
    Path(args.cache, "live_corners_forward_grade.json").write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
    print_report(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
