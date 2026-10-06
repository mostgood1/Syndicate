"""rescore_live_gameline_date.py: the NCAAF finals adapter.

NCAAF has no StatsAPI equivalent and its ledger rows carry `game_pk: None`, so its
finals index is keyed by `event_id` and built by joining the ledger's team names to
ESPN's FBS scoreboard. The load-bearing properties are that an unmatched game is
NAMED rather than silently dropped, that only an unmatched game carrying a scoreable
h2h row can shrink the measurement, and that the MLB path is untouched.

Every test here is offline: `urllib.request.urlopen` is replaced with a fixture.
"""
from __future__ import annotations

import importlib.util
import io
import json
import pathlib

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "rescore_live_gameline_date", _ROOT / "scripts/rescore_live_gameline_date.py")
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


def _espn(games):
    """games: list of (home, away, home_score, away_score, state)."""
    events = []
    for home, away, hs, as_, state in games:
        events.append({"competitions": [{
            "status": {"type": {"state": state}},
            "competitors": [
                {"homeAway": "home", "score": hs, "team": {"displayName": home}},
                {"homeAway": "away", "score": as_, "team": {"displayName": away}},
            ],
        }]})
    return {"events": events}


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture
def espn(monkeypatch):
    """Serve a canned ESPN payload; returns a setter the test calls."""
    holder: dict = {}

    def fake_urlopen(url, *a, **k):
        holder["url"] = url if isinstance(url, str) else getattr(url, "full_url", "")
        return _Resp(json.dumps(holder["payload"]).encode("utf-8"))

    monkeypatch.setattr(mod.urllib.request, "urlopen", fake_urlopen)
    return holder


def _h2h(event_id, home, away, *, scoreable=True):
    rec = {"event_id": event_id, "home_team": home, "away_team": away,
           "market": "h2h", "segment": "full", "sport": "ncaaf", "game_pk": None}
    if scoreable:
        rec["model_home_win_prob"] = 0.6
        rec["market_fair_prob"] = 0.55
    else:
        rec["model_home_win_prob"] = None
        rec["market_fair_prob"] = None
    return rec


def test_a_final_game_joins_and_a_non_final_one_is_ignored(espn):
    espn["payload"] = _espn([
        ("Georgia Bulldogs", "Vanderbilt Commodores", "38", "14", "post"),
        ("Clemson Tigers", "Miami Hurricanes", "13", "41", "in"),       # still playing
    ])
    records = [_h2h("ev-final", "Georgia Bulldogs", "Vanderbilt Commodores"),
               _h2h("ev-live", "Clemson Tigers", "Miami Hurricanes")]
    scores, join = mod._final_scores_ncaaf("2026-10-03", records)
    assert join["espn_finals"] == 1, "a game still in play is not a final"
    assert scores == {"ev-final": (14.0, 38.0)}, "(away, home) order"
    assert join["unmatched"] and "Miami Hurricanes @ Clemson Tigers" in join["unmatched"][0]
    # the CONTROL for the whole suite: the home-won view the scorer consumes
    assert mod.finals_from_scores(scores) == {"ev-final": True}


def test_the_date_is_sent_to_espn_in_compact_form(espn):
    espn["payload"] = _espn([("A Team", "B Team", "1", "0", "post")])
    mod._final_scores_ncaaf("2026-10-03", [_h2h("e", "A Team", "B Team")])
    assert "dates=20261003" in espn["url"], espn["url"]
    assert "groups=80" in espn["url"], "FBS group, or an FCS-heavy slate floods the join"


def test_punctuation_and_case_do_not_break_the_join(espn):
    espn["payload"] = _espn([("Texas A&M Aggies", "Hawai'i Rainbow Warriors", "21", "17", "post")])
    records = [_h2h("ev", "texas a & m aggies", "HAWAII   RAINBOW WARRIORS")]
    scores, join = mod._final_scores_ncaaf("2026-10-03", records)
    assert join["matched"] == 1 and scores["ev"] == (17.0, 21.0)


def test_an_orientation_flip_is_matched_and_reported_with_the_scores_swapped(espn):
    """The feed lists OUR home side as its away side. The game must still join, the
    scores must come back oriented to the LEDGER's home/away, and the flip must be
    reported -- a silent flip would invert the outcome for that game."""
    espn["payload"] = _espn([("Iowa Hawkeyes", "Ohio State Buckeyes", "14", "31", "post")])
    records = [_h2h("ev", "Ohio State Buckeyes", "Iowa Hawkeyes")]   # opposite orientation
    scores, join = mod._final_scores_ncaaf("2026-10-03", records)
    assert join["orientation_flipped"] == ["Iowa Hawkeyes @ Ohio State Buckeyes"]
    assert scores["ev"] == (14.0, 31.0), "away=Iowa 14, home=Ohio State 31 as the LEDGER orients it"
    assert mod.finals_from_scores(scores) == {"ev": True}, "Ohio State (our home) won"


