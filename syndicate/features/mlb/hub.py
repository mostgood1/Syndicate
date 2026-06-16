from __future__ import annotations

from datetime import date
from pathlib import Path
import re
from typing import Any

from syndicate.features.mlb.sources import available_daily_summary_dates
from syndicate.features.mlb.sources import daily_top_props_path
from syndicate.features.mlb.sources import default_mlb_source_root
from syndicate.features.mlb.sources import load_json_file
from syndicate.features.mlb.sources import live_lens_report_path


_DATE_TOKEN_RE = re.compile(r"(\d{4})_(\d{2})_(\d{2})")
_PROFILE_DIR_RE = re.compile(r"^betting_day_payloads(?:_(?P<profile>[a-z0-9_]+))?$", re.IGNORECASE)


def _latest_date(glob_pattern: str) -> str | None:
    root = default_mlb_source_root()
    latest: str | None = None
    for path in root.glob(glob_pattern):
        match = _DATE_TOKEN_RE.search(path.name)
        if not match:
            continue
        value = f"{match.group(1)}-{match.group(2)}-{match.group(3)}"
        if latest is None or value > latest:
            latest = value
    return latest


def _season_from_date(selected_date: str) -> str:
    text = str(selected_date or "").strip()
    if len(text) >= 4 and text[:4].isdigit():
        return text[:4]
    return "2026"


def _available_betting_profiles(season: str) -> list[dict[str, str]]:
    season_dir = default_mlb_source_root() / "data" / "eval" / "seasons" / str(season)
    profiles: list[dict[str, str]] = []
    if not season_dir.exists():
        return profiles
    for child in sorted(season_dir.iterdir()):
        if not child.is_dir():
            continue
        match = _PROFILE_DIR_RE.match(child.name)
        if not match:
            continue
        profile = str(match.group("profile") or "retuned").strip().lower() or "retuned"
        label = profile.replace("_", " ").title()
        profiles.append({"profile": profile, "label": label, "path": str(child)})
    return profiles


def _top_prop_lane_counts(selected_date: str) -> dict[str, int]:
    summary = load_json_file(daily_top_props_path(selected_date))
    groups = summary.get("groups") if isinstance(summary, dict) else {}
    pitcher_group = groups.get("pitcher") if isinstance(groups, dict) else {}
    hitter_group = groups.get("hitter") if isinstance(groups, dict) else {}
    pitcher_sections = pitcher_group.get("sections") if isinstance(pitcher_group, dict) else []
    hitter_sections = hitter_group.get("sections") if isinstance(hitter_group, dict) else []

    def _section_row_count(sections: Any) -> int:
        if not isinstance(sections, list) or not sections:
            return 0
        first_section = sections[0] if isinstance(sections[0], dict) else {}
        rows = first_section.get("rows") if isinstance(first_section, dict) else []
        return len(rows) if isinstance(rows, list) else 0

    return {"pitcher_rows": _section_row_count(pitcher_sections), "hitter_rows": _section_row_count(hitter_sections)}


def _cards_launch_date(archive_dates: list[str]) -> str:
    if not archive_dates:
        return _latest_date("data/daily/daily_summary_*.json") or date.today().isoformat()

    for selected_date in reversed(archive_dates):
        top_prop_counts = _top_prop_lane_counts(selected_date)
        if top_prop_counts["pitcher_rows"] and top_prop_counts["hitter_rows"]:
            return selected_date
        if load_json_file(live_lens_report_path(selected_date)):
            return selected_date

    return archive_dates[-1]


