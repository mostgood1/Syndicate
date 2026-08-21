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

What ships, and what does not
-----------------------------
**The INJURY half now ships ON**, because it was graded and it earns it:
`scripts/grade_nfl_fantasy_news.py` measures held-out MAE over 2,226
player-weeks at 6.894 with no adjustment against 4.399 with the fitted
multipliers -- a 36% improvement, on constants selected on 2022-2023 and only
reported on 2024-2025.

**The NEWS-TEXT half still ships OFF**, and the two are now separate flags
(`use_injury_availability` and `use_news_adjustments`) precisely so that one
being graded does not smuggle the other into production.

Why the text half stays off
---------------------------
``EngineConfig.use_news_adjustments`` defaults to ``False`` and the engine is
correct without it. Two reasons, both from ``model_engine_standard.md``:

* s4.4, mechanism vs estimator: this is a MECHANISM added to an engine whose
  shares were fitted without it. The fitted role priors already absorb the
  average effect of "some players get promoted in camp", so switching this on
  without re-fitting double-counts. Measured elsewhere in this repo: two
  mechanisms added to a calibrated engine produced a NEGATIVE interaction in 4
  of 4 markets.
* There is no backtest for it. Historical news TEXT is not archived -- ESPN
  serves current headlines only -- so the keyword weights below are REASONED,
  NOT FITTED, and nothing here can say whether they help. A number that has
  never been graded does not get to move a projection by default.

  Note what this does NOT excuse. Most fantasy "news" is a beat reporter
  relaying the practice report, and `practice_status` archives exactly that.
  So the coach-quote signal WAS gradeable after all, and it was graded:
  practice participation alone scores +25.8% against the game designation's
  +36.2%, and combining them scores +30.9% -- WORSE than the designation alone,
  because eight cells split the same data too thin. The practice report is
  already inside the designation the team publishes. That is a measured
  negative result, not an untested assumption.

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

#: Injury designation -> multiplier on AVAILABILITY. **FITTED on 2022-2023 and
#: reported on 2024-2025** by `scripts/grade_nfl_fantasy_news.py`. They were
#: previously a "practical reading" of the designations, and that reading was
#: materially wrong on two of the four that matter:
#:
#:   designation     reasoned   fitted   what the data says
#:   out                 0.00    0.000   correct
#:   doubtful            0.25    0.007   0 of 67 doubtful players played. AT ALL.
#:   questionable        0.85    0.593   played 67% of the time, scored 61%
#:   (no designation)      --    0.930   1,300 held-out rows the engine ignored
#:
#: "Doubtful" reads like a long shot and behaves like OUT. "Questionable" reads
#: like a coin flip that mostly lands on playing, and it is closer to a real
#: coin flip -- and the players who do suit up are diminished, so the cost is
#: taken twice.
#:
#: Held-out MAE over 2,226 player-weeks: 6.894 with no adjustment, 4.672 with
#: the reasoned constants, **4.399 with these**.
#:
#: The empty-string key is the row that carries a practice entry but NO game
#: designation -- a real and common state, and the largest single group.
INJURY_AVAILABILITY: dict[str, float] = {
    "out": 0.0,
    "injured reserve": 0.0,
    "ir": 0.0,
    "pup": 0.0,
    "doubtful": 0.01,
    "questionable": 0.59,
    "none": 0.93,
    "": 0.93,
    # Retired by the league in 2016 and absent from the modern feed, so it has
    # no fitted value; left at a benign near-1.0 rather than dropped, because a
    # missing key means "no adjustment" and that is the right answer for it.
    "probable": 0.95,
}

#: Keyword -> multiplier on OPPORTUNITY SHARE. REASONED, NOT FITTED -- see the
#: module docstring. Deliberately timid: the largest promotion here is +25% and
#: the largest demotion -40%, because a headline is weak evidence and this
#: multiplies a quantity the engine already measured properly.
#:
#: THESE ARE ABOUT ROLE AND PERFORMANCE, NOT HEALTH, and that is the whole
#: reason the layer still exists after the injury half was graded. The injury
#: axis is well covered: the team's own game designation is published weekly,
#: it is archived back to 2009, and grading showed the practice report adds
#: NOTHING beyond it. None of that touches "he has been the best player on the
#: field in camp", "the coaches want him more involved", or "he is running with
#: the ones" -- which are claims about opportunity share, arrive only as prose,
#: and have no structured equivalent anywhere in the feed.
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
    # Performance and coach-quote shapes, which the injury report cannot carry.
    (r"\brunning with the (?:ones|first team|starters)\b", 1.20),
    (r"\bmore (?:targets|touches|carries|snaps)\b", 1.15),
    (r"\bbigger workload\b|\bfeature(?:d)? back\b", 1.18),
    (r"\bturning heads\b|\bbest player on the field\b", 1.10),
    (r"\bimpress(?:ed|ive|ing)\b|\blooked explosive\b", 1.08),
    (r"\bearn(?:ed|ing) (?:more|a bigger)\b", 1.12),
    (r"\bfell? behind\b|\bslipp(?:ed|ing) down\b", 0.85),
    (r"\bfewer (?:targets|touches|carries|snaps)\b", 0.85),
    (r"\bstruggl(?:ed|ing)\b|\bdrop(?:s|ped) problem\b", 0.90),
    (r"\bwork(?:ing)? with the (?:twos|second team|backups)\b", 0.75),
)

