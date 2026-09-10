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
an id that had already landed (`#569`). The local lock is now machine-wide:

  * SAME MACHINE, ANY TREE: the lock is `<git common dir>/syndicate/todo_ids/`,
    which every worktree of this clone shares and git never tracks. Claims an
    older copy left in the MAIN worktree's `.syndicate/todo_ids/` count too --
    the primary tree routinely runs a stale copy, and 6 such claims were sitting
    there untracked when this was fixed.
  * A TREE BEHIND ITS REMOTE: the mark also reads `origin/main`'s two ledgers and
    its tracked claim files, after a best-effort `git fetch` (a failed fetch
    WARNS and uses the ref as last fetched).

RESERVED BY PUSH -- 2026-09-10 (lane `todo-id-push-reserve`). No local lock can
serialise two SEPARATE clones (another machine, a cloud container): they share
nothing but the remote. So by default the id is reserved ON THE REMOTE before
anyone writes a word about it. A commit is built whose parent is `origin/main`
as just fetched and whose only change is `.syndicate/todo_ids/<n>.claim`, and it
is pushed to `main`. A push is a compare-and-swap -- it lands only if `main`
still points at that parent -- so of two clones racing for one number exactly
one push succeeds; the other is rejected, re-fetches, sees the winner's claim,
and takes the next number.

  * Built with plumbing (`hash-object`, `mktree`, `commit-tree`), so it never
    touches the caller's index or working tree and runs no commit hook.
  * `[skip ci]` in the message: `ci.yml` runs on every push to `main`, and a
    claim file needs no CI run.
  * The claim is NOT also written into the caller's tree: it is already on
    `main`, and an untracked copy would block their next rebase ("untracked
    working tree file would be overwritten").
  * When a push cannot happen (offline, auth, no origin) the id falls back to
    the machine-wide lock and says so LOUDLY -- a separate clone could then take
    the same number, so commit the claim with the entry, and the collision fails
    as an add/add at land instead of silently. `--no-push` asks for that outright.

    python scripts/todo_id_alloc.py --holder <lane>          # reserve one on origin
    python scripts/todo_id_alloc.py --holder <lane> --count 2
    python scripts/todo_id_alloc.py --holder <lane> --no-push   # this machine only
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

PUSH = True          # reserve on the remote by default; `--no-push` (and tests) turn it off
_PUSH_ATTEMPTS = 8
# `git push` output meaning "main moved under you" -- worth a retry -- as opposed
# to auth, network or a server-side refusal, which no retry can fix.
# `[remote rejected] (cannot lock ref ...)` is the same race, lost at the server.
_RACE_MARKERS = ("[rejected]", "fetch first", "non-fast-forward", "cannot lock ref", "stale info")

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


def _git(*args: str, timeout: int = 30, input: str | None = None,
         env: dict | None = None) -> subprocess.CompletedProcess | None:
    """None when git cannot run at all; callers treat that as "no view" and say so."""
    try:
        return subprocess.run(["git", *args], cwd=str(REPO), capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout,
                              input=input, env=env)
    except (OSError, subprocess.TimeoutExpired):
        return None


def _checked(result: subprocess.CompletedProcess | None, what: str, *, allow_empty: bool = False) -> str:
    if result is None or result.returncode != 0 or not (allow_empty or result.stdout.strip()):
        detail = "" if result is None else (result.stderr or result.stdout).strip()[:200]
        raise RuntimeError(f"git {what} failed" + (f": {detail}" if detail else ""))
    return result.stdout


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


def _payload(value: int, holder: str) -> dict:
    return {
        "id": value,
        "holder": holder,
        "claimed_at": datetime.now(timezone.utc).isoformat(),
        "tree": str(REPO),
    }


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


# --- reserved by push -----------------------------------------------------------


def _ls_tree(tree: str | None) -> dict[str, tuple[str, str, str]]:
    if not tree:
        return {}
    entries: dict[str, tuple[str, str, str]] = {}
    for record in _checked(_git("ls-tree", "-z", tree), "ls-tree", allow_empty=True).split("\0"):
        if record:
            meta, _, name = record.partition("\t")
            mode, kind, sha = meta.split(" ")
            entries[name] = (mode, kind, sha)
    return entries


def _mktree(entries: dict[str, tuple[str, str, str]]) -> str:
    body = "".join(f"{mode} {kind} {sha}\t{name}\0" for name, (mode, kind, sha) in entries.items())
    return _checked(_git("mktree", "-z", input=body), "mktree").strip()


def _tree_with(tree: str | None, parts: list[str], files: dict[str, str]) -> str:
    """`tree` with `files` (name -> blob) added in the directory `parts`, rebuilding
    only the trees on that path -- three `mktree` calls, whatever the repo's size."""
    entries = _ls_tree(tree)
    if parts:
        current = entries.get(parts[0])
        sub = current[2] if current and current[1] == "tree" else None
        entries[parts[0]] = ("040000", "tree", _tree_with(sub, parts[1:], files))
    else:
        for name, blob in files.items():
            if name in entries:
                raise RuntimeError(f"{_CLAIM_PATH}/{name} already exists on {ORIGIN_REF}")
            entries[name] = ("100644", "blob", blob)
    return _mktree(entries)


def _origin_base() -> str | None:
    """`origin/main`, freshly fetched: the parent a reservation must be built on.
    None when it cannot be refreshed -- a compare-and-swap against a ref this
    clone could not update can only lose."""
    fetched = _git("fetch", "--quiet", "origin", "main", timeout=120)
    if fetched is None or fetched.returncode != 0:
        return None
    head = _git("rev-parse", "--verify", "--quiet", f"{ORIGIN_REF}^{{commit}}")
    if head is None or head.returncode != 0 or not head.stdout.strip():
        return None
    return head.stdout.strip()


def _claim_commit(base: str, payloads: dict[int, dict], holder: str) -> str:
    """A commit on `base` whose only change is one claim file per id."""
    files = {f"{value}.claim": _checked(_git("hash-object", "-w", "--stdin", input=json.dumps(payload)),
                                        "hash-object").strip()
             for value, payload in payloads.items()}
    root = _checked(_git("rev-parse", f"{base}^{{tree}}"), "rev-parse").strip()
    tree = _tree_with(root, _CLAIM_PATH.split("/"), files)
    ids = ", ".join(f"#{value}" for value in payloads)
    message = f"todo id: reserve {ids} for {holder} [skip ci]"
    return _checked(_git("commit-tree", tree, "-p", base, "-m", message), "commit-tree").strip()


def _push(commit: str) -> str:
    """"ok"; "moved" when `main` changed under us (retry); "error: <why>" otherwise."""
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}     # never hang on a credential prompt
    pushed = _git("push", "--porcelain", "origin", f"{commit}:refs/heads/main", timeout=120, env=env)
    if pushed is None:
        return "error: git push did not complete"
    if pushed.returncode == 0:
        return "ok"
    said = f"{pushed.stdout}\n{pushed.stderr}".strip()
    if any(marker in said for marker in _RACE_MARKERS):
        return "moved"
    return "error: " + (said.splitlines()[-1][:200] if said else f"exit {pushed.returncode}")


