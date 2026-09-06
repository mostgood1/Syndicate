# state — venues

Split out of `state.md` by `scripts/split_state.py`. Bodies are verbatim.
The INDEX of every subject, across every part, is in `state.md`; the
one-subject-one-section rule is global and spans these files.
Same rules as state.md: when a fact changes, EDIT THE LINE.

## [live-odds-worker-memory-is-page-cache] live-odds-worker READS 96% AND IS NOT IN DANGER — THE FIELD EVERYONE REACHES FOR IS THE WRONG ONE `[measured 2026-09-06, 200 samples, 3.7h uptime with NCAAF segment capture live]`

**The reading that looks like an emergency:**

    container_memory_pct_of_max   min 81.7   median 93.8   max 100.0
    container_memory_headroom_mb  min    0   median  129   max   374
    samples >= 95%                93 of 200  (46%)

**The same 200 samples, split:**

    container_memory_mb        median 1996   max 2048
    UNRECLAIMABLE (anon)       median 1358   max 1772   (43.5%-86.5% of max)
    reclaimable (page cache)   median  617   max  783

**`container_memory_mb` INCLUDES UP TO 783 MB OF RECLAIMABLE PAGE CACHE**, which
the kernel evicts under pressure rather than OOM-killing over. Worst-case
headroom against the ANON floor is **276 MB**, not the 0 MB the headroom field
reports. The service has not OOM'd.

**`container_memory_unreclaimable_mb` IS ON THE SAME LOG LINE AND ALWAYS WAS.**
`ALL_PROCESS_MEMORY` carries `container_memory_mb`,
`container_memory_headroom_mb`, `container_memory_pct_of_max`,
`container_memory_unreclaimable_mb` and `container_memory_unreclaimable_pct_of_max`.
The first three answer *"how close is the container to its limit, cache
included"*; only the last two answer *"how close are we to an OOM"*. Those are
different questions and the first is the one printed first.

**I nearly filed this as a segment-capture regression.** The tell that stopped
it: `accounted_rss_mb` moved **+20 MB** while `container_memory_mb` moved
**+232 MB** in 75 seconds. Anonymous memory cannot appear and vanish like that;
file cache can, and this service re-streams `book_quotes` shards whose
2026-09-06 shard alone is ~22 MB.

**A SINGLE SAMPLE CANNOT SEE THIS.** The container figure swings 84.6% -> 96.0%
in 75 seconds, so any one reading lands somewhere arbitrary in a 19-point range.
An earlier anchor of "87.0% / 286 MB" taken as ONE sample was not wrong so much
as unfalsifiable. **Read the distribution, and read the unreclaimable half.**

### What this does and does not clear

**CLEARED:** enabling NCAAF `h1` segment capture on this service
(`SYNDICATE_NCAAF_SEGMENT_MARKETS=h1`) has not moved it into OOM danger. That
was the owed measurement and it is a pass.

**NOT CLEARED:** 1,772 MB of anon on a 2,048 MB service is ~86% of the hard
limit, and `#241`'s restart loop lived in that band. This is headroom, not
comfort. Any NEW periodic work here still needs its own reading -- and it must
be the unreclaimable one over a distribution, not a headroom snapshot.

## [603-cross-game-quote-keys] VENUE QUOTES NAMED NO GAME; FIXED ON EVERY PATH, DEPLOYED, AND STILL UNPROVEN AFTER THREE READINGS `[2026-08-30, lane live-venue-order-placement]`

`quote_key` was `sport|market|side|line` and the fan-in resolves it against a
SPORT-WIDE pool, so one quote answered every fixture sharing a `(side, line)`.
Measured 2026-08-29: **26 of 28 live Polymarket totals quotes shared across
games** — `over 7.5 @ -400` on AZ@SF, COL@ATL, HOU@NYM and SD@TB at once, where
COL@ATL was worth ~2% and SD@TB had ALREADY WON. `best_any_book` was
`polymarket` on 28 of 28 of those rows.

**FIXED on all five surfaces** (`0c5243b4` live on refresh-worker
2026-08-30T01:21:03Z, content-verified): board `_candidate_keys`, the Kalshi
adapter (ticker blob via `match_event_blob` + schedule), Polymarket (slug clubs,
and for NCAAF the moneyline's nicknames), OddsAPI (its shard key already named
both clubs), and the GRID path. Role-keyed markets only — h2h keys by CLUB and
cannot collide. Bare key first, qualified second, plus a match-time rejection
(`CROSS_GAME_REJECTED` / `_GRID`) so an unqualified match on the wrong fixture is
refused rather than used.

**IT IS NOT VERIFIED. Three production readings, none of them evidence:**

    polymarket ncaaf   live=5  keys=5  collidable=0   UNMEASURABLE
    kalshi     mlb     live=7  keys=7  collidable=0   UNMEASURABLE
    kalshi     soccer  live=8  keys=6  collidable=2   FAIL

**A zero is only evidence if it could have been a one.** In the first two, no
two live games shared a `(side, line)`, so the count would read 0 with the
module deleted. Soccer is the only real reading and it still shares.
`scripts/verify_603_cross_game.py` now computes COLLIDABILITY FIRST and returns
`UNMEASURABLE` (exit 3) rather than a soft pass.

**Soccer residual, diagnosed:** four MLS codes (`NYRB`, `POR`, `LAG`, `STL`)
absent from the soccer alias map, so `match_event_blob` cannot complete a split
and the key stays bare. Patch verified by monkeypatch (4/4 `no_match` → `ok`,
no cross-league leakage — `STL`/`POR` collide with other sports so it must stay
sport-scoped). HANDED OFF: `handoff_2026-08-30_kalshi_soccer_mls_codes.md`;
`team_aliases.py` has multiple claimants.

**DO NOT fix NCAAF by populating `_alias_map("ncaaf")`** — built, measured and
REVERTED 2026-08-29; it makes `teams_match` map-authoritative and turns
`canonical_team("ncaaf","MAS")` → `UMass Dartmouth` into a confident wrong
answer.

Scheduled task `verify-603-cross-game-mlb` fires 2026-08-30 20:15 CT.

## [venue-fee-economics] FEES ARE READ FROM THE VENUE AND VERIFIED AGAINST 18/18 REAL FILLS; THE ARB THRESHOLD WAS ABOVE BREAK-EVEN EVERYWHERE ON MLB `[2026-08-30, lane live-venue-order-placement]`

Kalshi publishes `fee_type`/`fee_multiplier` per series — four distinct
combinations, and **every MLB game/total/spread/K series is HALF RATE**. Base
rate 0.07 measured off 27 of our own fills (21 at multiplier 0.5 → 0.0350, 4 at
1.0 → 0.0700 — discriminating), checked for circularity first. **Rounding is
ceil to a HUNDREDTH of a cent: 18/18 exact, vs 9/18 for round-to-4dp and wrong
for the whole-cent rule every third-party source states.**

`kalshi_polymarket_arb.DEFAULT_FEE_BUFFER = 0.04` demanded a flat 4.00c gap at
every price while MLB break-even runs **3.38c at even money down to 0.39c at
0.97** — above break-even everywhere, so that detector was structurally
incapable of reporting a profitable MLB pair.

**CROSS-VENUE ARB MEASURED: 12 complementary pairs, 0 positive.** Best raw edge
**+0.00c**, and **−0.87c even with a FREE Polymarket** — the venues agree and
Kalshi's own MLB fee exceeds the disagreement. All 12 were pregame and at even
money; the tail regime (break-even 0.52-1.11c against a 1c spread) contributed
none. **Kalshi trades in-play and is liquid** (14 markets, `vol24 904,281`, 1c
spreads, prices moving between reads) — so the live opportunity is FEE
GEOMETRY, not model edge.

**POLYMARKET'S FEE IS 150 bps OF NOTIONAL** `[2026-08-30, CORRECTED]`.
`0.015` per contract, FLAT, independent of price. Reproduces all five real
`commissionNotionalTotalCollected` values within a cent (18.70 contracts ->
$0.28 modelled $0.2805). A cost basis (3.247% of cost) was REJECTED on the
largest fill, where cent-rounding matters least.

