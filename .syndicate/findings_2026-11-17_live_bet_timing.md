# Live betting by game shape: when do live totals, spreads and moneylines pay? (2026-11-17)

Lane `live-bet-timing-by-game-shape`, session b1d2088f. Read-only. User 2026-11-17: "determine if there are ideal times in
game shape of each sport to live bet totals/spreads/mls - based on momentum, timing, game shape etc". Hypotheses H1-H3 and
their falsification were written into the lane (`9326ac378`) before any grading. Written ~4:00 PM CST.

## Method

- **Records:** each sport's fleet live game-line ledger (`~/syndicate-prod/data/<sport>_source/data/live_gameline_ledger/`),
  read in place. Population: PRICED (`priceable`) FULL-GAME records of h2h / spreads / totals; the NBA alternates are
  graded but kept apart.
- **Game time:** each record is placed at `recorded_at - 20 s` in ESPN's play-by-play (wallclock, period, clock, score).
  Finals come from ESPN; pushes are dropped. Only MLB's ledger carries a game clock of its own (inning/outs); no other
  sport's does, so ESPN plays are the clock.
- **Cuts:**
  - phase: the share of regulation elapsed, 0-25 / 25-50 / 50-75 / 75-90 / 90-100 %, or OT.
  - margin: close or lopsided. Basketball <= 5 / >= 15, football <= 7 / >= 17, hockey <= 1 / >= 3.
  - totals pace: points so far vs the record's own line x share elapsed, < 0.9 or > 1.1.
  - run: the net score change in the last 4 min (basketball), 10 min (football and hockey) of game clock.
    Basketball needs >= 8, football >= 7, hockey >= 1 goal.
  - totals heat: that window's points vs the line's pace, > 1.3 or < 0.7.
  - vs_run / vs_heat: whether a flag leans with the run (the side that just scored, or the over after a hot window) or against it.
- **Metrics:**
  - (A) flags (|edge_pp| >= 3): hit - fair, where fair is the de-vigged price of the leaned side.
  - (B) market: y - p_market for the home / over side. For runs it is signed to the run side, so a negative value means
    the market OVER-reacted.
  - Every mean is per GAME first, then across games. The 90% CI uses the game-clustered SE.
- **The control that decides most of this:**
  - **CLEAN**: the quote is no older than the last ESPN score change at pricing (the book had seen the score).
  - **FRESH**: clean AND the quote is <= 60 s old.
  - Clean records: NCAAB 44% (36,373 / 81,656); NBA 27% (61,926 / 229,445); NCAAF 81%; NFL 93%; NHL 90%; WNCAAB 44%.
  - Fresh records: NCAAB 15,707; NBA 15,926; NCAAF 16,463.
  - **An effect that disappears on clean / fresh quotes is the book's stale quote, not an edge anyone can take.**
- **Coverage, by sport** (dates are ledger slates):

| sport | ledger dates | graded records | games |
|---|---|---|---|
| NCAAB | 11-02..11-16 | 81,656 | 541 |
| NBA | 10-20..11-16 | 229,445 | 192 |
| NCAAF | 10-01..11-15 | 125,461 | 306 |
| WNCAAB | 11-03..11-16 | 8,522 | 123 |
| NFL | 10-01..11-16 | 979 (h2h only) | 67 |
| NHL | 11-09..11-16 | 623 (h2h only) | 43 |
| WNBA | 09-30..10-31 | 489 | 17, INSUFFICIENT |

  MLB (postseason, ledger has its own inning field) and soccer (per-league ESPN paths) are NOT covered.
- **Script:** `scripts/live_bet_timing_study.py` (main). Tables: `C:\tmp\livetiming\summary.py` / `report.py` over the per-sport
  JSONs in `C:\tmp\livetiming\`.
- **Caveats:**
  - The price is the ledger's quote at pricing; whether a bettor could still get it is not measured (FRESH is the closest proxy).
  - Many cuts are read at once, so a single cell clearing its CI is a CANDIDATE, not a finding.
  - These are the ledger's model flags (|edge| >= 3), not the rail's flag rule.
  - The NCAAB window is mostly before the #816 calibration (loaded 11-17 00:04Z).

## What holds on FRESH quotes (the answer)

1. **LATE IS WHERE THE FLAGS EARN -- in college. H1 SUPPORTED for NCAAB and NCAAF; NOT for NBA.**
   - NCAAB totals flags, hit - fair by phase (fresh): 0-25 +3.4, 25-50 +0.7, 50-75 +2.3, 75-90 +3.9, **90-100 +13.8 +- 3.7 pp (251 games)**.
   - NCAAB spreads: 75-90 +4.5 (fresh); all phases +2.7.
   - NCAAF spreads (fresh): 50-75 +7.4, 75-90 +7.0, 90-100 +8.1. Totals 75-100 +6.1 to +6.4. Moneylines 75-100 +4.8 / +5.0.
   - **NBA: the late edge is the book's stale quote.** Totals flags at 90-100 read +11.5 on all records, -0.1 clean and
     -3.2 fresh. Spreads at 90-100 read +17.4 on all, +7.9 clean and -6.6 fresh (31 games).
2. **MOMENTUM: the live market does NOT over-react to runs. H2 FALSIFIED as stated.** What helps is RIDING the run.
   - The market's run-side residual is >= 0 everywhere: NCAAB spreads +2.5 clean / +5.5 fresh (224 games); NCAAF +0.8
     fresh; NBA +8.7 clean (87 games).
   - On all records the market looked to UNDER-react (NCAAB +6.2, NBA +17.5); half or more of that is stale quotes.
   - **Our flags that agree with the run beat the ones that fade it.**
     - NCAAB spreads, fresh: with the run +7.2 (172 games), against -4.3 (122).
     - NCAAB totals, fresh: with the heat (over after a hot window, under after a cold one) +11.3 (289), against -0.5 (297).
     - WNCAAB totals: with +16.5 (63), against +3.8 (66).
     - NCAAF totals, fresh: with +3.5, against +2.1 (weak).
3. **TOTALS: UNDERS -- except when a game is running ahead of the line's pace.**
   - Under flags beat their price on fresh quotes: NCAAB +8.3 (429 games), NCAAF +10.7 (255), WNCAAB +7.3 (104), NBA +8.6
     (52, CI includes 0).
   - Over flags are ~0 (NCAAB +0.9, NCAAF +3.0, NBA -3.6).
   - Finals land under the live over price, most of all in the last 10% of regulation: NCAAB -9.0 +- 4.0 fresh (251
     games), NCAAF -8.4 +- 5.7 (164).
   - The exception: NCAAB games scoring AHEAD of the line's pace (> 1.1x). There the over is under-priced (+8.1 clean,
     125 games) and over flags hit +20.5 clean (80 games); fresh +5.2 (93 games, CI includes 0).
   - **H3 (lopsided games go under) NOT SUPPORTED specifically.** The under lean is no stronger in lopsided games than in close ones.
4. **MONEYLINES: avoid early; in pro football and hockey the AWAY side is the value.**
   - NCAAB model ML flags lose in the first half of regulation: fresh -11.3 at 0-25 (102 games); -7.1 clean in close games
     (246). NBA early ML flags -13 (all / clean).
   - NFL live market over-prices the HOME team: home y - p -8.7 fresh (57 games), -14 to -16 early. Our home ML flags lose
     -18.3 fresh (34 games).
   - NHL is the same: home -11.2 fresh (42 games), -16 to -22 in the first half. Home flags -14.2.
   - WNCAAB is the reverse: home ML UNDER-priced, +10.3 fresh (56 games); home flags +18.8 (32 games).
   - NCAAF ML flags pay late (+5.0 fresh at 90-100) and in lopsided games (+10.5 fresh, 80 games).
5. **NBA overall:** almost every NBA live edge in the ledger vanishes on clean / fresh quotes. NBA live flags are mostly
   priced against quotes that had not seen the latest basket. The NBA in-play quote cadence was 60 s only from #811
   (11-16); most of this window was 240 s.

## Candidates to pre-register forward (not findings; each rests on one descriptive read)

- **C1** College late game: NCAAB and NCAAF flags in the last 25% of regulation, on fresh quotes, beat their price; first-half flags do not.
- **C2** College totals: unders beat their price and overs do not, except NCAAB games running > 1.1x the line's pace (overs).
- **C3** Ride the run: NCAAB flags that agree with the last 4 minutes' run or scoring heat beat their price; flags that fade it do not.
- **C4** Pro live moneylines (NFL, NHL): the home side is over-priced in play, so the away side is the value; WNCAAB the reverse.
- **C5** NCAAB model moneylines in the first half of regulation lose to the price.
- **C6** NBA: no live edge survives on fresh quotes. Re-read after a month of #811's 60 s pull.
- None of these changes anything. Acting on one -- e.g. a rail cue for late college flags, or a phase-aware refusal --
  is the user's call, after a forward pre-registered read. Per the user's rule, every line stays its own decision: a cue
  or refusal would key on the row's own state, not switch a market off.

## Appendix: cross-population summary (main markets; `summary.py`)

```

