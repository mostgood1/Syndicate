"""hockeysim ingestion — Syndicate-owned collection of roster/lineup/goalie inputs.

Replaces the vendor CLI's data-collection commands (``roster-update``/``lineup-update``/
``starting-goalies``) so the ``nhl_betting`` subprocess can be fully retired (Phase 5). Everything
here reads the public NHL StatsWeb API (``api-web.nhle.com``) — the same source
``syndicate.local_nhl_odds`` and the truth layer already use — and derives line combinations +
starting goalies from recent-game time-on-ice, porting the vendor ``rosters.infer_lines`` algorithm.
"""
from __future__ import annotations

from .collect import collect_slate_inputs
from .lineups import build_team_usage, infer_lines, project_lineup
from .nhl_web import NhlWebIngestClient

__all__ = [
    "NhlWebIngestClient",
    "build_team_usage",
    "infer_lines",
    "project_lineup",
    "collect_slate_inputs",
]
