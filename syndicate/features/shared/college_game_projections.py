"""College basketball GAME-LINE projections for Layer 1 / Layer 2 (lane wncaab-module, Phase 3, 2026-11-02).

Reads the pregame sim artifact (`college_basketball/pregame_sim.py`) and prices every NCAAB / WNCAAB game
row -- moneyline, spread and total, full game and halves -- off the sim's own score histograms, through the
SAME helpers the NBA and WNBA joins use (`_projection_from_dist`, `_attach_sim_probability_edge`,
`refuse_published_certainty`). Before this, every college row read "no projection source wired".

EVERY LINE IS ITS OWN DECISION (user, 2026-10-02): no market-level withhold. A row is refused only on its
own facts, each counted by reason:
  - no pregame sim for this game (not simmed yet, or the producer refused it -- the refusal is named);
  - a segment the sim has no histogram for (a full-game mean is never stamped on a half);
  - a spread / total row with no line;
  - the game is in play (`_attach_sim_probability_edge` -> `live_edge_unavailable_reason`: the projection
    stays, the edge goes);
  - every draw on one side of the line (`refuse_published_certainty`).

NO BOOK BLEND. NBA serves a logit blend toward the market (`nba_prop_calibration.served_game_probability`),
fitted on NBA seasons. No college fit exists, so the raw sim probability is served and the edge is computed
against the same de-vigged fair. The pregame sim lands on the team model's targets by construction
(EXACT_TARGET), so the edge is mostly the team model's own disagreement with the market.

THE JOIN. Grid rows carry the odds feed's team names; sim entries carry ESPN's. Both go through
`team_aliases.chip_join_key(league, ...)`, the registry the slate's own odds join uses. Orientation: the
slate orients a neutral-site game to the odds feed, so a row's home is the sim's home; a row whose teams
match REVERSED is refused (counted), never silently flipped.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Iterable, Mapping

from syndicate.features.shared.probability_refusal import refuse_published_certainty
from syndicate.features.shared.timezone import central_date_from_iso
from syndicate.features.shared.wnba_game_projections import (
    _GAME_MARKET_FAMILY,
    _as_float,
    _attach_sim_probability_edge,
    _dist_segment,
    _projection_from_dist,
)

SOURCE = "college_pregame_sim"
# Grid rows name the whole game `full_game` (NCAAB, 2026-11-02) or `full` (WNCAAB); the sim names it `full`.
_SEGMENT_ALIASES = {"": "full", "full_game": "full", "game": "full", "fg": "full"}


def _segment(value: Any) -> str:
    text = str(value or "").strip().lower()
    return _SEGMENT_ALIASES.get(text, text)


@dataclass
class CollegeGameEntry:
    league: str
    slate_date: str
    event_id: str
    home_key: str
    away_key: str
    home_name: str
    away_name: str
    dist: Mapping[str, Any] | None = None
    sims: Any = None
    refused: str | None = None


@dataclass
class CollegeGameProjectionIndex:
    league: str
    entries: list[CollegeGameEntry] = field(default_factory=list)
    source_files: list[str] = field(default_factory=list)

    @property
    def games(self) -> int:
        return len(self.entries)

    @property
    def games_with_dist(self) -> int:
        return sum(1 for e in self.entries if e.dist is not None)

    def lookup(self, home: Any, away: Any, commence_time: Any = None) -> tuple[CollegeGameEntry | None, str | None]:
        """(entry, None) on a match; (None, reason) otherwise."""
        from syndicate.features.shared.team_aliases import chip_join_key

        h = chip_join_key(self.league, str(home or "")) or str(home or "").strip().lower()
        a = chip_join_key(self.league, str(away or "")) or str(away or "").strip().lower()
        central = central_date_from_iso(commence_time) if commence_time else None
        day = central.isoformat() if central is not None else None
        same = [e for e in self.entries if (e.home_key, e.away_key) == (h, a) and (day is None or e.slate_date == day)]
        if same:
            return same[-1], None
        if any((e.home_key, e.away_key) == (a, h) and (day is None or e.slate_date == day) for e in self.entries):
            return None, "teams match the sim reversed: orientation differs from the slate"
        return None, f"no {self.league} pregame sim for this game"


def window_dates(selected_date: str) -> list[str]:
    day = date.fromisoformat(selected_date)
    return [(day + timedelta(days=offset)).isoformat() for offset in (-1, 0, 1)]


def load_college_game_projections(selected_date: str, league: str) -> CollegeGameProjectionIndex:
    from syndicate.features.college_basketball.pregame_sim import artifact_path, read_pregame_sims

    index = CollegeGameProjectionIndex(league=league)
    for day in window_dates(selected_date):
        payload = read_pregame_sims(day, league)
        if not payload:
            continue
        index.source_files.append(str(artifact_path(day, league)))
        for event_id, game in (payload.get("games") or {}).items():
            home, away = game.get("home") or {}, game.get("away") or {}
            index.entries.append(CollegeGameEntry(
                league=league, slate_date=day, event_id=str(event_id),
                home_key=str(home.get("key") or ""), away_key=str(away.get("key") or ""),
                home_name=str(home.get("name") or ""), away_name=str(away.get("name") or ""),
                dist=game.get("dist") if isinstance(game.get("dist"), Mapping) else None,
                sims=game.get("sims_run"), refused=game.get("refused"),
            ))
    return index


def _project_row(row: Mapping[str, Any], market: str, segment: str, entry: CollegeGameEntry) -> tuple[dict[str, Any] | None, str | None]:
    if entry.dist is None:
        return None, f"pregame sim refused this game: {entry.refused or 'no distribution'}"
    block = _dist_segment({"dist": entry.dist}, segment)
    if block is None:
        return None, f"no sim histogram for segment {segment}"
    if market in {"spreads", "totals"} and _as_float(row.get("line")) is None:
        return None, "row has no line to price"
    projection = _projection_from_dist(row, market, block, segment=segment, sims=entry.sims)
    if projection is None:
        return None, f"sim histogram for segment {segment} has no {market} distribution"
    projection["source"] = SOURCE
    prob = projection.get("model_prob_over")
    if market == "h2h":
        # PRICED, like NBA's moneyline (every line is its own decision).
        projection.pop("edge_vs_market_pct", None)
        projection.pop("edge_unavailable_reason", None)
        projection.pop("market_fair_prob_over", None)
    if prob is not None:
        _attach_sim_probability_edge(projection, row=row, model_prob=prob)
    return projection, None


def _fill_edge_reason(projection: dict[str, Any]) -> None:
    if projection.get("edge_vs_market_pct") is None and not projection.get("edge_unavailable_reason"):
        reason = projection.get("probability_unavailable_reason")
        projection["edge_unavailable_reason"] = (
            f"no probability to price: {reason}" if reason else "this projection carries no probability, so no edge was priced"
        )


def attach_college_game_projections(grid: Iterable[Mapping[str, Any]], index: CollegeGameProjectionIndex) -> dict[str, Any]:
    """Stamp `projection` onto college game rows. Returns the coverage payload board enrichment reports."""
    considered = attached = with_probability = with_edge = unmatched = period_rows = unsupported = 0
    refused: Counter[str] = Counter()
    for row in grid:
        if str(row.get("kind") or "") == "prop":
            continue
        raw_market = str(row.get("market") or "").strip().lower()
        market = _GAME_MARKET_FAMILY.get(raw_market)
        considered += 1
        if market is None:
            unsupported += 1
            refused[f"market not modelled: {raw_market or '?'}"] += 1
            continue
        entry, reason = index.lookup(row.get("home_team"), row.get("away_team"), row.get("commence_time"))
        if entry is None:
            unmatched += 1
            refused[reason or "no match"] += 1
            continue
        segment = _segment(row.get("segment"))
        projection, reason = _project_row(row, market, segment, entry)
        if projection is None:
            refused[reason or "unknown"] += 1
            continue
        line, projected = _as_float(row.get("line")), _as_float(projection.get("projected"))
        if line is not None and projected is not None and market != "h2h":
            projection["edge_vs_line"] = round(projected - line, 3)
        _fill_edge_reason(projection)
        row["projection"] = refuse_published_certainty(projection)  # type: ignore[index]
        attached += 1
        period_rows += segment != "full"
        with_probability += row["projection"].get("model_prob_over") is not None  # type: ignore[index]
        with_edge += row["projection"].get("edge_vs_market_pct") is not None  # type: ignore[index]
    return {
        "supported": True,
        "source": SOURCE,
        "rows_considered": considered,
        "rows_with_projection": attached,
        "rows_with_probability": with_probability,
        "rows_with_edge": with_edge,
        "unmatched_game_rows": unmatched,
        "unsupported_market_rows": unsupported,
        "unprojected_by_reason": dict(sorted(refused.items())),
        "period_rows_priced": period_rows,
        "games_in_index": index.games,
        "games_with_sim_distribution": index.games_with_dist,
        "source_artifacts": index.source_files,
    }
