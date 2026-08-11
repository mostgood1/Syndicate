"""`#345` — the reuse guard took an `input_hash` and never read it.

Reuse was decided purely by "do these CSV files exist and have content". Those
files exist from any earlier run, so it reported reusable FOREVER. Measured on
production 2026-08-11: WNBA made zero OddsAPI calls across a 45-minute live
slate (`wnba_calls` pinned at 1158 while MLB climbed 135,645 -> 135,714), while
the caller computed a fresh hash every tick and passed it in. The `#344`
diagnostic confirmed it: hash changed 5a845929 -> 23c96420, decision stayed
`reused_source_root_state`.
"""

from __future__ import annotations

import importlib.util
import pathlib

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "_wnba_reuse", pathlib.Path(__file__).resolve().parents[1] / "scripts" / "refresh_wnba_oddsapi_props.py"
)
_MOD = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MOD)

STEP = "wnba_reuse_guard_test_step"


@pytest.fixture()
def slate(tmp_path):
    """A source root whose outputs all exist -- the state that used to mean
    'reusable forever'."""
    processed = tmp_path / "data" / "processed"
    raw = tmp_path / "data" / "raw"
    processed.mkdir(parents=True)
    raw.mkdir(parents=True)
    (raw / "odds_wnba_player_props_2026-08-10.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    for name in ("oddsapi_player_props", "predictions", "props_predictions", "props_edges", "props_recommendations"):
        (processed / f"{name}_2026-08-10.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    (processed / "recommendations_slate_2026-08-10.json").write_text('{"per_game": []}', encoding="utf-8")
    return tmp_path


def _call(slate, input_hash, step_key=STEP):
    return _MOD._existing_refresh_state(
        source_root=slate, date_str="2026-08-10", do_edges=True, do_export=True,
        input_hash=input_hash, step_key=step_key,
    )


def test_a_changed_hash_forces_a_rerun_even_with_every_output_present(slate, monkeypatch):
    # THE DEFECT. All outputs exist and look complete; the inputs moved.
    monkeypatch.setattr(_MOD, "should_recompute", lambda step, h: True)
    assert _call(slate, "hash-that-moved") is None


def test_an_unchanged_hash_still_reuses(slate, monkeypatch):
    # The guard must keep doing its actual job -- this is not "always refetch".
    monkeypatch.setattr(_MOD, "should_recompute", lambda step, h: False)
    state = _call(slate, "hash-unchanged")
    assert state is not None
    assert state["rc_snapshot"] == 0


def test_existence_is_checked_first_and_still_wins(slate, monkeypatch):
    # A matching hash must not make ABSENT outputs reusable.
    monkeypatch.setattr(_MOD, "should_recompute", lambda step, h: False)
    (slate / "data" / "raw" / "odds_wnba_player_props_2026-08-10.csv").unlink()
    assert _call(slate, "hash-unchanged") is None


def test_a_first_run_with_no_recorded_hash_fetches(slate):
    # should_recompute returns True when nothing is recorded, so leftovers from
    # an unrelated run are never trusted on a cold state.
    assert _call(slate, "brand-new-hash", step_key="wnba_reuse_guard_never_recorded") is None


def test_the_guard_is_inert_without_a_step_key(slate, monkeypatch):
    # Callers that pass no key keep the old behaviour rather than silently
    # comparing against the wrong step.
    monkeypatch.setattr(_MOD, "should_recompute", lambda step, h: True)
    assert _call(slate, "anything", step_key=None) is not None


def test_read_and_write_use_the_same_step_key():
    # A guard consulting a different key than the recorder is indistinguishable
    # from no guard at all, and would restore the permanent reuse.
    src = (pathlib.Path(__file__).resolve().parents[1] / "scripts" / "refresh_wnba_oddsapi_props.py").read_text(encoding="utf-8")
    assert src.count("step_key=_reuse_step_key") == 2
    assert "_reuse_step_key = (" in src
    assert 'f"wnba_artifact_bundle:{_refresh_state_scope_path(artifact_root_path)}:"' in src


def test_the_recorder_only_fires_after_real_work():
    """`#347` — recording a hash after a REUSE closes a self-perpetuating loop.

    A reused state has no error, so the recorder wrote the CURRENT hash as
    "done" without having fetched anything. Next tick's should_recompute then
    sees a match and reuses again: reuse -> record -> reuse. #345 gave the guard
    a hash to compare; this handed it a hash that always agreed.

    Measured after #345 deployed: the decision moved from
    `reused_source_root_state` to `reused_artifact_bundle` and WNBA calls stayed
    pinned at 1161 for 23 minutes.
    """
    src = (pathlib.Path(__file__).resolve().parents[1] / "scripts" / "refresh_wnba_oddsapi_props.py").read_text(encoding="utf-8")
    assert "_did_real_work = bool(" in src
    assert 'and not state.get("reused_existing_outputs")' in src
    assert 'and not state.get("reused_existing_artifact_bundle")' in src
    # and the guard on the record call itself
    assert 'if state and not state.get("error") and _did_real_work:' in src


def test_a_recorded_hash_means_the_inputs_were_actually_processed():
    # The invariant the loop violated: a recorded hash must mean work happened,
    # otherwise the guard agrees with itself forever.
    src = (pathlib.Path(__file__).resolve().parents[1] / "scripts" / "refresh_wnba_oddsapi_props.py").read_text(encoding="utf-8")
    record_idx = src.index("record_refresh_state(")
    window = src[max(0, record_idx - 1200):record_idx]
    assert "_did_real_work" in window, "record_refresh_state is reachable without a real-work guard"
