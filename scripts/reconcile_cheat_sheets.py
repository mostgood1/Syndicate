"""Reconcile the cheat sheets (lane `cheat-sheets`, user 2026-10-15: "can we reconcile the historical cheat sheets?
Have a button that toggles between pregame sheets and reconciled sheets").

For each day's sheets (`<data root>/cheatsheets/<sport>/<date>.json`), grade every prop and game line through
PRODUCTION'S OWN GRADER -- `score_ranking_backtest.py pull --source recorder`, the path the nightly scorecard and
`grade_play_cards.py` use -- and write `<sport>/<date>.reconciled.json` beside the sheet. The page reads it and toggles
between the sheet as published and the sheet with its results; the sheet itself is never changed.

    props  matched on the grader's own key: player, market, side, line (`cheat_sheets.prop_result_key`)
    lines  matched on event, market, side (home / away / over / under) and line (`cheat_sheets.line_result_key`)
    y      1 won, 0 lost; a push, a void (did not play) or a game not final carries no result and shows as "--"

Units are computed by the page at the sheet's best price, 1 unit a bet. A day is re-graded on every run until it is
complete, so a late final fills in. No OddsAPI: the grader reads the recorder through the web's ops API and settles
from free box scores, cached under `cheatsheets/.reconcile_cache/`.

    python scripts/reconcile_cheat_sheets.py --data-root ~/syndicate-prod/data            # today and the 2 days before
    python scripts/reconcile_cheat_sheets.py --data-root ~/syndicate-prod/data --date 2026-10-14
"""
from __future__ import annotations

import argparse
import collections
import importlib.util
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.shared import cheat_sheets as cs  # noqa: E402
from syndicate.features.shared import play_cards as pc  # noqa: E402

DAYS_BACK = 2
SOURCE = "score_ranking_backtest pull --source recorder (production's grader)"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def central_today() -> str:
    return pc.central(datetime.now(timezone.utc)).date().isoformat()


def _key_of(shaped: Mapping[str, Any]) -> str:
    """ONE key for every graded thing -- props, game lines and Syndicate picks, segment included (a pick can be a
    1st-3-innings moneyline): `cheat_sheets.pick_result_key`."""
    return cs.pick_result_key(shaped)


