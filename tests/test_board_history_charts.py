"""Dated per-game history on the Layer 2 prop charts (lane board-history-charts, 2026-10-09).

The board's prop chart drew bare values: `recent_values` only, no dates or opponents. These pin
that the per-game labels travel with the values from the evidence layer to the card, stay aligned
with them, and are dropped rather than mislabelled when they are not aligned.
"""

from syndicate.features import intelligence_recent_matchup as rm
from syndicate.features.shared.layer2_board import _chart_columns


def _row(**kw):
    row = {"kind": "prop", "sport": "soccer", "player_name": "Test Player", "market": "player_shots",
           "line": 1.5, "side": "over", "home_team": "A", "away_team": "B"}
    row.update(kw)
    return row


def setup_function(_fn):
    rm.RECENT_VALUES.clear()


def test_labels_reach_the_card_aligned_with_values():
    """REACHABILITY: what the evidence layer records is what `_chart_columns` emits."""
    row = _row()
    rm._record_values(row, [3, 1, 2], ["2026-10-04", "2026-09-27", "2026-09-20"], ["v Arsenal", "@ Spurs", "v Wolves"])
    out = _chart_columns(row)
    assert out["recent_values"] == [3.0, 1.0, 2.0]
    assert out["recent_dates"] == ["2026-10-04", "2026-09-27", "2026-09-20"]
    assert out["recent_opponents"] == ["v Arsenal", "@ Spurs", "v Wolves"]


def test_a_missing_value_drops_its_label_too():
    """A None value used to be dropped AFTER the fact, so one game with no stat cost the row all its dates."""
    row = _row()
    rm._record_values(row, [3, None, 2], ["d1", "d2", "d3"], ["o1", "o2", "o3"])
    out = _chart_columns(row)
    assert out["recent_values"] == [3.0, 2.0]
    assert out["recent_dates"] == ["d1", "d3"]
    assert out["recent_opponents"] == ["o1", "o3"]


def test_misaligned_labels_are_not_used():
    row = _row()
    rm._record_values(row, [3, 1, 2], ["only-one"], None)
    out = _chart_columns(row)
    assert out["recent_values"] == [3.0, 1.0, 2.0]
    assert "recent_dates" not in out and "recent_opponents" not in out


def test_values_only_callers_are_unchanged():
    """MLB's path and any caller without labels still produce the bare values, as before."""
    row = _row(sport="nhl")
    rm._record_values(row, [1, 0, 2])
    out = _chart_columns(row)
    assert out["recent_values"] == [1.0, 0.0, 2.0]
    assert "recent_dates" not in out


def _roster(monkeypatch, rows):
    from syndicate.features.shared.prop_evidence import football as fb

    monkeypatch.setattr(fb.C, "first_existing", lambda *a, **k: "roster.csv")
    monkeypatch.setattr(fb, "_read_csv", lambda path, label: rows)
    return fb


def _subject(name):
    from types import SimpleNamespace

    return SimpleNamespace(player_name=name)


def test_nfl_roster_fallback_resolves_a_player_the_projections_omit(monkeypatch):
    """2026-10-09: 29 NFL prop players (Justin Jefferson, Jayden Daniels, ...) had no chart because the id
    lookup read only the projections file; their game lines are keyed by gsis id in the usage file."""
    fb = _roster(monkeypatch, [
        {"gsis_id": "00-0036322", "full_name": "Justin Jefferson", "team": "MIN", "position": "WR"},
        {"gsis_id": "00-0036415", "full_name": "Van Jefferson", "team": "TEN", "position": "WR"},
    ])
    p = fb._nfl_roster_player(2026, _subject("Justin Jefferson"), None)
    assert p is not None and p.id == "00-0036322" and p.index == -1 and p.basis == {}


def test_nfl_roster_fallback_refuses_an_ambiguous_name(monkeypatch):
    fb = _roster(monkeypatch, [
        {"gsis_id": "A", "full_name": "Chris Bell", "team": "LV", "position": "WR"},
        {"gsis_id": "B", "full_name": "Chris Bell", "team": "BUF", "position": "WR"},
    ])
    assert fb._nfl_roster_player(2026, _subject("Chris Bell"), None) is None


def test_nfl_name_miss_is_not_reported_as_a_missing_file():
    from types import SimpleNamespace

    from syndicate.features.shared.prop_evidence import football as fb

    subject = SimpleNamespace(player_name="Nobody Known", market="Receiving Yards")
    layer = fb._nfl_recent_form(subject, "rec_yards", "Receiving yards", None, ([], None, []), 2026)
    why = str(layer.absent_reason)
    assert "no gsis id" in why, why
    assert "not on this disk" not in why


def test_capped_at_ten_and_kept_in_step():
    row = _row()
    vals = list(range(14))
    labels = [f"g{i}" for i in range(14)]
    rm._record_values(row, vals, labels, labels)
    out = _chart_columns(row)
    assert len(out["recent_values"]) == 10
    assert out["recent_dates"] == labels[:10]
