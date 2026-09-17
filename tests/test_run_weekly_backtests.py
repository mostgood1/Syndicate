"""`scripts/run_weekly_backtests.py` and the ADMIN_TOKEN env fallbacks it relies on.

Lane `model-scorecard-cron`. The runner is what a fresh-clone Render cron calls on
Mondays, so the properties that matter are the ones nobody would notice going
wrong: a job that hangs or fails must cost only its own row, the token must never
reach argv or a report, and the headline numbers must be read from each script's
REAL output shape. The samples under `tests/fixtures/weekly_backtests/` were
captured from real runs on 2026-09-17 (production inputs; only the local work-dir
prefix was replaced with `<work>`).
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import sys
import urllib.error
from datetime import date

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "weekly_backtests"
TOKEN = "s3cr3t-weekly-token-value"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"_wb_{name}", ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses resolve string annotations through sys.modules
    spec.loader.exec_module(module)
    return module


runner = _load("run_weekly_backtests")
Job = runner.Job


def _py(code: str, **kw) -> "runner.Job":
    return Job(name=kw.pop("name", "probe"), family=kw.pop("family", "probe"), args=("-c", code), **kw)


def _run(jobs, tmp_path, *, token=TOKEN, timeout=60.0):
    return runner.run_plan(jobs, token=token, timeout=timeout, out_dir=tmp_path / "out",
                           work_dir=tmp_path / "work", web_pause=0.0, log=lambda line: None)


# ---------------------------------------------------------------------------
# plan
# ---------------------------------------------------------------------------


def test_date_window_is_the_n_dates_before_today():
    assert runner.date_window(date(2026, 9, 21), 7) == [
        "2026-09-20", "2026-09-19", "2026-09-18", "2026-09-17", "2026-09-16", "2026-09-15", "2026-09-14"]


def test_plan_covers_the_date_window(tmp_path):
    plan = runner.build_plan(date(2026, 9, 21), 7, tmp_path / "work", tmp_path / "out")
    by_name = {job.name: job for job in plan}

    inputs = [job for job in plan if job.family == "layer2_inputs"]
    assert [job.name.split(":")[1] for job in inputs] == [f"2026-09-{d}" for d in range(14, 21)]
    for job in inputs:
        day = job.name.split(":")[1]
        assert f"reports/intelligence/clv_openings/{day}.jsonl" in job.args
        assert job.needs_token and job.touches_web
        scorecards = [j for j in plan if j.family == "layer2_scorecard" and j.requires == (job.name,)]
        assert sorted(j.args[j.args.index("--sport") + 1] for j in scorecards) == sorted(runner.LAYER2_SPORTS)
        assert all(not j.needs_token and not j.touches_web for j in scorecards)

    mlb = by_name["mlb_props"].args
    assert mlb[mlb.index("--limit") + 1] == "7" and mlb[mlb.index("--end") + 1] == "2026-09-20"
    assert by_name["ncaaf_player_props"].args[1:3] == ("--season", "2026")
    assert by_name["nfl_props"].args[1:3] == ("--seasons", "2025,2026")
    assert by_name["nfl_props"].requires == ("nfl_pbp",)
    nfl_env = dict(by_name["nfl_pbp"].env)
    # The pbp write root and read root must be one directory (see build_plan).
    assert nfl_env["SYNDICATE_NFL_SOURCE_ROOT"].endswith("source_artifacts")
    assert nfl_env == dict(by_name["nfl_props"].env)
    assert "mlb_hitter_props_vs_market" not in by_name  # no pregame odds on web; see module docstring

    january = {job.name: job for job in runner.build_plan(date(2027, 1, 15), 3, tmp_path, tmp_path)}
    assert january["nfl_props"].args[1:3] == ("--seasons", "2025,2026")


def test_only_selects_by_name_or_family_and_pulls_requirements(tmp_path):
    plan = runner.build_plan(date(2026, 9, 21), 2, tmp_path / "work", tmp_path / "out")
    assert [job.name for job in runner.select_jobs(plan, ["nfl_props"])] == ["nfl_pbp", "nfl_props"]
    layer2 = runner.select_jobs(plan, ["layer2_scorecard"])
    assert sum(job.family == "layer2_inputs" for job in layer2) == 2
    assert len(layer2) == 2 + 2 * len(runner.LAYER2_SPORTS)
    with pytest.raises(ValueError):
        runner.select_jobs(plan, ["no_such_job"])


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------


def test_token_reaches_the_child_by_env_and_never_the_report(tmp_path):
    jobs = [
        _py("import os; print('token=' + os.environ['ADMIN_TOKEN'])", name="needs", needs_token=True),
        _py("import os; print('token=' + str(os.environ.get('ADMIN_TOKEN')))", name="does_not_need"),
    ]
    results = _run(jobs, tmp_path)
    assert [r["status"] for r in results] == ["ok", "ok"]
    assert runner.REDACTED in results[0]["stdout_tail"]  # it WAS delivered, then scrubbed
    assert "token=None" in results[1]["stdout_tail"]  # least privilege
    assert TOKEN not in pathlib.Path(results[0]["stdout_log"]).read_text(encoding="utf-8")

    report = runner.build_report(results, run_day=date(2026, 9, 21), dates=["2026-09-20"])
    json_path, md_path = runner.write_report(report, tmp_path / "out", TOKEN)
    assert TOKEN not in json_path.read_text(encoding="utf-8")
    assert TOKEN not in md_path.read_text(encoding="utf-8")
    assert all(TOKEN not in r["command"] for r in results)

    with pytest.raises(ValueError):
        runner.run_job(_py(f"print('{TOKEN}')"), token=TOKEN, timeout=10, logs_dir=tmp_path / "logs",
                       work_dir=tmp_path / "work")


def test_missing_token_skips_token_jobs_only(tmp_path):
    results = _run([_py("print(1)", name="needs", needs_token=True), _py("print(1)", name="local")],
                   tmp_path, token=None)
    assert [r["status"] for r in results] == ["skipped", "ok"]


def test_timeout_is_its_own_status(tmp_path):
    [result] = _run([_py("import time; time.sleep(60)")], tmp_path, timeout=1.0)
    assert result["status"] == "timeout"
    assert result["exit_code"] is None
    assert result["duration_s"] < 30


def test_posix_branch_reads_exit_and_peak_from_wait4(tmp_path, monkeypatch):
    """The cron is Linux, so production takes the `os.wait4` branch a Windows run never reaches."""
    calls: list[int] = []

    class Usage:
        ru_maxrss = 204800  # kilobytes on Linux

    def fake_wait4(pid, options):
        calls.append(options)
        return (0, 0, None) if len(calls) == 1 else (pid, 3 << 8, Usage())

    monkeypatch.setattr(runner.os, "wait4", fake_wait4, raising=False)
    monkeypatch.setattr(runner.os, "WNOHANG", 1, raising=False)  # absent on Windows
    monkeypatch.setattr(runner.sys, "platform", "linux")
    [result] = _run([_py("pass")], tmp_path)
    assert calls == [1, 1]  # polled without blocking, not a blind wait
    assert (result["status"], result["exit_code"]) == ("failed", 3)
    assert (result["peak_rss_mb"], result["peak_rss_source"]) == (200.0, "wait4")


def test_a_failing_job_does_not_stop_the_rest(tmp_path):
    results = _run([
        _py("import sys; print('boom', file=sys.stderr); sys.exit(3)", name="fails"),
        _py("print('never')", name="depends", requires=("fails",)),
        _py("print('fine')", name="independent"),
    ], tmp_path)
    assert [(r["name"], r["status"], r["exit_code"]) for r in results] == [
        ("fails", "failed", 3), ("depends", "skipped", None), ("independent", "ok", 0)]
    assert "boom" in results[0]["stderr_tail"]


def test_exit_code_is_2_when_every_job_failed(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "build_plan", lambda *a, **k: [_py("raise SystemExit(1)", name="a"),
                                                              _py("raise SystemExit(4)", name="b")])
    code = runner.main(["--out-dir", str(tmp_path / "out"), "--work-dir", str(tmp_path / "work"),
                        "--web-pause", "0", "--run-date", "2026-09-21"])
    assert code == 2
    report = json.loads((tmp_path / "out" / "weekly_backtests_2026-09-21.json").read_text(encoding="utf-8"))
    assert report["runner_version"] == "weekly_backtests/1"
    assert [job["status"] for job in report["jobs"]] == ["failed", "failed"]


def test_dry_run_runs_nothing(tmp_path, monkeypatch, capsys):
    def _forbidden(*args, **kwargs):
        raise AssertionError("dry run started a process")

    monkeypatch.setattr(runner.subprocess, "Popen", _forbidden)
    monkeypatch.setattr(runner, "_download", _forbidden)
    assert runner.main(["--out-dir", str(tmp_path / "out"), "--dry-run", "--run-date", "2026-09-21"]) == 0
    assert "DRY RUN" in capsys.readouterr().out
    assert not (tmp_path / "out").exists()


def test_fetch_mode_counts_absent_and_keeps_the_token_out_of_the_url(tmp_path, monkeypatch, capsys):
    seen: list[tuple[str, dict]] = []

    def fake_download(url, dest, headers, timeout):
        seen.append((url, dict(headers)))
        if "missing" in url:
            raise urllib.error.HTTPError(url, 404, "not found", hdrs=None, fp=None)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text("x", encoding="utf-8")
        return 1

    monkeypatch.setattr(runner, "_download", fake_download)
    monkeypatch.setenv("ADMIN_TOKEN", TOKEN)
    code = runner.main(["--fetch", "reports/a.jsonl", str(tmp_path / "a"),
                        "--fetch-optional", "reports/missing.jsonl", str(tmp_path / "b"),
                        "--fetch-chips", "2026-09-20", str(tmp_path / "c"), "--fetch-pause", "0"])
    assert code == 0
    statuses = [f["status"] for f in json.loads(capsys.readouterr().out)["files"]]
    assert statuses == ["fetched", "absent", "fetched"]
    assert all(TOKEN not in url for url, _ in seen)
    assert seen[0][1] == {"X-Admin-Token": TOKEN} and seen[2][1] == {}  # chips are public

    code = runner.main(["--fetch", "reports/missing.jsonl", str(tmp_path / "d"), "--fetch-pause", "0"])
    assert code == 1  # a REQUIRED input that is absent fails the job


# ---------------------------------------------------------------------------
# summaries over REAL captured output
# ---------------------------------------------------------------------------


def _summary(family: str, fixture: str, json_source: str, json_file: str | None = None):
    job = Job(name=family, family=family, args=(), json_source=json_source, json_file=json_file)
    stdout = "" if json_source == "file" else (FIXTURES / fixture).read_text(encoding="utf-8")
    parsed, error = runner._parse_json(job, stdout)
    assert error is None
    return runner.SUMMARIZERS[family](parsed, stdout)


def test_summary_layer2_scorecard_real():
    s = _summary("layer2_scorecard", "layer2_scorecard_soccer.stdout.json", "stdout")
    assert (s["date"], s["sport"], s["opportunities"], s["graded"], s["units"]) == ("2026-09-16", "soccer", 138, 1, -1.0)
    assert s["roi_pct"] == -100.0
    assert s["ungraded"]["market_not_gradeable_from_score"] == 81
    assert s["departures_available"] is True


def test_summary_fetch_real():
    s = _summary("layer2_inputs", "layer2_inputs.stdout.json", "stdout")
    assert s["counts"] == {"fetched": 3}
    assert s["bytes"] == 19128712 + 2569202 + 87134


def test_summary_mlb_props_real():
    s = _summary("mlb_props", "mlb_props.stdout.txt", "marker")
    assert s["player_games"] == 478 and s["dates"] == "2026-09-15..2026-09-16"
    assert s["coverage"]["excluded, did not bat (0 PA)"] == 25
    assert s["markets"]["h"]["mae_model"] == 0.6662
    assert "h" in s["beats_constant_baseline"] and "rbi" not in s["beats_constant_baseline"]
    assert s["oos_debiased_beats_baseline"] == []  # 2 dates: out-of-sample not computed


def test_summary_ncaaf_real_and_nan_becomes_null():
    s = _summary("ncaaf_player_props", "ncaaf_player_props.stdout.json", "stdout")
    assert (s["season"], s["rows"], s["weeks_graded"]) == (2026, 8115, [])
    assert s["anytime_td"]["n"] == 0 and s["beats_both_baselines"] == []
    report = runner.build_report([{"name": "n", "family": "ncaaf_player_props", "status": "ok", "summary": s}],
                                 run_day=date(2026, 9, 17), dates=[])
    json.dumps(report, allow_nan=False)  # strict JSON: the script's NaN cells are null here


def test_summary_wnba_refusal_real():
    s = _summary_text("wnba_projection", "wnba_projection_refused.stdout.txt")
    assert s["refused"] is True and s["measurable_games"] == 0
    assert s["coverage"]["games joined to a final"] == 0


def _summary_text(family: str, fixture: str):
    stdout = (FIXTURES / fixture).read_text(encoding="utf-8")
    parsed, error = runner._parse_json(Job(name=family, family=family, args=(), json_source="marker"), stdout)
    assert parsed is None and error  # a refusal prints no MEASURED_SKILL block
    return runner.SUMMARIZERS[family](parsed, stdout)


def test_summary_nfl_real():
    pbp = _summary("nfl_pbp", "nfl_pbp.stdout.json", "stdout")
    assert [(r["season"], r["status"], r["reg_plays"]) for r in pbp["results"]] == [
        (2026, "written", 2756), (2025, "written", 46452)]
    props = _summary("nfl_props", "", "file", str(FIXTURES / "nfl_props.out.json"))
    assert props["coverage"]["player_game_weeks"] == 5691
    assert props["point_accuracy"]["passing_yards"]["n"] == 554
    assert "interceptions" not in props["beats_constant_baseline"]


# ---------------------------------------------------------------------------
# ADMIN_TOKEN env fallbacks: a fresh clone has no .env
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("script", ["backtest_mlb_props", "backtest_wnba_projection"])
def test_admin_token_falls_back_to_env_when_no_dotenv(script, tmp_path, monkeypatch):
    module = _load(script)
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)  # no .env here
    monkeypatch.delenv("ADMIN_TOKEN", raising=False)
    with pytest.raises(SystemExit):
        module._admin_token()
    monkeypatch.setenv("ADMIN_TOKEN", "from-env")
    assert module._admin_token() == "from-env"
    (tmp_path / ".env").write_text("ADMIN_TOKEN='from-file'\n", encoding="utf-8")
    assert module._admin_token() == "from-file"  # .env behaviour unchanged


def test_grade_market_script_env_token_and_input_paths(tmp_path, monkeypatch):
    module = _load("grade_mlb_hitter_props_vs_market")
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    monkeypatch.delenv("ADMIN_TOKEN", raising=False)
    assert "ADMIN_TOKEN" not in module._env()
    monkeypatch.setenv("ADMIN_TOKEN", "from-env")
    assert module._env()["ADMIN_TOKEN"] == "from-env"
    (tmp_path / ".env").write_text('ADMIN_TOKEN="from-file"\n', encoding="utf-8")
    assert module._env()["ADMIN_TOKEN"] == "from-file"

    day = "2099-01-01"
    snapshots = tmp_path / "snapshots"
    (snapshots / day).mkdir(parents=True)
    (snapshots / day / "oddsapi_hitter_props_2099_01_01.json").write_text(json.dumps({"hitter_props": {
        "a b": {"batter_hits": {"line": 0.5, "over_odds": -150, "under_odds": 120}}}}), encoding="utf-8")
    assert module.load_odds(day) == {}
    assert list(module.load_odds(day, snapshots)) == [("a b", "batter_hits")]
    log = tmp_path / "log.csv"
    log.write_text("date,player_name,h\n2099-01-01,A B,1\n", encoding="utf-8")
    assert module.load_actuals(log)[(day, "a b")]["h"] == "1"
