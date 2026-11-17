"""Grade NBA quarter/half game-line probabilities against the market and the box (todo #818).

WHY. `nba_game_projections._project_row` prices every NBA h1/h2/q1-q4 row off the game's
smart-sim histogram, then SERVES `served_game_probability`: a logit blend toward the
de-vigged book. The fleet's `nba_game_book_blend.json` has no period keys, so every period
row is served at the `default` weight 0 -- the book's own fair, edge 0 ("periods: unmeasured
-> default 0 (the market)"). A grade of the served number reads parity by construction. This
grades the RAW sim probability instead: do the sim's period probabilities carry anything
beyond the line, enough to earn a weight above 0?

PRE-REGISTERED in `.syndicate/findings_2026-11-16_nba_segment_skill.md` (main `53c4f664e`),
before any outcome was read. This file is committed to main after a `--count-only` run and
before any outcome is read; the results cite its blob.

REUSED UNCHANGED from `scripts/nfl_segment_skill.py` (#752, blob `020cb082b5a9`): the quote
reader, the de-vig and consensus line (`consensus_markets`), the framing (spreads in the
AWAY frame, home covers strictly past it), the outcome rule (`segment_outcome`, pushes
dropped), the statistics (`grade`, `clustered_ci`, `brier`). What is NBA's own:

- BRIDGE = production's: `nba_game_projections.load_nba_game_projections(<central date of
  tip>)` -> `NbaGameProjectionIndex.lookup(home, away, commence_time)` -> the entry's
  `smart_sim_<date>_<HOME>_<AWAY>.json` `score.dist`. Read from a READ-ONLY copy of the fleet
  (`--nba-root`, set as `SYNDICATE_NBA_SOURCE_ROOT`); any file that resolves outside it is
  refused (`sim_outside_run_dir` / `cards_outside_run_dir`), never silently read.
- AS-OF = the sim file's mtime (copied with `cp -p`; the file carries no generation stamp)
  must be STRICTLY before the quote's `commence_time`, else `sim_written_after_tip`.
- PHASE = production's `season_phase_for_date(<central date>)` must be "regular"
  (`season_phase_unknown` / `not_regular_season` otherwise). Window: tips
  `--tips-from` <= t < `--tips-to`.
- MODEL (RAW) = production's `_projection_from_dist(row, market, block, segment=, sims=)`
  `model_prob_over` at the consensus line, BEFORE `served_game_probability`. Its push
  convention is production's: P(X > line) over ALL draws, so on a whole-number line the push
  mass sits in the denominator (`whole_number_lines` is reported).
- BOX = ESPN's NBA scoreboard, matched on the sim's ESPN `game_id` (team names checked),
  scored by production's `segment_score_pair("nba", ...)`: `h2` takes every overtime, `q4`
  is the fourth quarter alone.
- G2 = production's `blend_with_book(p_raw, p_market, w)` on the grid 0, 0.05, ..., 1.0; the
  FIT window picks the w with the smallest Brier (ties -> the smaller w), TEST scores it.
  `--frozen-w` (the Dec 7 re-grade) skips the fit and scores the given weights on the whole
  window.
- Bootstrap seed 818.

`--count-only` reads NO box: ESPN is never fetched, and the population is (a) + (b) only.

    py -3 scripts/nba_segment_skill.py --nba-root C:\\tmp\\nba_seg\\nba_source \\
        --quotes C:\\tmp\\nba_seg\\quotes --linescores C:\\tmp\\nba_seg\\linescores.json \\
        --out C:\\tmp\\nba_seg\\result.json [--count-only]
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import statistics
import sys
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts.nfl_segment_skill import (  # noqa: E402 -- the #752 method, unchanged
    MARKETS,
    SEGMENTS,
    _ts,
    brier,
    clustered_ci,
    consensus_markets,
    grade,
    iter_quotes,
    segment_outcome,
)

TIPS_FROM = "2026-10-20T12:00:00Z"
FIT_END = "2026-11-02T12:00:00Z"
TIPS_TO = "2026-11-16T12:00:00Z"
W_GRID = tuple(round(0.05 * i, 2) for i in range(21))
SEED = 818
ESPN_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates={ymd}&limit=100"


def use_nba_root(nba_root: Path) -> Path:
    """Point production's NBA readers at the read-only copy. Returns the resolved root."""
    root = Path(nba_root).resolve()
    os.environ["SYNDICATE_NBA_SOURCE_ROOT"] = str(root)
    os.environ["SYNDICATE_DATA_ROOT"] = str(root.parent)
    return root


