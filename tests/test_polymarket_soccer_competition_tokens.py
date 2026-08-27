"""A soccer competition is proven ONCE, not re-proven per fixture.

MEASURED IN PRODUCTION 2026-08-27 via `/api/ops/polymarket/slate`:

    markets stranded under modelled-league tokens   849
    reachable under the generic `soccer` key        735

`_effective_league` folded a row to `soccer` only when BOTH clubs resolved via
`canonical_team`. Any fixture with one unresolved club kept its raw competition
token -- `epl`, `bun`, `lal`, `lg1` -- while every Syndicate soccer board row is
stamped `sport="soccer"` and looks up `("soccer", date, market)`. So two rows in
the SAME COMPETITION landed in different buckets purely by who was playing:

    atc-lal-cel-osa-...   cel + osa resolve       -> "soccer"   findable
    atc-bun-fcb-stu-...   fcb ambiguous, dropped  -> "bun"      invisible

`fcb` is ambiguous ON PURPOSE (Bayern and Barcelona both claim it), so
`_soccer_alias_to_name` drops it rather than guess. Correct per row, and it was
silently removing the whole market from the board's reach.

MONKEYPATCHED, NOT DATA-BACKED, DELIBERATELY. `canonical_team` reads
`data/soccer_source`, which session worktrees exclude -- there it returns None
for every club and these tests would pass while asserting nothing. Stubbing the
resolver makes the test about the FOLDING RULE, which is what changed.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared import polymarket_board_join as J


RESOLVES = {"cel", "osa", "lil", "psg"}


@pytest.fixture
def stub_aliases(monkeypatch):
    """`canonical_team` that knows four clubs and nothing else."""

    def canonical_team(sport, code):
        if str(sport) != "soccer":
            return None
        return str(code).lower() if str(code).lower() in RESOLVES else None

    monkeypatch.setattr(
        "syndicate.features.shared.team_aliases.canonical_team", canonical_team, raising=False
    )
    return canonical_team


def _m(slug):
    return {"slug": slug}


LAL_RESOLVING = _m("atc-lal-cel-osa-2026-08-16-cel")
LAL_STRANDED = _m("atc-lal-fcb-stu-2026-08-28-fcb")
BUN_STRANDED = _m("atc-bun-koe-hof-2026-08-29-koe")
MLB_COLLIDING = _m("tsc-mlb-min-ath-2026-08-25-10pt5")


def test_one_resolving_fixture_proves_its_competition(stub_aliases):
    assert "lal" in J.soccer_competition_tokens([LAL_RESOLVING])


def test_a_stranded_sibling_now_folds_to_soccer(stub_aliases):
    """THE WHOLE POINT: the ambiguous fixture rides on its competition."""
    tokens = J.soccer_competition_tokens([LAL_RESOLVING, LAL_STRANDED])
    parsed = J.parse_slug(LAL_STRANDED["slug"])
    assert J._effective_league(parsed) == "lal"                 # before
    assert J._effective_league(parsed, tokens) == "soccer"      # after


def test_a_competition_with_NO_resolving_fixture_stays_unproven(stub_aliases):
    """Not a translation table. No evidence, no membership.

    `bun` is a real competition we model, and it still does not join the set --
    because nothing in the slate identified it. The remaining gap is alias
    coverage, and this test refuses to paper over it.
    """
    tokens = J.soccer_competition_tokens([BUN_STRANDED])
    assert "bun" not in tokens
    assert J._effective_league(J.parse_slug(BUN_STRANDED["slug"]), tokens) == "bun"


def test_a_modelled_sport_can_NEVER_be_proven_soccer(stub_aliases, monkeypatch):
    """The measured MLB collision must stay impossible.

    `min` -> Minnesota United, `ath` -> Athletic Club. A club-code coincidence
    once indexed an MLB totals market under `soccer` and cost a real position.
    `_NON_SOCCER_LEAGUE_TOKENS` short-circuits before any of this, so even a
    resolver that claims both MLB codes cannot reclassify the sport.
    """
    monkeypatch.setattr(
        "syndicate.features.shared.team_aliases.canonical_team",
        lambda sport, code: "anything",
        raising=False,
    )
    tokens = J.soccer_competition_tokens([MLB_COLLIDING])
    assert "mlb" not in tokens
    assert J._effective_league(J.parse_slug(MLB_COLLIDING["slug"]), tokens) == "mlb"


def test_the_default_call_is_unchanged(stub_aliases):
    """Every existing caller keeps its exact behaviour.

    `soccer_tokens=None` means "no slate in hand" -- `venue_quote_adapters`
    still calls the one-argument form.
    """
    parsed = J.parse_slug(LAL_STRANDED["slug"])
    assert J._effective_league(parsed) == J._effective_league(parsed, None) == "lal"


def test_an_unparseable_slug_cannot_poison_the_set(stub_aliases):
    assert J.soccer_competition_tokens([_m("not-a-slug"), _m(None), {}]) == frozenset()


def test_a_raising_resolver_yields_an_empty_set_not_an_exception(monkeypatch):
    """The join must survive a broken alias table, not take the tick down."""

    def boom(sport, code):
        raise RuntimeError("alias table unreadable")

    monkeypatch.setattr(
        "syndicate.features.shared.team_aliases.canonical_team", boom, raising=False
    )
    assert J.soccer_competition_tokens([LAL_RESOLVING]) == frozenset()
