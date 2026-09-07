"""Rebuild the MLB season-scoped sim inputs and publish them to production.

WHY THIS EXISTS. Measured 2026-09-07: all five season artifacts
(`arsenal`, `quality`, `batted_ball`, `pitch_splits`, `conditional_mix`) carry
an embedded `generated_at` of **2026-08-17/18** while their disk mtimes refresh
daily. `pull_season_artifacts()` copies each file from web onto the worker
before every sim run -- a mirror of a mirror that touches the file and
regenerates nothing -- so the obvious freshness check reads current and the
CONTENTS are three weeks old. Nothing on any schedule rebuilds them: the five
builders were written in one session on 2026-08-17 and each has exactly one
commit in its entire history.

THREE BUILDERS, NOT FIVE, and that is a finding rather than a shortcut:

  arsenal      pb.statcast_pitcher_arsenal_stats + statcast_batter_pitch_arsenal
  batted_ball  pb.statcast_batter_exitvelo_barrels (+ pitcher side)
  quality      pb.statcast_batter_expected_stats + exitvelo_barrels
        ^ self-contained: two or three Statcast leaderboard calls each.

  conditional_mix  reads vendor/mlb_bettingv2/data/raw/statcast/pitches/<season>/*.csv.gz
  pitch_splits     reads vendor/mlb_bettingv2/data/cache/statcast/pitcher_pitch_splits
        ^ NOT schedulable here. Both read gitignored vendor trees that do not
          exist on any runner or on the worker, so scheduling them would produce
          a confident zero. `pitch_splits` is additionally SUPERSEDED -- the
          arsenal builder's own docstring says so, and it fills the same fields
          from 2 leaderboard calls instead of a 309-call ~80-minute pipeline.
          Scheduling a superseded builder would fight the one that replaced it.

WHY IT PUBLISHES TO WEB RATHER THAN WRITING A DISK. Render gives each service
its own volume (`syndicate-data-web`, `syndicate-data-refresh-worker`,
`syndicate-data-live-odds-worker`), all mounted at the same path. Nothing that
is not refresh-worker can write refresh-worker's disk. So the transport is the
one these artifacts already travel: publish to WEB, and the worker's
`pull_season_artifacts()` copies them down before its next roster build. That
is true of a GitHub runner and would have been equally true of a Render cron
job -- the disk is not shareable either way.

VERIFICATION IS PART OF THE JOB, NOT A FOLLOW-UP. `pull_season_artifacts`'s own
docstring warns that a return of 0 "is not proof of success -- it is equally
consistent with 'already current' and with 'nothing matched'". The same trap is
one layer up: a publish that 200s proves the request was accepted, not that the
bytes on production changed. So `--verify` reads each artifact BACK from
`/api/ops/artifacts/export` and compares the round-tripped `generated_at`
against what was just built. Anything else is the writer's account of itself.

    py -3 scripts/publish_mlb_season_artifacts.py --season 2026
    py -3 scripts/publish_mlb_season_artifacts.py --season 2026 --publish --verify
"""

from __future__ import annotations

import argparse
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

# (builder script, artifact relative path template)
BUILDERS: tuple[tuple[str, str], ...] = (
    ("build_mlb_arsenal_artifact.py",
     "mlb_source/source_artifacts/data/arsenal/arsenal_{season}.json"),
    ("build_mlb_batted_ball_artifact.py",
     "mlb_source/source_artifacts/data/batted_ball/batted_ball_{season}.json"),
    ("build_mlb_quality_artifact.py",
     "mlb_source/source_artifacts/data/quality/quality_{season}.json"),
)

# Deliberately named so a reader does not have to rediscover why they are absent.
NOT_SCHEDULABLE = {
    "build_mlb_conditional_mix_artifact.py":
        "reads vendor/mlb_bettingv2/data/raw/statcast/pitches/<season>/*.csv.gz "
        "(gitignored; absent on runners and on the worker)",
    "build_mlb_pitch_splits_artifact.py":
        "reads a local DiskCache under vendor/mlb_bettingv2/data/ (gitignored), "
        "AND is superseded by the arsenal builder per its own docstring",
}


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
    env_file = REPO_ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("ADMIN_TOKEN"):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def _generated_at(path: Path) -> str | None:
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("generated_at")
    except Exception:
        return None


