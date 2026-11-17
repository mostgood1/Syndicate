"""Every reader of a service marker prefers the NEUTRAL name and falls back on the Render-era
one, and gives the same answer either way (lane `render-config-retirement`, todo #766, user
2026-11-17: "we should not depend on render at all").

For each reader, four environments:
  neither  -- no marker at all (a laptop, CI);
  legacy   -- only the Render-era name (a role started before the launcher set both);
  neutral  -- only the neutral name (what step 3 will leave);
  both     -- both, one value (what the launcher sets now).
The reader must answer legacy == neutral == both (EQUIVALENCE: loading the launcher change
changes nothing) and neutral != neither (REACHABILITY: the branch really reads the neutral
name, `model_engine_standard`'s off != on rule).

Then a SOURCE test: no non-test file reads a Render-era marker except through
`service_identity`, outside an allowlist of scrubbers and the two tables.
"""

from __future__ import annotations

import ast
import os
import subprocess
from pathlib import Path

import pytest

from syndicate.features.shared import service_identity as si

REPO = Path(__file__).resolve().parents[1]

# Keys that some readers consult BEFORE the marker; cleared so the marker branch decides.
_OVERRIDES = (
    "SYNDICATE_WEB_DYNO", "SYNDICATE_REQUIRE_HOSTED_STORAGE", "SYNDICATE_REFRESH_LANE",
    "SYNDICATE_DISK_COMPACTION", "SYNDICATE_SERVICE_ROLE", "GIT_COMMIT", "SOURCE_VERSION",
    "GIT_BRANCH", "SYNDICATE_REFRESH_STATE_BACKEND", "SYNDICATE_REPORTS_ROOT", "SYNDICATE_STATE_ROOT",
)


def _clear(monkeypatch) -> None:
    for name in si.ALL_MARKER_NAMES + _OVERRIDES:
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
                monkeypatch.setenv(si.NEUTRAL_TO_RENDER[neutral], value)
        try:
            out[mode] = read()
        except Exception as exc:  # a reader that RAISES off-host is still an answer
            out[mode] = f"raised {type(exc).__name__}"
    return out


def _assert_reachable_and_equivalent(results: dict[str, object]) -> None:
    assert results["legacy"] == results["neutral"] == results["both"], results
    assert results["neutral"] != results["neither"], results


# --- the helper itself ------------------------------------------------------------------

def test_neutral_name_wins_when_present_even_empty(monkeypatch) -> None:
    _clear(monkeypatch)
    assert si.service_marker("SYNDICATE_HOSTED") is None
    monkeypatch.setenv("RENDER", "true")
    assert si.service_marker("SYNDICATE_HOSTED") == "true"
    assert si.service_marker_key("SYNDICATE_HOSTED") == "RENDER"
    monkeypatch.setenv("SYNDICATE_HOSTED", "")
    assert si.service_marker("SYNDICATE_HOSTED") == ""
    assert si.service_marker_key("SYNDICATE_HOSTED") == "SYNDICATE_HOSTED"
    with pytest.raises(KeyError):
        si.service_marker("RENDER")  # readers ask by the NEUTRAL name only


def test_environ_markers_decodes_only_marker_keys() -> None:
    blob = b"KALSHI_PRIVATE_KEY=secret\x00RENDER_SERVICE_NAME=local-refresh-worker\x00SYNDICATE_SERVICE_NAME=x\x00junk"
    assert si.environ_markers(blob) == {"RENDER_SERVICE_NAME": "local-refresh-worker", "SYNDICATE_SERVICE_NAME": "x"}


def test_marker_env_and_scrub_cover_both_spellings() -> None:
    both = si.marker_env({"SYNDICATE_HOSTED": "true", "SYNDICATE_GIT_COMMIT": "abc"})
    assert both == {"SYNDICATE_HOSTED": "true", "RENDER": "true", "SYNDICATE_GIT_COMMIT": "abc", "RENDER_GIT_COMMIT": "abc"}
    env = dict(both, OTHER="1", RENDER_EXTERNAL_HOSTNAME="h")
    assert si.scrub(env) == {"OTHER": "1"}


# --- H1 "hosted web" --------------------------------------------------------------------

@pytest.mark.parametrize("marker,value", [
    ("SYNDICATE_HOSTED", "true"), ("SYNDICATE_SERVICE_ID", "local-web"), ("SYNDICATE_EXTERNAL_URL", "https://x.test")])
def test_app_hosted_web_predicate(monkeypatch, marker, value) -> None:
    from syndicate import app as app_module

    _assert_reachable_and_equivalent(_four(monkeypatch, {marker: value}, app_module._is_render_web_dyno))


