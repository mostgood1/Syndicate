"""College basketball TOTALS PROBABILITY CALIBRATION, per line (lane ncaab-total-overprojection, todo #816; user
2026-11-16, after FAMU @ UTEP went 125 against an over 136.5 the board flagged: "I need you to understand, learn, and
optimize based on this", then "Spread + level").

WHAT IT CHANGES. Every college full-game TOTAL line's served P(over), pregame and live:

    logit p = logit p_mkt + a + c * (logit p_raw - logit p_mkt)

`p_mkt` is that line's de-vigged market probability, `p_raw` the engine's own (the sim histogram pregame; the live
re-sim's, after the point estimator and the #780 scale). `c` (SPREAD) is the share of the model's disagreement with
the market that has paid off; `a` (LEVEL) is how far finals have landed from the lines. Both are FITTED on graded
games over a trailing window and refit once a day, one pair per league and phase, and stamped on every row they
touch. No market or side is switched off: every line keeps its own probability (user rule, memory
`feedback-every-line-its-own-decision`); a line shows an edge only when its calibrated probability beats its price.

WHY (`.syndicate/findings_2026-11-16_ncaab_total_overprojection.md`, NCAAB, fleet, 11-02..11-16):
  * pregame: (final - close) on (model - close) has slope 0.017 +- 0.129 over 621 games -- the sim's distance from the
    close carries no information -- and finals landed 2.2 +- 0.8 under the close. Totals were served raw while
    margins were already book-blended at weight 0 for the same finding (`college_game_projections._served`).
  * live: the same slope is 0.42 +- 0.09 (874 game-buckets), but the board's priceable OVER rows (|edge| >= 3) hit
    0.472 over 129 games and the UNDER rows 0.707 over 131; finals landed ~2 points under the live line even where
    the model agreed with it. FAMU @ UTEP's 2nd-half flag was a 0.7-point disagreement read as +7 pp.
  * walk-forward (fit on earlier dates, score the next), floor 11-11: live Brier market 0.2345, raw 0.2423,
    calibrated 0.2263 (58 game-weights, 11-14..16); pregame 0.2500 / 0.2798 / 0.2407 (174 games, 11-12..16).

THE LEVEL IS A BET THAT FINALS KEEP LANDING WHERE THEY HAVE (user's choice, "Spread + level"). It is refit daily on
a trailing window, so it follows the season; its fitted standard error rides into the live precision gate, so a level
the data barely supports cannot by itself clear the gate.

ESTIMATOR, NOT MECHANISM (`model_engine_standard.md`): the engine, its priors and every rate fitted on it are
untouched; only the served probability moves, and the engine's own number is kept beside it
(`model_prob_uncalibrated` live, `p_model_raw` pregame).

SWITCH: `SYNDICATE_COLLEGE_TOTAL_CALIBRATION=off` (0 / false / no) serves every line raw, as before; absent = on.
A league or phase with fewer than MIN_GAMES graded games in the window writes an UNCALIBRATED entry and is served
raw by name. `scripts/fit_college_total_calibration.py` runs the fit by hand and prints the walk-forward.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import os
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Sequence

PHASES = ("pregame", "live")
LEAGUES = ("ncaab", "wncaab")
WINDOW_DAYS = 21
# The first full slate on today's engine: the #768 blowout fix loaded 11-09 05:13Z and RC46 was on, then reverted,
# through 11-10 (learnings 2026-11-11). Rows before it describe a different engine.
FIT_FLOOR = dt.date(2026, 11, 11)
MIN_GAMES = 60
A_RANGE = (-0.6, 0.6)      # logit units: +-0.6 moves a 0.50 line to 0.354 / 0.646
C_RANGE = (0.0, 1.0)       # 1.0 = trust the model's whole disagreement, as served today
RIDGE = 1.0                # on `a`, in game-weight units: a level needs games before it moves
EPS = 0.01
ENV_SWITCH = "SYNDICATE_COLLEGE_TOTAL_CALIBRATION"
_FILE_RE = re.compile(r"total_prob_calibration_(\d{4})_asof_(\d{8})\.json$")


def enabled(env: Optional[Mapping[str, str]] = None) -> bool:
    raw = str((env if env is not None else os.environ).get(ENV_SWITCH) or "").strip().lower()
    return raw not in {"0", "off", "false", "no"}


def _logit(p: float) -> float:
    q = min(1.0 - EPS, max(EPS, float(p)))
    return math.log(q / (1.0 - q))


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


@dataclass(frozen=True)
class TotalCalibration:
    league: str
    phase: str
    as_of: dt.date
    a: float
    c: float
    var_a: float = 0.0
    var_c: float = 0.0
    cov_ac: float = 0.0
    games: float = 0.0
    source: str = ""

    def apply(self, p_raw: float, p_mkt: float) -> float:
        lm = _logit(p_mkt)
        return _sigmoid(lm + self.a + self.c * (_logit(p_raw) - lm))

    def std_err(self, p_raw: float, p_mkt: float, sim_std_err: float) -> float:
        """The calibrated probability's error: the sim's own, carried through c (delta method), plus the fit's
        uncertainty in a and c at this line's disagreement x."""
        p_cal = self.apply(p_raw, p_mkt)
        q = min(1.0 - EPS, max(EPS, float(p_raw)))
        slope = p_cal * (1.0 - p_cal)
        sim_part = float(sim_std_err) * self.c * slope / (q * (1.0 - q))
        x = _logit(p_raw) - _logit(p_mkt)
        fit_var = max(0.0, self.var_a + x * x * self.var_c + 2.0 * x * self.cov_ac)
        return math.sqrt(sim_part ** 2 + (slope ** 2) * fit_var)

    def stamp(self) -> dict[str, Any]:
        return {"phase": self.phase, "as_of": self.as_of.isoformat(), "a": round(self.a, 4), "c": round(self.c, 4),
                "games": round(self.games, 1), "source": self.source}


