"""`#557` -- OddsAPI game lines reaching the NCAAF board.

REACHABILITY BEFORE CORRECTNESS. `model_engine_standard.md` requires `off != on`
for anything behind new plumbing, and it earned its place here twice while this
was being built:

  1. The first version resolved the quote log's `selection` against the TEAM
     NAME. The shared flattener already normalises it to `home`/`away`, so every
     spread and moneyline silently vanished while TOTALS -- whose outcome name
     really is "Over" -- kept working. A partly-populated board looked like thin
     book coverage, not a bug.
  2. Even with a correct line index, `markets` stayed null on all 51 games,
     because the card never emitted the `betting` block the shared publication
     adapter reads. The line existed and the board could not see it.

Neither would have failed a correctness test that only asserted "the number is
right when present".
"""

from __future__ import annotations

import math

import pytest

from syndicate.features.ncaaf import cards as ncaaf_cards
from syndicate.features.ncaaf import oddsapi_lines as ol


# --------------------------------------------------------------------------
# team-name join
# --------------------------------------------------------------------------

def test_cfbd_canonical_names_resolve_to_themselves():
    """The identity control. If CFBD's own names do not round-trip, the join is
    broken in a way no OddsAPI fixture would reveal."""
    for name in ("TCU", "North Carolina", "Florida State", "UNLV"):
        assert ol.resolve_team(name) == name


def test_oddsapi_school_plus_mascot_resolves():
    assert ol.resolve_team("TCU Horned Frogs") == "TCU"
    assert ol.resolve_team("North Carolina Tar Heels") == "North Carolina"
    assert ol.resolve_team("Florida State Seminoles") == "Florida State"


def test_diacritics_and_apostrophes_survive_the_join():
    """OddsAPI spells these without the accent; CFBD carries it.

    The board's own `_normalize_text` DELETES non-ASCII rather than folding it,
    so "San Jose State" and "San José State" normalise to different strings
    there. `oddsapi_lines.fold` transliterates first, which is the only reason
    these meet at all.
    """
    assert ol.resolve_team("San Jose State Spartans") == "San José State"
    assert ol.resolve_team("Hawaii Rainbow Warriors") == "Hawai'i"


def test_a_bare_mascot_never_resolves():
    """~680 schools share mascots (`state.md`). A mascot identifies nobody, and
    guessing would put another game's price on this card."""
    for mascot in ("Bulldogs", "Wildcats", "Tigers", "Eagles"):
        assert ol.resolve_team(mascot) is None


def test_unknown_and_empty_names_return_none_rather_than_guessing():
    assert ol.resolve_team("") is None
    assert ol.resolve_team(None) is None
    assert ol.resolve_team("Not A Real School Somethings") is None


def test_supplement_entries_all_name_real_teams():
    """The supplement RAISES on an entry naming a team that does not exist. A
    skipped alias is a team that quietly loses its line, so this asserts the
    guard is live rather than trusting it."""
    mapping = ol._alias_map()
    known = set(mapping.values())
    for alias, canonical in ol._ODDSAPI_NAME_SUPPLEMENT.items():
        assert canonical in known, f"{alias!r} -> {canonical!r} is not a canonical team"
        assert ol.resolve_team(alias) == canonical


# --------------------------------------------------------------------------
# selection side
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "selection,expected",
    [
        ("home", "home"),
        ("away", "away"),
        ("over", "over"),
        ("under", "under"),
        ("Over", "over"),
        ("Over 45.5", "over"),
        ("", None),
        ("Draw", None),
    ],
)
def test_selection_side_tokens(selection, expected):
    assert ol._selection_side(selection, home_raw="TCU Horned Frogs", away_raw="North Carolina Tar Heels") == expected


def test_selection_side_falls_back_to_team_names():
    """The log is shared; a future writer may not go through the flattener that
    normalises sides."""
    assert ol._selection_side("TCU Horned Frogs", home_raw="TCU Horned Frogs", away_raw="North Carolina Tar Heels") == "home"
    assert ol._selection_side("North Carolina Tar Heels", home_raw="TCU Horned Frogs", away_raw="North Carolina Tar Heels") == "away"


