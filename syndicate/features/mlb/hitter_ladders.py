from __future__ import annotations

from syndicate.features.mlb.ladders_common import build_ladders_page_context
from syndicate.features.mlb.ladders_common import hitter_rows_from_summary


def build_hitter_ladders_page_context(selected_date: str) -> dict[str, object]:
    return build_ladders_page_context(
        selected_date,
        active_label="Hitter ladders",
        route_path="/mlb/hitter-ladders",
        source_title="MLB hitter ladders artifact",
        intro_title="MLB hitter ladders",
        intro_body="This module reuses the shared ladder board and ranked-card layers, now applied to the hitter side of the prebuilt daily ladders artifact.",
        aria_label="Hitter ladder board",
        row_builder=hitter_rows_from_summary,
    )