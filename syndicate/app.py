from __future__ import annotations

import os
from typing import Callable

from flask import Flask
from syndicate.blueprints.ask_the_syndicate import ask_the_syndicate_bp
from syndicate.blueprints.home import home_bp
from syndicate.blueprints.intelligence import intelligence_bp
from syndicate.blueprints.ops import ops_bp
from syndicate.blueprints.nfl import nfl_bp
from syndicate.blueprints.nhl import nhl_bp
from syndicate.blueprints.ncaab import ncaab_bp
from syndicate.blueprints.ncaaf import ncaaf_bp
from syndicate.blueprints.nba import nba_bp
from syndicate.blueprints.mlb import mlb_bp
from syndicate.blueprints.sports import sports_bp
from syndicate.blueprints.wnba import wnba_bp
from syndicate.features.shared.live_refresh_loop import start_live_refresh_background_loop
from pipeline.intelligence_state import start_intelligence_state_background_loop


def _env_bool(name: str, *, default: bool = False) -> bool:
    raw = str(os.environ.get(name) or "").strip().lower()
    if not raw:
        return bool(default)
    return raw in {"1", "true", "yes", "on"}


def _bootstrap_render_data(bootstrap_main: Callable[[], int] | None = None) -> None:
    if not _env_bool("SYNDICATE_BOOTSTRAP_ON_START", default=False):
        return
    if bootstrap_main is None:
        try:
            from scripts.bootstrap_data_root import main as bootstrap_main  # type: ignore
        except Exception:
            return
    try:
        bootstrap_main()
    except Exception:
        return

