"""`SYNDICATE_LAYER2_SHORTLIST_PROFILE` reaches `build_layer2_shortlist` -- off != on.

Lane `board-build-stage-slowdown`, 2026-09-18. The profiler is armed on a real
build by an env var, so what a unit test can usefully pin is that the switch is
WIRED: on prints a `[profiler] layer2_shortlist` report naming the leaves under
the build, off prints nothing, arguments pass through, and the result is the
body's result either way. The real build publishes game chips, which is not what
this file is about, so the decorator is exercised on a stub body -- and the real
`build_layer2_shortlist` is checked to BE decorated with it.
"""

from __future__ import annotations

import inspect

import pytest

from pipeline import layer2_shortlist

ENV = "SYNDICATE_LAYER2_SHORTLIST_PROFILE"


def _stub_leaf_that_burns_a_little(n: int) -> int:
    return sum(i * i for i in range(n))


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    monkeypatch.delenv(ENV, raising=False)
    yield


@pytest.fixture
def build():
    calls = []

    @layer2_shortlist._profiled_by_date(ENV, label="layer2_shortlist")
    def stub_build(selected_date, sport_slugs, *, max_grid_rows_per_sport=None, horizon_days=None):
        calls.append((selected_date, list(sport_slugs), max_grid_rows_per_sport, horizon_days))
        return {"rows": [{"n": _stub_leaf_that_burns_a_little(20_000)}], "selected_date": selected_date}

    stub_build.calls = calls
    return stub_build


def test_the_real_builder_carries_the_hook_and_keeps_its_source():
    """The wiring half on the REAL function: decorated, and `inspect.getsource`
    still reaches the body (six other test files read it by name)."""
    fn = layer2_shortlist.build_layer2_shortlist
    assert fn.__wrapped__.__name__ == "build_layer2_shortlist"
    assert inspect.getsource(fn.__wrapped__) in inspect.getsource(fn)
    assert '@_profiled_by_date("SYNDICATE_LAYER2_SHORTLIST_PROFILE"' in inspect.getsource(fn)
    assert "install_measured_correlation" in inspect.getsource(fn)


def test_off_by_default_prints_no_profile(capsys, build):
    assert build("2026-09-18", ["mlb"])["selected_date"] == "2026-09-18"
    assert "[profiler] layer2_shortlist" not in capsys.readouterr().out


@pytest.mark.parametrize("value", ["all", "2026-09-18"])
def test_on_prints_a_profile_naming_the_leaves_under_the_build(monkeypatch, capsys, build, value):
    monkeypatch.setenv(ENV, value)
    build("2026-09-18", ["mlb"])
    out = capsys.readouterr().out
    assert "[profiler] layer2_shortlist" in out
    assert "_stub_leaf_that_burns_a_little" in out


@pytest.mark.parametrize("value", ["2026-09-19", "off"])
def test_another_date_or_off_is_not_profiled(monkeypatch, capsys, build, value):
    monkeypatch.setenv(ENV, value)
    build("2026-09-18", ["mlb"])
    assert "[profiler] layer2_shortlist" not in capsys.readouterr().out


def test_arguments_and_result_pass_through_unchanged(monkeypatch, build):
    plain = build("2026-09-18", ["mlb", "nfl"], max_grid_rows_per_sport=7, horizon_days=2)
    monkeypatch.setenv(ENV, "all")
    profiled = build("2026-09-18", ["mlb", "nfl"], max_grid_rows_per_sport=7, horizon_days=2)
    assert profiled == plain
    assert build.calls == [("2026-09-18", ["mlb", "nfl"], 7, 2)] * 2
