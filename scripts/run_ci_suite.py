"""Run the checks `ci.yml` runs, outside GitHub Actions.

WHY THIS EXISTS. GitHub Actions is billing-locked: no workflow run has succeeded
since 2026-08-22, and every push to `main` since -- 16 days of commits from
every session -- fails pre-step with *"The job was not started because your
account is locked due to a billing issue."* So `ci.yml` currently gates nothing,
and a green tree means only that nothing ran.

READ THIS BEFORE TREATING IT AS CI. **A scheduled run is DETECTION, not
GATING**, and the two are not interchangeable:

    ci.yml            runs on push and pull_request -- it can BLOCK a bad commit
    this, on a cron   runs on a clock -- it can only TELL YOU main is already red

Nothing here can stop a broken commit from landing. What it buys is that `main`
being red becomes knowable within a day instead of never. That is strictly
better than the current zero, and strictly worse than CI. When the billing lock
clears, `ci.yml` should be the gate again and this becomes redundant -- it is a
stopgap with a named end condition, not a replacement.

THE STEPS ARE COPIED FROM `ci.yml` VERBATIM, not re-derived, so that a
divergence between the two is a diff rather than a discovery. Both jobs:

    test             unittest archive suite, ledger coherence, hook guards
    pytest-baseline  full pytest gated on NO NEW failures against the baseline

`pytest_baseline.py` gates on the DERIVATIVE, not on green: measured 2026-08-22
on clean `origin/main`, `76 failed, 9245 passed`. A plain green gate would be
red on arrival, and `ci.yml`'s own comment explains why that is worse than
nothing -- "a check that is red on arrival is a check people learn to ignore".
So this preserves that semantics exactly rather than inventing a stricter one.

EVERY STEP RUNS EVEN IF AN EARLIER ONE FAILS. Stopping at the first failure
would hide the rest, and the whole point of a once-a-day signal is to see the
full picture in one run.

    py -3 scripts/run_ci_suite.py
    py -3 scripts/run_ci_suite.py --skip-pytest      # the fast job only
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# (label, argv) -- copied from .github/workflows/ci.yml, job `test`.
FAST_STEPS: tuple[tuple[str, list[str]], ...] = (
    ("archive regression suite", ["-m", "unittest", "tests.test_archives"]),
    ("ledger: lane identity", ["scripts/lane_identity_check.py"]),
    ("ledger: todo ids", ["scripts/todo_id_reconcile.py", "--no-history"]),
    ("ledger: state keys", ["scripts/state_key_check.py"]),
    ("hook guard: ledger commit", [".claude/hooks/test_ledger_commit_guard.py"]),
    ("hook guard: ledger append", [".claude/hooks/test_ledger_append_guard.py"]),
    ("hook guard: ledger postwrite", [".claude/hooks/test_ledger_postwrite_check.py"]),
    ("hook guard: deploys invariant", [".claude/hooks/test_ledger_deploys_invariant.py"]),
    ("hook guard: lane hyphen", [".claude/hooks/test_lane_guard_hyphen.py"]),
)

# job `pytest-baseline`. `--runnable` and the xdist flags are ci.yml's, verbatim.
PYTEST_STEP = ("pytest vs baseline",
               ["scripts/pytest_baseline.py", "--runnable", "--",
                "tests/", "-n", "auto", "--dist=loadscope"])


def run(label: str, argv: list[str], timeout: int) -> dict:
    started = time.time()
    print(f"\n=== {label} ===", flush=True)
    try:
        proc = subprocess.run([sys.executable, *argv], cwd=REPO_ROOT,
                              capture_output=True, text=True, timeout=timeout)
        rc, out = proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    except subprocess.TimeoutExpired:
        rc, out = 124, f"TIMEOUT after {timeout}s"
    tail = [l for l in out.strip().splitlines() if l.strip()][-12:]
    for l in tail:
        print("   " + l[:400], flush=True)
    print(f"   -> rc={rc}  {time.time()-started:.0f}s", flush=True)
    return {"step": label, "rc": rc, "seconds": round(time.time() - started, 1),
            "tail": tail[-6:]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-pytest", action="store_true",
                    help="run only ci.yml's `test` job, not the full suite")
    ap.add_argument("--json", type=Path, help="write the run summary here")
    args = ap.parse_args()

    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT,
                          capture_output=True, text=True).stdout.strip()
    print(f"commit      {head[:12]}")
    print(f"started     {datetime.now(timezone.utc).isoformat()}")
    print("NOTE: this is scheduled DETECTION, not per-commit gating. It cannot "
          "block a bad commit; it can only report that main is already red.")

    results = [run(label, argv, 900) for label, argv in FAST_STEPS]
    if not args.skip_pytest:
        results.append(run(*PYTEST_STEP, 3000))

    failed = [r for r in results if r["rc"] != 0]
    print("\n" + "=" * 72)
    for r in results:
        print(f"  {'FAIL' if r['rc'] else 'ok  '}  {r['step']:34s} rc={r['rc']:<4} "
              f"{r['seconds']:>6.1f}s")
    print(f"\n{len(failed)} of {len(results)} step(s) FAILED on {head[:12]}")

    summary = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "commit": head,
        "steps": results,
        "failed": [r["step"] for r in failed],
        # Stated in the artifact itself, because a consumer reading only this
        # file would otherwise reasonably assume it gated the commit it names.
        "semantics": "scheduled detection, not per-commit gating",
    }
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(f"wrote {args.json}")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