def _fetch_published(rel: str, token: str, *, attempts: int = 5) -> dict | None:
    """Read the artifact back from production. Retries: web is deployed often
    and a 502 mid-deploy is not evidence the publish failed."""
    url = (_base_url() + "/api/ops/artifacts/export?"
           + urllib.parse.urlencode({"pattern": rel, "limit": "2"}))
    for i in range(attempts):
        try:
            req = urllib.request.Request(
                url, headers={"X-Admin-Token": token, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=150) as resp:
                payload = json.load(resp)
            arts = payload.get("artifacts") or {}
            for _name, raw in arts.items():
                return json.loads(raw) if isinstance(raw, str) else raw
            return None
        except Exception as exc:
            print(f"    read-back retry {i}: {type(exc).__name__}", flush=True)
            time.sleep(15)
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--season", type=int, default=datetime.now(timezone.utc).year)
    ap.add_argument("--publish", action="store_true",
                    help="upload each rebuilt artifact to web")
    ap.add_argument("--verify", action="store_true",
                    help="read each artifact BACK from production and compare "
                         "generated_at against what was just built")
    args = ap.parse_args()

    root = _data_root()
    print(f"season      {args.season}")
    print(f"data root   {root}")
    print(f"base url    {_base_url()}")
    print("")
    for name, why in NOT_SCHEDULABLE.items():
        print(f"  NOT RUN  {name}\n           {why}")
    print("")

    built: list[tuple[str, Path, str | None, str | None]] = []
    failures: list[str] = []
    for script, tmpl in BUILDERS:
        rel = tmpl.format(season=args.season)
        target = root / rel
        before = _generated_at(target) if target.exists() else None
        print(f"=== {script} ===", flush=True)
        proc = subprocess.run([sys.executable, f"scripts/{script}",
                               "--season", str(args.season)],
                              cwd=REPO_ROOT, capture_output=True, text=True)
        tail = (proc.stdout or "").strip().splitlines()[-4:]
        for line in tail:
            print("   " + line)
        if proc.returncode != 0:
            print(f"   FAILED rc={proc.returncode}")
            print("   " + (proc.stderr or "").strip()[-400:])
            failures.append(script)
            continue
        after = _generated_at(target)
        if after is None:
            print(f"   FAILED: no artifact at {target}")
            failures.append(script)
            continue
        # A builder that exits 0 without moving `generated_at` has produced
        # nothing new. That is the exact silent-no-op this whole job exists to
        # end, so it is an error here rather than a shrug.
        if before is not None and after == before:
            print(f"   FAILED: generated_at did not move ({after})")
            failures.append(script)
            continue
        print(f"   generated_at {before} -> {after}")
        built.append((rel, target, before, after))
        print("")

    if failures:
        print(f"\n{len(failures)} builder(s) FAILED: {failures}")
        return 1

    if not args.publish:
        print("\nBUILT ONLY. Local mirror updated; production untouched. "
              "Re-run with --publish --verify to ship them.")
        return 0

    token = _token()
    if not token:
        print("\nREFUSING: no ADMIN_TOKEN. Publishing without it would 401 and "
              "the run would look like a success with nothing shipped.")
        return 2

    from syndicate.features.shared import artifact_publisher as ap_mod
    url = _base_url() + "/api/ops/artifacts/publish"
    published = 0
    for rel, target, _before, _after in built:
        ok = ap_mod._publish_streamed(  # noqa: SLF001
            target, relative_path=rel, url=url, token=token, timeout_seconds=180,
        # Name the TOOL when there is no service lane -- this script
        # runs wherever an operator runs it, so every artifact it published
        # reached the receiver as `publisher=unknown` (measured 2026-09-07).
        publisher=ap_mod.publisher_identity_for_tool("publish_mlb_season_artifacts"))
        print(f"publish {rel} -> {ok}")
        if ok:
            published += 1
    print(f"\npublished {published} of {len(built)}")
    if published != len(built):
        return 3

    if not args.verify:
        print("\nNOT VERIFIED. A 200 means the request was accepted, not that "
              "production's bytes changed. Re-run with --verify.")
        return 0

    print("\n=== READ-BACK FROM PRODUCTION ===")
    bad = []
    for rel, _target, _before, after in built:
        doc = _fetch_published(rel, token)
        got = (doc or {}).get("generated_at")
        state = "OK" if got == after else "MISMATCH"
        if got != after:
            bad.append((rel, after, got))
        print(f"  {state:8s} {rel.split('/')[-1]:28s} expected {after}  got {got}")
    if bad:
        print(f"\n{len(bad)} artifact(s) did NOT round-trip: {bad}")
        return 4
    print("\nVERIFIED: production now serves the generated_at this run produced.")
    print("The worker picks them up via pull_season_artifacts() before its next "
          "roster build; that hop is NOT verified here.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
