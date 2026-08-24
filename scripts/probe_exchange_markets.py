#!/usr/bin/env python3
"""One-time, OPT-IN schema probe for the six exchange-market clients built in
the `exchange-markets-api-integration` lane (`docs/ai_context/todo.md #542`).

WHY THIS EXISTS. Every client module in that lane
(`syndicate/features/shared/{polymarket,novig,prophetx,coinbase,robinhood,
cryptocom}_client.py`) was written against RESEARCHED, not called, schemas --
this sandbox's agent proxy 403s CONNECT to every venue host. `refresh-worker`
is the one service with real outbound access (it already reaches OddsAPI,
statsapi and FotMob), so it is where each schema assumption actually gets
checked -- same role `pipeline/kalshi_discovery.py` plays for Kalshi.

**OFF BY DEFAULT.** `run_all_probes_if_enabled()` is a no-op unless
`SYNDICATE_EXCHANGE_MARKETS_PROBE_ON_BOOT=1` is set for the boot(s) that need
it. This is a diagnostic, not a standing feature -- set the flag, deploy,
read the resulting `[exchange_markets_probe]` log lines from
`refresh-worker`, then unset the flag on the next deploy. Every branch PRINTS
(`logger.info` never reaches Render's log collector) and NOTHING here raises
past its own try/except -- a probe failure must never affect worker startup,
the same discipline `scripts/run_refresh_worker.py`'s own boot sequence uses
for every optional diagnostic it installs.

Run standalone too:

    python scripts/probe_exchange_markets.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _env_bool(name: str, *, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


# (label, module path, callable name). Only the four venues with an actual
# schema to verify -- coinbase/robinhood have no distinct endpoint of their
# own (see their modules' FINDING) and their probe() calls already pass
# through to kalshi_client's, which `pipeline/kalshi_discovery.py` verifies
# separately.
_PROBES: tuple[tuple[str, str, str], ...] = (
    ("polymarket", "syndicate.features.shared.polymarket_client", "probe"),
    ("novig", "syndicate.features.shared.novig_client", "probe"),
    ("prophetx", "syndicate.features.shared.prophetx_client", "probe"),
    ("cryptocom_og", "syndicate.features.shared.cryptocom_client", "probe"),
    # Polymarket US's dedicated Sports API -- a DIFFERENT venue/credential
    # from the "polymarket" row above (see polymarket_us_sports_client.py's
    # header). Reports credentials_absent by name if this service does not
    # carry POLYMARKET_US_API_KEY_ID/PRIVATE_KEY -- that is an expected,
    # informative outcome here, not a probe failure.
    ("polymarket_us_sports", "syndicate.features.shared.polymarket_us_sports_client", "probe_all_leagues"),
)


def run_all_probes(*, limit: int = 4000) -> dict[str, Any]:
    """Run every probe and return the combined result. Never raises -- one
    venue's import or network failure must not stop the rest from running."""
    import importlib

    results: dict[str, Any] = {}
    for label, module_path, func_name in _PROBES:
        try:
            module = importlib.import_module(module_path)
            func = getattr(module, func_name)
            results[label] = func()
        except Exception as exc:  # noqa: BLE001 -- a probe must never crash the caller
            results[label] = {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
        print(
            f"[exchange_markets_probe] {label.upper()} "
            + json.dumps(results[label], default=str)[:limit],
            flush=True,
        )
    return results


def run_all_probes_if_enabled() -> dict[str, Any] | None:
    """The boot-time entry point. No-op unless the env flag is set."""
    if not _env_bool("SYNDICATE_EXCHANGE_MARKETS_PROBE_ON_BOOT", default=False):
        return None
    print("[exchange_markets_probe] STARTING", flush=True)
    results = run_all_probes()
    print("[exchange_markets_probe] DONE", flush=True)
    return results


def main() -> int:
    run_all_probes()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
