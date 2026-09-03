"""The basketball prop name-join publishes its fallback's YIELD.

WHY. `_compute_props_edges_file_only_local` merges odds to predictions on a
normalised name, then RE-merges the misses on a short key. That second merge is
a real name-join fallback and it has run in production for as long as it has
existed without publishing a single number -- how many rows it rescued, and how
many are still unmatched after it.

A fallback with no measured yield cannot be told from a fallback that never
fires, and neither can be told from a slate the sim genuinely has no players
for. When the same gap was closed for MLB props on 2026-09-03 the split turned
out to matter: 191 of 1,423 player rows (13.4%) carried no projection because
the NAME did not match, against 43 where the sim genuinely had no view -- 82% of
the blanks were a broken join wearing an honest blank's clothes.

NBA and NCAAB are out of season and WNBA's sprint opens 2026-09-17, so this
counter publishes nothing in production until then. These tests are how it is
known to work before that slate rather than after it.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

pytest.importorskip("pandas")

from syndicate.features.shared.basketball_props_edges import (  # noqa: E402
    _compute_props_edges_file_only_local,
)

ODDS_HEADER = ("snapshot_ts,event_id,commence_time,bookmaker,bookmaker_title,market,"
               "outcome_name,player_name,point,price,home_team,away_team\n")
PRED_HEADER = "player_id,player_name,team,mean_pts,mean_reb,mean_ast,mean_threes,mean_pra,mean_stl,mean_blk,mean_tov\n"


def _odds_row(player):
    return ("2026-09-17T18:00:00Z,evt1,2026-09-17T23:00:00Z,fanduel,FanDuel,"
            f"player_points,Over,{player},19.5,-110,Home Team,Away Team\n")


def _pred_row(pid, player):
    return f"{pid},{player},HOM,21.4,5.1,4.2,2.1,30.7,1.1,0.6,2.2\n"


def _run(tmp_path, odds_players, pred_players, capsys):
    raw = tmp_path / "odds.csv"
    raw.write_text(ODDS_HEADER + "".join(_odds_row(p) for p in odds_players), encoding="utf-8")
    preds = tmp_path / "preds.csv"
    preds.write_text(PRED_HEADER + "".join(_pred_row(i, p) for i, p in enumerate(pred_players, 1)),
                     encoding="utf-8")
    _compute_props_edges_file_only_local(
        source_root=tmp_path, date_str="2026-09-17", raw_path=raw,
        predictions_path=preds, calibrate_prob=False,
    )
    line = [l for l in capsys.readouterr().out.splitlines() if "PROP_NAME_JOIN" in l]
    assert line, "the join emitted no PROP_NAME_JOIN line at all"
    return dict(part.split("=", 1) for part in line[-1].split() if "=" in part)


def test_a_clean_join_reports_zero_unmatched_AND_still_emits(tmp_path, capsys):
    """Emitted even when every count is zero. A line that only appears on
    failure cannot confirm the join ran, which is the whole point."""
    f = _run(tmp_path, ["LeBron James"], ["LeBron James"], capsys)
    assert f["rows_considered"] == "1"
    assert f["unmatched_after_fallback"] == "0"
    assert f["pct_unmatched"] == "0.0"


def test_a_name_the_predictions_never_heard_of_stays_unmatched(tmp_path, capsys):
    f = _run(tmp_path, ["Nobody At All"], ["LeBron James"], capsys)
    assert f["rows_considered"] == "1"
    assert f["unmatched_before_fallback"] == "1"
    assert f["unmatched_after_fallback"] == "1"
    assert f["short_key_recovered"] == "0", "nothing was rescued and it must not claim otherwise"
    assert f["pct_unmatched"] == "100.0"


def test_an_accent_is_NOT_what_the_fallback_is_for(tmp_path, capsys):
    """A guard against testing the wrong thing, kept because I got it wrong.

    My first attempt used "Nikola Jokic" against "Nikola Jokić" as the case only
    the short key could rescue. It is not: `_norm_name` already folds accents
    through NFKD, so the EXACT join matches and the fallback never runs. The
    test failed and the code was right. Asserting it here stops the next reader
    reaching for the same example.
    """
    f = _run(tmp_path, ["Nikola Jokic"], ["Nikola Jokić"], capsys)
    assert f["unmatched_before_fallback"] == "0", "the exact join already folds accents"
    assert f["short_key_recovered"] == "0", "nothing to rescue, and it must not claim one"


def test_the_short_key_fallback_REPORTS_what_it_rescued(tmp_path, capsys):
    """THE DISCRIMINATING CASE, and the one the counter exists for.

    `_short_key` is last name + first initial, so a book that says "Steph Curry"
    against a prediction row that says "Stephen Curry" misses the exact key and
    is recovered by the fallback. Before this counter that rescue and a total
    failure produced the same output: nothing at all.
    """
    f = _run(tmp_path, ["Steph Curry"], ["Stephen Curry"], capsys)
    assert f["unmatched_before_fallback"] == "1", "guard: the exact join must miss here"
    assert f["short_key_recovered"] == "1"
    assert f["unmatched_after_fallback"] == "0"


def test_the_rate_has_the_right_denominator(tmp_path, capsys):
    """Three odds rows, one resolvable. A count without its denominator is a
    count, not a rate -- and the denominator is every row the join considered."""
    f = _run(tmp_path, ["LeBron James", "Nobody At All", "Also Nobody"], ["LeBron James"], capsys)
    assert f["rows_considered"] == "3"
    assert f["unmatched_after_fallback"] == "2"
    assert f["pct_unmatched"] == "66.7"
