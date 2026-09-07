"""Settle what the diagnostic-ring cut is worth, on the service that runs it. `#632`.

    py -3 scripts/ring_cost_ab.py plan          # what to do, in order
    py -3 scripts/ring_cost_ab.py read FAT      # after arm 1 has run
    py -3 scripts/ring_cost_ab.py read SLIM     # after arm 2 has run
    py -3 scripts/ring_cost_ab.py compare

WHY THIS IS DEFERRED RATHER THAN DONE, measured 2026-09-07. A waiter polled
refresh-worker for 75 minutes and never found a clear window: board builds start
every **5-8 minutes** during a live slate, plus MLB sims and odds refreshes. A
deploy takes ~5 minutes to go live, so even catching a gap between builds lands
the restart inside the NEXT one. **Waiting cannot solve it** -- the experiment
needs a genuinely quiet period (overnight, or a no-games day), or a deliberate
decision to kill one board build per arm. Same shelf, and the same reason, as
`scripts/malloc_trim_ab.py`.

WHY THE MEASUREMENT IS THE CHECKPOINT'S OWN COST, not the arena. `UPDATE 33`
compared pymalloc arena LEVELS on two workers and was retracted twice over:
`UPDATE 34` found 47% of the difference sat in memory the cut cannot touch (the
arms ran 50 minutes apart on a live slate, and a gate on REQUEST COUNT cannot see
that request count is not work per request), and `UPDATE 35` found the treatment
was INERT on web anyway. The read-modify-write cost is what the cut actually
changes, it fires ~15x/min, and the ring is capped at 300 records -- so it is
nearly workload-independent and one arm yields N in the HUNDREDS.

WHY IT MUST RUN ON refresh-worker. Web's intelligence-state loop is off
(`SYNDICATE_ENABLE_INTELLIGENCE_STATE_BACKGROUND_LOOP='false'`), so web never
writes a checkpoint at all and `ring_cost` is absent there -- verified on both
web workers. Note this makes the result about the WORKER's efficiency: `#632` is
a WEB OOM, and the ring is already eliminated as a candidate for it.

READ VIA LOGS, NOT HTTP. refresh-worker runs no HTTP server, so the
`/api/ops/memory` readout is unreachable there. `_note_ring_cost` emits a
`RING_COST` line every 20 checkpoints, windowed rather than cumulative so each
line is an INDEPENDENT sample and a mean comes with a spread.
"""

from __future__ import annotations

import json
import re
import statistics
import subprocess
import sys
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent.parent / "reports" / "ring_cost_ab"

PLAN = """\
ARM 1 (FAT -- the pre-cut behaviour, restored at runtime):
  python scripts/deploy_claim.py acquire --service refresh-worker --holder <lane>
  python scripts/check_deploy_safety.py          # MUST be CLEAR, not just claim-free
  python scripts/render_env_set.py --service refresh-worker \\
      --key SYNDICATE_RING_KEEP_CMDLINE --value 1
  python scripts/deploy_preflight.py --service refresh-worker --holder <lane> \\
      --target-commit <sha>
  python scripts/render_deploy.py --service refresh-worker --commit <sha>
  # let it run >= 18 min, then:
  py -3 scripts/ring_cost_ab.py read FAT

ARM 2 (SLIM -- the cut, which is the default):
  python scripts/render_env_set.py --service refresh-worker \\
      --key SYNDICATE_RING_KEEP_CMDLINE --value 0
  # preflight again, deploy again, wait >= 18 min, then:
  py -3 scripts/ring_cost_ab.py read SLIM
  py -3 scripts/ring_cost_ab.py compare

AFTERWARDS: release the claim, and leave the flag at 0 (the cut is the default).

DO NOT skip check_deploy_safety because the claim is free. Those are different
questions: the claim says no other SESSION holds the service, the safety check
says no JOB is in flight on it. A deploy satisfying only the first still kills a
board build.
"""


def _read_logs(minutes: int = 40) -> str:
    cmd = [sys.executable, "scripts/render_logs.py", "--service", "refresh-worker",
           "--text", "RING_COST", "--tail", "400"]
    p = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace",
                       cwd=str(Path(__file__).resolve().parent.parent))
    return (p.stdout or "") + (p.stderr or "")