######## NCAAB (541 games, 15 days)
  totals   cut                | FLAGS hit-fair: all / clean / fresh                   | MARKET y-p home/over: all / clean / fresh
           all all            |   +3.9+- 1.9 540g+   +2.9+- 2.1 535g+   +2.5+- 2.4 466g+ |   -3.4+- 2.5 540g-   -5.1+- 2.6 535g-   -4.4+- 2.9 466g-
           phase 0-25         |   +1.5+- 3.2 456g    +1.4+- 3.6 401g    +3.4+- 4.2 301g  |   -3.6+- 3.5 456g-   -6.7+- 3.8 401g-   -9.5+- 4.4 301g-
           phase 25-50        |   +1.0+- 2.8 514g    -0.5+- 3.1 463g    +0.7+- 3.7 362g  |   -1.2+- 3.2 514g    -3.3+- 3.4 463g    -4.1+- 3.9 362g-
           phase 50-75        |   +2.6+- 2.3 534g+   +2.6+- 2.6 512g    +2.3+- 3.1 385g  |   -2.0+- 2.8 534g    -3.4+- 2.9 512g-   -2.7+- 3.4 385g 
           phase 75-90        |   +6.9+- 2.4 521g+   +6.7+- 3.0 416g+   +3.9+- 3.8 286g+ |   -3.9+- 2.8 521g-   -5.3+- 3.3 416g-   -4.1+- 4.0 286g-
           phase 90-100       |  +15.6+- 2.1 507g+  +15.6+- 2.8 391g+  +13.8+- 3.7 251g+ |   -9.2+- 2.5 507g-  -12.0+- 3.0 391g-   -9.0+- 4.0 251g-
           margin close       |   +2.0+- 2.7 441g    +2.6+- 3.0 395g    +3.8+- 3.5 318g+ |   -3.2+- 3.2 441g    -5.7+- 3.4 395g-   -7.6+- 3.9 318g-
           margin lopsided    |   +7.0+- 2.7 334g+   +5.7+- 3.1 293g+   +2.8+- 3.9 239g  |   -3.5+- 3.1 334g-   -5.0+- 3.5 293g-   -4.0+- 4.1 239g 
           pace behind        |   +3.4+- 2.8 422g+   +3.6+- 3.1 383g+   +3.2+- 3.5 290g  |   -2.6+- 3.3 423g    -5.7+- 3.4 384g-   -7.7+- 3.9 290g-
           pace ahead         |   +8.9+- 4.5 189g+  +11.4+- 5.3 125g+   +8.9+- 6.6  93g+ |   +7.8+- 4.8 189g+   +8.1+- 5.6 125g+   +5.2+- 6.9  93g 
           heat cold          |   +6.4+- 2.7 465g+   +4.0+- 3.1 400g+   +6.5+- 3.9 279g+ |   -5.8+- 3.1 465g-   -6.5+- 3.4 401g-   -6.0+- 4.1 279g-
           heat hot           |   +3.5+- 2.5 490g+   +5.9+- 3.0 382g+   +3.8+- 3.8 289g+ |   +0.7+- 2.8 490g    -1.3+- 3.3 382g    +1.5+- 4.0 289g 
           flags over         |   +5.5+- 2.8 506g+   +1.3+- 3.1 440g    +0.9+- 3.7 338g  |
           flags under        |   +9.2+- 2.5 530g+   +9.9+- 2.7 502g+   +8.3+- 3.0 429g+ |
           flags with_heat    |  +13.7+- 2.3 496g+  +11.7+- 2.8 408g+  +11.3+- 3.5 289g+ |
           flags against_heat |   -2.3+- 2.7 489g    -0.8+- 3.2 412g    -0.5+- 3.9 297g  |
  spreads  cut                | FLAGS hit-fair: all / clean / fresh                   | MARKET y-p home/over: all / clean / fresh
           all all            |   +3.7+- 1.7 541g+   +3.9+- 2.0 537g+   +2.7+- 2.4 468g+ |   -2.5+- 2.5 541g    -3.0+- 2.6 537g-   -1.4+- 3.0 468g 
           phase 0-25         |   +3.3+- 3.1 437g+   +3.8+- 3.6 360g+   +2.3+- 4.6 237g  |   -1.4+- 3.6 437g    -1.8+- 4.0 360g    -2.4+- 5.0 237g 
           phase 25-50        |   +2.2+- 2.8 510g    +2.1+- 3.2 436g    +3.6+- 3.9 320g  |   -1.8+- 3.2 510g    -2.0+- 3.5 436g    +1.6+- 4.2 320g 
           phase 50-75        |   +3.4+- 2.4 532g+   +3.3+- 2.7 508g+   +3.5+- 3.5 371g  |   -2.4+- 2.9 532g    -3.1+- 3.0 508g-   -2.9+- 3.8 371g 
           phase 75-90        |   +5.8+- 2.5 515g+   +6.7+- 3.2 409g+   +4.5+- 4.3 256g+ |   -2.4+- 2.9 515g    -2.6+- 3.5 409g    -5.6+- 4.5 256g-
           phase 90-100       |   +9.5+- 2.2 508g+   +7.6+- 3.1 385g+   +1.8+- 4.4 234g  |   -2.4+- 2.7 508g    -0.2+- 3.4 385g    -0.5+- 4.6 234g 
           margin close       |   +2.8+- 2.6 423g+   +4.1+- 3.0 376g+   +4.8+- 3.6 279g+ |   +2.4+- 3.3 423g    +1.0+- 3.6 376g    +1.1+- 4.3 279g 
           margin lopsided    |   +3.0+- 2.7 331g+   +2.5+- 3.3 297g    -0.5+- 4.0 229g  |   +0.3+- 3.3 331g    -0.6+- 3.8 297g    +0.2+- 4.4 229g 
           run none           |   +3.8+- 1.8 540g+   +3.8+- 2.1 536g+   +2.9+- 2.6 450g+ |   -2.4+- 2.5 540g    -2.1+- 2.7 536g    -2.1+- 3.1 450g 
           run run            |   +5.3+- 2.7 422g+   +4.6+- 3.5 339g+   +3.6+- 4.4 224g  |   -0.9+- 3.2 422g    -1.6+- 3.8 339g    -0.3+- 4.8 224g 
           flags home         |   +0.7+- 2.7 529g    +0.4+- 2.9 494g    -0.2+- 3.3 407g  |
           flags away         |   +8.3+- 2.7 527g+   +8.2+- 2.9 477g+   +5.1+- 3.6 360g+ |
           flags with_run     |   +8.6+- 3.3 366g+   +6.6+- 4.2 266g+   +7.2+- 5.4 172g+ |
           flags against_run  |   -3.1+- 4.1 282g    +0.9+- 5.1 203g    -4.3+- 6.7 122g  |
           mkt run-side y-p   |                                                      |   +6.2+- 3.0 422g+   +2.5+- 3.6 339g    +5.5+- 4.7 224g+
  h2h      cut                | FLAGS hit-fair: all / clean / fresh                   | MARKET y-p home/over: all / clean / fresh
           all all            |   -3.3+- 2.0 390g-   -4.0+- 2.4 347g-   -4.2+- 3.3 236g- |   +1.7+- 2.5 414g    +1.6+- 2.8 359g    +2.2+- 3.5 251g 
           phase 0-25         |   -6.7+- 3.8 230g-   -5.9+- 4.6 161g-  -11.3+- 6.1 102g- |   +3.4+- 3.9 235g    +3.8+- 4.6 165g    +2.5+- 6.1 106g 
           phase 25-50        |   -5.7+- 3.5 258g-   -6.5+- 4.7 165g-   -3.3+- 6.3  95g  |   +1.6+- 3.5 278g    +1.5+- 4.8 176g    +1.5+- 6.3 104g 
           phase 50-75        |   -2.4+- 3.3 254g    -2.9+- 3.9 206g    -4.4+- 5.6 112g  |   +1.4+- 3.5 270g    +1.4+- 4.0 218g    +0.9+- 5.5 120g 
           phase 75-90        |   -2.2+- 4.0 185g    -3.2+- 5.5 104g    -0.4+- 8.9  50g  |   +1.3+- 4.0 206g    +3.4+- 5.5 111g    -0.2+- 8.4  55g 
           phase 90-100       |   +2.5+- 3.3 165g    -0.6+- 4.6 100g    +3.4+- 5.7  51g  |   +1.2+- 3.3 186g    +1.2+- 4.3 109g    +4.1+- 5.5  54g 
           margin close       |   -4.8+- 3.0 303g-   -7.1+- 3.7 246g-   -8.4+- 4.9 157g- |   +1.6+- 3.5 306g    +0.4+- 4.1 246g    +0.0+- 5.3 157g 
           margin lopsided    |   +4.5+- 2.4  85g+   +3.5+- 3.2  46g+   +4.1+- 5.6  25g. |   +2.1+- 1.9 118g+   +3.6+- 2.3  63g+   +4.7+- 3.8  36g+
           run none           |   -3.4+- 2.2 379g-   -4.5+- 2.7 324g-   -4.8+- 3.7 209g- |   +1.8+- 2.6 399g    +1.5+- 3.0 333g    +2.3+- 3.8 222g 
           run run            |   +0.7+- 3.5 168g    +1.2+- 5.1 104g    -2.4+- 7.6  56g  |   +2.4+- 3.6 184g    +1.6+- 5.0 113g    +4.0+- 7.3  62g 
           flags home         |   -1.0+- 3.5 264g    -1.9+- 3.9 208g    -0.6+- 5.5 118g  |
           flags away         |   -3.7+- 3.0 318g-   -4.2+- 3.6 253g-   -5.8+- 4.4 167g- |
           flags with_run     |   +3.4+- 4.6 112g    +4.6+- 6.2  70g    -4.2+- 9.1  39g  |
           flags against_run  |   -5.1+- 5.3  88g    -5.9+- 8.6  47g    -4.2+-14.0  22g. |
           mkt run-side y-p   |                                                      |   +3.6+- 3.1 184g+   +4.5+- 4.6 113g    -0.8+- 6.5  62g 

