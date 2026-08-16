# Syndicate UI audit brief — MLB as reference

Run in Claude Code. Read-only pass; findings go to `.syndicate/`, fixes get
their own lanes.

MLB is the standard. That does **not** mean "make everything look like MLB" —
it means MLB's implementation is the source of truth for tokens, card
structure, and interaction patterns, and every divergence elsewhere is either a
bug or a justified sport-specific difference. This audit's job is to sort
divergences into those two piles.

---

## 0. Extract the standard first

Before looking at any other sport, write down what MLB actually does — concrete
values, not adjectives.

- The compact game card: which fields appear, in what order, at what sizes,
  with what spacing and truncation rules. Screenshot it.
- Type scale in use: every distinct font-size/weight/line-height combination
  on the card and the sport page.
- Color tokens: are they design tokens / CSS custom properties / Tailwind
  classes, or hardcoded values?
- Tab component: which component, how state is held, how it behaves when a tab
  has no data.
- Loading, empty, and error states.

Output a short spec. Everything below compares against it.

---

## 1. Component divergence — is this one component or N copies?

The likely root cause of "feels the same but isn't." Determine whether other
sports **reuse** MLB's components or **forked** them.

- Grep for duplicated card/tab components (`*Card`, `*GameCard`, `*Tabs`) and
  identify near-duplicates.
- For each sport, list which components are shared vs. sport-local.
- Where a fork exists, diff it against the MLB original and record what
  actually changed.

A fork that has drifted is the standard failure here: it looks right the day
it's copied, then every MLB fix lands in one file and not the others.

---

## 2. Data contract — probably the real source of the inconsistency

Sports genuinely have different data shapes, and cards built around MLB's shape
break in specific ways elsewhere. Check each:

- **Two-way vs. three-way markets.** Soccer has draws. A card laid out for
  home/away has no slot for it. How is this handled — a third row, a squeezed
  layout, a dropped outcome?
- **MLB-specific fields with no analogue** — probable pitchers, innings. Does
  the card render an empty region, a placeholder, or collapse cleanly?
- **Sport-specific fields with no MLB slot** — soccer competition/leg, aggregate
  score, red cards; basketball quarters.
- **Null and missing handling.** For every field: does missing data render
  blank, `—`, `N/A`, `undefined`, `0`, or collapse the row? Inconsistency here
  reads to users as "the app is broken for this sport," and it's usually the
  single highest-impact fix.
- **Team/competition name length.** MLB names are short and uniform. Soccer
  club names are long and irregular. Where do they wrap, truncate, or overflow?
- Do all sports come through one normalized view model, or does each page shape
  raw feed data itself?

For each sport, produce the list of fields the card expects and whether the
feed actually supplies them.

---

## 3. Tabs

"Tabs working" is the stated complaint, so isolate the failure mode rather than
noting that tabs are broken.

- Which tabs exist per sport? Is the set hardcoded or derived from available
  data?
- Does a tab render when there's nothing behind it — and if so, what does the
  user see?
- Is tab state per-page, in URL, or global? Does switching sport reset it, or
  leave a selected tab that doesn't exist in the new sport?
- Are there console errors on tab switch? Check each sport.
- Keyboard and focus behavior.

---

## 4. Typography and readability

Report measured values, not impressions.

- Every distinct font-size on game cards, per sport. Flag anything under 14px
  for body text and under 12px for metadata.
- Are sizes coming from a scale, or ad-hoc px values? Count the distinct values
  — a large count is the finding.
- Line-height on dense card rows; contrast ratios for secondary/muted text
  against its actual background (muted-on-tinted-card is where this usually
  fails, not muted-on-white).
- Tabular figures for scores, odds, and line values. Proportional digits on
  numeric columns cause visible jitter on live-updating values, which matters
  here more than in most apps.
- Touch target sizes on mobile for tabs and card controls.

---

## 5. Card density and layout

- Fixed or variable card height? Variable heights across a grid is a common
  cause of "compact for MLB, messy for everything else."
- What happens at each breakpoint per sport.
- With the longest realistic team names and a three-way market, does the layout
  hold?

---

## 6. Live-update behavior

Given the publish pipeline: when an artifact updates, does the card re-render
cleanly or flash/reflow? Does it differ by sport? Worth checking on the sports
with the highest publish rates.

---

## 7. Output

Write a dated note to `.syndicate/` containing:

1. The MLB spec from section 0
2. A **divergence matrix** — rows are sports, columns are (component reuse,
   data contract, tabs, typography, density) — each cell marked matches /
   diverges-as-bug / diverges-legitimately
3. Screenshots per sport at desktop and mobile widths
4. Ranked fix list, most user-visible first

Then propose — do not implement — the consolidation: which forked components
should collapse back into one parameterized component, and what the sport
config needs to express (market shape, sport-specific slots, field labels) so
that legitimate differences are configuration rather than separate code.
