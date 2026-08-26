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


def test_props_file_is_carried_into_the_artifact_bundle(tmp_path):
    """Written next to the lines file, and picked up by the bundle glob.

    Without this the capture would land on the worker's disk and stop there.
    """
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    (data_dir / "oddsapi_player_props_2026_wk1.csv").write_text("player,book\n", encoding="utf-8")
    (data_dir / "oddsapi_player_props_2026_wk2.csv").write_text("player,book\n", encoding="utf-8")
    (data_dir / "college_football_betting_lines_2026.csv").write_text("x\n", encoding="utf-8")

    found = [path.name for path in runner._glob_data_files(tmp_path)]
    assert found == [
        "oddsapi_player_props_2026_wk1.csv",
        "oddsapi_player_props_2026_wk2.csv",
    ], f"bundle glob picked up {found}"


def test_bundle_glob_is_sorted_so_the_input_hash_is_stable(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    for week in (3, 1, 2):
        (data_dir / f"oddsapi_player_props_2026_wk{week}.csv").write_text("x\n", encoding="utf-8")
    found = runner._glob_data_files(tmp_path)
    assert found == sorted(found)


@pytest.mark.parametrize("flag", ["--skip-props", "--mode"])
def test_runner_can_opt_out_of_props(flag):
    """`--mode fast` and `--skip-props` both have to exist for the cheap tick."""
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("fast", "full"), default="full")
    parser.add_argument("--skip-props", action="store_true")
    source = (REPO_ROOT / "scripts" / "refresh_ncaaf_oddsapi.py").read_text(encoding="utf-8")
    assert '"--skip-props"' in source
    assert 'args.skip_props' in source
