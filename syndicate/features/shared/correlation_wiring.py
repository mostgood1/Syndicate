"""Install the MEASURED same-game correlation resolver for a build's date.

`#621` Phase 4, the last mile. Three pieces existed and were not joined:

  * `correlation_engine.compute_correlation` accepts a `measured_lookup`
    (`1bbcc246`) and consults a process-wide registry when no caller passes one
    (`af83addb`), so all TEN of its call sites are reachable at once.
  * `syndicate.features.mlb.sim_joint_correlation.build_measured_lookup` reads
    the sim's joint artifact and returns exactly that callable (`ee083bd0`).
  * Nothing called the second and handed it to the first.

This module is that call, and it lives apart from both so the correlation engine
stays ignorant of MLB and of disk, and the MLB resolver stays ignorant of the
registry.

WHAT IT CHANGES, STATED PLAINLY. `compute_correlation` feeds parlay pricing, the
board correlation badges, and `bankroll_manager.build_portfolio` BET SIZING. So
this is a money path, and the number it replaces is a hand-authored constant
table -- one value for every player in every game. Measured on the sim's own
joint, `home_runs x total_bases` for the same batter ranges +0.227 (a contact
hitter) to +0.805 (a power hitter), 3.5x end to end. The cross-batter case is
the like-for-like one and it is worse: `total_bases x total_bases` measures
+0.097 same-team and +0.018 opposing, where the heuristic adds `same_game` 0.25
PLUS `same_team` 0.14 -- roughly a 4x overstatement.

INERT UNTIL THE DATA EXISTS, AND THAT IS DELIBERATE. The resolver answers `None`
for every pair until a `sim_*.json` carrying a `joint` block is on disk, and
producing one needs a deploy AND a sim RUN -- shipping code does not rewrite an
existing artifact. `None` falls back to the heuristic, so wiring this ahead of
the data changes nothing and then starts working by itself when the data lands.
That ordering is the whole point: the alternative is a resolver that has never
run in the process that will run it.

`None` IS NEVER `0.0`. The resolver refuses rather than defaults -- a measured
0.0 is a real and large claim ("these legs are independent") that would tell the
sizer to treat two legs as unrelated, and mapping "unknown" onto it is the
permissive-default failure this ledger names repeatedly. The counters below are
what distinguish "wired and answering" from "wired and silent", because a
resolver that returns `None` for everything is otherwise indistinguishable from
one nobody installed.
"""

from __future__ import annotations

from typing import Any, Mapping


def install_measured_correlation(selected_date: str) -> Mapping[str, Any]:
    """Register the measured resolver for `selected_date`. Never raises.

    Returns a small report so the caller can log what actually happened. A build
    that cannot install one continues on the heuristic, which is the documented
    degraded state and is exactly today's behaviour.
    """
    report: dict[str, Any] = {
        "installed": False,
        "date": str(selected_date or ""),
        "games_with_joint": 0,
        "reasons": {},
        "error": None,
    }
    if not str(selected_date or "").strip():
        report["error"] = "no_date"
        return report
    try:
        from syndicate.features.correlation_engine import (
            register_measured_correlation_resolver,
        )
        from syndicate.features.mlb.sim_joint_correlation import build_measured_lookup

        lookup, index = build_measured_lookup(str(selected_date))
        games = int(getattr(index, "games_with_joint", 0) or 0)
        report["games_with_joint"] = games
        try:
            report["reasons"] = dict(getattr(index, "reasons", {}) or {})
        except Exception:
            report["reasons"] = {}
        if games <= 0:
            # NOT INSTALLED, and the registry is left ALONE rather than cleared.
            # Clearing would be the same observable state by a different route,
            # and it would stamp on a resolver another build had installed.
            report["error"] = "no_joint_in_any_artifact"
            return report
        register_measured_correlation_resolver(lookup)
        report["installed"] = True
        return report
    except Exception as exc:  # pragma: no cover - defensive, must never raise
        report["error"] = "%s: %s" % (type(exc).__name__, exc)
        return report


def format_report(report: Mapping[str, Any]) -> str:
    """One line, and it must answer 'is the measured path live' without a
    second query -- a silent resolver and an absent one look identical
    otherwise."""
    return (
        "[correlation_wiring] MEASURED_CORRELATION "
        "installed=%s date=%s games_with_joint=%s reasons=%s error=%s"
        % (
            report.get("installed"),
            report.get("date"),
            report.get("games_with_joint"),
            report.get("reasons"),
            report.get("error"),
        )
    )
