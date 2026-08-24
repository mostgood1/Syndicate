"""Coverage telemetry for the compact-card -> live-chip join.

Twice this defect was found by a person looking at the board (MLS 2026-08-22,
La Liga 2026-08-24). Both times every existing count was healthy while cards
printed full club names because they resolved no chip. The join runs in the
browser, so nothing server-side ever saw it.

These tests pin the buckets, because the whole value of the reading is that
each one has a DIFFERENT owner and a wrong label sends the next person to the
wrong place.
"""

from __future__ import annotations

from syndicate.features.shared.chip_join_coverage import chip_join_coverage


def _chip(**kw):
    base = {
        "sport": "soccer",
        "game_key": kw.pop("game_key", ""),
        "matchup": kw.pop("matchup", ""),
        "away": {"name": kw.pop("away_name", ""), "key": kw.pop("away_key", "")},
        "home": {"name": kw.pop("home_name", ""), "key": kw.pop("home_key", "")},
    }
    base.update(kw)
    return base


def _card(**kw):
    return {
        "sport": "soccer",
        "matchup": kw.get("matchup", ""),
        "away_key": kw.get("away_key"),
        "home_key": kw.get("home_key"),
        "event_id": kw.get("event_id"),
    }


def _soccer(cards, chips):
    return chip_join_coverage(cards, chips)["by_sport"]["soccer"]


def test_the_reported_defect_is_visible_in_the_reading():
    """The actual La Liga case: two feeds, two spellings, no join.

    Chip names it "Athletic Club", the odds feed names it "Athletic Bilbao".
    Without a canonical key on the card there is no deterministic route, and
    this must SAY so rather than counting the card as fine.
    """
    chips = [_chip(matchup="SEV @ ATH", away_name="Sevilla", home_name="Athletic Club",
                   away_key="sevilla", home_key="athletic club")]
    card = _card(matchup="Sevilla @ Athletic Bilbao")
    report = _soccer([card], chips)
    assert report["by_matchup"] == 0
    assert report["by_canonical"] == 0
    assert report["unknown_no_key"] == 1
    # And it NAMES the fixture -- every fix here has been an alias entry, which
    # needs the exact string the feed used.
    assert report["samples"][0]["matchup"] == "Sevilla @ Athletic Bilbao"


def test_the_canonical_key_resolves_it_and_the_reading_says_which_route():
    chips = [_chip(matchup="SEV @ ATH", away_name="Sevilla", home_name="Athletic Club",
                   away_key="sevilla", home_key="athletic club")]
    card = _card(matchup="Sevilla @ Athletic Bilbao", away_key="sevilla", home_key="athletic club")
    report = _soccer([card], chips)
    assert report["by_canonical"] == 1
    assert report["unknown_no_key"] == 0
    assert report["samples"] == []


def test_no_chip_available_is_reserved_for_when_we_actually_looked():
    """The sharp bucket: keys present, no chip for the fixture.

    This card WILL print its matchup verbatim -- no join of any kind can
    succeed. Its owner is the chip window, not the alias map.
    """
    chips = [_chip(matchup="SEV @ ATH", away_name="Sevilla", home_name="Athletic Club",
                   away_key="sevilla", home_key="athletic club")]
    card = _card(matchup="Elche @ Barcelona", away_key="elche", home_key="barcelona")
    report = _soccer([card], chips)
    assert report["no_chip_available"] == 1
    assert report["unknown_no_key"] == 0
    assert report["samples"][0]["why"] == "no_chip_available"


def test_a_keyless_card_is_never_reported_as_having_no_chip():
    """The distinction the first version of this got WRONG.

    Reporting `no_chip_available` for a keyless card asserts a chip does not
    exist on the strength of not having looked. A diagnostic that guesses is
    worse than one that abstains, because the guess is what gets acted on.
    """
    chips = [_chip(matchup="SEV @ ATH", away_name="Sevilla", home_name="Athletic Club",
                   away_key="sevilla", home_key="athletic club")]
    report = _soccer([_card(matchup="Sevilla @ Athletic Bilbao")], chips)
    assert report["no_chip_available"] == 0
    assert report["unknown_no_key"] == 1


def test_a_canonical_collision_is_dropped_and_reported_as_needing_the_fallback():
    """Two fixtures between the same clubs in one window -- two legs, a cup tie.

    The key is dropped (a wrong chip attaches one game's score to another
    game's card), so the card has no deterministic route left. It is NOT
    `no_chip_available`: chips for that fixture plainly exist, and saying
    otherwise would send someone to look at the chip window instead of at the
    collision.
    """
    chips = [
        _chip(game_key="1", matchup="A @ B", away_name="Alpha", home_name="Beta",
              away_key="alpha", home_key="beta"),
        _chip(game_key="2", matchup="A @ B (leg 2)", away_name="Alpha FC", home_name="Beta FC",
              away_key="alpha", home_key="beta"),
    ]
    # The board's OWN spelling, matching neither chip's name text -- otherwise
    # the exact-name index answers first and the collision path is never
    # reached, which is what the first version of this test actually measured.
    card = _card(matchup="Alpha Club @ Beta Club", away_key="alpha", home_key="beta")
    full = chip_join_coverage([card], chips)
    assert full["canonical_collisions_dropped"] == 1
    report = full["by_sport"]["soccer"]
    assert report["by_canonical"] == 0
    assert report["needs_fallback"] == 1
    assert report["no_chip_available"] == 0


def test_the_exact_routes_still_win_and_are_counted_separately():
    """Route attribution is the point: "it joined" and "it joined by id" differ.

    A board whose cards all resolve by the fuzzy fallback is one rename away
    from the reported defect, and a single `matched` total would hide that.
    """
    chips = [_chip(game_key="99", matchup="LEV @ OSA", away_name="Levante", home_name="Osasuna",
                   away_key="levante", home_key="osasuna")]
    by_id = _soccer([_card(matchup="whatever", event_id="99")], chips)
    assert by_id["by_id"] == 1
    by_name = _soccer([_card(matchup="Levante @ Osasuna")], chips)
    assert by_name["by_matchup"] == 1


def test_samples_are_bounded_so_one_bad_slate_cannot_flood_the_log():
    chips: list = []
    cards = [_card(matchup=f"Team {i} @ Other {i}", away_key=f"t{i}", home_key=f"o{i}")
             for i in range(50)]
    report = _soccer(cards, chips)
    assert report["no_chip_available"] == 50
    assert len(report["samples"]) == 8


def test_sports_are_kept_apart():
    chips = [_chip(matchup="LEV @ OSA", away_name="Levante", home_name="Osasuna",
                   away_key="levante", home_key="osasuna")]
    mlb_card = {"sport": "mlb", "matchup": "Levante @ Osasuna"}
    report = chip_join_coverage([mlb_card], chips)["by_sport"]
    # The soccer chip must not answer for an MLB card even on identical text.
    assert report["mlb"]["by_matchup"] == 0
    assert "soccer" not in report


def test_it_never_raises_on_junk():
    """This is telemetry attached to the board build. It must degrade."""
    assert chip_join_coverage([], []) == {"by_sport": {}, "canonical_collisions_dropped": 0}
    assert chip_join_coverage([None, {}, {"sport": ""}], [None, "x"])["by_sport"] == {}
