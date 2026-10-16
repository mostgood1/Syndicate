"""The SyndicateROI brand kit: one JSON of constants, read by the play cards and the cheat-sheet page (lane `play-cards`).

User 2026-10-16 supplied the brand spec (a creative-director prompt) and asked for its constants to live in a JSON the
renderer references, "then use the system prompt only for creative direction and let the JSON enforce consistency".
`syndicate/static/brand/syndicate_roi_brand.json` is that file. Everything here is a pure read of it, of the committed
ESPN team-branding snapshots, or of the sheet the generator already wrote: no network, so the web may call it.

  * `css_tokens()`       the colours and fonts as CSS custom properties; the card and the page use nothing else
  * `team_color()`       a team's primary colour, the spec's "team colours as subtle accents only"
  * `hero_url()`         a headshot upgraded to the largest free cutout its league serves (the hero is 40-60% of a card)
  * `team_star()`        the player who fronts a team's side or total card (spec: "use team athlete hero image")
  * `faces_allowed()`    False for college sports: their cards and sheets show the team logo, never a player's face
                         (user 2026-10-16: "use team logos for college athletes")
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Mapping

BRAND_JSON = Path(__file__).resolve().parents[2] / "static" / "brand" / "syndicate_roi_brand.json"
_FALLBACK_FONTS = {"display": '"Arial Narrow", Impact, sans-serif', "body": '"Segoe UI", Helvetica, Arial, sans-serif'}


@lru_cache(maxsize=1)
def load() -> dict[str, Any]:
    return json.loads(BRAND_JSON.read_text(encoding="utf-8"))


def color(name: str) -> str:
    return load()["colors"][name]


def css_tokens() -> str:
    """`:root { --green: #8CFF00; ... }` -- every brand colour as `--<name>` (underscores become hyphens)."""
    brand = load()
    lines = [f"  --{key.replace('_', '-')}: {value};" for key, value in brand["colors"].items()]
    for key, family in brand["fonts"].items():
        lines.append(f'  --{key}: "{family}", {_FALLBACK_FONTS.get(key, "sans-serif")};')
    return ":root {\n" + "\n".join(lines) + "\n}"


def _norm(text: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(text or "").lower())


@lru_cache(maxsize=16)
def _colors(sport: str) -> dict[str, str]:
    """name -> primary colour, from the same snapshots `team_logos` reads (read once per process)."""
    from syndicate.features.shared import team_logos
    from syndicate.features.shared.team_branding import read_team_branding_snapshot

    out: dict[str, str] = {}
    for path in team_logos._branding_files(sport):
        for row in read_team_branding_snapshot(path):
            hexed = str(row.primary_color or "").strip()
            if not re.fullmatch(r"#?[0-9a-fA-F]{6}", hexed):
                continue
            hexed = "#" + hexed.lstrip("#").upper()
            for key in (row.display_name, row.location, row.abbreviation):
                if _norm(key):
                    out.setdefault(_norm(key), hexed)
    return out


def team_color(sport: Any, *names: Any) -> str | None:
    """The team's primary colour from the first name that resolves; None when unknown (never a guess)."""
    slug = str(sport or "").strip().lower()
    try:
        index = _colors(slug)
    except Exception:  # noqa: BLE001 -- a missing snapshot is "no accent", never an error
        return None
    for name in names:
        hit = index.get(_norm(name))
        if hit:
            return hit
    return None


FACE_FIELDS = ("headshot_url", "headshot_src", "headshot_card_src", "hero_url", "hero_src", "hero_away_url", "hero_away_src",
               "hero_home_url", "hero_home_src", "hero_name")


def faces_allowed(sport: Any) -> bool:
    """False for a logo-only sport (the brand JSON's `logo_only_sports`: college)."""
    return str(sport or "").strip().lower() not in set(load().get("logo_only_sports") or ())


def without_faces(item: Mapping[str, Any]) -> dict[str, Any]:
    """The item with every player-face field removed (the team logo fields stay)."""
    return {k: v for k, v in item.items() if k not in FACE_FIELDS}


_MLB_HEADSHOT = re.compile(r"^https://img\.mlbstatic\.com/mlb-photos/image/upload/.*?/people/(\d+)/headshot/")


def hero_url(sport: Any, url: Any) -> str | None:
    """The largest free cutout for a headshot. Measured 2026-10-16: NBA/WNBA 1040x760 and ESPN (NFL, NCAAF, soccer)
    600x436 are transparent already; MLB's 360px photo has a 1000px transparent `silo` twin; NHL's mug is 336px and is
    kept (its 1296px action shot is an overhead photo on white ice -- wrong for a dark card)."""
    if not url or not str(url).startswith("https://"):
        return None
    m = _MLB_HEADSHOT.match(str(url))
    if m:
        return f"https://img.mlbstatic.com/mlb-photos/image/upload/w_1000,q_auto:best/v1/people/{m.group(1)}/headshot/silo/current"
    return str(url)


def team_star(rows: Iterable[Mapping[str, Any]], *team_names: Any) -> Mapping[str, Any] | None:
    """The sheet row of the player who fronts a team's card: the one the books offer the most markets on (books list
    every prop on a star and few on a depth player), ties to the most lines, and only a player with a face."""
    wanted = {_norm(t) for t in team_names if _norm(t)}
    if not wanted:
        return None
    by_player: dict[str, dict[str, Any]] = {}
    for r in rows:
        if not r.get("headshot_url") or not r.get("player"):
            continue
        if not wanted & {_norm(r.get("team_name")), _norm(r.get("team"))}:
            continue
        slot = by_player.setdefault(str(r["player"]), {"row": r, "markets": set(), "lines": 0})
        slot["markets"].add(str(r.get("market")))
        slot["lines"] += 1
    if not by_player:
        return None
    best = max(by_player.values(), key=lambda s: (len(s["markets"]), s["lines"]))
    return best["row"]