def _reserve_on_origin(holder: str, count: int) -> list[int] | None:
    """Reserve `count` ids on the remote in ONE commit. None means "could not", and
    has already said why."""
    for _attempt in range(_PUSH_ATTEMPTS):
        base = _origin_base()
        if base is None:
            _warn(f"could not refresh {ORIGIN_REF} -- reserving on THIS machine only")
            return None
        start = high_water(fetch=False) + 1        # origin/main as just fetched, plus every local claim
        payloads = {value: _payload(value, holder) for value in range(start, start + count)}
        try:
            commit = _claim_commit(base, payloads, holder)
        except RuntimeError as exc:
            _warn(f"could not build the reservation commit ({exc}) -- reserving on THIS machine only")
            return None
        status = _push(commit)
        if status == "ok":
            shared = _shared_claim_dir()
            if shared is not None:                 # a local record too; the lock was the push
                shared.mkdir(parents=True, exist_ok=True)
                for value, payload in payloads.items():
                    _create_exclusive(shared / f"{value}.claim", payload)
            sys.stderr.write(f"reserved on {ORIGIN_REF} by {commit[:10]} -- nothing to commit for it\n")
            return list(payloads)
        if status != "moved":
            _warn(f"push failed ({status[len('error: '):]}) -- reserving on THIS machine only")
            return None
    _warn(f"{ORIGIN_REF} moved {_PUSH_ATTEMPTS} times in a row -- reserving on THIS machine only")
    return None


# --- the machine-wide lock ------------------------------------------------------


def _reserve_locally(holder: str, count: int, fetch: bool) -> list[int]:
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
        payload = _payload(candidate, holder)
        # The SHARED file is the lock. The tracked one in this tree is the record
        # that turns a collision with another clone into a loud add/add at land.
        # Losing either create skips the number; a gap is legal.
        if _create_exclusive(lock_dir / f"{candidate}.claim", payload) and (
                lock_dir == CLAIM_DIR or _create_exclusive(CLAIM_DIR / f"{candidate}.claim", payload)):
            taken.append(candidate)
        candidate += 1
    if len(taken) < count:
        raise RuntimeError(f"could not allocate {count} ids below {ceiling}")
    sys.stderr.write(f"reserved on THIS machine only -- commit {_CLAIM_PATH}/<id>.claim with the "
                     "entry: it is what makes a collision with another clone fail loudly at land\n")
    return taken


def allocate(holder: str, *, count: int = 1, fetch: bool = True, push: bool | None = None) -> list[int]:
    """Reserve on the remote when possible; otherwise on this machine, loudly."""
    if PUSH if push is None else push:
        reserved = _reserve_on_origin(holder, count)
        if reserved is not None:
            return reserved
    return _reserve_locally(holder, count, fetch)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--holder", help="lane or session taking the id")
    ap.add_argument("--count", type=int, default=1)
    ap.add_argument("--show", action="store_true", help="print the high-water mark and exit")
    ap.add_argument("--no-push", action="store_true",
                    help="reserve on this machine only; commit the claim with the entry")
    ap.add_argument("--no-fetch", action="store_true",
                    help=f"stay off the network: no fetch of {ORIGIN_REF} and no push")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if args.show:
        print(high_water(fetch=not args.no_fetch))
        return 0
    if not args.holder:
        ap.error("--holder is required when allocating")
    if args.count < 1:
        ap.error("--count must be at least 1")

    ids = allocate(args.holder, count=args.count, fetch=not args.no_fetch,
                   push=not (args.no_push or args.no_fetch))
    if args.json:
        print(json.dumps({"ids": ids, "holder": args.holder}))
    else:
        for value in ids:
            print(value)
    return 0


if __name__ == "__main__":
    sys.exit(main())
