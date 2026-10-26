"""Publish Syndicate Fair v1's fitted parameters for the DecisionRecord's SHADOW fields.

Decision Engine `#736`, lane `syndicate-decision-engine`. The user (2026-10-26): write sigma_fair_v1 (with
p_fair_v1 beside it) into the DecisionRecord in shadow for the four families that passed stage 1, and never use
p_fair_v1 for EV, pricing or staking.

What it writes: for each named family, the walk-forward's LAST fold -- the model `scripts/syndicate_fair_fit.py`
scored on the final held-out date, with that fold's residual variances -- so the record runs exactly the model
whose performance the findings report, not a refit nobody scored. Families default to the four stage-1 passes
(`.syndicate/findings_2026-10-26_syndicate_fair_v1.md`).

    py -3 scripts/publish_syndicate_fair_params.py --out C:/tmp/sfv1 --dest C:/tmp/sfv1/syndicate_fair_v1_params.json
    # then copy to <data root>/reports/syndicate_fair/syndicate_fair_v1_params.json on the fleet

Reads only the stage-1 extract (`syndicate_fair_fit.py extract`); makes no network calls.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

STAGE1_PASSES = ("ncaaf|regular|game", "nhl|regular|game", "nhl|regular|prop", "soccer|regular|game")
FINDINGS = ".syndicate/findings_2026-10-26_syndicate_fair_v1.md"


def git_blob_sha(path: Path) -> str:
    """The blob id git gives this file's bytes, so a reader can tell which library computed the params."""
    data = path.read_bytes()
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def publish(out: Path, families: list[str], log=print) -> dict:
    from scripts import syndicate_fair_fit as fit
    from syndicate.features.shared import syndicate_fair as sf

    by_sport: dict[str, list[str]] = {}
    for fam in families:
        by_sport.setdefault(fam.split("|")[0], []).append(fam)
    published: dict[str, dict] = {}
    for sport, fams in sorted(by_sport.items()):
        rows, counters = fit.assemble_sport(out, sport, {})
        log(f"ASSEMBLE {sport} rows={len(rows)} {json.dumps(counters, sort_keys=True)}")
        for fam in fams:
            fam_rows = sorted((r for r in rows if r["family"] == fam), key=lambda r: r["commence"])
            if not fam_rows:
                raise SystemExit(f"REFUSING: family {fam} has no rows in {out}")
            wf = fit.walk_forward(fam_rows, log=log)
            model, fits = wf["model"], wf["fits"]
            if model is None or not fits:
                raise SystemExit(f"REFUSING: family {fam} was never fitted (too little training data)")
            last = fits[-1]
            published[fam] = {
                "books": list(model.books),
                "theta": [float(x) for x in model.theta],
                "n_params": int(model.n_params),
                "lambda": last["lambda"],
                "r2": last["r2"],
                "last_test_date": last["test_date"],
                "train_rows": last["train_rows"],
                "train_dates": last["train_dates"],
                "train_games": last["train_games"],
                "converged": last["converged"],
            }
            log(f"PUBLISH {fam} books={len(model.books)} lambda={last['lambda']} last_test_date={last['test_date']} "
                f"train_rows={last['train_rows']} converged={last['converged']}")
    lib = REPO_ROOT / "syndicate" / "features" / "shared" / "syndicate_fair.py"
    last_date = max(v["last_test_date"] for v in published.values())
    blob = git_blob_sha(lib)
    return {
        "version": f"syndicate_fair_v1@{last_date}@{blob[:8]}",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "library_blob": blob,
        "source": "walk-forward last fold per family (scripts/syndicate_fair_fit.py walk_forward)",
        "verdict_source": FINDINGS,
        "use": "SHADOW ONLY -- recorded in the DecisionRecord; never for EV, pricing or staking (user, 2026-10-26)",
        "constants": {"TTS_BUCKETS": list(sf.TTS_BUCKETS), "AGE_EDGES_S": list(sf.AGE_EDGES_S),
                      "MARKET_FAMILIES": list(sf.MARKET_FAMILIES), "MAX_AGE_S": sf.MAX_AGE_S,
                      "MIN_BOOKS": fit.MIN_BOOKS},
        "families": published,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", required=True, help="the stage-1 extract directory (syndicate_fair_fit.py extract --out)")
    ap.add_argument("--dest", required=True, help="where to write the params JSON")
    ap.add_argument("--families", default=",".join(STAGE1_PASSES))
    args = ap.parse_args(argv)
    payload = publish(Path(args.out), [f for f in args.families.split(",") if f])
    dest = Path(args.dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".partial")
    tmp.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    tmp.replace(dest)
    print(f"WROTE {dest} version={payload['version']} families={sorted(payload['families'])}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
