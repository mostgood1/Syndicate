"""E3: are Kalshi / Polymarket DERIVED contracts mispriced against a surface built on the sharp main line?

Decision Engine plan §4 **E3** (lane `e3-derived-surface`). PRE-REGISTERED in
`.syndicate/findings_2026-10-26_e3_derived_surface_preregistration.md` before any surface x venue x outcome
join. Every constant below is the registered one; change one only through a dated amendment in that file.

READ-ONLY. Reads the fleet data root and sends only unauthenticated GETs to Kalshi's PUBLIC API (event
candlesticks, market listings). Imports no order, execution or credential code.

A derived contract is a binary "X > L" on a quantity X the sharp book does not price at L: an alternate
ladder rung of the full-game margin or total, a quarter / half / period / first-5 segment, or a team total.
Two arms price it, and they differ ONLY in shape:

  (a) PARAMETRIC: normal margin and total (basketball, football), independent Poisson goals (NHL, soccer),
      independent negative-binomial runs (MLB); its spread parameters come from history (cross-fitted).
  (b) SIM-SHAPED: the sport's own sim distribution of X, shifted on its integer lattice until it prices the
      sharp main line exactly. The sim supplies SHAPE only, never the mean.

Both arms take their LOCATION from the same anchor: the sharp book's main line of the same quantity where it
quotes one, else the full-game location times a cross-fitted segment share.

Pure python (no numpy) so the fleet half runs on the fleet's system interpreter.
"""
from __future__ import annotations

import argparse
import gzip
import json
import math
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import NormalDist, median
from typing import Any, Callable, Iterable, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.shared.opportunity_signals import devig  # noqa: E402

UTC = timezone.utc
N01 = NormalDist()

# ----------------------------------------------------------------------------- registered constants
WINDOW_START = datetime(2026, 9, 30, 0, 0, tzinfo=UTC)
WINDOW_END = datetime(2026, 10, 26, 8, 0, tzinfo=UTC)      # commence < this
DECISION_OFFSETS_MIN = {"t60": 60, "t15": 15}               # t60 PRIMARY, t15 secondary
CAPTURE_ALIVE = timedelta(minutes=90)
SHARP_BOOK = "pinnacle"
MIN_CONSENSUS_BOOKS = 2
SPORTS = ("ncaaf", "nfl", "nba", "wnba", "nhl", "mlb", "soccer")
ANCHOR_MARKETS = ("spreads", "totals", "h2h")
# Venues and exchanges in OddsAPI's bookmaker list: never part of a BOOK set (E5's set).
NON_BOOKS = {"kalshi", "polymarket", "polymarket_us", "prophetx", "novig", "sporttrade", "betfair_ex_eu",
             "betfair_ex_uk", "betfair_ex_au", "matchbook", "smarkets", "betopenly"}

# ============================================================================= A. surfaces (shape math)


def normal_p_over(line: float, mu: float, sigma: float) -> float:
    """P(X > line) for X ~ N(mu, sigma^2)."""
    return 1.0 - N01.cdf((line - mu) / sigma)


def normal_solve_mu(line0: float, p0: float, sigma: float) -> float:
    """The mu at which P(X > line0) = p0 under N(mu, sigma^2)."""
    return line0 + sigma * N01.inv_cdf(p0)


class Pmf:
    """A probability mass function on consecutive integers starting at `lo`."""

    __slots__ = ("lo", "p", "_tail")

    def __init__(self, lo: int, probs: Sequence[float]) -> None:
        total = float(sum(probs))
        if total <= 0:
            raise ValueError("empty pmf")
        self.lo = int(lo)
        self.p = [float(x) / total for x in probs]
        # _tail[i] = P(X >= lo + i)
        tail, acc = [0.0] * (len(self.p) + 1), 0.0
        for i in range(len(self.p) - 1, -1, -1):
            acc += self.p[i]
            tail[i] = acc
        self._tail = tail

    @classmethod
    def from_counts(cls, counts: Mapping[int, float]) -> "Pmf":
        lo, hi = min(counts), max(counts)
        return cls(lo, [float(counts.get(k, 0.0)) for k in range(lo, hi + 1)])

    @property
    def hi(self) -> int:
        return self.lo + len(self.p) - 1

    def mean(self) -> float:
        return sum((self.lo + i) * q for i, q in enumerate(self.p))

    def sd(self) -> float:
        m = self.mean()
        return math.sqrt(max(0.0, sum(((self.lo + i) - m) ** 2 * q for i, q in enumerate(self.p))))

    def p_ge(self, k: int) -> float:
        """P(X >= k) for integer k."""
        i = k - self.lo
        if i <= 0:
            return 1.0
        if i >= len(self.p):
            return 0.0
        return self._tail[i]

    def p_over(self, line: float) -> float:
        """P(X > line) for any real line."""
        return self.p_ge(math.floor(line) + 1)

    def negate(self) -> "Pmf":
        return Pmf(-self.hi, list(reversed(self.p)))

    def p_over_shifted(self, line: float, shift: float) -> float:
        """P(X + shift > line), the shift kept on the integer lattice.

        A real shift u = k + w is the mixture (1 - w) * (X + k) + w * (X + k + 1). The pmf's integer
        structure (football's key numbers, hockey's one-goal games) is moved intact, and the price at
        the anchor line is a continuous, non-decreasing function of u.
        """
        k = math.floor(shift)
        w = shift - k
        return (1.0 - w) * self.p_over(line - k) + w * self.p_over(line - k - 1)

    def mean_shifted(self, shift: float) -> float:
        return self.mean() + shift


def pmf_solve_shift(pmf: Pmf, line0: float, p0: float, *, span: float = 120.0, iters: int = 80) -> float | None:
    """The lattice shift u at which P(X + u > line0) = p0, or None when p0 is out of reach.

    The function is piecewise linear and non-decreasing in u; where it is flat at p0 the midpoint of
    the flat stretch is returned (bisection converges into it).
    """
    lo, hi = -span, span
    f_lo, f_hi = pmf.p_over_shifted(line0, lo), pmf.p_over_shifted(line0, hi)
    if not (f_lo <= p0 <= f_hi):
        return None
    for _ in range(iters):
        mid = 0.5 * (lo + hi)
        if pmf.p_over_shifted(line0, mid) < p0:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


# ----------------------------------------------------------------------------- count models (NHL, MLB, soccer)

COUNT_KMAX = 40


def poisson_probs(lam: float, kmax: int = COUNT_KMAX) -> list[float]:
    lam = max(lam, 1e-9)
    out, logp = [], -lam
    for k in range(kmax + 1):
        if k:
            logp += math.log(lam) - math.log(k)
        out.append(math.exp(logp))
    return out


def negbin_probs(mean: float, size: float, kmax: int = COUNT_KMAX) -> list[float]:
    """NB with E = mean, Var = mean + mean^2 / size."""
    mean = max(mean, 1e-9)
    p = size / (size + mean)
    out = []
    for k in range(kmax + 1):
        logpmf = (math.lgamma(k + size) - math.lgamma(size) - math.lgamma(k + 1)
                  + size * math.log(p) + k * math.log(1.0 - p))
        out.append(math.exp(logpmf))
    return out


def team_probs(mean: float, size: float | None) -> list[float]:
    return poisson_probs(mean) if size is None else negbin_probs(mean, size)


def pair_pmfs(ph: Sequence[float], pa: Sequence[float], *, tie_rule: str) -> dict[str, Pmf]:
    """Margin (home - away), total and team-score pmfs from two independent team-score pmfs.

    tie_rule: 'none' (soccer 90 min, segments), 'ot_plus_one' (NHL OT/shootout and MLB extra innings:
    a tie becomes a one-goal / one-run win, home with probability E[H] / (E[H] + E[A])).
    """
    n = len(ph)
    margin: dict[int, float] = {}
    total: dict[int, float] = {}
    home: dict[int, float] = {}
    away: dict[int, float] = {}
    mh = sum(k * q for k, q in enumerate(ph))
    ma = sum(k * q for k, q in enumerate(pa))
    home_ot = mh / (mh + ma) if (mh + ma) > 0 else 0.5
    for i in range(n):
        if ph[i] < 1e-15:
            continue
        for j in range(len(pa)):
            q = ph[i] * pa[j]
            if q < 1e-15:
                continue
            if i == j and tie_rule == "ot_plus_one":
                for d, w in ((1, home_ot), (-1, 1.0 - home_ot)):
                    margin[d] = margin.get(d, 0.0) + q * w
                total[i + j + 1] = total.get(i + j + 1, 0.0) + q
                home[i + 1] = home.get(i + 1, 0.0) + q * home_ot
                home[i] = home.get(i, 0.0) + q * (1.0 - home_ot)
                away[j] = away.get(j, 0.0) + q * home_ot
                away[j + 1] = away.get(j + 1, 0.0) + q * (1.0 - home_ot)
                continue
            margin[i - j] = margin.get(i - j, 0.0) + q
            total[i + j] = total.get(i + j, 0.0) + q
            home[i] = home.get(i, 0.0) + q
            away[j] = away.get(j, 0.0) + q
    return {"margin": Pmf.from_counts(margin), "total": Pmf.from_counts(total),
            "home": Pmf.from_counts(home), "away": Pmf.from_counts(away)}


def _bisect(f: Callable[[float], float], target: float, lo: float, hi: float, iters: int = 60) -> float | None:
    """x in [lo, hi] with f(x) = target for non-decreasing f, or None if out of reach."""
    f_lo, f_hi = f(lo), f(hi)
    if not (f_lo <= target <= f_hi):
        return None
    for _ in range(iters):
        mid = 0.5 * (lo + hi)
        if f(mid) < target:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def pair_arrays(ph: Sequence[float], pa: Sequence[float], *, tie_rule: str) -> dict[str, Pmf]:
    """`pair_pmfs` with numpy (the scoring side): same definitions, convolution instead of loops."""
    import numpy as np
    h = np.asarray(ph, dtype=float)
    a = np.asarray(pa, dtype=float)
    n = len(h)
    margin = np.convolve(h, a[::-1])            # index i <-> margin i - (n - 1)
    total = np.convolve(h, a)                   # index i <-> total i
    home, away = h.copy(), a.copy()
    if tie_rule == "ot_plus_one":
        diag = h * a
        tie = diag.sum()
        mh, ma = float((np.arange(n) * h).sum()), float((np.arange(n) * a).sum())
        w = mh / (mh + ma) if (mh + ma) > 0 else 0.5
        margin[n - 1] -= tie
        margin[n] += tie * w
        margin[n - 2] += tie * (1 - w)
        total = np.append(total, 0.0)
        total[0:2 * n - 1:2] -= diag
        total[1:2 * n:2] += diag
        home = np.append(h - diag * w, 0.0)
        home[1:] += diag * w
        away = np.append(a - diag * (1 - w), 0.0)
        away[1:] += diag * (1 - w)
    clip = lambda x: np.clip(x, 0.0, None)      # noqa: E731
    return {"margin": Pmf(-(n - 1), clip(margin).tolist()), "total": Pmf(0, clip(total).tolist()),
            "home": Pmf(0, clip(home).tolist()), "away": Pmf(0, clip(away).tolist())}


def two_way_over(pmf: Pmf, line: float, shift: float = 0.0) -> float:
    """P(X + shift > line) conditional on no push: a whole line refunds X == line."""
    over = pmf.p_over_shifted(line, shift)
    if abs(line - round(line)) > 1e-9:
        return over
    under = 1.0 - pmf.p_over_shifted(line - 0.5, shift)
    return over / (over + under) if (over + under) > 0 else 0.5


