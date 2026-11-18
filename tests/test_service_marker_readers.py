"""Every reader of a service marker reads the fleet's NEUTRAL `SYNDICATE_*` name, and nothing
reads a Render-era name any more (lane `render-config-retirement`, todo #766; user 2026-11-17:
"we should not depend on render at all", "go ahead with step 3", "drop the RENDER names too").

For each reader, four environments:
  neither  -- no marker at all (a laptop, CI);
  legacy   -- only the Render-era name (what the fleet carried until the 21:53Z 11-17 `up`);
  neutral  -- only the neutral name (what every role carries since then);
  both     -- both, one value.
Since step 3b the reader must answer neutral == both (the Render twin is ignored),
neutral != neither (REACHABILITY, `model_engine_standard`'s off != on rule), and
legacy == neither (the fallback is GONE).

Then a SOURCE test: no non-test file names a Render-era marker, outside an allowlist of two
(the launcher's stray-name strip and the env-reading tool's history table).
"""

from __future__ import annotations

import ast
import os
import subprocess
from pathlib import Path

import pytest

from syndicate.features.shared import service_identity as si

REPO = Path(__file__).resolve().parents[1]

# The Render-era twin of each neutral marker -- history, kept HERE only (the code no longer
# knows these names). Render also injected the four in `_RENDER_ONLY`.
_RENDER_TWIN = {
    "SYNDICATE_HOSTED": "RENDER",
    "SYNDICATE_SERVICE_NAME": "RENDER_SERVICE_NAME",
    "SYNDICATE_SERVICE_ID": "RENDER_SERVICE_ID",
    "SYNDICATE_INSTANCE_ID": "RENDER_INSTANCE_ID",
    "SYNDICATE_GIT_COMMIT": "RENDER_GIT_COMMIT",
    "SYNDICATE_EXTERNAL_URL": "RENDER_EXTERNAL_URL",
    "SYNDICATE_GIT_BRANCH": "RENDER_GIT_BRANCH",
}
_RENDER_ONLY = ("RENDER_SERVICE_TYPE", "RENDER_EXTERNAL_HOSTNAME", "RENDER_GIT_REPO_SLUG", "RENDER_DISCOVERY_SERVICE")
_RENDER_MARKERS = set(_RENDER_TWIN.values()) | set(_RENDER_ONLY)

# Keys that some readers consult BEFORE the marker; cleared so the marker branch decides.
_OVERRIDES = (
    "SYNDICATE_WEB_DYNO", "SYNDICATE_REQUIRE_HOSTED_STORAGE", "SYNDICATE_REFRESH_LANE",
    "SYNDICATE_DISK_COMPACTION", "SYNDICATE_SERVICE_ROLE", "GIT_COMMIT", "SOURCE_VERSION",
    "GIT_BRANCH", "SYNDICATE_REFRESH_STATE_BACKEND", "SYNDICATE_REPORTS_ROOT", "SYNDICATE_STATE_ROOT",
)


def _clear(monkeypatch) -> None:
    for name in si.ALL_MARKER_NAMES + tuple(sorted(_RENDER_MARKERS)) + _OVERRIDES:
        monkeypatch.delenv(name, raising=False)


def _four(monkeypatch, markers: dict[str, str], read, *, setup=None) -> dict[str, object]:
    """`read()` under neither / legacy / neutral / both for the given {neutral: value}."""
    out: dict[str, object] = {}
    for mode in ("neither", "legacy", "neutral", "both"):
        _clear(monkeypatch)
        if setup:
            setup()
        for neutral, value in markers.items():
            if mode in ("neutral", "both"):
                monkeypatch.setenv(neutral, value)
            if mode in ("legacy", "both"):
                monkeypatch.setenv(_RENDER_TWIN[neutral], value)
        try:
            out[mode] = read()
        except Exception as exc:  # a reader that RAISES off-host is still an answer
            out[mode] = f"raised {type(exc).__name__}"
    return out


def _assert_reachable_and_equivalent(results: dict[str, object]) -> None:
    """Step 3b: the neutral name decides, the Render twin changes nothing."""
    assert results["neutral"] == results["both"], results
    assert results["neutral"] != results["neither"], results
    assert results["legacy"] == results["neither"], results  # no Render fallback


