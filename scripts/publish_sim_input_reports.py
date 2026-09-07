"""Produce PRODUCTION sim-input reports for the engines that have none.

WHY THIS EXISTS. `roster_objs` and the per-game feature payloads are
deliberately off `HOT_ARTIFACT_PATTERNS`, so publishing a report is the ONLY
way an engine's production input population is readable at all. Measured
2026-09-07:

    mlb      20 reports   (worker-produced, daily)
    soccer    1 report    (worker-produced, today)
    nhl / nba / wnba / nfl / ncaaf      ZERO

So every population claim about those five rests on a LOCAL MIRROR, which
CLAUDE.md says is not evidence about production. That is not a small caveat: a
local run of MLB's checklist reported 24 failures where production reported 10,
and soccer's own gate reported 2 alarms locally against 6 in production. The
mirror has been wrong in BOTH directions on the same day.

--------------------------------------------------------------------------
THE THREE ENGINES SPLIT BY WHAT THEY READ, and that decides what a cron can do
--------------------------------------------------------------------------
    basketball   reads nba_source/data/processed + wnba_source/.../processed
                 -> real DATA. A cron has its own empty disk, so it must PULL
                    first. Both paths ARE allowlisted (checked with the real
                    predicate), which is what makes this possible at all.
    nhl          reads nothing under the data root -- walks contracts
    football     reads nothing under the data root -- AST + load_features

For NHL and football the report is a CODE fact, already true of production, and
the value here is that it becomes READABLE rather than asserted. For basketball
it is a genuine population measurement, and the pull is load-bearing: without
it the checklist would audit an empty directory and report 0.0% for everything,
which looks exactly like the defect it is meant to detect. That failure mode is
why `_pull_or_refuse` exits non-zero instead of proceeding on an empty root.

MLB and soccer are deliberately NOT run here. Both need worker-disk data that
is not allowlisted (roster_objs, league history), so a cron would measure an
absence and report it as a finding. They already publish from the worker.

    py -3 scripts/publish_sim_input_reports.py
    py -3 scripts/publish_sim_input_reports.py --publish --verify
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# EXACT allowlist patterns, not a convenient `*.csv`. My first draft used
# `<dir>/*.csv` and the guard below caught it: the allowlist is per-FILENAME,
# so `*.csv` matches nothing and the pull would have returned a cheerful zero
# while the checklist audited an empty directory and reported every field at
# 0.0% -- indistinguishable from the defect it exists to find.
#
# These are copied from `HOT_ARTIFACT_PATTERNS` and each is asserted to match
# the real file below, because a pattern that is merely PLAUSIBLE is the whole
# failure mode here.
BASKETBALL_INPUTS = (
    "*_source/source_artifacts/data/processed/team_advanced_stats_*.csv",
    "*_source/data/processed/team_advanced_stats_*.csv",
    "*_source/source_artifacts/data/processed/home_court_advantage.json",
    "*_source/data/processed/home_court_advantage.json",
)

# What each pattern must actually match. Checked at run time, so a future
# rename of the artifact breaks the run loudly instead of silently pulling
# nothing.
BASKETBALL_WITNESSES = (
    "wnba_source/source_artifacts/data/processed/team_advanced_stats_2026.csv",
    "nba_source/data/processed/team_advanced_stats_2026.csv",
    "wnba_source/source_artifacts/data/processed/home_court_advantage.json",
)

# (label, script, report relative paths it publishes)
CHECKS = (
    ("basketball", "basketball_sim_input_checklist.py",
     ("wnba_source/source_artifacts/data/sim_input_report/sim_input_report_{d}.json",
      "nba_source/source_artifacts/data/sim_input_report/sim_input_report_{d}.json")),
    ("nhl", "nhl_sim_input_checklist.py",
     ("nhl_source/source_artifacts/data/sim_input_report/sim_input_report_{d}.json",)),
    ("football", "football_sim_input_checklist.py",
     ("nfl_source/source_artifacts/data/sim_input_report/sim_input_report_{d}.json",
      "ncaaf_source/source_artifacts/data/sim_input_report/sim_input_report_{d}.json")),
)


def _data_root() -> Path:
    root = str(os.environ.get("SYNDICATE_DATA_ROOT") or "").strip()
    return Path(root).expanduser().resolve() if root else (REPO_ROOT / "data")


def _base_url() -> str:
    for key in ("SYNDICATE_WEB_PUBLISH_URL", "SYNDICATE_BASE_URL", "BASE_URL"):
        v = str(os.environ.get(key) or "").strip()
        if v:
            return v.rstrip("/")
    return "https://syndicate-an21.onrender.com"


def _token() -> str:
    v = str(os.environ.get("ADMIN_TOKEN") or "").strip()
    if v:
        return v
    env = REPO_ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("ADMIN_TOKEN"):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def _pull_or_refuse(token: str) -> int:
    """Pull basketball's inputs onto this disk. REFUSES on an empty result.

    A checklist run against an empty directory reports 0.0% for every field --
    identical to the defect it exists to detect. So "pulled nothing" must be a
    hard stop, not a warning that scrolls past.
    """
    from syndicate.features.shared import artifact_publisher as ap
    # Assert the patterns match REAL filenames, not that they look allowlisted.
    # `is_hot_artifact_relative_path(pattern)` on a glob is meaningless -- it
    # was my first draft and it passed a pattern that matched nothing.
    for w in BASKETBALL_WITNESSES:
        if not ap.is_hot_artifact_relative_path(w):
            print(f"REFUSING: {w} is not allowlisted, so it cannot be pulled and "
                  f"the checklist would audit an empty directory.")
            return -1
        if not any(fnmatch.fnmatch(w, p) for p in BASKETBALL_INPUTS):
            print(f"REFUSING: no pull pattern here matches {w}. The pull would "
                  f"fetch nothing and every field would read 0.0%.")
            return -1
    # `_export_url()` builds from `SYNDICATE_WEB_PUBLISH_URL` and returns an
    # EMPTY STRING when it is unset -- which `urlopen` then raises ValueError
    # on, once per pattern, so the run reports four failures that look like
    # network trouble and are actually one missing env var. Set it from the
    # base URL this script already resolves, so a laptop run and a cron run
    # take the same path.
    if not ap._publish_url():  # noqa: SLF001
        os.environ["SYNDICATE_WEB_PUBLISH_URL"] = _base_url()
        print(f"  (set SYNDICATE_WEB_PUBLISH_URL={_base_url()} for the pull)")
    total = 0
    for pattern in BASKETBALL_INPUTS:
        try:
            url = ap._export_url(pattern)  # noqa: SLF001
            if not url:
                print(f"  REFUSING {pattern}: no export URL could be built")
                return -1
            ok, n = ap._pull_hot_artifacts_request(  # noqa: SLF001
                url, token, timeout_seconds=120)
            print(f"  pulled {pattern}  ok={ok} files={n}", flush=True)
            total += int(n or 0)
        except Exception as exc:
            # THE MESSAGE, NOT JUST THE TYPE. The first cron run printed four
            # bare `RuntimeError`s and nothing else, and the message named the
            # fix outright: "SYNDICATE_DATA_ROOT must be set when hosted storage
            # is required." `refresh_state_store.data_root()` RAISES on Render
            # (where `RENDER` is set) rather than falling back to REPO_ROOT/data
            # the way it does locally -- so the pull worked on a laptop and could
            # not work on a cron, and my own handler discarded the sentence that
            # said so. An exception type is a category; the message is the
            # finding.
            print(f"  pull FAILED {pattern}: {type(exc).__name__}: {exc}", flush=True)
    return total


def _publish(rel: str, token: str) -> bool | None:
    from syndicate.features.shared import artifact_publisher as ap
    src = _data_root() / rel
    if not src.is_file():
        return None
    return ap._publish_streamed(  # noqa: SLF001
        src, relative_path=rel, url=_base_url() + "/api/ops/artifacts/publish",
        token=token, timeout_seconds=180,
        # Name the TOOL when there is no service lane -- this script
        # runs wherever an operator runs it, so every artifact it published
        # reached the receiver as `publisher=unknown` (measured 2026-09-07).
        publisher=ap.publisher_identity_for_tool("publish_sim_input_reports"))


def _read_back(rel: str, token: str) -> dict | None:
    url = (_base_url() + "/api/ops/artifacts/export?"
           + urllib.parse.urlencode({"pattern": rel, "limit": "2"}))
    for _ in range(5):
        try:
            req = urllib.request.Request(
                url, headers={"X-Admin-Token": token, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=150) as r:
                d = json.load(r)
            for _n, raw in (d.get("artifacts") or {}).items():
                return json.loads(raw) if isinstance(raw, str) else raw
            return None
        except Exception:
            time.sleep(15)
    return None


def main() -> int:
    ap_ = argparse.ArgumentParser(description=__doc__)
    ap_.add_argument("--publish", action="store_true")
    ap_.add_argument("--verify", action="store_true")
    args = ap_.parse_args()

    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    token = _token()
    print(f"data root   {_data_root()}")
    print(f"base url    {_base_url()}")
    print(f"date        {day}")
    print("NOT RUN here: mlb, soccer -- both need worker-disk data that is not "
          "allowlisted, so a cron would measure an absence and report it as a "
          "finding. They already publish from the worker.\n")

    if not token:
        print("REFUSING: no ADMIN_TOKEN. The pull would fetch nothing and the "
              "checklists would report 0.0% for everything -- a false finding "
              "that looks exactly like a real one.")
        return 2

    print("=== pulling basketball inputs ===")
    pulled = _pull_or_refuse(token)
    if pulled < 0:
        return 3
    if pulled == 0:
        print("\nREFUSING: pulled 0 files. Running the basketball checklist now "
              "would audit an empty directory and report every field at 0.0%, "
              "which is indistinguishable from the defect it detects.")
        return 4
    print(f"  total files pulled: {pulled}\n")

    rc_overall = 0
    published: list[str] = []
    for label, script, rels in CHECKS:
        print(f"=== {label} ===", flush=True)
        proc = subprocess.run(
            [sys.executable, f"scripts/{script}"] + (["--publish"] if args.publish else []),
            cwd=REPO_ROOT, capture_output=True, text=True)
        for line in (proc.stdout or "").strip().splitlines()[-6:]:
            print("   " + line[:220])
        print(f"   -> rc={proc.returncode}")
        # A non-zero rc is the checklist DOING ITS JOB (alarms present); it is
        # not a failure of this wrapper. Only a missing report is.
        for rel_t in rels:
            rel = rel_t.format(d=day)
            if not (_data_root() / rel).is_file():
                print(f"   MISSING report: {rel}")
                rc_overall = 5
                continue
            if args.publish:
                ok = _publish(rel, token)
                print(f"   publish {rel.split('/')[0]:16s} -> {ok}")
                if ok:
                    published.append(rel)
        print("")

    if args.publish and args.verify:
        print("=== READ-BACK FROM PRODUCTION ===")
        for rel in published:
            doc = _read_back(rel, token)
            got = (doc or {}).get("resolved_root")
            n = len((doc or {}).get("failures") or (doc or {}).get("alarms") or [])
            state = "OK" if doc else "MISSING"
            print(f"  {state:8s} {rel.split('/')[0]:16s} resolved_root={got} alarms={n}")
            if not doc:
                rc_overall = 6
        print("\nA report that reads back with `resolved_root` under the mounted "
              "root is a PRODUCTION reading. `host` alone is not -- it only means "
              "SYNDICATE_DATA_ROOT was set, and a laptop with that set stamps "
              "itself `worker`.")
    return rc_overall


if __name__ == "__main__":
    raise SystemExit(main())
