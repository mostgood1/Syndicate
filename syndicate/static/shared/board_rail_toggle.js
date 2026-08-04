(function () {
  "use strict";

  // .board-rail (bet slip / watchlist / portfolio / parlays) is
  // collapsible at every width via data-rail-state (board_cards.css):
  // under 1080px it docks to the bottom of the viewport, collapsed by
  // default to this handle's 48px and expanding to a 62vh scrollable
  // sheet only while tapped open; at/above 1080px it stays a normal
  // static column, expanded by default (existing behavior), collapsible
  // down to just the handle on demand. Root-caused 2026-08-03 (mobile)
  // and 2026-08-04 (desktop): neither collapse was ever wired up, so the
  // rail rendered permanently expanded on every width -- covering the
  // board on phones, and just taking up the full column on desktop with
  // no way to shrink it. A no-op on any page without a .board-rail.
  var MOBILE_QUERY = "(max-width: 1080px)";
  var COLLAPSED_LABEL = "Bet slip, watchlist & more ▴";
  var EXPANDED_LABEL = "Hide bet slip & more ▾";

  function defaultState() {
    return window.matchMedia(MOBILE_QUERY).matches ? "collapsed" : "expanded";
  }

  function initBoardRailToggle() {
    var rail = document.querySelector(".board-rail");
    if (!rail || rail.querySelector(".board-rail-handle")) {
      return;
    }
    rail.setAttribute("data-rail-state", defaultState());

    var handle = document.createElement("button");
    handle.type = "button";
    handle.className = "board-rail-handle";
    handle.addEventListener("click", function () {
      var expanded = rail.getAttribute("data-rail-state") === "expanded";
      var nextExpanded = !expanded;
      rail.setAttribute("data-rail-state", nextExpanded ? "expanded" : "collapsed");
      handle.setAttribute("aria-expanded", nextExpanded ? "true" : "false");
      handle.textContent = nextExpanded ? EXPANDED_LABEL : COLLAPSED_LABEL;
    });
    var initiallyExpanded = rail.getAttribute("data-rail-state") === "expanded";
    handle.setAttribute("aria-expanded", initiallyExpanded ? "true" : "false");
    handle.textContent = initiallyExpanded ? EXPANDED_LABEL : COLLAPSED_LABEL;
    rail.insertBefore(handle, rail.firstChild);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initBoardRailToggle);
  } else {
    initBoardRailToggle();
  }
})();
