"""WNBA branding resolved to one root and that root has no file on Render.

MEASURED on production web 2026-08-08, the served slate for the date:

    GET /wnba/api/cards?date=2026-08-08
    SEA POR IND CHI LVA MIN  ->  primary_color: None x6
    BRANDING COVERAGE: 0 of 6 team slots

TWO independent causes, and fixing either alone is a no-op:

  1. `preferred_source_roots(...)[0]` discarded the repo fallback that helper
     deliberately appends on Render -- the defect class the soccer session
     root-caused the same day (`60689dee`), reported as live at
     `wnba/cards.py:321`; and
  2. the file was not in the repo to fall back TO. `.gitignore`'s
     `data/*_source/source_artifacts/` swallowed it, and unlike NFL/NCAAF
     (`e2cd339c`) WNBA never got the narrow un-ignore.

Confirmed via /api/ops/wnba/artifact-counts that on Render the
`source_artifacts/data/processed` root has NO files at all while
`.../wnba_source/data/processed` is where the day's artifacts land -- so the
hard-coded `source_artifacts` segment is a third way to miss the file.

These tests pin the Render SHAPE, not the local one: locally the file sits at
roots[0] and the bug is invisible.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from syndicate.features.wnba import cards as wnba_cards


BRANDING_CSV = (
    "team_id,abbreviation,location,display_name,primary_color,secondary_color,logo_url,source_snapshot_date\n"
    "19,CHI,Chicago,Chicago Sky,#5091cd,#ffd520,https://example.invalid/chi.png,2026-07-20\n"
    "5,IND,Indiana,Indiana Fever,#002d62,#e03a3e,https://example.invalid/ind.png,2026-07-20\n"
)


def _write_branding(root: Path, *layout: str) -> None:
    target = root.joinpath(*layout, "team_branding", "wnba_team_branding.csv")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(BRANDING_CSV, encoding="utf-8")


def test_the_repo_fallback_is_used_when_the_mounted_disk_has_no_file(tmp_path):
    """The Render shape: env var points at the mounted disk (empty), and the
    repo checkout is the second candidate `preferred_source_roots` appends.
    Taking [0] threw that away and returned an empty index."""
    mounted = tmp_path / "mounted" / "wnba_source"
    mounted.mkdir(parents=True)
    repo = tmp_path / "repo" / "wnba_source"
    _write_branding(repo, "source_artifacts", "data", "processed")

    with patch.object(wnba_cards, "preferred_source_roots", return_value=[mounted, repo]):
        wnba_cards._wnba_team_branding_index.cache_clear()
        index = wnba_cards._wnba_team_branding_index()

    assert set(index) == {"CHI", "IND"}
    wnba_cards._wnba_team_branding_index.cache_clear()


def test_the_non_source_artifacts_layout_is_also_tried(tmp_path):
    """/api/ops/wnba/artifact-counts showed the day's WNBA artifacts land in
    `<root>/data/processed`, not `<root>/source_artifacts/data/processed`. A
    reader that hard-codes one layout misses a root that does have the file."""
    mounted = tmp_path / "mounted" / "wnba_source"
    _write_branding(mounted, "data", "processed")

    with patch.object(wnba_cards, "preferred_source_roots", return_value=[mounted]):
        wnba_cards._wnba_team_branding_index.cache_clear()
        index = wnba_cards._wnba_team_branding_index()

    assert set(index) == {"CHI", "IND"}
    wnba_cards._wnba_team_branding_index.cache_clear()


def test_no_branding_anywhere_degrades_instead_of_raising(tmp_path):
    """Branding is decoration. Missing it must leave the card colourless, never
    break the slate -- which is why this went unnoticed in production."""
    empty = tmp_path / "empty" / "wnba_source"
    empty.mkdir(parents=True)

    with patch.object(wnba_cards, "preferred_source_roots", return_value=[empty]):
        wnba_cards._wnba_team_branding_index.cache_clear()
        assert wnba_cards._wnba_team_branding_index() == {}
        assert wnba_cards._wnba_primary_color("CHI") is None
    wnba_cards._wnba_team_branding_index.cache_clear()


def test_the_branding_csv_is_committed():
    """Half the fix. With the reader repaired but the file still ignored, the
    repo fallback resolves to a path that does not exist on Render and the
    coverage stays 0 of 6. `.gitignore` un-ignores team_branding ONLY -- WNBA's
    processed/ is per-date artifact output and does not belong in git."""
    import subprocess

    tracked = subprocess.run(
        ["git", "ls-files", "data/wnba_source/source_artifacts/data/processed/team_branding/"],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[1],
    ).stdout.split()

    assert any(name.endswith("wnba_team_branding.csv") for name in tracked), (
        "the branding CSV is not tracked; the repo fallback has nothing to find on Render"
    )
