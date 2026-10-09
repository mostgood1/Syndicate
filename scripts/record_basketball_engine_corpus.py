"""Record a parity corpus of REAL production basketball engine calls.

Lane basketball-native-engine (plan P1). It runs the production smart-sim entrypoint
(``basketball_props_smart_sim._smart_sim_run_date_local``, the same call
``export_props_predictions_with_smart_sim_local`` makes) for a league and a date,
and intercepts every call to the possession engine at Syndicate's per-draw helper
(``_simulate_pbp_game_boxscore_local``). For each call it keeps three things:

  * the kwargs, exactly as production built them (player frames, the config, the
    lineup pools, the quarter model, targets, team adjustments). They are stored
    once per game, because every draw of a game reuses the same objects;
  * the RNG state just before the call;
  * a digest of the OUTPUT production computed in this run. On replay, the
    vendored engine must reproduce this digest before the native comparison can
    count. That proves the recorder captured the call faithfully.

SAFETY. Point ``--source-root`` at a SCRATCH COPY of ``<league>_source``, never at
the production data root. The sim writes its outputs (and side files such as
team-advanced-stats rebuilds) under that root. ``--env-from-pid`` loads a fleet
role's environment as a Python dict read from /proc/<pid>/environ. It rewrites
every value that names the production data root to the scratch root, and drops
keyvalue/redis keys, so nothing reaches shared state. It never prints a value.

    nice -n 19 python scripts/record_basketball_engine_corpus.py --league nba \\
        --dates 2026-10-05,2026-10-06 --source-root ~/bn_corpus/data/nba_source \\
        --out-dir ~/bn_corpus/corpus --n-sims 200 --env-from-pid <refresh-worker pid> \\
        --prod-data-root ~/syndicate-prod/data --scratch-data-root ~/bn_corpus/data
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import pickle
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_DROP_ENV_MARKERS = ("KEYVALUE", "REDIS", "VALKEY")


def output_digest(out: Any) -> str:
    return hashlib.sha256(pickle.dumps(out, protocol=4)).hexdigest()


def load_role_env(pid: int, *, prod_root: str, scratch_root: str) -> dict[str, str]:
    """A role's environment as a dict, with production data paths redirected to the scratch copy. Values never printed."""
    raw = Path(f"/proc/{int(pid)}/environ").read_bytes()
    env: dict[str, str] = {}
    for item in raw.split(b"\0"):
        if b"=" not in item:
            continue
        k, v = item.split(b"=", 1)
        env[k.decode("utf-8", "replace")] = v.decode("utf-8", "replace")
    prod_root = str(Path(prod_root).expanduser())
    scratch_root = str(Path(scratch_root).expanduser())
    redirected = []
    for k in list(env):
        if any(m in k.upper() for m in _DROP_ENV_MARKERS):
            env.pop(k)
            continue
        if prod_root in env[k]:
            env[k] = env[k].replace(prod_root, scratch_root)
            redirected.append(k)
    env["SYNDICATE_REFRESH_STATE_BACKEND"] = "file"
    print(f"ENV_LOADED pid={pid} keys={len(env)} redirected_keys={sorted(redirected)}", flush=True)
    return env


