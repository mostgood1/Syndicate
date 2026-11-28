"""The cheat sheets' scorecard: every featured bet of every official day, by sport x section x section-rules version,
with 95% intervals from a bootstrap over GAMES (lane `cheat-sheet-optimization`, todo #862, user 2026-11-27: "optimizing
the cheat sheets across all sports ... Most of them are currently losing").

WHAT IT COUNTS is exactly what the season record counts (`cheat_sheet_record.day_record`): each sheet's sections under
the rules version it was STAMPED with, posted rows and game lines pinned in and graded at their posted price, 1 u a bet
at the sheet's best price, a push / void / ungraded bet left out, "All featured picks" once a day. It keeps each bet
rather than a tally, so every cell can carry an interval, and it checks itself against `record.json` day by day: a
sport-day whose tally differs from the record's is printed and the script exits 3.

    BY RULES     section x rules version over all sports, then section x sport x rules version: W-L, units, ROI [95%],
                 the excess over the fair the sheet showed (hits minus `p_market`, in points) [95%], games, and a
                 verdict. The season line mixes days built under retired rules; this says how the rules IN FORCE do.
    RULE CHANGES on every sheet built under a newer rules version than its sport's earlier sheets: the bets the EARLIER
                 rules would have featured there and the new ones did not ("removed"), and the reverse ("added"),
                 re-derived from the same rows and graded the same way. This is the FORWARD test of each rule change:
                 the replay that motivated it was in sample. A removal is borne out when the removed bets keep losing.
                 "Earlier" is the version the sport's sheets last carried in scope (v1 -> v3 on 11-13: v2 never built a
                 final sheet); with no earlier sheet in scope it is vN-1. Only a rule inside `cheat_sheets.sections` can
                 be re-derived: v4 changed the "value" VERDICT stored on each row at build time, so v3 -> v4 shows no
                 change, and the page says so rather than leaving the row out.
    --replay N   the same comparison on every sheet in scope, rules N against the sheet's stamp: an IN-SAMPLE replay
                 for designing a rule, never evidence for one.

Why intervals by game: props of one game move together (a blowout sinks every over in it), so bets are not independent
draws and a per-bet interval is too narrow (`review_cheat_sheets._boot_ci`, the same resampler). So the VERDICT comes
from the game interval, not from the review's per-bet z (kept in --json as `z`): a cell is a reading until it has 30+
bets on 5+ games, and is beyond noise only when its ROI interval excludes 0. Measured on the first run (2026-11-27): the
per-bet z called NFL Sim vs the line v4 "losing beyond noise" on 45 bets from 4 games, and NFL Hot streaks v3 "within
noise" while its game interval was [-32.0, -0.6].

Read-only: it reads `<data root>/cheatsheets/<sport>/<day>.json|.reconciled.json|.posted.json` one day at a time and
`record.json`; it writes only `--out` / `--json`. A person reads it and decides; nothing here changes a sheet.

    python scripts/cheat_sheet_scorecard.py --data-root ~/syndicate-prod/data
    python scripts/cheat_sheet_scorecard.py --data-root ~/syndicate-prod/data --since 2026-11-13 --sport nba,nfl
    python scripts/cheat_sheet_scorecard.py --data-root ~/syndicate-prod/data --replay 5 --out scorecard.md
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
for _p in (REPO_ROOT, REPO_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import review_cheat_sheets as rcs  # noqa: E402  (the review's resampler, noise verdict and z)
from syndicate.features.shared import cheat_sheet_record as csr  # noqa: E402
from syndicate.features.shared import cheat_sheets as cs  # noqa: E402
from syndicate.features.shared import play_cards as pc  # noqa: E402

ALL = csr.ALL
SECTION_ORDER = [k for k, _label in csr.FEATURED] + [ALL]
LABELS = {**dict(csr.FEATURED), ALL: "All featured picks"}
MIN_GAMES = 5            # fewer games than this and an interval over games means nothing
MIN_SPORT_BETS = 15      # a sport x section x rules cell below this is left out of the sport table (it stays in --json)
UNITS_TOLERANCE = 0.015  # the record rounds each day's units to cents before summing


# ---------------------------------------------------------------------------------------------------------- the bets

def _bet(section: str, key: str, sport: str, day: str, rules: int, item: Mapping[str, Any], price: Any,
         result: Mapping[str, Any] | None, *, p_market: Any, ev: Any, one_sided: bool) -> dict[str, Any] | None:
    """One graded bet, or None when the record would not count it (no result, a push, a void)."""
    if not result or result.get("y") not in (0, 1):
        return None
    won = result.get("y") == 1
    event = item.get("event_id")
    return {"section": section, "key": key, "sport": sport, "date": day, "rules": rules,
            "event_id": str(event) if event not in (None, "") else f"{sport}:{day}:{key}",
            "price": price, "p_market": p_market if isinstance(p_market, (int, float)) else None, "ev": ev,
            "one_sided": one_sided, "y": 1.0 if won else 0.0,
            "units": float(result.get("units") or 0) if won else -1.0}


def day_bets(sheet: Mapping[str, Any], reconciled: Mapping[str, Any], posted: Mapping[str, Any] | None = None, *,
             rules: int | None = None) -> list[dict[str, Any]]:
    """Every graded featured bet of one sheet, one entry per section it sat in, plus one `ALL` entry per bet (the
    record's "All featured picks", once a day). Mirrors `cheat_sheet_record.day_record` line for line -- a test holds
    the two equal -- so a scorecard cell is the record's tally with an interval. `rules` re-derives the row sections
    under another version (posted items stay pinned: they went out whatever the rule); None is the sheet's own stamp."""
    if posted:
        sheet = cs.with_posted(sheet, posted)
    sport, day = str(sheet.get("sport")), str(sheet.get("date"))
    stamp = cs.sheet_rules(sheet)
    use = stamp if rules is None else int(rules)
    rows = list(sheet.get("rows") or [])
    lines = list(sheet.get("game_lines") or [])
    row_ids = [pc.card_id(sport, day, r) for r in rows]
    line_ids = [pc.card_id(sport, day, g) for g in lines]
    first_row, first_line = cs.posted_first(posted, "rows"), cs.posted_first(posted, "lines")

    def price(item: Mapping[str, Any], first: Mapping[str, Any] | None) -> Any:
        return first["price"] if first and first.get("price") is not None else (item.get("check") or {}).get("price")

    props, line_results = reconciled.get("props") or {}, reconciled.get("lines") or {}
    picks = list(sheet.get("picks") or [])
    pick_results = reconciled.get("picks") or {}
    play = [(pk.get("label") or cs.pick_label(pk)) == cs.PRICE_PLAY_LABEL for pk in picks]
    secs = cs.pin_posted(cs.sections(rows, rules=use), row_ids, cs.posted_entries(posted, "rows"))
    line_secs = cs.pin_posted(cs.game_line_sections(lines), line_ids, cs.posted_entries(posted, "lines")) if lines else {}

    out: list[dict[str, Any]] = []
    # The record's ALL is a dict keyed the grader's way, the LATER section's result winning -- None included.
    featured: dict[str, dict[str, Any] | None] = {}
    for key, _label in csr.FEATURED:
        if key in ("picks", "price_plays"):
            for i, pk in enumerate(picks):
                if play[i] != (key == "price_plays"):
                    continue
                rk = cs.pick_result_key(pk)
                b = _bet(key, rk, sport, day, use, pk, pk.get("price"),
                         cs.result_for(pk.get("price"), pick_results.get(rk)),
                         p_market=pk.get("p_market"), ev=pk.get("ev_pct"), one_sided=False)
                featured[rk] = b
                if b:
                    out.append(b)
        elif key == "lines_value":
            for i in line_secs.get("value") or []:
                g = lines[i]
                check = g.get("check") or {}
                p = price(g, first_line.get(line_ids[i]))
                b = _bet(key, cs.pick_result_key(g), sport, day, use, g, p,
                         cs.result_for(p, line_results.get(cs.line_result_key(g))),
                         p_market=check.get("p_market"), ev=check.get("ev_market"), one_sided=False)
                featured[cs.pick_result_key(g)] = b
                if b:
                    out.append(b)
        else:
            for i in secs.get(key) or []:
                r = rows[i]
                check = r.get("check") or {}
                p = price(r, first_row.get(row_ids[i]))
                b = _bet(key, cs.pick_result_key(r), sport, day, use, r, p,
                         cs.result_for(p, props.get(cs.prop_result_key(r))),
                         p_market=check.get("p_market"), ev=check.get("ev_market"),
                         one_sided=check.get("verdict") == "one_sided_fair")
                featured[cs.pick_result_key(r)] = b
                if b:
                    out.append(b)
    out += [dict(b, section=ALL) for b in featured.values() if b]
    return out


def iter_days(sheets_dir: Path, *, since: str | None = None, until: str | None = None,
              sports: set[str] | None = None) -> Iterator[tuple[dict[str, Any], dict[str, Any], dict[str, Any] | None, Path]]:
    """(sheet, reconciled, posted, reconciled path) for every reconciled OFFICIAL day in scope, one at a time: a sheet
    is up to ~1.2 MB of JSON, and holding a season of them would cost gigabytes."""
    for rec_path in sorted(sheets_dir.glob("*/*.reconciled.json")):
        sport, day = rec_path.parent.name, rec_path.name[: -len(".reconciled.json")]
        if day < pc.OFFICIAL_START or (since and day < since) or (until and day > until):
            continue
        if sports and sport not in sports:
            continue
        try:
            reconciled = json.loads(rec_path.read_text(encoding="utf-8"))
            sheet = json.loads(rec_path.with_name(f"{day}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        yield sheet, reconciled, cs.load_posted(sheets_dir, sport, day), rec_path


def rule_diff(old: Iterable[Mapping[str, Any]], new: Iterable[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """{"removed": bets `old` featured and `new` did not, "added": the reverse} -- per section, by result key."""
    have_old = {(b["section"], b["key"]): b for b in old}
    have_new = {(b["section"], b["key"]): b for b in new}
    return {"removed": [b for k, b in have_old.items() if k not in have_new],
            "added": [b for k, b in have_new.items() if k not in have_old]}


# ------------------------------------------------------------------------------------------------ the record check

def _day_tally(bets: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = defaultdict(lambda: {"w": 0, "l": 0, "units": 0.0})
    for b in bets:
        t = out[b["section"]]
        t["w" if b["y"] == 1 else "l"] += 1
        t["units"] += b["units"]
    return out


def check_day(bets: Iterable[Mapping[str, Any]], record_day: Mapping[str, Any]) -> list[str]:
    """Where one sport-day's bets differ from the record's tally of it ([] when they agree)."""
    mine = _day_tally(bets)
    theirs = dict(record_day.get("sections") or {})
    theirs[ALL] = record_day.get(ALL) or {}
    out = []
    for key in sorted(set(mine) | set(theirs)):
        a, b = mine.get(key, {"w": 0, "l": 0, "units": 0.0}), theirs.get(key) or {}
        if (a["w"], a["l"]) != (b.get("w", 0), b.get("l", 0)) or abs(round(a["units"], 2) - float(b.get("units") or 0)) > UNITS_TOLERANCE:
            out.append(f"{key}: scorecard {a['w']}-{a['l']} {a['units']:+.2f}u, record {b.get('w', 0)}-{b.get('l', 0)} "
                       f"{float(b.get('units') or 0):+.2f}u")
    return out


def _changed_after(paths: Iterable[Path], moment: datetime | None) -> bool:
    if moment is None:
        return False
    for p in paths:
        try:
            if datetime.fromtimestamp(p.stat().st_mtime, timezone.utc) > moment:
                return True
        except OSError:
            continue
    return False


# ------------------------------------------------------------------------------------------------------ the cells

def cell(bets: list[Mapping[str, Any]], *, resamples: int = rcs.BOOT_RESAMPLES) -> dict[str, Any]:
    """W-L, units, ROI and the excess over the shown fair, each with a 95% interval over games once the cell has
    `review_cheat_sheets.MIN_BETS` bets on `MIN_GAMES` games; below that it is a reading."""
    w = sum(1 for b in bets if b["y"] == 1)
    n = len(bets)
    units = sum(b["units"] for b in bets)
    games = len({b["event_id"] for b in bets})
    out: dict[str, Any] = {"n": n, "w": w, "l": n - w, "units": round(units, 2),
                           "roi_pct": round(100 * units / n, 1) if n else None, "games": games,
                           "dates": [min(b["date"] for b in bets), max(b["date"] for b in bets)] if bets else None,
                           "days": len({b["date"] for b in bets})}
    fair = [b for b in bets if b["p_market"] is not None]
    if fair:
        out["excess_pts"] = round(100 * sum(b["y"] - b["p_market"] for b in fair) / len(fair), 1)
        out["excess_n"] = len(fair)
    if n >= rcs.MIN_BETS and games >= MIN_GAMES:
        ci = rcs._boot_ci(rcs._by_game((b["event_id"], b["units"]) for b in bets), resamples=resamples)
        if ci:
            out["roi_ci"] = [round(100 * ci[0], 1), round(100 * ci[1], 1)]
        if len(fair) >= rcs.MIN_BETS:
            ci = rcs._boot_ci(rcs._by_game((b["event_id"], b["y"] - b["p_market"]) for b in fair), resamples=resamples)
            if ci:
                out["excess_ci"] = [round(100 * ci[0], 1), round(100 * ci[1], 1)]
                out["vs_price"] = "beats" if ci[0] > 0 else "trails" if ci[1] < 0 else "not separable from"
    out["z"] = rcs.roi_z(out["w"], out["l"], units)
    out["verdict"] = verdict(out)
    return out


def verdict(c: Mapping[str, Any]) -> str:
    """From the ROI interval over games: a reading below 30 bets / 5 games, else beyond noise only when it excludes 0."""
    ci = c.get("roi_ci")
    if not ci:
        return f"reading ({c.get('n', 0)} bets on {c.get('games', 0)} games)"
    if ci[1] < 0:
        return "losing beyond noise"
    if ci[0] > 0:
        return "winning beyond noise"
    return "within noise"


def _group(bets: Iterable[Mapping[str, Any]], *fields: str) -> dict[tuple, list[Mapping[str, Any]]]:
    out: dict[tuple, list[Mapping[str, Any]]] = defaultdict(list)
    for b in bets:
        out[tuple(b[f] for f in fields)].append(b)
    return out


def _section_rank(key: str) -> int:
    return SECTION_ORDER.index(key) if key in SECTION_ORDER else len(SECTION_ORDER)


def build(sheets_dir: Path, *, since: str | None = None, until: str | None = None, sports: set[str] | None = None,
          replay: int | None = None, record: Mapping[str, Any] | None = None, check: bool = True,
          resamples: int = rcs.BOOT_RESAMPLES) -> dict[str, Any]:
    record_days = {(str(d.get("sport")), str(d.get("date"))): d for d in (record or {}).get("days") or []}
    try:
        generated = datetime.fromisoformat(str((record or {}).get("generated_at")))
    except ValueError:
        generated = None
    bets: list[dict[str, Any]] = []
    changes: list[dict[str, Any]] = []   # rule-change diffs, each bet tagged with the change it measures
    replays: list[dict[str, Any]] = []
    sheets: dict[tuple[str, int], set[str]] = defaultdict(set)
    checked = matched = skipped = missing = 0
    mismatches: list[str] = []
    seen: dict[str, set[int]] = defaultdict(set)   # the stamps each sport's earlier sheets carried (days come in order)
    change_sheets: dict[str, int] = defaultdict(int)
    for sheet, reconciled, posted, rec_path in iter_days(sheets_dir, since=since, until=until, sports=sports):
        sport, day = str(sheet.get("sport")), str(sheet.get("date"))
        stamp = cs.sheet_rules(sheet)
        sheets[(sport, stamp)].add(day)
        earlier = [v for v in seen[sport] if v < stamp]
        prior = max(earlier) if earlier else stamp - 1
        seen[sport].add(stamp)
        own = day_bets(sheet, reconciled, posted)
        bets += own
        if check and record is not None:
            rd = record_days.get((sport, day))
            files = [rec_path, rec_path.with_name(f"{day}.json"), rec_path.with_name(f"{day}{cs.POSTED_SUFFIX}")]
            if rd is None:
                missing += 1
            elif _changed_after(files, generated):
                skipped += 1
            else:
                checked += 1
                diff = check_day(own, rd)
                if diff:
                    mismatches.append(f"{sport} {day}: " + "; ".join(diff))
                else:
                    matched += 1
        if prior >= 1:
            change_sheets[f"v{prior} -> v{stamp}"] += 1
            d = rule_diff(day_bets(sheet, reconciled, posted, rules=prior), own)
            for side, items in d.items():
                changes += [dict(b, change=f"v{prior} -> v{stamp}", side=side) for b in items]
        if replay is not None and replay != stamp:
            d = rule_diff(own, day_bets(sheet, reconciled, posted, rules=replay))
            for side, items in d.items():
                replays += [dict(b, change=f"v{stamp} -> v{replay} (replay)", side=side) for b in items]

    def table(items: list[Mapping[str, Any]], fields: tuple[str, ...], min_n: int = 0) -> list[dict[str, Any]]:
        rows = []
        for k, group in _group(items, *fields).items():
            if len(group) < min_n:
                continue
            rows.append({**dict(zip(fields, k)), **cell(list(group), resamples=resamples)})
        def order(r: Mapping[str, Any]) -> tuple:
            return tuple(_section_rank(r[f]) if f == "section" else (r[f] != "removed") if f == "side" else r[f]
                         for f in fields)
        return sorted(rows, key=order)

    versions = {}
    for (sport, v), days in sorted(sheets.items()):
        e = versions.setdefault(f"v{v}", {"sheets": 0, "dates": set()})
        e["sheets"] += len(days)
        e["dates"] |= days
    all_days = sorted({b["date"] for b in bets})
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "scope": {"since": since, "until": until, "sports": sorted(sports) if sports else "all",
                  "first": all_days[0] if all_days else None, "last": all_days[-1] if all_days else None,
                  "dates": len(all_days), "sheets": sum(len(d) for d in sheets.values()),
                  "bets": sum(1 for b in bets if b["section"] == ALL)},
        "versions": {v: {"sheets": e["sheets"], "dates": len(e["dates"]), "first": min(e["dates"]), "last": max(e["dates"])}
                     for v, e in sorted(versions.items())},
        "record_check": None if not check or record is None else {
            "record_generated_at": (record or {}).get("generated_at"), "checked": checked, "matched": matched,
            "skipped_changed_since": skipped, "not_in_record": missing, "mismatches": mismatches},
        "by_rules": table([b for b in bets], ("section", "rules")),
        "by_sport": table(bets, ("section", "sport", "rules")),
        "rule_changes": table(changes, ("change", "section", "side")),
        "rule_change_sheets": dict(sorted(change_sheets.items())),
        "rule_changes_by_sport": table(changes, ("change", "section", "sport", "side")),
        **({"replay": {"rules": replay, "rows": table(replays, ("change", "section", "side")),
                       "by_sport": table(replays, ("change", "section", "sport", "side"))}} if replay is not None else {}),
    }


# ------------------------------------------------------------------------------------------------------- the page

def _md(d: str) -> str:
    return d[5:] if d else "?"


def _ci(c: Mapping[str, Any], key: str) -> str:
    v = c.get(key)
    return f" [{v[0]:+.1f}, {v[1]:+.1f}]" if v else ""


def _roi(c: Mapping[str, Any]) -> str:
    return "–" if c.get("roi_pct") is None else f"{c['roi_pct']:+.1f}%{_ci(c, 'roi_ci')}"


def _excess(c: Mapping[str, Any]) -> str:
    return "–" if c.get("excess_pts") is None else f"{c['excess_pts']:+.1f}{_ci(c, 'excess_ci')}"


def _short_verdict(c: Mapping[str, Any]) -> str:
    v = str(c.get("verdict") or "")
    if v.endswith("beyond noise"):
        return f"**{v}**"
    return "reading" if v.startswith("reading") else v


def _line(c: Mapping[str, Any], *lead: str) -> str:
    dates = f"{_md(c['dates'][0])}..{_md(c['dates'][1])} ({c['days']})" if c.get("dates") else "–"
    return ("| " + " | ".join(lead) + f" | {dates} | {c['w']}-{c['l']} | {c['units']:+.1f} | {_roi(c)} | {_excess(c)} | "
            f"{c['games']} | {_short_verdict(c)}{'; ' + c['vs_price'] + ' the price' if c.get('vs_price') in ('beats', 'trails') else ''} |")


HEAD = "| dates (days) | W-L | units | ROI [95%] | vs fair, pts [95%] | games | verdict |"


def render(sc: Mapping[str, Any], *, min_sport_bets: int = MIN_SPORT_BETS) -> str:
    s = sc["scope"]
    out = [f"# Cheat-sheet scorecard -- official days {s['first']}..{s['last']}", "",
           f"Generated {sc['generated_at']}. Scope: sports {s['sports'] if isinstance(s['sports'], str) else ', '.join(s['sports'])}"
           f"{', from ' + s['since'] if s['since'] else ''}{', to ' + s['until'] if s['until'] else ''}. "
           f"{s['bets']:,} featured bets on {s['sheets']} sheets over {s['dates']} dates; 1 u a bet at the sheet's best "
           "price (a posted bet at its posted price), a push, void or ungraded bet left out -- the season record's own "
           "count. ROI and the excess over the fair the sheet showed carry a 95% interval from a bootstrap over games "
           f"once a cell has {rcs.MIN_BETS}+ bets on {MIN_GAMES}+ games; below that a cell is a reading. **Beyond noise** "
           "means the ROI interval excludes 0; \"beats/trails the price\" means the excess interval does.", ""]
    rc = sc.get("record_check")
    if rc:
        line = (f"**Checked against `record.json`** (generated {rc['record_generated_at']}): {rc['matched']} of "
                f"{rc['checked']} sport-days equal")
        if rc["skipped_changed_since"]:
            line += f"; {rc['skipped_changed_since']} skipped (a file changed after the record was built)"
        if rc["not_in_record"]:
            line += f"; {rc['not_in_record']} not in the record yet"
        out += [line + ".", ""]
        out += [f"- MISMATCH {m}" for m in rc["mismatches"][:20]]
        if rc["mismatches"]:
            out.append("")
    out.append("Rules versions (sheets, dates): " + "; ".join(
        f"{v} {e['sheets']} sheets / {e['dates']} dates {_md(e['first'])}..{_md(e['last'])}" for v, e in sc["versions"].items()))
    out += ["", "## By section and rules version (all sports)", "", "| section | rules " + HEAD,
            "|---|---|---|---|---|---|---|---|---|"]
    out += [_line(c, LABELS.get(c["section"], c["section"]), f"v{c['rules']}") for c in sc["by_rules"]]
    out += ["", f"## By sport, section and rules version ({min_sport_bets}+ bets)", "", "| section | sport | rules " + HEAD,
            "|---|---|---|---|---|---|---|---|---|---|"]
    out += [_line(c, LABELS.get(c["section"], c["section"]), c["sport"], f"v{c['rules']}")
            for c in sc["by_sport"] if c["n"] >= min_sport_bets]
    out += ["", "## Rule changes, graded forward", "",
            "On each sheet built under newer rules than its sport's earlier sheets: the bets the earlier rules would have "
            "featured there and the new ones did not (**removed**), and the reverse (**added**), re-derived from the same "
            "rows and graded the same way. A removal is borne out when what it removed keeps losing; an addition when "
            "what it added beats the section it joined.", ""]
    out += _change_lines(sc["rule_changes"], sc["rule_changes_by_sport"], min_sport_bets)
    with_bets = {c["change"] for c in sc["rule_changes"]}
    quiet = [f"{ch} ({n} sheets)" for ch, n in (sc.get("rule_change_sheets") or {}).items() if ch not in with_bets]
    if quiet:
        out += ["", "No featured bet changes when these are re-derived from the same rows: " + "; ".join(quiet) + ". A "
                "rule applied when the sheet was built and stored on its rows (v4: the board's \"value\" verdict) cannot "
                "be re-derived, so its effect is not measured here."]
    rp = sc.get("replay")
    if rp:
        out += ["", f"## Replay: rules v{rp['rules']} on every sheet in scope (IN SAMPLE)", "",
                "What rules v{0} would remove from and add to each sheet against the rules it was built with. These are "
                "the days a rule is designed from: a replay shows what a rule does, never that it works.".format(rp["rules"]), ""]
        out += _change_lines(rp["rows"], rp["by_sport"], min_sport_bets)
    return "\n".join(out) + "\n"


def _change_lines(rows: list[Mapping[str, Any]], by_sport: list[Mapping[str, Any]], min_sport_bets: int) -> list[str]:
    if not rows:
        return ["- no sheet in scope changed a featured bet"]
    out = ["| change | section | side " + HEAD, "|---|---|---|---|---|---|---|---|---|---|"]
    out += [_line(c, c["change"], LABELS.get(c["section"], c["section"]), c["side"]) for c in rows]
    sport_rows = [c for c in by_sport if c["n"] >= min_sport_bets]
    if sport_rows:
        out += ["", "| change | section | sport | side " + HEAD, "|---|---|---|---|---|---|---|---|---|---|---|"]
        out += [_line(c, c["change"], LABELS.get(c["section"], c["section"]), c["sport"], c["side"]) for c in sport_rows]
    return out


# ------------------------------------------------------------------------------------------------------------ main

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-root", default=os.environ.get("SYNDICATE_DATA_ROOT"))
    ap.add_argument("--since", default=None, help="first day, YYYY-MM-DD (default: the official start)")
    ap.add_argument("--until", default=None, help="last day, YYYY-MM-DD")
    ap.add_argument("--sport", default=None, help="comma list, e.g. nba,nfl (default: every sport)")
    ap.add_argument("--replay", type=int, default=None, help="also replay this rules version on every sheet (in sample)")
    ap.add_argument("--min-bets", type=int, default=MIN_SPORT_BETS, help="smallest sport cell printed (all are in --json)")
    ap.add_argument("--resamples", type=int, default=rcs.BOOT_RESAMPLES)
    ap.add_argument("--no-check", action="store_true", help="skip the check against record.json")
    ap.add_argument("--out", default=None, help="write the markdown here (default: stdout)")
    ap.add_argument("--json", default=None, help="also write the full scorecard as JSON here")
    args = ap.parse_args(argv)
    if not args.data_root:
        print("REFUSING: no --data-root (or SYNDICATE_DATA_ROOT)", flush=True)
        return 2
    sheets_dir = Path(os.path.expanduser(args.data_root)) / "cheatsheets"
    if args.replay is not None and args.replay < 1:
        print(f"REFUSING: --replay {args.replay} is not a rules version", flush=True)
        return 2
    try:
        record = json.loads((sheets_dir / "record.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        record = None
    sports = {s.strip().lower() for s in args.sport.split(",") if s.strip()} if args.sport else None
    sc = build(sheets_dir, since=args.since, until=args.until, sports=sports, replay=args.replay, record=record,
               check=not args.no_check, resamples=args.resamples)
    if not sc["scope"]["dates"]:
        print(f"REFUSING: no graded official day in scope under {sheets_dir}", flush=True)
        return 2
    text = render(sc, min_sport_bets=args.min_bets)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    if args.json:
        Path(args.json).write_text(json.dumps(sc, indent=1), encoding="utf-8")
    rc = sc.get("record_check")
    check_text = "skipped" if rc is None else f"{rc['matched']}/{rc['checked']}" + (
        f" MISMATCH {len(rc['mismatches'])}" if rc["mismatches"] else "")
    print(f"SCORECARD days={sc['scope']['dates']} sheets={sc['scope']['sheets']} bets={sc['scope']['bets']} "
          f"record_check={check_text}{' -> ' + args.out if args.out else ''}", file=sys.stderr, flush=True)
    if record is None and not args.no_check:
        print("NOTE: no record.json under the data root, so nothing was checked against it", file=sys.stderr, flush=True)
    return 3 if rc and rc["mismatches"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
