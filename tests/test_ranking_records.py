"""`load_recent_ranking_records`: the board ranker's ledger reader (design A).

Lane `board-eval-reader-chunk-ceiling`. The old reader
(`intelligence_evaluation.load_recent_evaluation_records`) skips every daily
chunk over 64 MB and keeps whole records; production chunks are 117-417 MB, so
12 of 14 days never reached the ranker. These tests pin:

* REACHABILITY -- a chunk over the old ceiling is read by the new reader and
  skipped by the old one (this fails on the pre-lane call path);
* PARITY -- every ranker consumer gives identical output from full records and
  from projected settled records, so no field the ranker reads was dropped;
* the settled-only filter, backstop reporting, and the log line.
"""

from __future__ import annotations

import copy
import json
import random
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from syndicate.features.shared import intelligence_evaluation as ie
from syndicate.features.shared import ranking_records as rr
from syndicate.features.shared import recommendation_engine as re_engine


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _days_ago(n: int) -> str:
    return (datetime.now(timezone.utc).date() - timedelta(days=n)).isoformat()


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    """A chunked ledger root in tmp, recognised as chunked by both readers."""
    ledger_path = tmp_path / "evaluation_ledger.jsonl"
    (tmp_path / "evaluation_ledger_chunks").mkdir()
    monkeypatch.setattr(ie, "_is_chunked_ledger_path", lambda path: True)
    return ledger_path


def _write_chunk(ledger_path: Path, token: str, records: list[dict]) -> Path:
    chunk = ie._ledger_chunk_path(ledger_path, token)
    with chunk.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
    return chunk


# --- synthetic ledger ---------------------------------------------------------

SPORTS = ("mlb", "nba", "nhl")
MARKETS = ("moneyline", "total", "player_points")
POLICIES = (None, "balanced", "conservative", "aggressive")

# Where each field family lives on a record. EXACTLY ONE location per record,
# rotated, so dropping any single projected field changes some consumer's
# output -- a fixture that repeats a value in two places cannot detect the loss
# of either (the first version of this fixture missed 25 of 60 removals).
_SOURCE_CONTAINERS = ("recommendation", "response", "record", "empty_recommendation")
_SPORT_LOCATIONS = {
    "recommendation": (("recommendation", "sport"), ("recommendation", "sport_slug")),
    "any": (("record", "sport"), ("response", "sport"), ("query", "sport"), ("artifact_metadata", "sport")),
}
_MARKET_LOCATIONS = {
    "recommendation": (("recommendation", "market"), ("recommendation", "market_key"), ("recommendation", "market_label")),
    "any": (("record", "market"), ("response", "market"), ("query", "market")),
}
_POLICY_LOCATIONS = {
    "recommendation": (("recommendation", "decision_strategy"), ("recommendation", "policy")),
    "any": (("record", "decision_strategy"), ("response", "decision_strategy"), ("response", "policy")),
}


def _put(record: dict, location: "tuple[str, str]", value) -> None:
    container, key = location
    if container == "record":
        record[key] = value
    else:
        record.setdefault(container, {})[key] = value


def _pick_location(rng, table: dict, record: dict):
    options = list(table["any"]) + (list(table["recommendation"]) if "recommendation" in record else [])
    if "recommendation" not in record and "response" not in record:
        # Creating a response here would silently make it the source.
        options = [option for option in options if option[0] != "response"]
    return rng.choice(options)


