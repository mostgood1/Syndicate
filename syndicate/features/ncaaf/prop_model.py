"""NCAAF player-prop projections. ANYTIME TD ONLY, and that is a result.

--------------------------------------------------------------------------
WHY ONE MARKET AND NOT SIX
--------------------------------------------------------------------------

Backtested on the 2025 game logs, out-of-sample, weeks 5-16, rates fitted on
weeks `< w` only (`scripts/backtest_ncaaf_player_props.py`):

    ANYTIME TD    Brier, n=18,989
      model           0.18168
      player mean     0.21919
      league base     0.19400        -> BEATS BOTH

    YARDAGE/COUNTS  MAE          model   player-mean
      Receiving Yards  n=15,484  19.018     18.683
      Rushing Yards    n=11,136  21.499     20.220
      Passing Yards     n=3,237  67.351     56.771
      Receptions       n=15,647   1.272      1.245
      Passing TDs       n=2,701   0.859      0.848

On every continuous market the player's own prior-weeks mean predicts better
than the model. **Those markets are deliberately not projected here.** Shipping
them would add machinery, not information, and a projection that is worse than
"his average" is worse than a blank column because it looks like knowledge.

--------------------------------------------------------------------------
THE SHIPPED CODE IS THE GRADED CODE
--------------------------------------------------------------------------

`anytime_td_probability` below is imported BY the backtest. It is not a
reimplementation of it. `learnings.md` records the cost of the alternative --
a fixture that took a cheaper path than production and failed 80x too fast,
which read as a good result. If these two ever diverge, the number on the board
stops being the number that was graded, silently.

--------------------------------------------------------------------------
THIS IS A PROJECTION, NOT A PICK
--------------------------------------------------------------------------

`football/pick_gate.py` suppresses NCAAF PICKS default-DENY and says in terms
that it "does NOT stop projections being generated, published, or displayed",
because a gate that blinds its own exit criterion never opens. So a probability
may be shown. An edge, a tier, a recommendation or a stake may NOT be, until
the gate's LIFT_CONDITION is met on real graded bets.

And the market comparison this enables is not yet a measurement: there are
ZERO historical NCAAF prop odds -- the first capture in this platform's
history was 2026-08-26 -- so nothing here has ever been scored against a
price. Saturday's captures are what make that possible for the first time.
"""
from __future__ import annotations

import csv
import math
import re
import unicodedata
from collections import defaultdict
from functools import lru_cache
from pathlib import Path
from typing import Any

#: Shrinkage weight toward the league rate, in units of games. Fitted nowhere
#: and tuned nowhere: it was chosen before the backtest ran and left alone, so
#: the reported Brier is not a number selected on the grade set it is quoted
#: against.
SHRINK_GAMES = 4.0

#: Below this many prior appearances a player is REFUSED rather than projected.
#: Measured on the real capture: 6 of 68 quoted openers have no 2025 history at
#: all, so refusing is a live branch, not a theoretical one.
MIN_PRIOR_GAMES = 3

_SPACE_RE = re.compile(r"\s+")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9 ]+")


