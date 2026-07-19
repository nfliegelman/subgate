// ==UserScript==
// @name         subgate
// @namespace    https://github.com/OWNER/subgate
// @version      0.2.1
// @description  Blocks subreddits Reddit itself marks 18+, checked at page load so brand new communities are covered without waiting for a list update.
// @match        *://*.reddit.com/*
// @run-at       document-start
// @grant        none
// ==/UserScript==

/*
 * How this works, in plain terms:
 *
 * Reddit's own pages announce when a community is 18+. Old Reddit shows an
 * "over 18" interstitial. New Reddit tags the page and the community header.
 * This script reads those signals as the page loads and stops the page before
 * you get anywhere. It calls no API, needs no key, and asks Reddit for nothing
 * it was not already sending you.
 *
 * That matters because it works on a subreddit created five minutes ago, which
 * no published list can know about yet.
 *
 * Tuning: Reddit changes its markup regularly. If something slips through, or
 * a safe subreddit gets blocked by mistake, open the browser console and look
 * for lines starting with "subgate". Every decision is logged with the reason.
 * Then adjust ALLOW below, or send the log line back and the detection rule
 * can be updated.
 */

(function () {
  "use strict";

  // Subreddits to never block, lowercase, no r/ prefix.
  const ALLOW = new Set([
    "pornfree",
    "nofap",
  ]);

  // Set to false once you trust it, to quiet the console.
  const VERBOSE = true;

  // Media stays hidden this long while the check runs. Prevents a flash of
  // images before a verdict. Raise it if your connection is slow.
  const HIDE_MS = 2500;

  const HIDE_STYLE_ID = "subgate-hide";
  let blocked = false;
  let currentPath = location.pathname;

  function log() {
    if (VERBOSE) {
      console.log.apply(console, ["subgate:"].concat([].slice.call(arguments)));
    }
  }

  function subredditFromPath(pathname) {
    const m = /^\/r\/([A-Za-z0-9_]{2,21})(\/|$)/.exec(pathname || "");
    return m ? m[1] : null;
  }

  // Hide media early, then reveal if the verdict is safe. Text is left alone so
  // normal browsing does not feel broken.
  function hideMedia() {
    if (document.getElementById(HIDE_STYLE_ID)) return;
    const style = document.createElement("style");
    style.id = HIDE_STYLE_ID;
    style.textContent =
      "img, video, canvas, [style*='background-image'], " +
      "shreddit-post img, shreddit-post video, .thumbnail img " +
      "{ visibility: hidden !important; }";
    (document.head || document.documentElement).appendChild(style);
  }

  function revealMedia() {
    const style = document.getElementById(HIDE_STYLE_ID);
    if (style) style.remove();
  }

  function blockPage(reason, sub) {
    if (blocked) return;
    blocked = true;
    try {
      window.stop();
    } catch (e) {
      // Not fatal; the rewrite below still runs.
    }
    log("BLOCKED", sub || "(unknown)", "reason:", reason);
    const label = sub ? "r/" + sub : "this page";
    document.documentElement.innerHTML =
      '<head><title>Blocked by subgate</title></head>' +
      '<body style="margin:0;display:flex;align-items:center;' +
      'justify-content:center;height:100vh;font-family:system-ui,sans-serif;' +
      'background:#141414;color:#e8e8e8;">' +
      '<div style="text-align:center;max-width:32rem;padding:2rem;">' +
      '<div style="font-size:1.4rem;font-weight:600;margin-bottom:.75rem;">' +
      "Blocked by subgate</div>" +
      '<div style="opacity:.75;line-height:1.5;">' +
      "Reddit marks " + label + " as 18+.</div>" +
      '<div style="opacity:.45;margin-top:1.25rem;font-size:.85rem;">' +
      "Detected: " + reason + "</div></div></body>";
  }

  // Each rule returns a reason string when it fires, otherwise null. Any single
  // rule firing is enough to block, so a markup change in one does not defeat
  // the rest.
  const RULES = [
    function oldRedditInterstitial() {
      // Old Reddit serves a dedicated over-18 gate with a known form.
      if (document.querySelector(".over18, form[action*='over18']")) {
        return "old Reddit 18+ interstitial";
      }
      return null;
    },
    function newRedditGate() {
      if (document.querySelector(
        "xpromo-nsfw-blocking-container, shreddit-blocking-modal, " +
        "shreddit-forbidden[reason='nsfw'], [data-testid='nsfw-gate']")) {
        return "new Reddit 18+ gate";
      }
      return null;
    },
    function communityAttribute() {
      // Shreddit exposes community metadata as element attributes.
      const el = document.querySelector(
        "shreddit-subreddit-header[nsfw], shreddit-app[nsfw='true'], " +
        "[data-nsfw='true'], shreddit-subreddit-header[is-nsfw='true']");
      return el ? "community tagged 18+ in page markup" : null;
    },
    function metaTag() {
      const meta = document.querySelector(
        "meta[name='rating'], meta[property='og:restrictions:age']");
      if (meta) {
        const v = (meta.getAttribute("content") || "").toLowerCase();
        if (v.indexOf("adult") !== -1 || v.indexOf("mature") !== -1 ||
            v.indexOf("rta-") !== -1 || v.indexOf("18") !== -1) {
          return "page rating meta tag: " + v;
        }
      }
      return null;
    },
    function nsfwBadge() {
      // The community header badge on a subreddit's own page.
      const nodes = document.querySelectorAll(
        "shreddit-subreddit-header [class*='nsfw'], " +
        ".subreddit-nsfw, .nsfw-stamp, [aria-label='NSFW']");
      return nodes.length ? "NSFW badge in community header" : null;
    },
  ];

  function evaluate() {
    if (blocked) return false;
    const sub = subredditFromPath(location.pathname);
    if (sub && ALLOW.has(sub.toLowerCase())) {
      log("allowed by ALLOW list:", sub);
      revealMedia();
      return true;
    }
    for (let i = 0; i < RULES.length; i++) {
      let reason = null;
      try {
        reason = RULES[i]();
      } catch (e) {
        // A broken selector must never take the whole script down.
      }
      if (reason) {
        blockPage(reason, sub);
        return true;
      }
    }
    return false;
  }

  hideMedia();
  evaluate();

  // Reddit renders progressively, so keep checking as nodes arrive.
  const observer = new MutationObserver(function () {
    if (evaluate()) observer.disconnect();
  });
  if (document.documentElement) {
    observer.observe(document.documentElement, { childList: true, subtree: true });
  }

  // Reddit is a single page app: a click can change the subreddit without a
  // page load, so re-arm on navigation.
  function onNavigate() {
    if (location.pathname === currentPath) return;
    currentPath = location.pathname;
    blocked = false;
    hideMedia();
    evaluate();
    setTimeout(function () { if (!blocked) revealMedia(); }, HIDE_MS);
  }
  ["pushState", "replaceState"].forEach(function (fn) {
    const orig = history[fn];
    history[fn] = function () {
      const r = orig.apply(this, arguments);
      setTimeout(onNavigate, 0);
      return r;
    };
  });
  window.addEventListener("popstate", onNavigate);

  // Failsafe: never leave media hidden forever on a safe page.
  setTimeout(function () {
    if (!blocked) {
      evaluate();
      if (!blocked) {
        revealMedia();
        log("no 18+ signal found, page allowed:",
            subredditFromPath(location.pathname) || location.pathname);
      }
    }
  }, HIDE_MS);
})();
