"""Run the engine experts over one date's logged evidence and report (Phase 1B M1, lane `engine-experts`).

READ-ONLY. Reads the DecisionRecord (`reports/intelligence/decision_records/<date>.json.gz`), the live gameline
ledger (`<sport>_source/data/live_gameline_ledger/live_gameline_ledger_<date>.jsonl`) and the live evidence log
(`live_evidence/<sport>/<date>.jsonl`, the date before and after too, because a producer's date rolls at its own
hour). Writes nothing under the data root; `--json` / `--opinions` write where you point them.

    python scripts/engine_experts.py run --date 2026-11-09 [--sports nba,ncaab] [--json OUT] [--opinions OUT.jsonl]

Prints, per sport:
  COVERAGE    one line per (phase, clock bucket, expert): lines, opined, share, median |delta|, median sigma, refusals
  JOIN        the live re-sim expert against the live join's own model probability, same lane state, half-point
              totals/spreads (the gate: mismatched must be 0); whole-number lines and moneylines reported beside it
  CHECKLIST   model_engine_standard.md §1: an input an expert CONSUMED this run that is unpopulated on real rows, or
              an output field at its default on every opined opinion, unless documented in EXPECTED_SPARSE

Exit 1 on any checklist alarm or any JOIN mismatch; 0 otherwise. Run on the fleet with the worker's environment, at
nice 19 (it reads ~50 MB of NBA ledger on a busy night).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from syndicate.features.shared import engine_experts as ee  # noqa: E402

LIVE_SPORTS = ("nba", "ncaab", "wncaab", "nhl", "nfl", "ncaaf", "wnba")


def _days_around(d: str) -> list[str]:
    day = date.fromisoformat(d)
    return [(day + timedelta(days=k)).isoformat() for k in (-1, 0, 1)]


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not path.exists():
        return out
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict):
                out.append(row)
    return out


def pregame(date_str: str, sports: set[str] | None, root: Path | None) -> dict[str, Any]:
    from syndicate.features.shared import decision_record as dr

    doc = dr.read_records(date_str, root=root)
    if not isinstance(doc, dict):
        return {"present": False, "by_sport": {}}
    t = str(doc.get("written_at") or "")
    records = [dr.expand_record(r) for r in doc.get("records") or [] if isinstance(r, dict)]
    by_sport: dict[str, list[Any]] = {}
    for rec in records:
        sport = str(rec.identity.sport or "").lower()
        if sports and sport not in sports:
            continue
        by_sport.setdefault(sport, []).append(rec)
    out: dict[str, Any] = {"present": True, "t": t, "build_id": doc.get("build_id"), "by_sport": {}}
    for sport, recs in sorted(by_sport.items()):
        reader = ee.Reader()
        ops = ee.pregame_opinions(recs, t, reader)
        out["by_sport"][sport] = {"opinions": ops, "checklist": ee.checklist(
            ops, reader, {"decision_record": recs}, sport=sport)}
    return out


def live(date_str: str, sports: set[str] | None, root: Path | None) -> dict[str, Any]:
    from syndicate.features.shared import live_evidence_log as lel
    from syndicate.features.shared import live_gameline_ledger as lgl

    out: dict[str, Any] = {}
    for sport in LIVE_SPORTS:
        if sports and sport not in sports:
            continue
        ledger_rows = _read_jsonl(lgl.ledger_path(sport, date_str))
        if not ledger_rows:
            continue
        evidence = [row for d in _days_around(date_str) for row in lel.iter_rows(sport, d, root=root)]
        index = ee.EvidenceIndex(evidence)
        reader = ee.Reader()
        ops = ee.live_opinions(ledger_rows, index, reader)
        # The ledger's refusal rows carry no lane state or prices by design; a populated share over them would
        # dilute every input. The checklist measures the PRICED rows, the population the expert reads.
        priced = [row for row in ledger_rows if not ee.is_ledger_refusal_row(row)]
        out[sport] = {
            "opinions": ops,
            "ledger_rows": len(ledger_rows),
            "ledger_refusal_rows": len(ledger_rows) - len(priced),
            "evidence_rows": len(evidence),
            "join": ee.join_reproduction(ops),
            "checklist": ee.checklist(ops, reader, {"live_gameline_ledger": priced, "live_evidence": evidence},
                                      sport=sport),
        }
    return out


def _print_coverage(sport: str, ops: list[Any]) -> None:
    for row in ee.coverage(ops):
        refusals = ", ".join(f"{k} {v}" for k, v in list(row["refusals"].items())[:4])
        print(f"   COVERAGE {sport:7s} {row['phase']:7s} {row['bucket']:6s} {row['expert']:10s} lines={row['lines']:6d} "
              f"opined={row['opined']:6d} share={row['share']} med|d|={row['median_abs_delta']} "
              f"mean_d={row['mean_delta']} med_sigma={row['median_sigma']} | {refusals}")


def run(args: argparse.Namespace) -> int:
    root = Path(args.root) if args.root else None
    sports = {s.strip().lower() for s in args.sports.split(",")} if args.sports else None
    bad = 0
    report: dict[str, Any] = {"date": args.date, "pregame": {}, "live": {}}
    all_ops: list[Any] = []

    pre = pregame(args.date, sports, root)
    print(f"PREGAME date={args.date} record_file={'present' if pre['present'] else 'MISSING'} t={pre.get('t')} "
          f"build={pre.get('build_id')}")
    for sport, block in pre["by_sport"].items():
        ops = block["opinions"]
        all_ops += ops
        _print_coverage(sport, ops)
        cl = block["checklist"]
        print(f"   CHECKLIST {sport} pregame ok={cl['ok']} alarms={len(cl['alarms'])}")
        for a in cl["alarms"][:12]:
            print("      ALARM", json.dumps(a, default=str))
        bad += len(cl["alarms"])
        report["pregame"][sport] = {"coverage": ee.coverage(ops), "checklist": cl}

    lv = live(args.date, sports, root)
    for sport, block in lv.items():
        ops = block["opinions"]
        all_ops += ops
        print(f"LIVE sport={sport} ledger_rows={block['ledger_rows']} (refusal rows {block['ledger_refusal_rows']}) "
              f"evidence_rows={block['evidence_rows']}")
        _print_coverage(sport, ops)
        j = block["join"]
        print(f"   JOIN {sport} half_point checked={j['checked']} mismatched={j['mismatched']} | "
              f"whole_number checked={j['whole_number']['checked']} differ={j['whole_number']['differ']} "
              f"mean(expert-join)={j['whole_number']['mean_expert_minus_join']} | h2h checked={j['h2h']['checked']} "
              f"differ={j['h2h']['differ']}")
        for ex in j["examples"][:5]:
            print("      MISMATCH", json.dumps(ex, default=str))
        bad += j["mismatched"]
        cl = block["checklist"]
        print(f"   CHECKLIST {sport} live ok={cl['ok']} alarms={len(cl['alarms'])}")
        for a in cl["alarms"][:12]:
            print("      ALARM", json.dumps(a, default=str))
        bad += len(cl["alarms"])
        report["live"][sport] = {"coverage": ee.coverage(ops), "join": j, "checklist": cl,
                                 "ledger_rows": block["ledger_rows"], "evidence_rows": block["evidence_rows"]}

    if args.json:
        Path(args.json).write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
    if args.opinions:
        with open(args.opinions, "w", encoding="utf-8") as fh:
            for op in all_ops:
                fh.write(json.dumps(op.to_dict(), separators=(",", ":"), default=str) + "\n")
    print(f"RESULT date={args.date} opinions={len(all_ops)} alarms_plus_mismatches={bad} exit={1 if bad else 0}")
    return 1 if bad else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--date", required=True)
    r.add_argument("--sports", default=None)
    r.add_argument("--root", default=None, help="data root override (default: the store's data root)")
    r.add_argument("--json", default=None)
    r.add_argument("--opinions", default=None)
    args = ap.parse_args(argv)
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