# ------------------------------------------------------------------------------------------------ the fit

def fit(rows: Sequence[tuple[float, float, float, float]]) -> dict[str, Any]:
    """Weighted logistic with offset: y ~ sigmoid(off + a + c*x), rows (x, off, y, w). Newton; ridge RIDGE on a, a
    whisper on c. Returns a, c, their covariance (inverse Hessian, game-weight units) and the clamps applied."""
    a, c = 0.0, 0.5
    h_aa = h_ac = h_cc = 0.0
    for _ in range(60):
        g_a = g_c = h_aa = h_ac = h_cc = 0.0
        for x, off, y, w in rows:
            p = _sigmoid(off + a + c * x)
            r, v = (y - p) * w, p * (1.0 - p) * w
            g_a += r
            g_c += r * x
            h_aa += v
            h_ac += v * x
            h_cc += v * x * x
        g_a -= RIDGE * a
        h_aa += RIDGE
        g_c -= 0.01 * c
        h_cc += 0.01
        det = h_aa * h_cc - h_ac * h_ac
        if det <= 0.0:
            break
        da, dc = (h_cc * g_a - h_ac * g_c) / det, (h_aa * g_c - h_ac * g_a) / det
        a, c = a + da, c + dc
        if abs(da) + abs(dc) < 1e-10:
            break
    det = h_aa * h_cc - h_ac * h_ac
    var_a, var_c, cov = (h_cc / det, h_aa / det, -h_ac / det) if det > 0 else (0.0, 0.0, 0.0)
    clamped: list[str] = []
    if not A_RANGE[0] <= a <= A_RANGE[1]:
        clamped.append(f"a {a:.3f}")
        a = min(A_RANGE[1], max(A_RANGE[0], a))
    if not C_RANGE[0] <= c <= C_RANGE[1]:
        clamped.append(f"c {c:.3f}")
        c = min(C_RANGE[1], max(C_RANGE[0], c))
    return {"a": a, "c": c, "var_a": var_a, "var_c": var_c, "cov_ac": cov, "clamped": clamped,
            "games": sum(w for *_, w in rows), "rows": len(rows)}


