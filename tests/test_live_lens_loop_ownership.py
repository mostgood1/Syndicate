"""The live-lens loop moves from live-odds-worker (2Gi) to refresh-worker (4Gi).

WHY. Its heavy piece is MLB's vendored 120-sim-per-live-game Monte Carlo, run
in-process with no batching. MEASURED 2026-08-08 with 13 MLB games live:

    03:29:43   295.5MB   live_lens_tick_before_mlb
    03:30:02  1740.8MB   live_lens_tick_after_build_mlb   <- +1,445MB
                         OOM-killed 4 seconds later, on a 2048MB limit

live-odds-worker carries a ~700-900MB steady-state baseline, so a 1.4GB build
cannot fit there at ANY gate threshold. #124 had already been forced to LOWER
MLB's headroom gate because the correct value (1800MB) was unsatisfiable on a
2Gi container -- that was this squeeze showing, and it was read as gate tuning.

Same move made for the MLB SIM tick on 2026-07-20, stopped one step short: the
4Gi service owned the simulations while the 2Gi service ran a ~1,560-simulation
Monte Carlo.
"""

from __future__ import annotations

import inspect
import os
from unittest.mock import patch

from syndicate.features.shared import live_lens_loop


def test_refresh_worker_starts_the_loop():
    import scripts.run_refresh_worker as worker

    source = inspect.getsource(worker.main)
    assert "start_live_lens_loop" in source, "refresh-worker does not start the live-lens loop"


def test_live_odds_worker_still_calls_it_too():
    """Both calling it is SAFE BY CONSTRUCTION and deliberate: the loop is gated
    on SYNDICATE_ENABLE_LIVE_LENS_LOOP, which defaults False. Ownership is the
    env var, not the call site -- so the move is a config flip and is instantly
    reversible without a code deploy."""
    import scripts.run_live_odds_refresh_worker as odds_worker

    assert "start_live_lens_loop" in inspect.getsource(odds_worker)


def test_the_gate_defaults_off_so_two_call_sites_cannot_both_run_it():
    """The load-bearing property. If this ever defaults True, BOTH services run
    a 1.4GB Monte Carlo and the move makes things worse rather than better."""
    with patch.dict(os.environ, {}, clear=True):
        assert live_lens_loop._is_live_lens_loop_enabled() is False


def test_the_gate_is_what_decides_ownership():
    with patch.dict(os.environ, {"SYNDICATE_ENABLE_LIVE_LENS_LOOP": "true"}, clear=False):
        assert live_lens_loop._is_live_lens_loop_enabled() is True
    with patch.dict(os.environ, {"SYNDICATE_ENABLE_LIVE_LENS_LOOP": "false"}, clear=False):
        assert live_lens_loop._is_live_lens_loop_enabled() is False


def test_start_returns_false_when_disabled():
    """So a service without the flag starts nothing and says so, rather than
    silently running a second copy."""
    with patch.dict(os.environ, {"SYNDICATE_ENABLE_LIVE_LENS_LOOP": "false"}, clear=False):
        assert live_lens_loop.start_live_lens_loop() is False
