(function () {
  "use strict";

  // .board-rail (bet slip / watchlist / portfolio / parlays) docks to the
  // bottom of the viewport under 1080px (board_cards.css) -- collapsed by
  // default to this handle's 48px, expanding to a 62vh scrollable sheet
  // only while tapped open. Root-caused 2026-08-03: the collapse was never
  // wired up at all, so the rail rendered permanently expanded, fixed to
  // the bottom of every phone screen, covering the board underneath it.
  // No-op on desktop/tablet (.board-rail-handle stays display:none there)
  // and a no-op entirely on any page without a .board-rail.
  var COLLAPSED_LABEL = "Bet slip, watchlist & more ▴";
  var EXPANDED_LABEL = "Hide bet slip & more ▾";

  function initBoardRailToggle() {
    var rail = document.querySelector(".board-rail");
    if (!rail || rail.querySelector(".board-rail-handle")) {
      return;
    }
    var handle = document.createElement("button");
    handle.type = "button";
    handle.className = "board-rail-handle";
    handle.setAttribute("aria-expanded", "false");
    handle.textContent = COLLAPSED_LABEL;
    handle.addEventListener("click", function () {
      var expanded = rail.classList.toggle("is-expanded");
      handle.setAttribute("aria-expanded", expanded ? "true" : "false");
      handle.textContent = expanded ? EXPANDED_LABEL : COLLAPSED_LABEL;
    });
    rail.insertBefore(handle, rail.firstChild);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initBoardRailToggle);
  } else {
    initBoardRailToggle();
  }
})();
