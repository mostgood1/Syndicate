"""Weekly backtests for the `model-scorecard` cron (lane `model-scorecard-cron`, 2026-09-17).

The cron runs from a FRESH CLONE of main: no persistent disk, no `.env`, 2 GB
RAM, `RENDER=true`, `ADMIN_TOKEN` in the environment. Every backtest that can
run under those conditions is run here, one at a time, each as its own
subprocess with a timeout, and the results land in one dated report:

    <out-dir>/weekly_backtests_<YYYY-MM-DD>.json   machine-readable
    <out-dir>/weekly_backtests_<YYYY-MM-DD>.md     one line per job
    <out-dir>/logs/<job>.stdout.log / .stderr.log  full output, token redacted
    <out-dir>/raw/<job>.json                       for scripts that write a file

WHY SUBPROCESSES. A backtest that leaks memory, hangs, or raises must cost only
its own row. Each child is reaped with `os.wait4` on POSIX, so `peak_rss_mb` is
the kernel's own high-water mark for that child -- the number that decides
whether a job fits a 2 GB plan -- not a sample.

WHY INPUTS ARE PULLED FIRST, BY THIS SCRIPT. The web service has OOM'd on bursts
of `/api/ops/artifacts/export` (JSON-encodes the whole file in memory). Inputs
come through `/api/ops/artifacts/stream` (send_file from disk) into a work dir,
ONE request at a time, with `--web-pause` between web-touching jobs. The Layer 2
opening ledger (~17.5 MB/day) is pulled once per date and graded per sport from
the file, instead of re-exporting it for every sport.

THE TOKEN travels in the child's ENVIRONMENT only, and only to jobs that need
it. It is never in argv, and every captured log, tail and the report itself are
scrubbed of it anyway.

Jobs (`--only` takes a job name or a family name; requirements are pulled in):

  layer2_inputs:<date>            openings + departures + game chips for a date
  layer2_scorecard:<date>:<sport> scripts/layer2_live_scorecard.py, per sport
  mlb_props                       scripts/backtest_mlb_props.py (vs constant baseline)
  ncaaf_inputs                    the player game-stats snapshot
  ncaaf_player_props              scripts/backtest_ncaaf_player_props.py
  wnba_projection                 scripts/backtest_wnba_projection.py
  nfl_pbp                         scripts/fetch_nfl_pbp.py (nflverse, not web)
  nfl_props                       scripts/backtest_nfl_props.py

NOT RUN: `scripts/grade_mlb_hitter_props_vs_market.py` (model vs market Brier).
It runs from a fresh clone given `--snapshots-dir`/`--batter-log`, but web has no
PREGAME hitter-prop odds to give it. The only allowlisted copy,
`daily/snapshots/<date>/oddsapi_hitter_props_*.json`, is the day's LAST live
refresh -- measured 2026-09-17: 09-16 was retrieved 04:30Z the next morning (13
players, home-run over-only) and 09-15 at 04:59Z (0 players), so both dates
scored nothing. A weekly job that cannot score only trains readers to skip
failures; it belongs here once a pregame source is readable.

Exit 0 when the report was written and at least one job succeeded; 2 when every
job failed, timed out or was skipped.

Usage:
  py -3 scripts/run_weekly_backtests.py --out-dir reports/weekly_backtests --dry-run
  py -3 scripts/run_weekly_backtests.py --out-dir out --only layer2_scorecard --dates 2
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNNER_VERSION = "weekly_backtests/1"
TOKEN_ENV = "ADMIN_TOKEN"
REDACTED = "***REDACTED***"
DEFAULT_BASE_URL = "https://syndicate-an21.onrender.com"
TAIL_CHARS = 3000

# Sports the opening ledger can carry. A sport with no records that date grades
# in about a second and reports `opportunities: 0`, which is itself the answer.
LAYER2_SPORTS: tuple[str, ...] = ("mlb", "nfl", "ncaaf", "wnba", "nhl", "nba", "ncaab", "soccer")
# The WNBA harness walks production's stored dates; the most recent N keeps the
# weekly run to N small CSV streams instead of every date ever stored.
WNBA_DATE_LIMIT = 30

OPENINGS_PATH = "reports/intelligence/clv_openings/{date}.jsonl"
DEPARTURES_PATH = "reports/intelligence/clv_departures/{date}.jsonl"
NCAAF_STATS_PATH = (
    "ncaaf_source/source_artifacts/data/processed/player_game_stats/ncaaf_player_game_stats_snapshot.csv"
)

try:
    from zoneinfo import ZoneInfo

    _CENTRAL: Any = ZoneInfo("America/Chicago")
except Exception:  # no tz data: fall back to CDT, off by an hour in winter only
    _CENTRAL = timezone(timedelta(hours=-5))


# ---------------------------------------------------------------------------
# plan
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Job:
    name: str
    family: str
    args: tuple[str, ...]  # argv after the interpreter
    needs_token: bool = False
    touches_web: bool = False
    requires: tuple[str, ...] = ()
    env: tuple[tuple[str, str], ...] = ()
    # (flag, path) appended only when `path` exists as the job starts -- e.g. a
    # departure log that web does not have for an older date.
    optional_file_args: tuple[tuple[str, str], ...] = ()
    json_source: str = "none"  # "stdout" | "marker" | "file" | "none"
    json_file: str | None = None


def central_today(now: datetime | None = None) -> date:
    moment = now or datetime.now(timezone.utc)
    return moment.astimezone(_CENTRAL).date()


def date_window(run_day: date, n_dates: int) -> list[str]:
    """The N Central dates BEFORE `run_day`, newest first. Today is excluded: its games are not final."""
    return [(run_day - timedelta(days=i)).isoformat() for i in range(1, max(1, n_dates) + 1)]


def football_season(run_day: date) -> int:
    return run_day.year if run_day.month >= 3 else run_day.year - 1


def _fetch_args(required: Sequence[tuple[str, str]] = (), optional: Sequence[tuple[str, str]] = (),
                chips: Sequence[tuple[str, str]] = ()) -> tuple[str, ...]:
    args: list[str] = ["scripts/run_weekly_backtests.py"]
    for source, dest in required:
        args += ["--fetch", source, dest]
    for source, dest in optional:
        args += ["--fetch-optional", source, dest]
    for day, dest in chips:
        args += ["--fetch-chips", day, dest]
    return tuple(args)


def build_plan(run_day: date, n_dates: int, work_dir: Path, out_dir: Path) -> list[Job]:
    dates = date_window(run_day, n_dates)
    newest = dates[0]
    season = football_season(run_day)
    raw_dir = out_dir / "raw"
    jobs: list[Job] = []

    for day in sorted(dates):
        base = work_dir / "layer2" / day
        openings, departures, chips = base / "openings.jsonl", base / "departures.jsonl", base / "chips.json"
        inputs = f"layer2_inputs:{day}"
        jobs.append(Job(
            name=inputs, family="layer2_inputs", needs_token=True, touches_web=True, json_source="stdout",
            args=_fetch_args(required=[(OPENINGS_PATH.format(date=day), str(openings))],
                             optional=[(DEPARTURES_PATH.format(date=day), str(departures))],
                             chips=[(day, str(chips))]),
        ))
        for sport in LAYER2_SPORTS:
            jobs.append(Job(
                name=f"layer2_scorecard:{day}:{sport}", family="layer2_scorecard", requires=(inputs,),
                json_source="stdout",
                args=("scripts/layer2_live_scorecard.py", "--date", day, "--sport", sport, "--json",
                      "--openings-file", str(openings), "--chips-file", str(chips)),
                optional_file_args=(("--departures-file", str(departures)),),
            ))

    jobs.append(Job(
        name="mlb_props", family="mlb_props", needs_token=True, touches_web=True, json_source="marker",
        args=("scripts/backtest_mlb_props.py", "--limit", str(len(dates)), "--end", newest),
    ))

    ncaaf_csv = work_dir / "ncaaf" / "ncaaf_player_game_stats_snapshot.csv"
    jobs.append(Job(
        name="ncaaf_inputs", family="ncaaf_inputs", needs_token=True, touches_web=True, json_source="stdout",
        args=_fetch_args(required=[(NCAAF_STATS_PATH, str(ncaaf_csv))]),
    ))
    jobs.append(Job(
        name="ncaaf_player_props", family="ncaaf_player_props", requires=("ncaaf_inputs",), json_source="stdout",
        args=("scripts/backtest_ncaaf_player_props.py", "--season", str(season), "--path", str(ncaaf_csv), "--json"),
    ))

    jobs.append(Job(
        name="wnba_projection", family="wnba_projection", needs_token=True, touches_web=True, json_source="marker",
        args=("scripts/backtest_wnba_projection.py", "--limit", str(WNBA_DATE_LIMIT)),
    ))

    # One root for the pbp WRITE (`nfl_artifact_output_root`, the env value) and
    # the READ (`player_stats._pbp_path` -> `default_nfl_source_root()`, candidate 0).
    # A root named `source_artifacts` makes both the same directory, and strict
    # hosted storage keeps a checkout's `data/nfl_source` from being preferred --
    # a fresh clone ships the `upcoming_recs_*.csv` that root selector probes for.
    nfl_data = work_dir / "nfl_data"
    nfl_env = (
        ("SYNDICATE_NFL_SOURCE_ROOT", str(nfl_data / "nfl_source" / "source_artifacts")),
        ("SYNDICATE_DATA_ROOT", str(nfl_data)),
        ("SYNDICATE_REQUIRE_HOSTED_STORAGE", "1"),
    )
    jobs.append(Job(
        name="nfl_pbp", family="nfl_pbp", env=nfl_env, json_source="stdout",
        args=("scripts/fetch_nfl_pbp.py", "--season", str(season), "--json"),
    ))
    nfl_json = raw_dir / "nfl_props.json"
    jobs.append(Job(
        name="nfl_props", family="nfl_props", env=nfl_env, requires=("nfl_pbp",), json_source="file",
        json_file=str(nfl_json),
        args=("scripts/backtest_nfl_props.py", "--seasons", f"{season - 1},{season}", "--out", str(nfl_json)),
    ))
    return jobs


def select_jobs(plan: Sequence[Job], only: Sequence[str]) -> list[Job]:
    """Jobs named (by name or family) plus everything they require, in plan order."""
    if not only:
        return list(plan)
    by_name = {job.name: job for job in plan}
    families = {job.family for job in plan}
    unknown = [item for item in only if item not in by_name and item not in families]
    if unknown:
        raise ValueError(f"unknown job(s) {unknown}; families: {sorted(families)}")
    wanted: set[str] = set()
    stack = [job.name for job in plan if job.name in only or job.family in only]
    while stack:
        name = stack.pop()
        if name in wanted:
            continue
        wanted.add(name)
        stack.extend(by_name[name].requires)
    return [job for job in plan if job.name in wanted]


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------


def redact(text: str, token: str | None) -> str:
    return text.replace(token, REDACTED) if token and text else text


def _safe_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", name)


def _wait_with_peak(proc: subprocess.Popen, timeout: float) -> tuple[int | None, bool, float | None, str | None]:
    """(exit_code, timed_out, peak_rss_mb, peak_rss_source)."""
    deadline = time.monotonic() + timeout
    if hasattr(os, "wait4"):
        # The kernel's high-water mark for exactly this child.
        while True:
            pid, status, usage = os.wait4(proc.pid, os.WNOHANG)
            if pid:
                code = os.waitstatus_to_exitcode(status)
                proc.returncode = code
                return code, False, _maxrss_mb(usage.ru_maxrss), "wait4"
            if time.monotonic() >= deadline:
                proc.kill()
                _, status, usage = os.wait4(proc.pid, 0)
                proc.returncode = os.waitstatus_to_exitcode(status)
                return None, True, _maxrss_mb(usage.ru_maxrss), "wait4"
            time.sleep(0.2)

    # Windows (local dev only): psutil's peak working set, sampled until exit.
    watcher = None
    try:
        import psutil  # type: ignore

        watcher = psutil.Process(proc.pid)
    except Exception:
        watcher = None
    peak: float | None = None
    source: str | None = None
    while True:
        if watcher is not None:
            try:
                info = watcher.memory_info()
                value = getattr(info, "peak_wset", None) or info.rss
                source = "psutil_peak_wset" if getattr(info, "peak_wset", None) else "psutil_rss_sampled"
                peak = max(peak or 0.0, value / (1024 * 1024))
            except Exception:
                pass
        try:
            code = proc.wait(timeout=0.25)
            return code, False, (round(peak, 1) if peak else None), source
        except subprocess.TimeoutExpired:
            if time.monotonic() >= deadline:
                proc.kill()
                proc.wait()
                return None, True, (round(peak, 1) if peak else None), source


def _maxrss_mb(raw: float) -> float:
    # Linux reports kilobytes, macOS bytes.
    return round(raw / (1024 * 1024) if sys.platform == "darwin" else raw / 1024, 1)


def _child_env(job: Job, token: str | None, work_dir: Path) -> dict[str, str]:
    env = dict(os.environ)
    env.pop(TOKEN_ENV, None)
    if job.needs_token and token:
        env[TOKEN_ENV] = token
    scratch = work_dir / "tmp"
    scratch.mkdir(parents=True, exist_ok=True)
    # Script caches key off TEMP; a per-run dir means no stale cache feeds a result.
    env["TEMP"] = env["TMP"] = str(scratch)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
    env.update(dict(job.env))
    return env


def run_job(job: Job, *, token: str | None, timeout: float, logs_dir: Path, work_dir: Path,
            python: str = sys.executable) -> dict[str, Any]:
    args = list(job.args)
    for flag, path in job.optional_file_args:
        if Path(path).is_file():
            args += [flag, path]
    argv = [python, *args]
    if token and any(token in part for part in argv):
        raise ValueError(f"{job.name}: the token must never be in argv")
    logs_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = logs_dir / f"{_safe_name(job.name)}.stdout.log"
    stderr_path = logs_dir / f"{_safe_name(job.name)}.stderr.log"
    if job.json_file:
        Path(job.json_file).parent.mkdir(parents=True, exist_ok=True)

    started = time.monotonic()
    with stdout_path.open("wb") as out, stderr_path.open("wb") as err:
        proc = subprocess.Popen(argv, cwd=str(REPO_ROOT), env=_child_env(job, token, work_dir),
                                stdout=out, stderr=err, stdin=subprocess.DEVNULL)
        code, timed_out, peak, peak_source = _wait_with_peak(proc, timeout)
    duration = round(time.monotonic() - started, 1)

    stdout = _read_redacted(stdout_path, token)
    stderr = _read_redacted(stderr_path, token)
    status = "timeout" if timed_out else ("ok" if code == 0 else "failed")
    parsed, parse_error = _parse_json(job, stdout)
    try:
        summary = SUMMARIZERS.get(job.family, _no_summary)(parsed, stdout)
    except Exception as exc:  # a summary bug must not change the job's status
        summary = {"summary_error": f"{type(exc).__name__}: {exc}"}
    if parse_error and job.json_source != "none":
        summary = {**summary, "json_error": parse_error}
    result: dict[str, Any] = {
        "name": job.name,
        "family": job.family,
        "command": redact(shlex.join(argv), token),
        "status": status,
        "exit_code": code,
        "duration_s": duration,
        "summary": summary,
        "stdout_tail": stdout[-TAIL_CHARS:],
        "stderr_tail": stderr[-TAIL_CHARS:],
        "stdout_log": str(stdout_path),
        "stderr_log": str(stderr_path),
    }
    if peak is not None:
        result["peak_rss_mb"] = peak
        result["peak_rss_source"] = peak_source
    return result


def _read_redacted(path: Path, token: str | None) -> str:
    text = path.read_bytes().decode("utf-8", errors="replace")
    if token and token in text:
        text = redact(text, token)
        path.write_text(text, encoding="utf-8")
    return text


def _parse_json(job: Job, stdout: str) -> tuple[Any, str | None]:
    try:
        if job.json_source == "stdout":
            return json.loads(stdout), None
        if job.json_source == "marker":
            marker = stdout.rfind("MEASURED_SKILL block")
            if marker < 0:
                return None, "no MEASURED_SKILL block in stdout"
            start = stdout.find("{", marker)
            return json.JSONDecoder().raw_decode(stdout[start:])[0], None
        if job.json_source == "file" and job.json_file:
            path = Path(job.json_file)
            if not path.is_file():
                return None, f"{path.name} was not written"
            return json.loads(path.read_text(encoding="utf-8")), None
    except (ValueError, OSError) as exc:
        return None, f"{type(exc).__name__}: {exc}"[:300]
    return None, None


def _skipped(job: Job, reason: str) -> dict[str, Any]:
    return {"name": job.name, "family": job.family, "command": shlex.join(["python", *job.args]),
            "status": "skipped", "exit_code": None, "duration_s": 0.0, "summary": {"reason": reason},
            "stdout_tail": "", "stderr_tail": ""}


def run_plan(jobs: Sequence[Job], *, token: str | None, timeout: float, out_dir: Path, work_dir: Path,
             web_pause: float = 0.0, python: str = sys.executable,
             log: Callable[[str], None] = lambda line: print(line, flush=True)) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    status_by_name: dict[str, str] = {}
    last_web_end: float | None = None
    for index, job in enumerate(jobs, 1):
        unmet = [name for name in job.requires if status_by_name.get(name) != "ok"]
        if unmet:
            result = _skipped(job, f"requirement not ok: {', '.join(unmet)}")
        elif job.needs_token and not token:
            result = _skipped(job, f"{TOKEN_ENV} is not set")
        else:
            if job.touches_web and last_web_end is not None and web_pause > 0:
                time.sleep(max(0.0, web_pause - (time.monotonic() - last_web_end)))
            log(f"[{index}/{len(jobs)}] {job.name} ...")
            try:
                result = run_job(job, token=token, timeout=timeout, logs_dir=out_dir / "logs",
                                 work_dir=work_dir, python=python)
            except Exception as exc:  # e.g. the interpreter could not be started
                result = {**_skipped(job, ""), "status": "failed",
                          "summary": {"runner_error": redact(f"{type(exc).__name__}: {exc}", token)}}
            if job.touches_web:
                last_web_end = time.monotonic()
        status_by_name[job.name] = result["status"]
        log(f"    -> {result['status']} exit={result.get('exit_code')} {result.get('duration_s')}s"
            + (f" peak={result['peak_rss_mb']}MB" if result.get("peak_rss_mb") is not None else ""))
        results.append(result)
    return results


# ---------------------------------------------------------------------------
# summaries: the headline numbers per script, read from its REAL output shape
# ---------------------------------------------------------------------------


def _no_summary(payload: Any, stdout: str) -> dict[str, Any]:
    return {}


def _colon_counts(stdout: str) -> dict[str, int]:
    """`  label padded : 123` lines, as the coverage blocks print them."""
    out: dict[str, int] = {}
    for match in re.finditer(r"^\s+([A-Za-z][^:\n]*?)\s*:\s*(\d+)\b", stdout, flags=re.MULTILINE):
        out[re.sub(r"\s+", " ", match.group(1)).strip()] = int(match.group(2))
    return out


def _summ_fetch(payload: Any, stdout: str) -> dict[str, Any]:
    files = (payload.get("files") or []) if isinstance(payload, Mapping) else []
    counts: dict[str, int] = {}
    for item in files:
        counts[item.get("status")] = counts.get(item.get("status"), 0) + 1
    return {"counts": counts, "bytes": sum(int(item.get("bytes") or 0) for item in files),
            "files": [{k: item.get(k) for k in ("source", "status", "bytes", "seconds", "error")} for item in files]}


def _summ_layer2(payload: Any, stdout: str) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        return {}
    phases = [{k: cell.get(k) for k in ("phase", "n", "graded", "games", "w_l_p", "units", "roi_pct", "gone10_pct")}
              for cell in (payload.get("tables") or {}).get("phase") or []]
    graded = sum(int(cell.get("graded") or 0) for cell in phases)
    units = round(sum(float(cell.get("units") or 0.0) for cell in phases), 3)
    return {
        "date": payload.get("date"), "sport": payload.get("sport"),
        "records_in": payload.get("records_in"), "opportunities": payload.get("opportunities"),
        "chips": payload.get("chips"), "finals": payload.get("finals"),
        "graded": graded, "units": units, "roi_pct": round(units / graded * 100.0, 2) if graded else None,
        "ungraded": payload.get("ungraded"),
        "departures_available": (payload.get("departures") or {}).get("available"),
        "phase": phases,
    }


def _oos_beats(block: Mapping[str, Any]) -> bool | None:
    oos = block.get("out_of_sample") or {}
    return oos.get("debiased_beats_baseline") if oos.get("available") else None


def _summ_mlb_props(payload: Any, stdout: str) -> dict[str, Any]:
    coverage = _colon_counts(stdout.split("PER-MARKET")[0])
    if not isinstance(payload, Mapping):
        return {"coverage": coverage}
    markets = {
        label: {"n": block.get("n"), "verdict": block.get("verdict"), "correlation": block.get("correlation"),
                "mae_model": block.get("mae_model"), "mae_constant_baseline": block.get("mae_constant_baseline"),
                "beats_constant_baseline": block.get("beats_constant_baseline"),
                "oos_debiased_beats_baseline": _oos_beats(block)}
        for label, block in (payload.get("markets") or {}).items()
    }
    return {"dates": payload.get("dates"), "player_games": payload.get("player_games"), "coverage": coverage,
            "beats_constant_baseline": [m for m, b in markets.items() if b.get("beats_constant_baseline")],
            "oos_debiased_beats_baseline": [m for m, b in markets.items() if b.get("oos_debiased_beats_baseline")],
            "markets": markets}


def _summ_nfl_pbp(payload: Any, stdout: str) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        return {}
    return {"results": [{k: item.get(k) for k in ("season", "status", "bytes", "reg_plays", "detail", "problems")}
                        for item in payload.get("results") or []]}


def _summ_nfl_props(payload: Any, stdout: str) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        return {"coverage": _colon_counts(stdout.split("SECTION 1")[0])}
    section1 = payload.get("section_1_point_accuracy") or {}
    point = {stat: {"n": b.get("n"), "verdict": b.get("verdict"), "correlation": b.get("correlation"),
                    "mae_model": b.get("mae_model"), "mae_constant_baseline": b.get("mae_constant_baseline"),
                    "oos_debiased_beats_baseline": _oos_beats(b)} for stat, b in section1.items()}
    ladder = {stat: {"n": b.get("n"), "brier": b.get("brier_score")}
              for stat, b in ((payload.get("section_2_ladder_calibration") or {}).get("markets") or {}).items()}
    return {"seasons": payload.get("seasons"), "coverage": payload.get("coverage"),
            "beats_constant_baseline": [s for s, b in section1.items() if b.get("beats_constant_baseline")],
            "point_accuracy": point, "ladder_brier": ladder,
            "real_market": (payload.get("section_3_real_market_hit_rate") or {}).get("markets")}


def _summ_ncaaf(payload: Any, stdout: str) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        return {}
    td = payload.get("anytime_td") or {}
    yardage = payload.get("yardage") or {}
    beats_both = [m for m, s in yardage.items()
                  if _lt(s.get("mae_model"), s.get("mae_player_mean")) and _lt(s.get("mae_model"), s.get("mae_base_rate"))]
    if _lt(td.get("brier_model"), td.get("brier_player_mean")) and _lt(td.get("brier_model"), td.get("brier_base_rate")):
        beats_both.append("Anytime TD")
    return {"season": payload.get("season"), "rows": payload.get("rows"), "players": payload.get("players"),
            "weeks_graded": payload.get("weeks_graded"), "anytime_td": td, "yardage": yardage,
            "beats_both_baselines": beats_both}


def _lt(a: Any, b: Any) -> bool:
    try:
        return math.isfinite(float(a)) and math.isfinite(float(b)) and float(a) < float(b)
    except (TypeError, ValueError):
        return False


def _summ_wnba(payload: Any, stdout: str) -> dict[str, Any]:
    coverage = _colon_counts(stdout.split("SIGN CHECK")[0])
    if not isinstance(payload, Mapping):
        refused = re.search(r"only (\d+) games carry a projection", stdout)
        return {"refused": bool(refused), "measurable_games": int(refused.group(1)) if refused else None,
                "coverage": coverage}
    pick = ("n", "correlation", "mae_model", "mae_constant_baseline", "mae_market_line",
            "beats_constant_baseline", "beats_market", "verdict")
    return {"refused": False, "games": payload.get("games"), "dates": payload.get("dates"), "coverage": coverage,
            "margins": {k: (payload.get("margins") or {}).get(k) for k in pick},
            "totals": {k: (payload.get("totals") or {}).get(k) for k in pick}}


SUMMARIZERS: dict[str, Callable[[Any, str], dict[str, Any]]] = {
    "layer2_inputs": _summ_fetch,
    "ncaaf_inputs": _summ_fetch,
    "layer2_scorecard": _summ_layer2,
    "mlb_props": _summ_mlb_props,
    "nfl_pbp": _summ_nfl_pbp,
    "nfl_props": _summ_nfl_props,
    "ncaaf_player_props": _summ_ncaaf,
    "wnba_projection": _summ_wnba,
}


def headline(result: Mapping[str, Any]) -> str:
    s = result.get("summary") or {}
    family = result.get("family")
    if result.get("status") == "skipped":
        return str(s.get("reason") or "")
    if family == "layer2_scorecard":
        phases = "; ".join(f"{c['phase']} {c['w_l_p']} roi {c['roi_pct']}" for c in s.get("phase") or [] if c.get("graded"))
        return f"opps {s.get('opportunities')}, graded {s.get('graded')}, units {s.get('units')}, roi {s.get('roi_pct')}% ({phases or 'none graded'})"
    if family in ("layer2_inputs", "ncaaf_inputs"):
        return f"{s.get('counts')} {round((s.get('bytes') or 0) / 1e6, 1)} MB"
    if family == "mlb_props":
        return (f"player-games {s.get('player_games')}; beats baseline: {s.get('beats_constant_baseline')}; "
                f"OOS de-biased beats: {s.get('oos_debiased_beats_baseline')}")
    if family == "nfl_pbp":
        return "; ".join(f"{r.get('season')}: {r.get('status')} {round((r.get('bytes') or 0) / 1e6, 1)} MB"
                         for r in s.get("results") or [])
    if family == "nfl_props":
        return f"rows {(s.get('coverage') or {}).get('player_game_weeks')} player-weeks; beats baseline: {s.get('beats_constant_baseline')}"
    if family == "ncaaf_player_props":
        return (f"season {s.get('season')} weeks {s.get('weeks_graded')}; anytime_td n {(s.get('anytime_td') or {}).get('n')}; "
                f"beats both baselines: {s.get('beats_both_baselines')}")
    if family == "wnba_projection":
        if s.get("refused"):
            return f"REFUSED: {s.get('measurable_games')} games carry a projection"
        return f"games {s.get('games')}; margin: {(s.get('margins') or {}).get('verdict')}; total: {(s.get('totals') or {}).get('verdict')}"
    return ""


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------


def _finite(value: Any) -> Any:
    """NaN/inf -> None, so the report is strict JSON (the NCAAF script emits NaN for empty cells)."""
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Mapping):
        return {k: _finite(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_finite(v) for v in value]
    return value


def build_report(results: Sequence[Mapping[str, Any]], *, run_day: date, dates: Sequence[str]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for result in results:
        counts[result["status"]] = counts.get(result["status"], 0) + 1
    return _finite({
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "runner_version": RUNNER_VERSION,
        "run_date": run_day.isoformat(),
        "dates": list(dates),
        "counts": counts,
        "jobs": list(results),
    })


def render_markdown(report: Mapping[str, Any]) -> str:
    dates = report.get("dates") or []
    lines = [
        f"# Weekly backtests {report['run_date']}",
        "",
        f"generated {report['generated_at']} | {report['runner_version']} | dates "
        f"{min(dates) if dates else '-'}..{max(dates) if dates else '-'} | {report.get('counts')}",
        "",
        "| job | status | exit | secs | peak MB | headline |",
        "|---|---|---|---|---|---|",
    ]
    quiet: list[str] = []
    for job in report["jobs"]:
        summary = job.get("summary") or {}
        if job.get("family") == "layer2_scorecard" and job.get("status") == "ok" and not summary.get("opportunities"):
            quiet.append(job["name"].split(":", 1)[1])
            continue
        cell = headline(job).replace("|", "/")
        lines.append(f"| {job['name']} | {job['status']} | {job.get('exit_code')} | {job.get('duration_s')} | "
                     f"{job.get('peak_rss_mb', '')} | {cell} |")
    if quiet:
        lines += ["", f"Layer 2 runs with zero opportunities ({len(quiet)}): {', '.join(quiet)}"]
    return "\n".join(lines) + "\n"


def write_report(report: Mapping[str, Any], out_dir: Path, token: str | None) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"weekly_backtests_{report['run_date']}"
    json_path, md_path = out_dir / f"{stem}.json", out_dir / f"{stem}.md"
    json_path.write_text(redact(json.dumps(report, indent=1, default=str), token), encoding="utf-8")
    md_path.write_text(redact(render_markdown(report), token), encoding="utf-8")
    return json_path, md_path


# ---------------------------------------------------------------------------
# fetch mode: the runner's own input pull, run as a child job
# ---------------------------------------------------------------------------


def _download(url: str, dest: Path, headers: Mapping[str, str], timeout: float) -> int:
    dest.parent.mkdir(parents=True, exist_ok=True)
    partial = dest.with_name(dest.name + ".part")
    size = 0
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=dict(headers)), timeout=timeout) as response, \
                partial.open("wb") as handle:
            while True:
                chunk = response.read(1 << 20)
                if not chunk:
                    break
                handle.write(chunk)
                size += len(chunk)
        os.replace(partial, dest)
    finally:
        if partial.exists():
            partial.unlink()
    return size


def fetch_one(url: str, dest: Path, headers: Mapping[str, str], *, timeout: float, retry_wait: float) -> dict[str, Any]:
    started = time.monotonic()
    for attempt in (1, 2):
        try:
            size = _download(url, dest, headers, timeout)
            return {"status": "fetched", "bytes": size, "seconds": round(time.monotonic() - started, 1)}
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return {"status": "absent", "bytes": 0, "seconds": round(time.monotonic() - started, 1)}
            if exc.code == 403:
                return {"status": "forbidden", "bytes": 0, "error": "HTTP 403 (not allowlisted?)"}
            error = f"HTTP {exc.code}"
            retryable = exc.code in (408, 429, 500, 502, 503, 504)
        except Exception as exc:  # timeouts and resets: web is erratic, not gone
            error, retryable = f"{type(exc).__name__}: {exc}", True
        if attempt == 2 or not retryable:
            return {"status": "failed", "bytes": 0, "error": error[:300],
                    "seconds": round(time.monotonic() - started, 1)}
        time.sleep(retry_wait)
    raise AssertionError("unreachable")


def fetch_main(args: argparse.Namespace) -> int:
    base = str(os.environ.get("SYNDICATE_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
    token = str(os.environ.get(TOKEN_ENV) or "").strip()
    items: list[tuple[str, str, Path, bool, dict[str, str]]] = []
    admin = {"X-Admin-Token": token} if token else {}
    for required, pairs in ((True, args.fetch), (False, args.fetch_optional)):
        for source, dest in pairs:
            url = f"{base}/api/ops/artifacts/stream?path={urllib.parse.quote(source, safe='')}"
            items.append((source, url, Path(dest), required, admin))
    for day, dest in args.fetch_chips:
        # Every sport in one call; the scorecard filters by sport itself.
        url = f"{base}/api/board/game-chips?{urllib.parse.urlencode({'date': day})}"
        items.append((f"game-chips:{day}", url, Path(dest), True, {}))

    files: list[dict[str, Any]] = []
    for index, (source, url, dest, required, headers) in enumerate(items):
        if index:
            time.sleep(args.fetch_pause)  # one request at a time, never a burst
        outcome = fetch_one(url, dest, headers, timeout=args.fetch_timeout, retry_wait=args.fetch_retry_wait)
        files.append({"source": source, "dest": str(dest), "required": required, **outcome})
    print(json.dumps({"files": files}, indent=1))
    missing = [f for f in files if f["required"] and f["status"] != "fetched"]
    return 1 if missing else 0


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out-dir", help="where the report, logs and raw outputs go (required)")
    parser.add_argument("--only", default="", help="comma-separated job or family names")
    parser.add_argument("--dates", type=int, default=7, help="Central dates before today to grade")
    parser.add_argument("--dry-run", action="store_true", help="print the plan and run nothing")
    parser.add_argument("--timeout-per-job", type=float, default=1800.0)
    parser.add_argument("--web-pause", type=float, default=15.0, help="seconds between web-touching jobs")
    parser.add_argument("--work-dir", default=None, help="inputs and caches; default a temp dir, removed after")
    parser.add_argument("--run-date", default=None, help="Central 'today' (YYYY-MM-DD); default now")
    parser.add_argument("--fetch", nargs=2, action="append", default=[], metavar=("ARTIFACT_PATH", "DEST"))
    parser.add_argument("--fetch-optional", nargs=2, action="append", default=[], metavar=("ARTIFACT_PATH", "DEST"))
    parser.add_argument("--fetch-chips", nargs=2, action="append", default=[], metavar=("DATE", "DEST"))
    parser.add_argument("--fetch-pause", type=float, default=5.0)
    parser.add_argument("--fetch-timeout", type=float, default=600.0)
    parser.add_argument("--fetch-retry-wait", type=float, default=30.0)
    args = parser.parse_args(argv)

    if args.fetch or args.fetch_optional or args.fetch_chips:
        return fetch_main(args)
    if not args.out_dir:
        parser.error("--out-dir is required")

    run_day = date.fromisoformat(args.run_date) if args.run_date else central_today()
    out_dir = Path(args.out_dir).resolve()
    only = [item.strip() for item in args.only.split(",") if item.strip()]
    token = str(os.environ.get(TOKEN_ENV) or "").strip() or None

    if args.dry_run:
        work_dir = Path(args.work_dir) if args.work_dir else Path(tempfile.gettempdir()) / "weekly_backtests_<tmp>"
    else:
        work_dir = Path(args.work_dir) if args.work_dir else Path(tempfile.mkdtemp(prefix="weekly_backtests_"))
    try:
        jobs = select_jobs(build_plan(run_day, args.dates, work_dir.resolve(), out_dir), only)
    except ValueError as exc:
        parser.error(str(exc))

    dates = date_window(run_day, args.dates)
    if args.dry_run:
        print(f"DRY RUN {RUNNER_VERSION} run_date={run_day} dates={dates[-1]}..{dates[0]} "
              f"jobs={len(jobs)} token={'set' if token else 'NOT SET'}")
        for job in jobs:
            flags = [f for f, on in (("token", job.needs_token), ("web", job.touches_web)) if on]
            print(f"  {job.name}  [{', '.join(flags) or 'local'}]"
                  + (f"  requires={','.join(job.requires)}" if job.requires else ""))
            print(f"      python {shlex.join(job.args)}"
                  + "".join(f" [{flag} {path} if present]" for flag, path in job.optional_file_args))
            if job.env:
                print(f"      env {' '.join(f'{k}={v}' for k, v in job.env)}")
        return 0

    try:
        results = run_plan(jobs, token=token, timeout=args.timeout_per_job, out_dir=out_dir,
                           work_dir=work_dir.resolve(), web_pause=args.web_pause)
        report = build_report(results, run_day=run_day, dates=dates)
        json_path, md_path = write_report(report, out_dir, token)
    finally:
        if not args.work_dir:
            shutil.rmtree(work_dir, ignore_errors=True)
    print(f"report: {json_path}\n        {md_path}\ncounts: {report['counts']}")
    return 0 if report["counts"].get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
