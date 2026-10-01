"""Sweep every parameter-free GET route on the local production fleet.

Ported from the out-of-repo `C:\\SyndicateProd\\audit_sweep.py` (2026-10-01),
which found the unscoped `/api/ops/intelligence/candidate-trace` running 87.98s
until gunicorn killed its worker, and the `/nba/api/live-player-props-audit`
502. Same rules as the original:

  * routes come from `<home>/audit_routes.json` (regenerate it with
    `scripts/local_audit_routes.py`); only rules without URL arguments are hit;
  * anything matching `SKIP` (export/trigger/run/refresh/... and /static) is
    recorded as skipped and never requested, because a GET there can mutate;
  * every request carries `X-Admin-Token` from `<home>/local_production.env`;
  * a body containing a traceback/template-error marker, or one that is just
    `{}`/`[]`/`null`, is flagged;
  * the supervisor pid is read before and after, so a fleet restart during the
    sweep is reported instead of silently mixing two fleets' answers.

Added: the previous results are kept as `audit_sweep.prev.json`, and a
comparison is printed -- status counts, p50/p99/max, failures, and every route
whose status changed.

    python scripts/local_audit_sweep.py                       # http://127.0.0.1:10000
    python scripts/local_audit_sweep.py --base-url http://127.0.0.1:5000
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import shutil
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASE_URL = "http://127.0.0.1:10000"
SKIP = re.compile(r"export|trigger|/run|launch|refresh|rebuild|backfill|reset|clear|purge|logout|delete|restart|kill|/static", re.I)
ERR = re.compile(r"Traceback|Internal Server Error|jinja2\.exceptions|UndefinedError|KeyError|TypeError: |AttributeError", re.I)

# (status, body, error) for one GET; error is "" on any HTTP answer.
Fetch = Callable[[str], tuple[int | None, bytes, str]]


def read_admin_token(env_file: Path) -> str:
    if not env_file.exists():
        return ""
    for line in env_file.read_text(encoding="utf-8").splitlines():
        if line.startswith("ADMIN_TOKEN="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def http_fetcher(base_url: str, token: str, *, timeout: float = 90.0) -> Fetch:
    def fetch(rule: str) -> tuple[int | None, bytes, str]:
        request = urllib.request.Request(base_url + rule, headers={"X-Admin-Token": token, "User-Agent": "syndicate-audit"})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.status, response.read(), ""
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read() or b"", ""
        except Exception as exc:  # noqa: BLE001 -- a timeout or reset is a finding, not a crash
            return None, b"", f"{type(exc).__name__}: {exc}"

    return fetch


def sweep(routes: Iterable[dict[str, Any]], fetch: Fetch, *, echo: Callable[[str], None] = print) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for route in routes:
        if route.get("args"):
            continue
        rule = route["rule"]
        if SKIP.search(rule):
            results.append({"rule": rule, "skipped": True})
            continue
        started = time.time()
        status, body, error = fetch(rule)
        seconds = round(time.time() - started, 2)
        text = body[:400000].decode("utf-8", "replace")
        marker = ERR.search(text)
        results.append({
            "rule": rule, "status": status, "secs": seconds, "bytes": len(body), "error": error,
            "err_marker": marker.group(0) if marker else "",
            "json_empty": text.strip() in ("{}", "[]", "null"),
        })
        echo(f"{status} {seconds:6.2f}s {len(body):9d} {rule} {error} {marker.group(0) if marker else ''}")
    return results


def is_failure(result: dict[str, Any]) -> bool:
    return bool(result.get("error") or (result.get("status") or 0) >= 500 or result.get("err_marker"))


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    hit = [r for r in results if not r.get("skipped")]
    secs = sorted(r["secs"] for r in hit) or [0.0]
    return {
        "hit": len(hit),
        "skipped": len(results) - len(hit),
        "p50": round(statistics.median(secs), 2),
        "p99": secs[max(0, int(0.99 * len(secs)) - 1)],
        "max": secs[-1],
        "failures": sorted(r["rule"] for r in hit if is_failure(r)),
        "json_empty": sorted(r["rule"] for r in hit if r.get("json_empty")),
        "status": dict(sorted(collections.Counter(str(r.get("status")) for r in hit).items())),
        "slowest": [(r["rule"], r["secs"]) for r in sorted(hit, key=lambda r: -r["secs"])[:5]],
    }


def compare(previous: list[dict[str, Any]], current: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Routes whose status (or error/no-error) changed between two runs."""
    before = {r["rule"]: r for r in previous if not r.get("skipped")}
    changes = []
    for result in current:
        old = before.get(result["rule"])
        if result.get("skipped") or old is None:
            continue
        if old.get("status") != result.get("status") or bool(old.get("error")) != bool(result.get("error")):
            changes.append({
                "rule": result["rule"],
                "before": {"status": old.get("status"), "secs": old.get("secs"), "error": old.get("error", "")[:80]},
                "after": {"status": result.get("status"), "secs": result.get("secs"), "error": result.get("error", "")[:80]},
            })
    return changes


def supervisor_pid() -> str | None:
    try:
        out = subprocess.run(["pgrep", "-f", "local_production.py --home"], capture_output=True, text=True, timeout=10).stdout.split()
    except Exception:  # noqa: BLE001 -- no pgrep (native Windows): report unknown
        return None
    return out[0] if out else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--home", help="local-production home (default: local_production.default_home())")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--timeout", type=float, default=90.0, help="per-request seconds (default 90)")
    parser.add_argument("--quiet", action="store_true", help="no per-route lines")
    args = parser.parse_args(argv)

    if args.home:
        home = Path(args.home).expanduser()
    else:
        sys.path.insert(0, str(REPO_ROOT))
        from scripts.local_production import default_home

        home = default_home()
    routes = json.loads((home / "audit_routes.json").read_text(encoding="utf-8"))
    token = read_admin_token(home / "local_production.env")
    out_path = home / "audit_sweep.json"
    prev_path = home / "audit_sweep.prev.json"

    pid_before = supervisor_pid()
    results = sweep(routes, http_fetcher(args.base_url.rstrip("/"), token, timeout=args.timeout), echo=(lambda _l: None) if args.quiet else print)
    pid_after = supervisor_pid()

    previous = json.loads(out_path.read_text(encoding="utf-8")).get("results", []) if out_path.exists() else []
    if out_path.exists():
        shutil.copy2(out_path, prev_path)
    out_path.write_text(json.dumps({"pid_before": pid_before, "pid_after": pid_after, "results": results}, indent=1), encoding="utf-8")

    report = {
        "supervisor": "RESTARTED MID-SWEEP" if pid_before != pid_after else "stable",
        "now": summarize(results),
        "previous": summarize(previous) if previous else None,
        "changed": compare(previous, results) if previous else [],
        "written": str(out_path),
    }
    print(json.dumps(report, indent=1), flush=True)
    return 1 if report["now"]["failures"] or pid_before != pid_after else 0


if __name__ == "__main__":
    raise SystemExit(main())
