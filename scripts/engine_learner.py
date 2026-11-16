"""Phase 1B M2 shadow learner, the runner (lane ``engine-learner``). READ-ONLY: it writes nothing under the data root.

    python scripts/engine_learner.py run --opinions-dir <dir>[,<dir>...] --dates 2026-11-09..2026-11-14 \
        --test-from 2026-11-13 [--truth outcome|close] [--json out.json] [--root <data root>] [--chips-dir <dir>]

Reads ``opinions_<date>.jsonl`` (the experts runner's ``--opinions`` output, ``scripts/engine_experts.py``) from every
``--opinions-dir`` for each slate, joins each opinion to its truth, fits ``engine_learner`` on the slates before
``--test-from`` and prints:

* COVERAGE   per sport x family x phase: opinions, graded examples, and every refusal by name -- the denominator for
             everything below.
* PRIOR_LL   the prior's own log loss per group, in and out of sample. A side or frame read backwards shows here as
             a log loss far above ln 2 (0.693), so it is the truth join's self-check.
* WEIGHTS    per expert x leaf cell: n, the fitted weight, its game-clustered SE, and whether it is applied.
* HELD_OUT   per sport x family x phase: log loss of p_decision minus the prior's on the test slates, 95% CI by game
             bootstrap. ``OFF`` must read exactly 0 everywhere (the off switch is the prior); ``ON`` is the learner
             with the lower-bound rule; ``RAW`` applies every fitted weight (a reading, not the learner); ``ON_BY_AGE``
             splits ON by the prior's age; with ``--truth close``, ``ON_BY_BASIS`` splits it by the close's basis.
* REACH      off != on: how many held-out examples ON moves away from the prior.

Truth (``--truth``; ``docs/ai_context/engine_learner.md``):

* ``outcome`` (the slow truth, pregame and live): did the opinion's side win.
  - LIVE BASKETBALL (nba / ncaab / wncaab; slice 1): ``nba_source/data/processed/linescores_<date>.json`` (completed
    games only, by ESPN event id, which the live evidence log carries) and the college slate scoreboards
    (``<league>_source/data/scoreboard/scoreboard_<date>.json``, FINAL only). Orientation: the evidence log's home
    team against the score source's.
  - EVERY OTHER GAME LINE (slice 2: pregame in every sport; live NHL / NFL / NCAAF / WNBA): the board's final-score
    chips (``/api/board/game-chips`` on the fleet's web, or ``--chips-dir``), matched to the event's teams
    (``layer2_live_scorecard.match_chip``) within 6 h of its start; the event's teams and start come from the
    DecisionRecords and, for a live event they never listed, the live gameline ledger. Segments by
    ``segment_actuals.segment_score_pair`` (NBA, football) or the college rule (h1 = period 1, h2 = period 2 plus
    overtime); any other sport's segment is refused.
  - Frames: a LIVE line is in the live join's frame (spreads HOME = home - away > line); a PREGAME line is in the
    book's own (``layer2_live_scorecard.grade``: the side's margin plus its line > 0). Totals OVER = total > line;
    h2h by the final; equal = push, dropped and counted. A spread or moneyline whose orientation cannot be told is
    refused, never guessed.
  - Player props are refused (``prop_outcome_owed``; the NBA prop grader is lane ``nba-live-prop-grade``'s).
* ``close`` (the fast PREGAME truth, plan D11): the probability of the opinion's side at the close -- Pinnacle's (power
  devig) where it quotes that line, else the median Shin consensus of >= 2 books, the softer standard
  (``decision_policy_paper.collect_closes`` / ``close_probabilities``). Pregame only; props included.

The window: a game that starts at or after ``--max-commence`` (default 06:00Z the day after the last slate, midnight
Central) is never graded, and no chip or quote file dated after the last slate is read.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import date as _date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from syndicate.features.shared import engine_learner as el  # noqa: E402

SPORTS = ("nba", "ncaab", "wncaab")          # live basketball: slice 1's score sources
COLLEGE_HALVES = ("ncaab", "wncaab")
GAME_FAMILIES = ("totals", "spreads", "h2h")
LEDGER_SPORTS = ("nhl", "nfl", "ncaaf", "wnba")  # live events the records may not list
CHIP_START_TOLERANCE_S = 6 * 3600

# ESPN's NBA abbreviations that differ from the slate's.
NBA_CODE_ALIASES = {"NO": "NOP", "NY": "NYK", "GS": "GSW", "SA": "SAS", "UTAH": "UTA", "WSH": "WAS", "UTA": "UTA"}

# BasketballTruth's own refusals (the dispatcher routes around the first three).
R_PREGAME = "pregame_not_in_slice1"
R_PROPS = "props_not_in_slice1"
R_SPORT = "sport_not_in_slice1"
R_NO_FINAL = "no_final_score"
R_SEGMENT = "segment_unscorable"
R_ORIENT = "orientation_unresolved"
R_SIDE = "side_unsupported"
# Slice 2.
R_PROP_OUTCOME = "prop_outcome_owed"
R_NO_EVENT = "event_identity_unknown"
R_AFTER_WINDOW = "commence_after_window"
R_NOT_FINAL = "not_final"
R_PREGAME_ONLY = "close_truth_is_pregame_only"
R_NO_CLOSE = "no_close"


def _module(name: str, rel: str):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, REPO / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _college():
    return _module("college_segment_grade", "scripts/college_segment_grade.py")


def _scorecard():
    return _module("layer2_live_scorecard", "scripts/layer2_live_scorecard.py")


def _dpp():
    from syndicate.features.shared import decision_policy_paper as dpp

    return dpp


def span(text: str) -> list[str]:
    if ".." not in text:
        return [d for d in text.split(",") if d]
    lo, hi = (_date.fromisoformat(x) for x in text.split(".."))
    return [(lo + timedelta(days=i)).isoformat() for i in range((hi - lo).days + 1)]


def default_max_commence(last_date: str) -> float:
    """06:00Z the day after the last slate: midnight Central, so every graded game's Central date is in the window."""
    d = _date.fromisoformat(last_date) + timedelta(days=1)
    return datetime(d.year, d.month, d.day, 6, tzinfo=timezone.utc).timestamp()


