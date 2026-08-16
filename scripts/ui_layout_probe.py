"""Re-runnable version of the 2026-08-14 UI audit's measurements.

The audit that produced `.syndicate/audit_2026-08-14_ui.md` was a set of
throwaway probes; its findings were real but nobody could reproduce them
without rewriting the probes. This is those measurements as a script, so a
regression shows up as a number moving rather than as someone noticing a card
looks wrong.

What it measures, per sport, at both widths:

  * horizontal page overflow      documentElement.scrollWidth - clientWidth
  * card-height spread            max - min over the slate's game cards
  * tab/panel id agreement        every tab addresses a panel, and vice versa
  * tab click-through             a TRUSTED click on each tab leaves exactly
                                  one panel active and a card taller than its
                                  header strip
  * touch targets                 tab width/height against WCAG 2.5.5's 44x44
  * type scale                    computed font-size/weight per named class,
                                  reported PER SURFACE (card vs scoreboard
                                  strip) -- see the second caveat below
  * tabular figures               computed font-variant-numeric on the classes
                                  carrying odds and projections
  * unstyled links                any anchor inside a card still rendering the
                                  user-agent's default link colour
  * repeated copy                 the same string rendered more than once in
                                  one card, per panel
  * empty regions                 empty-state blocks, `—` placeholder cells and
                                  zero-bin distribution bars, per panel

METHOD CAVEAT 1, and it is not optional reading. The original audit's tab
results were produced with synthetic `el.click()` and one of them was WRONG
and had to be retracted (WNBA's tabs were reported broken; they work). Only
Playwright's `locator.click()` -- a real input event through the browser's own
dispatch -- is trusted here. If you extend this script, do not reach for
`page.evaluate("el.click()")` to save a scroll.

METHOD CAVEAT 2, added 2026-08-15 after this script produced its own wrong
number. The type-scale table was built with `document.querySelector(selector)`
-- the FIRST match on the page. `.cards-head-team-name` is used by both the
scoreboard strip and the game card, and soccer ships a bespoke strip that
deliberately sets 13px. So the table read "soccer 13px / NFL 16px" and the
audit turned that into a defect ("raise soccer's team names to 16px") for an
element that had been 16px all along, against a rule Lane E had just written
down for the OTHER element. One class, two surfaces, one sample. The table is
now keyed by surface, and a class appearing on more than one surface at
different sizes is reported as `conflated`, not silently collapsed to its
first hit. Any per-class table over a shared stylesheet needs this.

A sport that serves zero cards is reported as `cards: 0`, NOT as a pass. NBA,
NHL and NCAAB were out of season on 2026-08-14 and their rows in the audit's
divergence matrix are code-only for that reason.

Usage:

    py -3 scripts/ui_layout_probe.py                       # serve in-process
    py -3 scripts/ui_layout_probe.py --base-url http://127.0.0.1:5000
    py -3 scripts/ui_layout_probe.py --json --write reports/ui_layout/latest.json
"""
from __future__ import annotations

import argparse
import json
import socket
import sys
import threading
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from werkzeug.serving import BaseWSGIServer, WSGIRequestHandler, make_server

from syndicate.app import create_app

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover - CLI-only path.
    sync_playwright = None


# Route per sport. Soccer is per-league; EPL is the league the audit measured.
SPORT_ROUTES: dict[str, str] = {
    "mlb": "/mlb/cards",
    "nfl": "/nfl/cards",
    "ncaaf": "/ncaaf/cards",
    "ncaab": "/ncaab/cards",
    "nba": "/nba/cards",
    "nhl": "/nhl/cards",
    "wnba": "/wnba/cards",
    "soccer": "/soccer/epl/cards",
}

VIEWPORTS: dict[str, dict[str, int]] = {
    "desktop": {"width": 1440, "height": 1200},
    "mobile": {"width": 390, "height": 844},
}

# Classes the audit tabulated. Kept as one list so the type-scale table stays
# comparable across runs rather than drifting with whatever was interesting
# that day.
TYPE_CLASSES = [
    ".cards-mini-copy",
    ".cards-market-label",
    ".cards-market-main",
    ".cards-market-sub",
    ".cards-tab",
    ".cards-head-team-name",
    ".cards-data-pair span",
    ".cards-data-pair strong",
]

# The classes that carry numbers which change on the 30s poll.
#
# THIS LIST IS A CROSS-CHECK, NOT THE MEASUREMENT, and the difference is the
# whole point. Measured 2026-08-15 on production `c774fe1a`: all three of these
# selectors match ZERO elements on /mlb/cards, because MLB renders through
# `cards_source.js`, which emits `.cards-linescore-stat`, `.cards-chip`,
# `.cards-starter-ladder-badge` and friends instead. The old probe did
# `querySelector(sel); if (!el) return;` -- so the key simply vanished from the
# report and `summarize()` had no branch for a missing key. MLB, the sport with
# the most traffic and a 30s poll, read as a PASS on a check that never touched
# it. A hand-maintained list of class names goes stale the moment a renderer
# forks; `numericSweep` below finds elements by what they RENDER instead.
NUMERIC_CLASSES = [".cards-data-pair strong", ".cards-market-main", ".cards-mini-metric strong"]

# Classes a sport's design legitimately does not have, DECLARED BY NAME with a
# reason -- the same opt-out shape as OUT_OF_SEASON, and for the same reason.
# Silent absence is the bug this file exists to prevent; declared absence is a
# design fact, and writing it down is what keeps the two apart.
#
# An entry here is a claim that can rot, so it is checked in BOTH directions:
# absent-and-exempt passes quietly, but present-and-exempt is reported, because
# that means the sport grew the class and the exemption is now a lie.
NUMERIC_CLASS_EXEMPT: dict[str, dict[str, str]] = {
    "ncaaf": {
        ".cards-market-main": (
            "the ncaaf card has no market tile row at all -- `_game_card.html` "
            "sends `ncaaf_main` to `_game_card_ncaaf.html`, which contains zero "
            "`cards-market` markup and presents the same numbers as "
            "`.cards-data-pair` inside panels. Verified 2026-08-15. NOTE: "
            "`ncaaf/cards.py` does build `market_tiles`, but they are "
            "publication metadata (Coverage/Tier/Status/Priority), not market "
            "data, and they are consumed by `home.py` -- not dead, do not delete."
        ),
    },
}

WCAG_TARGET_PX = 44

# How far a card may sit from the `chrome + k * units` height model before the
# run fails, and it is a MEASURED number, not a guess. Baseline taken on
# production 2026-08-15 with the render fully settled, across every group the
# model called reliable:
#
#     mlb mobile  Live     n= 3   residual   6px
#     mlb mobile  Preview  n=10   residual  54px
#     mlb desktop Live     n= 3   residual  18px
#
# 150px is ~3x the worst clean reading. Wide enough that ordinary content
# churn does not trip it, narrow enough that a card rendering an extra block
# (~62px per pair on mobile, and every panel is larger than that) shows up.
# Re-derive it if the card design changes; do not widen it to silence a run.
LAYOUT_RESIDUAL_BUDGET_PX = 150

# How far cards carrying IDENTICAL content may sit apart before the run fails,
# as a share of their own height. Proportional because the fixed 150px above was
# calibrated for a different metric (the residual, which no longer judges) on a
# different slate, and because wrap noise scales with card size: 150px is 2.8% of
# a 4800px mlb mobile card and 27% of a 541px ncaaf desktop one.
#
# Calibrated on 16 healthy readings, production 2026-08-16, two runs, all sports
# and both widths -- `spread / median height of the tied group`:
#
#     mlb   desktop Live     9.9%  8.3%      mlb   mobile Live     3.3%  3.3%
#     mlb   desktop Preview  3.3%  0.0%      mlb   mobile Preview  1.1%  2.8%
#     ncaaf desktop          8.3%  8.3%      ncaaf mobile          3.9%  3.9%
#     nfl   desktop          1.6%  1.6%      nfl   mobile          2.8%  2.8%
#
# Worst healthy reading 9.9%, so 15% is ~1.5x margin. Deliberately tighter than
# the 3x the fixed budget above used: 3x here would be 30%, which on a 4800px
# card is 1440px and would not catch anything.
#
# HONEST LIMIT, measured and not hidden: proportional does NOT tighten the
# distribution. Raw px span 0-158 (max/median 3.3) and these percentages span
# 0-9.9% (max/median 3.0) -- the same scatter. What it fixes is the width bias,
# where a fixed px budget is strict on tall mobile cards and loose on short
# desktop ones. It is a BACKSTOP for rows with no baseline; drift against a
# baseline (see TIE_SPREAD_BASELINED) is the sharper check and should be
# preferred wherever a row is stable enough to carry one.
PEER_DEVIATION_BUDGET_PCT = 15.0

# How many cards must share a pair count before their spread may FAIL a run.
# Thinner groups are still reported — never silently dropped — they just do not
# carry a verdict.
#
# Measured 2026-08-16: one run failed at 30.9% on an **n=2** Live group (2 cards
# at 41 pairs, 312px apart) while the n=6 group on the same board sat at 82px,
# comfortably under budget. Minutes later only ONE card remained at 41 pairs —
# the pairing was transient, and three consecutive runs since were green.
#
# The mechanism is MLB live enrichment: the peer rule assumes equal pair count
# implies comparable cards, and a card still receiving data holds a TRANSIENT
# pair count that can coincide with an unrelated card at a different stage. Two
# cards is the thinnest evidence the rule can be built on, and it is the second
# time an n=2 group produced a misleading number.
#
# 3 is the smallest n where one odd card does not BE the spread.
PEER_MIN_GROUP_N = 3

