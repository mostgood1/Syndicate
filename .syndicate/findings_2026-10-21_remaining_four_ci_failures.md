# The remaining four ci-suite failures: one was already fixed, three were stale TESTS — and one of those stale tests was hiding a real defect

`[2026-10-21 13:15Z / 08:15 CDT]` session `4ab694ed`
lane `ci-suite-four-stale-1021`
`[no outcomes used; a test-suite + code-reading measurement, plus one behaviour fix]`

Closes the four left unattributed in
`findings_2026-10-21_full_suite_seven_real_failures.md`. That file deliberately
reported names without causes (`--tb=no`), and said so. This is the causes.

## The headline

**None of the four was a product regression.** Three were test expectations
that had gone stale against DELIBERATE code changes, and the fourth had already
been fixed by someone else. But taking them seriously turned up **one real,
user-visible defect** that the stale test was sitting on top of: the
cards-backed MLB live lens counted a **postponed game as final**.

So "it's just a stale test" was true of the assertion and false of the file.

## Instrument first

The earlier run was in the fleet checkout (which has `data/`), and the fleet is
**not** at `origin/main` — it was `3fffb430b`, then `085fe1e81` while I was
reading it, 5 behind. A test failing there can already be fixed on main, so I
checked before diagnosing:

```
git diff --stat HEAD..github/main -- tests/test_archives.py tests/test_intelligence.py \
    tests/test_nba_live_resim.py tests/test_ncaaf_team_aliases.py
```

**Empty** — the four test files are byte-identical between the fleet checkout
and `github/main`, so for these four the fleet checkout is a valid instrument.
That check is the only reason the diagnosis below can be trusted; it is not
ceremony.

(The `git fetch github main` this needed updates remote refs only. Nothing was
checked out and nothing was deployed.)

## 1. `test_nba_live_resim::test_league_keyword_threads_through_storage_and_names` — ALREADY GREEN

Passes on the fleet now. Fixed by someone else between the 2026-10-21 01:25Z
run and 13:00Z. Nothing to do, and worth stating plainly: a name on a
seven-failure list is a reading from a moment, not a standing fact.

## 2. `test_archives::test_mlb_live_lens_empty_date_does_not_inject_fake_sample_games`

**Symptom.** The expected counts dict was six keys written out by hand;
`_snapshot_counts` now returns seven. The extra key is `postponed`, added
2026-10-16 for a good reason — StatsAPI files a postponed game under abstract
`"Final"` and says "Postponed" only in `detailed`.

**So the test was stale. But the same change had been applied to ONE of the two
paths that build this payload.** `syndicate/features/mlb/live_lens.py` builds
`counts` twice:

| | `_snapshot_counts` (snapshot path) | the cards-fallback `payload["counts"]` |
|---|---|---|
| `postponed` key | present | **absent** |
| postponed game counted as | `postponed` | **`final`** |

The second row is the defect, and it is not a missing key — it is a wrong
number. `_card_status_bucket` had no postponed branch, and because a
postponement arrives as abstract `"Final"`, its `"final"` token test matched
first. **Measured, HEAD vs fixed, on the same card:**

```
HEAD  on {"abstract": "Final", "detailed": "Postponed"} -> final
FIXED on the same card                                  -> postponed
```

(Run by extracting HEAD's own function body with `git show` and calling it, so
the before-state is a reading and not a recollection.)

**Fixed:** `_card_status_bucket` checks `not_played_reason(status)` first, the
same way `_status_bucket_from_row` has since 2026-10-16; the cards-fallback
counts loop counts postponements separately instead of folding them into the
`else` (pregame) branch; and the fallback `counts` dict carries the same key set
as `_snapshot_counts`, so a consumer reading `counts.postponed` gets a number on
both paths. Safe at all three call sites of the bucket function — the `== "live"`
test is unaffected, and the `.title()` fallback only runs when a card carries no
status dict at all, where `not_played_reason({})` is falsy.

**Test rewritten to DERIVE the shape**, not pin it: `assertEqual(counts,
_snapshot_counts([]))` plus an independent "every value is zero". The second
assertion is what makes it non-circular, and that is **demonstrated, not
argued** — patching `_snapshot_counts` to report `games: 3, live: 1` for an
empty slate leaves the first assertion happily agreeing with the lie and the
second one fires.

## 3. `test_intelligence::test_intelligence_blotter_view_includes_odds_projected_and_live_columns`

**Third formulation of this test, and the second drift.** Its own comment
records the first: on 2026-08-15 it pinned `<th>Odds</th><th>Projected</th>…`
and went red when #240/#243 made the blotter sortable, "without anything being
dropped". It was rewritten to pin column DEFINITIONS instead — and those
drifted too.

Checked what the code does now, the same way that comment says it was checked
last time. **All three values still render; nothing was dropped:**

- a price — `<td data-label="Best price">${renderBlotterBook(item)}`, which
  reads `firstNumeric(quote?.price, item?.odds)`. The column key went
  `odds` → `book`.