# --- the helper itself ------------------------------------------------------------------

def test_only_the_neutral_name_counts(monkeypatch) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv("RENDER", "true")
    assert si.service_marker("SYNDICATE_HOSTED") is None  # the Render name means nothing now
    assert si.service_marker_key("SYNDICATE_HOSTED") is None
    monkeypatch.setenv("SYNDICATE_HOSTED", "true")
    assert si.service_marker("SYNDICATE_HOSTED") == "true"
    assert si.service_marker_key("SYNDICATE_HOSTED") == "SYNDICATE_HOSTED"
    with pytest.raises(KeyError):
        si.service_marker("RENDER")


def test_environ_markers_decodes_only_neutral_marker_keys() -> None:
    blob = b"KALSHI_PRIVATE_KEY=secret\x00RENDER_SERVICE_NAME=local-refresh-worker\x00SYNDICATE_SERVICE_NAME=x\x00junk"
    assert si.environ_markers(blob) == {"SYNDICATE_SERVICE_NAME": "x"}


def test_scrub_removes_every_marker() -> None:
    env = {name: "1" for name in si.SERVICE_MARKERS}
    env.update(OTHER="1")
    assert si.scrub(env) == {"OTHER": "1"}


# --- H1 "hosted web" --------------------------------------------------------------------

@pytest.mark.parametrize("marker,value", [
    ("SYNDICATE_HOSTED", "true"), ("SYNDICATE_SERVICE_ID", "local-web"), ("SYNDICATE_EXTERNAL_URL", "https://x.test")])
def test_app_hosted_web_predicate(monkeypatch, marker, value) -> None:
    from syndicate import app as app_module

    _assert_reachable_and_equivalent(_four(monkeypatch, {marker: value}, app_module._is_web_role))


@pytest.mark.parametrize("module", [
    "syndicate.blueprints.home", "syndicate.features.mlb.cards", "syndicate.features.wnba.cards",
    "syndicate.features.shared.game_board_contract"])
@pytest.mark.parametrize("marker,value", [
    ("SYNDICATE_HOSTED", "true"), ("SYNDICATE_SERVICE_ID", "local-web"), ("SYNDICATE_EXTERNAL_URL", "https://x.test")])
def test_web_dyno_predicates(monkeypatch, module, marker, value) -> None:
    import importlib

    mod = importlib.import_module(module)
    _assert_reachable_and_equivalent(_four(monkeypatch, {marker: value}, mod._is_web_role))


def test_nba_web_dyno_predicate(monkeypatch) -> None:
    from syndicate.features.nba import cards

    _assert_reachable_and_equivalent(_four(monkeypatch, {"SYNDICATE_HOSTED": "true"}, cards._is_web_role))


def test_web_dyno_override_still_comes_first(monkeypatch) -> None:
    from syndicate.features.mlb import cards

    _clear(monkeypatch)
    monkeypatch.setenv("SYNDICATE_HOSTED", "true")
    monkeypatch.setenv("SYNDICATE_WEB_DYNO", "false")
    assert cards._is_web_role() is False


@pytest.mark.parametrize("marker,value", [
    ("SYNDICATE_HOSTED", "true"), ("SYNDICATE_SERVICE_ID", "local-web"), ("SYNDICATE_EXTERNAL_URL", "https://x.test")])
def test_portfolio_auth_hosted(monkeypatch, marker, value) -> None:
    from syndicate.features.shared import portfolio_auth

    _assert_reachable_and_equivalent(_four(monkeypatch, {marker: value}, portfolio_auth._is_hosted))


# --- H2 "hosted storage" ----------------------------------------------------------------

def test_intelligence_hosted_request(monkeypatch) -> None:
    from syndicate.blueprints import intelligence

    _assert_reachable_and_equivalent(_four(monkeypatch, {"SYNDICATE_HOSTED": "true"}, intelligence._is_hosted_request))


