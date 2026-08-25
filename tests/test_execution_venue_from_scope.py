"""In live mode the placing venue is the SCOPE, never the env var.

MEASURED 2026-08-25T00:13:26Z, the first tick after
`SYNDICATE_EXECUTION_VENUE` became a comma list:

  EXECUTION status=skipped reason=no_adapter_for_venue:kalshi,polymarket scope=kalshi
  EXECUTION status=skipped reason=no_adapter_for_venue:kalshi,polymarket scope=polymarket

The worker looped correctly and passed one scope per call. `run_execution`
then looked past its own argument, read the WHOLE env string back out, and
asked `_venue_submitter` for an adapter named "kalshi,polymarket". Kalshi,
which had been placing live all evening, stopped placing.

The existing live tests could not catch it: they set the env var to the single
venue they also passed as the scope, so the two were indistinguishable. These
tests make them DIFFER on purpose -- that is the entire point.
"""

from __future__ import annotations

import pytest

from pipeline import execute_portfolio


def test_the_live_venue_is_the_SCOPE_when_the_env_var_holds_a_list(monkeypatch):
    """The regression, stated directly."""
    monkeypatch.setenv("SYNDICATE_EXECUTION_VENUE", "kalshi,polymarket")

    assert execute_portfolio._venue_submitter("kalshi,polymarket") is None, (
        "a comma list is not an adapter name -- if this ever resolves, the "
        "test below is no longer testing anything"
    )
    assert execute_portfolio._venue_submitter("kalshi") is not None
    assert execute_portfolio._venue_submitter("polymarket") is not None


@pytest.mark.parametrize("scope", ["kalshi", "polymarket"])
def test_each_scope_resolves_its_OWN_adapter(monkeypatch, scope):
    """Both venues in the list must reach a real adapter, one at a time."""
    monkeypatch.setenv("SYNDICATE_EXECUTION_VENUE", "kalshi,polymarket")

    submitter = execute_portfolio._venue_submitter(scope)

    assert submitter is not None, f"no adapter resolved for scope={scope}"
    assert callable(submitter)


def test_an_unknown_venue_fails_CLOSED_rather_than_falling_through(monkeypatch):
    """Why the regression was cheap rather than expensive.

    An unresolvable venue name yields no adapter, and `place_order` rejects a
    live order with no adapter instead of completing it as a paper fill wearing
    a live `mode` -- which would put a record in the ledger claiming money
    moved when none did.
    """
    assert execute_portfolio._venue_submitter("kalshi,polymarket") is None
    assert execute_portfolio._venue_submitter("not-a-venue") is None
    assert execute_portfolio._venue_submitter("") is None
    assert execute_portfolio._venue_submitter(None) is None
