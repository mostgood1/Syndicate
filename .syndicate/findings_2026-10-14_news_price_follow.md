# FINDINGS -- How fast do books move after injury news? First read, 2026-10-13/14 (lane `news-price-follow`, session 9e18a0e7)

User 2026-10-14: "do both, start with #1" (#2 = the price-follow study the news collector was built for).
Script `scripts/news_price_follow.py` (tests `tests/test_news_price_follow.py`, 4). Read on the fleet 2026-10-14 22:23Z,
`--start 2026-10-13 --end 2026-10-14 --sports nfl,nhl`, worktree code against `~/syndicate-prod/data`.

## What it rests on

- **Events:** material status changes from the collector's ESPN injury logs (playable <-> Out / IR / Suspension; the
  collector's first run per sport is a baseline and skipped) plus NHL scratches (first sighting per game). t0 = our
  capture (<= 10 min after the source).
- **Quotes:** the fleet's append-on-change quote logs, the player's next game within 8 days. Two sets, kept apart:
  the player's OWN props, and his team's GAME LINES (h2h / spreads / totals).
- **Window: ~27 hours of news** (the collector started 2026-10-13 ~19:31Z). NFL 163 events (84 to_out / 79 to_in,
  all matched to a next game); NHL 136 (108 / 28; 130 matched). NBA 2 (preseason, no props), WNBA 46 (0 matched:
  eliminated teams have no next game).

## Results

| set | events | moved <= 15 min | placebo (same keys, 24 h earlier) | lift | stale quotes | stale EV mean | EV > 0 |
|---|---|---|---|---|---|---|---|
| NFL own props, to_out | 6 | 5.6% | 0% | -- | 0 | -- | -- |
| NFL own props, to_in | 5 | 0% | 0% | -- | 0 | -- | -- |
| NFL game lines, to_out | 84 | 15.6% | 7.4% | 2.11 | 5,010 | -4.44% | 0.2% |
| NFL game lines, to_in | 79 | 15.9% | 6.9% | 2.30 | 4,880 | -4.44% | 0.3% |
| NHL own props, to_out (mostly scratches) | 14 | 7.7% | 0% | -- | 0 | -- | -- |
| NHL game lines, to_out | 103 | 85.2% | 57.9% | 1.47 | 166 | -5.84% | 1.8% |
| NHL game lines, to_in | 12 | 79.0% | 89.5% | 0.88 | 20 | -4.09% | 15% |

Timing resolution = OUR capture cadence: median gap between capture times within +-60 min of t0 is 8.4 min (NFL) and
0.5 min (NHL, near puck drop). A per-book latency finer than that is not measurable.

## What it says -- and does not

- **No stale-price edge in this window.** Prices left up by slower books average about -4.4% EV against the movers'
  Shin fair, with 0.2-0.3% positive (NFL) -- that is one book's hold, i.e. the stale price is an ordinary price. NOT
  SUPPORTED on 27 hours; not yet a test (n of material events small, see below).
- **The NFL game-line "lift" is not news.** It is the same for players ruled OUT and players back IN (2.11 vs 2.30):
  the Wednesday injury report and the books' own line updates land in the same hours. A news effect would be
  asymmetric and concentrated on high-usage players.
- **Books mostly PULL a ruled-out player's props rather than reprice them** (NHL own props: 7.7% moved within 15 min
  of a scratch). A pull is invisible in an append-on-change log, so the own-prop set under-counts the reaction.
- **Most events are low-impact** (backups to IR, Wednesday report turnover). There is no usage weighting yet.

## For the re-read (scheduled)

Weeks of events, and three changes before a claim is made: (1) weight events by the player's usage (snaps / TOI /
minutes) or restrict to starters; (2) detect pulls -- a book's key absent from captures that include its other keys
for the same game; (3) a placebo at the same weekday and hour. Until then this is a measurement harness with a
first, thin read -- not evidence for or against a news edge.

## Re-read 2026-11-04 -- three weeks (2026-10-13..11-03), NFL / NHL / NBA / WNBA (scheduled task `news-price-follow-reread-1104`)

Read on the fleet 2026-11-04 ~16:10-16:20Z (10:10-10:20 CST), `~/Syndicate` code (= origin/main for this script) against
`~/syndicate-prod/data`, nice 19, no code changed, no OddsAPI calls. **How it was run, and why it differs from the
scheduled command:** the one-process command as scheduled was OOM-killed (exit 137, ~9 GB anon RSS -- the loader reads
EVERY NFL weekly quote file regardless of window, 955 MB on disk). Re-run per sport, under `ulimit -v 4.5 GB`, through a
scratchpad wrapper that imports the script unchanged and swaps only `load_quotes`: 7-day event chunks, weekly files
limited to the weeks a chunk can reach, and only the rows the study reads (game rows in h2h/spreads/totals; prop rows of
a player with an event in the chunk). The event set is the same as a single run (the baseline skip uses min
`captured_at` over all news files either way). Bootstrap = 2,000 resamples of GAMES (stale-EV mean; and the difference
of news-minus-placebo 60-min share between to_out and to_in), seed 1104. Wrapper + analysis scripts were scratchpad-only.

