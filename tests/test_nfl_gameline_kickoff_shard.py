"""NFL game-line quotes are filed by the game's CENTRAL KICKOFF date, not the UTC capture date.

THE DEFECT THIS PINS (lane nfl-gameline-kickoff-shard, measured on the fleet 2026-11-15).
`fetch_nfl_team_odds_local._append_nfl_team_book_quotes` wrote every NFL game-market quote
under `datetime.now(utc).date()`. From 00:00Z (6 PM CST) that is TOMORROW, so Sunday Night
Football's in-play game lines (PIT @ CIN, kickoff 01:22Z = 7:20 PM CST 11-15) all went to
`2026-11-16.jsonl` while the 11-15 board, in-play overlay and Games Rail read `2026-11-15.jsonl`.

These tests run the REAL `append_book_quotes` into a temporary data root and read the files
it wrote, so they assert where the rows LAND, not which date string a mock was handed.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
from datetime import datetime, timezone

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]

# 7:20 PM CST Sunday 11-15 is 01:20Z Monday 11-16 -- the SNF shape that was misfiled.
SNF_KICKOFF = "2026-11-16T01:20:00Z"
# 7:15 PM CST Monday 11-16 is 01:15Z Tuesday 11-17 -- MNF, the next game the defect would hit.
MNF_KICKOFF = "2026-11-17T01:15:00Z"
# Noon CST Sunday 11-22: a next-week game captured on Monday.
NEXT_SUNDAY_KICKOFF = "2026-11-22T18:00:00Z"
# 7:15 PM CST Thursday 11-19 (TNF): Central 11-19, UTC 11-20.
TNF_KICKOFF = "2026-11-20T01:15:00Z"

# Captured in play during SNF: 7:45 PM CST 11-15, which is already 11-16 in UTC.
AFTER_UTC_MIDNIGHT = datetime(2026, 11, 16, 1, 45, tzinfo=timezone.utc)
# Captured Monday afternoon, 3:00 PM CST 11-16.
MONDAY_AFTERNOON = datetime(2026, 11, 16, 21, 0, tzinfo=timezone.utc)


def _module():
    spec = importlib.util.spec_from_file_location(
        "fetch_nfl_team_odds_local_kickoff_shard", ROOT / "scripts" / "fetch_nfl_team_odds_local.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _event(event_id: str, commence_time, *, home: str, away: str, market_suffix: str = "") -> dict:
    """An OddsAPI-shaped event with one book quoting h2h and totals (or their `_<segment>` keys)."""
    stamp = "2026-11-16T01:40:00Z"
    event = {
        "id": event_id,
        "sport_key": "americanfootball_nfl",
        "home_team": home,
        "away_team": away,
        "bookmakers": [
            {
                "key": "draftkings",
                "title": "DraftKings",
                "last_update": stamp,
                "markets": [
                    {
                        "key": f"h2h{market_suffix}",
                        "last_update": stamp,
                        "outcomes": [{"name": home, "price": -150}, {"name": away, "price": 130}],
                    },
                    {
                        "key": f"totals{market_suffix}",
                        "last_update": stamp,
                        "outcomes": [
                            {"name": "Over", "price": -110, "point": 44.5},
                            {"name": "Under", "price": -110, "point": 44.5},
                        ],
                    },
                ],
            }
        ],
    }
    if commence_time is not None:
        event["commence_time"] = commence_time
    return event


def _snf(**kwargs) -> dict:
    return _event("snf-pit-cin", SNF_KICKOFF, home="Cincinnati Bengals", away="Pittsburgh Steelers", **kwargs)


def _mnf() -> dict:
    return _event("mnf-lac-bal", MNF_KICKOFF, home="Baltimore Ravens", away="Los Angeles Chargers")


@pytest.fixture()
def data_root(monkeypatch, tmp_path):
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path))
    monkeypatch.delenv("SYNDICATE_WEB_PUBLISH_URL", raising=False)
    monkeypatch.delenv("SYNDICATE_NFL_GAMELINE_QUOTES_KICKOFF_SHARD", raising=False)
    return tmp_path


def _shards(root: pathlib.Path) -> dict[str, list[dict]]:
    """{shard date: rows} for every NFL quote shard the writer created."""
    folder = root / "nfl_source" / "tracking" / "book_quotes"
    out: dict[str, list[dict]] = {}
    for path in sorted(folder.glob("*.jsonl")):
        out[path.stem] = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return out


def _events_in(rows: list[dict]) -> set[str]:
    return {str(row.get("event_id")) for row in rows}


def test_switch_reaches_the_filing_off_differs_from_on(data_root, monkeypatch, tmp_path):
    """Reachability first: the same capture lands in a DIFFERENT shard with the switch off."""
    module = _module()

    on = module._append_nfl_team_book_quotes([_snf()], now=AFTER_UTC_MIDNIGHT)
    on_shards = _shards(data_root)

    off_root = tmp_path / "off"
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(off_root))
    monkeypatch.setenv("SYNDICATE_NFL_GAMELINE_QUOTES_KICKOFF_SHARD", "0")
    off = module._append_nfl_team_book_quotes([_snf()], now=AFTER_UTC_MIDNIGHT)
    off_shards = _shards(off_root)

    assert on["basis"] == "kickoff_central"
    assert off["basis"] == "utc_capture"
    assert sorted(on_shards) == ["2026-11-15"]
    assert sorted(off_shards) == ["2026-11-16"]  # the old behaviour, exactly
    assert on_shards != off_shards


@pytest.mark.parametrize("raw", ["0", "false", "no", "off", " OFF "])
def test_every_off_spelling_restores_the_utc_capture_date(monkeypatch, raw):
    monkeypatch.setenv("SYNDICATE_NFL_GAMELINE_QUOTES_KICKOFF_SHARD", raw)
    assert _module()._nfl_gameline_kickoff_shard_enabled() is False


@pytest.mark.parametrize("raw", [None, "", "1", "true", "on"])
def test_absent_or_on_files_by_kickoff(monkeypatch, raw):
    if raw is None:
        monkeypatch.delenv("SYNDICATE_NFL_GAMELINE_QUOTES_KICKOFF_SHARD", raising=False)
    else:
        monkeypatch.setenv("SYNDICATE_NFL_GAMELINE_QUOTES_KICKOFF_SHARD", raw)
    assert _module()._nfl_gameline_kickoff_shard_enabled() is True


def test_a_7_20_pm_cst_kickoff_captured_after_utc_midnight_lands_in_its_central_date(data_root):
    """The SNF case: in-play rows captured at 01:45Z 11-16 belong to the 11-15 board."""
    module = _module()
    full = _snf()
    segment = _snf(market_suffix="_q1")  # a per-event segment payload for the same game

    summary = module._append_nfl_team_book_quotes([full, segment], now=AFTER_UTC_MIDNIGHT)
    shards = _shards(data_root)

    assert sorted(shards) == ["2026-11-15"], shards.keys()
    rows = shards["2026-11-15"]
    assert _events_in(rows) == {"snf-pit-cin"}
    # Full-game AND quarter rows both follow the game, not the clock.
    assert {row.get("segment") or "full" for row in rows} == {"full", "q1"}
    assert all(str(row.get("captured_at", "")).startswith("2026-11-16T01:45") for row in rows)
    assert summary["shards"] == {"2026-11-15": len(rows)}
    assert summary["unfiled_no_commence_time"] == 0


def test_one_capture_splits_across_each_games_own_kickoff_date(data_root):
    """Monday afternoon's pull carries tonight's MNF, Thursday's TNF and next Sunday's games."""
    module = _module()
    next_sunday = _event("sun-buf-kc", NEXT_SUNDAY_KICKOFF, home="Kansas City Chiefs", away="Buffalo Bills")
    tnf = _event("tnf-gb-chi", TNF_KICKOFF, home="Chicago Bears", away="Green Bay Packers")

    summary = module._append_nfl_team_book_quotes([_mnf(), tnf, next_sunday], now=MONDAY_AFTERNOON)
    shards = _shards(data_root)

    assert sorted(shards) == ["2026-11-16", "2026-11-19", "2026-11-22"]
    assert _events_in(shards["2026-11-16"]) == {"mnf-lac-bal"}
    assert _events_in(shards["2026-11-19"]) == {"tnf-gb-chi"}  # Central Thursday, not UTC Friday
    assert _events_in(shards["2026-11-22"]) == {"sun-buf-kc"}
    assert sum(summary["shards"].values()) == summary["rows"]


def test_mnf_in_play_after_utc_midnight_stays_on_mondays_shard(data_root):
    """The next game the defect hits: MNF 11-16, captured in play at 01:40Z 11-17."""
    module = _module()
    module._append_nfl_team_book_quotes([_mnf()], now=datetime(2026, 11, 17, 1, 40, tzinfo=timezone.utc))
    assert sorted(_shards(data_root)) == ["2026-11-16"]


def test_a_null_kickoff_is_reported_not_silently_dropped_and_not_filed_as_today(data_root, capsys):
    module = _module()
    unknown = _event("no-kickoff", None, home="Detroit Lions", away="Minnesota Vikings")
    blank = _event("blank-kickoff", "", home="Denver Broncos", away="Las Vegas Raiders")

    summary = module._append_nfl_team_book_quotes([unknown, blank, _mnf()], now=MONDAY_AFTERNOON)
    shards = _shards(data_root)
    line = [text for text in capsys.readouterr().out.splitlines() if "NFL_GAMELINE_QUOTE_SHARD" in text]

    # The known game still files; the unknown ones are not guessed onto any date.
    assert sorted(shards) == ["2026-11-16"]
    assert _events_in(shards["2026-11-16"]) == {"mnf-lac-bal"}
    # ...and the count and the events are on the always-printed line.
    assert summary["unfiled_no_commence_time"] == 8  # 2 events x 2 markets x 2 outcomes, one row each
    assert summary["rows"] == 8 + len(shards["2026-11-16"])  # every row is either filed or counted
    assert summary["unfiled_events"] == ["blank-kickoff", "no-kickoff"]
    assert len(line) == 1
    assert "basis=kickoff_central" in line[0]
    assert "unfiled_no_commence_time=8" in line[0]
    assert "unfiled_events=blank-kickoff,no-kickoff" in line[0]
    assert "shards=2026-11-16:" in line[0]


def test_the_branch_line_is_printed_on_the_off_path_too(data_root, monkeypatch, capsys):
    monkeypatch.setenv("SYNDICATE_NFL_GAMELINE_QUOTES_KICKOFF_SHARD", "off")
    _module()._append_nfl_team_book_quotes([_snf()], now=AFTER_UTC_MIDNIGHT)
    out = capsys.readouterr().out
    assert "NFL_GAMELINE_QUOTE_SHARD basis=utc_capture" in out
    assert "shards=2026-11-16:" in out


def test_never_raises_and_empty_input_writes_nothing(data_root, monkeypatch):
    module = _module()
    assert module._append_nfl_team_book_quotes([], now=MONDAY_AFTERNOON) is None
    assert module._append_nfl_team_book_quotes(None, now=MONDAY_AFTERNOON) is None  # type: ignore[arg-type]
    assert _shards(data_root) == {}

    import syndicate.features.shared.odds_book_quotes as obq

    def _boom(*_args, **_kwargs):
        raise RuntimeError("disk gone")

    monkeypatch.setattr(obq, "bucket_quote_rows_by_kickoff_date", _boom)
    assert module._append_nfl_team_book_quotes([_mnf()], now=MONDAY_AFTERNOON) is None


def test_main_still_routes_full_game_and_segment_payloads_through_the_writer(monkeypatch):
    """Wiring: `main()` hands BOTH the bulk events and the per-event segment payloads to the writer."""
    module = _module()
    seen: list[list[dict]] = []
    monkeypatch.setenv("ODDS_API_KEY", "test-key")
    monkeypatch.setattr(module, "fetch_odds", lambda **_kwargs: [_mnf()])
    monkeypatch.setattr(module, "_fetch_nfl_segments", lambda _key, _events: [_snf(market_suffix="_q1")])
    monkeypatch.setattr(module, "_append_nfl_team_book_quotes", lambda events: seen.append(list(events)))
    monkeypatch.setattr(module, "write_daily_lines", lambda payload, *, data_dir: data_dir / "x.json")
    module.main(data_dir=ROOT / "nonexistent-test-dir")
    assert len(seen) == 1
    assert [event["id"] for event in seen[0]] == ["mnf-lac-bal", "snf-pit-cin"]
