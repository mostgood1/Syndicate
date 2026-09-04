"""Reachability + invariant tests for the MLB hitter prop distributions.

`model_engine_standard.md` §4.3: write the REACHABILITY test first. The defect
these cover is `#334`/`#429`'s third instance -- `_HITTER_PROP_DIST_SPECS`
carries `("strikeouts", "SO", "so_mean")` while the per-sim `hitter_stat_values`
dict that feeds it has no `"SO"` key, so `.get(row_key, 0)` -- a NEUTRAL DEFAULT,
§4.2 -- returned 0 on every sim of every hitter of every game. The published
ladder said every MLB hitter strikes out exactly zero times with probability
1.000, and `batter_strikeouts` is a real fetched-and-joined market.

`test_strikeouts_dist_is_reachable` FAILS on the unfixed code and passes after;
it drives the real `_sim_many` over the real sim engine rather than asserting on
a fixture, because a fixture cannot tell reachable from unfed.

`test_every_hitter_spec_row_key_is_populated` is the import-time-style invariant
that would have caught this class of defect loudly at either site. See the
`scripts/sim_input_checklist.py` note: that gate enumerates INPUT dataclass
fields, so an OUTPUT spec/dict mismatch like this one is structurally invisible
to it.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
VENDOR_ROOT = REPO_ROOT / "vendor" / "mlb_bettingv2"

if str(VENDOR_ROOT) not in sys.path:
    sys.path.insert(0, str(VENDOR_ROOT))

daily_update = pytest.importorskip("tools.daily_update")

from sim_engine.models import (  # noqa: E402
    BatterProfile,
    Handedness,
    Lineup,
    ManagerProfile,
    PitcherProfile,
    Player,
    Team,
    TeamRoster,
)


def _batter(pid: int, name: str) -> BatterProfile:
    return BatterProfile(
        player=Player(
            mlbam_id=pid,
            full_name=name,
            primary_position="OF",
            bat_side=Handedness.R,
            throw_side=Handedness.R,
        ),
        # A deliberately HIGH strikeout rate. The point of the test is that the
        # accumulated distribution must have more than one bin; a league-average
        # rate would also produce that, but this makes a false pass from a thin
        # sim count effectively impossible.
        k_rate=0.35,
    )


def _roster(team_id: int, abbr: str, pid_base: int) -> TeamRoster:
    batters = [_batter(pid_base + i, f"{abbr} Batter {i}") for i in range(9)]
    pitcher = PitcherProfile(
        player=Player(
            mlbam_id=pid_base + 100,
            full_name=f"{abbr} Starter",
            primary_position="P",
            bat_side=Handedness.R,
            throw_side=Handedness.R,
        ),
        role="SP",
    )
    bullpen = [
        PitcherProfile(
            player=Player(
                mlbam_id=pid_base + 101 + i,
                full_name=f"{abbr} Reliever {i}",
                primary_position="P",
                bat_side=Handedness.R,
                throw_side=Handedness.R,
            ),
            role="RP",
        )
        for i in range(4)
    ]
    return TeamRoster(
        team=Team(team_id=team_id, name=f"{abbr} Team", abbreviation=abbr),
        manager=ManagerProfile(),
        lineup=Lineup(batters=batters, pitcher=pitcher, bullpen=bullpen),
    )


@pytest.fixture(scope="module")
def sim_result():
    away = _roster(1, "AAA", 1000)
    home = _roster(2, "HHH", 2000)
    return daily_update._sim_many(
        away_roster=away,
        home_roster=home,
        sims=40,
        seed=20260904,
        workers=1,
        hitter_props_top_n=24,
    )


def _hitter_prop_rows(result) -> list[dict]:
    rows = result.get("hitter_props") or []
    if isinstance(rows, dict):
        rows = list(rows.values())
    return [r for r in rows if isinstance(r, dict)]


def test_strikeouts_dist_is_reachable(sim_result):
    """REACHABILITY (§4.3): at least one batter must strike out a varying number
    of times across sims. On the unfixed code every row is `{0: n_sims}`."""
    rows = _hitter_prop_rows(sim_result)
    assert rows, "sim produced no hitter_props rows -- test cannot discriminate"

    multi_bin = []
    for row in rows:
        dist = row.get("strikeouts_dist") or {}
        if len(dist) > 1:
            multi_bin.append((row.get("name"), dist))

    assert multi_bin, (
        "strikeouts_dist has a single bin for ALL %d hitters -- the field is "
        "UNFED, not merely quiet. Distributions seen: %r"
        % (len(rows), [row.get("strikeouts_dist") for row in rows[:5]])
    )


def test_so_mean_is_positive_for_some_hitter(sim_result):
    """The mean the ladder actually publishes (`so_mean`) must be non-zero."""
    rows = _hitter_prop_rows(sim_result)
    means = [float(row.get("so_mean") or 0.0) for row in rows]
    assert any(m > 0.0 for m in means), (
        "so_mean is 0.0 for all %d hitters; ladders_build.py maps "
        "hitter_strikeouts -> so_mean, so the published model would say every "
        "hitter strikes out zero times with probability 1.000" % len(rows)
    )


def _hitter_stat_value_sites() -> list[list[str]]:
    """Return the key list of every `hitter_stat_values = {...}` dict literal.

    Parsed with `ast`, not a regex. A regex over the source is fragile in
    exactly the way this defect is: the fix's own comment contains a literal
    `{0: n_sims}`, whose brace truncated a non-greedy match and made the dict
    look SHORTER than it is -- a false PASS shaped like the bug being tested.
    """
    import ast

    tree = ast.parse((VENDOR_ROOT / "tools" / "daily_update.py").read_text(encoding="utf-8"))
    sites: list[list[str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Dict):
            continue
        targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if "hitter_stat_values" not in targets:
            continue
        sites.append(
            [k.value for k in node.value.keys if isinstance(k, ast.Constant)]
        )
    return sites


def test_every_hitter_spec_row_key_is_populated():
    """INVARIANT: `set(spec row_keys) <= set(hitter_stat_values keys)`.

    Checked at BOTH duplicated accumulation sites, because the `#334`/`#429`
    failure mode is fixing one copy and not the other.
    """
    sites = _hitter_stat_value_sites()
    assert len(sites) == 2, (
        "expected exactly TWO hitter_stat_values sites (_simw_chunk and "
        "_sim_many); found %d. If a site was added or removed, this test and "
        "the `#334` comments at both sites need updating together." % len(sites)
    )

    required = {row_key for _dist, row_key, _mean in daily_update._HITTER_PROP_DIST_SPECS}
    for index, keys in enumerate(sites):
        missing = required - set(keys)
        assert not missing, (
            "hitter_stat_values site #%d does not populate %r, which "
            "_HITTER_PROP_DIST_SPECS reads. `.get(row_key, 0)` makes this "
            "silent: the dist becomes {0: n_sims} and the mean 0.0."
            % (index + 1, sorted(missing))
        )


def test_both_accumulation_sites_are_identical():
    """The two copies must not drift -- that drift IS `#334`."""
    sites = _hitter_stat_value_sites()
    assert sites[0] == sites[1], (
        "the two hitter_stat_values dicts have drifted: %r vs %r" % (sites[0], sites[1])
    )
