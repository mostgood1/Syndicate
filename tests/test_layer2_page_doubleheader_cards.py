"""Layer 2 page rail: each half of a doubleheader is its own card, on its own chip.

MEASURED ON PRODUCTION 2026-09-22 -- TB @ NYY split doubleheader:

    G1  gamePk 823543  chip start 17:05Z  "12:05P CT"   OddsAPI event 394e1e2b.. commence 17:06Z
    G2  gamePk 823494  chip start 23:05Z  "6:05P CT"    OddsAPI event 574050c1.. commence 23:06Z

The page rendered ONE TB @ NYY card holding both games' opportunities, plus an
empty card for G1's unclaimed chip. Three steps in `intelligence.html` did it:
the exact matchup index was `Map.set` (last chip wins, so both halves' rows
joined G2's chip); a Layer 2 row's id (OddsAPI hash) never hits the chip id
index (gamePk); and the merge pass folded every group sharing a chip and text.

WHY NODE FROM PYTEST. The functions live inside the page's IIFE, so they are
not importable; the harnesses in `tests/js/` slice them out of the template and
run them under node, and this does the same. Unlike those harnesses it runs the
REAL `loadGameChips` (with `fetch` stubbed) instead of seeding the chip indexes
by hand -- the defect is IN how that function builds the exact index, and a
hand-seeded index cannot express it.

A/B against another template (e.g. the pre-change one):
    SYNDICATE_TEMPLATE_HTML=<path> python -m pytest tests/test_layer2_page_doubleheader_cards.py
Only the 8-character event-id prefixes are production values; the rest of each
id is padding.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

TEMPLATE = Path(__file__).resolve().parents[1] / "syndicate" / "templates" / "intelligence.html"
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed")

G1_EVENT = "394e1e2b00000000000000000000aaaa"
G2_EVENT = "574050c100000000000000000000bbbb"

HARNESS = r"""
import fs from 'fs';
const html = fs.readFileSync(process.argv[2], 'utf8').split('\r\n').join('\n');
function slice(a, b) {
  const i = html.indexOf(a), j = html.indexOf(b, i + 1);
  if (i < 0 || j < 0 || j <= i) throw new Error(`slice ${a} .. ${b} not found`);
  return html.slice(i, j);
}
const src = [
  slice('let gameChipsById = new Map();', "// The chip-less card's matchup, shortened."),
  slice('function chipForGame', 'function chipTeamRow'),
  slice('function displayMatchup', 'function gameKey'),
  slice('function gameKey', '// A whole-numbered line must keep its decimal'),
  slice('function deriveGameCards', 'function renderGameCards'),
].join('\n');

let payload = { chips: [] };
const state = { sport: 'all', date: '2026-09-22' };
const fetchStub = async () => ({ ok: true, json: async () => payload });
const recommendationState = (item) => item.market_state || 'pregame';
const built = new Function('state', 'fetch', 'renderBoardBody', 'recommendationState',
  src + `; return {
    loadGameChips, deriveGameCards, chipForGame, gameKey,
    indexes: () => ({ byId: gameChipsById, byMatchup: gameChipsByMatchup }),
    mergeMap: () => gameKeyMergeMap,
  };`)(state, fetchStub, () => {}, recommendationState);

const G1_EVENT = '__G1__', G2_EVENT = '__G2__';
const side = (abbr, name) => ({ abbr, name, key: name.toLowerCase(), score: null });
const chip = (gameKey, start, token, away = side('TB', 'Tampa Bay Rays'), home = side('NYY', 'New York Yankees'), state = 'pregame') => ({
  sport: 'mlb', league: null, league_display: null, game_key: gameKey,
  matchup: `${away.abbr} @ ${home.abbr}`, away, home, state, status_token: token,
  score_suppressed: null, leader: null, start_time_utc: start,
});
// The IN-PLAY shape, measured off production 2026-09-25 20:33Z: a traditional
// doubleheader's halves start five minutes apart, and the surviving odds group
// carries a commence_time ~3 HOURS from BOTH of them. That spacing is the whole
// point -- it is what makes the clock unable to answer, so a test built on the
// ordinary 17:05/23:05 pair would pass with the state branch inert.
const LIVE_G1 = (state = 'live') =>
  chip('823543', '2026-09-25T20:05:00+00:00', 'BOT 4', undefined, undefined, state);
const LIVE_G2 = (state = 'pregame') =>
  chip('823494', '2026-09-25T20:10:00+00:00', '3:10P CT', undefined, undefined, state);
