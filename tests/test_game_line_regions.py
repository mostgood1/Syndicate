"""S0b — extra OddsAPI regions on GAME LINES only.

The split is a billing fact. Measured on production 2026-08-07, the per-event
families (props + segment + alternate) are 95.5% of all credits, so a region on
the per-request game-line call costs ~30K/month while the same region on the
per-event prop calls costs ~1M. A single flat `regions` string cannot express
that, which is why the plan's "eu and us_ex on game lines only" was unshippable.

The behaviour that matters most is `test_base_regions_are_never_dropped`: the env
var supplies EXTRAS, so a bad value can widen coverage but can never silently
lose `us` and take the whole board's prices with it.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "fetch_mlb_oddsapi_local.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("fetch_mlb_oddsapi_local_under_test", _MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def mod():
    return _load_module()


def test_unset_env_is_exactly_todays_behaviour(mod, monkeypatch):
    """Ships dark: with no env var, nothing changes anywhere."""
    monkeypatch.delenv("SYNDICATE_LIVE_ODDS_GAME_LINE_REGIONS", raising=False)
    assert mod._game_line_regions("us") == "us"
    assert mod._game_line_regions("us,us2") == "us,us2"


def test_blank_env_is_treated_as_unset(mod, monkeypatch):
    monkeypatch.setenv("SYNDICATE_LIVE_ODDS_GAME_LINE_REGIONS", "   ")
    assert mod._game_line_regions("us") == "us"


def test_extras_are_appended_for_game_lines(mod, monkeypatch):
    monkeypatch.setenv("SYNDICATE_LIVE_ODDS_GAME_LINE_REGIONS", "eu,us_ex")
    assert mod._game_line_regions("us,us2") == "us,us2,eu,us_ex"


def test_base_regions_are_never_dropped(mod, monkeypatch):
    """The env var is EXTRAS, not a replacement. A value that omits `us` must
    not be able to remove it -- losing `us` would empty the board."""
    monkeypatch.setenv("SYNDICATE_LIVE_ODDS_GAME_LINE_REGIONS", "eu")
    assert mod._game_line_regions("us").split(",")[0] == "us"
    assert "us" in mod._game_line_regions("us").split(",")


def test_duplicates_are_not_billed_twice(mod, monkeypatch):
    monkeypatch.setenv("SYNDICATE_LIVE_ODDS_GAME_LINE_REGIONS", "us,eu,eu, US ")
    assert mod._game_line_regions("us,us2") == "us,us2,eu"


def test_ordering_keeps_us_first(mod, monkeypatch):
    """Order is preserved so the base list leads; some callers read the first
    region as the primary."""
    monkeypatch.setenv("SYNDICATE_LIVE_ODDS_GAME_LINE_REGIONS", "eu,us_ex,us2")
    assert mod._game_line_regions("us") == "us,eu,us_ex,us2"


def test_case_and_whitespace_are_normalised(mod, monkeypatch):
    monkeypatch.setenv("SYNDICATE_LIVE_ODDS_GAME_LINE_REGIONS", " EU , Us_Ex ")
    assert mod._game_line_regions("us") == "us,eu,us_ex"


# --- wiring -------------------------------------------------------------------
# The helper being correct is not the same as it being applied to the right call.
# This is the test that fails if someone later threads game_lines_regions into
# the prop fetches, which is the mistake that costs ~1M credits/month.


def test_only_the_game_line_call_gets_the_widened_regions(mod, monkeypatch, tmp_path):
    seen: dict[str, str] = {}

    def _fake_game_lines(api_key, date_str, *, regions, bookmakers, events):
        seen["game_lines"] = regions
        return {"game_lines": {"x": 1}}

    def _fake_pitcher(api_key, date_str, *, regions, bookmakers, events):
        seen["pitcher_props"] = regions
        return {"pitcher_props": {"x": 1}}

    def _fake_hitter(api_key, date_str, *, regions, bookmakers, markets, events):
        seen["hitter_props"] = regions
        return {"hitter_props": {"x": 1}}

    monkeypatch.setenv("ODDS_API_KEY", "test-key")
    monkeypatch.setenv("SYNDICATE_LIVE_ODDS_GAME_LINE_REGIONS", "eu,us_ex")
    monkeypatch.setattr(mod, "_load_env", lambda: None)
    monkeypatch.setattr(mod, "diagnose_odds_history_provenance", lambda *a, **k: None)
    monkeypatch.setattr(mod, "_fetch_live_events_for_date", lambda *a, **k: [])
    monkeypatch.setattr(mod, "fetch_live_game_lines_for_date", _fake_game_lines)
    monkeypatch.setattr(mod, "fetch_live_pitcher_props_for_date", _fake_pitcher)
    monkeypatch.setattr(mod, "fetch_live_hitter_props_for_date", _fake_hitter)
    monkeypatch.setattr(mod, "_append_mlb_book_quotes", lambda *a, **k: None)
    monkeypatch.setattr(mod, "_market_doc_entry_count", lambda *a, **k: 1)
    monkeypatch.setattr(mod, "_read_json_if_exists", lambda *a, **k: None)
    monkeypatch.setattr(mod, "_write_json", lambda *a, **k: None)

    result = mod.fetch_and_write_live_odds_for_date(
        "2026-08-07", out_dir=tmp_path, overwrite=True, regions="us,us2"
    )

    assert seen["game_lines"] == "us,us2,eu,us_ex"
    # The expensive calls MUST stay on the base list.
    assert seen["pitcher_props"] == "us,us2"
    assert seen["hitter_props"] == "us,us2"
    # And both lists are reported so a production artifact can prove it ran.
    assert result["regions"] == "us,us2"
    assert result["game_line_regions"] == "us,us2,eu,us_ex"


def test_with_env_unset_all_three_calls_match(mod, monkeypatch, tmp_path):
    seen: dict[str, str] = {}
    monkeypatch.setenv("ODDS_API_KEY", "test-key")
    monkeypatch.delenv("SYNDICATE_LIVE_ODDS_GAME_LINE_REGIONS", raising=False)
    monkeypatch.setattr(mod, "_load_env", lambda: None)
    monkeypatch.setattr(mod, "diagnose_odds_history_provenance", lambda *a, **k: None)
    monkeypatch.setattr(mod, "_fetch_live_events_for_date", lambda *a, **k: [])
    monkeypatch.setattr(mod, "fetch_live_game_lines_for_date",
                        lambda *a, regions, **k: seen.__setitem__("g", regions) or {"game_lines": {}})
    monkeypatch.setattr(mod, "fetch_live_pitcher_props_for_date",
                        lambda *a, regions, **k: seen.__setitem__("p", regions) or {"pitcher_props": {}})
    monkeypatch.setattr(mod, "fetch_live_hitter_props_for_date",
                        lambda *a, regions, **k: seen.__setitem__("h", regions) or {"hitter_props": {}})
    monkeypatch.setattr(mod, "_append_mlb_book_quotes", lambda *a, **k: None)
    monkeypatch.setattr(mod, "_market_doc_entry_count", lambda *a, **k: 1)
    monkeypatch.setattr(mod, "_read_json_if_exists", lambda *a, **k: None)
    monkeypatch.setattr(mod, "_write_json", lambda *a, **k: None)

    mod.fetch_and_write_live_odds_for_date("2026-08-07", out_dir=tmp_path, regions="us")
    assert seen == {"g": "us", "p": "us", "h": "us"}
