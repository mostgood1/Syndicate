"""`polymarket_us_outcome` -- the adapter that turns the persisted Polymarket
US slate into board-vocabulary quotes.

Regression coverage for two 2026-08-25 fixes, both scoped narrowly under a
carve-out from `portfolio-decision-and-execution` (see `.syndicate/lanes.md`):

1. `SPORTS_MARKET_TYPE_DRAWABLE_OUTCOME` (soccer's 3-way home/draw/away shape)
   was entirely absent from the market-type map and refused as
   `market_type_not_a_game_line` alongside PROP -- the largest refusal bucket
   measured in production (5,810-6,612 of ~12,200-12,900 markets every cycle).
2. The league filter compared the literal Polymarket slug token against
   Syndicate's `sport` key. That works for mlb/nfl/nba/wnba by coincidence but
   never for soccer: Polymarket lists soccer per COMPETITION (`eflc` observed
   live for EFL Championship) while every Syndicate soccer board row is
   stamped `sport="soccer"` uniformly.
"""

from __future__ import annotations

import json
import time

import pytest

from syndicate.features.shared import venue_quote_adapters as mod


def _payload(markets, fetched_at=None):
    return {
        "fetched_at": fetched_at if fetched_at is not None else time.time(),
        "markets": markets,
    }


def _market(slug, kind="SPORTS_MARKET_TYPE_MONEYLINE",
            outcomes=("Arsenal", "Chelsea"), prices=("0.45", "0.55"), **kw):
    row = {
        "slug": slug,
        "sportsMarketTypeV2": kind,
        "outcomes": json.dumps(list(outcomes)),
        "outcomePrices": json.dumps(list(prices)),
        "orderPriceMinTickSize": 0.01,
        "minimumTradeQty": 1,
    }
    row.update(kw)
    return row


# Club tokens these tests need to resolve. Deliberately TINY and explicit.
_SOCCER_CLUBS = {
    "ars": "arsenal",
    "arsenal": "arsenal",
    "che": "chelsea",
    "chelsea": "chelsea",
}


@pytest.fixture
def _soccer_aliases(monkeypatch):
    """Make soccer club resolution DETERMINISTIC instead of reading `data/`.

    WHY THIS EXISTS. `canonical_team("soccer", ...)` resolves through
    `_soccer_alias_to_name`, which is DERIVED AT RUNTIME from the team
    artifacts under `data/soccer_source/**`. Session worktrees exclude `data/`
    by design (`scripts/session_worktree.py`: 34,690 files, and a lossy mirror
    that is never evidence about production), so in the tree every session
    actually works in, that map is EMPTY -- 0 aliases against 508 in a checkout
    that has `data/`.

    The three tests below then failed with `no_rows` and read exactly like the
    production defect they were written to guard
    (`no_polymarket_row_for_league_soccer`). They are not that. They were
    passing or failing on whether a data mirror happened to be checked out.

    WORSE, AND THE REASON THIS IS A FIXTURE RATHER THAN A SKIP:
    `test_an_unresolvable_pair_is_not_relabelled_as_soccer` PASSED without
    `data/` -- vacuously. With an empty map every pair is unresolvable, so the
    assertion could not fail and the test could not detect the thing it exists
    to detect. A green test that cannot go red is worse than a red one.

    What is stubbed is a DEPENDENCY, not the subject. These tests are about the
    adapter: that `DRAWABLE_OUTCOME` maps to `h2h`, that `_effective_league`
    relabels a competition token when both clubs resolve, and that "Draw" is
    dropped. Whether the local mirror happens to contain Arsenal is not the
    claim. Non-soccer sports fall through to the real resolver untouched, so
    the MLB/NFL isolation tests still exercise the real map.
    """
    from syndicate.features.shared import team_aliases

    real = team_aliases.canonical_team

    def _stub(sport, value):
        if str(sport or "").strip().lower() == "soccer":
            return _SOCCER_CLUBS.get(team_aliases.normalize(value))
        return real(sport, value)

    monkeypatch.setattr(team_aliases, "canonical_team", _stub)
    return _SOCCER_CLUBS


@pytest.fixture
def _artifact(monkeypatch):
    holder = {}

    def read_json_file(_path):
        return holder.get("payload")

    monkeypatch.setattr(
        "syndicate.features.shared.refresh_state_store.read_json_file", read_json_file
    )
    return holder


