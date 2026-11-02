"""Women's college basketball (WNCAAB) -- lane wncaab-module, 2026-11-02.

User: "fully build a WNCAAB (womens college basketball) module from scratch using the NCAAB module
as the model". The routes mirror NCAAB's: the parity cards page (the NBA/WNBA layout in its
no-model mode) fed by `/wncaab/api/source/cards`, and the shared Layer 1 market board. Everything
reads the shared college-basketball code with `league="wncaab"`.
"""
from __future__ import annotations

from datetime import date

from flask import Blueprint, jsonify, redirect, render_template, request

from syndicate.blueprints.layer1_page import render_layer1_board
from syndicate.features.ncaab.source_cards import build_ncaab_source_cards_payload
from syndicate.features.shared.asset_version import cards_source_asset_version
from syndicate.features.shared.timezone import central_today_iso

wncaab_bp = Blueprint("syndicate_wncaab", __name__, url_prefix="/wncaab")


def _selected_date() -> str:
    return (request.args.get("date") or "").strip() or central_today_iso()


@wncaab_bp.get("")
@wncaab_bp.get("/cards")
def cards():
    selected = _selected_date()
    day = date.fromisoformat(selected)
    return render_template(
        "wncaab/cards_source.html",
        date=selected,
        prev_date=date.fromordinal(day.toordinal() - 1).isoformat(),
        next_date=date.fromordinal(day.toordinal() + 1).isoformat(),
        asset_version=cards_source_asset_version(
            "shared/standalone_shell.css", "wnba/styles.css", "wnba/cards-parity.css", "wnba/cards-parity.js"
        ),
    )


@wncaab_bp.get("/api/source/cards")
def api_source_cards():
    return jsonify(build_ncaab_source_cards_payload(_selected_date(), league="wncaab"))


@wncaab_bp.get("/market-board")
def market_board():
    return render_layer1_board("wncaab")


@wncaab_bp.get("/hub")
def hub():
    # No hub page of its own yet: the cards page is the sport's front door.
    return redirect(f"/wncaab/cards?date={_selected_date()}", code=302)
