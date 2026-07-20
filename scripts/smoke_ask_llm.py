"""Live smoke test for the Ask the Syndicate LLM briefing path.

Runs one question per category through the real engine (focused evidence
fetchers + Claude call) against whatever is on the data disk, and prints the
briefing, token usage, and latency for each.

Usage (PowerShell):
    $env:ANTHROPIC_API_KEY = "sk-ant-..."
    python scripts/smoke_ask_llm.py

Without a key it reports the fallback behavior and exits nonzero so it can
double as a wiring check.
"""

from __future__ import annotations

import io
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from syndicate.blueprints.ask_the_syndicate_data import collect_focused_evidence
from syndicate.blueprints.ask_the_syndicate_engine import generate_briefing, llm_enabled

QUESTIONS = [
    ("MLB game sim", "How do the Brewers look against the Pirates?", {"sport": "mlb"}),
    ("MLB pitcher K + BvP", "How many strikeouts will Paul Skenes get, and how does the lineup fare against him?", {"sport": "mlb"}),
    ("MLB accuracy / trust", "How accurate has SmartSim been lately?", {"sport": "mlb"}),
    ("WNBA player outlook", "What is the outlook for Kamilla Cardoso tonight? Has she been clearing 14.5 points?", {"sport": "wnba"}),
    ("NBA last-10", "How has Kevin Durant looked in his last 10 games?", {"sport": "nba"}),
    ("No-visuals board question", "What are the best bets on the board today?", {"sport": "mlb"}),
]

SNAPSHOT = {
    "query_type": "market_summary",
    "summary": "Smoke-test snapshot: live board unavailable, focused evidence attached per question.",
    "recommendations": [],
    "board_notes": ["Smoke test run - snapshot intentionally minimal."],
    "readiness_gate": {"ok": True},
}


def main() -> int:
    if not llm_enabled():
        print("LLM disabled: no ANTHROPIC_API_KEY in the environment (or the kill switch is set).")
        print("The endpoint would serve deterministic snapshot + visuals responses in this state.")
        return 1

    failures = 0
    for label, question, context in QUESTIONS:
        print("=" * 78)
        print(f"[{label}] {question}")
        started = time.time()
        focused = collect_focused_evidence(question, context)
        fetch_seconds = time.time() - started
        sections = [s.get("source") for s in (focused or {}).get("evidence", [])]
        print(f"  focused evidence: {sections or 'none'} ({fetch_seconds:.2f}s)")

        started = time.time()
        payload = generate_briefing(
            question=question,
            context=context,
            intent="bet_analysis",
            snapshot=SNAPSHOT,
            focused_evidence=focused,
        )
        llm_seconds = time.time() - started
        if not payload:
            print(f"  LLM: FELL BACK after {llm_seconds:.2f}s (see logs above)")
            failures += 1
            continue

        briefing = payload["briefing"]
        usage = payload.get("usage") or {}
        print(f"  LLM: ok in {llm_seconds:.2f}s | model={payload.get('model')} | "
              f"in={usage.get('input_tokens')} out={usage.get('output_tokens')} "
              f"cache_read={usage.get('cache_read_input_tokens')}")
        print(f"  headline:   {briefing.get('headline')}")
        print(f"  verdict:    {briefing.get('verdict')}")
        print(f"  confidence: {briefing.get('confidence')}")
        print(f"  drivers:    {briefing.get('key_drivers')}")
        print(f"  risks:      {briefing.get('risks')}")
        if briefing.get("data_quality_note"):
            print(f"  data note:  {briefing.get('data_quality_note')}")
        narrative = str(briefing.get("narrative") or "")
        print(f"  narrative:  {narrative[:400]}{'…' if len(narrative) > 400 else ''}")

    print("=" * 78)
    print("PASS" if failures == 0 else f"{failures} question(s) fell back")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