def brier(rows: Sequence[tuple[float, float, float, float]], a: float, c: float) -> dict[str, float]:
    tot = {"market": 0.0, "raw": 0.0, "calibrated": 0.0}
    weight = sum(w for *_, w in rows)
    for x, off, y, w in rows:
        tot["market"] += w * (_sigmoid(off) - y) ** 2
        tot["raw"] += w * (_sigmoid(off + x) - y) ** 2
        tot["calibrated"] += w * (_sigmoid(off + a + c * x) - y) ** 2
    return {k: round(v / weight, 5) for k, v in tot.items()} | {"games": round(weight, 1)} if weight else {"games": 0.0}


MIN_WALK_FORWARD_GAMES = 40.0


def _walk_forward_verdict(wf: Mapping[str, Any]) -> Optional[str]:
    """None when the phase may be served; else the reason it is not."""
    games = float(wf.get("games") or 0.0)
    if games < MIN_WALK_FORWARD_GAMES:
        return f"walk-forward scored {games:.0f} games < {MIN_WALK_FORWARD_GAMES:.0f}"
    cal, raw, market = wf.get("calibrated"), wf.get("raw"), wf.get("market")
    if cal is None or raw is None or market is None:
        return "walk-forward has no score"
    if cal >= raw:
        return f"walk-forward Brier {cal} did not beat the raw model's {raw}"
    if cal > market:
        return f"walk-forward Brier {cal} is worse than the market's {market}"
    return None


def walk_forward(by_date: Mapping[str, Sequence[tuple[float, float, float, float]]], *, min_train: float = 40.0) -> dict[str, Any]:
    """Fit on every earlier date, score the next; pooled Brier over the scored dates (game-weighted)."""
    dates = sorted(by_date)
    pooled = {"market": 0.0, "raw": 0.0, "calibrated": 0.0}
    weight = 0.0
    steps = []
    for i, day in enumerate(dates):
        train = [row for d in dates[:i] for row in by_date[d]]
        if sum(w for *_, w in train) < min_train or not by_date[day]:
            continue
        f = fit(train)
        b = brier(by_date[day], f["a"], f["c"])
        w = b["games"]
        for k in pooled:
            pooled[k] += b[k] * w
        weight += w
        steps.append({"date": day, "a": round(f["a"], 4), "c": round(f["c"], 4), **b})
    return {"steps": steps, "games": round(weight, 1),
            **({k: round(v / weight, 5) for k, v in pooled.items()} if weight else {})}


# ------------------------------------------------------------------------------------------------ fit rows

def _finals(league: str, day: str) -> tuple[dict[tuple[str, str], float], dict[str, float]]:
    """(join-key pair -> final total, event id -> final total) for the slate's FINAL games."""
    from syndicate.features.ncaab import live_resim as lr
    from syndicate.features.ncaab.slate import read_slate

    by_key: dict[tuple[str, str], float] = {}
    by_eid: dict[str, float] = {}
    for game in (read_slate(day, league) or {}).get("games") or []:
        if not bool((game.get("live_state") or {}).get("final")):
            continue
        home, away = game.get("home") or {}, game.get("away") or {}
        hs, as_ = home.get("score"), away.get("score")
        if not isinstance(hs, (int, float)) or not isinstance(as_, (int, float)):
            continue
        total = float(hs + as_)
        by_key[(lr._join_key(league, home.get("name")), lr._join_key(league, away.get("name")))] = total
        by_eid[str(game.get("event_id") or "")] = total
    return by_key, by_eid


