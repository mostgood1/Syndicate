"""Game-day NBA player-props pull, ahead of each cheat-sheet build (user 2026-10-19: "Pull now + fix game days").

WHY. After the first pull of a date, the NBA props refresh reuses that snapshot whenever its files exist.
`scripts/refresh_nba_oddsapi_props.py` `_existing_refresh_state` takes `input_hash` and never reads it, the defect `#345`
closed for WNBA. So nothing refetches the day's pregame props unless forced. The board drops a quote 14 h after it was
last seen (`layer2_board`, `max_quote_age_seconds` 50400), and the sheets read the board. Measured 2026-10-19 on the
10-20 board: 2,887 of 4,780 NBA candidates were beyond that age.

WHAT. On a day with NBA games still to start, make one forced NBA pregame pull through the orchestrator
(`refresh_odds_sources.py --sports nba --phase pregame --force-refresh`). It is scheduled ~20 min before the 8:30 /
12:30 / 4:30 CT sheet builds, which leaves time for the board to rebuild on the new quotes. It skips, spending nothing:
  - when no NBA game is listed for today (`game_odds_<day>.csv`, or the day's sims);
  - when every one of today's games starts within `--min-lead-minutes`;
  - when the day's snapshot is under `--min-age-minutes` old, because something else just pulled;
  - when an NBA props job is already running.
Cost is one event call per game on the slate. ~60 credits were ESTIMATED for 3 games on 10-19; it is not metered,
because the quota ledger carries no NBA line.

ENV. The pull runs with the running live-odds-worker role's env (read from /proc, never printed) -- the env that role's
own odds jobs run this command with -- and refuses when no role is running. `--env-file` supplies ODDS_API_KEY only if
the role env has none.
"""
from __future__ import annotations

import argparse
import csv
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parents[1]
CENTRAL = ZoneInfo("America/Chicago")
RUNNING_PATTERN = "[r]efresh_nba_oddsapi_props|[f]etch_basketball_oddsapi_props"


