# UI audit, 2026-08-14 — what is here and how to re-run it

The report is `.syndicate/audit_2026-08-14_ui.md`; the lane plan derived from it
is `.syndicate/plan_2026-08-14_ui.md`. **This directory is the evidence, not the
instrument.** The instrument is `scripts/ui_layout_probe.py`:

```bash
py -3 scripts/ui_layout_probe.py --base-url https://syndicate-an21.onrender.com --sports soccer,nfl,ncaaf
```

It measures, per sport and at 1440 and 390: horizontal overflow, card-height
spread, tab/panel id agreement, tab click-through, touch targets, the computed
type scale per class **per surface**, tabular figures, unstyled links, repeated
copy, and empty regions. Exit code 0 only if everything passes.

---

## Two probe results from this audit were WRONG. Read this before trusting a number.

### 1. `el.click()` is not a click, and it produced a retraction

The original tab results were produced with a synthetic `el.click()` in
`page.evaluate`. **WNBA was reported as having broken tabs. WNBA's tabs work.**
The finding was retracted.

Only Playwright's `locator.click()` — a real input event through the browser's
own dispatch — is trusted. `scripts/ui_layout_probe.py` uses it, and the cost is
a `scroll_into_view_if_needed` per tab. Do not "optimise" that away. If you are
extending the probe and reach for `page.evaluate("el.click()")`, this paragraph
is the reason not to.

### 2. `querySelector` takes the FIRST match, and one class can live on two surfaces

The type-scale table was built with `document.querySelector(selector)` — one
element per class per page. `.cards-head-team-name` is used by **both** the
scoreboard strip and the game card, and soccer ships a bespoke strip that
deliberately sets 13px (`.cards-strip-card--soccer`, with `white-space: nowrap`
+ ellipsis, which is the *documented fix* for club names breaking mid-word in a
~52px box).

So the table read "soccer 13px / NFL 16px", the audit turned that into a defect
— §2 "13px team names", and plan item **G1** "raise 13px to match the 16px used
elsewhere" — and it was wrong twice over: the card-head name had been 16px all
along, and the 13px belonged to a different element that Lane E had just written
a rule for. Measured on production 2026-08-15, all four elements on the page:

| surface | tag | size | colour | decoration |
|---|---|---|---|---|
| strip | `<div>` | 13px | `rgb(237,244,251)` = `--cards-text` | none |
| strip | `<div>` | 13px | `rgb(237,244,251)` | none |
| card head | `<a>` | **16px** | **`rgb(0,0,238)`** | **underline** |
| card head | `<a>` | **16px** | **`rgb(0,0,238)`** | **underline** |

The real defect was a colour one — an anchor nobody had restyled, falling
through to the user agent's default link blue. It was fixed as such; the 13px
was left alone.

The probe now reports the type scale **keyed by surface**, and flags a class
whose size differs between surfaces as `conflated` rather than silently
collapsing it to its first hit. Any per-class table over a shared stylesheet
needs that, because the whole point of a shared stylesheet is that one class
renders in more than one place.

### 3. A related trap the probe now guards: a clean run against a 502

On 2026-08-15 the probe printed a full table of `0 cards / 0px overflow` and
exit code **0** while every route on production was returning HTTP 502.
Render's error page has no cards and does not overflow. The probe now records
`httpStatus`, fails on `>= 400`, and fails on a sport serving zero cards unless
that sport is in `OUT_OF_SEASON`.

**`OUT_OF_SEASON` is `{nba, nhl, ncaab}` and needs reviewing in October.**
Leaving a sport in that set after its season opens converts a real outage into a
green run — the same shape as the two errors above: a value that means "nothing
here" being read as a measurement.

### 4. A selector that matched nothing was DROPPED from the report

Same family, found 2026-08-15 while re-checking the tabular-figures claim. The
old probe did `querySelector(sel); if (!el) return;`, so a class that matched
zero elements produced no key, and `summarize()` had no branch for a missing
key. NCAAF serves 16 cards and matches **zero** `.cards-market-main`; that read
as a pass. A numeric class with 0 elements on a sport that is serving cards now
FAILS the run — the honest state of that measurement is "did not run", not
"fine".

### 5. And the correction that caught me on the way to fixing 4

