"""Gate: every player-prop layer Ask claims to fill is actually filled.

`docs/ai_context/model_engine_standard.md` requires a checklist that crosses
"is this CONSUMED" against "is this POPULATED" and exits non-zero. For Ask's
prop evidence that means three questions, each answered from the object itself
rather than a name grep:

  1. OFFLINE -- every table/chart title the Ask data module can build maps to a
     layer (an unmapped title is a table whose layer silently goes unshown).
  2. OFFLINE -- every provider, run on its production-sliced fixture, declares
     all seven layers and FILLS the ones it is expected to fill.
  3. PRODUCTION (`--base-url`) -- over real pregame board prop rows, the served
     `prop_evidence.coverage` fills every expected layer on at least one row.
     0 filled over >= `--min-rows` rows is the lane's registered falsification:
     the provider does not reach the data.

    python scripts/prop_evidence_checklist.py
    python scripts/prop_evidence_checklist.py --base-url https://syndicate-an21.onrender.com --sports mlb,wnba,nfl,ncaaf --sample 8 --json out.json

Exit 0 = pass, 1 = a gate failed, 2 = could not run.
"""

from __future__ import annotations

import argparse
import ast
import collections
import json
import os
import statistics
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

FIXTURE_ROOT = REPO_ROOT / "tests" / "fixtures" / "prop_evidence" / "root"
LAYERS = ("player_sim", "recent_form", "matchup", "advanced", "game_sim", "environment", "track_record")

# Layers each provider must fill on its fixture row AND, in production, on at
# least one sampled pregame row. A layer left out here is one the sport has no
# producer or no published data for -- each is named in the provider's absent
# reasons and in `docs/ai_context/prop_evidence_reference.md`.
EXPECTED: dict[str, set[str]] = {
    "mlb": {"player_sim", "recent_form", "matchup", "advanced", "game_sim"},
    "wnba": {"player_sim", "recent_form", "matchup", "advanced", "game_sim", "environment"},
    "nba": {"player_sim", "matchup", "advanced", "game_sim", "environment"},
    "nhl": {"player_sim", "recent_form", "matchup", "advanced", "game_sim", "environment"},
    "soccer": {"player_sim", "matchup", "advanced", "game_sim", "environment"},
    # NFL recent form is NOT expected: `nfl_fantasy_usage_*.json` is allowlisted
    # but production web holds zero of them (export listing, 2026-09-17), so no
    # per-game NFL player stats reach this service. NCAAF has no published player
    # projection and web must not model, so player_sim is not expected either.
    "nfl": {"player_sim", "matchup", "advanced", "game_sim", "environment"},
    "ncaaf": {"recent_form", "matchup", "advanced", "game_sim", "environment"},
}

# One real board row per provider sport, the same rows the provider tests use.
FIXTURE_ROWS: dict[str, tuple[str, dict[str, Any]]] = {
    "wnba": ("2026-09-17", {
        "sport": "wnba", "event_id": "0fd1d4ee6d6e720e030e8cefb6a5a591", "market": "player_points",
        "player_name": "Saniya Rivers", "line": 9.5, "side": "over", "segment": "full",
        "home_team": "Atlanta Dream", "away_team": "Connecticut Sun", "commence_time": "2026-09-17T23:30:00Z", "kind": "prop"}),
    "nhl": ("2026-06-09", {
        "sport": "nhl", "event_id": "nhl-2025030414", "market": "SOG", "player_name": "Jack Eichel", "line": 2.5,
        "side": "under", "segment": "full", "home_team": "Vegas Golden Knights", "away_team": "Carolina Hurricanes",
        "commence_time": "2026-06-10T00:00:00Z", "kind": "prop"}),
    "nfl": ("2026-09-17", {
        "sport": "nfl", "event_id": "56e8897681915f7ec92baeee952bb1ae", "market": "Receptions",
        "player_name": "Jahmyr Gibbs", "line": 4.5, "side": "over", "segment": "full",
        "home_team": "Buffalo Bills", "away_team": "Detroit Lions", "commence_time": "2026-09-18T00:15:00Z", "kind": "prop"}),
    "ncaaf": ("2026-09-17", {
        "sport": "ncaaf", "event_id": "03297aa8a399c223aa1cc6aa923d9bc6", "market": "Receptions",
        "player_name": "Joseph Williams", "line": 4.5, "side": "over", "segment": "full",
        "home_team": "Northwestern Wildcats", "away_team": "Colorado Buffaloes",
        "commence_time": "2026-09-19T23:30:00Z", "kind": "prop"}),
    "soccer": ("2026-09-17", {
        "sport": "soccer", "event_id": "c7b8233ea02650f1055ae086b169b7a1", "market": "player_shots",
        "player_name": "Roberto Piccoli", "line": 2.5, "side": "over", "segment": "full",
        "home_team": "Bologna", "away_team": "Torino", "commence_time": "2026-09-19T13:00:00Z", "kind": "prop"}),
}

