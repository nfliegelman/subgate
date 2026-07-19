/* subgate content script. Runs on every reddit.com page at document-start.
 *
 * Asks the background for a verdict (ALLOW list, subgate list, mirror), hides
 * media while waiting, blocks in place when told to, and keeps a markup
 * tiebreaker for when the background or network is unavailable. Handles
 * Reddit's in-app navigation via a nudge from the background's webNavigation
 * listener plus a local popstate fallback.
 */

"use strict";

(function () {
  var HIDE_MS = 3500;
  var HIDE_STYLE_ID = "subgate-hide";
  var VERBOSE_DEFAULT = true;

  var blocked = false;
  var currentPath = location.pathname;
  var verbose = VERBOSE_DEFAULT;

  try {
    chrome.storage.local.get({ verbose: VERBOSE_DEFAULT }, function (d) {
      verbose = !!d.verbose;
    });
  } catch (e) {}

  function log() {
    if (!verbose) { return; }
    var args = ["subgate:"];
    for (var i = 0; i < arguments.length; i++) { args.push(arguments[i]); }
    console.log.apply(console, args);
  }

  function subredditFromPath(pathname) {
    var m = /^\/r\/([A-Za-z0-9_]{2,21})(\/|$)/.exec(pathname || "");
    return m ? m[1] : null;
  }

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

  function evaluate() {
    if (blocked) { return; }
    var sub = subredditFromPath(location.pathname);
    if (!sub) { revealMedia(); return; }
    var m = markupSignal();
    if (m) { blockPage(m, sub); return; }
    var answered = false;
    try {
      chrome.runtime.sendMessage({ type: "check", sub: sub }, function (res) {
        answered = true;
        if (chrome.runtime.lastError || !res) {
          log("background unavailable, markup only for", sub);
          return;
        }
        if (res.verdict === "block") { blockPage(res.layer, sub); }
        else if (res.verdict === "allow") {
          log("allowed:", sub, "by", res.layer);
          revealMedia();
        } else {
          log("unknown:", sub, "markup stays armed");
        }
      });
    } catch (e) {
      log("messaging failed, markup only:", String(e));
    }
    setTimeout(function () {
      if (!answered && !blocked) { log("verdict timeout for", sub); }
    }, 5200);
  }

  function onNavigate() {
    if (location.pathname === currentPath) { return; }
    currentPath = location.pathname;
    blocked = false;
    hideMedia();
    evaluate();
    setTimeout(function () { if (!blocked) { revealMedia(); } }, HIDE_MS);
  }

  try {
    chrome.runtime.onMessage.addListener(function (msg) {
      if (msg && msg.type === "nav") { onNavigate(); }
    });
  } catch (e) {}
  window.addEventListener("popstate", onNavigate);

  hideMedia();
  evaluate();

  var observer = new MutationObserver(function () {
    if (blocked) { observer.disconnect(); return; }
    var sub = subredditFromPath(location.pathname);
    if (!sub) { return; }
    var m = markupSignal();
    if (m) { blockPage(m, sub); observer.disconnect(); }
  });
  if (document.documentElement) {
    observer.observe(document.documentElement, { childList: true, subtree: true });
  }

  setTimeout(function () {
    if (!blocked) {
      evaluate();
      setTimeout(function () {
        if (!blocked) {
          revealMedia();
          var where = subredditFromPath(location.pathname) || location.pathname;
          log("no 18+ verdict, page allowed:", where);
        }
      }, 700);
    }
  }, HIDE_MS);
})();
