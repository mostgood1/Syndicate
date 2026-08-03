"""Compact oversized evaluation-ledger chunk files in place.

Historical ledger records embedded every sport's FULL artifact manifest
(including per-artifact lists spanning MLB's ~32k-file statcast cache) into
``artifact_metadata.manifest_summary.sport_manifests`` -- producing
single-day chunk files of 2.0-2.7GB that no consumer can safely read
(confirmed 2026-08-02, see the end-to-end assessment in
docs/reports/syndicate_end_to_end_assessment_2026_08_02.md). The writer is
fixed (intelligence_evaluation._artifact_manifest_summary now stores a slim
provenance row per sport); this script rewrites the already-written history
to the same slim shape so the full ledger becomes loadable again.

Streams line-by-line (never loads a chunk into memory), writes to a temp
file alongside the chunk, and atomically replaces on success. Record count
per chunk is preserved exactly -- only the embedded manifest payloads
shrink -- so the chunk index/manifest stay valid.

Usage:
    py -3 scripts/compact_evaluation_ledger.py --dry-run
    py -3 scripts/compact_evaluation_ledger.py
    py -3 scripts/compact_evaluation_ledger.py --chunk-root <dir> --min-bytes 1000000
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEFAULT_CHUNK_ROOT = REPO_ROOT / "reports" / "intelligence" / "evaluation_ledger_chunks"

# One shared implementation with the persist path -- history and new writes
# must converge on the same slim shape (response -> provenance scalars,
# manifest_summary.sport_manifests -> slim rows, recursed through nested
# prediction/raw/recommendations containers).
from syndicate.features.shared.intelligence_evaluation import slim_evaluation_record_payload  # noqa: E402


def _compact_record_line(line: str) -> tuple[str, bool]:
    """Return (possibly rewritten line, changed?). Unparseable lines pass
    through byte-identical -- this script must never lose a record."""
    stripped = line.strip()
    if not stripped:
        return line, False
    try:
        payload = json.loads(stripped)
    except Exception:
        return line, False
    if not isinstance(payload, dict):
        return line, False
    slimmed, changed = slim_evaluation_record_payload(payload)
    if not changed:
        return line, False
    return json.dumps(slimmed, sort_keys=False, default=str), True


def compact_chunk(chunk_path: Path, *, dry_run: bool = False) -> dict[str, Any]:
    original_bytes = chunk_path.stat().st_size
    temp_path = chunk_path.with_suffix(chunk_path.suffix + ".compact_tmp")
    records = 0
    rewritten = 0
    written_bytes = 0
    try:
        with chunk_path.open("r", encoding="utf-8") as reader:
            if dry_run:
                for line in reader:
                    if not line.strip():
                        continue
                    records += 1
                    compacted, changed = _compact_record_line(line)
                    rewritten += int(changed)
                    written_bytes += len(compacted.encode("utf-8")) + 1
            else:
                with temp_path.open("w", encoding="utf-8", newline="\n") as writer:
                    for line in reader:
                        if not line.strip():
                            continue
                        records += 1
                        compacted, changed = _compact_record_line(line)
                        rewritten += int(changed)
                        writer.write(compacted.rstrip("\n") + "\n")
        if not dry_run:
            written_bytes = temp_path.stat().st_size
            os.replace(temp_path, chunk_path)
    finally:
        if temp_path.exists() and (dry_run or written_bytes == 0):
            try:
                temp_path.unlink()
            except OSError:
                pass
    return {
        "chunk": chunk_path.name,
        "records": records,
        "rewritten": rewritten,
        "before_bytes": original_bytes,
        "after_bytes": written_bytes,
        "dry_run": dry_run,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compact oversized evaluation-ledger chunk files")
    parser.add_argument("--chunk-root", default=str(DEFAULT_CHUNK_ROOT))
    parser.add_argument("--min-bytes", type=int, default=1_000_000, help="Only compact chunk files at least this large")
    parser.add_argument("--dry-run", action="store_true", help="Report what would change without writing")
    args = parser.parse_args(argv)

    chunk_root = Path(args.chunk_root)
    if not chunk_root.exists():
        print(json.dumps({"ok": False, "error": f"chunk root not found: {chunk_root}"}))
        return 1

    results = []
    for chunk_path in sorted(chunk_root.glob("*.jsonl")):
        if chunk_path.stat().st_size < max(0, int(args.min_bytes)):
            continue
        result = compact_chunk(chunk_path, dry_run=bool(args.dry_run))
        results.append(result)
        print(
            f"[compact_evaluation_ledger] {result['chunk']} records={result['records']} rewritten={result['rewritten']} "
            f"{result['before_bytes']:,}B -> {result['after_bytes']:,}B dry_run={result['dry_run']}",
            flush=True,
        )

    total_before = sum(int(r["before_bytes"]) for r in results)
    total_after = sum(int(r["after_bytes"]) for r in results)
    print(
        f"[compact_evaluation_ledger] DONE chunks={len(results)} {total_before:,}B -> {total_after:,}B",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
