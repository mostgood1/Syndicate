"""NFL player props: the read path, the side attribution, and the card attach.

Ordered deliberately. The FIRST test is a reachability test -- does the resolver
actually reach the real capture instead of the git-tracked stub -- because every
other behaviour in this file is inert if it does not. A fix that is present but
unreachable passes correctness tests and changes nothing in production, which is
the failure mode these tests exist to make impossible.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from syndicate.features.nfl import props as nfl_props
from syndicate.features.nfl.sources import nfl_props_path


HEADER = (
    "player,team,market,line,over_price,under_price,book,event,"
    "game_time,home_team,away_team,is_ladder\n"
)

AWAY = "New England Patriots"
HOME = "Seattle Seahawks"


def _write(path: Path, body: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(HEADER + body, encoding="utf-8")
    return path


def _row(player, market="Anytime TD", line="", over="150", under="", book="draftkings"):
    return (
        f"{player},,{market},{line},{over},{under},{book},{AWAY} @ {HOME},"
        f"2026-09-10T00:15:00Z,{HOME},{AWAY},False\n"
    )


@pytest.fixture(autouse=True)
def _clear_caches():
    nfl_props._nfl_raw_player_props.cache_clear()
    nfl_props.nfl_player_team_index.cache_clear()
    yield
    nfl_props._nfl_raw_player_props.cache_clear()
    nfl_props.nfl_player_team_index.cache_clear()


@pytest.fixture
def two_roots(tmp_path, monkeypatch):
    """A root whose FIRST candidate holds a header-only stub and whose second
    holds the real capture -- production's exact shape on 2026-08-27."""
    base = tmp_path / "nfl_source"
    monkeypatch.setenv("SYNDICATE_NFL_SOURCE_ROOT", str(base))
    monkeypatch.delenv("SYNDICATE_DATA_ROOT", raising=False)
    return base


def test_resolver_prefers_the_real_capture_over_a_header_only_stub(two_roots):
    """THE REACHABILITY TEST. `_resolve_nfl_tracking_path`'s first-that-EXISTS
    rule is not enough here, because the stub exists. Fails without the content
    probe, which is precisely what shipped to production as a silent zero."""
    stub = _write(two_roots / "source_artifacts" / "oddsapi_player_props_2026_wk1.csv")
    real = _write(two_roots / "oddsapi_player_props_2026_wk1.csv", _row("A.J. Brown"))

    resolved = nfl_props_path(2026, 1)

    assert resolved == real, f"resolved to {resolved} -- the stub shadowed the real capture"
    assert stub.read_text(encoding="utf-8") == HEADER
    assert len(nfl_props._nfl_raw_player_props(2026, 1)) == 1


def test_a_genuinely_empty_week_still_resolves_to_a_concrete_path(two_roots):
    """A capture that found no markets is not an error, and must still name a
    real file rather than falling through to the write-root fallback."""
    stub = _write(two_roots / "source_artifacts" / "oddsapi_player_props_2026_wk4.csv")

    assert nfl_props_path(2026, 4) == stub
    assert nfl_props._nfl_raw_player_props(2026, 4) == ()


def test_week_enumeration_unions_every_root(two_roots):
    """A week captured to the mounted disk after the last mirror refresh has no
    git stub, so globbing a single root could never list it."""
    _write(two_roots / "source_artifacts" / "oddsapi_player_props_2026_wk1.csv", _row("A.J. Brown"))
    _write(two_roots / "oddsapi_player_props_2026_wk2.csv", _row("Puka Nacua"))

    assert nfl_props.nfl_props_available_weeks(2026) == [1, 2]


# --------------------------------------------------------------------------
# Side attribution. Every one of these is a REFUSAL test, pinning
# player_stats.player_name_index's rule: "An unresolvable name costs us one bet.
# A wrongly resolved name prices a projection against a different human being,
# which is worse than no bet at any stake."
# --------------------------------------------------------------------------

ROSTER_HEADER = "player_id,player_name,team,position,season,snapshot_date,team_abbr,team_name\n"


@pytest.fixture
def roster(two_roots):
    def _build(entries):
        path = two_roots / "source_artifacts" / "data" / "processed" / "rosters" / "roster_2026_snapshot.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        body = "".join(
            f"00-{index:07d},{name},{team},WR,2026,2026-08-01,{team},{team} Team\n"
            for index, (name, team) in enumerate(entries)
        )
        path.write_text(ROSTER_HEADER + body, encoding="utf-8")
        return path

    return _build


