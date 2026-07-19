// ==UserScript==
// @name         subgate
// @namespace    https://github.com/OWNER/subgate
// @version      0.3.0
// @description  Blocks 18+ subreddits on any navigation type. Verdicts come from your own subgate list and Reddit's flag via the Postpone mirror; page markup is only a tiebreaker.
// @match        *://*.reddit.com/*
// @run-at       document-start
// @grant        GM_xmlhttpRequest
// @grant        GM_getValue
// @grant        GM_setValue
// @connect      raw.githubusercontent.com
// @connect      api.postpone.app
// ==/UserScript==

/*
 * How a verdict is reached, in order:
 *
 *   1. ALLOW list below: always allowed.
 *   2. Your subgate list: the script downloads your published list once a
 *      day and keeps it locally, so 29k+ known 18+ communities are blocked
 *      instantly on ANY navigation: typed URL, ctrl+click, or in-app click.
 *   3. The mirror: names not on your list are checked against Reddit's own
 *      18+ flag through Postpone's public endpoint, then the answer is
 *      cached. This is what catches brand new communities.
 *   4. Page markup: only a tiebreaker when the network is unavailable,
 *      because Reddit changes markup too often to trust it as primary.
 *
 * The script finds your list by itself from the address you installed it
 * from. If you pasted it in manually instead, set LIST_URL_FALLBACK below.
 *
 * Every decision is logged to the console as "subgate: ..." with the layer
 * that decided it. That log line is what to send back when something is
 * wrong.
 */

