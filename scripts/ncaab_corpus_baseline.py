"""NCAAB pbp corpus: the team-model check, the in-game baseline to beat, and the scoring shape.

Lane `ncaab-native-live-tier` (P4 of `docs/ai_context/basketball_live_native_plan.md`).
Reads `scripts/build_ncaab_pbp_corpus.py`'s output; fetches nothing.

WHAT THIS IS NOT: the P4 backtest. That needs the native engine (P1) resumed
from native live state (P2). What it measures is everything that does NOT need
them, so the engine has a bar and a shape to meet when it arrives:

  1. coverage   -- games per phase, pbp-final == official-final, lines, ESPN win
                   probability and directed substitutions present.
  2. pregame    -- the live tier's team model (`ncaab/live_team_model.py`),
                   WALK-FORWARD: each date's ratings come from `compute_ratings`
                   over corpus box rows strictly before that date. Graded against
                   the final and against the DK close (both teams >= 5 games).
  3. checkpoints -- "resume at the prior's rate": projected = current score +
                   prior x remaining/2400. Graded against the FINAL at H1 10:00,
                   halftime, H2 10:00 / 5:00 / 2:00 / 1:00, with n per checkpoint.
                   ML is a normal on the projected margin with sigma x
                   sqrt(remaining share), Brier beside ESPN's own win probability
                   at the same play. The LIVE CLOSE is not in ESPN; it is owed
                   from a separate source and this report says so.
  4. shape      -- second-half-on-first-half margin reversion (NBA real: -0.174,
                   NBA sim: -0.001 -- findings 2026-10-06), scoring rate by margin
                   state in the second half, end-of-game foul rate by trailing
                   margin, and starter on-floor share by minute (the bench
                   intervals the NCAAB rotation windows are priors for).

Regular season and tournament are reported SEPARATELY everywhere; nothing is
pooled across phases (learnings: season-phase populations differ).

    py -3 scripts/ncaab_corpus_baseline.py --season 2026 --json-out report.json
"""

from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from syndicate.features.ncaab import live_team_model as tm  # noqa: E402
from syndicate.features.shared.basketball_league_rules import NCAAB  # noqa: E402

_SPEC = importlib.util.spec_from_file_location("build_ncaab_pbp_corpus", REPO / "scripts" / "build_ncaab_pbp_corpus.py")
corpus = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(corpus)  # type: ignore[union-attr]
ratings = corpus.ratings

FOUL_TYPE = 519
REG = NCAAB.regulation_seconds
CHECKPOINTS = {  # name -> regulation seconds elapsed
    "H1_10:00": 600,
    "half": 1200,
    "H2_10:00": 1800,
    "H2_5:00": 2100,
    "H2_2:00": 2280,
    "H2_1:00": 2340,
}
MIN_GAMES = 5
PHASE_GROUPS = {"regular": ("regular",), "conf_tournament": ("conf_tournament",), "ncaa_tournament": ("ncaa_tournament",), "other_postseason": ("other_postseason",)}


# ------------------------------------------------------------------ helpers

