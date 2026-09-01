"""Kalshi's club CODES resolve through Kalshi's own club NAMES.

Measured 2026-09-01 against the live Kalshi catalogue (176 clubs, 9
`KX<LEAGUE>GAME` series, read from `trade-api/v2/markets`):

    resolvable by CODE alone .... 111  63%   <- what the join tried
    resolvable by NAME alone .... 115  65%
    resolvable by EITHER ........ 144  82%   <- what it now tries

Nothing here is a guessed alias. Kalshi publishes the pairing: each game
series lists one market per club whose ticker SUFFIX is the code and whose
TITLE is "<Club> wins".
"""

from __future__ import annotations

import pytest

from syndicate.features.shared.kalshi_board_join import (
    _series_family,
    build_club_code_names,
)
from syndicate.features.shared.kalshi_catalogue import match_event_blob


def _m(ticker, series, title):
    return {"ticker": ticker, "series": series, "title": title}


# Real markets, verbatim shapes from the 2026-09-01 read.
_LALIGA = [
    _m("KXLALIGAGAME-26SEP15ELCRMA-RMA", "KXLALIGAGAME", "Real Madrid wins"),
    _m("KXLALIGAGAME-26SEP15ELCRMA-ELC", "KXLALIGAGAME", "Elche wins"),
    _m("KXLALIGAGAME-26SEP15ELCRMA-TIE", "KXLALIGAGAME", "Tie is the result"),
]
_SERIEA = [
    _m("KXSERIEAGAME-26SEP14INTUDI-INT", "KXSERIEAGAME", "Inter wins"),
    _m("KXSERIEAGAME-26SEP14INTUDI-UDI", "KXSERIEAGAME", "Udinese wins"),
]


class TestTheDerivation:
    def test_the_code_to_name_map_is_read_from_kalshis_own_titles(self):
        out = build_club_code_names(_LALIGA)
        assert out["KXLALIGA"]["RMA"] == "Real Madrid"
        assert out["KXLALIGA"]["ELC"] == "Elche"

    def test_the_draw_leg_names_no_club_and_is_skipped(self):
        assert "TIE" not in build_club_code_names(_LALIGA)["KXLALIGA"]

    def test_a_non_moneyline_title_contributes_nothing(self):
        totals = [
            _m("KXLALIGATOTAL-26SEP15ELCRMA-5", "KXLALIGATOTAL",
               "Will over 5.5 goals be scored?")
        ]
        assert build_club_code_names(totals) == {}

    def test_a_code_claimed_by_two_clubs_in_ONE_league_is_dropped_not_guessed(self):
        """Ambiguity inside a competition is refused, like everywhere else."""
        clash = _LALIGA + [
            _m("KXLALIGAGAME-26SEP20XRMA-RMA", "KXLALIGAGAME", "Not Real Madrid wins")
        ]
        assert "RMA" not in build_club_code_names(clash).get("KXLALIGA", {})

    def test_spread_and_total_series_share_the_GAME_series_family(self):
        """A totals market carries no club name, so it must look its codes up
        under the same competition the game series populated."""
        assert _series_family("KXLALIGATOTAL") == "KXLALIGA"
        assert _series_family("KXLALIGASPREAD") == "KXLALIGA"
        assert _series_family("KXLALIGAGAME") == "KXLALIGA"

    def test_a_half_series_is_not_cut_at_the_wrong_token(self):
        assert _series_family("KXLALIGA1HSPREAD") == "KXLALIGA"
        assert _series_family("KXLALIGA1H") == "KXLALIGA"

    def test_bundesliga_2_stays_its_own_competition(self):
        """Folding it into KXBUNDESLIGA would recreate the very collision the
        scoping prevents -- different league, different club set."""
        assert _series_family("KXBUNDESLIGA2GAME") == "KXBUNDESLIGA2"
        assert _series_family("KXBUNDESLIGAGAME") == "KXBUNDESLIGA"


