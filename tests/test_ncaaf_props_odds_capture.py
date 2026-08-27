"""Guards for the NCAAF player-prop capture path, wired 2026-08-26.

Two defects are pinned here, both of which were live in production on the
morning of the 2026-08-29 season openers:

1. **Nothing called the fetcher.** `scripts/fetch_ncaaf_oddsapi_props_local.py`
   had been complete since 2026-08-20 and had no caller anywhere -- not the
   NCAAF runner, not the orchestrator, not a worker autorun. NFL's identical
   fetcher is invoked from `refresh_nfl_oddsapi.py`; NCAAF's was not. Measured
   on production 2026-08-26: all 51 served wk1 cards carried
   `shared_prop_rows: []`.

2. **The parser kept one book.** `_choose_bookmaker` selected a single
   bookmaker out of a response that already contained several. Measured on the
   real wk1 openers, one sweep: the shared quote log recorded **409 quotes
   across 6 books and 6 markets** while the CSV this file writes held **60
   rows, one market, effectively one book**. After the fix, the same sweep
   wrote **329 rows across all 6 books and all 6 markets**, and 74 of 130
   selections turned out to be quoted by more than one book.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load(module_name: str, relative: str):
    path = REPO_ROOT / relative
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


props = _load("_test_ncaaf_props_capture", "scripts/fetch_ncaaf_oddsapi_props_local.py")
runner = _load("_test_ncaaf_runner", "scripts/refresh_ncaaf_oddsapi.py")


def _event_with_books() -> dict:
    """One event, three books, deliberately disagreeing on price.

    Shaped like the real 2026 wk1 payload: an Anytime TD market with no
    `point`, plus a yardage market carrying over/under at a line.
    """
    def _book(key: str, td_price: int, yds_over: int, yds_line: float):
        return {
            "key": key,
            "markets": [
                {
                    "key": "player_anytime_td",
                    "outcomes": [{"name": "Yes", "description": "Landen Thomas", "price": td_price}],
                },
                {
                    "key": "player_reception_yds",
                    "outcomes": [
                        {"name": "Over", "description": "Landen Thomas", "price": yds_over, "point": yds_line},
                        {"name": "Under", "description": "Landen Thomas", "price": -120, "point": yds_line},
                    ],
                },
            ],
        }

    return {
        "away_team": "North Carolina",
        "home_team": "TCU",
        "commence_time": "2026-08-29T16:00:00Z",
        "bookmakers": [
            _book("draftkings", 700, -110, 34.5),
            _book("fanduel", 230, -115, 34.5),
            _book("betonlineag", 140, -105, 33.5),
        ],
    }


def test_every_bookmaker_is_kept_not_just_one():
    """The #209 Class A defect, on the CSV rather than the quote log."""
    rows = props.parse_events_to_rows([_event_with_books()])
    books = {row["book"] for row in rows}
    assert books == {"draftkings", "fanduel", "betonlineag"}, (
        f"parser dropped books: kept {sorted(books)}"
    )

    td_rows = [row for row in rows if row["market"] == "Anytime TD"]
    assert len(td_rows) == 3, f"expected one Anytime TD row per book, got {len(td_rows)}"
    assert {int(row["over_price"]) for row in td_rows} == {700, 230, 140}


def test_price_shopping_is_possible_from_the_output():
    """The whole point of keeping every book: a best price must be derivable.

    +700 vs +140 on the same selection is the measured shape of the real
    payload, not a synthetic exaggeration.
    """
    rows = props.parse_events_to_rows([_event_with_books()])
    td_prices = [int(row["over_price"]) for row in rows if row["market"] == "Anytime TD"]
    assert max(td_prices) - min(td_prices) == 560


def test_alternate_lines_for_one_player_are_not_collapsed():
    """A player-only aggregation key made the last line win and dropped the rest."""
    event = {
        "away_team": "NC State",
        "home_team": "Virginia",
        "commence_time": "2026-08-29T19:30:00Z",
        "bookmakers": [
            {
                "key": "draftkings",
                "markets": [
                    {
                        "key": "player_rush_yds",
                        "outcomes": [
                            {"name": "Over", "description": "Hollywood Smothers", "price": -110, "point": 49.5},
                            {"name": "Over", "description": "Hollywood Smothers", "price": +130, "point": 69.5},
                        ],
                    }
                ],
            }
        ],
    }
    rows = props.parse_events_to_rows([event])
    lines = sorted(float(row["line"]) for row in rows)
    assert lines == [49.5, 69.5], f"alternate lines collapsed to {lines}"


def test_choose_bookmaker_is_retained_for_diffability_against_nfl():
    """Left in place on purpose -- deleting it makes the two files diverge."""
    assert hasattr(props, "_choose_bookmaker")


# ---------------------------------------------------------------- the caller


def test_runner_exposes_a_props_step():
    assert hasattr(runner, "_refresh_player_props")
    assert runner._props_file_name(2026, 1) == "oddsapi_player_props_2026_wk1.csv"