# Titles that are not prop evidence and never render on a board-row prop answer:
# the ranking/leaderboard fetcher's tables, and the coverage table itself.
_EXEMPT_TITLE_PREFIXES = ("Published board", "Top edges", "Top HR candidates", "Top {X} candidates",
                          "What this answer could not show")
_EXEMPT_TITLE_CONTAINS = (" probability leaders",)


def _literal_prefix(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        text = ""
        for part in node.values:
            if isinstance(part, ast.Constant) and isinstance(part.value, str):
                text += part.value
            else:
                text += "{X}"
        return text
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        return _literal_prefix(node.func.value)  # f"...".replace(...)
    if isinstance(node, ast.BinOp):
        return _literal_prefix(node.left)
    return None


def check_title_map() -> list[str]:
    from syndicate.blueprints import ask_the_syndicate_data as ask_data

    source = (REPO_ROOT / "syndicate" / "blueprints" / "ask_the_syndicate_data.py").read_text(encoding="utf-8")
    titles: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if isinstance(key, ast.Constant) and key.value == "title":
                    literal = _literal_prefix(value)
                    if literal is not None:
                        titles.append(literal)
        elif isinstance(node, ast.Call):
            for kw in node.keywords:
                if kw.arg == "title":
                    literal = _literal_prefix(kw.value)
                    if literal is not None:
                        titles.append(literal)
    failures = []
    for title in sorted(set(titles)):
        if title.startswith(_EXEMPT_TITLE_PREFIXES) or any(s in title for s in _EXEMPT_TITLE_CONTAINS):
            continue
        probe = {"title": title.replace("{X}", "Q")}
        ask_data._tag_legacy_layers([probe])
        if not probe.get("layer"):
            failures.append(f"title map: no layer for Ask table/chart title {title!r}")
    return failures


def check_providers() -> tuple[list[str], dict[str, dict[str, str]]]:
    os.environ["SYNDICATE_DATA_ROOT"] = str(FIXTURE_ROOT)
    os.environ["SYNDICATE_REQUIRE_HOSTED_STORAGE"] = "1"
    from syndicate.features.shared import prop_evidence

    failures: list[str] = []
    report: dict[str, dict[str, str]] = {}
    for sport in sorted(prop_evidence.PROVIDERS):
        if sport not in FIXTURE_ROWS:
            continue
        date, row = FIXTURE_ROWS[sport]
        evidence = prop_evidence.build_prop_evidence(row, selected_date=date)
        if evidence is None:
            failures.append(f"{sport}: provider returned None for its fixture row")
            continue
        coverage = evidence.coverage()
        report[sport] = coverage
        for layer in LAYERS:
            status = coverage.get(layer, "")
            if status.endswith(":undeclared"):
                failures.append(f"{sport}: layer {layer} undeclared by the provider")
            if layer in EXPECTED.get(sport, set()) and status != "filled":
                failures.append(f"{sport}: expected layer {layer} not filled on fixture ({status})")
    return failures, report


# ---------------------------------------------------------------------------
# Production
# ---------------------------------------------------------------------------


def _http_json(url: str, *, body: dict[str, Any] | None = None, timeout: int = 180) -> tuple[Any, float, int]:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, method="POST" if body is not None else "GET",
                                     headers={"Content-Type": "application/json", "Accept-Encoding": "gzip"})
    started = time.time()
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read()
        if response.headers.get("Content-Encoding") == "gzip" or raw[:2] == b"\x1f\x8b":
            import gzip

            raw = gzip.decompress(raw)
    return json.loads(raw), time.time() - started, len(raw)


def _sample_rows(rows: list[dict[str, Any]], n: int) -> list[dict[str, Any]]:
    by_market: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for row in rows:
        by_market[str(row.get("market"))].append(row)
    picked: list[dict[str, Any]] = []
    while len(picked) < n and any(by_market.values()):
        for market in sorted(by_market):
            if by_market[market] and len(picked) < n:
                picked.append(by_market[market].pop(0))
    return picked


