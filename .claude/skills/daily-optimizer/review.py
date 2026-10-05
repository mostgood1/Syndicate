"""Read back the daily optimizer's published report and say what it measured and what it would change.

Stdlib only, no repo imports -- it runs from a bare checkout. A READER: it computes nothing the cron
did not already publish (the `daily-accuracy` skill's rule: never a second grader).

    py -3 .claude/skills/daily-optimizer/review.py            # fleet default, token from WSL
    py -3 .claude/skills/daily-optimizer/review.py --json

Exit codes: 0 fresh · 2 stale (generated_at older than --max-age-hours) · 4 unreadable · 5 no token.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPORT_PATH = "reports/model_scorecard/model_scorecard_optimizer.json"
FLEET_URL = "http://127.0.0.1:10000"
LAST_SEEN = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "syndicate" / "daily_optimizer_last_overlay.json"


def token() -> str:
    value = str(os.environ.get("ADMIN_TOKEN") or "").strip()
    if value:
        return value
    # The fleet's token lives in WSL, not in the repo .env (that one is Render's) -- scripts/_base_url.py.
    try:
        out = subprocess.run(["wsl.exe", "-e", "bash", "-lc",
                              "grep ^ADMIN_TOKEN= ~/syndicate-prod/local_production.env | head -1 | cut -d= -f2-"],
                             capture_output=True, text=True, timeout=60).stdout
    except (OSError, subprocess.SubprocessError):
        return ""
    return out.strip().strip('"').strip("'")


def fetch(base: str, tok: str) -> Any:
    url = f"{base.rstrip('/')}/api/ops/artifacts/stream?path={urllib.parse.quote(REPORT_PATH, safe='')}"
    request = urllib.request.Request(url, headers={"X-Admin-Token": tok})
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.loads(response.read().decode("utf-8"))


def overlay_changes(previous: Any, current: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for kind in ("edge_shrink", "stake_scale"):
        before = (previous or {}).get(kind) or {}
        after = current.get(kind) or {}
        for cell in sorted(set(before) | set(after)):
            old, new = (before.get(cell) or {}).get("factor"), (after.get(cell) or {}).get("factor")
            if old != new:
                lines.append(f"{kind} {cell}: {old} -> {new}")
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default=os.environ.get("SYNDICATE_BASE_URL") or FLEET_URL)
    parser.add_argument("--max-age-hours", type=float, default=30.0)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--no-remember", action="store_true", help="do not update the last-seen overlay copy")
    args = parser.parse_args(argv)

    tok = token()
    if not tok:
        print("NO TOKEN: set ADMIN_TOKEN or make ~/syndicate-prod/local_production.env readable in WSL.")
        return 5
    try:
        report = fetch(args.base_url, tok)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        print(f"UNREADABLE {REPORT_PATH} from {args.base_url}: {type(exc).__name__}: {exc}")
        return 4
    generated = datetime.fromisoformat(str(report.get("generated_at")).replace("Z", "+00:00"))
    age_h = (datetime.now(timezone.utc) - generated).total_seconds() / 3600.0
    stale = age_h > args.max_age_hours

    try:
        previous = json.loads(LAST_SEEN.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        previous = None
    overlay = report.get("overlay") or {}
    changes = overlay_changes(previous, overlay)
    if not args.no_remember and not stale:
        LAST_SEEN.parent.mkdir(parents=True, exist_ok=True)
        LAST_SEEN.write_text(json.dumps(overlay, indent=1, sort_keys=True), encoding="utf-8")

    if args.json:
        print(json.dumps({"generated_at": report.get("generated_at"), "age_hours": round(age_h, 1), "stale": stale,
                          "window": report.get("window"), "by_sport": report.get("by_sport"),
                          "edge_shrink": overlay.get("edge_shrink"), "stake_scale": overlay.get("stake_scale"),
                          "overlay_changes": changes, "resets": report.get("resets")}, indent=1, sort_keys=True))
    else:
        print(f"generated_at {report.get('generated_at')} ({age_h:.1f} h old){'  ** STALE **' if stale else ''}")
        print(report.get("markdown") or "(no markdown in report)")
        print("Overlay changes since last review:" if changes else
              "Overlay changes since last review: none" + ("" if previous is not None else " (no previous copy)"))
        for line in changes:
            print("  " + line)
    return 2 if stale else 0


if __name__ == "__main__":
    sys.exit(main())
