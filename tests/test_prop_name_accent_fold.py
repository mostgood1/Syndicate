"""Accented sim-side names join to plain quote-side names.

THE DEFECT. `_norm_name`'s docstring claimed accents were folded -- "the same
fold `#218`'s team matching needed" -- and the code did the opposite. With no
decomposition step, `re.sub(r"[^a-z ]", " ", text)` replaced each accented
letter WITH A SPACE:

    sim feed    "Eugenio Suárez"  ->  "eugenio su rez"
    quote feed  "Eugenio Suarez"  ->  "eugenio suarez"     never joins

MEASURED, both sides. Sim side, across the local hitter-prop artifacts: **412
distinct hitters, 33 accented (8.0%)** -- Rodríguez, Sánchez, Peña, Domínguez,
Giménez. Quote side: plain ASCII throughout. So the asymmetry is real and it is
one-directional, which is exactly the shape that breaks a join silently.

Board impact, 2026-08-16: of 75 MLB players carrying NO projection on ANY stat,
**18 match an accented sim-side name**. The remaining 57 are a genuine lineup
question and this change does not touch them -- recorded so the fix is not
credited with the whole population.

The correct pattern already existed two files away in
`basketball_props_edges._norm_name`, which has folded with NFKD since it was
written.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared.prop_projections import PropProjectionIndex, _norm_name


@pytest.mark.parametrize(
    "accented,plain",
    [
        ("Eugenio Suárez", "Eugenio Suarez"),
        ("Andrés Giménez", "Andres Gimenez"),
        ("Francisco Álvarez", "Francisco Alvarez"),
        ("Julio Rodríguez", "Julio Rodriguez"),
        ("Jeremy Peña", "Jeremy Pena"),
        ("Jasson Domínguez", "Jasson Dominguez"),
        ("Mauricio Dubón", "Mauricio Dubon"),
        ("José Caballero", "Jose Caballero"),
    ],
)
def test_the_two_feeds_agree_on_an_accented_name(accented, plain):
    assert _norm_name(accented) == _norm_name(plain)


def test_the_accent_is_folded_not_deleted():
    """The precise regression. Deleting gives "su rez"; folding gives "suarez".

    Asserting the VALUE, not just equality -- two names could agree by both
    being shattered the same way, which would pass an equality-only test while
    still failing to join anything real.
    """
    assert _norm_name("Eugenio Suárez") == "eugenio suarez"
    assert _norm_name("Andrés Giménez") == "andres gimenez"
    assert "su rez" not in _norm_name("Eugenio Suárez")


def test_enye_and_umlaut_fold_to_their_base_letters():
    """`ñ` -> `n`, `ü` -> `u`: what the quote feeds do when they strip accents."""
    assert _norm_name("Jeremy Peña") == "jeremy pena"
    assert _norm_name("Müller") == "muller"


def test_unaccented_names_are_unchanged():
    """The fold must be inert where there is nothing to fold."""
    for name in ("Christian Yelich", "Aaron Judge", "Mike Trout"):
        assert _norm_name(name) == name.lower()


def test_punctuation_handling_is_preserved():
    """The pre-existing behaviour this change must not disturb."""
    assert _norm_name("Luis Robert Jr.") == _norm_name("Luis Robert Jr")
    assert _norm_name("Logan O'Hoppe") == _norm_name("Logan OHoppe")
    assert _norm_name("Jean-Carlos Mejia") == _norm_name("Jean Carlos Mejia")


def test_the_join_itself_now_finds_the_player():
    """Through the index, not the helper alone.

    The helper agreeing proves the function; this proves the lookup a board row
    actually performs resolves an accented sim row from a plain quote name.
    """
    idx = PropProjectionIndex()
    idx._hitters[(_norm_name("Eugenio Suárez"), "hr_1plus")] = {
        "name": "Eugenio Suárez", "hr_mean": 0.4, "p_hr_1plus": 0.28,
    }
    got = idx.project(player_name="Eugenio Suarez", market="batter_home_runs", line=0.5)
    assert got is not None, "the plain quote name still does not reach the accented sim row"
    assert got["model_prob_over"] == 0.28


@pytest.mark.parametrize("value", [None, "", "   ", 123])
def test_degenerate_input_is_still_an_empty_or_safe_key(value):
    assert isinstance(_norm_name(value), str)