(function () {
  "use strict";

  // Subreddits to never block, lowercase, no r/ prefix.
  var ALLOW = ["pornfree", "nofap"];

  // Only used when the script cannot work out where it was installed from.
  var LIST_URL_FALLBACK =
    "https://raw.githubusercontent.com/OWNER/subgate/main/subgate_full.txt";

  var VERBOSE = true;          // set false later to quiet the console
  var HIDE_MS = 3500;          // media stays hidden this long while checking
  var LIST_TTL_MS = 24 * 60 * 60 * 1000;      // re-download list daily
  var VERDICT_TTL_MS = 7 * 24 * 60 * 60 * 1000; // cache mirror answers 7 days

  var HIDE_STYLE_ID = "subgate-hide";
  var blocked = false;
  var currentPath = location.pathname;
  var listSet = null;          // Set of lowercase names, once loaded

  function log() {
    if (VERBOSE) {
      var args = ["subgate:"];
      for (var i = 0; i < arguments.length; i++) { args.push(arguments[i]); }
      console.log.apply(console, args);
    }
  }

  function gmGet(key, dflt) {
    try { return GM_getValue(key, dflt); } catch (e) {}
    try {
      var v = localStorage.getItem("subgate_" + key);
      return v === null ? dflt : v;
    } catch (e2) { return dflt; }
  }

  function gmSet(key, val) {
    try { GM_setValue(key, val); return; } catch (e) {}
    try { localStorage.setItem("subgate_" + key, val); } catch (e2) {}
  }

  function xhr(opts) {
    try { GM_xmlhttpRequest(opts); }
    catch (e) { if (opts.onerror) { opts.onerror(e); } }
  }

  function subredditFromPath(pathname) {
    var m = /^\/r\/([A-Za-z0-9_]{2,21})(\/|$)/.exec(pathname || "");
    return m ? m[1] : null;
  }

  function listUrl() {
    try {
      var dl = GM_info && GM_info.script &&
        (GM_info.script.downloadURL || GM_info.scriptSource || "");
      if (typeof dl === "string" && dl.indexOf("subgate.user.js") !== -1) {
        return dl.replace("subgate.user.js", "subgate_full.txt");
      }
    } catch (e) {}
    return LIST_URL_FALLBACK;
  }

  // ---------- media hiding while a verdict is pending ----------

  function hideMedia() {
    if (document.getElementById(HIDE_STYLE_ID)) { return; }
    var style = document.createElement("style");
    style.id = HIDE_STYLE_ID;
    style.textContent =
      "img, video, canvas, [style*='background-image'] " +
      "{ visibility: hidden !important; }";
    var root = document.head || document.documentElement;
    if (root) { root.appendChild(style); }
  }

  function revealMedia() {
    var style = document.getElementById(HIDE_STYLE_ID);
    if (style) { style.remove(); }
  }

  // ---------- the block page ----------

  function blockPage(reason, sub) {
    if (blocked) { return; }
    blocked = true;
    try { window.stop(); } catch (e) {}
    log("BLOCKED", sub || "?", "layer:", reason);
    var label = sub ? "r/" + sub : "this page";
    document.documentElement.innerHTML =
      "<head><title>Blocked by subgate</title></head>" +
      "<body style='margin:0;display:flex;align-items:center;" +
      "justify-content:center;height:100vh;font-family:system-ui,sans-serif;" +
      "background:#141414;color:#e8e8e8;'>" +
      "<div style='text-align:center;max-width:32rem;padding:2rem;'>" +
      "<div style='font-size:1.4rem;font-weight:600;margin-bottom:.75rem;'>" +
      "Blocked by subgate</div>" +
      "<div style='opacity:.75;line-height:1.5;'>" +
      "Reddit marks " + label + " as 18+.</div>" +
      "<div style='opacity:.45;margin-top:1.25rem;font-size:.85rem;'>" +
      "Decided by: " + reason + "</div></div></body>";
  }

  // ---------- layer 2: your subgate list ----------

  function loadListFromCache() {
    var raw = gmGet("list", "");
    if (!raw) { return null; }
    var set = new Set();
    var lines = raw.split("\n");
    for (var i = 0; i < lines.length; i++) {
      if (lines[i]) { set.add(lines[i]); }
    }
    return set.size ? set : null;
  }

  function refreshListIfStale() {
    var ts = parseInt(gmGet("list_ts", "0"), 10) || 0;
    if (Date.now() - ts < LIST_TTL_MS && listSet) { return; }
    var url = listUrl();
    xhr({
      method: "GET",
      url: url,
      timeout: 15000,
      onload: function (res) {
        if (res.status !== 200 || !res.responseText) {
          log("list refresh failed, status", res.status, "from", url);
          return;
        }
        var names = [];
        var lines = res.responseText.split("\n");
        var prefix = "||reddit.com/r/";
        for (var i = 0; i < lines.length; i++) {
          var line = lines[i];
          if (line.indexOf(prefix) !== 0) { continue; }
          var end = line.indexOf("^");
          if (end > prefix.length) {
            names.push(line.substring(prefix.length, end).toLowerCase());
          }
        }
        if (names.length) {
          gmSet("list", names.join("\n"));
          gmSet("list_ts", String(Date.now()));
          listSet = new Set(names);
          log("list refreshed:", names.length, "names, from", url);
          evaluate();
        } else {
          log("list refresh parsed 0 names, keeping old list. URL:", url);
        }
      },
      onerror: function () { log("list refresh network error from", url); },
      ontimeout: function () { log("list refresh timed out from", url); }
    });
  }

  // ---------- layer 3: the mirror, with a small verdict cache ----------

  var mirrorAsked = {};

  function mirrorCheck(sub) {
    var key = "v_" + sub.toLowerCase();
    var cached = gmGet(key, "");
    if (cached) {
      try {
        var obj = JSON.parse(cached);
        if (Date.now() - obj.ts < VERDICT_TTL_MS) {
          log("mirror cache for", sub, "->", obj.nsfw);
          if (obj.nsfw === true) { blockPage("mirror cache", sub); }
          else { revealMedia(); }
          return;
        }
      } catch (e) {}
    }
    if (mirrorAsked[key]) { return; }
    mirrorAsked[key] = true;
    var q = "{isNsfwSubreddit" + "(subreddit:\"" + sub + "\")}";
    xhr({
      method: "POST",
      url: "https://api.postpone.app/public/graphql",
      headers: { "Content-Type": "application/json" },
      data: JSON.stringify({ query: q }),
      timeout: 5000,
      onload: function (res) {
        var nsfw = null;
        try {
          var d = JSON.parse(res.responseText);
          if (d && d.data) { nsfw = d.data.isNsfwSubreddit; }
        } catch (e) {}
        log("mirror says", sub, "->", nsfw);
        if (nsfw === true || nsfw === false) {
          gmSet(key, JSON.stringify({ nsfw: nsfw, ts: Date.now() }));
        }
        if (nsfw === true) { blockPage("Reddit's flag via mirror", sub); }
        else if (nsfw === false) { revealMedia(); }
        // null means the mirror does not know it; markup stays the tiebreaker
      },
      onerror: function () { log("mirror unreachable for", sub); },
      ontimeout: function () { log("mirror timed out for", sub); }
    });
  }

  // ---------- layer 4: markup tiebreaker only ----------

  function markupSignal() {
    try {
      if (document.querySelector(".over18, form[action*='over18']")) {
        return "old Reddit 18+ interstitial";
      }
      if (document.querySelector(
        "xpromo-nsfw-blocking-container, shreddit-blocking-modal, " +
        "[data-testid='nsfw-gate']")) {
        return "18+ gate element";
      }
      if (document.querySelector(
        "shreddit-post[nsfw], shreddit-blurred-container, " +
        "shreddit-subreddit-header[nsfw], [data-nsfw='true']")) {
        return "18+ markup attribute";
      }
      var meta = document.querySelector(
        "meta[name='rating'], meta[property='og:restrictions:age']");
      if (meta) {
        var v = String(meta.getAttribute("content") || "").toLowerCase();
        if (v.indexOf("adult") !== -1 || v.indexOf("mature") !== -1 ||
            v.indexOf("18") !== -1) {
          return "page rating meta tag";
        }
      }
    } catch (e) {}
    return null;
  }

  // ---------- decision ----------

  function evaluate() {
    if (blocked) { return true; }
    var sub = subredditFromPath(location.pathname);
    if (!sub) { return false; }
    var lower = sub.toLowerCase();
    if (ALLOW.indexOf(lower) !== -1) {
      log("allowed by ALLOW list:", sub);
      revealMedia();
      return true;
    }
    if (listSet && listSet.has(lower)) {
      blockPage("your subgate list", sub);
      return true;
    }
    var m = markupSignal();
    if (m) {
      blockPage(m, sub);
      return true;
    }
    mirrorCheck(sub);
    return false;
  }

  // ---------- boot ----------

  listSet = loadListFromCache();
  if (listSet) { log("list loaded from cache:", listSet.size, "names"); }
  else { log("no cached list yet; mirror and markup carry this session"); }
  refreshListIfStale();

  hideMedia();
  evaluate();

  var observer = new MutationObserver(function () {
    if (blocked) { observer.disconnect(); return; }
    if (evaluate()) { observer.disconnect(); }
  });
  if (document.documentElement) {
    observer.observe(document.documentElement, { childList: true, subtree: true });
  }

  function onNavigate() {
    if (location.pathname === currentPath) { return; }
    currentPath = location.pathname;
    blocked = false;
    hideMedia();
    evaluate();
    setTimeout(function () { if (!blocked) { revealMedia(); } }, HIDE_MS);
  }
  ["pushState", "replaceState"].forEach(function (fn) {
    var orig = history[fn];
    history[fn] = function () {
      var r = orig.apply(this, arguments);
      setTimeout(onNavigate, 0);
      return r;
    };
  });
  window.addEventListener("popstate", onNavigate);

  setTimeout(function () {
    if (!blocked) {
      evaluate();
      if (!blocked) {
        revealMedia();
        var where = subredditFromPath(location.pathname) || location.pathname;
        log("no 18+ verdict, page allowed:", where);
      }
    }
  }, HIDE_MS);
})();