def test_props_failure_never_fails_the_lines_refresh(monkeypatch, tmp_path):
    """A prop-side error must degrade to a reason, not a non-zero exit.

    The lines snapshot is what the board reads today. NFL's runner returns the
    props exit code and would take the whole refresh down; NCAAF deliberately
    does not.
    """
    def _boom():
        raise RuntimeError("odds api exploded")

    monkeypatch.setattr(runner, "_load_props_fetcher", _boom)
    result = runner._refresh_player_props(data_root=tmp_path, season=2026, week=1)
    assert result["status"] == "error"
    assert "RuntimeError" in result["error"]


def test_props_file_lands_where_the_allowlist_already_reaches(tmp_path):
    """`data/processed/`, and the glob that fingerprints it agrees.

    One directory shallower and the capture can never cross to web -- and it
    fails as an empty props panel, not as an error.
    `tests/test_ncaaf_props_board.py` pins the allowlist half of this; this
    pins the writer half.
    """
    processed = tmp_path / "data" / "processed"
    processed.mkdir(parents=True)
    (processed / "oddsapi_player_props_2026_wk1.csv").write_text("player,book\n", encoding="utf-8")
    (processed / "oddsapi_player_props_2026_wk2.csv").write_text("player,book\n", encoding="utf-8")
    (tmp_path / "data" / "college_football_betting_lines_2026.csv").write_text("x\n", encoding="utf-8")

    found = [path.name for path in runner._glob_data_files(tmp_path)]
    assert found == [
        "oddsapi_player_props_2026_wk1.csv",
        "oddsapi_player_props_2026_wk2.csv",
    ], f"fingerprint glob picked up {found}"


def test_the_props_file_is_NOT_copied_flat_into_the_artifact_bundle():
    """A flat bundle copy would be undeliverable, so it must not happen.

    `artifact_root / path.name` would land it at
    `ncaaf_source/source_artifacts/oddsapi_player_props_*.csv`, which the
    allowlist does not match -- a second, stale, unreachable copy beside the
    live one. Delivery is `publish_hot_artifact` on the canonical path.
    """
    source = (REPO_ROOT / "scripts" / "refresh_ncaaf_oddsapi.py").read_text(encoding="utf-8")
    # Checked as the COPY LOOP, not as the expression -- the expression also
    # appears in the comment in that file explaining why it must not be there,
    # and a substring test on it fails against its own documentation.
    assert "_copy_if_exists(path, destination)" not in source
    assert "publish_hot_artifact" in source


def test_the_capture_is_published_not_just_written():
    """Allowlisting PERMITS a transfer; it does not perform one (`#208`).

    Without the publish call the CSV sits on the worker disk forever, because
    Render cannot share a disk between the worker and web.
    """
    source = (REPO_ROOT / "scripts" / "refresh_ncaaf_oddsapi.py").read_text(encoding="utf-8")
    assert "published = bool(publish_hot_artifact(out_path))" in source
    # Guarded on rows, so an empty pregame capture does not burn egress.
    assert "if rows > 0:" in source


def test_bundle_glob_is_sorted_so_the_input_hash_is_stable(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    for week in (3, 1, 2):
        (data_dir / f"oddsapi_player_props_2026_wk{week}.csv").write_text("x\n", encoding="utf-8")
    found = runner._glob_data_files(tmp_path)
    assert found == sorted(found)


def test_the_legacy_runners_opt_out_flag_is_retained_for_compatibility():
    """`--skip-props` still parses, and now defaults ON.

    REPLACES a test that asserted `args.skip_props` was READ in that runner.
    That was true when props lived there and is not any more -- props moved to
    `ncaaf_player_props_oddsapi` because the legacy runner cannot execute for
    2026 at all. The flag stays so existing callers do not break; what it must
    NOT do is gate a second capture, which
    `test_the_legacy_runner_no_longer_captures_props` pins.
    """
    source = (REPO_ROOT / "scripts" / "refresh_ncaaf_oddsapi.py").read_text(encoding="utf-8")
    assert '"--skip-props"' in source
    assert "default=True" in source




# ------------------------------------------------- the production path bug


def _seed_predictions(directory):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "college_football_schedule_2026_predicted_totals_enhanced.csv").write_text(
        "season,week\n2026,1\n", encoding="utf-8"
    )


@pytest.mark.parametrize(
    "relative,label",
    [("", "local: csv directly in --artifact-root"),
     ("source_artifacts", "render: csv one level down"),
     ("data", "csv under data/")],
)
def test_data_root_resolves_in_every_layout_that_actually_occurs(tmp_path, relative, label):
    """`_local_source_artifact_root` names two different layouts.

    LOCALLY it appends `source_artifacts` and the CSVs sit in the root it
    passes; ON RENDER it does NOT append it, so the same CSVs are one level
    down. Only the local layout was searched, so the NCAAF step could not run
    in production at all -- measured 2026-08-27, failing in 0 seconds with a
    FileNotFoundError that surfaced only inside ODDS_REFRESH_FAILURE_SUMMARY.
    """
    _seed_predictions(tmp_path / relative if relative else tmp_path)
    assert runner._resolve_data_root(source_root=None, artifact_root=tmp_path) == tmp_path.resolve()


