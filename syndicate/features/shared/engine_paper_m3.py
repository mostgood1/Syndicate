"""M3, the paper book: its live replay and its gate (decision engine #736, Phase 1B; lane `engine-paper-m3`).

REGISTERED BEFORE ITS DATA: `.syndicate/findings_2026-11-17_m3_paper_book.md` (main `9f37d556c`, 2026-11-17 5:22 PM
CST, user "Yes, register it"). This module applies that rule and nothing else. Every constant below is quoted from it.

WHAT IT DOES. For one slate and one sport it takes:
- the eligible live lines, each with the learner's frozen adjustment `A = logit(p_decision) - logit(p_prior)`, handed in by
  its script (`scripts/engine_paper_m3.py`), which runs the pinned learner;
- the in-play recorder's Kalshi rows (`scripts/inplay_recorder.py`: `kalshi.jsonl`, Kalshi's public API every 10 s, each
  row stamped with its receive time).

It places each line on a Kalshi market with the order path's own resolver, buys 1 contract at the first quote received
at least 10 s after the decision when the registered edge holds, and marks it 300..420 s later and at settlement. The
gate half computes the game-clustered z of the mark-outs at the registered looks.

PURE AND SHADOW ONLY. It writes nothing, places no order and imports no order module. The market placement is
`kalshi_board_join._resolve_event` / `_side_for_team`, read-only, as the slice-5 index used them. It imports neither the
learner nor the opinion producers; its script hands it what they compute. (The opinion producers' shadow guard fails
on any file under `syndicate/` that names them, so this one never does.)

THE FRAME (the live join's, which the opinions are in): every line is OUR side --
  totals   P(over L)                  Kalshi "Over L points"            -> key L,  p = mid(YES)
  spreads  P(home covers at L), margin > L
                                      "<home> wins by over s"           -> key s,  p = mid(YES)
                                      "<away> wins by over s"           -> key -s, p = 1 - mid(YES)
  h2h      P(home wins)               "<home>" GAME market              -> key 0,  p = mid(YES)
                                      "<away>" GAME market              -> key 0,  p = 1 - mid(YES)
The away-team spread is the 2026-08-08 backwards-sign shape. The per-slate FRAME check refuses a family whose book
priors sit nearer the flipped orientation than the chosen one.
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any, Callable, Iterable, Mapping, Sequence

M3_VERSION = "engine_paper_m3/1"

# ---- the registered constants (findings_2026-11-17_m3_paper_book.md) ----
LATENCY_S = 10.0              # entry: the first quote received at or after t_d + 10 s ...
ENTRY_WINDOW_S = 70.0         # ... and no later than t_d + 70 s
ASK_MIN, ASK_MAX = 0.05, 0.95  # asks outside [0.05, 0.95] are not taken
EDGE_FLOOR = 0.03             # p - ask - fee >= 0.03 (the in-play paper book's floor)
FEE_CONTRACTS = 10            # the fee per contract on a 10-contract order (the in-play scoreboard's convention)
FRESH_PRIOR_S = 60.0          # M2 judged the fresh (<= 60 s) prior only
FRESH_STRATUM = "a<=60"
MARK_FROM_S, MARK_TO_S = 300.0, 420.0  # the in-play paper book's own mark window
LOOKS: tuple[tuple[str, int, int, float, float | None], ...] = (
    ("L1", 400, 100, 3.935, -3.935),
    ("L2", 800, 200, 2.783, -2.783),
    ("L3", 1200, 300, 2.272, None),   # L3: z >= 2.272 passes, anything else fails
)
CALENDAR_STOP = "2027-01-31"   # L3 is taken at the calendar stop if its counts were never reached
UNMARKED_MAX = 0.10            # more than 10% of a look's bets unmarked -> NOT_A_VERDICT
HARM_MIN_BETS, HARM_MIN_GAMES, HARM_Z = 100, 30, -2.576
ROI_Z = 1.96                   # the ROI's game-clustered 95% CI, read only after a mark-out PASS

# Not registered as numbers but implied by the registered rule, and stated here so nothing is silent:
FRAME_MIN_LINES = 20           # the frame check needs at least this many line-instants with both prices, else the
                               # family is UNVERIFIED that slate and places no bet (refusing is the safe direction)
FRAME_QUOTE_MAX_AGE_S = 60.0   # the standing Kalshi quote the frame check compares must be at most 60 s old

ARM_A1, ARM_A2 = "A1", "A2"    # A1 gates: Kalshi's mid plus the learner's adjustment. A2 (reported): p_decision itself.
ARMS = (ARM_A1, ARM_A2)

# The recorder polls these series (NBA, NHL, NFL, NCAAF full-game lines). Longest prefix first: KXNCAAF before KXNFL is
# not an issue (no shared prefix), but the order is explicit anyway.
SPORT_OF_PREFIX: tuple[tuple[str, str], ...] = (("KXNCAAF", "ncaaf"), ("KXNBA", "nba"), ("KXNHL", "nhl"),
                                                ("KXNFL", "nfl"))
KIND_OF_SUFFIX = {"GAME": "h2h", "SPREAD": "spreads", "TOTAL": "totals"}
_SPREAD_TITLE = re.compile(r"^\s*(?P<team>.+?)\s+wins\s+by\s+over\s+(?P<n>[0-9]+(?:\.[0-9]+)?)\s+\w+\s*$", re.I)
_TOTAL_TITLE = re.compile(r"^\s*over\s+(?P<n>[0-9]+(?:\.[0-9]+)?)\s+\w+\s*$", re.I)
_MARKET_BASE = {"h2h": "h2h", "spreads": "spreads", "spreads_alt": "spreads", "totals": "totals",
                "totals_alt": "totals"}


def _ts(value: Any) -> float | None:
    """ISO time -> epoch seconds (UTC), or None."""
    if value in (None, ""):
        return None
    try:
        d = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.timestamp()


def iso(epoch: float | None) -> str | None:
    return None if epoch is None else datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()


def _price(value: Any) -> float | None:
    try:
        p = float(value)
    except (TypeError, ValueError):
        return None
    return p if 0.0 < p < 1.0 else None


def _logit(p: float) -> float:
    q = min(1.0 - 1e-6, max(1e-6, float(p)))
    return math.log(q / (1.0 - q))


def _sigmoid(x: float) -> float:
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    e = math.exp(x)
    return e / (1.0 + e)


def bump(stats: dict[str, int], key: str, n: int = 1) -> None:
    stats[key] = stats.get(key, 0) + n


# ----------------------------------------------------------------------------- the recorder's Kalshi markets


def series_sport_kind(series: str) -> tuple[str, str] | None:
    s = str(series or "").strip().upper()
    for prefix, sport in SPORT_OF_PREFIX:
        if s.startswith(prefix):
            kind = KIND_OF_SUFFIX.get(s[len(prefix):])
            return (sport, kind) if kind else None
    return None


@dataclass(slots=True)
class Market:
    """One Kalshi market as the recorder saw it: every quote in receive-time order, and its result once finalized."""

    ticker: str
    series: str
    sport: str
    kind: str                       # h2h | spreads | totals
    sub: str = ""                   # Kalshi's yes-subtitle: the club (GAME), "<club> wins by over s points", "Over L"
    strike: float | None = None     # Kalshi's floor strike (spreads / totals)
    ts: list[float] = field(default_factory=list)
    ya: list[float | None] = field(default_factory=list)  # YES ask
    na: list[float | None] = field(default_factory=list)  # NO ask
    active: list[bool] = field(default_factory=list)
    result: str = ""                # "yes" / "no" once Kalshi finalized it, else ""

    def quote_valid(self, i: int) -> bool:
        """A two-sided, uncrossed, active quote."""
        ya, na = self.ya[i], self.na[i]
        return bool(self.active[i]) and ya is not None and na is not None and ya + na >= 1.0 - 1e-9

    def mid_yes(self, i: int) -> float:
        return (self.ya[i] + (1.0 - self.na[i])) / 2.0

    def first_at_or_after(self, t: float) -> int | None:
        import bisect

        i = bisect.bisect_left(self.ts, t)
        return i if i < len(self.ts) else None

    def last_at_or_before(self, t: float) -> int | None:
        import bisect

        i = bisect.bisect_right(self.ts, t) - 1
        return i if i >= 0 else None

    def settled_at(self) -> float | None:
        """When the market stopped trading for good: the receive time of the first non-active quote after its LAST
        active one, when Kalshi's result is known. A pause the market came back from is not a settlement."""
        if self.result not in ("yes", "no"):
            return None
        last_active = max((i for i, a in enumerate(self.active) if a), default=None)
        if last_active is None or last_active + 1 >= len(self.ts):
            return None
        return self.ts[last_active + 1]