class ValueTap:
    """The number each production settler graded on -- read WITHOUT changing what any settler returns
    (user 2026-10-15: "yes add the actual stat line too").

    The settlers keep the value to themselves, their files belong to another lane, and production grading must not
    move for a display column. So for the length of one pull, in THIS process only, this wraps:
      * the entry points that receive the record being graded: `CompositeSettler.__call__` (every extra settler)
        and `MlbPropGrader.settle` (MLB props);
      * the comparisons that receive the number: `resolve_bet_status` as the ESPN (football, basketball, game lines)
        and NHL settlers call it, `prop_outcomes.settle_prop` (MLB props), `settle_over_under` (soccer stats) and
        `settle_runs` (MLB game lines).
    Every wrapper passes its arguments through untouched and returns the original's result, so the value shown is
    the one the result was decided on. A target that no longer exists is reported in `missing`, never guessed: that
    sport's values are simply absent and the run says so. Soccer's goalscorer markets compare no number (a goal
    count is checked inline), so they carry a result and no value."""

    def __init__(self) -> None:
        self.values: dict[str, dict[str, Any]] = {}
        self.reasons: dict[str, str] = {}            # why a record was NOT graded: did not play, push, not final ...
        self.scores: dict[str, dict[str, float]] = {}  # event id -> the full-game final, home and away
        self.missing: list[str] = []
        self._current: Mapping[str, Any] | None = None
        self._restore: list[tuple[Any, str, Any]] = []

    def _wrap(self, owner: Any, name: str, make: Callable[[Any], Any]) -> None:
        original = getattr(owner, name, None)
        if original is None:
            self.missing.append(f"{getattr(owner, '__name__', owner)}.{name}")
            return
        self._restore.append((owner, name, original))
        setattr(owner, name, make(original))

    def _entry(self, original: Any) -> Any:
        tap = self

        def entry(settler: Any, shaped: Mapping[str, Any], *args: Any, **kwargs: Any) -> Any:
            outer, tap._current = tap._current, shaped
            try:
                out = original(settler, shaped, *args, **kwargs)
                if isinstance(out, tuple) and out and (out[0] is None or out[0] == "push"):
                    tap.reasons[_key_of(shaped)] = "push" if out[0] == "push" else str(out[1] or "unsettled")
                return out
            finally:
                tap._current = outer
        return entry

    def _score(self, home: Any, away: Any) -> None:
        shaped = self._current
        if shaped is None or str(shaped.get("segment") or "full") not in ("full", "full_game"):
            return
        try:
            self.scores[str(shaped.get("event_id"))] = {"home": float(home), "away": float(away)}
        except (TypeError, ValueError):
            pass

    def _record(self, value: Any, **extra: Any) -> None:
        if self._current is None or value is None:
            return
        # A game line's number reads as a stat only for a total (the combined score); a spread or moneyline is graded
        # on a margin, which is not what a reader means by "the actual".
        if not self._current.get("player_name") and "total" not in str(self._current.get("market") or "").lower():
            return
        try:
            number = float(value)
        except (TypeError, ValueError):
            return
        self.values[_key_of(self._current)] = {"v": round(number, 2), **extra}

    def __enter__(self) -> "ValueTap":
        from syndicate.features.mlb import prop_outcomes
        from syndicate.features.shared import population_outcomes, population_outcomes_espn, population_outcomes_mlb
        from syndicate.features.shared import population_outcomes_nhl, population_outcomes_soccer

        self._wrap(population_outcomes.CompositeSettler, "__call__", self._entry)
        self._wrap(prop_outcomes.MlbPropGrader, "settle", self._entry)
        tap = self

        def via_status(original: Any) -> Any:
            def wrapped(*args: Any, **kwargs: Any) -> Any:
                tap._record(kwargs.get("current_value"))
                return original(*args, **kwargs)
            return wrapped

        def via_args(position: int) -> Callable[[Any], Any]:
            def make(original: Any) -> Any:
                def wrapped(*args: Any, **kwargs: Any) -> Any:
                    if len(args) > position:
                        tap._record(args[position])
                    return original(*args, **kwargs)
                return wrapped
            return make

        def via_runs(original: Any) -> Any:
            def wrapped(market: Any, side: Any, line: Any, away_runs: Any, home_runs: Any, *args: Any, **kwargs: Any) -> Any:
                if "total" in str(market or "").lower():
                    tap._record((away_runs or 0) + (home_runs or 0))
                tap._score(home_runs, away_runs)
                return original(market, side, line, away_runs, home_runs, *args, **kwargs)
            return wrapped

        def via_line_view(original: Any) -> Any:        # ESPN and NHL game lines hand it the final score
            def wrapped(*args: Any, **kwargs: Any) -> Any:
                tap._score(kwargs.get("home_score"), kwargs.get("away_score"))
                return original(*args, **kwargs)
            return wrapped

        def via_segment_actuals(original: Any) -> Any:  # soccer game lines
            def wrapped(*args: Any, **kwargs: Any) -> Any:
                out = original(*args, **kwargs)
                if isinstance(out, Mapping) and out.get("is_final"):
                    tap._score(out.get("home_score"), out.get("away_score"))
                return out
            return wrapped

        def via_goals(original: Any) -> Any:            # soccer scorer props read the box's final score
            def wrapped(box: Any, *args: Any, **kwargs: Any) -> Any:
                if isinstance(box, Mapping):
                    tap._score(box.get("score_home"), box.get("score_away"))
                return original(box, *args, **kwargs)
            return wrapped

        self._wrap(population_outcomes_espn, "resolve_bet_status", via_status)
        self._wrap(population_outcomes_nhl, "resolve_bet_status", via_status)
        self._wrap(prop_outcomes, "settle_prop", via_args(2))
        self._wrap(population_outcomes_soccer, "settle_over_under", via_args(0))
        self._wrap(population_outcomes_mlb, "settle_runs", via_runs)
        from syndicate.features.shared import game_line_bet, segment_actuals

        self._wrap(game_line_bet, "game_line_view", via_line_view)
        self._wrap(segment_actuals, "segment_actuals", via_segment_actuals)
        self._wrap(population_outcomes_soccer, "qualifying_goals", via_goals)

        def via_found_game(read: Any) -> Callable[[Any], Any]:
            # Every prop finds its game before it is graded, so every game with a graded prop has its final: MLB through
            # the schedule (`MlbPropGrader._final_game`), football / basketball through ESPN's scoreboard (`_locate`).
            def make(original: Any) -> Any:
                def wrapped(settler: Any, *args: Any, **kwargs: Any) -> Any:
                    out = original(settler, *args, **kwargs)
                    game = out[0] if isinstance(out, tuple) and out else None
                    if isinstance(game, Mapping):
                        read(game)
                    return out
                return wrapped
            return make

        def mlb_final(game: Mapping[str, Any]) -> None:
            if str(game.get("state") or "") == "Final":
                tap._score(game.get("home_score"), game.get("away_score"))

        def espn_final(event: Mapping[str, Any]) -> None:
            if event.get("completed"):
                tap._score((event.get("home") or {}).get("score"), (event.get("away") or {}).get("score"))

        self._wrap(prop_outcomes.MlbPropGrader, "_final_game", via_found_game(mlb_final))
        self._wrap(population_outcomes_espn.EspnPopulationSettler, "_locate", via_found_game(espn_final))
        return self

    def __exit__(self, *exc: Any) -> None:
        for owner, name, original in reversed(self._restore):
            setattr(owner, name, original)
        self._restore.clear()