######## NBA (192 games, 27 days)
  totals   cut                | FLAGS hit-fair: all / clean / fresh                   | MARKET y-p home/over: all / clean / fresh
           all all            |   +6.9+- 3.2 192g+   +1.3+- 4.9 174g    -0.6+- 7.6  83g  |   -2.2+- 4.4 192g    -4.0+- 5.1 174g    -6.7+- 7.7  83g 
           phase 0-25         |   +2.2+- 5.5 159g    +5.1+- 9.2  73g    -5.9+-17.4  21g. |   -4.4+- 6.1 159g    -3.4+- 9.4  73g    +6.5+-17.3  21g.
           phase 25-50        |   +5.5+- 5.0 182g+   +6.6+- 8.5  80g    +3.6+-13.7  32g  |   -0.2+- 5.7 182g    -3.7+- 8.8  80g    -6.0+-13.9  32g 
           phase 50-75        |   +7.2+- 4.4 190g+   +3.8+- 6.1 153g    +5.0+-11.1  46g  |   -4.8+- 5.2 190g    -5.1+- 6.3 153g    -6.4+-11.4  46g 
           phase 75-90        |   +9.3+- 4.1 185g+   +4.3+- 7.4  96g    +1.6+-12.5  34g  |   -4.6+- 5.4 185g    -8.0+- 7.9  96g-   -0.3+-13.4  34g 
           phase 90-100       |  +11.5+- 4.1 178g+   -0.1+- 7.7  81g    -3.2+-10.8  41g  |   -3.7+- 5.2 178g    -3.6+- 8.1  81g    -8.5+-11.3  41g 
           margin close       |   +2.2+- 4.5 172g    +1.2+- 7.0 107g    -8.3+-11.5  42g  |   -2.5+- 5.4 172g    +1.6+- 7.2 107g    +3.2+-11.8  42g 
           margin lopsided    |   +9.6+- 5.0 123g+   +3.9+- 8.3  74g    +1.7+-13.1  32g  |   -4.0+- 6.2 123g    -6.3+- 8.7  74g   -12.8+-13.1  32g 
           pace behind        |   +3.1+- 7.2  99g    -5.6+-11.6  46g   -13.9+-24.2  10g. |   -3.5+- 7.6  99g    +6.3+-11.9  46g    +5.0+-25.8  10g.
           pace ahead         |   +7.4+- 8.3  76g    +8.7+-17.2  24g.   -7.3+-33.1   7g. |   +4.5+- 8.8  76g   -13.2+-16.8  24g.   +6.9+-33.1   7g.
           heat cold          |  +14.2+- 5.2 160g+   +5.0+- 8.5  79g    +0.9+-17.1  18g. |  -13.6+- 5.5 160g-   -2.1+- 8.8  79g   -16.2+-17.5  18g.
           heat hot           |   +7.2+- 4.6 169g+   +1.8+- 9.3  58g   +15.3+-12.1  26g. |   +5.8+- 5.3 169g+   -4.4+- 9.5  58g   -15.5+-13.2  26g.
           flags over         |   +7.1+- 4.7 187g+   +1.1+- 6.4 129g    -3.6+-10.2  54g  |
           flags under        |  +10.4+- 4.8 187g+   +9.2+- 6.3 126g+   +8.6+- 9.8  52g  |
           flags with_heat    |  +16.7+- 3.9 178g+   +4.7+- 8.4  79g    +3.4+-15.0  24g. |
           flags against_heat |   -2.0+- 6.2 133g    +4.2+- 8.9  64g    +8.8+-14.7  23g. |
  spreads  cut                | FLAGS hit-fair: all / clean / fresh                   | MARKET y-p home/over: all / clean / fresh
           all all            |   +7.7+- 3.3 192g+   +1.6+- 4.9 176g    +1.1+- 7.4  81g  |   -0.8+- 4.5 192g    -3.1+- 5.3 176g    -0.3+- 8.1  81g 
           phase 0-25         |   -1.5+- 5.8 154g   -10.1+-10.1  58g   -20.4+-15.1  21g. |   +2.2+- 6.3 154g    +2.1+-10.6  58g    -7.4+-17.5  21g.
           phase 25-50        |   +4.8+- 5.3 179g    +0.9+- 8.0  97g    +2.4+-12.7  41g  |   +2.2+- 5.8 179g    +7.7+- 8.1  97g   +13.1+-12.5  41g+
           phase 50-75        |   +9.3+- 4.4 189g+   +0.6+- 6.2 142g    -0.9+-10.9  47g  |   -0.2+- 5.2 189g    -3.6+- 6.4 142g    -0.8+-11.5  47g 
           phase 75-90        |   +9.6+- 4.3 184g+   +8.7+- 7.3 103g+   +7.3+-11.7  36g  |   -4.9+- 5.3 184g   -14.3+- 7.4 103g-   -9.0+-12.7  36g 
           phase 90-100       |  +17.4+- 3.7 176g+   +7.9+- 7.8  74g+   -6.6+-11.9  31g  |   -3.9+- 5.0 176g    -3.9+- 8.6  74g    -1.2+-13.1  31g 
           margin close       |   +2.0+- 4.9 165g    -2.5+- 7.3  97g   -10.4+-11.4  37g  |   +0.1+- 5.6 165g    -2.7+- 7.9  97g    -5.6+-13.0  37g 
           margin lopsided    |   +7.2+- 5.6 128g+   +1.8+- 7.8  88g    +2.2+-12.8  34g  |   +0.2+- 6.0 128g    -1.1+- 7.8  88g    +7.2+-12.0  34g 
           run none           |   +6.3+- 3.5 192g+   +3.0+- 5.2 166g    +2.3+- 7.8  73g  |   -1.1+- 4.5 192g    -2.1+- 5.5 166g    +2.0+- 8.5  73g 
           run run            |  +15.5+- 4.4 165g+   -2.7+- 7.9  87g   -11.3+-13.1  25g. |   -0.5+- 5.5 165g    -9.9+- 7.9  87g-  -10.8+-13.4  25g.
           flags home         |   +3.7+- 4.6 181g    -3.9+- 6.5 128g    -3.9+- 9.8  57g  |
           flags away         |   +5.9+- 4.9 178g+   +2.9+- 6.7 120g    +2.5+-10.8  50g  |
           flags with_run     |  +18.6+- 4.6 154g+   +1.7+- 9.1  69g    -7.6+-20.2  16g. |
           flags against_run  |   -9.8+- 8.5  78g-  -17.7+-11.4  39g-  -13.5+-16.1  18g. |
           mkt run-side y-p   |                                                      |  +17.5+- 4.2 165g+   +8.7+- 7.6  87g+   +7.7+-14.2  25g.
  h2h      cut                | FLAGS hit-fair: all / clean / fresh                   | MARKET y-p home/over: all / clean / fresh
           all all            |   +1.1+- 3.3 189g    -1.2+- 4.7 140g    -1.1+- 8.0  62g  |   -1.9+- 3.9 189g    -0.5+- 4.9 142g    -0.6+- 8.4  62g 
           phase 0-25         |  -12.9+- 6.2 118g-  -13.3+-10.7  46g-  -14.4+-19.2  18g. |   -1.3+- 6.7 118g    -4.3+-11.3  46g   -11.2+-20.2  18g.
           phase 25-50        |   -2.5+- 5.5 143g   -11.6+- 8.5  68g-   +0.4+-16.0  26g. |   -2.0+- 5.8 143g    +7.2+- 8.7  69g    +8.8+-15.7  26g.
           phase 50-75        |   +5.7+- 4.7 147g+   -0.2+- 7.4  81g    -2.1+-12.1  33g  |   +0.5+- 5.0 147g    -0.5+- 7.4  82g    -4.3+-12.2  33g 
           phase 75-90        |   +6.1+- 4.6 117g+   +4.0+- 6.5  52g    -2.5+-10.9  16g. |   -5.0+- 5.0 117g    -7.8+- 6.8  52g-   -9.9+-12.4  17g.
           phase 90-100       |  +10.6+- 2.8 104g+   +8.2+- 5.2  39g+   +2.8+- 9.3  11g. |   -0.5+- 3.6 105g    -2.8+- 5.7  39g    -8.7+- 8.6  11g.
           margin close       |   -4.8+- 5.2 140g    -5.6+- 7.2  84g    -7.7+-11.1  37g  |   -1.4+- 5.7 140g    -1.6+- 7.6  84g    -3.5+-11.9  37g 
           margin lopsided    |   +3.4+- 3.9  99g    -2.4+- 7.8  40g    -2.5+-15.7  11g. |   +0.1+- 3.9 100g    +1.6+- 7.5  42g    +7.2+-15.5  11g.
           run none           |   +1.1+- 3.4 188g    +0.4+- 4.8 131g    -4.5+- 8.4  52g  |   -2.2+- 3.9 188g    -0.9+- 5.0 132g    +1.1+- 8.8  53g 
           run run            |   +3.4+- 4.8 125g    -5.1+- 8.2  55g    +3.4+-15.5  22g. |   +1.2+- 5.2 125g    +4.4+- 8.3  56g    -5.8+-15.6  22g.
           flags home         |   -3.9+- 4.5 140g    -3.8+- 5.7  83g    -5.7+- 9.5  39g  |
           flags away         |   -1.3+- 4.8 147g    -1.7+- 6.3  95g    -0.9+-11.9  35g  |
           flags with_run     |   +5.7+- 5.2 105g+   -4.5+-10.3  39g    +4.4+-24.0  11g. |
           flags against_run  |   -2.5+- 8.6  50g    -7.7+-12.7  25g.   +3.8+-19.0  13g. |
           mkt run-side y-p   |                                                      |   +5.6+- 4.2 125g+   +1.6+- 7.6  56g    -0.8+-15.7  22g.