### The event set is mostly feed flapping -- the headline result of this read

| sport | ESPN events | players | events reversed within 60 min | de-flapped events kept (+ NHL scratches) |
|---|---|---|---|---|
| NFL | 6,389 (3,194 out / 3,195 in) | 529 | 3,978 | 1,435 of 6,389 |
| NBA | 932 (491 / 441) | 149 | 254 | 444 of 932 |
| NHL | 649 ESPN + 816 scratches | 166 | 134 | 1,205 of 1,465 |
| WNBA | 967 (484 / 483) | **5** | 842 | -- (13 matched to a game; season over) |

The dominant transitions are `Out -> (none)` then `(none) -> Out` (NFL 1,611 / 1,610; IR 871 / 869): a player drops
off the ESPN list for one capture and comes back. That is a collector/feed artifact, not news, and it is why to_out and
to_in counts are near-equal -- and why the FIRST read's symmetric lift could not separate news from anything.
"De-flapped" below = drop every ESPN event that is reversed by the same player's next event within 60 min.

### Results (all events | de-flapped). Shares are book-observations; placebo = same keys 24 h earlier

| sport / set / kind | events (games) | moved <= 15 min | placebo 15 | moved <= 60 min | placebo 60 | stale quotes (events / games / books) | stale EV mean [game-boot 95% CI] | EV > 0 |
|---|---|---|---|---|---|---|---|---|
| NFL game lines, to_out | 2,725 (57) | 9,199/53,916 17.1% | 3,773/47,771 7.9% | 21,650/53,916 40.2% | 11,295/47,771 23.6% | 286,405 (2,620/57/32) | -4.84% [-5.00, -4.69] | 2.7% |
| ... de-flapped | 697 (56) | 3,770/13,618 27.7% | 1,224/12,514 9.8% | 8,172/13,618 60.0% | 3,320/12,514 26.5% | 87,789 (674/55/32) | -4.90% [-5.11, -4.71] | 4.0% |
| NFL game lines, to_in | 2,674 (57) | 7,027/54,878 12.8% | 3,075/46,536 6.6% | 17,836/54,878 32.5% | 9,827/46,536 21.1% | 256,626 (2,576/57/32) | -4.88% [-5.05, -4.72] | 2.1% |
| ... de-flapped | 646 (56) | 1,607/14,579 11.0% | 545/11,279 4.8% | 4,351/14,579 29.8% | 1,859/11,279 16.5% | 58,010 (629/56/32) | -5.12% [-5.29, -4.95] | 2.0% |
| NFL own props, to_out | 387 (50) | 58/2,289 2.5% | 62/2,005 3.1% | 111/2,289 4.8% | 273/2,005 13.6% | 257 (15/9/8) | -6.25% [-6.53, -6.03] | 5.4% |
| NFL own props, to_in | 354 (54) | 97/1,650 5.9% | 52/1,197 4.3% | 173/1,650 10.5% | 167/1,197 14.0% | 297 (19/11/9) | -6.29% [-6.43, -6.14] | 2.7% |
| NHL game lines, to_out | 1,074 (157) | 8,442/11,718 72.0% | 6,915/9,016 76.7% | 10,774/11,718 91.9% | 8,906/9,016 98.8% | 1,656 (271/83/13) | -7.90% [-10.29, -5.80] | 6.3% |
| NHL game lines, to_in | 183 (90) | 986/1,780 55.4% | 364/666 54.7% | 1,729/1,780 97.1% | 661/666 99.2% | 153 (25/21/10) | -4.67% [-5.97, -3.53] | 7.8% |
| NHL own props, to_out | 289 (117) | 22/929 2.4% | 7/178 3.9% | 44/929 4.7% | 14/178 7.9% | 404 (22/14/7) | -6.46% [-7.00, -5.95] | 9.2% |
| NHL own props, to_in | 38 (27) | 19/144 13.2% | 0/5 | 38/144 26.4% | 2/5 | 158 (9/6/7) | -7.13% [-7.95, -6.60] | 10.1% |
| NBA game lines, to_out | 343 (96) | 660/3,298 20.0% | 24/842 2.9% | 1,544/3,298 46.8% | 99/842 11.8% | 229 (26/12/7) | -3.87% [-4.51, -2.42] | 13.5% |
| NBA game lines, to_in | 196 (76) | 379/1,821 20.8% | 18/374 4.8% | 870/1,821 47.8% | 44/374 11.8% | 138 (20/12/5) | -3.65% [-4.50, -2.34] | 12.3% |
| NBA own props, to_out | 66 (45) | 8/637 1.3% | 0/12 | 21/637 3.3% | 0/12 | 668 (12/10/12) | -6.38% [-6.65, -6.08] | 6.1% |
| NBA own props, to_in | 23 (15) | 16/201 8.0% | 0/0 | 39/201 19.4% | 0/0 | 202 (11/8/12) | -6.57% [-7.24, -5.69] | 5.9% |
| WNBA (all sets) | 3-6 per set, 1-3 games | -- | -- | -- | -- | 16-34 per set | -4.8% .. -6.2% | 3-13% |