I first reported that all three numeric classes matched zero elements on MLB —
i.e. that the check had never measured the platform's biggest sport. **That was
wrong.** MLB renders through `cards_source.js`, and I had sampled 600 ms after
load, before the renderer had created anything. Measured through the probe's own
timing: `.cards-data-pair strong` 495, `.cards-market-main` 60,
`.cards-mini-metric strong` 30, every one of them `tabular-nums`. Lane E's fix
landed on MLB exactly as claimed.

**Rule: on MLB, never read the DOM on a fixed short delay.** Every other sport
renders server-side and is stable at load; MLB is not, and a single early read
of an async render will hand you a confident zero.

### The shape all five share

A value meaning *"this was not measured"* — a missing element, a dropped key, an
error page, a first-of-many match, a render that has not happened yet — read as
a value meaning *"this is fine"*. When a probe reports good news, the question
to ask first is what a bad reading would have looked like, and whether the
instrument could have produced one.

---

## What the PNGs are

Screenshots at 1440×1200 and 390×844 per sport, taken 2026-08-14 against
production web `f9aa2399`. They are the **before** state for Lanes E, F and G
and should not be regenerated in place — a later screenshot under the same
filename destroys the comparison. `audit.json`, `probe2.json` and `probe3.json`
are the raw readings behind the report's tables, from the throwaway probes that
`scripts/ui_layout_probe.py` replaced.

`ncaaf_tab_game_BLANK.png` and `ncaaf_tab_context_OK.png` are the E1 defect: the
default tab addressed a panel id that did not exist, so the card collapsed to a
187px header strip.

## Rows that were never measured

NBA, NHL and NCAAB served **0 cards** on 2026-08-14 — out of season. Their rows
in the report's divergence matrix are read off the code, not off a rendered
page. Re-measure when those seasons open before relying on anything in them.


---

## The height model: what the `layout residual` figure is

Raw card-height spread is **not** a layout signal on MLB. It tracks how much
data each game has: height is `chrome + k * content`, and MLB serves 41-57
`.cards-data-pair` per card, so the raw number moved 796 -> 1716 -> 1583 ->
1125px across four readings with no code change.

The probe fits `height = chrome + k * units` **per game state** and reports the
RESIDUAL from that fit. Baseline, production 2026-08-15, render fully settled:

    mlb mobile   Live     n= 3   residual   6px   (832px chrome + 68.2px/pair)
    mlb mobile   Preview  n=10   residual  54px  (1029px chrome + 62.5px/pair)
    mlb desktop  Live     n= 3   residual  18px

`LAYOUT_RESIDUAL_BUDGET_PX = 150` is ~3x the worst clean reading. Re-derive it
if the card design changes; **do not widen it to silence a run.**

### Three things that were learned building it, all the hard way

**1. `height / units` is the obvious form and it is wrong.** The fit has a
**1051px intercept** — head, market tiles, tab rail. A ratio reads 94px/pair on
a 33-pair card and 82px/pair on a 53-pair one and calls that a 15% layout
difference. It is not a difference; it is the constant.

**2. Fit inside a game state, not across the slate.** One line over all 15 MLB
cards gave a residual of **668px**; the same fit restricted to the 10 Preview
cards gave **52px**. A live card carries content the unit does not count.

**3. The model is only valid where the summary grid stacks single-column.** On
mobile it does, and the residual is 6-54px. On desktop the grid wraps into
columns, so height is linear in ROWS, not pairs — same cards, same instant,
residual 201px against 261px of explained range. A poor fit is declared
`UNRELIABLE` and reports having no signal, rather than firing an alarm that
would make the run permanently red on a healthy board.

### And the measurement bug it exposed

Building this found that **every MLB figure this probe had produced was taken
mid-render.** `wait_for_selector` proves a card ATTACHED, not that the render
finished. Total `.cards-data-pair` across 15 MLB cards at 390px:

    +0ms 482   +600ms 530   +1200ms 590   +2000ms 683   +3000ms 719   +4500ms 719

The old fixed 600ms settle measured MLB at **74% of its final content**. The
probe now polls a DOM fingerprint until it is stable across two consecutive
samples (`_settle`), records `settledMs`, and **fails** if the render never
settles — because a still-growing page makes every figure on that row
provisional. MLB settles at 3.6-4.0s; every other sport at 0.8s.