######## WNCAAB (123 games, 14 days)
  totals   cut                | FLAGS hit-fair: all / clean / fresh                   | MARKET y-p home/over: all / clean / fresh
           all all            |   +6.8+- 4.7 122g+   +5.7+- 5.3 119g+   +4.6+- 5.7 113g  |   -4.3+- 5.6 122g    -6.3+- 5.9 119g-   -3.6+- 6.3 113g 
           phase 0-25         |   +7.4+- 7.0 103g+   +8.2+- 8.0  87g+   +8.3+- 9.1  71g  |   -5.5+- 7.7 103g    -4.6+- 8.5  87g    -4.6+- 9.7  71g 
           phase 25-50        |   +8.0+- 6.5 110g+  +10.5+- 7.2  97g+  +10.1+- 8.1  80g+ |   -6.5+- 7.2 110g    -5.9+- 7.7  97g    -4.6+- 8.7  80g 
           phase 50-75        |   +8.8+- 6.0 114g+   +9.6+- 6.7 110g+   +5.8+- 7.4  94g  |   -4.3+- 6.7 114g    -6.8+- 7.1 110g    -5.3+- 7.8  94g 
           phase 75-90        |   +2.8+- 6.3 102g    +2.1+- 7.4  94g    +2.1+- 8.4  73g  |   -2.9+- 7.4 102g    -3.4+- 8.0  94g    -2.1+- 9.2  73g 
           phase 90-100       |   +5.7+- 6.3  99g    +7.3+- 8.7  65g    +2.7+-10.6  43g  |   +0.1+- 7.2  99g    -2.1+- 9.4  65g    -7.1+-11.3  43g 
           margin close       |   +4.8+- 7.3  85g    +4.2+- 8.0  74g    +6.3+- 8.8  64g  |   -3.0+- 8.0  85g    -2.3+- 8.5  74g    -3.2+- 9.2  64g 
           margin lopsided    |   +3.5+- 6.0  90g    +4.6+- 7.0  85g    +3.6+- 7.5  74g  |   -3.7+- 7.0  90g    -4.8+- 7.8  85g    -6.3+- 8.4  74g 
           pace behind        |  +13.2+- 7.4  79g+  +13.3+- 8.0  68g+  +10.8+- 9.1  53g+ |   -6.4+- 8.4  79g    -4.6+- 9.1  68g    -0.6+-10.6  53g 
           pace ahead         |   +9.7+- 9.8  54g    +7.4+-12.4  37g    +9.8+-14.2  28g. |   -2.2+-10.5  54g    -3.7+-12.8  37g    -3.9+-14.9  28g.
           heat cold          |  +10.6+- 6.8  96g+   +9.3+- 7.5  85g+  +10.9+- 8.5  63g+ |   -6.4+- 7.5  96g    -7.4+- 7.9  85g    -6.8+- 9.3  63g 
           heat hot           |   +3.0+- 5.9 101g    +5.7+- 8.1  71g    +6.2+- 9.5  57g  |   -0.4+- 6.9 101g    -4.2+- 8.7  71g    -2.6+-10.1  57g 
           flags over         |   +6.3+- 6.9  99g    +2.7+- 8.3  76g    +2.8+- 8.9  65g  |
           flags under        |   +8.7+- 5.9 118g+   +9.3+- 6.3 111g+   +7.3+- 6.8 104g+ |
           flags with_heat    |  +15.1+- 6.2 103g+  +14.8+- 7.4  84g+  +16.5+- 8.5  63g+ |
           flags against_heat |   +0.2+- 6.3 100g    +1.1+- 7.7  79g    +3.8+- 8.8  66g  |
  spreads  cut                | FLAGS hit-fair: all / clean / fresh                   | MARKET y-p home/over: all / clean / fresh
           all all            |   +4.8+- 4.8 109g    +3.3+- 5.5 107g    +0.9+- 6.4  92g  |   -0.1+- 6.2 109g    +4.1+- 6.6 107g    +1.4+- 7.4  92g 
           phase 0-25         |   +1.3+- 7.4  85g    +0.5+- 9.7  60g    -3.5+-11.5  44g  |   -3.5+- 8.2  85g    -6.8+- 9.9  60g   -10.7+-11.6  44g 
           phase 25-50        |  +10.9+- 7.0  92g+   +9.2+- 8.6  71g+   +8.4+-10.3  56g  |   +1.0+- 8.0  92g    +3.9+- 9.3  71g    +3.1+-10.7  56g 
           phase 50-75        |   -2.5+- 6.3 101g    -5.1+- 7.2  91g    -5.6+- 8.6  71g  |   +2.3+- 7.5 101g    +1.1+- 8.0  91g    -6.8+- 9.2  71g 
           phase 75-90        |   +4.8+- 6.7  88g    +9.8+- 7.8  79g+   +8.4+- 9.5  55g  |   -2.4+- 7.5  88g    +0.8+- 8.1  79g    -1.4+- 9.8  55g 
           phase 90-100       |  +17.0+- 6.6  73g+   +4.2+-11.1  43g    +8.3+-12.9  33g  |   -5.4+- 8.6  73g    -5.8+-11.3  43g    +2.8+-13.5  33g 
           margin close       |   +8.8+- 7.5  72g+  +10.8+- 8.5  55g+  +16.2+- 9.1  45g+ |   +3.8+- 8.4  72g    +1.6+- 9.7  55g    +5.0+-10.8  45g 
           margin lopsided    |   +1.1+- 6.6  77g    +2.7+- 7.7  72g    -1.2+- 9.2  56g  |   -3.7+- 7.8  77g    -3.9+- 8.4  72g   -10.2+- 9.7  56g-
           run none           |   +5.1+- 5.0 109g+   +3.1+- 5.9 105g    -1.2+- 6.8  85g  |   -0.4+- 6.3 109g    +4.2+- 6.8 105g    +0.7+- 7.7  85g 
           run run            |   +7.0+- 7.2  80g    +8.9+- 9.3  62g    +7.2+-10.7  46g  |   +1.7+- 7.9  80g    +1.9+- 9.9  62g    -0.1+-11.7  46g 
           flags home         |   +4.8+- 6.5 100g    +3.0+- 7.2  95g    -2.3+- 8.2  77g  |
           flags away         |   +7.9+- 7.2  92g+   +6.1+- 8.7  77g    +7.8+- 9.9  57g  |
           flags with_run     |   +8.8+- 8.5  63g+   +6.5+-11.6  43g    +4.3+-13.4  32g  |
           flags against_run  |   +7.2+-10.9  49g   +13.7+-13.9  30g   +10.6+-16.2  23g. |
           mkt run-side y-p   |                                                      |   +5.2+- 7.7  80g    -1.6+- 9.8  62g    -1.4+-11.4  46g 
  h2h      cut                | FLAGS hit-fair: all / clean / fresh                   | MARKET y-p home/over: all / clean / fresh
           all all            |   +8.7+- 4.6  62g+  +11.2+- 5.9  50g+  +11.5+- 6.8  47g+ |   +7.9+- 4.7  74g+  +10.0+- 5.5  63g+  +10.3+- 6.2  56g+
           phase 0-25         |   +5.5+- 9.0  33g    +7.6+-15.5  18g.   +9.1+-16.1  17g. |  +11.1+- 7.2  39g+  +16.5+-10.3  24g.  +16.9+-11.2  22g.
           phase 25-50        |   +9.6+- 8.1  37g+   +6.2+- 9.1  28g.   +5.2+-10.1  25g. |   +4.0+- 7.0  46g    +4.8+- 7.4  35g    +6.1+- 9.0  28g.
           phase 50-75        |   +5.0+- 9.0  39g    +8.8+-10.3  28g.  +14.7+-11.2  22g. |   +8.8+- 7.6  46g+  +10.4+- 8.6  33g+  +10.5+-10.3  25g.
           phase 75-90        |   +5.1+-11.3  25g.   +0.5+-14.7  18g.   +1.4+-18.4  14g. |  +14.5+- 9.2  30g+  +15.4+-12.8  20g.  +20.7+-13.4  16g.
           phase 90-100       |  +26.2+- 8.3  19g.  +30.7+-15.3  10g.  +26.6+-21.8   6g. |  +18.3+-10.4  20g.  +25.2+-15.9  11g.  +20.9+-20.4   7g.
           margin close       |   +6.6+- 7.4  41g    +8.1+-10.1  30g    +9.8+-11.6  27g. |  +12.6+- 8.2  42g+  +13.9+-10.9  31g+  +11.6+-11.5  29g.
           margin lopsided    |  +11.3+- 2.8  17g.  +13.0+- 6.9  13g.  +12.3+- 7.6  12g. |   +4.4+- 4.4  24g.   +5.9+- 6.1  18g.   +9.4+- 7.0  14g.
           run none           |   +8.7+- 5.1  54g+  +11.5+- 6.5  46g+  +11.8+- 8.0  40g+ |   +8.8+- 5.0  67g+  +10.3+- 6.1  56g+  +11.0+- 7.5  46g+
           run run            |   +4.8+- 6.6  30g    +2.5+- 8.8  21g.   +7.7+- 7.8  18g. |  +12.9+- 6.4  32g+  +10.5+- 7.6  22g.   +8.1+- 7.2  19g.
           flags home         |  +14.9+- 5.3  49g+  +18.7+- 6.7  38g+  +18.8+- 7.8  32g+ |
           flags away         |  -10.7+- 9.2  36g-   -9.4+-11.9  26g.   -3.9+-13.0  22g. |
           flags with_run     |   +5.7+- 6.9  28g.   +3.4+- 9.7  19g.   +8.3+- 8.2  17g. |
           flags against_run  |  -23.3+-28.7   3g.   -5.8+- 3.9   2g.   -3.4  n/a    1g. |
           mkt run-side y-p   |                                                      |   +7.1+- 5.2  32g+   +3.4+- 8.4  22g.   +7.6+- 7.3  19g.

