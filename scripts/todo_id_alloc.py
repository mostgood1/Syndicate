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

SEPARATE CHECKOUTS -- FIXED 2026-09-10 (lane `todo-id-alloc-worktrees`).
`O_EXCL` is atomic within ONE directory, and that directory used to be the
TRACKED `.syndicate/todo_ids/` of whichever tree ran this script (`REPO` is
`__file__`'s checkout). With one worktree per session every session had its own
copy, so two O_EXCL creates of the same number both succeeded -- recorded twice
in `todo.md` (`#562` -> `#563`, `#569`), each found at `git merge`. And the mark
was read from the local tree only, so a tree behind `origin/main` could re-issue
an id that had already landed (`#569`). Three layers now, one per distance:

  * SAME MACHINE, ANY TREE: the lock is `<git common dir>/syndicate/todo_ids/`,
    which every worktree of this clone shares and git never tracks. Claims an
    older copy left in the MAIN worktree's `.syndicate/todo_ids/` count too --
    the primary tree routinely runs a stale copy, and 6 such claims were sitting
    there untracked when this was fixed.
  * A TREE BEHIND ITS REMOTE: the mark also reads `origin/main`'s two ledgers and
    its tracked claim files, after a best-effort `git fetch` (`--no-fetch` skips
    it; a failed fetch WARNS and uses the ref as last fetched).
  * SEPARATE CLONES (another machine, a cloud container): nothing local can
    serialise those. The TRACKED claim is still written in this tree -- commit it
    with the entry, and a collision fails LOUDLY as an add/add at land instead of
    silently. Preventing it outright needs a store the clones share, or an id
    reserved by a push before the work (`#563`); not built.

    python scripts/todo_id_alloc.py --holder <lane>          # allocate one
    python scripts/todo_id_alloc.py --holder <lane> --count 2
    python scripts/todo_id_alloc.py --show                   # high-water mark
    python scripts/todo_id_alloc.py --show --no-fetch        # offline

The ledgers stay the source of truth for what an id MEANS. This file only
decides who got which number.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TODO = REPO / "docs" / "ai_context" / "todo.md"
CLOSED = REPO / "docs" / "ai_context" / "todo_closed.md"
CLAIM_DIR = REPO / ".syndicate" / "todo_ids"
ORIGIN_REF = "origin/main"
_LEDGER_PATHS = ("docs/ai_context/todo.md", "docs/ai_context/todo_closed.md")
_CLAIM_PATH = ".syndicate/todo_ids"

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


def _ids_in_text(text: str) -> set[int]:
    found: set[int] = set()
    for pattern in _PATTERNS:
        found.update(int(m) for m in pattern.findall(text))
    return found


def _ids_in(path: Path) -> set[int]:
    try:
        return _ids_in_text(path.read_text(encoding="utf-8"))
    except OSError:
        return set()


def _claimed_in(directory: Path | None) -> set[int]:
    if directory is None or not directory.is_dir():
        return set()
    return {int(entry.stem) for entry in directory.iterdir()
            if entry.suffix == ".claim" and entry.stem.isdigit()}


def _warn(message: str) -> None:
    sys.stderr.write(f"WARNING: {message}\n")


def _git(*args: str, timeout: int = 30) -> subprocess.CompletedProcess | None:
    """None when git cannot run at all; callers treat that as "no view" and say so."""
    try:
        return subprocess.run(["git", *args], cwd=str(REPO), capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None


def _shared_claim_dir() -> Path | None:
    """`<git common dir>/syndicate/todo_ids`: the one directory every worktree shares."""
    found = _git("rev-parse", "--path-format=absolute", "--git-common-dir")
    if found is None or found.returncode != 0 or not found.stdout.strip():
        return None
    return Path(found.stdout.strip()) / "syndicate" / "todo_ids"


def _main_claim_dir() -> Path | None:
    """The MAIN worktree's tracked claim dir -- where the primary tree's copy writes.
    `git worktree list` names the main worktree first."""
    listed = _git("worktree", "list", "--porcelain")
    if listed is None or listed.returncode != 0:
        return None
    for line in listed.stdout.splitlines():
        if line.startswith("worktree "):
            return Path(line[len("worktree "):]) / _CLAIM_PATH
    return None


def _origin_ids(fetch: bool) -> set[int]:
    """Ids in `origin/main`'s two ledgers and in its tracked claim files."""
    if fetch:
        fetched = _git("fetch", "--quiet", "origin", "main", timeout=120)
        if fetched is None or fetched.returncode != 0:
            _warn(f"`git fetch origin main` failed -- the mark uses {ORIGIN_REF} as last fetched")
    ids: set[int] = set()
    readable = False
    for rel in _LEDGER_PATHS:
        shown = _git("show", f"{ORIGIN_REF}:{rel}")
        if shown is not None and shown.returncode == 0:
            readable = True
            ids |= _ids_in_text(shown.stdout)
    listing = _git("ls-tree", "--name-only", ORIGIN_REF, "--", _CLAIM_PATH + "/")
    if listing is not None and listing.returncode == 0:
        for name in listing.stdout.split():
            if name.endswith(".claim") and Path(name).stem.isdigit():
                ids.add(int(Path(name).stem))
    if not readable:
        _warn(f"{ORIGIN_REF} is unreadable -- the mark covers this machine only")
    return ids


def high_water(*, fetch: bool = True) -> int:
    """The largest id anywhere it can already be taken.

    Claims are included deliberately: an id allocated a minute ago is not in the
    ledger yet -- the entry is still being written -- and a scan that ignored it
    would hand the same number to the next caller, which is the whole bug. The
    same holds for a claim made from another worktree, and for an id on
    `origin/main` that this tree has not merged yet.
    """
    ids = _ids_in(TODO) | _ids_in(CLOSED) | _origin_ids(fetch)
    for directory in (CLAIM_DIR, _main_claim_dir(), _shared_claim_dir()):
        ids |= _claimed_in(directory)
    return max(ids) if ids else 0


def _create_exclusive(path: Path, payload: dict) -> bool:
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    # Written straight into the O_EXCL handle, no temp-and-rename: the same
    # reasoning deploy_claim.py records -- a rename is a second operation
    # that can fail after the claim is already visible to everyone else.
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(payload, handle)
    return True


def allocate(holder: str, *, count: int = 1, fetch: bool = True) -> list[int]:
    shared = _shared_claim_dir()
    if shared is None:
        _warn("no git common dir -- claims serialise within THIS tree only")
    lock_dir = shared or CLAIM_DIR
    for directory in {lock_dir, CLAIM_DIR}:
        directory.mkdir(parents=True, exist_ok=True)
    taken: list[int] = []
    candidate = high_water(fetch=fetch) + 1
    # Bounded so a bug here cannot spin: 500 past the high-water mark is far more
    # than any plausible burst and still terminates.
    ceiling = candidate + 500
    while len(taken) < count and candidate < ceiling:
        payload = {
            "id": candidate,
            "holder": holder,
            "claimed_at": datetime.now(timezone.utc).isoformat(),
            "tree": str(REPO),
        }
        # The SHARED file is the lock. The tracked one in this tree is the record
        # that turns a collision with another clone into a loud add/add at land.
        # Losing either create skips the number; a gap is legal.
        if _create_exclusive(lock_dir / f"{candidate}.claim", payload) and (
                lock_dir == CLAIM_DIR or _create_exclusive(CLAIM_DIR / f"{candidate}.claim", payload)):
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
    ap.add_argument("--no-fetch", action="store_true",
                    help=f"do not refresh {ORIGIN_REF} before reading it")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if args.show:
        print(high_water(fetch=not args.no_fetch))
        return 0
    if not args.holder:
        ap.error("--holder is required when allocating")
    if args.count < 1:
        ap.error("--count must be at least 1")

    ids = allocate(args.holder, count=args.count, fetch=not args.no_fetch)
    if args.json:
        print(json.dumps({"ids": ids, "holder": args.holder}))
    else:
        for value in ids:
            print(value)
    sys.stderr.write(f"commit {_CLAIM_PATH}/<id>.claim with the entry: it is what makes a "
                     "collision with another clone fail loudly at land\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
