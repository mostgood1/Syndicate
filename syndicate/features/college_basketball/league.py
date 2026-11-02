"""Men's and women's college basketball: ONE description per league, read by the shared code.

WHY (2026-11-02, lane wncaab-module; user: "fully build a WNCAAB module from scratch using the
NCAAB module as the model"). NCAAB's slate, cards, odds capture and in-play lane hard-coded the
men's game -- `mens-college-basketball`, `basketball_ncaab`, two halves. Copying ~3,000 lines into
a women's tree would fork two codebases that must stay in step, so those modules take a league and
default to NCAAB; women's college basketball binds WNCAAB.

THE GAMES DIFFER WHERE IT MATTERS: men play two 20-minute halves, women four 10-minute quarters
(5-minute overtimes for both). That changes the clock token, the line score, the segment markets
the odds feed offers and what the in-play lane asks for.

NCAAB's values are the constants its modules carried before this file existed; its tests pin them.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

_SHARED = Path(__file__).resolve().parents[1] / "shared"


@dataclass(frozen=True)
class CollegeLeague:
    slug: str                      # platform sport slug
    label: str                     # display name
    espn_path: str                 # site.api.espn.com/apis/site/v2/sports/<espn_path>
    oddsapi_key: str               # OddsAPI sport key
    registry_csv: Path             # committed D1 team registry (ESPN ids)
    periods: int                   # regulation periods: 2 halves (men) / 4 quarters (women)
    period_seconds: int
    # OddsAPI segment-market suffixes the capture asks for, and the shared quote-log segment names.
    segments: tuple[str, ...]
    data_dir: str                  # <data root>/<data_dir>

    @property
    def scoreboard_url(self) -> str:
        # `groups=50` is ESPN's Division I filter; without it the college scoreboard returns a
        # small featured subset (measured 2026-11-03 women's: 3 games vs 41).
        return (f"https://site.api.espn.com/apis/site/v2/sports/{self.espn_path}/"
                "scoreboard?dates={compact}&groups=50&limit=500")

    @property
    def teams_url(self) -> str:
        return f"https://site.api.espn.com/apis/site/v2/sports/{self.espn_path}/teams?limit=1000"

    def period_label(self, period: int) -> str:
        """Live clock prefix: H1/H2 for halves, Q1..Q4 for quarters; OT, 2OT, ... after regulation."""
        if period <= self.periods:
            return f"{'H' if self.periods == 2 else 'Q'}{period}"
        extra = period - self.periods
        return "OT" if extra == 1 else f"{extra}OT"


NCAAB = CollegeLeague(
    slug="ncaab",
    label="NCAAB",
    espn_path="basketball/mens-college-basketball",
    oddsapi_key="basketball_ncaab",
    registry_csv=_SHARED / "ncaab_team_registry.csv",
    periods=2,
    period_seconds=1200,
    segments=("h1", "h2"),
    data_dir="ncaab_source",
)

WNCAAB = CollegeLeague(
    slug="wncaab",
    label="WNCAAB",
    espn_path="basketball/womens-college-basketball",
    oddsapi_key="basketball_wncaab",
    registry_csv=_SHARED / "wncaab_team_registry.csv",
    periods=4,
    period_seconds=600,
    segments=("q1", "q2", "q3", "q4", "h1", "h2"),
    data_dir="wncaab_source",
)

LEAGUES: dict[str, CollegeLeague] = {league.slug: league for league in (NCAAB, WNCAAB)}


def league_for(slug: str) -> CollegeLeague:
    try:
        return LEAGUES[str(slug or "").strip().lower()]
    except KeyError:
        raise ValueError(f"not a college basketball league: {slug!r} (known: {sorted(LEAGUES)})") from None
