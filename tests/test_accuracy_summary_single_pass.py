"""`build_accuracy_summaries` -- every graded sport from ONE ledger read.

The refresh-worker autorun called `build_accuracy_summary(sport=...)` once per
graded sport, and every call re-streamed the whole bounded ledger to keep one
sport of it: eight `LEDGER_CHUNKS_ACCEPTED` lines per autorun on 2026-09-10,
each re-reading ~4 GB. Under the chunk-count bound that is ~8 GB x 8 per day.

These pin what makes one read a safe replacement for eight:
  * EQUIVALENCE -- each sport's summary equals the single-sport call on the same
    ledger (`generated_at` aside), including a sport with NO records of its own,
    which receives only the unsported ones: the `{sport, None}` rule, surviving
    the partition;
  * ONE READ -- one `LEDGER_CHUNKS_ACCEPTED` line, against one per sport;
  * ISOLATION -- a sport whose summary raises gets an error, the rest compute.
"""
from __future__ import annotations

import json

import pytest

from syndicate.features.shared import intelligence_evaluation as ie

SPORTS = ["mlb", "nfl", "nhl", "wnba"]  # nhl has no records of its own
DATES = ["2026-08-01", "2026-08-02", "2026-08-03", "2026-08-04"]
ROTATION = ["mlb", "mlb", "mlb", "nfl", "wnba", None]


def _record(date, i, *, sport, result, marker=None):
    recommendation = {"market": ["moneyline", "totals", "player_prop"][i % 3],
                      "confidence": ["high", "medium", "low"][i % 3]}
    metadata = {"selected_date": date}
    if sport:
        recommendation["sport"] = sport
        metadata["sport"] = sport
    record = {
        "recommendation_id": f"{date}-{i}",
        "record_type": "recommendation",
        "result": result,
        "stake": 10.0,
        "pnl": {"win": 9.1, "loss": -10.0, "push": 0.0}.get(result),
        "odds": -110,
        "price": -110,
        "closing_price": -115,
        "implied_probability": 0.524,
        "model_probability": 0.55 + (i % 5) / 100,
        "recommendation": recommendation,
        "artifact_metadata": metadata,
        "created_at": f"{date}T12:00:00Z",
    }
    if marker:
        record["marker"] = marker
    return record


@pytest.fixture()
def ledger(tmp_path, monkeypatch):
    path = tmp_path / "evaluation_ledger.jsonl"
    monkeypatch.setattr(ie, "DEFAULT_LEDGER_PATH", path)
    chunk_root = tmp_path / "evaluation_ledger_chunks"
    chunk_root.mkdir(parents=True)
    for d, date in enumerate(DATES):
        rows = [
            _record(date, i, sport=ROTATION[i % len(ROTATION)], result=["win", "loss", "push", None][i % 4])
            for i in range(60)
        ]
        if d == len(DATES) - 1:
            # An id re-recorded in a later chunk: last-wins must hold across the partition.
            rows.append(_record(DATES[0], 0, sport="mlb", result="loss", marker="later"))
        (chunk_root / f"{date}.jsonl").write_text(
            "\n".join(json.dumps(r, separators=(",", ":")) for r in rows) + "\n", encoding="utf-8"
        )
    return path


def _without_clock(summary):
    return {key: value for key, value in summary.items() if key != "generated_at"}


def test_each_sport_equals_the_single_sport_call(ledger):
    together = ie.build_accuracy_summaries(SPORTS)
    assert list(together) == SPORTS
    for sport in SPORTS:
        alone = ie.build_accuracy_summary(sport=sport)
        assert _without_clock(together[sport]) == _without_clock(alone), sport
    # The fixture must exercise the rules, or equality proves nothing.
    assert together["mlb"]["sample_size"] > together["nfl"]["sample_size"] > 0
    assert together["nhl"]["sample_size"] > 0, "unsported records must reach a sport with none of its own"
    assert together["mlb"]["settled_count"] < together["mlb"]["sample_size"], "fixture needs unsettled rows"


def test_the_ledger_is_read_once_not_once_per_sport(ledger, capsys):
    ie.build_accuracy_summaries(SPORTS)
    together = [line for line in capsys.readouterr().out.splitlines() if "LEDGER_CHUNKS_ACCEPTED" in line]
    for sport in SPORTS:
        ie.build_accuracy_summary(sport=sport)
    per_sport = [line for line in capsys.readouterr().out.splitlines() if "LEDGER_CHUNKS_ACCEPTED" in line]
    assert len(per_sport) == len(SPORTS), "control: the single-sport path reads once per call"
    assert len(together) == 1


def test_one_sport_failing_does_not_cost_the_others(ledger, monkeypatch):
    real = ie.compute_metrics

    def flaky(*, records=None, ledger_path=None, sport=None):
        if sport == "nfl":
            raise RuntimeError("boom")
        return real(records=records, ledger_path=ledger_path, sport=sport)

    monkeypatch.setattr(ie, "compute_metrics", flaky)
    out = ie.build_accuracy_summaries(SPORTS)
    assert out["nfl"] == {"error": "RuntimeError: boom"}
    assert all("error" not in out[sport] for sport in SPORTS if sport != "nfl")


def test_sports_are_normalised_and_deduplicated(ledger):
    out = ie.build_accuracy_summaries([" MLB", "mlb", "", "nfl"])
    assert list(out) == ["mlb", "nfl"]
