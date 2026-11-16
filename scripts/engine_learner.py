"""Phase 1B M2 shadow learner, the runner (lane ``engine-learner``). READ-ONLY: it writes nothing under the data root.

    python scripts/engine_learner.py run --opinions-dir <dir> --dates 2026-11-09..2026-11-14 --test-from 2026-11-13 \
        [--json out.json] [--root <data root>]

Reads ``opinions_<date>.jsonl`` (the experts runner's ``--opinions`` output, ``scripts/engine_experts.py``) for each
slate, joins every LIVE BASKETBALL GAME LINE (nba / ncaab / wncaab; totals, spreads, h2h; full game and segments) to
its outcome from the data root, fits ``engine_learner`` on the slates before ``--test-from`` and prints:

* COVERAGE   per sport x family x phase: opinions, graded examples, lines, games, and every refusal by name -- the
             denominator for everything below.
* PRIOR_LL   the prior's own log loss per group, in and out of sample. A side or frame read backwards shows here as
             a log loss far above ln 2 (0.693), so it is the truth join's self-check.
* WEIGHTS    per expert x leaf cell: n, the fitted weight, its game-clustered SE, and whether it is applied.
* HELD_OUT   per sport x family x phase: log loss of p_decision minus the prior's on the test slates, 95% CI by game
             bootstrap. ``OFF`` must read exactly 0 everywhere (the off switch is the prior); ``ON`` is the learner
             with the lower-bound rule; ``RAW`` applies every fitted weight (a reading, not the learner).
* REACH      off != on: how many held-out examples ON moves away from the prior.

Truth, slice 1 (``docs/ai_context/engine_learner.md``):

* NBA: ``nba_source/data/processed/linescores_<date>.json`` (completed games only, by ESPN event id, which the live
  evidence log carries). Full game = every period, overtime included; segments by the platform's own rule,
  ``segment_actuals.segment_score_pair``.
* NCAAB / WNCAAB: the slate scoreboard (``<league>_source/data/scoreboard/scoreboard_<date>.json``), FINAL games only;
  h1 = period 1, h2 = period 2 plus every overtime (``college_segment_grade.segment_points``).
* Orientation: the evidence log's home team against the score source's (neutral sites are re-oriented by the slate).
  Totals never need it; a spread or moneyline whose orientation cannot be told is refused, never guessed.
* The event: totals OVER = total > line; spreads HOME = home - away > line (the live join's away frame, as
  ``college_segment_grade.outcome``); h2h HOME = home > away. Equal = push, dropped.

Not in slice 1, each refused by name: pregame opinions, player props, other sports (slice 2 adds the NBA prop grader
of lane ``nba-live-prop-grade``, NHL / NFL / NCAAF finals, the pregame close and outcome, and the +300 s mark-out).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from collections import defaultdict
from datetime import date as _date, timedelta
from pathlib import Path
from typing import Any, Iterable, Mapping

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from syndicate.features.shared import engine_learner as el  # noqa: E402

SPORTS = ("nba", "ncaab", "wncaab")
GAME_FAMILIES = ("totals", "spreads", "h2h")

# ESPN's NBA abbreviations that differ from the slate's.
NBA_CODE_ALIASES = {"NO": "NOP", "NY": "NYK", "GS": "GSW", "SA": "SAS", "UTAH": "UTA", "WSH": "WAS", "UTA": "UTA"}

R_PREGAME = "pregame_not_in_slice1"
R_PROPS = "props_not_in_slice1"
R_SPORT = "sport_not_in_slice1"
R_NO_FINAL = "no_final_score"
R_SEGMENT = "segment_unscorable"
R_ORIENT = "orientation_unresolved"
R_SIDE = "side_unsupported"


def _college():
    spec = importlib.util.spec_from_file_location("college_segment_grade", REPO / "scripts" / "college_segment_grade.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def span(text: str) -> list[str]:
    if ".." not in text:
        return [d for d in text.split(",") if d]
    lo, hi = (_date.fromisoformat(x) for x in text.split(".."))
    return [(lo + timedelta(days=i)).isoformat() for i in range((hi - lo).days + 1)]


# ----------------------------------------------------------------------------- the outcome of one line


def outcome(family: str, side: str, line: float | None, home: int, away: int) -> float | None | str:
    """1.0 / 0.0 for the opinion's side winning / losing, 0.5 for a push, or a refusal name."""
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
    """Outcome of a live basketball game line from the data root's final scores (see the module docstring)."""

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
        y = outcome(family, str(op.get("side") or ""), op.get("line"), *pair)
        if isinstance(y, str):
            return None, y
        return y, None


