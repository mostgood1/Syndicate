"""Team ratings must not be built from matches that had not happened yet.

Lane `soccer-backtest-leakage`, audit §7 ranked fix #6.

`compute_team_ratings` had no notion of time, and
`backtest_soccer_live_lens.run_backtest` computed it ONCE per league then
applied it to every match inside that season -- so a March match was scored
using ratings built partly from May results. Every number in
`data/soccer_source/*/validation/*_backtest_*.csv` was produced that way.
"""

from __future__ import annotations

import pathlib

import pytest

from syndicate.features.soccer.features.loaders import compute_team_ratings


def _row(team: str, date: str, xg_for: float, xg_against: float) -> dict:
    return {"team": team, "date": date, "xg_for": xg_for, "xg_against": xg_against}


def _history() -> list[dict]:
    return [
        _row("Arsenal", "2026-03-01 15:00:00", 0.5, 2.0),   # bad, early
        _row("Arsenal", "2026-03-08 15:00:00", 0.5, 2.0),
        _row("Arsenal", "2026-05-01 15:00:00", 3.5, 0.2),   # good, LATE
        _row("Arsenal", "2026-05-08 15:00:00", 3.5, 0.2),
        _row("Spurs", "2026-03-01 15:00:00", 1.4, 1.4),
        _row("Spurs", "2026-05-01 15:00:00", 1.4, 1.4),
    ]


def test_as_of_is_required():
    """A default would silently pick the wrong behaviour for two of the three
    call sites, which is how the leak survived."""
    with pytest.raises(TypeError):
        compute_team_ratings(_history())  # type: ignore[call-arg]


def test_an_empty_as_of_is_refused_not_treated_as_no_filter():
    with pytest.raises(ValueError):
        compute_team_ratings(_history(), as_of="")


def test_may_results_do_not_reach_a_march_rating():
    """The leak itself, in one assertion."""
    march = compute_team_ratings(_history(), as_of="2026-03-15")
    assert march["Arsenal"]["matches"] == 2.0, "a March rating saw more than the two March matches"
    assert march["Arsenal"]["xg_for_per_match"] == pytest.approx(0.5)

    season = compute_team_ratings(_history(), as_of="2026-06-01")
    assert season["Arsenal"]["matches"] == 4.0
    assert season["Arsenal"]["xg_for_per_match"] == pytest.approx(2.0)

    assert march["Arsenal"]["attack_rating"] < season["Arsenal"]["attack_rating"], (
        "the March rating already carried the May improvement -- this is the leak"
    )


def test_a_match_cannot_inform_its_own_prediction():
    """Strictly before, by calendar day. Kickoff times within a day are not
    reliably ordered across these sources, so same-day is excluded too."""
    same_day = compute_team_ratings(_history(), as_of="2026-03-01")
    assert "Arsenal" not in same_day, "the 2026-03-01 match fed its own rating"


def test_a_row_with_no_date_is_dropped_not_admitted():
    rows = _history() + [_row("Arsenal", "", 9.9, 0.0)]
    ratings = compute_team_ratings(rows, as_of="2026-06-01")
    assert ratings["Arsenal"]["matches"] == 4.0, "an undated row was admitted"
    assert ratings["Arsenal"]["xg_for_per_match"] == pytest.approx(2.0)


def test_the_window_applies_after_the_as_of_filter():
    """Filter first, then take the last N. The other order would let the window
    select future matches and then hide that it had."""
    ratings = compute_team_ratings(_history(), as_of="2026-06-01", window=2)
    assert ratings["Arsenal"]["matches"] == 2.0
    # The last TWO matches before the cutoff are the May pair.
    assert ratings["Arsenal"]["xg_for_per_match"] == pytest.approx(3.5)


def test_unsorted_input_still_selects_the_most_recent_window():
    """`window` takes the LAST N, so ordering is load-bearing and was only ever
    an assumption in a docstring."""
    rows = list(reversed(_history()))
    ratings = compute_team_ratings(rows, as_of="2026-06-01", window=2)
    assert ratings["Arsenal"]["xg_for_per_match"] == pytest.approx(3.5)


def test_a_team_with_no_prior_matches_is_absent_rather_than_neutral():
    ratings = compute_team_ratings(_history(), as_of="2026-01-01")
    assert ratings == {}


def test_the_backtest_derives_ratings_per_match_not_once():
    """The call-site half. A correct `compute_team_ratings` still leaks if the
    caller hoists it out of the loop, which is exactly what happened."""
    import inspect

    import scripts.backtest_soccer_live_lens as mod

    source = inspect.getsource(mod.run_backtest)
    assert "_ratings_as_of(" in source, "run_backtest no longer derives ratings per match"
    body = source.split("for event in completed:", 1)
    assert len(body) == 2, "the match loop moved; re-check that ratings are still inside it"
    assert "_ratings_as_of(" in body[1], "ratings are computed OUTSIDE the match loop -- the leak is back"


def test_the_production_builder_passes_the_date_it_is_building_for():
    import inspect

    import scripts.build_soccer_artifacts as mod

    assert "as_of" in inspect.signature(mod._load_team_ratings).parameters


