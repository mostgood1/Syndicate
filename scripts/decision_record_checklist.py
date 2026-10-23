"""Populated-field checklist for the DecisionRecord (`#709` step 2). Exits 1 on an alarm.

`docs/ai_context/model_engine_standard.md` section 1, applied to the record: enumerate
`dataclasses.fields()` of every record component (never a list of names), and for each
field ask two things --

* CONSUMED: does the record's own logic or the agreement report read it? (AST over
  `decision_record.py` + `decision_agreement.py`: attribute accesses and string keys);
* POPULATED: in a REAL record file, how often does it differ from the dataclass
  DEFAULT? A field at its default is unfed even when it holds a number.

CONSUMED + below its floor is the alarm. Legitimately sparse fields are listed in
`EXPECTED_SPARSE` with a reason; those must still be non-default SOMEWHERE (> 0), or
they are unfed and alarm too. The build's context inputs (w* table, cheat-sheet form,
bankrolls) are checked as well, because each one is a `.get(..., default)` away from
turning a feature into a no-op.

Substrate: whatever file you point it at. A record file read off the fleet's disk is a
production reading; anything built from a checkout's `data/` is not, and this script
prints the path so the reader can tell.

    python scripts/decision_record_checklist.py --date 2026-10-23           # data root
    python scripts/decision_record_checklist.py --file <path>.json.gz [--json]
"""

from __future__ import annotations

import argparse
import ast
import dataclasses
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from syndicate.features.shared import decision_record as dr  # noqa: E402

MIN_POPULATED = 0.5

# (Class, field) -> why it is legitimately sparse. Must still be > 0 somewhere.
EXPECTED_SPARSE: dict[tuple[str, str], str] = {
    ("Identity", "player"): "game lines carry no player",
    ("Identity", "line"): "h2h has no line",
    ("VenueContract", "ref"): "the board carries one venue_ref, only for the venue whose feed priced the row",
    ("VenueContract", "identity"): "default no_contract is the common case (see ref)",
    ("VenueContract", "ref_date"): "only rows with a dated venue ref",
    ("MarketFair", "quote_seen_age_seconds"): "set only where the fan-in saw the quote",
    ("ModelView", "p_model"): "rows without a sim/model view (~14% of the 10-23 board)",
    ("ModelView", "source_field"): "with p_model",
    ("ModelView", "engine"): "with p_model",
    ("ModelView", "basis"): "with p_model",
    ("ModelView", "skill_status"): "with p_model",
    ("ModelView", "skill_verdict"): "with p_model and a measured skill line",
    ("ModelView", "skill_loses_to_market"): "only where the skill verdict names beats/loses",
    ("ModelView", "calibration_cell"): "with p_model",
    ("ModelView", "w_star"): "only cells the optimizer has fitted",
    ("ModelView", "w_star_ci_upper"): "only fitted cells with a bootstrap",
    ("ModelView", "w_star_verdict"): "only fitted cells",
    ("ModelView", "w_star_games"): "only fitted cells",
    ("FormView", "source"): "props on a cheat sheet only",
    ("FormView", "games5"): "props on a cheat sheet only",
    ("FormView", "hits5"): "props on a cheat sheet only",
    ("FormView", "games10"): "props on a cheat sheet only",
    ("FormView", "hits10"): "props on a cheat sheet only",
    ("FormView", "p_posterior"): "props on a cheat sheet with >=1 graded game",
    ("FormView", "prior_strength"): "props on a cheat sheet only",
    ("FormView", "provisional"): "props on a cheat sheet only",
    ("Blend", "w_model"): "0 where the model loses to the market or there is no model",
    ("Blend", "w_form"): "DEFAULT_FORM_WEIGHT is 0 until form's weight is measured",
    ("Blend", "model_shift_pp"): "0 where w_model is 0",
    ("Blend", "form_shift_pp"): "0 while w_form is 0",
    ("PriceQuote", "fee_per_contract"): "sportsbooks charge no fee (0.0 is the default-looking real value)",
    ("PriceQuote", "fee_is_bound"): "True only where the venue's series is unresolved",
    ("Gate", "passed"): "None (unmeasured) is the default; most gates pass or fail",
    ("Gate", "blocks_on_unknown"): "False only for advisory gates",
    ("Gate", "enforced_live"): "live gates only",
    ("Gate", "detail"): "only failed or unknown gates carry detail",
    ("Verdict", "bet"): "most lines are no-bet",
    ("Verdict", "failed_gates"): "empty on bets",
    ("Verdict", "reason"): "always set; listed because bet/no-bet share it",
    ("Size", "bankroll"): "live capital is known only when a live plan carries a compounding stamp",
    ("Size", "bankroll_source"): "with bankroll",
    ("Size", "stake_dollars"): "with bankroll",
    ("Size", "stake_dollars_live_equivalent"): "with bankroll",
    ("SizeLayer", "value"): "credibility is None when the sport has no settled-sample stamp",
    ("SizeLayer", "dollars_after"): "only layers after the bankroll",
    ("SizeLayer", "note"): "some layers carry no note",
    ("SizeLayer", "applied"): "False only for live-only layers (band, favourite cap)",
    ("DecisionRecord", "board_model_edge_pct"): "rows without a model view",
    ("DecisionRecord", "form"): "props on a cheat sheet only",
    ("DecisionRecord", "sizes"): "sized only where a paper/live verdict is bet",
}

