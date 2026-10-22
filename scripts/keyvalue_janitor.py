#!/usr/bin/env python3
"""Expire test-origin keys from the keyvalue state store (dry run unless --apply).

WHY THIS EXISTS (lane fleet-redis-test-pollution, 2026-10-22). The local fleet's
Redis (127.0.0.1:6379) is the production state store. A census of the live
instance found 426 keys that could not be production: 262 whose embedded path is
a Windows temp dir (C:/Users/<u>/AppData/Local/Temp/tmpXXXX/...) and 164 under
WSL /tmp, absent from the 10-16 and 10-18 daily snapshots and first seen in the
10-20 one. They are pytest fixtures written through refresh_state_store while a
test run was pointed at the fleet; 243 of them never expire. 28 were extra
`odds_control_plane/oddsapi_quota.json` documents, and the off-fleet quota
forwarder writes only when EXACTLY ONE such key matches, so a polluted store can
silently stop attributing research spend. The pytest guard in
refresh_state_store._get_keyvalue_client stops new ones from a test process; this
tool removes what got in before the guard, or through a path it cannot see.

WHAT IT TOUCHES -- and the locks that keep it from touching anything else:
  1. only keys under `<namespace>:refresh-state:` (default namespace `syndicate`);
  2. only when the embedded PATH matches a temp-dir signature (Windows
     AppData/Local/Temp, /tmp or /var/tmp, or any pytest-of-<user> dir). The match
     is on the path text, NOT on this host's tempfile.gettempdir(): the janitor
     runs in WSL and must recognise Windows paths;
  3. a PROTECTED root always wins over a signature: /home/<user>/syndicate-prod/
     (the fleet's data root) and /opt/render/ (the Render-era roots). A key under
     either is never a candidate, whatever else its path contains;
  4. a key touched in the last --min-idle-seconds (default 3600) is left alone, so
     a test run in flight is not disrupted;
  5. --max-keys (default 2000) is a tripwire: a candidate set bigger than that is
     refused, because a wrong regex would be far larger than any real mess;
  6. --apply needs a backup (--backup-dir) or an explicit --no-backup. The backup
     is written and fsync'd BEFORE any key is changed, and --restore puts it back.

HOW IT ACTS. Like the existing keyvalue sweeps (refresh_state_store keyvalue_sweep_apply)
it EXPIREs with a grace period (--grace-seconds, default 60) instead of deleting, so a
mistake can still be undone with PERSIST inside the window; --delete-now uses UNLINK.

EXIT CODES: 0 ok / dry run; 1 candidates found with --fail-on-found; 2 Redis
unreachable (nothing changed); 3 backup failed or missing (nothing changed);
4 after --apply some candidates still live, or more than one non-test quota
document remains (the forwarder needs exactly one); 5 --max-keys tripwire (nothing
changed).

    python scripts/keyvalue_janitor.py                                   # dry run, reads like a report
    python scripts/keyvalue_janitor.py --apply --backup-dir <dir>        # expire them, backup first
    python scripts/keyvalue_janitor.py --restore <dir>/keyvalue_janitor_<stamp>.jsonl --apply
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import urlsplit

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEFAULT_URL = "redis://127.0.0.1:6379/0"
STATE_MARKER = ":refresh-state:"
QUOTA_DOC_SUFFIX = "odds_control_plane/oddsapi_quota.json"
BACKUP_PREFIX = "keyvalue_janitor_"

# Signature -> class name. Searched in order; the first match names the class.
_TEST_ORIGIN_CLASSES: tuple[tuple[str, "re.Pattern[str]"], ...] = (
    ("windows_temp", re.compile(r"^[A-Za-z]:[\\/].*?[\\/]AppData[\\/]Local[\\/]Temp[\\/]", re.IGNORECASE)),
    ("posix_tmp", re.compile(r"^/(?:var/)?tmp/")),
    ("pytest_tmp", re.compile(r"[\\/]pytest-of-[^\\/]+[\\/]")),
)
# A key under one of these roots is never a candidate, whatever else its path says.
_PROTECTED_ROOTS: tuple["re.Pattern[str]", ...] = (
    re.compile(r"^/home/[^/]+/syndicate-prod(?:/|$)"),
    re.compile(r"^/opt/render/"),
)


def classify_path(path: str) -> str | None:
    """The test-origin class of a state-key PATH, or None. A protected root wins."""
    if any(rx.search(path) for rx in _PROTECTED_ROOTS):
        return None
    for name, rx in _TEST_ORIGIN_CLASSES:
        if rx.search(path):
            return name
    return None


def is_protected_path(path: str) -> bool:
    return any(rx.search(path) for rx in _PROTECTED_ROOTS)


def state_path(key: str, namespace: str) -> str | None:
    prefix = namespace + STATE_MARKER
    return key[len(prefix):] if key.startswith(prefix) else None


def _text(raw: Any) -> str:
    return raw.decode("utf-8", "replace") if isinstance(raw, (bytes, bytearray)) else str(raw)


@dataclass
class Finding:
    raw: Any                 # the key exactly as Redis returned it (bytes)
    name: str
    path: str
    cls: str
    idle: int | None
    pttl: int                # ms; -1 = no expiry, -2 = gone


@dataclass
class Census:
    scanned: int = 0
    protected_seen: int = 0
    candidates: list[Finding] = field(default_factory=list)
    too_recent: list[Finding] = field(default_factory=list)
    quota_docs_nontest: int = 0


def take_census(client: Any, namespace: str, *, min_idle_seconds: int, count: int = 5000) -> Census:
    """One full SCAN of the namespace (not the capped helper in refresh_state_store)."""
    census = Census()
    for raw in client.scan_iter(match=f"{namespace}{STATE_MARKER}*", count=count):
        name = _text(raw)
        path = state_path(name, namespace)
        if path is None:
            continue
        census.scanned += 1
        if is_protected_path(path):
            census.protected_seen += 1
        cls = classify_path(path)
        if cls is None:
            if name.endswith(QUOTA_DOC_SUFFIX):
                census.quota_docs_nontest += 1
            continue
        try:
            idle = client.object("idletime", raw)
        except Exception:  # LFU policy, or the key vanished between SCAN and here
            idle = None
        finding = Finding(raw=raw, name=name, path=path, cls=cls, idle=idle, pttl=int(client.pttl(raw)))
        if min_idle_seconds > 0 and (idle is None or idle < min_idle_seconds):
            census.too_recent.append(finding)
        else:
            census.candidates.append(finding)
    return census


def write_backup(client: Any, findings: Iterable[Finding], directory: Path, *, stamp: str, keep: int) -> Path:
    """DUMP every candidate to <directory>/keyvalue_janitor_<stamp>.jsonl, fsync'd, then prune old files."""
    directory.mkdir(parents=True, exist_ok=True)
    final = directory / f"{BACKUP_PREFIX}{stamp}.jsonl"
    partial = final.with_name(final.name + ".partial")
    with partial.open("w", encoding="utf-8", newline="\n") as handle:
        for item in findings:
            blob = client.dump(item.raw)
            if blob is None:  # vanished since the census: nothing to back up
                continue
            handle.write(json.dumps({"key": item.name, "pttl_ms": int(item.pttl), "dump_b64": base64.b64encode(blob).decode("ascii")}) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(partial, final)
    if keep > 0:
        for stale in sorted(directory.glob(f"{BACKUP_PREFIX}*.jsonl"))[:-keep]:
            try:
                stale.unlink()
            except OSError:
                pass
    return final


def restore_backup(client: Any, path: Path) -> int:
    """Put every key in a backup file back (REPLACE), with its remaining TTL. Returns the count."""
    restored = 0
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            ttl = int(row.get("pttl_ms") or 0)
            client.restore(row["key"], max(ttl, 0), base64.b64decode(row["dump_b64"]), replace=True)
            restored += 1
    return restored


def apply_expiry(client: Any, findings: Iterable[Finding], namespace: str, *, grace_seconds: int, delete_now: bool) -> int:
    done = 0
    for item in findings:
        # Last-chance re-check, independent of the census: never act on a key that is
        # outside the namespace, under a protected root, or no longer matches a signature.
        path = state_path(item.name, namespace)
        if path is None or is_protected_path(path) or classify_path(path) is None:
            continue
        if delete_now:
            client.unlink(item.raw)
        else:
            client.expire(item.raw, max(int(grace_seconds), 1))
        done += 1
    return done


def _resolve_url(explicit: str | None) -> str:
    for candidate in (explicit, os.environ.get("SYNDICATE_JANITOR_REDIS_URL"), os.environ.get("SYNDICATE_REFRESH_STATE_URL"), os.environ.get("REDIS_URL")):
        if candidate and str(candidate).strip():
            return str(candidate).strip()
    return DEFAULT_URL


def _describe(url: str) -> str:
    """host:port/db only -- the URL itself can carry credentials and is never printed."""
    try:
        parts = urlsplit(url)
        return f"{parts.hostname or '?'}:{parts.port or '?'}{parts.path or ''}"
    except ValueError:
        return "<unparseable url>"


def _default_client_factory(url: str) -> Any:
    from syndicate.features.shared.refresh_state_store import _refuse_loopback_redis_under_pytest

    # A test that calls main() without injecting a client must not reach the fleet either.
    _refuse_loopback_redis_under_pytest(url)
    import redis

    return redis.Redis.from_url(url, decode_responses=False, socket_timeout=15, socket_connect_timeout=5)


def _print_census(census: Census, *, namespace: str) -> None:
    by_class: dict[str, int] = {}
    for item in census.candidates:
        by_class[item.cls] = by_class.get(item.cls, 0) + 1
    print(f"namespace {namespace!r}: scanned {census.scanned} state keys; fleet/protected-root keys seen (never touched): {census.protected_seen}")
    print(f"test-origin candidates: {len(census.candidates)}  " + "  ".join(f"{k}={v}" for k, v in sorted(by_class.items())))
    if census.too_recent:
        print(f"skipped (touched too recently, so a run may be in flight): {len(census.too_recent)}")
    never = sum(1 for item in census.candidates if item.pttl == -1)
    print(f"  of the candidates, {never} never expire and {len(census.candidates) - never} carry a TTL")


def main(argv: list[str] | None = None, *, client_factory: Callable[[str], Any] | None = None, now: datetime | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    ap.add_argument("--url", help="Redis URL (default: $SYNDICATE_JANITOR_REDIS_URL, $SYNDICATE_REFRESH_STATE_URL, $REDIS_URL, then the fleet's 127.0.0.1:6379)")
    ap.add_argument("--namespace", default=None, help="state namespace (default: $SYNDICATE_REFRESH_STATE_NAMESPACE or 'syndicate')")
    ap.add_argument("--apply", action="store_true", help="act; without it this is a dry run that reports what it would do")
    ap.add_argument("--min-idle-seconds", type=int, default=3600, help="leave keys touched more recently than this alone (default 3600)")
    ap.add_argument("--grace-seconds", type=int, default=60, help="EXPIRE grace (default 60); PERSIST inside it undoes a mistake")
    ap.add_argument("--delete-now", action="store_true", help="UNLINK instead of EXPIRE with a grace period")
    ap.add_argument("--max-keys", type=int, default=2000, help="tripwire: refuse to act on more candidates than this (default 2000)")
    ap.add_argument("--backup-dir", help="write a restorable backup here before changing anything (required with --apply unless --no-backup)")
    ap.add_argument("--no-backup", action="store_true", help="allow --apply without a backup")
    ap.add_argument("--keep-backups", type=int, default=14, help="keep this many backup files (default 14)")
    ap.add_argument("--restore", metavar="FILE", help="put a backup file's keys back (needs --apply)")
    ap.add_argument("--fail-on-found", action="store_true", help="exit 1 in a dry run when candidates exist")
    ap.add_argument("--sample", type=int, default=0, metavar="N", help="print up to N example paths per class")
    args = ap.parse_args(argv)

    namespace = (args.namespace or os.environ.get("SYNDICATE_REFRESH_STATE_NAMESPACE") or "syndicate").strip() or "syndicate"
    url = _resolve_url(args.url)
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")

    try:
        client = (client_factory or _default_client_factory)(url)
        client.ping()
    except Exception as exc:  # unreachable is a skip, not a crash: the nightly hook must not fail on it
        print(f"keyvalue_janitor: Redis at {_describe(url)} unreachable ({type(exc).__name__}) -- nothing changed")
        return 2

    if args.restore:
        if not args.apply:
            print("keyvalue_janitor: --restore needs --apply (it writes keys back)")
            return 0
        print(f"keyvalue_janitor: restored {restore_backup(client, Path(args.restore))} keys from {args.restore}")
        return 0

    census = take_census(client, namespace, min_idle_seconds=int(args.min_idle_seconds))
    _print_census(census, namespace=namespace)
    if args.sample > 0:
        seen: dict[str, int] = {}
        for item in census.candidates:
            if seen.get(item.cls, 0) < args.sample:
                seen[item.cls] = seen.get(item.cls, 0) + 1
                print(f"    [{item.cls}] ...{item.path[-90:]}")
    quota_after = census.quota_docs_nontest
    print(f"quota documents that are not test fixtures: {quota_after} (the off-fleet forwarder writes only when exactly 1)")

    if not args.apply:
        print("DRY RUN -- nothing changed. Add --apply (with --backup-dir) to act.")
        print(f"JANITOR mode=dry-run scanned={census.scanned} protected_seen={census.protected_seen} candidates={len(census.candidates)} skipped_recent={len(census.too_recent)} quota_docs_after={quota_after}")
        return 1 if (args.fail_on_found and census.candidates) else 0

    if len(census.candidates) > int(args.max_keys):
        print(f"REFUSING: {len(census.candidates)} candidates exceeds --max-keys {args.max_keys}. A real mess is smaller than this; a wrong match is not. Nothing changed.")
        return 5
    if not census.candidates:
        print(f"JANITOR mode=apply scanned={census.scanned} protected_seen={census.protected_seen} candidates=0 expired=0 skipped_recent={len(census.too_recent)} remaining=0 quota_docs_after={quota_after}")
        return 0 if quota_after <= 1 else 4

    backup_path: Path | None = None
    if not args.no_backup:
        if not args.backup_dir:
            print("REFUSING: --apply needs --backup-dir (or --no-backup). Nothing changed.")
            return 3
        try:
            backup_path = write_backup(client, census.candidates, Path(args.backup_dir), stamp=stamp, keep=int(args.keep_backups))
        except Exception as exc:
            print(f"REFUSING: could not write the backup ({type(exc).__name__}: {exc}). Nothing changed.")
            return 3
        print(f"backup written: {backup_path}")

    acted = apply_expiry(client, census.candidates, namespace, grace_seconds=int(args.grace_seconds), delete_now=bool(args.delete_now))
    # Verify: any candidate that is neither gone nor scheduled to go within grace is still live.
    after = take_census(client, namespace, min_idle_seconds=0)
    horizon_ms = (int(args.grace_seconds) + 5) * 1000
    # Only the keys this run chose: ones skipped as too recent are left alone on purpose.
    chosen = {item.name for item in census.candidates}
    remaining = [item for item in after.candidates if item.name in chosen and not (0 <= item.pttl <= horizon_ms)]
    quota_after = after.quota_docs_nontest
    print(f"{'unlinked' if args.delete_now else f'set to expire in {args.grace_seconds}s'}: {acted} keys; still live afterwards: {len(remaining)}; "
          f"quota documents that are not test fixtures: {quota_after}")
    print(f"JANITOR mode=apply scanned={census.scanned} protected_seen={census.protected_seen} candidates={len(census.candidates)} expired={acted} "
          f"skipped_recent={len(census.too_recent)} remaining={len(remaining)} quota_docs_after={quota_after} backup={backup_path or 'none'}")
    if remaining:
        print(f"WARNING: {len(remaining)} candidates are still live after the run")
        return 4
    if quota_after > 1:
        print("WARNING: more than one non-test quota document remains -- the off-fleet forwarder needs exactly one")
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
