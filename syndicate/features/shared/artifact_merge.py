"""Merging a published artifact into the copy already on disk. `#630`.

WHY THIS IS A MODULE AND NOT PART OF THE BLUEPRINT. The `odds_history` merge is
run in a SUBPROCESS, off the request path, so it has to be importable without
dragging Flask in. Extracting it also puts the merge rules next to nothing else,
which is what they are: pure functions over two files.

--------------------------------------------------------------------------
THE DEFECT ALL OF THIS EXISTS FOR
--------------------------------------------------------------------------

Two services each keep their OWN copy of a published artifact, append only their
own rows to it, and then publish the WHOLE FILE. Web kept whichever published
last. Measured 2026-09-01 on `book_quotes/2026-09-01.jsonl`: a refetch an hour
later had LOST 1,318 exchange rows and gained none, a clean tail truncation,
while sportsbook rows gained a whole hour. Merging makes publishes COMMUTATIVE.

--------------------------------------------------------------------------
WHY `odds_history` RUNS OUT OF PROCESS AND `book_quotes` DOES NOT
--------------------------------------------------------------------------

MEASURED, and the two are not close:

    book_quotes  (line union)   34 MB in ->  20 MB peak   0.59x   <- SYNTHETIC
    book_quotes  (line union)  154 MB target -> 81 MB peak 0.53x   <- REAL SCALE
    odds_history (JSON union)   88 MB in -> 276 MB peak   3.13x

**BOTH RUN OUT OF PROCESS NOW.** The line union looked cheap at 20 MB and I kept
it on the request path on that basis -- but production's `book_quotes` shard is
**150 MB**, not the 34 MB I had measured, and at real scale it peaks at **81 MB
per merge** on the most frequent publish on the platform. The RATIO held; the
absolute number, which is what ratchets a worker, was 4x larger. Measuring small
and generalising the DECISION rather than the ratio is the same error that sized
the odds_history cap on a 39 MB soccer shard when MLB's pair was 109 MB.

The line union streams and holds only 16-byte digests, so it is sub-linear and
stays on the request path. The JSON union must hold two parsed documents, and on
web -- a 2Gi service -- that RATCHETED THE FLOOR: unreclaimable memory went
717.7 MB at boot to ~1030 MB once merges started and did NOT come back, because
CPython does not return freed arenas to the OS. A background THREAD would not
have helped: same process, same arenas. A SUBPROCESS does, because the child's
whole address space is reclaimed when it exits.

It also restores an architectural rule this had broken -- `CLAUDE.md`: *"The web
service does no heavy computation."* A 276 MB parse in a request handler is
exactly what that forbids.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
import uuid
from pathlib import Path

from syndicate.features.shared.refresh_state_store import data_root

CHUNK_BYTES = 1024 * 1024

# MEASURED TWICE, AND THE FIRST CAP WAS SIZED ON THE WRONG SPORT.
#
#   soccer shard  39,581,487 B / 2,745 markets -> peak 189 MB on  72 MB (2.6x)
#   MLB shard     54,909,482 B / 3,873 markets -> peak 276 MB on  88 MB (3.13x)
#
# A 100 MiB cap sized on soccer made the merge INERT on MLB's 109,448,725 B
# pair -- the very first live publish logged `over_size_cap` and replaced
# instead. It was visible only because the fallback logs its reason.
ODDS_HISTORY_MERGE_MAX_INPUT_BYTES = 160 * 1024 * 1024
ODDS_HISTORY_MERGE_LOCK_STALE_SECONDS = 300


def is_append_only_jsonl(relative_path: str) -> bool:
    """Kept as a thin alias so callers read symmetrically; the authority is
    `artifact_publisher._is_append_only`, imported by the blueprint. Do not
    duplicate that list here -- it is the SAME predicate that decides a
    Range/tail pull, and two copies is how one starts merging a family the
    other still replaces."""
    raise NotImplementedError("import _is_append_only from artifact_publisher")


def is_mergeable_odds_history(relative_path: str) -> bool:
    text = str(relative_path or "")
    return "/odds_history/" in text and text.endswith(".json")


# ---------------------------------------------------------------------------
# append-only JSONL: a line union, cheap enough to stay on the request path
# ---------------------------------------------------------------------------

def iter_lines(path: Path):
    """Newline-stripped lines as bytes, skipping blanks. Bounded memory."""
    try:
        with path.open("rb") as handle:
            for raw in handle:
                line = raw.rstrip(b"\r\n")
                if line:
                    yield line
    except Exception:
        return


def ends_with_newline(path: Path) -> bool:
    try:
        size = path.stat().st_size
        if size <= 0:
            return True
        with path.open("rb") as handle:
            handle.seek(-1, os.SEEK_END)
            return handle.read(1) in (b"\n", b"\r")
    except Exception:
        return True


def append_only_merge_lock(target_path: Path, *, wait_seconds: float = 0.0):
    """PER-PATH admission for the line merge, unlike odds_history's ONE global
    lock. The global lock exists to bound MEMORY (276 MB a merge); the line
    merge peaks at 81 MB on a 154 MB target, so two of them on DIFFERENT files
    are affordable and serialising them would queue the most frequent publish on
    the platform behind everything else. Two children on the SAME target must
    still not race, hence per-path."""
    lock_path = target_path.parent / f".{target_path.name}.merge.lock"
    deadline = time.time() + max(0.0, wait_seconds)
    while True:
        try:
            if lock_path.is_file():
                age = time.time() - lock_path.stat().st_mtime
                if age > ODDS_HISTORY_MERGE_LOCK_STALE_SECONDS:
                    lock_path.unlink(missing_ok=True)
            handle = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(handle)
            return lock_path
        except FileExistsError:
            if time.time() >= deadline:
                return None
            time.sleep(0.25)
        except Exception:
            return None


def merge_append_only(target_path: Path, incoming_path: Path,
                      *, lock_wait_seconds: float = 0.0) -> dict:
    """UNION an incoming append-only artifact into the one already on disk.

    THE LOAD-BEARING INVARIANT IS THAT THE EXISTING FILE STAYS A BYTE PREFIX OF
    THE RESULT. Existing bytes are copied through untouched and new lines are
    only appended -- never reordered, never rewritten. That is not tidiness:
    `artifact_publisher.pull_streamed_artifact` fetches these families by HTTP
    Range from the worker's local size, so any edit before that offset would
    splice two different files together on the worker. Merging is what finally
    MAKES that append-only assumption true.

    DEDUP IS ON THE WHOLE LINE, not a parsed semantic key. A semantic key needs
    a schema, and getting one wrong collapses two genuinely different
    observations -- silent, unrecoverable loss. Whole-line identity can only
    collapse rows that are already byte-identical, which is what a re-publish
    of the same file produces, so this is idempotent.

    RACES ARE SELF-HEALING, which is why there is no lock: every publisher sends
    its COMPLETE file every cycle, so rows lost to an interleaved
    read-modify-write are re-offered on the next publish.
    """
    lock_path = append_only_merge_lock(target_path, wait_seconds=lock_wait_seconds)
    if lock_path is None:
        return {"merged": False, "error": "merge_busy: another child holds this path"}
    try:
        return _merge_append_only_locked(target_path, incoming_path)
    finally:
        try:
            lock_path.unlink(missing_ok=True)
        except Exception:
            pass


def _merge_append_only_locked(target_path: Path, incoming_path: Path) -> dict:
    digests: set[bytes] = set()
    existing_lines = 0
    for line in iter_lines(target_path):
        digests.add(hashlib.blake2b(line, digest_size=16).digest())
        existing_lines += 1

    merged_path = target_path.parent / f"{target_path.name}.{os.getpid()}.{uuid.uuid4().hex}.merge"
    added = 0
    duplicates = 0
    try:
        with merged_path.open("wb") as out:
            with target_path.open("rb") as current:
                shutil.copyfileobj(current, out, CHUNK_BYTES)
            if existing_lines and not ends_with_newline(target_path):
                out.write(b"\n")
            for line in iter_lines(incoming_path):
                digest = hashlib.blake2b(line, digest_size=16).digest()
                if digest in digests:
                    duplicates += 1
                    continue
                digests.add(digest)
                out.write(line + b"\n")
                added += 1
        os.replace(merged_path, target_path)
    except Exception as exc:
        try:
            merged_path.unlink(missing_ok=True)
        except Exception:
            pass
        return {"merged": False, "error": f"{type(exc).__name__}: {exc}"}
    return {"merged": True, "existing_lines": existing_lines,
            "added": added, "duplicates": duplicates}


# ---------------------------------------------------------------------------
# odds_history JSON: a document union, run OUT OF PROCESS
# ---------------------------------------------------------------------------

def odds_history_recency(entry) -> str:
    """How recent an entry is, for picking a winner. Never guesses a shape."""
    if not isinstance(entry, dict):
        return ""
    for field in ("last_updated", "last_snapshot_ts"):
        value = str(entry.get(field) or "").strip().replace("Z", "+00:00")
        if value:
            return value
    return ""


def odds_history_merge_lock(root: Path | None = None, *, wait_seconds: float = 0.0):
    """Service-wide single-merge admission, or None if it is held.

    ONE lock for the whole service, NOT one per directory.
    `<sport>_source/tracking/odds_history/` and
    `<sport>_source/artifacts/<sport>/odds_history/` are DIFFERENT directories,
    and those two twins are exactly the pair observed publishing 2 SECONDS
    apart -- so a per-directory lock would have let the one case it was built
    for run concurrently anyway.
    """
    base = root if root is not None else data_root()
    lock_path = Path(base) / ".odds_history_merge.lock"
    deadline = time.time() + max(0.0, wait_seconds)
    while True:
        try:
            if lock_path.is_file():
                age = time.time() - lock_path.stat().st_mtime
                if age > ODDS_HISTORY_MERGE_LOCK_STALE_SECONDS:
                    lock_path.unlink(missing_ok=True)
            handle = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(handle)
            return lock_path
        except FileExistsError:
            # WAITING IS THE POINT when the caller is the detached child: nothing
            # is blocked on it. Measured in production 2026-09-02, TWELVE
            # odds_history publishes landed inside 2 SECONDS (each shard plus its
            # artifacts twin, several match dates at once). A non-blocking lock
            # admitted one and DROPPED eleven -- self-healing on the next cycle,
            # but a 1-in-12 hit rate is a bottleneck, not a guard. On the request
            # path waiting was not an option; here it is the correct behaviour.
            if time.time() >= deadline:
                return None
            time.sleep(0.25)
        except Exception:
            return None


def merge_odds_history(target_path: Path, incoming_path: Path,
                       *, root: Path | None = None,
                       lock_wait_seconds: float = 0.0) -> dict:
    """UNION two `odds_history` documents by market key.

    Shape, read from the live shard rather than assumed (2,745 markets):

        {schema_version, sport, shard_key, date, updated_at, history_limit,
         markets: {<market_key>: {history: [...], last_line, previous_line,
                                  delta, movement, last_updated, ...}}}

    ENTRIES ARE TAKEN WHOLESALE, NEVER FIELD-MIXED, and that is the safety
    property. Each entry carries a `history` list AND scalars DERIVED from
    consecutive history points. Merging two histories while keeping one side's
    scalars would publish an entry whose `previous_line` does not correspond to
    its own history -- an inconsistency nothing downstream could detect.

    STRICTLY BETTER THAN THE REPLACE IT REMOVES, for every key:
      * key only in the existing copy -> today DESTROYED; here it survives.
      * key only in the incoming copy -> unchanged.
      * key in both -> today the INCOMING wins EVEN WHEN IT IS THE STALER of the
        two; here the newer one wins.
    """
    try:
        combined = target_path.stat().st_size + incoming_path.stat().st_size
    except Exception as exc:
        return {"merged": False, "error": f"stat_failed: {type(exc).__name__}: {exc}"}
    if combined > ODDS_HISTORY_MERGE_MAX_INPUT_BYTES:
        return {"merged": False,
                "error": f"over_size_cap: {combined} > {ODDS_HISTORY_MERGE_MAX_INPUT_BYTES}"}

    lock_path = odds_history_merge_lock(root, wait_seconds=lock_wait_seconds)
    if lock_path is None:
        return {"merged": False, "error": "merge_busy: another worker holds the merge lock"}
    try:
        return _merge_odds_history_locked(target_path, incoming_path)
    finally:
        try:
            lock_path.unlink(missing_ok=True)
        except Exception:
            pass


def _merge_odds_history_locked(target_path: Path, incoming_path: Path) -> dict:
    # PARSED SEPARATELY so the caller can tell WHICH side failed, and that
    # distinction decides whether the staged copy may be promoted. A refusal
    # normally falls back to the plain replace -- but promoting an UNPARSEABLE
    # incoming would overwrite a good artifact with garbage, so that one case
    # must be distinguishable. One combined try/except could not tell them apart.
    try:
        existing = json.loads(target_path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        return {"merged": False,
                "error": f"target_unparseable: {type(exc).__name__}: {exc}"}
    try:
        incoming = json.loads(incoming_path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        return {"merged": False, "do_not_promote": True,
                "error": f"incoming_unparseable: {type(exc).__name__}: {exc}"}

    # SHAPE GATE. An unrecognised document is REPLACED, not merged -- guessing a
    # shape is how a merge corrupts something it was never meant to touch.
    for doc in (existing, incoming):
        if not isinstance(doc, dict) or doc.get("schema_version") != 1:
            return {"merged": False, "error": "shape_gate: not a schema_version=1 document"}
        if not isinstance(doc.get("markets"), dict):
            return {"merged": False, "error": "shape_gate: markets is not a mapping"}

    existing_markets: dict = existing["markets"]
    incoming_markets: dict = incoming["markets"]
    kept_existing = 0
    replaced = 0
    added = 0
    for key, entry in incoming_markets.items():
        current = existing_markets.get(key)
        if current is None:
            existing_markets[key] = entry
            added += 1
        elif odds_history_recency(entry) >= odds_history_recency(current):
            existing_markets[key] = entry
            replaced += 1
        else:
            kept_existing += 1

    merged_doc = dict(incoming)          # the newer publish owns the metadata ...
    merged_doc["markets"] = existing_markets
    merged_doc["updated_at"] = max(      # ... except the clock, which only moves forward
        str(existing.get("updated_at") or ""), str(incoming.get("updated_at") or "")
    ) or incoming.get("updated_at")
    incoming = None

    merged_path = target_path.parent / f"{target_path.name}.{os.getpid()}.{uuid.uuid4().hex}.merge"
    try:
        # json.dump streams; json.dumps would materialise another ~40MB string.
        with merged_path.open("w", encoding="utf-8") as out:
            json.dump(merged_doc, out, separators=(",", ":"))
        os.replace(merged_path, target_path)
    except Exception as exc:
        try:
            merged_path.unlink(missing_ok=True)
        except Exception:
            pass
        return {"merged": False, "error": f"{type(exc).__name__}: {exc}"}
    return {"merged": True, "markets": len(existing_markets),
            "added": added, "replaced_by_newer": replaced,
            "kept_existing_newer": kept_existing}