def load_recorder(path: Path, sport: str, stats: dict[str, int] | None = None,
                  tickers: set[str] | None = None) -> dict[str, Market]:
    """The recorder's `kalshi.jsonl`, this sport's GAME / SPREAD / TOTAL markets only, quotes sorted by receive time."""
    stats = stats if stats is not None else {}
    out: dict[str, Market] = {}
    sport = str(sport or "").strip().lower()
    with Path(path).open(encoding="utf-8") as fh:
        for line in fh:
            try:
                r = json.loads(line)
            except ValueError:
                bump(stats, "recorder_bad_line")
                continue
            t = str(r.get("t") or "")
            series = t.split("-", 1)[0].upper()
            sk = series_sport_kind(series)
            if sk is None or sk[0] != sport:
                continue
            if tickers is not None and t not in tickers:
                continue
            ts = _ts(r.get("ts"))
            if ts is None:
                bump(stats, "recorder_no_ts")
                continue
            m = out.get(t)
            if m is None:
                fs = r.get("fs")
                try:
                    strike = None if fs is None else float(fs)
                except (TypeError, ValueError):
                    strike = None
                m = out[t] = Market(ticker=t, series=series, sport=sport, kind=sk[1], sub=str(r.get("sub") or ""),
                                    strike=strike)
            m.ts.append(ts)
            m.ya.append(_price(r.get("ya")))
            m.na.append(_price(r.get("na")))
            m.active.append(str(r.get("st") or "").strip().lower() == "active")
            res = str(r.get("res") or "").strip().lower()
            if res in ("yes", "no"):
                m.result = res
            bump(stats, "recorder_rows")
    for m in out.values():
        if any(b < a for a, b in zip(m.ts, m.ts[1:])):
            order = sorted(range(len(m.ts)), key=m.ts.__getitem__)
            m.ts = [m.ts[i] for i in order]
            m.ya = [m.ya[i] for i in order]
            m.na = [m.na[i] for i in order]
            m.active = [m.active[i] for i in order]
    stats["recorder_markets"] = len(out)
    return out