######## NCAAF (306 games, 34 days)
  totals   cut                | FLAGS hit-fair: all / clean / fresh                   | MARKET y-p home/over: all / clean / fresh
           all all            |   +5.9+- 2.5 306g+   +4.9+- 2.5 306g+   +0.3+- 3.1 294g  |   -2.1+- 3.3 306g    -3.7+- 3.3 306g-   -3.0+- 3.7 294g 
           phase 0-25         |   +3.5+- 3.7 300g    +2.6+- 3.8 299g    -3.9+- 5.1 221g  |   -2.3+- 4.1 300g    -3.2+- 4.1 299g    -4.9+- 5.2 221g 
           phase 25-50        |   +4.2+- 3.2 303g+   +3.5+- 3.2 303g+   -1.4+- 4.4 259g  |   -1.4+- 3.9 303g    -2.3+- 3.9 303g    -3.6+- 4.7 259g 
           phase 50-75        |   +6.4+- 3.1 306g+   +5.4+- 3.1 306g+   +2.5+- 4.2 252g  |   -2.4+- 3.7 306g    -3.0+- 3.7 306g    -3.4+- 4.5 252g 
           phase 75-90        |   +9.8+- 2.6 303g+   +8.8+- 2.7 302g+   +6.4+- 4.2 226g+ |   -2.3+- 3.6 303g    -3.9+- 3.6 302g-   -2.5+- 4.8 226g 
           phase 90-100       |   +8.9+- 2.4 298g+   +8.8+- 2.6 297g+   +6.1+- 5.3 164g+ |   -8.6+- 3.5 298g-  -11.1+- 3.5 297g-   -8.4+- 5.7 164g-
           margin close       |   +6.7+- 3.0 302g+   +5.7+- 3.0 301g+   +0.4+- 3.8 269g  |   -0.2+- 3.6 302g    -1.4+- 3.6 301g    -1.2+- 4.1 269g 
           margin lopsided    |   +6.9+- 3.5 163g+   +5.9+- 3.6 162g+   +0.3+- 5.4 123g  |   -2.7+- 4.7 163g    -6.1+- 4.9 162g-   -4.5+- 6.3 123g 
           pace behind        |   +9.9+- 3.1 294g+   +9.6+- 3.2 294g+   +3.7+- 4.4 230g  |   -3.7+- 3.7 294g-   -3.4+- 3.7 294g    -0.1+- 4.7 230g 
           pace ahead         |   +9.7+- 3.2 293g+   +8.4+- 3.5 274g+   +4.8+- 4.9 194g  |  +10.4+- 3.7 293g+   +7.3+- 4.0 274g+   +0.2+- 5.3 194g 
           heat cold          |   +8.6+- 2.7 303g+   +8.0+- 2.8 302g+   +4.1+- 4.2 232g  |   -3.2+- 3.5 303g    -2.9+- 3.5 302g    +0.7+- 4.7 232g 
           heat hot           |   +6.1+- 2.7 305g+   +5.0+- 2.9 305g+   +1.6+- 4.0 256g  |   -0.3+- 3.4 305g    -3.9+- 3.5 305g-   -5.2+- 4.2 256g-
           flags over         |   +9.2+- 3.4 305g+   +8.1+- 3.5 305g+   +3.0+- 4.1 267g  |
           flags under        |  +14.6+- 3.3 306g+  +15.2+- 3.3 306g+  +10.7+- 4.3 255g+ |
           flags with_heat    |  +13.1+- 2.4 306g+  +11.1+- 2.5 306g+   +3.5+- 4.1 246g  |
           flags against_heat |   +2.5+- 3.0 306g    +3.5+- 3.1 306g+   +2.1+- 4.0 253g  |
  spreads  cut                | FLAGS hit-fair: all / clean / fresh                   | MARKET y-p home/over: all / clean / fresh
           all all            |   +9.8+- 2.2 306g+   +8.8+- 2.3 306g+   +4.9+- 3.0 293g+ |   +2.5+- 3.2 306g    +2.4+- 3.2 306g    +1.8+- 3.6 293g 
           phase 0-25         |   +6.3+- 3.6 299g+   +6.1+- 3.7 298g+   +2.4+- 5.0 216g  |   +2.3+- 4.0 299g    +2.2+- 4.0 298g    +2.5+- 5.2 216g 
           phase 25-50        |   +6.6+- 3.3 303g+   +6.1+- 3.4 303g+   +3.2+- 4.5 248g  |   +3.0+- 3.9 303g    +2.9+- 3.9 303g    +0.8+- 4.7 248g 
           phase 50-75        |  +10.3+- 2.9 306g+   +9.2+- 3.0 306g+   +7.4+- 4.2 249g+ |   +2.9+- 3.7 306g    +3.2+- 3.8 306g    +1.9+- 4.6 249g 
           phase 75-90        |  +13.5+- 2.4 301g+  +12.6+- 2.5 300g+   +7.0+- 4.0 220g+ |   +2.7+- 3.5 301g    +2.2+- 3.5 300g    +4.5+- 4.7 220g 
           phase 90-100       |  +15.7+- 2.0 300g+  +13.9+- 2.1 300g+   +8.1+- 4.5 184g+ |   +2.3+- 3.0 300g    +2.4+- 3.0 300g    +3.5+- 5.1 184g 
           margin close       |   +9.6+- 2.9 303g+   +9.0+- 3.1 303g+   +4.1+- 3.9 269g+ |   +4.7+- 3.8 303g+   +4.6+- 3.8 303g+   +4.2+- 4.3 269g 
           margin lopsided    |  +14.3+- 3.1 163g+  +13.1+- 3.1 162g+   +8.0+- 5.4 119g+ |   +3.9+- 4.6 163g    +2.2+- 4.6 162g    +1.4+- 6.1 119g 
           run none           |  +10.1+- 2.5 305g+   +9.3+- 2.5 305g+   +5.4+- 3.7 260g+ |   +1.9+- 3.3 305g    +1.7+- 3.3 305g    +3.7+- 4.1 260g 
           run run            |  +10.1+- 2.3 305g+   +9.1+- 2.5 305g+   +3.4+- 3.4 274g  |   +2.8+- 3.3 305g    +2.4+- 3.3 305g    +0.7+- 4.0 274g 
           flags home         |  +16.8+- 3.0 306g+  +16.2+- 3.1 306g+  +12.9+- 4.0 257g+ |
           flags away         |   +8.4+- 3.3 306g+   +8.3+- 3.3 306g+   +4.8+- 4.1 269g+ |
           flags with_run     |  +13.5+- 2.9 304g+  +11.8+- 3.1 302g+   +4.5+- 4.5 233g+ |
           flags against_run  |   +7.5+- 3.2 298g+   +8.5+- 3.2 297g+   +5.3+- 4.6 221g+ |
           mkt run-side y-p   |                                                      |   +5.7+- 2.4 305g+   +3.5+- 2.6 305g+   +0.8+- 3.6 274g 
  h2h      cut                | FLAGS hit-fair: all / clean / fresh                   | MARKET y-p home/over: all / clean / fresh
           all all            |   +2.8+- 2.6 303g+   +2.9+- 2.6 303g+   +2.5+- 3.0 278g  |   +1.2+- 3.2 304g    +1.2+- 3.2 304g    +0.5+- 3.5 279g 
           phase 0-25         |   +0.4+- 4.4 271g    +0.4+- 4.4 265g    -0.8+- 5.5 182g  |   -1.2+- 4.5 271g    -1.6+- 4.5 265g    -2.6+- 5.6 182g 
           phase 25-50        |   -0.1+- 3.7 292g    -0.1+- 3.7 290g    -0.2+- 4.6 216g  |   +1.5+- 4.0 294g    +1.4+- 4.0 292g    +0.1+- 4.7 219g 
           phase 50-75        |   +2.2+- 3.3 273g    +2.5+- 3.4 271g    +3.1+- 4.1 207g  |   +1.6+- 3.6 282g    +1.4+- 3.7 280g    -0.6+- 4.3 211g 
           phase 75-90        |   +6.3+- 2.9 240g+   +6.3+- 2.9 237g+   +4.8+- 3.8 162g+ |   +0.7+- 3.2 261g    +0.8+- 3.2 257g    +0.0+- 4.1 166g 
           phase 90-100       |   +8.3+- 2.3 219g+   +8.8+- 2.3 218g+   +5.0+- 4.3 118g+ |   +1.0+- 3.0 236g    +0.9+- 3.0 235g    +0.6+- 5.0 121g 
           margin close       |   +1.6+- 3.3 292g    +1.8+- 3.3 290g    +1.8+- 3.8 247g  |   +1.4+- 3.9 292g    +1.3+- 3.9 290g    -0.2+- 4.4 247g 
           margin lopsided    |  +12.3+- 1.3 149g+  +12.6+- 1.2 148g+  +10.5+- 2.3  80g+ |   +2.3+- 2.1 154g+   +2.5+- 2.1 153g+   +1.2+- 2.9  84g 
           run none           |   +1.5+- 2.9 285g    +1.8+- 2.9 284g    +1.6+- 3.7 221g  |   +1.1+- 3.5 289g    +1.0+- 3.5 289g    +1.2+- 4.2 223g 
           run run            |   +4.1+- 2.6 295g+   +4.1+- 2.6 293g+   +3.1+- 3.3 243g  |   +1.3+- 3.1 300g    +1.2+- 3.1 298g    +0.5+- 3.7 245g 
           flags home         |   -0.0+- 3.8 242g    +0.2+- 3.8 241g    +0.2+- 4.3 193g  |
           flags away         |   -3.7+- 3.8 253g    -3.6+- 3.8 253g    -2.1+- 4.4 201g  |
           flags with_run     |   +3.7+- 2.8 286g+   +3.6+- 2.8 285g+   +3.9+- 3.6 213g+ |
           flags against_run  |   +2.9+- 4.4 209g    +4.9+- 4.3 202g+   +5.2+- 5.6 132g  |
           mkt run-side y-p   |                                                      |   +3.4+- 1.9 300g+   +3.0+- 2.0 298g+   +2.6+- 2.7 245g 

