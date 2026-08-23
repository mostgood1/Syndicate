"""Stage A runner: read the Layer 2 shortlist, commit a portfolio, persist it.

Worker-side, like everything that computes. Web reads the artifact this writes.

**DARK BY DEFAULT.** `SYNDICATE_PORTFOLIO_COMMIT_ENABLED` gates it, absent means
off, and `run_portfolio_commit` returns a `skipped` status rather than raising
when it is off -- the same dark-launch discipline every autorun in this repo
uses, and the thing that makes the `off != on` reachability test meaningful:
with the flag off the artifact must be ABSENT, with it on it must be PRESENT for
the same date. A feature that writes either way cannot be shown to be reachable.

**Why the plan is its own artifact rather than a key on the board state:**
exactly `write_layer2_shortlist`'s reasoning one layer up -- the canonical board
state is written only under two flags that both default False and are off in
production, so a plan that lived only there would be built correctly and
deposited where nothing reads it.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping

from syndicate.features.shared.portfolio_commit import commit_portfolio
from syndicate.features.shared.order_clv import (
    clv_for_orders,
    order_clv_report_line,
)
from syndicate.features.shared.position_marks import (
    mark_orders_to_board,
    marks_report_line,
)
from syndicate.features.shared.clv_position_join import (
    join_positions_to_openings,
    join_report_line,
)
from syndicate.features.shared.execution_ledger import execution_mode
from syndicate.features.shared.portfolio_settings import resolve_settings
from syndicate.features.shared.refresh_state_store import (
    read_json_file,
    reports_root,
    write_json_file,
)


def portfolio_commit_enabled() -> bool:
    raw = str(os.environ.get("SYNDICATE_PORTFOLIO_COMMIT_ENABLED") or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def portfolio_plan_path(selected_date: str) -> Path:
    # Date-tokened deliberately: this is a per-slate artifact and takes the
    # store's 10-day TTL, which comfortably covers settlement's 7-day
    # `EVALUATION_SETTLEMENT_LOOKBACK_DAYS` window.
    #
    # **Stage B's execution ledger must NOT copy this pattern.** A plan is a
    # recomputable recommendation; a record of money placed is not, and a
    # 10-day TTL on that would delete the evidence. See
    # `portfolio_settings._settings_path` for the date-free form.
    suffix = str(selected_date or "").strip().replace("-", "_")
    return reports_root() / "intelligence" / f"portfolio_plan_{suffix}.json"


def read_portfolio_plan(selected_date: str | None) -> dict[str, Any] | None:
    normalized = str(selected_date or "").strip()
    if not normalized:
        return None
    payload = read_json_file(portfolio_plan_path(normalized))
    return payload if isinstance(payload, dict) else None


def _execution_enabled() -> bool:
    """Imported inside the call: `execute_portfolio` imports this module."""
    from pipeline.execute_portfolio import execution_enabled

    return execution_enabled()


def _utc_now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_portfolio_commit(
    selected_date: str,
    *,
    settled_sample_size_by_sport: Mapping[str, int] | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Build and persist today's plan. Returns a status payload, never raises.

    `force` bypasses only the enablement flag, never the input checks -- a
    forced run on an absent shortlist still reports `no_shortlist` rather than
    writing an empty plan, because an empty plan and no plan are different
    facts and the reader needs to tell them apart.
    """
    normalized = str(selected_date or "").strip()
    if not normalized:
        return {"status": "skipped", "reason": "no_date"}
    if not (force or portfolio_commit_enabled()):
        return {"status": "skipped", "reason": "disabled", "date": normalized}

    from pipeline.intelligence_state import read_layer2_shortlist

    shortlist = read_layer2_shortlist(normalized)
    if not isinstance(shortlist, dict):
        print(f"[portfolio_commit] NO_SHORTLIST date={normalized}", flush=True)
        return {"status": "skipped", "reason": "no_shortlist", "date": normalized}

    rows = shortlist.get("rows")
    if not isinstance(rows, list):
        return {"status": "skipped", "reason": "shortlist_has_no_rows_key", "date": normalized}

    # THE GATE. Pure computation, no I/O, so it runs before every plan write.
    #
    # Harder than the reference implementation's `--warn-only`
    # (`run_mlb_daily_sim_job.py:506`) on purpose: the failure this catches does
    # not look like a failure. An unfed sizer writes a plan full of $0 positions
    # and a reader cannot tell it from a slate with no edges. Refusing to write
    # leaves the previous plan standing and an absence to explain, which is the
    # recoverable direction.
    try:
        import sys
        from pathlib import Path as _Path

        sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / "scripts"))
        from portfolio_commit_input_checklist import run_checklist

        checklist_ok, checklist_lines = run_checklist()
    except Exception as exc:
        print(f"[portfolio_commit] CHECKLIST_ERROR date={normalized} error={exc}", flush=True)
        return {"status": "error", "reason": f"checklist_error: {exc}", "date": normalized}
    if not checklist_ok:
        # Carry the failing lines, not just a verdict -- a check whose failure
        # message does not carry the evidence for the failure is one nobody can
        # act on (`learnings.md` 2026-08-16, FORBIDDEN).
        failures = [line for line in checklist_lines if line.startswith("FAIL")]
        for line in failures:
            print(f"[portfolio_commit] CHECKLIST_FAIL {line}", flush=True)
        return {
            "status": "error",
            "reason": "input_checklist_failed",
            "date": normalized,
            "failures": failures,
        }

    plan = commit_portfolio(
        rows,
        selected_date=normalized,
        settings=resolve_settings(),
        # S6 HOOK. Layer 2 rows carry no `historical_profile`, so this is empty
        # today and every market therefore sizes at `_MIN_SAMPLE_CREDIBILITY`
        # (0.25) -- which is correct while `settled_count` is 0 platform-wide.
        # When settlement starts producing records this is where the real
        # per-sport sample enters, and stakes rise on evidence rather than on a
        # constant being edited.
        settled_sample_size_by_sport=settled_sample_size_by_sport,
    )

    # Run the CLV join BEFORE the write, so its summary lands in the artifact the
    # web service reads. Web must not compute -- `/portfolio/paper` would
    # otherwise have to load ~3k opening records per request to show a match
    # rate, which is exactly the recompute-in-a-request-handler the architecture
    # forbids. The worker joins once; web reads the answer.
    #
    # `rows` is deliberately DROPPED from what gets stored: it duplicates every
    # position and would roughly double an artifact that has an 8MB keyvalue
    # refusal ceiling. The counters are what anybody reads.
    # WHERE THE JOBS ACTUALLY RUN, stamped by the process that runs them.
    # `/portfolio/paper` read these flags from its OWN environment and reported
    # "COMMIT JOB off / EXECUTION JOB off" on a page full of committed positions
    # and filled orders -- true of the web service, useless to a reader, and
    # exactly backwards as a status line. The flags are worker-side facts, so
    # the worker records them.
    plan["job_state"] = {
        "commit_enabled": True,
        "execution_enabled": _execution_enabled(),
        "execution_mode": execution_mode(),
        "recorded_by": "refresh-worker",
        "recorded_at": _utc_now_iso(),
    }

    # LIVE MARKS -- every order for this date re-priced against the board that
    # was just built. Covers orphans too: a bet whose position left the plan is
    # still a bet, and is usually the one you most want to look at.
    try:
        from syndicate.features.shared.execution_ledger import _load as _load_ledger

        todays_orders = [
            order
            for order in (_load_ledger().get("orders") or [])
            if order.get("selected_date") == normalized
        ]
        marks = mark_orders_to_board(todays_orders, rows)
        print(marks_report_line(marks), flush=True)
        plan["live_marks"] = marks
    except Exception as exc:
        print(f"[portfolio_commit] LIVE_MARKS_FAILED date={normalized} error={exc}", flush=True)

    # STAGE C'S GATE INPUT: what our placed orders got against the CLOSE.
    # Distinct from the join below, which is orders -> OPENING. A close only
    # exists once a market has stopped moving, so most of the day this resolves
    # nothing for today and everything for yesterday -- which is why it runs
    # over the ledger rather than over today's positions, and why an unresolved
    # row is named rather than dropped.
    try:
        from syndicate.features.shared.execution_ledger import _load as _load_ledger_for_clv

        dated_orders = [
            order
            for order in (_load_ledger_for_clv().get("orders") or [])
            if order.get("selected_date") == normalized
        ]
        if dated_orders:
            order_clv = clv_for_orders(dated_orders, date=normalized)
            print(order_clv_report_line(order_clv), flush=True)
            # `rows` dropped from the artifact for the same reason as the join
            # below: it duplicates every order against an 8MB ceiling. The
            # per-market aggregates are what a reader needs, and they carry `n`.
            plan["order_clv"] = {
                key: value for key, value in order_clv.items() if key != "rows"
            }
    except Exception as exc:
        print(f"[portfolio_commit] ORDER_CLV_FAILED date={normalized} error={exc}", flush=True)

    clv_join = None
    try:
        report = join_positions_to_openings(plan.get("positions") or [], date=normalized)
        print(join_report_line(report), flush=True)
        for example in report.get("disagreement_examples") or []:
            # A count says the derivation is wrong; an example says which field.
            print(
                f"[portfolio_commit] CLV_KEY_DISAGREEMENT position={example.get('position_key')} "
                f"stamped={example.get('stamped')} derived={example.get('derived')}",
                flush=True,
            )
        clv_join = {key: value for key, value in report.items() if key != "rows"}
        plan["clv_join"] = clv_join
    except Exception as exc:
        # A DIAGNOSTIC must never cost a slate. The plan is complete either way.
        print(f"[portfolio_commit] CLV_JOIN_FAILED date={normalized} error={exc}", flush=True)

    try:
        write_json_file(portfolio_plan_path(normalized), plan)
    except Exception as exc:
        print(f"[portfolio_commit] PLAN_WRITE_FAILED date={normalized} error={exc}", flush=True)
        return {"status": "error", "reason": f"write_failed: {exc}", "date": normalized}

    totals = plan.get("totals") or {}
    # print, not logger.info -- logger.info never reaches Render's collector.
    print(
        f"[portfolio_commit] PLAN_WRITTEN date={normalized} "
        f"rows_in={plan.get('rows_in')} sized={plan.get('sized')} "
        f"positions={totals.get('positions')} staked=${totals.get('staked_dollars')} "
        f"bankroll=${plan.get('bankroll_units')} scale={totals.get('slate_scale_factor')} "
        f"refusals={plan.get('refusals')}",
        flush=True,
    )
    return {"status": "ok", "date": normalized, "plan": plan, "clv_join": clv_join}


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Commit a portfolio from the Layer 2 shortlist.")
    parser.add_argument("--date", required=True, help="slate date, YYYY-MM-DD")
    parser.add_argument("--force", action="store_true", help="ignore the enablement flag")
    args = parser.parse_args()
    result = run_portfolio_commit(args.date, force=args.force)
    print(result.get("status"), result.get("reason") or "")
    return 0 if result.get("status") in {"ok", "skipped"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
