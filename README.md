# subgate

_One line: builds auto-updating browser filter lists that block NSFW subreddits, using Reddit's own 18+ flags as the authority, for Noah's own devices._

## What it does
Reddit marks every adult community with an internal 18+ flag. subgate reads those flags through Postpone's public mirror (a Reddit scheduling service with approved API access that republishes the flag, with a freshness timestamp), collects extra candidate names from a second directory and from anything you paste into `manual_seeds.txt`, and publishes the confirmed 18+ communities as two block lists. Your ad blocker subscribes to those lists by URL and re-downloads them daily, so browsing `reddit.com/r/<anything on the list>` simply gets blocked, while the rest of Reddit works normally.

No Reddit account or API key is needed. Reddit closed self-service API signup, so subgate reads the answers from a service that already has access. Nothing ships on a directory's word alone: Reddit's own flag (via the mirror) decides, with `force_block.txt` as your one manual override for unflagged borderline communities.

The lists cover the back catalog. Brand new communities are covered by the included browser userscript (`subgate.user.js`), which reads Reddit's own 18+ signals the moment a page loads and blocks it, so a subreddit created five minutes ago is caught without any list knowing about it.

## Setup
Fastest path: run `setup.ps1` (Windows) or `setup.sh` (Git Bash, macOS, Linux) from the extracted folder. It creates the repo, uploads everything, sets the workflow permission, and starts the first run. See SETUP.md for that plus a no-install browser path and troubleshooting. Never paste a GitHub token into a script or a chat; the setup scripts sign you in through your own browser.

Manual steps, if you prefer to do it yourself:
1. Prerequisites: a GitHub account, Firefox with uBlock Origin, Chrome with the AdGuard extension (MV3), and a userscript manager (Violentmonkey or Tampermonkey) in each browser. Python 3.12 only if you want to run it locally; the automation runs on GitHub's machines.
2. Create a **public** repo named `subgate` (public is required so the list URLs work without login) and upload the contents of this folder. Rename `gitignore.txt` to `.gitignore`.
3. First run: Actions tab, subgate workflow, "Run workflow", set mode to **bootstrap**, run it once. The core catalog (about 30k confirmed communities) lands in the first minutes via one bulk request; the NSFWDog crawl adds roughly half an hour. It commits `subgate_state.json`, `subgate_full.txt`, and `subgate_chrome.txt`.
4. After that the every-6-hours schedule keeps everything fresh on its own. Directory candidates the bulk request does not cover get verified at 300 names per run, so the long tail fills in automatically over the first few weeks; no action needed.
5. Optional, only if Reddit ever approves you for API access: add `REDDIT_CLIENT_ID` and `REDDIT_CLIENT_SECRET` (and optionally `REDDIT_USERNAME`) as repo Actions secrets. subgate detects them and switches to verifying against Reddit directly, which also restores new-subreddit discovery and the bootstrap search sweep. Nothing breaks if you never do this.

## Subscribing your browsers
The raw URLs (replace OWNER with your GitHub username):
- Full list: `https://raw.githubusercontent.com/OWNER/subgate/main/subgate_full.txt`
- Chrome list: `https://raw.githubusercontent.com/OWNER/subgate/main/subgate_chrome.txt`

Firefox: uBlock Origin dashboard, Filter lists tab, scroll to Import, paste the full list URL, Apply changes.

Chrome: AdGuard extension settings, Filters, Custom filters, Add custom filter, paste the Chrome list URL. If AdGuard warns about rule limits, lower `chrome_max_rules` in `sources.yaml`.

## Installing the userscript
This is the piece that catches brand new subreddits, so do not skip it.

1. Install a userscript manager: Violentmonkey (Firefox) or Tampermonkey (Chrome). On Chrome, also turn on Developer mode at `chrome://extensions`, which Tampermonkey needs to run userscripts.
2. Open `https://raw.githubusercontent.com/OWNER/subgate/main/subgate.user.js` in that browser; the manager will offer to install it.
3. The top of the script has an `ALLOW` list (support communities like r/pornfree are pre-listed) and a `VERBOSE` switch. Leave `VERBOSE` on for the first week: every allow or block decision is logged to the browser console with its reason, so if anything misfires you can send the log line back and the rule gets fixed.

iPhone note: Chrome on iOS has no extension platform, so neither the lists nor the userscript can run there. On the phone, the working layers are your Reddit account's 18+ setting (server side, covers every browser and the app) and NextDNS (make sure `old.reddit.com` is on the denylist). A Safari-based phone layer is pre-planned as Phase 3 in FUTURE.md if you ever want it.

## What each part shows
- `subgate_full.txt` and `subgate_chrome.txt`: the published lists. The header comments show entry count and build time.
- `subgate_state.json`: the catalog with every name ever verified, its status (nsfw, sfw, gone), subscriber count, sources, and timestamps. The workflow maintains it; you never edit it.
- `subgate.user.js`: the in-browser check for brand new communities. Install once per desktop browser; it updates when you reinstall from the raw URL after a version bump.
- `manual_seeds.txt`: paste any text containing subreddit names or URLs; next run extracts and verifies them. Optional: both big directories are already automated, so this is only for one-off names you come across yourself.
- `force_block.txt`: names that ship even without Reddit's flag. Your override for unflagged borderline subs.
- `sources.yaml`: verification provider, rate limits, caps, schedule, and seed sources, all commented.
- The Actions log for each run prints a report line: bulk confirmations, drain progress, list sizes, and how many the Chrome cap trimmed.

## Secrets and configuration
No secrets are required. The optional Reddit credentials above only exist for the day Reddit approves API access, if ever. Never commit keys. Configuration lives in `sources.yaml`; its limits are guards, see HANDOFF.md before changing them.

## Version
Semver via git tags. Current: v0.2.1. The changelog lives in HANDOFF.md.
