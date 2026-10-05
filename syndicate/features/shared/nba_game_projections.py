"""NBA GAME-LINE projections for the Layer 2 board `[2026-10-03, lane nba-layer2-projections]`.

BASELINE, served `/api/board/layer2-shortlist` 2026-10-04T03:29Z (10-03 10:29 PM
CT): `per_sport_ingest.nba.enrichment.projections` read `supported: false`,
"no projection source wired for nba", over 5 NBA game rows. The model existed
the whole time -- it reached users only on the NBA cards page.

THE SOURCE IS THE PER-GAME SMART-SIM ARTIFACT, NOT `cards_sim_detail`. Measured
on the fleet's 2026-10-04 files: NBA's `cards_sim_detail_<date>.json` carries no
`sim.score_dist` (WNBA's does), and `game_cards_<date>.csv` carries no
`p_home_win`/`p_home_cover`/`p_total_over` columns. But every
`smart_sim_<date>_<HOME>_<AWAY>.json` has `score.dist` -- 500 recorded draws,
`margin_frame: home_minus_away`, segments full/regulation/h1/h2/q1-q4 -- which
prices ANY line, not just the sim's own. So this reads those files directly,
and no producer change was needed.

EVERY LINE IS ITS OWN DECISION (user, 2026-10-02). There is no market-level
withhold here, and unlike `wnba_game_projections` the full-game moneyline edge
is PRICED: the WNBA branch withholds it on a 2026-08-16 "unvalidated sim"
judgement, and that judgement is exactly the market-level gate the prime
directive withdrew. A line is refused only on its own facts:
  - no sim for this row's game (no smart_sim / no game_cards entry);
  - a period row whose segment has no histogram;
  - a spreads/totals row with no line (no row context);
  - the game is in play (`live_edge_unavailable_reason`, via
    `_attach_sim_probability_edge` -- the projection stays, only the edge goes);
  - every draw on one side of the line (`refuse_published_certainty`).

WHAT THE NUMBERS ARE. The game-line sim is market-anchored by design
(`market_anchor`: total_w 0.7, margin_w 0.95), so most edges here will be small.
That is the sim's own statement, not this join's: when the producer changes, the
histograms change and this module carries it with no edit.

REUSED, NOT RE-DERIVED: the histogram pricing (`_projection_from_dist`), the
edge computation (`_attach_sim_probability_edge`) and the de-vig all come from
the WNBA/shared modules that production already exercises. Only the NBA file
layout and the moneyline-edge policy differ.
"""

from __future__ import annotations

import csv
import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Iterable, Mapping

from syndicate.features.shared.nba_prop_calibration import served_game_probability
from syndicate.features.shared.probability_refusal import refuse_published_certainty
from syndicate.features.shared.prop_projections import _no_vig_over_probability
from syndicate.features.shared.team_aliases import teams_match
from syndicate.features.shared.timezone import central_date_from_iso
from syndicate.features.shared.wnba_game_projections import (
    _GAME_MARKET_FAMILY,
    _as_float,
    _attach_sim_probability_edge,
    _dist_segment,
    _norm_team,
    _projection_from_dist,
)

SOURCE = "nba_smart_sim_draws"


# --------------------------------------------------------------------------
# Paths. Resolved PER FILE across every candidate root (`#309`): "does this
# root contain anything" is not "does it contain the file you asked for".
# SYNDICATE_NBA_SOURCE_ROOT first, then SYNDICATE_DATA_ROOT/nba_source -- the
# fleet's ~/syndicate-prod/data/nba_source/data/processed.
# --------------------------------------------------------------------------


def nba_processed_candidates(filename: str) -> list[Path]:
    from syndicate.features.shared.source_roots import preferred_artifact_roots

    out: list[Path] = []
    try:
        from syndicate.features.nba.sources import processed_path

        out.append(Path(processed_path(filename)))
    except Exception:
        pass
    for root in preferred_artifact_roots(__file__, env_var="SYNDICATE_NBA_SOURCE_ROOT", local_dir_name="nba_source"):
        out.append(root / "data" / "processed" / filename)
    deduped: list[Path] = []
    for path in out:
        if path not in deduped:
            deduped.append(path)
    return deduped


