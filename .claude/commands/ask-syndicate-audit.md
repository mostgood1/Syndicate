# "Ask the Syndicate" audit brief

Run in Claude Code. Read-only; findings to `.syndicate/`, fixes as separate
lanes.

Three stated problems: answers aren't accurate enough, behavior differs by
sport, and it needs to do more. Sections 1 and 2 usually explain the first two,
and both should be settled before building anything new — expanding on a weak
grounding layer multiplies the error surface instead of adding capability.

---

## 1. Grounding architecture — settle this first

Establish exactly how a question becomes an answer. Trace one real request end
to end and write down every step.

Which pattern is it?

- **Tool / function calling** into the data layer — the model requests specific
  games, odds, or model outputs and gets structured results back
- **Embedding retrieval** over artifacts or generated text
- **Prompt stuffing** — a slab of current data injected into every request
- **Ungrounded** — the model answers from training data plus whatever's in the
  system prompt

### The question this determines

Most questions users ask a betting assistant are **aggregation and filtering**
questions, not retrieval questions: "biggest edges tonight," "which totals moved
most since open," "who's favored in the late games." Semantic similarity cannot
answer those. Embedding search retrieves documents that *read* like the query,
then the model does arithmetic over an arbitrary subset it happened to receive —
and produces a confident, specific, wrong number. If that's the architecture,
the accuracy problem is structural and no amount of prompt tuning fixes it.

So: for each class of question in section 3, determine whether the retrieval
layer can in principle return the data needed to answer correctly. Report that
as a capability, not as a quality score.

### Single source of truth

Does chat read the same view model the game cards read, or its own path into
the data? If they can diverge, they eventually will, and a user who sees one
number on the card and a different number in chat stops trusting both. Check
whether a divergence is possible today, and construct a case where it happens.

---

## 2. Sport coverage — the likely cause of the inconsistency

Same root cause as the UI audit: built for MLB first, extended sideways.

- Read the system prompt. Does it hardcode MLB vocabulary — innings, probable
  pitchers, run line? Does it describe the data shape in MLB terms?
- Are the tools/retrieval scoped per sport, or does one generic path silently
  return less for some sports?
- **Three-way markets.** Can it reason about draws, or does it treat every
  market as two-outcome? Ask it directly about a soccer draw price and see.
- Entity resolution: team name and alias handling across sports. Soccer club
  names collide and abbreviate irregularly ("United", "City", multiple clubs
  per city). How are ambiguous names resolved — and what happens when they
  can't be?
- Competition/league scoping. Does it know which league a match belongs to, and
  can it filter by one?
- Time zones and "tonight" / "today" resolution across international fixtures.
  This alone breaks a lot of soccer answers.

Produce a per-sport capability matrix: for each question class, does it answer
correctly, answer wrongly, or decline?

---

## 3. Question taxonomy and evaluation

Nothing here is measurable without this.

- Pull real questions from logs. If questions aren't logged, that's finding #1
  and everything else is anecdote.
- Cluster them into classes: single-game lookup, cross-game ranking, historical
  performance, explanation of a model output, strategy/advice, out-of-scope.
- Note which classes are most common and which fail most often — they're not
  the same list, and that gap is your priority order.

### Build a regression set

Assemble ~50 questions with **verifiable** answers, spread across sports and
question classes, including deliberately hard ones: ambiguous team names,
questions about games that don't exist, three-way markets, questions the data
genuinely can't answer.

Score each response for:

- **Numeric accuracy** — does the number match the source of truth
- **Staleness** — does it reflect current data (section 4)
- **Hallucinated entities** — teams, games, or stats that don't exist
- **Overreach** — confident claims beyond what the model supports
- **Appropriate refusal** — does it say "I don't know" when it should, or
  always produce something

That last one deserves weight. A chat feature that answers everything is worse
than one that declines cleanly, because users can't tell the two modes apart.

---

## 4. Freshness

Odds move; answers age badly.

- What's the lag between a line changing and chat reflecting it?
- Is there caching between the data layer and the answer? What's the TTL?
- Does the answer state *as of when* it's true? For a live-odds product this
  should be in the response, not a footnote.
- With the publish pipeline in mind: can chat serve from an artifact that the
  checksum guard correctly skipped re-publishing but that is nonetheless
  the current truth? Confirm the guard's skip path can't be read as staleness.

---

## 5. Confidence and framing

This is a betting product, so calibration of *tone* matters as much as
calibration of probability.

- Does chat have access to model confidence, or only point estimates? If only
  point estimates, it will present a coin-flip and a strong edge in identical
  language.
- Connect to the confidence gate from the model audit: chat should surface an
  edge only where the same threshold the UI uses would surface it. Check
  whether that's true today.
- Does it ever imply certainty about outcomes? Grep the system prompt for what
  it's told about hedging.
- Is responsible-gambling framing present, and does it hold under adversarial
  phrasing ("how much should I put on this")?
- Jurisdiction: does it give the same answers regardless of where the user is?

---

## 6. Cost and latency

Not flagged as a problem, but section 7 will make it one.

- Tokens and cost per question; the distribution, not the mean
- Latency, including retrieval and tool round-trips
- What a 10x volume increase costs
- Any caching of identical questions

---

## 7. Expansion — only after 1–4

Rank candidate additions against measured failures rather than ideas:

- Which frequent question classes currently fail?
- Which would become answerable purely by exposing a tool over data that
  already exists?
- Which need new data?

Prefer widening the tool surface over widening the prompt. Every capability
added by describing it in the system prompt is a capability with no guardrail
behind it.

---

## 8. Output

To `.syndicate/`, dated:

1. Grounding architecture — the actual traced path, with a verdict on whether
   it can support aggregation questions
2. Per-sport capability matrix
3. Regression set (checked in, runnable) and current baseline scores
4. Freshness and confidence findings
5. Ranked fix list, with the grounding verdict at the top if it's negative

No code changes this pass. If the regression set is the only artifact that
comes out of this, it was still worth running — it's the thing that makes every
later change measurable.