def read(label: str) -> None:
    text = _read_logs()
    samples = []
    for m in re.finditer(r"RING_COST (\{.*?\})", text):
        try:
            samples.append(json.loads(m.group(1)))
        except Exception:
            continue
    if not samples:
        print("  no RING_COST lines found. Either the arm has not run long enough")
        print("  (one line per 20 checkpoints, ~15/min) or the deploy did not take.")
        return
    want = "1" if label.upper() == "FAT" else "0"
    labelled = [s for s in samples if str(s.get("keep_cmdline", "")) == want]
    dropped = len(samples) - len(labelled)
    if dropped:
        # The arm label travels inside each sample precisely so lines from the
        # OTHER arm, still in the log window, cannot be counted into this one.
        print("  dropped %d line(s) whose keep_cmdline != %r -- they belong to the"
              % (dropped, want))
        print("  other arm and would have contaminated this one.")
    if not labelled:
        print("  no lines match keep_cmdline=%r. The arm did not take." % want)
        return
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / ("arm_%s.json" % label.upper())
    path.write_text(json.dumps(labelled, indent=1), encoding="utf-8")
    blocks = [s["blocks_mean"] for s in labelled]
    recs = [s["records"] for s in labelled]
    print("  %s: %d samples, %d checkpoints" % (label.upper(), len(labelled),
                                                sum(s["n"] for s in labelled)))
    print("     blocks/checkpoint  mean %.1f  median %.1f  min %.1f  max %.1f"
          % (statistics.mean(blocks), statistics.median(blocks), min(blocks), max(blocks)))
    print("     ring records       min %d  max %d" % (min(recs), max(recs)))
    print("  -> %s" % path)


def compare() -> None:
    arms = {}
    for label in ("FAT", "SLIM"):
        p = OUT_DIR / ("arm_%s.json" % label)
        if not p.exists():
            print("  missing arm: %s -- run `read %s` first." % (p, label))
            return
        arms[label] = json.loads(p.read_text(encoding="utf-8"))

    for label, rows in arms.items():
        if len(rows) < 5:
            print("  arm %s has only %d samples. Let it run longer; one line is 20"
                  % (label, len(rows)))
            print("  checkpoints and a mean over <5 lines has no usable spread.")
            return

    # THE GATE. The read cost scales with ring length, so arms whose rings were
    # different lengths are not comparable. This is the control the retracted
    # arena A/B lacked -- there, request count passed while WORK per request did
    # not, and the whole result was confound.
    recs = {k: (min(s["records"] for s in v), max(s["records"] for s in v))
            for k, v in arms.items()}
    if min(recs["FAT"][0], recs["SLIM"][0]) < 250:
        print("  a ring held only %d records -- it had not filled, so the arms are"
              % min(recs["FAT"][0], recs["SLIM"][0]))
        print("  NOT comparable. Re-run the short arm for longer.")
        return

    print("  %-6s %-9s %-9s %-11s %-11s %s"
          % ("arm", "samples", "ckpts", "blocks/ckpt", "median", "ring records"))
    st = {}
    for label in ("FAT", "SLIM"):
        rows = arms[label]
        b = [s["blocks_mean"] for s in rows]
        st[label] = b
        print("  %-6s %-9d %-9d %-11.1f %-11.1f %s"
              % (label, len(rows), sum(s["n"] for s in rows),
                 statistics.mean(b), statistics.median(b), recs[label]))

    f, s = st["FAT"], st["SLIM"]
    mf, ms = statistics.mean(f), statistics.mean(s)
    print()
    print("  blocks per checkpoint: FAT %.1f -> SLIM %.1f   (%+.1f, %.2fx)"
          % (mf, ms, ms - mf, (mf / ms) if ms else 0))
    # Report the SPREAD, not just the means. Overlapping ranges on a
    # well-powered sample still mean the difference is not clean.
    print("  FAT  range %.1f - %.1f      SLIM range %.1f - %.1f"
          % (min(f), max(f), min(s), max(s)))
    overlap = not (max(s) < min(f) or max(f) < min(s))
    print()
    if overlap:
        print("  THE RANGES OVERLAP despite N in the hundreds. Report a direction at")
        print("  most -- this is the failure the arena A/B made twice.")
    elif ms < mf * 0.75:
        print("  CONFIRMED: the checkpoint costs %.0f%% fewer blocks with the cut,"
              % (100 * (1 - ms / mf)))
        print("  ranges separated. That -- per checkpoint, ~15x/min on the WORKER --")
        print("  is what the cut is worth. It is NOT a web-OOM figure.")
    elif abs(ms - mf) < 0.1 * mf:
        print("  NO DIFFERENCE on the direct quantity. The cut does not do in")
        print("  production what it does locally (18,644 -> 9,642 blocks), and that")
        print("  local measurement needs explaining before anything rests on it.")
    else:
        print("  PARTIAL: %.0f%% fewer blocks, less than the local measurement"
              % (100 * (1 - ms / mf)))
        print("  predicted. Report the share; do not round it up to the local one.")


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "plan":
        print(PLAN)
    elif len(sys.argv) == 3 and sys.argv[1] == "read":
        read(sys.argv[2])
    elif len(sys.argv) == 2 and sys.argv[1] == "compare":
        compare()
    else:
        print(__doc__)
