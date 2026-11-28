# Portfolio monitor findings, 2026-11-28 (lane `portfolio-monitor`)

Public repo: counts and percentages only. No dollars, balances, order ids or row-level live trades.

## Lane `clv-fair-close` -- first coverage reading after the load (read 9:50 AM CST)

One GET of `/api/portfolio/live` at 15:50:04Z (9:50 AM CST), via `C:\tmp\pfmon\clvload\marks_reading.py` (local
scratch, never committed). It counts closing marks whose `checked_at` is at or after the load, 2026-11-27T23:02:03Z
(5:02 PM CST 11-27). The newest mark was checked at 08:42:19Z (2:42 AM CST).

- **Every mark stamped since the load carries the fair-close key: 21 of 21** (Kalshi 17 of 17, Polymarket 4 of 4).
  So the board child stamps it on every path, not just the same-book one.
- **Resolved since the load: 9** (Kalshi 6, Polymarket 3).
  - Kalshi: 2 same-book. **Both carry a fair CLV value (2 of 2).**
  - Polymarket: 0 same-book. All 3 resolved closes are `different_book_close`, so there is no fair close to take.
  - No same-book mark is missing its fair value, so there are no `close_fair_reason` counts to report.
- **The Polymarket bar (>= 60%) cannot be read yet: its denominator is 0.** The Kalshi 2 of 2 is a denominator of 2.
  This is a check that the path runs, not a coverage share.

**Rate, so the owed readings can be dated.** Resolved same-book marks per Central day, 11-24..11-27: Kalshi 2, 4, 5,
5; Polymarket 2, 1, 0, 2. That is about 4 a day for Kalshi and about 1.25 a day for Polymarket. Marks stamped per day
(all reasons, both venues): 7, 16, 13, 24. The 21 since the load are in line with that, so the change did not slow
stamping.

- A Polymarket share on at least 10 same-book marks: about 8 days out, around 12-06.
- The falsification test on at least 100 covered forward marks: about 19 days at about 5.25 a day, around 12-17.
  The 11-27 replay already measured the gap at +0.82 pp [+0.67, +0.98] on the 30 d book, outside [-0.3, +0.3]. So
  the forward test is a confirmation, not the first read.

**Owed:** the Polymarket share at n >= 10 (around 12-06); the forward falsification test at n >= 100 (around 12-17);
the readout half (fair CLV in `scripts/live_book_edge_readout.py`, under lane `portfolio-monitor`).