# How long to wait for the first card to attach before calling the render
# failed. Generous on purpose: it is only ever paid in full by a sport that is
# genuinely serving nothing, and the cost of being stingy is a false zero on
# the sport with the most traffic.
CARD_WAIT_MS = 20000

# Sports whose season has not opened, where 0 cards is the correct answer and
# not a failure. Measured 2026-08-14: NBA, NHL and NCAAB served 0 cards, so
# their rows in the audit's divergence matrix are code-only. REVIEW THIS LIST
# IN OCTOBER -- leaving a sport here after its season opens turns a real
# outage into a green run. Override on the command line with --expect-cards.
OUT_OF_SEASON = {"nba", "nhl", "ncaab"}


MEASURE_JS = """
(spec) => {
  const doc = document.documentElement;
  const cards = [...document.querySelectorAll('.cards-game-card, .cards-strip-card')];
  const gameCards = [...document.querySelectorAll('.cards-game-card')];
  const heights = gameCards.map((c) => Math.round(c.getBoundingClientRect().height));

  // Spread WITHIN a game state, because the overall number is dominated by how
  // many games happen to be live. Measured on production /mlb/cards at 390px,
  // 15 cards, 2026-08-15:
  //
  //     Preview  n=10  2929-3009px  spread   80px
  //     Final    n= 2  2833-2915px  spread   82px
  //     Live     n= 3  3156-4549px  spread 1393px
  //     overall                     spread 1716px
  //
  // The layout is tight to ~80px inside a state; the whole 1716 is live-game
  // content. So the overall figure swung 796 -> 1716 between two runs with no
  // code change, which makes it useless for catching a layout regression -- it
  // reports the slate, not the CSS. Per-state is the comparable number.
  const byState = {};
  gameCards.forEach((c) => {
    const badge = c.querySelector('.cards-status-badge');
    const state = ((badge && badge.textContent) || 'unknown').trim() || 'unknown';
    const h = Math.round(c.getBoundingClientRect().height);
    (byState[state] = byState[state] || []).push(h);
  });
  const cardHeightByState = {};
  Object.keys(byState).forEach((k) => {
    const v = byState[k].slice().sort((a, b) => a - b);
    cardHeightByState[k] = {n: v.length, min: v[0], max: v[v.length - 1], spread: v[v.length - 1] - v[0]};
  });

  // ...and even WITHIN a state the spread is mostly content volume, not layout.
  // Measured on production /mlb/cards at 390px, 10 Preview cards, 2026-08-15:
  // height tracks `.cards-data-pair` count almost linearly --
  //
  //     33 pairs -> 3100px      45 pairs -> 3830-3846px
  //     41 pairs -> 3591px      49 pairs -> 4101-4121px      53 pairs -> 4317-4345px
  //
  // i.e. ~62px per pair, and the same Preview group measured 80px of spread
  // twenty minutes earlier when every game carried the same amount of data.
  // So the height figures answer "how much data does this game have", and a
  // reader cannot tell a layout regression from a busy slate WITHOUT the
  // content count next to it. That is what this reports.
  const unitCounts = gameCards.map((c) => c.querySelectorAll('.cards-data-pair').length).sort((a, b) => a - b);
  const contentUnits = unitCounts.length
    ? {min: unitCounts[0], max: unitCounts[unitCounts.length - 1],
       spread: unitCounts[unitCounts.length - 1] - unitCounts[0]}
    : null;

  // THE LAYOUT SIGNAL. Card height is `chrome + k * units`, so the residual
  // from that fit is what stays flat while the slate churns and moves when the
  // layout actually changes.
  //
  // `height / units` is the obvious form and it is WRONG, measurably: fitted
  // over 10 production MLB Preview cards (33-53 pairs, 3100-4345px) the
  // intercept is **1051px** of fixed chrome -- head, market tiles, tab rail --
  // against a slope of 62.1px per pair. A ratio would read 94px/pair on the
  // 33-pair card and 82px/pair on the 53-pair card and call that a 15% layout
  // difference. It is not a difference; it is the constant, and it would have
  // made the metric worse than the raw number on exactly the sport it is for.
  //
  // Residuals on that same slate: [1, -5, -14, 2, 8, 28, -24, 4] px -- a spread
  // of 52px against a raw height spread of 1245px.
  // FIT PER GAME STATE, not across the slate, and that is a measured decision.
  // A single line over all 15 MLB cards gave a residual spread of 668px; the
  // same fit restricted to the 10 Preview cards gave 52px. A live card carries
  // content this unit does not count (the live lens), so mixing states breaks
  // the linearity and the residual stops being a layout signal. Fitting inside
  // a state is what makes it one.
  // Model-free layout signal: two cards carrying the same amount of data should
  // be the same height. No slope, no intercept, no n>=5 -- two tied cards is
  // enough, so it survives slates where `fitGroup` refuses to fit anything.
  //
  // That is not an edge case, it is the common one. Measured 2026-08-16 11:5x
  // CDT: every MLB card carried exactly 33 pairs, so there was ONE distinct `u`
  // and no line could be fitted at either width -- while 15 mutually tied cards
  // sat there, which is this metric at its strongest. Gating it behind the fit
  // would have thrown away the best reading of the day.
  function tieFloor(pts) {
    const byU = {};
    pts.forEach((p) => (byU[p.u] = byU[p.u] || []).push(p.h));
    const median = (v) => {
      const s = v.slice().sort((a, b) => a - b);
      const mid = Math.floor(s.length / 2);
      return s.length % 2 ? s[mid] : Math.round((s[mid - 1] + s[mid]) / 2);
    };
    const groups = Object.keys(byU)
      .map((u) => ({
        u: Number(u),
        n: byU[u].length,
        spread: Math.round(Math.max(...byU[u]) - Math.min(...byU[u])),
        // The DENOMINATOR for a proportional budget: how tall the cards being
        // compared actually are. Wrap noise scales with card size, so the same
        // px of spread means something different on a 700px nfl card and a
        // 4800px mlb one.
        medianH: median(byU[u]),
      }))
      .filter((g) => g.n > 1);
    if (!groups.length) return null;
    // TWO statistics, because two questions are being asked and they do not
    // have the same answer.
    //
    // `worstGroupPx` is the MAX spread over all tie groups. That is the floor a
    // FIT has to beat -- a model must explain every card, so the worst tie
    // bounds its residual from below. Using anything smaller here would let
    // something read as fittable when it is not.
    //
    // `spreadPx` is the TRACKED number, and it is the worst group as well.
    // It was briefly the largest group instead (2026-08-16, to try to steady
    // mlb mobile) and that was MEASURED WORSE on both mlb rows -- tracked
    // 67/132/164 = 2.45x against the worst group's 99/132/164 = 1.66x, because
    // the largest group's own SIZE churns (n = 7/14/7 across three runs). The
    // instability was never the statistic: nfl and ncaaf read 1.00x under both,
    // on static slates, while MLB enriches continuously during a live slate.
    // Reverted, so the tracked number and the fit floor are one quantity.
    //
    // `largestGroupPx` is kept and printed when it differs, because the two
    // statistics disagreeing is itself informative -- it says a small group is
    // straddling the extremes.
    const worst = groups.reduce((a, b) => (b.spread > a.spread ? b : a));
    const largest = groups.reduce((a, b) =>
      b.n > a.n || (b.n === a.n && b.spread > a.spread) ? b : a);
    return {
      spreadPx: worst.spread,
      atU: worst.u,
      n: worst.n,
      medianH: worst.medianH,
      // Spread as a share of the compared cards' own height, in percent.
      spreadPct: worst.medianH ? Math.round((worst.spread / worst.medianH) * 1000) / 10 : null,
      // EVERY tie group, not just the worst and largest. The failure gate needs
      // to pick the worst group ABOVE a minimum size, and it cannot do that from
      // two summary entries: excluding a thin group would otherwise skip a
      // genuine larger group whose spread happens to be smaller.
      groups: groups
        .map((g) => ({
          u: g.u,
          n: g.n,
          spread: g.spread,
          medianH: g.medianH,
          pct: g.medianH ? Math.round((g.spread / g.medianH) * 1000) / 10 : null,
        }))
        .sort((a, b) => (b.pct || 0) - (a.pct || 0)),
      // Same value as `spreadPx`, kept under its own name so a report written
      // on either side of the revert compares on the SAME quantity.
      worstGroupPx: worst.spread,
      largestGroupPx: largest.spread,
      largestAtU: largest.u,
      largestN: largest.n,
      tiedGroups: groups.length,
      cardsTied: groups.reduce((a, g) => a + g.n, 0),
    };
  }

  function fitGroup(pts) {
    // A line costs 2 parameters, so n=3 leaves ONE degree of freedom and the
    // residual is noise. Measured on the same slate, same instant: Live n=3
    // gave fit ratio 0.59 and 1.29 while Preview n=9 gave 0.09 -- the small
    // groups were not detecting anything, they were fitting themselves. n>=5
    // is the floor; below it there is no fit rather than a bad one.
    if (pts.length < 5 || new Set(pts.map((p) => p.u)).size < 2) return null;
    const n = pts.length;
    const sx = pts.reduce((a, p) => a + p.u, 0);
    const sy = pts.reduce((a, p) => a + p.h, 0);
    const sxx = pts.reduce((a, p) => a + p.u * p.u, 0);
    const sxy = pts.reduce((a, p) => a + p.u * p.h, 0);
    const denom = n * sxx - sx * sx;
    if (denom === 0) return null;
    const slope = (n * sxy - sx * sy) / denom;
    const intercept = (sy - slope * sx) / n;
    const res = pts.map((p) => p.h - (intercept + slope * p.u));
    const worst = pts
      .map((p, i) => ({u: p.u, h: p.h, residual: Math.round(res[i])}))
      .sort((a, b) => Math.abs(b.residual) - Math.abs(a.residual))[0];
    const residualSpread = Math.round(Math.max(...res) - Math.min(...res));
    // How much of the height range the model actually accounts for. The model
    // assumes each unit adds a ROW, which is true where the summary grid
    // stacks single-column and false where it wraps into columns. Measured
    // 2026-08-15 on the same MLB slate: mobile Preview residual 54px against
    // ~1000px explained (5%), desktop Preview 201px against ~261px (77%). Same
    // cards, same instant -- the desktop grid simply is not linear in pairs.
    // Reporting that as a layout alarm would make this permanently red on a
    // healthy board, so a poor fit is declared UNRELIABLE instead.
    const uRange = Math.max(...pts.map((p) => p.u)) - Math.min(...pts.map((p) => p.u));
    const explained = Math.abs(slope) * uRange;
    const fitRatio = explained > 0 ? residualSpread / explained : null;
    const groupHeightSpread = Math.max(...pts.map((p) => p.h)) - Math.min(...pts.map((p) => p.h));
    // Content-INDEPENDENT is a third state, and mistaking it for "no signal"
    // was this metric's bug. At 1440 the summary grid wraps into columns, so an
    // extra pair adds WIDTH, not height: measured slope **0.4-5.5 px/pair** on
    // desktop against **62 px/pair** on mobile, same cards, same instant. The
    // model then explains almost nothing and `fitRatio` calls it unreliable --
    // true, and the wrong conclusion. Where content does not drive height, the
    // RAW spread is already a clean layout signal and needs no model.
    //
    // 50px is the cutoff: content accounting for less than that across the
    // whole observed range is not driving height. Desktop groups measured
    // 10-38px explained; mobile Preview measured 745px.
    const contentIndependent = explained < 50;
    // THE FLOOR NO MODEL IN `u` CAN BEAT: cards carrying IDENTICAL content
    // still differ in height, because a pair's text WRAPS. The summary grid is
    // a wrapping flow -- 10 columns at 1440, 2 at 390 -- so a long team name or
    // a 5-character price pushes a row that a short one does not, and the pair
    // COUNT does not see it. Measured on production MLB, 2026-08-16, one slate,
    // one instant, all 15 cards Preview:
    //
    //     desktop u=45 (n=7) 1092..1208 = 116px    mobile u=45 (n=7) = 81px
    //     desktop u=49 (n=5) 1106..1203 =  97px    mobile u=49 (n=5) = 40px
    //
    // A second variable does not rescue it: cards agreeing on BOTH visible pair
    // count and visible row count still spread **74px** on desktop.
    //
    // This is what makes desktop UNFITTABLE rather than mis-tuned. `reliable`
    // wants residual <= 0.25 * explained, so a 116px floor needs 464px of
    // explained range; desktop's content spans 197px. No slope and no intercept
    // reach that, and moving the threshold to make it pass would be
    // manufacturing a fit rather than finding one.
    //
    // It also reframes a PASSING model. Mobile's residual is 81px and its floor
    // is 81px -- the fit sits exactly on the noise floor, so it is reporting how
    // text wraps, not a layout deviation. Mobile passes because its slope is
    // ~62px/pair against desktop's ~16px, which buys 743px of explained range
    // to hide the same noise behind.
    // The WORST tie, not the largest one: a fit has to beat every tie group.
    // The WORST tie, not the largest one: a fit has to beat every tie group.
    const tie = tieFloor(pts);
    const floorPx = tie ? tie.worstGroupPx : null;

    // IS THE LINE THE WRONG SHAPE? `fitRatio` cannot answer that. It is
    // residual / explained, so a misspecified model with a wide explained range
    // passes: mlb mobile Live, 2026-08-16, scored ratio 0.20 and `reliable`
    // while its per-pair cost ran 41.3 -> 61.8 -> 76.6 px/pair. Its residual was
    // not noise, it was a bend -- +76 at u=45, negative through the middle, +73
    // at u=57, the U-shape of a line fitted to a curve.
    //
    // Test the SHAPE directly: slopes between consecutive pair-count group
    // MEANS (means, so within-group wrap noise averages out instead of driving
    // the sign), then ask whether those slopes drift monotonically.
    //
    // Threshold measured rather than guessed, same slate and instant:
    //     Live    (97.0 - 40.8) / 64.0 = 0.88   <- curved
    //     Preview (65.6 - 65.1) / 65.4 = 0.008  <- straight
    // Two orders of magnitude apart, so 0.5 sits between them with enormous
    // margin and is not a load-bearing number.
    //
    // >=3 steps required: two steps can only ever be "one went up", which is
    // noise, not drift.
    const meanByU = {};
    pts.forEach((p) => (meanByU[p.u] = meanByU[p.u] || []).push(p.h));
    const orderedU = Object.keys(meanByU).map(Number).sort((a, b) => a - b);
    const slopes = [];
    for (let i = 1; i < orderedU.length; i++) {
      const lo = meanByU[orderedU[i - 1]], hi = meanByU[orderedU[i]];
      const mLo = lo.reduce((a, b) => a + b, 0) / lo.length;
      const mHi = hi.reduce((a, b) => a + b, 0) / hi.length;
      slopes.push((mHi - mLo) / (orderedU[i] - orderedU[i - 1]));
    }
    let curved = false;
    let slopeDrift = null;
    if (slopes.length >= 3) {
      const diffs = [];
      for (let i = 1; i < slopes.length; i++) diffs.push(slopes[i] - slopes[i - 1]);
      const monotone = diffs.every((d) => d > 0) || diffs.every((d) => d < 0);
      const meanSlope = slopes.reduce((a, b) => a + b, 0) / slopes.length;
      const range = Math.max(...slopes) - Math.min(...slopes);
      slopeDrift = meanSlope ? Math.round((range / Math.abs(meanSlope)) * 100) / 100 : null;
      curved = monotone && slopeDrift !== null && slopeDrift > 0.5;
    }
    // The best ratio ANY model in `u` could reach on this slate. Above the
    // reliability bar means no fit is possible here, however the line is drawn.
    const floorRatio = floorPx !== null && explained > 0 ? floorPx / explained : null;
    return {
      n,
      pxPerUnit: Math.round(slope * 10) / 10,
      chromePx: Math.round(intercept),
      residualSpread,
      maxAbsResidual: Math.round(Math.max(...res.map(Math.abs))),
      explainedPx: Math.round(explained),
      groupHeightSpread,
      fitRatio: fitRatio === null ? null : Math.round(fitRatio * 100) / 100,
      contentIndependent,
      // A curved fit is NOT reliable however small its ratio -- the ratio is
      // measuring the wrong thing when the shape is wrong.
      reliable: fitRatio !== null && fitRatio <= 0.25 && !curved,
      curved,
      slopeDrift,
      slopePerStep: slopes.map((s) => Math.round(s * 10) / 10),
      // Model-free, no free parameters, and the same number at both widths:
      // two cards with the same amount of data should be the same height.
      floorPx,
      floorRatio: floorRatio === null ? null : Math.round(floorRatio * 100) / 100,
      unfittable: floorRatio !== null && floorRatio > 0.25,
      atNoiseFloor: floorPx !== null && residualSpread <= floorPx,
      worstCard: worst,
    };
  }

  const ptsByState = {};
  gameCards.forEach((c) => {
    const badge = c.querySelector('.cards-status-badge');
    const state = ((badge && badge.textContent) || 'unknown').trim() || 'unknown';
    (ptsByState[state] = ptsByState[state] || []).push({
      u: c.querySelectorAll('.cards-data-pair').length,
      h: Math.round(c.getBoundingClientRect().height),
    });
  });
  const heightModelByState = {};
  Object.keys(ptsByState).forEach((k) => {
    const m = fitGroup(ptsByState[k]);
    if (m) heightModelByState[k] = m;
  });
  // The reported figure is the WORST state that could be fitted. States with
  // too few cards are absent rather than passing -- `statesUnfitted` says which,
  // so "no signal" never reads as "clean".
  // Rank states by the figure that will actually be REPORTED for them -- the
  // raw spread where content does not drive height, the residual where it
  // does. Ranking everything by residual would hide a content-independent
  // state with a large spread behind a well-fitted one with a small residual.
  const reported = (m) => (m.contentIndependent ? m.groupHeightSpread : m.residualSpread);
  const fittedStates = Object.keys(heightModelByState);
  const worstState = fittedStates.length
    ? fittedStates.reduce((a, b) =>
        reported(heightModelByState[a]) >= reported(heightModelByState[b]) ? a : b)
    : null;
  const heightModel = worstState
    ? Object.assign({state: worstState}, heightModelByState[worstState])
    : null;
  const statesUnfitted = Object.keys(ptsByState).filter((k) => !heightModelByState[k]);
  // Computed over EVERY state, independent of whether a line could be fitted.
  const tieByState = {};
  Object.keys(ptsByState).forEach((k) => {
    const t = tieFloor(ptsByState[k]);
    if (t) tieByState[k] = t;
  });
  const tieStates = Object.keys(tieByState);
  // Ranked by the statistic that is actually REPORTED, so the row shown is the
  // row the number came from.
  const worstTieState = tieStates.length
    ? tieStates.reduce((a, b) => (tieByState[a].spreadPx >= tieByState[b].spreadPx ? a : b))
    : null;
  const identicalContentSpread = worstTieState
    ? Object.assign({state: worstTieState}, tieByState[worstTieState])
    : null;

  // Tab/panel id agreement, per card. A tab whose target has no panel blanks
  // the card when clicked (NCAAF, measured 2026-08-14); a panel with no tab is
  // markup shipped to the browser that no user can reach.
  const tabsWithoutPanel = [];
  const panelsWithoutTab = [];
  gameCards.forEach((card) => {
    card.querySelectorAll('.cards-tab[data-tab-target]').forEach((tab) => {
      const id = tab.getAttribute('data-tab-target');
      if (!card.querySelector('.cards-panel[data-panel-id="' + id + '"]')) tabsWithoutPanel.push(id);
    });
    card.querySelectorAll('.cards-panel[data-panel-id]').forEach((panel) => {
      const id = panel.getAttribute('data-panel-id');
      if (!card.querySelector('.cards-tab[data-tab-target="' + id + '"]')) panelsWithoutTab.push(id);
    });
  });

  // Per SURFACE, not per page. See METHOD CAVEAT 2: one `querySelector` per
  // class reported soccer's strip size as the card's and produced a defect
  // that did not exist.
  const surfaceOf = (el) => el.closest('.cards-strip-card') ? 'strip'
                          : el.closest('.cards-game-card') ? 'card'
                          : 'other';
  const typeScale = {};
  (spec.typeClasses || []).forEach((selector) => {
    const bySurface = {};
    document.querySelectorAll(selector).forEach((el) => {
      const cs = getComputedStyle(el);
      const key = surfaceOf(el);
      if (!bySurface[key]) bySurface[key] = new Set();
      bySurface[key].add(cs.fontSize + '/' + cs.fontWeight);
    });
    const entry = {};
    Object.keys(bySurface).forEach((k) => { entry[k] = [...bySurface[k]].sort(); });
    if (Object.keys(entry).length) {
      const all = new Set(Object.keys(entry).map((k) => entry[k]).flat());
      typeScale[selector] = all.size > 1 ? Object.assign({conflated: true}, entry) : entry;
    }
  });

  // An anchor inside a card that nobody restyled. rgb(0, 0, 238) is Chromium's
  // default link colour; measured on soccer's card-head team names 2026-08-15,
  // underlined, against a #0a1522 card.
  const unstyledLinks = [...document.querySelectorAll('.cards-game-card a, .cards-strip-card a')]
    .map((a) => {
      const cs = getComputedStyle(a);
      return {text: a.textContent.trim().slice(0, 40), cls: String(a.className || ''),
              color: cs.color, decoration: cs.textDecorationLine};
    })
    .filter((a) => a.color === 'rgb(0, 0, 238)' || a.color === 'rgb(85, 26, 139)');

  // Repeated copy: the same rendered string appearing more than once inside a
  // single card. Soccer carried its projected-score sentence six times.
  const firstCard = document.querySelector('.cards-game-card');
  const repeatedCopy = [];
  const emptyRegions = [];
  if (firstCard) {
    const counts = new Map();
    firstCard.querySelectorAll('*').forEach((el) => {
      if (el.children.length) return;
      const t = (el.textContent || '').trim();
      if (t.length < 12) return;
      const panel = el.closest('.cards-panel');
      const hit = counts.get(t) || {text: t.slice(0, 70), count: 0, panels: []};
      hit.count += 1;
      hit.panels.push(panel ? panel.getAttribute('data-panel-id') : '(head)');
      counts.set(t, hit);
    });
    [...counts.values()].filter((h) => h.count > 1)
      .sort((a, b) => b.count - a.count).slice(0, 8)
      .forEach((h) => repeatedCopy.push(h));

    firstCard.querySelectorAll('.cards-panel[data-panel-id]').forEach((p) => {
      const emptyCopy = p.querySelectorAll('.cards-empty-copy').length;
      const placeholders = [...p.querySelectorAll('*')]
        .filter((e) => !e.children.length && e.textContent.trim() === '—').length;
      const emptyBars = [...p.querySelectorAll('.cards-run-dist-bar')]
        .filter((b) => b.children.length === 0).length;
      if (emptyCopy || placeholders || emptyBars) {
        emptyRegions.push({panel: p.getAttribute('data-panel-id'),
                           emptyCopy, placeholders, emptyBars});
      }
    });
  }

  // Every element, not the first one, and a selector that matches nothing is
  // reported as `count: 0` rather than dropped -- see the note on
  // NUMERIC_CLASSES. An absent measurement must never look like a clean one.
  const tabularFigures = {};
  (spec.numericClasses || []).forEach((selector) => {
    const els = [...document.querySelectorAll(selector)];
    const values = {};
    els.forEach((el) => {
      const v = getComputedStyle(el).fontVariantNumeric;
      values[v] = (values[v] || 0) + 1;
    });
    tabularFigures[selector] = {count: els.length, values};
  });

  // The check that does not depend on knowing the class names. Any leaf element
  // that actually renders a digit is a candidate for proportional-digit jitter
  // on the 30s poll, whichever renderer emitted it. Grouped by class so the
  // result names something a stylesheet can target.
  const sweep = {};
  document.querySelectorAll('.cards-game-card *, .cards-strip-card *').forEach((el) => {
    if (el.children.length) return;
    if (!/[0-9]/.test(el.textContent || '')) return;
    if (getComputedStyle(el).fontVariantNumeric === 'tabular-nums') return;
    const cls = (typeof el.className === 'string' ? el.className : '').split(/\\s+/).filter(Boolean);
    (cls.length ? cls : ['(no class)']).forEach((c) => { sweep[c] = (sweep[c] || 0) + 1; });
  });
  const numericSweep = Object.entries(sweep)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 12)
    .map(([cls, count]) => ({cls, count}));

  const tabBoxes = [...document.querySelectorAll('.cards-tab')].map((t) => {
    const r = t.getBoundingClientRect();
    return {w: Math.round(r.width), h: Math.round(r.height)};
  });

  // Mid-word breaking is not directly observable, but its precondition is: a
  // team-name box narrower than the longest word it has to render.
  const nameBoxes = [...document.querySelectorAll('.cards-head-team-name')].map((el) => ({
    text: el.textContent.trim(),
    surface: surfaceOf(el),
    width: Math.round(el.getBoundingClientRect().width),
    fontSize: getComputedStyle(el).fontSize,
    wrap: getComputedStyle(el).overflowWrap,
  }));

  return {
    scrollWidth: doc.scrollWidth,
    clientWidth: doc.clientWidth,
    overflowPx: doc.scrollWidth - doc.clientWidth,
    boxSizing: cards.length ? getComputedStyle(cards[0]).boxSizing : null,
    cards: gameCards.length,
    stripCards: cards.length - gameCards.length,
    cardHeightMin: heights.length ? Math.min(...heights) : null,
    cardHeightMax: heights.length ? Math.max(...heights) : null,
    cardHeightSpread: heights.length ? Math.max(...heights) - Math.min(...heights) : null,
    cardHeightByState,
    contentUnits,
    heightModel,
    heightModelByState,
    statesUnfitted,
    identicalContentSpread,
    identicalContentSpreadByState: tieByState,
    // The least-confounded figure available: the worst spread inside any one
    // game state. Still not a pure layout signal -- read it with contentUnits.
    cardHeightSpreadWithinState: Object.keys(cardHeightByState).length
      ? Math.max(...Object.keys(cardHeightByState).map((k) => cardHeightByState[k].spread))
      : null,
    tabsWithoutPanel: [...new Set(tabsWithoutPanel)],
    panelsWithoutTab: [...new Set(panelsWithoutTab)],
    typeScale,
    tabularFigures,
    numericSweep,
    tabBoxes,
    nameBoxes: nameBoxes.slice(0, 8),
    unstyledLinks,
    repeatedCopy,
    emptyRegions,
  };
}
"""


