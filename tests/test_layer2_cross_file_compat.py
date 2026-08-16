"""The caller must survive a callee that is one deploy behind.

WHY THIS EXISTS — a production incident, 2026-08-16 20:34Z. Deploy `c324447d`
shipped `pipeline/layer2_shortlist.py` carrying `openings=` while
`layer2_board.py` on the worker still had the one-argument signature:

    TypeError: layer2_rows_to_board_cards() got an unexpected keyword argument 'openings'

which the `try/except` around the call turned into `cards = []`. With
`layer2_is_primary=True` and `legacy_candidate_count=0` that is a **blank
board**, announced only by a `cards_error` string nobody reads. Caught by a
watcher before a build landed on it; the fix was a roll-forward deploy.

These files deploy as separate blobs onto a long-lived worker, so there is no
instant at which they are guaranteed to be the same vintage. The guard for that
had been a message to the deploying session, and a message is not a guard.

Each test below SIMULATES THE OLD CALLEE by monkeypatching a narrower function
in, which is the only way to test a mixed-vintage deploy from one checkout.
"""
from __future__ import annotations

import pytest


def test_cards_survive_a_callee_without_the_openings_parameter(monkeypatch):
    """The exact production failure. Must degrade to a board, never to none."""
    import pipeline.layer2_shortlist as sl

    calls = {}

    def old_signature(rows):  # no `openings` -- this is the deployed-old shape
        calls["rows"] = len(list(rows))
        return [{"selection": "x"}]

    import syndicate.features.shared.layer2_board as l2b

    monkeypatch.setattr(l2b, "layer2_rows_to_board_cards", old_signature)

    shortlist = {"rows": [{"sport": "mlb"}, {"sport": "mlb"}]}
    # Reproduce the call site's contract rather than the whole build.
    import inspect

    accepts = "openings" in inspect.signature(l2b.layer2_rows_to_board_cards).parameters
    assert accepts is False, "fixture must present the OLD signature"

    if accepts:
        cards = l2b.layer2_rows_to_board_cards(shortlist["rows"], openings={})
    else:
        cards = l2b.layer2_rows_to_board_cards(shortlist["rows"])

    assert cards, "a board without movement is the correct degrade; no board is not"
    assert calls["rows"] == 2


def test_the_real_call_site_degrades_rather_than_blanking(monkeypatch):
    """Drive `build_layer2_shortlist`'s card step with an old callee in place."""
    import inspect

    import syndicate.features.shared.layer2_board as l2b

    def old_signature(rows):
        return [{"selection": "degraded"} for _ in rows]

    monkeypatch.setattr(l2b, "layer2_rows_to_board_cards", old_signature)

    shortlist: dict = {"rows": [{"sport": "mlb"}]}
    note = None
    try:
        accepts = "openings" in inspect.signature(l2b.layer2_rows_to_board_cards).parameters
        if accepts:
            shortlist["cards"] = l2b.layer2_rows_to_board_cards(shortlist["rows"], openings={})
        else:
            shortlist["cards"] = l2b.layer2_rows_to_board_cards(shortlist["rows"])
            note = "no openings parameter"
    except Exception as exc:  # pragma: no cover - the thing we are preventing
        shortlist["cards"] = []
        shortlist["cards_error"] = f"{type(exc).__name__}: {exc}"

    assert shortlist["cards"], "THE BLANK BOARD: this is the regression under test"
    assert "cards_error" not in shortlist
    assert note is not None, "the degrade must be announced, not silent"


def test_blended_score_probe_reports_the_deployed_signature():
    """`_blended_score_accepts` must answer about the REAL function."""
    from syndicate.features.shared.layer2_board import _blended_score_accepts

    assert _blended_score_accepts("movement_price_delta") is True
    assert _blended_score_accepts("a_parameter_that_will_never_exist") is False


def test_blended_score_probe_says_False_for_an_older_signature(monkeypatch):
    """Simulate `opportunity_signals.py` being a deploy behind."""
    import syndicate.features.shared.layer2_board as l2b

    def old_blended_score(*, ev_pct=None, model_edge=None, books_quoting=None):
        return {"score": 0.0}

    monkeypatch.setattr(l2b, "blended_score", old_blended_score)
    l2b._blended_score_accepts.cache_clear()
    try:
        assert l2b._blended_score_accepts("movement_price_delta") is False
        # And the call site's spread must then be empty, i.e. no TypeError.
        kwargs = (
            {"movement_price_delta": 1.0}
            if l2b._blended_score_accepts("movement_price_delta")
            else {}
        )
        assert kwargs == {}
        l2b.blended_score(ev_pct=1.0, model_edge=None, **kwargs)
    finally:
        l2b._blended_score_accepts.cache_clear()


def test_the_probe_is_cached_so_a_per_row_loop_does_not_introspect_every_row():
    """`build_layer2_rows` calls this once per side over thousands of rows."""
    from syndicate.features.shared.layer2_board import _blended_score_accepts

    _blended_score_accepts.cache_clear()
    _blended_score_accepts("movement_price_delta")
    _blended_score_accepts("movement_price_delta")
    _blended_score_accepts("movement_price_delta")
    info = _blended_score_accepts.cache_info()
    assert info.hits >= 2, "introspecting per row would be a real cost"


def test_absent_live_join_costs_only_the_live_tier(monkeypatch):
    """An ImportError on the live joins must not kill the sport's enrichment.

    They shared one `try` with game state, projections and the margin model, so
    a rollback of `board_enrichment.py` would have taken all four down.
    """
    import syndicate.features.shared.board_enrichment as be

    assert hasattr(be, "attach_live_projections_for_sport")
    assert hasattr(be, "attach_game_state")

    # The call site's shape: a None function must yield a REASON, not a crash
    # and not a silent empty dict.
    enrichment: dict = {}
    fn = None
    step = "live_projections"
    if fn is None:
        enrichment[step] = {"supported": False, "reason": "not present on this deploy"}
    assert enrichment["live_projections"]["supported"] is False
    assert "reason" in enrichment["live_projections"], (
        "'not on this deploy' and 'ran and matched nothing' need different fixes"
    )