# ----------------------------------------------------------------------------- the outcome of one line


def outcome(family: str, side: str, line: float | None, home: int, away: int) -> float | None | str:
    """A LIVE line (the live join's frame): 1.0 / 0.0 for the side winning / losing, 0.5 for a push, or a refusal."""
    if family == "totals":
        if line is None:
            return R_SIDE
        v = home + away
        if side == "over":
            return 0.5 if v == line else float(v > line)
        if side == "under":
            return 0.5 if v == line else float(v < line)
        return R_SIDE
    if family == "spreads":
        if line is None or side != "home":
            return R_SIDE
        v = home - away
        return 0.5 if v == line else float(v > line)
    if family == "h2h":
        if home == away:
            return 0.5
        if side == "home":
            return float(home > away)
        if side == "away":
            return float(away > home)
        return R_SIDE
    return R_SIDE


def outcome_book(family: str, side: str, line: float | None, home: int, away: int) -> float | None | str:
    """A PREGAME line, in the book's own frame (``layer2_live_scorecard.grade``): a spread side wins when its margin
    plus its line is above 0. Totals and h2h as ``outcome``."""
    if family == "spreads":
        if line is None:
            return R_SIDE
        if side == "home":
            v = home - away + line
        elif side == "away":
            v = away - home + line
        else:
            return R_SIDE
        return 0.5 if v == 0 else float(v > 0)
    return outcome(family, side, line, home, away)


def _graded(y: float | None | str) -> tuple[float | None, str | None]:
    if isinstance(y, str):
        return None, y
    if y == 0.5:
        return None, el.PUSH
    return y, None


def _nba_code(code: Any) -> str:
    c = str(code or "").strip().upper()
    return NBA_CODE_ALIASES.get(c, c)


def nba_orientation(evidence: Mapping[str, Any], game: Mapping[str, Any]) -> str | None:
    eh, ea = _nba_code(evidence.get("home")), _nba_code(evidence.get("away"))
    sh, sa = _nba_code(game.get("home")), _nba_code(game.get("away"))
    if eh and ea and (eh, ea) == (sh, sa):
        return "same"
    if eh and ea and (eh, ea) == (sa, sh):
        return "swapped"
    return None


