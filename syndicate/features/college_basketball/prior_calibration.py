"""College basketball PRIOR CALIBRATION (lane wncaab-module; user 2026-11-03 "College model fit").

WHY. The team prior (`ncaab/live_team_model.prior_for_game`) is what the engine is TOLD to produce: with the exact
target on, the pregame sim reproduces it within about a point (measured 2026-11-03 on the fleet, sim mean on prior:
men slope 0.94 over 129 games; the women's engine narrows only blowouts past 25 points, by ~6). So a sim that is
off the market is a prior that is off the market, and the prior is what gets fitted. Measured:

  * 2026-11-02/03 opener, men, against the closing line (135 games): close = 1.115 x prior margin + 2.25 at a home
    site, and close total = 0.72 x prior total (centred): opening-week margins too narrow, totals too spread out.
  * 2025-26 walk-forward against finals (ratings from games strictly before each date, both teams >= 5 games;
    fitted Nov-Jan, judged Feb-Apr, ~4,600 games a league): men's margins already right (1.007, the ratings
    builder's own MARGIN_CALIBRATION_K fit); men's totals spread out (0.70) and ~1.5 points low; women's margins
    12-19% too narrow (they carry the men's K); women's totals 0.80.

THE FIT, one per league, refitted daily over a trailing window of this season's games:

    margin' = beta * margin + gamma * [home site]          (no intercept: a neutral game has no home side)
    total'  = target_mean + slope * (total - prior_mean)

ESTIMATOR, NOT MECHANISM (`model_engine_standard.md`). Only the prior's mean margin and total move --
`home_points` / `away_points` are re-derived from them, possessions stay -- so the engine, its mechanisms and every
rate fitted on it are untouched. Pregame and live sims read the same calibrated prior, so the live margin anchor
(`live_resim.margin_anchor_for`, close minus pregame sim) compares like with like.

TARGET. The closing line (`live_resim.closing_home_margin` and `closing_totals` here: the median of each book's last
quote before the listed tip), the lowest-noise estimate of the expected outcome. A league with fewer than
MIN_CLOSES closes in the window (the women's feed prices ~14 games a day) fits on finals instead, given
MIN_FINALS; fewer than that writes an UNCALIBRATED file and the prior is served raw, by name. Fitted values outside
the guard ranges are clamped, and the clamp is recorded.

NO LEAKAGE. `prior_calibration_<season>_asof_<YYYYMMDD>.json` is fitted on games dated <= as_of and applies only to
games dated strictly AFTER it, within the same season (the ratings tables' rule). The newest such file wins, an
UNCALIBRATED one included: an older fit is never resurrected.

SWITCH. SYNDICATE_COLLEGE_PRIOR_CALIBRATION: absent = ON; 0/false/off/no = the raw prior everywhere.

Refreshed once a day by the pregame child (`scripts/build_college_pregame_sims.py --refresh-inputs`);
`scripts/fit_college_prior_calibration.py` runs it by hand and prints the hold-out.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import statistics
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Sequence

SCHEMA = "college_prior_calibration_v1"
ENV = "SYNDICATE_COLLEGE_PRIOR_CALIBRATION"
WINDOW_DAYS = 21
MIN_CLOSES = 60
MIN_FINALS = 80
BETA_RANGE = (0.8, 1.4)
GAMMA_RANGE = (-2.0, 5.0)
SLOPE_RANGE = (0.5, 1.1)
_FILE_RE = re.compile(r"prior_calibration_(\d{4})_asof_(\d{8})\.json$")


def enabled(env: Optional[Mapping[str, str]] = None) -> bool:
    raw = str((env if env is not None else os.environ).get(ENV, "") or "").strip().lower()
    return raw not in {"0", "false", "off", "no"}


@dataclass(frozen=True)
class PriorCalibration:
    league: str
    season: int
    as_of: dt.date
    calibrated: bool
    target: str = ""  # "close" | "final"; "" when uncalibrated
    games: int = 0
    beta: float = 1.0
    gamma: float = 0.0
    total_slope: float = 1.0
    total_prior_mean: float = 0.0
    total_target_mean: float = 0.0
    reason: str = ""  # why it is uncalibrated
    clamped: tuple[str, ...] = ()
    source: str = ""

    def margin(self, raw_margin: float, *, home_site: bool) -> float:
        if not self.calibrated:
            return float(raw_margin)
        return self.beta * float(raw_margin) + (self.gamma if home_site else 0.0)

    def total(self, raw_total: float) -> float:
        if not self.calibrated:
            return float(raw_total)
        return self.total_target_mean + self.total_slope * (float(raw_total) - self.total_prior_mean)

    def stamp(self) -> dict[str, Any]:
        """What a sim's provenance records (and its inputs key re-sims on)."""
        out: dict[str, Any] = {"asOf": self.as_of.isoformat(), "calibrated": self.calibrated}
        if self.calibrated:
            out.update(target=self.target, games=self.games, beta=self.beta, gamma=self.gamma,
                       totalSlope=self.total_slope, totalPriorMean=self.total_prior_mean, totalTargetMean=self.total_target_mean)
        else:
            out["reason"] = self.reason
        return out

    def to_payload(self) -> dict[str, Any]:
        return {"schema": SCHEMA, "league": self.league, "season": self.season, "as_of": self.as_of.isoformat(),
                "calibrated": self.calibrated, "target": self.target, "games": self.games, "beta": self.beta,
                "gamma": self.gamma, "total_slope": self.total_slope, "total_prior_mean": self.total_prior_mean,
                "total_target_mean": self.total_target_mean, "reason": self.reason, "clamped": list(self.clamped)}

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any], *, source: str = "") -> "PriorCalibration":
        return cls(league=str(payload["league"]), season=int(payload["season"]), as_of=dt.date.fromisoformat(str(payload["as_of"])),
                   calibrated=bool(payload["calibrated"]), target=str(payload.get("target") or ""), games=int(payload.get("games") or 0),
                   beta=float(payload.get("beta", 1.0)), gamma=float(payload.get("gamma", 0.0)),
                   total_slope=float(payload.get("total_slope", 1.0)), total_prior_mean=float(payload.get("total_prior_mean", 0.0)),
                   total_target_mean=float(payload.get("total_target_mean", 0.0)), reason=str(payload.get("reason") or ""),
                   clamped=tuple(payload.get("clamped") or ()), source=source)


