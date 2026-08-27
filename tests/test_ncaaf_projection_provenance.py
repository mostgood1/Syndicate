"""A projections file must record WHICH CALIBRATION produced it.

WHY THIS AND NOT A LOG LINE. `profile_name` is a constant ("ncaaf_v2") and
cannot distinguish the shipped default from a promoted artifact, so before these
columns a projections CSV could not say whether the re-fitted profile had
actually been used.

The diagnostic this replaces was a print at module import. Measured 2026-08-27,
that is weakly reachable for the purpose: NOTHING in the refresh worker's boot
path imports the profile -- `run_refresh_worker.py` invokes
`generate_smartsim2_ncaaf_projections.py` as a SUBPROCESS -- so a boot-time log
search reads zero forever, however long you wait. Provenance belongs on the
OUTPUT ARTIFACT, beside `rating_source` and `generated_at`, which already record
exactly this kind of fact and are readable from anywhere the file is.

BACKWARD COMPATIBILITY IS THE LOAD-BEARING PART. 17 projection CSVs are already
committed, including the 2026 wk1 file the live board reads. `from_csv_row` used
hard `row["..."]` indexing, so a REQUIRED column would have broken every one of
them the moment this shipped.
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.ncaaf.smartsim2_projection import (
    PROJECTION_CSV_COLUMNS,
    SmartSimNcaafProjection,
    read_projection_artifact,
    write_projection_artifact,
)

_BASE = dict(
    game_id="401856766", season=2026, week=1, home_team="TCU", away_team="North Carolina",
    home_score_mean=30.3, away_score_mean=20.037, margin_mean=10.263, total_mean=50.337,
    margin_stdev=13.291, total_stdev=11.719, home_win_rate=0.8, seeds_used=300,
    profile_name="ncaaf_v2", rating_source="cfbd_sp_plus_2026", generated_at="2026-08-27T18:00:00+00:00",
)


def test_the_columns_are_in_the_csv_schema():
    assert "profile_source" in PROJECTION_CSV_COLUMNS
    assert "profile_version" in PROJECTION_CSV_COLUMNS


def test_a_projection_round_trips_its_provenance(tmp_path):
    p = SmartSimNcaafProjection(**_BASE, profile_source="artifact", profile_version="ncaaf-goal-line-refit-1")
    write_projection_artifact([p], season=2026, week=1, data_root=tmp_path)
    back = read_projection_artifact(season=2026, week=1, data_root=tmp_path)
    assert len(back) == 1
    assert back[0].profile_source == "artifact"
    assert back[0].profile_version == "ncaaf-goal-line-refit-1"


def test_the_written_header_carries_the_columns(tmp_path):
    """A reader outside this module -- a notebook, a spreadsheet -- must see them."""
    p = SmartSimNcaafProjection(**_BASE, profile_source="artifact", profile_version="v1")
    path = write_projection_artifact([p], season=2026, week=1, data_root=tmp_path)
    header = next(csv.reader(path.open(encoding="utf-8-sig")))
    assert "profile_source" in header and "profile_version" in header


def test_A_PRE_PROVENANCE_CSV_STILL_LOADS(tmp_path):
    """THE COMPATIBILITY GUARANTEE. 17 committed CSVs predate these columns,
    including the 2026 wk1 file the live board reads. A required column would
    have broken every one of them."""
    path = tmp_path / "smartsim2_projections_2026_wk1.csv"
    old_columns = [c for c in PROJECTION_CSV_COLUMNS if c not in {"profile_source", "profile_version"}]
    with path.open("w", encoding="utf-8", newline="") as handle:
        w = csv.DictWriter(handle, fieldnames=old_columns)
        w.writeheader()
        w.writerow({c: str(_BASE[c]) for c in old_columns})
    rows = read_projection_artifact(season=2026, week=1, data_root=tmp_path)
    assert len(rows) == 1
    assert rows[0].margin_mean == pytest.approx(10.263), "the real data must survive"
    assert rows[0].profile_source == "unknown"
    assert rows[0].profile_version == ""


def test_an_older_file_says_UNKNOWN_not_default():
    """A pre-provenance artifact genuinely does not record which profile made
    it. Defaulting to "default" would assert a fact the file never carried, and
    would be indistinguishable from a run that really did use the default."""
    p = SmartSimNcaafProjection(**_BASE)
    assert p.profile_source == "unknown"
    assert p.profile_source != "default"


def test_the_generator_stamps_the_LOADED_profile_not_a_constant():
    """Reachability: it must read the profile metadata, not hardcode a value."""
    import ast

    src = (REPO_ROOT / "scripts" / "generate_smartsim2_ncaaf_projections.py").read_text(encoding="utf-8")
    assert "NCAAF_CALIBRATION_PROFILE_METADATA" in src
    tree = ast.parse(src)
    stamped = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg in {"profile_source", "profile_version"}:
            # the value must reference the metadata, not be a literal
            assert not isinstance(node.value, ast.Constant), (
                f"{node.arg} is hardcoded; it must come from the loaded profile's metadata"
            )
            stamped.add(node.arg)
    assert stamped == {"profile_source", "profile_version"}