class TestTheCollisionsThatForcedPerLeagueScoping:
    """MEASURED 2026-09-01: four codes name different clubs in different
    competitions. A soccer-wide map would bet on the wrong club."""

    def test_TOR_is_torino_in_serie_a_and_toronto_in_mls(self):
        markets = [
            _m("KXSERIEAGAME-26SEP14TORJUV-TOR", "KXSERIEAGAME", "Torino wins"),
            _m("KXMLSGAME-26SEP14TORCIN-TOR", "KXMLSGAME", "Toronto wins"),
        ]
        out = build_club_code_names(markets)
        assert out["KXSERIEA"]["TOR"] == "Torino"
        assert out["KXMLS"]["TOR"] == "Toronto"

    def test_the_two_meanings_never_appear_in_one_scope(self):
        markets = [
            _m("KXLIGUE1GAME-26SEP14PARLIL-PAR", "KXLIGUE1GAME", "Paris FC wins"),
            _m("KXSERIEAGAME-26SEP14PARINT-PAR", "KXSERIEAGAME", "Parma Calcio wins"),
        ]
        out = build_club_code_names(markets)
        assert out["KXLIGUE1"]["PAR"] == "Paris FC"
        assert out["KXSERIEA"]["PAR"] == "Parma Calcio"
        assert set(out) == {"KXLIGUE1", "KXSERIEA"}


def _soccer_aliases_present() -> bool:
    """Does THIS tree carry the per-league soccer club map?

    It derives from `data/soccer_source/**/rosters_*.csv`, and
    `scripts/session_worktree.py` excludes `data/` BY DEFAULT (CLAUDE.md tells
    every session to work that way), so in a protocol-standard worktree
    `canonical_team("soccer", ...)` answers None for every club. Same predicate
    and same reasoning as `test_polymarket_board_join.needs_soccer_rosters`.
    """
    from syndicate.features.shared.team_aliases import canonical_team

    return bool(canonical_team("soccer", "Real Madrid"))


needs_soccer_aliases = pytest.mark.skipif(
    not _soccer_aliases_present(),
    reason=(
        "per-league soccer club aliases absent from this tree -- `data/` is "
        "excluded from session worktrees by default, so the club map is EMPTY "
        "and every soccer name resolves to None. SKIPPED rather than RED: a "
        "red that also means 'you followed the worktree instructions' is a red "
        "people learn to ignore. The MECHANISM is covered without the mirror "
        "in `TestResolutionMechanismWithoutTheMirror`."
    ),
)


class TestResolutionMechanismWithoutTheMirror:
    """The code -> name substitution itself, with an INJECTED club map.

    Covers the logic in every tree, including worktrees with no `data/`. The
    real-alias behaviour is asserted separately and skipped when absent.
    """

    @staticmethod
    def _fake_canonical(sport, value):
        table = {"elche": "elche", "real madrid": "real madrid",
                 "minnesota twins": "minnesota twins", "athletics": "athletics",
                 "min": "minnesota twins", "ath": "athletics"}
        return table.get(str(value or "").strip().lower())

    def _patched(self, monkeypatch):
        from syndicate.features.shared import team_aliases

        monkeypatch.setattr(team_aliases, "canonical_team", self._fake_canonical)
        return match_event_blob

    def test_a_code_the_map_cannot_reach_resolves_through_kalshis_name(
        self, monkeypatch
    ):
        """off != on, holding the fixture constant: only the map differs."""
        run = self._patched(monkeypatch)
        game = {"away_team": "Elche", "home_team": "Real Madrid", "event_id": "evt-1"}
        names = build_club_code_names(_LALIGA)["KXLALIGA"]
        assert run("ELCRMA", [game], sport="soccer")["status"] == "no_match"
        got = run("ELCRMA", [game], sport="soccer", code_names=names)
        assert got["status"] == "ok" and got["event_id"] == "evt-1"

    def test_the_map_never_alters_a_resolution_that_already_worked(
        self, monkeypatch
    ):
        """MLB is the control: its codes already resolve, and an unrelated map
        must leave it byte-identical."""
        run = self._patched(monkeypatch)
        game = {"away_team": "Minnesota Twins", "home_team": "Athletics",
                "event_id": "evt-mlb"}
        plain = run("MINATH", [game], sport="mlb")
        with_map = run("MINATH", [game], sport="mlb", code_names={"ZZZ": "Nobody"})
        assert plain["status"] == "ok"
        assert plain["status"] == with_map["status"]
        assert plain.get("event_id") == with_map.get("event_id")

    def test_a_wrong_fixture_still_refuses_with_the_map_present(self, monkeypatch):
        run = self._patched(monkeypatch)
        other = {"away_team": "Elche", "home_team": "Elche", "event_id": "evt-x"}
        names = build_club_code_names(_LALIGA)["KXLALIGA"]
        assert run("ELCRMA", [other], sport="soccer", code_names=names)["status"] == "no_match"

    def test_two_of_our_games_producing_one_blob_stay_ambiguous(self, monkeypatch):
        run = self._patched(monkeypatch)
        names = build_club_code_names(_LALIGA)["KXLALIGA"]
        out = run(
            "ELCRMA",
            [
                {"away_team": "Elche", "home_team": "Real Madrid", "event_id": "evt-1"},
                {"away_team": "Elche", "home_team": "Real Madrid", "event_id": "evt-2"},
            ],
            sport="soccer", code_names=names,
        )
        assert out["status"] == "ambiguous"