class Recorder:
    """Wraps the per-draw helper. Groups consecutive calls that share the same kwargs objects into one game."""

    def __init__(self, out_dir: Path, league: str, date: str, entrypoint: str):
        self.out_dir, self.league, self.date, self.entrypoint = out_dir, league, date, entrypoint
        self.game: dict[str, Any] | None = None
        self.key: tuple | None = None
        self.n_games = self.n_calls = 0

    def _flush(self) -> None:
        if not self.game:
            return
        hp = self.game["kwargs"].get("home_players")
        ap = self.game["kwargs"].get("away_players")
        tag = f"{self.league}_{self.date}_{self.n_games:03d}_{len(hp) if hp is not None else 0}v{len(ap) if ap is not None else 0}"
        path = self.out_dir / f"{tag}.pkl"
        tmp = path.with_suffix(".tmp")
        with tmp.open("wb") as fh:
            pickle.dump(self.game, fh, protocol=4)
        tmp.replace(path)
        self.n_games += 1
        self.game, self.key = None, None

    def wrap(self, fn):
        def recording(**kwargs):
            rng = kwargs.get("rng")
            state = copy.deepcopy(rng.bit_generator.state)
            body = {k: v for k, v in kwargs.items() if k not in ("rng", "league_code")}
            key = tuple((k, id(v)) for k, v in sorted(body.items()))
            if key != self.key:
                self._flush()
                self.key = key
                self.game = {
                    "league": self.league,
                    "date": self.date,
                    "entrypoint": self.entrypoint,
                    "kwargs": copy.deepcopy(body),
                    "rng_states": [],
                    "output_digests": [],
                }
            out = fn(**kwargs)
            self.game["rng_states"].append(state)
            self.game["output_digests"].append(output_digest(out))
            self.n_calls += 1
            return out

        return recording

    def close(self) -> None:
        self._flush()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Record real production basketball engine calls for the parity gate.")
    ap.add_argument("--league", required=True, choices=("nba", "wnba"))
    ap.add_argument("--dates", required=True, help="comma-separated YYYY-MM-DD")
    ap.add_argument("--source-root", required=True, type=Path, help="SCRATCH copy of <league>_source")
    ap.add_argument("--out-dir", required=True, type=Path)
    ap.add_argument("--n-sims", type=int, default=200)
    ap.add_argument("--max-games", type=int, default=None)
    ap.add_argument("--env-from-pid", type=int, default=None)
    ap.add_argument("--prod-data-root", default="~/syndicate-prod/data")
    ap.add_argument("--scratch-data-root", default=None)
    ap.add_argument("--seed", type=int, default=None, help="fixed seed (also seeds the global numpy/random RNGs the quarter model draws from)")
    ap.add_argument("--no-record", action="store_true", help="run the sim only (end-to-end A/B arm), record no corpus")
    ap.add_argument("--out-prefix", default="engine_corpus")
    args = ap.parse_args(argv)

    source_root = args.source_root.expanduser().resolve()
    prod = str(Path(args.prod_data_root).expanduser().resolve())
    if str(source_root).startswith(prod):
        raise SystemExit(f"REFUSED: --source-root {source_root} is inside the production data root; use a scratch copy")
    if args.env_from_pid is not None:
        if not args.scratch_data_root:
            raise SystemExit("--env-from-pid needs --scratch-data-root")
        env = load_role_env(args.env_from_pid, prod_root=prod, scratch_root=args.scratch_data_root)
        os.environ.clear()
        os.environ.update(env)

    from syndicate.features.shared import basketball_props_smart_sim as bps

    out_dir = args.out_dir.expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    summary: list[dict[str, Any]] = []
    for date in [d.strip() for d in args.dates.split(",") if d.strip()]:
        rec = Recorder(out_dir, args.league, date, "simulate_pbp_game_boxscore")
        original = bps._simulate_pbp_game_boxscore_local
        if not args.no_record:
            bps._simulate_pbp_game_boxscore_local = rec.wrap(original)
        if args.seed is not None:
            # The quarter model draws from the GLOBAL numpy RNG (it takes no rng); seed both, as
            # scripts/ab_basketball_sim_anchor.py does, so two arms differ only in the code under test.
            import random

            import numpy as np

            np.random.seed(int(args.seed))
            random.seed(int(args.seed))
        started = time.time()
        try:
            result = bps._smart_sim_run_date_local(
                processed_root=source_root / "data" / "processed",
                raw_root=source_root / "data" / "raw",
                date_str=date,
                n_sims=int(args.n_sims),
                seed=args.seed,
                max_games=args.max_games,
                overwrite=True,
                pbp=True,
                workers=1,
                roster_mode=bps._resolve_smart_sim_roster_mode_local(date_str=date, roster_mode="historical"),
                out_prefix=str(args.out_prefix),
                league_code=args.league,
            )
        finally:
            bps._simulate_pbp_game_boxscore_local = original
            rec.close()
        row = {"league": args.league, "date": date, "games_recorded": rec.n_games, "engine_calls": rec.n_calls, "elapsed_s": round(time.time() - started, 1)}
        try:
            row["run_summary"] = {k: v for k, v in dict(result or {}).items() if isinstance(v, (int, float, str, bool))}
        except Exception:
            pass
        print("CORPUS_DATE " + json.dumps(row), flush=True)
        summary.append(row)
    (out_dir / f"record_summary_{args.league}.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    if args.no_record:
        return 0 if all((r.get("run_summary") or {}).get("failures", 1) == 0 for r in summary) else 1
    return 0 if all(r["engine_calls"] > 0 for r in summary) else 1


if __name__ == "__main__":
    sys.exit(main())
