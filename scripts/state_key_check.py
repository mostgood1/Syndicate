"""`state.md` says one subject, one section. This is the key that makes it checkable.

WHY A KEY AT ALL. `state.md`'s own header states the rule that keeps it useful:
"when you learn something here is wrong, EDIT THE LINE. Do not append a newer
section that contradicts it." Nothing enforced that, because the file had no
identity to check -- 38 prose sections, no duplicate titles, and therefore
nothing a tool could compare.

"No duplicate titles" looked like health and was the opposite: it is trivially
true when every section is titled by its DATE. The file collapsed on 2026-08-15
from stacking, collapsed again on 2026-08-18 from stacking, and by that evening
had four sections on the WNBA sweep gate and two on one deploy-lineage story,
each a dated snapshot of a narrative whose ending was elsewhere in the same
file. A reader had to reconstruct the current truth from a chronology. That is
exactly what both collapses were meant to stop, recurring inside ten days.

THE KEY. Every section header carries a subject slug, mirroring `lanes.md`'s
`### slug — STATUS` so there is one convention to learn, not two:

    ## [refresh-worker-memory] MEMORY — refresh-worker: THE OOM IS FIXED ...

One subject, one section. Two sections sharing a slug is the stacking failure,
by definition, and this reports it.

DELIBERATE: THE INITIAL KEYING MADE THE FILE FAIL. The five WNBA sweep-gate
sections were given the SAME slug rather than five distinct ones, and so were
the two halves of the deploy-lineage story. Keying them apart would have made
the checker pass while the file stayed unreadable -- grading the labels instead
of the content. A checker that cannot fail on the thing it was built for is
decoration.

EXIT CODES
  0  one subject, one section        1  a slug is stacked, or a section is unkeyed
  2  cannot read the file

    python scripts/state_key_check.py
    python scripts/state_key_check.py --json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
STATE = REPO_ROOT / ".syndicate" / "state.md"

SECTION = re.compile(r"^## (?!\[)(.*)$", re.M)          # a header with no key
KEYED = re.compile(r"^## \[([a-z0-9][a-z0-9-]*)\] (.*)$", re.M)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    try:
        text = STATE.read_text(encoding="utf-8-sig")
    except OSError as exc:
        print(f"FATAL: cannot read {STATE}: {exc}", file=sys.stderr)
        return 2

    keyed: dict[str, list[str]] = {}
    for slug, title in KEYED.findall(text):
        keyed.setdefault(slug, []).append(title.strip()[:70])
    unkeyed = [t.strip()[:70] for t in SECTION.findall(text)]

    stacked = sorted((s, t) for s, t in keyed.items() if len(t) > 1)
    report = {
        "sections": sum(len(v) for v in keyed.values()) + len(unkeyed),
        "subjects": len(keyed),
        "unkeyed": unkeyed,
        "stacked": {s: t for s, t in stacked},
    }
    failed = bool(stacked or unkeyed)

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
        return 1 if failed else 0

    print(f"{report['sections']} sections / {report['subjects']} subjects")

    if unkeyed:
        print(f"\nUNKEYED -- {len(unkeyed)} section(s) with no subject slug.")
        print("Add one: `## [subject-slug] TITLE`. Without it the section cannot")
        print("be compared against anything and stacking on it is invisible:")
        for title in unkeyed:
            print(f"  {title}")

    if stacked:
        print(f"\nSTACKED -- {len(stacked)} subject(s) with more than one section.")
        print("state.md's rule is to EDIT THE LINE, not append a contradicting")
        print("section. Collapse each of these into one, newest truth winning:")
        for slug, titles in stacked:
            print(f"  [{slug}] x{len(titles)}")
            for title in titles:
                print(f"      {title}")

    if not failed:
        print("\ncoherent -- one subject, one section")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
