# UEFA pricing vs the de-vigged close: the Stage 1 go/no-go gate (todo #699 step 3) — 2026-10-16

Lane `uefa-close-backtest`, session 436c79e2. Research only: nothing in this lane touches the sim,
the board, a worker, `render.yaml` or a deploy. Stage 0 keeps serving no UEFA projection whatever
this finds; a GO licenses a separately registered serving design, not an enable.

Builds on: `findings_2026-10-16_uefa_league_offsets.md` (step 2), `..._uefa_offsets_recency_prod.md`
(item (i): CONST offsets on production's scale), `..._uefa_outscope_ratings.md` (item (ii):
out-of-scope ratings, FITTED arm).

## 1. PRE-REGISTRATION (committed BEFORE any close is pulled)

Before this was written, only these were read: 3 probe snapshots (30 credits) to establish that the
endpoint answers, how far back it goes (UCL 2020-10-20: 16 events, Pinnacle on most) and that
qualifiers are barely listed (UECL 2024-07-25: 1 event on a full qualifying night), plus ESPN
kickoff counts. No close was joined to a match and no model probability was compared with one.
Any later change is a deviation with its own dated line in section 5, never an edit here.

### Question

**Does the model add information to the de-vigged closing price on UEFA main-draw 1X2?** The
close is expected to beat the model on its own (domestically it wins by +0.022 log loss), so the
gate is a BLEND: does a walk-forward mix of model and close beat the close alone?

### Matches

- ESPN UEFA results in the research root `C:/tmp/uefa-offsets` (step 1), **main draw only**
  (`stage != "qualifying"`), UCL / UEL / UECL, kickoff on or after **2020-06-06** (the start of
  OddsAPI's historical odds). That is ESPN's 925 UCL, 1,055 UEL and 747 UECL rows (665 distinct
  kickoff windows). Qualifiers are out: OddsAPI barely lists them, and they are not what Stage 1
  would price.
- 90-minute 1X2 result. Extra time / penalties count as a draw; finals are neutral. Both rules are
  as in steps 2 and (ii).

### The close

- **Source:** OddsAPI `/v4/historical/sports/{soccer_uefa_champs_league | soccer_uefa_europa_league
  | soccer_uefa_europa_conference_league}/odds`, `regions=eu`, `markets=h2h`, decimal. Take ONE
  snapshot per distinct ESPN kickoff minute per competition, requested at **kickoff − 5 minutes**.
  A snapshot is used for an event only if its timestamp is before that event's `commence_time`
  (pre-match).
- **Pull:** `scripts/backfill_uefa_historical_closes.py`. It is dry-run by default, aborts on 3
  consecutive failures, and has a hard `--max-credits 12000`. The estimate is 665 × 10 = 6,650
  credits, about 0.13% of the 5M monthly cap. Credits come from `x-requests-last` and are reported.
- **Probability:** **Pinnacle** where it quotes all three outcomes, de-vigged proportionally
  (`market_anchoring.devig_decimal_odds`). Otherwise the mean over every `eu` book quoting all
  three, each de-vigged proportionally. Counts by source are reported.
- **Join (ESPN match -> OddsAPI event):** candidates are the snapshot's events with
  `|commence_time − ESPN kickoff| ≤ 60 min`. Names are normalised (lower case, accents stripped,
  punctuation and club-form tokens such as `fc cf ac sc ssc as afc club de` removed) and scored
  with difflib's ratio. A candidate's score is min(home, away), in either orientation; a swapped
  orientation maps the probabilities back. The best candidate is accepted if its score is ≥ 0.60
  and no other candidate is within 0.05 of it. **The join is AUDITED BEFORE ANY SCORING:** every
  accepted pair below 0.85 and every unmatched match is listed. A wrong pair is fixed by an
  explicit alias, recorded in section 2. Unmatched matches are counted, never dropped silently.

### The model (frozen at July 1 of each test season S)

Exactly what items (i) and (ii) measured, refit walk-forward:

- In-scope club: production's `compute_team_ratings` as of the kickoff day (`ProdRatingIndex`:
  Understat window 45 for the big 5, football-data window 90 for the rest, the fleet's disk depth,
  the Sporting CP alias), mapped to effective `A = β·a + o_L`, `D = β·d + o_L` by the **CONST** fit
  on cross-league matches of 2014..S−1.
