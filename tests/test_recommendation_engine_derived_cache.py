"""`recommendation_engine`'s derived-aggregate memo (lane `ranking-records-build-cost`).

The ranker's policy, sport profile, market profiles and policy comparison are
pure functions of the evaluation records, and `rank_recommendations` rebuilt
the policy comparison once per scored candidate. With a fingerprinted record
list (`ranking_records.RankingRecords`) they are memoized across calls. Pinned:

* EQUALITY -- a fingerprinted list ranks exactly like the same records as a
  plain list, on the first (miss) and the second (hit) call;
* REACHABILITY -- the second call recomputes nothing (`build_reliability_profile`
  and `build_policy_optimization_summary` are never called), and a plain list
  never touches the memo;
* the per-call hoist -- the policy comparison is built once per call, not once
  per candidate, even without a fingerprint;
* ISOLATION -- a caller mutating its rows cannot reach the next call, or the
  cached records;
* the memo is scoped by `SYNDICATE_FEEDBACK_MIN_SAMPLE`, which gates profiles.
"""

from __future__ import annotations

import copy
import importlib.util
from pathlib import Path

import pytest

from syndicate.features.shared import intelligence_evaluation as ie
from syndicate.features.shared import ranking_records as rr
from syndicate.features.shared import recommendation_engine as re_engine

_spec = importlib.util.spec_from_file_location("_ranking_records_fixtures", Path(__file__).with_name("test_ranking_records.py"))
fx = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fx)


@pytest.fixture
def records(tmp_path, monkeypatch):
    ledger_path = tmp_path / "evaluation_ledger.jsonl"
    (tmp_path / "evaluation_ledger_chunks").mkdir()
    monkeypatch.setattr(ie, "_is_chunked_ledger_path", lambda path: True)
    monkeypatch.setenv("SYNDICATE_FEEDBACK_MIN_SAMPLE", "20")
    monkeypatch.delenv("SYNDICATE_RANKING_RECORDS_CACHE", raising=False)
    rr.reset_ranking_records_cache()
    re_engine.reset_derived_memo()
    fx._write_chunk(ledger_path, fx._today(), fx._synthetic_records())
    loaded = rr.load_recent_ranking_records(days=14, ledger_path=ledger_path)
    assert loaded.fingerprint and len(loaded) > 100
    yield loaded
    rr.reset_ranking_records_cache()
    re_engine.reset_derived_memo()


def _rank(evaluation_records):
    return re_engine.rank_recommendations(fx._candidates(), evaluation_records=evaluation_records)


def _same(a, b):
    assert a, "no candidate survived -- the comparison would be vacuous"
    assert [r.get("adjusted_score") for r in a] == [r.get("adjusted_score") for r in b]
    assert [r.get("candidate_id") for r in a] == [r.get("candidate_id") for r in b]
    assert fx._volatile_free(a) == fx._volatile_free(b)


class _Counter:
    def __init__(self, monkeypatch, name):
        self.calls = 0
        original = getattr(re_engine, name)

        def wrapper(*args, **kwargs):
            self.calls += 1
            return original(*args, **kwargs)

        monkeypatch.setattr(re_engine, name, wrapper)


def test_fingerprinted_and_plain_lists_rank_identically_on_miss_and_hit(records):
    plain = _rank(list(copy.deepcopy(records)))
    miss = _rank(records)
    hit = _rank(records)
    _same(miss, plain)
    _same(hit, plain)
    # Not vacuous: feedback is live, so the profiles move the score.
    assert miss[0]["historical_profile"]["sport"]["feedback_gated"] is False
    assert miss[0]["historical_profile"]["policy_comparison"]


def test_second_call_recomputes_nothing(records, monkeypatch, capsys):
    _rank(records)
    reliability = _Counter(monkeypatch, "build_reliability_profile")
    summary = _Counter(monkeypatch, "build_policy_optimization_summary")
    capsys.readouterr()
    _rank(records)
    assert reliability.calls == 0 and summary.calls == 0
    line = [l for l in capsys.readouterr().out.splitlines() if "RANKING_DERIVED_CACHE" in l][-1]
    assert f"fingerprint={records.fingerprint[:16]} " in line and " miss=0" in line
    assert int(line.split(" hit=")[1].split()[0]) > 0


def test_a_plain_list_never_touches_the_memo(records, monkeypatch, capsys):
    plain = list(copy.deepcopy(records))
    _rank(plain)
    reliability = _Counter(monkeypatch, "build_reliability_profile")
    capsys.readouterr()
    _rank(plain)
    assert reliability.calls > 0
    assert "RANKING_DERIVED_CACHE fingerprint=none hit=0 miss=0" in capsys.readouterr().out
    assert re_engine._DERIVED_MEMO["entries"] == {}


def test_policy_comparison_is_built_once_per_call_not_per_candidate(records, monkeypatch):
    summary = _Counter(monkeypatch, "build_policy_optimization_summary")
    rows = _rank(list(copy.deepcopy(records)))
    assert len(rows) > 2
    # One for select_policy, one for the rows' comparison -- was 1 + len(rows).
    assert summary.calls == 2
    # ...and every row still carries its OWN copy.
    rows[0]["historical_profile"]["policy_comparison"].append("mutated")
    assert "mutated" not in rows[1]["historical_profile"]["policy_comparison"]


def test_mutating_returned_rows_cannot_reach_the_next_call_or_the_records(records):
    snapshot = copy.deepcopy(list(records))
    first = _rank(records)
    expected = fx._volatile_free(_rank(records))
    for row in first:
        row["historical_profile"]["sport"]["reliability_multiplier"] = 99.0
        row["historical_profile"]["market"]["roi"] = 99.0
        row["historical_profile"]["policy_comparison"].clear()
    assert fx._volatile_free(_rank(records)) == expected
    assert list(records) == snapshot


def test_memo_is_scoped_by_the_feedback_sample_gate(records, monkeypatch):
    live = _rank(records)
    assert live[0]["historical_profile"]["sport"]["feedback_gated"] is False
    monkeypatch.setenv("SYNDICATE_FEEDBACK_MIN_SAMPLE", "100000")
    gated = _rank(records)
    _same(gated, _rank(list(copy.deepcopy(records))))
    assert gated[0]["historical_profile"]["sport"]["feedback_gated"] is True


def test_filter_candidates_memo_matches_plain(records):
    plain = re_engine.filter_candidates(fx._candidates(), evaluation_records=list(copy.deepcopy(records)))
    miss = re_engine.filter_candidates(fx._candidates(), evaluation_records=records)
    hit = re_engine.filter_candidates(fx._candidates(), evaluation_records=records)
    assert plain
    assert fx._volatile_free(miss) == fx._volatile_free(plain) == fx._volatile_free(hit)
