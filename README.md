# subgate

_One line: builds auto-updating browser filter lists that block NSFW subreddits, using Reddit's own 18+ flags as the authority, for Noah's own devices._

## What it does
Reddit marks every adult community with an internal 18+ flag. subgate collects candidate subreddit names (from two directory sites, from anything you paste into `manual_seeds.txt`, and from Reddit's own new-subreddit feed), asks Reddit which of them are flagged 18+, and publishes the confirmed ones as two block lists. Your ad blocker subscribes to those lists by URL and re-downloads them daily, so browsing `reddit.com/r/<anything on the list>` simply gets blocked, while the rest of Reddit works normally. Nothing ships on a directory's word alone: Reddit's flag decides, with `force_block.txt` as your one manual override for unflagged borderline communities.

## Setup
1. Prerequisites: a GitHub account, a Reddit account, Firefox with uBlock Origin, and Chrome with the AdGuard extension (MV3). Python 3.12 only if you want to run it locally; the automation runs on GitHub's machines.
2. Create a **public** repo named `subgate` (public is required so the list URLs work without login) and upload the contents of this folder. Rename `gitignore.txt` to `.gitignore`.
3. Create the Reddit API app: reddit.com/prefs/apps, "create another app", type **script**, name `subgate`, redirect uri `http://localhost:8080` (required but unused). Copy the client id (the short string under the app name) and the secret.
4. In the repo: Settings, Secrets and variables, Actions. Add `REDDIT_CLIENT_ID` and `REDDIT_CLIENT_SECRET`. Optionally `REDDIT_USERNAME` (your username, used only inside the API user agent string, which Reddit likes).
5. First run: Actions tab, subgate workflow, "Run workflow", set mode to **bootstrap**, run it once. This does the deep harvest (roughly 45 to 90 minutes) and commits `subgate_state.json`, `subgate_full.txt`, and `subgate_chrome.txt`. After that the every-6-hours schedule keeps everything fresh on its own.
6. Automatic runs: the GitHub Actions workflow runs every 6 hours (so newly created subreddits cannot roll out of Reddit's new-subs window unseen) and commits the updated state back to the repo. The heavier NSFWDog crawl happens on one Sunday run per week.

## Subscribing your browsers
The raw URLs (replace OWNER with your GitHub username):
- Full list: `https://raw.githubusercontent.com/OWNER/subgate/main/subgate_full.txt`
- Chrome list: `https://raw.githubusercontent.com/OWNER/subgate/main/subgate_chrome.txt`

Firefox: uBlock Origin dashboard, Filter lists tab, scroll to Import, paste the full list URL, Apply changes.

Chrome: AdGuard extension settings, Filters, Custom filters, Add custom filter, paste the Chrome list URL. If AdGuard warns about rule limits, lower `chrome_max_rules` in `sources.yaml`.

iPhone note: Chrome on iOS has no extension platform, so no list can load there. On the phone, the working layers are your Reddit account's 18+ setting (server side, covers every browser and the app) and NextDNS (make sure `old.reddit.com` is on the denylist). A Safari-based phone layer is pre-planned as Phase 3 in FUTURE.md if you ever want it.

## What each part shows
- `subgate_full.txt` and `subgate_chrome.txt`: the published lists. The header comments show entry count and build time.
- `subgate_state.json`: the catalog with every name ever verified, its status (nsfw, sfw, gone), subscriber count, sources, and timestamps. The workflow maintains it; you never edit it.
- `manual_seeds.txt`: paste any text containing subreddit names or URLs; next run extracts and verifies them. Optional: both big directories are already automated, so this is only for one-off names you come across yourself.
- `force_block.txt`: names that ship even without Reddit's flag. Your override for unflagged borderline subs.
- `sources.yaml`: rate limits, caps, schedule, and seed sources, all commented.
- The Actions log for each run prints a report line: how many names attempted, resolved, list sizes, and how many the Chrome cap trimmed.

## Secrets and configuration
Secrets live only in GitHub repo secrets: `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`, optional `REDDIT_USERNAME`. Never commit keys. Configuration lives in `sources.yaml`; its limits are guards, see HANDOFF.md before changing them.

## Version
Semver via git tags. Current: v0.1.2. The changelog lives in HANDOFF.md.