class BasketballTruth:
    """Outcome of a LIVE basketball game line from the data root's final scores (slice 1; module docstring)."""

    def __init__(self, dates: Iterable[str], *, root: Path | None = None, evidence_teams=None, college=None):
        from syndicate.features.shared.refresh_state_store import data_root

        self.root = Path(root) if root else data_root()
        days = sorted(set(dates))
        if days:  # a late game's score lands on the next day's files too
            days.append((_date.fromisoformat(days[-1]) + timedelta(days=1)).isoformat())
        self.csg = college or _college()
        self.nba: dict[str, Mapping[str, Any]] = {}
        self.college: dict[tuple[str, str], Mapping[str, Any]] = {}
        for d in days:
            path = self.root / "nba_source" / "data" / "processed" / f"linescores_{d}.json"
            if path.exists():
                payload = json.loads(path.read_text(encoding="utf-8-sig"))
                for eid, game in (payload.get("games") or {}).items():
                    self.nba[str(eid)] = game
            for league in ("ncaab", "wncaab"):
                path = self.root / f"{league}_source" / "data" / "scoreboard" / f"scoreboard_{d}.json"
                if path.exists():
                    board = json.loads(path.read_text(encoding="utf-8-sig"))
                    for eid, game in self.csg.final_games([board]).items():
                        self.college[(league, eid)] = game
        self.teams = evidence_teams if evidence_teams is not None else self._evidence_teams(dates)

    def _evidence_teams(self, dates: Iterable[str]) -> dict[tuple[str, str], dict[str, Any]]:
        from syndicate.features.shared import live_evidence_log as lel

        out: dict[tuple[str, str], dict[str, Any]] = {}
        for sport in SPORTS:
            for d in dates:
                for row in lel.iter_rows(sport, d, root=self.root):
                    eid = str(row.get("event_id") or "")
                    if eid and (sport, eid) not in out:
                        out[(sport, eid)] = {k: row.get(k) for k in ("home_name", "away_name", "home", "away")}
        return out

    def scores(self, sport: str, event_id: str, segment: str) -> tuple[tuple[int, int] | None, str | None, str | None]:
        """((home, away) in the EVIDENCE log's orientation, orientation, refusal)."""
        from syndicate.features.shared.segment_actuals import segment_score_pair

        teams = self.teams.get((sport, event_id)) or {}
        if sport == "nba":
            game = self.nba.get(event_id)
            if game is None:
                return None, None, R_NO_FINAL
            hp, ap = game.get("home_periods"), game.get("away_periods")
            if segment == "full":
                ok = isinstance(hp, list) and isinstance(ap, list) and len(hp) >= 4 and len(ap) >= 4 \
                    and all(isinstance(v, int) for v in hp + ap)
                pair = (sum(hp), sum(ap)) if ok else None
            else:
                pair = segment_score_pair("nba", segment, home_linescores=hp, away_linescores=ap)
            orient = nba_orientation(teams, game)
        else:
            game = self.college.get((sport, event_id))
            if game is None:
                return None, None, R_NO_FINAL
            live = game.get("live_state") or {}
            hl, al = live.get("home_linescores"), live.get("away_linescores")
            if segment == "full":
                ok = isinstance(hl, list) and isinstance(al, list) and len(hl) >= 2 and len(al) >= 2 \
                    and all(isinstance(v, int) and not isinstance(v, bool) for v in hl + al)
                pair = (sum(hl), sum(al)) if ok else None
            else:
                h, a = self.csg.segment_points(hl, segment), self.csg.segment_points(al, segment)
                pair = (h, a) if h is not None and a is not None else None
            orient = self.csg.orientation(teams, game)
        if pair is None:
            return None, orient, R_SEGMENT
        if orient == "swapped":
            pair = (pair[1], pair[0])
        return pair, orient, None

    def __call__(self, op: Mapping[str, Any]) -> tuple[float | None, str | None]:
        sport = str(op.get("sport") or "")
        family = el.family_of(str(op.get("market") or ""))
        if op.get("phase") != "live":
            return None, R_PREGAME
        if family not in GAME_FAMILIES:
            return None, R_PROPS
        if sport not in SPORTS:
            return None, R_SPORT
        pair, orient, refusal = self.scores(sport, el.game_id(op), str(op.get("segment") or "full"))
        if pair is None:
            return None, refusal
        if family != "totals" and orient is None:
            return None, R_ORIENT
        return _graded(outcome(family, str(op.get("side") or ""), op.get("line"), *pair))


# ----------------------------------------------------------------------------- slice 2: events, chips, closes


