"""The cheat sheets' daily review (lane `cheat-sheets`, user 2026-10-15: "consider any kind of monitoring/optimizations
that should happen via a daily skill run based on section trends").

Runs right after the reconcile (Windows task `SyndicateCheatSheetsReconcile`, 7:45 AM CT) and writes
`<data root>/cheatsheets/reviews/<date>.md|.json` plus `latest.md|.json`. The daily Claude task
`cheat-sheet-review` only READS `latest.md` and reports it. Nothing here changes a sheet, a threshold or a section.

  HEALTH   is the pipeline doing its job: the record is fresh; yesterday's sheets were reconciled; how much of each
           sheet the grader settled; whether the actual-stat tap still sees its targets; why bets went unsettled
           (a rise in "not in the box score" is a NAME-MATCHING gap, e.g. a nickname); faces and positions.
  TRENDS   each featured section's season and last-7-day record, and slices of its bets by price band, EV band and
           sport -- the slices are what turn "this section is losing" into a specific threshold to look at.

A trend is FLAGGED only with 30+ bets AND a z of 2+ on ROI (z = ROI / its standard error, from the win rate and the
average payout). Below that it is printed as a reading, never a flag: a day or a week of results is mostly noise.
A flag is a PROPOSAL for a person to weigh: tighten that section's own entry rule, re-order sections, re-label. It
never removes a sport, a market or a market family -- accuracy ranks and stakes, it never hides (2026-10-05).

    python scripts/review_cheat_sheets.py --data-root ~/syndicate-prod/data
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.shared import cheat_sheet_record as csr  # noqa: E402
from syndicate.features.shared import cheat_sheets as cs  # noqa: E402
from syndicate.features.shared import play_cards as pc  # noqa: E402

MIN_BETS = 30          # below this a record is a reading, never a flag
FLAG_Z = 2.0           # |ROI / SE| needed to flag
STALE_HOURS = 26       # the record should be rebuilt every morning
MIN_GRADED_SHARE = 0.8
RECENT_DAYS = 7
LABELS = dict(csr.FEATURED)


def central_today() -> str:
    return pc.central(datetime.now(timezone.utc)).date().isoformat()


def roi_z(w: int, l: int, units: float) -> float | None:
    """ROI over its standard error. Each bet returns +payout or -1; the variance comes from the win rate and the
    average payout of the wins (a flat-stake approximation, fine for a guard)."""
    n = w + l
    if n < 2 or w == 0 or l == 0:
        return None
    p = w / n
    avg_win = (units + l) / w                       # mean payout of a winning bet
    var = p * (1 - p) * (avg_win + 1) ** 2
    se = math.sqrt(var / n)
    return round((units / n) / se, 2) if se else None


def verdict(t: Mapping[str, Any]) -> str:
    n = t.get("n", 0)
    if n < MIN_BETS:
        return f"reading only ({n} bets, flags need {MIN_BETS})"
    z = roi_z(t.get("w", 0), t.get("l", 0), t.get("units", 0.0))
    if z is None:
        return "reading only (no spread to test)"
    if z <= -FLAG_Z:
        return f"FLAG: losing beyond noise (z {z})"
    if z >= FLAG_Z:
        return f"FLAG: winning beyond noise (z {z}) -- keep, do not size up on results alone"
    return f"within noise (z {z})"


def _band(value: float | None, edges: Iterable[tuple[float, str]], default: str) -> str:
    if value is None:
        return "unknown"
    for edge, label in edges:
        if value < edge:
            return label
    return default


def price_band(price: Any) -> str:
    try:
        p = float(price)
    except (TypeError, ValueError):
        return "unknown"
    return _band(p, ((-200, "big favourite (-200 or shorter)"), (-120, "favourite (-199..-121)"),
                     (101, "near even (-120..+100)"), (200, "dog (+101..+199)")), "long dog (+200 or longer)")


def ev_band(ev: Any) -> str:
    try:
        e = float(ev)
    except (TypeError, ValueError):
        return "no fair line"
    return _band(e, ((0, "EV < 0"), (2, "EV 0-2%"), (5, "EV 2-5%"), (10, "EV 5-10%")), "EV 10%+")


def featured_bets(sheet: Mapping[str, Any], reconciled: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Every featured bet of one sheet with its section, sport, price, EV and graded result (per-bet, for slices)."""
    rows = list(sheet.get("rows") or [])
    props = reconciled.get("props") or {}
    secs = cs.sections(rows)
    out = []
    pick_results = reconciled.get("picks") or {}
    for pk in sheet.get("picks") or []:                         # the Syndicate picks: the board's suggested opps
        res = cs.result_for(pk.get("price"), pick_results.get(cs.pick_result_key(pk)))
        if res is not None and res.get("y") in (0.0, 1.0):
            section = "price_plays" if (pk.get("label") or cs.pick_label(pk)) == cs.PRICE_PLAY_LABEL else "picks"
            out.append({"section": section, "sport": sheet.get("sport"), "date": sheet.get("date"), "price": pk.get("price"),
                        "ev": pk.get("ev_pct"), "y": res["y"], "units": res["units"] or 0.0})
    for key, _label in csr.FEATURED:
        if key in ("lines_value", "picks", "price_plays"):
            continue
        for i in secs.get(key) or []:
            r = rows[i]
            check = r.get("check") or {}
            res = cs.result_for(check.get("price"), props.get(cs.prop_result_key(r)))
            if res is None or res.get("y") not in (0.0, 1.0):
                continue
            out.append({"section": key, "sport": sheet.get("sport"), "date": sheet.get("date"), "price": check.get("price"),
                        "ev": check.get("ev_market"), "y": res["y"], "units": res["units"] or 0.0})
    return out


