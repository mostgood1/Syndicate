"""todo #784 -- the OUTCOME GATE for a change to a `SYNDICATE_<LEAGUE>_LIVE_MECHANISMS` env value.

WHY THIS EXISTS, and it is one specific incident (learnings.md 2026-11-11, lane `ncaab-score-effect-load`).

On 2026-11-10 07:49:46Z NCAAB's live re-sim loaded RC46 (`score_effect_k` 0.005 + `possession_alternation` 1.0 +
`solver_endgame_pts_per_team` 0.46). The gate that chose it scored the margin's MEAN (point |err|) at most
checkpoints -- "the harness has no distribution to score" -- and the distribution only from 30 / 36 min, on the
2025-26 corpus. RC46 is mainly a WIDTH change, and live spreads and moneylines are priced off the re-sim's margin
DISTRIBUTION from the tip on (`live_gameline_join._two_way_home_prob`). Replayed on 240 rated 2026-27 games and scored
on the finals, totals tied and win Brier was worse beyond 1.96 SE at 20 m (+0.011 +- 0.009) and 36 m
(+0.007 +- 0.005). It was reverted at 22:56:28Z, six minutes before the slate's first live game. The registered
post-load reading -- an effect ratio -- came back NOT FALSIFIED. Nothing in the process asked the outcome question.

WHAT IT DOES. Re-sims the CURRENT season's completed games from their real play-by-play state on two values of the
league's mechanisms key -- the one running now and the candidate -- with the SAME seeds (production's own
`stable_seed`), production's own inputs (`ncaab/live_resim.build_engine_inputs`, the dated team and player priors the
fleet serves) and the replay harness's state (`state_at` / `resume_game_state`). At every checkpoint the live pricing
reads (tip, 10, 20, 30, 36 min for NCAAB) it scores both arms against the real finals:

  margin:  CRPS, |central-80% coverage - 0.80|          (spreads and moneylines read this distribution)
  total:   CRPS, |central-80% coverage - 0.80|          (totals are served raw from the sim)
  win:     Brier and log loss of the result's home_win_prob

paired candidate - current over games, with 1.96 x bootstrap SE (1000 draws, seed 13). Every metric is
lower-is-better; a cell is WORSE when its lower bound is above 0 and BETTER when its upper bound is below 0. Coverage is
scored as distance from nominal, not as "higher", because the 7-field config over-covers (0.83-0.91) and RC46 under-
covers (0.69-0.83): neither direction is good by itself.

THE RECEIPT. `<main tree>/.syndicate/deploy/outcome_gate/<league>__<candidate12>__<current12>.json`, keyed on the
sha256 of the canonical JSON of each value, so it names the exact TRANSITION. `deploy_preflight.py` reads it (through
`check_receipt` below -- one source for the predicate, the same file on both sides) and returns OUTCOME_GATE when a
changed key has no fresh receipt, too few games, or WORSE cells not explicitly accepted.

Run it ON THE FLEET (WSL), at nice 19, from a worktree at origin/main with the fleet's venv:

    nice -n 19 ~/.venvs/syndicate/bin/python scripts/live_mechanism_outcome_gate.py --league ncaab \\
        --candidate-file /path/candidate.json --current-from-role live-odds-worker \\
        --dates 2026-11-03..2026-11-09 --data-root ~/syndicate-prod/data

The half-split and exact-target switches are copied from the running role's environ (booleans; nothing else is read).
Values are printed: a mechanisms value is engine config, not a secret. Exit 0 = receipt written with no WORSE cell,
1 = receipt written WITH worse cells, 2 = no receipt (too few games, bad value, unsupported league).

Read-only against production: reads the fleet's data root and one process's environ, writes only the receipt.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

REPO = Path(__file__).resolve().parents[1]

# Every league whose mechanisms key this gate can replay. A key for a league not listed here (NBA today:
# `SYNDICATE_NBA_LIVE_MECHANISMS` runs through a different engine path) gets NO receipt, so preflight refuses it until
# the gate is extended or the operator waives with a reason -- never a silent pass.
LEAGUES: dict[str, dict[str, Any]] = {
    "ncaab": {
        "env_key": "SYNDICATE_NCAAB_LIVE_MECHANISMS",
        "switch_keys": ("SYNDICATE_NCAAB_HALF_SPLIT", "SYNDICATE_NCAAB_EXACT_TARGET"),
        "role": "live-odds-worker",
        "worker_script": "scripts/run_live_odds_refresh_worker.py",
        # Elapsed game seconds. Live NCAAB spreads, moneylines and totals are priced at every state from the tip.
        "checkpoints": {"0m": 0.0, "10m": 600.0, "20m": 1200.0, "30m": 1800.0, "36m": 2160.0},
    },
}

# The floor on scored games, enforced by PREFLIGHT as well as here so `--min-games 1` cannot satisfy it. Measured on
# the RC46 replays: 240 games gave win-Brier SEs of +-0.005..0.009, enough to resolve RC46's +0.007..0.011; 54 games
# (one slate) gave +-0.006..0.025, which cannot. 150 sits between them.
MIN_GAMES = 150
# A receipt describes a population and code at one time; past this age the season has moved under it.
MAX_RECEIPT_AGE_SECONDS = 7 * 24 * 3600
RECEIPT_SUBDIR = Path(".syndicate") / "deploy" / "outcome_gate"
COVERAGE_NOMINAL = 0.80
METRICS = ("margin_crps", "margin_cov80_dev", "total_crps", "total_cov80_dev", "win_brier", "win_logloss")
_KEY_RE = re.compile(r"^SYNDICATE_([A-Z0-9]+)_LIVE_MECHANISMS$")


# --------------------------------------------------------------------------------------------------------------------
# Shared with deploy_preflight.py. Stdlib only: preflight loads this module on Windows without the engine.
# --------------------------------------------------------------------------------------------------------------------

def canonical_value(raw: Any) -> str:
    """One spelling per VALUE: JSON is re-serialised with sorted keys and no whitespace; empty / unset is ''."""
    text = str(raw or "").strip()
    if not text:
        return ""
    try:
        return json.dumps(json.loads(text), sort_keys=True, separators=(",", ":"))
    except ValueError:
        return text


def value_hash(raw: Any) -> str:
    return hashlib.sha256(canonical_value(raw).encode("utf-8")).hexdigest()


def league_of_key(key: str) -> Optional[str]:
    match = _KEY_RE.match(str(key or ""))
    return match.group(1).lower() if match else None


def receipt_name(league: str, candidate_hash: str, current_hash: str) -> str:
    return f"{league}__{candidate_hash[:12]}__{current_hash[:12]}.json"


def root_from_gitfile(text: str, repo: Path, windows: bool) -> Optional[Path]:
    """The primary checkout from a worktree's `.git` FILE (`gitdir: <main>/.git/worktrees/<name>`).

    WHY NOT GIT: the gate runs in WSL from a worktree Windows git created, whose `.git` file says `gitdir: C:/...`.
    WSL git cannot follow that (measured 2026-11-11: `rev-parse --git-common-dir` rc=128), and falling back to the
    worktree would put the receipt where preflight -- which reads the PRIMARY tree, on Windows -- never looks."""
    match = re.match(r"^\s*gitdir:\s*(.+?)\s*$", text or "", re.M)
    if not match:
        return None
    raw = match.group(1)
    drive = re.match(r"^([A-Za-z]):[\\/](.*)$", raw)
    if drive and not windows:
        raw = f"/mnt/{drive.group(1).lower()}/" + drive.group(2).replace("\\", "/")
    # Absolute by its spelling, not by this platform's Path rules (a /mnt/c path is not "absolute" on Windows).
    absolute = raw.startswith("/") or bool(re.match(r"^[A-Za-z]:[\\/]", raw))
    gitdir = Path(raw) if absolute else (repo / raw).resolve()
    if gitdir.parent.name == "worktrees" and gitdir.parent.parent.name == ".git":
        return gitdir.parent.parent.parent
    return None


def main_tree_root(start: Path = REPO) -> Path:
    """The primary checkout, where deploy-guard and preflight read (deploy_preflight._main_worktree_root's rule)."""
    dot_git = start / ".git"
    if dot_git.is_file():
        try:
            found = root_from_gitfile(dot_git.read_text(encoding="utf-8", errors="replace"), start,
                                      sys.platform.startswith("win"))
        except OSError:
            found = None
        if found is not None and found.is_dir():
            return found
    for args in (["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
                 ["git", "rev-parse", "--git-common-dir"]):
        try:
            done = subprocess.run(args, cwd=str(start), capture_output=True, text=True, timeout=15)
        except Exception:  # noqa: BLE001
            continue
        raw = (done.stdout or "").strip()
        if done.returncode != 0 or not raw:
            continue
        common = Path(raw)
        if not common.is_absolute():
            common = (start / common).resolve()
        if common.name == ".git" and common.parent.is_dir():
            return common.parent
    return start


def receipt_dir(root: Optional[Path] = None) -> Path:
    return (root or main_tree_root()) / RECEIPT_SUBDIR


def check_receipt(directory: Path, league: str, candidate_hash: str, current_hash: str, now: float,
                  accept_regression: str = "") -> tuple[Optional[str], dict]:
    """(problem or None, detail) for one changed key. Pure apart from reading the one file it names.

    Refuses on: no receipt for this exact transition; unreadable; a hash inside that does not match (a renamed
    file); older than MAX_RECEIPT_AGE_SECONDS or stamped in the future; fewer than MIN_GAMES scored; WORSE cells
    without `accept_regression`. Each refusal names its remedy."""
    path = Path(directory) / receipt_name(league, candidate_hash, current_hash)
    detail: dict[str, Any] = {"receipt": str(path), "league": league,
                              "candidate_hash": candidate_hash[:12], "current_hash": current_hash[:12]}
    if league not in LEAGUES:
        return (f"no outcome replay exists for league {league!r} (the gate replays {sorted(LEAGUES)}); extend "
                f"scripts/live_mechanism_outcome_gate.py or waive with --no-outcome-gate \"<reason>\""), detail
    if not path.is_file():
        return (f"no outcome-gate receipt for {league} {current_hash[:12]} -> {candidate_hash[:12]}: run "
                f"scripts/live_mechanism_outcome_gate.py on the fleet for this exact transition"), detail
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 -- unreadable is not a pass
        return f"outcome-gate receipt {path.name} is unreadable ({type(exc).__name__})", detail
    if receipt.get("candidate_hash") != candidate_hash or receipt.get("current_hash") != current_hash:
        return f"outcome-gate receipt {path.name} names a different transition than its file name", detail
    written = receipt.get("written_at")
    age = (now - float(written)) if isinstance(written, (int, float)) else None
    detail.update(written_at_iso=receipt.get("written_at_iso"), games=receipt.get("games"),
                  worse=receipt.get("worse") or [], better=receipt.get("better") or [])
    if age is None or age < -120:
        return f"outcome-gate receipt {path.name} has no readable written_at", detail
    detail["age_hours"] = round(age / 3600, 1)
    if age > MAX_RECEIPT_AGE_SECONDS:
        return (f"outcome-gate receipt {path.name} is {age / 86400:.1f} days old (limit "
                f"{MAX_RECEIPT_AGE_SECONDS // 86400}); re-run it on this season's games"), detail
    games = receipt.get("games")
    if not isinstance(games, int) or games < MIN_GAMES:
        return (f"outcome-gate receipt {path.name} scored {games} games (floor {MIN_GAMES}); widen --dates"), detail
    worse = receipt.get("worse") or []
    if worse and not str(accept_regression or "").strip():
        return ("the candidate scores WORSE beyond 1.96 SE on " + ", ".join(worse) + " (" + path.name + "). "
                "Do not load it, or accept with --accept-outcome-regression \"<reason>\""), detail
    if worse:
        detail["accepted_regression"] = str(accept_regression).strip()
    return None, detail


# --------------------------------------------------------------------------------------------------------------------
# Scoring. numpy only, imported inside, so the shared block above stays importable without it.
# --------------------------------------------------------------------------------------------------------------------

def _crps(samples: Iterable[float], y: float) -> float:
    import numpy as np

    x = np.sort(np.asarray(list(samples), float))
    n = len(x)
    return float(np.mean(np.abs(x - y)) - np.sum((2 * np.arange(1, n + 1) - n - 1) * x) / (n * n))


def game_features(cp: Mapping[str, Any], final_home: int, final_away: int) -> dict[str, float]:
    """Per game x checkpoint x arm. `cp` holds `rows` ([home window, away window, home OT, away OT] per sim), the
    score at the checkpoint (`h0`, `a0`) and the result's `home_win_prob`."""
    import numpy as np

    rows = np.asarray(cp["rows"], float)
    h0, a0 = float(cp.get("h0") or 0), float(cp.get("a0") or 0)
    margin = (h0 - a0) + rows[:, 0] - rows[:, 1] + rows[:, 2] - rows[:, 3]
    total = (h0 + a0) + rows[:, 0] + rows[:, 1] + rows[:, 2] + rows[:, 3]
    real_margin, real_total = final_home - final_away, final_home + final_away
    lo_m, hi_m = np.quantile(margin, [0.1, 0.9])
    lo_t, hi_t = np.quantile(total, [0.1, 0.9])
    p = min(max(float(cp["home_win_prob"]), 1e-3), 1 - 1e-3)
    win = 1.0 if final_home > final_away else 0.0
    return {
        "margin_crps": _crps(margin, real_margin),
        "margin_in80": float(lo_m <= real_margin <= hi_m),
        "total_crps": _crps(total, real_total),
        "total_in80": float(lo_t <= real_total <= hi_t),
        "win_brier": (p - win) ** 2,
        "win_logloss": -(win * np.log(p) + (1 - win) * np.log(1 - p)),
        "margin_sd": float(margin.std()),
        "margin_err": float(real_margin - margin.mean()),
        # The MEANS, reported as shifts (not scored): totals are served raw from the sim's mean, so a candidate that
        # moves the mean total moves every priced total, whether or not CRPS can resolve it.
        "total_mean": float(total.mean()),
        "margin_mean": float(margin.mean()),
    }


def score_cells(paired: Mapping[str, Mapping[str, Mapping[str, Mapping[str, float]]]], checkpoints: Iterable[str],
                draws: int = 1000, seed: int = 13) -> dict[str, dict[str, dict[str, float]]]:
    """paired[game][cp][arm] -> features (arm in {current, candidate}). Returns cells[cp][metric] with the arm means,
    the paired difference and its 1.96 x bootstrap SE. Coverage cells score |coverage - 0.80| per draw."""
    import numpy as np

    cells: dict[str, dict[str, dict[str, float]]] = {}
    for cp in checkpoints:
        games = sorted(g for g, by_cp in paired.items()
                       if cp in by_cp and {"current", "candidate"} <= set(by_cp[cp]))
        if not games:
            continue
        n = len(games)
        idx = np.random.default_rng(seed).integers(0, n, size=(draws, n))
        keys = ["margin_crps", "margin_in80", "total_crps", "total_in80", "win_brier", "win_logloss", "margin_sd",
                "margin_err"]
        has_means = all("total_mean" in paired[g][cp][arm] for g in games for arm in ("current", "candidate"))
        if has_means:
            keys += ["total_mean", "margin_mean"]
        col = {arm: {k: np.array([paired[g][cp][arm][k] for g in games], float) for k in keys}
               for arm in ("current", "candidate")}
        out: dict[str, dict[str, float]] = {"_n": {"games": float(n)}}
        for metric in METRICS:
            if metric.endswith("_cov80_dev"):
                base = "margin_in80" if metric.startswith("margin") else "total_in80"
                cur, cand = col["current"][base], col["candidate"][base]
                point = abs(cand.mean() - COVERAGE_NOMINAL) - abs(cur.mean() - COVERAGE_NOMINAL)
                boot = np.abs(cand[idx].mean(axis=1) - COVERAGE_NOMINAL) - np.abs(cur[idx].mean(axis=1) - COVERAGE_NOMINAL)
                out[metric] = {"current": float(abs(cur.mean() - COVERAGE_NOMINAL)),
                               "candidate": float(abs(cand.mean() - COVERAGE_NOMINAL)),
                               "current_coverage": float(cur.mean()), "candidate_coverage": float(cand.mean()),
                               "diff": float(point), "se196": float(1.96 * boot.std())}
            else:
                cur, cand = col["current"][metric], col["candidate"][metric]
                d = cand - cur
                out[metric] = {"current": float(cur.mean()), "candidate": float(cand.mean()),
                               "diff": float(d.mean()), "se196": float(1.96 * d[idx].mean(axis=1).std())}
        out["_info"] = {"margin_sd_current": float(col["current"]["margin_sd"].mean()),
                        "margin_sd_candidate": float(col["candidate"]["margin_sd"].mean()),
                        "resid_sd_current": float(col["current"]["margin_err"].std()),
                        "resid_sd_candidate": float(col["candidate"]["margin_err"].std())}
        if has_means:
            for name in ("total_mean", "margin_mean"):
                d = col["candidate"][name] - col["current"][name]
                out["_info"][f"{name}_shift"] = float(d.mean())
                out["_info"][f"{name}_shift_se196"] = float(1.96 * d[idx].mean(axis=1).std())
        cells[cp] = out
    return cells


def flag_cells(cells: Mapping[str, Mapping[str, Mapping[str, float]]]) -> tuple[list[str], list[str]]:
    """(worse, better) as `cp:metric` labels. Every metric is lower-is-better."""
    worse, better = [], []
    for cp, by_metric in cells.items():
        for metric in METRICS:
            cell = by_metric.get(metric)
            if not cell:
                continue
            if cell["diff"] - cell["se196"] > 0:
                worse.append(f"{cp}:{metric}")
            elif cell["diff"] + cell["se196"] < 0:
                better.append(f"{cp}:{metric}")
    return worse, better


def write_receipt(directory: Path, payload: Mapping[str, Any]) -> Path:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / receipt_name(payload["league"], payload["candidate_hash"], payload["current_hash"])
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)
    return path


# --------------------------------------------------------------------------------------------------------------------
# The replay (fleet only: production's engine, the fleet's data root, a forked pool).
# --------------------------------------------------------------------------------------------------------------------

def role_environ(worker_script: str, keys: Iterable[str]) -> dict[str, str]:
    """The running worker's values for `keys` only, from /proc. Raises when the worker cannot be found or read."""
    wanted = set(keys)
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        try:
            cmd = (proc / "cmdline").read_bytes().replace(b"\0", b" ").decode("utf-8", "replace")
        except OSError:
            continue
        if "python" not in cmd or worker_script not in cmd:
            continue
        out: dict[str, str] = {}
        for item in (proc / "environ").read_bytes().split(b"\0"):
            key, sep, value = item.decode("utf-8", "replace").partition("=")
            if sep and key in wanted:
                out[key] = value
        return out
    raise RuntimeError(f"no running process for {worker_script}")


def _season(date: str) -> int:
    day = dt.date.fromisoformat(date)
    return day.year + 1 if day.month >= 7 else day.year  # ESPN's season is the year it ends


def expand_dates(spec: str) -> list[str]:
    out: list[str] = []
    for part in [p.strip() for p in str(spec).split(",") if p.strip()]:
        if ".." in part:
            lo, hi = (dt.date.fromisoformat(x) for x in part.split(".."))
            while lo <= hi:
                out.append(lo.isoformat())
                lo += dt.timedelta(days=1)
        else:
            out.append(dt.date.fromisoformat(part).isoformat())
    return out


_HARNESS = None


def _harness():
    global _HARNESS
    if _HARNESS is None:
        import importlib.util

        sys.path.insert(0, str(REPO))
        spec = importlib.util.spec_from_file_location("bbi_outcome_gate", REPO / "scripts" / "backtest_basketball_intervals.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        _HARNESS = module
    return _HARNESS


def ncaab_tasks(data_root: Path, date: str) -> tuple[list[dict], dict]:
    """Completed men's D1 games of one date with matched finals, play-by-play and the ids production priced."""
    import csv

    s = _harness()
    season = _season(date)
    games_csv = data_root / "ncaab_source" / "data" / "processed" / "rotation_stints" / f"games_{date}.csv"
    pregame_path = data_root / "ncaab_source" / "data" / "pregame_sim" / f"pregame_sim_{date}.json"
    cov = {"table_rows": 0, "score_match": 0, "events": 0, "priced_ids": 0}
    if not games_csv.is_file() or not pregame_path.is_file():
        cov["missing"] = [p.name for p in (games_csv, pregame_path) if not p.is_file()]
        return [], cov
    pregame = (json.loads(pregame_path.read_text(encoding="utf-8")) or {}).get("games") or {}
    box = s.read_box(data_root, "ncaab", date)
    tasks = []
    with games_csv.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            cov["table_rows"] += 1
            if str(row.get("score_match")) != "1" or str(row.get("season")) != str(season):
                continue
            cov["score_match"] += 1
            events = s.events_path(data_root, "ncaab", season, row["event_id"])
            if not events.is_file():
                continue
            cov["events"] += 1
            p = pregame.get(str(row["event_id"]))
            if not p:
                continue
            cov["priced_ids"] += 1
            tasks.append({"league": "ncaab", "game_id": str(row["event_id"]), "date": date,
                          "phase": row.get("season_type") or "", "season": season, "events_path": str(events),
                          "final": {"home": row.get("official_home"), "away": row.get("official_away")},
                          "game_row": row, "box_rows": box.get(str(row["event_id"]), []),
                          "team_ids": {"home": str(p["home"]["espn_id"]), "away": str(p["away"]["espn_id"])},
                          "neutral": bool(p.get("neutral_site")),
                          "codes": {"home": str(p["home"].get("abbr") or ""), "away": str(p["away"].get("abbr") or "")}})
    return tasks, cov


def _replay_one(job) -> dict:
    task, arm, value, checkpoints, sims = job
    try:
        return _replay_ncaab(task, arm, value, checkpoints, sims)
    except Exception:  # noqa: BLE001 -- a failed game is reported, never silently dropped
        return {"game_id": task["game_id"], "arm": arm, "error": traceback.format_exc()[-1200:]}


def _replay_ncaab(task, arm, value, checkpoints, sims) -> dict:
    from syndicate.features.basketball_engine.resume import GameState
    from syndicate.features.ncaab import live_resim as lr
    from syndicate.features.shared import basketball_interval_backtest as bib

    if value:
        os.environ[lr.LIVE_MECHANISMS_ENV] = value
    else:
        os.environ.pop(lr.LIVE_MECHANISMS_ENV, None)
    mech = lr.live_mechanisms_from_env()
    game = _harness().build_game(task)
    inputs = lr.build_engine_inputs(task["date"], task["team_ids"]["home"], task["team_ids"]["away"],
                                    neutral=task["neutral"], home_code=task["codes"]["home"],
                                    away_code=task["codes"]["away"])
    if isinstance(inputs, lr.NcaabResimRefusal):
        return {"game_id": task["game_id"], "arm": arm, "refusal": inputs.reason}
    cfg = inputs["cfg"]
    off = [k for k, v in mech.items() if getattr(cfg, k) != v]
    if off:  # the arm must actually reach the engine config, or the comparison is of nothing
        return {"game_id": task["game_id"], "arm": arm, "error": f"cfg does not carry {off}"}
    names: dict[str, str] = {}
    for frame in (inputs["home_players"], inputs["away_players"]):
        names.update({str(k): str(v) for k, v in zip(frame["athlete_id"], frame["player_name"])})
    engine = lr.ncaab_engine(league="ncaab")
    kwargs = {k: inputs[k] for k in lr._ENGINE_KWARGS}
    out = {"game_id": task["game_id"], "arm": arm, "final": task["final"], "mechanisms": sorted(mech), "cps": {}}
    for cp, t in checkpoints.items():
        if t <= 0:
            state_obj, h0, a0, seed_key = GameState(), 0, 0, 0
        else:
            state = bib.state_at(game, t)
            state_obj, _ = bib.resume_game_state(game, state, names, with_floor=True)
            h0, a0, seed_key = int(state.home_score), int(state.away_score), int(round(state.elapsed))
        rows: list[list[int]] = []

        def simulate(rng, g, h0=h0, a0=a0, rows=rows):
            hb, ab, hq, aq = engine.simulate_pbp_game_boxscore(rng=rng, **kwargs, state=g)
            rows.append([int(sum(hq[:2])) - h0, int(sum(aq[:2])) - a0, lr._ot_points(hb), lr._ot_points(ab)])
            return hb, ab, hq, aq

        res = lr.resim_live_game(inputs, state_obj, sims=sims, base_seed=lr.stable_seed(task["game_id"], seed_key, "ncaab"),
                                 simulate=simulate, league="ncaab")
        if isinstance(res, lr.NcaabResimRefusal):
            out["cps"][cp] = {"refusal": res.reason}
            continue
        out["cps"][cp] = {"rows": rows, "h0": h0, "a0": a0, "home_win_prob": res["home_win_prob"]}
    return out


def run_replay(league: str, values: Mapping[str, str], dates: list[str], data_root: Path, sims: int, procs: int,
               log=print) -> tuple[dict, dict]:
    """(paired features[game][cp][arm], coverage). Same seeds on both arms (common random numbers)."""
    from multiprocessing import get_context

    spec = LEAGUES[league]
    tasks, coverage = [], {}
    for date in dates:
        got, cov = ncaab_tasks(data_root, date)
        coverage[date] = cov
        tasks += got
    log(f"tasks {len(tasks)} over {len(dates)} dates")
    jobs = [(t, arm, values[arm], spec["checkpoints"], sims) for t in tasks for arm in ("current", "candidate")]
    paired: dict[str, dict[str, dict[str, dict[str, float]]]] = {}
    notes: dict[str, int] = {}
    with get_context("fork").Pool(procs) as pool:
        for i, res in enumerate(pool.imap_unordered(_replay_one, jobs), 1):
            if "error" in res or "refusal" in res:
                key = f"{res['arm']}:{res.get('refusal') or 'error'}"
                notes[key] = notes.get(key, 0) + 1
                if "error" in res and notes[key] <= 3:
                    log(f"ERROR {res['game_id']} {res['arm']}: {res['error'][-400:]}")
                continue
            try:
                fh, fa = int(float(res["final"]["home"])), int(float(res["final"]["away"]))
            except (TypeError, ValueError, KeyError):
                notes["no_final"] = notes.get("no_final", 0) + 1
                continue
            for cp, data in res["cps"].items():
                if "rows" in data:
                    paired.setdefault(res["game_id"], {}).setdefault(cp, {})[res["arm"]] = game_features(data, fh, fa)
            if i % 50 == 0:
                log(f"{i}/{len(jobs)} game-arms done")
    coverage["_notes"] = notes
    return paired, coverage


def _git_head(path: Path) -> str:
    """The code commit the replay ran. From WSL a Windows worktree's `.git` file names a `C:/` gitdir that git
    cannot follow, so retry with the translated gitdir (the same translation as `root_from_gitfile`)."""
    commands = [["git", "rev-parse", "HEAD"]]
    dot_git = path / ".git"
    if dot_git.is_file():
        match = re.match(r"^\s*gitdir:\s*(.+?)\s*$", dot_git.read_text(encoding="utf-8", errors="replace"), re.M)
        drive = re.match(r"^([A-Za-z]):[\\/](.*)$", match.group(1)) if match else None
        if drive and not sys.platform.startswith("win"):
            gitdir = f"/mnt/{drive.group(1).lower()}/" + drive.group(2).replace("\\", "/")
            commands.append(["git", f"--git-dir={gitdir}", "rev-parse", "HEAD"])
    for command in commands:
        try:
            done = subprocess.run(command, cwd=str(path), capture_output=True, text=True, timeout=15)
        except Exception:  # noqa: BLE001
            continue
        if done.returncode == 0 and done.stdout.strip():
            return done.stdout.strip()
    return ""


def _read_value(text: Optional[str], path: Optional[str]) -> Optional[str]:
    if path:
        return Path(path).expanduser().read_text(encoding="utf-8").strip()
    return text


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--league", required=True)
    ap.add_argument("--candidate", help="the new value (JSON); '' means unset")
    ap.add_argument("--candidate-file")
    ap.add_argument("--current", help="the value running now; default: read from the running role")
    ap.add_argument("--current-file")
    ap.add_argument("--current-from-role", action="store_true", default=None,
                    help="read the current value (and the switches) from the running role's environ (default when "
                         "--current is not given)")
    ap.add_argument("--dates", required=True, help="YYYY-MM-DD, comma list or A..B ranges, of the CURRENT season")
    ap.add_argument("--data-root", default=os.environ.get("SYNDICATE_DATA_ROOT", ""))
    ap.add_argument("--sims", type=int, default=100)
    ap.add_argument("--procs", type=int, default=4)
    ap.add_argument("--min-games", type=int, default=MIN_GAMES)
    ap.add_argument("--receipt-dir", default="", help="default: <main tree>/.syndicate/deploy/outcome_gate")
    args = ap.parse_args(argv)

    league = args.league.lower()
    if league not in LEAGUES:
        print(f"REFUSE: no replay for league {league!r}; supported: {sorted(LEAGUES)}")
        return 2
    spec = LEAGUES[league]
    candidate = _read_value(args.candidate, args.candidate_file)
    if candidate is None:
        print("REFUSE: give --candidate or --candidate-file")
        return 2
    current = _read_value(args.current, args.current_file)
    switches: dict[str, str] = {}
    if current is None or args.current_from_role:
        try:
            env = role_environ(spec["worker_script"], (spec["env_key"], *spec["switch_keys"]))
        except Exception as exc:  # noqa: BLE001
            print(f"REFUSE: cannot read the running {spec['role']} ({type(exc).__name__}: {exc})")
            return 2
        if current is None:
            current = env.get(spec["env_key"], "")
        switches = {k: env[k] for k in spec["switch_keys"] if k in env}
    if not args.data_root:
        print("REFUSE: --data-root (or SYNDICATE_DATA_ROOT) is required: the fleet's data, never a checkout's mirror")
        return 2
    data_root = Path(args.data_root).expanduser()
    os.environ["SYNDICATE_DATA_ROOT"] = str(data_root)
    for key in spec["switch_keys"]:
        os.environ.pop(key, None)
    os.environ.update(switches)

    # Each value must parse to exactly its own fields: the parser turns ANY unknown field into {} (every mechanism
    # off), which would replay a different config than the one being loaded.
    sys.path.insert(0, str(REPO))
    from syndicate.features.ncaab import live_resim as lr

    for label, value in (("candidate", candidate), ("current", current)):
        try:
            want = json.loads(value) if canonical_value(value) else {}
        except ValueError:
            print(f"REFUSE: the {label} value is not JSON")
            return 2
        if not isinstance(want, dict):
            print(f"REFUSE: the {label} value is not a JSON object")
            return 2
        got = lr.live_mechanisms_from_env({spec["env_key"]: value})
        if len(got) != len(want):
            print(f"REFUSE: the {label} value parses to {len(got)} of its {len(want)} fields with this code")
            return 2
    if canonical_value(candidate) == canonical_value(current):
        print("REFUSE: candidate and current are the same value; there is no transition to score")
        return 2

    dates = expand_dates(args.dates)
    t0 = time.time()
    print(f"league {league} key {spec['env_key']} dates {dates[0]}..{dates[-1]} ({len(dates)}) sims {args.sims} "
          f"switches {sorted(switches)} code {_git_head(REPO)[:9]}", flush=True)
    print(f"current   {canonical_value(current) or '(unset)'}\ncandidate {canonical_value(candidate) or '(unset)'}", flush=True)
    paired, coverage = run_replay(league, {"current": current, "candidate": candidate}, dates, data_root,
                                  args.sims, args.procs, log=lambda m: print(m, flush=True))
    cps = list(spec["checkpoints"])
    cells = score_cells(paired, cps)
    games = min((int(cells[cp]["_n"]["games"]) for cp in cells), default=0)
    worse, better = flag_cells(cells)
    for cp in cps:
        if cp not in cells:
            continue
        c = cells[cp]
        print(f"\n### {cp}: {int(c['_n']['games'])} games | margin SD {c['_info']['margin_sd_current']:.2f} -> "
              f"{c['_info']['margin_sd_candidate']:.2f} | real SD of (final - mean) {c['_info']['resid_sd_current']:.2f} -> "
              f"{c['_info']['resid_sd_candidate']:.2f}")
        if "total_mean_shift" in c["_info"]:
            i = c["_info"]
            print(f"  mean shift (not scored): total {i['total_mean_shift']:+.3f} +- {i['total_mean_shift_se196']:.3f}"
                  f" | home margin {i['margin_mean_shift']:+.3f} +- {i['margin_mean_shift_se196']:.3f}")
        for metric in METRICS:
            m = c[metric]
            tag = ("  WORSE" if f"{cp}:{metric}" in worse else "  better" if f"{cp}:{metric}" in better else "")
            extra = (f" (coverage {m['current_coverage']:.3f} -> {m['candidate_coverage']:.3f})"
                     if "current_coverage" in m else "")
            print(f"  {metric:16s} {m['current']:.4f} -> {m['candidate']:.4f}  diff {m['diff']:+.4f} +- {m['se196']:.4f}{extra}{tag}")
    print(f"\nWORSE beyond 1.96 SE: {worse or 'none'}\nbetter beyond 1.96 SE: {better or 'none'}")
    if games < args.min_games or games < MIN_GAMES:
        print(f"NO RECEIPT: {games} games scored on every checkpoint, floor {max(args.min_games, MIN_GAMES)}. Widen --dates.")
        return 2
    payload = {
        "league": league, "env_key": spec["env_key"],
        "candidate_hash": value_hash(candidate), "current_hash": value_hash(current),
        "candidate": canonical_value(candidate), "current": canonical_value(current),
        "dates": dates, "games": games, "sims": args.sims, "checkpoints": spec["checkpoints"],
        "switches": {k: bool(str(v).strip()) for k, v in switches.items()},
        "code_commit": _git_head(REPO), "data_root": str(data_root),
        "coverage": coverage, "cells": cells, "worse": worse, "better": better,
        "written_at": time.time(),
        "written_at_iso": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "elapsed_seconds": round(time.time() - t0, 1),
    }
    path = write_receipt(Path(args.receipt_dir) if args.receipt_dir else receipt_dir(), payload)
    print(f"RECEIPT {path}")
    return 1 if worse else 0


if __name__ == "__main__":
    sys.exit(main())
