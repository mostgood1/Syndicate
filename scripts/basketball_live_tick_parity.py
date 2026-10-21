"""Parity replay: Syndicate basketball live-lens tick (syndicate/features/<league>/live_tick) against RECORDED vendored output.

Lane nba-live-tick-native (2026-10-12; NBA and WNBA, `--league`). The vendored tick was recorded against live games
(network tape + the files it opened + its output) while vendor/ existed; the `record` arm, the vendored replay arm and
`reduce` were removed 2026-10-20 (lane vendor-dead-paths-cleanup, vendor/ is empty). What stays, one arm per PROCESS:

  replay   run the PORT with the network served from a recorded tape. A request the tape does not hold is a failure.
  compare  leaf-compare two outputs (e.g. the recorded vendored output vs the port's); `--plant` first changes one
           leaf, which must then be reported (positive control).

DETERMINISM. Nothing in the tick uses threads or randomness, so the only other inputs are the clock and the files:
`time.time()` is a call counter (base + 1 ms per call) and `datetime.now()/utcnow()/today()` read the same counter.
Each replay gets its OWN copy of the data root and live-lens dir (the tick read-modify-writes
`processed/live_lens_registry/` and appends to `player_ids.csv` and the JSONLs).

Usage (fleet, at Idle):
  nice -n 19 python scripts/basketball_live_tick_parity.py replay --league nba --arm port --date 2026-10-12 --data-root B/data \
      --live-lens-dir B/ll --tape T.json --out port.json
  python scripts/basketball_live_tick_parity.py compare vendored.json port.json [--plant]
"""
from __future__ import annotations

import argparse
import base64
import datetime as _dt_mod
import gzip
import hashlib
import json
import os
import sys
import time as _time_mod
import urllib.parse
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SECRET_PARAMS = {"apikey", "api_key", "key"}


# ---------------------------------------------------------------- deterministic clock
class _Clock:
    def __init__(self, base: float) -> None:
        self.base = float(base)
        self.calls = 0
        self.real = _time_mod.time
        self.passthrough = 0

    def time(self) -> float:
        if self.passthrough:
            return self.real()
        self.calls += 1
        return self.base + self.calls * 0.001


CLOCK: _Clock | None = None
_RealDT = _dt_mod.datetime


class _FrozenDT(_RealDT):
    @classmethod
    def now(cls, tz=None):  # noqa: D401
        return _RealDT.fromtimestamp(CLOCK.time(), tz) if tz is not None else _RealDT.fromtimestamp(CLOCK.time())

    @classmethod
    def utcnow(cls):
        return _RealDT.utcfromtimestamp(CLOCK.time())

    @classmethod
    def today(cls):
        return cls.now()


def install_clock(base: float) -> None:
    """Install BEFORE the arm is imported, so the arm's own `from datetime import datetime` binds the frozen class."""
    global CLOCK
    import numpy  # noqa: F401  -- heavy libraries bind the REAL datetime first
    import pandas  # noqa: F401
    import requests  # noqa: F401

    CLOCK = _Clock(base)
    _time_mod.time = CLOCK.time
    _dt_mod.datetime = _FrozenDT


# ---------------------------------------------------------------- network tape
def _key(method: str, url: str, params: Any, data: Any, json_body: Any) -> str:
    parts = urllib.parse.urlsplit(url)
    q = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
    if isinstance(params, dict):
        q += [(str(k), str(v)) for k, v in params.items() if v is not None]
    elif isinstance(params, (list, tuple)):
        q += [(str(k), str(v)) for k, v in params]
    q = sorted((k, v) for k, v in q if k.lower() not in SECRET_PARAMS)
    base = urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
    body = json.dumps(json_body, sort_keys=True, default=str) if json_body is not None else (str(data) if data else "")
    return f"{method.upper()} {base}?{urllib.parse.urlencode(q)} {body}"


def install_tape(tape: dict) -> None:
    import requests
    from requests.structures import CaseInsensitiveDict

    entries = tape.setdefault("entries", [])
    queues: dict[str, list[dict]] = {}
    for e in entries:
        queues.setdefault(e["key"], []).append(e)
    tape.setdefault("misses", [])

    def fake(self, method, url, params=None, data=None, headers=None, cookies=None, files=None, auth=None,
             timeout=None, allow_redirects=True, proxies=None, hooks=None, stream=None, verify=None, cert=None,
             json=None):
        key = _key(method, url, params, data, json)
        q = queues.get(key)
        if not q:
            tape["misses"].append(key)
            raise requests.exceptions.ConnectionError(f"parity tape miss: {key[:200]}")
        e = q.pop(0) if len(q) > 1 else q[0]
        tape.setdefault("served", []).append(key)
        if "error" in e:
            mod, name, msg = e["error"]
            cls = getattr(sys.modules.get(mod), name, None) or requests.exceptions.RequestException
            raise cls(msg)
        r = requests.models.Response()
        r.status_code = int(e["status"])
        r._content = base64.b64decode(e["content"])
        r.headers = CaseInsensitiveDict(e.get("headers") or {})
        r.encoding = e.get("encoding")
        r.url = e.get("url") or url
        r.reason = "OK" if r.status_code < 400 else "ERR"
        return r

    requests.sessions.Session.request = fake