# --------------------------------------------------------------------------
# line index
# --------------------------------------------------------------------------

def _quote(market, selection, *, book="draftkings", line=None, price=None):
    return {
        "kind": "game",
        "segment": "full",
        "home_team": "TCU Horned Frogs",
        "away_team": "North Carolina Tar Heels",
        "bookmaker": book,
        "market": market,
        "selection": selection,
        "line": line,
        "price": price,
    }


KEY = (ncaaf_cards._normalize_text("TCU"), ncaaf_cards._normalize_text("North Carolina"))


def test_line_index_negates_the_book_spread_into_a_home_margin():
    """THE SIGN TEST, and it is the one that matters most.

    `market_margin` is a HOME MARGIN (positive = home favoured); a book quotes
    the home side at a NEGATIVE number when it is favoured. `state.md` records
    this exact inversion costing a whole NFL analysis while producing entirely
    plausible numbers.
    """
    rows = [_quote("spreads", "home", line=-15.0, price=-110)]
    index = ol.build_line_index(rows, key_fn=ncaaf_cards._normalize_text)
    assert index[KEY]["market_margin"] == pytest.approx(15.0)


def test_line_index_ignores_the_away_spread_so_the_pair_cannot_cancel():
    rows = [
        _quote("spreads", "home", line=-15.0, price=-110),
        _quote("spreads", "away", line=15.0, price=-110),
    ]
    index = ol.build_line_index(rows, key_fn=ncaaf_cards._normalize_text)
    assert index[KEY]["market_margin"] == pytest.approx(15.0)


def test_line_index_averages_spread_and_total_across_books():
    rows = [
        _quote("spreads", "home", book="draftkings", line=-14.0, price=-110),
        _quote("spreads", "home", book="fanduel", line=-15.0, price=-110),
        _quote("totals", "over", book="draftkings", line=44.0, price=-110),
        _quote("totals", "over", book="fanduel", line=45.0, price=-110),
    ]
    index = ol.build_line_index(rows, key_fn=ncaaf_cards._normalize_text)
    assert index[KEY]["market_margin"] == pytest.approx(14.5)
    assert index[KEY]["market_total"] == pytest.approx(44.5)
    assert index[KEY]["book_count"] == 2


def test_line_index_takes_moneylines_from_one_book_not_an_average():
    """American odds do not average meaningfully, so the CFBD reader this
    supplements takes the first book quoting BOTH sides. Same rule here, or the
    two sources would produce differently-shaped numbers for one game."""
    rows = [
        _quote("h2h", "home", book="draftkings", price=-320),
        _quote("h2h", "away", book="draftkings", price=260),
        _quote("h2h", "home", book="fanduel", price=-340),
        _quote("h2h", "away", book="fanduel", price=280),
    ]
    index = ol.build_line_index(rows, key_fn=ncaaf_cards._normalize_text)
    assert index[KEY]["home_moneyline"] in (-320, -340)
    assert index[KEY]["away_moneyline"] in (260, 280)
    # Never the mean of the two books.
    assert index[KEY]["home_moneyline"] != pytest.approx(-330)


def test_line_index_keeps_only_the_latest_quote_per_book_and_market():
    """The log is append-only; a moved line must not be averaged with its own
    earlier value."""
    rows = [
        _quote("spreads", "home", line=-14.0, price=-110),
        _quote("spreads", "home", line=-16.0, price=-110),
    ]
    index = ol.build_line_index(rows, key_fn=ncaaf_cards._normalize_text)
    assert index[KEY]["market_margin"] == pytest.approx(16.0)


def test_line_index_drops_non_full_game_segments():
    """A first-quarter total shown as the game total is `learnings.md`
    2026-08-21's failure: a number that is right and labelled wrong."""
    row = _quote("totals", "over", line=10.5, price=-110)
    row["segment"] = "q1"
    index = ol.build_line_index([row], key_fn=ncaaf_cards._normalize_text)
    assert index == {}