@dataclass(frozen=True)
class FitRow:
    date: str
    event_id: str
    home_site: bool
    prior_margin: float  # the RAW prior, home minus away in the slate's orientation
    prior_total: float
    close_margin: Optional[float] = None
    close_total: Optional[float] = None
    final_margin: Optional[float] = None
    final_total: Optional[float] = None


# ------------------------------------------------------------------------------------------------ the fit

def _clamp(value: float, bounds: tuple[float, float], name: str, clamped: list[str]) -> float:
    lo, hi = bounds
    if value < lo or value > hi:
        clamped.append(f"{name}={value:.3f}")
        return min(hi, max(lo, value))
    return value


def fit_margin(points: Sequence[tuple[float, bool, float]]) -> tuple[float, float]:
    """(beta, gamma) of y = beta*x + gamma*[home site], least squares, no intercept. All-neutral -> gamma 0."""
    sxx = sum(x * x for x, _h, _y in points)
    sxh = sum(x for x, h, _y in points if h)
    shh = float(sum(1 for _x, h, _y in points if h))
    sxy = sum(x * y for x, _h, y in points)
    shy = sum(y for _x, h, y in points if h)
    det = sxx * shh - sxh * sxh
    if shh == 0 or abs(det) < 1e-9:
        return (sxy / sxx if sxx else 1.0), 0.0
    return (sxy * shh - shy * sxh) / det, (sxx * shy - sxh * sxy) / det


def fit_total(points: Sequence[tuple[float, float]]) -> tuple[float, float, float]:
    """(slope, prior_mean, target_mean) of y = target_mean + slope*(x - prior_mean)."""
    mx = statistics.fmean(x for x, _y in points)
    my = statistics.fmean(y for _x, y in points)
    sxx = sum((x - mx) ** 2 for x, _y in points)
    slope = sum((x - mx) * (y - my) for x, y in points) / sxx if sxx else 1.0
    return slope, mx, my


