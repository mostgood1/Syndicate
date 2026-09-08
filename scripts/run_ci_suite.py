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

THE STEPS RUN WITH RENDER'S OWN ENV VARS SCRUBBED -- see `_step_env()`, and it
is load-bearing rather than tidying. `RENDER` is injected on every Render
service type, cron jobs included, so a suite running ON a cron trips every
production branch gated on it and ends up measuring its own host. Measured
2026-09-08: this cron reported `Ran 386 tests ... FAILED (failures=18,
errors=21)` for a commit that is `OK (skipped=2)` off Render, and setting
`RENDER=true` on a laptop reproduced both counts exactly.

**A red step here has to mean "main is red" and nothing else, because that
sentence is this job's entire product.** A host that silently changes the
answer is therefore not a nuisance, it is the one failure mode that makes the
whole job worse than having no job -- it manufactures the alarm it exists to
raise. Scrubbing is also what keeps the promise made four paragraphs up: GitHub
runners have no `RENDER`, so this is what makes the cron run `ci.yml`'s
experiment rather than a neighbouring one.

Do NOT fix a recurrence by adding the specific `SYNDICATE_*` override that
silences it. That was tried first here: `SYNDICATE_WEB_DYNO=0` moved 18/21 to
4/19 and stalled, because it answers one of nineteen bare-`RENDER` reads across
ten files, and the next one along (`refresh_state_store.data_root()`) fails in
a completely different shape -- a `RuntimeError`, not an assertion.

    py -3 scripts/run_ci_suite.py
    py -3 scripts/run_ci_suite.py --skip-pytest      # the fast job only
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# Per-step wall-clock caps, in seconds.
#
# FAST_STEP_TIMEOUT is comfortable: the whole fast job runs in ~47s on the cron.
#
# PYTEST_TIMEOUT_DEFAULT is a CEILING, NOT A MEASUREMENT, and it is written
# that way because nobody has yet seen this step finish on a Render cron. The
# old value was 3000s and the 2026-09-08 08:00Z run hit it exactly (rc=124 at
# 3001s) with no idea how far it had got -- the timeout branch discarded its
# output, which is the other half of this file that just changed.
#
# What is actually known:
#   ci.yml    45min serial -> 12min at `-n auto` on a 4-core GitHub runner,
#             and it allows `timeout-minutes: 60`.
#   this cron `standard` = 2GB / 1 CPU. `--pytest-workers 2` was picked the
#             evening before to stop an `oomKilled memoryLimit 2Gi` on
#             `-n auto`, and two xdist workers on ONE cpu is serial plus
#             overhead, not a 2x. That trade bought memory and spent
#             wall-clock, and this constant was not moved with it.
#
# So 7200s is "generous enough that a real rc becomes reachable", chosen to
# stop a clock from masquerading as a test result. THE FIRST RUN THAT FINISHES
# SHOULD REPLACE IT with the measured duration plus headroom; until then it is
# a guess and is labelled one.
FAST_STEP_TIMEOUT = 900
PYTEST_TIMEOUT_DEFAULT = 7200

# `#647`. THE KNOB THAT WORKER COUNT WAS NOT.
#
# The pytest step was OOM-killed at 2Gi in every worker configuration tried,
# and REDUCING workers made it fail SOONER (`-n 0` at 537s against `-n 2`'s
# 1056s) -- because `-n 0` is the floor for PROCESS COUNT, not for PEAK MEMORY.
# One process must hold what the whole suite accumulates. Measured locally on
# the same command, sampling the process tree: a **2443 MB peak** against a
# 2048 MB limit, on a box with no cgroup accounting and no page cache counted.
#
# Chunking is the lever that actually moves it: N sequential processes each
# hold roughly 1/N of the accumulation, and `pytest_baseline.py` unions their
# results so the gate still compares a whole-suite failure set.
#
# 8 IS NOT MEASURED. It is chosen to leave real headroom against a peak that is
# ~1.2x the limit -- the peak is set by the WORST chunk, not the average, and
# the observed shape (flat, then a steep second climb) says cost is not evenly
# spread. Replace it with a measured value once a run completes on the cron.
PYTEST_CHUNKS_DEFAULT = 8

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

# job `pytest-baseline`. `--runnable` and `--dist=loadscope` are ci.yml's,
# verbatim. The WORKER COUNT is the one deliberate divergence and it is a
# parameter rather than a different constant, so the difference is visible at
# the call site instead of buried here.
#
# WHY IT HAD TO BECOME A KNOB. `-n auto` is correct on GitHub's runner (16GB)
# and fatal on a Render cron: the first real run died at 18:36:44Z with
# `Your cronjob failed because of an error: Out of memory (used over 2Gi)`,
# inside this step. `-n auto` spawns one xdist worker per CPU and each holds a
# full import of the app, so the peak scales with core count on a box that has
# more cores than gigabytes.
def _pytest_step(workers: str, chunks: int) -> tuple[str, list[str]]:
    return ("pytest vs baseline",
            ["scripts/pytest_baseline.py", "--runnable", "--chunks", str(chunks), "--",
             "tests/", "-n", workers, "--dist=loadscope"])


