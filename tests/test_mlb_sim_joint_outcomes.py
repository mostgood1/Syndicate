"""`#621` Phase 4 producer -- the joint accumulator and its rank correlation.

REACHABILITY FIRST (`model_engine_standard` §4.3). The correctness tests below
are worthless on their own: a joint payload of all-zeros would pass "the key
exists" and "the shape is right" while measuring nothing. So the first test
asserts `off != on` -- a matrix with real dependence must produce a materially
different number from an independent one -- and the second asserts that a
CONSTANT column reads `null` rather than `0.0`, which is the one confusion that
would let a dead field masquerade as a measured independence.
"""
from __future__ import annotations

import os
import random
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "vendor", "mlb_bettingv2"))

from sim_engine.joint_outcomes import (  # noqa: E402
    CORR_SCALE,
    CORR_UNDEFINED,
    HITTER_MARKET_ROW_KEYS,
    JointAccumulator,
    build_labels,
    hitter_label,
    lookup,
    rankdata_average,
    spearman_lower_triangle,
    triangle_index,
    unpack,
)


def _accumulate(rows):
    """Build an accumulator over explicit per-sim rows: [{label: value}, ...]."""
    labels = sorted({k for row in rows for k in row})
    acc = JointAccumulator(labels, len(rows))
    for i, row in enumerate(rows):
        acc.record(i, row)
    return acc


# --- 1. REACHABILITY: a dependent pair must not read like an independent one --


def test_reachability_dependence_moves_the_number():
    """off != on. Identical shapes, one independent and one coupled."""
    rng = random.Random(7)

    independent = [{"a": rng.randint(0, 4), "b": rng.randint(0, 4)} for _ in range(1000)]
    coupled = []
    for _ in range(1000):
        a = rng.randint(0, 4)
        coupled.append({"a": a, "b": a + rng.randint(0, 1)})

    rho_independent = unpack(_accumulate(independent).to_payload()["corr_lower"][0])
    rho_coupled = unpack(_accumulate(coupled).to_payload()["corr_lower"][0])

    assert rho_independent is not None and rho_coupled is not None
    assert abs(rho_independent) < 0.10, rho_independent
    assert rho_coupled > 0.80, rho_coupled
    # The point of the test: the instrument DISTINGUISHES them.
    assert rho_coupled - rho_independent > 0.70


def test_reachability_negative_dependence_is_signed():
    """A negatively coupled pair must come back negative, not merely non-zero."""
    rng = random.Random(11)
    rows = []
    for _ in range(1000):
        a = rng.randint(0, 6)
        rows.append({"a": a, "b": 6 - a})
    rho = unpack(_accumulate(rows).to_payload()["corr_lower"][0])
    assert rho is not None and rho < -0.95, rho


# --- 2. A CONSTANT COLUMN IS `null`, NEVER 0.0 -------------------------------


def test_constant_column_is_undefined_not_zero():
    """`model_engine_standard` §4.2, and lane `mlb-hitter-so-dead-field`'s bug.

    `strikeouts` is pinned at 0 for every hitter in every game on `origin/main`.
    If a constant column returned 0.0, that dead field would publish as a
    measured independence and be indistinguishable from a working one.
    """
    rng = random.Random(3)
    rows = [{"live": rng.randint(0, 5), "dead": 0} for _ in range(500)]
    payload = _accumulate(rows).to_payload()

    packed = payload["corr_lower"][0]
    assert packed == CORR_UNDEFINED
    assert unpack(packed) is None
    # And it must not merely be small.
    assert unpack(packed) != 0.0


def test_lookup_returns_none_for_undefined_pair():
    rows = [{"live": i % 5, "dead": 3} for i in range(200)]
    payload = _accumulate(rows).to_payload()
    assert lookup(payload, "dead", "live") is None
    assert lookup(payload, "live", "absent") is None


# --- 3. The rank statistic itself, against scipy ------------------------------


def test_rankdata_matches_scipy_on_random_input():
    scipy_stats = pytest.importorskip("scipy.stats")
    rng = random.Random(19)
    values = [rng.randint(0, 30) for _ in range(400)]
    assert rankdata_average(values) == pytest.approx(list(scipy_stats.rankdata(values)))


def test_rankdata_matches_scipy_on_heavy_ties():
    """The case that matters: MLB counts are mostly 0 and 1."""
    scipy_stats = pytest.importorskip("scipy.stats")
    rng = random.Random(23)
    values = [0] * 300 + [1] * 80 + [2] * 15 + [3] * 5
    rng.shuffle(values)
    assert rankdata_average(values) == pytest.approx(list(scipy_stats.rankdata(values)))