**RETRACTED: the entry that stood here said the fee was ZERO.** That was
inferred from the venue's realized P&L at settlement, and realized P&L is
`(exit - entry)` on the position, so **a commission taken at FILL is invisible
to it by construction** — the method returns zero whether or not a fee was
charged. Disproven on its own sample: `C60JWBG0WKDK` implied -0.0023 there while
the venue charged $0.06; two more of the ten were also commissioned. Caught by
peer lane `unknown-submit-retry-provenance`, whose `98e103e1`/`fb749d97` made
the field readable AFTER my reading, and who had an independent cash-movement
route agreeing to the cent.

**POLYMARKET IS THE DOMINANT LEG COST, and the earlier inversion of that was
wrong.** Kalshi's fee is a parabola that vanishes at the tails; Polymarket's is
flat and does not. At P=0.94 Kalshi MLB is 0.0020/contract, Polymarket 0.0150 —
seven times larger. MLB two-leg break-even: **2.50c at even money, 1.70c at
0.94** (the retracted zero said 0.88c / 0.20c, i.e. **2.8x too permissive** — a
threshold below true break-even manufactures arbs that lose on every fill).

The arb VERDICT is unchanged and fails by MORE: best raw edge +0.00c.
**RESOLVED 2026-08-30 — IT WAS NEVER A CONTRADICTION.** `commissionsBasisPoints`
reads `'0'` beside a real `collected` because **the fee is FLAT PER CONTRACT
($0.015) and therefore has no ad-valorem component for a rate field to
express.** 18.70 contracts -> $0.28, 3.91 -> $0.06, 2.38 -> $0.04. Against the
$1 notional that equals 150 bps, but the venue does not report it that way.
**`bps == 0` is evidence of the fee's SHAPE, never of its ABSENCE** — reading it
as absence is exactly what produced the retracted zero above. Guarded in code:
`COMMISSION_RATE_APPEARED` fires if a non-zero rate ever shows up (`c0989cfe`).

## [venue-join-refusal-visibility] WHY THE EXCHANGES DO NOT EXECUTE SOCCER OR PROPS, and the two instruments that were lying about it `[verified 2026-08-28T16:13Z, lane venue-join-refusal-visibility]`

- **Kalshi's join refusal breakdown was discarded on EVERY build in that log
  line's history.** `portfolio_commit` printed `joined.get('refusals')`;
  `join_kalshi_to_board` returns it under `reasons`. Fixed in `26a5be42`. First
  populated reading, 16:13:11Z: `matched=198/1308 reasons={'no_matching_board_row':
  4500, 'market_is_for_another_date': 3203, 'unreadable_title': 2260,
  'series_out_of_scope': 1334, 'stat_not_in_market_vocabulary': 255,
  'event_not_on_our_board': 239, 'spread_line_orientation_mismatch': 24,
  'team_side_unresolved': 13}`.
- **THE ABOVE IS SUPERSEDED — CORRECTED 2026-09-01 ~20:0xZ, read from production.
  THE SOCCER TITLE PARSER IS FIXED AND HAS BEEN SINCE 2026-08-28/30.**
  `[kalshi_odds] BOARD_JOIN` at 19:51:47Z: `unreadable_title` is **18 of 6,000
  markets**, and every sampled `unreadable_title` GAP family today is NCAAF
  SEASON AWARDS (`KXNCAAFACCAWARD` 99, `KXNCAAFBIG12AWARD` 98,
  `KXNCAAFBIGTENAWARD` 98, `KXNCAAFSECAWARD` 100 — futures with no board market,
  correctly refused). **ZERO soccer series appear in the gap list.**
  `kalshi_catalogue` carries `_SOCCER_DRAW` ("Tie is the result"), `_SOCCER_BTTS`,
  `_SOCCER_TOTAL` ("Will over 5.5 goals be scored?") and the
  `more than`/`less than` spread wording, all read from production titles.
  **Anyone told "fix the Kalshi soccer title parser" would ship an inert change.**
- **THE REAL REASON KALSHI SOCCER NEVER REACHES THE BOARD IS THE DATE, AND IT IS
  THE SAME DEFECT THE POLYMARKET JOIN ALREADY FIXED.** `kalshi_board_join`
  compares each market's `game_date_from_ticker` against a SINGLE scalar
  `wanted_date = selected_date` (lines 599/722/950) and refuses anything else as
  `market_is_for_another_date` — **3,495 of 6,000, the largest refusal bucket.**
  Measured from `[kalshi_odds] BY_GAME_DATE` 19:51:44Z: Kalshi's working set
  holds **~900 full-game soccer markets spanning 2026-09-02..09-15 and NOT ONE
  dated today** (KXMLSTOTAL, KXLALIGA/LIGUE1/SERIEA/BUNDESLIGA/EREDIVISIE
  GAME+SPREAD+TOTAL, KXBELGIANPLGAME). Soccer is never same-day, so an
  exact-date join can only ever match zero of it. The sibling
  `polymarket_board_join` solved exactly this with a SOCCER-ONLY, FORWARD-ONLY
  widening at `_FORWARD_HORIZON_DAYS = 14` — the same span Kalshi's soccer set
  occupies.
- **NOT FIXED HERE, and it is a USER DECISION because it is the MONEY PATH.**
  `kalshi_board_join` feeds order pricing, and widening soccer date matching
  would make soccer markets priceable and orderable for the first time — on a
  sport whose model is recorded as NOT beating the market (`soccer-model-dispersion`:
  worse than market in 8 of 9 leagues). Coverage and profitability are different
  questions and this change couples them.
- **KALSHI DOES LIST SOCCER; OUR CATALOGUE CANNOT READ ITS TITLES.** ~665
  markets refuse `unreadable_title`: `KXMLSTOTAL` 90, `KXLALIGATOTAL` 66,
  `KXLIGUE1TOTAL` 60, `KXSERIEATOTAL` 60, `KXBUNDESLIGATOTAL` 54,
  `KXEREDIVISIETOTAL` 54, `KXSERIEAGAME` 40, `KXLALIGAGAME` 39,
  `KXBUNDESLIGAGAME` 36, `KXLIGUE1GAME` 34, `KXBELGIANPLGAME` 12,
  `KXEREDIVISIEGAME` 9, + segment/award series. This is a PARSER gap, not a
  coverage gap, and it was unreadable for as long as the line printed `None`.
- **THE POLYMARKET SPREAD SIGN TEST CANNOT ANSWER ITS QUESTION AT ANY SAMPLE
  SIZE.** Polymarket publishes BOTH legs at every line — 12 of 12 sampled MLB
  fixture/magnitude pairs carry `pos` AND `neg` — so the slug's sign names a
  LEG, not a TEAM. Verdict now `NON-IDENTIFYING`, `rate=None`,
  `both_signs=17` (16:06:53Z). **Its old ladder mapped ~0.5 to `FALSIFIED: do
  not ship a mapping on this` and was at n=17 of 30** — it would have recorded
  a property of the instrument as a measurement about the venue. Answering it
  needs PRICE or SETTLEMENT. Spreads stay refused, unchanged.
