"""Phase B producer: payload shape, both axes, the narrator's name, the artifact.

**NOTHING HERE PROVES CAPTURE HAPPENS.** These tests exercise a producer that
nothing schedules. `#208`: allowlisting permits a transfer and does not make
one happen; the same is true of a tested producer and a running one.
"""

from __future__ import annotations

import fnmatch
import json
from pathlib import Path
from typing import Any

import pytest

from syndicate.features.shared.artifact_publisher import HOT_ARTIFACT_PATTERNS
from syndicate.features.shared.basketball_momentum import DEFAULT_HALF_LIFE_POSSESSIONS
from syndicate.features.shared.basketball_momentum import DEFAULT_HALF_LIFE_SECONDS
from syndicate.features.shared.basketball_momentum import possession_index_stream
from syndicate.features.shared.basketball_momentum_artifacts import SCHEMA
from syndicate.features.shared.basketball_momentum_artifacts import append_momentum_artifact
from syndicate.features.shared.basketball_momentum_artifacts import build_momentum_block
from syndicate.features.shared.basketball_momentum_artifacts import build_momentum_payload
from syndicate.features.shared.basketball_momentum_artifacts import momentum_artifact_path

HOME_ID, HOME_TRI = "16", "PHX"
AWAY_ID, AWAY_TRI = "20", "LVA"


def _play(period: int, clock: str, team_id: str, **kw: Any) -> dict[str, Any]:
    play: dict[str, Any] = {
        "period": {"number": period},
        "clock": {"displayValue": clock},
        "team": {"id": team_id},
        "type": {"text": kw.get("type_text", "")},
        "text": kw.get("text", ""),
        "shootingPlay": kw.get("shooting", False),
        "scoreValue": kw.get("score_value", 0),
    }
    if kw.get("attempted") is not None:
        play["pointsAttempted"] = kw["attempted"]
    return play


def _summary(plays: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "header": {"competitions": [{"competitors": [
            {"homeAway": "home", "team": {"id": HOME_ID, "abbreviation": HOME_TRI}},
            {"homeAway": "away", "team": {"id": AWAY_ID, "abbreviation": AWAY_TRI}},
        ]}]},
        "plays": plays,
    }


def _live_game() -> dict[str, Any]:
    return _summary([
        _play(1, "11:00", HOME_ID, shooting=True, attempted=2, score_value=2),
        _play(1, "10:30", HOME_ID, type_text="Offensive Rebound"),
        _play(1, "10:00", HOME_ID, shooting=True, attempted=3, score_value=3),
        _play(1, "9:00", AWAY_ID, type_text="Turnover"),
        _play(1, "8:00", AWAY_ID, shooting=True, attempted=2, score_value=0),
        _play(2, "11:00", AWAY_ID, shooting=True, attempted=3, score_value=3),
    ])


# --------------------------------------------------------------------------
# BOTH AXES (scope section 7, decision 1)
# --------------------------------------------------------------------------

def test_both_decay_axes_are_published() -> None:
    """The decision was 'publish both, decide in Phase C'. If only one axis
    ships, that sweep becomes a rebuild instead of a read."""
    block = build_momentum_block(_live_game(), league_code="nba")
    assert set(block["pressure"]) == {"seconds", "possessions"}
    assert block["pressure"]["seconds"]["half_life"] == DEFAULT_HALF_LIFE_SECONDS
    assert block["pressure"]["possessions"]["half_life"] == DEFAULT_HALF_LIFE_POSSESSIONS
    for axis in ("seconds", "possessions"):
        assert block["pressure"][axis]["series"], f"{axis} series is empty"


def test_the_two_axes_are_genuinely_different_series() -> None:
    """If possessions were a relabelled clock, publishing both would buy
    nothing and the Phase C sweep would compare a series with itself."""
    block = build_momentum_block(_live_game(), league_code="nba")
    seconds = [point["t"] for point in block["pressure"]["seconds"]["series"]]
    possessions = [point["t"] for point in block["pressure"]["possessions"]["series"]]
    assert seconds != possessions


def test_possession_index_is_monotonic_where_the_estimator_says_it_should_be() -> None:
    """`FGA + TOV + 0.44*FTA - OREB` -- an offensive rebound is the one term
    that DECREASES it, because it means the possession never ended."""
    plays = [
        _play(1, "11:00", HOME_ID, shooting=True, attempted=2),      # +1
        _play(1, "10:50", HOME_ID, type_text="Offensive Rebound"),   # -1
        _play(1, "10:40", HOME_ID, shooting=True, attempted=2),      # +1
        _play(1, "10:00", AWAY_ID, type_text="Turnover"),            # +1
        _play(1, "9:00", AWAY_ID, shooting=True, attempted=1),       # +0.44
    ]
    assert possession_index_stream(plays) == [1.0, 0.0, 1.0, 2.0, 2.44]


def test_possession_index_stays_aligned_with_the_play_list() -> None:
    """One entry per play INCLUDING plays that move nothing. A filtered list
    would silently misalign every annotation after the first inert play."""
    plays = [
        _play(1, "11:00", HOME_ID, type_text="Substitution"),
        _play(1, "10:00", HOME_ID, shooting=True, attempted=2),
        _play(1, "9:00", HOME_ID, type_text="Personal Foul"),
    ]
    assert len(possession_index_stream(plays)) == len(plays)
    assert possession_index_stream(plays) == [0.0, 1.0, 1.0]


# --------------------------------------------------------------------------
# THE NARRATOR
# --------------------------------------------------------------------------