def test_spearman_matches_scipy_on_count_data():
    scipy_stats = pytest.importorskip("scipy.stats")
    rng = random.Random(29)
    rows = []
    for _ in range(600):
        base = rng.randint(0, 3)
        rows.append({"a": base, "b": base + rng.randint(0, 2), "c": rng.randint(0, 4)})
    acc = _accumulate(rows)
    payload = acc.to_payload()
    labels = payload["labels"]

    for first in labels:
        for second in labels:
            if first >= second:
                continue
            mine = lookup(payload, first, second)
            fi, si = labels.index(first), labels.index(second)
            col_a = [rows[i][first] for i in range(len(rows))]
            col_b = [rows[i][second] for i in range(len(rows))]
            theirs = float(scipy_stats.spearmanr(col_a, col_b).statistic)
            assert mine == pytest.approx(theirs, abs=1.5 / CORR_SCALE), (first, second, fi, si)


def test_numpy_and_pure_python_paths_agree(monkeypatch):
    """The pure-Python fallback must not be a second, different estimator."""
    rng = random.Random(31)
    rows = [{"a": rng.randint(0, 5), "b": rng.randint(0, 5), "c": rng.randint(0, 2)} for _ in range(300)]
    acc = _accumulate(rows)
    with_numpy = spearman_lower_triangle(acc.buf, acc.rows_written, acc.n_dims)

    real_import = __import__

    def _no_numpy(name, *args, **kwargs):
        if name == "numpy":
            raise ImportError("numpy blocked for this test")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", _no_numpy)
    without_numpy = spearman_lower_triangle(acc.buf, acc.rows_written, acc.n_dims)
    assert with_numpy == without_numpy


# --- 4. The multiprocessing boundary -----------------------------------------


def test_chunks_concatenate_to_the_same_matrix_as_a_serial_run():
    """`_simw_chunk` splits 1,000 sims four ways; the joint must survive that.

    `_merge_seg` merges only counts today, which is why nothing joint crosses
    the process boundary at all. A rank correlation is invariant to row order,
    so concatenation is the whole merge -- this pins that claim.
    """
    rng = random.Random(37)
    rows = []
    for _ in range(400):
        a = rng.randint(0, 4)
        rows.append({"a": a, "b": a + rng.randint(0, 1), "c": rng.randint(0, 3)})
    labels = ["a", "b", "c"]

    serial = JointAccumulator(labels, len(rows))
    for i, row in enumerate(rows):
        serial.record(i, row)

    merged = JointAccumulator(labels, 0)
    for start in range(0, len(rows), 100):
        chunk_rows = rows[start : start + 100]
        chunk = JointAccumulator(labels, len(chunk_rows))
        for i, row in enumerate(chunk_rows):
            chunk.record(i, row)
        merged.extend(chunk.to_transport())

    assert merged.rows_written == serial.rows_written == len(rows)
    assert merged.to_payload()["corr_lower"] == serial.to_payload()["corr_lower"]


def test_transport_survives_a_real_pickle_round_trip():
    import pickle

    rows = [{"a": i % 7, "b": (i * 3) % 5} for i in range(120)]
    acc = _accumulate(rows)
    restored = JointAccumulator.from_transport(pickle.loads(pickle.dumps(acc.to_transport())))
    assert restored.to_payload()["corr_lower"] == acc.to_payload()["corr_lower"]


def test_label_mismatch_across_chunks_raises_rather_than_silently_mixing():
    """Concatenating columns that mean different things is a plausible wrong
    number with no error -- the exact failure this repo keeps paying for."""
    left = JointAccumulator(["a", "b"], 2)
    right = JointAccumulator(["a", "c"], 2)
    with pytest.raises(ValueError):
        left.extend(right.to_transport())


# --- 5. Shape, clamping, and the label contract -------------------------------


def test_buffer_is_int16_and_sized_to_theory():
    labels = [f"d{i}" for i in range(292)]
    acc = JointAccumulator(labels, 1000)
    assert acc.buf.typecode == "h"
    assert acc.buf.itemsize == 2
    # The number the memory argument rests on: n*D*2 bytes, one allocation.
    assert len(acc.buf) * acc.buf.itemsize == 1000 * 292 * 2 == 584_000


def test_out_of_range_values_are_clamped_and_COUNTED():
    """A wrapped int16 would corrupt a correlation with no error and no log."""
    acc = JointAccumulator(["a", "b"], 2)
    acc.record(0, {"a": 999_999, "b": -999_999})
    acc.record(1, {"a": 1, "b": 1})
    assert acc.clamped == 2
    assert acc.to_payload()["clamped"] == 2
    assert acc.buf[0] == 32767
    assert acc.buf[1] == -32767