const LATE_GROUP = '2026-09-25T23:05:00Z';
const G1 = () => chip('823543', '2026-09-22T17:05:00+00:00', '12:05P CT');
const G2 = () => chip('823494', '2026-09-22T23:05:00+00:00', '6:05P CT');
// The board-card shape `layer2_rows_to_board_cards` emits for an MLB row.
const row = (eventId, extra = {}) => ({
  sport: 'mlb', sport_slug: 'mlb', event_id: eventId, game_pk: eventId, source: 'layer2_shortlist',
  matchup: 'Tampa Bay Rays @ New York Yankees', away_team: 'Tampa Bay Rays', home_team: 'New York Yankees',
  away_key: 'tampa bay rays', home_key: 'new york yankees', market_state: 'pregame', ...extra,
});
const g1Rows = (extra) => [row(G1_EVENT, extra), row(G1_EVENT, extra), row(G1_EVENT, extra)];
const g2Rows = (extra) => [row(G2_EVENT, extra), row(G2_EVENT, extra)];
const withCommence = (start) => ({ commence_time: start });
const withGameKey = (key) => ({ game: { game_key: key } });

// The group `deriveGameCards` would seat for a row, resolved on its own --
// what each half joins BEFORE any merge.
function groupChip(r) {
  const game = r.game && typeof r.game === 'object' ? r.game : null;
  const group = {
    key: built.gameKey(r), sportSlug: 'mlb', sport: 'MLB', matchup: r.matchup,
    awayKey: r.away_key, homeKey: r.home_key,
    ownGameKey: (game && game.game_key) || null,
    commenceTime: r.commence_time || (game && game.start_time_utc) || null,
  };
  const c = built.chipForGame(group);
  return c ? c.game_key : null;
}

async function scenario(chips, rows) {
  payload = { chips };
  await built.loadGameChips();
  const idx = built.indexes();
  const cards = built.deriveGameCards(rows).map((card) => {
    const c = built.chipForGame(card);
    return { key: card.key, matchup: card.matchup, count: card.count, chip: c ? c.game_key : null };
  });
  const merge = built.mergeMap();
  return {
    chips_indexed_by_id: idx.byId.size,
    cards,
    merged_to: Object.fromEntries(rows.map((r) => [built.gameKey(r), merge.get(built.gameKey(r)) || built.gameKey(r)])),
    row_chip: Object.fromEntries(rows.map((r) => [built.gameKey(r), groupChip(r)])),
  };
}

const out = {};
out.by_commence_time = await scenario([G1(), G2()], [...g1Rows(withCommence('2026-09-22T17:06:00Z')), ...g2Rows(withCommence('2026-09-22T23:06:00Z'))]);
{
  const exact = built.indexes().byMatchup;
  const size = (k) => { const v = exact.get(k); return Array.isArray(v) ? v.length : (v ? 1 : 0); };
  out.exact_index = { abbr: size('mlb|tb @ nyy'), full_name: size('mlb|tampa bay rays @ new york yankees') };
}
out.by_game_key = await scenario([G1(), G2()], [...g1Rows(withGameKey('823543')), ...g2Rows(withGameKey('823494'))]);
out.no_discriminator = await scenario([G1(), G2()], [...g1Rows(), ...g2Rows()]);
out.g2_has_no_rows = await scenario([G1(), G2()], [...g1Rows(withCommence('2026-09-22T17:06:00Z'))]);
out.one_chip_missing = await scenario([G2()], [...g1Rows(withCommence('2026-09-22T17:06:00Z')), ...g2Rows(withCommence('2026-09-22T23:06:00Z'))]);
out.no_chips = await scenario([], [...g1Rows(withCommence('2026-09-22T17:06:00Z')), ...g2Rows(withCommence('2026-09-22T23:06:00Z'))]);
out.no_chips_same_game_two_ids = await scenario([], [...g1Rows(withCommence('2026-09-22T17:06:00Z')), ...g2Rows(withCommence('2026-09-22T17:06:00Z'))]);
out.inseparable_starts = await scenario(
  [G1(), chip('823494', '2026-09-22T17:30:00+00:00', '12:30P CT')],
  [...g1Rows(withCommence('2026-09-22T17:06:00Z'))]);
