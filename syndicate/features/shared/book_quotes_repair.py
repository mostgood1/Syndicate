"""Remove splice fragments from `book_quotes` shards, and nothing else.

Lane `book-quotes-splice-repair`, P3 (user decision 2026-09-15). refresh-worker
used to append its own venue rows to a shard AND tail-pull web's copy by byte
offset, so a pull after a local append started mid-line and left a headless
fragment -- the tail of a row that also exists intact elsewhere in the file:

    intact   {"captured_at":"2026-09-03T...","sport":"mlb",...,"price":340}
    fragment Z","sport":"mlb",...,"price":340}

Web merged each fragment as a "new" line (29 in mlb 09-03, 190 in soccer 09-13).
P1 now refuses them at the merge and P2 stops refresh-worker producing them; this
removes the ones already on disk.

THE RULE IS NARROW ON PURPOSE. A line is removed only if it is NOT a JSON object
AND it is a byte SUFFIX of an intact line in the same shard -- the splice
signature. Any other unreadable line is an ORPHAN: counted and reported, never
deleted, because a rule we did not prove against it could be deleting data.

Runs under the same per-path lock the merge child takes, so a merge cannot land
between the read and the rewrite. DRY RUN unless `apply=True`.
"""
from __future__ import annotations

import json
import os
import re
import uuid
from pathlib import Path
from typing import Any, Iterable

_SHARD_NAME = re.compile(r"^(\d{4}-\d{2}-\d{2})\.jsonl$")
_SAMPLE_BYTES = 120
_MAX_SAMPLES = 3


def _is_json_object(line: bytes) -> bool:
    try:
        return isinstance(json.loads(line), dict)
    except Exception:
        return False


def _lines(path: Path) -> Iterable[bytes]:
    with path.open("rb") as handle:
        for raw in handle:
            line = raw.rstrip(b"\r\n")
            if line:
                yield line


def repair_shard(path: Path, *, apply: bool = False, lock_wait_seconds: float = 180.0) -> dict[str, Any]:
    """Counts for one shard, and the rewrite when `apply`. Never raises."""
    from syndicate.features.shared.artifact_merge import append_only_merge_lock

    path = Path(path)
    result: dict[str, Any] = {"shard": f"{path.parent.parent.parent.name}/{path.name}", "apply": bool(apply)}
    lock_path = append_only_merge_lock(path, wait_seconds=lock_wait_seconds)
    if lock_path is None:
        result["error"] = "lock_busy: a merge holds this shard"
        return result
    try:
        result["bytes_before"] = int(path.stat().st_size)
        total = 0
        bad: dict[bytes, int] = {}
        for line in _lines(path):
            total += 1
            if not _is_json_object(line):
                bad[line] = bad.get(line, 0) + 1
        result["lines"] = total
        result["bad_lines"] = sum(bad.values())
        if not bad:
            result.update(verified_fragments=0, orphan_bad_lines=0, bytes_after=result["bytes_before"])
            return result

        by_length: dict[int, set[bytes]] = {}
        for fragment in bad:
            by_length.setdefault(len(fragment), set()).add(fragment)
        lengths = sorted(by_length)
        verified: set[bytes] = set()
        for line in _lines(path):
            if line in bad:
                continue
            size = len(line)
            for length in lengths:
                if length >= size:
                    break
                tail = line[-length:]
                if tail in by_length[length]:
                    verified.add(tail)

        result["verified_fragments"] = sum(bad[f] for f in verified)
        result["orphan_bad_lines"] = sum(count for f, count in bad.items() if f not in verified)
        result["verified_samples"] = [f[:_SAMPLE_BYTES].decode("utf-8", "replace") for f in list(verified)[:_MAX_SAMPLES]]
        result["orphan_samples"] = [
            f[:_SAMPLE_BYTES].decode("utf-8", "replace") for f in bad if f not in verified
        ][:_MAX_SAMPLES]

        if not apply or not verified:
            result["bytes_after"] = result["bytes_before"]
            return result

        temp = path.with_name(f"{path.name}.{os.getpid()}.{uuid.uuid4().hex}.repair")
        removed = 0
        try:
            with temp.open("wb") as out:
                for line in _lines(path):
                    if line in verified:
                        removed += 1
                        continue
                    out.write(line + b"\n")
            os.replace(temp, path)
        finally:
            try:
                temp.unlink(missing_ok=True)
            except Exception:
                pass
        result["removed"] = removed
        result["bytes_after"] = int(path.stat().st_size)
        return result
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        return result
    finally:
        try:
            lock_path.unlink(missing_ok=True)
        except Exception:
            pass


def shard_paths(data_root: Path, *, sports: Iterable[str], since: str) -> list[Path]:
    paths: list[Path] = []
    for sport in sports:
        directory = Path(data_root) / f"{str(sport).strip().lower()}_source" / "tracking" / "book_quotes"
        if not directory.is_dir():
            continue
        for candidate in sorted(directory.glob("*.jsonl")):
            match = _SHARD_NAME.match(candidate.name)
            if match and match.group(1) >= since:
                paths.append(candidate)
    return paths


def repair_book_quotes_shards(data_root: Path, *, sports: Iterable[str], since: str, apply: bool = False) -> dict[str, Any]:
    """Every shard in scope, one `REPAIR_SHARD` line each, then `REPAIR_DONE`."""
    totals = {"shards": 0, "shards_with_bad": 0, "bad_lines": 0, "verified_fragments": 0,
              "orphan_bad_lines": 0, "removed": 0, "errors": 0, "apply": bool(apply), "since": since}
    for path in shard_paths(data_root, sports=sports, since=since):
        result = repair_shard(path, apply=apply)
        totals["shards"] += 1
        totals["errors"] += 1 if result.get("error") else 0
        for key in ("bad_lines", "verified_fragments", "orphan_bad_lines", "removed"):
            totals[key] += int(result.get(key) or 0)
        if result.get("bad_lines"):
            totals["shards_with_bad"] += 1
        print(f"[book_quotes_repair] REPAIR_SHARD {json.dumps(result, sort_keys=True)}", flush=True)
    print(f"[book_quotes_repair] REPAIR_DONE {json.dumps(totals, sort_keys=True)}", flush=True)
    return totals