def load_events(dates: Iterable[str], *, root: Path | None = None,
                ledger_sports: Sequence[str] = LEDGER_SPORTS) -> dict[str, dict[str, Any]]:
    """event id -> {sport, home, away, commence, source}. The DecisionRecords' identity first (each slate's kept
    pregame lines, else its latest build); then the live gameline ledger for a live event the records never listed,
    whose ``commence`` is its first ``recorded_at`` (the game was under way by then: an upper bound on the start)."""
    from syndicate.features.shared import decision_record as dr
    from syndicate.features.shared import live_gameline_ledger as lgl

    out: dict[str, dict[str, Any]] = {}
    for d in dates:
        kept = list(dr.read_pregame_lines(d, root=root))
        if kept:
            snaps = [s for row in kept for s in (row.get("first"), row.get("last")) if isinstance(s, Mapping)]
        else:
            doc = dr.read_records(d, root=root)
            snaps = [s for s in (doc.get("records") or []) if isinstance(s, Mapping)] if isinstance(doc, dict) else []
        for snap in snaps:
            idn = dr.expand_record(snap).identity
            ev = str(idn.event_id or "")
            if ev and idn.home_team and idn.away_team and ev not in out:
                out[ev] = {"sport": str(idn.sport or "").lower(), "home": idn.home_team, "away": idn.away_team,
                           "commence": idn.commence_time, "source": "decision_record"}
    ledger_first: dict[str, dict[str, Any]] = {}
    for sport in ledger_sports:
        for d in dates:
            path = lgl.ledger_path(sport, d)
            if not path.exists():
                continue
            with path.open(encoding="utf-8") as fh:
                for line in fh:
                    try:
                        row = json.loads(line)
                    except ValueError:
                        continue
                    ev = str(row.get("event_id") or "")
                    if not ev or ev in out or not row.get("home_team") or not row.get("away_team"):
                        continue
                    at = _dpp()._epoch(row.get("recorded_at"))
                    held = ledger_first.get(ev)
                    if held is None or (at is not None and (held["_at"] is None or at < held["_at"])):
                        ledger_first[ev] = {"sport": sport, "home": row["home_team"], "away": row["away_team"],
                                            "_at": at}
    for ev, row in ledger_first.items():
        at = row.pop("_at")
        row["commence"] = None if at is None else datetime.fromtimestamp(at, timezone.utc).isoformat()
        row["source"] = "live_ledger"
        out[ev] = row
    return out


class Chips:
    """The board's final-score chips per Central date: the fleet's ``/api/board/game-chips``, or saved responses
    (``<chips_dir>/game_chips_<date>.json``). A date after ``last_date`` is never read."""

    def __init__(self, *, base_url: str | None = None, chips_dir: Path | None = None, last_date: str | None = None,
                 fetch: Callable[[str], Mapping[str, Any]] | None = None):
        self.base_url, self.chips_dir, self.last_date = base_url, chips_dir, last_date
        self._fetch = fetch
        self.cache: dict[str, list[Mapping[str, Any]]] = {}
        self.read: list[str] = []

    def _payload(self, d: str) -> Mapping[str, Any]:
        if self._fetch is not None:
            return self._fetch(d)
        if self.chips_dir is not None:
            path = Path(self.chips_dir) / f"game_chips_{d}.json"
            return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        url = f"{str(self.base_url).rstrip('/')}/api/board/game-chips?{urllib.parse.urlencode({'date': d})}"
        with urllib.request.urlopen(url, timeout=180) as resp:
            return json.loads(resp.read())

    def __call__(self, d: str) -> list[Mapping[str, Any]]:
        if self.last_date and d > self.last_date:
            return []
        if d not in self.cache:
            payload = self._payload(d)
            self.read.append(d)
            self.cache[d] = [c for c in (payload.get("chips") or []) if isinstance(c, Mapping)]
        return self.cache[d]