def test_labels_are_in_ASCENDING_ID_ORDER_not_merely_repeatable():
    """The mutation check caught this test being a tautology. Kept as a lesson.

    It first asserted only `build_labels(a) == build_labels(reversed(a))`, and
    DELETING the `sorted()` did not turn it red -- because a CPython `set` of
    ints iterates by value-mod-table-size, which is a function of the values
    alone. Two calls over the same three ids therefore agree whether or not the
    code sorts, and the test proved nothing about the property it was named for.

    The real requirement is a TOTAL ORDER that four independently-spawned
    `_simw_chunk` processes will each derive identically, so this asserts the
    labels are ascending by id. The ids below are chosen so set order and sorted
    order genuinely differ (`list({592450, 592458, 592454})` yields
    `[592450, 592458, 592454]`), which is what makes the assertion bite.
    """
    ids = [592450, 592458, 592454]
    assert list({int(x) for x in ids}) != sorted(ids), "ids no longer expose set order"

    labels = build_labels(ids, starter_ids=[70, 12])
    seen_ids = []
    for label in labels:
        if label.startswith("batter|"):
            pid = int(label.split("|")[1])
            if pid not in seen_ids:
                seen_ids.append(pid)
    assert seen_ids == sorted(ids), seen_ids

    starter_ids_seen = []
    for label in labels:
        if label.startswith("pitcher|"):
            pid = int(label.split("|")[1])
            if pid not in starter_ids_seen:
                starter_ids_seen.append(pid)
    assert starter_ids_seen == [12, 70], starter_ids_seen

    assert build_labels(ids, starter_ids=[70, 12]) == build_labels(list(reversed(ids)), starter_ids=[12, 70])
    assert len(set(labels)) == len(labels)


def test_labels_cover_every_hitter_market_for_every_batter():
    labels = build_labels([101, 102])
    for pid in (101, 102):
        for market, _row_key in HITTER_MARKET_ROW_KEYS:
            assert hitter_label(pid, market) in labels


def test_a_REGEX_over_daily_update_reads_the_wrong_dict__do_not_use_one():
    """This test exists because the FIRST version of the test below used a regex.

    Measured on the real file: `re.findall(r"hitter_stat_values = \\{(.*?)\\}")`
    returns **6 keys where the dict has 10**. The `#621` fix's own comment
    contains a literal `{0: n_sims}`, and that brace closes the non-greedy match
    early -- silently dropping `"SO"`, the very key the comment is about.

    Pinned rather than deleted, so the next person who reaches for a regex here
    sees the measurement instead of rediscovering it.
    """
    import re

    source = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "vendor", "mlb_bettingv2", "tools", "daily_update.py",
    )
    with open(source, encoding="utf-8") as handle:
        text = handle.read()

    blocks = re.findall(r"hitter_stat_values = \{(.*?)\}", text, re.S)
    assert blocks, "the anchor moved; this demonstration no longer demonstrates anything"
    truncated = set(re.findall(r'"([^"]+)":', blocks[0]))
    assert "SO" not in truncated, (
        "the regex now sees SO -- the comment brace moved, so the trap changed shape. "
        "Re-measure before trusting any regex over this file."
    )


def test_every_joint_market_has_a_live_source_key_at_BOTH_sites():
    """A joint market whose source key is absent publishes a CONSTANT column.

    This began as an assertion that `strikeouts` was NOT published, because
    `hitter_stat_values` had no `"SO"` key while lane `mlb-hitter-so-dead-field`
    was mid-flight on it. That lane landed and `strikeouts` was added here in
    the same change. Rather than delete the test, it now delegates to the AST
    invariant in `scripts/sim_input_checklist.py`, which checks both sites and
    cannot be fooled by the brace above.
    """
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
    from sim_input_checklist import joint_site_problems

    assert joint_site_problems() == []
    assert "strikeouts" in {market for market, _ in HITTER_MARKET_ROW_KEYS}


def test_triangle_index_round_trips_for_every_pair():
    n = 12
    seen = set()
    for i in range(n):
        for j in range(i):
            pos = triangle_index(i, j)
            assert triangle_index(j, i) == pos
            assert pos not in seen
            seen.add(pos)
    assert len(seen) == n * (n - 1) // 2
    assert max(seen) == n * (n - 1) // 2 - 1


def test_record_ignores_unknown_labels_and_out_of_range_sims():
    acc = JointAccumulator(["a"], 2)
    acc.record(0, {"a": 3, "nonexistent": 9})
    acc.record(99, {"a": 5})
    assert acc.rows_written == 1
    assert list(acc.buf) == [3, 0]


def test_too_few_rows_is_undefined_not_zero():
    acc = JointAccumulator(["a", "b"], 1)
    acc.record(0, {"a": 1, "b": 2})
    assert acc.to_payload()["corr_lower"] == [CORR_UNDEFINED]
