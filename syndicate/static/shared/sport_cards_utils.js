// Shared pure-utility functions extracted 2026-08-03 (Phase 3) from
// nba/cards_source.js and wnba/cards-parity.js -- the first real cut of
// "card client unification". Those two files are ~6,500 lines each and were
// forked wholesale (86% line-identical at fork time), but 90 days of
// independent development since then means 133 of 134 diff hunks between
// them are now genuine feature drift, not just copy-paste noise -- a real
// merge of the two boards is a much bigger project than "extract the common
// 85%". These 12 functions are the confirmed-safe subset: verified
// byte-identical between both files (zero diff-hunk overlap, then a direct
// line-range comparison) AND fully self-contained -- no reference to either
// file's closure-scoped state (the `state` object, cached DOM elements,
// etc.), only their own parameters and real JS globals. Extracting anything
// beyond this list requires reconciling the two files' actual behavioral
// differences first, not just moving code.
window.SyndicateCardsUtils = (function () {
  "use strict";

  function escapeHtml(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function extractApiErrorText(text, fallbackMessage) {
    const raw = String(text || "").trim();
    if (!raw) {
      return fallbackMessage;
    }
    if (raw.startsWith("<")) {
      return `${fallbackMessage} Server returned HTML instead of JSON.`;
    }
    if (raw.startsWith("{") || raw.startsWith("[")) {
      return fallbackMessage;
    }
    return raw.slice(0, 240);
  }

  function waitFor(ms) {
    return new Promise((resolve) => window.setTimeout(resolve, ms));
  }

  function viewportMode() {
    const width = Math.max(window.innerWidth || 0, document.documentElement?.clientWidth || 0);
    if (width <= 767) return "phone";
    if (width <= 1180) return "tablet";
    return "desktop";
  }

  function clampNumber(value, min, max) {
    return Math.min(max, Math.max(min, value));
  }

  function titleCase(value) {
    const raw = String(value || "").trim();
    if (!raw) {
      return "";
    }
    return raw
      .split(/[_\s]+/)
      .map((part) => (part ? part.charAt(0).toUpperCase() + part.slice(1).toLowerCase() : ""))
      .join(" ");
  }

  function normalizeLogoTri(tri) {
    const raw = String(tri || "").trim().toUpperCase();
    if (!raw) {
      return "";
    }
    return {
      BRO: "BKN",
      CHO: "CHA",
      GOL: "GSW",
      NJN: "BKN",
      NOH: "NOP",
      NOK: "NOP",
      PHO: "PHX",
      SAN: "SAS",
      UTH: "UTA",
    }[raw] || raw;
  }

  function marketLabel(value) {
    const key = String(value || "").trim().toLowerCase();
    return {
      pts: "Points",
      reb: "Rebounds",
      ast: "Assists",
      threes: "3PM",
      stl: "Steals",
      blk: "Blocks",
      tov: "Turnovers",
      pra: "PRA",
      pr: "PR",
      pa: "PA",
      ra: "RA",
    }[key] || titleCase(key);
  }

  function safeArray(value) {
    return Array.isArray(value) ? value : [];
  }

  function safeObjectFromEntries(entries) {
    try {
      return Object.fromEntries(entries || []);
    } catch (_error) {
      return {};
    }
  }

  function fmtTime(value) {
    if (!value) {
      return "Time TBD";
    }
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
      return "Time TBD";
    }
    return new Intl.DateTimeFormat(undefined, {
      hour: "numeric",
      minute: "2-digit",
      month: "short",
      day: "numeric",
    }).format(date);
  }

  function cardId(game) {
    return String(game?.sim?.game_id || `${game?.away_tri || "AWAY"}@${game?.home_tri || "HOME"}`);
  }

  return {
    escapeHtml,
    extractApiErrorText,
    waitFor,
    viewportMode,
    clampNumber,
    titleCase,
    normalizeLogoTri,
    marketLabel,
    safeArray,
    safeObjectFromEntries,
    fmtTime,
    cardId,
  };
})();
