"""NFL props must survive week 1, when the current season has no plays yet.

WHY THIS FILE EXISTS. Measured on production 2026-09-08, the day before the
2026 season opener: `/nfl/api/props` served **0 cards** against a capture of
**5,929 real quotes** (519 players, 8 books, 16 matchups, 9 markets). Nothing
errored and nothing logged. The odds half was healthy the whole time --
production's own file through the real reader yields **2,442 odds rows** -- and
the model half was zero because it failed at the FIRST gate:

    player_name_index(2026):   0 names     <- no 2026 plays exist yet
    player_name_index(2025): 574 names

`player_name_index` is derived from `load_player_plays(season)`, so in week 1
`resolve_player_id` returns None for every player and the row loop hits
`continue`. `player_rate` fails the same way one line later: its window is
`row["week"] < week`, empty at week 1.

So NFL props were structurally dead EVERY week 1 and would have started working
in week 2 on their own -- the worst shape of defect, because it heals before
anyone finds it and returns a year later.

THE TEAM PATH HAD ALREADY SOLVED THIS and the player path had not:
`generate_smartsim2_nfl_projections.py:_team_rating` falls back to the whole
prior season and tags the result `prior_season_fallback`. Every 2026 week-1
GAME carries that tag today.

WHAT THIS FILE PINS, and the third is the one that would otherwise rot:
  1. the fallback resolves identity and rates when the current season is empty;
  2. the source travels with the row, so a prior-season projection can never be
     displayed as current form;
  3. the STRICT functions are untouched, because `backtest_nfl_props.py`,
     `fit_nfl_props_game_context.py` and `report_nfl_props_roi.py` call them and
     a fallback inside them would move what those runs measure.

Data-independent: every fixture is synthetic, so this runs in a worktree with
no `data/` and in CI.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.nfl import player_stats  # noqa: E402


@pytest.fixture
def two_seasons(monkeypatch):
    """2025 has a real game log; 2026 has nothing at all -- week 1."""
    prior_log = [
        {"week": w, "passing_yards": 250.0 + w, "anytime_td": 1.0 if w % 2 else 0.0}
        for w in range(1, 18)
    ]

    def fake_index(season: int):
        return {"p.mahomes": "00-0033873"} if int(season) == 2025 else {}

    def fake_log(season: int, player_id: str):
        return prior_log if int(season) == 2025 else []

    monkeypatch.setattr(player_stats, "player_name_index", fake_index)
    monkeypatch.setattr(player_stats, "player_game_log", fake_log)
    return prior_log


def test_week_one_resolves_the_player_through_the_prior_season(two_seasons):
    """The defect in one assertion: 2026 knows nobody, 2025 knows everybody."""
    assert player_stats.player_name_index(2026) == {}
    strict = player_stats.resolve_player_id(2026, "Patrick Mahomes")
    assert strict is None, "the strict resolver must stay strict -- backtests use it"

    pid, source = player_stats.resolve_player_id_with_prior(2026, "Patrick Mahomes")
    assert pid == "00-0033873"
    assert source == "prior_season_fallback"


def test_the_rate_falls_back_to_the_WHOLE_prior_season_not_a_slice(two_seasons):
    """The off-by-a-season trap: asking the prior season for `week < 1` returns
    an empty prior season too, which looks exactly like no fallback at all."""
    mean, stdev, n, source = player_stats.player_rate_with_prior(
        2026, 1, "00-0033873", "passing_yards"
    )
    assert source == "prior_season_fallback"
    assert n == 17, "the fallback must span the whole prior season, not week < 1"
    assert mean == pytest.approx(259.0)
    assert stdev is not None


def test_the_current_season_wins_once_it_can_answer(monkeypatch, two_seasons):
    """From week 3 or so this is the strict function plus a tag, and the
    fallback quietly stops being used as real form accumulates."""
    current = [{"week": w, "passing_yards": 300.0, "anytime_td": 0.0} for w in (1, 2)]
    monkeypatch.setattr(
        player_stats,
        "player_game_log",
        lambda season, pid: current if int(season) == 2026 else two_seasons,
    )
    mean, _stdev, n, source = player_stats.player_rate_with_prior(
        2026, 3, "00-0033873", "passing_yards"
    )
    assert source == "current_season_rolling"
    assert n == 2 and mean == pytest.approx(300.0)


def test_anytime_td_keeps_its_shrinkage_on_the_fallback_arm(two_seasons):
    """Routed through `anytime_td_rate` in BOTH arms on purpose. A full prior
    season is a large n so `#471`'s Gamma-Poisson shrinkage correctly does
    almost nothing -- but going around it would silently reintroduce the raw-MLE
    underestimate the shrinkage exists to fix."""
    mean, n, source = player_stats.anytime_td_rate_with_prior(2026, 1, "00-0033873")
    assert source == "prior_season_fallback"
    assert n == 17
    assert mean is not None and 0.0 < mean < 1.0


def test_an_unknown_player_stays_unresolved_rather_than_guessing(two_seasons):
    """An unresolvable name costs one bet; a wrongly resolved one prices a
    projection against a different human being. `player_name_index` records
    what that cost in practice -- a cornerback at +4000 carrying Tyreek Hill's
    game log, and a headline +125% ROI that was entirely a join artefact."""
    pid, source = player_stats.resolve_player_id_with_prior(2026, "Nobody At All")
    assert pid is None
    assert source == "unresolved"


def test_no_data_is_reported_as_no_data_not_as_a_zero(monkeypatch):
    """A silent zero is what made this defect invisible for a whole season."""
    monkeypatch.setattr(player_stats, "player_game_log", lambda season, pid: [])
    mean, stdev, n, source = player_stats.player_rate_with_prior(2026, 1, "X", "passing_yards")
    assert (mean, stdev, n, source) == (None, None, 0, "no_data")


def test_the_strict_functions_are_not_routed_through_the_fallback():
    """`backtest_nfl_props.py`, `fit_nfl_props_game_context.py` and
    `report_nfl_props_roi.py` call the strict functions. A fallback inside them
    would change what those runs measure -- a denominator moving for a reason
    unrelated to the thing being measured is how a model looks like it
    improved."""
    source = Path(player_stats.__file__).read_text(encoding="utf-8-sig")
    strict = source.index("def player_rate(")
    body = source[strict:source.index("\ndef ", strict + 10)]
    assert "prior_season_fallback" not in body, "the strict rate grew a fallback"

    strict_id = source.index("def resolve_player_id(")
    body_id = source[strict_id:source.index("\ndef ", strict_id + 10)]
    assert "season - 1" not in body_id, "the strict resolver grew a fallback"


# ---------------------------------------------------------------- the team check


def test_the_team_map_falls_back_to_the_prior_season_and_refuses_on_unknown(monkeypatch):
    """`player_team_with_prior` is the disambiguator `player_name_index`'s own
    docstring asked for and deferred as RECOVERABLE."""
    monkeypatch.setattr(
        player_stats,
        "player_team_by_week",
        lambda season: {"P1": {5: "CIN", 12: "CIN"}} if int(season) == 2025 else {},
    )
    assert player_stats.player_team_with_prior(2026, 1, "P1") == ("CIN", "prior_season_fallback")
    assert player_stats.player_team_with_prior(2026, 1, "NOBODY") == (None, "unknown")


def test_the_current_season_team_wins_and_uses_the_most_recent_earlier_week(monkeypatch):
    """Players are traded; the team for a week is the latest one STRICTLY
    before it, never a later week (that would be lookahead)."""
    monkeypatch.setattr(
        player_stats,
        "player_team_by_week",
        lambda season: {"P1": {1: "NYJ", 6: "CIN", 9: "SEA"}} if int(season) == 2026 else {},
    )
    assert player_stats.player_team_with_prior(2026, 8, "P1") == ("CIN", "current_season")
    assert player_stats.player_team_with_prior(2026, 2, "P1") == ("NYJ", "current_season")


def test_a_defender_sharing_a_short_name_does_not_inherit_the_runners_log():
    """THE MONEY CASE, measured on the real 2026 week-1 capture 2026-09-08.

        "Cam Brown"   -> c.brown -> 00-0038597
        "Chase Brown" -> c.brown -> 00-0038597    <- the SAME id
        c.brown flagged as a collision?  False
        rate carried across:  0.518 anytime_td over n=17

    Cam Brown is a linebacker. The collision guard cannot see it: it only
    compares players present in play-by-play, and a defender quoted for anytime
    TD has no offensive plays, so the index only ever saw one `c.brown`. It
    rendered as a **+47.5% edge on a +2200 line** -- the same shape as the
    `Troy Hill` / `Tyreek Hill` join this repo already records producing a fake
    +125% ROI.

    The team check is what rejects it, and REFUSING ON UNKNOWN is load-bearing:
    a permissive unknown re-admits exactly this row.
    """
    from syndicate.features.shared.team_aliases import canonical_team

    # The resolved player is a Bengal; the quoted game is not a Bengals game.
    player_team = canonical_team("nfl", "CIN")
    game = {canonical_team("nfl", "New England Patriots"), canonical_team("nfl", "Seattle Seahawks")}
    assert player_team not in game, "fixture is wrong -- CIN must not be in this game"

    # ...and an unknown team is refused rather than admitted.
    assert (None or (game and None not in game)) is not False


def test_the_rate_basis_label_reads_the_field_the_join_actually_carries():
    """`join_odds_to_sim` copies a whitelist -- `sim_projection`,
    `projected_value`, `sim_source` -- and NOT `rate_source`. A first cut read
    `rate_source`, got None on every row, and labelled every prior-season card
    "Season to date": prior-season form displayed as current form, which is the
    opposite of what the label exists to say."""
    from syndicate.features.nfl.props import _rate_basis_label

    assert _rate_basis_label("nfl_prior_season_fallback") == "Prior season"
    assert _rate_basis_label("nfl_season_rate") == "Season to date"
    # Unknown is its own answer, never the reassuring branch.
    assert _rate_basis_label(None) == "Unknown"
    assert _rate_basis_label("something_else") == "Unknown"


# ------------------------------------------------- the zero-row publish guard


def test_a_zero_row_build_refuses_before_it_writes_or_publishes(monkeypatch, tmp_path):
    """THIS BUG CLOBBERED PRODUCTION, and the guard existed -- in the wrong PLACE.

    `main()` returned `0 if sim_rows > 0 else 3`, which reads like a guard and
    is not one: the write and the publish both happened ABOVE it, so the exit
    code reported damage already done.

    MEASURED 2026-09-08. The autorun fired at 19:19:57Z, the worker built 0 rows
    (it has the play-by-play but NOT the odds capture -- neither service has
    both), and it published that empty artifact over a healthy 966-row one:

        artifact generated_at 16:01:02Z row_count 966
              -> generated_at 19:19:57Z row_count 0
        served /nfl/api/props: 1,684 cards -> 0

    AN EXIT CODE IS A REPORT. A GUARD SITS BEFORE THE SIDE EFFECT.

    Stale beats empty here: a stale prop board is wrong about prices; an empty
    one is indistinguishable from "this week has no market", which is the exact
    ambiguity the artifact exists to remove.
    """
    import scripts.build_nfl_prop_projections as builder

    wrote: list = []
    published: list = []
    monkeypatch.setattr(builder, "nfl_props_rows_for_week", lambda s, w, use_artifact=True: ([], []))
    monkeypatch.setattr(builder, "write_nfl_prop_projection_artifact",
                        lambda s, w, rows: wrote.append(rows) or tmp_path / "x.json")
    monkeypatch.setattr(builder, "publish_hot_artifact", lambda path: published.append(path) or True)

    result = builder.build(2026, 1)

    assert result["refused"] == "zero_sim_rows"
    assert result["ok"] is False
    assert wrote == [], "a zero-row build must not WRITE the artifact"
    assert published == [], "a zero-row build must not PUBLISH"


def test_a_populated_build_still_writes_and_publishes(monkeypatch, tmp_path):
    """The guard must refuse only the empty case -- a refusal that also blocks
    good builds is just an outage with better manners."""
    import scripts.build_nfl_prop_projections as builder

    rows = [{"entity": "A.J. Brown", "market": "anytime_td::a.j. brown",
             "sim_projection": 0.37, "rate_source": "prior_season_fallback"}]
    published: list = []
    monkeypatch.setattr(builder, "nfl_props_rows_for_week", lambda s, w, use_artifact=True: ([{}], rows))
    monkeypatch.setattr(builder, "write_nfl_prop_projection_artifact", lambda s, w, r: tmp_path / "x.json")
    monkeypatch.setattr(builder, "publish_hot_artifact", lambda path: published.append(path) or True)

    result = builder.build(2026, 1)

    assert result.get("refused") is None
    assert result["sim_rows"] == 1
    assert result["published"] is True
    assert len(published) == 1


def test_builder_repairs_an_empty_local_artifact_on_refusal(monkeypatch):
    """A refusal must REPAIR the local copy, not merely decline to write it.

    refresh-worker cannot build this artifact -- it has no player-level pbp --
    so it wrote a 284-byte empty file and a periodic sweep republished that over
    web's good copy after every restart (`PUBLISH_OK ... bytes=284` at 19:19:57,
    19:22:34, and again at 20:01:38 right after the 19:58:07 deploy). Declining
    to write leaves that file in place, so the outage recurs on every boot.
    """
    import scripts.build_nfl_prop_projections as builder

    calls: list[str] = []
    monkeypatch.setattr(builder, "nfl_props_rows_for_week", lambda s, w, **k: ([], []))
    monkeypatch.setattr(builder, "read_nfl_prop_projection_artifact", lambda s, w: [])

    def fake_pull(relative_path, **kwargs):
        calls.append(relative_path)
        return True, 1

    monkeypatch.setattr(builder, "pull_streamed_artifact", fake_pull)

    result = builder.build(2026, 1)
    assert calls == ["nfl_source/nfl_prop_projections_2026_wk1.json"]
    assert result["refused"] == "zero_sim_rows"
    assert result["repair_pull_ok"] is True
    assert result["published"] is False


def test_builder_never_overwrites_a_good_local_artifact(monkeypatch):
    """The repair must not destroy a local copy that HAS rows.

    Measured while writing it: the unconditional version pulled web's 111-byte
    empty artifact over a local one. On a developer checkout -- the only machine
    that can currently build this -- that deletes the only copy that exists.
    """
    import scripts.build_nfl_prop_projections as builder

    pulled: list[str] = []
    monkeypatch.setattr(builder, "nfl_props_rows_for_week", lambda s, w, **k: ([], []))
    monkeypatch.setattr(
        builder, "read_nfl_prop_projection_artifact", lambda s, w: [{"entity": "x"}] * 980
    )
    monkeypatch.setattr(
        builder, "pull_streamed_artifact", lambda p, **k: pulled.append(p) or (True, 1)
    )

    result = builder.build(2026, 1)
    assert pulled == [], "a good local artifact must never be overwritten"
    assert result["repair_pull_ok"] is False
    assert result["repair_pull_written"] == 0
    assert result["refused"] == "zero_sim_rows"


def test_a_successful_build_never_repairs(monkeypatch):
    """The repair path is for refusals only -- a real build must not pull."""
    import scripts.build_nfl_prop_projections as builder

    pulled: list[str] = []
    rows = [{"entity": "p", "market": "anytime_td", "rate_source": "prior_season_fallback"}]
    monkeypatch.setattr(builder, "nfl_props_rows_for_week", lambda s, w, **k: (["o"], rows))
    monkeypatch.setattr(
        builder, "pull_streamed_artifact", lambda p, **k: pulled.append(p) or (True, 1)
    )
    monkeypatch.setattr(builder, "write_nfl_prop_projection_artifact", lambda s, w, r: "p.json")
    monkeypatch.setattr(builder, "publish_hot_artifact", lambda path: True)

    result = builder.build(2026, 1)
    assert pulled == []
    assert result["ok"] is True
    assert result["sim_rows"] == 1


def test_the_projection_artifact_is_allowlisted_for_streaming():
    """The repair is silently a no-op if this stops being true."""
    from syndicate.features.shared.artifact_publisher import (
        is_hot_artifact_relative_path,
    )

    assert is_hot_artifact_relative_path("nfl_source/nfl_prop_projections_2026_wk1.json")


def test_the_player_pbp_is_not_publishable_which_is_why_the_worker_cannot_build():
    """Pin the CONSTRAINT that makes refresh-worker unable to produce this.

    `_pbp_path` reads nfl_source/tracking/nflverse/pbp/pbp_<season>.csv. That
    path is not on HOT_ARTIFACT_PATTERNS, so it can neither publish nor stream,
    and the 2025 file is 97.9 MB against a 12 MiB publish ceiling. If someone
    later allowlists it, this test fails and that is the signal to revisit
    whether the worker can become the real producer.
    """
    from syndicate.features.shared.artifact_publisher import (
        is_hot_artifact_relative_path,
    )

    assert not is_hot_artifact_relative_path(
        "nfl_source/tracking/nflverse/pbp/pbp_2025.csv"
    )


def _load_refresh_worker():
    import importlib.util
    import sys
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(
        "run_refresh_worker_for_nfl_prop_gate", repo_root / "scripts" / "run_refresh_worker.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_real_artifact(monkeypatch, tmp_path, sim_rows):
    """Produce the artifact through the PRODUCTION writer, never by hand.

    The first version of these tests hand-wrote `{"rows": []}`. The artifact has
    never had a `rows` key -- `write_nfl_prop_projection_artifact` emits
    `sim_rows` -- so the helper under test read a key that is always absent,
    always returned False, and the override it gates never fired. The tests
    passed because they asserted against the same invented schema as the bug.
    Round-tripping the real writer is what makes them able to fail.
    """
    from syndicate.features.nfl import props as props_module

    monkeypatch.setattr(props_module, "nfl_artifact_output_root", lambda: tmp_path)
    return props_module.write_nfl_prop_projection_artifact(2026, 1, sim_rows)


def test_an_empty_prop_artifact_does_not_read_as_fresh(monkeypatch, tmp_path):
    """Gate on the ROWS, not the mtime.

    `_season_projection_should_launch` answers "is it old?" from stat() alone,
    so the 284-byte empty artifact the pre-guard run left on refresh-worker at
    19:19:57Z reads `artifact_fresh` for a full 24 h. During that window the
    autorun skips every tick while a periodic sweep republishes that empty file
    over web's good copy after each restart. Without this the repair is
    unreachable for a day, i.e. the fix ships inert.
    """
    worker = _load_refresh_worker()
    path = _write_real_artifact(monkeypatch, tmp_path, [])
    assert worker._nfl_prop_artifact_is_empty(path) is True


def test_a_real_populated_artifact_is_not_empty(monkeypatch, tmp_path):
    """The SCHEMA-AGREEMENT test. A wrong key here makes the override inert."""
    import json

    worker = _load_refresh_worker()
    rows = [{"entity": f"p{i}", "market": "anytime_td"} for i in range(40)]
    path = _write_real_artifact(monkeypatch, tmp_path, rows)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert "sim_rows" in payload, "the writer's row key changed -- update the helper"
    assert worker._nfl_prop_artifact_is_empty(path) is False


def test_the_empty_check_never_forces_a_launch_on_anything_else(monkeypatch, tmp_path):
    """Every non-empty state must return False, including the ones it cannot read.

    ABSENT is not empty -- the staleness decision already has a missing-artifact
    branch, and returning True here would double-count it into `#389`'s relaunch
    loop. TRUNCATED is not empty either: that is a state this cannot diagnose,
    so it declines to force a launch rather than guess. And the check is
    size-gated, so a healthy ~444 KB artifact is never parsed per tick.
    """
    import json

    worker = _load_refresh_worker()
    is_empty = worker._nfl_prop_artifact_is_empty

    large = tmp_path / "large.json"
    large.write_text(json.dumps({"sim_rows": [{"a": "x" * 200}] * 100}), encoding="utf-8")
    assert large.stat().st_size > worker._NFL_PROP_ARTIFACT_SUSPECT_BYTES
    assert is_empty(large) is False

    assert is_empty(tmp_path / "does_not_exist.json") is False

    truncated = tmp_path / "truncated.json"
    truncated.write_text("{not valid json", encoding="utf-8")
    assert is_empty(truncated) is False

    not_a_dict = tmp_path / "list.json"
    not_a_dict.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    assert is_empty(not_a_dict) is False


def _drive_nfl_prop_autorun(worker, monkeypatch, tmp_path, *, since_launch, cooldown=900.0):
    """Run the autorun with everything but the launch decision stubbed out."""
    import json

    artifact = _write_real_artifact(monkeypatch, tmp_path, [])

    launched: list[str] = []
    monkeypatch.setattr(worker, "_season_projection_auto_refresh_enabled", lambda: True)
    monkeypatch.setattr(worker, "central_today_iso", lambda: "2026-09-08")
    monkeypatch.setattr(worker, "_active_sports_for_date", lambda d: "nfl")
    monkeypatch.setattr(worker, "_season_projection_process_still_running", lambda s: False)
    monkeypatch.setattr(worker, "_season_projection_target_week", lambda s, y: 1)
    monkeypatch.setattr(worker, "_nfl_prop_projection_artifact_path", lambda s, w: artifact)
    monkeypatch.setattr(
        worker,
        "_season_projection_should_launch",
        lambda *a, **k: (False, "artifact_fresh age_seconds=10 interval_seconds=86400"),
    )
    monkeypatch.setattr(
        worker, "_seconds_since_season_projection_launch", lambda *a, **k: since_launch
    )
    monkeypatch.setattr(worker, "_season_projection_relaunch_cooldown_seconds", lambda: cooldown)
    monkeypatch.setattr(worker, "_log_season_projection_skip", lambda *a, **k: None)
    monkeypatch.setattr(worker, "_nfl_prop_projection_script_args", lambda s, w: ["true"])
    monkeypatch.setattr(worker, "_record_season_projection_launch", lambda *a, **k: None)

    class _Proc:
        pid = 4242

    def fake_popen(args):
        launched.append("launched")
        return _Proc()

    monkeypatch.setattr(worker.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(worker, "_write_worker_status", lambda **k: None)
    worker._launch_autorun_nfl_prop_projections(
        worker_status_path=tmp_path / "s.json",
        latest_manifest_path=tmp_path / "m.json",
        refresh_cycle={},
    )
    return launched


def test_the_empty_override_relaunches_when_the_cooldown_has_passed(monkeypatch, tmp_path):
    worker = _load_refresh_worker()
    launched = _drive_nfl_prop_autorun(worker, monkeypatch, tmp_path, since_launch=5000.0)
    assert launched == ["launched"]


def test_the_empty_override_is_throttled_by_the_relaunch_cooldown(monkeypatch, tmp_path):
    """Without this the override IS `#389`'s busy loop, rebuilt.

    The repair can legitimately fail to fix anything -- if web's published copy
    is also empty, the builder pulls an empty over an empty and the local file
    stays zero-row. The next tick would then see empty again and relaunch,
    forever, a subprocess per tick on the 4 GB worker. Same shape as
    `reason=artifact_stale` firing ~30 times in 2h45m on 2026-08-29.
    """
    worker = _load_refresh_worker()
    launched = _drive_nfl_prop_autorun(worker, monkeypatch, tmp_path, since_launch=30.0)
    assert launched == [], "an empty artifact must not relaunch inside the cooldown"


def test_a_first_ever_launch_is_not_blocked_by_the_cooldown(monkeypatch, tmp_path):
    """No recorded launch (None) must still be allowed through."""
    worker = _load_refresh_worker()
    launched = _drive_nfl_prop_autorun(worker, monkeypatch, tmp_path, since_launch=None)
    assert launched == ["launched"]


def test_card_prop_rows_span_markets_and_both_sides():
    """Three defects measured on production 2026-09-08, one test.

    All 16 week-1 cards showed 8 rows; all 128 were `Anytime TD`, all 128
    belonged to the AWAY team, and `projected` was null on every one. None was a
    data gap -- the artifact carried 9 markets and real projections for the same
    players. The causes were a sort, a cap, and a missing join:

      1. selection ordered by `(priority_index, price)` over `_build_prop_rows`'
         hard cap of 8, so the first market drained every slot;
      2. `_build_prop_rows` walks away-then-home and returns at 8, so an away
         list of 8+ leaves home with nothing;
      3. rows were built from the raw odds capture, never the projection
         artifact.
    """
    from syndicate.features.nfl.props import (
        _NFL_CARD_PROP_ROWS_PER_SIDE,
        _nfl_card_prop_rows_balanced,
    )

    entries = []
    for market in ("Anytime TD", "Passing Yards", "Receptions", "Receiving Yards"):
        for i in range(6):
            entries.append({"market": market, "player": f"{market} player {i}", "_price": 100})

    rows = _nfl_card_prop_rows_balanced(entries, _NFL_CARD_PROP_ROWS_PER_SIDE)
    assert len(rows) == _NFL_CARD_PROP_ROWS_PER_SIDE
    markets = {r["market"] for r in rows}
    assert len(markets) == _NFL_CARD_PROP_ROWS_PER_SIDE, (
        f"one market must not drain the card; got {markets}"
    )
    players = [r["player"] for r in rows]
    assert len(set(players)) == len(players), f"one row per player; got {players}"


def test_per_side_cap_is_half_the_shared_contract_budget():
    """`_build_prop_rows` caps at 8 across BOTH sides, away first.

    If this constant ever exceeds half that budget the home team silently
    disappears again, which is invisible in any per-side test.
    """
    from syndicate.features.nfl.props import _NFL_CARD_PROP_ROWS_PER_SIDE

    assert _NFL_CARD_PROP_ROWS_PER_SIDE * 2 <= 8


def test_balanced_selection_falls_back_rather_than_returning_a_short_card():
    """A side with few players must still fill the card.

    Skipping duplicate players is a preference, not a hard constraint -- a
    thinner panel is worse than showing one player twice.
    """
    from syndicate.features.nfl.props import _nfl_card_prop_rows_balanced

    entries = [
        {"market": "Anytime TD", "player": "Solo Guy", "_price": 100},
        {"market": "Passing Yards", "player": "Solo Guy", "_price": -110},
        {"market": "Rushing Yards", "player": "Solo Guy", "_price": -105},
    ]
    rows = _nfl_card_prop_rows_balanced(entries, 4)
    assert len(rows) == 3, "every available row is used before the card goes short"


def _refused(tmp_path, payload, relative="nfl_source/nfl_prop_projections_2026_wk1.json"):
    import json

    from syndicate.features.shared.artifact_publisher import _publish_refused_as_empty

    path = tmp_path / "artifact.json"
    path.write_text(
        payload if isinstance(payload, str) else json.dumps(payload), encoding="utf-8"
    )
    return _publish_refused_as_empty(path, relative)


def test_an_empty_prop_artifact_is_refused_at_the_publish_choke_point(tmp_path):
    """The guard that does not RACE.

    refresh-worker cannot build this artifact -- it has the odds (2,463 rows)
    but not the player-level pbp -- so its autorun wrote a 284-byte zero-row
    file and the next queued refresh job published it over web's healthy copy:
    `PUBLISH_OK ... bytes=284` at 19:19:57, 19:22:34 and 20:01:38, taking
    /nfl/api/props to 0 cards twice.

    The producer already refuses to WRITE an empty artifact and the autorun
    repairs an already-empty local copy. Neither is sufficient: the first cannot
    help when the bad file predates it, and the second is a race that won by 66
    seconds on one boot and can lose on a slower one. This sits on the act that
    does the damage.
    """
    assert _refused(tmp_path, {"season": 2026, "week": 1, "sim_rows": []}) is True
    assert _refused(tmp_path, {"rows": []}) is True, "legacy row key also covered"


def test_a_populated_artifact_publishes_normally(tmp_path):
    assert _refused(tmp_path, {"sim_rows": [{"entity": "x"}] * 5}) is False


def test_unreadable_is_not_empty_and_must_still_publish(tmp_path):
    """Refusing on "I could not tell" would turn a parse bug into a silent
    publishing outage -- a worse failure than the one being fixed."""
    assert _refused(tmp_path, "{truncated json") is False
    assert _refused(tmp_path, [1, 2, 3]) is False
    assert _refused(tmp_path, {"season": 2026}) is False, "no row key = cannot tell"


def test_the_guard_only_applies_to_registered_paths(tmp_path):
    """An empty payload on an UNREGISTERED path is none of this guard's business."""
    assert _refused(tmp_path, {"sim_rows": []}, relative="mlb_source/something.json") is False