@pytest.mark.parametrize("module", [
    "syndicate.blueprints.home", "syndicate.features.mlb.cards", "syndicate.features.wnba.cards",
    "syndicate.features.shared.game_board_contract"])
@pytest.mark.parametrize("marker,value", [
    ("SYNDICATE_HOSTED", "true"), ("SYNDICATE_SERVICE_ID", "local-web"), ("SYNDICATE_EXTERNAL_URL", "https://x.test")])
def test_web_dyno_predicates(monkeypatch, module, marker, value) -> None:
    import importlib

    mod = importlib.import_module(module)
    _assert_reachable_and_equivalent(_four(monkeypatch, {marker: value}, mod._render_web_dyno))


def test_nba_web_dyno_predicate(monkeypatch) -> None:
    from syndicate.features.nba import cards

    _assert_reachable_and_equivalent(_four(monkeypatch, {"SYNDICATE_HOSTED": "true"}, cards._render_web_dyno))


def test_web_dyno_override_still_comes_first(monkeypatch) -> None:
    from syndicate.features.mlb import cards

    _clear(monkeypatch)
    monkeypatch.setenv("SYNDICATE_HOSTED", "true")
    monkeypatch.setenv("SYNDICATE_WEB_DYNO", "false")
    assert cards._render_web_dyno() is False


@pytest.mark.parametrize("marker,value", [
    ("SYNDICATE_HOSTED", "true"), ("SYNDICATE_SERVICE_ID", "local-web"), ("SYNDICATE_EXTERNAL_URL", "https://x.test")])
def test_portfolio_auth_hosted(monkeypatch, marker, value) -> None:
    from syndicate.features.shared import portfolio_auth

    _assert_reachable_and_equivalent(_four(monkeypatch, {marker: value}, portfolio_auth._on_render))


# --- H2 "hosted storage" ----------------------------------------------------------------

def test_intelligence_hosted_request(monkeypatch) -> None:
    from syndicate.blueprints import intelligence

    _assert_reachable_and_equivalent(_four(monkeypatch, {"SYNDICATE_HOSTED": "true"}, intelligence._render_hosted_request))


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


def test_request_path_guard_arms_on_either_spelling(monkeypatch) -> None:
    from syndicate.features.shared import request_path_guard as guard

    for marker, value in (("SYNDICATE_HOSTED", "true"), ("SYNDICATE_INSTANCE_ID", "local-web-1"),
                          ("SYNDICATE_SERVICE_NAME", "local-web"), ("SYNDICATE_SERVICE_ID", "local-web"),
                          ("SYNDICATE_EXTERNAL_URL", "https://x.test")):
        results = _four(monkeypatch, {marker: value}, guard.hosted_signal)
        assert results["neither"] is None
        assert results["legacy"] == si.NEUTRAL_TO_RENDER[marker]  # names the key that armed it
        assert results["neutral"] == results["both"] == marker
        armed = _four(monkeypatch, {marker: value}, guard._is_render_hosted)
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


def test_refresh_worker_counts_only_its_own_jobs_under_either_spelling(monkeypatch, tmp_path) -> None:
    """The throttle that once counted live-odds-worker's jobs as refresh-worker's
    (2026-10-03: 17 of 18 ticks JOB_CAP_THROTTLED)."""
    from scripts import run_refresh_worker as rrw

    for child_style in ("legacy", "neutral", "both"):
        root = tmp_path / child_style
        mine, theirs = "local-refresh-worker", "local-live-odds-worker"

        def env_for(service: str) -> dict[str, str]:
            if child_style == "legacy":
                return {"RENDER_SERVICE_NAME": service}
            if child_style == "neutral":
                return {"SYNDICATE_SERVICE_NAME": service}
            return si.marker_env({"SYNDICATE_SERVICE_NAME": service})

        _fake_proc(root, 101, env_for(mine))
        _fake_proc(root, 102, env_for(theirs))
        _fake_proc(root, 103, env_for(theirs))
        _fake_proc(root, 104, {})  # no name: counts (unknown must not read low)
        _fake_proc(root, 105, env_for(theirs), job=False)
        results = _four(monkeypatch, {"SYNDICATE_SERVICE_NAME": mine}, lambda: rrw._running_job_process_count(root))
        assert results["neither"] == 4  # no own name: nothing filtered (the old behaviour)
        assert results["legacy"] == results["neutral"] == results["both"] == 2, (child_style, results)


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


# --- the launcher sets both, and scrubbers remove both ----------------------------------

def test_launcher_table_is_the_helper_table() -> None:
    from scripts import local_production as lp

    assert lp.SERVICE_MARKERS == si.NEUTRAL_TO_RENDER