- Both clubs in-scope (cross- or same-league): the CONST model, `μ, η, β, o` from that fit.
- Any OOS club: the item (ii) **FITTED** model: 365-day weights to July 1 of S, τ by the inner
  walk-forward on the registered grid, `μ, η` refit, trained on all eligible ≥1-OOS matches
  2014..S−1 (qualifiers included, as in item (ii)).
- Excluded and counted, from every arm: an in-scope club with no production rating or with < 5
  rated matches.
- 1X2 from independent Poisson, truncated at 10 goals.

### Arms, split and metric

- **Test seasons S = 2020 .. 2026** (2020 = 2020-21; 2026 is partial), main draw, joined
  matches only. Every arm scores the same matches.
- **MODEL**, **CLOSE**, and **BLEND** `p = w·p_model + (1 − w)·p_close`. `w` for season S is the
  grid value in {0, 0.05, …, 1} with the lowest mean log loss over all joined held-out matches of
  seasons 2020..S−1, pooled across competitions; ties go to the smaller w. **BLEND is scored on
  S = 2021..2026** (2020 has no history to fit w).
- Per-match 1X2 log loss; paired differences; 95% CI by bootstrap over matches (2,000 resamples,
  seed 699).

### Verdicts

- **H-BLEND (primary), per competition (UCL, UEL, UECL) and pooled:** Δ = LL(BLEND) − LL(CLOSE),
  seasons 2021-2026.
  - **GO** if the CI lies entirely below 0.
  - **NO-GO / NOT DEMONSTRATED** if the point estimate is below 0 and the CI includes 0.
  - **NO-GO / FALSIFIED** if the point estimate is ≥ 0. That means the model adds nothing the
    close does not already have.
  - The per-competition verdicts are the gate. Stage 0's guards may only be lifted for a GO
    competition, and only after a separate serving registration.
- **Reported, no verdict:** Δ = LL(MODEL) − LL(CLOSE) per competition (expected > 0); Brier;
  per season; the w trajectory; pair type (in/in, in/OOS, OOS/OOS); league or group phase vs
  knockout; close source (Pinnacle vs average); calibration of MODEL and CLOSE by
  close-favourite probability decile.

### What this does NOT establish

- **Betting profit.** Only closes are pulled. A CLV or ROI test needs bet-time prices (earlier
  snapshots); a GO here is about information, not money.
- **Qualifiers**, and **two-legged aggregate state**: second legs are priced as ordinary matches.
- **Live / in-play pricing.**
- **Whether a blend can be served.** It needs a live close at serve time, which is a serving-design
  question.

## 2. Coverage and the pre-scoring join audit

(written after the pull and the join audit, BEFORE any model probability was compared with a close)

- **Pull:** 665 snapshots (UCL 303, UEL 201, UECL 161 kickoff windows), **6,240 credits** from
  `x-requests-last`, 0 failures, recorded in the platform quota ledger (`oddsapi_quota`,
  sport=soccer). 41 snapshots came back empty. Raw files: `C:/tmp/uefa-closes/raw/`.