def test_data_root_is_the_source_root_not_the_predictions_directory(tmp_path):
    """Writes go to `<data_root>/data/`, so returning the deeper directory
    would scatter artifacts into `source_artifacts/data/` on production."""
    _seed_predictions(tmp_path / "source_artifacts")
    assert runner._resolve_data_root(source_root=None, artifact_root=tmp_path) == tmp_path.resolve()


def test_a_root_with_no_predictions_is_still_refused_and_says_where_it_looked(tmp_path):
    """Widening the search must not turn the gate into a rubber stamp."""
    with pytest.raises(FileNotFoundError) as excinfo:
        runner._resolve_data_root(source_root=None, artifact_root=tmp_path)
    assert "Searched:" in str(excinfo.value)


def test_the_gate_and_its_consumer_use_one_rule(tmp_path):
    """The defect class: a gate strictly narrower than the thing it guards.

    `_prediction_context` always searched `data/` as well, so the gate could
    refuse a root the consumer would have read happily.
    """
    _seed_predictions(tmp_path / "source_artifacts")
    assert runner._prediction_files(tmp_path), "consumer cannot see the predictions"
    assert runner._resolve_data_root(source_root=None, artifact_root=tmp_path)


# ------------------------------------- the capture hangs off the RIGHT step


def _ncaaf_steps():
    import argparse
    import importlib
    import sys

    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    if str(REPO_ROOT / "scripts") not in sys.path:
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
    ros = importlib.import_module("refresh_odds_sources")
    return ros, ros._build_ncaaf_steps(argparse.Namespace(season=2026, week=1, date="2026-08-26"))


def test_props_are_captured_by_their_own_step_not_the_legacy_runner():
    """The correction this file's earlier version got wrong.

    Props were first wired inside `refresh_ncaaf_oddsapi.py`. That runner
    CANNOT RUN FOR 2026: it requires a
    `college_football_schedule_<season>_predicted_totals_enhanced*.csv`, git
    holds 359 of them and every one is season 2025, and even were one found
    `_should_skip_auto_refresh` returns True once
    `prediction_season < current year`. Measured on production
    2026-08-27T01:04:55Z: `STEP_FAIL name=ncaaf_lines_snapshot
    runtime_seconds=0 return_code=1`. Props wired there were unreachable in
    exactly the season they were built for.
    """
    _ros, steps = _ncaaf_steps()
    names = [s.name for s in steps]
    assert "ncaaf_player_props_oddsapi" in names
    props = next(s for s in steps if s.name == "ncaaf_player_props_oddsapi")
    joined = " ".join(str(c) for c in props.command)
    assert "fetch_ncaaf_oddsapi_props_local.py" in joined
    assert "refresh_ncaaf_oddsapi.py" not in joined, "props must not depend on the legacy runner"


def test_props_land_on_the_allowlisted_week_keyed_path():
    from syndicate.features.shared.artifact_publisher import is_hot_artifact_relative_path

    _ros, steps = _ncaaf_steps()
    props = next(s for s in steps if s.name == "ncaaf_player_props_oddsapi")
    out = Path(str(props.command[props.command.index("--out") + 1]))
    assert out.parent.name == "processed"
    assert out.name == "oddsapi_player_props_2026_wk1.csv"
    assert is_hot_artifact_relative_path(f"ncaaf_source/data/processed/{out.name}")


def test_props_run_after_the_game_lines_capture():
    """Lines are one call; props are billed per event per market.

    If a sweep runs short of time or credits it should lose props and keep
    prices, so ordering is load-bearing rather than cosmetic.
    """
    _ros, steps = _ncaaf_steps()
    names = [s.name for s in steps]
    assert names.index("ncaaf_game_lines_oddsapi") < names.index("ncaaf_player_props_oddsapi")


def test_the_legacy_runner_no_longer_captures_props():
    """Exactly one producer -- two would double-spend per event per market."""
    source = (REPO_ROOT / "scripts" / "refresh_ncaaf_oddsapi.py").read_text(encoding="utf-8")
    assert "moved_to_ncaaf_player_props_oddsapi" in source
    assert "_refresh_player_props(data_root=" not in source


def test_the_fetcher_publishes_what_it_writes():
    """No wrapper left to hang the publish on -- the step shells the script."""
    source = (REPO_ROOT / "scripts" / "fetch_ncaaf_oddsapi_props_local.py").read_text(encoding="utf-8")
    assert "publish_hot_artifact(out_path)" in source
    assert "if len(out_df):" in source


def test_season_and_week_come_from_the_boards_own_resolver():
    """A capture filed under a week the card never asks for is, from the
    board, indistinguishable from no capture at all."""
    ros, _steps = _ncaaf_steps()
    assert ros._infer_ncaaf_context(2026, 3) == (2026, 3)
    season, week = ros._infer_ncaaf_context(None, None)
    assert season >= 2026 and week >= 1
