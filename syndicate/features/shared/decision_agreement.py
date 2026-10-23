"""How often the DecisionRecord agrees with what the board, paper and live actually did.

`#709` step 2's gate (lane `decision-record-shadow`). Every build, after the record is
written, this compares it against:

* the board's `suggested` flag on the same row;
* the paper main plan, the paper venue books (`paper:<venue>`) and the live plans
  (`live:<venue>`) that the same tick committed -- membership AND stake;
* the live executor's actual orders on the slate (execution ledger, mode=live).

Every disagreement is NAMED by cause, using the audit's vocabulary
(`findings_2026-10-20_one_engine_audit.md` section 2): `sim_opposes` (F3),
`negative_at_venue_price` (F1), `full_kelly_band` (sizing rank 3), plus the record's
own failed gate names (`gate:price_band`, `gate:pregame`, ...).

One line per build is appended to `<date>.agreement.jsonl`; the daily report
(`<date>.agreement_report.json` / `.md`) is re-rendered from those lines each build,
so the day's report exists as soon as the day has a build, and is final after it.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from syndicate.features.shared.decision_record import (
    DESTINATION_BOARD,
    DESTINATION_PAPER,
    LIVE_VENUES,
    DecisionRecord,
    _f,
    line_key,
    records_dir,
)

SAMPLES_PER_DESTINATION = 12
SIZE_TOLERANCE = 0.10  # stakes within 10% agree


def _verdict(rec: DecisionRecord, dest: str):
    return next((v for v in rec.verdicts if v.destination == dest), None)


def _size(rec: DecisionRecord, dest: str):
    return next((s for s in rec.sizes if s.destination == dest), None)


def _price(rec: DecisionRecord, book: str):
    return next((p for p in rec.prices if p.role == "venue" and p.book == book), None)


def _sim_opposes(rec: DecisionRecord) -> bool:
    p_model, p_market = rec.model.p_model, rec.market.p_market
    return p_model is not None and p_market is not None and p_model < p_market


def _label(rec: DecisionRecord) -> str:
    i = rec.identity
    who = i.player or f"{i.away_team} @ {i.home_team}"
    line = "" if i.line is None else f" {i.line:g}"
    return f"{i.sport} {who} {i.market}{'' if i.segment == 'full' else ' ' + i.segment} {i.side}{line}"


class _Tally:
    def __init__(self) -> None:
        self.compared = 0
        self.agree = 0
        self.causes: Counter[str] = Counter()
        self.kinds: Counter[str] = Counter()
        self.size_compared = 0
        self.size_agree = 0
        self.size_causes: Counter[str] = Counter()
        self.samples: list[dict[str, Any]] = []

    def disagree(self, rec: DecisionRecord | None, key: str, kind: str, causes: Sequence[str]) -> None:
        self.kinds[kind] += 1
        for cause in causes or ["unexplained"]:
            self.causes[cause] += 1
        if len(self.samples) < SAMPLES_PER_DESTINATION:
            self.samples.append({"key": key, "label": _label(rec) if rec else key, "kind": kind, "causes": list(causes)})

    def as_dict(self) -> dict[str, Any]:
        return {
            "compared": self.compared, "agree": self.agree, "disagree": self.compared - self.agree,
            "disagree_kinds": dict(self.kinds), "causes": dict(self.causes.most_common()),
            "size_compared": self.size_compared, "size_agree": self.size_agree,
            "size_causes": dict(self.size_causes.most_common()), "samples": self.samples,
        }


def _record_no_causes(rec: DecisionRecord, dest: str) -> list[str]:
    verdict = _verdict(rec, dest)
    causes = [f"gate:{g}" for g in (verdict.failed_gates if verdict else [])]
    if _sim_opposes(rec):
        causes.append("sim_opposes")
    if dest.startswith(("live:", "paper:")):
        venue = dest.split(":", 1)[1]
        price = _price(rec, venue)
        if price is not None and price.ev_net_pct_at_market is not None and price.ev_net_pct_at_market <= 0:
            causes.append("negative_at_venue_price")
    return causes


def compare_board(records: Sequence[DecisionRecord], rows_by_key: Mapping[str, Mapping[str, Any]], board_floor: float) -> tuple[_Tally, dict[str, Any]]:
    tally = _Tally()
    suggested = 0
    negative_at = Counter()
    quoted_at = Counter()
    sim_opposed_suggested = 0
    with_model_suggested = 0
    for rec in records:
        if rec.board_suggested is None:
            continue
        verdict = _verdict(rec, DESTINATION_BOARD)
        tally.compared += 1
        if rec.board_suggested:
            suggested += 1
            if rec.model.p_model is not None:
                with_model_suggested += 1
                sim_opposed_suggested += int(_sim_opposes(rec))
            for venue in LIVE_VENUES:
                price = _price(rec, venue)
                if price is not None and price.ev_net_pct_at_market is not None:
                    quoted_at[venue] += 1
                    negative_at[venue] += int(price.ev_net_pct_at_market < 0)
        if bool(verdict and verdict.bet) == bool(rec.board_suggested):
            tally.agree += 1
            continue
        if rec.board_suggested:
            tally.disagree(rec, rec.key, "board_suggests_record_no", _record_no_causes(rec, DESTINATION_BOARD))
        else:
            best = next((p for p in rec.prices if p.role == "best_bettable"), None)
            causes = []
            if best and best.ev_net_pct_at_market is not None and best.ev_net_pct_at_market < board_floor:
                causes.append("model_weight_lifted_over_floor")
            row = rows_by_key.get(rec.key) or {}
            causes.extend(f"board_rule:{r}" for r in (row.get("suggested_reasons") or []) if isinstance(r, str))
            tally.disagree(rec, rec.key, "record_bets_board_no", causes or ["board_other"])
    forks = {
        "suggested_rows": suggested,
        "F3_suggested_sim_opposes": {"count": sim_opposed_suggested, "of_suggested_with_model": with_model_suggested},
        "F1_suggested_negative_at_venue_price": {
            v: {"count": negative_at[v], "of_suggested_quoted": quoted_at[v]} for v in LIVE_VENUES},
    }
    return tally, forks


def _position_stake(position: Mapping[str, Any]) -> float | None:
    return _f(position.get("stake_dollars"))


def _size_causes(rec: DecisionRecord, dest: str, position: Mapping[str, Any]) -> list[str]:
    causes: list[str] = []
    sizing = position.get("sizing") if isinstance(position.get("sizing"), Mapping) else {}
    band = position.get("stake_band") if isinstance(position.get("stake_band"), Mapping) else {}
    stake = _position_stake(position)
    if band.get("band_stake_dollars") is not None and stake is not None and abs(stake - float(band["band_stake_dollars"])) < 0.011:
        causes.append("full_kelly_band")
    if band.get("favourite_capped_from") is not None:
        causes.append("favourite_cap")
    model_p = _f(position.get("model_probability"))
    if model_p is not None and rec.blend.p_decision is not None and abs(model_p - rec.blend.p_decision) > 0.01:
        causes.append("probability_basis")
    if sizing.get("exposure_capped") or (_f(sizing.get("slate_scale_factor")) or 1.0) < 0.999:
        causes.append("exposure_or_slate_scale")
    size = _size(rec, dest)
    if size is not None and size.bankroll is None:
        causes.append("record_bankroll_unknown")
    return causes or ["size_other"]


def compare_plan(dest: str, verdict_dest: str, records_by_key: Mapping[str, DecisionRecord],
                 plan: Mapping[str, Any] | None) -> _Tally | None:
    """One plan against the record's verdict for `verdict_dest`. None when no plan."""
    if not isinstance(plan, Mapping):
        return None
    tally = _Tally()
    positions = {line_key(p): p for p in (plan.get("positions") or []) if isinstance(p, Mapping)}
    keys = set(positions) | {k for k, r in records_by_key.items()
                             if (v := _verdict(r, verdict_dest)) is not None and v.bet}
    for key in sorted(keys):
        rec = records_by_key.get(key)
        tally.compared += 1
        in_plan = key in positions
        verdict = _verdict(rec, verdict_dest) if rec else None
        record_bets = bool(verdict and verdict.bet)
        if rec is None:
            tally.disagree(None, key, "plan_has_line_not_on_board", ["no_record_for_line"])
            continue
        if in_plan != record_bets:
            if in_plan:
                tally.disagree(rec, key, "plan_bets_record_no", _record_no_causes(rec, verdict_dest))
            else:
                causes = ["plan_requires_suggested"] if not rec.board_suggested else ["plan_cut_or_refused"]
                tally.disagree(rec, key, "record_bets_plan_no", causes)
            continue
        tally.agree += 1
        if in_plan and record_bets:
            size = _size(rec, verdict_dest)
            plan_stake = _position_stake(positions[key])
            # The record's OWN stake (applied Kelly), not its live-equivalent: the point is
            # to see where the plan's chain departs from it (`full_kelly_band`, ...).
            ours = size.stake_dollars if size is not None else None
            if plan_stake is None or ours is None:
                tally.size_causes["unsized"] += 1
                continue
            tally.size_compared += 1
            if plan_stake > 0 and abs(ours / plan_stake - 1.0) <= SIZE_TOLERANCE:
                tally.size_agree += 1
            else:
                for cause in _size_causes(rec, verdict_dest, positions[key]):
                    tally.size_causes[cause] += 1
    return tally


