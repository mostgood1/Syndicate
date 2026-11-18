# The learner against Kalshi's own price (dev study, 2026-11-17)

Lane `engine-learner`, umbrella #736. The user asked for it ("Yes, run it") after M3's dev rehearsal: there, the NCAAF
live gain the learner showed against the books' price lost 3.3c per contract at Kalshi. The hypothesis and falsifier
were written to the lane before the run (main `526f9f4b3`, 7:54 PM CST). **Dev slates only**: nothing of M2's
11-15..11-22 or M3's windows was read. Kit `C:\tmp\elp\kprior` (`make_opinions.py`, `run.sh`, outputs).

## Method

- **Opinions:** the M2 kit's frozen ones (experts `981ef14f6`). Live, full-game h2h, spreads and totals; NBA, NHL,
  NFL and NCAAF; slates 11-09, 11-10, 11-11, 11-13 and 11-14 (the in-play recorder has no 11-12).
- **Kalshi's price:** the recorder's 10 s Kalshi quotes, placed on each line by M3's index (the order path's
  resolver, the live join's frame), at the decision instant t_d: the tick, or the evidence state's `as_of` if later.
  - P1 is the last quote at or before t_d, at most 60 s old.
  - P2 is the first quote in [t_d + 10, t_d + 70] s: M3's entry quote.
- **The same line-instants in every arm:** only those with both P1 and P2. NBA 42,329; NCAAF 10,327; NHL 1,517; NFL 0
  (no NFL Kalshi market could be placed).
- **Arms:**
  - `book`: the original opinions, the control.
  - `kbefore` / `kentry`: prior = P1 / P2. Each expert's delta becomes logit(p_expert) - logit(p_Kalshi), and the
    books' fair is added as one more expert, `books`.
- **Learner:** the frozen one (tau 0.5), test from 11-13 (44 train games, 87 test games, each game held out whole),
  outcome truth.

## Result

**The hypothesis holds.** Against either Kalshi prior, 0 of 82 cells are applied and 0 of 20,657 held-out examples
move. Against the books' prior on the same lines, 16 NBA cells are applied, mostly where the books' prior was 60 to
900 s old. None of them reaches a held-out d_ll CI below 0 on these 14 NBA test games.

| test, prior log loss | books | Kalshi P1 | Kalshi P2 |
|---|---|---|---|
| NBA h2h | 0.4470 | 0.4160 | 0.4137 |
| NBA spreads | 0.4605 | 0.4433 | 0.4378 |
| NBA totals | 0.4370 | 0.4133 | 0.4106 |
| NCAAF h2h | 0.4616 | 0.4481 | 0.4463 |
| NCAAF spreads | 0.6809 | 0.6035 | 0.5953 |
| NCAAF totals | 0.6854 | 0.6265 | 0.6146 |
| NHL h2h | 0.5481 | 0.5373 | 0.5324 |
| NHL spreads | 0.5472 | 0.4683 | 0.4696 |

Fitted NBA weights against P2 (train cells with n >= 300; n-weighted mean, typical SE):

| expert | NBA spreads | NBA totals |
|---|---|---|
| `books` | -0.68 (se ~0.44) | -0.27 (se ~0.49) |
| `live_resim` | +0.17 (se ~0.48) | -0.32 (se ~0.40) |

Against the books' prior, `live_resim` was +0.46 / +0.25.

## Reading

- **Kalshi's in-play mid is a much better forecast than the books' fair** in every sport and family here. Log loss is
  lower by 0.02 to 0.09 nats, and by most in NCAAF spreads and totals.
- **Moving toward the books from Kalshi makes the forecast worse.** The `books` weights are negative.
- **The live re-sim shows no weight against Kalshi.** NBA's train set is 44 games, so this rules out a strong signal
  (w near 1), not a modest one (w up to about 0.5-0.8).
- **NCAAF trained on only 214 line-instants** (weeknights 11-10 and 11-11), so its null says little.
- **Consequence:** a live learner built on the books' prior (M2 as registered) can pass M2 and still have nothing to
  sell at Kalshi. This is the dev-data reason M3's rehearsal lost. Live edge, if any, has to come from information
  Kalshi lacks, judged against Kalshi's own price.

## What would change it

The same study on more data. After M2's 11-24 read, slates 11-15..11-22 may be read, adding two NCAAF Saturdays and
about 8 NBA nights. Whether slice 5 (Kalshi as the prior) is worth rebuilding turns on that: a weight surviving against
P2 there. Nothing here changes M2's or M3's registered rules.
