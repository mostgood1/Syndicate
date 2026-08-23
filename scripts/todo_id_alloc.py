"""Allocate the next TODO id ATOMICALLY. Two sessions cannot get the same one.

WHY THIS EXISTS, measured 2026-08-23. Ids are allocated by reading `todo.md`,
taking the largest, and adding one. The read and the write are not atomic, so
two sessions that look at the same moment pick the same number -- and the loser
finds out at `git merge`, after the entry, the code comments and the tests are
all written and have to be renamed together.

That happened **eight times in one session**, across at least three sessions:
514/515 -> 520/521, 522 -> 523, 524 -> 525, 527/528 -> 530/531, 532 -> 536. Each
rename touches the ledger AND every `#N` in the code, because a stale
cross-reference is worse than none -- it resolves to somebody else's item and
reads as deliberate.

`todo_id_reconcile.py` is the sibling of this tool and answers a different
question: every id ever issued must live in exactly one of the two files. It
audits AFTER the fact. This prevents the collision in the first place.

THE MECHANISM IS THE ONE THE REPO ALREADY TRUSTS. `deploy_claim.py` serialises
deploys with `O_CREAT|O_EXCL`, whose own docstring notes that coordination by
MESSAGE cannot work because a cross-session message waits for the target's turn
to end. The same is true here, and more so: nobody announces an id.

So: scan both ledgers for the high-water mark, then CLAIM the next number by
creating `.syndicate/todo_ids/<n>.claim` with O_EXCL. A create that loses the
race raises FileExistsError; increment and retry. The winner gets the number and
a file recording who took it and when.

CLAIMS ARE NEVER EXPIRED, unlike a deploy claim. A deploy claim expires because
holding one forever wedges a service; an id claim expires into a COLLISION,
which is the thing being prevented. An id taken and then abandoned is a gap in
the sequence, and a gap costs nothing -- `todo.md`'s own rule is that ids are
stable and never reused, so a hole is already legal.

    python scripts/todo_id_alloc.py --holder <lane>          # allocate one
    python scripts/todo_id_alloc.py --holder <lane> --count 2
    python scripts/todo_id_alloc.py --show                   # high-water mark

The ledgers stay the source of truth for what an id MEANS. This file only
decides who got which number.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TODO = REPO / "docs" / "ai_context" / "todo.md"
CLOSED = REPO / "docs" / "ai_context" / "todo_closed.md"
CLAIM_DIR = REPO / ".syndicate" / "todo_ids"

# BOTH ERAS, because the high-water mark has to be the true one. Ids ~0-168 are
# table rows (`| **125** |`), ~275+ are headers (``### `#447` ``). Reading only
# the current format would be correct today and wrong the moment anyone touches
# the archive -- and `todo_id_reconcile.py` documents that the archive also
# carries `- **#N` bullets and `#### `#N`` sub-headers.
_PATTERNS = (
    re.compile(r"^#{3,4} `#(\d+)`", re.M),
    re.compile(r"^\|\s*\*\*(\d+)\*\*\s*\|", re.M),
    re.compile(r"^- \*\*#(\d+)", re.M),
)


def _ids_in(path: Path) -> set[int]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return set()
    found: set[int] = set()
    for pattern in _PATTERNS:
        found.update(int(m) for m in pattern.findall(text))
    return found


def high_water() -> int:
    """The largest id in either ledger OR already claimed here.

    Claims are included deliberately: an id allocated a minute ago is not in the
    ledger yet -- the entry is still being written -- and a scan that ignored it
    would hand the same number to the next caller, which is the whole bug.
    """
    ids = _ids_in(TODO) | _ids_in(CLOSED)
    if CLAIM_DIR.is_dir():
        for entry in CLAIM_DIR.iterdir():
            if entry.suffix == ".claim" and entry.stem.isdigit():
                ids.add(int(entry.stem))
    return max(ids) if ids else 0


def allocate(holder: str, *, count: int = 1) -> list[int]:
    CLAIM_DIR.mkdir(parents=True, exist_ok=True)
    taken: list[int] = []
    candidate = high_water() + 1
    # Bounded so a bug here cannot spin: 500 past the high-water mark is far more
    # than any plausible burst and still terminates.
    ceiling = candidate + 500
    while len(taken) < count and candidate < ceiling:
        path = CLAIM_DIR / f"{candidate}.claim"
        try:
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            candidate += 1
            continue
        # Written straight into the O_EXCL handle, no temp-and-rename: the same
        # reasoning deploy_claim.py records -- a rename is a second operation
        # that can fail after the claim is already visible to everyone else.
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "id": candidate,
                    "holder": holder,
                    "claimed_at": datetime.now(timezone.utc).isoformat(),
                },
                handle,
            )
        taken.append(candidate)
        candidate += 1
    if len(taken) < count:
        raise RuntimeError(f"could not allocate {count} ids below {ceiling}")
    return taken


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--holder", help="lane or session taking the id")
    ap.add_argument("--count", type=int, default=1)
    ap.add_argument("--show", action="store_true", help="print the high-water mark and exit")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if args.show:
        print(high_water())
        return 0
    if not args.holder:
        ap.error("--holder is required when allocating")
    if args.count < 1:
        ap.error("--count must be at least 1")

    ids = allocate(args.holder, count=args.count)
    if args.json:
        print(json.dumps({"ids": ids, "holder": args.holder}))
    else:
        for value in ids:
            print(value)
    return 0


if __name__ == "__main__":
    sys.exit(main())