class ChipTruth:
    """Outcome of a game line from the board's final-score chips (slice 2; module docstring)."""

    def __init__(self, events: Mapping[str, Mapping[str, Any]], chips: Callable[[str], list], *, max_commence: float,
                 college=None, scorecard=None):
        self.events, self.chips, self.max_commence = events, chips, max_commence
        self.csg = college or _college()
        self.sc = scorecard or _scorecard()
        self._cand: dict[tuple[str, str], list[dict[str, Any]]] = {}
        self._found: dict[str, tuple[Mapping[str, Any] | None, str | None, str | None]] = {}

    def _candidates(self, d: str, sport: str) -> list[dict[str, Any]]:
        key = (d, sport)
        if key not in self._cand:
            rows = []
            for chip in self.chips(d):
                if str(chip.get("sport") or "").strip().lower() != sport:
                    continue
                away = chip.get("away") if isinstance(chip.get("away"), Mapping) else {}
                home = chip.get("home") if isinstance(chip.get("home"), Mapping) else {}
                try:
                    scores: tuple[int, int] | None = (int(away.get("score")), int(home.get("score")))
                except (TypeError, ValueError):
                    scores = None
                rows.append({
                    "state": str(chip.get("state") or "").strip().lower(), "scores": scores,
                    "away": self.sc._side_names(away), "home": self.sc._side_names(home),
                    "linescore": chip.get("linescore") if isinstance(chip.get("linescore"), Mapping) else {},
                    "start": _dpp()._epoch(chip.get("start_time_utc")),
                })
            self._cand[key] = rows
        return self._cand[key]

    def find(self, event_id: str) -> tuple[Mapping[str, Any] | None, str | None, str | None]:
        """(chip, 'same' | 'swapped', refusal) for one event; cached."""
        if event_id in self._found:
            return self._found[event_id]
        res: tuple[Mapping[str, Any] | None, str | None, str | None]
        ev = self.events.get(event_id)
        start = _dpp()._epoch(ev.get("commence")) if ev else None
        if ev is None or start is None:
            res = (None, None, R_NO_EVENT)
        elif start >= self.max_commence:
            res = (None, None, R_AFTER_WINDOW)
        else:
            res = (None, None, "no_chip_match")
            rec = {"sport": ev["sport"], "home_team": ev["home"], "away_team": ev["away"]}
            cdate = _date.fromisoformat(_dpp()._central_date(start))
            for d in (cdate, cdate - timedelta(days=1), cdate + timedelta(days=1)):
                cands = [c for c in self._candidates(d.isoformat(), ev["sport"])
                         if c["start"] is None or (abs(c["start"] - start) <= CHIP_START_TOLERANCE_S
                                                   and c["start"] < self.max_commence)]
                if not cands:
                    continue
                chip, why = self.sc.match_chip(rec, cands)
                orient = "same"
                if chip is None and why == "no_chip_match":
                    chip, why = self.sc.match_chip({**rec, "home_team": ev["away"], "away_team": ev["home"]}, cands)
                    orient = "swapped"
                if chip is not None:
                    res = (chip, orient, None)
                    break
                res = (None, None, why or "no_chip_match")
                if why == "ambiguous_chip_match":
                    break
        self._found[event_id] = res
        return res

    def scores(self, sport: str, event_id: str, segment: str) -> tuple[tuple[int, int] | None, str | None]:
        """((home, away) in the EVENT's orientation, refusal)."""
        from syndicate.features.shared.segment_actuals import segment_score_pair

        chip, orient, refusal = self.find(event_id)
        if chip is None:
            return None, refusal
        if chip["state"] != "final":
            return None, R_NOT_FINAL
        if segment in ("", "full"):
            if chip["scores"] is None:
                return None, R_NOT_FINAL
            pair: tuple[int, int] | None = (chip["scores"][1], chip["scores"][0])
        else:
            hl, al = chip["linescore"].get("home"), chip["linescore"].get("away")
            if sport in COLLEGE_HALVES:
                h, a = self.csg.segment_points(hl, segment), self.csg.segment_points(al, segment)
                pair = (h, a) if h is not None and a is not None else None
            else:
                pair = segment_score_pair(sport, segment, home_linescores=hl, away_linescores=al)
        if pair is None:
            return None, R_SEGMENT
        return (pair[1], pair[0]) if orient == "swapped" else pair, None

    def __call__(self, op: Mapping[str, Any]) -> tuple[float | None, str | None]:
        family = el.family_of(str(op.get("market") or ""))
        if family not in GAME_FAMILIES:
            return None, R_PROP_OUTCOME
        pair, refusal = self.scores(str(op.get("sport") or ""), str(op.get("event_id") or ""),
                                    str(op.get("segment") or "full"))
        if pair is None:
            return None, refusal
        rule = outcome if op.get("phase") == "live" else outcome_book
        return _graded(rule(family, str(op.get("side") or ""), op.get("line"), *pair))


