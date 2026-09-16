"""A FUTURE date must never take another date's games, because a worker saves them.

Measured 2026-09-16, lane `wnba-future-date-cache-carry` (after `9b214a33` closed
the today path):
  * `/wnba/api/live_state?date=2026-09-16` served the four 2026-08-30 finals
    (ESPN 401857186..189) on a no-game day, while every refresh-worker build of
    09-16 after CT midnight returned 0 games (584 of them);
  * refresh-worker logged `build_live_state_payload_fallback_return
    selected_date=2026-09-16 game_count=4` at 04:31:02Z -- 23:31 CDT on 09-15,
    while 09-16 was still TOMORROW;
  * the look-ahead warmer is live on refresh-worker (`last_look_ahead_check`
    `date 2026-09-17 launched true`) and runs `refresh_wnba_oddsapi_props.py
    --date <tomorrow> --source-root ... --artifact-root ...`, whose
    `_export_live_snapshot_artifacts` saves `build_live_state_payload(<tomorrow>,
    allow_stored_date_fallback=True)` under tomorrow's live_state key.

`_stored_date_substitution_allowed` answered True for every non-today date, so
the resolver substituted the last real slate under tomorrow. After midnight
`_games_from_live_state_fallback(today)` reads the key back, so a single
pre-midnight write lasts the whole day.

Every test here is pinned both ways: the pre-fix code fails it.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from syndicate.features.wnba import cards
from syndicate.features.wnba import sources

EVE = "2026-09-15"
TOMORROW = "2026-09-16"
PAST = "2026-09-05"
LAST_SLATE = "2026-08-30"
PHANTOM_IDS = ["401857186", "401857187", "401857188", "401857189"]
TOMORROW_IDS = ["401857190"]

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "refresh_wnba_oddsapi_props.py"


class _Response:
    def __init__(self, body):
        self._body = json.dumps(body).encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _game(event_id, away, home):
    return {"gamePk": event_id, "event_id": event_id, "away": {"abbr": away}, "home": {"abbr": home},
            "away_tri": away, "home_tri": home, "detail": "Final", "status": "Final",
            "live_state": {"final": True, "away_pts": 80, "home_pts": 70}}


# ------------------------------------------------------------------ the rule
@pytest.mark.parametrize("verdict", [None, False, True])
def test_a_future_date_is_never_substituted(monkeypatch, verdict):
    monkeypatch.setattr(cards, "central_today_iso", lambda: EVE)
    assert cards._stored_date_substitution_allowed(TOMORROW, verdict) is False


@pytest.mark.parametrize("verdict, expected", [(None, False), (False, False), (True, True)])
def test_today_and_the_past_are_unchanged(monkeypatch, verdict, expected):
    monkeypatch.setattr(cards, "central_today_iso", lambda: EVE)
    assert cards._stored_date_substitution_allowed(EVE, verdict) is expected
    assert cards._stored_date_substitution_allowed(PAST, verdict) is True


# ---------------------------------------------------------------- the writer
@pytest.fixture
def eve_of_a_no_game_day(monkeypatch):
    """23:31 CDT on 09-15. Only the 08-30 slate has cards, and ESPN lists nothing for 09-16.

    Stubbed: the clock, ESPN, and the ARTIFACT LOADERS (no real CSVs). REAL: the
    look-ahead writer `_export_live_snapshot_artifacts`, `build_live_state_payload`,
    `build_cards_page_context`, `_resolved_source_cards_date`,
    `_nearest_available_cards_date`, `_stored_date_substitution_allowed` and
    `has_games_for_date`.
    """
    slates = {LAST_SLATE: [_game(i, a, h) for i, (a, h) in zip(
        PHANTOM_IDS, [("MIN", "ATL"), ("LAS", "SEA"), ("GSV", "POR"), ("CON", "DAL")])]}

    monkeypatch.setattr(sources.urllib_request, "urlopen", lambda _r, timeout=None: _Response({"events": []}))
    monkeypatch.delenv("SYNDICATE_WNBA_SCOREBOARD_URL", raising=False)
    for module in (cards, sources):
        monkeypatch.setattr(module, "central_today_iso", lambda: EVE)
        monkeypatch.setattr(module, "available_dates", lambda: sorted(slates))
    sources._HAS_GAMES_CONFIRMED_TRUE_CACHE.clear()
    cards._BUILD_CARDS_PAGE_CONTEXT_CACHE.clear()
    cards.build_live_state_payload.cache_clear()

    monkeypatch.setattr(cards, "_artifact_bundle", lambda d, allow_fallback=True: {
        "rows": [{}] * len(slates.get(d, [])), "recommendations": {}, "sim": {}, "props": {}, "paths": {}})
    monkeypatch.setattr(cards, "_games_from_artifacts",
                        lambda d: ([dict(g) for g in slates.get(d, [])], "cards.csv", "recs.json"))
    monkeypatch.setattr(cards, "_games_from_public_scoreboard", lambda _d: ([], ""))
    monkeypatch.setattr(cards, "_public_scoreboard_live_state_payload", lambda _d: None)
    monkeypatch.setattr(cards, "_supplement_games_with_live_state", lambda games, _d, **_k: (games, None, 0, 0))
    monkeypatch.setattr(cards, "_games_from_live_state_fallback", lambda _d, ttl=12: ([], ""))
    monkeypatch.setattr(cards, "_render_web_dyno", lambda: False)
    monkeypatch.setattr(cards, "_cache_get_context", lambda _k: None)
    monkeypatch.setattr(cards, "_cache_set_context", lambda *_a, **_k: None, raising=False)
    monkeypatch.setattr(cards, "_game_cards_or_live_state_signature", lambda _p: None)
    monkeypatch.setattr(cards, "_path_cache_signature", lambda _p: None)
    monkeypatch.setattr(cards, "_wnba_live_cache_bucket", lambda _d: None)
    monkeypatch.setattr(cards, "_build_wnba_game_lens", lambda _g: {})
    monkeypatch.setattr(cards, "_attach_wnba_momentum", lambda *_a, **_k: None)
    monkeypatch.setattr(cards, "apply_game_board_contract", lambda payload, **_k: dict(payload))
    monkeypatch.setattr(cards, "_wnba_advanced_contract", lambda **_k: {})
    monkeypatch.setattr(cards, "publish_cards_page_context", lambda *_a, **_k: None)
    monkeypatch.setattr(cards, "_maybe_persist_current_day_live_snapshot_artifact", lambda _k, _d, payload: payload)
    yield slates
    sources._HAS_GAMES_CONFIRMED_TRUE_CACHE.clear()
    cards._BUILD_CARDS_PAGE_CONTEXT_CACHE.clear()
    cards.build_live_state_payload.cache_clear()


@pytest.fixture
def writer(monkeypatch):
    spec = importlib.util.spec_from_file_location("test_wnba_future_seed_refresh", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    writes = {}
    real_local = module._build_local_live_snapshot_payload

    def _local(*, kind, date_str, event_ids):
        return real_local(kind=kind, date_str=date_str, event_ids=event_ids) if kind == "live_state" else None

    monkeypatch.setattr(module, "_keyvalue_write_json_file", lambda path, record: writes.__setitem__(Path(path).name, record))
    monkeypatch.setattr(module, "_keyvalue_read_json_file", lambda _path: None)
    monkeypatch.setattr(module, "_source_app_fallback_enabled", lambda: False)
    monkeypatch.setattr(module, "_build_local_live_snapshot_payload", _local)
    monkeypatch.setattr(module, "_build_source_live_lines_payload", lambda **_k: None)
    monkeypatch.setattr(module, "_build_bundle_local_live_snapshot_payload", lambda **_k: None)
    monkeypatch.setattr(module, "_build_bundle_local_live_player_lens_payload", lambda **_k: None)
    return module, writes


def _export(module, tmp_path, date_str):
    return module._export_live_snapshot_artifacts(
        source_root=tmp_path / "source", date_str=date_str, processed_root=tmp_path / "artifact" / "data" / "processed")


def _saved_ids(writes, date_str):
    record = writes.get(f"live_state_{date_str}.jsonl")
    games = ((record or {}).get("payload") or {}).get("games") or []
    return sorted(str(g.get("event_id")) for g in games)


def test_the_look_ahead_writer_does_not_save_the_last_slate_under_tomorrow(eve_of_a_no_game_day, writer, tmp_path):
    module, writes = writer
    assert module._build_local_live_snapshot_payload is not cards.build_live_state_payload  # the wrapper, delegating
    copied = _export(module, tmp_path, TOMORROW)
    assert _saved_ids(writes, TOMORROW) == []
    assert "live_state_path" not in copied


def test_the_look_ahead_writer_still_saves_tomorrows_own_slate(eve_of_a_no_game_day, writer, tmp_path):
    """No false negative: 09-17 has a real slate, and its own cards are the ones saved."""
    eve_of_a_no_game_day[TOMORROW] = [_game(TOMORROW_IDS[0], "PHX", "LVA")]
    module, writes = writer
    _export(module, tmp_path, TOMORROW)
    assert _saved_ids(writes, TOMORROW) == TOMORROW_IDS


def test_a_past_date_still_recovers_a_missing_artifact(eve_of_a_no_game_day):
    """The fallback's documented purpose is kept: a past date with no artifact recovers the stored slate."""
    context = cards._build_cards_page_context_uncached(PAST, allow_stored_date_fallback=True)
    assert context["date"] == LAST_SLATE
    assert sorted(g["event_id"] for g in context["games"]) == PHANTOM_IDS