# (Class, field) that may be zero everywhere on a given day, with the reason.
MAY_BE_ZERO: dict[tuple[str, str], str] = {
    ("Blend", "w_form"): "form weight is 0 by design until measured",
    ("Blend", "form_shift_pp"): "follows w_form",
    ("PriceQuote", "fee_is_bound"): "every series may resolve",
    ("MarketFair", "suspect_stale"): "False is the healthy value",
    ("VenueContract", "ref_date"): "a slate may carry no dated venue ref",
    ("Gate", "enforced_live"): "None on board/paper gates; live gates set it",
    ("Size", "bankroll"): "no live plan with a compounding stamp this build",
    ("Size", "bankroll_source"): "follows bankroll",
    ("Size", "stake_dollars"): "follows bankroll",
    ("Size", "stake_dollars_live_equivalent"): "follows bankroll",
    ("SizeLayer", "dollars_after"): "follows bankroll",
    ("ModelView", "skill_loses_to_market"): "no measured verdict names beats/loses",
}

# Fields that only label or carry identity; read by humans, not by the logic.
INFORMATIONAL = {("Identity", n) for n in ("home_team", "away_team", "kind")} | {
    ("MarketFair", "devig_method"), ("ModelView", "engine"), ("ModelView", "basis"),
    ("ModelView", "skill_verdict"), ("FormView", "source"), ("Blend", "anchor"),
}


def _consumed_names() -> set[str]:
    names: set[str] = set()
    for module in ("decision_record.py", "decision_agreement.py"):
        tree = ast.parse((REPO / "syndicate" / "features" / "shared" / module).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load):
                names.add(node.attr)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                names.add(node.value)
    return names


def _walk(rec: dr.DecisionRecord):
    yield rec
    for name in ("identity", "market", "model", "form", "blend"):
        yield getattr(rec, name)
    yield from rec.contracts
    yield from rec.prices
    yield from rec.gates
    yield from rec.verdicts
    for size in rec.sizes:
        yield size
        yield from size.layers


def _default(f: dataclasses.Field):
    if f.default is not dataclasses.MISSING:
        return f.default
    if f.default_factory is not dataclasses.MISSING:  # type: ignore[misc]
        return f.default_factory()  # type: ignore[misc]
    return None


def run(payload: dict) -> dict:
    records = [dr.expand_record(r) for r in payload.get("records") or []]
    consumed = _consumed_names()
    counts: dict[tuple[str, str], list[int]] = {}
    for cls in dr.COMPONENT_CLASSES:
        for f in dataclasses.fields(cls):
            counts[(cls.__name__, f.name)] = [0, 0]
    defaults = {cls.__name__: {f.name: _default(f) for f in dataclasses.fields(cls)} for cls in dr.COMPONENT_CLASSES}
    for rec in records:
        for obj in _walk(rec):
            cls_name = type(obj).__name__
            for f in dataclasses.fields(obj):
                cell = counts[(cls_name, f.name)]
                cell[1] += 1
                if getattr(obj, f.name) != defaults[cls_name][f.name]:
                    cell[0] += 1
    rows = []
    alarms = []
    for (cls_name, name), (populated, seen) in sorted(counts.items()):
        rate = populated / seen if seen else None
        is_consumed = name in consumed and (cls_name, name) not in INFORMATIONAL
        sparse = (cls_name, name) in EXPECTED_SPARSE
        if not seen:
            verdict = "NO_INSTANCES"
        elif rate >= MIN_POPULATED:
            verdict = "OK"
        elif populated > 0 and sparse:
            verdict = "SPARSE_OK"
        elif populated == 0 and (cls_name, name) in MAY_BE_ZERO:
            verdict = "ZERO_OK"
        elif not is_consumed:
            verdict = "UNCONSUMED"
        else:
            verdict = "ALARM"
        if verdict == "ALARM" or (verdict == "NO_INSTANCES" and cls_name not in {"Size", "SizeLayer"}):
            alarms.append(f"{cls_name}.{name}")
        rows.append({"field": f"{cls_name}.{name}", "consumed": is_consumed, "populated": populated, "seen": seen,
                     "rate": None if rate is None else round(rate, 4), "verdict": verdict,
                     "sparse_reason": EXPECTED_SPARSE.get((cls_name, name)) or MAY_BE_ZERO.get((cls_name, name))})
    context = payload.get("context") or {}
    context_checks = {
        "calibration_cells": (context.get("calibration_cells") or 0) > 0,
        "form_lines": (context.get("form_lines") or 0) > 0,
        "paper_bankroll": context.get("paper_bankroll") is not None,
    }
    for name, ok in context_checks.items():
        if not ok:
            alarms.append(f"context.{name}")
    return {"records": len(records), "build_id": payload.get("build_id"), "written_at": payload.get("written_at"),
            "context": context, "context_checks": context_checks, "fields": rows, "alarms": alarms}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--date")
    parser.add_argument("--file")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    path = Path(args.file) if args.file else (dr.records_path(args.date) if args.date else None)
    if path is None:
        parser.error("--date or --file")
    payload = dr.read_records_file(path)
    if not payload:
        print(f"UNMEASURED: no readable record file at {path}")
        return 1
    result = run(payload)
    result["path"] = str(path)
    if args.json:
        print(json.dumps(result, indent=1, default=str))
    else:
        print(f"DecisionRecord checklist -- {path}")
        print(f"build {result['build_id']} written {result['written_at']}  records={result['records']}")
        print(f"context: {json.dumps(result['context_checks'])}")
        for row in result["fields"]:
            if row["verdict"] != "OK":
                print(f"  {row['verdict']:<12} {row['field']:<40} {row['populated']}/{row['seen']}"
                      f"  consumed={row['consumed']}  {row['sparse_reason'] or ''}")
        ok = sum(1 for r in result["fields"] if r["verdict"] == "OK")
        print(f"{ok}/{len(result['fields'])} fields OK; alarms: {result['alarms'] or 'none'}")
    return 1 if result["alarms"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
