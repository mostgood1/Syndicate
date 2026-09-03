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
# PERMISSIVE, and it must stay that way. This was `[a-z0-9][a-z0-9-]*`, which
# matched neither a conforming slug with an underscore or a capital, NOR the
# unkeyed pattern above (that one requires no `[`). Nine real sections fell
# through both and were counted by NEITHER -- `[layer2_board_display]`,
# `[polymarket-price-gate-LIVE]`, `[accuracy-autorun-OOM-2026-09-02]` and six
# more -- so this reported "167 sections" for a file that has 176, and stacking
# on any of those nine would never have appeared here.
#
# Nothing was left UNPROTECTED by that: `.claude/hooks/ledger_invariants.py`,
# which is what actually blocks a commit, has always used `\[([^\]]+)\]` and so
# saw all 176. The gap was in the REPORT a human reads while auditing by hand.
# Matching the guard's pattern is the point -- two implementations of one
# invariant that disagree is how the invariant stops meaning anything.
KEYED = re.compile(r"^## \[([^\]]+)\] (.*)$", re.M)
# Convention is lower-kebab. Off-convention slugs are REPORTED, not failed:
# they are checkable and check out, and a permanently red light is one nobody
# reads (see the cap-raise reasoning in .claude/hooks/session-start.sh).
CONFORMING = re.compile(r"^[a-z0-9][a-z0-9-]*$")


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
    offconvention = sorted(s for s in keyed if not CONFORMING.match(s))
    report = {
        "sections": sum(len(v) for v in keyed.values()) + len(unkeyed),
        "subjects": len(keyed),
        "unkeyed": unkeyed,
        "stacked": {s: t for s, t in stacked},
        "offconvention": offconvention,
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

    if offconvention:
        print(f"\nOFF-CONVENTION -- {len(offconvention)} slug(s) outside lower-kebab.")
        print("These ARE checked for stacking (this reporter used to skip them")
        print("entirely). Not a failure; normalise them when you next edit the section:")
        for slug in offconvention:
            print(f"  [{slug}]")

    if not failed:
        print("\ncoherent -- one subject, one section")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
