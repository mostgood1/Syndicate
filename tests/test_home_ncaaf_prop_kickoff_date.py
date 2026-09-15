"""NCAAF prop rows carry their game's CENTRAL kickoff date as `slate_date`.

Lane `ncaaf-prop-kickoff-slate-date`, from lane `quote-shard-date-fallback-prod`
(2026-09-15). NCAAF legacy prop rows came from `_compact_prop_rows` with no date of
their own; `_finalize_home_prop_rows` filled a date only from `scheduled_start_utc`,
which NCAAF games do not have; and `_build_prop_dashboard_row` rebuilt the dict
without one. `quote_enrichment._row_slate_date` returned None for 102/102 rows
replayed over production, so `enrich_prop_rows` joined the WORKER'S today -- a quote
shard that did not exist -- and all 104 production rows were unpriced.

`slate_date`, not `commence_time`: `_row_slate_date` slices `commence_time[:10]`,
the UTC date, while quote shards are keyed by CENTRAL kickoff date.

THE FIXTURE IS THE PRODUCTION SHAPE, on purpose. A first version of these tests built
a game with a top-level `kickoff` -- a shape the prop games never have -- and passed
8/8 while the same fix dated 0 of 102 real rows. The games here mirror
`/ncaaf/api/cards?week=3` (2026-09-15): a string `gamePk`, `startTime`, and
`ncaaf_card.scoreboard.kickoff`, with prop rows produced by the real
`_compact_prop_rows` and matched by the real game index.
"""

from __future__ import annotations

from syndicate.blueprints import home
from syndicate.features.shared import odds_book_quotes, quote_enrichment

# Friday 2026-09-18, 7:00 PM CDT. Its UTC date is the 19th; its shard is the 18th.
FRIDAY_NIGHT_KICKOFF = "2026-09-19T00:00:00.000Z"
GAME_KEY = "3_Syracuse_Pittsburgh"
SPORT = {"slug": "ncaaf", "name": "NCAAF", "context_label": "2026 Week 3"}


def _board_game(kickoff=FRIDAY_NIGHT_KICKOFF, *, with_start_time=True):
    """A game-board NCAAF game as the prop path receives it (production shape)."""
    game = {
        "gamePk": GAME_KEY,
        "away": {"abbr": "SYR", "name": "Syracuse"},
        "home": {"abbr": "PIT", "name": "Pittsburgh"},
        "ncaaf_card": {
            "scoreboard": {"kickoff": kickoff},
            "scoreboard_header": {"kickoff": kickoff},
        },
        "shared_prop_rows": [
            {"name": "Jane Runner", "market": "Anytime TD", "pick": "Anytime TD - 3 books", "line": "-", "odds": "+150", "value": "+150"},
        ],
    }
    if with_start_time:
        game["startTime"] = kickoff
    return game


def _finalize(slug, game):
    rows = home._compact_prop_rows([game])
    return home._finalize_home_prop_rows(rows, slug=slug, context_label="2026 Week 3", home_games=[game])


def test_precondition_the_compact_row_matches_its_game():
    # Without this, a green result could come from the no-match path.
    game = _board_game()
    rows = home._compact_prop_rows([game])
    assert len(rows) == 1
    assert home._home_prop_matched_game(rows[0], home._home_prop_game_index([game])) is game


def test_an_evening_kickoff_gets_the_central_date_not_the_utc_date():
    finalized = _finalize("ncaaf", _board_game())
    assert finalized[0]["slate_date"] == "2026-09-18"


def test_the_nested_card_kickoff_is_read_when_start_time_is_absent():
    finalized = _finalize("ncaaf", _board_game(with_start_time=False))
    assert finalized[0]["slate_date"] == "2026-09-18"


def test_the_raw_card_shape_top_level_kickoff_is_read():
    raw = {"away": {"abbr": "SYR"}, "home": {"abbr": "PIT"}, "kickoff": FRIDAY_NIGHT_KICKOFF}
    assert home._ncaaf_game_kickoff_slate_date(raw) == "2026-09-18"


def test_a_placeholder_kickoff_sets_no_date():
    # Unknown is not defaulted: a row filed under a guessed date is indistinguishable
    # from one that really kicks off then.
    finalized = _finalize("ncaaf", _board_game("Week 3 kickoff unavailable"))
    assert not finalized[0].get("slate_date")


def test_other_sports_are_unchanged():
    finalized = _finalize("nfl", _board_game())
    assert not finalized[0].get("slate_date")


def test_an_existing_slate_date_is_kept():
    game = _board_game()
    rows = home._compact_prop_rows([game])
    rows[0]["slate_date"] = "2026-09-17"
    finalized = home._finalize_home_prop_rows(rows, slug="ncaaf", context_label="2026 Week 3", home_games=[game])
    assert finalized[0]["slate_date"] == "2026-09-17"


def test_the_date_survives_the_dashboard_rebuild_and_the_candidate_builder():
    from syndicate.features import intelligence

    finalized = _finalize("ncaaf", _board_game())

    dashboard_row = home._build_prop_dashboard_row(SPORT, finalized[0], default_surface="Props")
    assert dashboard_row["slate_date"] == "2026-09-18"
    assert quote_enrichment._row_slate_date(dashboard_row) == "2026-09-18"

    candidate = intelligence._prop_candidate_from_item(SPORT, finalized[0], surface_key="pregame", surface_title="Pregame props")
    assert candidate is not None
    assert quote_enrichment._row_slate_date(candidate) == "2026-09-18"


def test_a_row_without_a_date_still_serialises_slate_date_as_absent():
    item = {"name": "Some Player", "market": "Hits", "pick": "Over", "line": "0.5", "odds": "-110"}
    dashboard_row = home._build_prop_dashboard_row({"slug": "mlb", "name": "MLB"}, item, default_surface="Props")
    assert dashboard_row["slate_date"] is None


def test_the_quote_join_reads_the_kickoff_shard_not_the_workers_today(monkeypatch):
    """Reachability, off != on, at the join itself: the date `quote_ref_for_bet` receives."""
    from syndicate.features import intelligence

    seen: list[str] = []

    def _capture(**kwargs):
        seen.append(kwargs.get("date_str"))
        return None

    monkeypatch.setattr(odds_book_quotes, "quote_ref_for_bet", _capture)
    worker_today = "2026-09-15"

    finalized = _finalize("ncaaf", _board_game())
    on = intelligence._prop_candidate_from_item(SPORT, finalized[0], surface_key="pregame", surface_title="Pregame props")
    quote_enrichment.enrich_prop_rows([on], date_str=worker_today)

    off = dict(on)
    off.pop("slate_date", None)  # the row shape before this fix
    quote_enrichment.enrich_prop_rows([off], date_str=worker_today)

    assert seen == ["2026-09-18", worker_today]