out.single_game_pair = await scenario(
  [chip('823600', '2026-09-22T23:05:00+00:00', '6:05P CT', side('BOS', 'Boston Red Sox'), side('BAL', 'Baltimore Orioles'))],
  [{ ...row('c0ffee0000000000000000000000cccc'), matchup: 'Boston Red Sox @ Baltimore Orioles',
     away_team: 'Boston Red Sox', home_team: 'Baltimore Orioles', away_key: 'boston red sox', home_key: 'baltimore orioles',
     commence_time: '2026-09-23T23:05:00Z' }]);
out.same_game_listed_twice = await scenario([G1(), G1()], [...g1Rows()]);
// TRADITIONAL doubleheader whose two sources disagree about game 2's start by
// HOURS: StatsAPI publishes the nominal placeholder 5 min after game 1, the
// book publishes the realistic one. Measured on production 2026-09-25,
// BAL @ NYY: chips 20:05Z / 20:10Z against row groups 20:05Z / 23:06Z.
out.ordinal_pairing = await scenario(
  [chip('823491', '2026-09-25T20:05:00+00:00', '3:05P CT'),
   chip('823489', '2026-09-25T20:10:00+00:00', '3:10P CT')],
  [...g1Rows(withCommence('2026-09-25T20:05:00Z')),
   ...g2Rows(withCommence('2026-09-25T23:06:00Z'))]);
// CONTROL: one half only. Counts differ, so ordinal pairing must NOT fire --
// otherwise a lone game would be handed whichever chip sorted first.
out.ordinal_refused_when_counts_differ = await scenario(
  [chip('823491', '2026-09-25T20:05:00+00:00', '3:05P CT'),
   chip('823489', '2026-09-25T20:10:00+00:00', '3:10P CT')],
  [...g2Rows(withCommence('2026-09-25T23:06:00Z'))]);
// IN PLAY: game 1 is under way and has lost its odds group, so ONE group faces
// TWO chips and the counts can never match. The chips' own `state` separates
// them; the clock cannot, since the group sits ~3h from both.
out.inplay_live_half_has_no_group = await scenario(
  [LIVE_G1(), LIVE_G2()], [...g2Rows(withCommence(LATE_GROUP))]);
// The split-doubleheader shape of the same thing: game 1 FINAL rather than live.
out.inplay_final_half_has_no_group = await scenario(
  [LIVE_G1('final'), LIVE_G2()], [...g2Rows(withCommence(LATE_GROUP))]);
// CONTROL: a chip with no state must REFUSE, not drop out of the pregame set
// and make the counts match by omission.
out.inplay_refused_when_a_state_is_missing = await scenario(
  [LIVE_G1(''), LIVE_G2()], [...g2Rows(withCommence(LATE_GROUP))]);
// CONTROL: two halves still to come. Both chips are pregame, so the pregame
// set is 2 against 1 group -- ambiguous, and refused.
out.inplay_refused_when_both_halves_pregame = await scenario(
  [LIVE_G1('pregame'), LIVE_G2()], [...g2Rows(withCommence(LATE_GROUP))]);
// TIMELESS GROUP: once a half is under way its odds group arrives with NO
// commence_time, only a date label -- measured 21:34Z. It cannot be ordered,
// so it is placed by matching its own live/final state to exactly one chip.
const untimedLive = () => ({ game_date: '2026-09-25', market_state: 'live' });
out.untimed_live_group_joins_the_live_chip = await scenario(
  [LIVE_G1(), LIVE_G2()],
  [...g1Rows(untimedLive()), ...g2Rows(withCommence(LATE_GROUP))]);
// CONTROL: no date means no bucket. Without an anchor the group could be
// paired across two different days' meetings of the same clubs.
out.untimed_group_without_a_date_is_refused = await scenario(
  [LIVE_G1(), LIVE_G2()],
  [...g1Rows({ market_state: 'live' }), ...g2Rows(withCommence(LATE_GROUP))]);
// CONTROL: two chips in the SAME state name no winner. A wrong merge here
// hides a game, so ambiguity must refuse.
out.untimed_group_refused_when_two_chips_share_its_state = await scenario(
  [LIVE_G1('live'), LIVE_G2('live')],
  [...g1Rows(untimedLive()), ...g2Rows(withCommence(LATE_GROUP))]);
// THE MEASURED PRODUCTION SHAPE, 2026-09-25 22:39Z: the timeless group's rows
// say `pregame` while its game is in the top of the 9th. The first version of
// the pass read that field and could never fire.
const untimedButStale = () => ({ game_date: '2026-09-25', market_state: 'pregame' });
out.untimed_group_with_a_stale_state_still_pairs = await scenario(
  [LIVE_G1(), LIVE_G2()],
  [...g1Rows(untimedButStale()), ...g2Rows(withCommence(LATE_GROUP))]);