# Environment variables RENDER INJECTS to describe the host, scrubbed from
# every step's child environment by `_step_env()`.
#
# `RENDER_API_KEY` is deliberately NOT here: Render does not inject it, it is a
# user-set secret, and scrubbing someone's credential to fix a host-detection
# bug would be a second bug. This is an allowlist of injected names for exactly
# that reason, not a `RENDER_*` wildcard.
RENDER_INJECTED_ENV = (
    "RENDER",
    "RENDER_SERVICE_ID",
    "RENDER_SERVICE_NAME",
    "RENDER_SERVICE_TYPE",
    "RENDER_INSTANCE_ID",
    "RENDER_EXTERNAL_URL",
    "RENDER_EXTERNAL_HOSTNAME",
    "RENDER_GIT_COMMIT",
    "RENDER_GIT_BRANCH",
    "RENDER_GIT_REPO_SLUG",
    "RENDER_DISCOVERY_SERVICE",
)


def _step_env() -> dict[str, str]:
    """The child environment for every step: this host, minus "I am Render".

    THE TESTS WERE MEASURING THE HOST. Measured 2026-09-08 on the `ci-suite`
    cron: `Ran 386 tests ... FAILED (failures=18, errors=21)` where the same
    commit is `OK (skipped=2)` off Render. `RENDER` is injected on every Render
    service type -- web, worker AND cron job -- so a suite running ON a cron
    trips every production branch gated on it. Setting `RENDER=true` locally
    reproduced the cron's counts exactly.

    WHY SCRUBBING AND NOT `SYNDICATE_WEB_DYNO=0` ON THE SERVICE. That was the
    first fix tried and it is a per-symptom one: it moved 18/21 to 4/19 and
    stopped, because it addresses ONE of nineteen bare-`RENDER` reads across
    ten files. The next one along is `refresh_state_store.data_root()`, which
    escalates a missing `SYNDICATE_DATA_ROOT` into a `RuntimeError` only when
    the host says Render. Feeding that chain the roots it wants would make the
    suite pass by making it test a THIRD configuration -- neither this repo's
    tests nor production.

    WHY THIS IS THE FAITHFUL CHOICE, not just the convenient one: this file's
    whole contract is that its steps are `ci.yml`'s verbatim, "so that a
    divergence between the two is a diff rather than a discovery". GitHub
    runners have no `RENDER`. Scrubbing it is what makes the cron run the SAME
    experiment as CI; inheriting it is the silent divergence.

    A test that genuinely wants the hosted branch should set the variable
    itself -- `patch.dict(os.environ, ...)` -- which is what a test asserting
    on configuration should do regardless of where it runs.
    """
    env = dict(os.environ)
    for key in RENDER_INJECTED_ENV:
        env.pop(key, None)
    return env


def _pump(pipe, sink: list[str], echo: bool) -> None:
    """Drain a pipe line by line, echoing as it goes.

    A thread rather than iterating in the caller, because a blocking read on a
    hung child would make the timeout unenforceable -- the whole point is to
    kill a step that has stopped making progress.
    """
    try:
        for raw in pipe:
            line = raw.rstrip("\n")
            sink.append(line)
            if echo:
                print("   " + line[:400], flush=True)
    except Exception:  # noqa: BLE001 -- a broken pipe must not kill the run
        pass