def test_an_unmatched_game_WITH_a_scoreable_row_is_flagged_as_shrinking_the_measurement(espn):
    espn["payload"] = _espn([("Georgia Bulldogs", "Vanderbilt Commodores", "38", "14", "post")])
    records = [_h2h("ev-ok", "Georgia Bulldogs", "Vanderbilt Commodores"),
               _h2h("ev-miss", "LSU Tigers", "McNeese State Cowboys")]
    scores, join = mod._final_scores_ncaaf("2026-10-03", records)
    assert join["matched"] == 1
    assert join["unmatched_scoreable"] == ["McNeese State Cowboys @ LSU Tigers"]
    assert "SCOREABLE" in join["unmatched"][0]


def test_an_unmatched_game_WITHOUT_a_scoreable_row_does_not_shrink_the_measurement(espn):
    """Measured on 2026-10-03: 3 of 54 games went unmatched and none was scoreable,
    which is why the --expect-* gate still reproduced the retained figures exactly.
    The warning has to distinguish these two cases or it cries wolf on every date."""
    espn["payload"] = _espn([("Georgia Bulldogs", "Vanderbilt Commodores", "38", "14", "post")])
    records = [_h2h("ev-ok", "Georgia Bulldogs", "Vanderbilt Commodores"),
               _h2h("ev-miss", "UMass Minutemen", "Eastern Michigan Eagles", scoreable=False)]
    scores, join = mod._final_scores_ncaaf("2026-10-03", records)
    assert join["unmatched_scoreable"] == [], "no scoreable row, so the h2h measurement is intact"
    assert "no scoreable h2h row" in join["unmatched"][0]
    assert join["scoreable_games"] == 1


def test_a_game_with_no_numeric_score_is_not_treated_as_a_final(espn):
    espn["payload"] = _espn([("A Team", "B Team", None, None, "post")])
    scores, join = mod._final_scores_ncaaf("2026-10-03", [_h2h("e", "A Team", "B Team")])
    assert join["espn_finals"] == 0 and scores == {}


def test_the_ledger_path_is_sport_scoped_and_mlb_is_unchanged():
    """The MLB path must keep its exact pre-change artifact path, and ncaaf must not
    reach into mlb_source. A sport-blind path was a real cross-sport mix-up: a cached
    ncaaf ledger was scored under --sport mlb (2026-10-06)."""
    assert mod.LEDGER_PATH.format(sport="mlb", date="2026-10-03") == \
        "mlb_source/data/live_gameline_ledger/live_gameline_ledger_2026-10-03.jsonl"
    assert mod.LEDGER_PATH.format(sport="ncaaf", date="2026-10-03") == \
        "ncaaf_source/data/live_gameline_ledger/live_gameline_ledger_2026-10-03.jsonl"


def test_only_wired_sports_are_accepted():
    # The PROPERTY, not the literal tuple: pinning the exact tuple made this test
    # fail when soccer was legitimately wired, which is a brittle assertion about
    # a list that is expected to grow rather than a fact worth defending.
    assert "mlb" in mod.WIRED_SPORTS and "ncaaf" in mod.WIRED_SPORTS
    rc = mod.main(["--date", "2026-10-03", "--sport", "nhl"])
    assert rc == 2, "an unwired sport must refuse, not fetch a path that does not exist"


def test_mlb_finals_still_come_from_statsapi_keyed_by_game_pk(monkeypatch):
    """off != on for the sport switch: the mlb provider is untouched and keys by
    game_pk, which is what makes the ncaaf event_id keying a separate path rather
    than a change to the existing one."""
    sched = {"dates": [{"games": [
        {"gamePk": 777, "status": {"abstractGameState": "Final"},
         "teams": {"away": {"score": 2}, "home": {"score": 5}}},
        {"gamePk": 888, "status": {"abstractGameState": "Live"},
         "teams": {"away": {"score": 1}, "home": {"score": 1}}},
    ]}]}
    monkeypatch.setattr(mod.urllib.request, "urlopen",
                        lambda *a, **k: _Resp(json.dumps(sched).encode("utf-8")))
    scores = mod._final_scores("2026-10-03")
    assert scores == {"777": (2.0, 5.0)}, "final only, keyed by game_pk, (away, home)"


def test_a_diacritic_and_an_apostrophe_are_canonicalised(espn):
    """Measured 2026-10-06: ESPN writes `San José State Spartans` and `Hawai'i Rainbow
    Warriors` where the odds feed writes the plain ASCII forms. Folding these lifted the
    2026-10-03 join from 51 to 52 matched games. The apostrophe must be DROPPED, not
    spaced -- spacing gives `hawai i`, which matches nothing."""
    espn["payload"] = _espn([("Hawai'i Rainbow Warriors", "San José State Spartans",
                              "24", "20", "post")])
    records = [_h2h("ev", "Hawaii Rainbow Warriors", "San Jose State Spartans")]
    scores, join = mod._final_scores_ncaaf("2026-10-03", records)
    assert join["matched"] == 1, join
    assert scores["ev"] == (20.0, 24.0)
    assert mod._norm_team("Hawai\u2019i") == "hawaii", "the curly apostrophe too"


