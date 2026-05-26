from __future__ import annotations

from datetime import date
from datetime import datetime, timedelta
from pathlib import Path

from flask import Blueprint, jsonify, render_template, request

from syndicate.features.shared.game_board_contract import build_game_board_api_payload
from syndicate.features.shared.rank_board import build_rank_api_payload
from syndicate.features.mlb.betting_card import build_betting_card_page_context
from syndicate.features.mlb.cards import build_cards_page_context
from syndicate.features.mlb.cards import source_card_detail_payload
from syndicate.features.mlb.cards import source_cards_api_payload
from syndicate.features.mlb.daily_archive import build_daily_archive_api_payload
from syndicate.features.mlb.daily_archive import build_daily_archive_page_context
from syndicate.features.mlb.game_detail import build_game_detail_page_context
from syndicate.features.mlb.hub import build_hub_context
from syndicate.features.mlb.hitter_ladders import build_hitter_ladders_page_context
from syndicate.features.mlb.hr_targets import build_hr_targets_page_context
from syndicate.features.mlb.live_lens import build_live_lens_api_payload
from syndicate.features.mlb.live_lens import build_live_lens_page_context
from syndicate.features.mlb.live_lens_daily_accuracy import build_live_lens_daily_accuracy_payload
from syndicate.features.mlb.market_accuracy import build_market_accuracy_payload
from syndicate.features.mlb.pitcher_ladders import build_pitcher_ladders_page_context
from syndicate.features.mlb.rfi_targets import build_rfi_targets_page_context
from syndicate.features.mlb.season import build_season_page_context
from syndicate.features.mlb.sources import available_daily_summary_dates
from syndicate.features.mlb.sources import load_json_file
from syndicate.features.mlb.sources import season_betting_card_day_path
from syndicate.features.mlb.sources import season_eval_manifest_path
from syndicate.features.mlb.sources import season_frontend_day_path
from syndicate.features.mlb.top_props import build_top_props_page_context
from syndicate.features.shared.timezone import central_today
from syndicate.features.shared.timezone import central_today_iso
from syndicate.features.shared.timezone import central_year


mlb_bp = Blueprint("syndicate_mlb", __name__, url_prefix="/mlb")


def _cards_source_asset_version() -> str:
    static_root = Path(__file__).resolve().parents[1] / "static"
    paths = [
        static_root / "shared" / "standalone_shell.css",
        static_root / "mlb" / "cards_exact.css",
        static_root / "mlb" / "cards_source.js",
        static_root / "mlb" / "back_to_top.js",
    ]
    mtimes: list[int] = []
    for path in paths:
        try:
            mtimes.append(int(path.stat().st_mtime_ns))
        except OSError:
            continue
    if mtimes:
        return str(max(mtimes))
    return "1"


def _iso_or_today(value: str | None) -> str:
    text = str(value or "").strip()
    if text:
        return text
    return central_today_iso()


def _path_label(path: Path | None) -> str | None:
    return str(path) if path is not None else None


def _app_meta() -> dict:
    return {
        "service": "syndicate",
        "sport": "mlb",
        "generatedAt": central_today_iso(),
    }


def _date_nav(selected_date: str) -> dict:
    try:
        parsed = datetime.strptime(selected_date, "%Y-%m-%d").date()
    except Exception:
        parsed = central_today()
    return {
        "prevDate": (parsed - timedelta(days=1)).isoformat(),
        "nextDate": (parsed + timedelta(days=1)).isoformat(),
    }


def _load_context_source(context: dict) -> dict | None:
    path_value = context.get("source_path")
    if not path_value:
        return None
    return load_json_file(Path(str(path_value)))


def _artifact_side_group(artifact: dict | None, side: str) -> dict:
    groups = artifact.get("groups") if isinstance(artifact, dict) and isinstance(artifact.get("groups"), dict) else {}
    return groups.get(side) if isinstance(groups.get(side), dict) else {}


def _artifact_prop_group(artifact: dict | None, side: str, requested_prop: str, fallback_prop: str) -> dict:
    side_group = _artifact_side_group(artifact, side)
    requested_key = str(requested_prop or fallback_prop).strip() or fallback_prop
    group = side_group.get(requested_key) if isinstance(side_group.get(requested_key), dict) else {}
    if group:
        return group
    return side_group.get(fallback_prop) if isinstance(side_group.get(fallback_prop), dict) else {}


