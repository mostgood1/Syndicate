"""The cheat sheets' running season record (lane `cheat-sheets`, user 2026-10-15: "add a running season record page for
the cheat sheets").

Built by `scripts/reconcile_cheat_sheets.py` after every grading run, from every reconciled day on disk, into
`<data root>/cheatsheets/record.json`; the page `/cheatsheets/record` only reads it.

What counts is what each day's sheet FEATURED -- the same sections the page showed (`cheat_sheets.sections` over the
sheet's rows, `game_line_sections(...)["value"]` over its game lines) -- each graded by production's grader, 1 unit a
bet at the sheet's best price (`cheat_sheets.result_for`). "All featured picks" counts a bet once a day even when two
sections featured it. The every-prop table and price shopping list both sides of a line, so they are never in the
record. A push, a void or a bet not graded yet is not in it either. Days before `play_cards.OFFICIAL_START` are the
beta and are kept apart from the official record.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping

from syndicate.features.shared import cheat_sheets as cs
from syndicate.features.shared.play_cards import OFFICIAL_START

# (key, label) in page order. Row sections first, then the game-line value section.
FEATURED: tuple[tuple[str, str], ...] = (
    ("picks", "Syndicate picks"),          # the board's suggested opps, promoted (2026-10-15) -- the headline section
    ("value", "Value at the best price"),
    ("hot_streaks", "Hot streaks"),
    ("hot_form", "Hot form, one-sided"),
    ("consistency", "Consistency"),
    ("matchup_spots", "Matchups"),
    ("pvp_batters", "Batter vs pitcher"),
    ("pvp_pitchers", "Pitcher vs lineup"),
    ("pvp_skaters", "Skater vs goalie"),
    ("pvp_goalies", "Goalie vs this team"),
    ("pvp_scorers", "Defender matchups"),
    ("pvp_receivers", "Defenders on his targets"),
    ("pvp_qbs", "QB vs this secondary"),
    ("lines_value", "Game lines: value"),
)
ALL = "featured"


def _tally() -> dict[str, float]:
    return {"w": 0, "l": 0, "units": 0.0}


def _add(t: dict[str, float], result: Mapping[str, Any] | None) -> None:
    if not result:
        return
    if result.get("y") == 1:
        t["w"] += 1
        t["units"] += float(result.get("units") or 0)
    elif result.get("y") == 0:
        t["l"] += 1
        t["units"] -= 1.0


def _merge(into: dict[str, float], other: Mapping[str, Any]) -> None:
    into["w"] += other.get("w", 0)
    into["l"] += other.get("l", 0)
    into["units"] += float(other.get("units") or 0)


def finish(t: Mapping[str, Any]) -> dict[str, Any]:
    """{w, l, n, units, win_pct, roi_pct}: ROI is units per bet, the honest number next to a win rate."""
    w, l = int(t.get("w", 0)), int(t.get("l", 0))
    n, units = w + l, round(float(t.get("units") or 0), 2)
    return {"w": w, "l": l, "n": n, "units": units,
            "win_pct": round(100 * w / n, 1) if n else None, "roi_pct": round(100 * units / n, 1) if n else None}


def day_record(sheet: Mapping[str, Any], reconciled: Mapping[str, Any]) -> dict[str, Any]:
    """One sport's day: a tally per featured section, and all featured picks counted once."""
    rows = list(sheet.get("rows") or [])
    lines = list(sheet.get("game_lines") or [])
    props, line_results = reconciled.get("props") or {}, reconciled.get("lines") or {}
    row_result = [cs.result_for((r.get("check") or {}).get("price"), props.get(cs.prop_result_key(r))) for r in rows]
    line_result = [cs.result_for((g.get("check") or {}).get("price"), line_results.get(cs.line_result_key(g))) for g in lines]
    picks = list(sheet.get("picks") or [])
    pick_results = reconciled.get("picks") or {}
    pick_result = [cs.result_for(pk.get("price"), pick_results.get(cs.pick_result_key(pk))) for pk in picks]
    secs = cs.sections(rows)
    tallies: dict[str, dict[str, float]] = {}
    # Every featured bet ONCE, keyed the grader's way: a Syndicate pick that is also a value row is one bet.
    featured: dict[str, Mapping[str, Any] | None] = {}
    for key, _label in FEATURED:
        if key == "picks":
            ids = list(range(len(picks)))
            results = [pick_result[i] for i in ids]
            featured.update({cs.pick_result_key(picks[i]): pick_result[i] for i in ids})
        elif key == "lines_value":
            ids = cs.game_line_sections(lines)["value"] if lines else []
            results = [line_result[i] for i in ids]
            featured.update({cs.pick_result_key(lines[i]): line_result[i] for i in ids})
        else:
            ids = secs.get(key) or []
            results = [row_result[i] for i in ids]
            featured.update({cs.pick_result_key(rows[i]): row_result[i] for i in ids})
        if not ids:
            continue
        t = tallies.setdefault(key, _tally())
        for res in results:
            _add(t, res)
    every = _tally()
    for res in featured.values():
        _add(every, res)
    day = str(sheet.get("date") or "")
    counts = reconciled.get("counts") or {}
    return {"date": day, "sport": sheet.get("sport"), "beta": day < OFFICIAL_START,
            "sections": {k: finish(t) for k, t in tallies.items()}, ALL: finish(every),
            "graded": counts.get("props_graded", 0) + counts.get("lines_graded", 0) + counts.get("picks_graded", 0),
            "bets": counts.get("props", 0) + counts.get("lines", 0) + counts.get("picks", 0)}


def _scope(days: list[Mapping[str, Any]]) -> dict[str, Any]:
    total: dict[str, dict[str, float]] = {}
    by_sport: dict[str, dict[str, dict[str, float]]] = {}
    per_date: dict[str, dict[str, float]] = {}
    per_date_value: dict[str, dict[str, float]] = {}
    for d in days:
        sport = str(d.get("sport"))
        for key, t in list((d.get("sections") or {}).items()) + [(ALL, d.get(ALL) or {})]:
            _merge(total.setdefault(key, _tally()), t)
            _merge(by_sport.setdefault(sport, {}).setdefault(key, _tally()), t)
        _merge(per_date.setdefault(d["date"], _tally()), d.get(ALL) or {})
        _merge(per_date_value.setdefault(d["date"], _tally()), (d.get("sections") or {}).get("value") or {})
    series, cum, cum_value = [], 0.0, 0.0
    for date in sorted(per_date):
        cum += per_date[date]["units"]
        cum_value += per_date_value[date]["units"]
        series.append({"date": date, "featured": finish(per_date[date]), "cum_units": round(cum, 2),
                       "cum_value_units": round(cum_value, 2)})
    return {"totals": {k: finish(t) for k, t in total.items()},
            "by_sport": {s: {k: finish(t) for k, t in secs.items()} for s, secs in sorted(by_sport.items())},
            "series": series, "days": len(per_date)}


def season_record(days: Iterable[Mapping[str, Any]], *, generated_at: str) -> dict[str, Any]:
    """The page's whole payload: the official record, the beta apart, and every day newest first."""
    days = sorted(days, key=lambda d: (str(d.get("date")), str(d.get("sport"))), reverse=True)
    return {"generated_at": generated_at, "official_start": OFFICIAL_START,
            "sections": [{"key": k, "label": label} for k, label in FEATURED] + [{"key": ALL, "label": "All featured picks"}],
            "official": _scope([d for d in days if not d.get("beta")]),
            "beta": _scope([d for d in days if d.get("beta")]),
            "days": days}