# ----------------------------------------------------------------------------- the run


def iter_opinions(opinions_dir: Path, dates: Iterable[str]) -> Iterable[tuple[str, dict[str, Any]]]:
    for d in dates:
        path = opinions_dir / f"opinions_{d}.jsonl"
        if not path.exists():
            print(f"MISSING opinions file {path}", flush=True)
            continue
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                yield d, json.loads(line)


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
        if y is None:
            table[g][refusal or "unknown"] += 1
        elif y == 0.5:
            table[g]["push"] += 1
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


def run(args: argparse.Namespace) -> int:
    dates = span(args.dates)
    opinions_dir = Path(args.opinions_dir)
    truth = BasketballTruth(dates, root=Path(args.root) if args.root else None)
    print(f"TRUTH nba_games={len(truth.nba)} college_games={len(truth.college)} evidence_games={len(truth.teams)} "
          f"root={truth.root}", flush=True)
    cov = coverage(iter_opinions(opinions_dir, dates), truth)
    for k in sorted(cov):
        row = dict(sorted(cov[k].items()))
        print(f"COVERAGE {_fmt_group(k)} {json.dumps(row)}", flush=True)
    examples, stats = el.build_examples(iter_opinions(opinions_dir, dates), truth)
    print(f"BUILD {json.dumps(stats.as_dict())}", flush=True)
    train, test = el.forward_split(examples, args.test_from)
    print(f"SPLIT train={len(train)} ({len({e.cluster for e in train})} games, slates < {args.test_from}) "
          f"test={len(test)} ({len({e.cluster for e in test})} games)", flush=True)
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
    off_nonzero = 0
    for label, rep in reports.items():
        for k, v in rep.items():
            if label == "OFF" and v["delta_log_loss"] != 0.0:
                off_nonzero += 1
            print(f"HELD_OUT {label:9s} {_fmt_group(k)} games={v['games']:4d} lines={v['lines']:6d} "
                  f"prior_ll={v['prior_log_loss']} d_ll={v['delta_log_loss']:+.5f} ci95={v['ci95']} "
                  f"beats_prior={v['beats_prior']}", flush=True)
    moved = sum(1 for ex in test if abs(el.p_decision(ex, model) - el.p_decision(ex, None)) > 1e-12)
    applied_cells = sum(1 for w in weights if w["applied"])
    print(f"REACH on_moves={moved}/{len(test)} applied_cells={applied_cells}/{len(weights)} "
          f"off_nonzero={off_nonzero}", flush=True)
    if args.json:
        out = {
            "learner": el.LEARNER_VERSION, "dates": dates, "test_from": args.test_from, "tau": args.tau,
            "coverage": {"|".join(k): dict(v) for k, v in cov.items()}, "build": stats.as_dict(),
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
    r.add_argument("--opinions-dir", required=True)
    r.add_argument("--dates", required=True, help="YYYY-MM-DD..YYYY-MM-DD or a comma list")
    r.add_argument("--test-from", required=True, help="first held-out slate date")
    r.add_argument("--root", default=None)
    r.add_argument("--tau", type=float, default=el.TAU)
    r.add_argument("--min-print-n", type=int, default=200)
    r.add_argument("--json", default=None)
    args = ap.parse_args(argv)
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
