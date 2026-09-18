# -*- coding: utf-8 -*-
"""scripts/soccer_season_audit/live_corners_book_grade.py -- H36's grader (forward, paper).

End to end first: a harvest, an ESPN final and an in-play book capture must come out scored, with the funnel
naming every stage. Then the two rules that decide whether the comparison is fair: the projection row is the
one in force when the BOOK last updated (never a later one), and the join is by the platform's canonical team
name (amended before any evidence), with the live pricer's own exact key kept beside it for the report.
"""
import collections
import datetime as dt
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "soccer_season_audit"))

import live_corners_book_grade as g  # noqa: E402
import live_corners_dispersion_study as h35  # noqa: E402

TODAY = dt.date(2026, 9, 20)
KO = "2026-09-19T14:00:00Z"


def _hist(generated_at, projected, sim=11.0, home_so_far=3, away_so_far=1, event="e1", league="epl"):
    return {"league": league, "event_id": event, "source": "projection_history", "generated_at": generated_at,
            "half": 1, "clock_remaining": 300.0, "corners_basis": g.LIVE_BASIS, "projected_total_corners": projected,
            "sim_projected_total_corners": sim, "home_corners_so_far": home_so_far, "away_corners_so_far": away_so_far}


def _quote(line, side, price, captured="2026-09-19T14:40:00Z", updated="2026-09-19T14:38:30Z", book="draftkings",
           home="Arsenal", away="Chelsea", commence=KO, league="epl", event="odds1"):
    return {"captured_at": captured, "book_updated_at": updated, "commence_time": commence, "event_id": event,
            "home_team": home, "away_team": away, "league": league, "bookmaker": book, "market": g.MARKET,
            "selection": side, "line": line, "price": price, "kind": "game", "sport": "soccer"}


def _espn(home="Arsenal", away="Chelsea", home_corners=6, away_corners=4, date=KO, completed=True):
    return {
        "header": {"competitions": [{
            "date": date,
            "status": {"type": {"name": "STATUS_FULL_TIME" if completed else "STATUS_IN_PROGRESS", "completed": completed}},
            "competitors": [{"homeAway": "home", "score": "1", "team": {"id": "1", "displayName": home}},
                            {"homeAway": "away", "score": "0", "team": {"id": "2", "displayName": away}}]}]},
        "boxscore": {"teams": [
            {"team": {"id": "1"}, "statistics": [{"name": "wonCorners", "displayValue": str(home_corners)}]},
            {"team": {"id": "2"}, "statistics": [{"name": "wonCorners", "displayValue": str(away_corners)}]}]},
        "rosters": [],
    }


def _write(tmp_path, harvest_rows, quotes, summaries):
    harvest, cache = tmp_path / "harvest", tmp_path / "cache"
    harvest.mkdir()
    (cache / "espn").mkdir(parents=True)
    (cache / "book_quotes").mkdir()
    with open(harvest / "live_projections_2026-09-19.jsonl", "w", encoding="utf-8") as fh:
        fh.writelines(json.dumps(r) + "\n" for r in harvest_rows)
    with open(cache / "book_quotes" / "2026-09-19.jsonl", "w", encoding="utf-8") as fh:
        fh.writelines(json.dumps(r) + "\n" for r in quotes)
    for (league, event), summary in summaries.items():
        (cache / "espn" / f"{league}__{event}.json").write_text(json.dumps(summary), encoding="utf-8")
    return harvest, cache


def _two_sided(line, over, under, **kw):
    return [_quote(line, "over", over, **kw), _quote(line, "under", under, **kw)]


# ---------------------------------------------------------------------------- end to end first

def test_a_capture_joined_to_the_history_and_a_final_is_scored_through_every_stage(tmp_path):
    rows = [_hist("2026-09-19T14:37:00+00:00", 9.0),               # in force at the book's 14:38:30 update
            _hist("2026-09-19T14:39:00+00:00", 12.0)]              # later: must never be used
    quotes = _two_sided(9.5, -110, -110) + _two_sided(10.5, 150, -190)
    harvest, cache = _write(tmp_path, rows, quotes, {("epl", "e1"): _espn()})
    report = g.grade(harvest, cache, TODAY)
    assert report["funnel"]["in_play_groups"] == 2 and report["funnel"]["two_sided"] == 2
    assert report["funnel"]["scored"] == 2
    assert report["matches"] == 1 and report["items"] == 2
    assert report["verdict"] == "WATCHING"
    assert report["matches_per_week"] == {"2026-W38": 1}