def live_fit_rows(league: str, day: str) -> list[tuple[float, float, float, float]]:
    """One day's live full-game total ledger rows as (x, offset, y, w); each game's rows weigh 1 in all. The fit reads
    the ENGINE's number: `model_home_win_prob_uncalibrated` where this calibration was applied, else the served one;
    a calibrated row without its raw number is skipped, never refit on its own output."""
    from syndicate.features.ncaab import live_resim as lr
    from syndicate.features.shared.live_gameline_ledger import ledger_path, read_records

    finals, _ = _finals(league, day)
    per_game: dict[tuple[str, str], list[tuple[float, float, float]]] = {}
    for rec in read_records(ledger_path(league, day)):
        if rec.get("market") != "totals" or str(rec.get("segment") or "") not in ("full", "full_game") or rec.get("line") is None:
            continue
        p_raw = rec.get("model_home_win_prob_uncalibrated")
        if p_raw is None:
            if rec.get("total_cal"):
                continue
            p_raw = rec.get("model_home_win_prob")
        p_mkt = rec.get("market_fair_prob_over")
        if p_raw is None or p_mkt is None or not 0.0 < float(p_mkt) < 1.0:
            continue
        key = (lr._join_key(league, rec.get("home_team")), lr._join_key(league, rec.get("away_team")))
        total = finals.get(key) or finals.get((key[1], key[0]))
        line = float(rec["line"])
        if total is None or total == line:
            continue
        per_game.setdefault(key, []).append((_logit(p_raw) - _logit(p_mkt), _logit(p_mkt), 1.0 if total > line else 0.0))
    out: list[tuple[float, float, float, float]] = []
    for rows in per_game.values():
        out += [(x, off, y, 1.0 / len(rows)) for x, off, y in rows]
    return out


def pregame_fit_rows(league: str, day: str) -> list[tuple[float, float, float, float]]:
    """One row per graded game at its CLOSE (each book's last pre-tip over line, median): p_raw = the sim's P(total >
    close), p_mkt = 0.5 (the close is the market's median), outcome final > close; pushes dropped."""
    from syndicate.features.college_basketball.pregame_sim import read_pregame_sims
    from syndicate.features.college_basketball.prior_calibration import closing_totals
    from syndicate.features.ncaab import live_resim as lr
    from syndicate.features.shared.prop_projections import _dist_prob_over

    _, finals = _finals(league, day)
    closes = closing_totals(league, day)
    out: list[tuple[float, float, float, float]] = []
    for event_id, game in ((read_pregame_sims(day, league) or {}).get("games") or {}).items():
        total = finals.get(str(event_id))
        dist = (((game.get("dist") or {}).get("segments") or {}).get("full") or {}).get("total")
        if total is None or not isinstance(dist, Mapping) or not dist:
            continue
        hk = lr._join_key(league, (game.get("home") or {}).get("name"))
        ak = lr._join_key(league, (game.get("away") or {}).get("name"))
        close = closes.get((hk, ak)) or closes.get((ak, hk))
        if close is None or float(close[0]) == total:
            continue
        p_raw = _dist_prob_over(dist, float(close[0]))
        if p_raw is None:
            continue
        out.append((_logit(p_raw), 0.0, 1.0 if total > float(close[0]) else 0.0, 1.0))
    return out


# ------------------------------------------------------------------------------------------------ files

def calibration_path(league: str, season: int, as_of: dt.date) -> Path:
    from syndicate.features.college_basketball.prior_calibration import processed_dir

    return processed_dir(league) / f"total_prob_calibration_{season}_asof_{as_of:%Y%m%d}.json"