NHL / NBA de-flapped rows change no conclusion (NHL game-line stale EV -8.10% [-10.75, -5.88]; NBA -3.92% / -3.45%).

**Capture cadence (the latency floor), median_poll_gap_min:** NFL 3.9, NHL 0.6, NBA **32.9**, WNBA 4.5. Per-book median
latency, NFL game lines to_out: fastest matchbook 14.9, coolbet 20.3, nordicbet 26.2, betsson 26.3, betfair_ex_eu 34.5,
betmgm 49.2 min; US retail 75-162 min (fanatics 75.0, pinnacle 84.3, draftkings 93.4, fanduel 129.1, williamhill_us 162.0).
NHL game lines: 5-7 min for every US book (kalshi 15.6, polymarket 16.7) -- near puck drop everything moves. NBA: ~58-60
min for nearly all books = the 32.9-min cadence, i.e. **NBA latency is not measurable** below about an hour.

### Answers

**(a) Stale-price edge: ABSENT everywhere.** In 16 of 16 sport x set x kind cells (and every de-flapped cell) the
game-clustered 95% CI of stale-quote EV lies wholly BELOW zero (upper bounds -2.3% .. -6.2%; the 4 WNBA cells rest on
1-3 games and prove little on their own); the positive share is
2-13%. A price a slow book leaves up after the first mover is an ordinary price carrying its hold. The lane's
falsification test ("CI touching or below 0") is MET on three weeks -- the hypothesis is FALSIFIED for this harness.

**(b) Asymmetry (60-min news-minus-placebo share, to_out minus to_in, game-boot 95% CI):**
- NFL game lines, all events: +5.1pp [-2.6, +15.4] -- symmetric. **De-flapped: to_out +33.5pp vs to_in +13.4pp,
  difference +20.1pp [+12.2, +28.5] -- ASYMMETRIC**, the first sign that genuine OUT designations move NFL game lines
  more than returns. NOT yet a news effect: the placebo is t0 - 24 h, and OUT designations cluster on the Friday report
  and game-day inactives, nearer kickoff than returns -- time-to-kickoff can produce the same asymmetry.
- NBA game lines: -1.0pp [-17.9, +16.0] (de-flapped -5.4 [-24.4, +13.2]) -- symmetric (lift ~4 both ways = timing,
  and at a 33-min cadence).
- NHL game lines: -4.7pp [-8.5, -0.7] (de-flapped -3.4 [-9.0, +3.3]) -- near puck drop the placebo already moves 99%;
  no room for a lift.
- Own props: every cell's CI spans zero (NFL -5.3 [-9.8, -0.6] negative, i.e. FEWER moves than placebo -- the pull
  signature); the news-window own-prop move rate is BELOW placebo in most cells.

**(c) Which improvement would change the answer** (recommendation only -- not built; the user's decision):
1. **De-flap the event source FIRST (a 4th item, not in the original three).** It is the largest single effect on the
   result: 78% of NFL events are flaps and removing them is what made the NFL asymmetry appear. Belongs in the study
   (persistence filter) and arguably in the collector (`collect_news_snapshots.py` should not emit `cleared` on a
   one-capture dropout).
2. **Same-weekday / same-time-to-kickoff placebo -- would change (b).** It is the one improvement that can tell whether
   the de-flapped NFL asymmetry is news or report timing. Recommended next.
3. **Pull detection -- would change the own-prop latency answer, not (a).** Own-prop moves run below placebo, i.e. books
   pull rather than reprice; a pulled line has no stale price to bet, so it cannot create a stale edge.
4. **Usage weighting -- unlikely to change (a)** (no cell is near zero; a high-usage subset would need +5pp of EV), but
   could sharpen (b) once 1-2 are in.
Not worth more runs as-is: NBA latency needs a faster capture cadence (32.9 min) before any NBA timing claim.