class CloseTruth:
    """The fast PREGAME truth: the probability of the opinion's side at the close (module docstring). ``prepare``
    reads the quotes once for every pregame line; the call then looks the line up."""

    def __init__(self, events: Mapping[str, Mapping[str, Any]], *, max_commence: float, last_date: str | None = None,
                 iter_quotes: Callable[[str, str], Iterable[Mapping[str, Any]]] | None = None):
        self.events, self.max_commence, self.last_date = events, max_commence, last_date
        self.iter_quotes = iter_quotes or _dpp()._default_iter_quotes
        self.label: dict[str, tuple[float | None, str | None]] = {}
        self.basis: dict[str, str] = {}
        self.shards_read: list[tuple[str, str]] = []

    def _quotes(self, sport: str, d: str) -> Iterable[Mapping[str, Any]]:
        if self.last_date and d > self.last_date:
            return iter(())
        self.shards_read.append((sport, d))
        return self.iter_quotes(sport, d)

    def prepare(self, opinions: Iterable[tuple[str, Mapping[str, Any]]]) -> int:
        dpp = _dpp()
        bets: dict[str, dict[str, Any]] = {}
        for _, op in opinions:
            if op.get("phase") != "pregame" or op.get("refusal"):
                continue
            lk = str(op.get("line_key") or "")
            if not lk or lk in bets or lk in self.label:
                continue
            ev = self.events.get(str(op.get("event_id") or ""))
            start = dpp._epoch(ev.get("commence")) if ev else None
            if start is None:
                self.label[lk] = (None, R_NO_EVENT)
                continue
            if start >= self.max_commence:
                self.label[lk] = (None, R_AFTER_WINDOW)
                continue
            bets[lk] = {"event_id": str(op.get("event_id")), "market": op.get("market"), "segment": op.get("segment"),
                        "player": op.get("player"), "side": op.get("side"), "line": op.get("line"),
                        "sport": op.get("sport"), "commence_time": ev["commence"]}
        closes, commence = dpp.collect_closes(list(bets.values()), self._quotes)
        for lk, b in bets.items():
            key = dpp.close_key(b["event_id"], b["market"], b["segment"], b["player"], b["side"], b["line"])
            side = str(b["side"] or "").strip().lower()
            res = dpp.close_probabilities(closes.get(key) or {}, side, commence.get(b["event_id"]))
            if res["sharp_close"] is not None:
                self.label[lk], self.basis[lk] = (float(res["sharp_close"]), None), "sharp"
            elif res["consensus_close"] is not None:
                self.label[lk], self.basis[lk] = (float(res["consensus_close"]), None), "consensus"
            else:
                why = res["sharp_reason"] or "none"
                self.label[lk] = (None, f"{R_NO_CLOSE}:{why}|books={res['consensus_books']}")
        return len(bets)

    def __call__(self, op: Mapping[str, Any]) -> tuple[float | None, str | None]:
        if op.get("phase") != "pregame":
            return None, R_PREGAME_ONLY
        return self.label.get(str(op.get("line_key") or ""), (None, f"{R_NO_CLOSE}:not_prepared"))


class Truth:
    """``outcome``: live basketball -> slice 1's scores; every other game line -> the chips; props refused.
    ``close``: the pregame close."""

    def __init__(self, mode: str, *, basketball=None, chips=None, close=None):
        self.mode, self.basketball, self.chips, self.close = mode, basketball, chips, close

    def __call__(self, op: Mapping[str, Any]) -> tuple[float | None, str | None]:
        if self.mode == "close":
            return self.close(op)
        if el.family_of(str(op.get("market") or "")) not in GAME_FAMILIES:
            return None, R_PROP_OUTCOME
        if op.get("phase") == "live" and str(op.get("sport") or "") in SPORTS:
            return self.basketball(op)
        return self.chips(op)


# ----------------------------------------------------------------------------- the run


def iter_opinions(opinions_dirs: Sequence[Path] | Path, dates: Iterable[str]) -> Iterable[tuple[str, dict[str, Any]]]:
    dirs = [opinions_dirs] if isinstance(opinions_dirs, Path) else list(opinions_dirs)
    for d in dates:
        for directory in dirs:
            path = directory / f"opinions_{d}.jsonl"
            if not path.exists():
                print(f"MISSING opinions file {path}", flush=True)
                continue
            with path.open(encoding="utf-8") as fh:
                for line in fh:
                    yield d, json.loads(line)


