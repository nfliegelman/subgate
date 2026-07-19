/* subgate background. Owns the list, the network-level rules, and verdicts.
 *
 * Responsibilities:
 *  1. Download the published subgate list on a schedule, parse it, keep the
 *     name set in storage.
 *  2. Maintain declarativeNetRequest dynamic rules for the biggest
 *     communities, so direct navigation is stopped before the page even
 *     starts loading. The content script covers the tail and in-app moves.
 *  3. Answer verdict requests from the content script: ALLOW list, then the
 *     subgate list, then Reddit's flag via the Postpone mirror with a cached
 *     answer.
 *
 * No analytics, no tracking, no data leaves the machine except the list
 * download and the per-name mirror checks.
 */

"use strict";

var DEFAULT_LIST_URL =
  "https://raw.githubusercontent.com/nfliegelman/subgate/main/subgate_full.txt";
var MIRROR_URL = "https://api.postpone.app/public/graphql";
var LIST_TTL_MS = 24 * 60 * 60 * 1000;
var VERDICT_TTL_MS = 7 * 24 * 60 * 60 * 1000;
var DNR_MAX = 28000;          // headroom under the 30k dynamic-rule ceiling
var DNR_CHUNK = 5000;
var DEFAULT_ALLOW = ["pornfree", "nofap"];

var nameSet = null;           // Set of lowercase names, lazy loaded

function log() {
  var args = ["subgate bg:"];
  for (var i = 0; i < arguments.length; i++) { args.push(arguments[i]); }
  console.log.apply(console, args);
}

function storageGet(keys) {
  return new Promise(function (resolve) {
    chrome.storage.local.get(keys, resolve);
  });
}

function storageSet(obj) {
  return new Promise(function (resolve) {
    chrome.storage.local.set(obj, resolve);
  });
}

async function getConfig() {
  var d = await storageGet({
    listUrl: DEFAULT_LIST_URL,
    allow: DEFAULT_ALLOW,
    names: [],
    listTs: 0,
    verdicts: {}
  });
  return d;
}

async function ensureNameSet() {
  if (nameSet) { return nameSet; }
  var d = await getConfig();
  nameSet = new Set(d.names || []);
  return nameSet;
}

// ---------- list download and parsing ----------

function parseList(text) {
  var names = [];
  var prefix = "||reddit.com/r/";
  var lines = text.split("\n");
  for (var i = 0; i < lines.length; i++) {
    var line = lines[i];
    if (line.indexOf(prefix) !== 0) { continue; }
    var end = line.indexOf("^");
    if (end > prefix.length) {
      names.push(line.substring(prefix.length, end).toLowerCase());
    }
  }
  return names;
}

async function refreshList(force) {
  var d = await getConfig();
  if (!force && Date.now() - (d.listTs || 0) < LIST_TTL_MS && d.names.length) {
    return { ok: true, count: d.names.length, skipped: true };
  }
  var url = d.listUrl || DEFAULT_LIST_URL;
  try {
    var res = await fetch(url, { cache: "no-cache" });
    if (!res.ok) {
      log("list fetch failed:", res.status, url);
      return { ok: false, error: "HTTP " + res.status };
    }
    var names = parseList(await res.text());
    if (!names.length) {
      log("list parsed to zero names, keeping the old one");
      return { ok: false, error: "parsed 0 names" };
    }
    await storageSet({ names: names, listTs: Date.now() });
    nameSet = new Set(names);
    var dnr = await rebuildDnrRules(names);
    log("list refreshed:", names.length, "names; network rules:", dnr);
    return { ok: true, count: names.length, dnr: dnr };
  } catch (e) {
    log("list fetch error:", String(e));
    return { ok: false, error: String(e) };
  }
}

// ---------- network-level rules ----------

function makeRule(id, name, useRedirect) {
  var action = useRedirect
    ? { type: "redirect", redirect: { extensionPath: "/blocked.html" } }
    : { type: "block" };
  return {
    id: id,
    priority: 1,
    action: action,
    condition: {
      urlFilter: "||reddit.com/r/" + name + "^",
      isUrlFilterCaseSensitive: false,
      resourceTypes: ["main_frame"]
    }
  };
}