@dataclass(slots=True)
class Placed:
    market: Market
    orient: int     # +1: p(our side) = mid(YES); -1: p(our side) = 1 - mid(YES)


class KalshiIndex:
    """One sport-slate's recorded Kalshi markets, each placed on one of our games (by the ledger's event id) and
    oriented to our side, by the order path's resolver. `stats` names what happened to every market."""

    def __init__(self, markets: Mapping[str, Market], sport: str, games: Sequence[Mapping[str, Any]]) -> None:
        from syndicate.features.shared import kalshi_catalogue as kc
        from syndicate.features.shared.kalshi_board_join import (
            _resolve_event,
            _side_for_team,
            build_club_code_collisions,
            build_club_code_names,
            build_event_club_code_names,
        )

        self.sport = str(sport or "").strip().lower()
        self.by_key: dict[tuple[str, str, float], list[Placed]] = {}
        self.stats: dict[str, int] = {}
        if not markets:
            return
        # The sport of a series is learned the way the worker learns it (never overwriting a hand-written entry).
        kc.register_discovered({m.series: self.sport for m in markets.values() if kc.sport_for_series(m.series) is None})
        rows = [{"ticker": t, "series": m.series, "title": f"{m.sub} wins" if m.kind == "h2h" and m.sub else None}
                for t, m in markets.items()]
        code_names = build_club_code_names(rows)
        collided = build_club_code_collisions(rows)
        event_names = build_event_club_code_names(rows)
        games_list = [dict(g) for g in games if isinstance(g, Mapping)]
        memo: dict = {}
        for t, m in sorted(markets.items()):
            result = _resolve_event({"ticker": t, "series": m.series, "title": None}, (), code_names, games=games_list,
                                    memo=memo, collided=collided, event_names=event_names)
            status = str((result or {}).get("status") or "error")
            if status != "ok":
                bump(self.stats, f"unresolved_{status}")
                continue
            if str(result.get("sport") or "").strip().lower() != self.sport:
                bump(self.stats, "resolved_to_another_sport")
                continue
            event_id = str(result.get("event_id") or "")
            if not event_id:
                bump(self.stats, "resolved_without_event_id")
                continue
            if m.kind == "totals":
                hit = _TOTAL_TITLE.match(m.sub)
                if not hit or m.strike is None or abs(float(hit.group("n")) - m.strike) > 1e-9:
                    bump(self.stats, "total_title_or_strike_unreadable")
                    continue
                key, orient = (event_id, "totals", m.strike + 0.0), 1
            else:
                if m.kind == "spreads":
                    hit = _SPREAD_TITLE.match(m.sub)
                    if not hit or m.strike is None or abs(float(hit.group("n")) - m.strike) > 1e-9:
                        bump(self.stats, "spread_title_or_strike_unreadable")
                        continue
                    team = hit.group("team")
                else:
                    team = m.sub
                side = _side_for_team(team, result, sport=self.sport)
                if side not in ("home", "away"):
                    bump(self.stats, "team_side_unresolved")
                    continue
                orient = 1 if side == "home" else -1
                if m.kind == "h2h":
                    key = (event_id, "h2h", 0.0)
                else:
                    key = (event_id, "spreads", (m.strike if side == "home" else -m.strike) + 0.0)
            self.by_key.setdefault(key, []).append(Placed(market=m, orient=orient))
            bump(self.stats, "indexed")
        # A moneyline is listed once per club: the two are one proposition, so the home-named market is the one we
        # trade (its NO is the other side). Anything else sharing a key is two contracts we cannot tell apart.
        for key in list(self.by_key):
            placed = self.by_key[key]
            if len(placed) == 1:
                continue
            if key[1] == "h2h" and sorted(p.orient for p in placed) == [-1, 1]:
                self.by_key[key] = [p for p in placed if p.orient == 1]
                continue
            bump(self.stats, "ambiguous_key", len(placed))
            self.by_key[key] = []

    def place(self, event_id: str, market: str, line: float | None) -> Placed | None:
        base = _MARKET_BASE.get(str(market or ""))
        if base is None:
            return None
        key_line = 0.0 if base == "h2h" else (None if line is None else float(line) + 0.0)
        if key_line is None:
            return None
        placed = self.by_key.get((str(event_id), base, key_line)) or []
        return placed[0] if len(placed) == 1 else None


