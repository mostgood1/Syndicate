"""NCAAF LIVE TOTAL CALIBRATION: the re-sim's final-total draws anchored to the market's close and widened (todo #835).

`[2026-11-19, lane ncaaf-live-total-dispersion; findings `.syndicate/findings_2026-11-19_ncaaf_live_total_dispersion.md`]`

ABSENT IS OFF. `SYNDICATE_NCAAF_LIVE_TOTAL_CALIBRATION=on` (1 / true / yes) switches it on. Off, nothing here runs and
the published lane is byte-identical.

--------------------------------------------------------------------------
WHAT WAS WRONG (dev 11-14, measured against Kalshi's in-play strike ladder and against the finals)
--------------------------------------------------------------------------
The engine read (`findings_2026-11-17_engine_read_kalshi.md`) found the live re-sim's NCAAF totals the most
over-confident cell it read: calibration slope 0.41 against Kalshi's 1.35, log loss +0.077 (se 0.054). Two causes,
and the second is the bigger one:

1. THE SPREAD is ~15-25% narrower than Kalshi's at every stage (sd ratio 0.85 / 0.81 / 0.84 / 0.75 by quarter of
   game time). Widening alone by 1.2x closes it (1.02 / 0.97 / 1.00; 0.99 late on a like-for-like probit read) but
   lifts the slope only to 0.51.
2. THE CENTRE is per-game noise. The live engine's own kickoff total sits a mean 5.7 points from the closing
   consensus total (correlation 0.43 over 55 games): the live level shrink (`total_level.py`, 0.3) compresses each
   game's level toward the league, and the market knows the game. The re-sim's centre was 4.0 points from Kalshi's at
   the median early in games. Kalshi's own centre sits 0.4 from the close at kickoff.

THE FIX is two estimator steps on the 120 draws the engine already produced (`model_engine_standard.md` 4.4: no new
mechanism, no engine input changes):

    anchor   every draw moves by (C - E0) x rho          C   = the closing consensus full-game total
                                                          E0  = the live engine's own total at kickoff, same ratings
                                                          rho = the share of regulation still to play
    widen    every draw's distance from the (moved) mean is multiplied by K (1.2 to half-time, rising to 1.6 at 95%
             of regulation), then floored at the score already on the board (points cannot be taken back) without
             letting the floor move the mean

MEASURED (findings): on 11-14 the sd ratio reads 1.02 / 0.97 / 1.05 / 0.96 by quarter of game time, the slope 0.95
(from 0.41), log loss vs Kalshi +0.014 (from +0.077). Against the finals of 109 games on the three Saturdays before,
the slope goes 0.41 -> 0.94, and the PRICED probability beats today's (raw x #780's k 2.48) by -0.026 nats (se 0.009).

WHERE IT RUNS: `calibrate_snapshot_totals`, a post-pass on the built snapshot inside the worker's NCAAF tick
(`run_refresh_worker._run_ncaaf_live_resim_tick`), before the snapshot is written -- on the tick's own ratings, so E0
is the same engine on the same inputs. `live_resim.py` itself is unchanged.

The anchor is #834's NBA rule (`nba/live_resim.anchor_total_result`) on NCAAF: at kickoff the total IS the close, and
the engine's game-state information (score, possession, clock) moves it from there exactly as before. E0 is the
re-sim itself at Q1 15:00, 0-0, possession unknown -- the resume-at-kickoff identity (`live_resim` docstring) -- so it
is the engine's own level, not the pregame artifact's (that one runs the PREGAME shrink, 0.5).

NOT FIXED HERE, AND NAMED: the engine's late-game scoring surge. At 75-95% of game time the re-sim expects the rest of
the game at 1.29x the close's even pace where Kalshi expects 0.82x, and the anchor does not touch it (its offset is
already small by then). It lives in smartsim2's end-game (no kneel-out or clock management for NCAAF: #808's
mechanisms are off there), which is an engine mechanism and a re-fit, not an estimator.

--------------------------------------------------------------------------
WHAT IT LEAVES ALONE
--------------------------------------------------------------------------
The margin, the win probability, the segment blocks (display only; under the switch h1 + h2 no longer sums to the
full-game draw) and `total_mean_uncalibrated` (the engine's own mean, kept so a reader can always recover it).
A game with no close, or no E0, is still WIDENED and carries `anchorRefusal` naming why.

THE JOIN'S k. `live_gameline_join._TOTALS_PROB_SCALE_BY_SPORT["ncaaf"]` (2.48, #780) tempers the engine's P(over)
for pricing; it was fitted on the UN-calibrated totals, whose over-confidence it absorbs. Switching this on without
re-fitting it would correct the same over-confidence twice. On the calibrated totals the best join k is 1.05 (flat
over 1.0-1.1): load `SYNDICATE_LIVE_TOTALS_PROB_SCALE_NCAAF=1` WITH this switch, in the same betting-change window.
"""

