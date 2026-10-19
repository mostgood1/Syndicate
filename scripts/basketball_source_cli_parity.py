"""Parity gate: Syndicate source CLI (syndicate/features/<league>/source_cli) == the vendored <league>_betting.cli (`--league`).

Lane nba-source-cli-native (2026-10-12). Record/replay, one arm per PROCESS, built on scripts/basketball_live_tick_parity.py
(call-counted clock, frozen datetime, `requests` tape with the OddsAPI key stripped, file-open audit).

Each arm runs the props refresh's whole game-input bootstrap IN ORDER, in-process through click
(`cli.main([...], standalone_mode=False)`), on its OWN copy of the data root -- the commands feed each other
(schedule -> features -> injuries -> pbp -> lineup effects -> game cards -> predictions), exactly as
`_ensure_source_game_inputs` runs them. Every command runs (the refresh skips some when their outputs are fresh;
parity wants every code path).

  record   the VENDORED commands against the real network (cwd = vendor/nba_betting_repo, as production runs them)
  replay   either arm from the tape (port: cwd = the Syndicate repo, as the switched refresh will run it)
  compare  every file either arm created or changed (CSV/JSON as text, parquet as frames, anything else by sha256),
           each command's outcome, the clock-call count and the tape misses; `--plant` is the positive control

Usage (fleet, at Idle):
  nice -n 19 python scripts/basketball_source_cli_parity.py record --date 2026-10-13 --data-root A/data --tape T.json --out v.json
  nice -n 19 python scripts/basketball_source_cli_parity.py replay --arm port --date 2026-10-13 --data-root B/data --tape T.json --out p.json
  python scripts/basketball_source_cli_parity.py compare v.json p.json [--plant]
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.util
import io
import json
import os
import sys
import time as _time_mod
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("_tick_parity", ROOT / "scripts" / "basketball_live_tick_parity.py")
tp = importlib.util.module_from_spec(_spec)
sys.modules["_tick_parity"] = tp
_spec.loader.exec_module(tp)



def bootstrap_steps(date_str: str, league: str = "nba") -> list[list[str]]:
    """The commands each refresh's game-input bootstrap runs, in its order."""
    if league == "wnba":
        # refresh_wnba_oddsapi_props: _ensure_source_game_inputs + _ensure_rotation_inputs_for_props_refresh + predict-date
        return [
            ["fetch-schedule"],
            ["fetch", "--years", "1"],
            ["build-features"],
            ["fetch-injuries", "--date", date_str],
            ["write-pregame-expected-minutes", "--date", date_str],
            ["predict-date", "--date", date_str],
        ]
    # update-pbp-espn-history / build-lineup-teammate-effects left the NBA bootstrap 2026-10-13 (lineup effects retired).
    return [
        ["fetch-schedule"],
        ["fetch", "--years", "1"],
        ["build-features"],
        ["fetch-injuries", "--date", date_str],
        ["export-game-cards", "--date", date_str],
        ["predict-date", "--date", date_str],
    ]