SETTLE_POLL_MS = 400
SETTLE_MAX_MS = 12000
# How long the card DOM must hold STILL before the render is called finished.
# Two consecutive equal polls -- 800ms, the floor the old loop could return --
# was not enough: it fit inside a pre-enrichment plateau. See `_settle`.
SETTLE_QUIET_MS = 2400

_FINGERPRINT_JS = """() => document.querySelectorAll('.cards-game-card').length * 100000
  + document.querySelectorAll('.cards-data-pair').length * 100
  + document.querySelectorAll('.cards-callout').length"""


def _settle(page) -> dict[str, Any]:
    """Wait until the card DOM stops growing, not until the first card exists.

    `wait_for_selector` proves a card ATTACHED. It does not prove the render
    finished, and on MLB those are seconds apart. Measured on production
    /mlb/cards at 390px, 2026-08-15, total `.cards-data-pair` across 15 cards:

        +0ms 482   +600ms 530   +1200ms 590   +2000ms 683   +3000ms 719   +4500ms 719

    The old fixed 600ms settle measured MLB at **74% of its final content**, so
    every MLB height, spread and content figure this probe produced was taken
    mid-render -- including the ones used to argue about the height model. A
    timeout is REPORTED, never silently treated as settled.

    **Two consecutive equal fingerprints was itself too weak, and it shipped a
    bad row.** `reports/ui_layout/rerun_2026-08-16.json`, mlb desktop: 15 cards
    at `contentUnits {min: 33, max: 33, spread: 0}` -- every game carrying
    identical data -- with `renderSettled: true` at `settledMs` **800**, which
    is the floor the old loop could return (two equal 400ms polls). In the same
    run, at the same slate, mobile read **33-49**, and 33 is exactly mobile's
    minimum. A recheck eight minutes later read desktop 33-49 at 1600ms; the
    08-15 baseline settled MLB at 6000/3600ms. The plateau, not the slate, was
    uniform: the poll landed before enrichment started and never saw it.

    Two changes follow from that.

    **1. The quiet window is wall-clock, not a poll count.** `SETTLE_QUIET_MS`
    of continuous stillness, so the floor is 2400ms rather than 800ms. The
    growth curve above moves at every 400ms step through 3000ms, so no 2400ms
    window inside it is quiet.

    **2. A verdict that rests on absence says so.** Absence of DOM change
    cannot distinguish "the render finished" from "the render has not started"
    -- these are the same observation. Only *change, then stillness* is
    affirmative evidence that the renderer ran to completion, so `sawChange`
    is reported and travels onto the row. This is the ledger's rule about wait
    loops gating on an affirmative success token rather than on the absence of
    a failure, recurring in a render poll.

    `sawChange: False` is NOT failed here: seven of the eight sports render
    server-side and are complete at `load`, so a still DOM is their normal and
    correct state. It is labelled, and `summarize` fails it only when a second
    reading contradicts it.
    """
    first = page.evaluate(_FINGERPRINT_JS)
    last = first
    saw_change = False
    quiet_ms = 0
    waited = 0
    while waited < SETTLE_MAX_MS:
        page.wait_for_timeout(SETTLE_POLL_MS)
        waited += SETTLE_POLL_MS
        fp = page.evaluate(_FINGERPRINT_JS)
        if fp == last:
            quiet_ms += SETTLE_POLL_MS
        else:
            saw_change = True
            quiet_ms = 0
            last = fp
        if quiet_ms >= SETTLE_QUIET_MS:
            return {
                "settledMs": waited,
                "settled": True,
                "sawChange": saw_change,
                "quietMs": quiet_ms,
                "firstFingerprint": first,
                "finalFingerprint": last,
            }
    return {
        "settledMs": waited,
        "settled": False,
        "sawChange": saw_change,
        "quietMs": quiet_ms,
        "firstFingerprint": first,
        "finalFingerprint": last,
    }


