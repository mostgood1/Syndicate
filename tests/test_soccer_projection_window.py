"""The projection read is the WINDOW, not one date -- the second half of `#379`.

`#379` widened Layer 2's QUOTE read from `selected_date` to the sport's whole
slate window, because soccer shards by KICKOFF date and almost nothing kicks off
"today". The projection read sitting beside it was never widened, so the board
held seven days of quotes and asked for one day of projections.

MEASURED ON PRODUCTION 2026-08-17 19:5xZ, soccer's own `per_sport_ingest`:

    window_dates          7   (08-17 .. 08-23)
    dates_with_rows       6   (08-17, 08-19, 08-20, 08-21, 08-22, 08-23)
    grid_rows             8,759
    rows_with_projection  4      (pct_projected 0.0)
    matches_in_source     3
    unmatched_match_rows  8,755

and downstream `rows_with_model_edge: 0`, soccer absent from `per_sport`, 0 rows
served out of 5,527 opportunities. This is not a cosmetic gap: the A3 filter
drops a row whose `ev_pct` merely restates the book's hold UNLESS it carries a
projection, so the one-date read is what kept soccer off the board entirely.

The three matches that did load were today's and all three were in play, so
their pregame projections were correctly withheld. Today was never the problem.

THE HAZARD THE WIDENING CREATES, and why half this file is about it: the sim
feed (ESPN) and the board feed (OddsAPI) use different event-id schemes, which
`SoccerProjectionIndex.match_for` documents -- `by_event` "can never hit across
these two feeds". So the join is in practice keyed on TEAM NAMES. Within one
date that is safe, because a club plays once. Across seven days it is not.
"""

from __future__ import annotations

import json
from pathlib import Path

from syndicate.features.shared.soccer_projections import load_soccer_projections

WINDOW = [
    "2026-08-17", "2026-08-18", "2026-08-19", "2026-08-20",
    "2026-08-21", "2026-08-22", "2026-08-23",
]