- **Join** (`scripts/backtest_uefa_vs_close.py join`, `C:/tmp/uefa-closes/joined.json`): **2,474 of
  2,727 main-draw matches joined**: UCL 901 / 925, UEL 1,035 / 1,055, **UECL 538 / 747**.
  The close is Pinnacle on **2,201** and the book average on 273. 0 joins needed the swapped
  orientation.
  - Unmatched: 218 `no_candidate` and 35 `low_score`.
    - 206 of the `no_candidate` are UECL: 141 in 2021-22, the competition's first season, and
      65 in the autumn of 2022-23. OddsAPI did not carry it then. Every other cell has 3 or fewer.
    - The `low_score` cases are events missing from OddsAPI's snapshot: 31 of 35 are 2021-22
      UCL/UEL, mostly group matchdays 1-2 (e.g. 3 of 6 UCL 19:00 games listed on 2021-09-14). Two
      are the Cercle Brugge mislabel below. They are not name misses.
  - **Every accepted pair below 0.85 was read: 50 distinct name pairings, all correct** (e.g.
    `Sporting CP` -> `Sporting Lisbon`, `RB Salzburg` -> `Salzburg`, `Hapoel Be'er` -> `Hapoel Beer
    Sheva FC`).
- **Deviation 1 (aliases for MISSED pairs, decided before scoring).** The registration provides
  an alias only for a WRONG pair. A sweep of the missed joins where one club matched ≥ 0.8 found
  18 name gaps: `Ajax Amsterdam` -> `Ajax`/`AFC Ajax`, `Stade Rennais` -> `Rennes`,
  `Racing Genk` -> `Genk`, `Zenit St Petersburg` -> `Zenit`, `Internazionale` -> `Inter Milan`,
  and 13 more (see `ALIASES` in the driver). They are added as ALTERNATIVE names; the ESPN name is
  still tried, and the best "ok" join wins.
  - Effect: joins went from 2,269 to 2,474. Without the aliases, Ajax (56 matches) and Rennes
    would be dropped wholesale, which would bias the sample.
  - **One pairing from the same sweep is WRONG and was refused:** OddsAPI labels Cercle Brugge's
    UECL matches `Club Brugge`. Those 2 matches stay unjoined.
- **Snapshot year of the joined closes:** 2020 264, 2021 248, 2022 294, 2023 404, 2024 440,
  2025 529, 2026 295 (calendar year of the snapshot).

## 3. Results

Run 2026-10-16 at Idle priority, after `3285328a` (closes, join, audit and code on main before any
scoring). Driver: `scripts/backtest_uefa_vs_close.py run`. Output:
`C:/tmp/uefa-closes/report_close.json` (research root, not git).
**2,474 joined main-draw matches were scored, 0 excluded.** By pair: in/in 911, in/OOS 1,029,
OOS/OOS 534. **2,120 are in the blend seasons (2021-2026).**

### THE GATE: NO-GO for all three competitions

| competition | n (2021-26) | Δ LL BLEND − CLOSE | 95% CI | verdict |
|---|---|---|---|---|
| **UCL** | 765 | −0.0006 | [−0.0039, +0.0029] | **NO-GO / NOT DEMONSTRATED** |
| **UEL** | 817 | +0.0025 | [−0.0013, +0.0062] | **NO-GO / FALSIFIED** |
| **UECL** | 538 | +0.0013 | [−0.0029, +0.0056] | **NO-GO / FALSIFIED** |
| pooled | 2,120 | +0.0011 | [−0.0011, +0.0033] | NO-GO / FALSIFIED |

- **The model adds no information to the de-vigged close that survives out of sample.** The
  walk-forward blend weight w fell every season: 0.35 (2021), 0.30, 0.20, 0.15, 0.10, **0.05
  (2026)**. With each added season of evidence, the blend leaned further toward "trust the close".
- **Stage 0's guards stay in place for UCL, UEL and UECL.** No serving registration is licensed.

### The model alone vs the close (reported, no verdict)

| | n | MODEL LL | CLOSE LL | Δ MODEL − CLOSE | 95% CI |
|---|---|---|---|---|---|
| all (2020-26) | 2,474 | 0.9503 | 0.9218 | **+0.0286** | [+0.0184, +0.0388] |
| UCL | 901 | 0.9083 | 0.8894 | +0.0188 | [+0.0035, +0.0339] |
| UEL | 1,035 | 0.9679 | 0.9368 | +0.0310 | [+0.0154, +0.0458] |
| UECL | 538 | 0.9871 | 0.9471 | +0.0400 | [+0.0169, +0.0638] |