# How long to wait for a clicked tab's panel to actually become active, and how
# often to look. `activateTab` in `game_board.js` is a synchronous classList
# swap, so one poll normally suffices -- this window exists because the board
# replaces its own innerHTML on a 30s timer and can detach the node mid-check.
TAB_ACTIVATE_WAIT_MS = 2000
TAB_POLL_MS = 100


def _tab_click_through(page, sport: str) -> list[dict[str, Any]]:
    """Trusted click on every tab of the first card. See the method caveat."""
    card = page.locator(".cards-game-card").first
    if card.count() == 0:
        return []
    tabs = card.locator(".cards-tab[data-tab-target]")
    results: list[dict[str, Any]] = []
    read_state = """(node) => ({
        active: [...node.querySelectorAll('.cards-panel.is-active')].map((p) => p.getAttribute('data-panel-id')),
        height: Math.round(node.getBoundingClientRect().height),
    })"""
    for index in range(tabs.count()):
        tab = tabs.nth(index)
        target = tab.get_attribute("data-tab-target")
        # THE BOARD REPLACES ITSELF UNDERNEATH THIS CHECK. `game_board.js` polls
        # every 30s and does `cardsGrid.innerHTML = fresh.innerHTML`, which
        # detaches every node this loop is holding. The check had NO defence
        # against that and read the panel state exactly once, immediately after
        # `click()` returned -- a single sample of a DOM that another timer can
        # rewrite between the click and the read.
        #
        # So: retry once when the element goes stale, and wait for the OUTCOME
        # rather than sampling it. `activateTab` is synchronous, so the first
        # poll normally succeeds; the loop exists for the swap, not for a slow
        # handler. A timeout is REPORTED, never treated as success.
        state, error, attempts = None, None, 0
        for attempt in (1, 2):
            attempts = attempt
            try:
                tab.scroll_into_view_if_needed(timeout=5000)
                tab.click(timeout=5000)
                waited = 0
                while True:
                    state = card.evaluate(read_state)
                    if state["active"] == [target]:
                        break
                    if waited >= TAB_ACTIVATE_WAIT_MS:
                        break
                    page.wait_for_timeout(TAB_POLL_MS)
                    waited += TAB_POLL_MS
                error = None
                break
            except Exception as exc:  # pragma: no cover - reported, not raised.
                error = f"{type(exc).__name__}: {str(exc).splitlines()[0][:80]}"
                state = None
        if state is None:
            # No measurement at all. Carries `ok: False` explicitly rather than
            # relying on a missing key to read as failure downstream.
            results.append({"tab": target, "error": error, "attempts": attempts, "ok": False})
            continue
        results.append(
            {
                "tab": target,
                "activePanels": state["active"],
                "cardHeight": state["height"],
                "attempts": attempts,
                # One panel active, and a card taller than a bare header strip.
                # The NCAAF failure rendered 0 panels and a 187px card.
                "ok": len(state["active"]) == 1 and state["active"][0] == target and state["height"] > 250,
            }
        )
    return results


