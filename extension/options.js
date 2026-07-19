/* subgate options page logic. */
"use strict";

var DEFAULTS = {
  listUrl: "https://raw.githubusercontent.com/OWNER/subgate/main/subgate_full.txt",
  allow: ["pornfree", "nofap"],
  verbose: true
};

function el(id) { return document.getElementById(id); }

function setStatus(text) { el("status").textContent = text; }

function paintStats() {
  chrome.runtime.sendMessage({ type: "stats" }, function (s) {
    if (chrome.runtime.lastError || !s) { return; }
    var when = s.listTs ? new Date(s.listTs).toLocaleString() : "never";
    setStatus(s.count + " communities on the list. Last updated: " + when);
  });
}

chrome.storage.local.get(DEFAULTS, function (d) {
  el("listUrl").value = d.listUrl;
  el("allow").value = (d.allow || []).join("\n");
  el("verbose").checked = !!d.verbose;
  paintStats();
});

el("save").addEventListener("click", function () {
  var allow = el("allow").value.split("\n")
    .map(function (s) { return s.trim().replace(/^r\//i, ""); })
    .filter(function (s) { return /^[A-Za-z0-9_]{2,21}$/.test(s); });
  chrome.storage.local.set({
    listUrl: el("listUrl").value.trim() || DEFAULTS.listUrl,
    allow: allow,
    verbose: el("verbose").checked
  }, function () {
    setStatus("Saved.");
    setTimeout(paintStats, 400);
  });
});

el("update").addEventListener("click", function () {
  setStatus("Updating...");
  chrome.runtime.sendMessage({ type: "refresh" }, function (res) {
    if (chrome.runtime.lastError || !res) { setStatus("Update failed."); return; }
    if (res.ok) { paintStats(); }
    else { setStatus("Update failed: " + (res.error || "unknown")); }
  });
});
