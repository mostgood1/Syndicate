"""NCAAF `_team_context`'s indexes are built once per rows object (lane `web-restart-healthz`).

py-spy on the fleet refresh-worker 2026-10-06 20:45 CT: during the board's NCAAF
hydration, `_team_registry_index` (rebuilt + regex-normalised over the whole registry on
every `_resolve_team`) was 36.5% and `_count_rows` (full roster/transfer scans per team)
32.5% of the NCAAF samples. Equivalence on fleet data: 6,848 `_team_context` calls, 0
differences; 240 calls 12.36 s -> 0.03 s.
"""

from __future__ import annotations

import random

from syndicate.features.ncaaf import cards


def _rows(n: int, seed: int) -> tuple:
    rng = random.Random(seed)
    out = []
    for _ in range(n):
        out.append({"team_id": str(rng.choice([" 1", "2", "3 ", "", "4"])),
                    "season": rng.choice(["2026", "2025", "", " 2026 "]),
                    "destination_team_id": str(rng.choice(["1", "2"]))})
    out.append("not a dict")
    return tuple(out)


def test_count_rows_matches_the_linear_scan():
    rows = _rows(500, 3)
    for key in ("team_id", "destination_team_id"):
        for team in ("1", " 2 ", "3", "9", ""):
            for season in (None, 2026, 2025, 2030):
                assert cards._count_rows(rows, key=key, team_id=team, season=season) == \
                    cards._count_rows_scan(rows, key=key, team_id=team, season=season)


def test_count_index_follows_the_rows_object():
    first = ({"team_id": "1", "season": "2026"},)
    second = ({"team_id": "1", "season": "2026"}, {"team_id": "1", "season": ""})
    assert cards._count_rows(first, key="team_id", team_id="1", season=2026) == 1
    assert cards._count_rows(second, key="team_id", team_id="1", season=2026) == 2   # new object -> rebuilt


def test_registry_index_follows_the_rows_object(monkeypatch):
    current = {"rows": ({"team_id": "1", "canonical_team_name": "Alpha State"},)}
    monkeypatch.setattr(cards, "_team_registry_rows", lambda: current["rows"])
    monkeypatch.setattr(cards, "_REGISTRY_INDEX_MEMO", [None, None])
    assert cards._resolve_team("alpha state")["team_id"] == "1"
    current["rows"] = ({"team_id": "2", "canonical_team_name": "Alpha State"},)   # a cache_clear() gives a new tuple
    assert cards._resolve_team("Alpha State")["team_id"] == "2"
