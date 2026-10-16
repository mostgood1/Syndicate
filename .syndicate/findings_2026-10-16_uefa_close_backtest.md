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

## 4. What cannot be estimated

## 5. Deviations from the registration
