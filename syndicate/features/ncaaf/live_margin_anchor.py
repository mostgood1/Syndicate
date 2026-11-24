"""NCAAF LIVE MARGIN ANCHOR: the in-play margin and win probability anchored to the market's pregame line (todo #859).

`[2026-11-24, lane ncaaf-margin-aware-endgame, user "Yes, build it"; findings
`.syndicate/findings_2026-11-20_ncaaf_margin_aware_endgame.md` "## IN-PLAY TEAM-STRENGTH RE-FIT"]`

ABSENT IS OFF. `SYNDICATE_NCAAF_LIVE_MARGIN_ANCHOR=on` (1 / true / yes) switches it on. Off, nothing here runs and the
published snapshot and the tick's status are byte-identical. It is a BETTING CHANGE: it moves the live moneyline and
spread probabilities, so it loads only in a betting-change window, with the user's yes.

--------------------------------------------------------------------------
WHAT WAS WRONG (the in-play moneyline diagnosis and the pre-registered re-fit, 2026-11-23)
--------------------------------------------------------------------------
The live re-sim's in-play win probability is OVER-CONFIDENT. On production's own in-season blend ratings (2026 weeks
4-10, 337 games), its favourites at 0.60-0.90 won 0.695 against a predicted 0.751: -0.0555 (se 0.0207). The cause is
the team-strength gap, not the end game: the projected margin leans about +1.1 points (se 0.5) toward the favourite,
most in the first half. In paper, the sim's in-play NCAAF moneyline edges lost -24.4% (se 9.7).

THE FIX is NCAAB's shipped live margin anchor (`ncaab/live_resim.py` "margin anchor", user 2026-11-03) on NCAAF:

    every draw's home margin moves by (M - E0) x rho     M   = the closing consensus home margin (-home spread)
                                                         E0  = the live engine's own mean home margin at kickoff,
                                                               same ratings, same engine, same sims
                                                         rho = the share of regulation still to play

At kickoff the anchored margin IS the market's; every move after that is what the engine makes of the game state. The
points already scored are real, so the shift shrinks as the game runs, and in overtime it is zero.

MEASURED (pre-registered, 2026-11-23 7:49 PM CST; results 10:40 PM CST): against the 12-08 engine (#852 damping +
#859 end game) on the 2026 hold-out (396 games, 2,376 states):
  (a) the full-state Brier of the win probability -0.00683 (se 0.00236);
  (b) the favourites' headline -0.0283 (se 0.0197), no longer over-confident at 2 SE;
  (c) the Brier of P(home covers the pregame line) -0.01313 (se 0.00328).
The 2025-fitted rating-difference gain (G* 0.70) failed (a). On 2025 the anchor points the same way, by 1.4 SE.

--------------------------------------------------------------------------
WHAT IS SERVED, EXACTLY
--------------------------------------------------------------------------
- `projection.marginDist`: the histogram moved by the offset, by NCAAB's cumulative rounding
  (`ncaab/live_resim._shift_margin_hist`): counts stay integers, their total is unchanged, the mean moves by the offset
  to within 1/sims. The join prices spreads off it.
- `modelHomeWinProb`: read off THAT histogram (margin > 0, a 0 counting half), as NCAAB's `anchor_result` does.
- `projection.homeMargin`: the engine's mean plus the offset.
- Kept beside them: `rawModelHomeWinProb`, `projection.rawHomeMargin`, and `projection.marginAnchor` (the market
  margin, E0, the offset, the share left, the offset applied, the book count).

WHY NOT THE REPLAY'S OWN RULE. The replay scored each draw as "draw + offset > 0". Football margins pile up on 3 and 7,
and that rule calls a draw of +3 moved by -2.5 a WIN (+0.5) while a -0.5 spread prices the same draw as NO COVER: the
moneyline and the spread at the pivot disagreed by 8.5 pp on one test state (the whole 3-pile), past the ~9 pp
publish bar's tripwire. It also jumps every time the offset crosses an integer, and the offset moves with the clock.
The histogram rule splits a pile between its two neighbours in proportion, so it is continuous in the offset and the
moneyline and every spread come from ONE distribution. The hold-out was re-scored under the SERVED rule before this
shipped (findings "### THE ANCHOR AS BUILT").

--------------------------------------------------------------------------
WHAT IT LEAVES ALONE, AND WHAT IT DOES NOT FIX
--------------------------------------------------------------------------
- TOTALS: an anchor on the margin moves no total (#835's `live_total_dispersion` owns those).
- THE SEGMENT BLOCKS (h1 h2 q1-q4): display only, left raw, as #835 leaves them.
- A MARKET-IMPLIED FCS LANE (`ratingSource`): its ratings already come from the pregame line, and the anchor was not
  tested on it. Refused by name, served raw.
- A game with no closing spread in the quote log, or no E0: served RAW (today's lane) and named
  (`projection.marginAnchorRefusal`). Unlike NCAAB, a raw NCAAF lane is what production prices today, so refusing it
  would only cut coverage.
- THE SPREADS k. `live_gameline_join._SPREADS_PROB_SCALE_BY_SPORT["ncaaf"]` (1.80, #780) tempers the live spread
  probability. It was fitted on UN-anchored margins and has no anchored NCAAF entry, so an anchored lane gets the same
  1.80. Moneylines are not tempered (#780 found no h2h gain), so the measured win-probability gain reaches the price
  as tested. Measured at the PREGAME line only (post hoc, the replay has no live lines): at k 1.80 the anchored lane
  still beats today's raw lane on the cover Brier (2026 -0.00726, se 0.00211; 2025 -0.00350, se 0.00214), and the
  best k there is about 1.2 anchored against 1.5 raw. So the k on anchored margins is a re-fit owed with or after the
  load (`model_engine_standard.md` 4.4), on the fleet's live spread ledger as NBA's was; it can ride as
  `SYNDICATE_LIVE_SPREADS_PROB_SCALE_NCAAF` with no code change.
- Only tested on top of the 12-08 set (#835 + #852 + #859's end game). Without that set it is untested.

--------------------------------------------------------------------------
WHERE IT RUNS, AND WHAT IT COSTS
--------------------------------------------------------------------------
`anchor_snapshot_margins`, a post-pass on the built snapshot inside the worker's NCAAF tick
(`run_refresh_worker._run_ncaaf_live_resim_tick`), on the tick's own ratings, before the snapshot is written.
`live_resim.py` is unchanged. E0 is ONE kickoff re-sim per game per process (~2 s at 120 sims), cached for the game
(its ratings are fixed). At most `MAX_KICKOFF_SIMS_PER_TICK` run per tick (#241: worker periodic work is never free);
a game still waiting is served raw and named `kickoff_margin_pending` until a later tick reaches it. With #835's
calibration also on, each game costs two kickoff re-sims, once each.
"""

