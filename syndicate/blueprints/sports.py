from __future__ import annotations

from flask import Blueprint, abort, current_app, render_template


sports_bp = Blueprint("syndicate_sports", __name__)


def _sport_map() -> dict[str, dict[str, str]]:
    sports = current_app.config["SYNDICATE_SPORTS"]
    return {item["slug"]: item for item in sports}


@sports_bp.get("/<sport_slug>")
def sport_hub(sport_slug: str):
    if sport_slug in {"mlb", "nba", "nhl", "nfl", "wnba", "ncaaf", "ncaab"}:
        abort(404)
    sport = _sport_map().get(sport_slug)
    if sport is None:
        abort(404)
    return render_template("sport_hub.html", sport=sport)