# ---------------------------------------------------------------- file audit
def install_open_audit(roots: dict[str, Path], sink: set[str]) -> None:
    """Record every file opened under a root as "<tag>/<relative path>"."""
    rs = {tag: str(r.resolve()) for tag, r in roots.items()}

    def hook(event, args):
        if event == "open" and args and isinstance(args[0], (str, bytes, os.PathLike)):
            try:
                p = os.path.abspath(os.fsdecode(args[0]))
            except Exception:
                return
            for tag, r in rs.items():
                if p.startswith(r + os.sep):
                    sink.add(tag + "/" + os.path.relpath(p, r).replace("\\", "/"))

    sys.addaudithook(hook)


# ---------------------------------------------------------------- outputs
def _jsonable(x: Any) -> Any:
    return json.loads(json.dumps(x, default=str, allow_nan=True))


def collect_outputs(data_root: Path, live_lens_dir: Path, before: dict[str, str]) -> dict[str, Any]:
    """Every file the arm created or changed under its data root / live-lens dir, with its content."""
    out: dict[str, Any] = {}
    for base, tag in ((data_root, "data"), (live_lens_dir, "live_lens")):
        for p in sorted(base.rglob("*")):
            if not p.is_file():
                continue
            rel = f"{tag}/{p.relative_to(base).as_posix()}"
            raw = p.read_bytes()
            digest = hashlib.sha256(raw).hexdigest()
            if before.get(rel) == digest:
                continue
            if p.suffix == ".jsonl":
                out[rel] = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]
            elif p.suffix == ".json":
                out[rel] = json.loads(raw.decode("utf-8"))
            else:
                out[rel] = raw.decode("utf-8", errors="replace").splitlines()
    return out


def snapshot_hashes(data_root: Path, live_lens_dir: Path) -> dict[str, str]:
    snap = {}
    for base, tag in ((data_root, "data"), (live_lens_dir, "live_lens")):
        for p in base.rglob("*"):
            if p.is_file():
                snap[f"{tag}/{p.relative_to(base).as_posix()}"] = hashlib.sha256(p.read_bytes()).hexdigest()
    return snap


def run_arm(args) -> int:
    data_root = Path(args.data_root).resolve()
    live_lens_dir = Path(args.live_lens_dir).resolve()
    league = args.league
    up = league.upper()
    # Both apps read <LEAGUE>_BETTING_DATA_ROOT / <LEAGUE>_LIVE_LENS_DIR first (WNBA then falls back to the NBA names).
    os.environ[f"{up}_BETTING_DATA_ROOT"] = str(data_root)
    os.environ[f"{up}_LIVE_LENS_DIR"] = str(live_lens_dir)
    os.environ.pop("LIVE_LENS_DIR", None)
    tape_path = Path(args.tape)
    tape: dict[str, Any] = load_tape(tape_path)
    base = float(tape.get("clock_base") or _time_mod.time())
    tape["clock_base"] = base
    # Whether the OddsAPI key is SET changes the path (no key = no OddsAPI calls). The tape never holds the key; it
    # records whether the recording had one, and a replay reproduces that with a dummy, whatever its own shell holds.
    if tape.get("odds_api_key_present"):
        os.environ["ODDS_API_KEY"] = "parity-replay-dummy-key"
    else:
        os.environ.pop("ODDS_API_KEY", None)
    install_clock(base)
    install_tape(tape)
    opened: set[str] = set()
    install_open_audit({"data": data_root, "live_lens": live_lens_dir}, opened)
    before = snapshot_hashes(data_root, live_lens_dir)
    sys.path.insert(0, str(ROOT))
    import importlib

    arm = "port"
    mod = f"syndicate.features.{league}.live_tick.tick"
    fn = importlib.import_module(mod)._live_lens_tick_payload
    clock_at_call = CLOCK.calls
    CLOCK.calls = 0  # import-time clock reads differ between arms; the tick itself starts at 0 in both
    t0 = _time_mod.perf_counter()
    try:
        result: Any = {"ok": True, "value": _jsonable(fn(args.date))}
    except Exception as exc:  # noqa: BLE001
        result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    elapsed = _time_mod.perf_counter() - t0
    out = {
        "arm": arm,
        "league": league,
        "date": args.date,
        "result": result,
        "files": collect_outputs(data_root, live_lens_dir, before),
        "meta": {"data_root": str(data_root), "live_lens_dir": str(live_lens_dir), "clock_calls": CLOCK.calls, "import_clock_calls": clock_at_call, "seconds": round(elapsed, 2),
                 "requests": None,
                 "misses": tape.get("misses", []), "served": tape.get("served", [])},
    }
    Path(args.out).write_text(json.dumps(out, sort_keys=True, default=str), encoding="utf-8")
    games = (result.get("value") or {}).get("games") if isinstance(result.get("value"), dict) else None
    print(json.dumps({"arm": arm, "mode": "replay", "ok": result["ok"], "error": result.get("error"),
                      "files_written": len(out["files"]), "clock_calls": CLOCK.calls,
                      "requests": out["meta"]["requests"], "misses": len(out["meta"]["misses"]),
                      "opened": len(opened), "seconds": out["meta"]["seconds"],
                      "value_keys": sorted(result["value"].keys())[:20] if isinstance(result.get("value"), dict) else None,
                      "games": len(games) if isinstance(games, list) else None}))
    return 0 if result["ok"] and (getattr(args, "allow_misses", False) or not out["meta"]["misses"]) else 2