def test_refresh_state_store_hosted_branches(monkeypatch, tmp_path) -> None:
    from syndicate.features.shared import refresh_state_store as rss

    _assert_reachable_and_equivalent(_four(monkeypatch, {"SYNDICATE_HOSTED": "true"}, rss._strict_hosted_storage_enabled))

    def backend():
        return rss._refresh_state_backend_name()

    _assert_reachable_and_equivalent(_four(
        monkeypatch, {"SYNDICATE_HOSTED": "true"}, backend,
        setup=lambda: monkeypatch.setenv("SYNDICATE_REFRESH_STATE_URL", "redis://127.0.0.1:1/0")))

    def strict_reports_root():
        return str(rss.reports_root())

    _assert_reachable_and_equivalent(_four(
        monkeypatch, {"SYNDICATE_HOSTED": "true"}, strict_reports_root,
        setup=lambda: monkeypatch.setenv("SYNDICATE_REQUIRE_HOSTED_STORAGE", "true")))


def test_source_roots_hosted_branches(monkeypatch, tmp_path) -> None:
    from syndicate.features.shared import source_roots

    _assert_reachable_and_equivalent(_four(monkeypatch, {"SYNDICATE_HOSTED": "true"}, source_roots._strict_hosted_storage_enabled))

    def roots():
        source_roots.clear_source_root_caches()
        return [str(p) for p in source_roots.preferred_source_roots(
            REPO / "syndicate" / "features" / "mlb" / "cards.py", env_var="SYNDICATE_TEST_ROOT_UNSET", local_dir_name="mlb_source")]

    monkeypatch.delenv("SYNDICATE_TEST_ROOT_UNSET", raising=False)
    monkeypatch.delenv("SYNDICATE_DATA_ROOT", raising=False)
    _assert_reachable_and_equivalent(_four(
        monkeypatch, {"SYNDICATE_HOSTED": "true"}, roots,
        setup=lambda: monkeypatch.setenv("SYNDICATE_REQUIRE_HOSTED_STORAGE", "true")))
    source_roots.clear_source_root_caches()


def test_request_path_guard_arms_on_the_neutral_name_only(monkeypatch) -> None:
    from syndicate.features.shared import request_path_guard as guard

    for marker, value in (("SYNDICATE_HOSTED", "true"), ("SYNDICATE_INSTANCE_ID", "local-web-1"),
                          ("SYNDICATE_SERVICE_NAME", "local-web"), ("SYNDICATE_SERVICE_ID", "local-web"),
                          ("SYNDICATE_EXTERNAL_URL", "https://x.test")):
        results = _four(monkeypatch, {marker: value}, guard.hosted_signal)
        assert results["neither"] is None
        assert results["legacy"] is None  # a Render name alone no longer arms it
        assert results["neutral"] == results["both"] == marker
        armed = _four(monkeypatch, {marker: value}, guard._is_hosted)
        _assert_reachable_and_equivalent(armed)


def test_disk_compaction_needs_the_hosted_marker(monkeypatch) -> None:
    from syndicate.features.shared import disk_compaction

    _assert_reachable_and_equivalent(_four(
        monkeypatch, {"SYNDICATE_HOSTED": "true"}, lambda: disk_compaction.disk_compaction_wanted("refresh-worker")))


# --- S "which service am I" -------------------------------------------------------------

@pytest.mark.parametrize("marker", ["SYNDICATE_SERVICE_NAME", "SYNDICATE_SERVICE_ID"])
def test_service_slugs(monkeypatch, marker) -> None:
    from syndicate.features.shared import disk_maintenance, win_prob_null_diag

    _assert_reachable_and_equivalent(_four(monkeypatch, {marker: "local-refresh-worker"}, disk_maintenance._service_slug))
    _assert_reachable_and_equivalent(_four(monkeypatch, {marker: "local-refresh-worker"}, win_prob_null_diag.service_slug))


def test_ops_refresh_identities(monkeypatch) -> None:
    from syndicate.features.shared import ops_refresh

    for marker in ("SYNDICATE_SERVICE_ID", "SYNDICATE_SERVICE_NAME"):
        _assert_reachable_and_equivalent(_four(monkeypatch, {marker: "local-refresh-worker"}, ops_refresh._this_service_identity))
    _assert_reachable_and_equivalent(_four(
        monkeypatch, {"SYNDICATE_INSTANCE_ID": "local-refresh-worker-1794930464"}, ops_refresh._this_instance_identity))


