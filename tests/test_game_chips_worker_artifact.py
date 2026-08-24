"""The chip build moved off the request path. `#545`.

`/api/board/game-chips` used to call `build_game_chips` inline. That fans out
over every sport and, for soccer, over every league -- and `#545` widened it to
TWO matchdays per league to cover the board's forward horizon, so it became
twenty card-context builds for soccer alone, inside a request handler. The
worker-split rule forbids computation there outright; the widening is what made
it indefensible rather than merely against the rules.

So the worker publishes and the web reads.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared.game_chip_scoreboard import GAME_CHIP_DEFAULT_SPORTS


@pytest.fixture()
def reports_root(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNDICATE_REPORTS_ROOT", str(tmp_path))
    import pipeline.intelligence_state as state

    return state


def test_chips_round_trip_through_the_shared_store(reports_root):
    state = reports_root
    chips = [
        {"sport": "soccer", "game_key": "1", "matchup": "SEV @ ATH"},
        {"sport": "mlb", "game_key": "2", "matchup": "NYY @ BOS"},
    ]
    written = state.write_game_chips("2026-08-24", chips)
    assert written is not None
    assert written["chip_count"] == 2

    read = state.read_game_chips("2026-08-24")
    assert read is not None
    assert read["chip_count"] == 2
    assert [c["game_key"] for c in read["chips"]] == ["1", "2"]


def test_a_missing_date_is_not_an_error(reports_root):
    state = reports_root
    assert state.write_game_chips("", [{"sport": "mlb"}]) is None
    assert state.read_game_chips(None) is None
    assert state.read_game_chips("2099-01-01") is None


def test_the_count_is_stamped_so_thin_and_stale_are_distinguishable(reports_root):
    """A reader must not have to diff two payloads to tell them apart.

    `chip_count` and `written_at` answer different questions -- "did this build
    find anything" and "is this build recent" -- and a thin fresh build and a
    rich stale one are both bad in ways the other number cannot show.
    """
    state = reports_root
    written = state.write_game_chips("2026-08-24", [])
    assert written["chip_count"] == 0
    assert written["written_at"]
    assert state.read_game_chips("2026-08-24")["chips"] == []


def test_the_default_sport_list_is_shared_not_duplicated():
    """One list, or a sport silently loses its scoreboard.

    The worker builds for this list and the endpoint defaults to it. If they
    were two lists and drifted, the extra sport would serve a chip-less strip --
    which looks exactly like a sport with no games that day.
    """
    from syndicate.blueprints.intelligence import _GAME_CHIP_DEFAULT_SPORTS

    assert list(_GAME_CHIP_DEFAULT_SPORTS) == list(GAME_CHIP_DEFAULT_SPORTS)
    assert "soccer" in GAME_CHIP_DEFAULT_SPORTS


def test_the_endpoint_serves_the_artifact_and_says_so(reports_root, monkeypatch):
    state = reports_root
    state.write_game_chips(
        "2026-08-24",
        [
            {"sport": "soccer", "game_key": "1", "matchup": "SEV @ ATH"},
            {"sport": "mlb", "game_key": "2", "matchup": "NYY @ BOS"},
        ],
    )

    def _explode(*args, **kwargs):  # pragma: no cover - must never run
        raise AssertionError("the endpoint recomputed instead of reading the artifact")

    monkeypatch.setattr("syndicate.blueprints.intelligence.build_game_chips", _explode)

    from syndicate.app import app

    payload = app.test_client().get("/api/board/game-chips?date=2026-08-24&sports=soccer").get_json()
    assert payload["source"] == "worker_artifact"
    assert [c["game_key"] for c in payload["chips"]] == ["1"]
    assert payload["published_at"]


def test_the_requested_sport_filter_is_applied_to_the_published_chips(reports_root, monkeypatch):
    """The artifact holds every sport; a caller asking for one must get one.

    Serving the whole payload regardless of `sports` would put other sports'
    games into a strip that asked for soccer -- the same class of wrong-game
    error the chip join's collision guard exists to prevent.
    """
    state = reports_root
    state.write_game_chips("2026-08-24", [{"sport": "mlb", "game_key": "2"}])
    monkeypatch.setattr(
        "syndicate.blueprints.intelligence.build_game_chips",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not recompute")),
    )
    from syndicate.app import app

    payload = app.test_client().get("/api/board/game-chips?date=2026-08-24&sports=soccer").get_json()
    assert payload["source"] == "worker_artifact"
    assert payload["chips"] == []


def test_a_missing_artifact_falls_back_and_labels_itself(reports_root, monkeypatch):
    """The fallback is kept ON PURPOSE, and must be impossible to miss.

    Between a deploy and the worker's next shortlist build there is no artifact,
    and refusing to serve would blank every sport's scoreboard strip. That is a
    visible regression traded for a purity that buys the user nothing. What must
    NOT happen is the fallback becoming the silent status quo -- so it names
    itself in the response, where a reader can see the request fan-out `#545`
    removed is quietly still running.
    """
    monkeypatch.setattr(
        "syndicate.blueprints.intelligence.build_game_chips",
        lambda date, sports: [{"sport": "soccer", "game_key": "9"}],
    )
    from syndicate.app import app

    payload = app.test_client().get("/api/board/game-chips?date=2026-08-24&sports=soccer").get_json()
    assert payload["source"] == "fallback_inline_build"
    assert [c["game_key"] for c in payload["chips"]] == ["9"]
    assert payload["published_at"] is None
