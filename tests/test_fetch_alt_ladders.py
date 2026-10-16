"""Alternate-line ladders, once per cheat-sheet game, late pregame (lane `alt-ladders`, user 2026-10-16 option c)."""
from __future__ import annotations

import importlib.util
import json
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "fetch_alt_ladders", Path(__file__).resolve().parents[1] / "scripts" / "fetch_alt_ladders.py")
alt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(alt)

NOW = datetime(2026, 10, 18, 16, 0, tzinfo=timezone.utc)          # 11:00 AM CT


def _sheet(root: Path, sport: str, games: list[dict]) -> None:
    path = root / "cheatsheets" / sport / f"{alt.central_day(NOW)}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"sport": sport, "games": games}), encoding="utf-8")


def _game(event_id: str, minutes: float) -> dict:
    start = NOW + timedelta(minutes=minutes)
    return {"event_id": event_id, "commence_time": start.isoformat().replace("+00:00", "Z"),
            "home_team": "Jacksonville Jaguars", "away_team": "Houston Texans"}


def _payload(event_id: str, markets: list[str]) -> dict:
    return {"id": event_id, "commence_time": "2026-10-18T17:30:00Z", "home_team": "Jacksonville Jaguars",
            "away_team": "Houston Texans",
            "bookmakers": [{"key": "draftkings", "markets": [
                {"key": m, "last_update": "2026-10-18T15:59:00Z", "outcomes": [
                    {"name": "Over", "description": "Nico Collins", "point": p, "price": price}
                    for p, price in ((49.5, -180), (59.5, -125), (69.5, 110), (79.5, 160))]} for m in markets]}]}


class FakeApi:
    def __init__(self, cost_per_market=1, fail_422_with=None):
        self.calls = []
        self.cost = cost_per_market
        self.fail_422_with = fail_422_with

    def __call__(self, url):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        markets = q["markets"][0].split(",")
        self.calls.append({"markets": markets, "bookmakers": q.get("bookmakers", [""])[0], "regions": q["regions"][0]})
        if self.fail_422_with and self.fail_422_with in markets and len(markets) > 1:
            return 422, None, {"x-requests-last": "0"}
        event_id = urllib.parse.urlparse(url).path.split("/events/")[1].split("/")[0]
        good = [m for m in markets if m != self.fail_422_with]
        return 200, _payload(event_id, good), {"x-requests-last": str(self.cost * len(good)), "x-requests-used": "1"}


@pytest.fixture(autouse=True)
def _no_quota_store(monkeypatch):
    import syndicate.features.shared.oddsapi_quota as q

    monkeypatch.setattr(q, "record_oddsapi_quota", lambda headers, **kw: None)


def test_only_games_entering_the_window_are_fetched_once_and_only_the_alternate_keys(tmp_path):
    _sheet(tmp_path, "nfl", [_game("soon", 75), _game("later", 200), _game("started", -5), _game("too_close", 10)])
    api = FakeApi()
    totals = alt.run(tmp_path, ["nfl"], now=NOW, api_key="k", cap=400, get=api)
    assert [c["markets"] for c in api.calls] == [list(alt.ALT_MARKETS["nfl"])]
    assert all(m.endswith("_alternate") for m in api.calls[0]["markets"])
    assert api.calls[0]["bookmakers"].count(",") == 9                        # the 10-book list: one region
    assert totals["fetched"] == 1 and totals["credits"] == 8
    rows = [json.loads(line) for line in (tmp_path / "nfl_source" / "tracking" / "alt_ladders" /
                                          f"{alt.central_day(NOW)}.jsonl").read_text(encoding="utf-8").splitlines()]
    assert {r["line"] for r in rows} == {49.5, 59.5, 69.5, 79.5}               # the whole ladder, every rung
    assert rows[0]["base_market"] == rows[0]["market_key"].removesuffix("_alternate")
    again = FakeApi()
    alt.run(tmp_path, ["nfl"], now=NOW + timedelta(minutes=15), api_key="k", cap=400, get=again)
    assert again.calls == []                                                  # once per game, ever
    state = json.loads((tmp_path / "nfl_source" / "tracking" / "alt_ladders" /
                        f"{alt.central_day(NOW)}.state.json").read_text(encoding="utf-8"))
    assert state["credits"] == 8 and state["events"]["soon"]["players"] == 1


def test_the_daily_cap_stops_spending_before_the_call(tmp_path):
    _sheet(tmp_path, "nfl", [_game("a", 60), _game("b", 70)])
    api = FakeApi()
    totals = alt.run(tmp_path, ["nfl"], now=NOW, api_key="k", cap=10, get=api)
    assert len(api.calls) == 1 and totals["skipped_cap"] == 1                  # 8 spent; 8 more would pass 10


def test_a_422_on_the_combined_call_falls_back_to_one_call_per_key(tmp_path):
    _sheet(tmp_path, "nhl", [_game("g", 60)])
    api = FakeApi(fail_422_with="player_total_saves_alternate")
    totals = alt.run(tmp_path, ["nhl"], now=NOW, api_key="k", cap=400, get=api)
    assert len(api.calls) == 1 + len(alt.ALT_MARKETS["nhl"])
    assert totals["errors"] == 0 and totals["rows"] > 0


def test_ncaaf_is_never_fetched_and_a_dry_run_spends_nothing(tmp_path):
    _sheet(tmp_path, "ncaaf", [_game("x", 60)])
    _sheet(tmp_path, "nfl", [_game("y", 60)])
    api = FakeApi()
    totals = alt.run(tmp_path, ["ncaaf", "nfl"], now=NOW, api_key="k", cap=400, dry_run=True, get=api)
    assert api.calls == [] and totals["due"] == 1
    assert "ncaaf" not in alt.SPORT_KEYS


def test_the_ladder_is_a_separate_family_from_the_main_quotes(tmp_path):
    _sheet(tmp_path, "mlb", [_game("m", 45)])
    alt.run(tmp_path, ["mlb"], now=NOW, api_key="k", cap=400, get=FakeApi())
    written = sorted(str(p.relative_to(tmp_path)).replace("\\", "/") for p in tmp_path.rglob("*") if p.is_file())
    assert all("alt_ladders" in p or p.startswith("cheatsheets/") for p in written)
    assert not any("book_quotes" in p for p in written)
