"""subgate: builds NSFW subreddit filter lists from Reddit's own over_18 flags.

What this does, in one breath: collect candidate subreddit names from seed
sources and from Reddit's own discovery endpoints, verify every name against
Reddit's authoritative per subreddit over_18 flag, keep a persistent catalog
in subgate_state.json, and publish two adblock format lists that block
reddit.com/r/<name> paths in the browser.

Reddit's flag is the sole authority for what ships. The one owner override is
force_block.txt. Read HANDOFF.md before changing behavior; the guards in it
are deliberate.

Version: bump VERSION here and add a changelog entry in HANDOFF.md in the
same commit (semver, tagged).
"""

import argparse
import datetime as dt
import json
import os
import re
import string
import sys
import time

import requests
import yaml

VERSION = "0.3.0"

STATE_FILE = "subgate_state.json"
FULL_LIST = "subgate_full.txt"
CHROME_LIST = "subgate_chrome.txt"
SOURCES_FILE = "sources.yaml"
FORCE_FILE = "force_block.txt"

# Subreddit names: letters, digits, underscore. A few legacy two character
# subs exist, so the floor is 2, the ceiling is Reddit's 21.
VALID_NAME_RE = re.compile(r"^[A-Za-z0-9_]{2,21}$")

# Pulls names out of pasted text: full URLs or bare r/Name mentions. The
# lookbehind stops "your/thing" from matching as r/thing.
PREFIXED_NAME_RE = re.compile(r"(?<![A-Za-z0-9_])r/([A-Za-z0-9_]{2,21})")


class BudgetExceeded(Exception):
    """Raised when the per run Reddit API call budget is used up."""


def utcnow_iso():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_config(path=SOURCES_FILE):
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    if not isinstance(cfg, dict):
        raise ValueError(f"{path} did not parse to a mapping")
    return cfg


# ---------------------------------------------------------------------------
# Name extraction
# ---------------------------------------------------------------------------