def test_a_DIFFERENT_name_for_one_team_is_reported_rather_than_guessed(espn):
    """The designed limitation, pinned so nobody replaces it with fuzzy matching without
    deciding to. `McNeese State` vs `McNeese` and `UMass` vs `Massachusetts` are the two
    real 2026-10-03 cases: different strings for one team, which this join reports as a
    miss and pairs with the unused ESPN final so the operator can see why."""
    espn["payload"] = _espn([("LSU Tigers", "McNeese Cowboys", "41", "7", "post"),
                             ("Massachusetts Minutemen", "Eastern Michigan Eagles", "17", "24", "post")])
    records = [_h2h("ev1", "LSU Tigers", "McNeese State Cowboys", scoreable=False),
               _h2h("ev2", "UMass Minutemen", "Eastern Michigan Eagles", scoreable=False)]
    scores, join = mod._final_scores_ncaaf("2026-10-03", records)
    assert scores == {} and join["matched"] == 0
    assert join["unmatched_scoreable"] == [], "neither carries a scoreable row"
    unused = " | ".join(join["espn_unused"])
    assert "mcneese cowboys" in unused and "massachusetts minutemen" in unused, \
        "the ESPN side of a miss must be printed so the pair is diagnosable"


# --- the exclusion flags on the NCAAF path -----------------------------------
# Both filter/search the finals dict BY ITS OWN KEYS, which the adapter makes
# `event_id`s for this sport. Proven live on 2026-10-03 first: an explicit
# --exclude-game-pk took scored_games 49 -> 48 and n 2472 -> 2447 and FAILED the
# 49-game gate (exit 4), then --search-exclusions searched 52 finals and recovered
# that same event_id as the UNIQUE match (exit 0). These pin it offline.

def _mini_ledger(tmp_path, rows):
    p = tmp_path / "ledger.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return str(p)


def _two_game_fixture(espn):
    espn["payload"] = _espn([
        ("Georgia Bulldogs", "Vanderbilt Commodores", "38", "14", "post"),
        ("Clemson Tigers", "Miami Hurricanes", "13", "41", "post"),
    ])
    rows = []
    for ev, home, away, mp in (("ev-a", "Georgia Bulldogs", "Vanderbilt Commodores", 0.7),
                               ("ev-b", "Clemson Tigers", "Miami Hurricanes", 0.6)):
        for q in (10.0, 30.0):
            rec = _h2h(ev, home, away)
            rec["model_home_win_prob"] = mp
            rec["market_fair_prob"] = 0.5
            rec["quote_age_seconds"] = q
            rows.append(rec)
    return rows


def test_exclude_game_pk_accepts_an_event_id_on_the_ncaaf_path(espn, tmp_path, capsys):
    rows = _two_game_fixture(espn)
    ledger = _mini_ledger(tmp_path, rows)
    rc = mod.main(["--sport", "ncaaf", "--date", "2026-10-03", "--ledger", ledger,
                   "--exclude-game-pk", "ev-b"])
    out = capsys.readouterr().out
    assert "excluded=['ev-b']" in out, out
    assert "scored_games=1" in out, "excluding one of two games must drop the count"
    # exit 3 is DOCUMENTED: "no expectation given (refuses to append blind)". The
    # exclusion is what this test is about and it took effect above; the tool
    # declining to bless an unanchored re-score is correct, not a failure.
    assert rc == 3, "an unanchored run must refuse rather than look successful"


def test_an_exclusion_that_is_not_a_final_is_reported_as_having_no_effect(espn, tmp_path, capsys):
    rows = _two_game_fixture(espn)
    ledger = _mini_ledger(tmp_path, rows)
    mod.main(["--sport", "ncaaf", "--date", "2026-10-03", "--ledger", ledger,
              "--exclude-game-pk", "ev-does-not-exist"])
    out = capsys.readouterr().out
    assert "not among" in out and "no effect" in out, out
    assert "scored_games=2" in out, "a bogus exclusion must not silently shrink the population"


def test_search_exclusions_recovers_the_one_excluded_event_uniquely(espn, tmp_path, capsys):
    """Give the tool the figures that arise from excluding ev-b and NO explicit
    exclusion; it must search the finals and land on ev-b alone. A search returning
    0 or >1 is refused upstream -- picking one of several would be a guess."""
    rows = _two_game_fixture(espn)
    ledger = _mini_ledger(tmp_path, rows)
    # derive the one-game expectation with the module's own scorer, so the test pins
    # the FLAG plumbing rather than restating the scorer's arithmetic
    one = {"ev-a": (14.0, 38.0)}
    target = mod.score_ledger_records(rows, mod.finals_from_scores(one), final_scores=one)
    allr = target["all_records"]
    rc = mod.main(["--sport", "ncaaf", "--date", "2026-10-03", "--ledger", ledger,
                   "--search-exclusions",
                   "--expect-model", str(allr["model"]["brier"]),
                   "--expect-market", str(allr["market"]["brier"]),
                   "--expect-n", f"{allr['model']['n']}/{allr['market']['n']}"])
    out = capsys.readouterr().out
    assert "1 exact match(es) ['ev-b']" in out, out
    assert rc == 0, "the gate must pass once the search has found the population"
