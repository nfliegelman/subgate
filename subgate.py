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

VERSION = "0.1.2"

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


# ---------------------------------------------------------------------------
# Emission
# ---------------------------------------------------------------------------

RULE_PREFIX = "||reddit.com/r/"


def rule_line(name):
    # ||reddit.com matches every subdomain (www, old, sh, np, new). The ^
    # separator stops r/name from also matching r/nameplus. Adblock matching
    # is case insensitive by default, which fits Reddit's case insensitive
    # subreddit routing.
    return f"{RULE_PREFIX}{name}^"


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
    client = RedditClient(cfg, max_calls=args.max_calls)
    print(f"[subgate v{VERSION}] mode={mode} "
          f"auth={'oauth' if client.authed else 'none (slow local fallback)'} "
          f"budget={client.max_calls} calls")
    misses = int(cfg.get("misses_before_gone", 3))
    budget_hit = False
    cand_sources = {}
    try:
        if mode == "bootstrap":
            res = search_sweep(client, cfg)
            apply_verification(state, res, set(res.keys()), misses, "reddit_search", now)
            print(f"[discover] search sweep saw {len(res)} subreddits")
        if not args.skip_new:
            pages = args.reddit_new_pages if args.reddit_new_pages is not None \
                else int(cfg.get("reddit_new_pages", 10))
            res = fetch_new_subreddits(client, pages)
            unseen = [k for k in res if k not in state["subs"]]
            window = pages * 100
            if state["subs"] and len(res) >= window - 10 and len(unseen) == len(res):
                print("[warn] entire new-subreddit window was unseen; the "
                      "window may have rolled over between runs. Consider a "
                      "higher polling cadence (see FUTURE.md watch item).")
            apply_verification(state, res, set(res.keys()), misses, "reddit_new", now)
            print(f"[discover] /subreddits/new saw {len(res)} subreddits "
                  f"({len(unseen)} new to the catalog)")
        scrape_dirs = mode == "bootstrap" or args.force_scrape or is_scrape_time(cfg)
        cand_sources = collect_candidates(cfg, scrape_dirs)
        names = set(cand_sources.keys()) | set(state["subs"].keys())
        attempted, resolved = verify_and_apply(client, state, names, misses, now)
        print(f"[verify] attempted {attempted} names, {resolved} resolved")
    except BudgetExceeded as e:
        budget_hit = True
        print(f"[warn] {e}; emitting lists from what is verified so far")
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
          f"api_calls={client.calls} budget_hit={budget_hit}")


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
