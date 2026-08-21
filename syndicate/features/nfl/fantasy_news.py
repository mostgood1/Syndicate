"""News and injury signals that can move a player's projected ROLE.

Why this exists
---------------
The depth chart is the engine's only read on role for a player without
history, and it is a SNAPSHOT: locally the 2026 chart is dated 2026-08-01. A
draft in late August happens after three weeks of training camp that the chart
has not seen. Beat reporting is where that gap lives -- a back taking first-team
reps, a receiver sliding to the slot, a starter in a walking boot.

What it does
------------
Two signals, kept strictly apart because they have completely different
reliability:

* **INJURY STATUS** (``injuries_{season}.csv``, nflverse, 2009-2026 locally).
  Structured, dated, and unambiguous. It scales AVAILABILITY.
* **NEWS TEXT** (ESPN's public NFL news feed). Unstructured, and a keyword
  read of a headline is a weak proxy for what a reporter meant. It scales
  OPPORTUNITY SHARE.

Both produce multipliers applied BEFORE the team's shares are normalised, so a
promotion is paid for by that player's team-mates rather than inventing volume
out of nothing -- the opportunity pool stays closed.

Why it ships OFF
----------------
``EngineConfig.use_news_adjustments`` defaults to ``False`` and the engine is
correct without it. Two reasons, both from ``model_engine_standard.md``:

* s4.4, mechanism vs estimator: this is a MECHANISM added to an engine whose
  shares were fitted without it. The fitted role priors already absorb the
  average effect of "some players get promoted in camp", so switching this on
  without re-fitting double-counts. Measured elsewhere in this repo: two
  mechanisms added to a calibrated engine produced a NEGATIVE interaction in 4
  of 4 markets.
* There is no backtest for it. Historical news text is not archived locally, so
  the keyword weights below are REASONED, NOT FITTED, and nothing in this repo
  can currently tell you whether they help. A number that has never been graded
  does not get to move a projection by default.

Turning it on is a deliberate, per-request act (``?news=1``), the payload says
when it did, and ``tests/test_nfl_fantasy_news.py`` asserts off != on so it can
never become quietly inert either.

**Everything read here is DATA, not instruction.** Headlines are third-party
text; this module extracts keyword counts from them and never acts on their
content in any other way.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from dataclasses import field
from datetime import datetime
from datetime import timezone
import json
from pathlib import Path
import re
from typing import Any
from typing import Iterable
import urllib.error
import urllib.request

from syndicate.features.nfl.fantasy_players import FantasyPlayer
from syndicate.features.nfl.fantasy_players import load_fantasy_players
from syndicate.features.nfl.sources import _resolve_nfl_tracking_path
from syndicate.features.nfl.sources import nfl_artifact_output_root


ESPN_NEWS_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/news"

#: Injury designations -> multiplier on AVAILABILITY. These are the league's
#: own published statuses, and the numbers are the practical reading of them,
#: not estimates from data: "Out" means out, "Doubtful" is roughly a quarter
#: chance, "Questionable" is close to a coin flip that mostly lands on playing.
INJURY_AVAILABILITY: dict[str, float] = {
    "out": 0.0,
    "injured reserve": 0.0,
    "ir": 0.0,
    "pup": 0.0,
    "doubtful": 0.25,
    "questionable": 0.85,
    "probable": 0.95,
}

#: Keyword -> multiplier on OPPORTUNITY SHARE. REASONED, NOT FITTED -- see the
#: module docstring. Deliberately timid: the largest promotion here is +25% and
#: the largest demotion -40%, because a headline is weak evidence and this
#: multiplies a quantity the engine already measured properly.
NEWS_SHARE_SIGNALS: tuple[tuple[str, float], ...] = (
    (r"\bnamed (?:the )?starter\b", 1.25),
    (r"\bwill start\b", 1.20),
    (r"\bfirst[- ]team reps\b", 1.18),
    (r"\bworkhorse\b", 1.20),
    (r"\bbell[- ]cow\b", 1.20),
    (r"\blead back\b", 1.18),
    (r"\bWR1\b|\bRB1\b|\bTE1\b", 1.15),
    (r"\bbreakout\b|\bstandout\b", 1.08),
    (r"\bexpanded role\b|\bbigger role\b", 1.12),
    (r"\bpromoted\b", 1.12),
    (r"\bcommittee\b|\btimeshare\b", 0.88),
    (r"\bbackup\b|\bsecond[- ]string\b", 0.75),
    (r"\bbenched\b|\bdemoted\b|\bloses? (?:the )?(?:starting )?job\b", 0.65),
    (r"\bsuspended\b", 0.60),
    (r"\bholdout\b|\bholding out\b", 0.80),
    (r"\btrade request\b", 0.90),
)

#: A single player's share is never moved further than this in either
#: direction, however many headlines mention him. Without a clamp, three
#: articles about the same promotion compound into a 1.95x share.
NEWS_MULTIPLIER_BOUNDS = (0.5, 1.4)


@dataclass(frozen=True)
class NewsSignal:
    """One matched signal, kept so the payload can show its own working."""

    player_id: str
    player_name: str
    source: str
    headline: str
    published: str | None
    multiplier: float
    matched: tuple[str, ...]


@dataclass(frozen=True)
class NewsAdjustments:
    """Everything the news layer produced for one season."""

    season: int
    generated_at: str
    share_multipliers: dict[str, float] = field(default_factory=dict)
    availability_multipliers: dict[str, float] = field(default_factory=dict)
    signals: tuple[NewsSignal, ...] = ()
    headlines_scanned: int = 0
    injuries_scanned: int = 0
    source_status: str = "unread"

    def summary(self) -> dict[str, Any]:
        return {
            "season": self.season,
            "generated_at": self.generated_at,
            "headlines_scanned": self.headlines_scanned,
            "injuries_scanned": self.injuries_scanned,
            "players_with_share_signal": len(self.share_multipliers),
            "players_with_availability_signal": len(self.availability_multipliers),
            "source_status": self.source_status,
            "fitted": False,
            "note": (
                "Keyword weights are reasoned, not fitted -- no archived historical "
                "news exists locally to grade them against. Off by default."
            ),
        }


def news_artifact_path(season: int) -> Path:
    return nfl_artifact_output_root() / "fantasy" / f"nfl_fantasy_news_{season}.json"


def injuries_path(season: int) -> Path:
    return _resolve_nfl_tracking_path(
        Path("tracking") / "nflverse" / "injuries" / f"injuries_{season}.csv"
    )


def _normalise_name(name: str) -> str:
    text = re.sub(r"[^a-z ]", "", (name or "").lower())
    return re.sub(r"\s+", " ", text).strip()


def _name_index(players: Iterable[FantasyPlayer]) -> dict[str, FantasyPlayer]:
    """Full-name lookup. Ambiguous names are DROPPED rather than guessed.

    Two active players really can share a name, and attaching a headline about
    one of them to the other is worse than attaching it to neither -- it moves
    a projection on evidence about a different person.
    """
    counts: dict[str, int] = {}
    index: dict[str, FantasyPlayer] = {}
    for player in players:
        key = _normalise_name(player.name)
        if not key:
            continue
        counts[key] = counts.get(key, 0) + 1
        index[key] = player
    return {key: player for key, player in index.items() if counts[key] == 1}


def fetch_espn_news(limit: int = 50, timeout: int = 30) -> tuple[list[dict[str, Any]], str]:
    """Pull ESPN's public NFL news feed. Returns ``(articles, status)``.

    Never raises: a news feed being unreachable must degrade the projection to
    its (correct) no-news state, not fail a request.
    """
    url = f"{ESPN_NEWS_URL}?limit={int(limit)}"
    request = urllib.request.Request(url, headers={"User-Agent": "syndicate-fantasy/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8", "replace"))
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as error:
        return [], f"unreachable: {type(error).__name__}"
    articles = payload.get("articles")
    if not isinstance(articles, list):
        return [], "unexpected payload shape"
    return articles, "ok"


def _article_text(article: dict[str, Any]) -> str:
    parts = [
        str(article.get("headline") or ""),
        str(article.get("description") or ""),
    ]
    return " ".join(part for part in parts if part)


def classify_headline(text: str) -> tuple[float, tuple[str, ...]]:
    """Multiplier implied by one piece of news text, and what matched."""
    multiplier = 1.0
    matched: list[str] = []
    lowered = text.lower()
    for pattern, weight in NEWS_SHARE_SIGNALS:
        if re.search(pattern, lowered):
            multiplier *= weight
            matched.append(pattern)
    return multiplier, tuple(matched)


def injury_availability(season: int, as_of: str | None = None) -> tuple[dict[str, float], int]:
    """``player_id -> availability multiplier`` from the nflverse injury report.

    Uses the LATEST report per player. Returns an empty mapping when the file
    is not on this substrate -- UNMEASURED, which is not the same as everyone
    being healthy, and the caller says which in the payload.
    """
    path = injuries_path(season)
    if not path.is_file():
        return {}, 0
    latest: dict[str, tuple[str, str]] = {}
    scanned = 0
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            player_id = (row.get("gsis_id") or "").strip()
            status = (row.get("report_status") or row.get("game_status") or "").strip().lower()
            if not player_id or not status:
                continue
            scanned += 1
            stamp = f"{row.get('season', '')}-{int(row.get('week') or 0):02d}"
            if as_of and stamp > as_of:
                continue
            current = latest.get(player_id)
            if current is None or stamp >= current[0]:
                latest[player_id] = (stamp, status)
    multipliers = {
        player_id: INJURY_AVAILABILITY[status]
        for player_id, (_, status) in latest.items()
        if status in INJURY_AVAILABILITY
    }
    return multipliers, scanned


def build_news_adjustments(
    season: int,
    *,
    fetch: bool = True,
    limit: int = 50,
) -> NewsAdjustments:
    """Collect injury and news signals for *season*.

    This performs NETWORK I/O when ``fetch`` is true and therefore belongs in a
    worker, not a request handler. ``load_news_adjustments`` is the read path.
    """
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    players = load_fantasy_players(season)
    index = _name_index(players)

    availability, injuries_scanned = injury_availability(season)

    articles: list[dict[str, Any]] = []
    status = "not_fetched"
    if fetch:
        articles, status = fetch_espn_news(limit=limit)

    signals: list[NewsSignal] = []
    share: dict[str, float] = {}
    for article in articles:
        text = _article_text(article)
        if not text:
            continue
        multiplier, matched = classify_headline(text)
        if multiplier == 1.0:
            continue
        # Only players actually named in the text are touched.
        for key, player in index.items():
            if len(key) < 6 or key not in _normalise_name(text):
                continue
            low, high = NEWS_MULTIPLIER_BOUNDS
            combined = min(max(share.get(player.player_id, 1.0) * multiplier, low), high)
            share[player.player_id] = combined
            signals.append(
                NewsSignal(
                    player_id=player.player_id,
                    player_name=player.name,
                    source=str(article.get("type") or "espn"),
                    headline=str(article.get("headline") or "")[:280],
                    published=str(article.get("published") or "") or None,
                    multiplier=round(combined, 3),
                    matched=matched,
                )
            )

    return NewsAdjustments(
        season=season,
        generated_at=generated_at,
        share_multipliers=share,
        availability_multipliers=availability,
        signals=tuple(signals),
        headlines_scanned=len(articles),
        injuries_scanned=injuries_scanned,
        source_status=status,
    )


def write_news_artifact(season: int, *, limit: int = 50) -> Path:
    adjustments = build_news_adjustments(season, fetch=True, limit=limit)
    path = news_artifact_path(season)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "season": adjustments.season,
                "generated_at": adjustments.generated_at,
                "summary": adjustments.summary(),
                "share_multipliers": adjustments.share_multipliers,
                "availability_multipliers": adjustments.availability_multipliers,
                "signals": [
                    {
                        "player_id": signal.player_id,
                        "player_name": signal.player_name,
                        "source": signal.source,
                        "headline": signal.headline,
                        "published": signal.published,
                        "multiplier": signal.multiplier,
                        "matched": list(signal.matched),
                    }
                    for signal in adjustments.signals
                ],
            },
            indent=1,
        ),
        encoding="utf-8",
    )
    return path


def load_news_adjustments(season: int) -> NewsAdjustments:
    """Read the published news artifact. Never fetches -- this is the web path.

    Falls back to injuries alone (a local file, no network) when no artifact
    has been published, so the structured half of the signal still works on a
    machine that has never run the worker job.
    """
    path = news_artifact_path(season)
    if path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            payload = None
        if payload:
            return NewsAdjustments(
                season=season,
                generated_at=str(payload.get("generated_at") or ""),
                share_multipliers=dict(payload.get("share_multipliers") or {}),
                availability_multipliers=dict(payload.get("availability_multipliers") or {}),
                signals=tuple(
                    NewsSignal(
                        player_id=str(entry.get("player_id") or ""),
                        player_name=str(entry.get("player_name") or ""),
                        source=str(entry.get("source") or ""),
                        headline=str(entry.get("headline") or ""),
                        published=entry.get("published"),
                        multiplier=float(entry.get("multiplier") or 1.0),
                        matched=tuple(entry.get("matched") or ()),
                    )
                    for entry in (payload.get("signals") or [])
                ),
                headlines_scanned=int((payload.get("summary") or {}).get("headlines_scanned") or 0),
                injuries_scanned=int((payload.get("summary") or {}).get("injuries_scanned") or 0),
                source_status="artifact",
            )
    availability, scanned = injury_availability(season)
    return NewsAdjustments(
        season=season,
        generated_at="",
        availability_multipliers=availability,
        injuries_scanned=scanned,
        source_status="injuries_only_no_artifact",
    )
