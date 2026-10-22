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
    ("picks", "Syndicate picks"),          # the board's suggested opps the sim BACKS (2026-10-15) -- the headline section
    # ... and the ones it does not: the same price edge without the sim's backing. Kept apart so the record itself says
    # whether the sim's backing adds anything (user 2026-10-15: "split the season record into picks vs price plays").
    ("price_plays", "Price plays"),
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

# SAME-GAME PARLAYS, kept OUT of "All featured picks" (user 2026-10-19: "make sure ... the overall scorecards and
# scorecards by sports show all categories"). Paper only: no SGP price is published, so they carry a won-lost count and
# what our probabilities said (the sum of `p_joint` over the settled tickets) and never units. Graded by the rule the
# reconciled page and the paper ledger share (`cheat_sheets.sgp_results`).
SGP = "sgp"
SGP_LABEL = "Same-game parlays (paper)"
SGP_SPORTS = frozenset({"nfl", "nhl", "wnba", "nba", "mlb"})   # scripts/build_cheat_sheets.SGP_SPORTS (a test holds them equal)

# The sports each sport-specific category can appear for. A scorecard lists EVERY category that applies to its sport,
# with "no bets yet" where none was featured, so a missing category reads as "none yet" rather than as not tracked.
# Unlisted categories apply to every sport.
CATEGORY_SPORTS: dict[str, frozenset] = {
    "pvp_batters": frozenset({"mlb"}), "pvp_pitchers": frozenset({"mlb"}),
    "pvp_skaters": frozenset({"nhl"}), "pvp_goalies": frozenset({"nhl"}),
    "pvp_scorers": frozenset({"nba"}),
    "pvp_receivers": frozenset({"nfl"}), "pvp_qbs": frozenset({"nfl"}),
    SGP: SGP_SPORTS,
}


# CROSS-GAME PARLAYS (2026-10-20): graded by the reconcile into `cheatsheets_cross/<day>.graded.json`. Every ticket counts
# on the all-sports scorecard; a one-sport ticket (one sport across its games) also counts on that sport's. A book pays
# the full product on them, so unlike the same-game parlays they are counted in units -- and, like them, never inside
# "All featured picks".
CROSS_KINDS = (("xg_hit_rate", "Cross-game parlays: hit rate", "hit_rate"), ("xg_value", "Cross-game parlays: value", "value"))


def cross_totals(graded_docs: Iterable[Mapping[str, Any]], *, beta: bool
                 ) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, dict[str, Any]]]]:
    """({xg_hit_rate / xg_value: finish()} over every ticket, {sport: {...}} over the one-sport tickets) for the graded
    days on one side of OFFICIAL_START. A ticket across sports counts on the all-sports scorecard only."""
    by_kind = {kind: key for key, _label, kind in CROSS_KINDS}
    tallies: dict[str, dict[str, float]] = {}
    by_sport: dict[str, dict[str, dict[str, float]]] = {}
    for doc in graded_docs or []:
        if (str(doc.get("date") or "") < OFFICIAL_START) != beta:
            continue
        for res in (doc.get("tickets") or {}).values():
            key = by_kind.get(res.get("kind"))
            if not key or res.get("status") not in ("won", "lost"):
                continue
            result = {"y": 1 if res["status"] == "won" else 0, "units": res.get("units")}
            _add(tallies.setdefault(key, _tally()), result)
            scope = res.get("scope")
            if scope and scope != "multi":
                _add(by_sport.setdefault(scope, {}).setdefault(key, _tally()), result)
    return ({k: finish(t) for k, t in tallies.items()},
            {s: {k: finish(t) for k, t in kinds.items()} for s, kinds in by_sport.items()})


def applies(key: str, sport: str) -> bool:
    return sport in CATEGORY_SPORTS.get(key, frozenset(cs.SPORT_ORDER))


def _sgp_tally() -> dict[str, float]:
    return {"w": 0, "l": 0, "expected": 0.0, "pending": 0, "void": 0}