######## NFL (67 games, 34 days)
  h2h      cut                | FLAGS hit-fair: all / clean / fresh                   | MARKET y-p home/over: all / clean / fresh
           all all            |   -1.3+- 5.3  67g    -1.2+- 5.3  67g    -5.3+- 6.3  57g  |   -7.1+- 6.8  67g-   -7.0+- 6.8  67g-   -8.7+- 7.8  57g-
           phase 0-25         |   +4.0+-12.8  36g    +3.0+-13.1  35g    -9.6+-16.7  22g. |  -14.5+-12.2  36g-  -16.0+-12.3  35g-  -14.1+-16.3  22g.
           phase 25-50        |   -0.6+- 9.0  54g    +1.0+- 9.4  51g    +3.9+-14.4  28g. |  -10.9+- 9.0  54g-   -9.7+- 9.5  51g-  -18.6+-13.2  28g.
           phase 50-75        |   -5.7+- 8.0  50g    -5.9+- 8.2  49g    -2.9+- 9.6  23g. |   -3.7+- 8.2  50g    -3.9+- 8.4  49g   -15.7+- 8.0  23g.
           phase 75-90        |   +5.9+- 7.0  47g    +5.3+- 6.9  47g    +2.7+-10.0  30g  |   -6.7+- 8.2  47g    -6.8+- 8.2  47g    -4.3+-10.7  30g 
           phase 90-100       |   +9.0+- 6.5  37g+  +10.5+- 6.4  35g+   +6.5+-11.1  22g. |   -5.7+- 9.3  37g    -4.7+- 9.5  35g    -5.8+-13.9  22g.
           margin close       |   -2.1+- 6.3  60g    -2.2+- 6.3  60g    -8.2+- 7.4  50g- |   -8.1+- 8.0  60g-   -7.9+- 7.9  60g    -9.1+- 9.0  50g-
           margin lopsided    |   +7.0+- 2.7  10g.   +7.0+- 2.7  10g.   +6.0+- 5.3   5g. |   -2.9+- 4.4  10g.   -2.9+- 4.4  10g.   -0.4+- 7.2   5g.
           run none           |   +0.3+- 6.5  63g    +1.5+- 6.6  62g    -3.2+- 9.3  42g  |   -7.6+- 7.7  63g    -7.0+- 7.7  62g   -10.2+- 9.3  42g-
           run run            |   +0.2+- 5.3  60g    +0.8+- 5.3  60g    -2.6+- 8.1  41g  |   -6.5+- 7.0  60g    -6.3+- 7.0  60g    -9.0+- 9.7  41g 
           flags home         |  -10.3+- 8.9  48g-  -10.6+- 9.0  47g-  -18.3+-10.2  34g- |
           flags away         |   +3.6+- 7.2  61g    +4.1+- 7.3  60g    +4.0+- 8.7  48g  |
           flags with_run     |   -1.3+- 8.2  48g    -1.7+- 8.4  47g   -10.7+-13.7  28g. |
           flags against_run  |   -1.3+- 8.6  42g    +0.4+- 8.6  40g    +1.4+- 9.7  27g. |
           mkt run-side y-p   |                                                      |   -0.8+- 5.2  60g    -1.3+- 5.1  60g    -6.0+- 7.6  41g 

######## NHL (43 games, 8 days)
  h2h      cut                | FLAGS hit-fair: all / clean / fresh                   | MARKET y-p home/over: all / clean / fresh
           all all            |   +2.2+- 6.5  43g    +1.8+- 6.8  42g    +1.2+- 7.4  42g  |  -10.3+- 9.0  43g-  -10.1+- 9.1  42g-  -11.2+- 9.3  42g-
           phase 0-25         |   -3.5+-11.9  41g    -1.9+-12.3  40g    +4.4+-15.6  26g. |  -19.0+-11.4  41g-  -20.2+-11.4  40g-  -21.6+-14.4  26g.
           phase 25-50        |   +1.3+-10.5  35g    +2.9+-12.0  34g    +6.1+-14.0  27g. |  -16.4+-11.3  36g-  -16.4+-11.7  35g-  -18.7+-13.4  28g.
           phase 50-75        |  +11.8+- 7.7  38g+   +9.8+- 8.1  37g+   +5.7+- 8.3  29g. |   -4.5+- 9.0  40g    -4.7+- 9.4  39g    -9.5+- 8.4  31g-
           phase 75-90        |   -5.0+- 9.3  30g    -5.5+- 9.6  30g    -4.4+-11.8  17g. |   -4.0+-10.2  32g    -3.6+-10.4  32g    -0.1+-12.4  20g.
           phase 90-100       |   -3.0+-14.0  23g.   -4.1+-15.3  21g.   +3.1+-17.3  16g. |   -9.1+-12.9  25g.   -9.5+-13.8  23g.  -11.7+-15.6  17g.
           margin close       |   +5.5+- 8.4  42g    +3.9+- 9.0  42g    +2.5+-10.3  37g  |  -13.7+-10.8  42g-  -13.5+-10.9  42g-  -16.4+-11.4  37g-
           margin lopsided    |   +1.9+- 8.8  17g.   +6.7+-14.0  15g.   +6.8+-15.3  14g. |   -4.1+-10.7  20g.   -4.5+-12.4  17g.   -4.7+-14.4  15g.
           run none           |   +9.1+- 9.5  38g    +7.0+-10.0  37g    +4.9+-11.7  32g  |  -13.1+-10.4  38g-  -13.3+-10.5  37g-  -15.3+-11.3  32g-
           run run            |   -2.0+- 6.2  42g    -1.9+- 6.4  40g    -6.7+- 8.6  36g  |   -8.0+- 8.7  43g    -7.7+- 9.1  41g    -5.9+-10.0  38g 
           flags home         |  -11.4+-10.8  37g-  -13.2+-10.4  35g-  -14.2+-10.8  33g- |
           flags away         |   +8.4+- 9.5  38g    +8.0+-10.3  36g    +7.7+-11.9  33g  |
           flags with_run     |   +1.4+- 7.2  42g    +2.0+- 8.2  40g    +0.6+-10.1  35g  |
           flags against_run  |   -8.9+-14.9  25g.   -9.7+-17.4  22g.  -20.1+-16.8  14g. |
           mkt run-side y-p   |                                                      |   +3.7+- 6.8  43g    +4.0+- 7.4  41g    +2.5+- 9.0  38g 