def solve_count_means(*, total_line: float, p_over: float, margin_line: float | None = None,
                      p_margin_over: float | None = None, p_home_minus_away: float | None = None,
                      size: float | None, tie_rule: str, max_total: float = 30.0,
                      kmax: int = COUNT_KMAX, fast: bool = False) -> tuple[float, float] | None:
    """(E[home], E[away]) at which the pair prices the anchor's total AND its margin constraint exactly.

    The margin constraint is either P(margin > margin_line) = p_margin_over (a run line / puck line,
    margin = home - away) or P(H > A) - P(A > H) = p_home_minus_away (soccer 1X2). Whole lines are priced
    conditional on no push. Nested bisection: outer on the total mean T, inner on the home share r of T.
    """
    pair = pair_arrays if fast else pair_pmfs

    def probs(mean: float) -> list[float]:
        return poisson_probs(mean, kmax) if size is None else negbin_probs(mean, size, kmax)

    def margin_stat(t: float, r: float) -> float:
        pm = pair(probs(t * r), probs(t * (1 - r)), tie_rule=tie_rule)
        if p_home_minus_away is not None:
            return pm["margin"].p_over(0.5) - (1.0 - pm["margin"].p_over(-0.5))
        return two_way_over(pm["margin"], margin_line)

    target = p_home_minus_away if p_home_minus_away is not None else p_margin_over
    if target is None:
        return None

    def share_for(t: float) -> float | None:
        return _bisect(lambda r: margin_stat(t, r), target, 0.02, 0.98, iters=32)

    def total_stat(t: float) -> float:
        r = share_for(t)
        if r is None:
            r = 0.5
        pm = pair(probs(t * r), probs(t * (1 - r)), tie_rule=tie_rule)
        return two_way_over(pm["total"], total_line)

    t = _bisect(total_stat, p_over, 0.2, max_total, iters=32)
    if t is None:
        return None
    r = share_for(t)
    if r is None:
        return None
    return t * r, t * (1 - r)


# ============================================================================= B. fleet extraction (anchors)


