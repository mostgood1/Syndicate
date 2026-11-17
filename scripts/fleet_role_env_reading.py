"""Before/after reading of each fleet role's environment across a drained `down`/`up`.

    python3 scripts/fleet_role_env_reading.py snapshot --out ~/syndicate-prod/run/env_before.json   # BEFORE `down`
    python3 scripts/fleet_role_env_reading.py compare  --before ~/syndicate-prod/run/env_before.json  # AFTER `up`

WHY `[2026-11-17, lane render-config-retirement, step 3]`. Env is built only at `up`, so a
launcher change lands silently at the next drained `down`/`up`. Whoever runs it owes ONE
reading: did any role's env change in a way nobody intended? `snapshot` records, per role,
the sha256 of every value in `/proc/<pid>/environ` -- NEVER a value -- into a mode-600 file.
`compare` reads the roles again and names the keys that were removed, added or changed.

EXPECTED changes, which `compare` labels and does not fail on:
- every key that `--expect-removed` / `--expect-added` / `--expect-changed` names (repeatable);
- by default (`--render-markers-step3`, on unless `--no-render-markers-step3`):
  - RENDER, RENDER_SERVICE_NAME, RENDER_SERVICE_ID, RENDER_INSTANCE_ID, RENDER_GIT_COMMIT and
    RENDER_EXTERNAL_URL removed;
  - their SYNDICATE_* twins added;
  - and, for the three that do not move with a restart (SYNDICATE_HOSTED,
    SYNDICATE_SERVICE_NAME / _ID), the new value's hash equal to the old RENDER twin's.
  - The instance id and the commit change on every `up` by design.

Exit codes: 0 = only expected changes; 3 = an unexpected key change (the names are printed);
2 = refused (no supervisor pidfile, unreadable /proc, missing or foreign snapshot).
Read-only: it signals nothing, and prints key names and counts only.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import sys
from pathlib import Path

EXIT_OK, EXIT_REFUSED, EXIT_UNEXPECTED = 0, 2, 3
ROLES = ("web", "refresh-worker", "live-odds-worker")

# neutral -> Render-era (the same table as syndicate/features/shared/service_identity.py,
# pinned by tests/test_fleet_role_env_reading.py; spelled out so this runs with no imports).
MARKERS = {
    "SYNDICATE_HOSTED": "RENDER",
    "SYNDICATE_SERVICE_NAME": "RENDER_SERVICE_NAME",
    "SYNDICATE_SERVICE_ID": "RENDER_SERVICE_ID",
    "SYNDICATE_INSTANCE_ID": "RENDER_INSTANCE_ID",
    "SYNDICATE_GIT_COMMIT": "RENDER_GIT_COMMIT",
    "SYNDICATE_EXTERNAL_URL": "RENDER_EXTERNAL_URL",
}
# Twins whose value must carry over unchanged across an `up`.
STABLE_TWINS = ("SYNDICATE_HOSTED", "SYNDICATE_SERVICE_NAME", "SYNDICATE_SERVICE_ID")
# Keys that change on EVERY `up`, whatever the launcher does.
ALWAYS_CHANGES = {"RENDER_INSTANCE_ID", "SYNDICATE_INSTANCE_ID", "RENDER_GIT_COMMIT", "SYNDICATE_GIT_COMMIT"}


def _hash(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def read_role_hashes(home: Path, proc_root: Path) -> dict:
    pidfile = home / "run" / "supervisor.json"
    if not pidfile.is_file():
        raise SystemExit(f"REFUSED: no {pidfile} -- is the fleet up?")
    info = json.loads(pidfile.read_text(encoding="utf-8"))
    roles = {}
    for role, pid in (info.get("roles") or {}).items():
        if role not in ROLES:
            continue
        try:
            blob = (proc_root / str(int(pid)) / "environ").read_bytes()
        except (OSError, ValueError, TypeError) as exc:
            raise SystemExit(f"REFUSED: cannot read {role} pid {pid} environ: {type(exc).__name__}")
        keys = {}
        for item in blob.split(b"\0"):
            key, sep, value = item.partition(b"=")
            if sep:
                keys[key.decode("utf-8", "replace")] = _hash(value)
        roles[role] = {"pid": int(pid), "keys": keys}
    return {"supervisor_pid": info.get("supervisor_pid"), "roles": roles}


def cmd_snapshot(home: Path, out: Path, proc_root: Path) -> int:
    doc = read_role_hashes(home, proc_root)
    doc["taken_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    out.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(out), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(doc, handle, sort_keys=True)
    for role, row in doc["roles"].items():
        print(f"  {role:17s} pid={row['pid']} keys={len(row['keys'])}")
    print(f"snapshot: {out} (hashes only, mode 600)")
    return EXIT_OK


def classify(before: dict, after: dict, *, step3: bool, removed_ok: set, added_ok: set, changed_ok: set) -> dict:
    out = {}
    for role in ROLES:
        if role not in before or role not in after:
            out[role] = {"missing": True}
            continue
        b, a = before[role]["keys"], after[role]["keys"]
        removed, added = sorted(set(b) - set(a)), sorted(set(a) - set(b))
        changed = sorted(k for k in set(a) & set(b) if a[k] != b[k])
        ok_removed = set(removed_ok) | (set(MARKERS.values()) if step3 else set())
        ok_added = set(added_ok) | (set(MARKERS) if step3 else set())
        ok_changed = set(changed_ok) | ALWAYS_CHANGES
        unexpected = [f"-{k}" for k in removed if k not in ok_removed]
        unexpected += [f"+{k}" for k in added if k not in ok_added]
        unexpected += [f"~{k}" for k in changed if k not in ok_changed]
        if step3:
            for neutral in STABLE_TWINS:
                legacy = MARKERS[neutral]
                if legacy in b and neutral in a and a[neutral] != b[legacy]:
                    unexpected.append(f"!{neutral} (value differs from the old {legacy})")
                if legacy in b and neutral not in a and legacy not in a:
                    unexpected.append(f"!{neutral} (LOST: neither {neutral} nor {legacy} is set any more)")
        out[role] = {"removed": removed, "added": added, "changed": changed, "unexpected": unexpected,
                     "pid_before": before[role]["pid"], "pid_after": after[role]["pid"]}
    return out


def cmd_compare(home: Path, before_path: Path, proc_root: Path, *, step3: bool, removed_ok, added_ok, changed_ok) -> int:
    if not before_path.is_file():
        print(f"REFUSED: no snapshot {before_path}")
        return EXIT_REFUSED
    before = json.loads(before_path.read_text(encoding="utf-8"))
    after = read_role_hashes(home, proc_root)
    if after.get("supervisor_pid") == before.get("supervisor_pid"):
        print(f"NOTE: same supervisor pid {after.get('supervisor_pid')} as the snapshot -- no full `up` happened in between")
    result = classify(before["roles"], after["roles"], step3=step3, removed_ok=set(removed_ok),
                      added_ok=set(added_ok), changed_ok=set(changed_ok))
    bad = 0
    for role, row in result.items():
        if row.get("missing"):
            print(f"  {role:17s} MISSING from one side")
            bad += 1
            continue
        verdict = "UNEXPECTED" if row["unexpected"] else "expected only"
        bad += bool(row["unexpected"])
        print(f"  {role:17s} pid {row['pid_before']} -> {row['pid_after']}: {verdict}; removed={row['removed']} "
              f"added={row['added']} changed={row['changed']}" + (f" UNEXPECTED={row['unexpected']}" if row["unexpected"] else ""))
    print("COMPARE: " + ("OK -- only expected changes" if not bad else f"{bad} role(s) changed unexpectedly"))
    return EXIT_OK if not bad else EXIT_UNEXPECTED


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--home", default="~/syndicate-prod")
    parser.add_argument("--proc-root", default="/proc")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("snapshot")
    p.add_argument("--out", required=True)
    p = sub.add_parser("compare")
    p.add_argument("--before", required=True)
    p.add_argument("--no-render-markers-step3", action="store_true")
    p.add_argument("--expect-removed", action="append", default=[])
    p.add_argument("--expect-added", action="append", default=[])
    p.add_argument("--expect-changed", action="append", default=[])
    args = parser.parse_args(argv)
    home, proc_root = Path(args.home).expanduser(), Path(args.proc_root)
    try:
        if args.cmd == "snapshot":
            return cmd_snapshot(home, Path(args.out).expanduser(), proc_root)
        return cmd_compare(home, Path(args.before).expanduser(), proc_root, step3=not args.no_render_markers_step3,
                           removed_ok=args.expect_removed, added_ok=args.expect_added, changed_ok=args.expect_changed)
    except SystemExit as exc:
        print(exc)
        return EXIT_REFUSED


if __name__ == "__main__":
    sys.exit(main())