def run(label: str, argv: list[str], timeout: int, *, stream: bool = False) -> dict:
    """Run one step. `stream=True` echoes its output live instead of at the end.

    WHY STREAMING IS NOT COSMETIC. With output captured, a step is SILENT for
    its entire run and everything it printed is lost the moment the process is
    killed by anything that also kills this parent. Measured 2026-09-08: the
    pytest step ran 17.6 minutes and was OOM-killed at 2Gi, and Render's log for
    that window contains **zero lines** -- the container went, parent included,
    so no handler ran and no tail was ever printed. The diagnosis rested
    entirely on Render's own `oomKilled` event.

    Echoing as the child produces it puts every line in the log BEFORE the kill,
    so an OOM now leaves a trail up to the moment it died instead of erasing the
    run. That is the failure mode the previous fix could not reach: it handled
    `TimeoutExpired`, where a killed CHILD is still readable, and an OOM is not
    that shape.

    It also removes the need to recover output from the exception. The buffer is
    filled as we go, so a timeout has the same lines a success would -- no
    dependence on `TimeoutExpired.stdout`, whose type differs by platform.

    Off by default: the fast steps finish in under a minute and their 12-line
    tail is the right granularity. This is for the step that runs for an hour.
    """
    started = time.time()
    timed_out = False
    print(f"\n=== {label} ===", flush=True)
    lines: list[str] = []
    proc = subprocess.Popen(
        [sys.executable, *argv], cwd=REPO_ROOT, env=_step_env(),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1, errors="replace")
    pump = threading.Thread(target=_pump, args=(proc.stdout, lines, stream), daemon=True)
    pump.start()
    try:
        rc = proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        # A CAP HIT IS NOT A TEST RESULT, and it is labelled so on purpose.
        # `learnings.md` 2026-08-20, FORBIDDEN: reading a KILLED pytest run as a
        # result -- a 12-failure report was invented from truncated output and
        # used to argue for rolling back three verified deploys. What this
        # licenses is "it reached HERE", never "these are the failures".
        timed_out = True
        rc = 124
        proc.kill()
        proc.wait()
        print(f"   TIMED OUT after {timeout}s -- rc=124. Anything above is "
              f"PARTIAL OUTPUT FROM A KILLED RUN, not a result: it says how far "
              f"it got, and nothing about what passed or failed.", flush=True)
    pump.join(timeout=10)
    tail = [l for l in lines if l.strip()][-12:]
    if not stream:
        for l in tail:
            print("   " + l[:400], flush=True)
    # SAID IN BOTH MODES. "Produced nothing" and "produced something I am not
    # showing you" are different facts, and a step that dies silently is the
    # case where the distinction matters most -- it is the difference between
    # a hang and a crash before first output.
    if not tail:
        print("   (the step produced no output at all)", flush=True)
    print(f"   -> rc={rc}  {time.time()-started:.0f}s", flush=True)
    return {"step": label, "rc": rc, "seconds": round(time.time() - started, 1),
            "timed_out": timed_out, "tail": tail[-6:]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-pytest", action="store_true",
                    help="run only ci.yml's `test` job, not the full suite")
    ap.add_argument("--pytest-workers", default="auto",
                    help="xdist worker count. ci.yml uses 'auto'; a 2Gi Render "
                         "cron cannot afford that (it OOM'd at 18:36:44Z on "
                         "2026-09-07) because each worker holds a full app "
                         "import. Pass a small integer there.")
    ap.add_argument("--pytest-chunks", type=int, default=PYTEST_CHUNKS_DEFAULT,
                    help="run the suite in N sequential pytest processes, unioning the "
                         "results. This is the knob that WORKER COUNT was not: measured "
                         "2026-09-08, the suite peaks at 2443 MB in one process against "
                         "a 2048 MB limit.")
    ap.add_argument("--pytest-timeout", type=int, default=PYTEST_TIMEOUT_DEFAULT,
                    help="wall-clock cap for the pytest step, seconds. A cap "
                         "hit is rc=124 and is NOT a test result -- see the "
                         "timeout branch in run().")
    ap.add_argument("--json", type=Path, help="write the run summary here")
    args = ap.parse_args()

    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT,
                          capture_output=True, text=True).stdout.strip()
    print(f"commit      {head[:12]}")
    print(f"started     {datetime.now(timezone.utc).isoformat()}")
    print("NOTE: this is scheduled DETECTION, not per-commit gating. It cannot "
          "block a bad commit; it can only report that main is already red.")

    results = [run(label, argv, FAST_STEP_TIMEOUT) for label, argv in FAST_STEPS]
    if not args.skip_pytest:
        label, argv = _pytest_step(str(args.pytest_workers), args.pytest_chunks)
        note = ("" if str(args.pytest_workers) == "auto"
                else "  -- DIVERGES from ci.yml's 'auto', deliberately, for memory")
        print(f"\n(xdist workers: {args.pytest_workers}{note}; "
              f"chunks {args.pytest_chunks}; cap {args.pytest_timeout}s)", flush=True)
        results.append(run(label, argv, args.pytest_timeout, stream=True))

    failed = [r for r in results if r["rc"] != 0]
    timed_out = [r for r in results if r.get("timed_out")]
    print("\n" + "=" * 72)
    for r in results:
        # A timeout is not a failed test and must not be summarised as one --
        # `FAIL` next to `rc=124` reads as "the suite is red", and it is the
        # sentence that gets copied out of this table into a report. TIMEOUT
        # says the only thing that is actually known.
        verdict = "TIME" if r.get("timed_out") else ("FAIL" if r["rc"] else "ok  ")
        print(f"  {verdict}  {r['step']:34s} rc={r['rc']:<4} "
              f"{r['seconds']:>6.1f}s")
    print(f"\n{len(failed)} of {len(results)} step(s) FAILED on {head[:12]}")
    if timed_out:
        print(f"{len(timed_out)} of those was a TIMEOUT, which reports nothing "
              f"about pass/fail: " + ", ".join(r["step"] for r in timed_out))

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