def test_artifact_retention_cursor(monkeypatch, tmp_path) -> None:
    from syndicate.features.shared import artifact_retention

    _assert_reachable_and_equivalent(_four(
        monkeypatch, {"SYNDICATE_SERVICE_ID": "local-refresh-worker"}, lambda: artifact_retention._cursor_path(tmp_path).name,
        setup=lambda: monkeypatch.setenv("SYNDICATE_REPORTS_ROOT", str(tmp_path / "reports"))))


def test_soccer_prekickoff_tag_and_metrics_role(monkeypatch) -> None:
    from scripts import build_soccer_artifacts
    from syndicate.features.shared import opportunity_contract_metrics

    _assert_reachable_and_equivalent(_four(
        monkeypatch, {"SYNDICATE_SERVICE_NAME": "local-live-odds-worker"}, build_soccer_artifacts._prekickoff_service_tag))
    _assert_reachable_and_equivalent(_four(
        monkeypatch, {"SYNDICATE_SERVICE_NAME": "local-web"}, lambda: opportunity_contract_metrics.snapshot()["service_role"]))


def _fake_proc(root: Path, pid: int, environ: dict[str, str], *, job: bool = True) -> None:
    entry = root / str(pid)
    entry.mkdir(parents=True)
    cmd = b"python\x00scripts/run_refresh_odds_job.py\x00" if job else b"python\x00other.py\x00"
    (entry / "cmdline").write_bytes(cmd)
    (entry / "environ").write_bytes(b"\x00".join(f"{k}={v}".encode() for k, v in environ.items()))


def test_refresh_worker_counts_only_its_own_jobs(monkeypatch, tmp_path) -> None:
    """The throttle that once counted live-odds-worker's jobs as refresh-worker's
    (2026-10-03: 17 of 18 ticks JOB_CAP_THROTTLED). A job carrying only a Render-era name
    is now a job with NO name, and counts (unknown must not read low)."""
    from scripts import run_refresh_worker as rrw

    for child_style in ("legacy", "neutral", "both"):
        root = tmp_path / child_style
        mine, theirs = "local-refresh-worker", "local-live-odds-worker"

        def env_for(service: str) -> dict[str, str]:
            if child_style == "legacy":
                return {"RENDER_SERVICE_NAME": service}
            if child_style == "neutral":
                return {"SYNDICATE_SERVICE_NAME": service}
            return {"SYNDICATE_SERVICE_NAME": service, "RENDER_SERVICE_NAME": service}

        _fake_proc(root, 101, env_for(mine))
        _fake_proc(root, 102, env_for(theirs))
        _fake_proc(root, 103, env_for(theirs))
        _fake_proc(root, 104, {})  # no name: counts (unknown must not read low)
        _fake_proc(root, 105, env_for(theirs), job=False)
        results = _four(monkeypatch, {"SYNDICATE_SERVICE_NAME": mine}, lambda: rrw._running_job_process_count(root))
        assert results["neither"] == results["legacy"] == 4  # no own neutral name: nothing filtered
        expected = 4 if child_style == "legacy" else 2  # Render-named children read as unnamed
        assert results["neutral"] == results["both"] == expected, (child_style, results)


# --- C "which commit" -------------------------------------------------------------------

def test_commit_readers(monkeypatch) -> None:
    from syndicate.features.shared import model_version, win_prob_null_diag, worker_shutdown

    def code_version():
        model_version.code_version.cache_clear()
        return model_version.code_version()

    sha = "0123456789abcdef0123"
    _assert_reachable_and_equivalent(_four(monkeypatch, {"SYNDICATE_GIT_COMMIT": sha}, code_version))
    model_version.code_version.cache_clear()
    _assert_reachable_and_equivalent(_four(monkeypatch, {"SYNDICATE_GIT_COMMIT": sha}, win_prob_null_diag._commit))
    _assert_reachable_and_equivalent(_four(
        monkeypatch, {"SYNDICATE_GIT_COMMIT": sha}, lambda: worker_shutdown.build_shutdown_record("w", "SIGTERM")["commit"]))


# --- the launcher sets the neutral markers, and scrubbers remove them -------------------

def test_launcher_table_is_the_helper_table() -> None:
    from scripts import local_production as lp

    assert lp.SERVICE_MARKERS == si.SERVICE_MARKERS