def test_line_index_drops_player_props():
    row = _quote("totals", "over", line=250.5, price=-110)
    row["kind"] = "prop"
    index = ol.build_line_index([row], key_fn=ncaaf_cards._normalize_text)
    assert index == {}


def test_line_index_skips_games_whose_teams_do_not_resolve():
    """An unresolved team costs that game its line. Inventing a key for it would
    cost some OTHER game the wrong line."""
    row = _quote("spreads", "home", line=-3.0, price=-110)
    row["home_team"] = "Some Unknown Academy Somethings"
    index = ol.build_line_index([row], key_fn=ncaaf_cards._normalize_text)
    assert index == {}


def test_line_index_key_matches_the_board_key_exactly():
    """The index is keyed with the board's OWN `_normalize_text`, passed in
    rather than reimplemented, so the two cannot drift."""
    rows = [_quote("spreads", "home", line=-15.0, price=-110)]
    index = ol.build_line_index(rows, key_fn=ncaaf_cards._normalize_text)
    assert list(index) == [(ncaaf_cards._normalize_text("TCU"), ncaaf_cards._normalize_text("North Carolina"))]


# --------------------------------------------------------------------------
# the card's betting block -- what the shared adapter actually reads
# --------------------------------------------------------------------------

class _Projection:
    margin_mean = 10.263
    margin_stdev = 13.291
    total_mean = 50.337
    total_stdev = 11.719
    home_win_rate = 0.80


def test_betting_block_inverts_the_home_margin_into_a_book_spread():
    row = {"market_margin": 14.875, "market_total": 43.75, "home_moneyline": -320, "away_moneyline": 260}
    betting = ncaaf_cards._smartsim2_standalone_betting(row, _Projection())
    assert betting["home_spread"] == pytest.approx(-14.875)
    assert betting["away_spread"] == pytest.approx(14.875)
    assert betting["total"] == pytest.approx(43.75)
    assert betting["home_ml"] == -320


def test_cover_probability_is_priced_against_the_market_line_not_the_model():
    """The model has the home side by 10.3 against a market asking 14.875, so it
    does NOT expect a cover: P(home cover) must be below 0.5.

    The inverted form of this returned 0.97 -- a plausible-looking number that
    said the exact opposite. It was caught by reading the output, not by a test,
    which is why there is now a test.
    """
    row = {"market_margin": 14.875, "market_total": 43.75}
    betting = ncaaf_cards._smartsim2_standalone_betting(row, _Projection())
    assert betting["p_home_cover"] < 0.5
    assert betting["p_home_cover"] + betting["p_away_cover"] == pytest.approx(1.0)


def test_cover_probability_exceeds_half_when_the_model_beats_the_line():
    row = {"market_margin": 3.0, "market_total": 43.75}
    betting = ncaaf_cards._smartsim2_standalone_betting(row, _Projection())
    assert betting["p_home_cover"] > 0.5


def test_probabilities_stay_none_without_a_line():
    """Pricing the model against its own number compares it to itself and reads
    as a permanent zero edge, which is worse than an honest gap."""
    betting = ncaaf_cards._smartsim2_standalone_betting({}, _Projection())
    assert betting["p_home_cover"] is None
    assert betting["p_total_over"] is None
    assert betting["home_spread"] is None
    # The model's own win probability does not depend on a book and stays.
    assert betting["p_home_win"] == pytest.approx(0.80)


def test_market_tiles_say_no_line_rather_than_showing_a_dash():
    tiles = ncaaf_cards._smartsim2_standalone_market_tiles({})
    assert tiles[0]["title"] == "No line"
    assert tiles[1]["title"] == "No line"