def test_the_narrator_is_named_so_it_cannot_be_mistaken_for_a_predictor() -> None:
    """`learnings.md` 2026-08-21 FORBIDS publishing a field under a name that
    describes a different quantity. A points series called 'momentum' is
    exactly that, so the key must say narrator and there must be no key
    anywhere in the block that calls it momentum."""
    block = build_momentum_block(_live_game(), league_code="nba")
    assert "scoring_narrator" in block
    flat = json.dumps(block)
    assert "scoring_momentum" not in flat
    assert "momentum" not in set(block["scoring_narrator"])


def test_the_narrator_carries_points_and_the_pressure_series_does_not() -> None:
    block = build_momentum_block(_live_game(), league_code="nba")
    assert block["events"] == 6           # 4 attempts + 1 OREB + 1 turnover credited
    assert block["scoring_narrator"]["events"] == 3   # 2 + 3 home, 3 away


# --------------------------------------------------------------------------
# HONEST EMPTY STATES
# --------------------------------------------------------------------------

def test_a_thin_feed_returns_a_stated_reason_not_a_zero() -> None:
    """A flat series and an absent one mean different things to anyone reading
    the card. A bare 0.0 is the neutral-default trap: it makes an unfed series
    indistinguishable from a balanced game at every level except the data."""
    block = build_momentum_block(_summary([]), league_code="nba")
    assert block["supported"] is True
    assert block["reason"]
    assert block["pressure"] is None


def test_an_unparseable_feed_is_unsupported_and_says_why_rather_than_raising() -> None:
    block = build_momentum_block({"header": None, "plays": "not a list"}, league_code="nba")
    assert block["supported"] is True
    assert block["pressure"] is None
    assert block["reason"]


def test_an_unknown_league_is_reported_not_raised() -> None:
    """The producer must never take a tick down for one bad game."""
    block = build_momentum_block(_live_game(), league_code="cricket")
    assert block["supported"] is False
    assert "ValueError" in block["reason"]


def test_with_series_distinguishes_no_games_from_unreadable_games() -> None:
    """`count` alone cannot: both are a number next to an empty chart."""
    payload = build_momentum_payload(
        {"1": _live_game(), "2": _summary([])}, league_code="nba", date_str="2026-08-22"
    )
    assert payload["count"] == 2
    assert payload["with_series"] == 1


# --------------------------------------------------------------------------
# CAUSALITY AT THE PAYLOAD LEVEL
# --------------------------------------------------------------------------

def test_as_of_truncates_the_series_rather_than_reading_the_whole_feed() -> None:
    """Reading to the end of the feed would let a card show pressure from after
    the moment it claims to describe."""
    early = build_momentum_block(_live_game(), league_code="nba", as_of_seconds=200.0)
    late = build_momentum_block(_live_game(), league_code="nba")
    assert early["as_of_seconds"] == 200.0
    assert all(point["t"] <= 200.0 for point in early["pressure"]["seconds"]["series"])
    assert len(early["pressure"]["seconds"]["series"]) < len(late["pressure"]["seconds"]["series"])


def test_as_of_also_truncates_the_possession_axis() -> None:
    """The possession `as_of` must be derived from events at or before the
    seconds `as_of` -- taking the max over ALL rows would let the possession
    axis see past the instant the seconds axis stops at."""
    early = build_momentum_block(_live_game(), league_code="nba", as_of_seconds=200.0)
    late = build_momentum_block(_live_game(), league_code="nba")
    assert early["as_of_possessions"] < late["as_of_possessions"]


# --------------------------------------------------------------------------
# THE ARTIFACT
# --------------------------------------------------------------------------

def test_artifact_path_is_under_the_allowlisted_live_lens_directory(tmp_path: Path) -> None:
    path = momentum_artifact_path(tmp_path, league_code="wnba", date_str="2026-08-22")
    relative = path.relative_to(tmp_path).as_posix()
    assert relative == "wnba_source/source_artifacts/data/live_lens/live_momentum_2026-08-22.jsonl"
    assert any(fnmatch.fnmatch(relative, pattern) for pattern in HOT_ARTIFACT_PATTERNS), (
        "the artifact path is not allowlisted -- it could never reach web"
    )


@pytest.mark.parametrize("relative", [
    "wnba_source/source_artifacts/data/live_lens/live_momentum_2026-08-22.jsonl",
    "nba_source/data/live_lens/live_momentum_2026-08-22.jsonl",
])
def test_both_root_depths_are_allowlisted(relative: str) -> None:
    """The sibling live_lens families are declared at both depths. A sport whose
    root resolves to the shallow layout would otherwise transfer its
    projections and silently drop its momentum."""
    assert any(fnmatch.fnmatch(relative, pattern) for pattern in HOT_ARTIFACT_PATTERNS)


def test_the_artifact_appends_and_never_truncates(tmp_path: Path) -> None:
    """Phase C needs the sequence of what was true at each tick, not the last
    frame. Overwriting would leave a file that looks like a record and is a
    snapshot."""
    path = momentum_artifact_path(tmp_path, league_code="wnba", date_str="2026-08-22")
    for _ in range(3):
        append_momentum_artifact(
            build_momentum_payload({"1": _live_game()}, league_code="wnba", date_str="2026-08-22"),
            path=path,
        )
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == 3
    assert all(json.loads(line)["schema"] == SCHEMA for line in lines)


def test_the_payload_is_json_serialisable_and_finite(tmp_path: Path) -> None:
    """A non-finite value reaching a snapshot fails `validate_live_lens_snapshot`
    for the WHOLE sport, not just this game."""
    payload = build_momentum_payload({"1": _live_game()}, league_code="nba", date_str="2026-08-22")
    text = json.dumps(payload, allow_nan=False)
    assert "NaN" not in text and "Infinity" not in text