@pytest.mark.parametrize("state", ["redis", "file"])
def test_launcher_sets_only_the_neutral_markers(tmp_path, state) -> None:
    """Step 3a (user "go ahead with step 3", 2026-11-17): no role env carries a Render-era
    marker, stray ones from the operator shell included; each neutral marker carries
    exactly the value its Render twin used to."""
    from scripts import local_production as lp

    spec = lp.load_role_spec()
    settings = lp.Settings(home=tmp_path, state=state)
    stray = {name: "stray" for name in si.ALL_MARKER_NAMES + tuple(sorted(_RENDER_MARKERS))}
    for role in lp.ROLE_ORDER:
        env, _ = lp.derive_role_env(role, spec, {"SYNDICATE_PUBLIC_URL": "https://x.test"}, settings,
                                    base_env=dict(stray), instance_id=f"local-{role}-1794930464")
        assert not _RENDER_MARKERS & set(env), role  # stray Render names are stripped too
        assert env["SYNDICATE_SERVICE_NAME"] == env["SYNDICATE_SERVICE_ID"] == f"local-{role}"
        assert env["SYNDICATE_INSTANCE_ID"] == f"local-{role}-1794930464"
        assert env["SYNDICATE_EXTERNAL_URL"] == "https://x.test"
        assert "SYNDICATE_GIT_BRANCH" not in env  # a stray one is stripped, and nothing sets it
        if state == "redis":
            assert env["SYNDICATE_HOSTED"] == "true"
        else:
            assert "SYNDICATE_HOSTED" not in env


def test_readers_on_the_launcher_env_and_on_a_render_named_env(monkeypatch, tmp_path) -> None:
    """The load-bearing readers on the env the launcher builds answer "hosted, this role";
    on the same values under the Render names they answer as if unmarked -- the fallback is
    gone, so a role must carry the neutral names (every role has since 21:53Z 11-17)."""
    from scripts import local_production as lp
    from syndicate import app as app_module
    from syndicate.features.shared import disk_compaction, ops_refresh, portfolio_auth, source_roots
    from syndicate.features.shared import request_path_guard as guard

    spec = lp.load_role_spec()
    settings = lp.Settings(home=tmp_path)
    readers = {
        "app": app_module._is_web_role, "portfolio": portfolio_auth._is_hosted,
        "guard": guard._is_hosted, "strict": source_roots._strict_hosted_storage_enabled,
        "compaction": lambda: disk_compaction.disk_compaction_wanted("refresh-worker"),
        "service": ops_refresh._this_service_identity, "instance": ops_refresh._this_instance_identity,
    }
    for role in lp.ROLE_ORDER:
        env, _ = lp.derive_role_env(role, spec, {}, settings, base_env={}, instance_id=f"local-{role}-1")
        markers = {k: v for k, v in env.items() if k in si.SERVICE_MARKERS}
        answers = {}
        for style in ("neutral", "render", "none"):
            _clear(monkeypatch)
            if style != "none":
                for k, v in markers.items():
                    monkeypatch.setenv(k if style == "neutral" else _RENDER_TWIN[k], v)
            answers[style] = {name: read() for name, read in readers.items()}
        assert answers["neutral"]["app"] is True and answers["neutral"]["compaction"] is True
        assert answers["neutral"]["service"] == f"local-{role}"
        assert answers["render"] == answers["none"], role


def test_launcher_status_reads_prefer_the_neutral_name(monkeypatch) -> None:
    from scripts import local_production as lp

    class _Proc:
        def __init__(self, env):
            self._env = env

        def environ(self):
            return self._env

    import types

    envs = {
        1: {"RENDER_GIT_COMMIT": "old", "RENDER_INSTANCE_ID": "local-web-1794000000"},
        2: {"SYNDICATE_GIT_COMMIT": "new", "SYNDICATE_INSTANCE_ID": "local-web-1794111111"},
        3: {"SYNDICATE_GIT_COMMIT": "neutral", "RENDER_GIT_COMMIT": "legacy"},
    }
    monkeypatch.setitem(__import__("sys").modules, "psutil", types.SimpleNamespace(Process=lambda pid: _Proc(envs[pid])))
    assert lp.role_loaded_commit(1) is None  # Render names are not read any more
    assert lp.role_loaded_commit(2) == "new"
    assert lp.role_loaded_commit(3) == "neutral"
    assert lp.role_spawn_stamp(1) is None
    assert lp.role_spawn_stamp(2) == 1794111111.0