def extract_names(text):
    """Return a set of subreddit names found in arbitrary text.

    Accepts full reddit URLs, r/Name mentions anywhere, and bare names that
    sit alone on a line. Lines starting with # are comments and ignored.
    """
    names = set()
    kept_lines = []
    for line in (text or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        kept_lines.append(line)
        if VALID_NAME_RE.match(stripped):
            names.add(stripped)
    names.update(PREFIXED_NAME_RE.findall("\n".join(kept_lines)))
    return names


def read_names_file(path):
    if not os.path.exists(path):
        return set()
    with open(path, encoding="utf-8", errors="replace") as f:
        return extract_names(f.read())


def candidate_variants(slug, heading):
    """Directory sites slugify names, which is lossy (underscores and case
    are destroyed). Generate the plausible original spellings; verification
    against Reddit keeps only the ones that really exist, so recall matters
    here and precision comes free later."""
    cands = set()
    h = (heading or "").strip()
    if h:
        for c in (re.sub(r"\s+", "", h), re.sub(r"\s+", "_", h)):
            if VALID_NAME_RE.match(c):
                cands.add(c)
    s = (slug or "").strip()
    if s:
        for c in (s.replace("-", "_"), s.replace("-", "")):
            if VALID_NAME_RE.match(c):
                cands.add(c)
    return cands


# ---------------------------------------------------------------------------
# Reddit client
# ---------------------------------------------------------------------------

class RedditClient:
    """Thin Reddit JSON client. Authenticated (client_credentials, app only)
    when REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET are set, otherwise a slow
    unauthenticated fallback so local smoke tests work without secrets."""

    def __init__(self, cfg, max_calls=None):
        self.cid = os.environ.get("REDDIT_CLIENT_ID", "").strip()
        self.csec = os.environ.get("REDDIT_CLIENT_SECRET", "").strip()
        self.authed = bool(self.cid and self.csec)
        qpm = cfg.get("qpm_authenticated", 90) if self.authed else cfg.get("qpm_unauthenticated", 6)
        self.min_interval = 60.0 / max(float(qpm), 1.0)
        default_budget = int(cfg.get("max_calls_per_run", 4000))
        self.max_calls = default_budget if max_calls is None else int(max_calls)
        self.calls = 0
        self._last = 0.0
        uname = os.environ.get("REDDIT_USERNAME", "").strip()
        by = f" by u/{uname}" if uname else ""
        self.session = requests.Session()
        self.session.headers["User-Agent"] = (
            f"subgate/{VERSION}{by} (personal NSFW filter list builder)"
        )
        if self.authed:
            self._authenticate()

    def _authenticate(self):
        r = self.session.post(
            "https://www.reddit.com/api/v1/access_token",
            data={"grant_type": "client_credentials"},
            auth=(self.cid, self.csec),
            timeout=30,
        )
        r.raise_for_status()
        self.session.headers["Authorization"] = "bearer " + r.json()["access_token"]

    def get_json(self, path, params=None):
        if self.calls >= self.max_calls:
            raise BudgetExceeded(f"API call budget of {self.max_calls} reached")
        wait = self.min_interval - (time.time() - self._last)
        if wait > 0:
            time.sleep(wait)
        base = "https://oauth.reddit.com" if self.authed else "https://www.reddit.com"
        url = base + path
        if not self.authed and not url.endswith(".json"):
            url += ".json"
        p = dict(params or {})
        p.setdefault("raw_json", 1)
        last_err = None
        for attempt in range(3):
            self._last = time.time()
            self.calls += 1
            try:
                resp = self.session.get(url, params=p, timeout=30)
            except requests.RequestException as e:
                last_err = e
                time.sleep(3 * (attempt + 1))
                continue
            if resp.status_code == 200:
                return resp.json()
            last_err = requests.HTTPError(f"HTTP {resp.status_code} for {path}", response=resp)
            if resp.status_code in (429, 500, 502, 503):
                time.sleep(5 * (attempt + 1))
                continue
            break
        raise last_err


class PostponeVerifier:
    """Verification authority that does not require Reddit credentials.

    Postpone holds approved Reddit API access and republishes Reddit's own
    per subreddit over_18 field (their `over18`), with a
    lastRefreshedFromReddit timestamp. Measured 2026-07-18: flags correct on
    every spot check, and 62 percent of their catalog re-checked against
    Reddit within 24 hours, 88 percent within 7 days.

    Two paths:
      bulk_nsfw()   one request returning their whole NSFW catalog, which is
                    the backbone of verification.
      lookup(name)  one request per name, for candidates the bulk list does
                    not cover. Budgeted per run because it is a free third
                    party endpoint.
    """

    name = "postpone"

    def __init__(self, cfg):
        v = cfg.get("verification", {}) or {}
        self.url = v.get("postpone_url", "https://api.postpone.app/public/graphql")
        self.bulk_limit = int(v.get("postpone_bulk_limit", 30000))
        self.lookup_budget = int(v.get("per_run_lookup_budget", 300))
        self.min_interval = 60.0 / max(float(v.get("postpone_qpm", 45)), 1.0)
        self.timeout = int(v.get("timeout", 180))
        self.calls = 0
        self._last = 0.0
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": f"subgate/{VERSION} (personal NSFW filter list builder)",
            "Content-Type": "application/json",
        })

    def _post(self, query, timeout=None):
        wait = self.min_interval - (time.time() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.time()
        self.calls += 1
        r = self.session.post(self.url, json={"query": query},
                              timeout=timeout or self.timeout)
        r.raise_for_status()
        payload = r.json()
        if payload.get("errors"):
            raise RuntimeError(f"graphql errors: {str(payload['errors'])[:200]}")
        return payload.get("data") or {}

    def bulk_nsfw(self):
        """Their entire NSFW catalog in one request. Everything returned is
        confirmed 18+ by Reddit's own flag."""
        data = self._post("{nsfwSubreddits(limit:%d){name subscribers}}" % self.bulk_limit)
        rows = data.get("nsfwSubreddits") or []
        out = {}
        for row in rows:
            n = (row.get("name") or "").strip()
            if VALID_NAME_RE.match(n):
                out[n.lower()] = {"name": n, "over18": True,
                                  "subscribers": row.get("subscribers"), "type": None}
        return out

    def lookup(self, name):
        """Single name. Returns a result dict or None if it does not resolve."""
        data = self._post(
            '{subreddit(subreddit:"%s"){displayName over18 subscribers subredditType}}' % name,
            timeout=60)
        row = data.get("subreddit")
        if not row or not row.get("displayName"):
            return None
        return {"name": row["displayName"], "over18": bool(row.get("over18")),
                "subscribers": row.get("subscribers"), "type": row.get("subredditType")}


def build_verifier(cfg):
    """Pick the verification authority.

    auto (default): Reddit directly when credentials exist, otherwise
    Postpone's mirror. Reddit closed self-service API signup in late 2025 and
    blocked unauthenticated access in mid 2026, so the mirror is the working
    path for most people. If Reddit access is ever approved, adding the
    secrets switches this back with no code change.
    """
    provider = (cfg.get("verification", {}) or {}).get("provider", "auto")
    have_creds = bool(os.environ.get("REDDIT_CLIENT_ID", "").strip()
                      and os.environ.get("REDDIT_CLIENT_SECRET", "").strip())
    if provider == "reddit" or (provider == "auto" and have_creds):
        return RedditClient(cfg), True
    return PostponeVerifier(cfg), False


def children_to_results(payload):
    """Flatten a Reddit Listing of t5 things into {key: result}."""
    out = {}
    for child in (payload or {}).get("data", {}).get("children", []):
        d = child.get("data", {})
        dn = d.get("display_name") or ""
        if not dn:
            continue
        out[dn.lower()] = {
            "name": dn,
            "over18": bool(d.get("over18")),
            "subscribers": d.get("subscribers"),
            "type": d.get("subreddit_type"),
        }
    return out


def about_to_result(payload):
    d = (payload or {}).get("data", {})
    dn = d.get("display_name") or ""
    if not dn:
        return {}
    return {dn.lower(): {
        "name": dn,
        "over18": bool(d.get("over18")),
        "subscribers": d.get("subscribers"),
        "type": d.get("subreddit_type"),
    }}


def fetch_new_subreddits(client, pages):
    """Reddit's own feed of newly created subreddits, self verifying (the
    listing carries over18 directly)."""
    results, after = {}, None
    for _ in range(max(int(pages), 0)):
        params = {"limit": 100}
        if after:
            params["after"] = after
        payload = client.get_json("/subreddits/new", params)
        results.update(children_to_results(payload))
        after = (payload or {}).get("data", {}).get("after")
        if not after:
            break
    return results


def search_sweep(client, cfg):
    """Bootstrap harvest: sweep subreddit search with short tokens. Listings
    cap around 250 results per query, so many small queries beat one big one."""
    boot = cfg.get("bootstrap", {}) or {}
    tokens = list(string.ascii_lowercase) + list(string.digits)
    tokens += [str(t) for t in (boot.get("extra_tokens") or [])]
    pages = int(boot.get("pages_per_token", 3))
    results = {}
    for tok in tokens:
        after = None
        for _ in range(pages):
            params = {"q": tok, "include_over_18": "on", "limit": 100}
            if after:
                params["after"] = after
            payload = client.get_json("/subreddits/search", params)
            results.update(children_to_results(payload))
            after = (payload or {}).get("data", {}).get("after")
            if not after:
                break
    return results


# ---------------------------------------------------------------------------
# Seed sources (candidates only; Reddit verification decides what ships)
# ---------------------------------------------------------------------------

def polite_get(url, timeout=30):
    time.sleep(1.0)
    headers = {"User-Agent": f"subgate/{VERSION} (personal NSFW filter list builder)"}
    r = requests.get(url, headers=headers, timeout=timeout)
    r.raise_for_status()
    return r


def scrape_manual(src):
    return read_names_file(src.get("path", "manual_seeds.txt"))


def scrape_nsfwdog(src):
    base = src.get("url", "https://api2.nsfwdog.com/v1/subreddits/")
    max_pages = int(src.get("max_pages", 2000))
    names, url, page = set(), base.rstrip("/") + "/?page=1", 0
    while url and page < max_pages:
        page += 1
        data = polite_get(url).json()
        for row in data.get("results", []):
            names |= candidate_variants(row.get("slug"), row.get("heading"))
        url = data.get("next")
    return names


def scrape_html_regex(src):
    """Generic fallback: fetch pages and regex extract r/Name tokens. Only
    useful for server rendered pages."""
    names = set()
    for url in src.get("urls", []) or []:
        names |= extract_names(polite_get(url).text)
    return names


def scrape_postpone_graphql(src):
    """Postpone exposes a public GraphQL endpoint with an nsfwSubreddits
    query. It takes a limit and no offset, and returns rows ordered by
    subscriber count descending, so a single large-limit call retrieves the
    whole catalog. Verified 2026-07-18: 35000 rows served in about 12s,
    40000 returns 502, and the tail is already down to 1 subscriber by row
    25000, so the cap loses nothing that matters.

    Names come back clean (no slugification), so no variant generation is
    needed. Reddit verification still decides what ships.
    """
    url = src.get("url", "https://api.postpone.app/public/graphql")
    limit = int(src.get("limit", 35000))
    query = "{nsfwSubreddits(limit:%d){name}}" % limit
    time.sleep(1.0)
    headers = {
        "User-Agent": f"subgate/{VERSION} (personal NSFW filter list builder)",
        "Content-Type": "application/json",
    }
    r = requests.post(url, headers=headers, json={"query": query},
                      timeout=int(src.get("timeout", 180)))
    r.raise_for_status()
    payload = r.json()
    if payload.get("errors"):
        raise RuntimeError(f"graphql errors: {str(payload['errors'])[:200]}")
    rows = (payload.get("data") or {}).get("nsfwSubreddits") or []
    if not rows:
        raise RuntimeError("graphql returned no rows")
    names = set()
    for row in rows:
        n = (row.get("name") or "").strip()
        if VALID_NAME_RE.match(n):
            names.add(n)
    return names


SCRAPERS = {
    "manual": scrape_manual,
    "nsfwdog_api": scrape_nsfwdog,
    "postpone_graphql": scrape_postpone_graphql,
    "html_regex": scrape_html_regex,
}


def collect_candidates(cfg, include_directories):
    """Returns {lowercase_name: set(source_names)}. A source failing is logged
    and skipped; it never touches existing state (guard, see HANDOFF.md)."""
    cands = {}
    for src in cfg.get("sources", []) or []:
        if not src.get("enabled", False):
            continue
        typ = src.get("type")
        name = src.get("name", typ)
        if typ != "manual" and not include_directories:
            continue
        fn = SCRAPERS.get(typ)
        if fn is None:
            print(f"[warn] unknown source type {typ!r} for {name}, skipping")
            continue
        try:
            got = fn(src)
            print(f"[source] {name}: {len(got)} candidate names")
            for n in got:
                cands.setdefault(n.lower(), set()).add(name)
        except Exception as e:
            print(f"[warn] source {name} failed, continuing without it: {e}")
    return cands


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

def load_state(path=STATE_FILE):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {"version": 1, "updated_utc": None, "subs": {}}


def save_state(state, path=STATE_FILE):
    state["updated_utc"] = utcnow_iso()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, sort_keys=True, indent=1)
        f.write("\n")