- the projection — folded INTO the Sim cell as the muted `proj …` line. The
  template's own comment at `BLOTTER_COLUMNS` says so:
  `Projected + Win% + the sim tags -> Sim`.
- the live value — still its own `liveOnly` column, still reading
  `item.live_projection`.

**Rewritten on the data axis.** Labels and column keys are no longer asserted at
all: they are presentation, they have drifted twice, and each drift read as a
regression. What is pinned now is what each cell READS — `quote?.price` /
`item?.odds`, `displayProjection`, `item.live_projection` — which is the server
contract the blotter consumes. Deleting a column still deletes its reader, so
the guard still fires; renaming a header no longer breaks it.

Plus one structural assertion, because a reader can survive a column's removal:
the column keys are parsed out of `BLOTTER_COLUMNS` and `{"live", "actual"}`
must be among them. **Verified non-vacuous:** the regex extracts all ten real
keys (`actual age book ev fair live move pick score winpct`), and removing the
live column from a copy makes the assertion fire.

## 4. `test_ncaaf_team_aliases::test_match_event_blob_can_now_resolve_an_fbs_pairing`

The one that could have been real money, so it got the most care. Its last line
asserted *"an FCS visitor still refuses rather than guessing"* and the code now
returns `ok` for Wagner @ James Madison.

**It is not guessing. The FCS reach was added on purpose.** `match_event_blob`
resolves through `kalshi_catalogue.club_key` → `chip_join_key`, which for NCAAF
is the **CFBD registry, all four divisions** — not `team_aliases.canonical_team`,
whose NCAAF map is FBS-only. Its docstring carries the measurement from that
change (2026-10-16): over 254 Kalshi `KXNCAAFGAME` names, **118 unresolved by
`canonical_team` against 7 by `chip_join_key`**. Confirmed live:

```
canonical_team("ncaaf", "Wagner Seahawks") -> None
club_key      ("ncaaf", "Wagner Seahawks") -> 'wagner'
```

**And the no-guess property holds, on every way I could think of to break it:**

| probe | result |
|---|---|
| `WAGJMU` vs Wagner@JMU | `ok`, g3 |
| `WAGJMU` vs Wagner@**NowhereState** | `no_match` |
| `WAGJMU` vs **NowhereState**@JMU | `no_match` |
| `WAGJMU` vs [Wagner@JMU, **Washington**@JMU] | `ok`, picks Wagner@JMU |
| `WASJMU` vs the same two | `no_match` |
| `WAGJMU` vs the same fixture twice | `ambiguous`, `count: 2` |
| `ZZZQQQ` vs a real game | `no_match` |
| any blob vs `[]` | `no_match` |

It is also structurally safe in a way the proxy never was: the function
**inverts** the problem — it builds `AWAY+HOME` from the games WE already have
and looks for the blob among those, so a fixture we do not hold cannot be named
at all. Its own docstring: *"Our own schedule supplies the boundary that the
string omits, so no guess is required."*

**So "FCS refuses" was only ever a PROXY for "never guess", and the proxy
expired while the property held.** The property is now asserted directly, with
all eight probes above. Note the Washington decoy line specifically: Washington
IS resolvable (`club_key` → `'washington'`), so that refusal is not for want of
a club — it is because our Washington fixture does not generate that blob. The
test says so, because the reason matters more than the verdict.

## What links three of the four

All three stale tests were broken by deliberate, well-reasoned changes made on
**2026-10-16**, by three different pieces of work, none of which updated the
test that pinned the old behaviour. The suite then read as "red for five days"
when the product was fine. That is the cost of pinning a PROXY or a LABEL
instead of the thing you care about — and in case 2 it was also the cover under
which a genuine wrong number sat.

## Verification

- `test_archives` node id: **passes**. Non-circularity demonstrated by patching
  the counter to lie.
- `test_intelligence` node id: **passes**. Key regex shown non-vacuous and shown
  to fire when the live column is removed.
- `test_ncaaf_team_aliases` node id: **passes** — but only with a registry. It
  SKIPS in a session worktree, and its own skip message says *"an absent
  registry means they did not run"*, so a skip was never accepted as a pass.
  Run with `SYNDICATE_DATA_ROOT` pointed at the primary tree's `data/`
  (`fbs_canonical_names()` → 138). That mirror is lossy by CLAUDE.md's rule, but
  a team registry is a static table rather than a dated artifact, so it is the
  right kind of thing to read from it — said here so the next reader can
  disagree.
- `test_nba_live_resim` node id: **passes**, and was already passing.
- `_card_status_bucket`: before/after measured on the same postponed card.

## Left open

The `postponed` fix is on the cards-backed path only because that is where the
two shapes disagreed. I did not audit whether anything else in the MLB live lens
treats a postponement as a completed game — the three call sites of
`_card_status_bucket` were checked and are safe, and that is the extent of it.
