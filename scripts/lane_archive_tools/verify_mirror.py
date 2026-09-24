"""Compare the git-tracked mirror in this directory against the LIVE, out-of-git tools.

The live copies in C:\tmp\lane-archive-tools are shared between sessions and freely rewritten
(two of three were rewritten mid-run on 2026-09-23), so a fix that landed only there can be
reverted with no diff and no history. This is the check that makes such a revert visible.

Exit 0 when every file matches byte for byte, 1 otherwise. Reports each file as MATCH, DIFFERS,
MISSING-LIVE or MISSING-MIRROR -- a missing file is never silently a pass.

NOTE: `.gitattributes` carries `scripts/lane_archive_tools/*.py -text`, without which
core.autocrlf (true on the dev machine) rewrites line endings on checkout and every file here
reports DIFFERS for that reason alone. If you see a whole-file DIFFERS with equal line counts,
check that rule before concluding anything was reverted.

THIS SCRIPT NOW LIVES IN BOTH PLACES, AND THAT IS WHY IT REFUSES A SAME-DIRECTORY RUN.
`here` is whatever directory THIS FILE sits in, and `--live` defaults to the out-of-git tools
directory. Copied into that directory and run with defaults, both sides resolve to the same path
and every file is compared WITH ITSELF: measured 2026-09-24, it printed
`3 mirrored file(s), 0 discrepancy(ies)` and exit 0 -- byte-identical to a genuine pass, and
unfalsifiable. A check that cannot fail is worse than no check, so that invocation exits 2.

The comparison itself is symmetric, so from the live directory pass `--live <repo>/scripts/
lane_archive_tools` and the MATCH/DIFFERS verdicts are correct; only the MISSING-LIVE /
MISSING-MIRROR labels read from the other side's point of view.

Usage:  py -3 scripts/lane_archive_tools/verify_mirror.py [--live <dir>]
        py -3 C:\tmp\lane-archive-tools\verify_mirror.py --live <repo>\scripts\lane_archive_tools
"""
import argparse
import hashlib
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ap = argparse.ArgumentParser()
ap.add_argument("--live", default=r"C:\tmp\lane-archive-tools",
                help="directory holding the live tools (default: C:\tmp\lane-archive-tools)")
args = ap.parse_args()

here = Path(__file__).resolve().parent
live = Path(args.live)
if here.resolve() == live.resolve():
    print("REFUSING: --live is this script's own directory, so every file would be compared with\n"
          "itself and report MATCH no matter what was reverted -- a pass that cannot fail.\n"
          f"  both sides: {here}\n"
          "Run it from the git mirror, or pass --live pointing at the OTHER copy.")
    sys.exit(2)
names = sorted(p.name for p in here.glob("*.py") if p.name != Path(__file__).name)
if not names:
    print("no mirrored .py files found next to this script")
    sys.exit(1)

bad = 0
for n in names:
    m, l = here / n, live / n
    if not l.exists():
        print(f"{n:34s} MISSING-LIVE   (mirror has it, {live} does not)")
        bad += 1
        continue
    mb, lb = m.read_bytes(), l.read_bytes()
    if mb == lb:
        print(f"{n:34s} MATCH          {len(mb)} B  {hashlib.sha256(mb).hexdigest()[:16]}")
    else:
        print(f"{n:34s} DIFFERS        mirror {len(mb)} B {hashlib.sha256(mb).hexdigest()[:16]} | "
              f"live {len(lb)} B {hashlib.sha256(lb).hexdigest()[:16]}")
        bad += 1
for p in live.glob("*.py") if live.exists() else []:
    if p.name not in names and p.name != Path(__file__).name:
        print(f"{p.name:34s} MISSING-MIRROR (live has it, this directory does not)")
        bad += 1

print(f"\n{len(names)} mirrored file(s), {bad} discrepancy(ies)")
if bad:
    print("A difference is NOT automatically a revert -- the live copy may be newer. Diff before\n"
          "copying either way; see README.md.")
sys.exit(1 if bad else 0)