def apply_verification(state, results, attempted, misses_before_gone, source_tag, now):
    """Merge one batch of verification results into state.

    attempted: lowercase keys we asked Reddit about in this batch. A key that
    is attempted but absent from results did not resolve; after
    misses_before_gone consecutive misses a known entry is marked gone.
    Removal from the published lists happens only through this function, on
    Reddit's own signal (guard, see HANDOFF.md).
    """
    subs = state["subs"]
    newly_nsfw = 0
    for key in attempted:
        r = results.get(key)
        e = subs.get(key)
        if r is not None:
            was_nsfw = bool(e) and e.get("status") == "nsfw"
            if e is None:
                e = {"first_seen_utc": now, "sources": []}
                subs[key] = e
            e["name"] = r["name"]
            e["over18"] = r["over18"]
            e["subscribers"] = r.get("subscribers")
            e["subreddit_type"] = r.get("type")
            e["status"] = "nsfw" if r["over18"] else "sfw"
            e["misses"] = 0
            e["last_verified_utc"] = now
            if source_tag and source_tag not in e["sources"]:
                e["sources"].append(source_tag)
            if e["status"] == "nsfw" and not was_nsfw:
                newly_nsfw += 1
        elif e is not None:
            e["misses"] = int(e.get("misses", 0)) + 1
            if e["misses"] >= misses_before_gone:
                e["status"] = "gone"
    return newly_nsfw