def check_production(base_url: str, sports: list[str], sample: int, min_rows: int) -> tuple[list[str], dict[str, Any]]:
    failures: list[str] = []
    out: dict[str, Any] = {}
    for sport in sports:
        try:
            board, _, _ = _http_json(f"{base_url}/api/board/layer2-shortlist?sport={sport}&limit=3000")
        except Exception as exc:
            failures.append(f"{sport}: shortlist unreadable ({type(exc).__name__})")
            continue
        props = [r for r in board.get("rows") or [] if r.get("kind") == "prop" and r.get("player_name")
                 and str(r.get("game_state") or "pregame") == "pregame"]
        rows = _sample_rows(props, sample)
        layer_filled = collections.Counter()
        reasons: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
        seconds: list[float] = []
        answered = 0
        details = []
        for row in rows:
            context = {k: str(row.get(k)) for k in ("sport", "market", "player_name", "event_id", "side", "line", "segment")
                       if row.get(k) not in (None, "")}
            context["name"] = str(row.get("player_name"))
            subject = " ".join(str(x) for x in (row.get("player_name"), row.get("line")) if x not in (None, ""))
            try:
                answer, took, size = _http_json(f"{base_url}/api/syndicate/query",
                                                body={"question": f"What's the case for and against {subject}?", "context": context})
            except Exception as exc:
                details.append({"row": context, "error": type(exc).__name__})
                continue
            seconds.append(took)
            block = answer.get("prop_evidence") or {}
            coverage = block.get("coverage") or {}
            if coverage:
                answered += 1
            for layer in LAYERS:
                status = str(coverage.get(layer) or "missing_block")
                if status == "filled":
                    layer_filled[layer] += 1
                else:
                    reasons[layer][status.split(":", 1)[0]] += 1
            details.append({"row": context, "seconds": round(took, 2), "bytes": size, "provider": block.get("provider"),
                            "coverage": coverage, "tables_served": block.get("tables_served")})
            time.sleep(1.0)
        out[sport] = {
            "board_prop_rows_pregame": len(props),
            "sampled": len(rows),
            "answered_with_coverage": answered,
            "filled_rate": {layer: (round(layer_filled[layer] / answered, 3) if answered else None) for layer in LAYERS},
            "absent_reasons": {layer: dict(reasons[layer]) for layer in LAYERS if reasons[layer]},
            "median_seconds": round(statistics.median(seconds), 2) if seconds else None,
            "details": details,
        }
        if answered < min_rows:
            out[sport]["verdict"] = f"UNVERIFIED: {answered} answered rows < {min_rows}"
            continue
        missing = [layer for layer in sorted(EXPECTED.get(sport, set())) if layer_filled[layer] == 0]
        if missing:
            failures.append(f"{sport}: expected layers filled on 0 of {answered} production rows: {missing}")
        out[sport]["verdict"] = "FAIL" if missing else "PASS"
    return failures, out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base-url", default="")
    parser.add_argument("--sports", default="mlb,wnba,nba,nhl,nfl,ncaaf,soccer")
    parser.add_argument("--sample", type=int, default=8)
    parser.add_argument("--min-rows", type=int, default=8)
    parser.add_argument("--json", default="")
    args = parser.parse_args(argv)

    failures: list[str] = []
    result: dict[str, Any] = {}
    try:
        title_failures = check_title_map()
        provider_failures, provider_report = check_providers()
    except Exception as exc:
        print(f"[prop_evidence_checklist] COULD NOT RUN: {type(exc).__name__}: {exc}", flush=True)
        return 2
    failures += title_failures + provider_failures
    result["offline"] = {"title_map_failures": title_failures, "providers": provider_report}
    for sport, coverage in provider_report.items():
        print(f"[offline] {sport}: " + ", ".join(f"{k}={'ok' if v == 'filled' else v.split(':', 1)[0]}" for k, v in coverage.items()))

    if args.base_url:
        sports = [s.strip() for s in args.sports.split(",") if s.strip()]
        prod_failures, prod = check_production(args.base_url.rstrip("/"), sports, args.sample, args.min_rows)
        failures += prod_failures
        result["production"] = prod
        for sport, block in prod.items():
            rates = ", ".join(f"{k}={'-' if v is None else f'{100 * v:.0f}%'}" for k, v in block["filled_rate"].items())
            print(f"[production] {sport}: {block.get('verdict')} pregame_props={block['board_prop_rows_pregame']} "
                  f"answered={block['answered_with_coverage']}/{block['sampled']} median_s={block['median_seconds']} | {rates}")

    if args.json:
        Path(args.json).write_text(json.dumps(result, indent=1, default=str), encoding="utf-8")
    for failure in failures:
        print(f"FAIL {failure}")
    print("PROP EVIDENCE CHECKLIST " + ("FAILED" if failures else "PASSED"))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