def load_tape(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    if path.suffix == ".gz":
        raw = gzip.decompress(raw)
    return json.loads(raw.decode("utf-8"))


# ---------------------------------------------------------------- compare
def leaf_compare(a: Any, b: Any, path: str = "$", diffs: list[str] | None = None, limit: int = 40) -> tuple[int, list[str]]:
    diffs = [] if diffs is None else diffs
    count = [0, 0]

    def walk(x, y, p):
        if isinstance(x, dict) and isinstance(y, dict):
            for k in sorted(set(x) | set(y), key=str):
                if k not in x or k not in y:
                    count[1] += 1
                    if len(diffs) < limit:
                        diffs.append(f"{p}.{k}: only in {'A' if k in x else 'B'}")
                    continue
                walk(x[k], y[k], f"{p}.{k}")
        elif isinstance(x, list) and isinstance(y, list):
            if len(x) != len(y):
                count[1] += 1
                if len(diffs) < limit:
                    diffs.append(f"{p}: len {len(x)} != {len(y)}")
            for i, (u, v) in enumerate(zip(x, y)):
                walk(u, v, f"{p}[{i}]")
        else:
            count[0] += 1
            same = x == y or (isinstance(x, float) and isinstance(y, float) and x != x and y != y)
            if not same or type(x) is not type(y):
                count[1] += 1
                if len(diffs) < limit:
                    diffs.append(f"{p}: {str(x)[:80]!r} != {str(y)[:80]!r}")

    walk(a, b, path)
    return count[0], diffs if count[1] == 0 else diffs + [f"TOTAL_DIFFS={count[1]}"]


def _plant(obj: Any) -> str | None:
    """Change the first numeric leaf found (deepest-first walk over the outputs)."""
    stack = [("$", obj)]
    while stack:
        p, x = stack.pop()
        if isinstance(x, dict):
            for k in sorted(x, key=str, reverse=True):
                v = x[k]
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    x[k] = v + 1
                    return f"{p}.{k}"
                stack.append((f"{p}.{k}", v))
        elif isinstance(x, list):
            for i in range(len(x) - 1, -1, -1):
                stack.append((f"{p}[{i}]", x[i]))
    return None


def _neutral_roots(out: dict) -> dict:
    """Each arm runs on its own copy of the data root / live-lens dir; the path itself is not an output."""
    meta = out.get("meta") or {}
    # The clock-call count and the tape misses are outputs too: a different path through the tick shows in them.
    text = json.dumps({"result": out["result"], "files": out["files"], "clock_calls": meta.get("clock_calls"),
                       "misses": meta.get("misses") or []}, sort_keys=True)
    for key, token in (("live_lens_dir", "<LIVE_LENS_DIR>"), ("data_root", "<DATA_ROOT>")):
        root = (out.get("meta") or {}).get(key)
        if root:
            text = text.replace(json.dumps(root)[1:-1], token)
    return json.loads(text)


def cmd_compare(args) -> int:
    a = _neutral_roots(json.loads(Path(args.a).read_text(encoding="utf-8")))
    b = _neutral_roots(json.loads(Path(args.b).read_text(encoding="utf-8")))
    planted = None
    if args.plant:
        planted = _plant(b["files"]) or _plant(b["result"])
    leaves, diffs = leaf_compare(a, b)
    report = {"leaves": leaves, "diffs": len([d for d in diffs if not d.startswith("TOTAL")]), "planted": planted,
              "files": sorted(a["files"]), "first_diffs": diffs[:20]}
    print(json.dumps(report, indent=1))
    if args.plant:
        return 0 if diffs else 3  # the planted change MUST be found
    return 0 if not diffs else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("replay")
    p.add_argument("--league", choices=("nba", "wnba"), required=True)
    p.add_argument("--date", required=True)
    p.add_argument("--data-root", required=True)
    p.add_argument("--live-lens-dir", required=True)
    p.add_argument("--tape", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--arm", choices=("port",), default="port", help="the port; the vendored arm went with vendor/")
    p.add_argument("--allow-misses", action="store_true", help="a tape miss raises in the arm (deterministically) instead of failing the run")
    c = sub.add_parser("compare")
    c.add_argument("a")
    c.add_argument("b")
    c.add_argument("--plant", action="store_true")
    args = ap.parse_args(argv)
    if args.cmd == "replay":
        return run_arm(args)
    return cmd_compare(args)


if __name__ == "__main__":
    sys.exit(main())