def _order_key(order: Mapping[str, Any]) -> str:
    return str(order.get("idempotency_key") or order.get("order_id") or order.get("venue_order_id") or line_key(order))


def compare_orders(records_by_key: Mapping[str, DecisionRecord], orders: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for order in orders:
        venue = str(order.get("venue") or "").split(":")[-1].lower()
        dest = f"live:{venue}"
        key = line_key(order)
        rec = records_by_key.get(key)
        verdict = _verdict(rec, dest) if rec else None
        agree = bool(verdict and verdict.bet)
        causes = [] if agree else (_record_no_causes(rec, dest) if rec else ["no_record_for_line"])
        out.append({
            "order_key": _order_key(order), "line_key": key, "venue": venue,
            "label": _label(rec) if rec else key,
            "submitted_at": order.get("submitted_at") or order.get("created_at") or order.get("recorded_at"),
            "status": order.get("status"),
            "stake_dollars": _f(order.get("stake_dollars") or order.get("requested_stake_dollars")),
            "record_stake_dollars": (_size(rec, dest).stake_dollars if rec and _size(rec, dest) else None),
            "agree": agree, "causes": causes,
        })
    return out


def agreement_jsonl_path(selected_date: str, root: Path | None = None) -> Path:
    return records_dir(root) / f"{selected_date}.agreement.jsonl"


def report_paths(selected_date: str, root: Path | None = None) -> tuple[Path, Path]:
    base = records_dir(root)
    return base / f"{selected_date}.agreement_report.json", base / f"{selected_date}.agreement_report.md"


def build_agreement(records: Sequence[DecisionRecord], rows: Sequence[Mapping[str, Any]],
                    plans: Mapping[str, Any], live_orders: Sequence[Mapping[str, Any]], *,
                    board_floor: float = 2.0) -> dict[str, Any]:
    records_by_key = {r.key: r for r in records}
    rows_by_key = {line_key(r): r for r in rows if isinstance(r, Mapping)}
    board, forks = compare_board(records, rows_by_key, board_floor)
    by_dest: dict[str, Any] = {DESTINATION_BOARD: board.as_dict()}
    plan_pairs = [(DESTINATION_PAPER, DESTINATION_PAPER)]
    for venue in LIVE_VENUES:
        plan_pairs += [(f"paper:{venue}", f"live:{venue}"), (f"live:{venue}", f"live:{venue}")]
    for plan_name, verdict_dest in plan_pairs:
        tally = compare_plan(plan_name, verdict_dest, records_by_key, plans.get(plan_name))
        by_dest[plan_name] = tally.as_dict() if tally else {"status": "no_plan"}
    orders = compare_orders(records_by_key, live_orders)
    return {"by_destination": by_dest, "forks": forks, "live_orders": orders}


def record_build_agreement(selected_date: str, records: Sequence[DecisionRecord], rows: Sequence[Mapping[str, Any]],
                           plans: Mapping[str, Any], live_orders: Sequence[Mapping[str, Any]], *,
                           build_id: str, root: Path | None = None) -> dict[str, Any]:
    try:
        from syndicate.features.shared.decision_record import _board_min_ev_pct

        floor = _board_min_ev_pct()
    except Exception:  # noqa: BLE001
        floor = 2.0
    line = {
        "build_id": build_id,
        "written_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "records": len(records),
        **build_agreement(records, rows, plans, live_orders, board_floor=floor),
    }
    path = agreement_jsonl_path(selected_date, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(line, separators=(",", ":"), default=str) + "\n")
    report = write_daily_report(selected_date, root=root)
    board = line["by_destination"][DESTINATION_BOARD]
    print(
        f"[decision_record] DECISION_AGREEMENT date={selected_date} board={board['agree']}/{board['compared']} "
        + " ".join(
            f"{d}={v.get('agree')}/{v.get('compared')}" if "compared" in v else f"{d}=no_plan"
            for d, v in line["by_destination"].items() if d != DESTINATION_BOARD)
        + f" live_orders={sum(o['agree'] for o in line['live_orders'])}/{len(line['live_orders'])}"
        + f" builds={report.get('builds')}",
        flush=True,
    )
    return {"board": f"{board['agree']}/{board['compared']}", "builds": report.get("builds")}


# --------------------------------------------------------------------------- daily report


def _read_lines(path: Path) -> list[dict[str, Any]]:
    out = []
    try:
        with path.open(encoding="utf-8") as fh:
            for raw in fh:
                raw = raw.strip()
                if raw.startswith("{"):
                    try:
                        out.append(json.loads(raw))
                    except ValueError:
                        continue
    except OSError:
        return []
    return out


def summarize_day(lines: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Daily totals over every build, the latest build in full, and each live order once."""
    if not lines:
        return {"builds": 0}
    totals: dict[str, dict[str, Any]] = {}
    for line in lines:
        for dest, tally in (line.get("by_destination") or {}).items():
            if "compared" not in tally:
                continue
            agg = totals.setdefault(dest, {"builds": 0, "compared": 0, "agree": 0, "causes": Counter(),
                                           "size_compared": 0, "size_agree": 0, "size_causes": Counter()})
            agg["builds"] += 1
            for name in ("compared", "agree", "size_compared", "size_agree"):
                agg[name] += int(tally.get(name) or 0)
            agg["causes"].update(tally.get("causes") or {})
            agg["size_causes"].update(tally.get("size_causes") or {})
    for agg in totals.values():
        agg["agree_rate"] = round(agg["agree"] / agg["compared"], 4) if agg["compared"] else None
        agg["size_agree_rate"] = round(agg["size_agree"] / agg["size_compared"], 4) if agg["size_compared"] else None
        agg["causes"] = dict(agg["causes"].most_common())
        agg["size_causes"] = dict(agg["size_causes"].most_common())
    # Each live order judged ONCE, by the first build written at or after it was submitted
    # (the record that existed when it went out), else the latest build that saw it.
    orders: dict[str, dict[str, Any]] = {}
    for line in sorted(lines, key=lambda l: str(l.get("written_at") or "")):
        for order in line.get("live_orders") or []:
            key = order.get("order_key")
            seen = orders.get(key)
            submitted = str(order.get("submitted_at") or "")
            if seen is None or (str(seen.get("_build_at")) < submitted <= str(line.get("written_at"))):
                orders[key] = {**order, "_build_at": line.get("written_at")}
    order_list = [{k: v for k, v in o.items() if k != "_build_at"} | {"judged_by_build_at": o["_build_at"]}
                  for o in orders.values()]
    order_causes = Counter(c for o in order_list if not o["agree"] for c in (o.get("causes") or []))
    latest = lines[-1]
    return {
        "builds": len(lines),
        "first_build_at": lines[0].get("written_at"),
        "last_build_at": latest.get("written_at"),
        "totals": totals,
        "latest_build": {"build_id": latest.get("build_id"), "written_at": latest.get("written_at"),
                         "records": latest.get("records"), "by_destination": latest.get("by_destination"),
                         "forks": latest.get("forks")},
        "live_orders": {"count": len(order_list), "agree": sum(1 for o in order_list if o["agree"]),
                        "causes": dict(order_causes.most_common()), "orders": order_list},
    }


def _pct(a: int, b: int) -> str:
    return f"{a}/{b} ({100.0 * a / b:.1f}%)" if b else f"{a}/{b}"


def render_markdown(selected_date: str, summary: Mapping[str, Any]) -> str:
    lines = [f"# DecisionRecord agreement -- {selected_date}", ""]
    if not summary.get("builds"):
        return "\n".join(lines + ["No builds recorded."]) + "\n"
    lines += [
        "SHADOW: nothing reads the record for placement, sizing or the board (#709 step 2).",
        f"Builds: {summary['builds']} ({summary.get('first_build_at')} .. {summary.get('last_build_at')}). "
        "Daily totals sum per-build comparisons, so a line seen in N builds counts N times; the latest build is shown on its own.",
        "",
        "## Latest build",
    ]
    latest = summary.get("latest_build") or {}
    forks = latest.get("forks") or {}
    f3 = forks.get("F3_suggested_sim_opposes") or {}
    lines.append(f"- records {latest.get('records')}, suggested rows {forks.get('suggested_rows')}")
    lines.append(f"- F3 board suggests a side its sim opposes: {_pct(int(f3.get('count') or 0), int(f3.get('of_suggested_with_model') or 0))} of suggested rows with a model view")
    for venue, f1 in (forks.get("F1_suggested_negative_at_venue_price") or {}).items():
        lines.append(f"- F1 suggested but negative net at {venue}'s own price: {_pct(int(f1.get('count') or 0), int(f1.get('of_suggested_quoted') or 0))} of suggested rows {venue} quotes")
    lines += ["", "| destination | agree | size agree | top causes (membership) | top size causes |", "|---|---|---|---|---|"]
    for dest, tally in (latest.get("by_destination") or {}).items():
        if "compared" not in tally:
            lines.append(f"| {dest} | no plan | | | |")
            continue
        causes = ", ".join(f"{k} {v}" for k, v in list((tally.get("causes") or {}).items())[:4])
        size_causes = ", ".join(f"{k} {v}" for k, v in list((tally.get("size_causes") or {}).items())[:3])
        lines.append(f"| {dest} | {_pct(tally['agree'], tally['compared'])} | {_pct(tally['size_agree'], tally['size_compared'])} | {causes} | {size_causes} |")
    lines += ["", "## Day totals (summed over builds)", "", "| destination | builds | agree | size agree | top causes |", "|---|---|---|---|---|"]
    for dest, agg in (summary.get("totals") or {}).items():
        causes = ", ".join(f"{k} {v}" for k, v in list(agg["causes"].items())[:4])
        lines.append(f"| {dest} | {agg['builds']} | {_pct(agg['agree'], agg['compared'])} | {_pct(agg['size_agree'], agg['size_compared'])} | {causes} |")
    orders = summary.get("live_orders") or {}
    lines += ["", f"## Live orders on this slate: record agrees with {_pct(int(orders.get('agree') or 0), int(orders.get('count') or 0))}"]
    if orders.get("causes"):
        lines.append("Causes: " + ", ".join(f"{k} {v}" for k, v in orders["causes"].items()))
    for order in (orders.get("orders") or [])[:40]:
        mark = "agree" if order.get("agree") else "DISAGREE " + ",".join(order.get("causes") or [])
        lines.append(f"- {order.get('venue')} {order.get('label')} ${order.get('stake_dollars')} (record ${order.get('record_stake_dollars')}): {mark}")
    lines += ["", "## Samples of disagreement (latest build)"]
    for dest, tally in (latest.get("by_destination") or {}).items():
        for sample in (tally.get("samples") or [])[:6]:
            lines.append(f"- {dest}: {sample.get('label')} -- {sample.get('kind')}: {', '.join(sample.get('causes') or [])}")
    return "\n".join(lines) + "\n"


def write_daily_report(selected_date: str, *, root: Path | None = None) -> dict[str, Any]:
    summary = summarize_day(_read_lines(agreement_jsonl_path(selected_date, root)))
    summary = {"selected_date": selected_date, **summary}
    json_path, md_path = report_paths(selected_date, root)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    from syndicate.features.shared.decision_record import _atomic_write

    _atomic_write(json_path, json.dumps(summary, indent=1, default=str))
    _atomic_write(md_path, render_markdown(selected_date, summary))
    return summary