# ----------------------------------------------------------------------------- the M2 verdict and reproduction


def pass_strata(verdict_line: str) -> tuple[set[str], set[str]]:
    """(live `sport|family`, pregame `sport|family`) named by an `M2_VERDICT PASS` line. Anything but a PASS raises."""
    line = str(verdict_line or "").strip()
    hit = re.search(r"M2_VERDICT PASS judged=\d+ pass=\d+ \[(?P<items>[^\]]*)\]", line)
    if not hit:
        raise ValueError(f"not an M2_VERDICT PASS line: {line[:120]!r}")
    live, pregame = set(), set()
    for item in (x.strip() for x in hit.group("items").split(",")):
        if not item:
            continue
        m = re.fullmatch(r"(?P<sport>[a-z0-9_]+)\|(?P<family>[a-z0-9_]+)\|(?P<rest>[^()]+)\((?P<truth>\w+)\)", item)
        if not m:
            raise ValueError(f"unreadable PASS stratum {item!r}")
        rest, truth = m.group("rest"), m.group("truth")
        key = f"{m.group('sport')}|{m.group('family')}"
        if rest == f"live|{FRESH_STRATUM}" and truth == "outcome":
            live.add(key)
        elif rest == "pregame" and truth == "close":
            pregame.add(key)
        else:
            raise ValueError(f"PASS stratum of no registered shape {item!r}")
    return live, pregame


