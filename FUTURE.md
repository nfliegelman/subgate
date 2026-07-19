# subgate: Roadmap and Known Weaknesses

The phased plan, and the things deliberately not built yet. Phase gates are pre-registered: a later phase turns on only when its named condition is met, never because the data "looks ready." Phases map to semver minor bumps.

## Phase map

### Phase 1 (current): Verified catalog and two lists
Status: shipped in v0.1.0
- Seed collection (NSFWDog API weekly, manual paste file every run), Reddit-native discovery (`/subreddits/new` daily, one-time bootstrap search sweep), verification of every name against Reddit's `over_18` flag, persistent catalog with miss tracking, and two published adblock lists (full for Firefox uBlock Origin, capped for Chrome AdGuard MV3).

### Phase 2: Click-time dynamic checker (userscript)
Status: shipped in v0.2.0 as `subgate.user.js`. The original gate (2+ observed list misses over 2+ weeks) was superseded, not met: Reddit closing API access removed the lists' only new-subreddit feed, so the condition that justified waiting no longer applied. Implementation differs from the original sketch in one way: instead of querying an API for the flag, it reads the 18+ signals Reddit's own pages already carry (interstitials, gates, markup attributes), which needs no credentials and no network calls.

### Phase 3: iPhone Safari list layer
Gate: Noah decides he wants list coverage on the phone, accepting that it requires a shell app (AdGuard for Safari) and using Safari there. iOS Chrome has no extension platform, so this phase cannot cover it; the account-level 18+ setting plus NextDNS remain the phone layers until then.
- Publish the existing full list for AdGuard for Safari consumption (same format, already compatible) and document the phone setup in README.

## Known weaknesses / watch items
Honest list of what is fragile, approximated, or unproven. Not bugs to fix now, but things to watch.
- Unflagged subreddits slip through. The flag depends on moderators self-labeling, and Reddit's enforcement of labeling is imperfect. Mitigations: `force_block.txt` for anything Noah encounters, the NextDNS domain layer beneath, and Phase 2 if the miss rate proves real. Trigger for action: repeated misses on communities that are obviously 18+ but unflagged.
- Chrome trims the long tail. `chrome_max_rules` (20000) keeps only the biggest subs on Chrome; the run log prints the trimmed count. Trigger: if trimmed count grows large and Chrome is the primary browser, revisit the cap against AdGuard's observed ceiling.
- Directory dependency for the back catalog. Both NSFWDog and Postpone API shapes were verified 2026-07-18 but can change or vanish; the guard means the catalog persists regardless, only freshness of directory-sourced candidates degrades. Running two independent directories is the mitigation: a sampled overlap check showed each still contributes names the other lacks. Trigger: scraper failure warnings in the Actions log for 2+ consecutive weeks.
- Brand new subreddits are invisible to the lists in the default (no credentials) path. There is no list-side feed of new creations without Reddit API access; the userscript is the sole cover for them, and it is desktop-only. The phone relies on the account-level 18+ setting for new communities. If Reddit credentials are ever added, the every-6-hours polling of the new-subreddit feed resumes (the feed exposes only the newest ~1000 entries, so cadence gives roughly 4000 per day of headroom, and the saturation warning in the Actions log is the trigger to add cron entries).
- Verification authority is a third party in the default path. Postpone republishes Reddit's flag with a `lastRefreshedFromReddit` timestamp; measured 2026-07-18, 62 percent of their catalog re-checked within 24 hours and 88 percent within 7 days, with all spot checks correct. Trigger: refresh timestamps aging badly, flag mismatches against what Reddit's own pages show, or the endpoint changing shape. The Reddit path re-enables automatically via secrets.
- Userscript detection depends on Reddit's markup, which changes regularly. Five redundant rules (old Reddit interstitial, new Reddit gate, community attributes, rating meta tags, header badge) mean one breaking does not defeat the rest, and every decision is console-logged with its reason. Trigger: any slip-through or false block; fix is a rule update, and ALLOW covers false blocks immediately.
- Drain pace in the default path. Directory candidates outside Postpone's bulk list verify at `per_run_lookup_budget` (300) per run, so the NSFWDog long tail takes a few weeks to fully verify after bootstrap. The top ~30k are instant via the bulk call. Trigger: if the queued count in the run log stays large past a month, raise the budget modestly while respecting the politeness QPM.
- Back-catalog completeness is unproven. Reddit listings cap around 1000 entries, so historical coverage rests on the bootstrap sweep plus seeds. The first bootstrap run's counts will show how big the verified catalog actually is; judge coverage then, not now.
- Unauthenticated mode is a smoke-test path only. It is slow by design and datacenter IPs are often blocked by Reddit; never rely on it in Actions.
- Search sweep recall is unmeasured (applies only when Reddit credentials exist). `include_over_18=on` behavior with app-only auth is assumed correct; if bootstrap yields suspiciously few NSFW results relative to NSFWDog-sourced ones, investigate before trusting the sweep.

## Parked ideas
Considered and set aside, with the reason, so they are not re-litigated from scratch.
- Regex-packed Chrome rules (many names per rule to beat the MV3 cap), parked because per-rule memory limits make it fragile and hard to debug; the subscriber-sorted trim is predictable.
- Self-hosted MITM proxy for path filtering across every app and browser, parked because certificate installs, cert-pinned app breakage, and an always-on host are heavy for the gain.
- Private repo with delivery via secret gist, parked because the public raw URL is simpler and stable; revisit only if the public repo becomes a problem.
- Postpone pagination beyond the bulk cap, parked because their endpoint 502s on larger requests and the result set is already down to single-subscriber communities well before the cap.
- Paid third-party Reddit data proxies, parked because per-call fees and a commercial middleman are overkill for a personal filter list while the free mirror carries the same field.
- Self-hosted GitHub runner using Noah's logged-in Reddit session, parked because it risks the account, requires a machine that never sleeps, and the userscript covers the same gap without either cost.
