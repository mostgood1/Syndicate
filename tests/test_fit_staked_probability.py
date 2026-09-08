"""`scripts/fit_staked_probability.py` -- the harness that fits the blend.

Synthetic ledgers with a KNOWN truth: a market that is a noisy view of the
true probability, and a model that is either informative (beta > 0 should
win out of sample) or pure noise around the market (beta = 0 should win, and
the harness must refuse to write). Plus the pre-registered floor.
"""

from __future__ import annotations

import json
import math
import random

import pytest

from scripts import fit_staked_probability as harness
from syndicate.features.shared.staked_probability_profile import (
    cell_key,
    clear_profile_cache,
    load_staked_probability_profile,
)


def _expit(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def _logit(p: float) -> float:
    return math.log(p / (1.0 - p))


def _american_for(prob: float) -> float:
    """A price a touch better than `prob`, so ev_pct is small and positive."""
    fair_decimal = 1.0 / prob
    decimal = fair_decimal * 1.02
    if decimal >= 2.0:
        return round((decimal - 1.0) * 100.0)
    return -round(100.0 / (decimal - 1.0))


def synthetic_ledger(*, n: int, model: str, seed: int = 7, sport: str = "mlb", dates: int = 30) -> list[dict]:
    """`model="informative"`: the model IS the true probability. `model="noise"`:
    the model is the market plus noise, i.e. worthless."""
    rng = random.Random(seed)
    rows = []
    for i in range(n):
        truth = rng.uniform(0.35, 0.65)
        market = _expit(_logit(truth) + rng.gauss(0.0, 0.6))
        if model == "informative":
            model_p = truth
        else:
            model_p = _expit(_logit(market) + rng.gauss(0.0, 0.6))
        price = _american_for(market)
        profit = 100.0 / abs(price) if price < 0 else price / 100.0
        ev_pct = (market * (profit + 1.0) - 1.0) * 100.0  # so fair back-derives to `market`
        edge = max(-15.0, min(15.0, (model_p - market) * 100.0))
        day = 1 + (i * dates) // n
        rows.append(
            {
                "sport": sport,
                "market": "h2h",
                "segment": "full_game",
                "venue": "paper",
                "requested_price": price,
                "ev_pct": round(ev_pct, 4),
                "model_edge_pct": round(edge, 4),
                "outcome": "won" if rng.random() < truth else "lost",
                "selected_date": f"2026-08-{day:02d}",
                "submitted_at": f"2026-08-{day:02d}T18:00:{i % 60:02d}Z",
            }
        )
    return rows


def _jsonl(tmp_path, rows, name="rows.jsonl"):
    path = tmp_path / name
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return path


@pytest.fixture(autouse=True)
def _fresh_cache():
    clear_profile_cache()
    yield
    clear_profile_cache()


# ---------------------------------------------------------------------------


def test_the_split_is_chronological_and_never_cuts_a_date():
    rows = synthetic_ledger(n=1000, model="informative")
    derived = [harness.derive_row(r)[0] for r in rows]
    train, test = harness.chronological_split(derived)
    assert train and test
    assert max(r["date"] for r in train) < min(r["date"] for r in test)
    assert 0.6 < len(train) / len(derived) < 0.8


def test_the_floor_refuses_by_name_and_writes_nothing(tmp_path, capsys):
    rows = synthetic_ledger(n=300, model="informative")  # ~90 held-out rows
    out = tmp_path / "profile.json"
    code = harness.main(["--sport", "mlb", "--rows-jsonl", str(_jsonl(tmp_path, rows)), "--write", "--profile-path", str(out)])
    assert code == 2
    assert not out.exists()
    printed = capsys.readouterr().out
    assert harness.VERDICT_FLOOR in printed
    assert f"n_test >= {harness.MIN_TEST_ROWS}" in printed
    assert harness.MIN_TEST_ROWS == 200  # pre-registered; changing it is a decision, not a tidy-up


def test_an_informative_model_earns_a_positive_beta_and_is_written(tmp_path, capsys):
    rows = synthetic_ledger(n=1500, model="informative")
    out = tmp_path / "profile.json"
    path = _jsonl(tmp_path, rows)

    # Dry run first: reports, writes nothing.
    assert harness.main(["--sport", "mlb", "--rows-jsonl", str(path), "--profile-path", str(out)]) == 0
    assert not out.exists()
    assert "DRY RUN" in capsys.readouterr().out

    assert harness.main(["--sport", "mlb", "--rows-jsonl", str(path), "--write", "--profile-path", str(out)]) == 0
    assert out.exists()
    payload = json.loads(out.read_text(encoding="utf-8"))
    cell = payload["fields"]["cells"][cell_key("mlb", "h2h", "full_game")]
    assert cell["beta"] > 0.0
    assert cell["n_test"] >= harness.MIN_TEST_ROWS
    assert cell["brier_fit"] < cell["brier_beta0"]
    assert cell["fitted_on"] and cell["source"].startswith("jsonl:")
    assert payload["fit_from"]["scorer"] == harness.SCORER
    assert payload["fit_from"]["min_test_rows"] == 200

    profile, meta = load_staked_probability_profile(out)
    assert meta["source"] == "artifact"
    assert profile.beta_for("mlb", "h2h", "full_game") == cell["beta"]


def test_a_noise_model_does_not_beat_the_market_and_is_refused(tmp_path, capsys):
    rows = synthetic_ledger(n=1500, model="noise")
    out = tmp_path / "profile.json"
    code = harness.main(["--sport", "mlb", "--rows-jsonl", str(_jsonl(tmp_path, rows)), "--write", "--profile-path", str(out)])
    assert code == 2
    assert not out.exists()
    printed = capsys.readouterr().out
    assert harness.VERDICT_NO_GAIN in printed
    # The comparison is printed either way.
    assert "B(0)" in printed and "B(fit)" in printed


def test_no_usable_rows_exits_3(tmp_path):
    rows = synthetic_ledger(n=50, model="informative", sport="nba")
    code = harness.main(["--sport", "mlb", "--rows-jsonl", str(_jsonl(tmp_path, rows)), "--write", "--profile-path", str(tmp_path / "p.json")])
    assert code == 3
    assert not (tmp_path / "p.json").exists()


def test_pushes_and_modelless_rows_are_dropped_by_name():
    row = synthetic_ledger(n=1, model="informative")[0]
    assert harness.derive_row({**row, "outcome": "push"}) == (None, "push")
    assert harness.derive_row({**row, "model_edge_pct": None}) == (None, "no_model_edge_pct")
    assert harness.derive_row({**row, "outcome": None}) == (None, "unsettled")


def test_a_write_replaces_the_sports_cells_and_keeps_other_sports(tmp_path):
    out = tmp_path / "profile.json"
    out.write_text(
        json.dumps(
            {
                "version": "old",
                "fields": {
                    "cells": {
                        cell_key("mlb", "totals", "1st_5"): {"beta": 0.9, "source": "stale"},
                        cell_key("nba", "h2h", "full_game"): {"beta": 0.4, "source": "other-sport"},
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    rows = synthetic_ledger(n=1500, model="informative")
    assert harness.main(["--sport", "mlb", "--rows-jsonl", str(_jsonl(tmp_path, rows)), "--write", "--profile-path", str(out)]) == 0
    cells = json.loads(out.read_text(encoding="utf-8"))["fields"]["cells"]
    assert cell_key("mlb", "totals", "1st_5") not in cells  # stale mlb cell gone, not merged beside
    assert cells[cell_key("nba", "h2h", "full_game")]["beta"] == 0.4  # untouched
    assert cell_key("mlb", "h2h", "full_game") in cells


def test_the_ledger_path_filters_to_the_portfolio_book(monkeypatch):
    rows = synthetic_ledger(n=40, model="informative")
    rows[0]["venue"] = "paper:kalshi"  # a venue-comparison shadow row
    kept, dropped = harness.rows_from_records(rows, sport="mlb", start=None, end=None, portfolio_book_only=True)
    assert dropped.get("not_portfolio_book") == 1
    assert len(kept) == 39
    kept, dropped = harness.rows_from_records(rows, sport="mlb", start="2026-08-10", end="2026-08-20", portfolio_book_only=False)
    assert all("2026-08-10" <= r["date"] <= "2026-08-20" for r in kept)
    assert dropped.get("outside_date_range")