def _inside(path: Path, root: Path) -> bool:
    try:
        Path(path).resolve().relative_to(root)
        return True
    except ValueError:
        return False


# ------------------------------------------------------------------ bridge ----
class Bridge:
    """Production's quote -> sim join, with the as-of and phase refusals, cached per date."""

    def __init__(self, root: Path, *, tips_from: str = TIPS_FROM, tips_to: str = TIPS_TO):
        self.root = Path(root).resolve()
        self.tips_from, self.tips_to = _ts(tips_from), _ts(tips_to)
        self._index: dict[str, Any] = {}
        self._payload: dict[str, Mapping[str, Any]] = {}

    def index_for(self, central: str):
        from syndicate.features.shared.nba_game_projections import load_nba_game_projections

        if central not in self._index:
            self._index[central] = load_nba_game_projections(central)
        return self._index[central]

    def payload(self, path: str) -> Mapping[str, Any]:
        if path not in self._payload:
            try:
                self._payload[path] = json.loads(Path(path).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                self._payload[path] = {}
        return self._payload[path]

    def find(self, c: Mapping[str, Any]) -> tuple[str | None, dict[str, Any]]:
        from syndicate.features.shared.nba_game_projections import season_phase_for_date
        from syndicate.features.shared.timezone import central_date_from_iso

        start = _ts(str(c["commence_time"]))
        if not (self.tips_from <= start < self.tips_to):
            return "outside_window", {}
        central = central_date_from_iso(str(c["commence_time"]))
        if central is None:
            return "season_phase_unknown", {}
        central_s = central.isoformat()
        phase = season_phase_for_date(central_s)
        if phase is None:
            return "season_phase_unknown", {}
        if phase != "regular":
            return "not_regular_season", {}
        index = self.index_for(central_s)
        if any(not _inside(Path(p), self.root) for p in index.source_files):
            return "cards_outside_run_dir", {}
        entry = index.lookup(c.get("home_team"), c.get("away_team"), c.get("commence_time"))
        if entry is None:
            return "no_sim_entry", {}
        if not entry.smart_sim_path:
            return "no_smart_sim_file", {}
        path = Path(entry.smart_sim_path)
        if not _inside(path, self.root):
            return "sim_outside_run_dir", {}
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        if not mtime < start:
            return "sim_written_after_tip", {}
        if entry.dist is None:
            return "no_sim_histogram", {}
        return None, {"entry": entry, "central_date": central_s, "sim_path": str(path),
                      "sim_mtime": mtime.isoformat(), "minutes_before_tip": (start - mtime).total_seconds() / 60.0}


def raw_model_prob(c: Mapping[str, Any], seg: str, market: str, entry) -> tuple[str | None, float | None]:
    """Production's RAW probability (home/over side) at the consensus line, before the blend."""
    from syndicate.features.shared.wnba_game_projections import _dist_segment, _projection_from_dist

    block = _dist_segment({"dist": entry.dist}, seg)
    if block is None:
        return "no_segment_block", None
    row = {"line": c["line"], "home_team": c.get("home_team"), "away_team": c.get("away_team"),
           "commence_time": c.get("commence_time"), "market": market, "segment": seg}
    projection = _projection_from_dist(row, market, block, segment=seg, sims=entry.sim_draws)
    if projection is None:
        return "no_market_distribution", None
    prob = projection.get("model_prob_over")
    if prob is None:
        return "model_prob_refused", None
    return None, float(prob)


# ----------------------------------------------------------------- outcomes ----
def fetch_linescores(dates: Iterable[str], cache: Path) -> dict[str, dict[str, Any]]:
    """`{espn_event_id: {date, home_name, away_name, home, away, final}}` from ESPN's NBA scoreboard."""
    from syndicate.features.shared.segment_actuals import linescores_from_competitor

    have: dict[str, Any] = json.loads(cache.read_text(encoding="utf-8")) if cache.exists() else {}
    games = have.setdefault("games", {})
    fetched = set(have.setdefault("dates_fetched", []))
    for ymd in sorted(set(dates)):
        if ymd in fetched:
            continue
        req = urllib.request.Request(ESPN_SCOREBOARD.format(ymd=ymd.replace("-", "")),
                                     headers={"User-Agent": "segment-grade/1.0"})
        payload = json.load(urllib.request.urlopen(req, timeout=60))
        for event in payload.get("events") or []:
            comp = (event.get("competitions") or [{}])[0]
            status = (comp.get("status") or {}).get("type") or {}
            teams = {t.get("homeAway"): t for t in comp.get("competitors") or []}
            if "home" not in teams or "away" not in teams:
                continue
            games[str(event.get("id"))] = {
                "date": str(event.get("date") or comp.get("date") or ""),
                "home_name": (teams["home"].get("team") or {}).get("displayName"),
                "away_name": (teams["away"].get("team") or {}).get("displayName"),
                "home": linescores_from_competitor(teams["home"]),
                "away": linescores_from_competitor(teams["away"]),
                "final": bool(status.get("completed")),
            }
        fetched.add(ymd)
        have["dates_fetched"] = sorted(fetched)
        cache.write_text(json.dumps(have, indent=1), encoding="utf-8")
    return games


def find_box(c: Mapping[str, Any], game_id: str, boxes: Mapping[str, Mapping[str, Any]]) -> tuple[str | None, Mapping[str, Any] | None]:
    """The ESPN event for this game: the sim's `game_id`, home/away names checked."""
    from syndicate.features.shared.team_aliases import teams_match

    box = boxes.get(str(game_id)) if game_id else None
    if box is None:
        return "no_espn_event", None
    if not (teams_match("nba", c.get("home_team"), box.get("home_name"))
            and teams_match("nba", c.get("away_team"), box.get("away_name"))):
        return "box_team_mismatch", None
    if not box.get("final"):
        return "no_final_box", None
    return None, box


# ------------------------------------------------------------------- build ----
def build_observations(consensus, bridge: Bridge, boxes, *, count_only: bool = False):
    """`(obs, refused_markets, refused_games, eligible)`. With `count_only` no box is touched."""
    from syndicate.features.shared.segment_actuals import segment_score_pair

    refused: dict[str, int] = defaultdict(int)
    refused_games: dict[str, set[str]] = defaultdict(set)
    eligible: dict[tuple[str, str, str], dict[str, Any]] = {}
    obs = []
    for (event, seg, market), c in sorted(consensus.items()):
        why, found = bridge.find(c)
        if why is None:
            why, p_raw = raw_model_prob(c, seg, market, found["entry"])
        if why:
            refused[why] += 1
            refused_games[why].add(event)
            continue
        entry = found["entry"]
        payload = bridge.payload(found["sim_path"])
        game_id = str(payload.get("game_id") or "")
        eligible[(event, seg, market)] = {"commence_time": c["commence_time"], "central_date": found["central_date"],
                                          "minutes_before_tip": found["minutes_before_tip"]}
        if count_only:
            continue  # NO OUTCOME IS READ before the grader is on main.
        why, box = find_box(c, game_id, boxes)
        if why is None:
            pair = segment_score_pair("nba", seg, home_linescores=box["home"], away_linescores=box["away"])
            if pair is None:
                why = "no_segment_score"
        if why is None:
            y = segment_outcome(market, c["line"], *pair)
            if y is None:
                why = "push"
        if why:
            refused[why] += 1
            refused_games[why].add(event)
            continue
        obs.append({
            "game": event, "espn_id": game_id, "segment": seg, "market": market, "line": c["line"], "y": y,
            "p_model": p_raw, "p_market": c["market_prob"], "books": c["books_at_line"],
            "home": c["home_team"], "away": c["away_team"], "commence_time": c["commence_time"],
            "central_date": found["central_date"], "sim_path": found["sim_path"], "sim_mtime": found["sim_mtime"],
            "home_pts": pair[0], "away_pts": pair[1], "periods_played": len(box["home"] or []),
        })
    return obs, dict(refused), {k: len(v) for k, v in refused_games.items()}, eligible


# --------------------------------------------------------------------- G2 ----
def _blend(o: Mapping[str, Any], w: float) -> float:
    from syndicate.features.shared.nba_prop_calibration import blend_with_book

    return blend_with_book(o["p_model"], o["p_market"], w)


def fit_weight(obs: list[Mapping[str, Any]]) -> tuple[float | None, dict[str, float]]:
    """The grid w with the smallest mean Brier of the blend; a tie (within 1e-12) keeps the smaller w."""
    if not obs:
        return None, {}
    curve: dict[str, float] = {}
    best_w, best = None, None
    for w in W_GRID:
        b = sum(brier(_blend(o, w), o["y"]) for o in obs) / len(obs)
        curve[f"{w:.2f}"] = round(b, 6)
        if best is None or b < best - 1e-12:
            best_w, best = w, b
    return best_w, curve


def _test(sub: list[Mapping[str, Any]], w: float | None, *, reps: int, seed: int) -> dict[str, Any]:
    if not sub or w is None:
        return {"n": len(sub)}
    d = clustered_ci(sub, lambda o: brier(_blend(o, w), o["y"]) - brier(o["p_market"], o["y"]), reps=reps, seed=seed)
    return {"n": len(sub), "games": len({o["game"] for o in sub}),
            "brier_blend": round(sum(brier(_blend(o, w), o["y"]) for o in sub) / len(sub), 5),
            "brier_market": round(sum(brier(o["p_market"], o["y"]) for o in sub) / len(sub), 5),
            "d": round(d[0], 6), "ci95": [round(d[1], 6), round(d[2], 6)]}


def g2(obs: list[Mapping[str, Any]], *, reps: int, seed: int, fit_end: str = FIT_END,
       frozen: Mapping[str, float] | None = None) -> dict[str, Any]:
    """Per family: w_fit on FIT, d = Brier(blend at w_fit) - Brier(market) on TEST, and whether it EARNS a weight
    (w_fit > 0 AND TEST CI upper < 0). With `frozen`, no fit: TEST is every observation, at the given w."""
    cut = _ts(fit_end)
    out: dict[str, Any] = {"grid": list(W_GRID), "fit_end": fit_end, "frozen": dict(frozen) if frozen else None,
                           "families": {}, "by_segment": {}}
    for market in MARKETS:
        fam = [o for o in obs if o["market"] == market]
        if frozen is not None:
            fit, test, w, curve = [], fam, frozen.get(market), {}
        else:
            fit = [o for o in fam if _ts(o["commence_time"]) < cut]
            test = [o for o in fam if _ts(o["commence_time"]) >= cut]
            w, curve = fit_weight(fit)
        t = _test(test, w, reps=reps, seed=seed)
        earns = bool(w is not None and w > 0 and t.get("ci95") and t["ci95"][1] < 0)
        out["families"][market] = {"w_fit" if frozen is None else "w_frozen": w, "fit_n": len(fit),
                                   "fit_games": len({o["game"] for o in fit}), "fit_curve": curve,
                                   "test": t, "earns_weight": earns}
        if frozen is not None:
            continue
        for seg in SEGMENTS:
            sfit = [o for o in fit if o["segment"] == seg]
            stest = [o for o in test if o["segment"] == seg]
            sw, _ = fit_weight(sfit)
            out["by_segment"][f"{market}/{seg}"] = {"w_fit": sw, "fit_n": len(sfit), "test": _test(stest, sw, reps=reps, seed=seed)}
    return out


# --------------------------------------------------------------------- G3 ----
def engine_read(obs: list[Mapping[str, Any]], bridge: Bridge, boxes, *, reps: int, seed: int) -> dict[str, Any]:
    """Every GRADED game: per-segment sim mean total/margin vs actual (bias CI), PIT of totals, quarter
    shares, overtime, and the `market_anchor.model_margin_raw` count. Descriptive only."""
    from syndicate.features.shared.prop_projections import _dist_mean
    from syndicate.features.shared.segment_actuals import segment_score_pair

    games: dict[str, Mapping[str, Any]] = {}
    for o in obs:
        games.setdefault(o["game"], o)
    rows = []
    anchor = Counter()
    ot_games = 0
    for event, o in sorted(games.items()):
        payload = bridge.payload(o["sim_path"])
        segs = ((payload.get("score") or {}).get("dist") or {}).get("segments") or {}
        ma = payload.get("market_anchor")
        raw = ma.get("model_margin_raw") if isinstance(ma, Mapping) else None
        anchor["graded_games"] += 1
        if not isinstance(ma, Mapping):
            anchor["no_market_anchor"] += 1
        elif raw is None:
            anchor["model_margin_raw_absent"] += 1
        elif isinstance(raw, (int, float)) and float(raw) == 0.0:
            anchor["model_margin_raw_exactly_0"] += 1
        else:
            anchor["model_margin_raw_nonzero"] += 1
        box = boxes[o["espn_id"]]
        if len(box["home"] or []) > 4:
            ot_games += 1
        for seg in ("full", "regulation", *SEGMENTS):
            sb = segs.get(seg)
            if not isinstance(sb, Mapping) or not isinstance(sb.get("total"), Mapping) or not isinstance(sb.get("margin"), Mapping):
                continue
            if seg == "full":
                pair = (sum(v or 0 for v in box["home"]), sum(v or 0 for v in box["away"]))
            elif seg == "regulation":
                pair = (sum(v or 0 for v in box["home"][:4]), sum(v or 0 for v in box["away"][:4]))
            else:
                pair = segment_score_pair("nba", seg, home_linescores=box["home"], away_linescores=box["away"])
            if pair is None:
                continue
            hist = sb["total"]
            n = sum(float(v) for v in hist.values()) or 1.0
            actual = pair[0] + pair[1]
            below = sum(float(v) for k, v in hist.items() if float(k) < actual) / n
            at = sum(float(v) for k, v in hist.items() if float(k) == actual) / n
            rows.append({"game": event, "segment": seg, "sim_total": _dist_mean(hist), "sim_margin": _dist_mean(sb["margin"]),
                         "actual_total": actual, "actual_margin": pair[0] - pair[1], "pit_mid": below + at / 2.0})
    out: dict[str, Any] = {"games": len(games), "overtime_games": ot_games,
                           "overtime_rule": "segment_score_pair('nba'): h2 = periods 3, 4 and every OT; q4 = period 4 alone; "
                                            "full = every period; regulation = periods 1-4",
                           "market_anchor": dict(anchor)}
    for seg in ("full", "regulation", *SEGMENTS):
        sub = [r for r in rows if r["segment"] == seg]
        if not sub:
            continue
        bias = clustered_ci(sub, lambda r: r["sim_total"] - r["actual_total"], reps=reps, seed=seed)
        mbias = clustered_ci(sub, lambda r: r["sim_margin"] - r["actual_margin"], reps=reps, seed=seed)
        pits = [r["pit_mid"] for r in sub]
        out[seg] = {
            "n": len(sub),
            "sim_total_mean": round(sum(r["sim_total"] for r in sub) / len(sub), 2),
            "actual_total_mean": round(sum(r["actual_total"] for r in sub) / len(sub), 2),
            "total_bias": [round(x, 2) for x in bias],
            "total_bias_ci_excludes_0": bool(bias[1] > 0 or bias[2] < 0),
            "margin_bias": [round(x, 2) for x in mbias],
            "actual_total_sd": round(statistics.pstdev(r["actual_total"] for r in sub), 2),
            "pit_outer_20pct": round(sum(1 for p in pits if p < 0.1 or p > 0.9) / len(pits), 3),
        }
    full, sim_full = out.get("full", {}).get("actual_total_mean"), out.get("full", {}).get("sim_total_mean")
    if full and sim_full:
        out["quarter_share"] = {q: {"sim": round(out[q]["sim_total_mean"] / sim_full, 3),
                                    "actual": round(out[q]["actual_total_mean"] / full, 3)}
                                for q in ("q1", "q2", "q3", "q4") if q in out}
    return out


# -------------------------------------------------------------------- main ----
def _parse_frozen(text: str | None) -> dict[str, float] | None:
    if not text:
        return None
    out = {}
    for part in text.split(","):
        key, _, value = part.partition("=")
        if key.strip() not in MARKETS:
            raise SystemExit(f"--frozen-w: unknown family {key!r}")
        out[key.strip()] = float(value)
    missing = set(MARKETS) - set(out)
    if missing:
        raise SystemExit(f"--frozen-w: missing {sorted(missing)}")
    return out


def population_counts(consensus, refused, refused_games, eligible) -> dict[str, Any]:
    by_family_games: dict[str, set[str]] = defaultdict(set)
    by_family_markets: Counter = Counter()
    by_date: dict[str, set[str]] = defaultdict(set)
    mins = []
    seen = set()
    for (event, _seg, market), e in eligible.items():
        by_family_games[market].add(event)
        by_family_markets[market] += 1
        by_date[e["central_date"]].add(event)
        if event not in seen:
            seen.add(event)
            mins.append(e["minutes_before_tip"])
    mins.sort()
    return {
        "segment_markets_quoted": len(consensus),
        "games_quoted": len({k[0] for k in consensus}),
        "refused_markets": dict(sorted(refused.items())),
        "refused_games": dict(sorted(refused_games.items())),
        "eligible_markets": len(eligible),
        "eligible_games": len({k[0] for k in eligible}),
        "eligible_markets_by_family": dict(sorted(by_family_markets.items())),
        "eligible_games_by_family": {m: len(v) for m, v in sorted(by_family_games.items())},
        "eligible_games_by_central_date": {d: len(v) for d, v in sorted(by_date.items())},
        "sim_minutes_before_tip": ({"min": round(mins[0], 1), "median": round(statistics.median(mins), 1),
                                    "max": round(mins[-1], 1)} if mins else None),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--nba-root", required=True, help="read-only copy of the fleet's nba_source")
    ap.add_argument("--quotes", required=True)
    ap.add_argument("--linescores", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--reps", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--tips-from", default=TIPS_FROM)
    ap.add_argument("--tips-to", default=TIPS_TO)
    ap.add_argument("--fit-end", default=FIT_END)
    ap.add_argument("--frozen-w", default=None, help="e.g. totals=0.05,spreads=0,h2h=0: G2 TEST only, no fit")
    ap.add_argument("--count-only", action="store_true", help="population counts only; no box is read or graded")
    args = ap.parse_args(argv)

    root = use_nba_root(Path(args.nba_root))
    bridge = Bridge(root, tips_from=args.tips_from, tips_to=args.tips_to)
    consensus = consensus_markets(iter_quotes(sorted(glob.glob(str(Path(args.quotes) / "*.jsonl*")))))
    frozen = _parse_frozen(args.frozen_w)

    if args.count_only:
        obs, refused, refused_games, eligible = build_observations(consensus, bridge, {}, count_only=True)
        population = population_counts(consensus, refused, refused_games, eligible)
        population["window"] = [args.tips_from, args.tips_to]
        Path(args.out).write_text(json.dumps({"count_only": True, "population": population}, indent=1), encoding="utf-8")
        print(json.dumps({"count_only": True, "population": population}, indent=1))
        return 0

    starts = [_ts(str(c["commence_time"])) for c in consensus.values()]
    lo, hi = max(min(starts), _ts(args.tips_from)) - timedelta(days=1), min(max(starts), _ts(args.tips_to)) + timedelta(days=1)
    dates, day = set(), lo
    while day <= hi:
        dates.add(day.strftime("%Y-%m-%d"))
        day += timedelta(days=1)
    boxes = fetch_linescores(dates, Path(args.linescores))
    obs, refused, refused_games, eligible = build_observations(consensus, bridge, boxes)
    population = population_counts(consensus, refused, refused_games, eligible)
    population.update({"window": [args.tips_from, args.tips_to], "observations": len(obs),
                       "games": len({o["game"] for o in obs}),
                       "dates": len({o["central_date"] for o in obs}),
                       "first_tip": min((o["commence_time"] for o in obs), default=None),
                       "last_tip": max((o["commence_time"] for o in obs), default=None),
                       "whole_number_lines": sum(1 for o in obs if o["market"] != "h2h" and float(o["line"]).is_integer())})
    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "seed": args.seed, "reps": args.reps,
        "population": population,
        "g1": grade(obs, reps=args.reps, seed=args.seed),
        "g2": g2(obs, reps=args.reps, seed=args.seed, fit_end=args.fit_end, frozen=frozen),
        "g3": engine_read(obs, bridge, boxes, reps=args.reps, seed=args.seed),
    }
    Path(args.out).write_text(json.dumps(result, indent=1), encoding="utf-8")
    Path(args.out).with_suffix(".obs.json").write_text(json.dumps(obs), encoding="utf-8")
    print(json.dumps({"population": population, "g1": result["g1"]["families"],
                      "g2": {m: {k: v for k, v in f.items() if k != "fit_curve"} for m, f in result["g2"]["families"].items()}},
                     indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
