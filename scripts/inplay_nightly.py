"""Nightly in-play recording + stage-2 scoreboard (lane in-game-trading). Read-only.

Run by the Windows scheduled task "Syndicate inplay nightly" (user-approved
2026-10-22) from a stable copy in C:/tmp/inplay_runner/, NOT from a worktree:

  1. sync: refresh the runner's copies of RUNNER_FILES from the repo's
     `origin/main` (`git show`, read-only: no fetch, no checkout). A file not on
     origin/main keeps its current copy.
  2. read ESPN for tonight's slate (`dates=<date>`) per sport; no game -> exit.
  3. wait (Idle priority) until 30 min before the first scheduled start.
  4. run scripts/inplay_recorder.py into <root>/inplay_<date>/ until 30 min
     after the last final (hard cap: last start + 6 h). OddsAPI is polled for a
     sport only while one of its games is in play (9 credits/min/sport).
  5. copy the fleet's NBA live re-sim ledger in (`wsl -- cp`; the UNC path
     fails for it), then run inplay_edge_report.py, inplay_fair_score.py and
     inplay_scoreboard.py: <dir>/scoreboard.md for the night and
     <root>/inplay_scoreboard.md for every night so far.
  6. replay the in-game ENTRY rule over every recorded night
     (inplay_rule_sweep.py, walk-forward by night), NHL then NBA spreads:
     <root>/inplay_rule_sweep.md.

It sends no order, writes nothing on the fleet, and reads only ODDS_API_KEY.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUNNER = HERE.parent
REPO = r"C:\Users\tempadmin\OneDrive\Coding\Syndicate"
RUNNER_FILES = ["scripts/inplay_recorder.py", "scripts/inplay_edge_report.py", "scripts/inplay_fair_score.py",
                "scripts/inplay_scoreboard.py", "scripts/inplay_nightly.py", "scripts/inplay_rule_sweep.py",
                "syndicate/features/shared/venue_fees.py", "syndicate/features/shared/inplay_entries_paper.py"]
ESPN = "https://site.api.espn.com/apis/site/v2/sports/{path}/scoreboard?dates={ymd}{q}"
ESPN_PATH = {"nba": ("basketball/nba", ""), "nhl": ("hockey/nhl", ""), "nfl": ("football/nfl", ""),
             "ncaaf": ("football/college-football", "&groups=80&limit=400")}
LEDGER = "/home/amyn/syndicate-prod/data/nba_source/data/live_gameline_ledger/live_gameline_ledger_{date}.jsonl"
NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def log(root: Path, msg: str):
    line = f"{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')} {msg}"
    print(line, flush=True)
    with open(root / "inplay_nightly.log", "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def idle():
    if os.name == "nt":
        k32 = ctypes.windll.kernel32
        k32.GetCurrentProcess.restype = ctypes.c_void_p
        k32.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        if not k32.SetPriorityClass(k32.GetCurrentProcess(), 0x40):
            raise SystemExit("could not set Idle priority")
    elif hasattr(os, "nice"):
        os.nice(19)


def sync(root: Path, repo: str):
    if RUNNER == Path(repo) or (RUNNER / ".git").exists():
        log(root, "SYNC skipped: running from a checkout, not the runner")
        return
    (RUNNER / "syndicate").mkdir(parents=True, exist_ok=True)
    init = RUNNER / "syndicate" / "__init__.py"
    if not init.exists():
        init.write_bytes(b"")  # the real one installs app-only hooks; venue_fees needs none
    changed = []
    for rel in RUNNER_FILES:
        try:
            blob = subprocess.run(["git", "-C", repo, "show", f"origin/main:{rel}"], capture_output=True,
                                  timeout=60, creationflags=NO_WINDOW)
        except Exception as e:  # noqa: BLE001
            log(root, f"SYNC_FAILED {rel} {e!r}")
            continue
        if blob.returncode != 0 or not blob.stdout:
            log(root, f"SYNC_KEEP {rel} (not on origin/main)")
            continue
        dst = RUNNER / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if not dst.exists() or dst.read_bytes() != blob.stdout:
            dst.write_bytes(blob.stdout)
            changed.append(rel)
    sha = subprocess.run(["git", "-C", repo, "rev-parse", "--short", "origin/main"], capture_output=True, text=True,
                         creationflags=NO_WINDOW).stdout.strip()
    log(root, f"SYNC origin/main={sha} changed={changed}")


def slate(sports, ymd):
    """{sport: [(start_utc, state)]} for games not final/postponed."""
    out = {}
    for s in sports:
        path, q = ESPN_PATH[s]
        req = urllib.request.Request(ESPN.format(path=path, ymd=ymd, q=q), headers={"User-Agent": "syndicate-inplay-nightly/1"})
        with urllib.request.urlopen(req, timeout=20) as r:
            d = json.loads(r.read().decode("utf-8"))
        games = []
        for ev in d.get("events", []):
            typ = (((ev.get("competitions") or [{}])[0].get("status") or ev.get("status") or {}).get("type") or {})
            if typ.get("state") == "post" or typ.get("name") in ("STATUS_POSTPONED", "STATUS_CANCELED"):
                continue
            games.append((datetime.fromisoformat(ev["date"].replace("Z", "+00:00")), typ.get("state")))
        if games:
            out[s] = games
    return out


def run(root: Path, args, out_path: Path, timeout=None):
    with open(out_path, "w", encoding="utf-8") as fh:
        p = subprocess.run(args, stdout=fh, stderr=subprocess.STDOUT, timeout=timeout, creationflags=NO_WINDOW,
                           cwd=str(RUNNER))
    log(root, f"RAN {Path(args[1]).name if len(args) > 1 else args[0]} rc={p.returncode} -> {out_path.name}")
    return p.returncode


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="slate date YYYY-MM-DD (default: today, local)")
    ap.add_argument("--sports", default="nba,nhl,nfl,ncaaf")
    ap.add_argument("--root", default="C:/tmp")
    ap.add_argument("--repo", default=REPO)
    ap.add_argument("--regions", default="us,eu,uk")
    ap.add_argument("--lead-minutes", type=float, default=30.0)
    ap.add_argument("--tail-minutes", type=float, default=30.0)
    ap.add_argument("--no-sync", action="store_true")
    ap.add_argument("--no-wait", action="store_true")
    ap.add_argument("--score-only", action="store_true", help="skip recording; rescore an existing night")
    a = ap.parse_args()
    idle()
    root = Path(a.root)
    root.mkdir(parents=True, exist_ok=True)
    date = a.date or datetime.now().strftime("%Y-%m-%d")
    out = root / f"inplay_{date}"
    py = sys.executable
    if not a.no_sync:
        sync(root, a.repo)
    sports = [s.strip() for s in a.sports.split(",") if s.strip()]
    if not a.score_only:
        try:
            games = slate(sports, date.replace("-", ""))
        except Exception as e:  # noqa: BLE001
            log(root, f"SLATE_READ_FAILED {e!r}; recording every sport")
            games = {s: [(datetime.now(timezone.utc), "pre")] for s in sports}
        if not games:
            log(root, f"NO_GAMES {date} sports={sports}")
            return 0
        starts = [g[0] for v in games.values() for g in v]
        first, last = min(starts), max(starts)
        rec_sports = sorted(games)
        log(root, f"SLATE {date} " + " ".join(f"{s}={len(v)}" for s, v in sorted(games.items()))
            + f" first={first:%H:%MZ} last={last:%H:%MZ}")
        begin = first - timedelta(minutes=a.lead_minutes)
        while not a.no_wait and datetime.now(timezone.utc) < begin:
            time.sleep(min(300.0, (begin - datetime.now(timezone.utc)).total_seconds() + 1))
        until = last + timedelta(hours=6)
        out.mkdir(parents=True, exist_ok=True)
        run(root, [py, str(RUNNER / "scripts" / "inplay_recorder.py"), "--date", date, "--sports", ",".join(rec_sports),
                   "--out", str(out), "--until", until.strftime("%Y-%m-%dT%H:%M:%SZ"), "--regions", a.regions,
                   "--stop-after-final-minutes", str(a.tail_minutes)], out / "recorder.stdout")
    else:
        rec_sports = sports
    if "nba" in rec_sports:
        (out / "nba_live_gameline").mkdir(parents=True, exist_ok=True)
        dst = "/mnt/c/" + str(out / "nba_live_gameline").replace("\\", "/").split(":", 1)[1].lstrip("/") + "/"
        r = subprocess.run(["wsl", "--", "cp", LEDGER.format(date=date), dst], capture_output=True, text=True,
                           timeout=300, creationflags=NO_WINDOW)
        log(root, f"LEDGER_COPY rc={r.returncode} {r.stderr.strip()[:200]}")
    run(root, [py, str(RUNNER / "scripts" / "inplay_edge_report.py"), "--dir", str(out), "--json-out", str(out / "edge_report.json")],
        out / "edge_report.txt", timeout=3600)
    run(root, [py, str(RUNNER / "scripts" / "inplay_fair_score.py"), "--dir", str(out)], out / "fair_score.txt", timeout=3600)
    run(root, [py, str(RUNNER / "scripts" / "inplay_scoreboard.py"), "--root", str(root), "--nights", date,
               "--out", str(out / "scoreboard.md")], out / "scoreboard.stdout", timeout=3600)
    run(root, [py, str(RUNNER / "scripts" / "inplay_scoreboard.py"), "--root", str(root),
               "--out", str(root / "inplay_scoreboard.md"), "--json-out", str(root / "inplay_scoreboard.json")],
        root / "inplay_scoreboard.stdout", timeout=3600)
    nights = sorted(str(p.parent) for p in root.glob("inplay_*/kalshi.jsonl"))
    parts = []
    for sport in ("nhl", "nba"):
        so = root / f"inplay_rule_sweep_{sport}.stdout"
        run(root, [py, str(RUNNER / "scripts" / "inplay_rule_sweep.py"), "--nights", *nights, "--sports", sport],
            so, timeout=3 * 3600)
        body = so.read_text(encoding="utf-8", errors="replace")
        parts.append(f"## {sport.upper()} spreads\n\n```\n{body}```\n")
    names = ", ".join(Path(n).name.replace("inplay_", "") for n in nights)
    (root / "inplay_rule_sweep.md").write_text(
        f"# In-game entry-rule sweep (walk-forward by night)\n\nNights: {len(nights)} ({names}). Written by the {date} run.\n\n"
        + "\n".join(parts), encoding="utf-8")
    log(root, f"DONE {date}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