def build_hub_context() -> dict[str, Any]:
    archive_dates = available_daily_summary_dates()
    today_date = date.today().isoformat()
    latest_archive_date = archive_dates[-1] if archive_dates else (_latest_date("data/daily/daily_summary_*.json") or today_date)
    cards_date = _cards_launch_date(archive_dates)
    season = _season_from_date(cards_date)
    live_lens_date = cards_date
    hr_targets_date = cards_date
    rfi_targets_date = cards_date
    top_prop_counts = _top_prop_lane_counts(cards_date)
    profiles = _available_betting_profiles(season)
    default_profile = next((item["profile"] for item in profiles if item["profile"] == "retuned"), profiles[0]["profile"] if profiles else "retuned")

    if top_prop_counts["pitcher_rows"] and top_prop_counts["hitter_rows"]:
        availability_note = (
            f"Latest MLB top-props artifact has {top_prop_counts['pitcher_rows']} pitcher rows and "
            f"{top_prop_counts['hitter_rows']} hitter rows for {cards_date}."
        )
    elif top_prop_counts["pitcher_rows"]:
        availability_note = (
            f"Latest MLB top-props artifact has {top_prop_counts['pitcher_rows']} pitcher rows, but no hitter rows yet, "
            f"so the Hitter Top Props lane stays empty for {cards_date}."
        )
    elif top_prop_counts["hitter_rows"]:
        availability_note = (
            f"Latest MLB top-props artifact has {top_prop_counts['hitter_rows']} hitter rows, but no pitcher rows yet, "
            f"so the Pitcher Top Props lane stays empty for {cards_date}."
        )
    else:
        availability_note = f"Latest MLB top-props artifact has no pitcher or hitter rows yet for {cards_date}."

    route_groups = [
        {
            "eyebrow": "Primary board",
            "title": "Cards",
            "body": "This should be the MLB first-read workflow in Syndicate, not just a demo route.",
            "links": [
                {"label": f"Cards {cards_date}", "href": f"/mlb/cards?date={cards_date}"},
                {"label": f"Live lens {live_lens_date}", "href": f"/mlb/live-lens?date={live_lens_date}"},
                {"label": f"Live lens accuracy {live_lens_date}", "href": f"/mlb/live-lens-accuracy?date={live_lens_date}"},
                {"label": f"Market accuracy {live_lens_date}", "href": f"/mlb/market-accuracy?date={live_lens_date}"},
            ],
        },
        {
                "body": "The primary launch links now point at the latest stored MLB slate so the hub matches the data that is actually available, while the surrounding route groups still expose the stored artifact lanes that back historical review and archive navigation.",
            "title": "Betting card profiles",
            "body": "These routes should mirror the source betting-card workflow with real profile choices, not hard-coded placeholders.",
            "links": [
                {
                    "label": f"{item['label']} betting card",
                    "href": f"/mlb/season/{season}/betting-card?date={cards_date}&profile={item['profile']}",
                }
                for item in profiles
            ]
            or [{"label": "Retuned betting card", "href": f"/mlb/season/{season}/betting-card?date={cards_date}&profile={default_profile}"}],
        },
        {
            "eyebrow": "Targets and ladders",
            "title": "Daily ranking boards",
            "body": "The supporting ladders and target boards should stay one click away from the main MLB pane.",
            "links": [
                {"label": f"HR targets {hr_targets_date}", "href": f"/mlb/hr-targets?date={hr_targets_date}"},
                {"label": f"RFI targets {rfi_targets_date}", "href": f"/mlb/rfi-targets?date={rfi_targets_date}"},
                {"label": f"Pitcher ladders {cards_date}", "href": f"/mlb/pitcher-ladders?date={cards_date}"},
                {"label": f"Hitter ladders {cards_date}", "href": f"/mlb/hitter-ladders?date={cards_date}"},
                {"label": f"Top props {cards_date}", "href": f"/mlb/top-props?date={cards_date}"},
            ],
        },
        {
            "eyebrow": "Historical lane",
            "title": "Daily archive",
            "body": "Stored day artifacts should be browsable as a historical entry lane instead of forcing every archived date through manual query-string edits.",
            "links": [
                {"label": f"Archive {cards_date}", "href": f"/mlb/archive?date={cards_date}"},
                {"label": f"Season review {cards_date}", "href": f"/mlb/season/{season}?date={cards_date}"},
            ],
        },
    ]

    return {
        "launch_date": cards_date,
        "live_lens_date": live_lens_date,
        "hr_targets_date": hr_targets_date,
        "rfi_targets_date": rfi_targets_date,
        "default_profile": default_profile,
        "profiles": profiles,
        "availability_note": availability_note,
        "summary_stats": [
            {"label": "Launch date", "value": cards_date},
            {"label": "Latest stored date", "value": latest_archive_date},
            {"label": "Archive dates", "value": str(len(archive_dates))},
            {"label": "Betting profiles", "value": str(len(profiles) or 1)},
        ],
        "route_groups": route_groups,
    }