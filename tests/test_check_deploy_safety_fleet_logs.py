"""`check_deploy_safety.board_build_state` against the local WSL fleet's log.

Render's logs API sees nothing from the fleet, so the Render path read UNKNOWN
on every run there. The fleet log has no timestamps; order decides.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest import mock

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "check_deploy_safety.py"
spec = importlib.util.spec_from_file_location("check_deploy_safety_fleet_under_test", MODULE_PATH)
cds = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cds)

COMPLETE_BUILD = [
    "[intelligence_state] BUILD_SPAN_ENTER stage=pull_hot_artifacts date=2026-10-01",
    "noise line 2026-10-04T18:00:00Z",
    "[intelligence_state] BUILD_SPAN_ENTER stage=portfolio_commit date=2026-10-01",
    "[intelligence_state] BUILD_SPAN_EXIT stage=portfolio_commit elapsed_s=34.8",
    "[intelligence_state] BOARD_BUILD_TIMING wall_s=177.8 cpu_s=158.5 off_cpu_pct=10.8 ok=True",
]


def test_completed_build_is_idle_with_typical_from_wall_s():
    in_flight, facts = cds._fleet_board_build_state(COMPLETE_BUILD + ["tail noise"])
    assert in_flight is False
    assert facts["typical_build_seconds"] == 177
    assert facts["newest_build_complete"] == "1 log lines ago"


def test_enter_after_last_timing_is_in_flight():
    lines = COMPLETE_BUILD + [
        "[intelligence_state] BUILD_SPAN_ENTER stage=layer2_shortlist_build date=2026-10-01",
        "work",
    ]
    in_flight, facts = cds._fleet_board_build_state(lines)
    assert in_flight is True
    assert "stage=layer2_shortlist_build" in facts["newest_build_start"]
    assert "estimated_seconds_remaining" not in facts  # no log clock: never invented


def test_no_enter_is_unknown_not_clear():
    in_flight, facts = cds._fleet_board_build_state(["nothing", "here"])
    assert in_flight is None
    assert "no BUILD_SPAN_ENTER" in facts["reason"]


def test_sub_second_timings_do_not_set_typical():
    lines = COMPLETE_BUILD[:-1] + ["[intelligence_state] BOARD_BUILD_TIMING wall_s=0.2 ok=True"]
    _, facts = cds._fleet_board_build_state(lines)
    assert "typical_build_seconds" not in facts


@pytest.mark.parametrize(
    "url,fleet",
    [
        ("http://127.0.0.1:10000", True),
        ("http://localhost:10000", True),
        ("http://syndicate.localhost", True),
        ("https://syndicate-an21.onrender.com", False),
        (None, False),
    ],
)
def test_fleet_detection(url, fleet):
    assert cds._is_fleet_base_url(url) is fleet


def test_routing_fleet_reads_log_render_reads_api():
    """Reachability: the two arms are distinct, and the no-arg call (deploy_preflight's) stays on Render."""
    with mock.patch.object(cds, "_fleet_log_tail", return_value=COMPLETE_BUILD) as tail, \
         mock.patch.object(cds, "_load_render_key", return_value="") as key:
        fleet = cds.board_build_state("http://127.0.0.1:10000")
        render = cds.board_build_state()
    assert fleet[0] is False and tail.call_count == 1
    assert render[1].get("missing_api_key") is True and key.call_count == 1
    assert fleet != render


def test_unreadable_fleet_log_is_unknown():
    with mock.patch.object(cds, "_fleet_log_tail", side_effect=FileNotFoundError("gone")):
        in_flight, facts = cds.board_build_state("http://127.0.0.1:10000")
    assert in_flight is None
    assert "FileNotFoundError" in facts["reason"]


def test_reads_tail_of_a_real_file(tmp_path, monkeypatch):
    log = tmp_path / "refresh-worker.log"
    log.write_text("x" * 100 + "\n" + "\n".join(COMPLETE_BUILD) + "\n", encoding="utf-8")
    monkeypatch.setenv("SYNDICATE_FLEET_REFRESH_LOG", str(log))
    lines = cds._fleet_log_tail(max_bytes=10_000)
    assert lines[-1] == COMPLETE_BUILD[-1]


def _drain_ttl(base_url, *, fleet_lines, capsys):
    """Run `_run_drain` to an immediate idle and return (ttl_seconds, stdout)."""
    import syndicate.features.shared.deploy_drain as deploy_drain
    import syndicate.features.shared.refresh_state_store as store

    with mock.patch.object(store, "_state_backend_kind", return_value="keyvalue"), \
         mock.patch.object(deploy_drain, "request_drain") as request, \
         mock.patch.object(deploy_drain, "read_worker_state", return_value=({"in_flight": {}, "acked_drain_at": 9e12}, "idle")), \
         mock.patch.object(cds, "board_build_state", return_value=(False, {})), \
         mock.patch.object(cds, "refresh_worker_children", return_value=([], {"applicable": True})), \
         mock.patch.object(cds, "_fleet_log_tail", return_value=fleet_lines) as tail, \
         mock.patch.object(cds, "_expected_build_seconds", return_value=None) as render:
        assert cds._run_drain(owner="t", wait_seconds=30, base_url=base_url) == 0
    return request.call_args.kwargs["ttl_seconds"], tail.call_count, render.call_count, capsys.readouterr().out


def test_drain_ttl_reads_fleet_log_for_a_fleet_url(capsys):
    """Reachability: a build longer than the floor/3 moves the TTL only via the fleet arm."""
    from syndicate.features.shared.deploy_drain import _DEFAULT_TTL_SECONDS

    long_build = int(_DEFAULT_TTL_SECONDS) // 3 + 1000
    lines = COMPLETE_BUILD[:-1] + [f"[intelligence_state] BOARD_BUILD_TIMING wall_s={long_build}.0 ok=True"]
    ttl, tail_calls, render_calls, out = _drain_ttl("http://127.0.0.1:10000", fleet_lines=lines, capsys=capsys)
    assert ttl == long_build * 3
    assert (tail_calls, render_calls) == (1, 0)
    assert f"longest recent build {long_build}s" in out


def test_drain_ttl_render_path_unchanged(capsys):
    from syndicate.features.shared.deploy_drain import _DEFAULT_TTL_SECONDS

    ttl, tail_calls, render_calls, out = _drain_ttl(None, fleet_lines=COMPLETE_BUILD, capsys=capsys)
    assert ttl == int(_DEFAULT_TTL_SECONDS)
    assert (tail_calls, render_calls) == (0, 1)
    assert "unmeasurable" in out


def test_drain_ttl_floor_holds_for_a_typical_fleet_build(capsys):
    from syndicate.features.shared.deploy_drain import _DEFAULT_TTL_SECONDS

    ttl, _, _, out = _drain_ttl("http://127.0.0.1:10000", fleet_lines=COMPLETE_BUILD, capsys=capsys)
    assert ttl == int(_DEFAULT_TTL_SECONDS)  # 3 x 177.8s is under the floor
    assert "longest recent build 178s" in out


# --- `fleet-drain-e2e`: CLEAR needs the ack AND an idle board build ---------

REQ = 1_000.0


@pytest.mark.parametrize(
    "state,verdict,build,clear,why",
    [
        # The measured defect: idle, but published before the request (no ack).
        ({"in_flight": {}, "acked_drain_at": None}, "idle", False, False, "not acked"),
        ({"in_flight": {}, "acked_drain_at": REQ - 5}, "idle", False, False, "not acked"),
        ({"in_flight": {}, "acked_drain_at": REQ + 5}, "idle", True, False, "board build in flight"),
        ({"in_flight": {}, "acked_drain_at": REQ + 5}, "idle", None, False, "UNKNOWN"),
        ({"in_flight": {"mlb_sim": True}, "acked_drain_at": REQ + 5}, "busy", False, False, "worker busy"),
        (None, "unknown", False, False, "worker unknown"),
        ({"in_flight": {}, "acked_drain_at": REQ + 5}, "idle", False, True, ""),
    ],
)
def test_drain_clear_requires_ack_and_idle_build(state, verdict, build, clear, why):
    ok, why_not = cds._drain_clear(state, verdict, REQ, build)
    assert ok is clear
    assert why in why_not


def _patched_drain(read_states, build_states, wait_seconds, child_states=None):
    import syndicate.features.shared.deploy_drain as deploy_drain
    import syndicate.features.shared.refresh_state_store as store

    t = [REQ]
    with mock.patch.object(store, "_state_backend_kind", return_value="keyvalue"), \
         mock.patch.object(deploy_drain, "request_drain", return_value={"requested_at": REQ}), \
         mock.patch.object(deploy_drain, "read_worker_state", side_effect=read_states), \
         mock.patch.object(cds, "board_build_state", side_effect=build_states) as builds, \
         mock.patch.object(cds, "refresh_worker_children",
                           side_effect=child_states or (lambda *_: ([], {"applicable": True}))), \
         mock.patch.object(cds, "expected_build_seconds", return_value=None), \
         mock.patch("time.time", side_effect=lambda: t[0]), \
         mock.patch("time.sleep", side_effect=lambda s: t.__setitem__(0, t[0] + s)):
        rc = cds._run_drain(owner="t", wait_seconds=wait_seconds, base_url="http://127.0.0.1:10000")
    return rc, builds.call_count


def test_run_drain_waits_through_unacked_then_building_then_clears(capsys):
    """Reachability: the loop really polls past a stale idle and a running build."""
    unacked = ({"in_flight": {}, "acked_drain_at": None}, "idle")
    acked = ({"in_flight": {}, "acked_drain_at": REQ + 30}, "idle")
    rc, build_calls = _patched_drain(
        [unacked, acked, acked, acked], [(False, {}), (True, {}), (False, {})], wait_seconds=600
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert build_calls == 3
    assert "has not acked this drain yet" in out
    assert "board build in flight" in out
    assert "CLEAR: refresh-worker acked the drain" in out


def test_run_drain_never_acked_is_unknown_not_clear(capsys):
    unacked = ({"in_flight": {}, "acked_drain_at": None}, "idle")
    rc, _ = _patched_drain(lambda *_: unacked, lambda *_: (False, {}), wait_seconds=60)
    assert rc == 2
    assert "never acknowledged the drain" in capsys.readouterr().out


def test_run_drain_unknown_build_state_is_unknown_not_clear(capsys):
    acked = ({"in_flight": {}, "acked_drain_at": REQ + 30}, "idle")
    rc, _ = _patched_drain(lambda *_: acked, lambda *_: (None, {"reason": "log gone"}), wait_seconds=60)
    assert rc == 2
    assert "board build state unreadable: log gone" in capsys.readouterr().out


# --- `deploy-safety-worker-children`: every refresh-worker child blocks ------

SUP = (100, 1, 9000, "/venv/bin/python scripts/local_production.py --home /h up")
RW = (200, 100, 8000, "/venv/bin/python scripts/run_refresh_worker.py")
NFL = (300, 200, 85, "/venv/bin/python /home/u/Syndicate/scripts/generate_smartsim2_nfl_projections.py --season 2026 --week 4")
GRANDCHILD = (301, 300, 80, "/venv/bin/python -c helper")
ADHOC = (400, 50, 10, "/venv/bin/python scripts/run_refresh_worker.py")  # not under the supervisor
ADHOC_KID = (401, 400, 5, "/venv/bin/python scripts/should_not_count.py")
WEB = (500, 100, 9000, "/venv/bin/python -m gunicorn wsgi:application")


def test_worker_children_finds_descendants_under_the_supervised_worker_only():
    root, kids = cds._worker_children([SUP, RW, NFL, GRANDCHILD, ADHOC, ADHOC_KID, WEB])
    assert root == 200
    assert sorted(k["pid"] for k in kids) == [300, 301]
    nfl = next(k for k in kids if k["pid"] == 300)
    assert nfl["script"] == "generate_smartsim2_nfl_projections.py" and nfl["age_s"] == 85


def test_worker_children_none_when_idle_and_root_missing_when_unsupervised():
    assert cds._worker_children([SUP, RW, WEB]) == (200, [])
    assert cds._worker_children([ADHOC, ADHOC_KID]) == (None, [])


def test_refresh_worker_children_not_applicable_off_the_fleet():
    with mock.patch.object(cds, "_fleet_process_table") as table:
        assert cds.refresh_worker_children("https://syndicate-an21.onrender.com") == ([], {"applicable": False})
        assert cds.refresh_worker_children(None) == ([], {"applicable": False})
    assert table.call_count == 0  # Render / deploy_preflight never scan


def test_refresh_worker_children_unknown_on_scan_failure_or_missing_worker():
    with mock.patch.object(cds, "_fleet_process_table", side_effect=RuntimeError("wsl gone")):
        kids, facts = cds.refresh_worker_children("http://127.0.0.1:10000")
    assert kids is None and "wsl gone" in facts["reason"]
    with mock.patch.object(cds, "_fleet_process_table", return_value=[SUP, WEB]):
        kids, facts = cds.refresh_worker_children("http://127.0.0.1:10000")
    assert kids is None and "no refresh-worker" in facts["reason"]


def test_drain_clear_blocks_on_children_and_on_unknown_children():
    acked = {"in_flight": {}, "acked_drain_at": REQ + 5}
    kid = [{"pid": 300, "age_s": 85, "script": "generate_smartsim2_nfl_projections.py"}]
    ok, why = cds._drain_clear(acked, "idle", REQ, False, kid)
    assert not ok and "generate_smartsim2_nfl_projections.py (pid=300" in why
    ok, why = cds._drain_clear(acked, "idle", REQ, False, None)
    assert not ok and why == "refresh-worker child jobs UNKNOWN"
    assert cds._drain_clear(acked, "idle", REQ, False, []) == (True, "")


def test_run_drain_waits_for_the_child_job_to_exit(capsys):
    """Reachability: acked + idle + no build, but a child is running -> keep waiting."""
    acked = ({"in_flight": {}, "acked_drain_at": REQ + 30}, "idle")
    kid = [{"pid": 300, "age_s": 85, "script": "generate_smartsim2_nfl_projections.py"}]
    children = iter([(kid, {"applicable": True}), (kid, {"applicable": True}), ([], {"applicable": True})])
    rc, _ = _patched_drain(lambda *_: acked, lambda *_: (False, {}), wait_seconds=600,
                           child_states=lambda *_: next(children))
    out = capsys.readouterr().out
    assert rc == 0
    assert "refresh-worker child job running: generate_smartsim2_nfl_projections.py" in out
    assert "no board build or child job is in flight" in out


def test_run_drain_unknown_children_is_unknown_not_clear(capsys):
    acked = ({"in_flight": {}, "acked_drain_at": REQ + 30}, "idle")
    rc, _ = _patched_drain(lambda *_: acked, lambda *_: (False, {}), wait_seconds=60,
                           child_states=lambda *_: (None, {"applicable": True, "reason": "wsl gone"}))
    assert rc == 2
    assert "child processes unreadable: wsl gone" in capsys.readouterr().out


def _run_main(children_result, capsys):
    payload = {"state": {"sim_run_status": {"state": "finished", "exit_code": 0},
                         "latest_tick": {"anyLive": False, "result": {"state": "idle"}}}}
    with mock.patch.object(cds, "_load_admin_token", return_value="t"), \
         mock.patch.object(cds, "_get_json", return_value=payload), \
         mock.patch.object(cds, "board_build_state", return_value=(False, {"newest_build_complete": "x"})), \
         mock.patch.object(cds, "refresh_worker_children", return_value=children_result), \
         mock.patch("sys.argv", ["check_deploy_safety.py", "--base-url", "http://127.0.0.1:10000"]):
        rc = cds.main()
    return rc, capsys.readouterr().out


def test_main_blocks_on_a_child_job(capsys):
    kid = [{"pid": 300, "ppid": 200, "age_s": 85, "script": "generate_smartsim2_nfl_projections.py",
            "args": NFL[3]}]
    rc, out = _run_main((kid, {"applicable": True, "worker_pid": 200}), capsys)
    assert rc == 1
    assert "refresh-worker child job RUNNING: generate_smartsim2_nfl_projections.py (pid=300, age=85s)" in out


def test_main_clear_with_no_children_and_unknown_blocks(capsys):
    rc, out = _run_main(([], {"applicable": True, "worker_pid": 200}), capsys)
    assert rc == 0 and "refresh-worker child jobs: none (worker pid=200)" in out
    rc, out = _run_main((None, {"applicable": True, "reason": "wsl gone"}), capsys)
    assert rc == 1 and "refresh-worker child jobs UNKNOWN (wsl gone)" in out