_ESPN_SEASON_PHASE = {1: "preseason", 2: "regular", 3: "postseason"}


def season_phase_for_date(slate_date: str | None) -> str | None:
    """The NBA season phase of a slate date from the ESPN scoreboard the sim caches
    (`_espn_cache/nba/scoreboard_<ymd>.json`, `events[].season.type` 1/2/3). None when the cache is absent or the
    date's events disagree -- the caller must treat None as UNKNOWN, never as regular season."""
    if not slate_date:
        return None
    path = nba_processed_file(f"_espn_cache/nba/scoreboard_{str(slate_date)[:10].replace('-', '')}.json")
    if path is None:
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        types = {int((ev.get("season") or {}).get("type")) for ev in doc.get("events") or []
                 if (ev.get("season") or {}).get("type") is not None}
    except Exception:  # noqa: BLE001
        return None
    return _ESPN_SEASON_PHASE.get(types.pop()) if len(types) == 1 else None


def nba_processed_file(filename: str) -> Path | None:
    for path in nba_processed_candidates(filename):
        try:
            if path.is_file():
                return path
        except OSError:
            continue
    return None


def window_dates(selected_date: str) -> list[str]:
    """The anchor date and its neighbours, anchor LAST so it wins any tie.

    The board's date is a slate date, while a 9:30 PM CT tip is 02:30Z the next
    day (learnings 2026-10-02: bucket by central date, never the UTC prefix).
    Reading D-1..D+1 and then matching each row to the entry whose slate date
    is the row's CENTRAL commence date makes the join independent of which
    calendar the caller passed.
    """
    try:
        anchor = date.fromisoformat(str(selected_date).strip()[:10])
    except ValueError:
        return [str(selected_date)]
    return [(anchor + timedelta(days=d)).isoformat() for d in (-1, 1, 0)]


# --------------------------------------------------------------------------
# Index
# --------------------------------------------------------------------------


@dataclass
class NbaGameEntry:
    slate_date: str
    home_team: str
    away_team: str
    home_tri: str
    away_tri: str
    pred_margin: float | None = None
    pred_total: float | None = None
    p_home_win: float | None = None
    dist: Mapping[str, Any] | None = None
    sim_draws: Any = None
    smart_sim_path: str = ""

    def matches(self, home: Any, away: Any) -> bool:
        h, a = _norm_team(home), _norm_team(away)
        if not (h and a):
            return False
        if (h, a) in {
            (_norm_team(self.home_team), _norm_team(self.away_team)),
            (_norm_team(self.home_tri), _norm_team(self.away_tri)),
        }:
            return True
        return bool(
            self.home_team
            and self.away_team
            and teams_match("nba", h, self.home_team)
            and teams_match("nba", a, self.away_team)
        )


@dataclass
class NbaGameProjectionIndex:
    entries: list[NbaGameEntry] = field(default_factory=list)
    source_files: list[str] = field(default_factory=list)

    @property
    def games(self) -> int:
        return len(self.entries)

    @property
    def games_with_dist(self) -> int:
        return sum(1 for e in self.entries if e.dist is not None)

    def lookup(self, home: Any, away: Any, commence_time: Any = None) -> NbaGameEntry | None:
        hits = [e for e in self.entries if e.matches(home, away)]
        if not hits:
            return None
        central = central_date_from_iso(commence_time) if commence_time else None
        if central is not None:
            same_day = [e for e in hits if e.slate_date == central.isoformat()]
            if len(same_day) == 1:
                return same_day[0]
            if same_day:
                return same_day[-1]
            # The sim for this PAIR exists only on another slate: a different
            # game between the same clubs. A wrong-day sim is worse than none.
            return None
        return hits[-1] if len({e.slate_date for e in hits}) == 1 else None

    def by_tri(self, slate_date: str, home_tri: str, away_tri: str) -> NbaGameEntry | None:
        for entry in self.entries:
            if (
                entry.slate_date == slate_date
                and _norm_team(entry.home_tri) == _norm_team(home_tri)
                and _norm_team(entry.away_tri) == _norm_team(away_tri)
            ):
                return entry
        return None


def _read_game_cards(path: Path) -> list[dict[str, str]]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    if not text.strip():
        return []
    return [row for row in csv.DictReader(text.splitlines()) if isinstance(row, dict)]


