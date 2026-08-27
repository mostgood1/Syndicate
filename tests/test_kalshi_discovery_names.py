"""Every global name `kalshi_discovery` calls must actually resolve.

WHY THIS TEST EXISTS. `run_kalshi_discovery` called `probe()`, `discover()` and
`KalshiError` and imported none of them. The call sites sit inside
`try/except Exception` blocks whose whole purpose is to survive a venue that
will not answer, so `NameError: name 'probe' is not defined` was caught,
logged as a probe failure, and returned -- indistinguishable from Kalshi being
unreachable. Nine consecutive boots on 2026-08-24 (21:32Z through 23:45Z)
produced that line and nobody read it as a bug in our own module.

A unit test that mocks the client cannot catch this: mocking `probe` binds the
name the code was missing. So this walks the module's own bytecode instead and
asserts every LOAD_GLOBAL resolves against the module namespace or builtins --
which is exactly the check the interpreter defers to runtime, moved to import
time where CI sees it.
"""

from __future__ import annotations

import builtins
import dis
import types


def _global_loads(func: types.FunctionType) -> set[str]:
    names: set[str] = set()
    seen: set[int] = set()

    def walk(code) -> None:
        if id(code) in seen:
            return
        seen.add(id(code))
        for instruction in dis.get_instructions(code):
            if instruction.opname in {"LOAD_GLOBAL", "LOAD_NAME"}:
                names.add(str(instruction.argval))
        for const in code.co_consts:
            if isinstance(const, types.CodeType):
                walk(const)

    walk(func.__code__)
    return names


def test_every_global_kalshi_discovery_calls_RESOLVES() -> None:
    import pipeline.kalshi_discovery as module

    unresolved = sorted(
        name
        for name in _global_loads(module.run_kalshi_discovery)
        if not hasattr(module, name) and not hasattr(builtins, name)
    )
    assert unresolved == [], (
        "run_kalshi_discovery loads global names that do not exist, so every "
        f"call raises NameError inside a broad except and looks like a venue "
        f"failure: {unresolved}"
    )


def test_the_three_names_the_missing_imports_cost_us_are_BOUND() -> None:
    """Named individually so a future edit that drops one is a specific failure."""
    import pipeline.kalshi_discovery as module

    for name in ("probe", "discover", "KalshiError"):
        assert hasattr(module, name), f"{name} is not imported into kalshi_discovery"


def test_discovery_registers_GAME_series_not_only_props(monkeypatch) -> None:
    """The board-building process needs game lines registered in ITS OWN state.

    Discovery is per-process, so `kalshi_odds_refresh` registering game series
    in the odds-refresh process leaves this one able to count zero moneylines
    -- which is what `kalshi_polymarket_arb` reported on every scan.
    """
    from syndicate.features.shared import kalshi_catalogue as cat

    module = __import__("pipeline.kalshi_discovery", fromlist=["run_kalshi_discovery"])
    monkeypatch.setattr(module, "_ALREADY_RAN", False, raising=False)
    monkeypatch.setattr(
        module, "probe", lambda **_: {"attempts": [{"ok": True, "base": "b"}]}
    )
    monkeypatch.setattr(
        module,
        "discover",
        lambda **_: {"count": 0, "by_series_singles": {}, "markets": []},
    )
    titles = {"KXMLBGAMETESTZZ": "Baseball Moneyline"}
    monkeypatch.setattr(
        "syndicate.features.shared.kalshi_client.discover_series",
        lambda **_: {"status": "ok", "titles": titles},
    )
    monkeypatch.setitem(cat.SERIES_SPORT, "KXMLBGAMETESTZZ", "mlb")

    calls: list[dict] = []
    real_register = cat.register_discovered
    monkeypatch.setattr(
        cat,
        "register_discovered",
        lambda found: (calls.append(dict(found)), real_register(found))[1],
    )

    module.run_kalshi_discovery(force=True)

    assert len(calls) == 2, (
        "expected discovery to register BOTH prop series and game series; "
        f"it made {len(calls)} registration call(s)"
    )