def _with_value(graded: dict[str, Any], key: str, values: Mapping[str, Any]) -> dict[str, Any]:
    tapped = values.get(key)
    return {**graded, "v": tapped["v"]} if tapped else graded


def _graded_shape(g: Mapping[str, Any]) -> dict[str, Any]:
    """A graded population row in a pick's shape (its event id rides in `game`, 'sport|event')."""
    return {"player_name": g.get("player"), "market": g.get("market"), "side": g.get("side"), "line": g.get("line"),
            "segment": g.get("segment") or "full", "event_id": str(g.get("game") or "").split("|", 1)[-1]}


def graded_index(rows: list[dict[str, Any]], values: Mapping[str, Any] | None = None
                 ) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    """Graded population rows -> (props by prop key, lines by line key -- both FULL GAME --, and every segment by
    pick key for the Syndicate picks). `values` (a `ValueTap`'s) adds the number each was graded on as `v`."""
    values = values or {}
    props: dict[str, dict[str, Any]] = {}
    lines: dict[str, dict[str, Any]] = {}
    picks: dict[str, dict[str, Any]] = {}
    for g in rows:
        if g.get("y") is None:
            continue
        shape = _graded_shape(g)
        key = cs.pick_result_key(shape)
        entry = _with_value({"y": float(g["y"])}, key, values)
        picks.setdefault(key, entry)
        if str(shape["segment"]).lower() not in ("full", "full_game"):
            continue
        if g.get("player"):
            props.setdefault(cs.prop_result_key(g), entry)
        else:
            lines.setdefault(cs.line_result_key(shape), entry)
    return props, lines, picks


def actuals_index(rows: list[dict[str, Any]], values: Mapping[str, Any] | None = None) -> dict[tuple[str, str, str], float]:
    """(player key, market, event id) -> the stat the grader settled that player's market on, read from ANY line of it
    the grader graded (the `ValueTap` value, full game only).

    WHY (user 2026-10-19: "make sure reconciliation and tracking is happening for every category by every sport").
    The grader settles what the recorder captured, and a sheet can feature a line the recorder never held. Measured that
    day: on the NCAAF 10-15 / 10-16 sheets 33 featured props were still open days after their games. Re-pulling the
    grader settled none of them. In 31 of the 33, the same player was graded at OTHER lines, e.g. a receiving-yards
    over 35.5 on the sheet against 40.5 in the population. That player's stat for the game is known, so the sheet's line
    is graded from it (`reconcile(actuals=)`)."""
    from syndicate.features.shared.basketball_props_availability import player_key

    values = values or {}
    out: dict[tuple[str, str, str], float] = {}
    for g in rows:
        if not g.get("player") or g.get("y") is None:
            continue
        shape = _graded_shape(g)
        if str(shape["segment"]).lower() not in ("full", "full_game"):
            continue
        v = (values.get(cs.pick_result_key(shape)) or {}).get("v")
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            out.setdefault((player_key(g.get("player")), str(g.get("market") or "").strip().lower(), shape["event_id"]),
                           float(v))
    return out


def merge_results(prior: Mapping[str, Any], fresh: Mapping[str, Any]) -> dict[str, Any]:
    """A settled result never changes: keep every earlier one, take the fresh ones, and never lose a value an
    earlier run captured to a run that did not."""
    out = {k: dict(v) for k, v in (prior or {}).items()}
    for key, entry in fresh.items():
        out[key] = {**out.get(key, {}), **entry}
    return out


