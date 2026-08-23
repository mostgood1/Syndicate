"""`shared_momentum` reaching a WNBA card.

Momentum has been captured to disk since 2026-08-22 23:19Z and rendered
nowhere: `soccer/cards.py` was the ONLY setter of `shared_momentum` in the
repo, and `live_lens_loop.py` assigned the payload to a local it never used.
These tests pin the join that closes that gap.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

import syndicate.features.wnba.cards as wnba_cards
from syndicate.features.shared.basketball_momentum_artifacts import momentum_artifact_path

DATE = "2026-08-22"
EVENT = "401857164"


def _block(current: float = -1.3478, *, supported: bool = True,
           home_tri: str = "IND", away_tri: str = "NYL") -> dict[str, Any]:
    vals = [0.5, -1.2, 2.1, 0.3, -3.0, 1.1, 4.2, -0.8, 2.2, -1.9,
            0.4, 3.3, -2.7, 1.5, -4.55, 0.9, 2.8, -1.1, 0.2, -3.4, current]
    series = [{"t": float(t), "v": v} for t, v in zip(range(0, 1260, 60), vals)]
    return {
        "schema": "basketball_momentum_v1", "supported": supported, "reason": None,
        "home_tri": home_tri, "away_tri": away_tri,
        "events": 198, "as_of_seconds": 1200.0, "as_of_possessions": 148.84,
        "pressure": {
            "seconds": {"half_life": 120.0, "as_of": 1200.0,
                        "current": current, "series": series},
            "possessions": {"half_life": 8.0, "as_of": 148.84,
                            "current": -1.4657, "series": series},
        },
        "scoring_narrator": {"events": 97, "seconds": {}},
    }


@pytest.fixture
def artifact_root(tmp_path: Path):
    def _write(rows: list[dict[str, Any]]) -> Path:
        path = momentum_artifact_path(tmp_path, league_code="wnba", date_str=DATE)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row) + "\n")
        return tmp_path
    return _write


def _attach(games, root: Path, date: str = DATE) -> int:
    with mock.patch(
        "syndicate.features.shared.refresh_state_store.data_root", return_value=root
    ):
        return wnba_cards._attach_wnba_momentum(games, date)


def _game(event_id: str, away: str = "NYL", home: str = "IND") -> dict[str, Any]:
    return {"event_id": event_id, "away": {"abbr": away}, "home": {"abbr": home}}


# ---------------------------------------------------------------------------
# The join
# ---------------------------------------------------------------------------

def test_a_live_game_gets_a_chart(artifact_root) -> None:
    root = artifact_root([{"games": {EVENT: _block()}}])
    games = [_game(EVENT)]
    assert _attach(games, root) == 1
    chart = games[0]["shared_momentum"]
    assert chart["label"] == "NYL pressure"
    assert chart["now_x"] == 50.0          # 1200s of a 2400s WNBA game
    assert len(chart["points"]) == 21


def test_the_leading_zero_event_id_still_joins(artifact_root) -> None:
    """**`game_cards_*.csv` carries `0401856943` for ESPN's `401856943`.**

    Without alias handling every game whose id arrived from the artifact side
    would silently miss its chart -- and silently is the operative word: the
    card renders fine, just without the panel.
    """
    root = artifact_root([{"games": {EVENT: _block()}}])
    games = [_game(f"0{EVENT}")]
    assert _attach(games, root) == 1
    assert games[0]["shared_momentum"] is not None


def test_an_artifact_form_id_still_joins_by_matchup(artifact_root) -> None:
    """**THE PRODUCTION FAILURE, pinned.** Measured 01:18:49Z on web:

        [wnba_cards] MOMENTUM_ATTACHED date=2026-08-22 games=3 blocks=2 attached=0

    Blocks existed and none joined. `_wnba_row_game_id` gives an
    artifact-only card `"AWY@HOM"` or an opaque hash, and only
    `_supplement_games_with_live_state` repairs it -- for live rows. So a card
    can hold a captured block's game and have no key to find it with.

    The block now carries its own tricodes, so the `(away, home)` pair the rest
    of this module already joins on works here too.
    """
    root = artifact_root([{"games": {EVENT: _block()}}])
    games = [_game("NYL@IND")]                  # no ESPN id anywhere on the card
    assert _attach(games, root) == 1
    assert games[0]["shared_momentum"]["label"] == "NYL pressure"


def test_the_event_id_still_wins_over_the_matchup(artifact_root) -> None:
    """The id is exact; the matchup assumes one meeting per date. Order matters
    and the fallback must never shadow a real key."""
    right = _block(-4.55, home_tri="IND", away_tri="NYL")
    decoy = _block(4.55, home_tri="IND", away_tri="NYL")
    root = artifact_root([{"games": {EVENT: right, "999999": decoy}}])
    games = [_game(EVENT)]
    _attach(games, root)
    assert games[0]["shared_momentum"]["side_is_away"] is True   # from `right`


def test_a_block_without_tricodes_does_not_break_the_matchup_index(artifact_root) -> None:
    """Rows captured before the tricodes were added are still in tonight's
    jsonl, so the index has to tolerate their absence rather than assume it."""
    legacy = _block()
    legacy.pop("home_tri")
    legacy.pop("away_tri")
    root = artifact_root([{"games": {EVENT: legacy}}])
    assert _attach([_game(EVENT)], root) == 1          # id path unaffected
    assert _attach([_game("NYL@IND")], root) == 0      # no matchup key to use


def test_a_game_with_no_captured_block_is_left_alone(artifact_root) -> None:
    """Pregame/artifact-only cards carry `"AWY@HOM"` in `event_id` and have no
    momentum, which is correct rather than a gap: momentum only exists for
    games ESPN reports as in play."""
    root = artifact_root([{"games": {EVENT: _block()}}])
    games = [_game("DAL@LVA", away="DAL", home="LVA")]
    assert _attach(games, root) == 0
    assert "shared_momentum" not in games[0]


def test_the_newest_row_wins(artifact_root) -> None:
    """The producer appends one payload per tick, so the card wants the last."""
    early = _block(-4.55)
    late = _block(4.55)
    root = artifact_root([{"games": {EVENT: early}}, {"games": {EVENT: late}}])
    games = [_game(EVENT)]
    _attach(games, root)
    assert games[0]["shared_momentum"]["side_is_home"] is True   # from `late`


def test_a_torn_final_line_does_not_lose_the_rows_before_it(tmp_path) -> None:
    """Expected, not exceptional: this is read while the producer appends."""
    path = momentum_artifact_path(tmp_path, league_code="wnba", date_str=DATE)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        handle.write(json.dumps({"games": {EVENT: _block()}}) + "\n")
        handle.write('{"games": {"401857164": {"eve')          # mid-write
    games = [_game(EVENT)]
    assert _attach(games, tmp_path) == 1


# ---------------------------------------------------------------------------
# Never fatal to a board build
# ---------------------------------------------------------------------------

def test_a_missing_artifact_is_not_an_error(tmp_path) -> None:
    games = [_game(EVENT)]
    assert _attach(games, tmp_path) == 0
    assert "shared_momentum" not in games[0]


def test_an_unsupported_block_draws_nothing(artifact_root) -> None:
    """A flat line and "no data" look identical on a canvas."""
    root = artifact_root([{"games": {EVENT: {"supported": False,
                                             "reason": "no pressure events yet",
                                             "pressure": None}}}])
    games = [_game(EVENT)]
    assert _attach(games, root) == 0
    assert "shared_momentum" not in games[0]


def test_a_read_failure_does_not_take_down_the_board(artifact_root) -> None:
    """**A card without a chart beats a board that 500s.**"""
    root = artifact_root([{"games": {EVENT: _block()}}])
    games = [_game(EVENT)]
    with mock.patch(
        "syndicate.features.shared.basketball_momentum_card.latest_momentum_blocks",
        side_effect=RuntimeError("keyvalue exploded"),
    ):
        assert _attach(games, root) == 0
    assert "shared_momentum" not in games[0]


@pytest.mark.parametrize("games", [None, [], "not-a-list", [None, "x", 3]])
def test_junk_game_collections_are_survivable(games, artifact_root) -> None:
    root = artifact_root([{"games": {EVENT: _block()}}])
    assert _attach(games, root) == 0


# ---------------------------------------------------------------------------
# Both live paths are wired -- the shortcut is the one that would be missed
# ---------------------------------------------------------------------------

def test_both_live_entry_points_call_the_attach() -> None:
    """**The ESPN-only shortcut returns EARLY and skips the main attach loop.**

    It is taken on a live slate with no odds-rich artifacts yet -- exactly when
    a momentum chart is most wanted. Wiring only the main loop would leave the
    chart missing precisely there, looking like the feature just did not work.
    """
    source = Path(wnba_cards.__file__).read_text(encoding="utf-8")
    assert source.count("_attach_wnba_momentum(") == 3, (
        "one definition plus BOTH call sites: the main attach loop and the "
        "ESPN-only shortcut branch"
    )