def parse_ts(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    opener = gzip.open if path.suffix == ".gz" else open
    try:
        with opener(path, "rt", encoding="utf-8") as handle:
            for line in handle:
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if isinstance(rec, dict):
                    yield rec
    except (OSError, EOFError):
        return


def book_quote_files(root: Path, sport: str) -> list[Path]:
    folder = root / f"{sport}_source" / "tracking" / "book_quotes"
    return sorted(p for p in folder.glob("*.jsonl*") if p.is_file()) + \
        sorted(p for p in folder.glob(".*.jsonl*") if p.is_file())


def extract_anchors(root: Path, sport: str, log: Callable[[str], None] = print) -> dict[str, Any]:
    """Per book game: every book's latest MAIN-market record at or before each decision time.

    `book_quotes` is append-on-change, so the latest record per (book, market, segment, selection, line)
    at or before t_d is that quote's state at t_d. Alternate markets (`*_alt`) are kept for Pinnacle only,
    as a diagnostic (Pinnacle's own price for a derived rung). Duplicate rows across a day file and its
    .gz twin collapse on the key.
    """
    events: dict[str, dict[str, Any]] = {}
    latest: dict[tuple, tuple[str, Any]] = {}
    snaps: set[str] = set()
    rows = 0
    for path in book_quote_files(root, sport):
        for r in read_jsonl(path):
            if r.get("kind") != "game":
                continue
            rows += 1
            book = str(r.get("bookmaker") or "").lower()
            market = str(r.get("market") or "")
            is_alt = market.endswith("_alt")
            if book in NON_BOOKS or (is_alt and book != SHARP_BOOK):
                continue
            base = market[:-4] if is_alt else market
            if base not in ANCHOR_MARKETS and market != "h2h_3_way":
                continue
            ev = str(r.get("event_id") or "")
            commence = parse_ts(r.get("commence_time"))
            ts = str(r.get("snapshot_ts") or "")
            t = parse_ts(ts)
            if not ev or commence is None or t is None:
                continue
            if not (WINDOW_START <= commence < WINDOW_END):
                continue
            snaps.add(ts)
            if ev not in events:
                events[ev] = {"event_id": ev, "sport": sport, "commence": commence.isoformat(),
                              "home": r.get("home_team"), "away": r.get("away_team")}
            line = r.get("line")
            try:
                line = None if line is None or (isinstance(line, float) and math.isnan(line)) else float(line)
            except (TypeError, ValueError):
                line = None
            for label, off in DECISION_OFFSETS_MIN.items():
                if t > commence - timedelta(minutes=off):
                    continue
                key = (ev, label, book, market, str(r.get("segment") or "full"), str(r.get("selection")), line)
                prev = latest.get(key)
                if prev is None or ts > prev[0]:
                    latest[key] = (ts, r.get("price"))
    snap_times = sorted(parse_ts(s) for s in snaps)
    out_events = []
    by_event: dict[str, list] = defaultdict(list)
    for key, val in latest.items():
        by_event[key[0]].append((key[1:], val))
    from bisect import bisect_right
    for ev, info in events.items():
        commence = parse_ts(info["commence"])
        info = dict(info)
        info["alive"] = {}
        for label, off in DECISION_OFFSETS_MIN.items():
            td = commence - timedelta(minutes=off)
            i = bisect_right(snap_times, td) - 1
            info["alive"][label] = bool(i >= 0 and td - snap_times[i] <= CAPTURE_ALIVE)
        info["quotes"] = [[*k, v[0], v[1]] for k, v in by_event.get(ev, [])]
        out_events.append(info)
    log(f"E3_EXTRACT sport={sport} rows={rows} events={len(out_events)} keys={len(latest)}")
    return {"sport": sport, "events": out_events}


def _is_quarter_line(line: float) -> bool:
    return abs(line * 2 - round(line * 2)) > 1e-9


def book_pairs(quotes: Sequence[Sequence[Any]], label: str, market: str, segment: str) -> dict[str, dict[str, Any]]:
    """book -> its main two-way pair at decision `label`: {'line': L0, 'p': p0} on the HOME-margin / OVER axis.

    Spreads: L0 = -(home line), p0 = de-vigged P(home margin > L0). Totals: L0 = line, p0 = P(total > L0).
    Both sides must be quoted at the book's most recently written line; Shin de-vig (two-way).
    Quarter lines (x.25 / x.75) are skipped. Whole lines are kept: p0 is then conditional on no push.
    """
    rows: dict[str, dict[tuple[str, float], tuple[str, Any]]] = defaultdict(dict)
    for q in quotes:
        lab, book, mkt, seg, sel, line, ts, price = q
        if lab != label or mkt != market or seg != segment or line is None:
            continue
        rows[book][(sel, float(line))] = (ts, price)
    out: dict[str, dict[str, Any]] = {}
    for book, recs in rows.items():
        if market == "spreads":
            cands = []
            for (sel, line), (ts, price) in recs.items():
                if sel != "home":
                    continue
                other = recs.get(("away", -line))
                if other is None:
                    continue
                cands.append((max(ts, other[0]), line, price, other[1]))
            if not cands:
                continue
            ts, hline, ph, pa = max(cands)
            if _is_quarter_line(hline):
                continue
            fair = devig([ph, pa], method="shin")
            if not fair:
                continue
            out[book] = {"line": -hline, "p": fair[0], "ts": ts}
        elif market == "totals":
            cands = []
            for (sel, line), (ts, price) in recs.items():
                if sel != "over":
                    continue
                other = recs.get(("under", line))
                if other is None:
                    continue
                cands.append((max(ts, other[0]), line, price, other[1]))
            if not cands:
                continue
            ts, line, po, pu = max(cands)
            if _is_quarter_line(line):
                continue
            fair = devig([po, pu], method="shin")
            if not fair:
                continue
            out[book] = {"line": line, "p": fair[0], "ts": ts}
    return out


def book_three_way(quotes: Sequence[Sequence[Any]], label: str, segment: str = "full") -> dict[str, dict[str, Any]]:
    """book -> de-vigged (home, draw, away) from its latest h2h home/draw/away quotes (soccer)."""
    rows: dict[str, dict[str, tuple[str, Any]]] = defaultdict(dict)
    for q in quotes:
        lab, book, mkt, seg, sel, line, ts, price = q
        if lab == label and mkt == "h2h" and seg == segment and sel in ("home", "draw", "away"):
            prev = rows[book].get(sel)
            if prev is None or ts > prev[0]:
                rows[book][sel] = (ts, price)
    out = {}
    for book, recs in rows.items():
        if len(recs) != 3:
            continue
        fair = devig([recs["home"][1], recs["draw"][1], recs["away"][1]], method="shin")
        if fair:
            out[book] = {"home": fair[0], "draw": fair[1], "away": fair[2],
                         "ts": max(v[0] for v in recs.values())}
    return out


def consensus(pairs: Mapping[str, Mapping[str, Any]]) -> dict[str, Any] | None:
    """Modal line across books (ties -> nearest the median line, then lower); median p0 at it; >= 2 books."""
    if not pairs:
        return None
    by_line: dict[float, list[float]] = defaultdict(list)
    for v in pairs.values():
        by_line[float(v["line"])].append(float(v["p"]))
    mid_line = median(float(v["line"]) for v in pairs.values())
    line = sorted(by_line, key=lambda x: (-len(by_line[x]), abs(x - mid_line), x))[0]
    ps = by_line[line]
    if len(ps) < MIN_CONSENSUS_BOOKS:
        return None
    return {"line": line, "p": median(ps), "n_books": len(ps)}


# ============================================================================= C. venues (Kalshi public API, Polymarket logs)

import re  # noqa: E402

KALSHI_BASE = "https://api.elections.kalshi.com/trade-api/v2"
KALSHI_LEAGUE_SPORT = {"NBA": "nba", "WNBA": "wnba", "NFL": "nfl", "NCAAF": "ncaaf", "NHL": "nhl", "MLB": "mlb"}
SOCCER_LEAGUES = ("BUNDESLIGA", "EREDIVISIE", "LALIGA", "LIGUE1", "SERIEA", "MLS", "UCL", "UEL", "UECL", "EPL",
                  "BELGIANPL", "BBL")
_SERIES_RE = re.compile(
    r"^KX(?P<league>NCAAF|WNBA|NBA|NFL|NHL|MLB|" + "|".join(SOCCER_LEAGUES) + r")"
    r"(?P<seg>[1-4]Q|[12]H|[1-3]P|F5)?(?P<kind>TEAMTOTAL|SPREAD|TOTAL)$")
SEGMENT_OF = {"1Q": "q1", "2Q": "q2", "3Q": "q3", "4Q": "q4", "1H": "h1", "2H": "h2",
              "1P": "p1", "2P": "p2", "3P": "p3", "F5": "first5", None: "full"}
GAME_SERIES = {"nba": "KXNBAGAME", "wnba": "KXWNBAGAME", "nfl": "KXNFLGAME", "ncaaf": "KXNCAAFGAME",
               "nhl": "KXNHLGAME", "mlb": "KXMLBGAME"}
_SPREAD_TITLE = re.compile(r"^(?P<team>.+?) wins(?: (?:1Q|2Q|3Q|4Q|1H|2H|1st Half|2nd Half|First Half|"
                           r"Second Half|1st Quarter|2nd Quarter|3rd Quarter|4th Quarter|F5|First 5))? by over",
                           re.IGNORECASE)
_TEAMTOTAL_TITLE = re.compile(r"^Will (?P<team>.+?) score over", re.IGNORECASE)


def parse_series(series: str) -> dict[str, str] | None:
    """`KXNBA1QSPREAD` -> {sport nba, segment q1, kind spread}; None for anything else."""
    m = _SERIES_RE.match(str(series or "").upper())
    if not m:
        return None
    league = m.group("league")
    sport = KALSHI_LEAGUE_SPORT.get(league, "soccer")
    return {"sport": sport, "league": league, "segment": SEGMENT_OF[m.group("seg")],
            "kind": {"SPREAD": "spread", "TOTAL": "total", "TEAMTOTAL": "team_total"}[m.group("kind")]}


def kalshi_derived_events(root: Path, sports: Iterable[str]) -> dict[str, dict[str, Any]]:
    """event ticker -> {series, sport, segment, kind, files} for every derived event in our venue logs."""
    out: dict[str, dict[str, Any]] = {}
    folder = root / "reports" / "intelligence" / "venue_odds"
    for sport in sports:
        for path in sorted(folder.glob(f"kalshi__{sport}__*.json")):
            try:
                doc = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            for ticker, m in (doc.get("markets") or {}).items():
                series = str(ticker).split("-", 1)[0]
                info = parse_series(series)
                if info is None or info["sport"] != sport:
                    continue
                event = str(m.get("event") or ticker.rsplit("-", 1)[0])
                rec = out.setdefault(event, {"event": event, "series": series, **info, "captured": set()})
                rec["captured"].add(ticker)
    for rec in out.values():
        rec["captured"] = sorted(rec["captured"])
    return out


PM_SEGMENT = {"1h": "h1", "h1": "h1", "2h": "h2", "h2": "h2", "1q": "q1", "q1": "q1", "2q": "q2", "q2": "q2",
              "3q": "q3", "q3": "q3", "4q": "q4", "q4": "q4", "1p": "p1", "p1": "p1", "2p": "p2", "p2": "p2",
              "3p": "p3", "p3": "p3", "f5": "first5"}
PM_LEAGUE_SPORT = {"nba": "nba", "wnba": "wnba", "nfl": "nfl", "cfb": "ncaaf", "nhl": "nhl", "mlb": "mlb"}
_PM_NUMBER = re.compile(r"^\d+(pt\d+)?$")


def pm_segment(modifiers: Sequence[str]) -> str | None:
    """The slug's segment ('full' when none); None when a modifier is not understood (refuse, never guess)."""
    seg = "full"
    for tok in modifiers:
        t = str(tok).lower()
        if t in ("pos", "neg", "total") or _PM_NUMBER.match(t):
            continue
        if t in PM_SEGMENT:
            seg = PM_SEGMENT[t]
            continue
        return None
    return seg


def polymarket_derived(root: Path, sports: Iterable[str]) -> list[dict[str, Any]]:
    """Polymarket spread / total markets (every rung) in the window, from our venue logs, with compact points
    [ts, yes, no]."""
    from syndicate.features.shared.polymarket_board_join import parse_slug
    out = []
    folder = root / "reports" / "intelligence" / "venue_odds"
    seen: set[str] = set()
    for sport in sports:
        for path in sorted(folder.glob(f"polymarket__{sport}__*.json")):
            try:
                doc = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            for slug, m in (doc.get("markets") or {}).items():
                if m.get("market") not in ("spreads", "totals") or slug in seen:
                    continue
                parsed = parse_slug(slug)
                if not parsed or PM_LEAGUE_SPORT.get(parsed["league"]) != sport:
                    continue
                seg = pm_segment(parsed["modifiers"])
                if seg is None or m.get("line") is None:
                    continue
                if not (WINDOW_START.date().isoformat() <= str(parsed["date"]) <= WINDOW_END.date().isoformat()):
                    continue
                seen.add(slug)
                out.append({"slug": slug, "sport": sport, "kind": "spread" if m["market"] == "spreads" else "total",
                            "segment": seg, "line": float(m["line"]), "away_code": parsed["away"],
                            "home_code": parsed["home"], "date": parsed["date"], "last_seen": m.get("last_seen"),
                            "points": [[pt.get("ts"), pt.get("yes"), pt.get("no")] for pt in m.get("points") or []]})
    return out


class KalshiPublic:
    """Unauthenticated GETs to Kalshi's public API, rate-limited, cached on disk (E5's client, event-scoped)."""

    def __init__(self, cache: Path | None, offline: bool = False, min_interval: float = 0.08) -> None:
        from scripts.e5_venue_news_lag import Kalshi
        self._k = Kalshi(cache, offline=offline, min_interval=min_interval)

    @property
    def calls(self) -> int:
        return self._k.calls

    def markets(self, event: str) -> list[dict[str, Any]]:
        body = self._k.get("/markets", {"event_ticker": event, "limit": 1000})
        return list(body.get("markets") or [])

    def event_candles(self, series: str, event: str, start: datetime, end: datetime,
                      period: int = 1) -> dict[str, list[tuple]]:
        """ticker -> [(end_ts, yes_bid, yes_ask)] candles over [start, end], following adjusted_end_ts."""
        out: dict[str, list[tuple]] = defaultdict(list)
        lo = int(start.timestamp())
        hi = int(end.timestamp())
        for _ in range(50):
            body = self._k.get(f"/series/{series}/events/{event}/candlesticks",
                               {"start_ts": lo, "end_ts": hi, "period_interval": period})
            tickers = body.get("market_tickers") or []
            for ticker, candles in zip(tickers, body.get("market_candlesticks") or []):
                for c in candles or []:
                    def close(side: str) -> float | None:
                        v = (c.get(side) or {}).get("close_dollars")
                        try:
                            return float(v) if v is not None else None
                        except (TypeError, ValueError):
                            return None
                    out[ticker].append((int(c["end_period_ts"]), close("yes_bid"), close("yes_ask")))
            adj = body.get("adjusted_end_ts")
            if not tickers or adj is None or int(adj) >= hi or int(adj) <= lo:
                break
            lo = int(adj)
        for ticker in out:
            out[ticker] = sorted(set(out[ticker]))
        return dict(out)


_MONTHS = {m: i + 1 for i, m in enumerate("JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split())}
_EVENT_DATE = re.compile(r"^(\d{2})([A-Z]{3})(\d{2})")
_CODE_SUFFIX = re.compile(r"^(?P<code>[A-Z][A-Z0-9]*?)(?P<num>\d+)$")
_WINS = re.compile(r"^(?P<team>.+?) wins", re.IGNORECASE)


def event_date(event: str):
    """The ET game date in a Kalshi event ticker (`KXNBASPREAD-26OCT22DENOKC` -> 2026-10-22)."""
    from datetime import date
    seg = event.split("-")[1] if "-" in event else ""
    m = _EVENT_DATE.match(seg)
    if not m or m.group(2) not in _MONTHS:
        return None
    return date(2000 + int(m.group(1)), _MONTHS[m.group(2)], int(m.group(3)))


def game_series_for(info: Mapping[str, str]) -> str:
    return GAME_SERIES.get(info["sport"]) or f"KX{info['league']}GAME"


def code_names_from(markets: Sequence[Mapping[str, Any]]) -> dict[str, str]:
    """{CODE: club name} from one GAME event's markets ("<Club> wins"); a code named twice is dropped."""
    found: dict[str, set[str]] = defaultdict(set)
    for m in markets:
        code = str(m.get("ticker") or "").rsplit("-", 1)[-1].upper()
        hit = _WINS.match(str(m.get("title") or ""))
        if code and code != "TIE" and hit:
            found[code].add(hit.group("team").strip())
    return {c: next(iter(n)) for c, n in found.items() if len(n) == 1}


def code_side(blob: str, code: str, sport: str) -> str | None:
    """'home' / 'away' for a market's team code inside its event blob (AWAY+HOME; soccer HOME+AWAY)."""
    starts, ends = blob.startswith(code), blob.endswith(code)
    if starts == ends:
        return None
    first, second = ("home", "away") if sport == "soccer" else ("away", "home")
    return first if starts else second


def quote_at(candles: Sequence[tuple], t: datetime) -> tuple[float, float] | None:
    """(bid, ask) from the last candle at or before t; None unless 0 < bid <= ask < 1."""
    ts = t.timestamp()
    best = None
    for c in candles:
        if c[0] <= ts:
            best = c
        else:
            break
    if best is None or best[1] is None or best[2] is None:
        return None
    bid, ask = best[1], best[2]
    if not (0.0 < bid <= ask < 1.0):
        return None
    return bid, ask


def _last_at_or_before(candles: Sequence[tuple], ts: float) -> tuple | None:
    best = None
    for c in candles:
        if c[0] <= ts:
            best = c
        else:
            break
    return best


def quote_two_res(minute: Sequence[tuple], hourly: Sequence[tuple], t: datetime) -> tuple[float, float] | None:
    """The book at t: the last 1-min candle at or before t; else (no change in the minute window) the last
    HOURLY candle ending at or before t. Any change after that hour's end and before t would have produced a
    later hourly candle ending at or before t, or a 1-min candle in the window, so this is the state at t."""
    ts = t.timestamp()
    best = _last_at_or_before(minute, ts) or _last_at_or_before(hourly, ts)
    if best is None or best[1] is None or best[2] is None:
        return None
    bid, ask = best[1], best[2]
    if not (0.0 < bid <= ask < 1.0):
        return None
    return bid, ask


def kalshi_fetch(extract_dir: Path, cache_dir: Path, sports: Sequence[str], *, workers: int = 5,
                 reverse: bool = False, log: Callable[[str], None] = print) -> dict[str, Any]:
    """Identity + every contract of every in-window derived event: line, side, result, quotes at t60 / t15."""
    from concurrent.futures import ThreadPoolExecutor
    from zoneinfo import ZoneInfo
    from syndicate.features.shared.kalshi_catalogue import event_blob_from_ticker, match_event_blob, \
        event_start_from_ticker
    et = ZoneInfo("America/New_York")
    events = json.loads((extract_dir / "kalshi_events.json").read_text(encoding="utf-8"))
    games: dict[str, list[dict[str, Any]]] = {}
    for sport in sports:
        doc = json.loads((extract_dir / f"anchors_{sport}.json").read_text(encoding="utf-8"))
        games[sport] = [{"event_id": e["event_id"], "home_team": e["home"], "away_team": e["away"],
                         "commence_time": e["commence"],
                         "et_date": parse_ts(e["commence"]).astimezone(et).date()} for e in doc["events"]]
    lo_d, hi_d = WINDOW_START.astimezone(et).date() - timedelta(days=1), WINDOW_END.astimezone(et).date()
    todo = {e: r for e, r in events.items() if r["sport"] in sports and event_date(e) and lo_d <= event_date(e) <= hi_d}
    pool = [KalshiPublic(cache_dir, min_interval=0.3) for _ in range(workers)]

    def run(fn, items):
        items = list(items)
        with ThreadPoolExecutor(max_workers=workers) as ex:
            return list(ex.map(lambda ix: fn(pool[ix[0] % workers], ix[1]), enumerate(items)))

    # 1. game identity, once per (sport, event segment), with the GAME event's own code names
    game_keys = sorted({(r["sport"], e.split("-")[1], game_series_for(r)) for e, r in todo.items()})
    game_mkts = run(lambda kp, k: kp.markets(f"{k[2]}-{k[1]}"), game_keys)
    identity: dict[tuple[str, str], dict[str, Any]] = {}
    for (sport, seg, _gs), mkts in zip(game_keys, game_mkts):
        any_event = next(e for e, r in todo.items() if r["sport"] == sport and e.split("-")[1] == seg)
        d = event_date(any_event)
        cand = [g for g in games[sport] if g["et_date"] == d]
        res = match_event_blob(event_blob_from_ticker(any_event), cand, sport=sport,
                               code_names=code_names_from(mkts) or None,
                               commence_hint=event_start_from_ticker(any_event))
        identity[(sport, seg)] = res
    # 2. markets + candles for every matched derived event
    matched = [(e, r) for e, r in todo.items() if identity[(r["sport"], e.split("-")[1])].get("status") == "ok"]
    by_id = {g["event_id"]: g for s in sports for g in games[s]}

    def pull(kp: KalshiPublic, item):
        e, r = item
        g = by_id[identity[(r["sport"], e.split("-")[1])]["event_id"]]
        commence = parse_ts(g["commence_time"])
        mkts = kp.markets(e)
        # Two resolutions (Kalshi pages event candles by market x period): hourly over 4 days for the standing
        # state, 1-minute over [commence - 180, commence - 10] so every change within 2 h of a decision is exact.
        hourly = kp.event_candles(r["series"], e, commence - timedelta(days=4), commence, period=60)
        minute = kp.event_candles(r["series"], e, commence - timedelta(minutes=180),
                                  commence - timedelta(minutes=10), period=1)
        return mkts, {"h": hourly, "m": minute}

    if reverse:   # a second process filling the same cache from the other end
        run(pull, matched[::-1])
    pulled = run(pull, matched)
    out: dict[str, Any] = {"identity": {f"{k[0]}|{k[1]}": v for k, v in identity.items()}, "contracts": [],
                           "rules": {}, "counts": defaultdict(int)}
    for (e, r), (mkts, candles) in zip(matched, pulled):
        gid = identity[(r["sport"], e.split("-")[1])]["event_id"]
        g = by_id[gid]
        commence = parse_ts(g["commence_time"])
        blob = event_blob_from_ticker(e) or ""
        for m in mkts:
            ticker = str(m.get("ticker") or "")
            out["counts"]["markets"] += 1
            if m.get("strike_type") != "greater" or m.get("floor_strike") is None:
                out["counts"]["not_greater_strike"] += 1
                continue
            side = None
            if r["kind"] in ("spread", "team_total"):
                suf = _CODE_SUFFIX.match(ticker.rsplit("-", 1)[-1].upper())
                side = code_side(blob.upper(), suf.group("code"), r["sport"]) if suf else None
                if side is None:
                    out["counts"]["side_unresolved"] += 1
                    continue
            out["rules"].setdefault(r["series"], str(m.get("rules_primary") or "")[:400])
            quotes = {lab: quote_two_res(candles["m"].get(ticker, []), candles["h"].get(ticker, []),
                                         commence - timedelta(minutes=off))
                      for lab, off in DECISION_OFFSETS_MIN.items()}
            out["contracts"].append({
                "ticker": ticker, "event": e, "series": r["series"], "sport": r["sport"], "segment": r["segment"],
                "kind": r["kind"], "side": side, "line": float(m["floor_strike"]), "result": m.get("result"),
                "event_id": gid, "commence": g["commence_time"], "captured": ticker in set(r["captured"]),
                "quotes": quotes, "title": m.get("title")})
    out["counts"] = dict(out["counts"])
    out["counts"]["events_in_window"] = len(todo)
    out["counts"]["events_matched"] = len(matched)
    out["counts"]["api_calls"] = sum(kp.calls for kp in pool)
    log(f"E3_KALSHI events={len(todo)} matched={len(matched)} contracts={len(out['contracts'])} "
        f"calls={out['counts']['api_calls']}")
    return out


# ============================================================================= D. parameters (history)

NORMAL_SPORTS = ("ncaaf", "nfl", "nba", "wnba")
COUNT_SPORTS = ("nhl", "mlb", "soccer")
NORMAL_SEGS = ("full", "h1", "h2", "h2reg", "q1", "q2", "q3", "q4")
NB_GRID = (2.0, 3.0, 4.0, 6.0, 8.0, 12.0, 20.0, None)       # None = Poisson
KMAX = {"nhl": 25, "soccer": 20, "mlb": 30}


def seg_score(g: Mapping[str, Any], seg: str) -> tuple[float, float] | None:
    """(home, away) points in a segment from a history / window record; None if not derivable."""
    ph = [0 if v is None else v for v in (g.get("periods_home") or [])]
    pa = [0 if v is None else v for v in (g.get("periods_away") or [])]
    ot_h, ot_a = g.get("ot_home") or 0, g.get("ot_away") or 0
    idx = {"q1": [0], "q2": [1], "q3": [2], "q4": [3], "h1": [0, 1], "h2": [2, 3], "h2reg": [2, 3],
           "p1": [0], "p2": [1], "p3": [2], "first5": [0, 1, 2, 3, 4]}
    if seg == "full":
        if g.get("final_home") is None or g.get("final_away") is None:
            return None
        return float(g["final_home"]), float(g["final_away"])
    if seg not in idx or max(idx[seg]) >= min(len(ph), len(pa)):
        return None
    h = sum(ph[i] for i in idx[seg])
    a = sum(pa[i] for i in idx[seg])
    if seg == "h2":
        h, a = h + ot_h, a + ot_a
    return float(h), float(a)


def _rms(xs: Sequence[float]) -> float:
    return math.sqrt(sum(x * x for x in xs) / len(xs)) if xs else float("nan")


def fit_normal_params(games: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """sigma and segment shares about the closing line (mu_M = -home spread, mu_T = total), per segment."""
    rows = [g for g in games if g.get("home_spread") is not None and g.get("total_line") is not None]
    out: dict[str, Any] = {"n_games": len(rows)}
    for seg in NORMAL_SEGS:
        mm, mt, xm, xt, xh, xa = [], [], [], [], [], []
        for g in rows:
            sc = seg_score(g, seg)
            if sc is None:
                continue
            mm.append(-float(g["home_spread"]))
            mt.append(float(g["total_line"]))
            xm.append(sc[0] - sc[1])
            xt.append(sc[0] + sc[1])
            xh.append(sc[0])
            xa.append(sc[1])
        if len(mm) < 10:
            continue
        if seg == "full":
            fm = ft = 1.0
        else:
            fm = sum(x * m for x, m in zip(xm, mm)) / sum(m * m for m in mm)
            ft = sum(x * m for x, m in zip(xt, mt)) / sum(m * m for m in mt)
        sm = _rms([x - fm * m for x, m in zip(xm, mm)])
        st = _rms([x - ft * m for x, m in zip(xt, mt)])
        team_res = ([x - (ft * t + fm * m) / 2 for x, t, m in zip(xh, mt, mm)]
                    + [x - (ft * t - fm * m) / 2 for x, t, m in zip(xa, mt, mm)])
        out[seg] = {"n": len(mm), "share_margin": fm, "share_total": ft, "sigma_margin": sm,
                    "sigma_total": st, "sigma_team": _rms(team_res)}
    return out


def fit_period_shares(games: Sequence[Mapping[str, Any]], segs: Sequence[str]) -> dict[str, float]:
    """Share of regulation scoring in each segment (count sports)."""
    tot = {s: 0.0 for s in segs}
    reg = 0.0
    for g in games:
        ph = [0 if v is None else v for v in (g.get("periods_home") or [])]
        pa = [0 if v is None else v for v in (g.get("periods_away") or [])]
        if not ph or not pa:
            continue
        reg += sum(ph) + sum(pa)
        for s in segs:
            sc = seg_score(g, s)
            if sc is not None:
                tot[s] += sc[0] + sc[1]
    return {s: (tot[s] / reg if reg else float("nan")) for s in segs}


# ============================================================================= E. surfaces


def anchor_set(ev: Mapping[str, Any], label: str, tier: str, sport: str) -> dict[tuple[str, str], dict] | None:
    """(market, segment) -> {'line', 'p'} (soccer adds ('h2h3', 'full') -> {'hma'}) for one tier, or None
    when the tier lacks the full-game margin constraint or total."""
    quotes = ev["quotes"]
    segs = ("full", "h1", "h2", "q1", "q2", "q3", "q4", "first5", "p1", "p2", "p3")
    out: dict[tuple[str, str], dict] = {}
    for market in ("spreads", "totals"):
        for seg in segs:
            pairs = book_pairs(quotes, label, market, seg)
            if tier == "S":
                if SHARP_BOOK in pairs:
                    out[(market, seg)] = {"line": pairs[SHARP_BOOK]["line"], "p": pairs[SHARP_BOOK]["p"],
                                          "n_books": 1}
            else:
                c = consensus(pairs)
                if c:
                    out[(market, seg)] = c
    if sport == "soccer":
        three = book_three_way(quotes, label)
        if tier == "S":
            if SHARP_BOOK in three:
                v = three[SHARP_BOOK]
                out[("h2h3", "full")] = {"hma": v["home"] - v["away"], "n_books": 1}
        elif len(three) >= MIN_CONSENSUS_BOOKS:
            out[("h2h3", "full")] = {"hma": median(v["home"] - v["away"] for v in three.values()),
                                     "n_books": len(three)}
        need = [("h2h3", "full"), ("totals", "full")]
    else:
        need = [("spreads", "full"), ("totals", "full")]
    if not all(k in out for k in need):
        return None
    return out


def kde_pmf(hist: Mapping[str, float]) -> Pmf | None:
    """Variance-preserving discrete Gaussian KDE of a sim histogram (registered §3)."""
    pts = sorted((int(float(k)), float(v)) for k, v in hist.items() if float(v) > 0)
    n = sum(w for _, w in pts)
    if n <= 0 or len(pts) < 2:
        return None
    mean = sum(k * w for k, w in pts) / n
    s = math.sqrt(sum((k - mean) ** 2 * w for k, w in pts) / n)
    if s <= 0:
        return None
    acc, q1, q3 = 0.0, None, None
    for k, w in pts:
        acc += w
        if q1 is None and acc >= 0.25 * n:
            q1 = k
        if q3 is None and acc >= 0.75 * n:
            q3 = k
    iqr = (q3 - q1) if q1 is not None and q3 is not None else 0.0
    spread = min(s, iqr / 1.34) if iqr > 0 else s
    h = 0.9 * spread * n ** (-0.2)
    shrink = math.sqrt(max(0.0, 1.0 - h * h / (s * s)))
    lo, hi = math.floor(mean - 7 * s), math.ceil(mean + 7 * s)
    probs = []
    for x in range(lo, hi + 1):
        total = 0.0
        for k, w in pts:
            z = (x - (mean + shrink * (k - mean))) / h
            if abs(z) < 9:
                total += w * math.exp(-0.5 * z * z)
        probs.append(total)
    return Pmf(lo, probs)


def raw_pmf(hist: Mapping[str, float]) -> Pmf | None:
    pts = {int(round(float(k))): float(v) for k, v in hist.items() if float(v) > 0}
    return Pmf.from_counts(pts) if pts else None


def normal_two_way(line: float, mu: float, sigma: float) -> float:
    """P(X > line | no push) for integer-valued X ~ N(mu, sigma^2) with a continuity correction."""
    if abs(line - round(line)) > 1e-9:
        return normal_p_over(line, mu, sigma)
    over = 1.0 - N01.cdf((line + 0.5 - mu) / sigma)
    under = N01.cdf((line - 0.5 - mu) / sigma)
    return over / (over + under)


def normal_solve(line0: float, p0: float, sigma: float) -> float | None:
    if abs(line0 - round(line0)) > 1e-9:
        return normal_solve_mu(line0, p0, sigma)
    return _bisect(lambda mu: normal_two_way(line0, mu, sigma), p0, line0 - 10 * sigma, line0 + 10 * sigma)


def p_over_normal(line: float, mu: float, sigma: float) -> float:
    """P(X > line) for integer-valued X (boundary at floor(line) + 0.5)."""
    return 1.0 - N01.cdf((math.floor(line) + 0.5 - mu) / sigma)


class Surface:
    """One game x tier x decision time x arm: prices P(X > L) per (quantity, segment); remembers anchor lines."""

    def __init__(self) -> None:
        self.dists: dict[tuple[str, str], Any] = {}   # (qty, seg) -> ("normal", mu, sigma) | ("pmf", Pmf, shift)
        self.anchor_lines: dict[tuple[str, str], float] = {}

    def price(self, qty: str, seg: str, line: float, below: bool = False) -> float | None:
        """P(X > line), or P(X < -line) when `below` (an away-side margin rung)."""
        d = self.dists.get((qty, seg))
        if d is None:
            return None
        if d[0] == "normal":
            _, mu, sigma = d
            if below:
                return N01.cdf((-math.floor(line) - 0.5 - mu) / sigma)
            return p_over_normal(line, mu, sigma)
        _, pmf, shift = d
        if below:
            return 1.0 - pmf.p_over_shifted(-math.floor(line) - 0.5, shift)
        return pmf.p_over_shifted(line, shift)

    def location(self, qty: str, seg: str) -> tuple[float, float] | None:
        """(mean, sd) of the located quantity, for the rung-distance split."""
        d = self.dists.get((qty, seg))
        if d is None:
            return None
        if d[0] == "normal":
            return d[1], d[2]
        return d[1].mean() + d[2], d[1].sd()


ANCHOR_MARKET = {"margin": "spreads", "total": "totals"}


def _anchor_lines(anchors: Mapping) -> dict[tuple[str, str], float]:
    return {("margin" if m == "spreads" else "total", seg): a["line"]
            for (m, seg), a in anchors.items() if m in ("spreads", "totals")}


def build_normal_surface(anchors: Mapping, params: Mapping, arm: str, sim: Mapping[str, Any] | None,
                         raw: bool = False) -> Surface | None:
    """Arm 'a' (Normal, history sigma) or 'b' (sim pmf, lattice-shifted); location from the anchors."""
    surf = Surface()
    surf.anchor_lines = _anchor_lines(anchors)
    full_mu: dict[str, float] = {}
    for qty in ("margin", "total"):
        for seg in NORMAL_SEGS:
            ps = params.get(seg)
            if ps is None:
                continue
            sigma = ps[f"sigma_{qty}"]
            a = anchors.get((ANCHOR_MARKET[qty], seg)) if seg != "h2reg" else None
            if arm == "a":
                if a is not None:
                    mu = normal_solve(a["line"], a["p"], sigma)
                elif seg != "full" and qty in full_mu:
                    mu = ps[f"share_{qty}"] * full_mu[qty]
                else:
                    mu = None
                if mu is None:
                    continue
                if seg == "full":
                    full_mu[qty] = mu
                surf.dists[(qty, seg)] = ("normal", mu, sigma)
                continue
            if sim is None or seg == "h2reg":
                continue
            hist = (sim.get("dists") or {}).get(f"{seg}_{qty}")
            pmf = (raw_pmf(hist) if raw else kde_pmf(hist)) if hist else None
            if pmf is None:
                continue
            if a is not None:
                u = _bisect(lambda x: two_way_over(pmf, a["line"], x), a["p"], -150.0, 150.0)
            elif seg != "full" and qty in full_mu:
                u = ps[f"share_{qty}"] * full_mu[qty] - pmf.mean()
            else:
                u = None
            if u is None:
                continue
            if seg == "full":
                full_mu[qty] = pmf.mean() + u
            surf.dists[(qty, seg)] = ("pmf", pmf, u)
    if arm == "a":
        for seg in NORMAL_SEGS:
            m, t, ps = surf.dists.get(("margin", seg)), surf.dists.get(("total", seg)), params.get(seg)
            if m and t and ps:
                surf.dists[("home", seg)] = ("normal", (t[1] + m[1]) / 2, ps["sigma_team"])
                surf.dists[("away", seg)] = ("normal", (t[1] - m[1]) / 2, ps["sigma_team"])
    if ("margin", "full") not in surf.dists or ("total", "full") not in surf.dists:
        return None
    return surf


def team_probs_k(mean: float, size: float | None, kmax: int) -> list[float]:
    return poisson_probs(mean, kmax) if size is None else negbin_probs(mean, size, kmax)


def build_count_surface(sport: str, anchors: Mapping, params: Mapping, arm: str,
                        sim: Mapping[str, Any] | None) -> Surface | None:
    """NHL / MLB / soccer: arm 'a' = Poisson / NB pair solved on the anchors; 'b' = the sim pmfs, shifted."""
    surf = Surface()
    surf.anchor_lines = _anchor_lines(anchors)
    kmax = KMAX[sport]
    tie = "none" if sport == "soccer" else "ot_plus_one"
    size, size5 = params.get("size"), params.get("size5")
    shares = params.get("shares") or {}
    tot = anchors[("totals", "full")]
    if arm == "a":
        if sport == "soccer":
            kw: dict[str, Any] = {"p_home_minus_away": anchors[("h2h3", "full")]["hma"]}
        else:
            kw = {"margin_line": anchors[("spreads", "full")]["line"],
                  "p_margin_over": anchors[("spreads", "full")]["p"]}
        sol = solve_count_means(total_line=tot["line"], p_over=tot["p"], size=size, tie_rule=tie, kmax=kmax,
                                fast=True, **kw)
        if sol is None:
            return None
        mh, ma = sol
        full = pair_arrays(team_probs_k(mh, size, kmax), team_probs_k(ma, size, kmax), tie_rule=tie)
        for qty in ("margin", "total", "home", "away"):
            surf.dists[(qty, "full")] = ("pmf", full[qty], 0.0)
        for seg, share in shares.items():
            sz = size5 if seg == "first5" else size
            sa, st = anchors.get(("spreads", seg)), anchors.get(("totals", seg))
            seg_sol = None
            if seg == "first5" and sa and st:
                seg_sol = solve_count_means(total_line=st["line"], p_over=st["p"], margin_line=sa["line"],
                                            p_margin_over=sa["p"], size=sz, tie_rule="none", kmax=kmax, fast=True)
            sh, sw = seg_sol if seg_sol else (share * mh, share * ma)
            pm = pair_arrays(team_probs_k(sh, sz, kmax), team_probs_k(sw, sz, kmax), tie_rule="none")
            for qty in ("margin", "total", "home", "away"):
                surf.dists[(qty, seg)] = ("pmf", pm[qty], 0.0)
        return surf
    if sim is None:
        return None
    dists = sim.get("dists") or {}
    full_mean: dict[str, float] = {}
    for seg in ["full"] + [s for s in shares if f"{s}_margin" in dists]:
        for qty in ("margin", "total"):
            hist = dists.get(f"{seg}_{qty}")
            pmf = raw_pmf(hist) if hist else None
            if pmf is None:
                continue
            a = anchors.get((ANCHOR_MARKET[qty], seg))
            if seg == "full" and sport == "soccer" and qty == "margin":
                target = anchors[("h2h3", "full")]["hma"]
                u = _bisect(lambda x: pmf.p_over_shifted(0.5, x) - (1 - pmf.p_over_shifted(-0.5, x)), target,
                            -15.0, 15.0)
            elif a is not None:
                u = _bisect(lambda x: two_way_over(pmf, a["line"], x), a["p"], -40.0, 40.0)
            elif seg != "full" and qty in full_mean:
                u = shares[seg] * full_mean[qty] - pmf.mean()
            else:
                u = None
            if u is None:
                continue
            if seg == "full":
                full_mean[qty] = pmf.mean() + u
            surf.dists[(qty, seg)] = ("pmf", pmf, u)
    if ("margin", "full") not in surf.dists or ("total", "full") not in surf.dists:
        return None
    return surf


# ============================================================================= scoring helpers

LL_CLIP = 1e-3


def log_loss(p: float, y: int) -> float:
    p = min(1.0 - LL_CLIP, max(LL_CLIP, p))
    return -math.log(p) if y else -math.log(1.0 - p)


def fee_net_return(win: int, ask: float, fee: float) -> float:
    """Return on cost of one $1 contract bought at `ask` plus `fee`."""
    cost = ask + fee
    return (float(win) - cost) / cost


def predicted_ev(p_side: float, ask: float, fee: float) -> float:
    return p_side / (ask + fee) - 1.0


# ============================================================================= F. scoring run

BOOT_DRAWS, SEED = 2000, 20261026
LL_MAX_SPREAD = 0.10
EV_BANDS = ((0.0, 0.02), (0.02, 0.05), (0.05, 0.10), (0.10, float("inf")))
DEV_BANDS = ((0.0, 0.02), (0.02, 0.04), (0.04, 0.07), (0.07, float("inf")))
MIN_VERDICT_CONTRACTS, MIN_VERDICT_GAMES = 300, 30
MIN_BAND_CONTRACTS, MIN_BAND_GAMES = 30, 15
MIN_CELL_CONTRACTS, MIN_CELL_GAMES = 100, 15


def _load(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def reg_variant(series_rules: str, seg: str) -> str:
    """'h2reg' where the series' own rules exclude overtime from the 2nd half (WNBA), else the segment."""
    text = series_rules.lower()
    if seg == "h2" and ("not including overtime" in text or "excluding overtime" in text):
        return "h2reg"
    return seg


def excludes_overtime(series_rules: str) -> bool:
    text = series_rules.lower()
    return "not including overtime" in text or "excluding overtime" in text


def contract_query(c: Mapping[str, Any], seg: str) -> tuple[str, str, float, bool]:
    """(qty, seg, line, below) for a Kalshi contract: P(X > line), or P(margin < -line) for an away rung."""
    if c["kind"] == "total":
        return "total", seg, c["line"], False
    if c["kind"] == "team_total":
        return c["side"], seg, c["line"], False
    return "margin", seg, c["line"], c["side"] == "away"


def realised(score: tuple[float, float], qty: str, line: float, below: bool) -> int:
    h, a = score
    x = {"margin": h - a, "total": h + a, "home": h, "away": a}[qty]
    return int(x < -line) if below else int(x > line)


def is_main_line_rung(surf: Surface, qty: str, seg: str, line: float, below: bool, sport: str) -> bool:
    if qty == "margin":
        l0 = surf.anchor_lines.get(("margin", seg))
        if sport == "soccer" and abs(line - 0.5) < 1e-9:
            return True
        return l0 is not None and abs((-line if below else line) - l0) < 1e-9
    if qty == "total":
        l0 = surf.anchor_lines.get(("total", seg))
        return l0 is not None and abs(line - l0) < 1e-9
    return False


def fit_mlb_lodo(window: Mapping[str, Any], anchors_by_event: Mapping[str, Any], label: str = "t60") -> dict:
    """Per test date: NB size r (9-inning team runs), r5 (F5 team runs) and the F5 share, fitted on the
    OTHER dates' games (registered: window LODO)."""
    games = []
    for eid, g in window.items():
        anchors = anchors_by_event.get(eid)
        if not anchors or g.get("final_home") is None:
            continue
        reg = seg_score({**g, "periods_home": g["periods_home"][:9], "periods_away": g["periods_away"][:9]}, "first5")
        h9 = sum(0 if v is None else v for v in g["periods_home"][:9])
        a9 = sum(0 if v is None else v for v in g["periods_away"][:9])
        games.append({"eid": eid, "date": g["date"], "h9": h9, "a9": a9, "f5": reg, "anchors": anchors})
    sol: dict[tuple[str, Any], tuple[float, float] | None] = {}
    for gm in games:
        a = gm["anchors"]
        for r in NB_GRID:
            sol[(gm["eid"], r)] = solve_count_means(
                total_line=a[("totals", "full")]["line"], p_over=a[("totals", "full")]["p"],
                margin_line=a[("spreads", "full")]["line"], p_margin_over=a[("spreads", "full")]["p"],
                size=r, tie_rule="ot_plus_one", kmax=KMAX["mlb"], fast=True)

    def nb_logpmf(k: int, mean: float, size: float | None) -> float:
        probs = team_probs_k(mean, size, max(KMAX["mlb"], int(k) + 1))
        return math.log(max(probs[int(k)], 1e-300))

    out = {}
    for d in sorted({gm["date"] for gm in games}):
        train = [gm for gm in games if gm["date"] != d]
        f5_runs = sum(gm["f5"][0] + gm["f5"][1] for gm in train if gm["f5"])
        reg_runs = sum(gm["h9"] + gm["a9"] for gm in train)
        share5 = f5_runs / reg_runs if reg_runs else 0.55
        best_r = max(NB_GRID, key=lambda r: sum(
            nb_logpmf(gm["h9"], sol[(gm["eid"], r)][0], r) + nb_logpmf(gm["a9"], sol[(gm["eid"], r)][1], r)
            for gm in train if sol[(gm["eid"], r)]))
        best_r5 = max(NB_GRID, key=lambda r5: sum(
            nb_logpmf(gm["f5"][0], share5 * sol[(gm["eid"], best_r)][0], r5)
            + nb_logpmf(gm["f5"][1], share5 * sol[(gm["eid"], best_r)][1], r5)
            for gm in train if gm["f5"] and sol[(gm["eid"], best_r)]))
        out[d] = {"size": best_r, "size5": best_r5, "shares": {"first5": share5}, "n_train": len(train)}
    return out


def fit_wnba_lodo(window: Mapping[str, Any], anchors_by_event: Mapping[str, Any]) -> dict:
    """WNBA: no prior lines exist, so sigma / shares are fitted on the other dates' window games, with the
    tier anchor's full-game lines standing in for the closing lines."""
    recs = []
    for eid, g in window.items():
        a = anchors_by_event.get(eid)
        if not a:
            continue
        recs.append({**g, "home_spread": -a[("spreads", "full")]["line"], "total_line": a[("totals", "full")]["line"]})
    return {d: fit_normal_params([r for r in recs if r["date"] != d]) for d in sorted({r["date"] for r in recs})}


def cluster_boot(values: Sequence[float], clusters: Sequence[str], *, draws: int = BOOT_DRAWS, seed: int = SEED,
                 alpha: float = 0.05) -> tuple[float, float, float]:
    """(mean, lo, hi): game-clustered percentile bootstrap of the contract-level mean."""
    import numpy as np
    if not values:
        return float("nan"), float("nan"), float("nan")
    keys = sorted(set(clusters))
    index = {k: i for i, k in enumerate(keys)}
    sums = np.zeros(len(keys))
    cnts = np.zeros(len(keys))
    for v, c in zip(values, clusters):
        sums[index[c]] += v
        cnts[index[c]] += 1
    rng = np.random.default_rng(seed)
    pick = rng.integers(0, len(keys), size=(draws, len(keys)))
    means = sums[pick].sum(axis=1) / np.maximum(cnts[pick].sum(axis=1), 1)
    lo, hi = np.quantile(means, [alpha / 2, 1 - alpha / 2])
    return float(sums.sum() / cnts.sum()), float(lo), float(hi)


def score_run(extract_dir: Path, sports: Sequence[str], log: Callable[[str], None] = print) -> dict[str, Any]:
    """Build every surface, price every Kalshi contract, validate results, and return rows + parameters."""
    from zoneinfo import ZoneInfo
    from syndicate.features.shared.season_phase import season_phase
    from syndicate.features.shared.venue_fees import taker_fee_per_contract
    from syndicate.features.shared.kalshi_catalogue import event_blob_from_ticker
    et = ZoneInfo("America/New_York")
    kc = _load(extract_dir / "kalshi_contracts.json") or {}
    rules = kc.get("rules") or {}
    params_doc: dict[str, Any] = {}
    rows: list[dict[str, Any]] = []
    counts: dict[str, int] = defaultdict(int)
    validation: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for sport in sports:
        events = {e["event_id"]: e for e in (_load(extract_dir / f"anchors_{sport}.json") or {}).get("events", [])}
        sims = (_load(extract_dir / f"sims_{sport}.json") or {}).get("games", {})
        window = (_load(extract_dir / f"window_{sport}.json") or {}).get("games", {})
        history = (_load(extract_dir / f"history_{sport}.json") or {}).get("games", [])
        # ---- tier anchors per (event, label)
        anchors: dict[tuple[str, str], tuple[str, dict]] = {}
        for eid, ev in events.items():
            for label in DECISION_OFFSETS_MIN:
                if not ev["alive"].get(label):
                    continue
                s_set = anchor_set(ev, label, "S", sport)
                if s_set:
                    anchors[(eid, label)] = ("S", s_set)
                    continue
                c_set = anchor_set(ev, label, "C", sport)
                if c_set:
                    anchors[(eid, label)] = ("C", c_set)
        t60_anchors = {eid: a for (eid, lab), (_t, a) in anchors.items() if lab == "t60"}
        # ---- parameters
        if sport in ("nfl", "nba", "ncaaf"):
            base = fit_normal_params(history)
            params_for = lambda eid, date, base=base: base       # noqa: E731
            params_doc[sport] = {"source": "prior season", **base}
        elif sport == "wnba":
            lodo = fit_wnba_lodo(window, t60_anchors)
            params_for = lambda eid, date, lodo=lodo: lodo.get(date)   # noqa: E731
            params_doc[sport] = {"source": "window LODO", "by_date": lodo}
        elif sport == "nhl":
            shares = fit_period_shares([g for g in history if g.get("phase") == "REG"], ("p1", "p2", "p3"))
            base = {"size": None, "shares": shares}
            params_for = lambda eid, date, base=base: base       # noqa: E731
            params_doc[sport] = {"source": "2025-26 regular season period shares", **base}
        elif sport == "soccer":
            ht = sum(g["periods_home"][0] + g["periods_away"][0] for g in history if g.get("periods_home"))
            ft = sum(g["final_home"] + g["final_away"] for g in history if g.get("periods_home"))
            base = {"size": None, "shares": {"h1": ht / ft if ft else 0.45}}
            params_for = lambda eid, date, base=base: base       # noqa: E731
            params_doc[sport] = {"source": "2023-2025 first-half goal share", **base, "n_games": len(history)}
        elif sport == "mlb":
            lodo = fit_mlb_lodo(window, t60_anchors)
            params_for = lambda eid, date, lodo=lodo: lodo.get(date)   # noqa: E731
            params_doc[sport] = {"source": "window LODO", "by_date": lodo}
        else:
            continue
        log(f"E3_PARAMS sport={sport} {json.dumps(params_doc[sport], default=str)[:600]}")
        # ---- surfaces (cached per event x label x arm)
        cache: dict[tuple[str, str, str], Surface | None] = {}

        def surface(eid: str, label: str, arm: str) -> Surface | None:
            key = (eid, label, arm)
            if key in cache:
                return cache[key]
            tier_anchor = anchors.get((eid, label))
            ev = events.get(eid)
            out = None
            if tier_anchor and ev:
                date = parse_ts(ev["commence"]).astimezone(et).date().isoformat()
                prm = params_for(eid, date)
                if prm:
                    sim = sims.get(eid)
                    if sport in NORMAL_SPORTS:
                        if arm in ("a", "b", "b0"):
                            out = build_normal_surface(tier_anchor[1], prm, "a" if arm == "a" else "b",
                                                       sim if arm != "a" else None, raw=(arm == "b0"))
                    elif arm in ("a", "b"):
                        out = build_count_surface(sport, tier_anchor[1], prm, arm, sim if arm == "b" else None)
            cache[key] = out
            return out

        # ---- contracts
        sport_contracts = [c for c in kc.get("contracts", []) if c["sport"] == sport]
        game_bad: set[str] = set()
        for c in sport_contracts:
            if c["result"] not in ("yes", "no"):
                continue
            seg = reg_variant(rules.get(c["series"], ""), c["segment"])
            qty, qseg, line, below = contract_query(c, seg)
            g = window.get(c["event_id"])
            if g is not None:
                sc = seg_score(g, qseg) if not (sport == "soccer" and qseg == "h1") else None
                if sc is not None:
                    agree = realised(sc, qty, line, below) == int(c["result"] == "yes")
                    validation[sport]["checked"] += 1
                    validation[sport]["agree"] += int(agree)
                    if not agree:
                        game_bad.add(c["event_id"])
        validation[sport]["games_disagreeing"] = len(game_bad)
        for c in sport_contracts:
            counts[f"{sport}:contracts"] += 1
            if c["result"] not in ("yes", "no"):
                counts[f"{sport}:no_result"] += 1
                continue
            if c["event_id"] in game_bad:
                counts[f"{sport}:result_disagrees_with_score"] += 1
                continue
            ev = events.get(c["event_id"])
            if ev is None:
                counts[f"{sport}:no_book_event"] += 1
                continue
            commence = parse_ts(ev["commence"])
            phase = season_phase(sport, commence.astimezone(et).date().isoformat()) or "unknown"
            seg = reg_variant(rules.get(c["series"], ""), c["segment"])
            if seg == "full" and excludes_overtime(rules.get(c["series"], "")):
                counts[f"{sport}:ot_definition_mismatch"] += 1
                continue
            qty, qseg, line, below = contract_query(c, seg)
            y = int(c["result"] == "yes")
            for label in DECISION_OFFSETS_MIN:
                q = (c.get("quotes") or {}).get(label)
                ta = anchors.get((c["event_id"], label))
                if ta is None:
                    counts[f"{sport}:{label}:no_anchor"] += 1
                    continue
                if q is None:
                    counts[f"{sport}:{label}:no_quote"] += 1
                    continue
                sa = surface(c["event_id"], label, "a")
                if sa is None:
                    counts[f"{sport}:{label}:no_surface"] += 1
                    continue
                if is_main_line_rung(sa, qty, qseg, line, below, sport):
                    counts[f"{sport}:{label}:main_line_rung"] += 1
                    continue
                bid, ask = q
                prices = {}
                for arm in ("a", "b", "b0"):
                    s = surface(c["event_id"], label, arm)
                    prices[arm] = s.price(qty, qseg, line, below) if s else None
                loc = sa.location(qty, qseg)
                axis_line = -line if below else line
                dist = abs(axis_line - loc[0]) / loc[1] if loc and loc[1] > 0 else None
                sim = sims.get(c["event_id"])
                sim_when = None
                if sim and sim.get("written_at"):
                    wt = parse_ts(sim["written_at"])
                    td = commence - timedelta(minutes=DECISION_OFFSETS_MIN[label])
                    sim_when = "before_td" if wt <= td else ("before_commence" if wt <= commence else "after_commence")
                p_pin = None
                if qty in ("margin", "total"):
                    x = -line if below else line
                    pp = pinnacle_alt_p(ev["quotes"], label, qty, qseg, x)
                    p_pin = (1.0 - pp) if (pp is not None and below) else pp
                fee_yes = taker_fee_per_contract("kalshi", ask, venue_ref=c["ticker"])[0]
                fee_no = taker_fee_per_contract("kalshi", 1.0 - bid, venue_ref=c["ticker"])[0]
                rows.append({
                    "venue": "kalshi", "sport": sport, "phase": phase, "tier": ta[0], "label": label,
                    "event_id": c["event_id"], "date": commence.astimezone(et).date().isoformat(),
                    "ticker": c["ticker"], "series": c["series"], "seg": qseg, "kind": c["kind"], "qty": qty,
                    "line": line, "below": below, "y": y, "bid": bid, "ask": ask, "mid": (bid + ask) / 2,
                    "fee_yes": fee_yes, "fee_no": fee_no, "captured": c.get("captured"),
                    "p_a": prices["a"], "p_b": prices["b"], "p_b0": prices["b0"], "dist_sigma": dist,
                    "sim_when": sim_when, "anchor_books": ta[1][("totals", "full")].get("n_books"),
                    "p_pin": p_pin})
        # ---- Polymarket (INDICATIVE): identity only through a Kalshi event that passed identity (prereg 6)
        blob_to_event = {}
        for key, ident in (kc.get("identity") or {}).items():
            sp, seg_code = key.split("|", 1)
            if sp == sport and ident.get("status") == "ok":
                d = event_date(f"X-{seg_code}")
                blob = event_blob_from_ticker(f"X-{seg_code}-Y")
                if d and blob:
                    blob_to_event[(d.isoformat(), blob.upper())] = ident["event_id"]
        for m in _load(extract_dir / f"pm_markets_{sport}.json") or []:
            counts[f"{sport}:pm_markets"] += 1
            eid = blob_to_event.get((m["date"], (m["away_code"] + m["home_code"]).upper()))
            if eid is None:
                counts[f"{sport}:pm_identity_refused"] += 1
                continue
            ev, g = events.get(eid), window.get(eid)
            if ev is None or g is None:
                counts[f"{sport}:pm_no_window_score"] += 1
                continue
            qseg = m["segment"]
            sc = seg_score(g, qseg)
            if sc is None:
                counts[f"{sport}:pm_no_segment_score"] += 1
                continue
            commence = parse_ts(ev["commence"])
            phase = season_phase(sport, commence.astimezone(et).date().isoformat()) or "unknown"
            if m["kind"] == "spread":   # YES = the slug's first (away) club covers: home margin < line
                qty, line, below = "margin", -m["line"], True
            else:
                qty, line, below = "total", m["line"], False
            y = realised(sc, qty, line, below)
            pts = sorted((parse_ts(pt[0]), pt[1], pt[2]) for pt in m["points"] if parse_ts(pt[0]))
            last_seen = parse_ts(m.get("last_seen"))
            for label in DECISION_OFFSETS_MIN:
                td = commence - timedelta(minutes=DECISION_OFFSETS_MIN[label])
                before = [pt for pt in pts if pt[0] <= td]
                ta = anchors.get((eid, label))
                if ta is None or not before or last_seen is None or last_seen < td:
                    counts[f"{sport}:{label}:pm_no_price"] += 1
                    continue
                _, yes, no = before[-1]
                if yes is None or no is None or not (0 < yes < 1 and 0 < no < 1) or yes + no < 1:
                    counts[f"{sport}:{label}:pm_one_sided"] += 1
                    continue
                sa = surface(eid, label, "a")
                if sa is None or is_main_line_rung(sa, qty, qseg, line, below, sport):
                    counts[f"{sport}:{label}:pm_main_or_no_surface"] += 1
                    continue
                prices = {}
                for arm in ("a", "b", "b0"):
                    s_ = surface(eid, label, arm)
                    prices[arm] = s_.price(qty, qseg, line, below) if s_ else None
                loc = sa.location(qty, qseg)
                dist = abs((-line if below else line) - loc[0]) / loc[1] if loc and loc[1] > 0 else None
                bid, ask = 1.0 - no, yes
                rows.append({
                    "venue": "polymarket", "sport": sport, "phase": phase, "tier": ta[0], "label": label,
                    "event_id": eid, "date": commence.astimezone(et).date().isoformat(), "ticker": m["slug"],
                    "series": "polymarket", "seg": qseg, "kind": m["kind"], "qty": qty, "line": line, "below": below,
                    "y": y, "bid": bid, "ask": ask, "mid": (bid + ask) / 2,
                    "fee_yes": taker_fee_per_contract("polymarket", ask)[0],
                    "fee_no": taker_fee_per_contract("polymarket", no)[0], "captured": True,
                    "p_a": prices["a"], "p_b": prices["b"], "p_b0": prices["b0"], "dist_sigma": dist,
                    "sim_when": None, "anchor_books": ta[1][("totals", "full")].get("n_books")})
        log(f"E3_SCORE sport={sport} rows={sum(1 for r in rows if r['sport'] == sport)} "
            f"validation={dict(validation[sport])}")
    return {"rows": rows, "params": params_doc, "counts": dict(counts),
            "validation": {k: dict(v) for k, v in validation.items()}}


def ev_side(p: float, row: Mapping[str, Any]) -> tuple[str, float, float, float] | None:
    """(side, predicted EV, cost, realised return) on the side with the larger predicted fee-net EV >= 0."""
    ev_yes = predicted_ev(p, row["ask"], row["fee_yes"])
    no_ask = 1.0 - row["bid"]
    ev_no = predicted_ev(1.0 - p, no_ask, row["fee_no"])
    if max(ev_yes, ev_no) < 0:
        return None
    if ev_yes >= ev_no:
        return "yes", ev_yes, row["ask"] + row["fee_yes"], fee_net_return(row["y"], row["ask"], row["fee_yes"])
    return "no", ev_no, no_ask + row["fee_no"], fee_net_return(1 - row["y"], no_ask, row["fee_no"])


def pinnacle_alt_p(quotes: Sequence[Sequence[Any]], label: str, qty: str, seg: str, x: float) -> float | None:
    """Pinnacle's own de-vigged P(X > x) from its ALT ladder at the same rung (diagnostic, prereg §4), or None.

    Margin: the home side at line -x against the away side at +x. Total: over / under at x. Main markets are
    excluded on purpose (those rungs are E1's, not E3's)."""
    want: dict[str, Any] = {}
    market = {"margin": "spreads_alt", "total": "totals_alt"}.get(qty)
    if market is None:
        return None
    for q in quotes:
        lab, book, mkt, sg, sel, line, ts, price = q
        if lab != label or book != SHARP_BOOK or mkt != market or sg != seg or line is None:
            continue
        if qty == "margin" and ((sel == "home" and abs(line + x) < 1e-9) or (sel == "away" and abs(line - x) < 1e-9)):
            if sel not in want or ts > want[sel][0]:
                want[sel] = (ts, price)
        if qty == "total" and abs(line - x) < 1e-9 and sel in ("over", "under"):
            if sel not in want or ts > want[sel][0]:
                want[sel] = (ts, price)
    sides = ("home", "away") if qty == "margin" else ("over", "under")
    if not all(k in want for k in sides):
        return None
    fair = devig([want[sides[0]][1], want[sides[1]][1]], method="shin")
    return fair[0] if fair else None


def summarise(rows: Sequence[Mapping[str, Any]], arm: str) -> dict[str, Any]:
    """The registered measures for one population and arm."""
    priced = [r for r in rows if r.get(f"p_{arm}") is not None]
    ll_rows = [r for r in priced if r["ask"] - r["bid"] <= LL_MAX_SPREAD + 1e-9]
    out: dict[str, Any] = {"n_priced": len(priced), "n_games_priced": len({r["event_id"] for r in priced})}
    d_ll = [log_loss(r[f"p_{arm}"], r["y"]) - log_loss(r["mid"], r["y"]) for r in ll_rows]
    d_br = [(r[f"p_{arm}"] - r["y"]) ** 2 - (r["mid"] - r["y"]) ** 2 for r in ll_rows]
    cl = [r["event_id"] for r in ll_rows]
    out["ll"] = {"n": len(ll_rows), "games": len(set(cl)), "dates": len({r["date"] for r in ll_rows}),
                 "delta": cluster_boot(d_ll, cl), "brier_delta": cluster_boot(d_br, cl),
                 "ll_surface": (sum(log_loss(r[f"p_{arm}"], r["y"]) for r in ll_rows) / len(ll_rows)) if ll_rows else None,
                 "ll_mid": (sum(log_loss(r["mid"], r["y"]) for r in ll_rows) / len(ll_rows)) if ll_rows else None}
    bets = []
    for r in priced:
        side = ev_side(r[f"p_{arm}"], r)
        if side:
            bets.append((r, side))
    bands = []
    for lo, hi in EV_BANDS:
        sel = [(r, s) for r, s in bets if lo <= s[1] < hi]
        vals = [s[3] for _, s in sel]
        cls = [r["event_id"] for r, _ in sel]
        b95 = cluster_boot(vals, cls)
        bbon = cluster_boot(vals, cls, alpha=0.05 / len(EV_BANDS))
        bands.append({"band": [lo, hi], "n": len(sel), "games": len(set(cls)), "mean": b95[0], "ci95": b95[1:],
                      "ci_bonf": bbon[1:], "pred_ev": (sum(s[1] for _, s in sel) / len(sel)) if sel else None})
    out["ev_bands"] = bands
    dev = []
    for lo, hi in DEV_BANDS:
        sel = [(r, s) for r, s in bets if lo <= abs(r[f"p_{arm}"] - r["mid"]) < hi]
        vals = [s[3] for _, s in sel]
        cls = [r["event_id"] for r, _ in sel]
        b = cluster_boot(vals, cls)
        dev.append({"band": [lo, hi], "n": len(sel), "games": len(set(cls)), "mean": b[0], "ci95": b[1:]})
    out["dev_bands"] = dev
    best: dict[tuple, tuple] = {}
    for r, s in bets:
        key = (r["event_id"], r["seg"], r["qty"])
        if key not in best or s[1] > best[key][1][1]:
            best[key] = (r, s)
    one = list(best.values())
    b = cluster_boot([s[3] for _, s in one], [r["event_id"] for r, _ in one])
    out["one_per_axis"] = {"n": len(one), "games": len({r['event_id'] for r, _ in one}), "mean": b[0], "ci95": b[1:]}
    return out


def verdict(summary: Mapping[str, Any], min_n: int = MIN_VERDICT_CONTRACTS, min_games: int = MIN_VERDICT_GAMES) -> str:
    ll = summary["ll"]
    if ll["n"] < min_n or ll["games"] < min_games:
        return "UNDERPOWERED"
    ll_pass = ll["delta"][2] < 0
    ev_pass = any(b["n"] >= MIN_BAND_CONTRACTS and b["games"] >= MIN_BAND_GAMES and b["ci_bonf"][0] > 0
                  for b in summary["ev_bands"])
    return "SURVIVES" if (ll_pass and ev_pass) else f"KILL ({'LL ok' if ll_pass else 'LL fails'}, " \
                                                   f"{'EV ok' if ev_pass else 'EV fails'})"


def cell_of(r: Mapping[str, Any]) -> str:
    if r["kind"] == "team_total":
        return "team_total" if r["seg"] == "full" else "team_total_seg"
    return f"{r['kind']}_{'full' if r['seg'] == 'full' else 'seg'}"


def dist_band(d: float | None) -> str:
    if d is None:
        return "n/a"
    return "body<0.5sd" if d < 0.5 else ("mid0.5-1.5sd" if d < 1.5 else "tail>1.5sd")


def paired(rows: Sequence[Mapping[str, Any]], arm1: str, arm0: str) -> dict[str, Any]:
    sel = [r for r in rows if r.get(f"p_{arm1}") is not None and r.get(f"p_{arm0}") is not None
           and r["ask"] - r["bid"] <= LL_MAX_SPREAD + 1e-9]
    vals = [log_loss(r[f"p_{arm1}"], r["y"]) - log_loss(r[f"p_{arm0}"], r["y"]) for r in sel]
    b = cluster_boot(vals, [r["event_id"] for r in sel])
    return {"n": len(sel), "games": len({r["event_id"] for r in sel}), "delta": b}


def reliability(rows: Sequence[Mapping[str, Any]], key: str) -> list[dict[str, Any]]:
    sel = sorted((r for r in rows if r.get(key) is not None), key=lambda r: r[key])
    out = []
    for i in range(10):
        part = sel[i * len(sel) // 10:(i + 1) * len(sel) // 10]
        if part:
            out.append({"decile": i + 1, "n": len(part), "pred": sum(r[key] for r in part) / len(part),
                        "obs": sum(r["y"] for r in part) / len(part)})
    return out


def build_report(run: Mapping[str, Any]) -> dict[str, Any]:
    rows = run["rows"]
    rep: dict[str, Any] = {"verdicts": [], "cells": [], "engine": {}, "coverage": {}}
    for venue in ("kalshi", "polymarket"):
        for label in DECISION_OFFSETS_MIN:
            for tier in ("S", "C"):
                pop = [r for r in rows if r["venue"] == venue and r["label"] == label and r["tier"] == tier]
                for arm in ("a", "b"):
                    sm = summarise(pop, arm)
                    rep["verdicts"].append({"venue": venue, "label": label, "tier": tier, "arm": arm,
                                            "verdict": verdict(sm), **sm})
    t60_all = [r for r in rows if r["label"] == "t60"]
    cells = sorted({(r["venue"], r["tier"], r["sport"], r["phase"], cell_of(r)) for r in t60_all})
    for venue, tier, sport, phase, cell in cells:
        pop = [r for r in t60_all
               if (r["venue"], r["tier"], r["sport"], r["phase"], cell_of(r)) == (venue, tier, sport, phase, cell)]
        for arm in ("a", "b"):
            sm = summarise(pop, arm)
            if sm["n_priced"] == 0:
                continue
            ll = sm["ll"]
            readable = ll["n"] >= MIN_CELL_CONTRACTS and ll["games"] >= MIN_CELL_GAMES
            rep["cells"].append({"venue": venue, "tier": tier, "sport": sport, "phase": phase, "cell": cell,
                                 "arm": arm, "readable": readable,
                                 "read": verdict(sm, MIN_CELL_CONTRACTS, MIN_CELL_GAMES) if readable else "thin",
                                 "_pop": pop, **sm})
    # Bonferroni across the readable cells of each (venue, tier, arm), reported beside the cell read (prereg §5)
    fams: dict[tuple, list] = defaultdict(list)
    for c in rep["cells"]:
        if c["readable"]:
            fams[(c["venue"], c["tier"], c["arm"])].append(c)
    for fam in fams.values():
        k = len(fam)
        for c in fam:
            arm, pop = c["arm"], c["_pop"]
            ll_rows = [r for r in pop if r.get(f"p_{arm}") is not None and r["ask"] - r["bid"] <= LL_MAX_SPREAD + 1e-9]
            vals = [log_loss(r[f"p_{arm}"], r["y"]) - log_loss(r["mid"], r["y"]) for r in ll_rows]
            c["ll_ci_bonf_cells"] = cluster_boot(vals, [r["event_id"] for r in ll_rows], alpha=0.05 / k)[1:]
            bets = [(r, ev_side(r[f"p_{arm}"], r)) for r in pop if r.get(f"p_{arm}") is not None]
            bets = [(r, sd) for r, sd in bets if sd]
            for b in c["ev_bands"]:
                lo, hi = b["band"]
                sel = [(r, sd) for r, sd in bets if lo <= sd[1] < hi]
                b["ci_bonf_cells"] = cluster_boot([sd[3] for _, sd in sel], [r["event_id"] for r, _ in sel],
                                                  alpha=0.05 / (k * len(EV_BANDS)))[1:]
            c["n_cells_in_family"] = k
    for c in rep["cells"]:
        c.pop("_pop", None)
    t60 = [r for r in t60_all if r["venue"] == "kalshi"]
    eng: dict[str, Any] = {"b_vs_a": [], "b0_vs_a": [], "b_vs_a_by_dist": [], "sim_when": [], "reliability": {}}
    groups = sorted({(r["sport"], cell_of(r)) for r in t60})
    for sport, cell in groups:
        pop = [r for r in t60 if r["sport"] == sport and cell_of(r) == cell]
        eng["b_vs_a"].append({"sport": sport, "cell": cell, **paired(pop, "b", "a")})
        eng["b0_vs_a"].append({"sport": sport, "cell": cell, **paired(pop, "b0", "a")})
        for band in ("body<0.5sd", "mid0.5-1.5sd", "tail>1.5sd"):
            sub = [r for r in pop if dist_band(r["dist_sigma"]) == band]
            eng["b_vs_a_by_dist"].append({"sport": sport, "cell": cell, "band": band, **paired(sub, "b", "a")})
    for sport in sorted({r["sport"] for r in t60}):
        for when in ("before_td", "before_commence", "after_commence"):
            sub = [r for r in t60 if r["sport"] == sport and r["sim_when"] == when]
            if sub:
                sm = summarise(sub, "b")
                eng["sim_when"].append({"sport": sport, "when": when, "ll": sm["ll"], **paired(sub, "b", "a")})
    pin = [r for r in t60 if r.get("p_pin") is not None and r["ask"] - r["bid"] <= LL_MAX_SPREAD + 1e-9]
    eng["pinnacle_alt"] = {"n": len(pin), "games": len({r["event_id"] for r in pin})}
    for key in ("a", "b", "pin"):
        sel = [r for r in pin if r.get(f"p_{key}") is not None]
        vals = [log_loss(r[f"p_{key}"], r["y"]) - log_loss(r["mid"], r["y"]) for r in sel]
        eng["pinnacle_alt"][f"{key}_vs_mid"] = {"n": len(sel), "delta": cluster_boot(vals, [r["event_id"] for r in sel])}
        if key != "pin":
            both = [r for r in sel]
            v2 = [log_loss(r[f"p_{key}"], r["y"]) - log_loss(r["p_pin"], r["y"]) for r in both]
            eng["pinnacle_alt"][f"{key}_vs_pin"] = {"n": len(both),
                                                    "delta": cluster_boot(v2, [r["event_id"] for r in both])}
            eng["pinnacle_alt"][f"{key}_abs_gap_pp"] = (100 * sum(abs(r[f"p_{key}"] - r["p_pin"]) for r in both)
                                                        / len(both)) if both else None
    for arm in ("a", "b"):
        eng["reliability"][arm] = reliability([r for r in t60 if r["ask"] - r["bid"] <= LL_MAX_SPREAD], f"p_{arm}")
    eng["reliability"]["mid"] = reliability([r for r in t60 if r["ask"] - r["bid"] <= LL_MAX_SPREAD], "mid")
    rep["engine"] = eng
    cov: dict[str, Any] = defaultdict(lambda: {"rows": 0, "games": set(), "dates": set()})
    for r in rows:
        k = f"{r['label']}|{r['tier']}|{r['sport']}"
        cov[k]["rows"] += 1
        cov[k]["games"].add(r["event_id"])
        cov[k]["dates"].add(r["date"])
    rep["coverage"] = {k: {"rows": v["rows"], "games": len(v["games"]), "dates": len(v["dates"]),
                           "first": min(v["dates"]), "last": max(v["dates"])} for k, v in cov.items()}
    return rep


# ============================================================================= CLI


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    ex = sub.add_parser("extract", help="fleet side: per-game book anchors at each decision time")
    ex.add_argument("--data-root", default=os.path.expanduser("~/syndicate-prod/data"))
    ex.add_argument("--sports", default=",".join(SPORTS))
    ex.add_argument("--out-dir", required=True)
    ve = sub.add_parser("venue-extract", help="fleet side: Kalshi derived events + Polymarket spread/total points")
    ve.add_argument("--data-root", default=os.path.expanduser("~/syndicate-prod/data"))
    ve.add_argument("--sports", default=",".join(SPORTS))
    ve.add_argument("--out-dir", required=True)
    kf = sub.add_parser("kalshi-fetch", help="Kalshi public API: identity, contracts, results, t60/t15 quotes")
    kf.add_argument("--extract-dir", required=True)
    kf.add_argument("--cache", required=True)
    kf.add_argument("--sports", default=",".join(SPORTS))
    kf.add_argument("--workers", type=int, default=5)
    kf.add_argument("--reverse", action="store_true")
    kf.add_argument("--out-name", default=None)
    sc = sub.add_parser("score", help="build surfaces, price contracts, write rows + the registered report")
    sc.add_argument("--extract-dir", required=True)
    sc.add_argument("--out-dir", required=True)
    sc.add_argument("--sports", default=",".join(SPORTS))
    args = ap.parse_args(argv)
    if args.cmd == "score":
        out = Path(args.out_dir)
        out.mkdir(parents=True, exist_ok=True)
        run = score_run(Path(args.extract_dir), [s for s in args.sports.split(",") if s])
        with open(out / "rows.jsonl", "w", encoding="utf-8") as fh:
            for r in run["rows"]:
                fh.write(json.dumps(r) + "\n")
        rep = build_report(run)
        rep.update({"params": run["params"], "counts": run["counts"], "validation": run["validation"]})
        (out / "report.json").write_text(json.dumps(rep, default=str, indent=1), encoding="utf-8")
        for v in rep["verdicts"]:
            ll = v["ll"]
            print(f"E3_VERDICT {v['venue']} {v['label']} tier={v['tier']} arm={v['arm']} -> {v['verdict']} | "
                  f"dLL {ll['delta'][0]:+.4f} [{ll['delta'][1]:+.4f}, {ll['delta'][2]:+.4f}] n={ll['n']} "
                  f"games={ll['games']}", flush=True)
        return 0
    if args.cmd == "kalshi-fetch":
        sports = [s for s in args.sports.split(",") if s]
        doc = kalshi_fetch(Path(args.extract_dir), Path(args.cache), sports, workers=args.workers, reverse=args.reverse)
        name = args.out_name or ("kalshi_contracts.json" if len(sports) == len(SPORTS)
                                 else f"kalshi_contracts_{'_'.join(sports)}.json")
        (Path(args.extract_dir) / name).write_text(json.dumps(doc), encoding="utf-8")
        return 0
    if args.cmd == "venue-extract":
        out = Path(args.out_dir)
        out.mkdir(parents=True, exist_ok=True)
        sports = [s for s in args.sports.split(",") if s]
        events = kalshi_derived_events(Path(args.data_root), sports)
        (out / "kalshi_events.json").write_text(json.dumps(events), encoding="utf-8")
        n_pm = 0
        for sport in sports:
            pm = polymarket_derived(Path(args.data_root), [sport])
            n_pm += len(pm)
            with open(out / f"pm_markets_{sport}.json", "w", encoding="utf-8") as fh:
                json.dump(pm, fh)
            del pm
        print(f"E3_VENUE_EXTRACT kalshi_events={len(events)} pm_markets={n_pm}", flush=True)
        return 0
    if args.cmd == "extract":
        out = Path(args.out_dir)
        out.mkdir(parents=True, exist_ok=True)
        for sport in [s for s in args.sports.split(",") if s]:
            doc = extract_anchors(Path(args.data_root), sport)
            (out / f"anchors_{sport}.json").write_text(json.dumps(doc), encoding="utf-8")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
