"""`#430` — turning the worker's build-relative odds ages into a wall-clock instant.

THE ARITHMETIC IS THE WHOLE RISK. `seen_age_seconds` was measured against the
REFRESH WORKER's clock at artifact-build time, so a stored 120s in an artifact
built 40 minutes ago describes odds that are 42 minutes old, not 2. Serving the
stored number as if it were current understates every age by exactly the
artifact's own age -- which is the same class of error the field was added to
fix, reintroduced one layer up.

Local mirrors cannot cover this: every book-grid artifact in the checkout
predates last-seen tracking (5,547 rows, 0 with a `seen_age_seconds`, measured
2026-08-14 on `book_grid_2026-08-09.json`), so a local board only ever exercises
the unknown path. Production carries the field. These stub the reader so the
numeric path is tested at all.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from syndicate.app import create_app


ARTIFACT_BUILT_AT = "2026-08-14T14:58:49.145798+00:00"


def _row(seen_age, move_age=None, event_id="evt-1", state="pregame"):
    row = {
        "sport": "mlb",
        "event_id": event_id,
        "kind": "game",
        "market": "h2h",
        "segment": "full",
        "sides": ["away", "home"],
        "away_team": "St. Louis Cardinals",
        "home_team": "Chicago Cubs",
        "commence_time": "2026-08-14T18:20:00Z",
        "game": {"state": state},
        "books": ["draftkings"],
        "cells": {"draftkings": {"away": {"price": 163}, "home": {"price": -180}}},
    }
    if seen_age is not None:
        row["seen_age_seconds"] = seen_age
    if move_age is not None:
        row["age_seconds"] = move_age
    return row


@pytest.fixture()
def board_client(monkeypatch):
    """A client whose artifact reader is ours, so the ages under test are known."""

    def _install(rows, generated_at=ARTIFACT_BUILT_AT):
        import syndicate.features.shared.book_grid_artifact as artifact_module

        def _fake_read(sport, date):  # noqa: ARG001 - signature must match
            if date != "2026-08-14":
                return None
            return {"rows": rows, "generated_at": generated_at, "version": 4}

        monkeypatch.setattr(artifact_module, "read_book_grid_artifact", _fake_read)
        app = create_app()
        app.testing = True
        return app.test_client()

    return _install


def _fetch(client, **params):
    query = "&".join(f"{k}={v}" for k, v in {"sport": "mlb", "date": "2026-08-14", **params}.items())
    response = client.get(f"/api/board/layer1?{query}")
    assert response.status_code == 200
    return json.loads(response.get_data(as_text=True))


def test_the_age_is_re_anchored_to_the_artifacts_build_time(board_client):
    """The measured production shape, reproduced exactly.

    On 2026-08-14 15:00Z the MLB board's artifact was built at 14:58:49Z with a
    minimum `seen_age_seconds` of 6576.8 -- so the freshest quote on the board
    was observed at 13:09:12Z, 1h51m before the read. The header said "built 2m
    old" and that was the only age on the page.
    """
    client = board_client([_row(seen_age=6576.8)])

    board = _fetch(client)

    observed = datetime.fromisoformat(board["odds_freshness"]["odds_observed_at"])
    built = datetime.fromisoformat(ARTIFACT_BUILT_AT)
    assert observed == built - timedelta(seconds=6576.8)
    # The stated instant, not just the offset: a sign error would still satisfy
    # the subtraction above if it were written as an absolute difference.
    assert observed.strftime("%Y-%m-%dT%H:%M:%S") == "2026-08-14T13:09:12"
    # And the input to the subtraction is served too, so a reader can check it.
    assert board["odds_freshness"]["artifact_generated_at"] == ARTIFACT_BUILT_AT


def test_odds_age_is_older_than_board_age_and_the_two_are_separate_fields(board_client):
    """Never one number. The board really had just rebuilt; the odds had not."""
    client = board_client([_row(seen_age=6576.8)])

    board = _fetch(client)

    assert board["generated_at"] == ARTIFACT_BUILT_AT
    assert board["odds_freshness"]["odds_observed_at"] < board["generated_at"]


def test_an_unknown_seen_age_stays_null_and_never_becomes_the_build_time(board_client):
    """The dangerous fallback, asserted against directly.

    Defaulting an unknown observation time to `generated_at` would report a
    two-hour-old board as freshly quoted -- an unknown mapped onto the
    permissive branch, which is exactly how a degraded board comes to look
    healthy. Every artifact in the local checkout is in this state.
    """
    client = board_client([_row(seen_age=None, move_age=53862.6)])

    freshness = _fetch(client)["odds_freshness"]

    assert freshness["odds_observed_at"] is None
    assert freshness["odds_observed_at_median"] is None
    assert freshness["rows_with_seen_age"] == 0
    assert freshness["rows_missing_seen_age"] == 1
    # The other clock still resolves -- it is a real fact about the board and is
    # simply not the same fact.
    assert freshness["price_moved_at"] is not None


def test_the_move_clock_and_the_look_clock_resolve_to_different_instants(board_client):
    """A motionless market that we looked at 2 minutes ago is FRESH.

    `book_quotes` is a change log, so reading the move clock as the odds age
    would cry stale on every quiet pregame market -- 424-minute NFL medians were
    once read as a capture outage and were nothing of the kind.
    """
    client = board_client([_row(seen_age=120.0, move_age=36000.0)])

    freshness = _fetch(client)["odds_freshness"]

    built = datetime.fromisoformat(ARTIFACT_BUILT_AT)
    assert datetime.fromisoformat(freshness["odds_observed_at"]) == built - timedelta(seconds=120)
    assert datetime.fromisoformat(freshness["price_moved_at"]) == built - timedelta(seconds=36000)


def test_an_unparseable_build_time_yields_null_rather_than_a_wrong_instant(board_client):
    """A bad `generated_at` must not produce a plausible timestamp."""
    client = board_client([_row(seen_age=120.0)], generated_at="not-a-timestamp")

    freshness = _fetch(client)["odds_freshness"]

    assert freshness["odds_observed_at"] is None
    # The relative age the worker measured is still true and still served.
    assert freshness["seen_age_seconds_min"] == 120.0


def test_the_live_view_reports_its_own_odds_age_not_the_full_slates(board_client):
    """`view=live` filters the games; the freshness must filter with them."""
    client = board_client(
        [
            _row(seen_age=20.0, event_id="evt-live", state="live"),
            _row(seen_age=6600.0, event_id="evt-pre", state="pregame"),
        ]
    )

    live = _fetch(client, view="live")["odds_freshness"]
    pregame = _fetch(client, view="pregame")["odds_freshness"]

    assert live["seen_age_seconds_min"] == 20.0
    assert pregame["seen_age_seconds_min"] == 6600.0
    assert live["odds_observed_at"] > pregame["odds_observed_at"]