def test_market_tiles_show_the_favourite_side_of_the_spread():
    tiles = ncaaf_cards._smartsim2_standalone_market_tiles(
        {"market_margin": 14.875, "market_total": 43.75, "home_team": "TCU", "away_team": "North Carolina", "market_book_count": 4}
    )
    assert tiles[0]["title"] == "TCU -14.9"
    tiles_away = ncaaf_cards._smartsim2_standalone_market_tiles(
        {"market_margin": -7.5, "market_total": 43.75, "home_team": "TCU", "away_team": "North Carolina", "market_book_count": 4}
    )
    assert tiles_away[0]["title"] == "North Carolina -7.5"


# --------------------------------------------------------------------------
# reachability -- the whole point
# --------------------------------------------------------------------------

def test_board_markets_are_empty_without_a_line_index_and_populated_with_one(monkeypatch):
    """OFF != ON, end to end through the real board builder.

    Asserted as a COUNT over the served games rather than on one card: the bug
    this replaces populated some markets and not others, and a single-card
    assertion would have passed throughout.
    """
    def _anyval(value):
        if isinstance(value, dict):
            return any(_anyval(inner) for inner in value.values())
        return value is not None

    def _priced(games):
        return sum(1 for game in games if ((game.get("markets") or {}).get("total") or {}).get("line") is not None)

    monkeypatch.setattr(ncaaf_cards, "_smartsim2_standalone_market_lines", lambda *a, **k: {})
    ncaaf_cards._smartsim2_standalone_rows.cache_clear() if hasattr(ncaaf_cards._smartsim2_standalone_rows, "cache_clear") else None
    off = ncaaf_cards.build_smartsim_cards_page_context(1).get("games") or []
    if not off:
        pytest.skip("no NCAAF projection artifact in this checkout; nothing to price")
    assert _priced(off) == 0

    sample = {
        (ncaaf_cards._normalize_text(g["ncaaf_card"]["teams"]["home"]["team_name"]),
         ncaaf_cards._normalize_text(g["ncaaf_card"]["teams"]["away"]["team_name"])):
            {"market_margin": 7.5, "market_total": 51.5, "home_moneyline": -300, "away_moneyline": 240,
             "book_count": 4, "source": "oddsapi_book_quotes"}
        for g in off[:3]
    }
    monkeypatch.setattr(ncaaf_cards, "_smartsim2_standalone_market_lines", lambda *a, **k: dict(sample))
    on = ncaaf_cards.build_smartsim_cards_page_context(1).get("games") or []
    assert _priced(on) == len(sample) > 0


# --------------------------------------------------------------------------
# the compact card
# --------------------------------------------------------------------------

def test_compact_spread_is_a_signed_home_spread():
    """A home MARGIN of +14.9 (home favoured) is a home SPREAD of -14.9."""
    assert ncaaf_cards._market_metric_row(14.875) == {"label": "Market spread", "value": "-14.9"}
    assert ncaaf_cards._market_metric_row(-7.5) == {"label": "Market spread", "value": "+7.5"}
    assert ncaaf_cards._market_metric_row(0) == {"label": "Market spread", "value": "PK"}


def test_compact_metric_values_fit_the_strip_tile():
    """THE REGRESSION GUARD. `.cards-mini-metrics--strip` shows roughly six
    characters and clips the rest with no wrap and no ellipsis, so a long value
    is silently truncated on the most-scanned surface of the board. Measured:
    "TCU -14.9" rendered as "TC -14".

    Six is the budget; this asserts the widest realistic spread stays inside it.
    """
    for margin in (14.875, -7.5, 0, 49.5, -49.5, 3.0):
        row = ncaaf_cards._market_metric_row(margin)
        assert len(row["value"]) <= 6, (margin, row["value"])


def test_market_metric_row_is_dropped_rather_than_dashed_when_unquoted():
    """An empty tile reads as a broken card; a missing one just lets the model
    rows move up."""
    assert ncaaf_cards._market_metric_row(None) is None