def reconcile(sheet: dict[str, Any], props: dict[str, Any], lines: dict[str, Any], *, now: datetime,
              reasons: Mapping[str, str] | None = None, scores: Mapping[str, Any] | None = None,
              picks: Mapping[str, Any] | None = None,
              actuals: Mapping[tuple[str, str, str], float] | None = None) -> dict[str, Any]:
    """The reconciled file for one sheet: the result of every prop, game line and Syndicate pick the grader settled,
    why each one it did NOT settle was left (`void` / `picks_void`: did not play, push, not final ...), and each
    game's final score (`scores`). `reasons` is keyed by `pick_result_key`. A prop line the grader never held is graded
    from the player's actual stat for that game when `actuals` (`actuals_index`) has it, marked `"by": "actual"`."""
    from syndicate.features.shared.basketball_props_availability import player_key

    p_out = {k: props[k] for k in (cs.prop_result_key(r) for r in sheet.get("rows") or []) if k in props}
    l_out = {k: lines[k] for k in (cs.line_result_key(g) for g in sheet.get("game_lines") or []) if k in lines}
    reasons, scores, picks = reasons or {}, scores or {}, picks or {}
    void = {}
    for r in sheet.get("rows") or []:
        k = cs.prop_result_key(r)
        line = r.get("line")
        if k in p_out or not actuals or not isinstance(line, (int, float)) or isinstance(line, bool):
            continue
        v = actuals.get((player_key(r.get("player")), str(r.get("market") or "").strip().lower(), str(r.get("event_id") or "")))
        if v is None:
            continue
        hit = cs.side_hit(v, float(line), str(r.get("side") or "").strip().lower())
        if hit is not None:
            p_out[k] = {"y": float(hit), "v": v, "by": "actual"}
        elif v == float(line):
            void[k] = "push"
    for r in sheet.get("rows") or []:
        k, rk = cs.prop_result_key(r), cs.pick_result_key(r)
        if k not in p_out and k not in void and rk in reasons:
            void[k] = reasons[rk]
    pick_keys = [cs.pick_result_key(pk) for pk in sheet.get("picks") or []]
    k_out = {k: picks[k] for k in pick_keys if k in picks}
    k_void = {k: reasons[k] for k in pick_keys if k not in k_out and k in reasons}
    events = ({str(g.get("event_id")) for g in sheet.get("games") or []} | {str(r.get("event_id")) for r in sheet.get("rows") or []}
              | {str(pk.get("event_id")) for pk in sheet.get("picks") or []})
    return {"sport": sheet.get("sport"), "date": sheet.get("date"), "reconciled_at": now.isoformat(timespec="seconds"),
            "source": SOURCE, "props": p_out, "lines": l_out, "void": void, "picks": k_out, "picks_void": k_void,
            "scores": {e: scores[e] for e in sorted(events) if e in scores},
            "counts": {"props": len({cs.prop_result_key(r) for r in sheet.get("rows") or []}), "props_graded": len(p_out),
                       "props_valued": sum(1 for v in p_out.values() if "v" in v),
                       "props_from_actual": sum(1 for v in p_out.values() if v.get("by") == "actual"),
                       "lines": len({cs.line_result_key(g) for g in sheet.get("game_lines") or []}),
                       "lines_graded": len(l_out), "picks": len(set(pick_keys)), "picks_graded": len(k_out)}}


# SHEET PROPS THE RECORDER NEVER HELD, GRADED BY THE PRODUCTION SETTLER ITSELF (lane `cheat-sheets`, 2026-10-21).
# The grader settles the recorder's captured population; `actuals_index` then grades a sheet line the population never
# held from the same player's value at another line. A player the population held at NO line stayed open forever.
# Measured on the NCAAF 10-20 sheet: 47 of 147 props neither graded nor voided, 35 of them from Missouri State @
# Delaware, whose box score carries every one of those players. So each still-open prop goes through
# `population_outcomes.build_extra_settler` -- the composite every pull uses, under its own rules (team-pair game join,
# finality, ABSENT IS NOT ZERO) -- reading ESPN's summary box. Its value is the `ValueTap` reading, like any graded row.
BOX_SETTLED_SPORTS = frozenset({"nfl", "ncaaf", "wnba", "nba", "ncaab"})
# Reasons that will not change on a later run: the prop is void, with that reason. Anything else (not final, a fetch
# that failed, a game not found) leaves it open for the next run.
_FINAL_REASONS = frozenset({"dnp_void", "player_absent_unverifiable", "player_ambiguous", "prop_market_unmapped",
                            "prop_segment_unsupported", "non_player_prop_unsupported", "unsettleable_side_or_line"})


def settle_open_props(sheet: Mapping[str, Any], rec: dict[str, Any], settler: Callable[..., Any],
                      values: Mapping[str, Any]) -> int:
    """Grade, in place, the sheet props `reconcile` left open, through `settler(shaped, view)`; returns how many it
    graded. `values` is the live `ValueTap.values` (read after each call). Counts are rewritten to include them."""
    if str(sheet.get("sport") or "") not in BOX_SETTLED_SPORTS:
        return 0
    games = {str(g.get("event_id") or ""): g for g in sheet.get("games") or [] if isinstance(g, Mapping)}
    graded = 0
    for r in sheet.get("rows") or []:
        k = cs.prop_result_key(r)
        line = r.get("line")
        if (k in rec["props"] or k in rec["void"] or not r.get("player") or not isinstance(line, (int, float))
                or isinstance(line, bool)):
            continue
        game = games.get(str(r.get("event_id") or "")) or {}
        shaped = {"sport": sheet.get("sport"), "market": r.get("market"), "segment": "full",
                  "player_name": r.get("player"), "side": str(r.get("side") or "").strip().lower(), "line": float(line),
                  "event_id": str(r.get("event_id") or ""),
                  "commence_time": r.get("commence_time") or game.get("commence_time"),
                  "home_team": game.get("home_team"), "away_team": game.get("away_team")}
        out = settler(shaped, {})
        if not out:
            continue
        result, reason = out
        if result in ("win", "loss"):
            entry: dict[str, Any] = {"y": 1.0 if result == "win" else 0.0, "by": "box"}
            tapped = values.get(cs.pick_result_key(shaped))
            if tapped:
                entry["v"] = tapped["v"]
            rec["props"][k] = entry
            graded += 1
        elif result == "push":
            rec["void"][k] = "push"
        elif reason in _FINAL_REASONS:
            rec["void"][k] = reason
    counts = rec.setdefault("counts", {})
    counts["props_graded"] = len(rec["props"])
    counts["props_valued"] = sum(1 for v in rec["props"].values() if "v" in v)
    counts["props_from_box"] = sum(1 for v in rec["props"].values() if v.get("by") == "box")
    return graded