def probe(base_url: str, sports: Sequence[str], timeout_ms: int) -> dict[str, Any]:
    if sync_playwright is None:
        raise SystemExit(
            "playwright is not installed. pip install -r requirements-dev.txt && playwright install chromium"
        )
    report: dict[str, Any] = {"baseUrl": base_url, "sports": {}}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            for sport in sports:
                route = SPORT_ROUTES[sport]
                sport_report: dict[str, Any] = {"route": route}
                for label, viewport in VIEWPORTS.items():
                    context = browser.new_context(viewport=viewport)
                    page = context.new_page()
                    try:
                        # The status is not decoration. Run against a 502ing
                        # production on 2026-08-15 this script printed a clean
                        # table and exit code 0: every sport measured 0 cards
                        # and 0px of overflow, because Render's error page has
                        # no cards and does not overflow. A probe that passes
                        # on an error page is worse than no probe.
                        response = page.goto(f"{base_url}{route}", timeout=timeout_ms, wait_until="load")
                        status = response.status if response is not None else None
                        # Wait on CONTENT, not on a timer. Seven of the eight
                        # sports render server-side and are complete at `load`;
                        # MLB renders through `cards_source.js` AFTER it, so a
                        # fixed delay races the renderer. Measured 2026-08-15:
                        # the same production URL returned 0 cards and 15 cards
                        # minutes apart, and a 600ms read found 0 elements for
                        # classes a 2500ms read found 495 of. That false zero
                        # reached a written claim before it was caught.
                        #
                        # A timeout here is NOT a 0-card slate. It is recorded
                        # as its own state so an unfinished render can never be
                        # read as an empty one -- the same rule this file
                        # applies to a missing selector and a 502.
                        card_wait_timed_out = False
                        settle: dict[str, Any] = {}
                        if status is not None and status < 400:
                            try:
                                page.wait_for_selector(
                                    ".cards-game-card, .cards-strip-card",
                                    timeout=min(timeout_ms, CARD_WAIT_MS),
                                    state="attached",
                                )
                                settle = _settle(page)
                            except Exception:
                                card_wait_timed_out = True
                        measured = page.evaluate(
                            MEASURE_JS,
                            {"typeClasses": TYPE_CLASSES, "numericClasses": NUMERIC_CLASSES},
                        )
                        measured["httpStatus"] = status
                        measured["cardWaitTimedOut"] = card_wait_timed_out
                        measured["settledMs"] = settle.get("settledMs")
                        measured["renderSettled"] = settle.get("settled")
                        # Whether the settle verdict has affirmative evidence
                        # behind it (the DOM changed, then went still) or rests
                        # only on the absence of change. See `_settle`.
                        measured["settleSawChange"] = settle.get("sawChange")
                        measured["touchTargetFailures"] = [
                            box
                            for box in measured.pop("tabBoxes", [])
                            if box["h"] < WCAG_TARGET_PX or box["w"] < WCAG_TARGET_PX
                        ]
                        if label == "desktop":
                            measured["tabClickThrough"] = _tab_click_through(page, sport)
                        sport_report[label] = measured
                    except Exception as exc:  # pragma: no cover - reported, not raised.
                        sport_report[label] = {"error": f"{type(exc).__name__}: {exc}"}
                    finally:
                        context.close()
                report["sports"][sport] = sport_report
        finally:
            browser.close()
    return report


def _contradicted_width(sport_report: dict[str, Any]) -> str | None:
    """The width whose content reading the other width contradicts.

    `.cards-data-pair` count is a DOM fact, and no card renderer keys it on
    viewport width -- checked against `syndicate/static/mlb/cards_source.js`,
    which has no `matchMedia`/`innerWidth` branch. So the two widths must agree
    on how much content the slate carries. When they disagree, one of the two
    was measured before the slate finished arriving.

    Returns the label that read LESS content **and** whose settle rested on the
    absence of change -- the reading that has both a contradiction against it
    and no affirmative evidence for it. That conjunction is what makes this
    safe to fail on: a bare disagreement is not proof of an unfinished render,
    because the widths are separate navigations and the slate can genuinely
    grow between them. Returns None when the widths agree, when the short side
    watched the DOM change, or when either side is missing the field (an older
    report predates it, and must not be failed on it).
    """
    readings = {}
    for label in VIEWPORTS:
        measured = sport_report.get(label) or {}
        units = measured.get("contentUnits") or {}
        if units.get("max") is None:
            return None
        readings[label] = (units, measured.get("settleSawChange"))
    if len({(u["min"], u["max"]) for u, _ in readings.values()}) == 1:
        return None
    short = min(readings, key=lambda lbl: readings[lbl][0]["max"])
    return short if readings[short][1] is False else None