def game_dated(opinions: Iterable[tuple[str, Mapping[str, Any]]], events: Mapping[str, Mapping[str, Any]]
               ) -> Iterable[tuple[str, Mapping[str, Any]]]:
    """(the GAME's Central date, opinion): a pregame line takes its event's start date (it is listed on earlier
    slates); a live line keeps its slate, which is the game's. So the forward split never cuts a game in two."""
    dpp = _dpp()
    for slate, op in opinions:
        if op.get("phase") == "pregame":
            ev = events.get(str(op.get("event_id") or ""))
            start = dpp._epoch(ev.get("commence")) if ev else None
            if start is not None:
                yield dpp._central_date(start), op
                continue
        yield slate, op


def coverage(opinions: Iterable[tuple[str, Mapping[str, Any]]], truth) -> dict[tuple[str, str, str], dict[str, int]]:
    """Per sport x family x phase: usable opinions and each truth outcome by name (one row per line-instant)."""
    table: dict[tuple[str, str, str], dict[str, int]] = defaultdict(lambda: defaultdict(int))
    seen: set[str] = set()
    for _, op in opinions:
        if op.get("refusal") or op.get("p_prior") is None or op.get("delta_logit") is None:
            continue
        key = f"{op.get('line_key')}|{op.get('t')}"
        if key in seen:
            continue
        seen.add(key)
        g = (str(op.get("sport") or ""), el.family_of(str(op.get("market") or "")), str(op.get("phase") or ""))
        table[g]["line_instants"] += 1
        y, refusal = truth(op)
        if refusal == el.PUSH:
            table[g]["push"] += 1
        elif y is None:
            table[g][refusal or "unknown"] += 1
        else:
            table[g]["graded"] += 1
    return table


def prior_ll(examples) -> dict[tuple[str, str, str], float]:
    acc: dict[tuple[str, str, str], list[float]] = defaultdict(lambda: [0.0, 0.0])
    for ex in examples:
        k = el.group_key(ex)
        acc[k][0] += ex.weight * el.log_loss(el._sig(ex.logit_prior), ex.y)
        acc[k][1] += ex.weight
    return {k: round(v[0] / v[1], 5) for k, v in acc.items() if v[1]}


def _fmt_group(k) -> str:
    return " ".join(f"{x:8s}" for x in k)


def build_truth(args: argparse.Namespace, dates: list[str], dirs: list[Path], events):
    root = Path(args.root) if args.root else None
    max_commence = _dpp()._epoch(args.max_commence) if args.max_commence else default_max_commence(dates[-1])
    by_source: dict[str, int] = defaultdict(int)
    for ev in events.values():
        by_source[ev["source"]] += 1
    window = datetime.fromtimestamp(max_commence, timezone.utc).isoformat()
    if args.truth == "close":
        close = CloseTruth(events, max_commence=max_commence, last_date=dates[-1])
        n = close.prepare(iter_opinions(dirs, dates))
        basis: dict[str, int] = defaultdict(int)
        for b in close.basis.values():
            basis[b] += 1
        print(f"TRUTH mode=close events={len(events)} {json.dumps(dict(by_source))} max_commence={window} "
              f"pregame_lines={n} labelled={dict(basis)} shards_read={len(close.shards_read)} "
              f"last_shard={max((d for _s, d in close.shards_read), default=None)}", flush=True)
        return Truth("close", close=close), close
    sc = _scorecard()
    base = args.base_url or os.environ.get("SYNDICATE_BASE_URL") or sc.DEFAULT_BASE_URL
    chips = Chips(base_url=base, chips_dir=Path(args.chips_dir) if args.chips_dir else None, last_date=dates[-1])
    basketball = BasketballTruth(dates, root=root)
    print(f"TRUTH mode=outcome nba_games={len(basketball.nba)} college_games={len(basketball.college)} "
          f"evidence_games={len(basketball.teams)} events={len(events)} {json.dumps(dict(by_source))} "
          f"max_commence={window} chips={'dir ' + str(args.chips_dir) if args.chips_dir else base} "
          f"root={basketball.root}", flush=True)
    return Truth("outcome", basketball=basketball, chips=ChipTruth(events, chips, max_commence=max_commence)), chips