# Amendment 2's attribution (m2_gate.py sha256 c1a2c029...), applied per M3 slate.
REPRO_LINES = (
    ("CHECKLIST", re.compile(r"^\s+CHECKLIST (\S+) (pregame|live|stat_progress|live_segment) ok=\S+ alarms=(\d+)")),
    ("JOIN", re.compile(r"^\s+JOIN (\S+) half_point checked=\d+ mismatched=(\d+)")),
    ("FALLBACK_FRAME", re.compile(r"^\s+FALLBACK_FRAME (\S+) judged=\d+ failed=(\d+)")),
    ("PRIOR", re.compile(r"^\s+PRIOR (\S+) checked=\d+ prior_mismatched=(\d+) p_mismatched=(\d+)")),
    ("SEG_JOIN", re.compile(r"^\s+SEG_JOIN (\S+) half_point checked=\d+ mismatched=(\d+)")),
    ("SEG_PRIOR", re.compile(r"^\s+SEG_PRIOR (\S+) checked=\d+ mismatched=(\d+)")),
)
RESULT_RE = re.compile(r"^RESULT date=(\S+) opinions=\d+ alarms_plus_mismatches=(\d+) exit=([01])\s*$")


def reproduction(lines: Iterable[str], d: str) -> tuple[int | None, dict[tuple[str, str], dict[str, int]], int]:
    """(RESULT's alarms_plus_mismatches or None, {(sport, phase): {check: n > 0}}, attributed total)."""
    total = None
    fails: dict[tuple[str, str], dict[str, int]] = {}
    attributed = 0
    for line in lines:
        r = RESULT_RE.match(line)
        if r and r.group(1) == d:
            n, ex = int(r.group(2)), int(r.group(3))
            total = n if (n == 0) == (ex == 0) else None
            continue
        for name, rx in REPRO_LINES:
            m = rx.match(line)
            if not m:
                continue
            sport = m.group(1)
            if name == "CHECKLIST":
                phase, n = ("pregame" if m.group(2) == "pregame" else "live"), int(m.group(3))
            elif name == "PRIOR":
                phase, n = "live", int(m.group(2)) + int(m.group(3))
            else:
                phase, n = "live", int(m.group(2))
            if n:
                fails.setdefault((sport, phase), {})
                fails[(sport, phase)][name] = fails[(sport, phase)].get(name, 0) + n
                attributed += n
            break
    return total, fails, attributed


# ----------------------------------------------------------------------------- one slate's replay


@dataclass(slots=True)
class Candidate:
    """One eligible live line at one decision instant, with the learner's frozen numbers."""

    sport: str
    event_id: str
    family: str
    market: str
    line: float | None
    tick: str                 # the opinion's `t` (the line's instant)
    t_d: float                # the decision instant: the tick, or the evidence state's own time if later (epoch)
    p_prior: float
    p_decision: float
    prior_age_s: float | None

    @property
    def adjustment(self) -> float:
        return _logit(self.p_decision) - _logit(self.p_prior)

    @property
    def game(self) -> str:
        return f"{self.sport}|{self.event_id}"

    @property
    def stratum(self) -> str:
        return f"{self.sport}|{self.family}|live|{FRESH_STRATUM}"


def taker_fee(ask: float, series: str) -> tuple[float, bool]:
    """(Kalshi's taker fee per contract on a 10-contract order at `ask`, the series multiplier was unresolved).
    The multiplier is the series' own; an unresolved series pays the full rate (understating a fee invents edge)."""
    from syndicate.features.shared.venue_fees import kalshi_fee_multiplier_for_series, kalshi_taker_fee_dollars

    mult = kalshi_fee_multiplier_for_series(series)
    unresolved = mult is None
    return kalshi_taker_fee_dollars(FEE_CONTRACTS, ask, fee_multiplier=1.0 if unresolved else mult) / FEE_CONTRACTS, \
        unresolved