def test_the_compact_card_leads_with_the_market_when_there_is_one(monkeypatch):
    """`shared/_scoreboard_strip_generic.html` renders `metrics[:3]` and nothing
    else, so the first three entries ARE the compact card. This pins that a
    priced game leads with the price and an unpriced one still fills all three
    slots with model rows.
    """
    off = ncaaf_cards.build_smartsim_cards_page_context(1).get("games") or []
    if not off:
        pytest.skip("no NCAAF projection artifact in this checkout")

    keys = [
        (ncaaf_cards._normalize_text(g["ncaaf_card"]["teams"]["home"]["team_name"]),
         ncaaf_cards._normalize_text(g["ncaaf_card"]["teams"]["away"]["team_name"]))
        for g in off[:2]
    ]
    priced = {
        keys[0]: {"market_margin": 7.5, "market_total": 51.5, "home_moneyline": -300,
                  "away_moneyline": 240, "book_count": 4, "source": "oddsapi_book_quotes"}
    }
    monkeypatch.setattr(ncaaf_cards, "_smartsim2_standalone_market_lines", lambda *a, **k: dict(priced))
    games = ncaaf_cards.build_smartsim_cards_page_context(1).get("games") or []
    by_key = {
        (ncaaf_cards._normalize_text(g["ncaaf_card"]["teams"]["home"]["team_name"]),
         ncaaf_cards._normalize_text(g["ncaaf_card"]["teams"]["away"]["team_name"])): g
        for g in games
    }

    labels_priced = [row["label"] for row in by_key[keys[0]]["metrics"][:3]]
    assert labels_priced[:2] == ["Market spread", "Market total"]

    labels_unpriced = [row["label"] for row in by_key[keys[1]]["metrics"][:3]]
    assert "Market spread" not in labels_unpriced
    assert len(labels_unpriced) == 3


# --------------------------------------------------------------------------
# the odds sweep
# --------------------------------------------------------------------------

def test_the_sweep_runs_the_game_lines_capture_before_the_legacy_bundle():
    """`#552`. Without this step the fetcher had no automated caller at all and
    the board could never carry a price.

    Order is asserted, not just membership: if the legacy bundle step fails, the
    book lines are already captured, and the reverse is not true.
    """
    import argparse

    from scripts import refresh_odds_sources

    steps = refresh_odds_sources._build_ncaaf_steps(
        argparse.Namespace(week=None, season=None, date="2026-08-29")
    )
    names = [step.name for step in steps]
    # THIRD COPY OF A STALE STEP LIST, and the last one. `28324d06`
    # (2026-08-26) added `ncaaf_player_props_oddsapi` between these two,
    # moving the props capture OFF `refresh_ncaaf_oddsapi.py` because that
    # runner cannot execute for 2026: `_resolve_data_root` requires a
    # `college_football_schedule_<season>_predicted_totals_enhanced*.csv` and
    # git holds 359 of them, every one season 2025. Production confirmed it
    # 2026-08-27T01:04:55Z -- `ncaaf_lines_snapshot` died in zero seconds with
    # FileNotFoundError while `ncaaf_game_lines_oddsapi` succeeded in the same
    # sweep. Two sibling assertions in `tests/test_ops.py` carried the same
    # staleness and were corrected in `f05284f9`.
    #
    # The ORDER claim in this test's docstring still holds and is what matters:
    # the OddsAPI capture runs BEFORE the legacy bundle, so a bundle failure
    # cannot cost the board its prices.
    assert names == [
        "ncaaf_game_lines_oddsapi",
        "ncaaf_player_props_oddsapi",
        "ncaaf_lines_snapshot",
    ]

    capture = steps[0]
    assert capture.phases == ("pregame", "live")
    assert any(str(part).endswith("fetch_ncaaf_oddsapi_game_lines.py") for part in capture.command)