def run(args: argparse.Namespace) -> int:
    dates = span(args.dates)
    dirs = [Path(x) for x in args.opinions_dir.split(",") if x]
    events = load_events(dates, root=Path(args.root) if args.root else None)
    truth, source = build_truth(args, dates, dirs, events)
    cov = coverage(iter_opinions(dirs, dates), truth)
    for k in sorted(cov):
        row = dict(sorted(cov[k].items()))
        print(f"COVERAGE {_fmt_group(k)} {json.dumps(row)}", flush=True)
    if isinstance(source, Chips):
        print(f"CHIPS dates_read={sorted(source.read)}", flush=True)
    examples, stats = el.build_examples(game_dated(iter_opinions(dirs, dates), events), truth)
    print(f"BUILD {json.dumps(stats.as_dict())}", flush=True)
    train, test = el.forward_split(examples, args.test_from)
    print(f"SPLIT train={len(train)} ({len({e.cluster for e in train})} games, all before {args.test_from}) "
          f"test={len(test)} ({len({e.cluster for e in test})} games, each held out whole) "
          f"shared={len({e.cluster for e in train} & {e.cluster for e in test})}", flush=True)
    for label, part in (("train", train), ("test", test)):
        for k, v in sorted(prior_ll(part).items()):
            flag = "  <-- ABOVE ln2: check the side/frame" if v > 0.75 else ""
            print(f"PRIOR_LL {label:5s} {_fmt_group(k)} {v}{flag}", flush=True)
    model = el.fit(train, tau=args.tau)
    print(f"FIT params={len(model.params)} examples={model.n_examples} games={model.n_games} "
          f"converged={model.converged} ({model.message})", flush=True)
    weights = el.weight_table(model, train)
    for w in weights:
        if w["n"] >= args.min_print_n:
            print(f"WEIGHT {w['expert']:13s} {w['cell']:48s} n={w['n']:6d} w={w['w']:+.3f} se={w['se']:.3f} "
                  f"applied={w['applied']}", flush=True)
    reports = {
        "OFF": el.evaluate(test, None),
        "ON": el.evaluate(test, model, applied=True),
        "RAW": el.evaluate(test, model, applied=False),
        "ON_BY_AGE": el.evaluate(test, model, applied=True, by=el.group_age_key),
    }
    if isinstance(source, CloseTruth):
        reports["ON_BY_BASIS"] = el.evaluate(test, model, applied=True,
                                             by=lambda ex: el.group_key(ex) + (source.basis.get(ex.line_key, "?"),))
    off_nonzero = 0
    for label, rep in reports.items():
        for k, v in rep.items():
            if label == "OFF" and v["delta_log_loss"] != 0.0:
                off_nonzero += 1
            print(f"HELD_OUT {label:11s} {_fmt_group(k)} games={v['games']:4d} lines={v['lines']:6d} "
                  f"prior_ll={v['prior_log_loss']} d_ll={v['delta_log_loss']:+.5f} ci95={v['ci95']} "
                  f"beats_prior={v['beats_prior']}", flush=True)
    moved = sum(1 for ex in test if abs(el.p_decision(ex, model) - el.p_decision(ex, None)) > 1e-12)
    applied_cells = sum(1 for w in weights if w["applied"])
    print(f"REACH on_moves={moved}/{len(test)} applied_cells={applied_cells}/{len(weights)} "
          f"off_nonzero={off_nonzero}", flush=True)
    if args.json:
        out = {
            "learner": el.LEARNER_VERSION, "truth": args.truth, "dates": dates, "test_from": args.test_from,
            "tau": args.tau, "coverage": {"|".join(k): dict(v) for k, v in cov.items()}, "build": stats.as_dict(),
            "weights": weights,
            "held_out": {lab: {"|".join(k): v for k, v in rep.items()} for lab, rep in reports.items()},
            "reach": {"on_moves": moved, "test": len(test), "applied_cells": applied_cells, "off_nonzero": off_nonzero},
        }
        Path(args.json).write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
    return 1 if off_nonzero else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--opinions-dir", required=True, help="one directory, or a comma list")
    r.add_argument("--dates", required=True, help="YYYY-MM-DD..YYYY-MM-DD or a comma list")
    r.add_argument("--test-from", required=True, help="first held-out slate date")
    r.add_argument("--truth", choices=("outcome", "close"), default="outcome")
    r.add_argument("--max-commence", default=None, help="ISO time; default 06:00Z the day after the last slate")
    r.add_argument("--chips-dir", default=None, help="saved /api/board/game-chips responses, game_chips_<date>.json")
    r.add_argument("--base-url", default=None, help="the fleet's web (default: SYNDICATE_BASE_URL, else the fleet)")
    r.add_argument("--root", default=None)
    r.add_argument("--tau", type=float, default=el.TAU)
    r.add_argument("--min-print-n", type=int, default=200)
    r.add_argument("--json", default=None)
    args = ap.parse_args(argv)
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