def tag_sources(state, cand_sources):
    for key, tags in cand_sources.items():
        e = state["subs"].get(key)
        if e is None:
            continue
        for t in sorted(tags):
            if t not in e["sources"]:
                e["sources"].append(t)


def verify_and_apply(client, state, names, misses_before_gone, now):
    """Verify names in batches of 100 via /api/info and merge each batch as it
    lands, so a budget stop mid run keeps everything verified so far."""
    todo = sorted({n.lower() for n in names})
    resolved = 0
    fallback_warned = False
    for i in range(0, len(todo), 100):
        chunk = todo[i:i + 100]
        try:
            payload = client.get_json("/api/info", {"sr_name": ",".join(chunk)})
            results = children_to_results(payload)
        except BudgetExceeded:
            raise
        except requests.HTTPError as e:
            code = getattr(getattr(e, "response", None), "status_code", None)
            if not client.authed and code in (403, 404):
                if not fallback_warned:
                    print("[warn] /api/info unavailable unauthenticated, "
                          "falling back to per name lookups (slow)")
                    fallback_warned = True
                results = {}
                for n in chunk:
                    try:
                        results.update(about_to_result(client.get_json(f"/r/{n}/about")))
                    except BudgetExceeded:
                        raise
                    except requests.HTTPError:
                        continue
            else:
                raise
        resolved += len(results)
        apply_verification(state, results, set(chunk), misses_before_gone, None, now)
    return len(todo), resolved