from __future__ import annotations

import math
import os
import time
from typing import Any, Callable, Iterable, Mapping, Optional

SWITCH_ENV = "SYNDICATE_NCAAF_LIVE_MARGIN_ANCHOR"
_ON = frozenset({"1", "true", "on", "yes"})
#: The quote log grows all day; re-read it at most this often (#835's and NCAAB's anchors use the same order).
_QUOTES_TTL_S = 600.0
#: See the module docstring: E0 costs one kickoff re-sim; this bounds what a full Saturday adds to one tick.
MAX_KICKOFF_SIMS_PER_TICK = 8
#: Every setting the live engine reads lives under this prefix; the E0 cache key carries them all, so a cached E0 can
#: never come from a different engine than the lane's draws.
_ENGINE_ENV_PREFIX = "SYNDICATE_NCAAF_LIVE_"
SOURCE = "book_quotes_close+live_kickoff_resim"

_QUOTE_SOURCES: dict[str, tuple[float, Any]] = {}
_E0_CACHE: dict[tuple, float] = {}


def enabled(env: Optional[Mapping[str, str]] = None) -> bool:
    raw = str((env if env is not None else os.environ).get(SWITCH_ENV, "") or "").strip().lower()
    return raw in _ON


# --------------------------------------------------------------------------
# THE ANCHOR'S TWO INPUTS
# --------------------------------------------------------------------------

def _spread_quotes(date: str) -> Mapping[Any, Any]:
    """(home_key, away_key) -> every full-game HOME spread quote of the date's NCAAF quote-log shard."""
    from syndicate.features.ncaab.live_resim import home_spread_quotes

    return home_spread_quotes("ncaaf", str(date))


def _quote_map(date: str, clock: Callable[[], float] = time.monotonic) -> Mapping[Any, Any]:
    hit = _QUOTE_SOURCES.get(str(date))
    if hit is not None and clock() - hit[0] < _QUOTES_TTL_S:
        return hit[1]
    try:
        quotes = _spread_quotes(str(date))
    except Exception:  # noqa: BLE001 -- an unreadable log is "no closing spread", named by the caller
        quotes = {}
    _QUOTE_SOURCES[str(date)] = (clock(), quotes)
    return quotes


