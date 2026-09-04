"""Ligatures and stroke letters fold to ASCII instead of becoming a SPACE.

`_norm_name` already folds accents: NFD, then drop category Mn. That cannot
touch a LIGATURE or a STROKE letter -- `ø` is a single codepoint with no
combining mark, so NFD leaves it alone and the `[^a-z ]` scrub replaces it with
a space.

MEASURED ON THE LIVE NORMALISER 2026-09-04, before the fix:

    Emil Højbjerg     -> 'emil h jbjerg'     SPLIT IN HALF
    Rasmus Højlund    -> 'rasmus h jlund'    SPLIT IN HALF
    Tom Krauß         -> 'tom krau'
    Łukasz Fabiański  -> 'ukasz fabianski'   vs ASCII 'lukasz fabianski'

The last pair is the defect in one line: the same player spelled natively by one
feed and in ASCII by the other produced DIFFERENT keys, so the join could never
see them as the same person. 24 of 3,139 sim soccer names carry one of these.

THIS FUNCTION IS CROSS-SPORT -- `soccer_projections` imports it and the MLB prop
join uses it -- so MLB spellings are asserted here too.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.shared.prop_projections import _norm_name  # noqa: E402

NATIVE_AND_ASCII = [
    ("Emil Højbjerg", "Emil Hojbjerg"),
    ("Rasmus Højlund", "Rasmus Hojlund"),
    ("Martin Ødegaard", "Martin Odegaard"),
    ("Leo Østigard", "Leo Ostigard"),
    ("Tom Krauß", "Tom Krauss"),
    ("Łukasz Fabiański", "Lukasz Fabianski"),
]


def test_the_two_spellings_of_one_player_produce_ONE_key():
    """THE test. Everything else here guards this from passing vacuously."""
    for native, ascii_form in NATIVE_AND_ASCII:
        assert _norm_name(native) == _norm_name(ascii_form), (
            "%r -> %r  but  %r -> %r"
            % (native, _norm_name(native), ascii_form, _norm_name(ascii_form)))


def test_a_stroke_letter_no_longer_SPLITS_the_name():
    """`ø` became a space, which is worse than being dropped: it turned one
    token into two and no token-subset rule could recover it."""
    assert _norm_name("Emil Højbjerg") == "emil hojbjerg"
    assert _norm_name("Rasmus Højlund") == "rasmus hojlund"
    for native, _ in NATIVE_AND_ASCII:
        assert len(_norm_name(native).split()) == len(native.split()), (
            "%r changed its token count" % native)


def test_the_eszett_becomes_ss_as_the_feeds_write_it():
    assert _norm_name("Tom Krauß") == "tom krauss"
    assert _norm_name("Krauß") == _norm_name("Krauss")


def test_the_ligatures_expand():
    assert _norm_name("Æthelstan") == "aethelstan"
    assert _norm_name("Œuvre") == "oeuvre"


def test_accents_still_fold_the_way_they_did():
    """The fix runs BEFORE NFD; it must not disturb the fold that already worked
    (`#218`, and the MLB accent repair of 2026-08-16)."""
    assert _norm_name("Saša Lukić") == _norm_name("Sasa Lukic") == "sasa lukic"
    assert _norm_name("Eugenio Suárez") == "eugenio suarez"
    assert _norm_name("Andrés Giménez") == "andres gimenez"
    assert _norm_name("Francisco Álvarez") == "francisco alvarez"


def test_plain_ascii_names_are_untouched():
    """Off != on in the other direction: this must only ADD joins."""
    for name, want in (
        ("Aaron Judge", "aaron judge"),
        ("Dara O'Shea", "dara oshea"),
        ("Jean-Philippe Mateta", "jean philippe mateta"),
        ("A.J. Puk", "a j puk"),
    ):
        assert _norm_name(name) == want, name


def test_empty_and_junk_are_unchanged():
    assert _norm_name(None) == ""
    assert _norm_name("") == ""
    assert _norm_name("   ") == ""


def test_the_fold_is_applied_before_the_scrub_not_after():
    """Order is the whole fix. Applied after the `[^a-z ]` scrub the characters
    would already be spaces, and the table would be a no-op that looks correct
    in review."""
    assert "ss" in _norm_name("ß"), "ß must survive as ss, not vanish"
    assert _norm_name("ø") == "o"