def fit(rows: Iterable[FitRow], *, league: str, season: int, as_of: dt.date, min_closes: int = MIN_CLOSES,
        min_finals: int = MIN_FINALS) -> PriorCalibration:
    rows = list(rows)
    closes_m = [(r.prior_margin, r.home_site, r.close_margin) for r in rows if r.close_margin is not None]
    closes_t = [(r.prior_total, r.close_total) for r in rows if r.close_total is not None]
    finals_m = [(r.prior_margin, r.home_site, r.final_margin) for r in rows if r.final_margin is not None]
    finals_t = [(r.prior_total, r.final_total) for r in rows if r.final_total is not None]
    if min(len(closes_m), len(closes_t)) >= min_closes:
        target, margins, totals = "close", closes_m, closes_t
    elif min(len(finals_m), len(finals_t)) >= min_finals:
        target, margins, totals = "final", finals_m, finals_t
    else:
        return PriorCalibration(league, season, as_of, calibrated=False,
                                reason=f"{len(closes_m)} closes < {min_closes} and {len(finals_m)} finals < {min_finals}")
    beta, gamma = fit_margin(margins)  # type: ignore[arg-type]
    slope, prior_mean, target_mean = fit_total(totals)  # type: ignore[arg-type]
    clamped: list[str] = []
    beta = _clamp(beta, BETA_RANGE, "beta", clamped)
    gamma = _clamp(gamma, GAMMA_RANGE, "gamma", clamped)
    slope = _clamp(slope, SLOPE_RANGE, "total_slope", clamped)
    return PriorCalibration(league, season, as_of, calibrated=True, target=target, games=len(margins),
                            beta=round(beta, 4), gamma=round(gamma, 3), total_slope=round(slope, 4),
                            total_prior_mean=round(prior_mean, 3), total_target_mean=round(target_mean, 3), clamped=tuple(clamped))


