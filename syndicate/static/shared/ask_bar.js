// Ask-the-Syndicate board embed, added 2026-08-03 (Phase 3 item 9). Prior
// to this, Ask-the-Syndicate was a "well-crafted island" -- a separate
// /syndicate page behind a single-shot search box, disconnected from the
// board a bettor is actually looking at. This reuses the exact same JSON
// API (/api/syndicate/query, unchanged) from a persistent panel embedded in
// the board itself, plus a per-card "Ask about this pick" action that
// pre-fills the question's context from the same data-syndicate-* attributes
// bet_slip.js/watchlist.js already read.
//
// Deliberately NOT built here: server-side conversational memory (passing
// prior turns back into the Claude call). The panel below shows a real
// scrollback of the conversation so far, but each question is still
// answered independently, exactly like the standalone /syndicate page --
// feeding history into every LLM call would multiply this feature's token
// cost per question, a real ongoing-cost decision that needs a deliberate
// call, not something to take on silently while embedding the UI.
window.SyndicateAskBar = (function () {
  "use strict";

  const TRANSCRIPT_STORAGE_KEY = "syndicate_ask_transcript_v1";
  const COLLAPSED_STORAGE_KEY = "syndicate_ask_collapsed_v1";
  const MAX_TRANSCRIPT_ENTRIES = 20;
  const REQUEST_TIMEOUT_MS = 45000;

  let transcript = loadTranscript();
  let collapsed = loadCollapsed();
  let panelWired = false;
  let inFlight = false;

  function escapeHtml(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, (char) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[char] || char));
  }

  function safeText(value, fallback) {
    const text = String(value == null ? "" : value).trim();
    return text || (fallback ?? "");
  }

  function loadTranscript() {
    try {
      const raw = window.localStorage.getItem(TRANSCRIPT_STORAGE_KEY);
      const parsed = raw ? JSON.parse(raw) : [];
      return Array.isArray(parsed) ? parsed : [];
    } catch (error) {
      return [];
    }
  }

  function saveTranscript() {
    try {
      window.localStorage.setItem(TRANSCRIPT_STORAGE_KEY, JSON.stringify(transcript.slice(0, MAX_TRANSCRIPT_ENTRIES)));
    } catch (error) {
      // Storage unavailable -- transcript still works for this page load.
    }
  }

  function loadCollapsed() {
    try {
      return window.localStorage.getItem(COLLAPSED_STORAGE_KEY) === "true";
    } catch (error) {
      return false;
    }
  }

  function saveCollapsed() {
    try {
      window.localStorage.setItem(COLLAPSED_STORAGE_KEY, collapsed ? "true" : "false");
    } catch (error) {
      // Storage unavailable -- collapse state still works for this page load.
    }
  }

  // Same data-syndicate-* attributes bet_slip.js/watchlist.js already read
  // off a rendered card -- the exact context keys getPageContext() on the
  // standalone /syndicate page pulls from URL params instead.
  function contextFromCard(card) {
    const context = {};
    const attrMap = {
      sport: "data-syndicate-sport-slug",
      market: "data-syndicate-market",
      selection: "data-syndicate-selection",
      matchup: "data-syndicate-matchup",
      player_name: "data-syndicate-player-name",
      name: "data-syndicate-name",
      candidate_type: "data-syndicate-candidate-type",
    };
    Object.entries(attrMap).forEach(([key, attr]) => {
      const value = String(card.getAttribute(attr) || "").trim();
      if (value) context[key] = value;
    });
    return context;
  }

  function setStatus(text, tone) {
    const el = document.getElementById("ask-bar-status");
    if (!el) return;
    el.textContent = text || "";
    el.setAttribute("aria-busy", tone === "loading" ? "true" : "false");
  }

  async function askQuestion(question, context) {
    const trimmed = String(question || "").trim();
    if (!trimmed || inFlight) return;
    inFlight = true;
    collapsed = false;
    saveCollapsed();
    setStatus("Thinking…", "loading");
    renderPanel();

    const controller = new AbortController();
    const timeoutId = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
    const entry = { question: trimmed, context: context || {}, askedAt: new Date().toISOString() };
    try {
      const response = await fetch("/api/syndicate/query", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: trimmed, context: context || {} }),
        signal: controller.signal,
      });
      const payload = await response.json();
      if (!response.ok || !payload || payload.ok !== true) {
        throw new Error((payload && payload.error) || "The Syndicate API returned an error.");
      }
      entry.response = payload;
      setStatus("");
    } catch (error) {
      entry.error = error && error.name === "AbortError" ? "Timed out -- try a shorter or more specific question." : (error && error.message) || "Request failed.";
      setStatus("");
    } finally {
      window.clearTimeout(timeoutId);
      inFlight = false;
    }
    transcript.unshift(entry);
    transcript = transcript.slice(0, MAX_TRANSCRIPT_ENTRIES);
    saveTranscript();
    renderPanel();
  }

  function askTodaysBriefing() {
    void askQuestion("Summarize today's best opportunities across the board and what to watch for.", {});
  }

  function wireAskButtons(container) {
    const scope = container || document;
    scope.querySelectorAll("[data-ask-action='ask-pick']").forEach((button) => {
      button.addEventListener("click", (event) => {
        event.preventDefault();
        const card = button.closest("[data-syndicate-name]");
        if (!card) return;
        const context = contextFromCard(card);
        const subject = context.selection || context.name || context.matchup || "this pick";
        void askQuestion(`What's the case for and against ${subject}?`, context);
      });
    });
  }

  // Compact rendering of the same `briefing` block syndicate.html's
  // renderBriefing() draws in full -- narrative + top picks only, since
  // this is a sidebar widget answering quick questions, not a replacement
  // for the standalone page's deep-dive view (tables/charts/drivers/risks).
  function renderBriefingCompact(response) {
    const briefing = response && typeof response.briefing === "object" ? response.briefing : null;
    if (briefing) {
      const narrative = safeText(briefing.narrative, "");
      const picks = Array.isArray(briefing.top_picks) ? briefing.top_picks : [];
      return `
        ${briefing.headline ? `<div class="ask-bar__answer-headline">${escapeHtml(briefing.headline)}</div>` : ""}
        ${briefing.verdict ? `<div class="ask-bar__answer-verdict">${escapeHtml(briefing.verdict)}</div>` : ""}
        ${narrative ? `<div class="ask-bar__answer-narrative">${escapeHtml(narrative).replace(/\n+/g, "<br><br>")}</div>` : ""}
        ${picks.length ? `
          <div class="ask-bar__answer-picks">
            ${picks.slice(0, 3).map((pick) => `
              <div class="ask-bar__answer-pick">
                <span class="ask-bar__answer-pick-name">${escapeHtml(safeText(pick.selection, "Pick"))}</span>
                ${pick.why ? `<span class="ask-bar__answer-pick-why">${escapeHtml(pick.why)}</span>` : ""}
              </div>
            `).join("")}
          </div>
        ` : ""}
      `;
    }
    // `briefing` only exists when the optional LLM narration layer is on.
    // It is deliberately NOT in use, so the snapshot-shaped
    // structured_response below is the normal path, not a fallback.
    const structured = response && typeof response.structured_response === "object" ? response.structured_response : null;
    // Each schema_type nests its text differently: bet_analysis/matchup put
    // it under `explanation`, market_summary under `rationale_summary`.
    // Reading only the top-level `narrative`/`summary` found nothing for a
    // market_summary answer and printed "No structured answer came back"
    // over a perfectly good payload -- reported live 2026-08-03, with 5 real
    // opportunities attached to the response it was discarding.
    const nested = structured
      ? (structured.rationale_summary || structured.explanation || structured.market_insight || null)
      : null;
    // structured.recommendation (bet_analysis's own top-level field) is the
    // same per-pick prose the main board already renders under each card
    // (server-side: ask_the_syndicate_adapter.py's _candidate_prose, same
    // "detail" field the board's own pickReasoning checks first). Reported
    // live 2026-08-04: a correctly-matched, real pick's real board-quality
    // writeup existed on the candidate the whole time -- this just never
    // read it.
    const fallbackText = safeText(
      (structured && (structured.narrative || structured.summary || structured.recommendation))
        || (nested && typeof nested === "object" ? (nested.narrative || nested.summary) : ""),
      "",
    );
    // A market summary's substance is the opportunity list; render it the
    // same way briefing top_picks are rendered above rather than dropping
    // it because the prose slot was empty.
    const opportunities = structured && Array.isArray(structured.top_opportunities) ? structured.top_opportunities
      // matchup_analysis's own list, same shape/purpose as top_opportunities.
      : (structured && Array.isArray(structured.key_edges) ? structured.key_edges : []);
    if (fallbackText || opportunities.length) {
      return `
        ${fallbackText ? `<div class="ask-bar__answer-narrative">${escapeHtml(fallbackText).replace(/\n+/g, "<br><br>")}</div>` : ""}
        ${opportunities.length ? `
          <div class="ask-bar__answer-picks">
            ${opportunities.slice(0, 3).map((row) => {
              const name = safeText(row && (row.selection || row.name), "Opportunity");
              const market = safeText(row && row.market, "");
              const why = safeText(row && row.recommendation, "");
              return `
              <div class="ask-bar__answer-pick">
                <span class="ask-bar__answer-pick-name">${escapeHtml(name)}</span>
                ${market ? `<span class="ask-bar__answer-pick-why">${escapeHtml(market)}</span>` : ""}
                ${why ? `<div class="ask-bar__answer-pick-detail">${escapeHtml(why)}</div>` : ""}
              </div>`;
            }).join("")}
          </div>
        ` : ""}
      `;
    }
    // bet_analysis for a real, specific pick with no prose at all on the
    // underlying candidate (e.g. a steam-move alert, which is a market
    // signal rather than a modeled pick and genuinely has no writeup) --
    // still show the real numbers rather than a dead end.
    if (structured && structured.schema_type === "bet_analysis" && structured.selection) {
      const facts = [
        typeof structured.model_probability === "number" ? `Model ${structured.model_probability.toFixed(1)}%` : null,
        typeof structured.market_probability === "number" ? `Market ${structured.market_probability.toFixed(1)}%` : null,
        typeof structured.edge === "number" ? `Edge ${(structured.edge * 100).toFixed(1)}%` : null,
        typeof structured.EV === "number" ? `EV ${structured.EV.toFixed(2)}` : null,
      ].filter(Boolean);
      return `
        <div class="ask-bar__answer-picks">
          <div class="ask-bar__answer-pick">
            <span class="ask-bar__answer-pick-name">${escapeHtml(safeText(structured.selection, "This pick"))}</span>
            ${facts.length ? `<span class="ask-bar__answer-pick-why">${escapeHtml(facts.join(" · "))}</span>` : ""}
          </div>
        </div>
        ${!facts.length ? `<div class="ask-bar__answer-narrative ask-bar__answer-narrative--empty">No detailed numbers available for this pick yet.</div>` : ""}
      `;
    }
    return `<div class="ask-bar__answer-narrative ask-bar__answer-narrative--empty">No structured answer came back for this question -- try rephrasing it.</div>`;
  }

  function renderEntry(entry) {
    const contextBits = [entry.context && entry.context.selection, entry.context && entry.context.matchup].filter(Boolean);
    return `
      <div class="ask-bar__entry">
        <div class="ask-bar__question">${escapeHtml(entry.question)}${contextBits.length ? ` <span class="ask-bar__question-context">(${escapeHtml(contextBits.join(" · "))})</span>` : ""}</div>
        <div class="ask-bar__answer">
          ${entry.error ? `<div class="ask-bar__answer-error">${escapeHtml(entry.error)}</div>` : renderBriefingCompact(entry.response || {})}
        </div>
      </div>
    `;
  }

  function ensurePanel() {
    const panel = document.getElementById("ask-bar-panel");
    if (panel && !panelWired) {
      panelWired = true;
      panel.addEventListener("click", (event) => {
        if (event.target.closest(".ask-bar__header")) {
          collapsed = !collapsed;
          saveCollapsed();
          renderPanel();
        }
      });
      panel.addEventListener("submit", (event) => {
        const form = event.target.closest("[data-ask-form]");
        if (!form) return;
        event.preventDefault();
        const input = form.querySelector("[data-ask-input]");
        if (!input) return;
        const question = input.value;
        input.value = "";
        void askQuestion(question, {});
      });
      panel.addEventListener("click", (event) => {
        const briefingButton = event.target.closest("[data-ask-briefing]");
        if (briefingButton) {
          event.stopPropagation();
          askTodaysBriefing();
        }
      });
      panel.addEventListener("click", (event) => {
        const clearButton = event.target.closest("[data-ask-clear]");
        if (clearButton) {
          event.stopPropagation();
          clearTranscript();
        }
      });
    }
    return panel;
  }

  function clearTranscript() {
    // Requested live 2026-08-04: the panel's history is persisted in
    // localStorage (loadTranscript/saveTranscript) and never re-fetched on
    // its own, so old questions/answers -- including ones asked before a
    // fix landed -- sit there indefinitely, indistinguishable from a
    // current, live answer. This is the only way to clear it.
    transcript = [];
    saveTranscript();
    renderPanel();
  }

  function renderPanel() {
    const panel = ensurePanel();
    if (!panel) return;
    panel.setAttribute("data-collapsed", collapsed ? "true" : "false");
    const statusText = document.getElementById("ask-bar-status")?.textContent || "";
    panel.innerHTML = `
      <div class="ask-bar__header">
        <div class="ask-bar__title">Ask the Syndicate${transcript.length ? ` <span class="ask-bar__count">${transcript.length}</span>` : ""}</div>
        <div class="ask-bar__toggle">▾</div>
      </div>
      <div class="ask-bar__body">
        <form data-ask-form class="ask-bar__form">
          <input type="text" data-ask-input class="ask-bar__input" placeholder="Ask about today's board…" autocomplete="off" />
          <button type="submit" class="ask-bar__send">Ask</button>
        </form>
        <div class="ask-bar__actions">
          <button type="button" class="ask-bar__briefing-btn" data-ask-briefing="1">📋 Today's briefing</button>
          ${transcript.length ? `<button type="button" class="ask-bar__clear-btn" data-ask-clear="1" title="Clear conversation history">🗑️ Clear</button>` : ""}
          <span id="ask-bar-status" class="ask-bar__status" role="status" aria-live="polite">${escapeHtml(statusText)}</span>
        </div>
        <div class="ask-bar__transcript">
          ${transcript.length ? transcript.map(renderEntry).join("") : `<div class="ask-bar__empty">Ask a question, or tap ☰ Ask on any pick.</div>`}
        </div>
      </div>
    `;
  }

  function init() {
    renderPanel();
  }

  return { init, wireAskButtons, askTodaysBriefing };
})();