######## WNBA (17 games, 13 days)
  totals   cut                | FLAGS hit-fair: all / clean / fresh                   | MARKET y-p home/over: all / clean / fresh
           all all            |  +29.4+-32.4   5g.  +51.4  n/a    1g.        --        |   -9.2+-39.8   5g.  +51.4  n/a    1g.        --       
           phase 25-50        |  +51.4  n/a    1g.  +51.4  n/a    1g.        --        |  +51.4  n/a    1g.  +51.4  n/a    1g.        --       
           phase 50-75        |  +49.5  n/a    1g.        --               --        |  +49.5  n/a    1g.        --               --       
           phase 75-90        |  +24.4+-40.5   4g.        --               --        |   +1.0+-46.6   4g.        --               --       
           phase 90-100       |  +50.0+- 0.9   3g.        --               --        |  -15.9+-55.1   3g.        --               --       
           margin close       |  +16.7+-54.4   3g.  +51.4  n/a    1g.        --        |  +17.0+-54.3   3g.  +51.4  n/a    1g.        --       
           margin lopsided    |  +47.9  n/a    1g.        --               --        |  -47.9  n/a    1g.        --               --       
           pace behind        |  +47.9  n/a    1g.        --               --        |  -47.9  n/a    1g.        --               --       
           heat cold          |  +49.4+- 1.8   2g.        --               --        |   +1.1+-81.2   2g.        --               --       
           flags over         |  +50.5  n/a    1g.  +51.4  n/a    1g.        --        |
           flags under        |  +24.1+-40.4   4g.        --               --        |
           flags with_heat    |  +48.3  n/a    1g.        --               --        |
           flags against_heat |  +50.5  n/a    1g.        --               --        |
  spreads  cut                | FLAGS hit-fair: all / clean / fresh                   | MARKET y-p home/over: all / clean / fresh
           all all            |   -7.6+-24.4  11g.  -12.5+-32.0   7g.  -23.9+-42.9   4g. |  +32.0+-20.7  11g.  +22.5+-31.9   7g.  +23.9+-42.9   4g.
           phase 0-25         |  +51.2  n/a    1g.        --               --        |  +51.2  n/a    1g.        --               --       
           phase 25-50        |  -16.2+-35.6   6g.        --               --        |  +32.9+-28.7   6g.        --               --       
           phase 50-75        |  -22.3+-31.1   7g.  -32.2+-34.1   5g.  -50.3  n/a    1g. |  +36.9+-24.0   7g.  +32.2+-34.1   5g.  +50.3  n/a    1g.
           phase 75-90        |  -49.9+- 0.5   5g.  -49.8+- 0.4   2g.  -49.8+- 0.3   2g. |  +49.9+- 0.5   5g.  +49.8+- 0.4   2g.  +49.8+- 0.3   2g.
           phase 90-100       |   +1.1+-37.4   6g.  +19.8+-57.1   3g.  +55.5  n/a    1g. |  +32.3+-28.9   6g.  +15.9+-58.7   3g.  -55.5  n/a    1g.
           margin close       |  -14.7+-25.4  10g.   +2.5+-40.2   5g.   +2.3+-85.5   2g. |  +30.0+-22.7  10g.  +11.4+-42.9   5g.   -2.3+-85.5   2g.
           margin lopsided    |  -50.0+- 0.4   2g.  -50.3  n/a    1g.  -50.3  n/a    1g. |  +50.0+- 0.4   2g.  +50.3  n/a    1g.  +50.3  n/a    1g.
           run none           |   -5.8+-24.8  11g.   -0.5+-39.0   6g.  -15.1+-57.1   3g. |  +32.0+-20.8  11g.  +18.0+-36.7   6g.  +15.1+-57.1   3g.
           run run            |  -21.3+-31.0   7g.  -16.6+-54.8   3g.  -50.3  n/a    1g. |  +21.3+-31.0   7g.  +16.6+-54.8   3g.  +50.3  n/a    1g.
           flags home         |  +50.5+- 1.8   4g.  +52.3  n/a    1g.        --        |
           flags away         |  -27.7+-24.9   9g.  -22.2+-31.8   7g.  -23.9+-42.9   4g. |
           flags with_run     |  -16.4+-35.4   6g.   -0.1+-82.6   2g.  -50.3  n/a    1g. |
           flags against_run  |  -50.3+- 0.3   3g.  -49.5  n/a    1g.        --        |
           mkt run-side y-p   |                                                      |   +9.8+-28.5   7g.  +16.4+-54.9   3g.  -50.3  n/a    1g.
  h2h      cut                | FLAGS hit-fair: all / clean / fresh                   | MARKET y-p home/over: all / clean / fresh
           all all            |   -1.9+-13.7  15g.   -9.9+-12.5  13g.  -17.3+-13.4  10g. |  +14.3+-15.1  15g.  +15.0+-15.5  13g.   +9.6+-21.1  10g.
           phase 0-25         |  -29.5+-15.9   2g.  -17.9  n/a    1g.  -17.9  n/a    1g. |  +29.5+-15.9   2g.  +17.9  n/a    1g.  +17.9  n/a    1g.
           phase 25-50        |   -8.9+-22.7   8g.  -17.1+-24.4   6g.   +2.1+-37.6   3g. |  +11.2+-22.3   8g.   +3.3+-27.4   6g.  -29.8+-14.9   3g.
           phase 50-75        |   -3.6+-21.1   9g.  -16.1+-23.6   6g.  -26.5+-34.4   2g. |  +14.6+-21.9   9g.  +25.9+-18.3   6g.  +26.5+-34.4   2g.
           phase 75-90        |  -20.9+-31.5   6g.  -15.6+-29.9   6g.  -19.8+-36.2   5g. |  +16.5+-39.7   6g.  +16.2+-38.3   6g.  +10.4+-45.3   5g.
           phase 90-100       |   -3.4+-21.4   9g.   +6.2+-24.7   7g.   +0.6+-62.2   3g. |  +25.2+-16.6   9g.  +23.6+-20.7   7g.  +47.8+-27.8   3g.
           margin close       |   -3.7+-18.0  11g.  -10.6+-16.4  10g.  -19.3+-18.8   7g. |  +23.8+-20.0  11g.  +20.9+-21.7  10g.  +15.1+-31.8   7g.
           margin lopsided    |  -10.3+- 7.9   3g.   -9.1+- 9.1   3g.  -14.9+-11.3   2g. |   -4.1+-13.6   3g.   -3.8+-13.2   3g.   -6.9+-24.5   2g.
           run none           |   -1.7+-15.5  14g.   -8.0+-14.0  12g.  -12.9+-19.4   9g. |  +15.1+-17.5  14g.  +16.3+-18.2  12g.  +10.1+-25.3   9g.
           run run            |  -11.1+-22.8   6g.  -20.0+-17.8   5g.  -23.8+-19.8   5g. |   +4.7+-24.0   6g.  +12.4+-22.0   5g.  +15.1+-24.9   5g.
           flags home         |   +6.4+-25.6   9g.   +0.8+-26.6   8g.  -18.6+-37.9   5g. |
           flags away         |  -14.9+-17.4  11g.  -19.5+-17.3  10g.  -16.8+-22.6   8g. |
           flags with_run     |   +1.2+-46.9   3g.  +17.0  n/a    1g.  +17.0  n/a    1g. |
           flags against_run  |  -31.2+-12.8   4g.  -29.3+-11.8   4g.  -34.0+-13.5   4g. |
           mkt run-side y-p   |                                                      |  +26.1+- 4.1   6g.  +26.8+-10.0   5g.  +30.6+-11.9   5g.
