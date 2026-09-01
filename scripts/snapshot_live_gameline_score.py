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


def fetch(base: str, sport: str, date: str = "", timeout: int = 120) -> dict:
    """Fetch the board. With `date`, the server RE-SCORES that past date from
    its retained live-gameline ledger, building the finals index from that
    date's grid -- so a missed night is recoverable rather than lost."""
    url = f"{base.rstrip('/')}/api/board/book-grid?sport={sport}"
    if date:
        url += f"&date={date}"
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
    ap.add_argument(
        "--date",
        default="",
        metavar="YYYY-MM-DD",
        help="Re-score a PAST slate date instead of whatever the board is "
             "currently serving. The collector runs at 23:25 CT precisely "
             "because the slate rolls at midnight Central; if a run is missed "
             "or fires pre-slate, `--date <yesterday>` recovers it from the "
             "retained ledger. Rows are stamped `backfill: true`.",
    )
    ap.add_argument(
        "--allow-date-mismatch",
        action="store_true",
        help="Append even if the board returns a different date than --date "
             "asked for. Off by default: an ignored --date would otherwise "
             "silently record today's slate under a backfill stamp.",
    )
    ap.add_argument("--print-only", action="store_true")
    args = ap.parse_args()

    if args.date:
        try:
            # strptime alone is lenient -- it accepts "2026-8-1". Round-trip
            # so only the canonical zero-padded form passes, otherwise a
            # malformed date reaches the API and fails as SCORER_DISABLED.
            if datetime.strptime(args.date, "%Y-%m-%d").strftime("%Y-%m-%d") != args.date:
                raise ValueError(args.date)
        except ValueError:
            print(f"BAD_DATE {args.date!r} -- expected YYYY-MM-DD (zero-padded)")
            return 5

    try:
        doc = fetch(args.base_url, args.sport, args.date)
    except Exception as exc:
        print(f"FETCH_FAILED {type(exc).__name__}: {exc}")
        return 2

    served = doc.get("date")
    if args.date and served != args.date:
        # UNKNOWN MUST NOT DEFAULT PERMISSIVE: if the server ignored `date`,
        # this is today's slate, and appending it as a backfill would corrupt
        # the history with a row that pooling then trusts as a past capture.
        msg = (f"DATE_MISMATCH requested={args.date} served={served} -- "
               f"the board did not honour ?date=")
        if not args.allow_date_mismatch:
            print(msg + " (use --allow-date-mismatch to append anyway)")
            return 4
        print("WARNING " + msg)

    score = doc.get("live_gameline_score") or {}
    ledger = doc.get("live_gameline_ledger") or {}
    gl = doc.get("live_gamelines") or {}
    if args.date and not score:
        # An empty score block on an HONOURED past date means no ledger was
        # retained that far back -- NOT that the scorer is off. Exit 3 is
        # documented as a real finding; do not let a stale backfill raise it.
        print(f"NO_DATA_FOR_DATE sport={args.sport} date={args.date} -- "
              f"board served the date but retained no live-gameline score")
        return 6
    if not score.get("enabled"):
        print(f"SCORER_DISABLED sport={args.sport} -- nothing to record")
        return 3

    row = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "sport": args.sport,
        "date": served,
        "board_generated_at": doc.get("generated_at"),
        # Provenance: a reconstruction must never be mistaken for a live
        # capture. Absent/false means the row came from the live board.
        "backfill": bool(args.date),
        "requested_date": args.date or None,
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
        # --- SCORER PROVENANCE. THE FIELD THAT MAKES THESE ROWS POOLABLE ---
        #
        # **ROWS WRITTEN BEFORE 2026-08-30 DESCRIBE A DIFFERENT MEASUREMENT AND
        # MUST NOT BE POOLED WITH LATER ONES.** Until `75cf9aec` the scorer
        # compared a totals `P(over)` and a spreads `P(home covers)` against
        # "did the home team win", so ~92% of the scored population was a
        # category error. The evidence is the row counts: offline h2h-only
        # scoring matches production EXACTLY on 08-30 (n=249/249, briers
        # 0.13400/0.19644 identical) and is 10-20x SMALLER on every earlier date
        # (08-20: 156 vs 3,098).
        #
        # Nothing in the row said which scorer produced it, so a pooling pass on
        # 2026-09-01 averaged across the boundary and reported "+0.04839, model
        # worse on 10 of 12 dates" -- a statement about a fixed bug, not about
        # the model. `scored_markets` is now recorded from the payload so the
        # boundary is visible IN THE DATA rather than by remembering a date.
        # A row with `scored_markets` absent is pre-fix by construction.
        "scored_markets": score.get("scored_markets"),
        "records_by_market": score.get("records_by_market"),
        # --- THE CUT A MODEL CLAIM MUST BE MADE ON (see the scorer) ---
        # Pooled over every quote age the model reads as parity (-0.00202);
        # restricted to quotes that were actually alive it LOSES (+0.01096).
        # Absent on rows captured before this field existed.
        "fresh_quotes_only": score.get("fresh_quotes_only"),
        "fresh_quote_seconds": score.get("fresh_quote_seconds"),
        "by_quote_age": score.get("by_quote_age"),
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
    fq = row.get("fresh_quotes_only") or {}
    fm, fk = (fq.get("model") or {}), (fq.get("market") or {})
    print(f"  fresh_quotes_only (<={row.get('fresh_quote_seconds')}s) "
          f"model_brier={fm.get('brier')} market_brier={fk.get('brier')} "
          f"diff={fq.get('model_minus_market_brier')} n={fm.get('n')}/{fk.get('n')}")
    print(f"  scored_markets={row.get('scored_markets')} "
          f"(absent => PRE-2026-08-30 SCORER, not poolable with later rows)")
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