def test_scored_items_use_the_row_in_force_and_h35s_poisson():
    funnel = collections.Counter()
    items = g.quote_items(_two_sided(9.5, -110, -110), funnel)
    history = {("epl", "e1"): [_hist("2026-09-19T14:37:00+00:00", 9.0), _hist("2026-09-19T14:39:00+00:00", 12.0)]}
    scored = g.score_items(items, _by_names(), {("epl", "e1"): 10.0}, history, funnel)
    assert len(scored) == 1
    s = scored[0]
    # so_far 4, published total 9.0 -> remaining mean 5; over 9.5 needs 6+ more
    assert s["ours"] == pytest.approx(h35.prob_over("p0", 5.5, 5.0, {}))
    assert s["book_p"] == pytest.approx(0.5) and s["happened"] is True


# ---------------------------------------------------------------------------- the as-of rule

def test_the_row_is_the_last_at_or_before_the_books_update_and_never_after():
    t = dt.datetime(2026, 9, 19, 14, 38, 30, tzinfo=dt.timezone.utc)
    rows = [_hist("2026-09-19T14:36:00+00:00", 1.0), _hist("2026-09-19T14:38:30+00:00", 2.0), _hist("2026-09-19T14:38:31+00:00", 3.0)]
    assert g.pick_row(rows, t)["projected_total_corners"] == 2.0


def test_a_row_more_than_180_seconds_old_is_not_used():
    t = dt.datetime(2026, 9, 19, 14, 38, 30, tzinfo=dt.timezone.utc)
    assert g.pick_row([_hist("2026-09-19T14:35:29+00:00", 1.0)], t) is None
    assert g.pick_row([_hist("2026-09-19T14:35:30+00:00", 1.0)], t) is not None


def test_a_pair_is_valid_only_from_its_later_sides_update():
    funnel = collections.Counter()
    items = g.quote_items([_quote(9.5, "over", -110, updated="2026-09-19T14:37:00Z"),
                           _quote(9.5, "under", -110, updated="2026-09-19T14:38:00Z")], funnel)
    assert items[0]["book_updated"] == dt.datetime(2026, 9, 19, 14, 38, tzinfo=dt.timezone.utc)


# ---------------------------------------------------------------------------- the join

def _by_names(n=1):
    ko = dt.datetime(2026, 9, 19, 14, tzinfo=dt.timezone.utc)
    return {("epl", "arsenal", "chelsea"): [(f"e{i}", ko, ("arsenal", "chelsea")) for i in range(1, n + 1)]}


@pytest.mark.parametrize("home,commence,espn_matches,reason,pricer_key", [
    ("  ARSENAL ", KO, 1, None, True),                              # case and spacing: both keys join
    ("Arsenal FC", KO, 1, None, False),                             # club token: canonical joins, the pricer's key would not
    ("Arsenal Londres", KO, 1, "unmatched", None),                  # a different name is never guessed
    ("Arsenal", "2026-09-19T13:15:00Z", 1, "unmatched", None),      # kickoff 45 min away (still in play at 14:40)
    ("Arsenal", KO, 2, "ambiguous", None),
])
def test_the_join_is_the_canonical_name_and_the_pricers_key_is_reported(home, commence, espn_matches, reason, pricer_key):
    funnel = collections.Counter()
    items = g.quote_items(_two_sided(9.5, -110, -110, home=home, commence=commence), funnel)
    history = {("epl", "e1"): [_hist("2026-09-19T14:37:00+00:00", 9.0)]}
    scored = g.score_items(items, _by_names(espn_matches), {("epl", "e1"): 10.0}, history, funnel)
    assert (len(scored), funnel.get(reason, 0) if reason else 0) == ((0, 1) if reason else (1, 0))
    if not reason:
        assert scored[0]["pricer_key_matches"] is pricer_key


