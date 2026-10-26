"""Print decision policy v1's gate read (the pre-registered looks) as text. READ-ONLY.

Lane `decision-policy-paper`. Reads `<data root>/reports/intelligence/decision_policy_paper/reads/<date>.json`, the
file `run_decision_policy_paper.py nightly` writes; with --run it takes the day's read first (that WRITES the read
and looks.json, exactly as the nightly job does).

    python scripts/evaluate_decision_policy_paper.py                 # the newest read
    python scripts/evaluate_decision_policy_paper.py --date 2026-11-16
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from syndicate.features.shared import decision_policy_paper as paper  # noqa: E402


def render(read: dict) -> str:
    lines = [f"DECISION POLICY v1 PAPER -- read {read.get('read_date')} (prereg {read.get('preregistration')})",
             f"gate: {read.get('gate', {}).get('verdict')} passed_by={read.get('gate', {}).get('passed_by')}"]
    for strategy, s in (read.get("strategies") or {}).items():
        g = s.get("gate_clv_sharp") or {}
        roi = s.get("roi_flat") or {}
        look = (read.get("looks") or {}).get(strategy) or {"status": "comparator"}
        lines.append(f"- {strategy}: bets={s.get('bets')} sharp-graded n={g.get('n')} games={g.get('games')} "
                     f"CLV mean={g.get('mean')}% se={g.get('se')} z={g.get('z')} ci95={g.get('ci95_boot')} | "
                     f"ROI flat n={roi.get('n')} mean={roi.get('mean')} ci95={roi.get('ci95_boot')} | "
                     f"no sharp close {s.get('no_sharp_close', {}).get('n')} | look: {look.get('status')}"
                     + (f" {look.get('look')} z={look.get('z')} >= {look.get('boundary')}? {look.get('pass')}"
                        if look.get("status") == "look_taken" else ""))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--date", default=None)
    ap.add_argument("--data-root", default=None)
    ap.add_argument("--run", action="store_true", help="take today's read first (writes it)")
    args = ap.parse_args(argv)
    root = Path(args.data_root).expanduser() if args.data_root else None
    if args.run:
        paper.run_evaluate(root)
    reads = paper.store_dir(root) / "reads"
    path = reads / f"{args.date}.json" if args.date else max(reads.glob("*.json"), default=None)
    if path is None or not path.is_file():
        print(f"no read at {reads}")
        return 1
    print(render(json.loads(path.read_text(encoding="utf-8"))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
