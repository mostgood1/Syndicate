"""NFL quarter / half game lines priced from the sim's own segment histograms.

User 2026-10-08 (lane layer2-board-ui-redesign): "there's a number of
intervals showing no sim data, I see NFL for sure". Measured on the served
board the same afternoon: NFL h1/h2/q1-q4 rows were 14 of 14 `no sim view`,
while the sim had written `smartsim2_segment_distributions_<season>_wk<week>.json`
(`football_segment_distributions.py`) for the very same week -- 15 games,
segments full/q1-q4/h1/h2, `total_points_dist` + `margin_dist` -- and nothing
read it for NFL. NCAAF's identical join (`ncaaf/segment_projections.py`) was
already live; this is the NFL half of it, reusing that module's pricer so the
two sports cannot drift on the arithmetic or the sign convention.

THE JOIN. The artifact is keyed by nflverse game id ``<season>_<week>_<AWAY>_<HOME>``
and carries no team names, so each key's two codes are canonicalised
(`team_aliases.canonical_team`) and matched to the board row's home/away.
Among the season's files the HIGHEST week holding the pair wins: a pairing
repeats in the same orientation only in the playoffs, which come after.

ALSO FULL-GAME SPREADS. `nfl_game_projections` refused every NFL cover
probability because a spreads row's line had no stated side. `#262`
(`book_grid._canonical_line`) has since pinned the grid line to the AWAY frame,
the same convention the NCAAF segment pricer and MLB's run line price in
(home covers when margin > L), so the full-game margin histogram prices those
rows here. Only rows that still have no probability are touched.

PRESEASON NEVER REACHES THIS: the segment sidecar is written beside
`smartsim2_projections_<season>_wk<week>.csv` (regular season) only, never the
preseason series whose full-game numbers `skill_note` refuses.
"""

from __future__ import annotations

import glob
import json
import logging
import re
from pathlib import Path
from typing import Any, Iterable, Mapping

from syndicate.features.shared.probability_refusal import refuse_published_certainty

_LOGGER = logging.getLogger(__name__)

SOURCE = "nfl_smartsim2_segment"
SEGMENTS = ("h1", "h2", "q1", "q2", "q3", "q4")
MARKETS = ("h2h", "spreads", "totals")
_KEY_RE = re.compile(r"^(\d{4})_(\d{1,2})_([A-Z]{2,3})_([A-Z]{2,3})$")
_FILE_RE = re.compile(r"smartsim2_segment_distributions_(\d{4})_wk(\d+)\.json$")


def _team_key(value: Any) -> str | None:
    if not value:
        return None
    try:
        from syndicate.features.shared.team_aliases import canonical_team

        key = canonical_team("nfl", str(value))
    except Exception:  # noqa: BLE001 -- a display/pricing join, never fatal
        key = None
    return key or None


def _season_for(commence_time: Any) -> int | None:
    text = str(commence_time or "")
    try:
        year, month = int(text[:4]), int(text[5:7])
    except ValueError:
        return None
    return year if month >= 3 else year - 1


def load_nfl_segment_blocks(roots: Iterable[Path] | None = None) -> dict[tuple[int, str, str], dict[str, Any]]:
    """``{(season, home key, away key): block}`` from every segment artifact found.

    Empty on any failure: the artifact is optional, and absent must never break
    the full-game join beside it."""
    if roots is None:
        from syndicate.features.shared.nfl_game_projections import _source_roots

        roots = _source_roots()
    best: dict[tuple[int, str, str], tuple[int, dict[str, Any]]] = {}
    seen: set[str] = set()
    for root in roots:
        for path_text in glob.glob(str(Path(root) / "smartsim2_segment_distributions_*_wk*.json")):
            match = _FILE_RE.search(path_text)
            if not match or Path(path_text).name in seen:
                continue
            seen.add(Path(path_text).name)  # first root wins, like the full-game index
            try:
                payload = json.loads(Path(path_text).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                _LOGGER.exception("NFL_SEGMENT_ARTIFACT_READ_FAILURE path=%s", path_text)
                continue
            games = payload.get("games") if isinstance(payload, Mapping) else None
            if not isinstance(games, Mapping):
                continue
            for game_id, block in games.items():
                key = _KEY_RE.match(str(game_id))
                if not key or not isinstance(block, Mapping):
                    continue
                season, week = int(key.group(1)), int(key.group(2))
                home, away = _team_key(key.group(4)), _team_key(key.group(3))
                if not home or not away:
                    continue
                slot = (season, home, away)
                if slot not in best or week > best[slot][0]:
                    best[slot] = (week, dict(block, game_id=str(game_id)))
    return {slot: block for slot, (_week, block) in best.items()}


def attach_nfl_segment_projections(
    grid: Iterable[Mapping[str, Any]],
    blocks: Mapping[tuple[int, str, str], Mapping[str, Any]],
) -> dict[str, Any]:
    """Stamp `projection` onto NFL h1/h2/q1-q4 rows, and price full-game spreads
    that still carry no cover probability. Returns coverage counters."""
    from syndicate.features.ncaaf.segment_projections import _price_against_market, segment_projection
    from syndicate.features.shared.prop_projections import _no_vig_over_probability

    considered = attached = priced = unmatched = full_spreads_priced = 0
    for row in grid:
        if str(row.get("kind") or "") == "prop":
            continue
        market = str(row.get("market") or "").strip().lower()
        segment = str(row.get("segment") or "full").strip().lower() or "full"
        if market not in MARKETS:
            continue
        full_spread = segment == "full" and market == "spreads"
        if segment not in SEGMENTS and not full_spread:
            continue
        existing = row.get("projection") if isinstance(row.get("projection"), Mapping) else None
        if full_spread and existing is not None and existing.get("model_prob_over") is not None:
            continue
        considered += 1
        season = _season_for(row.get("commence_time"))
        home, away = _team_key(row.get("home_team")), _team_key(row.get("away_team"))
        block = blocks.get((season, home, away)) if season and home and away else None
        if block is None:
            unmatched += 1
            continue
        projection = segment_projection(row, market=market, segment=segment, block=block, sims=block.get("sims"))
        if projection is None:
            unmatched += 1
            continue
        projection["source"] = SOURCE
        projection["model_skill"] = {"state": "unmeasured", "note": "NFL segment probabilities have no measured market skill yet"}
        if full_spread and existing is not None:
            # Keep the full-game module's projected margin and its provenance.
            for key in ("projected", "generated_at"):
                if existing.get(key) is not None:
                    projection[key] = existing.get(key)
        _price_against_market(row, projection, _no_vig_over_probability)
        row["projection"] = refuse_published_certainty(projection)  # type: ignore[index]
        attached += 1
        if projection.get("model_prob_over") is not None:
            priced += 1
            full_spreads_priced += int(full_spread)
    return {
        "segment_rows_considered": considered,
        "segment_rows_attached": attached,
        "segment_rows_priced": priced,
        "segment_rows_unmatched_game": unmatched,
        "full_spreads_priced_from_margin_dist": full_spreads_priced,
        "segment_games_indexed": len(blocks),
    }