def _write(
    root: Path,
    league: str,
    date: str,
    *,
    home: str = "Getafe",
    away: str = "Alaves",
    event_id: str | None = None,
    generated_at: str = "2026-08-17T19:10:00",
) -> None:
    path = root / league / "api" / "recommendations" / f"recommendations_{date}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "league": league,
                "date": date,
                "generated_at": generated_at,
                "matches": [
                    {
                        "event_id": event_id or f"{league}-{date}-1",
                        "date": date,
                        "kickoff": f"{date}T19:00Z",
                        "matchup": {"home_team": home, "away_team": away},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


class TestTheWidening:
    def test_dates_beyond_today_are_now_read(self, tmp_path):
        # The production shape: nothing on the selected date, fixtures later in
        # the window. Before this change the index came back empty.
        _write(tmp_path, "la_liga", "2026-08-22", home="Real Sociedad", away="Betis")
        _write(tmp_path, "epl", "2026-08-21", home="Arsenal", away="Coventry City")

        one_date = load_soccer_projections([tmp_path], "2026-08-17")
        assert one_date.matches == 0, "precondition: the old behaviour finds nothing"

        windowed = load_soccer_projections([tmp_path], "2026-08-17", window_dates=WINDOW)
        assert windowed.matches == 2
        assert sorted(windowed.leagues) == ["epl", "la_liga"]

    def test_a_row_on_a_later_date_now_finds_its_projection(self, tmp_path):
        # The behaviour that actually matters, expressed as the join the board
        # performs rather than as a file count.
        _write(tmp_path, "epl", "2026-08-21", home="Arsenal", away="Coventry City")
        index = load_soccer_projections([tmp_path], "2026-08-17", window_dates=WINDOW)
        row = {"home_team": "Arsenal", "away_team": "Coventry City"}
        assert index.match_for(row) is not None

    def test_the_window_is_recorded_so_a_zero_is_attributable(self, tmp_path):
        # "Zero against one date" and "zero against seven" are different facts.
        index = load_soccer_projections([tmp_path], "2026-08-17", window_dates=WINDOW)
        assert index.dates == WINDOW
        assert index.matches == 0


class TestItIsANoOpForEveryExistingCaller:
    def test_omitting_the_window_reads_exactly_one_date(self, tmp_path):
        _write(tmp_path, "epl", "2026-08-17", home="Arsenal", away="Coventry City")
        _write(tmp_path, "epl", "2026-08-21", home="Chelsea", away="Fulham")
        index = load_soccer_projections([tmp_path], "2026-08-17")
        assert index.matches == 1
        assert index.dates == ["2026-08-17"]
        assert index.match_for({"home_team": "Chelsea", "away_team": "Fulham"}) is None

    def test_an_empty_window_falls_back_rather_than_reading_nothing(self, tmp_path):
        # A resolver that returns [] must degrade to the old behaviour, never
        # silently empty the read.
        _write(tmp_path, "epl", "2026-08-17", home="Arsenal", away="Coventry City")
        index = load_soccer_projections([tmp_path], "2026-08-17", window_dates=[])
        assert index.matches == 1


class TestFirstRootWinsIsNowPerLeagueDate:
    """`#360`'s precedence must survive the widening, and not swallow it."""

    def test_the_fresh_runtime_disk_still_beats_the_stale_mirror(self, tmp_path):
        runtime, mirror = tmp_path / "runtime", tmp_path / "mirror"
        _write(runtime, "la_liga", "2026-08-22", generated_at="2026-08-17T21:54:14")
        _write(mirror, "la_liga", "2026-08-22", generated_at="2026-07-20T21:32:50")
        index = load_soccer_projections([runtime, mirror], "2026-08-17", window_dates=WINDOW)
        assert index.generated_at_by_league["la_liga"] == "2026-08-17T21:54:14"

    def test_claiming_a_league_on_one_date_does_not_suppress_its_other_dates(self, tmp_path):
        # THE BUG A LEAGUE-KEYED CLAIM WOULD CAUSE: the first date read claims
        # `la_liga`, every later date's file is skipped, and the widening is a
        # no-op that still reports seven dates. Keying the claim on
        # (league, date) is what prevents it.
        _write(tmp_path, "la_liga", "2026-08-17", home="Elche", away="Deportivo")
        _write(tmp_path, "la_liga", "2026-08-22", home="Real Sociedad", away="Betis")
        index = load_soccer_projections([tmp_path], "2026-08-17", window_dates=WINDOW)
        assert index.matches == 2, "a later date in the same league was suppressed"
        assert index.match_for({"home_team": "Real Sociedad", "away_team": "Betis"}) is not None


class TestOneTeamPairCannotMeanTwoFixtures:
    """A wrong projection is far worse than a blank one."""

    def test_the_same_clubs_on_two_dates_join_to_neither(self, tmp_path):
        # A midweek cup tie and a weekend league game between the same clubs.
        # `by_teams` is a plain write, so without this the later file would win
        # and a row for the earlier fixture would be priced against the wrong
        # simulation -- silently, with a real number next to the wrong bet.
        _write(tmp_path, "epl", "2026-08-19", home="Arsenal", away="Chelsea", event_id="cup-1")
        _write(tmp_path, "epl", "2026-08-22", home="Arsenal", away="Chelsea", event_id="league-1")
        index = load_soccer_projections([tmp_path], "2026-08-17", window_dates=WINDOW)

        assert index.match_for({"home_team": "Arsenal", "away_team": "Chelsea"}) is None
        assert ("arsenal", "chelsea") in index.ambiguous_team_keys
        # Both fixtures were still counted and are still reachable by event id --
        # the ambiguity is in the NAME key, not in the data.
        assert index.matches == 2
        assert "cup-1" in index.by_event and "league-1" in index.by_event

    def test_ambiguity_does_not_leak_through_the_alias_fallback(self, tmp_path):
        # The fuzzy `teams_match` path walks `by_teams` directly, so it needs its
        # own guard -- removing the exact key is not enough on its own.
        _write(tmp_path, "epl", "2026-08-19", home="Arsenal FC", away="Chelsea", event_id="cup-1")
        _write(tmp_path, "epl", "2026-08-22", home="Arsenal FC", away="Chelsea", event_id="league-1")
        index = load_soccer_projections([tmp_path], "2026-08-17", window_dates=WINDOW)
        assert index.match_for({"home_team": "Arsenal", "away_team": "Chelsea"}) is None

    def test_one_fixture_read_twice_is_not_ambiguous(self, tmp_path):
        # Two roots carrying the same league-date is normal and must NOT blank a
        # good key. Only a genuine second FIXTURE does.
        runtime, mirror = tmp_path / "runtime", tmp_path / "mirror"
        _write(runtime, "epl", "2026-08-21", home="Arsenal", away="Chelsea", event_id="evt-1")
        _write(mirror, "epl", "2026-08-21", home="Arsenal", away="Chelsea", event_id="evt-1")
        index = load_soccer_projections([runtime, mirror], "2026-08-17", window_dates=WINDOW)
        assert index.ambiguous_team_keys == set()
        assert index.match_for({"home_team": "Arsenal", "away_team": "Chelsea"}) is not None

    def test_a_repeat_fixture_cannot_be_resurrected_by_a_third_file(self, tmp_path):
        # Once poisoned, a key stays poisoned: a later write must not quietly
        # re-seat one of the two fixtures under the ambiguous name.
        _write(tmp_path, "epl", "2026-08-19", home="Arsenal", away="Chelsea", event_id="a")
        _write(tmp_path, "epl", "2026-08-21", home="Arsenal", away="Chelsea", event_id="b")
        _write(tmp_path, "epl", "2026-08-23", home="Arsenal", away="Chelsea", event_id="c")
        index = load_soccer_projections([tmp_path], "2026-08-17", window_dates=WINDOW)
        assert index.match_for({"home_team": "Arsenal", "away_team": "Chelsea"}) is None


def test_the_production_caller_actually_passes_a_multi_date_window():
    """THE FIX MUST REACH PRODUCTION, which is how it failed the first time.

    `load_soccer_projections` gained `window_dates` and defaults to
    `[selected_date]` "so every existing caller behaves exactly as before" --
    and the only production caller never passed one. The merge logic, its cost
    analysis and its documentation all shipped while production read one date:
    8,759 grid rows, `rows_with_projection: 4`, `unmatched_match_rows: 8,755`
    (measured 2026-08-17).

    THIS TEST PINS THE CALL SITE, NOT THE FUNCTION. A test of the merge alone
    passes happily while the caller ignores it -- that is precisely the state
    this repairs.

    It also pins `window="slate"` specifically. The resolver DEFAULTS to
    `window="day"`, which returns a single date, so a bare
    `resolve_window_dates("soccer", selected_date)` would leave the fix exactly
    as inert as the bug. I made that mistake writing it and caught it by
    reading the returned value.
    """
    import inspect

    from syndicate.features.shared import board_enrichment
    from syndicate.features.shared.layer1_board import resolve_window_dates

    src = inspect.getsource(board_enrichment)
    assert "window_dates=soccer_window" in src, (
        "the soccer projection load must pass a window; without it #379 is inert"
    )
    assert 'resolve_window_dates("soccer", selected_date, window="slate")' in src, (
        'the window must be "slate" -- the resolver defaults to "day", which is one date'
    )

    # And the window that call produces must genuinely span more than a day.
    window = resolve_window_dates("soccer", "2026-08-17", window="slate")
    assert len(window) > 1, "a one-date window is the defect, not the fix"
    assert window[0] == "2026-08-17"


def test_the_soccer_window_matches_the_quote_read_it_accompanies():
    """Two independent notions of "which dates is this sport's board" would
    drift, and that drift IS the defect -- so the projection read must use the
    same resolver and span as the quote read, not a hand-rolled number."""
    from syndicate.features.shared.layer1_board import resolve_window_dates, slate_window_days

    assert len(resolve_window_dates("soccer", "2026-08-17", window="slate")) == slate_window_days("soccer")
