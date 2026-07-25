"""Atomic artifact writes for producers (#25).

Artifact producers write files that the web service reads concurrently.
`df.to_csv(path)` and `path.write_text(...)` are not atomic: they truncate
the destination and then stream into it, so a reader arriving mid-write sees
a short or empty file. Nothing raises -- the reader just gets fewer rows
than the producer wrote, which surfaces as the board quietly losing props or
candidates and then recovering on the next cycle. That is one of the
symptoms #25 exists to remove.

`refresh_state_store` already solved this for STATE writes
(`_atomic_write_text`). This is the same guarantee for artifact writes,
which live outside that module and mostly bypassed it.

Why not reuse the `path.with_suffix(path.suffix + ".tmp")` pattern that
several fetchers already use: that name is derived only from the
destination, so two processes writing the same artifact -- which genuinely
happens here, since refresh runs can overlap across three services -- share
one temp path and interleave into it. The winner then renames a file the
loser was still writing. Including pid and a uuid makes each writer's temp
private, so the worst case is a wasted write rather than a corrupt artifact.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any


def atomic_write_text(path: Path | str, text: str, *, encoding: str = "utf-8") -> None:
    """Write `text` to `path` so readers see either the old file or the new
    one, never a partial one.

    The temp file is created in the DESTINATION directory on purpose:
    os.replace is only atomic within a single filesystem, and a temp in
    /tmp would silently degrade to a copy across a mount boundary --
    exactly the non-atomic behaviour being removed.
    """
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_path = destination.parent / f"{destination.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
    try:
        temp_path.write_text(str(text if text is not None else ""), encoding=encoding)
        os.replace(temp_path, destination)
    finally:
        # A crash between write and replace would otherwise leave the temp
        # behind in a directory the artifact readers glob over.
        try:
            if temp_path.exists():
                temp_path.unlink()
        except OSError:
            pass


def atomic_write_csv(path: Path | str, frame: Any, **to_csv_kwargs: Any) -> None:
    """Atomic `DataFrame.to_csv`. Renders to a string first, so a failure
    while serialising leaves the previous artifact untouched rather than
    truncated -- a partially-serialised artifact is worse than a stale one,
    because staleness is detectable downstream and truncation is not.
    """
    to_csv_kwargs.setdefault("index", False)
    atomic_write_text(path, frame.to_csv(**to_csv_kwargs))