from __future__ import annotations

import math
import os
import time
from typing import Any, Callable, Iterable, Mapping, Optional

SWITCH_ENV = "SYNDICATE_NCAAF_LIVE_TOTAL_CALIBRATION"
K_ENV = "SYNDICATE_NCAAF_LIVE_TOTAL_CALIBRATION_K"
K_LATE_ENV = "SYNDICATE_NCAAF_LIVE_TOTAL_CALIBRATION_K_LATE"
#: The spread multiplier through half-time. 1.2 is #835's own estimate (Kalshi's sd over the re-sim's, 1.18-1.33 by
#: stage); on 11-14 it reads sd ratio 1.02 / 0.97 / 1.00 against Kalshi's ladder.
DEFAULT_K = 1.2
#: ... rising linearly to this at 95% of regulation (and held after). Against the finals of 109 games on the three
#: Saturdays before 11-14, the last quarter of game time stays over-confident at a flat 1.2 (calibration slope 0.56);
#: a late 1.5 / 1.6 / 1.8 lifts it to 0.69 / 0.73 / 0.81. 1.6 puts the 11-14 late sd ratio against Kalshi's ladder at
#: 0.96 (1.5: 0.93, 1.8: 1.02) while staying nearer Kalshi's like-for-like width (probit ratio 1.20; 1.8: 1.28).
DEFAULT_K_LATE = 1.6
_RAMP_FROM, _RAMP_TO = 0.5, 0.95
_ON = frozenset({"1", "true", "on", "yes"})
_QUARTER_SECONDS = 900
_REGULATION_SECONDS = 4 * _QUARTER_SECONDS
#: The quote log grows all day; re-read the closes at most this often (NBA's anchor uses the same order of magnitude).
_CLOSE_TTL_S = 600.0

_CLOSE_SOURCES: dict[str, tuple[float, Any]] = {}
_E0_CACHE: dict[tuple, float] = {}


def enabled(env: Optional[Mapping[str, str]] = None) -> bool:
    raw = str((env if env is not None else os.environ).get(SWITCH_ENV, "") or "").strip().lower()
    return raw in _ON


def _k_from(env: Optional[Mapping[str, str]], name: str, default: float) -> float:
    raw = str((env if env is not None else os.environ).get(name, "") or "").strip()
    try:
        value = float(raw) if raw else default
    except ValueError:
        return default
    return value if value > 0.0 and math.isfinite(value) else default


def spread_k(env: Optional[Mapping[str, str]] = None) -> float:
    """K through half-time; an unparseable or non-positive override falls back to the default, never to 'no
    widening' (a knob that can be typo'd into a different behaviour is the shape `#603` shipped inert twice)."""
    return _k_from(env, K_ENV, DEFAULT_K)


def spread_k_late(env: Optional[Mapping[str, str]] = None) -> float:
    """K at 95% of regulation and after; same fallback rule."""
    return _k_from(env, K_LATE_ENV, DEFAULT_K_LATE)


def k_at(remaining_share: float, *, k_early: float, k_late: float) -> float:
    """K at a resume point: `k_early` until half-time, then linear to `k_late` at 95% of regulation, held after."""
    played = 1.0 - max(0.0, min(1.0, float(remaining_share)))
    t = max(0.0, min(1.0, (played - _RAMP_FROM) / (_RAMP_TO - _RAMP_FROM)))
    return float(k_early) + (float(k_late) - float(k_early)) * t


def remaining_regulation_share(period: Any, clock_seconds: Any) -> float:
    """The share of regulation still to play, in [0, 1]. Overtime (period > 4) has none."""
    try:
        per, clk = int(period), float(clock_seconds)
    except (TypeError, ValueError):
        return 0.0
    if per < 1:
        return 1.0
    if per > 4:
        return 0.0
    left = (4 - per) * _QUARTER_SECONDS + max(0.0, min(float(_QUARTER_SECONDS), clk))
    return max(0.0, min(1.0, left / _REGULATION_SECONDS))