@needs_soccer_aliases
class TestResolutionAgainstTheRealAliasMap:
    """Against the REAL per-league club map, on a REAL production fixture.

    THE FIXTURE CHOICE IS THE TEST. A first version used `ELCRMA` and failed
    its own off!=on assertion -- because `ELC` already resolved by CODE, so the
    map changed nothing and there was no difference to detect. That is the
    fixture-cannot-violate-the-property trap from the other direction: a
    passing "on" case proves nothing unless the "off" case genuinely fails.

    `TFCLIL` (Toulouse v Lille, Ligue 1, ticker shape read from production
    2026-09-01) is the honest case: measured, `canonical_team("soccer","TFC")`
    is **None** while `canonical_team("soccer","Toulouse")` resolves. So the
    code is unreachable and Kalshi's own name is what rescues it.
    """

    _LIGUE1 = [
        _m("KXLIGUE1GAME-26SEP03TFCLIL-TFC", "KXLIGUE1GAME", "Toulouse wins"),
        _m("KXLIGUE1GAME-26SEP03TFCLIL-LIL", "KXLIGUE1GAME", "Lille wins"),
    ]

    def test_the_code_really_is_unresolvable_and_the_name_really_is_not(self):
        """Pins the premise. If our alias map ever learns `TFC`, this fixture
        stops testing anything and this test says so rather than going quietly
        green."""
        from syndicate.features.shared.team_aliases import canonical_team

        assert canonical_team("soccer", "TFC") is None
        assert canonical_team("soccer", "Toulouse")

    def test_a_real_fixture_resolves_ONLY_once_kalshis_names_are_supplied(self):
        names = build_club_code_names(self._LIGUE1)["KXLIGUE1"]
        game = {"away_team": "Toulouse", "home_team": "Lille", "event_id": "evt-tfc"}
        assert match_event_blob("TFCLIL", [game], sport="soccer")["status"] == "no_match"
        got = match_event_blob("TFCLIL", [game], sport="soccer", code_names=names)
        assert got["status"] == "ok"
        assert got["event_id"] == "evt-tfc"
        assert got["away_team"] == "Toulouse" and got["home_team"] == "Lille"

    def test_the_sides_are_not_swapped_by_the_substitution(self):
        """A resolver that matched the fixture but inverted home/away would be
        a confidently-priced bet on the wrong team."""
        names = build_club_code_names(self._LIGUE1)["KXLIGUE1"]
        reversed_game = {"away_team": "Lille", "home_team": "Toulouse", "event_id": "evt-rev"}
        assert match_event_blob(
            "TFCLIL", [reversed_game], sport="soccer", code_names=names
        )["status"] == "no_match"
