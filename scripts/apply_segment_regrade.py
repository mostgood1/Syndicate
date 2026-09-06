"""Apply the segment re-grade to the execution ledger. DRY-RUN BY DEFAULT.

WHAT THIS CORRECTS. `segment` reached the order row and no MLB resolver read it,
so `first5`/`first3`/`first1` bets were graded against the whole nine innings.
Measured 2026-09-05: of 173 settled segment orders, **53 outcomes are wrong**.
`scripts/regrade_segment_orders.py` computed the corrections and is deliberately
READ-ONLY; this is the separate decision its docstring reserved.

--------------------------------------------------------------------------
THE POPULATION IS 49, NOT 53, AND THE DIFFERENCE IS THE WHOLE SAFETY STORY
--------------------------------------------------------------------------
Ten of the 173 were settled BY THE VENUE (`settled_by == "venue"`), and three of
those have a changed outcome. **They are excluded, and not merely out of
deference to the venue.** For five of the ten the contract we HELD was a
full-game contract (`KXMLBTOTAL-...`), because a first5 board row matched a
whole-game series before `_segments_agree` shipped. The venue graded the
instrument we actually owned, so ITS grade is the correct grade of the bet.
"Correcting" those would invent P&L that no position earned.

    total settled segment orders          173
    settled_by == "venue"                  10   EXCLUDED, always
    inferred AND outcome_changed           49   <- what this writes
    P&L effect of applying the 49      -$31.32

--------------------------------------------------------------------------
IT OVERWRITES `outcome` AND PRESERVES THE ORIGINAL. Both, deliberately.
--------------------------------------------------------------------------
Additive-only (writing `outcome_regraded` beside a stale `outcome`) would leave
every downstream consumer -- calibration, CLV, ROI, `ledger_summary` -- still
reading the wrong field, which is the entire defect. So `outcome` is corrected.
But the as-settled value is kept in `outcome_as_settled`, with `regraded_at`,
`regrade_manifest` and `regrade_reason`, so the correction is auditable and
mechanically reversible from the row itself. A money record that cannot be
un-done is worse than one that is briefly wrong.

--------------------------------------------------------------------------
WHY WRITING IS SAFE NOW WHEN IT WAS NOT, AND WHY THAT IS CHECKED NOT ASSUMED
--------------------------------------------------------------------------
`regrade_segment_orders.py` refuses to write partly because "the ledger is
written concurrently by two services ... concurrent edits have been lost". That
was true of the BLIND whole-document write `#600` removed. `_persist` now runs
`_merge_onto_current` (execution_ledger.py:842), a three-way merge against a
baseline captured at load, so a concurrent writer is merged rather than
clobbered. This script asserts that function is present before writing, because
running it against an older build would reintroduce exactly the lost-update the
original author was protecting against.

--------------------------------------------------------------------------
IT ONLY RUNS WHERE THE LEDGER LIVES
--------------------------------------------------------------------------
The ledger is keyvalue-backed on Render. A laptop has no
`SYNDICATE_REFRESH_STATE_URL`, so `_load()` there reads an empty or local
document and a "successful" apply would silently write nothing -- the exact
absence/failure confusion this repo keeps refusing to make. So this REFUSES to
run unless the keyvalue backend is configured, rather than reporting a cheerful
zero.

    py -3 scripts/apply_segment_regrade.py --manifest reports/segment_regrade/manifest_2026-09-05.json
    py -3 scripts/apply_segment_regrade.py --manifest ... --apply
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

WRITE_FIELDS = ("outcome", "pnl_dollars", "settled_value")


def _identity(row: dict[str, Any]) -> str | None:
    """The key that finds this order in the ledger.

    `idempotency_key` rather than a composite: it is what `execution_ledger`
    itself uses to identify an order, so a composite built here could match a
    different row than the one the manifest measured.
    """
    key = str(row.get("idempotency_key") or "").strip()
    return key or None


def _selected(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    rows = manifest.get("orders") or []
    out = []
    for r in rows:
        if str(r.get("settled_by") or "").strip().lower() == "venue":
            continue  # see the module docstring -- never, under any flag
        if not r.get("outcome_changed"):
            continue
        if r.get("control_reproduces_ledger") is False:
            # The control arm could not reproduce the as-settled verdict for
            # this row, so the harness disagrees with production about it and
            # the re-grade is not trustworthy HERE specifically.
            continue
        if _identity(r):
            out.append(r)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--apply", action="store_true",
                    help="write the ledger. Without this, reports and exits.")
    args = ap.parse_args()

    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    rows = manifest.get("orders") or []
    picked = _selected(manifest)
    venue = [r for r in rows if str(r.get("settled_by") or "").lower() == "venue"]
    venue_changed = [r for r in venue if r.get("outcome_changed")]
    delta = sum(float(r.get("pnl_delta_dollars") or 0) for r in picked)

    print(f"manifest            : {args.manifest}")
    print(f"  settled segment orders   {len(rows)}")
    print(f"  settled_by=venue         {len(venue)}  EXCLUDED "
          f"({len(venue_changed)} of them changed -- deliberately not applied)")
    print(f"  to correct               {len(picked)}")
    print(f"  P&L effect               ${delta:+.2f}")
    flips: dict[str, int] = {}
    for r in picked:
        k = f"{r.get('outcome')}->{r.get('corrected_outcome')}"
        flips[k] = flips.get(k, 0) + 1
    print(f"  flips                    {flips}")

    if not args.apply:
        print("\nDRY RUN. Nothing written. Re-run with --apply on a service that "
              "has the keyvalue backend configured.")
        return 0

    from syndicate.features.shared import refresh_state_store as store
    # `_state_backend_kind`, not `_backend` -- the latter does not exist, and the
    # first version of this guard CRASHED instead of refusing. It failed closed
    # so nothing was written, but a guard that raises is not a guard: it reads as
    # a bug to be worked around rather than a refusal to be respected.
    try:
        backend = store._state_backend_kind()  # noqa: SLF001
    except Exception as exc:
        print(f"\nREFUSING: cannot determine the state backend ({exc}). Unknown "
              f"must not take the permissive branch when the next step rewrites "
              f"settled money history.")
        return 3
    if backend != "keyvalue":
        print(f"\nREFUSING: backend is {backend!r}, not 'keyvalue'. The execution "
              f"ledger is keyvalue-backed on Render; applying here would write a "
              f"LOCAL document and report success while production is untouched.")
        return 3

    from syndicate.features.shared import execution_ledger as el
    if not hasattr(el, "_merge_onto_current"):
        print("\nREFUSING: `_merge_onto_current` is absent, so `_persist` still "
              "writes the whole document blind. Two services write this ledger; "
              "a blind write is the lost-update `#600` fixed.")
        return 4

    state = el._load()  # noqa: SLF001
    by_key = {}
    for o in state.get("orders") or []:
        k = str(o.get("idempotency_key") or "").strip()
        if k:
            by_key[k] = o

    applied, missing, already = 0, [], 0
    for r in picked:
        key = _identity(r)
        row = by_key.get(key)
        if row is None:
            missing.append(key)
            continue
        if row.get("outcome_as_settled") is not None:
            already += 1
            continue  # idempotent: this row was corrected by an earlier run
        row["outcome_as_settled"] = row.get("outcome")
        row["pnl_as_settled_dollars"] = row.get("pnl_dollars")
        row["outcome"] = r.get("corrected_outcome")
        row["pnl_dollars"] = r.get("corrected_pnl_dollars")
        row["settled_value"] = r.get("corrected_settled_value")
        row["regraded_at"] = manifest.get("generated_at_utc")
        row["regrade_manifest"] = Path(args.manifest).name
        row["regrade_reason"] = "segment_graded_against_whole_game_actual"
        applied += 1

    print(f"\nledger rows            {len(by_key)}")
    print(f"  corrected            {applied}")
    print(f"  already corrected    {already}  (idempotent, left alone)")
    print(f"  NOT FOUND in ledger  {len(missing)}"
          + (f" -- first few {missing[:3]}" if missing else ""))

    if applied:
        el._persist(state)  # noqa: SLF001
        print("PERSISTED via _persist -> _merge_onto_current (concurrent writers merged).")
    else:
        print("nothing to write.")
    print("\nREVERSIBLE: every corrected row carries `outcome_as_settled` and "
          "`pnl_as_settled_dollars`.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