def _round_preserving_sum(values: list[float]) -> list[int]:
    """Each value to an integer within 1 of it, with the TOTAL kept to within 0.5 (cumulative rounding, the margin
    anchor's rule). `floor(x + 0.5)`, not `round`: banker's rounding would let one integer step become two."""
    out: list[int] = []
    cumulative = 0.0
    allocated = 0
    for value in values:
        cumulative += value
        target = math.floor(cumulative + 0.5)
        out.append(int(target - allocated))
        allocated = target
    return out


def calibrate_total_draws(totals: Iterable[int], *, score_so_far: int, remaining_share: float,
                          anchor_offset: Optional[float], k: float) -> list[int]:
    """The draws moved by `anchor_offset * remaining_share` (None = no anchor) and widened by `k` around the moved
    mean, floored at `score_so_far`. Same count, order of the sorted draws kept.

    THE FLOOR MUST NOT MOVE THE CENTRE. Late in a game many draws sit at or near the score, and widening pushes some
    below it; flooring those alone raised the 11-14 replay's 75-95% mean by ~0.3 points -- a centre change made by a
    spread step. So the excess the floor adds is taken back from the draws above it (a few passes), and the mean stays
    the moved mean whenever that is reachable."""
    draws = sorted(int(x) for x in totals)
    if not draws:
        return []
    rho = max(0.0, min(1.0, float(remaining_share)))
    delta = 0.0 if anchor_offset is None else float(anchor_offset) * rho
    target = sum(draws) / len(draws) + delta
    floor_at = float(score_so_far)
    moved = [max(floor_at, target + float(k) * (x + delta - target)) for x in draws]
    for _ in range(4):
        excess = sum(moved) / len(moved) - max(target, floor_at)
        above = [i for i, v in enumerate(moved) if v > floor_at]
        if excess <= 1e-9 or not above:
            break
        cut = excess * len(moved) / len(above)
        for i in above:
            moved[i] = max(floor_at, moved[i] - cut)
    return [max(int(score_so_far), v) for v in _round_preserving_sum(moved)]


def histogram(draws: Iterable[int]) -> dict[str, int]:
    out: dict[str, int] = {}
    for value in sorted(int(x) for x in draws):
        out[str(value)] = out.get(str(value), 0) + 1
    return out


# --------------------------------------------------------------------------
# THE ANCHOR'S TWO INPUTS
# --------------------------------------------------------------------------

def _closing_totals(date: str) -> Mapping[Any, Any]:
    from syndicate.features.college_basketball.prior_calibration import closing_totals

    return closing_totals("ncaaf", str(date))


def _close_map(date: str, clock: Callable[[], float] = time.monotonic) -> Mapping[Any, Any]:
    hit = _CLOSE_SOURCES.get(str(date))
    if hit is not None and clock() - hit[0] < _CLOSE_TTL_S:
        return hit[1]
    try:
        market = _closing_totals(str(date))
    except Exception:  # noqa: BLE001 -- an unreadable log is "no closing total", named by the caller
        market = {}
    _CLOSE_SOURCES[str(date)] = (clock(), market)
    return market


def closing_total_for(dates: Iterable[str], home: str, away: str) -> Optional[tuple[float, int]]:
    """(closing consensus total, books) for the game, from the first of `dates` whose quote-log shard has it.

    Each book's last full-game OVER line before the commence, median across books
    (`college_basketball/prior_calibration.closing_totals`, the reader #834's NBA anchor uses). Keys are
    `_join_key('ncaaf', name)`, which maps the projections artifact's names onto the odds source's (55 of 58 dev
    11-14 games; the three misses were Friday games, whose quotes sit in the Friday shard -- hence the date list: the
    tick's own UTC date, then the day before, for the games still running after midnight UTC). A total has no
    orientation, so both key orders are tried."""
    from syndicate.features.ncaab.live_resim import _join_key

    h, a = _join_key("ncaaf", home), _join_key("ncaaf", away)
    for date in dates:
        market = _close_map(str(date))
        for key in ((h, a), (a, h)):
            hit = market.get(key)
            if hit is not None:
                try:
                    return float(hit[0]), int(hit[1])
                except (TypeError, ValueError, IndexError):
                    continue
    return None


def kickoff_total(cache_key: tuple, compute: Callable[[], Optional[float]]) -> Optional[float]:
    """E0, computed once per game per process (~2 s at 120 sims, measured on the fleet's data) and kept: the ratings
    behind it are fixed for the game, so it cannot change while the game runs."""
    if cache_key in _E0_CACHE:
        return _E0_CACHE[cache_key]
    value = compute()
    if value is not None and math.isfinite(float(value)):
        _E0_CACHE[cache_key] = float(value)
        return float(value)
    return None