def side_prices(placed: Placed, i: int) -> dict[str, Any]:
    """At quote `i`: our side's mid and asks, oriented. 'our' is the opinion's side; 'other' its complement."""
    m = placed.market
    mid_yes = m.mid_yes(i)
    if placed.orient > 0:
        return {"m_our": mid_yes, "our": ("yes", m.ya[i]), "other": ("no", m.na[i])}
    return {"m_our": 1.0 - mid_yes, "our": ("no", m.na[i]), "other": ("yes", m.ya[i])}


def _choose(p_our: float, prices: Mapping[str, Any], series: str) -> dict[str, Any] | None:
    """The side to buy at these asks, or None: our side if p - ask - fee >= floor, else the other side if
    (1 - p) - ask - fee >= floor. An ask outside [ASK_MIN, ASK_MAX] is not taken."""
    for which, p in (("our", p_our), ("other", 1.0 - p_our)):
        side, ask = prices[which]
        if ask is None or not ASK_MIN <= ask <= ASK_MAX:
            continue
        fee, unresolved = taker_fee(ask, series)
        edge = p - ask - fee
        if edge >= EDGE_FLOOR - 1e-12:
            return {"which": which, "side": side, "ask": ask, "fee": fee, "fee_unresolved": unresolved,
                    "p_side": p, "edge": edge}
    return None


def mark(placed: Placed, side: str, t_entry: float) -> dict[str, Any]:
    """The bought side's value 300..420 s after entry: the mid of the first quote received in that window, or the
    settlement (1 / 0) when the market settled first; else unmarked."""
    m = placed.market
    settled = m.settled_at()
    win = 1.0 if m.result == side else 0.0
    i = m.first_at_or_after(t_entry + MARK_FROM_S)
    if settled is not None and settled <= t_entry + MARK_TO_S and (i is None or settled <= m.ts[i]):
        return {"value": win, "kind": "settled", "t": settled}
    if i is not None and m.ts[i] <= t_entry + MARK_TO_S and m.quote_valid(i):
        mid_yes = m.mid_yes(i)
        return {"value": mid_yes if side == "yes" else 1.0 - mid_yes, "kind": "mid", "t": m.ts[i]}
    return {"value": None, "kind": "unmarked", "t": None}


def frame_check(cands: Sequence[Candidate], index: KalshiIndex) -> dict[str, dict[str, Any]]:
    """Per family: on line-instants with both a fresh book prior and a standing Kalshi quote (<= 60 s old at t_d), the
    median |book - Kalshi| in the chosen orientation must be below the flipped one's, over >= FRAME_MIN_LINES."""
    by_family: dict[str, tuple[list[float], list[float]]] = {}
    for c in cands:
        placed = index.place(c.event_id, c.market, c.line)
        if placed is None:
            continue
        i = placed.market.last_at_or_before(c.t_d)
        if i is None or c.t_d - placed.market.ts[i] > FRAME_QUOTE_MAX_AGE_S or not placed.market.quote_valid(i):
            continue
        m_our = side_prices(placed, i)["m_our"]
        chosen, flipped = by_family.setdefault(c.family, ([], []))
        chosen.append(abs(c.p_prior - m_our))
        flipped.append(abs(c.p_prior - (1.0 - m_our)))
    out: dict[str, dict[str, Any]] = {}
    for fam, (chosen, flipped) in sorted(by_family.items()):
        n = len(chosen)
        dc, df = (median(chosen), median(flipped)) if n else (None, None)
        # A tie (every line at 50/50) cannot tell the two orientations apart: unverified, not flipped.
        verdict = ("unverified" if n < FRAME_MIN_LINES or dc == df else "ok" if dc < df else "FLIPPED")
        out[fam] = {"lines": n, "median_chosen": None if dc is None else round(dc, 4),
                    "median_flipped": None if df is None else round(df, 4), "verdict": verdict}
    return out