- Δ Brier MODEL − CLOSE: UCL +0.0125, UEL +0.0203, UECL +0.0272 (all CIs above 0).
- **By pair type** the model trails the close about equally:
  - in/in +0.026 [+0.012, +0.040] and in/OOS +0.026 [+0.011, +0.042];
  - OOS/OOS +0.038 [+0.013, +0.063].
  - **So the out-of-scope ratings are not the weak link.** The gap is the same where every club
    carries a production rating. Blend − close is −0.0003 [−0.0040, +0.0030] for in/OOS,
    +0.0020 for in/in and +0.0021 for OOS/OOS.
- League/group phase +0.029 and knockout +0.028: the same gap.
- Pinnacle closes +0.031 (n 2,201) and book-average closes +0.011 [−0.021, +0.046] (n 273). The
  model gets nearer a softer close, as expected.
- **Per season** the gap WIDENS: 2020 +0.011, 2021 +0.022, 2022 +0.025, 2023 +0.034,
  2024 +0.032, 2025 +0.036, 2026 (90 matches) +0.040. Blend − close is within ±0.003 of 0 in every
  season.

### Engine read (beyond the verdict)

- **The model underrates favourites, exactly as it does domestically.** By decile of the close's
  favourite probability:

  | decile | close fav | model fav | actual |
  |---|---|---|---|
  | 1 | 0.374 | 0.395 | 0.435 |
  | 5 | 0.524 | 0.506 | 0.547 |
  | 6 | 0.563 | 0.528 | 0.619 |
  | 9 | 0.726 | 0.671 | 0.753 |
  | 10 | 0.821 | 0.778 | 0.854 |

  - From the 5th decile up, the model sits 2-5 points BELOW the close and the close sits below
    the actual rate.
  - So the market itself underrates UEFA favourites slightly, and the model underrates them more.
  - This is the domestic finding of lane `soccer-team-strength` again (top-decile domestic model
    0.743 / close 0.804 / actual 0.821): **the gap is information the rating never sees**
    (lineups, injuries, squad quality, rotation, market). It is not specific to UEFA, and it is
    not the offsets or the OOS ratings.
- **The size of the gap matches the domestic one** (+0.029 here, +0.022 domestically). The UEFA
  machinery (offsets + OOS ratings) carries production's rating to UEFA at about the same quality,
  so the weakness is upstream, in the rating itself.
- **The widening gap over seasons** fits a market that has sharpened since 2020 while the rating
  stayed fixed. It also fits the drift found in item (i) (the EPL pulling away), which the CONST
  offset deliberately does not chase. Neither cause was tested.

## 4. What cannot be estimated

- **Betting value.** There are no bet-time prices; a CLV test needs earlier snapshots. With blend −
  close at about 0 there is no evidence of an edge to look for, but this did not test one.
- **Qualifiers** (not on OddsAPI) and **UECL 2021-22 plus autumn 2022** (206 matches OddsAPI did
  not carry).
- **Whether better domestic information would pass the gate.** That is the domestic problem lane
  `soccer-team-strength` is on, and this gate inherits whatever it finds.

## 5. Deviations from the registration

- **1. Aliases for MISSED join pairs** (section 2), decided after the join audit and before any
  scoring. Joins went from 2,269 to 2,474. One sweep pairing (Cercle Brugge -> Club Brugge) was
  wrong and was refused.
- **2. Name normalisation detail** (decided before any join was run): `normalise_name`
  transliterates the letters NFKD does not decompose (ø, æ, ß, ł, đ, ı, þ, ð), and drops dots so
  that `F.C.` becomes the dropped token `fc`. Both are within "accents stripped, punctuation …
  removed" and were found by a unit test, not by the data.
