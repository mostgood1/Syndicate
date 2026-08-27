"""Place a game-clock probe against the market line that was live at that moment.

**THIS IS THE STEP THAT TURNS AN ERROR CURVE INTO AN EDGE, OR KILLS IT.**
Everything measured in this lane so far -- momentum's null result, the interval
error curve, the final-minute split -- describes how close a projection lands to
the truth. None of it says whether the number was better than the price you could
have got, which is the only comparison a bet rests on.

## THE TWO CLOCKS

Game state is in GAME seconds since tip. Quotes are in WALL-CLOCK UTC. Neither
can be converted to the other by arithmetic -- a game's elapsed clock and the
world's clock diverge by every timeout, review and quarter break, and by a
variable pre-tip delay. The mapping has to be OBSERVED, and
`live_momentum_<date>.jsonl` is where it is: every append pairs a `generated_at`
wall clock with a per-game `as_of_seconds`.

So `clock_bridge` reads those pairs and interpolates between them. Outside their
range it returns None rather than extrapolating: a probe before the first
capture or after the last one has no observed anchor, and inventing one would
silently date a quote lookup to a moment nobody measured.

## WHY EVERY RESULT CARRIES ITS DATE COUNT

The coverage probe found the three families intersecting on ONE date. That is
the MLB trap `CLAUDE.md` records -- families that look like weeks and overlap on
a day. Any function here that returns a comparison also returns `dates`, and the
caller is expected to print it, because a market result computed on one date is
not a backtest and must never be able to look like one.

## WHAT THIS DOES NOT DO

It does not price, stake, or recommend. It reports where the projection and the
line disagreed and who was right. `model_engine_standard.md` binds before any of
it reaches a pricing path.
"""

from __future__ import annotations

from bisect import bisect_left
from typing import Any, Iterable, Mapping, Sequence

# A live quarter/half total is quoted for the WHOLE segment, points already
# scored included -- the same quantity `project_interval` calls
# `proj_period_total`. Anything else here would be comparing two different bets.
PERIOD_SEGMENTS = ("q1", "q2", "q3", "q4")


def clock_bridge(pairs: Sequence[tuple[float, float]]) -> Any:
    """Build wall-clock -> game-seconds lookup from OBSERVED pairs.

    `pairs` is (epoch_seconds, game_seconds), in any order. Returns a callable
    taking game seconds and returning epoch seconds, or None when the probe
    falls outside the observed range.

    **NO EXTRAPOLATION, DELIBERATELY.** A probe before the first capture or
    after the last has no anchor. Extending the nearest slope past the edge
    would produce a confident timestamp for a moment nobody observed, and the
    quote lookup it feeds would then silently select the wrong line -- which
    looks exactly like a model being wrong.
    """
    clean = sorted({(float(g), float(w)) for w, g in pairs or ()})
    if not clean:
        return lambda _game_seconds: None
    games = [g for g, _ in clean]
    walls = [w for _, w in clean]

    def _at(game_seconds: float) -> float | None:
        t = float(game_seconds)
        if t < games[0] or t > games[-1]:
            return None
        i = bisect_left(games, t)
        if i < len(games) and games[i] == t:
            return walls[i]
        lo, hi = i - 1, i
        span = games[hi] - games[lo]
        if span <= 0:
            return walls[lo]
        frac = (t - games[lo]) / span
        return walls[lo] + frac * (walls[hi] - walls[lo])

    return _at


def line_as_of(
    quotes: Iterable[Mapping[str, Any]],
    *,
    segment: str,
    as_of_epoch: float,
) -> float | None:
    """The market's line for `segment`, as it stood at `as_of_epoch`.

    **STRICTLY AT OR BEFORE.** A quote captured one second later is a price that
    did not exist yet, and using it is lookahead -- the most flattering bug
    available to a betting backtest, and one that produces a beautiful result
    from nothing.

    Reduced across books by the LOWER-MIDDLE median, matching
    `period_lines._median_line` rather than inventing a second rule: these are
    LINES, not prices, so "best" is undefined without a side, and averaging
    invents a number no book is offering.
    """
    want = str(segment or "").strip().lower()
    latest: dict[str, tuple[float, float]] = {}
    for row in quotes or ():
        if str(row.get("segment") or "").strip().lower() != want:
            continue
        if str(row.get("market") or "").strip().lower() != "totals":
            continue
        line = row.get("line")
        stamp = row.get("captured_epoch")
        if line is None or stamp is None:
            continue
        stamp = float(stamp)
        if stamp > float(as_of_epoch):
            continue
        book = str(row.get("bookmaker") or "").strip().lower()
        if not book:
            continue
        seen = latest.get(book)
        if seen is None or stamp >= seen[0]:
            latest[book] = (stamp, float(line))
    if not latest:
        return None
    values = sorted(v for _, v in latest.values())
    return values[(len(values) - 1) // 2]


def compare(projection: float, line: float, truth: float) -> dict[str, Any]:
    """Did the projection beat the line, on the side it actually took?

    `edge` is signed toward OVER. A push -- truth exactly on the line -- is
    neither won nor lost and is reported as its own outcome, because folding it
    into either column moves a win rate by the number of pushes and a
    half-point line produces them constantly.
    """
    edge = float(projection) - float(line)
    side = "over" if edge > 0 else ("under" if edge < 0 else "none")
    if float(truth) == float(line):
        outcome = "push"
    elif side == "none":
        outcome = "none"
    elif (float(truth) > float(line)) == (side == "over"):
        outcome = "win"
    else:
        outcome = "loss"
    return {"edge": round(edge, 3), "side": side, "outcome": outcome}


def summarise(rows: Sequence[Mapping[str, Any]], *, dates: Sequence[str]) -> dict[str, Any]:
    """Win rate by |edge| bucket, and THE DATE COUNT, inseparably.

    `dates` is not decoration. The families this reads intersect narrowly, and a
    win rate over a handful of games on one date is noise wearing a percentage.
    Returning them together means a caller cannot print one without the other
    unless it goes out of its way to.
    """
    buckets = ((0.0, 1.0), (1.0, 2.0), (2.0, 4.0), (4.0, 999.0))
    out: list[dict[str, Any]] = []
    for lo, hi in buckets:
        picked = [r for r in rows
                  if r.get("outcome") in ("win", "loss")
                  and lo <= abs(float(r.get("edge") or 0.0)) < hi]
        if not picked:
            continue
        wins = sum(1 for r in picked if r["outcome"] == "win")
        out.append({"edge_lo": lo, "edge_hi": hi, "n": len(picked),
                    "wins": wins, "win_rate": round(wins / len(picked), 4)})
    graded = [r for r in rows if r.get("outcome") in ("win", "loss")]
    return {
        "dates": list(dates),
        "date_count": len(dates),
        "rows": len(rows),
        "graded": len(graded),
        "pushes": sum(1 for r in rows if r.get("outcome") == "push"),
        "buckets": out,
        # **THE BREAK-EVEN A BET ACTUALLY FACES**, stated next to the win rate so
        # nobody reads 52% as a win. Standard -110 juice.
        "break_even_at_minus_110": 0.5238,
    }