def create_app() -> Flask:
    _bootstrap_render_data()

    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )

    if not app.config.get("SYNDICATE_SPORTS"):
        app.config["SYNDICATE_SPORTS"] = [
            {
                "slug": "mlb",
                "name": "MLB",
                "status": "Phase-1 complete",
                "phase": "Reference module",
                "summary": "Phase-1 complete reference module for the shared Syndicate board contract with cards, game detail, live lens, a daily archive, season betting-card surfaces, and stabilized shared rank-board API transport across the main ranked MLB views.",
                "primary_href": "/mlb",
                "primary_label": "Open MLB hub",
                "surfaces": ["cards", "game", "live-lens", "daily archive", "season betting-card", "hub"],
                "next_step": "Keep MLB stable as the reference module, and only extract shared board helpers where multiple migrated sports now prove the abstraction without weakening artifact-backed browser parity.",
                "runtime_contract": {
                    "dependency_tier": "owned_local",
                    "ownership_goal": "full_local",
                    "source_of_truth": "Syndicate-owned artifacts and refresh workflows",
                    "fallback_surfaces": [],
                },
            },
            {
                "slug": "nba",
                "name": "NBA",
                "status": "Active migration",
                "phase": "Artifact-backed cards + picks + live-lens + betting-card lanes",
                "summary": "NBA now has artifact-backed cards, picks, live-lens, market-accuracy, recap/features payloads, season betting-card flows, a real hub, and a stored-date daily archive under the MLB-shaped public contract, with mirrored live snapshot families covering same-day live fallback lanes.",
                "primary_href": "/nba",
                "primary_label": "Open NBA cards",
                "surfaces": ["cards", "game", "picks", "props", "live-lens", "accuracy", "recap", "features", "daily archive", "season betting-card", "hub"],
                "next_step": "Keep NBA stable on the protected artifact-backed contract, and only deepen postgame or historical lanes where mirrored stored-date artifacts already exist.",
                "runtime_contract": {
                    "dependency_tier": "artifact_backed",
                    "ownership_goal": "mirror_first",
                    "source_of_truth": "Local processed artifacts plus mirrored live snapshot families",
                    "fallback_surfaces": [],
                },
            },
            {
                "slug": "nhl",
                "name": "NHL",
                "status": "Active migration",
                "phase": "Artifact-backed cards + picks + recap + props lanes",
                "summary": "NHL now has artifact-backed cards and game drill-in surfaces in Syndicate, plus ranked picks, a season betting-card lane, native live-lens and market-accuracy pages, local betting and props reconciliation lanes, a props-lines surface, a real hub, and a stored-date daily archive built from mirrored daily artifacts.",
                "primary_href": "/nhl",
                "primary_label": "Open NHL cards",
                "surfaces": ["cards", "game", "live-lens", "accuracy", "recap", "props reconciliation", "props lines", "picks", "daily archive", "season betting-card", "hub"],
                "next_step": "Keep NHL stable on the protected artifact-backed contract, and only deepen settled-history lanes where mirrored daily artifacts can support native views.",
                "runtime_contract": {
                    "dependency_tier": "artifact_backed",
                    "ownership_goal": "mirror_first",
                    "source_of_truth": "Mirrored daily artifacts with public schedule augmentation",
                    "fallback_surfaces": [],
                },
            },
            {
                "slug": "nfl",
                "name": "NFL",
                "status": "Near completion candidate",
                "phase": "Cards + game + grouped picks + betting card",
                "summary": "NFL now has snapshot-backed cards and game drill-ins in Syndicate, alongside grouped weekly picks, a read-only live-lens monitor, a weekly daily archive, source-style picks payload aliases, and a season betting-card companion built from the same stored snapshot lane.",
                "primary_href": "/nfl",
                "primary_label": "Open NFL cards",
                "surfaces": ["cards", "game", "picks", "live-lens", "daily archive", "season betting-card", "hub"],
                "next_step": "Keep NFL stable as the next module-family completion candidate, now that weekly snapshots back cards, live lens, archive, and betting-card lanes under the same artifact-backed contract.",
                "runtime_contract": {
                    "dependency_tier": "artifact_backed",
                    "ownership_goal": "mirror_first",
                    "source_of_truth": "Weekly stored snapshots mirrored into Syndicate",
                    "fallback_surfaces": [],
                },
            },
            {
                "slug": "wnba",
                "name": "WNBA",
                "status": "Active migration",
                "phase": "Artifact-backed shared board + picks + props + live audit lanes",
                "summary": "WNBA now exposes shared cards, picks, props, game detail, a real hub, a first season betting-card lane, MLB-style live-lens routes, a stored-date daily archive lane, and native local accuracy/audit payloads in Syndicate.",
                "primary_href": "/wnba",
                "primary_label": "Open WNBA cards",
                "surfaces": ["cards", "game", "picks", "props", "live-lens", "daily archive", "season betting-card", "hub"],
                "next_step": "Keep WNBA stable on the protected artifact-backed contract, and only deepen historical coverage where repeated stored dates already exist in the mirrored processed lane.",
                "runtime_contract": {
                    "dependency_tier": "artifact_backed",
                    "ownership_goal": "mirror_first",
                    "source_of_truth": "Shared stored-date artifacts plus native local live audit payloads",
                    "fallback_surfaces": [],
                },
            },
            {
                "slug": "ncaaf",
                "name": "NCAAF",
                "status": "Active migration",
                "phase": "Artifact-backed weekly cards + picks + betting-card lanes",
                "summary": "NCAAF now has artifact-backed weekly cards, game drill-ins, picks, a read-only live-lens monitor, a weekly daily archive, and a season betting-card companion in Syndicate, built from stored recommendation summaries while the live source feed is offseason-empty.",
                "primary_href": "/ncaaf",
                "primary_label": "Open NCAAF cards",
                "surfaces": ["cards", "game", "picks", "live-lens", "daily archive", "season betting-card", "hub"],
                "next_step": "Keep NCAAF stable on the protected artifact-backed weekly contract until the live source workflow repopulates, then decide whether live-lens or archive wrappers need richer native views.",
                "runtime_contract": {
                    "dependency_tier": "artifact_backed",
                    "ownership_goal": "mirror_first",
                    "source_of_truth": "Syndicate-local weekly snapshots",
                    "fallback_surfaces": [],
                },
            },
            {
                "slug": "ncaab",
                "name": "NCAAB",
                "status": "Active migration",
                "phase": "Mirror-first cards + game + live-lens + historical lanes",
                "summary": "NCAAB now runs cards, game detail, live lens, season review, the historical betting-card companion, and the daily archive from mirrored artifacts inside Syndicate.",
                "primary_href": "/ncaab",
                "primary_label": "Open NCAAB cards",
                "surfaces": ["cards", "game", "live-lens", "daily archive", "season review", "season betting-card", "hub"],
                "next_step": "Keep NCAAB stable as the mirror-first college basketball reference module, and only deepen historical or live wrappers where mirrored artifacts already justify the surface.",
                "runtime_contract": {
                    "dependency_tier": "artifact_backed",
                    "ownership_goal": "mirror_first",
                    "source_of_truth": "Local mirrored NCAAB artifacts refreshed from the source app",
                    "fallback_surfaces": [],
                },
            },
        ]

    @app.context_processor
    def inject_syndicate_sports() -> dict[str, object]:
        return {"syndicate_sports": app.config.get("SYNDICATE_SPORTS", [])}

    app.register_blueprint(home_bp)
    app.register_blueprint(intelligence_bp)
    app.register_blueprint(ask_the_syndicate_bp)
    app.register_blueprint(ops_bp)
    app.register_blueprint(mlb_bp)
    app.register_blueprint(nba_bp)
    app.register_blueprint(nhl_bp)
    app.register_blueprint(nfl_bp)
    app.register_blueprint(wnba_bp)
    app.register_blueprint(ncaaf_bp)
    app.register_blueprint(ncaab_bp)
    app.register_blueprint(sports_bp)

    start_live_refresh_background_loop()
    start_intelligence_state_background_loop(app)
    return app


app = create_app()