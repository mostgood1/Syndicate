# Soccer spreads: the side labels were never the problem. The AH line SIGN splits one market into two one-sided rows.

**2026-09-08, lane `mlb-live-segment-pricing`, session 3492626c.**
Root cause of `no_two_sided_market_price` on soccer spreads — the defect
`d926be42` (canonical sides) was aimed at and did not close.

## The measurement

`soccer_source/eredivisie/api/odds/game_odds_current.csv`, grouped by
`(away, home, line, book)` — the shape a two-sided de-vig needs:

```
Willem II @ AZ Alkmaar   line '-2.25'  book bovada   sides=['AZ Alkmaar']   ONE SIDE
Willem II @ AZ Alkmaar   line  '2.25'  book bovada   sides=['Willem II']    ONE SIDE
Groningen @ Go Ahead Eagles  line '0.0'  book lowvig sides=[both]           BOTH

quote groups with BOTH sides:  2
quote groups with ONE side:   36
```

**Asian handicap stores the line SIGNED PER SIDE.** `AZ Alkmaar -2.25` and
`Willem II +2.25` are the same market — one bet, two legs — but any grouping
keyed on `line` puts them in different buckets, and each bucket then holds a
single leg. `_no_vig_over_probability` returns None because the row it is handed
genuinely has one side. **The de-vig is correct. The grouping upstream is
wrong.**

## It explains every observation

- **h2h works** (18/18 on the live fixture): h2h rows carry an empty `line`, so
  home / Draw / away all group together.
- **spreads fails ~universally**: AH lines are mirrored, so the legs never meet.
- **The only two working groups are `line 0.0`** — the one value whose mirror is
  itself.
- **The canonical-sides fix could not have helped.** It maps club names onto
  `home`/`away`, which is a real and necessary translation; but mapping the one
  side present still leaves one side. That fix addressed a genuine defect that
  was not the binding constraint.

## What was ruled out on the way, and how

- **Club-name vocabulary.** The live fixture's h2h resolved **18/18** while its
  spreads resolved **0/15**, and both run through the same
  `_canonical_side_view`. `teams_match` demonstrably handles "Excelsior" and
  "NEC Nijmegen".
- **Handicap embedded in the side label** (`"Excelsior +0.25"`). Checked across
  all ten leagues: sides are bare club names everywhere.
  `eredivisie 40 spreads rows | 14 distinct sides | handicap-in-label: 0`.
  The three bundesliga "hits" were false positives from a digit test —
  `FC Schalke 04`, `1. FC Köln`.

## The fix, not yet made

Pair AH legs by the mirrored line: `(home, +L)` belongs with `(away, -L)`. The
join key for a two-sided handicap is `(fixture, book, abs(line))` with the sign
carried on the side, not `(fixture, book, line)`.

Worth checking whether the same shape affects other sports' `spreads_alt` before
fixing it in one place only.

## Status of the earlier claim

`d926be42`'s commit message says the canonical-sides translation would move
soccer spreads off "0 of 874 priceable". **It will not, on its own.** The
translation is still correct and still needed; it is simply downstream of a
market that arrives already split in half.

---

## CONFIRMED 2026-09-08 19:07Z — the prediction above held, on a real population

The post-deploy watcher cleared its six-distinct-fixture floor against live
`47d84a5e` (the canonical-sides fix `d926be42`, **not** the pairing fix):

```
VERDICT   6 fixtures / 37 spreads rows
  with market_fair_prob   0/37  = 0.0%
  priceable               0/37
  CONTROL h2h            37/37  carry a market price
  reasons  no_two_sided_market_price: 36
           live_resim_published_no_distribution_for_this_market: 1
```

Fixtures: Excelsior @ NEC Nijmegen, Sheffield United @ Blackburn Rovers,
Preston North End @ Watford, Swansea City @ Southampton, Stoke City @ Cardiff
City, West Ham United @ Bolton Wanderers.

**Three things this settles.**

1. **`teams_match` is EXONERATED, and this time the population can carry it.**
   h2h resolved **37/37** across all six fixtures while spreads resolved 0/37,
   and both run through the same `_canonical_side_view`. The earlier 18/18 read
   the same way but came off ONE fixture — the exact n=1 shape this watcher was
   rebuilt to refuse, so it was not evidence when it was first cited. It is now.

2. **`d926be42`'s commit message is wrong and stays wrong.** It claimed the
   canonical-sides translation would move soccer spreads off "0 of 874
   priceable". Measured: 0 of 37, 0.0%, against `model_home_win_prob` set on
   ~94% of rows. The translation is still correct and still needed; it simply
   sits downstream of a market that arrives already split in half. **This was
   predicted in the section above BEFORE the reading existed** — it is a
   confirmed diagnosis, not a retraction under a bad number.

3. **36 of 37 failures are `no_two_sided_market_price`** — the exact signature
   of the sign split, and the exact refusal `6ff8f47b` targets.

**The baseline for the pairing fix is therefore `0/37 = 0.0% across 6 fixtures`,
not "0 of 874 over three days".** The three-day figure mixes code versions; this
one is a single-version reading with a working control beside it, so it is what
the post-deploy number must be compared against.

The watcher's parting line ("next step is `teams_match` on these leagues' club
names") was retired in the same pass — a false lead left in a log that a future
session reads is worse than no lead.
