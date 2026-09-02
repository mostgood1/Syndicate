"""Manifest-driven prod->local mirror. `todo.md #625` build item (1), laws (1) and (2).

    py -3 scripts/mirror_manifest.py inventory
    py -3 scripts/mirror_manifest.py sync   --date 2026-09-01 --family mlb_book_grid_replay
    py -3 scripts/mirror_manifest.py verify --date 2026-09-01
    py -3 scripts/mirror_manifest.py list

WHAT THIS REPLACES AND WHY
--------------------------
`scripts/refresh_<sport>_source_mirror.ps1` (seven of them) and the backup
workflow each pull a different subset on a different schedule into
`data/<sport>_source/` INSIDE THE GIT TREE. That is the mechanism behind
`CLAUDE.md`'s measured trap: four MLB artifact families whose git-tracked date
windows are 46 / 33 / 26 / 11 dates and whose intersection is **one usable
date**. An analysis that joins across them silently collapses to that
intersection and still looks like it ran on months of data.

The fix is not a bigger pull. It is that **a local claim must be able to cite
what it actually had** -- law (2), "parity or it isn't evidence". So every sync
writes a content-addressed manifest, and `verify` re-hashes the files against
it. `--cite` prints the manifest id a claim should quote.

ONE-WAY, BY CONSTRUCTION (law (1))
----------------------------------
This module imports no publisher and calls no POST. Data moves prod->local
only. Code and config move local->prod only via git and the deploy locks, which
are somewhere else entirely. There is deliberately no `push` subcommand here;
adding one would make this file the bidirectional channel the law forbids.

TWO MEASUREMENTS THAT SHAPE THE DESIGN, both taken 2026-09-02 against production
-------------------------------------------------------------------------------
1. `/api/ops/artifacts/export?names_only=1` inventories the WHOLE hot artifact
   set -- **33,221 files / 13.97 GB -- in 13.0 seconds and 2.8 MB of JSON**. It
   never opens a file (`ops.py:2239-2260`), so there is no body budget to
   exceed. A full inventory is therefore cheap enough to take on every sync,
   and "verify by manifest, not by timestamp" costs one call.
2. **A narrow `pattern=` costs exactly the same as no pattern at all.** The
   handler globs all ~155 `HOT_ARTIFACT_PATTERNS` first and applies `pattern=`
   as a post-filter (`ops.py:2240-2248`), so the walk is the cost and the
   filter saves nothing. Ten per-family queries are therefore ten full walks.
   This tool takes ONE inventory and filters locally.

WHAT THE MANIFEST CAN AND CANNOT ASSERT -- stated because a guard that overstates
--------------------------------------------------------------------------------
`names_only` returns `bytes` and `mtime`. It does NOT return a hash, and there
is no endpoint that does. So:

- REMOTE side: size and mtime. Two different files of equal length are
  indistinguishable to this tool at the remote end. Say so rather than call it
  parity.
- LOCAL side: sha256, computed here after the transfer.
- What `sync` therefore proves is **transfer integrity** (local length ==
  the length production reported) and what `verify` proves is **local
  non-drift** (the bytes have not changed since the sync). That pair is what
  makes a mirrored day usable as a replay fixture; it is not a claim that
  production's file is byte-identical to ours, and nothing here says it is.

`mtime` is recorded and deliberately never compared. Modern Standby stalled a
scheduled run 9h13m between dispatch and execution (`lastRunAt is dispatch, not
execution`), so a timestamp answers a different question than the one a sync
asks.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts._pipeline_diag import WEB_BASE, _load_dotenv  # noqa: E402

MANIFEST_DIRNAME = "_manifests"
MANIFEST_VERSION = 1

# Families are named GROUPS OF GLOBS over the relative artifact path, with
# `{date}` (2026-09-01) and `{slug}` (2026_09_01) substituted. They are globs
# rather than exact paths on purpose: `mirror_pull.py`'s `FAMILY_PATHS` is a
# list of exact templates, which is precise and cannot express "every sim file
# for this date" without knowing the game keys in advance.
#
# Every family here is INPUT-side or OUTPUT-side for a replay target, and says
# which. `replay_diff_gate.py` reads these names; keep them in step.
FAMILIES: dict[str, dict[str, Any]] = {
    "mlb_book_grid_replay": {
        "role": "input",
        "note": "what build_book_grid_artifact('mlb', D) reads: the tick tape plus its last-seen index.",
        "patterns": (
            "mlb_source/tracking/book_quotes/{date}.jsonl",
            "mlb_source/tracking/book_quotes/{date}.state.json",
        ),
    },
    "mlb_book_grid_enrichment": {
        "role": "input",
        # ADJACENT DATES, and this is a MEASURED requirement rather than caution.
        # `attach_game_state` asks the scoreboard for "the dates the ROWS
        # actually span, not just this artifact's date" (`board_enrichment.py:70-97`,
        # `#348`) -- the shard is keyed by CAPTURE date, so a fixture quoted a day
        # early lands in the earlier shard. Replayed with day D alone, the
        # 2026-09-01 grid reported `game_state.chips = 15` against production's
        # 30: exactly one slate's worth missing, because D+1's schedule was not
        # in the fixture. A fixture that stops at D silently halves this join.
        "note": (
            "what board_enrichment's attach_* steps read for the same date. NOTE the two "
            "date spellings: the daily/live_lens families use the SLUG (2026_08_29) while "
            "the snapshot directory and the ledger use the ISO date. Guessing one form "
            "returns zero matches, which reads exactly like 'production has none'."
        ),
        # D ONLY, and the D+1 experiment is recorded because the NEGATIVE result
        # is the useful one. `attach_game_state` resolves chips for the dates the
        # ROWS span (`board_enrichment.py:70-97`), so a D+1 slate is genuinely
        # read -- replaying D alone gives `game_state.chips = 15` against
        # production's 30. But D's grid is rebuilt DURING D+1, so D+1's snapshot
        # directory is still being written when production answers: measured over
        # nine consecutive MLB dates, `D+1 inputs settled before D's output` was
        # FALSE on 9 of 9, by 743s to 1,510s on 2026-09-01 alone.
        #
        # So the D+1 half of that join is not a fixture gap that a wider pull
        # closes -- it is structurally unmirrorable, and `replay_diff_gate.py`
        # declares it UNREPLAYABLE rather than pretending a bigger sync fixes it.
        "patterns": (
            ("mlb_source/source_artifacts/data/daily/daily_summary_{slug}*.json", (0,)),
            ("mlb_source/source_artifacts/data/daily/snapshots/{date}/*.json", (0,)),
            ("mlb_source/source_artifacts/data/live_lens/live_lens_report_{slug}.json", (0,)),
            ("mlb_source/data/live_gameline_ledger/live_gameline_ledger_{date}.jsonl", (0,)),
        ),
    },
    "mlb_book_grid_output": {
        "role": "output",
        "note": "production's OWN answer for the date -- the thing the replay is diffed against.",
        "patterns": ("mlb_source/data/book_grid/book_grid_{date}.json",),
    },
}


def mirror_root(explicit: str | None = None) -> Path:
    """Resolve the mirror root, or refuse.

    There is deliberately NO silent default. A guessed data root is how a run
    reads a tree nobody meant it to read and reports a confident number about
    the wrong machine; `unknown must not default permissive` applies to paths
    exactly as it does to gate predicates.
    """
    raw = (explicit or os.environ.get("SYNDICATE_MIRROR_ROOT") or "").strip()
    if not raw:
        raise SystemExit(
            "no mirror root. Pass --mirror or set SYNDICATE_MIRROR_ROOT.\n"
            "It must live OUTSIDE the git tree and OUTSIDE OneDrive (`#625` practicals):\n"
            "  setx SYNDICATE_MIRROR_ROOT C:\\syndicate-mirror"
        )
    root = Path(raw).expanduser().resolve()
    lowered = str(root).lower().replace("\\", "/")
    if lowered.startswith(str(REPO_ROOT).lower().replace("\\", "/")):
        raise SystemExit(
            f"refusing: mirror root {root} is inside the git tree.\n"
            "`data/**` in git is a lossy mirror and is never evidence about production;\n"
            "putting a real mirror there makes the two indistinguishable to every later reader."
        )
    if "onedrive" in lowered:
        raise SystemExit(
            f"refusing: mirror root {root} is under OneDrive.\n"
            "A ~14 GB artifact set behind a sync client is a different failure every time."
        )
    return root


def _token() -> str:
    token = (os.environ.get("ADMIN_TOKEN") or _load_dotenv().get("ADMIN_TOKEN") or "").strip()
    if not token:
        raise SystemExit("ADMIN_TOKEN not set (env or .env). Cannot read production.")
    return token


def _get(path: str, *, timeout: int = 300) -> tuple[int | None, bytes, str]:
    """GET against web. Returns (status, body, error). Never raises.

    403 and 404 stay DISTINCT all the way to the report. 403 means the path is
    not in `HOT_ARTIFACT_PATTERNS` -- the artifact may well exist on the worker
    and simply cannot cross. 404 means web does not have it. Collapsing them is
    how "not permitted" gets recorded as "absent".
    """
    request = urllib.request.Request(WEB_BASE + path, headers={"X-Admin-Token": _token()})
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=ssl.create_default_context()) as response:
            return response.getcode(), response.read(), ""
    except urllib.error.HTTPError as exc:
        detail = {
            403: "NOT ALLOWLISTED (may exist on the worker; this is not absence)",
            404: "not present on web",
        }.get(exc.code, f"HTTP {exc.code}")
        return exc.code, b"", detail
    except Exception as exc:  # noqa: BLE001
        return None, b"", f"{type(exc).__name__}: {exc}"


def fetch_inventory() -> dict[str, Any]:
    """One call, the whole hot set. See measurement (2) in the module docstring."""
    started = time.time()
    status, body, error = _get("/api/ops/artifacts/export?names_only=1")
    if status != 200:
        raise SystemExit(f"inventory failed: [{status}] {error}")
    payload = json.loads(body)
    if not payload.get("names_only"):
        # The flag was ignored -- which is exactly what happened on 2026-08-08
        # when `names_only` did not yet exist and a caller pulled 30 MB
        # believing they had asked for names. Refuse rather than proceed.
        raise SystemExit(
            "the response is not names_only. This web build ignores the flag; "
            "do NOT retry without it -- an un-flagged export pulls bodies."
        )
    payload["_elapsed_sec"] = round(time.time() - started, 2)
    return payload


def service_version() -> dict[str, Any]:
    status, body, error = _get("/api/ops/version", timeout=60)
    if status != 200:
        return {"ok": False, "error": f"[{status}] {error}"}
    try:
        return json.loads(body).get("version") or {}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def resolve_patterns(family: str, date_str: str) -> tuple[str, ...]:
    spec = FAMILIES.get(family)
    if spec is None:
        raise SystemExit(f"unknown family {family!r}. known: {', '.join(sorted(FAMILIES))}")
    anchor = date.fromisoformat(date_str)
    default_offsets = spec.get("date_offsets") or (0,)
    out: list[str] = []
    for entry in spec["patterns"]:
        # A pattern is either a bare template (default offsets) or
        # `(template, offsets)`. Per-pattern offsets exist because a fixture
        # widened uniformly pulls in files that are still being written.
        pattern, offsets = entry if isinstance(entry, tuple) else (entry, default_offsets)
        for offset in offsets:
            day = (anchor + timedelta(days=offset)).isoformat()
            out.append(pattern.format(date=day, slug=day.replace("-", "_")))
    # de-duplicated, order preserved: two offsets can resolve to the same glob
    # when a pattern carries no date token at all.
    seen: set[str] = set()
    return tuple(p for p in out if not (p in seen or seen.add(p)))


def match_inventory(inventory: dict[str, Any], patterns: Iterable[str]) -> dict[str, dict[str, Any]]:
    artifacts = inventory.get("artifacts") or {}
    out: dict[str, dict[str, Any]] = {}
    for pattern in patterns:
        for relative_path, entry in artifacts.items():
            if fnmatch.fnmatch(relative_path, pattern):
                out[relative_path] = entry
    return out


def sha256_file(path: Path, *, chunk: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(chunk)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def stream_to(relative_path: str, destination: Path, *, timeout: int = 900) -> tuple[bool, str, int]:
    """Pull ONE artifact via /api/ops/artifacts/stream, straight to disk.

    `stream` and not `export`: export accumulates whole bodies into a dict on a
    2 GB web instance and truncates at a 24 MB budget. The MLB tick tape is
    163 MB. Streaming is the only transport that can carry it, and the one that
    does not put web at risk while it does.
    """
    url = f"{WEB_BASE}/api/ops/artifacts/stream?path={relative_path}"
    request = urllib.request.Request(url, headers={"X-Admin-Token": _token()})
    temporary = destination.with_suffix(destination.suffix + ".part")
    temporary.parent.mkdir(parents=True, exist_ok=True)
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=ssl.create_default_context()) as response:
            written = 0
            with temporary.open("wb") as handle:
                while True:
                    block = response.read(1 << 20)
                    if not block:
                        break
                    handle.write(block)
                    written += len(block)
        # Replace only after the whole body landed. A partial file that looks
        # like a complete one is the worst outcome here: the replay would run
        # on a truncated tape and produce a confident wrong diff.
        temporary.replace(destination)
        return True, "", written
    except urllib.error.HTTPError as exc:
        temporary.unlink(missing_ok=True)
        detail = {403: "NOT ALLOWLISTED (may exist on the worker)", 404: "not present on web"}.get(
            exc.code, f"HTTP {exc.code}"
        )
        return False, f"[{exc.code}] {detail}", 0
    except Exception as exc:  # noqa: BLE001
        temporary.unlink(missing_ok=True)
        return False, f"{type(exc).__name__}: {exc}", 0


def manifest_path(root: Path, date_str: str) -> Path:
    return root / MANIFEST_DIRNAME / f"{date_str}.json"


def compute_manifest_id(files: dict[str, dict[str, Any]]) -> str:
    """Content-addressed: the id IS the content, so citing it is checkable."""
    digest = hashlib.sha256()
    for relative_path in sorted(files):
        digest.update(relative_path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(files[relative_path].get("sha256") or "").encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()[:16]


def cmd_inventory(args: argparse.Namespace) -> int:
    inventory = fetch_inventory()
    print(
        f"hot artifact set: {inventory['count']:,} files, {inventory['bytes']:,} bytes, "
        f"in {inventory['_elapsed_sec']}s"
    )
    if args.pattern:
        matched = match_inventory(inventory, [args.pattern])
        total = sum(int(v["bytes"]) for v in matched.values())
        print(f"matching {args.pattern!r}: {len(matched):,} files, {total:,} bytes")
        for relative_path in sorted(matched)[: args.limit]:
            print(f"  {matched[relative_path]['bytes']:>14,}  {relative_path}")
        if len(matched) > args.limit:
            print(f"  ... {len(matched) - args.limit:,} more (raise --limit)")
    return 0


def cmd_sync(args: argparse.Namespace) -> int:
    root = mirror_root(args.mirror)
    date_str = args.date
    families = args.family or [name for name, spec in FAMILIES.items()]
    inventory = fetch_inventory()
    version = service_version()

    print(f"MIRROR SYNC  date={date_str}  root={root}")
    print(f"  source      {WEB_BASE}  commit={version.get('commit', '?')[:8]}  data_root={version.get('syndicate_data_root', '?')}")
    print(f"  inventory   {inventory['count']:,} files / {inventory['bytes']:,} bytes in {inventory['_elapsed_sec']}s (one call)")

    manifest_families: dict[str, Any] = {}
    all_files: dict[str, dict[str, Any]] = {}
    failures = 0

    for family in families:
        patterns = resolve_patterns(family, date_str)
        matched = match_inventory(inventory, patterns)
        spec = FAMILIES[family]
        print(f"\n  [{family}]  role={spec['role']}  patterns={len(patterns)}  matched={len(matched)}")
        if not matched:
            # An empty family is a RESULT, not a skip. It is recorded with its
            # patterns so a later reader can tell "production has none" from
            # "we never asked".
            print("       production reports NO files for these patterns on this date.")
        family_files: dict[str, dict[str, Any]] = {}
        refused: list[dict[str, Any]] = []
        for relative_path in sorted(matched):
            remote = matched[relative_path]
            destination = root / relative_path
            remote_bytes = int(remote["bytes"])
            if destination.is_file() and destination.stat().st_size == remote_bytes and not args.force:
                digest = sha256_file(destination)
                family_files[relative_path] = {
                    "bytes": destination.stat().st_size,
                    "remote_bytes": remote_bytes,
                    "remote_mtime": remote.get("mtime"),
                    "sha256": digest,
                    "transfer": "skipped_same_length",
                }
                print(f"       SAME {remote_bytes:>14,}  {relative_path}")
                continue
            ok, error, written = stream_to(relative_path, destination)
            if not ok:
                failures += 1
                refused.append({"path": relative_path, "error": error})
                print(f"       FAIL {'':>14}  {relative_path}  {error}")
                continue
            digest = sha256_file(destination)
            entry = {
                "bytes": written,
                "remote_bytes": remote_bytes,
                "remote_mtime": remote.get("mtime"),
                "sha256": digest,
                "transfer": "streamed",
            }
            if written != remote_bytes:
                # Transfer integrity is the ONE parity claim this tool can
                # actually make. If it fails, say so loudly rather than record
                # a manifest entry that implies a clean pull.
                entry["length_mismatch"] = True
                failures += 1
                print(f"       LEN! got {written:,} want {remote_bytes:,}  {relative_path}")
            else:
                print(f"       OK   {written:>14,}  {relative_path}")
            family_files[relative_path] = entry
        manifest_families[family] = {
            "role": spec["role"],
            "note": spec["note"],
            "patterns": list(patterns),
            "count": len(family_files),
            "bytes": sum(int(v["bytes"]) for v in family_files.values()),
            "refused": refused,
        }
        all_files.update(family_files)

    manifest = {
        "manifest_version": MANIFEST_VERSION,
        "date": date_str,
        "created_at_iso": datetime.now(timezone.utc).isoformat(),
        "source": {
            "base_url": WEB_BASE,
            "service_commit": version.get("commit"),
            "syndicate_data_root": version.get("syndicate_data_root"),
            "render_instance_id": version.get("render_instance_id"),
        },
        "inventory": {"count": inventory["count"], "bytes": inventory["bytes"]},
        "families": manifest_families,
        "files": all_files,
        "failures": failures,
        "parity_claim": (
            "local length == length production reported at sync time, and sha256 of what "
            "landed locally. NOT a claim that production's bytes equal ours -- names_only "
            "returns no hash and no endpoint does."
        ),
    }
    manifest["manifest_id"] = compute_manifest_id(all_files)
    target = manifest_path(root, date_str)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

    print()
    print(f"  manifest_id  {manifest['manifest_id']}   ({len(all_files)} files, {sum(int(v['bytes']) for v in all_files.values()):,} bytes)")
    print(f"  written      {target}")
    if failures:
        print(f"  FAILURES     {failures} -- this manifest does NOT describe a complete day.")
        return 1
    print("  CITE THIS ID in any claim built on this day's local data (law (2)).")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    root = mirror_root(args.mirror)
    target = manifest_path(root, args.date)
    if not target.is_file():
        print(f"NO MANIFEST for {args.date} at {target}")
        print("A local day with no manifest is not a fixture -- law (2). Run `sync` first.")
        return 3
    manifest = json.loads(target.read_text(encoding="utf-8"))
    files = manifest.get("files") or {}
    missing: list[str] = []
    drifted: list[dict[str, Any]] = []
    checked = 0
    for relative_path, entry in sorted(files.items()):
        path = root / relative_path
        if not path.is_file():
            missing.append(relative_path)
            continue
        digest = sha256_file(path)
        checked += 1
        if digest != entry.get("sha256"):
            drifted.append(
                {
                    "path": relative_path,
                    "manifest_sha256": entry.get("sha256"),
                    "disk_sha256": digest,
                    "manifest_bytes": entry.get("bytes"),
                    "disk_bytes": path.stat().st_size,
                }
            )
    print(f"VERIFY  date={manifest.get('date')}  manifest_id={manifest.get('manifest_id')}")
    print(f"  files in manifest {len(files)}   re-hashed {checked}   missing {len(missing)}   drifted {len(drifted)}")
    for relative_path in missing[:20]:
        print(f"    MISSING  {relative_path}")
    for row in drifted[:20]:
        print(f"    DRIFT    {row['path']}  {row['manifest_bytes']:,}B -> {row['disk_bytes']:,}B")
    if missing or drifted:
        print("  FAIL -- the local tree is not the tree this manifest describes.")
        return 1
    print("  OK -- local bytes are exactly what this manifest recorded.")
    if args.cite:
        print(f"\n  cite: mirror manifest {manifest.get('manifest_id')} ({manifest.get('date')}, {len(files)} files)")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    root = mirror_root(args.mirror)
    directory = root / MANIFEST_DIRNAME
    if not directory.is_dir():
        print(f"no manifests under {directory}")
        return 3
    rows = sorted(directory.glob("*.json"))
    if not rows:
        print(f"no manifests under {directory}")
        return 3
    print(f"{'date':<12} {'manifest_id':<18} {'files':>6} {'bytes':>16}  created")
    for path in rows:
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            print(f"{path.stem:<12} UNREADABLE ({type(exc).__name__})")
            continue
        files = manifest.get("files") or {}
        print(
            f"{manifest.get('date', path.stem):<12} {manifest.get('manifest_id', '?'):<18} "
            f"{len(files):>6} {sum(int(v.get('bytes') or 0) for v in files.values()):>16,}  "
            f"{manifest.get('created_at_iso', '?')}"
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--mirror", help="mirror root (else SYNDICATE_MIRROR_ROOT)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_inventory = sub.add_parser("inventory", help="one names_only call: what production has right now")
    p_inventory.add_argument("--pattern", help="fnmatch glob, filtered LOCALLY (a remote pattern saves nothing)")
    p_inventory.add_argument("--limit", type=int, default=40)
    p_inventory.set_defaults(func=cmd_inventory)

    p_sync = sub.add_parser("sync", help="pull a date's families and write its manifest")
    p_sync.add_argument("--date", required=True)
    p_sync.add_argument("--family", action="append", choices=sorted(FAMILIES), help="repeatable; default all")
    p_sync.add_argument("--force", action="store_true", help="re-pull even when local length already matches")
    p_sync.set_defaults(func=cmd_sync)

    p_verify = sub.add_parser("verify", help="re-hash the local tree against a manifest")
    p_verify.add_argument("--date", required=True)
    p_verify.add_argument("--cite", action="store_true")
    p_verify.set_defaults(func=cmd_verify)

    p_list = sub.add_parser("list", help="manifests present locally")
    p_list.set_defaults(func=cmd_list)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
