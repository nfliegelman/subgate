/* subgate network-level block page. No bypass button by design. */
"use strict";
document.getElementById("back").addEventListener("click", function () {
  if (history.length > 1) { history.back(); }
  else { location.href = "https://www.reddit.com/"; }
});