def sgp_leg_actuals(root: Path, day: str, sheet: Mapping[str, Any]) -> dict[str, float]:
    """Each parlay leg's actual (the sheet's parlays and the day's paper-ledger ones) from the sport's own game log --
    NHL box scores, NFL usage lines: the high-hit-rate pool draws legs from players the sheet never graded."""
    sport = str(sheet.get("sport") or "")
    try:
        if sport in ("wnba", "nba"):
            from syndicate.features.shared import basketball_sgp_pool

            def actuals(root_, day_, tickets_):
                return basketball_sgp_pool.leg_actuals(root_, day_, tickets_, sport=sport)
        elif sport == "mlb":
            from syndicate.features.shared.mlb_sgp_pool import leg_actuals as actuals
        elif sport == "nhl":
            from syndicate.features.nhl.sgp_pool import leg_actuals as actuals
        else:
            from syndicate.features.nfl.sgp_pool import leg_actuals as actuals

        tickets = list(sheet.get("sgp") or [])
        ledger = root / "cheatsheets" / sport / "sgp_ledger.jsonl"
        if ledger.is_file():
            for line in ledger.read_text(encoding="utf-8").splitlines():
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if rec.get("date") == day:
                    tickets.append(rec)
        # Cross-game parlays (2026-10-20): this sport's legs of the day's tickets, read off the same box scores.
        cross = _cross_doc(root, day)
        lists = list((cross.get("kinds") or {}).values()) + list(((cross.get("by_sport") or {}).get(sport) or {}).values())
        for kind_tickets in lists:
            for t in kind_tickets or []:
                mine = [leg for leg in t.get("legs") or [] if leg.get("sport") == sport and leg.get("kind") == "prop"]
                if mine:
                    tickets.append({"legs": mine})
        return actuals(root, day, tickets)
    except Exception as exc:  # noqa: BLE001 -- the props still reconcile; those legs stay pending
        print(f"RECONCILE {sport} date={day} leg actuals failed: {type(exc).__name__}: {exc}", flush=True)
        return {}


CROSS_DIR = "cheatsheets_cross"