def replay(cands: Sequence[Candidate], index: KalshiIndex, *, date: str, stats: dict[str, int] | None = None
           ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Every arm's entries for one sport-slate. Returns (bets, report)."""
    stats = stats if stats is not None else {}
    frame = frame_check(cands, index)
    bets: list[dict[str, Any]] = []
    for arm in ARMS:
        entered: set[tuple[str, str]] = set()     # (game, ticker): one entry per game and market
        groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
        for c in sorted(cands, key=lambda c: (c.t_d, c.event_id, c.market, c.line or 0.0)):
            if frame.get(c.family, {}).get("verdict") != "ok":
                bump(stats, f"{arm}:frame_{frame.get(c.family, {}).get('verdict', 'unverified')}")
                continue
            if abs(c.adjustment) <= 1e-12:
                bump(stats, f"{arm}:no_adjustment")
                continue
            placed = index.place(c.event_id, c.market, c.line)
            if placed is None:
                bump(stats, f"{arm}:no_kalshi_market")
                continue
            m = placed.market
            if (c.game, m.ticker) in entered:
                bump(stats, f"{arm}:already_entered")
                continue
            i = m.first_at_or_after(c.t_d + LATENCY_S)
            if i is None or m.ts[i] > c.t_d + ENTRY_WINDOW_S:
                bump(stats, f"{arm}:no_quote_in_entry_window")
                continue
            if not m.quote_valid(i):
                bump(stats, f"{arm}:entry_quote_invalid")
                continue
            prices = side_prices(placed, i)
            p_our = _sigmoid(_logit(prices["m_our"]) + c.adjustment) if arm == ARM_A1 else c.p_decision
            pick = _choose(p_our, prices, m.series)
            if pick is None:
                bump(stats, f"{arm}:below_floor")
                continue
            groups.setdefault((c.tick, c.game, c.family), []).append(
                {"c": c, "placed": placed, "i": i, "prices": prices, "p_our": p_our, "pick": pick})
        for (_tick, _game, _fam), options in sorted(groups.items(), key=lambda kv: min(o["c"].t_d for o in kv[1])):
            options = [o for o in options if (o["c"].game, o["placed"].market.ticker) not in entered]
            if not options:
                continue
            best = max(options, key=lambda o: (o["pick"]["edge"], o["placed"].market.ticker))
            bump(stats, f"{arm}:same_instant_not_best", len(options) - 1)
            c, placed, i, pick = best["c"], best["placed"], best["i"], best["pick"]
            m = placed.market
            entered.add((c.game, m.ticker))
            t_entry = m.ts[i]
            mk = mark(placed, pick["side"], t_entry)
            cost = pick["ask"] + pick["fee"]
            payout = None if m.result not in ("yes", "no") else (1.0 if m.result == pick["side"] else 0.0)
            bets.append({
                "v": M3_VERSION, "arm": arm, "date": date, "sport": c.sport, "game": c.game, "event_id": c.event_id,
                "stratum": c.stratum, "family": c.family, "market": c.market, "line": c.line, "ticker": m.ticker,
                "orient": placed.orient, "side": pick["side"], "our_side": pick["which"] == "our",
                "tick": c.tick, "t_d": iso(c.t_d), "t_entry": iso(t_entry), "entry_lag_s": round(t_entry - c.t_d, 3),
                "ask": pick["ask"], "fee": round(pick["fee"], 6), "fee_unresolved": pick["fee_unresolved"],
                "cost": round(cost, 6), "p_used": round(pick["p_side"], 6), "edge": round(pick["edge"], 6),
                "m_our_entry": round(best["prices"]["m_our"], 6), "adjustment": round(c.adjustment, 6),
                "p_decision": round(c.p_decision, 6), "p_prior": round(c.p_prior, 6), "prior_age_s": c.prior_age_s,
                "mark_kind": mk["kind"], "mark_t": iso(mk["t"]),
                "mark_value": None if mk["value"] is None else round(mk["value"], 6),
                "markout": None if mk["value"] is None else round(mk["value"] - cost, 6),
                "result": m.result, "payout": payout,
                "roi": None if payout is None else round((payout - cost) / cost, 6),
            })
            bump(stats, f"{arm}:entered")
    return bets, {"frame": frame, "index": dict(index.stats), "stats": dict(stats)}


# ----------------------------------------------------------------------------- the gate


def clustered_z(values: Sequence[float], clusters: Sequence[str]) -> dict[str, Any]:
    """Mean, game-clustered SE and z: SE = sqrt(sum_g S_g^2) / n * sqrt(G / (G - 1)), S_g = the game's summed
    residuals."""
    n = len(values)
    games = sorted(set(clusters))
    g = len(games)
    if n == 0:
        return {"n": 0, "games": 0, "mean": None, "se": None, "z": None}
    mean = sum(values) / n
    s: dict[str, float] = {}
    for x, c in zip(values, clusters):
        s[c] = s.get(c, 0.0) + (x - mean)
    se = math.sqrt(sum(v * v for v in s.values())) / n * (math.sqrt(g / (g - 1)) if g > 1 else float("inf"))
    z = mean / se if se and math.isfinite(se) and se > 0 else None
    return {"n": n, "games": g, "mean": mean, "se": se, "z": z}


def counts(bets: Sequence[Mapping[str, Any]], arm: str = ARM_A1) -> dict[str, int]:
    """What triggers a look: entries, games, unmarked. Reads no mark-out and no result."""
    mine = [b for b in bets if b.get("arm") == arm]
    return {"bets": len(mine), "games": len({b["game"] for b in mine}),
            "unmarked": sum(1 for b in mine if b.get("markout") is None)}


def due_look(c: Mapping[str, int], taken: Sequence[str], today: str) -> str | None:
    """The next look whose counts are reached, in order; or L3 at the calendar stop whatever the counts."""
    for name, n_bets, n_games, _hi, _lo in LOOKS:
        if name in taken:
            continue
        if c["bets"] >= n_bets and c["games"] >= n_games:
            return name
        break
    if today >= CALENDAR_STOP and "L3" not in taken:
        return "L3"
    return None


def look(bets: Sequence[Mapping[str, Any]], name: str) -> dict[str, Any]:
    """One registered look over arm A1: PASS / FAIL / CONTINUE / NOT_A_VERDICT / CONTRADICTION, with HARM per stratum
    and the reported arm A2 beside it."""
    spec = next(s for s in LOOKS if s[0] == name)
    _n, n_bets, n_games, hi, lo = spec
    a1 = [b for b in bets if b.get("arm") == ARM_A1]
    c = counts(bets)
    out: dict[str, Any] = {"look": name, "counts": c, "boundary": {"pass_z": hi, "fail_z": lo}}
    if c["bets"] and c["unmarked"] / c["bets"] > UNMARKED_MAX:
        out["verdict"] = "NOT_A_VERDICT"
        out["why"] = f"unmarked {c['unmarked']} of {c['bets']} > {UNMARKED_MAX:.0%}"
        return out
    marked = [b for b in a1 if b.get("markout") is not None]
    stat = clustered_z([b["markout"] for b in marked], [b["game"] for b in marked])
    out["markout"] = stat
    z = stat["z"]
    harm = []
    for stratum in sorted({b["stratum"] for b in marked}):
        rows = [b for b in marked if b["stratum"] == stratum]
        s = clustered_z([b["markout"] for b in rows], [b["game"] for b in rows])
        if s["n"] >= HARM_MIN_BETS and s["games"] >= HARM_MIN_GAMES and s["z"] is not None and s["z"] <= HARM_Z:
            harm.append(stratum)
        out.setdefault("by_stratum", {})[stratum] = s
    out["harm"] = harm
    a2 = [b for b in bets if b.get("arm") == ARM_A2 and b.get("markout") is not None]
    out["reported_A2"] = clustered_z([b["markout"] for b in a2], [b["game"] for b in a2])
    if z is None:
        out["verdict"] = "NOT_A_VERDICT"
        out["why"] = "no z (fewer than two games or zero variance)"
    elif z >= hi:
        settled = [b for b in a1 if b.get("roi") is not None]
        roi = clustered_z([b["roi"] for b in settled], [b["game"] for b in settled])
        out["roi"] = roi
        hi95 = None if roi["mean"] is None or roi["se"] is None else roi["mean"] + ROI_Z * roi["se"]
        out["roi_hi95"] = hi95
        out["verdict"] = "CONTRADICTION" if hi95 is not None and hi95 < 0 else "PASS"
    elif lo is None or z <= lo:
        out["verdict"] = "FAIL"
    else:
        out["verdict"] = "CONTINUE"
    return out