def verify_via_postpone(verifier, state, candidate_names, misses_before_gone, now):
    """Verification without Reddit credentials.

    Pass 1 (bulk): one request returns Postpone's whole NSFW catalog. Every
    name in it is marked nsfw.

    Pass 2 (drain): names in the catalog that bulk did not confirm get a
    per-name lookup, capped by per_run_lookup_budget because this is a free
    third party endpoint. The queue drains across runs, oldest unverified
    first.

    GUARD: absence from the bulk list must never mark a name sfw or gone. The
    bulk list is capped, so absence means unknown, not safe. Only an explicit
    per-name lookup can set sfw, and only a failed lookup counts as a miss.
    """
    bulk = verifier.bulk_nsfw()
    apply_verification(state, bulk, set(bulk.keys()), misses_before_gone, "postpone_bulk", now)
    print(f"[verify] postpone bulk confirmed {len(bulk)} nsfw subreddits")

    known = set(state["subs"].keys())
    pending = sorted((set(candidate_names) | known) - set(bulk.keys()))
    # Never verified yet first, then least recently verified.
    def sort_key(k):
        e = state["subs"].get(k) or {}
        return (e.get("last_verified_utc") or "", k)
    pending.sort(key=sort_key)

    budget = verifier.lookup_budget
    attempted, resolved = 0, 0
    for key in pending[:budget]:
        attempted += 1
        try:
            r = verifier.lookup(key)
        except BudgetExceeded:
            raise
        except Exception as e:
            print(f"[warn] lookup failed for one name, continuing: {str(e)[:80]}")
            continue
        results = {key: r} if r else {}
        if r:
            resolved += 1
        apply_verification(state, results, {key}, misses_before_gone, "postpone_lookup", now)
    remaining = max(0, len(pending) - budget)
    print(f"[verify] postpone drain: attempted {attempted}, resolved {resolved}, "
          f"{remaining} still queued for later runs")
    return attempted, resolved