def _load_smart_sim_score(slate_date: str, home_tri: str, away_tri: str) -> tuple[Mapping[str, Any] | None, str]:
    path = nba_processed_file(f"smart_sim_{slate_date}_{home_tri}_{away_tri}.json")
    if path is None:
        return None, ""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, str(path)
    score = payload.get("score") if isinstance(payload, Mapping) else None
    return (score if isinstance(score, Mapping) else None), str(path)


def load_nba_game_projections(selected_date: str) -> NbaGameProjectionIndex:
    """Index `game_cards_<d>.csv` + each game's smart_sim score, over D-1..D+1."""
    index = NbaGameProjectionIndex()
    for slate_date in window_dates(selected_date):
        cards_path = nba_processed_file(f"game_cards_{slate_date}.csv")
        if cards_path is None:
            continue
        index.source_files.append(str(cards_path))
        for row in _read_game_cards(cards_path):
            home_tri = str(row.get("home_tri") or "").strip().upper()
            away_tri = str(row.get("away_tri") or "").strip().upper()
            entry = NbaGameEntry(
                slate_date=slate_date,
                home_team=str(row.get("home_team") or "").strip(),
                away_team=str(row.get("visitor_team") or row.get("away_team") or "").strip(),
                home_tri=home_tri,
                away_tri=away_tri,
                pred_margin=_as_float(row.get("pred_margin")),
                pred_total=_as_float(row.get("pred_total")),
            )
            if home_tri and away_tri:
                score, sim_path = _load_smart_sim_score(slate_date, home_tri, away_tri)
                entry.smart_sim_path = sim_path
                if score is not None:
                    entry.p_home_win = _as_float(score.get("p_home_win"))
                    dist = score.get("dist")
                    if isinstance(dist, Mapping) and isinstance(dist.get("segments"), Mapping):
                        # The pricing helpers assume margin = home - away. Refuse a
                        # histogram that says otherwise rather than invert every
                        # spread and moneyline while still looking reasonable.
                        frame = str(dist.get("margin_frame") or "home_minus_away").strip().lower()
                        if frame == "home_minus_away":
                            entry.dist = dist
                            entry.sim_draws = dist.get("n")
            # A later file for the same game (same slate + pair) replaces it.
            existing = index.by_tri(slate_date, home_tri, away_tri) if home_tri and away_tri else None
            if existing is not None:
                index.entries.remove(existing)
            index.entries.append(entry)
    return index


# --------------------------------------------------------------------------
# Join
# --------------------------------------------------------------------------


def _fill_edge_reason(projection: dict[str, Any]) -> None:
    if projection.get("edge_vs_market_pct") is None and not projection.get("edge_unavailable_reason"):
        probability_reason = projection.get("probability_unavailable_reason")
        projection["edge_unavailable_reason"] = (
            "no probability to price: %s" % probability_reason
            if probability_reason
            else "this projection carries no probability, so no edge was priced"
        )


