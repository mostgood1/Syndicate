"""Archive the NFL news feed, daily, so that it becomes gradeable.

WHY THIS EXISTS AND WHY IT COMES FIRST. The injury half of the news layer could
be graded the day it was written, because nflverse archives the weekly injury
report going back to 2009. The TEXT half could not be graded at all -- ESPN
serves only CURRENT headlines, so there is no record of what was written before
a past game, and a keyword rule cannot be scored against text that no longer
exists.

That is not a permanent property of the problem. It is a consequence of nobody
having stored it. This job stores it.

Every capture is an append-only dated document. After a few weeks there is a
real corpus: what was said, when, about whom -- and at that point
`scripts/grade_nfl_fantasy_news.py` can ask the only question that matters,
which is whether a player the beat writers were talking up on Thursday actually
out-performed his projection on Sunday.

Until then the layer stays OFF and the page shows the quotes WITHOUT letting
them move a number. Reading the news is useful; weighting it unmeasured is not.

    python scripts/capture_nfl_news.py --limit 60
    python scripts/capture_nfl_news.py --limit 60 --publish
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from syndicate.features.nfl.fantasy_news import capture_news_snapshot  # noqa: E402
from syndicate.features.nfl.fantasy_news import news_archive_path  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", type=int, default=2026)
    parser.add_argument("--limit", type=int, default=60)
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    snapshot = capture_news_snapshot(args.season, limit=args.limit)
    path = news_archive_path(snapshot["captured_date"])
    path.parent.mkdir(parents=True, exist_ok=True)

    # APPEND-ONLY WITHIN THE DAY, keyed by article id. The feed is polled more
    # than once a day and mostly repeats itself; overwriting would keep only
    # the last poll and silently lose everything published earlier that day,
    # which is exactly the history this job exists to build.
    existing: dict[str, dict] = {}
    if path.is_file():
        try:
            existing = {
                item["id"]: item
                for item in json.loads(path.read_text(encoding="utf-8")).get("articles", [])
                if item.get("id")
            }
        except (OSError, ValueError):
            existing = {}
    before = len(existing)
    for item in snapshot["articles"]:
        existing.setdefault(item["id"], item)

    path.write_text(
        json.dumps(
            {
                "captured_date": snapshot["captured_date"],
                "last_capture_at": snapshot["captured_at"],
                "source_status": snapshot["source_status"],
                "articles": sorted(existing.values(), key=lambda item: item.get("published") or ""),
            },
            indent=1,
        ),
        encoding="utf-8",
    )

    added = len(existing) - before
    print(
        f"[news_capture] status={snapshot['source_status']} fetched={len(snapshot['articles'])} "
        f"new={added} total_today={len(existing)} linked={snapshot['linked_players']} -> {path}",
        flush=True,
    )

    if snapshot["source_status"] != "ok":
        # A feed that cannot be read is not a day with no news, and the two must
        # never look alike in the archive.
        print("  FEED UNREACHABLE -- today's archive is INCOMPLETE, not empty.", flush=True)

    published = None
    if args.publish:
        from syndicate.features.shared.artifact_publisher import publish_hot_artifact

        published = publish_hot_artifact(path, timeout_seconds=60)
        print(f"[news_capture] publish -> {published}", flush=True)

    if args.json:
        print(json.dumps({"path": str(path), "added": added, "total": len(existing),
                          "published": published, "status": snapshot["source_status"]}, indent=1))
    return 0 if snapshot["source_status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