def sgp_tally(sheet: Mapping[str, Any], reconciled: Mapping[str, Any],
              posted: Mapping[str, Any] | None = None) -> dict[str, float] | None:
    """The day's parlays as the sheet showed them, graded; None when the sheet carried none. With `posted`, the posted
    ones only (the SHARED value, `shared_day`)."""
    tickets = list(sheet.get("sgp") or [])
    if cs.posted_sgps(posted):
        tickets = [t for t in cs.with_posted_sgps(tickets, posted) if t.get("posted")]
    if not tickets:
        return None
    t = _sgp_tally()
    for ticket, res in zip(tickets, cs.sgp_results(tickets, reconciled)):
        status = res.get("status")
        if status in ("won", "lost"):
            t["w" if status == "won" else "l"] += 1
            t["expected"] += float(ticket.get("p_joint") or 0.0)
        elif status == "void":
            t["void"] += 1
        else:
            t["pending"] += 1
    return t


def finish_sgp(t: Mapping[str, Any]) -> dict[str, Any]:
    """{w, l, n, win_pct, expected, expected_pct, pending, void, paper: True} -- no units: nothing was priced."""
    w, l = int(t.get("w", 0)), int(t.get("l", 0))
    n, expected = w + l, round(float(t.get("expected") or 0.0), 2)
    return {"w": w, "l": l, "n": n, "win_pct": round(100 * w / n, 1) if n else None, "expected": expected,
            "expected_pct": round(100 * expected / n, 1) if n else None, "pending": int(t.get("pending", 0)),
            "void": int(t.get("void", 0)), "paper": True}


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


