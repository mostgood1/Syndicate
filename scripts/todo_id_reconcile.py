"""Every TODO id ever issued must live in exactly one of the two todo files.

WHY THIS EXISTS. On 2026-08-18 a de-dup pass on `todo.md` removed `#447` and it
was never archived to `todo_closed.md`, so it existed in NEITHER file. The same
working copy would have dropped `#448`, `#449`, `#454`, `#455` and `#456` the
same way -- five open items, zero copies each, one of them an active OOM crash
loop. None of it was visible in review: a deletion inside a 300-line hunk of an
append-only ledger looks exactly like a tidy.

`todo.md`'s own rule is that ids are stable and never reused, and that an item
leaves the working list only by landing in the archive. That rule had nothing
enforcing it. This is the enforcement.

TWO ERAS, AND THE HEURISTIC THIS TOOL IS HONEST ABOUT. The id conventions
changed partway through the project:

  * ids ~0-168 are TABLE ROWS  (`| **125** | ... |`), the original format
  * ids ~275+ are HEADERS      (``### `#447` — ...``), the current format

`todo.md` today uses headers exclusively and is machine-checkable. The archive
is NOT: it carries table rows, `- **#N` bullets, `#### `#N`` sub-headers, and
prose sections titled by date rather than by id. So "is this id closed?" is
answered by a UNION of patterns, and an id whose only archive record is inside
prose can read as missing when it is merely filed in an unusual shape.

That is why MISSING is reported as REVIEW rather than as a failure, with the
last commit that held the id so it can be judged in seconds. The exit code
gates on the unambiguous cases only -- see EXIT CODES below. A gate that cried
wolf on archive formatting would be turned off within a day, and then the real
case (an id in neither file) would go unnoticed again.

EXIT CODES
  0  clean
  1  a CURRENT-ERA id is in neither file, or an id is duplicated within `todo.md`
  2  could not read one of the files

Pre-#275 ids in neither file are reported on ONE line and do NOT gate: their
archive records predate the header format and cannot be matched here, so
gating on them would fail every run and train the reader to skim -- which is
exactly what happened on 2026-08-26, when two sessions each read a correct
duplicate warning delivered alongside twelve of them and dismissed it.
`--show-legacy` expands that line.

    python scripts/todo_id_reconcile.py
    python scripts/todo_id_reconcile.py --json
    python scripts/todo_id_reconcile.py --since 275   # current-era ids only
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TODO = REPO_ROOT / "docs" / "ai_context" / "todo.md"
CLOSED = REPO_ROOT / "docs" / "ai_context" / "todo_closed.md"

# An ITEM DECLARATION in todo.md. Deliberately `###` only: `####` is an
# update/sub-note on an existing item (`#### `#445` UPDATE 2`), not a second
# declaration of it, and counting those would report every updated item as a
# duplicate.
OPEN_ITEM = re.compile(r"^### `#(\d+)`", re.M)

# THE ERA BOUNDARY, and it is the difference between a finding and noise.
#
# This module's own docstring records that the id conventions changed partway
# through the project: ids ~0-168 are TABLE ROWS in the original format, ids
# ~275+ are HEADERS in the current one, and the ARCHIVE is not machine-checkable
# for the older era -- it carries table rows, `- **#N` bullets, `#### `#N``
# sub-headers, and prose sections titled by DATE rather than by id. So a
# legacy id whose only archive record sits inside prose reads as MISSING when
# it is merely filed in a shape no pattern here can match.
#
# MEASURED 2026-08-26: an unfiltered run reports twelve such ids (#65-#81) and
# exits 1 EVERY TIME. That is the state this file's docstring set out to avoid
# -- "a gate that cried wolf on archive formatting would be turned off within a
# day" -- reached anyway, because the crying-wolf moved from the exit code into
# the output. Both of the sessions that declared `#581` twice that evening read
# the resulting warning and skimmed it, independently, and each said so.
#
# So legacy misses are still COUNTED and still reportable, but they are
# collapsed to one line and do not gate the exit code. A miss in the CURRENT
# era -- where every item is a header and the tool can genuinely see it -- is
# reported in full and does gate. Nothing is suppressed; the two populations are
# separated so a real finding is not delivered in the same breath as twelve
# known-unmatchable ones.
_HEADER_ERA_FIRST_ID = 275

# ...but `todo.md` ALSO carries 51 legacy table rows (`| **125** | 🟢 ...`), the
# pre-header convention where a CLOSED item stayed in the working file under a
# green marker instead of moving to the archive. They are records, not open
# items, so they do not count toward "declared twice" -- but an id recorded this
# way is recorded, and reporting it as lost is exactly the false alarm that gets
# a gate switched off. The first version of this tool did precisely that: it
# flagged 40+ legacy ids because it only looked for headers.
TODO_LEGACY_ROW = re.compile(r"^\| \*\*(\d+)\*\* \|", re.M)

# Any shape the archive has actually used to record a closed item. Prose sections
# titled by date carry no id and cannot be matched -- see the docstring.
CLOSED_PATTERNS = (
    re.compile(r"^\| \*\*(\d+)\*\* \|", re.M),      # legacy table row
    re.compile(r"^- \*\*#(\d+)", re.M),             # bullet
    re.compile(r"^#{2,4} `#(\d+)`", re.M),          # header / sub-header
)

# Ids ever DECLARED, harvested from history in one pass. `git log -p` over both
# files is ~10s at 738 commits, which is cheap enough to re-derive every run --
# a hardcoded list would be wrong the first time someone opened an id.
HISTORY_PATTERNS = (
    re.compile(r"^\+### `#(\d+)`"),
    re.compile(r"^\+\| \*\*(\d+)\*\* \|"),
)


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        print(f"FATAL: cannot read {path}: {exc}", file=sys.stderr)
        raise SystemExit(2)


def ids_ever_issued() -> set[int]:
    try:
        out = subprocess.run(
            ["git", "log", "-p", "--format=", "--", str(TODO), str(CLOSED)],
            cwd=REPO_ROOT, capture_output=True, timeout=600,
        )
    except Exception as exc:  # noqa: BLE001 -- history is context, not a gate
        print(f"WARNING: could not read git history ({exc}); "
              "checking only ids present in the files today", file=sys.stderr)
        return set()
    found: set[int] = set()
    for line in out.stdout.decode("utf-8", "replace").splitlines():
        if not line.startswith("+"):
            continue
        for pattern in HISTORY_PATTERNS:
            m = pattern.match(line)
            if m:
                found.add(int(m.group(1)))
    return found


def last_commit_holding(item_id: int) -> str:
    """The most recent commit that carried this id. '' if unknown.

    Tries BOTH declaration shapes: an id from the legacy era never appeared as a
    header, so searching only for the header form returns "(unknown)" for exactly
    the ids that need the most explaining.
    """
    for needle in (f"### `#{item_id}`", f"| **{item_id}** |"):
        try:
            out = subprocess.run(
                ["git", "log", "-1", "--format=%h %s", "-S", needle,
                 "--", str(TODO), str(CLOSED)],
                cwd=REPO_ROOT, capture_output=True, timeout=120,
            )
            found = out.stdout.decode("utf-8", "replace").strip()
            if found:
                return found[:90]
        except Exception:  # noqa: BLE001
            continue
    return ""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--since", type=int, default=0,
                    help="only reconcile ids >= this (e.g. 275 for the header era)")
    ap.add_argument("--no-history", action="store_true",
                    help="skip the git-history pass; check only ids present today")
    ap.add_argument("--show-legacy", action="store_true",
                    help=f"list pre-#{_HEADER_ERA_FIRST_ID} misses individually, with the "
                         "commit that last held each (slow: one git log -S per id)")
    args = ap.parse_args()

    todo_text, closed_text = _read(TODO), _read(CLOSED)

    open_counts: dict[int, int] = {}
    for m in OPEN_ITEM.finditer(todo_text):
        open_counts[int(m.group(1))] = open_counts.get(int(m.group(1)), 0) + 1

    legacy_ids = {int(x) for x in TODO_LEGACY_ROW.findall(todo_text)}

    closed_ids: set[int] = set()
    for pattern in CLOSED_PATTERNS:
        closed_ids.update(int(x) for x in pattern.findall(closed_text))

    universe = set(open_counts) | legacy_ids | closed_ids
    if not args.no_history:
        universe |= ids_ever_issued()
    universe = {i for i in universe if i >= args.since}

    missing, duplicated, both = [], [], []
    for item_id in sorted(universe):
        n_open = open_counts.get(item_id, 0)
        is_closed = item_id in closed_ids
        recorded_in_todo = n_open >= 1 or item_id in legacy_ids
        if not recorded_in_todo and not is_closed:
            missing.append(item_id)
        elif n_open > 1:
            duplicated.append((item_id, n_open))
        elif recorded_in_todo and is_closed:
            both.append(item_id)

    # SPLIT BY ERA. See `_HEADER_ERA_FIRST_ID`: only the current era is
    # machine-checkable on both sides, so only it can gate.
    missing_current = [i for i in missing if i >= _HEADER_ERA_FIRST_ID]
    missing_legacy = [i for i in missing if i < _HEADER_ERA_FIRST_ID]

    report = {
        "ids_reconciled": len(universe),
        "open": sum(1 for i in universe if open_counts.get(i, 0) >= 1),
        "closed": len(closed_ids & universe),
        "missing_from_both": missing,
        "missing_current_era": missing_current,
        "missing_legacy": missing_legacy,
        "duplicated_in_todo": duplicated,
        "in_both_files": both,
    }

    if args.json:
        detail_for = missing if args.show_legacy else missing_current
        if detail_for:
            report["missing_detail"] = {str(i): last_commit_holding(i) for i in detail_for}
        print(json.dumps(report, indent=2, sort_keys=True))
        return 1 if (missing_current or duplicated) else 0

    print(f"reconciled {report['ids_reconciled']} ids "
          f"({report['open']} open, {report['closed']} closed)"
          + (f", ids >= {args.since}" if args.since else ""))

    if duplicated:
        print(f"\nDUPLICATED in todo.md -- {len(duplicated)} id(s) declared more than once:")
        for item_id, n in duplicated:
            print(f"  #{item_id}: {n} item headers")

    if both:
        print(f"\nIN BOTH FILES -- {len(both)} id(s) open and archived at once:")
        for item_id in both:
            print(f"  #{item_id}")

    if missing_current:
        print(f"\nREVIEW -- {len(missing_current)} CURRENT-ERA id(s) in NEITHER file.")
        print("Every item in this era is a header the tool can see on both sides, so")
        print("this is a lost item rather than an archive-formatting artifact:")
        for item_id in missing_current:
            print(f"  #{item_id:<5} last seen: {last_commit_holding(item_id) or '(unknown)'}")

    if missing_legacy:
        # ONE LINE, NOT TWELVE. Counted, not hidden -- and the count is the
        # thing that changes if one is ever genuinely lost.
        if args.show_legacy:
            print(f"\nLEGACY -- {len(missing_legacy)} pre-#{_HEADER_ERA_FIRST_ID} id(s) "
                  "in neither file, archive not machine-checkable for that era:")
            for item_id in missing_legacy:
                print(f"  #{item_id:<5} last seen: {last_commit_holding(item_id) or '(unknown)'}")
        else:
            ids = ", ".join(f"#{i}" for i in missing_legacy)
            print(f"\nlegacy (not gating): {len(missing_legacy)} pre-#{_HEADER_ERA_FIRST_ID} "
                  f"id(s) unmatched -- {ids}")
            print("  their archive records predate the header format; --show-legacy to expand")

    if not (missing_current or duplicated or both):
        print("\nclean -- every current-era id lives in exactly one file")
    return 1 if (missing_current or duplicated) else 0


if __name__ == "__main__":
    sys.exit(main())