def _synthetic_records(seed: int = 7, count: int = 1200) -> list[dict]:
    """Settled and pending records across sports, markets and policies, with
    every field in exactly one of the places its consumers look, plus padding
    the ranker must never need."""
    rng = random.Random(seed)
    out: list[dict] = []
    for index in range(count):
        sport = SPORTS[index % len(SPORTS)]
        market = MARKETS[(index // 3) % len(MARKETS)]
        policy = POLICIES[(index // 7) % len(POLICIES)]
        roll = rng.random()
        result = "win" if roll < 0.36 else "loss" if roll < 0.66 else "push" if roll < 0.71 else "void" if roll < 0.73 else ("pending" if roll < 0.87 else None)
        stake = rng.choice([1.0, 1.0, 2.0, None])
        pnl = {"win": round((stake or 1.0) * 0.91, 4), "loss": -(stake or 1.0), "push": 0.0, "void": 0.0}.get(result)
        source_container = _SOURCE_CONTAINERS[index % len(_SOURCE_CONTAINERS)]
        record: dict = {
            "result": result,
            "stake": stake,
            "pnl": pnl,
            "settled_at": _today(),
            "artifact_metadata": {"manifest_summary": {"big": "x" * 200}},
            "query": {"selected_date": _today(), "prompt": "unused " * 10},
            "padding_unused": "p" * 300,
        }
        if index % 11 == 0:
            record.pop("result")
        if index % 13 == 0:
            record["record_type"] = "portfolio_event"
        # Identity: most by recommendation_id; some by prediction_id, in
        # colliding SETTLED pairs so dropping prediction_id changes dedup.
        if index % 9 == 0:
            record["prediction_id"] = f"pred_{index // 18:05d}"
        else:
            record["recommendation_id"] = f"reco_{index:05d}"
        source_location = source_container
        if source_container == "recommendation":
            record["recommendation"] = {"narrative": "unused " * 30}
        elif source_container == "response":
            record["response"] = {"summary": "unused"}
        elif source_container == "empty_recommendation":
            # A recommendation carrying NONE of the kept fields, with the
            # values on response: `recommendation or response or record` must
            # still pick the (empty) recommendation after projection.
            record["recommendation"] = {"narrative": "unused"}
            record["response"] = {"summary": "unused"}
            source_location = "response"
        has_recommendation = "recommendation" in record

        def _src(key, value):
            _put(record, (source_location, key), value)

        _src("edge", round(rng.uniform(-0.05, 0.12), 4))
        probability_key = ("confidence", "model_probability", "fair_probability")[(index // 3) % 3]
        _src(probability_key, round(rng.uniform(0.42, 0.72), 4))
        _src("market_fit_score", round(rng.uniform(0, 90), 2))
        price = rng.choice([-150, -120, -110, 100, 115, 140, "+125", "-105"])
        price_key = ("odds", "price")[(index // 5) % 2]
        if (index // 4) % 2 == 1 and source_container != "record":
            # Entry price on the RECORD while the source is nested: `_price_clv`
            # and `_policy_record_clv` both fall back to record.odds/price.
            record[price_key] = price
        else:
            _src(price_key, price)
        closing = rng.choice([-160, -115, -105, 105, 120, None])
        if closing is not None:
            if (index // 4) % 2 == 0 or source_container == "record":
                record["closing_price"] = closing
            else:
                _src("closing_price", closing)
        implied = round(rng.uniform(0.4, 0.65), 4)
        if (index // 4) % 2 == 0 or source_container == "record":
            record["implied_probability"] = implied
        else:
            _src("implied_probability", implied)
        # Line CLV: recommendation.line/projected, else record.line; direction
        # from selection_direction, else pick, else name.
        if index % 3 == 0:
            record["closing_line"] = round(rng.uniform(5, 10), 1)
            if has_recommendation:
                line_key = ("line", "projected")[(index // 4) % 2]
                value = round(rng.uniform(5, 10), 1)
                record["recommendation"][line_key] = {"line": value} if line_key == "projected" else value
                direction_key = ("selection_direction", "pick", "name")[(index // 3) % 3]
                record["recommendation"][direction_key] = {"selection_direction": -1, "pick": "Under 7.5", "name": "Under"}[direction_key]
            else:
                record["line"] = round(rng.uniform(5, 10), 1)
        _put(record, _pick_location(rng, _SPORT_LOCATIONS, record), sport)
        _put(record, _pick_location(rng, _MARKET_LOCATIONS, record), market.title() if rng.random() < 0.3 else market)
        if policy is not None:
            _put(record, _pick_location(rng, _POLICY_LOCATIONS, record), policy)
        out.append(record)
    # Duplicate ids where the LAST copy is also settled (dedup keeps it).
    for index in (3, 40, 41):
        duplicate = copy.deepcopy(out[index])
        duplicate["result"] = "win"
        duplicate["pnl"] = 0.5
        out.append(duplicate)
    return out


def _load_via_reader(ledger_path: Path, records: list[dict]) -> list[dict]:
    """The records as the ranker will receive them: written to a chunk and read
    back through `load_recent_ranking_records` itself, not a test re-implementation."""
    _write_chunk(ledger_path, _today(), records)
    stats: dict = {}
    loaded = rr.load_recent_ranking_records(days=14, ledger_path=ledger_path, stats=stats)
    # Not vacuous: pending rows were dropped, and a settled->pending identity
    # collision was exercised (the fixture also has pending->settled ones).
    assert stats["skipped_unsettled"] > 0 and stats["kept_superseding_pending"] > 0
    return loaded


def _strip_pending_counts(value):
    """`compute_metrics()["sample_size"]` counts PENDING rows by definition, so
    it is the one field that legitimately differs (module docstring, point 1)."""
    if isinstance(value, dict):
        return {
            key: (None if key == "sample_size" and "settled_count" in value else _strip_pending_counts(item))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_strip_pending_counts(item) for item in value]
    return value


# --- reachability -------------------------------------------------------------

def test_chunk_over_the_old_64mb_ceiling_is_read_by_the_new_reader_only(ledger, capsys):
    settled = {"recommendation_id": "r1", "result": "win", "pnl": 0.9, "stake": 1.0,
               "recommendation": {"sport": "mlb", "market": "total", "odds": -110}}
    pending = {"recommendation_id": "r2", "result": "pending", "recommendation": {"sport": "mlb"}}
    padding = "x" * 65_000_000
    padded = {"recommendation_id": "r3", "result": "loss", "pnl": -1.0,
              "artifact_metadata": {"sport": "nba", "manifest_blob": padding}}
    chunk = _write_chunk(ledger, _today(), [settled, pending, padded])
    del padding
    assert chunk.stat().st_size > 64_000_000

    old = ie.load_recent_evaluation_records(days=14, ledger_path=ledger)
    assert old == [], "the old reader must skip this chunk -- that is the defect"
    assert "SKIP_OVERSIZED_LEDGER_CHUNK" in capsys.readouterr().out

    new = rr.load_recent_ranking_records(days=14, ledger_path=ledger)
    assert [r["recommendation_id"] for r in new] == ["r1", "r3"]
    assert new[1] == {"recommendation_id": "r3", "result": "loss", "pnl": -1.0, "artifact_metadata": {"sport": "nba"}}
    assert "manifest_blob" not in json.dumps(new)
    assert "SKIP_OVERSIZED_LEDGER_CHUNK" not in capsys.readouterr().out


def test_call_site_uses_the_new_reader():
    import inspect

    from pipeline.intelligence_state import IntelligenceStateService

    src = inspect.getsource(IntelligenceStateService._attach_adjusted_scores)
    code = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
    assert "load_recent_ranking_records(days=14)" in code
    assert "load_recent_evaluation_records(" not in code


# --- parity -------------------------------------------------------------------

def _consumer_outputs(records: list[dict]) -> dict:
    """Every function the ranking pass hands `evaluation_records` to."""
    out: dict = {}
    for sport in (None, *SPORTS):
        out[f"sport_profile:{sport}"] = re_engine._gated_reliability_profile(records=records, sport=sport)
        out[f"compare_policies:{sport}"] = re_engine.compare_policies(records, sport=sport)
        for key in ("exp-a", "exp-b", "exp-c", None):
            out[f"policy_summary:{sport}:{key}"] = re_engine.build_policy_optimization_summary(records, sport=sport, experiment_key=key)
            out[f"select_policy:{sport}:{key}"] = re_engine.select_policy(records, sport=sport, experiment_key=key)
        for market in (*MARKETS, "player_points".title(), "market"):
            out[f"market_profile:{sport}:{market}"] = re_engine._market_profile(records, sport=sport, market=market.lower())
    return out


def _candidates() -> list[dict]:
    now = datetime.now(timezone.utc).isoformat()
    rows = []
    for index, (sport, market) in enumerate((s, m) for s in SPORTS for m in MARKETS):
        rows.append(
            {
                "candidate_id": f"c{index}",
                "recommendation_id": f"cand_{index}",
                "sport": sport,
                "sport_slug": sport,
                "market": market,
                "selection": f"sel {index}",
                "event_id": f"evt{index}",
                "odds": -110 + index * 5,
                "model_probability": 0.56 + index * 0.01,
                "fair_probability": 0.56 + index * 0.01,
                "confidence": 0.6,
                "score": 40 + index,
                "market_fit_score": 30 + index,
                "last_updated": now,
                "market_features": {"line_movement": 0.0, "odds_movement": 0.0},
            }
        )
    return rows


def _volatile_free(rows):
    text = json.dumps(rows, sort_keys=True, default=str)
    # Wall-clock stamps and ages, which differ between two calls regardless.
    text = re.sub(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(\+00:00|Z)?", "<ts>", text)
    text = re.sub(r'"(age_seconds|candidate_age_seconds|freshness_age_seconds)": [0-9.]+', r'"\1": 0', text)
    return json.loads(text)


def test_parity_every_ranker_consumer_identical_on_projected_settled_records(ledger, monkeypatch):
    monkeypatch.setenv("SYNDICATE_FEEDBACK_MIN_SAMPLE", "20")
    full = _synthetic_records()
    slim = _load_via_reader(ledger, full)
    assert 0 < len(slim) < len(full)
    full_out = _consumer_outputs(copy.deepcopy(full))
    slim_out = _consumer_outputs(copy.deepcopy(slim))
    assert _strip_pending_counts(slim_out) == _strip_pending_counts(full_out)
    # The comparison is not vacuous: feedback is live and policies have samples.
    assert full_out["sport_profile:None"]["feedback_gated"] is False
    assert any(row["sample_size"] > 0 and row["average_clv_price"] != 0 for row in full_out["compare_policies:None"])
    assert full_out["sport_profile:None"]["metrics"]["clv"] is not None
    assert full_out["sport_profile:None"]["metrics"]["calibration"]["sample_size"] > 0


def test_parity_rank_recommendations_end_to_end(ledger, monkeypatch):
    monkeypatch.setenv("SYNDICATE_FEEDBACK_MIN_SAMPLE", "20")
    full = _synthetic_records()
    slim = _load_via_reader(ledger, full)
    full_rows = re_engine.rank_recommendations(_candidates(), evaluation_records=copy.deepcopy(full))
    slim_rows = re_engine.rank_recommendations(_candidates(), evaluation_records=copy.deepcopy(slim))
    assert full_rows, "no candidate survived the filter -- the parity check would be vacuous"
    assert [r.get("adjusted_score") for r in slim_rows] == [r.get("adjusted_score") for r in full_rows]
    assert [r.get("candidate_id") for r in slim_rows] == [r.get("candidate_id") for r in full_rows]
    assert [r.get("decision_strategy") for r in slim_rows] == [r.get("decision_strategy") for r in full_rows]
    assert _strip_pending_counts(_volatile_free(slim_rows)) == _strip_pending_counts(_volatile_free(full_rows))


# --- filter, backstop, log line -----------------------------------------------

def test_only_settled_records_are_kept(ledger):
    rows = [
        {"recommendation_id": "w", "result": "win"},
        {"recommendation_id": "l", "result": "LOSS "},
        {"recommendation_id": "p", "result": "push"},
        {"recommendation_id": "v", "result": "void"},
        {"recommendation_id": "pe", "result": "pending"},
        {"recommendation_id": "n", "result": None},
        {"recommendation_id": "missing"},
        {"recommendation_id": "o", "result": "open"},
    ]
    _write_chunk(ledger, _today(), rows)
    stats: dict = {}
    kept = rr.load_recent_ranking_records(days=14, ledger_path=ledger, stats=stats)
    assert [r["recommendation_id"] for r in kept] == ["w", "l", "p", "v"]
    assert stats["kept"] == 4 and stats["skipped_unsettled"] == 4 and stats["lines_seen"] == 8


def test_window_order_and_out_of_window_chunks(ledger):
    _write_chunk(ledger, _days_ago(1), [{"recommendation_id": "yesterday", "result": "win"}])
    _write_chunk(ledger, _today(), [{"recommendation_id": "today", "result": "win"}])
    _write_chunk(ledger, _days_ago(30), [{"recommendation_id": "stale", "result": "win"}])
    kept = rr.load_recent_ranking_records(days=14, ledger_path=ledger)
    assert [r["recommendation_id"] for r in kept] == ["yesterday", "today"]


def test_backstop_exclusions_are_reported_not_silent(ledger, capsys):
    for n in range(5):
        _write_chunk(ledger, _days_ago(n), [{"recommendation_id": f"d{n}", "result": "win"}])
    stats: dict = {}
    kept = rr.load_recent_ranking_records(days=14, ledger_path=ledger, max_chunks=3, stats=stats)
    assert sorted(r["recommendation_id"] for r in kept) == ["d0", "d1", "d2"]
    assert stats["excluded_by_backstop"] == 2
    assert stats["bytes_excluded_by_backstop"] > 0
    line = [l for l in capsys.readouterr().out.splitlines() if "RANKING_RECORDS_LOADED" in l][-1]
    assert "excluded_by_backstop=2" in line


def test_byte_backstop_stops_mid_chunk_and_reports_partial(ledger):
    rows = [{"recommendation_id": f"r{i}", "result": "win", "pad": "y" * 80} for i in range(10)]
    chunk = _write_chunk(ledger, _today(), rows)
    stats: dict = {}
    kept = rr.load_recent_ranking_records(days=14, ledger_path=ledger, max_total_bytes=chunk.stat().st_size // 2, stats=stats)
    assert 0 < len(kept) < 10
    assert stats["chunks_partial"] == 1
    assert stats["bytes_read"] <= chunk.stat().st_size // 2


def test_log_line_shape(ledger, capsys):
    _write_chunk(ledger, _today(), [{"recommendation_id": "a", "result": "win"}, {"recommendation_id": "b"}, ])
    rr.load_recent_ranking_records(days=14, ledger_path=ledger)
    out = capsys.readouterr().out
    assert re.search(
        r"^\[ranking_records\] RANKING_RECORDS_LOADED days=14 chunks=1 bytes=\d+ lines=2 kept=1 "
        r"skipped_unsettled=1 kept_superseding_pending=0 excluded_by_backstop=0 .*elapsed_s=\d+\.\d{3}$",
        out,
        re.MULTILINE,
    ), out


def test_log_line_is_printed_even_when_nothing_exists(ledger, capsys):
    assert rr.load_recent_ranking_records(days=14, ledger_path=ledger) == []
    assert "RANKING_RECORDS_LOADED days=14 chunks=0 bytes=0 lines=0 kept=0" in capsys.readouterr().out


def test_projection_keeps_source_truthiness():
    record = {"result": "win", "recommendation": {"narrative": "only unused"}, "response": {"edge": 0.5}}
    projected = rr.project_ranking_record(record)
    assert projected["recommendation"], "an empty projection would flip the source to response"
    assert re_engine._policy_record_features(projected) == re_engine._policy_record_features(record)


def test_pending_record_that_supersedes_a_settled_one_is_kept(ledger):
    rows = [
        {"recommendation_id": "a", "result": "win", "pnl": 1.0},
        {"recommendation_id": "b", "result": "pending"},  # precedes nothing settled: dropped
        {"recommendation_id": "a", "result": "pending"},  # hides "a" in last-wins dedup: kept
        {"prediction_id": "p", "result": "loss"},
        {"prediction_id": "p"},  # same, in the prediction_id namespace
        {"recommendation_id": "p", "result": None},  # different namespace: dropped
        {"record_type": "portfolio_event", "recommendation_id": "e", "result": "win"},
        {"record_type": "portfolio_event", "recommendation_id": "e"},  # never deduped: dropped
    ]
    _write_chunk(ledger, _today(), rows)
    stats: dict = {}
    kept = rr.load_recent_ranking_records(days=14, ledger_path=ledger, stats=stats)
    assert [(r.get("recommendation_id") or r.get("prediction_id"), r.get("result")) for r in kept] == [
        ("a", "win"), ("a", "pending"), ("p", "loss"), ("p", None), ("e", "win"),
    ]
    assert stats["kept"] == 3 and stats["kept_superseding_pending"] == 2 and stats["skipped_unsettled"] == 3
    assert ie.compute_metrics(records=kept)["settled_count"] == ie.compute_metrics(records=rows)["settled_count"] == 0