# ---------------------------------------------------------------------------
# Emission
# ---------------------------------------------------------------------------

RULE_PREFIX = "||reddit.com/r/"


def rule_line(name):
    # ||reddit.com matches every subdomain (www, old, sh, np, new). The ^
    # separator stops r/name from also matching r/nameplus. Adblock matching
    # is case insensitive by default, which fits Reddit's case insensitive
    # subreddit routing.
    #
    # $all is load bearing. Without it, uBlock treats a path filter as
    # subresource-only: the app's background fetches get blocked (clicks die
    # silently) but typing the URL or opening a post link loads the page.
    # Observed live 2026-07-19. $all includes the document type, so direct
    # navigation gets uBlock's block page too. AdGuard supports $all as well.
    return f"{RULE_PREFIX}{name}^$all"


def build_entries(state, force_names):
    entries, seen = [], set()
    for key, e in state["subs"].items():
        if e.get("status") == "nsfw":
            entries.append({"name": e.get("name") or key, "subscribers": e.get("subscribers")})
            seen.add(key)
    forced_added = 0
    for n in sorted(force_names, key=str.lower):
        if n.lower() not in seen and VALID_NAME_RE.match(n):
            entries.append({"name": n, "subscribers": None})
            forced_added += 1
    entries.sort(key=lambda x: (-(x["subscribers"] or 0), x["name"].lower()))
    return entries, forced_added


def repo_homepage():
    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    return f"https://github.com/{repo}" if repo else "https://github.com/OWNER/subgate"


def write_list(path, entries, flavor, cap=None):
    subset = entries[:cap] if cap else entries
    lines = [
        f"! Title: subgate ({flavor})",
        f"! Description: Subreddits Reddit itself flags 18+, path blocked. Built by subgate v{VERSION}.",
        f"! Homepage: {repo_homepage()}",
        f"! Version: {utcnow_iso()}",
        "! Expires: 1 day",
        f"! Entry count: {len(subset)}",
    ]
    lines += [rule_line(x["name"]) for x in subset]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return len(subset)


def summarize(state):
    counts = {"nsfw": 0, "sfw": 0, "gone": 0}
    for e in state["subs"].values():
        s = e.get("status")
        if s in counts:
            counts[s] += 1
    return counts


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def is_scrape_time(cfg, now=None):
    """Weekly directory re-scrape fires on one specific run only: the
    configured weekday AND hour (UTC). With the workflow polling every 6
    hours, this keeps the full NSFWDog crawl to once a week instead of four
    times every Sunday."""
    now = now or dt.datetime.now(dt.timezone.utc)
    return (now.weekday() == int(cfg.get("scrape_weekday", 6))
            and now.hour == int(cfg.get("scrape_hour", 9)))


