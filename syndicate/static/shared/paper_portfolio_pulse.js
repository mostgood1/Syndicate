// Paper-portfolio live pulse. The plan artifact and the execution ledger are
// both rewritten by the refresh worker every time the Layer 2 shortlist
// rebuilds (a few minutes), so a server-rendered snapshot goes stale between
// one glance and the next -- which is exactly what "track it in real time"
// asks not to happen.
//
// Same contract as shared/portfolio_pulse.js: every render function below
// reproduces one block of portfolio_paper.html's Jinja exactly (same number
// formatting, same conditional show/hide, same empty-state wording) so a
// live-refreshed page is indistinguishable from a freshly server-rendered
// one. If you change a format string in one, change it in the other.
window.SyndicatePaperPortfolioPulse = (function () {
  "use strict";

  function escapeHtml(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, (char) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[char] || char));
  }

  function isNum(value) {
    return typeof value === "number" && Number.isFinite(value);
  }

  function usd(value) {
    return `$${(isNum(value) ? value : 0).toFixed(2)}`;
  }

  // Mirrors Jinja "%.2f"|format(value * 100) + "%".
  function pct2(value) {
    return `${((isNum(value) ? value : 0) * 100).toFixed(2)}%`;
  }

  // Mirrors Jinja "%.0f"|format(value * 100) + "%", or an em dash for null.
  function pct0OrDash(value) {
    return isNum(value) ? `${Math.round(value * 100)}%` : "—";
  }

  // Mirrors Jinja "%+.1f"|format(value * 100) + "%", or an em dash for null.
  function pctSigned1OrDash(value) {
    if (!isNum(value)) return "—";
    const scaled = value * 100;
    return `${scaled >= 0 ? "+" : ""}${scaled.toFixed(1)}%`;
  }

  // Mirrors Jinja "%+.2f"|format(value), or an em dash for null.
  function signed2OrDash(value) {
    if (!isNum(value)) return "—";
    return `${value >= 0 ? "+" : ""}${value.toFixed(2)}`;
  }

  // Mirrors Jinja "%+d"|format(value|int) -- American odds always carry a sign.
  function americanOrDash(value) {
    if (!isNum(value)) return "—";
    const whole = Math.trunc(value);
    return `${whole >= 0 ? "+" : ""}${whole}`;
  }

  function plural(count, singular, pluralForm) {
    return count === 1 ? singular : pluralForm;
  }

  function signClass(value) {
    if (!isNum(value) || value === 0) return "";
    return value > 0 ? " pos" : " neg";
  }

  function renderBanner(data) {
    const mode = String(data.execution_mode || "paper");
    const banner = document.getElementById("paper-banner");
    const badge = document.getElementById("paper-mode-badge");
    const text = document.getElementById("paper-banner-text");
    if (banner) banner.setAttribute("data-mode", mode);
    if (badge) {
      badge.textContent = mode.toUpperCase();
      badge.className = `paper-badge${mode !== "paper" ? " paper-badge--live" : ""}`;
    }
    if (text) {
      text.textContent = mode === "paper"
        ? "Simulated fills only. No money moves, no book is contacted, nothing here is a real wager."
        : "LIVE execution mode is selected. Orders on this page correspond to real submissions.";
    }
    // Say WHOSE flag state this is. Reading web's own env on a page showing the
    // worker's output is how it came to report "off" beside filled orders.
    const commitLabel = document.querySelector('[data-flag-label="commit"]');
    if (commitLabel) {
      commitLabel.textContent = data.job_state_source === "worker" ? "Commit job" : "Commit job (web env)";
    }
    const commit = document.getElementById("paper-flag-commit");
    if (commit) {
      commit.textContent = data.commit_enabled ? "on" : "off";
      commit.className = `paper-flag__value ${data.commit_enabled ? "on" : "off"}`;
    }
    const exec = document.getElementById("paper-flag-exec");
    if (exec) {
      exec.textContent = data.execution_enabled ? "on" : "off";
      exec.className = `paper-flag__value ${data.execution_enabled ? "on" : "off"}`;
    }
    const generated = document.getElementById("paper-generated-at");
    if (generated) generated.textContent = data.generated_at || "—";
  }

  function renderLedgerError(data) {
    const box = document.getElementById("paper-ledger-error");
    const text = document.getElementById("paper-ledger-error-text");
    if (!box) return;
    box.hidden = !data.ledger_error;
    if (text) text.textContent = data.ledger_error || "";
  }

  // Mirrors portfolio_paper.html's CLV tile exactly, including the precedence
  // of its three meta lines: a key mismatch is reported ahead of a missing
  // opening, because a derivation that drifted makes every CLV number suspect
  // while a missing opening only loses that one row.
  function movementTile(marks) {
    if (!marks.marked) {
      return { label: "Line movement", value: "—", meta: "no order re-priced yet" };
    }
    const avg = marks.avg_clv_pct;
    return {
      label: "Line movement",
      value: isNum(avg) ? `${signed2OrDash(avg)} pts` : "—",
      meta: `${marks.moved_toward || 0} toward · ${marks.moved_against || 0} against, of ${marks.marked} marked`,
      valueClass: isNum(avg) && avg > 0 ? " mark-pos" : (isNum(avg) && avg < 0 ? " mark-neg" : ""),
    };
  }

  function clvTile(clv) {
    if (clv.positions === null || clv.positions === undefined) {
      return { label: "CLV openings", value: "—", meta: "plan predates the join" };
    }
    const matched = clv.matched || 0;
    const positions = clv.positions || 0;
    let meta = "joined to an opening price";
    if ((clv.derivation_disagrees || 0) > 0) {
      meta = `${clv.derivation_disagrees} key mismatch — CLV unsafe`;
    } else if ((clv.no_key_match || 0) > 0) {
      meta = `${clv.no_key_match} with no recorded opening`;
    }
    return {
      label: "CLV openings",
      value: `${matched}/${positions}`,
      meta,
      valueClass: matched < positions ? " warn" : "",
    };
  }

  function renderTiles(data) {
    const container = document.getElementById("paper-tiles");
    if (!container) return;
    const totals = data.totals || {};
    const ledger = data.ledger || {};
    const byStatus = ledger.by_status || {};
    const coverage = data.sim_coverage || {};
    const simSides = totals.positions_where_sim_picked_the_side || 0;
    const unreconciled = ledger.unreconciled || 0;
    const tiles = [
      { label: "Bankroll", value: usd(data.bankroll_units), meta: "editable on /portfolio" },
      { label: "Positions", value: String(totals.positions || 0), meta: `committed for ${data.date || "—"}` },
      { label: "Staked", value: usd(totals.staked_dollars), meta: `${pct2(totals.staked_fraction)} of bankroll` },
      {
        label: "Sim share of stake",
        value: pctSigned1OrDash(totals.sim_share_of_staked),
        meta: `${simSides} ${plural(simSides, "side", "sides")} picked by sim`,
      },
      {
        label: "Orders",
        value: String(ledger.orders || 0),
        meta: `${byStatus.filled || 0} filled · ${byStatus.rejected || 0} rejected`,
      },
      {
        label: "Unreconciled",
        value: String(unreconciled),
        meta: "submitted, never completed",
        valueClass: unreconciled > 0 ? " warn" : "",
      },
      { label: "Filled stake", value: usd(ledger.filled_stake_dollars), meta: "at simulated fill price" },
      movementTile(data.live_marks || {}),
      clvTile(data.clv_join || {}),
      {
        label: "Sim coverage",
        value: pct0OrDash(coverage.share_with_sim_edge),
        meta: `${coverage.rows_with_sim_edge || 0}/${coverage.rows_in || 0} candidates had a sim edge`,
      },
    ];
    container.innerHTML = tiles.map((tile) => `
      <div class="paper-tile">
        <div class="paper-tile__label">${escapeHtml(tile.label)}</div>
        <div class="paper-tile__value${tile.valueClass || ""}">${escapeHtml(tile.value)}</div>
        <div class="paper-tile__meta">${escapeHtml(tile.meta)}</div>
      </div>
    `).join("");
  }

  // The four states are DISTINCT on purpose -- job off, no artifact, an empty
  // plan, and a plan whose orders were never placed have four different
  // fixes, and one shared "nothing here" would hide which one you are in.
  function emptyStateHtml(data) {
    if (!data.commit_enabled) {
      return `<div class="paper-empty">
        The portfolio commit job is <strong>off</strong>. Nothing is being sized, so there is no plan to show.
        Set <code>SYNDICATE_PORTFOLIO_COMMIT_ENABLED=1</code> on the refresh worker.
      </div>`;
    }
    if (!data.plan_present) {
      return `<div class="paper-empty">
        No plan artifact for ${escapeHtml(data.date || "this date")} yet. The plan is written by the refresh worker right after the
        Layer&nbsp;2 shortlist rebuilds — if the shortlist has not run today, this is expected.
      </div>`;
    }
    return `<div class="paper-empty">
      The plan ran and committed <strong>zero</strong> positions. That is a decision, not a gap — see the refusal
      counts below for which gate each candidate hit.
    </div>`;
  }

  // Mirrors portfolio_paper.html's `mark_cell` macro exactly. Movement is always
  // probability points from clv_pct_from_prices -- American odds are not linear,
  // so a raw price difference would be wrong in both directions at once.
  function markCell(mark) {
    if (!mark) return `<span class="paper-table__sub">—</span>`;
    if (mark.reason === "marked") {
      const cls = isNum(mark.clv_pct) && mark.clv_pct > 0
        ? "mark-pos"
        : (isNum(mark.clv_pct) && mark.clv_pct < 0 ? "mark-neg" : "");
      const move = isNum(mark.clv_pct) ? `${signed2OrDash(mark.clv_pct)} pts` : "no move";
      return `<span class="${cls}">${americanOrDash(mark.current_price)}</span>
        <span class="paper-table__sub">${move}</span>`;
    }
    if (mark.reason === "book_no_longer_quoting") {
      return `<span class="paper-table__sub">${escapeHtml(mark.taken_book || "our book")} pulled</span>`;
    }
    if (mark.reason === "market_not_on_board") {
      return `<span class="paper-table__sub">off board</span>`;
    }
    if (mark.reason === "unkeyable") {
      return `<span class="paper-table__sub">not re-priceable</span>`;
    }
    return `<span class="paper-table__sub">${escapeHtml(mark.reason || "")}</span>`;
  }

  // The orphan table's own selection cell. Same shape as the positions table's,
  // built from the LEDGER's fields rather than the plan's -- an orphan has no
  // position left to read from, which is the whole reason the ledger carries
  // player_name, line and the matchup itself.
  function orderSelectionCell(order) {
    let sub = escapeHtml(order.market || "—");
    if (order.line !== null && order.line !== undefined) sub += ` ${escapeHtml(String(order.line))}`;
    if (order.player_name) sub += `· ${escapeHtml(order.side || "")}`;
    if (order.away_team || order.home_team) {
      sub += `· ${escapeHtml(order.away_team || "?")} @ ${escapeHtml(order.home_team || "?")}`;
    }
    return `${escapeHtml(order.player_name || order.side || "—")}
      <span class="paper-table__sub">${sub}</span>`;
  }

  function selectionCell(row) {
    const parts = [];
    parts.push(escapeHtml(row.market || "—"));
    if (row.line !== null && row.line !== undefined) parts.push(escapeHtml(String(row.line)));
    let sub = parts.join(" ");
    if (row.player_name) sub += `· ${escapeHtml(row.side || "")}`;
    if (row.away_team || row.home_team) {
      sub += `· ${escapeHtml(row.away_team || "?")} @ ${escapeHtml(row.home_team || "?")}`;
    }
    return `
      ${escapeHtml(row.player_name || row.side || "—")}
      <span class="paper-table__sub">${sub}</span>
    `;
  }

  function fillCell(order) {
    if (order && isNum(order.fill_price)) {
      return `${americanOrDash(order.fill_price)}
        <span class="paper-table__sub">${usd(order.fill_stake_dollars)}</span>`;
    }
    if (order && order.error) {
      return `<span class="paper-table__sub">${escapeHtml(order.error)}</span>`;
    }
    return "—";
  }

  function renderPositions(data) {
    const wrap = document.getElementById("paper-positions");
    if (!wrap) return;
    const rows = Array.isArray(data.rows) ? data.rows : [];
    if (!rows.length) {
      wrap.innerHTML = emptyStateHtml(data);
      return;
    }
    const body = rows.map((row) => {
      const attribution = row.attribution || {};
      const order = row.order;
      const status = order ? String(order.status || "") : "";
      const orderCell = order
        ? `<span class="paper-pill paper-pill--${escapeHtml(status)}">${escapeHtml(status)}</span>`
        : `<span class="paper-pill paper-pill--none">not placed</span>`;
      return `
        <tr>
          <td class="primary">${escapeHtml(String(row.sport || "—").toUpperCase())}</td>
          <td class="primary">${selectionCell(row)}</td>
          <td>${escapeHtml(row.book || "—")}</td>
          <td>${americanOrDash(row.price)}</td>
          <td class="primary">${usd(row.stake_dollars)}</td>
          <td>${pct2(row.stake_fraction)}</td>
          <td class="${signClass(row.ev_pct).trim()}">${signed2OrDash(row.ev_pct)}</td>
          <td class="${signClass(row.model_edge_pct).trim()}">${signed2OrDash(row.model_edge_pct)}</td>
          <td>${isNum(row.board_score) ? row.board_score.toFixed(2) : "—"}</td>
          <td class="${signClass(attribution.stake_dollars_sim_delta).trim()}">${signed2OrDash(attribution.stake_dollars_sim_delta)}</td>
          <td>${escapeHtml(attribution.side_picked_by || "—")}</td>
          <td>${orderCell}</td>
          <td>${fillCell(order)}</td>
          <td>${markCell(row.mark)}</td>
        </tr>
      `;
    }).join("");
    wrap.innerHTML = `
      <div class="paper-table-wrap">
        <table class="paper-table">
          <thead>
            <tr>
              <th>Sport</th><th>Selection</th><th>Book</th><th>Price</th><th>Stake</th><th>% BR</th>
              <th>EV%</th><th>Sim edge</th><th>Score</th><th>Sim $</th><th>Side by</th><th>Order</th><th>Fill</th><th>Now</th>
            </tr>
          </thead>
          <tbody>${body}</tbody>
        </table>
      </div>
    `;
  }

  function renderRefusals(data) {
    const section = document.getElementById("paper-refusals-section");
    const chips = document.getElementById("paper-refusals");
    if (!section || !chips) return;
    const refusals = data.refusals && typeof data.refusals === "object" ? data.refusals : {};
    const entries = Object.keys(refusals);
    section.hidden = entries.length === 0;
    if (!entries.length) return;
    chips.innerHTML = entries.map((reason) => `
      <span class="paper-chip">${escapeHtml(reason)} <strong>${escapeHtml(String(refusals[reason]))}</strong></span>
    `).join("");
  }

  function renderOrphans(data) {
    const section = document.getElementById("paper-orphans-section");
    const body = document.getElementById("paper-orphans");
    if (!section || !body) return;
    const orders = Array.isArray(data.orphan_orders) ? data.orphan_orders : [];
    section.hidden = orders.length === 0;
    if (!orders.length) return;
    body.innerHTML = orders.map((order) => `
      <tr>
        <td>${escapeHtml(order.submitted_at || "—")}</td>
        <td class="primary">${escapeHtml(String(order.sport || "—").toUpperCase())}</td>
        <td class="primary">${orderSelectionCell(order)}</td>
        <td>${escapeHtml(order.book || "—")}</td>
        <td>${americanOrDash(order.requested_price)}</td>
        <td>${usd(order.requested_stake_dollars)}</td>
        <td><span class="paper-pill paper-pill--${escapeHtml(String(order.status || ""))}">${escapeHtml(order.status || "")}</span></td>
        <td>${markCell(order.mark)}</td>
      </tr>
    `).join("");
  }

  // Mirrors portfolio_paper.html's paper2 section. Only the tiles and the
  // empty-state are re-rendered live; the positions table is server-rendered
  // and changes at most once per board build, which the pulse already reloads
  // the rest of the page against.
  function renderPaper2(data) {
    const section = document.getElementById("paper2-section");
    if (!section) return;
    const p2 = data.paper2 || {};
    section.hidden = !p2.venue;
    if (!p2.venue) return;
    const tiles = section.querySelector(".paper-tiles");
    if (!tiles || !p2.plan_present) return;
    const totals = data.totals || {};
    const quoted = (p2.rows_in || 0) + (p2.venue_not_quoting || 0);
    const spec = [
      {
        label: `${String(p2.venue).toUpperCase()} coverage`,
        value: pct0OrDash(p2.coverage),
        meta: `${p2.rows_in || 0} of ${quoted} candidates quoted`,
        valueClass: isNum(p2.coverage) && p2.coverage < 0.25 ? " warn" : "",
      },
      {
        label: "Positions",
        value: String(p2.positions || 0),
        meta: `vs ${totals.positions || 0} unrestricted`,
      },
      {
        label: "Staked",
        value: usd(p2.staked_dollars),
        meta: `vs ${usd(totals.staked_dollars)} unrestricted`,
      },
      {
        label: "Sim share of stake",
        value: pctSigned1OrDash(p2.sim_share_of_staked),
        meta: `vs ${pctSigned1OrDash(totals.sim_share_of_staked)} unrestricted`,
      },
    ];
    tiles.innerHTML = spec.map((tile) => `
      <div class="paper-tile">
        <div class="paper-tile__label">${escapeHtml(tile.label)}</div>
        <div class="paper-tile__value${tile.valueClass || ""}">${escapeHtml(tile.value)}</div>
        <div class="paper-tile__meta">${escapeHtml(tile.meta)}</div>
      </div>
    `).join("");
  }

  function renderAll(data) {
    renderBanner(data);
    renderLedgerError(data);
    renderTiles(data);
    renderPositions(data);
    renderRefusals(data);
    renderOrphans(data);
    renderPaper2(data);
  }

  let lastSuccessAt = null;
  let tickerHandle = null;
  let endpoint = "/api/portfolio/paper";

  function formatRelativeTime(ms) {
    const seconds = Math.max(0, Math.round(ms / 1000));
    if (seconds < 5) return "just now";
    if (seconds < 60) return `${seconds}s ago`;
    const minutes = Math.round(seconds / 60);
    if (minutes < 60) return `${minutes}m ago`;
    const hours = Math.round(minutes / 60);
    return `${hours}h ago`;
  }

  function setPulseState(state, text) {
    const chip = document.getElementById("paper-pulse");
    const label = document.getElementById("paper-pulse-text");
    if (chip) chip.setAttribute("data-state", state);
    if (label) label.textContent = text;
  }

  function updatePulseLabel() {
    if (lastSuccessAt === null) return;
    setPulseState("ok", `Updated ${formatRelativeTime(Date.now() - lastSuccessAt)}`);
  }

  async function fetchAndRender() {
    try {
      const response = await fetch(endpoint, { headers: { Accept: "application/json" } });
      if (!response.ok) throw new Error(`paper portfolio fetch failed: ${response.status}`);
      const data = await response.json();
      if (!data || data.ok === false) throw new Error("paper portfolio response not ok");
      renderAll(data);
      lastSuccessAt = Date.now();
      updatePulseLabel();
    } catch (error) {
      // Degrade honestly: keep whatever was last rendered, but say the page is
      // stale. A silently frozen money page is worse than an empty one.
      if (lastSuccessAt === null) {
        setPulseState("error", "Live updates unavailable");
      } else {
        setPulseState("error", `Stale — last updated ${formatRelativeTime(Date.now() - lastSuccessAt)}`);
      }
    }
  }

  function init(selectedDate) {
    if (tickerHandle) return;
    // Pin the polled date to the one the server rendered. Without this a page
    // opened with ?date=<yesterday> would silently start showing today after
    // the first tick.
    if (selectedDate) endpoint = `/api/portfolio/paper?date=${encodeURIComponent(selectedDate)}`;
    setPulseState("ok", "Live");
    tickerHandle = window.setInterval(updatePulseLabel, 15000);
    void fetchAndRender();
    window.SyndicatePolling.startFromPolicy(
      {},
      { onTick: fetchAndRender },
      { enabled: true, intervalMs: 45000, refreshOnVisible: true, refreshOnFocus: true, skipWhenHidden: true, preventOverlap: true }
    );
  }

  return { init, fetchAndRender, renderAll };
})();
