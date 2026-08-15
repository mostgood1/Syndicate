"""Drop 2: a rebuild that cannot produce live-state signal must not destroy it.

Lane `live-game-line-projection`. Evidence:
`.syndicate/spec_live_game_line_projection.md`.

Web's fallback rebuild has the live Monte Carlo hard-refused in-request, and it
REPLACED rather than merged -- so on any request where the worker's snapshot read
as stale (max age 60s against a 60s worker tick), the live win probability was
silently dropped. These pin the merge, and just as importantly the four cases
where carrying forward would be WRONG: a settled game, an unbounded age, an
unknown age, and a second hop that would otherwise reset the clock.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from syndicate.features.mlb import live_lens as m


def _iso(seconds_ago: float) -> str:
    return (datetime.now().astimezone() - timedelta(seconds=seconds_ago)).isoformat(timespec="seconds")


def _mc_lens() -> list[dict]:
    return [
        {"key": "live", "label": "Top 7", "source": "live_mc", "modelHomeWinProb": 0.6842,
         "projection": {"total": 7.5, "homeMargin": 0.7}},
        {"key": "full", "label": "Full Game", "source": "live_mc", "modelHomeWinProb": 0.6842,
         "projection": {"total": 7.5, "homeMargin": 0.7}},
    ]


def _card_lens() -> list[dict]:
    return [{"key": "first5", "label": "F5", "projection": {"total": 5.02, "homeMargin": 0.31}}]


def _previous_snapshot(*, age_seconds: float = 30.0, lens=None, game_pk: int = 824159) -> dict:
    return {
        "generatedAt": _iso(age_seconds),
        "games": [{
            "gamePk": game_pk,
            "status": {"abstract": "Live", "detailed": "In Progress"},
            "gameLens": _mc_lens() if lens is None else lens,
        }],
    }


def _fresh_report(*, abstract: str = "Live", detailed: str = "In Progress", game_pk: int = 824159) -> dict:
    """What web's lens-less rebuild produces."""
    return {
        "generatedAt": _iso(0),
        "counts": {"games": 1},
        "games": [{
            "gamePk": game_pk,
            "status": {"abstract": abstract, "detailed": detailed},
            "gameLens": _card_lens(),
        }],
    }


def _lens_of(report: dict) -> list[dict]:
    return report["games"][0]["gameLens"]


class TestCarriesForward:
    def test_live_game_keeps_the_previous_monte_carlo_lens(self):
        out = m._carry_forward_live_state_lens(_fresh_report(), _previous_snapshot())
        assert m._lens_rows_have_live_state_signal(_lens_of(out)) is True
        assert out["counts"]["liveStateLensCarriedForward"] == 1

    def test_carried_rows_are_stamped_so_a_consumer_can_refuse_them(self):
        prev = _previous_snapshot(age_seconds=42.0)
        out = m._carry_forward_live_state_lens(_fresh_report(), prev)
        for row in _lens_of(out):
            assert row["liveStateCarriedForward"] is True
            assert row["liveStateAsOf"] == prev["generatedAt"]

    def test_the_source_report_is_not_mutated(self):
        report = _fresh_report()
        m._carry_forward_live_state_lens(report, _previous_snapshot())
        assert m._lens_rows_have_live_state_signal(_lens_of(report)) is False


