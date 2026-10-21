"""Which basketball SmartSim builds ran after their game's tip? Read-only, from the props refresh logs.

Lane freeze-nba-pregame-sims (2026-10-21). For every build in
``<data_root>/<league>_source/logs/syndicate_refresh_oddsapi_props_*.log``, prints:
- when it ran, against the game's tip;
- what triggered it: the reuse line printed for that file (exclusions / pool / calibration), or none, which means a
  missing file, overwrite or the targeted trigger;
- with ``--replay-freeze``, what ``smart_sim_tip_freeze.keep_existing`` decides at the batch's decision time and
  queue position (the switch forced on, the existing sim assumed to have players).

Timestamps: every log timestamp is UTC, both ``[YYYY-MM-DDTHH:MM:SS]`` (the refresh wrapper) and
``YYYY-MM-DDTHH:MM:SS.fffZ`` (child stdout). A build is located by its
``smart_sim_worker_run_local:before_simulation`` line, which has no timestamp, so it is bounded by the last timestamp
before it (``lo``) and the first after it (``hi``):
- ``after_tip`` means lo >= tip;
- ``before_tip`` means hi <= tip;
- anything between is ``straddles_tip``.
The decision time of a batch is the last timestamp before its ``prepared_jobs`` line.

Tip sources: the same ones the freeze uses (``smart_sim_tip_freeze.tip_time``). They are the predictions row,
``game_odds_<D>.csv`` and ``schedule_*.csv``, all read as they are NOW. The first two are written once, about a day
before the slate (measured 10-20: 10-19 1:01 AM CT, never rewritten), so they match what the run saw.

    python scripts/basketball_posttip_rebuilds.py --data-root /home/amyn/syndicate-prod/data [--since 2026-10-21]
        [--replay-freeze] [--json out.json]
"""

from __future__ import annotations

import argparse
import contextlib
import glob
import io
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

TS_BRACKET = re.compile(r"^\[(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})\]")
TS_Z = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.\d+)?Z")
REUSE = re.compile(r"\[smart_sim_reuse\] (SMART_SIM_REUSE_\w+) league=(\w+) date=(\S+) file=(\S+)(.*)$")
CAL_STALE = re.compile(r"NBA_SIM_STALE path=(\S+) have=(.*) want=(.*) -> re-simulate")
FREEZE = re.compile(r"SMART_SIM_TIP_FREEZE league=(\w+) date=(\S+) file=(\S+) mode=(\w+)(.*)$")


