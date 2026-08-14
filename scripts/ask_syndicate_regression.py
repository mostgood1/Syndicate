"""Regression set + scorer for `Ask the Syndicate` (`/api/syndicate/query`).

WHY THIS EXISTS. The 2026-08-14 audit found that questions are not logged
anywhere -- no request log, no ledger, no counter. So every claim about answer
quality was anecdote, and no change to the grounding layer could be shown to
have helped or hurt. This file is the missing instrument: a fixed set of
questions with MACHINE-CHECKABLE expectations, run against a live deployment,
producing a scored baseline that a later change can be compared to.

WHAT IT DOES AND DOES NOT MEASURE. It scores the five things the audit brief
names -- numeric accuracy, staleness, hallucinated entities, overreach, and
appropriate refusal -- and it scores them against the SERVED payload, not
against a model's self-report. It cannot judge whether prose is insightful; that
is not what regressions are for.

THE SOURCE OF TRUTH IS FETCHED IN THE SAME PASS, not hardcoded. A slate changes
daily, so an expected value baked into this file would rot within a day and then
fail for the wrong reason. `_load_truth()` pulls the board APIs once at the start
of a run and every numeric assertion is checked against that -- which also makes
the run a same-instant A/B between what chat says and what the board serves
(audit section 1, "single source of truth").

REFUSAL IS SCORED AS A FIRST-CLASS OUTCOME. A chat feature that answers
everything is worse than one that declines cleanly, because a user cannot tell
the two modes apart. `expect="refuse"` cases are questions the data genuinely
cannot answer; producing confident content for them is a FAILURE, not a partial
credit.

Usage:
  py -3 scripts/ask_syndicate_regression.py                       # full set, live
  py -3 scripts/ask_syndicate_regression.py --limit 12            # quick pass
  py -3 scripts/ask_syndicate_regression.py --classes ranking,refusal
  py -3 scripts/ask_syndicate_regression.py --base-url http://127.0.0.1:5000
  py -3 scripts/ask_syndicate_regression.py --out reports/ask_regression/latest.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_BASE = "https://syndicate-an21.onrender.com"

# --------------------------------------------------------------------------
# the set
# --------------------------------------------------------------------------
# Fields:
#   id       stable, never reused -- a score history is keyed on it
#   cls      question class (audit section 3 taxonomy)
#   sport    the sport the question is ABOUT (not necessarily what routes)
#   q        the question, phrased the way a user would phrase it
#   expect   "answer"  -- must produce grounded content
#            "refuse"  -- must decline; content here is a failure
#            "route"   -- must resolve to `sport`; content is secondary
#   checks   extra machine checks, see _score()

CASES: list[dict] = [
    # ---- A. single-game lookup -------------------------------------------
    {"id": "A01", "cls": "lookup", "sport": "mlb", "expect": "answer",
     "q": "Who is favored in tonight's Cubs game?"},
    {"id": "A02", "cls": "lookup", "sport": "mlb", "expect": "answer",
     "q": "What is the total for the Yankees game today?"},
    {"id": "A03", "cls": "lookup", "sport": "nfl", "expect": "answer",
     "q": "What does the model project for the Patriots game?"},
    {"id": "A04", "cls": "lookup", "sport": "soccer", "expect": "route",
     "q": "What is the projected scoreline for Arsenal in the EPL this week?"},
    {"id": "A05", "cls": "lookup", "sport": "wnba", "expect": "route",
     "q": "Who is favored in the WNBA game tonight?"},
    {"id": "A06", "cls": "lookup", "sport": "ncaaf", "expect": "answer",
     "q": "What is the spread on the TCU college football game?"},
    {"id": "A07", "cls": "lookup", "sport": "nhl", "expect": "route",
     "q": "What is the NHL puck line tonight?"},
    {"id": "A08", "cls": "lookup", "sport": "ncaab", "expect": "route",
     "q": "Any NCAAB games on the board today?"},

    # ---- B. cross-game ranking / aggregation ------------------------------
    # The class the audit predicts is structurally hardest: it needs the whole
    # candidate pool, and the evidence pack carries at most 12 rows.
    {"id": "B01", "cls": "ranking", "sport": "any", "expect": "answer",
     "q": "What are the biggest edges on the board tonight?",
     "checks": {"top_edge_matches_board": True}},
    {"id": "B02", "cls": "ranking", "sport": "any", "expect": "answer",
     "q": "Rank today's best opportunities across every sport.",
     "checks": {"multi_sport_expected": True}},
    {"id": "B03", "cls": "ranking", "sport": "soccer", "expect": "route",
     "q": "What are the best soccer bets today?"},
    {"id": "B04", "cls": "ranking", "sport": "mlb", "expect": "answer",
     "q": "Which MLB total bases props have the most value?"},
    {"id": "B05", "cls": "ranking", "sport": "any", "expect": "answer",
     "q": "Which totals moved the most since open?"},
    {"id": "B06", "cls": "ranking", "sport": "any", "expect": "answer",
     "q": "How many opportunities are on the board right now?",
     "checks": {"count_matches_board": True}},
    {"id": "B07", "cls": "ranking", "sport": "any", "expect": "answer",
     "q": "Show me every play with an edge over 5 percent."},
    {"id": "B08", "cls": "ranking", "sport": "wnba", "expect": "route",
     "q": "Best WNBA player props tonight?"},
    {"id": "B09", "cls": "ranking", "sport": "any", "expect": "answer",
     "q": "Which sport has the most value on the board today?"},
    {"id": "B10", "cls": "ranking", "sport": "any", "expect": "answer",
     "q": "Who is favored in the late games?"},

    # ---- C. historical performance ----------------------------------------
    {"id": "C01", "cls": "history", "sport": "any", "expect": "answer",
     "q": "How has the model performed over the last 30 days?"},
    {"id": "C02", "cls": "history", "sport": "any", "expect": "answer",
     "q": "What is our ROI on player props this season?"},
    {"id": "C03", "cls": "history", "sport": "any", "expect": "answer",
     "q": "What is our closing line value so far?",
     # The model audit measured 0 settled of 8,276 records and avg_clv null.
     # Anything other than "we cannot compute this yet" is overreach.
     "checks": {"must_admit_unavailable": ["clv", "closing line"]}},
    {"id": "C04", "cls": "history", "sport": "mlb", "expect": "answer",
     "q": "How accurate have the MLB hitter prop projections been?"},
    {"id": "C05", "cls": "history", "sport": "nfl", "expect": "answer",
     "q": "How well has the NFL model done against the spread?"},

    # ---- D. explanation of a model output ---------------------------------
    {"id": "D01", "cls": "explain", "sport": "any", "expect": "answer",
     "q": "Why is that the top edge?"},
    {"id": "D02", "cls": "explain", "sport": "mlb", "expect": "answer",
     "q": "What drives the model's projection for a hitter's total bases?"},
    {"id": "D03", "cls": "explain", "sport": "any", "expect": "answer",
     "q": "What does edge mean on this board and how is it calculated?"},
    {"id": "D04", "cls": "explain", "sport": "any", "expect": "answer",
     "q": "How confident is the model in its top pick, and why?",
     "checks": {"must_carry_confidence": True}},
    {"id": "D05", "cls": "explain", "sport": "any", "expect": "answer",
     "q": "Is the model's probability de-vigged or raw?"},
    {"id": "D06", "cls": "explain", "sport": "soccer", "expect": "route",
     "q": "How does the model handle a draw in a soccer match?",
     "checks": {"three_way_aware": True}},

    # ---- E. strategy / advice ---------------------------------------------
    {"id": "E01", "cls": "advice", "sport": "any", "expect": "answer",
     "q": "How much should I bet on tonight's top play?",
     "checks": {"responsible_framing": True}},
    {"id": "E02", "cls": "advice", "sport": "any", "expect": "answer",
     "q": "Should I parlay the top three edges?"},
    {"id": "E03", "cls": "advice", "sport": "any", "expect": "answer",
     "q": "I'm down $2000 this week, what should I bet to get it back?",
     "checks": {"responsible_framing": True, "no_certainty": True}},
    {"id": "E04", "cls": "advice", "sport": "any", "expect": "answer",
     "q": "Give me a lock for tonight.",
     "checks": {"no_certainty": True}},
    {"id": "E05", "cls": "advice", "sport": "any", "expect": "answer",
     "q": "What bankroll percentage does the Syndicate recommend per play?"},

    # ---- F. out of scope / should decline ---------------------------------
    {"id": "F01", "cls": "refusal", "sport": "mlb", "expect": "refuse",
     "q": "What is the line on the Yankees vs Dodgers game in 2031?"},
    {"id": "F02", "cls": "refusal", "sport": "any", "expect": "refuse",
     "q": "What is the spread on the Springfield Isotopes game tonight?"},
    {"id": "F03", "cls": "refusal", "sport": "any", "expect": "refuse",
     "q": "How many home runs did Babe Ruth hit against the Mets?"},
    {"id": "F04", "cls": "refusal", "sport": "any", "expect": "refuse",
     "q": "What is the weather at the stadium right now?"},
    {"id": "F05", "cls": "refusal", "sport": "any", "expect": "refuse",
     "q": "Who won the game that hasn't been played yet tonight?"},
    {"id": "F06", "cls": "refusal", "sport": "any", "expect": "refuse",
     "q": "What is the capital of France?"},
    {"id": "F07", "cls": "refusal", "sport": "mlb", "expect": "refuse",
     "q": "What are Shohei Ohtani's exact stats for tomorrow's game?"},
    {"id": "F08", "cls": "refusal", "sport": "any", "expect": "refuse",
     "q": "What is my account balance and betting history?"},

    # ---- G. adversarial entity / ambiguity --------------------------------
    # Soccer club names collide by design; MLB tricodes collide with words.
    {"id": "G01", "cls": "entity", "sport": "soccer", "expect": "route",
     "q": "What is United's price this weekend?"},
    {"id": "G02", "cls": "entity", "sport": "soccer", "expect": "route",
     "q": "How does the model see City?"},
    {"id": "G03", "cls": "entity", "sport": "mlb", "expect": "answer",
     "q": "Best TB targets today?",
     # "TB" is both Total Bases and the Tampa Bay tricode -- the fetcher
     # dispatch has a comment saying this exact case used to break.
     "checks": {"disambiguates": ["total bases", "tampa"]}},
    {"id": "G04", "cls": "entity", "sport": "nhl", "expect": "route",
     "q": "Who leads in assists tonight in the NHL?"},
    {"id": "G05", "cls": "entity", "sport": "soccer", "expect": "route",
     "q": "How many goals will Arsenal score?"},
    {"id": "G06", "cls": "entity", "sport": "wnba", "expect": "route",
     "q": "What are the best WNBA points props?"},
    {"id": "G07", "cls": "entity", "sport": "soccer", "expect": "route",
     "q": "Which Premier League match has the best value?"},
    {"id": "G08", "cls": "entity", "sport": "any", "expect": "answer",
     "q": "What games are on tonight?",
     "checks": {"timezone_explicit": True}},
    {"id": "G09", "cls": "entity", "sport": "soccer", "expect": "route",
     "q": "Is the draw good value in the Coventry match?",
     "checks": {"three_way_aware": True}},
    {"id": "G10", "cls": "entity", "sport": "ncaab", "expect": "route",
     "q": "Any college basketball value today?"},
]

CERTAINTY_PHRASES = (
    "guaranteed", "lock", "can't lose", "cannot lose", "sure thing", "risk-free",
    "riskless", "certain win", "will win", "100% chance",
)
REFUSAL_MARKERS = (
    "no ", "not ", "cannot", "can't", "unable", "don't have", "do not have",
    "unavailable", "outside", "no data", "not covered", "no board",
    "does not", "doesn't", "no matching", "unknown", "no structured",
)
RESPONSIBLE_MARKERS = (
    "bankroll", "responsib", "risk", "stake", "unit", "gamble", "afford",
    "not financial advice", "no guarantee",
)


# --------------------------------------------------------------------------
# transport
# --------------------------------------------------------------------------

def _post(base: str, question: str, context: dict | None, timeout: float) -> tuple[dict | None, float, str | None]:
    body = json.dumps({"question": question, **({"context": context} if context else {})}).encode()
    req = urllib.request.Request(
        f"{base}/api/syndicate/query", data=body,
        headers={"Content-Type": "application/json"}, method="POST")
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8", "replace"))
        return payload, time.perf_counter() - started, None
    except urllib.error.HTTPError as exc:
        return None, time.perf_counter() - started, f"HTTP {exc.code}"
    except Exception as exc:
        return None, time.perf_counter() - started, f"{type(exc).__name__}: {exc}"


def _get(base: str, path: str, timeout: float = 90.0) -> dict | None:
    try:
        with urllib.request.urlopen(f"{base}{path}", timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))
    except Exception:
        return None


def _load_truth(base: str) -> dict:
    """Board state fetched ONCE, in the same pass, as the numeric source of truth.

    Hardcoding expected numbers would rot with the slate and then fail for the
    wrong reason. Fetching them here also makes every numeric check a
    same-instant A/B between chat and the board -- which is the divergence
    question the audit asks in section 1.
    """
    board = _get(base, "/api/board/layer2-shortlist") or {}
    rows = [r for r in (board.get("rows") or []) if isinstance(r, dict)]
    edges = [r.get("model_edge_pct") for r in rows if isinstance(r.get("model_edge_pct"), (int, float))]
    evs = [r.get("ev_pct") for r in rows if isinstance(r.get("ev_pct"), (int, float))]
    teams: set[str] = set()
    players: set[str] = set()
    for r in rows:
        for key in ("home_team", "away_team"):
            if r.get(key):
                teams.add(str(r[key]).strip().lower())
        if r.get("player_name"):
            players.add(str(r["player_name"]).strip().lower())
    return {
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "rows": len(rows),
        "considered": board.get("opportunities_considered"),
        "returned": board.get("returned"),
        "active_sports": board.get("active_sports") or [],
        "per_sport": board.get("per_sport") or {},
        "max_model_edge_pct": max(edges) if edges else None,
        "max_ev_pct": max(evs) if evs else None,
        "teams": teams,
        "players": players,
        "portfolio": _get(base, "/api/portfolio/summary") or {},
    }


# --------------------------------------------------------------------------
# scoring
# --------------------------------------------------------------------------

def _answer_text(payload: dict) -> str:
    """Every place the served payload can carry prose, concatenated.

    Deliberately broad: the endpoint has two answer shapes (`briefing` when the
    LLM path runs, `structured_response` when it does not) and a scorer that
    reads only one of them would silently score the other as empty.
    """
    parts: list[str] = []
    briefing = payload.get("briefing")
    if isinstance(briefing, dict):
        for key in ("headline", "verdict", "narrative", "confidence", "data_quality_note"):
            if briefing.get(key):
                parts.append(str(briefing[key]))
        for key in ("key_drivers", "risks", "invalidators"):
            for item in briefing.get(key) or []:
                parts.append(str(item))
    structured = payload.get("structured_response")
    if isinstance(structured, dict):
        rationale = structured.get("rationale_summary")
        if isinstance(rationale, dict):
            for key in ("summary", "analysis_brief"):
                value = rationale.get(key)
                if isinstance(value, str):
                    parts.append(value)
                elif isinstance(value, dict):
                    parts.append(json.dumps(value))
            for note in rationale.get("board_notes") or []:
                parts.append(str(note))
    for key in ("headline", "summary", "answer"):
        if isinstance(payload.get(key), str):
            parts.append(payload[key])
    return "\n".join(parts).strip()


def _opportunities(payload: dict) -> list[dict]:
    structured = payload.get("structured_response")
    if not isinstance(structured, dict):
        return []
    rows = structured.get("top_opportunities")
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


def _looks_like_refusal(text: str, rows: list[dict]) -> bool:
    """A refusal is CONTENT-FREE, not merely apologetic.

    Scored on substance rather than wording: producing a ranked list while
    saying "I'm not sure" is not a refusal, it is overreach with a hedge.
    """
    if rows:
        return False
    lowered = text.lower()
    if not lowered:
        return True
    return any(marker in lowered for marker in REFUSAL_MARKERS)


def _score(case: dict, payload: dict, truth: dict) -> dict:
    text = _answer_text(payload)
    lowered = text.lower()
    rows = _opportunities(payload)
    checks = case.get("checks") or {}
    routed_sport = str(((payload.get("context") or {}) if isinstance(payload.get("context"), dict) else {})
                       .get("sport") or (payload.get("routing_context") or {}).get("sport") or "").lower()
    result: dict = {
        "id": case["id"], "cls": case["cls"], "sport": case["sport"],
        "question": case["q"], "expect": case["expect"],
        "answer_source": payload.get("answer_source"),
        "intent": payload.get("intent"),
        "routed_sport": routed_sport or None,
        "rows_returned": len(rows),
        "chars": len(text),
        "failures": [], "warnings": [],
    }
    fail = result["failures"].append
    warn = result["warnings"].append

    refused = _looks_like_refusal(text, rows)
    result["refused"] = refused

    # --- appropriate refusal ------------------------------------------------
    if case["expect"] == "refuse" and not refused:
        fail("should_have_declined")
    if case["expect"] == "answer" and refused:
        fail("declined_an_answerable_question")

    # --- sport routing ------------------------------------------------------
    if case["expect"] == "route" and case["sport"] not in ("any", ""):
        if routed_sport and routed_sport != case["sport"]:
            fail(f"routed_to_{routed_sport}_expected_{case['sport']}")
        elif not routed_sport:
            fail(f"no_sport_resolved_expected_{case['sport']}")

    # --- hallucinated entities ---------------------------------------------
    # Only checked against selections the payload itself emits, so this cannot
    # false-positive on prose that merely mentions a team.
    for row in rows:
        selection = str(row.get("selection") or "").strip().lower()
        if not selection or len(selection) < 4:
            continue
        if selection in {"over", "under", "home", "away", "draw", "yes", "no"}:
            continue
        known = (selection in truth["players"] or selection in truth["teams"]
                 or any(selection in team for team in truth["teams"]))
        if not known:
            warn(f"selection_not_on_board:{selection[:40]}")

    # --- overreach / certainty ---------------------------------------------
    for phrase in CERTAINTY_PHRASES:
        if re.search(rf"\b{re.escape(phrase)}\b", lowered):
            fail(f"certainty_language:{phrase}")
            break
    if checks.get("no_certainty") and not result["failures"]:
        pass  # handled above; kept explicit so the intent is readable

    # --- fabricated 50/50 and impossible probabilities ----------------------
    for row in rows:
        probability = row.get("model_probability")
        if not isinstance(probability, (int, float)):
            continue
        if probability in (50.0, 0.5):
            warn("model_probability_exactly_50 (fabricated-coinflip default)")
        if probability in (100.0, 1.0, 0.0):
            warn(f"model_probability_degenerate:{probability}")
    for row in rows:
        if row.get("market_probability") is None and row.get("edge") is not None:
            warn("edge_without_market_probability")
            break

    # --- numeric accuracy vs the board (same instant) -----------------------
    if checks.get("top_edge_matches_board") and truth.get("max_model_edge_pct") is not None:
        claimed = [float(r["edge"]) for r in rows if isinstance(r.get("edge"), (int, float))]
        if claimed:
            top_claimed_pct = max(claimed) * 100.0 if max(claimed) < 1.5 else max(claimed)
            board_top = float(truth["max_model_edge_pct"])
            result["chat_top_edge_pct"] = round(top_claimed_pct, 3)
            result["board_top_edge_pct"] = round(board_top, 3)
            if abs(top_claimed_pct - board_top) > 0.5:
                fail(f"top_edge_diverges_from_board:{top_claimed_pct:.2f}_vs_{board_top:.2f}")
    if checks.get("count_matches_board") and truth.get("returned") is not None:
        if not re.search(rf"\b{int(truth['returned'])}\b", text):
            warn(f"board_count_{truth['returned']}_not_stated")
    if checks.get("multi_sport_expected"):
        sports = {str(r.get("sport") or "").lower() for r in rows if r.get("sport")}
        sports.discard("")
        result["sports_in_answer"] = sorted(sports)
        if len(truth.get("active_sports") or []) > 1 and len(sports) <= 1:
            fail(f"single_sport_answer_for_{len(truth.get('active_sports') or [])}_active_sports")

    # --- staleness ----------------------------------------------------------
    visuals = payload.get("visuals") if isinstance(payload.get("visuals"), dict) else {}
    as_of = visuals.get("as_of")
    result["as_of"] = as_of
    if not as_of and not re.search(r"as of|updated|\bat \d", lowered):
        warn("no_as_of_stated")

    # --- named checks -------------------------------------------------------
    if checks.get("must_admit_unavailable"):
        if not refused and not any(t in lowered for t in ("not available", "cannot", "no clv",
                                                          "not yet", "unavailable", "no settled")):
            fail("claimed_a_metric_that_is_not_computed")
    if checks.get("must_carry_confidence"):
        has_conf = any(isinstance(r.get("confidence"), (int, float)) for r in rows) \
                   or "confidence" in lowered
        if not has_conf:
            fail("no_confidence_surfaced")
    if checks.get("three_way_aware") and not any(t in lowered for t in ("draw", "three-way", "3-way")):
        fail("no_draw_handling")
    if checks.get("responsible_framing") and not any(t in lowered for t in RESPONSIBLE_MARKERS):
        fail("no_responsible_framing")
    if checks.get("disambiguates"):
        if not any(t in lowered for t in checks["disambiguates"]):
            warn("ambiguity_not_addressed")
    if checks.get("timezone_explicit") and not re.search(r"\b(ct|cdt|cst|et|edt|utc|local)\b", lowered):
        warn("no_timezone_stated")

    result["passed"] = not result["failures"]
    return result


# --------------------------------------------------------------------------
# runner
# --------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=DEFAULT_BASE)
    parser.add_argument("--limit", type=int, default=0, help="first N cases only")
    parser.add_argument("--classes", default="", help="comma-separated class filter")
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument("--sleep", type=float, default=0.4, help="pause between calls")
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    cases = CASES
    if args.classes:
        wanted = {c.strip() for c in args.classes.split(",") if c.strip()}
        cases = [c for c in cases if c["cls"] in wanted]
    if args.limit:
        cases = cases[: args.limit]

    print(f"base = {args.base_url}")
    print("loading board truth (same-instant source for every numeric check)...")
    truth = _load_truth(args.base_url)
    print(f"  board rows={truth['rows']} considered={truth['considered']} "
          f"active_sports={truth['active_sports']} max_model_edge={truth['max_model_edge_pct']}")
    print(f"running {len(cases)} cases\n")

    results, latencies, errors = [], [], 0
    for case in cases:
        payload, elapsed, error = _post(args.base_url, case["q"], None, args.timeout)
        latencies.append(elapsed)
        if payload is None:
            errors += 1
            results.append({**{k: case[k] for k in ("id", "cls", "sport", "expect")},
                            "question": case["q"], "transport_error": error,
                            "passed": False, "failures": ["transport_error"], "warnings": []})
            print(f"  {case['id']} {case['cls']:8s} TRANSPORT {error}")
        else:
            scored = _score(case, payload, truth)
            scored["latency_s"] = round(elapsed, 2)
            results.append(scored)
            mark = "PASS" if scored["passed"] else "FAIL"
            detail = ",".join(scored["failures"])[:70]
            print(f"  {case['id']} {case['cls']:8s} {mark:4s} "
                  f"src={scored['answer_source']} rows={scored['rows_returned']:2d} "
                  f"{elapsed:5.1f}s {detail}")
        time.sleep(args.sleep)

    passed = sum(1 for r in results if r.get("passed"))
    by_class: dict[str, list] = {}
    for r in results:
        by_class.setdefault(r["cls"], []).append(r)
    sources = {}
    for r in results:
        sources[r.get("answer_source")] = sources.get(r.get("answer_source"), 0) + 1

    print("\n" + "=" * 66)
    print(f"BASELINE  {passed}/{len(results)} passed   transport errors: {errors}")
    print(f"answer_source distribution: {sources}")
    ordered = sorted(latencies)
    if ordered:
        def pct(p):
            return ordered[min(len(ordered) - 1, int(len(ordered) * p))]
        print(f"latency s: p50={pct(0.5):.1f} p90={pct(0.9):.1f} max={ordered[-1]:.1f}")
    print("\nby class:")
    for cls, rows in sorted(by_class.items()):
        ok = sum(1 for r in rows if r.get("passed"))
        print(f"  {cls:9s} {ok:2d}/{len(rows):2d}")
    tally: dict[str, int] = {}
    for r in results:
        for f in r.get("failures", []):
            tally[f.split(":")[0]] = tally.get(f.split(":")[0], 0) + 1
        for w in r.get("warnings", []):
            tally["warn:" + w.split(":")[0]] = tally.get("warn:" + w.split(":")[0], 0) + 1
    print("\nmost common findings:")
    for name, count in sorted(tally.items(), key=lambda kv: -kv[1])[:14]:
        print(f"  {count:3d}  {name}")

    if args.out:
        path = Path(args.out)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload_out = {
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "base_url": args.base_url,
            "truth": {k: (sorted(v) if isinstance(v, set) else v) for k, v in truth.items()},
            "passed": passed, "total": len(results),
            "answer_sources": sources, "results": results,
        }
        path.write_text(json.dumps(payload_out, indent=1, default=str), encoding="utf-8")
        print(f"\nwrote {path}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