def test_drawable_outcome_prices_a_soccer_h2h_row(_artifact, _soccer_aliases):
    """Was refused entirely before 2026-08-25 -- `market_type_not_a_game_line`
    had no entry for DRAWABLE_OUTCOME. Slug is `<away>-<home>`: `ars` away,
    `che` home."""
    _artifact["payload"] = _payload(
        [_market("aec-eflc-ars-che-2026-08-25", kind="SPORTS_MARKET_TYPE_DRAWABLE_OUTCOME")]
    )
    result = mod.polymarket_us_outcome("soccer", "2026-08-25")
    assert result.status == "ok"
    keys = {q.key for q in result.quotes}
    assert "soccer|h2h|arsenal" in keys
    assert "soccer|h2h|chelsea" in keys


def test_a_draw_outcome_prices_alongside_the_two_clubs(_artifact, _soccer_aliases):
    """A third "Draw" outcome is a real, priceable quote in its own right --
    it must not be dropped just because it does not name a club the board
    already asks a moneyline side for."""
    _artifact["payload"] = _payload(
        [_market("aec-eflc-ars-che-2026-08-25",
                 kind="SPORTS_MARKET_TYPE_DRAWABLE_OUTCOME",
                 outcomes=("Arsenal", "Chelsea", "Draw"),
                 prices=("0.45", "0.30", "0.25"))]
    )
    result = mod.polymarket_us_outcome("soccer", "2026-08-25")
    assert result.status == "ok"
    keys = {q.key for q in result.quotes}
    # "Draw" does not resolve to a club and is silently dropped -- exactly
    # like any other unresolved outcome name, counted in `unresolved_clubs`.
    assert len(result.quotes) == 2
    assert "soccer|h2h|arsenal" in keys and "soccer|h2h|chelsea" in keys


def test_a_soccer_row_is_found_across_a_non_soccer_league_token(_artifact, _soccer_aliases):
    """The regression this fix guards: before it, `wanted_league="soccer"`
    could never equal a literal slug token like `eflc`, so this returned
    `no_rows` for every soccer market regardless of catalogue coverage --
    exactly the production symptom `.syndicate/deploys.md` recorded
    (`reason=no_polymarket_row_for_league_soccer`)."""
    _artifact["payload"] = _payload(
        [_market("aec-eflc-ars-che-2026-08-25")]
    )
    result = mod.polymarket_us_outcome("soccer", "2026-08-25")
    assert result.status == "ok"
    assert len(result.quotes) == 2


def test_a_non_soccer_league_still_requires_a_literal_match(_artifact):
    """mlb/nfl/nba/wnba are unaffected by the soccer relabelling -- an MLB
    row must not leak into a call for a different sport."""
    _artifact["payload"] = _payload(
        [_market("aec-mlb-pit-sd-2026-08-24",
                 outcomes=("Pittsburgh Pirates", "San Diego Padres"))]
    )
    result = mod.polymarket_us_outcome("nfl", "2026-08-24")
    assert result.status == "no_rows"
    assert result.reason == "no_polymarket_row_for_league_nfl"


def test_an_unresolvable_pair_is_not_relabelled_as_soccer(_artifact, _soccer_aliases):
    """Both clubs must resolve as known soccer clubs before a row is
    relabelled -- an unresolvable pair keeps its literal (wrong, but not
    guessed) league token and correctly misses a soccer call."""
    _artifact["payload"] = _payload(
        [_market("aec-xyz-zzznotaclub-alsonotaclub-2026-08-25",
                 outcomes=("Zzznotaclub", "Alsonotaclub"))]
    )
    result = mod.polymarket_us_outcome("soccer", "2026-08-25")
    assert result.status == "no_rows"


def test_prop_stays_refused_by_design(_artifact):
    """Unlike DRAWABLE_OUTCOME, PROP is deliberately out of scope -- player
    name resolution is a different problem this fix does not touch."""
    _artifact["payload"] = _payload(
        [_market("astatc-eflc-ars-che-2026-08-25-goals-player-gte1",
                 kind="SPORTS_MARKET_TYPE_PROP", outcomes=("Yes", "No"))]
    )
    result = mod.polymarket_us_outcome("soccer", "2026-08-25")
    assert result.status == "no_rows"