def _file_value(p: Path) -> Any:
    raw = p.read_bytes()
    if p.suffix == ".parquet":
        import pandas as pd

        try:
            return {"parquet": tp._jsonable(pd.read_parquet(p).to_dict(orient="list"))}
        except Exception as exc:  # noqa: BLE001
            return {"parquet_unreadable": type(exc).__name__, "sha256": hashlib.sha256(raw).hexdigest()}
    if p.suffix in {".csv", ".json", ".jsonl", ".txt", ".log"}:
        return raw.decode("utf-8", errors="replace").splitlines()
    return {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def collect(data_root: Path, before: dict[str, str]) -> dict[str, Any]:
    out = {}
    for p in sorted(data_root.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(data_root).as_posix()
        if before.get(rel) == hashlib.sha256(p.read_bytes()).hexdigest():
            continue
        out[rel] = _file_value(p)
    return out


def snapshot(data_root: Path) -> dict[str, str]:
    return {p.relative_to(data_root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in data_root.rglob("*") if p.is_file()}


def run_arm(args, mode: str, arm: str) -> int:
    data_root = Path(args.data_root).resolve()
    league = args.league
    up = league.upper()
    vendor_repo = ROOT / "vendor" / f"{league}_betting_repo"
    os.environ[f"{up}_BETTING_DATA_ROOT"] = str(data_root)
    os.environ["NBA_BETTING_RECONCILE_REPO_DATA"] = "0"
    os.environ["WNBA_BETTING_RECONCILE_REPO_DATA"] = "0"
    tape_path = Path(args.tape)
    tape: dict[str, Any] = tp.load_tape(tape_path) if mode == "replay" else {"date": args.date, "league": league, "kind": f"{league}_source_cli"}
    base = float(tape.get("clock_base") or _time_mod.time())
    tape["clock_base"] = base
    if mode == "record":
        tape["odds_api_key_present"] = bool((os.environ.get("ODDS_API_KEY") or "").strip())
    elif tape.get("odds_api_key_present"):
        os.environ["ODDS_API_KEY"] = "parity-replay-dummy-key"
    else:
        os.environ.pop("ODDS_API_KEY", None)
    real_sleep = _time_mod.sleep
    if mode == "replay":
        _time_mod.sleep = lambda s: None  # rate-limit sleeps protect the upstream APIs; a replay calls none
    tp.install_clock(base)
    tp.install_tape(mode, tape)
    opened: set[str] = set()
    tp.install_open_audit({"data": data_root}, opened)
    before = snapshot(data_root)
    if arm == "vendored":
        sys.path.insert(0, str(vendor_repo / "src"))
        os.chdir(vendor_repo)
        mod = importlib.import_module(f"{league}_betting.cli")
    else:
        sys.path.insert(0, str(ROOT))
        os.chdir(ROOT)
        mod = importlib.import_module(f"syndicate.features.{league}.source_cli.cli")
    tp.CLOCK.calls = 0
    steps = []
    t0 = _time_mod.perf_counter()
    for argv in bootstrap_steps(args.date, league):
        buf = io.StringIO()
        try:
            with redirect_stdout(buf):
                rv = mod.cli.main(args=list(argv), standalone_mode=False)
            outcome = {"ok": True, "rv": tp._jsonable(rv) if rv is not None else None}
        except SystemExit as exc:
            outcome = {"ok": exc.code in (0, None), "exit": exc.code}
        except Exception as exc:  # noqa: BLE001
            outcome = {"ok": False, "error": f"{type(exc).__name__}: {str(exc)[:300]}"}
        outcome["clock_calls_after"] = tp.CLOCK.calls
        steps.append({"argv": argv, **outcome})
        print(json.dumps({"step": argv[0], **{k: v for k, v in outcome.items() if k != "rv"}}), file=sys.stderr, flush=True)
    _time_mod.sleep = real_sleep
    out = {
        "arm": arm,
        "date": args.date,
        "result": {"steps": steps},
        "files": collect(data_root, before),
        "meta": {"data_root": str(data_root), "clock_calls": tp.CLOCK.calls, "seconds": round(_time_mod.perf_counter() - t0, 1),
                 "requests": len(tape["entries"]) if mode == "record" else None,
                 "misses": tape.get("misses", []), "served": len(tape.get("served", []))},
    }
    Path(args.out).write_text(json.dumps(out, sort_keys=True, default=str), encoding="utf-8")
    if mode == "record":
        tape["opened"] = sorted(opened)
        tape_path.write_text(json.dumps(tape, sort_keys=True), encoding="utf-8")
    print(json.dumps({"arm": arm, "mode": mode, "steps_ok": [s["ok"] for s in steps], "files_written": len(out["files"]),
                      "clock_calls": tp.CLOCK.calls, "requests": out["meta"]["requests"], "misses": len(out["meta"]["misses"]),
                      "opened": len(opened), "seconds": out["meta"]["seconds"]}))
    return 0 if not out["meta"]["misses"] else 2


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("record", "replay"):
        p = sub.add_parser(name)
        p.add_argument("--league", choices=("wnba",), default="wnba")  # NBA arm retired, lane nba-vendor-deletion-prep
        p.add_argument("--date", required=True)
        p.add_argument("--data-root", required=True)
        p.add_argument("--tape", required=True)
        p.add_argument("--out", required=True)
        if name == "replay":
            p.add_argument("--arm", choices=("vendored", "port"), required=True)
    c = sub.add_parser("compare")
    c.add_argument("a")
    c.add_argument("b")
    c.add_argument("--plant", action="store_true")
    args = ap.parse_args(argv)
    if args.cmd == "record":
        return run_arm(args, "record", "vendored")
    if args.cmd == "replay":
        return run_arm(args, "replay", args.arm)
    return tp.cmd_compare(args)  # same comparison: result + files + clock calls + misses, data root neutralised


if __name__ == "__main__":
    sys.exit(main())