def anchor_dates(date_str: str) -> list[str]:
    """The quote-log shards to look in: the tick's own date, then the day before (a game still running after midnight
    UTC was quoted, and closed, on the previous date's shard)."""
    from datetime import date, timedelta

    text = str(date_str or "")[:10]
    try:
        day = date.fromisoformat(text)
    except ValueError:
        return [text] if text else []
    return [day.isoformat(), (day - timedelta(days=1)).isoformat()]


def inputs_for(date_str: str, home: str, away: str, *, cache_key: tuple,
               kickoff: Callable[[], Optional[float]]) -> dict[str, Any]:
    """What `resim_live_game(total_calibration=...)` needs for one game: the close (and its book count) and E0. A
    missing input is carried as `anchor_refusal`, so the game is still widened and says why it was not anchored."""
    close = closing_total_for(anchor_dates(date_str), home, away)
    if close is None:
        return {"close": None, "e0": None, "books": None, "anchor_refusal": "no_closing_total"}
    try:
        e0 = kickoff_total(cache_key, kickoff)
    except Exception:  # noqa: BLE001 -- a failed kickoff sim is "no kickoff total", named, never a crash of the tick
        e0 = None
    if e0 is None:
        return {"close": close[0], "e0": None, "books": close[1], "anchor_refusal": "no_kickoff_total"}
    return {"close": close[0], "e0": e0, "books": close[1], "anchor_refusal": None}


def apply(totals: list[int], *, score_so_far: int, period: Any, clock_seconds: Any, close: Optional[float],
          e0: Optional[float], anchor_refusal: Optional[str] = None, books: Optional[int] = None,
          k: Optional[float] = None, env: Optional[Mapping[str, str]] = None) -> tuple[list[int], dict[str, Any]]:
    """The calibrated draws and the block that rides on the lane (`totalCalibration`). `k` given = that K flat;
    None = the schedule (`k_at`) from the env's two knobs."""
    rho = remaining_regulation_share(period, clock_seconds)
    kk = (k_at(rho, k_early=spread_k(env), k_late=spread_k_late(env)) if k is None else float(k))
    offset = None
    refusal = anchor_refusal
    if refusal is None:
        if close is None:
            refusal = "no_closing_total"
        elif e0 is None:
            refusal = "no_kickoff_total"
        else:
            offset = float(close) - float(e0)
    out = calibrate_total_draws(totals, score_so_far=score_so_far, remaining_share=rho, anchor_offset=offset, k=kk)
    block: dict[str, Any] = {"k": round(kk, 4), "remainingShare": round(rho, 4)}
    if offset is not None:
        block.update({"marketTotal": round(float(close), 2), "kickoffTotal": round(float(e0), 3),
                      "offset": round(offset, 3), "appliedOffset": round(offset * rho, 3), "books": books,
                      "source": "book_quotes_close+live_kickoff_resim"})
    else:
        block["anchorRefusal"] = refusal
    return out, block


# --------------------------------------------------------------------------
# THE TICK'S ONE CALL
# --------------------------------------------------------------------------
#: E0 costs one kickoff re-sim (~2 s at 120 sims). After a worker restart on a full Saturday every live game needs
#: one; this many per tick bounds the added time (`#241`: worker periodic work is never free), and a game still
#: waiting is widened and named `kickoff_total_pending` until a later tick reaches it.
MAX_KICKOFF_SIMS_PER_TICK = 8


def _live_profile_key() -> tuple:
    """What the live re-sim's default profile depends on besides the ratings: #852's leader damping
    (`ncaaf/live_blowout_damping.py`), which `resim_live_game` applies when its switch is on. E0 is that same function
    at kickoff, so it is damped exactly when the snapshot's draws are; the cache key carries the setting so a cached E0
    can never come from a different engine."""
    try:
        from syndicate.features.ncaaf.live_blowout_damping import enabled as damping_on
        from syndicate.features.ncaaf.live_blowout_damping import settings as damping_settings
    except Exception:  # noqa: BLE001 -- no damping module: nothing beyond the ratings
        return ()
    return ("blowout_damping", tuple(sorted(damping_settings().items()))) if damping_on() else ()


def _draws(dist: Mapping[Any, Any]) -> list[int]:
    out: list[int] = []
    for key, count in dist.items():
        out.extend([int(key)] * int(count))
    return out