def _parse_ts(value: Any) -> datetime | None:
    try:
        ts = datetime.fromisoformat(str(value or "").strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def slate_starts(processed: Path, day: str) -> list[datetime] | None:
    """Start times of the day's NBA games from `game_odds_<day>.csv`. If that file is absent but the day's sims exist,
    returns [] (games, times unknown). Returns None when nothing says there are games."""
    path = processed / f"game_odds_{day}.csv"
    if path.exists():
        try:
            with open(path, encoding="utf-8") as fh:
                starts = [_parse_ts(r.get("commence_time")) for r in csv.DictReader(fh)]
        except OSError:
            starts = []
        starts = [s for s in starts if s]
        if starts:
            return starts
    return [] if any(processed.glob(f"smart_sim_{day}_*.json")) else None


def decide(starts: list[datetime] | None, now: datetime, snapshot_age_min: float | None, running: bool, *,
           min_lead_minutes: float = 10.0, min_age_minutes: float = 60.0) -> tuple[bool, str]:
    """(pull?, why). Pure, so the gate is testable without spending a credit."""
    if starts is None:
        return False, "no NBA games today"
    if starts:
        ahead = [s for s in starts if (s - now).total_seconds() / 60.0 >= min_lead_minutes]
        if not ahead:
            return False, f"all {len(starts)} games start within {min_lead_minutes:.0f} min or have started"
        why = f"{len(ahead)} of {len(starts)} games still to start"
    else:
        why = "games today (sims), start times unknown"
    if running:
        return False, "an NBA props job is already running"
    if snapshot_age_min is not None and snapshot_age_min < min_age_minutes:
        return False, f"snapshot is {snapshot_age_min:.0f} min old (< {min_age_minutes:.0f})"
    return True, why


def snapshot_age_minutes(processed: Path, day: str, now_epoch: float) -> float | None:
    path = processed / f"oddsapi_player_props_{day}.csv"
    try:
        return (now_epoch - path.stat().st_mtime) / 60.0
    except OSError:
        return None


def props_job_running() -> bool:
    try:
        out = subprocess.run(["pgrep", "-af", RUNNING_PATTERN], capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    return bool(out.strip())


#: The role whose odds jobs run this same orchestrator command. Its env is what `local_production.py` derived for it at
#: boot (blueprint + live import + local file + forced keys, plus the logstamp path), so a pull made with it is the
#: role's own pull. The scheduled tasks launch this script from a bare login shell, and with that env the props run
#: lacked NBA_BETTING_DATA_ROOT, the local memory limit and the log stamps (lane gameday-pull-role-env, todo #718).
ROLE = "live-odds-worker"
ROLE_SCRIPT = "run_live_odds_refresh_worker.py"


def role_env(proc_root: Path = Path("/proc"), role_script: str = ROLE_SCRIPT) -> dict[str, str] | None:
    """The running role process's env, read as a dict (never printed), or None when no such process is readable."""
    try:
        pids = sorted((p for p in proc_root.iterdir() if p.name.isdigit()), key=lambda p: int(p.name))
    except OSError:
        return None
    for pid in pids:
        try:
            argv = [a.decode("utf-8", "replace") for a in (pid / "cmdline").read_bytes().split(b"\0") if a]
            if len(argv) < 2 or "python" not in Path(argv[0]).name or not any(Path(a).name == role_script for a in argv[1:3]):
                continue
            raw = (pid / "environ").read_bytes()
        except OSError:
            continue
        env = dict(item.decode("utf-8", "replace").split("=", 1) for item in raw.split(b"\0") if b"=" in item)
        if env:
            return env
    return None


def pull_command(day: str, python: str = sys.executable) -> list[str]:
    return [python, "scripts/refresh_odds_sources.py", "--date", day, "--sports", "nba", "--phase", "pregame",
            "--force-refresh", "--json"]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data-root", default=os.environ.get("SYNDICATE_DATA_ROOT") or "")
    ap.add_argument("--date", default=None, help="the slate day (default: today in Central)")
    ap.add_argument("--env-file", default=None, help="read ODDS_API_KEY from this file only if the role env has none")
    ap.add_argument("--min-age-minutes", type=float, default=60.0)
    ap.add_argument("--min-lead-minutes", type=float, default=10.0)
    ap.add_argument("--dry-run", action="store_true", help="decide and print; no pull")
    args = ap.parse_args(argv)
    if not args.data_root:
        print("NBA_GAMEDAY_PULL REFUSING: no --data-root", flush=True)
        return 2
    now = datetime.now(timezone.utc)
    day = args.date or now.astimezone(CENTRAL).date().isoformat()
    processed = Path(args.data_root) / "nba_source" / "data" / "processed"
    age = snapshot_age_minutes(processed, day, time.time())
    pull, why = decide(slate_starts(processed, day), now, age, props_job_running(),
                       min_lead_minutes=args.min_lead_minutes, min_age_minutes=args.min_age_minutes)
    stamp = now.astimezone(CENTRAL).strftime("%Y-%m-%d %H:%M CT")
    print(f"NBA_GAMEDAY_PULL {stamp} day={day} {'PULL' if pull else 'SKIP'}: {why}", flush=True)
    if not pull or args.dry_run:
        return 0
    env = role_env()
    if env is None:
        # Never fall back to this shell's env: that is the pull this replaced.
        print(f"NBA_GAMEDAY_PULL REFUSING: no running {ROLE} role process to take the env from (fleet down?)", flush=True)
        return 2
    role_root = str(env.get("SYNDICATE_DATA_ROOT") or "").strip()
    if Path(role_root or "/nonexistent").resolve() != Path(args.data_root).resolve():
        print(f"NBA_GAMEDAY_PULL REFUSING: the {ROLE} role's SYNDICATE_DATA_ROOT is not --data-root", flush=True)
        return 2
    if not str(env.get("ODDS_API_KEY") or "").strip() and args.env_file:
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
        from fetch_alt_ladders import key_from_env_file

        key = key_from_env_file(Path(args.env_file))
        if not key:
            print("NBA_GAMEDAY_PULL REFUSING: the role has no ODDS_API_KEY and --env-file has none", flush=True)
            return 2
        env["ODDS_API_KEY"] = key
    print(f"NBA_GAMEDAY_PULL env: {ROLE} role ({len(env)} keys)", flush=True)
    started = time.monotonic()
    result = subprocess.run(pull_command(day), cwd=str(REPO_ROOT), env=env, capture_output=True, text=True, timeout=1800)
    after = snapshot_age_minutes(processed, day, time.time())
    fresh = after is not None and after < (time.monotonic() - started) / 60.0 + 1.0
    print(f"NBA_GAMEDAY_PULL day={day} exit={result.returncode} secs={time.monotonic() - started:.0f} "
          f"snapshot {'REWRITTEN' if fresh else 'NOT rewritten'}", flush=True)
    if result.returncode != 0:
        tail = (result.stderr or "")[-400:]
        print("NBA_GAMEDAY_PULL stderr tail: " + (tail.replace(env["ODDS_API_KEY"], "<key>") if env.get("ODDS_API_KEY") else tail),
              flush=True)
    return 0 if result.returncode == 0 and fresh else 1


if __name__ == "__main__":
    raise SystemExit(main())
