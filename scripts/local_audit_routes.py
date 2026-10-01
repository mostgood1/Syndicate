"""Regenerate the local-production audit sweep's route list from the app.

The sweep (`audit_sweep.py`, run in WSL against the local fleet) GETs every
parameter-free route listed in `<home>/audit_routes.json`. That list was a
one-off dump, so it went stale the moment routes changed: on 2026-10-01 it
still held the six MLB betting-card stub URLs deleted in `d5aeeca4`, and the
sweep reported them as six 404s.

This rebuilds the list from `app.url_map` -- every rule that accepts GET, as
`{"rule", "endpoint", "args"}`, the shape the sweep reads -- and prints what
changed. It writes nothing unless `--write` is passed, and then keeps the old
file as `audit_routes.json.<UTC timestamp>.bak`.

    python scripts/local_audit_routes.py                      # dry run: diff only
    python scripts/local_audit_routes.py --write              # replace, with backup
    python scripts/local_audit_routes.py --env-from-gunicorn  # build under web's env

`--env-from-gunicorn` (Linux/WSL) copies the environment of the running web
gunicorn process before importing the app, so the route table is built the
way web builds it. Without it the current environment is used.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]
ROUTES_FILE = "audit_routes.json"


def build_route_list(rules: Iterable[Any]) -> list[dict[str, Any]]:
    """GET rules in url_map order, in the shape `audit_sweep.py` reads."""
    return [
        {"rule": rule.rule, "endpoint": rule.endpoint, "args": sorted(rule.arguments)}
        for rule in rules
        if "GET" in (rule.methods or set())
    ]


def diff_route_lists(old: list[dict[str, Any]], new: list[dict[str, Any]]) -> dict[str, Any]:
    old_keys = {(item["rule"], item["endpoint"]) for item in old}
    new_keys = {(item["rule"], item["endpoint"]) for item in new}
    return {
        "old_count": len(old),
        "new_count": len(new),
        "old_param_free": sum(1 for item in old if not item.get("args")),
        "new_param_free": sum(1 for item in new if not item.get("args")),
        "removed": sorted(old_keys - new_keys),
        "added": sorted(new_keys - old_keys),
    }


def write_route_list(path: Path, routes: list[dict[str, Any]], *, now: datetime | None = None) -> Path | None:
    """Replace `path`, keeping the previous file as a timestamped backup."""
    backup = None
    if path.exists():
        stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
        backup = path.with_name(f"{path.name}.{stamp}.bak")
        shutil.copy2(path, backup)
    tmp = path.with_name(f"{path.name}.tmp")
    tmp.write_text(json.dumps(routes, indent=1), encoding="utf-8")
    os.replace(tmp, path)
    return backup


def _gunicorn_environ() -> dict[str, str]:
    """Environment of the running web gunicorn (Linux/WSL /proc only)."""
    proc = Path("/proc")
    for pid_dir in sorted(proc.iterdir(), key=lambda p: p.name) if proc.is_dir() else []:
        if not pid_dir.name.isdigit():
            continue
        try:
            cmdline = (pid_dir / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
            if "gunicorn" not in cmdline or "wsgi:application" not in cmdline:
                continue
            raw = (pid_dir / "environ").read_bytes()
        except OSError:
            continue
        env: dict[str, str] = {}
        for item in raw.split(b"\0"):
            if b"=" in item:
                key, value = item.split(b"=", 1)
                env[key.decode(errors="replace")] = value.decode(errors="replace")
        if env:
            return env
    raise SystemExit("--env-from-gunicorn: no readable web gunicorn process found")


def _default_home() -> Path:
    sys.path.insert(0, str(REPO_ROOT))
    from scripts.local_production import default_home

    return default_home()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--home", help="local-production home (default: local_production.default_home())")
    parser.add_argument("--write", action="store_true", help="replace the route list (old one kept as a .bak)")
    parser.add_argument("--env-from-gunicorn", action="store_true", help="build under the running web process's environment")
    args = parser.parse_args(argv)

    home = Path(args.home).expanduser() if args.home else _default_home()
    path = home / ROUTES_FILE
    if args.env_from_gunicorn:
        os.environ.update(_gunicorn_environ())

    sys.path.insert(0, str(REPO_ROOT))
    from syndicate.app import create_app

    routes = build_route_list(create_app().url_map.iter_rules())
    old = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    report = diff_route_lists(old, routes)
    print(json.dumps({"path": str(path), **report}, indent=1, default=list), flush=True)
    if args.write:
        backup = write_route_list(path, routes)
        print(f"WROTE {path} ({len(routes)} routes); backup {backup}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