def _load_team_ratings_call_census() -> list[tuple[str, int, int, int]]:
    """Every `_load_team_ratings` call in the repo, with the arity it must have.

    Returns `(relative_path, lineno, positional_args_passed, args_required)`.

    Resolution rule, matching Python's own: a module-local `def` wins; otherwise
    the call binds to whatever `from ... import _load_team_ratings` brought in.
    There are TWO distinct functions with this name and DIFFERENT arities --
    `build_soccer_artifacts._load_team_ratings(league, source_root, as_of)` (3)
    and `validate_soccer_vs_market._load_team_ratings(league, as_of)` (2) -- so
    a census that assumed one arity would be wrong about half the call sites.
    """
    import ast

    repo_root = pathlib.Path(__file__).resolve().parents[1]
    # `.claude/worktrees/` holds stale COPIES of these same scripts from other
    # sessions, still carrying the pre-`as_of` two-arg signature. They are not
    # this repo's code and asserting on them would make this test fail for
    # reasons that have nothing to do with the tree under test.
    skip = {".claude", ".venv", ".venv-1", "vendor", "node_modules", ".git", "data", "reports"}

    definitions: dict[str, int] = {}
    sources: dict[str, tuple[str, ast.Module]] = {}
    for path in sorted(repo_root.rglob("*.py")):
        if any(part in skip for part in path.relative_to(repo_root).parts):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        rel = path.relative_to(repo_root).as_posix()
        sources[rel] = (rel, tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_load_team_ratings":
                required = len(node.args.args) - len(node.args.defaults)
                definitions[rel] = required

    census: list[tuple[str, int, int, int]] = []
    for rel, (_, tree) in sources.items():
        imported_from = None
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name == "_load_team_ratings":
                        imported_from = (node.module or "").replace(".", "/") + ".py"
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if name != "_load_team_ratings":
                continue
            if rel in definitions:
                required = definitions[rel]
            elif imported_from and imported_from in definitions:
                required = definitions[imported_from]
            else:
                continue
            census.append((rel, node.lineno, len(node.args) + len(node.keywords), required))
    return census


def test_every_caller_passes_as_of():
    """A CALLER CENSUS, because the spot-check version of this test was green
    through a total production outage.

    What stood here asserted one literal string -- the call site inside
    `build_soccer_artifacts` -- and nothing else. When `_load_team_ratings`
    gained its third parameter, that one caller was updated and FOUR others
    were not. The test passed the whole time.

    The cost, measured on production 2026-08-17 20:1x-20:3xZ:
    `poll_soccer_live_state.py` raised `TypeError: _load_team_ratings() missing
    1 required positional argument: 'as_of'` for la_liga, primeira_liga and
    championship -- exactly and only the three leagues with matches in play,
    because the call sits behind `if live_events:` and a league with nothing
    live never reaches it. All three live-lens boards read "Live matches: 0 /
    Source: No data" while those matches were being played and scoring. Two
    more sites in `validate_soccer_vs_market.py` were broken on the same
    footing and were found by writing this census, not by running anything.

    THE GENERAL RULE, which is the point of keeping this test: a signature
    change needs a caller census, not a spot-check of the caller you just
    edited. Asserting call-site TEXT can only ever prove the one site you
    thought of.
    """
    census = _load_team_ratings_call_census()
    assert census, "the census found no call sites at all -- it has stopped looking correctly"

    wrong = [
        f"{rel}:{line} passes {passed} arg(s), needs {required}"
        for rel, line, passed, required in census
        if passed != required
    ]
    assert not wrong, "call sites disagree with the signature:\n  " + "\n  ".join(wrong)


def test_undated_rows_are_admitted_only_when_explicitly_allowed():
    """`fetch_asa_mls_team_history` returns SEASON AGGREGATES with no date.

    Dropping them silently emptied MLS ratings in production -- caught by a full
    suite run, not by the targeted one. Forward-looking callers opt in; the
    backtest must not, because a season average is contaminated by construction
    and no `as_of` can repair it.
    """
    rows = [{"team": "LAFC", "xg_for": 1.8, "xg_against": 1.1}]  # no date
    assert compute_team_ratings(rows, as_of="2026-06-01") == {}
    allowed = compute_team_ratings(rows, as_of="2026-06-01", allow_undated=True)
    assert allowed["LAFC"]["matches"] == 1.0


def test_the_backtest_never_admits_undated_rows():
    """MLS cannot be backtested from a season aggregate. The correct result is
    an empty rating set that says so, not a number that quietly leaks."""
    import inspect

    import scripts.backtest_soccer_live_lens as mod

    assert "allow_undated" not in inspect.getsource(mod), (
        "the backtest opted into undated rows; MLS season aggregates would leak"
    )


def test_the_forward_looking_callers_do_opt_in_and_say_why():
    import inspect

    import scripts.build_soccer_artifacts as build
    import scripts.validate_soccer_vs_market as validate

    for mod in (build, validate):
        source = inspect.getsource(mod._load_team_ratings)
        assert "allow_undated=True" in source, f"{mod.__name__} would empty MLS ratings"