def _phi(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _stats(errors: list[float]) -> dict[str, Any]:
    if not errors:
        return {"n": 0}
    return {
        "n": len(errors),
        "bias": round(statistics.fmean(errors), 3),
        "mae": round(statistics.fmean(abs(e) for e in errors), 3),
        "rmse": round(math.sqrt(statistics.fmean(e * e for e in errors)), 3),
    }


def _ols_slope(xs: list[float], ys: list[float]) -> dict[str, Any]:
    n = len(xs)
    if n < 3:
        return {"n": n}
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    slope = sxy / sxx if sxx else float("nan")
    resid = [y - my - slope * (x - mx) for x, y in zip(xs, ys)]
    se = math.sqrt(sum(r * r for r in resid) / (n - 2) / sxx) if sxx and n > 2 else float("nan")
    return {"n": n, "slope": round(slope, 4), "se": round(se, 4), "ci95": [round(slope - 1.96 * se, 4), round(slope + 1.96 * se, 4)]}


_PLAYS: dict[str, list[dict[str, Any]]] = {}


def plays_of(record: Mapping[str, Any]) -> list[dict[str, Any]]:
    key = str(record.get("game_id"))
    if key in _PLAYS:
        return _PLAYS[key]
    _PLAYS[key] = _parse_plays(record)
    return _PLAYS[key]


def _parse_plays(record: Mapping[str, Any]) -> list[dict[str, Any]]:
    cols = record["plays_cols"]
    out = []
    for row in record["plays"]:
        play = dict(zip(cols, row))
        if play["period"] is None or play["clock"] is None:
            continue
        play["elapsed"] = NCAAB.elapsed_seconds(play["period"], play["clock"])
        out.append(play)
    return out


def state_at(plays: list[dict[str, Any]], elapsed: float) -> dict[str, Any] | None:
    """The last play at or before `elapsed` with a score."""
    best = None
    for play in plays:
        if play["elapsed"] > elapsed + 1e-9:
            break
        if play["home"] is not None and play["away"] is not None:
            best = play
    return best


# ---------------------------------------------------------- walk-forward model

def walk_forward_priors(records: list[dict[str, Any]]) -> dict[str, tm.NcaabGamePrior | tm.NcaabPriorRefusal]:
    d1 = ratings.load_registry()
    by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in records:
        by_date[r["date"]].append(r)
    out: dict[str, Any] = {}
    seen_rows: list[dict[str, Any]] = []
    for day in sorted(by_date):
        if seen_rows:
            table_ratings = ratings.compute_ratings(seen_rows, d1)
            table = tm.table_from_rows(
                ({**v, "espn_id": k, "team": d1.get(k, k)} for k, v in table_ratings.items()),
                season=records[0]["season"],
                as_of=dt.date.fromisoformat(day) - dt.timedelta(days=1),
                source=f"computed:walk_forward<{day}",
            )
        else:
            table = None
        for r in by_date[day]:
            if table is None:
                out[r["game_id"]] = tm.NcaabPriorRefusal("no_ratings_table", "first date")
            else:
                out[r["game_id"]] = tm.game_prior(table, r["home"]["id"], r["away"]["id"], neutral=r["neutral"])
        for r in by_date[day]:
            seen_rows.extend(r.get("box_rows") or [])
    return out


# ------------------------------------------------------------------ sections

def coverage(records: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for phase in PHASE_GROUPS:
        rs = [r for r in records if r["phase"] == phase]
        if not rs:
            continue
        out[phase] = {
            "games": len(rs),
            "dates": len({r["date"] for r in rs}),
            "first": min(r["date"] for r in rs),
            "last": max(r["date"] for r in rs),
            "pbp_final_matches": sum(1 for r in rs if r["check"]["pbp_final_matches"]),
            "with_close_total": sum(1 for r in rs if (r.get("lines") or {}).get("total_close") is not None),
            "with_close_spread": sum(1 for r in rs if (r.get("lines") or {}).get("spread_home_close") is not None),
            "with_espn_wp": sum(1 for r in rs if r["check"]["n_wp"] > 0),
            "with_directed_subs": sum(1 for r in rs if r["check"]["n_subs"] > 0 and r["check"].get("n_subs_undirected", 0) == 0),
            "overtime": sum(1 for r in rs if len(r["home"]["linescores"]) > 2),
        }
    return out


def _usable(prior: Any) -> bool:
    return isinstance(prior, tm.NcaabGamePrior) and prior.home_games >= MIN_GAMES and prior.away_games >= MIN_GAMES


def pregame(records: list[dict[str, Any]], priors: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    refusals: dict[str, int] = defaultdict(int)
    for phase in PHASE_GROUPS:
        rs = [r for r in records if r["phase"] == phase]
        tot_model, tot_close, mar_model, mar_close, both_tot = [], [], [], [], []
        for r in rs:
            prior = priors.get(r["game_id"])
            if isinstance(prior, tm.NcaabPriorRefusal):
                refusals[prior.reason] += 1
                continue
            if not _usable(prior):
                refusals["fewer_than_min_games"] += 1
                continue
            final_total = r["home"]["score"] + r["away"]["score"]
            final_margin = r["home"]["score"] - r["away"]["score"]
            tot_model.append(prior.total - final_total)
            mar_model.append(prior.home_margin - final_margin)
            lines = r.get("lines") or {}
            if lines.get("total_close") is not None:
                tot_close.append(lines["total_close"] - final_total)
                both_tot.append((prior.total, lines["total_close"], final_total))
            if lines.get("spread_home_close") is not None:
                mar_close.append(-lines["spread_home_close"] - final_margin)
        if not tot_model:
            continue
        over_hit = None
        if both_tot:
            # When the model disagrees with the close by >= 3 points, which side did the final land on?
            picks = [(m > c) == (f > c) for m, c, f in both_tot if abs(m - c) >= 3 and f != c]
            over_hit = {"n": len(picks), "model_side_hit_rate": round(sum(picks) / len(picks), 4) if picks else None}
        out[phase] = {
            "total_model_minus_final": _stats(tot_model),
            "total_close_minus_final": _stats(tot_close),
            "margin_model_minus_final": _stats(mar_model),
            "margin_close_minus_final": _stats(mar_close),
            "model_vs_close_disagreement_ge3": over_hit,
        }
    out["refusals_all_phases"] = dict(refusals)
    return out


def checkpoints(records: list[dict[str, Any]], priors: Mapping[str, Any], sigma: float) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for phase in PHASE_GROUPS:
        rs = [r for r in records if r["phase"] == phase and _usable(priors.get(r["game_id"]))]
        if not rs:
            continue
        section: dict[str, Any] = {}
        for name, cp in CHECKPOINTS.items():
            tot_err, mar_err, brier_model, brier_espn, n_wp = [], [], [], [], 0
            for r in rs:
                prior = priors[r["game_id"]]
                state = state_at(plays_of(r), cp)
                if state is None:
                    continue
                rem_share = max(0.0, (REG - cp) / REG)
                proj_total = state["home"] + state["away"] + prior.total * rem_share
                proj_margin = state["home"] - state["away"] + prior.home_margin * rem_share
                final_total = r["home"]["score"] + r["away"]["score"]
                final_margin = r["home"]["score"] - r["away"]["score"]
                tot_err.append(proj_total - final_total)
                mar_err.append(proj_margin - final_margin)
                home_won = 1.0 if final_margin > 0 else 0.0
                p_model = _phi(proj_margin / (sigma * math.sqrt(rem_share))) if rem_share > 0 else float(proj_margin > 0)
                if state.get("wp_home") is not None:
                    n_wp += 1
                    brier_model.append((p_model - home_won) ** 2)
                    brier_espn.append((float(state["wp_home"]) - home_won) ** 2)
            section[name] = {
                "n": len(tot_err),
                "total_projection_minus_final": _stats(tot_err),
                "margin_projection_minus_final": _stats(mar_err),
                "ml_brier_paired_with_espn": {
                    "n": n_wp,
                    "baseline": round(statistics.fmean(brier_model), 4) if brier_model else None,
                    "espn_wp": round(statistics.fmean(brier_espn), 4) if brier_espn else None,
                },
                "live_close": "NOT AVAILABLE: ESPN carries pregame lines only; the live close needs OddsAPI historical in-play snapshots",
            }
        out[phase] = section
    return out


def shape(records: list[dict[str, Any]], priors: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for phase in PHASE_GROUPS:
        rs = [r for r in records if r["phase"] == phase and _usable(priors.get(r["game_id"])) and len(r["home"]["linescores"]) >= 2]
        if len(rs) < 30:
            continue
        # 1. reversion: H2 margin residual on H1 margin residual (prior split evenly by half)
        xs, ys = [], []
        for r in rs:
            prior = priors[r["game_id"]]
            h1 = (r["home"]["linescores"][0] or 0) - (r["away"]["linescores"][0] or 0)
            h2 = (r["home"]["linescores"][1] or 0) - (r["away"]["linescores"][1] or 0)
            xs.append(h1 - prior.home_margin / 2)
            ys.append(h2 - prior.home_margin / 2)
        # 2. second-half scoring rate by margin state, relative to the prior's per-minute rate
        rate_by_margin: dict[str, list[float]] = defaultdict(list)
        # 3. end-of-game fouls per minute, trailing vs leading team, by margin, last 2:00 and 4:00-2:00
        fouls: dict[tuple[str, str, str], float] = defaultdict(float)
        foul_minutes: dict[tuple[str, str], float] = defaultdict(float)
        # 4. starter on-floor share by regulation minute
        starter_on: dict[int, list[float]] = defaultdict(list)
        for r in rs:
            prior = priors[r["game_id"]]
            plays = plays_of(r)
            per_min = prior.total / 40.0
            for start in range(1200, 2400, 120):
                a, b = state_at(plays, start), state_at(plays, start + 120)
                if a is None or b is None:
                    continue
                m = abs(a["home"] - a["away"])
                bucket = "0-5" if m <= 5 else "6-10" if m <= 10 else "11-19" if m <= 19 else "20+"
                rate_by_margin[bucket].append(((b["home"] + b["away"]) - (a["home"] + a["away"])) / 2.0 / per_min)
            for window, lo, hi in (("last_2:00", 2280, 2400), ("4:00-2:00", 2160, 2280)):
                a = state_at(plays, lo)
                if a is None:
                    continue
                m = a["home"] - a["away"]
                if m == 0:
                    continue
                am = abs(m)
                bucket = "1-3" if am <= 3 else "4-6" if am <= 6 else "7-10" if am <= 10 else "11+"
                trailing = "a" if m > 0 else "h"
                foul_minutes[(window, bucket)] += (hi - lo) / 60.0
                for p in plays:
                    if lo < p["elapsed"] <= hi and p["type"] == FOUL_TYPE and p["team"] in ("h", "a"):
                        fouls[(window, bucket, "trailing" if p["team"] == trailing else "leading")] += 1
            share = starter_share_by_minute(r, plays)
            for minute, value in share.items():
                starter_on[minute].append(value)
        rate = {k: {"n": len(v), "rate_vs_prior": round(statistics.fmean(v), 4)} for k, v in sorted(rate_by_margin.items())}
        foul_rates = {}
        for (window, bucket), minutes in sorted(foul_minutes.items()):
            foul_rates[f"{window} margin {bucket}"] = {
                "team_minutes": round(minutes, 1),
                "trailing_fouls_per_min": round(fouls[(window, bucket, "trailing")] / minutes, 3),
                "leading_fouls_per_min": round(fouls[(window, bucket, "leading")] / minutes, 3),
            }
        out[phase] = {
            "games": len(rs),
            "h2_on_h1_margin_reversion": {**_ols_slope(xs, ys), "nba_real": -0.174, "nba_sim": -0.001},
            "h2_scoring_rate_by_margin_vs_prior": rate,
            "end_game_fouls": foul_rates,
            "starter_on_floor_share_by_minute": {m: round(statistics.fmean(v), 3) for m, v in sorted(starter_on.items()) if v},
        }
    return out


def starter_share_by_minute(record: Mapping[str, Any], plays: list[dict[str, Any]]) -> dict[int, float]:
    """Share of the 10 starters on the floor at each regulation minute (0..39), from directed subs.

    H1 opens with the box-score starters. Each half after that: a player whose
    first sub event in the half is OUT was on the floor at its start, IN was
    not; no event carries the previous half's end state. Undirected subs void
    the game (returns {}).
    """
    if record["check"].get("n_subs_undirected"):
        return {}
    starters = {(side, pid) for side, pid, starter, *_ in record.get("players") or [] if starter and pid}
    if len(starters) != 10:
        return {}
    events = [(p["elapsed"], p["period"], p["team"], p["athlete"], p["sub"]) for p in plays if p.get("sub") in (1, -1) and p["athlete"] and p["team"]]
    on: dict[tuple[str, str], bool] = {s: True for s in starters}
    intervals: dict[tuple[str, str], list[tuple[float, float]]] = defaultdict(list)
    since: dict[tuple[str, str], float] = {s: 0.0 for s in starters}
    for period in (1, 2):
        start = (period - 1) * 1200.0
        end = period * 1200.0
        half = [e for e in events if e[1] == period]
        if period == 2:
            for s in starters:
                first = next((e[4] for e in half if (e[2], e[3]) == s), None)
                state = on[s] if first is None else first == -1
                if on[s]:
                    intervals[s].append((since[s], start))
                on[s] = state
                since[s] = start
        for elapsed, _period, side, pid, direction in half:
            s = (side, pid)
            if s not in starters:
                continue
            if direction == -1 and on[s]:
                intervals[s].append((since[s], elapsed))
                on[s] = False
            elif direction == 1 and not on[s]:
                on[s] = True
                since[s] = elapsed
        if period == 2:
            for s in starters:
                if on[s]:
                    intervals[s].append((since[s], end))
    share: dict[int, float] = {}
    for minute in range(40):
        t = minute * 60 + 30
        n_on = sum(1 for s in starters for a, b in intervals[s] if a <= t < b)
        share[minute] = n_on / 10.0
    return share


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--season", type=int, default=2026)
    parser.add_argument("--json-out", type=Path, default=None)
    args = parser.parse_args(argv)
    path = corpus.corpus_path(args.season)
    records = [r for r in corpus.read_records(path) if r.get("v") == corpus.RECORD_VERSION]
    if not records:
        print(f"[ncaab_corpus_baseline] NO_CORPUS path={path}", flush=True)
        return 2
    records.sort(key=lambda r: (r["date"], r["game_id"]))
    priors = walk_forward_priors(records)
    pre = pregame(records, priors)
    sigma = (pre.get("regular") or {}).get("margin_model_minus_final", {}).get("rmse") or 11.2
    report = {
        "substrate": f"local corpus {path} (ESPN summary, fetched by build_ncaab_pbp_corpus.py)",
        "season": args.season,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "coverage": coverage(records),
        "pregame": pre,
        "ml_sigma_points": sigma,
        "ml_sigma_note": "the regular season's pregame margin RMSE, in-sample; a baseline constant, not a fit",
        "checkpoints": checkpoints(records, priors, sigma),
        "shape": shape(records, priors),
    }
    text = json.dumps(report, indent=2)
    if args.json_out:
        args.json_out.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