def day_record(sheet: Mapping[str, Any], reconciled: Mapping[str, Any],
               posted: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """One sport's day: a tally per featured section, and all featured picks counted once. A row or game line that went
    out on an exported graphic (`posted`, user 2026-10-17) counts in its section whatever later builds made of the
    section, graded at the price the graphic showed.

    TWO VALUES (user 2026-10-22: "actually we should create a new value for shared record vs all"): this day's `sections` /
    `featured` are ALL -- every featured bet, posted rows pinned in; `shared` (`shared_day`) is only what went out on a
    graphic, graded at the posted price. Over the 5 export days to 10-21 consistency is 39-25 +2.25u all vs 26-14 +3.36u
    shared."""
    from syndicate.features.shared import play_cards as pc

    if posted:
        sheet = cs.with_posted(sheet, posted)
    sport, day_key = str(sheet.get("sport")), str(sheet.get("date"))
    rows = list(sheet.get("rows") or [])
    lines = list(sheet.get("game_lines") or [])
    row_ids = [pc.card_id(sport, day_key, r) for r in rows]
    line_ids = [pc.card_id(sport, day_key, g) for g in lines]
    first_row, first_line = cs.posted_first(posted, "rows"), cs.posted_first(posted, "lines")

    def price(item: Mapping[str, Any], first: Mapping[str, Any] | None) -> Any:
        return first["price"] if first and first.get("price") is not None else (item.get("check") or {}).get("price")

    props, line_results = reconciled.get("props") or {}, reconciled.get("lines") or {}
    row_result = [cs.result_for(price(r, first_row.get(cid)), props.get(cs.prop_result_key(r))) for r, cid in zip(rows, row_ids)]
    line_result = [cs.result_for(price(g, first_line.get(cid)), line_results.get(cs.line_result_key(g)))
                   for g, cid in zip(lines, line_ids)]
    picks = list(sheet.get("picks") or [])
    pick_results = reconciled.get("picks") or {}
    pick_result = [cs.result_for(pk.get("price"), pick_results.get(cs.pick_result_key(pk))) for pk in picks]
    secs = cs.pin_posted(cs.sections(rows), row_ids, cs.posted_entries(posted, "rows"))
    line_secs = cs.pin_posted(cs.game_line_sections(lines), line_ids, cs.posted_entries(posted, "lines")) if lines else {}
    tallies: dict[str, dict[str, float]] = {}
    # Every featured bet ONCE, keyed the grader's way: a Syndicate pick that is also a value row is one bet.
    featured: dict[str, Mapping[str, Any] | None] = {}
    play = [(pk.get("label") or cs.pick_label(pk)) == cs.PRICE_PLAY_LABEL for pk in picks]
    for key, _label in FEATURED:
        if key in ("picks", "price_plays"):
            ids = [i for i in range(len(picks)) if play[i] == (key == "price_plays")]
            results = [pick_result[i] for i in ids]
            featured.update({cs.pick_result_key(picks[i]): pick_result[i] for i in ids})
        elif key == "lines_value":
            ids = line_secs.get("value") or []
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
    parlays = sgp_tally(sheet, reconciled)
    shared = shared_day(sheet, reconciled, posted)
    return {"date": day, "sport": sheet.get("sport"), "beta": day < OFFICIAL_START,
            "sections": {k: finish(t) for k, t in tallies.items()}, ALL: finish(every),
            **({SGP: finish_sgp(parlays)} if parlays else {}),
            **({"shared": shared} if shared else {}),
            "graded": counts.get("props_graded", 0) + counts.get("lines_graded", 0) + counts.get("picks_graded", 0),
            "bets": counts.get("props", 0) + counts.get("lines", 0) + counts.get("picks", 0)}


# The record key a posted GAME LINE section counts under (the page's line sections -> FEATURED); others count in ALL only.
_SHARED_LINE_KEYS = {"value": "lines_value"}


def shared_day(sheet: Mapping[str, Any], reconciled: Mapping[str, Any],
               posted: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """The SHARED value for one sport's day: only the rows, game lines and parlays that went out on an exported graphic
    (`<sport>/<date>.posted.json`), each graded at the price the graphic showed -- per posted section (a featured key),
    every posted bet once (`featured`), and the posted parlays (`sgp`). None when nothing was posted. Syndicate picks are
    their own record and are never recorded as posted (`blueprints/cheat_sheets._NOT_POSTED`)."""
    from syndicate.features.shared import play_cards as pc

    if not posted:
        return None
    sheet = cs.with_posted(sheet, posted)
    sport, day_key = str(sheet.get("sport")), str(sheet.get("date"))
    featured_keys = {k for k, _label in FEATURED}
    tallies: dict[str, dict[str, float]] = {}
    once: dict[str, Mapping[str, Any] | None] = {}
    for kind, field, result_key, results in (("rows", "rows", cs.prop_result_key, reconciled.get("props") or {}),
                                             ("lines", "game_lines", cs.line_result_key, reconciled.get("lines") or {})):
        items = list(sheet.get(field) or [])
        index = {}
        for i, it in enumerate(items):
            index.setdefault(pc.card_id(sport, day_key, it), i)
        first = cs.posted_first(posted, kind)
        for e in cs.posted_entries(posted, kind):
            i = index.get(e["card_id"])
            if i is None:
                continue
            item, info = items[i], first.get(e["card_id"]) or {}
            price = info.get("price") if info.get("price") is not None else (item.get("check") or {}).get("price")
            res = cs.result_for(price, results.get(result_key(item)))
            key = e["section"] if kind == "rows" else _SHARED_LINE_KEYS.get(e["section"], "")
            if key in featured_keys:
                _add(tallies.setdefault(key, _tally()), res)
            once[cs.pick_result_key(item)] = res
    every = _tally()
    for res in once.values():
        _add(every, res)
    parlays = sgp_tally(sheet, reconciled, posted) if cs.posted_sgps(posted) else None
    if not once and not parlays:
        return None
    return {"sections": {k: finish(t) for k, t in tallies.items()}, ALL: finish(every),
            **({SGP: finish_sgp(parlays)} if parlays else {})}


def _scope(days: list[Mapping[str, Any]]) -> dict[str, Any]:
    total: dict[str, dict[str, float]] = {}
    by_sport: dict[str, dict[str, dict[str, float]]] = {}
    per_date: dict[str, dict[str, float]] = {}
    per_date_value: dict[str, dict[str, float]] = {}
    sgp_total: dict[str, float] = _sgp_tally()
    sgp_by_sport: dict[str, dict[str, float]] = {}
    for d in days:
        sport = str(d.get("sport"))
        for key, t in list((d.get("sections") or {}).items()) + [(ALL, d.get(ALL) or {})]:
            _merge(total.setdefault(key, _tally()), t)
            _merge(by_sport.setdefault(sport, {}).setdefault(key, _tally()), t)
        if d.get(SGP):
            for into in (sgp_total, sgp_by_sport.setdefault(sport, _sgp_tally())):
                for k in ("w", "l", "expected", "pending", "void"):
                    into[k] += d[SGP].get(k, 0) or 0
            by_sport.setdefault(sport, {})
        _merge(per_date.setdefault(d["date"], _tally()), d.get(ALL) or {})
        _merge(per_date_value.setdefault(d["date"], _tally()), (d.get("sections") or {}).get("value") or {})
    series, cum, cum_value = [], 0.0, 0.0
    for date in sorted(per_date):
        cum += per_date[date]["units"]
        cum_value += per_date_value[date]["units"]
        series.append({"date": date, "featured": finish(per_date[date]), "cum_units": round(cum, 2),
                       "cum_value_units": round(cum_value, 2)})
    totals = {k: finish(t) for k, t in total.items()}
    if any(sgp_total[k] for k in ("w", "l", "pending", "void")):
        totals[SGP] = finish_sgp(sgp_total)
    sports = {s: {k: finish(t) for k, t in secs.items()} for s, secs in sorted(by_sport.items())}
    for s, t in sgp_by_sport.items():
        sports[s][SGP] = finish_sgp(t)
    out = {"totals": totals,
           "by_sport": sports,
           "series": series, "days": len(per_date)}
    shared_days = [dict(d["shared"], date=d["date"], sport=d.get("sport")) for d in days if d.get("shared")]
    if shared_days and not any(d.get("_shared_scope") for d in days):
        # The same roll-up over the SHARED value (`shared_day`): one more scope inside this one.
        out["shared"] = _scope([dict(d, _shared_scope=True) for d in shared_days])
    return out


def season_record(days: Iterable[Mapping[str, Any]], *, generated_at: str,
                  cross: Iterable[Mapping[str, Any]] | None = None) -> dict[str, Any]:
    """The page's whole payload: the official record, the beta apart, and every day newest first. `cross`: the
    cross-game parlays' graded days (`reconcile_cheat_sheets.cross_graded`)."""
    days = sorted(days, key=lambda d: (str(d.get("date")), str(d.get("sport"))), reverse=True)
    cross = list(cross or [])
    official, beta = _scope([d for d in days if not d.get("beta")]), _scope([d for d in days if d.get("beta")])
    for scope, is_beta in ((official, False), (beta, True)):
        totals, sports = cross_totals(cross, beta=is_beta)
        scope["totals"].update(totals)
        for sport, kinds in sports.items():
            scope["by_sport"].setdefault(sport, {}).update(kinds)
    return {"generated_at": generated_at, "official_start": OFFICIAL_START,
            "sections": [{"key": k, "label": label} for k, label in FEATURED] + [{"key": ALL, "label": "All featured picks"},
                                                                                 {"key": SGP, "label": SGP_LABEL, "paper": True}]
                        + [{"key": key, "label": label, "cross": True} for key, label, _kind in CROSS_KINDS],
            # Every sport, and which sports each category applies to: a scorecard lists every category that applies
            # to its sport, "no bets yet" included, rather than only the ones that happen to have bets.
            "sports": list(cs.SPORT_ORDER),
            "applies": {**{k: sorted(s for s in cs.SPORT_ORDER if applies(k, s)) for k, _ in FEATURED + ((SGP, ""),)},
                        **{key: list(cs.SPORT_ORDER) for key, _label, _kind in CROSS_KINDS}},   # one-sport tickets: each sport
            "official": official,
            "beta": beta,
            "days": days}