// CONTROL: two timeless groups leave nothing forced -- elimination needs
// exactly one on each side.
out.two_untimed_groups_are_refused = await scenario(
  [LIVE_G1(), LIVE_G2()],
  [...g1Rows(untimedButStale()), ...g2Rows(untimedButStale())]);
console.log(JSON.stringify(out));
"""


@pytest.fixture(scope="module")
def observed(tmp_path_factory: pytest.TempPathFactory) -> dict:
    script = tmp_path_factory.mktemp("doubleheader_cards") / "harness.mjs"
    script.write_text(HARNESS.replace("__G1__", G1_EVENT).replace("__G2__", G2_EVENT), encoding="utf-8")
    template = os.environ.get("SYNDICATE_TEMPLATE_HTML") or str(TEMPLATE)
    proc = subprocess.run([NODE, str(script), template], capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _cards_by_chip(result: dict) -> dict:
    return {card["chip"]: card for card in result["cards"]}


def test_harness_ran_the_real_chip_load(observed: dict) -> None:
    # `loadGameChips` swallows every exception into its catch block, so a throw
    # inside it would leave empty indexes and every assertion below would be
    # made against a page with no chips at all. Prove the load happened.
    assert observed["by_commence_time"]["chips_indexed_by_id"] == 2


def test_exact_index_keeps_both_halves(observed: dict) -> None:
    assert observed["exact_index"] == {"abbr": 2, "full_name": 2}


@pytest.mark.parametrize("name", ["by_commence_time", "by_game_key"])
def test_each_half_joins_its_own_chip_and_card(observed: dict, name: str) -> None:
    result = observed[name]
    mlb = f"mlb|{G1_EVENT}", f"mlb|{G2_EVENT}"
    assert result["row_chip"] == {mlb[0]: "823543", mlb[1]: "823494"}
    cards = _cards_by_chip(result)
    assert len(result["cards"]) == 2, result["cards"]
    assert cards["823543"]["count"] == 3 and cards["823543"]["key"] == mlb[0]
    assert cards["823494"]["count"] == 2 and cards["823494"]["key"] == mlb[1]
    # A click on either card filters the board to that half only.
    assert result["merged_to"] == {mlb[0]: mlb[0], mlb[1]: mlb[1]}


def test_no_discriminator_attaches_no_chip(observed: dict) -> None:
    result = observed["no_discriminator"]
    assert set(result["row_chip"].values()) == {None}
    # No card that carries opportunities is wearing either half's scoreboard.
    assert all(card["chip"] is None for card in result["cards"] if card["count"])
    # The two chip-seeded cards each still show their OWN game's scoreboard.
    assert sorted(card["chip"] for card in result["cards"] if not card["count"]) == ["823494", "823543"]


def test_a_half_with_no_rows_keeps_its_own_chip(observed: dict) -> None:
    # The count-0 card seeded from G2's chip must show G2, not re-join the pair.
    result = observed["g2_has_no_rows"]
    assert sorted((card["chip"], card["count"]) for card in result["cards"]) == [("823494", 0), ("823543", 3)]


def test_halves_not_merged_when_one_chip_is_missing(observed: dict) -> None:
    result = observed["one_chip_missing"]
    assert sorted(card["count"] for card in result["cards"]) == [2, 3], result["cards"]


def test_chipless_halves_not_merged_but_same_game_still_is(observed: dict) -> None:
    assert sorted(card["count"] for card in observed["no_chips"]["cards"]) == [2, 3]
    # Two ids for ONE game (same commence time) still collapse -- #165's merge.
    assert [card["count"] for card in observed["no_chips_same_game_two_ids"]["cards"]] == [5]


def test_starts_inside_the_window_resolve_when_one_is_near_exact(observed: dict) -> None:
    """CHANGED 2026-09-25, and the old expectation was the bug.

    The fixture's row commences 17:06Z against chips at 17:05Z and 17:30Z: one
    minute from its own game and twenty-four from the other. The browser rule
    refused it anyway, because it only asked whether the winner was 45 minutes
    clearer than the runner-up.

    That blanket refusal is unreachable-by-construction for a TRADITIONAL
    doubleheader, whose halves are published five minutes apart -- BAL @ NYY
    seated four tiles for two games on 2026-09-25. `pickChipByStart` now also
    accepts a near-exact absolute match. See `DOUBLEHEADER_NEAR_EXACT_MS`.
    """
    assert set(observed["inseparable_starts"]["row_chip"].values()) == {"823543"}


def test_single_chip_pair_behaves_as_before(observed: dict) -> None:
    # One chip on the pair: it is the game, even with a commence time a day off
    # (the page keeps its own date filtering; this join does not add one).
    result = observed["single_game_pair"]
    assert list(result["row_chip"].values()) == ["823600"]
    assert [(card["chip"], card["count"]) for card in result["cards"]] == [("823600", 1)]


def test_one_game_listed_twice_is_one_candidate(observed: dict) -> None:
    result = observed["same_game_listed_twice"]
    assert set(result["row_chip"].values()) == {"823543"}
    assert [(card["chip"], card["count"]) for card in result["cards"]] == [("823543", 3)]


def test_ordinal_pairing_resolves_a_doubleheader_no_clock_can(observed: dict) -> None:
    """The BAL @ NYY case, 2026-09-25: the two sources are HOURS apart on game 2.

    StatsAPI publishes a traditional doubleheader's game 2 at a NOMINAL start
    five minutes after game 1 (there is no real second time until game 1 ends);
    the book publishes the realistic one, ~3 h later. `pickChipByStart` refuses
    -- correctly, and no time window could bridge it without guessing. ORDER is
    the discriminator both sides still agree on.
    """
    result = observed["ordinal_pairing"]
    pairs = result["row_chip"]
    assert sorted(v for v in pairs.values() if v) == ["823489", "823491"], pairs
    # game 1's rows (20:05Z) take game 1's chip, game 2's (23:06Z) take game 2's
    g1 = [k for k in pairs if k.endswith("aaaa")]
    g2 = [k for k in pairs if k.endswith("bbbb")]
    assert g1 and g2
    assert pairs[g1[0]] == "823491"
    assert pairs[g2[0]] == "823489"


def test_ordinal_pairing_is_refused_when_the_counts_differ(observed: dict) -> None:
    """CONTROL: ordinal pairing is an assumption about ORDER, not a measurement.

    One row-group against two chips cannot say which half it is, so the pairing
    must not fire -- without this the rule would hand a lone game whichever chip
    happened to sort first, which is exactly the wrong-scoreboard failure the
    whole doubleheader module exists to prevent.
    """
    result = observed["ordinal_refused_when_counts_differ"]
    assert set(result["row_chip"].values()) == {None}, result["row_chip"]


def test_a_live_half_with_no_group_lets_the_other_half_join(observed: dict) -> None:
    """THE IN-PLAY CASE, which the ordinal pass alone could not reach.

    Measured on production 2026-09-25 20:33Z on served `42b9be30`: with 823491
    `In Progress` and 823489 `Scheduled`, the payload carried ONE BAL @ NYY
    group (`3fe14d478bc1`, 23:05:00Z, 4 rows against 78-110 for every other
    fixture) and the live half had no group at all. One group against two chips
    fails the equal-counts guard, so the rail seated THREE tiles for two games:
    one for the live half, and two for the half that still had both.

    THIS IS ALSO THE REACHABILITY TEST. The group sits 2h55m from one chip and
    3h00m from the other -- five minutes apart, so `pickChipByStart` cannot
    separate them, and 2h55m is far outside `DOUBLEHEADER_NEAR_EXACT_MS`. No
    clock rule can answer here, which is why this scenario returns None with the
    state branch removed and `823494` with it in place.
    """
    pairs = observed["inplay_live_half_has_no_group"]["row_chip"]
    assert set(pairs.values()) == {"823494"}, pairs


def test_a_final_half_with_no_group_behaves_the_same(observed: dict) -> None:
    """The split-doubleheader shape: CHC @ BOS the same day, game 1 FINAL.

    `final` and `live` both mean "not pregame", so one rule covers both, and
    keying on the `pregame` value rather than enumerating the others is what
    makes that true.
    """
    pairs = observed["inplay_final_half_has_no_group"]["row_chip"]
    assert set(pairs.values()) == {"823494"}, pairs


def test_a_chip_with_no_state_refuses_rather_than_matching_by_omission(observed: dict) -> None:
    """CONTROL: an unknown state must not land on the permissive branch.

    A stateless chip would silently fall out of the `pregame` filter and leave
    the counts matching -- a failed read spelled as a decision. `learnings.md`
    2026-09-14: unknown must not default permissive.
    """
    pairs = observed["inplay_refused_when_a_state_is_missing"]["row_chip"]
    assert set(pairs.values()) == {None}, pairs


def test_two_pregame_halves_against_one_group_are_still_refused(observed: dict) -> None:
    """CONTROL: the state filter must not become "pair with whatever is left".

    Both halves still to come means two pregame chips against one group, which
    names no winner. This is the same ambiguity the equal-counts guard exists
    for, and it must survive the new branch.
    """
    pairs = observed["inplay_refused_when_both_halves_pregame"]["row_chip"]
    assert set(pairs.values()) == {None}, pairs


def test_a_timeless_group_is_placed_by_its_own_live_state(observed: dict) -> None:
    """THE GROUP-VS-GROUP CASE, measured on production 2026-09-25 21:34Z.

    Once a half is under way its odds group arrives TIMELESS -- a bare
    "FRI SEP 25" label with "2 opportunities" and no clock -- while a
    gamePk-keyed group carries the same game's scoreboard. The merge pass
    cannot fold them: chipped groups cluster on a shared chip OBJECT and
    chipless ones on matchup TEXT, so the two never meet and the game seats
    twice. Giving the timeless group its chip puts both in the same chip
    cluster and the existing merge collapses them.

    REACHABILITY: no ordered pass can place this group -- it has no start at
    all, so it never enters the timed list. Without the state match it stays
    chipless and this returns None.
    """
    pairs = observed["untimed_live_group_joins_the_live_chip"]["row_chip"]
    g1 = [k for k in pairs if k.endswith("aaaa")]
    g2 = [k for k in pairs if k.endswith("bbbb")]
    assert g1 and g2
    assert pairs[g1[0]] == "823543", pairs   # the LIVE chip
    assert pairs[g2[0]] == "823494", pairs   # the pregame half, via the state pass


def test_a_timeless_group_with_no_date_is_refused(observed: dict) -> None:
    """CONTROL: the date is the only thing keeping this within one venue-day.

    A group with no start AND no date has nothing anchoring it to today, so
    pairing it risks handing it a chip from another day's meeting of the same
    two clubs -- the exact failure `#165` follow-up #1 recorded.
    """
    pairs = observed["untimed_group_without_a_date_is_refused"]["row_chip"]
    g1 = [k for k in pairs if k.endswith("aaaa")]
    assert g1 and pairs[g1[0]] is None, pairs


def test_a_timeless_group_is_refused_when_two_chips_share_its_state(observed: dict) -> None:
    """CONTROL: exactly one unclaimed chip, or nothing.

    Both chips live means the ordered pass claims neither, so TWO chips remain
    unclaimed against one timeless group and nothing is forced. A wrong merge
    HIDES A GAME, which is the worst outcome this rail has, so ambiguity must
    refuse rather than pick.
    """
    pairs = observed["untimed_group_refused_when_two_chips_share_its_state"]["row_chip"]
    assert set(pairs.values()) == {None}, pairs


def test_a_timeless_group_pairs_even_when_its_own_state_is_stale(observed: dict) -> None:
    """THE REGRESSION TEST FOR THE FIRST VERSION OF THIS PASS.

    Measured on production 2026-09-25 22:39Z on served `c081d2e3`: the timeless
    BAL @ NYY group carried `market_state: "pregame"` while its game was in the
    top of the 9th and its own tile rendered LIVE. The pass asked the group what
    state it was in, got "pregame", and could never match the live chip -- so it
    never fired, and the rail seated game 1 twice.

    Pairing is now by ELIMINATION: the ordered pass takes the pregame chip for
    game 2's timed group, and the one chip and one timeless group left over are
    forced. The group's own state is never consulted, which is the point -- it
    is exactly the field that is unreliable here.
    """
    pairs = observed["untimed_group_with_a_stale_state_still_pairs"]["row_chip"]
    g1 = [k for k in pairs if k.endswith("aaaa")]
    g2 = [k for k in pairs if k.endswith("bbbb")]
    assert g1 and g2
    assert pairs[g1[0]] == "823543", pairs   # the live half, despite saying pregame
    assert pairs[g2[0]] == "823494", pairs


def test_two_timeless_groups_are_refused(observed: dict) -> None:
    """CONTROL: elimination needs exactly one on each side.

    With both groups timeless the ordered passes claim nothing, so two chips
    face two groups and no pairing is forced. Without this the rule could
    degrade into "hand them out in some order", which is the guessing the
    doubleheader module exists to prevent.
    """
    pairs = observed["two_untimed_groups_are_refused"]["row_chip"]
    assert set(pairs.values()) == {None}, pairs
