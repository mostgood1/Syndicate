"""scripts/local_production.py -- the env each local role runs with.

The derivation is the whole risk surface: it decides which loops run where
(render.yaml's per-service flags), where data lands, and whether money is live.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts import local_production as lp


@pytest.fixture()
def settings(tmp_path: Path) -> lp.Settings:
    return lp.Settings(home=tmp_path / "home", port=12345)


@pytest.fixture(scope="module")
def blueprint():
    return lp.load_blueprint()


def _env(role, blueprint, settings, local=None, live=None):
    env, audit = lp.derive_role_env(role, blueprint, local or {}, settings, live=live, base_env={})
    return env, audit


def test_blueprint_has_all_three_roles(blueprint):
    assert set(lp.ROLE_ORDER) <= set(blueprint)
    assert all(blueprint[r] for r in lp.ROLE_ORDER)


def test_render_paths_rewritten_to_one_shared_data_root(blueprint, settings):
    for role in lp.ROLE_ORDER:
        env, _ = _env(role, blueprint, settings)
        assert env["SYNDICATE_DATA_ROOT"] == str(settings.data_root)
        assert not any(str(v).startswith("/opt/render") for v in env.values()), role
    web, _ = _env("web", blueprint, settings)
    worker, _ = _env("refresh-worker", blueprint, settings)
    assert web["SYNDICATE_REPORTS_ROOT"] == worker["SYNDICATE_REPORTS_ROOT"]


def test_loop_ownership_comes_from_the_blueprint_per_role(blueprint, settings):
    web, _ = _env("web", blueprint, settings)
    rw, _ = _env("refresh-worker", blueprint, settings)
    low, _ = _env("live-odds-worker", blueprint, settings)
    # intelligence loop: refresh-worker only
    assert rw["SYNDICATE_ENABLE_INTELLIGENCE_STATE_BACKGROUND_LOOP"] == "true"
    assert web["SYNDICATE_ENABLE_INTELLIGENCE_STATE_BACKGROUND_LOOP"] == "false"
    assert low["SYNDICATE_ENABLE_INTELLIGENCE_STATE_BACKGROUND_LOOP"] == "false"
    # live odds loop: live-odds-worker only
    assert low["SYNDICATE_ENABLE_LIVE_ODDS_REFRESH_LOOP"] == "true"
    assert rw["SYNDICATE_ENABLE_LIVE_ODDS_REFRESH_LOOP"] == "false"
    assert rw["SYNDICATE_REFRESH_LANE"] == "refresh-worker"
    assert low["SYNDICATE_REFRESH_LANE"] == "live-odds-worker"
    assert web["SYNDICATE_WEB_DYNO"] == "true" and rw["SYNDICATE_WEB_DYNO"] == "false"


def test_redis_state_mode_keeps_production_semantics(blueprint, settings):
    for role in lp.ROLE_ORDER:
        env, _ = _env(role, blueprint, settings)
        assert env["RENDER"] == "true"
        assert env["SYNDICATE_REFRESH_STATE_BACKEND"] == "keyvalue"
        assert env["SYNDICATE_REFRESH_STATE_URL"] == settings.redis_url
        assert env["RENDER_SERVICE_NAME"] == f"local-{role}"
        # one bootstrap, run by `up` itself, never three racing ones
        assert env["SYNDICATE_BOOTSTRAP_ON_START"] == "0"


def test_file_state_mode_clears_hosted_flags(blueprint, tmp_path):
    settings = lp.Settings(home=tmp_path, state="file")
    env, _ = _env("refresh-worker", blueprint, settings)
    assert env["SYNDICATE_REFRESH_STATE_BACKEND"] == "filesystem"
    assert "RENDER" not in env
    assert "SYNDICATE_REQUIRE_HOSTED_STORAGE" not in env


def test_publish_url_dropped_on_a_shared_disk(blueprint, settings):
    env, _ = _env("refresh-worker", blueprint, settings)
    assert "SYNDICATE_WEB_PUBLISH_URL" not in env
    loop = lp.Settings(home=settings.home, port=12345, publish_loopback=True)
    env, _ = _env("refresh-worker", blueprint, loop)
    assert env["SYNDICATE_WEB_PUBLISH_URL"] == "http://127.0.0.1:12345"


def test_money_is_paper_unless_explicitly_allowed(blueprint, settings):
    armed = {"SYNDICATE_EXECUTION_MODE": "live", "SYNDICATE_EXECUTION_LIVE_ARMED": "1", "SYNDICATE_EXECUTION_ENABLED": "1"}
    env, _ = _env("live-odds-worker", blueprint, settings, live=armed)
    assert env["SYNDICATE_EXECUTION_MODE"] == "paper"
    assert env["SYNDICATE_EXECUTION_LIVE_ARMED"] == "0"
    assert not lp.money_is_live(env)
    allowed = lp.Settings(home=settings.home, allow_live_execution=True)
    env, _ = _env("live-odds-worker", blueprint, allowed, live=armed)
    assert lp.money_is_live(env)


def test_layering_live_over_blueprint_and_local_over_live(blueprint, settings):
    live = {"SYNDICATE_LIVE_ODDS_REFRESH_INTERVAL_SECONDS": "90", "SOME_DASHBOARD_KEY": "/opt/render/project/data/x"}
    env, audit = _env("live-odds-worker", blueprint, settings, live=live)
    assert env["SYNDICATE_LIVE_ODDS_REFRESH_INTERVAL_SECONDS"] == "90"
    assert env["SOME_DASHBOARD_KEY"] == str(settings.data_root / "x")
    env, _ = _env("live-odds-worker", blueprint, settings, live=live, local={"SYNDICATE_LIVE_ODDS_REFRESH_INTERVAL_SECONDS": "120"})
    assert env["SYNDICATE_LIVE_ODDS_REFRESH_INTERVAL_SECONDS"] == "120"


def test_sync_false_keys_absent_until_supplied(blueprint, settings):
    env, audit = _env("refresh-worker", blueprint, settings)
    assert "EVALUATION_SETTLEMENT_ENABLE_REFRESH_WORKER_AUTORUN" not in env
    assert "EVALUATION_SETTLEMENT_ENABLE_REFRESH_WORKER_AUTORUN" in audit["unset"]
    env, audit = _env("refresh-worker", blueprint, settings, live={"EVALUATION_SETTLEMENT_ENABLE_REFRESH_WORKER_AUTORUN": "true"})
    assert env["EVALUATION_SETTLEMENT_ENABLE_REFRESH_WORKER_AUTORUN"] == "true"
    assert "EVALUATION_SETTLEMENT_ENABLE_REFRESH_WORKER_AUTORUN" not in audit["unset"]


def test_render_api_key_never_carried(blueprint, settings):
    env, _ = _env("web", blueprint, settings, live={"RENDER_API_KEY": "x"}, local={"RENDER_API_KEY": "y"})
    assert "RENDER_API_KEY" not in env


def test_stray_render_markers_in_operator_shell_do_not_leak(blueprint, settings):
    env, _ = lp.derive_role_env("web", blueprint, {}, settings, base_env={"RENDER_EXTERNAL_URL": "https://syndicate-an21.onrender.com"})
    assert "RENDER_EXTERNAL_URL" not in env


def test_env_file_parsing(tmp_path):
    path = tmp_path / "x.env"
    path.write_text('# c\nA=1\nexport B="two words"\nPEM="-----BEGIN-----\\nabc\\n-----END-----"\nC=\'q\'\n\nbad\n', encoding="utf-8")
    values = lp.parse_env_file(path)
    assert values == {"A": "1", "B": "two words", "PEM": "-----BEGIN-----\nabc\n-----END-----", "C": "q"}


def test_template_lists_every_value_less_blueprint_key(blueprint):
    text = lp.template_text(blueprint)
    for items in blueprint.values():
        for item in items:
            if item.source in {"generate", "from_web", "sync_false"}:
                assert item.key in text
    assert "ADMIN_TOKEN=" in text  # generated, not left blank


def test_web_command_is_a_production_server(blueprint, settings):
    env, _ = _env("web", blueprint, settings)
    command, server = lp.role_command("web", env, settings)
    assert server in {"gunicorn", "waitress"}
    assert "12345" in " ".join(command)


def test_worker_to_web_urls_point_at_local_web_never_onrender(blueprint, settings):
    for role in lp.ROLE_ORDER:
        env, _ = _env(role, blueprint, settings, live={"SYNDICATE_WNBA_LIVE_BOX_BASE_URL": "http://syndicate-an21:10000"})
        for key in ("SYNDICATE_INTERNAL_WEB_BASE_URL", "SYNDICATE_WNBA_LIVE_BOX_BASE_URL", "SYNDICATE_BASE_URL"):
            assert env[key] == "http://127.0.0.1:12345"
        assert not any("onrender.com" in str(v) or "syndicate-an21" in str(v) for v in env.values()), role


def test_web_counts_as_render_web_dyno_in_both_state_modes(blueprint, tmp_path):
    # Without a marker, syndicate/app.py starts the intelligence loop on web
    # regardless of its flag -- a second board builder on the same disk.
    for state in ("redis", "file"):
        env, _ = _env("web", blueprint, lp.Settings(home=tmp_path, state=state))
        assert env["RENDER_SERVICE_ID"] == "local-web"
        assert env["SYNDICATE_ENABLE_INTELLIGENCE_STATE_BACKGROUND_LOOP"] == "false"


def _down_args(home, timeout=30.0):
    return lp.parse_args(["--home", str(home), "down", "--timeout", str(timeout)])


def _write_pidfile(settings, supervisor_pid, roles=None, redis_pid=None):
    import json

    settings.run_dir.mkdir(parents=True, exist_ok=True)
    (settings.run_dir / lp.PIDFILE_NAME).write_text(
        json.dumps({"supervisor_pid": supervisor_pid, "roles": roles or {}, "redis_pid": redis_pid}), encoding="utf-8"
    )


def _dead_pid():
    import subprocess
    import sys

    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait()
    return child.pid


def test_down_with_a_dead_supervisor_returns_at_once_and_reaps_orphans(settings):
    # 2026-09-30: `down` waited its full 90 s timeout on a supervisor that was
    # already gone, because only a live supervisor ever reads the stop file.
    import subprocess
    import sys
    import time

    orphan = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        _write_pidfile(settings, _dead_pid(), roles={"web": orphan.pid, "refresh-worker": _dead_pid()})
        started = time.monotonic()
        assert lp.cmd_down(_down_args(settings.home, timeout=30.0)) == 0
        assert time.monotonic() - started < 10
        assert orphan.wait(timeout=10) is not None  # the orphaned role was killed
        assert not (settings.run_dir / lp.PIDFILE_NAME).exists()
        assert not (settings.run_dir / "stop").exists()
    finally:
        if orphan.poll() is None:
            orphan.kill()


def test_down_with_a_live_supervisor_signals_it_and_waits(settings):
    import subprocess
    import sys
    import threading

    supervisor = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        _write_pidfile(settings, supervisor.pid)

        def _behave_like_a_supervisor():
            # a real supervisor sees the stop file and removes its own pidfile
            stop = settings.run_dir / "stop"
            for _ in range(100):
                if stop.exists():
                    (settings.run_dir / lp.PIDFILE_NAME).unlink(missing_ok=True)
                    return
                threading.Event().wait(0.05)

        watcher = threading.Thread(target=_behave_like_a_supervisor)
        watcher.start()
        assert lp.cmd_down(_down_args(settings.home, timeout=30.0)) == 0
        watcher.join(timeout=10)
        assert supervisor.poll() is None  # a cooperative supervisor is NOT killed
    finally:
        supervisor.kill()


def test_down_with_no_pidfile_is_a_noop(settings):
    assert lp.cmd_down(_down_args(settings.home)) == 0


def test_down_runs_as_a_script_from_outside_the_repo(tmp_path):
    # 2026-09-30: `down` imported syndicate.* and died with ModuleNotFoundError
    # when run the way the runbook says -- as a script -- because only
    # scripts/ is on sys.path then. The in-process tests could not see it.
    import subprocess
    import sys

    script = lp.REPO_ROOT / "scripts" / "local_production.py"
    settings = lp.Settings(home=tmp_path / "home")
    _write_pidfile(settings, _dead_pid())
    result = subprocess.run(
        [sys.executable, str(script), "--home", str(settings.home), "down", "--timeout", "5"],
        cwd=str(tmp_path), capture_output=True, text=True, timeout=60,
        env={k: v for k, v in __import__("os").environ.items() if k != "PYTHONPATH"},
    )
    assert result.returncode == 0, result.stderr
    assert "stale pidfile" in result.stdout


def test_checkout_depth_matches_repo_root_from():
    # `#313`: pipeline/intelligence_state.py resolves parents[3] at import.
    # A checkout at a drive root's first level crashed web with IndexError.
    from syndicate.features.shared.source_roots import clear_source_root_caches, repo_root_from

    for root, expected in ((Path("/Syndicate"), False), (Path("/a/b/Syndicate"), True)):
        assert lp.checkout_depth_ok(root) is expected
        clear_source_root_caches()
        try:
            repo_root_from(root / "pipeline" / "intelligence_state.py")
            resolved = True
        except IndexError:
            resolved = False
        assert resolved is expected


def test_each_role_gets_its_render_plan_as_a_memory_ceiling(blueprint, settings):
    # Without a ceiling every headroom gate reads None and fails closed.
    for role, megabytes in lp.PLAN_MEMORY_MB.items():
        assert _env(role, blueprint, settings)[0]["SYNDICATE_LOCAL_MEMORY_LIMIT_MB"] == str(megabytes)
    override = {"SYNDICATE_LOCAL_MEMORY_LIMIT_MB": "8192"}
    assert _env("refresh-worker", blueprint, settings, local=override)[0]["SYNDICATE_LOCAL_MEMORY_LIMIT_MB"] == "8192"


def test_gunicorn_usable_does_not_require_gunicorn_on_path(monkeypatch):
    # The WSL boot task runs the venv python without activating the venv, so
    # its bin/ is not on PATH; web runs `python -m gunicorn` and never needs it.
    import types

    monkeypatch.setattr(lp, "IS_WINDOWS", False)
    monkeypatch.setattr(lp.shutil, "which", lambda name: None)
    monkeypatch.setattr(lp.subprocess, "run", lambda *a, **k: types.SimpleNamespace(returncode=0))
    assert lp.gunicorn_usable() is True
    monkeypatch.setattr(lp.subprocess, "run", lambda *a, **k: types.SimpleNamespace(returncode=1))
    assert lp.gunicorn_usable() is False


# --- scheduled jobs, rotation, backup, CI env (lane local-prod-gap-fixes) ----

import datetime as _dt  # noqa: E402
import shutil as _shutil  # noqa: E402
import sys as _sys  # noqa: E402


def _utc(y, m, d, hh, mm):
    return _dt.datetime(y, m, d, hh, mm, tzinfo=_dt.timezone.utc)


def test_every_render_cron_is_a_scheduled_job_and_none_publishes():
    # The three dashboard crons were missing locally (assessment 2026-10-01);
    # `--publish` would only HTTP-write onto the disk the job already wrote.
    jobs = {job.name: job for job in lp.SCHEDULED_JOBS}
    assert {"model-scorecard", "sim-input-reports", "ci-suite", "mlb-season-artifacts", "data-backup"} <= set(jobs)
    assert (jobs["sim-input-reports"].hour, jobs["sim-input-reports"].minute) == (7, 0)
    assert (jobs["ci-suite"].hour, jobs["ci-suite"].minute) == (8, 0)
    assert (jobs["mlb-season-artifacts"].hour, jobs["mlb-season-artifacts"].weekday) == (9, 0)
    assert "--no-pull" in jobs["sim-input-reports"].argv
    for job in lp.SCHEDULED_JOBS:
        assert "--publish" not in job.argv, job.name


def test_job_is_due_daily_weekly_and_once_per_day():
    daily = lp.ScheduledJob("d", 7, 0, ("x",))
    weekly = lp.ScheduledJob("w", 9, 0, ("x",), weekday=0)
    monday, tuesday = _utc(2026, 10, 5, 9, 1), _utc(2026, 10, 6, 9, 1)
    assert not lp.job_is_due(daily, _utc(2026, 10, 5, 6, 59), None)
    assert lp.job_is_due(daily, monday, None)
    assert lp.job_is_due(daily, monday, "2026-10-04")
    assert not lp.job_is_due(daily, monday, "2026-10-05")
    assert lp.job_is_due(weekly, monday, None)
    assert not lp.job_is_due(weekly, tuesday, None)
    assert not lp.job_is_due(weekly, _utc(2026, 10, 5, 8, 59), None)


def test_run_due_jobs_substitutes_home_runs_once_and_records_rc(settings):
    import json
    import time

    settings.run_dir.mkdir(parents=True, exist_ok=True)
    settings.logs_dir.mkdir(parents=True, exist_ok=True)
    job = lp.ScheduledJob("probe", 0, 0, ("-c", "import sys; print('HOME=' + sys.argv[1]); sys.exit(3)", "{home}"))
    running: dict = {}
    now = _utc(2026, 10, 5, 12, 0)
    lp.run_due_jobs(settings, {}, running, now=now, jobs=(job,))
    assert "probe" in running
    running["probe"].wait(timeout=30)
    time.sleep(0.2)
    lp.run_due_jobs(settings, {}, running, now=now, jobs=(job,))  # reaps, does not relaunch
    assert running == {}
    state = json.loads((settings.run_dir / "scheduled_jobs.json").read_text(encoding="utf-8"))
    assert state["probe"]["last_run_date"] == "2026-10-05"
    assert state["probe"]["last_rc"] == 3
    log = (settings.logs_dir / "job-probe.log").read_text(encoding="utf-8")
    assert f"HOME={settings.home}" in log


def test_rotate_running_log_keeps_the_writers_handle_working(tmp_path):
    # A rename-rotation strands a live writer on the renamed file; copy+truncate
    # must leave the role's append-mode handle writing into the CURRENT log.
    log = tmp_path / "role.log"
    handle = log.open("a", encoding="utf-8")
    handle.write("old-line\n" * 50)
    handle.flush()
    assert lp.rotate_running_log(log, max_bytes=100) is True
    handle.write("new-line\n")
    handle.flush()
    handle.close()
    assert log.read_text(encoding="utf-8") == "new-line\n"
    assert (tmp_path / "role.log.1").read_text(encoding="utf-8").count("old-line") == 50
    assert lp.rotate_running_log(log, max_bytes=10_000) is False


def test_ci_env_carries_nothing_that_reaches_the_fleet():
    base = {
        "PATH": "/usr/bin", "HOME": "/home/x", "RENDER": "true", "ADMIN_TOKEN": "t",
        "SYNDICATE_REFRESH_STATE_URL": "redis://127.0.0.1:6379/0", "SYNDICATE_DATA_ROOT": "/d",
        "KALSHI_PRIVATE_KEY": "k", "ODDS_API_KEY": "o", "PYTHONPATH": "/repo",
    }
    env = lp.ci_env(base)
    assert env["PATH"] == "/usr/bin" and env["HOME"] == "/home/x"
    for key in ("RENDER", "ADMIN_TOKEN", "SYNDICATE_REFRESH_STATE_URL", "SYNDICATE_DATA_ROOT",
                "KALSHI_PRIVATE_KEY", "ODDS_API_KEY", "PYTHONPATH"):
        assert key not in env


def test_ensure_redis_durable_turns_aof_on(monkeypatch):
    import types

    calls = []

    class Fake:
        def __init__(self, value):
            self.value = value

        def config_get(self, key):
            return {key: self.value}

        def config_set(self, key, value):
            calls.append((key, value))

        def config_rewrite(self):
            calls.append(("rewrite",))

    fake_redis = types.SimpleNamespace(Redis=types.SimpleNamespace(from_url=lambda *a, **k: Fake("no")))
    monkeypatch.setitem(_sys.modules, "redis", fake_redis)
    assert lp.ensure_redis_durable("redis://x") == "aof=enabled+persisted"
    assert calls == [("appendonly", "yes"), ("rewrite",)]
    fake_redis.Redis.from_url = lambda *a, **k: Fake("yes")
    assert lp.ensure_redis_durable("redis://x") == "aof=already-on"


@pytest.mark.skipif(_shutil.which("rsync") is None, reason="backup uses rsync (Linux/WSL host)")
def test_backup_snapshots_hardlinks_unchanged_files_and_prunes(tmp_path):
    import json
    import os

    home = tmp_path / "home"
    data = home / "data" / "mlb_source"
    data.mkdir(parents=True)
    (data / "a.json").write_text("same", encoding="utf-8")
    (data / "x.lock").write_text("held", encoding="utf-8")
    dest = tmp_path / "backup"
    offdisk = tmp_path / "offdisk"
    args = lambda: lp.parse_args(["--home", str(home), "--state", "file", "backup", "--dest", str(dest), "--keep", "2",  # noqa: E731
                                  "--offdisk", str(offdisk), "--offdisk-keep", "1"])

    assert lp.cmd_backup(args()) == 0
    first = lp._complete_snapshots(dest)
    assert len(first) == 1
    manifest = json.loads((first[0] / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["snapshot_files"] == manifest["source_files_at_start"] == 1  # the lock is excluded
    assert not (first[0] / "data" / "mlb_source" / "x.lock").exists()

    import time
    for _ in range(2):
        time.sleep(1.1)  # snapshot names have one-second resolution
        (data / "b.json").write_text(str(time.time()), encoding="utf-8")
        assert lp.cmd_backup(args()) == 0
    snaps = lp._complete_snapshots(dest)
    assert len(snaps) == 2  # --keep 2 pruned the oldest
    assert not list(dest.glob("*.partial"))
    a_old = os.stat(snaps[0] / "data" / "mlb_source" / "a.json")
    a_new = os.stat(snaps[1] / "data" / "mlb_source" / "a.json")
    assert a_old.st_ino == a_new.st_ino  # unchanged file is hard-linked, not copied

    # the off-disk copy is ONE archive of the newest snapshot, pruned to --offdisk-keep
    import tarfile

    archives = sorted(offdisk.glob("*.tar.gz"))
    assert [p.name for p in archives] == [f"{snaps[1].name}.tar.gz"]
    assert not list(offdisk.glob("*.partial"))
    with tarfile.open(archives[0]) as tar:
        names = tar.getnames()
    assert f"{snaps[1].name}/manifest.json" in names
    assert f"{snaps[1].name}/data/mlb_source/a.json" in names


def test_default_backup_dirs(settings, monkeypatch):
    monkeypatch.delenv("SYNDICATE_LOCAL_BACKUP_DIR", raising=False)
    monkeypatch.delenv("SYNDICATE_LOCAL_BACKUP_OFFDISK_DIR", raising=False)
    # snapshots stay on the data root's filesystem (rsync needs mtimes; /mnt/c refuses utime)
    assert lp.default_backup_dir(settings, {}) == settings.home.parent / f"{settings.home.name}-backup"
    assert lp.default_backup_dir(settings, {"SYNDICATE_LOCAL_BACKUP_DIR": "/x"}) == Path("/x")
    assert lp.default_offdisk_dir({"SYNDICATE_LOCAL_BACKUP_OFFDISK_DIR": "/y"}) == Path("/y")


# --- `status` stale flag: runtime diff, not commit stamp (lane local-prod-stale-flag) --


@pytest.fixture()
def git_repo(tmp_path, monkeypatch):
    import subprocess

    base = tmp_path.resolve()
    (base / "gitconfig").write_text("")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(base / "gitconfig"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for key in ("GIT_AUTHOR", "GIT_COMMITTER"):
        monkeypatch.setenv(f"{key}_NAME", "test")
        monkeypatch.setenv(f"{key}_EMAIL", "test@example.invalid")
    repo = base / "repo"
    repo.mkdir()

    def git(*args):
        return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()

    def commit(path: str, text: str) -> str:
        target = repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        git("add", path)
        git("commit", "-q", "-m", path)
        return git("rev-parse", "HEAD")

    git("init", "-q")
    return repo, commit


def test_a_ledger_only_gap_is_not_stale(git_repo):
    repo, commit = git_repo
    loaded = commit("syndicate/app.py", "v1\n")
    head = commit(".syndicate/deploys.md", "entry\n")
    commit("docs/runbook.md", "x\n")
    head = commit("tests/test_x.py", "x\n")
    assert lp.runtime_files_between(loaded, head, repo) == []
    note = lp.code_stamp_note(loaded, head, diff=lambda a, b: lp.runtime_files_between(a, b, repo))
    assert "no role code changed -- nothing to load" in note and "STALE" not in note


def test_a_code_gap_is_stale_and_counted(git_repo):
    repo, commit = git_repo
    loaded = commit("syndicate/app.py", "v1\n")
    commit(".syndicate/deploys.md", "entry\n")
    head = commit("syndicate/app.py", "v2\n")
    assert lp.runtime_files_between(loaded, head, repo) == ["syndicate/app.py"]
    note = lp.code_stamp_note(loaded, head, diff=lambda a, b: lp.runtime_files_between(a, b, repo))
    assert "STALE -- 1 runtime file(s) changed" in note


def test_an_undiffable_commit_reads_stale_not_current(git_repo):
    # Unknown must not take the permissive branch.
    repo, commit = git_repo
    head = commit("syndicate/app.py", "v1\n")
    assert lp.runtime_files_between("0" * 40, head, repo) is None
    note = lp.code_stamp_note("0" * 40, head, diff=lambda a, b: lp.runtime_files_between(a, b, repo))
    assert "STALE?" in note and "treat as stale" in note


def test_a_supervisor_only_gap_does_not_mark_roles_stale(git_repo):
    # No role imports the supervisor or the host install tooling.
    repo, commit = git_repo
    loaded = commit("syndicate/app.py", "v1\n")
    commit("scripts/local_production.py", "supervisor v2\n")
    head = commit("deploy/local/install_windows_task.ps1", "x\n")
    assert lp.runtime_files_between(loaded, head, repo) == []
    head2 = commit("scripts/run_refresh_worker.py", "worker v2\n")   # a role entrypoint IS runtime
    assert lp.runtime_files_between(loaded, head2, repo) == ["scripts/run_refresh_worker.py"]


def test_same_commit_has_no_note():
    assert lp.code_stamp_note("abc", "abc") == ""
