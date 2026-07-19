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

### Phase 4: Standalone extension
Status: shipped in v0.4.0 as `extension/` (load-unpacked preview). Replaces the uBlock list plus userscript pairing on desktop with one install.

### Phase 5 (v1.0.0): Store-ready free release
Gate: Noah runs the v0.4.x extension as his daily driver for 2 weeks with no critical miss (a critical miss is an NSFW community rendering with media visible).
- Icons and store listing assets, a proper privacy policy stating no data collection, Firefox signing through AMO, Chrome Web Store listing (one-time 5 dollar developer fee), an onboarding page after install, and migration notes for retiring the uBlock list and userscript on desktop. Free, with a visible tip jar. Launch post drafted for r/pornfree and r/NoFap; that post doubles as market validation.

### Phase 6 (v2.0.0): Supporter tier
Gate: pre-registered before launch: the validation post gathers at least 10 unprompted "I would pay" replies OR the free extension passes 500 installs. Do not build paid features on hope.
- One-time 5 to 10 dollar unlock through a third-party license service (ExtensionPay or Lemon Squeezy; the Chrome Web Store cannot take payments). Gated features are conveniences only: allowlist manager UI, strict-mode scheduling, custom block page, personal stats. The core blocking stays free forever; charging someone mid-relapse to keep protection running is the one line this project does not cross.

## Known weaknesses / watch items
Honest list of what is fragile, approximated, or unproven. Not bugs to fix now, but things to watch.
- Unflagged subreddits slip through. The flag depends on moderators self-labeling, and Reddit's enforcement of labeling is imperfect. Mitigations: `force_block.txt` for anything Noah encounters, the NextDNS domain layer beneath, and Phase 2 if the miss rate proves real. Trigger for action: repeated misses on communities that are obviously 18+ but unflagged.
- Chrome trims the long tail. `chrome_max_rules` (20000) keeps only the biggest subs on Chrome; the run log prints the trimmed count. Trigger: if trimmed count grows large and Chrome is the primary browser, revisit the cap against AdGuard's observed ceiling.
- Directory dependency for the back catalog. Both NSFWDog and Postpone API shapes were verified 2026-07-18 but can change or vanish; the guard means the catalog persists regardless, only freshness of directory-sourced candidates degrades. Running two independent directories is the mitigation: a sampled overlap check showed each still contributes names the other lacks. Trigger: scraper failure warnings in the Actions log for 2+ consecutive weeks.
- Brand new subreddits are invisible to the lists in the default (no credentials) path. There is no list-side feed of new creations without Reddit API access; the userscript is the sole cover for them, and it is desktop-only. The phone relies on the account-level 18+ setting for new communities. If Reddit credentials are ever added, the every-6-hours polling of the new-subreddit feed resumes (the feed exposes only the newest ~1000 entries, so cadence gives roughly 4000 per day of headroom, and the saturation warning in the Actions log is the trigger to add cron entries).
- Verification authority is a third party in the default path. Postpone republishes Reddit's flag with a `lastRefreshedFromReddit` timestamp; measured 2026-07-18, 62 percent of their catalog re-checked within 24 hours and 88 percent within 7 days, with all spot checks correct. Trigger: refresh timestamps aging badly, flag mismatches against what Reddit's own pages show, or the endpoint changing shape. The Reddit path re-enables automatically via secrets.
- Userscript markup detection is now only the offline tiebreaker (v0.3.0); the primary verdicts come from the owner's list and the mirror, which do not move when Reddit's DOM does. Residual watch: GM_info install-URL derivation failed live in Violentmonkey, so since v0.3.1 the workflow bakes the repo URL into the committed userscript; the GM_info path remains only as a bonus for odd installs, and the mirror check adds one cached network round trip for names not on the list. Old trigger still stands for the tiebreaker rules: Five redundant rules (old Reddit interstitial, new Reddit gate, community attributes, rating meta tags, header badge) mean one breaking does not defeat the rest, and every decision is console-logged with its reason. Trigger: any slip-through or false block; fix is a rule update, and ALLOW covers false blocks immediately.
- Drain pace in the default path. Directory candidates outside Postpone's bulk list verify at `per_run_lookup_budget` (300) per run, so the NSFWDog long tail takes a few weeks to fully verify after bootstrap. The top ~30k are instant via the bulk call. Trigger: if the queued count in the run log stays large past a month, raise the budget modestly while respecting the politeness QPM.
- Back-catalog completeness is unproven. Reddit listings cap around 1000 entries, so historical coverage rests on the bootstrap sweep plus seeds. The first bootstrap run's counts will show how big the verified catalog actually is; judge coverage then, not now.
- Unauthenticated mode is a smoke-test path only. It is slow by design and datacenter IPs are often blocked by Reddit; never rely on it in Actions.
- The extension is untested in a real browser: this sandbox has no Chrome or Firefox, so v0.4.0 is validated by syntax checks, structural tests, and design review only. First load-unpacked run on Noah's machine is the real test; Firefox's dynamic-rule ceiling may be lower than Chrome's 30k, which the chunked-add fallback handles by stopping gracefully. Trigger: any console error on load or a rule count far below the list size in the options page.
- AdGuard MV3 handling of `$all` on the Chrome list is unverified. uBlock honors it (confirmed by design intent and the live fix); if AdGuard's MV3 converter warns on import or drops the modifier, the fallback is emitting paired rules (plain plus `$document`) at the cost of halving the Chrome cap. Trigger: any import warning or a direct navigation loading on Chrome.
- Search sweep recall is unmeasured (applies only when Reddit credentials exist). `include_over_18=on` behavior with app-only auth is assumed correct; if bootstrap yields suspiciously few NSFW results relative to NSFWDog-sourced ones, investigate before trusting the sweep.

## Parked ideas
Considered and set aside, with the reason, so they are not re-litigated from scratch.
- Regex-packed Chrome rules (many names per rule to beat the MV3 cap), parked because per-rule memory limits make it fragile and hard to debug; the subscriber-sorted trim is predictable.
- Self-hosted MITM proxy for path filtering across every app and browser, parked because certificate installs, cert-pinned app breakage, and an always-on host are heavy for the gain.
- Private repo with delivery via secret gist, parked because the public raw URL is simpler and stable; revisit only if the public repo becomes a problem.
- Postpone pagination beyond the bulk cap, parked because their endpoint 502s on larger requests and the result set is already down to single-subscriber communities well before the cap.
- Paid third-party Reddit data proxies, parked because per-call fees and a commercial middleman are overkill for a personal filter list while the free mirror carries the same field.
- Self-hosted GitHub runner using Noah's logged-in Reddit session, parked because it risks the account, requires a machine that never sleeps, and the userscript covers the same gap without either cost.