def calibrate_snapshot_totals(snapshot: dict[str, Any], *, ratings: Mapping[str, tuple[float, float]],
                              date_str: str, env: Optional[Mapping[str, str]] = None,
                              max_kickoff_sims: int = MAX_KICKOFF_SIMS_PER_TICK) -> Optional[dict[str, Any]]:
    """Calibrate every live re-sim lane's full-game total in a built NCAAF live-lens snapshot, in place.

    None, touching nothing, when the switch is off -- so the published snapshot and the tick's status are byte-
    identical. On, each `live_resim` lane's `totalRunsDist` and `total` are replaced by the calibrated draws' and
    `projection.totalCalibration` says what was done (`rawTotal` keeps the engine's own mean); the snapshot carries a
    `totalCalibration` tally (anchored / widened only, by reason) so the fleet can count fed vs absent.

    `ratings` are the tick's own (the ones the snapshot's re-sims ran on), so E0 is the same engine on the same
    inputs at kickoff. A market-implied FCS lane (`ratingSource`) re-sims unshrunk, as `build_live_lens_snapshot`
    does for it.
    """
    if not enabled(env):
        return None
    from collections import Counter

    from syndicate.features.ncaaf import live_resim as lr

    k_early, k_late = spread_k(env), spread_k_late(env)
    sims = int(snapshot.get("simsPerGame") or lr.default_sims())
    tally: Counter = Counter()
    ran: list[int] = []  # one entry per kickoff re-sim actually run this tick
    for game in snapshot.get("games") or ():
        if not isinstance(game, dict):
            continue
        home, away = str(game.get("home_name") or ""), str(game.get("away_name") or "")
        for lane in game.get("gameLens") or ():
            if not isinstance(lane, dict) or lane.get("source") != lr.LIVE_RESIM_LENS_SOURCE:
                continue
            proj = lane.get("projection")
            if not isinstance(proj, dict) or not proj.get("totalRunsDist"):
                tally["skipped_no_distribution"] += 1
                continue
            pair = lr._ratings_for(ratings, home, away)
            shrink = 1.0 if lane.get("ratingSource") else None
            refusal = None
            inputs: dict[str, Any] = {"close": None, "e0": None, "books": None}
            if pair is None:
                refusal = "no_pregame_ratings"
            else:
                (ho, hd), (ao, ad) = pair
                cache_key = (str(date_str)[:10], home, away, sims, shrink, ho, hd, ao, ad, _live_profile_key())

                def _kickoff(ho=ho, hd=hd, ao=ao, ad=ad, shrink=shrink, home=home, away=away) -> Optional[float]:
                    ran.append(1)
                    state = lr.NcaafLiveGameState(away_team=away, home_team=home, period=1, clock_seconds=900,
                                                  home_score=0, away_score=0)
                    res = lr.resim_live_game(state, home_offense=ho, home_defense=hd, away_offense=ao,
                                             away_defense=ad, sims=sims, level_shrink=shrink)
                    return None if isinstance(res, lr.NcaafResimRefusal) else float(res["total_mean"])

                if cache_key not in _E0_CACHE and len(ran) >= max_kickoff_sims:
                    close = closing_total_for(anchor_dates(date_str), home, away)
                    inputs = {"close": None if close is None else close[0], "e0": None,
                              "books": None if close is None else close[1]}
                    refusal = "no_closing_total" if close is None else "kickoff_total_pending"
                else:
                    inputs = inputs_for(date_str, home, away, cache_key=cache_key, kickoff=_kickoff)
                    refusal = inputs.get("anchor_refusal")
            try:
                score = int(proj.get("homeScore") or 0) + int(proj.get("awayScore") or 0)
            except (TypeError, ValueError):
                tally["skipped_no_score"] += 1
                continue
            draws = _draws(proj["totalRunsDist"])
            new, block = apply(draws, score_so_far=score, period=proj.get("period"),
                               clock_seconds=proj.get("clockSeconds"), close=inputs.get("close"),
                               e0=inputs.get("e0"), anchor_refusal=refusal, books=inputs.get("books"), env=env)
            block["rawTotal"] = proj.get("total")
            proj["totalRunsDist"] = histogram(new)
            proj["total"] = round(sum(new) / len(new), 3) if new else proj.get("total")
            proj["totalCalibration"] = block
            tally["anchored" if "offset" in block else f"widened_only:{block.get('anchorRefusal')}"] += 1
    summary = {"k": [k_early, k_late], "kickoff_sims": len(ran), **dict(sorted(tally.items()))}
    snapshot["totalCalibration"] = summary
    return summary
