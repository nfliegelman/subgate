# subgate: Technical Handoff

You are an AI assistant helping Noah modify this program. Noah is a data enthusiast, not a professional developer. This file is the project-specific technical spec: what the program is, how it is built, and which decisions are deliberate. Read it fully before proposing changes.

The prime directives, coding conventions, validation gates, and handback protocol live in the project instructions, not in this file. Read those first. If you are reading this repo without them (for example straight from GitHub), the two rules most expensive to miss are: never delete or hand back the state and data files listed in the manifest below, and never use em dashes anywhere. Then go find the full project instructions before editing.

**Versioning:** semver (MAJOR.MINOR.PATCH) via git tags. PATCH for fixes and guard-preserving tweaks, MINOR for new features or roadmap phases, MAJOR for breaking changes to the data schema, list format, or state format. Bump `VERSION` in `subgate.py`, the tag, and add a changelog entry in the same commit as the code change. Current: v0.1.2.

---

## 1. What this program is
subgate builds and publishes adblock-format filter lists that block NSFW subreddit paths (`reddit.com/r/<name>`) in the browser, so Noah can use Reddit without its adult side. The core design decision: Reddit's own per-subreddit `over_18` flag is the sole authority for what ships. Seed directories and pasted lists only nominate candidates; every name is verified against Reddit's flag before it can appear in a list. A good output is two fresh list files at stable raw GitHub URLs, regenerated daily, that uBlock Origin (Firefox) and AdGuard's MV3 extension (Chrome) consume automatically.

## 2. Architecture
- Entry point: `subgate.py`. Modes: `run` (daily) and `bootstrap` (one-time deep harvest). Flags: `--force-scrape`, `--skip-new`, `--reddit-new-pages N`, `--max-calls N`.
- Data sources:
  - Reddit API (the authority and a discovery source). Auth: OAuth2 client_credentials using a free "script" app; secrets `REDDIT_CLIENT_ID` and `REDDIT_CLIENT_SECRET` (optional `REDDIT_USERNAME` for the user agent string). Unauthenticated fallback exists for local smoke tests only (slow, and datacenter IPs may be blocked). Endpoints: `/api/info?sr_name=` (batch verify, 100 names per call), `/subreddits/new` (daily discovery), `/subreddits/search` (bootstrap sweep), `/r/<name>/about` (per-name fallback).
  - NSFWDog directory API (`api2.nsfwdog.com/v1/subreddits/`, paginated JSON, about 89k entries as of 2026-07-18). Candidates only. Their slugs are lossy, so `candidate_variants()` generates plausible original spellings and verification keeps the real ones.
  - Postpone directory (`api.postpone.app/public/graphql`, `nsfwSubreddits(limit)` query, about 33.8k clean names as of 2026-07-18). Candidates only. Names arrive unslugified so no variant generation is needed. One request per weekly crawl.
  - `manual_seeds.txt`: paste anything; the extractor pulls names from URLs, `r/Name` mentions, and bare lines.
  - `force_block.txt`: the single owner override; names here ship regardless of the flag.
- State and output files, in repo root, committed back by the workflow: `subgate_state.json` (the catalog), `subgate_full.txt` (full list), `subgate_chrome.txt` (capped list).
- Deploy: GitHub Actions (`.github/workflows/subgate.yml`), cron every 6 hours (03:13, 09:13, 15:13, 21:13 UTC) plus `workflow_dispatch` with a mode picker for the one-time bootstrap. The 6 hour cadence exists because Reddit's new-subreddit listing only ever exposes the newest ~1000 entries; polling must outrun that window to catch every creation. The weekly NSFWDog crawl is pinned to the single run matching `scrape_weekday` plus `scrape_hour`. The repo must be public so the raw list URLs are fetchable without auth.

