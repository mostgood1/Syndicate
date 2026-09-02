"""The guard every local fleet child loads BEFORE any Syndicate code. `#625`(4).

Imported from a generated `sitecustomize.py` that `fleet_local.py` places first
on the child's `PYTHONPATH`. CPython imports `sitecustomize` during interpreter
startup, before `__main__`, which is the only hook that reaches **gunicorn** as
well as a plain `python scripts/run_*.py` — the three roles do not share an
entrypoint, so a guard installed in any one of them would miss the others.

WHY A GUARD AT ALL, AND WHY IT FAILS CLOSED
-------------------------------------------
Read off the live services on 2026-09-02, live-odds-worker runs:

    SYNDICATE_EXECUTION_MODE=live        SYNDICATE_EXECUTION_LIVE_ARMED=1
    SYNDICATE_EXECUTION_ENABLED=1        SYNDICATE_EXECUTION_VENUE=kalshi,polymarket
    KALSHI_PRIVATE_KEY=<1616 chars>      POLYMARKET_US_PRIVATE_KEY=<88 chars>
    SYNDICATE_EXECUTION_MAX_DAY_DOLLARS=40   ..._ALL_VENUES=150

and both workers carry `SYNDICATE_WEB_PUBLISH_URL`, a POST that writes onto
production web's disk. **So a local run that inherits production env places real
money orders and mutates production.** That is not a hypothetical: it is what
those processes are configured to do, and the whole point of `#625`(4) is to
make running them locally something other than an accident.

`fleet_local.py` scrubs the environment before launching. This module is the
SECOND, INDEPENDENT mechanism, because a scrub is a thing that can be
mis-implemented, edited, or bypassed by someone running the command by hand:
whatever the parent believed it did, this refuses to let the interpreter
continue if money is armed. It runs inside the child, after the environment is
final, and it raises rather than warns.

Three independent things stop an order, so any ONE of them holding is enough:
  1. `SYNDICATE_EXECUTION_MODE` != "live"  -> `execution_mode()` returns PAPER
     (`execution_ledger.py:233` — anything not literally "live" is paper).
  2. `SYNDICATE_EXECUTION_LIVE_ARMED` falsy -> `live_execution_armed()` False
     (`execution_ledger.py:244`).
  3. No venue credentials in the environment -> nothing can sign a submit.
This module asserts all three and refuses on any one of them failing.
"""

from __future__ import annotations

import json
import os
import socket
import sys
import time
from pathlib import Path

RECEIPT_ENV = "SYNDICATE_FLEET_GUARD_RECEIPT"
MODE_ENV = "SYNDICATE_FLEET_FETCH_MODE"
ROLE_ENV = "SYNDICATE_FLEET_ROLE"

# Any of these present with a value means something in this process could sign a
# venue request. The guard refuses rather than trusting that the code path is
# not reached -- "it is not called today" is not a property of the environment.
VENUE_CREDENTIAL_ENV: tuple[str, ...] = (
    "KALSHI_API_KEY_ID",
    "KALSHI_PRIVATE_KEY",
    "POLYMARKET_US_API_KEY_ID",
    "POLYMARKET_US_PRIVATE_KEY",
    "POLYMARKET_API_KEY",
    "POLYMARKET_PRIVATE_KEY",
)

# Credentials that spend a shared, metered budget or grant production write
# access. Not money-in-a-market, but not free either: the OddsAPI key is a 5M
# call cap shared with production, CFBD's monthly quota is already exhausted
# (`#633`), and ADMIN_TOKEN plus the publish URL are production write paths.
SHARED_BUDGET_ENV: tuple[str, ...] = (
    "ODDS_API_KEY",
    "THE_ODDS_API_KEY",
    "ODDSAPI_KEY",
    "CFBD_API_KEY",
    "ADMIN_TOKEN",
    "SYNDICATE_ADMIN_TOKEN",
    "SYNDICATE_WEB_PUBLISH_URL",
)


class FleetGuardRefused(RuntimeError):
    """Raised during interpreter startup. Nothing Syndicate has imported yet."""


def _truthy(name: str) -> bool:
    return str(os.environ.get(name) or "").strip().lower() in {"1", "true", "yes", "on"}


def assert_money_is_off() -> list[str]:
    """Return the reasons money CANNOT be spent, or raise. Never returns empty."""
    reasons: list[str] = []
    failures: list[str] = []

    mode = str(os.environ.get("SYNDICATE_EXECUTION_MODE") or "").strip().lower()
    if mode == "live":
        failures.append("SYNDICATE_EXECUTION_MODE=live")
    else:
        reasons.append(f"execution mode is {mode or '<unset>'} -> PAPER")

    if _truthy("SYNDICATE_EXECUTION_LIVE_ARMED"):
        failures.append("SYNDICATE_EXECUTION_LIVE_ARMED is truthy")
    else:
        reasons.append("live execution is not armed")

    present = [name for name in VENUE_CREDENTIAL_ENV if str(os.environ.get(name) or "").strip()]
    if present:
        failures.append(f"venue credentials present: {', '.join(sorted(present))}")
    else:
        reasons.append("no venue credentials in the environment")

    if failures:
        raise FleetGuardRefused(
            "REFUSING TO START A LOCAL FLEET PROCESS THAT COULD SPEND MONEY.\n  "
            + "\n  ".join(failures)
            + "\n\nThis is the local fleet guard (`scripts/_fleet_guard.py`), running inside the\n"
            "child before any Syndicate code is imported. Start the fleet through\n"
            "`scripts/fleet_local.py`, which scrubs these; do not set them by hand."
        )
    return reasons


