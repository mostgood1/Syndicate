"""Verify the 2026-08-02/03 shipped work against the LIVE production board.

Several changes shipped in that window are wired end to end but had never
executed against real data, because they need conditions no unit test and
no idle-board check can produce -- a live slate, or accumulated settled
bets. Rather than assume they work, this script checks each one against
production and reports PASS / FAIL / PENDING, where PENDING explicitly
means "the precondition for judging this has not occurred yet" and is NOT
counted as success.

Run it against a live slate (an in-progress WNBA or MLB game):

    python scripts/verify_recent_shipped_work.py

Requires ADMIN_TOKEN (read from the environment, or from a local .env).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASE_URL = "https://syndicate-an21.onrender.com"

PASS = "PASS"
FAIL = "FAIL"
PENDING = "PENDING"


def _load_admin_token() -> str:
    token = str(os.environ.get("ADMIN_TOKEN") or os.environ.get("SYNDICATE_ADMIN_TOKEN") or "").strip()
    if token:
        return token
    env_path = REPO_ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            if key.strip() in {"ADMIN_TOKEN", "SYNDICATE_ADMIN_TOKEN"}:
                return value.strip().strip('"').strip("'")
    return ""


def _get_json(base_url: str, path: str, token: str, timeout: int = 180) -> Any:
    request = urllib.request.Request(f"{base_url.rstrip('/')}{path}", headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _numeric(value: Any) -> float | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _candidates(status: Any) -> list[dict[str, Any]]:
    rows = status.get("top_opportunities") if isinstance(status, dict) else None
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def check_stakes(status: Any) -> tuple[str, str]:
    """Fractional-Kelly stakes reach real candidates (commit 25dc6a01).

    _attach_board_stakes swallows per-candidate errors by design, so an
    exception inside it ships a board with NO stakes and no error anywhere.
    This asserts they are actually attached.
    """
    candidates = _candidates(status)
    if not candidates:
        return PENDING, "No candidates on the board to inspect."
    staked = [c for c in candidates if isinstance(c.get("stake"), dict)]
    if not staked:
        return FAIL, f"0 of {len(candidates)} candidates carry a stake -- the attach hook is silently failing."
    priced = [c for c in staked if _numeric(c["stake"].get("stake_fraction")) is not None]
    if not priced:
        return FAIL, f"{len(staked)} stakes attached but none carry a numeric stake_fraction."
    sample = priced[0]["stake"]
    return PASS, (
        f"{len(staked)}/{len(candidates)} candidates staked; "
        f"e.g. fraction={sample.get('stake_fraction')} units={sample.get('stake_units')} "
        f"multiplier={sample.get('kelly_multiplier')} credibility={sample.get('sample_credibility')}"
    )


def check_exposure_budgets(status: Any) -> tuple[str, str]:
    """Correlated legs on one game get shrunk (commit 4d9d0ac4).

    Only judgeable when some game actually has multiple staked legs.
    """
    candidates = [c for c in _candidates(status) if isinstance(c.get("stake"), dict)]
    if not candidates:
        return PENDING, "No staked candidates to inspect."
    by_game: dict[str, list[dict[str, Any]]] = {}
    for candidate in candidates:
        key = str(
            candidate.get("event_id")
            or candidate.get("game_id")
            or candidate.get("gamePk")
            or candidate.get("matchup")
            or ""
        ).strip()
        if key:
            by_game.setdefault(key, []).append(candidate)
    multi = {key: rows for key, rows in by_game.items() if len(rows) > 1}
    if not multi:
        return PENDING, "No game currently has multiple staked legs -- nothing to budget."
    annotated = [
        row
        for rows in multi.values()
        for row in rows
        if "stake_fraction_pre_exposure" in row.get("stake", {})
    ]
    if not annotated:
        return FAIL, f"{len(multi)} multi-leg game(s) but none carry stake_fraction_pre_exposure -- budgets never ran."
    shrunk = [
        row
        for row in annotated
        if (_numeric(row["stake"].get("stake_fraction")) or 0.0)
        < (_numeric(row["stake"].get("stake_fraction_pre_exposure")) or 0.0) - 1e-9
    ]
    return PASS, (
        f"{len(multi)} multi-leg game(s); {len(annotated)} legs budgeted, {len(shrunk)} actually shrunk."
    )


def check_decided_prop_guard(status: Any) -> tuple[str, str]:
    """No effectively-decided live prop is served as an opportunity
    (commits c6a8b62c + 869e0645).

    Game-level steam candidates legitimately sit at probability 1.0 and are
    out of the guard's scope by design, so they are excluded here.
    """
    candidates = _candidates(status)
    live_props = [
        c
        for c in candidates
        if bool(c.get("is_live")) and str(c.get("candidate_type") or "").strip().lower() == "prop"
    ]
    if not live_props:
        return PENDING, "No live player props on the board -- needs a live slate."
    saturated = [c for c in live_props if (_numeric(c.get("model_probability")) or 0.0) >= 0.97]
    if saturated:
        names = ", ".join(str(c.get("player_name") or c.get("selection"))[:28] for c in saturated[:3])
        return FAIL, f"{len(saturated)} of {len(live_props)} live props still >= 0.97 (e.g. {names})."
    return PASS, f"{len(live_props)} live props on the board, none saturated at >= 0.97."


def check_live_sigma(status: Any) -> tuple[str, str]:
    """The WNBA/NBA live variance model actually executes (c6a8b62c, bd8851a8).

    live_probability_source == "live_sigma_normal" has never once appeared
    in production; both sports were idle at every deploy.
    """
    candidates = _candidates(status)
    basketball_live = [
        c
        for c in candidates
        if bool(c.get("is_live"))
        and str(c.get("sport") or "").strip().lower() in {"wnba", "nba"}
        and str(c.get("candidate_type") or "").strip().lower() == "prop"
    ]
    if not basketball_live:
        return PENDING, "No live WNBA/NBA props -- the sigma model cannot run without one."
    sourced = [c for c in basketball_live if str(c.get("live_probability_source") or "") == "live_sigma_normal"]
    if not sourced:
        return FAIL, f"{len(basketball_live)} live basketball props but none report live_sigma_normal."
    return PASS, f"{len(sourced)}/{len(basketball_live)} live basketball props priced by the sigma model."


def check_price_clv(base_url: str, token: str) -> tuple[str, str]:
    """clv_price goes non-null once settled bets carry closing prices
    (commit c3220c4a)."""
    try:
        summary = _get_json(base_url, "/api/portfolio/summary", token)
    except Exception as exc:
        return PENDING, f"Could not read portfolio summary ({type(exc).__name__})."
    settled = _numeric(summary.get("settled_count")) or _numeric(summary.get("settled")) or 0.0
    if settled <= 0:
        return PENDING, "No settled bets yet -- price CLV has nothing to average."
    clv_price = summary.get("clv_price")
    if clv_price is None:
        return FAIL, f"{int(settled)} settled bets but clv_price is still null -- closing prices are not being captured."
    return PASS, f"clv_price={clv_price} over {int(settled)} settled bets."


def check_keyvalue_usage(base_url: str, token: str) -> tuple[str, str]:
    """migration_runs should fall sharply as pre-truncation keys age out
    (commit 44b0f247). Measured at 185.71MB / 2,549 keys on 2026-08-03."""
    try:
        usage = _get_json(base_url, "/api/ops/keyvalue/usage?top_keys=1", token)
    except Exception as exc:
        return PENDING, f"Could not read keyvalue usage ({type(exc).__name__})."
    buckets = usage.get("buckets") if isinstance(usage.get("buckets"), list) else []
    migration = next((b for b in buckets if "migration_runs" in str(b.get("bucket") or "")), None)
    total_mb = usage.get("total_estimated_mb")
    if migration is None:
        return PASS, f"No migration_runs bucket remains; total={total_mb}MB."
    mb = _numeric(migration.get("mb")) or 0.0
    detail = f"migration_runs={mb}MB across {migration.get('key_count')} keys; total={total_mb}MB (was 185.71MB/2549)."
    if mb >= 185.0:
        return FAIL, "No reduction yet -- " + detail
    if mb > 50.0:
        return PENDING, "Falling but still large (old keys aging out) -- " + detail
    return PASS, detail


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    args = parser.parse_args()

    token = _load_admin_token()
    if not token:
        print("ADMIN_TOKEN not found in environment or .env", file=sys.stderr)
        return 2

    try:
        status = _get_json(args.base_url, "/api/intelligence/status", token)
    except Exception as exc:
        print(f"Could not read the board: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    results: list[tuple[str, str, str]] = [
        ("kelly stakes attached", *check_stakes(status)),
        ("correlated exposure budgets", *check_exposure_budgets(status)),
        ("decided-prop guard", *check_decided_prop_guard(status)),
        ("live sigma model executes", *check_live_sigma(status)),
        ("price CLV populated", *check_price_clv(args.base_url, token)),
        ("keyvalue reduction", *check_keyvalue_usage(args.base_url, token)),
    ]

    print(f"\nBoard: {status.get('candidate_count')} candidates, generated {status.get('snapshot_generated_at')}\n")
    width = max(len(name) for name, _, _ in results)
    for name, verdict, detail in results:
        print(f"  [{verdict:>7}] {name.ljust(width)}  {detail}")

    failed = [name for name, verdict, _ in results if verdict == FAIL]
    pending = [name for name, verdict, _ in results if verdict == PENDING]
    print()
    if failed:
        print(f"FAILED: {', '.join(failed)}")
    if pending:
        print(f"PENDING (precondition not met -- NOT a pass): {', '.join(pending)}")
    if not failed and not pending:
        print("All checks passed.")
    # Pending is not failure: the condition to judge simply has not occurred.
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