def _rank_payload(context: dict, extra: dict | None = None, *, include_app: bool = False) -> dict:
    payload = build_rank_api_payload(context)
    if extra:
        payload.update(extra)
    if include_app:
        payload["app"] = _app_meta()
    return payload


def _hr_target_options(rows: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    game_map: dict[str, dict] = {}
    team_map: dict[str, dict] = {}
    hitter_map: dict[str, dict] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        matchup = str(row.get("matchup") or "").strip()
        team = str(row.get("team") or "").strip()
        hitter = str(row.get("player_name") or "").strip()
        game_pk = int(row.get("game_pk") or 0)
        if matchup and matchup not in game_map:
            game_map[matchup] = {"value": str(game_pk) if game_pk else matchup, "label": matchup, "gamePk": game_pk or None, "matchup": matchup}
        if team and team not in team_map:
            team_map[team] = {"value": team, "label": team}
        if hitter and hitter not in hitter_map:
            hitter_map[hitter] = {"value": hitter, "label": hitter, "team": team or None}
    return list(game_map.values()), list(team_map.values()), list(hitter_map.values())


def _season_months_from_days(days: list[dict]) -> list[dict]:
    buckets: dict[str, int] = {}
    for day in days:
        if not isinstance(day, dict):
            continue
        day_value = str(day.get("date") or "").strip()
        if len(day_value) < 7:
            continue
        month = day_value[:7]
        buckets[month] = buckets.get(month, 0) + 1
    return [{"month": month, "days": count} for month, count in sorted(buckets.items())]


def _season_manifest_payload(season: int) -> dict:
    manifest_path = season_eval_manifest_path(int(season))
    manifest = load_json_file(manifest_path)
    if not isinstance(manifest, dict):
        return {
            "season": int(season),
            "found": False,
            "source_path": _path_label(manifest_path),
            "manifest": {},
        }
    payload = dict(manifest)
    payload["found"] = True
    payload["season"] = int(season)
    payload["artifactPath"] = _path_label(manifest_path)
    payload["artifactSource"] = "season_eval_manifest"
    payload["artifactDate"] = str((manifest.get("artifactDate") or manifest.get("date") or "")).strip() or None
    payload["app"] = _app_meta()
    payload["manifest"] = dict(manifest)
    payload["source_path"] = _path_label(manifest_path)
    return payload


def _season_day_payload(season: int, date_str: str, profile: str) -> tuple[dict, int]:
    day_path = season_frontend_day_path(int(season), date_str, profile=profile)
    payload = load_json_file(day_path)
    if isinstance(payload, dict):
        out = dict(payload)
        out.setdefault("season", int(season))
        out.setdefault("date", str(date_str))
        out["found"] = True
        out["source_path"] = _path_label(day_path)
        return out, 200
    context = build_season_page_context(int(season), date_str, profile=profile)
    return {
        "season": int(season),
        "date": str(date_str),
        "found": False,
        "source_path": _path_label(day_path),
        "games": context.get("games", []),
        "scoreboard": context.get("scoreboard_items", []),
        "using_sample_data": context.get("using_sample_data", False),
    }, 404


def _season_betting_day_payload(season: int, date_str: str, profile: str) -> tuple[dict, int]:
    card_path = season_betting_card_day_path(int(season), date_str, profile=profile)
    payload = load_json_file(card_path)
    if isinstance(payload, dict):
        out = dict(payload)
        out.setdefault("season", int(season))
        out.setdefault("date", str(date_str))
        out["found"] = True
        out["source_path"] = _path_label(card_path)
        return out, 200
    context = build_betting_card_page_context(int(season), date_str, profile=profile)
    return {
        "season": int(season),
        "date": str(date_str),
        "found": False,
        "source_path": _path_label(card_path),
        "rank_cards": context.get("rank_cards", []),
        "using_sample_data": context.get("using_sample_data", False),
    }, 404


def _season_betting_manifest_payload(season: int, profile: str) -> dict:
    profile_slug = (profile or "retuned").strip() or "retuned"
    root = season_betting_card_day_path(int(season), central_today_iso(), profile=profile_slug).parent
    entries = []
    if root.exists() and root.is_dir():
        for path in sorted(root.glob(f"season_betting_day_{int(season)}_*.json")):
            stem = path.stem.removeprefix(f"season_betting_day_{int(season)}_")
            if len(stem) == 10 and stem[4] == "_" and stem[7] == "_":
                date_str = f"{stem[:4]}-{stem[5:7]}-{stem[8:10]}"
            else:
                date_str = stem.replace("_", "-")
            entries.append({"date": date_str, "source_path": _path_label(path)})
    months = _season_months_from_days(entries)
    return {
        "season": int(season),
        "profile": profile_slug,
        "found": bool(entries),
        "available_days": entries,
        "days": entries,
        "months": months,
        "available_profiles": [profile_slug],
        "status": "ok" if entries else "missing",
        "source_kind": "artifact_backed",
        "summary": {"days": len(entries), "months": len(months)},
        "meta": {"sourceDir": _path_label(root)},
        "app": _app_meta(),
        "source_path": _path_label(root),
    }


def _live_lens_daily_accuracy_template_context(selected_date: str) -> dict[str, object]:
    season = int(selected_date[:4]) if len(selected_date) >= 4 and selected_date[:4].isdigit() else central_year()
    return {
        "date": selected_date,
        "season": season,
        "api_path": "/mlb/api/live-lens-accuracy",
        "back_href": f"/mlb/cards?date={selected_date}",
        "back_label": "Cards",
        "self_href": f"/mlb/live-lens-accuracy?date={selected_date}",
        "live_lens_href": f"/mlb/live-lens?date={selected_date}",
    }


def _market_accuracy_template_context(selected_date: str) -> dict[str, object]:
    season = int(selected_date[:4]) if len(selected_date) >= 4 and selected_date[:4].isdigit() else central_year()
    return {
        "date": selected_date,
        "season": season,
        "api_path": "/mlb/api/market-accuracy",
        "back_href": f"/mlb/cards?date={selected_date}",
        "back_label": "Cards",
        "self_href": f"/mlb/market-accuracy?date={selected_date}",
        "live_lens_href": f"/mlb/live-lens?date={selected_date}",
        "daily_accuracy_href": f"/mlb/live-lens-accuracy?date={selected_date}",
    }


@mlb_bp.get("/hub")
def hub():
    return render_template("mlb/hub.html", **build_hub_context())


@mlb_bp.get("")
def root_cards():
    return cards()


@mlb_bp.get("/cards")
def cards():
    selected_date = _iso_or_today(request.args.get("date"))
    context = build_cards_page_context(selected_date)
    context["show_home_link"] = False
    embed_mode = (request.args.get("embed") or "").strip().lower()
    client = (request.args.get("client") or "").strip().lower()
    if client != "board":
        context["cards_script"] = "mlb/cards_source.js"
        context["asset_version"] = _cards_source_asset_version()
        if client == "source":
            context["cards_client"] = "source"
            source_meta_items = context.get("source_meta_items") if isinstance(context.get("source_meta_items"), list) else []
            context["source_meta_items"] = source_meta_items + ["Client source-preview"]
    else:
        context["cards_client"] = "board"
        return render_template("shared/game_cards_board.html", **context)
    if embed_mode:
        context["embed_mode"] = embed_mode
        return render_template("mlb/cards_embed.html", **context)
    return render_template("mlb/cards.html", **context)


@mlb_bp.get("/api/cards")
def api_cards():
    selected_date = _iso_or_today(request.args.get("date"))
    context = build_cards_page_context(selected_date)
    payload = build_game_board_api_payload(context)
    payload.update(source_cards_api_payload(context))
    payload["app"] = _app_meta()
    requested_client = str(request.args.get("client") or "").strip().lower()
    effective_client = "board" if requested_client == "board" else "source"
    payload["view"] = {"client": effective_client}
    payload["sources"] = {
        "primary": context.get("source_path"),
        "hrTargets": ((payload.get("hrTargets") or {}).get("sourcePath")),
    }
    return jsonify(payload)


@mlb_bp.get("/api/game/<int:game_pk>/card-detail")
def api_card_detail(game_pk: int):
    selected_date = _iso_or_today(request.args.get("date"))
    payload = source_card_detail_payload(selected_date, game_pk)
    found = bool(isinstance(payload.get("snapshot"), dict) or ((payload.get("sim") or {}).get("found")))
    payload["found"] = found
    payload["error"] = None if found else "card_detail_missing"
    payload["generatedAt"] = central_today_iso()
    return jsonify(payload)


@mlb_bp.get("/api/schedule")
def api_schedule():
    selected_date = _iso_or_today(request.args.get("date"))
    context = build_cards_page_context(selected_date)
    games = context.get("games") if isinstance(context.get("games"), list) else []
    payload_games = []
    for game in games:
        if not isinstance(game, dict):
            continue
        status = game.get("status") if isinstance(game.get("status"), dict) else {}
        probable = game.get("probable") if isinstance(game.get("probable"), dict) else {}
        payload_games.append(
            {
                "gamePk": int(game.get("gamePk") or 0),
                "officialDate": str(game.get("officialDate") or selected_date),
                "gameDate": str(game.get("gameDate") or ""),
                "gameType": str(game.get("gameType") or ""),
                "status": {
                    "abstract": str(status.get("abstract") or game.get("status_badge") or game.get("status") or "").strip(),
                    "detailed": str(status.get("detailed") or game.get("detail") or game.get("status") or "").strip(),
                },
                "away": game.get("away") if isinstance(game.get("away"), dict) else {},
                "home": game.get("home") if isinstance(game.get("home"), dict) else {},
                "probable": {
                    "away": probable.get("away") if isinstance(probable.get("away"), dict) else {},
                    "home": probable.get("home") if isinstance(probable.get("home"), dict) else {},
                },
            }
        )
    return jsonify({"date": selected_date, "games": payload_games})


@mlb_bp.get("/api/game/<int:game_pk>/snapshot")
def api_game_snapshot(game_pk: int):
    selected_date = _iso_or_today(request.args.get("date"))
    payload = source_card_detail_payload(selected_date, game_pk)
    snapshot = payload.get("snapshot") if isinstance(payload.get("snapshot"), dict) else None
    if not snapshot:
        return jsonify({"gamePk": int(game_pk), "date": selected_date, "found": False, "error": "snapshot_missing"}), 404
    return jsonify(snapshot)


@mlb_bp.get("/hr-targets")
def hr_targets():
    selected_date = _iso_or_today(request.args.get("date"))
    context = build_hr_targets_page_context(selected_date)
    return render_template("shared/rank_board.html", **context)


@mlb_bp.get("/api/hr-targets")
def api_hr_targets():
    selected_date = _iso_or_today(request.args.get("date"))
    context = build_hr_targets_page_context(selected_date)
    artifact = _load_context_source(context) or {}
    rows = artifact.get("rows") if isinstance(artifact.get("rows"), list) else []
    game_options, team_options, hitter_options = _hr_target_options(rows)
    payload = _rank_payload(
        context,
        {
            "targets": context["targets"],
            "rows": rows,
            "games": game_options,
            "counts": {
                "rows": len(rows),
                "games": len(game_options),
                "teams": len(team_options),
            },
            "found": bool(rows),
            "nav": _date_nav(selected_date),
            "gameOptions": game_options,
            "teamOptions": team_options,
            "hitterOptions": hitter_options,
            "sortOptions": [
                {"value": "probability", "label": "Probability"},
                {"value": "support", "label": "Support"},
            ],
            "selectedGame": str(request.args.get("game") or "").strip(),
            "selectedTeam": str(request.args.get("team") or "").strip(),
            "selectedHitter": str(request.args.get("hitter") or "").strip(),
            "selectedSort": str(request.args.get("sort") or "probability").strip() or "probability",
            "policy": artifact.get("policy") if isinstance(artifact.get("policy"), dict) else {},
            "reconciliation": artifact.get("diagnostics") if isinstance(artifact.get("diagnostics"), dict) else {},
            "sourcePath": context["source_path"],
        },
        include_app=True,
    )
    return jsonify(payload)


@mlb_bp.get("/rfi-targets")
def rfi_targets():
    selected_date = _iso_or_today(request.args.get("date"))
    context = build_rfi_targets_page_context(selected_date)
    return render_template("shared/rank_board.html", **context)


@mlb_bp.get("/api/rfi-targets")
def api_rfi_targets():
    selected_date = _iso_or_today(request.args.get("date"))
    context = build_rfi_targets_page_context(selected_date)
    return jsonify(_rank_payload(context, {"signals": context["signals"]}))


@mlb_bp.get("/pitcher-ladders")
def pitcher_ladders():
    selected_date = _iso_or_today(request.args.get("date"))
    context = build_pitcher_ladders_page_context(selected_date)
    return render_template("shared/rank_board.html", **context)


@mlb_bp.get("/api/pitcher-ladders")
def api_pitcher_ladders():
    selected_date = _iso_or_today(request.args.get("date"))
    context = build_pitcher_ladders_page_context(selected_date)
    artifact = _load_context_source(context) or {}
    group = _artifact_prop_group(artifact, "pitcher", str(request.args.get("prop") or "strikeouts"), "strikeouts")
    payload = _rank_payload(
        context,
        {
            "rows": context["rows"],
            "found": bool(context["rows"]),
            "nav": _date_nav(selected_date),
            "prop": str((group or {}).get("prop") or "strikeouts"),
            "propLabel": str((group or {}).get("propLabel") or "Strikeouts"),
            "propUnit": str((group or {}).get("propUnit") or "K"),
            "propOptions": list((group or {}).get("propOptions") or []),
            "selectedGame": str(request.args.get("game") or (group or {}).get("selectedGame") or "").strip(),
            "selectedPitcher": str(request.args.get("pitcher") or (group or {}).get("selectedPitcher") or "").strip(),
            "selectedSort": str(request.args.get("sort") or (group or {}).get("selectedSort") or "").strip(),
            "gameOptions": list((group or {}).get("gameOptions") or []),
            "pitcherOptions": list((group or {}).get("pitcherOptions") or []),
            "sortOptions": list((group or {}).get("sortOptions") or []),
            "summary": (group or {}).get("summary") if isinstance((group or {}).get("summary"), dict) else {},
            "featuredRow": ((group or {}).get("rows") or [None])[0] if isinstance((group or {}).get("rows"), list) and (group or {}).get("rows") else None,
            "artifactGeneratedAt": artifact.get("generatedAt"),
            "artifactPath": context["source_path"],
            "artifactSource": "daily_ladders",
            "sourceDir": str(Path(context["source_path"]).parent),
            "marketMode": (group or {}).get("marketMode"),
            "marketSource": (group or {}).get("marketSource"),
            "pregameMarketSource": (group or {}).get("pregameMarketSource"),
            "historyMode": (group or {}).get("historyMode"),
            "defaultSims": (group or {}).get("defaultSims"),
            "reconciliation": (group or {}).get("reconciliation") if isinstance((group or {}).get("reconciliation"), dict) else {},
        },
        include_app=True,
    )
    return jsonify(payload)


@mlb_bp.get("/hitter-ladders")
def hitter_ladders():
    selected_date = _iso_or_today(request.args.get("date"))
    context = build_hitter_ladders_page_context(selected_date)
    return render_template("shared/rank_board.html", **context)


@mlb_bp.get("/api/hitter-ladders")
def api_hitter_ladders():
    selected_date = _iso_or_today(request.args.get("date"))
    context = build_hitter_ladders_page_context(selected_date)
    artifact = _load_context_source(context) or {}
    group = _artifact_prop_group(artifact, "hitter", str(request.args.get("prop") or "hits"), "hits")
    payload = _rank_payload(
        context,
        {
            "rows": context["rows"],
            "found": bool(context["rows"]),
            "nav": _date_nav(selected_date),
            "prop": str((group or {}).get("prop") or "hits"),
            "propLabel": str((group or {}).get("propLabel") or "Hits"),
            "propUnit": str((group or {}).get("propUnit") or "H"),
            "propOptions": list((group or {}).get("propOptions") or []),
            "selectedGame": str(request.args.get("game") or (group or {}).get("selectedGame") or "").strip(),
            "selectedTeam": str(request.args.get("team") or (group or {}).get("selectedTeam") or "").strip(),
            "selectedHitter": str(request.args.get("hitter") or (group or {}).get("selectedHitter") or "").strip(),
            "selectedSort": str(request.args.get("sort") or (group or {}).get("selectedSort") or "").strip(),
            "gameOptions": list((group or {}).get("gameOptions") or []),
            "teamOptions": list((group or {}).get("teamOptions") or []),
            "hitterOptions": list((group or {}).get("hitterOptions") or []),
            "sortOptions": list((group or {}).get("sortOptions") or []),
            "summary": (group or {}).get("summary") if isinstance((group or {}).get("summary"), dict) else {},
            "featuredRow": ((group or {}).get("rows") or [None])[0] if isinstance((group or {}).get("rows"), list) and (group or {}).get("rows") else None,
            "artifactGeneratedAt": artifact.get("generatedAt"),
            "artifactPath": context["source_path"],
            "artifactSource": "daily_ladders",
            "sourceDir": str(Path(context["source_path"]).parent),
            "marketMode": (group or {}).get("marketMode"),
            "marketSource": (group or {}).get("marketSource"),
            "historyMode": (group or {}).get("historyMode"),
            "defaultSims": (group or {}).get("defaultSims"),
            "ladderShape": (group or {}).get("ladderShape"),
            "reconciliation": (group or {}).get("reconciliation") if isinstance((group or {}).get("reconciliation"), dict) else {},
        },
        include_app=True,
    )
    return jsonify(payload)


@mlb_bp.get("/top-props")
def top_props():
    selected_date = _iso_or_today(request.args.get("date"))
    context = build_top_props_page_context(selected_date, group="pitcher")
    return render_template("shared/rank_board.html", **context)


@mlb_bp.get("/api/top-props")
def api_top_props():
    selected_date = _iso_or_today(request.args.get("date"))
    context = build_top_props_page_context(selected_date, group="pitcher")
    return jsonify(_rank_payload(context))


@mlb_bp.get("/archive")
def daily_archive():
    selected_date = _iso_or_today(request.args.get("date"))
    context = build_daily_archive_page_context(selected_date)
    return render_template("shared/rank_board.html", **context)


@mlb_bp.get("/api/archive")
def api_daily_archive():
    selected_date = _iso_or_today(request.args.get("date"))
    return jsonify(build_daily_archive_api_payload(selected_date))


@mlb_bp.get("/pitcher-top-props")
def pitcher_top_props():
    selected_date = _iso_or_today(request.args.get("date"))
    context = build_top_props_page_context(selected_date, group="pitcher")
    context["group"] = "pitcher"
    context["groupLabel"] = "Pitcher"
    context["title"] = "Pitcher Top Props"
    context["season"] = int(selected_date[:4]) if len(selected_date) >= 4 and selected_date[:4].isdigit() else central_year()
    context["embed_mode"] = (request.args.get("embed") or "").strip().lower() or None
    return render_template("mlb/daily_top_props.html", **context)


@mlb_bp.get("/api/pitcher-top-props")
def api_pitcher_top_props():
    selected_date = _iso_or_today(request.args.get("date"))
    context = build_top_props_page_context(selected_date, group="pitcher")
    artifact = _load_context_source(context) or {}
    group = _artifact_side_group(artifact, "pitcher")
    payload = _rank_payload(
        context,
        {
            "found": bool(context["rank_cards"]),
            "group": "pitcher",
            "groupLabel": str(group.get("groupLabel") or "Pitcher"),
            "title": str(group.get("title") or context.get("intro_title") or "Pitcher Top Props"),
            "defaultStat": str(group.get("defaultStat") or "strikeouts"),
            "defaultGame": str(group.get("defaultGame") or ""),
            "gameOptions": list(group.get("gameOptions") or []),
            "nav": group.get("nav") if isinstance(group.get("nav"), dict) else _date_nav(selected_date),
            "marketMode": group.get("marketMode"),
            "marketSource": group.get("marketSource"),
            "reconciliation": group.get("reconciliation") if isinstance(group.get("reconciliation"), dict) else {},
            "sections": list(group.get("sections") or []),
            "summary": group.get("summary") if isinstance(group.get("summary"), dict) else {},
            "season": group.get("season") or int(selected_date[:4]),
            "artifactGeneratedAt": artifact.get("generatedAt"),
            "artifactPath": context["source_path"],
            "artifactSource": "daily_top_props",
        },
        include_app=True,
    )
    return jsonify(payload)


@mlb_bp.get("/hitter-top-props")
def hitter_top_props():
    selected_date = _iso_or_today(request.args.get("date"))
    context = build_top_props_page_context(selected_date, group="hitter")
    context["group"] = "hitter"
    context["groupLabel"] = "Hitter"
    context["title"] = "Hitter Top Props"
    context["season"] = int(selected_date[:4]) if len(selected_date) >= 4 and selected_date[:4].isdigit() else central_year()
    context["embed_mode"] = (request.args.get("embed") or "").strip().lower() or None
    return render_template("mlb/daily_top_props.html", **context)


@mlb_bp.get("/api/hitter-top-props")
def api_hitter_top_props():
    selected_date = _iso_or_today(request.args.get("date"))
    context = build_top_props_page_context(selected_date, group="hitter")
    artifact = _load_context_source(context) or {}
    group = _artifact_side_group(artifact, "hitter")
    payload = _rank_payload(
        context,
        {
            "found": bool(context["rank_cards"]),
            "group": "hitter",
            "groupLabel": str(group.get("groupLabel") or "Hitter"),
            "title": str(group.get("title") or context.get("intro_title") or "Hitter Top Props"),
            "defaultStat": str(group.get("defaultStat") or "hits"),
            "defaultGame": str(group.get("defaultGame") or ""),
            "gameOptions": list(group.get("gameOptions") or []),
            "nav": group.get("nav") if isinstance(group.get("nav"), dict) else _date_nav(selected_date),
            "marketMode": group.get("marketMode"),
            "marketSource": group.get("marketSource"),
            "reconciliation": group.get("reconciliation") if isinstance(group.get("reconciliation"), dict) else {},
            "sections": list(group.get("sections") or []),
            "summary": group.get("summary") if isinstance(group.get("summary"), dict) else {},
            "season": group.get("season") or int(selected_date[:4]),
            "artifactGeneratedAt": artifact.get("generatedAt"),
            "artifactPath": context["source_path"],
            "artifactSource": "daily_top_props",
        },
        include_app=True,
    )
    return jsonify(payload)


@mlb_bp.get("/season/<int:season>")
def season(season: int):
    selected_date = _iso_or_today(request.args.get("date"))
    profile = (request.args.get("profile") or "retuned").strip() or "retuned"
    context = build_season_page_context(season, selected_date, profile=profile)
    return render_template("shared/game_cards_board.html", **context)


@mlb_bp.get("/api/season/<int:season>")
def api_season(season: int):
    payload = _season_manifest_payload(int(season))
    status_code = 200 if payload.get("found") else 404
    return jsonify(payload), status_code


@mlb_bp.get("/api/season/<int:season>/board")
def api_season_board(season: int):
    selected_date = _iso_or_today(request.args.get("date"))
    profile = (request.args.get("profile") or "retuned").strip() or "retuned"
    context = build_season_page_context(season, selected_date, profile=profile)
    return jsonify(build_game_board_api_payload(context))


@mlb_bp.get("/api/season/<int:season>/day/<date_str>")
def api_season_day(season: int, date_str: str):
    profile = (request.args.get("profile") or "retuned").strip() or "retuned"
    payload, status_code = _season_day_payload(int(season), str(date_str), profile)
    payload["artifactPath"] = payload.get("source_path")
    payload["artifactSource"] = "season_day"
    payload["app"] = _app_meta()
    return jsonify(payload), status_code


@mlb_bp.get("/game/<int:game_pk>")
def game_detail(game_pk: int):
    selected_date = _iso_or_today(request.args.get("date"))
    context = build_game_detail_page_context(selected_date, game_pk)
    return render_template("shared/game_cards_board.html", **context)


@mlb_bp.get("/api/game/<int:game_pk>")
def api_game_detail(game_pk: int):
    selected_date = _iso_or_today(request.args.get("date"))
    context = build_game_detail_page_context(selected_date, game_pk)
    return jsonify(build_game_board_api_payload(context))


@mlb_bp.get("/live-lens")
def live_lens():
    selected_date = _iso_or_today(request.args.get("date"))
    context = {
        "date": selected_date,
        "season": None,
        "intro_title": "MLB Live Lens",
        "api_path": "/mlb/api/live-lens",
        "back_href": f"/mlb/cards?date={selected_date}",
        "back_label": "Back to cards",
        "daily_accuracy_href": f"/mlb/live-lens-accuracy?date={selected_date}",
        "market_accuracy_href": f"/mlb/market-accuracy?date={selected_date}",
        "form_action": "/mlb/live-lens",
        "show_app_header": False,
        "page_body_class": "syndicate-mlb-live-lens-page",
        "page_shell_class": "syndicate-mlb-live-lens-shell",
    }
    return render_template("mlb/live_lens.html", **context)


@mlb_bp.get("/api/live-lens")
def api_live_lens():
    selected_date = _iso_or_today(request.args.get("date"))
    context = build_live_lens_page_context(selected_date)
    return jsonify(build_live_lens_api_payload(context))


@mlb_bp.get("/live-lens-accuracy")
def live_lens_accuracy():
    selected_date = _iso_or_today(request.args.get("date"))
    return render_template("mlb/live_lens_daily_accuracy.html", **_live_lens_daily_accuracy_template_context(selected_date))


@mlb_bp.get("/api/live-lens-accuracy")
def api_live_lens_accuracy():
    payload = build_live_lens_daily_accuracy_payload(request.query_string.decode("utf-8") if request.query_string else "")
    if not isinstance(payload, dict):
        return jsonify({"ok": False, "error": "failed to load live lens daily accuracy"}), 502
    return jsonify(payload)


@mlb_bp.get("/market-accuracy")
def market_accuracy():
    selected_date = _iso_or_today(request.args.get("date"))
    return render_template("mlb/market_accuracy.html", **_market_accuracy_template_context(selected_date))


@mlb_bp.get("/api/market-accuracy")
def api_market_accuracy():
    payload = build_market_accuracy_payload(request.query_string.decode("utf-8") if request.query_string else "")
    if not isinstance(payload, dict):
        return jsonify({"ok": False, "error": "failed to load market accuracy"}), 502
    return jsonify(payload)


@mlb_bp.get("/season/<int:season>/live-lens")
def season_live_lens(season: int):
    selected_date = _iso_or_today(request.args.get("date"))
    context = {
        "date": selected_date,
        "season": int(season),
        "intro_title": f"MLB {int(season)} Live Lens",
        "api_path": f"/mlb/api/season/{int(season)}/live-lens",
        "back_href": f"/mlb/season/{int(season)}/betting-card?date={selected_date}",
        "back_label": "Back to betting card",
        "daily_accuracy_href": f"/mlb/live-lens-accuracy?date={selected_date}",
        "market_accuracy_href": f"/mlb/market-accuracy?date={selected_date}",
        "form_action": f"/mlb/season/{int(season)}/live-lens",
        "show_app_header": False,
        "page_body_class": "cards-body syndicate-mlb-live-lens-page syndicate-mlb-live-lens-page--season",
        "page_shell_class": "syndicate-mlb-live-lens-shell",
    }
    return render_template("mlb/live_lens.html", **context)


@mlb_bp.get("/api/season/<int:season>/live-lens")
def api_season_live_lens(season: int):
    selected_date = _iso_or_today(request.args.get("date"))
    context = build_live_lens_page_context(selected_date, season=season)
    return jsonify(build_live_lens_api_payload(context))


@mlb_bp.get("/season/<int:season>/betting-card")
def betting_card(season: int):
    selected_date = _iso_or_today(request.args.get("date"))
    profile = (request.args.get("profile") or "retuned").strip() or "retuned"
    context = build_betting_card_page_context(season, selected_date, profile=profile)
    return render_template("shared/rank_board.html", **context)


@mlb_bp.get("/api/season/<int:season>/betting-card")
def api_betting_card(season: int):
    selected_date = _iso_or_today(request.args.get("date"))
    profile = (request.args.get("profile") or "retuned").strip() or "retuned"
    context = build_betting_card_page_context(season, selected_date, profile=profile)
    return jsonify(_rank_payload(context))


@mlb_bp.get("/api/season/<int:season>/betting-cards")
def api_betting_cards_manifest(season: int):
    profile = (request.args.get("profile") or "retuned").strip() or "retuned"
    payload = _season_betting_manifest_payload(int(season), profile)
    status_code = 200 if payload.get("found") else 404
    return jsonify(payload), status_code


@mlb_bp.get("/api/season/<int:season>/betting-card/day/<date_str>")
def api_betting_card_day(season: int, date_str: str):
    profile = (request.args.get("profile") or "retuned").strip() or "retuned"
    payload, status_code = _season_betting_day_payload(int(season), str(date_str), profile)
    payload["artifactDate"] = str(date_str)
    payload["artifactPath"] = payload.get("source_path") or payload.get("card_source")
    payload["artifactSource"] = "season_betting_day"
    payload["cards_available"] = bool(payload.get("games"))
    payload["cards_url"] = f"/mlb/season/{int(season)}/betting-card?date={date_str}"
    payload["manifest_source"] = payload.get("source_path")
    payload["staking_plan"] = payload.get("summary", {}).get("staking_plan") if isinstance(payload.get("summary"), dict) else None
    payload["app"] = _app_meta()
    return jsonify(payload), status_code


@mlb_bp.get("/api/season/<int:season>/betting-cards/day/<date_str>")
def api_betting_cards_day(season: int, date_str: str):
    profile = (request.args.get("profile") or "retuned").strip() or "retuned"
    payload, status_code = _season_betting_day_payload(int(season), str(date_str), profile)
    return jsonify(payload), status_code