def summarize(report: dict[str, Any]) -> tuple[list[str], bool]:
    lines: list[str] = []
    ok = True
    rests_on_absence: list[str] = []
    out_of_season = set(report.get("outOfSeason") or ())
    # `spread` is the worst spread WITHIN a game state, not across the slate --
    # see the note in MEASURE_JS. The across-slate figure is still in the JSON
    # as `cardHeightSpread`, but it is not what gets printed, because it moves
    # with how many games are live and cannot be compared between runs.
    header = f"{'sport':8} {'width':8} {'cards':>5} {'overflow':>9} {'spread':>7}  tabs"
    lines.append(header)
    lines.append("-" * len(header))
    for sport, sport_report in report["sports"].items():
        contradicted = _contradicted_width(sport_report)
        for label in VIEWPORTS:
            measured = sport_report.get(label) or {}
            if "error" in measured:
                lines.append(f"{sport:8} {label:8} {'ERR':>5}  {measured['error'][:60]}")
                ok = False
                continue
            overflow = measured.get("overflowPx")
            spread = measured.get("cardHeightSpreadWithinState")
            if spread is None:
                spread = measured.get("cardHeightSpread")
            cards = measured.get("cards") or 0
            issues = []
            if overflow:
                issues.append(f"overflow {overflow}px")
                ok = False
            if measured.get("tabsWithoutPanel"):
                issues.append("tab->missing panel " + ",".join(measured["tabsWithoutPanel"]))
                ok = False
            if measured.get("panelsWithoutTab"):
                issues.append("unreachable panel " + ",".join(measured["panelsWithoutTab"]))
                ok = False
            failed_clicks = [r for r in measured.get("tabClickThrough", []) if not r.get("ok")]
            if failed_clicks:
                # Print WHY, not just which tab. `tab click identity` was the
                # whole of what the 2026-08-16 intermittent left behind, and it
                # is not enough to diagnose from -- the reason has to survive
                # into the row and the JSON or the next occurrence costs another
                # investigation.
                def _why(r):
                    if r.get("error"):
                        return f"{r.get('tab')} [{r['error']}]"
                    return (f"{r.get('tab')} [active={r.get('activePanels')} "
                            f"h={r.get('cardHeight')}px]")
                issues.append("tab click " + ",".join(_why(r) for r in failed_clicks))
                ok = False
            if label == "mobile" and measured.get("touchTargetFailures"):
                issues.append(f"{len(measured['touchTargetFailures'])} tabs < 44px")
            # An anchor left on the user-agent's default link colour is
            # unambiguous and cheap to fix, so it fails the run.
            if measured.get("unstyledLinks"):
                issues.append(f"{len(measured['unstyledLinks'])} unstyled link(s)")
                ok = False
            # Tabular figures, and the reason this branch exists at all: the
            # old probe reported nothing when a selector matched nothing, so
            # MLB passed a check that had never run on it. A numeric class with
            # 0 elements on a sport that IS serving cards is now a failure --
            # it means the class list has gone stale against that renderer, and
            # the honest state of the measurement is "unknown", not "fine".
            if cards:
                figures = measured.get("tabularFigures") or {}
                exempt = NUMERIC_CLASS_EXEMPT.get(sport, {})
                unmeasured = [
                    s for s, v in figures.items()
                    if not (v or {}).get("count") and s not in exempt
                ]
                if unmeasured:
                    issues.append(
                        "numeric class not found (measurement did NOT run): "
                        + ",".join(s.replace(".cards-", "") for s in unmeasured)
                    )
                    ok = False
                # The exemption is a CLAIM about the sport's markup, so it is
                # checked in the other direction too. If the class turns up, the
                # sport grew a surface the exemption says it does not have, and
                # the entry is now hiding a real measurement.
                stale_exempt = [s for s in exempt if (figures.get(s) or {}).get("count")]
                if stale_exempt:
                    issues.append(
                        "STALE EXEMPTION (class now exists, remove it from "
                        "NUMERIC_CLASS_EXEMPT): "
                        + ",".join(s.replace(".cards-", "") for s in stale_exempt)
                    )
                    ok = False
                proportional = [
                    s for s, v in figures.items()
                    if (v or {}).get("count") and any(k != "tabular-nums" for k in (v.get("values") or {}))
                ]
                if proportional:
                    issues.append("proportional digits: " + ",".join(s.replace(".cards-", "") for s in proportional))
                    ok = False
                # The name-independent sweep. Reported, not failed: it finds the
                # long tail a class list cannot, and hard-failing it would gate
                # every run on a backlog rather than on a regression.
                sweep = measured.get("numericSweep") or []
                if sweep:
                    total = sum(s["count"] for s in sweep)
                    top = ",".join(f"{s['cls']}({s['count']})" for s in sweep[:3])
                    issues.append(f"{total} numeric leaves not tabular, top: {top}")
            # These two are REPORTED, not failed. They are counts that should
            # trend down; hard-failing them on day one across seven sports
            # would make the harness something people skip rather than run.
            repeats = measured.get("repeatedCopy") or []
            if repeats:
                worst = max(r["count"] for r in repeats)
                issues.append(f"copy repeated up to {worst}x")
            empties = measured.get("emptyRegions") or []
            if empties:
                total = sum(e["emptyCopy"] + e["placeholders"] + e["emptyBars"] for e in empties)
                issues.append(f"{total} empty slot(s) in {len(empties)} panel(s)")
            # Print the content range next to the spread whenever cards differ
            # in how much data they carry, so nobody reads a busy slate as a
            # layout regression. MLB's spread is ~62px per `.cards-data-pair`.
            units = measured.get("contentUnits") or {}
            if units.get("spread"):
                issues.append(f"content varies {units['min']}-{units['max']} pairs/card")
            # The layout signal: deviation from `chrome + k * units`. Printed
            # whenever it exists, and FAILED only against a baseline that was
            # measured rather than guessed -- see LAYOUT_RESIDUAL_BUDGET_PX.
            model = measured.get("heightModel") or {}
            # Report EVERY fitted state, not only the worst. Measured: mobile
            # Preview (n=9) was a clean 68px/ratio-0.09 signal while Live (n=3,
            # since excluded) ranked "worst" at ratio 0.59 -- so the one real
            # signal on the page was hidden behind noise from a group too small
            # to fit. A summary that shows only the worst row can suppress the
            # only row that was working.
            by_state = measured.get("heightModelByState") or {}
            healthy = [s for s, m in by_state.items() if m.get("reliable") and not m.get("contentIndependent")]
            if healthy and (model or {}).get("state") not in healthy:
                for s in sorted(healthy):
                    m2 = by_state[s]
                    issues.append(f"layout residual {m2['residualSpread']}px in {s} (reliable)")
            if model:
                # Three states, not two. Treating the middle one as "no signal"
                # was this metric's own bug -- see the note in fitGroup.
                if model.get("contentIndependent"):
                    # "Content is not driving height" is what a FLAT LINEAR
                    # SLOPE means, and on desktop that inference is false. The
                    # pair grid wraps, so content drives height non-linearly and
                    # a near-zero slope says the line cannot see it, not that it
                    # is absent.
                    #
                    # Measured 2026-08-16, mlb desktop: raw group spread 313px
                    # against an identical-content spread of 70px. Calling 313px
                    # "a layout difference" is wrong -- 243px of it tracks the
                    # 33-57 pair range. That failed a run on a healthy board.
                    #
                    # So the budget is applied to the CONTENT-CONTROLLED figure
                    # when one exists: cards carrying the same data, how far
                    # apart are they. The raw spread is only the signal when
                    # nothing ties and there is nothing better.
                    issues.append(
                        f"layout spread {model['groupHeightSpread']}px in {model['state']} "
                        f"(content-independent: {model['explainedPx']}px explained "
                        f"at {model['pxPerUnit']}px/pair) -- context; the peer check below "
                        "is what judges"
                    )
                elif model.get("unfittable"):
                    # Not "mis-tuned" and not "no signal" -- IMPOSSIBLE. State
                    # the floor and the range so the number can be checked
                    # rather than believed, and so nobody tries to rescue this
                    # by moving LAYOUT_RESIDUAL_BUDGET_PX or the fit ratio.
                    issues.append(
                        f"layout model UNFITTABLE in {model['state']}: "
                        f"identical-content cards differ by {model['floorPx']}px while "
                        f"content explains only {model['explainedPx']}px -- no model in "
                        "pair count fits here at ANY threshold (text wrap drives height)"
                    )
                elif model.get("curved"):
                    # Distinct from UNRELIABLE: the line is not noisy, it is the
                    # WRONG SHAPE, and its ratio looked fine. Saying "no layout
                    # signal here" would understate it -- there is a signal and
                    # the model is mis-reading it.
                    issues.append(
                        f"layout model MISSPECIFIED in {model['state']}: per-pair cost "
                        f"drifts {'/'.join(str(s) for s in model.get('slopePerStep') or [])}"
                        f" px/pair (drift {model.get('slopeDrift')}) -- the fit is CURVED, "
                        f"so its {model['fitRatio']} ratio certifies nothing"
                    )
                elif not model.get("reliable"):
                    issues.append(
                        f"layout model UNRELIABLE in {model['state']} "
                        f"(fit ratio {model['fitRatio']}, {model['explainedPx']}px "
                        "explained) -- no layout signal here"
                    )
                else:
                    # A fit sitting ON its floor has not measured a deviation.
                    # Saying so is the difference between "82px of layout
                    # residual" and "82px of text wrapping".
                    floor_note = ""
                    if model.get("atNoiseFloor"):
                        floor_note = (
                            f" -- AT ITS NOISE FLOOR ({model['floorPx']}px between "
                            "identical-content cards), so this is text wrap, not "
                            "layout deviation"
                        )
                    issues.append(
                        f"layout residual {model['residualSpread']}px in {model['state']} "
                        f"({model['chromePx']}px chrome + {model['pxPerUnit']}px/pair)"
                        + floor_note
                    )
                # Absence of a fit is absence of a signal, never a pass.
                unfitted = measured.get("statesUnfitted") or []
                if unfitted:
                    issues.append("no layout fit for: " + ",".join(unfitted))
            # Printed OUTSIDE the `if model:` block on purpose: this is the one
            # height figure that survives a slate no line can be fitted to, and
            # gating it on the model would hide it exactly when it is the only
            # thing left. Reported, never failed -- see WATCH_METRICS.
            tie = measured.get("identicalContentSpread") or {}
            if tie.get("spreadPx") is not None:
                # Both statistics, always. The tracked one is the largest group;
                # printing the worst next to it is what stops the choice of
                # statistic from quietly hiding a bigger difference elsewhere on
                # the page.
                other = ""
                if tie.get("largestGroupPx") != tie.get("spreadPx"):
                    other = (f"; largest group {tie['largestGroupPx']}px "
                             f"at {tie['largestAtU']} pairs, n={tie['largestN']}")
                issues.append(
                    f"identical-content spread {tie['spreadPx']}px in {tie['state']} "
                    f"(worst group: {tie['n']} cards at {tie['atU']} pairs; "
                    f"{tie['cardsTied']} tied across {tie['tiedGroups']} group(s)"
                    f"{other})"
                )
            # THE ONE HEIGHT FAILURE RULE. A card is anomalous when it differs
            # from cards carrying the SAME pair count -- not when it differs from
            # a fitted line. Model-free: no slope, no intercept, no reliability
            # bar, and it runs on slates where nothing can be fitted at all.
            #
            # It replaces two rules that each produced a false alarm on a healthy
            # board on 2026-08-16:
            #   * residual-from-the-line: mlb mobile Live read residual 151px and
            #     failed, while every card agreed with its OWN peers to 40px. The
            #     fit was CURVED (41.3 -> 61.8 -> 76.6 px/pair) and `fitRatio`
            #     cannot see curvature, so a misspecified model passed as
            #     `reliable` and its structured residual tripped the budget. The
            #     card it accused was the only card at its pair count, so the
            #     accusation had no peer to rest on.
            #   * raw group spread: mlb desktop read 313px and failed, while
            #     identical-content cards differed by 70px -- the other 243px was
            #     the 33-57 pair range.
            #
            # THE COVERAGE THIS COSTS, stated rather than hidden: a card with no
            # same-pair-count peer cannot be judged at all, so a defect isolated
            # to a unique-content card is missed where the residual might have
            # caught it. Both the tie coverage and the did-not-run case are
            # printed so the blind spot is visible on the row rather than implied
            # by a clean line.
            by_state_ties = measured.get("identicalContentSpreadByState") or {}
            if by_state_ties:
                # Proportional, not a fixed px: wrap noise scales with card
                # size, so 150px is 2.8% of an mlb mobile card and 27% of an
                # ncaaf desktop one. A reading with no measurable height cannot
                # be judged as a share of it -- absence must not map onto the
                # permissive branch, so it is named instead of skipped.
                over, thin, unmeasurable = [], [], []
                for state, blob in sorted(by_state_ties.items()):
                    groups = blob.get("groups")
                    if groups is None:
                        # A report predating the per-group list. Fall back to the
                        # summary entry so an older artifact still gets judged,
                        # but it carries no group sizes, so it cannot be filtered.
                        groups = [{
                            "u": blob.get("atU"), "n": blob.get("n"),
                            "spread": blob.get("spreadPx"), "medianH": blob.get("medianH"),
                            "pct": blob.get("spreadPct"),
                        }]
                    for g in groups:
                        if g.get("pct") is None:
                            unmeasurable.append((state, g))
                        elif g["pct"] <= PEER_DEVIATION_BUDGET_PCT:
                            continue
                        elif (g.get("n") or 0) >= PEER_MIN_GROUP_N:
                            over.append((state, g))
                        else:
                            thin.append((state, g))
                for state, g in over:
                    issues.append(
                        f"PEER DEVIATION OVER BUDGET in {state} ({g['pct']}% > "
                        f"{PEER_DEVIATION_BUDGET_PCT}% of card height): {g['n']} cards "
                        f"carry {g['u']} pairs each and differ by {g['spread']}px "
                        f"on a {g['medianH']}px card -- same data, different height"
                    )
                    ok = False
                for state, g in thin:
                    # Reported, not failed, and NOT silent: a thin group over
                    # budget is the shape of a transient pairing during live
                    # enrichment, but it is also how a real defect would first
                    # appear, so it has to stay visible.
                    issues.append(
                        f"peer deviation in {state} NOT JUDGED -- {g['pct']}% over "
                        f"{g['n']} card(s) at {g['u']} pairs, below the n>={PEER_MIN_GROUP_N} "
                        "a verdict needs"
                    )
                for state, g in unmeasurable:
                    issues.append(
                        f"peer deviation in {state} NOT JUDGED -- {g.get('spread')}px "
                        "with no measurable card height to take a share of"
                    )
                tied = sum(b.get("cardsTied", 0) for b in by_state_ties.values())
                if cards and tied < cards:
                    issues.append(
                        f"peer check covered {tied}/{cards} cards -- the rest share a "
                        "pair count with nothing and cannot be judged"
                    )
            elif cards:
                # Absence of a comparison is not a pass, and it is not a failure
                # either -- it is a stated gap, the same treatment `statesUnfitted`
                # gets.
                issues.append(
                    f"PEER CHECK DID NOT RUN -- no two of {cards} cards share a pair "
                    "count, so nothing is comparable at equal content"
                )
            conflated = [k for k, v in (measured.get("typeScale") or {}).items() if isinstance(v, dict) and v.get("conflated")]
            if conflated:
                issues.append("type conflated: " + ",".join(c.lstrip(".") for c in conflated))
            status = measured.get("httpStatus")
            if status is not None and status >= 400:
                issues.append(f"HTTP {status} -- NOTHING BELOW IS A MEASUREMENT")
                ok = False
            # This used to be reported and then passed: the docstring said "0
            # cards is NOT a pass" and the exit code said 0 anyway. An
            # out-of-season sport is a legitimate 0, so it is opt-out by name
            # rather than silently tolerated -- which is what makes a 0 on a
            # sport you EXPECTED to have cards fail the run.
            # A render that never produced a card is NOT an empty slate, and
            # conflating the two is what let MLB report `0 cards` on a slate of
            # 15. This branch runs before the 0-card one so the timeout gets
            # named as the cause, and it fails even for an out-of-season sport:
            # "nothing to show" should resolve fast, so a 20s timeout there is
            # itself the anomaly.
            # A render still growing when we measured it makes every number on
            # the row provisional -- MLB was measured at 74% of its content
            # under the old fixed settle. Fail rather than footnote it.
            if measured.get("renderSettled") is False:
                issues.append(
                    f"RENDER NEVER SETTLED in {SETTLE_MAX_MS // 1000}s -- "
                    "every figure on this row was taken mid-render"
                )
                ok = False
            # A settle can be wrong in the other direction too: still, because
            # the render had not started. That reading is indistinguishable
            # from a finished one ON ITS OWN -- so it fails only when the other
            # width contradicts it, which is the case the old rule shipped.
            if contradicted == label:
                other = next(lbl for lbl in VIEWPORTS if lbl != label)
                units = measured.get("contentUnits") or {}
                other_units = ((sport_report.get(other) or {}).get("contentUnits")) or {}
                issues.append(
                    f"CONTENT CONTRADICTED by {other} "
                    f"({units.get('min')}-{units.get('max')} vs "
                    f"{other_units.get('min')}-{other_units.get('max')} pairs/card) "
                    "and this row's settle never saw the DOM change -- measured "
                    "before the slate finished arriving, NOT a uniform slate"
                )
                ok = False
            elif measured.get("renderSettled") and measured.get("settleSawChange") is False:
                rests_on_absence.append(f"{sport} {label}")
            if measured.get("cardWaitTimedOut"):
                issues.append(
                    f"NO CARD ATTACHED in {CARD_WAIT_MS // 1000}s -- render did not "
                    "finish; this is NOT a 0-card slate"
                )
                ok = False
            elif not cards:
                issues.append("0 cards served -- NOT a pass, re-measure in season")
                if sport not in out_of_season:
                    ok = False
            lines.append(
                f"{sport:8} {label:8} {cards:>5} {str(overflow) + 'px':>9} {str(spread) + 'px':>7}  "
                + ("; ".join(issues) if issues else "ok")
            )
    # Stated once, as a footer, rather than as a note on every row. For the
    # seven sports that render server-side and are complete at `load`, a still
    # DOM is the correct state and flagging it per row would train readers to
    # skip the flag. What the footer preserves is that the settle on these rows
    # is an assumption, not a measurement -- so a surprising content or height
    # figure here has a known candidate cause.
    if rests_on_absence:
        lines.append(
            f"settle rests on absence (DOM never changed while watched, "
            f"so 'finished' and 'not started' look alike): {', '.join(rests_on_absence)}"
        )
    return lines, ok


