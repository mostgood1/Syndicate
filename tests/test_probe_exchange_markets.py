"""The boot-time orchestration for the exchange-venue schema probe.

Covers only the gating and never-raises contract -- the underlying probes
are network calls, tested in their own modules.
"""

from __future__ import annotations

from scripts.probe_exchange_markets import run_all_probes, run_all_probes_if_enabled

_EXPECTED_LABELS = {"polymarket", "novig", "prophetx", "cryptocom_og", "polymarket_us_sports"}


def test_disabled_by_default(monkeypatch):
    monkeypatch.delenv("SYNDICATE_EXCHANGE_MARKETS_PROBE_ON_BOOT", raising=False)
    assert run_all_probes_if_enabled() is None


def test_runs_every_probe_when_enabled(monkeypatch):
    monkeypatch.setenv("SYNDICATE_EXCHANGE_MARKETS_PROBE_ON_BOOT", "1")
    result = run_all_probes_if_enabled()
    assert set(result.keys()) == _EXPECTED_LABELS


def test_one_venue_import_failure_does_not_stop_the_rest(monkeypatch):
    """A broken import for one venue must not take the others down with it --
    same discipline every module in this lane uses for its own probe()."""
    import scripts.probe_exchange_markets as mod

    broken = (("broken", "not.a.real.module", "probe"),) + mod._PROBES[1:]
    monkeypatch.setattr(mod, "_PROBES", broken)
    result = run_all_probes()
    assert result["broken"]["status"] == "error"
    assert len(result) == len(broken)
