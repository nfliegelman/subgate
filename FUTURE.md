# subgate: Roadmap and Known Weaknesses

The phased plan, and the things deliberately not built yet. Phase gates are pre-registered: a later phase turns on only when its named condition is met, never because the data "looks ready." Phases map to semver minor bumps.

## Phase map

### Phase 1 (current): Verified catalog and two lists
Status: shipped in v0.1.0
- Seed collection (NSFWDog API weekly, manual paste file every run), Reddit-native discovery (`/subreddits/new` daily, one-time bootstrap search sweep), verification of every name against Reddit's `over_18` flag, persistent catalog with miss tracking, and two published adblock lists (full for Firefox uBlock Origin, capped for Chrome AdGuard MV3).

### Phase 2: Click-time dynamic checker (userscript)
Gate: after at least 2 weeks of live use, Noah reports reaching an NSFW subreddit the lists missed on at least 2 separate occasions. Do not build it preemptively.
- A small userscript (Tampermonkey or Violentmonkey) that, on any `reddit.com/r/<name>` navigation, queries that subreddit's live flag and blocks the page if 18+. No list, no lag behind newly created subs. Complements the lists rather than replacing them.

### Phase 3: iPhone Safari list layer
Gate: Noah decides he wants list coverage on the phone, accepting that it requires a shell app (AdGuard for Safari) and using Safari there. iOS Chrome has no extension platform, so this phase cannot cover it; the account-level 18+ setting plus NextDNS remain the phone layers until then.
- Publish the existing full list for AdGuard for Safari consumption (same format, already compatible) and document the phone setup in README.

## Known weaknesses / watch items
Honest list of what is fragile, approximated, or unproven. Not bugs to fix now, but things to watch.
- Unflagged subreddits slip through. The flag depends on moderators self-labeling, and Reddit's enforcement of labeling is imperfect. Mitigations: `force_block.txt` for anything Noah encounters, the NextDNS domain layer beneath, and Phase 2 if the miss rate proves real. Trigger for action: repeated misses on communities that are obviously 18+ but unflagged.
- Chrome trims the long tail. `chrome_max_rules` (20000) keeps only the biggest subs on Chrome; the run log prints the trimmed count. Trigger: if trimmed count grows large and Chrome is the primary browser, revisit the cap against AdGuard's observed ceiling.
- Directory dependency for the back catalog. Both NSFWDog and Postpone API shapes were verified 2026-07-18 but can change or vanish; the guard means the catalog persists regardless, only freshness of directory-sourced candidates degrades. Running two independent directories is the mitigation: a sampled overlap check showed each still contributes names the other lacks. Trigger: scraper failure warnings in the Actions log for 2+ consecutive weeks.
- New-subreddit window rollover. Reddit's new-subreddit feed exposes only the newest ~1000 entries, so capture of every creation depends on polling cadence (now every 6 hours, roughly 4000 per day of headroom). Trigger: the saturation warning appearing in an Actions log means a window rolled over unseen; the fix is more cron entries, not a bigger page count (the listing cap makes pages beyond 10 meaningless).
- Back-catalog completeness is unproven. Reddit listings cap around 1000 entries, so historical coverage rests on the bootstrap sweep plus seeds. The first bootstrap run's counts will show how big the verified catalog actually is; judge coverage then, not now.
- Unauthenticated mode is a smoke-test path only. It is slow by design and datacenter IPs are often blocked by Reddit; never rely on it in Actions.
- Search sweep recall is unmeasured. `include_over_18=on` behavior with app-only auth is assumed correct; if bootstrap yields suspiciously few NSFW results relative to NSFWDog-sourced ones, investigate before trusting the sweep.

## Parked ideas
Considered and set aside, with the reason, so they are not re-litigated from scratch.
- Regex-packed Chrome rules (many names per rule to beat the MV3 cap), parked because per-rule memory limits make it fragile and hard to debug; the subscriber-sorted trim is predictable.
- Self-hosted MITM proxy for path filtering across every app and browser, parked because certificate installs, cert-pinned app breakage, and an always-on host are heavy for the gain.
- Private repo with delivery via secret gist, parked because the public raw URL is simpler and stable; revisit only if the public repo becomes a problem.
- Postpone pagination beyond 35000 rows, parked because their endpoint 502s above that and the result set is already down to single-subscriber communities well before the cap.