class LocalServer(AbstractContextManager["LocalServer"]):
    def __init__(self) -> None:
        self._server: BaseWSGIServer | None = None
        self._thread: threading.Thread | None = None
        self.base_url = ""

    def __enter__(self) -> "LocalServer":
        app = create_app()
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            sock.listen(1)
            port = int(sock.getsockname()[1])
        self._server = make_server("127.0.0.1", port, app, request_handler=_SilentRequestHandler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        self.base_url = f"http://127.0.0.1:{port}"
        return self

    def __exit__(self, exc_type, exc, exc_tb) -> None:
        if self._server is not None:
            self._server.shutdown()
        if self._thread is not None:
            self._thread.join(timeout=5)


class _SilentRequestHandler(WSGIRequestHandler):
    def log(self, type: str, message: str, *args) -> None:  # noqa: A003 - Werkzeug API name.
        return


# Metrics that are a property of the CODE. A deploy can move them; an evening
# of games cannot. If one of these differs between two runs and nothing shipped
# to the card surface, the harness is measuring something it does not
# understand -- that is the finding, not the number.
STABLE_METRICS = ("overflowPx", "tabsWithoutPanel", "panelsWithoutTab", "unstyledLinks")

# Metrics that legitimately move with the slate. Printed for context, never
# failed. Established the hard way: card-height spread read 796 / 1716 / 1583 /
# 1125 px across one evening with no code change.
SLATE_METRICS = ("cards", "cardHeightSpread", "cardHeightSpreadWithinState", "contentUnits")

# Metrics being COLLECTED, not yet judged. `identicalContentSpread` ought to be
# code-driven -- two cards with the same data should be the same height whatever
# the slate does -- but that is a belief, not a measurement: as of 2026-08-16 it
# has ONE reading per width (116px desktop, 81px mobile). Until several runs say
# otherwise it is printed as context and CANNOT fail a run, because promoting it
# to STABLE_METRICS on one reading would be exactly the mistake this file keeps
# recording. The decision rule was written down in advance: if it moves more than
# ~2x across runs with no card-surface deploy, it is slate-driven and cannot be
# baselined.
WATCH_METRICS = ("identicalContentSpread",)

# Sports whose `identicalContentSpread` has EARNED a baseline and now fails on
# drift. Opt-in BY NAME with a reason, the same shape as OUT_OF_SEASON and
# NUMERIC_CLASS_EXEMPT -- a blanket promotion would take mlb with it, and mlb
# moved on every reading.
#
# Evidence (2026-08-16, 7+ production runs, both widths, across both the
# largest-group and worst-group statistics): nfl 14/50 and ncaaf 45/53 were
# bit-identical every single time. mlb was not. The difference is not the sport,
# it is that these slates are STATIC -- units 3-3 and 16-16, a single "Week 1"
# state, no games in progress -- while mlb enriches continuously during a live
# slate.
#
# THE LIMIT THIS CARRIES: when these games kick off, the slates stop being
# static and this check will fire on a slate change rather than a layout
# regression. That is designed for rather than ignored -- the tie spread is
# per-STATE, so the comparison below only fires when the state matches on both
# sides, and a state change is reported as not-comparable instead. The failure
# text names the slate as the first thing to check.
TIE_SPREAD_BASELINED = frozenset({"nfl", "ncaaf"})


def _cmp_value(v):
    if isinstance(v, list):
        return len(v)
    if isinstance(v, dict):
        # `worstGroupPx` FIRST, ahead of `spreadPx`: reports written during the
        # brief largest-group window carry `spreadPx` meaning something else,
        # and diffing those against a current report would compare two
        # different quantities and call the difference movement. Both eras
        # carry `worstGroupPx`, and in both it means the same thing.
        #
        # The rest of the chain: `identicalContentSpread` has no `spread`/`max`,
        # and without a branch that matches it the comparison reads None vs None
        # and prints "unchanged" forever -- a watch metric that can never move is
        # not a watch.
        return v.get(
            "worstGroupPx",
            v.get("spreadPx", v.get("floorPx", v.get("spread", v.get("max")))),
        )
    return v


def compare(baseline: dict[str, Any], current: dict[str, Any]) -> tuple[list[str], bool]:
    """Diff two reports, separating code-driven drift from slate movement."""
    lines = ["comparison vs baseline", "-" * 60]
    ok = True
    for sport, cur_sport in current.get("sports", {}).items():
        base_sport = (baseline.get("sports") or {}).get(sport) or {}
        for width in VIEWPORTS:
            cur = cur_sport.get(width) or {}
            base = base_sport.get(width) or {}
            if not base:
                lines.append(f"{sport:8} {width:8} NEW -- not in baseline, nothing to compare")
                continue
            # A row that ERRORED carries no metrics at all, so every stable
            # metric reads `None` and the diff below would announce
            # "CODE-DRIVEN DRIFT: overflowPx 0 -> None" -- a false alarm of
            # exactly the class this comparison exists to avoid. Seen live
            # 2026-08-16: soccer mobile hit a 30s `page.goto` timeout and was
            # reported as drift on four metrics at once. A failed measurement
            # is not a measurement of a change.
            if "error" in cur or "error" in base:
                side = "current" if "error" in cur else "baseline"
                detail = str((cur if "error" in cur else base)["error"])[:50]
                lines.append(
                    f"{sport:8} {width:8} SKIPPED -- the {side} row ERRORED "
                    f"({detail}), which is not a comparison"
                )
                ok = False
                continue
            if (cur.get("httpStatus") or 0) >= 400 or (base.get("httpStatus") or 0) >= 400:
                lines.append(f"{sport:8} {width:8} SKIPPED -- an HTTP error on one side is not a comparison")
                ok = False
                continue
            drift = []
            for key in STABLE_METRICS:
                b, c = _cmp_value(base.get(key)), _cmp_value(cur.get(key))
                if b != c:
                    drift.append(f"{key} {b} -> {c}")
            moved = []
            for key in SLATE_METRICS:
                b, c = _cmp_value(base.get(key)), _cmp_value(cur.get(key))
                if b != c:
                    moved.append(f"{key} {b} -> {c}")
            if drift:
                ok = False
                lines.append(f"{sport:8} {width:8} CODE-DRIVEN DRIFT: " + "; ".join(drift))
            else:
                lines.append(f"{sport:8} {width:8} stable metrics unchanged")
            if moved:
                lines.append(f"{'':17} slate moved: " + "; ".join(moved))
            if sport in TIE_SPREAD_BASELINED:
                b_tie = base.get("identicalContentSpread") or {}
                c_tie = cur.get("identicalContentSpread") or {}
                b_val, c_val = _cmp_value(b_tie), _cmp_value(c_tie)
                if b_val is None and c_val is None:
                    pass
                elif b_val is None:
                    # A baseline predating the field cannot be drifted from.
                    # Reported, not failed -- this is absence on the BASELINE
                    # side, and failing here would just punish an old file.
                    lines.append(
                        f"{'':17} identicalContentSpread {c_val}px NOT COMPARED "
                        "-- the baseline predates this metric; re-baseline to arm it"
                    )
                elif c_val is None:
                    # Absence on the CURRENT side is different in kind: the
                    # measurement stopped happening, and absence is never a pass.
                    lines.append(
                        f"{'':17} identicalContentSpread VANISHED (baseline {b_val}px, "
                        "now unmeasured) -- no two cards tie, so the check did NOT run"
                    )
                    ok = False
                elif b_tie.get("state") != c_tie.get("state"):
                    # Per-state metric: two states are two quantities.
                    lines.append(
                        f"{'':17} identicalContentSpread NOT COMPARABLE -- state moved "
                        f"{b_tie.get('state')!r} -> {c_tie.get('state')!r} "
                        f"({b_val}px -> {c_val}px)"
                    )
                elif b_val != c_val:
                    lines.append(
                        f"{'':17} identicalContentSpread DRIFT {b_val}px -> {c_val}px "
                        f"in {c_tie.get('state')!r} -- cards with the SAME data changed "
                        "height. Check whether the slate went live before reading this "
                        "as a layout regression"
                    )
                    ok = False
                else:
                    lines.append(
                        f"{'':17} identicalContentSpread {c_val}px unchanged (baselined)"
                    )
            else:
                # Collected, not judged. Printed even when unchanged, because the
                # point of this line is to build a series -- a metric only shown
                # when it moves can never be shown to be stable.
                for key in WATCH_METRICS:
                    b, c = _cmp_value(base.get(key)), _cmp_value(cur.get(key))
                    if b is None and c is None:
                        continue
                    verdict = "unchanged" if b == c else f"{b} -> {c}"
                    lines.append(f"{'':17} watch (stability unknown): {key} {verdict}")
    return lines, ok


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default=None, help="Probe a running server instead of serving in-process.")
    parser.add_argument("--sports", default=",".join(SPORT_ROUTES), help="Comma-separated sport slugs.")
    parser.add_argument("--timeout-ms", type=int, default=30000)
    parser.add_argument(
        "--expect-cards",
        default="",
        help=f"Comma-separated sports that MUST serve cards even though they are in {sorted(OUT_OF_SEASON)}.",
    )
    parser.add_argument("--json", action="store_true", help="Print the full report as JSON.")
    parser.add_argument("--write", default=None, help="Write the full JSON report to this path.")
    parser.add_argument(
        "--compare",
        default=None,
        help="Diff this run against a baseline JSON. Code-driven drift fails; slate movement is printed.",
    )
    args = parser.parse_args(argv)

    sports = [s.strip() for s in args.sports.split(",") if s.strip()]
    unknown = [s for s in sports if s not in SPORT_ROUTES]
    if unknown:
        parser.error(f"unknown sport(s): {', '.join(unknown)}")

    if args.base_url:
        report = probe(args.base_url.rstrip("/"), sports, args.timeout_ms)
    else:
        with LocalServer() as server:
            report = probe(server.base_url, sports, args.timeout_ms)

    expect_cards = {s.strip() for s in args.expect_cards.split(",") if s.strip()}
    report["outOfSeason"] = sorted(OUT_OF_SEASON - expect_cards)
    lines, ok = summarize(report)
    report["ok"] = ok
    if args.write:
        path = Path(args.write)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    if args.compare:
        baseline_path = Path(args.compare)
        if not baseline_path.exists():
            # A missing baseline is not a clean comparison, and this file's
            # whole discipline is that absent must not read as fine.
            print(f"BASELINE NOT FOUND: {baseline_path} -- nothing was compared")
            return 1
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
        cmp_lines, cmp_ok = compare(baseline, report)
        lines = lines + ["", *cmp_lines]
        ok = ok and cmp_ok

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print("\n".join(lines))
        print("\nOK" if ok else "\nFAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
