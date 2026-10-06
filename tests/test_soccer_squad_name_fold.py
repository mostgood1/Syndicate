"""Soccer squad/roster/starter name matching folds letters that NFKD leaves intact.

Lane `soccer-squad-name-fold` (2026-10-05): `Aron Dønnum` (stats file) never matched the
ESPN roster's `Aron Donnum`, so the departed-player roster rescue dropped him.
"""
from syndicate.features.soccer.features.lineups import _norm_player_name, resolve_starter_ids


def test_non_decomposing_letters_fold_to_the_plain_spelling():
    assert _norm_player_name("Aron Dønnum") == _norm_player_name("Aron Donnum") == "aron donnum"
    assert _norm_player_name("Joakim Mæhle") == "joakim maehle"
    assert _norm_player_name("Łukasz Fabiański") == "lukasz fabianski"


def test_ordinary_accents_still_fold_and_case_and_punctuation_are_unchanged():
    assert _norm_player_name("Kylian Mbappé") == "kylian mbappe"
    assert _norm_player_name("J.-P. Smith") == "j p smith"


def test_a_starter_spelled_with_o_resolves_the_stats_row_spelled_with_slashed_o():
    rows = [{"player_id": "p1", "player_name": "Aron Dønnum"}]
    assert resolve_starter_ids(rows, {_norm_player_name("Aron Donnum")}) == {"p1"}
