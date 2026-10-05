"""`daily_optimizer` -- calibration fit, recommendation grade, the overlay's rails, and that the cron reaches it.

Lane `daily-optimizer` `[2026-10-05]`. Reachability first (model engine standard): the cron run with
`--optimizer on` must produce a published-recommendation grade that `--optimizer off` does not.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import random
from datetime import datetime, timedelta, timezone

import pytest

from syndicate.features.shared import daily_optimizer as opt

NOW = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)
CELL = "nba|player_points|full|pregame"


def _games(*, true_w: float, n_games: int = 90, n_dates: int = 9, rows: int = 12, seed: int = 7,
           sport_cell: str = CELL) -> list[dict]:
    """Games whose model edge is 1/true_w times too big: the market is right, the model exaggerates."""
    rng = random.Random(seed)
    games = []
    for g in range(n_games):
        graded = []
        for _ in range(rows):
            market = rng.uniform(0.3, 0.7)
            truth = min(0.95, max(0.05, market + rng.uniform(-0.15, 0.15)))
            model = market + (truth - market) / true_w
            y = 1.0 if rng.random() < truth else 0.0
            graded.append({"buckets": [f"{sport_cell}|disagreement=2-5"], "p_model": model, "p_market": market, "y": y,
                           "price": 100, "pnl": 1.0 if y else -1.0})
        cal, bands = opt.accumulate(graded)
        games.append({"key": f"nba|e{g}", "date": f"2026-09-{10 + g % n_dates:02d}", "sport": "nba",
                      "cal": cal, "pool": bands, "rec": bands})
    return games


def test_an_overconfident_model_is_found_and_shrunk_but_only_to_the_ci_upper_and_never_below_the_floor():
    [result] = opt.fit_calibration(_games(true_w=0.4), resamples=400)
    assert result["verdict"] == "overconfident"
    assert 0.2 < result["w"] < 0.7
    assert result["ci95"][1] < 1.0
    assert result["edge_shrink"] == max(opt.FACTOR_FLOOR, result["ci95"][1])
    assert opt.FACTOR_FLOOR <= result["edge_shrink"] < 1.0


def test_a_well_calibrated_model_gets_no_entry():
    [result] = opt.fit_calibration(_games(true_w=1.0), resamples=400)
    assert result["verdict"] == "not_proven" and result["edge_shrink"] is None


def test_too_few_games_is_insufficient_whatever_the_point_estimate():
    [result] = opt.fit_calibration(_games(true_w=0.3, n_games=20, n_dates=3), resamples=200)
    assert result["verdict"] == "insufficient" and result["edge_shrink"] is None


def test_the_fit_does_not_depend_on_the_order_games_were_read():
    games = _games(true_w=0.5)
    first = opt.fit_calibration(games, resamples=300)
    shuffled = list(games)
    random.Random(3).shuffle(shuffled)
    assert opt.fit_calibration(shuffled, resamples=300) == first


def test_ev_bands_cover_every_value_once():
    assert [opt.ev_band(v) for v in (-3, 0, 1.99, 2, 7, 10, 40)] == [
        "ev<0", "ev0-2", "ev0-2", "ev2-5", "ev5-10", "ev10+", "ev10+"]


def test_published_bets_that_realise_below_their_predicted_ev_get_a_bounded_stake_scale():
    rng = random.Random(11)
    games = []
    for g in range(80):
        rows = []
        for _ in range(10):
            y = 1.0 if rng.random() < 0.40 else 0.0  # priced at +150 against a 0.46 fair: predicted +15%, real -0%
            rows.append({"buckets": [f"{CELL}|x=y"], "p_model": 0.5, "p_market": 0.46, "y": y, "price": 150,
                         "pnl": 1.5 if y else -1.0})
        games.append({"key": f"k{g}", "date": f"2026-09-{10 + g % 8:02d}", "rec": opt.accumulate(rows)[1]})
    rec = opt.grade_bands(games, "rec", resamples=400)
    scales = opt.stake_scales(rec)
    assert CELL in scales
    assert opt.FACTOR_FLOOR <= scales[CELL]["factor"] < 1.0


def test_overlay_round_trips_through_the_consumer_validator_and_every_rail_rejects():
    calibration = opt.fit_calibration(_games(true_w=0.4), resamples=300)
    overlay = opt.overlay_payload(calibration, {}, now=NOW, window="28d")
    table, why = opt.validate_overlay(overlay, now=NOW)
    assert why == "ok" and CELL in table["edge_shrink"] and table["stake_scale"] == {}
    assert overlay["rails"]["applies_to"] == "rank_and_stake_only"

    def broken(mutate):
        payload = json.loads(json.dumps(overlay))
        mutate(payload)
        return opt.validate_overlay(payload, now=NOW)[1]

    assert broken(lambda p: p["edge_shrink"][CELL].update(factor=1.2)) == "edge_shrink_factor_out_of_rails"
    assert broken(lambda p: p["edge_shrink"][CELL].update(factor=0.1)) == "edge_shrink_factor_out_of_rails"
    assert broken(lambda p: p["edge_shrink"][CELL].update(factor=0.0)) == "edge_shrink_factor_out_of_rails"
    assert broken(lambda p: p["edge_shrink"][CELL].update(games=10)) == "edge_shrink_below_sample_floor"
    assert broken(lambda p: p.update(source="hand_edited")) == "unknown_source"
    assert opt.validate_overlay(overlay, now=NOW + timedelta(hours=opt.OVERLAY_TTL_HOURS + 1))[1] == "expired"


def test_an_unreadable_openings_ledger_marks_the_game_unknown_not_unpublished():
    state = opt.empty_state("sig")
    records = [{"k": "a", "sport": "mlb"}]
    opt.note_published(state, "2026-10-04", records, None, game_key=lambda r: "mlb|1")
    assert state["pub"]["mlb|1"]["known"] is False
    opt.note_published(state, "2026-10-04", [{"k": "b"}], {"b"}, game_key=lambda r: "mlb|2")
    assert state["pub"]["mlb|2"] == {"known": True, "keys": ["b"], "seen": "2026-10-04"}
    opt.note_published(state, "2026-10-04", [{"k": "c"}], {"c"}, game_key=lambda r: "mlb|3", pending={"mlb|9": []})
    assert "mlb|3" not in state["pub"], "a game the scorecard already graded is not noted"


def test_wrap_grade_returns_exactly_what_grade_returns_and_grades_published_rows_separately():
    calls = []

    def grade(records, chips, **kw):
        calls.append([r["k"] for r in records])
        return ([{"buckets": [f"{CELL}|x=y"], "p_model": 0.6, "p_market": 0.5, "y": 1.0, "price": 100, "pnl": 1.0}
                 for _ in records], {"why": 1})

    state = opt.empty_state("sig")
    state["pub"]["nba|1"] = {"known": True, "keys": ["b"], "seen": "2026-10-04"}
    wrapped = opt.wrap_grade(grade, state, game_key=lambda r: "nba|1")
    records = [{"k": "a"}, {"k": "b"}]
    graded, ungraded = wrapped(records, {}, today="2026-10-05", ungraded_by_sport={})
    assert graded == grade(records, {})[0] and ungraded == {"why": 1}
    assert calls[1] == ["b"], "the second grade sees ONLY the published rows"
    entry = state["candidates"]["nba|1"]
    assert entry["pub_known"] and entry["rec"][f"{CELL}|all"][0] == 1 and entry["pool"][f"{CELL}|all"][0] == 2

    # commit keeps only what the scorecard committed
    assert opt.commit(state, {"nba|1": {"date": "2026-10-04"}}) == {"committed": 1, "with_published": 1}
    assert "nba|1" in state["games"] and "nba|1" not in state["pub"] and "candidates" not in state


def test_wrap_grade_never_breaks_the_scorecard_when_accumulation_fails():
    state = opt.empty_state("sig")
    wrapped = opt.wrap_grade(lambda records, chips, **kw: ([{"buckets": 5}], {}), state, game_key=lambda r: "x|1")
    assert wrapped([{"k": "a"}], {}) == ([{"buckets": 5}], {})


def test_state_resets_on_a_new_grader_and_drops_only_the_changed_sport():
    saved = opt.empty_state("old", {"mlb": "1", "nba": "1"})
    saved["games"] = {"mlb|1": {"sport": "mlb"}, "nba|1": {"sport": "nba"}}
    state, reason = opt.load_state(json.loads(json.dumps(saved)), "new", sport_versions={"mlb": "1", "nba": "1"})
    assert reason == "grader_signature_changed" and state["games"] == {}
    state, reason = opt.load_state(json.loads(json.dumps(saved)), "old", sport_versions={"mlb": "1", "nba": "2"})
    assert reason == "sport_versions_changed:nba" and list(state["games"]) == ["mlb|1"]


# ---------------------------------------------------------------------------
# reachability: the cron
# ---------------------------------------------------------------------------

_SRC = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "publish_model_scorecard.py"


@pytest.fixture()
def cron(monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location("publish_model_scorecard_opt", _SRC)
    pms = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pms)
    bs = pms.msc.load_bucket_search()
    yesterday = (datetime.now(timezone.utc) - timedelta(days=2)).strftime("%Y-%m-%dT18:00:00Z")
    opening = {"key": "o1", "sport": "mlb", "event_id": "ev1", "market": "h2h", "side": "home", "kind": "game_line",
               "commence_time": yesterday, "home_team": "A", "away_team": "B", "price": 110,
               "fair_probability": 0.5, "fair_method": "consensus", "model_edge_pct": 3.0, "captured_at": yesterday}
    published = bs.records_from_openings([opening])[0]
    unpublished = dict(published, k=published["k"].replace("home", "away"))
    assert published["k"] != unpublished["k"]

    def fake_grade_population(records, chips, *a, **kw):
        return ([{"buckets": [f"mlb|h2h|full|pregame|x=y"], "y": 1.0, "p_market": 0.5, "p_model": 0.53,
                  "price": 110, "pnl": 1.1} for _ in records], {})

    monkeypatch.setattr(pms, "admin_token", lambda: "t")
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(pms.WebReader, "json", lambda self, relative: None)
    monkeypatch.setattr(pms.WebReader, "bytes", lambda self, relative: None)
    monkeypatch.setattr(pms.WebReader, "text",
                        lambda self, relative: json.dumps(opening) + "\n" if "clv_openings" in relative else None)
    monkeypatch.setattr(pms, "fetch_board_date", lambda reader, b, day, sports: ([published, unpublished], {"mlb": 1}))
    monkeypatch.setattr(pms, "fetch_chips_with_retry", lambda b, day: [])
    monkeypatch.setattr(pms, "grader_signature", lambda b, s: ("sig", {}, {}))
    monkeypatch.setattr(bs, "grade_population", fake_grade_population)
    monkeypatch.setattr(pms.msc, "load_bucket_search", lambda: bs)
    monkeypatch.setattr(pms.msc, "build_scorecard", lambda state, **kw: (
        {"windows": {}, "overlay": {}, "generated_at": "x"}, {"buckets": {}, "buckets_validated": 0}))
    monkeypatch.setattr(pms.msc, "markdown", lambda scorecard: "")
    return pms, tmp_path


def test_reachability_the_cron_grades_published_recommendations_only_when_the_optimizer_is_on(cron):
    pms, root = cron
    assert pms.main(["--weekly", "off", "--sports", "mlb", "--resamples", "50"]) == 0
    report = json.loads((root / opt.OPTIMIZER_PATH).read_text(encoding="utf-8"))
    mlb = report["by_sport"]["mlb"]
    assert mlb["games"] == 1 and mlb["games_with_published_known"] == 1
    assert mlb["recommended"]["bets"] == 1 and mlb["pooled"]["bets"] == 2
    assert json.loads((root / opt.OPT_STATE_PATH).read_text(encoding="utf-8"))["games"]
    scorecard = json.loads((root / pms.msc.LATEST_PATH).read_text(encoding="utf-8"))
    assert scorecard["optimizer"]["by_sport"]["mlb"]["recommended"]["bets"] == 1


def test_reachability_off_writes_nothing_of_the_optimizer(cron):
    pms, root = cron
    assert pms.main(["--weekly", "off", "--sports", "mlb", "--optimizer", "off", "--resamples", "50"]) == 0
    assert not (root / opt.OPTIMIZER_PATH).exists()
    assert "optimizer" not in json.loads((root / pms.msc.LATEST_PATH).read_text(encoding="utf-8"))