def test_ci_steps_scrub_the_markers(monkeypatch) -> None:
    from scripts import run_ci_suite

    assert run_ci_suite.NEUTRAL_MARKER_ENV == si.SERVICE_MARKERS
    assert not hasattr(run_ci_suite, "RENDER_INJECTED_ENV")
    for name in si.ALL_MARKER_NAMES:
        monkeypatch.setenv(name, "x")
    env = run_ci_suite._step_env()
    assert not set(si.ALL_MARKER_NAMES) & set(env)


def test_replay_and_rehearsal_harnesses_clear_the_neutral_hosted_flag(monkeypatch, tmp_path) -> None:
    from scripts import fleet_local, replay_diff_gate

    monkeypatch.setenv("SYNDICATE_HOSTED", "true")
    env = replay_diff_gate._child_env(tmp_path)
    assert "SYNDICATE_HOSTED" not in env
    assert fleet_local.FORCED_ENV_BASE["SYNDICATE_HOSTED"] == ""
    assert "RENDER" not in fleet_local.FORCED_ENV_BASE


def test_mlb_base_url_reads_the_neutral_external_url() -> None:
    text = (REPO / "scripts" / "refresh_mlb_oddsapi.py").read_text(encoding="utf-8")
    assert '"SYNDICATE_EXTERNAL_URL"' in text and '"RENDER_EXTERNAL_URL"' not in text


# --- nothing reads a Render marker any other way ----------------------------------------

# file -> why it may still NAME a Render marker. Neither reads one from the environment.
_ALLOWED = {
    "scripts/local_production.py": "strips stray RENDER* names from the operator's shell before building a role env",
    "scripts/fleet_role_env_reading.py": "the before/after reading's history table (--render-markers-step3); reads no env by name",
}


def _render_marker_constants(source: str) -> list[tuple[int, object]]:
    """(line, constant) for every string equal to a Render-era marker name, and every bytes
    constant starting `RENDER`. A docstring or comment cannot EQUAL a bare key name, so this
    finds the strings code uses as env keys, not prose about them."""
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        tree = ast.parse(source)
    found = []
    for node in ast.walk(tree):
        value = node.value if isinstance(node, ast.Constant) else None
        if (isinstance(value, str) and value in _RENDER_MARKERS) or (
                isinstance(value, bytes) and value.startswith(b"RENDER")):
            found.append((node.lineno, value))
    return found


def test_the_scan_flags_a_direct_read() -> None:
    # Positive control: what this lane removed would be caught if it came back.
    assert _render_marker_constants('import os\nx = os.environ.get("RENDER_SERVICE_NAME")\n') == [(2, "RENDER_SERVICE_NAME")]
    assert _render_marker_constants('p = b"RENDER_SERVICE_NAME="\n') == [(1, b"RENDER_SERVICE_NAME=")]
    assert _render_marker_constants('"""RENDER is prose here."""\n# os.environ.get("RENDER")\n') == []


def test_no_non_test_file_reads_a_render_marker_directly() -> None:
    files = subprocess.run(["git", "ls-files", "*.py"], cwd=str(REPO), capture_output=True, text=True,
                           check=True).stdout.split()
    offenders: list[str] = []
    scanned = 0
    for rel in files:
        if rel.startswith(("tests/", "vendor/", "data/")) or "/tests/" in rel or rel.startswith(".claude/hooks/test_"):
            continue
        if rel in _ALLOWED:
            continue
        try:
            found = _render_marker_constants((REPO / rel).read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError, FileNotFoundError):
            continue
        scanned += 1
        offenders += [f"{rel}:{line} {value!r}" for line, value in found]
    assert scanned > 500  # the walk really covered the repo
    assert offenders == [], offenders


def test_the_allowlist_has_no_dead_entries() -> None:
    for rel in _ALLOWED:
        text = (REPO / rel).read_text(encoding="utf-8")
        assert any(f'"{m}"' in text for m in _RENDER_MARKERS), rel