def test_espn_summaries_are_indexed_by_canonical_name(tmp_path):
    from syndicate.features.soccer.features.team_names import canonical_team_name

    harvest, cache = _write(tmp_path, [], [], {("ligue_1", "e9"): _espn(home="Le Havre AC", away="Paris Saint-Germain")})
    by_names, finals = g.espn_matches(cache)
    (key, entries), = by_names.items()
    assert key[0] == "ligue_1" and entries[0][0] == "e9" and entries[0][2] == ("le havre ac", "paris saint-germain")
    assert key[1:] == (canonical_team_name("Le Havre"), canonical_team_name("Paris Saint Germain"))
    assert finals == {("ligue_1", "e9"): 10.0}


# ---------------------------------------------------------------------------- filters

def _score_one(quotes, final=10.0, history_row=None):
    funnel = collections.Counter()
    items = g.quote_items(quotes, funnel)
    history = {("epl", "e1"): [history_row or _hist("2026-09-19T14:37:00+00:00", 9.0)]}
    return g.score_items(items, _by_names(), {("epl", "e1"): final}, history, funnel), funnel


@pytest.mark.parametrize("quotes,final,row,stage", [
    ([_quote(9.5, "over", -110)], 10.0, None, "one_sided"),
    (_two_sided(3.5, -110, -110), 10.0, None, "line_already_settled"),                  # 4 taken already
    (_two_sided(9.5, -5000, 2000), 10.0, None, "book_p_out_of_range"),                  # de-vigged 0.954
    (_two_sided(10.0, -110, -110), 10.0, None, "push"),
    (_two_sided(9.5, -110, -110), 10.0, dict(_hist("2026-09-19T14:37:00+00:00", 9.0), corners_basis="sim"), "row_not_on_live_basis"),
])
def test_each_filter_is_counted(quotes, final, row, stage):
    scored, funnel = _score_one(quotes, final, row)
    assert scored == [] and funnel[stage] == 1


def test_a_quote_captured_before_kickoff_is_not_in_play():
    scored, funnel = _score_one(_two_sided(9.5, -110, -110, captured="2026-09-19T13:59:00Z"))
    assert scored == [] and funnel["in_play_groups"] == 0


def test_a_match_without_a_final_is_not_scored():
    funnel = collections.Counter()
    items = g.quote_items(_two_sided(9.5, -110, -110), funnel)
    assert g.score_items(items, _by_names(), {}, {("epl", "e1"): [_hist("2026-09-19T14:37:00+00:00", 9.0)]}, funnel) == []
    assert funnel["no_final"] == 1


# ---------------------------------------------------------------------------- prices, verdict, paper ROI

def test_devig_is_proportional():
    assert g.devig_over(-110, -110) == pytest.approx(0.5)
    assert g.devig_over(150, -190) == pytest.approx(0.4 / (0.4 + 190 / 290))
    assert g.devig_over(50, -110) is None                      # not an American price: refused, not coerced


def test_settle_and_paper_roi_take_the_side_with_the_edge():
    assert g.settle(150, True) == pytest.approx(1.5) and g.settle(-110, True) == pytest.approx(100 / 110)
    assert g.settle(-110, False) == -1.0
    scored = [{"ours": 0.60, "book_p": 0.50, "happened": True, "over": 100, "under": -120},    # over, wins +1
              {"ours": 0.40, "book_p": 0.50, "happened": True, "over": -120, "under": 100},    # under, loses
              {"ours": 0.51, "book_p": 0.50, "happened": False, "over": 100, "under": -120}]   # below 0.03: no bet
    roi = g.paper_roi(scored, 0.03)
    assert roi["bets"] == 2 and roi["profit"] == pytest.approx(0.0)


@pytest.mark.parametrize("n,hi,today,expected", [
    (149, -0.5, dt.date(2026, 11, 14), "WATCHING"),
    (149, -0.5, dt.date(2026, 11, 15), "INSUFFICIENT"),
    (150, -0.001, dt.date(2026, 10, 1), "SUPPORTED"),
    (150, 0.0, dt.date(2026, 10, 1), "FALSIFIED"),
    (150, float("nan"), dt.date(2026, 10, 1), "FALSIFIED"),
])
def test_verdict(n, hi, today, expected):
    assert g.verdict(n, hi, today) == expected
