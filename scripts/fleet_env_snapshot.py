"""The fleet's per-role env snapshot: `<home>/fleet_env/<role>.json`, and the one-way
migration from the Render-era copy it replaced.

    python3 scripts/fleet_env_snapshot.py migrate --home ~/syndicate-prod --dry-run
    python3 scripts/fleet_env_snapshot.py migrate --home ~/syndicate-prod
    python3 scripts/fleet_env_snapshot.py check   --home ~/syndicate-prod

WHY `[2026-11-17, lane render-config-retirement, todo #766 reopened; user: "we should not
depend on render at all", then "Yes, copy now"]`. Until this lane, `local_production.py`
built every role's env from Render-shaped files: `render.yaml` (the lowest layer) and
`<home>/render_env/<role>.json`, the snapshot imported once from the Render API on
2026-10-01 (88 / 182 / 148 keys). The launcher now reads `scripts/fleet_role_spec.json`
and `<home>/fleet_env/<role>.json` instead, and never opens either Render file.

THIS TOOL IS THE ONLY CODE THAT READS `render_env/`, and only to write `fleet_env/` from it,
once, or to convert a secrets backup taken before the rename (`fleet_secrets_backup.py
restore` writes the old member names; run `migrate --home <restored dir>` on the result).

WHAT THE MIGRATION CHANGES, and nothing else:
- the directory: `render_env/` -> `fleet_env/` (files 0600, directory 0700). `render_env/`
  is left in place, untouched, as the rollback for any checkout older than this lane;
- the metadata: Render's `service_id` and `pages` are dropped; `fetched_at` is kept as
  `snapshot_taken_at`, and `migrated_from` / `migrated_at` say where the file came from;
- path values: the Render disk prefixes become placeholders the launcher expands --
  `/opt/render/project/data[/...]` -> `{data_root}[/...]` and
  `/opt/render/project/src[/...]` -> `{repo_root}[/...]` -- under EXACTLY the condition the
  launcher used to rewrite them (`== prefix` or `startswith(prefix + "/")`), keeping the rest
  of the value verbatim. So `expand(placeholder value)` is byte-identical to the old rewrite
  of the original value (`tests/test_fleet_env_snapshot.py` proves it, value by value).
Every other value is copied byte for byte. NEVER PRINTS A VALUE: key names, counts, verdicts.

Exit codes: 0 ok; 2 refused (missing input, or a fleet_env file that already exists and
DIFFERS -- never overwritten); 5 check failed.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path
from typing import Any

EXIT_OK, EXIT_REFUSED, EXIT_CHECK = 0, 2, 5

ROLES = ("web", "refresh-worker", "live-odds-worker")
SNAPSHOT_DIR_NAME = "fleet_env"
LEGACY_DIR_NAME = "render_env"  # read by THIS tool only

DATA_ROOT_TOKEN = "{data_root}"
REPO_ROOT_TOKEN = "{repo_root}"
# The Render disk prefixes, kept here and ONLY here, to convert old files.
LEGACY_PREFIXES = (
    ("/opt/render/project/data", DATA_ROOT_TOKEN),
    ("/opt/render/project/src", REPO_ROOT_TOKEN),
)


def to_placeholders(value: str) -> str:
    """A Render-era value with its disk prefix replaced by the launcher's placeholder."""
    for prefix, token in LEGACY_PREFIXES:
        if value == prefix or value.startswith(prefix + "/"):
            return token + value[len(prefix):]
    return value


def convert_legacy(payload: dict[str, Any], *, role: str, source: str, now: dt.datetime) -> dict[str, Any]:
    values = payload.get("values") if isinstance(payload, dict) else None
    if not isinstance(values, dict):
        raise ValueError(f"{source}: no `values` object")
    return {
        "role": role,
        "snapshot_taken_at": payload.get("fetched_at"),
        "migrated_from": source,
        "migrated_at": now.isoformat(),
        "values": {str(k): (None if v is None else to_placeholders(str(v))) for k, v in values.items()},
    }