def holdout(rows: Sequence[FitRow], *, league: str, season: int, as_of: dt.date) -> dict[str, Any]:
    """Split-sample check: fit on even event ids, score the odd ones raw vs calibrated, against closes and finals.
    A diagnostic, so the half-sample fit needs half the shipped minimums."""
    def rmse(values: list[float]) -> Optional[float]:
        return round((sum(v * v for v in values) / len(values)) ** 0.5, 3) if values else None

    train = [r for r in rows if _parity(r.event_id) == 0]
    test = [r for r in rows if _parity(r.event_id) == 1]
    cal = fit(train, league=league, season=season, as_of=as_of, min_closes=MIN_CLOSES // 2, min_finals=MIN_FINALS // 2)
    out: dict[str, Any] = {"train": len(train), "test": len(test), "calibrated": cal.calibrated, "target": cal.target}
    if not cal.calibrated:
        out["reason"] = cal.reason
        return out
    for name, m_attr, t_attr in (("close", "close_margin", "close_total"), ("final", "final_margin", "final_total")):
        m = [r for r in test if getattr(r, m_attr) is not None]
        t = [r for r in test if getattr(r, t_attr) is not None]
        out[f"vs_{name}"] = {
            "margin_n": len(m),
            "margin_rmse_raw": rmse([getattr(r, m_attr) - r.prior_margin for r in m]),
            "margin_rmse_cal": rmse([getattr(r, m_attr) - cal.margin(r.prior_margin, home_site=r.home_site) for r in m]),
            "total_n": len(t),
            "total_rmse_raw": rmse([getattr(r, t_attr) - r.prior_total for r in t]),
            "total_rmse_cal": rmse([getattr(r, t_attr) - cal.total(r.prior_total) for r in t]),
            "total_bias_raw": round(statistics.fmean(getattr(r, t_attr) - r.prior_total for r in t), 3) if t else None,
            "total_bias_cal": round(statistics.fmean(getattr(r, t_attr) - cal.total(r.prior_total) for r in t), 3) if t else None,
        }
    return out


def _parity(event_id: str) -> int:
    try:
        return int(event_id) % 2
    except ValueError:
        return sum(event_id.encode("utf-8")) % 2


# ------------------------------------------------------------------------------------------------ fit rows

def closing_totals(league: str, date_str: str, *, rows: Optional[Iterable[Mapping[str, Any]]] = None) -> dict[tuple[str, str], tuple[float, int]]:
    """(home_key, away_key) -> (closing consensus full-game total, books): each book's last OVER line before the listed
    tip, then the median across books (`live_resim.closing_home_margin`'s rule)."""
    from syndicate.features.ncaab import live_resim as lr

    if rows is None:
        from syndicate.features.shared.odds_book_quotes import iter_book_quotes

        rows = iter_book_quotes(league, date_str)
    latest: dict[tuple[str, str], dict[str, tuple[dt.datetime, float]]] = {}
    for row in rows:
        if (not isinstance(row, Mapping) or row.get("market") != "totals" or str(row.get("selection") or "").lower() != "over"
                or str(row.get("segment") or "full") not in ("full", "full_game") or row.get("line") is None):
            continue
        seen, commence = lr._utc(row.get("snapshot_ts") or row.get("captured_at")), lr._utc(row.get("commence_time"))
        if seen is None or commence is None or seen >= commence:
            continue
        try:
            line = float(row["line"])
        except (TypeError, ValueError):
            continue
        key = (lr._join_key(league, row.get("home_team")), lr._join_key(league, row.get("away_team")))
        book = str(row.get("bookmaker") or "")
        books = latest.setdefault(key, {})
        if book not in books or seen > books[book][0]:
            books[book] = (seen, line)
    return {key: (float(statistics.median(v[1] for v in books.values())), len(books)) for key, books in latest.items() if books}


def _not_played(game: Mapping[str, Any]) -> bool:
    status = str((game.get("live_state") or {}).get("status") or "").lower()
    return "postpon" in status or "cancel" in status


def build_fit_rows(league: str, dates: Iterable[str], *, now: Optional[dt.datetime] = None, dirs: Optional[Sequence[Path]] = None,
                   quote_rows: Optional[Mapping[str, Sequence[Mapping[str, Any]]]] = None) -> list[FitRow]:
    """One row per slate game of `dates` that has tipped: its RAW prior, closing line and final, where each exists."""
    from syndicate.features.ncaab import live_resim as lr
    from syndicate.features.ncaab import live_team_model as tm
    from syndicate.features.ncaab.slate import read_slate

    moment = now or dt.datetime.now(dt.timezone.utc)
    out: list[FitRow] = []
    for day in dates:
        games = (read_slate(day, league) or {}).get("games") or []
        if not games:
            continue
        injected = (quote_rows or {}).get(day) if quote_rows is not None else None
        spreads = lr.home_spread_quotes(league, day, rows=injected)
        totals = closing_totals(league, day, rows=injected)
        for game in games:
            start = lr._utc(game.get("start_time_utc"))
            if start is None or start > moment or _not_played(game):
                continue
            home, away = game.get("home") or {}, game.get("away") or {}
            prior = tm.prior_for_game(dt.date.fromisoformat(day), str(home.get("espn_id") or ""), str(away.get("espn_id") or ""),
                                      neutral=bool(game.get("neutral_site")), dirs=dirs, league=league, calibrate=False)
            if isinstance(prior, tm.NcaabPriorRefusal):
                continue
            hk, ak = lr._join_key(league, home.get("name")), lr._join_key(league, away.get("name"))
            close_margin = None
            if (hk, ak) in spreads:
                got = lr.closing_home_margin(spreads[(hk, ak)])
                close_margin = got[0] if got else None
            elif (ak, hk) in spreads:  # the feed oriented a neutral-site game the other way
                got = lr.closing_home_margin(spreads[(ak, hk)])
                close_margin = -got[0] if got else None
            total = totals.get((hk, ak)) or totals.get((ak, hk))
            final = bool((game.get("live_state") or {}).get("final"))
            hs, as_ = home.get("score"), away.get("score")
            scored = final and isinstance(hs, (int, float)) and isinstance(as_, (int, float))
            out.append(FitRow(date=day, event_id=str(game.get("event_id") or ""), home_site=not bool(game.get("neutral_site")),
                              prior_margin=float(prior.home_margin), prior_total=float(prior.total),
                              close_margin=close_margin, close_total=total[0] if total else None,
                              final_margin=float(hs - as_) if scored else None, final_total=float(hs + as_) if scored else None))
    return out


# ------------------------------------------------------------------------------------------------ files

def processed_dir(league: str) -> Path:
    """Where the ratings builder writes this league's tables (`build_ncaab_team_ratings.ncaab_root`)."""
    from syndicate.features.shared.refresh_state_store import data_root

    env_var, local_dir = ("SYNDICATE_WNCAAB_SOURCE_ROOT", "wncaab_source") if league == "wncaab" else ("SYNDICATE_NCAAB_SOURCE_ROOT", "ncaab_source")
    override = str(os.environ.get(env_var) or "").strip()
    return (Path(override) if override else Path(data_root()) / local_dir) / "data" / "processed"


def calibration_path(league: str, season: int, as_of: dt.date) -> Path:
    return processed_dir(league) / f"prior_calibration_{season}_asof_{as_of:%Y%m%d}.json"


def refresh_calibration(league: str, *, today: dt.date, window_days: int = WINDOW_DAYS, now: Optional[dt.datetime] = None,
                        dirs: Optional[Sequence[Path]] = None, quote_rows: Optional[Mapping[str, Sequence[Mapping[str, Any]]]] = None,
                        write: bool = True) -> tuple[PriorCalibration, dict[str, Any]]:
    """Fit on this season's games dated (today - window_days) .. (today - 1) and write the file for `today`'s games."""
    from syndicate.features.ncaab import live_team_model as tm

    as_of = today - dt.timedelta(days=1)
    season = tm.espn_season_for(today)
    dates = [(as_of - dt.timedelta(days=k)).isoformat() for k in range(window_days - 1, -1, -1)]
    dates = [d for d in dates if tm.espn_season_for(dt.date.fromisoformat(d)) == season]
    rows = build_fit_rows(league, dates, now=now, dirs=dirs, quote_rows=quote_rows)
    cal = fit(rows, league=league, season=season, as_of=as_of)
    report = {**cal.to_payload(), "window": [dates[0], dates[-1]] if dates else [], "rows": len(rows),
              "closes": sum(1 for r in rows if r.close_margin is not None), "finals": sum(1 for r in rows if r.final_margin is not None),
              "holdout": holdout(rows, league=league, season=season, as_of=as_of), "fitted_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    if write:
        path = calibration_path(league, season, as_of)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(report, sort_keys=True), encoding="utf-8")
        tmp.replace(path)
        report["written"] = str(path)
    status = (f"target={cal.target} games={cal.games} beta={cal.beta} gamma={cal.gamma} total_slope={cal.total_slope}"
              if cal.calibrated else f"UNCALIBRATED reason={cal.reason!r}")
    print(f"[college_prior_calibration] FIT league={league} as_of={as_of} rows={len(rows)} closes={report['closes']} "
          f"finals={report['finals']} {status}{' clamped=' + ','.join(cal.clamped) if cal.clamped else ''}", flush=True)
    return cal, report


_LOCK = threading.Lock()
_PARSED: dict[str, tuple[int, PriorCalibration]] = {}


def calibration_for(game_date: dt.date, league: str = "ncaab", *, dirs: Optional[Iterable[Path]] = None) -> Optional[PriorCalibration]:
    """The newest calibration of `game_date`'s season fitted strictly before it, or None when there is no file."""
    from syndicate.features.ncaab import live_team_model as tm

    season = tm.espn_season_for(game_date)
    found: dict[dt.date, Path] = {}
    for directory in list(dirs) if dirs is not None else tm.ratings_dirs(league):
        directory = Path(directory)
        if not directory.is_dir():
            continue
        for path in directory.glob(f"prior_calibration_{season}_asof_*.json"):
            match = _FILE_RE.search(path.name)
            if not match:
                continue
            as_of = dt.datetime.strptime(match.group(2), "%Y%m%d").date()
            if as_of < game_date:
                found.setdefault(as_of, path)  # first root wins, as preferred_artifact_roots orders them
    if not found:
        return None
    path = found[max(found)]
    try:
        mtime = path.stat().st_mtime_ns
    except OSError:
        return None
    key = str(path)
    with _LOCK:
        hit = _PARSED.get(key)
        if hit is not None and hit[0] == mtime:
            return hit[1]
    try:
        cal = PriorCalibration.from_payload(json.loads(path.read_text(encoding="utf-8")), source=key)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        # The newest file is the truth even when unreadable: serve the raw prior BY NAME, never an older fit.
        return PriorCalibration(league, season, max(found), calibrated=False, reason=f"unreadable {path.name}: {type(exc).__name__}", source=key)
    with _LOCK:
        _PARSED[key] = (mtime, cal)
    return cal