def install_network_guard(record: list[dict[str, object]]) -> None:
    """Deny every outbound connection and RECORD what was attempted.

    Recording matters as much as denying: "would this role have called out, and
    where to?" is otherwise answered by reading code, and reading is how a
    conditional fetch behind a cache check gets missed.

    Loopback is ALLOWED. The roles legitimately talk to each other and to a
    local redis, and a guard that broke that would make the fleet untestable --
    which is how a guard gets switched off.
    """

    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex
    original_create_connection = socket.create_connection

    def _local(address: object) -> bool:
        if not isinstance(address, tuple) or not address:
            return False
        host = str(address[0])
        return host in {"127.0.0.1", "::1", "localhost", "0.0.0.0", ""} or host.startswith("127.")

    def _deny(where: str, address: object) -> None:
        host, port = (address[0], address[1]) if isinstance(address, tuple) and len(address) >= 2 else (address, None)
        record.append({"via": where, "host": str(host), "port": port, "at": time.time()})
        path = os.environ.get(RECEIPT_ENV)
        if path:
            try:
                Path(path).with_suffix(".network.jsonl").open("a", encoding="utf-8").write(
                    json.dumps({"role": os.environ.get(ROLE_ENV), "via": where, "host": str(host), "port": port}) + "\n"
                )
            except Exception:
                pass
        raise OSError(
            f"local fleet is in REPLAY mode: {where} to {host}:{port} denied. "
            "One-way flows (`#625` law 1): a local run must not read from or write to production. "
            "Re-run with --fetch live if an outbound call is genuinely intended."
        )

    def guarded_connect(self, address):  # type: ignore[no-untyped-def]
        if _local(address):
            return original_connect(self, address)
        _deny("socket.connect", address)

    def guarded_connect_ex(self, address):  # type: ignore[no-untyped-def]
        if _local(address):
            return original_connect_ex(self, address)
        _deny("socket.connect_ex", address)

    def guarded_create_connection(address, *args, **kwargs):  # type: ignore[no-untyped-def]
        if _local(address):
            return original_create_connection(address, *args, **kwargs)
        _deny("socket.create_connection", address)

    socket.socket.connect = guarded_connect  # type: ignore[method-assign]
    socket.socket.connect_ex = guarded_connect_ex  # type: ignore[method-assign]
    socket.create_connection = guarded_create_connection  # type: ignore[assignment]


def engage() -> dict[str, object]:
    """Run every guard and write the receipt the parent verifies.

    THE RECEIPT IS THE POINT. A guard that silently failed to load would leave
    the child running with production credentials and nothing saying so, and the
    parent cannot see inside the child. So the child writes what it did, and
    `fleet_local.py` refuses to consider a role started until it has read one.
    `presence is not reachability`, applied to the harness itself.
    """
    receipt: dict[str, object] = {
        "role": os.environ.get(ROLE_ENV),
        "pid": os.getpid(),
        "python": sys.executable,
        "guard_file": __file__,
        "fetch_mode": (os.environ.get(MODE_ENV) or "replay").strip().lower(),
        "engaged_at": time.time(),
    }
    # `os._exit`, NOT a raise. MEASURED 2026-09-02: a `sitecustomize` that
    # raises does NOT stop the interpreter. CPython's `site.execsitecustomize`
    # catches the exception, prints
    #
    #     Error in sitecustomize; set PYTHONVERBOSE for traceback:
    #     RuntimeError: GUARD REFUSED
    #
    # and CARRIES ON — verified with a one-line probe: the process printed its
    # own output and exited **rc=0**. So the first version of this guard was a
    # guard that announced its refusal and then let the money-armed process run.
    # It read as correct, it produced an error message, and it stopped nothing.
    # `fleet_local.py doctor`'s negative control is what caught it, before any
    # role was started.
    #
    # `os._exit` skips atexit handlers and cannot be caught by anything. That is
    # the point: a refusal that another frame can swallow is not a refusal.
    try:
        receipt["money_off_because"] = assert_money_is_off()
    except FleetGuardRefused as refusal:
        sys.stderr.write(f"\n{refusal}\n")
        sys.stderr.flush()
        os._exit(70)
    shared = [name for name in SHARED_BUDGET_ENV if str(os.environ.get(name) or "").strip()]
    receipt["shared_budget_credentials_present"] = shared
    if receipt["fetch_mode"] == "replay":
        install_network_guard([])
        receipt["network"] = "DENIED (loopback allowed)"
    else:
        # Explicit, and recorded in the receipt so a run that spent real quota
        # is identifiable afterwards rather than reconstructed.
        receipt["network"] = "LIVE -- outbound allowed by explicit --fetch live"
    path = os.environ.get(RECEIPT_ENV)
    if path:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(receipt, indent=2, default=str), encoding="utf-8")
    return receipt
