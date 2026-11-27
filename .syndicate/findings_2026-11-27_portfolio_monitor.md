# Portfolio monitor findings, 2026-11-27 (lane `portfolio-monitor`)

Public repo: counts and percentages only. No dollars, balances, order ids or row-level live trades.

## The 11-24 close-beat study, run 2026-11-27 -- RULE RESTATED BEFORE COMPUTING (written 12:32 PM CST)

User 11-27 ~12:30 PM CST: "Yes, run it" (answering "Should I run the 11-24 closing-line study now?").

The study is the one pre-registered by the daily learning review in `findings_2026-11-24_portfolio_monitor.md`,
"One optimization lead". Its hypothesis, buckets and decision rule are copied here unchanged, and they are frozen:

- *Hypothesis:* the 7 d close-beat decline (beat-close 61.1% to 53.9%) comes from bets submitted long before
  commence, where our fair is stale against a moving market, not from bets near the start.
- *Data:* 30 d and 7 d graded bets with a priced close in `live_all.json`, split by submit-to-commence hours (< 1,
  1-6, > 6). Fee-net CLV per bucket with event-clustered 95% ranges. A forward copy follows on bets submitted from
  11-25, once the > 6 h bucket reaches 100 games.
- *Decision rule:* GO (name a fair-refresh-before-submit or a submit-closer-to-start challenger for a later window)
  iff ALL three hold: (1) the > 6 h bucket's fee-net CLV has a 95% upper bound < 0 on the 30 d set; (2) the < 1 h
  bucket's range includes or exceeds 0; (3) the forward set keeps the same order. Otherwise KILL.

How it is computed (fixed before the numbers are read):
- Orders come from the newest Portfolio Watch reading's `live_all.json` (20261127T180404Z).
- Each bet and its CLV come from `scripts/live_book_edge_readout.py`'s own `bets_from_orders` and the same-book
  scope, the same code that produces the review's CLV figures. That covers fee-net CLV, the close scope and the
  event-clustered SE (`_clustered_mean`); range = mean +- 1.96 SE.
- Windows are by `selected_date`: 30 d = 10-28..11-26 and 7 d = 11-20..11-26, the review's last complete day.
- Hours = `commence_time` minus `submitted_at`. Read literally, the frozen "< 1" bucket also holds in-play bets
  (hours < 0). The rule uses the literal bucket. A pregame-only 0-1 h row and an in-play row are shown beside it
  as a sensitivity, and they do not change the verdict. Bets with no readable `commence_time` or `submitted_at`
  are counted and left out.
- If (1) or (2) fails on the 30 d set, the verdict is KILL now and no forward copy is owed. If both pass, the
  verdict is "30 d half PASS, forward copy owed", not GO.
