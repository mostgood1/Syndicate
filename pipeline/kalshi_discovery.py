"""Run Kalshi discovery ONCE per worker boot, and log what came back.

WHY ONCE PER BOOT rather than a refresh job. This answers a QUESTION -- what
does Kalshi actually list -- and a question does not need re-asking every three
minutes. `run_refresh_worker.py`'s autorun chain is an exclusive `elif` whose
own comment says the only shape safe near the front is daily-gated and inline;
a network call added to that chain would either steal ticks from the refresh
branches or starve at the back the way settlement did in `#504`. Once per boot
is neither: it costs one HTTP request per deploy and cannot compete for a slot.

IT IS ALSO NOT IN THE ARTIFACT PIPELINE. `bet_status_mlb` passes
`fetch_if_missing=False` precisely to keep live HTTP out of the board build
(`#506`: 15 statsapi calls per request, 3318-8400ms). This runs beside that
pipeline, before it, guarded, and its failure is a logged line rather than
anything a board build waits on.

WHAT IT IS FOR. Every exchange price on the board arrives via OddsAPI, which
carries game lines only for these venues. So the coverage figures measured on
2026-08-23 -- kalshi 1.93%, novig 1.74%, polymarket 1.54%, prophetx 1.16% of a
1,037-row board -- are statements about OddsAPI, not about the venues. This is
the first reading that is actually about Kalshi.
"""

from __future__ import annotations

import os
from typing import Any

_ALREADY_RAN = False


def kalshi_discovery_enabled() -> bool:
    """Default ON. It is one request per boot and it answers a blocking question.

    Absent means ON here deliberately: a flag defaulting off would leave the
    Stage D decision resting on the OddsAPI figure indefinitely while looking
    installed -- `#284`'s "absent is not off" read in the direction that costs
    a measurement rather than money. Nothing here can trade.
    """
    raw = os.environ.get("SYNDICATE_KALSHI_DISCOVERY_ENABLED")
    if raw is None:
        return True
    return str(raw).strip().lower() not in {"0", "false", "no", "off"}


def run_kalshi_discovery(*, force: bool = False) -> dict[str, Any]:
    """Probe the schema, then report what Kalshi lists. Never raises."""
    global _ALREADY_RAN

    if not (force or kalshi_discovery_enabled()):
        return {"status": "skipped", "reason": "disabled"}
    if _ALREADY_RAN and not force:
        return {"status": "skipped", "reason": "already_ran_this_boot"}
    _ALREADY_RAN = True

    from syndicate.features.shared.kalshi_client import KalshiError, discover, probe

    # SCHEMA FIRST, and reported separately from the data. The field names in
    # `kalshi_client` were written without ever calling the API (the agent proxy
    # denies the host from a Claude session), so this line is what turns them
    # from an assumption into a checked fact -- or names the ones that are wrong.
    try:
        shape = probe()
        attempt = next((a for a in shape.get("attempts") or [] if a.get("ok")), None)
        if attempt is None:
            errors = "; ".join(
                str(a.get("error")) for a in (shape.get("attempts") or [])
            )
            print(f"[kalshi_discovery] PROBE_FAILED {errors}", flush=True)
            return {"status": "error", "reason": "probe_failed", "detail": errors}
        print(
            "[kalshi_discovery] PROBE_OK"
            f" base={attempt.get('base')}"
            f" market_keys={attempt.get('market_keys')}"
            # Non-empty on either side means my field names are wrong, and says
            # exactly which -- the whole point of probing before parsing.
            f" expected_but_absent={attempt.get('expected_but_absent')}"
            f" present_but_unexpected={attempt.get('present_but_unexpected')}",
            flush=True,
        )
    except Exception as exc:
        print(f"[kalshi_discovery] PROBE_ERROR {type(exc).__name__}: {exc}", flush=True)
        return {"status": "error", "reason": f"probe_error: {exc}"}

    try:
        report = discover()
    except KalshiError as exc:
        # Loud. An empty result would read as "Kalshi lists nothing", which is
        # the precise wrong conclusion this exists to prevent.
        print(f"[kalshi_discovery] DISCOVER_FAILED {exc}", flush=True)
        return {"status": "error", "reason": str(exc)}
    except Exception as exc:
        print(f"[kalshi_discovery] DISCOVER_ERROR {type(exc).__name__}: {exc}", flush=True)
        return {"status": "error", "reason": f"{type(exc).__name__}: {exc}"}

    top = list(report.get("by_series", {}).items())[:15]
    print(
        "[kalshi_discovery] LISTED"
        f" markets={report.get('count')}"
        f" series={report.get('series_count')}"
        f" pages={report.get('pages')}"
        # `truncated` matters: a capped listing under-reports what Kalshi has,
        # and reading it as the whole catalogue is the same class of error as
        # reading OddsAPI's view as Kalshi's.
        f" truncated={report.get('truncated')}"
        f" missing_fields={report.get('missing_fields')}"
        f" top_series={top}",
        flush=True,
    )
    for series, example in list((report.get("series_examples") or {}).items())[:15]:
        print(f"[kalshi_discovery] SERIES {series} :: {example}", flush=True)
    return {"status": "ok", "report": report}
