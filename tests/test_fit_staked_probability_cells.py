"""`scripts/fit_staked_probability_cells.py` -- the per venue x sport x market x segment x phase fit.

Lane `sim-stake-earned-profile` (2026-10-22). Synthetic ledgers with a KNOWN truth: an
informative model earns beta > 0 through the event-bootstrap gate; a noise model does not.
Then the structural rules the pre-registration names: phases never pool, unknown is never
written, diagnostics never written, and the candidate key's reachability through the REAL sizer.
"""

from __future__ import annotations

import json
import math
import random

import pytest

from scripts import fit_staked_probability_cells as cells
from syndicate.features.shared.portfolio_commit import sizing_inputs_with_provenance
from syndicate.features.shared.staked_probability_profile import (
    PROFILE_PATH_ENV,
    UNFITTED_MODE_ENV,
    cell_key,
    clear_profile_cache,
    load_staked_probability_profile,
)


def _expit(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def _logit(p: float) -> float:
    return math.log(p / (1.0 - p))


def _american_for(prob: float) -> float:
    decimal = (1.0 / prob) * 1.02
    if decimal >= 2.0:
        return round((decimal - 1.0) * 100.0)
    return -round(100.0 / (decimal - 1.0))


def ledger(*, n: int, model: str, seed: int = 11, sport: str = "nba", book: str = "prophetx",
           start_day: int = 21, dates: int = 30, month: str = "2026-10", per_event: int = 4) -> list[dict]:
    """Orders on `n // per_event` events. `informative`: model == truth. `noise`: market + noise."""
    rng = random.Random(seed)
    out = []
    for i in range(n):
        event = i // per_event
        truth = rng.uniform(0.35, 0.65)
        market = _expit(_logit(truth) + rng.gauss(0.0, 0.6))
        model_p = truth if model == "informative" else _expit(_logit(market) + rng.gauss(0.0, 0.6))
        price = _american_for(market)
        profit = 100.0 / abs(price) if price < 0 else price / 100.0
        ev_pct = (market * (profit + 1.0) - 1.0) * 100.0
        day = start_day + (event * dates) // max(1, n // per_event)
        y, m = month.split("-")
        mm, dd = int(m), day
        while dd > 31:
            dd -= 31
            mm += 1
        date = f"{y}-{mm:02d}-{dd:02d}"
        out.append({
            "sport": sport,
            "market": "h2h",
            "segment": "full",
            "book": book,
            "venue": "paper",
            "event_id": f"{sport}-{book}-{seed}-{event}",
            "requested_price": price,
            "ev_pct": round(ev_pct, 4),
            "model_edge_pct": round(max(-15.0, min(15.0, (model_p - market) * 100.0)), 4),
            "outcome": "won" if rng.random() < truth else "lost",
            "selected_date": date,
            "submitted_at": f"{date}T18:00:{i % 60:02d}Z",
            "fill_stake_dollars": 5.0,
        })
    return out


def _fit(records, **kw):
    rows, _ = cells.rows_from_records(records)
    return cells.fit_all(rows, draws=kw.pop("draws", 200), **kw)


# ---------------------------------------------------------------------------
# the cell
# ---------------------------------------------------------------------------


def test_cell_carries_venue_and_phase_and_never_pools_phases():
    pre = ledger(n=40, model="noise", start_day=5, dates=10)    # nba 10-05..10-15 = preseason
    reg = ledger(n=40, model="noise", start_day=21, dates=8)    # nba 10-21.. = regular
    rows, _ = cells.rows_from_records(pre + reg)
    keys = {r["cell"] for r in rows}
    assert keys == {"prophetx|nba|h2h|full|preseason", "prophetx|nba|h2h|full|regular"}


def test_unknown_phase_is_its_own_cell_and_never_written():
    # nba in July: no window -> unknown, NOT regular
    records = ledger(n=1400, model="informative", month="2026-07", start_day=1, dates=28)
    results = _fit(records)
    (cell, result), = results.items()
    assert cell.endswith("|unknown")
    assert result["verdict"] == cells.VERDICT_UNKNOWN_PHASE
    doc = cells.candidate_profile(results, fitted_on="t", source="test")
    assert doc["fields"]["cells"] == {}


def test_event_is_the_cluster_with_fallbacks():
    assert cells.event_of({"event_id": "E1", "game_pk": 9}) == "e1"
    assert cells.event_of({"event_id": None, "game_pk": 776}) == "776"
    assert cells.event_of({"opening_key": "event_id=abc|market=h2h"}) == "abc"


def test_portfolio_book_only():
    records = ledger(n=10, model="noise")
    shadow = [{**r, "venue": "paper:kalshi"} for r in records]
    rows, dropped = cells.rows_from_records(records + shadow)
    assert len(rows) == 10 and dropped["not_portfolio_book"] == 10


# ---------------------------------------------------------------------------
# the gates
# ---------------------------------------------------------------------------


def test_informative_model_earns_beta_through_the_event_bootstrap_gate():
    results = _fit(ledger(n=1400, model="informative"))
    (cell, result), = results.items()
    assert cell == "prophetx|nba|h2h|full|regular"
    assert result["verdict"] == cells.VERDICT_WRITE
    assert result["beta_fit"] > 0.0
    assert result["delta_fit_ci"][0] > 0.0
    assert result["beta_ci"][0] > 0.0
    doc = cells.candidate_profile(results, fitted_on="t", source="test")
    assert doc["fields"]["cells"][cell]["beta"] == result["beta_fit"]
    assert doc["fields"]["cells"][cell]["market_only"] is False


def test_noise_model_is_not_written_with_beta():
    results = _fit(ledger(n=1400, model="noise"))
    (cell, result), = results.items()
    assert result["verdict"] != cells.VERDICT_WRITE
    doc = cells.candidate_profile(results, fitted_on="t", source="test")
    written = doc["fields"]["cells"].get(cell)
    assert written is None or (written["beta"] == 0.0 and written["market_only"] is True)


def test_floors_and_diagnostic_rows_are_never_written():
    thin = ledger(n=400, model="informative")  # ~120 held out: below the 200 floor
    results = _fit(thin, diagnostic=True)
    (cell, result), = results.items()
    assert result["verdict"] == "refused_n_test_below_floor"
    assert result.get("diagnostic") is True and result["beta_fit"] is not None
    assert cells.candidate_profile(results, fitted_on="t", source="test")["fields"]["cells"] == {}


def test_event_floor_refuses_a_cell_with_many_rows_on_few_events():
    records = ledger(n=1400, model="informative", per_event=60)  # ~24 events in all
    (_, result), = _fit(records).items()
    assert result["verdict"] == cells.VERDICT_EVENT_FLOOR


def test_pooled_venue_grain_is_never_written():
    rows, _ = cells.rows_from_records(ledger(n=1400, model="informative"))
    results = cells.fit_all(cells.pooled_venue_rows(rows), draws=200)
    (cell, result), = results.items()
    assert cell.startswith("*|") and result["verdict"] == cells.VERDICT_WRITE
    assert cells.candidate_profile(results, fitted_on="t", source="test")["fields"]["cells"] == {}


def test_candidate_document_loads_through_the_real_store(tmp_path):
    results = _fit(ledger(n=1400, model="informative"))
    path = tmp_path / "candidate.json"
    path.write_text(json.dumps(cells.candidate_profile(results, fitted_on="t", source="test")), encoding="utf-8")
    clear_profile_cache()
    profile, meta = load_staked_probability_profile(path)
    assert meta["source"] == "artifact"
    assert profile.version.startswith("staked_probability_cells_v1@")
    assert set(profile.cells) == {"prophetx|nba|h2h|full|regular"}


# ---------------------------------------------------------------------------
# REACHABILITY through the real sizer (off != on), and the reader gap (findings s5)
# ---------------------------------------------------------------------------


def _row():
    return {
        "sport": "nba", "event_id": "evt-1", "kind": "game", "market": "h2h", "segment": "full",
        "line": None, "player_name": None, "home_team": "Home", "away_team": "Away",
        "commence_time": "2026-10-25T23:05:00Z", "selected_date": "2026-10-25", "side": "home",
        "quote": {"price": -110, "bookmaker": "prophetx"}, "ev_pct": 4.5, "model_edge_pct": 3.2,
        "score": {"score": 5.1, "price_reliability": 0.82},
    }


def _profile(tmp_path, key, beta=0.5):
    path = tmp_path / f"p_{abs(hash(key))}.json"
    path.write_text(json.dumps({"version": "sp-test", "fields": {"cells": {key: {"beta": beta}}}}), encoding="utf-8")
    return path


@pytest.fixture
def _sizer_env(monkeypatch):
    monkeypatch.delenv(UNFITTED_MODE_ENV, raising=False)
    monkeypatch.delenv("SYNDICATE_KELLY_ON_FAIR", raising=False)
    monkeypatch.delenv("SYNDICATE_PREGAME_INTERVAL_GATE", raising=False)
    clear_profile_cache()
    yield monkeypatch
    clear_profile_cache()


def _staked(monkeypatch, path):
    monkeypatch.setenv(PROFILE_PATH_ENV, str(path))
    clear_profile_cache()
    inputs, refusal, prov = sizing_inputs_with_provenance(_row())
    assert refusal is None
    return inputs.model_probability, prov


def test_reachability_reader_key_off_differs_from_on(tmp_path, _sizer_env):
    off, prov_off = _staked(_sizer_env, tmp_path / "absent.json")
    on, prov_on = _staked(_sizer_env, _profile(tmp_path, cell_key("nba", "h2h", "full")))
    assert off != on
    assert prov_on["blend_beta"] == 0.5 and prov_off["blend_beta"] == 0.0
    assert prov_on["staked_probability_version"] == "sp-test"


def test_five_part_candidate_key_is_inert_to_todays_reader(tmp_path, _sizer_env):
    """The reader keys sport|market|segment. A venue|...|phase cell is NOT read -- the candidate
    profile is inert until the reader learns the longer key (findings s5). This test pins that
    gap so the day the reader changes, it fails and is updated on purpose."""
    off, _ = _staked(_sizer_env, tmp_path / "absent.json")
    on, prov = _staked(_sizer_env, _profile(tmp_path, "prophetx|nba|h2h|full|regular"))
    assert off == on
    assert prov["blend_beta"] == 0.0 and prov["staked_probability_version"] == "unfitted"


def test_failed_ledger_read_refuses_instead_of_fitting_the_archive_alone(monkeypatch):
    """findings s7: a keyvalue read that FAILS reads as an empty live document; the harness must
    refuse (exit 4) rather than fit the archive alone and look complete."""
    from syndicate.features.shared import refresh_state_store

    monkeypatch.setattr(refresh_state_store, "read_json_file_result", lambda path: (None, False))
    called = []
    monkeypatch.setattr(cells.base, "load_ledger_records", lambda: called.append(1) or ([], "x"))
    assert cells.main(["coverage"]) == 4
    assert called == []
