"""`#360` -- a stale git mirror must not overwrite a freshly simulated league.

MEASURED. On 2026-08-11 the soccer sim was repaired and la_liga began writing
`recommendations_2026-08-15.json` to the runtime disk (verified by mtime >=
launch, twice). The board built SEVEN MINUTES LATER still served:

    la_liga   generated_at 2026-07-20T21:32:50   (528.5h stale)
    mls       generated_at 2026-08-11T21:27:18   (0.6h)

`load_soccer_projections` loaded every matching file from every root, and
`_load_one` ASSIGNS rather than merges (`generated_at_by_league[league]`,
`by_event[id]`, `by_teams[(home, away)]` are plain writes). `preferred_source_roots`
orders the runtime disk first and the git repo mirror second, so the mirror won.

THE SPLIT IS THE PROOF, and it is why this is a test and not a hunch: the
checkout tracks `la_liga/api/recommendations/recommendations_2026-08-15.json` --
exactly the simulated date -- so la_liga was overwritten, while the checkout's
newest mls file is from July, so nothing overwrote mls. Same code path, same
board, opposite outcome, decided purely by which stale files git happens to carry.
Any league whose git-tracked dates catch up to the live slate would silently
inherit la_liga's bug.

The fallback itself is NOT the bug and must survive: a league the runtime disk
lacks entirely still has to come from the mirror. Both halves are asserted.
"""

from __future__ import annotations

import json
from pathlib import Path

from syndicate.features.shared.soccer_projections import load_soccer_projections

DATE = "2026-08-15"


def _write(root: Path, league: str, generated_at: str, *, home: str = "Getafe", away: str = "Alaves") -> None:
    path = root / league / "api" / "recommendations" / f"recommendations_{DATE}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "league": league,
                "generated_at": generated_at,
                "matches": [
                    {
                        "event_id": f"{league}-evt-1",
                        "matchup": {"home_team": home, "away_team": away},
                        "generated_at": generated_at,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def test_the_fresh_runtime_disk_beats_the_stale_mirror(tmp_path):
    runtime, mirror = tmp_path / "runtime", tmp_path / "mirror"
    _write(runtime, "la_liga", "2026-08-11T21:54:14")   # what the sim just wrote
    _write(mirror, "la_liga", "2026-07-20T21:32:50")    # what git carries
    index = load_soccer_projections([runtime, mirror], DATE)
    assert index.generated_at_by_league["la_liga"] == "2026-08-11T21:54:14", (
        "the git mirror overwrote a freshly simulated league -- this is the board bug"
    )
    # The match payload must come from the same file, not just the timestamp.
    assert index.by_event["la_liga-evt-1"]["generated_at"] == "2026-08-11T21:54:14"


def test_root_order_is_what_decides_not_luck(tmp_path):
    # Reversing the roots reverses the winner. If this passes with both orders
    # giving the same answer, precedence is not actually being applied.
    runtime, mirror = tmp_path / "runtime", tmp_path / "mirror"
    _write(runtime, "la_liga", "2026-08-11T21:54:14")
    _write(mirror, "la_liga", "2026-07-20T21:32:50")
    reversed_index = load_soccer_projections([mirror, runtime], DATE)
    assert reversed_index.generated_at_by_league["la_liga"] == "2026-07-20T21:32:50"


def test_the_mirror_still_serves_a_league_the_runtime_disk_lacks(tmp_path):
    # The fallback's whole purpose. Breaking this would trade one outage for another.
    runtime, mirror = tmp_path / "runtime", tmp_path / "mirror"
    _write(runtime, "la_liga", "2026-08-11T21:54:14")
    _write(mirror, "championship", "2026-08-10T09:00:00")
    index = load_soccer_projections([runtime, mirror], DATE)
    assert index.generated_at_by_league["la_liga"] == "2026-08-11T21:54:14"
    assert index.generated_at_by_league["championship"] == "2026-08-10T09:00:00"
    assert index.matches == 2


def test_mls_shaped_case_is_unaffected(tmp_path):
    # mls rendered CORRECTLY in production only because git had no 08-15 file.
    # That accident must keep working the same way once precedence is explicit.
    runtime, mirror = tmp_path / "runtime", tmp_path / "mirror"
    _write(runtime, "mls", "2026-08-11T21:27:18")
    (mirror / "mls" / "api" / "recommendations").mkdir(parents=True, exist_ok=True)
    index = load_soccer_projections([runtime, mirror], DATE)
    assert index.generated_at_by_league["mls"] == "2026-08-11T21:27:18"


def test_an_unreadable_first_root_does_not_suppress_a_good_mirror(tmp_path):
    # A league is claimed only by a file that actually PARSED. Otherwise a
    # truncated or half-written file on the runtime disk would blank the league
    # entirely -- strictly worse than the staleness being fixed here.
    runtime, mirror = tmp_path / "runtime", tmp_path / "mirror"
    bad = runtime / "la_liga" / "api" / "recommendations" / f"recommendations_{DATE}.json"
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_text("{ this is not json", encoding="utf-8")
    _write(mirror, "la_liga", "2026-07-20T21:32:50")
    index = load_soccer_projections([runtime, mirror], DATE)
    assert index.generated_at_by_league["la_liga"] == "2026-07-20T21:32:50", (
        "an unparseable runtime file suppressed the mirror's good copy"
    )


def test_duplicate_roots_do_not_double_count(tmp_path):
    runtime = tmp_path / "runtime"
    _write(runtime, "la_liga", "2026-08-11T21:54:14")
    index = load_soccer_projections([runtime, runtime], DATE)
    assert index.matches == 1
