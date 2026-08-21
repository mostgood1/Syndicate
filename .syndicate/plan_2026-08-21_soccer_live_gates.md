# Soccer live board gates 2 & 3 — design, 2026-08-21

Lane `soccer-board-mlb-parity`. Gate 1 (live game state) is BUILT and on
`origin/main`; this file covers the two that remain. Target: build against
tonight's live window, kickoffs 18:45Z (Marseille v Strasbourg, Standard Liege
v RAAL La Louvière) and 19:00Z (Arsenal v Coventry, Real Betis v Real
Sociedad).

## What soccer actually publishes (checked, not assumed)

`scripts/poll_soccer_live_state.py` writes, per league, to
`soccer_source/<league>/api/live_state/live_state_<date>.json`. The `games` map
holds **matches IN PLAY only** (a finished match lives in `match_box`; that
asymmetry is what gate 1 had to respect). Each `games[event_id]` carries:

- `projection` — `LiveMatchProjection.to_dict()`:
  `simulations`, `home_win_probability`, `draw_probability`,
  `away_win_probability`, `projected_final_home_goals` / `_away_goals` /
  `_total`, `over_2_5_probability`, `both_teams_scored_probability`,
  `projected_home_corners` / `_away_corners` / `_total_corners`,
  `home_red_card_applied`, `away_red_card_applied`
- `live_player_props` — top 12 rows by projected final shots
- `goal_windows`, plus live score, clock, shots, SOT, corners, red cards

**Soccer publishes `simulations` (400 on today's ligue_1 artifact).** That is
the n `prob_std_err` needs, so soccer can get a PRICED live edge rather than
WNBA's "publish, refuse to price" posture — WNBA has no `simsRun` and is
therefore withheld by `REASON_UNUSABLE_SIMS`. Do NOT invent an n for any sport;
soccer simply has a real one.

## RETRACTED: "the live pricer mis-frames three-way h2h"

**This section previously claimed `attach_live_gamelines` would mis-price soccer
draw/away rows because it prices every h2h row with
`model_prob=hit["home_win_prob"]`. That claim was WRONG and is retracted.**

Checked against the served Layer 2 payload rather than reasoned from the call
site: a row with `side: "draw"` carries a projection block stamped
`side: "home"`, `model_prob_over 0.79`, `market_fair_prob_over 0.7916`. **Both
terms are home-framed, deliberately and consistently** --
`soccer_projections._price_against_market` documents exactly this: the model
emits an unconditional P(home) over the three-way space and the fair is
home/(home+draw+away) over the same space, so the subtraction is valid. The
live pricer inherits that framing unchanged. **No per-side selection is needed
in gate 3.** `side_probabilities` is still published by the adapter, because the
CONSUMER below turned out to need it.

Retraction is not innocence, and looking for the real version of the defect
found one -- in the PREGAME board, not the live path:

## REAL BUG FOUND AND FIXED: `_model_edge_for` negates a three-way edge

`layer2_board.py:840` did:

    # The projection is stated from one side; flip it for the other.
    if projected_side != side: return -edge

`-edge_home` is the other side's edge only when there IS exactly one other side.
With a draw leg the three edges sum to zero but are otherwise unrelated, so
negating answers a question about a different outcome.

**MEASURED, served shortlist 2026-08-21, soccer h2h, 49 rows -- 23 away and 13
draw take the branch:**

    RC Lens v Auxerre, away:   published +1.63   TRUE -1.65   SIGN INVERTED
    Orlando v Real Salt Lake:  published +9.47   TRUE +6.83
    Arsenal v Coventry, draw:  published +0.16   TRUE +0.18
    Charlotte v DC United:     published -5.14   TRUE -5.25

Nearly right on a heavy favourite, inverted on a close one -- the worst
available failure mode. `model_edge_pct` feeds `blended_score` (ranking) and
`sim_view`, so RC Lens ranked and rendered as a side the model LIKES while the
model disliked it. `_model_edge_for`'s own docstring says the bound exists so a
row "cannot invert one"; the negation was doing the inverting.

Fixed by pricing the side DIRECTLY from the three-way vector against that
side's own fair probability, both in the unconditional space. Two-way markets
(MLB/WNBA) keep the identity and are bit-for-bit unchanged. A three-way row
whose side cannot be priced is DROPPED, not negated -- falling back to the
identity is how this bug would have survived its own fix.

## Totals: one analytic line, not a distribution

The live projection carries `over_2_5_probability` and **no scoreline
distribution** — unlike the PREGAME artifact, where `scoreline_probabilities`
let today's totals fix price any line. So live totals are the WNBA-shaped case:
one analytic probability at one line. Use `price_analytic_line_market` with
line 2.5 and refuse every other line by name. Do NOT reuse the pregame
`_total_prob_from_scorelines` here — that distribution describes the match from
kickoff, not from the current score, and applying it live would publish a
pregame answer as a live one.

Spreads/handicaps: the live projection has means (`projected_final_home_goals`
minus away) and no margin distribution, so spreads are `REASON_TOTALS_MEAN`'s
sibling — withheld by name, not answered from a mean.

## Gate 2 (live player props)

`live_player_props` is capped at **12 rows per match** by the poller
(`sorted(...)[:12]`). That cap is invisible downstream and will read as
"no live projection" for every other player. Either raise it at the producer or
report the cap in the coverage block — a silent truncation reads as absence,
which is the `no silent caps` rule.

## Build order

1. Soccer adapter for `build_live_gameline_index` — reads the per-league
   live_state files (same loader shape as gate 1's `_soccer_live_state_games`),
   keyed `(away, home)` on full names. Gate 1 proved the names join exactly:
   ESPN "Rayo Vallecano"/"Alavés" matched the OddsAPI grid on 286 rows.
2. ~~Per-side model probability selection~~ NOT NEEDED in the live path -- see
   the retraction above. Done instead, in the PREGAME path: `_model_edge_for`
   now prices a three-way side directly rather than negating the home edge.
3. Analytic totals at 2.5; every other line refused by name.
4. Add `soccer` to `_LIVE_GAMELINE_SPORTS` / gate 2's sport check LAST, so the
   reachability test (`off != on`) is meaningful.

## Verification, which is the point of doing this tonight

Gate 1 shipped with its live-clock path unwitnessed in production — every
reading available today was a FINISHED match. Tonight there is a real live
window (~18:45–20:45Z). For each gate the reading that counts:

- `/api/board/book-grid?sport=soccer` → `live_gamelines.supported: true` and
  `rows_live_gameline_edged > 0` **while a match is in play**, with
  `withheld_by_reason` enumerated rather than a bare zero.
- A live h2h row's `live_gameline.model_prob` must equal that match's
  `home_win_probability` -- home-framed, matching `market_fair_prob_over`. The
  thing to check by VALUE is that it moved off the pregame number: a live
  projection that equals the pregame one has not been re-simulated.
- On the pregame side, `model_edge_pct` for an away/draw row must equal
  `model(side) - fair(side)`, not `-edge_home`. RC Lens v Auxerre is the
  regression case: away must read negative.
- `rows_live_projected > 0` for gate 2, against the 12-row cap stated.
