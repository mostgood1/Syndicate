"""A cached `feed/live` payload is reusable only once the game is FINAL.

REGRESSION FOR A MEASURED LOSS. On 2026-09-03 MLB played 9 games and StatsAPI
records all 9 as Final; `live_gameline_score` scored 7. ATH @ SEA went final
05:05Z and STL @ LAD 05:09Z -- both AFTER the 05:00Z midnight-Central roll --
and the board artifact built at 05:33:14Z still carried them as unfinished.
A past date's artifact is never rebuilt, so that miss is permanent.

Two defects composed:

1. INVERTED PREDICATE. `cards.py` re-fetched when the cached payload was NOT
   live, so a cached PREGAME or FINAL document was refreshed and a cached
   LIVE one never was -- and live -> final is the only transition that
   mattered. `home.py` had no freshness rule at all.
2. WINDOW. Both re-fetches were gated `selected_date == today_iso`, which
   refuses precisely the games that end after the date rolls.
"""

from __future__ import annotations

import pytest

from syndicate.features.mlb.game_state import (
    mlb_feed_live_is_refreshable,
    mlb_feed_payload_is_final,
)


def _payload(abstract: str, detailed: str) -> dict:
    return {"gameData": {"status": {"abstractGameState": abstract, "detailedState": detailed}}}


LIVE = _payload("Live", "In Progress")
FINAL = _payload("Final", "Final")
PREGAME = _payload("Preview", "Scheduled")
WARMUP = _payload("Live", "Warmup")  # #98/#100: abstract says Live, it is not


class TestPayloadIsFinal:
    def test_final_is_final(self):
        assert mlb_feed_payload_is_final(FINAL) is True

    @pytest.mark.parametrize("payload", [LIVE, PREGAME, WARMUP])
    def test_everything_else_is_not(self, payload):
        assert mlb_feed_payload_is_final(payload) is False

    @pytest.mark.parametrize("payload", [None, {}, {"gameData": {}}, {"gameData": None}, "nope"])
    def test_a_shape_it_cannot_read_is_not_final(self, payload):
        """UNKNOWN MUST NOT DEFAULT TO THE PERMISSIVE BRANCH. Here permissive
        means 'terminal, never refresh again', which is how a payload freezes."""
        assert mlb_feed_payload_is_final(payload) is False


class TestRefreshWindow:
    def test_today_always(self):
        assert mlb_feed_live_is_refreshable("2026-09-04", "2026-09-04", in_request_context=True) is True
        assert mlb_feed_live_is_refreshable("2026-09-04", "2026-09-04", in_request_context=False) is True

    def test_yesterday_off_the_request_path(self):
        """THE 2026-09-03 CASE: a game that ended after the Central roll can
        only be recorded by a build for yesterday's slate."""
        assert mlb_feed_live_is_refreshable("2026-09-03", "2026-09-04", in_request_context=False) is True

    def test_yesterday_is_refused_inside_a_web_request(self):
        """Every miss on the request path is an uncached HTTPS call, and that
        is the measured cause of gunicorn being SIGTERM'd."""
        assert mlb_feed_live_is_refreshable("2026-09-03", "2026-09-04", in_request_context=True) is False

    def test_nothing_older_than_yesterday(self):
        assert mlb_feed_live_is_refreshable("2026-09-02", "2026-09-04", in_request_context=False) is False

    def test_crosses_a_month_boundary(self):
        """String comparison would get this wrong; date arithmetic does not."""
        assert mlb_feed_live_is_refreshable("2026-08-31", "2026-09-01", in_request_context=False) is True

    @pytest.mark.parametrize("bad", ["", None, "not-a-date", "2026-13-45"])
    def test_an_unreadable_date_refuses(self, bad):
        assert mlb_feed_live_is_refreshable(bad, "2026-09-04", in_request_context=False) is False


class TestHomeReader:
    """`_mlb_feed_live_payload` is the reader `attach_live_game_state_from_lens`
    was built to paper over."""

    @pytest.fixture
    def reader(self, monkeypatch):
        from syndicate.blueprints import home

        calls: list[int] = []

        def _install(cached, *, today="2026-09-04", fetched=FINAL):
            monkeypatch.setattr(home, "raw_feed_live_path", lambda *_a, **_k: "ignored")
            monkeypatch.setattr(home, "load_json_or_gz_file", lambda *_a, **_k: cached)
            monkeypatch.setattr(home, "central_today_iso", lambda: today)

            def _fetch(game_pk):
                calls.append(int(game_pk))
                return fetched

            monkeypatch.setattr(home, "_fetch_mlb_feed_live", _fetch)
            return home

        return _install, calls

    def test_a_cached_live_payload_is_refreshed(self, reader):
        """THE BUG. Before the fix this returned the frozen LIVE document."""
        install, calls = reader
        home = install(LIVE)
        out = home._mlb_feed_live_payload("2026-09-04", 776)
        assert out is FINAL
        assert calls == [776]

    def test_a_cached_final_payload_costs_no_call(self, reader):
        """Final is terminal -- and this is a real saving, not just caution:
        the old cards.py rule spent a call per already-final game per build."""
        install, calls = reader
        home = install(FINAL)
        out = home._mlb_feed_live_payload("2026-09-04", 776)
        assert out is FINAL
        assert calls == []

    def test_yesterday_is_refreshed_off_the_request_path(self, reader):
        install, calls = reader
        home = install(LIVE, today="2026-09-04")
        out = home._mlb_feed_live_payload("2026-09-03", 776)
        assert out is FINAL
        assert calls == [776]

    def test_an_old_date_is_never_fetched(self, reader):
        install, calls = reader
        home = install(LIVE, today="2026-09-04")
        out = home._mlb_feed_live_payload("2026-08-01", 776)
        assert out is LIVE
        assert calls == []

    def test_a_failed_refresh_falls_back_to_the_cached_document(self, reader):
        """Stale beats nothing. Returning None here would blank a chip that
        currently renders, converting a staleness bug into a coverage bug."""
        install, calls = reader
        home = install(LIVE, fetched=None)
        out = home._mlb_feed_live_payload("2026-09-04", 776)
        assert out is LIVE
        assert calls == [776]

    def test_a_missing_file_still_fetches(self, reader):
        install, calls = reader
        home = install(None)
        out = home._mlb_feed_live_payload("2026-09-04", 776)
        assert out is FINAL
        assert calls == [776]