```

## Forward test, PRE-REGISTERED (todo #830, lane `live-bet-timing-forward`; user "Register them", 2026-11-17 ~5:10 PM CST, before any 11-18 game)

- **Window:** ledger slates **2026-11-18 .. 2026-12-01** (14 nights) for NCAAB, NCAAF, WNCAAB, NBA, NFL and NHL. Nothing from
  the discovery window (through 11-16) or the 11-17 slate (in play when this was written) is in it.
- **Run:** `scripts/live_bet_timing_study.py` (blob `25543aebf51e`), once per sport on the fleet:
  `--from 2026-11-18 --to 2026-12-01 --cache /mnt/c/tmp/livetiming_fwd/tl --json /mnt/c/tmp/livetiming_fwd/<sport>.json`.
  Then `scripts/score_live_bet_timing_forward.py --dir /mnt/c/tmp/livetiming_fwd` (this commit) prints every cell and verdict.
  Scheduled task `live-bet-timing-forward-830`, **Wed 2026-12-02 10:00 AM CST**.
- **Every cell is FRESH-quote** (`main_fresh`: the book had seen the current score and the quote was <= 60 s old),
  game-clustered, with a 90% CI. **< 30 games = INSUFFICIENT.** The scorer fixes the cells and rules:

| cand | claim | cell(s) | rule |
|---|---|---|---|
| C1 | college flags earn late | NCAAB totals 90-100%; NCAAB spreads 75-90%; NCAAF spreads 75-90% and 90-100%; NCAAF totals 75-90% | CI > 0, and the mean above the same market's 0-25% cell |
| C2 | totals: unders yes, overs no | under flags NCAAB / NCAAF / WNCAAB; over flags NCAAB / NCAAF | unders CI > 0; overs CI contains 0 |
| C2x | NCAAB games ahead of the line's pace: the over is under-priced | market y - p, totals, pace "ahead" | CI > 0 (did NOT clear on fresh in discovery; registered as the weakest) |
| C3 | ride the run (NCAAB) | totals flags with the heat; spreads flags with the run | CI > 0, and the mean above the matching "against" cell |
| C4 | pro live ML over-prices home | NHL and NFL market y - p, home, h2h | CI < 0 |
| C4r | WNCAAB live ML under-prices home | WNCAAB market y - p, home, h2h | CI > 0 |
| C5 | NCAAB model ML flags lose early | h2h flags, 0-25% of regulation | CI < 0 |
| C6 | NBA has no fresh-quote edge | totals flags and spreads flags, all | CI contains 0 |

- **Verdict per candidate:**
  - HOLDS: every cell meets its rule.
  - FAILS: a cell's CI sits on the wrong side of 0.
  - INSUFFICIENT: any cell has < 30 games. NFL is likely, at ~2 weeks of games; it is then re-run on a longer window under the same rules.
  - NOT CONFIRMED: otherwise.
- **Loads inside the window:** list every fleet load 11-18..12-01 that changes live pricing or flags for a registered
  sport x market. Score the cells on each side of the load as well as pooled.
  - Known risk: the #816 7-day grade (11-24) may flip `FIT_LEVEL`, which changes which NCAAB total flags exist.
  - A candidate HOLDS only if no side with >= 30 games reverses its sign.
- **Nothing is changed by this test.** A HOLDS makes a candidate eligible for a user decision, e.g. a rail cue for late
  college flags or a per-row refusal keyed on the row's own state. It is never a market-wide switch: the user's rule is
  that every line is its own decision.
- **Scorer smoke run** on the discovery JSONs (in-sample, so expected to pass): C1-C6 and C4r HOLDS, C2x NOT CONFIRMED. It
  proves only that the scorer reads the right cells.

## Interim read, 11-18 only (NOT the registered verdict)

INTERIM, one night. Run at 1:17-1:18 AM CST 11-19 by scheduled task `live-bet-timing-interim-1118`, on the user's request
of 11-18 (~10 AM CST): "run the #830 forward test early on today's games". **It does NOT replace or change the 12-02
verdict** (task `live-bet-timing-forward-830`, the 14 nights 11-18..12-01). It changes no cell, rule or the 30-game minimum.

- **Run:** the registered blobs, `live_bet_timing_study.py` `25543aebf51e` and `score_live_bet_timing_forward.py`
  `d58692e395c2`, from worktree `live-bet-timing-forward` at `1ff9f2554`. On the fleet (`~/syndicate-prod/data`, read
  only), nice 19, `--from 2026-11-18 --to 2026-11-18`. Outputs and scorer print: `C:\tmp\livetiming_interim_1118\`
  (`score.txt`; not in git).
- **Games graded:** NCAAB 52, WNCAAB 16, NBA 12, NHL 2, NCAAF 1, NFL 0 (no NFL slate on a Wednesday).
  - `no_final`: **0** in every sport. The run started after the last game ended.
  - Unmatched to ESPN: NCAAB 1,629 of 12,010 records, NCAAF 303 of 621, NHL 18 of 67. The registered run counts these the same way.
  - Fresh (<= 60 s) records: NCAAB 5,296, NCAAF 215, WNCAAB 1,182, NBA 12,796, NHL 22.

Every cell, hit - fair or y - p in pp on FRESH quotes, 90% game-clustered CI. Discovery = the fresh number in this file's
"What holds on FRESH quotes" (through 11-16):

| cand | cell | interim mean [90% CI] | games | cell status | discovery |
|---|---|---|---|---|---|
| C1 | NCAAB totals flags, 90-100% | +13.7 [+4.7, +22.6] | 50 | MEETS (0-25% cell +4.6) | +13.8 +- 3.7 (251 g) |
| C1 | NCAAB spreads flags, 75-90% | +5.0 [-1.9, +12.0] | 51 | OPEN | +4.5 |
| C1 | NCAAF spreads flags, 75-90% | no cell | 0 | INSUFFICIENT | +7.0 |
| C1 | NCAAF spreads flags, 90-100% | no cell | 0 | INSUFFICIENT | +8.1 |
| C1 | NCAAF totals flags, 75-90% | no cell | 0 | INSUFFICIENT | +6.1 to +6.4 (75-100) |
| C2 | NCAAB under flags | +8.6 [+0.6, +16.5] | 52 | MEETS | +8.3 (429 g) |
| C2 | NCAAF under flags | no cell | 0 | INSUFFICIENT | +10.7 (255 g) |
| C2 | WNCAAB under flags | +22.6 [+9.2, +36.1] | 16 | INSUFFICIENT | +7.3 (104 g) |
| C2 | NCAAB over flags (no edge) | no cell | 0 | INSUFFICIENT | +0.9 |
| C2 | NCAAF over flags (no edge) | no cell | 0 | INSUFFICIENT | +3.0 |
| C2x | NCAAB totals ahead of pace, market y - p | +8.5 [-20.5, +37.5] | 8 | INSUFFICIENT | +5.2 (93 g, CI incl. 0) |
| C3 | NCAAB totals flags WITH the heat | +18.2 [+7.3, +29.0] | 31 | MEETS (against +2.4) | +11.3 (289 g) vs -0.5 |
| C3 | NCAAB spreads flags WITH the run | -5.5 [-14.8, +3.9] | 41 | OPEN | +7.2 (172 g) vs -4.3 |
| C4 | NHL live ML, home y - p | +0.6 [-31.3, +32.5] | 2 | INSUFFICIENT | -11.2 (42 g) |
| C4 | NFL live ML, home y - p | no cell | 0 | INSUFFICIENT | -8.7 (57 g) |
| C4r | WNCAAB live ML, home y - p | +16.5 [+6.9, +26.0] | 10 | INSUFFICIENT | +10.3 (56 g) |
| C5 | NCAAB model ML flags, 0-25% | +8.6 [+0.3, +16.9] | 30 | FAILS | -11.3 (102 g) |
| C6 | NBA totals flags (no edge) | -11.9 [-23.5, -0.2] | 12 | INSUFFICIENT | CI contains 0 |
| C6 | NBA spreads flags (no edge) | +9.3 [-7.2, +25.9] | 12 | INSUFFICIENT | CI contains 0 |

**INTERIM verdicts, as the scorer prints them** (one night; none of them is the registered verdict):

- **C1 INSUFFICIENT.** NCAAF had 1 graded game. The headline cell repeats: NCAAB late totals +13.7 on 50 games vs +13.8 in discovery.
- **C2 INSUFFICIENT.** NCAAB unders +8.6 MEETS (discovery +8.3). NCAAF has no cells. WNCAAB has 16 games. There were no NCAAB or NCAAF over-flag cells.
- **C2x INSUFFICIENT** (8 games).
- **C3 NOT CONFIRMED.** Totals with the heat +18.2 MEETS. Spreads with the run read -5.5, which is OPEN: its CI holds 0. Discovery was +7.2.
- **C4 INSUFFICIENT.** NHL had 2 games and NFL 0.
- **C4r INSUFFICIENT** (10 games; +16.5, the discovery sign).
- **C5 FAILS** on exactly 30 games: +8.6 [+0.3, +16.9], against discovery's -11.3. Early NCAAB model ML flags BEAT their price on 11-18.
  - That is one night at the 30-game floor, with the CI's low end at +0.3. Treat it as the first thing to watch in the full run, not a result.
- **C6 INSUFFICIENT** (12 NBA games). NBA totals flags read -11.9 with the CI just below 0. Spreads read +9.3 with the CI around 0.

**Fleet loads on 11-18, before or during the slate** (deploys.md; listed only, NOT split. One night cannot carry a split.)

| UTC 11-18 | CST | load | BC | relevance |
|---|---|---|---|---|
| 08:02:54Z | 2:02 AM | refresh-worker TERM: I-17's calibrated college total (`923869cf3`) and the NFL re-sim event-id seeds (`ee47c930a`) | BC-041 / BC-045 | I-17 is display only. The NFL seeds have no NFL games in this read. |
| 08:30:50Z | 2:30 AM | the board split: the board build runs in its own process (`09eddabf2`, #832) | yes | cadence of the board and the live plan |
| 13:47:14Z | 7:47 AM | I-22, the live odds lane fix: one sport's hung child no longer takes the lane (`2ae0c646a`, #838) | | changes how fresh live quotes are, and so the FRESH population |
| 14:42:44Z | 8:42 AM | the #816 gate fallback: a failed college totals calibration serves the market (`36a9f5501`) | BC-048 | pregame only; NCAAB live is unchanged |
| 15:56:43Z | 9:56 AM | the pregame NHL generation split (`cdab875d5`, #838) | BC-049 | pregame NHL |

Later loads on the 11-18 slate, at 04:46Z and 04:58Z on 11-19, came near or after the last games. They are not listed; the 12-02 run's load list will cover them.
