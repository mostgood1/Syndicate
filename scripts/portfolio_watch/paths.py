r"""Where Portfolio Watch reads and writes (lane portfolio-monitor). One place, so the builders and the runner agree.

ROOT is durable (not C:\tmp, which a cleanup wiped once): the probe's reading log, the daily rollup, the page data.
The finished page is published to three places:
  ROOT\page\dashboard.html            the builder's own copy
  C:\tmp\pfmon\page\dashboard.html   the path the local dashboards hub frames (kept unchanged on request)
  <fleet data root>/reports/portfolio_watch/index.html   read by the fleet web app's /ops/dashboards route
                                        (lane ops-dashboards-hub; same pattern as reports/rail_watch/)
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(os.environ.get("PORTFOLIO_WATCH_ROOT", r"C:\SyndicateProd\portfolio_watch"))
READINGS = ROOT / "readings"            # probe --out-dir: readings.jsonl (never pruned) + one folder per reading
HISTORY = ROOT / "history"              # daily_rollup.json (never pruned)
PAGE = ROOT / "page"                    # readings.json, performance.json, findings.json, dashboard.html
REGISTRY = ROOT / "findings_registry.json"
LOG = ROOT / "run.log"

LOCAL_PAGE_COPY = Path(os.environ.get("PORTFOLIO_WATCH_LOCAL_COPY", r"C:\tmp\pfmon\page\dashboard.html"))
FLEET_PAGE = Path(os.environ.get(
    "PORTFOLIO_WATCH_FLEET_PAGE",
    # Forward slashes on purpose: a shell heredoc ate one of the two leading backslashes on 11-20 and the "fleet copy"
    # went to C:\wsl.localhost\... instead. //server/share is the same UNC path to pathlib and survives any quoting.
    "//wsl.localhost/Ubuntu-24.04/home/amyn/syndicate-prod/data/reports/portfolio_watch/index.html"))

REPO_SCRIPTS = Path(os.environ.get("PORTFOLIO_WATCH_REPO_SCRIPTS", r"C:\Users\tempadmin\Coding\Syndicate\scripts"))
PROBE = REPO_SCRIPTS / "portfolio_monitor_probe.py"
S8_HEARTBEAT = Path(r"C:\tmp\pfmon\s8\heartbeat.json")
KEEP_READING_DIRS_H = 48
