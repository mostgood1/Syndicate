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