- **Polymarket props are structurally out of scope BOTH WAYS**: 8,029
  `market_type_not_a_game_line` (the venue's PROP markets) and 922
  `board_market_not_a_game_line` (70% of our board — `batter_*`,
  `alternate_totals_corners`, `spreads_alt`, `player_*`). Polymarket carries no
  player-prop resolution; Kalshi does and its 7 prop families place fine.
  **SUPERSEDED 2026-09-01 `[lane polymarket-prop-quote-capture]`: MLB player
  props are IN SCOPE for the JOIN + QUOTE CAPTURE as of `9a436fab`**
  (verified 18:10:22Z, capture appended 0→374; both counters above collapsed:
  6,960→3,375 / 935→138). "Carries no player-prop resolution" conflated two
  things: the venue LISTS player props (its largest bucket); what we lacked
  was a measured player-token decode, which now exists (97/99 exact,
  `.syndicate/findings_2026-09-01_polymarket_prop_census.md`). ORDER
  placement on Polymarket props sits behind `SYNDICATE_POLYMARKET_PROP_RESOLVERS`
  — **staged '1' (user-authorized, lane polymarket-prop-resolver-arming) and
  INJECTED by the `bde67379` deploy live 19:06:37Z `[verified present pre-deploy
  by lane prop-unmatched-decomposition; the armed=True/venue_priced log read
  belongs to the arming lane]`** — see `todo #628`.
  **Prop no-match refusals are DECOMPOSABLE as of `bde67379` `[verified
  2026-09-01T19:18:45Z, lane prop-unmatched-decomposition]`:** each prop
  `unmatched_sample` names `player`/`token`/`fixture_tokens` (same
  fixture+family, near-tokens first, bounded 6)/`token_lines`, so one
  `POLYMARKET_UNMATCHED` read separates token-miss (`wilcon2`-class) vs
  rung-miss vs player-not-listed — **and COUNTED COMPLETELY as of `356d65b9`
  (`prop_classes=`, per-family sums == `no_match|mlb|*`, invariant held 532=532
  on first read) `[measured 2026-09-01 ~20:30Z on `839bfa06`, lane
  prop-rung-miss-rate]`: player_not_listed 65.2%, rung_miss 27.4%, near_token
  4.9%, fixture_miss 2.4% (532 rows, one cycle — quote a FRESH line, the
  population moves). Pitcher props are the inverse of the headline: 85.7%
  rung_miss (strikeouts 100%); batter props 71.8% player_not_listed — the venue
  lists ~6–10 batters/game vs our full-lineup board.** The earlier 3-sample
  read (2 of 3 rung-miss) had suggested rung-miss plurality; the complete count
  falsified it. Named follow-up in
  `findings_2026-09-01_prop_rung_miss_rate.md`: board names like `Max Muncy
  (2002)` derive token `max200` (parenthetical survives cleaning) — a
  derivation fix CHANGES MATCHING for deliberately-ambiguous names, own lane
  required.
  rung-miss vs player-not-listed. First read: 2 rung-miss (Soto hits 0.5 vs
  venue 1.5; Gasser K 4.5 vs {1.5,2.5,6.5}), 1 player-not-listed (Rocchio),
  0 token-miss; counts unchanged (224 ≈ 230 baseline — instrumentation only).
  **UPDATED 2026-09-01 19:18Z `[lane polymarket-prop-resolver-arming, USER
  DECISION]`: the resolvers are ARMED** (key set by the user, injected by
  dep-dabi38dcqm1c73dmhdjg live 19:06:37Z). Verified first cycle:
  `armed=True withheld=0`, polymarket `venue_priced` 62 → **462**/485. Props
  are now venue-priced and ticker-stamped, **but prop POSITIONS (and
  therefore prop orders) are still closed by the portfolio commit's own
  `market_family_excluded` policy (402/485 refused, positions unchanged at
  4/$14.71)** — pricing opened, position-taking did not; opening the family
  policy is a separate decision nobody has made.
- **Soccer competition bucketing FIXED, and it bought nothing yet.**
  `soccer_competition_tokens` now unions the flat alias test with the PAIR test
  (`soccer_fixture_clubs`), which `_teams_match` had already trusted since
  08-27. `soccer_tokens_proven=['arg2','bun','eflch','epl','lal','lg1',
  'ligpor','lng','lpa','mlp','mls','sea','swe2']`; ops reader soccer buckets
  **738 -> 1,809**. But `no_match|soccer|h2h` is **93 of 93 board rows** and
  totals **18 of 18** — still 100%. The 104 -> 93 drop was the BOARD SHRINKING
  (1326 -> 1308 rows), not the fix.
- **THE SOCCER BLOCKER IS FIXTURE PAIRING, AND THE REFUSAL NAME SAID SO BEFORE
  THE FIX SHIPPED.** Those rows were already `no_match` (candidates present,
  no fixture paired), never `no_candidates`. Bucketing was a real defect for
  MLS markets and was never the binding constraint for these rows.
- **ORIENTATION: SUPPORTED, NOT ESTABLISHED** `[measured 2026-08-28T17:40:42Z,
  73a7e358, board_rows=1313]`. `POLYMARKET_ORIENTATION`, read denominator-first:

      tried   = {soccer|h2h 106, soccer|totals 27, wnba|totals 6,
                 nfl|h2h 3, wnba|spreads 2, nfl|totals 2}
      flipped = {soccer|h2h 10, soccer|totals 2}

  Soccer flips at **12 of 133 = 9.0%**, a real rate on a real sample. **The
  claim that this is SPORT-SPECIFIC is not established** and must not be
  written as if it were.
- **THE CONTROL CANNOT DISCRIMINATE AT THIS n, and that is arithmetic, not
  caution.** `mlb` is absent from `tried` entirely — 0 of 0, 35 unmatched
  game-line rows and the flip attempted on NONE (spreads/totals only attempt at
  the board's own line). NFL was exercised at 0 of 5. At soccer's 9.02%,
  P(zero rescues in 5) = **0.623** — a zero is the MAJORITY outcome even if NFL
  behaved identically. All non-soccer pooled is 0 of 13, P(zero) = **0.293**.
  Verified independently here and by a second reader. **~30 non-soccer attempts
  would make a zero mean something** (P(>=1) = 0.941); NFL volume should climb
  with the season.
- **A SECOND, NESTED DENOMINATOR PROBLEM — the 9% is a LOWER BOUND, not a
  rate.** The 106 includes rows that could never flip-match for reasons
  unrelated to orientation (a club the alias map cannot resolve fails BOTH
  orientations). So 12/133 is "flipped, out of all unmatched", not "flipped,
  out of fixtures where a flip was even possible". The true inversion rate
  among RESOLVABLE fixtures is unknown and higher. Nobody has that denominator.
- **RESOLVED 2026-08-28, and the earlier downgrade was wrong: THE SOCCER SLUG IS
  HOME-FIRST.** Checked against ESPN scoreboards, independently in two sessions:
  `eng.1 Manchester City @ Crystal Palace` / slug `atc-epl-cry-mnc` (cry = HOME,
  listed first); `fra.1 PSG @ Lille` / `atc-lg1-lil-psg`; `esp.1 Villarreal @
  Alavés` / `atc-lal-ala-vil`. **Our board is CORRECT on all three.** MLB is
  away-first (`aec-mlb-lad-det` = Dodgers @ Tigers) and pairs today, so the slug
  order genuinely DIFFERS BY SPORT.
- **10 of 106 WAS THE WRONG DENOMINATOR AND IT IS WHY I DOWNGRADED IN ERROR.** A
  board row reaches `no_match` only if it did NOT pair normally. So:
  paired normally 0 · paired flipped 10 · never paired either way 96.
  **Among soccer h2h fixtures pairable at all: 10 of 10 inverted, 0 correct.**
  The 96 are a COVERAGE question — the fixture is absent from the slate, or its
  venue tri-code resolves in neither orientation — not a join defect.
- **`no_match` CONFLATES "listed but unpairable" WITH "NOT LISTED"**, because
  `no_candidates` fires only when the whole `(league, date, market)` bucket is
  empty, and for soccer it never is. That conflation is what made 96 look like
  join failures. Splitting it is the next instrument.
- Board-side resolvability MEASURED and exonerated: **all 106** board soccer h2h
  rows have BOTH clubs resolving via `canonical_team`. Zero fail there.
- **STILL DO NOT SHIP A BLANKET FLIP.** MLB pairs correctly away-first today; a
  global flip breaks it. Any fix is per-sport and needs the 96 split first.
- **THE SAMPLES SHOW THE MECHANISM, NOT THE RATE.** All 8 are soccer, across
  five competitions (Ligue 1, MLS, EFL Championship, La Liga, EPL) and both
  slug prefixes, every one board-`away@home` against the reversed slug pair.
  They are capped at 8 AND SELECTED ON THE OUTCOME — drawn only from rows that
  did flip-match — so the "prominent club is away in our data" pattern I read
  off them is conditioned on flipping and cannot support an inference about the
  other ~96. **DO NOT APPLY A FLIP.**
- `/api/ops/polymarket/slate` now passes the join's `soccer_tokens`, so reader
  and decider agree; and it emits `outcome_readability_by_reason_and_recency`
  — `outcomes_count_mismatch` is `past 216 / upcoming 193`, i.e. NOT the stale
  population a six-row sample suggested.
- **NCAAF is invisible to Polymarket for an unrelated token mismatch**: the
  venue files college football under `cfb`, the board says `ncaaf`.
  `no_candidates|ncaaf|totals` 41 of 41, `|h2h` 6 of 6.

## [live-odds-worker-deploy-gate] THE DEPLOY GATE IS UNREACHABLE ON live-odds-worker, and the documented override CANNOT WORK AS WRITTEN `[measured 2026-08-30 18:0x-18:35Z]`

`deploy_preflight --service live-odds-worker` returned **`HOLD` on ~76 samples
across ~30 minutes**, sampled as tightly as every 4s, and never once `CLEAR`.
Independently reproduces `live-venue-order-placement`'s 36-poll finding.

**Cause: `refresh_odds_sources.py` (pid 2580) is a PERSISTENT sweep** walking the
soccer league list (`epl -> mls -> eredivisie -> ...`) under a stable parent pid.
It briefly showed 2 jobs and went straight back to 3. The only window is the gap
between sweeps, and **a preflight sample itself takes ~10s** — so a shorter gap
is not observable at all. (A window DID open later at ~18:4xZ and another lane
took the claim, so this is "unreachable in practice", not "impossible".)

**`SYNDICATE_DEPLOY_GUARD=off` AS AN INLINE PREFIX DOES NOTHING.** The hook is a
separate process that reads its own environment BEFORE the command runs, so
prefixing the sanctioned deploy entrypoint is blocked exactly as if unset
(measured). Making it take means putting the var in Claude Code's own
environment — `.claude/settings.json` — which disables the guard **repo-wide, for
every session, permanently**. That is not a per-deploy override.

**The narrow form that works:** the same one-liner run in a HUMAN's own shell,
where hooks do not apply and nothing persists. Used for `fcadd126` at 18:37:12Z.

**A SECOND, UNRELATED HOOK BEHAVIOUR worth knowing:** the guard pattern-matches
the COMMAND STRING, so a `cat >>` writing ledger prose that merely NAMES the
deploy script is blocked as if it were a deploy. Write such prose from a file,
not from a heredoc.

## [venue-candidate-key-ambiguity] BOARD JOIN KEYS: a bare token could name another fixture's team, and the guard's own counter cannot see it fire `[verified PARTIAL 2026-08-28T02:36Z, lane venue-candidate-key-token-guard]`

`_candidate_keys` built city/nickname keys from a board team, bounded only by
subtracting the OPPONENT's words — correct about the ROW and the wrong SCOPE for the
lookup, since `apply_venue_quotes` resolves against the sport's WHOLE quote pool.
Measured over the alias maps: **soccer 21 ambiguous tokens** (`city` names 14 clubs,
`real` 4), **mlb 7**, **nfl 5**, **nba 3**; and `_alias_map` is `{}` for nhl/ncaaf/
ncaab, so those rows had NO guard at all ("Ohio State Buckeyes" offered
`ncaaf|h2h|state`). An unresolvable board team also fell through to raw words
("Not A Real Club" -> `mlb|h2h|club`, `|not`, `|real`).

`unambiguous_club_tokens` now keeps only tokens naming exactly one club, and
`team_name_tokens` resolves through `canonical_team` with no raw fallback.

**PARTIAL, and the limit is the instrument.** Production read (`32b0cfaa`, 02:36Z):
soccer inputs byte-identical across the boundary and output identical — unmatched
rate **30.72% -> 30.72%**, kalshi `wanted_overlap` **83 -> 83**. That shows NO HARM.
It does NOT show the guard fired: `wanted_overlap` counts `offered ∩ wanted`, this
change shrinks *wanted*, and kalshi's soccer keys are full club names the guard
preserves — so the counter reads 83 either way. The nhl/ncaaf/ncaab **wrong**-match
half is a different question and no counter here answers it.

## [odds-cadence] ODDS CADENCE AND CAPTURE

- **MLB quote capture has THREE regimes, not one beat. `[measured 08-15 02:5xZ,
  supersedes the single-cadence reading of 08-14 16:3xZ]`** All 371,567 rows of
  `mlb_source/tracking/book_quotes/2026-08-14.jsonl`, streamed from web and
  bucketed by distinct `captured_at`:
  | window (UTC) | slate | gap |
  |---|---|---|
  | 07:03→15:10 | pregame, nothing live | **121 / 121 / 123 / 121 min** |
  | 16:20→18:25 | first games start | 70 / 61 / 64 min |
  | 18:36→20:54 | ramping | 11–12 min |
  | 21:48→02:53 | full live slate | **~1 min, continuous** |
  **121.6 is exact and it is the EMPTY-SLATE PREGAME number only.** The same
  pipeline samples 122× faster once games are live. Never quote it unqualified.
- **SUPERSEDED IN PART — there is a THIRD regime, and it dominates.
  `[measured 08-15 16:38-17:00Z, deploy-free window, 22 samples]`**
  On 08-15 the pregame beat was **~60 min, not 121.6**, and then MLB capture
  starved for **5.8 h**. Cause is neither the tick nor the cooldown: a chain of
  back-to-back refresh **run-locks** (`ops_refresh.py:669`, per-lane, NOT the
  separate `JOB_CAP_THROTTLED` job cap -- an earlier version of this line
  conflated them; raising the job cap would not have helped), each
  held ~25 min with ~2 min free — **~92% occupancy, traced 11:39→17:00Z**.
  17 consecutive ticks refused by `pid=4047`; the ONE tick that got through at
  16:56:26 took end-to-end from **20,880 s to 32 s**, then `pid=5681` retook it.
  **End-to-end is BIMODAL: ~32 s or hours, never in between.** In the starved
  regime the number rises exactly 1 s/s — it is a clock, not a latency.
  **`PREGAME_RELAUNCH_COOLDOWN_SKIPPED` fired ONCE in 5.75 h** (counted on
  live-odds-worker, the correct emitter, with a liveness control), so **Tier 0's
  `0.1` would NOT have prevented this** and is not the Tier 5 prerequisite the
  program plan calls it. Full working:
  `.syndicate/tier5_quote_to_ui_WINDOW2_2026-08-15.md`.
- **WHY 60s BECOMES ~7,300s, two multipliers, both measured `[08-14 17:0xZ]`:**
  1. `SYNDICATE_LIVE_ODDS_REFRESH_INTERVAL_SECONDS=60` is the TICK interval,
     never the launch interval.
  2. **The pregame relaunch cooldown is 1800s and GLOBAL** —
     `_pregame_relaunch_blocked` reads ONE marker keyed by **date only, not by
     sport and not by service**, so a launch for ANY sport starts the clock for
     EVERY sport. 30×.
  3. **Sports rotate across launches**, so MLB rides roughly 1 in 4. ~4×.
  **The leverage is a design fact, not a tuning value: because the cooldown is
  global, every sport added dilutes every other sport's cadence.** A per-sport
  cooldown decouples them; that is the change worth considering, not lowering 1800.
  4. **BUT THE COOLDOWN IS GATED ON PREGAME PHASE AND IS BYPASSED WHENEVER ANY
     GAME IS LIVE. `[measured 08-15 02:5xZ]`** On the deployed tree:
     `effective_phase = ("live" if any_live else "pregame")`, then
     `if ... effective_phase == "pregame" and _pregame_relaunch_blocked(...)`.
     `latest_tick` carried `adaptive:true, anyLive:true, phase:"live"`. So both
     multipliers above apply **only to the empty-slate pregame regime**.
- **The per-sport cooldown fix (`ea8fad58`) is NOT deployed on ANY service.
  `[measured 08-15 02:4xZ]`** Checked by reading the deployed trees, not
  ancestry: `git show <sha>:syndicate/features/shared/live_refresh_loop.py`
  gives `def _pregame_relaunch_blocked(*, now_epoch, date_str)` — no `sports`
  kwarg — on both `548ded38` (refresh-worker) and `ccd10349` (live-odds-worker).
  **`ea8fad58` IS an ancestor of `origin/main`, so an ancestry-only check says
  "shipped" and is wrong.** `autoDeploy` is off; being on `main` ships nothing.
- **WHICH SERVICE DRIVES CAPTURE IS AN OPEN DISCREPANCY — re-check the env
  before relying on either answer. `[measured 08-15 02:5xZ]`** The env API now
  reads the OPPOSITE of this file's 08-14 line: live-odds-worker
  `SYNDICATE_ENABLE_LIVE_ODDS_REFRESH_LOOP=true` and
  `SYNDICATE_MLB_REFRESH_TICK_OWNER=true`; refresh-worker `false` on both; and
  the 02:35:20Z tick wrote `refresh_status_latest__live-odds-worker.json`.
  **But** `ODDS_SWEEP_OUTCOME` since 02:00Z is refresh-worker **16**,
  live-odds-worker **0**, which matches the old line. The emitter
  (`live_refresh_loop.py:4100/4117`) is reachable from the board-build sweep as
  well as the loop tick, so both emitting is not itself a contradiction.
  Unresolved; resolving it needs the board-build loop. Loop ownership is an env
  flag that moves with no diff — that rule is why this line is now a question.
- **This is the real cause of "candidates that are no longer bettable"** — the
  board's MLB prices are up to ~2 hours old by construction.
- **Consequence for the whole movement family — REAL CONSTRAINT IS THE BUFFER
  DEPTH, NOT THE FETCH RATE. `[measured 08-15 02:4xZ, supersedes "sampled
  roughly every two hours"]`** From
  `/api/ops/odds-history/inspect?sport=mlb&date=2026-08-14`, 3,582 markets:
  sampling interval within the retained history is **p50 1.0 min** (live 0.9,
  pregame 1.0) — not 2 hours. But `history_points` is **capped at 20**
  (`_ODDS_HISTORY_LIMIT`, `shared/odds_refresh_tracking.py:40`, env-tunable via
  `SYNDICATE_ODDS_HISTORY_LIMIT` which is **unset on all three services**), and
  3,130 of 3,582 markets sit exactly at the cap. Retained span is therefore
  **p50 17.8 min**. The code's own comment concedes it is *"narrower than the
  steam detector's stated 45-min window for hot markets."*
  **So a movement calculation sees ~18 minutes and is structurally blind to
  whether the previous sweep was 1 minute or 2 hours earlier — the
  pregame→live transition, the biggest move of the day, falls out of the buffer
  within 20 minutes of first pitch.** Re-examine `movement_velocity` and the
  steam detector against `_ODDS_HISTORY_LIMIT`, not against fetch cadence.
  Raising it trades against the 8 MB keyvalue ceiling that forced it to 20.
- **A `too_large` line does NOT mean the artifact failed to publish.** The
  ceiling lives in `_publish_skip_reason`, which is **sweep-only**; the direct
  path streams and never consults it. Verified byte-identical on web. Four
  sessions have now misread this. `[measured 08-14 16:2xZ]`

### OddsAPI budget `[measured 08-14 17:2xZ]`

- **Projected 30-day burn 4,640,809 credits = 92.8% of the 5M cap.** Headroom
  ~360k/month. MLB is **93.7%** of spend (8.72 cr/call); soccer 4.2% (1.46
  cr/call, 6× cheaper); nfl 1.4%; wnba 0.7%. Live hours dominate (83–228k/hr)
  against pregame's 10–18k/hr.
- MLB pregame sweep interval is 3600s with an effective gap of **~1h10m**
  (7,289s → 4,215s). The loop wakes every 900s and sweeps whatever is past its
  interval, so the setting is a FLOOR the tick quantises.
- **Any cadence increase spends against the cap — it is a product decision, not
  a tuning tweak.**

---

## [venue-odds-storage] `venue_odds` LIVES ON DISK, NOT IN THE SHARED KEYVALUE `[measured + deployed 2026-09-02, lane venue-odds-byte-aware-trim]`

`reports/intelligence/venue_odds/` held **41 keys / 114.9 MB of a 224.3 MB
store** — 51% of a 256 MB Redis at 93% with 11,852 keys evicted — and the reader
trace found **nothing reads it**: the only read is `record_daily_odds`'s own
read-modify-write, and both external importers take write paths only. It is a
deliberate capture-first archive whose consumer was never built.

Two changes, both live on BOTH workers and measured:

- **`#638` byte-aware trim** (`21de4a9e`). The count caps could never bind:
  `MAX_POINTS_PER_MARKET=48` / `MAX_MARKETS_PER_FILE=8000` bound COUNTS while the
  guard bounds BYTES. **3,192 refused writes in 40h** (live-odds-worker 2,203,
  refresh-worker 989; web none — it does not run this writer). Trim is REACTIVE:
  it catches `KeyValuePayloadTooLarge` and retries at 90% of the ceiling, so it
  costs nothing on the happy path and is inert on a disk backend.
  **The criterion is a PAIR, not zero rejections** — one rejection per file per
  growth cycle is BY DESIGN; the failure is a rejection with no `TRIMMED_TO_FIT`
  after it.
- **`#637` moved off keyvalue** (`e4a471c0`). `_KEYVALUE_EXCLUDED_PATH_MARKERS`
  gains `/intelligence/venue_odds/`. **50 and 37 files hydrated, distinct ==
  total on both workers.** Disk is PER-SERVICE where Redis was shared — not a
  regression, since two services doing RMW on one key already lost each other's
  updates. `reports_root()` is `/opt/render/project/data/reports`, the MOUNTED
  disk (read off live env), so these survive a deploy.

**MEMORY NOT RECLAIMED, DELIBERATELY.** ~115 MB stays until the 10-day TTL.
Hydration reads the old key on a service's FIRST write of a file, and
refresh-worker has not yet written polymarket — expiring now would make those
start empty, and an accumulator that starts empty **re-dates every `opened_at`
to the expiry moment**. Wrong data, permanently. Gate before any expiry:
`scripts/check_venue_odds_hydration_census.py` (exits 0 only when every censused
key is SAFE and nothing was truncated; first run **27 SAFE / 15 PENDING**).

**NOT OWED — VOID. `#637` MADE `#638`'s TRIM UNREACHABLE, and "wait for it to
fire" was wrong `[corrected 2026-09-03]`.** The trim triggers by catching
`KeyValuePayloadTooLarge`, which ONLY the keyvalue backend raises. `#637` moved
`venue_odds` to disk, and disk has no 8 MB ceiling — so the write cannot be
refused, so the trim cannot be reached. Measured since the disk move
(2026-09-02T19:26:44Z): **zero `TRIMMED_TO_FIT` and zero
`KEYVALUE_WRITE_REJECTED` for `venue_odds` on BOTH workers**, including
live-odds-worker, which had trimmed twice before the move. That is the ceiling
being gone, not a stalled writer.

**UNREACHABLE IS NOT UNVERIFIED, and the two look identical in a log.** An
unverified fix might still be broken; an unreachable one cannot run at all.
Carrying this as "owed" would send a future session hunting a signal that can
never appear.

**The mechanism IS proven** — live-odds-worker emitted two `TRIMMED_TO_FIT`
lines on 2026-09-02 with `markets_dropped=0` and a `status=ok` book. `#638`
remains correct, unit-tested both directions, and is now DORMANT: the safety net
if `venue_odds` ever returns to keyvalue.

## [sharp-reference-price] SHARP REFERENCE PRICE — WE HAVE ONE. The audit's caveat is STALE.

**The models audit's "no Pinnacle, Circa or exchange in the feed" was true when
measured and is FALSE now.** The feed widened between 08-05 and 08-09 and nobody
re-read it. `[measured 08-15 from data/mlb_source/tracking/book_quotes/]`

| dates | distinct books | pinnacle rows | shard size |
|---|---|---|---|
| 07-28 .. 08-05 | **11** | **0** | ~13 MB/day |
| 08-09 | **37** | **2,604** | **217 MB/day** |

- **Sharp coverage on MLB GAME LINES is 102 of 102 markets = 100%** on 08-09.
  Sharp set present: `pinnacle`, `betfair_ex_eu`, `matchbook`, `novig`,
  `prophetx` (plus `kalshi` / `polymarket` as prediction markets).
- **Sharp coverage on PROPS is 0%.** Prop CLV therefore stays a soft-consensus
  measurement and **must be labelled as such**; game-line CLV can be taken
  against a genuine sharp close.
- **THERE IS ALREADY A PER-SPORT LEVER FOR THE PROP GAP, and NHL uses it.**
  `syndicate/local_nhl_odds.py:542` defaults
  `PROPS_ODDSAPI_BOOKMAKERS = "fanduel,draftkings,pinnacle"` — Pinnacle is
  explicitly requested for NHL props. `vendor/nhl_betting_repo/.../odds_api.py`
  carries it in a book list too. So closing the 0% on other sports' props is a
  **config change on an existing knob**, not a build. `[from-code 08-15]`
  **Cost it before flipping it:** every added book spends OddsAPI credits
  against the 5M cap — **STALE→UPDATED 2026-09-01: 4,959,329 of 5,000,000
  remaining (99.2% unused) per `odds_regions.py:63-66` after the #15/#16 cuts;
  quota is no longer the binding constraint** — and props are the highest-
  volume market family. Measure the per-call delta on one sport first.
- **This removes the standing caveat on the whole CLV program** — "beating a
  closing consensus of eleven soft books can read positive where no exploitable
  edge exists" no longer applies to game lines.
- **The widening is almost certainly the lost-books capture fix**, which also
  explains the 13 MB → 217 MB/day jump. That cost is real and it is what the
  storage-format work (delta/columnar) exists to absorb — **do not "fix" it by
  narrowing the book set again; price shopping was measured at +2.79 ROI pts.**
- **Caveats, stated:** read from the git-tracked mirror, which is lossy, and
  only ONE post-widening date exists locally (08-09). **Confirm against
  production before publishing a sharp-referenced CLV number**, and re-read
  whether the 37-book set is still current.

---

## [board-quote-staleness] Board freshness vs QUOTE staleness — verified 2026-08-26 (lane `board-staleness-visibility`)

**THE BOARD BUILD IS ~108s IN STEADY STATE.** n=40 unattended builds, median
107.8s, p90 145.5s. **A COLD build (first after restart) is 747.8s — 6.9x — but that is a FLOOR, not a bound: measured again 2026-08-27, boot `00:56:13Z` to first `GAME_CHIPS_PUBLISHED` `01:14:32Z` = **18m19s**, half again the recorded figure, on a 15-game slate. Slow rather than stuck — stages walked forward (`cards_context_end` 01:01, `board_contract_end` 01:07) and memory was flat at ~1.79GB anon. Do not size a wait against 747.8s.**
Every figure in older entries (19m43s, 12m44s, 11m22s) is a COLD build
generalised; they were measured in a window with 15 deploys in 6h15m where the
worker never reached a warm build. **Quote a board-build duration only with
cold/warm attached.**

**Cold-build decomposition:** `build_intelligence_overview` 295.1s,
`candidate_collection_with_fallback` 178.0s, `candidate_building` 0.01s,
`manifest_odds_history_join` 0.32s. **All eight sports' candidate generation is
47s — 6% of the build.** Optimising generation optimises nothing.

**Per-sport odds-history load is CHEAP:** total 0.2s across 5 sports, mlb 0.19s,
**soccer 0.01s**. Do not size work against an assumption that shard reads are
expensive.

**THE BOARD SERVES STALE QUOTES, and publication freshness cannot see it.**
`seen_p50=859s` against a ~60s publish cadence. Every publication-time
instrument (`written_at`, `state_meta`, the stale badge) reads FRESH on a board
carrying 14-minute-old quotes. Use `QUOTE_AGE_SERVED`.

**`last_seen` MUST be read across the same dates as `quote_rows`.** Fixed
2026-08-26: `quote_rows` extends across `window_dates` while `last_seen` read
`selected_date` alone, leaving rows clockless — and **a clockless row is
invisible to `drop_superseded_lines`**, which requires a clock on both sides by
design. Measured before the fix: `no_seen_age=7553` against `kept=15672`, 48% of
a grid exempt from the guard. After: `no_seen_age` max 52, drops 16 -> 824/2271,
artifact 962141 -> 962176 bytes.

**NFL's sweep cadence is FIXTURE-AWARE AND CORRECT, not an outage.**
`FIXTURE_CADENCE sport=nfl interval=28800 reason=mid:26h_out` — 8 hours by
design (`#440` Phase 1b, which predicted nfl_preseason 12.00 -> 3.56 sweeps/day).
ncaaf 86400s, wnba 7200s. **Judge a sport's sidecar against its OWN interval or
against its rows' ages — never a flat threshold.**

**`_pregame_sweep_interval_for_tick` DISAGREES ACROSS SERVICES.** It is
fixture-aware; the decision is made on **live-odds-worker**. Recomputing it on
refresh-worker returns 7200 for nfl against production's 28800, because the
fixture lookup finds nothing there.

**NO MEMORY PROBLEM EXISTS ON refresh-worker.** Peak unreclaimable 29.1% of
4096MB, zero oomKilled over two days. `container_memory_pct_of_max` counts page
cache; `ALL_PROCESS_MEMORY` now carries `container_memory_unreclaimable_*`
beside it. **Quote the unreclaimable figure.**

## [exchange-refresh-cadence] — VERIFIED 2026-08-27, live-odds-worker `34b4d4b4`

- **Kalshi's 120s refresh interval is unreachable.** `run_kalshi_odds_refresh()`
  is called from ONE site — inside the board build — whose period is 3.4-13 min.
  The board loop sets the venue refresh rate, not the venue config.
- **CORRECTED 2026-08-27 18:5xZ — my earlier line here ("`MAX_STORED_MARKETS =
  6000` drops ~42% of the catalogue") WAS WRONG and is replaced.** The cap is
  deliberate and safe: the keyvalue store hard-refuses at 8MB, an unbounded
  version reached 13.3MB and STOPPED WRITING THE ARTIFACT AT ALL, and
  `venue_daily_odds` keeps the complete record. 6000 is a bounded WORKING SET
  the join prices against, not the record. Nothing is lost by the bound.
- **ALLOCATION IS CONFIRMED AS THE BINDING CONSTRAINT, AND TODAY'S RECOVERY WAS
  NOT THE FIX FOR IT `[2026-08-27 ~21:0xZ, corrected]`.**
  `[kalshi_odds] BOARD_JOIN matched` went from 5-24 back to **208 / 218 / 221**
  against a complete-set 235 / 242 — the 6,000 working set now captures ~91% of
  what the full ~10,560-market catalogue matches, up from ~6%. `matched` tracks
  MLB's slot count almost exactly (`mlb_slots` 794 -> matched 27; 1620 -> 208;
  1741 -> 218; 1706 -> 221), which is what establishes allocation as the
  mechanism.
  **I FIRST ATTRIBUTED THIS TO `venue-quote-line-join`'s DEMAND-WEIGHTED TRIM
  (`bd81ba3c`). THAT WAS WRONG AND THEY CORRECTED IT.** The trim's own log line
  at the moment of recovery reads `TRIM_BY_SPORT ... demand=None mlb_slots=1620`
  — `_sport_slot_caps` returns None with no demand signal and the trim falls
  back to the FLAT-FLOOR branch. So the demand code was DEPLOYED AND NOT
  EXECUTED. I checked ancestry (deploy state) and inferred causation
  (predicate); the emitted field disproves it. Standing rule "test the fix's
  predicate, not its deploy state" — I had it available and did not apply it.
  **WHAT ACTUALLY RECOVERED IT: MLB's slate approaching first pitch.** Its
  markets churn, become the freshest in the catalogue, and the staleness-ordered
  remainder pass hands them the slots. Staleness ACCIDENTALLY doing what demand
  weighting does deliberately.
  **SO THE COLLAPSE IS EXPECTED TO RECUR TOMORROW MORNING** — corrected from
  "afternoon", which was wrong. In CENTRAL time today's collapse ran roughly
  09:00-14:00 CT (matched 5-27, spiking 146/210/99) and the recovery landed at
  14:49 CT (208 -> 218 -> 221). The bad window is the MORNING.
  **AND OBSERVING THE RECURRENCE IS NOT A PRECONDITION FOR ANYTHING.** I framed
  it as one. It would only confirm a prediction; the mechanism is understood
  (`matched` tracks mlb slot count) and `f4beb1bc` is landed. Turning "I could
  measure this" into "this must be measured first" is not a reason to carry a
  known-fixed defect through the window. Demand weighting is what stops the
  RECURRENCE; it is not what fixed today. Their `f4beb1bc` (per-sport MAX over a
  6h/12-sample window) additionally fixes `_record_board_demand` overwriting on
  every join — the alternating 442/842-row future-date builds were dropping mlb
  from the vector entirely, last-write-wins reading "not mentioned" as "no
  demand". Landed, undeployed as of this writing.
  HISTORICAL RECORD OF THE DEFECT FOLLOWS:
- ~~THE REAL DEFECT IS THE ALLOCATION, AND IT IS LIVE~~: the BOARD's Kalshi join
  lost ~93% of its matches today.** Same ticks, refresh-worker:
  `[kalshi_odds] BOARD_JOIN set=6000 rows=1329 matched=210` at 16:01:42Z, then
  `matched=5` from 16:13:19Z and 13-24 since — while
  `[portfolio_commit] KALSHI_BOARD_JOIN markets=10650 rows=1335 matched=210..217`
  on those same ticks. A SELECTION problem, not a catalogue one.
  CAUSE: `_trim_to_storage_bounds` orders by series staleness with a flat
  `PER_SPORT_FLOOR_MARKETS = 300` and has NO notion of which sports have games
  on the date being built. NCAAF opening week floods the set —
  `TRIM_BY_SPORT kept_by_sport={'mlb': 648, 'nba': 6, 'ncaaf': 1896,
  'nfl': 2083, 'soccer': 1067, 'wnba': 300}` (MLB hit the bare 300 floor at
  18:45Z) — against board demand of mlb 400 / soccer 400 / wnba 400 rows vs
  nfl 88 / ncaaf 42. ~4,000 of 6,000 slots serve 130 rows.
  **SCOPE, CHECKED NOT ASSUMED: EXECUTION IS UNAFFECTED.** `portfolio_commit`
  reads the STORED artifact via `markets_from_state` (~10,650) and still
  matches 210-217, so orders price off Kalshi's real book. The degradation is
  `join_to_board`'s board ANNOTATION — display and edge detection, not order
  placement. Not a money-at-risk incident.
  The 300/sport floor shipped the same day and DID fix soccer starving to zero;
  this is the adjacent failure a flat floor cannot see. Owned by lane
  `venue-quote-line-join` (claims `pipeline/kalshi_odds_refresh.py`), messaged
  with these measurements 18:5xZ. NOT edited by me — cross-lane file.
- **`run_polymarket_odds_refresh` is boot-only and yields nothing.** Wired only
  into `_polymarket_catalogue_at_boot`, so its 300s interval never applies. All
  10 boots in 17h: `count=100 sporting=0 truncated=False` — one page, zero
  sporting, and it believes the catalogue complete. `portfolio_commit`'s own
  Polymarket path sees `markets=17299 indexed=9106`.
- **Execution fires ~16 min, places almost nothing**: 9 cycles 13:49-15:52Z ->
  4 orders (Kalshi 3, Polymarket 1); otherwise `placed=0 duplicates=3-9`.
- **The live caps come from the SAVED STORE, not the env vars — BY DESIGN, and
  the current numbers are DELIBERATE `[USER CONFIRMED 2026-08-27]`.** Env
  `SYNDICATE_EXECUTION_MAX_DAY_DOLLARS_KALSHI=50` while `LIMITS` logs
  `max_day_dollars: 75.01`, because `_stored_live_limit` reads the `/portfolio`
  form store and that store WINS. `/api/portfolio/limits` reports every field as
  `source: stored`, `store_error: null`, `updated_at 2026-08-27T08:56:10-05:00`.
  In force: order $10.01 · kalshi $75.01/25 orders · polymarket $100.01/50 ·
  all-venues $200.01/75. The order caps exceed the `[USER DECISION 2026-08-25]`
  code defaults (15/15/25); **the user set them personally and they are
  intended.**
  **DO NOT "fix" this by reverting the caps to the env values — that would
  LOWER live money limits the user chose.** The env vars are fallback-only and
  are what is actually stale. Comparisons are strict `>`
  (`used + stake > cap`), so the trailing `.01` is not needed to admit an
  exactly-at-cap order; it only absorbs sub-cent overage such as Kalshi taker
  fees.
  STILL OPEN, not a defect: `update_limits` records only field values plus
  `updated_at` — no actor and no prior value — and `POST /api/portfolio/limits`
  is reachable by any agent session. No audit trail on a money surface.
- **Staleness dominates cadence.** `QUOTE_AGE_SERVED seen_p50=4285s` (71 min),
  p90 7776s, max 37837s; Polymarket join `slate_age_s=579.5`. A faster board
  loop cannot make a 71-minute-old quote fresh.

None of the above is fixed. No lane holds them.

## [exchange-venues] Crypto.com is NOT a third venue — VERIFIED 2026-08-28, local full-egress session

**The venue is attractive; the ACCESS is the blocker, and that is the whole
finding.** Crypto.com Predictions sports contracts are real, CFTC-regulated via
CDNA, and priced in dollars of probability against a $1 settlement — the SAME
unit convention as Kalshi (`BOS $0.42 / NYY $0.59`, ~1pt vig, one MLB game at
$1.37M cumulative traded). It still cannot be integrated:

- The only JSON sports surface is the consumer app's undocumented internal
  proxy, and it is **Cloudflare-gated: 200 to a challenged browser, 403 to a
  plain client** (curl, with and without full Chrome headers). Workers use
  `urllib.request`. Kalshi and Polymarket both answer a plain server-side GET.
- That JSON **carries no prices** (RSC-rendered; only a 2-point sparkline).
- The documented Exchange REST catalogue holds **957 instruments, 0 event
  contracts** (CCY_PAIR 578 / PERPETUAL_SWAP 367 / FUTURE 12).
- **OddsAPI has no crypto.com row** (`us_ex` = betopenly, kalshi, novig,
  polymarket, prophetx), so the aggregator path Novig/ProphetX use is closed.

Unblock is a **contact form, not code**. Do NOT build a browser-driven scraper.
`cryptocom_client.FINDING` and `probe()` now say all of this; `probe()` returns
`unblocked` (default False, flipped only by a non-crypto `inst_type` in the
SANCTIONED catalogue). Full evidence:
`.syndicate/findings_2026-08-28_cryptocom_venue_evaluation.md`.

**Supersedes the 2026-08-24 record**, which was written from a sandbox that
403s CONNECT to crypto.com and got three things wrong — see `learnings.md`.

## [venue-market-universe] The venues list ~25,000 markets and the board acts on 277 — VERIFIED 2026-08-30

Measured on `refresh-worker 7d5addba`, both joins, same cycle:

```
Polymarket  15,457 captured ->  60 matched   (0.4%)
Kalshi       9,267 captured -> 217 matched   (2.3%)
board_rows   1,179
```

**THE CAPTURE IS NOT THE GAP.** `/api/ops/polymarket/slate` reports
`truncated: False`, `dropped_for_size: 0`, `slug_unparseable: 0`, 15,104 rows,
horizon to 2026-09-27, and **2,508 totals rungs against 1,385 moneylines** — the
alt ladders are already in hand, 4-9 rungs per soccer fixture.

**WE DISCARD AT CONSUMPTION.** The board is built from the ODDS SOURCE, so its
market universe is OddsAPI's. A venue market with no board row has no model
probability, no edge, and cannot be traded however good the quote:

```
market_type_not_a_game_line   6,647   props, exact-score, ftts
segment_market_not_full_game  1,430   intervals — refused BY DESIGN (#563, $7.08)
no_matching_board_row         2,016   kalshi
series_out_of_scope           1,334   kalshi
```

**A MISSING ROW IS NOT A MISSING MODEL.** Kalshi team totals
(`KXWNBATEAMTOTAL`, 36/build) refuse for want of a board row, NOT for want of a
price: `basketball_props_smart_sim` already projects `home_mu`/`away_mu`,
`home_team_total_pts_mean` and `team_total_pts` per simulated box, so
P(team over N) is countable today. The two states call for different work.

**Polymarket soccer market grammar, measured rather than guessed:** 3-way h2h is
THREE Yes/No markets with the subject in the slug; corners are `cor-all-gt<line>`
where `gt` states the direction (`Yes` = over); college football is filed under
`cfb`; the venue row's `line` field is the ONLY source for corners and `_KEEP`
must retain it.

**Kalshi refusals now say WHICH KIND.** `unreadable_title` 1,371 -> 458 with
`recognised_but_no_board_market` 838: a grammar to WRITE is separated from a
market we understand and will never price. Segments remain untradeable.

---

**`#603` REOPENED 2026-08-31 01:11Z — the 06:18Z closure below measured a
NARROWER property than the ticket.** Venue quotes DO still answer the wrong
game: 41 of 97 live MLB Kalshi-priced rows, including **9 of 9 live totals**
(Reds@Cubs priced by `KXMLBTOTAL-26AUG311805SFATL-*`, a San Francisco @ Atlanta
market), on a pool built by `165c448f` which contains both `#603` fixes. Full
reading and cause in `deploys.md`. The closure reading was real but is blind to
a ref imported from a game **not on the priced slate**: it answers exactly one
of our fixtures — the wrong one — so a collision metric scores it clean.
Cause: `_unconfirmed_on_a_contested_key` returns False whenever
`len(claimants[key]) <= 1`, and `_kalshi_game_token` collapses `no_match` into
the same `None` as "named nothing", which is the permissive branch.
`CROSS_GAME_REJECTED_GRID` never fired in ~23.7h (positive control:
`GRID_REPRICE` 544 matches, same window). `verify_603_cross_game.py` shares the
blind spot — it scores UNMEASURABLE without a collidable pair, and this defect
needs no collision.

The superseded closure, kept because its reading was sound for what it covered:
**`#603` closed and measured 2026-08-30 06:18Z.** Board `2026-08-30` pool `06:18:37Z`, after `d7cda903`:
`refs answering >1 fixture 0 of 96`, `rows served by one 0 of 177`,
`wrong-game price as served HEADLINE 0` (was 2). **The zero is discriminating**
— 192 contested keys and 992 rows of opportunity existed, and 166 matched rows
sat on contested keys, all resolving to single-fixture refs. Rule:
`venue_quote_fanin._unconfirmed_on_a_contested_key` — on a key more than one
game claims, a match needs BOTH sides to name the same game.

**The venue basis (`venue_basis_edge.py`) is WIRED and UNMEASURED.** Live in-play
exchange price vs book consensus net of venue fee, attached in the grid path and
carried through `layer2_board`'s `quote` fan-out. Proven to run: 809/809 rows
carried the key, and the same script read `NOT WIRED` against the pre-deploy
pool. **`servable=False` on every row and no reading has yet produced a real
number** — its only measurement was a slate where all 7 displayable rows were
wrong-game artifacts, and the post-fix slate was `live=0`. Its two freshness
constants (45s venue, 900s anchor) are UNFITTED guesses.

**Polymarket's fee is 150 bps of NOTIONAL, flat, price-independent** (five
`commissionNotionalTotalCollected` fills + an independent `buyingPower` route).
The earlier "fee is zero" is RETRACTED: realized P&L is `exit − entry` and the
commission is charged at fill, so that method was fee-blind by construction.
`commissionsBasisPoints: '0'` is evidence of the fee's SHAPE, never its ABSENCE.
Shape matters at the tails: at P=0.94 Kalshi MLB is `0.0020`/contract and
Polymarket `0.0150`.

**LIVE EXECUTION IS RUNNING, 2026-08-30 16:42Z**, after a ~13h halt.
`LIVE_ORDER status=submitted` ×2, then `EXECUTION status=ok
spent={'dollars': 11.37, 'orders': 4}`, both venues stamping, unreconciled 0.
Both blockers were our own guards, each correct under an assumption the other
could not see: `FILL_ABOVE_LIMIT` withheld a real `avgPx 0.2350` assuming a BUY
on an `ORDER_SIDE_SELL` order, and the reconcile then refused the order for the
price's absence. Fixed at both layers.

**A PAPER ORDER CAN NO LONGER HALT LIVE EXECUTION.** `unreconciled_orders()`
blocked on any stale `submitted` row while `reconcile_live_orders` only selects
`mode==LIVE` / `outcome is None` / matching venue — a permanent latch. Measured:
`08e9385059f46852b160eeab`, `venue='paper:polymarket'`, blocked live for hours
and was never once examined. Now excused with `UNRECONCILABLE_ORDER
... blocks_live=False`; a venue with no reader still blocks, by design, and is
named on every pass.

**`venue_quote_fanin.age_seconds` IS THE CAPTURE'S AGE, NOT A PER-QUOTE AGE.**
32 MLB quotes in one build share it to the decimal. So
`venue_basis_edge.MAX_VENUE_QUOTE_AGE_SECONDS = 45` is an ALL-OR-NOTHING gate on
a race between the venue capture cycle and the board build cycle — 0-of-6 at
64s and 32-of-32 at 4.9s are the same mechanism. Do not tune it as per-quote
staleness. `VENUE_QUOTE_AGE` now emits the uncensored series.

**`#603` IS REOPENED (2026-08-31 01:11Z) — see above. The reading below is
DISCRIMINATING FOR COLLISIONS ONLY and cannot see an off-slate ref.**
Board 06:18:37Z: 0 of 96
refs answer more than one fixture, 0 rows served by one, 0 wrong-game headline
prices — against 192 contested keys and 992 rows of opportunity, with 166
matched rows sitting on contested keys.

**`POLYMARKET_MEASURED_NOTIONAL_RATE = 0.015` IS KNOWN WRONG BELOW p≈0.43.**
Probe of `C65VD0R72KDG`: actual commission `$0.1400` against a predicted
`$0.197`; `$0.010663`/contract at a 0.235 fill. The five fitted fills sit at
0.43-0.47, straddling the p=0.4620 point where per-contract and per-cost models
are identical by construction.

**THE VENUE BASIS IS WIRED AND UNMEASURED.** `venue_basis_edge` runs end to end
(809/809 rows carried the key) and `servable=False` on every row. **No reading
has yet produced a single scored comparison** — its one live slate refused all
six eligible rows before the arithmetic. Do not lift `servable` without one.
