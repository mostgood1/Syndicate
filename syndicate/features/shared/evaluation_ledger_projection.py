"""Persist a PROJECTED copy of each evaluation-ledger chunk, so the ledger can
leave refresh-worker at all.

WHY THIS EXISTS, and it is a reachability problem rather than a size problem.
The evaluation ledger is the input to `build_accuracy_summary`, and it is
readable ONLY from inside refresh-worker. Measured 2026-09-04:

  * refresh-worker is `type: worker` in `render.yaml`. It serves no HTTP.
  * `/api/ops/artifacts/stream` and `/export` run on WEB and read WEB's disk --
    `ops.py` says in its own comments that the route gates on
    `target.is_file()` and that allowlisting a path web does not hold "would 404
    forever". Allowlisting the raw chunks is therefore not a fix, it is a 404.
  * the worker->web publish sweep caps at `_PUBLISH_MAX_BYTES` = 12 MiB, and
    production chunks run **95-332 MB/day**. They are 8-27x over. They cannot
    cross by that path either.

So there is no HTTP route out for a raw chunk, and the accuracy summary is stuck
computing inside a 4 GB box that is simultaneously running board builds, MLB
sims and odds refreshes -- which is what forces the ledger byte budget, the
truncation, and a drift window that had ~1 day of baseline against a specified
21.

THE PROJECTION IS THE WAY OUT, and the number is the whole argument.
`_project_evaluation_record` already reduces a record to the ~20 scalars the
statistics read, and it is already applied in `build_accuracy_summary`'s stream
and then DISCARDED. Persisting it costs almost nothing and shrinks the artifact
by more than an order of magnitude:

    measured over 1,463 real records      14.24 MB -> 0.706 MB   (20.2x)
    per-record projected cost SATURATES   ~560 B, flat above a floor
      raw quartile 2/3/4: 11,397 -> 566 B, 12,336 -> 563 B, 13,226 -> 558 B
    production raw density (RENDER)       42,595 B/record, 4.0x larger than local
    => a typical 250 MB chunk projects to ~3.3 MB, the largest 332 MB to ~4.4 MB

Both land under `_PUBLISH_STREAM_MIN_BYTES` (4 MiB, so the ordinary JSON
envelope carries them) and far under the 12 MiB sweep ceiling. Breaching the
ceiling would need 2,144 B/record on a typical chunk -- **3.8x** the saturated
value.

**THE PER-RECORD FIGURE IS A CHECKOUT MEASUREMENT joined to a RENDER density.**
That is an inference across two substrates, not one measurement, and
`ledger_coverage.projected_bytes` (live on refresh-worker since 2026-09-04
18:44:18Z) is what turns it into a reading. `PROJECTION_OVER_CEILING` below is
the falsifier if the inference is wrong -- it fires loudly rather than shipping
a file the sweep will silently refuse.

WHAT THIS DELIBERATELY DOES NOT DO
----------------------------------
* **It does not compress.** At ~3.3 MB against a 12 MiB ceiling there is a 3.6x
  margin, and gzip would buy another ~5x at the cost of a binary artifact --
  `/api/ops/artifacts/export` returns DECODED TEXT and answers HTTP 500 on a
  file it cannot decode. Compress only if `PROJECTION_OVER_CEILING` ever fires.
* **It does not project the whole history on one run.** `max_chunks` bounds it,
  newest-first. A first pass over ~32 chunks would stream ~8 GB inside a job
  that already takes 669 s, and "worker periodic work is never free" is a rule
  this repo paid for with a production restart loop (`#241`). It converges over
  a few days instead, and the steady state is one chunk a day.
* **It does not re-read what it already has.** A chunk is rewritten only when
  the source is at least as new as the projection, so the steady-state cost is
  today's chunk alone. Older chunks are immutable per-day files.
* **It never partially publishes.** Output is written to a temp file and
  `os.replace`d, so a reader (or the sweep) can never see a half-written
  projection.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Iterable

from syndicate.features.shared.intelligence_evaluation import (
    DEFAULT_LEDGER_CHUNK_ROOT,
    _project_evaluation_record,
)

# Imported rather than re-declared ON PURPOSE. The projected field list is the
# contract between this producer and `build_accuracy_summary`; a local copy
# would drift the moment someone adds a field upstream, and the failure would be
# a silently thinner mirror rather than an error. `_project_evaluation_record`
# is private to the module, not to the package.

DEFAULT_MAX_CHUNKS_PER_RUN = 8

# The sweep's own refusal threshold (`artifact_publisher._PUBLISH_MAX_BYTES`).
# Duplicated as a WARNING threshold only -- this module never enforces it, it
# reports when a projection lands near it, because that is the signal that the
# 3.8x margin above has gone.
PROJECTION_CEILING_WARN_BYTES = 12 * 1024 * 1024


def projected_chunk_root(chunk_root: Path | str | None = None) -> Path:
    """Sibling of the chunk root, so it inherits `SYNDICATE_REPORTS_ROOT`.

    Deliberately a SEPARATE directory rather than a suffix inside
    `evaluation_ledger_chunks/`: the allowlist pattern for the projected set
    must not be able to match a raw chunk. A glob that accidentally admitted
    `evaluation_ledger_chunks/*.jsonl` would hand the sweep a 332 MB file.
    """
    root = Path(chunk_root) if chunk_root is not None else DEFAULT_LEDGER_CHUNK_ROOT
    return root.parent / "evaluation_ledger_projected"


def _needs_rewrite(source: Path, target: Path) -> bool:
    """Rewrite unless the projection is STRICTLY newer than its source.

    Not `>=`: today's chunk is appended to continuously, and an append landing
    in the same second as the projection would otherwise be skipped until the
    next day -- a stale mirror that looks fresh. Erring toward rewriting is
    safe because the operation is idempotent, and it costs one chunk a day.
    """
    try:
        if not target.is_file():
            return True
        return target.stat().st_mtime <= source.stat().st_mtime
    except OSError:
        return True


def _project_chunk(source: Path, target: Path) -> tuple[int, int, int]:
    """Stream one chunk through the projection. Returns (records, in, out).

    NEVER materialises. A 332 MB chunk read with `read_text()` is the exact
    defect `#254` fixed in the reader this mirrors, and this producer runs on
    the same 4 GB box.
    """
    temp = target.with_suffix(target.suffix + ".tmp")
    records = 0
    bytes_in = 0
    bytes_out = 0
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with source.open("r", encoding="utf-8") as handle, temp.open(
            "w", encoding="utf-8", newline="\n"
        ) as out:
            for line in handle:
                bytes_in += len(line.encode("utf-8"))
                line = line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except Exception:
                    # Same tolerance as the reader: a malformed line is skipped,
                    # never fatal. A projection that refuses the whole day
                    # because of one bad record is worse than a day short one.
                    continue
                if not isinstance(payload, dict):
                    continue
                slim = _project_evaluation_record(payload)
                if not slim:
                    continue
                encoded = json.dumps(slim, separators=(",", ":"))
                out.write(encoded)
                out.write("\n")
                records += 1
                bytes_out += len(encoded.encode("utf-8")) + 1
        os.replace(temp, target)
    finally:
        # A crashed run must not leave a .tmp behind for the next one to trip
        # over, and must never leave it where a glob could match it.
        try:
            if temp.exists():
                temp.unlink()
        except OSError:
            pass
    return records, bytes_in, bytes_out


def project_ledger_chunks(
    *,
    chunk_root: Path | str | None = None,
    out_root: Path | str | None = None,
    max_chunks: int = DEFAULT_MAX_CHUNKS_PER_RUN,
    publish: bool = True,
) -> dict[str, Any]:
    """Project up to `max_chunks` stale chunks, newest-first, and publish them.

    Returns a stats dict and prints ONE summary line. `print(..., flush=True)`
    rather than `logger.info` -- `#37`, the logger never reaches Render's
    collector.
    """
    source_root = Path(chunk_root) if chunk_root is not None else DEFAULT_LEDGER_CHUNK_ROOT
    target_root = Path(out_root) if out_root is not None else projected_chunk_root(source_root)

    stats: dict[str, Any] = {
        "chunks_seen": 0,
        "chunks_written": 0,
        "chunks_fresh": 0,
        "chunks_failed": 0,
        "chunks_deferred": 0,
        "records": 0,
        "bytes_in": 0,
        "bytes_out": 0,
        "published": 0,
        "over_ceiling": 0,
    }

    try:
        sources = sorted(
            (p for p in source_root.glob("*.jsonl") if p.is_file()),
            key=lambda p: p.name,
            reverse=True,  # newest date first: the budget buys the RECENT days
        )
    except OSError:
        sources = []

    stats["chunks_seen"] = len(sources)
    written: list[Path] = []

    for source in sources:
        target = target_root / source.name
        if not _needs_rewrite(source, target):
            stats["chunks_fresh"] += 1
            continue
        if stats["chunks_written"] >= max(0, int(max_chunks)):
            # Bounded per run BY DESIGN -- see the module docstring. The
            # remainder is not lost, it is picked up on the next run.
            stats["chunks_deferred"] += 1
            continue
        try:
            records, bytes_in, bytes_out = _project_chunk(source, target)
        except Exception as exc:  # one bad chunk must not cost the others
            stats["chunks_failed"] += 1
            print(
                f"[ledger_projection] PROJECTION_FAILED chunk={source.name} "
                f"error={type(exc).__name__}: {exc}",
                flush=True,
            )
            continue
        stats["chunks_written"] += 1
        stats["records"] += records
        stats["bytes_in"] += bytes_in
        stats["bytes_out"] += bytes_out
        written.append(target)
        if bytes_out >= PROJECTION_CEILING_WARN_BYTES:
            # THE FALSIFIER for the sizing this module was built on. If this
            # fires, the projected mirror does not fit the transport and the
            # design needs compression or per-chunk splitting -- do not simply
            # raise the ceiling, whose own comment forbids that.
            stats["over_ceiling"] += 1
            print(
                f"[ledger_projection] PROJECTION_OVER_CEILING chunk={source.name} "
                f"bytes={bytes_out} ceiling={PROJECTION_CEILING_WARN_BYTES} -- "
                f"the sweep will REFUSE this file; the ~3.3MB sizing is wrong",
                flush=True,
            )

    if publish and written:
        # Allowlisting PERMITS a transfer, it does not make one happen (`#208`).
        # The sweep would eventually carry these, but publishing directly is the
        # same pattern `record_openings` uses and it makes the hop observable on
        # the run that produced the file.
        try:
            from syndicate.features.shared.artifact_publisher import publish_hot_artifacts

            stats["published"] = publish_hot_artifacts(written)
        except Exception as exc:
            print(
                f"[ledger_projection] PUBLISH_FAILED error={type(exc).__name__}: {exc}",
                flush=True,
            )

    ratio = (stats["bytes_out"] / stats["bytes_in"]) if stats["bytes_in"] else 0.0
    stats["ratio"] = round(ratio, 6)
    stats["reduction"] = round((1.0 / ratio), 1) if ratio else 0.0
    print(
        f"[ledger_projection] PROJECTION_DONE seen={stats['chunks_seen']} "
        f"written={stats['chunks_written']} fresh={stats['chunks_fresh']} "
        f"deferred={stats['chunks_deferred']} failed={stats['chunks_failed']} "
        f"records={stats['records']} bytes_in={stats['bytes_in']} "
        f"bytes_out={stats['bytes_out']} ratio={stats['ratio']} "
        f"reduction={stats['reduction']}x published={stats['published']} "
        f"over_ceiling={stats['over_ceiling']}",
        flush=True,
    )
    return stats


__all__ = [
    "DEFAULT_MAX_CHUNKS_PER_RUN",
    "PROJECTION_CEILING_WARN_BYTES",
    "project_ledger_chunks",
    "projected_chunk_root",
]