def _project_row(row: Mapping[str, Any], market: str, segment: str, entry: NbaGameEntry) -> tuple[dict[str, Any] | None, str | None]:
    """(projection, refusal_reason). Exactly one is set."""
    block = _dist_segment({"dist": entry.dist} if entry.dist is not None else None, segment)
    if block is not None:
        if market in {"spreads", "totals"} and _as_float(row.get("line")) is None:
            return None, "row has no line to price"
        projection = _projection_from_dist(row, market, block, segment=segment, sims=entry.sim_draws)
        if projection is None:
            return None, f"sim histogram for segment {segment} has no {market} distribution"
        projection["source"] = SOURCE
        prob = projection.get("model_prob_over")
        if market == "h2h":
            # PRICED, unlike WNBA's withheld moneyline -- see the module docstring.
            projection.pop("edge_vs_market_pct", None)
            projection.pop("edge_unavailable_reason", None)
            projection.pop("market_fair_prob_over", None)
        if prob is not None:
            # NBA game-line book blend (lane nba-prop-calibration, user decision 2026-10-05): the raw sim histogram
            # carries no OOS information beyond the line (w 0.00 margin / 0.05 total, 2025-26) and runs far off the
            # market in preseason, so the served probability is the per-line logit blend toward the SAME de-vigged
            # fair the edge is computed against. Raw sim p + weight ride along; falls back to the sim WITH a reason.
            commence = row.get("commence_time")
            phase = season_phase_for_date(central_date_from_iso(commence) if commence else None)
            prob, blend_meta = served_game_probability(prob, _no_vig_over_probability(row), market, segment, phase=phase)
            projection.update(blend_meta)
            _attach_sim_probability_edge(projection, row=row, model_prob=prob)
        return projection, None
    if segment != "full":
        # A full-game mean on a period market is a real number against the
        # wrong bet (`#262`); without that period's own histogram, refuse.
        return None, f"no sim histogram for segment {segment}"
    # Full game, no histogram: the means from game_cards, labelled, never a
    # probability invented from them.
    reason = (
        "no smart-sim draws for this game"
        if not entry.smart_sim_path
        else "smart-sim artifact for this game carries no score histogram"
    )
    if market == "h2h":
        if entry.pred_margin is None:
            return None, reason
        projection = {
            "projected": round(entry.pred_margin, 3),
            "side": str(row.get("home_team") or "").strip(),
            "basis": "model_margin_mean",
            "source": "nba_game_cards",
            "model_prob_over": None,
            "edge_vs_market_pct": None,
            "probability_unavailable_reason": reason,
            "market_fair_prob_over": _no_vig_over_probability(row),
        }
        return projection, None
    mean = entry.pred_margin if market == "spreads" else entry.pred_total
    if mean is None:
        return None, reason
    return {
        "projected": round(mean, 3),
        "side": str(row.get("home_team") or "").strip() if market == "spreads" else "over",
        "basis": "model_margin_mean" if market == "spreads" else "model_total_mean",
        "source": "nba_game_cards",
        "model_prob_over": None,
        "edge_vs_market_pct": None,
        "probability_unavailable_reason": reason,
    }, None


def attach_nba_game_projections(
    grid: Iterable[Mapping[str, Any]], index: NbaGameProjectionIndex
) -> dict[str, Any]:
    """Stamp `projection` onto NBA game rows (h2h/spreads/totals, alt lines, periods)."""
    considered = 0
    attached = 0
    with_probability = 0
    with_edge = 0
    unmatched_games = 0
    period_rows_priced = 0
    unsupported_market_rows = 0
    refused: Counter[str] = Counter()

    for row in grid:
        if str(row.get("kind") or "") == "prop":
            continue
        raw_market = str(row.get("market") or "").strip().lower()
        market = _GAME_MARKET_FAMILY.get(raw_market)
        considered += 1
        if market is None:
            unsupported_market_rows += 1
            refused[f"market not modelled: {raw_market or '?'}"] += 1
            continue
        entry = index.lookup(row.get("home_team"), row.get("away_team"), row.get("commence_time"))
        if entry is None:
            unmatched_games += 1
            refused["no NBA sim for this game"] += 1
            continue
        segment = str(row.get("segment") or "full").strip().lower() or "full"
        projection, reason = _project_row(row, market, segment, entry)
        if projection is None:
            refused[reason or "unknown"] += 1
            continue
        line = _as_float(row.get("line"))
        projected = _as_float(projection.get("projected"))
        if line is not None and projected is not None and market != "h2h":
            projection["edge_vs_line"] = round(projected - line, 3)
        _fill_edge_reason(projection)
        row["projection"] = refuse_published_certainty(projection)  # type: ignore[index]
        attached += 1
        if segment != "full":
            period_rows_priced += 1
        if row["projection"].get("model_prob_over") is not None:  # type: ignore[index]
            with_probability += 1
        if row["projection"].get("edge_vs_market_pct") is not None:  # type: ignore[index]
            with_edge += 1

    return {
        "supported": True,
        "rows_considered": considered,
        "rows_with_projection": attached,
        "rows_with_probability": with_probability,
        "rows_with_edge": with_edge,
        "unmatched_game_rows": unmatched_games,
        "unsupported_market_rows": unsupported_market_rows,
        "unprojected_by_reason": dict(sorted(refused.items())),
        "period_rows_priced": period_rows_priced,
        "games_in_index": index.games,
        "games_with_sim_distribution": index.games_with_dist,
        "source_artifacts": index.source_files,
    }
