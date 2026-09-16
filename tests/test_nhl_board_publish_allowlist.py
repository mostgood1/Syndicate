"""The NHL board files live-odds-worker generates can be published to web.

Lane nhl-season-readiness, 2026-09-16. Web's /nhl/api/cards reads predictions_{date}.csv /
predictions_sim_{date}.csv and lineups_{date}.csv from web's OWN
disk, while generation runs only in live-odds-worker's refresh loop. Before these patterns every
one of those paths was refused by the publish allowlist, so web's NHL board would be empty.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared.artifact_publisher import (
    is_exportable_artifact_relative_path,
    is_hot_artifact_relative_path,
)

DATE = "2026-09-19"


@pytest.mark.parametrize(
    "relative_path",
    [
        f"nhl_source/data/processed/predictions_{DATE}.csv",
        f"nhl_source/data/processed/predictions_sim_{DATE}.csv",
        f"nhl_source/data/processed/lineups_{DATE}.csv",
    ],
)
def test_nhl_board_files_are_publishable_and_exportable(relative_path):
    assert is_hot_artifact_relative_path(relative_path)
    assert is_exportable_artifact_relative_path(relative_path)


@pytest.mark.parametrize(
    "relative_path",
    [
        f"nhl_source/data/processed/predictions_{DATE}.csv.tmp",
        f"wnba_source/data/processed/predictions_{DATE}.csv",
        f"nhl_source/data/raw/predictions_{DATE}.csv",
        f"nhl_source/data/odds/games/date={DATE}/oddsapi.csv",
        "../nhl_source/data/processed/predictions_x.csv",
        # Deliberately NOT allowlisted: a date=* directory pattern widens the dated-pull walk
        # that already runs past its timeout. It is only the cards' fallback.
        f"nhl_source/data/odds/games/date={DATE}/scoreboard.csv",
    ],
)
def test_lookalikes_stay_refused(relative_path):
    assert not is_hot_artifact_relative_path(relative_path)
