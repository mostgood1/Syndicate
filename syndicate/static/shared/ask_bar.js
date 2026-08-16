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

  // data-syndicate-selection is sometimes just the pick direction with no
  // player/team in it at all (e.g. "Under", confirmed live 2026-08-04 on
  // several real cards) -- selection alone was silently ambiguous there,
  // producing "What's the case for and against Under?", which cannot
  // possibly match one specific board recommendation. data-syndicate-name
  // (the card's own title, e.g. "Manny Machado") is always the specific
  // part; combine the two whenever selection doesn't already include it,
  // rather than treating selection as unconditionally more specific.
  function askSubjectFromContext(context) {
    const name = safeText(context.name, "");
    const selection = safeText(context.selection, "");
    if (name && selection && !selection.toLowerCase().includes(name.toLowerCase())) {
      return `${name} ${selection}`;
    }
    return selection || name || safeText(context.matchup, "") || "this pick";
  }

  function wireAskButtons(container) {
    const scope = container || document;
    scope.querySelectorAll("[data-ask-action='ask-pick']").forEach((button) => {
      button.addEventListener("click", (event) => {
        event.preventDefault();
        const card = button.closest("[data-syndicate-name]");
        if (!card) return;
        const context = contextFromCard(card);
        const subject = askSubjectFromContext(context);
        void askQuestion(`What's the case for and against ${subject}?`, context);
      });
    });
  }

  function finiteNumber(value) {
    return typeof value === "number" && isFinite(value) ? value : null;
  }

  function formatOdds(price) {
    const n = finiteNumber(price);
    if (n === null) return "";
    return n > 0 ? `+${n}` : String(n);
  }

  // What you are betting and at what price. `selection` now carries the side
  // and the number (server-side `_bet_label`), so this line is the market, the
  // price and the book -- the part that makes a row placeable rather than
  // merely nameable. Reported 2026-08-16: a prop answer named neither the prop
  // nor the side, and no answer has ever shown a price or a book.
  function renderPickFacts(row) {
    const bits = [];
    const market = safeText(row.market_label || row.market, "");
    if (market) bits.push(market);
    const odds = formatOdds(row.price);
    const book = safeText(row.bookmaker, "");
    if (odds && book) bits.push(`${odds} at ${book}`);
    else if (odds) bits.push(odds);
    const books = finiteNumber(row.books_quoting);
    if (books) bits.push(`${books} bks`);
    const matchup = safeText(row.matchup, "");
    if (matchup && !safeText(row.selection, "").includes(matchup)) bits.push(matchup);
    return bits.join(" · ");
  }

  // `edge` is a PERCENT on both schemas from 2026-08-16. It used to be a
  // FRACTION on bet_analysis and a PERCENT on market_summary, and this line
  // multiplied by 100 unconditionally -- which was right for one schema and
  // silently wrong for the other. Prefer the explicitly-united `edge_pct`.
  function renderPickNumbers(row) {
    const bits = [];
    const projected = finiteNumber(row.projected);
    const model = finiteNumber(row.model_probability);
    const market = finiteNumber(row.market_probability);
    const edge = finiteNumber(row.edge_pct === undefined || row.edge_pct === null ? row.edge : row.edge_pct);
    if (projected !== null) bits.push(`Sim ${projected}`);
    if (model !== null) bits.push(`Model ${model.toFixed(1)}%`);
    if (market !== null) bits.push(`Market ${market.toFixed(1)}%`);
    if (edge !== null) bits.push(`Edge ${edge.toFixed(1)}%`);
    return bits.join(" · ");
  }

  // INLINE STYLES, DELIBERATELY, AND THEY SHOULD NOT STAY THAT WAY.
  // These belong next to `.ask-bar__answer-pick-*` in
  // `syndicate/static/shared/board_cards.css`, which is claimed by the OPEN
  // lane `layer2-board-quality`. Editing across lanes is forbidden, and the
  // evidence table genuinely needs `overflow-x` or a 7-column starter
  // projection breaks the sidebar layout -- so shipping unstyled was not an
  // option either. The class names are already correct; move the declarations
  // into the stylesheet and delete this block when that lane closes.
  const STYLE = {
    numbers: "font-size:11px;font-variant-numeric:tabular-nums;",
    flag: "align-self:flex-start;margin-top:3px;padding:1px 6px;border-radius:999px;"
      + "border:1px solid rgba(255,196,120,0.45);background:rgba(255,176,80,0.12);"
      + "color:#ffd9a8;font-size:10px;letter-spacing:0.02em;text-transform:uppercase;",
    evidence: "margin-top:8px;display:flex;flex-direction:column;gap:6px;",
    table: "overflow-x:auto;",
    tableEl: "border-collapse:collapse;font-size:10.5px;white-space:nowrap;",
    tableTitle: "font-size:10.5px;text-transform:uppercase;letter-spacing:0.04em;opacity:0.65;margin-bottom:2px;",
    th: "padding:2px 6px 2px 0;text-align:left;font-weight:600;opacity:0.7;",
    td: "padding:2px 6px 2px 0;text-align:left;font-variant-numeric:tabular-nums;opacity:0.85;",
  };

  function renderPickRow(row) {
    const name = safeText(row.selection || row.name, "Opportunity");
    const facts = renderPickFacts(row);
    const numbers = renderPickNumbers(row);
    const why = safeText(row.recommendation || row.why, "");
    // The single most useful thing an answer can say about a number it is
    // asking you to trust: 88 of 108 board rows say of themselves "model never
    // backtested -- projection is unvalidated". Suppressed when the generated
    // reason already says it, so it does not appear twice.
    const unvalidated = safeText(row.model_skill_status, "") === "unmeasured"
      && !why.toLowerCase().includes("backtested");
    return `
      <div class="ask-bar__answer-pick">
        <span class="ask-bar__answer-pick-name">${escapeHtml(name)}</span>
        ${facts ? `<span class="ask-bar__answer-pick-why">${escapeHtml(facts)}</span>` : ""}
        ${numbers ? `<span class="ask-bar__answer-pick-numbers" style="${STYLE.numbers}">${escapeHtml(numbers)}</span>` : ""}
        ${why ? `<div class="ask-bar__answer-pick-detail">${escapeHtml(why)}</div>` : ""}
        ${unvalidated ? `<span class="ask-bar__answer-pick-flag" style="${STYLE.flag}">model unvalidated</span>` : ""}
      </div>`;
  }

  function renderEvidenceTable(table) {
    const cols = Array.isArray(table.columns) ? table.columns : [];
    const rows = Array.isArray(table.rows) ? table.rows : [];
    if (!rows.length) return "";
    const cell = (value) => `<td style="${STYLE.td}">${escapeHtml(String(value == null ? "—" : value))}</td>`;
    return `
      <div class="ask-bar__answer-table" style="${STYLE.table}">
        <div class="ask-bar__answer-table-title" style="${STYLE.tableTitle}">${escapeHtml(safeText(table.title, "Evidence"))}</div>
        <table style="${STYLE.tableEl}">
          ${cols.length ? `<thead><tr>${cols.map((c) => `<th style="${STYLE.th}">${escapeHtml(String(c))}</th>`).join("")}</tr></thead>` : ""}
          <tbody>
            ${rows.slice(0, 6).map((r) => `<tr>${(Array.isArray(r) ? r : [r]).map(cell).join("")}</tr>`).join("")}
          </tbody>
        </table>
      </div>`;
  }

  // The sim and advanced evidence has been in every response all along:
  // `collect_focused_evidence` builds it server-side and the standalone
  // /syndicate page renders it. This panel never read `response.visuals` at
  // all -- a deliberate scoping decision when it was a sidebar afterthought,
  // and wrong now that it is the surface people use. Measured 2026-08-16: an
  // MLB prop question returned 7 tables and 3 charts of real simulation output
  // (starter sim projections, last 5 starts, opposing-lineup Statcast, a full
  // simulated-strikeout distribution) and the panel showed a name and one
  // number. Two tables inline, everything else named, so a sidebar stays one.
  function renderEvidence(response) {
    const visuals = response && typeof response.visuals === "object" ? response.visuals : null;
    if (!visuals) return "";
    const tables = (Array.isArray(visuals.tables) ? visuals.tables : [])
      .filter((t) => t && Array.isArray(t.rows) && t.rows.length);
    const charts = Array.isArray(visuals.charts) ? visuals.charts : [];
    if (!tables.length && !charts.length) return "";
    const more = tables.slice(2).map((t) => safeText(t.title, ""))
      .concat(charts.map((c) => safeText(c && c.title, "")))
      .filter(Boolean);
    return `
      <div class="ask-bar__answer-evidence" style="${STYLE.evidence}">
        ${tables.slice(0, 2).map(renderEvidenceTable).join("")}
        ${more.length ? `<div class="ask-bar__answer-pick-why">Also computed: ${escapeHtml(more.join(" · "))}</div>` : ""}
      </div>`;
  }

  // Compact rendering of the same `briefing` block syndicate.html's
  // renderBriefing() draws in full.
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
            ${picks.map((pick) => `
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
    // bet_analysis is ONE named bet, so it renders as a pick row rather than
    // as loose prose. Checked BEFORE the opportunities branch: `recommendation`
    // is now populated for every layer2-sourced pick (the server generates the
    // sentence -- `_reason_sentences`), so `fallbackText` is non-empty and this
    // branch, when it sat last, became unreachable for exactly the answers it
    // was written to serve.
    if (structured && structured.schema_type === "bet_analysis" && structured.selection) {
      return `<div class="ask-bar__answer-picks">${renderPickRow(structured)}</div>`;
    }
    if (fallbackText || opportunities.length) {
      return `
        ${fallbackText ? `<div class="ask-bar__answer-narrative">${escapeHtml(fallbackText).replace(/\n+/g, "<br><br>")}</div>` : ""}
        ${opportunities.length ? `
          <div class="ask-bar__answer-picks">
            ${/* Was slice(0, 3) while the server's own sentence said "Showing
                  the top 5" and returned 5 -- reported 2026-08-16. The count in
                  the prose is generated from the rows the server sent, so the
                  renderer must not second-guess it. */""}
            ${opportunities.map((row) => renderPickRow(row || {})).join("")}
          </div>
        ` : ""}
      `;
    }
    // Any other schema that still named one bet (matchup_analysis with a
    // single edge, a steam-move alert) -- show the real numbers rather than a
    // dead end.
    if (structured && structured.selection) {
      return `<div class="ask-bar__answer-picks">${renderPickRow(structured)}</div>`;
    }
    return `<div class="ask-bar__answer-narrative ask-bar__answer-narrative--empty">No structured answer came back for this question -- try rephrasing it.</div>`;
  }

  function renderEntry(entry) {
    const contextBits = [entry.context && entry.context.selection, entry.context && entry.context.matchup].filter(Boolean);
    const response = entry.response || {};
    return `
      <div class="ask-bar__entry">
        <div class="ask-bar__question">${escapeHtml(entry.question)}${contextBits.length ? ` <span class="ask-bar__question-context">(${escapeHtml(contextBits.join(" · "))})</span>` : ""}</div>
        <div class="ask-bar__answer">
          ${entry.error
            ? `<div class="ask-bar__answer-error">${escapeHtml(entry.error)}</div>`
            : renderBriefingCompact(response) + renderEvidence(response)}
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