class TestRefusesToCarryForward:
    """Each of these would be a wrong number on the board, not a missing one."""

    def test_a_game_that_has_gone_final_is_left_alone(self):
        """Resurrecting a live win probability onto a settled game is #414's harm."""
        out = m._carry_forward_live_state_lens(
            _fresh_report(abstract="Final", detailed="Game Over"), _previous_snapshot()
        )
        assert _lens_of(out) == _card_lens()
        assert "liveStateLensCarriedForward" not in (out.get("counts") or {})

    def test_a_pregame_game_is_left_alone(self):
        out = m._carry_forward_live_state_lens(
            _fresh_report(abstract="Preview", detailed="Scheduled"), _previous_snapshot()
        )
        assert _lens_of(out) == _card_lens()

    def test_a_lens_older_than_the_bound_is_refused(self):
        out = m._carry_forward_live_state_lens(
            _fresh_report(), _previous_snapshot(age_seconds=10_000.0)
        )
        assert _lens_of(out) == _card_lens()

    def test_an_unreadable_age_is_refused_not_treated_as_fresh(self):
        """Unknown must not take the permissive branch."""
        prev = _previous_snapshot()
        prev["generatedAt"] = "not-a-timestamp"
        assert m._carry_forward_live_state_lens(_fresh_report(), prev)["games"][0]["gameLens"] == _card_lens()
        del prev["generatedAt"]
        assert m._carry_forward_live_state_lens(_fresh_report(), prev)["games"][0]["gameLens"] == _card_lens()

    def test_a_different_game_never_donates_its_lens(self):
        out = m._carry_forward_live_state_lens(
            _fresh_report(game_pk=111), _previous_snapshot(game_pk=222)
        )
        assert _lens_of(out) == _card_lens()

    def test_a_previous_snapshot_without_live_state_donates_nothing(self):
        out = m._carry_forward_live_state_lens(
            _fresh_report(), _previous_snapshot(lens=_card_lens())
        )
        assert _lens_of(out) == _card_lens()

    def test_a_fresh_lens_of_its_own_is_never_overwritten(self):
        report = _fresh_report()
        own = [{"key": "live", "source": "live_mc", "modelHomeWinProb": 0.9}]
        report["games"][0]["gameLens"] = own
        out = m._carry_forward_live_state_lens(report, _previous_snapshot())
        assert _lens_of(out) == own
        assert _lens_of(out)[0]["modelHomeWinProb"] == 0.9

    @pytest.mark.parametrize("previous", [None, {}, "snapshot", []])
    def test_malformed_previous_is_a_no_op(self, previous):
        report = _fresh_report()
        assert m._carry_forward_live_state_lens(report, previous) == report


class TestAgeDoesNotCompound:
    def test_a_second_hop_keeps_the_original_instant(self):
        """The bug this prevents: each hop re-stamping makes a stale lens read
        as permanently fresh, so the age bound could never fire."""
        original = _iso(200.0)
        already_carried = [dict(row, liveStateAsOf=original, liveStateCarriedForward=True) for row in _mc_lens()]
        prev = _previous_snapshot(age_seconds=10.0, lens=already_carried)
        out = m._carry_forward_live_state_lens(_fresh_report(), prev)
        assert all(row["liveStateAsOf"] == original for row in _lens_of(out))
        assert all(row["liveStateAsOf"] != prev["generatedAt"] for row in _lens_of(out))


class TestKillSwitch:
    def test_zero_disables_carry_forward(self, monkeypatch):
        monkeypatch.setenv("MLB_LIVE_STATE_CARRY_FORWARD_MAX_AGE_SECONDS", "0")
        out = m._carry_forward_live_state_lens(_fresh_report(), _previous_snapshot())
        assert _lens_of(out) == _card_lens()

    def test_a_negative_value_is_a_typo_and_does_not_read_as_disabled(self, monkeypatch):
        monkeypatch.setenv("MLB_LIVE_STATE_CARRY_FORWARD_MAX_AGE_SECONDS", "-1")
        assert m._live_state_carry_forward_max_age_seconds() == m._LIVE_STATE_CARRY_FORWARD_MAX_AGE_DEFAULT_SECONDS

    @pytest.mark.parametrize("raw", ["", "abc", "12.5"])
    def test_an_unparseable_value_falls_back_to_the_default(self, monkeypatch, raw):
        monkeypatch.setenv("MLB_LIVE_STATE_CARRY_FORWARD_MAX_AGE_SECONDS", raw)
        assert m._live_state_carry_forward_max_age_seconds() == m._LIVE_STATE_CARRY_FORWARD_MAX_AGE_DEFAULT_SECONDS


class TestSnapshotAccessor:
    def test_reads_games_from_page_context_when_top_level_is_absent(self):
        snapshot = {"generatedAt": _iso(5), "page_context": {"games": [
            {"gamePk": 7, "status": {"abstract": "Live"}, "gameLens": _mc_lens()},
        ]}}
        assert list(m._live_state_lens_by_game_pk(snapshot)) == [7]

    def test_skips_games_with_no_usable_game_pk(self):
        snapshot = {"generatedAt": _iso(5), "games": [
            {"gamePk": 0, "gameLens": _mc_lens()},
            {"gameLens": _mc_lens()},
            {"gamePk": "not-an-int", "gameLens": _mc_lens()},
        ]}
        assert m._live_state_lens_by_game_pk(snapshot) == {}