def _norm(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.strip().lower().replace("&", " and ")
    text = _NON_ALNUM_RE.sub(" ", text)
    return _SPACE_RE.sub(" ", text).strip()


def _game_stats_path() -> Path:
    from syndicate.features.ncaaf.sources import player_game_stats_snapshot_path

    return player_game_stats_snapshot_path()


def _checkout_game_stats_path() -> Path:
    """The repo-checkout copy, for the same reason `props.py` has one.

    `cards.py` reads these snapshots from the checkout while
    `sources.*_path()` reads the mounted disk, and the boot sync onto that disk
    is SEED-ONLY -- so the two can hold different vintages on Render.
    """
    return (
        Path(__file__).resolve().parents[3]
        / "data" / "ncaaf_source" / "source_artifacts" / "data" / "processed"
        / "player_game_stats" / "ncaaf_player_game_stats_snapshot.csv"
    )


def _read_rows() -> list[dict[str, str]]:
    for path in (_game_stats_path(), _checkout_game_stats_path()):
        try:
            if path.exists():
                with path.open("r", encoding="utf-8", newline="") as handle:
                    rows = [dict(r) for r in csv.DictReader(handle)]
                if rows:
                    return rows
        except Exception:
            continue
    return []


def _f(value: Any) -> float:
    try:
        text = str(value or "").strip()
        return float(text) if text else 0.0
    except (TypeError, ValueError):
        return 0.0


@lru_cache(maxsize=4)
def _rates(season: int) -> dict[str, Any]:
    """Per-player anytime-TD rate for `season`, plus the league rate.

    Keyed by NORMALISED PLAYER NAME, not `player_id`: the board's prop rows
    carry an OddsAPI display name and no id, so an id-keyed index would join
    nothing. The accent folding in `_norm` is the same one `props.py` needs --
    the registry stores `San Jose State` with an acute and the board does not.
    """
    games: dict[str, int] = defaultdict(int)
    tds: dict[str, float] = defaultdict(float)
    for row in _read_rows():
        if str(row.get("season") or "") != str(int(season)):
            continue
        name = _norm(row.get("player_name"))
        if not name:
            continue
        games[name] += 1
        tds[name] += _f(row.get("anytime_td"))
    total_games = sum(games.values())
    league = (sum(tds.values()) / total_games) if total_games else 0.0
    return {"games": dict(games), "tds": dict(tds), "league_rate": league, "players": len(games)}


@lru_cache(maxsize=8)
def resolve_history_season(requested: int) -> int | None:
    """The season whose game logs actually back a projection for `requested`.

    PRIOR-SEASON FALLBACK, NAMED RATHER THAN IMPLICIT. On opening weekend the
    requested season has no games played, so a rate fitted on it is fitted on
    nothing -- and the first version of this wiring passed the board's 2026
    straight through, got an empty table, and refused all 35 Anytime TD rows
    while the model answered correctly when called directly. A silent empty
    join and a deliberate refusal looked identical from the board.

    This mirrors the ratings path, which already resolves
    `cfbd_ppa_season_2025_fallback_for_2026` for the same reason and says so
    in the artifact's own `rating_source`.

    Returns None when NO season has logs -- never a guess.
    """
    seasons = available_seasons()
    if not seasons:
        return None
    if requested in seasons:
        table = _rates(requested)
        if table["players"]:
            return requested
    earlier = [s for s in seasons if s < requested]
    return max(earlier) if earlier else max(seasons)


@lru_cache(maxsize=1)
def available_seasons() -> tuple[int, ...]:
    """Seasons present in the game-log snapshot, newest last."""
    seasons: set[int] = set()
    for row in _read_rows():
        text = str(row.get("season") or "").strip()
        if text.isdigit():
            seasons.add(int(text))
    return tuple(sorted(seasons))


def anytime_td_probability(player_name: str, season: int) -> dict[str, Any] | None:
    """P(the player scores at least one TD), or None if not projectable.

    None rather than a default, deliberately. A neutral default is
    indistinguishable from a real estimate at every level except the data --
    `model_engine_standard.md` exists because 26 unfed fields hid behind
    `.get(key, 1.0)` in this platform's most mature engine.

    Poisson from a shrunk per-game rate: `1 - exp(-lambda)`. An unshrunk
    3-game rate of 1.00 would claim a 100% scorer, which is why the shrink is
    not optional.
    """
    history_season = resolve_history_season(int(season))
    if history_season is None:
        return None
    table = _rates(history_season)
    key = _norm(player_name)
    g = table["games"].get(key, 0)
    if g < MIN_PRIOR_GAMES:
        return None
    scored = table["tds"].get(key, 0.0)
    league = table["league_rate"]
    shrunk = (scored + SHRINK_GAMES * league) / (g + SHRINK_GAMES)
    probability = 1.0 - math.exp(-max(0.0, shrunk))
    return {
        "probability": round(probability, 4),
        "prior_games": g,
        "prior_tds": round(scored, 1),
        "raw_rate": round(scored / g, 4),
        "league_rate": round(league, 4),
        # The season the rate was FITTED on, not the one requested --
        # `ncaaf_anytime_td_2025_for_2026` on opening weekend. A
        # provenance string that names the wrong season is how a
        # prior-season fallback becomes invisible.
        "source": (f"ncaaf_anytime_td_{history_season}" if history_season == int(season)
                   else f"ncaaf_anytime_td_{history_season}_for_{int(season)}"),
        "history_season": history_season,
    }


def american_to_probability(price: Any) -> float | None:
    """Implied probability from an American price, VIG INCLUDED.

    Named `implied`, never `fair`. A single-sided anytime-TD price carries the
    book's margin and there is no opposing side quoted to de-vig against, so
    calling this fair would overstate the market's true probability and make
    every model edge look larger than it is.
    """
    # FLOAT, NOT INT `[2026-09-05]`. `int("-110.5")` RAISES, so a half-point
    # price refused instead of converting -- the differential harness probes
    # -110.5 and expects 0.5249406175. Truncating to -110 would have been worse
    # than refusing: it returns a plausible number for a price nobody quoted.
    try:
        value = float(str(price).replace("+", "").strip())
    except (TypeError, ValueError):
        return None
    if value == 0:
        return None
    # NOT ROUNDED `[2026-09-05]`. The arithmetic is identical to the other 37
    # implementations in `scripts/probability_differential.py`'s registry; this
    # one alone wrapped it in `round(..., 4)`, so at +10000 it returned 0.0099
    # where every other implementation returns 0.0099009901. That breaks the
    # property `test_all_implementations_agree_on_valid_prices` protects -- and
    # rounding an implied probability to four places serves nothing here, since
    # it is consumed as a float and compared against model probabilities that
    # are not rounded.
    if value > 0:
        return 100.0 / (value + 100.0)
    return -value / (-value + 100.0)


def reset_caches() -> None:
    _rates.cache_clear()
    available_seasons.cache_clear()
    resolve_history_season.cache_clear()