async function rebuildDnrRules(names) {
  var api = chrome.declarativeNetRequest;
  if (!api) { return 0; }
  try {
    var existing = await api.getDynamicRules();
    var ids = existing.map(function (r) { return r.id; });
    if (ids.length) {
      await api.updateDynamicRules({ removeRuleIds: ids });
    }
    var top = names.slice(0, DNR_MAX);
    var added = 0;
    var useRedirect = true;
    for (var i = 0; i < top.length; i += DNR_CHUNK) {
      var chunk = [];
      for (var j = i; j < Math.min(i + DNR_CHUNK, top.length); j++) {
        chunk.push(makeRule(j + 1, top[j], useRedirect));
      }
      try {
        await api.updateDynamicRules({ addRules: chunk });
        added += chunk.length;
      } catch (e1) {
        if (useRedirect) {
          // Some engines reject extensionPath redirects; retry as plain block.
          useRedirect = false;
          chunk = [];
          for (var k = i; k < Math.min(i + DNR_CHUNK, top.length); k++) {
            chunk.push(makeRule(k + 1, top[k], false));
          }
          try {
            await api.updateDynamicRules({ addRules: chunk });
            added += chunk.length;
            continue;
          } catch (e2) {
            log("rule chunk rejected even as block, stopping at", added, String(e2));
            break;
          }
        }
        log("rule chunk rejected, stopping at", added, String(e1));
        break;
      }
    }
    await storageSet({ dnrCount: added, dnrMode: useRedirect ? "redirect" : "block" });
    return added;
  } catch (e) {
    log("dnr rebuild failed:", String(e));
    return 0;
  }
}

// ---------- mirror verdicts for names not on the list ----------

async function mirrorVerdict(sub) {
  var key = sub.toLowerCase();
  var d = await getConfig();
  var cached = (d.verdicts || {})[key];
  if (cached && Date.now() - cached.ts < VERDICT_TTL_MS) {
    return cached.nsfw;
  }
  var controller = new AbortController();
  var timer = setTimeout(function () { controller.abort(); }, 5000);
  try {
    var q = "{isNsfwSubreddit" + "(subreddit:\"" + key + "\")}";
    var res = await fetch(MIRROR_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query: q }),
      signal: controller.signal
    });
    var data = await res.json();
    var nsfw = data && data.data ? data.data.isNsfwSubreddit : null;
    if (nsfw === true || nsfw === false) {
      var verdicts = d.verdicts || {};
      verdicts[key] = { nsfw: nsfw, ts: Date.now() };
      await storageSet({ verdicts: verdicts });
    }
    return nsfw;
  } catch (e) {
    return null;
  } finally {
    clearTimeout(timer);
  }
}

// ---------- verdict service ----------

async function checkSub(sub) {
  var key = sub.toLowerCase();
  var d = await getConfig();
  var allow = (d.allow || DEFAULT_ALLOW).map(function (s) {
    return String(s).toLowerCase();
  });
  if (allow.indexOf(key) !== -1) {
    return { verdict: "allow", layer: "your ALLOW list" };
  }
  var set = await ensureNameSet();
  if (set.has(key)) {
    return { verdict: "block", layer: "your subgate list" };
  }
  var nsfw = await mirrorVerdict(key);
  if (nsfw === true) {
    return { verdict: "block", layer: "Reddit's flag via mirror" };
  }
  if (nsfw === false) {
    return { verdict: "allow", layer: "mirror says not 18+" };
  }
  return { verdict: "unknown", layer: "no data, markup decides" };
}

// ---------- wiring ----------

chrome.runtime.onMessage.addListener(function (msg, sender, sendResponse) {
  if (!msg || !msg.type) { return false; }
  if (msg.type === "check" && msg.sub) {
    checkSub(msg.sub).then(sendResponse);
    return true;
  }
  if (msg.type === "refresh") {
    refreshList(true).then(sendResponse);
    return true;
  }
  if (msg.type === "stats") {
    getConfig().then(function (d) {
      sendResponse({
        count: (d.names || []).length,
        listTs: d.listTs || 0,
        listUrl: d.listUrl || DEFAULT_LIST_URL
      });
    });
    return true;
  }
  return false;
});

if (chrome.webNavigation && chrome.webNavigation.onHistoryStateUpdated) {
  chrome.webNavigation.onHistoryStateUpdated.addListener(function (details) {
    chrome.tabs.sendMessage(details.tabId, { type: "nav" }, function () {
      void chrome.runtime.lastError; // tab may have no content script; fine
    });
  }, { url: [{ hostContains: "reddit" }] });
}

chrome.runtime.onInstalled.addListener(function () {
  chrome.alarms.create("subgate-refresh", { periodInMinutes: 360 });
  refreshList(true);
});

if (chrome.runtime.onStartup) {
  chrome.runtime.onStartup.addListener(function () {
    chrome.alarms.create("subgate-refresh", { periodInMinutes: 360 });
    refreshList(false);
  });
}

chrome.alarms.onAlarm.addListener(function (alarm) {
  if (alarm && alarm.name === "subgate-refresh") { refreshList(false); }
});

chrome.storage.onChanged.addListener(function (changes, area) {
  if (area === "local" && changes.listUrl) {
    nameSet = null;
    refreshList(true);
  }
});
