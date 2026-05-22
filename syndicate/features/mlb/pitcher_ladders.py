from __future__ import annotations

from syndicate.features.mlb.ladders_common import build_ladders_page_context
from syndicate.features.mlb.ladders_common import pitcher_rows_from_summary


def build_pitcher_ladders_page_context(selected_date: str) -> dict[str, object]:
    return build_ladders_page_context(
        selected_date,
        active_label="Pitcher ladders",
        route_path="/mlb/pitcher-ladders",
        source_title="MLB pitcher ladders artifact",
        intro_title="MLB pitcher ladders",
        intro_body="This is the third real MLB module inside Syndicate, backed by the existing ladders artifact and reusing shared ranked-card patterns.",
        aria_label="Pitcher ladder board",
        row_builder=pitcher_rows_from_summary,
    )