## 3. Deliberate decisions and guards (do not undo without cause)
Everything here is on purpose. The burden of proof to remove a guard is high; default to keeping it and flag explicitly if you think it should go.
- Reddit's `over_18` flag is the sole shipping authority; `force_block.txt` is the only override. Never ship a directory's word for it unverified.
- Entries leave the published lists only on Reddit's own signal: flag flipped to false, or `misses_before_gone` (3) consecutive failed resolutions marking the entry `gone`. A directory dropping a name never removes it from the catalog.
- Seed source failures are logged and skipped; they must never zero or shrink existing state. A broken scraper degrades freshness, not coverage.
- Budget exhaustion mid-run still emits lists from everything verified so far (fail-open on emission, fail-safe on removal). Batches are verified and merged one at a time to make this true.
- Rate limits are guards: 90 QPM authenticated (Reddit's free tier is 100), 6 QPM unauthenticated, one request per second with an honest user agent on directory crawls, and the full directory re-scrape pinned to one run per week (`scrape_weekday` plus `scrape_hour`). Do not raise these to make runs faster, and do not let a cadence increase multiply the directory crawl.
- Postpone's limit stays at 35000: 40000 returns 502, and the result set is subscriber-descending and already at 1 subscriber by row 25000, so raising it buys nothing. Do not chase a bigger number.
- `chrome_max_rules` stays conservative (20000) until AdGuard's real MV3 ceiling is observed on Noah's machine. Regex packing to squeeze more rules in is parked (see FUTURE.md), not an invitation.
- State and list files are committed by the workflow and NEVER ship in handback zips.
- The em dash ban is enforced by a unit test (`test_no_em_dashes`); keep that test passing and do not weaken it.

## 4. Data schema
`subgate_state.json`:
- `version` (int): schema version, currently 1. Bump on breaking changes (MAJOR).
- `updated_utc` (str): ISO timestamp of the last save.
- `subs` (object): keyed by lowercase subreddit name. Each entry:
  - `name` (str): canonical display name from Reddit (case preserved).
  - `over18` (bool): Reddit's flag at last verification.
  - `subscribers` (int or null): from Reddit; used to sort lists and trim the Chrome build.
  - `subreddit_type` (str or null): e.g. public, restricted, private.
  - `status` (str): `nsfw` (ships), `sfw` (tracked, re-checked, flips handled), or `gone` (stopped resolving; excluded but retained).
  - `sources` (list of str): where the name was first nominated (`reddit_new`, `reddit_search`, `nsfwdog`, `manual`).
  - `misses` (int): consecutive failed resolutions; reset to 0 on success.
  - `first_seen_utc`, `last_verified_utc` (str): ISO timestamps.

List files: adblock syntax, header comments (`! Title`, `! Version`, `! Expires: 1 day`, `! Entry count`) then one `||reddit.com/r/<name>^` rule per entry, sorted by subscribers descending. `||reddit.com` covers every subdomain (www, old, sh, np); `^` stops prefix collisions; adblock matching is case-insensitive by default, matching Reddit's case-insensitive routing.

## 5. Handback manifest
Ships in every handback (full files, zipped, never diffs):
- `subgate.py`, `test_subgate.py`, `sources.yaml`, `manual_seeds.txt`, `force_block.txt`
- `HANDOFF.md`, `FUTURE.md`, `README.md`, `gitignore.txt`
- `.github/workflows/subgate.yml`
- `AUDIT_TODO.md` only during an audit

Never ships (the live track record; the workflow commits it back, git history is the backup):
- `subgate_state.json`
- `subgate_full.txt`, `subgate_chrome.txt`

## 6. Changelog
Newest first. One entry per code change, in the same commit.

### v0.1.2 (2026-07-18)
- Postpone re-enabled as a first-class source via new `postpone_graphql` scraper, replacing the manual paste workaround. Their public GraphQL endpoint returns the full catalog (about 33.8k valid names) in a single request, so it refreshes automatically on the weekly crawl.
- Added tests for the new scraper (query construction, name filtering, error and empty handling) and an explicit regression test that a failing source cannot shrink the catalog.

### v0.1.1 (2026-07-18)
- Polling cadence raised from daily to every 6 hours so new-subreddit creation cannot outrun Reddit's ~1000 entry listing window; headroom is now roughly 4000 creations per day.
- Weekly NSFWDog crawl pinned to a single run via new `scrape_hour` config (`is_scrape_time`), so the cadence increase does not multiply directory traffic.
- Saturation warning added: if an entire fetched new-subreddit window is unseen, the log flags probable rollover, the pre-registered trigger for raising cadence further (FUTURE.md watch item).

### v0.1.0 (2026-07-18)
- Initial build. Pipeline: seed collection (NSFWDog API, manual paste file), Reddit-native discovery (`/subreddits/new` daily, search sweep in bootstrap mode), batch verification against `over_18` via `/api/info` with per-name fallback, persistent catalog with miss tracking, force-block override, and emission of full plus Chrome-capped adblock lists.
- Daily GitHub Actions workflow with manual bootstrap dispatch; state and lists committed back by the workflow.
- Unit test suite including the automated em dash sweep. Postpone source shipped disabled (client-rendered, no endpoint found 2026-07-18).

## 7. Decision log
Longer-lived "why we chose X over Y" notes that outlast a single changelog line.
- Reddit's flag over curated directories as the authority: directories are marketer-built, partial, and stale; the flag is complete, live, and free to query in batches of 100. Directories were demoted to candidate nomination only.
- OAuth client_credentials over password grant: verification only needs app-level access to public data, so Noah's Reddit password never exists in secrets.
- Two list artifacts over regex packing: Chrome MV3 caps dynamic rules, and packing thousands of names into regex alternations hits per-rule memory limits and is fragile. A subscriber-sorted trim loses only the long tail on Chrome; Firefox gets everything.
- Slug variant generation for NSFWDog: their slugs destroy underscores and case, so the scraper emits several plausible spellings per row and lets verification pick the real one. Recall at the scraper, precision at the verifier.
- Name "subgate" over descriptive names: the repo must be public for raw URL subscriptions, so the name stays discreet on Noah's profile while README states plainly what it does.
- Unauthenticated fallback kept despite being slow: it makes local smoke tests possible with zero setup, and it is the honest path for a fresh clone before secrets exist.