def test_the_capture_step_is_not_week_scoped():
    """NCAAF weeks are not calendar windows -- 2026 week 1 spans 08-29 to 09-07 --
    and the board reads quotes per KICKOFF DATE. A week-keyed capture would file
    ten days of games under one key and the board would find none of them, so
    passing `--week`/`--season` here would be a silent regression.
    """
    import argparse

    from scripts import refresh_odds_sources

    steps = refresh_odds_sources._build_ncaaf_steps(
        argparse.Namespace(week=3, season=2026, date="2026-09-19")
    )
    capture = steps[0]
    assert "--week" not in [str(part) for part in capture.command]
    assert "--season" not in [str(part) for part in capture.command]


# --------------------------------------------------------------------------
# spelling coverage across the whole FBS, not just one week's slate
# --------------------------------------------------------------------------

def _fbs_rows():
    import csv

    from syndicate.features.ncaaf.sources import team_registry_snapshot_path

    with open(team_registry_snapshot_path(), encoding="utf-8-sig") as handle:
        return [r for r in csv.DictReader(handle) if (r.get("subdivision") or "").lower() == "fbs"]


def test_every_fbs_team_resolves_from_the_spellings_a_feed_might_send():
    """A COUNT over all 138 FBS teams, not a spot check.

    The live `--report` cannot be run from a sandbox (no `ODDS_API_KEY`, and
    egress to api.the-odds-api.com is refused by org policy), so this is the
    substitute: exercise every realistic way a feed can render a school and
    assert the whole division resolves. An unresolved team is a game whose card
    shows no line, and on the board that is indistinguishable from "no book
    quoted it" -- so a silent miss here has no other alarm.
    """
    import unicodedata

    def deaccent(value):
        return "".join(c for c in unicodedata.normalize("NFKD", value) if not unicodedata.combining(c))

    rows = _fbs_rows()
    assert len(rows) > 100, f"registry looks wrong: only {len(rows)} FBS rows"

    spellings = {
        "school+mascot": lambda s, m: f"{s} {m}",
        "de-accented": lambda s, m: deaccent(f"{s} {m}").replace("'", ""),
        "school only": lambda s, m: s,
        "St. for State": lambda s, m: f"{s} {m}".replace(" State", " St."),
    }
    for label, render in spellings.items():
        missed = []
        for row in rows:
            canonical = row["canonical_team_name"]
            school = row.get("school_name") or ""
            mascot = row.get("mascot_name") or ""
            if not school:
                continue
            if resolve := ol.resolve_team(render(school, mascot)):
                if resolve != canonical:
                    missed.append((canonical, render(school, mascot), resolve))
            else:
                missed.append((canonical, render(school, mascot), None))
        assert missed == [], f"{label}: {len(missed)} of {len(rows)} unresolved, e.g. {missed[:5]}"


def test_the_state_abbreviation_alias_does_not_capture_real_saint_schools():
    """The `State` -> `St.` coverage ADDS aliases; it must never rewrite input.

    The registry holds 11 schools whose name genuinely begins "St."/"Saint". A
    transform mapping the token `st` to `state` on the way in would mangle every
    one of them, which is why the alias is generated per registered team
    instead.
    """
    # THE 2026 SPELLINGS. These names are read from the CFBD catalog, and
    # `d195be63` (2026-08-26, "build the 2026 team data") regenerated
    # `ncaaf_team_registry_snapshot.csv` -- which is what `resolve_team` reads --
    # with several schools RENAMED: `St. Anselm` -> `Saint Anselm`,
    # `St. Francis (PA)` -> `Saint Francis`. The older
    # `ncaaf_team_registry.csv` alongside it still carries the pre-rename
    # spellings and is NOT what the resolver reads, which is why asserting the
    # old names failed while the alias logic was working correctly the whole
    # time. Verified against the snapshot, not remembered.
    for name in ("Saint Anselm", "Saint John's (MN)", "Saint Francis", "Saint Vincent"):
        assert ol.resolve_team(name) == name, name
    assert ol.resolve_team("St. Lawrence Saints") == "St. Lawrence"
    # And the abbreviation still reaches the State schools it was added for.
    assert ol.resolve_team("Boise St. Broncos") == "Boise State"
    assert ol.resolve_team("Arizona St. Sun Devils") == "Arizona State"
