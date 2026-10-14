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
