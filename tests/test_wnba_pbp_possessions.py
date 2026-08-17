"""Tests for `scripts/wnba_pbp_possessions.py` (`#454`, lane `game-shape-capture`).

Every fixture below is shaped from a REAL record measured on the tracked mirror
2026-08-16, including the two defects the first version of the script had and
the traps in the data itself.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

_SPEC = importlib.util.spec_from_file_location(
    "wnba_pbp_possessions",
    Path(__file__).resolve().parents[1] / "scripts" / "wnba_pbp_possessions.py",
)
mod = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(mod)


def _possessions(**teams: float) -> dict[str, Any]:
    """The measured shape: tricode keys carry data, home/away are ZERO."""
    out: dict[str, Any] = {
        "home": {"dreb": 0, "oreb": 0, "poss_est": 0.0, "tov": 0},
        "away": {"dreb": 0, "oreb": 0, "poss_est": 0.0, "tov": 0},
        "UNKNOWN": {"dreb": 0, "oreb": 0, "poss_est": 0.0, "tov": 0},
        "total": {"dreb": 45, "oreb": 14, "poss_est": sum(teams.values()), "tov": 23},
    }
    for tri, poss in teams.items():
        out[tri] = {"dreb": 20, "oreb": 7, "poss_est": poss, "tov": 11}
    return out


def _quarters(*, q1=38, q2=44, q3=45, q4=36, period=4) -> dict[str, Any]:
    return {"current": {"period": period, "q_total": q4},
            "q_totals": {"q1": q1, "q2": q2, "q3": q3, "q4": q4}}


def _game(game_id="PHX@TOR", *, teams=None, quarters=None) -> dict[str, Any]:
    return {
        "game_id": game_id,
        "pbp_possessions": _possessions(**(teams or {"PHX": 73.0, "TOR": 73.04})),
        "pbp_quarters": quarters if quarters is not None else _quarters(),
    }


# --------------------------------------------------------------------------
# Trap 1 -- home/away are zero, the real data is tricode-keyed
# --------------------------------------------------------------------------


def test_team_possessions_ignores_the_zero_valued_home_and_away_keys():
    """Measured: 17 of 17 populated records have `poss_est == 0.0` under both.

    A reader that goes straight to `home`/`away` gets a plausible-looking zero
    rather than an obvious miss.
    """
    teams = mod.team_possessions(_possessions(PHX=73.0, TOR=73.04))
    assert set(teams) == {"PHX", "TOR"}
    assert teams["PHX"]["poss_est"] == 73.0
    for dropped in ("home", "away", "total", "unknown", "UNKNOWN"):
        assert dropped not in teams


def test_the_key_filter_is_load_bearing_independently_of_the_zero_filter():
    """The test above passes for the WRONG REASON and this one exists to fix that.

    Caught by mutation: removing `home`/`away` from `_NON_TEAM_KEYS` changed
    nothing, because the `poss_est <= 0` filter already drops them on real data.
    So that test pinned the zero filter, not the key filter, and the key filter
    could have been deleted silently.

    The case that separates them is a record where `home`/`away` carry NON-zero
    values alongside the tricodes -- which is what the producer would emit if it
    ever populated both. Including them would DOUBLE COUNT: `total_possessions`
    would be the sum of four entries for a two-team game.
    """
    poss = _possessions(PHX=73.0, TOR=73.04)
    poss["home"] = {"dreb": 20, "oreb": 7, "poss_est": 73.04, "tov": 11}
    poss["away"] = {"dreb": 20, "oreb": 7, "poss_est": 73.0, "tov": 11}
    teams = mod.team_possessions(poss)
    assert set(teams) == {"PHX", "TOR"}, (
        "home/away must be excluded BY KEY, not merely by being zero"
    )
    # And the row built from it must still be a two-team game.
    row = mod.game_row(
        {"game_id": "PHX@TOR", "pbp_possessions": poss, "pbp_quarters": _quarters()},
        date="2026-06-27",
    )
    assert row is not None
    assert row["total_possessions"] == 146.04


def test_zero_possession_blocks_are_dropped_rather_than_kept_as_zero():
    teams = mod.team_possessions(_possessions(PHX=0.0, TOR=73.0))
    assert set(teams) == {"TOR"}


def test_team_possessions_never_raises_on_junk():
    for bad in (None, {}, "", 0, [], {"PHX": "banana"}):
        assert mod.team_possessions(bad) == {} or isinstance(mod.team_possessions(bad), dict)


# --------------------------------------------------------------------------
# Trap 2 -- placeholder ids
# --------------------------------------------------------------------------


def test_placeholder_game_ids_are_recognised():
    for placeholder in ("0000000001", "0000000004", "1", "", None):
        assert mod._is_placeholder_game_id(placeholder) is True
    for real in ("SEA@TOR", "PHX@TOR", "401856947"):
        assert mod._is_placeholder_game_id(real) is False


# --------------------------------------------------------------------------
# The defect the first version shipped: partial games counted as complete
# --------------------------------------------------------------------------


def test_quarters_complete_requires_all_four():
    """The bug this pins produced a `pace_per_team` of 2.5 next to real games."""
    assert mod.quarters_complete(_quarters()) is True
    assert mod.quarters_complete(_quarters(q4=None, period=3)) is False
    assert mod.quarters_complete(_quarters(q3=None, q4=None, period=2)) is False
    assert mod.quarters_complete(_quarters(q2=None, q3=None, q4=None, period=1)) is False
    for bad in (None, {}, {"q_totals": None}, "banana"):
        assert mod.quarters_complete(bad) is False


def test_game_row_annotates_instead_of_filtering():
    """`scan` must be able to COUNT each exclusion, not receive a silent drop."""
    partial = mod.game_row(_game(quarters=_quarters(q4=None, period=3)), date="2026-06-27")
    assert partial is not None
    assert partial["complete"] is False
    assert partial["period"] == 3
    fake = mod.game_row(_game("0000000001"), date="")
    assert fake is not None and fake["placeholder"] is True


def test_game_row_refuses_a_record_that_is_not_two_teams():
    one = {"game_id": "X@Y", "pbp_possessions": _possessions(PHX=70.0), "pbp_quarters": _quarters()}
    assert mod.game_row(one, date="") is None
    three = {"game_id": "X@Y",
             "pbp_possessions": _possessions(PHX=70.0, TOR=70.0, SEA=70.0),
             "pbp_quarters": _quarters()}
    assert mod.game_row(three, date="") is None


def test_pace_is_possessions_per_team():
    row = mod.game_row(_game(teams={"PHX": 73.0, "TOR": 73.04}), date="2026-06-27")
    assert row["total_possessions"] == 146.04
    assert row["pace_per_team"] == 73.02


# --------------------------------------------------------------------------
# The floor -- the whole point of the tool
# --------------------------------------------------------------------------


def test_summarise_refuses_below_the_floor_and_names_the_shortfall():
    rows = [{"pace_per_team": 75.0} for _ in range(4)]
    out = mod.summarise(rows, min_games=10)
    assert out["status"] == "refused"
    assert out["reason"] == "insufficient_sample"
    assert out["n"] == 4 and out["shortfall"] == 6
    # A refusal must not smuggle a number out anyway.
    for numeric in ("mean_pace_per_team", "median_pace_per_team"):
        assert numeric not in out


def test_summarise_computes_once_the_floor_is_cleared():
    rows = [{"pace_per_team": p} for p in (70.0, 75.0, 80.0)]
    out = mod.summarise(rows, min_games=3)
    assert out["status"] == "ok"
    assert out["n"] == 3
    assert out["mean_pace_per_team"] == 75.0
    assert out["median_pace_per_team"] == 75.0
    assert out["min_pace"] == 70.0 and out["max_pace"] == 80.0


def test_median_is_a_real_median_on_an_even_sample():
    rows = [{"pace_per_team": p} for p in (70.0, 74.0, 76.0, 80.0)]
    out = mod.summarise(rows, min_games=1)
    assert out["median_pace_per_team"] == 75.0


# --------------------------------------------------------------------------
# Deduplication -- the snapshots are periodic
# --------------------------------------------------------------------------


def test_scan_collapses_repeated_snapshots_of_the_same_game(tmp_path):
    """Measured: SEA@TOR appeared twice with byte-identical totals.

    Counting a periodic snapshot twice inflates exactly the denominator this
    tool exists to state honestly.
    """
    import json

    root = tmp_path / "wnba_source"
    root.mkdir()
    early = _game("PHX@TOR", teams={"PHX": 40.0, "TOR": 41.0})
    late = _game("PHX@TOR", teams={"PHX": 73.0, "TOR": 73.04})
    for name, game in (("live_pbp_stats_2026-06-27.jsonl", early),
                       ("live_pbp_stats_2026-06-27b.jsonl", late)):
        (root / name).write_text(
            json.dumps({"payload": {"date": "2026-06-27", "games": [game]}}) + "\n",
            encoding="utf-8",
        )
    result = mod.scan([root])
    assert result["coverage"]["usable_games"] == 1
    assert result["coverage"]["duplicate_snapshots_collapsed"] == 1
    # The LATER snapshot wins -- possessions only accrue.
    assert result["rows"][0]["total_possessions"] == 146.04


def test_scan_counts_every_exclusion_reason(tmp_path):
    """A coverage tool that hides why it dropped a record reads as full coverage."""
    import json

    root = tmp_path / "wnba_source"
    root.mkdir()
    games = [
        _game("PHX@TOR"),                                            # usable
        _game("0000000001"),                                         # placeholder
        _game("CHI@DAL", quarters=_quarters(q2=None, q3=None, q4=None, period=1)),  # partial
    ]
    (root / "live_pbp_stats_2026-06-27.jsonl").write_text(
        json.dumps({"payload": {"date": "2026-06-27", "games": games}}) + "\n", encoding="utf-8"
    )
    cov = mod.scan([root])["coverage"]
    assert cov["game_records"] == 3
    assert cov["with_possessions"] == 3
    assert cov["placeholder_excluded"] == 1
    assert cov["partial_excluded"] == 1
    assert cov["usable_games"] == 1
    # The trap is reported as a NUMBER, not left silent.
    assert cov["home_away_keys_zero"] == 3


def test_scan_on_a_missing_root_returns_zero_rather_than_raising(tmp_path):
    result = mod.scan([tmp_path / "does-not-exist"])
    assert result["coverage"]["usable_games"] == 0
    assert result["rows"] == []
