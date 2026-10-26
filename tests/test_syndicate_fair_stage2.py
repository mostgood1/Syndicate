"""`scripts/syndicate_fair_stage2.py` -- the stage-2 forward read's driver around the UNCHANGED stage-1 fit module.

Hermetic: synthetic rows and tmp files only. The fit module itself is tested in `tests/test_syndicate_fair_fit.py`.
"""
from __future__ import annotations

import importlib.util
import math
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest

_ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location("syndicate_fair_stage2", _ROOT / "scripts" / "syndicate_fair_stage2.py")
s2 = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(s2)


# ----------------------------------------------------------------------------- the pin


def test_blob_sha_is_gits_and_ignores_crlf() -> None:
    # `printf 'hello\n' | git hash-object --stdin`
    assert s2.git_blob_sha(b"hello\n") == "ce013625030ba8dba906f756967f9e9ca394464a"
    assert s2.git_blob_sha(b"hello\r\n") == s2.git_blob_sha(b"hello\n")


def test_the_stage1_code_in_this_tree_is_the_pinned_code() -> None:
    """Fails if `syndicate_fair_fit.py` or `syndicate_fair.py` changes before the stage-2 read: stage 2 must run the
    stage-1 blobs (pre-registration section 11). After the read this pin may be retired with the lane."""
    status = s2.pin_status()
    assert set(status) == set(s2.PINNED_BLOBS)
    assert all(s["ok"] for s in status.values()), status


def test_a_changed_file_breaks_the_pin_and_the_read_refuses(tmp_path: Path, monkeypatch) -> None:
    for rel in s2.PINNED_BLOBS:
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_bytes((_ROOT / rel).read_bytes() + b"\n# edited\n")
    status = s2.pin_status(tmp_path)
    assert not any(s["ok"] for s in status.values())
    monkeypatch.setattr(s2, "pin_status", lambda root=s2.REPO_ROOT: status)
    with pytest.raises(SystemExit, match="REFUSING"):
        s2.main(["read", "--out", str(tmp_path), "--report", str(tmp_path / "r.json")])


# ----------------------------------------------------------------------------- the read's rules


@pytest.mark.parametrize("now,override,expected", [
    (datetime(2026, 11, 23, 23, 59, tzinfo=timezone.utc), False, False),
    (datetime(2026, 11, 24, 0, 0, tzinfo=timezone.utc), False, True),
    (datetime(2026, 12, 1, tzinfo=timezone.utc), True, False),  # a --window override is always a preview
])
def test_registered_read(now, override, expected) -> None:
    assert s2.registered_read(now, override) is expected


def test_abs_pp_two_way_and_three_way() -> None:
    p = np.array([[0.55, 0.45, 0.0], [0.50, 0.30, 0.20]])
    t = np.array([[0.52, 0.48, 0.0], [0.45, 0.30, 0.25]])
    assert s2.abs_pp(p, t) == pytest.approx([3.0, 5.0])


@pytest.mark.parametrize("a,b,gate,lead", [
    ("PASS", "PASS", "PASS", False),
    ("FAIL", "PASS", "FAIL", True),
    ("UNDERPOWERED", "PASS (outcome unmeasured)", "UNDERPOWERED", True),
    ("PASS (outcome unmeasured)", "FAIL", "PASS (outcome unmeasured)", False),
])
def test_arm_a_is_the_gate_and_a_b_only_pass_is_a_lead(a, b, gate, lead) -> None:
    v = s2.gate_verdict(a, b)
    assert v["gate"] == gate and bool(v["lead"]) is lead


def test_the_grid_is_set_per_arm_and_restored_even_on_error() -> None:
    fit = s2.load_fit_module()
    registered = fit.LAMBDA_GRID
    assert tuple(registered) == s2.ARMS["A"]
    seen = s2.with_grid(fit, s2.ARMS["B"], lambda: fit.LAMBDA_GRID)
    assert seen == s2.ARMS["B"] and fit.LAMBDA_GRID == registered

    def boom():
        raise RuntimeError("x")

    with pytest.raises(RuntimeError):
        s2.with_grid(fit, s2.ARMS["B"], boom)
    assert fit.LAMBDA_GRID == registered


# ----------------------------------------------------------------------------- end to end on a synthetic family


def _family(seed: int, first_day: int = 16, n_days: int = 20, games: int = 8) -> list[dict]:
    """A sharp book that is the close plus noise and three soft books; dates span the stage-1 / stage-2 boundary."""
    fit = s2.load_fit_module()
    rng = np.random.default_rng(seed)
    rows = []
    for d in range(n_days):
        day = datetime(2026, 10, first_day, tzinfo=timezone.utc).toordinal() + d
        date = datetime.fromordinal(day).date().isoformat()
        for g in range(games):
            truth = rng.normal(0, 0.6)
            close = 1 / (1 + math.exp(-truth))
            ev = f"{date}-{g}"
            for tts in ("t24h", "t6h", "t2h", "t30m"):
                books = []
                for b, noise in (("sharp", 0.02), ("soft0", 0.25), ("soft1", 0.25), ("soft2", 0.25)):
                    p = 1 / (1 + math.exp(-(truth + rng.normal(0, noise))))
                    books.append((b, 600.0, [p, 1 - p]))
                rows.append({"ev": ev, "date": date, "commence": fit.epoch(f"{date}T18:00:00+00:00"), "k": 2,
                             "mfam": "h2h", "tts": tts, "books": books,
                             "base": fit.shin_median({b: p for b, _, p in books}, 2),
                             "target": [close, 1 - close], "src": "consensus", "cons_close": [close, 1 - close],
                             "y": None, "family": "nhl|regular|game"})
    return rows


def test_read_family_scores_only_the_window_with_both_arms() -> None:
    fit = s2.load_fit_module()
    rows = _family(31)
    start, end = fit.epoch(s2.STAGE2_START), fit.epoch(s2.STAGE2_END)
    out = s2.read_family(fit, rows, start, end, log=lambda s: None)
    in_window = [r for r in rows if start <= r["commence"] < end]
    assert out["window_rows"] == len(in_window) > 0
    for arm in ("A", "B"):
        r = out["arms"][arm]
        assert r["g1_close"]["n"] == len(in_window)              # every window row scored, nothing from before it
        assert min(r["test_dates"]) >= "2026-10-26"
        assert r["fits_in_window"] and all(f["test_date"] >= "2026-10-26" for f in r["fits_in_window"])
        assert set(r["lambdas_in_window"]) <= set(s2.ARMS[arm])
        pp = r["abs_pp_v1_minus_shin"]
        assert pp["n"] == len(in_window) and "ci0.95" in pp
        assert "inside_2sigma" in r["sigma"]
    assert out["verdict"]["gate"] == out["arms"]["A"]["verdict"]
    assert out["arms"]["A"]["g1_close"]["mean"] < 0             # the sharp book is learnable: the fitted path ran


def test_a_family_with_no_window_rows_is_underpowered() -> None:
    fit = s2.load_fit_module()
    rows = _family(37, first_day=1, n_days=10)                    # 10-01 .. 10-10: all before the window
    out = s2.read_family(fit, rows, fit.epoch(s2.STAGE2_START), fit.epoch(s2.STAGE2_END), log=lambda s: None)
    assert out["window_rows"] == 0 and out["verdict"]["gate"] == "UNDERPOWERED" and out["arms"] == {}