def _write_private(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        os.chmod(path.parent, 0o700)
    tmp = path.with_suffix(path.suffix + ".partial")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(text)
    if os.name != "nt":
        os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def plan(home: Path, now: dt.datetime) -> list[dict[str, Any]]:
    rows = []
    for role in ROLES:
        legacy = home / LEGACY_DIR_NAME / f"{role}.json"
        target = home / SNAPSHOT_DIR_NAME / f"{role}.json"
        row: dict[str, Any] = {"role": role, "legacy": str(legacy), "target": str(target)}
        if not legacy.is_file():
            row["verdict"] = "NO LEGACY FILE"
            rows.append(row)
            continue
        converted = convert_legacy(json.loads(legacy.read_text(encoding="utf-8")), role=role,
                                   source=f"{LEGACY_DIR_NAME}/{role}.json", now=now)
        row["converted"] = converted
        row["keys"] = len(converted["values"])
        row["placeholders"] = sorted(k for k, v in converted["values"].items()
                                     if isinstance(v, str) and v.startswith((DATA_ROOT_TOKEN, REPO_ROOT_TOKEN)))
        if target.is_file():
            existing = json.loads(target.read_text(encoding="utf-8"))
            row["verdict"] = "ALREADY MIGRATED" if existing.get("values") == converted["values"] else "TARGET DIFFERS"
        else:
            row["verdict"] = "TO WRITE"
        rows.append(row)
    return rows


def cmd_migrate(home: Path, *, dry_run: bool, now: dt.datetime | None = None) -> int:
    now = now or dt.datetime.now(dt.timezone.utc)
    rows = plan(home, now)
    code = EXIT_OK
    for row in rows:
        print(f"  {row['role']:17s} {row['verdict']:17s} keys={row.get('keys', '-')} "
              f"placeholders={len(row.get('placeholders') or [])}")
        if row["verdict"] in {"NO LEGACY FILE", "TARGET DIFFERS"}:
            code = EXIT_REFUSED
    if code != EXIT_OK:
        print("REFUSED: nothing written (a fleet_env file that differs is never overwritten; "
              "a missing legacy file has nothing to migrate).")
        return code
    if dry_run:
        print("dry run: nothing written")
        return EXIT_OK
    for row in rows:
        if row["verdict"] == "TO WRITE":
            _write_private(Path(row["target"]), json.dumps(row["converted"], indent=1, sort_keys=True) + "\n")
            print(f"  wrote {row['target']}")
    return cmd_check(home)


def cmd_check(home: Path) -> int:
    """Every legacy key is present in fleet_env with exactly the converted value, and nothing else."""
    bad = 0
    for role in ROLES:
        legacy = home / LEGACY_DIR_NAME / f"{role}.json"
        target = home / SNAPSHOT_DIR_NAME / f"{role}.json"
        if not target.is_file():
            print(f"  {role:17s} MISSING {target}")
            bad += 1
            continue
        mode = oct(target.stat().st_mode & 0o777)
        new_values = json.loads(target.read_text(encoding="utf-8")).get("values") or {}
        if not legacy.is_file():
            print(f"  {role:17s} keys={len(new_values)} mode={mode} (no legacy file to compare)")
            continue
        old_values = json.loads(legacy.read_text(encoding="utf-8")).get("values") or {}
        missing = sorted(set(old_values) - set(new_values))
        extra = sorted(set(new_values) - set(old_values))
        differ = sorted(k for k in set(old_values) & set(new_values)
                        if (None if old_values[k] is None else to_placeholders(str(old_values[k]))) != new_values[k])
        ok = not (missing or extra or differ) and (os.name == "nt" or mode == "0o600")
        bad += 0 if ok else 1
        print(f"  {role:17s} {'SAME' if ok else 'DIFFERS'} keys={len(new_values)}/{len(old_values)} mode={mode}"
              f" missing={missing} extra={extra} differ={differ}")
    print("CHECK: " + ("OK" if not bad else f"FAILED ({bad})"))
    return EXIT_OK if not bad else EXIT_CHECK


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("migrate", "check"):
        p = sub.add_parser(name)
        p.add_argument("--home", default="~/syndicate-prod")
        if name == "migrate":
            p.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    home = Path(args.home).expanduser()
    if args.cmd == "migrate":
        return cmd_migrate(home, dry_run=args.dry_run)
    return cmd_check(home)


if __name__ == "__main__":
    sys.exit(main())