def run_pipeline(mode, args):
    cfg = load_config()
    state = load_state()
    now = utcnow_iso()
    verifier, is_reddit = build_verifier(cfg)
    if is_reddit:
        client = verifier
        print(f"[subgate v{VERSION}] mode={mode} verify=reddit "
              f"auth={'oauth' if client.authed else 'none (slow local fallback)'} "
              f"budget={client.max_calls} calls")
    else:
        print(f"[subgate v{VERSION}] mode={mode} verify=postpone (no Reddit "
              f"credentials needed) lookup_budget={verifier.lookup_budget}")
    misses = int(cfg.get("misses_before_gone", 3))
    budget_hit = False
    cand_sources = {}
    try:
        if is_reddit and mode == "bootstrap":
            res = search_sweep(verifier, cfg)
            apply_verification(state, res, set(res.keys()), misses, "reddit_search", now)
            print(f"[discover] search sweep saw {len(res)} subreddits")
        if is_reddit and not args.skip_new:
            pages = args.reddit_new_pages if args.reddit_new_pages is not None \
                else int(cfg.get("reddit_new_pages", 10))
            res = fetch_new_subreddits(verifier, pages)
            unseen = [k for k in res if k not in state["subs"]]
            window = pages * 100
            if state["subs"] and len(res) >= window - 10 and len(unseen) == len(res):
                print("[warn] entire new-subreddit window was unseen; the "
                      "window may have rolled over between runs. Consider a "
                      "higher polling cadence (see FUTURE.md watch item).")
            apply_verification(state, res, set(res.keys()), misses, "reddit_new", now)
            print(f"[discover] /subreddits/new saw {len(res)} subreddits "
                  f"({len(unseen)} new to the catalog)")
        elif not is_reddit:
            print("[discover] Reddit-native discovery skipped (no credentials). "
                  "Brand new subreddits are covered by the browser userscript, "
                  "not by these lists. See README.")
        scrape_dirs = mode == "bootstrap" or args.force_scrape or is_scrape_time(cfg)
        cand_sources = collect_candidates(cfg, scrape_dirs)
        names = set(cand_sources.keys()) | set(state["subs"].keys())
        if is_reddit:
            attempted, resolved = verify_and_apply(verifier, state, names, misses, now)
            print(f"[verify] attempted {attempted} names, {resolved} resolved")
        else:
            verify_via_postpone(verifier, state, names, misses, now)
    except BudgetExceeded as e:
        budget_hit = True
        print(f"[warn] {e}; emitting lists from what is verified so far")
    except (requests.RequestException, RuntimeError) as e:
        if not state["subs"]:
            raise
        print(f"[warn] verification pass failed ({str(e)[:100]}); emitting "
              "lists from the existing catalog, which is left intact")
    tag_sources(state, cand_sources)
    force = read_names_file(FORCE_FILE)
    entries, forced = build_entries(state, force)
    n_full = write_list(FULL_LIST, entries, "full")
    cap = int(cfg.get("chrome_max_rules", 20000))
    n_chrome = write_list(CHROME_LIST, entries, "chrome", cap=cap)
    save_state(state)
    counts = summarize(state)
    trimmed = max(0, len(entries) - n_chrome)
    print(f"[emit] full={n_full} chrome={n_chrome} (cap {cap}, trimmed {trimmed}) forced={forced}")
    print(f"[state] nsfw={counts['nsfw']} sfw={counts['sfw']} gone={counts['gone']} "
          f"api_calls={verifier.calls} budget_hit={budget_hit}")


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="subgate",
        description="Build NSFW subreddit filter lists from Reddit's own flags.",
    )
    ap.add_argument("mode", nargs="?", choices=["run", "bootstrap"], default="run",
                    help="run: daily update. bootstrap: one time deep harvest.")
    ap.add_argument("--force-scrape", action="store_true",
                    help="scrape directory sources even off schedule")
    ap.add_argument("--skip-new", action="store_true",
                    help="skip the /subreddits/new discovery pass")
    ap.add_argument("--reddit-new-pages", type=int, default=None,
                    help="override reddit_new_pages from sources.yaml")
    ap.add_argument("--max-calls", type=int, default=None,
                    help="override max_calls_per_run from sources.yaml")
    args = ap.parse_args(argv)
    run_pipeline(args.mode, args)


if __name__ == "__main__":
    sys.exit(main())