def closing_home_margin_for(dates: Iterable[str], home: str, away: str) -> Optional[tuple[float, int]]:
    """(closing consensus home margin, books) in the LANE's home orientation, from the first of `dates` whose shard has
    the game: each book's last home spread before the listed commence, median across books
    (`ncaab/live_resim.closing_home_margin`). Keys are `_join_key('ncaaf', name)` (#835's join). A neutral-site game the
    odds feed orients the other way is found under the swapped key and its margin is negated."""
    from syndicate.features.ncaab.live_resim import _join_key, closing_home_margin

    h, a = _join_key("ncaaf", home), _join_key("ncaaf", away)
    for date in dates:
        quotes = _quote_map(str(date))
        for key, flip in (((h, a), False), ((a, h), True)):
            close = closing_home_margin(quotes.get(key) or (), tip=None)
            if close is not None:
                margin, books = close
                return (-float(margin) if flip else float(margin)), int(books)
    return None


def engine_key() -> tuple:
    """Every live-engine setting in the PROCESS environment, sorted (this module's own switch excluded: it moves no
    draw). Always `os.environ`, never a passed mapping: `resim_live_game` reads its damping and end-game switches from
    the process, so that is what E0's engine is."""
    return tuple(sorted((k, str(v)) for k, v in os.environ.items()
                        if k.startswith(_ENGINE_ENV_PREFIX) and k != SWITCH_ENV))


def kickoff_margin(cache_key: tuple, compute: Callable[[], Optional[float]]) -> Optional[float]:
    """E0, computed once per game per process and kept (the ratings behind it are fixed for the game)."""
    if cache_key in _E0_CACHE:
        return _E0_CACHE[cache_key]
    value = compute()
    if value is not None and math.isfinite(float(value)):
        _E0_CACHE[cache_key] = float(value)
        return float(value)
    return None


def _dist_mean(dist: Mapping[Any, Any]) -> Optional[float]:
    n = sum(int(c) for c in dist.values())
    return None if n <= 0 else sum(int(k) * int(c) for k, c in dist.items()) / n


# --------------------------------------------------------------------------
# THE TRANSFORM
# --------------------------------------------------------------------------

def shifted_margin_dist(dist: Mapping[Any, Any], offset: float) -> dict[str, int]:
    """The histogram moved by `offset` (NCAAB's cumulative rounding: integer counts, same total, mean + offset), then
    any draws that landed on 0 split evenly between +1 and -1 (an odd one stays at 0).

    WHY THE SPLIT. No football game ends level, but a shifted key-number pile can land on 0 (+7 moved by -7). The
    moneyline counts a 0 as half a win, as overtime would; a spread at -0.5 counts it as no cover. Left there, the two
    disagreed by half the pile -- 5.25 pp on one test state at 400 sims. Split symmetrically, the mean, the count and
    the moneyline are all unchanged, and a spread at the pivot agrees with the moneyline to within half a draw."""
    from syndicate.features.ncaab.live_resim import _shift_margin_hist

    moved = _shift_margin_hist(dist, float(offset))
    zero = int(moved.pop(0, 0))
    if zero:
        half = zero // 2
        moved[1] += half
        moved[-1] += half
        if zero % 2:
            moved[0] += 1
    return {str(m): int(c) for m, c in sorted(moved.items()) if c}


def win_prob_of(dist: Mapping[Any, Any]) -> Optional[float]:
    """P(home wins) read off an integer margin histogram, a margin of 0 counting half (the re-sim's own tie rule)."""
    n = sum(int(c) for c in dist.values())
    if n <= 0:
        return None
    return (sum(int(c) for k, c in dist.items() if int(k) > 0) + 0.5 * sum(int(c) for k, c in dist.items()
                                                                            if int(k) == 0)) / n


def anchored_win_prob(dist: Mapping[Any, Any], offset: float) -> Optional[float]:
    """P(home wins) off the histogram moved by `offset` -- the SAME histogram the join prices spreads from."""
    return win_prob_of(shifted_margin_dist(dist, offset))


