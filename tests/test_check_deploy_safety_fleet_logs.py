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
         mock.patch.object(deploy_drain, "read_worker_state", return_value=({"in_flight": {}}, "idle")), \
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
