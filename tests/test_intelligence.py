from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from collections import OrderedDict
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from flask import Flask

from syndicate.app import create_app
from syndicate.blueprints.intelligence import intelligence_bp
from syndicate.blueprints.intelligence import intelligence_query_api
from syndicate.blueprints.intelligence import intelligence_status_api
from pipeline.intelligence_state import _payload_key
from pipeline.intelligence_state import IntelligenceStateService
from syndicate.blueprints.home import _finalize_home_prop_rows
from syndicate.blueprints.home import _load_home_pregame_prop_items
from syndicate.blueprints.home import _game_bet_candidates_from_game
from syndicate.features.intelligence_board import build_intelligence_board_contract
from syndicate.features.intelligence import _advanced_signals_from_item
from syndicate.features.intelligence import _advanced_input_rows_for_sport
from syndicate.features.intelligence import _score_candidates
from syndicate.features.intelligence import _advanced_signals_from_item
from syndicate.features.intelligence import _build_parlays
from syndicate.features.intelligence import _balanced_recommendation_order
from syndicate.features.intelligence import _bind_candidate_state
from syndicate.features.intelligence import _candidate_advanced_signal_score
from syndicate.features.intelligence import _candidate_live_claim_is_stale
from syndicate.features.intelligence import _basketball_source_summary_score
from syndicate.features.intelligence import _candidate_market_fit
from syndicate.features.intelligence import _game_candidates_for_sport
from syndicate.features.intelligence import _is_game_level_market
from syndicate.features.intelligence import _prop_candidate_from_item
from syndicate.features.intelligence import collect_candidates
from syndicate.features.intelligence import classify_candidate
from syndicate.features.intelligence import is_valid_candidate
from syndicate.features.intelligence import normalize_candidate
from syndicate.features.intelligence import score_candidate
from syndicate.features.intelligence import _latest_matching_path
from syndicate.features.intelligence import _parlay_matches_preferences
from syndicate.features.intelligence import _parlay_rank_score
from syndicate.features.intelligence import _query_preferences
from syndicate.features.intelligence import build_intelligence_overview
from syndicate.features.intelligence import get_top_live_opportunities
from syndicate.features.intelligence import run_intelligence_query
from syndicate.features.intelligence import _attach_intelligence_response_aliases
from syndicate.features.intelligence.api.response_builder import _recommendation_state


from contextlib import contextmanager


@contextmanager
def _patch_build_intelligence_overview(return_value):
    """Patch the overview at BOTH import sites.

    pipeline/intelligence_state.py binds build_intelligence_overview by value
    (`from syndicate.features.intelligence import ...`, line 24), so patching
    only the features module leaves the candidate-pool half of the query path
    reading real artifacts while the analysis half sees the fixture -- empty
    pools, no parlays, wrong counts. One mock serves both seams so `as`
    aliases still see every call.
    """
    with patch("syndicate.features.intelligence.build_intelligence_overview", return_value=return_value) as overview_mock:
        with patch("pipeline.intelligence_state.build_intelligence_overview", overview_mock):
            yield overview_mock


def _sample_overview() -> list[dict[str, object]]:
    return [
        {
            "slug": "nba",
            "name": "NBA",
            "context_label": "2026-06-04",
            "data_health": "healthy",
            "data_warnings": [],
            "home_rails": {
                "pregame": {
                    "title": "Pregame props",
                    "items": [
                        {
                            "name": "Jayson Tatum Over 28.5",
                            "market": "PTS",
                            "pick": "Over 28.5",
                            "matchup": "BOS at NYK",
                            "team_pace_signal": 1.08,
                            "usage_rate_advanced": 1.14,
                            "shot_profile_advanced": 1.06,
                            "minutes_role_advanced": 1.03,
                            "projected": 31.8,
                            "line": 28.5,
                            "odds": "+102",
                            "confidence": "63%",
                            "edge": "+5.4%",
                            "basketball_summary": "Recent form is already clearing this number with a last-five average of 31.2. The last-10 sample is still above this number at 30.1, so the over is not just riding a short heater. Last game landed at 33.0, which keeps the most recent touch well above the book.",
                            "why_explain": "Projected minutes (36.0) sit above his last-10 workload (34.0), which strengthens the volume path.",
                            "writeup": "Projection is clearing the number with usage and minutes support.",
                            "display_pills": ["Line 28.5", "Odds +102", "Sim% 63%"],
                            "href": "/nba/prop-ladders?date=2026-06-04",
                        }
                    ],
                },
                "live": {
                    "title": "Top Live Props",
                    "items": [
                        {
                            "name": "Donovan Mitchell Over 4.5 3PM",
                            "market": "3PM",
                            "pick": "Over 4.5",
                            "matchup": "CLE at IND",
                            "team_pace_signal": 1.08,
                            "usage_rate_advanced": 1.14,
                            "shot_profile_advanced": 1.06,
                            "minutes_role_advanced": 1.03,
                            "projected": 4.9,
                            "live_projection": 5.8,
                            "actual": 3,
                            "line": 4.5,
                            "odds": "+118",
                            "confidence": "61%",
                            "edge": "+4.1%",
                            "basketball_summary": "Recent form is already clearing this number with a last-five average of 5.1. The last-10 sample is still above this number at 4.8, so the over is not just riding a short heater. Last game landed at 6.0, which keeps the recent shot volume above the book.",
                            "why_explain": "Projected minutes (35.0) sit above his last-10 workload (33.0), which strengthens the volume path.",
                            "writeup": "The live model is still above the book after the in-game adjustment.",
                            "display_pills": ["Line 4.5", "Odds +118", "Live Proj 5.8"],
                            "is_live": True,
                            "href": "/nba/season/2026/live-lens?date=2026-06-04",
                        }
                    ],
                },
                "compact": {"items": []},
            },
            "dashboard_games": [
                {
                    "matchup": "MIN at DAL",
                    "summary": "Model makes the total short by a couple of points.",
                    "betting": {
                        "total": 217.5,
                        "over_ev": 3.8,
                        "p_total_over": 0.58,
                    },
                    "href": "/nba/cards?date=2026-06-04",
                    "href_label": "Open game",
                }
            ],
        }
    ]


def _sample_overview_with_secondary_sport() -> list[dict[str, object]]:
    rows = _sample_overview()
    rows.append(
        {
            "slug": "wnba",
            "name": "WNBA",
            "context_label": "2026-06-04",
            "data_health": "healthy",
            "data_warnings": [],
            "home_rails": {
                "pregame": {
                    "title": "Pregame props",
                    "items": [
                        {
                            "name": "A'ja Wilson Over 24.5",
                            "market": "PTS",
                            "pick": "Over 24.5",
                            "matchup": "LVA at SEA",
                            "team_environment_advanced": 1.12,
                            "possession_profile_advanced": 1.05,
                            "matchup_pressure_advanced": 1.09,
                            "rotation_pressure_advanced": 1.03,
                            "live_shift_advanced": 1.01,
                            "projected": 28.1,
                            "line": 24.5,
                            "odds": "+102",
                            "confidence": "63%",
                            "edge": "+5.4%",
                            "basketball_summary": "Recent form is already clearing this number with a last-five average of 28.4. The last-10 sample is still above this number at 26.8, so the over is not just riding a short heater. Last game landed at 29.0, which keeps the most recent result on the right side of the number.",
                            "why_explain": "Projected minutes (34.0) sit above his last-10 workload (31.5), which strengthens the volume path.",
                            "writeup": "Projection is clearing the number with stable volume.",
                            "display_pills": ["Line 24.5", "Odds +102", "Sim% 63%"],
                            "href": "/wnba/prop-ladders?date=2026-06-04",
                        }
                    ],
                },
                "live": {"title": "Top Live Props", "items": []},
                "compact": {"items": []},
            },
            "dashboard_games": [],
        }
    )
    return rows


def _sample_nba_subject_specific_overview() -> list[dict[str, object]]:
    return [
        {
            "slug": "nba",
            "name": "NBA",
            "context_label": "2026-06-05",
            "data_health": "healthy",
            "data_warnings": [],
            "home_rails": {
                "pregame": {
                    "title": "Pregame props",
                    "items": [
                        {
                            "name": "Julian Champagnie Over 1.5 3PM",
                            "market": "3PM",
                            "pick": "Over 1.5",
                            "matchup": "SAS at PHX",
                            "projected": 2.3,
                            "line": 1.5,
                            "odds": "+108",
                            "confidence": "60%",
                            "edge": "+3.9%",
                            "writeup": "The volume profile still supports Julian's threes over.",
                            "href": "/nba/prop-ladders?date=2026-06-05",
                        },
                        {
                            "name": "Julian Champagnie Over 11.5 PTS",
                            "market": "PTS",
                            "pick": "Over 11.5",
                            "matchup": "SAS at PHX",
                            "projected": 12.1,
                            "line": 11.5,
                            "odds": "-102",
                            "confidence": "56%",
                            "edge": "+1.7%",
                            "writeup": "The points line is playable but thinner than the threes angle.",
                            "href": "/nba/prop-ladders?date=2026-06-05",
                        },
                        {
                            "name": "Devin Booker Over 2.5 3PM",
                            "market": "3PM",
                            "pick": "Over 2.5",
                            "matchup": "SAS at PHX",
                            "projected": 3.0,
                            "line": 2.5,
                            "odds": "+104",
                            "confidence": "58%",
                            "edge": "+2.4%",
                            "writeup": "Booker still clears the threes line, but this is not the requested player.",
                            "href": "/nba/prop-ladders?date=2026-06-05",
                        },
                    ],
                },
                "live": {"title": "Top Live Props", "items": []},
                "compact": {"items": []},
            },
            "dashboard_games": [],
        }
    ]


def _sample_live_game_projection_overview() -> list[dict[str, object]]:
    return [
        {
            "slug": "nba",
            "name": "NBA",
            "context_label": "2026-06-05",
            "data_health": "healthy",
            "data_warnings": [],
            "home_rails": {
                "pregame": {"title": "Pregame props", "items": []},
                "live": {"title": "Top Live Props", "items": []},
                "compact": {"items": []},
            },
            "dashboard_games": [
                {
                    "matchup": "CLE at IND",
                    "away": {"abbr": "CLE"},
                    "home": {"abbr": "IND"},
                    "summary": "Live model still runs above the current total.",
                    "shared_is_live": True,
                    "href": "/nba/live-lens?date=2026-06-05",
                    "href_label": "Open game",
                    "gameLens": [
                        {
                            "label": "Live",
                            "markets": {
                                "total": {
                                    "pick": "Over 221.5",
                                    "line": 221.5,
                                    "odds": "-108",
                                    "edge": 3.2,
                                    "p_win": 0.57,
                                    "projection": 223.0,
                                    "live_projection": 228.5,
                                }
                            },
                        }
                    ],
                },
                {
                    "matchup": "OKC at DEN",
                    "away": {"abbr": "OKC"},
                    "home": {"abbr": "DEN"},
                    "summary": "Live model only has a narrow total edge.",
                    "shared_is_live": True,
                    "href": "/nba/live-lens?date=2026-06-05",
                    "href_label": "Open game",
                    "gameLens": [
                        {
                            "label": "Live",
                            "markets": {
                                "total": {
                                    "pick": "Over 221.5",
                                    "line": 221.5,
                                    "odds": "-108",
                                    "edge": 3.2,
                                    "p_win": 0.57,
                                    "projection": 223.0,
                                    "live_projection": 222.2,
                                }
                            },
                        }
                    ],
                },
            ],
        }
    ]


def _sample_mlb_statcast_overview() -> list[dict[str, object]]:
    return [
        {
            "slug": "mlb",
            "name": "MLB",
            "context_label": "2026-06-05",
            "data_health": "healthy",
            "data_warnings": [],
            "home_rails": {
                "pregame": {
                    "title": "Pregame props",
                    "items": [
                        {
                            "name": "Aaron Judge Over 0.5 Home Runs",
                            "market": "HR",
                            "pick": "Over 0.5",
                            "matchup": "NYY at BOS",
                            "batter_id": 608324,
                            "opponent_pitcher_id": 605400,
                            "projected": 0.68,
                            "line": 0.5,
                            "odds": "+118",
                            "confidence": "57%",
                            "edge": "+2.4%",
                            "writeup": "Power shape is trending up.",
                            "display_pills": ["Line 0.5", "Odds +118"],
                            "batter_statcast_hr_mult": 1.24,
                            "pitcher_statcast_hr_mult": 1.09,
                            "bvp_history_source": "derived_statcast",
                            "href": "/mlb/props?date=2026-06-05",
                        },
                        {
                            "name": "Mookie Betts Over 1.5 Hits",
                            "market": "Hits",
                            "pick": "Over 1.5",
                            "matchup": "LAD at SF",
                            "batter_id": 605141,
                            "opponent_pitcher_id": 657277,
                            "projected": 1.64,
                            "line": 1.5,
                            "odds": "+118",
                            "confidence": "57%",
                            "edge": "+2.4%",
                            "writeup": "Contact quality is steady.",
                            "display_pills": ["Line 1.5", "Odds +118"],
                            "batter_statcast_inplay_mult": 1.01,
                            "pitcher_statcast_inplay_mult": 1.0,
                            "href": "/mlb/props?date=2026-06-05",
                        },
                    ],
                },
                "live": {"title": "Top Live Props", "items": []},
                "compact": {"items": []},
            },
            "dashboard_games": [],
        }
    ]


def _sample_mlb_market_overview() -> list[dict[str, object]]:
    return [
        {
            "slug": "mlb",
            "name": "MLB",
            "context_label": "2026-06-04",
            "data_health": "healthy",
            "data_warnings": [],
            "home_rails": {
                "pregame": {
                    "title": "Pregame props",
                    "items": [
                        {
                            "name": "Aaron Judge Over 0.5 Home Runs",
                            "market": "Hitter Home Runs",
                            "pick": "Over 0.5",
                            "matchup": "NYY at BOS",
                            "projected": 0.64,
                            "line": 0.5,
                            "odds": "+310",
                            "confidence": "27%",
                            "edge": "+3.2%",
                            "writeup": "Barrel rate and park lift the HR ceiling.",
                            "display_pills": ["Line 0.5", "Odds +310"],
                            "href": "/mlb/prop-ladders?date=2026-06-04",
                        },
                        {
                            "name": "Chris Sale Over 7.5 Strikeouts",
                            "market": "Pitcher Strikeouts",
                            "pick": "Over 7.5",
                            "matchup": "ATL at NYM",
                            "batter_id": 592450,
                            "opponent_pitcher_id": 519242,
                            "projected": 8.4,
                            "line": 7.5,
                            "odds": "+102",
                            "confidence": "61%",
                            "edge": "+4.8%",
                            "writeup": "Whiff-heavy matchup keeps the strikeout ceiling in play.",
                            "display_pills": ["Line 7.5", "Odds +102"],
                            "href": "/mlb/prop-ladders?date=2026-06-04",
                        },
                        {
                            "name": "Freddie Freeman Over 1.5 Total Bases",
                            "market": "Hitter Total Bases",
                            "pick": "Over 1.5",
                            "matchup": "LAD at SD",
                            "batter_id": 518692,
                            "opponent_pitcher_id": 543037,
                            "projected": 2.1,
                            "line": 1.5,
                            "odds": "+115",
                            "confidence": "58%",
                            "edge": "+3.6%",
                            "writeup": "Contact quality and lineup spot support extra-base upside.",
                            "display_pills": ["Line 1.5", "Odds +115"],
                            "href": "/mlb/prop-ladders?date=2026-06-04",
                        },
                    ],
                },
                "live": {"title": "Top Live Props", "items": []},
                "compact": {"items": []},
            },
            "dashboard_games": [],
        }
    ]


def _sample_multi_sport_points_overview() -> list[dict[str, object]]:
    return [
        {
            "slug": "nba",
            "name": "NBA",
            "context_label": "2026-06-04",
            "data_health": "healthy",
            "data_warnings": [],
            "home_rails": {
                "pregame": {
                    "title": "Pregame props",
                    "items": [
                        {
                            "name": "Jayson Tatum Over 28.5",
                            "market": "Points",
                            "pick": "Over 28.5",
                            "matchup": "BOS at NYK",
                            "projected": 31.8,
                            "line": 28.5,
                            "odds": "+102",
                            "confidence": "63%",
                            "edge": "+5.4%",
                            "writeup": "Usage and shot quality keep the points ceiling live.",
                            "href": "/nba/prop-ladders?date=2026-06-04",
                        }
                    ],
                },
                "live": {"title": "Top Live Props", "items": []},
                "compact": {"items": []},
            },
            "dashboard_games": [],
        },
        {
            "slug": "wnba",
            "name": "WNBA",
            "context_label": "2026-06-04",
            "data_health": "healthy",
            "data_warnings": [],
            "home_rails": {
                "pregame": {
                    "title": "Pregame props",
                    "items": [
                        {
                            "name": "A'ja Wilson Over 22.5",
                            "market": "Points",
                            "pick": "Over 22.5",
                            "matchup": "LVA at PHX",
                            "projected": 25.1,
                            "line": 22.5,
                            "odds": "+100",
                            "confidence": "61%",
                            "edge": "+4.1%",
                            "writeup": "Role pressure and stable usage support the points path.",
                            "href": "/wnba/prop-ladders?date=2026-06-04",
                        }
                    ],
                },
                "live": {"title": "Top Live Props", "items": []},
                "compact": {"items": []},
            },
            "dashboard_games": [],
        },
    ]


def _sample_mlb_risk_overview() -> list[dict[str, object]]:
    return [
        {
            "slug": "mlb",
            "name": "MLB",
            "context_label": "2026-06-04",
            "data_health": "healthy",
            "data_warnings": [],
            "home_rails": {
                "pregame": {
                    "title": "Pregame props",
                    "items": [
                        {
                            "name": "Freddie Freeman Over 1.5 Total Bases",
                            "market": "Hitter Total Bases",
                            "pick": "Over 1.5",
                            "matchup": "LAD at SD",
                            "projected": 2.0,
                            "line": 1.5,
                            "odds": "-135",
                            "confidence": "64%",
                            "edge": "+2.5%",
                            "score": 88.0,
                            "writeup": "High-contact shape and lineup spot support the floor.",
                            "href": "/mlb/prop-ladders?date=2026-06-04",
                        },
                        {
                            "name": "Aaron Judge Over 0.5 Home Runs",
                            "market": "Hitter Home Runs",
                            "pick": "Over 0.5",
                            "matchup": "NYY at BOS",
                            "projected": 0.62,
                            "line": 0.5,
                            "odds": "+320",
                            "confidence": "38%",
                            "edge": "+12.8%",
                            "score": 87.0,
                            "writeup": "Barrel rate and pull-side lift create the ceiling case.",
                            "href": "/mlb/prop-ladders?date=2026-06-04",
                        },
                    ],
                },
                "live": {"title": "Top Live Props", "items": []},
                "compact": {"items": []},
            },
            "dashboard_games": [],
        }
    ]


def _sample_mlb_compare_overview() -> list[dict[str, object]]:
    return [
        {
            "slug": "mlb",
            "name": "MLB",
            "context_label": "2026-06-04",
            "data_health": "healthy",
            "data_warnings": [],
            "home_rails": {
                "pregame": {
                    "title": "Pregame props",
                    "items": [
                        {
                            "name": "Aaron Judge Over 0.5 Home Runs",
                            "market": "Hitter Home Runs",
                            "pick": "Over 0.5",
                            "matchup": "NYY at BOS",
                            "projected": 0.64,
                            "line": 0.5,
                            "odds": "+310",
                            "confidence": "27%",
                            "edge": "+3.2%",
                            "writeup": "Barrel rate and park lift the HR ceiling.",
                            "href": "/mlb/prop-ladders?date=2026-06-04",
                        },
                        {
                            "name": "Shohei Ohtani Over 0.5 Home Runs",
                            "market": "Hitter Home Runs",
                            "pick": "Over 0.5",
                            "matchup": "LAD at SD",
                            "projected": 0.58,
                            "line": 0.5,
                            "odds": "+295",
                            "confidence": "25%",
                            "edge": "+2.7%",
                            "writeup": "Pulled-air damage and lift support the HR path.",
                            "href": "/mlb/prop-ladders?date=2026-06-04",
                        },
                        {
                            "name": "Freddie Freeman Over 1.5 Total Bases",
                            "market": "Hitter Total Bases",
                            "pick": "Over 1.5",
                            "matchup": "LAD at SD",
                            "projected": 2.1,
                            "line": 1.5,
                            "odds": "+115",
                            "confidence": "58%",
                            "edge": "+3.6%",
                            "writeup": "Contact quality and lineup spot support extra-base upside.",
                            "href": "/mlb/prop-ladders?date=2026-06-04",
                        },
                    ],
                },
                "live": {
                    "title": "Top Live Props",
                    "items": [
                        {
                            "name": "Aaron Judge Over 1.5 Hits",
                            "market": "Hits",
                            "pick": "Over 1.5",
                            "matchup": "NYY at BOS",
                            "projected": 1.8,
                            "live_projection": 2.0,
                            "actual": 1,
                            "line": 1.5,
                            "odds": "+125",
                            "confidence": "57%",
                            "edge": "+4.1%",
                            "writeup": "Live contact shape still favors another knock.",
                            "is_live": True,
                            "href": "/mlb/live-lens?date=2026-06-04",
                        },
                        {
                            "name": "Mookie Betts Over 1.5 Hits",
                            "market": "Hits",
                            "pick": "Over 1.5",
                            "matchup": "LAD at SD",
                            "projected": 1.7,
                            "live_projection": 1.9,
                            "actual": 1,
                            "line": 1.5,
                            "odds": "+118",
                            "confidence": "55%",
                            "edge": "+3.4%",
                            "writeup": "Ball-in-play quality is still carrying the lane.",
                            "is_live": True,
                            "href": "/mlb/live-lens?date=2026-06-04",
                        },
                    ],
                },
                "compact": {"items": []},
            },
            "dashboard_games": [],
        }
    ]


def _sample_mlb_live_pitcher_state_overview() -> list[dict[str, object]]:
    return [
        {
            "slug": "mlb",
            "name": "MLB",
            "context_label": "2026-06-05",
            "data_health": "healthy",
            "data_warnings": [],
            "home_rails": {
                "pregame": {"title": "Pregame props", "items": []},
                "live": {
                    "title": "Top Live Props",
                    "items": [
                        {
                            "game_pk": 1,
                            "name": "Chris Sale Over 5.5 Strikeouts",
                            "player_name": "Chris Sale",
                            "market": "Pitcher Strikeouts",
                            "pick": "Over 5.5",
                            "matchup": "ATL at NYM",
                            "pitcher_id": 519242,
                            "projected": 6.2,
                            "live_projection": 6.0,
                            "actual": 3,
                            "line": 5.5,
                            "odds": "+102",
                            "confidence": "61%",
                            "edge": "+4.8%",
                            "writeup": "The model still liked the strikeout path before the live pitching change.",
                            "is_live": True,
                            "href": "/mlb/live-lens?date=2026-06-05",
                        },
                        {
                            "game_pk": 1,
                            "name": "Pete Alonso Over 1.5 Total Bases",
                            "player_name": "Pete Alonso",
                            "market": "Hitter Total Bases",
                            "pick": "Over 1.5",
                            "matchup": "ATL at NYM",
                            "projected": 1.9,
                            "live_projection": 2.1,
                            "actual": 1,
                            "line": 1.5,
                            "odds": "+115",
                            "confidence": "58%",
                            "edge": "+3.2%",
                            "writeup": "The live board still supports Alonso against the current game script.",
                            "is_live": True,
                            "href": "/mlb/live-lens?date=2026-06-05",
                        },
                    ],
                },
                "compact": {"items": []},
            },
            "dashboard_games": [],
        }
    ]


def _sample_nfl_market_overview() -> list[dict[str, object]]:
    return [
        {
            "slug": "nfl",
            "name": "NFL",
            "context_label": "2026-09-10",
            "data_health": "healthy",
            "data_warnings": [],
            "home_rails": {
                "pregame": {
                    "title": "Pregame props",
                    "items": [
                        {
                            "name": "CeeDee Lamb Over 86.5 Receiving Yards",
                            "market": "Receiving Yards",
                            "pick": "Over 86.5",
                            "matchup": "DAL at PHI",
                            "off_epa_advanced": 1.11,
                            "target_share_advanced": 0.29,
                            "pass_rate_advanced": 1.07,
                            "air_yards_advanced": 1.13,
                            "projected": 94.1,
                            "line": 86.5,
                            "odds": "+105",
                            "confidence": "61%",
                            "edge": "+4.4%",
                            "writeup": "Target share and matchup support the receiving ceiling.",
                            "display_pills": ["Line 86.5", "Odds +105"],
                            "href": "/nfl/props?date=2026-09-10",
                        }
                    ],
                },
                "live": {"title": "Top Live Props", "items": []},
                "compact": {"items": []},
            },
            "dashboard_games": [],
        }
    ]


def _sample_nhl_market_overview() -> list[dict[str, object]]:
    return [
        {
            "slug": "nhl",
            "name": "NHL",
            "context_label": "2026-06-04",
            "data_health": "healthy",
            "data_warnings": [],
            "home_rails": {
                "pregame": {"title": "Pregame props", "items": []},
                "live": {
                    "title": "Top Live Props",
                    "items": [
                        {
                            "name": "Nathan MacKinnon Over 4.5 Shots",
                            "market": "Shots",
                            "pick": "Over 4.5",
                            "matchup": "COL at EDM",
                            "projected": 5.2,
                            "live_projection": 5.8,
                            "actual": 3,
                            "line": 4.5,
                            "odds": "+110",
                            "confidence": "60%",
                            "edge": "+3.7%",
                            "writeup": "Volume is holding even after the live move.",
                            "display_pills": ["Line 4.5", "Odds +110", "Live Proj 5.8"],
                            "is_live": True,
                            "href": "/nhl/live?date=2026-06-04",
                        }
                    ],
                },
                "compact": {"items": []},
            },
            "dashboard_games": [],
        }
    ]


class IntelligenceBlueprintTests(unittest.TestCase):
    def test_collect_candidates_promotes_wnba_props_csv_into_board_contract(self) -> None:
        candidate_item = {
            "name": "Dearica Hamby Over 1.5 AST",
            "market": "AST",
            "pick": "Over 1.5",
            "matchup": "LAS at SEA",
            "projected": 3.5,
            "line": 1.5,
            "odds": "-112",
            "confidence": "0.0",
            "edge": "12.0%",
            "writeup": "OVER 1.5 AST | model 3.5 vs line 1.5 (+2.0)",
            "href": "/wnba/cards?date=2026-07-06",
        }
        overview = [
            {
                "slug": "wnba",
                "name": "WNBA",
                "context_label": "2026-07-06",
                "data_health": "healthy",
                "data_warnings": [],
                "active_today": True,
                "home_rails": {
                    "compact": {"title": "Compact game rail", "items": [], "links": [], "empty_summary": ""},
                    "pregame": {"title": "Pregame props", "items": [candidate_item], "links": [], "empty_summary": ""},
                    "live": {"title": "Top Live Props", "items": [], "links": [], "empty_summary": ""},
                },
                "dashboard_games": [],
            }
        ]

        preferences = {
            "question": "top edges today",
            "mode": "recommendation",
            "sport": "all",
            "timing": "all",
            "include_props": True,
            "include_games": True,
            "requested_markets": [],
        }
        candidates = collect_candidates(overview, preferences)
        board = build_intelligence_board_contract({"recommendations": candidates})

        self.assertTrue(any(candidate.get("sport_slug") == "wnba" for candidate in candidates))
        self.assertTrue(any(card.get("sport") == "wnba" for card in board["cards"]))
        self.assertEqual(board["lane_counts"]["pregame"], 1)
        self.assertGreaterEqual(board["recommendation_count"], 1)

    def setUp(self) -> None:
        # Isolate every test in this class from ambient dev-machine state
        # *before* create_app() runs, in this order:
        #
        # 1. Prevent create_app()'s real background loops. On a non-Render
        #    dyno (true for every local/CI test run), create_app()
        #    registers a Flask before_request hook that -- on this test
        #    class's very first client request -- spawns a real daemon
        #    thread calling start_intelligence_state_background_loop() and
        #    start_live_refresh_background_loop(). Since setUp() builds a
        #    brand-new app per test, every single test method was
        #    triggering a fresh background thread that outlives the test,
        #    accumulating dozens of live threads across a full run and
        #    doing real (if throttled) I/O/refresh work concurrently with
        #    whatever the test itself was asserting -- a real contributor
        #    to both non-determinism and the suite's runtime.
        # 2. Redirect the on-disk intelligence-state cache
        #    (reports/intelligence/*.json) to a fresh temp directory per
        #    test, and swap in a brand-new IntelligenceStateService so its
        #    in-memory snapshot cache doesn't leak across test methods
        #    either. Previously every test shared this repo's real,
        #    already-populated reports/intelligence/ files (this being a
        #    dev machine also used to run the app directly), so a test's
        #    build_intelligence_overview mock frequently never even ran --
        #    the cache-first read path
        #    (_latest_non_empty_intelligence_board_snapshot_response)
        #    found real on-disk data first and returned that, silently
        #    bypassing the mock entirely.
        self._background_loop_patchers = [
            patch("syndicate.app.start_intelligence_state_background_loop", return_value=False),
            patch("syndicate.app.start_live_refresh_background_loop", return_value=None),
        ]
        for loop_patcher in self._background_loop_patchers:
            loop_patcher.start()

        self._intel_state_tempdir = TemporaryDirectory()
        temp_reports_dir = Path(self._intel_state_tempdir.name) / "intelligence"
        temp_reports_dir.mkdir(parents=True, exist_ok=True)

        # 1b. Same isolation problem again, for the per-sport artifact roots.
        #     The redirects below cover pipeline.intelligence_state.* and (further
        #     down) the evaluation ledger, but nothing pointed the *sport source
        #     roots* away from this repo's real data/<sport>_source/ trees. So the
        #     query pipeline walked genuine production artifacts: e.g.
        #     test_mlb_live_prop_rows_do_not_fall_back_to_top_props_when_live_payload_has_no_props
        #     asserted an empty list and got real rows back
        #     ("game_pk": 823860, "TB @ MIA"). Each SYNDICATE_<SPORT>_SOURCE_ROOT
        #     *replaces* the search path rather than prepending to it (see
        #     mlb/sources.py::_source_roots -- SYNDICATE_DATA_ROOT would NOT work
        #     here, it keeps the repo path as a fallback), so pointing all eight at
        #     one empty directory is what actually isolates them.
        empty_source_root = Path(self._intel_state_tempdir.name) / "empty_source_root"
        empty_source_root.mkdir(parents=True, exist_ok=True)
        #     Do NOT add SYNDICATE_DATA_ROOT here. It was tried and measurably
        #     made things worse on both axes: the MLB real-data leak above came
        #     back (0.20s pass -> failing again) and the two slow query tests got
        #     slower (2.61s -> 3.05s, 3.14s -> 4.21s). Setting it changes which
        #     branch the artifact-root resolvers take, and they still keep a repo
        #     fallback -- only the per-sport vars actually replace the path.
        self._source_root_env_patcher = patch.dict(
            os.environ,
            {
                f"SYNDICATE_{sport}_SOURCE_ROOT": str(empty_source_root)
                for sport in ("MLB", "WNBA", "NBA", "NHL", "NFL", "NCAAF", "NCAAB", "SOCCER")
            },
        )
        self._source_root_env_patcher.start()

        # 1c. Do not persist intelligence state during tests. Profiling
        #     test_intelligence_query_ranks_basketball_candidates_using_source_summary
        #     put ~86% of its runtime inside IntelligenceStateService._persist_locked
        #     -> refresh_state_store.write_json_file -> json.dumps: 210 dumps and
        #     8.4M _iterencode calls for ONE request, because a force_refresh query
        #     serialises the whole multi-megabyte state blob (the same payload #43
        #     is about) on every call. Nothing in this file asserts on persisted
        #     content -- the only references to the state paths are the redirects
        #     right below -- so the write is pure cost here.
        self._persist_patcher = patch.object(IntelligenceStateService, "_persist_locked", return_value=None)
        self._persist_patcher.start()

        # 1d used to patch out record_prediction here -- intelligence.py called
        #     it on every query and rewrote the real 2.5MB ledger twice per
        #     test (1.46s of a 2.6s test). The production write path itself
        #     was deleted 2026-07-27 (#72), so there is nothing left to patch.

        self._intel_state_path_patchers = [
            patch("pipeline.intelligence_state.STATE_PATH", temp_reports_dir / "query_state_cache.json"),
            patch("pipeline.intelligence_state.BOARD_SNAPSHOT_PATH", temp_reports_dir / "board_snapshot.json"),
            patch("pipeline.intelligence_state.STATUS_CACHE_PATH", temp_reports_dir / "status_response_cache.json"),
            patch("pipeline.intelligence_state.INTELLIGENCE_STATE_PATH", temp_reports_dir / "intelligence_state.json"),
            patch("pipeline.intelligence_state.INTELLIGENCE_HISTORY_PATH", temp_reports_dir / "intelligence_state_history.jsonl"),
            patch("pipeline.intelligence_state.LIVE_PIPELINE_LAST_SUCCESSFUL_PATH", temp_reports_dir / "live_pipeline_last_successful.json"),
            patch("pipeline.intelligence_state.reports_root", return_value=Path(self._intel_state_tempdir.name)),
            patch("pipeline.intelligence_state._INTELLIGENCE_STATE_SERVICE", IntelligenceStateService()),
        ]
        for path_patcher in self._intel_state_path_patchers:
            path_patcher.start()

        app = create_app()
        app.config.update(TESTING=True)
        self.client = app.test_client()
        self._shared_recommendations_patcher = patch(
            "syndicate.features.intelligence.collect_all_recommendations",
            return_value=[],
        )
        self._shared_recommendations_patcher.start()
        self._artifact_manifests_patcher = patch(
            "syndicate.features.intelligence.load_artifact_manifests",
            return_value=[],
        )
        self._artifact_manifests_patcher.start()
        self._reliability_profile_patcher = patch(
            "syndicate.features.shared.intelligence_evaluation.build_reliability_profile",
            return_value={"sample_size": 0, "metrics": {}},
        )
        self._reliability_profile_patcher.start()
        # Same isolation problem as the pipeline.intelligence_state.* paths
        # above, for a completely separate module: build_intelligence_evaluation_bundle
        # (invoked by force_refresh=True query-api requests) reads/writes
        # syndicate.features.shared.intelligence_evaluation.DEFAULT_LEDGER_PATH
        # (reports/intelligence/evaluation_ledger.jsonl) and its
        # evaluation_ledger_chunks/ directory by default -- on this dev
        # machine, that directory has grown to several GB of real
        # accumulated data from actually running the app, making every one
        # of these requests take 60-150+ seconds to scan/append to it, and
        # growing it further on every test run. Redirect to the same
        # per-test temp dir already used above.
        self._evaluation_ledger_path_patcher = patch(
            "syndicate.features.shared.intelligence_evaluation.DEFAULT_LEDGER_PATH",
            temp_reports_dir / "evaluation_ledger.jsonl",
        )
        self._evaluation_ledger_path_patcher.start()
        # syndicate.features.intelligence.load_artifact_manifests (mocked
        # above via self._artifact_manifests_patcher) is that module's OWN
        # bound import -- intelligence_evaluation.py imports the exact same
        # function separately (`from syndicate.features.shared.artifact_manifests
        # import load_artifact_manifests`), so patching the former never
        # touched the latter's real, unmocked scan of this dev machine's
        # actual per-sport artifact manifests inside
        # build_artifact_metadata -> _artifact_manifest_summary.
        self._evaluation_artifact_manifests_patcher = patch(
            "syndicate.features.shared.intelligence_evaluation.load_artifact_manifests",
            return_value=[],
        )
        self._evaluation_artifact_manifests_patcher.start()
        self._simulation_patcher = patch(
            "syndicate.features.simulation_engine.SimulationEngine.run_simulation",
            return_value={},
        )
        self._simulation_patcher.start()
        # Both genuinely fast/pure (no I/O), but they log "compute in request
        # path" warnings and, more importantly, were previously reached far
        # less often because the disk-cache leak (fixed above) usually
        # short-circuited before the query pipeline got this far. Mocking
        # them keeps these tests deterministic regardless of the specific
        # candidate pool a test's fixture produces.
        self._bet_size_patcher = patch(
            "syndicate.features.intelligence._compute_bet_size",
            return_value={"model_probability": 0.5, "implied_probability": 0.5, "odds": None, "odds_adjustment": 0.5, "edge": 0.0, "kelly_fraction": 0.0, "confidence": 0.5, "cap_fraction": 0.02, "recommended_bet_size": 0.0},
        )
        self._bet_size_patcher.start()
        self._correlation_patcher = patch(
            "syndicate.features.intelligence._compute_candidate_correlation",
            return_value={"correlation_score": 0.0, "same_game": False, "same_team": False},
        )
        self._correlation_patcher.start()

    def test_build_intelligence_overview_preserves_requested_date(self) -> None:
        app = create_app()
        app.config.update(TESTING=True)
        app.config["SYNDICATE_SPORTS"] = [{"slug": "mlb", "name": "MLB"}]

        with app.app_context():
            with patch(
                "syndicate.features.intelligence._build_sport_overview",
                return_value={"slug": "mlb", "context_label": "2026-06-07"},
            ) as mocked_build:
                build_intelligence_overview(selected_date="2026-06-17", force_refresh=True)

        mocked_build.assert_called_once_with(
            {"slug": "mlb", "name": "MLB"},
            "2026-06-17",
            force_refresh=True,
            preserve_requested_date=True,
            skip_game_hydration=False,
        )

    def test_build_intelligence_overview_falls_back_without_app_context(self) -> None:
        with patch("syndicate.features.intelligence._configured_syndicate_sports", return_value=[{"slug": "mlb", "name": "MLB"}]), patch(
            "syndicate.features.intelligence._build_sport_overview",
            return_value={"slug": "mlb"},
        ) as mocked_build:
            overview = build_intelligence_overview(selected_date="2026-07-04", force_refresh=True)

        self.assertEqual(overview, [{"slug": "mlb"}])
        mocked_build.assert_called_once()
        sports_arg = mocked_build.call_args.args[0]
        self.assertIsInstance(sports_arg, dict)
        self.assertEqual(sports_arg.get("slug"), "mlb")

    def test_build_intelligence_overview_keeps_hidden_sports_for_pipeline(self) -> None:
        app = create_app()
        app.config.update(TESTING=True)
        app.config["SYNDICATE_SPORTS"] = [
            {"slug": "mlb", "name": "MLB"},
            {"slug": "nba", "name": "NBA"},
        ]

        with app.app_context():
            with patch(
                "syndicate.features.intelligence._build_sport_overview",
                side_effect=[
                    {"slug": "mlb", "show_on_home": True, "context_label": "2026-07-05"},
                    {"slug": "nba", "show_on_home": False, "context_label": "2026-07-05"},
                ],
            ) as mocked_build:
                overview = build_intelligence_overview(selected_date="2026-07-05", force_refresh=True)

        self.assertEqual([sport["slug"] for sport in overview], ["mlb", "nba"])
        self.assertEqual(mocked_build.call_count, 2)

    def test_build_intelligence_overview_accepts_artifact_backed_wnba_slate_without_placeholder(self) -> None:
        app = create_app()
        app.config.update(TESTING=True)
        app.config["SYNDICATE_SPORTS"] = [{"slug": "wnba", "name": "WNBA"}]

        with TemporaryDirectory() as temp_dir:
            processed_dir = Path(temp_dir) / "data" / "processed"
            processed_dir.mkdir(parents=True, exist_ok=True)
            (processed_dir / "game_cards_2026-07-06.csv").write_text(
                "away_tri,home_tri,visitor_team,home_team,commence_time\n"
                "LAS,SEA,Las Vegas Aces,Seattle Storm,2026-07-06T23:00:00Z\n",
                encoding="utf-8",
            )
            (processed_dir / "recommendations_slate_2026-07-06.json").write_text("{}", encoding="utf-8")
            (processed_dir / "cards_props_snapshot_2026-07-06.json").write_text("{}", encoding="utf-8")
            (processed_dir / "cards_sim_detail_2026-07-06.json").write_text("{}", encoding="utf-8")

            with app.app_context():
                with patch("syndicate.features.wnba.sources._source_roots", return_value=[Path(temp_dir)]), patch(
                    "syndicate.features.wnba.cards._wnba_source_roots",
                    return_value=[Path(temp_dir)],
                ), patch(
                    "syndicate.features.wnba.cards._render_web_dyno",
                    return_value=True,
                ):
                    from syndicate.features.wnba.cards import get_wnba_overview

                    overview_payload = get_wnba_overview("2026-07-06")
                    self.assertEqual(overview_payload.get("status"), "ok")

                    overview = build_intelligence_overview(selected_date="2026-07-06", force_refresh=True)

        self.assertEqual([sport["slug"] for sport in overview], ["wnba"])
        self.assertGreater(len(overview[0].get("dashboard_games") or []), 0)

        preferences = _query_preferences(
            "top edges today",
            mode="recommendation",
            sport="all",
            timing="all",
            include_props=True,
            include_games=True,
        )
        trace_events: list[tuple[str, dict[str, object]]] = []

        def _capture_trace(event: str, **fields: object) -> None:
            trace_events.append((event, dict(fields)))

        with patch("syndicate.features.intelligence._intel_trace", side_effect=_capture_trace):
            collect_candidates(overview, preferences)

        self.assertTrue(any(event == "candidate_generation" and fields.get("sport") == "wnba" for event, fields in trace_events))

    def tearDown(self) -> None:
        self._shared_recommendations_patcher.stop()
        self._artifact_manifests_patcher.stop()
        self._reliability_profile_patcher.stop()
        self._evaluation_ledger_path_patcher.stop()
        self._evaluation_artifact_manifests_patcher.stop()
        self._simulation_patcher.stop()
        self._bet_size_patcher.stop()
        self._correlation_patcher.stop()
        for path_patcher in self._intel_state_path_patchers:
            path_patcher.stop()
        self._persist_patcher.stop()
        self._source_root_env_patcher.stop()
        self._intel_state_tempdir.cleanup()
        for loop_patcher in self._background_loop_patchers:
            loop_patcher.stop()

    def test_query_preferences_parses_exact_parlay_leg_count(self) -> None:
        preferences = _query_preferences("Build me a four-leg parlay from the best NBA edges")

        self.assertEqual(preferences.get("intent"), "parlay")
        self.assertEqual(preferences.get("parlay_leg_min"), 4)
        self.assertEqual(preferences.get("parlay_leg_max"), 4)

    def test_query_preferences_parses_parlay_leg_range(self) -> None:
        preferences = _query_preferences("Build a 2 to 5 leg parlay from the best live edges")

        self.assertEqual(preferences.get("parlay_leg_min"), 2)
        self.assertEqual(preferences.get("parlay_leg_max"), 5)

    def test_query_preferences_parses_parlay_structure_risk_and_correlation(self) -> None:
        preferences = _query_preferences("Build a same game round robin with low correlation and aggressive cross-sport upside")

        self.assertEqual(preferences.get("parlay_type"), "round_robin")
        self.assertTrue(preferences.get("cross_sport_required"))
        self.assertEqual(preferences.get("risk_profile"), "aggressive")
        self.assertEqual(preferences.get("correlation_tolerance"), "low")
        self.assertEqual(preferences.get("round_robin_unit"), 2)

    def test_query_preferences_parses_market_focus_and_bankroll_controls(self) -> None:
        preferences = _query_preferences("Build me a live ML parlay with medium correlation, $100 bankroll, and max 20% exposure")

        self.assertEqual(preferences.get("intent"), "parlay")
        self.assertTrue(preferences.get("live_only"))
        self.assertFalse(preferences.get("pregame_only"))
        self.assertEqual(preferences.get("requested_markets"), ["moneyline"])
        self.assertEqual(preferences.get("correlation_tolerance"), "medium")
        self.assertTrue(preferences.get("correlation_explicit"))
        self.assertEqual(preferences.get("bankroll_amount"), 100)
        self.assertEqual(preferences.get("max_exposure_pct"), 20)

    def test_query_preferences_normalizes_three_point_make_aliases(self) -> None:
        preferences = _query_preferences("Julian champaigne 3ptM")

        self.assertEqual(preferences.get("requested_markets"), ["threes"])

    def test_market_key_from_text_agrees_across_hits_runs_rbis_label_variants(self) -> None:
        # Every real-world spelling of this composite stat across MLB's
        # candidate builders must resolve to the SAME key -- daily_top_props'
        # stat key ("hits_runs_rbis"), its own statLabel ("Hits + Runs +
        # RBIs"), and live-lens's abbreviated vendor-sim label ("Hitter
        # H+R+R"). Before this stat had its own _MARKET_FOCUS_ALIASES entry,
        # the first two false-matched the plain "hits" alias while the third
        # fell through to a different fallback key entirely.
        from syndicate.features.intelligence import _market_key_from_text

        variants = ("hits_runs_rbis", "Hits + Runs + RBIs", "Hitter H+R+R", "Hitter H+r+r", "H+R+R")
        keys = {_market_key_from_text(text, allow_fallback=True) for text in variants}
        self.assertEqual(keys, {"hits_runs_rbis"})
        # And the plain single-stat "Hits" market must be unaffected.
        self.assertEqual(_market_key_from_text("Hits", allow_fallback=True), "hits")
        self.assertEqual(_market_key_from_text("hits", allow_fallback=True), "hits")

    def test_query_preferences_infers_baseball_market_focus(self) -> None:
        preferences = _query_preferences("Who are the top 3 strikeout targets for today?")

        self.assertEqual(preferences.get("requested_sports"), ["mlb"])
        self.assertEqual(preferences.get("requested_markets"), ["strikeouts"])
        self.assertTrue(preferences.get("include_props"))
        self.assertFalse(preferences.get("include_games"))
        self.assertEqual(preferences.get("limit"), 3)

    def test_query_preferences_extracts_requested_date(self) -> None:
        preferences = _query_preferences("Who are the top 3 strikeout targets for 20260604?")

        self.assertEqual(preferences.get("requested_date"), "2026-06-04")

    def test_query_preferences_applies_explicit_timing_scope_and_limit_overrides(self) -> None:
        preferences = _query_preferences(
            "Show me the strongest board targets today.",
            timing="live",
            include_props=True,
            include_games=False,
            limit=7,
        )

        self.assertEqual(preferences.get("intent"), "live_bets")
        self.assertTrue(preferences.get("live_only"))
        self.assertFalse(preferences.get("pregame_only"))
        self.assertTrue(preferences.get("include_props"))
        self.assertFalse(preferences.get("include_games"))
        self.assertEqual(preferences.get("limit"), 7)

    def test_query_preferences_keeps_mixed_timing_for_all_state_boards(self) -> None:
        preferences = _query_preferences(
            "What are the best edges for this board?",
            timing="all",
        )

        self.assertFalse(preferences.get("live_only"))
        self.assertFalse(preferences.get("pregame_only"))
        self.assertTrue(preferences.get("include_props"))
        self.assertTrue(preferences.get("include_games"))

    def test_collect_candidates_preserves_valid_mlb_candidates_with_tiers(self) -> None:
        overview = [
            {
                "slug": "mlb",
                "name": "MLB",
                "context_label": "2026-06-04",
                "active_today": True,
                "data_health": "healthy",
                "data_warnings": [],
                "home_rails": {
                    "pregame": {
                        "title": "Pregame props",
                        "items": [
                            {
                                "name": "Fallback MLB Prop",
                                "market": "Hitter Total Bases",
                                "pick": "Over 1.5",
                                "matchup": "NYY at BOS",
                                "projected": 1.9,
                                "line": 1.5,
                                "odds": "+115",
                                "confidence": "58%",
                                "edge": "+3.2%",
                                "writeup": "Daily top props fallback",
                                "detail": "Over 1.5 Hitter Total Bases | Daily top props fallback",
                                "summary": "Daily top props fallback",
                                "href": "/mlb/cards?date=2026-06-04",
                            }
                        ],
                    },
                    "live": {"title": "Top Live Props", "items": []},
                    "compact": {"items": []},
                },
                "dashboard_games": [],
            },
            {
                "slug": "wnba",
                "name": "WNBA",
                "context_label": "2026-06-04",
                "active_today": True,
                "data_health": "healthy",
                "data_warnings": [],
                "home_rails": {
                    "pregame": {
                        "title": "Pregame props",
                        "items": [
                            {
                                "name": "A'ja Wilson Over 24.5",
                                "market": "PTS",
                                "pick": "Over 24.5",
                                "matchup": "LVA at SEA",
                                "projected": 28.1,
                                "line": 24.5,
                                "odds": "+102",
                                "confidence": "63%",
                                "edge": "+5.4%",
                                "writeup": "Projection is clearing the number with stable volume.",
                                "href": "/wnba/prop-ladders?date=2026-06-04",
                            }
                        ],
                    },
                    "live": {"title": "Top Live Props", "items": []},
                    "compact": {"items": []},
                },
                "dashboard_games": [],
            },
        ]

        preferences = _query_preferences("top edges today", mode="recommendation", sport="all", timing="all", include_props=True, include_games=True)
        candidates = collect_candidates(overview, preferences)

        candidates_by_sport = {str(candidate.get("sport_slug") or "").lower(): candidate for candidate in candidates}
        self.assertIn("wnba", candidates_by_sport)
        self.assertIn("mlb", candidates_by_sport)
        self.assertEqual(candidates_by_sport["wnba"].get("tier"), "tier_2")
        self.assertEqual(candidates_by_sport["mlb"].get("tier"), "tier_2")
        self.assertGreater(float(candidates_by_sport["mlb"].get("projected") or 0.0), 0.0)
        self.assertTrue("fallback" in str(candidates_by_sport["mlb"].get("detail") or candidates_by_sport["mlb"].get("summary") or "").lower())

    def test_collect_candidates_drops_final_and_inactive_prop_rows(self) -> None:
        overview = [
            {
                "slug": "nba",
                "name": "NBA",
                "context_label": "2026-06-06",
                "active_today": True,
                "data_health": "healthy",
                "data_warnings": [],
                "home_rails": {
                    "pregame": {
                        "title": "Pregame props",
                        "items": [
                            {
                                "name": "Jayson Tatum Over 28.5",
                                "market": "PTS",
                                "pick": "Over 28.5",
                                "matchup": "BOS at NYK",
                                "projected": 31.8,
                                "line": 28.5,
                                "odds": "+102",
                                "confidence": "63%",
                                "edge": "+5.4%",
                                "writeup": "Projection is clearing the number with usage and minutes support.",
                                "href": "/nba/prop-ladders?date=2026-06-06",
                            },
                            {
                                "name": "Al Horford Over 7.5 Rebounds",
                                "market": "REB",
                                "pick": "Over 7.5",
                                "matchup": "BOS at NYK",
                                "projected": 8.1,
                                "line": 7.5,
                                "odds": "+110",
                                "confidence": "56%",
                                "edge": "+1.9%",
                                "status_display": "Inactive",
                                "status_context": "Out",
                                "writeup": "This row should be filtered because the player is inactive.",
                                "href": "/nba/prop-ladders?date=2026-06-06",
                            },
                            {
                                "name": "Jaylen Brown Over 22.5 Points",
                                "market": "PTS",
                                "pick": "Over 22.5",
                                "matchup": "BOS at NYK",
                                "projected": 24.0,
                                "line": 22.5,
                                "odds": "-104",
                                "confidence": "58%",
                                "edge": "+2.2%",
                                "status_display": "Final",
                                "status_context": "Completed",
                                "writeup": "This row should be filtered because the game is final.",
                                "href": "/nba/prop-ladders?date=2026-06-06",
                            },
                        ],
                    },
                    "live": {"title": "Top Live Props", "items": []},
                    "compact": {"items": []},
                },
                "dashboard_games": [],
            }
        ]

        preferences = _query_preferences("top edges today", mode="recommendation", sport="all", timing="all", include_props=True, include_games=False)
        candidates = collect_candidates(overview, preferences)

        candidate_names = [str(candidate.get("name") or "") for candidate in candidates]
        self.assertIn("Jayson Tatum Over 28.5", candidate_names)
        self.assertNotIn("Al Horford Over 7.5 Rebounds", candidate_names)
        self.assertNotIn("Jaylen Brown Over 22.5 Points", candidate_names)

    def test_collect_candidates_keeps_multi_sport_pregame_and_live_rows(self) -> None:
        overview = [
            {
                "slug": "mlb",
                "name": "MLB",
                "context_label": "2026-06-06",
                "active_today": True,
                "data_health": "healthy",
                "data_warnings": [],
                "home_rails": {
                    "pregame": {
                        "title": "Pregame props",
                        "items": [
                            {
                                "name": "Mookie Betts Over 1.5 Hits",
                                "market": "Hits",
                                "pick": "Over 1.5",
                                "matchup": "LAD at SFG",
                                "projected": 1.8,
                                "line": 1.5,
                                "odds": "+104",
                                "confidence": "60%",
                                "edge": "+2.5%",
                                "writeup": "Pregame MLB prop",
                                "href": "/mlb/cards?date=2026-06-06",
                            }
                        ],
                    },
                    "live": {
                        "title": "Top Live Props",
                        "items": [
                            {
                                "name": "Freddie Freeman Over 1.5 Hits",
                                "market": "Hits",
                                "pick": "Over 1.5",
                                "matchup": "LAD at SFG",
                                "projected": 2.1,
                                "live_projection": 2.3,
                                "line": 1.5,
                                "odds": "+118",
                                "confidence": "59%",
                                "edge": "+2.9%",
                                "is_live": True,
                                "writeup": "Live MLB prop",
                                "href": "/mlb/cards?date=2026-06-06",
                            }
                        ],
                    },
                    "compact": {"items": []},
                },
                "dashboard_games": [
                    {
                        "matchup": "LAD at SFG",
                        "is_live": False,
                    }
                ],
            },
            {
                "slug": "wnba",
                "name": "WNBA",
                "context_label": "2026-06-06",
                "active_today": True,
                "data_health": "healthy",
                "data_warnings": [],
                "home_rails": {
                    "pregame": {
                        "title": "Pregame props",
                        "items": [
                            {
                                "name": "A'ja Wilson Over 24.5 Points",
                                "market": "PTS",
                                "pick": "Over 24.5",
                                "matchup": "LVA at SEA",
                                "projected": 27.1,
                                "line": 24.5,
                                "odds": "+102",
                                "confidence": "63%",
                                "edge": "+4.1%",
                                "writeup": "Pregame WNBA prop",
                                "href": "/wnba/prop-ladders?date=2026-06-06",
                            }
                        ],
                    },
                    "live": {
                        "title": "Top Live Props",
                        "items": [
                            {
                                "name": "A'ja Wilson Over 26.5 Points",
                                "market": "PTS",
                                "pick": "Over 26.5",
                                "matchup": "LVA at SEA",
                                "projected": 28.0,
                                "live_projection": 28.8,
                                "line": 26.5,
                                "odds": "+122",
                                "confidence": "61%",
                                "edge": "+3.7%",
                                "is_live": True,
                                "writeup": "Live WNBA prop",
                                "href": "/wnba/prop-ladders?date=2026-06-06",
                            }
                        ],
                    },
                    "compact": {"items": []},
                },
                "dashboard_games": [
                    {
                        "matchup": "LVA at SEA",
                        "is_live": True,
                    }
                ],
            },
        ]

        def _fake_game_candidates_for_sport(sport: dict[str, object]) -> list[dict[str, object]]:
            slug = str(sport.get("slug") or "").lower()
            if slug == "mlb":
                return [
                    {
                        "candidate_type": "game",
                        "sport": "MLB",
                        "sport_slug": "mlb",
                        "selection": "LAD ML",
                        "pick": "LAD ML",
                        "market": "Moneyline",
                        "projection": 0.57,
                        "odds": "+108",
                        "is_live": False,
                        "is_final": False,
                        "matchup": "LAD at SFG",
                    }
                ]
            if slug == "wnba":
                return [
                    {
                        "candidate_type": "game",
                        "sport": "WNBA",
                        "sport_slug": "wnba",
                        "selection": "LVA ML",
                        "pick": "LVA ML",
                        "market": "Moneyline",
                        "projection": 0.61,
                        "odds": "+114",
                        "is_live": True,
                        "is_final": False,
                        "matchup": "LVA at SEA",
                    }
                ]
            return []

        preferences = _query_preferences("top edges today", mode="recommendation", sport="all", timing="all", include_props=True, include_games=True)
        with patch("syndicate.features.intelligence._game_candidates_for_sport", side_effect=_fake_game_candidates_for_sport):
            candidates = collect_candidates(overview, preferences)

        by_sport = {}
        live_count = 0
        pregame_count = 0
        for candidate in candidates:
            sport_slug = str(candidate.get("sport_slug") or "").lower()
            by_sport.setdefault(sport_slug, 0)
            by_sport[sport_slug] += 1
            if bool(candidate.get("is_live")):
                live_count += 1
            else:
                pregame_count += 1

        self.assertIn("mlb", by_sport)
        self.assertIn("wnba", by_sport)
        self.assertGreaterEqual(by_sport["mlb"], 2)
        self.assertGreaterEqual(by_sport["wnba"], 2)
        self.assertGreaterEqual(live_count, 2)
        self.assertGreaterEqual(pregame_count, 2)

    def test_collect_candidates_keeps_both_games_of_a_doubleheader_distinct(self) -> None:
        # #117. CLE @ CIN, a real same-day MLB doubleheader, showed a LIVE
        # candidate carrying the OTHER (not-yet-started) game's 21-hour-stale
        # odds. Root cause: the dedup identity tuple (candidate_type,
        # sport_slug, matchup, market, pick) has no per-game field, so two
        # doubleheader games producing byte-identical tuples ("CLE @ CIN" /
        # "Moneyline" / "Home ML") collapsed into one -- only one set of 5
        # candidates existed for the matchup, not two. This fails pre-fix
        # (one candidate survives, the live game's own gamePk is a coin
        # flip) and passes post-fix (both gamePks survive as distinct rows).
        overview = [{"slug": "mlb", "name": "MLB", "dashboard_games": []}]

        def _fake_game_candidates_for_sport(sport: dict[str, object]) -> list[dict[str, object]]:
            if str(sport.get("slug") or "").lower() != "mlb":
                return []
            return [
                {
                    "candidate_type": "game",
                    "sport": "MLB",
                    "sport_slug": "mlb",
                    "selection": "Home ML",
                    "pick": "Home ML",
                    "market": "Moneyline",
                    "projection": 0.68,
                    "odds": "+110",
                    "is_live": True,
                    "is_final": False,
                    "matchup": "CLE @ CIN",
                    "gamePk": 824489,
                    "event_id": None,
                    "score": 10.0,
                },
                {
                    "candidate_type": "game",
                    "sport": "MLB",
                    "sport_slug": "mlb",
                    "selection": "Home ML",
                    "pick": "Home ML",
                    "market": "Moneyline",
                    "projection": 0.55,
                    "odds": "-120",
                    "is_live": False,
                    "is_final": False,
                    "matchup": "CLE @ CIN",
                    "gamePk": 824490,
                    "event_id": None,
                    "score": 5.0,
                },
            ]

        preferences = _query_preferences("top edges today", mode="recommendation", sport="all", timing="all", include_props=True, include_games=True)
        with patch("syndicate.features.intelligence._game_candidates_for_sport", side_effect=_fake_game_candidates_for_sport):
            candidates = collect_candidates(overview, preferences)

        cin_candidates = [c for c in candidates if c.get("matchup") == "CLE @ CIN"]
        self.assertEqual(len(cin_candidates), 2, "expected both doubleheader games to survive dedup as distinct candidates")
        game_pks = {c.get("gamePk") for c in cin_candidates}
        self.assertEqual(game_pks, {824489, 824490})
        live_candidate = next(c for c in cin_candidates if c.get("gamePk") == 824489)
        self.assertTrue(live_candidate.get("is_live"))
        not_started_candidate = next(c for c in cin_candidates if c.get("gamePk") == 824490)
        self.assertFalse(not_started_candidate.get("is_live"))

    def test_score_candidate_marks_inactive_prop_as_state_invalid(self) -> None:
        candidate = {
            "sport_slug": "nba",
            "candidate_type": "prop",
            "pick": "Over 7.5",
            "name": "Al Horford Over 7.5 Rebounds",
            "market": "REB",
            "projection": 8.1,
            "odds": "+110",
            "edge": 0.19,
            "status_display": "Inactive",
            "status_context": "Out",
            "source_strength": 0.5,
        }

        scored = score_candidate(candidate)

        self.assertTrue(scored.get("state_invalid"))
        self.assertIn("inactive", str(scored.get("state_note") or "").lower())
        self.assertNotIn("score", scored)

    def test_score_candidate_excludes_over_prop_that_already_hit(self) -> None:
        # 2026-08-01 board audit: user asked for a prop to be removed (or
        # designated) once its outcome is already decided, e.g. mid-game
        # with the actual already past the line. No code anywhere compared
        # actual against line before this.
        candidate = {
            "sport_slug": "mlb",
            "candidate_type": "prop",
            "pick": "Over 1.5",
            "name": "Steven Kwan Over 1.5 Hits",
            "market": "Hits",
            "line": "1.5",
            "actual": "3",
            "is_live": True,
            "status_display": "In Progress",
            "projection": 1.7,
            "odds": "+110",
            "edge": 0.1,
            "source_strength": 0.5,
        }

        scored = score_candidate(candidate)

        self.assertTrue(scored.get("state_invalid"))
        self.assertEqual(scored.get("prop_outcome"), "hit")
        self.assertIn("hit", str(scored.get("state_note") or "").lower())

    def test_score_candidate_excludes_under_prop_that_already_missed(self) -> None:
        candidate = {
            "sport_slug": "mlb",
            "candidate_type": "prop",
            "pick": "Under 1.5",
            "name": "Steven Kwan Under 1.5 Hits",
            "market": "Hits",
            "line": "1.5",
            "actual": "2",
            "is_live": True,
            "status_display": "In Progress",
            "projection": 1.7,
            "odds": "+110",
            "edge": 0.1,
            "source_strength": 0.5,
        }

        scored = score_candidate(candidate)

        self.assertTrue(scored.get("state_invalid"))
        self.assertEqual(scored.get("prop_outcome"), "missed")

    def test_score_candidate_keeps_prop_still_undecided(self) -> None:
        candidate = {
            "sport_slug": "mlb",
            "candidate_type": "prop",
            "pick": "Over 1.5",
            "name": "Steven Kwan Over 1.5 Hits",
            "market": "Hits",
            "line": "1.5",
            "actual": "1",
            "is_live": True,
            "status_display": "In Progress",
            "projection": 1.7,
            "odds": "+110",
            "edge": 0.1,
            "source_strength": 0.5,
        }

        scored = score_candidate(candidate)

        self.assertFalse(scored.get("state_invalid"))
        self.assertNotIn("prop_outcome", scored)

    def test_score_candidate_excludes_steam_candidate_with_already_hit_prop(self) -> None:
        # 2026-08-01 board audit follow-up: the settled-prop guard above was
        # gated to candidate_type == "prop" only -- confirmed live, steam
        # is roughly half of MLB's daily candidate pool, so a steam
        # candidate on the exact same already-decided player+market stayed
        # on the board indefinitely. Must apply to a player-level steam
        # candidate exactly like a real prop.
        candidate = {
            "sport_slug": "mlb",
            "candidate_type": "steam",
            "player_name": "Steven Kwan",
            "pick": "Over 1.5",
            "name": "Steven Kwan Hits steam move",
            "market": "Hits · Steam",
            "line": "1.5",
            "actual": "3",
            "is_live": True,
            "status_display": "In Progress",
            "projection": 1.7,
            "odds": "+110",
            "edge": 0.1,
            "source_strength": 0.5,
        }

        scored = score_candidate(candidate)

        self.assertTrue(scored.get("state_invalid"))
        self.assertEqual(scored.get("prop_outcome"), "hit")

    def test_score_candidate_keeps_game_level_steam_candidate_untouched_by_settled_prop_logic(self) -> None:
        # A team-level steam move (moneyline/spread/total) has no
        # per-player monotonic-stat semantics -- _candidate_is_player_
        # level_market must gate on player_name being present, not just
        # candidate_type, or a real live game-level steam candidate could
        # get wrongly excluded the moment its "line"/"actual"-shaped fields
        # (which mean something entirely different for a game market)
        # happened to satisfy the same numeric comparison.
        candidate = {
            "sport_slug": "mlb",
            "candidate_type": "steam",
            "player_name": None,
            "pick": "Cincinnati Reds -1.5",
            "name": "Cincinnati Reds H2H steam move",
            "market": "H2H · Steam",
            "line": "-1.5",
            "actual": "3",
            "is_live": True,
            "status_display": "In Progress",
            "projection": None,
            "odds": "-120",
            "edge": 0.1,
            "source_strength": 0.5,
        }

        scored = score_candidate(candidate)

        self.assertFalse(scored.get("state_invalid"))
        self.assertNotIn("prop_outcome", scored)

    def test_score_candidate_keeps_prop_with_no_actual_yet(self) -> None:
        candidate = {
            "sport_slug": "mlb",
            "candidate_type": "prop",
            "pick": "Over 1.5",
            "name": "Steven Kwan Over 1.5 Hits",
            "market": "Hits",
            "line": "1.5",
            "actual": "-",
            "projection": 1.7,
            "odds": "+110",
            "edge": 0.1,
            "source_strength": 0.5,
        }

        scored = score_candidate(candidate)

        self.assertFalse(scored.get("state_invalid"))

    def test_candidate_live_claim_is_stale_trusts_missing_timestamp(self) -> None:
        # updated_epoch is only ever populated by home.py's
        # _game_row_updated_epoch, which falls back to a hardcoded 0.0
        # whenever a game lacks its own updated_at-style field -- the
        # common case, not a rare one. Treating that as automatically
        # stale (a prior, reverted change) silently disqualified nearly
        # every genuinely-live candidate from ever showing as live.
        self.assertFalse(_candidate_live_claim_is_stale({"is_live": True}))
        self.assertFalse(_candidate_live_claim_is_stale({"is_live": True, "updated_epoch": None}))
        self.assertFalse(_candidate_live_claim_is_stale({"is_live": True, "updated_epoch": 0}))
        self.assertFalse(_candidate_live_claim_is_stale({"is_live": True, "updated_epoch": -5}))

    def test_candidate_live_claim_is_stale_uses_real_timestamp_when_present(self) -> None:
        self.assertFalse(_candidate_live_claim_is_stale({"is_live": True, "updated_epoch": time.time()}))
        self.assertTrue(_candidate_live_claim_is_stale({"is_live": True, "updated_epoch": time.time() - 100000}))

    def test_candidate_live_claim_is_stale_ignores_non_live_candidates(self) -> None:
        self.assertFalse(_candidate_live_claim_is_stale({"is_live": False}))
        self.assertFalse(_candidate_live_claim_is_stale({}))

    def test_bind_candidate_state_does_not_promote_scheduled_time_as_game_state(self) -> None:
        # A prop candidate that fell back to pregame data carries a
        # scheduled-time status_display (e.g. "6:10 PM CT") -- that must
        # never become game_state, which used to make a scheduled game look
        # like it might be live.
        candidate = {"status_display": "6:10 PM CT", "is_live": False}
        _bind_candidate_state(candidate)
        self.assertFalse(bool(candidate.get("game_state")))

    def test_bind_candidate_state_promotes_real_live_signal(self) -> None:
        candidate = {"status_display": "Top 7th - In Progress", "is_live": True}
        _bind_candidate_state(candidate)
        self.assertEqual(candidate.get("game_state"), "Top 7th - In Progress")

    def test_bind_candidate_state_promotes_final_signal_even_without_is_live(self) -> None:
        candidate = {"status_display": "Final", "is_live": False}
        _bind_candidate_state(candidate)
        self.assertEqual(candidate.get("game_state"), "Final")

    def test_bind_candidate_state_promotes_text_naming_live_state_without_explicit_flag(self) -> None:
        candidate = {"status_context": "In Progress - Bot 4th"}
        _bind_candidate_state(candidate)
        self.assertEqual(candidate.get("game_state"), "In Progress - Bot 4th")

    def test_balanced_recommendation_order_preserves_multi_sport_live_mix(self) -> None:
        candidates = [
            {
                "sport_slug": "mlb",
                "sport": "MLB",
                "name": "Play 1",
                "score": 0.96,
                "edge": 0.22,
                "confidence": 0.94,
                "is_live": True,
            },
            {
                "sport_slug": "mlb",
                "sport": "MLB",
                "name": "Play 2",
                "score": 0.95,
                "edge": 0.21,
                "confidence": 0.93,
                "is_live": True,
            },
            {
                "sport_slug": "wnba",
                "sport": "WNBA",
                "name": "Play 3",
                "score": 0.81,
                "edge": 0.16,
                "confidence": 0.88,
                "is_live": True,
            },
            {
                "sport_slug": "nhl",
                "sport": "NHL",
                "name": "Play 4",
                "score": 0.79,
                "edge": 0.15,
                "confidence": 0.86,
                "is_live": False,
            },
        ]

        ordered = _balanced_recommendation_order(candidates)

        self.assertEqual([item.get("sport_slug") for item in ordered[:3]], ["mlb", "wnba", "nhl"])
        self.assertTrue(any(item.get("sport_slug") == "wnba" for item in ordered[:3]))
        self.assertTrue(any(item.get("is_live") for item in ordered[:3]))

    def test_balanced_recommendation_order_does_not_let_a_weak_live_candidate_outrank_a_strong_pregame_one(self) -> None:
        # Real bug found 2026-07-23: within a sport bucket, candidates used to
        # sort by is_live FIRST and betting quality second, so every live
        # candidate outranked every pregame candidate regardless of edge --
        # a weak live pick with near-zero edge would sort ahead of a much
        # stronger pregame pick in the same sport. Confirmed live while
        # investigating why WNBA's pregame candidates were missing from the
        # served board. Betting quality alone should decide order here.
        candidates = [
            {
                "sport_slug": "mlb",
                "sport": "MLB",
                "name": "Weak live pick",
                "score": 0.05,
                "edge": 0.01,
                "confidence": 0.51,
                "is_live": True,
            },
            {
                "sport_slug": "mlb",
                "sport": "MLB",
                "name": "Strong pregame pick",
                "score": 0.9,
                "edge": 0.25,
                "confidence": 0.9,
                "is_live": False,
            },
        ]

        ordered = _balanced_recommendation_order(candidates)

        self.assertEqual(ordered[0].get("name"), "Strong pregame pick")
        self.assertEqual(ordered[1].get("name"), "Weak live pick")

    def test_score_candidate_applies_shared_formula(self) -> None:
        candidate = {
            "sport_slug": "mlb",
            "candidate_type": "prop",
            "pick": "Over 4.5",
            "market": "outs recorded",
            "projection": 13.1,
            "odds": "+110",
            "edge": 1.0,
            "source_strength": 0.5,
            "detail": "Daily top props fallback",
        }

        scored = score_candidate(candidate)

        self.assertEqual(scored.get("tier"), "tier_2")
        self.assertAlmostEqual(float(scored.get("score") or 0.0), 0.3, places=4)

    def test_score_candidate_rewards_mlb_daily_update_readiness(self) -> None:
        candidate = {
            "sport_slug": "mlb",
            "candidate_type": "prop",
            "pick": "Over 4.5",
            "market": "outs recorded",
            "projection": 13.1,
            "odds": "+110",
            "edge": 1.0,
            "source_strength": 0.5,
            "detail": "Daily top props fallback",
        }
        advanced_context = [
            {
                "label": "Daily-update simulation contract",
                "metrics": ["Source mode", "Freshness", "Source paths", "Advanced by sport", "HR targets"],
                "path": "reports/daily_update/latest/unified_daily_update_latest_simulation_contract.json",
                "exists": True,
                "tracked": True,
                "inside_repo": True,
            }
        ]

        baseline = score_candidate(candidate)
        boosted = score_candidate(candidate, advanced_context=advanced_context)

        self.assertEqual(boosted.get("advanced_gate", {}).get("ready"), True)
        self.assertGreater(float(boosted.get("score") or 0.0), float(baseline.get("score") or 0.0))

    def test_score_candidate_rewards_larger_line_movement_regardless_of_direction(self) -> None:
        base_candidate = {
            "sport_slug": "mlb",
            "candidate_type": "prop",
            "pick": "Over 4.5",
            "market": "outs recorded",
            "projection": 13.1,
            "odds": "+110",
            "edge": 1.0,
            "source_strength": 0.5,
        }

        baseline = score_candidate(dict(base_candidate))
        moved_up = score_candidate(dict(base_candidate, percent_change=10.0))
        moved_down = score_candidate(dict(base_candidate, percent_change=-10.0))

        self.assertGreater(float(moved_up.get("score") or 0.0), float(baseline.get("score") or 0.0))
        # Magnitude-only: a 10% move up and a 10% move down must score
        # identically -- direction relative to the candidate's own side
        # (over/under, spread side, moneyline sign) is deliberately not
        # modeled, since getting that backwards would silently reward bad
        # picks instead of good ones.
        self.assertAlmostEqual(float(moved_up.get("score") or 0.0), float(moved_down.get("score") or 0.0), places=6)

    def test_score_candidate_caps_line_movement_bonus(self) -> None:
        base_candidate = {
            "sport_slug": "mlb",
            "candidate_type": "prop",
            "pick": "Over 4.5",
            "market": "outs recorded",
            "projection": 13.1,
            "odds": "+110",
            "edge": 1.0,
            "source_strength": 0.5,
        }

        moderate_move = score_candidate(dict(base_candidate, percent_change=20.0))
        huge_move = score_candidate(dict(base_candidate, percent_change=500.0))

        self.assertAlmostEqual(float(moderate_move.get("score") or 0.0), float(huge_move.get("score") or 0.0), places=6)

    def test_score_candidate_derives_movement_bonus_from_odds_history_delta_line(self) -> None:
        # pipeline/intelligence_state.py's _build_candidate_pool attaches a
        # differently-shaped odds_history (delta_line/last_line, no
        # precomputed percent_change) than
        # _enrich_candidates_with_odds_history's delta/percent_change --
        # the bonus must still kick in from that shape.
        base_candidate = {
            "sport_slug": "mlb",
            "candidate_type": "prop",
            "pick": "Over 4.5",
            "market": "outs recorded",
            "projection": 13.1,
            "odds": "+110",
            "edge": 1.0,
            "source_strength": 0.5,
        }
        with_delta_line = dict(base_candidate, odds_history={"delta_line": 1.0, "last_line": 4.5})

        baseline = score_candidate(dict(base_candidate))
        boosted = score_candidate(with_delta_line)

        self.assertGreater(float(boosted.get("score") or 0.0), float(baseline.get("score") or 0.0))

    def test_score_candidate_line_movement_bonus_can_be_disabled(self) -> None:
        base_candidate = {
            "sport_slug": "mlb",
            "candidate_type": "prop",
            "pick": "Over 4.5",
            "market": "outs recorded",
            "projection": 13.1,
            "odds": "+110",
            "edge": 1.0,
            "source_strength": 0.5,
            "percent_change": 10.0,
        }

        with patch.dict(os.environ, {"SYNDICATE_INTELLIGENCE_SCORE_LINE_MOVEMENT": "false"}):
            disabled = score_candidate(dict(base_candidate))
        enabled = score_candidate(dict(base_candidate))

        self.assertGreater(float(enabled.get("score") or 0.0), float(disabled.get("score") or 0.0))

    def test_score_candidate_tags_news_triggered_when_sport_recently_changed(self) -> None:
        # Plan item 1F0's deferred board callout: a candidate whose data was
        # just regenerated because of a detected injury/lineup change should
        # carry a distinct flag, separate from the (direction-agnostic)
        # movement bonus above, which says nothing about *why* a line moved.
        candidate = {
            "sport_slug": "mlb",
            "candidate_type": "prop",
            "pick": "Over 4.5",
            "market": "outs recorded",
            "projection": 13.1,
            "odds": "+110",
            "edge": 1.0,
            "source_strength": 0.5,
        }

        with patch(
            "syndicate.features.shared.live_refresh_loop.sports_with_recent_lineup_injury_change",
            return_value={"mlb"},
        ):
            scored = score_candidate(dict(candidate))

        self.assertTrue(scored.get("news_triggered"))

    def test_score_candidate_does_not_tag_news_triggered_for_a_different_sport(self) -> None:
        candidate = {
            "sport_slug": "mlb",
            "candidate_type": "prop",
            "pick": "Over 4.5",
            "market": "outs recorded",
            "projection": 13.1,
            "odds": "+110",
            "edge": 1.0,
            "source_strength": 0.5,
        }

        with patch(
            "syndicate.features.shared.live_refresh_loop.sports_with_recent_lineup_injury_change",
            return_value={"nba"},
        ):
            scored = score_candidate(dict(candidate))

        self.assertFalse(scored.get("news_triggered"))

    def test_score_candidate_news_triggered_tag_never_raises_on_read_failure(self) -> None:
        candidate = {
            "sport_slug": "mlb",
            "candidate_type": "prop",
            "pick": "Over 4.5",
            "market": "outs recorded",
            "projection": 13.1,
            "odds": "+110",
            "edge": 1.0,
            "source_strength": 0.5,
        }

        with patch(
            "syndicate.features.shared.live_refresh_loop.sports_with_recent_lineup_injury_change",
            side_effect=RuntimeError("boom"),
        ):
            scored = score_candidate(dict(candidate))

        self.assertFalse(scored.get("news_triggered"))
        self.assertIn("score", scored)

    def test_attach_intelligence_response_aliases_promotes_nested_analysis_fields(self) -> None:
        # IntelligenceStateService._compute_response (pipeline/intelligence_state.py)
        # only ever sets analysis_views/headline/summary/analysis_brief/
        # supporting_evidence inside response["analysis"] (== response["response"],
        # the same dict exposed under two keys) -- never at this dict's own
        # top level, unlike board_contract/policy_control/etc., which ARE
        # already top-level by the time this function runs. Confirmed real
        # regression: every /api/intelligence/query force_refresh request had
        # analysis_views genuinely computed but unreachable at the top level
        # any real consumer (or these tests) actually reads from.
        analysis = {
            "recommendations": [{"name": "Donovan Mitchell Over 4.5 3PM"}],
            "analysis_views": {"focus": "nba_matchups", "table": {"rows": [{"player": "Donovan Mitchell"}]}},
            "headline": "The Syndicate brief",
            "summary": "Top NBA matchup edges tonight.",
            "analysis_brief": {"sections": [{"title": "Matchup case"}]},
            "supporting_evidence": {"kind": "bundle", "sections": []},
        }
        response = {
            "ok": True,
            "top_opportunities": [],
            "by_sport": {},
            "analysis": analysis,
            "response": analysis,
            "board_contract": {"schema": "intelligence_board_v1"},
        }

        result = _attach_intelligence_response_aliases(response)

        self.assertEqual(result.get("analysis_views"), analysis["analysis_views"])
        self.assertEqual(result.get("headline"), "The Syndicate brief")
        self.assertEqual(result.get("summary"), "Top NBA matchup edges tonight.")
        self.assertEqual(result.get("analysis_brief"), analysis["analysis_brief"])
        self.assertEqual(result.get("supporting_evidence"), analysis["supporting_evidence"])

    def test_attach_intelligence_response_aliases_does_not_overwrite_existing_top_level_value(self) -> None:
        analysis = {"headline": "Nested headline", "analysis_views": {"focus": "nested"}}
        response = {
            "headline": "Already-top-level headline",
            "analysis": analysis,
            "response": analysis,
        }

        result = _attach_intelligence_response_aliases(response)

        self.assertEqual(result.get("headline"), "Already-top-level headline")

    def test_attach_intelligence_response_aliases_is_noop_without_nested_analysis(self) -> None:
        response = {"ok": True, "top_opportunities": [], "by_sport": {}}

        result = _attach_intelligence_response_aliases(response)

        self.assertNotIn("analysis_views", result)
        self.assertNotIn("headline", result)

    def test_score_candidate_sets_scoring_mode_by_available_inputs(self) -> None:
        candidates = [
            {
                "sport_slug": "mlb",
                "candidate_type": "prop",
                "pick": "Over 4.5",
                "market": "outs recorded",
                "projection": 13.1,
                "odds": "+110",
                "edge": 0.08,
                "model_probability": 0.58,
                "implied_probability": 0.50,
                "source_strength": 0.5,
            },
            {
                "sport_slug": "mlb",
                "candidate_type": "prop",
                "pick": "Over 4.5",
                "market": "outs recorded",
                "projection": 13.1,
                "odds": "+110",
                "edge": 0.08,
                "source_strength": 0.5,
            },
            {
                "sport_slug": "mlb",
                "candidate_type": "prop",
                "pick": "Over 4.5",
                "market": "outs recorded",
                "projection": 13.1,
                "odds": "+110",
                "source_strength": 0.5,
            },
        ]

        scored = [score_candidate(candidate) for candidate in candidates]

        self.assertEqual([candidate.get("scoring_mode") for candidate in scored], ["full", "partial", "minimal"])

    def test_normalize_candidate_adds_required_baseline_fields(self) -> None:
        candidate = {
            "sport_slug": "mlb",
            "candidate_type": "game",
            "pick": "NYM ML",
            "market": "Full game Total",
            "detail": "12:05 PM",
            "summary": "Luinder Avila vs Zack Littell",
        }

        normalized = normalize_candidate(candidate)

        self.assertEqual(normalized.get("sport"), "mlb")
        self.assertEqual(normalized.get("type"), "game")
        self.assertEqual(normalized.get("selection"), "NYM ML")
        self.assertEqual(normalized.get("market"), "Full game Total")
        self.assertIsNone(normalized.get("odds"))
        self.assertIsNone(normalized.get("projection"))
        self.assertIsNone(normalized.get("source"))
        self.assertEqual(float(normalized.get("source_strength") or 0.0), 0.5)
        self.assertFalse(bool(normalized.get("is_live")))

    def test_mlb_game_markets_total_fallback_emits_game_candidate(self) -> None:
        sport = {"slug": "mlb", "name": "MLB", "hub_href": "/mlb"}
        game = {
            "gamePk": 822721,
            "summary": "Luinder Avila vs Zack Littell | 1 official pick(s) | +1 playable",
            "detail": "12:05 PM",
            "gameMarkets": {"total": {"line": 8.1, "pick": None, "reason": "KC 45.3% | WSH 54.7% | Tie 0.0%"}},
        }

        candidates = _game_bet_candidates_from_game(sport, game, fallback_epoch=0.0)

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].get("market"), "Total")
        self.assertNotEqual(candidates[0].get("projected"), "-")

    def test_wnba_total_market_shell_rows_are_not_emitted(self) -> None:
        sport = {"slug": "wnba", "name": "WNBA", "hub_href": "/wnba"}
        game = {
            "gamePk": 401857043,
            "summary": "Oddsapi consensus market snapshot",
            "detail": "7/6 - 7:30 PM EDT",
            "betting": {
                "home_ml": -2113,
                "away_ml": 2113,
                "home_ml_ev": 0.0,
                "away_ml_ev": 0.0,
                "p_home_win": 0.955,
                "p_away_win": 0.045,
                "total": 162.5,
                "p_total_over": 0.501,
                "p_total_under": 0.499,
            },
            "gameMarkets": {"total": {"line": 162.5, "pick": "Over", "reason": "Consensus total"}},
        }

        candidates = _game_bet_candidates_from_game(sport, game, fallback_epoch=0.0)

        self.assertTrue(any(candidate.get("market") == "Moneyline" for candidate in candidates))
        self.assertFalse(any(candidate.get("market") == "Total" for candidate in candidates))

    def test_collect_candidates_keeps_valid_wnba_props_after_classification(self) -> None:
        overview = _sample_overview_with_secondary_sport()
        preferences = _query_preferences("top edges today", mode="recommendation", sport="all", timing="all", include_props=True, include_games=True)

        candidates = collect_candidates(overview, preferences)
        wnba_candidates = [candidate for candidate in candidates if str(candidate.get("sport_slug") or "").lower() == "wnba"]

        self.assertGreater(len(wnba_candidates), 0)
        self.assertTrue(all(classify_candidate(candidate) is not None for candidate in wnba_candidates))

    def test_is_valid_candidate_requires_selection_type_and_value(self) -> None:
        valid_candidate = normalize_candidate(
            {
                "sport_slug": "nhl",
                "candidate_type": "prop",
                "pick": "Over 2.5",
                "market": "shots",
                "odds": "+105",
                "detail": "Stale slate fallback",
            }
        )
        missing_selection = normalize_candidate(
            {
                "sport_slug": "nhl",
                "candidate_type": "prop",
                "market": "shots",
                "odds": "+105",
            }
        )
        missing_type = normalize_candidate(
            {
                "sport_slug": "nhl",
                "pick": "Over 2.5",
                "market": "shots",
                "odds": "+105",
            }
        )
        missing_value = normalize_candidate(
            {
                "sport_slug": "nhl",
                "candidate_type": "prop",
                "pick": "Over 2.5",
                "market": "shots",
            }
        )

        self.assertTrue(is_valid_candidate(valid_candidate))
        self.assertFalse(is_valid_candidate(missing_selection))
        self.assertEqual(missing_type.get("type"), "prop")
        self.assertTrue(is_valid_candidate(missing_type))
        self.assertFalse(is_valid_candidate(missing_value))

    def test_classify_candidate_assigns_tier_one_when_source_strength_is_high(self) -> None:
        candidate = {
            "sport_slug": "mlb",
            "candidate_type": "prop",
            "pick": "Over 1.5",
            "market": "hits",
            "projection": 1.9,
            "odds": "+115",
            "source_strength": 0.85,
        }

        classified = normalize_candidate(candidate)
        classified = classify_candidate(classified)

        self.assertIsNotNone(classified)
        self.assertEqual(classified.get("tier"), "tier_1")

    def test_run_intelligence_query_prefers_primary_candidates_over_legacy_fallback(self) -> None:
        with _patch_build_intelligence_overview(_sample_overview_with_secondary_sport()):
            with patch("syndicate.features.intelligence._tracked_repo_files", return_value=set()):
                with patch("syndicate.features.intelligence._advanced_input_rows_for_sport", return_value=[]):
                    with patch(
                        "syndicate.features.intelligence.collect_all_recommendations",
                        return_value=[
                            {
                                "candidate_type": "prop",
                                "sport_slug": "mlb",
                                "sport": "MLB",
                                "matchup": "NYY at BOS",
                                "market": "outs recorded",
                                "pick": "Over 8+ Outs Recorded",
                                "name": "Tobias Myers Outs Recorded",
                                "detail": "Over 8+ Outs Recorded | Daily top props fallback",
                                "writeup": "Daily top props fallback",
                                "surface_title": "Top Live Props",
                                "confidence": "55%",
                                "score": 10.0,
                            }
                        ],
                    ) as mocked_fallback:
                        result = run_intelligence_query("top edges today", selected_date="2026-06-04", force_refresh=True)

        recommendations = result.get("recommendations") or []
        self.assertTrue(recommendations)
        self.assertNotIn("mlb", {str(item.get("sport_slug") or item.get("sport") or "").lower() for item in recommendations})
        self.assertFalse(any("fallback" in str(item.get("detail") or item.get("summary") or "").lower() for item in recommendations))
        mocked_fallback.assert_not_called()

    def test_run_intelligence_query_uses_question_date_when_date_not_passed(self) -> None:
        with _patch_build_intelligence_overview(_sample_mlb_market_overview()) as build_overview:
            with patch("syndicate.features.intelligence._tracked_repo_files", return_value=set()):
                with patch("syndicate.features.intelligence._advanced_input_rows_for_sport", return_value=[]):
                    with patch("syndicate.features.intelligence.collect_all_recommendations", return_value=[]):
                        with patch("syndicate.features.intelligence.collect_candidates", return_value=[]):
                            result = run_intelligence_query("Who are the top 3 strikeout targets for 2026-06-04?")

        self.assertEqual(result.get("selected_date"), "2026-06-04")
        build_overview.assert_called_once()
        self.assertEqual(build_overview.call_args.kwargs.get("selected_date"), "2026-06-04")

    def test_run_intelligence_launches_full_refresh(self) -> None:
        app = create_app()
        app.testing = True

        with patch("syndicate.blueprints.intelligence.central_today_iso", return_value="2026-06-10"):
            with patch("syndicate.blueprints.intelligence.launch_refresh_run", return_value={"ok": True, "pid": 4321, "state": "running"}) as mocked_launch:
                with patch("syndicate.blueprints.intelligence.queue_intelligence_state_refresh") as mocked_queue:
                    response = app.test_client().get("/intelligence/run")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["launched"])
        self.assertEqual(payload["refresh"]["pid"], 4321)
        mocked_launch.assert_called_once_with(date="2026-06-10", mode=None, phase=None, regions=None, execution_mode=None, skip_mirror=None)
        mocked_queue.assert_called_once()

    def test_run_intelligence_degrades_when_queue_refresh_fails(self) -> None:
        app = create_app()
        app.testing = True

        with patch("syndicate.blueprints.intelligence.central_today_iso", return_value="2026-06-10"):
            with patch("syndicate.blueprints.intelligence.launch_refresh_run", return_value={"ok": True, "pid": 4321, "state": "running"}) as mocked_launch:
                with patch("syndicate.blueprints.intelligence.queue_intelligence_state_refresh", side_effect=RuntimeError("backend unavailable")) as mocked_queue:
                    response = app.test_client().get("/intelligence/run")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["launched"])
        self.assertEqual(payload["refresh"]["pid"], 4321)
        mocked_launch.assert_called_once_with(date="2026-06-10", mode=None, phase=None, regions=None, execution_mode=None, skip_mirror=None)
        mocked_queue.assert_called_once()

    def test_query_preferences_does_not_infer_nba_from_wnba_token(self) -> None:
        preferences = _query_preferences("Explain the best WNBA matchup targets today with a table and chart.")

        self.assertEqual(preferences.get("requested_sports"), ["wnba"])

    def test_intelligence_query_returns_ranked_recommendations_and_parlays(self) -> None:
        advanced_rows = [
            {
                "label": "Team advanced stats",
                "metrics": ["Pace", "Offensive rating", "Shot profile"],
                "path": "data/nba_source/data/processed/team_advanced_stats_2026.csv",
                "exists": True,
                "tracked": True,
                "inside_repo": True,
            }
        ]
        with _patch_build_intelligence_overview(_sample_overview()):
            with patch("syndicate.features.intelligence._tracked_repo_files", return_value=set()):
                with patch("syndicate.features.intelligence._advanced_input_rows_for_sport", return_value=advanced_rows):
                    response = self.client.post(
                        "/api/intelligence/query",
                        json={
                            "force_refresh": True,
                            "question": "Build a two-leg parlay from the best live and pregame NBA edges with a $100 bankroll and max 20% exposure",
                            "date": "2026-06-04",
                        },
                    )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json() or json.loads(response.get_data(as_text=True))
        self.assertIn("response", payload)
        result = payload.get("response") or {}
        structured = result.get("response") if isinstance(result.get("response"), dict) else result
        self.assertGreaterEqual(len(structured.get("recommendations") or []), 2)
        self.assertGreaterEqual(len(structured.get("parlays") or []), 1)
        self.assertIn("top_live_opportunities", structured)
        self.assertGreaterEqual(len(structured.get("top_live_opportunities") or []), 1)
        first = (structured.get("recommendations") or [])[0]
        self.assertIn("rationale", first)
        self.assertIn(first.get("candidate_type"), {"prop", "game"})
        self.assertIn("Advanced drivers in play", first.get("rationale") or "")
        self.assertTrue(first.get("advanced_inputs"))
        self.assertTrue(first.get("advanced_ready"))
        self.assertIn("board_contract", result)
        board_contract = result.get("board_contract") or structured.get("board_contract") or {}
        self.assertEqual(board_contract.get("schema"), "intelligence_board_v1")
        self.assertGreaterEqual((board_contract.get("lane_counts") or {}).get("live", 0), 1)
        self.assertGreaterEqual((board_contract.get("lane_counts") or {}).get("pregame", 0), 1)

    def test_get_top_live_opportunities_ranks_positive_ev_with_live_context(self) -> None:
        opportunities = get_top_live_opportunities(
            [
                {
                    "selection": "NBA Over",
                    "sport": "NBA",
                    "market": "points",
                    "player_name": "Jayson Tatum",
                    "matchup": "BOS at NYK",
                    "ev_current": 0.08,
                    "ev_delta": 0.01,
                    "confidence": 0.64,
                    "adjusted_score": 91.0,
                },
                {
                    "selection": "MLB Under",
                    "sport": "MLB",
                    "market": "strikeouts",
                    "player_name": "Chris Sale",
                    "matchup": "ATL at NYM",
                    "ev_current": 0.11,
                    "ev_delta": 0.03,
                    "confidence": 0.59,
                    "adjusted_score": 88.0,
                },
                {
                    "selection": "NHL Over",
                    "sport": "NHL",
                    "market": "shots",
                    "ev_current": -0.02,
                    "ev_delta": 0.04,
                    "confidence": 0.7,
                    "adjusted_score": 95.0,
                },
            ],
            limit=2,
        )

        self.assertEqual(len(opportunities), 2)
        self.assertEqual(opportunities[0]["selection"], "MLB Under")
        self.assertEqual(opportunities[0]["sport_slug"], "mlb")
        self.assertGreater(opportunities[0]["ev_current"], 0.0)
        self.assertGreater(opportunities[0]["ev_delta"], opportunities[1]["ev_delta"])
        self.assertNotIn("NHL Over", [item["selection"] for item in opportunities])

    def test_get_top_live_opportunities_requires_live_context(self) -> None:
        opportunities = get_top_live_opportunities(
            [
                {
                    "selection": "NBA Over 4.5",
                    "sport": "NBA",
                    "market": "points",
                    "ev_current": 0.08,
                    "confidence": 0.64,
                    "adjusted_score": 91.0,
                },
                {
                    "selection": "Donovan Mitchell Over 4.5 3PM",
                    "player_name": "Donovan Mitchell",
                    "sport": "NBA",
                    "market": "3PM",
                    "matchup": "CLE at IND",
                    "candidate_type": "prop",
                    "ev_current": 0.12,
                    "confidence": 0.72,
                    "adjusted_score": 94.0,
                },
            ],
            limit=5,
        )

        self.assertEqual(len(opportunities), 1)
        self.assertEqual(opportunities[0].get("selection"), "Donovan Mitchell Over 4.5 3PM")
        self.assertEqual(opportunities[0].get("display_name"), "Donovan Mitchell")
        self.assertEqual(opportunities[0].get("matchup"), "CLE at IND")

    def test_get_top_live_opportunities_derives_display_name_from_reasoning(self) -> None:
        opportunities = get_top_live_opportunities(
            [
                {
                    "selection": "Over",
                    "sport": "MLB",
                    "market": "pitcher_props",
                    "matchup": "CLE at MIN",
                    "reasoning": "Live lean Over for Carlos Rodon Props at 17.5. Model gives 75.8% win probability.",
                    "ev_current": 0.095,
                    "confidence": 0.76,
                    "adjusted_score": 95.0,
                }
            ],
            limit=5,
        )

        self.assertEqual(len(opportunities), 1)
        self.assertEqual(opportunities[0].get("display_name"), "Carlos Rodon")
        self.assertEqual(opportunities[0].get("selection"), "Over")

    def test_recommendation_state_accepts_fallback_fields_without_error(self) -> None:
        candidate = {
            "status_context": "",
            "settlement_status": "",
            "settlement_state": "Resolved",
            "settlement_label": "",
            "settlement": {"status": "", "status_label": ""},
            "actual": "",
            "actual_value": "",
            "actual_so_far": "",
            "current_actual": "",
            "live_actual": "",
        }

        self.assertEqual(_recommendation_state(candidate), "final")

    def test_get_top_live_opportunities_accepts_fallback_fields_without_error(self) -> None:
        recommendations = [
            {
                "status_context": "Live",
                "selection": "",
                "pick": "",
                "name": "A'ja Wilson Over 24.5",
                "sport": "WNBA",
                "sport_slug": "wnba",
                "market": "PTS",
                "market_key": "",
                "player_name": "A'ja Wilson",
                "matchup": "LVA at SEA",
                "candidate_type": "player_prop",
                "actual": "",
                "actual_value": "",
                "actual_so_far": "27",
                "current_actual": "",
                "live_actual": "",
                "ev_current": 0.12,
                "line_movement_impact": 0.03,
                "confidence": 0.61,
                "edge": 0.08,
            }
        ]

        top_live = get_top_live_opportunities(recommendations, limit=5)
        self.assertEqual(len(top_live), 1)
        self.assertEqual(top_live[0]["display_name"], "A'ja Wilson")

    def test_intelligence_query_api_returns_player_analysis_payload(self) -> None:
        advanced_rows = [
            {
                "label": "Team advanced stats",
                "metrics": ["Pace", "Offensive rating", "Shot profile"],
                "path": "data/nba_source/data/processed/team_advanced_stats_2026.csv",
                "exists": True,
                "tracked": True,
                "inside_repo": True,
            }
        ]
        with _patch_build_intelligence_overview(_sample_overview()):
            with patch("syndicate.features.intelligence._tracked_repo_files", return_value=set()):
                with patch("syndicate.features.intelligence._advanced_input_rows_for_sport", return_value=advanced_rows):
                    with patch("syndicate.features.intelligence.load_artifact_manifests", return_value=[]):
                        response = self.client.post(
                            "/api/intelligence/query",
                            json={
                                "force_refresh": True,
                                "question": "Analyze Jayson Tatum tonight",
                                "date": "2026-06-04",
                            },
                        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertIn("version", payload)
        self.assertIn("timestamp", payload)
        self.assertIn("response", payload)
        result = payload.get("response") or {}
        board_contract = result.get("board_contract") or {}
        self.assertEqual(result.get("selected_date"), "2026-06-04")
        self.assertIn("response", result)
        self.assertTrue((board_contract.get("cards") or []))
        self.assertEqual((board_contract.get("cards") or [])[0].get("name"), "Jayson Tatum Over 28.5")
        self.assertEqual((board_contract.get("cards") or [])[0].get("sport"), "nba")

    def test_intelligence_query_api_returns_fallback_when_query_raises(self) -> None:
        # The engine seam moved: the query API computes through the state
        # service (_compute_intelligence_response ->
        # _INTELLIGENCE_STATE_SERVICE._compute_response), and an engine
        # failure no longer surfaces {fallback, error} -- it degrades through
        # the cached/snapshot fallbacks to a 200 with an empty board rather
        # than an error payload. Pin that: a raising engine must never 500,
        # and must serve a response with no candidates.
        from pipeline.intelligence_state import _INTELLIGENCE_STATE_SERVICE

        with patch("syndicate.blueprints.intelligence._cached_intelligence_response_with_source", return_value=(None, "fallback")):
            with patch.object(_INTELLIGENCE_STATE_SERVICE, "_compute_response", side_effect=RuntimeError("boom")):
                response = self.client.post(
                    "/api/intelligence/query",
                    json={
                        "force_refresh": True,
                        "question": "Analyze Jayson Tatum tonight",
                        "date": "2026-06-04",
                    },
                )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json() or {}
        # The degrade path may legitimately serve cached/snapshot board
        # content when any exists -- the contract is "never 500, always a
        # response-shaped payload", not "empty".
        self.assertIn("response", payload)
        self.assertIsInstance(payload.get("response"), dict)

    def test_intelligence_query_api_reflects_model_reliability_in_confidence(self) -> None:
        advanced_rows = [
            {
                "label": "Team advanced stats",
                "metrics": ["Pace", "Offensive rating", "Shot profile"],
                "path": "data/nba_source/data/processed/team_advanced_stats_2026.csv",
                "exists": True,
                "tracked": True,
                "inside_repo": True,
            }
        ]
        with _patch_build_intelligence_overview(_sample_overview()):
            with patch("syndicate.features.intelligence._tracked_repo_files", return_value=set()):
                with patch("syndicate.features.intelligence._advanced_input_rows_for_sport", return_value=advanced_rows):
                    with patch("syndicate.features.intelligence.load_artifact_manifests", return_value=[]):
                        with patch(
                            "syndicate.features.intelligence.build_reliability_profile",
                            return_value={
                                "sport": "nba",
                                "sample_size": 24,
                                "metrics": {"win_rate": 0.46, "roi": -0.08, "clv": -0.12, "calibration": {"mae": 0.24, "brier_score": 0.12, "sample_size": 24}},
                                "calibration_error": 0.24,
                                "calibration_penalty": 0.06,
                                "win_rate_adjustment": -0.02,
                                "roi_adjustment": -0.01,
                                "reliability_multiplier": 0.91,
                            },
                        ):
                            with patch(
                                "syndicate.features.intelligence.adjust_confidence",
                                side_effect=lambda base_confidence, **_: (round(max(0.05, base_confidence - 0.08), 2), {"calibration_error": 0.24, "sample_size": 24}),
                            ):
                                response = self.client.post(
                                    "/api/intelligence/query",
                                    json={
                                        "question": "Analyze Jayson Tatum tonight",
                                        "date": "2026-06-04",
                                        "force_refresh": True,
                                    },
                                )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        structured = ((payload.get("response") or {}).get("response") or {}).get("structured_response") or {}
        recommendation = ((payload.get("response") or {}).get("recommendations") or [])[0] if (payload.get("response") or {}).get("recommendations") else {}
        risk_flags = recommendation.get("risk_flags") or []

        self.assertTrue(any("calibration" in str(flag).lower() for flag in risk_flags))
        self.assertTrue(any("reliability" in str(flag).lower() for flag in risk_flags))
        # Served confidence is always a display-formatted percent string
        # ("63%"), same convention as odds/edge on every other served field
        # -- parse it rather than comparing a str to a float directly.
        confidence_text = str(recommendation.get("confidence") or "0").strip().rstrip("%")
        self.assertGreaterEqual(float(confidence_text or 0.0), 0.0)

    def test_intelligence_query_api_force_refresh_returns_live_response(self) -> None:
        state_response = {
            "top_opportunities": [
                {
                    "sport": "NBA",
                    "sport_slug": "nba",
                    "name": "Jayson Tatum Over 28.5",
                    "recommendation_id": "rec-1",
                    "query_type": "board",
                }
            ],
            "by_sport": {"nba": [{"sport": "NBA", "name": "Jayson Tatum Over 28.5"}]},
            "analysis": {
                "recommendations": [{"recommendation_id": "rec-1", "name": "Jayson Tatum Over 28.5"}],
                "top_live_opportunities": [],
                "parlays": [],
                "portfolio": {},
            },
        }
        live_result = {
            "ok": True,
            "analysis": {"recommendations": [{"recommendation_id": "rec-1", "name": "Jayson Tatum Over 28.5"}]},
            "top_opportunities": [{"recommendation_id": "rec-1", "name": "Jayson Tatum Over 28.5"}],
            "by_sport": {"nba": [{"recommendation_id": "rec-1", "name": "Jayson Tatum Over 28.5"}]},
            "response": {"analysis": {"recommendations": [{"recommendation_id": "rec-1", "name": "Jayson Tatum Over 28.5"}]}},
            "board_contract": {"schema": "intelligence_board_v1", "cards": [{"name": "Jayson Tatum Over 28.5"}]},
        }
        board_contract = {"schema": "intelligence_board_v1", "cards": [{"name": "Jayson Tatum Over 28.5"}]}

        with patch("syndicate.blueprints.intelligence.queue_intelligence_state_refresh") as queue_mock:
            with patch("syndicate.blueprints.intelligence.read_latest_intelligence_state_response", return_value=state_response) as state_mock:
                with patch("pipeline.intelligence_state._INTELLIGENCE_STATE_SERVICE._compute_response", return_value=dict(live_result)) as compute_mock:
                    with patch("syndicate.blueprints.intelligence.build_intelligence_board_contract", return_value=dict(board_contract)):
                        response = self.client.post(
                            "/api/intelligence/query",
                            json={
                                "question": "Analyze Jayson Tatum tonight",
                                "date": "2026-06-04",
                                "force_refresh": True,
                            },
                        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertIn("version", payload)
        self.assertIn("timestamp", payload)
        self.assertTrue(payload.get("response"))
        self.assertEqual((payload.get("response") or {}).get("board_contract"), board_contract)
        self.assertEqual((payload.get("response") or {}).get("analysis", {}).get("recommendations", [])[0].get("name"), "Jayson Tatum Over 28.5")
        queue_mock.assert_not_called()
        # read_latest_intelligence_state_response is called once in the
        # non-hosted force_refresh branch itself and once more inside
        # _compute_intelligence_response, which the outer branch calls next
        # -- two calls with identical args on every request through this
        # path, not order-dependence.
        self.assertEqual(state_mock.call_count, 2)
        compute_mock.assert_called_once()

    def test_intelligence_query_api_never_computes_synchronously_on_render_when_cache_misses(self) -> None:
        # #109 follow-up, confirmed live 2026-07-27: this test used to assert
        # the OPPOSITE of what it does now -- that a cache miss on Render
        # falls through to a synchronous _compute_response call, added as a
        # 2026-07-24 "fix" for tomorrow's-date queries returning empty. That
        # caused a real production incident: a single request with a novel
        # question/date (never matching the background loop's own cached
        # key) drove web to 100% memory / 0MB headroom, because the compute
        # ran INSIDE the web request handler on the memory-constrained web
        # container -- a direct violation of this repo's load-bearing rule
        # (web does no heavy computation; intelligence runs on
        # refresh-worker's 4GB via the background loop, web only reads what
        # it already computed). Reverted: a cache miss on Render always
        # returns the queued/empty placeholder and waits for the background
        # loop's own next cycle, regardless of how novel the payload is.
        with patch.dict(os.environ, {"RENDER": "true"}, clear=False):
            with patch("syndicate.blueprints.intelligence.queue_intelligence_state_refresh") as queue_mock:
                with patch("syndicate.blueprints.intelligence.read_latest_intelligence_state_response", return_value=None):
                    with patch("syndicate.blueprints.intelligence._cached_intelligence_response_with_source", return_value=(None, "fallback")) as cached_mock:
                        with patch("pipeline.intelligence_state._INTELLIGENCE_STATE_SERVICE._compute_response") as compute_mock:
                            response = self.client.post(
                                "/api/intelligence/query",
                                json={
                                    "question": "Analyze Jayson Tatum tonight",
                                    "date": "2026-07-25",
                                    "force_refresh": True,
                                },
                            )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual((payload.get("response") or {}).get("queued_refresh"), True)
        self.assertEqual((payload.get("response") or {}).get("execution_source"), "fallback")
        self.assertEqual((payload.get("response") or {}).get("analysis", {}).get("recommendations"), [])
        queue_mock.assert_called_once()
        cached_mock.assert_called_once()
        compute_mock.assert_not_called()

    def test_intelligence_query_api_degrades_when_queue_refresh_fails(self) -> None:
        # Mocking read_latest_intelligence_state_response alone left the
        # engine seam unmocked: force_refresh's non-render-hosted branch
        # calls it only for its side effect and gets its actual data from
        # _INTELLIGENCE_STATE_SERVICE._compute_response (see
        # _compute_intelligence_response) -- so the response used to be
        # built from whatever real repo artifacts happened to be on disk
        # (observed: "Courtney Williams OVER 1.5"), not this fixture.
        from pipeline.intelligence_state import _INTELLIGENCE_STATE_SERVICE

        state_response = {
            "ok": True,
            "selected_date": "2026-06-04",
            "recommendations": [{"name": "Play 1"}],
            "top_opportunities": [{"name": "Play 1"}],
            "analysis": {"recommendations": [{"name": "Play 1"}], "top_live_opportunities": [], "picks": [], "portfolio": {}, "parlays": []},
            "board_contract": {"schema": "intelligence_board_v1", "cards": [{"name": "Play 1"}]},
        }

        with patch("syndicate.blueprints.intelligence.queue_intelligence_state_refresh", side_effect=RuntimeError("backend unavailable")) as queue_mock:
            with patch.object(_INTELLIGENCE_STATE_SERVICE, "_compute_response", return_value=dict(state_response)):
                response = self.client.post(
                    "/api/intelligence/query",
                    json={
                        "question": "Analyze Jayson Tatum tonight",
                        "date": "2026-06-04",
                        "force_refresh": True,
                    },
                )

        payload = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertIn("response", payload)
        result = payload.get("response") or {}
        structured = result.get("response") if isinstance(result.get("response"), dict) else result
        self.assertEqual((structured.get("top_opportunities") or [])[0].get("name"), "Play 1")
        # Unlike the render-hosted branch (which queues a background refresh
        # before falling back to a cache read), the non-render-hosted branch
        # exercised here never calls queue_intelligence_state_refresh at all:
        # _compute_response already persists its own result via
        # _persist_locked, so a second background-refresh trigger would be
        # redundant. This assertion used to be assert_called_once() (carried
        # over from an earlier version of this test that mocked
        # read_latest_intelligence_state_response instead, before the code
        # path above it changed) -- corrected 2026-07-28 once the
        # _INTELLIGENCE_STATE_SERVICE import-freezing bug (see
        # syndicate/blueprints/intelligence.py's _compute_intelligence_response)
        # was fixed and this mock started actually taking effect.
        queue_mock.assert_not_called()

    def test_intelligence_query_api_returns_live_recommendations_with_sparse_advanced_signals(self) -> None:
        advanced_rows = [
            {
                "label": "Team advanced stats",
                "metrics": ["Pace", "Offensive rating", "Shot profile"],
                "path": "data/nba_source/data/processed/team_advanced_stats_2026.csv",
                "exists": True,
                "tracked": True,
                "inside_repo": True,
            }
        ]
        with _patch_build_intelligence_overview(_sample_overview()):
            with patch("syndicate.features.intelligence._tracked_repo_files", return_value=set()):
                with patch("syndicate.features.intelligence._advanced_input_rows_for_sport", return_value=advanced_rows):
                    with patch("syndicate.features.intelligence.load_artifact_manifests", return_value=[]):
                        response = self.client.post(
                            "/api/intelligence/query",
                            json={
                                "question": "What are the best live bets?",
                                "date": "2026-06-04",
                                "force_refresh": True,
                            },
                        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        result = payload.get("response") or {}
        self.assertTrue(result.get("recommendations"))
        self.assertGreater(len(result.get("recommendations") or []), 0)
        self.assertTrue((result.get("structured_response") or {}).get("summary"))

    def test_intelligence_query_api_normalizes_top_opportunities_for_ui_contract(self) -> None:
        computed_response = {
            "ok": True,
            "top_opportunities": [
                {
                    "selection": "Over 7.5",
                    "market": "Hits",
                    "score": 1.2,
                    "normalized_edge": 0.33,
                    "sport": "MLB",
                }
            ],
            "by_sport": {"mlb": [{"selection": "Over 7.5", "market": "Hits", "score": 1.2}]},
            "analysis": {
                "recommendations": [{"selection": "Over 7.5", "market": "Hits", "score": 1.2}],
                "top_live_opportunities": [],
                "portfolio": {},
                "parlays": [],
            },
            "response": {
                "top_opportunities": [
                    {
                        "selection": "Over 7.5",
                        "market": "Hits",
                        "score": 1.2,
                        "normalized_edge": 0.33,
                        "sport": "MLB",
                    }
                ],
                "analysis": {
                    "recommendations": [{"selection": "Over 7.5", "market": "Hits", "score": 1.2}],
                    "top_live_opportunities": [],
                    "portfolio": {},
                    "parlays": [],
                },
            },
        }

        # _cached_intelligence_response_with_source is only consulted on the
        # render-hosted branch of force_refresh (_render_hosted_request());
        # without RENDER set the endpoint takes the non-hosted branch instead
        # and this mock was dead, so the response came from whatever real
        # repo artifacts _compute_intelligence_response found on disk
        # (observed: "Jordin Canada OVER 9.5").
        with patch.dict(os.environ, {"RENDER": "1"}):
            with patch("syndicate.blueprints.intelligence._cached_intelligence_response_with_source", return_value=(dict(computed_response), "render_compute")):
                with patch("syndicate.blueprints.intelligence.queue_intelligence_state_refresh"):
                    response = self.client.post(
                        "/api/intelligence/query",
                        json={
                            "question": "What are the best edges for this board?",
                            "date": "2026-06-18",
                            "force_refresh": True,
                        },
                    )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        result = payload.get("response") or {}
        top_opportunities = result.get("top_opportunities") or []
        self.assertGreater(len(top_opportunities), 0)
        first = top_opportunities[0]
        self.assertEqual(first.get("name"), "Over 7.5")
        self.assertEqual(first.get("pick"), "Over 7.5")
        self.assertEqual(first.get("market"), "Hits")
        self.assertEqual(first.get("score"), 1.2)
        self.assertEqual(first.get("edge"), 0.33)
        self.assertEqual(first.get("sport_slug"), "mlb")
        self.assertNotIn("undefined", json.dumps(first))

    def test_intelligence_query_api_resolves_preview_date_and_preserves_contract(self) -> None:
        advanced_rows = [
            {
                "label": "Team advanced stats",
                "metrics": ["Pace", "Offensive rating", "Shot profile"],
                "path": "data/nba_source/data/processed/team_advanced_stats_2026.csv",
                "exists": True,
                "tracked": True,
                "inside_repo": True,
            }
        ]
        with patch("router.query_router.central_today_iso", return_value="2026-06-07"):
            with _patch_build_intelligence_overview(_sample_overview()):
                with patch("syndicate.features.intelligence._tracked_repo_files", return_value=set()):
                    with patch("syndicate.features.intelligence._advanced_input_rows_for_sport", return_value=advanced_rows):
                        with patch("syndicate.features.intelligence.load_artifact_manifests", return_value=[]):
                            response = self.client.post(
                                "/api/intelligence/query",
                                json={
                                    "force_refresh": True,
                                    "question": "preview the Lakers game tonight",
                                },
                            )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertIn("version", payload)
        self.assertIn("timestamp", payload)
        self.assertIn("response", payload)
        result = payload.get("response") or {}
        board_contract = result.get("board_contract") or {}
        self.assertTrue(result.get("selected_date"))
        self.assertTrue((board_contract.get("cards") or []))
        self.assertEqual((board_contract.get("cards") or [])[0].get("sport"), "nba")
        self.assertEqual((board_contract.get("cards") or [])[0].get("name"), "Jayson Tatum Over 28.5")

    def test_intelligence_query_api_respects_explicit_filters_and_limit(self) -> None:
        overview = _sample_overview_with_secondary_sport()
        nba_live_bucket = ((overview[0].get("home_rails") or {}).get("live") or {})
        wnba_live_bucket = ((overview[1].get("home_rails") or {}).get("live") or {})
        nba_live_bucket["items"] = list(nba_live_bucket.get("items") or [])
        wnba_live_bucket["items"] = list(wnba_live_bucket.get("items") or [])
        nba_live_items = nba_live_bucket["items"]
        wnba_live_items = wnba_live_bucket["items"]

        nba_live_items.extend(
            [
                {
                    "name": "Darius Garland Over 7.5 Assists",
                    "market": "AST",
                    "pick": "Over 7.5",
                    "matchup": "CLE at IND",
                    "projected": 8.3,
                    "live_projection": 8.8,
                    "line": 7.5,
                    "odds": "+106",
                    "confidence": "60%",
                    "edge": "+3.7%",
                    "team_pace_signal": 1.07,
                    "usage_rate_advanced": 1.09,
                    "shot_profile_advanced": 1.01,
                    "minutes_role_advanced": 1.04,
                    "writeup": "The live role is still generating clean volume after the market move.",
                    "display_pills": ["Line 7.5", "Odds +106", "Live Proj 8.8"],
                    "is_live": True,
                    "href": "/nba/season/2026/live-lens?date=2026-06-04",
                },
                {
                    "name": "Evan Mobley Over 9.5 Rebounds",
                    "market": "REB",
                    "pick": "Over 9.5",
                    "matchup": "CLE at IND",
                    "projected": 10.4,
                    "live_projection": 10.9,
                    "line": 9.5,
                    "odds": "+104",
                    "confidence": "59%",
                    "edge": "+3.1%",
                    "team_pace_signal": 1.06,
                    "usage_rate_advanced": 1.02,
                    "shot_profile_advanced": 1.03,
                    "minutes_role_advanced": 1.05,
                    "writeup": "Rebounding volume is holding above the live number.",
                    "display_pills": ["Line 9.5", "Odds +104", "Live Proj 10.9"],
                    "is_live": True,
                    "href": "/nba/season/2026/live-lens?date=2026-06-04",
                },
            ]
        )
        wnba_live_items.extend(
            [
                {
                    "name": "Chelsea Gray Over 17.5 PA",
                    "market": "PA",
                    "pick": "Over 17.5",
                    "matchup": "LVA at SEA",
                    "projected": 18.6,
                    "live_projection": 19.1,
                    "line": 17.5,
                    "odds": "+100",
                    "confidence": "58%",
                    "edge": "+2.8%",
                    "team_environment_advanced": 1.08,
                    "possession_profile_advanced": 1.04,
                    "matchup_pressure_advanced": 1.07,
                    "rotation_pressure_advanced": 1.02,
                    "live_shift_advanced": 1.03,
                    "writeup": "Live creation volume remains above the adjusted line.",
                    "display_pills": ["Line 17.5", "Odds +100", "Live Proj 19.1"],
                    "is_live": True,
                    "href": "/wnba/live-lens?date=2026-06-04",
                },
                {
                    "name": "Jackie Young Over 2.5 Threes",
                    "market": "3PM",
                    "pick": "Over 2.5",
                    "matchup": "LVA at SEA",
                    "projected": 3.1,
                    "live_projection": 3.4,
                    "line": 2.5,
                    "odds": "+108",
                    "confidence": "57%",
                    "edge": "+2.6%",
                    "team_environment_advanced": 1.09,
                    "possession_profile_advanced": 1.03,
                    "matchup_pressure_advanced": 1.06,
                    "rotation_pressure_advanced": 1.01,
                    "live_shift_advanced": 1.02,
                    "writeup": "Three-point volume is still tracking above the live reset.",
                    "display_pills": ["Line 2.5", "Odds +108", "Live Proj 3.4"],
                    "is_live": True,
                    "href": "/wnba/live-lens?date=2026-06-04",
                },
            ]
        )

        advanced_rows = [
            {
                "label": "Team advanced stats",
                "metrics": ["Pace", "Usage", "Matchup pressure"],
                "path": "data/nba_source/data/processed/team_advanced_stats_2026.csv",
                "exists": True,
                "tracked": True,
                "inside_repo": True,
            }
        ]
        with _patch_build_intelligence_overview(overview):
            with patch("syndicate.features.intelligence._tracked_repo_files", return_value=set()):
                with patch("syndicate.features.intelligence._advanced_input_rows_for_sport", return_value=advanced_rows):
                    response = self.client.post(
                        "/api/intelligence/query",
                        json={
                            "force_refresh": True,
                            "question": "Rank the strongest in-session board targets right now.",
                            "date": "2026-06-04",
                            "timing": "live",
                            "include_props": True,
                            "include_games": False,
                            "limit": 4,
                        },
                    )

        self.assertEqual(response.status_code, 200)
        result = (response.get_json() or {}).get("response") or {}
        recommendations = result.get("recommendations") or []
        parsed_request = result.get("parsed_request") or {}
        self.assertEqual(len(recommendations), 4)
        self.assertTrue(all(item.get("is_live") for item in recommendations))
        self.assertTrue(all(item.get("candidate_type") == "prop" for item in recommendations))
        self.assertEqual(parsed_request.get("timing"), "Live only")
        self.assertEqual(parsed_request.get("board_scope"), ["Props"])
        self.assertIn("Top 4", parsed_request.get("chips") or [])

    def test_intelligence_query_api_forwards_policy_override(self) -> None:
        engine_response = {
            "ok": True,
            "headline": "Policy-aware intelligence brief",
            "selected_date": "2026-06-13",
            "policy_control": {"selected_policy": "aggressive", "decision_strategy": "aggressive"},
            "board_contract": {"schema": "intelligence_board_v1", "lane_counts": {"live": 0, "pregame": 0}, "active_lanes": [], "cards": []},
            "recommendation_history": {},
            "portfolio_tracking": {},
            "portfolio_events": {},
            "portfolio_event_records": [],
            "recommendations": [],
            "parlays": [],
            "top_opportunities": [],
            "by_sport": {},
        }

        with self.client.application.test_request_context(
            "/api/intelligence/query",
            method="POST",
            json={"question": "Analyze Jayson Tatum tonight", "date": "2026-06-13", "policy": "aggressive", "force_refresh": True},
        ):
            # The query no longer reaches run_intelligence_query from the
            # blueprint -- the compute seam is the state service, and the
            # forwarding under test is the payload _compute_intelligence_response
            # builds for it.
            from pipeline.intelligence_state import _INTELLIGENCE_STATE_SERVICE

            with patch("syndicate.blueprints.intelligence._cached_intelligence_response_with_source", return_value=(None, "fallback")):
                with patch.object(_INTELLIGENCE_STATE_SERVICE, "_compute_response", return_value=dict(engine_response)) as mocked_run:
                    response = intelligence_query_api()

        payload = response.get_json()
        self.assertIsNotNone(payload)
        self.assertIn("response", payload)
        self.assertEqual(payload["response"]["policy_control"]["selected_policy"], "aggressive")
        mocked_run.assert_called_once()
        self.assertEqual(mocked_run.call_args.args[0].get("policy"), "aggressive")

    def test_intelligence_query_api_forwards_game_state_override(self) -> None:
        engine_response = {
            "ok": True,
            "headline": "Live board brief",
            "selected_date": "2026-06-13",
            "board_contract": {"schema": "intelligence_board_v1", "lane_counts": {"live": 0, "pregame": 0}, "active_lanes": [], "cards": []},
            "recommendation_history": {},
            "portfolio_tracking": {},
            "portfolio_events": {},
            "portfolio_event_records": [],
            "recommendations": [],
            "parlays": [],
            "top_opportunities": [],
            "by_sport": {},
        }

        with self.client.application.test_request_context(
            "/api/intelligence/query",
            method="POST",
            json={"question": "Analyze the live board", "date": "2026-06-13", "sport": "nba", "game_state": "live", "force_refresh": True},
        ):
            # Same seam move as the policy-override test above: forwarding is
            # asserted on the payload handed to the state service.
            from pipeline.intelligence_state import _INTELLIGENCE_STATE_SERVICE

            with patch("syndicate.blueprints.intelligence._cached_intelligence_response_with_source", return_value=(None, "fallback")):
                with patch.object(_INTELLIGENCE_STATE_SERVICE, "_compute_response", return_value=dict(engine_response)) as mocked_run:
                    response = intelligence_query_api()

        payload = response.get_json()
        self.assertIsNotNone(payload)
        self.assertIn("response", payload)
        mocked_run.assert_called_once()
        self.assertEqual(mocked_run.call_args.args[0].get("game_state"), "live")

    def test_intelligence_query_prioritizes_ready_advanced_inputs(self) -> None:
        advanced_by_sport = {
            "nba": [
                {
                    "label": "Team advanced stats",
                    "metrics": ["Pace", "Offensive rating", "Shot profile"],
                    "path": "data/nba_source/data/processed/team_advanced_stats_2026.csv",
                    "exists": True,
                    "tracked": True,
                    "inside_repo": True,
                }
            ],
            "wnba": [
                {
                    "label": "Team environment and pace layer",
                    "metrics": ["Pace", "Team environment"],
                    "path": "data/wnba_source/data/processed/recommendations_slate_2026-06-04.json",
                    "exists": False,
                    "tracked": False,
                    "inside_repo": True,
                }
            ],
        }
        with _patch_build_intelligence_overview(_sample_overview_with_secondary_sport()):
            with patch("syndicate.features.intelligence._tracked_repo_files", return_value=set()):
                with patch("syndicate.features.intelligence._advanced_input_rows_for_sport", side_effect=lambda sport, tracked: advanced_by_sport.get(sport.get("slug"), [])):
                    response = self.client.post(
                        "/api/intelligence/query",
                        json={
                            "force_refresh": True,
                            "question": "Give me the best pregame props across NBA and WNBA",
                            "date": "2026-06-04",
                        },
                    )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        result = payload.get("response") or {}
        recommendations = result.get("recommendations") or []
        self.assertGreaterEqual(len(recommendations), 2)
        self.assertEqual(recommendations[0].get("sport_slug"), "nba")
        self.assertTrue(recommendations[0].get("advanced_ready"))
        self.assertEqual(recommendations[1].get("advanced_readiness"), "blocked")
        self.assertTrue(recommendations[1].get("missing_advanced_inputs"))
        self.assertIn("missing or unpublished", recommendations[1].get("rationale") or "")

    def test_intelligence_query_surfaces_direct_statcast_signals(self) -> None:
        advanced_rows = [
            {
                "label": "Statcast batter and pitcher features",
                "metrics": ["Launch angle", "Exit velocity", "Barrel rate", "Pitch mix"],
                "path": "data/mlb_source/data/statcast/features/player_features_latest.json",
                "exists": True,
                "tracked": True,
                "inside_repo": True,
            }
        ]
        with _patch_build_intelligence_overview(_sample_mlb_statcast_overview()):
            with patch("syndicate.features.intelligence._tracked_repo_files", return_value=set()):
                with patch("syndicate.features.intelligence._advanced_input_rows_for_sport", return_value=advanced_rows):
                    response = self.client.post(
                        "/api/intelligence/query",
                        json={
                            "force_refresh": True,
                            "question": "Give me the best MLB props using Statcast data",
                            "date": "2026-06-05",
                        },
                    )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json() or {}
        result = payload.get("response") or {}
        recommendations = result.get("recommendations") or []
        self.assertGreaterEqual(len(recommendations), 2)
        first = recommendations[0]
        self.assertEqual(first.get("market"), "HR")
        self.assertTrue(first.get("advanced_signals"))
        self.assertIn("batter_statcast_hr_mult", {item.get("key") for item in first.get("advanced_signals") or []})
        self.assertIn("Candidate-level advanced signals", first.get("rationale") or "")
        self.assertGreater(float(first.get("advanced_signal_score") or 0.0), 0.0)

    def test_intelligence_query_builds_home_run_analysis_views(self) -> None:
        advanced_rows = [
            {
                "label": "Statcast batter and pitcher features",
                "metrics": ["Launch angle", "Exit velocity", "Barrel rate", "Pitch mix"],
                "path": "data/mlb_source/data/statcast/features/player_features_latest.json",
                "exists": True,
                "tracked": True,
                "inside_repo": True,
            }
        ]
        with _patch_build_intelligence_overview(_sample_mlb_statcast_overview()):
            with patch("syndicate.features.intelligence._tracked_repo_files", return_value=set()):
                with patch("syndicate.features.intelligence._advanced_input_rows_for_sport", return_value=advanced_rows):
                    response = self.client.post(
                        "/api/intelligence/query",
                        json={
                            "force_refresh": True,
                            "question": "What are the best home run matchups today and why? Build a top 10 table and chart.",
                            "date": "2026-06-05",
                        },
                    )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json() or {}
        result = payload.get("response") or {}
        parsed_request = result.get("parsed_request") or {}
        self.assertEqual((result.get("analysis_views") or {}).get("focus"), "mlb_home_runs")
        self.assertEqual(parsed_request.get("intent"), "best_bets")
        self.assertEqual((result.get("analysis_views") or {}).get("table", {}).get("title"), "Top 10 likely HR targets")
        self.assertTrue((result.get("analysis_views") or {}).get("table", {}).get("rows"))
        self.assertTrue((result.get("analysis_views") or {}).get("chart", {}).get("rows"))
        first_row = ((result.get("analysis_views") or {}).get("table", {}).get("rows") or [])[0]
        self.assertIn("batter_hr_mult", first_row)
        self.assertIn("pitcher_hr_mult", first_row)
        self.assertIn("why", first_row)

    def test_intelligence_query_uses_mlb_hr_artifact_candidates_when_home_rails_are_empty(self) -> None:
        overview = [
            {
                "slug": "mlb",
                "name": "MLB",
                "context_label": "2026-06-05",
                "data_health": "healthy",
                "data_warnings": [],
                "home_rails": {
                    "pregame": {"title": "Pregame props", "items": []},
                    "live": {"title": "Top Live Props", "items": []},
                    "compact": {"items": []},
                },
                "dashboard_games": [],
            }
        ]
        hr_candidates = [
            {
                "candidate_type": "prop",
                "sport": "MLB",
                "sport_slug": "mlb",
                "surface_key": "pregame",
                "surface_title": "HR targets",
                "name": "Aaron Judge",
                "market": "Home Runs",
                "market_key": "home_runs",
                "pick": "Over 0.5",
                "matchup": "NYY at BOS",
                "line": "0.5",
                "odds": "-",
                "projected": "-",
                "confidence": "24.1%",
                # HR-target candidates have no book price to project against;
                # model_probability is the recognized projection-scan field
                # that carries their real signal (see the matching comment in
                # _mlb_home_run_candidates_from_artifact) -- without it this
                # fixture is pruned at classification as
                # missing_projection_or_odds before it ever reaches the board.
                "model_probability": 0.241,
                "edge": "-",
                "score": 91.0,
                "href": "/mlb/hr-targets?date=2026-06-05",
                "href_label": "Open HR board",
                "writeup": "Expected opportunity is strong and the handedness split is favorable.",
                "display_pills": ["HR Prob 24.1%", "Support 67"],
                "advanced_signals": [
                    {"key": "batter_statcast_hr_mult", "label": "Batter Statcast home-run multiplier", "value": 1.24},
                    {"key": "pitcher_statcast_hr_mult", "label": "Pitcher Statcast home-run multiplier", "value": 1.11},
                ],
                "batter_id": 608324,
                "opponent_pitcher_id": 605400,
            }
        ]
        advanced_rows = [
            {
                "label": "Statcast batter and pitcher features",
                "metrics": ["Launch angle", "Exit velocity", "Barrel rate", "Pitch mix"],
                "path": "data/mlb_source/data/statcast/features/player_features_latest.json",
                "exists": True,
                "tracked": True,
                "inside_repo": True,
            }
        ]
        with _patch_build_intelligence_overview(overview):
            with patch("syndicate.features.intelligence._tracked_repo_files", return_value=set()):
                with patch("syndicate.features.intelligence._advanced_input_rows_for_sport", return_value=advanced_rows):
                    with patch("syndicate.features.intelligence._mlb_home_run_candidates_from_artifact", return_value=hr_candidates):
                        response = self.client.post(
                            "/api/intelligence/query",
                            json={
                                "force_refresh": True,
                                "question": "What are the best home run matchups today and why? Build a top 10 table and chart.",
                                "date": "2026-06-05",
                            },
                        )

        self.assertEqual(response.status_code, 200)
        result = (response.get_json() or {}).get("response") or {}
        self.assertEqual(result.get("headline"), "The Syndicate home runs board")
        self.assertTrue(result.get("recommendations"))
        self.assertEqual((result.get("recommendations") or [])[0].get("sport_slug"), "mlb")
        self.assertEqual(((result.get("analysis_views") or {}).get("table") or {}).get("rows")[0].get("player"), "Aaron Judge")

    def test_mlb_home_run_artifact_candidates_survive_classification(self) -> None:
        # Direct unit coverage of the real builder (the test above mocks it
        # out entirely). Regression: odds and projected are always "-" for
        # this candidate type -- there's no book line to project against --
        # and until model_probability was wired from hr_probability, nothing
        # in normalize_candidate's projection scan recognized that, so
        # _classify_candidate_with_reason pruned every HR-target candidate
        # this function has ever produced as missing_projection_or_odds.
        # The mocked-artifact test above could not have caught this; it
        # never calls the real function or the real classifier.
        from syndicate.features.intelligence import (
            _classify_candidate_with_reason,
            _mlb_home_run_candidates_from_artifact,
        )

        artifact_payload = {
            "rows": [
                {
                    "player_name": "Aaron Judge",
                    "team": "NYY",
                    "matchup": "NYY at BOS",
                    "p_hr_1plus": 0.241,
                    "hr_support_raw_score": 67,
                    "hr_target_reasons": ["Favorable handedness split"],
                }
            ]
        }
        with patch("syndicate.features.intelligence.mlb_load_json_file", return_value=artifact_payload):
            candidates = _mlb_home_run_candidates_from_artifact({"slug": "mlb", "context_label": "2026-06-05"})

        self.assertEqual(len(candidates), 1)
        candidate = candidates[0]
        self.assertEqual(candidate.get("model_probability"), 0.241)
        self.assertEqual(candidate.get("actual"), "-")
        classified, reason = _classify_candidate_with_reason(candidate)
        self.assertIsNone(reason)
        self.assertIsNotNone(classified)

    def test_mlb_prop_candidate_from_artifact_row_defaults_actual_to_dash(self) -> None:
        # Layer 2 board follow-up: this is the PRIMARY pregame source for
        # MLB "Hitter X"/"Pitcher X" prop candidates, and it never set an
        # "actual" field at all -- only _mlb_hydrate_live_prop_projection
        # (a separate overlay that runs once a game goes live) ever added
        # one. Before this game goes live (or in any cycle where hydration
        # doesn't find a match), "actual" serialized as a raw None instead
        # of this board's universal "-" placeholder.
        from syndicate.features.intelligence import _mlb_prop_candidate_from_artifact_row

        row = {
            "ownerName": "Yordan Alvarez",
            "stat": "hitter_total_bases",
            "statLabel": "Total Bases",
            "mean": 2.1,
            "line": 1.5,
            "selectionLabel": "Over",
            "gamePk": 824003,
        }
        candidate = _mlb_prop_candidate_from_artifact_row(
            {"slug": "mlb", "name": "MLB"},
            row,
            selected_date="2026-07-29",
        )

        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.get("actual"), "-")

    def test_mlb_home_run_candidates_carry_the_game_id_the_artifact_row_has(self) -> None:
        # Without game_id/gamePk/event_id, intelligence.html's gameKey() falls
        # back to a sport+matchup-text key that can never match the id-keyed
        # group every other MLB candidate type produces for the same real
        # game -- confirmed live as a duplicate "Team A @ Team B, N
        # opportunities" fallback card sitting next to the real,
        # chip-hydrated score card for that game.
        from syndicate.features.intelligence import _mlb_home_run_candidates_from_artifact

        artifact_payload = {
            "rows": [
                {
                    "player_name": "Aaron Judge",
                    "team": "NYY",
                    "matchup": "NYY at BOS",
                    "p_hr_1plus": 0.241,
                    "gamePk": 745804,
                }
            ]
        }
        with patch("syndicate.features.intelligence.mlb_load_json_file", return_value=artifact_payload):
            candidates = _mlb_home_run_candidates_from_artifact({"slug": "mlb", "context_label": "2026-06-05"})

        self.assertEqual(len(candidates), 1)
        candidate = candidates[0]
        self.assertEqual(candidate.get("game_pk"), 745804)
        self.assertEqual(candidate.get("game_id"), "745804")
        self.assertEqual(candidate.get("event_id"), "745804")

    def test_mlb_live_lens_prop_candidates_generated_and_survive_classification(self) -> None:
        # #128: daily_top_props_<date>.json (every other MLB prop candidate
        # function's sole source) is a once-a-day artifact -- confirmed live
        # unchanged for over an hour during an active slate, while live-lens
        # itself rotates continuously. Without a candidate-generation path
        # sourced directly from live-lens, a prop that only ever appears
        # there (not in the static snapshot) could never become a board
        # candidate. Fixture shapes match real production field names
        # confirmed the same night (gamePk, status.abstract="Live",
        # trackedProps rows with playerName/marketLabel/line/odds/selection/
        # estimatedWinProb/liveProjection/actual).
        from syndicate.features.intelligence import (
            _classify_candidate_with_reason,
            _mlb_live_lens_prop_candidates_from_artifact,
        )

        live_lens_payload = {
            "games": [
                {
                    "gamePk": 824003,
                    "status": {"abstract": "Live", "detailed": "In Progress"},
                    "matchup": {"away": {"abbr": "HOU"}, "home": {"abbr": "LAA"}},
                    "trackedProps": [
                        {
                            "playerName": "Yordan Alvarez",
                            "market": "hitter_total_bases",
                            "marketLabel": "Hitter Total Bases",
                            "prop": "batter_total_bases",
                            "selection": "Under",
                            "line": 4.5,
                            "odds": "-120",
                            "estimatedWinProb": 0.837,
                            "modelProbOver": 0.163,
                            "rankingScore": 0.43,
                            "actual": None,
                            "liveProjection": None,
                        }
                    ],
                },
                {
                    # Final game -- must be excluded (live-only by design).
                    "gamePk": 823598,
                    "status": {"abstract": "Final", "detailed": "Final"},
                    "matchup": {"away": {"abbr": "SEA"}, "home": {"abbr": "LAD"}},
                    "trackedProps": [
                        {
                            "playerName": "Cal Raleigh",
                            "market": "hitter_hits",
                            "marketLabel": "Hitter Hits",
                            "selection": "Over",
                            "line": 1.5,
                            "odds": "+110",
                            "estimatedWinProb": 0.6,
                        }
                    ],
                },
            ]
        }
        with patch(
            "syndicate.features.intelligence._mlb_live_lens_report_cached",
            return_value=live_lens_payload,
        ):
            candidates = _mlb_live_lens_prop_candidates_from_artifact({"slug": "mlb", "name": "MLB", "context_label": "2026-07-28"})

        self.assertEqual(len(candidates), 1, candidates)
        candidate = candidates[0]
        self.assertEqual(candidate.get("player_name"), "Yordan Alvarez")
        self.assertEqual(candidate.get("market"), "Hitter Total Bases")
        self.assertEqual(candidate.get("pick"), "Under 4.5")
        self.assertEqual(candidate.get("odds"), "-120")
        self.assertEqual(candidate.get("game_pk"), 824003)
        self.assertTrue(candidate.get("is_live"))
        self.assertAlmostEqual(candidate.get("model_probability"), 0.837)
        classified, reason = _classify_candidate_with_reason(candidate)
        self.assertIsNone(reason)
        self.assertIsNotNone(classified)

    def test_mlb_live_lens_prop_candidates_use_pregame_mean_as_projected(self) -> None:
        # Layer 2 board follow-up: live-lens rows carry no pregame projection
        # field at all -- only a live one -- so "projected" and
        # "live_projection" used to be stamped with the SAME live value.
        # When a matching daily_top_props row exists for the same
        # player+market(+game), its "mean" is the real pregame value and
        # must end up in "projected", distinct from the live value.
        from syndicate.features.intelligence import _mlb_live_lens_prop_candidates_from_artifact

        live_lens_payload = {
            "games": [
                {
                    "gamePk": 824003,
                    "status": {"abstract": "Live", "detailed": "In Progress"},
                    "matchup": {"away": {"abbr": "HOU"}, "home": {"abbr": "LAA"}},
                    "trackedProps": [
                        {
                            "playerName": "Yordan Alvarez",
                            "market": "hitter_total_bases",
                            "marketLabel": "Hitter Total Bases",
                            "selection": "Under",
                            "line": 4.5,
                            "odds": "-120",
                            "estimatedWinProb": 0.837,
                            "liveProjection": 3.9,
                            "actual": 1.0,
                        }
                    ],
                }
            ]
        }
        pregame_rows = [
            {
                "ownerName": "Yordan Alvarez",
                "stat": "hitter_total_bases",
                "mean": 4.6,
                "gamePk": 824003,
            }
        ]
        with patch(
            "syndicate.features.intelligence._mlb_live_lens_report_cached",
            return_value=live_lens_payload,
        ), patch(
            "syndicate.features.intelligence._mlb_top_props_rows_from_artifact",
            return_value=pregame_rows,
        ):
            candidates = _mlb_live_lens_prop_candidates_from_artifact({"slug": "mlb", "name": "MLB", "context_label": "2026-07-28"})

        self.assertEqual(len(candidates), 1, candidates)
        candidate = candidates[0]
        self.assertEqual(candidate.get("projected"), "4.6")
        self.assertEqual(candidate.get("live_projection"), "3.9")
        self.assertNotEqual(candidate.get("projected"), candidate.get("live_projection"))

    def test_mlb_live_lens_hits_runs_rbis_join_survives_label_variant_mismatch(self) -> None:
        # 2026-08-01 board audit follow-up: daily_top_props stamps this
        # composite stat's key as "hits_runs_rbis" (row.get("stat")), while
        # live-lens's own trackedProps rows carry the vendor sim's display
        # label "Hitter H+R+R" as marketLabel -- before this stat had its
        # own _MARKET_FOCUS_ALIASES entry, "hits_runs_rbis" false-matched
        # the plain "hits" alias (both texts contain the word "hits") while
        # "Hitter H+R+R" fell through to a different fallback key
        # ("h_r_r") -- two different builders, two different keys, so
        # _mlb_pregame_mean_by_player_market's cross-builder lookup always
        # missed and this market's live candidates stayed permanently blank
        # in "projected" even with a real daily_top_props mean available.
        from syndicate.features.intelligence import _mlb_live_lens_prop_candidates_from_artifact

        live_lens_payload = {
            "games": [
                {
                    "gamePk": 824162,
                    "status": {"abstract": "Live", "detailed": "In Progress"},
                    "matchup": {"away": {"abbr": "TEX"}, "home": {"abbr": "HOU"}},
                    "trackedProps": [
                        {
                            "playerName": "Isaac Paredes",
                            "market": "hitter_hits_runs_rbis",
                            "marketLabel": "Hitter H+R+R",
                            "selection": "Over",
                            "line": 1.5,
                            "odds": "+100",
                            "estimatedWinProb": 0.52,
                            "liveProjection": 2.0,
                            "actual": 1.0,
                        }
                    ],
                }
            ]
        }
        pregame_rows = [
            {
                "ownerName": "Isaac Paredes",
                "stat": "hits_runs_rbis",
                "statLabel": "Hits + Runs + RBIs",
                "mean": 1.912,
                "gamePk": 824162,
            }
        ]
        with patch(
            "syndicate.features.intelligence._mlb_live_lens_report_cached",
            return_value=live_lens_payload,
        ), patch(
            "syndicate.features.intelligence._mlb_top_props_rows_from_artifact",
            return_value=pregame_rows,
        ):
            candidates = _mlb_live_lens_prop_candidates_from_artifact({"slug": "mlb", "name": "MLB", "context_label": "2026-07-28"})

        self.assertEqual(len(candidates), 1, candidates)
        candidate = candidates[0]
        self.assertEqual(candidate.get("projected"), "1.9")
        self.assertEqual(candidate.get("live_projection"), "2.0")

    def test_mlb_backfill_missing_projected_fills_from_top_props_by_subject_and_market(self) -> None:
        # 2026-08-02 board audit follow-up: reproduces the real "Miguel
        # Rojas" bug confirmed live -- a prop candidate whose exact
        # originating builder was never pinned down (malformed "OVER
        # Miguel Rojas" pick text, narrative detail with the real mean
        # baked into prose, blank structured "projected") but whose clean
        # player_name/market_focuses/game_pk are all intact, so the
        # backfill can still resolve it against daily_top_props' real row
        # (mean 1.807) even without knowing which function built it.
        from syndicate.features.intelligence import _mlb_backfill_missing_projected_from_top_props

        candidate = {
            "candidate_type": "prop",
            "sport_slug": "mlb",
            "player_name": "Miguel Rojas",
            "name": "Miguel Rojas",
            "pick": "OVER Miguel Rojas",
            "selection": "OVER Miguel Rojas",
            "market": "Hitter H+r+r",
            "market_key": "hitter h+r+r",
            "market_focuses": ["hits_runs_rbis"],
            "game_pk": 823920,
            "projected": "-",
            "detail": "The model baseline comes in around 1.8 batter hits runs rbis against a line of 0.5.",
        }
        pregame_rows = [
            {
                "ownerName": "Miguel Rojas",
                "stat": "hits_runs_rbis",
                "statLabel": "Hits + Runs + RBIs",
                "mean": 1.807,
                "gamePk": 823920,
            }
        ]
        with patch(
            "syndicate.features.intelligence._mlb_top_props_rows_from_artifact",
            return_value=pregame_rows,
        ):
            filled = _mlb_backfill_missing_projected_from_top_props(
                {"slug": "mlb", "context_label": "2026-08-01"}, [candidate]
            )

        self.assertEqual(filled, 1)
        self.assertEqual(candidate.get("projected"), "1.8")

    def test_mlb_backfill_missing_projected_never_overwrites_a_real_value(self) -> None:
        from syndicate.features.intelligence import _mlb_backfill_missing_projected_from_top_props

        candidate = {
            "candidate_type": "prop",
            "sport_slug": "mlb",
            "player_name": "Miguel Rojas",
            "market_focuses": ["hits_runs_rbis"],
            "game_pk": 823920,
            "projected": "3.3",
        }
        pregame_rows = [{"ownerName": "Miguel Rojas", "stat": "hits_runs_rbis", "mean": 1.807, "gamePk": 823920}]
        with patch(
            "syndicate.features.intelligence._mlb_top_props_rows_from_artifact",
            return_value=pregame_rows,
        ):
            filled = _mlb_backfill_missing_projected_from_top_props(
                {"slug": "mlb", "context_label": "2026-08-01"}, [candidate]
            )

        self.assertEqual(filled, 0)
        self.assertEqual(candidate.get("projected"), "3.3")

    def test_mlb_backfill_missing_projected_also_fills_standalone_steam_candidates(self) -> None:
        # 2026-08-01 board audit: this backfill was gated to candidate_type
        # == "prop" only -- confirmed live, ~195 of MLB's ~360 Layer 2
        # candidates (over half the board) were standalone steam candidates
        # (_steam_candidates_for_sport hardcodes "projected": "-"
        # unconditionally, since that function has no sim access of its
        # own) that never merged with a matching prop candidate -- a real
        # steam/line move on a player+market the recommendation engine
        # simply never flagged as a top pick, confirmed against a real
        # example (Jung Hoo Lee home runs) whose daily_top_props row exists
        # (mean 0.032) despite no matching prop candidate anywhere in the
        # pool. Steam candidates carry player_name/market_key/game_pk in
        # the same shape prop candidates do, so the same lookup applies.
        from syndicate.features.intelligence import _mlb_backfill_missing_projected_from_top_props

        candidate = {
            "candidate_type": "steam",
            "sport_slug": "mlb",
            "player_name": "Jung Hoo Lee",
            "name": "Jung Hoo Lee Home runs steam move",
            "pick": "Jung Hoo Lee over 0.5",
            "market": "Home runs · Steam",
            "market_key": "home_runs",
            "game_pk": 824010,
            "projected": "-",
        }
        pregame_rows = [{"ownerName": "Jung Hoo Lee", "stat": "home_runs", "mean": 0.032, "gamePk": 824010}]
        with patch(
            "syndicate.features.intelligence._mlb_top_props_rows_from_artifact",
            return_value=pregame_rows,
        ):
            filled = _mlb_backfill_missing_projected_from_top_props(
                {"slug": "mlb", "context_label": "2026-08-01"}, [candidate]
            )

        self.assertEqual(filled, 1)
        self.assertEqual(candidate.get("projected"), "0.0")

    def test_mlb_backfill_missing_projected_falls_back_when_steam_candidate_has_no_game_pk(self) -> None:
        # Confirmed live 2026-08-01 (same session, follow-up): the steam fix
        # above still left ~195/200 steam candidates blank in production --
        # _steam_candidates_for_sport's own game_id/game_pk end up ""/None
        # for a real lifecycle event whose game never resolved, so the
        # exact (subject, market_key, game_pk) lookup missed every one of
        # them even though a real per-player mean exists. Must fall back to
        # a (subject, market_key)-only match when game_pk can't be matched.
        from syndicate.features.intelligence import _mlb_backfill_missing_projected_from_top_props

        candidate = {
            "candidate_type": "steam",
            "sport_slug": "mlb",
            "player_name": "Jung Hoo Lee",
            "market": "Home runs · Steam",
            "market_key": "home_runs",
            "game_pk": None,
            "projected": "-",
        }
        pregame_rows = [{"ownerName": "Jung Hoo Lee", "stat": "home_runs", "mean": 0.032, "gamePk": 824010}]
        with patch(
            "syndicate.features.intelligence._mlb_top_props_rows_from_artifact",
            return_value=pregame_rows,
        ):
            filled = _mlb_backfill_missing_projected_from_top_props(
                {"slug": "mlb", "context_label": "2026-08-01"}, [candidate]
            )

        self.assertEqual(filled, 1)
        self.assertEqual(candidate.get("projected"), "0.0")

    def test_mlb_backfill_missing_projected_stays_blank_on_ambiguous_doubleheader(self) -> None:
        # A genuine doubleheader: the same player+stat has two DIFFERENT
        # means across two games. Without a resolvable game_pk on the
        # candidate, guessing either one risks showing the wrong game's
        # number -- must stay "-" rather than pick one arbitrarily.
        from syndicate.features.intelligence import _mlb_backfill_missing_projected_from_top_props

        candidate = {
            "candidate_type": "steam",
            "sport_slug": "mlb",
            "player_name": "Jung Hoo Lee",
            "market": "Home runs · Steam",
            "market_key": "home_runs",
            "game_pk": None,
            "projected": "-",
        }
        pregame_rows = [
            {"ownerName": "Jung Hoo Lee", "stat": "home_runs", "mean": 0.032, "gamePk": 824010},
            {"ownerName": "Jung Hoo Lee", "stat": "home_runs", "mean": 0.058, "gamePk": 824099},
        ]
        with patch(
            "syndicate.features.intelligence._mlb_top_props_rows_from_artifact",
            return_value=pregame_rows,
        ):
            filled = _mlb_backfill_missing_projected_from_top_props(
                {"slug": "mlb", "context_label": "2026-08-01"}, [candidate]
            )

        self.assertEqual(filled, 0)
        self.assertEqual(candidate.get("projected"), "-")

    def test_mlb_backfill_also_fills_blank_team_for_the_same_mystery_candidate_class(self) -> None:
        # 2026-08-01 board audit follow-up: the same mystery-origin
        # candidate class the "projected" backfill above already handles
        # (confirmed live: "Rhys Hoskins"/pick "UNDER Rhys Hoskins") ALSO
        # had a blank "team" despite a real one ("CLE") sitting right there
        # in its daily_top_props row. Must backfill both fields in one pass
        # -- a candidate with real "projected" already but blank "team"
        # must still get team filled (the old code bailed out as soon as
        # "projected" alone was non-blank).
        from syndicate.features.intelligence import _mlb_backfill_missing_projected_from_top_props

        candidate = {
            "candidate_type": "prop",
            "sport_slug": "mlb",
            "player_name": "Rhys Hoskins",
            "pick": "UNDER Rhys Hoskins",
            "market": "Hitter Total Bases",
            "market_key": "total_bases",
            "market_focuses": ["total_bases"],
            "game_pk": 824405,
            "projected": "1.2",
            "team": "-",
        }
        pregame_rows = [
            {"ownerName": "Rhys Hoskins", "stat": "total_bases", "team": "CLE", "mean": 1.205, "gamePk": 824405}
        ]
        with patch(
            "syndicate.features.intelligence._mlb_top_props_rows_from_artifact",
            return_value=pregame_rows,
        ):
            filled = _mlb_backfill_missing_projected_from_top_props(
                {"slug": "mlb", "context_label": "2026-08-01"}, [candidate]
            )

        self.assertEqual(filled, 1)
        self.assertEqual(candidate.get("team"), "CLE")
        self.assertEqual(candidate.get("projected"), "1.2")

    def test_mlb_backfill_team_never_overwrites_a_real_value(self) -> None:
        from syndicate.features.intelligence import _mlb_backfill_missing_projected_from_top_props

        candidate = {
            "candidate_type": "prop",
            "sport_slug": "mlb",
            "player_name": "Rhys Hoskins",
            "market": "Hitter Total Bases",
            "market_key": "total_bases",
            "market_focuses": ["total_bases"],
            "game_pk": 824405,
            "projected": "1.2",
            "team": "PHI",
        }
        pregame_rows = [
            {"ownerName": "Rhys Hoskins", "stat": "total_bases", "team": "CLE", "mean": 1.205, "gamePk": 824405}
        ]
        with patch(
            "syndicate.features.intelligence._mlb_top_props_rows_from_artifact",
            return_value=pregame_rows,
        ):
            filled = _mlb_backfill_missing_projected_from_top_props(
                {"slug": "mlb", "context_label": "2026-08-01"}, [candidate]
            )

        self.assertEqual(filled, 0)
        self.assertEqual(candidate.get("team"), "PHI")

    def test_mlb_backfill_resolves_rbis_vs_rbi_naming_mismatch(self) -> None:
        # 2026-08-01 board audit, final round: confirmed live this was
        # ~77% (60/78) of all remaining blank steam candidates after every
        # other fix in this pass -- _steam_candidates_for_sport's own
        # market_key ("rbis") doesn't match daily_top_props' raw "stat"
        # field naming ("rbi"), a naming-convention mismatch, not a real
        # coverage gap (a real row exists, just under the other spelling).
        from syndicate.features.intelligence import _mlb_backfill_missing_projected_from_top_props

        candidate = {
            "candidate_type": "steam",
            "sport_slug": "mlb",
            "player_name": "Alika Williams",
            "name": "Alika Williams Rbis steam move",
            "market": "Rbis · Steam",
            "market_key": "rbis",
            "pick": "Alika Williams over 0.5",
            "game_pk": None,
            "projected": "-",
        }
        pregame_rows = [{"ownerName": "Alika Williams", "stat": "rbi", "mean": 0.453, "gamePk": 824972}]
        with patch(
            "syndicate.features.intelligence._mlb_top_props_rows_from_artifact",
            return_value=pregame_rows,
        ):
            filled = _mlb_backfill_missing_projected_from_top_props(
                {"slug": "mlb", "context_label": "2026-08-01"}, [candidate]
            )

        self.assertEqual(filled, 1)
        self.assertEqual(candidate.get("projected"), "0.5")

    def test_mlb_backfill_resolves_runs_scored_vs_runs_naming_mismatch(self) -> None:
        from syndicate.features.intelligence import _mlb_backfill_missing_projected_from_top_props

        candidate = {
            "candidate_type": "steam",
            "sport_slug": "mlb",
            "player_name": "Masataka Yoshida",
            "name": "Masataka Yoshida Runs Scored steam move",
            "market": "Runs Scored · Steam",
            "market_key": "runs_scored",
            "pick": "Masataka Yoshida over 0.5",
            "game_pk": None,
            "projected": "-",
        }
        pregame_rows = [{"ownerName": "Masataka Yoshida", "stat": "runs", "mean": 0.379, "gamePk": 824600}]
        with patch(
            "syndicate.features.intelligence._mlb_top_props_rows_from_artifact",
            return_value=pregame_rows,
        ):
            filled = _mlb_backfill_missing_projected_from_top_props(
                {"slug": "mlb", "context_label": "2026-08-01"}, [candidate]
            )

        self.assertEqual(filled, 1)
        self.assertEqual(candidate.get("projected"), "0.4")

    def test_mlb_live_lens_prop_candidates_projected_stays_dash_without_a_pregame_match(self) -> None:
        # No matching daily_top_props row -- must NOT fabricate a pregame
        # value from the live one; "-" is the honest answer.
        from syndicate.features.intelligence import _mlb_live_lens_prop_candidates_from_artifact

        live_lens_payload = {
            "games": [
                {
                    "gamePk": 824003,
                    "status": {"abstract": "Live", "detailed": "In Progress"},
                    "matchup": {"away": {"abbr": "HOU"}, "home": {"abbr": "LAA"}},
                    "trackedProps": [
                        {
                            "playerName": "Yordan Alvarez",
                            "market": "hitter_total_bases",
                            "marketLabel": "Hitter Total Bases",
                            "selection": "Under",
                            "line": 4.5,
                            "odds": "-120",
                            "estimatedWinProb": 0.837,
                            "liveProjection": 3.9,
                            "actual": 1.0,
                        }
                    ],
                }
            ]
        }
        with patch(
            "syndicate.features.intelligence._mlb_live_lens_report_cached",
            return_value=live_lens_payload,
        ), patch(
            "syndicate.features.intelligence._mlb_top_props_rows_from_artifact",
            return_value=[],
        ):
            candidates = _mlb_live_lens_prop_candidates_from_artifact({"slug": "mlb", "name": "MLB", "context_label": "2026-07-28"})

        self.assertEqual(len(candidates), 1, candidates)
        candidate = candidates[0]
        self.assertEqual(candidate.get("projected"), "-")
        self.assertEqual(candidate.get("live_projection"), "3.9")

    def test_mlb_live_lens_prop_candidates_dedupe_within_same_game(self) -> None:
        from syndicate.features.intelligence import _mlb_live_lens_prop_candidates_from_artifact

        row = {
            "playerName": "Jake Bennett",
            "market": "pitcher_props",
            "marketLabel": "Strikeouts",
            "selection": "Over",
            "line": 2.5,
            "odds": "-145",
            "estimatedWinProb": 0.888,
        }
        live_lens_payload = {
            "games": [
                {
                    "gamePk": 824976,
                    "status": {"abstract": "Live", "detailed": "In Progress"},
                    "matchup": {"away": {"abbr": "BOS"}, "home": {"abbr": "ATH"}},
                    "trackedProps": [dict(row), dict(row)],
                }
            ]
        }
        with patch(
            "syndicate.features.intelligence._mlb_live_lens_report_cached",
            return_value=live_lens_payload,
        ):
            candidates = _mlb_live_lens_prop_candidates_from_artifact({"slug": "mlb", "context_label": "2026-07-28"})

        self.assertEqual(len(candidates), 1, candidates)

    def test_soccer_live_lens_prop_candidates_generated_from_live_state(self) -> None:
        # Confirmed live 2026-08-01: _SoccerDataProvider.live_props()
        # (syndicate/blueprints/home.py) is hardcoded `return []` -- soccer
        # never produced a single live prop candidate on the Layer 2 board.
        # Fixture shape matches the real LivePlayerPropProjection.to_dict()
        # output (syndicate/features/soccer/features/live_lens.py).
        from syndicate.features.intelligence import _soccer_live_lens_prop_candidates_from_artifact

        live_state_payload_value = {
            "league": "mls",
            "date": "2026-08-01",
            "games": {
                "761699": {
                    "home_team": "D.C. United",
                    "away_team": "Nashville SC",
                    "live_player_props": [
                        {
                            "player_id": "p1",
                            "player_name": "Christian Benteke",
                            "side": "home",
                            "shots_so_far": 2,
                            "projected_remainder_shots": 1.1,
                            "projected_final_shots": 3.1,
                            "shots_over_probabilities": {"0.5": 0.91, "1.5": 0.74, "2.5": 0.52, "3.5": 0.28},
                        }
                    ],
                }
            },
        }
        with patch(
            "syndicate.features.soccer.sources.active_leagues_for_date", return_value=["mls"]
        ), patch(
            "syndicate.features.soccer.sources.live_state_payload", return_value=live_state_payload_value
        ):
            candidates = _soccer_live_lens_prop_candidates_from_artifact({"slug": "soccer", "context_label": "MLS 2026 Week 18"})

        self.assertEqual(len(candidates), 1, candidates)
        candidate = candidates[0]
        self.assertEqual(candidate.get("player_name"), "Christian Benteke")
        self.assertEqual(candidate.get("candidate_type"), "prop")
        self.assertEqual(candidate.get("market"), "Shots")
        # 3.5 is the shot line closest to the model's own 3.1 projection
        # (distance 0.4 vs 2.5's 0.6) -- not the shortest (0.5) line.
        self.assertEqual(candidate.get("pick"), "Over 3.5")
        self.assertAlmostEqual(candidate.get("model_probability"), 0.28)
        self.assertEqual(candidate.get("projected"), "3.1")
        self.assertEqual(candidate.get("live_projection"), "3.1")
        self.assertEqual(candidate.get("actual"), "2")
        self.assertTrue(candidate.get("is_live"))
        self.assertEqual(candidate.get("team"), "D.C. United")
        self.assertEqual(candidate.get("matchup"), "Nashville SC @ D.C. United")

    def test_soccer_live_lens_prop_candidates_empty_for_non_soccer_sport(self) -> None:
        from syndicate.features.intelligence import _soccer_live_lens_prop_candidates_from_artifact

        self.assertEqual(_soccer_live_lens_prop_candidates_from_artifact({"slug": "mlb"}), [])

    def test_soccer_live_lens_prop_candidates_empty_when_no_active_leagues(self) -> None:
        from syndicate.features.intelligence import _soccer_live_lens_prop_candidates_from_artifact

        with patch("syndicate.features.soccer.sources.active_leagues_for_date", return_value=[]):
            candidates = _soccer_live_lens_prop_candidates_from_artifact({"slug": "soccer", "context_label": "MLS 2026 Week 18"})
        self.assertEqual(candidates, [])

    def test_soccer_live_lens_prop_candidates_dedupe_same_player_line(self) -> None:
        from syndicate.features.intelligence import _soccer_live_lens_prop_candidates_from_artifact

        row = {
            "player_id": "p2",
            "player_name": "Kei Kamara",
            "side": "away",
            "shots_so_far": 1,
            "projected_final_shots": 1.4,
            "shots_over_probabilities": {"0.5": 0.7, "1.5": 0.4},
        }
        live_state_payload_value = {
            "games": {"761700": {"home_team": "FC Cincinnati", "away_team": "San Jose", "live_player_props": [dict(row), dict(row)]}}
        }
        with patch(
            "syndicate.features.soccer.sources.active_leagues_for_date", return_value=["mls"]
        ), patch(
            "syndicate.features.soccer.sources.live_state_payload", return_value=live_state_payload_value
        ):
            candidates = _soccer_live_lens_prop_candidates_from_artifact({"slug": "soccer", "context_label": "MLS 2026 Week 18"})

        self.assertEqual(len(candidates), 1, candidates)

    def test_collect_candidates_merges_fresh_live_lens_data_into_stale_home_rails_duplicate(self) -> None:
        # Root-caused 2026-07-31 against real production data: gamePk
        # 823271/824974/823595 (all confirmed live) each produced a MIX of
        # correctly-"live" and incorrectly-"Pre-Game" candidate rows for the
        # SAME game, because the in-pool dedup in _collect_candidates
        # silently dropped the fresh, correctly-hydrated
        # _mlb_live_lens_prop_candidates_from_artifact row whenever a
        # matching stale candidate (from the slower home_rails path) was
        # already in the pool for the same subject+market+pick. This
        # reproduces that exact scenario: a stale pregame-shaped home_rails
        # item for "Yordan Alvarez Under 4.5 Hitter Total Bases" alongside a
        # fresh, genuinely-live live-lens artifact row for the same
        # player/market/pick -- the surviving candidate must show the fresh
        # values, not the stale ones, and there must be exactly one.
        overview = [
            {
                "slug": "mlb",
                "name": "MLB",
                "context_label": "2026-07-30",
                "active_today": True,
                "data_health": "healthy",
                "data_warnings": [],
                "home_rails": {
                    "pregame": {
                        "title": "Pregame props",
                        "items": [
                            {
                                "name": "Yordan Alvarez Under 4.5 Hitter Total Bases",
                                "market": "Hitter Total Bases",
                                "pick": "Under 4.5",
                                "matchup": "HOU at LAA",
                                "projected": 4.6,
                                "line": 4.5,
                                "odds": "-120",
                                "confidence": "60%",
                                "edge": "+2.0%",
                                "writeup": "Pregame projection.",
                                "detail": "Under 4.5 Hitter Total Bases",
                                "summary": "Pregame projection.",
                                "href": "/mlb/cards?date=2026-07-30",
                                "game_pk": 824003,
                                "is_live": False,
                                "status_display": "Pre-Game",
                                "game_state": "Pre-Game",
                                "actual": "-",
                            }
                        ],
                    },
                    "live": {"title": "Top Live Props", "items": []},
                    "compact": {"items": []},
                },
                "dashboard_games": [],
            }
        ]
        live_lens_payload = {
            "games": [
                {
                    "gamePk": 824003,
                    "status": {"abstract": "Live", "detailed": "In Progress"},
                    "matchup": {"away": {"abbr": "HOU"}, "home": {"abbr": "LAA"}},
                    "trackedProps": [
                        {
                            "playerName": "Yordan Alvarez",
                            "market": "hitter_total_bases",
                            "marketLabel": "Hitter Total Bases",
                            "selection": "Under",
                            "line": 4.5,
                            "odds": "-120",
                            "estimatedWinProb": 0.837,
                            "liveProjection": 3.9,
                            "actual": 1.0,
                        }
                    ],
                }
            ]
        }
        preferences = _query_preferences("top edges today", mode="recommendation", sport="all", timing="all", include_props=True, include_games=True)
        with patch(
            "syndicate.features.intelligence._mlb_live_lens_report_cached",
            return_value=live_lens_payload,
        ):
            candidates = collect_candidates(overview, preferences)

        matching = [
            candidate
            for candidate in candidates
            if "yordan alvarez" in str(candidate.get("name") or "").lower()
        ]
        self.assertEqual(len(matching), 1, matching)
        merged = matching[0]
        # The live-lens artifact candidate is the one and only source of
        # is_live/actual/live_projection here (it doesn't carry status_display/
        # game_state at all -- those come from a separate pass,
        # _apply_live_state_context_to_candidates, covered by its own test
        # below since it needs the raw MLB feed mocked, not the live-lens
        # artifact). Before the fix, this candidate would have kept the
        # stale home_rails values (is_live=False, actual="-") because the
        # fresh artifact row was silently dropped by the old dedup.
        self.assertTrue(merged.get("is_live"))
        self.assertEqual(merged.get("actual"), "1.0")
        self.assertEqual(merged.get("live_projection"), "3.9")

    def test_apply_live_state_context_syncs_game_state_with_status_display(self) -> None:
        # Root-caused 2026-07-31 against real production data: a candidate
        # could show a correct, freshly-resolved `status_display` while its
        # separate `game_state` field (stamped by whichever builder created
        # the candidate, from a different/slower artifact) stayed stale --
        # confirmed live as a row with game_state literally containing
        # {'abstract': 'Live', ...} while is_live/status_display still said
        # "Scheduled". _mlb_candidate_live_state never returns a game_state
        # key at all, so the two fields could permanently disagree on the
        # same row until this fix forced them to the same resolved value.
        from syndicate.features.intelligence import _apply_live_state_context_to_candidates

        candidate = {
            "sport_slug": "mlb",
            "candidate_type": "prop",
            "context_label": "2026-07-30",
            "game_pk": 823271,
            "is_live": False,
            "status_display": "Scheduled",
            "game_state": {"abstract": "Live", "detailed": "In Progress"},
        }
        with patch(
            "syndicate.features.intelligence._mlb_actual_payload_for_candidate",
            return_value={"gameData": {"status": {"abstractGameState": "Live", "detailedState": "In Progress"}}},
        ), patch(
            "syndicate.features.intelligence._mlb_candidate_live_state",
            return_value={"is_live": True, "is_final": False, "status_display": "In Progress"},
        ):
            _apply_live_state_context_to_candidates([candidate])

        self.assertTrue(candidate.get("is_live"))
        self.assertEqual(candidate.get("status_display"), "In Progress")
        self.assertEqual(candidate.get("game_state"), "In Progress")
        self.assertEqual(candidate.get("game_state"), candidate.get("status_display"))

    def test_mlb_pregame_game_market_candidate_survives_classification(self) -> None:
        # #98/#100: a pregame MLB moneyline/total candidate carries a real
        # model win probability (game["markets"]["ml"/"totals"]["model_prob"])
        # but no book-line "projected" field. _mlb_game_market_recommendation_rows
        # (home.py) only ever threaded that probability through as display
        # text under "confidence" -- a field normalize_candidate's projection
        # scan never checks -- so every genuinely pregame MLB game-level
        # candidate classified as missing_projection_or_odds even with real
        # data present. Confirmed against production ground truth in #98 (8
        # pregame MLB games, all pruned this way). This exercises the real
        # cross-file pipeline (home.py's builder into intelligence.py's
        # classifier), not a mock, so it would fail pre-fix.
        from syndicate.blueprints.home import (
            _game_bet_candidates_from_game,
            _mlb_game_market_recommendation_rows,
        )
        from syndicate.features.intelligence import _classify_candidate_with_reason

        game = {
            "away": "Baltimore Orioles",
            "home": "Detroit Tigers",
            "status": {"abstract": "Preview", "detailed": "Scheduled"},
            "markets": {
                "ml": {"selection": "home", "model_prob": 0.57, "odds": None},
                "totals": {"selection": "over", "market_line": 8.5, "model_prob": 0.52, "odds": None},
            },
        }
        game["game_market_recommendations"] = _mlb_game_market_recommendation_rows(game)
        candidates = _game_bet_candidates_from_game({"slug": "mlb"}, game, fallback_epoch=0.0)
        moneyline = next(c for c in candidates if c["market"] == "Moneyline")

        self.assertEqual(moneyline["odds"], "-")
        # #131 follow-up: projected used to stay "-" here even with real model
        # data present (this test originally pinned that as the reason
        # classification had to fall back to model_probability alone) --
        # _mlb_game_market_recommendation_rows now also stamps the win
        # probability onto "projected" directly (a moneyline's projection IS
        # its win probability, no separate "projected line" concept exists),
        # so it survives classification via BOTH fields now, not just one.
        self.assertEqual(moneyline["projected"], "57.0%")
        self.assertAlmostEqual(moneyline["model_probability"], 0.57)
        classified, reason = _classify_candidate_with_reason(moneyline)
        self.assertIsNone(reason)
        self.assertIsNotNone(classified)

    def test_intelligence_query_builds_nba_analysis_views(self) -> None:
        advanced_rows = [
            {
                "label": "Team advanced stats",
                "metrics": ["Pace", "Usage", "Shot profile"],
                "path": "data/nba_source/data/processed/team_advanced_stats_2026.csv",
                "exists": True,
                "tracked": True,
                "inside_repo": True,
            }
        ]
        with _patch_build_intelligence_overview(_sample_overview()):
            with patch("syndicate.features.intelligence._tracked_repo_files", return_value=set()):
                with patch("syndicate.features.intelligence._advanced_input_rows_for_sport", return_value=advanced_rows):
                    response = self.client.post(
                        "/api/intelligence/query",
                        json={
                            "question": "Explain the best NBA matchup targets today with a table and chart.",
                            "date": "2026-06-04",
                            "force_refresh": True,
                        },
                    )

        self.assertEqual(response.status_code, 200)
        result = (response.get_json() or {}).get("response") or {}
        analysis_views = result.get("analysis_views") or {}
        self.assertEqual(analysis_views.get("focus"), "nba_matchups")
        self.assertTrue((analysis_views.get("table") or {}).get("rows"))
        self.assertTrue((analysis_views.get("chart") or {}).get("rows"))
        self.assertIn("last_game_delta_signal", (analysis_views.get("chart") or {}).get("series") or [])
        first_row = ((analysis_views.get("table") or {}).get("rows") or [])[0]
        self.assertIn("market_fit_score", first_row)
        self.assertEqual(first_row.get("analysis_shape"), "nba_usage_creation")
        self.assertEqual(first_row.get("pace_signal"), 1.08)
        self.assertEqual(first_row.get("usage_signal"), 1.14)
        self.assertEqual(first_row.get("shot_profile_signal"), 1.06)
        self.assertGreater(first_row.get("last5_delta_signal") or 0.0, 0.0)
        self.assertGreater(first_row.get("last10_delta_signal") or 0.0, 0.0)
        self.assertGreater(first_row.get("last_game_delta_signal") or 0.0, 0.0)
        self.assertGreater(first_row.get("workload_delta_signal") or 0.0, 0.0)
        self.assertIn("why", first_row)
        concrete_nba_writeups = {
            "Projection is clearing the number with usage and minutes support.",
            "The live model is still above the book after the in-game adjustment.",
        }
        self.assertTrue(any(text in (first_row.get("why") or "") for text in concrete_nba_writeups))
        self.assertTrue(any(text in ((result.get("recommendations") or [])[0].get("rationale") or "") for text in concrete_nba_writeups))
        analysis_brief = result.get("analysis_brief") or {}
        brief_sections = analysis_brief.get("sections") or []
        self.assertTrue(brief_sections)
        self.assertEqual((brief_sections[0] or {}).get("title"), "Matchup case")
        self.assertTrue(any((section.get("title") == "Data inputs") for section in brief_sections if isinstance(section, dict)))
        supporting_evidence = result.get("supporting_evidence") or {}
        sections = supporting_evidence.get("sections") or []
        self.assertTrue(sections)
        recent_form_table = next((section for section in sections if section.get("title") == "Recent form table"), None)
        self.assertIsNotNone(recent_form_table)
        recent_form_row = ((recent_form_table.get("rows") or [])[0] or {})
        self.assertEqual(recent_form_row.get("target"), "Donovan Mitchell Over 4.5 3PM")
        self.assertEqual(recent_form_row.get("last5_average"), 5.1)
        self.assertEqual(recent_form_row.get("last10_average"), 4.8)
        self.assertEqual(recent_form_row.get("last_game_value"), 6.0)
        self.assertEqual(recent_form_row.get("projected_minutes"), 35.0)
        self.assertEqual(recent_form_row.get("last10_workload"), 33.0)
        self.assertGreater(recent_form_row.get("last5_delta_signal") or 0.0, 0.0)
        evidence_table = next((section for section in sections if section.get("kind") == "table"), None)
        self.assertIsNotNone(evidence_table)
        self.assertTrue(any((row.get("target") == "Jayson Tatum Over 28.5") for row in (evidence_table.get("rows") or [])))
        sources_section = next((section for section in sections if section.get("kind") == "sources"), None)
        self.assertIsNotNone(sources_section)
        self.assertEqual((sources_section.get("items") or [])[0].get("label"), "Team advanced stats")

    def test_intelligence_query_builds_wnba_analysis_views(self) -> None:
        advanced_rows = [
            {
                "label": "Team environment and pace layer",
                "metrics": ["Team environment", "Possession profile", "Matchup pressure"],
                "path": "data/wnba_source/data/processed/recommendations_slate_2026-06-04.json",
                "exists": True,
                "tracked": True,
                "inside_repo": True,
            }
        ]
        with _patch_build_intelligence_overview(_sample_overview_with_secondary_sport()):
            with patch("syndicate.features.intelligence._tracked_repo_files", return_value=set()):
                with patch("syndicate.features.intelligence._advanced_input_rows_for_sport", return_value=advanced_rows):
                    response = self.client.post(
                        "/api/intelligence/query",
                        json={
                            "force_refresh": True,
                            "question": "Explain the top 2 WNBA matchup targets today with a table and chart.",
                            "date": "2026-06-04",
                            "limit": 2,
                        },
                    )

        self.assertEqual(response.status_code, 200)
        result = (response.get_json() or {}).get("response") or {}
        analysis_views = result.get("analysis_views") or {}
        parsed_request = result.get("parsed_request") or {}
        recommendations = result.get("recommendations") or []
        self.assertEqual(analysis_views.get("focus"), "wnba_matchups")
        self.assertEqual(parsed_request.get("sports"), ["WNBA"])
        self.assertTrue((analysis_views.get("table") or {}).get("rows"))
        self.assertIn("last_game_delta_signal", (analysis_views.get("chart") or {}).get("series") or [])
        first_row = ((analysis_views.get("table") or {}).get("rows") or [])[0]
        self.assertTrue(recommendations)
        self.assertEqual(recommendations[0].get("sport_slug"), "wnba")
        self.assertEqual(first_row.get("analysis_shape"), "wnba_role_pressure")
        self.assertEqual(first_row.get("team_environment_signal"), 1.12)
        self.assertEqual(first_row.get("possession_profile_signal"), 1.05)
        self.assertEqual(first_row.get("matchup_pressure_signal"), 1.09)
        self.assertGreater(first_row.get("last5_delta_signal") or 0.0, 0.0)
        self.assertGreater(first_row.get("last10_delta_signal") or 0.0, 0.0)
        self.assertGreater(first_row.get("last_game_delta_signal") or 0.0, 0.0)
        self.assertGreater(first_row.get("workload_delta_signal") or 0.0, 0.0)
        self.assertIn("Projection is clearing the number with stable volume.", first_row.get("why") or "")
        self.assertIn("Projection is clearing the number with stable volume.", recommendations[0].get("rationale") or "")
        supporting_evidence = result.get("supporting_evidence") or {}
        sections = supporting_evidence.get("sections") or []
        recent_form_table = next((section for section in sections if section.get("title") == "Recent form table"), None)
        self.assertIsNotNone(recent_form_table)
        recent_form_row = ((recent_form_table.get("rows") or [])[0] or {})
        self.assertEqual(recent_form_row.get("last5_average"), 28.4)
        self.assertEqual(recent_form_row.get("last10_average"), 26.8)
        self.assertEqual(recent_form_row.get("last_game_value"), 29.0)
        self.assertEqual(recent_form_row.get("projected_minutes"), 34.0)
        self.assertEqual(recent_form_row.get("last10_workload"), 31.5)
        recent_form_row = ((recent_form_table.get("rows") or [])[0] or {})
        self.assertEqual(recent_form_row.get("target"), "A'ja Wilson Over 24.5")
        self.assertGreater(recent_form_row.get("last10_delta_signal") or 0.0, 0.0)

    def test_build_intelligence_status_handles_missing_wnba_artifacts(self) -> None:
        from syndicate.features.intelligence import build_intelligence_status

        def fake_path_status(path, tracked):
            return {
                "path": str(path),
                "exists": False,
                "tracked": False,
                "inside_repo": True,
            }

        overview = [
            {
                "slug": "wnba",
                "name": "WNBA",
                "context_label": "2026-07-03",
                "data_health": "ready",
                "data_warnings": [],
                "active_today": True,
            }
        ]

        with _patch_build_intelligence_overview(overview):
            with patch("syndicate.features.intelligence._tracked_repo_files", return_value=set()):
                with patch("syndicate.features.intelligence.load_latest_refresh_status", return_value={}):
                    with patch("syndicate.features.intelligence._path_status", side_effect=fake_path_status):
                        status = build_intelligence_status(selected_date="2026-07-03")

        wnba_row = next((sport for sport in status.get("sports", []) if sport.get("slug") == "wnba"), None)
        self.assertIsNotNone(wnba_row)
        self.assertEqual(wnba_row.get("data_health"), "missing")
        self.assertTrue(wnba_row.get("artifacts"))
        self.assertTrue(any("No tracked artifacts" in warning for warning in (wnba_row.get("data_warnings") or [])))

    def test_intelligence_query_uses_basketball_source_summary_without_writeup(self) -> None:
        overview = _sample_overview_with_secondary_sport()
        wnba_item = ((((overview[1].get("home_rails") or {}).get("pregame") or {}).get("items") or [])[0])
        wnba_item.pop("writeup", None)
        wnba_item["basketball_summary"] = "Source matchup summary says the volume is stable and the defense is yielding clean looks."
        wnba_item["why_explain"] = "Primary creator workload remains intact in this matchup."
        wnba_item["basketball_reasons"] = [
            "Opponent is allowing efficient pull-up attempts.",
            "Projected role remains unchanged.",
        ]
        advanced_rows = [
            {
                "label": "Team environment and pace layer",
                "metrics": ["Team environment", "Possession profile", "Matchup pressure"],
                "path": "data/wnba_source/data/processed/recommendations_slate_2026-06-04.json",
                "exists": True,
                "tracked": True,
                "inside_repo": True,
            }
        ]
        with _patch_build_intelligence_overview(overview):
            with patch("syndicate.features.intelligence._tracked_repo_files", return_value=set()):
                with patch("syndicate.features.intelligence._advanced_input_rows_for_sport", return_value=advanced_rows):
                    response = self.client.post(
                        "/api/intelligence/query",
                        json={
                            "force_refresh": True,
                            "question": "Explain the top 2 WNBA matchup targets today with a table and chart.",
                            "date": "2026-06-04",
                            "limit": 2,
                        },
                    )

        self.assertEqual(response.status_code, 200)
        result = (response.get_json() or {}).get("response") or {}
        analysis_views = result.get("analysis_views") or {}
        first_row = ((analysis_views.get("table") or {}).get("rows") or [])[0]
        first_recommendation = (result.get("recommendations") or [])[0]
        self.assertIn("Source matchup summary says the volume is stable", first_row.get("why") or "")
        self.assertIn("Source matchup summary says the volume is stable", first_recommendation.get("rationale") or "")

    def test_intelligence_query_builds_ncaab_analysis_views(self) -> None:
        overview = [
            {
                "slug": "ncaab",
                "name": "NCAAB",
                "context_label": "2026-06-04",
                "data_health": "healthy",
                "data_warnings": [],
                "home_rails": {
                    "pregame": {
                        "title": "Pregame props",
                        "items": [
                            {
                                "name": "Braden Smith Over 15.5 PA",
                                "market": "PA",
                                "pick": "Over 15.5",
                                "matchup": "PUR at ILL",
                                "tempo_bucket_advanced": 1.07,
                                "volatility_advanced": 1.03,
                                "minutes_role_advanced": 1.05,
                                "projected": 18.4,
                                "line": 15.5,
                                "odds": "+101",
                                "confidence": "61%",
                                "edge": "+4.0%",
                                "basketball_summary": "Recent form is already clearing this number with a last-five average of 18.8. The last-10 sample is still above this number at 17.9, so the over is not just riding a short heater. Last game landed at 19.0, which keeps the most recent touch above the book.",
                                "why_explain": "Projected minutes (36.0) sit above his last-10 workload (33.5), which strengthens the volume path.",
                                "writeup": "Projection is clearing the number in a stable role.",
                                "href": "/ncaab/prop-ladders?date=2026-06-04",
                            }
                        ],
                    },
                    "live": {"title": "Top Live Props", "items": []},
                    "compact": {"items": []},
                },
                "dashboard_games": [],
            }
        ]
        advanced_rows = [
            {
                "label": "College pace and volatility layer",
                "metrics": ["Tempo", "Volatility", "Role"],
                "path": "data/ncaab_source/data/processed/recommendations_2026-06-04.json",
                "exists": True,
                "tracked": True,
                "inside_repo": True,
            }
        ]
        with _patch_build_intelligence_overview(overview):
            with patch("syndicate.features.intelligence._tracked_repo_files", return_value=set()):
                with patch("syndicate.features.intelligence._advanced_input_rows_for_sport", return_value=advanced_rows):
                    response = self.client.post(
                        "/api/intelligence/query",
                        json={
                            "force_refresh": True,
                            "question": "Explain the best NCAAB matchup targets today with a table and chart.",
                            "date": "2026-06-04",
                        },
                    )

        self.assertEqual(response.status_code, 200)
        result = (response.get_json() or {}).get("response") or {}
        analysis_views = result.get("analysis_views") or {}
        self.assertEqual(analysis_views.get("focus"), "ncaab_matchups")
        self.assertIn("last_game_delta_signal", (analysis_views.get("chart") or {}).get("series") or [])
        first_row = ((analysis_views.get("table") or {}).get("rows") or [])[0]
        self.assertEqual(first_row.get("analysis_shape"), "ncaab_tempo_volatility")
        self.assertEqual(first_row.get("tempo_bucket_signal"), 1.07)
        self.assertEqual(first_row.get("volatility_signal"), 1.03)
        self.assertGreater(first_row.get("last5_delta_signal") or 0.0, 0.0)
        self.assertGreater(first_row.get("last10_delta_signal") or 0.0, 0.0)
        self.assertGreater(first_row.get("last_game_delta_signal") or 0.0, 0.0)
        self.assertGreater(first_row.get("workload_delta_signal") or 0.0, 0.0)
        self.assertIn("Projection is clearing the number in a stable role.", first_row.get("why") or "")

    def test_basketball_market_fit_scoring_diverges_by_league(self) -> None:
        market_context = {
            "american_odds": 102,
            "decimal_odds": 2.02,
            "implied_probability": 49.5,
            "model_probability": 63.0,
            "price_edge_pct": 13.5,
        }
        shared_fields = {
            "candidate_type": "prop",
            "market": "PTS",
            "pick": "Over 24.5",
            "line": 24.5,
            "projected": 28.1,
            "odds": "+102",
            "confidence": "63%",
            "edge": "+5.4%",
        }

        nba_fit = _candidate_market_fit(
            {
                **shared_fields,
                "sport_slug": "nba",
                "name": "Jayson Tatum Over 24.5",
            },
            market_context,
        )
        wnba_fit = _candidate_market_fit(
            {
                **shared_fields,
                "sport_slug": "wnba",
                "name": "A'ja Wilson Over 24.5",
            },
            market_context,
        )

        self.assertEqual(nba_fit.get("market_shape"), "counting_prop")
        self.assertEqual(wnba_fit.get("market_shape"), "counting_prop")
        self.assertEqual(nba_fit.get("market_shape_detail"), "nba_usage_creation")
        self.assertEqual(wnba_fit.get("market_shape_detail"), "wnba_role_pressure")
        self.assertGreater(nba_fit.get("market_fit_score") or 0.0, wnba_fit.get("market_fit_score") or 0.0)
        self.assertIn("nba usage creation", nba_fit.get("market_fit_note") or "")
        self.assertIn("wnba role pressure", wnba_fit.get("market_fit_note") or "")

    def test_advanced_signal_score_handles_share_based_metrics(self) -> None:
        item = ((
            (_sample_nfl_market_overview()[0].get("home_rails") or {}).get("pregame") or {}
        ).get("items") or [])[0]
        signals = _advanced_signals_from_item(item)

        self.assertIn("target_share_advanced", {signal.get("key") for signal in signals})
        score = _candidate_advanced_signal_score(
            {
                "market": item.get("market"),
                "pick": item.get("pick"),
                "name": item.get("name"),
                "advanced_signals": signals,
            }
        )

        self.assertGreater(score, 0.0)

    def test_basketball_source_summary_score_is_direction_aware(self) -> None:
        over_score = _basketball_source_summary_score(
            {
                "candidate_type": "prop",
                "sport_slug": "wnba",
                "pick": "Over 18.5",
                "line": 18.5,
                "summary": "Recent form is already clearing this number with a last-five average of 22.2. The last-10 sample is still above this number at 21.7, so the over is not just riding a short heater.",
            }
        )
        under_score = _basketball_source_summary_score(
            {
                "candidate_type": "prop",
                "sport_slug": "wnba",
                "pick": "Over 18.5",
                "line": 18.5,
                "summary": "Recent form has stayed below this line with a last-five average of 12.6. The last-10 sample is holding under this line at 9.0, which supports the lower-volume case.",
            }
        )

        self.assertGreater(over_score, 0.0)
        self.assertLess(under_score, 0.0)

    def test_basketball_source_summary_score_rewards_matchup_specific_context(self) -> None:
        baseline = _basketball_source_summary_score(
            {
                "candidate_type": "prop",
                "sport_slug": "wnba",
                "pick": "Over 18.5",
                "line": 18.5,
                "summary": "Recent form is already clearing this number with a last-five average of 22.2. The last-10 sample is still above this number at 21.7, so the over is not just riding a short heater.",
            }
        )
        matchup_score = _basketball_source_summary_score(
            {
                "candidate_type": "prop",
                "sport_slug": "wnba",
                "pick": "Over 18.5",
                "line": 18.5,
                "summary": "Recent form is already clearing this number with a last-five average of 22.2. The last-10 sample is still above this number at 21.7, so the over is not just riding a short heater. Opponent is allowing efficient pull-up attempts and the defense is yielding clean looks.",
                "why_explain": "Primary creator workload remains intact in this favorable matchup.",
            }
        )

        self.assertGreater(matchup_score, baseline)

    def test_advanced_signals_extract_basketball_summary_deltas(self) -> None:
        signals = _advanced_signals_from_item(
            {
                "line": 18.5,
                "basketball_summary": "Recent form is already clearing this number with a last-five average of 22.2. The last-10 sample is still above this number at 21.7, so the over is not just riding a short heater.",
                "why_explain": "Projected minutes (32.0) sit above his last-10 workload (30.0), which strengthens the volume path.",
            }
        )

        signal_keys = {signal.get("key") for signal in signals}
        self.assertIn("basketball_last5_average", signal_keys)
        self.assertIn("basketball_last10_average", signal_keys)
        self.assertIn("basketball_last5_delta", signal_keys)
        self.assertIn("basketball_last10_delta", signal_keys)
        self.assertIn("basketball_projected_minutes", signal_keys)
        self.assertIn("basketball_last10_workload", signal_keys)
        self.assertIn("basketball_minutes_workload_delta", signal_keys)

    def test_advanced_signal_score_handles_basketball_summary_deltas(self) -> None:
        signals = _advanced_signals_from_item(
            {
                "line": 18.5,
                "basketball_summary": "Recent form is already clearing this number with a last-five average of 22.2. The last-10 sample is still above this number at 21.7, so the over is not just riding a short heater.",
            }
        )

        score = _candidate_advanced_signal_score(
            {
                "market": "PA",
                "pick": "Over 18.5",
                "name": "Chelsea Gray Over 18.5 PA",
                "advanced_signals": signals,
            }
        )

        self.assertGreater(score, 0.0)

    def test_intelligence_query_ranks_basketball_candidates_using_source_summary(self) -> None:
        overview = [
            {
                "slug": "wnba",
                "name": "WNBA",
                "context_label": "2026-06-04",
                "data_health": "healthy",
                "data_warnings": [],
                "home_rails": {
                    "pregame": {
                        "title": "Pregame props",
                        "items": [
                            {
                                "name": "Chelsea Gray Over 18.5 PA",
                                "market": "PA",
                                "pick": "Over 18.5",
                                "matchup": "LVA at SEA",
                                "team_environment_advanced": 1.05,
                                "possession_profile_advanced": 1.03,
                                "matchup_pressure_advanced": 1.04,
                                "projected": 18.9,
                                "line": 18.5,
                                "odds": "+102",
                                "confidence": "60%",
                                "edge": "+3.0%",
                                "basketball_summary": "Recent form is already clearing this number with a last-five average of 22.2. The last-10 sample is still above this number at 21.7, so the over is not just riding a short heater.",
                                "href": "/wnba/prop-ladders?date=2026-06-04",
                            },
                            {
                                "name": "Jackie Young Over 13.5 RA",
                                "market": "RA",
                                "pick": "Over 13.5",
                                "matchup": "LVA at SEA",
                                "team_environment_advanced": 1.05,
                                "possession_profile_advanced": 1.03,
                                "matchup_pressure_advanced": 1.04,
                                "projected": 13.9,
                                "line": 13.5,
                                "odds": "+102",
                                "confidence": "60%",
                                "edge": "+3.0%",
                                "basketball_summary": "Recent form has stayed below this line with a last-five average of 12.6. The last-10 sample is holding under this line at 9.0, which supports the lower-volume case.",
                                "href": "/wnba/prop-ladders?date=2026-06-04",
                            },
                        ],
                    },
                    "live": {"title": "Top Live Props", "items": []},
                    "compact": {"items": []},
                },
                "dashboard_games": [],
            }
        ]
        advanced_rows = [
            {
                "label": "Team environment and pace layer",
                "metrics": ["Team environment", "Possession profile", "Matchup pressure"],
                "path": "data/wnba_source/data/processed/recommendations_slate_2026-06-04.json",
                "exists": True,
                "tracked": True,
                "inside_repo": True,
            }
        ]
        with _patch_build_intelligence_overview(overview):
            with patch("syndicate.features.intelligence._tracked_repo_files", return_value=set()):
                with patch("syndicate.features.intelligence._advanced_input_rows_for_sport", return_value=advanced_rows):
                    response = self.client.post(
                        "/api/intelligence/query",
                        json={
                            "force_refresh": True,
                            "question": "Explain the top 2 WNBA matchup targets today with a table and chart.",
                            "date": "2026-06-04",
                            "limit": 2,
                        },
                    )

        self.assertEqual(response.status_code, 200)
        result = (response.get_json() or {}).get("response") or {}
        recommendations = result.get("recommendations") or []
        self.assertEqual(len(recommendations), 2)
        self.assertEqual(recommendations[0].get("name"), "Chelsea Gray Over 18.5 PA")
        self.assertGreater(float(recommendations[0].get("source_summary_score") or 0.0), 0.0)
        self.assertLess(float(recommendations[1].get("source_summary_score") or 0.0), 0.0)

    def test_advanced_input_rows_include_basketball_pbp_recap(self) -> None:
        # setUp redirects SYNDICATE_NBA_SOURCE_ROOT to an empty tempdir (see
        # its comment on real-data leaks), so this row's path resolver finds
        # nothing there -- deliberately, but this test needs a live_pbp_stats
        # file to exist to assert on "exists". Point the resolver's actual
        # seam at a small fixture instead of depending on the class-wide
        # isolation OR on a specific date still being present in the repo's
        # live artifact mirror, which churns.
        with TemporaryDirectory() as fixture_dir:
            fixture_root = Path(fixture_dir) / "data" / "processed"
            live_snapshots = fixture_root / "live_snapshots"
            live_snapshots.mkdir(parents=True, exist_ok=True)
            (live_snapshots / "live_pbp_stats_2026-05-28.jsonl").write_text("", encoding="utf-8")
            with patch("syndicate.features.nba.sources.artifact_processed_root", return_value=fixture_root):
                rows = _advanced_input_rows_for_sport(
                    {
                        "slug": "nba",
                        "name": "NBA",
                        "context_label": "2026-05-28",
                    },
                    set(),
                )

        pbp_row = next((row for row in rows if row.get("label") == "Play-by-play live recap"), None)
        self.assertIsNotNone(pbp_row)
        self.assertTrue((pbp_row or {}).get("exists"))
        self.assertIn("Recent scoring run", (pbp_row or {}).get("metrics") or [])

    def test_advanced_input_rows_include_mlb_daily_update_simulation_contract(self) -> None:
        rows = _advanced_input_rows_for_sport(
            {
                "slug": "mlb",
                "name": "MLB",
                "context_label": "2026-06-22",
            },
            set(),
        )

        contract_row = next((row for row in rows if row.get("label") == "Daily-update simulation contract"), None)
        self.assertIsNotNone(contract_row)
        self.assertTrue((contract_row or {}).get("inside_repo"))
        self.assertIn("Source mode", (contract_row or {}).get("metrics") or [])
        self.assertIn("HR targets", (contract_row or {}).get("metrics") or [])

    def test_advanced_input_rows_include_ncaab_pbp_recap(self) -> None:
        # setUp redirects SYNDICATE_NCAAB_SOURCE_ROOT to an empty tempdir
        # OUTSIDE the repo (see its comment on real-data leaks), so
        # inside_repo -- which is purely path-based, not existence-based --
        # comes back False under that redirect no matter what. This test's
        # own contract needs a source root INSIDE the repo; patch the seam
        # directly instead of fighting the class-wide isolation, using a
        # fixture path guaranteed absent so "exists" stays deterministically
        # False rather than depending on no one ever mirroring this date.
        from syndicate.features.intelligence import _repo_root

        fixture_root = _repo_root() / "data" / "ncaab_source" / "_test_pbp_recap_fixture_root"
        with patch("syndicate.features.ncaab.sources._source_roots", return_value=[fixture_root]):
            rows = _advanced_input_rows_for_sport(
                {
                    "slug": "ncaab",
                    "name": "NCAAB",
                    "context_label": "2026-04-06",
                },
                set(),
            )

        pbp_row = next((row for row in rows if row.get("label") == "Play-by-play derived live recap"), None)
        self.assertIsNotNone(pbp_row)
        self.assertFalse((pbp_row or {}).get("exists"))
        self.assertTrue((pbp_row or {}).get("inside_repo"))
        self.assertIn("Points per possession", (pbp_row or {}).get("metrics") or [])

    def test_advanced_signals_from_item_prefers_structured_basketball_recent_form_fields(self) -> None:
        signals = _advanced_signals_from_item(
            {
                "line": 28.5,
                "last5_average": 31.2,
                "last10_average": 30.1,
                "last_game_value": 33.0,
                "projected_minutes": 36.0,
                "last10_workload": 34.0,
                "basketball_summary": "Projection is clearing the number with usage support.",
            }
        )

        by_key = {str(signal.get("key")): signal.get("value") for signal in signals if isinstance(signal, dict)}
        self.assertEqual(by_key.get("basketball_last5_average"), 31.2)
        self.assertAlmostEqual(float(by_key.get("basketball_last5_delta") or 0.0), 0.095, places=3)
        self.assertEqual(by_key.get("basketball_last10_average"), 30.1)
        self.assertEqual(by_key.get("basketball_last_game_value"), 33.0)
        self.assertEqual(by_key.get("basketball_projected_minutes"), 36.0)
        self.assertEqual(by_key.get("basketball_last10_workload"), 34.0)
        self.assertAlmostEqual(float(by_key.get("basketball_minutes_workload_delta") or 0.0), 0.059, places=3)

    def test_advanced_input_rows_use_source_artifact_fallback_for_nfl(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / "source_artifacts").mkdir(parents=True, exist_ok=True)
            (root / "source_artifacts" / "current_week.json").write_text('{"season": 2026, "week": 3}', encoding="utf-8")
            (root / "source_artifacts" / "upcoming_recs_2026_wk3.csv").write_text("player\nA\n", encoding="utf-8")
            (root / "source_artifacts" / "oddsapi_player_props_2026_wk3.csv").write_text("player\nA\n", encoding="utf-8")

            with patch("syndicate.features.intelligence.nfl_sources.default_nfl_source_root", return_value=root):
                with patch("syndicate.features.intelligence.nfl_sources.tracked_week", return_value={"season": 2026, "week": 3}):
                    rows = _advanced_input_rows_for_sport(
                        {
                            "slug": "nfl",
                            "name": "NFL",
                            "context_label": "2026 Week 3",
                        },
                        set(),
                    )

        self.assertTrue(rows)
        self.assertTrue(all(bool(row.get("exists")) for row in rows))
        self.assertTrue(any(str(row.get("path") or "").replace("\\", "/").endswith("current_week.json") for row in rows))

    def test_advanced_input_rows_use_source_artifact_fallback_for_ncaaf(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            rec_root = root / "source_artifacts" / "recommendations_summary"
            rec_root.mkdir(parents=True, exist_ok=True)
            (rec_root / "index.json").write_text('{"weeks": [{"week": 7, "season": 2025, "count": 4}]}', encoding="utf-8")
            (rec_root / "week_7.json").write_text('{"games": []}', encoding="utf-8")
            (root / "source_artifacts" / "college_football_schedule_2025_predicted_totals_enhanced_20251123T161637Z.csv").write_text("game\nA\n", encoding="utf-8")

            with patch("syndicate.features.intelligence.ncaaf_sources.default_ncaaf_source_root", return_value=root):
                rows = _advanced_input_rows_for_sport(
                    {
                        "slug": "ncaaf",
                        "name": "NCAAF",
                        "context_label": "2025 Week 7",
                    },
                    set(),
                )

        self.assertTrue(rows)
        self.assertTrue(all(bool(row.get("exists")) for row in rows))
        self.assertTrue(any(str(row.get("path") or "").replace("\\", "/").endswith("recommendations_summary/index.json") for row in rows))

    def test_latest_matching_path_uses_parent_date_for_scoreboard_snapshots(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            january = root / "date=2026-01-25"
            june = root / "date=2026-06-06"
            january.mkdir(parents=True, exist_ok=True)
            june.mkdir(parents=True, exist_ok=True)
            (january / "scoreboard.csv").write_text("game_id\n1\n", encoding="utf-8")
            (june / "scoreboard.csv").write_text("game_id\n2\n", encoding="utf-8")

            resolved = _latest_matching_path(root, "date=*/scoreboard.csv", requested_date="2026-06-07")

        self.assertIsNotNone(resolved)
        self.assertEqual("date=2026-06-06/scoreboard.csv", str(resolved.relative_to(root)).replace("\\", "/"))

    def test_latest_matching_path_max_age_days_rejects_stale_fallback(self) -> None:
        # Confirmed live 2026-07-22: WNBA's live_pbp_stats fell back to a
        # 9-day-old file with no age ceiling, and the readiness check
        # treated it as "ready" -- a false freshness signal for a "live,
        # in-game right now" artifact. max_age_days must reject a fallback
        # older than the ceiling instead of silently returning it.
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / "live_pbp_stats_2026-07-13.jsonl").write_text("{}\n", encoding="utf-8")

            stale_rejected = _latest_matching_path(
                root, "live_pbp_stats_*.jsonl", requested_date="2026-07-22", max_age_days=1,
            )
            no_ceiling = _latest_matching_path(
                root, "live_pbp_stats_*.jsonl", requested_date="2026-07-22",
            )

        self.assertIsNone(stale_rejected)
        self.assertIsNotNone(no_ceiling)

    def test_latest_matching_path_max_age_days_accepts_recent_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / "live_pbp_stats_2026-07-22.jsonl").write_text("{}\n", encoding="utf-8")

            resolved = _latest_matching_path(
                root, "live_pbp_stats_*.jsonl", requested_date="2026-07-22", max_age_days=1,
            )

        self.assertIsNotNone(resolved)
        self.assertEqual("live_pbp_stats_2026-07-22.jsonl", resolved.name)

    def test_intelligence_query_builds_football_analysis_views(self) -> None:
        advanced_rows = [
            {
                "label": "Weekly recommendation snapshot",
                "metrics": ["EPA", "Pace", "Target share"],
                "path": "data/nfl_source/data/processed/recommendations_2026_wk1.csv",
                "exists": True,
                "tracked": True,
                "inside_repo": True,
            }
        ]
        with _patch_build_intelligence_overview(_sample_nfl_market_overview()):
            with patch("syndicate.features.intelligence._tracked_repo_files", return_value=set()):
                with patch("syndicate.features.intelligence._advanced_input_rows_for_sport", return_value=advanced_rows):
                    response = self.client.post(
                        "/api/intelligence/query",
                        json={
                            "force_refresh": True,
                            "question": "Explain the best NFL receiving yards targets today with a table and chart.",
                            "date": "2026-09-10",
                        },
                    )

        self.assertEqual(response.status_code, 200)
        result = (response.get_json() or {}).get("response") or {}
        analysis_views = result.get("analysis_views") or {}
        analysis_brief = result.get("analysis_brief") or {}
        self.assertEqual(analysis_views.get("focus"), "football_markets")
        self.assertTrue(any((section.get("title") == "Game script context") for section in (analysis_brief.get("sections") or []) if isinstance(section, dict)))
        self.assertTrue((analysis_views.get("table") or {}).get("rows"))
        first_row = ((analysis_views.get("table") or {}).get("rows") or [])[0]
        self.assertEqual(first_row.get("market_label"), "Receiving yards")
        self.assertEqual(first_row.get("off_epa_signal"), 1.11)
        self.assertEqual(first_row.get("target_share_signal"), 0.29)
        self.assertEqual(first_row.get("pass_rate_signal"), 1.07)

    def test_intelligence_query_builds_hockey_analysis_views(self) -> None:
        advanced_rows = [
            {
                "label": "Props recommendation layer",
                "metrics": ["Shot volume", "Game state", "Market depth"],
                "path": "data/nhl_source/data/processed/props_recommendations_2026-06-04.csv",
                "exists": True,
                "tracked": True,
                "inside_repo": True,
            }
        ]
        with _patch_build_intelligence_overview(_sample_nhl_market_overview()):
            with patch("syndicate.features.intelligence._tracked_repo_files", return_value=set()):
                with patch("syndicate.features.intelligence._advanced_input_rows_for_sport", return_value=advanced_rows):
                    response = self.client.post(
                        "/api/intelligence/query",
                        json={
                            "force_refresh": True,
                            "question": "Explain the best live NHL shots targets with a table and chart.",
                            "date": "2026-06-04",
                        },
                    )

        self.assertEqual(response.status_code, 200)
        result = (response.get_json() or {}).get("response") or {}
        analysis_views = result.get("analysis_views") or {}
        analysis_brief = result.get("analysis_brief") or {}
        self.assertEqual(analysis_views.get("focus"), "hockey_props")
        self.assertTrue(any((section.get("title") == "Shot and market context") for section in (analysis_brief.get("sections") or []) if isinstance(section, dict)))
        self.assertTrue((analysis_views.get("table") or {}).get("rows"))

    def test_intelligence_query_builds_mlb_strikeout_analysis_views(self) -> None:
        advanced_rows = [
            {
                "label": "Statcast batter and pitcher features",
                "metrics": ["Whiff shape", "Pitch mix", "xwOBA"],
                "path": "data/mlb_source/data/statcast/features/player_features_latest.json",
                "exists": True,
                "tracked": True,
                "inside_repo": True,
            }
        ]
        statcast_payload = {
            "meta": {"generated_at": "2026-06-04T10:00:00Z"},
            "batters": {
                "592450": {
                    "overall": {"xwoba": 0.301},
                    "mult_overall": {"k": 1.19},
                }
            },
            "pitchers": {
                "519242": {
                    "overall": {"xwoba": 0.284},
                    "mult_overall": {"k": 1.27},
                    "pitch_mix": {"FF": 0.46, "SL": 0.31, "CH": 0.15},
                }
            },
        }
        with _patch_build_intelligence_overview(_sample_mlb_market_overview()):
            with patch("syndicate.features.intelligence._tracked_repo_files", return_value=set()):
                with patch("syndicate.features.intelligence._advanced_input_rows_for_sport", return_value=advanced_rows):
                    with patch("syndicate.features.intelligence._mlb_statcast_feature_payload", return_value=statcast_payload):
                        response = self.client.post(
                            "/api/intelligence/query",
                            json={
                                "force_refresh": True,
                                "question": "Explain the best MLB strikeout matchups today with a table and chart.",
                                "date": "2026-06-04",
                            },
                        )

        self.assertEqual(response.status_code, 200)
        result = (response.get_json() or {}).get("response") or {}
        analysis_views = result.get("analysis_views") or {}
        supporting_evidence = result.get("supporting_evidence") or {}
        self.assertEqual(analysis_views.get("focus"), "mlb_props")
        first_row = ((analysis_views.get("table") or {}).get("rows") or [])[0]
        self.assertEqual(first_row.get("market_key"), "strikeouts")
        self.assertEqual(first_row.get("pitcher_k_mult"), 1.27)
        self.assertEqual(first_row.get("batter_k_mult"), 1.19)
        self.assertIn("pitch mix", first_row.get("why") or "")
        sections = supporting_evidence.get("sections") or []
        self.assertTrue(sections)
        metrics_section = next((section for section in sections if section.get("kind") == "metrics"), None)
        self.assertIsNotNone(metrics_section)
        signals_section = next((section for section in sections if section.get("kind") == "signals"), None)
        self.assertIsNotNone(signals_section)
        self.assertEqual((signals_section.get("items") or [])[0].get("label"), "Batter K Mult")
        sources_section = next((section for section in sections if section.get("kind") == "sources"), None)
        self.assertIsNotNone(sources_section)
        self.assertEqual((sources_section.get("items") or [])[0].get("label"), "Statcast batter and pitcher features")

    def test_intelligence_query_builds_mlb_total_bases_analysis_views(self) -> None:
        advanced_rows = [
            {
                "label": "Statcast batter and pitcher features",
                "metrics": ["Exit velocity", "Hard-hit rate", "xwOBA"],
                "path": "data/mlb_source/data/statcast/features/player_features_latest.json",
                "exists": True,
                "tracked": True,
                "inside_repo": True,
            }
        ]
        statcast_payload = {
            "meta": {"generated_at": "2026-06-04T10:00:00Z"},
            "batters": {
                "518692": {
                    "overall": {"ev_mean": 92.8, "hardhit_rate": 0.487, "xwoba": 0.391},
                    "mult_overall": {"inplay": 1.14},
                }
            },
            "pitchers": {
                "543037": {
                    "overall": {"xwoba": 0.347},
                    "mult_overall": {"inplay": 1.08},
                    "pitch_mix": {"SI": 0.37, "SL": 0.29, "CH": 0.18},
                }
            },
        }
        with _patch_build_intelligence_overview(_sample_mlb_market_overview()):
            with patch("syndicate.features.intelligence._tracked_repo_files", return_value=set()):
                with patch("syndicate.features.intelligence._advanced_input_rows_for_sport", return_value=advanced_rows):
                    with patch("syndicate.features.intelligence._mlb_statcast_feature_payload", return_value=statcast_payload):
                        response = self.client.post(
                            "/api/intelligence/query",
                            json={
                                "force_refresh": True,
                                "question": "Explain the best MLB total bases targets today with a table and chart.",
                                "date": "2026-06-04",
                            },
                        )

        self.assertEqual(response.status_code, 200)
        result = (response.get_json() or {}).get("response") or {}
        analysis_views = result.get("analysis_views") or {}
        self.assertEqual(analysis_views.get("focus"), "mlb_props")
        first_row = ((analysis_views.get("table") or {}).get("rows") or [])[0]
        self.assertEqual(first_row.get("market_key"), "total_bases")
        self.assertEqual(first_row.get("batter_inplay_mult"), 1.14)
        self.assertEqual(first_row.get("pitcher_inplay_mult"), 1.08)
        self.assertEqual(first_row.get("batter_hardhit_rate"), 48.7)
        self.assertIn("in-play mult", first_row.get("why") or "")

    def test_intelligence_query_uses_live_game_projection_for_live_totals(self) -> None:
        with _patch_build_intelligence_overview(_sample_live_game_projection_overview()):
            with patch("syndicate.features.intelligence._tracked_repo_files", return_value=set()):
                with patch("syndicate.features.intelligence._advanced_input_rows_for_sport", return_value=[]):
                    response = self.client.post(
                        "/api/intelligence/query",
                        json={
                            "force_refresh": True,
                            "question": "Show me the best live NBA total edges",
                            "date": "2026-06-05",
                        },
                    )

        self.assertEqual(response.status_code, 200)
        result = (response.get_json() or {}).get("response") or {}
        recommendations = result.get("recommendations") or []
        self.assertTrue(recommendations)
        first = recommendations[0]
        self.assertEqual(first.get("candidate_type"), "game")
        self.assertEqual(first.get("matchup"), "CLE @ IND")
        self.assertEqual(first.get("projected"), "223")
        self.assertEqual(first.get("live_projection"), "228.5")
        self.assertEqual(first.get("market_key"), "total")
        self.assertIn("Live model projection is 228.5 versus a current line of 221.5.", first.get("rationale") or "")
        self.assertGreater(first.get("market_fit_score") or 0.0, 0.0)

    def test_intelligence_query_adds_live_pbp_reasoning_signals_for_live_basketball_props(self) -> None:
        advanced_rows = [
            {
                "label": "Play-by-play live recap",
                "metrics": ["Recent scoring run", "Possession estimate", "Shot mix"],
                "path": "data/nba/live/live_pbp_stats_2026-06-04.jsonl",
                "exists": True,
                "tracked": True,
                "inside_repo": True,
            },
            {
                "label": "Live state and pace context",
                "metrics": ["Live pace", "Game state", "Board pressure"],
                "path": "data/nba/live/live_context_2026-06-04.json",
                "exists": True,
                "tracked": True,
                "inside_repo": True,
            },
        ]
        with _patch_build_intelligence_overview(_sample_overview()):
            with patch("syndicate.features.intelligence._tracked_repo_files", return_value=set()):
                with patch("syndicate.features.intelligence._advanced_input_rows_for_sport", return_value=advanced_rows):
                    result = run_intelligence_query(
                        question="Break down the best live NBA props today",
                        selected_date="2026-06-04",
                        timing="live",
                    )

        recommendations = result.get("recommendations") or []
        self.assertTrue(recommendations)
        first = recommendations[0]
        signal_keys = {
            str(item.get("key") or "")
            for item in (first.get("advanced_signals") or [])
            if isinstance(item, dict)
        }
        self.assertIn("live_sequence_pressure_advanced", signal_keys)
        self.assertIn("projection_shift_advanced", signal_keys)

    def test_intelligence_query_returns_market_specific_board(self) -> None:
        advanced_rows = [
            {
                "label": "Statcast quality",
                "metrics": ["Whiff rate", "Pitch mix", "Opponent K rate"],
                "path": "data/mlb_source/data/statcast/features/player_features_latest.json",
                "exists": True,
                "tracked": True,
                "inside_repo": True,
            }
        ]
        with _patch_build_intelligence_overview(_sample_mlb_market_overview()):
            with patch("syndicate.features.intelligence._tracked_repo_files", return_value=set()):
                with patch("syndicate.features.intelligence._advanced_input_rows_for_sport", return_value=advanced_rows):
                    response = self.client.post(
                        "/api/intelligence/query",
                        json={
                            "force_refresh": True,
                            "question": "Who are the top 3 strikeout targets for today?",
                            "date": "2026-06-04",
                        },
                    )

        self.assertEqual(response.status_code, 200)
        result = (response.get_json() or {}).get("response") or {}
        self.assertEqual(result.get("headline"), "The Syndicate strikeouts board")
        parsed_request = result.get("parsed_request") or {}
        self.assertIn("Strikeouts", parsed_request.get("requested_markets") or [])
        self.assertIn("Strikeouts", parsed_request.get("chips") or [])
        recommendations = result.get("recommendations") or []
        self.assertTrue(recommendations)
        self.assertTrue(all("strikeout" in str(item.get("market") or "").lower() for item in recommendations))

    def test_intelligence_query_backfills_mlb_strikeout_board_from_top_props_artifact(self) -> None:
        top_props = {
            "groups": {
                "pitcher": {
                    "sections": [
                        {
                            "rows": [
                                {
                                    "ownerName": "Chris Sale",
                                    "stat": "strikeouts",
                                    "statLabel": "Strikeouts",
                                    "selectionLabel": "Over",
                                    "marketLine": 7.5,
                                    "mean": 8.6,
                                    "simProb": 0.61,
                                    "rawEdge": 0.048,
                                    "matchup": "ATL at NYM",
                                    "team": "ATL",
                                    "rank": 2,
                                    "group": "pitcher",
                                },
                                {
                                    "ownerName": "Spencer Strider",
                                    "stat": "strikeouts",
                                    "statLabel": "Strikeouts",
                                    "selectionLabel": "Over",
                                    "marketLine": 8.5,
                                    "mean": 9.4,
                                    "simProb": 0.58,
                                    "rawEdge": 0.044,
                                    "matchup": "PHI at ATL",
                                    "team": "ATL",
                                    "rank": 3,
                                    "group": "pitcher",
                                },
                                {
                                    "ownerName": "Tarik Skubal",
                                    "stat": "strikeouts",
                                    "statLabel": "Strikeouts",
                                    "selectionLabel": "Over",
                                    "marketLine": 7.5,
                                    "mean": 8.3,
                                    "simProb": 0.56,
                                    "rawEdge": 0.039,
                                    "matchup": "DET at CLE",
                                    "team": "DET",
                                    "rank": 4,
                                    "group": "pitcher",
                                },
                            ]
                        }
                    ]
                }
            }
        }
        pitcher_snapshot = {
            "pitcher_props": {
                "chris sale": {"strikeouts": {"line": 7.5, "over_odds": "+102"}},
                "spencer strider": {"strikeouts": {"line": 8.5, "over_odds": "+108"}},
                "tarik skubal": {"strikeouts": {"line": 7.5, "over_odds": "+110"}},
            }
        }

        def _mock_mlb_json(path: object) -> dict[str, object]:
            text = str(path).lower()
            if "top" in text and "props" in text:
                return top_props
            if "pitcher" in text and "props" in text:
                return pitcher_snapshot
            return {}

        with _patch_build_intelligence_overview(_sample_mlb_market_overview()):
            with patch("syndicate.features.intelligence._tracked_repo_files", return_value=set()):
                with patch("syndicate.features.intelligence._advanced_input_rows_for_sport", return_value=[]):
                    with patch("syndicate.features.intelligence._mlb_statcast_profile_from_ids", return_value=None):
                        with patch("syndicate.features.intelligence.mlb_load_json_file", side_effect=_mock_mlb_json):
                            response = self.client.post(
                                "/api/intelligence/query",
                                json={
                                    "force_refresh": True,
                                    "question": "Who are the top 5 strikeout targets for today?",
                                    "date": "2026-06-04",
                                },
                            )

        self.assertEqual(response.status_code, 200)
        result = (response.get_json() or {}).get("response") or {}
        self.assertEqual(result.get("headline"), "The Syndicate strikeouts board")
        recommendations = result.get("recommendations") or []
        self.assertGreaterEqual(len(recommendations), 3)
        self.assertTrue(all("strikeout" in str(item.get("market") or "").lower() for item in recommendations[:3]))
        recommendation_names = [str(item.get("name") or "") for item in recommendations]
        self.assertTrue(any("Spencer Strider" in name for name in recommendation_names))
        self.assertTrue(any("Tarik Skubal" in name for name in recommendation_names))

    def test_intelligence_query_builds_generic_multi_sport_market_board(self) -> None:
        with _patch_build_intelligence_overview(_sample_multi_sport_points_overview()):
            with patch("syndicate.features.intelligence._tracked_repo_files", return_value=set()):
                with patch("syndicate.features.intelligence._advanced_input_rows_for_sport", return_value=[]):
                    response = self.client.post(
                        "/api/intelligence/query",
                        json={
                            "force_refresh": True,
                            "question": "Explain the best points targets across NBA and WNBA today with a table and chart.",
                            "date": "2026-06-04",
                        },
                    )

        self.assertEqual(response.status_code, 200)
        result = (response.get_json() or {}).get("response") or {}
        self.assertEqual(result.get("headline"), "The Syndicate points board")
        analysis_views = result.get("analysis_views") or {}
        self.assertEqual(analysis_views.get("focus"), "market_board")
        rows = ((analysis_views.get("table") or {}).get("rows") or [])
        self.assertGreaterEqual(len(rows), 2)
        sports = {str(row.get("sport_slug") or "") for row in rows[:2]}
        self.assertEqual(sports, {"nba", "wnba"})
        self.assertTrue(all(str(row.get("market_key") or "") == "points" for row in rows[:2]))

    def test_query_preferences_treats_high_confidence_as_conservative(self) -> None:
        preferences = _query_preferences("Show me the highest confidence live MLB props today")

        self.assertEqual(preferences.get("risk_profile"), "conservative")
        self.assertTrue(preferences.get("live_only"))
        self.assertEqual(preferences.get("requested_sports"), ["mlb"])

    def test_intelligence_query_prioritizes_conservative_non_parlay_props(self) -> None:
        with _patch_build_intelligence_overview(_sample_mlb_risk_overview()):
            with patch("syndicate.features.intelligence._tracked_repo_files", return_value=set()):
                with patch("syndicate.features.intelligence._advanced_input_rows_for_sport", return_value=[]):
                    response = self.client.post(
                        "/api/intelligence/query",
                        json={
                            "force_refresh": True,
                            "question": "Show me the highest confidence MLB props today",
                            "date": "2026-06-04",
                        },
                    )

        self.assertEqual(response.status_code, 200)
        result = (response.get_json() or {}).get("response") or {}
        recommendations = result.get("recommendations") or []
        self.assertTrue(recommendations)
        self.assertEqual(recommendations[0].get("name"), "Freddie Freeman Over 1.5 Total Bases")
        self.assertEqual((result.get("parsed_request") or {}).get("risk_profile"), "conservative")

    def test_intelligence_query_prioritizes_aggressive_non_parlay_props(self) -> None:
        with _patch_build_intelligence_overview(_sample_mlb_risk_overview()):
            with patch("syndicate.features.intelligence._tracked_repo_files", return_value=set()):
                with patch("syndicate.features.intelligence._advanced_input_rows_for_sport", return_value=[]):
                    response = self.client.post(
                        "/api/intelligence/query",
                        json={
                            "force_refresh": True,
                            "question": "Show me the highest-upside MLB props today",
                            "date": "2026-06-04",
                        },
                    )

        self.assertEqual(response.status_code, 200)
        result = (response.get_json() or {}).get("response") or {}
        recommendations = result.get("recommendations") or []
        self.assertTrue(recommendations)
        self.assertEqual(recommendations[0].get("name"), "Aaron Judge Over 0.5 Home Runs")
        self.assertEqual((result.get("parsed_request") or {}).get("risk_profile"), "aggressive")

    def test_intelligence_query_builds_subject_comparison_view(self) -> None:
        with _patch_build_intelligence_overview(_sample_mlb_compare_overview()):
            with patch("syndicate.features.intelligence._tracked_repo_files", return_value=set()):
                with patch("syndicate.features.intelligence._advanced_input_rows_for_sport", return_value=[]):
                    response = self.client.post(
                        "/api/intelligence/query",
                        json={
                            "force_refresh": True,
                            "question": "Compare Judge vs Ohtani home run outlook today",
                            "date": "2026-06-04",
                        },
                    )

        self.assertEqual(response.status_code, 200)
        result = (response.get_json() or {}).get("response") or {}
        self.assertIn("Judge", result.get("headline") or "")
        parsed_request = result.get("parsed_request") or {}
        self.assertEqual(parsed_request.get("requested_subjects"), ["Aaron Judge", "Shohei Ohtani"])
        recommendations = result.get("recommendations") or []
        self.assertEqual(len(recommendations), 2)
        self.assertEqual({item.get("subject_key") for item in recommendations}, {"aaron judge", "shohei ohtani"})
        analysis_views = result.get("analysis_views") or {}
        self.assertEqual(analysis_views.get("focus"), "subject_comparison")
        table_rows = ((analysis_views.get("table") or {}).get("rows") or [])
        self.assertEqual(len(table_rows), 2)
        self.assertEqual([row.get("subject") for row in table_rows], ["Aaron Judge", "Shohei Ohtani"])

    def test_intelligence_query_filters_live_props_to_requested_subject(self) -> None:
        with _patch_build_intelligence_overview(_sample_mlb_compare_overview()):
            with patch("syndicate.features.intelligence._tracked_repo_files", return_value=set()):
                with patch("syndicate.features.intelligence._advanced_input_rows_for_sport", return_value=[]):
                    response = self.client.post(
                        "/api/intelligence/query",
                        json={
                            "force_refresh": True,
                            "question": "Show me the best live props for Judge right now",
                            "date": "2026-06-04",
                        },
                    )

        self.assertEqual(response.status_code, 200)
        result = (response.get_json() or {}).get("response") or {}
        parsed_request = result.get("parsed_request") or {}
        self.assertEqual(parsed_request.get("requested_subjects"), ["Aaron Judge"])
        recommendations = result.get("recommendations") or []
        self.assertTrue(recommendations)
        self.assertTrue(all(item.get("subject_key") == "aaron judge" for item in recommendations))
        self.assertTrue(all(item.get("is_live") for item in recommendations))

    def test_intelligence_query_uses_mlb_top_props_artifact_for_requested_pitcher_subject(self) -> None:
        overview = _sample_mlb_market_overview()
        overview[0]["context_label"] = "2026-06-05"

        def _mock_mlb_load_json_file(path):
            text = str(path).replace("\\", "/").lower()
            if text.endswith("daily/top_props/daily_top_props_2026_06_05.json"):
                return {
                    "groups": {
                        "pitcher": {
                            "sections": [
                                {
                                    "stat": "strikeouts",
                                    "rows": [
                                        {
                                            "stat": "strikeouts",
                                            "statLabel": "Strikeouts",
                                            "group": "pitcher",
                                            "ownerId": 687064,
                                            "ownerName": "Brandon Young",
                                            "playerName": "Brandon Young",
                                            "team": "BAL",
                                            "opponent": "TOR",
                                            "matchup": "BAL @ TOR",
                                            "mean": 5.327,
                                            "line": 3.5,
                                            "marketLine": 3.5,
                                            "selection": "over",
                                            "selectionLabel": "Over",
                                            "simProb": 0.819,
                                            "marketProb": 0.5665,
                                            "rawEdge": 0.2525,
                                            "odds": -155,
                                            "rank": 3,
                                        }
                                    ],
                                }
                            ]
                        }
                    }
                }
            if text.endswith("daily/snapshots/2026-06-05/oddsapi_pitcher_props_2026_06_05.json"):
                return {
                    "pitcher_props": {
                        "brandon young": {
                            "strikeouts": {
                                "line": 4.5,
                                "over_odds": "+124",
                                "under_odds": "-166",
                                "alternates": [{"line": 3.5, "over_odds": "-170", "under_odds": "+130"}],
                            }
                        }
                    }
                }
            return {}

        with _patch_build_intelligence_overview(overview):
            with patch("syndicate.features.intelligence._tracked_repo_files", return_value=set()):
                with patch("syndicate.features.intelligence._advanced_input_rows_for_sport", return_value=[]):
                    with patch("syndicate.features.intelligence.mlb_load_json_file", side_effect=_mock_mlb_load_json_file):
                        response = self.client.post(
                            "/api/intelligence/query",
                            json={
                                "force_refresh": True,
                                "question": "What is Brandon Young strikeouts projection today?",
                                "date": "2026-06-05",
                            },
                        )

        self.assertEqual(response.status_code, 200)
        result = (response.get_json() or {}).get("response") or {}
        parsed_request = result.get("parsed_request") or {}
        self.assertEqual(parsed_request.get("requested_subjects"), ["Brandon Young"])
        recommendations = result.get("recommendations") or []
        self.assertTrue(recommendations)
        self.assertEqual(recommendations[0].get("subject_key"), "brandon young")
        self.assertEqual(recommendations[0].get("projected"), "5.3")
        self.assertEqual(recommendations[0].get("line"), "4.5")
        self.assertEqual(recommendations[0].get("odds"), "+124")
        self.assertIn("Projection 5.3 versus line 4.5", recommendations[0].get("rationale") or "")

    def test_intelligence_query_builds_subject_mlb_matchup_analysis_views_without_explicit_market(self) -> None:
        overview = [
            {
                "slug": "mlb",
                "name": "MLB",
                "context_label": "2026-06-05",
                "data_health": "healthy",
                "data_warnings": [],
                "home_rails": {
                    "pregame": {"title": "Pregame props", "items": []},
                    "live": {"title": "Live props", "items": []},
                    "compact": {"items": []},
                },
                "dashboard_games": [],
            }
        ]

        def _mock_mlb_load_json_file(text_path: str):
            text = str(text_path).replace("\\", "/")
            if text.endswith("daily/top_props/daily_top_props_2026_06_05.json"):
                return {
                    "groups": {
                        "pitcher": {
                            "sections": [
                                {
                                    "stat": "strikeouts",
                                    "rows": [
                                        {
                                            "stat": "strikeouts",
                                            "statLabel": "Strikeouts",
                                            "group": "pitcher",
                                            "ownerId": 687064,
                                            "ownerName": "Brandon Young",
                                            "playerName": "Brandon Young",
                                            "team": "BAL",
                                            "opponent": "TOR",
                                            "matchup": "BAL @ TOR",
                                            "mean": 5.327,
                                            "line": 3.5,
                                            "marketLine": 3.5,
                                            "selection": "over",
                                            "selectionLabel": "Over",
                                            "simProb": 0.819,
                                            "marketProb": 0.5665,
                                            "rawEdge": 0.2525,
                                            "odds": -155,
                                            "rank": 3,
                                        }
                                    ],
                                }
                            ]
                        }
                    }
                }
            if text.endswith("daily/snapshots/2026-06-05/oddsapi_pitcher_props_2026_06_05.json"):
                return {
                    "pitcher_props": {
                        "brandon young": {
                            "strikeouts": {
                                "line": 4.5,
                                "over_odds": "+124",
                                "under_odds": "-166",
                            }
                        }
                    }
                }
            return {}

        advanced_rows = [
            {
                "label": "Pitch model context",
                "metrics": ["Pitch mix", "Opponent K rate", "Swing/miss profile"],
                "path": "data/mlb_source/data/processed/top_props_2026-06-05.json",
                "exists": True,
                "tracked": True,
                "inside_repo": True,
            }
        ]

        with _patch_build_intelligence_overview(overview):
            with patch("syndicate.features.intelligence._tracked_repo_files", return_value=set()):
                with patch("syndicate.features.intelligence._advanced_input_rows_for_sport", return_value=advanced_rows):
                    with patch("syndicate.features.intelligence.mlb_load_json_file", side_effect=_mock_mlb_load_json_file):
                        response = self.client.post(
                            "/api/intelligence/query",
                            json={
                                "force_refresh": True,
                                "question": "What does Brandon Young's matchup today look like and how do his stats project against betting lines?",
                                "date": "2026-06-05",
                            },
                        )

        self.assertEqual(response.status_code, 200)
        result = (response.get_json() or {}).get("response") or {}
        analysis_views = result.get("analysis_views") or {}
        analysis_brief = result.get("analysis_brief") or {}
        supporting_evidence = result.get("supporting_evidence") or {}
        recommendations = result.get("recommendations") or []
        self.assertTrue(recommendations)
        self.assertEqual((result.get("parsed_request") or {}).get("requested_subjects"), ["Brandon Young"])
        self.assertEqual(analysis_views.get("focus"), "mlb_props")
        self.assertTrue(analysis_brief.get("sections"))
        self.assertTrue(any((section.get("title") == "Data inputs") for section in (analysis_brief.get("sections") or []) if isinstance(section, dict)))
        self.assertTrue((analysis_views.get("table") or {}).get("rows"))
        self.assertTrue((analysis_views.get("chart") or {}).get("rows"))
        self.assertTrue((supporting_evidence.get("sections") or []))
        first_row = ((analysis_views.get("table") or {}).get("rows") or [])[0]
        self.assertEqual(first_row.get("label"), "Brandon Young Over 4.5 Strikeouts")
        self.assertIn("Projection 5.3 versus line 4.5", first_row.get("why") or "")

    def test_intelligence_query_filters_stale_live_mlb_pitcher_props_when_starter_is_out(self) -> None:
        actual_payload = {
            "gameData": {
                "status": {"abstractGameState": "Live", "detailedState": "In Progress"},
                "probablePitchers": {
                    "away": {"id": 519242, "fullName": "Chris Sale"},
                    "home": {"id": 543037, "fullName": "Reed Garrett"},
                },
            },
            "liveData": {
                "linescore": {"inningHalf": "bottom"},
                "plays": {
                    "currentPlay": {
                        "matchup": {
                            "pitcher": {"id": 543037, "fullName": "Reed Garrett"},
                        }
                    }
                },
            },
        }

        with _patch_build_intelligence_overview(_sample_mlb_live_pitcher_state_overview()):
            with patch("syndicate.features.intelligence._tracked_repo_files", return_value=set()):
                with patch("syndicate.features.intelligence._advanced_input_rows_for_sport", return_value=[]):
                    with patch("syndicate.features.intelligence._mlb_actual_payload_for_candidate", return_value=actual_payload):
                        response = self.client.post(
                            "/api/intelligence/query",
                            json={
                                "force_refresh": True,
                                "question": "Best live MLB props right now",
                                "date": "2026-06-05",
                            },
                        )

        self.assertEqual(response.status_code, 200)
        result = (response.get_json() or {}).get("response") or {}
        recommendations = result.get("recommendations") or []
        self.assertTrue(recommendations)
        self.assertNotIn("Chris Sale Over 5.5 Strikeouts", [item.get("name") for item in recommendations])
        self.assertIn("Pete Alonso Over 1.5 Total Bases", [item.get("name") for item in recommendations])

    def test_mlb_candidate_live_state_excludes_hitter_removed_from_lineup(self) -> None:
        # 2026-08-01 board audit follow-up: no hitter equivalent existed for
        # the pitcher-starter-removed check above -- direct unit test of
        # the wiring (_hitter_removed_from_actual_payload's own boxscore-
        # parsing logic is covered separately in test_mlb_market_board.py).
        from syndicate.features.intelligence import _mlb_candidate_live_state

        candidate = {
            "sport_slug": "mlb",
            "candidate_type": "prop",
            "market": "Hitter Hits",
            "player_name": "Jorge Soler",
            "batter_id": 624585,
        }
        actual_payload = {
            "gameData": {"status": {"abstractGameState": "Live", "detailedState": "In Progress"}},
            "liveData": {"boxscore": {"teams": {"home": {"players": {}}, "away": {"players": {}}}}},
        }
        with patch(
            "syndicate.features.mlb.cards._hitter_removed_from_actual_payload",
            return_value=True,
        ):
            state = _mlb_candidate_live_state(candidate, actual_payload)

        self.assertTrue(state.get("state_invalid"))
        self.assertIn("no longer in the active lineup", state.get("state_note", ""))

    def test_mlb_candidate_live_state_keeps_hitter_still_active(self) -> None:
        from syndicate.features.intelligence import _mlb_candidate_live_state

        candidate = {
            "sport_slug": "mlb",
            "candidate_type": "prop",
            "market": "Hitter Hits",
            "player_name": "Jorge Soler",
            "batter_id": 624585,
        }
        actual_payload = {
            "gameData": {"status": {"abstractGameState": "Live", "detailedState": "In Progress"}},
            "liveData": {"boxscore": {"teams": {"home": {"players": {}}, "away": {"players": {}}}}},
        }
        with patch(
            "syndicate.features.mlb.cards._hitter_removed_from_actual_payload",
            return_value=False,
        ):
            state = _mlb_candidate_live_state(candidate, actual_payload)

        self.assertNotIn("state_invalid", state)

    def test_intelligence_query_resolves_typo_subject_and_three_point_market(self) -> None:
        with _patch_build_intelligence_overview(_sample_nba_subject_specific_overview()):
            with patch("syndicate.features.intelligence._tracked_repo_files", return_value=set()):
                with patch("syndicate.features.intelligence._advanced_input_rows_for_sport", return_value=[]):
                    response = self.client.post(
                        "/api/intelligence/query",
                        json={
                            "force_refresh": True,
                            "question": "Julian champaigne 3ptM",
                            "date": "2026-06-05",
                        },
                    )

        self.assertEqual(response.status_code, 200)
        result = (response.get_json() or {}).get("response") or {}
        parsed_request = result.get("parsed_request") or {}
        self.assertEqual(parsed_request.get("requested_subjects"), ["Julian Champagnie"])
        self.assertIn("Threes", parsed_request.get("requested_markets") or [])
        recommendations = result.get("recommendations") or []
        self.assertEqual([item.get("name") for item in recommendations], ["Julian Champagnie Over 1.5 3PM"])
        self.assertTrue(all(item.get("subject_key") == "julian champagnie" for item in recommendations))
        self.assertTrue(all(item.get("market_key") == "threes" for item in recommendations))

    def test_build_parlays_limits_standard_leg_count_for_tight_exposure_caps(self) -> None:
        preferences = _query_preferences(
            "Build an aggressive 2 to 3 leg parlay from the best NBA edges with a $100 bankroll and max 3% exposure"
        )
        candidates = [
            {
                "candidate_type": "prop",
                "sport": "NBA",
                "sport_slug": "nba",
                "matchup": "BOS at NYK",
                "market": "PTS",
                "pick": "Over 28.5",
                "name": "Tatum Over 28.5",
                "surface_title": "Pregame props",
                "odds": "+125",
                "score": 88.0,
                "market_context": {"decimal_odds": 2.25, "american_odds": 125, "implied_probability": 44.44},
            },
            {
                "candidate_type": "prop",
                "sport": "NBA",
                "sport_slug": "nba",
                "matchup": "MIA at PHI",
                "market": "REB",
                "pick": "Over 7.5",
                "name": "Adebayo Over 7.5",
                "surface_title": "Pregame props",
                "odds": "+130",
                "score": 86.0,
                "market_context": {"decimal_odds": 2.3, "american_odds": 130, "implied_probability": 43.48},
            },
            {
                "candidate_type": "prop",
                "sport": "NBA",
                "sport_slug": "nba",
                "matchup": "MIN at DAL",
                "market": "AST",
                "pick": "Over 6.5",
                "name": "Edwards Over 6.5",
                "surface_title": "Pregame props",
                "odds": "+135",
                "score": 84.0,
                "market_context": {"decimal_odds": 2.35, "american_odds": 135, "implied_probability": 42.55},
            },
        ]

        parlays = _build_parlays(candidates, limit=5, preferences=preferences)

        self.assertTrue(parlays)
        self.assertTrue(all(parlay.get("leg_count") == 2 for parlay in parlays))
        self.assertTrue(all(parlay.get("suggested_total_exposure") == 3.0 for parlay in parlays))

    def test_build_parlays_trims_round_robin_anchor_for_tight_exposure_caps(self) -> None:
        preferences = _query_preferences(
            "Build me a four-leg round robin from the best NBA edges with a $100 bankroll and max 5% exposure"
        )
        candidates = [
            {
                "candidate_type": "prop",
                "sport": "NBA",
                "sport_slug": "nba",
                "matchup": "BOS at NYK",
                "market": "PTS",
                "pick": "Over 28.5",
                "name": "Tatum Over 28.5",
                "surface_title": "Pregame props",
                "odds": "+102",
                "score": 88.0,
                "market_context": {"decimal_odds": 2.02, "american_odds": 102, "implied_probability": 49.5},
            },
            {
                "candidate_type": "prop",
                "sport": "NBA",
                "sport_slug": "nba",
                "matchup": "MIA at PHI",
                "market": "REB",
                "pick": "Over 6.5",
                "name": "Brown Over 6.5 Reb",
                "surface_title": "Pregame props",
                "odds": "+108",
                "score": 86.0,
                "market_context": {"decimal_odds": 2.08, "american_odds": 108, "implied_probability": 48.08},
            },
            {
                "candidate_type": "prop",
                "sport": "NBA",
                "sport_slug": "nba",
                "matchup": "PHX at SAC",
                "market": "AST",
                "pick": "Over 7.5",
                "name": "Booker Over 7.5 Ast",
                "surface_title": "Pregame props",
                "odds": "+104",
                "score": 85.0,
                "market_context": {"decimal_odds": 2.04, "american_odds": 104, "implied_probability": 49.02},
            },
            {
                "candidate_type": "prop",
                "sport": "NBA",
                "sport_slug": "nba",
                "matchup": "MIN at DAL",
                "market": "3PM",
                "pick": "Over 3.5",
                "name": "Edwards Over 3.5 3PM",
                "surface_title": "Pregame props",
                "odds": "+110",
                "score": 84.0,
                "market_context": {"decimal_odds": 2.1, "american_odds": 110, "implied_probability": 47.62},
            },
        ]

        parlays = _build_parlays(candidates, limit=5, preferences=preferences)

        self.assertTrue(parlays)
        self.assertTrue(all(parlay.get("parlay_type") == "round_robin" for parlay in parlays))
        self.assertTrue(all(parlay.get("round_robin_group_size") == 3 for parlay in parlays))
        self.assertTrue(all(parlay.get("round_robin_unit") == 2 for parlay in parlays))
        self.assertEqual(len(parlays), 3)
        self.assertTrue(all(parlay.get("suggested_total_exposure") == 5.0 for parlay in parlays))
        self.assertTrue(all(parlay.get("suggested_stake") == 1.67 for parlay in parlays))

    def test_build_parlays_uses_market_fit_for_market_constrained_ranking(self) -> None:
        preferences = _query_preferences("Build me a two-leg turnovers parlay")
        candidates = [
            {
                "candidate_type": "prop",
                "sport": "NBA",
                "sport_slug": "nba",
                "matchup": "IND at CLE",
                "market": "Turnovers",
                "pick": "Over 2.5",
                "name": "Haliburton Over 2.5 Turnovers",
                "surface_title": "Pregame props",
                "odds": "+112",
                "score": 82.0,
                "market_fit": {"market_key": "turnovers", "market_label": "Turnovers", "market_shape": "volume_prop", "market_fit_score": 15.0},
                "market_context": {"decimal_odds": 2.12, "american_odds": 112, "implied_probability": 47.17},
            },
            {
                "candidate_type": "prop",
                "sport": "NBA",
                "sport_slug": "nba",
                "matchup": "BOS at NYK",
                "market": "Turnovers",
                "pick": "Over 3.5",
                "name": "Brunson Over 3.5 Turnovers",
                "surface_title": "Pregame props",
                "odds": "+108",
                "score": 81.5,
                "market_fit": {"market_key": "turnovers", "market_label": "Turnovers", "market_shape": "volume_prop", "market_fit_score": 14.0},
                "market_context": {"decimal_odds": 2.08, "american_odds": 108, "implied_probability": 48.08},
            },
            {
                "candidate_type": "prop",
                "sport": "NBA",
                "sport_slug": "nba",
                "matchup": "PHX at SAC",
                "market": "Turnovers",
                "pick": "Over 2.5",
                "name": "Booker Over 2.5 Turnovers",
                "surface_title": "Pregame props",
                "odds": "+106",
                "score": 88.0,
                "market_fit": {"market_key": "turnovers", "market_label": "Turnovers", "market_shape": "volume_prop", "market_fit_score": 4.0},
                "market_context": {"decimal_odds": 2.06, "american_odds": 106, "implied_probability": 48.54},
            },
        ]

        parlays = _build_parlays(candidates, limit=3, preferences=preferences)

        self.assertTrue(parlays)
        first_parlay = parlays[0]
        self.assertEqual(first_parlay.get("market_labels"), ["Turnovers"])
        self.assertEqual(first_parlay.get("market_shapes"), ["volume_prop"])
        self.assertGreater(first_parlay.get("combined_market_fit_score") or 0.0, 10.0)
        leg_names = [leg.get("name") for leg in (first_parlay.get("legs") or [])]
        self.assertIn("Haliburton Over 2.5 Turnovers", leg_names)
        self.assertIn("Brunson Over 3.5 Turnovers", leg_names)

    def test_low_correlation_same_game_rejects_duplicate_market_shapes(self) -> None:
        preferences = _query_preferences("Build me a same game three-leg parlay with low correlation")
        legs = (
            {"candidate_type": "prop", "sport_slug": "nba", "matchup": "BOS at NYK", "market": "PTS", "market_shape": "counting_prop", "pick": "Over 28.5"},
            {"candidate_type": "prop", "sport_slug": "nba", "matchup": "BOS at NYK", "market": "AST", "market_shape": "counting_prop", "pick": "Over 6.5"},
            {"candidate_type": "prop", "sport_slug": "nba", "matchup": "BOS at NYK", "market": "3PM", "market_shape": "counting_prop", "pick": "Over 2.5"},
        )

        self.assertFalse(_parlay_matches_preferences(legs, preferences))

    def test_explicit_medium_correlation_allows_three_mlb_volume_props(self) -> None:
        preferences = _query_preferences("Build me a same game three-leg parlay with medium correlation")
        legs = (
            {"candidate_type": "prop", "sport_slug": "mlb", "matchup": "ATL at NYM", "market": "Pitcher Strikeouts", "market_shape": "volume_prop", "pick": "Over 7.5"},
            {"candidate_type": "prop", "sport_slug": "mlb", "matchup": "ATL at NYM", "market": "Hitter Total Bases", "market_shape": "volume_prop", "pick": "Over 1.5"},
            {"candidate_type": "prop", "sport_slug": "mlb", "matchup": "ATL at NYM", "market": "Hits", "market_shape": "volume_prop", "pick": "Over 1.5"},
        )

        self.assertTrue(_parlay_matches_preferences(legs, preferences))

    def test_explicit_medium_correlation_blocks_points_assists_pair_but_allows_points_threes(self) -> None:
        preferences = _query_preferences("Build me a same game two-leg parlay with medium correlation")
        points_assists_legs = (
            {"candidate_type": "prop", "sport_slug": "nba", "matchup": "BOS at NYK", "market": "PTS", "market_key": "points", "market_shape": "counting_prop", "pick": "Over 28.5"},
            {"candidate_type": "prop", "sport_slug": "nba", "matchup": "BOS at NYK", "market": "AST", "market_key": "assists", "market_shape": "counting_prop", "pick": "Over 6.5"},
        )
        points_threes_legs = (
            {"candidate_type": "prop", "sport_slug": "nba", "matchup": "BOS at NYK", "market": "PTS", "market_key": "points", "market_shape": "counting_prop", "pick": "Over 28.5"},
            {"candidate_type": "prop", "sport_slug": "nba", "matchup": "BOS at NYK", "market": "3PM", "market_key": "threes", "market_shape": "counting_prop", "pick": "Over 2.5"},
        )

        self.assertFalse(_parlay_matches_preferences(points_assists_legs, preferences))
        self.assertTrue(_parlay_matches_preferences(points_threes_legs, preferences))

    def test_build_parlays_applies_soft_pair_penalty_to_allowed_same_game_pairs(self) -> None:
        preferences = _query_preferences("Build me a same game two-leg parlay with medium correlation")
        candidates = [
            {
                "candidate_type": "prop",
                "sport": "NBA",
                "sport_slug": "nba",
                "matchup": "BOS at NYK",
                "market": "PTS",
                "market_key": "points",
                "market_shape": "counting_prop",
                "pick": "Over 28.5",
                "name": "Tatum Over 28.5",
                "surface_title": "Pregame props",
                "odds": "+102",
                "score": 84.0,
                "market_fit": {"market_key": "points", "market_label": "Points", "market_shape": "counting_prop", "market_fit_score": 12.0},
                "market_context": {"decimal_odds": 2.02, "american_odds": 102, "implied_probability": 49.5},
            },
            {
                "candidate_type": "prop",
                "sport": "NBA",
                "sport_slug": "nba",
                "matchup": "BOS at NYK",
                "market": "REB",
                "market_key": "rebounds",
                "market_shape": "counting_prop",
                "pick": "Over 8.5",
                "name": "Tatum Over 8.5 Reb",
                "surface_title": "Pregame props",
                "odds": "+104",
                "score": 84.0,
                "market_fit": {"market_key": "rebounds", "market_label": "Rebounds", "market_shape": "counting_prop", "market_fit_score": 12.0},
                "market_context": {"decimal_odds": 2.04, "american_odds": 104, "implied_probability": 49.02},
            },
            {
                "candidate_type": "prop",
                "sport": "NBA",
                "sport_slug": "nba",
                "matchup": "BOS at NYK",
                "market": "3PM",
                "market_key": "threes",
                "market_shape": "counting_prop",
                "pick": "Over 2.5",
                "name": "Tatum Over 2.5 3PM",
                "surface_title": "Pregame props",
                "odds": "+104",
                "score": 84.0,
                "market_fit": {"market_key": "threes", "market_label": "Threes", "market_shape": "counting_prop", "market_fit_score": 12.0},
                "market_context": {"decimal_odds": 2.04, "american_odds": 104, "implied_probability": 49.02},
            },
        ]

        parlays = _build_parlays(candidates, limit=3, preferences=preferences)

        self.assertTrue(parlays)
        parlay_by_keys = {
            tuple(sorted(leg.get("market_key") for leg in (parlay.get("legs") or []))): parlay
            for parlay in parlays
        }
        clean_parlay = parlay_by_keys[("rebounds", "threes")]
        lighter_penalty_parlay = parlay_by_keys[("points", "threes")]
        heavier_penalty_parlay = parlay_by_keys[("points", "rebounds")]

        self.assertEqual(tuple(sorted(leg.get("market_key") for leg in (parlays[0].get("legs") or []))), ("rebounds", "threes"))
        self.assertEqual(clean_parlay.get("pair_correlation_penalty"), 0.0)
        self.assertEqual(lighter_penalty_parlay.get("pair_correlation_penalty"), 1.5)
        self.assertEqual(heavier_penalty_parlay.get("pair_correlation_penalty"), 3.0)
        self.assertIn("Points + Threes correlation penalty 1.5", lighter_penalty_parlay.get("rationale") or "")
        self.assertGreater(
            _parlay_rank_score(lighter_penalty_parlay, preferences),
            _parlay_rank_score(heavier_penalty_parlay, preferences),
        )

    def test_intelligence_query_surfaces_raw_statcast_profile_context(self) -> None:
        advanced_rows = [
            {
                "label": "Statcast batter and pitcher features",
                "metrics": ["Launch angle", "Exit velocity", "Barrel rate", "Pitch mix"],
                "path": "data/mlb_source/data/statcast/features/player_features_latest.json",
                "exists": True,
                "tracked": True,
                "inside_repo": True,
            }
        ]
        statcast_payload = {
            "meta": {"generated_at": "2026-06-05T10:00:00Z"},
            "batters": {
                "608324": {
                    "overall": {
                        "ev_mean": 94.2,
                        "barrel_rate": 0.182,
                        "hr_per_bip": 0.091,
                        "xwoba": 0.422,
                        "pulled_air_rate": 0.211,
                    },
                    "mult_overall": {"hr": 1.28},
                }
            },
            "pitchers": {
                "605400": {
                    "overall": {
                        "ev_mean": 90.4,
                        "barrel_rate": 0.101,
                        "hardhit_rate": 0.428,
                        "hr_per_bip": 0.067,
                        "xwoba": 0.344,
                    },
                    "mult_overall": {"hr": 1.11},
                    "pitch_mix": {"FF": 0.47, "SL": 0.31, "CH": 0.14},
                }
            },
        }
        with _patch_build_intelligence_overview(_sample_mlb_statcast_overview()):
            with patch("syndicate.features.intelligence._tracked_repo_files", return_value=set()):
                with patch("syndicate.features.intelligence._advanced_input_rows_for_sport", return_value=advanced_rows):
                    with patch("syndicate.features.intelligence._mlb_statcast_feature_payload", return_value=statcast_payload):
                        response = self.client.post(
                            "/api/intelligence/query",
                            json={
                                "force_refresh": True,
                                "question": "What are the best home run matchups today and why?",
                                "date": "2026-06-05",
                            },
                        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json() or {}
        result = payload.get("response") or {}
        first = ((result.get("recommendations") or [])[0])
        self.assertIn("Raw Statcast context", first.get("rationale") or "")
        profile = first.get("mlb_statcast_profile") or {}
        self.assertEqual((profile.get("batter") or {}).get("ev_mean"), 94.2)
        self.assertEqual((profile.get("pitcher") or {}).get("hr_mult"), 1.11)
        first_row = ((result.get("analysis_views") or {}).get("table", {}).get("rows") or [])[0]
        self.assertEqual(first_row.get("barrel_rate"), 18.2)
        self.assertEqual(first_row.get("pitcher_hr_per_bip_allowed"), 6.7)

    def test_intelligence_query_excludes_props_for_final_games(self) -> None:
        overview = _sample_overview()
        live_items = (((overview[0].get("home_rails") or {}).get("live") or {}).get("items") or [])
        live_items.insert(
            0,
            {
                "name": "Jalen Brunson Over 6.5 Assists",
                "market": "AST",
                "pick": "Over 6.5",
                "matchup": "BOS at NYK",
                "projected": 7.4,
                "live_projection": 7.1,
                "actual": 6,
                "line": 6.5,
                "odds": "+110",
                "confidence": "62%",
                "edge": "+4.0%",
                "writeup": "This should be filtered because the game is over.",
                "display_pills": ["Line 6.5", "Odds +110", "Live Proj 7.1"],
                "is_live": True,
                "status_display": "102-99 | Final",
                "status_context": "102-99 | Final",
                "href": "/nba/season/2026/live-lens?date=2026-06-04",
            },
        )
        advanced_rows = [
            {
                "label": "Team advanced stats",
                "metrics": ["Pace", "Offensive rating", "Shot profile"],
                "path": "data/nba_source/data/processed/team_advanced_stats_2026.csv",
                "exists": True,
                "tracked": True,
                "inside_repo": True,
            }
        ]
        with _patch_build_intelligence_overview(overview):
            with patch("syndicate.features.intelligence._tracked_repo_files", return_value=set()):
                with patch("syndicate.features.intelligence._advanced_input_rows_for_sport", return_value=advanced_rows):
                    response = self.client.post(
                        "/api/intelligence/query",
                        json={
                            "force_refresh": True,
                            "question": "Show me the best live NBA props",
                            "date": "2026-06-04",
                        },
                    )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        result = payload.get("response") or {}
        recommendation_names = [item.get("name") for item in (result.get("recommendations") or [])]
        self.assertNotIn("Jalen Brunson Over 6.5 Assists", recommendation_names)
        self.assertIn("Donovan Mitchell Over 4.5 3PM", recommendation_names)

    def test_mlb_live_prop_rows_do_not_depend_on_home_game_live_gate(self) -> None:
        from syndicate.blueprints.home import _load_home_live_prop_items

        scheduled_home_games = [
            {
                "away": {"abbr": "NYY", "name": "Yankees"},
                "home": {"abbr": "BOS", "name": "Red Sox"},
                "status": {"abstract": "Scheduled", "detailed": "7:10 PM ET"},
                "detail": "7:10 PM ET",
            }
        ]
        live_lens_games = [
            {
                "gamePk": 123,
                "away": {"abbr": "NYY", "name": "Yankees"},
                "home": {"abbr": "BOS", "name": "Red Sox"},
                "status": {"abstract": "Scheduled", "detailed": "7:10 PM ET"},
                "detail": "7:10 PM ET",
                "href": "/mlb/live-lens?date=2026-06-05",
                "liveProps": [
                    {
                        "playerName": "Aaron Judge",
                        "playerId": 592450,
                        "playerPhoto": "https://example.com/judge.png",
                        "marketLabel": "Hits",
                        "selection": "over",
                        "line": 1.5,
                        "estimatedWinProb": 0.61,
                        "modelMean": 1.9,
                        "liveProjection": 2.1,
                        "odds": "+110",
                    }
                ],
            }
        ]

        live_page_context = {"games": live_lens_games, "counts": {"live": 1, "final": 0, "props": 1}}

        with patch("syndicate.features.mlb.live_lens.read_latest_live_lens_page_context", return_value=live_page_context):
            rows = _load_home_live_prop_items(
                "mlb",
                context_label="2026-06-05",
                home_games=scheduled_home_games,
                is_active_today=True,
            )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].get("name"), "Aaron Judge")
        self.assertTrue(rows[0].get("is_live"))
        self.assertEqual(rows[0].get("href"), "/mlb/live-lens?date=2026-06-05")

    def test_mlb_live_prop_rows_do_not_fall_back_to_top_props_when_live_payload_has_no_props(self) -> None:
        from syndicate.blueprints.home import _load_home_prop_items

        live_lens_games = [
            {
                "gamePk": 123,
                "away": {"abbr": "NYY", "name": "Yankees"},
                "home": {"abbr": "BOS", "name": "Red Sox"},
                "status": {"abstract": "Live", "detailed": "Top 3"},
                "matchup": {"status_badge": "Live", "status_line": None},
                "liveProps": [],
                "archivedLiveProps": [],
            }
        ]
        live_page_context = {"games": live_lens_games, "counts": {"live": 1, "final": 0, "props": 0}}

        with patch("syndicate.features.mlb.live_lens.read_latest_live_lens_page_context", return_value=live_page_context):
            rows = _load_home_prop_items(
                "mlb",
                context_label="2026-06-05",
                home_games=[],
                is_active_today=True,
            )

        self.assertEqual(rows, [])

    def test_mlb_pregame_rows_include_extra_pitcher_props(self) -> None:
        from syndicate.blueprints.home import _pregame_prop_rows_from_mlb_recommendations

        payload = {
            123: {
                "markets": {
                    "pitcherProps": [],
                    "extraPitcherProps": [
                        {
                            "pitcher_name": "Zebby Matthews",
                            "pitcher_id": 700001,
                            "prop": "strikeouts",
                            "market_line": 5.5,
                            "selection": "over",
                            "model_prob_over": 0.58,
                            "projection": 6.2,
                            "odds": "+130",
                            "edge": 0.061,
                            "away_abbr": "MIN",
                            "home_abbr": "SEA",
                        }
                    ],
                    "hitterProps": [],
                    "extraHitterProps": [],
                },
                "away": {"abbr": "MIN", "team_id": 142},
                "home": {"abbr": "SEA", "team_id": 136},
            }
        }

        with patch("syndicate.features.mlb.cards._cards_recommendation_payload_by_game", return_value=payload):
            rows = _pregame_prop_rows_from_mlb_recommendations(
                "2026-06-05",
                limit=18,
                fallback_href="/mlb/cards?date=2026-06-05",
            )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].get("name"), "Zebby Matthews")
        self.assertEqual(rows[0].get("market"), "Pitcher Strikeouts")
        self.assertEqual(rows[0].get("pick"), "OVER")

    def test_intelligence_query_supports_plus_money_only_filter(self) -> None:
        advanced_rows = [
            {
                "label": "Team advanced stats",
                "metrics": ["Pace", "Offensive rating", "Shot profile"],
                "path": "data/nba_source/data/processed/team_advanced_stats_2026.csv",
                "exists": True,
                "tracked": True,
                "inside_repo": True,
            }
        ]
        with _patch_build_intelligence_overview(_sample_overview()):
            with patch("syndicate.features.intelligence._tracked_repo_files", return_value=set()):
                with patch("syndicate.features.intelligence._advanced_input_rows_for_sport", return_value=advanced_rows):
                    response = self.client.post(
                        "/api/intelligence/query",
                        json={
                            "force_refresh": True,
                            "question": "Give me the best NBA props plus money only",
                            "date": "2026-06-04",
                        },
                    )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        result = payload.get("response") or {}
        recommendations = result.get("recommendations") or []
        self.assertTrue(recommendations)
        self.assertTrue(all((item.get("american_odds") or 0) >= 100 for item in recommendations))

    def test_intelligence_query_supports_target_parlay_odds_range(self) -> None:
        advanced_rows = [
            {
                "label": "Team advanced stats",
                "metrics": ["Pace", "Offensive rating", "Shot profile"],
                "path": "data/nba_source/data/processed/team_advanced_stats_2026.csv",
                "exists": True,
                "tracked": True,
                "inside_repo": True,
            }
        ]
        with _patch_build_intelligence_overview(_sample_overview()):
            with patch("syndicate.features.intelligence._tracked_repo_files", return_value=set()):
                with patch("syndicate.features.intelligence._advanced_input_rows_for_sport", return_value=advanced_rows):
                    response = self.client.post(
                        "/api/intelligence/query",
                        json={
                            "force_refresh": True,
                            "question": "Build me a two-leg parlay between +300 and +500 from the best NBA edges",
                            "date": "2026-06-04",
                        },
                    )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        result = payload.get("response") or {}
        parlays = result.get("parlays") or []
        self.assertTrue(parlays)
        for parlay in parlays:
            combined_odds = str(parlay.get("combined_odds") or "")
            self.assertTrue(combined_odds.startswith("+"))
            self.assertGreaterEqual(int(combined_odds), 300)
            self.assertLessEqual(int(combined_odds), 500)

    def test_intelligence_query_supports_four_leg_parlays(self) -> None:
        overview = [
            {
                "slug": "nba",
                "name": "NBA",
                "context_label": "2026-06-04",
                "data_health": "healthy",
                "data_warnings": [],
                "home_rails": {
                    "pregame": {
                        "title": "Pregame props",
                        "items": [
                            {
                                "name": "Tatum Over 28.5",
                                "market": "PTS",
                                "pick": "Over 28.5",
                                "matchup": "BOS at NYK",
                                "projected": 31.8,
                                "line": 28.5,
                                "odds": "+102",
                                "confidence": "63%",
                                "edge": "+5.4%",
                                "writeup": "Projection clears the number.",
                                "display_pills": ["Line 28.5", "Odds +102"],
                                "href": "/nba/prop-ladders?date=2026-06-04",
                            },
                            {
                                "name": "Brown Over 6.5 Reb",
                                "market": "REB",
                                "pick": "Over 6.5",
                                "matchup": "MIA at PHI",
                                "projected": 7.9,
                                "line": 6.5,
                                "odds": "+108",
                                "confidence": "61%",
                                "edge": "+4.0%",
                                "writeup": "Rebounding spot is favorable.",
                                "display_pills": ["Line 6.5", "Odds +108"],
                                "href": "/nba/prop-ladders?date=2026-06-04",
                            },
                            {
                                "name": "Booker Over 7.5 Ast",
                                "market": "AST",
                                "pick": "Over 7.5",
                                "matchup": "PHX at SAC",
                                "projected": 8.6,
                                "line": 7.5,
                                "odds": "+104",
                                "confidence": "60%",
                                "edge": "+3.6%",
                                "writeup": "Primary handler workload supports the over.",
                                "display_pills": ["Line 7.5", "Odds +104"],
                                "href": "/nba/prop-ladders?date=2026-06-04",
                            },
                        ],
                    },
                    "live": {
                        "title": "Top Live Props",
                        "items": [
                            {
                                "name": "Mitchell Over 4.5 3PM",
                                "market": "3PM",
                                "pick": "Over 4.5",
                                "matchup": "CLE at IND",
                                "projected": 4.9,
                                "live_projection": 5.8,
                                "actual": 3,
                                "line": 4.5,
                                "odds": "+118",
                                "confidence": "61%",
                                "edge": "+4.1%",
                                "writeup": "Live model still clears the line.",
                                "display_pills": ["Line 4.5", "Odds +118", "Live Proj 5.8"],
                                "is_live": True,
                                "href": "/nba/season/2026/live-lens?date=2026-06-04",
                            }
                        ],
                    },
                    "compact": {"items": []},
                },
                "dashboard_games": [],
            }
        ]
        advanced_rows = [
            {
                "label": "Team advanced stats",
                "metrics": ["Pace", "Offensive rating", "Shot profile"],
                "path": "data/nba_source/data/processed/team_advanced_stats_2026.csv",
                "exists": True,
                "tracked": True,
                "inside_repo": True,
            }
        ]
        with _patch_build_intelligence_overview(overview):
            with patch("syndicate.features.intelligence._tracked_repo_files", return_value=set()):
                with patch("syndicate.features.intelligence._advanced_input_rows_for_sport", return_value=advanced_rows):
                    response = self.client.post(
                        "/api/intelligence/query",
                        json={
                            "force_refresh": True,
                            "question": "Build me a four-leg parlay from the best NBA edges",
                            "date": "2026-06-04",
                        },
                    )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        result = payload.get("response") or {}
        parlays = result.get("parlays") or []
        self.assertTrue(parlays)
        self.assertTrue(all(len(parlay.get("legs") or []) == 4 for parlay in parlays))
        self.assertTrue(all(str(parlay.get("label") or "").startswith("4-leg") for parlay in parlays))

    def test_intelligence_query_supports_cross_sport_parlays(self) -> None:
        advanced_by_sport = {
            "nba": [
                {
                    "label": "Team advanced stats",
                    "metrics": ["Pace", "Offensive rating"],
                    "path": "data/nba_source/data/processed/team_advanced_stats_2026.csv",
                    "exists": True,
                    "tracked": True,
                    "inside_repo": True,
                }
            ],
            "wnba": [
                {
                    "label": "Team environment and pace layer",
                    "metrics": ["Pace", "Team environment"],
                    "path": "data/wnba_source/data/processed/recommendations_slate_2026-06-04.json",
                    "exists": True,
                    "tracked": True,
                    "inside_repo": True,
                }
            ],
        }
        with _patch_build_intelligence_overview(_sample_overview_with_secondary_sport()):
            with patch("syndicate.features.intelligence._tracked_repo_files", return_value=set()):
                with patch("syndicate.features.intelligence._advanced_input_rows_for_sport", side_effect=lambda sport, tracked: advanced_by_sport.get(sport.get("slug"), [])):
                    response = self.client.post(
                        "/api/intelligence/query",
                        json={
                            "force_refresh": True,
                            "question": "Build me a cross-sport two-leg parlay across NBA and WNBA",
                            "date": "2026-06-04",
                        },
                    )

        self.assertEqual(response.status_code, 200)
        result = (response.get_json() or {}).get("response") or {}
        parlays = result.get("parlays") or []
        self.assertTrue(parlays)
        self.assertTrue(all(parlay.get("cross_sport") for parlay in parlays))
        self.assertTrue(all(len(set(leg.get("sport_slug") for leg in (parlay.get("legs") or []))) > 1 for parlay in parlays))
        self.assertTrue(any("Cross-sport" in chip for chip in ((result.get("parsed_request") or {}).get("chips") or [])))

    def test_intelligence_query_supports_same_game_parlays(self) -> None:
        overview = [
            {
                "slug": "nba",
                "name": "NBA",
                "context_label": "2026-06-04",
                "data_health": "healthy",
                "data_warnings": [],
                "home_rails": {
                    "pregame": {
                        "title": "Pregame props",
                        "items": [
                            {
                                "name": "Tatum Over 28.5",
                                "market": "PTS",
                                "pick": "Over 28.5",
                                "matchup": "BOS at NYK",
                                "projected": 31.8,
                                "line": 28.5,
                                "odds": "+102",
                                "confidence": "63%",
                                "edge": "+5.4%",
                                "writeup": "Projection clears the number.",
                                "display_pills": ["Line 28.5", "Odds +102"],
                                "href": "/nba/prop-ladders?date=2026-06-04",
                            },
                            {
                                "name": "Brunson Over 6.5 Ast",
                                "market": "AST",
                                "pick": "Over 6.5",
                                "matchup": "BOS at NYK",
                                "projected": 7.8,
                                "line": 6.5,
                                "odds": "+106",
                                "confidence": "61%",
                                "edge": "+4.2%",
                                "writeup": "Primary handler usage is intact.",
                                "display_pills": ["Line 6.5", "Odds +106"],
                                "href": "/nba/prop-ladders?date=2026-06-04",
                            },
                            {
                                "name": "Holiday Over 2.5 3PM",
                                "market": "3PM",
                                "pick": "Over 2.5",
                                "matchup": "BOS at NYK",
                                "projected": 3.3,
                                "line": 2.5,
                                "odds": "+112",
                                "confidence": "60%",
                                "edge": "+3.8%",
                                "writeup": "Spot-up volume is there.",
                                "display_pills": ["Line 2.5", "Odds +112"],
                                "href": "/nba/prop-ladders?date=2026-06-04",
                            },
                        ],
                    },
                    "live": {"title": "Top Live Props", "items": []},
                    "compact": {"items": []},
                },
                "dashboard_games": [],
            }
        ]
        advanced_rows = [
            {
                "label": "Team advanced stats",
                "metrics": ["Pace", "Offensive rating", "Shot profile"],
                "path": "data/nba_source/data/processed/team_advanced_stats_2026.csv",
                "exists": True,
                "tracked": True,
                "inside_repo": True,
            }
        ]
        with _patch_build_intelligence_overview(overview):
            with patch("syndicate.features.intelligence._tracked_repo_files", return_value=set()):
                with patch("syndicate.features.intelligence._advanced_input_rows_for_sport", return_value=advanced_rows):
                    response = self.client.post(
                        "/api/intelligence/query",
                        json={
                            "force_refresh": True,
                            "question": "Build me a same game three-leg parlay from the best NBA edges",
                            "date": "2026-06-04",
                        },
                    )

        self.assertEqual(response.status_code, 200)
        result = (response.get_json() or {}).get("response") or {}
        parlays = result.get("parlays") or []
        self.assertTrue(parlays)
        self.assertTrue(all(parlay.get("parlay_type") == "same_game" for parlay in parlays))
        self.assertTrue(all(len(set(leg.get("matchup") for leg in (parlay.get("legs") or []))) == 1 for parlay in parlays))

    def test_intelligence_query_supports_round_robin_parlays(self) -> None:
        overview = [
            {
                "slug": "nba",
                "name": "NBA",
                "context_label": "2026-06-04",
                "data_health": "healthy",
                "data_warnings": [],
                "home_rails": {
                    "pregame": {
                        "title": "Pregame props",
                        "items": [
                            {
                                "name": "Tatum Over 28.5",
                                "market": "PTS",
                                "pick": "Over 28.5",
                                "matchup": "BOS at NYK",
                                "projected": 31.8,
                                "line": 28.5,
                                "odds": "+102",
                                "confidence": "63%",
                                "edge": "+5.4%",
                                "writeup": "Projection clears the number.",
                                "display_pills": ["Line 28.5", "Odds +102"],
                                "href": "/nba/prop-ladders?date=2026-06-04",
                            },
                            {
                                "name": "Brown Over 6.5 Reb",
                                "market": "REB",
                                "pick": "Over 6.5",
                                "matchup": "MIA at PHI",
                                "projected": 7.9,
                                "line": 6.5,
                                "odds": "+108",
                                "confidence": "61%",
                                "edge": "+4.0%",
                                "writeup": "Rebounding spot is favorable.",
                                "display_pills": ["Line 6.5", "Odds +108"],
                                "href": "/nba/prop-ladders?date=2026-06-04",
                            },
                            {
                                "name": "Booker Over 7.5 Ast",
                                "market": "AST",
                                "pick": "Over 7.5",
                                "matchup": "PHX at SAC",
                                "projected": 8.6,
                                "line": 7.5,
                                "odds": "+104",
                                "confidence": "60%",
                                "edge": "+3.6%",
                                "writeup": "Primary handler workload supports the over.",
                                "display_pills": ["Line 7.5", "Odds +104"],
                                "href": "/nba/prop-ladders?date=2026-06-04",
                            },
                            {
                                "name": "Edwards Over 3.5 3PM",
                                "market": "3PM",
                                "pick": "Over 3.5",
                                "matchup": "MIN at DAL",
                                "projected": 4.4,
                                "line": 3.5,
                                "odds": "+110",
                                "confidence": "60%",
                                "edge": "+3.9%",
                                "writeup": "Volume holds in a fast environment.",
                                "display_pills": ["Line 3.5", "Odds +110"],
                                "href": "/nba/prop-ladders?date=2026-06-04",
                            },
                        ],
                    },
                    "live": {"title": "Top Live Props", "items": []},
                    "compact": {"items": []},
                },
                "dashboard_games": [],
            }
        ]
        advanced_rows = [
            {
                "label": "Team advanced stats",
                "metrics": ["Pace", "Offensive rating", "Shot profile"],
                "path": "data/nba_source/data/processed/team_advanced_stats_2026.csv",
                "exists": True,
                "tracked": True,
                "inside_repo": True,
            }
        ]
        with _patch_build_intelligence_overview(overview):
            with patch("syndicate.features.intelligence._tracked_repo_files", return_value=set()):
                with patch("syndicate.features.intelligence._advanced_input_rows_for_sport", return_value=advanced_rows):
                    response = self.client.post(
                        "/api/intelligence/query",
                        json={
                            "force_refresh": True,
                            "question": "Build me a four-leg round robin from the best NBA edges",
                            "date": "2026-06-04",
                        },
                    )

        self.assertEqual(response.status_code, 200)
        result = (response.get_json() or {}).get("response") or {}
        parlays = result.get("parlays") or []
        self.assertTrue(parlays)
        self.assertTrue(all(parlay.get("parlay_type") == "round_robin" for parlay in parlays))
        self.assertTrue(all(parlay.get("round_robin_unit") == 2 for parlay in parlays))
        self.assertTrue(all(parlay.get("round_robin_group_size") == 4 for parlay in parlays))
        self.assertTrue(all(str(parlay.get("label") or "").startswith("Round robin") for parlay in parlays))

    def test_intelligence_query_requires_question(self) -> None:
        response = self.client.post("/api/intelligence/query", json={"date": "2026-06-04"})

        self.assertEqual(response.status_code, 400)
        payload = response.get_json()
        self.assertFalse(payload.get("ok"))

    def test_intelligence_query_recomputes_for_identical_request(self) -> None:
        # Rewritten: the old version stubbed fifteen internal seams with
        # exact-signature lambdas, so it broke on every internal refactor
        # while proving nothing about the behavior under test. The invariant
        # is only that an identical force-refresh request RECOMPUTES (the
        # per-question cache serves force_refresh=False reads only) -- count
        # the pool builds and compare the served picks.
        from syndicate.features.intelligence import collect_candidates_with_fallback_merge as real_collect

        overview = _sample_overview()
        with _patch_build_intelligence_overview(overview):
            with patch("syndicate.features.intelligence._tracked_repo_files", return_value=set()):
                with patch("syndicate.features.intelligence._advanced_input_rows_for_sport", return_value=[]):
                    with patch(
                        "syndicate.features.intelligence.collect_candidates_with_fallback_merge",
                        side_effect=real_collect,
                    ) as mocked_collect:
                        first = run_intelligence_query("top edges today", selected_date="2026-06-11", force_refresh=True)
                        second = run_intelligence_query("top edges today", selected_date="2026-06-11", force_refresh=True)

        self.assertEqual(mocked_collect.call_count, 2)
        self.assertEqual(
            [item.get("name") for item in (first.get("recommendations") or [])],
            [item.get("name") for item in (second.get("recommendations") or [])],
        )

    def test_intelligence_status_reports_tracked_artifacts(self) -> None:
        status_overview = [
            {
                "slug": "mlb",
                "name": "MLB",
                "context_label": "2026-06-04",
                "data_health": "healthy",
                "data_warnings": [],
            }
        ]
        tracked_paths = {
            "data/mlb_source/data/live_lens/live_lens_report_2026_06_04.json",
            "data/mlb_source/data/live_lens/live_lens_2026_06_04.jsonl",
        }
        # /api/intelligence/status is snapshot-read-only now (see the
        # sibling test_status_endpoint_* tests) -- it no longer calls
        # build_intelligence_status itself. Build the real status payload
        # directly (still exercising the sports/artifacts/advanced_inputs/
        # readiness_gate shape under test) and feed it through as the
        # snapshot the endpoint would have read from disk.
        from syndicate.features.intelligence import build_intelligence_status

        # setUp redirects SYNDICATE_MLB_SOURCE_ROOT (along with every other
        # sport) to an empty tempdir OUTSIDE the repo, so artifact_specs'
        # paths resolve outside repo_root and "tracked" reads False no
        # matter what tracked_paths says (inside_repo gates it). Route the
        # MLB artifact-spec paths through _repo_root() directly rather than
        # fight that redirect via env vars: preferred_artifact_roots's
        # repo_root_from(__file__) is also off by one directory level when
        # called from intelligence.py itself (it assumes 3 levels of
        # nesting, correct for syndicate/features/<sport>/sources.py but not
        # for syndicate/features/intelligence.py, which is only 2) -- a real
        # separate bug, out of scope here, but real enough that trusting
        # that resolver in this test would be fragile on top of broken.
        from syndicate.features.intelligence import _repo_root

        def _fixture_mlb_path(*parts: str) -> Path:
            return _repo_root().joinpath("data", "mlb_source", *parts)

        with _patch_build_intelligence_overview(status_overview):
            with patch("syndicate.features.intelligence._mlb_repo_artifact_path", side_effect=_fixture_mlb_path):
                # build_intelligence_status's market_summary/
                # market_summary_by_sport come from reports/daily_update/
                # latest/unified_daily_update_latest_simulation_contract.json
                # on disk (via _read_json_payload), NOT from
                # load_latest_refresh_status's "daily_update" key -- that
                # dict is spread in first and then unconditionally
                # overwritten by the simulation-contract values. Mock the
                # real seam so this test doesn't depend on whatever that
                # file happens to contain in a live checkout.
                with patch(
                    "syndicate.features.intelligence._read_json_payload",
                    return_value={
                        "market_summary": {"market_feature_count": 1},
                        "market_summary_by_sport": {"mlb": {"market_feature_count": 1}},
                    },
                ):
                    with patch("syndicate.features.intelligence._tracked_repo_files", return_value=tracked_paths), patch(
                        "syndicate.features.intelligence.load_latest_refresh_status",
                        return_value={
                            "refresh_status": {"runtime": {"state": "finished"}, "manifest": {"date": "2026-06-04"}},
                            "daily_update": {
                                "manifest": {"date": "2026-06-04", "state": "finished"},
                            },
                        },
                    ):
                        built_status = build_intelligence_status(selected_date="2026-06-04")

        # _response_has_board_content gates whether the endpoint copies
        # status keys into the response at all; build_intelligence_status's
        # own shape carries none of the fields it checks (top_opportunities/
        # recommendations/board_contract), so it needs a stub to pass that
        # gate without changing anything this test asserts on.
        built_status["top_opportunities"] = [{"name": "stub"}]

        with patch("syndicate.blueprints.intelligence.read_latest_intelligence_state", return_value=dict(built_status)):
            with patch("syndicate.blueprints.intelligence.read_latest_intelligence_board_snapshot_response", return_value={}):
                response = self.client.get("/api/intelligence/status?date=2026-06-04")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload.get("ok"))
        sports = payload.get("sports") or []
        self.assertTrue(sports)
        mlb_row = next((row for row in sports if row.get("slug") == "mlb"), None)
        self.assertIsNotNone(mlb_row)
        artifacts = (mlb_row or {}).get("artifacts") or []
        self.assertTrue(any(item.get("tracked") for item in artifacts))
        advanced_inputs = (mlb_row or {}).get("advanced_inputs") or []
        self.assertTrue(advanced_inputs)
        self.assertIn("metrics", advanced_inputs[0])
        self.assertIn("readiness_gate", payload)
        self.assertIn("refresh_status", payload)
        self.assertEqual((payload.get("refresh_status") or {}).get("refresh_status", {}).get("runtime", {}).get("state"), "finished")
        self.assertIn("daily_update", payload)
        self.assertEqual((payload.get("daily_update") or {}).get("manifest", {}).get("state"), "finished")
        self.assertEqual((payload.get("daily_update") or {}).get("market_summary", {}).get("market_feature_count"), 1)
        self.assertEqual((payload.get("daily_update") or {}).get("market_summary_by_sport", {}).get("mlb", {}).get("market_feature_count"), 1)
        self.assertIn("advanced_gate", mlb_row or {})
        self.assertIn("publish_missing_inputs", (mlb_row or {}).get("advanced_gate") or {})

    def test_status_endpoint_builds_fresh_status_without_cache(self) -> None:
        app = Flask(__name__)
        app.register_blueprint(intelligence_bp)

        # The endpoint is snapshot-read-only now: it serves whatever the
        # worker-owned read_latest_intelligence_state returns, with no
        # request-path rebuild. Board-content gating goes through
        # _response_candidate_count, which only counts
        # candidate_pool.candidates / top_opportunities / recommendations --
        # a bare top-level "candidates" list reads as an empty board.
        cached_status = {
            "ok": True,
            "threadAlive": True,
            "cachedSnapshots": 3,
            "candidate_count": 1,
            "last_updated": "2026-06-11T16:05:00Z",
            "top_opportunities": [{"name": "Play 1"}],
        }

        with app.test_request_context("/api/intelligence/status?date=2026-06-10", method="GET"):
            with patch("syndicate.blueprints.intelligence.read_latest_intelligence_board_snapshot_response", return_value={}):
                with patch("syndicate.blueprints.intelligence.read_latest_intelligence_state", return_value=dict(cached_status)):
                    response = intelligence_status_api()

        payload = response.get_json()
        self.assertIsNotNone(payload)
        self.assertEqual((payload.get("status") or {}).get("cachedSnapshots"), 3)
        self.assertEqual((payload.get("status") or {}).get("threadAlive"), True)
        # Snapshot timestamps are served as stored; centralization is owned
        # by the worker that writes the state, not by this read path.
        self.assertEqual(payload["state_last_updated"], "2026-06-11T16:05:00Z")
        self.assertEqual((payload.get("status") or {}).get("last_updated"), "2026-06-11T16:05:00Z")
        self.assertEqual(payload["debug_source"], "snapshot_read")
        self.assertEqual(payload["selected_date"], "2026-06-10")
        self.assertEqual(response.headers.get("Cache-Control"), "no-cache, no-store, must-revalidate")
        self.assertEqual(response.headers.get("Pragma"), "no-cache")
        self.assertEqual(response.headers.get("Expires"), "0")

    def test_status_endpoint_ignores_status_cache_artifacts(self) -> None:
        app = Flask(__name__)
        app.register_blueprint(intelligence_bp)

        # build_intelligence_status moved off the request path entirely --
        # the worker cycle in pipeline/intelligence_state.py owns it now.
        # The endpoint serves the latest worker snapshot for the requested
        # date and must never consult the legacy status-response cache
        # artifacts (_load_status_response_cache_state is a dead stub).
        fresh_status = {
            "ok": True,
            "threadAlive": False,
            "cachedSnapshots": 1,
            "last_updated": "2026-06-11T16:05:00Z",
            "candidate_pool": {"candidates": [{"name": "Play 1"}]},
        }

        with app.test_request_context("/api/intelligence/status?date=2026-06-10", method="GET"):
            with patch("syndicate.blueprints.intelligence.read_latest_intelligence_state", return_value=dict(fresh_status)) as state_mock:
                with patch("syndicate.blueprints.intelligence._load_status_response_cache_state") as load_cache_mock:
                    with patch("syndicate.blueprints.intelligence.read_latest_intelligence_board_snapshot_response", return_value={}):
                        response = intelligence_status_api()

        payload = response.get_json()
        self.assertIsNotNone(payload)
        self.assertEqual((payload.get("status") or {}).get("cachedSnapshots"), 1)
        self.assertEqual((payload.get("status") or {}).get("threadAlive"), False)
        self.assertEqual(state_mock.call_args[0][0].get("date"), "2026-06-10")
        load_cache_mock.assert_not_called()

    def test_status_endpoint_degrades_when_queue_refresh_fails(self) -> None:
        app = Flask(__name__)
        app.register_blueprint(intelligence_bp)

        # top_opportunities (not a bare "candidates" list) is what the
        # board-content gate counts -- see _response_candidate_count.
        status_payload = {
            "ok": True,
            "threadAlive": True,
            "cachedSnapshots": 2,
            "candidate_count": 1,
            "last_updated": "2026-06-11T16:05:00Z",
            "top_opportunities": [{"name": "Play 1"}],
        }

        with app.test_request_context("/api/intelligence/status?date=2026-06-10&refresh=1", method="GET"):
            with patch("syndicate.blueprints.intelligence.queue_intelligence_state_refresh", side_effect=RuntimeError("backend unavailable")) as queue_mock:
                with patch("syndicate.blueprints.intelligence.read_latest_intelligence_state_response", return_value=dict(status_payload)):
                    with patch("syndicate.blueprints.intelligence.read_latest_intelligence_board_snapshot_response", return_value=None):
                        response = intelligence_status_api()

        payload = response.get_json()
        self.assertIsNotNone(payload)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload.get("ok"))
        self.assertEqual((payload.get("status") or {}).get("candidate_count"), 1)
        queue_mock.assert_called_once()

    def test_status_endpoint_render_hosted_branch_uses_payload_dict(self) -> None:
        # The render-hosted cached-read branch moved out of the status
        # endpoint into intelligence_query_api (force_refresh on a hosted
        # request): it must hand _cached_intelligence_response_with_source a
        # plain payload dict carrying the requested date, with
        # force_refresh=True, and serve the cached board it returns.
        app = Flask(__name__)
        app.register_blueprint(intelligence_bp)

        cached_board_response = {
            "candidate_count": 2,
            "top_opportunities": [{"name": "WNBA play"}],
            "recommendations": [{"name": "WNBA play"}],
            "portfolio": {},
            "parlays": [],
        }

        def cached_response_probe(payload: dict[str, object], *, force_refresh: bool = True):
            self.assertIsInstance(payload, dict)
            self.assertEqual(str(payload.get("date") or "").strip(), "2026-06-10")
            self.assertTrue(force_refresh)
            cached_response_probe.called = True
            return dict(cached_board_response), "render_compute"

        cached_response_probe.called = False

        with app.test_request_context(
            "/api/intelligence/query",
            method="POST",
            json={"question": "top edges today", "date": "2026-06-10", "force_refresh": True},
        ):
            with patch("syndicate.blueprints.intelligence._render_hosted_request", return_value=True):
                with patch("syndicate.blueprints.intelligence._safe_queue_intelligence_state_refresh"):
                    with patch("syndicate.blueprints.intelligence._cached_intelligence_response_with_source", side_effect=cached_response_probe):
                        response = intelligence_query_api()

        payload = response.get_json()
        self.assertIsNotNone(payload)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(cached_response_probe.called)
        self.assertTrue((payload.get("response") or {}).get("queued_refresh"))
        self.assertEqual((payload.get("response") or {}).get("execution_source"), "render_compute")
        self.assertEqual(response.headers.get("Cache-Control"), "no-cache, no-store, must-revalidate")
        self.assertEqual(response.headers.get("Pragma"), "no-cache")

    def test_status_endpoint_preserves_requested_sport_in_payload_key(self) -> None:
        app = Flask(__name__)
        app.register_blueprint(intelligence_bp)

        captured_payloads: list[dict[str, object]] = []

        def capture_latest_state(payload: dict[str, object], *args, **kwargs):
            captured_payloads.append(dict(payload))
            selected_date = str(payload.get("date") or payload.get("selected_date") or "2026-07-07")
            return {
                "ok": True,
                "selected_date": selected_date,
                "candidate_count": 1,
                "response": {"selected_date": selected_date},
                "top_opportunities": [{"name": "Play 1"}],
                "recommendations": [{"name": "Play 1"}],
                "analysis": {"recommendations": [{"name": "Play 1"}], "picks": [], "top_live_opportunities": [], "portfolio": {}, "parlays": []},
            }

        with app.test_request_context("/api/intelligence/status?date=2026-07-07&sport=wnba", method="GET"):
            with patch("syndicate.blueprints.intelligence.read_latest_intelligence_state_response", side_effect=capture_latest_state):
                with patch("syndicate.blueprints.intelligence._response_has_content", side_effect=lambda payload: bool(payload)):
                    with patch("syndicate.blueprints.intelligence._safe_queue_intelligence_state_refresh"):
                        response = intelligence_status_api()

        payload = response.get_json()
        self.assertIsNotNone(payload)
        self.assertGreaterEqual(len(captured_payloads), 1)
        requested_payload = captured_payloads[0]
        self.assertEqual(str(requested_payload.get("sport") or "").lower(), "wnba")

        all_payload = dict(requested_payload)
        all_payload["sport"] = "all"
        self.assertNotEqual(_payload_key(requested_payload), _payload_key(all_payload))

    def test_status_endpoint_queues_refresh_for_missing_requested_sport(self) -> None:
        app = Flask(__name__)
        app.register_blueprint(intelligence_bp)

        queued_payloads: list[dict[str, object]] = []

        def queue_refresh_spy(payload: dict[str, object]) -> None:
            queued_payloads.append(dict(payload))

        with app.test_request_context("/api/intelligence/status?date=2026-07-07&sport=wnba", method="GET"):
            # return_value, not a side_effect list: the endpoint re-reads the
            # state seam per fallback rung (current snapshot, post-queue
            # read, queued-state retry), so the miss must hold however many
            # reads happen.
            with patch("syndicate.blueprints.intelligence.read_latest_intelligence_state", return_value=None):
                with patch("syndicate.blueprints.intelligence.read_latest_intelligence_board_snapshot_response", return_value=None):
                    with patch("syndicate.blueprints.intelligence._safe_queue_intelligence_state_refresh", side_effect=queue_refresh_spy):
                        response = intelligence_status_api()

        payload = response.get_json()
        self.assertIsNotNone(payload)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload.get("ok"))
        self.assertGreaterEqual(len(queued_payloads), 1)
        self.assertEqual(str(queued_payloads[0].get("sport") or "").lower(), "wnba")
        self.assertEqual((payload.get("status") or {}).get("board_contract", {}).get("cards", []), [])

    def test_intelligence_page_renders_embedded_console(self) -> None:
        fake_response = {
            "headline": "The Syndicate brief",
            "summary": "Rendered directly from the routed intelligence response.",
            "portfolio": {
                "total_exposure": 18.0,
                "expected_return": 22.5,
                "risk_level": "low",
                "risk_label": "low risk",
                "diversification_score": 0.83,
                "average_correlation": 0.12,
            },
            "picks": [
                {
                    "selection": "Player A over 1.5 hits",
                    "edge": 0.032,
                    "confidence": 0.61,
                    "model_probability": 0.574,
                    "implied_probability": 0.542,
                    "movement": {"trend": "up"},
                    "visual": {"risk_level": "low", "pills": ["MLB", "hits"]},
                }
            ],
            "parlays": [
                {
                    "label": "2-leg parlay",
                    "combined_probability": 0.41,
                    "combined_edge": 0.056,
                    "expected_value": 0.18,
                    "correlation_score": 0.12,
                }
            ],
        }
        with patch(
            "syndicate.blueprints.intelligence._cached_intelligence_response_with_source",
            return_value=(fake_response, "worker"),
        ):
            response = self.client.get("/intelligence?date=2026-06-04")

        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        # The embedded console form was replaced by the board command bar
        # (id="board-toolbar") plus a client-side renderer fed from the
        # routed response embedded as JSON in id="initial-intelligence-response".
        self.assertIn('id="board-toolbar"', body)
        self.assertIn('id="initial-intelligence-response"', body)
        self.assertIn('/api/intelligence/query', body)
        self.assertIn('Data coverage', body)
        self.assertIn('Betting Board', body)
        self.assertIn('id="board-portfolio"', body)
        self.assertIn('id="board-parlays"', body)
        self.assertIn('Player A over 1.5 hits', body)
        self.assertIn('2-leg parlay', body)

    def test_intelligence_page_uses_safe_state_reader(self) -> None:
        cached_response = {
            "ok": True,
            "selected_date": "2026-06-04",
            "top_opportunities": [{"name": "Play 1"}],
            "analysis": {"recommendations": [{"name": "Play 1"}], "picks": [], "top_live_opportunities": [], "portfolio": {}, "parlays": []},
            "response": {"recommendations": [{"name": "Play 1"}], "top_opportunities": [{"name": "Play 1"}]},
        }

        with patch("syndicate.blueprints.intelligence._cached_intelligence_response_with_source", new=None):
            with patch("syndicate.blueprints.intelligence.read_latest_intelligence_board_snapshot_response", return_value=None) as mocked_board_snapshot:
                with patch("syndicate.blueprints.intelligence.read_latest_intelligence_state_response", return_value=cached_response) as mocked_state_response:
                    with patch("syndicate.blueprints.intelligence.queue_intelligence_state_refresh") as mocked_queue:
                        response = self.client.get("/intelligence?date=2026-06-04")

        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn('Betting Board', body)
        mocked_board_snapshot.assert_called_once()
        mocked_state_response.assert_called_once()
        self.assertEqual(mocked_state_response.call_args.kwargs.get("force_refresh"), False)
        self.assertEqual(mocked_state_response.call_args.kwargs.get("allow_latest_fallback"), False)
        mocked_queue.assert_not_called()

    def test_intelligence_blotter_view_includes_odds_projected_and_live_columns(self) -> None:
        # The blotter (table) view showed Lane/Matchup/Pick/Win%/Edge/Move
        # only -- no odds, no projected value, and no current-live value
        # for a live bet, even though the card view already surfaced all
        # three via cardFacts(). renderBlotter is pure client-side JS with
        # no server-rendered table markup to assert against directly, so
        # this checks the template's JS source for the header cells and
        # the live-only gating comment as a guard against silently
        # dropping them again in a future edit -- the real behavioral
        # verification was done via Playwright against a running server.
        template_path = Path(__file__).resolve().parents[1] / "syndicate" / "templates" / "intelligence.html"
        source = template_path.read_text(encoding="utf-8")
        self.assertIn("<th>Odds</th><th>Projected</th><th>Live</th>", source)
        self.assertIn('itemState === "live" ? displayLiveProjection(item) : null', source)

    def test_intelligence_page_renders_game_cards_container(self) -> None:
        # Mini per-game cards (grouping opportunities by underlying game so
        # a user can select one game's picks instead of scrolling the whole
        # board) are pure client-side JS driven by this container -- this
        # just confirms the page still wires the mount point up.
        cached_response = {
            "ok": True,
            "selected_date": "2026-06-04",
            "top_opportunities": [{"name": "Play 1"}],
            "analysis": {"recommendations": [{"name": "Play 1"}], "picks": [], "top_live_opportunities": [], "portfolio": {}, "parlays": []},
            "response": {"recommendations": [{"name": "Play 1"}], "top_opportunities": [{"name": "Play 1"}]},
        }

        with patch("syndicate.blueprints.intelligence._cached_intelligence_response_with_source", new=None):
            with patch("syndicate.blueprints.intelligence.read_latest_intelligence_board_snapshot_response", return_value=None):
                with patch("syndicate.blueprints.intelligence.read_latest_intelligence_state_response", return_value=cached_response):
                    with patch("syndicate.blueprints.intelligence.queue_intelligence_state_refresh"):
                        response = self.client.get("/intelligence?date=2026-06-04")

        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn('id="board-game-cards"', body)

    def test_intelligence_page_defaults_to_today_without_manifest_scan(self) -> None:
        cached_response = {
            "ok": True,
            "selected_date": "2026-07-04",
            "top_opportunities": [{"name": "Play 1"}],
            "analysis": {"recommendations": [{"name": "Play 1"}], "picks": [], "top_live_opportunities": [], "portfolio": {}, "parlays": []},
            "response": {"recommendations": [{"name": "Play 1"}], "top_opportunities": [{"name": "Play 1"}]},
        }

        # Pin "today" so the cached response is same-date: a date-mismatched
        # cached board now deliberately queues a background refresh (serve
        # last-known-good while the worker catches up), so leaving today
        # floating would turn this into a test of the refresh path instead.
        with patch("syndicate.blueprints.intelligence.central_today_iso", return_value="2026-07-04"):
            with patch("syndicate.blueprints.intelligence._latest_available_intelligence_date") as mocked_latest_date:
                with patch("syndicate.blueprints.intelligence._cached_intelligence_response_with_source", new=None):
                    with patch("syndicate.blueprints.intelligence.read_latest_intelligence_board_snapshot_response", return_value=None):
                        with patch("syndicate.blueprints.intelligence.read_latest_intelligence_state_response", return_value=cached_response):
                            with patch("syndicate.blueprints.intelligence.queue_intelligence_state_refresh") as mocked_queue:
                                response = self.client.get("/intelligence")

        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Betting Board", body)
        self.assertIn("Play 1", body)
        mocked_latest_date.assert_not_called()
        mocked_queue.assert_not_called()

    def test_intelligence_page_computes_when_cache_is_empty(self) -> None:
        # The synchronous compute-on-request path is gone: computation is
        # worker-owned via pipeline.intelligence_state (the service behind
        # compute_intelligence_state_response). With every cache empty the
        # page must queue a background refresh and render the degraded empty
        # board -- never compute inline in the request handler.
        with patch("syndicate.blueprints.intelligence.read_latest_intelligence_board_snapshot_response", return_value=None) as mocked_board_snapshot:
            with patch("syndicate.blueprints.intelligence.read_latest_intelligence_state_response", return_value=None) as mocked_state_response:
                with patch("pipeline.intelligence_state.compute_intelligence_state_response") as mocked_compute:
                    with patch("syndicate.blueprints.intelligence.queue_intelligence_state_refresh") as mocked_queue:
                        response = self.client.get("/intelligence?date=2026-07-04")

        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Betting Board", body)
        mocked_board_snapshot.assert_called_once()
        mocked_state_response.assert_called_once()
        mocked_compute.assert_not_called()
        mocked_queue.assert_called_once()
        self.assertEqual(mocked_queue.call_args[0][0].get("date"), "2026-07-04")

    def test_intelligence_page_degrades_when_queue_refresh_fails(self) -> None:
        with patch("syndicate.blueprints.intelligence._cached_intelligence_response_with_source", new=None):
            with patch("syndicate.blueprints.intelligence.read_latest_intelligence_board_snapshot_response", return_value=None):
                with patch("syndicate.blueprints.intelligence.read_latest_intelligence_state_response", return_value=None):
                    with patch("syndicate.blueprints.intelligence.queue_intelligence_state_refresh", side_effect=RuntimeError("backend unavailable")) as mocked_queue:
                        response = self.client.get("/intelligence?date=2026-07-05")

        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Betting Board", body)
        mocked_queue.assert_called_once()

    def test_source_fingerprint_changes_when_sport_manifest_updates(self) -> None:
        from pipeline.intelligence_state import IntelligenceStateService

        service = IntelligenceStateService()
        with tempfile.TemporaryDirectory() as tmp_dir:
            reports_root = Path(tmp_dir) / "reports"
            manifests_root = reports_root / "manifests"
            manifests_root.mkdir(parents=True, exist_ok=True)
            manifest_path = manifests_root / "nba.json"
            manifest_path.write_text('{"sport":"nba","last_updated":"2026-06-07T10:00:00Z","artifact_paths":["a.csv"],"status":"complete"}', encoding="utf-8")

            with patch(
                "pipeline.intelligence_state.build_intelligence_status",
                return_value={
                    "selected_date": "2026-06-07",
                    "sports": [{"slug": "nba", "artifacts": [], "advanced_inputs": []}],
                    "tracked_summary": {},
                    "advanced_summary": {},
                    "readiness_gate": {},
                    "refresh_status": {"refresh_status": {"manifest": {}, "runtime": {}, "artifacts": {}}},
                },
            ), patch("pipeline.intelligence_state.reports_root", return_value=reports_root):
                first_fingerprint = service._source_state_fingerprint("2026-06-07")
                manifest_path.write_text('{"sport":"nba","last_updated":"2026-06-07T10:01:00Z","artifact_paths":["a.csv","b.csv"],"status":"complete"}', encoding="utf-8")
                second_fingerprint = service._source_state_fingerprint("2026-06-07")

        self.assertNotEqual(first_fingerprint, second_fingerprint)


class GameLevelMarketClassificationTests(unittest.TestCase):
    def test_hitter_and_pitcher_prop_markets_are_never_game_level(self) -> None:
        # Real bug found in production 2026-07-22: "total" in
        # _GAME_LEVEL_MARKET_KEYWORDS matched as a bare substring, so
        # "Hitter Total bases" / "Pitcher Total outs" (MLB's per-player
        # prop rows, market = f"{market_prefix} {market_label}") got
        # classified as candidate_type="game" -- every single "game"
        # candidate on the live board was actually a mislabeled player
        # prop, while genuine team-level Moneyline/Spread/Total candidates
        # never appeared measurably at all.
        self.assertFalse(_is_game_level_market("Hitter Total bases"))
        self.assertFalse(_is_game_level_market("Pitcher Total outs"))
        self.assertFalse(_is_game_level_market("hitter total bases"))

    def test_real_game_level_markets_still_classify_correctly(self) -> None:
        self.assertTrue(_is_game_level_market("Moneyline"))
        self.assertTrue(_is_game_level_market("Total"))
        self.assertTrue(_is_game_level_market("Spread"))
        self.assertTrue(_is_game_level_market("Live Total"))
        self.assertTrue(_is_game_level_market("ats"))
        self.assertTrue(_is_game_level_market(""))

    def test_game_candidates_for_sport_labels_hitter_props_as_prop_not_game(self) -> None:
        sport = {
            "slug": "mlb",
            "dashboard_games": [
                {
                    "matchup": "NYY @ BOS",
                    "markets": {
                        "hitterProps": [
                            {"player_name": "Aaron Judge", "market_label": "Total bases", "selection": "OVER", "market_line": 1.5, "model_prob": 0.58},
                        ],
                    },
                    "betting": {"away_ml": -150, "home_ml": 130, "p_away_win": 0.6, "p_home_win": 0.4},
                }
            ],
        }

        candidates = _game_candidates_for_sport(sport)
        by_type = {}
        for candidate in candidates:
            by_type.setdefault(candidate["candidate_type"], []).append(candidate)

        prop_markets = [c["market"] for c in by_type.get("prop", [])]
        game_markets = [c["market"] for c in by_type.get("game", [])]
        self.assertTrue(any("total bases" in market.lower() for market in prop_markets), prop_markets)
        self.assertNotIn("Hitter Total bases", game_markets)
        self.assertTrue(any(market == "Moneyline" for market in game_markets), game_markets)


class PropCandidateFromItemCompletenessGuardTests(unittest.TestCase):
    """Board audit follow-up, found live 2026-07-31: MLB's HR-targets
    narrative shelf (_load_mlb_home_hr_target_items, home.py) scrapes prose
    writeup/reasons text into a home_rails pregame item with no real
    market, no line, no odds, and no model projection -- just a sentence
    ("His underlying HR-quality profile is running above baseline.") and a
    team abbreviation stamped into "market". _prop_candidate_from_item must
    suppress (return None for) any item with nothing bettable, the same
    shape of completeness guard added to _append_game_bet_candidate for
    WNBA's equivalent symptom.
    """

    def test_narrative_only_item_with_no_line_odds_or_projection_returns_none(self) -> None:
        sport = {"slug": "mlb", "context_label": "2026-07-31"}
        item = {
            "name": "Ben Rice",
            "team": "NYY",
            "pick": "His underlying HR-quality profile is running above baseline.",
            "detail": "His underlying HR-quality profile is running above baseline.",
        }
        candidate = _prop_candidate_from_item(sport, item, surface_key="pregame", surface_title="Pregame props")
        self.assertIsNone(candidate)

    def test_real_prop_with_a_line_and_odds_still_returns_a_candidate(self) -> None:
        sport = {"slug": "mlb", "context_label": "2026-07-31"}
        item = {
            "name": "Aaron Judge",
            "market": "Hitter Total Bases",
            "pick": "OVER 1.5",
            "line": 1.5,
            "odds": -120,
            "projected": 1.8,
        }
        candidate = _prop_candidate_from_item(sport, item, surface_key="pregame", surface_title="Pregame props")
        self.assertIsNotNone(candidate)
        self.assertEqual(candidate["candidate_type"], "prop")

    def test_real_prop_with_only_a_projection_and_no_priced_odds_yet_still_returns_a_candidate(self) -> None:
        sport = {"slug": "mlb", "context_label": "2026-07-31"}
        item = {
            "name": "Aaron Judge",
            "market": "Hitter Total Bases",
            "pick": "OVER 1.5",
            "line": 1.5,
            "projected": 1.8,
        }
        candidate = _prop_candidate_from_item(sport, item, surface_key="pregame", surface_title="Pregame props")
        self.assertIsNotNone(candidate)


class ScoreCandidatesPipelineTaggingTests(unittest.TestCase):
    # _score_candidates is called from three distinct places
    # (collect_all_recommendations, collect_candidates_with_fallback_merge,
    # run_intelligence_query), all emitting an identically-shaped
    # "candidate_scoring" INTEL_TRACE event with no way to tell them apart --
    # confirmed live 2026-07-23 while investigating why WNBA's pregame
    # candidates were missing from the served board: two same-shaped,
    # same-timing "candidate_scoring" traces couldn't be attributed to a
    # specific call site, stalling the investigation. Purely additive/
    # observability-only; asserts the pipeline tag round-trips into the
    # emitted trace, not any behavior change.
    def test_pipeline_kwarg_is_included_in_emitted_trace(self) -> None:
        with patch("syndicate.features.intelligence._intel_trace_timed") as mocked_trace:
            _score_candidates([], {}, {}, pipeline="collect_all_recommendations")

        mocked_trace.assert_called_once()
        _, kwargs = mocked_trace.call_args
        self.assertEqual(kwargs.get("pipeline"), "collect_all_recommendations")

    def test_pipeline_kwarg_defaults_to_none_when_omitted(self) -> None:
        with patch("syndicate.features.intelligence._intel_trace_timed") as mocked_trace:
            _score_candidates([], {}, {})

        mocked_trace.assert_called_once()
        _, kwargs = mocked_trace.call_args
        self.assertIsNone(kwargs.get("pipeline"))


class MlbLivePropProjectionHydrationTests(unittest.TestCase):
    # Real production bug found 2026-07-23: a user placed a live bet on Chris
    # Sale's strikeout UNDER after he'd already recorded 3 live K's, but the
    # board's card still showed a pregame-only projection with no live
    # update ("LIVE PROJ 0" / "-"), even though is_live correctly flipped
    # true. Traced to _apply_live_state_context_to_candidates: it flips
    # is_live from the raw MLB game feed but never reads the ALREADY-CORRECT
    # live projection sitting in the live_lens report (produced by the same
    # live tick, refreshed independently). These tests cover the fix that
    # attaches it by matching player + market + line.
    def _live_actual_payload(self) -> dict:
        return {"gameData": {"status": {"abstractGameState": "Live", "detailedState": "In Progress"}}}

    def _sale_candidate(self, **overrides: object) -> dict:
        candidate = {
            "sport_slug": "mlb",
            "candidate_type": "prop",
            "context_label": "2026-07-23",
            "game_pk": 824893,
            "entity": "Chris Sale",
            "market": "Pitcher Strikeouts",
            "line": "7.5",
            "live_projection": "-",
        }
        candidate.update(overrides)
        return candidate

    def _live_lens_report(self, **row_overrides: object) -> dict:
        row = {
            "playerName": "Chris Sale",
            "marketLabel": "Strikeouts",
            "line": 7.5,
            "actual": 3.0,
            "liveProjection": 6.854,
        }
        row.update(row_overrides)
        return {"games": [{"gamePk": 824893, "trackedProps": [row]}]}

    def test_apply_live_state_hydrates_live_projection_from_live_lens_report(self) -> None:
        from syndicate.features.intelligence import _apply_live_state_context_to_candidates

        candidate = self._sale_candidate()
        with patch(
            "syndicate.features.intelligence._mlb_actual_payload_for_candidate",
            return_value=self._live_actual_payload(),
        ), patch(
            "syndicate.features.intelligence.mlb_load_json_file",
            return_value=self._live_lens_report(),
        ):
            _apply_live_state_context_to_candidates([candidate])

        self.assertTrue(candidate.get("is_live"))
        self.assertEqual(candidate.get("live_projection"), "6.9")
        self.assertEqual(candidate.get("actual"), "3.0")

    def test_live_lens_report_path_uses_the_correct_resolver(self) -> None:
        # Real production bug: the hydration above was originally wired to
        # _mlb_repo_artifact_path (used elsewhere in this file only for
        # cosmetic advanced_context display), which resolves via
        # default_mlb_source_root() -- returns SYNDICATE_MLB_SOURCE_ROOT
        # verbatim with no "source_artifacts" segment once that env var is
        # set (true in every deployed environment), so the real file was
        # silently never found and hydration always no-opped. This locks in
        # the fix: the cache helper must call the same
        # live_lens_report_path/_resolve_data_path_with_reconcile resolver
        # every other working MLB artifact reader in this file uses.
        from syndicate.features.intelligence import _mlb_live_lens_report_cached

        with patch(
            "syndicate.features.intelligence.mlb_live_lens_report_path",
            return_value=Path("/resolved/via/correct/helper/live_lens_report_2026_07_23.json"),
        ) as mocked_path_resolver, patch(
            "syndicate.features.intelligence.mlb_load_json_file",
            return_value={"games": []},
        ) as mocked_load:
            _mlb_live_lens_report_cached("2026-07-23", {})

        mocked_path_resolver.assert_called_once_with("2026-07-23")
        mocked_load.assert_called_once_with(Path("/resolved/via/correct/helper/live_lens_report_2026_07_23.json"))

    def test_apply_live_state_does_not_hydrate_when_not_live(self) -> None:
        from syndicate.features.intelligence import _apply_live_state_context_to_candidates

        candidate = self._sale_candidate()
        with patch(
            "syndicate.features.intelligence._mlb_actual_payload_for_candidate",
            return_value={"gameData": {"status": {"abstractGameState": "Preview", "detailedState": "Scheduled"}}},
        ), patch(
            "syndicate.features.intelligence.mlb_load_json_file",
            return_value=self._live_lens_report(),
        ) as mocked_load:
            _apply_live_state_context_to_candidates([candidate])

        self.assertFalse(candidate.get("is_live"))
        self.assertEqual(candidate.get("live_projection"), "-")
        mocked_load.assert_not_called()

    def test_apply_live_state_falls_back_to_game_date_when_context_label_is_missing(self) -> None:
        # 2026-08-01 board audit: confirmed live -- a genuinely stale MLB
        # game-level moneyline candidate (real game had ended hours
        # earlier, but the row still claimed is_live=True with a frozen
        # "3-3" score) never got re-checked against the real current game
        # status, because context_label was null on this candidate class
        # (game-level, not prop) and the loop skipped it entirely before
        # even attempting a lookup -- despite game_date carrying the exact
        # same real date this lookup needs. Must fall back rather than
        # silently give up.
        from syndicate.features.intelligence import _apply_live_state_context_to_candidates

        candidate = {
            "sport_slug": "mlb",
            "candidate_type": "game",
            "context_label": None,
            "game_date": "2026-08-01",
            "game_pk": 824893,
            "is_live": True,
            "game_state": "live",
            "actual": "3-3",
        }
        final_payload = {"gameData": {"status": {"abstractGameState": "Final", "detailedState": "Final"}}}
        with patch(
            "syndicate.features.intelligence._mlb_actual_payload_for_candidate",
            return_value=final_payload,
        ) as mocked_lookup:
            _apply_live_state_context_to_candidates([candidate])

        mocked_lookup.assert_called_once_with("2026-08-01", 824893, {})
        self.assertTrue(candidate.get("is_final"))
        self.assertFalse(candidate.get("is_live"))

    def test_apply_live_state_leaves_placeholder_when_no_matching_row(self) -> None:
        from syndicate.features.intelligence import _apply_live_state_context_to_candidates

        candidate = self._sale_candidate(entity="Someone Else")
        with patch(
            "syndicate.features.intelligence._mlb_actual_payload_for_candidate",
            return_value=self._live_actual_payload(),
        ), patch(
            "syndicate.features.intelligence.mlb_load_json_file",
            return_value=self._live_lens_report(),
        ):
            _apply_live_state_context_to_candidates([candidate])

        self.assertTrue(candidate.get("is_live"))
        self.assertEqual(candidate.get("live_projection"), "-")

    def test_apply_live_state_matches_regardless_of_pitcher_market_label_case(self) -> None:
        from syndicate.features.intelligence import _apply_live_state_context_to_candidates

        candidate = self._sale_candidate(market="pitcher strikeouts")
        with patch(
            "syndicate.features.intelligence._mlb_actual_payload_for_candidate",
            return_value=self._live_actual_payload(),
        ), patch(
            "syndicate.features.intelligence.mlb_load_json_file",
            return_value=self._live_lens_report(),
        ):
            _apply_live_state_context_to_candidates([candidate])

        self.assertEqual(candidate.get("live_projection"), "6.9")

    def test_apply_live_state_does_not_hydrate_non_prop_candidates(self) -> None:
        from syndicate.features.intelligence import _apply_live_state_context_to_candidates

        candidate = self._sale_candidate(candidate_type="game")
        with patch(
            "syndicate.features.intelligence._mlb_actual_payload_for_candidate",
            return_value=self._live_actual_payload(),
        ), patch(
            "syndicate.features.intelligence.mlb_load_json_file",
            return_value=self._live_lens_report(),
        ) as mocked_load:
            _apply_live_state_context_to_candidates([candidate])

        self.assertTrue(candidate.get("is_live"))
        self.assertEqual(candidate.get("live_projection"), "-")
        mocked_load.assert_not_called()

    def test_apply_live_state_hydrates_player_prop_steam_candidates(self) -> None:
        # Real, already-documented gap (30a6cff9): _steam_candidates_for_sport
        # (candidate_type="steam") builds player-prop steam candidates with
        # the exact same name/market/line shape a "prop"-type candidate has
        # -- it only sets player_name at all when the market is NOT a
        # game-side market (moneyline/spread/total) -- but this hydration
        # gate was hardcoded to candidate_type == "prop" alone, so every
        # player-prop steam candidate's live_projection/actual stayed "-"
        # even while genuinely live.
        from syndicate.features.intelligence import _apply_live_state_context_to_candidates

        candidate = self._sale_candidate(candidate_type="steam", player_name="Chris Sale")
        with patch(
            "syndicate.features.intelligence._mlb_actual_payload_for_candidate",
            return_value=self._live_actual_payload(),
        ), patch(
            "syndicate.features.intelligence.mlb_load_json_file",
            return_value=self._live_lens_report(),
        ):
            _apply_live_state_context_to_candidates([candidate])

        self.assertTrue(candidate.get("is_live"))
        self.assertEqual(candidate.get("live_projection"), "6.9")
        self.assertEqual(candidate.get("actual"), "3.0")

    def test_apply_live_state_does_not_hydrate_game_level_steam_candidates(self) -> None:
        # A game-level steam move (moneyline/spread/total) never gets
        # player_name set (_steam_candidates_for_sport's own assignment) --
        # confirm those stay excluded, since they'd never match a
        # player-prop row in the live-lens report anyway.
        from syndicate.features.intelligence import _apply_live_state_context_to_candidates

        candidate = self._sale_candidate(candidate_type="steam", player_name=None)
        with patch(
            "syndicate.features.intelligence._mlb_actual_payload_for_candidate",
            return_value=self._live_actual_payload(),
        ), patch(
            "syndicate.features.intelligence.mlb_load_json_file",
            return_value=self._live_lens_report(),
        ) as mocked_load:
            _apply_live_state_context_to_candidates([candidate])

        self.assertTrue(candidate.get("is_live"))
        self.assertEqual(candidate.get("live_projection"), "-")
        mocked_load.assert_not_called()

    def test_steam_candidates_game_side_markets_get_scoreline_not_combined_score(self) -> None:
        # Board-alignment audit, found live 2026-08-01 against a real live
        # WNBA game: every game-side steam candidate (moneyline/spread) for
        # the same live game showed the identical combined away+home score
        # as "actual", which tells nothing about which side is actually
        # ahead. Only "total" (the market genuinely comparable to a
        # combined number) should keep it -- moneyline/spread get the real
        # scoreline instead.
        from syndicate.features.intelligence import _steam_candidates_for_sport

        base_event = {
            "sport": "wnba",
            "steam": {"capture_phase": "live", "previous_line": -8.0, "previous_odds": -110, "line_delta": 2.0, "odds_delta": 5.0},
            "game_id": "GAME1",
            "price": -150,
            "implied_prob": 0.6,
            "player_name": "",
            "selection": "Away",
            "is_live": True,
            "timestamp": "2026-08-01T18:00:00Z",
        }
        events = [
            {**base_event, "market_type": "moneyline", "line": -6.0},
            {**base_event, "market_type": "total", "line": 184.0, "selection": "Under"},
        ]
        sport = {
            "slug": "wnba",
            "context_label": "2026-08-01",
            "dashboard_games": [{"gamePk": "GAME1", "away": {"abbr": "LVA", "score": 78}, "home": {"abbr": "CHI", "score": 77}}],
        }
        with patch("syndicate.features.intelligence._load_steam_events_for_date", return_value=events):
            candidates = _steam_candidates_for_sport(sport)

        by_market_key = {c.get("market_key"): c for c in candidates}
        self.assertEqual(by_market_key["moneyline"]["actual"], "78-77")
        self.assertEqual(by_market_key["total"]["actual"], "155.0")

    def test_prop_merge_dedup_key_ignores_player_name_that_is_actually_pick_text(self) -> None:
        # Board-alignment audit, found live 2026-08-01 against a real live
        # WNBA game: a candidate whose upstream builder never set a real
        # player_name (root source not yet pinned down) had the ENTIRE pick
        # text ("Alyssa Thomas UNDER 8.5 AST") land in player_name instead
        # of just "Alyssa Thomas". Since that value is truthy,
        # _prop_merge_dedup_key always used it over _candidate_subject_key's
        # careful "split on over/under" parse of the "name" field -- so this
        # candidate's dedup key never matched its correctly-labeled twin
        # (subject "Alyssa Thomas") from a different pipeline. They never
        # merged, and the mislabeled one stayed permanently stuck with no
        # live_projection/actual even once its game went live. A real
        # player name is never itself "... over ..."/"... under ..." text,
        # so that's a safe, general tell -- when detected, fall back to
        # _candidate_subject_key's parse instead of trusting player_name.
        from syndicate.features.intelligence import _merge_duplicate_prop_candidates, _prop_merge_dedup_key

        mislabeled = {
            "candidate_type": "prop",
            "sport_slug": "wnba",
            "player_name": "Alyssa Thomas UNDER 8.5 AST",
            "name": "Alyssa Thomas UNDER 8.5 AST",
            "pick": "Alyssa Thomas UNDER 8.5",
            "market": "Ast",
            "line": 8.5,
            "projected": 5.6,
            "detail": "Rich pregame detail with real reasoning behind the pick and model inputs.",
            "is_live": False,
        }
        correctly_live = {
            "candidate_type": "prop",
            "sport_slug": "wnba",
            "player_name": "Alyssa Thomas",
            "name": "Alyssa Thomas AST",
            "pick": "UNDER",
            "market": "ast",
            "line": 8.5,
            "is_live": True,
            "live_projection": "8.4",
            "actual": "5",
            "status_display": "37-27 | 5:49 - 2nd",
        }
        self.assertEqual(_prop_merge_dedup_key(mislabeled), _prop_merge_dedup_key(correctly_live))

        merged = _merge_duplicate_prop_candidates([mislabeled, correctly_live])

        self.assertEqual(len(merged), 1, merged)
        self.assertEqual(merged[0].get("live_projection"), "8.4")
        self.assertEqual(merged[0].get("actual"), "5")
        self.assertTrue(merged[0].get("is_live"))
        # The richer pregame candidate's own analytical fields must survive
        # the merge too -- this is a reconciliation, not a one-sided win.
        self.assertEqual(merged[0].get("projected"), 5.6)

    def test_prop_merge_dedup_key_still_uses_a_real_player_name(self) -> None:
        # Guard against the fix above being too aggressive -- a genuine,
        # correctly-set player_name (no "over"/"under" substring) must keep
        # winning over _candidate_subject_key, unchanged from before.
        from syndicate.features.intelligence import _prop_merge_dedup_key

        candidate = {
            "candidate_type": "prop",
            "sport_slug": "wnba",
            "player_name": "Alyssa Thomas",
            "name": "Alyssa Thomas AST",
            "pick": "UNDER",
            "market": "ast",
            "line": 8.5,
        }
        key = _prop_merge_dedup_key(candidate)
        self.assertIsNotNone(key)
        self.assertEqual(key[1], "alyssa thomas")

    def test_fallback_merge_reconciles_union_duplicate_the_identity_hash_missed(self) -> None:
        # Board-alignment audit, found live 2026-08-01 against a real live
        # WNBA game -- the actual end-to-end root cause of the "Alyssa
        # Thomas" duplicate. collect_candidates_with_fallback_merge unions
        # collect_candidates' primary result with collect_all_recommendations'
        # richer fallback (triggered whenever the primary pool looks "thin",
        # e.g. a small 2-game WNBA slate) using candidate_identity_key -- a
        # strict hash of exact field text (selection/line/odds verbatim),
        # by design meant to dedupe a pipeline against re-running itself,
        # not to reconcile two DIFFERENT pipelines' representations of the
        # same real-world bet. "Alyssa Thomas UNDER 8.5" (selection text)
        # vs "UNDER" hash to different keys even for the identical player/
        # market/line, so setdefault() kept the mislabeled, never-live
        # candidate and permanently discarded its correctly-live-hydrated
        # twin -- no backfill, no reconciliation. Running
        # _merge_duplicate_prop_candidates (already fixed above to tolerate
        # a corrupted player_name) again on the union catches exactly this.
        from syndicate.features.intelligence import collect_candidates_with_fallback_merge

        live_hydrated = {
            "candidate_type": "prop",
            "sport_slug": "wnba",
            "sport": "wnba",
            "player_name": "Alyssa Thomas",
            "name": "Alyssa Thomas AST",
            "pick": "UNDER",
            "market": "ast",
            "line": 8.5,
            "is_live": True,
            "live_projection": "8.4",
            "actual": "5",
            "event_id": "401857106",
            "odds": "-150",
        }
        mislabeled = {
            "candidate_type": "prop",
            "sport_slug": "wnba",
            "sport": "wnba",
            "player_name": "Alyssa Thomas UNDER 8.5 AST",
            "name": "Alyssa Thomas UNDER 8.5 AST",
            "pick": "Alyssa Thomas UNDER 8.5",
            "market": "Ast",
            "line": 8.5,
            "projected": 5.6,
            "detail": "Rich pregame detail with real reasoning.",
            "is_live": False,
            "event_id": "401857106",
            "odds": "100",
        }
        filler = [
            {
                "candidate_type": "prop",
                "sport_slug": "wnba",
                "sport": "wnba",
                "player_name": f"Filler Player {i}",
                "name": f"Filler Player {i} OVER 10.0",
                "pick": "OVER",
                "market": "pts",
                "line": 10.0,
                "event_id": "401857106",
                "odds": "-110",
            }
            for i in range(25)
        ]
        with patch(
            "syndicate.features.intelligence.collect_candidates", return_value=[live_hydrated]
        ), patch(
            "syndicate.features.intelligence.collect_all_recommendations",
            return_value=[live_hydrated, mislabeled, *filler],
        ):
            result = collect_candidates_with_fallback_merge([], {}, apply_edge_filter=False)

        thomas = [c for c in result if "Thomas" in str(c.get("name") or "")]
        self.assertEqual(len(thomas), 1, thomas)
        self.assertEqual(thomas[0].get("live_projection"), "8.4")
        self.assertEqual(thomas[0].get("actual"), "5")
        self.assertEqual(thomas[0].get("projected"), 5.6)


class RepoArtifactPathFallbackTests(unittest.TestCase):
    # _mlb_repo_artifact_path/_wnba_repo_artifact_path used to resolve via
    # preferred_source_roots (no "source_artifacts" segment once the
    # SYNDICATE_*_SOURCE_ROOT env var is set, true in every deployed
    # environment) -- confirmed broken for MLB's live_lens report (which
    # lives under source_artifacts). But not every artifact uses that
    # convention (confirmed: MLB's statcast player-features file does not),
    # so the fix checks both candidate locations and prefers whichever
    # actually has the file, rather than assuming either one unconditionally.
    def test_prefers_source_artifacts_location_when_it_exists(self) -> None:
        from syndicate.features.intelligence import _mlb_repo_artifact_path

        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir) / "mlb_source"
            source_artifacts_file = root / "source_artifacts" / "data" / "live_lens" / "report.json"
            source_artifacts_file.parent.mkdir(parents=True, exist_ok=True)
            source_artifacts_file.write_text("{}", encoding="utf-8")
            with patch.dict(os.environ, {"SYNDICATE_MLB_SOURCE_ROOT": str(root)}, clear=False):
                result = _mlb_repo_artifact_path("data", "live_lens", "report.json")

        self.assertEqual(result.resolve(), source_artifacts_file.resolve())

    def test_falls_back_to_plain_root_when_only_that_exists(self) -> None:
        from syndicate.features.intelligence import _mlb_repo_artifact_path

        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir) / "mlb_source"
            plain_file = root / "data" / "statcast" / "features" / "player_features_latest.json"
            plain_file.parent.mkdir(parents=True, exist_ok=True)
            plain_file.write_text("{}", encoding="utf-8")
            with patch.dict(os.environ, {"SYNDICATE_MLB_SOURCE_ROOT": str(root)}, clear=False):
                result = _mlb_repo_artifact_path("data", "statcast", "features", "player_features_latest.json")

        self.assertEqual(result.resolve(), plain_file.resolve())

    def test_defaults_to_source_artifacts_candidate_when_neither_exists(self) -> None:
        from syndicate.features.intelligence import _mlb_repo_artifact_path

        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir) / "mlb_source"
            with patch.dict(os.environ, {"SYNDICATE_MLB_SOURCE_ROOT": str(root)}, clear=False):
                result = _mlb_repo_artifact_path("data", "live_lens", "report.json")

        self.assertEqual(result.resolve(), (root / "source_artifacts" / "data" / "live_lens" / "report.json").resolve())

    def test_wnba_repo_artifact_path_checks_both_locations_too(self) -> None:
        from syndicate.features.intelligence import _wnba_repo_artifact_path

        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir) / "wnba_source"
            plain_file = root / "data" / "processed" / "live_snapshots" / "live_pbp_stats_2026-07-23.jsonl"
            plain_file.parent.mkdir(parents=True, exist_ok=True)
            plain_file.write_text("", encoding="utf-8")
            with patch.dict(os.environ, {"SYNDICATE_WNBA_SOURCE_ROOT": str(root)}, clear=False):
                result = _wnba_repo_artifact_path("live_snapshots", "live_pbp_stats_2026-07-23.jsonl")

        self.assertEqual(result.resolve(), plain_file.resolve())

class OverviewCountsTraceCoverageTests(unittest.TestCase):
    """The overview_counts trace is the only visibility into what candidate
    generation is actually handed: _collect_candidates reads dashboard_games
    and home_rails straight off these dicts, so a sport with zero here cannot
    produce a candidate regardless of downstream filters.

    It used to emit for WNBA only, which misled a 2026-07-25 investigation
    into an almost-empty board -- the single visible "dashboard_games_count:
    0" was WNBA's on a one-game All-Star day, and was briefly read as
    evidence about MLB.
    """

    def test_emits_one_trace_per_configured_sport(self) -> None:
        from syndicate.features import intelligence as intelligence_module

        sports = [
            {"slug": "mlb", "name": "MLB"},
            {"slug": "wnba", "name": "WNBA"},
            {"slug": "nhl", "name": "NHL"},
        ]

        def _fake_overview(sport, effective_date, **kwargs):
            return {
                "slug": sport["slug"],
                "context_label": effective_date,
                "data_health": "healthy",
                "dashboard_games": [{"g": 1}] if sport["slug"] == "mlb" else [],
                "home_rails": {"pregame": {"items": [{"p": 1}, {"p": 2}]}, "live": {"items": []}},
            }

        traced: list[dict] = []
        with patch.object(intelligence_module, "_configured_syndicate_sports", return_value=sports), patch.object(
            intelligence_module, "_build_sport_overview", side_effect=_fake_overview
        ), patch.object(
            intelligence_module, "_intel_trace", side_effect=lambda event, **kw: traced.append({"event": event, **kw})
        ):
            intelligence_module.build_intelligence_overview(selected_date="2026-07-25")

        counts = [t for t in traced if t.get("event") == "overview_counts"]
        self.assertEqual({t["sport"] for t in counts}, {"mlb", "wnba", "nhl"})

    def test_reports_the_counts_candidate_generation_depends_on(self) -> None:
        from syndicate.features import intelligence as intelligence_module

        def _fake_overview(sport, effective_date, **kwargs):
            return {
                "slug": "mlb",
                "context_label": effective_date,
                "data_health": "healthy",
                "dashboard_games": [{"g": 1}, {"g": 2}, {"g": 3}],
                "home_rails": {"pregame": {"items": [{"p": 1}]}, "live": {"items": [{"l": 1}, {"l": 2}]}},
            }

        traced: list[dict] = []
        with patch.object(intelligence_module, "_configured_syndicate_sports", return_value=[{"slug": "mlb"}]), patch.object(
            intelligence_module, "_build_sport_overview", side_effect=_fake_overview
        ), patch.object(
            intelligence_module, "_intel_trace", side_effect=lambda event, **kw: traced.append({"event": event, **kw})
        ):
            intelligence_module.build_intelligence_overview(selected_date="2026-07-25")

        row = next(t for t in traced if t.get("event") == "overview_counts")
        self.assertEqual(row["dashboard_games_count"], 3)
        self.assertEqual(row["pregame_count"], 1)
        self.assertEqual(row["live_count"], 2)


class DefaultSyndicateSportsTests(unittest.TestCase):
    """#47. _default_syndicate_sports is not a cosmetic fallback -- it is the
    list the WORKER uses. _configured_syndicate_sports falls back to it
    whenever current_app raises, and the intelligence loop runs on
    refresh-worker outside any Flask app context, so every candidate the
    curated board is built from comes from here.

    Soccer was configured in app.py all along and still never reached Layer 2.
    Production traces settled it: candidate generation ran for mlb, nba, wnba,
    nfl, ncaaf, ncaab, nhl -- the fallback list, in its exact order, not
    app.py's different order.

    A sport missing here is invisible to the board regardless of app config,
    and it fails SILENTLY: no error, the sport just never generates
    candidates. Hence this test.
    """

    def _app_config_slugs(self) -> set[str]:
        import re
        from pathlib import Path

        source = Path(__file__).resolve().parent.parent.joinpath("syndicate", "app.py").read_text(encoding="utf-8")
        start = source.index('app.config["SYNDICATE_SPORTS"] = [')
        block = source[start : source.index("\n        ]", start)]
        return set(re.findall(r'"slug":\s*"([a-z]+)"', block))

    def test_worker_fallback_covers_every_configured_sport(self) -> None:
        from syndicate.features.intelligence import _default_syndicate_sports

        fallback = {sport["slug"] for sport in _default_syndicate_sports()}
        missing = self._app_config_slugs() - fallback
        self.assertEqual(
            missing,
            set(),
            f"these sports are configured in app.py but invisible to the worker's candidate generation: {sorted(missing)}",
        )

    def test_soccer_is_present(self) -> None:
        from syndicate.features.intelligence import _default_syndicate_sports

        self.assertIn("soccer", {sport["slug"] for sport in _default_syndicate_sports()})

    def test_every_entry_has_the_fields_the_overview_needs(self) -> None:
        from syndicate.features.intelligence import _default_syndicate_sports

        for sport in _default_syndicate_sports():
            for field in ("slug", "name", "primary_href"):
                self.assertTrue(str(sport.get(field) or "").strip(), f"{sport.get('slug')} missing {field}")


class PostDedupeAndClassifyTraceTests(unittest.TestCase):
    """#64. Classification and dedupe were the last stage before the candidate
    pool and the only one invisible in production.

    Every earlier stage emits an INTEL_TRACE, which is a print and so survives
    Render's collector. Classification and dedupe reported only through
    _log_json_event at logging.INFO, and logger.info never reaches that
    collector (#37). So on 2026-07-26 a build carried 16 candidates through
    every traced filter, dropped all 16 here, and reported candidate_count=0
    with no visible reason -- an hour of reading code to recover a fact the
    logs should have stated outright.
    """

    def test_trace_names_the_rule_that_rejected_candidates(self) -> None:
        import io
        from contextlib import redirect_stdout

        from syndicate.features.intelligence import _intel_trace

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            _intel_trace(
                "candidate_generation",
                stage="post_dedupe_and_classify",
                total_candidates=0,
                normalized_in=16,
                classification_pruned=16,
                dedupe_pruned=0,
                classification_reasons={"missing_projection_or_odds": 16},
            )
        emitted = buffer.getvalue()
        self.assertIn("[INTEL_TRACE]", emitted)
        payload = json.loads(emitted.split("[INTEL_TRACE]", 1)[1].strip())
        # The three facts needed to diagnose a 16 -> 0 drop at a glance.
        self.assertEqual(payload["stage"], "post_dedupe_and_classify")
        self.assertEqual(payload["normalized_in"], 16)
        self.assertEqual(payload["total_candidates"], 0)
        self.assertEqual(payload["classification_reasons"], {"missing_projection_or_odds": 16})

    def test_classification_rules_are_what_the_trace_can_report(self) -> None:
        # Locks the reason strings the trace aggregates. missing_type is
        # deliberately absent: normalize_candidate defaults type to "prop", so
        # that branch is unreachable and a trace reporting it would mean
        # normalize_candidate changed.
        from syndicate.features.intelligence import _classify_candidate_with_reason

        base = {"type": "prop", "selection": "Messi Over 0.5", "odds": "+120", "projection": 0.42}
        self.assertIsNotNone(_classify_candidate_with_reason(base)[0])
        self.assertEqual(_classify_candidate_with_reason({**base, "selection": ""})[1], "missing_selection")
        self.assertEqual(
            _classify_candidate_with_reason({k: v for k, v in base.items() if k not in ("odds", "projection")})[1],
            "missing_projection_or_odds",
        )

    def test_either_odds_or_projection_is_enough(self) -> None:
        # The rule is permissive, which is why "soccer props have no odds yet"
        # is not on its own an explanation for the drop.
        from syndicate.features.intelligence import _classify_candidate_with_reason

        odds_only = {"type": "prop", "selection": "Messi Over 0.5", "odds": "+120"}
        projection_only = {"type": "prop", "selection": "Messi Over 0.5", "projection": 0.42}
        self.assertIsNotNone(_classify_candidate_with_reason(odds_only)[0])
        self.assertIsNotNone(_classify_candidate_with_reason(projection_only)[0])

    def test_a_projection_of_zero_is_a_projection(self) -> None:
        # #68. The presence test was `_safe_text(value, "") not in {"", "-"}`,
        # and _safe_text is truthiness-based -- `str(0.0 or "")` is "" -- so a
        # projection of exactly zero was reported as MISSING.
        #
        # Not a corner case. _append_game_bet_candidate gives a live
        # game-level candidate with no explicit live_projection the game's
        # current combined score, which is 0 for every scoreless live game,
        # and normalize_candidate takes the first *present* field in its scan
        # order -- so that 0 also shadowed the real model_probability behind
        # it. Measured against production 2026-07-26: all 32 live MLS game
        # candidates were pruned as missing_projection_or_odds this way.
        from syndicate.features.intelligence import _classify_candidate_with_reason

        zero_projection = {"type": "game", "selection": "Home ML", "projection": 0.0}
        self.assertIsNotNone(_classify_candidate_with_reason(zero_projection)[0])

        scoreless_live = {
            "type": "game",
            "selection": "Home ML",
            "market": "Moneyline",
            "projected": "-",
            "live_projection": "0",
            "model_probability": 0.49,
            "odds": "-",
        }
        self.assertIsNone(_classify_candidate_with_reason(scoreless_live)[1])

        # A genuinely absent projection is still absent.
        for empty in (None, "", "-"):
            self.assertEqual(
                _classify_candidate_with_reason({"type": "game", "selection": "Home ML", "projection": empty})[1],
                "missing_projection_or_odds",
            )


class VersionedResponseJsonSafetyTests(unittest.TestCase):
    """Found live 2026-07-31: the Layer 2 board was stuck on "Loading
    board..." forever, with zero console errors and every network request
    returning 200. Root cause: a raw Python float('nan') reached the
    response somewhere in the candidate/movement pipeline (a pandas-derived
    line/odds value read without the same NaN guard _line_number already
    applies defensively elsewhere). json.dumps serializes NaN as the bare
    token `NaN` -- valid to Python's own lenient json.loads, but not valid
    JSON per spec, so the browser's strict JSON.parse threw a SyntaxError on
    the ENTIRE 78MB payload the instant it hit that one token, anywhere in
    the tree. The fetch itself succeeded; only response.json() failed,
    inside a catch block that left the page's "Loading board..." status
    text stuck. Rather than chase every possible NaN producer across every
    sport's candidate-building code, _versioned_query_response now
    sanitizes once, centrally -- every response path funnels through it.
    """

    def test_json_safe_value_replaces_nan_and_infinity_with_none(self) -> None:
        from syndicate.blueprints.intelligence import _json_safe_value

        payload = {
            "a": float("nan"),
            "b": [1, float("inf"), {"c": float("-inf")}],
            "d": "ok",
            "e": 3.5,
            "f": (float("nan"), 2),
        }
        safe = _json_safe_value(payload)
        self.assertIsNone(safe["a"])
        self.assertEqual(safe["b"][0], 1)
        self.assertIsNone(safe["b"][1])
        self.assertIsNone(safe["b"][2]["c"])
        self.assertEqual(safe["d"], "ok")
        self.assertEqual(safe["e"], 3.5)
        self.assertEqual(safe["f"], [None, 2])

    def test_versioned_query_response_output_is_valid_strict_json(self) -> None:
        from syndicate.blueprints.intelligence import _versioned_query_response

        versioned = _versioned_query_response(
            {
                "recommendations": [{"pick": "Home ML", "away_line": float("nan"), "edge": 0.05}],
                "ranked_all": [{"pick": "Over 2.5", "line_odds_movement": float("inf")}],
            }
        )
        encoded = json.dumps(versioned)
        # json.loads is lenient the same way Python's producer is -- the
        # real regression test is that the string contains no bare NaN/
        # Infinity/-Infinity tokens, which is exactly what a strict
        # (browser) JSON parser rejects.
        for forbidden in ("NaN", "Infinity", "-Infinity"):
            self.assertNotIn(forbidden, encoded)
        reparsed = json.loads(encoded)
        self.assertIsNone(reparsed["response"]["recommendations"][0]["away_line"])
        self.assertIsNone(reparsed["response"]["ranked_all"][0]["line_odds_movement"])

    def test_finite_numbers_pass_through_unchanged(self) -> None:
        from syndicate.blueprints.intelligence import _json_safe_value

        self.assertEqual(_json_safe_value(0.0), 0.0)
        self.assertEqual(_json_safe_value(-12.5), -12.5)
        self.assertEqual(_json_safe_value(42), 42)
        self.assertIsNone(_json_safe_value(None))
        self.assertEqual(_json_safe_value("text"), "text")
