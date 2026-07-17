"""Validation exercise for the expanded SmartSim 2.0 NCAAF public trial.

Three checks, matching the methodology used in Phase 3 (`smartsim_public_trial_report.md`)
and Public Trial Operations (`smartsim_public_trial_monitoring_report.md`), re-run now
against the expanded (38-token) cohort from `smartsim_expanded_trial_plan.md`:

1. Access control: a sample of tokens from every tier (old and new) is granted
   trial content on real HTTP requests (Flask test client); no-token and
   invalid-token requests are denied. All are real HTTP round trips, not mocks.
2. Publication-gate parity: build the same week's cards context three ways
   (trial off / trial on with a valid token / trial on with an invalid token)
   and diff every game's `coverage_score`/`publication_status`. These must be
   byte-identical across all three -- trial visibility must never change what
   publishes or how it's prioritized.
3. Monitoring instrumentation: after the access-control requests above, read
   the trial monitoring log's newest entries and summarize availability/
   visibility/fallback rates.

**Disclosure, stated as plainly as every prior report on this mechanism has
stated it**: the "page views" this script generates are Flask test-client
requests, not organic clicks from real people. This is a validation exercise
proving the operational mechanism still works correctly at the expanded
cohort size -- it is not a report of real usage.

Does not modify SmartSim 2.0, calibration profiles, blend formulas, or the
decision policy -- it only drives already-built code paths with test requests.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from syndicate.app import create_app  # noqa: E402
from syndicate.features.ncaaf.cards import build_smartsim_cards_page_context  # noqa: E402
from syndicate.features.ncaaf.smartsim2_trial_monitoring import MONITORING_LOG_PATH  # noqa: E402
from syndicate.features.ncaaf.smartsim2_trial_monitoring import read_monitoring_log  # noqa: E402
from syndicate.features.ncaaf.sources import default_ncaaf_source_root  # noqa: E402

COHORT_PATH = default_ncaaf_source_root() / "data" / "smartsim2_trial_cohort.json"
VALIDATION_WEEK = 1
TRIAL_QUERY_PARAM = "smartsim_trial"


def load_cohort() -> list[dict]:
    with COHORT_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)["cohort"]


def sample_one_token_per_role(cohort: list[dict]) -> dict[str, str]:
    sample = {}
    for entry in cohort:
        sample.setdefault(entry["role"], entry["token"])
    return sample


def check_access_control(app, all_tokens: list[str], sample_tokens: dict[str, str]) -> dict:
    client = app.test_client()
    results = {"granted": {}, "denied": {}}
    for role, token in sample_tokens.items():
        resp = client.get(f"/ncaaf/cards?week={VALIDATION_WEEK}&{TRIAL_QUERY_PARAM}={token}")
        body = resp.get_data(as_text=True)
        results["granted"][role] = {
            "status": resp.status_code,
            "trial_panel_present": "Model Comparison" in body,
        }

    resp_no_token = client.get(f"/ncaaf/cards?week={VALIDATION_WEEK}")
    resp_bad_token = client.get(f"/ncaaf/cards?week={VALIDATION_WEEK}&{TRIAL_QUERY_PARAM}=not-a-real-token")
    results["denied"]["no_token"] = {
        "status": resp_no_token.status_code,
        "trial_panel_present": "Model Comparison" in resp_no_token.get_data(as_text=True),
    }
    results["denied"]["invalid_token"] = {
        "status": resp_bad_token.status_code,
        "trial_panel_present": "Model Comparison" in resp_bad_token.get_data(as_text=True),
    }
    return results


def check_publication_gate_parity(app, valid_token: str) -> dict:
    def snapshot(query_suffix: str) -> dict[str, tuple[float | None, str | None]]:
        with app.test_request_context(f"/ncaaf/cards?week={VALIDATION_WEEK}{query_suffix}"):
            context = build_smartsim_cards_page_context(VALIDATION_WEEK)
        out = {}
        for game in context.get("games", []):
            card = game.get("ncaaf_card") or {}
            summary = card.get("summary") or {}
            out[game["gamePk"]] = (summary.get("coverage_score"), summary.get("publication_status"))
        return out

    baseline = snapshot("")
    with_valid_token = snapshot(f"&{TRIAL_QUERY_PARAM}={valid_token}")
    with_invalid_token = snapshot(f"&{TRIAL_QUERY_PARAM}=not-a-real-token")

    def diff(a: dict, b: dict) -> list[str]:
        mismatches = []
        for key in set(a) | set(b):
            if a.get(key) != b.get(key):
                mismatches.append(key)
        return mismatches

    return {
        "n_games": len(baseline),
        "mismatches_baseline_vs_valid_token": diff(baseline, with_valid_token),
        "mismatches_baseline_vs_invalid_token": diff(baseline, with_invalid_token),
        "mismatches_valid_vs_invalid_token": diff(with_valid_token, with_invalid_token),
    }


def check_monitoring(before_count: int) -> dict:
    records = read_monitoring_log()
    new_records = records[before_count:]
    if not new_records:
        return {"n_new_records": 0}
    avg_availability = sum(r["projection_availability_rate"] for r in new_records) / len(new_records)
    avg_visibility = sum(r["smartsim2_visibility_rate"] for r in new_records) / len(new_records)
    avg_fallback = sum(r["fallback_rate"] for r in new_records) / len(new_records)
    return {
        "n_new_records": len(new_records),
        "avg_projection_availability_rate": round(avg_availability, 4),
        "avg_smartsim2_visibility_rate": round(avg_visibility, 4),
        "avg_fallback_rate": round(avg_fallback, 4),
    }


def main() -> None:
    cohort = load_cohort()
    all_tokens = [entry["token"] for entry in cohort]
    sample_tokens = sample_one_token_per_role(cohort)

    os.environ["SMARTSIM_PUBLIC_TRIAL_ENABLED"] = "1"
    os.environ["SMARTSIM_PUBLIC_TRIAL_TOKENS"] = ",".join(all_tokens)

    app = create_app()

    before_count = len(read_monitoring_log())
    access_results = check_access_control(app, all_tokens, sample_tokens)
    gate_results = check_publication_gate_parity(app, sample_tokens[cohort[0]["role"]])
    monitoring_results = check_monitoring(before_count)

    print(f"cohort_size={len(cohort)}")
    print(f"roles_sampled={list(sample_tokens)}")
    print("=== access_control ===")
    print(json.dumps(access_results, indent=2))
    print("=== publication_gate_parity ===")
    print(json.dumps(gate_results, indent=2))
    print("=== monitoring ===")
    print(json.dumps(monitoring_results, indent=2))
    print(f"monitoring_log_path={MONITORING_LOG_PATH}")


if __name__ == "__main__":
    main()