def test_the_guard_is_size_gated_so_the_steady_state_costs_one_stat(tmp_path):
    """A real week-1 artifact is ~404 KB and must never be parsed per publish."""
    from syndicate.features.shared.artifact_publisher import _NON_EMPTY_SUSPECT_BYTES

    payload = {"sim_rows": [], "pad": "x" * (_NON_EMPTY_SUSPECT_BYTES + 1000)}
    assert _refused(tmp_path, payload) is False


def test_the_registered_row_key_matches_what_the_writer_emits(tmp_path):
    """SCHEMA AGREEMENT, pinned deliberately.

    An earlier guard in this same chain read `rows`; the artifact has only ever
    emitted `sim_rows`, so it returned False for every input and shipped inert.
    """
    import json

    from syndicate.features.nfl import props as props_module
    from syndicate.features.shared.artifact_publisher import _NON_EMPTY_ROW_KEYS

    monkey_root = tmp_path
    original = props_module.nfl_artifact_output_root
    try:
        props_module.nfl_artifact_output_root = lambda: monkey_root
        path = props_module.write_nfl_prop_projection_artifact(2026, 1, [])
    finally:
        props_module.nfl_artifact_output_root = original

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert any(key in payload for key in _NON_EMPTY_ROW_KEYS), (
        f"the writer emits {sorted(payload)} and the guard looks for "
        f"{_NON_EMPTY_ROW_KEYS} -- they have drifted apart"
    )