def anchor_lane(lane: dict[str, Any], *, market_margin: float, kickoff: float, books: Optional[int]) -> dict[str, Any]:
    """Anchor one live re-sim lane in place and return its `marginAnchor` block."""
    from syndicate.features.ncaaf.live_total_dispersion import remaining_regulation_share

    proj = lane["projection"]
    dist = proj["marginDist"]
    rho = remaining_regulation_share(proj.get("period"), proj.get("clockSeconds"))
    offset = float(market_margin) - float(kickoff)
    applied = offset * rho
    block = {"marketHomeMargin": round(float(market_margin), 2), "kickoffHomeMargin": round(float(kickoff), 3),
             "offset": round(offset, 3), "remainingShare": round(rho, 4), "appliedOffset": round(applied, 3),
             "books": books, "source": SOURCE}
    lane["rawModelHomeWinProb"] = lane.get("modelHomeWinProb")
    proj["marginAnchor"] = block
    if applied == 0.0:
        # Overtime (or an offset of exactly 0): nothing to move, so the engine's own numbers are served as they are.
        proj["rawHomeMargin"] = proj.get("homeMargin")
        return block
    moved = shifted_margin_dist(dist, applied)
    win = win_prob_of(moved)
    if win is not None:
        lane["modelHomeWinProb"] = round(win, 6)
    proj["rawHomeMargin"] = proj.get("homeMargin")
    if proj.get("homeMargin") is not None:
        proj["homeMargin"] = round(float(proj["homeMargin"]) + applied, 3)
    proj["marginDist"] = moved
    return block


# --------------------------------------------------------------------------
# THE TICK'S ONE CALL
# --------------------------------------------------------------------------

def anchor_dates(date_str: str) -> list[str]:
    """The tick's UTC date, then the day before (#835's rule: a game running past midnight UTC closed on the earlier
    shard)."""
    from syndicate.features.ncaaf.live_total_dispersion import anchor_dates as _dates

    return _dates(date_str)


def anchor_snapshot_margins(snapshot: dict[str, Any], *, ratings: Mapping[str, tuple[float, float]], date_str: str,
                            env: Optional[Mapping[str, str]] = None,
                            max_kickoff_sims: int = MAX_KICKOFF_SIMS_PER_TICK) -> Optional[dict[str, Any]]:
    """Anchor every live re-sim lane's margin and win probability in a built NCAAF live-lens snapshot, in place.

    None, touching nothing, when the switch is off. On, each anchored lane carries `projection.marginAnchor`; a lane
    left raw carries `projection.marginAnchorRefusal`; the snapshot carries a `marginAnchor` tally (anchored, and each
    refusal by reason) so the fleet can count fed vs absent. `ratings` are the tick's own, so E0 is the same engine on
    the same inputs at kickoff."""
    if not enabled(env):
        return None
    from collections import Counter

    from syndicate.features.ncaaf import live_resim as lr

    sims = int(snapshot.get("simsPerGame") or lr.default_sims())
    key_env = engine_key()
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
            if not isinstance(proj, dict) or not proj.get("marginDist"):
                tally["skipped_no_distribution"] += 1
                continue
            refusal: Optional[str] = None
            close = None
            e0 = None
            pair = lr._ratings_for(ratings, home, away)
            if lane.get("ratingSource"):
                refusal = "market_implied_ratings"
            elif pair is None:
                refusal = "no_pregame_ratings"
            else:
                close = closing_home_margin_for(anchor_dates(date_str), home, away)
                if close is None:
                    refusal = "no_closing_spread"
            if refusal is None:
                (ho, hd), (ao, ad) = pair
                cache_key = (str(date_str)[:10], home, away, sims, ho, hd, ao, ad, key_env)

                def _kickoff(ho=ho, hd=hd, ao=ao, ad=ad, home=home, away=away) -> Optional[float]:
                    ran.append(1)
                    state = lr.NcaafLiveGameState(away_team=away, home_team=home, period=1, clock_seconds=900,
                                                  home_score=0, away_score=0)
                    res = lr.resim_live_game(state, home_offense=ho, home_defense=hd, away_offense=ao,
                                             away_defense=ad, sims=sims)
                    return None if isinstance(res, lr.NcaafResimRefusal) else _dist_mean(res.get("margin_dist") or {})

                if cache_key not in _E0_CACHE and len(ran) >= max_kickoff_sims:
                    refusal = "kickoff_margin_pending"
                else:
                    try:
                        e0 = kickoff_margin(cache_key, _kickoff)
                    except Exception:  # noqa: BLE001 -- a failed kickoff sim is named, never a crash of the tick
                        e0 = None
                    if e0 is None:
                        refusal = "no_kickoff_margin"
            if refusal is not None:
                proj["marginAnchorRefusal"] = refusal
                tally[f"refused:{refusal}"] += 1
                continue
            anchor_lane(lane, market_margin=close[0], kickoff=e0, books=close[1])
            tally["anchored"] += 1
    summary = {"kickoff_sims": len(ran), **dict(sorted(tally.items()))}
    snapshot["marginAnchor"] = summary
    return summary
