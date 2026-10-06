"""The window merge must not SUM a coverage half's identity fields or rates.

WHY `[lane layer2-coverage-identity-merge, 2026-10-06]`. Read on the fleet
2026-10-06 19:00Z, `/api/board/layer2-shortlist` served NFL
`prop_coverage.artifact_week = 35`, `artifact_season = 14182`,
`artifact_rows = 3661` and `pct_projected = 490.7` -- while the single-date
book-grid for any date in the same 7-date window read week 5, season 2026,
523 rows. `_attach_projections_over_window` summed EVERY numeric sub-key of
the nested halves, so "which artifact answered" became "7 x the artifact" and a
percentage became a sum of percentages. NCAAF's prop half read 186.8%.

The NFL half of it also had a second cause: NFL's joins never read the date,
so the window ran seven identical passes. NFL now joins once.
"""
from __future__ import annotations

import pipeline.layer2_shortlist as ls


def _run(per_date_coverage, sport="ncaaf"):
    """Drive the real merge with a stubbed per-date `attach_projections`."""
    dates = list(per_date_coverage)
    calls: list[str] = []

    def fake_attach(grid, *, sport, selected_date):  # noqa: ARG001
        calls.append(selected_date)
        return per_date_coverage[selected_date]

    import syndicate.features.shared.board_enrichment as be
    original = be.attach_projections
    be.attach_projections = fake_attach
    try:
        out = ls._attach_projections_over_window(
            [], sport=sport, selected_date=dates[0], window_dates=dates)
    finally:
        be.attach_projections = original
    return out, calls


def _nfl_prop_half(considered, projected, *, week=5):
    return {
        "supported": True,
        "rows_considered": considered,
        "rows_with_projection": projected,
        "artifact_season": 2026,
        "artifact_week": week,
        "artifact_rows": 523,
        "pct_projected": round(100.0 * projected / considered, 1),
    }


def test_two_dates_same_week_serve_week_5_not_10():
    merged, calls = _run({
        "2026-10-08": {"prop_coverage": _nfl_prop_half(106, 67)},
        "2026-10-11": {"prop_coverage": _nfl_prop_half(575, 420)},
    })
    assert len(calls) == 2                       # the merge really ran twice
    half = merged["prop_coverage"]
    assert half["artifact_week"] == 5            # not 10
    assert half["artifact_season"] == 2026       # not 4052
    assert half["artifact_rows"] == 523          # not 1046
    # Counts still sum, and the rate is re-derived from them -- not 63.2 + 73.0.
    assert half["rows_considered"] == 681
    assert half["rows_with_projection"] == 487
    assert half["pct_projected"] == round(100.0 * 487 / 681, 1)
    assert half["supported"] is True


def test_distinct_weeks_become_a_sorted_list_and_stay_per_date():
    merged, _ = _run({
        "2026-10-12": {"prop_coverage": _nfl_prop_half(100, 50, week=6)},
        "2026-10-08": {"prop_coverage": _nfl_prop_half(100, 50, week=5)},
    })
    assert merged["prop_coverage"]["artifact_week"] == [5, 6]
    assert merged["prop_coverage"]["artifact_season"] == 2026
    assert merged["per_date"]["2026-10-08"]["prop_coverage"]["artifact_week"] == 5
    assert merged["per_date"]["2026-10-12"]["prop_coverage"]["artifact_week"] == 6


def test_index_size_is_identity_and_string_identity_survives():
    """NHL's game half carries `artifact_date` and `games_in_artifact`."""
    merged, _ = _run({
        "2026-10-06": {"game_coverage": {"artifact_date": "2026-10-06", "games_in_artifact": 9,
                                         "games_in_index": 321}},
        "2026-10-07": {"game_coverage": {"artifact_date": "2026-10-07", "games_in_artifact": 9,
                                         "games_in_index": 321}},
    })
    half = merged["game_coverage"]
    assert half["artifact_date"] == ["2026-10-06", "2026-10-07"]
    assert half["games_in_artifact"] == 9
    assert half["games_in_index"] == 321         # not 642


def test_tally_dict_sums_per_key_instead_of_first_wins():
    """NCAAF's `artifact_weeks` is a per-week ROW tally, not an identity."""
    merged, _ = _run({
        "2026-10-09": {"prop_coverage": {"rows_considered": 90, "rows_with_projection": 28,
                                         "artifact_weeks": {"2026_wk6": 28}, "pct_projected": 31.1}},
        "2026-10-10": {"prop_coverage": {"rows_considered": 160, "rows_with_projection": 73,
                                         "artifact_weeks": {"2026_wk6": 73}, "pct_projected": 45.6}},
    })
    half = merged["prop_coverage"]
    assert half["artifact_weeks"] == {"2026_wk6": 101}
    assert half["pct_projected"] == round(100.0 * 101 / 250, 1)   # not 76.7


def test_underivable_half_rate_is_dropped_not_summed():
    merged, _ = _run({
        "2026-10-09": {"prop_coverage": {"pct_two_sided": 40.0}},
        "2026-10-10": {"prop_coverage": {"pct_two_sided": 50.0}},
    })
    assert "pct_two_sided" not in merged["prop_coverage"]


def test_nfl_joins_once_because_its_joins_are_date_blind():
    merged, calls = _run({
        "2026-10-06": {"rows_considered": 733, "prop_coverage": _nfl_prop_half(733, 514)},
        "2026-10-07": {"rows_considered": 733, "prop_coverage": _nfl_prop_half(733, 514)},
        "2026-10-08": {"rows_considered": 733, "prop_coverage": _nfl_prop_half(733, 514)},
    }, sport="nfl")
    assert calls == ["2026-10-06"]
    assert merged["rows_considered"] == 733      # not 2199
    assert merged["prop_coverage"]["artifact_week"] == 5
