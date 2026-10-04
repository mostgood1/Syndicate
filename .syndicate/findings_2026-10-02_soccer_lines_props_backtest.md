# Soccer game lines + player props — consolidated backtest and board gate list

**2026-10-02, lane `soccer-lines-props-backtest`, session 43e4d5fe.** Measurement only: no deploy, no
board change. Template: NHL props lane (`nhl-player-props-projection`, deploys.md 2026-10-02 21:38Z,
`0f25d513`): a market earns a board probability / edge only if it beats a naive as-of baseline AND the
de-vigged book. Numbers: `reports/soccer_backtest/lines_props_backtest_2026-10-02.{json,md}`.

> **CORRECTION 2026-10-03 -- USER DECISION: every line is judged on its own; NO market is removed.**
> The "gate list" below was written as market-wide withholding (the NHL template's form). That is
> withdrawn. The numbers stand as the ACCURACY DIAGNOSIS and as inputs to per-line weighting; nothing in
> this file is a reason to switch a market off. What was done instead (lane
> `soccer-skill-registry-line-weighting`):
> - **Registry re-measured** (`02a76fb7`): soccer pregame totals PARITY (n 194) -> LOSES (n 492); h2h
>   n 671 and spreads n 458 re-measured; `totals_alt` / `spreads_alt` / `h2h_3_way` aliased. This only
>   moves each row's Layer 2 RANKING multiplier (totals 1.0 -> 0.93, h2h 0.877 -> 0.857, spreads 0.835).
> - **Per-line edge weight FITTED** (`audit_games.py --extra`): edge = w x (model - de-vigged fair), w fitted
>   on 2026-27 = **0.000** for 1X2 [0, 0.066], totals [0, 0.232], AH [0, 0.287]. Held until a model fix
>   (user decision), so the model can earn weight back before the mechanism ships.
> - **1X2 favourite calibration FALSIFIED** (post-hoc power sharpening, chronological): fitted T = 0.90
>   (train) / 0.86 [0.68, 1.08] -- the model is slightly OVER-confident overall; held-out Brier -0.0011
>   [-0.0039, +0.0018] vs raw, still +0.030 [+0.012, +0.048] vs the book, refit w still 0. Held-out
>   favourites: raw 0.618, sharpened 0.592, book 0.722, actual 0.757. The favourite gap is TEAM-STRENGTH
>   identity, not dispersion (matches 2025-26's temperature ~1.0). `C:/tmp/soccer-lpb/calib_1x2.py`.
> - **Defect 4 below is CORRECTED**: after the 09-16 squad rebuild, unlisted players take **4.0%** of real
>   shots (38.5% before, 119 vs 185 pre-kickoff matches); the remaining 29% unbound model rows are listed
>   players not in the matchday squad, not stale squads.

## Bottom line

**No soccer market — game line or player prop, pregame or live — earns a board probability or edge.**
Every game-line market loses to (or ties) the de-vigged close; every prop market is priced one-sided
(OVER only), so "beats the de-vigged book" cannot be certified, and flat ROI on the model's EV>0 side is
negative in all four projected prop markets. The difference from NHL: the soccer prop MEAN is not
worse than the player's own average — anytime scorer (post-fix) beats a shrunk own-average on both
Brier and log loss, SOT is roughly even, shots is worse. So: **means stay on the board, probabilities
and edges come off.** The board today contradicts this in six places (1X2 and totals edges still rank; totals is registered "parity" on a stale sample; the BTTS card prints an edge; first/last scorer show an ungraded probability; two-sided prop rows can carry an edge) -- see the gate table.

## Data — what every number rests on (production, not the git mirror)

Render has been billing-suspended since 2026-09-30 06:37:51Z; its disk is unreachable and was never
mirrored for soccer (git holds **150** `data/soccer_source` files, almost none 2026-27 production). The
2026-27 production record survives only in session caches pulled from Render before the cutover, plus
the local fleet since 09-30:

| family | source | dates | window |
|---|---|---|---|
| production recs (latest build) | Render export cached 09-15 (session abacd435) + fleet 09-30 | 49 | 07-22..10-09 |
| production recs (PRE-KICKOFF build) | 09-02 snapshot (150 files) + forward-grade freeze 09-16..09-27 + fleet freeze 09-30 | 26 | 07-22..10-09 |
| ESPN finals (score, team + player box) | ESPN summary API, fetched this lane (712 completed) | 48 | 07-22..09-30 |
| prop odds (`props/<date>.csv`, OVER only, 8 US books) | Render export (09-15 + forward-grade cache to 09-27) + fleet | 61 | 07-19..10-03 |
| game_markets (BTTS, corners main line; last PRE-KICKOFF capture) | same | 39 | 08-22..10-03 |
| 1X2 / O/U 2.5 / AH closes | football-data.co.uk 2026-27, fetched 10-02 (Europe ends 09-20) | 54 | 07-17..10-02 |
| 2025-26 arm | committed `history/` + `team_history/` (git-tracked, origin/main) + football-data 2025-26 closes | — | 2025-08-01..2026-05 |

- **Intersection of all six 2026-27 families: 15 dates** (09-02..09-27). Match level: **712** matches
  joined latest-build x outcome; **304** joined PRE-KICKOFF build x outcome (all prop results rest on these).
- **Production predictions for 09-21..09-29 are LOST** (Render-only, never mirrored, not in any cache);
  football-data's European closes also stop at 09-20. Game lines therefore extend the 09-15 audit by
  one weekend (07-22..09-20, MLS to 09-30), not to today.
- The cached `recommendations_<date>.json` are post-kickoff REBUILDS (H7: 1X2 not materially leaky —
  re-measured here: pre-kickoff 0.6243 vs final 0.6230 vs market 0.5968, n=165). Player means move more
  (|Δ shots| 0.071), so **props use only builds generated before kickoff** (`load_recs(prekickoff_only=True)`).

## 2026-27 pregame game lines (n = matches; CI = match bootstrap 95%; market = de-vigged football-data close, MLS Pinnacle)

| market | n | window | model vs NAIVE as-of | model vs BOOK | 09-15 audit | status |
|---|---|---|---|---|---|---|
| 1X2 (3-way Brier) | 671 | 07-22..09-30 | **beats** last-season league rates −0.0320 [−0.0494, −0.0141] (book beats it by −0.0605) | **LOSES +0.0285 [+0.0169, +0.0411]**; LL +0.0435 | +0.0276 (n 543) | settled, extended: same |
| draw (two-way) | 671 | same | no diff +0.0002 [−0.0026, +0.0031] | no diff +0.0017 [−0.0008, +0.0042]; LL +0.0051 [−0.0020, +0.0120] | untested | **new**: no skill |
| Asian handicap (close main line) | 458 | same | — | **LOSES +0.0208 [+0.0082, +0.0340]** | +0.0178 (n 368) | settled, extended: same |
| O/U 2.5 | 492 | Europe to 09-20 | — | **LOSES +0.0095 [+0.0032, +0.0157]** | +0.0081 (n 394) | settled, extended: same |
| total goals (mean, MAE) | 712 / 492 | 07-22..09-30 | no diff −0.0207 [−0.0472, +0.0063] vs last-season league mean | **worse than book mean +0.0521 [+0.0233, +0.0810]** | bias only | **new** |
| BTTS | 487 | 08-22..09-30 | — | **LOSES +0.0060 [+0.0006, +0.0116]** (vs captured price, median 14.2 h before KO) | parity +0.0039 | **stale → now loses** |
| team goals | 492 | Europe | — | LOSES LL +0.0430 [+0.0251, +0.0620] | +0.0447 | settled |
| corners match total (sim, pre-09-17) | 444 | to 09-17 | no diff +0.030 [−0.007, +0.067] vs last-season league mean; r 0.04 | main line Brier +0.0089 [−0.0002, +0.0185] (n 344) | no information | settled |
| corners match total (estimator `05b808cc`, from 09-17) | 89 | 09-17..09-30 | no diff −0.065 [−0.175, +0.036] | — (H27 forward: 87/150, grades 2026-11-15) | — | **under-powered; H27 owns it** |
| cards (To Receive Card / Red Card) | — | — | priced (20,770 / 17,970 offer rows) but **not projected** | — | — | untestable |
| first / last scorer | — | — | priced (202,121 / 84,373) but **not projected** | — | — | untestable |

Per league (1X2 Brier vs book): significant LOSSES in championship, ligue_1, belgian_pro_league, mls;
no league wins (EPL −0.0219 [−0.0667, +0.0237] is the best). Ten leagues at 95% → about one chance cell.

## 2025-26 (last season) — reported separately

| market | result | n | benchmark | source |
|---|---|---|---|---|
| 1X2 | model LOSES in 8 of 9 leagues (Belgian the exception); dispersion falsified, temperature ≈ 1.0 | 1,112 (limit 120/league), 2023-07..2026-05 history incl. 2025-26 | **PRE-close** `Avg*` (labelled "closing" there — defect 2) | lanes_history 08-15; `backtest_soccer_h2h_calibration.py` |
| O/U 2.5, total goals, draw, true-close 1X2 | **NOT RE-RUN — owed.** The harness is extended and smoke-tested (10 EPL 2025-26 matches: all fields populated, 10/10 true-close joins), but the full run (~3,300 matches of real sim) could not progress on this host: 100% CPU, 1.3 GB free of 32 GB, the process paging at 0.3 CPU-s per 30 s while the production fleet shares the machine. Stopped deliberately after ~50 min rather than add memory pressure to production. | — | — | command below |
| AH, BTTS, corners, props | untestable for 2025-26 from what is retained: no AH/BTTS/corners/prop prices captured last season; no as-of player substrate | — | — | — |

- **STATUS 2026-10-03 ~21:30Z -- the 03:42Z re-run did NOT finish; it is SUPERSEDED, not complete.** First launch died in 3 s (`no committed history`: a `git rebase` of the sparse worktree deleted the materialised `data/` history files); the relaunch was stopped when the work moved into the H37 chain (lane `soccer-1x2-ratings-xg-source`). The 2025-26 O/U 2.5 / total-goals / true-close numbers for the four goals-rated leagues (championship, eredivisie, primeira_liga, belgian_pro_league) come from H37 **arm A** -- the same harness and production ratings, same per-match fields -- RUNNING (eredivisie 158 matches dumped at 21:2xZ), resumable. The five rest-of-leagues steps are DEFERRED by user decision (2026-10-03) until H37 is scored. No 2025-26 O/U Brier exists yet; nothing here is a result.

- **RESULT 2026-10-04 -- 2025-26, the four goals-rated leagues (championship, eredivisie, primeira_liga, belgian_pro_league), n = 1,333, from H37 arm A (production ratings, leak-free per-day as-of, 300 sims), vs football-data TRUE close (AvgC*):** 1X2 Brier **+0.0267 [+0.0159, +0.0371] LOSES** (vs pre-close Avg +0.0254); O/U 2.5 Brier **+0.0054 [+0.0019, +0.0090] LOSES** (log loss +0.0112 [+0.0039, +0.0187]); total-goals MAE vs the book's goal mean **+0.0187 [+0.0047, +0.0339] worse**, vs the as-of league mean no diff (-0.0056 [-0.0197, +0.0085]); draw no diff (+0.0017 [-0.0002, +0.0037]). Same picture as 2026-27. (A two-league interim -- eredivisie + primeira, 553 -- read parity; championship and belgian carry the loss.) STILL OWED: the five xG-rated leagues (deferred).

The owed run cannot change the gate list: every 2026-27 market already fails the book clause. It would
change only whether 2025-26 agrees.

    py -3 scripts/backtest_soccer_h2h_calibration.py --all --since 2025-08-01 --fd-close-dir <football-data 2526 CSVs> --dump-matches <jsonl>
    py -3 C:/tmp/soccer-lpb/analyze_2526.py <jsonl>

## 2026-27 player props — vs the player's OWN as-of average (the NHL baseline)

Population: model players bound one-to-one to an ESPN box-score player who APPEARED (books void
non-appearances), latest build generated BEFORE kickoff. **304 matches, 6,789 appeared player-rows**
(funnel: 12,897 model rows → 4,724 not in the box score (stale squads, as 09-15 found) → 1,384 did not
appear → 6,789); 4,559 rows have ≥3 prior appearances (the baseline's minimum). Model = the
`*_if_playing` mean (what the board prices since fix #2). Baselines: **a** = own per-appearance mean
over prior box scores; **b** = last 5; **c** = a shrunk to the league as-of mean with 3 pseudo-apps (the
fair one early in a season). Post-fix = builds after 09-17 (shots/SOT/anytime: fixes #2/#3) and 09-19
(assists: H33). League split: only championship and MLS reach 30 pre-kickoff matches; the other eight
are pooled.

Point accuracy (MAE; anytime = Brier), **post-fix**, n = 3,003 rows / 119 matches (assists 2,736 / 108), 09-17..09-30:

| market | mean actual / model / own-avg | Δ vs a | Δ vs c (shrunk) | verdict vs c |
|---|---|---|---|---|
| shots | 0.978 / 0.810 / 0.944 | −0.0128 [−0.0330, +0.0078] | −0.0329 [−0.0501, −0.0153] | MAE "beats" — but see lines: MAE rewards the model's low bias |
| SOT | 0.327 / 0.277 / 0.326 | −0.0097 [−0.0206, +0.0011] | (in json) | — |
| anytime scorer | 0.092 / 0.086 / 0.094 | −0.0129 [−0.0169, −0.0091] | −0.0039 [−0.0064, −0.0014] | **BEATS** |
| assists | 0.084 / 0.069 / 0.076 | −0.0013 [−0.0069, +0.0043] | −0.0030 [−0.0067, +0.0006] | no diff |

Probability at standard lines (proper scores; Poisson from the mean for counts), **post-fix**, vs shrunk own-average c:

| market @ line | base rate | ΔBrier model − c [CI] | ΔLogLoss model − c [CI] | verdict |
|---|---|---|---|---|
| shots 0.5 | 0.513 | −0.0012 [−0.0080, +0.0059] | **+0.0459 [+0.0126, +0.0831]** | worse (LL) |
| shots 1.5 | 0.255 | **+0.0068 [+0.0020, +0.0117]** | **+0.0357 [+0.0173, +0.0551]** | **worse** |
| shots 2.5 | 0.112 | +0.0020 [−0.0009, +0.0050] | +0.0066 [−0.0060, +0.0196] | no diff |
| SOT 0.5 | 0.245 | **−0.0048 [−0.0089, −0.0007]** | −0.0012 [−0.0192, +0.0203] | marginal (Brier only) |
| SOT 1.5 | 0.059 | −0.0013 [−0.0029, +0.0002] | −0.0066 [−0.0165, +0.0033] | no diff |
| anytime 0.5 | 0.092 | **−0.0028 [−0.0051, −0.0006]** | **−0.0169 [−0.0279, −0.0059]** | **beats** |
| assists 0.5 | 0.077 | −0.0009 [−0.0024, +0.0008] | −0.0075 [−0.0176, +0.0025] | no diff |

All-versions pooled (304 matches) agrees in direction; PRE-fix anytime and assists were WORSE than c on
log loss (+0.0572, +0.0664) — the 09-16/09-18 fixes are what moved them. Against the raw own-average **a**
the model looks better everywhere (e.g. SOT 0.5 −0.0145), because a 3–6 appearance raw average is a
poor probability; **c is the honest naive baseline, and it is the one used for the gate.** ~35 cells were
tested, so one or two "beats" are expected by chance; anytime is the only market that wins on both scores.

Vs the book (all versions, appeared + baseline present; **50 of 168,846 price rows carry an UNDER**, so
no de-vig exists — compared to the raw implied probability WITH vig, and flat 1u at the best price
when model p > implied):

| market | player-lines / matches | hit | mean p model / implied | ROI model EV>0 [CI] | ROI own-avg EV>0 [CI] |
|---|---|---|---|---|---|
| shots | 9,569 / 143 | 0.252 | 0.207 / 0.419 | **−22.4% [−40.6, −1.7]** (199 bets) | −24.0% [−36.1, −12.3] |
| SOT | 5,182 / 143 | 0.168 | 0.141 / 0.274 | −7.1% [−41.3, +31.1] (210) | −23.4% [−37.4, −8.7] |
| anytime | 2,652 / 144 | 0.097 | 0.107 / 0.156 | −29.5% [−53.7, +0.8] (487) | −32.6% [−49.4, −13.7] |
| assists | 2,048 / 115 | 0.082 | 0.083 / 0.181 | −8.4% [−47.0, +34.8] (93) | −32.3% [−51.7, −10.4] |

The model's Brier "beats" the implied probability only because the implied carries a 40–100% overround
on alternate overs. No EV>0 rule is positive; this matches the 09-15 audit and W2/W3 (forward, 11-15).

## Live markets (separate; from the existing graders, not re-run)

| market | result | n | source |
|---|---|---|---|
| live totals | re-sim beats frozen score early, LOSES to frozen at 75'/85'; no price comparison | 70 (2026-27), 160–200 (2025-26) | `euro_holdout_ON/OFF`, `live_totals_2026-08-21_lastseason*` |
| live goals (running xG) | H30 FALSIFIED −0.0134 [−0.0403, +0.0125] | 259 | state_soccer H30 |
| live corners | H29 FALSIFIED (pregame pace beats re-sim); H32 FALSIFIED 09-28 (published ≈ sim, −0.0172 [−0.093, +0.060]); H36 vs in-play book WATCHING 26/150, may end INSUFFICIENT | 320 / 107 / 26 | lane `soccer-live-corners-book-test` |
| live 1X2 / draw / BTTS signals | momentum etc. add ≤0.01 AUC over clock+score; no price | 151k samples | `outcome_markets_test.json` |
| live soccer game lines on the fleet | crashed every window until 09-30; no in-play reading yet (`#693`) | 0 | state_soccer 10-01 |

None has been graded against an in-play price with a CI excluding zero → no live market earns an edge.

## Consolidation — market x status

| market | season | last graded | window then → now | status | source |
|---|---|---|---|---|---|
| 1X2 (+ legs) | 2026-27 | 09-15 audit (n 543) | 07-22..09-14 → 09-20 (n 671) | **settled** (re-run: same verdict) | `audit_games.py` |
| 1X2 | 2025-26 | 08-15 h2h calibration (1,112, limit 120/league, PRE-close benchmark) | → full season, true close | re-run this lane (see 2025-26) | `backtest_soccer_h2h_calibration.py` |
| draw (two-way) | 2026-27 | never standalone | n 671 | **new** — no skill | `audit_games.py --extra` |
| AH | 2026-27 | 09-15 (n 368) | → n 458 | **settled** | `audit_games.py` |
| O/U 2.5 | 2026-27 | 09-15 (n 394) | → n 492 | **settled** | `audit_games.py` |
| O/U 2.5, total goals | 2025-26 | never (pregame) | full season | **new** (see 2025-26) | `backtest_soccer_h2h_calibration.py` |
| total goals vs naive | 2026-27 | never | n 712 | **new** — no skill | `audit_games.py --extra` |
| BTTS | 2026-27 | 09-15 parity (n 359) | → n 487, now LOSES | **was stale; re-graded** | `audit_games.py` |
| team goals | 2026-27 | 09-15 | → n 492 | settled | `audit_games.py` |
| corners total (sim) | 2026-27 | 09-15 r 0.02 | → n 444 | settled (model replaced 09-17) | `audit_games.py --extra` |
| corners total (estimator) | 2026-27 | H26 study (held-out 554); H27 forward 87/150 | n 89 here | **under-powered; H27 grades 11-15** | `forward_grade.py` |
| cards, first/last scorer | — | never | priced, NOT projected (first/last: board derives a race probability) | **untested** — no model to grade (first/last: no box-score order captured) | — |
| shots / SOT / anytime props | 2026-27 | 09-15 vs constant + ROI (pre-fix) | → vs own as-of average, pre-kickoff builds, post-fix arm | **was untested vs the NHL baseline; graded here** | `audit_props.py --asof` |
| assists prop | 2026-27 | H33 (engine arms only) | → vs own average | **graded here** | `audit_props.py --asof` |
| all props | 2025-26 | never | no prop prices were captured last season; no as-of player substrate (players_*.csv are season aggregates, leaky) | **untestable** | — |
| live totals / goals / corners / 1X2 | both | H29–H32, H36, euro_holdout | unchanged | settled where graded; H36 vs book WATCHING | state_soccer |

## Gate list vs what the board serves TODAY (WITHDRAWN as a gate -- see the correction at the top; kept as the diagnosis)

Rule (NHL template): probability/edge only if the market beats the naive as-of baseline (CI wholly < 0)
AND the de-vigged book (CI wholly < 0). **Passing list: empty.** Board treatment is by code
(`origin/main`, file:line verified by an agent, the two load-bearing ones re-read here); the served
board tonight carries no soccer projection at all (defect 3), so "today" means "as soon as recs flow".

| market | baseline | book | gate | board TODAY (code) | contradicted? |
|---|---|---|---|---|---|
| 1X2 home/draw/away | beats naive | **loses** | withhold | probability + `edge_vs_market_pct` per leg (2σ sim-noise gate only), ranks on Layer 2 at ×0.877 (`measured_market_skill.py:268-278` LOSES), stakes on market-fair EV only (`portfolio_commit.py:312-386`) | **YES** — a measured-losing edge is still published and ranked |
| totals (full game, all lines) | no diff (goal mean) | **loses** (+0.0095, n 492) | withhold | probability + edge, ranks at ×1.0 because the registry says **parity** (`measured_market_skill.py:279-289`, n 194, 08-31..09-13) | **YES** — registry verdict is stale; the larger sample loses |
| `totals_alt` | — | — | withhold | same pricing, reads as UNMEASURED (registry key mismatch) | **YES** |
| AH / spreads | — | loses | withhold | mean only (`soccer_projections.py:704-718`); no edge | no |
| BTTS | — | **loses** | withhold | board: unsupported, no model; **game card tile prints "Model x \| Market y \| Edge z"** (`soccer/cards.py:1327-1333`) | **YES on the card** |
| corners | no diff | parity | withhold | mean only, "unbuyable" (`soccer_projections.py:1282-1324`) | no |
| cards | untestable | — | withhold | unsupported, no model | no |
| player shots | **worse** than own-avg (lines 1.5, LL all) | one-sided; ROI −22% | withhold | probability from the ladder; edge on TWO-SIDED rows ranks as unmeasured ×1.0; one-sided withheld (`layer2_board.py:900-973`) | **YES** for two-sided rows (rare: 50 UNDER prices in 168,846) and for the displayed probability |
| player SOT | ~even (Brier 0.5 only) | one-sided; ROI −7% [−41, +31] | withhold | same as shots | **YES** (same) |
| player assists | no diff | one-sided; ROI −8% [−47, +35] | withhold | same as shots | **YES** (same) |
| anytime scorer | **beats** shrunk own-avg (post-fix) | one-sided; ROI −30% [−54, +1] | withhold probability; **mean/probability as information only** | probability (unconditional field) shown; edge withheld one-sided | **partly** — probability shown, no edge: consistent with "information, not edge" |
| first / last scorer | untested | one-sided | withhold | race probability derived (`soccer_projections.py:1331-1370`); edge withheld one-sided | **YES** — a probability for a never-graded market |
| live game lines (h2h/totals) | — | never vs an in-play price with CI | withhold | probability + edge, ranks at ×1.0 (live "parity"), cannot stake | **YES** for ranking |
| live props | — | — | withhold | ladder probability; one-sided withheld; cannot stake | partly |
| staking (all soccer) | — | — | — | market-fair EV only; model never sizes (`portfolio_commit.py:283-386`, allowlist set on refresh-worker 09-16, NOT in render.yaml) | consistent |

**What the evidence asks for, if the user decides to act** (each is a separate change behind a decision,
none made here): (1) mark soccer pregame `totals` LOSES in `measured_market_skill.py` with this lane's
n 492 reading, and key `totals_alt` / `h2h_3_way` onto the same verdicts; (2) withhold the soccer 1X2
and totals `edge_vs_market_pct` from Layer 2 ranking (the ×0.877 demotion still ranks a losing edge);
(3) drop the "Edge" from the BTTS card tile; (4) withhold first/last-scorer probabilities until graded;
(5) for props, keep the mean (and the anytime probability as information) but publish no edge from
two-sided rows. The NHL equivalent was `MEASURED_MARKETS` stays empty — soccer has no such single switch.

## Defects / leads found on the way

1. **Production soccer history for 09-21..09-29 is gone** (Render-only artifacts, Render suspended, no
   mirror). Any future grade of that window must rebuild as-of. The fleet backup now covers the fleet's
   own disk, so the gap does not recur.
2. **The 2025-26 "closing" 1X2 benchmark is pre-close.** `match_history.py:109-113` writes football-data
   `Avg*` (market average at collection), not `AvgC*`; `backtest_soccer_h2h_calibration.py` and the 08-15
   result call it "closing". This lane joins the true close via `--fd-close-dir`.
3. **The fleet serves no soccer projection today**: `per_sport_ingest.soccer.enrichment.projections` =
   0 rows, "no soccer recommendations for this date" (02:57Z read, 18 soccer rows, all
   `ev_basis=market_fair`). Not a gate — the fleet has written soccer recs for 09-30 (MLS) and 10-02 only.
4. ~~Prop squads are still stale~~ CORRECTED 2026-10-03: 4,724 of 12,897 pre-kickoff model rows bind to no box-score player, but after the 09-16 rebuild only 4.0% of real shots come from unlisted players -- the unbound rows are listed players outside the matchday squad.

## Reproduce

Cache `C:/tmp/soccer-lpb/cache` (copy of session abacd435's 09-15 audit cache + freeze/fleet additions;
`C:/tmp/soccer-lpb/prep_asof_recs.py`). `SOCCER_AUDIT_CACHE=<cache> SYNDICATE_REPO_ROOT=<checkout with
data/soccer_source/*/history>`:
`outcomes.py` → `audit_games.py` → `audit_games.py --extra <json>` → `audit_props.py --asof <json>`;
2025-26: `backtest_soccer_h2h_calibration.py --all --since 2025-08-01 --fd-close-dir <fd2526> --dump-matches <jsonl>`
then `C:/tmp/soccer-lpb/analyze_2526.py <jsonl>`.