@pytest.mark.parametrize("state", ["redis", "file"])
def test_launcher_sets_each_marker_under_both_names_to_one_value(tmp_path, state) -> None:
    from scripts import local_production as lp

    spec = lp.load_role_spec()
    settings = lp.Settings(home=tmp_path, state=state)
    stray = {"SYNDICATE_HOSTED": "stray", "SYNDICATE_SERVICE_NAME": "stray", "RENDER_SERVICE_NAME": "stray"}
    for role in lp.ROLE_ORDER:
        env, _ = lp.derive_role_env(role, spec, {"SYNDICATE_PUBLIC_URL": "https://x.test"}, settings,
                                    base_env=dict(stray), instance_id=f"local-{role}-1794930464")
        for neutral, legacy in si.NEUTRAL_TO_RENDER.items():
            assert env.get(neutral) == env.get(legacy), (role, neutral)
        assert env["SYNDICATE_SERVICE_NAME"] == env["SYNDICATE_SERVICE_ID"] == f"local-{role}"
        assert env["SYNDICATE_INSTANCE_ID"] == f"local-{role}-1794930464"
        assert env["SYNDICATE_EXTERNAL_URL"] == "https://x.test"
        assert "SYNDICATE_GIT_BRANCH" not in env and "RENDER_GIT_BRANCH" not in env
        if state == "redis":
            assert env["SYNDICATE_HOSTED"] == env["RENDER"] == "true"
        else:
            assert "SYNDICATE_HOSTED" not in env and "RENDER" not in env  # a stray one is stripped too


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
        2: si.marker_env({"SYNDICATE_GIT_COMMIT": "new", "SYNDICATE_INSTANCE_ID": "local-web-1794111111"}),
        3: {"SYNDICATE_GIT_COMMIT": "neutral", "RENDER_GIT_COMMIT": "legacy"},
    }
    monkeypatch.setitem(__import__("sys").modules, "psutil", types.SimpleNamespace(Process=lambda pid: _Proc(envs[pid])))
    assert lp.role_loaded_commit(1) == "old"
    assert lp.role_loaded_commit(2) == "new"
    assert lp.role_loaded_commit(3) == "neutral"
    assert lp.role_spawn_stamp(1) == 1794000000.0
    assert lp.role_spawn_stamp(2) == 1794111111.0


def test_ci_steps_scrub_both_spellings(monkeypatch) -> None:
    from scripts import run_ci_suite

    assert run_ci_suite.NEUTRAL_MARKER_ENV == tuple(si.NEUTRAL_TO_RENDER)
    assert set(run_ci_suite.RENDER_INJECTED_ENV) == set(si.NEUTRAL_TO_RENDER.values()) | set(si.RENDER_ONLY_INJECTED)
    for name in si.ALL_MARKER_NAMES:
        monkeypatch.setenv(name, "x")
    env = run_ci_suite._step_env()
    assert not set(si.ALL_MARKER_NAMES) & set(env)


def test_replay_and_rehearsal_harnesses_clear_the_neutral_hosted_flag(monkeypatch, tmp_path) -> None:
    from scripts import fleet_local, replay_diff_gate

    monkeypatch.setenv("SYNDICATE_HOSTED", "true")
    monkeypatch.setenv("RENDER", "true")
    env = replay_diff_gate._child_env(tmp_path)
    assert "SYNDICATE_HOSTED" not in env and "RENDER" not in env
    assert fleet_local.FORCED_ENV_BASE["SYNDICATE_HOSTED"] == fleet_local.FORCED_ENV_BASE["RENDER"] == ""


def test_mlb_base_url_prefers_the_neutral_external_url() -> None:
    text = (REPO / "scripts" / "refresh_mlb_oddsapi.py").read_text(encoding="utf-8")
    assert '"SYNDICATE_EXTERNAL_URL", "RENDER_EXTERNAL_URL"' in text


# --- nothing reads a Render marker any other way ----------------------------------------

_RENDER_MARKERS = set(si.NEUTRAL_TO_RENDER.values()) | set(si.RENDER_ONLY_INJECTED)

# file -> why it may still NAME a Render marker. Each is a table, a scrubber, or a
# fallback that sits AFTER its neutral name.
_ALLOWED = {
    "syndicate/features/shared/service_identity.py": "the neutral -> Render table",
    "scripts/local_production.py": "SERVICE_MARKERS (pinned above) and the stray-RENDER strip",
    "scripts/run_ci_suite.py": "RENDER_INJECTED_ENV scrub list (pinned above)",
    "scripts/replay_diff_gate.py": "pops RENDER from the replay child (pinned above)",
    "scripts/fleet_local.py": "clears RENDER in the rehearsal env (pinned above)",
    "scripts/refresh_mlb_oddsapi.py": "RENDER_EXTERNAL_URL after SYNDICATE_EXTERNAL_URL (pinned above)",
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