def refresh(league: str, *, today: dt.date, window_days: int = WINDOW_DAYS, floor: dt.date = FIT_FLOOR,
            write: bool = True) -> dict[str, Any]:
    """Fit both phases on this season's games dated max(floor, today - window_days) .. today - 1; write the file
    every game dated after that reads."""
    from syndicate.features.ncaab import live_team_model as tm

    as_of = today - dt.timedelta(days=1)
    season = tm.espn_season_for(today)
    first = max(floor, as_of - dt.timedelta(days=window_days - 1))
    dates = []
    day = first
    while day <= as_of:
        if tm.espn_season_for(day) == season:
            dates.append(day.isoformat())
        day += dt.timedelta(days=1)
    payload: dict[str, Any] = {"league": league, "season": season, "as_of": as_of.isoformat(),
                               "window": [dates[0], dates[-1]] if dates else [], "phases": {},
                               "fitted_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    for phase, builder in (("pregame", pregame_fit_rows), ("live", live_fit_rows)):
        by_date = {d: builder(league, d) for d in dates}
        rows = [row for d in dates for row in by_date[d]]
        games = sum(w for *_, w in rows)
        if games < MIN_GAMES:
            payload["phases"][phase] = {"calibrated": False, "reason": f"{games:.0f} graded games < {MIN_GAMES}", "games": round(games, 1)}
        else:
            f = fit(rows)
            wf = walk_forward(by_date)
            entry = {**{k: (round(v, 6) if isinstance(v, float) else v) for k, v in f.items()},
                     "in_sample": brier(rows, f["a"], f["c"]), "walk_forward": wf}
            # SELF-GATED ON OUTCOMES (learnings 2026-11-11: a served-distribution change is judged on outcomes): the
            # phase is served only when, fitted on earlier dates and scored on the next, it beat the engine's own number
            # and was no worse than the market. The fitted values stay in the file either way, for the record.
            verdict = _walk_forward_verdict(wf)
            payload["phases"][phase] = {"calibrated": verdict is None, **entry, **({"reason": verdict} if verdict else {})}
        entry = payload["phases"][phase]
        print(f"[college_total_calibration] FIT league={league} phase={phase} as_of={as_of} games={entry.get('games')} "
              + (f"a={entry['a']:+.4f} c={entry['c']:.4f}" + (f" clamped={','.join(entry['clamped'])}" if entry.get("clamped") else "")
                 if "a" in entry else "")
              + ("" if entry.get("calibrated") else f" UNCALIBRATED reason={entry.get('reason')!r}"), flush=True)
    if write:
        path = calibration_path(league, season, as_of)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        tmp.replace(path)
        payload["written"] = str(path)
    return payload


_LOCK = threading.Lock()
_PARSED: dict[str, tuple[int, Mapping[str, Any]]] = {}
_LISTING: dict[tuple[str, int], tuple[float, dict[dt.date, Path]]] = {}
_LISTING_TTL_SECONDS = 60.0


def calibration_for(league: str, phase: str, game_date: dt.date, *, env: Optional[Mapping[str, str]] = None,
                    directory: Optional[Path] = None) -> Optional[TotalCalibration]:
    """The newest fit of `game_date`'s season dated strictly before it, for one phase; None when switched off, when
    there is no file, or when that phase is uncalibrated or unreadable (served raw, as before)."""
    if not enabled(env) or phase not in PHASES:
        return None
    from syndicate.features.college_basketball.prior_calibration import processed_dir
    from syndicate.features.ncaab import live_team_model as tm

    season = tm.espn_season_for(game_date)
    root = Path(directory) if directory is not None else processed_dir(league)
    # The live join asks once per ROW; the listing is cached briefly so a board build globs the directory once.
    listing_key = (str(root), season)
    now = time.monotonic()
    with _LOCK:
        cached = _LISTING.get(listing_key)
    if cached is not None and now - cached[0] < _LISTING_TTL_SECONDS:
        listing = cached[1]
    else:
        listing = {}
        if root.is_dir():
            for path in root.glob(f"total_prob_calibration_{season}_asof_*.json"):
                match = _FILE_RE.search(path.name)
                if match:
                    listing[dt.datetime.strptime(match.group(2), "%Y%m%d").date()] = path
        with _LOCK:
            _LISTING[listing_key] = (now, listing)
    found = {as_of: path for as_of, path in listing.items() if as_of < game_date}
    if not found:
        return None
    path = found[max(found)]
    try:
        mtime = path.stat().st_mtime_ns
    except OSError:
        return None
    with _LOCK:
        hit = _PARSED.get(str(path))
    if hit is None or hit[0] != mtime:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        with _LOCK:
            _PARSED[str(path)] = (mtime, payload)
    else:
        payload = hit[1]
    entry = ((payload.get("phases") or {}).get(phase)) or {}
    if not entry.get("calibrated"):
        return None
    try:
        return TotalCalibration(league=league, phase=phase, as_of=max(found), a=float(entry["a"]), c=float(entry["c"]),
                                var_a=float(entry.get("var_a") or 0.0), var_c=float(entry.get("var_c") or 0.0),
                                cov_ac=float(entry.get("cov_ac") or 0.0), games=float(entry.get("games") or 0.0),
                                source=path.name)
    except (KeyError, TypeError, ValueError):
        return None
