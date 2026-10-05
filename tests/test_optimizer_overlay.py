"""Phase 2 of lane `daily-optimizer`: the overlay reaches RANK and STAKE, and only lowers them.

Reachability first (model engine standard, `off != on`): the same row through the real
`layer2_board._apply_skill_reliability` and `portfolio_commit._sizing_skill_factor`, with and without
a validated overlay on disk.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from syndicate.features.shared import daily_optimizer as opt
from syndicate.features.shared import optimizer_overlay as oo
from syndicate.features.shared import layer2_board as lb
from syndicate.features.shared import portfolio_commit as pc

NOW = datetime.now(timezone.utc)
CELL = "nfl|player_reception_yds|full|pregame"


def _row() -> dict:
    return {"sport": "nfl", "market": "player_reception_yds", "segment": "full", "game_state": "pregame",
            "commence_time": (NOW + timedelta(hours=20)).isoformat(), "model_edge_pct": 6.0,
            "quote": {"fair_probability": 0.5, "book_age_seconds": 30, "books_quoting": 6, "fair_method": "consensus"},
            "projection": {}}


def _overlay(shrink: float | None = 0.7, scale: float | None = None, *, hours: int = 72) -> dict:
    entry = lambda f: {"factor": f, "games": 120, "dates": 9}
    return {"source": opt.SOURCE, "generated_at": NOW.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "expires_at": (NOW + timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "edge_shrink": {CELL: entry(shrink)} if shrink is not None else {},
            "stake_scale": {CELL: entry(scale)} if scale is not None else {}}


@pytest.fixture()
def disk(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path))
    monkeypatch.delenv(oo.ENV_SWITCH, raising=False)
    monkeypatch.setattr(oo, "_overlay_file", lambda: tmp_path / opt.OVERLAY_PATH)
    oo.reset_cache()
    yield tmp_path
    oo.reset_cache()


def _write(root, payload) -> None:
    path = root / opt.OVERLAY_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    oo.reset_cache()


def test_the_row_resolves_to_the_scorecard_cell():
    assert oo.cell_of_row(_row()) == CELL


def test_reachability_rank_and_stake_move_only_with_a_validated_overlay(disk):
    score = {"score": 10.0, "value_pct": 4.0}
    assert lb._apply_skill_reliability(score, {}, row=_row()) == score
    assert pc._sizing_skill_factor(_row()) == 1.0

    _write(disk, _overlay(shrink=0.7))
    ranked = lb._apply_skill_reliability(score, {}, row=_row())
    assert ranked["score"] == 7.0 and ranked["optimizer_factor"] == 0.7
    assert ranked["value_pct"] == 4.0, "admission reads value_pct: it must never move"
    assert "skill_reliability" not in ranked, "the category term did not bite, so it is not stamped"
    assert pc._sizing_skill_factor(_row()) == pytest.approx(0.7)


def test_the_kill_switch_restores_byte_identical_behaviour(disk, monkeypatch):
    _write(disk, _overlay(shrink=0.6))
    monkeypatch.setenv(oo.ENV_SWITCH, "off")
    oo.reset_cache()
    score = {"score": 10.0}
    assert lb._apply_skill_reliability(score, {}, row=_row()) == score
    assert pc._sizing_skill_factor(_row()) == 1.0


def test_an_expired_or_out_of_rails_overlay_is_ignored(disk):
    _write(disk, _overlay(shrink=0.6, hours=-1))
    assert oo.factor_for_row(_row()) == 1.0 and oo.status()["reason"] == "expired"
    _write(disk, _overlay(shrink=1.4))
    assert oo.factor_for_row(_row()) == 1.0
    _write(disk, _overlay(shrink=0.2))
    assert oo.factor_for_row(_row()) == 1.0


def test_two_factors_combine_but_never_below_the_floor(disk):
    _write(disk, _overlay(shrink=0.6, scale=0.6))
    assert oo.factor_for_row(_row()) == opt.FACTOR_FLOOR
    _write(disk, _overlay(shrink=0.9, scale=0.9))
    assert oo.factor_for_row(_row()) == pytest.approx(0.81)


def test_a_negative_score_is_never_raised(disk):
    _write(disk, _overlay(shrink=0.5))
    assert lb._apply_skill_reliability({"score": -4.0}, {}, row=_row())["score"] == -4.0


def test_another_cell_is_untouched(disk):
    _write(disk, _overlay(shrink=0.5))
    other = dict(_row(), market="player_rush_yds")
    assert oo.factor_for_row(other) == 1.0


def test_the_cron_writes_the_consumer_overlay_beside_the_report(tmp_path):
    report, overlay = opt.build_report(opt.empty_state("sig"), today="2026-10-05", now=NOW, resamples=20)
    table, why = opt.validate_overlay(json.loads(opt.dumps(overlay)), now=NOW)
    assert why == "ok" and table == {"edge_shrink": {}, "stake_scale": {}}