#: Which axis a matched signal belongs to. The injury axis is already graded
#: and modelled from the team's own designation, so a headline repeating it
#: must not double-count; only the ROLE axis is allowed to move share.
_INJURY_AXIS_PATTERNS = frozenset({
    r"\bsuspended\b",
    r"\bholdout\b|\bholding out\b",
    r"\btrade request\b",
})

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

    # NO CUSTOM HEADERS -- urllib's own default User-Agent, and this is load
    # bearing. `live_game_state.py` already carried the rule ("DO NOT ADD A
    # BROWSER USER-AGENT. ESPN returns HTTP 403 ... from Render's outbound IP",
    # confirmed 2026-08-05 across three variants), and this function shipped
    # with `User-Agent: syndicate-fantasy/1.0` anyway and got 403 in BOTH
    # places. I read that as a local network block on my machine -- the one
    # explanation that made the two failures unrelated, when in fact the same
    # header caused both. A rule was already written down for this exact API.
    request = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as error:
        # CARRY THE STATUS CODE. "HTTPError" alone cost a deploy cycle: 403
        # (they refused us) and 404 (we asked for the wrong thing) are
        # different bugs and were indistinguishable in the worker log.
        return [], f"unreachable: HTTP {error.code}"
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


def espn_id_index(season: int) -> dict[str, str]:
    """``espn_id -> gsis_id`` for the season's fantasy players.

    ESPN TAGS ITS OWN ARTICLES WITH ATHLETE IDS, and using them is strictly
    better than matching on a name. Name matching has to drop every ambiguous
    case to stay safe (two active players really can share a name), it breaks
    on "D.J." versus "DJ" and on suffixes, and it cannot tell a mention from a
    subject. The roster carries `espn_id`, so the join is exact.

    Name matching is kept as a FALLBACK for articles carrying no athlete tag,
    which is common for wire copy.
    """
    index: dict[str, str] = {}
    for player in load_fantasy_players(season):
        espn = (getattr(player, "espn_id", "") or "").strip()
        if espn and player.player_id:
            index[espn] = player.player_id
    return index


def _tagged_players(article: dict[str, Any], espn_index: dict[str, str]) -> list[str]:
    """gsis_ids ESPN itself attached to this article."""
    found: list[str] = []
    for category in article.get("categories") or []:
        if not isinstance(category, dict):
            continue
        if category.get("type") != "athlete":
            continue
        raw = category.get("athleteId") or (category.get("athlete") or {}).get("id")
        mapped = espn_index.get(str(raw).strip()) if raw else None
        if mapped and mapped not in found:
            found.append(mapped)
    return found


def capture_news_snapshot(season: int, *, limit: int = 60) -> dict[str, Any]:
    """One poll of the feed, shaped for the archive.

    Stores the TEXT alongside the linkage, because the point of the archive is
    to make a keyword rule gradeable later -- and a rule that has not been
    written yet cannot have its features extracted now. Keeping only today's
    classification would bake in today's guesses.
    """
    from datetime import date

    articles, status = fetch_espn_news(limit=limit)
    espn_index = espn_id_index(season)
    names = _name_index(load_fantasy_players(season))
    captured_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    rows: list[dict[str, Any]] = []
    linked = 0
    for article in articles:
        text = _article_text(article)
        players = _tagged_players(article, espn_index)
        via = "espn_tag" if players else ""
        if not players:
            normalized = _normalise_name(text)
            for key, player in names.items():
                if len(key) >= 6 and key in normalized and player.player_id:
                    players.append(player.player_id)
                    via = "name_match"
        if players:
            linked += 1
        rows.append(
            {
                "id": str(article.get("id") or article.get("headline") or "")[:120],
                "published": str(article.get("published") or ""),
                "headline": str(article.get("headline") or "")[:300],
                "description": str(article.get("description") or "")[:900],
                "type": str(article.get("type") or ""),
                # The article's own URL, so a reader can go and read the thing
                # rather than take a 900-character excerpt as the whole story.
                # Guarded at every hop: ESPN nests it three deep and older
                # archive rows predate this field entirely, so the UI must treat
                # an absent link as normal rather than as an error.
                "link": str((((article.get("links") or {}).get("web") or {}).get("href") or ""))[:400],
                "players": players,
                "linked_via": via,
            }
        )

    return {
        "season": season,
        "captured_at": captured_at,
        "captured_date": captured_at[:10],
        "source_status": status,
        "articles": rows,
        "linked_players": linked,
    }


def news_archive_path(day: str) -> Path:
    from syndicate.features.nfl.sources import nfl_artifact_output_root

    return nfl_artifact_output_root() / "fantasy" / "news_archive" / f"nfl_news_{day}.json"


def recent_news_by_player(season: int, *, days: int = 21) -> dict[str, list[dict[str, Any]]]:
    """``gsis_id -> recent articles``, newest first, from the ARCHIVE.

    Reads only published archive files, never the network: this is on the web
    request path, and a page that fetches a third-party feed per request is
    both slow and a dependency on someone else's uptime.
    """
    from datetime import date, timedelta
    from syndicate.features.nfl.sources import default_nfl_source_root

    root = default_nfl_source_root() / "fantasy" / "news_archive"
    out: dict[str, list[dict[str, Any]]] = {}
    if not root.is_dir():
        return out
    today = date.today()
    for offset in range(days):
        day = (today - timedelta(days=offset)).isoformat()
        path = root / f"nfl_news_{day}.json"
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for article in payload.get("articles") or []:
            for player_id in article.get("players") or []:
                out.setdefault(player_id, []).append(article)
    for entries in out.values():
        entries.sort(key=lambda item: item.get("published") or "", reverse=True)
    return out


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