def _tally(bets: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    t = {"w": 0, "l": 0, "units": 0.0}
    for b in bets:
        if b["y"] == 1:
            t["w"] += 1
            t["units"] += b["units"]
        else:
            t["l"] += 1
            t["units"] -= 1.0
    return csr.finish(t)


def load_days(sheets_dir: Path) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    out = []
    for rec_path in sorted(sheets_dir.glob("*/*.reconciled.json")):
        day = rec_path.name[: -len(".reconciled.json")]
        try:
            out.append((json.loads(rec_path.with_name(f"{day}.json").read_text(encoding="utf-8")),
                        json.loads(rec_path.read_text(encoding="utf-8"))))
        except (OSError, ValueError):
            continue
    return out


def health(sheets_dir: Path, days: list[tuple[dict, dict]], record: Mapping[str, Any] | None, *, today: str,
           now: datetime, log_tail: str) -> list[dict[str, Any]]:
    """[{level: ok|warn|fail, check, detail}] -- the pipeline's own state, before any trend is read."""
    checks: list[dict[str, Any]] = []

    def add(level: str, check: str, detail: str) -> None:
        checks.append({"level": level, "check": check, "detail": detail})

    if record is None:
        add("fail", "season record", "record.json is missing")
    else:
        age = (now - datetime.fromisoformat(record["generated_at"])).total_seconds() / 3600
        add("ok" if age <= STALE_HOURS else "fail", "season record", f"rebuilt {age:.1f} h ago")
    yesterday = (datetime.fromisoformat(today) - timedelta(days=1)).date().isoformat()
    published = {p.parent.name: p for p in sheets_dir.glob(f"*/{yesterday}.json")}
    reconciled = {s.get("sport"): (s, r) for s, r in days if s.get("date") == yesterday}
    for sport in sorted(published):
        try:
            sheet = json.loads(published[sport].read_text(encoding="utf-8"))
        except (OSError, ValueError):
            add("fail", f"{sport} {yesterday}", "sheet unreadable")
            continue
        if not (sheet.get("rows") or sheet.get("game_lines")):
            continue
        if sport not in reconciled:
            add("fail", f"{sport} {yesterday} reconcile", "published but not reconciled")
            continue
        c = reconciled[sport][1].get("counts") or {}
        share = c.get("props_graded", 0) / c["props"] if c.get("props") else 1.0
        add("ok" if share >= MIN_GRADED_SHARE else "warn", f"{sport} {yesterday} graded",
            f"{c.get('props_graded', 0)} of {c.get('props', 0)} props ({100 * share:.0f}%)")
        valued = c.get("props_valued", 0)
        if c.get("props_graded") and valued < 0.9 * c["props_graded"] and sport != "soccer":
            add("warn", f"{sport} {yesterday} actual stats", f"values on {valued} of {c['props_graded']} graded props -- "
                "a settler may have moved under the tap")
        void = defaultdict(int)
        for reason in (reconciled[sport][1].get("void") or {}).values():
            void[cs.void_label(reason)] += 1
        if void.get("Not in the box score", 0) >= 3:
            # NOT "usually a nickname or spelling" (2026-10-21): on the NCAAF 10-20 sheet all 9 such bets (4 players) were
            # on their team's ESPN roster and absent from the box -- no stat line, so a DNP void cannot be told from a
            # zero. Check the spelling only when a player IS in the box under another name.
            add("warn", f"{sport} {yesterday} not in the box score", f"{void['Not in the box score']} bets 'not in the box "
                "score' -- the player has no stat line (did not play, or played without one); a spelling mismatch is the "
                "rarer cause")
        rows = sheet.get("rows") or []
        faced = sum(1 for r in rows if r.get("headshot_url"))
        if rows and faced < 0.8 * len(rows) and sport != "soccer":
            add("warn", f"{sport} {yesterday} faces", f"{faced} of {len(rows)} rows have a photo")
    if "MISSING" in log_tail:
        add("fail", "actual-stat tap", "the last reconcile logged value hooks MISSING")
    if "pull failed" in log_tail:
        add("fail", "grader pull", "the last reconcile logged a failed pull")
    return checks


def trends(bets: list[dict[str, Any]], *, today: str) -> dict[str, Any]:
    recent_from = (datetime.fromisoformat(today) - timedelta(days=RECENT_DAYS)).date().isoformat()
    by_section: dict[str, list[dict]] = defaultdict(list)
    for b in bets:
        by_section[b["section"]].append(b)
    out = {}
    for key, rows in by_section.items():
        season = _tally(rows)
        recent = _tally([b for b in rows if b["date"] >= recent_from])
        slices = {}
        for name, fn in (("price", lambda b: price_band(b["price"])), ("ev", lambda b: ev_band(b["ev"])),
                         ("sport", lambda b: b["sport"])):
            groups: dict[str, list[dict]] = defaultdict(list)
            for b in rows:
                groups[fn(b)].append(b)
            slices[name] = {g: dict(_tally(v), verdict=verdict(_tally(v))) for g, v in sorted(groups.items())}
        out[key] = {"label": LABELS.get(key, key), "season": dict(season, verdict=verdict(season)),
                    "last_7_days": dict(recent, verdict=verdict(recent)), "slices": slices}
    return out


def render(review: Mapping[str, Any]) -> str:
    def rec(t: Mapping[str, Any]) -> str:
        roi = "–" if t.get("roi_pct") is None else f"{t['roi_pct']:+.1f}%"
        return f"{t['w']}-{t['l']} ({t['n']} bets) {t['units']:+.2f}u ROI {roi}"

    lines = [f"# Cheat-sheet review {review['date']} (scope: {review['scope']}, generated {review['generated_ct']})", "",
             "## Health", ""]
    for c in review["health"]:
        lines.append(f"- [{c['level'].upper()}] {c['check']}: {c['detail']}")
    lines += ["", "## Section trends", ""]
    if not review["trends"]:
        lines.append("- no graded featured bets in this scope yet")
    for key, t in review["trends"].items():
        lines.append(f"- **{t['label']}** season {rec(t['season'])} -- {t['season']['verdict']}; "
                     f"last {RECENT_DAYS} days {rec(t['last_7_days'])}")
        for name, groups in t["slices"].items():
            flagged = [f"{g}: {rec(v)} -- {v['verdict']}" for g, v in groups.items() if v["verdict"].startswith("FLAG")]
            for f in flagged:
                lines.append(f"  - {name} slice {f}")
    lines += ["", "## Flags", ""]
    flags = review["flags"]
    lines += [f"- {f}" for f in flags] if flags else ["- none: nothing is beyond noise (30+ bets and |z| >= 2 needed)"]
    lines += ["", "A flag is a proposal for a person: tighten that section's own entry rule, re-order, or re-label. "
              "Never remove a sport, a market or a market family."]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-root", default=os.environ.get("SYNDICATE_DATA_ROOT"))
    ap.add_argument("--log", default=None, help="the reconcile log to scan (default <data root>/../logs/cheat_sheets_reconcile.log)")
    ap.add_argument("--mirror", default=None, help="also write latest.md / latest.json here (the daily Claude task reads "
                                                   "this copy with the Read tool alone, so it needs no shell command)")
    args = ap.parse_args(argv)
    if not args.data_root:
        print("REFUSING: no --data-root", flush=True)
        return 2
    root = Path(os.path.expanduser(args.data_root))
    sheets_dir = root / "cheatsheets"
    now = datetime.now(timezone.utc)
    today = central_today()
    try:
        record = json.loads((sheets_dir / "record.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        record = None
    log_path = Path(args.log) if args.log else root.parent / "logs" / "cheat_sheets_reconcile.log"
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
        log_tail = text[text.rfind("RECONCILE_RUN"):] if "RECONCILE_RUN" in text else ""   # the LAST run only
    except OSError:
        log_tail = ""
    days = load_days(sheets_dir)
    official = [(s, r) for s, r in days if str(s.get("date")) >= pc.OFFICIAL_START]
    scope = "official" if official else "beta"
    bets = [b for s, r in (official or days) for b in featured_bets(s, r)]
    review = {"date": today, "scope": scope, "generated_at": now.isoformat(timespec="seconds"),
              "generated_ct": pc.central(now).strftime("%b %d %I:%M %p CT"),
              "health": health(sheets_dir, days, record, today=today, now=now, log_tail=log_tail),
              "trends": trends(bets, today=today)}
    flags = [f"{t['label']}: season {t['season']['verdict']}" for t in review["trends"].values() if t["season"]["verdict"].startswith("FLAG")]
    flags += [f"{t['label']} / {name} {g}: {v['verdict']}" for t in review["trends"].values()
              for name, groups in t["slices"].items() for g, v in groups.items() if v["verdict"].startswith("FLAG")]
    review["flags"] = flags
    out_dir = sheets_dir / "reviews"
    out_dir.mkdir(parents=True, exist_ok=True)
    text = render(review)
    for name, body in ((f"{today}.md", text), ("latest.md", text), (f"{today}.json", json.dumps(review, indent=1)),
                       ("latest.json", json.dumps(review, indent=1))):
        (out_dir / name).write_text(body, encoding="utf-8")
    if args.mirror:
        mirror = Path(os.path.expanduser(args.mirror))
        mirror.mkdir(parents=True, exist_ok=True)
        (mirror / "latest.md").write_text(text, encoding="utf-8")
        (mirror / "latest.json").write_text(json.dumps(review, indent=1), encoding="utf-8")
    worst = "fail" if any(c["level"] == "fail" for c in review["health"]) else "warn" if any(c["level"] == "warn" for c in review["health"]) else "ok"
    print(f"REVIEW date={today} scope={scope} health={worst} flags={len(flags)} bets={len(bets)} -> {out_dir / 'latest.md'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
