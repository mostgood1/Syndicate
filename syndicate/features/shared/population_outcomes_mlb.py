"""MLB outcomes for the priced-population rows `scripts/bucket_search.py` cannot grade from a final score.

OFFLINE ONLY. Lane `model-scorecard-cron`: a daily cron grades the Layer 2 PRICED population
(`opportunity_population_ledger` records) with `bucket_search.grade_population`, which settles
full-game h2h / spreads / totals from final scores and MLB player props through
`prop_outcomes.MlbPropGrader`, and SKIPS the rest. An instance of `MlbPopulationSettler` is the
`extra_settler(shaped, view)` that `grade_population` consults BEFORE its skip branches:
`None` means "not mine, fall through"; otherwise `(result, reason)`, result 'win' | 'loss' |
'push', or None with the reason it could not settle. Nothing on the serving path imports this.

WHAT IT SETTLES -- and ONLY this, so nothing is graded twice:
- inning segments `firstN` (first1 / first3 / first5 seen on 2026-09-16) of h2h, h2h_3_way,
  spreads, spreads_alt, totals, totals_alt, from the runs per inning in statsapi's linescore;
- FULL-game spreads_alt / totals_alt, from the official final score (extra innings count, as
  they do for spreads / totals);
- FULL-game h2h_3_way, from the runs through REGULATION (`scheduledInnings`). A 3-way line on
  a sport that cannot end tied only exists as a regulation market: 2026-09-16 NYY @ MIN was 2-2
  after nine and 5-4 MIN after thirteen;
- `batter_strikeouts`, discriminated by SUBJECT: one book publishes starting-pitcher
  strikeouts under that key (`prop_projections`, measured 2026-08-30; every one of the 50
  rows on 2026-09-16 names a starter, lines 2.5-8.5). A player who pitched and had no plate
  appearance settles on his pitching strikeouts; a batter on his batting strikeouts; a
  player who did both is refused (`ambiguous_strikeout_subject`).
Full-game h2h / spreads / totals, every prop market `prop_outcomes.MARKET_STATS` maps, and
every other sport return None.

THE RULES are `scripts/layer2_live_scorecard.grade`'s, applied to runs through the segment:
- h2h (2-way): a tie is a push;
- h2h_3_way: a tie wins the `draw` side and loses both team sides;
- spreads / spreads_alt: the side's runs minus the opponent's, plus the side's own `line`
  (the recorder keys `away|2.5` and `home|-2.5`); zero is a push;
- totals / totals_alt: both teams' runs against the line; equal is a push.

A SEGMENT SETTLES ONLY WHEN IT IS OVER. In a game still going, inning N is over once the
linescore's `currentInning` is past N, or is N with `inningState` End; otherwise
`segment_not_complete`. In a Final game every inning through N needs both halves, except that
the home team does not bat in the last inning of a game it already leads -- allowed only when
N reaches `scheduledInnings`. A Final game that never reached N (shortened) is
`segment_not_played`: books void it, and the 4.5-inning rule is not guessed at.

FINDING THE GAME is `MlbPropGrader`'s: the schedule of the commence time's Eastern date, teams
through the alias registry, cached the same way (a schedule once all Final; a Final game's
linescore / box score). One addition: when the same teams play twice that day, the quoted start
must be nearer one game by `DOUBLEHEADER_MARGIN_SECONDS`, or the row is `ambiguous_game`
rather than a guess.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable, Mapping

from syndicate.features.mlb import cards
from syndicate.features.mlb.prop_outcomes import (
    _EASTERN,
    MARKET_STATS,
    MAX_START_GAP_SECONDS,
    STATSAPI,
    MlbPropGrader,
    _as_float,
    _parse_ts,
    settle_prop,
    team_key,
)

__all__ = [
    "DOUBLEHEADER_MARGIN_SECONDS",
    "FULL_GAME_MARKETS",
    "GRADER_VERSION",
    "MlbPopulationSettler",
    "SEGMENT_MARKETS",
    "STRIKEOUT_PROP_MARKET",
    "runs_through",
    "segment_innings",
    "settle_runs",
]

GRADER_VERSION = "mlb/1"
SPORT = "mlb"

SEGMENT_MARKETS = frozenset({"h2h", "h2h_3_way", "spreads", "spreads_alt", "totals", "totals_alt"})
#: Full-game markets `bucket_search` does not grade. Base h2h / spreads / totals are ITS.
FULL_GAME_MARKETS = frozenset({"spreads_alt", "totals_alt", "h2h_3_way"})
STRIKEOUT_PROP_MARKET = "batter_strikeouts"
FULL_SEGMENTS = frozenset({"", "full", "full_game"})
NOT_PLAYED_PREFIXES = ("postponed", "cancelled", "canceled")
#: With two games between the same teams on a date, the quoted start must be at least this much
#: nearer one of them. A 2026-09-04 split doubleheader (DET @ CLE) started 5h05m apart.
DOUBLEHEADER_MARGIN_SECONDS = 3600
DEFAULT_SCHEDULED_INNINGS = 9

_SEGMENT_RE = re.compile(r"^first(\d+)$")


def _norm(value: Any) -> str:
    return str(value or "").strip().lower()


def _as_int(value: Any) -> int | None:
    number = _as_float(value)
    if number is None or not number.is_integer():
        return None
    return int(number)


def segment_innings(segment: Any) -> int | None:
    """`firstN` -> N (N >= 1); anything else -> None."""
    match = _SEGMENT_RE.match(_norm(segment))
    if not match:
        return None
    innings = int(match.group(1))
    return innings if innings >= 1 else None


def _base_market(market: Any) -> str:
    text = _norm(market)
    return text[: -len("_alt")] if text.endswith("_alt") else text


def settle_runs(market: Any, side: Any, line: Any, away_runs: int, home_runs: int) -> str | None:
    """'win' | 'loss' | 'push' for a game-line side at these runs, or None when it cannot settle."""
    kind = _norm(market)
    pick = _norm(side)
    line_value = _as_float(line)
    if kind == "h2h_3_way":
        if pick == "draw":
            return "win" if away_runs == home_runs else "loss"
        if pick not in {"away", "home"}:
            return None
        if away_runs == home_runs:
            return "loss"
        return "win" if (pick == "away") == (away_runs > home_runs) else "loss"
    base = _base_market(kind)
    if base == "h2h":
        if pick not in {"away", "home"}:
            return None
        if away_runs == home_runs:
            return "push"
        return "win" if (pick == "away") == (away_runs > home_runs) else "loss"
    if base == "spreads":
        if pick not in {"away", "home"} or line_value is None:
            return None
        margin = (away_runs - home_runs if pick == "away" else home_runs - away_runs) + line_value
        return "push" if margin == 0 else ("win" if margin > 0 else "loss")
    if base == "totals":
        if pick not in {"over", "under"} or line_value is None:
            return None
        diff = (away_runs + home_runs) - line_value
        if diff == 0:
            return "push"
        return "win" if (diff > 0) == (pick == "over") else "loss"
    return None


def _bet_is_settleable(market: Any, side: Any, line: Any) -> bool:
    """The side / line check `settle_runs` makes, without runs -- so a bad row fetches nothing."""
    kind, pick = _norm(market), _norm(side)
    if kind == "h2h_3_way":
        return pick in {"away", "home", "draw"}
    base = _base_market(kind)
    if base == "h2h":
        return pick in {"away", "home"}
    if base == "spreads":
        return pick in {"away", "home"} and _as_float(line) is not None
    if base == "totals":
        return pick in {"over", "under"} and _as_float(line) is not None
    return False


def runs_through(linescore: Mapping[str, Any], innings: int, *, final: bool) -> tuple[tuple[int, int] | None, str | None]:
    """((away, home) runs through `innings`, None), or (None, reason) when that is not yet known."""
    not_known = "segment_not_played" if final else "segment_not_complete"
    rows = [row for row in (linescore.get("innings") or []) if isinstance(row, Mapping)]
    scheduled = _as_int(linescore.get("scheduledInnings")) or DEFAULT_SCHEDULED_INNINGS
    if final:
        if len(rows) < innings:
            return None, not_known
    else:
        current = _as_int(linescore.get("currentInning"))
        state = _norm(linescore.get("inningState"))
        if current is None or not (current > innings or (current == innings and state == "end")):
            return None, not_known
        if len(rows) < innings:
            return None, not_known
    away_total = home_total = 0
    for number, row in enumerate(rows[:innings], start=1):
        if _as_int(row.get("num")) not in (None, number):
            return None, "linescore_malformed"
        away = _as_int((row.get("away") or {}).get("runs"))
        home = _as_int((row.get("home") or {}).get("runs"))
        if away is None:
            return None, not_known
        if home is None:
            # The home team does not bat in the last inning of a game it already leads.
            if final and number == len(rows) and innings >= scheduled:
                home = 0
            else:
                return None, not_known
        away_total += away
        home_total += home
    return (away_total, home_total), None


class MlbPopulationSettler:
    """`extra_settler` for `bucket_search.grade_population`: MLB segments, alt / 3-way lines, batter_strikeouts.

    `fetch_json(url)` returns parsed JSON or None (the default reads statsapi.mlb.com, the way
    `MlbPropGrader` does). With `cache_dir`, what can no longer change is kept on disk.
    """

    grader_version = GRADER_VERSION

    def __init__(self, *, fetch_json: Callable[[str], Any] | None = None,
                 cache_dir: Path | str | None = None) -> None:
        # The prop grader's schedule / box-score fetch and cache, shared: one schedule per date, and a
        # cache_dir shared with it serves both. Its default fetch reads statsapi over urllib, sequentially.
        self._grader = MlbPropGrader(cache_dir=cache_dir, fetch=fetch_json)

    @property
    def fetches(self) -> int:
        return self._grader.fetches

    # -- routing ----------------------------------------------------------------------------

    @staticmethod
    def _identity(shaped: Mapping[str, Any], view: Mapping[str, Any] | None) -> tuple[str, str, str, bool]:
        view = view or {}
        sport = _norm(shaped.get("sport") or view.get("sport"))
        market = _norm(shaped.get("market") or view.get("market"))
        segment = _norm(shaped.get("segment") or view.get("segment"))
        return sport, market, segment, bool(_norm(shaped.get("player_name")))

    def handles(self, shaped: Mapping[str, Any], view: Mapping[str, Any] | None = None) -> bool:
        sport, market, segment, is_prop = self._identity(shaped, view)
        if sport != SPORT:
            return False
        if is_prop:
            # `not in MARKET_STATS`: the day the prop grader maps this key, it is the prop grader's.
            return market == STRIKEOUT_PROP_MARKET and market not in MARKET_STATS and segment in FULL_SEGMENTS
        if segment in FULL_SEGMENTS:
            return market in FULL_GAME_MARKETS
        return segment_innings(segment) is not None and market in SEGMENT_MARKETS

    def __call__(self, shaped: Mapping[str, Any], view: Mapping[str, Any] | None = None) -> tuple[str | None, str | None] | None:
        if not self.handles(shaped, view):
            return None
        return self.settle(shaped, view)

    def settle(self, shaped: Mapping[str, Any], view: Mapping[str, Any] | None = None) -> tuple[str | None, str | None]:
        if not self.handles(shaped, view):
            return None, "not_handled"
        _sport, market, segment, is_prop = self._identity(shaped, view)
        if is_prop:
            return self._settle_strikeouts(shaped)
        if not _bet_is_settleable(market, shaped.get("side"), shaped.get("line")):
            return None, "unsettleable_side_or_line"
        if segment in FULL_SEGMENTS and market != "h2h_3_way":
            return self._settle_full_game(shaped, market)
        return self._settle_innings(shaped, market, segment_innings(segment))

    # -- data -------------------------------------------------------------------------------

    def _find_game(self, shaped: Mapping[str, Any]) -> tuple[Mapping[str, Any] | None, str | None]:
        home, away = shaped.get("home_team"), shaped.get("away_team")
        if not (home and away):
            return None, "no_team_names"
        start = _parse_ts(shaped.get("commence_time"))
        if start is None:
            return None, "no_commence_time"
        games = self._grader.games_on(start.astimezone(_EASTERN).date().isoformat())
        if games is None:
            return None, "schedule_unavailable"
        home_key, away_key = team_key(home), team_key(away)
        candidates: list[tuple[float, Mapping[str, Any]]] = []
        for game in games:
            if team_key(game.get("home")) != home_key or team_key(game.get("away")) != away_key:
                continue
            when = _parse_ts(game.get("game_date"))
            if when is None:
                continue
            gap = abs((when - start).total_seconds())
            if gap <= MAX_START_GAP_SECONDS:
                candidates.append((gap, game))
        if not candidates:
            return None, "game_not_found"
        candidates.sort(key=lambda item: item[0])
        if len(candidates) > 1 and candidates[1][0] - candidates[0][0] < DOUBLEHEADER_MARGIN_SECONDS:
            return None, "ambiguous_game"
        game = candidates[0][1]
        if _norm(game.get("detailed_state")).startswith(NOT_PLAYED_PREFIXES):
            return None, "game_not_played"
        return game, None

    def linescore(self, game_pk: Any, *, final: bool) -> Mapping[str, Any] | None:
        """statsapi's linescore; kept on disk only once the game is Final."""
        payload = self._grader._get(f"linescore_{game_pk}.json", f"{STATSAPI}/game/{game_pk}/linescore",
                                    keep=lambda _payload: final)
        return payload if isinstance(payload, Mapping) else None

    # -- settlement -------------------------------------------------------------------------

    def _settle_innings(self, shaped: Mapping[str, Any], market: str, innings: int | None) -> tuple[str | None, str | None]:
        game, why = self._find_game(shaped)
        if game is None:
            return None, why
        final = game.get("state") == "Final"
        if game.get("state") == "Preview":
            return None, "segment_not_complete" if innings is not None else "game_not_final"
        linescore = self.linescore(game.get("game_pk"), final=final)
        if linescore is None:
            return None, "linescore_unavailable"
        if innings is None:  # full-game h2h_3_way: regulation
            innings = _as_int(linescore.get("scheduledInnings")) or DEFAULT_SCHEDULED_INNINGS
        runs, why = runs_through(linescore, innings, final=final)
        if runs is None:
            return None, why
        result = settle_runs(market, shaped.get("side"), shaped.get("line"), *runs)
        return (result, None) if result else (None, "unsettleable_side_or_line")

    def _settle_full_game(self, shaped: Mapping[str, Any], market: str) -> tuple[str | None, str | None]:
        game, why = self._find_game(shaped)
        if game is None:
            return None, why
        if game.get("state") != "Final":
            return None, "game_not_final"
        away, home = _as_int(game.get("away_score")), _as_int(game.get("home_score"))
        if away is None or home is None:
            return None, "score_absent"
        result = settle_runs(market, shaped.get("side"), shaped.get("line"), away, home)
        return (result, None) if result else (None, "unsettleable_side_or_line")

    def _settle_strikeouts(self, shaped: Mapping[str, Any]) -> tuple[str | None, str | None]:
        if _norm(shaped.get("side")) not in {"over", "under"} or _as_float(shaped.get("line")) is None:
            return None, "unsettleable_side_or_line"
        game, why = self._find_game(shaped)
        if game is None:
            return None, why
        if game.get("state") != "Final":
            return None, "game_not_final"
        feed = self._grader.box_score(game.get("game_pk"))
        if feed is None:
            return None, "boxscore_unavailable"
        batting = cards._actual_batting_context_by_name(dict(feed))
        pitching = cards._actual_pitching_context_by_name(dict(feed))
        batter = pitcher = None
        for variant in cards._market_name_variants(shaped.get("player_name")):
            batter, pitcher = batting.get(variant), pitching.get(variant)
            if batter or pitcher:
                break
        if not (batter or pitcher):
            return None, "player_not_in_boxscore"
        batted = bool(batter) and (_as_int((batter.get("stats") or {}).get("plateAppearances")) or 0) > 0
        if pitcher and batted:
            return None, "ambiguous_strikeout_subject"
        if pitcher:
            actual = cards._actual_pitcher_stat_value(pitcher.get("stats"), "strikeouts")
        else:
            actual = _as_float((batter.get("stats") or {}).get("strikeOuts"))
        if actual is None:
            return None, "stat_absent"
        result = settle_prop(shaped.get("side"), shaped.get("line"), actual)
        return (result, None) if result else (None, "unsettleable_side_or_line")
