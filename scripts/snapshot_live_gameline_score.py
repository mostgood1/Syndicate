"""Snapshot the live-gameline model-vs-market score into an accumulating history.

WHY THIS EXISTS. `live_gameline_score` is computed on every board build and
served on `/api/board/book-grid`, but it is a SNAPSHOT of one build -- nothing
retains it. On 2026-08-20 it read `model_minus_market_brier +0.04006` on the
`priceable_only` cut, which sounds decisive and is not: it rested on
`games_with_outcome: 3`. The 985/1449/1526 record counts are repeated snapshots
of those same games, not independent trials.

So the blocker on this lane is SAMPLE SIZE, not access. This appends one row per
run to a JSONL history, keyed on date, so `games_with_outcome` accumulates until
the comparison means something.

WHAT IT DELIBERATELY DOES NOT DO. It does not average Briers across days --
that would weight a 3-game day equally with a 15-game day. It stores the raw
per-day components so a later pass can pool them correctly, weighted by the
independent unit (games), which is the denominator that matters.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DEFAULT_BASE = "https://syndicate-an21.onrender.com"
HISTORY = REPO / "reports" / "live_gameline_accuracy" / "history.jsonl"


def _admin_token() -> str:
    tok = os.environ.get("ADMIN_TOKEN", "").strip()
    if tok:
        return tok
    env = REPO / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("ADMIN_TOKEN="):
                return line.split("=", 1)[1].strip().strip('"')
    return ""


def fetch(base: str, sport: str, timeout: int = 120) -> dict:
    url = f"{base.rstrip('/')}/api/board/book-grid?sport={sport}"
    req = urllib.request.Request(url)
    tok = _admin_token()
    if tok:
        req.add_header("Authorization", f"Bearer {tok}")
    with urllib.request.urlopen(req, timeout=timeout) as fh:
        return json.loads(fh.read().decode("utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sport", default="mlb")
    ap.add_argument("--base-url", default=DEFAULT_BASE)
    ap.add_argument("--out", default=str(HISTORY))
    ap.add_argument("--print-only", action="store_true")
    args = ap.parse_args()

    try:
        doc = fetch(args.base_url, args.sport)
    except Exception as exc:
        print(f"FETCH_FAILED {type(exc).__name__}: {exc}")
        return 2

    score = doc.get("live_gameline_score") or {}
    ledger = doc.get("live_gameline_ledger") or {}
    gl = doc.get("live_gamelines") or {}
    if not score.get("enabled"):
        print(f"SCORER_DISABLED sport={args.sport} -- nothing to record")
        return 3

    row = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "sport": args.sport,
        "date": doc.get("date"),
        "board_generated_at": doc.get("generated_at"),
        # THE DENOMINATOR THAT MATTERS. Record counts are repeated snapshots of
        # the same games; this is the independent unit.
        "games_with_outcome": score.get("games_with_outcome"),
        "records_considered": score.get("records_considered"),
        "unscored": score.get("unscored"),
        # `priceable_only` is the SOUND cut: same population both sides. In
        # `all_records` the model and market n differ (1526 vs 1449 on
        # 2026-08-20), so that Brier difference spans different row sets.
        "priceable_only": score.get("priceable_only"),
        "all_records": score.get("all_records"),
        "last_per_game": score.get("last_per_game"),
        # v2 discriminator: `written` above `priceable` proves non-priceable
        # rows are recorded, i.e. the ledger measures the MODEL and not the
        # publish gate.
        "ledger_written": ledger.get("written"),
        "ledger_candidates": ledger.get("candidates"),
        "rows_priceable": gl.get("rows_live_gameline_priceable"),
        "rows_considered": gl.get("rows_live_gameline_considered"),
        "withheld_by_reason": gl.get("withheld_by_reason"),
    }

    po = row.get("priceable_only") or {}
    m, k = (po.get("model") or {}), (po.get("market") or {})
    print(f"date={row['date']} games_with_outcome={row['games_with_outcome']} "
          f"priceable_only model_brier={m.get('brier')} market_brier={k.get('brier')} "
          f"diff={po.get('model_minus_market_brier')} n={m.get('n')}/{k.get('n')}")
    print(f"  ledger written={row['ledger_written']} candidates={row['ledger_candidates']} "
          f"priceable={row['rows_priceable']} "
          f"(v2 discriminator satisfied: {bool((row['ledger_written'] or 0) > (row['rows_priceable'] or 0))})")

    if args.print_only:
        return 0

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with io.open(out, "a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(row, sort_keys=True) + "\n")
    n = sum(1 for _ in io.open(out, encoding="utf-8"))
    print(f"appended -> {out}  ({n} row(s) total)")
    return 0


if __name__ == "__main__":
    import io  # noqa: E402  (used above; imported late to keep the header clean)
    sys.exit(main())