def _recs(away=AWAY, home=HOME):
    return nfl_props.nfl_prop_recommendations_for_matchup(
        2026, 1, away_full_name=away, home_full_name=home
    )


def test_props_split_onto_the_side_the_roster_says(two_roots, roster):
    roster([("A.J. Brown", "NE"), ("Puka Nacua", "SEA")])
    _write(
        two_roots / "oddsapi_player_props_2026_wk1.csv",
        _row("A.J. Brown") + _row("Puka Nacua", over="200"),
    )

    recs = _recs()

    assert [row["player"] for row in recs["away"]] == ["A.J. Brown"]
    assert [row["player"] for row in recs["home"]] == ["Puka Nacua"]


def test_a_player_whose_roster_team_is_in_neither_side_is_refused(two_roots, roster):
    """The guard that makes mis-attribution structurally impossible rather than
    merely unlikely: a stale roster row must not put a real prop on a card the
    player has nothing to do with."""
    roster([("A.J. Brown", "PHI")])
    _write(two_roots / "oddsapi_player_props_2026_wk1.csv", _row("A.J. Brown"))

    assert _recs() == {"away": [], "home": []}


def test_an_unknown_player_is_refused_not_guessed(two_roots, roster):
    roster([("Someone Else", "NE")])
    _write(two_roots / "oddsapi_player_props_2026_wk1.csv", _row("A.J. Brown"))

    assert _recs() == {"away": [], "home": []}


def test_a_name_on_two_teams_is_dropped_rather_than_chosen_between(two_roots, roster):
    """Two real humans sharing a name give no evidence for choosing one."""
    roster([("Mike Williams", "NE"), ("Mike Williams", "SEA")])
    _write(two_roots / "oddsapi_player_props_2026_wk1.csv", _row("Mike Williams"))

    assert _recs() == {"away": [], "home": []}
    assert "mike williams" in nfl_props.nfl_player_team_collisions(2026)


def test_suffix_and_punctuation_differences_still_join(two_roots, roster):
    """Typography must not cost a bet: the odds feed and the roster disagree on
    periods and generational suffixes for the same human."""
    roster([("Michael Pittman Jr.", "NE")])
    _write(two_roots / "oddsapi_player_props_2026_wk1.csv", _row("Michael Pittman"))

    assert [row["player"] for row in _recs()["away"]] == ["Michael Pittman"]


def test_the_card_shows_the_best_price_across_books(two_roots, roster):
    roster([("A.J. Brown", "NE")])
    _write(
        two_roots / "oddsapi_player_props_2026_wk1.csv",
        _row("A.J. Brown", over="150", book="draftkings")
        + _row("A.J. Brown", over="230", book="betonlineag")
        + _row("A.J. Brown", over="120", book="fanduel"),
    )

    rows = _recs()["away"]

    assert len(rows) == 1, "one selection must render one row"
    assert rows[0]["price"] == 230
    assert rows[0]["book"] == "betonlineag"


def test_no_roster_artifact_degrades_to_empty_rather_than_raising(two_roots):
    _write(two_roots / "oddsapi_player_props_2026_wk1.csv", _row("A.J. Brown"))

    assert _recs() == {"away": [], "home": []}


def test_best_price_seam_keeps_one_row_per_selection_per_side(two_roots):
    """The compatibility contract. Consumers of `nfl_props_rows_for_week` were
    written against a one-book file; the multi-book capture must not multiply
    their denominators. Best price is taken PER SIDE, because the best over and
    the best under are routinely at different books."""
    _write(
        two_roots / "oddsapi_player_props_2026_wk1.csv",
        _row("Drake Maye", "Passing Yards", "250.5", "-115", "-105", "draftkings")
        + _row("Drake Maye", "Passing Yards", "250.5", "-130", "100", "fanduel"),
    )

    collapsed = nfl_props._best_price_player_props(2026, 1)

    assert len(collapsed) == 1
    assert float(collapsed[0]["over_price"]) == -115
    assert float(collapsed[0]["under_price"]) == 100


def test_distinct_lines_are_distinct_selections(two_roots):
    """An alternate ladder must not collapse onto one row -- the aggregation-key
    defect, seen from the reader's side."""
    _write(
        two_roots / "oddsapi_player_props_2026_wk1.csv",
        _row("Drake Maye", "Passing Yards", "250.5", "-110")
        + _row("Drake Maye", "Passing Yards", "275.5", "140"),
    )

    assert len(nfl_props._best_price_player_props(2026, 1)) == 2
