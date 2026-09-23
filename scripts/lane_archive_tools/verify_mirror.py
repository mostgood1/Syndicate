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

Usage:  py -3 scripts/lane_archive_tools/verify_mirror.py [--live <dir>]
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