def _ts(line: str) -> datetime | None:
    m = TS_BRACKET.match(line) or TS_Z.match(line)
    return datetime.strptime(m.group(1), "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc) if m else None


class _Tips:
    """Tip per (date, home, away) through smart_sim_tip_freeze.tip_time, on the processed root's files."""

    def __init__(self, processed: Path):
        import pandas as pd

        from syndicate.features.shared import smart_sim_tip_freeze as tf
        from syndicate.features.shared.basketball_props_smart_sim import _to_tricode_local

        self.tf, self.pd, self.to_tri, self.processed = tf, pd, _to_tricode_local, processed
        self.cache: dict[str, tuple] = {}

    def _load(self, date_str: str):
        if date_str in self.cache:
            return self.cache[date_str]
        pd, to_tri = self.pd, self.to_tri
        rows: dict[tuple[str, str], object] = {}
        odds = None
        try:
            pdf = pd.read_csv(self.processed / f"predictions_{date_str}.csv")
            for _, row in pdf.iterrows():
                rows[(to_tri(row.get("home_team")), to_tri(row.get("visitor_team")))] = row
        except Exception:
            pass
        try:
            odds = pd.read_csv(self.processed / f"game_odds_{date_str}.csv")
            odds["home_tri"] = odds.get("home_team", "").astype(str).map(to_tri)
            odds["away_tri"] = odds.get("visitor_team", "").astype(str).map(to_tri)
        except Exception:
            odds = None
        self.cache[date_str] = (rows, odds, self.tf.schedule_tips(self.processed, date_str))
        return self.cache[date_str]

    def tip(self, date_str: str, home: str, away: str) -> datetime | None:
        rows, odds, schedule = self._load(date_str)
        row = rows.get((home, away), {})
        return self.tf.tip_time(row, odds_df=odds, schedule=schedule, home=home, away=away)


def scan(league: str, data_root: Path, *, since: str | None, replay: bool) -> list[dict]:
    src = data_root / f"{league}_source"
    tips = _Tips(src / "data" / "processed")
    builds: list[dict] = []
    for log in sorted(glob.glob(str(src / "logs" / "syndicate_refresh_oddsapi_props_*.log"))):
        log_date = Path(log).stem.rsplit("_", 1)[-1]
        if since and log_date < since:
            continue
        lines = Path(log).read_text(encoding="utf-8", errors="replace").splitlines()
        last_ts: list[datetime | None] = [None] * len(lines)
        next_ts: list[datetime | None] = [None] * len(lines)
        cur = None
        for i, line in enumerate(lines):
            cur = _ts(line) or cur
            last_ts[i] = cur
        cur = None
        for i in range(len(lines) - 1, -1, -1):
            cur = _ts(lines[i]) or cur
            next_ts[i] = cur
        pending: dict[str, list[dict]] = {}
        decision_ts, pos = None, 0
        for i, line in enumerate(lines):
            mr = REUSE.search(line)
            if mr:
                kind, _lg, _date, fname, rest = mr.groups()
                if "reuse=False" in rest or "stale=1" in rest:
                    pending.setdefault(fname, []).append({"kind": kind, "detail": rest.strip()})
                continue
            mcal = CAL_STALE.search(line)
            if mcal:
                pending.setdefault(mcal.group(1), []).append(
                    {"kind": "NBA_SIM_STALE", "detail": f"have={mcal.group(2)} want={mcal.group(3)}"})
                continue
            mf = FREEZE.search(line)
            if mf:
                pending.setdefault(mf.group(3), []).append({"kind": "SMART_SIM_TIP_FREEZE", "detail": mf.group(5).strip()})
                continue
            if line.startswith("PROCESS_TREE_MEMORY") and "smart_sim_run_date_local:prepared_jobs" in line:
                decision_ts, pos = last_ts[i], 0
                continue
            if not (line.startswith("PROCESS_TREE_MEMORY") and "smart_sim_worker_run_local:before_simulation" in line):
                continue
            try:
                payload = json.loads(line[len("PROCESS_TREE_MEMORY "):])
            except Exception:
                continue
            date_str = str(payload.get("date_str"))
            home, away = str(payload.get("home_tri")), str(payload.get("away_tri"))
            fname = os.path.basename(str(payload.get("out_path") or ""))
            tip = tips.tip(date_str, home, away)
            lo, hi = last_ts[i], next_ts[i]
            if tip is None:
                phase = "no_tip"
            elif lo is not None and lo >= tip:
                phase = "after_tip"
            elif hi is not None and hi <= tip:
                phase = "before_tip"
            else:
                phase = "straddles_tip"
            build = {
                "league": league, "log": Path(log).name, "line": i + 1, "date": date_str, "game": f"{home}_{away}",
                "decision": decision_ts.isoformat() if decision_ts else None, "queued": pos,
                "lo": lo.isoformat() if lo else None, "hi": hi.isoformat() if hi else None,
                "tip": tip.isoformat() if tip else None,
                "min_after_tip": round((lo - tip).total_seconds() / 60.0, 1) if (lo and tip) else None,
                "phase": phase, "reasons": pending.pop(fname, []),
            }
            if replay and decision_ts is not None:
                with contextlib.redirect_stdout(io.StringIO()):
                    old = os.environ.pop(tips.tf.SWITCH_ENV, None)
                    try:
                        build["freeze_would_keep"] = tips.tf.keep_existing(
                            Path(fname), has_players=True, tip=tip, queued=pos, date_str=date_str, league=league,
                            now=lambda d=decision_ts: d)
                    finally:
                        if old is not None:
                            os.environ[tips.tf.SWITCH_ENV] = old
            pos += 1
            builds.append(build)
    return builds


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data-root", required=True)
    ap.add_argument("--leagues", default="nba,wnba")
    ap.add_argument("--since", default=None, help="first log date to read (YYYY-MM-DD)")
    ap.add_argument("--replay-freeze", action="store_true")
    ap.add_argument("--json", default=None)
    args = ap.parse_args()
    builds: list[dict] = []
    for league in [s.strip() for s in args.leagues.split(",") if s.strip()]:
        builds.extend(scan(league, Path(args.data_root), since=args.since, replay=args.replay_freeze))
    if args.json:
        Path(args.json).write_text(json.dumps(builds, indent=1), encoding="utf-8")
    for league in sorted({b["league"] for b in builds}):
        rows = [b for b in builds if b["league"] == league]
        games = defaultdict(list)
        for b in rows:
            games[(b["date"], b["game"])].append(b)
        print(f"== {league}: builds={len(rows)} games={len(games)} by phase={dict(Counter(b['phase'] for b in rows))}"
              f" games_with_after_tip={sum(1 for v in games.values() if any(x['phase'] == 'after_tip' for x in v))}")
        for b in rows:
            if b["phase"] == "before_tip" and not b.get("freeze_would_keep"):
                continue
            kinds = "+".join(sorted({r["kind"] for r in b["reasons"]})) or "(none: missing/overwrite/targeted)"
            replay = f" freeze_would_keep={b['freeze_would_keep']}" if "freeze_would_keep" in b else ""
            print(f"  {b['date']} {b['game']} {b['phase']} lo={b['lo']} tip={b['tip']} min_after_tip={b['min_after_tip']}"
                  f" queued={b['queued']} trigger={kinds}{replay}")
        if args.replay_freeze:
            fp = sum(1 for b in rows if b["phase"] == "before_tip" and b.get("freeze_would_keep"))
            tp = sum(1 for b in rows if b["phase"] == "after_tip" and b.get("freeze_would_keep"))
            n_after = sum(1 for b in rows if b["phase"] == "after_tip")
            print(f"  replay: after_tip kept {tp}/{n_after}; before_tip kept (finish projected past tip) {fp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
