from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

_SUBJOB_TIMEOUT_SECONDS = 120


def _run_script(script_name: str) -> None:
    try:
        subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / script_name), "--run-once"],
            check=False,
            timeout=_SUBJOB_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        print(f"{script_name} TIMED OUT AFTER {_SUBJOB_TIMEOUT_SECONDS} SECONDS")


def run_live_odds_refresh_job() -> None:
    print("RUNNING LIVE ODDS REFRESH")
    try:
        _run_script("run_live_odds_refresh_worker.py")
    except Exception as exc:
        print(f"LIVE ODDS REFRESH ERROR: {exc}")


def run_refresh_job() -> None:
    print("RUNNING REFRESH")
    try:
        _run_script("run_refresh_worker.py")
    except Exception as exc:
        print(f"REFRESH ERROR: {exc}")


def run_mlb_live_lens_job() -> None:
    print("RUNNING MLB")
    try:
        _run_script("run_mlb_live_lens_worker.py")
    except Exception as exc:
        print(f"MLB ERROR: {exc}")


def run_nba_live_lens_job() -> None:
    print("RUNNING NBA")
    try:
        _run_script("run_nba_live_lens_worker.py")
    except Exception as exc:
        print(f"NBA ERROR: {exc}")


def run_wnba_live_lens_job() -> None:
    print("RUNNING WNBA")
    try:
        _run_script("run_wnba_live_lens_worker.py")
    except Exception as exc:
        print(f"WNBA ERROR: {exc}")


def run_intelligence_state_job() -> None:
    print("RUNNING INTELLIGENCE")
    try:
        _run_script("run_intelligence_state_worker.py")
    except Exception as exc:
        print(f"INTELLIGENCE ERROR: {exc}")


def main() -> int:
    while True:
        run_live_odds_refresh_job()
        time.sleep(5)
        run_refresh_job()
        time.sleep(5)
        run_mlb_live_lens_job()
        time.sleep(5)
        run_nba_live_lens_job()
        time.sleep(5)
        run_wnba_live_lens_job()
        time.sleep(5)
        run_intelligence_state_job()
        time.sleep(20)


if __name__ == "__main__":
    raise SystemExit(main())