def _cross_doc(root: Path, day: str) -> dict[str, Any]:
    try:
        doc = json.loads((root / CROSS_DIR / f"{day}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def grade_cross(root: Path, sheets_dir: Path, today: str, *, days: int = 7) -> int:
    """Grade the cross-game parlays of the last `days` days from every sport's reconciled file for the day
    (`cross_game_parlays.grade`) into `cheatsheets_cross/<day>.graded.json`. Returns the days written."""
    from syndicate.features.shared import cross_game_parlays as xg

    written = 0
    for k in range(days, -1, -1):
        day = (datetime.fromisoformat(today) - timedelta(days=k)).date().isoformat()
        doc = _cross_doc(root, day)
        if not doc.get("kinds") and not doc.get("by_sport"):
            continue
        recs = {}
        for sport in doc.get("sports") or []:
            try:
                recs[sport] = json.loads((sheets_dir / sport / f"{day}.reconciled.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
        if not recs:
            continue
        graded = {t["xg_id"]: dict(xg.grade(t, recs), kind=kind, scope="multi", price=t.get("price"), p_joint=t.get("p_joint"))
                  for kind, tickets in (doc.get("kinds") or {}).items() for t in tickets or [] if t.get("xg_id")}
        for sport, kinds in (doc.get("by_sport") or {}).items():       # one sport across its games
            for kind, tickets in (kinds or {}).items():
                for t in tickets or []:
                    if t.get("xg_id"):
                        graded[t["xg_id"]] = dict(xg.grade(t, recs), kind=kind, scope=sport, price=t.get("price"),
                                                  p_joint=t.get("p_joint"))
        write_atomic(root / CROSS_DIR / f"{day}.graded.json",
                     {"date": day, "graded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "tickets": graded})
        counts = collections.Counter(g["status"] for g in graded.values())
        print(f"CROSS date={day} {dict(counts)}", flush=True)
        written += 1
    return written


def cross_graded(root: Path) -> list[dict[str, Any]]:
    out = []
    for path in sorted((root / CROSS_DIR).glob("*.graded.json")):
        try:
            out.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return out


def write_record(sheets_dir: Path, *, now: datetime) -> dict[str, Any]:
    """`<cheatsheets>/record.json` -- the running season record (user 2026-10-15: "add a running season record page")
    -- rebuilt from EVERY reconciled day on disk, so a late final or a re-graded day always flows through."""
    from syndicate.features.shared import cheat_sheet_record as csr

    days = []
    for rec_path in sorted(sheets_dir.glob("*/*.reconciled.json")):
        day = rec_path.name[: -len(".reconciled.json")]
        try:
            reconciled = json.loads(rec_path.read_text(encoding="utf-8"))
            sheet = json.loads(rec_path.with_name(f"{day}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        days.append(csr.day_record(sheet, reconciled, cs.load_posted(sheets_dir, rec_path.parent.name, day)))
    record = csr.season_record(days, generated_at=now.isoformat(timespec="seconds"), cross=cross_graded(sheets_dir.parent))
    write_atomic(sheets_dir / "record.json", record)
    official = record["official"]["totals"].get(csr.ALL) or {}
    print(f"RECORD days={len(days)} official featured {official.get('w', 0)}-{official.get('l', 0)} "
          f"{official.get('units', 0):+.2f}u beta days={record['beta']['days']}", flush=True)
    return record


def write_atomic(path: Path, doc: dict[str, Any]) -> None:
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False)
    os.replace(tmp, path)


def write_postmortem(root: Path, path: Path, sheet: dict[str, Any], rec: dict[str, Any], day: str) -> dict[str, Any] | None:
    """The ENGINE LEDGER for one reconciled sheet (lane result-cards, user 2026-10-16: "what did we get wrong - this is
    something that can help optimize our sim engine"): `<sport>/<date>.postmortem.jsonl`, one record per graded
    featured bet -- verdict (close x result), the sim's error where it was the reason, opportunity vs efficiency from
    box-score usage (NHL / MLB / NFL). Rewritten whole each run; a failure here never fails the reconcile."""
    try:
        from syndicate.features.shared import box_usage
        from syndicate.features.shared import play_card_results as pcr

        gpc = _load("grade_play_cards")
        sport = str(sheet.get("sport"))
        records = pcr.sheet_postmortem(sheet, rec)                   # first pass: which bets are graded
        cards = [{"card_id": r["card_id"], "event_id": r.get("event_id"), "market": r.get("market"), "player": r.get("player"),
                  "line": r.get("line"), "side": r.get("side"), "price": r.get("price"), "p_market": r.get("p_market"),
                  "commence_time": next((g.get("commence_time") for g in sheet.get("games") or []
                                         if g.get("event_id") == r.get("event_id")), None)}
                 for r in records if r.get("kind") == "prop"]
        closes = gpc.closing_fairs(root, sport, day, cards)
        cache = root / "cheatsheets" / ".usage_cache"
        records = pcr.sheet_postmortem(sheet, rec, closes=closes,
                                       usage=lambda card, item: box_usage.usage_for(card, item, cache=cache, data_root=root))
        out = path.with_name(f"{day}.postmortem.jsonl")
        tmp = out.with_name(out.name + ".tmp")
        tmp.write_text("".join(json.dumps(r, default=str) + "\n" for r in records), encoding="utf-8")
        tmp.replace(out)
        summary = pcr.engine_summary(records)
        print(f"POSTMORTEM {sport} date={day} {json.dumps(summary)} closes={len(closes)}", flush=True)
        return summary
    except Exception as exc:  # noqa: BLE001 -- the engine ledger is an addition, never a failed reconcile
        print(f"POSTMORTEM {sheet.get('sport')} date={day} failed: {type(exc).__name__}: {exc}", flush=True)
        return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-root", default=os.environ.get("SYNDICATE_DATA_ROOT"))
    ap.add_argument("--date", action="append", help="a day to reconcile (repeatable); default today and the 2 before")
    ap.add_argument("--sports", default=None, help="limit to these sports (default: every sport with a sheet)")
    args = ap.parse_args(argv)
    if not args.data_root:
        print("REFUSING: no --data-root", flush=True)
        return 2
    root = Path(os.path.expanduser(args.data_root))
    sheets_dir = root / "cheatsheets"
    today = central_today()
    # One marker a run, so the daily review reads only the LAST run's lines (scripts/review_cheat_sheets.py).
    print(f"RECONCILE_RUN start {datetime.now(timezone.utc).isoformat(timespec='seconds')}", flush=True)
    days = args.date or [(datetime.fromisoformat(today) - timedelta(days=k)).date().isoformat() for k in range(DAYS_BACK, -1, -1)]
    if not args.date:
        late = catchup_days(sheets_dir, today)
        if late:
            print(f"RECONCILE catch-up {late}: featured bets still open past the {DAYS_BACK}-day window", flush=True)
        days = late + days
    wanted = {s.strip() for s in args.sports.split(",")} if args.sports else None
    cache = sheets_dir / ".reconcile_cache"
    cache.mkdir(parents=True, exist_ok=True)
    srb = None
    box_settler = None
    for day in days:
        if day > today:
            continue
        sheets = []
        for path in sorted(sheets_dir.glob(f"*/{day}.json")):
            sport = path.parent.name
            if wanted and sport not in wanted:
                continue
            try:
                doc = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            # A row that went out on an exported graphic is graded even if no build after the post kept it.
            doc = cs.with_posted(doc, cs.load_posted(sheets_dir, sport, day))
            # Picks count on their own: an NBA preseason sheet carried price plays and nothing else (10-15 / 10-16) and
            # was never reconciled, so 15 published picks never got a result.
            if doc.get("rows") or doc.get("game_lines") or doc.get("picks"):
                sheets.append((path, doc))
        if not sheets:
            print(f"RECONCILE date={day} no sheets", flush=True)
            continue
        sports = sorted({doc["sport"] for _, doc in sheets})
        srb = srb or _load("score_ranking_backtest")
        with tempfile.TemporaryDirectory(prefix="reconcile_") as work:
            out = Path(work) / f"graded_{day}.jsonl"
            with ValueTap() as tap:
                code = srb.main(["pull", "--start", day, "--end", day, "--sports", ",".join(sports), "--source", "recorder",
                                 "--cache", str(cache), "--out", str(out)])
            if tap.missing:
                print(f"RECONCILE date={day} value hooks MISSING {tap.missing} -- those sports carry results without values",
                      flush=True)
            if code not in (0, None) or not out.is_file():
                # A failed pull must never overwrite results already on disk with an empty file.
                print(f"RECONCILE date={day} grader pull failed (exit {code}) -- nothing written", flush=True)
                continue
            graded = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
        props, lines, pick_results = graded_index(graded, tap.values)
        actuals = actuals_index(graded, tap.values)
        now = datetime.now(timezone.utc)
        for path, doc in sheets:
            target = path.with_name(f"{day}.reconciled.json")
            try:
                prior = json.loads(target.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                prior = {}
            # A settled result never changes, so an earlier run's results stay when a re-run grades fewer.
            # Earlier runs' reasons: `void` is keyed by prop key (full game), `picks_void` already by pick key.
            earlier = {**{f"p:{k}|full": v for k, v in (prior.get("void") or {}).items()}, **(prior.get("picks_void") or {})}
            rec = reconcile(doc, merge_results(prior.get("props") or {}, props), merge_results(prior.get("lines") or {}, lines),
                            now=now, reasons={**earlier, **tap.reasons}, scores={**(prior.get("scores") or {}), **tap.scores},
                            picks=merge_results(prior.get("picks") or {}, pick_results), actuals=actuals)
            if doc.get("sport") in BOX_SETTLED_SPORTS:
                try:
                    if box_settler is None:
                        from syndicate.features.shared.population_outcomes import build_extra_settler

                        box_settler = build_extra_settler(cache_dir=cache / "settlers")
                    with ValueTap() as box_tap:
                        settle_open_props(doc, rec, box_settler, box_tap.values)
                except Exception as exc:  # noqa: BLE001 -- the population's results still stand
                    print(f"RECONCILE {doc['sport']} date={day} box pass failed: {type(exc).__name__}: {exc}", flush=True)
            c = rec["counts"]
            if not prior and not (c["props_graded"] or c["lines_graded"] or c["picks_graded"]):
                # Nothing final yet: no file, so the page offers no toggle onto a sheet of dashes.
                print(f"RECONCILE {doc['sport']} date={day} nothing settled yet -- no file", flush=True)
                continue
            if doc.get("sport") in ("nhl", "nfl", "wnba", "nba", "mlb"):
                rec["leg_actuals"] = sgp_leg_actuals(root, day, doc)
            write_atomic(target, rec)
            write_postmortem(root, path, doc, rec, day)
            print(f"RECONCILE {doc['sport']} date={day} props {c['props_graded']}/{c['props']} (values {c['props_valued']}, "
                  f"from the actual stat {c['props_from_actual']}, from the box {c.get('props_from_box', 0)}, "
                  f"explained voids {len(rec['void'])}, finals {len(rec['scores'])}) "
                  f"lines {c['lines_graded']}/{c['lines']} graded_population={len(graded)}", flush=True)
    refresh_leg_actuals(root, sheets_dir, today)
    grade_cross(root, sheets_dir, today)
    write_record(sheets_dir, now=datetime.now(timezone.utc))
    grade_sgp_ledger(root)
    return 0


CATCHUP_DAYS = 7


def open_featured(sheet: Mapping[str, Any], rec: Mapping[str, Any] | None) -> int:
    """How many of the bets the sheet FEATURED (the season record's sections, its picks and game-line value) have
    neither a result nor a stated reason (void / push / not in the box score) in its reconciled file."""
    from syndicate.features.shared import cheat_sheet_record as csr

    rec = rec or {}
    rows, lines, picks = sheet.get("rows") or [], sheet.get("game_lines") or [], sheet.get("picks") or []
    done_props = set(rec.get("props") or {}) | set(rec.get("void") or {})
    done_picks = set(rec.get("picks") or {}) | set(rec.get("picks_void") or {})
    secs = cs.sections(rows)
    keys = {cs.prop_result_key(rows[i]) for k, _ in csr.FEATURED for i in secs.get(k) or []} - done_props
    line_keys = {cs.line_result_key(lines[i]) for i in (cs.game_line_sections(lines).get("value") if lines else [])}
    line_keys -= set(rec.get("lines") or {})
    pick_keys = {cs.pick_result_key(p) for p in picks} - done_picks
    return len(keys) + len(line_keys) + len(pick_keys)


def catchup_days(sheets_dir: Path, today: str, *, days: int = CATCHUP_DAYS) -> list[str]:
    """Days past the regular window (`DAYS_BACK`) and within `days` whose sheets still hold an open FEATURED bet. A
    result that lands late -- an NFL usage file, an NCAAF box score -- used to be dropped for good once its day left the
    2-day window (user 2026-10-19: "make sure reconciliation and tracking is happening for every category by every
    sport"). Oldest first, like the regular days."""
    out = []
    for k in range(days, DAYS_BACK, -1):
        day = (datetime.fromisoformat(today) - timedelta(days=k)).date().isoformat()
        for path in sorted(sheets_dir.glob(f"*/{day}.json")):
            try:
                sheet = json.loads(path.read_text(encoding="utf-8"))
                rec_path = path.with_name(f"{day}.reconciled.json")
                rec = json.loads(rec_path.read_text(encoding="utf-8")) if rec_path.exists() else None
            except (OSError, ValueError):
                continue
            if open_featured(sheet, rec):
                out.append(day)
                break
    return out


SGP_ACTUALS_DAYS = 7


def refresh_leg_actuals(root: Path, sheets_dir: Path, today: str, *, days: int = SGP_ACTUALS_DAYS) -> int:
    """Parlay legs graded from the game logs for the last `days` days -- not only the DAYS_BACK the grader re-pulls.
    A game log can land after a day leaves that window (2026-10-19: NFL's usage file still held only Thursday's week-6
    game the morning after Sunday, leaving 15 of 22 NFL parlays pending, and the 10-18 sheet would leave the window
    after the 10-20 night run). Re-reads the logs only -- no grader pull -- and rewrites a reconciled file only when
    its actuals change. Returns the number of files updated."""
    updated = 0
    for k in range(days, -1, -1):
        day = (datetime.fromisoformat(today) - timedelta(days=k)).date().isoformat()
        for sport in ("nhl", "nfl", "wnba", "nba", "mlb"):
            path = sheets_dir / sport / f"{day}.json"
            target = path.with_name(f"{day}.reconciled.json")
            if not (path.is_file() and target.is_file()):
                continue
            try:
                doc = json.loads(path.read_text(encoding="utf-8"))
                rec = json.loads(target.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not doc.get("sgp"):
                continue
            acts = sgp_leg_actuals(root, day, doc)
            merged = {**(rec.get("leg_actuals") or {}), **acts}
            if merged != (rec.get("leg_actuals") or {}):
                rec["leg_actuals"] = merged
                write_atomic(target, rec)
                updated += 1
                print(f"RECONCILE {sport} date={day} leg actuals refreshed: {len(merged)}", flush=True)
    return updated


def grade_sgp_ledger(root: Path) -> None:
    """Grade each sport's same-game-parlay paper ledger from the reconciled sheets just written (lanes
    `nfl-sgp-builder`, `nhl-sgp-builder`, `basketball-sgp-builder`). Never fails the reconcile.

    EVERY SGP SPORT, from the one list the builder and the record share (2026-10-21): this looped over nfl/nhl only, so
    the NBA, WNBA and MLB ledgers -- written daily -- were never graded."""
    from syndicate.features.shared.cheat_sheet_record import SGP_SPORTS

    for sport in sorted(SGP_SPORTS):
        if not (root / "cheatsheets" / sport / "sgp_ledger.jsonl").is_file():
            continue
        try:
            import importlib.util

            spec = importlib.util.spec_from_file_location("grade_sgp_paper", Path(__file__).resolve().parent / "grade_sgp_paper.py")
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            mod.main(["--data-root", str(root), "--sport", sport])
        except Exception as exc:  # noqa: BLE001
            print(f"SGP_PAPER {sport} failed: {type(exc).__name__}: {exc}", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
